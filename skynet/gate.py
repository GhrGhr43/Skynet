"""Permission gate: clasifica cada llamada a herramienta y decide permitir, preguntar o denegar.

Reglas (principio 1, mínimo privilegio):
  READ        permitido
  WRITE       permitido solo si todas las rutas caen dentro del repo autorizado
  EXECUTE     permitido si el comando está en la lista blanca; si no, se pregunta
  PRIVILEGED  se pregunta (o se permite si la tarea lo tiene preaprobado)
  DESTRUCTIVE se pregunta siempre
Sin humano presente (tareas largas), "preguntar" se convierte en "denegar".
Modos por modelo (modos.py): las herramientas `sistema.*` (todo el PC) solo se permiten según el modo
(lectura / editar / total) y, en cualquier modo, administrador, carpetas del sistema, borrar y secretos
se preguntan siempre (sin «sí a toda la tarea»). En «total» también se relaja la lista blanca del repo.
«Sin preguntar» (Control total + casilla): lo que se preguntaría se permite directamente y se audita;
lo denegado (skills/memoria de Skynet, archivos que gestiona Skynet) sigue denegado.
Las skills y la memoria curada de Skynet (skills/, memoria/) solo cambian con /aprobar:
cualquier herramienta que no sea de lectura y apunte ahí se deniega.
Cada decisión queda en el audit log.
"""
from __future__ import annotations

import fnmatch
import os
import posixpath
import re
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import propuestas
from .audit import Audit
from .config import RepoConfig, Settings


class Level(IntEnum):
    READ = 0
    WRITE = 1
    EXECUTE = 2
    PRIVILEGED = 3
    DESTRUCTIVE = 4


class Decision(str, Enum):
    ALLOW = "permitido"
    ASK = "preguntar"
    DENY = "denegado"


@dataclass
class GateResult:
    decision: Decision
    level: Level
    reason: str
    siempre: bool = False  # categoría que se pregunta siempre: «t» vale solo para esta vez

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


# Respuesta del humano: "s" (sí), "n" (no) o "t" (sí a esta herramienta durante toda la tarea)
Asker = Callable[[str, Level, dict[str, Any], str], Awaitable[str]]

PATH_KEYS = ("path", "ruta", "file", "archivo", "cwd", "directory", "dir", "repo")
SHELL_META = ("&", "|", ";", ">", "<", "`", "$(", "\n", "\r", "%")
SIEMPRE_TAG = "siempre se pregunta"
SISTEMA = "sistema."

# --- zonas que se preguntan siempre (modos por modelo) -------------------------
_SYSTEM_DEFAULTS = ["C:/Windows", "C:/Program Files", "C:/Program Files (x86)", "C:/ProgramData"]
_SECRET_PARTS = ("/.ssh/", "/.gnupg/", "/.aws/", "/.azure/", "/.kube/", "/.docker/config.json", "/microsoft/credentials",
                 "/microsoft/protect", "/microsoft/vault", "login data", "/cookies", "/network/cookies", "web data",
                 "key4.db", "logins.json", "id_rsa", "id_ed25519", "password", "contraseña", "credentials",
                 "/data/omniroute", ".kdbx", "wallet", "secrets")
_SECRET_EXT = (".pem", ".pfx", ".p12", ".key", ".ppk")
_ADMIN_RE = re.compile(
    r"\b(runas|sudo|gsudo|bcdedit|diskpart|takeown|icacls|netsh|reg\s+(add|delete|import)|sc(\.exe)?\s+(config|create|delete|stop)"
    r"|set-executionpolicy|new-service|set-service|disable-|enable-windowsoptionalfeature|dism|sfc|wmic|shutdown|restart-computer"
    r"|stop-computer|format-volume|bitlocker)\b|-verb\s+runas|hklm:|hkey_local_machine", re.IGNORECASE)
_DELETE_RE = re.compile(r"(^|[\s;&|(])(rm|del|erase|rd|rmdir|ri|remove-item|rimraf|clear-content|format)(\.exe)?(\s|$)",
                        re.IGNORECASE)
_SYS_WORDS = ("system32", "syswow64", "%windir%", "$env:windir", "%systemroot%", "$env:systemroot", "%programfiles",
              "$env:programfiles", "$env:programdata", "%programdata%")


