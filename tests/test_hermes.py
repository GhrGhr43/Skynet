"""Hermes como segundo cerebro (D19): perfil `agente`, router, runtime, motor y lanzador."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeUI, ScriptedLLM, coder

from skynet import engines as eng
from skynet.coordinator import Coordinator
from skynet.router import Capabilities
from skynet_tools import hermes_motor as hm


def test_config_real_solo_local_y_hermes(make_rt):
    rt = make_rt(None)
    reales = {n for n, m in rt.settings.models.items() if n not in ("gemini", "omniroute", "cloud")}
    assert reales == {"local", "hermes", "hermes-nube"}
    h, n = rt.settings.models["hermes"], rt.settings.models["hermes-nube"]
    assert h.agente and h.privado and n.agente and not n.privado and n.motor == "hermes"
    assert Path(h.api_key_archivo).is_absolute()  # relativo a la carpeta de Skynet


def test_router_hermes_solo_en_conversacion(make_rt):
    rt = make_rt(None)
    assert rt.router.choose(Capabilities(force="hermes")).profile.nombre == "hermes"
    d = rt.router.choose(Capabilities(force="hermes", coding="alto"))  # Coder
    assert d.profile.nombre == "local" and "bucle de Skynet" in d.reason
    assert rt.router.choose(Capabilities(force="hermes", cost="bajo")).profile.nombre == "local"  # /largo
    # La nube de Hermes pide activación como cualquier modelo en línea.
    assert rt.router.choose(Capabilities(force="hermes-nube")).profile.nombre == "local"
    rt.access.activar_nube("hermes-nube", True)
    assert rt.router.choose(Capabilities(force="hermes-nube")).profile.nombre == "hermes-nube"


def test_clave_desde_archivo(make_rt, tmp_path):
    rt = make_rt(None)
    p = rt.settings.models["hermes"]
    p.api_key_archivo = str(tmp_path / "api_key")
    assert p.resolved_api_key() is None  # el motor aún no ha arrancado
    (tmp_path / "api_key").write_text("secreta\n", encoding="utf-8")
    assert p.resolved_api_key() == "secreta"


async def test_hermes_recibe_la_conversacion_sin_herramientas(make_rt):
    llm = ScriptedLLM([("Hola, soy Hermes.", None), ("Sigo aquí.", None)])
    rt = make_rt(llm)
    c = Coordinator(rt, FakeUI())
    c.force_model, c.internet = "hermes", True  # Internet no añade herramientas a un agente externo
    await c.handle("hola")
    await c.handle("¿sigues?")
    first, second = llm.calls
    assert first["api_base"] == "http://127.0.0.1:8642/v1" and first["model"] == "openai/local"
    assert "tools" not in first and all(m["role"] != "system" for m in first["messages"])
    # Historial real (la lista guardada incluye después la respuesta que el agente añade).
    assert [m["role"] for m in second["messages"]][:3] == ["user", "assistant", "user"]


async def test_coder_con_hermes_elegido_usa_skynet(make_rt):
    llm = ScriptedLLM([("Hecho sin cambios.", None)])
    rt = make_rt(llm)
    c = coder(Coordinator(rt, FakeUI()))
    c.force_model = "hermes"
    await c.handle("mira el repo")
    assert llm.calls[0]["api_base"] == "http://127.0.0.1:8090/v1" and llm.calls[0]["messages"][0]["role"] == "system"


def test_motor_con_comando_de_parar(tmp_path, monkeypatch):
    runs = []
    monkeypatch.setattr(eng.subprocess, "run", lambda args, **kw: runs.append(args))
    e = eng.load_engines({"hermes": {"tipo": "proceso", "url": "http://127.0.0.1:8642/v1", "exe": "{python}",
                                     "args": ["-m", "x"], "parar": ["{python}", "-m", "x", "stop"]}}, tmp_path)
    assert e.specs["hermes"].exe.lower().endswith(("python.exe", "python"))  # {python} = el de Skynet
    e.stop("hermes")
    assert runs and runs[0][-1] == "stop"


def test_lanzador_rutas_y_config(tmp_path, monkeypatch):
    assert hm.en_contenedor("C:/Users/HACHO") == "/c/Users/HACHO"
    assert hm.en_contenedor(r"C:\Git") == "/c/Git"
    monkeypatch.delenv("HERMES_NUBE_PROVEEDOR", raising=False)
    cfg = hm.config(["C:/Users/HACHO"])
    rutas = cfg["platforms"]["api_server"]["extra"]["model_routes"]
    assert set(rutas) == {"local"} and cfg["terminal"]["cwd"] == "/c/Users/HACHO"
    assert cfg["approvals"] == {"mode": "off", "unattended_mode": "approve"}
    monkeypatch.setenv("HERMES_NUBE_PROVEEDOR", "openrouter")
    monkeypatch.setenv("HERMES_NUBE_MODELO", "anthropic/claude-sonnet-5.5")
    assert hm.config([])["platforms"]["api_server"]["extra"]["model_routes"]["nube"]["provider"] == "openrouter"
    k = hm.clave(tmp_path / "d" / "api_key")
    assert len(k) > 20 and hm.clave(tmp_path / "d" / "api_key") == k  # se crea una vez
    json.dumps(cfg)  # viaja como JSON en una variable de entorno
