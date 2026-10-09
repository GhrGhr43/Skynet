"""Sesiones de chat al estilo Claude/Codex: cada conversación se guarda con su historial.

Una sesión agrupa los mensajes que ve la interfaz (los tuyos, las respuestas, la actividad) y las
tareas que salen de ella. Así se puede cerrar Skynet, volver y seguir donde lo dejaste, y el modelo
recibe la conversación reciente de la sesión aunque se haya reiniciado.

Va en tablas propias (`CREATE TABLE IF NOT EXISTS`) y no como migración del Store: no toca `tasks`
ni la numeración de esquema que usa el resto del Core.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .store import Store, now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS sesiones(
    id INTEGER PRIMARY KEY,
    titulo TEXT NOT NULL DEFAULT '',
    creada TEXT NOT NULL,
    actualizada TEXT NOT NULL,
    archivada INTEGER NOT NULL DEFAULT 0,
    contexto INTEGER NOT NULL DEFAULT 0,
    modelo TEXT
);
CREATE TABLE IF NOT EXISTS sesion_mensajes(
    id INTEGER PRIMARY KEY,
    sesion_id INTEGER NOT NULL REFERENCES sesiones(id),
    seq INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    datos_json TEXT NOT NULL,
    ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sesion_tareas(
    sesion_id INTEGER NOT NULL REFERENCES sesiones(id),
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    PRIMARY KEY (sesion_id, task_id)
);
CREATE INDEX IF NOT EXISTS idx_sesion_mensajes ON sesion_mensajes(sesion_id, id);
CREATE INDEX IF NOT EXISTS idx_sesiones_act ON sesiones(archivada, actualizada);
CREATE INDEX IF NOT EXISTS idx_sesion_tareas_task ON sesion_tareas(task_id)
"""

TITULO_MAX = 60


def titulo_de(texto: str) -> str:
    """Título corto a partir del primer mensaje (sin LLM: primera línea, sin comandos ni espacios de más)."""
    t = re.sub(r"\s+", " ", (texto or "").strip().splitlines()[0] if texto.strip() else "").strip(" .¿?¡!")
    if len(t) > TITULO_MAX:
        t = t[:TITULO_MAX].rsplit(" ", 1)[0] + "…"
    return t[:1].upper() + t[1:] if t else "Sesión nueva"


