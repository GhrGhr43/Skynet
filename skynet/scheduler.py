"""Scheduler: tareas largas en iteraciones cortas y verificadas (sin LLM en el control).

Cada iteración usa una sesión nueva del modelo y su estado sale de la DB y de archivos:
  leer estado -> 1 paso del agente -> verificador -> commit si pasa o no empeora / rollback si empeora
  -> actualizar PROGRESO.md
Paradas: límite de horas, de iteraciones, N fallos iguales seguidos, N iteraciones sin
avance, o parada pedida (estado 'pausada' en la DB). Si el repo usa agente-godot, el
scheduler lo lanza por MCP (coding_agent) y lo vigila hasta que acaba.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import gitops
from .agent import DONE_MARK
from .config import RepoConfig
from .context import task_dir
from .gate import PermissionGate
from .runtime import Runtime
from .store import EN_CURSO, FALLIDA, HECHA, PAUSADA, Task
from .toolhub import ToolHub
from .verifier import VerifierResult, run_verifier

ITERATION_INSTRUCTIONS = f"""Esta es la iteración {{n}} de una tarea larga que avanza en pasos pequeños verificados.
- Haz UN avance concreto y pequeño hacia el objetivo, que el verificador pueda comprobar. No intentes hacerlo todo de golpe.
- Lee PROGRESO.md y ERRORES.md (arriba) para no repetir lo que ya falló. PROGRESO.md lo escribe Skynet: no lo edites.
- Si después de tu cambio pasan menos tests o fallan más que al empezar, todo lo de esta iteración se deshará.
- Al terminar, resume en 1-3 líneas qué hiciste.
- Solo si el objetivo COMPLETO ya está cumplido y el verificador pasa, añade al final una línea con {DONE_MARK}."""

EventFn = Callable[[str, dict[str, Any]], None]


def _print_event(kind: str, data: dict[str, Any]) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {kind}: {data}", flush=True)


class LongTaskRunner:
    def __init__(self, rt: Runtime, task_id: int, on_event: EventFn | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.rt = rt
        self.store = rt.store
        self.task_id = task_id
        self.on_event = on_event or _print_event
        self.sleep = sleep
        self.clock = clock

    # --- archivos de estado ---------------------------------------------
    def _write_progress(self, task: Task, repo: RepoConfig, estado: str) -> None:
        steps = self.store.steps_for(task.id)
        tot = self.store.totals(task_id=task.id)
        lines = [
            f"# PROGRESO: tarea {task.id}",
            "",
            f"**Objetivo:** {task.goal}",
            "",
            f"- Estado: **{estado}**",
            f"- Iteraciones: {task.iters_done}"
            + (f" de {task.max_iters}" if task.max_iters else "")
            + (f" | límite {task.max_hours} h" if task.max_hours else ""),
            f"- Modelo: {tot['tokens_in']} tokens de entrada, {tot['tokens_out']} de salida, {tot['cost_eur']:.4f} €",
            f"- Actualizado: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "| # | Resultado | Verificador | Commit | Resumen |",
            "|---|---|---|---|---|",
        ]
        for s in steps:
            if s.kind != "iteracion":
                continue
            summary = (s.output_summary or "").replace("\n", " ").replace("|", "/")[:140]
            lines.append(f"| {s.n} | {s.status} | {(s.verifier_result or '').replace('|', '/')[:60]} | "
                         f"{(s.commit_sha or '')[:8]} | {summary} |")
        (repo.ruta / "PROGRESO.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _append_error(self, repo: RepoConfig, task: Task, n: int, text: str) -> None:
        td = task_dir(repo, task.id)
        td.mkdir(parents=True, exist_ok=True)
        f = td / "ERRORES.md"
        prev = f.read_text(encoding="utf-8") if f.exists() else "# Errores de iteraciones revertidas\n"
        entry = f"\n## Iteración {n} ({datetime.now().strftime('%H:%M')})\n```\n{text.strip()[-1500:]}\n```\n"
        f.write_text((prev + entry)[-20000:], encoding="utf-8")

    def _audit_verifier(self, task: Task, step_id: int | None, ver: VerifierResult, inicial: bool = False) -> None:
        self.rt.audit.log("verifier", task_id=task.id, step_id=step_id,
                          detail={"ok": ver.ok, "exit": ver.exit_code, "comando": ver.command, "inicial": inicial,
                                  "cuentas": ver.counts(), "segundos": round(ver.seconds, 1),
                                  "salida": ver.output_tail[-1500:]})

    async def _heartbeat_loop(self) -> None:
        while True:
            self.store.heartbeat(self.task_id)
            await asyncio.sleep(30)

    # --- bucle principal ------------------------------------------------
    async def run(self) -> Task:
        task = self.store.get_task(self.task_id)
        repo = self.rt.repo_for(task)
        if repo is None:
            raise ValueError("Una tarea larga necesita un repo autorizado")
        if repo.agente == "agente-godot":
            return await self._run_agente_godot(task, repo)
        L = self.rt.settings.long
        max_hours = task.max_hours or L.max_horas
        max_iters = task.max_iters or L.max_iteraciones
        deadline = self.clock() + max_hours * 3600

        gitops.ensure_repo(repo.ruta)
        td = task_dir(repo, task.id)
        td.mkdir(parents=True, exist_ok=True)
        (td / "OBJETIVO.md").write_text(f"# Objetivo de la tarea {task.id}\n\n{task.goal}\n", encoding="utf-8")
        sha = gitops.commit_all(repo.ruta, f"skynet: estado previo a la tarea {task.id}")
        if sha:
            self.rt.audit.log("commit", task_id=task.id, detail={"sha": sha, "mensaje": "estado previo"})
        task = self.store.update_task(task.id, status=EN_CURSO, max_hours=max_hours, max_iters=max_iters)
        self.store.heartbeat(task.id)
        self._write_progress(task, repo, "en curso")
        gitops.commit_all(repo.ruta, f"skynet: inicio de la tarea {task.id}")
        self.on_event("inicio", {"tarea": task.id, "repo": repo.nombre, "horas": max_hours, "iters": max_iters})

        streak_sig, streak_n, no_progress = None, 0, 0
        final_status, reason = PAUSADA, "interrumpida"
        hb = asyncio.create_task(self._heartbeat_loop())
        try:
            # Estado de partida: una iteración se acepta si el verificador pasa o, al menos,
            # no empeora respecto a la última aceptada (menos tests en verde o más fallos = rollback).
            baseline: VerifierResult | None = None
            if repo.verificador:
                baseline = await asyncio.to_thread(run_verifier, repo.verificador, repo.ruta,
                                                   L.timeout_verificador_seg)
                self._audit_verifier(task, None, baseline, inicial=True)
                self.on_event("verificador_inicial", {"resumen": baseline.summary(), "cuentas": baseline.counts()})
            while True:
                task = self.store.get_task(self.task_id)
                if task.status == PAUSADA:
                    final_status, reason = PAUSADA, "parada pedida por el usuario"
                    break
                if self.clock() >= deadline:
                    final_status, reason = PAUSADA, f"límite de tiempo ({max_hours} h)"
                    break
                if task.iters_done >= max_iters:
                    final_status, reason = PAUSADA, f"límite de iteraciones ({max_iters})"
                    break

                n = task.iters_done + 1
                checkpoint = gitops.head(repo.ruta)
                self.on_event("iteracion", {"n": n})
                run = await self.rt.agent_step(
                    task, "iteracion", on_event=self.on_event, max_turns=L.turnos_por_iteracion,
                    instructions=ITERATION_INSTRUCTIONS.format(n=n), protected=["PROGRESO.md"],
                )
                out = run.outcome
                ver: VerifierResult | None = None
                if out.status == "error":
                    strict = accepted = False
                    sig, err_text = "modelo:" + (out.error or "")[:80], out.error or "error del modelo"
                elif repo.verificador:
                    ver = await asyncio.to_thread(run_verifier, repo.verificador, repo.ruta,
                                                  L.timeout_verificador_seg)
                    self._audit_verifier(task, run.step.id, ver)
                    strict, accepted = ver.ok, ver.not_worse_than(baseline)
                    sig, err_text = ver.signature, ver.output_tail
                else:
                    strict = accepted = out.status == "completado"
                    sig, err_text = "sin-verificador", out.final_text
                self.on_event("verificador", {"ok": strict, "aceptada": accepted,
                                              "resumen": ver.summary() if ver else "sin verificador"})

                changed = gitops.is_dirty(repo.ruta)
                if accepted:
                    if ver is not None:
                        baseline = ver
                    no_progress = 0 if (changed or out.claims_done) else no_progress + 1
                    step_status = ("ok" if strict else "avance") if changed else "sin_cambios"
                else:
                    gitops.rollback(repo.ruta, checkpoint)
                    self.rt.audit.log("rollback", task_id=task.id, step_id=run.step.id,
                                      detail={"sha": checkpoint or "", "mensaje": f"iteración {n} revertida"})
                    self._append_error(repo, task, n, err_text)
                    step_status = "revertida"
                if strict:
                    streak_sig, streak_n = None, 0
                else:
                    streak_n = streak_n + 1 if sig == streak_sig else 1
                    streak_sig = sig

                summary = out.final_text.replace(DONE_MARK, "").strip()
                self.store.finish_step(run.step.id, step_status, summary[:2000],
                                       ver.summary() if ver else None, None)
                task = self.store.update_task(task.id, iters_done=n)
                self._write_progress(task, repo, "en curso")
                first = (summary.splitlines() or ["(sin resumen)"])[0][:72]
                msg = (f"skynet: tarea {task.id} it. {n}: {first}" if accepted
                       else f"skynet: tarea {task.id} it. {n} revertida (verificador falla)")
                commit_sha = gitops.commit_all(repo.ruta, msg)
                if commit_sha:
                    self.store.finish_step(run.step.id, step_status, summary[:2000],
                                           ver.summary() if ver else None, commit_sha)
                    self.rt.audit.log("commit", task_id=task.id, step_id=run.step.id,
                                      detail={"sha": commit_sha, "mensaje": msg})

                if strict and out.claims_done:
                    final_status, reason = HECHA, "objetivo cumplido y verificador en verde"
                    break
                if streak_n >= L.max_errores_iguales:
                    final_status, reason = FALLIDA, f"el mismo fallo se repitió {streak_n} veces seguidas"
                    break
                if no_progress >= L.max_sin_avance:
                    final_status, reason = PAUSADA, f"{no_progress} iteraciones seguidas sin cambios"
                    break
                if out.status == "error":
                    await self.sleep(30)  # p. ej. LM Studio reiniciándose
        finally:
            hb.cancel()
            task = self.store.get_task(self.task_id)
            summary = f"{reason}. {task.iters_done} iteraciones."
            self.store.update_task(task.id, status=final_status, result_summary=summary)
            self.store.clear_heartbeat(task.id)
            self.rt.audit.log("task", task_id=task.id, decision=final_status, detail={"motivo": reason})
            task = self.store.get_task(task.id)
            self._write_progress(task, repo, f"{final_status}: {reason}")
            gitops.commit_all(repo.ruta, f"skynet: tarea {task.id} {final_status} ({reason})")
            self.on_event("fin", {"estado": final_status, "motivo": reason})
        return task

    # --- agente-godot ----------------------------------------------------
    async def _run_agente_godot(self, task: Task, repo: RepoConfig) -> Task:
        """Lanza noche.ps1 vía el servidor MCP coding_agent y lo vigila (sin LLM)."""
        hours = task.max_hours or self.rt.settings.long.max_horas
        audit = self.rt.audit.bind(task.id)
        grants = list(task.capabilities.get("permisos_preaprobados", []))
        gate = PermissionGate(self.rt.settings, repo, audit, asker=None, grants=grants)
        self.store.update_task(task.id, status=EN_CURSO)
        self.store.heartbeat(task.id)
        final, reason = FALLIDA, "no se pudo lanzar agente-godot"
        step = self.store.start_step(task.id, "agente-godot", f"noche.ps1 {hours} h")
        try:
            async with ToolHub(self.rt.server_specs(repo, ["coding_agent"]), self.rt.settings.logs_dir) as hub:
                async def call(tool: str, args: dict[str, Any]) -> tuple[bool, str]:
                    key = f"coding_agent.{tool}"
                    gr = await gate.check(key, args, str(args))
                    if not gr.allowed:
                        return False, f"DENEGADO: {gr.reason}"
                    r = await hub.call(f"coding_agent__{tool}", args)
                    audit.log("tool", step_id=step.id, tool=key, permission_level=gr.level.name,
                              decision=gr.decision.value, detail={"args_resumen": str(args), "ok": r.ok,
                                                                  "resultado": r.text[:150]})
                    return r.ok, r.text

                ok, text = await call("start_task", {"repo": str(repo.ruta), "horas": hours})
                self.on_event("agente-godot", {"start": text[:200]})
                if ok:
                    final, reason = PAUSADA, "vigilancia interrumpida"
                    while True:
                        await self.sleep(60)
                        self.store.heartbeat(task.id)
                        if self.store.get_task(task.id).status == PAUSADA:
                            await call("stop_task", {"repo": str(repo.ruta)})
                            final, reason = PAUSADA, "parada pedida por el usuario"
                            break
                        ok, st = await call("status", {"repo": str(repo.ruta)})
                        if "en_marcha: no" in st:
                            final, reason = HECHA, "agente-godot terminó su sesión"
                            break
                    _, hist = await call("history", {"repo": str(repo.ruta), "n": 20})
                    self.store.finish_step(step.id, "ok", hist[:2000])
                else:
                    self.store.finish_step(step.id, "error", text[:2000])
        finally:
            self.store.update_task(task.id, status=final, result_summary=reason)
            self.store.clear_heartbeat(task.id)
            audit.log("task", decision=final, detail={"motivo": reason})
        return self.store.get_task(task.id)


def spawn_background(rt: Runtime, task_id: int) -> int:
    """Lanza `python -m skynet largo --tarea N` desacoplado del chat. Devuelve el pid."""
    logs = rt.settings.logs_dir
    logs.mkdir(parents=True, exist_ok=True)
    log = open(logs / f"tarea-{task_id}.log", "a", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    env = dict(os.environ, SKYNET_HOME=str(rt.settings.home), PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([sys.executable, "-m", "skynet", "largo", "--tarea", str(task_id)],
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         cwd=str(rt.settings.home), env=env, creationflags=flags)
    log.close()
    rt.store.update_task(task_id, pid=p.pid)
    return p.pid
