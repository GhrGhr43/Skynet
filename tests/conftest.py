"""Utilidades de test: un SKYNET_HOME temporal y un LLM guionizado (sin red ni GPU)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from skynet import gitops
from skynet.config import load_settings
from skynet.runtime import Runtime

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_MOD = "VERSION = 1\n\n\ndef doble(x):\n    raise NotImplementedError\n"

# Que "python -m pytest" del verificador use el Python de este entorno
_scripts = str(Path(sys.executable).parent)
import os  # noqa: E402

if not os.environ.get("PATH", "").lower().startswith(_scripts.lower()):
    os.environ["PATH"] = _scripts + os.pathsep + os.environ.get("PATH", "")


def tool_call(name: str, args: dict[str, Any], id: str | None = None) -> dict[str, Any]:
    return {"tool": name, "args": args, "id": id}


def make_response(content: str = "", calls: list[dict[str, Any]] | None = None) -> Any:
    tcs = None
    if calls:
        tcs = [SimpleNamespace(id=c.get("id") or f"call_{i}_{c['tool']}", type="function",
                               function=SimpleNamespace(name=c["tool"], arguments=json.dumps(c["args"])))
               for i, c in enumerate(calls)]
    msg = SimpleNamespace(content=content, tool_calls=tcs)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="tool_calls" if tcs else "stop")],
                           usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20))


class ScriptedLLM:
    """Devuelve respuestas en orden. Cada elemento es (content, calls) o una función(messages) -> (content, calls)."""

    def __init__(self, script: list[Any]):
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.script:
            return make_response("Terminado (guion agotado).")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(kwargs["messages"])
        content, calls = item
        return make_response(content, calls)


def herramientas(call: dict[str, Any]) -> set[str]:
    """Herramientas que vio el modelo en una llamada, sin las internas de Skynet (van siempre en el chat: D20, D21)."""
    return {t["function"]["name"] for t in call.get("tools") or []} - {"memoria", "crear_proyecto", "tarea_larga",
                                                                       "ver_skill"}


def coder(c):
    """Coordinator con el modo Coder activado (el repo elegido entra en las tareas)."""
    c.coder = True
    return c


# Perfiles de prueba en la nube: la config real solo trae local y Hermes (D19), pero el router, el presupuesto y
# la activación de modelos en línea son genéricos y se siguen probando con estos.
PERFILES_PRUEBA = '''
[modelos.gemini]
litellm = "gemini/gemini-flash-latest"
api_key_env = "GEMINI_API_KEY"
privado = false
coste_entrada_usd_mtok = 0
coste_salida_usd_mtok = 0

[modelos.omniroute]
litellm = "openai/skynet"
api_base = "http://127.0.0.1:20128/v1"
api_key = "omniroute"
privado = false
coste_entrada_usd_mtok = 0
coste_salida_usd_mtok = 0

[modelos.cloud]
litellm = "anthropic/claude-opus-5-5"
api_key_env = "ANTHROPIC_API_KEY"
privado = false
coste_entrada_usd_mtok = 4.0
coste_salida_usd_mtok = 20.0
max_tokens = 16000
'''


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / "config").mkdir(parents=True)
    for f in ("skynet.toml", "permisos.toml", "router.toml"):
        shutil.copy(ROOT / "config" / f, h / "config" / f)
    router = (h / "config" / "router.toml").read_text(encoding="utf-8")
    (h / "config" / "router.toml").write_text(router.rstrip() + "\n" + PERFILES_PRUEBA, encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "conftest.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n",
        encoding="utf-8")
    (repo / "tests" / "test_mod.py").write_text(
        "from mod import doble\n\n\ndef test_doble():\n    assert doble(3) == 6\n", encoding="utf-8")
    (repo / "tests" / "test_ok.py").write_text(
        "from mod import VERSION\n\n\ndef test_version():\n    assert VERSION == 1\n", encoding="utf-8")
    (repo / "mod.py").write_text(ORIGINAL_MOD, encoding="utf-8")
    gitops.ensure_repo(repo)
    gitops.commit_all(repo, "inicial")
    (h / "config" / "repos.toml").write_text(
        f'[repos.prueba]\nruta = "{repo.as_posix()}"\nverificador = "python -m pytest -q"\n', encoding="utf-8")
    return h


@pytest.fixture
def repo_path(home: Path) -> Path:
    return home.parent / "repo"


@pytest.fixture
def make_rt(home: Path) -> Callable[[ScriptedLLM | None], Runtime]:
    created: list[Runtime] = []

    def _make(llm: ScriptedLLM | None = None) -> Runtime:
        rt = Runtime(load_settings(home), completion_fn=llm)
        created.append(rt)
        return rt

    yield _make
    for rt in created:
        rt.store.close()


class FakeUI:
    def __init__(self, answers: list[str] | None = None):
        self.answers = list(answers or [])
        self.infos: list[str] = []
        self.answers_given: list[str] = []
        self.prompts: list[str] = []
        self.events: list[tuple[str, dict]] = []

    def info(self, text: str) -> None:
        self.infos.append(text)

    def answer(self, text: str) -> None:
        self.answers_given.append(text)

    def show(self, renderable: Any) -> None:
        self.infos.append(str(renderable))

    def event(self, kind: str, data: dict) -> None:
        self.events.append((kind, data))

    async def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else "n"
