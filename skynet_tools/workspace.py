"""Servidor MCP `workspace`: archivos, búsqueda, git y comandos dentro de UN repo.

Se lanza con `python -m skynet_tools.workspace --root <repo>`. Todas las rutas son
relativas a esa raíz y nunca pueden salir de ella (defensa en profundidad: el permission
gate de Skynet ya lo comprueba antes de llamar).
"""
from __future__ import annotations

import argparse
import fnmatch
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".skynet",
                ".godot", ".mypy_cache", "dist", "build"}
SHELL_META = ("&", "|", ";", ">", "<", "`", "$(", "\n", "\r", "%")
MAX_OUTPUT = 12000

mcp = MCPServer(
    "workspace",
    instructions="Herramientas para leer, buscar, editar y probar código dentro de un único repo.",
)
ROOT: Path = Path.cwd()


def _resolve(path: str, must_exist: bool = False) -> Path:
    p = Path(path or ".")
    target = (p if p.is_absolute() else ROOT / p).resolve()
    if target != ROOT and ROOT not in target.parents:
        raise ToolError(f"Ruta fuera del repo: {path}")
    rel = target.relative_to(ROOT).parts
    if rel and rel[0] == ".git":
        raise ToolError("No se puede acceder al interior de .git")
    if must_exist and not target.exists():
        raise ToolError(f"No existe: {path}")
    return target


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix() or "."


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... [{len(text) - limit} caracteres omitidos] ...\n" + text[-half:]


def _git(*args: str, timeout: int = 60) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise ToolError(f"git {' '.join(args)} falló: {r.stderr.strip()[:2000]}")
    return r.stdout


