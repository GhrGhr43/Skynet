"""Pi instalado, proveedor simulado y MCP real: extras, permisos y sesiones oficiales."""
import json
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from conftest import FakeUI
from skynet.coordinator import Coordinator
from skynet_tools import pi_agent


@pytest.mark.parametrize("extras", [False, True])
async def test_pi_original_con_extras_optativos(make_rt, home, repo_path, monkeypatch, extras):
    root = Path(__file__).resolve().parents[1]
    try:
        installed = pi_agent.installation(root)
    except RuntimeError:
        pytest.skip("Pi opcional no instalado")
    monkeypatch.setattr(pi_agent, "installation", lambda _: installed)
    rt = make_rt()
    calls = []
    replies = [
        ("tool_search", {"query": "sumar"}),
        ("mcp__prueba_mcp__sumar", {"a": 2, "b": 3}),
        ("memoria", {"texto": "Prefiero ejemplos cortos"}),
    ] if extras else []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(payload)
            index = len(calls) - 1
            if index < len(replies):
                name, args = replies[index]
                delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{index}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}}]}
                reason = "tool_calls"
            else:
                delta, reason = {"role": "assistant", "content": "Comprobación terminada"}, "stop"
            chunks = [{"id": "test", "object": "chat.completion.chunk", "created": 1, "model": "local",
                "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": "local",
                "choices": [{"index": 0, "delta": {}, "finish_reason": reason}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}}]
            content = "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(content.encode())))
            self.end_headers()
            self.wfile.write(content.encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rt.settings.models["local"].api_base = f"http://127.0.0.1:{server.server_port}/v1"
    marker = repo_path / "mcp-ejecutado.txt"
    script = home / "sumar_mcp.py"
    script.write_text("from mcp.server.mcpserver import MCPServer\nfrom pathlib import Path\n"
        "mcp=MCPServer('prueba')\n@mcp.tool()\ndef sumar(a:int,b:int)->int:\n"
        f" Path({str(marker)!r}).write_text(str(a+b))\n return a+b\n"
        "mcp.run()\n", encoding="utf-8")
    rt.settings.tool_levels["prueba-mcp.sumar"] = "read"
    rt.personalizacion.cambiar({"memoria_activa": extras, "mcp_activo": extras,
        "mcp": {"prueba-mcp": {"command": sys.executable, "args": [str(script)], "enabled": True}}})
    other = rt.personalizacion.proponer_memoria("Otra entrada pendiente")
    ui = FakeUI(["s"])
    coord = Coordinator(rt, ui)
    try:
        task = await coord.new_task("Ejecuta las comprobaciones disponibles")
        assert task.status == "hecha", task.result_summary
        names = {t["function"]["name"] for t in calls[0].get("tools", [])}
        assert {"read", "bash", "edit", "write"} <= names
        assert ("memoria" in names) is extras
        assert ("tool_search" in names) is extras
        assert "mcp__prueba_mcp__sumar" not in names  # esquema cargado solo al buscarlo
        if extras:
            assert marker.exists(), str(ui.events) + str(calls[-1]["messages"][-4:])
            assert marker.read_text() == "5"
            assert "mcp__prueba_mcp__sumar" in {t["function"]["name"] for t in calls[1]["tools"]}
            assert len(ui.prompts) == 1 and "Prefiero ejemplos cortos" in ui.prompts[0]
            assert rt.personalizacion.data["memoria"][-1]["aprobada"]
            assert not next(e for e in rt.personalizacion.data["memoria"] if e["id"] == other["id"])["aprobada"]
        else:
            assert not marker.exists()
        assert list((home / "data/pi/sessions").rglob("*.jsonl"))
        rt.personalizacion.cambiar({"memoria_activa": False, "mcp_activo": False})
        second = await coord.new_task("Continúa la conversación sin extras")
        assert second.status == "hecha"
        names = {t["function"]["name"] for t in calls[-1].get("tools", [])}
        assert names == {"read", "bash", "edit", "write"}
        assert any(m.get("role") == "user" and "Ejecuta las comprobaciones" in str(m.get("content")) for m in calls[-1]["messages"])
        assert len(list((home / "data/pi/sessions").rglob("*.jsonl"))) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