def norm_path(p: str, base: str) -> str:
    """Ruta normalizada en minúsculas con «/», sin tocar el disco (vale para rutas de Windows en cualquier SO)."""
    p = os.path.expandvars(os.path.expanduser(p.strip().strip('"'))).replace("\\", "/")
    if not (p.startswith("/") or re.match(r"^[a-zA-Z]:/", p) or re.match(r"^[a-zA-Z]:$", p)):
        p = base.replace("\\", "/").rstrip("/") + "/" + p
    drive = ""
    if re.match(r"^[a-zA-Z]:", p):
        drive, p = p[:2], p[2:] or "/"
    return (drive + posixpath.normpath(p)).lower()


def system_dirs() -> list[str]:
    dirs = list(_SYSTEM_DEFAULTS)
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
        if os.environ.get(var):
            dirs.append(os.environ[var])
    return sorted({norm_path(d, "/") for d in dirs})


def _under(path: str, roots: list[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def is_secret_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (any(s in path + ("/" if not path.endswith("/") else "") for s in _SECRET_PARTS)
            or name == ".env" or name.startswith(".env.") or name.endswith(_SECRET_EXT))


def command_risks(command: str, sysdirs: list[str]) -> str | None:
    """Motivo por el que un comando se pregunta siempre (o None)."""
    low = command.lower().replace("\\", "/")
    if _ADMIN_RE.search(command):
        return "pide permisos de administrador o cambia el sistema"
    if _DELETE_RE.search(command):
        return "borra archivos"
    if any(d in low for d in sysdirs) or any(w in low for w in _SYS_WORDS):
        return "toca carpetas del sistema"
    if any(s in low for s in _SECRET_PARTS) or re.search(r"(^|[\s/\\\"'])\.env\b", low) or any(e in low for e in _SECRET_EXT):
        return "puede leer contraseñas, claves o cookies"
    return None


def tool_key(server: str, tool: str) -> str:
    return f"{server}.{tool}"


def has_shell_meta(command: str) -> bool:
    return any(m in command for m in SHELL_META)


def normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def command_whitelisted(command: str, whitelist: list[str]) -> bool:
    cmd = normalize_command(command).lower()
    for w in whitelist:
        w = normalize_command(w).lower()
        if w and (cmd == w or cmd.startswith(w + " ")):
            return True
    return False


class PermissionGate:
    def __init__(
        self,
        settings: Settings,
        repo: RepoConfig | None,
        audit: Audit,
        asker: Asker | None = None,
        grants: list[str] | None = None,
        protected: list[str] | None = None,
        mode: str = "repo",
        user_home: Path | str | None = None,
        internet: bool = False,
        sin_preguntar: bool = False,
    ):
        self.settings = settings
        self.repo = repo
        self.audit = audit
        self.asker = asker
        self.grants = list(grants or [])       # patrones preaprobados para la tarea
        self.session_grants: set[str] = set()  # respondido "t" durante esta ejecución
        self.protected = [p.replace("\\", "/").lower() for p in (protected or [])]  # rutas que el agente no toca
        self.reserved = [d.resolve() for d in propuestas.reserved_dirs(settings.home)]
        self.mode = mode
        self.internet = internet
        self.sin_preguntar = sin_preguntar and mode == "total"
        self.user_home = norm_path(str(user_home or Path.home()), "/")
        self.sysdirs = system_dirs()
        self.skynet_home = norm_path(str(settings.home), "/")

    # --- clasificación ---------------------------------------------------
    def classify(self, key: str) -> Level:
        levels = self.settings.tool_levels
        if key in levels:
            return Level[levels[key].upper()]
        for pattern, lvl in levels.items():
            if fnmatch.fnmatchcase(key, pattern):
                return Level[lvl.upper()]
        return Level[self.settings.default_level.upper()]

    def _paths_inside_repo(self, args: dict[str, Any]) -> tuple[bool, str]:
        if self.repo is None:
            return False, "no hay repo autorizado para esta tarea"
        root = self.repo.ruta.resolve()
        for k, v in args.items():
            if k.lower() not in PATH_KEYS or not isinstance(v, str) or not v:
                continue
            p = Path(v)
            target = (p if p.is_absolute() else root / p).resolve()
            if target != root and root not in target.parents:
                return False, f"la ruta '{v}' está fuera del repo autorizado"
            rel = target.relative_to(root).parts
            if rel and rel[0] == ".git":
                return False, "no se puede tocar el interior de .git"
        return True, ""

    def evaluate(self, key: str, args: dict[str, Any]) -> GateResult:
        """Decisión pura (sin preguntar ni auditar)."""
        level = self.classify(key)
        if key.startswith("internet."):
            if not self.internet or key not in ("internet.buscar", "internet.leer"):
                return GateResult(Decision.DENY, level, "Internet está desactivado o la herramienta no está autorizada")
        if key.startswith(SISTEMA):
            return self._evaluate_sistema(key, level, args)
        if self.mode == "total" and level is Level.EXECUTE and self.repo is not None:
            command = str(args.get("command") or args.get("comando") or "")
            ok, why = self._paths_inside_repo(args)
            if command and ok:
                risk = command_risks(command, self.sysdirs)
                if risk:
                    return self._always(level, f"el comando {risk}")
                return GateResult(Decision.ALLOW, level, "modo Control total")
        # Toda herramienta con rutas debe quedarse dentro del repo, sea cual sea su nivel.
        ok, why = self._paths_inside_repo(args)
        if not ok and any(k.lower() in PATH_KEYS for k in args):
            return GateResult(Decision.DENY, level, why)

        if level is Level.READ:
            return GateResult(Decision.ALLOW, level, "lectura")
        hit = self._reserved_hit(args)
        if hit:
            return GateResult(Decision.DENY, level, f"'{hit}' es una skill o la memoria de Skynet: solo cambia con /aprobar")
        hit = self._protected_hit(args)
        if hit:
            return GateResult(Decision.DENY, level, f"'{hit}' lo gestiona Skynet; no lo modifiques")
        if level is Level.WRITE:
            if self.repo is None:
                return GateResult(Decision.DENY, level, "escritura sin repo autorizado")
            return GateResult(Decision.ALLOW, level, "escritura dentro del repo autorizado")
        if level is Level.EXECUTE:
            command = str(args.get("command") or args.get("comando") or "")
            if not command:
                return GateResult(Decision.ASK, level, "ejecución sin comando reconocible")
            if has_shell_meta(command):
                return GateResult(Decision.ASK, level, "el comando encadena o redirige (&, |, ;, >...)")
            wl = list(self.settings.execute_whitelist)
            if self.repo:
                wl += self.repo.ejecutar
                if self.repo.verificador:
                    wl.append(self.repo.verificador)
            if command_whitelisted(command, wl):
                return GateResult(Decision.ALLOW, level, "comando en lista blanca")
            if self._granted(key):
                return GateResult(Decision.ALLOW, level, "preaprobado para esta tarea")
            return GateResult(Decision.ASK, level, "comando fuera de la lista blanca")
        if level is Level.PRIVILEGED:
            if self._granted(key):
                return GateResult(Decision.ALLOW, level, "preaprobado para esta tarea")
            return GateResult(Decision.ASK, level, "acción privilegiada")
        return GateResult(Decision.ASK, level, "acción destructiva")

    # --- herramientas de todo el PC (modos) ----------------------------------
    def _always(self, level: Level, reason: str) -> GateResult:
        return GateResult(Decision.ASK, level, f"{reason} ({SIEMPRE_TAG})", siempre=True)

    def _evaluate_sistema(self, key: str, level: Level, args: dict[str, Any]) -> GateResult:
        from .modos import MODOS

        if self.mode == "repo":
            return GateResult(Decision.DENY, level, "el modelo está en modo «Solo repo»: no sale del repo")
        nombre = MODOS[self.mode].nombre if self.mode in MODOS else self.mode
        paths = [norm_path(v, self.user_home) for k, v in args.items()
                 if k.lower() in PATH_KEYS and isinstance(v, str) and v]
        if any(is_secret_path(p) for p in paths):
            return self._always(level, "puede contener contraseñas, claves o cookies")
        if level is Level.READ:
            return GateResult(Decision.ALLOW, level, f"lectura (modo «{nombre}»)")
        if self.mode == "lectura":
            return GateResult(Decision.DENY, level, "el modo «Ver mi PC» solo permite leer")
        hit = self._reserved_hit(args)
        if hit:
            return GateResult(Decision.DENY, level, f"'{hit}' es una skill o la memoria de Skynet: solo cambia con /aprobar")
        if any(_under(p, self.sysdirs) for p in paths):
            return self._always(level, "toca carpetas del sistema")
        if any(_under(p, [self.skynet_home]) for p in paths):
            return self._always(level, "toca la carpeta de Skynet")
        if level is Level.DESTRUCTIVE:
            return self._always(level, "borra archivos")
        if level is Level.WRITE:
            if paths and not all(_under(p, [self.user_home]) for p in paths):
                return self._always(level, "escribe fuera de tu carpeta de usuario")
            return GateResult(Decision.ALLOW, level, f"escritura en tu usuario (modo «{nombre}»)")
        if level in (Level.EXECUTE, Level.PRIVILEGED):
            if self.mode != "total":
                return GateResult(Decision.DENY, level, f"el modo «{nombre}» no permite ejecutar programas")
            command = str(args.get("command") or args.get("comando") or args.get("destino") or "")
            risk = command_risks(command, self.sysdirs) if command else None
            if risk:
                return self._always(level, f"el comando {risk}")
            return GateResult(Decision.ALLOW, level, "modo Control total")
        return self._always(level, "acción no reconocida")

    def _protected_hit(self, args: dict[str, Any]) -> str | None:
        if not self.protected or self.repo is None:
            return None
        root = self.repo.ruta.resolve()
        for k, v in args.items():
            if k.lower() in PATH_KEYS and isinstance(v, str) and v:
                p = Path(v)
                target = (p if p.is_absolute() else root / p).resolve()
                try:
                    rel = target.relative_to(root).as_posix().lower()
                except ValueError:
                    continue
                if rel in self.protected:
                    return v
        return None

    def _reserved_hit(self, args: dict[str, Any]) -> str | None:
        root = self.repo.ruta.resolve() if self.repo else None
        for k, v in args.items():
            if k.lower() in PATH_KEYS and isinstance(v, str) and v:
                p = Path(v)
                if not p.is_absolute() and root is None:
                    continue
                target = (p if p.is_absolute() else root / p).resolve()
                if any(target == d or d in target.parents for d in self.reserved):
                    return v
        return None

    def _granted(self, key: str) -> bool:
        if key in self.session_grants:
            return True
        return any(fnmatch.fnmatchcase(key, g) for g in self.grants)

    # --- decisión completa ----------------------------------------------
    async def check(self, key: str, args: dict[str, Any], args_summary: str = "") -> GateResult:
        result = self.evaluate(key, args)
        asked = False
        auto = False
        if result.decision is Decision.ASK and self.sin_preguntar:
            auto = True
            result = GateResult(Decision.ALLOW, result.level, f"{result.reason}; permitido por «Sin preguntar»")
        if result.decision is Decision.ASK:
            if self.asker is None:
                result = GateResult(Decision.DENY, result.level, f"{result.reason}; no hay nadie para confirmar")
            else:
                asked = True
                answer = (await self.asker(key, result.level, args, result.reason)).strip().lower()
                if (answer in ("t", "todo", "todas", "siempre") and result.level is not Level.DESTRUCTIVE
                        and not result.siempre):
                    self.session_grants.add(key)
                    result = GateResult(Decision.ALLOW, result.level, "confirmado por el usuario (toda la tarea)")
                elif answer in ("s", "si", "sí", "y", "yes", "t", "todo", "todas", "siempre"):
                    result = GateResult(Decision.ALLOW, result.level, "confirmado por el usuario")
                else:
                    result = GateResult(Decision.DENY, result.level, "rechazado por el usuario")
        # Lo permitido sin preguntar ya queda en el evento "tool"; aquí solo lo que decide un humano o se deniega.
        if asked or auto or result.decision is not Decision.ALLOW:
            self.audit.log(
                "permission",
                tool=key,
                permission_level=result.level.name,
                decision=result.decision.value,
                detail={"motivo": result.reason, "preguntado": asked, "args_resumen": args_summary},
            )
        return result
