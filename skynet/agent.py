"""Agente con herramientas: el bucle modelo -> herramientas -> modelo de un paso.

Cada llamada a herramienta pasa por el permission gate y queda auditada. El agente no
decide si su trabajo es bueno: eso lo hace el verificador fuera de este bucle.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .audit import Audit
from .config import RepoConfig
from .gate import PermissionGate
from .router import Capabilities, ModelRouter, RouteDecision, RouterError
from .toolhub import ToolHub

DONE_MARK = "OBJETIVO_CUMPLIDO"

SYSTEM_CODER = """Eres Skynet, un agente de programación que trabaja en el repo "{repo}" en Windows.
Todas las rutas son relativas a la raíz del repo.
Reglas:
- Usa las herramientas para leer, buscar y editar. No inventes el contenido de archivos que no has leído.
- Haz cambios pequeños y precisos (edit_file mejor que reescribir archivos enteros).
- {verificador}
- Si una herramienta es denegada, no insistas: busca otra forma o explica qué necesitas.
- Cuando termines, responde SIN llamar a herramientas con un resumen breve: qué cambiaste y cómo lo comprobaste.
Responde siempre en español."""

SYSTEM_CHAT = """Eres Skynet, el asistente personal de Daniel. Responde en español, breve y claro.
Si no tienes herramientas en esta conversación, no tienes acceso a archivos: si hace falta trabajar sobre
un repo, dile que lo elija con /repo <nombre>; si hace falta tocar su PC, que suba el modo de permisos
del modelo en Ajustes (o con /permisos)."""

EventFn = Callable[[str, dict[str, Any]], None]


@dataclass
class AgentOutcome:
    status: str                 # completado | limite_turnos | error
    final_text: str
    turns: int = 0
    tool_calls: int = 0
    denied: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_eur: float = 0.0
    model: str = ""
    error: str | None = None
    claims_done: bool = False
    files_touched: list[str] = field(default_factory=list)


def summarize_args(args: dict[str, Any]) -> str:
    parts = []
    for k, v in args.items():
        if isinstance(v, str):
            v = v if len(v) <= 100 else f"<{len(v)} caracteres>"
        parts.append(f"{k}={v!r}" if isinstance(v, str) else f"{k}={json.dumps(v, ensure_ascii=False)[:100]}")
    return ", ".join(parts)


def system_prompt_for(repo: RepoConfig | None) -> str:
    if repo is None:
        return SYSTEM_CHAT
    ver = (f"Antes de terminar, comprueba tu trabajo ejecutando el verificador con run_command: `{repo.verificador}`."
           if repo.verificador else "Comprueba tu trabajo antes de terminar si hay forma de hacerlo.")
    return SYSTEM_CODER.format(repo=repo.nombre, verificador=ver)


class Agent:
    def __init__(
        self,
        router: ModelRouter,
        gate: PermissionGate | None,
        hub: ToolHub | None,
        audit: Audit,
        max_tool_output: int = 6000,
        on_event: EventFn | None = None,
    ):
        self.router = router
        self.gate = gate
        self.hub = hub
        self.audit = audit
        self.max_tool_output = max_tool_output
        self.on_event = on_event or (lambda kind, data: None)

    def _clip(self, text: str) -> str:
        n = self.max_tool_output
        if len(text) <= n:
            return text
        return text[: n // 2] + f"\n... [{len(text) - n} caracteres omitidos] ...\n" + text[-n // 2:]

    async def run(
        self,
        system: str,
        user_content: str,
        caps: Capabilities,
        max_turns: int = 30,
    ) -> AgentOutcome:
        decision: RouteDecision = self.router.choose(caps)
        self.audit.log("route", model=decision.profile.litellm,
                       detail={"motivo": decision.reason, "capacidades": caps.to_dict()})
        self.on_event("route", {"model": decision.profile.litellm, "reason": decision.reason})

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        tools = self.hub.openai_tools() if self.hub else None
        out = AgentOutcome(status="error", final_text="", model=decision.profile.litellm)
        seen: dict[str, int] = {}
        touched: set[str] = set()

        for turn in range(1, max_turns + 1):
            out.turns = turn
            self.on_event("thinking", {"turn": turn})
            t0 = time.monotonic()
            try:
                res = await self.router.complete(decision, messages, tools, self.audit, effort=caps.effort)
            except RouterError as e:
                out.status, out.error = "error", str(e)
                out.final_text = str(e)
                return out
            out.tokens_in += res.tokens_in
            out.tokens_out += res.tokens_out
            # segundos de la llamada entera (incluye leer el prompt): la web muestra tokens/s con esto
            self.on_event("usage", {"tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                                    "model": decision.profile.litellm, "segundos": round(time.monotonic() - t0, 3)})
            out.cost_eur += res.cost_eur
            messages.append(res.message)

            if not res.tool_calls:
                out.status = "completado"
                out.final_text = res.content or "(el modelo terminó sin decir nada)"
                out.claims_done = DONE_MARK in out.final_text
                out.files_touched = sorted(touched)
                return out

            if res.content:
                self.on_event("say", {"text": res.content})
            for tc in res.tool_calls:
                text = await self._run_tool(tc, seen, touched, out)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": text})

        out.status = "limite_turnos"
        out.final_text = f"Alcancé el límite de {max_turns} turnos sin terminar."
        out.files_touched = sorted(touched)
        return out

    async def _run_tool(self, tc: dict[str, Any], seen: dict[str, int], touched: set[str],
                        out: AgentOutcome) -> str:
        name = tc["function"]["name"]
        raw = tc["function"].get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
            if not isinstance(args, dict):
                raise ValueError("los argumentos no son un objeto")
        except (ValueError, TypeError) as e:
            self.audit.log("tool", tool=name, decision="error", detail={"motivo": f"argumentos inválidos: {e}"})
            return f"ERROR: argumentos JSON inválidos ({e}). Repite la llamada con JSON válido."

        spec = self.hub.resolve(name) if self.hub else None
        if spec is None or self.gate is None:
            return f"ERROR: la herramienta '{name}' no existe."
        out.tool_calls += 1
        args_summary = summarize_args(args)

        sig = name + json.dumps(args, sort_keys=True, ensure_ascii=False)
        seen[sig] = seen.get(sig, 0) + 1
        if seen[sig] > 2:
            self.audit.log("tool", tool=spec.key, decision="bloqueado",
                           detail={"args_resumen": args_summary, "motivo": "llamada repetida"})
            return "ERROR: ya hiciste exactamente esta llamada dos veces. Cambia de enfoque."

        self.on_event("tool", {"key": spec.key, "args": args_summary})
        gr = await self.gate.check(spec.key, args, args_summary)
        if not gr.allowed:
            out.denied += 1
            self.audit.log("tool", tool=spec.key, permission_level=gr.level.name, decision=gr.decision.value,
                           detail={"args_resumen": args_summary, "motivo": gr.reason})
            self.on_event("denied", {"key": spec.key, "reason": gr.reason})
            return f"DENEGADO por el permission gate ({gr.level.name}): {gr.reason}."

        result = await self.hub.call(name, args)
        if result.ok and gr.level.name in ("WRITE", "DESTRUCTIVE") and isinstance(args.get("path"), str):
            touched.add(args["path"])
        first_line = result.text.strip().splitlines()[0][:150] if result.text.strip() else ""
        self.audit.log("tool", tool=spec.key, permission_level=gr.level.name, decision=gr.decision.value,
                       detail={"args_resumen": args_summary, "ok": result.ok, "resultado": first_line,
                               "caracteres": len(result.text)})
        self.on_event("tool_result", {"key": spec.key, "ok": result.ok, "first_line": first_line})
        return self._clip(result.text if result.ok else f"ERROR: {result.text}")
