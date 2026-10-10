"""Memoria que el modelo escribe por su cuenta, al estilo de Hermes (D20).

Dos archivos que ya entran siempre en el contexto (context.py): `memoria/USER.md` (preferencias de Daniel)
y `memoria/MEMORY.md` (hechos estables del entorno), con tope de tamaño. El modelo los cambia con la
herramienta interna `memoria` (guardar, reemplazar, quitar) sin pedir permiso, como Hermes; cada cambio queda
en el registro. Es interna y no un servidor MCP: escribe el estado del propio Skynet y así no añade el
arranque de un servidor a cada mensaje. No se ofrece en tareas largas ni a agentes externos.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .propuestas import CABECERAS, MAX_MEMORIA_BYTES, memoria_file

NOMBRE = "memoria"
DESTINOS = {"usuario": "USER", "entorno": "MEMORY"}
# Lo que parece un secreto no se guarda: la memoria va en cada prompt y se lee a simple vista.
SECRETO = re.compile(r"(contrase[ñn]a|password|passwd|api[_ -]?key|token|secret)\s*[:=]|sk-[A-Za-z0-9]{16,}|"
                     r"ghp_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY", re.IGNORECASE)

ESQUEMA = {
    "type": "function",
    "function": {
        "name": NOMBRE,
        "description": ("Memoria que dura entre conversaciones (la ves arriba, en «Memoria» y «Preferencias del "
                        "usuario»). Guarda por tu cuenta preferencias o correcciones de Daniel (destino usuario) y "
                        "hechos estables de su PC o sus proyectos (destino entorno). Una frase corta por entrada."),
        "parameters": {
            "type": "object",
            "properties": {
                "accion": {"type": "string", "enum": ["guardar", "reemplazar", "quitar"]},
                "destino": {"type": "string", "enum": list(DESTINOS)},
                "texto": {"type": "string", "description": "Entrada a guardar, o texto de la entrada a reemplazar o quitar."},
                "nuevo": {"type": "string", "description": "Solo con reemplazar: la entrada nueva."},
            },
            "required": ["accion", "destino", "texto"],
        },
    },
}

PROMPT = """## Memoria
Tienes memoria entre conversaciones (secciones «Memoria» y «Preferencias del usuario»). Usa la herramienta
`memoria` por tu cuenta, sin preguntar, cuando Daniel te diga una preferencia, te corrija o te cuente algo
estable de su entorno, y cuando descubras algo que te ahorraría trabajo la próxima vez. No guardes lo que solo
sirve para esta tarea ni secretos. Si está llena, quita o fusiona entradas viejas."""


def _entradas(lineas: list[str]) -> list[int]:
    """Índices de las líneas que son entradas («- texto»). El resto (cabeceras, notas escritas a mano) no se toca."""
    return [i for i, l in enumerate(lineas) if l.startswith("- ")]


def aplicar(home: Path, args: dict[str, Any]) -> tuple[bool, str]:
    """Ejecuta la herramienta. Devuelve (cambió algo, texto para el modelo)."""
    accion, destino = str(args.get("accion", "")), str(args.get("destino", ""))
    texto = " ".join(str(args.get("texto", "")).split())
    nuevo = " ".join(str(args.get("nuevo", "")).split())
    if destino not in DESTINOS or accion not in ("guardar", "reemplazar", "quitar") or not texto:
        return False, "ERROR: usa accion guardar|reemplazar|quitar, destino usuario|entorno y un texto."
    if SECRETO.search(texto) or SECRETO.search(nuevo):
        return False, "ERROR: eso parece un secreto (contraseña, clave o token); no se guarda en memoria."
    dest = DESTINOS[destino]
    f = memoria_file(home, dest)
    lineas = (f.read_text(encoding="utf-8", errors="replace") if f.is_file() else CABECERAS[dest]).splitlines()
    idx = _entradas(lineas)
    listado = "\nEntradas:\n" + "\n".join(lineas[i] for i in idx) if idx else ""
    if accion == "guardar":
        if any(texto.lower() == lineas[i][2:].strip().lower() for i in idx):
            return False, "Ya estaba guardado."
        lineas.append(f"- {texto}")
    else:
        hit = [i for i in idx if texto.lower() in lineas[i].lower()]
        if len(hit) != 1:
            return False, f"ERROR: «{texto}» coincide con {len(hit)} entradas; usa un trozo que identifique solo una.{listado}"
        if accion == "quitar":
            lineas.pop(hit[0])
        elif not nuevo:
            return False, "ERROR: reemplazar necesita `nuevo`."
        else:
            lineas[hit[0]] = f"- {nuevo}"
    contenido = "\n".join(lineas).rstrip() + "\n"
    tam = len(contenido.encode("utf-8"))
    if tam > MAX_MEMORIA_BYTES:
        return False, (f"ERROR: {f.name} pasaría de {MAX_MEMORIA_BYTES} bytes ({tam}). Quita o fusiona entradas "
                       f"antes (accion quitar o reemplazar).{listado}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(contenido, encoding="utf-8")
    return True, f"Hecho ({accion} en {f.name}: {len(_entradas(lineas))} entradas, {tam}/{MAX_MEMORIA_BYTES} bytes)."
