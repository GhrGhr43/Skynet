"""Servidor MCP `sistema`: archivos y programas de todo el PC (modos «Ver mi PC», «Ver y editar», «Control total»).

Se lanza con `python -m skynet_tools.sistema --home <carpeta de usuario>`. Las rutas relativas son
relativas a esa carpeta. Este servidor NO decide qué se permite: lo decide el permission gate de
Skynet según el modo del modelo, antes de cada llamada. Por eso solo se arranca cuando el modelo
de la tarea tiene un modo distinto de «Solo repo».
"""
from __future__ import annotations

import argparse
import fnmatch
import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

MAX_OUTPUT = 12000
MAX_LIST = 400

mcp = MCPServer(
    "sistema",
    instructions="Archivos y programas de todo el PC del usuario (Windows). Úsalo solo si la tarea lo necesita.",
)
HOME: Path = Path.home()


def _path(path: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(path or ".")))
    return p if p.is_absolute() else HOME / p


def _clip(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n... [{len(text) - limit} caracteres omitidos] ...\n" + text[-half:]


@mcp.tool()
def read_file(path: str, offset: int = 1, limit: int = 400) -> str:
    """Lee un archivo de texto de cualquier carpeta del PC (ruta absoluta, o relativa a la carpeta de usuario)."""
    target = _path(path)
    if not target.is_file():
        raise ToolError(f"No existe o no es un archivo: {target}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    offset = max(1, offset)
    chunk = lines[offset - 1: offset - 1 + max(1, limit)]
    body = "\n".join(f"{i:5d}| {line}" for i, line in enumerate(chunk, start=offset))
    tail = f"\n[... {len(lines)} líneas en total]" if offset - 1 + len(chunk) < len(lines) else ""
    return _clip(f"{target} ({len(lines)} líneas)\n{body}{tail}")


@mcp.tool()
def list_dir(path: str = ".", pattern: str = "*") -> str:
    """Lista una carpeta del PC (sin recursión). `pattern` filtra por nombre, p. ej. "*.exe"."""
    target = _path(path)
    if not target.is_dir():
        raise ToolError(f"No existe o no es una carpeta: {target}")
    out = []
    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError as e:
        raise ToolError(f"Sin permiso para listar {target}: {e}") from e
    for p in entries:
        if not fnmatch.fnmatch(p.name.lower(), pattern.lower()):
            continue
        try:
            out.append(f"{p.name}/" if p.is_dir() else f"{p.name}  ({p.stat().st_size} B)")
        except OSError:
            out.append(p.name)
        if len(out) >= MAX_LIST:
            out.append(f"... (más de {MAX_LIST}; usa pattern para filtrar)")
            break
    return f"{target}\n" + ("\n".join(out) or "(vacía)")


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Crea o sobrescribe un archivo de texto (crea las carpetas que falten)."""
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Escrito {target} ({len(content)} caracteres)"


@mcp.tool()
def edit_file(path: str, old: str, new: str) -> str:
    """Sustituye un fragmento exacto (y único) de un archivo de texto por otro."""
    target = _path(path)
    if not target.is_file():
        raise ToolError(f"No existe: {target}")
    text = target.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        raise ToolError(f"El fragmento aparece {n} veces; tiene que ser único")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"Editado {target}"


@mcp.tool()
def delete_file(path: str) -> str:
    """Borra un archivo (no carpetas). Siempre pide confirmación al usuario."""
    target = _path(path)
    if not target.is_file():
        raise ToolError(f"No existe o no es un archivo: {target}")
    target.unlink()
    return f"Borrado {target}"


@mcp.tool()
def run_command(command: str, cwd: str = ".", timeout_seg: int = 300) -> str:
    """Ejecuta un comando de PowerShell (Windows) en `cwd` y devuelve su salida. Máximo 30 minutos."""
    workdir = _path(cwd)
    if not workdir.is_dir():
        raise ToolError(f"La carpeta no existe: {workdir}")
    if os.name == "nt":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["bash", "-c", command]
    try:
        r = subprocess.run(argv, cwd=workdir, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=max(1, min(int(timeout_seg), 1800)), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ToolError(f"El comando superó {timeout_seg} s y se cortó") from None
    out = (r.stdout or "") + (f"\n[stderr]\n{r.stderr}" if r.stderr.strip() else "")
    return _clip(f"exit {r.returncode}\n{out.strip()}")


@mcp.tool()
def abrir(destino: str) -> str:
    """Abre un programa, archivo, carpeta o enlace con la aplicación asociada de Windows.
    Ejemplos: "steam://install/730" (instalar un juego de Steam por su AppID), "steam://run/730",
    "C:/Program Files (x86)/Steam/steam.exe", "https://...". No espera a que termine."""
    target = destino.strip()
    if not target:
        raise ToolError("Indica qué abrir")
    if "://" not in target:
        p = _path(target)
        if not p.exists():
            raise ToolError(f"No existe: {p}")
        target = str(p)
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]
    elif "://" in target:
        webbrowser.open(target)
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return f"Abierto: {target}"


# Plan B de instalar_steam (el principal está en steam.py, sin interfaz). Este script busca el diálogo (título «Install - …»
# o «Instalar - …», en cualquier idioma que empiece así) entre las ventanas de Steam y pulsa Intro.
_PULSAR_INSTALAR = r"""
Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
public static class W {
  public delegate bool P(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(P f, IntPtr l);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  public static IntPtr Find(string pat) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, l) => {
      if (!IsWindowVisible(h)) return true;
      var sb = new StringBuilder(256); GetWindowText(h, sb, 256);
      if (System.Text.RegularExpressions.Regex.IsMatch(sb.ToString(), pat)) { found = h; return false; }
      return true; }, IntPtr.Zero);
    return found; }
}
'@
Add-Type -AssemblyName System.Windows.Forms
$deadline = (Get-Date).AddSeconds(__SEG__)
while ((Get-Date) -lt $deadline) {
  $h = [W]::Find('^(Install|Instalar|Installer|Installieren|Installa)\b')
  if ($h -ne [IntPtr]::Zero) {
    [W]::ShowWindow($h, 9) | Out-Null; [W]::SetForegroundWindow($h) | Out-Null; Start-Sleep -Milliseconds 700
    [System.Windows.Forms.SendKeys]::SendWait('{ENTER}'); Start-Sleep -Seconds 2
    if ([W]::Find('^(Install|Instalar|Installer|Installieren|Installa)\b') -eq [IntPtr]::Zero) { 'pulsado'; exit 0 }
  }
  Start-Sleep -Milliseconds 800
}
'no_encontrado'
"""


def _pulsar_instalar(appid: int, seg: int) -> str:
    """Plan B: abre steam://install/<AppID> y pulsa Intro en el diálogo «Instalar»."""
    url = f"steam://install/{int(appid)}"
    if os.name != "nt":
        webbrowser.open(url)
        return "sin_dialogo"
    os.startfile(url)  # type: ignore[attr-defined]
    seg = max(10, min(int(seg), 180))
    script = _PULSAR_INSTALAR.replace("__SEG__", str(seg))
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=seg + 30, stdin=subprocess.DEVNULL)
    return "pulsado" if "pulsado" in (r.stdout or "") else "sin_dialogo"


