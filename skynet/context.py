"""Context builder: el mínimo contexto útil para el modelo (principio 5).

Sin base vectorial: objetivo de la tarea, estado de git, archivos de estado de la tarea
(PROGRESO / ERRORES), resumen de pasos anteriores y, si el último paso se cortó, lo que
alcanzó a hacer. De las skills (skills/<nombre>/SKILL.md) solo entra el catálogo, salvo
la que la tarea pidió con /skill, cuyo cuerpo sí entra. Cada sección tiene prioridad; si no cabe en el tope, se recortan las de
menor prioridad.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import gitops, skills
from .config import RepoConfig
from .store import Store, Task

CHARS_PER_TOKEN = 4


@dataclass
class Section:
    title: str
    body: str
    priority: int  # menor = más importante


def task_dir(repo: RepoConfig, task_id: int) -> Path:
    return repo.ruta / gitops.SKYNET_DIR / f"tarea-{task_id}"


def _tail(text: str, chars: int) -> str:
    return text if len(text) <= chars else "[...]\n" + text[-chars:]


class ContextBuilder:
    def __init__(self, store: Store, max_tokens: int = 6000, skills_dir: Path | None = None):
        self.store = store
        self.max_chars = max_tokens * CHARS_PER_TOKEN
        self.skills_dir = skills_dir

    def skill_sections(self, task: Task) -> list[Section]:
        """Cuerpo de la skill que pidió la tarea (si la hay) y catálogo de las demás.
        Se leen del disco en cada paso: editar una skill no exige reiniciar Skynet."""
        if self.skills_dir is None:
            return []
        found, _ = skills.load_skills(self.skills_dir)
        out = []
        chosen = task.capabilities.get("skill")
        if chosen and chosen in found:
            out.append(Section(f"Skill «{chosen}» (instrucciones a seguir en esta tarea)", found[chosen].body(), 1))
        others = {k: v for k, v in found.items() if k != chosen}
        if others:
            out.append(Section("Skills disponibles (el usuario puede cargarlas con /skill <nombre>)",
                               skills.catalog(others), 3))
        return out

    def build_chat(self, task: Task, extra: str | None = None) -> str:
        """Contexto de una conversación sin repo: el mensaje tal cual, más las skills si las hay."""
        text = task.goal + (f"\n\n{extra}" if extra else "")
        for sec in self.skill_sections(task):
            text += f"\n\n## {sec.title}\n{sec.body}"
        return text

    def sections(self, task: Task, repo: RepoConfig | None, extra: str | None = None) -> list[Section]:
        out = [Section("Objetivo de la tarea", task.goal.strip(), 0)]
        if extra:
            out.append(Section("Indicaciones nuevas del usuario", extra.strip(), 0))

        steps = self.store.steps_for(task.id)
        done = [s for s in steps if s.ended_at]
        if done:
            lines = []
            for s in done[-6:]:
                v = f" | verificador: {s.verifier_result}" if s.verifier_result else ""
                c = f" | commit {s.commit_sha[:8]}" if s.commit_sha else ""
                lines.append(f"- Paso {s.n} ({s.kind}, {s.status}): {(s.output_summary or '').strip()[:400]}{v}{c}")
            out.append(Section("Pasos anteriores", "\n".join(lines), 2))
        cut = [s for s in steps if not s.ended_at]
        if cut:
            last = cut[-1]
            evs = self.store.events(task_id=task.id, step_id=last.id, types=("tool",), limit=30)
            if evs:
                lines = [f"- {e['tool']} {((e.get('detail') or {}).get('args_resumen') or '')[:150]} "
                         f"-> {e.get('decision')}" for e in evs]
                out.append(Section(
                    f"El paso {last.n} se cortó a medias; herramientas que llegó a usar",
                    "\n".join(lines), 1))

        if repo is not None and repo.ruta.exists():
            td = task_dir(repo, task.id)
            for name, prio, chars in (("PROGRESO.md", 1, 3000), ("ERRORES.md", 1, 2500)):
                f = td / name
                if name == "PROGRESO.md" and not f.exists():
                    f = repo.ruta / "PROGRESO.md"
                if f.exists():
                    out.append(Section(name, _tail(f.read_text(encoding="utf-8", errors="replace"), chars), prio))
            if gitops.is_repo(repo.ruta):
                st = gitops.git(repo.ruta, "status", "--short", check=False).strip()
                out.append(Section("git status", "\n".join(st.splitlines()[:40]) or "limpio", 2))
                lg = gitops.log_oneline(repo.ruta, 8)
                if lg:
                    out.append(Section("Últimos commits", lg, 3))
                files = gitops.tracked_files(repo.ruta, 200)
                if files:
                    out.append(Section(f"Archivos del repo ({len(files)} primeros)", "\n".join(files), 4))
            if repo.verificador:
                out.append(Section("Verificador", f"`{repo.verificador}` (exit 0 = la tarea está bien)", 1))
        out += self.skill_sections(task)
        return out

    def build(self, task: Task, repo: RepoConfig | None, extra: str | None = None) -> str:
        secs = self.sections(task, repo, extra)
        budget = self.max_chars
        # Las secciones de menor prioridad se recortan primero.
        order = sorted(range(len(secs)), key=lambda i: secs[i].priority)
        bodies: dict[int, str] = {}
        for i in order:
            s = secs[i]
            room = budget - len(s.title) - 10
            if room <= 200:
                break
            body = s.body if len(s.body) <= room else s.body[:room] + "\n[... recortado]"
            bodies[i] = body
            budget -= len(body) + len(s.title) + 10
        parts = [f"## {secs[i].title}\n{bodies[i]}" for i in range(len(secs)) if i in bodies]
        return "\n\n".join(parts)
