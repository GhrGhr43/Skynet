"""Modelos locales (GGUF de la carpeta de LM Studio): listarlos y elegir cuál usa el motor «local».

La elección se guarda en data/modelo_local.json y se aplica encima de [motores.local] de skynet.toml.
Cada modelo lleva los ajustes del benchmark para una GPU de 16 GB: FA, KV q4_0 (a 64K rinde igual que q8_0 y
cabe el IQ3_S con MTP; ver docs/COMPARATIVA-HERMES.md), MTP en los densos
Qwen3.5+ (si el GGUF no lo trae, el motor reintenta sin él), expertos en RAM en los MoE y mmproj si hay visión.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE") or Path.home())
CARPETAS = [HOME / ".lmstudio" / "models"]
NO_CHAT = ("embed", "mmproj", "mtp-", "reranker", "whisper")
BASE = ["-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0", "-np", "1", "--no-webui"]


@dataclass
class Local:
    nombre: str
    ruta: Path
    gb: float
    moe: bool = False
    mtp: bool = False
    mmproj: Path | None = None

    def args(self, con_mtp: bool = True) -> list[str]:
        a = list(BASE)
        if self.moe:
            a += ["--n-cpu-moe", "13" if self.gb < 30 else "999"]
        if self.mtp and con_mtp:
            a += ["--spec-type", "draft-mtp"]
        if self.mmproj:
            a += ["--mmproj", str(self.mmproj)]
        return a

    def info(self) -> dict:
        nota = [f"{self.gb:.1f} GB"] + (["MoE, expertos en RAM"] if self.moe else []) + \
               (["MTP"] if self.mtp else []) + (["visión"] if self.mmproj else [])
        return {"nombre": self.nombre, "ruta": str(self.ruta), "detalle": ", ".join(nota)}


def buscar(carpetas: list[Path] | None = None) -> list[Local]:
    out = []
    for base in carpetas if carpetas is not None else CARPETAS:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.gguf")):
            low = p.name.lower()
            if any(k in low for k in NO_CHAT):
                continue
            m = re.search(r"-(\d{5})-of-(\d{5})\.gguf$", p.name)
            if m and m.group(1) != "00001":
                continue
            partes = sorted(p.parent.glob(re.sub(r"-\d{5}-of-", "-*-of-", p.name))) if m else [p]
            gb = sum(x.stat().st_size for x in partes) / 1e9
            moe = bool(re.search(r"-A\d+B|flash-next|moe|-\d+x\d+b", low, re.I))
            out.append(Local(re.sub(r"(-\d{5}-of-\d{5})?\.gguf$", "", p.name), p, gb, moe,
                             not moe and bool(re.search(r"qwen3\.[5-9]", low)),
                             next(iter(sorted(p.parent.glob("mmproj*.gguf"))), None)))
    return out


def archivo(data_dir: Path) -> Path:
    return data_dir / "modelo_local.json"


def elegido(data_dir: Path) -> str:
    try:
        return json.loads(archivo(data_dir).read_text(encoding="utf-8")).get("nombre", "")
    except (OSError, ValueError):
        return ""


def guardar(data_dir: Path, nombre: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    archivo(data_dir).write_text(json.dumps({"nombre": nombre}), encoding="utf-8")
