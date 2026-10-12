"""Tokens reales por intervalo y puesta a cero al terminar o perder conexión."""
import asyncio
import pytest

from skynet.web.server import Bus, Session
from skynet.web.velocidad import ContadorTokens


def slot(n, task=1, array=True):
    token = {"n_decoded": n}
    return [{"id": 0, "id_task": task, "is_processing": True,
             "next_token": [token] if array else token}]


def test_rate_uses_deltas_not_completion_average():
    c = ContadorTokens()
    assert c.medir([], 0) == 0
    assert c.medir(slot(32), 1) == 32
    assert c.medir(slot(79), 2) == 47
    assert c.medir(slot(79), 3) == 0
    assert c.medir(slot(99, array=False), 3.5) == 40
    assert c.medir([{"is_processing": False}], 4) == 0
    assert c.medir(slot(22, task=2), 5) == 22


def test_counter_reset_failure_and_prefill():
    c = ContadorTokens()
    assert c.medir(slot(1000), 1) == 0  # Conexión nueva: no cuenta tokens anteriores.
    assert c.medir(slot(0), 2) == 0
    assert c.medir(slot(20), 3) == 20
    assert c.medir(None, 4) == 0
    assert c.medir(slot(200), 5) == 0
    assert c.medir(slot(0, task=2), 6) == 0


def test_speed_events_are_ephemeral():
    persisted = []
    b = Bus(sink=persisted.append)
    q = b.subscribe()
    b.publish("evento", {"kind": "speed", "datos": {"tok_s": 40}})
    assert q.get_nowait()["datos"]["tok_s"] == 40
    assert not persisted and not b.history


@pytest.mark.parametrize('running', [True, False])
async def test_live_counter_and_release(make_rt, monkeypatch, running):
    from skynet import engines

    readings = iter([slot(0), slot(37), slot(37)])
    monkeypatch.setattr(engines, "_get_json", lambda *args: next(readings, None))
    s = Session(make_rt())
    s.running = running
    s._route_speed({"model": s.rt.settings.models["local"].litellm, "perfil": "local"})
    assert s._speed_url.endswith("/slots")
    q = s.bus.subscribe()
    s._speed_task = asyncio.create_task(s._speed())
    first = await asyncio.wait_for(q.get(), 1)
    second = await asyncio.wait_for(q.get(), 2)
    assert first["datos"]["tok_s"] == 0
    assert 30 <= second["datos"]["tok_s"] <= 45
    s._usage({"tokens_in": 100, "tokens_out": 600, "segundos": 1})
    assert s.tps == second["datos"]["tok_s"]
    task = s._speed_task
    s._release()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert s.sesion_info()["tps"] == 0 and not s.busy


def test_other_engine_with_same_model_name_does_not_count_local(make_rt):
    s = Session(make_rt())
    s._route_speed({"model": 'openai/local', "perfil": 'hermes'})
    assert s._speed_url is None
