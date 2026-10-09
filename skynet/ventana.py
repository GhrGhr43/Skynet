"""Ventana de contexto del bucle del agente: que el historial quepa en el contexto del modelo.

El modelo local tiene 32K de contexto. Sin esto, cada resultado de herramienta se queda en el
historial para siempre y a los 12-20 turnos el modelo trabaja con el contexto lleno (o el
servidor corta). Se hace sin LLM (principio 5), en dos pasos y solo cuando hace falta:

1. Pasada la mitad del contexto, las salidas de herramientas antiguas (todas menos las últimas)
   se quedan en una línea.
2. Si aún no cabe, los turnos del medio se sustituyen por un resumen de lo hecho
   (herramientas usadas y primera línea de cada resultado). Se conservan siempre el system
   prompt, el mensaje inicial (objetivo y contexto) y los últimos turnos.

Los tokens se estiman por caracteres: no hace falta exactitud, solo no pasarse.
"""
from __future__ import annotations

import json
from typing import Any

CHARS_PER_TOKEN = 3.5     # conservador para español y código con el tokenizador de Qwen
MARGEN = 512              # tokens de holgura por el formato del chat y los esquemas
MIN_SALIDA = 1024         # nunca se piden menos tokens de salida que esto
RECIENTES = 3             # resultados de herramienta que se dejan enteros
UMBRAL_RECORTE = 0.5      # a partir de esta fracción del contexto se recortan salidas viejas: un modelo
                          # pequeño razona peor con el contexto lleno aunque aún quepa
TURNOS_FINALES = 4        # grupos asistente+herramientas que nunca se resumen
PRIMERAS, ULTIMAS = 8, 24  # líneas del resumen que se conservan
RESUMEN = "## Resumen de los turnos anteriores (recortados para ahorrar contexto)"
STUB = "[resultado antiguo recortado para ahorrar contexto: {lineas} líneas] "


def estimate(obj: Any) -> int:
    """Tokens aproximados de un mensaje, una lista de mensajes o un esquema de herramientas."""
    if obj is None:
        return 0
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _first_line(text: str, n: int = 160) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:n]
    return ""


def _groups(messages: list[dict[str, Any]], start: int) -> list[tuple[int, int]]:
    """Grupos [i, j) desde `start`: un mensaje de asistente y los resultados de herramienta que le siguen
    (o un mensaje de usuario suelto). Así nunca se separa una llamada de su resultado."""
    out, i = [], start
    while i < len(messages):
        j = i + 1
        if messages[i].get("role") == "assistant":
            while j < len(messages) and messages[j].get("role") == "tool":
                j += 1
        out.append((i, j))
        i = j
    return out


def _summary(messages: list[dict[str, Any]]) -> str:
    names: dict[str, str] = {}
    lines = []
    for m in messages:
        role = m.get("role")
        if role == "assistant":
            if (m.get("content") or "").strip():
                lines.append(f"- Pensé: {_first_line(m['content'], 120)}")
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                names[tc.get("id", "")] = f"{fn.get('name', '?')}({str(fn.get('arguments', ''))[:120]})"
        elif role == "tool":
            call = names.get(m.get("tool_call_id", ""), "herramienta")
            text = m.get("content") or ""
            if text.startswith("[resultado antiguo"):
                text = text.split("] ", 1)[-1]
            lines.append(f"- {call} -> {_first_line(text, 120)}")
        elif role == "user":
            text = m.get("content") or ""
            if text.startswith(RESUMEN):  # resumen de un recorte anterior: se conserva tal cual
                lines.extend(l for l in text.splitlines()[1:] if l.startswith("- "))
            else:
                lines.append(f"- Usuario: {_first_line(text, 200)}")
    if len(lines) > PRIMERAS + ULTIMAS:  # el principio (cómo empezó) y lo último (dónde está)
        lines = lines[:PRIMERAS] + [f"- (... {len(lines) - PRIMERAS - ULTIMAS} acciones omitidas ...)"] + lines[-ULTIMAS:]
    return (RESUMEN + "\n"
            + "\n".join(lines)
            + "\nSigue desde aquí. Si necesitas el contenido exacto de un archivo, vuelve a leerlo.")


class Ventana:
    def __init__(self, contexto_tokens: int, max_salida: int):
        self.contexto = contexto_tokens
        self.max_salida = max_salida
        self.recortes = 0     # cuántas veces se recortó (para auditoría)
        self.resumenes = 0

    def presupuesto(self, tools: list[dict[str, Any]] | None) -> int:
        """Tokens que puede ocupar el historial dejando sitio para una salida razonable."""
        salida = min(self.max_salida, max(MIN_SALIDA, self.contexto // 4))
        return self.contexto - salida - estimate(tools) - MARGEN

    def max_tokens(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> int:
        """Tokens de salida a pedir: lo del perfil, sin pasarse de lo que queda libre en el contexto."""
        libre = self.contexto - estimate(messages) - estimate(tools) - MARGEN
        return max(MIN_SALIDA, min(self.max_salida, libre))

    def ajustar(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Devuelve el historial recortado para que quepa. No modifica la lista original."""
        budget = self.presupuesto(tools)
        soft = min(budget, int(self.contexto * UMBRAL_RECORTE))
        if estimate(messages) <= soft:
            return messages
        msgs = [dict(m) for m in messages]

        # 1) Salidas de herramientas antiguas a una línea.
        tool_idx = [i for i, m in enumerate(msgs) if m.get("role") == "tool"]
        for i in tool_idx[:-RECIENTES] if len(tool_idx) > RECIENTES else []:
            text = msgs[i].get("content") or ""
            if text.startswith("[resultado antiguo"):
                continue
            stub = STUB.format(lineas=text.count("\n") + 1) + _first_line(text)
            if len(stub) < len(text):
                msgs[i]["content"] = stub
                self.recortes += 1
        if estimate(msgs) <= budget:
            return msgs

        # 2) Resumen de los turnos del medio. Cabeza: system + primer mensaje de usuario.
        head = 2 if len(msgs) > 1 and msgs[1].get("role") == "user" else 1
        groups = _groups(msgs, head)
        keep = TURNOS_FINALES
        while keep >= 1:
            tail_start = groups[-keep][0] if len(groups) > keep else None
            if tail_start is None:
                keep -= 1
                continue
            middle = msgs[head:tail_start]
            summary = {"role": "user", "content": _summary(middle)}
            candidate = msgs[:head] + [summary] + msgs[tail_start:]
            if estimate(candidate) <= budget or keep == 1:
                self.resumenes += 1
                return candidate
            keep -= 1
        return msgs
