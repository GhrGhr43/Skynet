"""Adjuntos locales: referencias pequeñas en el historial, píxeles solo al llamar al modelo."""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from pathlib import Path
from typing import Any

from skynet_tools.vision import MAX_BYTES, normalizar

MAX_IMAGENES = 4
ID_RE = re.compile(r"^[0-9a-f]{64}$")


def ruta(data_dir: Path, ident: str) -> Path:
    if not isinstance(ident, str) or not ID_RE.fullmatch(ident):
        raise ValueError("Referencia de imagen inválida.")
    return data_dir / "imagenes" / (ident + ".jpg")


def guardar(data_dir: Path, adjuntos: Any) -> list[dict[str, Any]]:
    if not isinstance(adjuntos, list) or len(adjuntos) > MAX_IMAGENES:
        raise ValueError("Adjunta como máximo 4 imágenes por mensaje.")
    preparados = []
    for adj in adjuntos:
        if not isinstance(adj, dict):
            raise ValueError("Adjunto inválido.")
        url = adj.get("data_url")
        if not isinstance(url, str) or len(url) > MAX_BYTES * 4 // 3 + 100:
            raise ValueError("La imagen debe ocupar como máximo 5 MB.")
        match = re.fullmatch(r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", url)
        if not match:
            raise ValueError("Usa una imagen PNG, JPEG o WebP en base64.")
        try:
            data, w, h = normalizar(base64.b64decode(match[1], validate=True))
        except (binascii.Error, ValueError) as e:
            raise ValueError(f"Imagen inválida: {e}") from None
        ident = hashlib.sha256(data).hexdigest()
        nombre = str(adj.get("nombre") or "Imagen").replace("\\", "/").rsplit("/", 1)[-1][:100]
        preparados.append((data, {"id": ident, "nombre": nombre, "ancho": w, "alto": h}))
    for data, ref in preparados:
        p = ruta(data_dir, ref["id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(data)
    return [ref for _, ref in preparados]


def data_url(data_dir: Path, ident: str) -> str:
    p = ruta(data_dir, ident)
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def contenido(texto: str, refs: list[dict[str, Any]], data_dir: Path) -> str | list[dict[str, Any]]:
    if not refs:
        return texto
    partes = [{"type": "text", "text": texto}]
    for ref in refs:
        try:
            partes.append({"type": "image_url", "image_url": {"url": data_url(data_dir, ref["id"])}})
        except (OSError, ValueError, KeyError):
            partes.append({"type": "text", "text": "[Imagen adjunta no disponible; no inventes su contenido.]"})
    return partes


def texto_de(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(p.get("text", "") if p.get("type") == "text" else "[imagen]" for p in content or [])
