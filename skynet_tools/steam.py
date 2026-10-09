"""Instalar juegos de Steam sin pulsar nada (lo usa `sistema.instalar_steam`).

Steam no tiene una orden para «instalar ya»: `steam://install/<AppID>` solo abre un diálogo que hay que
aceptar a mano, y pulsarlo con el teclado falla según el idioma, el foco o la versión del cliente.
Método principal (sin interfaz): escribir `steamapps/appmanifest_<AppID>.acf` con «actualización pendiente»
(StateFlags 1026) en la biblioteca de Steam y (re)arrancar Steam, que al leerlo descarga el juego solo.
Si a los segundos no hay descarga (p. ej. un juego gratis que aún no está en la biblioteca, sin licencia),
se borra ese manifiesto y se recurre al diálogo `steam://install` pulsando «Instalar».

Nunca se reinicia Steam con un juego abierto (RunningAppID del registro): en ese caso el manifiesto queda
escrito y la descarga empieza la próxima vez que se abra Steam.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

INSTALADO = 4                 # StateFlags: StateFullyInstalled
PENDIENTE = 1026              # StateUpdateRequired | StateUpdateStarted: Steam lo descarga al leerlo
TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


# --- VDF (formato de texto de Valve) -------------------------------------------------
def parse_vdf(text: str) -> dict:
    """Parser mínimo de VDF de texto: claves y valores entre comillas y bloques { }."""
    root: dict = {}
    stack = [root]
    key: str | None = None
    for m in TOKEN_RE.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            new: dict = {}
            stack[-1][key or ""] = new
            stack.append(new)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = s.replace('\\\\', '\\')
        else:
            stack[-1][key] = s.replace('\\\\', '\\')
            key = None
    return root


def _vdf_dump(d: dict, indent: int = 0) -> str:
    tab = "\t" * indent
    out = []
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f'{tab}"{k}"\n{tab}{{\n{_vdf_dump(v, indent + 1)}{tab}}}\n')
        else:
            out.append(f'{tab}"{k}"\t\t"{v}"\n')
    return "".join(out)


# --- dónde está Steam ------------------------------------------------------------------
def _reg(name: str) -> str | int | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def steam_dir() -> Path | None:
    cands = [_reg("SteamPath"), os.path.expandvars(r"%ProgramFiles(x86)%\Steam"), os.path.expandvars(r"%ProgramFiles%\Steam")]
    for c in cands:
        if c and Path(str(c)).joinpath("steamapps").is_dir():
            return Path(str(c))
    return None


def libraries(steam: Path) -> list[Path]:
    """Carpetas `steamapps` de todas las bibliotecas; la principal primero."""
    out = [steam / "steamapps"]
    f = steam / "steamapps" / "libraryfolders.vdf"
    if f.is_file():
        data = parse_vdf(f.read_text(encoding="utf-8", errors="replace")).get("libraryfolders", {})
        for _, lib in sorted(data.items(), key=lambda kv: kv[0]):
            if isinstance(lib, dict) and lib.get("path"):
                p = Path(lib["path"]) / "steamapps"
                if p.is_dir() and p not in out:
                    out.append(p)
    return out


def manifest(steamapps: Path, appid: int) -> Path:
    return steamapps / f"appmanifest_{appid}.acf"


def state(steam: Path, appid: int) -> tuple[Path, dict] | None:
    """Manifiesto existente del juego en cualquier biblioteca."""
    for lib in libraries(steam):
        f = manifest(lib, appid)
        if f.is_file():
            return f, parse_vdf(f.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
    return None


def installdir_for(name: str, appid: int) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f™®©]', "", name).strip(" .")
    return clean or f"app_{appid}"


def write_manifest(steamapps: Path, appid: int, name: str) -> Path:
    data = {"AppState": {
        "appid": str(appid), "Universe": "1", "name": name or f"App {appid}", "StateFlags": str(PENDIENTE),
        "installdir": installdir_for(name, appid), "LastUpdated": "0", "UpdateResult": "0", "SizeOnDisk": "0",
        "buildid": "0", "LastOwner": "0", "BytesToDownload": "0", "BytesDownloaded": "0",
        "AutoUpdateBehavior": "0", "AllowOtherDownloadsWhileRunning": "0", "ScheduledAutoUpdate": "0",
        "UserConfig": {}, "MountedDepots": {},
    }}
    f = manifest(steamapps, appid)
    f.write_text(_vdf_dump(data), encoding="utf-8")
    return f


def downloading(steam: Path, f: Path, appid: int) -> bool:
    """Steam ya trabaja en el juego: tocó el manifiesto o creó su carpeta de descarga."""
    if (f.parent / "downloading" / str(appid)).exists():
        return True
    if not f.is_file():
        return False
    st = parse_vdf(f.read_text(encoding="utf-8", errors="replace")).get("AppState", {})
    return (st.get("StateFlags") != str(PENDIENTE) or st.get("BytesToDownload", "0") != "0"
            or st.get("buildid", "0") != "0")


# --- control de Steam (Windows) ----------------------------------------------------------
def steam_running() -> bool:
    if os.name != "nt":
        return False
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"], capture_output=True, text=True,
                       errors="replace", stdin=subprocess.DEVNULL)
    return "steam.exe" in (r.stdout or "").lower()


def game_running() -> bool:
    return bool(_reg("RunningAppID") or 0)


def restart_steam(steam: Path, wait_s: float = 60) -> None:
    exe = steam / "steam.exe"
    if steam_running():
        subprocess.Popen([str(exe), "-shutdown"], stdin=subprocess.DEVNULL)
        end = time.monotonic() + wait_s
        while steam_running() and time.monotonic() < end:
            time.sleep(1)
    subprocess.Popen([str(exe), "-silent"], stdin=subprocess.DEVNULL)


def store_name(appid: int) -> str:
    """Nombre del juego en la tienda (solo para el manifiesto y el mensaje). Sin red, AppID."""
    try:
        import httpx

        r = httpx.get("https://store.steampowered.com/api/appdetails", params={"appids": appid, "filters": "basic"},
                      timeout=8)
        d = r.json().get(str(appid), {})
        if d.get("success"):
            return str(d["data"].get("name") or "")
    except Exception:
        pass
    return ""


@dataclass
class Entorno:
    """Lo que toca el mundo real; los tests lo sustituyen."""
    steam_dir: Callable[[], Path | None] = steam_dir
    game_running: Callable[[], bool] = game_running
    restart: Callable[[Path], None] = restart_steam
    name: Callable[[int], str] = store_name
    dialog: Callable[[int, int], str] = lambda appid, seg: "sin_dialogo"
    sleep: Callable[[float], None] = time.sleep


def install(appid: int, wait_s: int = 90, env: Entorno | None = None) -> str:
    env = env or Entorno()
    steam = env.steam_dir()
    if steam is None:
        return "No encuentro Steam en este PC (ni en el registro ni en Program Files)."
    prev = state(steam, appid)
    if prev:
        f, st = prev
        flags = int(st.get("StateFlags", "0") or 0)
        name = st.get("name") or appid
        if flags & INSTALADO and not flags & 2:
            return f"{name} ({appid}) ya está instalado en {f.parent.parent}."
        return f"{name} ({appid}) ya está en la cola de descargas de Steam."
    name = env.name(appid)
    lib = libraries(steam)[0]
    f = write_manifest(lib, appid, name)
    label = f"{name or 'El juego'} ({appid})"
    if env.game_running():
        return (f"{label}: lo he dejado en cola en {lib.parent}. Hay un juego abierto, así que no reinicio Steam: "
                "la descarga empezará sola la próxima vez que se abra Steam.")
    env.restart(steam)
    step = 3.0
    waited = 0.0
    while waited < wait_s:
        env.sleep(step)
        waited += step
        if downloading(steam, f, appid):
            return f"{label}: descargándose en Steam (biblioteca {lib.parent}). No hace falta pulsar nada."
    # Sin descarga: lo normal es que la cuenta no tenga licencia (gratis aún no añadido). Plan B: diálogo.
    try:
        f.unlink()
    except OSError:
        pass
    res = env.dialog(appid, 60)
    if res == "pulsado":
        return f"{label}: instalación aceptada en el diálogo de Steam. La descarga sigue en Steam."
    return (f"{label}: Steam no empezó a descargarlo en {wait_s} s. Puede que la cuenta no lo tenga (si es de pago, "
            "hay que comprarlo) o que Steam pida iniciar sesión.")
