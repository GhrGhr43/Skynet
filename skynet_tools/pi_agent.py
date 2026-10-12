"""Adaptador al RPC oficial de Pi; reutiliza las herramientas y permisos de Skynet."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid
from typing import Any
from urllib.parse import urlparse

from skynet.agent import Agent, AgentOutcome, DONE_MARK

MAX_RECORD = 32 * 1024 * 1024
GUIDE = """Trabajas para Daniel en Windows. Responde en español. Las herramientas disponibles
son las de Skynet y pasan por sus permisos. Usa workspace__run_command con comandos de PowerShell.
Construye aplicaciones por pequeñas ediciones de unos 4000 caracteres; no intentes escribir un
archivo grande en una llamada. Comprueba con el verificador y, para HTML, con navegador__comprobar_html
si está disponible. Conserva el plan en .skynet/tarea-N/PLAN.md y completa los requisitos pendientes.
No declares terminado lo que no hayas comprobado."""


def installation(home: Path) -> tuple[str, Path, Path]:
    node = shutil.which("node")
    base = home / "herramientas" / "pi"
    cli = base / "node_modules" / "@earendil-works" / "pi-coding-agent" / "dist" / "cli.js"
    if not node or not cli.is_file():
        raise RuntimeError("Pi no está instalado. Ejecuta herramientas/pi/instalar.ps1.")
    return node, cli, base / "puente.ts"


def configure(home: Path, profile: Any, vision: bool = False) -> Path:
    """Solo el endpoint local elegido por Skynet; nunca descubre claves o proveedores del usuario."""
    url = urlparse(profile.api_base or "")
    if profile.agente or not profile.privado or url.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Esta integración de Pi necesita el perfil local de Skynet.")
    agent_dir = home / "data" / "pi" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    model = {
        "id": profile.litellm.split("/", 1)[-1], "name": "Modelo local de Skynet",
        "reasoning": True, "input": ["text", "image"] if vision else ["text"],
        "contextWindow": profile.contexto_tokens, "maxTokens": profile.max_tokens,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "compat": {"supportsStore": False, "supportsDeveloperRole": False,
                   "supportsReasoningEffort": True, "maxTokensField": "max_tokens"},
        "samplingParams": {k: v for k, v in {
            "temperature": profile.temperatura, "top_p": profile.top_p,
            "top_k": profile.top_k, "min_p": profile.min_p,
            "presence_penalty": profile.presence_penalty,
        }.items() if v is not None},
    }
    files = {
        "models.json": {"providers": {"skynet-local": {
            "baseUrl": profile.api_base, "api": "openai-completions",
            "apiKey": profile.resolved_api_key() or "local", "models": [model],
        }}},
        "settings.json": {"defaultProvider": "skynet-local", "defaultModel": model["id"],
                          "defaultThinkingLevel": profile.reasoning_effort or "medium",
                          "compaction": {"enabled": True, "reserveTokens": profile.max_tokens,
                                         "keepRecentTokens": min(12000, profile.contexto_tokens // 4)},
                          "cacheWarming": {"enabled": False}},
    }
    for name, data in files.items():
        (agent_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return agent_dir


def content_blocks(text: str, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for im in images[:4]:
        url = im.get("image_url", {}).get("url", "")
        match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,(.+)", url, re.S)
        if match:
            blocks.append({"type": "image", "mimeType": match[1], "data": match[2]})
    return blocks


class PiAgent(Agent):
    """El RPC lleva el razonamiento; Agent se reutiliza solo para ejecutar herramientas."""

    async def run(self, system, user_content, caps, max_turns=30, history=None) -> AgentOutcome:
        profile = self.router.choose(caps).profile
        home = self.router.settings.home
        node, cli, extension = installation(home)
        agent_dir = configure(home, profile, vision=self.gate.vision if self.gate else False)
        out = AgentOutcome(status="error", final_text="", model=profile.litellm)
        seen: dict[str, int] = {}
        touched: set[str] = set()
        self._repo_revision = 0
        token = uuid.uuid4().hex + uuid.uuid4().hex
        connections: set[asyncio.Task] = set()
        lock = asyncio.Lock()
        schemas = (self.hub.openai_tools() if self.hub else []) + [v.esquema for v in self.internas.values()]
        manifest = {"tools": [s["function"] for s in schemas]}

        async def http(reader, writer):
            current = asyncio.current_task()
            connections.add(current)
            try:
                header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
                lines = header.decode("latin-1").split("\r\n")
                method, path, _ = lines[0].split(" ")
                headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
                headers = {k.lower(): v.strip() for k, v in headers.items()}
                status, data = "200 OK", None
                if not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + token) or "origin" in headers:
                    status, data = "403 Forbidden", {"error": "No autorizado"}
                elif method == "GET" and path == "/manifest":
                    data = manifest
                elif method == "POST" and path == "/tool":
                    n = int(headers.get("content-length", "0"))
                    if not 0 < n <= MAX_RECORD:
                        raise ValueError("Tamaño de petición inválido")
                    body = json.loads(await asyncio.wait_for(reader.readexactly(n), 15))
                    if not isinstance(body.get("args"), dict):
                        raise ValueError("Argumentos inválidos")
                    async with lock:
                        self._images.clear()
                        text = await self._run_tool({"function": {"name": body["name"],
                            "arguments": json.dumps(body["args"], ensure_ascii=False)}}, seen, touched, out)
                        data = {"content": content_blocks(text, self._images), "details": {}}
                        self._images.clear()
                else:
                    status, data = "404 Not Found", {"error": "Ruta desconocida"}
                payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
                writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode() + payload)
                await writer.drain()
            except (ValueError, KeyError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
                writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                connections.discard(current)
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(http, "127.0.0.1", 0, limit=MAX_RECORD)
        port = server.sockets[0].getsockname()[1]
        sid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{home}:{self.audit.task_id}"))
        session_dir = home / "data" / "pi" / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PI_CODING_AGENT_DIR=str(agent_dir), PI_OFFLINE="1",
                   SKYNET_PI_BRIDGE=f"http://127.0.0.1:{port}", SKYNET_PI_TOKEN=token)
        argv = [node, str(cli), "--mode", "rpc", "--offline", "--no-builtin-tools",
                "--no-extensions", "--extension", str(extension), "--no-mcp", "--no-skills",
                "--no-prompt-templates", "--no-context-files", "--no-approve", "--no-themes",
                "--provider", "skynet-local", "--model", profile.litellm.split("/", 1)[-1],
                "--thinking", caps.effort or profile.reasoning_effort or "medium",
                "--session-dir", str(session_dir), "--session-id", sid,
                "--append-system-prompt", GUIDE]
        proc = None
        stderr_task = None
        llm_started = None
        last_error = ""
        limit = False
        pending_finishes = 0
        self.on_event("route", {"model": profile.litellm, "perfil": profile.nombre, "reason": "Pi oficial · modelo local"})
        self.audit.log("route", model=profile.litellm, detail={"harness": "pi", "session": sid})
        try:
            cwd = self.gate.repo.ruta if self.gate and self.gate.repo else home
            proc = await asyncio.create_subprocess_exec(*argv, cwd=str(cwd), env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=MAX_RECORD)

            async def drain_stderr():
                chunks = []
                while data := await proc.stderr.read(4096):
                    chunks.append(data.decode("utf-8", "replace"))
                    chunks[:] = chunks[-8:]
                return "".join(chunks)[-4000:]

            stderr_task = asyncio.create_task(drain_stderr())

            async def send(data):
                proc.stdin.write(json.dumps(data, ensure_ascii=False).encode("utf-8") + b"\n")
                await proc.stdin.drain()

            if isinstance(user_content, list):
                text = "\n".join(b.get("text", "") for b in user_content if b.get("type") == "text")
                images = content_blocks("", [b for b in user_content if b.get("type") == "image_url"])[1:]
            else:
                text, images = user_content, []
            if history:
                text = "\n\n".join(f"Usuario: {q}\nSkynet: {a}" for q, a in history) + "\n\n" + text
            await send({"id": "work", "type": "prompt", "message": text, **({"images": images} if images else {})})
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), profile.timeout_seg + 30)
                if not line:
                    raise RuntimeError("Pi se cerró antes de terminar: " + await stderr_task)
                event = json.loads(line)
                kind = event.get("type")
                if kind == "response" and event.get("success") is False:
                    raise RuntimeError(event.get("error", "Pi rechazó el comando"))
                if kind == "message_start" and event.get("message", {}).get("role") == "assistant":
                    llm_started = time.monotonic()
                    out.turns += 1
                    self.on_event("thinking", {"turn": out.turns})
                    if out.turns > max_turns:
                        limit = True
                        await send({"id": "stop", "type": "abort"})
                if kind == "message_end" and event.get("message", {}).get("role") == "assistant":
                    msg = event["message"]
                    usage = msg.get("usage", {})
                    tin = sum(int(usage.get(k, 0) or 0) for k in ("input", "cacheRead", "cacheWrite"))
                    tout = int(usage.get("output", 0) or 0)
                    seconds = max(0, time.monotonic() - llm_started) if llm_started is not None else 0
                    llm_started = None
                    out.segundos += seconds
                    out.tokens_in += tin
                    out.tokens_out += tout
                    self.on_event("usage", {"tokens_in": tin, "tokens_out": tout, "model": profile.litellm,
                                            "segundos": round(seconds, 3)})
                    self.audit.log("llm", model=profile.litellm, tokens_in=tin, tokens_out=tout,
                        cost_eur=0, detail={"harness": "pi", "fin": msg.get("stopReason")})
                    if msg.get("stopReason") in ("error", "aborted"):
                        last_error = msg.get("errorMessage") or "Pi interrumpió la respuesta."
                    else:
                        last_error = ""
                    out.final_text = "\n".join(b.get("text", "") for b in msg.get("content", []) if b.get("type") == "text")
                    if any(b.get("type") == "toolCall" for b in msg.get("content", [])) and out.final_text:
                        self.on_event("say", {"text": out.final_text})
                if kind == "agent_settled":
                    if not limit and not last_error and self.exigir_plan_completo and self.gate and self.gate.repo:
                        root = self.gate.repo.ruta.resolve()
                        plan = root / ".skynet" / f"tarea-{self.audit.task_id}" / "PLAN.md"
                        pending = ""
                        if plan.resolve().is_relative_to(root) and plan.is_file():
                            pending = "\n".join(line for line in plan.read_text(encoding="utf-8").splitlines()
                                                if re.match(r"\s*[-*]\s+\[ \]", line))[:2000]
                        if pending:
                            pending_finishes += 1
                            if pending_finishes < 3 and out.turns < max_turns:
                                await send({"id": f"pending-{pending_finishes}", "type": "prompt",
                                            "message": "El plan sigue teniendo pendientes. Implementa y comprueba el siguiente; "
                                                       "actualiza el plan solo tras realizarlo.\n" + pending})
                                continue
                            limit = True
                            out.final_text = "El plan sigue teniendo requisitos pendientes:\n" + pending
                    break
            out.status = "limite_turnos" if limit else "error" if last_error else "completado"
            out.error = last_error or None
            if limit:
                out.final_text = "Pi alcanzó el límite de turnos. Los avances se conservan."
            elif last_error:
                out.final_text = last_error
            out.claims_done = out.status == "completado" and DONE_MARK in out.final_text
        except (RuntimeError, OSError, ValueError, TimeoutError) as e:
            out.error = out.final_text = str(e)
        finally:
            if proc:
                if proc.returncode is None:
                    proc.stdin.close()
                    try:
                        await asyncio.wait_for(proc.wait(), 5)
                    except TimeoutError:
                        proc.kill()
                        await proc.wait()
                if stderr_task:
                    await stderr_task
            server.close()
            await server.wait_closed()
            for task in list(connections):
                task.cancel()
            await asyncio.gather(*connections, return_exceptions=True)
        out.files_touched = sorted(touched)
        return out
