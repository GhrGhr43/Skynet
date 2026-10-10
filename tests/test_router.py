import dataclasses

import pytest

from skynet.audit import Audit
from skynet.config import load_settings
from skynet.router import Capabilities, ModelRouter, RouteDecision
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


async def test_sampling_and_max_tokens_are_sent(router):
    r, s, store = router
    llm = ScriptedLLM([("a", None), ("b", None)])
    r._completion = llm
    prof = dataclasses.replace(s.models["local"], temperatura=0.6, top_p=0.95, top_k=20, min_p=0.0,
                               presence_penalty=None)
    await r.complete(RouteDecision(prof, "x"), [{"role": "user", "content": "x"}], None, Audit(store),
                     max_tokens=2000)
    call = llm.calls[0]
    assert call["temperature"] == 0.6 and call["top_p"] == 0.95 and call["max_tokens"] == 2000
    assert call["extra_body"]["top_k"] == 20 and call["extra_body"]["min_p"] == 0.0
    assert "presence_penalty" not in call
    plain = dataclasses.replace(s.models["local"], temperatura=None, top_p=None, top_k=None, min_p=None,
                                reasoning_effort=None)
    await r.complete(RouteDecision(plain, "x"), [{"role": "user", "content": "x"}], None, Audit(store))
    assert "temperature" not in llm.calls[1] and "extra_body" not in llm.calls[1]
    assert llm.calls[1]["max_tokens"] == plain.max_tokens


def test_context_window_comes_from_engine(router):
    _, s, _ = router
    local = s.models["local"]
    motor = s.engines.get("local", {}).get("contexto")
    assert local.contexto_tokens == (motor or 128_000)


def test_omniroute_nunca_con_privacidad(router):
    r, _, _ = router
    assert r.choose(Capabilities(force="omniroute")).profile.nombre == "omniroute"
    d = r.choose(Capabilities(force="omniroute", privacy="alta"))
    assert d.profile.nombre == "local" and "privacidad" in d.reason
