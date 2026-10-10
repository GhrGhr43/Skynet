"""Fase 1 «local más listo»: ventana de contexto, reparación de llamadas y herramientas por modo."""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

from conftest import FakeUI, ScriptedLLM, coder, make_response, tool_call, herramientas

from skynet.coordinator import Coordinator
from skynet.llamadas import calls_in_text, parse_args
from skynet.runtime import visible_tools
from skynet.store import HECHA
from skynet.ventana import RESUMEN, Ventana, estimate

GOOD = "VERSION = 1\n\n\ndef doble(x):\n    return 2 * x\n"


def _history(n_tools: int, size: int) -> list[dict]:
    msgs = [{"role": "system", "content": "sistema"}, {"role": "user", "content": "OBJETIVO: arreglar mod.py"}]
    for i in range(n_tools):
        msgs.append({"role": "assistant", "content": f"miro el archivo {i}",
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "workspace__read_file",
                                                  "arguments": json.dumps({"path": f"f{i}.py"})}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": f"primera linea {i}\n" + ("x" * 80 + "\n") * (size // 81)})
    return msgs


def _valid_pairs(msgs: list[dict]) -> bool:
    """Cada resultado de herramienta sigue a la llamada que lo pidió (si no, el servidor da error)."""
    pending: set[str] = set()
    for m in msgs:
        if m["role"] == "assistant":
            pending = {tc["id"] for tc in m.get("tool_calls") or []}
        elif m["role"] == "tool":
            if m["tool_call_id"] not in pending:
                return False
        else:
            pending = set()
    return True


# --- ventana de contexto ---------------------------------------------------------
def test_small_history_untouched():
    v = Ventana(32768, 8192)
    msgs = _history(3, 1000)
    assert v.ajustar(msgs, None) is msgs and v.recortes == 0


def test_old_tool_results_become_one_line():
    v = Ventana(32768, 8192)
    msgs = _history(12, 6000)          # ~20K tokens solo en resultados
    out = v.ajustar(msgs, None)
    assert estimate(out) <= 32768 // 2
    tools = [m for m in out if m["role"] == "tool"]
    assert tools[0]["content"].startswith("[resultado antiguo") and "primera linea 0" in tools[0]["content"]
    assert tools[-1]["content"] == msgs[-1]["content"]          # los últimos se dejan enteros
    assert out[1]["content"] == msgs[1]["content"]              # el objetivo nunca se toca
    assert msgs[3]["content"].startswith("primera linea 0\nx")  # no modifica la lista original
    assert _valid_pairs(out)


def test_long_history_summarized_keeps_goal_and_recent_turns():
    v = Ventana(8192, 2048)
    msgs = _history(150, 1500)
    out = v.ajustar(msgs, None)
    assert estimate(out) <= v.presupuesto(None)
    assert v.resumenes == 1 and out[0] == msgs[0] and out[1] == msgs[1]
    assert out[2]["role"] == "user" and out[2]["content"].startswith(RESUMEN)
    assert "workspace__read_file" in out[2]["content"] and "primera linea 0" in out[2]["content"]
    assert out[-1] == msgs[-1] and _valid_pairs(out)
    # un segundo recorte conserva lo del primer resumen
    more = out + _history(150, 1500)[2:]
    out2 = v.ajustar(more, None)
    assert v.resumenes == 2 and estimate(out2) <= v.presupuesto(None)
    assert "primera linea 0" in out2[2]["content"] and _valid_pairs(out2)


def test_max_tokens_never_overflows_context():
    v = Ventana(32768, 8192)
    assert v.max_tokens(_history(1, 100), None) == 8192
    big = _history(20, 5000)
    assert v.max_tokens(big, None) < 8192
    assert v.max_tokens(big, None) >= 1024


# --- reparación de llamadas ------------------------------------------------------
def test_parse_args_repairs_common_mistakes():
    assert parse_args('{"path": "a.py"}') == ({"path": "a.py"}, False)
    assert parse_args('```json\n{"path": "a.py",}\n```')[0] == {"path": "a.py"}
    assert parse_args("{'path': 'a.py'}")[0] == {"path": "a.py"}
    assert parse_args('{"path": "a.py"')[0] == {"path": "a.py"}
    assert parse_args("")[0] == {}
    try:
        parse_args("no es json")
        raise AssertionError("debería fallar")
    except ValueError:
        pass


def test_calls_written_as_text_are_parsed():
    text = 'Voy a leerlo.\n<tool_call>\n{"name": "workspace__read_file", "arguments": {"path": "mod.py"}}\n</tool_call>'
    calls, rest = calls_in_text(text, {"workspace__read_file"})
    assert rest == "Voy a leerlo." and len(calls) == 1
    assert json.loads(calls[0]["function"]["arguments"]) == {"path": "mod.py"}
    assert calls_in_text(text, {"otra"}) == ([], text)          # herramienta desconocida: se ignora
    assert calls_in_text("hola", {"x"}) == ([], "hola")


def _raw_response(content: str, name: str | None = None, arguments: str | None = None):
    tcs = None
    if name:
        tcs = [SimpleNamespace(id="call_raw", type="function",
                               function=SimpleNamespace(name=name, arguments=arguments))]
    msg = SimpleNamespace(content=content, tool_calls=tcs)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))


class RawLLM(ScriptedLLM):
    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0) if self.script else ("Terminado.", None, None)
        return _raw_response(*item)


