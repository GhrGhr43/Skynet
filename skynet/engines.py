"""Motores locales (LM Studio, llama-server y procesos como Hermes): saber si están
encendidos, encenderlos y apagarlos.

Los que usan la GPU (16 GB) se excluyen: encender uno apaga los demás con `gpu = true`. La configuración vive
en config/skynet.toml ([motores.*]); cada motor sirve a un perfil de router.toml del mismo nombre.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EngineSpec:
    nombre: str              # = perfil de router.toml que sirve
    tipo: str                # "lmstudio" | "llamacpp" | "proceso"
    url: str                 # base OpenAI, p. ej. http://127.0.0.1:1234/v1
    modelo: str = ""         # LM Studio: clave del modelo a cargar
    contexto: int = 0
    exe: str = ""            # llamacpp: llama-server.exe; proceso: ejecutable
    args: list[str] = field(default_factory=list)  # llamacpp: flags extra; proceso: argumentos
    env: dict[str, str] = field(default_factory=dict)  # proceso: variables de entorno extra
    salud: str = ""          # URL que devuelve {"status": "ok"} cuando está listo (si no, url + /models)
    firma: str = ""          # proceso: texto de su línea de comandos para apagarlo
    parar: list[str] = field(default_factory=list)  # proceso: comando para apagarlo (p. ej. un contenedor Docker)
    gpu: bool = True         # False = no compite por la GPU (no apaga ni es apagado por otros)
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
        if s.salud:
            return (_get_json(s.salud) or {}).get("status") == "ok"
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

    # --- modelo del motor local -----------------------------------------
    def set_local_model(self, name: str, local: Any) -> None:
        """Cambia el GGUF del motor `name` (objeto modelos_locales.Local); no lo reinicia."""
        s = self.specs[name]
        s.modelo, s.args = str(local.ruta), local.args()

    # --- encender / apagar ----------------------------------------------
    def start(self, name: str, wait_s: float = 360) -> str:
        s = self.specs[name]
        for other, o in self.specs.items():
            if other != name and s.gpu and o.gpu and self.is_on(other):
                self.stop(other)
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
        if s.tipo == "llamacpp":
            return self._start_llamacpp(s, wait_s)
        if s.tipo == "proceso":
            if self.is_on(name):
                return f"{name} ya estaba encendido"
            return self._spawn(s, [os.path.expandvars(s.exe), *[os.path.expandvars(a) for a in s.args]],
                               s.salud, wait_s, {k: os.path.expandvars(v) for k, v in s.env.items()})
        raise ValueError(f"Tipo de motor desconocido: {s.tipo}")

    def _start_llamacpp(self, s: EngineSpec, wait_s: float) -> str:
        # llama-server directo (el que trae LM Studio): permite FA, KV q8_0 y MTP, que `lms load` no expone
        if self.is_on(s.nombre):
            return f"{s.nombre} ya estaba encendido"
        port = s.url.rsplit(":", 1)[1].split("/")[0]
        args = [os.path.expandvars(s.exe), "-m", os.path.expandvars(s.modelo), "--port", port,
                "--alias", s.nombre, *s.args]
        if s.contexto:
            args += ["-c", str(s.contexto)]
        health = s.url.rstrip("/").removesuffix("/v1") + "/health"
        try:
            return self._spawn(s, args, health, wait_s)
        except RuntimeError:
            if "draft-mtp" not in args:
                raise
            i = args.index("--spec-type")   # el GGUF no trae capas MTP: reintento sin ellas
            return self._spawn(s, args[:i] + args[i + 2:], health, wait_s)

    def _spawn(self, s: EngineSpec, args: list[str], health: str, wait_s: float,
               env: dict[str, str] | None = None) -> str:
        """Lanza un servidor desacoplado de Skynet y espera a que `health` diga ok."""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        logname = f"{s.nombre}.log"
        log = open(self.logs_dir / logname, "a", encoding="utf-8")
        flags = NO_WINDOW | (subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                creationflags=flags, env={**os.environ, **(env or {})})
        log.close()
        end = time.monotonic() + wait_s
        while time.monotonic() < end:
            if proc.poll() is not None:
                raise RuntimeError(f"{s.nombre} se cerró al arrancar (mira data/logs/{logname})")
            if (_get_json(health, timeout=2) or {}).get("status") == "ok":
                return f"{s.nombre} encendido"
            time.sleep(2)
        raise RuntimeError(f"{s.nombre} no respondió a tiempo (mira data/logs/{logname})")

    def stop(self, name: str) -> str:
        s = self.specs[name]
        if s.tipo == "llamacpp":
            # solo el llama-server de este puerto: puede haber otro de pruebas (bench/) en otro
            port = s.url.rsplit(":", 1)[1].split("/")[0]
            ps = ("Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | Where-Object { "
                  f"$_.CommandLine -like '*--port {port} *' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                           creationflags=NO_WINDOW)
            return f"{name} apagado"
        if s.tipo == "proceso" and s.parar:
            subprocess.run([os.path.expandvars(a) for a in s.parar], capture_output=True, timeout=120,
                           creationflags=NO_WINDOW)
            return f"{name} apagado"
        if s.tipo == "proceso":
            # todo proceso cuya línea de comandos lleve la firma (el servidor y sus hijos)
            ps = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -like "
                  f"'*{s.firma}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                           creationflags=NO_WINDOW)
            return f"{name} apagado"
        if s.tipo == "lmstudio":
            lms = _lms()
            if lms:
                subprocess.run([lms, "unload", "--all"], capture_output=True, timeout=60, creationflags=NO_WINDOW)
            return "LM Studio descargado"
        raise ValueError(f"Tipo de motor desconocido: {s.tipo}")


def load_engines(raw: dict[str, Any], logs_dir: Path, home: Path | None = None) -> Engines:
    # {home} = carpeta de Skynet: así la config no depende de dónde esté clonado el repo. {python} = el de Skynet.
    def sub(v: Any) -> Any:
        if isinstance(v, str):
            v = v.replace("{python}", sys.executable)
            return v.replace("{home}", str(home)) if home else v
        if isinstance(v, list):
            return [sub(x) for x in v]
        if isinstance(v, dict):
            return {k: sub(x) for k, x in v.items()}
        return v

    specs = {}
    for n, e in (raw or {}).items():
        known = {k: sub(e[k]) for k in ("tipo", "url", "modelo", "contexto", "exe", "args", "env", "salud",
                                            "firma", "gpu", "parar") if k in e}
        specs[n] = EngineSpec(nombre=n, **known)
    eng = Engines(specs, logs_dir)
    if "local" in specs and specs["local"].tipo == "llamacpp":  # modelo elegido en Ajustes
        from . import modelos_locales as ml

        sel = ml.elegido(logs_dir.parent)
        if sel:
            hit = next((m for m in ml.buscar() if m.nombre == sel), None)
            if hit:
                eng.set_local_model("local", hit)
    return eng
