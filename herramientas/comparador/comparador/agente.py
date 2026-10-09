"""Bucle agéntico neutral para las pruebas de programador autónomo.

Todos los modelos usan las mismas herramientas y límites (comparación controlada). El agente
trabaja en un repo temporal; al terminar, tests ocultos deciden. Decir «he terminado» no puntúa.
"""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .cliente import Modelo
from .pruebas import Resultado
from .tareas_agente import COMMON, TASKS

MAX_TURNOS = 30
SISTEMA = ("Eres un agente de programación autónomo en un repo Python. Usa las herramientas para explorar, leer, "
           "editar y ejecutar los tests (python -m pytest -q). No inventes contenido de archivos que no has leído. "
           "Cuando termines y lo hayas comprobado, responde sin llamar a herramientas con un resumen breve.")


def _f(name: str, desc: str, props: dict, req: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": req}}}


S = {"type": "string"}
HERRAMIENTAS = [
    _f("list_dir", "Lista archivos del repo (recursivo)", {"path": S}, []),
    _f("read_file", "Lee un archivo de texto", {"path": S}, ["path"]),
    _f("write_file", "Crea o sobrescribe un archivo", {"path": S, "content": S}, ["path", "content"]),
    _f("edit_file", "Reemplaza un fragmento exacto (debe aparecer una vez)", {"path": S, "old_text": S, "new_text": S},
       ["path", "old_text", "new_text"]),
    _f("run_command", "Ejecuta un comando de python en el repo (p. ej. python -m pytest -q)", {"command": S}, ["command"]),
]


class Repo:
    def __init__(self, raiz: Path):
        self.raiz = raiz.resolve()

    def _ruta(self, p: str) -> Path:
        r = (self.raiz / (p or ".")).resolve()
        if self.raiz not in (r, *r.parents):
            raise ValueError("ruta fuera del repo")
        return r

    def list_dir(self, path: str = ".") -> str:
        base = self._ruta(path)
        return "\n".join(str(p.relative_to(self.raiz)).replace("\\", "/") for p in sorted(base.rglob("*"))
                         if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts) or "(vacío)"

    def read_file(self, path: str) -> str:
        return self._ruta(path).read_text(encoding="utf-8")[:20000]

    def write_file(self, path: str, content: str) -> str:
        p = self._ruta(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"escrito {path} ({len(content)} caracteres)"

    def edit_file(self, path: str, old_text: str, new_text: str) -> str:
        p = self._ruta(path)
        t = p.read_text(encoding="utf-8")
        n = t.count(old_text)
        if n != 1:
            return f"ERROR: el fragmento aparece {n} veces; debe aparecer exactamente una"
        p.write_text(t.replace(old_text, new_text), encoding="utf-8")
        return f"editado {path}"

    def run_command(self, command: str) -> str:
        args = shlex.split(command, posix=sys.platform != "win32")
        if not args or args[0] not in ("python", "python3", "pytest"):
            return "ERROR: solo se permiten comandos python/pytest"
        args = [sys.executable, "-m", "pytest", *args[1:]] if args[0] == "pytest" else [sys.executable, *args[1:]]
        try:
            r = subprocess.run(args, cwd=self.raiz, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return "ERROR: el comando superó 60 s (¿bucle infinito?)"
        out = (r.stdout + r.stderr)[-6000:]
        return f"exit {r.returncode}\n{out}"


def preparar(tarea: dict, raiz: Path) -> None:
    for rel, texto in {**COMMON, **tarea["files"]}.items():
        p = raiz / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texto, encoding="utf-8")


def verificar(tarea: dict, raiz: Path) -> tuple[bool, str]:
    d = raiz / "_oculto"
    d.mkdir(exist_ok=True)
    (d / "conftest.py").write_text(COMMON["tests/conftest.py"], encoding="utf-8")
    (d / "test_oculto.py").write_text(tarea["hidden"], encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(d), "tests"],
                           cwd=raiz, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "se cuelga"
    lin = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, lin[-1] if lin else ""


def tarea_autonoma(m: Modelo, nombre: str) -> Resultado:
    tarea = next(t for t in TASKS if t["name"] == nombre)
    with tempfile.TemporaryDirectory() as d:
        raiz = Path(d)
        preparar(tarea, raiz)
        repo = Repo(raiz)
        msgs = [{"role": "system", "content": SISTEMA}, {"role": "user", "content": tarea["prompt"]}]
        llamadas = tin = tout = 0
        t0 = time.monotonic()
        turnos = 0
        for turnos in range(1, MAX_TURNOS + 1):
            r = m.chat(msgs, HERRAMIENTAS, max_tokens=8192)
            tin, tout = tin + r.tokens_in, tout + r.tokens_out
            if not r.tool_calls:
                break
            msgs.append({"role": "assistant", "content": r.texto or None, "tool_calls": r.tool_calls})
            for tc in r.tool_calls:
                llamadas += 1
                f = tc.get("function", {})
                try:
                    args = json.loads(f.get("arguments") or "{}")
                    salida = getattr(repo, f["name"])(**args) if f.get("name") in {h["function"]["name"] for h in HERRAMIENTAS} \
                        else f"ERROR: herramienta desconocida {f.get('name')}"
                except Exception as e:  # el error vuelve al modelo, como en un agente real
                    salida = f"ERROR: {type(e).__name__}: {e}"
                msgs.append({"role": "tool", "tool_call_id": tc.get("id", "x"), "content": str(salida)[:6000]})
        ok, linea = verificar(tarea, raiz)
        met = {"turnos": turnos, "herramientas": llamadas, "tokens_in": tin, "tokens_out": tout,
               "segundos": round(time.monotonic() - t0, 1)}
        return Resultado(1.0 if ok else 0.0, "ok" if ok else "fallo", f"{linea} · {turnos} turnos, {llamadas} "
                         "herramientas", met)
