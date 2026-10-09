"""Modos de permisos por modelo, herramienta `sistema` y modelos en la nube con confirmación."""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FakeUI, ScriptedLLM, tool_call

from skynet.audit import Audit
from skynet.coordinator import Coordinator
from skynet.gate import Decision, PermissionGate
from skynet.modos import Accesos
from skynet.router import Capabilities
from skynet.web.server import create_app

USER = "C:/Users/HACHO"


@pytest.fixture
def ctx(make_rt):
    rt = make_rt(None)
    return rt


def gate(rt, mode, repo=None, asker=None):
    return PermissionGate(rt.settings, repo, Audit(rt.store), asker=asker, mode=mode, user_home=USER)


def dec(rt, mode, key, args, repo=None):
    return gate(rt, mode, repo).evaluate(key, args)


# --- gate -------------------------------------------------------------------
def test_solo_repo_no_sale_del_repo(ctx):
    assert dec(ctx, "repo", "sistema.read_file", {"path": f"{USER}/notas.txt"}).decision is Decision.DENY


def test_ver_mi_pc_solo_lee(ctx):
    assert dec(ctx, "lectura", "sistema.read_file", {"path": f"{USER}/notas.txt"}).decision is Decision.ALLOW
    assert dec(ctx, "lectura", "sistema.list_dir", {"path": "D:/Juegos"}).decision is Decision.ALLOW
    assert dec(ctx, "lectura", "sistema.write_file", {"path": f"{USER}/x.txt", "content": "x"}).decision is Decision.DENY
    assert dec(ctx, "lectura", "sistema.run_command", {"command": "dir"}).decision is Decision.DENY


@pytest.mark.parametrize("path", [f"{USER}/.ssh/id_rsa", "C:\\Skynet\\.env",
                                  f"{USER}/AppData/Local/Google/Chrome/User Data/Default/Login Data",
                                  f"{USER}/claves/servidor.pem"])
def test_secretos_se_preguntan_siempre(ctx, path):
    for mode in ("lectura", "editar", "total"):
        r = dec(ctx, mode, "sistema.read_file", {"path": path})
        assert r.decision is Decision.ASK and r.siempre, (mode, path, r)


def test_ver_y_editar(ctx):
    allow = dec(ctx, "editar", "sistema.write_file", {"path": f"{USER}/Documents/lista.txt", "content": "x"})
    assert allow.decision is Decision.ALLOW
    rel = dec(ctx, "editar", "sistema.edit_file", {"path": "Desktop/a.txt", "old": "a", "new": "b"})
    assert rel.decision is Decision.ALLOW  # relativo = dentro de la carpeta de usuario
    for path in ("C:/Windows/System32/drivers/etc/hosts", "C:\\Program Files (x86)\\Steam\\config.vdf"):
        r = dec(ctx, "editar", "sistema.write_file", {"path": path, "content": "x"})
        assert r.decision is Decision.ASK and r.siempre
    fuera = dec(ctx, "editar", "sistema.write_file", {"path": "D:/otra/cosa.txt", "content": "x"})
    assert fuera.decision is Decision.ASK and fuera.siempre
    skynet = dec(ctx, "editar", "sistema.write_file", {"path": str(ctx.settings.home / "skynet" / "gate.py"), "content": "x"})
    assert skynet.decision is Decision.ASK and skynet.siempre
    borrar = dec(ctx, "editar", "sistema.delete_file", {"path": f"{USER}/a.txt"})
    assert borrar.decision is Decision.ASK and borrar.siempre
    assert dec(ctx, "editar", "sistema.run_command", {"command": "dir"}).decision is Decision.DENY


