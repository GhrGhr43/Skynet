"""RPC oficial de Pi, herramientas originales y controles externos de Skynet."""
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

from skynet.agent import Agent, AgentOutcome, summarize_args

MAX_RECORD = 32 * 1024 * 1024



def installation(home: Path) -> tuple[str, Path, Path]:
    node = shutil.which("node")
    base = home / "herramientas" / "pi"
    cli = base / "node_modules" / "@earendil-works" / "pi-coding-agent" / "dist" / "cli.js"
    if not node or not cli.is_file():
        raise RuntimeError("Pi no está instalado. Ejecuta herramientas/pi/instalar.ps1.")
    return node, cli, base / "puente.ts"


def configure(home: Path, profile: Any, vision: bool = False) -> Path:
    """Solo el endpoint elegido; no descubre proveedores ni claves de otras instalaciones."""
    url = urlparse(profile.api_base or "")
    if profile.agente or (profile.privado and url.hostname not in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("Usa un perfil de modelo compatible; un perfil privado necesita un endpoint local.")
    agent_dir = home / "data" / "pi" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    model = {
        "id": profile.litellm.split("/", 1)[-1], "name": profile.nombre,
        "reasoning": profile.reasoning_effort is not None, "input": ["text", "image"] if vision else ["text"],
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
                          "defaultThinkingLevel": profile.reasoning_effort or "off"},
    }
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    if profile.contexto_tokens < 36000:
        # Los valores originales reservan 16K: una ventana menor necesita una reserva proporcional.
        files["settings.json"]["compaction"] = {"reserveTokens": min(profile.max_tokens, profile.contexto_tokens // 4),
                                                 "keepRecentTokens": profile.contexto_tokens // 3}
        model["maxTokens"] = min(profile.max_tokens, profile.contexto_tokens // 2)
    if git_bash.is_file():
        files["settings.json"]["shellPath"] = str(git_bash)
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
    """Pi lleva razonamiento, herramientas, historial y compactación sin un segundo bucle."""

    async def run(self, system, user_content, caps, max_turns=30, history=None) -> AgentOutcome:
        profile = self.router.choose(caps).profile
        home = self.router.settings.home
        node, cli, extension = installation(home)
        agent_dir = configure(home, profile, vision=self.gate.vision if self.gate else False)
        out = AgentOutcome(status="error", final_text="", model=profile.litellm)
        token = uuid.uuid4().hex + uuid.uuid4().hex
        connections: set[asyncio.Task] = set()
        lock = asyncio.Lock()
        from skynet_tools.personalizacion import Personalizacion
        options = getattr(self, "personalizacion", None) or Personalizacion(home)
        memory_tool = {"name": "memoria", "description": "Solicita guardar una sola entrada de memoria; Daniel debe aprobarla antes de usarse.",
            "parameters": {"type": "object", "properties": {"texto": {"type": "string"},
                "destino": {"type": "string", "enum": ["usuario", "entorno"]}}, "required": ["texto"]}}
        manifest = {"tools": [memory_tool] if options.data["memoria_activa"] else []}


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
                        if body.get("name") != "memoria" or not options.data["memoria_activa"]:
                            raise ValueError("Herramienta no disponible")
                        entry = options.proponer_memoria(body["args"].get("texto"), body["args"].get("destino", "usuario"))
                        answer = await self.gate.asker("memoria", __import__("skynet.gate", fromlist=["Level"]).Level.WRITE,
                            {"texto": entry["texto"]}, "Aprobar SOLO esta entrada de memoria: " + entry["texto"]) if self.gate and self.gate.asker else "n"
                        approved = answer.lower() in ("s", "si", "sí")
                        if approved:
                            options.revisar_memoria(entry["id"], True)
                        self.audit.log("memoria", decision="aprobada" if approved else "pendiente", detail={"id": entry["id"]})
                        data = {"content": [{"type": "text", "text": "Entrada aprobada." if approved else "Pendiente de aprobación; no se utiliza."}], "details": {}}
                elif method == "POST" and path == "/authorize":
                    n = int(headers.get("content-length", "0"))
                    if not 0 < n <= MAX_RECORD:
                        raise ValueError("Tamaño de petición inválido")
                    body = json.loads(await asyncio.wait_for(reader.readexactly(n), 15))
                    name, args = body["name"], body["args"]
                    if not isinstance(args, dict):
                        raise ValueError("Argumentos inválidos")
                    if name == "memoria":
                        data = {"allowed": bool(options.data["memoria_activa"])}
                    else:
                        native = {"read": "read_file", "write": "write_file", "edit": "edit_file", "bash": "run_command"}
                        if name in native:
                            if name not in options.data["herramientas"]:
                                data = {"allowed": False, "reason": "Herramienta desactivada"}
                            else:
                                key = "workspace." + native[name] if self.gate and self.gate.repo else "sistema." + native[name]
                                checked = dict(args)
                                if not (self.gate and self.gate.repo) and isinstance(args.get("path"), str):
                                    checked["path"] = str((home / "data" / "chat" / args["path"]).resolve())
                                gr = await self.gate.check(key, checked, name) if self.gate else None
                                data = {"allowed": bool(gr and gr.allowed), "reason": gr.reason if gr else "Sin permisos"}
                        elif name == "tool_search":
                            data = {"allowed": bool(options.data["mcp_activo"])}
                        elif name in ("list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"):
                            server_name = args.get("server")
                            enabled = options.data["mcp_activo"] and (not server_name or options.data["mcp"].get(server_name, {}).get("enabled", False))
                            gr = await self.gate.check("mcp." + name, args, name) if enabled and self.gate else None
                            data = {"allowed": bool(gr and gr.allowed), "reason": gr.reason if gr else "MCP desactivado"}
                        elif name.startswith("mcp__"):
                            parts = name.split("__", 2)
                            server_name = next((n for n in options.data["mcp"] if n.replace("-", "_") == parts[1]), "")
                            enabled = options.data["mcp_activo"] and options.data["mcp"].get(server_name, {}).get("enabled", False)
                            gr = await self.gate.check(server_name + "." + parts[2], args, name) if enabled and self.gate else None
                            data = {"allowed": bool(gr and gr.allowed), "reason": gr.reason if gr else "MCP desactivado"}
                        else:
                            data = {"allowed": False, "reason": "Herramienta desconocida"}
                    self.audit.log("permission", tool=name,
                        decision="permitido" if data.get("allowed") else "denegado",
                        detail={"motivo": data.get("reason", "")})

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
        sid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{home}:{getattr(self, 'session_key', self.audit.task_id)}"))
        session_dir = home / "data" / "pi" / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PI_CODING_AGENT_DIR=str(agent_dir), PI_OFFLINE="1",
                   SKYNET_PI_BRIDGE=f"http://127.0.0.1:{port}", SKYNET_PI_TOKEN=token)
        repo = self.gate.repo.ruta if self.gate and self.gate.repo else None
        mcp_config = options.mcp_config(repo, self.gate.mode if self.gate else "repo", bool(self.gate and self.gate.internet))
        (agent_dir / "mcp.json").write_text(json.dumps(mcp_config, ensure_ascii=False, indent=2), encoding="utf-8")
        selected = options.data["harnesses"][options.data["harness"]]
        command = [node, str(cli)] if options.data["harness"] == "pi" else [selected["comando"], *selected.get("args", [])]
        argv = [*command, "--mode", "rpc", "--offline", "--no-approve", "--no-extensions", "--extension", str(extension),
                "--no-prompt-templates", "--no-themes", "--no-skills", "--provider", "skynet-local",
                "--model", profile.litellm.split("/", 1)[-1], "--thinking", caps.effort or profile.reasoning_effort or "off",
                "--session-dir", str(session_dir), "--session-id", sid]
        tools = list(options.data["herramientas"])
        if repo is None and self.gate and self.gate.mode == "repo":
            tools = []  # chat sin proyecto: el modelo no recibe herramientas que no puede utilizar
        elif repo is None and self.gate and self.gate.mode == "lectura":
            tools = [t for t in tools if t == "read"]
        if options.data["memoria_activa"]:
            tools.append("memoria")
        if mcp_config["mcpServers"]:
            tools += ["tool_search", "mcp__*", "list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"]
        if tools:
            argv += ["--tools", ",".join(tools)]
        else:
            argv += ["--no-builtin-tools"]
        if repo is None:
            argv += ["--no-context-files"]  # el chat no hereda las instrucciones del código de Skynet
        if not options.data["mcp_activo"]:
            argv += ["--no-mcp"]
        else:
            argv += ["--extension", "builtin:mcp", "--extension", "builtin:tool-search"]
        approved_memory = options.memoria_aprobada()
        for skill in options.data["skills"]:
            argv += ["--skill", skill]
        if approved_memory:
            argv += ["--append-system-prompt", "Memoria aprobada por Daniel:\n" + approved_memory]

        proc = None
        stderr_task = None
        llm_started = None
        last_error = ""
        self.on_event("route", {"model": profile.litellm, "perfil": profile.nombre, "reason": "Harness " + options.data["harness"]})
        self.audit.log("route", model=profile.litellm, detail={"harness": options.data["harness"], "session": sid})
        try:
            cwd = self.gate.repo.ruta if self.gate and self.gate.repo else home / "data" / "chat"
            cwd.mkdir(parents=True, exist_ok=True)
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
            await send({"id": "work", "type": "prompt", "message": text, **({"images": images} if images else {})})
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), profile.timeout_seg + 30)
                if not line:
                    raise RuntimeError("Pi se cerró antes de terminar: " + await stderr_task)
                event = json.loads(line)
                kind = event.get("type")
                if kind == "extension_ui_request" and event.get("method") == "notify":
                    self.on_event("say", {"text": event.get("message", "")})
                    self.audit.log("harness", decision=event.get("notifyType"), detail={"mensaje": event.get("message", "")})
                if kind == "response" and event.get("success") is False:
                    raise RuntimeError(event.get("error", "Pi rechazó el comando"))
                if kind == "message_start" and event.get("message", {}).get("role") == "assistant":
                    llm_started = time.monotonic()
                    out.turns += 1
                    self.on_event("thinking", {"turn": out.turns})
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
                if kind == "tool_execution_start":
                    args_summary = summarize_args(event.get("args") or {})
                    self.on_event("tool", {"key": event.get("toolName", ""), "args": args_summary})
                    self.audit.log("tool", tool=event.get("toolName"), decision="iniciada", detail={"args_resumen": args_summary})
                    out.tool_calls += 1
                if kind == "tool_execution_end":
                    ok = not event.get("isError", False)
                    result_text = "\n".join(b.get("text", "") for b in event.get("result", {}).get("content", []) if b.get("type") == "text")
                    first = result_text.splitlines()[0][:200] if result_text else ("Hecho" if ok else "Error")
                    self.on_event("tool_result", {"key": event.get("toolName", ""), "ok": ok, "first_line": first})
                    self.audit.log("tool_result", tool=event.get("toolName"), decision="correcta" if ok else "error", detail={"resumen": first})
                if kind == "agent_settled":
                    break
            out.status = "error" if last_error else "completado"
            out.error = last_error or None
            if last_error:
                out.final_text = last_error
            out.claims_done = out.status == "completado"
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
        return out
