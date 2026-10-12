"""Píxeles por MCP, historial sin base64 y permisos de captura (sin mirar el escritorio real)."""
import base64
import io

import pytest
from PIL import Image

from skynet import imagenes
from skynet.agent import Agent
from skynet.gate import Decision, PermissionGate
from skynet.router import Capabilities
from skynet.toolhub import ToolHub
from skynet.ventana import Ventana, estimate
from skynet_tools import vision
from conftest import ScriptedLLM, tool_call


def png(size=(80, 50)):
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, format="PNG")
    return out.getvalue()


def adjunto():
    return {"nombre": "prueba.png", "data_url": "data:image/png;base64," + base64.b64encode(png()).decode()}


def test_adjuntos_validacion_y_referencias(tmp_path):
    refs = imagenes.guardar(tmp_path, [adjunto()])
    assert refs[0]["ancho"] == 80
    assert "data_url" not in refs[0]
    assert imagenes.contenido("mira", refs, tmp_path)[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    for bad in ({"data_url": "https://example.com/imagen.png"}, {"data_url": "data:image/png;base64,bm8="}):
        with pytest.raises(ValueError):
            imagenes.guardar(tmp_path, [bad])
    with pytest.raises(ValueError):
        imagenes.guardar(tmp_path, [adjunto()] * 5)
    with pytest.raises(ValueError):
        imagenes.ruta(tmp_path, "../../secret")
    with pytest.raises(ValueError):
        vision.normalizar(b"x" * (vision.MAX_BYTES + 1))
    with pytest.raises(ValueError):
        vision.normalizar(png((5000, 5000)))
    assert vision.normalizar(png((2000, 1000)))[1:] == (1280, 640)


def test_contexto_cuenta_imagen_no_base64(tmp_path):
    refs = imagenes.guardar(tmp_path, [adjunto()])
    content = imagenes.contenido("mira", refs, tmp_path)
    assert 1536 < estimate(content) < 1600
    assert estimate({"type": "image_url", "image_url": {"url": "x" * 1000000}}) == 1536
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "objetivo"}]
    for _ in range(20):
        msgs += [{"role": "user", "content": content}, {"role": "assistant", "content": "visto"}]
    ventana = Ventana(8192, 2048)
    result = ventana.ajustar(msgs, None)
    assert ventana.resumenes and estimate(result) < 8192
    assert "[imagen omitida del contexto]" in str(result)


def test_gate_capturas_y_lectura(make_rt, repo_path):
    rt = make_rt()
    repo = rt.settings.repo("prueba")
    def gate(mode="repo", enabled=True):
        return PermissionGate(rt.settings, repo, rt.audit, mode=mode, vision=enabled)
    assert gate().evaluate("vision.capturar_pantalla", {}).decision is Decision.DENY
    assert gate("lectura").evaluate("vision.capturar_pantalla", {}).decision is Decision.ALLOW
    assert gate("total", False).evaluate("vision.capturar_pantalla", {}).decision is Decision.DENY
    assert gate().evaluate("vision.leer_imagen", {"path": "prueba.png"}).allowed
    assert not gate().evaluate("vision.leer_imagen", {"path": "../fuera.png"}).allowed
    assert gate("lectura").evaluate("vision.leer_imagen", {"path": str(repo_path / ".ssh/id_rsa")}).siempre


async def test_mcp_imagen_llega_al_modelo(make_rt, repo_path):
    (repo_path / "prueba.png").write_bytes(png())
    llm = ScriptedLLM([
        ("", [tool_call("vision__leer_imagen", {"path": "prueba.png"})]),
        ("Veo rojo.", None),
    ])
    rt = make_rt(llm)
    repo = rt.settings.repo("prueba")
    spec = rt.settings.server_spec("vision", repo)
    async with ToolHub([spec]) as hub:
        gate = PermissionGate(rt.settings, repo, rt.audit, vision=True)
        agent = Agent(rt.router, gate, hub, rt.audit)
        outcome = await agent.run("s", "mira", Capabilities(), max_turns=2)
    assert outcome.final_text == "Veo rojo."
    messages = llm.calls[-1]["messages"]
    assert messages[-2]["role"] == "user"
    assert messages[-2]["content"][1]["type"] == "image_url"
    assert "base64" not in str([e["detail"] for e in rt.store.events()])


def test_captura_rechazada_en_repo(monkeypatch):
    monkeypatch.setattr(vision, "SOLO_REPO", True)
    with pytest.raises(Exception, match="Ver mi PC"):
        vision.capturar_pantalla()
