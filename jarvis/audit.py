"""Audit log: fachada sobre la tabla `events` y su presentación (`jarvis log`).

Tipos de evento: task (creación/cambio de estado), route (decisión del router),
llm (llamada al modelo), tool (llamada a herramienta + decisión del permission gate),
verifier, commit, rollback, error.
"""
from __future__ import annotations

from typing import Any

from .store import Store


class Audit:
    def __init__(self, store: Store, task_id: int | None = None, step_id: int | None = None):
        self.store = store
        self.task_id = task_id
        self.step_id = step_id

    def bind(self, task_id: int | None, step_id: int | None = None) -> "Audit":
        return Audit(self.store, task_id, step_id)

    def log(self, type: str, **kw: Any) -> int:
        kw.setdefault("task_id", self.task_id)
        kw.setdefault("step_id", self.step_id)
        return self.store.add_event(type, **kw)


def describe_event(e: dict[str, Any]) -> str:
    """Una línea legible con lo esencial del detalle de un evento."""
    d = e.get("detail") or {}
    t = e["type"]
    if t == "tool":
        args = d.get("args_resumen") or ""
        res = d.get("resultado") or d.get("motivo") or ""
        return f"{args} -> {res}"[:160]
    if t == "llm":
        return f"{d.get('motivo_ruta', '')} {d.get('fin', '')}".strip()[:160]
    if t == "route":
        return str(d.get("motivo", ""))[:160]
    if t == "verifier":
        return f"{'OK' if d.get('ok') else 'FALLA'} ({d.get('segundos', '?')} s) {d.get('comando', '')}"[:160]
    if t in ("commit", "rollback"):
        return f"{d.get('sha', '')[:10]} {d.get('mensaje', '')}"[:160]
    return str(d.get("mensaje") or d.get("motivo") or d or "")[:160]
