"""Lanza OpenCode (`opencode run`) sobre el repo de una tarea, en Docker como Hermes.

Imagen `skynet-bench/opencode` (docker-opencode/Dockerfile). Contenedor nuevo por tarea con el repo en
/workspace; el modelo es el llama-server de Windows (host.docker.internal). Permisos de editar y ejecutar
concedidos (no hay nadie delante). En las tareas con Internet recibe el MCP `internet` de Skynet, el mismo
buscador que usan los otros dos agentes.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

IMAGE = "skynet-bench/opencode:latest"
DOCKER = r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
SKYNET = Path(__file__).resolve().parents[2]


def config(url: str, contexto: int, internet: bool) -> dict:
    port = url.rsplit(":", 1)[1]
    cfg: dict = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "share": "disabled",
        "model": "llamacpp/local",
        "provider": {"llamacpp": {
            "npm": "@ai-sdk/openai-compatible", "name": "llama.cpp",
            "options": {"baseURL": f"http://host.docker.internal:{port}/v1", "apiKey": "local"},
            "models": {"local": {"name": "local", "tool_call": True,
                                 "limit": {"context": contexto, "output": 8192}}},
        }},
        "permission": {"edit": "allow", "bash": "allow", "webfetch": "allow"},
    }
    if internet:
        cfg["mcp"] = {"internet": {"type": "local", "command": ["python", "-m", "skynet_tools.internet"],
                                   "enabled": True}}
    return cfg


def run(task: dict, repo: Path, home: Path, url: str, contexto: int, max_turns: int, limite: int,
        log_path: Path) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    name = f"skb-oc-{int(time.time())}-{task['name'].replace('_', '-')}"
    cfg = json.dumps(config(url, contexto, bool(task.get("internet"))))
    cmd = [DOCKER, "run", "--rm", "--name", name, "-v", f"{repo}:/workspace",
           "-v", f"{SKYNET / 'skynet_tools'}:/skynet/skynet_tools:ro", "-e", f"OPENCODE_CONFIG_CONTENT={cfg}",
           IMAGE, "run", "--format", "json", "--auto", task["prompt"]]
    tools, final, estado, tipos = 0, "", "completado", {}
    with open(log_path, "w", encoding="utf-8") as log:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL, text=True,
                             encoding="utf-8", errors="replace")
        t0 = time.monotonic()
        for line in p.stdout:
            log.write(line)
            if time.monotonic() - t0 > limite:
                subprocess.run([DOCKER, "kill", name], capture_output=True)
                estado = "limite_tiempo"
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = str(ev.get("type", "")) if isinstance(ev, dict) else ""
            tipos[kind] = tipos.get(kind, 0) + 1
            if "tool" in kind:
                tools += 1
            part = ev.get("part") if isinstance(ev, dict) else None
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                final = part["text"]
        try:
            p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            subprocess.run([DOCKER, "kill", name], capture_output=True)
            p.kill()
    if estado == "completado" and p.returncode not in (0, None):
        estado = f"exit_{p.returncode}"
    return {"estado": estado, "turnos": tipos.get("step_finish", 0), "herramientas": tools,
            "error": None if estado == "completado" else estado, "respuesta": final[:800], "eventos": tipos}
