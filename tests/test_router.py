import pytest

from skynet.audit import Audit
from skynet.config import load_settings
from skynet.router import Capabilities, ModelRouter
from skynet.store import Store

from conftest import ScriptedLLM


@pytest.fixture
def router(home, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    settings = load_settings(home)
    store = Store(":memory:")
    yield ModelRouter(settings, store), settings, store
    store.close()


def test_default_is_local(router):
    r, _, _ = router
    assert r.choose(Capabilities()).profile.nombre == "local"


def test_privacy_always_local(router):
    r, s, _ = router
    s.budget_eur = 100
    d = r.choose(Capabilities(privacy="alta", reasoning="alto", force="cloud"))
    assert d.profile.nombre == "local" and "privacidad" in d.reason


def test_reasoning_high_without_key_falls_back(router):
    r, s, _ = router
    s.budget_eur = 100
    d = r.choose(Capabilities(reasoning="alto"))
    assert d.profile.nombre == "local" and "GEMINI_API_KEY" in d.reason


def test_reasoning_high_with_key_and_budget_goes_cloud(router, monkeypatch):
    r, s, _ = router
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    s.budget_eur = 10
    assert r.choose(Capabilities(force="cloud")).profile.nombre == "cloud"
    assert r.choose(Capabilities(reasoning="alto", cost="bajo")).profile.nombre == "local"


def test_budget_exhausted_falls_back(router, monkeypatch):
    r, s, store = router
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    s.budget_eur = 1
    store.add_event("llm", cost_eur=1.5)
    d = r.choose(Capabilities(force="cloud"))
    assert d.profile.nombre == "local" and "agotado" in d.reason


def test_budget_zero_disables_cloud(router, monkeypatch):
    r, s, _ = router
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    s.budget_eur = 0
    assert r.choose(Capabilities(force="cloud")).profile.nombre == "local"


async def test_complete_records_tokens_and_cost(router, monkeypatch):
    r, s, store = router
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    s.budget_eur = 10
    r._completion = ScriptedLLM([("<think>razono</think>Hola", None)])
    d = r.choose(Capabilities(force="cloud"))
    res = await r.complete(d, [{"role": "user", "content": "hola"}], None, Audit(store))
    assert res.content == "Hola"
    # 100 tokens in * 4 $/M + 20 out * 20 $/M = 0.0008 $ -> * 0.86
    assert res.cost_eur == pytest.approx(0.0008 * s.usd_eur)
    ev = store.events(types=("llm",))[-1]
    assert ev["tokens_in"] == 100 and ev["model"] == "anthropic/claude-opus-5-5"


def test_free_gemini_needs_no_budget(router, monkeypatch):
    r, s, _ = router
    s.budget_eur = 0
    assert r.choose(Capabilities(reasoning="alto")).profile.nombre == "local"  # sin clave
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert r.choose(Capabilities(reasoning="alto")).profile.nombre == "gemini"
    assert r.choose(Capabilities(reasoning="alto", privacy="alta")).profile.nombre == "local"


async def test_reasoning_level_is_sent(router):
    r, s, store = router
    llm = ScriptedLLM([("a", None), ("b", None)])
    r._completion = llm
    await r.complete(r.choose(Capabilities()), [{"role": "user", "content": "x"}], None, Audit(store), effort="high")
    assert llm.calls[0]["reasoning_effort"] == "high"
    strata = r.choose(Capabilities(force="strata"))
    await r.complete(strata, [{"role": "user", "content": "x"}], None, Audit(store), effort="low")
    assert llm.calls[1]["extra_body"] == {"reasoning_budget_tokens": 1024} and "reasoning_effort" not in llm.calls[1]
