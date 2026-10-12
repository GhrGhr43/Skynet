"""Recuperación de respuestas cortadas y continuación de tareas de código sin intervención."""
from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from conftest import FakeUI, ScriptedLLM, coder, make_response, tool_call
from skynet.agent import Agent
from skynet.coordinator import Coordinator
from skynet.router import Capabilities
from skynet.store import FALLIDA, HECHA, PAUSADA

GOOD = "VERSION = 1\n\ndef doble(x):\n    return 2 * x\n"
BAD = "VERSION = 1\n\ndef doble(x):\n    return x\n"


def raw_call(arguments, finish="tool_calls", content=""):
    msg = SimpleNamespace(content=content, tool_calls=[SimpleNamespace(
        id="cut", type="function", function=SimpleNamespace(name="workspace__write_file", arguments=arguments))])
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish)],
                           usage=SimpleNamespace(prompt_tokens=100, completion_tokens=8192))


class Responses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.mark.parametrize("first", [
    raw_call('{"path":"mod.py","content":"def doble(x):', "length"),
    # Aunque sea reparable (o incluso JSON completo), length nunca debe escribir código parcial.
    raw_call(json.dumps({"path": "mod.py", "content": BAD}), "length"),
    raw_call('{"path":"mod.py","content":"def doble(x):'),
    RuntimeError("Failed to parse tool call arguments as JSON: missing closing quote"),
    RuntimeError("litellm.APIConnectionError: Response payload is not completed"),
])
async def test_recovery_discards_bad_call_and_builds_by_edits(make_rt, repo_path, first):
    llm = Responses(first,
        make_response(calls=[tool_call("workspace__write_file", {"path": "mod.py", "content": BAD})]),
        make_response(calls=[tool_call("workspace__edit_file", {
            "path": "mod.py", "old_text": "return x", "new_text": "return 2 * x"})]),
        make_response("Hecho y comprobado."))
    rt = make_rt(llm)
    await coder(Coordinator(rt, FakeUI())).handle("Construye la aplicación por partes")
    task = rt.store.list_tasks(1)[0]
    assert task.status == HECHA
    assert (repo_path / "mod.py").read_text() == GOOD
    # Ninguna petición posterior puede llevar el JSON roto ni una llamada sin resultado.
    assert not any(m.get("tool_calls") for m in llm.calls[1]["messages"])
    writes = [e for e in rt.store.events(task_id=task.id, types=("tool",))
              if e["tool"] == "workspace.write_file" and e["decision"] == "permitido"]
    assert len(writes) == 1
    assert rt.store.events(task_id=task.id, types=("recuperacion",))


async def test_repaired_args_are_valid_json_in_next_request(make_rt):
    llm = Responses(raw_call('{"path":"mod.py","content":' + json.dumps(GOOD) + ',}'),
                    make_response("Hecho."))
    await coder(Coordinator(make_rt(llm), FakeUI())).handle("implementa doble")
    calls = [tc for m in llm.calls[1]["messages"] for tc in m.get("tool_calls", [])]
    assert json.loads(calls[0]["function"]["arguments"])["content"] == GOOD


async def test_repeated_truncation_stops_and_keeps_previous_changes(make_rt, repo_path):
    cut = raw_call('{"path":"mod.py","content":"unfinished', "length")
    llm = Responses(make_response(calls=[tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD})]),
                    cut, cut, cut)
    rt = make_rt(llm)
    await coder(Coordinator(rt, FakeUI())).handle("implementa doble")
    assert rt.store.list_tasks(1)[0].status == FALLIDA
    assert len(llm.calls) == 4 and (repo_path / "mod.py").read_text() == GOOD


async def test_text_cut_is_not_reported_complete(make_rt):
    response = make_response("Aquí está el código incompleto")
    response.choices[0].finish_reason = "length"
    llm = Responses(response, make_response("Respuesta completa."))
    rt = make_rt(llm)
    outcome = await Agent(rt.router, None, None, rt.audit).run("sistema", "pregunta", Capabilities())
    assert outcome.status == "completado" and outcome.final_text == "Respuesta completa."
    assert len(llm.calls) == 2


