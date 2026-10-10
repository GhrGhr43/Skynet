"""Tareas cortas que miden calidad agéntica más allá de «leer, editar y probar».

Cada tarea trae su propia comprobación oculta (`check(repo, info)`), sin LLM:
- regresion: usar git para encontrar el commit culpable de un fallo.
- restricciones: optimizar sin cambiar el comportamiento (también con elementos no hasheables)
  ni tocar los tests existentes.
- multiarchivo: un cambio coherente que atraviesa modelo, CSV, informe y CLI.
- proyecto: una CLI desde cero que cumpla una especificación, probada como caja negra.
- memoria: dos sesiones; en la segunda tiene que aplicar lo que se le dijo en la primera.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

PYTEST_INI = "[pytest]\ntestpaths = tests\n"
CONFTEST = "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def write_files(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def commit(repo: Path, msg: str) -> str:
    if not (repo / ".git").exists():
        _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=Daniel", "-c", "user.email=daniel@example.com", "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def run_hidden(repo: Path, test_code: str, extra_paths: tuple[str, ...] = ()) -> tuple[bool, str]:
    hd = repo / "_verificador_oculto"
    hd.mkdir(exist_ok=True)
    (hd / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (hd / "test_oculto.py").write_text(test_code, encoding="utf-8")
    paths = [str(hd)] + [p for p in extra_paths if (repo / p).exists()]
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "testpaths=", *paths],
                           cwd=repo, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "timeout (se cuelga)"
    out = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, (out[-1] if out else "")


# --- 1. regresion -----------------------------------------------------------------------------
def build_regresion(repo: Path) -> dict:
    write_files(repo, {
        "pytest.ini": PYTEST_INI, "tests/conftest.py": CONFTEST, "tienda/__init__.py": "",
        "tienda/precios.py": "IVA = 0.21\n\n\ndef con_iva(base: float) -> float:\n"
                             "    return round(base * (1 + IVA) + 1e-9, 2)\n",
        "tienda/factura.py": "from .precios import con_iva\n\n\ndef total_factura(lineas):\n"
                             "    return con_iva(sum(p * c for p, c in lineas))\n",
        "tests/test_factura.py": "from tienda.factura import total_factura\n\n\n"
                                 "def test_basico():\n    assert total_factura([(10.0, 2)]) == 24.2\n",
        "README.md": "# Tienda\n",
    })
    commit(repo, "Primera versión de la tienda")
    culprit = ""
    pasos = [
        ("Añade descripción al README", {"README.md": "# Tienda\n\nCálculo de facturas con IVA.\n"}),
        ("Añade módulo de clientes", {"tienda/clientes.py": "CLIENTES = {}\n\n\ndef alta(nombre):\n"
                                      "    CLIENTES[nombre] = {'nombre': nombre}\n    return CLIENTES[nombre]\n"}),
        ("Formato de importes", {"tienda/formato.py": "def euros(x: float) -> str:\n    return f'{x:.2f} €'\n"}),
        ("Refactor: IVA configurable y cálculo más simple",
         {"tienda/precios.py": "IVA = 0.21\n\n\ndef con_iva(base: float, iva: float = IVA) -> float:\n"
                               "    return int(base * (1 + iva) * 100) / 100\n"}),
        ("Tests de clientes", {"tests/test_clientes.py": "from tienda.clientes import alta\n\n\n"
                               "def test_alta():\n    assert alta('ana')['nombre'] == 'ana'\n"}),
        ("Docstrings", {"tienda/formato.py": "def euros(x: float) -> str:\n    \"\"\"12.5 -> '12.50 €'.\"\"\"\n"
                        "    return f'{x:.2f} €'\n"}),
        ("Cambia el README", {"README.md": "# Tienda\n\nCálculo de facturas con IVA (21 % por defecto).\n"}),
    ]
    for msg, files in pasos:
        write_files(repo, files)
        sha = commit(repo, msg)
        if msg.startswith("Refactor"):
            culprit = sha
    return {"culpable": culprit}


def check_regresion(repo: Path, info: dict) -> tuple[bool, str]:
    f = repo / "REGRESION.txt"
    hash_ok = f.exists() and info["culpable"].startswith(f.read_text(encoding="utf-8", errors="replace").strip()[:7] or "x")
    ok, line = run_hidden(repo, (
        "from tienda.precios import con_iva\nfrom tienda.factura import total_factura\n\n\n"
        "def test_redondeo():\n    assert con_iva(19.99) == 24.19\n    assert con_iva(0.05) == 0.06\n"
        "    assert total_factura([(9.99, 3)]) == 36.26\n\n\n"
        "def test_iva_configurable_sigue():\n    assert con_iva(100, 0.1) == 110.0\n"), ("tests",))
    return ok and hash_ok, f"hash {'bien' if hash_ok else 'MAL'} · {line}"


REGRESION = {
    "name": "regresion", "build": build_regresion, "check": check_regresion,
    "prompt": ("Desde hace unos días `total_factura` devuelve a veces un céntimo de menos (por ejemplo, 19.99 € "
               "con IVA debería ser 24.19 y no lo es). Usa el historial de git para averiguar en qué commit se "
               "introdujo el fallo, arréglalo sin perder lo que añadió ese commit y añade un test que lo cubra. "
               "Escribe en `REGRESION.txt` solo el hash corto (7 caracteres) del commit culpable."),
}


# --- 2. restricciones -------------------------------------------------------------------------
TEST_DUP = ("from duplicados import buscar_duplicados\n\n\n"
            "def test_basico():\n    assert buscar_duplicados([1, 2, 1, 3, 2, 1]) == [1, 2]\n\n\n"
            "def test_vacio():\n    assert buscar_duplicados([]) == []\n")


def build_restricciones(repo: Path) -> dict:
    write_files(repo, {
        "pytest.ini": PYTEST_INI, "tests/conftest.py": CONFTEST,
        "duplicados.py": ("def buscar_duplicados(items):\n"
                          "    \"\"\"Elementos que aparecen más de una vez, cada uno una sola vez, en el orden en\n"
                          "    que aparecen por primera vez.\"\"\"\n"
                          "    out = []\n    for x in items:\n        if items.count(x) > 1 and x not in out:\n"
                          "            out.append(x)\n    return out\n"),
        "tests/test_duplicados.py": TEST_DUP,
    })
    commit(repo, "inicial")
    return {"tests_hash": hashlib.sha256(TEST_DUP.encode()).hexdigest()}


def check_restricciones(repo: Path, info: dict) -> tuple[bool, str]:
    t = repo / "tests" / "test_duplicados.py"
    intactos = t.exists() and hashlib.sha256(t.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == info["tests_hash"]
    ok, line = run_hidden(repo, (
        "import time\nfrom duplicados import buscar_duplicados\n\n\n"
        "def test_orden():\n    assert buscar_duplicados(['b', 'a', 'b', 'a', 'c']) == ['b', 'a']\n"
        "    assert buscar_duplicados([3, 1, 1, 3]) == [3, 1]\n\n\n"
        "def test_no_hasheables():\n    assert buscar_duplicados([[1], [2], [1], {'a': 1}, {'a': 1}]) == [[1], {'a': 1}]\n\n\n"
        "def test_iguales_distinto_tipo():\n    assert buscar_duplicados([1, 1.0, True]) == [1]\n\n\n"
        "def test_rapido():\n    datos = list(range(100_000)) * 2\n    t0 = time.perf_counter()\n"
        "    r = buscar_duplicados(datos)\n    assert time.perf_counter() - t0 < 1.0\n    assert r[:3] == [0, 1, 2]\n"),
        ("tests",))
    return ok and intactos, f"tests {'intactos' if intactos else 'TOCADOS'} · {line}"


RESTRICCIONES = {
    "name": "restricciones", "build": build_restricciones, "check": check_restricciones,
    "prompt": ("`buscar_duplicados` es demasiado lenta con listas grandes (cientos de miles de elementos). Hazla "
               "rápida sin cambiar su comportamiento en ningún caso ni su firma. No modifiques los tests que ya "
               "existen ni añadas dependencias; si añades tests, en un archivo nuevo."),
}


# --- 3. multiarchivo --------------------------------------------------------------------------
def build_multiarchivo(repo: Path) -> dict:
    write_files(repo, {
        "pytest.ini": PYTEST_INI, "tests/conftest.py": CONFTEST, "pedidos/__init__.py": "",
        "pedidos/modelo.py": ("from dataclasses import dataclass\n\n\n@dataclass\nclass Pedido:\n"
                              "    id: int\n    cliente: str\n    importe: float\n"),
        "pedidos/csv_io.py": ("import csv\nfrom .modelo import Pedido\n\n\ndef leer(ruta):\n"
                              "    with open(ruta, newline='', encoding='utf-8') as f:\n"
                              "        return [Pedido(int(r['id']), r['cliente'], float(r['importe'])) for r in csv.DictReader(f)]\n\n\n"
                              "def escribir(ruta, pedidos):\n    with open(ruta, 'w', newline='', encoding='utf-8') as f:\n"
                              "        w = csv.writer(f)\n        w.writerow(['id', 'cliente', 'importe'])\n"
                              "        for p in pedidos:\n            w.writerow([p.id, p.cliente, p.importe])\n"),
        "pedidos/informe.py": ("def resumen(pedidos):\n    \"\"\"{cliente: total}\"\"\"\n    out = {}\n    for p in pedidos:\n"
                               "        out[p.cliente] = round(out.get(p.cliente, 0) + p.importe, 2)\n    return out\n"),
        "pedidos/cli.py": ("import argparse\nfrom .csv_io import leer\nfrom .informe import resumen\n\n\ndef main(argv=None):\n"
                           "    ap = argparse.ArgumentParser(prog='pedidos')\n    ap.add_argument('archivo')\n"
                           "    a = ap.parse_args(argv)\n    for cliente, total in sorted(resumen(leer(a.archivo)).items()):\n"
                           "        print(f'{cliente}: {total:.2f}')\n\n\nif __name__ == '__main__':\n    main()\n"),
        "pedidos/__main__.py": "from .cli import main\n\nmain()\n",
        "README.md": "# Pedidos\n\n`python -m pedidos archivo.csv` imprime el total por cliente.\n",
        "tests/test_pedidos.py": ("from pedidos.modelo import Pedido\nfrom pedidos.informe import resumen\n\n\n"
                                  "def test_resumen():\n    ps = [Pedido(1, 'ana', 10.0), Pedido(2, 'ana', 5.5), Pedido(3, 'luis', 1.0)]\n"
                                  "    assert resumen(ps) == {'ana': 15.5, 'luis': 1.0}\n"),
    })
    commit(repo, "inicial")
    return {}


def check_multiarchivo(repo: Path, info: dict) -> tuple[bool, str]:
    return run_hidden(repo, (
        "import subprocess, sys\nfrom pedidos.modelo import Pedido\nfrom pedidos.csv_io import leer, escribir\n"
        "from pedidos.informe import resumen\n\n\n"
        "def test_por_defecto_eur():\n    assert Pedido(1, 'a', 1.0).moneda == 'EUR'\n\n\n"
        "def test_csv_antiguo_sin_moneda(tmp_path):\n    f = tmp_path / 'p.csv'\n"
        "    f.write_text('id,cliente,importe\\n1,ana,2.5\\n', encoding='utf-8')\n    assert leer(f)[0].moneda == 'EUR'\n\n\n"
        "def test_ida_y_vuelta(tmp_path):\n    f = tmp_path / 'p.csv'\n"
        "    escribir(f, [Pedido(1, 'ana', 2.5, 'USD')])\n    p = leer(f)[0]\n    assert (p.moneda, p.importe) == ('USD', 2.5)\n\n\n"
        "def test_resumen_por_moneda():\n"
        "    ps = [Pedido(1, 'ana', 10.0, 'EUR'), Pedido(2, 'ana', 5.0, 'USD'), Pedido(3, 'ana', 1.0, 'EUR')]\n"
        "    assert resumen(ps) == {('ana', 'EUR'): 11.0, ('ana', 'USD'): 5.0}\n\n\n"
        "def test_cli_muestra_moneda(tmp_path):\n    f = tmp_path / 'p.csv'\n"
        "    escribir(f, [Pedido(1, 'ana', 2.5, 'USD')])\n"
        "    r = subprocess.run([sys.executable, '-m', 'pedidos', str(f)], capture_output=True, text=True)\n"
        "    assert r.returncode == 0 and 'USD' in r.stdout and 'ana' in r.stdout\n"), ("tests",))


MULTIARCHIVO = {
    "name": "multiarchivo", "build": build_multiarchivo, "check": check_multiarchivo,
    "prompt": ("Añade a los pedidos un campo `moneda` (texto, por defecto 'EUR'). Al leer CSV la columna `moneda` es "
               "opcional (los CSV antiguos no la tienen: entonces EUR) y al escribir se guarda siempre. "
               "`informe.resumen` pasa a devolver `{(cliente, moneda): total}`: nunca se suman importes de monedas "
               "distintas. La CLI debe mostrar la moneda junto a cada total. Actualiza el README, adapta los tests "
               "que haga falta y añade los que falten."),
}


# --- 4. proyecto ------------------------------------------------------------------------------
def build_proyecto(repo: Path) -> dict:
    write_files(repo, {"README.md": "# Tareas\n"})
    commit(repo, "inicial")
    return {}


def check_proyecto(repo: Path, info: dict) -> tuple[bool, str]:
    return run_hidden(repo, (
        "import os, subprocess, sys, pathlib\nROOT = pathlib.Path(__file__).resolve().parent.parent\n\n\n"
        "def cli(tmp_path, *args):\n    env = dict(os.environ, TAREAS_DB=str(tmp_path / 't.db'))\n"
        "    return subprocess.run([sys.executable, str(ROOT / 'tareas.py'), *args], capture_output=True, text=True,"
        " env=env, cwd=tmp_path)\n\n\n"
        "def test_flujo(tmp_path):\n    a = cli(tmp_path, 'add', 'comprar pan')\n    b = cli(tmp_path, 'add', 'llamar a Luis')\n"
        "    assert a.returncode == 0 and b.returncode == 0\n    ia, ib = a.stdout.strip(), b.stdout.strip()\n"
        "    assert ia.isdigit() and ib.isdigit() and ia != ib\n"
        "    lst = cli(tmp_path, 'list').stdout.strip().splitlines()\n    assert lst == [f'{ia}\\tcomprar pan', f'{ib}\\tllamar a Luis']\n"
        "    assert cli(tmp_path, 'done', ia).returncode == 0\n"
        "    assert cli(tmp_path, 'list').stdout.strip().splitlines() == [f'{ib}\\tllamar a Luis']\n"
        "    todas = cli(tmp_path, 'list', '--todas').stdout.strip().splitlines()\n"
        "    assert todas == [f'{ia}\\t[x] comprar pan', f'{ib}\\t[ ] llamar a Luis']\n\n\n"
        "def test_done_inexistente(tmp_path):\n    r = cli(tmp_path, 'done', '999')\n"
        "    assert r.returncode == 1 and r.stderr.strip() and not r.stdout.strip()\n\n\n"
        "def test_persistente(tmp_path):\n    cli(tmp_path, 'add', 'x')\n    assert len(cli(tmp_path, 'list').stdout.strip().splitlines()) == 1\n"))


PROYECTO = {
    "name": "proyecto", "build": build_proyecto, "check": check_proyecto,
    "prompt": ("Crea `tareas.py`, una CLI de tareas pendientes en Python que guarda los datos en SQLite (sin "
               "dependencias externas):\n"
               "- `python tareas.py add \"texto\"` añade una tarea e imprime solo su id.\n"
               "- `python tareas.py list` imprime una línea por tarea pendiente: `id<TAB>texto`, por orden de alta.\n"
               "- `python tareas.py list --todas` imprime todas: `id<TAB>[x] texto` si está hecha y `id<TAB>[ ] texto` si no.\n"
               "- `python tareas.py done ID` la marca como hecha; si no existe, mensaje en stderr y código de salida 1.\n"
               "- La base de datos está en la ruta de la variable de entorno `TAREAS_DB` (por defecto `tareas.db`).\n"
               "Añade tests que lo comprueben."),
}


# --- 5. memoria (dos sesiones) ----------------------------------------------------------------
def build_memoria(repo: Path) -> dict:
    write_files(repo, {"README.md": "# Utilidades\n"})
    commit(repo, "inicial")
    return {}


def check_memoria(repo: Path, info: dict) -> tuple[bool, str]:
    pruebas = list((repo / "pruebas").glob("test*.py")) if (repo / "pruebas").exists() else []
    en_tests = list((repo / "tests").glob("test*.py")) if (repo / "tests").exists() else []
    src = (repo / "utilidades.py").read_text(encoding="utf-8", errors="replace") if (repo / "utilidades.py").exists() else ""
    docstring = '"""' in src or "'''" in src
    ok, line = run_hidden(repo, (
        "import utilidades, inspect\n\n\n"
        "def test_mediana():\n    fs = [f for n, f in inspect.getmembers(utilidades, inspect.isfunction) if 'mediana' in n]\n"
        "    assert fs, 'no hay ninguna función con mediana en el nombre'\n"
        "    assert fs[0]([3, 1, 2]) == 2 and fs[0]([4, 1, 2, 3]) == 2.5\n"), ("pruebas",))
    prefs = bool(pruebas) and not en_tests and docstring
    return ok and prefs, (f"pruebas/ {'sí' if pruebas else 'no'}, tests/ {'sí' if en_tests else 'no'}, "
                          f"docstring {'sí' if docstring else 'no'} · {line}")


MEMORIA = {
    "name": "memoria", "build": build_memoria, "check": check_memoria,
    "sesion1": ("Apúntate esto para siempre, también para conversaciones futuras: en mis proyectos de Python los "
                "tests van en la carpeta `pruebas/` (nunca en `tests/`), las funciones se llaman en español y toda "
                "función pública lleva docstring. No hace falta que cambies nada ahora; confírmamelo en una frase."),
    "prompt": "Crea `utilidades.py` con una función que calcule la mediana de una lista de números y añade sus tests.",
}

TAREAS_CALIDAD = [REGRESION, RESTRICCIONES, MULTIARCHIVO, PROYECTO, MEMORIA]