@mcp.tool()
def read_file(path: str, offset: int = 1, limit: int = 400) -> str:
    """Lee un archivo de texto del repo. Devuelve las líneas numeradas desde `offset` (1 = primera), como máximo `limit` líneas."""
    target = _resolve(path, must_exist=True)
    if target.is_dir():
        raise ToolError(f"{path} es una carpeta; usa list_dir")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    offset = max(1, offset)
    chunk = lines[offset - 1: offset - 1 + max(1, limit)]
    body = "\n".join(f"{i:5d}| {line}" for i, line in enumerate(chunk, start=offset))
    tail = ""
    if offset - 1 + len(chunk) < len(lines):
        tail = f"\n[... {len(lines)} líneas en total; sigue con offset={offset + len(chunk)}]"
    return _clip(f"{_rel(target)} ({len(lines)} líneas)\n{body}{tail}")


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Crea o sobrescribe un archivo del repo con `content` (crea las carpetas que falten)."""
    target = _resolve(path)
    if target.is_dir():
        raise ToolError(f"{path} es una carpeta")
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8", newline="")
    return f"{'Sobrescrito' if existed else 'Creado'} {_rel(target)} ({len(content.splitlines())} líneas)"


@mcp.tool()
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
    """Reemplaza `old_text` por `new_text` en un archivo. `old_text` debe aparecer exactamente (incluidos espacios); si aparece varias veces, añade más contexto o usa replace_all=true."""
    target = _resolve(path, must_exist=True)
    text = target.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_text)
    if not old_text or count == 0:
        raise ToolError("old_text no aparece en el archivo. Léelo de nuevo con read_file y copia el texto exacto.")
    if count > 1 and not replace_all:
        raise ToolError(f"old_text aparece {count} veces; añade más contexto o usa replace_all=true")
    text = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
    target.write_text(text, encoding="utf-8", newline="")
    return f"Editado {_rel(target)} ({count if replace_all else 1} reemplazo/s)"


@mcp.tool()
def delete_file(path: str) -> str:
    """Borra un archivo del repo (no carpetas)."""
    target = _resolve(path, must_exist=True)
    if target.is_dir():
        raise ToolError("Solo se pueden borrar archivos")
    target.unlink()
    return f"Borrado {_rel(target)}"


@mcp.tool()
def list_dir(path: str = ".", depth: int = 2) -> str:
    """Lista archivos y carpetas (hasta `depth` niveles), sin .git, .venv, node_modules ni similares."""
    base = _resolve(path, must_exist=True)
    out: list[str] = []

    def walk(d: Path, level: int) -> None:
        try:
            entries = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            return
        for e in entries:
            if e.name in IGNORED_DIRS:
                continue
            out.append("  " * level + e.name + ("/" if e.is_dir() else ""))
            if len(out) > 500:
                return
            if e.is_dir() and level + 1 < depth:
                walk(e, level + 1)

    walk(base, 0)
    if len(out) > 500:
        out.append("[... lista recortada]")
    return f"{_rel(base)}/\n" + "\n".join(out)


@mcp.tool()
def search(pattern: str, path: str = ".", glob: str = "", max_results: int = 50) -> str:
    """Busca una expresión regular en los archivos del repo. Devuelve `ruta:línea: texto`. `glob` filtra nombres (p. ej. '*.py')."""
    base = _resolve(path, must_exist=True)
    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "--line-number", "--no-heading", "--color", "never", "--max-count", "20"]
        for d in IGNORED_DIRS:
            cmd += ["--glob", f"!{d}"]
        if glob:
            cmd += ["--glob", glob]
        cmd += ["-e", pattern, "--", _rel(base)]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
        if r.returncode not in (0, 1):
            raise ToolError(f"Búsqueda inválida: {r.stderr.strip()[:500]}")
        lines = r.stdout.splitlines()
    else:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"Expresión regular inválida: {e}") from e
        lines = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
            for fn in filenames:
                if glob and not fnmatch.fnmatch(fn, glob):
                    continue
                fp = Path(dirpath) / fn
                try:
                    for i, line in enumerate(fp.read_text(encoding="utf-8").splitlines(), 1):
                        if rx.search(line):
                            lines.append(f"{_rel(fp)}:{i}:{line}")
                except (UnicodeDecodeError, OSError):
                    continue
    total = len(lines)
    shown = lines[:max_results]
    suffix = f"\n[... {total - len(shown)} resultados más]" if total > len(shown) else ""
    return _clip("\n".join(shown) + suffix) if shown else "Sin resultados"


@mcp.tool()
def run_command(command: str, timeout: int = 300) -> str:
    """Ejecuta un comando en la raíz del repo (tests, build...). Devuelve código de salida y salida (recortada). Sin encadenar ni redirigir."""
    if any(m in command for m in SHELL_META):
        raise ToolError("No se permiten operadores de shell (&, |, ;, >, <, `, %)")
    try:
        r = subprocess.run(command, shell=True, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=max(1, min(timeout, 1800)))
    except subprocess.TimeoutExpired:
        raise ToolError(f"El comando superó {timeout} s") from None
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return _clip(f"exit={r.returncode}\n{out}", 8000)


@mcp.tool()
def git_status() -> str:
    """Estado de git del repo (rama y archivos cambiados)."""
    return _git("status", "--short", "--branch") or "limpio"


@mcp.tool()
def git_diff(path: str = "", staged: bool = False) -> str:
    """Diferencias de git sin confirmar (opcionalmente de una ruta)."""
    args = ["diff"] + (["--staged"] if staged else [])
    if path:
        args += ["--", _rel(_resolve(path))]
    return _clip(_git(*args)) or "Sin cambios"


@mcp.tool()
def git_log(n: int = 10) -> str:
    """Últimos `n` commits (una línea cada uno)."""
    return _git("log", f"-{max(1, min(n, 100))}", "--oneline", "--decorate") or "Sin commits"


def main() -> None:
    global ROOT
    ap = argparse.ArgumentParser(description="Servidor MCP workspace de Skynet")
    ap.add_argument("--root", required=True, help="Raíz del repo autorizado")
    a = ap.parse_args()
    ROOT = Path(a.root).resolve()
    if not ROOT.is_dir():
        print(f"La raíz no existe: {ROOT}", file=sys.stderr)
        sys.exit(2)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
