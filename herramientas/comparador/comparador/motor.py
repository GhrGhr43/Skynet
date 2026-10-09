"""Arranca cada modelo GGUF con el llama-server que trae LM Studio (Vulkan), uno a la vez.

Así no hace falta tener LM Studio abierto ni cargar nada a mano, y cada modelo va con los
ajustes que mejor le sientan en una GPU de 16 GB (los del benchmark de Skynet):
- Todos: Flash Attention, KV cache q8_0, 32K de contexto, un solo hueco (-np 1).
- Qwen3.5/3.6/3.8 densos: MTP integrado (--spec-type draft-mtp); si el GGUF no lo trae, se reintenta sin él.
- MoE (A3B, Flash-Next...): expertos en la RAM (--n-cpu-moe). Si el archivo es más grande que
  VRAM + RAM, el resto se lee del disco (mmap): funciona, pero lento.
- Si hay un mmproj-*.gguf en la misma carpeta, se carga y el modelo puede ver imágenes.
Nada de esto toca la tarjeta más allá de lo que hace LM Studio: sin overclock ni voltajes.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PUERTO = 8091   # distinto del 8090 de Skynet y del 1234 de LM Studio
HOME = Path(os.environ.get("USERPROFILE") or Path.home())
CARPETAS = [HOME / ".lmstudio" / "models", Path(r"C:\Strata\Strata-data\models")]
NO_CHAT = ("embed", "mmproj", "mtp-", "reranker", "whisper")


@dataclass
class GGUF:
    nombre: str
    ruta: Path
    gb: float
    mmproj: Path | None = None
    moe: bool = False
    mtp: bool = False
    args: list[str] = field(default_factory=list)   # ajustes extra de modelos.toml

    def descripcion(self) -> str:
        t = [f"{self.gb:.1f} GB"]
        if self.moe:
            t.append("MoE, expertos en RAM")
        if self.mtp:
            t.append("MTP")
        if self.mmproj:
            t.append("visión")
        return ", ".join(t)


def buscar(extra: list[str] | None = None) -> list[GGUF]:
    out = []
    for base in [*CARPETAS, *map(Path, extra or [])]:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.gguf")):
            low = p.name.lower()
            if any(k in low for k in NO_CHAT):
                continue
            m = re.search(r"-(\d{5})-of-(\d{5})\.gguf$", p.name)
            if m and m.group(1) != "00001":
                continue                       # solo la primera parte de un modelo partido
            partes = sorted(p.parent.glob(re.sub(r"-\d{5}-of-", "-*-of-", p.name))) if m else [p]
            gb = sum(x.stat().st_size for x in partes) / 1e9
            mm = next(iter(sorted(p.parent.glob("mmproj*.gguf"))), None)
            nombre = re.sub(r"(-\d{5}-of-\d{5})?\.gguf$", "", p.name)
            moe = bool(re.search(r"-A\d+B|flash-next|moe|-\d+x\d+b", low, re.I))
            mtp = not moe and bool(re.search(r"qwen3\.[5-9]", low))
            out.append(GGUF(nombre, p, gb, mm, moe, mtp))
    return out


def llama_server() -> str | None:
    """El llama-server Vulkan más nuevo que haya instalado LM Studio."""
    cands = glob.glob(str(HOME / ".lmstudio" / "extensions" / "backends" / "llama.cpp-win-*vulkan*" / "llama-server.exe"))
    def ver(p: str) -> tuple[int, ...]:
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", Path(p).parent.name)
        return tuple(map(int, m.groups())) if m else (0,)
    return max(cands, key=ver) if cands else None


def argumentos(g: GGUF, con_mtp: bool) -> list[str]:
    a = ["-m", str(g.ruta), "--port", str(PUERTO), "--alias", g.nombre, "-c", "32768", "-fa", "on",
         "-ctk", "q8_0", "-ctv", "q8_0", "-np", "1", "--no-webui"]   # sin -ngl: llama.cpp reparte capas solo (fit) si no cabe
    if g.moe:
        # En 16 GB: el 35B-A3B rinde mejor con 13 capas de expertos en CPU (benchmark de Skynet);
        # uno mucho más grande que la VRAM, todos los expertos fuera.
        a += ["--n-cpu-moe", "13" if g.gb < 30 else "999"]
    if con_mtp:
        a += ["--spec-type", "draft-mtp"]
    if g.mmproj:
        a += ["--mmproj", str(g.mmproj)]
    return a + g.args


class Servidor:
    """Context manager: arranca el modelo, espera a que esté listo y lo para al salir."""

    def __init__(self, g: GGUF, carpeta_logs: Path, espera_s: int = 900):
        self.g, self.espera = g, espera_s
        self.log = carpeta_logs / f"{re.sub(r'[^A-Za-z0-9._-]', '_', g.nombre)}-servidor.log"
        self.proc: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{PUERTO}/v1"
        self.segundos_arranque = 0.0

    def _arrancar(self, con_mtp: bool) -> bool:
        exe = llama_server()
        if not exe:
            raise RuntimeError("No encuentro el llama-server de LM Studio (extensions/backends/*vulkan*).")
        self.log.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.log, "w", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen([exe, *argumentos(self.g, con_mtp)], stdout=f, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=flags)
        t0 = time.monotonic()
        while time.monotonic() - t0 < self.espera:
            if self.proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/health", timeout=2) as r:
                    if json.loads(r.read()).get("status") == "ok":
                        self.segundos_arranque = time.monotonic() - t0
                        return True
            except (OSError, ValueError):
                pass
            time.sleep(2)
        self.parar()
        return False

    def __enter__(self) -> "Servidor":
        if self._arrancar(self.g.mtp):
            return self
        self.parar()
        if self.g.mtp and self._arrancar(False):     # el GGUF no trae capas MTP
            self.g.mtp = False
            return self
        cola = self.log.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-6:]
        raise RuntimeError("no arranca: " + " | ".join(cola)[-400:])

    def parar(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        time.sleep(3)   # que el driver libere la VRAM antes del siguiente

    def __exit__(self, *a) -> None:
        self.parar()


def puerto_ocupado(puerto: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/v1/models", timeout=1):
            return True
    except OSError:
        return False
