"""Acceso desde otros dispositivos (el móvil) a la web de Skynet, a través de Tailscale.

La web sigue escuchando solo en 127.0.0.1. Para llegar desde el móvil se usa Tailscale Serve
(`tailscale serve --bg 8765`): publica https://<pc>.<tailnet>.ts.net SOLO dentro de tu red de Tailscale
y reenvía cada petición a 127.0.0.1:8765 añadiendo `X-Forwarded-For` con la IP de Tailscale del que llama.

Encima, cada dispositivo necesita su llave. Se consigue emparejándolo desde el PC: la web enseña un QR con
un código de un solo uso (10 min) que el móvil cambia por una llave propia. Las llaves se guardan como hash en
data/dispositivos.json, se pueden quitar una a una y todo queda en el registro.

Lo que llega por un proxy pero no viene de una IP de Tailscale (p. ej. Tailscale Funnel, que publica en
internet) se rechaza siempre.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

TAILSCALE_REDES = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
ORIGENES = ("https://app.skynet.local",)  # la app Android (sirve su interfaz desde ese origen)
CODIGO_MIN = 10            # vida de un código de emparejado
MAX_CODIGOS = 5            # códigos vivos a la vez
INTENTOS_MAX = 10          # intentos de emparejar por minuto (los códigos son de 128 bits; es por higiene)
GUARDAR_USO_SEG = 60       # «último uso» se escribe a disco como mucho una vez por minuto y dispositivo
TAILSCALE_CACHE_SEG = 20


class AccesoError(Exception):
    def __init__(self, mensaje: str, status: int = 403):
        super().__init__(mensaje)
        self.status = status


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(secreto: str) -> str:
    return hashlib.sha256(secreto.encode("utf-8")).hexdigest()


def ip_de_tailscale(ip: str | None) -> bool:
    try:
        addr = ipaddress.ip_address((ip or "").strip().strip("[]"))
    except ValueError:
        return False
    return any(addr in red for red in TAILSCALE_REDES)


def ip_cliente(cabecera_xff: str | None) -> str | None:
    """IP de quien llama según el proxy. Tailscale Serve pone la suya; si hubiera varias, vale la última
    (la que añadió el último proxy, el nuestro)."""
    if not cabecera_xff:
        return None
    partes = [p.strip() for p in cabecera_xff.split(",") if p.strip()]
    return partes[-1] if partes else None


def nombre_limpio(nombre: Any, defecto: str = "Móvil") -> str:
    texto = " ".join(str(nombre or "").split())[:40]
    return texto or defecto


@dataclass
class Dispositivo:
    id: str
    nombre: str
    hash: str
    creado: str
    ultimo_uso: str | None = None
    ultimo_origen: str | None = None
    revocado: str | None = None

    def publico(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("hash")
        return d


@dataclass
class Cliente:
    """Quién hace la petición. Lo deja el middleware en request.state.cliente."""

    remoto: bool
    ip: str | None = None
    usuario: str | None = None          # cuenta de Tailscale (cabecera Tailscale-User-Login), si viene
    dispositivo: Dispositivo | None = None


@dataclass
class _Codigo:
    expira: float
    nombre: str


class Dispositivos:
    """Registro de dispositivos emparejados (data/dispositivos.json) y códigos de emparejado (en memoria)."""

    def __init__(self, path: Path, reloj=time.time):
        self.path = path
        self.reloj = reloj
        self._lock = threading.Lock()
        self._codigos: dict[str, _Codigo] = {}
        self._intentos: deque[float] = deque()
        self._guardado: dict[str, float] = {}
        self.items: dict[str, Dispositivo] = {}
        self._cargar()

    # --- disco ---------------------------------------------------------------
    def _cargar(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for d in data.get("dispositivos", []):
                disp = Dispositivo(**{k: d.get(k) for k in Dispositivo.__dataclass_fields__})
                if disp.id and disp.hash:
                    self.items[disp.id] = disp
        except (OSError, ValueError, TypeError) as e:
            # Un archivo roto no debe abrir la puerta: sin registro legible no entra nadie de fuera.
            print(f"Aviso: no se pudo leer {self.path}: {e}. Ningún dispositivo podrá entrar hasta arreglarlo.",
                  file=sys.stderr)
            self.items = {}

    def _guardar(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        data = {"version": 1, "dispositivos": [asdict(d) for d in self.items.values()]}
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    # --- emparejar -------------------------------------------------------------
    def nuevo_codigo(self, nombre: str | None = None) -> tuple[str, float]:
        with self._lock:
            t = self.reloj()
            self._podar(t)
            if len(self._codigos) >= MAX_CODIGOS:
                # el más viejo deja de valer: nunca hay más de MAX_CODIGOS abiertos
                viejo = min(self._codigos, key=lambda k: self._codigos[k].expira)
                del self._codigos[viejo]
            codigo = secrets.token_urlsafe(16)
            expira = t + CODIGO_MIN * 60
            self._codigos[_hash(codigo)] = _Codigo(expira, nombre_limpio(nombre))
            return codigo, expira

    def _podar(self, t: float) -> None:
        for k in [k for k, c in self._codigos.items() if c.expira <= t]:
            del self._codigos[k]
        while self._intentos and self._intentos[0] < t - 60:
            self._intentos.popleft()

    def emparejar(self, codigo: str, nombre: str | None, origen: str | None) -> tuple[str, Dispositivo]:
        """Cambia un código válido por una llave nueva. La llave solo se devuelve aquí."""
        with self._lock:
            t = self.reloj()
            self._podar(t)
            if len(self._intentos) >= INTENTOS_MAX:
                raise AccesoError("Demasiados intentos. Espera un minuto.", 429)
            self._intentos.append(t)
            pend = self._codigos.pop(_hash(str(codigo or "")), None)
            if pend is None:
                raise AccesoError("El código no vale: ha caducado o ya se usó. Genera otro QR en el PC.", 403)
            llave = secrets.token_urlsafe(32)
            disp = Dispositivo(id=secrets.token_hex(4), nombre=nombre_limpio(nombre, pend.nombre), hash=_hash(llave),
                               creado=ahora_iso(), ultimo_uso=ahora_iso(), ultimo_origen=origen)
            while disp.id in self.items:
                disp.id = secrets.token_hex(4)
            self.items[disp.id] = disp
            self._guardar()
            return llave, disp

    # --- uso -------------------------------------------------------------------
    def verificar(self, llave: str | None) -> Dispositivo | None:
        if not llave:
            return None
        h = _hash(llave)
        encontrado = None
        for d in self.items.values():  # se recorren todos: comparación en tiempo constante
            if hmac.compare_digest(d.hash, h) and not d.revocado:
                encontrado = d
        return encontrado

    def tocar(self, disp: Dispositivo, origen: str | None) -> None:
        disp.ultimo_uso = ahora_iso()
        disp.ultimo_origen = origen or disp.ultimo_origen
        t = self.reloj()
        if t - self._guardado.get(disp.id, 0) >= GUARDAR_USO_SEG:
            self._guardado[disp.id] = t
            with self._lock:
                self._guardar()

    def revocar(self, id_: str) -> Dispositivo:
        with self._lock:
            disp = self.items.get(id_)
            if disp is None:
                raise AccesoError("No existe ese dispositivo", 404)
            if not disp.revocado:
                disp.revocado = ahora_iso()
                self._guardar()
            return disp

    def lista(self) -> list[dict[str, Any]]:
        return sorted((d.publico() for d in self.items.values()), key=lambda d: d["creado"], reverse=True)


# --- Tailscale ------------------------------------------------------------------
def _tailscale_exe() -> str | None:
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for cand in (r"C:\Program Files\Tailscale\tailscale.exe", "/usr/bin/tailscale", "/usr/local/bin/tailscale",
                 "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if Path(cand).exists():
            return cand
    return None


def _ts_json(exe: str, *args: str) -> Any:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=6, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:200] or f"código {r.returncode}")
    return json.loads(r.stdout or "null")


def analizar_serve(cfg: Any, puerto: int) -> tuple[bool, bool]:
    """(sirve Skynet, funnel activo) a partir de `tailscale serve status --json`."""
    if not isinstance(cfg, dict):
        return False, False
    sirve = False
    for web in (cfg.get("Web") or {}).values():
        for h in ((web or {}).get("Handlers") or {}).values():
            proxy = str((h or {}).get("Proxy") or "")
            if proxy.rstrip("/").endswith(f":{puerto}") or proxy == str(puerto):
                sirve = True
    funnel = any(bool(v) for v in (cfg.get("AllowFunnel") or {}).values())
    return sirve, funnel


def estado_tailscale(puerto: int, exe: str | None = None) -> dict[str, Any]:
    """Qué hay de Tailscale en este PC. Nunca lanza: si algo falla, lo cuenta en «detalle»."""
    out: dict[str, Any] = {"instalado": False, "conectado": False, "nombre_dns": None, "serve": None,
                           "funnel": None, "detalle": ""}
    exe = exe or _tailscale_exe()
    if not exe:
        out["detalle"] = "Tailscale no está instalado en este PC."
        return out
    out["instalado"] = True
    try:
        st = _ts_json(exe, "status", "--json") or {}
    except Exception as e:
        out["detalle"] = f"Tailscale instalado pero no responde: {e}"
        return out
    yo = st.get("Self") or {}
    out["conectado"] = st.get("BackendState") == "Running"
    dns = str(yo.get("DNSName") or "").rstrip(".")
    out["nombre_dns"] = dns or None
    if not out["conectado"]:
        out["detalle"] = "Tailscale está instalado pero desconectado: ábrelo e inicia sesión."
        return out
    try:
        sirve, funnel = analizar_serve(_ts_json(exe, "serve", "status", "--json"), puerto)
        out["serve"], out["funnel"] = sirve, funnel
    except Exception as e:
        out["detalle"] = f"No pude leer «tailscale serve status»: {e}"
        return out
    if funnel:
        out["detalle"] = "Funnel está activado: eso publica en internet. Desactívalo con «tailscale funnel off»."
    elif not sirve:
        out["detalle"] = f"Falta publicar Skynet en tu red privada: en una terminal, «tailscale serve --bg {puerto}»."
    else:
        out["detalle"] = "Listo: Skynet es visible solo dentro de tu red de Tailscale."
    return out


class EstadoAcceso:
    """Estado de Tailscale con caché corta (lanzar el CLI tarda) y la URL que verá el móvil."""

    def __init__(self, puerto: int, url_fija: str | None = None, sondeo=estado_tailscale):
        self.puerto = puerto
        self.url_fija = (url_fija or "").rstrip("/") or None
        self.sondeo = sondeo
        self._cache: tuple[float, dict[str, Any]] | None = None

    def tailscale(self, fresco: bool = False) -> dict[str, Any]:
        t = time.monotonic()
        if fresco or self._cache is None or t - self._cache[0] > TAILSCALE_CACHE_SEG:
            self._cache = (t, self.sondeo(self.puerto))
        return self._cache[1]

    def url(self, ts: dict[str, Any]) -> str | None:
        if self.url_fija:
            return self.url_fija
        if ts.get("nombre_dns") and ts.get("conectado") and ts.get("serve") is not False and not ts.get("funnel"):
            return f"https://{ts['nombre_dns']}"
        return None

    def resumen(self, fresco: bool = False) -> dict[str, Any]:
        ts = self.tailscale(fresco)
        return {"url": self.url(ts), "tailscale": ts}


def enlace_emparejar(url: str | None, codigo: str) -> str | None:
    if not url:
        return None
    return f"skynet://emparejar?u={quote(url, safe='')}&c={quote(codigo, safe='')}"


@dataclass
class ConfigAcceso:
    url: str | None = None
    origenes: tuple[str, ...] = ORIGENES
    usuarios: tuple[str, ...] = ()        # si no está vacío, solo esas cuentas de Tailscale
    hosts: tuple[str, ...] = ()           # Host permitidos además de *.ts.net
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def desde(cls, raw: dict[str, Any] | None) -> "ConfigAcceso":
        raw = dict(raw or {})
        return cls(
            url=(str(raw.get("url") or "").strip() or None),
            origenes=tuple(str(o).rstrip("/") for o in raw.get("origenes", ORIGENES)),
            usuarios=tuple(str(u).lower() for u in raw.get("usuarios_tailscale", ())),
            hosts=tuple(str(h).lower() for h in raw.get("hosts", ())),
            extra=raw,
        )

    def host_valido(self, host: str) -> bool:
        nombre = host.rsplit(":", 1)[0].lower() if not host.startswith("[") else host.lower()
        return nombre.endswith(".ts.net") or nombre in self.hosts