def test_control_total(ctx):
    for cmd in ("Get-Process steam", "winget list", "& 'C:/Users/HACHO/juego.exe' --help"):
        assert dec(ctx, "total", "sistema.run_command", {"command": cmd}).decision is Decision.ALLOW, cmd
    assert dec(ctx, "total", "sistema.abrir", {"destino": "steam://install/730"}).decision is Decision.ALLOW
    for cmd in ("Start-Process powershell -Verb RunAs", "reg add HKLM\\Software\\X /v a /d 1", "sudo apt install x",
                "Remove-Item C:/Users/HACHO/a.txt", "del a.txt", "rm -rf build", "copy x C:\\Windows\\System32",
                "Get-Content $env:USERPROFILE/.ssh/id_rsa", "type .env", "shutdown /s"):
        r = dec(ctx, "total", "sistema.run_command", {"command": cmd})
        assert r.decision is Decision.ASK and r.siempre, (cmd, r)


def test_control_total_relaja_la_lista_blanca_del_repo(ctx):
    repo = ctx.settings.repo("prueba")
    assert dec(ctx, "repo", "workspace.run_command", {"command": "npm install"}, repo).decision is Decision.ASK
    assert dec(ctx, "total", "workspace.run_command", {"command": "npm install"}, repo).decision is Decision.ALLOW
    r = dec(ctx, "total", "workspace.run_command", {"command": "rm -rf src"}, repo)
    assert r.decision is Decision.ASK and r.siempre


async def test_siempre_no_admite_toda_la_tarea(ctx):
    async def asker(*_a):
        return "t"
    g = gate(ctx, "total", asker=asker)
    r = await g.check("sistema.run_command", {"command": "Start-Process x -Verb RunAs"})
    assert r.allowed and "sistema.run_command" not in g.session_grants


# --- modos y nube ---------------------------------------------------------------
def test_modos_persisten(make_rt):
    rt = make_rt(None)
    assert rt.access.modo("local") == "repo"
    rt.access.set_modo("local", "total")
    assert Accesos(rt.settings).modo("local") == "total"
    with pytest.raises(ValueError):
        rt.access.set_modo("local", "dios")


def test_nube_desactivada_por_defecto(make_rt, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    rt = make_rt(None)
    d = rt.router.choose(Capabilities(force="gemini"))
    assert d.profile.nombre == "local" and "sin activar" in d.reason
    assert rt.router.choose(Capabilities(reasoning="alto")).profile.nombre == "local"
    rt.access.activar_nube("gemini", True)
    assert rt.router.choose(Capabilities(force="gemini")).profile.nombre == "gemini"
    assert Accesos(rt.settings).nube_activada == set()  # no se recuerda entre arranques


async def test_coordinator_local_por_defecto_y_confirmaciones(make_rt, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    rt = make_rt(None)
    ui = FakeUI(["n", "s", "n", "s"])
    coord = Coordinator(rt, ui)
    assert coord.force_model == "local"
    await coord.handle("/modelo gemini")          # n
    assert coord.force_model == "local" and "gemini" not in rt.access.nube_activada
    await coord.handle("/modelo gemini")          # s
    assert coord.force_model == "gemini" and "gemini" in rt.access.nube_activada
    await coord.handle("/permisos gemini total")  # aviso -> n
    assert rt.access.modo("gemini") == "repo" and "AVISO" in ui.prompts[-1]
    await coord.handle("/permisos gemini lectura")  # no es fuerte: sin aviso
    assert rt.access.modo("gemini") == "lectura" and len(ui.prompts) == 3
    await coord.handle("/permisos local total")   # local: sin aviso
    assert rt.access.modo("local") == "total" and len(ui.prompts) == 3


async def test_flujo_control_total_sin_repo(make_rt, tmp_path, monkeypatch):
    """Chat sin repo con el local en Control total: tiene las herramientas sistema__*, escribe en la
    carpeta de usuario, ejecuta un comando y lo que borra se pregunta (y aquí se deniega)."""
    user = tmp_path / "usuario"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user))
    seen_tools: list[str] = []

    def first(messages):
        return ("", [tool_call("sistema__write_file", {"path": str(user / "lista.txt"), "content": "hola"}),
                     tool_call("sistema__run_command", {"command": "echo listo", "cwd": str(user)}),
                     tool_call("sistema__run_command", {"command": "rm lista.txt", "cwd": str(user)})])
    llm = ScriptedLLM([first, ("Hecho.", None)])
    rt = make_rt(llm)
    rt.access.set_modo("local", "total")
    ui = FakeUI(["n"])
    coord = Coordinator(rt, ui)
    await coord.handle("/repo ninguno")
    await coord.handle("crea una lista en mi carpeta")
    seen_tools = [t["function"]["name"] for t in llm.calls[0]["tools"]]
    assert "sistema__abrir" in seen_tools and "Control total" in llm.calls[0]["messages"][0]["content"]
    assert (user / "lista.txt").read_text() == "hola"  # el rm se preguntó y se denegó
    assert len(ui.prompts) == 1 and "borra" in ui.prompts[0]
    tool_msgs = [m["content"] for m in llm.calls[1]["messages"] if m["role"] == "tool"]
    assert any("listo" in t for t in tool_msgs) and any("DENEGADO" in t for t in tool_msgs)


