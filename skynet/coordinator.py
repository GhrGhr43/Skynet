"""Coordinator: convierte cada mensaje del chat en una tarea y decide cómo ejecutarla.

- Mensaje normal: tarea nueva. Con repo elegido -> agente programador con herramientas MCP;
  sin repo -> conversación sin herramientas. El modelo lo elige el router por capacidades.
- "continúa" (o "sigue"): retoma la última tarea sin terminar desde SQLite.
- /largo H objetivo: tarea larga en segundo plano (Scheduler).
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
from typing import Any, Protocol

from . import gitops, propuestas, skills
from .agent import summarize_args
from .gate import Level, PermissionGate
from .router import Capabilities
from .runtime import Runtime
from .scheduler import spawn_background
from .store import EN_CURSO, ESPERANDO_PERMISO, FALLIDA, HECHA, PAUSADA, PENDIENTE, Task
from .verifier import VerifierResult, run_verifier

RESUME_RE = re.compile(r"^\s*(contin[uú]a|continuar|sigue)\b[\s,:.\-]*(.*)$", re.IGNORECASE | re.DOTALL)

HELP = """Escribe lo que quieres que haga. Comandos:
  continúa [indicaciones]   retoma la última tarea sin terminar
  /repos                    repos autorizados          /repo <nombre|ninguno>  elegir repo
  /modelo local|cloud|auto  forzar modelo              /privado                privacidad alta on/off
  /largo <horas> <objetivo> tarea larga en segundo plano con verificador y commits
  /tareas                   últimas tareas             /estado <id>            detalle de una tarea
  /parar <id>               parar una tarea larga      /log [id]               audit log
  /buscar <texto>           buscar en el historial     /skills                 skills disponibles
  /skill <nombre> <tarea>   tarea siguiendo una skill  /propuestas             skills y memoria propuestas
  /aprobar <nombre>         activar una propuesta      /rechazar <nombre>      descartarla
  /doctor                   comprobar instalación      /descartar [id]         dar una tarea por abandonada
  /ayuda                    esta ayuda                 /salir                  salir"""


class UI(Protocol):
    def info(self, text: str) -> None: ...
    def answer(self, text: str) -> None: ...
    def event(self, kind: str, data: dict[str, Any]) -> None: ...
    def show(self, renderable: Any) -> None: ...
    async def ask(self, prompt: str) -> str: ...


class Coordinator:
    def __init__(self, rt: Runtime, ui: UI):
        self.rt = rt
        self.ui = ui
        repos = list(rt.settings.repos)
        self.repo_name: str | None = repos[0] if len(repos) == 1 else None
        self.force_model: str | None = None
        self.private = False
        self.history: list[tuple[str, str]] = []  # (petición, respuesta) recientes de esta sesión

    # --- entrada ---------------------------------------------------------
    async def handle(self, text: str) -> bool:
        """Procesa un mensaje. Devuelve False si hay que salir."""
        text = text.strip()
        if not text:
            return True
        if text.startswith("/"):
            return await self._command(text)
        word = text.lower().strip(" .!")
        if word in ("exit", "quit", "salir", "adiós", "adios"):
            return False
        if word in ("doctor", "ayuda", "help", "tareas", "log", "repos"):
            return await self._command("/" + word)
        m = RESUME_RE.match(text)
        if m:
            await self.resume(m.group(2).strip() or None)
            return True
        await self.new_task(text)
        return True

    def _caps(self, **extra: Any) -> dict[str, Any]:
        caps = Capabilities(coding="alto" if self.repo_name else "bajo", force=self.force_model)
        if self.private:
            caps.privacy = "alta"
        for k, v in extra.items():
            setattr(caps, k, v)
        return caps.to_dict()

    def _recent(self) -> str | None:
        if not self.history:
            return None
        lines = [f"- Pedido: {q[:300]}\n  Respuesta: {a[:500]}" for q, a in self.history[-3:]]
        return "Conversación reciente (por si la petición se refiere a ella):\n" + "\n".join(lines)

    # --- tareas ----------------------------------------------------------
    async def new_task(self, text: str, skill: str | None = None, skill_version: str | None = None) -> Task:
        title = text.splitlines()[0][:70]
        caps: dict[str, Any] = {"capacidades": self._caps()}
        if skill:
            caps["skill"] = skill  # el Context builder mete su cuerpo en cada paso, también al retomar
        task = self.rt.store.create_task(
            title=title, goal=text, agent="skynet" if self.repo_name else "chat", repo=self.repo_name,
            status=PENDIENTE, capabilities=caps,
        )
        self.rt.audit.log("task", task_id=task.id, decision="creada",
                          detail={"mensaje": title, "repo": self.repo_name, **({"skill": skill} if skill else {})})
        if skill:
            self.rt.store.add_skill_use(skill, skill_version, task.id)
        return await self._run(task, kind="chat", extra=self._recent())

    async def resume(self, extra: str | None, task_id: int | None = None) -> None:
        """Retoma la última tarea sin terminar, o la tarea `task_id` si se indica (lo usa la web)."""
        task = self.rt.store.get_task(task_id) if task_id else self.rt.store.last_resumable_task()
        if task is None:
            self.ui.info("No hay ninguna tarea pendiente que retomar.")
            return
        if task.repo and task.repo not in self.rt.settings.repos:
            self.ui.info(f"La tarea {task.id} es del repo '{task.repo}', que ya no está autorizado.")
            return
        if task.is_long:
            if task.runner_alive():
                self.ui.info(f"La tarea larga {task.id} ya está en marcha (pid {task.pid}). Mira /estado {task.id}.")
                return
            self.rt.store.update_task(task.id, status=PENDIENTE)
            pid = spawn_background(self.rt, task.id)
            self.ui.info(f"Retomo la tarea larga {task.id} «{task.title}» en segundo plano (pid {pid}).")
            return
        if task.runner_alive() and task.pid != os.getpid():
            self.ui.info(f"La tarea {task.id} parece estar en marcha en otra ventana (pid {task.pid}).")
            return
        self.repo_name = task.repo
        self.ui.info(f"Retomo la tarea {task.id} «{task.title}» (estado: {task.status}).")
        await self._run(task, kind="reanudar",
                        extra=(extra or "Continúa la tarea donde se quedó. Revisa los pasos anteriores y el "
                                        "estado de git antes de seguir."))

    def _make_asker(self, task: Task):
        async def ask(key: str, level: Level, args: dict[str, Any], reason: str) -> str:
            self.rt.store.update_task(task.id, status=ESPERANDO_PERMISO)
            options = "[s]í / [n]o" + (" / [t]odas en esta tarea" if level is not Level.DESTRUCTIVE else "")
            prompt = f"{level.name} · {key}({summarize_args(args)})\nMotivo: {reason}\n¿Permitir? {options}"
            try:
                return await self.ui.ask(prompt)
            finally:
                self.rt.store.update_task(task.id, status=EN_CURSO)
        return ask

    async def _run(self, task: Task, kind: str, extra: str | None) -> Task:
        store = self.rt.store
        repo = self.rt.repo_for(task)
        task = store.update_task(task.id, status=EN_CURSO)
        store.heartbeat(task.id)
        status, summary = PAUSADA, "interrumpida"
        ver: VerifierResult | None = None
        try:
            run = await self.rt.agent_step(task, kind, extra, asker=self._make_asker(task), on_event=self.ui.event)
            out = run.outcome
            if (repo and repo.verificador and out.status == "completado" and gitops.is_repo(repo.ruta)
                    and (out.files_touched or gitops.is_dirty(repo.ruta))):
                self.ui.event("verifying", {"command": repo.verificador})
                # En un hilo: el verificador puede tardar minutos y no debe congelar la interfaz web.
                ver = await asyncio.to_thread(run_verifier, repo.verificador, repo.ruta,
                                              self.rt.settings.long.timeout_verificador_seg)
                self.rt.audit.log("verifier", task_id=task.id, step_id=run.step.id,
                                  detail={"ok": ver.ok, "exit": ver.exit_code, "comando": ver.command,
                                          "segundos": round(ver.seconds, 1), "salida": ver.output_tail[-1500:]})
            if out.status == "error":
                status = FALLIDA
            elif out.status == "limite_turnos":
                status = PAUSADA
            elif ver is not None and not ver.ok:
                status = FALLIDA
            else:
                status = HECHA
            summary = out.final_text[:2000]
            store.finish_step(run.step.id, out.status, summary, ver.summary() if ver else None)
            self.history.append((task.goal if kind == "chat" else (extra or "continúa"), out.final_text))
            self.ui.answer(out.final_text)
            foot = (f"{out.model.split('/')[-1]} · {out.tokens_in}+{out.tokens_out} tokens · {out.cost_eur:.4f} € · "
                    f"{out.tool_calls} herramientas · tarea {task.id}: {status}")
            if ver is not None:
                foot += f" · verificador {'OK' if ver.ok else 'FALLA'}"
            self.ui.info(foot)
            if ver is not None and not ver.ok:
                self.ui.info("El verificador falla:\n" + "\n".join(ver.output_tail.strip().splitlines()[-12:])
                             + "\nDi «continúa» para que intente arreglarlo.")
            elif status == PAUSADA:
                self.ui.info("Se quedó a medias. Di «continúa» para seguir.")
        finally:
            store.update_task(task.id, status=status, result_summary=summary)
            store.clear_heartbeat(task.id)
            self.rt.audit.log("task", task_id=task.id, decision=status, detail={"motivo": (summary.splitlines() or [""])[0][:200]})
        if ver is not None and task.capabilities.get("skill"):
            store.set_skill_result(task.id, ver.ok)
        if status == HECHA and ver is not None and propuestas.eligible(self.rt, task, ver.ok):
            self.ui.info("Tarea verificada tras varios pasos: redacto una propuesta de skill/memoria...")
            created = await propuestas.propose_after_task(self.rt, store.get_task(task.id), ver.summary())
            if created:
                self.ui.info(f"Propuestas nuevas: {', '.join(created)}. Revísalas con /propuestas.")
        return store.get_task(task.id)

    # --- comandos --------------------------------------------------------
    async def _command(self, text: str) -> bool:
        from . import views

        try:
            parts = shlex.split(text, posix=True)
        except ValueError:
            parts = text.split()
        cmd, args = parts[0].lower(), parts[1:]
        st = self.rt.store
        if cmd in ("/salir", "/exit", "/quit"):
            return False
        if cmd in ("/ayuda", "/help", "/?"):
            self.ui.info(HELP)
        elif cmd == "/repos":
            for r in self.rt.settings.repos.values():
                mark = "→" if r.nombre == self.repo_name else " "
                self.ui.info(f"{mark} {r.nombre}: {r.ruta} · verificador: {r.verificador or '-'} · agente: {r.agente}")
            if not self.rt.settings.repos:
                self.ui.info("No hay repos autorizados. Añádelos en config/repos.toml.")
        elif cmd == "/repo":
            if not args:
                self.ui.info(f"Repo actual: {self.repo_name or 'ninguno'}")
            elif args[0] in ("ninguno", "-", "none"):
                self.repo_name = None
                self.ui.info("Sin repo: conversación sin herramientas.")
            elif args[0] in self.rt.settings.repos:
                self.repo_name = args[0]
                self.ui.info(f"Repo: {args[0]}")
            else:
                self.ui.info(f"'{args[0]}' no está autorizado. Mira /repos.")
        elif cmd == "/modelo":
            choice = (args[0] if args else "auto").lower()
            if choice == "auto":
                self.force_model = None
            elif choice in self.rt.settings.models:
                self.force_model = choice
            else:
                self.ui.info(f"Modelos: {', '.join(self.rt.settings.models)} o auto")
                return True
            self.ui.info(f"Modelo: {self.force_model or 'automático (router)'}")
        elif cmd == "/privado":
            self.private = not self.private
            self.ui.info(f"Privacidad alta {'activada: solo modelo local' if self.private else 'desactivada'}.")
        elif cmd == "/tareas":
            self.ui.show(views.tasks_table(st.list_tasks(limit=int(args[0]) if args else 15)))
        elif cmd == "/estado":
            task = self._task_arg(args)
            if task:
                self.ui.show(views.task_detail(st, task))
        elif cmd == "/log":
            task_id = int(args[0]) if args and args[0].isdigit() else None
            self.ui.show(views.events_table(st.events(task_id=task_id, limit=40)))
            self.ui.show(views.totals_line(st.totals(task_id=task_id), "Total" if task_id is None else f"Tarea {task_id}"))
        elif cmd == "/parar":
            task = self._task_arg(args)
            if task:
                if task.status in (HECHA, FALLIDA):
                    self.ui.info(f"La tarea {task.id} ya terminó ({task.status}).")
                else:
                    st.update_task(task.id, status=PAUSADA)
                    self.ui.info(f"Pedida la parada de la tarea {task.id}; se detiene al acabar la iteración en curso.")
        elif cmd == "/doctor":
            from .cli import cmd_doctor

            await asyncio.to_thread(cmd_doctor, self.rt)
        elif cmd == "/descartar":
            task = self._task_arg(args)
            if task:
                st.set_status(task.id, FALLIDA, "descartada por el usuario")
                self.ui.info(f"Tarea {task.id} descartada: «continúa» ya no la retomará.")
        elif cmd == "/largo":
            await self._long(args)
        elif cmd == "/buscar":
            self._search(text.split(None, 1)[1] if len(text.split(None, 1)) > 1 else "")
        elif cmd == "/skills":
            found, errors = skills.load_skills(self.rt.skills_dir)
            stats = self.rt.store.skill_stats()
            for sk in found.values():
                st_ = stats.get(sk.name)
                uso = ""
                if st_:
                    uso = f" · {st_['usos']} usos"
                    if st_["evaluados"]:
                        uso += f", verificador OK {st_['ok']}/{st_['evaluados']} ({100 * st_['ok'] // st_['evaluados']} %)"
                self.ui.info(f"- {sk.name}: {sk.description}{uso}")
            if not found:
                self.ui.info(f"No hay skills. Crea {self.rt.skills_dir / '<nombre>' / 'SKILL.md'} (ver README).")
            for e in errors:
                self.ui.info(f"Skill ignorada · {e}")
        elif cmd == "/skill":
            await self._skill(text)
        elif cmd == "/propuestas":
            self._list_proposals()
        elif cmd in ("/aprobar", "/rechazar"):
            await self._review(cmd, args)
        else:
            self.ui.info(f"Comando desconocido: {cmd}. Escribe /ayuda.")
        return True

    def _search(self, query: str) -> None:
        query = query.strip()
        if not query:
            self.ui.info("Uso: /buscar <texto>   (busca en pasos y eventos de todas las tareas)")
            return
        hits = self.rt.store.search(query, limit=10)
        if not hits:
            self.ui.info(f"Nada en el historial para «{query}».")
            return
        lines = [f"tarea {h['task_id'] or '-'} · {h['origen']} {h['id']} · {(h['ts'] or '')[:16].replace('T', ' ')}: "
                 f"{h['fragmento'][:220]}" for h in hits]
        self.ui.info(f"{len(hits)} resultados para «{query}»:\n" + "\n".join(lines))

    async def _skill(self, text: str) -> None:
        # Sin shlex: la tarea es texto libre (puede llevar comillas o apóstrofos).
        parts = text.split(None, 2)
        found, _ = skills.load_skills(self.rt.skills_dir)
        if len(parts) < 2:
            self.ui.info("Uso: /skill <nombre> <tarea>. Mira /skills.")
            return
        name = parts[1]
        if name not in found:
            self.ui.info(f"No existe la skill '{name}'. Mira /skills.")
            return
        if len(parts) < 3 or not parts[2].strip():
            self.ui.info(f"{name}: {found[name].description}\nUso: /skill {name} <tarea>")
            return
        await self.new_task(parts[2].strip(), skill=name, skill_version=found[name].version())

    def _list_proposals(self) -> None:
        skl, mem = propuestas.list_proposals(self.rt.settings.home)
        if not skl and not mem:
            self.ui.info("No hay propuestas pendientes.")
            return
        lines = [f"- {p['nombre']}: {p['descripcion']}" + (f"\n    {p['origen']}" if p["origen"] else "") for p in skl]
        if mem:
            lines.append("- memoria: " + "; ".join(f"[{d}] {t}" for d, t in mem))
        where = propuestas.propuestas_dir(self.rt.settings.home)
        self.ui.info(f"Propuestas (en {where}; /aprobar <nombre> o /rechazar <nombre>):\n" + "\n".join(lines))

    async def _review(self, cmd: str, args: list[str]) -> None:
        home = self.rt.settings.home
        if not args:
            self.ui.info(f"Uso: {cmd} <nombre>   (mira /propuestas)")
            return
        name = args[0]
        try:
            if not propuestas.exists(home, name):
                self.ui.info(f"No hay ninguna propuesta '{name}'. Mira /propuestas.")
                return
            if cmd == "/rechazar":
                msg = propuestas.reject(home, name)
                self.rt.audit.log("propuesta", decision="rechazada", detail={"nombre": name})
                self.ui.info(msg)
                return
            # Aprobar cambia el comportamiento futuro de Skynet: PRIVILEGED, pregunta y queda auditado.
            async def ask(key: str, level: Level, a: dict[str, Any], reason: str) -> str:
                return await self.ui.ask(f"{level.name} · {key}({name})\nMotivo: {reason}. "
                                         f"Se activará la propuesta '{name}'.\n¿Permitir? [s]í / [n]o")
            gate = PermissionGate(self.rt.settings, None, self.rt.audit, asker=ask)
            res = await gate.check("skynet.aprobar", {"propuesta": name}, f"propuesta={name}")
            if not res.allowed:
                self.ui.info("No aprobada.")
                return
            msg = propuestas.approve(home, name)
            self.rt.audit.log("propuesta", decision="aprobada", permission_level=res.level.name, detail={"nombre": name})
            self.ui.info(msg)
        except (ValueError, OSError) as e:
            self.ui.info(str(e))

    def _task_arg(self, args: list[str]) -> Task | None:
        st = self.rt.store
        try:
            return st.get_task(int(args[0])) if args else st.last_resumable_task() or (st.list_tasks(1) or [None])[0]
        except (KeyError, ValueError):
            self.ui.info("No encuentro esa tarea.")
            return None

    async def _long(self, args: list[str]) -> None:
        if not self.repo_name:
            self.ui.info("Elige antes un repo con /repo <nombre>.")
            return
        try:
            hours = float(args[0].replace(",", "."))
            goal = " ".join(args[1:]).strip()
            if not goal or hours <= 0:
                raise ValueError
        except (IndexError, ValueError):
            self.ui.info("Uso: /largo <horas> <objetivo>   (ej.: /largo 2 haz que pasen todos los tests)")
            return
        repo = self.rt.settings.repo(self.repo_name)
        agent = "agente-godot" if repo.agente == "agente-godot" else "scheduler"
        grants = ["coding_agent.start_task", "coding_agent.stop_task"] if agent == "agente-godot" else []
        detail = ("lanzará agente-godot (noche.ps1)" if agent == "agente-godot" else
                  f"iteraciones con el modelo local, verificador `{repo.verificador or 'ninguno'}`, commit si pasa y "
                  "rollback si falla; las acciones que necesiten confirmación se denegarán")
        answer = await self.ui.ask(f"Tarea larga en '{repo.nombre}' durante {hours} h: {detail}.\n¿Lanzar? [s/n]")
        if answer.strip().lower() not in ("s", "si", "sí", "y", "yes"):
            self.ui.info("Cancelado.")
            return
        task = self.rt.store.create_task(
            title=goal[:70], goal=goal, agent=agent, repo=repo.nombre, status=PENDIENTE, max_hours=hours,
            capabilities={"capacidades": self._caps(cost="bajo"), "permisos_preaprobados": grants},
        )
        self.rt.audit.log("task", task_id=task.id, decision="creada",
                          detail={"mensaje": f"tarea larga {hours} h", "preaprobado": grants})
        pid = spawn_background(self.rt, task.id)
        self.ui.info(f"Tarea larga {task.id} lanzada en segundo plano (pid {pid}). Sigue su avance con "
                     f"/estado {task.id}, /log {task.id} o en {repo.ruta / 'PROGRESO.md'}. Para pararla: /parar {task.id}.")
