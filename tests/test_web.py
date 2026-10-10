"""Interfaz web: la API HTTP sobre el Coordinator real (LLM guionizado, MCP real)."""
from __future__ import annotations

import asyncio
import time

import pytest
from conftest import ScriptedLLM, tool_call
from starlette.testclient import TestClient

from skynet.store import FALLIDA, HECHA, PAUSADA
from skynet.web.server import Bus, create_app

GOOD_MOD = "VERSION = 1\n\n\ndef doble(x):\n    return 2 * x\n"


def wait_until(client: TestClient, pred, timeout: float = 20.0) -> dict:
    end = time.monotonic() + timeout
    snap = {}
    while time.monotonic() < end:
        snap = client.get("/api/estado").json()
        if pred(snap):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"timeout; último estado: {snap}")


@pytest.fixture
def web(make_rt):
    clients = []

    def _make(llm=None, port=None):
        rt = make_rt(llm or ScriptedLLM([]))
        app = create_app(rt, port)
        c = TestClient(app, base_url=f"http://127.0.0.1:{port}" if port else "http://testserver")
        c.__enter__()
        clients.append(c)
        return c, rt, app

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


def test_estado_basico(web):
    c, rt, _ = web()
    s = c.get("/api/estado").json()
    assert s["repo"] == "prueba" and s["modelo"] == "local" and s["privado"] is False
    assert s["ocupado"] is False and s["preguntas"] == []
    assert {m["nombre"] for m in s["modelos"]} >= {"local", "cloud"}
    assert any(r["nombre"] == "prueba" and r["existe"] for r in s["repos"])
    assert c.get("/").status_code == 200
    assert c.get("/static/js/app.js").status_code == 200
    assert c.get("/static/js/app.js").headers["cache-control"] == "no-cache"
    assert c.get("/static/css/app.css").headers["cache-control"] == "no-cache"
    assert c.get("/static/cursors/arrow.svg").status_code == 200