async def test_sin_modo_el_chat_no_tiene_herramientas(make_rt):
    llm = ScriptedLLM([("hola", None)])
    rt = make_rt(llm)
    coord = Coordinator(rt, FakeUI())
    await coord.handle("/repo ninguno")
    await coord.handle("hola")
    assert not llm.calls[0].get("tools")


# --- web ----------------------------------------------------------------------
def test_web_nube_y_aviso(make_rt, monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setenv("GEMINI_API_KEY", "x")
    rt = make_rt(None)
    with TestClient(create_app(rt)) as c:
        s = c.get("/api/estado").json()
        assert s["modelo"] == "local" and s["modo_actual"] == "repo" and len(s["modos"]) == 4
        gem = next(m for m in s["modelos"] if m["nombre"] == "gemini")
        assert gem["activado"] is False and gem["disponible"] is False
        r = c.post("/api/ajustes", json={"modelo": "gemini"})
        assert r.status_code == 409 and r.json()["confirmar"]["tipo"] == "nube"
        assert c.get("/api/estado").json()["modelo"] == "local"
        s = c.post("/api/ajustes", json={"modelo": "gemini", "confirmar": True}).json()
        assert s["modelo"] == "gemini" and next(m for m in s["modelos"] if m["nombre"] == "gemini")["activado"]
        r = c.post("/api/ajustes", json={"permiso": {"modelo": "gemini", "modo": "total"}})
        assert r.status_code == 409 and r.json()["confirmar"]["tipo"] == "aviso"
        s = c.post("/api/ajustes", json={"permiso": {"modelo": "gemini", "modo": "total"}, "confirmar": True}).json()
        assert s["modo_actual"] == "total"
        s = c.post("/api/ajustes", json={"nube": {"modelo": "gemini", "activar": False}}).json()
        assert s["modelo"] == "local" and s["modo_actual"] == "repo"
        s = c.post("/api/ajustes", json={"permiso": {"modelo": "local", "modo": "editar"}}).json()
        assert s["modo_actual"] == "editar"
        assert c.post("/api/ajustes", json={"permiso": {"modelo": "local", "modo": "dios"}}).status_code == 400


def test_web_anadir_repo(make_rt, tmp_path):
    from starlette.testclient import TestClient

    rt = make_rt(None)
    carpeta = tmp_path / "juego"
    carpeta.mkdir()
    with TestClient(create_app(rt)) as c:
        assert c.post("/api/repos", json={"nombre": "mal nombre", "ruta": str(carpeta)}).status_code == 400
        assert c.post("/api/repos", json={"nombre": "juego", "ruta": str(tmp_path / "no-existe")}).status_code == 400
        s = c.post("/api/repos", json={"nombre": "juego", "ruta": str(carpeta), "verificador": "npm test"}).json()
        assert any(r["nombre"] == "juego" and r["existe"] for r in s["repos"])
        assert c.post("/api/repos", json={"nombre": "juego", "ruta": str(carpeta)}).status_code == 409
    # persiste: un Settings nuevo lo ve (config/repos.local.toml)
    from skynet.config import load_settings
    again = load_settings(rt.settings.home)
    assert again.repos["juego"].verificador == "npm test"


# --- «Sin preguntar» y Detener ---------------------------------------------------
async def test_sin_preguntar_permite_lo_que_se_preguntaria(ctx):
    async def asker(*_a):
        raise AssertionError("no debe preguntar")

    g = PermissionGate(ctx.settings, None, Audit(ctx.store), asker=asker, mode="total", user_home=USER,
                       sin_preguntar=True)
    for key, args in (("sistema.delete_file", {"path": f"{USER}/a.txt"}),
                      ("sistema.run_command", {"command": "Start-Process x -Verb RunAs"}),
                      ("sistema.write_file", {"path": "C:/Windows/x.ini"}),
                      ("sistema.read_file", {"path": f"{USER}/.ssh/id_rsa"})):
        assert (await g.check(key, args)).allowed, key
    # Solo vale en Control total
    g2 = PermissionGate(ctx.settings, None, Audit(ctx.store), mode="editar", user_home=USER, sin_preguntar=True)
    assert g2.evaluate("sistema.run_command", {"command": "echo"}).decision is Decision.DENY


def test_sin_preguntar_persiste_y_se_quita_al_bajar_de_modo(make_rt):
    rt = make_rt(None)
    with pytest.raises(ValueError):
        rt.access.set_sin_preguntar("local", True)
    rt.access.set_modo("local", "total")
    rt.access.set_sin_preguntar("local", True)
    assert Accesos(rt.settings).sin_preguntar("local")
    rt.access.set_modo("local", "editar")
    assert not Accesos(rt.settings).sin_preguntar("local")


def test_web_sin_preguntar(make_rt):
    from starlette.testclient import TestClient

    rt = make_rt(None)
    with TestClient(create_app(rt)) as c:
        assert c.post("/api/ajustes", json={"sin_preguntar": {"modelo": "local", "activar": True}}).status_code == 400
        both = {"permiso": {"modelo": "local", "modo": "total"}, "sin_preguntar": {"modelo": "local", "activar": True}}
        r = c.post("/api/ajustes", json=both)
        assert r.status_code == 409 and r.json()["confirmar"]["tipo"] == "aviso"
        assert c.get("/api/estado").json()["modo_actual"] == "repo"  # nada cambia hasta confirmar
        s = c.post("/api/ajustes", json={**both, "confirmar": True}).json()
        assert s["modo_actual"] == "total" and s["sin_preguntar_actual"] is True
        s = c.post("/api/ajustes", json={"sin_preguntar": {"modelo": "local", "activar": False}}).json()
        assert s["sin_preguntar_actual"] is False and s["modo_actual"] == "total"


async def test_detener_libera_aunque_el_trabajo_no_responda(make_rt):
    import asyncio

    from skynet.web.server import Session

    s = Session(make_rt(None))
    gone = asyncio.Event()

    async def terco():
        while True:  # se traga la cancelación, como una librería que no la respeta
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                if gone.is_set():
                    raise
                gone.set()

    s.start("terco", terco)
    await asyncio.sleep(0.05)
    assert await s.cancel(wait=0.3) and not s.busy
    done = asyncio.Event()

    async def otro():
        done.set()

    s.start("otro", otro)
    await asyncio.wait_for(done.wait(), 2)
    await asyncio.sleep(0.05)
    assert not s.busy
    await asyncio.sleep(2.2)  # el abandonado acaba muriendo con la segunda cancelación
    assert not s._abandoned
