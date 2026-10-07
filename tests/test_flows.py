"""Flujos completos del MVP con servidores MCP reales y un LLM guionizado."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import ORIGINAL_MOD, FakeUI, ScriptedLLM, tool_call

from jarvis import gitops
from jarvis.coordinator import Coordinator
from jarvis.scheduler import LongTaskRunner
from jarvis.store import EN_CURSO, FALLIDA, HECHA, PAUSADA

GOOD = "VERSION = 1\n\n\ndef doble(x):\n    return 2 * x\n"
BAD = "VERSION = 1\n\n\ndef doble(x):\n    return x\n"
BROKEN = "def doble(x) return x\n"


# --- MVP 1 y 3: tarea de código en chat, con permisos, auditada ------------------
async def test_chat_code_task_with_permission_prompt(make_rt, repo_path):
    llm = ScriptedLLM([
        ("", [tool_call("workspace__read_file", {"path": "mod.py"})]),
        ("", [tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD})]),
        ("", [tool_call("workspace__delete_file", {"path": "README.md"})]),   # destructiva: pregunta
        ("", [tool_call("workspace__run_command", {"command": "python -m pytest -q"})]),
        ("He implementado doble y los tests pasan.", None),
    ])
    rt = make_rt(llm)
    ui = FakeUI(answers=["n"])
    coord = Coordinator(rt, ui)
    assert coord.repo_name == "prueba"
    await coord.handle("implementa doble en mod.py")

    task = rt.store.list_tasks(1)[0]
    assert task.status == HECHA, ui.infos
    assert (repo_path / "mod.py").read_text() == GOOD
    assert len(ui.prompts) == 1 and "DESTRUCTIVE" in ui.prompts[0]
    tools = rt.store.events(task_id=task.id, types=("tool",))
    decisions = {e["tool"]: e["decision"] for e in tools}
    assert decisions["workspace.delete_file"] == "denegado"
    assert decisions["workspace.write_file"] == "permitido"
    assert any(e["type"] == "verifier" and e["detail"]["ok"] for e in rt.store.events(task_id=task.id))
    tot = rt.store.totals(task_id=task.id)
    assert tot["llamadas"] == 5 and tot["tokens_in"] == 500
    assert "verificador OK" in ui.infos[-1]


async def test_verifier_failure_marks_task_failed(make_rt):
    llm = ScriptedLLM([
        ("", [tool_call("workspace__write_file", {"path": "mod.py", "content": BAD})]),
        ("Listo, ya está.", None),
    ])
    rt = make_rt(llm)
    ui = FakeUI()
    await Coordinator(rt, ui).handle("implementa doble")
    task = rt.store.list_tasks(1)[0]
    assert task.status == FALLIDA
    assert any("continúa" in i for i in ui.infos)


async def test_path_escape_denied(make_rt, repo_path):
    llm = ScriptedLLM([
        ("", [tool_call("workspace__write_file", {"path": "../fuera.txt", "content": "x"})]),
        ("No pude.", None),
    ])
    rt = make_rt(llm)
    await Coordinator(rt, FakeUI()).handle("escribe fuera")
    assert not (repo_path.parent / "fuera.txt").exists()
    ev = rt.store.events(types=("tool",))[-1]
    assert ev["decision"] == "denegado"


# --- MVP 2: cerrar, abrir y "continúa" -------------------------------------------
async def test_resume_after_crash(make_rt, repo_path):
    rt1 = make_rt(ScriptedLLM([]))
    task = rt1.store.create_task("implementa doble", "implementa doble en mod.py", agent="jarvis",
                                 repo="prueba", status=EN_CURSO)
    step = rt1.store.start_step(task.id, "chat", "implementa doble")
    rt1.store.add_event("tool", task_id=task.id, step_id=step.id, tool="workspace.read_file",
                        decision="permitido", detail={"args_resumen": "path='mod.py'"})
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(timespec="seconds")
    rt1.store.update_task(task.id, heartbeat_at=old, pid=999999)   # el proceso murió
    rt1.store.close()

    llm = ScriptedLLM([
        ("", [tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD})]),
        ("Retomado y terminado.", None),
    ])
    rt2 = make_rt(llm)
    ui = FakeUI()
    await Coordinator(rt2, ui).handle("continúa")
    t = rt2.store.get_task(task.id)
    assert t.status == HECHA
    first_prompt = llm.calls[0]["messages"][1]["content"]
    assert "implementa doble en mod.py" in first_prompt
    assert "se cortó a medias" in first_prompt and "workspace.read_file" in first_prompt
    assert [s.kind for s in rt2.store.steps_for(task.id)] == ["chat", "reanudar"]


async def test_resume_with_nothing_pending(make_rt):
    rt = make_rt(ScriptedLLM([]))
    ui = FakeUI()
    await Coordinator(rt, ui).handle("continúa")
    assert "No hay" in ui.infos[-1]


# --- MVP 4: router local / cloud --------------------------------------------------
async def test_chat_without_repo_uses_local_model(make_rt, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = ScriptedLLM([("¡Hola, Daniel!", None)])
    rt = make_rt(llm)
    ui = FakeUI()
    coord = Coordinator(rt, ui)
    await coord.handle("/repo ninguno")
    await coord.handle("hola")
    assert llm.calls[0]["model"].startswith("lm_studio/")
    assert "tools" not in llm.calls[0]
    assert ui.answers_given == ["¡Hola, Daniel!"]


async def test_forced_cloud_model_with_budget(make_rt, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    llm = ScriptedLLM([("ok", None)])
    rt = make_rt(llm)
    rt.settings.budget_eur = 5
    coord = Coordinator(rt, FakeUI())
    await coord.handle("/repo ninguno")
    await coord.handle("/modelo cloud")
    await coord.handle("piensa algo difícil")
    assert llm.calls[0]["model"] == "anthropic/claude-opus-5-5"
    assert llm.calls[0]["api_key"] == "x"


# --- MVP 5: tarea larga verificada con commits y PROGRESO.md ----------------------
async def _no_sleep(_s):
    return None


async def test_long_task_rollback_then_success(make_rt, repo_path):
    llm = ScriptedLLM([
        # iteración 1: rompe la sintaxis (pasan menos tests que al empezar) -> rollback
        ("", [tool_call("workspace__write_file", {"path": "mod.py", "content": BROKEN})]),
        ("Probé una versión.", None),
        # iteración 2: avance que no empeora nada (aún falla un test) -> se acepta
        ("", [tool_call("workspace__write_file", {"path": "NOTAS.md", "content": "plan\n"})]),
        ("Apunté el plan.", None),
        # iteración 3: lo arregla y declara el objetivo cumplido
        ("", [tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD})]),
        ("Implementado doble.\nOBJETIVO_CUMPLIDO", None),
    ])
    rt = make_rt(llm)
    task = rt.store.create_task("doble", "haz que pasen los tests", agent="scheduler", repo="prueba",
                                max_hours=1, capabilities={"capacidades": {"cost": "bajo"}})
    final = await LongTaskRunner(rt, task.id, on_event=lambda k, d: None, sleep=_no_sleep).run()
    assert final.status == HECHA and final.iters_done == 3
    steps = [s for s in rt.store.steps_for(task.id) if s.kind == "iteracion"]
    assert [s.status for s in steps] == ["revertida", "avance", "ok"]
    assert all(s.commit_sha for s in steps)
    log = gitops.log_oneline(repo_path, 20)
    assert "it. 1 revertida" in log and "it. 3: Implementado doble." in log
    progreso = (repo_path / "PROGRESO.md").read_text(encoding="utf-8")
    assert "hecha" in progreso and "| 3 | ok |" in progreso
    errores = (repo_path / ".jarvis" / f"tarea-{task.id}" / "ERRORES.md").read_text(encoding="utf-8")
    assert "Iteración 1" in errores
    assert (repo_path / "mod.py").read_text() == GOOD
    assert not gitops.is_dirty(repo_path)
    assert all(c["model"].startswith("lm_studio/") for c in llm.calls)


async def test_long_task_stops_on_repeated_error(make_rt, repo_path):
    def breaker(messages):
        if messages[-1]["role"] == "tool":
            return ("Intenté algo.", None)
        return ("", [tool_call("workspace__write_file", {"path": "mod.py", "content": BROKEN + f"# {len(messages)}\n"})])

    rt = make_rt(ScriptedLLM([breaker] * 40))
    task = rt.store.create_task("doble", "haz que pasen los tests", agent="scheduler", repo="prueba", max_hours=1)
    final = await LongTaskRunner(rt, task.id, on_event=lambda k, d: None, sleep=_no_sleep).run()
    assert final.status == FALLIDA and final.iters_done == rt.settings.long.max_errores_iguales
    assert (repo_path / "mod.py").read_text() == ORIGINAL_MOD


async def test_long_task_time_and_iteration_limits(make_rt):
    rt = make_rt(ScriptedLLM([("Nada que hacer.", None)] * 10))
    task = rt.store.create_task("x", "y", agent="scheduler", repo="prueba", max_hours=1, max_iters=2)
    rt.settings.long.max_sin_avance = 99
    # El verificador falla siempre (doble sin implementar) pero sin cambios: mismo fallo -> se para antes
    final = await LongTaskRunner(rt, task.id, on_event=lambda k, d: None, sleep=_no_sleep).run()
    assert final.status in (PAUSADA, FALLIDA) and final.iters_done <= 2

    clock = iter([0, 0, 10_000, 10_000, 10_000])
    task2 = rt.store.create_task("x", "y", agent="scheduler", repo="prueba", max_hours=1)
    final2 = await LongTaskRunner(rt, task2.id, on_event=lambda k, d: None, sleep=_no_sleep,
                                  clock=lambda: next(clock)).run()
    assert final2.status == PAUSADA and "tiempo" in final2.result_summary


async def test_long_task_stop_requested(make_rt):
    rt = make_rt(ScriptedLLM([]))
    task = rt.store.create_task("x", "y", agent="scheduler", repo="prueba", max_hours=1)

    def stop_after_first(kind, data):
        if kind == "verificador":
            rt.store.update_task(task.id, status=PAUSADA)

    final = await LongTaskRunner(rt, task.id, on_event=stop_after_first, sleep=_no_sleep).run()
    assert final.status == PAUSADA and "parada" in final.result_summary and final.iters_done == 1


# --- comandos del chat -------------------------------------------------------------
async def test_largo_command_creates_and_spawns(make_rt, monkeypatch):
    import jarvis.coordinator as coord_mod

    spawned = []
    monkeypatch.setattr(coord_mod, "spawn_background", lambda rt, tid: spawned.append(tid) or 4242)
    rt = make_rt(ScriptedLLM([]))
    ui = FakeUI(answers=["s"])
    c = Coordinator(rt, ui)
    await c.handle("/largo 1,5 haz que pasen los tests")
    task = rt.store.get_task(spawned[0])
    assert task.agent == "scheduler" and task.max_hours == 1.5 and task.goal == "haz que pasen los tests"
    assert task.capabilities["capacidades"]["cost"] == "bajo"
    # continúa sobre una tarea larga sin runner vivo: la relanza en segundo plano
    rt.store.update_task(task.id, status=PAUSADA)
    await c.handle("continúa")
    assert spawned == [task.id, task.id]


async def test_largo_cancelled(make_rt, monkeypatch):
    import jarvis.coordinator as coord_mod

    monkeypatch.setattr(coord_mod, "spawn_background", lambda rt, tid: 1 / 0)
    rt = make_rt(ScriptedLLM([]))
    ui = FakeUI(answers=["n"])
    await Coordinator(rt, ui).handle("/largo 2 algo")
    assert rt.store.list_tasks() == [] and ui.infos[-1] == "Cancelado."


async def test_info_commands(make_rt):
    rt = make_rt(ScriptedLLM([("hola", None)]))
    ui = FakeUI()
    c = Coordinator(rt, ui)
    await c.handle("/repo ninguno")
    await c.handle("hola")
    for cmd in ("/ayuda", "/repos", "/tareas", "/estado 1", "/log", "/log 1", "/modelo local", "/privado", "/nada"):
        assert await c.handle(cmd)
    assert await c.handle("/salir") is False
    assert any("Comando desconocido" in i for i in ui.infos)
