"""Task store y audit log persistentes en SQLite (decisión D4 del diseño).

Tres tablas: `tasks` (qué hay que hacer), `steps` (cada paso o iteración) y `events`
(todo lo relevante: llamadas al modelo, herramientas, permisos, verificador, commits).
El esquema se versiona con PRAGMA user_version; cada cambio futuro añade una migración
en MIGRATIONS en vez de reescribir la base.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

# Estados de una tarea
PENDIENTE = "pendiente"
EN_CURSO = "en_curso"
ESPERANDO_PERMISO = "esperando_permiso"
HECHA = "hecha"
FALLIDA = "fallida"
PAUSADA = "pausada"
STATUSES = (PENDIENTE, EN_CURSO, ESPERANDO_PERMISO, HECHA, FALLIDA, PAUSADA)
RESUMABLE = (PENDIENTE, EN_CURSO, ESPERANDO_PERMISO, PAUSADA, FALLIDA)

# Un runner en marcha refresca heartbeat_at; si lleva más de esto sin hacerlo, se da por muerto.
HEARTBEAT_STALE = timedelta(minutes=3)

MIGRATIONS: list[str] = [
    # v1: esquema inicial
    """
    CREATE TABLE tasks(
        id INTEGER PRIMARY KEY,
        parent_id INTEGER REFERENCES tasks(id),
        title TEXT NOT NULL,
        goal TEXT NOT NULL,
        repo TEXT,
        agent TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        max_hours REAL,
        max_iters INTEGER,
        iters_done INTEGER NOT NULL DEFAULT 0,
        capabilities_json TEXT NOT NULL DEFAULT '{}',
        result_summary TEXT,
        pid INTEGER,
        heartbeat_at TEXT
    );
    CREATE TABLE steps(
        id INTEGER PRIMARY KEY,
        task_id INTEGER NOT NULL REFERENCES tasks(id),
        n INTEGER NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'en_curso',
        input_summary TEXT,
        output_summary TEXT,
        verifier_result TEXT,
        commit_sha TEXT,
        started_at TEXT NOT NULL,
        ended_at TEXT
    );
    CREATE TABLE events(
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        task_id INTEGER REFERENCES tasks(id),
        step_id INTEGER REFERENCES steps(id),
        type TEXT NOT NULL,
        tool TEXT,
        permission_level TEXT,
        decision TEXT,
        model TEXT,
        tokens_in INTEGER,
        tokens_out INTEGER,
        cost_eur REAL,
        detail_json TEXT
    );
    CREATE INDEX idx_tasks_status ON tasks(status, updated_at);
    CREATE INDEX idx_steps_task ON steps(task_id, n);
    CREATE INDEX idx_events_task ON events(task_id, id);
    CREATE INDEX idx_events_ts ON events(ts);
    """,
]


def pid_alive(pid: int | None) -> bool:
    """True si el proceso existe. En Windows no se usa os.kill(pid, 0): ahí mataría el proceso."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


@dataclass
class Task:
    id: int
    parent_id: int | None
    title: str
    goal: str
    repo: str | None
    agent: str
    status: str
    created_at: str
    updated_at: str
    max_hours: float | None
    max_iters: int | None
    iters_done: int
    capabilities: dict[str, Any]
    result_summary: str | None
    pid: int | None
    heartbeat_at: str | None

    @property
    def is_long(self) -> bool:
        return self.agent in ("scheduler", "agente-godot")

    def runner_alive(self) -> bool:
        """Hay un proceso trabajando en la tarea: latido reciente y, si se conoce, el pid sigue vivo."""
        hb = parse_iso(self.heartbeat_at)
        if not (hb and datetime.now(timezone.utc) - hb < HEARTBEAT_STALE):
            return False
        return pid_alive(self.pid) if self.pid else True


@dataclass
class Step:
    id: int
    task_id: int
    n: int
    kind: str
    status: str
    input_summary: str | None
    output_summary: str | None
    verifier_result: str | None
    commit_sha: str | None
    started_at: str
    ended_at: str | None


