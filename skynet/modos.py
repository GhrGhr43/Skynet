"""Modos de permisos por modelo y modelos en la nube activados.

Cada modelo tiene un modo que decide hasta dónde llega en el PC:
  repo     Solo repo       lee, edita y ejecuta tests solo dentro del repo autorizado (lo de siempre)
  lectura  Ver mi PC       además puede leer archivos de todo el PC (sin escribir ni ejecutar)
  editar   Ver y editar    además puede crear y editar archivos de tu usuario (sin ejecutar)
  total    Control total   además ejecuta comandos y abre programas (p. ej. instalar un juego de Steam)
En cualquier modo se pregunta siempre: administrador, carpetas del sistema, borrar y secretos.

Los modos se guardan en data/permisos_modelos.json. Los modelos en la nube empiezan desactivados en
cada arranque de Skynet: activarlos pide una confirmación explícita (no se recuerda entre sesiones).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings


@dataclass(frozen=True)
class Modo:
    clave: str
    nombre: str
    descripcion: str
    fuerte: bool  # sale del repo con escritura o ejecución: con un modelo en la nube pide aviso


MODOS: dict[str, Modo] = {m.clave: m for m in (
    Modo("repo", "Solo repo", "Lee, edita y ejecuta tests solo dentro del repo autorizado.", False),
    Modo("lectura", "Ver mi PC", "Además puede leer archivos de todo tu PC. No escribe ni ejecuta nada fuera del repo.", False),
    Modo("editar", "Ver y editar", "Además puede crear y editar archivos de tu usuario. No ejecuta programas.", True),
    Modo("total", "Control total", "Además ejecuta comandos y abre programas, por ejemplo Steam para instalar un juego.", True),
)}
ORDEN = list(MODOS)  # de menos a más permisos
POR_DEFECTO = "repo"

SIEMPRE = ("Siempre se pregunta, en cualquier modo: pedir administrador, tocar carpetas del sistema "
           "(Windows, Program Files, registro), borrar archivos y leer contraseñas, claves o cookies.")

AVISO_NUBE = ("{modelo} es un modelo en la nube: todo lo que lea de tu PC (archivos, salidas de comandos) "
              "se envía a los servidores de su proveedor. Con el modo «{modo}» además podrá {accion} sin "
              "preguntarte. Recomendado solo para modelos locales.")
ACCIONES = {"editar": "crear y editar archivos de tu usuario", "total": "ejecutar comandos e instalar programas"}

CONFIRMAR_NUBE = ("{modelo} funciona en la nube: tus mensajes y lo que Skynet lea para la tarea salen de tu PC "
                  "hacia su proveedor. Por defecto Skynet usa solo el modelo local. ¿Activar {modelo} para esta sesión?")


def modo_valido(clave: str) -> bool:
    return clave in MODOS


def aviso_nube(modelo: str, modo: str) -> str:
    return AVISO_NUBE.format(modelo=modelo, modo=MODOS[modo].nombre, accion=ACCIONES.get(modo, "salir del repo"))


@dataclass
class Accesos:
    """Modo de cada modelo (persistente) y modelos en la nube activados (solo esta sesión)."""

    settings: Settings
    path: Path | None = None
    modos: dict[str, str] = field(default_factory=dict)
    nube_activada: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.path is None:
            self.path = self.settings.db_path.parent / "permisos_modelos.json"
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.modos = {k: v for k, v in raw.get("modos", {}).items() if modo_valido(v)}
        except (OSError, ValueError, AttributeError):
            self.modos = {}

    # --- modos -------------------------------------------------------------
    def modo(self, modelo: str) -> str:
        return self.modos.get(modelo, POR_DEFECTO)

    def set_modo(self, modelo: str, modo: str) -> None:
        if modelo not in self.settings.models:
            raise ValueError(f"Modelo desconocido: {modelo}")
        if not modo_valido(modo):
            raise ValueError(f"Modo desconocido: {modo}. Modos: {', '.join(ORDEN)}")
        self.modos[modelo] = modo
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"modos": self.modos}, indent=2, ensure_ascii=False), encoding="utf-8")

    def necesita_aviso(self, modelo: str, modo: str) -> bool:
        """Un modo fuerte en un modelo en la nube pide confirmar el aviso."""
        return self.es_nube(modelo) and MODOS[modo].fuerte

    # --- nube --------------------------------------------------------------
    def es_nube(self, modelo: str) -> bool:
        p = self.settings.models.get(modelo)
        return p is not None and not p.privado

    def nube_ok(self, modelo: str) -> bool:
        return not self.es_nube(modelo) or modelo in self.nube_activada

    def activar_nube(self, modelo: str, on: bool) -> None:
        if not self.es_nube(modelo):
            raise ValueError(f"{modelo} no es un modelo en la nube")
        if on:
            self.nube_activada.add(modelo)
        else:
            self.nube_activada.discard(modelo)
