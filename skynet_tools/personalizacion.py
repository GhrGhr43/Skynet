"""Opciones del motor y memoria aprobada; no añade un bucle de razonamiento."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import uuid
from urllib.parse import urlparse

NATIVAS = ("read", "bash", "edit", "write")


class Personalizacion:
    def __init__(self, home: Path):
        self.home = home
        self.path = home / "data" / "personalizacion.json"
        self.lock = threading.RLock()
        self._modelos_base = None
        self.data = {"harness": "pi", "harnesses": {"pi": {"nombre": "Pi", "protocolo": "pi-rpc"}},
                     "herramientas": list(NATIVAS), "mcp_activo": False, "mcp": {},
                     "memoria_activa": False, "memoria": [], "contexto": 65536,
                     "mtp": True, "vision_gpu": False, "cache_kv": "f16", "modelos": {}, "skills": []}
        if self.path.is_file():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        else:
            for name, destino in (("USER", "usuario"), ("MEMORY", "entorno")):
                original = home / "memoria" / f"{name}.md"
                if original.is_file():
                    for line in original.read_text(encoding="utf-8").splitlines():
                        if line.startswith("- "):
                            self.data["memoria"].append({"id": uuid.uuid5(uuid.NAMESPACE_URL, str(original) + line).hex,
                                "texto": line[2:][:500], "destino": destino, "aprobada": False})

    def guardar(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)

    def cambiar(self, changes: dict):
        with self.lock:
            result = dict(self.data)
            allowed = {"harness", "harnesses", "herramientas", "mcp_activo", "mcp",
                       "memoria_activa", "contexto", "mtp", "vision_gpu", "cache_kv", "modelos", "skills"}
            if set(changes) - allowed:
                raise ValueError("Opción desconocida")
            result.update(changes)
            for key in ("mcp_activo", "memoria_activa", "mtp", "vision_gpu"):
                if not isinstance(result[key], bool):
                    raise ValueError(f"{key} debe ser verdadero o falso")
            if type(result["contexto"]) is not int or not 2048 <= result["contexto"] <= 262144:
                raise ValueError("Contexto: entre 2048 y 262144 tokens")
            if result["cache_kv"] not in ("f16", "q8_0", "q4_0"):
                raise ValueError("Caché KV: f16, q8_0 o q4_0")
            if not isinstance(result["herramientas"], list) or not all(isinstance(t, str) and t in NATIVAS for t in result["herramientas"]):
                raise ValueError("Herramientas nativas: read, bash, edit y write")
            if not isinstance(result["skills"], list) or not all(isinstance(p, str) for p in result["skills"]):
                raise ValueError("Skills: lista de rutas")
            if not isinstance(result["harnesses"], dict) or result["harness"] not in result["harnesses"]:
                raise ValueError("Harness no registrado")
            for name, spec in result["harnesses"].items():
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or not isinstance(spec, dict) or spec.get("protocolo") != "pi-rpc":
                    raise ValueError("Esta versión admite motores compatibles con Pi RPC; otros necesitan adaptador")
                if name != "pi" and (not isinstance(spec.get("comando"), str) or not spec["comando"].strip() or
                        not isinstance(spec.get("args", []), list) or not all(isinstance(a, str) for a in spec.get("args", []))):
                    raise ValueError("Indica comando y lista de argumentos del harness")
            if not isinstance(result["mcp"], dict):
                raise ValueError("MCP debe ser un objeto de servidores")
            for name, spec in result["mcp"].items():
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or not isinstance(spec, dict):
                    raise ValueError("Nombre o servidor MCP inválido")
                if not (spec.get("command") or spec.get("url")):
                    raise ValueError("Cada MCP necesita command o url")
                if "enabled" in spec and not isinstance(spec["enabled"], bool):
                    raise ValueError("enabled debe ser verdadero o falso")
                if spec.get("url") and (not isinstance(spec["url"], str) or urlparse(spec["url"]).scheme not in ("http", "https") or not urlparse(spec["url"]).hostname):
                    raise ValueError("URL MCP: http o https")
                if "command" in spec and (not isinstance(spec["command"], str) or not spec["command"].strip()):
                    raise ValueError("Comando MCP inválido")
                if not isinstance(spec.get("args", []), list) or not all(isinstance(a, str) for a in spec.get("args", [])):
                    raise ValueError("Argumentos MCP: lista de textos")
                if spec.get("exposure", "deferred") not in ("deferred", "direct", "hidden"):
                    raise ValueError("Exposición MCP: deferred, direct o hidden")
                for key in ("env", "headers"):
                    if not isinstance(spec.get(key, {}), dict) or not all(isinstance(v, str) for v in spec.get(key, {}).values()):
                        raise ValueError(f"{key}: objeto de textos")
            if len({n.replace("-", "_") for n in result["mcp"]}) != len(result["mcp"]):
                raise ValueError("Dos servidores MCP comparten el mismo nombre normalizado")
            if not isinstance(result["modelos"], dict):
                raise ValueError("Modelos: objeto de perfiles")
            for name, model in result["modelos"].items():
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or name == "local":
                    raise ValueError("Nombre de modelo inválido o reservado")
                if not isinstance(model, dict) or not isinstance(model.get("api_base"), str) or not model["api_base"].startswith(("http://", "https://")) or not isinstance(model.get("id"), str) or not model["id"].strip():
                    raise ValueError("Cada modelo necesita endpoint e id")
                url = urlparse(model["api_base"])
                if not url.hostname or (model.get("privado", True) and url.hostname not in ("localhost", "127.0.0.1", "::1")):
                    raise ValueError("Un modelo privado debe tener un endpoint local")
                if not isinstance(model.get("privado", True), bool):
                    raise ValueError("privado debe ser verdadero o falso")
                for key, default in (("contexto", result["contexto"]), ("max_tokens", 8192)):
                    if type(model.get(key, default)) is not int or not 256 <= model.get(key, default) <= 262144:
                        raise ValueError(f"{key} del modelo: entero entre 256 y 262144")
                if model.get("razonamiento", "medium") not in (None, "off", "minimal", "low", "medium", "high", "xhigh"):
                    raise ValueError("Nivel de razonamiento desconocido")
                if model.get("api_key_env") is not None and (not isinstance(model["api_key_env"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", model["api_key_env"])):
                    raise ValueError("api_key_env: nombre de variable de entorno")
            self.data = result
            self.guardar()

    def proponer_memoria(self, texto: str, destino: str = "usuario") -> dict:
        if destino not in ("usuario", "entorno") or not isinstance(texto, str) or not texto.strip() or len(texto) > 500 or "\n" in texto:
            raise ValueError("Una entrada de memoria por vez, de 1 a 500 caracteres")
        from skynet.memoria import SECRETO
        if SECRETO.search(texto):
            raise ValueError("No guardes credenciales o secretos en memoria")
        with self.lock:
            entry = {"id": uuid.uuid4().hex, "texto": texto.strip(), "destino": destino, "aprobada": False}
            self.data["memoria"].append(entry)
            self.guardar()
            return dict(entry)

    def revisar_memoria(self, entry_id: str, aprobar: bool):
        with self.lock:
            entry = next((e for e in self.data["memoria"] if e["id"] == entry_id), None)
            if entry is None:
                raise ValueError("Entrada no encontrada")
            if aprobar:
                entry["aprobada"] = True
            else:
                self.data["memoria"].remove(entry)
            self.guardar()

    def memoria_aprobada(self) -> str:
        if not self.data["memoria_activa"]:
            return ""
        return "\n".join("- " + e["texto"] for e in self.data["memoria"] if e["aprobada"])[:4000]

    def aplicar_modelos(self, settings):
        from skynet.config import ModelProfile
        if self._modelos_base is None:
            self._modelos_base = dict(settings.models)
        settings.models.clear()
        settings.models.update(self._modelos_base)
        for name, model in self.data["modelos"].items():
            settings.models[name] = ModelProfile(nombre=name, litellm="openai/" + model["id"],
                api_base=model["api_base"], api_key_env=model.get("api_key_env"), privado=bool(model.get("privado", True)),
                contexto_tokens=int(model.get("contexto", self.data["contexto"])),
                max_tokens=int(model.get("max_tokens", 8192)), reasoning_effort=model.get("razonamiento", "medium"))

    def mcp_config(self, repo: Path | None, modo: str = "repo", internet: bool = True) -> dict:
        servers = {}
        if self.data["mcp_activo"]:
            for name, spec in self.data["mcp"].items():
                if not spec.get("enabled", False):
                    continue
                if name in ("internet", "navegador") and not internet:
                    continue
                raw = json.dumps(spec).replace("{repo}", str(repo or self.home).replace("\\", "/"))
                raw = raw.replace("{home}", str(self.home).replace("\\", "/"))
                raw = raw.replace("{modo}", modo)
                servers[name] = json.loads(raw)
                if "args" in servers[name]:
                    servers[name]["args"] = [os.path.expandvars(a) for a in servers[name]["args"]]
                if name == "vision" and "--modo" not in servers[name].get("args", []):
                    servers[name].setdefault("args", []).extend(["--modo", modo])
                servers[name].setdefault("exposure", "deferred")
        return {"mcpServers": servers}

    def internet(self, activo: bool):
        """El globo controla búsqueda y navegador; otros MCP mantienen su selección."""
        servers = {n: dict(s) for n, s in self.data["mcp"].items()}
        for name in ("internet", "navegador"):
            if name in servers:
                servers[name]["enabled"] = activo
        self.cambiar({"mcp": servers, **({"mcp_activo": True} if activo else {})})
