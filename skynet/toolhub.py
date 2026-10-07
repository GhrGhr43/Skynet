"""Cliente MCP del Core: arranca los servidores MCP de una tarea y expone sus herramientas.

Las herramientas se presentan al modelo con nombre `servidor__herramienta` (formato válido
para function calling) y se identifican en permisos y auditoría como `servidor.herramienta`.
Añadir una herramienta nueva = añadir un servidor MCP en config/skynet.toml; el Core no cambia.
"""
from __future__ import annotations

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import ServerSpec

SEP = "__"


@dataclass
class ToolSpec:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def llm_name(self) -> str:
        return f"{self.server}{SEP}{self.name}"

    @property
    def key(self) -> str:
        return f"{self.server}.{self.name}"

    def openai_schema(self) -> dict[str, Any]:
        schema = dict(self.input_schema or {"type": "object", "properties": {}})
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.llm_name, "description": self.description[:1024], "parameters": schema},
        }


@dataclass
class ToolResult:
    ok: bool
    text: str


class ToolHub:
    """Context manager asíncrono: `async with ToolHub(specs, log_dir) as hub: ...`."""

    def __init__(self, specs: list[ServerSpec], log_dir: Path | None = None):
        self.specs = specs
        self.log_dir = log_dir
        self.tools: dict[str, ToolSpec] = {}  # por llm_name
        self._sessions: dict[str, ClientSession] = {}
        self._stack: AsyncExitStack | None = None
        self._logs: list[TextIO] = []

    async def __aenter__(self) -> "ToolHub":
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        try:
            for spec in self.specs:
                await self._start(spec)
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._stack is not None:
            try:
                await self._stack.aclose()
            finally:
                self._stack = None
                for f in self._logs:
                    f.close()
                self._logs.clear()

    async def _start(self, spec: ServerSpec) -> None:
        assert self._stack is not None
        errlog: TextIO
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            errlog = open(self.log_dir / f"mcp-{spec.nombre}.log", "a", encoding="utf-8")
            self._logs.append(errlog)
        else:
            import sys
            errlog = sys.stderr
        params = StdioServerParameters(command=spec.comando, args=spec.args, env=spec.env or None)
        read, write = await self._stack.enter_async_context(stdio_client(params, errlog=errlog))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[spec.nombre] = session
        listed = await session.list_tools()
        for t in listed.tools:
            schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
            ts = ToolSpec(spec.nombre, t.name, t.description or "", dict(schema))
            self.tools[ts.llm_name] = ts

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.openai_schema() for t in self.tools.values()]

    def resolve(self, llm_name: str) -> ToolSpec | None:
        return self.tools.get(llm_name)

    async def call(self, llm_name: str, args: dict[str, Any], timeout: float | None = None) -> ToolResult:
        spec = self.tools.get(llm_name)
        if spec is None:
            return ToolResult(False, f"La herramienta '{llm_name}' no existe")
        session = self._sessions[spec.server]
        try:
            res = await session.call_tool(spec.name, args, read_timeout_seconds=timeout)
        except Exception as e:  # el servidor murió o no respondió a tiempo
            return ToolResult(False, f"Error llamando a {spec.key}: {type(e).__name__}: {e}")
        parts = []
        for c in res.content or []:
            text = getattr(c, "text", None)
            parts.append(text if text is not None else json.dumps(c.model_dump(), ensure_ascii=False)[:2000])
        is_error = bool(getattr(res, "is_error", None) or getattr(res, "isError", False))
        return ToolResult(not is_error, "\n".join(parts))
