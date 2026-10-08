"""Propuestas de automejora (fase 2): skills candidatas y añadidos a la memoria curada.

Al cerrar una tarea con el verificador en verde y 3 o más pasos, el modelo activo redacta,
con contexto mínimo (objetivo, resumen de pasos y verificador), una skill candidata y,
si acaso, hechos para la memoria. Nada se activa solo: todo queda en skills/_propuestas/
hasta que Daniel hace /aprobar (PRIVILEGED en el gate) o /rechazar.

Memoria curada: memoria/MEMORY.md (hechos del entorno) y memoria/USER.md (preferencias),
con tope de 2 KB cada una; siempre entran en el contexto (ver context.py).
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import skills
from .store import Task

if TYPE_CHECKING:
    from .runtime import Runtime

MIN_PASOS = 3
MAX_MEMORIA_BYTES = 2048
MAX_LINEAS_MEMORIA = 3
MEMORIA = "memoria"  # nombre de la propuesta de memoria en /aprobar y /rechazar
SEPARADOR = "===MEMORIA==="
MEM_RE = re.compile(r"^\s*[-*]\s*\[(MEMORY|USER)\]\s*(.+?)\s*$", re.IGNORECASE)
CABECERAS = {"MEMORY": "# Memoria del entorno\n\n", "USER": "# Preferencias del usuario\n\n"}

PROMPT = """Una tarea de Skynet terminó bien (verificador en verde). Decide si de ella sale una skill
reutilizable: instrucciones generales para tareas PARECIDAS en el futuro, no un resumen de esta.
Si no sale nada reutilizable, escribe solo NINGUNA antes del separador.

Responde exactamente con este formato:
---
name: nombre-en-minusculas-con-guiones
description: Qué hace la skill y cuándo usarla, en una frase.
---
# Título
Pasos numerados y breves. Solo texto: sin scripts ni archivos adjuntos.
{sep}
- [MEMORY] hecho estable del entorno (rutas, herramientas, comandos que funcionan)
- [USER] preferencia del usuario que se vea en la tarea
Como mucho {n} líneas tras el separador, solo cosas que sigan siendo verdad en otras tareas;
si no hay ninguna, escribe NINGUNO.

## Objetivo de la tarea
{objetivo}

## Pasos
{pasos}

