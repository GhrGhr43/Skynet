"""Benchmark agéntico: el bucle real de Skynet (router -> agente -> gate -> MCP workspace) sobre
tareas de varios pasos, con verificador oculto. Funciona igual en el PC y en la nube.

Uso (desde C:\\Skynet):
    .venv\\Scripts\\python bench\\agentico.py                         # todos los modelos con clave
    .venv\\Scripts\\python bench\\agentico.py -m local,gemini -t factura,logs -n 2

Modelos: los perfiles de config/router.toml más los de bench/modelos_bench.toml (este manda).
Un perfil cuya clave (api_key_env) no está en el entorno se salta. Los extras de cada perfil
(temperature, top_p, extra_body...) se pasan tal cual a LiteLLM: son los "trucos" por modelo.
Resultados en bench/out/agentico-<fecha>.json y una tabla en pantalla.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from agentico_tareas import COMMON, TASKS  # noqa: E402
from skynet import gitops  # noqa: E402
from skynet.config import ModelProfile, load_settings  # noqa: E402
from skynet.router import Capabilities  # noqa: E402
from skynet.runtime import Runtime  # noqa: E402

PROFILE_FIELDS = set(ModelProfile.__dataclass_fields__)


def load_profiles() -> tuple[dict[str, dict], dict[str, dict]]:
    """Devuelve (perfiles, extras) mezclando router.toml y bench/modelos_bench.toml."""
    base = tomllib.loads((ROOT / "config" / "router.toml").read_text(encoding="utf-8")).get("modelos", {})
    extra_path = HERE / "modelos_bench.toml"
    bench = tomllib.loads(extra_path.read_text(encoding="utf-8")).get("modelos", {}) if extra_path.exists() else {}
    profiles, extras = {}, {}
    for name, d in {**base, **bench}.items():
        profiles[name] = {k: v for k, v in d.items() if k in PROFILE_FIELDS}
        extras[name] = dict(d.get("extra", {}))
    return profiles, extras


def make_completion(extras: dict[str, dict]):
    import litellm

    litellm.suppress_debug_info = True
    litellm.drop_params = True
    by_model: dict[str, dict] = {}

    async def completion(**kw):
        for k, v in by_model.get(kw["model"], {}).items():
            if k == "extra_body":
                kw["extra_body"] = {**(kw.get("extra_body") or {}), **v}
            else:
                kw[k] = v
        return await litellm.acompletion(**kw)

    return completion, by_model


def build_repo(task: dict, dest: Path) -> None:
    for rel, text in {**COMMON, **task["files"]}.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    gitops.ensure_repo(dest)
    gitops.commit_all(dest, "inicial")


def hidden_check(task: dict, repo: Path) -> tuple[bool, str]:
    hd = repo / "_verificador_oculto"
    hd.mkdir(exist_ok=True)
    (hd / "conftest.py").write_text(COMMON["tests/conftest.py"], encoding="utf-8")
    (hd / "test_oculto.py").write_text(task["hidden"], encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(hd), "tests"],
                           cwd=repo, capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip().splitlines()
        return r.returncode == 0, (out[-1] if out else "")
    except subprocess.TimeoutExpired:
        return False, "timeout (se cuelga)"


async def run_one(model: str, profile: dict, by_model: dict, completion, task: dict, max_turns: int) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix=f"skb-{task['name']}-"))
    try:
        home, repo = tmp / "home", tmp / "repo"
        (home / "config").mkdir(parents=True)
        for f in ("skynet.toml", "permisos.toml", "router.toml"):
            shutil.copy(ROOT / "config" / f, home / "config" / f)
        (home / "config" / "repos.toml").write_text(
            f'[repos.bench]\nruta = "{repo.as_posix()}"\nverificador = "python -m pytest -q"\n'
            'ejecutar = ["python", "pytest"]\n', encoding="utf-8")
        build_repo(task, repo)
        settings = load_settings(home)
        settings.models[model] = ModelProfile(nombre=model, **profile)
        settings.budget_eur = 100.0
        rt = Runtime(settings, completion_fn=completion)
        rt.access.nube_activada.add(model)
        task_row = rt.store.create_task(title=task["name"], goal=task["prompt"], agent="skynet", repo="bench",
                                        status="en_curso", capabilities={"capacidades": {"force": model}})

        async def asker(*_a):
            return "s"

        t0 = time.monotonic()
        run = await rt.agent_step(rt.store.get_task(task_row.id), "chat", asker=asker, max_turns=max_turns)
        secs = time.monotonic() - t0
        o = run.outcome
        ok, line = hidden_check(task, repo)
        touched_tests = [f for f in o.files_touched if f.replace("\\", "/").startswith("tests/")]
        rt.store.close()
        return {"modelo": model, "litellm": profile["litellm"], "tarea": task["name"], "ok": ok, "verificador": line,
                "estado": o.status, "turnos": o.turns, "herramientas": o.tool_calls, "denegadas": o.denied,
                "tokens_in": o.tokens_in, "tokens_out": o.tokens_out, "coste_eur": round(o.cost_eur, 5),
                "segundos": round(secs, 1), "error": o.error, "tests_tocados": touched_tests,
                "respuesta": o.final_text[:600]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def table(rows: list[dict]) -> str:
    models = sorted({r["modelo"] for r in rows}, key=lambda m: [r["modelo"] for r in rows].index(m))
    out = ["| Modelo | Aciertos | Turnos medios | Tokens in/out | Coste € | Segundos |", "|---|---|---|---|---|---|"]
    for m in models:
        rs = [r for r in rows if r["modelo"] == m]
        n = len(rs)
        ok = sum(r["ok"] for r in rs)
        fails = ", ".join(sorted({r["tarea"] for r in rs if not r["ok"]})) or "-"
        out.append(f"| {m} | {ok}/{n} (falla: {fails}) | {sum(r['turnos'] for r in rs) / n:.1f} | "
                   f"{sum(r['tokens_in'] for r in rs)}/{sum(r['tokens_out'] for r in rs)} | "
                   f"{sum(r['coste_eur'] for r in rs):.3f} | {sum(r['segundos'] for r in rs):.0f} |")
    return "\n".join(out)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--modelos", help="perfiles separados por comas (por defecto, todos con clave)")
    ap.add_argument("-t", "--tareas", help="tareas separadas por comas (por defecto, todas)")
    ap.add_argument("-n", "--repeticiones", type=int, default=1)
    ap.add_argument("--turnos", type=int, default=40)
    a = ap.parse_args()

    profiles, extras = load_profiles()
    names = a.modelos.split(",") if a.modelos else [n for n in profiles if n not in ("cloud", "omniroute")]
    tasks = [t for t in TASKS if not a.tareas or t["name"] in a.tareas.split(",")]
    completion, by_model = make_completion(extras)
    rows: list[dict] = []
    for name in names:
        if name not in profiles:
            print(f"!! perfil desconocido: {name}")
            continue
        prof = profiles[name]
        if prof.get("api_key_env") and not os.environ.get(prof["api_key_env"]):
            print(f"-- {name}: salto, falta {prof['api_key_env']}")
            continue
        by_model[prof["litellm"]] = extras.get(name, {})
        for task in tasks:
            for i in range(a.repeticiones):
                print(f">> {name} · {task['name']} · {i + 1}/{a.repeticiones}", flush=True)
                try:
                    r = await run_one(name, prof, by_model, completion, task, a.turnos)
                except Exception as e:  # un modelo roto no para el resto
                    r = {"modelo": name, "litellm": prof["litellm"], "tarea": task["name"], "ok": False,
                         "verificador": "", "estado": "excepcion", "turnos": 0, "herramientas": 0, "denegadas": 0,
                         "tokens_in": 0, "tokens_out": 0, "coste_eur": 0, "segundos": 0,
                         "error": f"{type(e).__name__}: {e}"[:500], "tests_tocados": [], "respuesta": ""}
                print(f"   {'OK ' if r['ok'] else 'MAL'} {r['estado']} turnos={r['turnos']} "
                      f"tok={r['tokens_in']}/{r['tokens_out']} {r['segundos']}s {r['verificador'] or r['error'] or ''}",
                      flush=True)
                rows.append(r)
    outdir = HERE / "out"
    outdir.mkdir(exist_ok=True)
    path = outdir / f"agentico-{datetime.now():%Y%m%d-%H%M}.json"
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + table(rows) + f"\n\nDetalle: {path}")


if __name__ == "__main__":
    asyncio.run(main())
