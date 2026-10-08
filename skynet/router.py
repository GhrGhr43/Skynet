"""Model router: los agentes piden capacidades, no modelos (principio 4).

`choose()` aplica las reglas de config/router.toml (gana la primera que encaja) y comprueba
que el perfil elegido esté disponible (clave de API) y que quede presupuesto mensual; si no,
cae al modelo local y lo dice en el motivo. `complete()` llama a LiteLLM y calcula tokens y
coste en euros. Toda decisión y llamada queda auditada.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable

from .audit import Audit
from .config import ModelProfile, Settings
from .store import Store

CompletionFn = Callable[..., Awaitable[Any]]


@dataclass
class Capabilities:
    privacy: str = "normal"   # normal | alta
    coding: str = "medio"     # bajo | medio | alto
    reasoning: str = "medio"  # bajo | medio | alto
    cost: str = "medio"       # bajo | medio | alto  (bajo = hay que gastar poco)
    force: str | None = None  # "local" / "cloud": preferencia explícita del usuario
    effort: str | None = None  # low | medium | high: cuánto razona el modelo (None = lo del perfil)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Capabilities":
        d = dict(d or {})
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class RouteDecision:
    profile: ModelProfile
    reason: str


@dataclass
class LLMResult:
    message: dict[str, Any]           # mensaje del asistente en formato OpenAI
    tokens_in: int
    tokens_out: int
    cost_eur: float
    finish_reason: str | None
    raw: Any = field(repr=False, default=None)

    @property
    def content(self) -> str:
        return self.message.get("content") or ""

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return self.message.get("tool_calls") or []


class RouterError(Exception):
    pass


REASONING_TOKENS = {"low": 1024, "medium": 4096, "high": 16384}

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _litellm_completion() -> CompletionFn:
    import litellm

    litellm.suppress_debug_info = True
    litellm.drop_params = True
    return litellm.acompletion


class ModelRouter:
    def __init__(self, settings: Settings, store: Store, completion_fn: CompletionFn | None = None):
        self.settings = settings
        self.store = store
        self._completion = completion_fn

    @property
    def completion(self) -> CompletionFn:
        if self._completion is None:
            self._completion = _litellm_completion()
        return self._completion

    # --- elección --------------------------------------------------------
    def _rule_matches(self, cond: dict[str, Any], caps: Capabilities) -> bool:
        c = caps.to_dict()
        return all(str(c.get(k)) == str(v) for k, v in cond.items())

    def _usable(self, profile: ModelProfile) -> tuple[bool, str]:
        ok, why = profile.available()
        if not ok:
            return False, why
        gratis = profile.coste_entrada_usd_mtok == 0 and profile.coste_salida_usd_mtok == 0
        if not profile.privado and not gratis:
            if self.settings.budget_eur <= 0:
                return False, "presupuesto cloud a 0 (desactivado en router.toml)"
            spent = self.store.month_cost_eur()
            if spent >= self.settings.budget_eur:
                return False, f"presupuesto mensual agotado ({spent:.2f}/{self.settings.budget_eur:.2f} €)"
        return True, ""

    def choose(self, caps: Capabilities) -> RouteDecision:
        models = self.settings.models
        local = models["local"]
        if caps.privacy == "alta":
            return RouteDecision(local, "privacidad alta: siempre local")
        if caps.force in models:
            target, why = caps.force, f"elegido por el usuario ({caps.force})"
        else:
            target, why = "local", "por defecto: local"
            for rule in self.settings.rules:
                if self._rule_matches(rule.get("si", {}), caps):
                    target, why = rule["usar"], rule.get("motivo", f"regla {rule.get('si')}")
                    break
        profile = models.get(target)
        if profile is None:
            return RouteDecision(local, f"{why}; el perfil '{target}' no existe, uso local")
        if target != "local":
            ok, problem = self._usable(profile)
            if not ok:
                return RouteDecision(local, f"{why}; pero {problem}: uso local")
        return RouteDecision(profile, why)

    # --- llamada ---------------------------------------------------------
    def _cost_eur(self, profile: ModelProfile, response: Any, tin: int, tout: int) -> float:
        if profile.coste_entrada_usd_mtok is not None and profile.coste_salida_usd_mtok is not None:
            usd = tin / 1e6 * profile.coste_entrada_usd_mtok + tout / 1e6 * profile.coste_salida_usd_mtok
        else:
            try:
                import litellm

                usd = float(litellm.completion_cost(completion_response=response) or 0.0)
            except Exception:
                usd = 0.0
        return round(usd * self.settings.usd_eur, 6)

    async def complete(
        self,
        decision: RouteDecision,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        audit: Audit,
        effort: str | None = None,
    ) -> LLMResult:
        p = decision.profile
        kwargs: dict[str, Any] = {
            "model": p.litellm,
            "messages": messages,
            "max_tokens": p.max_tokens,
            "timeout": p.timeout_seg,
            "num_retries": 1,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if p.api_base:
            kwargs["api_base"] = p.api_base
        level = effort or p.reasoning_effort
        if level:
            if p.razonamiento_por_tokens:
                kwargs["extra_body"] = {"reasoning_budget_tokens": REASONING_TOKENS.get(level, 4096)}
            else:
                kwargs["reasoning_effort"] = level
        key = p.resolved_api_key()
        if key:
            kwargs["api_key"] = key
        try:
            response = await self.completion(**kwargs)
        except Exception as e:
            audit.log("error", model=p.litellm, detail={"mensaje": f"{type(e).__name__}: {e}"[:2000],
                                                         "motivo_ruta": decision.reason})
            raise RouterError(f"El modelo {p.litellm} falló: {type(e).__name__}: {e}") from e

        choice = response.choices[0]
        msg = choice.message
        content = THINK_RE.sub("", getattr(msg, "content", None) or "").strip()
        tool_calls = []
        for tc in getattr(msg, "tool_calls", None) or []:
            tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
            })
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        usage = getattr(response, "usage", None)
        tin = int(getattr(usage, "prompt_tokens", 0) or 0)
        tout = int(getattr(usage, "completion_tokens", 0) or 0)
        cost = self._cost_eur(p, response, tin, tout)
        finish = getattr(choice, "finish_reason", None)
        audit.log("llm", model=p.litellm, tokens_in=tin, tokens_out=tout, cost_eur=cost,
                  detail={"motivo_ruta": decision.reason, "fin": finish, "herramientas_pedidas": len(tool_calls)})
        return LLMResult(message, tin, tout, cost, finish, response)
