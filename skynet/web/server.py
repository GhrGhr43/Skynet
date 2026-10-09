"""Servidor de la interfaz web: el mismo Coordinator que el chat de terminal, servido por HTTP.

- GET  /                 la página (static/index.html)
- GET  /api/stream       eventos en vivo (Server-Sent Events): respuestas, herramientas, preguntas...
- GET  /api/estado       foto del estado: repo, modelo, privacidad, modelos, repos, preguntas abiertas
- POST /api/mensaje      un mensaje del chat (igual que escribir en la terminal)
- POST /api/responder    respuesta a una confirmación (permiso o «¿lanzar?»)
- ...                    tareas, registro, diagnóstico y ajustes (ver `routes`)

Solo escucha en 127.0.0.1. Además comprueba Host y Origin: sin eso, cualquier web abierta en el
navegador podría mandar órdenes a Skynet (DNS rebinding / CSRF). Sin dependencias nuevas:
Starlette y uvicorn ya vienen con el SDK de MCP; SSE en vez de WebSocket por lo mismo.
"""
from __future__ import annotations

import asyncio
import io
import itertools
import json
import os
import re
import webbrowser
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import __version__, modos, modelos_locales, propuestas
from ..agent import summarize_args
from ..audit import describe_event
from ..config import ConfigError, add_repo
from ..coordinator import HELP, Coordinator
from ..gate import SIEMPRE_TAG, Level
from ..router import Capabilities
from ..runtime import Runtime
from ..store import EN_CURSO, ESPERANDO_PERMISO, FALLIDA, HECHA, PAUSADA, Task

STATIC = Path(__file__).resolve().parent / "static"
KEEPALIVE_SEG = 15
REPLAY = 300  # mensajes de la conversación que recupera una pestaña nueva o recargada


# --- bus de eventos --------------------------------------------------------
class Bus:
    """Reparte cada evento a todas las pestañas abiertas y guarda la conversación reciente."""

    REPLAYABLE = {"usuario", "info", "respuesta", "evento", "tabla", "error", "diagnostico"}

    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.history: deque[dict[str, Any]] = deque(maxlen=REPLAY)
        self._seq = itertools.count(1)

    def publish(self, kind: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        msg = {"seq": next(self._seq), "tipo": kind, **(data or {})}
        if kind in self.REPLAYABLE and not (kind == "evento" and msg.get("kind") == "thinking"):
            self.history.append(msg)
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

    def info(self, text: str) -> None:
        self.bus.publish("info", {"texto": text})

    def answer(self, text: str) -> None:
        self.bus.publish("respuesta", {"texto": text or "(sin respuesta)"})

    def event(self, kind: str, data: dict[str, Any]) -> None:
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
    """El Coordinator de siempre; solo cambia cómo pregunta (datos estructurados para el diálogo)."""

    ui: WebUI

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


# --- sesión: un único trabajo a la vez, como en la terminal ---------------------
class Busy(Exception):
    pass


class Session:
    def __init__(self, rt: Runtime):
        self.rt = rt
        self.bus = Bus()
        self.ui = WebUI(self.bus)
        self.coord = WebCoordinator(rt, self.ui)
        self.current: asyncio.Task[Any] | None = None
        self.running = False  # no se mira current.done(): en su propio finally aún no ha terminado
        self.label = ""
        from ..engines import load_engines

        self.engines = load_engines(rt.settings.engines, rt.settings.logs_dir)

    @property
    def busy(self) -> bool:
        return self.running

    def start(self, label: str, work: Callable[[], Awaitable[Any]]) -> None:
        if self.busy:
            raise Busy(f"Skynet está trabajando en «{self.label}». Espera o pulsa Detener.")
        self.label = label
        self.running = True
        self.current = asyncio.create_task(self._wrap(work))
        self.bus.publish("ocupado", {"ocupado": True, "etiqueta": label})

    async def _wrap(self, work: Callable[[], Awaitable[Any]]) -> None:
        try:
            await work()
        except asyncio.CancelledError:
            self.bus.publish("info", {"texto": "Detenido. La tarea queda pausada: «Continuar» la retoma."})
        except ConfigError as e:
            self.bus.publish("error", {"texto": f"Configuración: {e}"})
        except Exception as e:  # la web no debe morir por un fallo de una tarea
            self.bus.publish("error", {"texto": f"{type(e).__name__}: {e}"})
        finally:
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

    async def cancel(self) -> bool:
        if not self.busy:
            return False
        assert self.current is not None
        self.current.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(self.current), timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        if self.running and self.current.done():  # cancelada antes de empezar: su finally no llegó a correr
            self.running = False
            self.bus.publish("ocupado", {"ocupado": False})
        return True


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
        "repo": c.repo_name,
        "modelo": c.force_model or "auto",
        "privado": c.private,
        "internet": c.internet and not internet_blocked(s),
        "internet_bloqueado": internet_blocked(s),
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
        "modelo_efectivo": _current_model(s),
        "siempre": modos.SIEMPRE,
    }


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


# --- seguridad: solo esta página, solo desde este PC ------------------------
class LocalOnly:
    def __init__(self, app: ASGIApp, port_ref: dict[str, int]):
        self.app = app
        self.port_ref = port_ref

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        port = self.port_ref.get("port")
        allowed = {f"{h}:{port}" for h in ("127.0.0.1", "localhost", "[::1]")} if port else None
        host = headers.get("host", "")
        if allowed is not None and host not in allowed:
            return await _deny(scope, receive, send, "Host no permitido")
        if scope["method"] not in ("GET", "HEAD"):
            origin = headers.get("origin")
            if origin is not None and origin != f"http://{host}":
                return await _deny(scope, receive, send, "Origen no permitido")
            if "application/json" not in headers.get("content-type", ""):
                return await _deny(scope, receive, send, "Se espera JSON")
        await self.app(scope, receive, send)


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
        replay = list(session.bus.history)

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
        try:
            session.message(text)
        except Busy as e:
            return bad(str(e), 409)
        return ok()

    async def responder(request: Request) -> Response:
        b = await body(request)
        value = str(b.get("respuesta") or "n").strip().lower()
        if value not in ("s", "n", "t"):
            return bad("Respuesta: s, n o t")
        if not session.ui.resolve(str(b.get("id")), value):
            return bad("Esa pregunta ya no está abierta", 404)
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
        if "repo" in b:
            r = b["repo"]
            if r in (None, "", "ninguno"):
                c.repo_name = None
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
            acc.set_modo(name, mode)
            rt.audit.log("permission", tool="skynet.permisos", decision=mode, detail={"modelo": name})
            session.ui.info(f"{name}: modo «{modos.MODOS[mode].nombre}». {modos.MODOS[mode].descripcion}")
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

    routes = [
        Route("/api/modelos-locales", modelos_locales_lista),
        Route("/api/modelo-local", modelo_local, methods=["POST"]),
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
    app = Starlette(routes=routes, middleware=[Middleware(LocalOnly, port_ref=port_ref)])
    app.state.session = session
    app.state.port_ref = port_ref
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
