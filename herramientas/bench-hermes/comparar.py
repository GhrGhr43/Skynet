"""Skynet contra Hermes con el mismo modelo local: mismas tareas, mismo llama-server, verificador oculto.

Los tokens se miden en llama-server (/metrics), no en cada agente: así se cuentan igual en los dos,
incluido lo que Hermes gasta en resúmenes o tareas auxiliares. Cada ejecución empieza de cero
(repo nuevo y, en Hermes, un HERMES_HOME nuevo): sin memoria de tareas anteriores.

Uso (desde la raíz de Skynet):
    .venv\\Scripts\\python herramientas\\bench-hermes\\comparar.py --motor 27b-q4 -a skynet,hermes -t factura,appids
Resultados en herramientas/bench-hermes/out/<fecha>.json y una tabla en pantalla.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "herramientas" / "bench-agentico"))

from agentico import build_repo, hidden_check  # noqa: E402
from agentico_tareas import TASKS  # noqa: E402
from tareas_calidad import TAREAS_CALIDAD  # noqa: E402
from tareas_extra import APPIDS_TASK, check_appids  # noqa: E402

PORT = 8090
URL = f"http://127.0.0.1:{PORT}"
CONTEXTO = 65536
MODELS = Path(os.environ["USERPROFILE"]) / ".lmstudio" / "models"
Q27 = MODELS / "unsloth" / "Qwen3.8-27B-GGUF" / "Qwen3.8-27B-UD-IQ3_XXS.gguf"
MOE = MODELS / "unsloth" / "Qwen3.6-35B-A3B-GGUF" / "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
GSQ = MODELS / "ISTA-DASLab" / "Qwen3.8-27B-GSQ-RCO-GGUF"  # mismo 27B, cuantizado con GSQ-RCO (cabeza MTP dentro)
# Mismos ajustes que el motor de Skynet (FA, un slot, MTP en el denso), con 64K y la caché de cada variante.
MOTORES = {
    "27b-q4": (Q27, ["-ctk", "q4_0", "-ctv", "q4_0", "--spec-type", "draft-mtp"]),
    "27b-q8": (Q27, ["-ctk", "q8_0", "-ctv", "q8_0", "--spec-type", "draft-mtp"]),
    "35b-moe": (MOE, ["-ctk", "q8_0", "-ctv", "q8_0", "--n-cpu-moe", "13"]),
    "gsq-iq3xxs": (GSQ / "Qwen3.8-27B-GSQ-RCO-IQ3_XXS-mtp.gguf", ["-ctk", "q4_0", "-ctv", "q4_0", "--spec-type", "draft-mtp"]),
    "gsq-iq3s": (GSQ / "Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf", ["-ctk", "q4_0", "-ctv", "q4_0", "--spec-type", "draft-mtp"]),
    "gpt-oss-20b": (MODELS / "ggml-org" / "gpt-oss-20b-GGUF" / "gpt-oss-20b-MXFP4.gguf", ["-ctk", "q4_0", "-ctv", "q4_0"]),
}
# Muestreo recomendado por cada fabricante: se pone en el servidor y en el perfil de Skynet de la prueba.
MUESTREO_QWEN = {"temperatura": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0}
MUESTREO = {"gpt-oss-20b": {"temperatura": 1.0, "top_p": 1.0, "top_k": 0, "min_p": 0.0}}
ALL_TASKS = {t["name"]: t for t in TASKS} | {APPIDS_TASK["name"]: APPIDS_TASK} | {t["name"]: t for t in TAREAS_CALIDAD}
LIMITE_SEG = 15 * 60  # por ejecución: una tarea atascada no se come la hora de pruebas


# --- motor ------------------------------------------------------------------------------------
def _get(path: str, timeout: float = 3) -> str | None:
    try:
        with urllib.request.urlopen(URL + path, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except OSError:
        return None


def metrics() -> dict[str, float]:
    out = {}
    for line in (_get("/metrics") or "").splitlines():
        if line.startswith("llamacpp:") and " " in line:
            k, v = line.split(" ", 1)
            try:
                out[k.removeprefix("llamacpp:")] = float(v)
            except ValueError:
                pass
    return out


def stop_engine() -> None:
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='llama-server.exe'\" | Where-Object { "
                    f"$_.CommandLine -like '*--port {PORT} *' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"],
                   capture_output=True)
    for _ in range(30):
        if _get("/health", 1) is None:
            return
        time.sleep(1)


def start_engine(name: str, log_dir: Path) -> None:
    exe = tomllib.loads((ROOT / "config" / "skynet.toml").read_text(encoding="utf-8"))["motores"]["local"]["exe"]
    model, extra = MOTORES[name]
    stop_engine()
    args = [os.path.expandvars(exe), "-m", str(model), "--port", str(PORT), "--alias", "local", "-c", str(CONTEXTO),
            "-fa", "on", "-np", "1", "--no-webui", "--metrics", *extra]
    # Muestreo del modelo por defecto en el servidor: Skynet ya lo manda; así Hermes y OpenCode, si no mandan
    # el suyo, usan el mismo.
    m = MUESTREO.get(name, MUESTREO_QWEN)
    args += ["--temp", str(m["temperatura"]), "--top-p", str(m["top_p"]), "--top-k", str(m["top_k"]),
             "--min-p", str(m["min_p"])]
    log = open(log_dir / f"llama-{name}.log", "a", encoding="utf-8")
    subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    t0 = time.monotonic()
    while time.monotonic() - t0 < 360:
        if (_get("/health", 2) or "").find('"ok"') >= 0:
            print(f"   motor {name} listo en {time.monotonic() - t0:.0f} s", flush=True)
            return
        time.sleep(2)
    raise RuntimeError(f"el motor {name} no arrancó; mira {log_dir / f'llama-{name}.log'}")


# --- verificación -----------------------------------------------------------------------------
def check(task: dict, repo: Path, info: dict) -> tuple[bool, str]:
    if "check" in task:  # tareas de calidad: cada una trae su comprobación oculta
        return task["check"](repo, info)
    return check_appids(repo) if task["name"] == "appids" else hidden_check(task, repo)


# --- Skynet -----------------------------------------------------------------------------------
async def run_skynet(task: dict, repo: Path, home: Path, max_turns: int, muestreo: dict | None = None) -> dict:
    from skynet.config import ModelProfile, load_settings
    from skynet.runtime import Runtime

    (home / "config").mkdir(parents=True, exist_ok=True)  # la tarea de memoria reutiliza el mismo home
    for f in ("skynet.toml", "permisos.toml", "router.toml"):
        shutil.copy(ROOT / "config" / f, home / "config" / f)
    (home / "config" / "repos.toml").write_text(
        f'[repos.bench]\nruta = "{repo.as_posix()}"\nverificador = "python -m pytest -q"\n'
        'ejecutar = ["python", "pytest"]\n', encoding="utf-8")
    settings = load_settings(home)
    base = tomllib.loads((ROOT / "config" / "router.toml").read_text(encoding="utf-8"))["modelos"]["local"]
    fields = set(ModelProfile.__dataclass_fields__)
    settings.models["local"] = ModelProfile(**{"nombre": "local", **{k: v for k, v in base.items() if k in fields},
                                               "contexto_tokens": CONTEXTO, **(muestreo or {})})
    rt = Runtime(settings)
    caps = {"force": "local", **({"internet": True} if task.get("internet") else {})}
    row = rt.store.create_task(title=task["name"], goal=task["prompt"], agent="skynet", repo="bench",
                               status="en_curso", capabilities={"capacidades": caps})

    async def asker(*_a):
        return "s"  # como en el banco agéntico: sin nadie delante, se permite lo que pregunte

    run = await rt.agent_step(rt.store.get_task(row.id), "chat", asker=asker, max_turns=max_turns)
    o = run.outcome
    rt.store.close()
    return {"estado": o.status, "turnos": o.turns, "herramientas": o.tool_calls, "error": o.error,
            "respuesta": o.final_text[:800]}


# --- bucle principal --------------------------------------------------------------------------
async def run_one(agent: str, task: dict, motor: str, out_dir: Path, max_turns: int) -> dict:
    work = out_dir / f"{motor}-{agent}-{task['name']}"
    repo, home = work / "repo", work / "home"
    repo.mkdir(parents=True)
    info = task["build"](repo) if "build" in task else (build_repo(task, repo) or {})
    m0, t0 = metrics(), time.monotonic()

    async def session(t: dict, log_name: str) -> dict:
        if agent == "skynet":
            return await asyncio.wait_for(run_skynet(t, repo, home, max_turns, MUESTREO.get(motor)), LIMITE_SEG)
        # Hermes y OpenCode van en Docker: solo hacen falta si se piden.
        if agent == "opencode":
            import opencode_runner as runner
        else:
            import hermes_runner as runner
        return await asyncio.to_thread(runner.run, t, repo, home, URL, CONTEXTO, max_turns, LIMITE_SEG,
                                       work / log_name)

    try:
        if "sesion1" in task:  # memoria: primero se le cuenta algo; la tarea va en una sesión nueva (mismo agente)
            await session({**task, "prompt": task["sesion1"]}, "sesion1.log")
        r = await session(task, f"{agent}.log")
    except asyncio.TimeoutError:
        r = {"estado": "limite_tiempo", "turnos": 0, "herramientas": 0, "error": f"más de {LIMITE_SEG // 60} min",
             "respuesta": ""}
    except Exception as e:  # un fallo de un agente no para el resto
        r = {"estado": "excepcion", "turnos": 0, "herramientas": 0, "error": f"{type(e).__name__}: {e}"[:500],
             "respuesta": ""}
    secs = time.monotonic() - t0
    m1 = metrics()
    ok, line = check(task, repo, info)
    d = {k: m1.get(k, 0) - m0.get(k, 0) for k in ("prompt_tokens_total", "tokens_predicted_total",
                                                  "prompt_seconds_total", "tokens_predicted_seconds_total")}
    return {"agente": agent, "motor": motor, "tarea": task["name"], "ok": ok, "verificador": line,
            "segundos": round(secs, 1), "tokens_prompt": int(d["prompt_tokens_total"]),
            "tokens_salida": int(d["tokens_predicted_total"]),
            "seg_prompt": round(d["prompt_seconds_total"], 1), "seg_generar": round(d["tokens_predicted_seconds_total"], 1),
            **r}


def table(rows: list[dict]) -> str:
    out = ["| Motor | Agente | Aciertos | Tiempo total | Tokens procesados (prompt / salida) | Fallan |",
           "|---|---|---|---|---|---|"]
    keys = list(dict.fromkeys((r["motor"], r["agente"]) for r in rows))
    for motor, agent in keys:
        rs = [r for r in rows if r["motor"] == motor and r["agente"] == agent]
        fails = ", ".join(r["tarea"] for r in rs if not r["ok"]) or "-"
        out.append(f"| {motor} | {agent} | {sum(r['ok'] for r in rs)}/{len(rs)} | "
                   f"{sum(r['segundos'] for r in rs) / 60:.1f} min | "
                   f"{sum(r['tokens_prompt'] for r in rs)} / {sum(r['tokens_salida'] for r in rs)} | {fails} |")
    return "\n".join(out)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--motor", default="27b-q4", help=f"uno o varios separados por comas: {', '.join(MOTORES)}")
    ap.add_argument("-a", "--agentes", default="skynet,hermes")
    ap.add_argument("-t", "--tareas", default="factura,planificador,appids", help=", ".join(ALL_TASKS))
    ap.add_argument("--turnos", type=int, default=40)
    ap.add_argument("--no-motor", action="store_true", help="usar el llama-server que ya esté encendido")
    a = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "data" / "bench-hermes" / stamp
    out_dir.mkdir(parents=True)
    rows: list[dict] = []
    res = HERE / "out" / f"{stamp}.json"
    res.parent.mkdir(exist_ok=True)
    for motor in a.motor.split(","):
        if not a.no_motor:
            start_engine(motor, out_dir)
        for name in a.tareas.split(","):
            for agent in a.agentes.split(","):
                print(f">> {motor} · {agent} · {name}", flush=True)
                r = await run_one(agent, ALL_TASKS[name], motor, out_dir, a.turnos)
                print(f"   {'OK ' if r['ok'] else 'MAL'} {r['estado']} {r['segundos']} s "
                      f"tokens {r['tokens_prompt']}/{r['tokens_salida']} · {r['verificador'] or r['error'] or ''}",
                      flush=True)
                rows.append(r)
                res.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    if not a.no_motor:
        stop_engine()
    print("\n" + table(rows) + f"\n\nDetalle: {res}\nRepos de cada ejecución: {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