async def test_read_loop_keeps_evidence_and_can_return_to_editing(make_rt, repo_path):
    (repo_path / "mod.py").write_text(GOOD, encoding="utf-8")
    reads = [make_response(calls=[tool_call("workspace__read_file", {
        "path": "mod.py", "offset": n, "limit": 1})]) for n in range(5)]
    llm = Responses(*reads,
        make_response(calls=[tool_call("workspace__edit_file", {
            "path": "mod.py", "old_text": "return 2 * x", "new_text": "return x + x"})]),
        make_response("Hecho y comprobado."))
    rt = make_rt(llm)
    await coder(Coordinator(rt, FakeUI())).handle("Revisa e implementa doble")
    request = llm.calls[5]["messages"]
    assert "siguiente cambio pequeño" in request[-1]["content"]
    assert sum(m["role"] == "tool" for m in request) == 5
    assert (repo_path / "mod.py").read_text().endswith("return x + x\n")
    assert rt.store.list_tasks(1)[0].status == HECHA


@pytest.mark.parametrize("name,args", [
    ("workspace__read_file", {"path": "mod.py"}),
    ("workspace__run_command", {"command": "python -m pytest -q"}),
])
async def test_same_read_or_verifier_can_run_after_each_edit(make_rt, repo_path, name, args):
    (repo_path / "mod.py").write_text(GOOD, encoding="utf-8")
    check = lambda: make_response(calls=[tool_call(name, args)])
    llm = Responses(check(),
        make_response(calls=[tool_call("workspace__edit_file", {
            "path": "mod.py", "old_text": "return 2 * x", "new_text": "return x + x"})]), check(),
        make_response(calls=[tool_call("workspace__edit_file", {
            "path": "mod.py", "old_text": "return x + x", "new_text": "return sum([x, x])"})]), check(),
        make_response("Hecho y comprobado."))
    rt = make_rt(llm)
    await coder(Coordinator(rt, FakeUI())).handle("Mejora y comprueba doble por partes")
    events = [e for e in rt.store.events(types=("tool",)) if e["tool"] == name.replace("__", ".")]
    assert sum(e["decision"] == "permitido" for e in events) == 3
    assert not any(e["decision"] == "bloqueado" for e in events)
    assert rt.store.list_tasks(1)[0].status == HECHA


async def test_loading_model_waits_and_remains_cancellable(make_rt, monkeypatch):
    waits = []

    async def wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr("skynet.agent.asyncio.sleep", wait)
    llm = Responses(RuntimeError('HTTP 503 loading model'), make_response('Respuesta completa.'))
    rt = make_rt(llm)
    outcome = await Agent(rt.router, None, None, rt.audit).run('sistema', 'pregunta', Capabilities())
    assert outcome.status == 'completado' and waits == [30]

    async def cancel(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr("skynet.agent.asyncio.sleep", cancel)
    llm = Responses(RuntimeError('HTTP 503 loading model'))
    rt = make_rt(llm)
    with pytest.raises(asyncio.CancelledError):
        await Agent(rt.router, None, None, rt.audit).run('sistema', 'pregunta', Capabilities())
    assert len(llm.calls) == 1


async def test_coder_continues_after_turn_limit_and_reloads_plan(make_rt, repo_path):
    llm = Responses(
        make_response(calls=[tool_call("workspace__write_file", {
            "path": ".skynet/tarea-1/PLAN.md", "content": "- [x] Esqueleto\n- [ ] Implementar doble"}),
                            tool_call("workspace__write_file", {"path": "mod.py", "content": BAD})]),
        make_response(calls=[tool_call("workspace__edit_file", {
            "path": "mod.py", "old_text": "return x", "new_text": "return 2 * x"}),
                             tool_call("workspace__edit_file", {
            "path": ".skynet/tarea-1/PLAN.md", "old_text": "- [ ] Implementar doble", "new_text": "- [x] Implementar doble"})]),
        make_response("Hecho."))
    rt = make_rt(llm)
    rt.settings.agent.max_turnos = 1
    ui = FakeUI()
    await coder(Coordinator(rt, ui)).handle("implementa doble")
    task = rt.store.list_tasks(1)[0]
    assert task.status == HECHA and (repo_path / "mod.py").read_text() == GOOD
    assert [s.kind for s in rt.store.steps_for(task.id)] == ["chat", "continuacion", "continuacion"]
    assert "- [ ] Implementar doble" in llm.calls[1]["messages"][1]["content"]
    assert len(ui.answers_given) == 1 and not ui.prompts
    assert any("360 tokens" in info for info in ui.infos)  # suma los tres bloques, no solo el último


async def test_unfinished_plan_prevents_premature_completion(make_rt):
    llm = Responses(make_response(calls=[tool_call("workspace__write_file", {
        "path": ".skynet/tarea-1/PLAN.md", "content": "- [ ] Implementar doble"})]),
        make_response("Ya está."),
        make_response(calls=[tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD}),
                            tool_call("workspace__edit_file", {"path": ".skynet/tarea-1/PLAN.md",
                                "old_text": "- [ ] Implementar doble", "new_text": "- [x] Implementar doble"})]),
        make_response("Comprobado."))
    rt = make_rt(llm)
    ui = FakeUI()
    await coder(Coordinator(rt, ui)).handle("implementa doble")
    assert rt.store.list_tasks(1)[0].status == HECHA
    assert len(llm.calls) == 4 and ui.answers_given == ["Comprobado."]


