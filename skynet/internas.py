"""Herramientas internas del Core: las que actúan sobre el propio Skynet y no sobre el PC (D20, D21).

El modelo las usa hablando, sin comandos `/`:
- `memoria`: guarda preferencias y datos estables (memoria.py). Sin preguntar.
- `ver_skill`: carga las instrucciones de una skill cuando encaja con la petición. Sin preguntar.
- `crear_proyecto`: crea una carpeta con git y un test mínimo y la autoriza como repo. Pide confirmación.
- `tarea_larga`: lanza una tarea larga en segundo plano (minutos) sobre un repo con verificador. Pide
  confirmación, porque deja el modelo trabajando solo.
Son internas (no servidores MCP) porque cambian el estado de Skynet; no pasan por el gate de herramientas,
pero lo que pide confirmación usa el mismo diálogo y todo queda en el registro. No se ofrecen en tareas
largas (sin nadie delante) ni a agentes externos.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from . import gitops, memoria, skills
from .gate import Level

if TYPE_CHECKING:
    from .runtime import Runtime
    from .store import Task

Asker = Callable[[str, Level, dict[str, Any], str], Awaitable[str]]
SI = ("s", "si", "sí", "y", "yes", "t")
NOMBRE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")


@dataclass
class Interna:
    esquema: dict[str, Any]
    ejecutar: Callable[[dict[str, Any]], Awaitable[str]]


def _fn(name: str, desc: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": required}}}


def construir(rt: "Runtime", task: "Task", asker: Asker | None) -> dict[str, Interna]:
    home = rt.settings.home

    async def _memoria(args: dict[str, Any]) -> str:
        return memoria.aplicar(home, args)[1]

    async def _ver_skill(args: dict[str, Any]) -> str:
        found, _ = skills.load_skills(rt.skills_dir)
        sk = found.get(str(args.get("nombre", "")).strip())
        if sk is None:
            return f"ERROR: no existe esa skill. Hay: {', '.join(found) or 'ninguna'}."
        rt.store.add_skill_use(sk.name, sk.version(), task.id)
        return f"# Skill «{sk.name}»: síguela en esta tarea\n\n{sk.body()}"

    async def _confirmar(key: str, args: dict[str, Any], motivo: str) -> bool:
        if asker is None:
            return False
        return (await asker(key, Level.PRIVILEGED, args, motivo)).strip().lower() in SI

    async def _crear_proyecto(args: dict[str, Any]) -> str:
        nombre = str(args.get("nombre", "")).strip().lower()
        if not NOMBRE_RE.match(nombre):
            return "ERROR: nombre en minúsculas, números, - o _ (2-41 caracteres), p. ej. juego-naves."
        if nombre in rt.settings.repos:
            return f"Ya existe el repo «{nombre}» ({rt.settings.repos[nombre].ruta}). Úsalo."
        ruta = rt.settings.proyectos / nombre
        if ruta.exists() and any(ruta.iterdir()):
            return f"ERROR: {ruta} ya existe y no está vacía; elige otro nombre."
        desc = " ".join(str(args.get("descripcion", "")).split())[:300]
        if not await _confirmar("skynet.crear_proyecto", {"path": str(ruta)},
                                f"crear el proyecto «{nombre}» en {ruta} (git y un test mínimo) y autorizarlo como repo"):
            return "El usuario no lo ha aprobado: no se ha creado nada."
        (ruta / "tests").mkdir(parents=True, exist_ok=True)
        (ruta / "README.md").write_text(f"# {nombre}\n\n{desc}\n", encoding="utf-8")
        (ruta / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
        (ruta / "tests" / "conftest.py").write_text(
            "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n", encoding="utf-8")
        (ruta / "tests" / "test_inicio.py").write_text(
            "def test_el_proyecto_arranca():\n    assert True  # sustitúyelo por tests de verdad\n", encoding="utf-8")
        gitops.ensure_repo(ruta)
        gitops.commit_all(ruta, "Proyecto creado por Skynet")
        from .config import add_repo

        rt.settings.repos[nombre] = add_repo(home, nombre, ruta, "python -m pytest -q")
        rt.audit.log("task", task_id=task.id, decision="proyecto_creado", detail={"nombre": nombre, "ruta": str(ruta)})
        return (f"Proyecto «{nombre}» creado en {ruta} y autorizado como repo (verificador: python -m pytest -q). "
                "Para trabajar en él mucho rato usa tarea_larga con repo=" + nombre + ".")

    async def _tarea_larga(args: dict[str, Any]) -> str:
        from .scheduler import lanzar_larga

        nombre = str(args.get("repo") or task.repo or "").strip()
        repo = rt.settings.repos.get(nombre)
        if repo is None:
            return ("ERROR: hace falta un repo autorizado (parámetro repo). Si es un proyecto nuevo, créalo antes con "
                    f"crear_proyecto. Repos: {', '.join(rt.settings.repos) or 'ninguno'}.")
        objetivo = " ".join(str(args.get("objetivo", "")).split())
        try:
            minutos = int(float(args.get("minutos", 0)))
        except (TypeError, ValueError):
            minutos = 0
        tope = int(rt.settings.long.max_horas * 60)
        if not objetivo or not 5 <= minutos <= tope:
            return f"ERROR: indica el objetivo y los minutos (entre 5 y {tope})."
        if not await _confirmar("skynet.tarea_larga", {"comando": f"{minutos} min en {repo.nombre}: {objetivo}"},
                                f"trabajar solo {minutos} minutos en «{repo.nombre}» en segundo plano: pasos pequeños, "
                                f"verificador `{repo.verificador or 'ninguno'}`, commit si avanza y deshacer si empeora"):
            return "El usuario no lo ha aprobado: no se ha lanzado nada."
        caps = dict(task.capabilities.get("capacidades", {}), cost="bajo")
        larga, pid = lanzar_larga(rt, repo, objetivo, minutos / 60, caps)
        return (f"Tarea larga {larga.id} lanzada en segundo plano (pid {pid}) para {minutos} min en «{repo.nombre}». "
                f"Su avance queda en {repo.ruta / 'PROGRESO.md'}. Díselo a Daniel en una frase.")

    largo = int(rt.settings.long.max_horas * 60)
    out = {
        memoria.NOMBRE: Interna(memoria.ESQUEMA, _memoria),
        "crear_proyecto": Interna(_fn(
            "crear_proyecto",
            "Crea un proyecto nuevo (carpeta con git, README y un test mínimo) y lo autoriza como repo. Úsala cuando "
            "Daniel pida empezar algo nuevo (un juego, una app, un script grande). La herramienta ya le pide "
            "confirmación a Daniel: llámala directamente, sin preguntarle tú antes.",
            {"nombre": {"type": "string", "description": "minúsculas y guiones, p. ej. juego-naves"},
             "descripcion": {"type": "string"}}, ["nombre"]), _crear_proyecto),
        "tarea_larga": Interna(_fn(
            "tarea_larga",
            f"Deja trabajando a Skynet solo, en segundo plano, durante los minutos que pida Daniel (5 a {largo}), "
            "sobre un repo con tests. Úsala cuando pida que trabajes un rato largo o «toda la noche». La herramienta "
            "ya le pide confirmación: llámala directamente, sin preguntarle tú antes.",
            {"objetivo": {"type": "string"}, "minutos": {"type": "integer"},
             "repo": {"type": "string", "description": "repo autorizado; por defecto, el de esta conversación"}},
            ["objetivo", "minutos"]), _tarea_larga),
    }
    found, _ = skills.load_skills(rt.skills_dir)
    if found:
        out["ver_skill"] = Interna(_fn(
            "ver_skill", "Carga las instrucciones de una skill (ver «Skills disponibles») cuando encaje con la petición.",
            {"nombre": {"type": "string"}}, ["nombre"]), _ver_skill)
    return out
