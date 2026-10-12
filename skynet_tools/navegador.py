"""Comprueba páginas HTML del repo en un navegador aislado, sin red ni perfil personal."""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent

mcp = MCPServer("navegador")
ROOT = Path.cwd()


@mcp.tool()
def comprobar_html(path: str, acciones: list[dict[str, str]] | None = None, ancho: int = 1280,
                   alto: int = 800, segundos: float = 2, captura: bool = False) -> CallToolResult:
    """Abre un HTML del repo en Chrome sin ventana, comprueba errores JS y devuelve texto y controles.
    acciones: hasta 8 objetos {tipo:'clic',selector:'#boton'} o {tipo:'rellenar',selector:'#campo',valor:'texto'}.
    Permite probar la interfaz antes de terminar. captura=true devuelve además una imagen (requiere visión).
    No tiene red ni acceso a archivos fuera del repo; el perfil temporal se descarta al terminar.
    """
    target = (ROOT / path).resolve()
    if not target.is_relative_to(ROOT.resolve()) or target.suffix.lower() not in (".html", ".htm"):
        raise ToolError("Usa un archivo HTML dentro del repo autorizado.")
    if not target.is_file():
        raise ToolError("No existe el archivo HTML.")
    actions = acciones or []
    if len(actions) > 8 or any(a.get("tipo") not in ("clic", "rellenar") or not a.get("selector") for a in actions):
        raise ToolError("Hasta 8 acciones de tipo clic o rellenar, con selector CSS.")
    if not 320 <= ancho <= 1920 or not 320 <= alto <= 1200 or not 0 <= segundos <= 10:
        raise ToolError("Ancho 320–1920, alto 320–1200 y espera 0–10 segundos.")
    node = shutil.which("node")
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
    if not node and (bundled / "bin/node.exe").exists():
        node = str(bundled / "bin/node.exe")
    if not node:
        raise ToolError("Falta Node.js para la comprobación del navegador.")
    env = os.environ.copy()
    if (bundled / "node_modules/playwright").is_dir():
        env["NODE_PATH"] = str(bundled / "node_modules")
    payload = {"root": str(ROOT.resolve()), "path": str(target), "acciones": actions,
               "ancho": ancho, "alto": alto, "segundos": segundos, "captura": captura}
    try:
        result = subprocess.run([node, str(Path(__file__).with_name("navegador.cjs"))],
                                input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=env, timeout=90,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            raise ToolError(result.stderr.strip()[-1000:] or "No se pudo abrir el navegador.")
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError) as e:
        raise ToolError(f"No se pudo comprobar la página: {e}") from None
    screenshot = data.pop("imagen", None)
    content = [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]
    if screenshot:
        content.append(ImageContent(type="image", data=screenshot, mimeType="image/jpeg"))
    return CallToolResult(content=content, isError=bool(data.get("errores")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    global ROOT
    ROOT = Path(args.root).resolve()
    logging.basicConfig(level=logging.WARNING)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
