"""Búsqueda en el historial (FTS5 con triggers, relleno inicial y LIKE de reserva) y /buscar."""
from __future__ import annotations

import sqlite3

import pytest
from conftest import FakeUI, ScriptedLLM

from skynet.coordinator import Coordinator
from skynet.store import MIGRATIONS, Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "j.db")
    yield s
    s.close()


def _fill(store: Store) -> int:
    t = store.create_task("t", "g", agent="skynet")
    s = store.start_step(t.id, "chat", "implementa la función de facturación")
    store.finish_step(s.id, "completado", "Añadida la validación del NIF en clientes.py")
    store.add_event("tool", task_id=t.id, tool="workspace.run_command", detail={"comando": "pytest -q tests/test_pedidos.py"})
    store.add_event("llm", task_id=t.id, model="m")  # sin detalle: no entra en el índice
    return t.id


def test_fts_available_and_triggers(store):
    assert store.fts
    tid = _fill(store)
    hits = store.search("validacion NIF")  # sin tilde también encuentra «validación»
    assert [(h["origen"], h["task_id"]) for h in hits] == [("paso", tid)]
    assert "«NIF»" in hits[0]["fragmento"] and hits[0]["ts"]
    assert store.search("test_pedidos")[0]["origen"] == "evento"
    assert store.search("facturación")  # el input_summary también cuenta
    # finish_step cambia el resumen: el índice se actualiza (trigger UPDATE)
    s = store.start_step(tid, "chat", "x")
    store.finish_step(s.id, "completado", "primero")
    store.finish_step(s.id, "completado", "segundo")
    assert not store.search("primero") and store.search("segundo")
    assert store.search("nada parecido") == []


def test_query_syntax_is_not_interpreted(store):
    _fill(store)
    for q in ('"', "AND", "NIF OR", "cli*", "(", "NEAR(", "  "):
        store.search(q)  # no lanza
    assert store.search("clientes.py")


def test_backfill_existing_v1_database(tmp_path):
    path = tmp_path / "v1.db"
    db = sqlite3.connect(path)
    db.executescript(MIGRATIONS[0])
    db.execute("INSERT INTO tasks(title, goal, agent, status, created_at, updated_at) VALUES('t','g','skynet','hecha','x','x')")
    db.execute("INSERT INTO steps(task_id, n, kind, output_summary, started_at) VALUES(1, 1, 'chat', 'arreglado el parser TOML', 'x')")
    db.execute("INSERT INTO events(ts, task_id, type, tool, detail_json) VALUES('x', 1, 'tool', 'w.read', '{\"ruta\": \"parser.py\"}')")
    db.execute("PRAGMA user_version = 1")
    db.commit()
    db.close()
    s = Store(path)
    try:
        assert s.schema_version() == len(MIGRATIONS)
        assert s.search("parser TOML")[0]["origen"] == "paso"
        assert s.search("parser.py")[0]["origen"] == "evento"
    finally:
        s.close()


def test_like_fallback(store):
    tid = _fill(store)
    store.fts = False  # como si este SQLite no trajera FTS5
    hits = store.search("NIF clientes")
    assert [(h["origen"], h["task_id"]) for h in hits] == [("paso", tid)]
    assert "NIF" in hits[0]["fragmento"]
    assert store.search("test_pedidos")[0]["origen"] == "evento"
    assert store.search("NIF inexistente") == []


async def test_buscar_command(make_rt):
    rt = make_rt(ScriptedLLM([("He revisado el módulo de inventario.", None)]))
    ui = FakeUI()
    c = Coordinator(rt, ui)
    await c.handle("/repo ninguno")
    await c.handle("revisa el inventario")
    await c.handle("/buscar inventario")
    assert "resultados para «inventario»" in ui.infos[-1] and "tarea 1 · paso 1" in ui.infos[-1]
    await c.handle("/buscar zzz")
    assert "Nada en el historial" in ui.infos[-1]
    await c.handle("/buscar")
    assert ui.infos[-1].startswith("Uso: /buscar")
