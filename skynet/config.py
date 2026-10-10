"""Carga de configuración (config/*.toml).

Todo lo que el usuario puede ajustar vive en TOML; el código solo lee estructuras
tipadas. Un archivo `config/<nombre>.local.toml` (ignorado por git) se mezcla encima del
original, para cambios personales sin tocar los archivos versionados.
"""
from __future__ import annotations

import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_HOME = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    pass


@dataclass
class RepoConfig:
    nombre: str
    ruta: Path
    verificador: str | None = None
    ejecutar: list[str] = field(default_factory=list)
    privacidad: str = "normal"
    agente: str = "skynet"
    herramientas: list[str] = field(default_factory=lambda: ["workspace"])


@dataclass
class ModelProfile:
    nombre: str
    litellm: str
    api_base: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    privado: bool = False
    coste_entrada_usd_mtok: float | None = None
    coste_salida_usd_mtok: float | None = None
    max_tokens: int = 8192
    timeout_seg: float = 600
    reasoning_effort: str | None = None  # low | medium | high (si el modelo lo admite)
    contexto_tokens: int = 0  # ventana del modelo; 0 = la del motor de skynet.toml con el mismo nombre o 128K
    # Muestreo (None = lo del servidor). Para los locales importa: llama-server usa temperatura 0.8 por defecto.
    temperatura: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None
    presence_penalty: float | None = None
    # Perfil que es un agente entero (Hermes): Skynet le pasa la conversación y él usa sus propias herramientas.
    agente: bool = False
    motor: str | None = None            # motor de skynet.toml que lo sirve (por defecto, el del mismo nombre)
    api_key_archivo: str | None = None  # clave leída de un archivo (la genera el motor al arrancar)

    def resolved_api_key(self) -> str | None:
        if self.api_key_env:
            return os.environ.get(self.api_key_env) or None
        if self.api_key_archivo:
            try:
                return Path(self.api_key_archivo).read_text(encoding="utf-8").strip() or None
            except OSError:
                return None  # el motor aún no ha arrancado nunca
        return self.api_key

    def available(self) -> tuple[bool, str]:
        if self.api_key_env and not os.environ.get(self.api_key_env):
            return False, f"falta la variable de entorno {self.api_key_env}"
        return True, ""


@dataclass
class ServerSpec:
    nombre: str
    comando: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class AgentLimits:
    max_turnos: int = 30
    max_salida_herramienta: int = 6000
    contexto_max_tokens: int = 6000


@dataclass
class LongLimits:
    max_horas: float = 8
    max_iteraciones: int = 200
    max_errores_iguales: int = 3
    max_sin_avance: int = 3
    turnos_por_iteracion: int = 20
    timeout_verificador_seg: int = 900


@dataclass
class Settings:
    home: Path
    db_path: Path
    logs_dir: Path
    repos: dict[str, RepoConfig]
    tool_levels: dict[str, str]
    default_level: str
    execute_whitelist: list[str]
    models: dict[str, ModelProfile]
    budget_eur: float
    usd_eur: float
    servers: dict[str, ServerSpec]
    agent: AgentLimits
    long: LongLimits
    engines: dict[str, Any] = field(default_factory=dict)  # [motores.*] de skynet.toml
    proyectos: Path = Path(".")  # dónde crea proyectos nuevos crear_proyecto ([general] proyectos)
    acceso: dict[str, Any] = field(default_factory=dict)   # [acceso] de skynet.toml (móvil por Tailscale)

    def repo(self, nombre: str) -> RepoConfig:
        try:
            return self.repos[nombre]
        except KeyError:
            raise ConfigError(f"El repo '{nombre}' no está autorizado en config/repos.toml") from None

    def server_spec(self, nombre: str, repo: RepoConfig | None) -> ServerSpec:
        spec = self.servers.get(nombre)
        if spec is None:
            raise ConfigError(f"Servidor MCP '{nombre}' no definido en config/skynet.toml")
        subs = {
            "{python}": sys.executable,
            "{home}": str(self.home),
            "{repo}": str(repo.ruta) if repo else "",
        }

        def sub(s: str) -> str:
            for k, v in subs.items():
                s = s.replace(k, v)
            return s

        return ServerSpec(spec.nombre, sub(spec.comando), [sub(a) for a in spec.args], dict(spec.env))


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_toml(config_dir: Path, name: str) -> dict:
    path = config_dir / f"{name}.toml"
    data: dict = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}") from e
    local = config_dir / f"{name}.local.toml"
    if local.exists():
        try:
            data = _deep_merge(data, tomllib.loads(local.read_text(encoding="utf-8")))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{local}: {e}") from e
    return data