async def test_agent_survives_broken_tool_calls(make_rt, repo_path):
    """Un JSON roto y una llamada escrita como texto ya no cuestan turnos: se ejecutan."""
    llm = RawLLM([
        ("", "workspace__write_file", json.dumps({"path": "mod.py", "content": GOOD})[:-1] + ",}"),
        ('<tool_call>{"name": "workspace__run_command", "arguments": {"command": "python -m pytest -q"}}</tool_call>',
         None, None),
        ("Hecho, los tests pasan.", None, None),
    ])
    rt = make_rt(llm)
    ui = FakeUI()
    await coder(Coordinator(rt, ui)).handle("implementa doble")
    task = rt.store.list_tasks(1)[0]
    assert task.status == HECHA, ui.infos
    assert (repo_path / "mod.py").read_text() == GOOD
    evs = rt.store.events(task_id=task.id, types=("tool",))
    assert any(e["decision"] == "reparado" for e in evs)
    assert any(e["tool"] == "workspace.run_command" and e["decision"] == "permitido" for e in evs)


async def test_agent_trims_context_with_small_window(make_rt, repo_path):
    (repo_path / "grande.txt").write_text("".join(f"linea {i} " + "x" * 60 + "\n" for i in range(400)))
    reads = [("", [tool_call("workspace__read_file", {"path": "grande.txt", "offset": i * 10 + 1})])
             for i in range(12)]
    llm = ScriptedLLM(reads + [("Listo.", None)])
    seen: list[tuple[int, int]] = []
    orig = llm.__call__

    async def snapshot(**kwargs):  # el agente sigue añadiendo a la misma lista tras la llamada
        seen.append((estimate(kwargs["messages"]) + estimate(kwargs.get("tools")), kwargs["max_tokens"]))
        return await orig(**kwargs)

    rt = make_rt(snapshot)
    rt.settings.models["local"] = dataclasses.replace(rt.settings.models["local"], contexto_tokens=8192,
                                                      max_tokens=2048)
    await coder(Coordinator(rt, FakeUI())).handle("lee grande.txt por partes")
    assert seen
    for prompt, out in seen:  # nunca se pide más de lo que cabe
        assert prompt + out <= 8192
    task = rt.store.list_tasks(1)[0]  # el verificador falla (no implementa doble): da igual aquí
    assert any(e["type"] == "contexto" for e in rt.store.events(task_id=task.id))


# --- herramientas por modo -------------------------------------------------------
def test_tools_visible_per_mode():
    assert visible_tools("repo") == {} and visible_tools("total") == {}
    assert visible_tools("lectura") == {"sistema": {"read_file", "list_dir", "buscar_archivo"}}
    assert "run_command" not in visible_tools("editar")["sistema"]


async def test_toolhub_hides_tools(home):
    from skynet.config import load_settings
    from skynet.runtime import Runtime
    from skynet.toolhub import ToolHub

    rt = Runtime(load_settings(home))
    try:
        async with ToolHub([rt.sistema_spec()], only=visible_tools("lectura")) as hub:
            names = {t["function"]["name"] for t in hub.openai_tools()}
            assert names == {"sistema__read_file", "sistema__list_dir", "sistema__buscar_archivo"}
            assert hub.resolve("sistema__run_command") is None
    finally:
        rt.store.close()


# --- conversación primero (Coder apagado) ------------------------------------------
async def test_hola_is_a_conversation_not_a_repo_task(make_rt, home):
    (home / "memoria").mkdir(exist_ok=True)
    (home / "memoria" / "USER.md").write_text("Daniel prefiere respuestas cortas.", encoding="utf-8")
    llm = ScriptedLLM([("¡Hola!", None), ("Te dije hola.", None)])
    sent: list[dict] = []
    orig = llm.__call__

    async def snap(**kwargs):  # copia: el agente sigue añadiendo a la misma lista después
        sent.append({**kwargs, "messages": [dict(m) for m in kwargs["messages"]]})
        return await orig(**kwargs)

    rt = make_rt(snap)
    c = Coordinator(rt, FakeUI())
    assert c.repo_name == "prueba" and not c.coder        # hay repo elegido, pero Coder apagado
    await c.handle("hola")
    call = sent[0]
    assert not herramientas(call)                         # sin herramientas ni MCP (solo memoria)
    assert call["messages"][-1] == {"role": "user", "content": "hola"}   # el mensaje tal cual
    assert "PROGRESO" not in json.dumps(call["messages"]) and "git status" not in json.dumps(call["messages"])
    assert "respuestas cortas" in call["messages"][0]["content"]          # la memoria va al system
    assert call["reasoning_effort"] == "low"              # Auto: poco razonamiento en conversación
    task = rt.store.list_tasks(1)[0]
    assert task.repo is None and task.status == HECHA
    await c.handle("¿qué te dije?")
    roles = [m["role"] for m in sent[1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]               # historial como turnos de verdad


async def test_coder_toggle(make_rt):
    c = Coordinator(make_rt(ScriptedLLM([])), FakeUI())
    await c.handle("/coder on")
    assert c.coder and c.active_repo == "prueba"
    await c.handle("/repo ninguno")
    assert not c.coder and c.active_repo is None
    await c.handle("/coder on")
    assert not c.coder                                    # sin repo no se activa
