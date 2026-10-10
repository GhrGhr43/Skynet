"""Motor «hermes»: Hermes Agent como cerebro de Skynet, en Docker (ver D19 en docs/DECISIONES.md).

No es un servidor MCP: es el lanzador que usa el motor `hermes` de skynet.toml (tipo "proceso").
- `serve`: prepara los datos de Hermes y arranca su servidor de API en primer plano (contenedor
  `skynet-hermes`, solo publicado en 127.0.0.1). Skynet espera a que /health diga ok.
- `stop`: para el contenedor.

Hermes guarda su memoria y sus skills en HERMES_DATOS (montado en /opt/data): sobreviven a reinicios.
Ve las carpetas de HERMES_CARPETAS (montadas en /c/...), salvo las de HERMES_OCULTAR, que se tapan con
una carpeta vacía (secretos: AppData, .ssh...). Dentro del contenedor ejecuta sin preguntar: la barrera es
el contenedor. Dos alias de modelo: `local` (el llama-server de Skynet) y `nube` (si se configura).
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

NOMBRE = "skynet-hermes"
PUERTO = 8642

# Se ejecuta dentro del contenedor con el Python de Hermes: mezcla nuestras claves en su config.yaml (sin pisar
# lo demás que Daniel configure en Hermes) y añade a SOUL.md cómo se ven las rutas de Windows.
MEZCLA = r"""
import json, os, pathlib
from ruamel.yaml import YAML  # la que trae Hermes (no lleva PyYAML); conserva sus comentarios
yaml = YAML()
def mezclar(a, b):
    for k, v in b.items():
        a[k] = mezclar(a[k], v) if isinstance(v, dict) and isinstance(a.get(k), dict) else v
    return a
cfg_path = pathlib.Path('/opt/data/config.yaml')
cfg = (yaml.load(cfg_path.read_text(encoding='utf-8')) if cfg_path.exists() else None) or {}
mezclar(cfg, json.loads(os.environ['SKYNET_HERMES_CFG']))
with cfg_path.open('w', encoding='utf-8') as f:
    yaml.dump(cfg, f)
soul = pathlib.Path('/opt/data/SOUL.md')
nota = os.environ['SKYNET_HERMES_NOTA']
texto = soul.read_text(encoding='utf-8') if soul.exists() else ''
if '## Entorno (Skynet)' not in texto:
    soul.write_text(texto.rstrip() + '\n\n' + nota + '\n', encoding='utf-8')
"""


def docker() -> str:
    return shutil.which("docker") or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"


def en_contenedor(ruta: str) -> str:
    """C:\\Users\\HACHO -> /c/Users/HACHO (misma forma que Git Bash: fácil de traducir para el modelo)."""
    p = Path(ruta)
    drive = p.drive.rstrip(":").lower()
    return "/" + drive + "/" + "/".join(p.parts[1:]) if drive else p.as_posix()


def clave(ruta: Path) -> str:
    """Clave de la API de Hermes: se crea una vez y Skynet la lee del mismo archivo (api_key_archivo)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not ruta.exists() or not ruta.read_text(encoding="utf-8").strip():
        ruta.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return ruta.read_text(encoding="utf-8").strip()


def config(carpetas: list[str]) -> dict:
    local_url = os.environ.get("HERMES_MODELO_LOCAL_URL", "http://host.docker.internal:8090/v1")
    contexto = int(os.environ.get("HERMES_CONTEXTO", "65536"))
    rutas = {"local": {"model": "local", "provider": "custom", "base_url": local_url, "api_key": "local"}}
    proveedor, modelo = os.environ.get("HERMES_NUBE_PROVEEDOR", ""), os.environ.get("HERMES_NUBE_MODELO", "")
    if proveedor and modelo:  # la clave del proveedor va en el .env de Hermes (HERMES_DATOS/.env), no aquí
        rutas["nube"] = {"model": modelo, "provider": proveedor}
    return {
        "model": {"provider": "custom", "base_url": local_url, "api_key": "local", "default": "local",
                  "context_length": contexto},
        "terminal": {"backend": "local", "cwd": en_contenedor(carpetas[0]) if carpetas else "/opt/data"},
        "approvals": {"mode": "off", "unattended_mode": "approve"},
        "platforms": {"api_server": {"enabled": True, "extra": {"model_routes": rutas}}},
    }


def nota(carpetas: list[str]) -> str:
    vistas = "; ".join(f"{c} está en {en_contenedor(c)}" for c in carpetas) or "ninguna carpeta de Windows"
    return ("## Entorno (Skynet)\nTrabajas dentro de un contenedor Linux lanzado por Skynet, el agente personal de "
            f"Daniel. Carpetas de Windows montadas: {vistas}. Traduce las rutas de Windows a esas. No ves AppData, "
            ".ssh ni credenciales. Responde en español.")


def serve() -> int:
    datos = Path(os.environ.get("HERMES_DATOS") or Path.home() / ".hermes-skynet")
    datos.mkdir(parents=True, exist_ok=True)
    carpetas = [c for c in os.environ.get("HERMES_CARPETAS", str(Path.home())).split(";") if c and Path(c).exists()]
    key = clave(Path(os.environ.get("HERMES_CLAVE") or datos / "api_key"))
    subprocess.run([docker(), "rm", "-f", NOMBRE], capture_output=True)  # uno que quedara de antes
    cmd = [docker(), "run", "--rm", "--name", NOMBRE, "-p", f"127.0.0.1:{PUERTO}:{PUERTO}",
           "-v", f"{datos}:/opt/data",
           "-e", "API_SERVER_ENABLED=true", "-e", f"API_SERVER_KEY={key}", "-e", "API_SERVER_HOST=0.0.0.0",
           "-e", f"API_SERVER_PORT={PUERTO}", "-e", f"SKYNET_HERMES_CFG={json.dumps(config(carpetas))}",
           "-e", f"SKYNET_HERMES_NOTA={nota(carpetas)}", "-e", f"SKYNET_HERMES_MEZCLA={MEZCLA}"]
    for c in carpetas:
        cmd += ["-v", f"{c}:{en_contenedor(c)}"]
    for sub in os.environ.get("HERMES_OCULTAR", "").split(";"):
        for c in carpetas:
            if sub and (Path(c) / sub).exists():
                cmd += ["--tmpfs", f"{en_contenedor(c)}/{sub.replace(os.sep, '/')}"]
    cmd += [os.environ.get("HERMES_IMAGEN", "skynet/hermes:latest"), "sh", "-c",
            '/opt/hermes/.venv/bin/python -c "$SKYNET_HERMES_MEZCLA" && exec hermes gateway run']
    return subprocess.call(cmd)


def stop() -> int:
    return subprocess.call([docker(), "stop", "-t", "20", NOMBRE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    sys.exit(stop() if sys.argv[1:2] == ["stop"] else serve())


if __name__ == "__main__":
    main()
