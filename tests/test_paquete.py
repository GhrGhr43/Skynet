"""Paquete del 2026-10-10 (D21): permisos de Control total, Steam sin clics, índice de archivos e instrucciones."""
from __future__ import annotations

import time
from pathlib import Path

from conftest import FakeUI, ScriptedLLM
from test_steam import _env, _steam

from skynet.agent import comando_completo
from skynet.audit import Audit
from skynet.coordinator import Coordinator
from skynet.gate import Decision, PermissionGate
from skynet_tools import indice
from skynet_tools.steam import uninstall, write_manifest

USER = "C:/Users/HACHO"


def _dec(rt, key, args):
    return PermissionGate(rt.settings, None, Audit(rt.store), mode="total", user_home=USER).evaluate(key, args)


def test_control_total_mira_sin_preguntar_y_cambiar_el_sistema_si(make_rt):
    rt = make_rt(None)
    # Mirar dónde está Steam (Program Files) ya no pregunta; escribir ahí, borrar o administrador, sí.
    assert _dec(rt, "sistema.run_command", {"command": 'Get-ChildItem "C:\Program Files (x86)\Steam"'}).decision \
        is Decision.ALLOW
    assert _dec(rt, "sistema.run_command", {"command": 'Copy-Item a.dll "C:\Program Files\X"'}).decision \
        is Decision.ASK
    assert _dec(rt, "sistema.run_command", {"command": "Remove-Item C:/Users/HACHO/x.txt"}).decision is Decision.ASK
    assert _dec(rt, "sistema.run_command", {"command": "winget install --id Valve.Steam --silent"}).decision \
        is Decision.ALLOW
    assert _dec(rt, "sistema.write_file", {"path": "D:/Juegos/notas.txt"}).decision is Decision.ALLOW


def test_dialogo_muestra_el_comando_entero():
    largo = "Get-ChildItem -Recurse -Filter *.sav " + "C:/Users/HACHO/Documents/" * 10
    assert comando_completo({"command": largo}) == largo
    assert comando_completo({"destino": "steam://rungameid/1"}) == "steam://rungameid/1"


def test_desinstalar_steam_sin_clics(tmp_path):
    steam, _ = _steam(tmp_path)
    f = write_manifest(steam / "steamapps", 1942280, "Brotato")
    juego = steam / "steamapps" / "common" / "Brotato"
    (juego / "datos").mkdir(parents=True)
    (juego / "datos" / "x.bin").write_bytes(b"0" * 1000)
    paradas = []
    env, _ = _env(steam, stop=lambda s: paradas.append("stop") or True, start=lambda s: paradas.append("start"))
    msg = uninstall(1942280, env)
    assert "desinstalado" in msg and not f.exists() and not juego.exists()
    assert paradas == ["stop", "start"] and (steam / "steamapps").exists()
    assert "no está instalado" in uninstall(1942280, env)


def test_desinstalar_con_juego_abierto_no_toca_nada(tmp_path):
    steam, _ = _steam(tmp_path)
    f = write_manifest(steam / "steamapps", 7, "Otro")
    env, _ = _env(steam, game_running=lambda: True)
    assert "ciérralo" in uninstall(7, env) and f.exists()


def test_indice_de_archivos(tmp_path):
    raiz = tmp_path / "disco"
    for rel in ("Juegos/PEAK/PEAK.exe", "Docs/Factura 2025.pdf", "proyecto/node_modules/x/PEAK.exe",
                "AppData/secreto.txt"):
        p = raiz / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    db = tmp_path / "indice.db"
    assert indice.actualizar(db, [str(raiz)]) == 2  # node_modules y AppData no se recorren
    t0 = time.perf_counter()
    assert [n for n, *_ in indice.buscar(db, "peak.exe")] == ["PEAK.exe"]
    assert time.perf_counter() - t0 < 0.5
    assert [n for n, *_ in indice.buscar(db, "factura docs")] == ["Factura 2025.pdf"]  # la carpeta también cuenta
    assert indice.buscar(db, "secreto") == [] and indice.edad_h(db) < 0.1


async def test_skynet_md_y_agents_md(make_rt, home, repo_path):
    (home / "memoria").mkdir(exist_ok=True)
    (home / "memoria" / "SKYNET.md").write_text("Responde siempre con una frase como mucho.", encoding="utf-8")
    (repo_path / "AGENTS.md").write_text("En este repo los tests se escriben primero.", encoding="utf-8")
    llm = ScriptedLLM([("Vale.", None), ("Hecho.", None)])
    rt = make_rt(llm)
    c = Coordinator(rt, FakeUI())
    await c.handle("hola")
    assert "una frase como mucho" in llm.calls[0]["messages"][0]["content"]
    c.coder = True
    await c.handle("mira el repo")
    assert "tests se escriben primero" in str(llm.calls[1]["messages"])
