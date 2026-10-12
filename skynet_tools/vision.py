"""MCP de imágenes y capturas locales. Devuelve ImageContent, nunca base64 como texto."""
from __future__ import annotations

import argparse
import io
import logging
import sys
import warnings
from pathlib import Path

from PIL import Image, ImageGrab, ImageOps, UnidentifiedImageError
from mcp.server.mcpserver import MCPServer, Image as MCPImage
from mcp.server.mcpserver.exceptions import ToolError

mcp = MCPServer("vision")
MAX_BYTES = 5_000_000
MAX_PIXELS = 20_000_000
MAX_LADO = 1280
ROOT: Path | None = None
SOLO_REPO = True


def normalizar(data: bytes) -> tuple[bytes, int, int]:
    """Quita metadatos y limita resolución: no se llena el contexto con una captura 4K."""
    if not data or len(data) > MAX_BYTES:
        raise ValueError("La imagen debe ocupar como máximo 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.format not in ("PNG", "JPEG", "WEBP"):
                    raise ValueError("Usa una imagen PNG, JPEG o WebP.")
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError("La imagen supera los 20 megapíxeles.")
                im = ImageOps.exif_transpose(original).convert("RGB")
                im.thumbnail((MAX_LADO, MAX_LADO))
                out = io.BytesIO()
                im.save(out, format="JPEG", quality=88)
                return out.getvalue(), im.width, im.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("El archivo no es una imagen válida.") from None


@mcp.tool()
def leer_imagen(path: str) -> MCPImage:
    """Mira una imagen PNG/JPEG/WebP del PC o del repo. Reduce a 1280 px y quita metadatos."""
    p = Path(path)
    if not p.is_absolute():
        if ROOT is None:
            raise ToolError("Usa una ruta absoluta cuando no hay repo.")
        p = ROOT / p
    p = p.resolve()
    if SOLO_REPO and (ROOT is None or (p != ROOT and ROOT not in p.parents)):
        raise ToolError("La imagen está fuera del repo autorizado.")
    try:
        if p.stat().st_size > MAX_BYTES:
            raise ValueError("La imagen supera los 5 MB.")
        data, _, _ = normalizar(p.read_bytes())
        return MCPImage(data=data, format="jpeg")
    except (OSError, ValueError) as e:
        raise ToolError(str(e)) from None


@mcp.tool()
def capturar_pantalla(ventana: bool = True, titulo: str = "") -> MCPImage:
    """Mira una captura actual. Por defecto solo la ventana activa; ventana=false captura el escritorio.
    titulo permite elegir una ventana por una parte de su título (debe coincidir con una sola).
    Úsala al revisar una interfaz o juego abierto, después de cambios relevantes. No captura continuamente.
    """
    if SOLO_REPO:
        raise ToolError("Capturar requiere el modo «Ver mi PC» o superior.")
    if sys.platform != "win32":
        raise ToolError("Las capturas están disponibles en Windows.")
    try:
        if ventana:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsIconic.argtypes = [wintypes.HWND]
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            hwnd = user32.GetForegroundWindow()
            if titulo:
                encontrados = []
                callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
                def visitar(handle, _):
                    buf = ctypes.create_unicode_buffer(1024)
                    user32.GetWindowTextW(handle, buf, len(buf))
                    if user32.IsWindowVisible(handle) and titulo.casefold() in buf.value.casefold():
                        encontrados.append(handle)
                    return True
                user32.EnumWindows(callback_type(visitar), 0)
                if len(encontrados) != 1:
                    raise ValueError(f"Hay {len(encontrados)} ventanas con ese título; indica uno más concreto.")
                hwnd = encontrados[0]
            if not hwnd or user32.IsIconic(hwnd):
                raise ValueError("No hay una ventana activa visible.")
            im = ImageGrab.grab(window=hwnd)
        else:
            im = ImageGrab.grab(all_screens=True)
        im = im.convert("RGB")
        im.thumbnail((MAX_LADO, MAX_LADO))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=88)
        return MCPImage(data=out.getvalue(), format="jpeg")
    except (OSError, ValueError) as e:
        raise ToolError(f"No se pudo capturar: {e}") from None


def main() -> None:
    global ROOT, SOLO_REPO
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="")
    ap.add_argument("--modo", choices=("repo", "lectura", "editar", "total"), default="repo")
    a = ap.parse_args()
    ROOT = Path(a.root).resolve() if a.root else None
    SOLO_REPO = a.modo == "repo"
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
