"""Automejora fase 2: propuestas de skill y memoria, /aprobar por el gate, skill_uses y web."""
from __future__ import annotations

from pathlib import Path

from conftest import FakeUI, ScriptedLLM, tool_call
from test_web import web  # noqa: F401  (fixture)

from skynet import propuestas
from skynet.config import RepoConfig
from skynet.coordinator import Coordinator
from skynet.gate import Decision, PermissionGate
from skynet.store import HECHA

GOOD = "VERSION = 1\n\n\ndef doble(x):\n    return 2 * x\n"
RESPUESTA = """```markdown
---
name: Implementar Funciones Con Tests
description: Implementar una función pendiente hasta que pase pytest.
---
# Implementar funciones
1. Lee el test.
2. Implementa lo mínimo.
===MEMORIA===
- [MEMORY] El verificador del repo prueba es python -m pytest -q.
- [USER] Prefiere cambios mínimos.
- [MEMORY] segunda
- [MEMORY] tercera (sobra: tope de 3)
```"""


class T:  # lo mínimo de Task que usa save_proposal
    id, title = 7, "tarea de prueba"


# --- formato --------------------------------------------------------------------
def test_parse_response():
    skill, mem = propuestas.parse_response(RESPUESTA)
    assert skill[0] == "implementar-funciones-con-tests" and skill[1].startswith("Implementar una")
    assert skill[2].startswith("# Implementar funciones") and "===" not in skill[2]
    assert mem == [("MEMORY", "El verificador del repo prueba es python -m pytest -q."),
                   ("USER", "Prefiere cambios mínimos."), ("MEMORY", "segunda")]
    assert propuestas.parse_response("NINGUNA\n===MEMORIA===\nNINGUNO") == (None, [])
    assert propuestas.parse_response("texto libre sin formato") == (None, [])


def test_save_list_approve_reject(tmp_path: Path):
    home = tmp_path
    skill, mem = propuestas.parse_response(RESPUESTA)
    assert propuestas.save_proposal(home, T, "m", "PASA", skill, mem) == ["implementar-funciones-con-tests", "memoria"]
    # el mismo nombre otra vez: no pisa, sufijo; la memoria repetida no se duplica
    assert propuestas.save_proposal(home, T, "m", "PASA", skill, mem) == ["implementar-funciones-con-tests-2"]
    skl, pend = propuestas.list_proposals(home)
    assert [p["nombre"] for p in skl] == ["implementar-funciones-con-tests", "implementar-funciones-con-tests-2"]
    assert "tarea 7" in skl[0]["origen"] and len(pend) == 3
    assert propuestas.count(home) == 3

    msg = propuestas.approve(home, "implementar-funciones-con-tests")
    assert "activada" in msg and (home / "skills" / "implementar-funciones-con-tests" / "ORIGEN.md").exists()
    msg = propuestas.approve(home, "memoria")
    assert "3 líneas" in msg
    assert "- segunda" in (home / "memoria" / "MEMORY.md").read_text(encoding="utf-8")
    assert "cambios mínimos" in (home / "memoria" / "USER.md").read_text(encoding="utf-8")
    assert propuestas.read_memory(home).keys() == {"MEMORY", "USER"}
    assert propuestas.reject(home, "implementar-funciones-con-tests-2")
    assert propuestas.count(home) == 0
    for bad in ("../skills", "a/b", "..", "MAYUS"):
        try:
            propuestas.exists(home, bad)
            raise AssertionError(bad)
        except ValueError:
            pass


def test_memory_cap(tmp_path: Path):
    big = [("USER", "x" * 190) for _ in range(3)]
    for i in range(4):
        propuestas.save_proposal(tmp_path, T, "m", "OK", None, [(d, t + str(i) + str(j)) for j, (d, t) in enumerate(big)])
    try:
        propuestas.approve(tmp_path, "memoria")
        raise AssertionError("debía pasar del tope")
    except ValueError as e:
        assert "2048" in str(e)
    assert not (tmp_path / "memoria" / "USER.md").exists()  # todo o nada


# --- gate -------------------------------------------------------------------------
def test_gate_denies_writes_to_skills_and_memory(make_rt, home):
    rt = make_rt(ScriptedLLM([]))
    repo = RepoConfig(nombre="skynet", ruta=home)  # el propio Skynet como repo autorizado
    gate = PermissionGate(rt.settings, repo, rt.audit)
    for path in ("skills/x/SKILL.md", "skills/_propuestas/x/SKILL.md", "memoria/USER.md", str(home / "memoria" / "MEMORY.md")):
        assert gate.evaluate("workspace.write_file", {"path": path, "content": ""}).decision is Decision.DENY, path
    assert gate.evaluate("workspace.write_file", {"path": "otro.md", "content": ""}).decision is Decision.ALLOW
    assert gate.evaluate("workspace.read_file", {"path": "skills/x/SKILL.md"}).decision is Decision.ALLOW
    assert gate.classify("skynet.aprobar").name == "PRIVILEGED"


