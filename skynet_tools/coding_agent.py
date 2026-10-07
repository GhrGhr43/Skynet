"""Servidor MCP `coding_agent`: envuelve agente-godot sin modificarlo (decisión D5).

Herramientas:
  start_task(repo, horas)  lanza `sistema\\noche.ps1 -Juego <repo> -Horas <h>` en segundo plano
  status(repo)             si sigue en marcha + .agente\\ESTADO.md + final de agente.log
  stop_task(repo)          detiene el proceso (noche.ps1 retoma lo cortado en el siguiente arranque)
  history(repo, n)         últimas filas de HISTORIAL-LOCAL.csv de ese juego

El trabajo concreto lo define el PLAN.md del juego (tareas [local]), como en agente-godot.
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("coding_agent", instructions="Lanza y vigila el agente-godot (programador local con Qwen).")
AGENTE: Path = Path.home() / "Documents" / "agente-godot"
PID_FILE = Path(".agente") / "skynet-pid.txt"


def _repo(repo: str) -> Path:
    p = Path(repo).resolve()
    if not (p / "PLAN.md").exists():
        raise ToolError(f"{p} no parece un juego de agente-godot (falta PLAN.md)")
    return p


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _read_pid(p: Path) -> int | None:
    f = p / PID_FILE
    try:
        return int(f.read_text().strip())
    except (OSError, ValueError):
        return None


@mcp.tool()
def start_task(repo: str, horas: float = 2.0) -> str:
    """Lanza el trabajador de agente-godot (noche.ps1) sobre un juego durante `horas` horas."""
    p = _repo(repo)
    pid = _read_pid(p)
    if pid and _pid_alive(pid):
        return f"Ya está en marcha (pid {pid})"
    script = AGENTE / "sistema" / "noche.ps1"
    if not script.exists():
        raise ToolError(f"No encuentro {script}")
    log = open(p / "agente-skynet.log", "a", encoding="utf-8")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Juego", str(p), "-Horas", str(horas)],
        stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=str(p), creationflags=flags,
    )
    log.close()
    (p / PID_FILE).parent.mkdir(exist_ok=True)
    (p / PID_FILE).write_text(str(proc.pid))
    return f"Lanzado noche.ps1 durante {horas} h (pid {proc.pid})"


@mcp.tool()
def status(repo: str) -> str:
    """Estado del trabajador de agente-godot en un juego."""
    p = _repo(repo)
    pid = _read_pid(p)
    alive = bool(pid and _pid_alive(pid))
    out = [f"en_marcha: {'si' if alive else 'no'}" + (f" (pid {pid})" if pid else "")]
    estado = p / ".agente" / "ESTADO.md"
    if estado.exists():
        out.append(estado.read_text(encoding="utf-8", errors="replace").strip())
    log = p / "agente.log"
    if log.exists():
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
        out.append("--- agente.log ---\n" + "\n".join(lines))
    return "\n".join(out)


@mcp.tool()
def stop_task(repo: str) -> str:
    """Detiene el trabajador de agente-godot de un juego (retoma lo cortado la próxima vez)."""
    p = _repo(repo)
    pid = _read_pid(p)
    if not pid or not _pid_alive(pid):
        return "No estaba en marcha"
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        os.kill(pid, 15)
    return f"Detenido (pid {pid})"


@mcp.tool()
def history(repo: str, n: int = 20) -> str:
    """Últimas `n` tareas que hizo el agente local en ese juego (de HISTORIAL-LOCAL.csv)."""
    p = _repo(repo)
    f = AGENTE / "HISTORIAL-LOCAL.csv"
    if not f.exists():
        return "Sin historial"
    rows = list(csv.DictReader(io.StringIO(f.read_text(encoding="utf-8", errors="replace")), delimiter=";"))
    mine = [r for r in rows if r.get("juego") == p.name][-max(1, n):]
    if not mine:
        return "Sin tareas registradas para este juego"
    return "\n".join(f"{r['fecha']} {r['id']} {r['tipo']} {r['resultado']} ({r['minutos']} min, {r['modelo']})"
                     for r in mine)


def main() -> None:
    global AGENTE
    ap = argparse.ArgumentParser(description="Servidor MCP coding_agent (agente-godot)")
    ap.add_argument("--agente-godot", default=str(AGENTE))
    AGENTE = Path(ap.parse_args().agente_godot).resolve()
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