@mcp.tool()
def instalar_steam(appid: int, esperar_seg: int = 90) -> str:
    """Instala un juego de Steam por su AppID (p. ej. 730 = Counter-Strike 2) sin que el usuario pulse nada:
    lo pone en la cola de descargas de Steam (reinicia Steam si no hay un juego abierto) y comprueba que empieza
    a descargarse. Si no, prueba el diálogo «Instalar» de Steam. No espera a que termine la descarga."""
    if int(appid) <= 0:
        raise ToolError("AppID no válido")
    from .steam import Entorno, install

    return install(int(appid), max(15, min(int(esperar_seg), 300)), Entorno(dialog=_pulsar_instalar))


@mcp.tool()
def desinstalar_steam(appid: int) -> str:
    """Desinstala un juego de Steam sin pulsar nada: cierra Steam, quita el juego de su biblioteca (manifiesto y
    carpeta) y vuelve a abrir Steam. No lo hace si hay un juego abierto. Si no sabes el AppID, búscalo."""
    if int(appid) <= 0:
        raise ToolError("AppID no válido")
    from .steam import uninstall

    return uninstall(int(appid))


@mcp.tool()
def buscar_archivo(nombre: str, limite: int = 20) -> str:
    """Busca archivos por nombre en todo el PC (C:, con Program Files; sin Windows, ProgramData ni AppData) con un índice:
    responde al instante. `nombre` es una o varias palabras del nombre, p. ej. "brotato exe" o "factura 2025".
    Devuelve ruta completa, tamaño y fecha de los más recientes. Solo mira nombres, no el contenido."""
    from . import indice

    edad = indice.edad_h(INDICE)
    if edad is None:
        indice.lanzar_actualizacion(INDICE)
        return ("El índice de archivos se está creando por primera vez (tarda unos minutos). Mientras, busca con "
                "list_dir o vuelve a intentarlo en un rato.")
    if edad > indice.MAX_EDAD_H:
        indice.lanzar_actualizacion(INDICE)  # se refresca aparte; mientras, se usa el que hay
    filas = indice.buscar(INDICE, nombre, max(1, min(int(limite), 100)))
    if not filas:
        return f"Ningún archivo con «{nombre}» en el nombre (índice de hace {edad:.0f} h)."
    import time as _t

    def tam(n: int) -> str:
        for u in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f} {u}"
            n /= 1024
        return f"{n:.1f} TB"
    lineas = [f"{Path(c) / n}  ·  {tam(t)}  ·  {_t.strftime('%Y-%m-%d', _t.localtime(m))}" for n, c, t, m in filas]
    return f"{len(filas)} resultados (índice de hace {edad:.0f} h):\n" + "\n".join(lineas)


INDICE: Path = Path("indice.db")


def main() -> None:
    global HOME, INDICE
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", default=str(Path.home()))
    ap.add_argument("--indice", default="", help="base de datos del índice de archivos (skynet_tools.indice)")
    a = ap.parse_args()
    HOME = Path(a.home).resolve()
    INDICE = Path(a.indice) if a.indice else HOME / ".skynet-indice.db"
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
