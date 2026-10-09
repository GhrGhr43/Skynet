"""Comparador de modelos locales.

    python -m comparador listar
    python -m comparador ejecutar                        # elegir modelos en un menú, modo rápido
    python -m comparador ejecutar -m qwen3.8-27b,gemma-4-26b --modo completo -n 2
    python -m comparador ejecutar --modo especialidad --categorias autonomo,herramientas
    python -m comparador informe resultados/xxx.json     # regenera el HTML

Modelos: todos los GGUF de LM Studio y Strata (los arranca el comparador, uno a uno, con
llama-server), los del servidor de LM Studio si está encendido, y los de modelos.toml.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
import tomllib
import webbrowser
from datetime import datetime
from pathlib import Path

from . import motor
from .cliente import ErrorModelo, Modelo, modelos_del_servidor
from .informe import html
from .pruebas import CATEGORIAS, PRUEBAS, Resultado

RAIZ = Path(__file__).resolve().parent.parent
LMSTUDIO = "http://127.0.0.1:1234/v1"


def _cfg() -> dict:
    p = RAIZ / "modelos.toml"
    return tomllib.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def cargar_modelos() -> dict[str, Modelo]:
    """Modelos por nombre. Los GGUF llevan `.gguf` (el comparador los arranca él)."""
    out: dict[str, Modelo] = {}
    cfg = _cfg()
    ajustes = cfg.get("ajustes", {})
    gg = cfg.get("gguf", {})
    for g in motor.buscar(gg.get("carpetas")):
        g.args = list(gg.get("args", {}).get(g.nombre, []))
        m = Modelo(g.nombre, f"http://127.0.0.1:{motor.PUERTO}/v1", etiqueta=g.nombre, extra=ajustes.get(g.nombre, {}))
        m.gguf = g
        out[g.nombre] = m
    lm = cfg.get("lmstudio", {}).get("url", LMSTUDIO)
    for mid in modelos_del_servidor(lm):
        if "embed" not in mid.lower():
            out[f"lmstudio:{mid}"] = Modelo(mid, lm, etiqueta=f"lmstudio:{mid}", extra=ajustes.get(mid, {}))
    for nombre, d in cfg.get("modelos", {}).items():
        out[nombre] = Modelo(d.get("modelo", nombre), d["url"], d.get("api_key", "local"), nombre,
                             extra=d.get("extra", {}))
    return out


def elegir(modelos: dict[str, Modelo]) -> list[str]:
    nombres = list(modelos)
    for i, n in enumerate(nombres, 1):
        print(f"  {i:2}. {n}  ({_desc(modelos[n])})")
    sel = input("Números separados por comas (p. ej. 1,3): ").strip()
    return [nombres[int(x) - 1] for x in sel.split(",") if x.strip().isdigit() and 0 < int(x) <= len(nombres)]


def _desc(m: Modelo) -> str:
    g = getattr(m, "gguf", None)
    return g.descripcion() if g else m.url


def seleccionar_pruebas(modo: str, categorias: list[str] | None):
    if modo == "rapido":
        return [p for p in PRUEBAS if p.rapida]
    if modo == "especialidad":
        if not categorias:
            sys.exit(f"Con --modo especialidad indica --categorias. Disponibles: {', '.join(CATEGORIAS)}")
        return [p for p in PRUEBAS if p.categoria in categorias]
    return list(PRUEBAS)


def ejecutar(args) -> None:
    modelos = cargar_modelos()
    if not modelos:
        sys.exit("No encuentro modelos: ni GGUF en .lmstudio\\models ni servidores. Revisa modelos.toml.")
    nombres = args.modelos.split(",") if args.modelos else elegir(modelos)
    faltan = [n for n in nombres if n not in modelos]
    if faltan:
        sys.exit(f"Modelos desconocidos: {', '.join(faltan)}. Usa `listar`.")
    pruebas = seleccionar_pruebas(args.modo, args.categorias.split(",") if args.categorias else None)
    datos = {"fecha": datetime.now().isoformat(timespec="seconds"), "modo": args.modo, "repeticiones": args.n,
             "equipo": {"so": platform.platform(), "cpu": platform.processor()}, "modelos": {}}
    if any(getattr(modelos[n], "gguf", None) for n in nombres) and motor.puerto_ocupado(8090):
        print("AVISO: el motor local de Skynet (puerto 8090) está encendido y ocupa VRAM. Apágalo en Ajustes de "
              "Skynet o los resultados de velocidad saldrán peor.")
    for n in nombres:
        m = modelos[n]
        print(f"\n== {n}  ({_desc(m)})", flush=True)
        res_modelo = {"url": m.url, "ajustes": m.extra, "pruebas": {}}
        g = getattr(m, "gguf", None)
        if g:
            try:
                srv = motor.Servidor(g, RAIZ / "resultados" / "logs").__enter__()
            except RuntimeError as e:
                print(f"  ERR {e}")
                res_modelo["error"] = str(e)
                res_modelo["pruebas"] = {p.id: {"categoria": p.categoria, "titulo": p.titulo, "nota": None, "min": None,
                                                "max": None, "estado": "error", "detalle": "el modelo no arrancó",
                                                "metricas": {}} for p in pruebas}
                datos["modelos"][n] = res_modelo
                continue
            res_modelo["ajustes"] = {**m.extra, "archivo": str(g.ruta), "flags": " ".join(motor.argumentos(g, g.mtp)[4:]),
                                     "arranque_s": round(srv.segundos_arranque)}
            print(f"  arrancado en {srv.segundos_arranque:.0f} s", flush=True)
        try:
            _pasar(m, pruebas, args.n, res_modelo)
        finally:
            if g:
                srv.parar()
        datos["modelos"][n] = res_modelo
    guardar(datos, args.no_abrir)


def _pasar(m: Modelo, pruebas, repeticiones: int, res_modelo: dict) -> None:
    for p in pruebas:
        notas, ultimo = [], None
        for i in range(repeticiones):
            t0 = time.monotonic()
            try:
                r = p.fn(m)
            except ErrorModelo as e:
                r = Resultado(0, "error", str(e)[:300])
            except Exception as e:  # una prueba rota no para el resto
                r = Resultado(0, "error", f"{type(e).__name__}: {e}"[:300])
            r.metricas.setdefault("segundos", round(time.monotonic() - t0, 1))
            ultimo = r
            if r.nota is not None:
                notas.append(r.nota)
            if r.estado in ("no_compatible", "no_probado"):
                break
        nota = statistics.mean(notas) if notas else None
        res_modelo["pruebas"][p.id] = {
            "categoria": p.categoria, "titulo": p.titulo, "nota": nota,
            "min": min(notas) if notas else None, "max": max(notas) if notas else None,
            "estado": ultimo.estado, "detalle": ultimo.detalle, "metricas": ultimo.metricas}
        marca = {"ok": "OK ", "fallo": "MAL", "error": "ERR"}.get(ultimo.estado, "-- ")
        print(f"  {marca} {p.categoria:13} {p.titulo[:48]:48} "
              f"{'' if nota is None else f'{nota * 100:5.0f} %'}  {ultimo.detalle[:70]}", flush=True)


def guardar(datos: dict, no_abrir: bool = False) -> None:
    carpeta = RAIZ / "resultados"
    carpeta.mkdir(exist_ok=True)
    base = carpeta / datetime.now().strftime("%Y%m%d-%H%M%S")
    base.with_suffix(".json").write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    base.with_suffix(".html").write_text(html(datos), encoding="utf-8")
    print(f"\nInforme: {base.with_suffix('.html')}")
    if not no_abrir:
        webbrowser.open(base.with_suffix(".html").as_uri())


def main() -> None:
    ap = argparse.ArgumentParser(prog="comparador", description="Compara modelos de IA locales por capacidades.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("listar", help="modelos disponibles")
    e = sub.add_parser("ejecutar", help="pasar la batería")
    e.add_argument("-m", "--modelos", help="nombres separados por comas (sin esto, menú)")
    e.add_argument("--modo", choices=["rapido", "completo", "especialidad"], default="rapido")
    e.add_argument("--categorias", help=f"para especialidad: {','.join(CATEGORIAS)}")
    e.add_argument("-n", type=int, default=1, help="repeticiones por prueba (variación)")
    e.add_argument("--no-abrir", action="store_true")
    i = sub.add_parser("informe", help="regenerar el HTML de un .json")
    i.add_argument("json")
    a = ap.parse_args()
    if a.cmd == "listar":
        for n, m in cargar_modelos().items():
            print(f"{n}  ({_desc(m)})")
    elif a.cmd == "ejecutar":
        ejecutar(a)
    else:
        p = Path(a.json)
        p.with_suffix(".html").write_text(html(json.loads(p.read_text(encoding="utf-8"))), encoding="utf-8")
        print(p.with_suffix(".html"))


if __name__ == "__main__":
    main()
