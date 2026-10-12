"""Contrato RPC, gate real y cancelación del motor Pi, sin necesitar un modelo."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys

import pytest

from conftest import FakeUI, ScriptedLLM, coder
from skynet.coordinator import Coordinator
from skynet.router import Capabilities
from skynet_tools import pi_agent


FAKE = r'''
import json,os,sys,urllib.request,urllib.error,time
sys.stdout.reconfigure(encoding='utf-8')
url=os.environ['SKYNET_PI_BRIDGE'];token=os.environ['SKYNET_PI_TOKEN']
def http(path,body=None,auth=token):
 req=urllib.request.Request(url+path,data=json.dumps(body).encode() if body else None,
  headers={'Authorization':'Bearer '+auth,'Content-Type':'application/json'})
 with urllib.request.urlopen(req) as r:return json.load(r)
def emit(value):print(json.dumps(value,ensure_ascii=False),flush=True)
def assistant(text):
 emit({'type':'message_start','message':{'role':'assistant'}})
 emit({'type':'message_end','message':{'role':'assistant','stopReason':'stop',
  'usage':{'input':30,'cacheRead':10,'output':7},'content':[{'type':'text','text':text}]}})
for line in sys.stdin.buffer:
 cmd=json.loads(line)
 if cmd['type']=='abort':emit({'type':'agent_settled'});continue
 if cmd['type']!='prompt':continue
 emit({'id':cmd['id'],'type':'response','success':True})
 tools=http('/manifest')['tools']
 assert any(t['name']=='workspace__write_file' for t in tools)
 assert not any(t['name'] in ('bash','powershell','write') for t in tools)
 try:http('/manifest',auth='incorrecto');raise AssertionError('Sin autenticación')
 except urllib.error.HTTPError as e:assert e.code==403
 denied=http('/tool',{'name':'workspace__write_file','args':{'path':'../escape.txt','content':'error'}})
 assert denied['content'][0]['text'].startswith('DENEGADO')
 http('/tool',{'name':'workspace__write_file','args':{'path':'mod.py','content':'VERSION = 1\n\ndef doble(x):\n    return 2 * x\n'.replace('\\n','\n')}})
 # agent_end todavía no cierra el trabajo: el adaptador debe esperar settled.
 emit({'type':'agent_end','messages':[]})
 assistant('Hecho: verificado. U+2028: \u2028 OBJETIVO_CUMPLIDO')
 emit({'type':'agent_settled'})
'''


def fake_install(monkeypatch, home, code=FAKE):
    script = home / "pi_fake.py"
    script.write_text(code, encoding="utf-8")
    monkeypatch.setattr(pi_agent, "installation", lambda _: (sys.executable, script, script))


async def test_pi_rpc_uses_real_gate_and_mcp(make_rt, home, repo_path, monkeypatch):
    fake_install(monkeypatch, home)
    llm = ScriptedLLM([])
    rt = make_rt(llm)
    c = coder(Coordinator(rt, FakeUI()))
    c.coder_motor = "pi"
    task = await c.new_task("Implementa doble")
    assert task.status == "hecha", task.result_summary
    assert not (repo_path.parent / "escape.txt").exists()
    assert "return 2 * x" in (repo_path / "mod.py").read_text()
    assert not llm.calls  # no segundo bucle ni llamadas por LiteLLM
    calls = rt.store.events(task_id=task.id, types=("llm",))
    assert calls[0]["tokens_in"] == 40 and calls[0]["tokens_out"] == 7
    assert task.capabilities["harness"] == "pi"
    assert any(e["decision"] == "denegado" for e in rt.store.events(task_id=task.id, types=("tool",)))


@pytest.mark.parametrize("change", [{"api_base": "https://example.com/v1"}, {"privado": False}, {"agente": True}])
def test_pi_rejects_nonlocal_profile(make_rt, change):
    rt = make_rt()
    profile = dataclasses.replace(rt.settings.models["local"], **change)
    with pytest.raises(ValueError):
        pi_agent.configure(rt.settings.home, profile)


async def test_pi_cancel_ends_child(make_rt, home, monkeypatch):
    fake_install(monkeypatch, home, "import sys,time\nfor line in sys.stdin:\n time.sleep(600)\n")
    rt = make_rt()
    task = rt.store.create_task("Prueba", "Prueba", "skynet", repo="prueba", capabilities={"harness": "pi"})
    children = []
    create = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        proc = await create(*args, **kwargs)
        if args[0] == sys.executable and args[1].endswith("pi_fake.py"):
            children.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    work = asyncio.create_task(rt.agent_step(task, "chat"))
    for _ in range(100):
        if children:
            break
        await asyncio.sleep(.05)
    assert children
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    assert children[0].returncode is not None


def test_pi_configuration_matches_local_profile(make_rt):
    rt = make_rt()
    p = rt.settings.models["local"]
    folder = pi_agent.configure(rt.settings.home, p, True)
    config = json.loads((folder / "models.json").read_text())
    provider = config["providers"]["skynet-local"]
    model = provider["models"][0]
    assert provider["baseUrl"] == p.api_base
    assert model["contextWindow"] == p.contexto_tokens
    assert model["maxTokens"] == p.max_tokens
    assert model["samplingParams"]["temperature"] == p.temperatura
    assert model["input"] == ["text", "image"]


async def test_pi_keeps_pending_plan_unfinished(make_rt, home, repo_path, monkeypatch):
    code = r'''
import json,sys
for line in sys.stdin:
 cmd=json.loads(line)
 if cmd['type']!='prompt':continue
 print(json.dumps({'type':'message_start','message':{'role':'assistant'}}),flush=True)
 print(json.dumps({'type':'message_end','message':{'role':'assistant','stopReason':'stop','usage':{},
  'content':[{'type':'text','text':'Todo hecho OBJETIVO_CUMPLIDO'}]}}),flush=True)
 print(json.dumps({'type':'agent_settled'}),flush=True)
'''
    fake_install(monkeypatch, home, code)
    rt = make_rt()
    task = rt.store.create_task("Pendiente", "Pendiente", "skynet", repo="prueba", capabilities={"harness": "pi"})
    folder = repo_path / ".skynet" / f"tarea-{task.id}"
    folder.mkdir(parents=True)
    (folder / "PLAN.md").write_text("- [ ] Requisito sin implementar\n", encoding="utf-8")
    result = await rt.agent_step(task, "chat", max_turns=10)
    assert result.outcome.status == "limite_turnos"
    assert result.outcome.turns == 3 and not result.outcome.claims_done


def test_pi_keeps_error_screenshot_as_image():
    blocks = pi_agent.content_blocks("ERROR: JavaScript falla", [{"type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,YWJj"}}])
    assert blocks[1] == {"type": "image", "mimeType": "image/jpeg", "data": "YWJj"}
