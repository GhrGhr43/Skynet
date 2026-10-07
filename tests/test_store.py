from datetime import datetime, timedelta, timezone

import pytest

from skynet.store import EN_CURSO, HECHA, MIGRATIONS, PAUSADA, Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "j.db")
    yield s
    s.close()


def test_schema_version(store):
    assert store.schema_version() == len(MIGRATIONS)


def test_task_lifecycle(store):
    t = store.create_task("t", "objetivo", agent="skynet", repo="r", capabilities={"capacidades": {"cost": "bajo"}})
    assert t.status == "pendiente" and t.capabilities["capacidades"]["cost"] == "bajo"
    t = store.update_task(t.id, status=EN_CURSO, iters_done=2)
    assert t.status == EN_CURSO and t.iters_done == 2
    with pytest.raises(ValueError):
        store.update_task(t.id, status="inventado")
    with pytest.raises(ValueError):
        store.update_task(t.id, repo="otro")


def test_steps_numbering(store):
    t = store.create_task("t", "g", agent="skynet")
    s1 = store.start_step(t.id, "chat", "a")
    s2 = store.start_step(t.id, "chat", "b")
    assert (s1.n, s2.n) == (1, 2)
    store.finish_step(s1.id, "completado", "hecho", "PASA", "abc")
    steps = store.steps_for(t.id)
    assert steps[0].ended_at and steps[0].commit_sha == "abc" and steps[1].ended_at is None


def test_events_and_totals(store):
    t = store.create_task("t", "g", agent="skynet")
    store.add_event("llm", task_id=t.id, model="m", tokens_in=10, tokens_out=5, cost_eur=0.5)
    store.add_event("llm", task_id=t.id, model="m", tokens_in=1, tokens_out=1, cost_eur=0.25)
    store.add_event("tool", task_id=t.id, tool="workspace.read_file", decision="permitido", detail={"x": 1})
    tot = store.totals(task_id=t.id)
    assert tot == {"llamadas": 2, "tokens_in": 11, "tokens_out": 6, "cost_eur": 0.75}
    assert store.month_cost_eur() == pytest.approx(0.75)
    evs = store.events(task_id=t.id, types=("tool",))
    assert len(evs) == 1 and evs[0]["detail"] == {"x": 1}


def test_last_resumable(store):
    a = store.create_task("a", "g", agent="skynet")
    b = store.create_task("b", "g", agent="skynet")
    store.set_status(b.id, HECHA)
    store.set_status(a.id, PAUSADA)
    assert store.last_resumable_task().id == a.id
    store.set_status(a.id, HECHA)
    assert store.last_resumable_task() is None


def test_heartbeat_staleness(store):
    t = store.create_task("a", "g", agent="scheduler")
    store.heartbeat(t.id)  # pid de este proceso: vivo
    assert store.get_task(t.id).runner_alive()
    store.heartbeat(t.id, pid=999_999_9)  # latido reciente pero el proceso ya no existe
    assert not store.get_task(t.id).runner_alive()
    store.heartbeat(t.id)
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
    store.update_task(t.id, heartbeat_at=old)
    assert not store.get_task(t.id).runner_alive()


def test_reopen_keeps_data(tmp_path):
    s = Store(tmp_path / "j.db")
    t = s.create_task("a", "g", agent="skynet")
    s.close()
    s2 = Store(tmp_path / "j.db")
    assert s2.get_task(t.id).title == "a"
    s2.close()
