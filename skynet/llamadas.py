"""Arreglos para las llamadas a herramientas de modelos locales.

Los modelos pequeños fallan a menudo en el formato: JSON con comas finales, comillas simples,
bloques ```json, o la llamada escrita como texto (`<tool_call>{...}</tool_call>` de Qwen) en
vez de como tool call. Cada fallo costaba un turno entero. Aquí se reparan sin LLM; si no se
puede, el agente devuelve el error como antes.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.DOTALL)
TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def parse_args(raw: Any) -> tuple[dict[str, Any], bool]:
    """Argumentos de una llamada como dict. Devuelve (args, reparado). Lanza ValueError si no hay forma."""
    if isinstance(raw, dict):
        return raw, False
    text = (raw or "").strip() or "{}"
    try:
        val = json.loads(text)
        if isinstance(val, dict):
            return val, False
    except ValueError:
        pass
    val = _repair(text)
    if not isinstance(val, dict):
        raise ValueError("los argumentos no son un objeto JSON")
    return val, True


def _repair(text: str) -> Any:
    m = FENCE_RE.match(text)
    if m:
        text = m.group(1)
    try:  # librería json-repair si está instalada (cubre más casos)
        from json_repair import repair_json

        val = repair_json(text, return_objects=True)
        if isinstance(val, dict):
            return val
    except ImportError:
        pass
    candidates = [text, TRAILING_COMMA_RE.sub(r"\1", text)]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        inner = text[start:end + 1]
        candidates += [inner, TRAILING_COMMA_RE.sub(r"\1", inner)]
    if text.count("{") > text.count("}"):  # cortado al final
        candidates.append(text + "}" * (text.count("{") - text.count("}")))
    for c in candidates:
        for variant in (c, c.replace("'", '"')):
            try:
                return json.loads(variant)
            except ValueError:
                continue
    raise ValueError("JSON irreparable")


def calls_in_text(content: str, known: set[str]) -> tuple[list[dict[str, Any]], str]:
    """Llamadas escritas como texto en la respuesta (formato Qwen/Hermes `<tool_call>`).
    Solo cuenta las de herramientas que existen. Devuelve (tool_calls, texto sin ellas)."""
    if "<tool_call>" not in content:
        return [], content
    calls = []
    for body in TOOL_CALL_RE.findall(content):
        try:
            obj = _repair(body) if body.strip() else None
        except ValueError:
            continue
        if not isinstance(obj, dict) or obj.get("name") not in known:
            continue
        args = obj.get("arguments", obj.get("parameters", {}))
        calls.append({"id": f"txt_{uuid.uuid4().hex[:12]}", "type": "function",
                      "function": {"name": obj["name"],
                                   "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)}})
    if not calls:
        return [], content
    return calls, TOOL_CALL_RE.sub("", content).strip()
