"""Interfaz de línea de comandos: `skynet` (chat) y subcomandos de consulta.

  skynet                       chat
  skynet log [--tarea N]       audit log: herramientas, modelo, tokens y coste
  skynet tareas                últimas tareas
  skynet estado [N]            detalle de una tarea
  skynet largo --tarea N       ejecuta una tarea larga (lo usa el chat en segundo plano)
  skynet largo --repo R --horas H "objetivo"   crea y ejecuta una tarea larga en primer plano
  skynet doctor                comprueba configuración, LM Studio, git y servidores MCP
  skynet web [--puerto P]      interfaz gráfica local en el navegador (http://127.0.0.1:8765)
  skynet demo                  crea el repo de prueba data/sandbox/demo
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from . import __version__, gitops, views
from .config import ConfigError, load_settings
from .coordinator import Coordinator
from .runtime import Runtime
from .store import PENDIENTE

console = Console()


def _prepare_env() -> None:
    """Los comandos que lanza Skynet (verificador, MCP) usan el Python del entorno de Skynet."""
    scripts = str(Path(sys.executable).parent)
    path = os.environ.get("PATH", "")
    if not path.lower().startswith(scripts.lower()):
        os.environ["PATH"] = scripts + os.pathsep + path
    # Claves guardadas con setx no llegan a terminales abiertas antes: se leen del registro de usuario.
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if name.upper().endswith("_API_KEY") and value and not os.environ.get(name):
                        os.environ[name] = str(value)
        except OSError:
            pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")  # no ensuciar los repos con __pycache__
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


class ConsoleUI:
    def info(self, text: str) -> None:
        console.print(text, style="dim", markup=False, highlight=False)

    def answer(self, text: str) -> None:
        console.print(Panel(Markdown(text or "(sin respuesta)"), title="Skynet", border_style="cyan"))

    def show(self, renderable: Any) -> None:
        console.print(renderable)

    def event(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "route":
            console.print(f"→ {data['model']} ({data['reason']})", style="dim", markup=False)
        elif kind == "tool":
            console.print(f"  · {data['key']}({data['args']})", style="dim", markup=False, highlight=False)
        elif kind == "denied":
            console.print(f"  ✗ {data['key']}: {data['reason']}", style="red", markup=False)
        elif kind == "tool_result" and not data.get("ok"):
            console.print(f"    error: {data.get('first_line', '')}", style="yellow", markup=False)
        elif kind == "say":
            console.print(f"  {data['text'][:300]}", style="italic dim", markup=False)
        elif kind == "verifying":
            console.print(f"  ⧗ verificador: {data['command']}", style="dim", markup=False)

    async def ask(self, prompt: str) -> str:
        console.print(Panel(prompt, title="Confirmación", border_style="magenta"), markup=False)
        try:
            return await asyncio.to_thread(input, "> ")
        except EOFError:
            return "n"


def chat(rt: Runtime) -> None:
    """Bucle del chat. Cada mensaje corre en su propio event loop: así Ctrl+C solo corta la
    tarea en curso (queda pausada y «continúa» la retoma) y el chat sigue abierto."""
    ui = ConsoleUI()
    coord = Coordinator(rt, ui)
    console.print(f"[bold cyan]Skynet[/] {__version__} · repo: {coord.repo_name or 'ninguno'} · /ayuda para ver comandos")
    pending = rt.store.last_resumable_task()
    if pending:
        console.print(f"Tarea sin terminar: {pending.id} «{pending.title}» ({pending.status}). "
                      "Di «continúa» para retomarla.", style="yellow", markup=False)
    while True:
        try:
            text = input("\nTú> ")
        except (EOFError, KeyboardInterrupt):
            break
        try:
            if not asyncio.run(coord.handle(text)):
                break
        except KeyboardInterrupt:
            console.print("Interrumpido. La tarea queda pausada; «continúa» la retoma.", style="yellow")
        except ConfigError as e:
            console.print(f"Configuración: {e}", style="red", markup=False)
        except Exception as e:  # el chat no debe morir por un fallo de una tarea
            console.print(f"Error: {type(e).__name__}: {e}", style="red", markup=False)
    console.print("Hasta luego.", style="dim")


def cmd_long(rt: Runtime, a: argparse.Namespace) -> int:
    from .scheduler import LongTaskRunner

    if a.tarea:
        task_id = a.tarea
    else:
        if not (a.repo and a.objetivo):
            console.print("Uso: skynet largo --tarea N  |  skynet largo --repo R --horas H \"objetivo\"")
            return 2
        repo = rt.settings.repo(a.repo)
        agent = "agente-godot" if repo.agente == "agente-godot" else "scheduler"
        grants = ["coding_agent.start_task", "coding_agent.stop_task"] if agent == "agente-godot" else []
        task = rt.store.create_task(
            title=a.objetivo[:70], goal=a.objetivo, agent=agent, repo=repo.nombre, status=PENDIENTE,
            max_hours=a.horas, max_iters=a.iters,
            capabilities={"capacidades": {"cost": "bajo", "coding": "alto"}, "permisos_preaprobados": grants},
        )
        task_id = task.id
        console.print(f"Tarea larga {task_id} creada.")
    task = asyncio.run(LongTaskRunner(rt, task_id).run())
    console.print(f"Tarea {task.id}: {task.status} · {task.result_summary}")
    return 0 if task.status == "hecha" else 1


def doctor_checks(rt: Runtime) -> list[dict[str, Any]]:
    """Comprobaciones de la instalación. Cada una: nombre, estado (ok | mal | off) y detalle.
    La usan `skynet doctor` y la web; «off» = desactivado a propósito, no cuenta como fallo."""
    s = rt.settings
    out: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        out.append({"nombre": name, "estado": "ok" if ok else "mal", "detalle": detail})

    check("Configuración", True, str(s.home / "config"))
    check("Base de datos", True, f"{s.db_path} (esquema v{rt.store.schema_version()})")
    check("git", shutil.which("git") is not None)
    check("ripgrep (opcional)", True, "encontrado" if shutil.which("rg") else "no instalado: la búsqueda usa Python")
    local = s.models["local"]
    if local.api_base:
        try:
            with urllib.request.urlopen(local.api_base.rstrip("/") + "/models", timeout=5) as r:
                ids = [m["id"] for m in json.load(r).get("data", [])]
            want = local.litellm.split("/", 1)[1] if "/" in local.litellm else local.litellm
            check("LM Studio", want in ids, f"{want} {'disponible' if want in ids else 'NO aparece en ' + str(ids)}")
        except Exception as e:
            check("LM Studio", False, f"no responde en {local.api_base}: {e}")
    for name, m in s.models.items():
        if name == "local":
            continue
        avail, why = m.available()
        out.append({"nombre": f"modelo {name}", "estado": "ok" if avail else "off",
                    "detalle": f"{m.litellm} · {why or 'clave presente'} · presupuesto {s.budget_eur} €/mes"})
    for r in s.repos.values():
        exists = r.ruta.exists()
        check(f"Repo {r.nombre}", exists, f"{r.ruta}" + ("" if exists else " no existe (skynet demo lo crea)"))

    async def mcp_probe() -> None:
        from .toolhub import ToolHub

        for r in s.repos.values():
            if not r.ruta.exists():
                continue
            try:
                async with ToolHub(rt.server_specs(r), s.logs_dir) as hub:
                    check(f"MCP de {r.nombre}", True, f"{len(hub.tools)} herramientas")
            except Exception as e:
                check(f"MCP de {r.nombre}", False, f"{type(e).__name__}: {e}")
    asyncio.run(mcp_probe())
    return out


def cmd_doctor(rt: Runtime) -> int:
    style = {"ok": ("green", "OK "), "mal": ("red", "MAL"), "off": ("yellow", "OFF")}
    checks = doctor_checks(rt)
    for c in checks:
        color, label = style[c["estado"]]
        console.print(f"[{color}]{label}[/] {c['nombre']}" + (f" · {c['detalle']}" if c["detalle"] else ""),
                      highlight=False)
    return 1 if any(c["estado"] == "mal" for c in checks) else 0


def cmd_web(rt: Runtime, a: argparse.Namespace) -> int:
    import socket

    from .web.server import serve

    # Si otra ventana ya sirve en ese puerto, el navegador acabaría en ella (p. ej. una versión vieja)
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", a.puerto)) == 0:
            console.print(f"El puerto {a.puerto} ya está ocupado: cierra la otra ventana de Skynet "
                          f"o usa --puerto.", style="red", markup=False)
            return 1
    return serve(rt, port=a.puerto, open_browser=not a.no_abrir)


DEMO_FILES = {
    "pytest.ini": "[pytest]\ntestpaths = tests\n",
    ".gitignore": "__pycache__/\n.pytest_cache/\n",
    "README.md": "# demo\n\nRepo de prueba de Skynet: una pequeña librería de texto con tests.\n",
    "textos.py": '''"""Utilidades de texto (algunas sin implementar)."""


def contar_palabras(texto: str) -> int:
    """Número de palabras separadas por espacios en blanco."""
    return len(texto.split())


def es_palindromo(texto: str) -> bool:
    """True si se lee igual al revés, ignorando mayúsculas, espacios y tildes."""
    raise NotImplementedError


def slug(texto: str) -> str:
    """Convierte 'Hola Mundo, ¿qué tal?' en 'hola-mundo-que-tal'."""
    raise NotImplementedError
''',
    "tests/test_textos.py": '''from textos import contar_palabras, es_palindromo, slug


def test_contar_palabras():
    assert contar_palabras("hola  mundo ") == 2


def test_palindromo():
    assert es_palindromo("Anita lava la tina")
    assert es_palindromo("Dábale arroz a la zorra el abad")
    assert not es_palindromo("Skynet")


def test_slug():
    assert slug("Hola Mundo, ¿qué tal?") == "hola-mundo-que-tal"
    assert slug("  Ya   está  ") == "ya-esta"
''',
    "tests/conftest.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n",
}


def cmd_demo(rt: Runtime, force: bool) -> int:
    repo = rt.settings.repos.get("demo")
    if repo is None:
        console.print("No hay repo 'demo' en config/repos.toml")
        return 1
    if repo.ruta.exists() and any(repo.ruta.iterdir()) and not force:
        console.print(f"{repo.ruta} ya existe (usa --forzar para recrearlo)")
        return 1
    if repo.ruta.exists() and force:
        # Se vacía la carpeta (no se borra: puede ser el directorio actual de alguna consola)
        def _force(func: Any, path: str, _exc: Any) -> None:
            os.chmod(path, 0o700)  # los objetos de .git son de solo lectura en Windows
            func(path)

        for child in repo.ruta.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, onexc=_force)
            else:
                child.unlink()
    for rel, content in DEMO_FILES.items():
        p = repo.ruta / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    gitops.ensure_repo(repo.ruta)
    gitops.commit_all(repo.ruta, "demo: estado inicial (2 tests fallan)")
    console.print(f"Repo demo creado en {repo.ruta}. Prueba: skynet → «implementa es_palindromo» o "
                  "/largo 1 haz que pasen todos los tests")
    return 0


def main(argv: list[str] | None = None) -> int:
    _prepare_env()
    ap = argparse.ArgumentParser(prog="skynet", description="Skynet, agente personal")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    p_log = sub.add_parser("log", help="audit log")
    p_log.add_argument("--tarea", type=int)
    p_log.add_argument("-n", type=int, default=50)
    p_t = sub.add_parser("tareas", help="últimas tareas")
    p_t.add_argument("-n", type=int, default=20)
    p_e = sub.add_parser("estado", help="detalle de una tarea")
    p_e.add_argument("tarea", type=int, nargs="?")
    p_l = sub.add_parser("largo", help="ejecutar una tarea larga")
    p_l.add_argument("--tarea", type=int)
    p_l.add_argument("--repo")
    p_l.add_argument("--horas", type=float, default=1.0)
    p_l.add_argument("--iters", type=int)
    p_l.add_argument("objetivo", nargs="?")
    sub.add_parser("doctor", help="comprobar la instalación")
    p_w = sub.add_parser("web", help="interfaz gráfica local en el navegador")
    p_w.add_argument("--puerto", type=int, default=8765)
    p_w.add_argument("--no-abrir", action="store_true", help="no abrir el navegador")
    p_d = sub.add_parser("demo", help="crear el repo de prueba")
    p_d.add_argument("--forzar", action="store_true")
    sub.add_parser("chat", help="chat (por defecto)")
    a = ap.parse_args(argv)

    try:
        rt = Runtime(load_settings())
    except ConfigError as e:
        console.print(f"Error de configuración: {e}", style="red", markup=False)
        return 2

    if a.cmd in (None, "chat"):
        chat(rt)
        return 0
    if a.cmd == "log":
        console.print(views.events_table(rt.store.events(task_id=a.tarea, limit=a.n)))
        console.print(views.totals_line(rt.store.totals(task_id=a.tarea),
                                        "Total" if a.tarea is None else f"Tarea {a.tarea}"))
        console.print(views.totals_line(rt.store.totals(since=_month_start()), "Este mes"))
        return 0
    if a.cmd == "tareas":
        console.print(views.tasks_table(rt.store.list_tasks(limit=a.n)))
        return 0
    if a.cmd == "estado":
        task = rt.store.get_task(a.tarea) if a.tarea else (rt.store.list_tasks(1) or [None])[0]
        if task is None:
            console.print("No hay tareas.")
            return 1
        console.print(views.task_detail(rt.store, task))
        return 0
    if a.cmd == "largo":
        return cmd_long(rt, a)
    if a.cmd == "doctor":
        return cmd_doctor(rt)
    if a.cmd == "web":
        return cmd_web(rt, a)
    if a.cmd == "demo":
        return cmd_demo(rt, a.forzar)
    return 0


def _month_start() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat(
        timespec="seconds")


if __name__ == "__main__":
    sys.exit(main())
