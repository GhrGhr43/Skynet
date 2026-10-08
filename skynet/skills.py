"""Skills de solo lectura: carpetas skills/<nombre>/SKILL.md en el formato de agentskills.io.

SKILL.md = frontmatter YAML (name y description obligatorios) + cuerpo en Markdown. El Context
builder solo pone en el contexto el catálogo (nombre + descripción, con tope); el cuerpo entra
cuando el usuario lo pide con /skill <nombre>. Skynet no escribe skills (fase 1).
Sin PyYAML: el frontmatter se lee con un parser mínimo de `clave: valor` (y bloques > o |).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_BODY_CHARS = 12000      # cuerpo que entra en el contexto como mucho
MAX_CATALOG_CHARS = 2000    # tope del catálogo en el contexto


@dataclass
class Skill:
    name: str
    description: str
    path: Path

    def version(self) -> str:
        """Huella del contenido: cambia cada vez que se edita SKILL.md (sin campo version a mano)."""
        return hashlib.sha1(self.path.read_bytes()).hexdigest()[:8]

    def body(self) -> str:
        """El cuerpo de SKILL.md sin el frontmatter, recortado a MAX_BODY_CHARS."""
        _, body = split_frontmatter(self.path.read_text(encoding="utf-8", errors="replace"))
        body = body.strip()
        return body if len(body) <= MAX_BODY_CHARS else body[:MAX_BODY_CHARS] + "\n[... recortado]"


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    text = text.lstrip("﻿")
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", text, re.DOTALL)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    key: str | None = None
    block: list[str] = []
    folded = True

    def flush() -> None:
        if key is not None and block:
            meta[key] = (" " if folded else "\n").join(block).strip()

    for line in m.group(1).splitlines():
        if key is not None and (line.startswith((" ", "\t")) or not line.strip()):
            block.append(line.strip())  # continuación de un bloque > o |
            continue
        flush()
        key, block = None, []
        km = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not km:
            continue  # claves anidadas (metadata:) y demás: no las necesitamos
        k, v = km.group(1), km.group(2).strip()
        if v in (">", "|", ">-", "|-"):
            key, folded = k, v.startswith(">")
        elif len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            meta[k] = v[1:-1]
        else:
            meta[k] = v
    flush()
    return meta, text[m.end():]


def parse_skill(skill_md: Path) -> Skill:
    """Lee y valida una skill; ValueError con el motivo si no cumple el formato."""
    meta, _ = split_frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
    name, desc = meta.get("name", "").strip(), " ".join(meta.get("description", "").split())
    if not name or not desc:
        raise ValueError("falta name o description en el frontmatter")
    if len(name) > MAX_NAME or not NAME_RE.match(name):
        raise ValueError(f"name inválido «{name}» (minúsculas, números y guiones)")
    if name != skill_md.parent.name:
        raise ValueError(f"name «{name}» no coincide con la carpeta «{skill_md.parent.name}»")
    return Skill(name, desc[:MAX_DESCRIPTION], skill_md)


def load_skills(skills_dir: Path) -> tuple[dict[str, Skill], list[str]]:
    """Skills válidas por nombre y avisos de las que no se pudieron cargar."""
    skills: dict[str, Skill] = {}
    errors: list[str] = []
    if not skills_dir.is_dir():
        return skills, errors
    # Las carpetas que empiezan por _ (p. ej. _propuestas) no son skills activas.
    for d in sorted(p for p in skills_dir.iterdir() if p.is_dir() and not p.name.startswith("_")):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        try:
            s = parse_skill(f)
            skills[s.name] = s
        except (OSError, ValueError) as e:
            errors.append(f"{d.name}: {e}")
    return skills, errors


def catalog(skills: dict[str, Skill], max_chars: int = MAX_CATALOG_CHARS) -> str:
    """Lista nombre + descripción, cortada en `max_chars` (las descripciones largas se acortan)."""
    lines: list[str] = []
    used = 0
    for s in skills.values():
        line = f"- {s.name}: {s.description[:300]}"
        if used + len(line) + 1 > max_chars:
            lines.append(f"- [... {len(skills) - len(lines)} skills más; /skills las lista]")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)