def test_solo_local_host_origen_y_json(web):
    c, _, _ = web(port=8765)
    assert c.get("/api/estado").status_code == 200
    # DNS rebinding: otra web resolviendo a 127.0.0.1 llega con su propio Host
    assert c.get("/api/estado", headers={"Host": "evil.example:8765"}).status_code == 403
    # CSRF: una página de otro origen no puede mandar órdenes
    r = c.post("/api/mensaje", json={"texto": "hola"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    # sin JSON (formularios simples entre orígenes) tampoco
    r = c.post("/api/mensaje", content="texto=hola", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 403


def test_tarea_con_permiso_desde_la_web(web, repo_path):
    llm = ScriptedLLM([
        ("", [tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD_MOD})]),
        ("", [tool_call("workspace__run_command", {"command": "pip install algo"})]),   # fuera de lista: pregunta
        ("", [tool_call("workspace__run_command", {"command": "python -m pytest -q"})]),
        ("Hecho: doble implementada.", None),
    ])
    c, rt, app = web(llm)
    feed = app.state.session.bus.subscribe()
    assert c.post("/api/ajustes", json={"coder": True}).json()["coder"] is True
    assert c.post("/api/mensaje", json={"texto": "implementa doble"}).json()["ok"]
    snap = wait_until(c, lambda s: s["preguntas"])
    q = snap["preguntas"][0]
    assert q["clase"] == "permiso" and q["nivel"] == "EXECUTE" and "pip install" in q["args"] and q["todas"]
    # mientras trabaja no acepta otro mensaje
    assert c.post("/api/mensaje", json={"texto": "otra cosa"}).status_code == 409
    assert c.post("/api/responder", json={"id": q["id"], "respuesta": "n"}).json()["ok"]
    wait_until(c, lambda s: not s["ocupado"])
    task = rt.store.list_tasks(1)[0]
    assert task.status == HECHA
    assert (repo_path / "mod.py").read_text() == GOOD_MOD
    perm = [e for e in rt.store.events(task_id=task.id, types=("permission",))]
    assert perm and perm[0]["decision"] == "denegado"
    # la conversación queda en el bus para las pestañas que se abran después
    kinds = [m["tipo"] for m in app.state.session.bus.history]
    assert "usuario" in kinds and "respuesta" in kinds and "evento" in kinds
    # la foto de estado que se emite al terminar ya dice que está libre (antes decía ocupado)
    sent = []
    while not feed.empty():
        sent.append(feed.get_nowait())
    assert [m for m in sent if m["tipo"] == "estado"][-1]["ocupado"] is False
    assert [m["ocupado"] for m in sent if m["tipo"] == "ocupado"] == [True, False]
    # una pregunta ya respondida no se puede responder otra vez
    assert c.post("/api/responder", json={"id": q["id"], "respuesta": "s"}).status_code == 404


def test_detener_deja_la_tarea_pausada(web):
    async def slow(**kw):
        await asyncio.sleep(30)

    c, rt, _ = web(slow)
    c.post("/api/mensaje", json={"texto": "algo lento"})
    wait_until(c, lambda s: s["ocupado"])
    assert c.post("/api/cancelar", json={}).json()["cancelado"] is True
    wait_until(c, lambda s: not s["ocupado"])
    assert rt.store.list_tasks(1)[0].status == PAUSADA


def test_ajustes(web):
    c, _, _ = web()
    s = c.post("/api/ajustes", json={"repo": "ninguno", "modelo": "local", "privado": True}).json()
    assert s["repo"] is None and s["modelo"] == "local" and s["privado"] is True
    assert c.post("/api/ajustes", json={"repo": "no-existe"}).status_code == 400
    assert c.post("/api/ajustes", json={"modelo": "inventado"}).status_code == 400
    assert c.post("/api/ajustes", json={"modelo": "auto"}).status_code == 400  # ya no hay modo automático (D21)
    s = c.post("/api/ajustes", json={"repo": "prueba", "modelo": "local", "privado": False}).json()
    assert s["repo"] == "prueba" and s["modelo"] == "local" and not s["privado"]


def test_internet_switch_and_privacy(web):
    c, rt, app = web()
    assert c.get("/api/estado").json()["internet"] is False
    assert c.post("/api/ajustes", json={"internet": "false"}).status_code == 400
    assert c.post("/api/ajustes", json={"internet": True}).json()["internet"] is True
    assert c.post("/api/ajustes", json={"internet": False}).json()["internet"] is False
    app.state.session.running = True
    assert c.post("/api/ajustes", json={"internet": True}).status_code == 409
    app.state.session.running = False
    s = c.post("/api/ajustes", json={"privado": True}).json()
    assert s["internet"] is False and s["internet_bloqueado"] is True
    assert c.post("/api/ajustes", json={"internet": True}).status_code == 400
    c.post("/api/ajustes", json={"privado": False})
    rt.settings.repos["prueba"].privacidad = "alta"
    assert c.get("/api/estado").json()["internet_bloqueado"] is True
    assert c.post("/api/ajustes", json={"internet": True}).status_code == 400


def test_tareas_detalle_y_acciones(web):
    c, rt, _ = web()
    t = rt.store.create_task("x", "objetivo x", agent="skynet", repo="prueba", status=PAUSADA)
    rt.store.add_event("llm", task_id=t.id, model="m", tokens_in=10, tokens_out=5, cost_eur=0.01)
    lst = c.get("/api/tareas").json()
    assert lst[0]["id"] == t.id and lst[0]["vivo"] is False
    d = c.get(f"/api/tareas/{t.id}").json()
    assert d["tarea"]["goal"] == "objetivo x" and d["consumo"]["tokens_in"] == 10
    assert d["eventos"][0]["descripcion"] is not None
    assert c.get("/api/tareas/9999").status_code == 404
    assert c.post(f"/api/tareas/{t.id}/descartar", json={}).json()["ok"]
    assert rt.store.get_task(t.id).status == FALLIDA
    assert c.post(f"/api/tareas/{t.id}/parar", json={}).status_code == 400   # ya terminó
    log = c.get(f"/api/log?tarea={t.id}").json()
    assert log["total"]["llamadas"] == 1 and log["eventos"]


def test_continuar_una_tarea_concreta(web):
    llm = ScriptedLLM([("Listo, retomada.", None)])
    c, rt, _ = web(llm)
    old = rt.store.create_task("vieja", "tarea vieja", agent="chat", status=PAUSADA)
    rt.store.create_task("nueva", "tarea nueva", agent="chat", status=PAUSADA)
    assert c.post(f"/api/tareas/{old.id}/continuar", json={}).json()["ok"]
    wait_until(c, lambda s: not s["ocupado"])
    assert rt.store.get_task(old.id).status == HECHA
    assert rt.store.steps_for(old.id)[-1].kind == "reanudar"


def test_comando_doctor_va_a_la_web(web):
    c, _, app = web()
    c.post("/api/mensaje", json={"texto": "/doctor"})
    wait_until(c, lambda s: not s["ocupado"], timeout=60)
    diag = [m for m in app.state.session.bus.history if m["tipo"] == "diagnostico"]
    assert diag and any(ch["nombre"] == "Base de datos" and ch["estado"] == "ok" for ch in diag[0]["checks"])


async def test_bus_reparte_y_guarda_historial():
    bus = Bus()
    q = bus.subscribe()
    bus.publish("evento", {"kind": "thinking"})
    bus.publish("respuesta", {"texto": "hola"})
    bus.publish("ocupado", {"ocupado": False})
    got = [q.get_nowait()["tipo"] for _ in range(3)]
    assert got == ["evento", "respuesta", "ocupado"]
    # "pensando" y los cambios de estado no se repiten al reconectar; la respuesta sí
    assert [m["tipo"] for m in bus.history] == ["respuesta"]
    bus.unsubscribe(q)
    bus.publish("info", {"texto": "x"})
    assert q.empty()
