"""Presentación en terminal (rich) de tareas, pasos y audit log."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text

from .audit import describe_event
from .store import Step, Store, Task

STATUS_STYLE = {
    "hecha": "green", "fallida": "red", "pausada": "yellow", "en_curso": "cyan",
    "esperando_permiso": "magenta", "pendiente": "white",
}


def _local_time(ts: str | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%m-%d %H:%M:%S")
    except ValueError:
        return ts


def tasks_table(tasks: list[Task]) -> Table:
    t = Table(title="Tareas", show_lines=False)
    for col in ("id", "estado", "agente", "repo", "iters", "actualizada", "título"):
        t.add_column(col, overflow="fold")
    for task in tasks:
        st = Text(task.status, style=STATUS_STYLE.get(task.status, ""))
        if task.runner_alive():
            st.append(" ●", style="cyan")
        t.add_row(str(task.id), st, task.agent, task.repo or "-", str(task.iters_done),
                  _local_time(task.updated_at), task.title)
    return t


def events_table(events: list[dict[str, Any]], title: str = "Audit log") -> Table:
    t = Table(title=title)
    for col in ("hora", "tarea", "tipo", "herramienta", "permiso", "decisión", "modelo", "tok in", "tok out", "€",
                "detalle"):
        t.add_column(col, overflow="fold")
    for e in events:
        dec = e.get("decision") or ""
        style = "red" if dec in ("denegado", "fallida", "bloqueado", "error") else ""
        t.add_row(
            _local_time(e["ts"]), str(e.get("task_id") or ""), e["type"], e.get("tool") or "",
            e.get("permission_level") or "", Text(dec, style=style), (e.get("model") or "").split("/")[-1],
            str(e.get("tokens_in") or ""), str(e.get("tokens_out") or ""),
            f"{e['cost_eur']:.4f}" if e.get("cost_eur") else "", describe_event(e),
        )
    return t


def totals_line(tot: dict[str, Any], label: str) -> Text:
    return Text(f"{label}: {tot['llamadas']} llamadas al modelo · {tot['tokens_in']} tokens de entrada · "
                f"{tot['tokens_out']} de salida · {tot['cost_eur']:.4f} €", style="bold")


def task_detail(store: Store, task: Task) -> Group:
    steps: list[Step] = store.steps_for(task.id)
    head = Text()
    head.append(f"Tarea {task.id}: {task.title}\n", style="bold")
    head.append(f"Estado: ", style="")
    head.append(task.status, style=STATUS_STYLE.get(task.status, ""))
    head.append(f" · agente {task.agent} · repo {task.repo or '-'} · iteraciones {task.iters_done}")
    if task.runner_alive():
        head.append(f" · en marcha (pid {task.pid})", style="cyan")
    if task.result_summary:
        head.append(f"\nResultado: {task.result_summary}")
    t = Table(title="Pasos")
    for col in ("#", "tipo", "estado", "verificador", "commit", "resumen"):
        t.add_column(col, overflow="fold")
    for s in steps[-15:]:
        t.add_row(str(s.n), s.kind, s.status, s.verifier_result or "", (s.commit_sha or "")[:8],
                  (s.output_summary or "")[:200])
    return Group(head, t, totals_line(store.totals(task_id=task.id), "Consumo"))
