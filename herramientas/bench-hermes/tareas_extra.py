"""Tareas extra para comparar agentes: las que no son de código.

`appids`: investigar en Internet y dejar el resultado en un archivo. Se comprueba sin LLM
(los AppID de Steam son estables) y exige buscar: el modelo no se los sabe de memoria todos.
"""
from __future__ import annotations

import json
from pathlib import Path

APPIDS = {
    "The Farmer Was Replaced": 2060160,
    "Factorio": 427520,
    "Stardew Valley": 413150,
    "Hollow Knight": 367520,
}

APPIDS_TASK = {
    "name": "appids",
    "internet": True,
    "prompt": ("Busca en Internet el AppID de Steam de estos juegos: " + ", ".join(APPIDS) + ". "
               "Crea `appids.json` en la raíz del repo con un objeto {nombre del juego: AppID como número}, "
               "usando exactamente esos nombres, y `fuentes.md` con el enlace de la tienda de Steam de cada uno. "
               "Comprueba cada AppID en una fuente; no lo pongas de memoria."),
    "files": {"README.md": "# Investigación\n"},
}


def check_appids(repo: Path) -> tuple[bool, str]:
    f = repo / "appids.json"
    if not f.exists():
        return False, "no existe appids.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except ValueError as e:
        return False, f"JSON inválido: {e}"
    bien = [n for n, v in APPIDS.items() if str(data.get(n)) == str(v)]
    fuentes = (repo / "fuentes.md").read_text(encoding="utf-8", errors="replace") if (repo / "fuentes.md").exists() else ""
    enlaces = sum(f"/app/{v}" in fuentes for v in APPIDS.values())
    return len(bien) == len(APPIDS) and enlaces == len(APPIDS), f"{len(bien)}/{len(APPIDS)} AppID, {enlaces} enlaces"
