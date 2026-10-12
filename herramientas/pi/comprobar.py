"""Prueba real del adaptador con el modelo local; trabaja en una carpeta de pruebas."""
import asyncio
import json
import sys
from pathlib import Path

from skynet.config import add_repo, load_settings
from skynet.coordinator import Coordinator
from skynet.runtime import Runtime
from skynet.cli import ConsoleUI, _prepare_env


class PruebaUI(ConsoleUI):
    async def ask(self, prompt):
        print("Permiso no concedido en la prueba: " + prompt[:160], flush=True)
        return "n"


async def main():
    settings = load_settings()
    web = "--web" in sys.argv
    root = settings.home / "proyectos" / "prueba-pi" if web else settings.home / "data" / "pruebas" / "pi" / "smoke"
    root.mkdir(parents=True, exist_ok=True)
    name = "prueba-pi" if web else "pi-smoke"
    command = f'python "{(settings.home / "herramientas/pi/verificar_web.py").as_posix()}"' if web else "python -m pytest -q"
    repo = settings.repos.get(name) or add_repo(settings.home, name, root, command)
    settings.repos[repo.nombre] = repo
    rt = Runtime(settings)
    ui = PruebaUI()
    c = Coordinator(rt, ui)
    c.repo_name, c.coder, c.coder_motor = repo.nombre, True, "pi"
    try:
        prompt = ("Crea una página web index.html autocontenida en español, sin recursos externos, de un contador. "
                  "Diseño oscuro con acento turquesa, bonito y adaptable a móvil. Número en #numero, botón #sumar "
                  "incrementa exactamente en uno y botón #reiniciar vuelve a cero. Guarda automáticamente con "
                  "localStorage. Al cargar recupera el valor. Comprueba ambos botones con navegador__comprobar_html "
                  "usando acciones. Pide al menos una captura con captura=true, mírala y describe el color principal. "
                  "Comprueba 390px y pasa el verificador. Deja ABRIR.md con cómo abrir el HTML." if web else
                  "Crea limites.py con limitar(valor, minimo, maximo): devuelve valor dentro del intervalo cerrado, "
            "incluidos extremos; si minimo > maximo lanza ValueError. Añade tests con pytest para los casos de abajo, "
            "dentro, encima, extremos e intervalo inválido. Ejecuta python -m pytest -q y comprueba el resultado.")
        task = await c.new_task(prompt)
        proof = {"tarea": task.id, "estado": task.status, "resumen": task.result_summary,
                 "consumo": rt.store.totals(task_id=task.id)}
        evidence = settings.home / "data" / "pruebas" / "pi"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / ("resultado-web.json" if web else "resultado.json")).write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(proof, ensure_ascii=False), flush=True)
        if task.status != "hecha":
            raise RuntimeError("La prueba de Pi no terminó: " + str(task.result_summary))
    finally:
        rt.store.close()


if __name__ == "__main__":
    _prepare_env()
    asyncio.run(main())
