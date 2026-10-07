"""Motores locales (LM Studio y Strata): saber si están encendidos, encenderlos y apagarlos.

Los dos usan la misma GPU (16 GB), así que encender uno apaga el otro. La configuración vive
en config/skynet.toml ([motores.*]); cada motor sirve a un perfil de router.toml del mismo nombre.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EngineSpec:
    nombre: str              # = perfil de router.toml que sirve
    tipo: str                # "lmstudio" | "strata"
    url: str                 # base OpenAI, p. ej. http://127.0.0.1:1234/v1
    modelo: str = ""         # LM Studio: clave del modelo a cargar
    contexto: int = 0
    carpeta: str = ""        # Strata: carpeta con serve/server.py
    config: str = ""         # Strata: strata-*.json
    extra: dict[str, Any] = field(default_factory=dict)


def _get_json(url: str, timeout: float = 3) -> Any | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)
    except Exception:
        return None


def _lms() -> str | None:
    found = shutil.which("lms")
    if found:
        return found
    p = Path.home() / ".lmstudio" / "bin" / "lms.exe"
    return str(p) if p.exists() else None


NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class Engines:
    def __init__(self, specs: dict[str, EngineSpec], logs_dir: Path):
        self.specs = specs
        self.logs_dir = logs_dir
        self.busy: set[str] = set()  # encendiéndose o apagándose ahora
        self._cache: list[dict[str, Any]] = []
        self._cached_at = 0.0

    # --- estado ----------------------------------------------------------
    def is_on(self, name: str) -> bool:
        s = self.specs[name]
        if s.tipo == "lmstudio":
            lms = _lms()
            if lms:
                r = subprocess.run([lms, "ps"], capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=15, creationflags=NO_WINDOW)
                return s.modelo.lower() in r.stdout.lower()
            return _get_json(s.url.rstrip("/") + "/models") is not None
        return _get_json(s.url.rstrip("/") + "/models") is not None

    def status(self, max_age: float = 10) -> list[dict[str, Any]]:
        """Estado con caché corta: la web lo pide en cada refresco y `lms ps` tarda."""
        now = time.monotonic()
        if now - self._cached_at > max_age:
            self._cache = [{"nombre": n, "tipo": s.tipo, "encendido": self.is_on(n)} for n, s in self.specs.items()]
            self._cached_at = now
        return [dict(x, ocupado=x["nombre"] in self.busy) for x in self._cache]

    def invalidate(self) -> None:
        self._cached_at = 0.0

    # --- encender / apagar ----------------------------------------------
    def start(self, name: str, wait_s: float = 360) -> str:
        for other in self.specs:
            if other != name and self.is_on(other):
                self.stop(other)
        s = self.specs[name]
        if s.tipo == "lmstudio":
            lms = _lms()
            if not lms:
                raise RuntimeError("No encuentro el comando lms de LM Studio")
            subprocess.run([lms, "server", "start"], capture_output=True, timeout=60, creationflags=NO_WINDOW)
            args = [lms, "load", s.modelo, "--gpu", "max", "--identifier", s.modelo, "--yes"]
            if s.contexto:
                args += ["--context-length", str(s.contexto)]
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=wait_s, creationflags=NO_WINDOW)
            if r.returncode != 0:
                raise RuntimeError(f"LM Studio no cargó el modelo: {(r.stderr or r.stdout).strip()[-300:]}")
            return f"{s.modelo} cargado en LM Studio"
        # Strata: se lanza su servidor como hace run-*.bat, desacoplado de Skynet
        folder = Path(s.carpeta)
        py = folder / ".venv" / "Scripts" / "python.exe"
        port = s.url.rsplit(":", 1)[1].split("/")[0]
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log = open(self.logs_dir / "strata.log", "a", encoding="utf-8")
        flags = NO_WINDOW | (subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        subprocess.Popen([str(py), str(folder / "serve" / "server.py"), "--engine", "strata",
                          "--config", str(folder / s.config), "--port", port],
                         cwd=str(folder), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         creationflags=flags)
        log.close()
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            if self.is_on(name):
                return "Strata encendido"
            time.sleep(3)
        raise RuntimeError("Strata no respondió a tiempo (mira data/logs/strata.log)")

    def stop(self, name: str) -> str:
        s = self.specs[name]
        if s.tipo == "lmstudio":
            lms = _lms()
            if lms:
                subprocess.run([lms, "unload", "--all"], capture_output=True, timeout=60, creationflags=NO_WINDOW)
            return "LM Studio descargado"
        # Strata: matar el proceso de su servidor (por línea de comandos)
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*serve*server.py*--engine*strata*' } "
              "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                       creationflags=NO_WINDOW)
        return "Strata apagado"


def load_engines(raw: dict[str, Any], logs_dir: Path) -> Engines:
    specs = {}
    for n, e in (raw or {}).items():
        known = {k: e[k] for k in ("tipo", "url", "modelo", "contexto", "carpeta", "config") if k in e}
        specs[n] = EngineSpec(nombre=n, **known)
    return Engines(specs, logs_dir)
