"""Servidor de la interfaz web: el mismo Coordinator que el chat de terminal, servido por HTTP.

- GET  /                 la página (static/index.html)
- GET  /api/stream       eventos en vivo (Server-Sent Events): respuestas, herramientas, preguntas...
- GET  /api/estado       foto del estado: repo, modelo, privacidad, modelos, repos, preguntas abiertas
- POST /api/mensaje      un mensaje del chat (igual que escribir en la terminal)
- POST /api/responder    respuesta a una confirmación (permiso o «¿lanzar?»)
- ...                    tareas, registro, diagnóstico y ajustes (ver `routes`)

Solo escucha en 127.0.0.1. Además comprueba Host y Origin: sin eso, cualquier web abierta en el
navegador podría mandar órdenes a Skynet (DNS rebinding / CSRF). Desde otro dispositivo (el móvil) solo se
llega por Tailscale Serve y con la llave de un dispositivo emparejado: ver acceso.py. Sin dependencias nuevas:
Starlette y uvicorn ya vienen con el SDK de MCP; SSE en vez de WebSocket por lo mismo.
"""
from __future__ import annotations

import asyncio
import io
import itertools
import json
import os
import re
import subprocess
import threading
import time
import webbrowser
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import __version__, modos, modelos_locales, propuestas, skills
from ..agent import summarize_args
from ..audit import describe_event
from ..config import ConfigError, add_repo
from ..coordinator import HELP, Coordinator
from ..gate import SIEMPRE_TAG, Level
from ..router import Capabilities
from ..runtime import Runtime
from ..sesiones import Sesiones
from ..store import EN_CURSO, ESPERANDO_PERMISO, FALLIDA, HECHA, PAUSADA, Task
from .acceso import (AccesoError, Cliente, ConfigAcceso, Dispositivos, EstadoAcceso, enlace_emparejar,
                     ip_cliente, ip_de_tailscale)

STATIC = Path(__file__).resolve().parent / "static"


def _build() -> dict[str, Any]:
    """Commit y carpeta de la copia que se está ejecutando (para saber si la versión probada es la última)."""
    root = STATIC.parents[2]
    info: dict[str, Any] = {"carpeta": str(root), "commit": None, "fecha": None}
    try:
        out = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h %cs"], capture_output=True,
                             text=True, timeout=3).stdout.split()
        if len(out) == 2:
            info["commit"], info["fecha"] = out
    except (OSError, subprocess.SubprocessError):
        pass  # sin git: se muestra solo la versión
    return info


BUILD = _build()
KEEPALIVE_SEG = 15
REPLAY = 300  # mensajes de la conversación que recupera una pestaña nueva o recargada


