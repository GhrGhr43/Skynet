"""Informe HTML autocontenido: perfil por capacidades, con el detalle de cada prueba."""
from __future__ import annotations

import html as h
import json

from .pruebas import CATEGORIAS

CSS = """
:root{--bg:#0f1115;--panel:#171a21;--txt:#e6e8ee;--sub:#9aa3b2;--borde:#2a2f3a;--ok:#2fb67c;--mal:#e5534b;--gris:#596273}
@media (prefers-color-scheme: light){:root{--bg:#f6f7f9;--panel:#fff;--txt:#1b1f27;--sub:#5b6472;--borde:#e2e5ea;--gris:#a3abb8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}h1{font-size:22px;margin:0 0 4px}p.sub{color:var(--sub);margin:0 0 20px}
.tabla{overflow-x:auto;background:var(--panel);border:1px solid var(--borde);border-radius:12px}
table{border-collapse:collapse;width:100%}th,td{padding:10px 12px;border-bottom:1px solid var(--borde);text-align:left;white-space:nowrap}
th{color:var(--sub);font-weight:600;font-size:13px}td.n{font-variant-numeric:tabular-nums}
.barra{display:inline-block;height:8px;border-radius:4px;background:var(--ok);vertical-align:middle;margin-right:8px}
.na{color:var(--gris);font-size:13px}.mejor{font-weight:700}
details{background:var(--panel);border:1px solid var(--borde);border-radius:12px;margin-top:12px;padding:10px 14px}
summary{cursor:pointer;font-weight:600}.det td{white-space:normal;font-size:13px}.e-ok{color:var(--ok)}.e-fallo,.e-error{color:var(--mal)}
"""


def _celda(nota, estado) -> str:
    if nota is None:
        txt = {"no_compatible": "no compatible", "no_probado": "no probado"}.get(estado, "—")
        return f'<span class="na">{txt}</span>'
    pct = round(nota * 100)
    color = "var(--ok)" if pct >= 80 else "#d6a23b" if pct >= 50 else "var(--mal)"
    return f'<span class="barra" style="width:{max(pct * 0.6, 2):.0f}px;background:{color}"></span>{pct} %'


def resumen(datos: dict) -> dict[str, dict[str, tuple[float | None, str]]]:
    out: dict[str, dict[str, tuple[float | None, str]]] = {}
    for mod, d in datos["modelos"].items():
        for cat in CATEGORIAS:
            ps = [p for p in d["pruebas"].values() if p["categoria"] == cat]
            if not ps:
                continue
            notas = [p["nota"] for p in ps if p["nota"] is not None]
            out.setdefault(cat, {})[mod] = (sum(notas) / len(notas) if notas else None, ps[0]["estado"])
    return out


def html(datos: dict) -> str:
    mods = list(datos["modelos"])
    res = resumen(datos)
    filas = []
    for cat, por_mod in res.items():
        mejor = max((v[0] for v in por_mod.values() if v[0] is not None), default=None)
        celdas = "".join(
            f'<td class="n{" mejor" if mejor is not None and por_mod.get(m, (None,))[0] == mejor and len(mods) > 1 else ""}">'
            f'{_celda(*por_mod.get(m, (None, "no_probado")))}</td>' for m in mods)
        filas.append(f"<tr><td>{h.escape(CATEGORIAS[cat])}</td>{celdas}</tr>")
    detalles = []
    for m in mods:
        d = datos["modelos"][m]
        rows = "".join(
            f'<tr><td>{h.escape(CATEGORIAS[p["categoria"]])}</td><td>{h.escape(p["titulo"])}</td>'
            f'<td class="n">{_celda(p["nota"], p["estado"])}'
            f'{"" if p.get("min") in (None, p.get("max")) else f" ({round(p["min"]*100)}–{round(p["max"]*100)})"}</td>'
            f'<td class="e-{p["estado"]}">{h.escape(p["estado"])}</td><td>{h.escape(p["detalle"])}</td>'
            f'<td>{h.escape(json.dumps(p.get("metricas", {}), ensure_ascii=False))}</td></tr>'
            for p in d["pruebas"].values())
        detalles.append(
            f'<details><summary>{h.escape(m)}</summary><p class="sub">{h.escape(d["url"])} · ajustes '
            f'{h.escape(json.dumps(d.get("ajustes", {}), ensure_ascii=False))}</p><div class="tabla"><table class="det">'
            f"<tr><th>Capacidad</th><th>Prueba</th><th>Nota</th><th>Estado</th><th>Detalle</th><th>Métricas</th></tr>"
            f"{rows}</table></div></details>")
    cab = "".join(f"<th>{h.escape(m)}</th>" for m in mods)
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>Comparador de modelos</title><style>{CSS}</style>'
            f'</head><body><main><h1>Comparador de modelos</h1><p class="sub">{h.escape(datos["fecha"])} · modo '
            f'{h.escape(datos["modo"])} · {datos["repeticiones"]} repetición(es) · {h.escape(datos["equipo"]["so"])}</p>'
            f'<div class="tabla"><table><tr><th>Capacidad</th>{cab}</tr>{"".join(filas)}</table></div>'
            f'{"".join(detalles)}</main></body></html>')
