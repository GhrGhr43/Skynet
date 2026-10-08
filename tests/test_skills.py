"""Skills de solo lectura: formato SKILL.md, catálogo con tope, Context builder y /skills, /skill."""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ROOT, FakeUI, ScriptedLLM

from skynet import skills
from skynet.coordinator import Coordinator


def _write(base: Path, folder: str, text: str) -> None:
    (base / folder).mkdir(parents=True, exist_ok=True)
    (base / folder / "SKILL.md").write_text(text, encoding="utf-8")


SKILL = "---\nname: {n}\ndescription: {d}\n---\n\n# Cuerpo\nPaso secreto {n}.\n"


def test_parse_and_validation(tmp_path):
    _write(tmp_path, "buena", SKILL.format(n="buena", d="Hace cosas buenas."))
    _write(tmp_path, "plegada", "---\nname: plegada\ndescription: >\n  Primera línea\n  y segunda.\nlicense: MIT\n"
                                "metadata:\n  autor: x\n---\nCuerpo\n")
    _write(tmp_path, "otra-carpeta", SKILL.format(n="no-coincide", d="x"))
    _write(tmp_path, "Mayus", SKILL.format(n="Mayus", d="x"))
    _write(tmp_path, "sin-desc", "---\nname: sin-desc\n---\nx\n")
    _write(tmp_path, "sin-frontmatter", "# Solo cuerpo\n")
    (tmp_path / "vacia").mkdir()
    found, errors = skills.load_skills(tmp_path)
    assert list(found) == ["buena", "plegada"]
    assert found["plegada"].description == "Primera línea y segunda."
    assert found["buena"].body() == "# Cuerpo\nPaso secreto buena."
    assert len(errors) == 4 and any("no coincide" in e for e in errors)
    assert skills.load_skills(tmp_path / "no-existe") == ({}, [])


def test_catalog_cap(tmp_path):
    for i in range(50):
        _write(tmp_path, f"s{i:02d}", SKILL.format(n=f"s{i:02d}", d="descripción " * 20))
    found, _ = skills.load_skills(tmp_path)
    cat = skills.catalog(found, max_chars=1000)
    assert len(cat) < 1100 and "skills más" in cat and "s00" in cat and "s49" not in cat


def test_example_skill_is_valid():
    found, errors = skills.load_skills(ROOT / "skills")
    assert "escribir-tests" in found and not errors


def _system_and_user(llm: ScriptedLLM) -> str:
    return "\n".join(str(m.get("content")) for m in llm.calls[0]["messages"])


async def test_skill_command_in_chat_and_repo(make_rt, home):
    _write(home / "skills", "revisar", SKILL.format(n="revisar", d="Revisar código con lista de comprobación."))
    _write(home / "skills", "traducir", SKILL.format(n="traducir", d="Traducir textos al inglés."))
    llm = ScriptedLLM([("hecho", None), ("hecho", None), ("hecho", None)])
    rt = make_rt(llm)
    ui = FakeUI()
    c = Coordinator(rt, ui)

    await c.handle("/skills")
    assert any("revisar: Revisar código" in i for i in ui.infos)

    # Sin repo: el cuerpo de la skill elegida entra; de las demás, solo el catálogo
    await c.handle("/repo ninguno")
    await c.handle("/skill revisar mira este texto")
    ctx = _system_and_user(llm)
    assert "Paso secreto revisar." in ctx and "traducir: Traducir textos" in ctx
    assert "Paso secreto traducir." not in ctx
    task = rt.store.list_tasks(1)[0]
    assert task.goal == "mira este texto" and task.capabilities["skill"] == "revisar"

    # Con repo: el Context builder la mete como sección, y también al retomar
    await c.handle("/repo prueba")
    llm.calls.clear()
    await c.handle("hola")
    ctx = _system_and_user(llm)
    assert "Skills disponibles" in ctx and "Paso secreto" not in ctx
    t = rt.store.create_task("x", "objetivo", agent="skynet", repo="prueba", capabilities={"skill": "traducir"})
    sections = {s.title: s.body for s in rt.context.sections(t, rt.settings.repo("prueba"))}
    assert any("Paso secreto traducir." in b for b in sections.values())


@pytest.mark.parametrize("cmd,expected", [
    ("/skill", "Uso: /skill"),
    ("/skill nadie hazlo", "No existe la skill"),
    ("/skill revisar", "Uso: /skill revisar <tarea>"),
])
async def test_skill_command_errors(make_rt, home, cmd, expected):
    _write(home / "skills", "revisar", SKILL.format(n="revisar", d="Revisar."))
    rt = make_rt(ScriptedLLM([]))
    ui = FakeUI()
    await Coordinator(rt, ui).handle(cmd)
    assert expected in ui.infos[-1] and rt.store.list_tasks() == []


async def test_skills_empty(make_rt):
    ui = FakeUI()
    await Coordinator(make_rt(ScriptedLLM([])), ui).handle("/skills")
    assert "No hay skills" in ui.infos[-1]