# --- bus de eventos --------------------------------------------------------
class Bus:
    """Reparte cada evento a todas las pestañas abiertas y guarda la conversación reciente."""

    REPLAYABLE = {"usuario", "info", "respuesta", "evento", "tabla", "error", "diagnostico"}

    def __init__(self, start: int = 1, sink: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.history: deque[dict[str, Any]] = deque(maxlen=REPLAY)
        self._seq = itertools.count(start)
        self.sink = sink  # guarda la conversación en la sesión actual (SQLite)

    def publish(self, kind: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        msg = {"seq": next(self._seq), "tipo": kind, **(data or {})}
        if kind in self.REPLAYABLE and not (kind == "evento" and msg.get("kind") in ("thinking", "usage")):
            self.history.append(msg)
            if self.sink:
                try:
                    self.sink(msg)
                except Exception:  # la conversación en pantalla no debe caerse por la base
                    pass
        for q in list(self.subscribers):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:  # pestaña colgada: se la desconecta para no acumular memoria
                self.subscribers.discard(q)
        return msg

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.discard(q)

    def close(self) -> None:
        """Al cerrar el servidor: termina los streams abiertos para que el cierre sea limpio."""
        for q in list(self.subscribers):
            try:
                q.put_nowait({"seq": 0, "tipo": "_fin"})
            except asyncio.QueueFull:
                pass


# --- la "UI" que ve el Coordinator -----------------------------------------
class WebUI:
    """Implementa el protocolo UI del Coordinator publicando en el bus.

    Las confirmaciones quedan abiertas (con id) hasta que alguna pestaña responde; así una
    recarga de la página no pierde la pregunta."""

    def __init__(self, bus: Bus):
        self.bus = bus
        self.pending: dict[str, tuple[dict[str, Any], asyncio.Future[str]]] = {}
        self._ids = itertools.count(1)
        self.on_usage: Callable[[dict[str, Any]], None] | None = None

    def info(self, text: str) -> None:
        self.bus.publish("info", {"texto": text})

    def answer(self, text: str) -> None:
        self.bus.publish("respuesta", {"texto": text or "(sin respuesta)"})

    def event(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "usage" and self.on_usage:
            self.on_usage(data)
        self.bus.publish("evento", {"kind": kind, "datos": data})

    def show(self, renderable: Any) -> None:
        # Tablas de rich (/tareas, /log escritos a mano) pasadas a texto plano.
        from rich.console import Console

        buf = io.StringIO()
        Console(file=buf, width=120, color_system=None, legacy_windows=False).print(renderable)
        self.bus.publish("tabla", {"texto": buf.getvalue()})

    async def _request(self, payload: dict[str, Any]) -> str:
        qid = f"q{next(self._ids)}"
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        payload = {"id": qid, **payload}
        self.pending[qid] = (payload, fut)
        self.bus.publish("pregunta", payload)
        try:
            return await fut
        finally:
            self.pending.pop(qid, None)
            self.bus.publish("pregunta_cerrada", {"id": qid})

    async def ask(self, prompt: str) -> str:
        return await self._request({"clase": "confirmar", "texto": prompt})

    async def ask_permission(self, task_id: int, key: str, level: Level, args: dict[str, Any], reason: str) -> str:
        return await self._request({
            "clase": "permiso", "tarea": task_id, "herramienta": key, "nivel": level.name,
            "args": summarize_args(args), "motivo": reason,
            "todas": level is not Level.DESTRUCTIVE and SIEMPRE_TAG not in reason,
        })

    def resolve(self, qid: str, value: str) -> bool:
        item = self.pending.get(qid)
        if item is None or item[1].done():
            return False
        item[1].set_result(value)
        return True

    def open_questions(self) -> list[dict[str, Any]]:
        return [p for p, _ in self.pending.values()]


class WebCoordinator(Coordinator):
    """El Coordinator de siempre; cambia cómo pregunta (datos estructurados para el diálogo) y que cada
    tarea pertenece a la sesión abierta, cuya conversación reciente se guarda en SQLite."""

    ui: WebUI
    sesiones: Sesiones | None = None
    sesion_id: int | None = None

    def _recent(self) -> str | None:
        if not (self.sesiones and self.sesion_id):
            return super()._recent()
        pares = self.sesiones.recientes(self.sesion_id)
        if not pares:
            return None
        lines = [f"- Pedido: {q[:300]}\n  Respuesta: {a[:500]}" for q, a in pares]
        return "Conversación reciente (por si la petición se refiere a ella):\n" + "\n".join(lines)

    def _pairs(self, n: int = 6) -> list[tuple[str, str]]:
        if not (self.sesiones and self.sesion_id):
            return super()._pairs(n)
        return self.sesiones.recientes(self.sesion_id, n)

    async def _run(self, task: Task, kind: str, extra: str | None,
                   history: list[tuple[str, str]] | None = None) -> Task:
        if self.sesiones and self.sesion_id and not task.is_long:
            self.sesiones.enlazar(self.sesion_id, task.id)
        return await super()._run(task, kind, extra, history=history)

    def _make_asker(self, task: Task):
        async def ask(key: str, level: Level, args: dict[str, Any], reason: str) -> str:
            self.rt.store.update_task(task.id, status=ESPERANDO_PERMISO)
            try:
                return await self.ui.ask_permission(task.id, key, level, args, reason)
            finally:
                self.rt.store.update_task(task.id, status=EN_CURSO)
        return ask

    async def _command(self, text: str) -> bool:
        if text.split()[0].lower() == "/doctor":
            from ..cli import doctor_checks

            self.ui.bus.publish("diagnostico", {"checks": await asyncio.to_thread(doctor_checks, self.rt)})
            return True
        if text.split()[0].lower() in ("/salir", "/exit", "/quit"):
            self.ui.info("La web sigue abierta. Para cerrar Skynet, cierra la ventana donde lanzaste «skynet web».")
            return True
        return await super()._command(text)


def _warm_litellm() -> None:
    try:
        import litellm  # noqa: F401
    except Exception:
        pass


# --- sesión: un único trabajo a la vez, como en la terminal ---------------------
class Busy(Exception):
    pass


class Session:
    def __init__(self, rt: Runtime):
        self.rt = rt
        self.sesiones = Sesiones(rt.store)
        last = self.sesiones.ultima()
        self.sid: int = last["id"] if last else self.sesiones.crear()["id"]
        self.bus = Bus(start=self.sesiones.max_seq() + 1, sink=self._guardar)
        self.ui = WebUI(self.bus)
        self.coord = WebCoordinator(rt, self.ui)
        self.coord.sesiones, self.coord.sesion_id = self.sesiones, self.sid
        self.ctx: dict[str, Any] = {"contexto": last["contexto"] if last else 0, "modelo": last["modelo"] if last else None}
        self.current: asyncio.Task[Any] | None = None
        self.running = False  # no se mira current.done(): en su propio finally aún no ha terminado
        self.label = ""
        self._abandoned: set[asyncio.Task[Any]] = set()
        self.gen = 0  # cada trabajo tiene su número: uno abandonado al detener no pisa el estado del siguiente
        from ..engines import load_engines

        self.engines = load_engines(rt.settings.engines, rt.settings.logs_dir, rt.settings.home)
        # litellm tarda unos segundos en importarse; hecho en el primer mensaje congelaba la web (y Detener).
        threading.Thread(target=_warm_litellm, daemon=True).start()

        self.ui.on_usage = self._usage

    # --- sesiones -----------------------------------------------------------
    def _guardar(self, msg: dict[str, Any]) -> None:
        self.sesiones.guardar(self.sid, msg)

    def _usage(self, d: dict[str, Any]) -> None:
        self.ctx = {"contexto": int(d.get("tokens_in") or 0) + int(d.get("tokens_out") or 0), "modelo": d.get("model")}
        self.sesiones.tocar(self.sid, **self.ctx)
        seg, out = float(d.get("segundos") or 0), int(d.get("tokens_out") or 0)
        if seg > 0 and out > 0:  # velocidad de la última llamada (solo en memoria)
            self.tps = round(out / seg, 1)

    def abrir(self, sid: int) -> None:
        """Cambia de sesión: la conversación de las pestañas se rehace con la de la sesión elegida."""
        if self.busy:
            raise Busy(f"Skynet está trabajando en «{self.label}». Espera o pulsa Detener antes de cambiar de sesión.")
        if not self.sesiones.existe(sid):
            raise KeyError(f"No existe la sesión {sid}")
        if sid != self.sid:
            self.sid = self.coord.sesion_id = sid
            ses = self.sesiones.get(sid)
            self.ctx = {"contexto": ses["contexto"], "modelo": ses["modelo"]}
            self.coord.history.clear()
            self.bus.history.clear()
        self.bus.publish("sesion", {"sesion": self.sesion_info(), "mensajes": self.sesiones.mensajes(sid, REPLAY)})
        self.bus.publish("estado", snapshot(self))

    def nueva(self) -> int:
        """Sesión nueva; si la actual sigue vacía, se reutiliza (como «Nuevo chat» en Claude)."""
        if self.busy:
            raise Busy(f"Skynet está trabajando en «{self.label}». Espera o pulsa Detener antes de abrir otra sesión.")
        sid = self.sid if self.sesiones.vacia(self.sid) else self.sesiones.crear()["id"]
        self.abrir(sid)
        return sid

    def sesion_info(self) -> dict[str, Any]:
        ses = self.sesiones.get(self.sid)
        return {"id": self.sid, "titulo": ses["titulo"], "consumo": self.sesiones.consumo(self.sid),
                "contexto": self.ctx.get("contexto") or 0, "contexto_max": context_window(self, self.ctx.get("modelo")),
                "tps": getattr(self, "tps", None)}

    @property
    def busy(self) -> bool:
        return self.running

    def start(self, label: str, work: Callable[[], Awaitable[Any]]) -> None:
        if self.busy:
            raise Busy(f"Skynet está trabajando en «{self.label}». Espera o pulsa Detener.")
        self.label = label
        self.running = True
        self.gen += 1
        self.current = asyncio.create_task(self._wrap(work, self.gen))
        self.bus.publish("ocupado", {"ocupado": True, "etiqueta": label})

    async def _wrap(self, work: Callable[[], Awaitable[Any]], gen: int) -> None:
        try:
            await work()
        except asyncio.CancelledError:
            if gen == self.gen:
                self.bus.publish("info", {"texto": "Detenido. La tarea queda pausada: «Continuar» la retoma."})
        except ConfigError as e:
            self.bus.publish("error", {"texto": f"Configuración: {e}"})
        except Exception as e:  # la web no debe morir por un fallo de una tarea
            self.bus.publish("error", {"texto": f"{type(e).__name__}: {e}"})
        finally:
            if gen == self.gen:
                self._release()

    def _release(self) -> None:
        self.running = False
        self.label = ""
        self.bus.publish("ocupado", {"ocupado": False})
        self.bus.publish("estado", snapshot(self))

    def message(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self.busy:
            raise Busy(f"Skynet está trabajando en «{self.label}». Espera o pulsa Detener.")
        self.bus.publish("usuario", {"texto": text})

        async def run() -> None:
            if await self.coord.handle(text) is False:  # «salir», «adiós»...
                self.ui.info("La web sigue abierta. Para cerrar Skynet, cierra la ventana donde lanzaste «skynet web».")

        self.start(text.splitlines()[0][:70], run)

    async def cancel(self, wait: float = 4.0) -> bool:
        """Detiene el trabajo actual. Si en `wait` segundos no ha terminado (una llamada al modelo o una
        herramienta que no responde a la cancelación), se abandona: la web queda libre al momento y el
        trabajo viejo se sigue cancelando en segundo plano sin tocar el estado del siguiente."""
        if not self.busy:
            return False
        assert self.current is not None
        task = self.current
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        if self.running and (task.done() or task is self.current):
            if not task.done():
                self.bus.publish("info", {"texto": "Detenido. Algo seguía colgado y se cierra en segundo plano; "
                                                   "ya puedes escribir."})
                self._fail_open_questions()
                reaper = asyncio.create_task(self._keep_cancelling(task))
                self._abandoned.add(reaper)
                reaper.add_done_callback(self._abandoned.discard)
            self.gen += 1  # el finally del trabajo abandonado ya no toca nada
            self._release()
        return True

    @staticmethod
    async def _keep_cancelling(task: asyncio.Task[Any]) -> None:
        # Algunas librerías se tragan una cancelación (p. ej. al cerrar un servidor MCP): se repite.
        while not task.done():
            task.cancel()
            await asyncio.wait([task], timeout=2)

    def _fail_open_questions(self) -> None:
        for qid in list(self.ui.pending):
            self.ui.resolve(qid, "n")

# --- serialización -------------------------------------------------------
def task_dict(t: Task) -> dict[str, Any]:
    d = asdict(t)
    d["vivo"] = t.runner_alive()
    d["larga"] = t.is_long
    return d


def event_dict(e: dict[str, Any]) -> dict[str, Any]:
    return {**e, "descripcion": describe_event(e)}


def models_info(rt: Runtime, engines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    on = {e["nombre"]: e for e in engines}
    for name, m in rt.settings.models.items():
        free = (m.coste_entrada_usd_mtok or 0) == 0 and (m.coste_salida_usd_mtok or 0) == 0
        if name in on:
            ok, why = on[name]["encendido"], "" if on[name]["encendido"] else "motor apagado"
        else:
            ok, why = (True, "") if name == "local" else rt.router._usable(m)
            if why.startswith("modelo en la nube sin activar"):  # se explica con «activado»
                ok, why = m.available()
        nube_on = rt.access.nube_ok(name)
        if ok and not nube_on:
            ok, why = False, "desactivado (modelo en la nube)"
        out.append({"nombre": name, "litellm": m.litellm, "privado": m.privado, "gratis": free,
                    "disponible": ok, "motivo": why, "activado": nube_on, "modo": rt.access.modo(name),
                    "sin_preguntar": rt.access.sin_preguntar(name),
                    "coste": [m.coste_entrada_usd_mtok, m.coste_salida_usd_mtok]})
    return out


def snapshot(s: Session) -> dict[str, Any]:
    rt, c = s.rt, s.coord
    pending = rt.store.last_resumable_task()
    month = rt.store.totals(since=_month_start())
    long_alive = [t.id for t in rt.store.list_tasks(limit=30) if t.is_long and t.runner_alive()]
    engines = s.engines.status() if s.engines else []
    return {
        "version": __version__,
        "build": BUILD,
        "repo": c.repo_name,
        "modelo": c.force_model or "auto",
        "privado": c.private,
        "internet": c.internet and not internet_blocked(s),
        "internet_bloqueado": internet_blocked(s),
        "coder": c.coder and c.repo_name is not None,
        "razonamiento": c.effort or "auto",
        "ocupado": s.busy,
        "etiqueta": s.label,
        "preguntas": s.ui.open_questions(),
        "repos": [{"nombre": r.nombre, "ruta": str(r.ruta), "verificador": r.verificador, "agente": r.agente,
                   "privacidad": r.privacidad, "existe": r.ruta.exists()} for r in rt.settings.repos.values()],
        "modelos": models_info(rt, engines),
        "motores": engines,
        "reglas": rt.settings.rules,
        "presupuesto_eur": rt.settings.budget_eur,
        "mes": month,
        "pendiente": task_dict(pending) if pending else None,
        "largas_vivas": long_alive,
        "limites": {"max_horas": rt.settings.long.max_horas},
        "ayuda": HELP,
        "propuestas": propuestas.count(rt.settings.home),
        "modos": [{"clave": m.clave, "nombre": m.nombre, "descripcion": m.descripcion, "fuerte": m.fuerte}
                  for m in modos.MODOS.values()],
        "modo_actual": rt.access.modo(_current_model(s)),
        "sin_preguntar_actual": rt.access.sin_preguntar(_current_model(s)),
        "sin_preguntar_texto": modos.SIN_PREGUNTAR,
        "modelo_efectivo": _current_model(s),
        "siempre": modos.SIEMPRE,
        "sesion": s.sesion_info(),
    }


# Ventana de contexto conocida por proveedor (lo de llama-server sale de su motor en skynet.toml).
CONTEXTO_NUBE = {"gemini/": 1_048_576, "anthropic/": 200_000}


def context_window(s: Session, litellm: str | None = None) -> int | None:
    """Tamaño de la ventana de contexto del modelo que se usó (o del que se usaría ahora)."""
    rt = s.rt
    name = None
    if litellm:
        name = next((n for n, m in rt.settings.models.items() if m.litellm == litellm), None)
    name = name or _current_model(s)
    spec = s.engines.specs.get(name) if s.engines else None
    ctx = getattr(spec, "contexto", None) if spec else None
    if ctx:
        return int(ctx)
    m = rt.settings.models.get(name)
    lit = m.litellm if m else (litellm or "")
    return next((v for k, v in CONTEXTO_NUBE.items() if lit.startswith(k)), None)


def internet_blocked(s: Session) -> bool:
    repo = s.rt.settings.repos.get(s.coord.repo_name)
    return s.coord.private or bool(repo and repo.privacidad == "alta")


def _current_model(s: Session) -> str:
    """Modelo que usaría el próximo mensaje (para mostrar su modo de permisos junto al chat)."""
    try:
        return s.rt.router.choose(Capabilities.from_dict(s.coord._caps())).profile.nombre
    except Exception:
        return "local"


def _month_start() -> str:
    from ..cli import _month_start as ms

    return ms()


# --- seguridad: esta página desde este PC, o un dispositivo emparejado por Tailscale ---------
PROXY = ("x-forwarded-for", "forwarded", "x-real-ip", "tailscale-user-login", "tailscale-funnel-request")
SOLO_PC = ("/api/repos", "/api/dispositivos")  # en remoto no: añadir repos y gestionar dispositivos
SIN_LLAVE = ("/api/emparejar",)


class Acceso:
    """Dos tipos de cliente:
    - local: el navegador de este PC (Host 127.0.0.1/localhost y sin cabeceras de proxy). Como siempre.
    - remoto: llega por Tailscale Serve (proxy en este mismo PC). Necesita IP de Tailscale, Host *.ts.net,
      un origen permitido (la app) y la llave de un dispositivo emparejado. Sin Funnel (internet público)."""

    def __init__(self, app: ASGIApp, port_ref: dict[str, int], dispositivos: Dispositivos, cfg: ConfigAcceso,
                 on_rechazo: Callable[[str, str | None], None] | None = None):
        self.app = app
        self.port_ref = port_ref
        self.dispositivos = dispositivos
        self.cfg = cfg
        self.on_rechazo = on_rechazo or (lambda motivo, ip: None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        port = self.port_ref.get("port")
        allowed = {f"{h}:{port}" for h in ("127.0.0.1", "localhost", "[::1]")} if port else None
        host = headers.get("host", "")
        if not any(h in headers for h in PROXY) and (allowed is None or host in allowed):
            return await self._local(scope, receive, send, headers, host)
        if allowed is not None and host in allowed:
            # el Host de este PC con cabeceras de proxy: no es Tailscale Serve (que trae su propio Host)
            return await _deny(scope, receive, send, "Petición local con cabeceras de proxy")
        return await self._remoto(scope, receive, send, headers, host)

    async def _local(self, scope: Scope, receive: Receive, send: Send, headers: dict[str, str], host: str) -> None:
        if scope["method"] not in ("GET", "HEAD"):
            origin = headers.get("origin")
            if origin is not None and origin != f"http://{host}":
                return await _deny(scope, receive, send, "Origen no permitido")
            if "application/json" not in headers.get("content-type", ""):
                return await _deny(scope, receive, send, "Se espera JSON")
        scope.setdefault("state", {})["cliente"] = Cliente(remoto=False)
        await self.app(scope, receive, send)

    async def _remoto(self, scope: Scope, receive: Receive, send: Send, headers: dict[str, str], host: str) -> None:
        origin = headers.get("origin")
        cors = origin if origin in self.cfg.origenes else None
        extra = [(b"vary", b"Origin")] + ([(b"access-control-allow-origin", cors.encode("latin-1"))] if cors else [])

        async def no(msg: str, status: int = 403, **kw: Any) -> None:
            self.on_rechazo(msg, ip)
            r = JSONResponse({"ok": False, "error": msg, **kw}, status_code=status)
            r.raw_headers.extend(extra)
            await r(scope, receive, send)

        ip = ip_cliente(headers.get("x-forwarded-for"))
        if "tailscale-funnel-request" in headers:
            return await no("Skynet no se publica en internet (Tailscale Funnel): solo dentro de tu red de Tailscale.")
        if not ip_de_tailscale(ip):
            return await no("Solo se puede entrar por Tailscale.")
        if not self.cfg.host_valido(host):
            return await no("Host no permitido")
        usuario = (headers.get("tailscale-user-login") or "").lower() or None
        if self.cfg.usuarios and usuario not in self.cfg.usuarios:
            return await no("Esta cuenta de Tailscale no está autorizada en este PC.")
        if origin is not None and cors is None:
            return await no("Origen no permitido")
        path = scope["path"]
        if scope["method"] == "OPTIONS":
            if cors is None:
                return await no("Origen no permitido")
            r = Response(status_code=204, headers={
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Max-Age": "600"})
            r.raw_headers.extend(extra)
            return await r(scope, receive, send)
        if not path.startswith("/api/"):
            return await no("No encontrado", 404)
        if scope["method"] not in ("GET", "HEAD") and "application/json" not in headers.get("content-type", ""):
            return await no("Se espera JSON")
        cliente = Cliente(remoto=True, ip=ip, usuario=usuario)
        if path not in SIN_LLAVE:
            auth = headers.get("authorization", "")
            llave = auth[7:].strip() if auth[:7].lower() == "bearer " else None
            disp = self.dispositivos.verificar(llave)
            if disp is None:
                return await no("Este móvil no está autorizado (o se quitó desde el PC). Vuelve a emparejarlo.",
                                401, reautorizar=True)
            if any(path == p or path.startswith(p + "/") for p in SOLO_PC):
                return await no("Solo desde el PC: por seguridad, esto no se puede hacer desde el móvil.")
            self.dispositivos.tocar(disp, ip)
            cliente.dispositivo = disp
        scope.setdefault("state", {})["cliente"] = cliente

        async def send_cors(msg: Any) -> None:
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": [*msg.get("headers", []), *extra]}
            await send(msg)

        await self.app(scope, receive, send_cors)


def cliente_de(request: Request) -> Cliente:
    return getattr(request.state, "cliente", None) or Cliente(remoto=False)


def jresp(data: Any, status: int = 200) -> Response:
    return Response(json.dumps(data, ensure_ascii=False, default=str), status_code=status,
                    media_type="application/json")


async def _deny(scope: Scope, receive: Receive, send: Send, why: str) -> None:
    await JSONResponse({"error": why}, status_code=403)(scope, receive, send)


# --- aplicación ----------------------------------------------------------
class FreshStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        # Edge debe revalidar los módulos al actualizar Skynet, sin mezclar versiones.
        if path.endswith((".js", ".css")) and not path.startswith("vendor/"):
            response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(rt: Runtime, port: int | None = None) -> Starlette:
    session = Session(rt)
    port_ref: dict[str, int] = {"port": port} if port else {}
    cfg = ConfigAcceso.desde(getattr(rt.settings, "acceso", None))
    dispositivos = Dispositivos(rt.settings.home / "data" / "dispositivos.json")
    acceso = EstadoAcceso(port or 8765, cfg.url)
    rechazos: dict[str, float] = {}

    def on_rechazo(motivo: str, ip: str | None) -> None:
        # Al registro, pero como mucho una vez por minuto y motivo (un móvil viejo reintentando no lo llena).
        t = time.monotonic()
        if t - rechazos.get(motivo, -1e9) >= 60:
            rechazos[motivo] = t
            rt.audit.log("permission", tool="skynet.acceso", decision="denegado",
                         detail={"motivo": f"{motivo} ({ip or 'sin IP'})"})

    async def body(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def ok(**kw: Any) -> JSONResponse:
        return JSONResponse({"ok": True, **kw})

    def bad(msg: str, code: int = 400) -> JSONResponse:
        return JSONResponse({"ok": False, "error": msg}, status_code=code)

    def confirm(kind: str, title: str, text: str, ok_label: str) -> JSONResponse:
        """La web tiene que confirmar antes de repetir la petición con "confirmar": true (409)."""
        return JSONResponse({"ok": False, "error": title, "confirmar": {"tipo": kind, "titulo": title, "texto": text,
                                                                      "boton": ok_label}}, status_code=409)

    def cloud_confirm(model: str) -> JSONResponse:
        return confirm("nube", f"¿Activar {model}?", modos.CONFIRMAR_NUBE.format(modelo=model).rsplit("¿", 1)[0].strip(),
                       f"Activar {model}")

    async def index(request: Request) -> Response:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def stream(request: Request) -> Response:
        q = session.bus.subscribe()
        replay = session.sesiones.mensajes(session.sid, REPLAY)

        async def gen():
            try:
                yield f"event: hola\ndata: {json.dumps(snapshot(session), ensure_ascii=False, default=str)}\n\n"
                for m in replay:
                    yield f"data: {json.dumps({**m, 'replay': True}, ensure_ascii=False, default=str)}\n\n"
                last = replay[-1]["seq"] if replay else 0
                while True:
                    try:
                        m = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_SEG)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield ": ping\n\n"
                        continue
                    if m["tipo"] == "_fin":
                        break
                    if m["seq"] <= last:
                        continue
                    yield f"data: {json.dumps(m, ensure_ascii=False, default=str)}\n\n"
            finally:
                session.bus.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def estado(request: Request) -> Response:
        return jresp(snapshot(session))

    async def mensaje(request: Request) -> Response:
        text = str((await body(request)).get("texto") or "").strip()
        if not text:
            return bad("Mensaje vacío")
        if len(text) > 20000:
            return bad("Mensaje demasiado largo")
        cli = cliente_de(request)
        try:
            session.message(text)
        except Busy as e:
            return bad(str(e), 409)
        if cli.remoto and cli.dispositivo:
            rt.audit.log("permission", tool="skynet.remoto", decision="mensaje",
                         detail={"mensaje": f"Desde {cli.dispositivo.nombre}: {text[:120]}"})
        return ok()

    async def responder(request: Request) -> Response:
        b = await body(request)
        value = str(b.get("respuesta") or "n").strip().lower()
        if value not in ("s", "n", "t"):
            return bad("Respuesta: s, n o t")
        if not session.ui.resolve(str(b.get("id")), value):
            return bad("Esa pregunta ya no está abierta", 404)
        cli = cliente_de(request)
        if cli.remoto and cli.dispositivo:
            rt.audit.log("permission", tool="skynet.remoto", decision={"s": "permitido", "t": "permitido",
                                                                       "n": "denegado"}[value],
                         detail={"mensaje": f"Respondido desde {cli.dispositivo.nombre}"})
        return ok()

    async def repos_nuevo(request: Request) -> Response:
        b = await body(request)
        nombre = str(b.get("nombre") or "").strip()
        ruta = str(b.get("ruta") or "").strip().strip('"')
        verificador = str(b.get("verificador") or "").strip() or None
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", nombre):
            return bad("El nombre solo puede tener letras, números, guiones y guiones bajos (máx. 40).")
        if nombre in rt.settings.repos:
            return bad(f"Ya hay un repo llamado '{nombre}'.", 409)
        if not ruta:
            return bad("Indica la carpeta del repo.")
        folder = Path(os.path.expandvars(os.path.expanduser(ruta))).resolve()
        if not folder.is_dir():
            return bad(f"La carpeta no existe: {folder}")
        rt.settings.repos[nombre] = add_repo(rt.settings.home, nombre, folder, verificador)
        session.bus.publish("estado", snapshot(session))
        return jresp(snapshot(session))

    async def cancelar(request: Request) -> Response:
        return ok(cancelado=await session.cancel())

    async def ajustes(request: Request) -> Response:
        b = await body(request)
        c = session.coord
        # «Sin preguntar» se confirma antes de cambiar nada (también el modo que llega en la misma petición).
        sp = b.get("sin_preguntar") if isinstance(b.get("sin_preguntar"), dict) else None
        if sp and sp.get("activar") and cliente_de(request).remoto:
            return bad("Solo desde el PC: «Sin preguntar» no se puede activar desde el móvil.", 403)
        if sp and sp.get("activar") and sp.get("modelo") in rt.settings.models and not b.get("confirmar"):
            name = sp["modelo"]
            target = (b.get("permiso") or {}).get("modo") if isinstance(b.get("permiso"), dict) else None
            if (target or rt.access.modo(name)) == "total" and not rt.access.sin_preguntar(name):
                text = rt.access.aviso_sin_preguntar(name)
                if target and rt.access.necesita_aviso(name, target):
                    text = modos.aviso_nube(name, target) + " " + text
                return confirm("aviso", f"¿{name} sin preguntar nada?", text, "Sí, sin preguntar")
        if "internet" in b:
            if not isinstance(b["internet"], bool):
                return bad("Internet debe ser true o false")
            if session.busy:
                return bad("Espera a que termine o pulsa Detener antes de cambiar Internet.", 409)
            if b["internet"] and bool(b.get("privado", c.private)):
                return bad("Desactiva la privacidad alta antes de activar Internet.")
            target_repo = rt.settings.repos.get(b.get("repo", c.repo_name))
            if b["internet"] and target_repo and target_repo.privacidad == "alta":
                return bad("Este repo tiene privacidad alta: la búsqueda web está desactivada.")
            c.internet = b["internet"]
        if "coder" in b:
            if not isinstance(b["coder"], bool):
                return bad("Coder debe ser true o false")
            if session.busy:
                return bad("Espera a que termine o pulsa Detener antes de cambiar Coder.", 409)
            if b["coder"] and not (b.get("repo", c.repo_name) in rt.settings.repos):
                return bad("Elige un repo antes de activar Coder.")
            c.coder = b["coder"]
        if "repo" in b:
            r = b["repo"]
            if r in (None, "", "ninguno"):
                c.repo_name, c.coder = None, False
                session.ui.info("Sin repo: conversación sin herramientas.")
            elif r in rt.settings.repos:
                c.repo_name = r
                session.ui.info(f"Repo: {r}")
            else:
                return bad(f"'{r}' no está autorizado en config/repos.toml")
        if "razonamiento" in b:
            r = b["razonamiento"]
            if r not in ("auto", "low", "medium", "high"):
                return bad(f"Nivel de razonamiento desconocido: {r}")
            c.effort = None if r == "auto" else r
        acc = rt.access
        confirmed = bool(b.get("confirmar"))
        if "nube" in b:
            n = b["nube"] if isinstance(b["nube"], dict) else {}
            name, on = n.get("modelo"), bool(n.get("activar"))
            if not acc.es_nube(str(name)):
                return bad(f"{name} no es un modelo en la nube")
            if on and not acc.nube_ok(name) and not confirmed:
                return cloud_confirm(name)
            acc.activar_nube(name, on)
            rt.audit.log("permission", tool="skynet.nube", decision="activada" if on else "desactivada",
                         detail={"modelo": name})
            if not on and c.force_model == name:
                c.force_model = "local"
            session.ui.info(f"{name} {'activado para esta sesión' if on else 'desactivado: Skynet vuelve al modelo local'}.")
        if "permiso" in b:
            p = b["permiso"] if isinstance(b["permiso"], dict) else {}
            name, mode = p.get("modelo"), p.get("modo")
            if name not in rt.settings.models or not modos.modo_valido(str(mode)):
                return bad(f"Modelo o modo desconocido: {name} / {mode}")
            if acc.necesita_aviso(name, mode) and not confirmed:
                return confirm("aviso", f"Modo «{modos.MODOS[mode].nombre}» en un modelo en la nube",
                               modos.aviso_nube(name, mode), "Entiendo, darle este modo")
            changed = acc.modo(name) != mode
            acc.set_modo(name, mode)
            rt.audit.log("permission", tool="skynet.permisos", decision=mode, detail={"modelo": name})
            if changed and "sin_preguntar" not in b:
                session.ui.info(f"{name}: modo «{modos.MODOS[mode].nombre}». {modos.MODOS[mode].descripcion}")
        if "sin_preguntar" in b:
            p = b["sin_preguntar"] if isinstance(b["sin_preguntar"], dict) else {}
            name, on = p.get("modelo"), bool(p.get("activar"))
            if name not in rt.settings.models:
                return bad(f"Modelo desconocido: {name}")
            if on and acc.modo(name) != "total":
                return bad("«Sin preguntar» solo existe en el modo Control total")
            acc.set_sin_preguntar(name, on)
            rt.audit.log("permission", tool="skynet.sin_preguntar", decision="activado" if on else "desactivado",
                         detail={"modelo": name})
            session.ui.info(f"{name}: {'sin preguntar (Control total de verdad)' if on else 'vuelve a preguntar lo delicado'}.")
        if "modelo" in b:
            m = b["modelo"]
            if m in (None, "", "auto"):
                c.force_model = None
            elif m in rt.settings.models:
                if not acc.nube_ok(m):
                    if not confirmed:
                        return cloud_confirm(m)
                    acc.activar_nube(m, True)
                    rt.audit.log("permission", tool="skynet.nube", decision="activada", detail={"modelo": m})
                c.force_model = m
            else:
                return bad(f"Modelo desconocido: {m}")
            session.ui.info(f"Modelo: {c.force_model or 'automático (router)'}")
        if "privado" in b:
            c.private = bool(b["privado"])
            if c.private:
                c.internet = False
            session.ui.info(f"Privacidad alta {'activada: solo modelo local' if c.private else 'desactivada'}.")
        snap = snapshot(session)
        session.bus.publish("estado", snap)
        return jresp(snap)

    async def tareas(request: Request) -> Response:
        n = min(int(request.query_params.get("n", 30)), 200)
        return jresp([task_dict(t) for t in rt.store.list_tasks(limit=n)])

    def _task_or_404(request: Request) -> Task | Response:
        try:
            return rt.store.get_task(int(request.path_params["id"]))
        except (KeyError, ValueError):
            return bad("No existe esa tarea", 404)

    async def tarea(request: Request) -> Response:
        t = _task_or_404(request)
        if isinstance(t, Response):
            return t
        steps = [asdict(s) for s in rt.store.steps_for(t.id)]
        events = [event_dict(e) for e in rt.store.events(task_id=t.id, limit=80)]
        repo = rt.settings.repos.get(t.repo) if t.repo else None
        progreso = None
        if repo and t.is_long and (repo.ruta / "PROGRESO.md").exists():
            progreso = (repo.ruta / "PROGRESO.md").read_text(encoding="utf-8", errors="replace")[:8000]
        return jresp({"tarea": task_dict(t), "pasos": steps, "eventos": events,
                      "consumo": rt.store.totals(task_id=t.id), "progreso": progreso})

    async def tarea_accion(request: Request) -> Response:
        t = _task_or_404(request)
        if isinstance(t, Response):
            return t
        action = request.path_params["accion"]
        st = rt.store
        if action == "parar":
            if t.status in (HECHA, FALLIDA):
                return bad(f"La tarea {t.id} ya terminó ({t.status}).")
            st.update_task(t.id, status=PAUSADA)
            session.ui.info(f"Pedida la parada de la tarea {t.id}; se detiene al acabar la iteración en curso.")
        elif action == "descartar":
            st.set_status(t.id, FALLIDA, "descartada por el usuario")
            session.ui.info(f"Tarea {t.id} descartada: «continúa» ya no la retomará.")
        elif action == "continuar":
            extra = str((await body(request)).get("indicaciones") or "").strip() or None
            try:
                session.bus.publish("usuario", {"texto": f"continúa la tarea {t.id}" + (f": {extra}" if extra else "")})
                session.start(f"continúa {t.title}", lambda: session.coord.resume(extra, task_id=t.id))
            except Busy as e:
                return bad(str(e), 409)
        else:
            return bad("Acción desconocida", 404)
        session.bus.publish("tareas", {})
        return ok()

    async def largo(request: Request) -> Response:
        b = await body(request)
        goal = str(b.get("objetivo") or "").strip()
        try:
            hours = float(str(b.get("horas")).replace(",", "."))
        except ValueError:
            return bad("Horas no válidas")
        if not goal or not (0 < hours <= rt.settings.long.max_horas):
            return bad(f"Indica un objetivo y entre 0 y {rt.settings.long.max_horas} horas")
        repo = b.get("repo") or session.coord.repo_name
        if repo not in rt.settings.repos:
            return bad("Elige un repo autorizado")
        if session.busy:
            return bad(f"Skynet está trabajando en «{session.label}». Espera o pulsa Detener.", 409)
        session.coord.repo_name = repo
        session.bus.publish("usuario", {"texto": f"Tarea larga ({hours:g} h) en {repo}: {goal}"})
        session.start(f"tarea larga: {goal[:50]}", lambda: session.coord._long([f"{hours:g}", *goal.split()]))
        return ok()

    async def log(request: Request) -> Response:
        qp = request.query_params
        task_id = int(qp["tarea"]) if qp.get("tarea", "").isdigit() else None
        n = min(int(qp.get("n", 120)), 1000)
        data = {
            "eventos": [event_dict(e) for e in rt.store.events(task_id=task_id, limit=n)],
            "total": rt.store.totals(task_id=task_id),
            "mes": rt.store.totals(since=_month_start()),
        }
        return jresp(data)

    async def doctor(request: Request) -> Response:
        from ..cli import doctor_checks

        checks = await asyncio.to_thread(doctor_checks, rt)
        return jresp({"checks": checks})

    async def motor(request: Request) -> Response:
        b = await body(request)
        eng = session.engines
        name = b.get("nombre")
        if name not in eng.specs:
            return bad(f"Motor desconocido: {name}")
        if name in eng.busy:
            return bad("Ya se está encendiendo o apagando")
        on = bool(b.get("encender"))

        async def work() -> None:
            eng.busy.add(name)
            session.bus.publish("estado", snapshot(session))
            try:
                msg = await asyncio.to_thread(eng.start if on else eng.stop, name)
                session.ui.info(msg)
                if on and name in rt.settings.models:
                    if rt.access.nube_ok(name):
                        session.coord.force_model = name  # usar el motor que se acaba de encender
                    else:
                        session.ui.info(f"{name} es un modelo en la nube: para usarlo, actívalo en Ajustes (pide confirmación).")
            except Exception as e:
                session.ui.info(f"No se pudo {'encender' if on else 'apagar'} {name}: {e}")
            finally:
                eng.busy.discard(name)
                eng.invalidate()
                session.bus.publish("estado", snapshot(session))

        asyncio.create_task(work())
        return jresp(snapshot(session))

    def _actual_local() -> str:
        spec = session.engines.specs.get("local") if session.engines else None
        return Path(os.path.expandvars(spec.modelo)).name.removesuffix(".gguf") if spec and spec.modelo else ""

    async def modelos_locales_lista(request: Request) -> Response:
        ms = await asyncio.to_thread(modelos_locales.buscar)
        return jresp({"modelos": [m.info() for m in ms], "actual": _actual_local()})

    async def modelo_local(request: Request) -> Response:
        b = await body(request)
        eng = session.engines
        if not eng or "local" not in eng.specs or eng.specs["local"].tipo != "llamacpp":
            return bad("No hay motor local de llama.cpp")
        hit = next((m for m in modelos_locales.buscar() if m.nombre == b.get("nombre")), None)
        if not hit:
            return bad(f"No encuentro el modelo: {b.get('nombre')}")
        if "local" in eng.busy:
            return bad("El motor local se está encendiendo o apagando")
        was_on = await asyncio.to_thread(eng.is_on, "local")
        eng.set_local_model("local", hit)
        modelos_locales.guardar(rt.settings.logs_dir.parent, hit.nombre)

        async def work() -> None:
            eng.busy.add("local")
            session.bus.publish("estado", snapshot(session))
            try:
                if was_on:
                    await asyncio.to_thread(eng.stop, "local")
                    await asyncio.to_thread(eng.start, "local")
                session.ui.info(f"Modelo local: {hit.nombre}" + ("" if was_on else " (se usará al encender el motor)"))
            except Exception as e:
                session.ui.info(f"No se pudo cargar {hit.nombre}: {e}")
            finally:
                eng.busy.discard("local")
                eng.invalidate()
                session.bus.publish("estado", snapshot(session))

        asyncio.create_task(work())
        return jresp(snapshot(session))

    # --- dispositivos (el móvil) ---------------------------------------------------
    def lista_dispositivos(fresco: bool = False) -> dict[str, Any]:
        return {"dispositivos": dispositivos.lista(), "acceso": acceso.resumen(fresco)}

    async def dispositivos_get(request: Request) -> Response:
        fresco = request.query_params.get("fresco") == "1"
        return jresp(await asyncio.to_thread(lista_dispositivos, fresco))

    async def dispositivos_emparejar(request: Request) -> Response:
        b = await body(request)
        res = await asyncio.to_thread(acceso.resumen, True)
        codigo, expira = dispositivos.nuevo_codigo(b.get("nombre"))
        url = res["url"]
        return jresp({"codigo": codigo, "url": url, "enlace": enlace_emparejar(url, codigo),
                      "expira": datetime.fromtimestamp(expira, timezone.utc).isoformat(timespec="seconds"),
                      "acceso": res})

    async def dispositivos_revocar(request: Request) -> Response:
        try:
            d = dispositivos.revocar(str(request.path_params["id"]))
        except AccesoError as e:
            return bad(str(e), e.status)
        rt.audit.log("permission", tool="skynet.dispositivos", decision="quitado",
                     detail={"mensaje": f"Dispositivo quitado: {d.nombre}"})
        session.ui.info(f"Dispositivo quitado: {d.nombre}. Ya no puede entrar.")
        return jresp(await asyncio.to_thread(lista_dispositivos))

    async def emparejar(request: Request) -> Response:
        b = await body(request)
        cli = cliente_de(request)
        try:
            llave, d = dispositivos.emparejar(str(b.get("codigo") or ""), b.get("nombre"), cli.ip)
        except AccesoError as e:
            rt.audit.log("permission", tool="skynet.dispositivos", decision="denegado",
                         detail={"mensaje": f"Emparejado rechazado ({cli.ip or 'local'}): {e}"})
            return bad(str(e), e.status)
        quien = f" · {cli.usuario}" if cli.usuario else ""
        rt.audit.log("permission", tool="skynet.dispositivos", decision="emparejado",
                     detail={"mensaje": f"Nuevo dispositivo: {d.nombre} ({cli.ip or 'local'}{quien})"})
        session.ui.info(f"Nuevo dispositivo conectado: {d.nombre}. Puedes quitarlo en Configuración › Dispositivos.")
        return jresp({"ok": True, "llave": llave, "dispositivo": {"id": d.id, "nombre": d.nombre}})

    async def yo(request: Request) -> Response:
        cli = cliente_de(request)
        d = cli.dispositivo
        return jresp({"remoto": cli.remoto, "dispositivo": {"id": d.id, "nombre": d.nombre} if d else None})

    # --- sesiones (historial de conversaciones) ---------------------------------
    async def sesiones_lista(request: Request) -> Response:
        q = request.query_params.get("q", "")[:200]
        return jresp({"sesiones": session.sesiones.lista(q), "actual": session.sid})

    async def sesiones_nueva(request: Request) -> Response:
        try:
            session.nueva()
        except Busy as e:
            return bad(str(e), 409)
        return jresp(snapshot(session))

    async def sesion_abrir(request: Request) -> Response:
        try:
            session.abrir(int(request.path_params["id"]))
        except Busy as e:
            return bad(str(e), 409)
        except KeyError as e:
            return bad(str(e.args[0]), 404)
        return jresp(snapshot(session))

    async def sesion_editar(request: Request) -> Response:
        sid = int(request.path_params["id"])
        if not session.sesiones.existe(sid):
            return bad(f"No existe la sesión {sid}", 404)
        if request.url.path.endswith("/archivar"):
            if sid == session.sid and session.busy:
                return bad("Espera a que termine o pulsa Detener antes de borrar esta sesión.", 409)
            session.sesiones.archivar(sid)
            if sid == session.sid:
                last = session.sesiones.ultima()
                session.abrir(last["id"] if last else session.sesiones.crear()["id"])
            return jresp({"sesiones": session.sesiones.lista(), "actual": session.sid})
        titulo = str((await body(request)).get("titulo") or "").strip()
        if not titulo:
            return bad("El título no puede estar vacío")
        session.sesiones.renombrar(sid, titulo)
        if sid == session.sid:
            session.bus.publish("estado", snapshot(session))
        return jresp({"sesiones": session.sesiones.lista(), "actual": session.sid})

    # --- aprendizaje: propuestas de skills y memoria pendientes de tu visto bueno -----------
    async def aprendizaje_lista(request: Request) -> Response:
        home = rt.settings.home
        skl, mem = propuestas.list_proposals(home)
        items = []
        for p in skl:
            f = propuestas.propuestas_dir(home) / p["nombre"] / "SKILL.md"
            try:
                texto = skills.parse_skill(f).body()
            except (OSError, ValueError):
                texto = ""
            items.append({"id": p["nombre"], "tipo": "skill", "titulo": p["nombre"], "descripcion": p["descripcion"],
                          "origen": p["origen"], "texto": texto})
        if mem:
            items.append({"id": propuestas.MEMORIA, "tipo": "memoria", "titulo": "Recordar",
                          "descripcion": f"{len(mem)} dato{'s' if len(mem) != 1 else ''} para la memoria",
                          "origen": "", "texto": "\n".join(f"- {t}" for _, t in mem),
                          "lineas": [{"destino": d, "texto": t} for d, t in mem]})
        return jresp({"items": items})

    async def aprendizaje_accion(request: Request) -> Response:
        nombre = str(request.path_params["nombre"])
        accion = str((await body(request)).get("accion") or "")
        if accion not in ("aprobar", "descartar"):
            return bad("Acción: aprobar o descartar")
        try:
            if not propuestas.exists(rt.settings.home, nombre):
                return bad("Esa propuesta ya no está pendiente", 404)
        except ValueError as e:
            return bad(str(e))
        cmd = "/aprobar" if accion == "aprobar" else "/rechazar"
        try:  # el mismo camino que el comando: aprobar pasa por el permission gate y queda auditado
            session.start(f"{'Aprobar' if accion == 'aprobar' else 'Descartar'} {nombre}",
                          lambda: session.coord._review(cmd, [nombre]))
        except Busy as e:
            return bad(str(e), 409)
        return ok()

    routes = [
        Route("/api/sesiones", sesiones_lista),
        Route("/api/aprendizaje", aprendizaje_lista),
        Route("/api/aprendizaje/{nombre}", aprendizaje_accion, methods=["POST"]),
        Route("/api/sesiones/nueva", sesiones_nueva, methods=["POST"]),
        Route("/api/sesiones/{id:int}/abrir", sesion_abrir, methods=["POST"]),
        Route("/api/sesiones/{id:int}", sesion_editar, methods=["POST"]),
        Route("/api/sesiones/{id:int}/archivar", sesion_editar, methods=["POST"]),
        Route("/api/modelos-locales", modelos_locales_lista),
        Route("/api/modelo-local", modelo_local, methods=["POST"]),
        Route("/api/emparejar", emparejar, methods=["POST"]),
        Route("/api/yo", yo),
        Route("/api/dispositivos", dispositivos_get),
        Route("/api/dispositivos/emparejar", dispositivos_emparejar, methods=["POST"]),
        Route("/api/dispositivos/{id}/revocar", dispositivos_revocar, methods=["POST"]),
        Route("/api/motor", motor, methods=["POST"]),
        Route("/", index),
        Route("/api/stream", stream),
        Route("/api/estado", estado),
        Route("/api/mensaje", mensaje, methods=["POST"]),
        Route("/api/responder", responder, methods=["POST"]),
        Route("/api/cancelar", cancelar, methods=["POST"]),
        Route("/api/ajustes", ajustes, methods=["POST"]),
        Route("/api/repos", repos_nuevo, methods=["POST"]),
        Route("/api/tareas", tareas),
        Route("/api/tareas/{id:int}", tarea),
        Route("/api/tareas/{id:int}/{accion}", tarea_accion, methods=["POST"]),
        Route("/api/largo", largo, methods=["POST"]),
        Route("/api/log", log),
        Route("/api/doctor", doctor),
        Mount("/static", FreshStaticFiles(directory=STATIC), name="static"),
    ]
    app = Starlette(routes=routes, middleware=[Middleware(Acceso, port_ref=port_ref, dispositivos=dispositivos,
                                                           cfg=cfg, on_rechazo=on_rechazo)])
    app.state.session = session
    app.state.port_ref = port_ref
    app.state.dispositivos = dispositivos
    app.state.acceso = acceso
    return app


def serve(rt: Runtime, port: int = 8765, open_browser: bool = True) -> int:
    import uvicorn

    host = "127.0.0.1"
    app = create_app(rt, port)
    url = f"http://{host}:{port}"
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", timeout_graceful_shutdown=3,
                            access_log=False)

    class _Server(uvicorn.Server):
        async def startup(self, sockets: Any = None) -> None:
            self._loop = asyncio.get_running_loop()
            await super().startup(sockets)
            if self.started and open_browser:
                webbrowser.open(url)  # cuando ya escucha, para no ver una página de error

        def handle_exit(self, sig: int, frame: Any) -> None:
            # Ctrl+C: primero se cierran los streams SSE; si no, uvicorn espera por ellos.
            loop = getattr(self, "_loop", None)
            if loop is not None:
                loop.call_soon_threadsafe(app.state.session.bus.close)
            super().handle_exit(sig, frame)

    print(f"Skynet web en {url}  (Ctrl+C para cerrar)", flush=True)
    _Server(config).run()
    return 0