def _task(row: sqlite3.Row) -> Task:
    d = dict(row)
    d["capabilities"] = json.loads(d.pop("capabilities_json") or "{}")
    return Task(**d)


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), timeout=30, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA busy_timeout = 30000")
        self._migrate()

    # --- infraestructura -------------------------------------------------
    def _migrate(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            with self.tx():
                for stmt in [s for s in sql.split(";") if s.strip()]:
                    self.db.execute(stmt)
                self.db.execute(f"PRAGMA user_version = {i}")

    @contextmanager
    def tx(self) -> Iterator[None]:
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            else:
                self.db.execute("COMMIT")

    def close(self) -> None:
        self.db.close()

    def schema_version(self) -> int:
        return self.db.execute("PRAGMA user_version").fetchone()[0]

    # --- tareas ----------------------------------------------------------
    def create_task(
        self,
        title: str,
        goal: str,
        agent: str,
        repo: str | None = None,
        parent_id: int | None = None,
        status: str = PENDIENTE,
        capabilities: dict[str, Any] | None = None,
        max_hours: float | None = None,
        max_iters: int | None = None,
    ) -> Task:
        ts = now_iso()
        with self._lock:
            cur = self.db.execute(
                """INSERT INTO tasks(parent_id, title, goal, repo, agent, status, created_at, updated_at,
                                     max_hours, max_iters, capabilities_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (parent_id, title, goal, repo, agent, status, ts, ts, max_hours, max_iters,
                 json.dumps(capabilities or {}, ensure_ascii=False)),
            )
            return self.get_task(cur.lastrowid)

    def get_task(self, task_id: int) -> Task:
        row = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"No existe la tarea {task_id}")
        return _task(row)

    _UPDATABLE = {"title", "goal", "status", "max_hours", "max_iters", "iters_done",
                  "result_summary", "pid", "heartbeat_at", "capabilities"}

    def update_task(self, task_id: int, **fields: Any) -> Task:
        bad = set(fields) - self._UPDATABLE
        if bad:
            raise ValueError(f"Campos no actualizables: {bad}")
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(f"Estado inválido: {fields['status']}")
        if "capabilities" in fields:
            fields["capabilities_json"] = json.dumps(fields.pop("capabilities"), ensure_ascii=False)
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self.db.execute(f"UPDATE tasks SET {cols} WHERE id = ?", (*fields.values(), task_id))
        return self.get_task(task_id)

    def set_status(self, task_id: int, status: str, summary: str | None = None) -> Task:
        f: dict[str, Any] = {"status": status}
        if summary is not None:
            f["result_summary"] = summary
        return self.update_task(task_id, **f)

    def heartbeat(self, task_id: int, pid: int | None = None) -> None:
        self.update_task(task_id, heartbeat_at=now_iso(), pid=pid if pid is not None else os.getpid())

    def clear_heartbeat(self, task_id: int) -> None:
        self.update_task(task_id, heartbeat_at=None, pid=None)

    def list_tasks(self, limit: int = 20, statuses: tuple[str, ...] | None = None) -> list[Task]:
        sql = "SELECT * FROM tasks"
        args: list[Any] = []
        if statuses:
            sql += f" WHERE status IN ({','.join('?' * len(statuses))})"
            args += list(statuses)
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        args.append(limit)
        return [_task(r) for r in self.db.execute(sql, args)]

    def last_resumable_task(self) -> Task | None:
        """La tarea más reciente sin terminar (lo que retoma 'continúa')."""
        for t in self.list_tasks(limit=50, statuses=RESUMABLE):
            if t.parent_id is None:
                return t
        return None

    # --- pasos -----------------------------------------------------------
    def start_step(self, task_id: int, kind: str, input_summary: str | None = None) -> Step:
        with self.tx():
            n = self.db.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM steps WHERE task_id = ?",
                                (task_id,)).fetchone()[0]
            cur = self.db.execute(
                "INSERT INTO steps(task_id, n, kind, input_summary, started_at) VALUES(?,?,?,?,?)",
                (task_id, n, kind, input_summary, now_iso()),
            )
            step_id = cur.lastrowid
        return self.get_step(step_id)

    def get_step(self, step_id: int) -> Step:
        return Step(**dict(self.db.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()))

    def finish_step(
        self,
        step_id: int,
        status: str,
        output_summary: str | None = None,
        verifier_result: str | None = None,
        commit_sha: str | None = None,
    ) -> Step:
        with self._lock:
            self.db.execute(
                """UPDATE steps SET status = ?, output_summary = ?, verifier_result = ?, commit_sha = ?,
                   ended_at = ? WHERE id = ?""",
                (status, output_summary, verifier_result, commit_sha, now_iso(), step_id),
            )
        return self.get_step(step_id)

    def steps_for(self, task_id: int) -> list[Step]:
        rows = self.db.execute("SELECT * FROM steps WHERE task_id = ? ORDER BY n", (task_id,))
        return [Step(**dict(r)) for r in rows]

    # --- eventos (audit log) --------------------------------------------
    def add_event(
        self,
        type: str,
        task_id: int | None = None,
        step_id: int | None = None,
        tool: str | None = None,
        permission_level: str | None = None,
        decision: str | None = None,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_eur: float | None = None,
        detail: dict[str, Any] | None = None,
    ) -> int:
        with self._lock:
            cur = self.db.execute(
                """INSERT INTO events(ts, task_id, step_id, type, tool, permission_level, decision, model,
                                      tokens_in, tokens_out, cost_eur, detail_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (now_iso(), task_id, step_id, type, tool, permission_level, decision, model,
                 tokens_in, tokens_out, cost_eur,
                 json.dumps(detail, ensure_ascii=False, default=str) if detail else None),
            )
            return cur.lastrowid

    def events(self, task_id: int | None = None, step_id: int | None = None, limit: int = 100,
               types: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE 1=1"
        args: list[Any] = []
        if task_id is not None:
            sql += " AND task_id = ?"
            args.append(task_id)
        if step_id is not None:
            sql += " AND step_id = ?"
            args.append(step_id)
        if types:
            sql += f" AND type IN ({','.join('?' * len(types))})"
            args += list(types)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        out = []
        for r in self.db.execute(sql, args):
            d = dict(r)
            d["detail"] = json.loads(d.pop("detail_json") or "null")
            out.append(d)
        return list(reversed(out))

    def totals(self, task_id: int | None = None, since: str | None = None) -> dict[str, Any]:
        sql = """SELECT COUNT(*) AS llamadas, COALESCE(SUM(tokens_in),0) AS tokens_in,
                        COALESCE(SUM(tokens_out),0) AS tokens_out, COALESCE(SUM(cost_eur),0) AS cost_eur
                 FROM events WHERE type = 'llm'"""
        args: list[Any] = []
        if task_id is not None:
            sql += " AND task_id = ?"
            args.append(task_id)
        if since is not None:
            sql += " AND ts >= ?"
            args.append(since)
        return dict(self.db.execute(sql, args).fetchone())

    def month_cost_eur(self) -> float:
        start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return float(self.totals(since=start.isoformat(timespec="seconds"))["cost_eur"])
