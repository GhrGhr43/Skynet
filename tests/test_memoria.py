"""Memoria que el modelo escribe por su cuenta (D20)."""
from __future__ import annotations

from conftest import FakeUI, ScriptedLLM, tool_call

from skynet import memoria
from skynet.coordinator import Coordinator


def _leer(home, nombre):
    return (home / "memoria" / nombre).read_text(encoding="utf-8")


def test_guardar_reemplazar_quitar(tmp_path):
    ok, msg = memoria.aplicar(tmp_path, {"accion": "guardar", "destino": "usuario", "texto": "Tests en pruebas/"})
    assert ok and "USER.md" in msg
    assert memoria.aplicar(tmp_path, {"accion": "guardar", "destino": "usuario", "texto": "tests en pruebas/"})[1] == \
        "Ya estaba guardado."
    memoria.aplicar(tmp_path, {"accion": "guardar", "destino": "entorno", "texto": "Steam está en D:/Steam"})
    assert memoria.aplicar(tmp_path, {"accion": "reemplazar", "destino": "usuario", "texto": "pruebas",
                                      "nuevo": "Tests en pruebas/ y nombres en español"})[0]
    assert "- Tests en pruebas/ y nombres en español" in _leer(tmp_path, "USER.md")
    assert "D:/Steam" in _leer(tmp_path, "MEMORY.md")
    assert memoria.aplicar(tmp_path, {"accion": "quitar", "destino": "usuario", "texto": "español"})[0]
    assert "pruebas" not in _leer(tmp_path, "USER.md")


def test_respeta_lo_escrito_a_mano(tmp_path):
    f = tmp_path / "memoria" / "USER.md"
    f.parent.mkdir()
    f.write_text("# Preferencias del usuario\n\nNota mía: no tocar.\n- vieja\n", encoding="utf-8")
    memoria.aplicar(tmp_path, {"accion": "guardar", "destino": "usuario", "texto": "nueva"})
    memoria.aplicar(tmp_path, {"accion": "quitar", "destino": "usuario", "texto": "vieja"})
    text = _leer(tmp_path, "USER.md")
    assert "Nota mía: no tocar." in text and "- nueva" in text and "vieja" not in text


def test_rechaza_secretos_ambiguos_y_llena(tmp_path):
    assert not memoria.aplicar(tmp_path, {"accion": "guardar", "destino": "entorno", "texto": "password: hunter2"})[0]
    assert not memoria.aplicar(tmp_path, {"accion": "guardar", "destino": "entorno", "texto": "clave sk-abcdefghijklmnopqrstu"})[0]
    for t in ("uno a", "uno b"):
        memoria.aplicar(tmp_path, {"accion": "guardar", "destino": "entorno", "texto": t})
    ok, msg = memoria.aplicar(tmp_path, {"accion": "quitar", "destino": "entorno", "texto": "uno"})
    assert not ok and "2 entradas" in msg
    ok, msg = memoria.aplicar(tmp_path, {"accion": "guardar", "destino": "entorno", "texto": "x" * 2100})
    assert not ok and "2048" in msg


async def test_el_modelo_guarda_y_la_siguiente_sesion_lo_ve(make_rt):
    llm = ScriptedLLM([
        ("", [tool_call("memoria", {"accion": "guardar", "destino": "usuario",
                                    "texto": "Los tests van en la carpeta pruebas/"})]),
        ("Apuntado.", None),
        ("Vale.", None),
    ])
    rt = make_rt(llm)
    await Coordinator(rt, FakeUI()).handle("Apúntate que mis tests van en pruebas/")
    assert "pruebas/" in _leer(rt.settings.home, "USER.md")
    assert any(e["type"] == "memoria" for e in rt.store.events(limit=50))
    assert any(t["function"]["name"] == "memoria" for t in llm.calls[0]["tools"])
    await Coordinator(rt, FakeUI()).handle("hola")  # sesión nueva: la memoria va en el system prompt
    assert "pruebas/" in llm.calls[-1]["messages"][0]["content"]
