"""Ensamblaje del Core: crea las piezas y ejecuta un paso de agente sobre una tarea.

Lo usan tanto el chat (Coordinator) como las tareas largas (Scheduler), para que haya un
solo camino de ejecución: tarea -> paso -> contexto -> router -> agente -> gate -> MCP.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent import Agent, AgentOutcome, EventFn, system_prompt_for
from .audit import Audit
from .config import RepoConfig, ServerSpec, Settings, load_settings
from .context import ContextBuilder
from .gate import Asker, PermissionGate
from .router import Capabilities, CompletionFn, ModelRouter
from .store import Step, Store, Task
from .toolhub import ToolHub


def _adopt_legacy_db(db_path: Path) -> None:
    """El proyecto se llamó JARVIS: la primera vez se copia data/jarvis.db (con su WAL) al nombre nuevo."""
    old = db_path.with_name("jarvis.db")
    if db_path.exists() or not old.exists():
        return
    for suffix in ("", "-wal", "-shm"):
        src = old.with_name(old.name + suffix)
        if src.exists():
            shutil.copy2(src, db_path.with_name(db_path.name + suffix))


@dataclass
class StepRun:
    step: Step
    outcome: AgentOutcome


class Runtime:
    def __init__(self, settings: Settings | None = None, store: Store | None = None,
                 completion_fn: CompletionFn | None = None):
        self.settings = settings or load_settings()
        if store is None:
            _adopt_legacy_db(self.settings.db_path)
        self.store = store or Store(self.settings.db_path)
        self.audit = Audit(self.store)
        self.router = ModelRouter(self.settings, self.store, completion_fn)
        self.context = ContextBuilder(self.store, self.settings.agent.contexto_max_tokens)

    def repo_for(self, task: Task) -> RepoConfig | None:
        return self.settings.repo(task.repo) if task.repo else None

    def server_specs(self, repo: RepoConfig | None, only: list[str] | None = None) -> list[ServerSpec]:
        if repo is None:
            return []
        names = only if only is not None else repo.herramientas
        return [self.settings.server_spec(n, repo) for n in names]

    def capabilities_for(self, task: Task, repo: RepoConfig | None) -> Capabilities:
        caps = Capabilities.from_dict(task.capabilities.get("capacidades"))
        if repo and repo.privacidad == "alta":
            caps.privacy = "alta"
        return caps

    async def agent_step(
        self,
        task: Task,
        kind: str,
        extra: str | None = None,
        asker: Asker | None = None,
        on_event: EventFn | None = None,
        max_turns: int | None = None,
        instructions: str | None = None,
        protected: list[str] | None = None,
    ) -> StepRun:
        """Ejecuta un paso de agente con contexto fresco (sesión nueva). No verifica ni hace commit."""
        repo = self.repo_for(task)
        # El contexto se arma antes de abrir el paso nuevo, para que vea el paso que se cortó.
        context = self.context.build(task, repo, extra) if repo else task.goal + (f"\n\n{extra}" if extra else "")
        for s in self.store.steps_for(task.id):
            if s.ended_at is None:
                self.store.finish_step(s.id, "interrumpido", "El paso se cortó (Skynet se cerró o falló).")
        step = self.store.start_step(task.id, kind, (extra or task.goal)[:500])
        audit = self.audit.bind(task.id, step.id)
        if instructions:
            context += "\n\n## Instrucciones de este paso\n" + instructions
        grants = list(task.capabilities.get("permisos_preaprobados", []))
        gate = (PermissionGate(self.settings, repo, audit, asker=asker, grants=grants, protected=protected)
                if repo else None)
        agent_kwargs: dict[str, Any] = dict(max_tool_output=self.settings.agent.max_salida_herramienta,
                                            on_event=on_event)
        turns = max_turns or self.settings.agent.max_turnos
        caps = self.capabilities_for(task, repo)
        specs = self.server_specs(repo)
        if specs:
            async with ToolHub(specs, self.settings.logs_dir) as hub:
                agent = Agent(self.router, gate, hub, audit, **agent_kwargs)
                outcome = await agent.run(system_prompt_for(repo), context, caps, turns)
        else:
            agent = Agent(self.router, None, None, audit, **agent_kwargs)
            outcome = await agent.run(system_prompt_for(repo), context, caps, turns)
        return StepRun(step, outcome)