async def test_limit_without_code_progress_does_not_continue(make_rt):
    llm = ScriptedLLM([("", [tool_call("workspace__write_file", {
        "path": ".skynet/tarea-1/PLAN.md", "content": "Pendiente"})])])
    rt = make_rt(llm)
    rt.settings.agent.max_turnos = 1
    await coder(Coordinator(rt, FakeUI())).handle("haz la aplicación")
    assert rt.store.list_tasks(1)[0].status == PAUSADA and len(llm.calls) == 1


async def test_continuation_budget_is_bounded(make_rt):
    llm = Responses(*[make_response(calls=[tool_call("workspace__write_file", {
        "path": "mod.py", "content": content})]) for content in (BAD, GOOD)])
    rt = make_rt(llm)
    rt.settings.agent.max_turnos = 1
    rt.settings.agent.max_continuaciones = 1
    await coder(Coordinator(rt, FakeUI())).handle("implementa doble")
    assert rt.store.list_tasks(1)[0].status == PAUSADA and len(llm.calls) == 2


async def test_verifier_failure_repaired_without_user_continue(make_rt, repo_path):
    llm = Responses(make_response(calls=[tool_call("workspace__write_file", {"path": "mod.py", "content": BAD})]),
                    make_response("Ya está."),
                    make_response(calls=[tool_call("workspace__edit_file", {
                        "path": "mod.py", "old_text": "return x", "new_text": "return 2 * x"})]),
                    make_response("Corregido."))
    rt = make_rt(llm)
    ui = FakeUI()
    await coder(Coordinator(rt, ui)).handle("implementa doble")
    task = rt.store.list_tasks(1)[0]
    assert task.status == HECHA and (repo_path / "mod.py").read_text() == GOOD
    assert "FAILED" in llm.calls[2]["messages"][1]["content"]
    assert [s.kind for s in rt.store.steps_for(task.id)] == ["chat", "reparacion"]
    assert len(ui.answers_given) == 1 and not ui.prompts


async def test_stop_during_continuation_keeps_saved_step(make_rt, repo_path):
    llm = Responses(make_response(calls=[tool_call("workspace__write_file", {"path": "mod.py", "content": GOOD})]),
                    asyncio.CancelledError())
    rt = make_rt(llm)
    rt.settings.agent.max_turnos = 1
    with pytest.raises(asyncio.CancelledError):
        await coder(Coordinator(rt, FakeUI())).handle("implementa doble")
    task = rt.store.list_tasks(1)[0]
    assert task.status == PAUSADA and (repo_path / "mod.py").read_text() == GOOD
    assert rt.store.steps_for(task.id)[0].ended_at is not None