def _resolve(home: Path, p: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(p)))
    return (path if path.is_absolute() else home / path).resolve()


def load_settings(home: Path | str | None = None) -> Settings:
    home = Path(home or os.environ.get("SKYNET_HOME") or DEFAULT_HOME).resolve()
    cdir = home / "config"
    general = _load_toml(cdir, "skynet")
    permisos = _load_toml(cdir, "permisos")
    router = _load_toml(cdir, "router")
    repos_raw = _load_toml(cdir, "repos")

    g = general.get("general", {})
    repos: dict[str, RepoConfig] = {}
    for nombre, r in repos_raw.get("repos", {}).items():
        if "ruta" not in r:
            raise ConfigError(f"repos.toml: al repo '{nombre}' le falta 'ruta'")
        repos[nombre] = RepoConfig(
            nombre=nombre,
            ruta=_resolve(home, r["ruta"]),
            verificador=r.get("verificador"),
            ejecutar=list(r.get("ejecutar", [])),
            privacidad=r.get("privacidad", "normal"),
            agente=r.get("agente", "skynet"),
            herramientas=list(r.get("herramientas", ["workspace"])),
        )

    models = {}
    for nombre, m in router.get("modelos", {}).items():
        models[nombre] = ModelProfile(nombre=nombre, **m)
        if models[nombre].api_key_archivo:
            models[nombre].api_key_archivo = str(_resolve(home, models[nombre].api_key_archivo))
    if "local" not in models:
        raise ConfigError("router.toml debe definir [modelos.local] (el modelo de reserva)")
    for nombre, prof in models.items():
        if not prof.contexto_tokens:
            motor = general.get("motores", {}).get(nombre, {})
            prof.contexto_tokens = int(motor.get("contexto") or 0) or 128_000

    servers = {
        n: ServerSpec(n, s["comando"], list(s.get("args", [])), dict(s.get("env", {})))
        for n, s in general.get("mcp", {}).items()
    }

    return Settings(
        home=home,
        db_path=_resolve(home, g.get("base_datos", "data/skynet.db")),
        logs_dir=_resolve(home, g.get("logs", "data/logs")),
        repos=repos,
        tool_levels=dict(permisos.get("herramientas", {})),
        default_level=permisos.get("nivel_por_defecto", "PRIVILEGED"),
        execute_whitelist=list(permisos.get("ejecutar", {}).get("lista_blanca", [])),
        models=models,
        budget_eur=float(router.get("presupuesto", {}).get("mensual_eur", 0)),
        usd_eur=float(router.get("moneda_usd_eur", 0.86)),
        servers=servers,
        agent=AgentLimits(**general.get("agente", {})),
        long=LongLimits(**general.get("largo", {})),
        engines=dict(general.get("motores", {})),
        acceso=dict(general.get("acceso", {})),
        # Proyectos nuevos: junto a la carpeta de Skynet (p. ej. C:\Git) salvo que [general] proyectos diga otra cosa.
        proyectos=_resolve(home, g["proyectos"]) if g.get("proyectos") else home.parent,
    )


def add_repo(home: Path, nombre: str, ruta: Path, verificador: str | None = None) -> RepoConfig:
    """Añade un repo a config/repos.local.toml (ignorado por git, se mezcla sobre repos.toml)."""
    local = home / "config" / "repos.local.toml"
    lines = [f"\n[repos.{nombre}]", f"ruta = {json.dumps(str(ruta))}"]
    if verificador:
        lines.append(f"verificador = {json.dumps(verificador)}")
    local.parent.mkdir(parents=True, exist_ok=True)
    with local.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return RepoConfig(nombre=nombre, ruta=ruta, verificador=verificador)
