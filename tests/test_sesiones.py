"""Sesiones al estilo Claude/Codex y el panel de «lo que ha aprendido» en la web."""
from __future__ import annotations

from conftest import ScriptedLLM
from test_web import wait_until, web  # noqa: F401  (fixture)

from skynet import propuestas
from skynet.sesiones import Sesiones, titulo_de


def test_titulo_de():
    assert titulo_de("  arregla   el login\nde la app ") == "Arregla el login"
    assert titulo_de("") == "Sesión nueva"
    assert len(titulo_de("palabra " * 30)) <= 61


def test_sesiones_guardan_y_dan_contexto(make_rt):
    rt = make_rt(ScriptedLLM([]))
    ses = Sesiones(rt.store)
    a = ses.crear()["id"]
    assert ses.vacia(a)
    ses.guardar(a, {"seq": 1, "tipo": "usuario", "texto": "/doctor"})
    ses.guardar(a, {"seq": 2, "tipo": "usuario", "texto": "hola skynet"})
    ses.guardar(a, {"seq": 3, "tipo": "respuesta", "texto": "hola"})
    assert ses.get(a)["titulo"] == "Hola skynet"          # el comando no da título
    assert ses.recientes(a) == [("hola skynet", "hola")]
    assert [m["tipo"] for m in ses.mensajes(a)] == ["usuario", "usuario", "respuesta"]
    assert ses.lista("skynet")[0]["id"] == a and ses.lista("nada-de-esto") == []
    t = rt.store.create_task("x", "x", agent="chat")
    rt.store.add_event("llm", task_id=t.id, model="m", tokens_in=7, tokens_out=3, cost_eur=0)
    ses.enlazar(a, t.id)
    assert ses.consumo(a)["tokens_in"] == 7 and ses.de_tarea(t.id) == a
    ses.archivar(a)
    assert not ses.existe(a) and ses.lista() == []


def test_sesiones_en_la_web(web):  # noqa: F811
    llm = ScriptedLLM([("Primera respuesta.", None), ("Segunda respuesta.", None)])
    c, rt, app = web(llm)
    s = app.state.session
    first = c.get("/api/estado").json()["sesion"]
    assert first["titulo"] == "" and first["contexto"] == 0
    c.post("/api/mensaje", json={"texto": "primera pregunta"})
    snap = wait_until(c, lambda x: not x["ocupado"] and x["sesion"]["contexto"])
    assert snap["sesion"]["titulo"] == "Primera pregunta"
    assert snap["sesion"]["consumo"]["llamadas"] == 1 and snap["sesion"]["contexto"] == 120
    assert snap["sesion"]["tps"] and snap["sesion"]["tps"] > 0  # tokens/s de la última llamada
    # nueva sesión: vacía y sin el hilo anterior
    nueva = c.post("/api/sesiones/nueva", json={}).json()["sesion"]
    assert nueva["id"] != first["id"] and nueva["contexto"] == 0
    assert c.post("/api/sesiones/nueva", json={}).json()["sesion"]["id"] == nueva["id"]  # vacía: se reutiliza
    c.post("/api/mensaje", json={"texto": "otra cosa"})
    wait_until(c, lambda x: not x["ocupado"])
    msgs = llm.calls[-1]["messages"]
    assert not any("primera pregunta" in str(m.get("content")) for m in msgs)
    # volver a la primera: el modelo vuelve a ver su conversación
    lst = c.get("/api/sesiones").json()
    assert lst["actual"] == nueva["id"] and {x["id"] for x in lst["sesiones"]} == {first["id"], nueva["id"]}
    c.post(f"/api/sesiones/{first['id']}/abrir", json={})
    assert s.sid == first["id"] and "primera pregunta" in (s.coord._recent() or "")
    ev = [m for m in s.bus.history]
    assert ev == []  # al cambiar no se mezclan las conversaciones en el bus
    assert c.post("/api/sesiones/999/abrir", json={}).status_code == 404
    # renombrar y borrar (archivar)
    r = c.post(f"/api/sesiones/{first['id']}", json={"titulo": "  Mi sesión "}).json()
    assert next(x for x in r["sesiones"] if x["id"] == first["id"])["titulo"] == "Mi sesión"
    assert c.post(f"/api/sesiones/{first['id']}", json={"titulo": ""}).status_code == 400
    r = c.post(f"/api/sesiones/{first['id']}/archivar", json={}).json()
    assert [x["id"] for x in r["sesiones"]] == [nueva["id"]] and r["actual"] == nueva["id"]


def test_aprendizaje_aprobar_y_descartar(web):  # noqa: F811
    c, rt, app = web()
    home = rt.settings.home
    t = rt.store.create_task("x", "x", agent="chat")
    propuestas.save_proposal(home, t, "m", "ok", ("probar-cosas", "Cómo probar", "Ejecuta pytest."),
                             [("USER", "Prefiere respuestas cortas")])
    assert c.get("/api/estado").json()["propuestas"] == 2
    items = c.get("/api/aprendizaje").json()["items"]
    assert {i["tipo"] for i in items} == {"skill", "memoria"}
    sk = next(i for i in items if i["tipo"] == "skill")
    assert sk["id"] == "probar-cosas" and "pytest" in sk["texto"]
    assert c.post("/api/aprendizaje/probar-cosas", json={"accion": "x"}).status_code == 400
    assert c.post("/api/aprendizaje/..%2Fetc", json={"accion": "aprobar"}).status_code in (400, 404)
    assert c.post("/api/aprendizaje/memoria", json={"accion": "descartar"}).json()["ok"]
    wait_until(c, lambda x: not x["ocupado"] and x["propuestas"] == 1)
    # aprobar pasa por el permission gate: pregunta y, si dices que sí, se activa
    assert c.post("/api/aprendizaje/probar-cosas", json={"accion": "aprobar"}).json()["ok"]
    q = wait_until(c, lambda x: x["preguntas"])["preguntas"][0]
    c.post("/api/responder", json={"id": q["id"], "respuesta": "s"})
    wait_until(c, lambda x: not x["ocupado"] and x["propuestas"] == 0)
    assert (propuestas.skills_dir(home) / "probar-cosas" / "SKILL.md").is_file()
    assert c.get("/api/aprendizaje").json()["items"] == []
    assert c.post("/api/aprendizaje/probar-cosas", json={"accion": "aprobar"}).status_code == 404
