"""Internet opcional: aislamiento, lectura pública y conexión real por MCP sin red en tests."""
import json
import socket
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest

from conftest import FakeUI, ScriptedLLM, tool_call
from skynet.coordinator import Coordinator
from skynet.gate import Decision, PermissionGate
from skynet.store import PAUSADA
from skynet_tools import internet
from mcp.server.mcpserver.exceptions import ToolError


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])


@pytest.mark.parametrize("url", ["file:///C:/Windows/system.ini", "ftp://example.com", "https://user:pass@example.com",
                                "http://example.com:8765", "http://localhost", "http://127.0.0.1", "http://[::1]",
                                "http://192.168.1.10", "http://169.254.169.254"])
def test_private_urls_denied(url, monkeypatch):
    host = urlsplit(url).hostname
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (host if host != "localhost" else "127.0.0.1", 80))])
    with pytest.raises(ToolError):
        internet.public_url(url)


def test_search_compact_and_failure(monkeypatch):
    import ddgs

    def search(*a, **k):
        return [{"title": "Steam", "href": "https://store.steampowered.com/app/2060160/", "body": "x" * 2000}] * 8
    monkeypatch.setattr(ddgs, "DDGS", lambda **kw: SimpleNamespace(text=search))
    data = json.loads(internet.buscar("The Farmer Was Replaced Steam"))
    assert len(data["resultados"]) == 5
    assert len(data["resultados"][0]["extracto"]) == 600
    def fail(*a, **k):
        raise TimeoutError
    monkeypatch.setattr(ddgs, "DDGS", lambda **kw: SimpleNamespace(text=fail))
    with pytest.raises(ToolError, match="TimeoutError"):
        internet.buscar("Steam")


def mock_client(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(internet.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def test_read_text_bounded_without_scripts(public_dns, monkeypatch):
    def reply(req):
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              text="<h1>Steam</h1><script>INSTRUCCION_OCULTA</script><p>AppID 2060160</p><p>" + "z" * 6000 + "</p>")
    mock_client(monkeypatch, reply)
    data = json.loads(internet.leer("https://store.steampowered.com/app/2060160/"))
    assert "AppID 2060160" in data["texto"] and "INSTRUCCION_OCULTA" not in data["texto"]
    assert len(data["texto"]) == 5000 and data["recortado"]


def test_redirect_private_denied_before_request(monkeypatch):
    calls = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("127.0.0.1" if host == "localhost" else "93.184.216.34", 80))])
    def reply(req):
        calls.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://localhost/secret"})
    mock_client(monkeypatch, reply)
    with pytest.raises(ToolError):
        internet.leer("https://example.com/")
    assert calls == ["https://example.com/"]


def test_read_binary_denied(public_dns, monkeypatch):
    mock_client(monkeypatch, lambda req: httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=b"binary"))
    with pytest.raises(ToolError, match="texto"):
        internet.leer("https://example.com/")


def test_read_oversize_denied(public_dns, monkeypatch):
    mock_client(monkeypatch, lambda req: httpx.Response(200, headers={"content-type": "text/plain"},
                                                       content=b"x" * (internet.MAX_BYTES + 1)))
    with pytest.raises(ToolError, match="grande"):
        internet.leer("https://example.com/")


def test_gate_requires_explicit_internet(make_rt):
    rt = make_rt()
    gate = PermissionGate(rt.settings, None, rt.audit)
    assert gate.evaluate("internet.buscar", {"query": "Steam"}).decision is Decision.DENY
    gate = PermissionGate(rt.settings, None, rt.audit, internet=True)
    assert gate.evaluate("internet.buscar", {"query": "Steam"}).allowed
    assert gate.evaluate("internet.leer", {"url": "https://example.com/"}).allowed
    assert gate.evaluate("internet.ejecutar", {}).decision is Decision.DENY
    rt.settings.tool_levels["internet.leer"] = "PRIVILEGED"
    assert gate.evaluate("internet.leer", {"url": "https://example.com/"}).decision is Decision.ASK


@pytest.mark.asyncio
async def test_mcp_tools_only_when_enabled_and_no_repo(make_rt):
    llm = ScriptedLLM([("Hola", None), ("", [tool_call("internet__buscar", {"query": ""})]),
                       ("La consulta necesita texto", None), ("Hola de nuevo", None)])
    rt = make_rt(llm)
    c = Coordinator(rt, FakeUI())
    c.repo_name = None
    await c.handle("hola")
    assert not llm.calls[0].get("tools")
    await c.handle("/internet on")
    await c.handle("busca Steam")
    assert {t["function"]["name"] for t in llm.calls[1]["tools"]} == {"internet__buscar", "internet__leer"}
    assert "ERROR:" in llm.calls[2]["messages"][-2]["content"]
    events = rt.store.events(types=("tool",))
    assert events[0]["tool"] == "internet.buscar" and events[0]["decision"] == "permitido"
    await c.handle("/internet off")
    await c.handle("hola")
    assert not llm.calls[-1].get("tools")


@pytest.mark.asyncio
async def test_privacy_and_long_tasks_have_no_web(make_rt):
    llm = ScriptedLLM([("Privado", None), ("Larga", None)])
    rt = make_rt(llm)
    c = Coordinator(rt, FakeUI())
    c.repo_name = None
    await c.handle("/internet on")
    await c.handle("/privado")
    await c.handle("/internet on")
    assert c.internet is False
    await c.handle("hola")
    assert not llm.calls[0].get("tools")
    task = rt.store.create_task("larga", "hola", agent="scheduler", max_hours=1,
                                capabilities={"capacidades": {"internet": True}})
    await rt.agent_step(task, "larga")
    assert not llm.calls[1].get("tools")


@pytest.mark.asyncio
async def test_resume_honors_switch_off(make_rt):
    llm = ScriptedLLM([("Continúo", None)])
    rt = make_rt(llm)
    task = rt.store.create_task("antes", "hola", agent="chat", status=PAUSADA,
                                capabilities={"capacidades": {"internet": True}})
    c = Coordinator(rt, FakeUI())
    await c.resume(None, task.id)
    assert not llm.calls[0].get("tools")
    assert rt.store.get_task(task.id).capabilities["capacidades"]["internet"] is False