## Verificador
{verificador}
"""


# --- rutas -------------------------------------------------------------------
def skills_dir(home: Path) -> Path:
    return home / "skills"


def propuestas_dir(home: Path) -> Path:
    return skills_dir(home) / "_propuestas"


def memoria_dir(home: Path) -> Path:
    return home / "memoria"


def memoria_file(home: Path, dest: str) -> Path:
    return memoria_dir(home) / f"{dest.upper()}.md"


def reserved_dirs(home: Path) -> list[Path]:
    """Lo que solo se cambia con /aprobar: el gate deniega a las herramientas escribir aquí."""
    return [skills_dir(home), memoria_dir(home)]


def read_memory(home: Path) -> dict[str, str]:
    """Contenido de MEMORY.md y USER.md (recortado al tope) para el contexto."""
    out = {}
    for dest in ("MEMORY", "USER"):
        f = memoria_file(home, dest)
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                out[dest] = text.encode("utf-8")[:MAX_MEMORIA_BYTES].decode("utf-8", "ignore")
    return out


# --- generación ----------------------------------------------------------------
def eligible(rt: "Runtime", task: Task, verifier_ok: bool | None) -> bool:
    return bool(verifier_ok) and len(rt.store.steps_for(task.id)) >= MIN_PASOS


def build_prompt(rt: "Runtime", task: Task, verifier: str) -> str:
    lines = [f"- Paso {s.n} ({s.kind}, {s.status}): {' '.join((s.output_summary or '').split())[:300]}"
             for s in rt.store.steps_for(task.id)[-8:]]
    return PROMPT.format(sep=SEPARADOR, n=MAX_LINEAS_MEMORIA, objetivo=task.goal.strip()[:1500],
                         pasos="\n".join(lines), verificador=verifier[:500])


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-+", "-", s)[:skills.MAX_NAME].strip("-")


def parse_response(text: str) -> tuple[tuple[str, str, str] | None, list[tuple[str, str]]]:
    """(name, description, cuerpo) de la skill propuesta o None, y [(MEMORY|USER, hecho)]."""
    text = re.sub(r"^```\w*\s*\n|\n```\s*$", "", text.strip())
    skill_part, _, mem_part = text.partition(SEPARADOR)
    skill = None
    meta, body = skills.split_frontmatter(skill_part.strip())
    name = _slug(meta.get("name", ""))
    desc = " ".join(meta.get("description", "").split())[:skills.MAX_DESCRIPTION]
    if name and desc and body.strip() and not skill_part.strip().upper().startswith("NINGUNA"):
        skill = (name, desc, body.strip()[:skills.MAX_BODY_CHARS])
    mem = []
    for line in mem_part.splitlines():
        m = MEM_RE.match(line)
        if m and len(mem) < MAX_LINEAS_MEMORIA:
            mem.append((m.group(1).upper(), m.group(2)[:200]))
    return skill, mem


def _free_name(home: Path, name: str) -> str:
    taken = lambda n: n == MEMORIA or (skills_dir(home) / n).exists() or (propuestas_dir(home) / n).exists()  # noqa: E731
    cand, i = name, 2
    while taken(cand):
        cand, i = f"{name}-{i}"[:skills.MAX_NAME], i + 1
    return cand


def save_proposal(home: Path, task: Task, model: str, verifier: str,
                  skill: tuple[str, str, str] | None, mem: list[tuple[str, str]]) -> list[str]:
    """Escribe la propuesta en skills/_propuestas y devuelve los nombres creados."""
    created = []
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    if skill:
        name = _free_name(home, skill[0])
        d = propuestas_dir(home) / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {skill[1]}\n---\n\n{skill[2]}\n",
                                    encoding="utf-8")
        (d / "ORIGEN.md").write_text(
            f"Propuesta al cerrar la tarea {task.id} «{task.title}» ({fecha}), redactada por {model}.\n"
            f"Verificador: {verifier}\n", encoding="utf-8")
        created.append(name)
    current = {dest: (memoria_file(home, dest).read_text(encoding="utf-8") if memoria_file(home, dest).is_file() else "")
               for dest in ("MEMORY", "USER")}
    pending = pending_memory(home)
    new = [(d, t) for d, t in mem if t not in current[d] and (d, t) not in pending]
    if new:
        f = propuestas_dir(home) / f"{MEMORIA}.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        head = "" if f.exists() else "# Añadidos propuestos a la memoria (/aprobar memoria o /rechazar memoria)\n"
        with f.open("a", encoding="utf-8") as fh:
            fh.write(head + f"\n<!-- tarea {task.id}, {fecha} -->\n" + "".join(f"- [{d}] {t}\n" for d, t in new))
        created.append(MEMORIA)
    return created


async def propose_after_task(rt: "Runtime", task: Task, verifier: str) -> list[str]:
    """Pide al modelo activo la propuesta y la guarda. Nunca lanza: un fallo aquí no estropea la tarea."""
    audit = rt.audit.bind(task.id)
    try:
        repo = rt.repo_for(task)
        decision = rt.router.choose(rt.capabilities_for(task, repo))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "Eres el redactor de skills de Skynet. Respondes solo en el formato pedido."},
            {"role": "user", "content": build_prompt(rt, task, verifier)},
        ]
        res = await rt.router.complete(decision, messages, None, audit)
        skill, mem = parse_response(res.content)
        created = save_proposal(rt.settings.home, task, decision.profile.litellm, verifier, skill, mem)
        for name in created:
            audit.log("propuesta", decision="creada", detail={"nombre": name})
        return created
    except Exception as e:  # noqa: BLE001
        audit.log("error", detail={"mensaje": f"propuesta de skill: {type(e).__name__}: {e}"[:500]})
        return []


# --- revisión ------------------------------------------------------------------
def pending_memory(home: Path) -> list[tuple[str, str]]:
    f = propuestas_dir(home) / f"{MEMORIA}.md"
    if not f.is_file():
        return []
    return [(m.group(1).upper(), m.group(2)) for m in map(MEM_RE.match, f.read_text(encoding="utf-8").splitlines()) if m]


def list_proposals(home: Path) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    out = []
    base = propuestas_dir(home)
    if base.is_dir():
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            origen = (d / "ORIGEN.md").read_text(encoding="utf-8").splitlines()[0] if (d / "ORIGEN.md").is_file() else ""
            try:
                s = skills.parse_skill(d / "SKILL.md")
                out.append({"nombre": s.name, "descripcion": s.description, "origen": origen})
            except (OSError, ValueError) as e:
                out.append({"nombre": d.name, "descripcion": f"(no válida: {e})", "origen": origen})
    return out, pending_memory(home)


def count(home: Path) -> int:
    skl, mem = list_proposals(home)
    return len(skl) + (1 if mem else 0)


def _check_name(name: str) -> None:
    # Evita rutas tipo ../ : solo nombres de skill válidos o «memoria».
    if name != MEMORIA and not skills.NAME_RE.match(name):
        raise ValueError(f"Nombre de propuesta no válido: '{name}'")


def exists(home: Path, name: str) -> bool:
    _check_name(name)
    if name == MEMORIA:
        return bool(pending_memory(home))
    return (propuestas_dir(home) / name / "SKILL.md").is_file()


def approve(home: Path, name: str) -> str:
    """Activa la propuesta. Quien llama ya pasó el permission gate. ValueError si no se puede."""
    _check_name(name)
    if name == MEMORIA:
        lines = pending_memory(home)
        if not lines:
            raise ValueError("No hay añadidos de memoria pendientes.")
        new: dict[str, str] = {}
        for dest in ("MEMORY", "USER"):
            add = [t for d, t in lines if d == dest]
            if not add:
                continue
            f = memoria_file(home, dest)
            text = f.read_text(encoding="utf-8") if f.is_file() else CABECERAS[dest]
            text = text.rstrip("\n") + "\n" + "".join(f"- {t}\n" for t in add)
            if len(text.encode("utf-8")) > MAX_MEMORIA_BYTES:
                raise ValueError(f"{f.name} pasaría de {MAX_MEMORIA_BYTES} bytes. Recórtala a mano o "
                                 f"edita {propuestas_dir(home) / (MEMORIA + '.md')} y vuelve a aprobar.")
            new[dest] = text
        memoria_dir(home).mkdir(parents=True, exist_ok=True)
        for dest, text in new.items():
            memoria_file(home, dest).write_text(text, encoding="utf-8")
        (propuestas_dir(home) / f"{MEMORIA}.md").unlink()
        return f"Memoria actualizada: {len(lines)} líneas añadidas a {', '.join(d + '.md' for d in new)}."
    src = propuestas_dir(home) / name
    s = skills.parse_skill(src / "SKILL.md")  # se valida otra vez: pudo editarse a mano
    dst = skills_dir(home) / s.name
    if dst.exists():
        raise ValueError(f"Ya existe la skill activa '{s.name}'. Renombra la propuesta o recházala.")
    shutil.move(str(src), str(dst))
    return f"Skill '{s.name}' activada. Úsala con /skill {s.name} <tarea>."


def reject(home: Path, name: str) -> str:
    _check_name(name)
    if name == MEMORIA:
        (propuestas_dir(home) / f"{MEMORIA}.md").unlink()
        return "Añadidos de memoria descartados."
    shutil.rmtree(propuestas_dir(home) / name)
    return f"Propuesta '{name}' descartada."
