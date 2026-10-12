"""Comprobación real de HTML local: acciones, errores, captura y límite de rutas."""
import json
import sys
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from skynet_tools import navegador


@pytest.mark.parametrize("path", ["../fuera.html", "archivo.py", "/fuera.html"])
def test_html_requires_authorized_path(tmp_path, monkeypatch, path):
    monkeypatch.setattr(navegador, "ROOT", tmp_path)
    with pytest.raises(ToolError):
        navegador.comprobar_html(path)


def test_actions_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(navegador, "ROOT", tmp_path)
    (tmp_path / "index.html").write_text("<html></html>")
    with pytest.raises(ToolError):
        navegador.comprobar_html("index.html", acciones=[{"tipo": "ejecutar", "selector": "body"}])
    with pytest.raises(ToolError):
        navegador.comprobar_html("index.html", segundos=100)


@pytest.fixture
def local_browser(tmp_path, monkeypatch):
    bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"
    if not bundle.exists():
        pytest.skip("Comprobación con navegador optativa: requiere Playwright y Chrome")
    monkeypatch.setattr(navegador, "ROOT", tmp_path)
    return tmp_path


def test_browser_interactions_and_capture(local_browser):
    (local_browser / "index.html").write_text('''<!doctype html><title>Prueba</title>
<button id="sumar">Sumar</button><input id="nombre"><output id="salida">0</output>
<script>let n=0;document.querySelector('#sumar').onclick=()=>document.querySelector('#salida').textContent=++n;
document.querySelector('#nombre').oninput=e=>document.querySelector('#salida').textContent=e.target.value;</script>''')
    result = navegador.comprobar_html("index.html", acciones=[{"tipo": "clic", "selector": "#sumar"},
        {"tipo": "rellenar", "selector": "#nombre", "valor": "Daniel"}], segundos=0, captura=True, ancho=390)
    report = json.loads(result.content[0].text)
    assert report["ok"] and "Daniel" in report["texto"]
    assert result.content[1].mime_type == "image/jpeg" and len(result.content[1].data) > 100


def test_browser_reports_javascript_errors(local_browser):
    (local_browser / "index.html").write_text("<title>Error</title><script>funcionInexistente()</script>")
    result = navegador.comprobar_html("index.html", segundos=0)
    assert result.is_error and "funcionInexistente" in result.content[0].text


def test_browser_identifies_overflow_without_blame_on_scrolled_table(local_browser):
    (local_browser / "index.html").write_text('<div style="width:250px;overflow:auto"><table id="tabla" style="width:900px"><tr><td>Tabla con desplazamiento</td></tr></table></div><div id="exceso" style="width:700px">Desbordamiento real</div>')
    result = navegador.comprobar_html("index.html", segundos=0, ancho=390)
    report = json.loads(result.content[0].text)
    ids = {el["id"] for el in report["elementosAnchos"]}
    assert report["desbordamientoHorizontal"] and "exceso" in ids and "tabla" not in ids


async def test_browser_through_real_mcp(local_browser):
    from skynet.config import ServerSpec
    from skynet.toolhub import ToolHub

    (local_browser / "index.html").write_text("<title>MCP real</title><button>Listo</button>")
    spec = ServerSpec("navegador", sys.executable,
                      ["-m", "skynet_tools.navegador", "--root", str(local_browser)])
    async with ToolHub([spec]) as hub:
        result = await hub.call("navegador__comprobar_html", {"path": "index.html", "segundos": 0, "captura": True})
        assert result.ok and "MCP real" in result.text and result.images


async def test_error_screenshot_reaches_model(local_browser, make_rt, repo_path):
    from conftest import ScriptedLLM, tool_call
    from skynet.agent import Agent
    from skynet.config import ServerSpec
    from skynet.gate import PermissionGate
    from skynet.router import Capabilities
    from skynet.toolhub import ToolHub

    (repo_path / "index.html").write_text("<title>Error visible</title><h1>Fallo</h1><script>falloVisible()</script>")
    llm = ScriptedLLM([("", [tool_call("navegador__comprobar_html", {
        "path": "index.html", "segundos": 0, "captura": True})]), ("Veo el fallo.", None)])
    rt = make_rt(llm)
    repo = rt.settings.repo("prueba")
    spec = ServerSpec("navegador", sys.executable, ["-m", "skynet_tools.navegador", "--root", str(repo_path)])
    async with ToolHub([spec]) as hub:
        agent = Agent(rt.router, PermissionGate(rt.settings, repo, rt.audit, vision=True), hub, rt.audit)
        outcome = await agent.run("sistema", "Comprueba el fallo", Capabilities(), max_turns=2)
    assert outcome.final_text == "Veo el fallo."
    messages = llm.calls[-1]["messages"]
    assert any(m["role"] == "tool" and "falloVisible" in str(m["content"]) for m in messages)
    assert any(m["role"] == "user" and isinstance(m["content"], list)
               and any(item.get("type") == "image_url" for item in m["content"]) for m in messages)
    assert "base64" not in str([e["detail"] for e in rt.store.events()])
