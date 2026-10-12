"""Prepara el proyecto de pruebas y reutiliza el motor local de Skynet."""
from pathlib import Path

from skynet.config import add_repo, load_settings
from skynet.engines import load_engines
from skynet_tools.pi_agent import configure, installation


def preparar(encender=True):
    settings = load_settings()
    installation(settings.home)
    root = settings.home / "proyectos" / "prueba-pi"
    root.mkdir(parents=True, exist_ok=True)
    repo = settings.repos.get("prueba-pi") or add_repo(settings.home, "prueba-pi", root)
    configure(settings.home, settings.models["local"], True,
              "thinking_budget_tokens" if settings.engines["local"]["tipo"] == "llamacpp" else None)
    if encender:
        engines = load_engines(settings.engines, settings.logs_dir, settings.home)
        print(engines.start("local"))
    print("Proyecto para tus pruebas: " + str(root))
    return repo


if __name__ == "__main__":
    preparar()
