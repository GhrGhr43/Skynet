"""Permission gate: clasifica cada llamada a herramienta y decide permitir, preguntar o denegar.

Reglas (principio 1, mínimo privilegio):
  READ        permitido
  WRITE       permitido solo si todas las rutas caen dentro del repo autorizado
  EXECUTE     permitido si el comando está en la lista blanca; si no, se pregunta
  PRIVILEGED  se pregunta (o se permite si la tarea lo tiene preaprobado)
  DESTRUCTIVE se pregunta siempre
Sin humano presente (tareas largas), "preguntar" se convierte en "denegar".
Cada decisión queda en el audit log.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Awaitable, Callable

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

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


# Respuesta del humano: "s" (sí), "n" (no) o "t" (sí a esta herramienta durante toda la tarea)
Asker = Callable[[str, Level, dict[str, Any], str], Awaitable[str]]

PATH_KEYS = ("path", "ruta", "file", "archivo", "cwd", "directory", "dir", "repo")
SHELL_META = ("&", "|", ";", ">", "<", "`", "$(", "\n", "\r", "%")


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
    ):
        self.settings = settings
        self.repo = repo
        self.audit = audit
        self.asker = asker
        self.grants = list(grants or [])       # patrones preaprobados para la tarea
        self.session_grants: set[str] = set()  # respondido "t" durante esta ejecución

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
        # Toda herramienta con rutas debe quedarse dentro del repo, sea cual sea su nivel.
        ok, why = self._paths_inside_repo(args)
        if not ok and any(k.lower() in PATH_KEYS for k in args):
            return GateResult(Decision.DENY, level, why)

        if level is Level.READ:
            return GateResult(Decision.ALLOW, level, "lectura")
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

    def _granted(self, key: str) -> bool:
        if key in self.session_grants:
            return True
        return any(fnmatch.fnmatchcase(key, g) for g in self.grants)

    # --- decisión completa ----------------------------------------------
    async def check(self, key: str, args: dict[str, Any], args_summary: str = "") -> GateResult:
        result = self.evaluate(key, args)
        asked = False
        if result.decision is Decision.ASK:
            if self.asker is None:
                result = GateResult(Decision.DENY, result.level, f"{result.reason}; no hay nadie para confirmar")
            else:
                asked = True
                answer = (await self.asker(key, result.level, args, result.reason)).strip().lower()
                if answer in ("t", "todo", "todas", "siempre") and result.level is not Level.DESTRUCTIVE:
                    self.session_grants.add(key)
                    result = GateResult(Decision.ALLOW, result.level, "confirmado por el usuario (toda la tarea)")
                elif answer in ("s", "si", "sí", "y", "yes", "t", "todo", "todas", "siempre"):
                    result = GateResult(Decision.ALLOW, result.level, "confirmado por el usuario")
                else:
                    result = GateResult(Decision.DENY, result.level, "rechazado por el usuario")
        # Lo permitido sin preguntar ya queda en el evento "tool"; aquí solo lo que decide un humano o se deniega.
        if asked or result.decision is not Decision.ALLOW:
            self.audit.log(
                "permission",
                tool=key,
                permission_level=result.level.name,
                decision=result.decision.value,
                detail={"motivo": result.reason, "preguntado": asked, "args_resumen": args_summary},
            )
        return result
