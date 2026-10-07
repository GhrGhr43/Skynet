import pytest

from jarvis.audit import Audit
from jarvis.config import load_settings
from jarvis.gate import Decision, Level, PermissionGate, command_whitelisted
from jarvis.store import Store


@pytest.fixture
def ctx(home):
    settings = load_settings(home)
    store = Store(":memory:")
    yield settings, settings.repo("prueba"), Audit(store), store
    store.close()


def gate(ctx, asker=None, grants=None):
    settings, repo, audit, _ = ctx
    return PermissionGate(settings, repo, audit, asker=asker, grants=grants)


def test_classification(ctx):
    g = gate(ctx)
    assert g.classify("workspace.read_file") is Level.READ
    assert g.classify("workspace.delete_file") is Level.DESTRUCTIVE
    assert g.classify("desconocido.algo") is Level.PRIVILEGED


def test_read_and_write_inside_repo_allowed(ctx):
    g = gate(ctx)
    assert g.evaluate("workspace.read_file", {"path": "mod.py"}).decision is Decision.ALLOW
    assert g.evaluate("workspace.write_file", {"path": "nuevo/a.py", "content": "x"}).decision is Decision.ALLOW


@pytest.mark.parametrize("path", ["../fuera.txt", "C:/Windows/system.ini", ".git/config"])
def test_paths_outside_or_git_denied(ctx, path):
    r = gate(ctx).evaluate("workspace.write_file", {"path": path, "content": "x"})
    assert r.decision is Decision.DENY


def test_execute_whitelist(ctx):
    g = gate(ctx)
    assert g.evaluate("workspace.run_command", {"command": "python -m pytest -q tests"}).decision is Decision.ALLOW
    assert g.evaluate("workspace.run_command", {"command": "pip install requests"}).decision is Decision.ASK
    r = g.evaluate("workspace.run_command", {"command": "python -m pytest & del /q *"})
    assert r.decision is Decision.ASK and "encadena" in r.reason


def test_whitelist_prefix_is_word_based():
    assert command_whitelisted("pytest -q", ["pytest"])
    assert not command_whitelisted("pytest-evil", ["pytest"])


async def test_ask_without_human_is_denied_and_audited(ctx):
    _, _, _, store = ctx
    r = await gate(ctx).check("workspace.delete_file", {"path": "mod.py"})
    assert r.decision is Decision.DENY
    ev = store.events(types=("permission",))[-1]
    assert ev["decision"] == "denegado" and ev["permission_level"] == "DESTRUCTIVE"


async def test_ask_yes_no_and_session_grant(ctx):
    answers = iter(["n", "t"])

    async def asker(key, level, args, reason):
        return next(answers)

    g = gate(ctx, asker=asker)
    assert not (await g.check("workspace.run_command", {"command": "pip list"})).allowed
    assert (await g.check("workspace.run_command", {"command": "pip list"})).allowed
    # "t" concede la herramienta el resto de la tarea, sin volver a preguntar
    assert (await g.check("workspace.run_command", {"command": "pip freeze"})).allowed


async def test_destructive_never_session_granted(ctx):
    calls = []

    async def asker(key, level, args, reason):
        calls.append(key)
        return "t"

    g = gate(ctx, asker=asker)
    assert (await g.check("workspace.delete_file", {"path": "mod.py"})).allowed
    assert (await g.check("workspace.delete_file", {"path": "mod.py"})).allowed
    assert len(calls) == 2


def test_preapproved_grants(ctx):
    g = gate(ctx, grants=["coding_agent.*"])
    assert g.evaluate("coding_agent.start_task", {}).decision is Decision.ALLOW
    assert gate(ctx).evaluate("coding_agent.start_task", {}).decision is Decision.ASK


def test_protected_paths(ctx):
    settings, repo, audit, _ = ctx
    g = PermissionGate(settings, repo, audit, protected=["PROGRESO.md"])
    assert g.evaluate("workspace.write_file", {"path": "progreso.md", "content": "x"}).decision is Decision.DENY
    assert g.evaluate("workspace.edit_file", {"path": "./PROGRESO.md"}).decision is Decision.DENY
    assert g.evaluate("workspace.read_file", {"path": "PROGRESO.md"}).decision is Decision.ALLOW
    assert g.evaluate("workspace.write_file", {"path": "otro.md", "content": "x"}).decision is Decision.ALLOW
