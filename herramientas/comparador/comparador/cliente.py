"""Cliente mínimo para servidores con API OpenAI (LM Studio, llama-server, Ollama, OmniRoute...).

Solo librería estándar: funciona en el Python de Windows sin instalar nada.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class ErrorModelo(Exception):
    pass


@dataclass
class Respuesta:
    texto: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    segundos: float = 0.0
    primer_token: float | None = None   # segundos hasta el primer token (solo en streaming)

    @property
    def tok_s(self) -> float:
        gen = self.segundos - (self.primer_token or 0)
        return self.tokens_out / gen if gen > 0 and self.tokens_out else 0.0


@dataclass
class Modelo:
    nombre: str                 # id que espera el servidor
    url: str                    # base, p. ej. http://127.0.0.1:1234/v1
    api_key: str = "local"
    etiqueta: str = ""          # cómo se muestra en el informe
    vision: bool | None = None  # None = se averigua con una prueba
    extra: dict[str, Any] = field(default_factory=dict)  # temperature, top_p, reasoning_effort...
    gguf: Any = None            # motor.GGUF si el comparador arranca el modelo él mismo

    def __post_init__(self) -> None:
        self.etiqueta = self.etiqueta or self.nombre
        if self.api_key.startswith("env:"):
            self.api_key = os.environ.get(self.api_key[4:], "")

    def _post(self, ruta: str, cuerpo: dict[str, Any], timeout: float) -> Any:
        req = urllib.request.Request(
            self.url.rstrip("/") + ruta, data=json.dumps(cuerpo).encode(), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            raise ErrorModelo(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ErrorModelo(f"sin conexión con {self.url}: {e}") from e

    def chat(self, mensajes: list[dict[str, Any]], herramientas: list[dict] | None = None,
             max_tokens: int = 8192, timeout: float = 600, stream: bool = False, **kw: Any) -> Respuesta:
        cuerpo: dict[str, Any] = {"model": self.nombre, "messages": mensajes, "max_tokens": max_tokens,
                                  **self.extra, **kw}
        if herramientas:
            cuerpo["tools"] = herramientas
        t0 = time.monotonic()
        if stream and not herramientas:
            return self._stream(cuerpo, t0, timeout)
        with self._post("/chat/completions", cuerpo, timeout) as r:
            d = json.loads(r.read())
        msg = d["choices"][0]["message"]
        u = d.get("usage") or {}
        return Respuesta(texto=_limpia(msg.get("content") or ""), tool_calls=msg.get("tool_calls") or [],
                         tokens_in=u.get("prompt_tokens", 0), tokens_out=u.get("completion_tokens", 0),
                         segundos=time.monotonic() - t0)

    def _stream(self, cuerpo: dict[str, Any], t0: float, timeout: float) -> Respuesta:
        cuerpo = {**cuerpo, "stream": True, "stream_options": {"include_usage": True}}
        partes, primero, usage, trozos = [], None, {}, 0
        with self._post("/chat/completions", cuerpo, timeout) as r:
            for linea in r:
                linea = linea.decode(errors="replace").strip()
                if not linea.startswith("data:") or linea == "data: [DONE]":
                    continue
                d = json.loads(linea[5:])
                usage = d.get("usage") or usage
                for c in d.get("choices", []):
                    delta = c.get("delta", {})
                    t = (delta.get("content") or "") + (delta.get("reasoning_content") or "")
                    if t:
                        primero = primero or time.monotonic() - t0
                        trozos += 1
                        if delta.get("content"):
                            partes.append(delta["content"])
        return Respuesta(texto=_limpia("".join(partes)), tokens_in=usage.get("prompt_tokens", 0),
                         tokens_out=usage.get("completion_tokens", trozos), segundos=time.monotonic() - t0,
                         primer_token=primero)


def _limpia(texto: str) -> str:
    """Quita el razonamiento <think>...</think> que algunos servidores dejan en el contenido."""
    import re

    return re.sub(r"<think>.*?</think>\s*", "", texto, flags=re.S).strip()


def modelos_del_servidor(url: str, api_key: str = "local", timeout: float = 5) -> list[str]:
    req = urllib.request.Request(url.rstrip("/") + "/models", headers={"Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return [m["id"] for m in json.loads(r.read()).get("data", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return []