# --- flujo completo -------------------------------------------------------------
async def test_verified_task_with_3_steps_proposes_and_approve_flow(make_rt, home, repo_path):
    llm = ScriptedLLM([
        ("", [tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD})]),
        ("Hecho: doble implementada.", None),
        (RESPUESTA, None),  # redacción de la propuesta
    ])
    rt = make_rt(llm)
    task = rt.store.create_task("doble", "implementa doble en mod.py", agent="skynet", repo="prueba")
    for i in range(2):  # dos pasos previos (p. ej. sesiones cortadas)
        s = rt.store.start_step(task.id, "chat", "x")
        rt.store.finish_step(s.id, "interrumpido", f"paso previo {i}")
    ui = FakeUI(answers=["n", "s"])
    c = Coordinator(rt, ui)
    await c.resume(None, task.id)
    assert rt.store.get_task(task.id).status == HECHA, ui.infos
    # el prompt de la propuesta lleva objetivo, pasos y verificador; sin herramientas
    prompt = llm.calls[-1]["messages"][-1]["content"]
    assert "implementa doble" in prompt and "paso previo 1" in prompt and "PASA" in prompt
    assert "tools" not in llm.calls[-1]
    assert any("Propuestas nuevas" in i for i in ui.infos)
    assert (home / "skills" / "_propuestas" / "implementar-funciones-con-tests" / "SKILL.md").exists()

    await c.handle("/propuestas")
    assert "implementar-funciones-con-tests" in ui.infos[-1] and "[USER]" in ui.infos[-1]
    await c.handle("/aprobar implementar-funciones-con-tests")  # responde «n»
    assert ui.infos[-1] == "No aprobada." and "PRIVILEGED" in ui.prompts[-1]
    await c.handle("/aprobar implementar-funciones-con-tests")  # responde «s»
    assert "activada" in ui.infos[-1]
    assert (home / "skills" / "implementar-funciones-con-tests" / "SKILL.md").exists()
    perms = rt.store.events(types=("permission",))
    assert [e["decision"] for e in perms[-2:]] == ["denegado", "permitido"]
    assert any(e["decision"] == "aprobada" for e in rt.store.events(types=("propuesta",)))
    await c.handle("/rechazar memoria")
    assert "descartados" in ui.infos[-1] and propuestas.count(home) == 0
    await c.handle("/aprobar ../../x")
    assert "no válido" in ui.infos[-1]
    await c.handle("/aprobar nada")
    assert "No hay ninguna propuesta" in ui.infos[-1]


async def test_short_or_unverified_task_does_not_propose(make_rt, home):
    llm = ScriptedLLM([("", [tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD})]), ("Hecho.", None)])
    rt = make_rt(llm)
    c = Coordinator(rt, FakeUI())
    await c.handle("implementa doble")  # 1 paso: no hay propuesta
    assert len(llm.calls) == 2 and propuestas.count(home) == 0


async def test_skill_uses_and_success_rate(make_rt, home):
    d = home / "skills" / "doblar"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: doblar\ndescription: Doblar.\n---\nMultiplica por 2.\n", encoding="utf-8")
    llm = ScriptedLLM([("", [tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD})]), ("Hecho.", None)])
    rt = make_rt(llm)
    ui = FakeUI()
    c = Coordinator(rt, ui)
    await c.handle("/skill doblar implementa doble")
    rows = [dict(r) for r in rt.store.db.execute("SELECT * FROM skill_uses")]
    assert len(rows) == 1 and rows[0]["skill"] == "doblar" and rows[0]["verifier_ok"] == 1 and len(rows[0]["version"]) == 8
    rt.store.add_skill_use("doblar", "x", rows[0]["task_id"])  # un uso sin verificador no cuenta en la tasa
    await c.handle("/skills")
    assert any("doblar: Doblar. · 2 usos, verificador OK 1/1 (100 %)" in i for i in ui.infos)


async def test_memory_always_in_context(make_rt, home):
    (home / "memoria").mkdir()
    (home / "memoria" / "MEMORY.md").write_text("# Memoria\n- El PC tiene una RX 9070 XT.\n" + "y" * 5000, encoding="utf-8")
    (home / "memoria" / "USER.md").write_text("- Daniel prefiere español.\n", encoding="utf-8")
    llm = ScriptedLLM([("ok", None), ("ok", None)])
    rt = make_rt(llm)
    c = Coordinator(rt, FakeUI())
    await c.handle("/repo ninguno")
    await c.handle("hola")
    await c.handle("/repo prueba")
    await c.handle("qué hay")
    for call in llm.calls:
        ctx = "\n".join(str(m.get("content")) for m in call["messages"])
        assert "RX 9070 XT" in ctx and "prefiere español" in ctx and "y" * 2100 not in ctx


def test_web_counter(web, home):  # noqa: F811
    c, rt, _ = web()
    assert c.get("/api/estado").json()["propuestas"] == 0
    propuestas.save_proposal(home, T, "m", "OK", ("una-skill", "Desc.", "Cuerpo"), [("USER", "algo")])
    assert c.get("/api/estado").json()["propuestas"] == 2
