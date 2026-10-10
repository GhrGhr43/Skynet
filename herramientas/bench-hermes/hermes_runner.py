"""Lanza Hermes en modo una sola petición sobre el repo de una tarea y resume lo que hizo.

Hermes va entero en Linux dentro de Docker (imagen `skynet-bench/hermes`, ver docker/Dockerfile): en
Windows nativo sus herramientas de archivos traducen mal las rutas relativas cuando los comandos van
en Docker, y Linux es su plataforma recomendada. Cada ejecución es un contenedor nuevo con dos
carpetas montadas: el repo en /workspace y unos datos de Hermes vacíos en /opt/data (su arranque
pone sus skills de serie; sin memoria ni sesiones de tareas anteriores). El modelo es el
llama-server de Windows, al que llega por host.docker.internal.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

IMAGE = os.environ.get("SKYNET_BENCH_HERMES_IMAGE", "skynet-bench/hermes:latest")
DOCKER = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"


def config(url: str, contexto: int, max_turns: int) -> dict:
    port = url.rsplit(":", 1)[1]
    return {
        "model": {"provider": "custom", "base_url": f"http://host.docker.internal:{port}/v1", "api_key": "local",
                  "default": "local", "context_length": contexto},
        "agent": {"max_turns": max_turns},
        "terminal": {"backend": "local", "cwd": "/workspace", "timeout": 180},
    }


def run(task: dict, repo: Path, home: Path, url: str, contexto: int, max_turns: int, limite: int,
        log_path: Path) -> dict:
    data = home / "hermes-data"
    data.mkdir(parents=True, exist_ok=True)
    # JSON es YAML válido: sin depender de PyYAML en el venv de Skynet.
    (data / "config.yaml").write_text(json.dumps(config(url, contexto, max_turns), indent=2), encoding="utf-8")
    (data / "peticion.txt").write_text(task["prompt"], encoding="utf-8")
    name = f"skb-{int(time.time())}-{task['name'].replace('_', '-')}"
    cmd = [DOCKER, "run", "--rm", "--name", name, "-v", f"{repo}:/workspace", "-v", f"{data}:/opt/data",
           "-w", "/workspace", IMAGE, "chat", "--query-file", "/opt/data/peticion.txt", "--yolo",
           "--max-turns", str(max_turns), "--format", "stream-json"]
    tools = turns = 0
    final, exit_code, estado, tokens = "", None, "completado", {}
    with open(log_path, "w", encoding="utf-8") as log:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL, text=True,
                             encoding="utf-8", errors="replace")
        t0 = time.monotonic()
        for line in p.stdout:  # una línea JSON por evento; el resto es el arranque del contenedor
            log.write(line)
            if time.monotonic() - t0 > limite:
                subprocess.run([DOCKER, "kill", name], capture_output=True)
                estado = "limite_tiempo"
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type") if isinstance(ev, dict) else None
            if kind == "tool_use":
                tools += 1
            elif kind == "text":
                turns += 1
            elif kind == "result":
                exit_code = ev.get("exit_code")
                final = ev.get("text") or final
                tokens = ev.get("tokens") or {}
        try:
            p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            subprocess.run([DOCKER, "kill", name], capture_output=True)
            p.kill()
    if exit_code is None:
        exit_code = p.returncode
    if estado == "completado" and exit_code not in (0, None):
        estado = f"exit_{exit_code}"
    return {"estado": estado, "turnos": turns, "herramientas": tools,
            "error": None if estado == "completado" else estado, "respuesta": str(final)[:800],
            "tokens_hermes": tokens}