class Sesiones:
    def __init__(self, store: Store):
        self.store = store
        self.db = store.db
        with store._lock:
            for stmt in [s for s in SCHEMA.split(";") if s.strip()]:
                self.db.execute(stmt)

    # --- sesiones --------------------------------------------------------
    def crear(self, titulo: str = "") -> dict[str, Any]:
        ts = now_iso()
        with self.store._lock:
            cur = self.db.execute("INSERT INTO sesiones(titulo, creada, actualizada) VALUES(?,?,?)", (titulo, ts, ts))
        return self.get(cur.lastrowid)

    def get(self, sid: int) -> dict[str, Any]:
        row = self.db.execute("SELECT * FROM sesiones WHERE id = ?", (sid,)).fetchone()
        if row is None:
            raise KeyError(f"No existe la sesión {sid}")
        return dict(row)

    def existe(self, sid: int) -> bool:
        return self.db.execute("SELECT 1 FROM sesiones WHERE id = ? AND archivada = 0", (sid,)).fetchone() is not None

    def ultima(self) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM sesiones WHERE archivada = 0 ORDER BY actualizada DESC, id DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def vacia(self, sid: int) -> bool:
        return self.db.execute("SELECT 1 FROM sesion_mensajes WHERE sesion_id = ? LIMIT 1", (sid,)).fetchone() is None

    def lista(self, q: str = "", limit: int = 80) -> list[dict[str, Any]]:
        sql = """SELECT s.id, s.titulo, s.creada, s.actualizada,
                        (SELECT COUNT(*) FROM sesion_mensajes m WHERE m.sesion_id = s.id AND m.tipo = 'usuario') AS mensajes
                 FROM sesiones s WHERE s.archivada = 0"""
        args: list[Any] = []
        if q.strip():
            sql += """ AND (s.titulo LIKE ? OR EXISTS (SELECT 1 FROM sesion_mensajes m WHERE m.sesion_id = s.id
                        AND m.tipo IN ('usuario', 'respuesta') AND m.datos_json LIKE ?))"""
            like = f"%{q.strip()}%"
            args += [like, like]
        sql += " ORDER BY s.actualizada DESC, s.id DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(sql, args)]

    def renombrar(self, sid: int, titulo: str) -> dict[str, Any]:
        titulo = re.sub(r"\s+", " ", titulo).strip()[:120]
        with self.store._lock:
            self.db.execute("UPDATE sesiones SET titulo = ? WHERE id = ?", (titulo, sid))
        return self.get(sid)

    def archivar(self, sid: int) -> None:
        """Borrar desde la interfaz = archivar: las tareas y el registro siguen en la base (auditoría)."""
        with self.store._lock:
            self.db.execute("UPDATE sesiones SET archivada = 1 WHERE id = ?", (sid,))

    def tocar(self, sid: int, **campos: Any) -> None:
        campos = {k: v for k, v in campos.items() if k in ("contexto", "modelo")}
        campos["actualizada"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in campos)
        with self.store._lock:
            self.db.execute(f"UPDATE sesiones SET {cols} WHERE id = ?", (*campos.values(), sid))

    # --- mensajes (lo que se pinta en la conversación) ----------------------
    def guardar(self, sid: int, msg: dict[str, Any]) -> None:
        datos = {k: v for k, v in msg.items() if k not in ("seq", "tipo")}
        with self.store._lock:
            self.db.execute(
                "INSERT INTO sesion_mensajes(sesion_id, seq, tipo, datos_json, ts) VALUES(?,?,?,?,?)",
                (sid, int(msg.get("seq") or 0), msg["tipo"], json.dumps(datos, ensure_ascii=False, default=str), now_iso()))
            if msg["tipo"] == "usuario":
                row = self.db.execute("SELECT titulo FROM sesiones WHERE id = ?", (sid,)).fetchone()
                texto = str(datos.get("texto") or "")
                if row is not None and not row["titulo"] and not texto.startswith("/"):
                    self.db.execute("UPDATE sesiones SET titulo = ? WHERE id = ?", (titulo_de(texto), sid))
            self.db.execute("UPDATE sesiones SET actualizada = ? WHERE id = ?", (now_iso(), sid))

    def mensajes(self, sid: int, limit: int = 400) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT seq, tipo, datos_json FROM sesion_mensajes WHERE sesion_id = ? ORDER BY id DESC LIMIT ?",
            (sid, limit)).fetchall()
        return [{"seq": r["seq"], "tipo": r["tipo"], **json.loads(r["datos_json"])} for r in reversed(rows)]

    def max_seq(self) -> int:
        return self.db.execute("SELECT COALESCE(MAX(seq), 0) FROM sesion_mensajes").fetchone()[0]

    def recientes(self, sid: int, n: int = 3) -> list[tuple[str, str]]:
        """Últimos pares (petición, respuesta) de la sesión, para darle al modelo el hilo de la conversación."""
        rows = self.db.execute(
            """SELECT tipo, datos_json FROM sesion_mensajes WHERE sesion_id = ? AND tipo IN ('usuario', 'respuesta')
               ORDER BY id DESC LIMIT ?""", (sid, n * 4)).fetchall()
        pares: list[tuple[str, str]] = []
        respuesta: str | None = None
        for r in rows:  # del más nuevo al más viejo
            texto = str(json.loads(r["datos_json"]).get("texto") or "")
            if r["tipo"] == "respuesta":
                respuesta = texto
            elif respuesta is not None:
                if not texto.startswith("/"):
                    pares.append((texto, respuesta))
                respuesta = None
            if len(pares) >= n:
                break
        return list(reversed(pares))

    # --- tareas y consumo ------------------------------------------------
    def enlazar(self, sid: int, task_id: int) -> None:
        with self.store._lock:
            self.db.execute("INSERT OR IGNORE INTO sesion_tareas(sesion_id, task_id) VALUES(?,?)", (sid, task_id))

    def de_tarea(self, task_id: int) -> int | None:
        row = self.db.execute("SELECT sesion_id FROM sesion_tareas WHERE task_id = ? LIMIT 1", (task_id,)).fetchone()
        return row[0] if row else None

    def tareas(self, sid: int) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT task_id FROM sesion_tareas WHERE sesion_id = ?", (sid,))]

    def consumo(self, sid: int) -> dict[str, Any]:
        row = self.db.execute(
            """SELECT COUNT(*) AS llamadas, COALESCE(SUM(e.tokens_in),0) AS tokens_in,
                      COALESCE(SUM(e.tokens_out),0) AS tokens_out, COALESCE(SUM(e.cost_eur),0) AS cost_eur
               FROM events e JOIN sesion_tareas t ON t.task_id = e.task_id
               WHERE e.type = 'llm' AND t.sesion_id = ?""", (sid,)).fetchone()
        return dict(row)
