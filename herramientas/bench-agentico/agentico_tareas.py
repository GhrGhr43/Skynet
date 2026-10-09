"""Tareas agénticas de varios pasos para comparar modelos en el bucle real de Skynet.

Cada tarea es un repo pequeño con un problema realista. El agente solo ve el repo y el
enunciado; al terminar, un verificador oculto (tests que el agente no ha visto) decide si
la tarea está bien. Más difíciles que bench/tasks.py: hay que explorar, leer varios
archivos, ejecutar tests, editar en varios sitios y comprobar.
"""

COMMON = {
    "pytest.ini": "[pytest]\ntestpaths = tests\n",
    "tests/conftest.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))\n",
}

TASKS = []

# 1. Bug repartido en dos módulos ------------------------------------------------------------
TASKS.append({
    "name": "factura",
    "prompt": "Los totales de las facturas salen mal: un cliente con un 10 % de descuento ha pagado de más y "
              "los céntimos no cuadran. Encuentra la causa y arréglalo sin cambiar la interfaz pública. "
              "Los tests del repo deben pasar.",
    "files": {
        "tienda/__init__.py": "",
        "tienda/precios.py": (
            "def aplicar_descuento(precio: float, descuento_pct: float) -> float:\n"
            "    \"\"\"descuento_pct es un porcentaje: 10 significa 10 %.\"\"\"\n"
            "    return precio - descuento_pct\n"),
        "tienda/impuestos.py": (
            "IVA = 0.21\n\n\n"
            "def con_iva(base: float) -> float:\n"
            "    \"\"\"Devuelve base + IVA redondeado al céntimo (redondeo comercial, 0.005 sube).\"\"\"\n"
            "    return int(base * (1 + IVA) * 100) / 100\n"),
        "tienda/factura.py": (
            "from .precios import aplicar_descuento\nfrom .impuestos import con_iva\n\n\n"
            "def total(lineas: list[tuple[float, int]], descuento_pct: float = 0) -> float:\n"
            "    \"\"\"lineas = [(precio_unitario, cantidad)]. Descuento sobre la suma, luego IVA.\"\"\"\n"
            "    base = sum(p * c for p, c in lineas)\n"
            "    return con_iva(aplicar_descuento(base, descuento_pct))\n"),
        "tests/test_factura.py": (
            "from tienda.factura import total\n\n\n"
            "def test_sin_descuento():\n    assert total([(10.0, 2)]) == 24.2\n\n\n"
            "def test_descuento():\n    assert total([(100.0, 1)], 10) == 108.9\n"),
    },
    "hidden": (
        "from decimal import Decimal\n"
        "from tienda.factura import total\nfrom tienda.precios import aplicar_descuento\nfrom tienda.impuestos import con_iva\n\n\n"
        "def test_descuento_pct():\n    assert abs(aplicar_descuento(200, 25) - 150) < 1e-9\n\n\n"
        "def test_redondeo_comercial():\n    assert con_iva(1.0) == 1.21\n    assert con_iva(0.05) == 0.06\n"
        "    assert con_iva(19.99) == 24.19\n\n\n"
        "def test_total():\n    assert total([(100.0, 1)], 10) == 108.9\n    assert total([(9.99, 3)], 0) == 36.26\n"
        "    assert total([(10.0, 2)]) == 24.2\n"),
})

# 2. Refactor con alias de compatibilidad ------------------------------------------------------
TASKS.append({
    "name": "renombrar",
    "prompt": "Renombra la función `calc_total` a `calcular_total` en todo el proyecto (código, registro de "
              "comandos y README). Mantén `calc_total` como alias obsoleto que siga funcionando pero emita "
              "DeprecationWarning. Los tests del repo deben pasar.",
    "files": {
        "app/__init__.py": "",
        "app/calculo.py": "def calc_total(xs):\n    return round(sum(xs), 2)\n",
        "app/informe.py": "from .calculo import calc_total\n\n\ndef informe(xs):\n    return f'Total: {calc_total(xs)}'\n",
        "app/comandos.py": ("from . import calculo\n\nCOMANDOS = {'total': 'calc_total'}\n\n\n"
                            "def ejecutar(nombre, xs):\n    return getattr(calculo, COMANDOS[nombre])(xs)\n"),
        "app/api.py": "from app.calculo import calc_total as _t\n\n\ndef total_json(xs):\n    return {'total': _t(xs)}\n",
        "README.md": "# App\n\nUsa `calc_total(xs)` para sumar importes.\n",
        "tests/test_app.py": ("from app.informe import informe\nfrom app.comandos import ejecutar\nfrom app.api import total_json\n\n\n"
                              "def test_todo():\n    assert informe([1, 2]) == 'Total: 3'\n"
                              "    assert ejecutar('total', [1.111, 2]) == 3.11\n    assert total_json([5]) == {'total': 5}\n"),
    },
    "hidden": (
        "import pathlib, warnings, pytest\n"
        "from app.calculo import calcular_total, calc_total\nfrom app.comandos import COMANDOS, ejecutar\n"
        "from app.informe import informe\nfrom app.api import total_json\n\n"
        "ROOT = pathlib.Path(__file__).resolve().parent.parent\n\n\n"
        "def test_nuevo():\n    assert calcular_total([1.111, 2]) == 3.11\n    assert COMANDOS['total'] == 'calcular_total'\n"
        "    assert ejecutar('total', [1]) == 1 and informe([2]) == 'Total: 2' and total_json([1]) == {'total': 1}\n\n\n"
        "def test_alias():\n    with pytest.warns(DeprecationWarning):\n        assert calc_total([1, 2]) == 3\n\n\n"
        "def test_sin_restos():\n"
        "    for p in ['app/informe.py', 'app/comandos.py', 'app/api.py', 'README.md']:\n"
        "        assert 'calc_total' not in (ROOT / p).read_text(encoding='utf-8'), p\n\n\n"
        "def test_sin_aviso_en_uso_normal():\n    with warnings.catch_warnings():\n"
        "        warnings.simplefilter('error')\n        informe([1]); ejecutar('total', [1]); total_json([1])\n"),
})

# 3. Funcionalidad nueva que cruza CLI y modelo ---------------------------------------------
TASKS.append({
    "name": "cli_json",
    "prompt": "Añade a la CLI (`python -m informes resumen <csv>`) una opción `--formato` con valores `texto` "
              "(por defecto, salida actual sin cambios) y `json`. En json imprime un objeto con las claves "
              "`filas`, `total` y `por_categoria` (categoría -> suma, redondeadas a 2 decimales) usando una "
              "función nueva `Resumen.a_dict()`. Un valor de --formato no válido debe salir con código 2 "
              "(lo normal en argparse). Añade un test.",
    "files": {
        "informes/__init__.py": "",
        "informes/__main__.py": "from .cli import main\n\nraise SystemExit(main())\n",
        "informes/modelo.py": (
            "import csv\nfrom dataclasses import dataclass, field\n\n\n@dataclass\nclass Resumen:\n"
            "    filas: int = 0\n    total: float = 0.0\n    por_categoria: dict = field(default_factory=dict)\n\n\n"
            "def resumir(ruta):\n    r = Resumen()\n    with open(ruta, newline='', encoding='utf-8') as f:\n"
            "        for fila in csv.DictReader(f):\n            imp = float(fila['importe'])\n"
            "            r.filas += 1\n            r.total += imp\n"
            "            r.por_categoria[fila['categoria']] = r.por_categoria.get(fila['categoria'], 0) + imp\n"
            "    return r\n"),
        "informes/cli.py": (
            "import argparse\nfrom .modelo import resumir\n\n\ndef main(argv=None):\n"
            "    p = argparse.ArgumentParser(prog='informes')\n    sub = p.add_subparsers(dest='cmd', required=True)\n"
            "    s = sub.add_parser('resumen')\n    s.add_argument('csv')\n    a = p.parse_args(argv)\n"
            "    r = resumir(a.csv)\n    print(f'{r.filas} filas, total {r.total:.2f}')\n"
            "    for k in sorted(r.por_categoria):\n        print(f'  {k}: {r.por_categoria[k]:.2f}')\n    return 0\n"),
        "datos/ejemplo.csv": "fecha,categoria,importe\n2026-01-01,comida,10.5\n2026-01-02,ocio,20\n2026-01-03,comida,4.25\n",
        "tests/test_cli.py": (
            "from informes.cli import main\n\n\ndef test_texto(capsys):\n    assert main(['resumen', 'datos/ejemplo.csv']) == 0\n"
            "    assert '3 filas, total 34.75' in capsys.readouterr().out\n"),
    },
    "hidden": (
        "import json, subprocess, sys, pathlib\nfrom informes.cli import main\nfrom informes.modelo import resumir\n\n"
        "ROOT = pathlib.Path(__file__).resolve().parent.parent\n\n\n"
        "def test_texto_igual(capsys):\n    main(['resumen', str(ROOT / 'datos/ejemplo.csv')])\n"
        "    out = capsys.readouterr().out\n    assert out.startswith('3 filas, total 34.75') and 'comida: 14.75' in out\n\n\n"
        "def test_json(capsys):\n    assert main(['resumen', str(ROOT / 'datos/ejemplo.csv'), '--formato', 'json']) == 0\n"
        "    d = json.loads(capsys.readouterr().out)\n"
        "    assert d == {'filas': 3, 'total': 34.75, 'por_categoria': {'comida': 14.75, 'ocio': 20.0}}\n\n\n"
        "def test_a_dict():\n    d = resumir(ROOT / 'datos/ejemplo.csv').a_dict()\n    assert d['total'] == 34.75\n\n\n"
        "def test_invalido():\n    r = subprocess.run([sys.executable, '-m', 'informes', 'resumen', 'datos/ejemplo.csv', '--formato', 'xml'],\n"
        "                       cwd=ROOT, capture_output=True)\n    assert r.returncode == 2\n\n\n"
        "def test_agente_anadio_test():\n"
        "    txt = ''.join(p.read_text(encoding='utf-8') for p in (ROOT / 'tests').glob('test_*.py'))\n"
        "    assert 'json' in txt\n"),
})

# 4. Explorar datos con formatos mezclados ----------------------------------------------------
TASKS.append({
    "name": "logs",
    "prompt": "En `logs/` hay registros de varios servicios en dos formatos distintos. Crea `analisis.py` con "
              "`errores_por_servicio(carpeta) -> dict[str, int]` que cuente las líneas de nivel ERROR (sin "
              "distinguir mayúsculas) por servicio en todos los `*.log` de la carpeta, ignorando líneas "
              "mal formadas, y devuelva el dict ordenado por cuenta descendente y luego por nombre. Mira los "
              "archivos antes de escribir el parser. Añade tests.",
    "files": {
        "logs/web.log": ("2026-10-01 10:00:00 INFO [web] arranque\n2026-10-01 10:00:05 ERROR [web] 500 en /pagar\n"
                         "linea rota sin formato\n2026-10-01 10:01:00 error [pagos] timeout\n"
                         "2026-10-01 10:02:00 WARN [web] lento\n2026-10-01 10:03:00 ERROR [web] 502\n"),
        "logs/pagos.log": ('{"ts": "2026-10-01T10:00:00", "lvl": "error", "svc": "pagos", "msg": "rechazada"}\n'
                           '{"ts": "2026-10-01T10:00:01", "lvl": "info", "svc": "pagos", "msg": "ok"}\n'
                           '{"ts": "2026-10-01T10:00:02", "lvl": "ERROR", "svc": "auth"}\n'
                           '{roto\n'
                           '{"ts": "2026-10-01T10:00:03", "lvl": "error"}\n'),
        "logs/LEEME.txt": "Esto no es un log: ERROR [falso] no contar\n",
        "tests/test_vacio.py": "def test_placeholder():\n    assert True\n",
    },
    "hidden": (
        "import pathlib\nfrom analisis import errores_por_servicio\n\nROOT = pathlib.Path(__file__).resolve().parent.parent\n\n\n"
        "def test_repo():\n    d = errores_por_servicio(ROOT / 'logs')\n"
        "    assert d == {'pagos': 2, 'web': 2, 'auth': 1}\n    assert list(d) == ['pagos', 'web', 'auth']\n\n\n"
        "def test_otra_carpeta(tmp_path):\n"
        "    (tmp_path / 'a.log').write_text('2026-01-01 00:00:00 Error [z] x\\n2026-01-01 00:00:00 ERROR [a] y\\n'\n"
        "        '{\"lvl\": \"error\", \"svc\": \"a\"}\\n\\n', encoding='utf-8')\n"
        "    (tmp_path / 'b.txt').write_text('2026-01-01 00:00:00 ERROR [q] no', encoding='utf-8')\n"
        "    d = errores_por_servicio(str(tmp_path))\n    assert d == {'a': 2, 'z': 1} and list(d) == ['a', 'z']\n\n\n"
        "def test_vacia(tmp_path):\n    assert errores_por_servicio(tmp_path) == {}\n"),
})

# 5. Implementar desde una especificación ------------------------------------------------------
TASKS.append({
    "name": "cache_ttl",
    "prompt": "Implementa `cache.py` siguiendo exactamente `docs/SPEC.md`. Hay algunos tests en el repo pero no "
              "cubren toda la especificación: añade los que falten.",
    "files": {
        "docs/SPEC.md": (
            "# TTLCache\n\n`TTLCache(max_items: int, ttl: float, reloj=time.monotonic)`\n\n"
            "- `set(k, v)`: guarda o sobrescribe; cuenta como uso reciente y reinicia su caducidad.\n"
            "- `get(k, defecto=None)`: devuelve el valor si existe y no ha caducado (caduca cuando "
            "`reloj() - guardado >= ttl`), y cuenta como uso reciente. Si caducó, lo borra y devuelve `defecto`.\n"
            "- `len(cache)`: número de elementos NO caducados (purga los caducados).\n"
            "- Al insertar una clave nueva con la caché llena: primero se purgan los caducados; si sigue llena, "
            "se expulsa el menos usado recientemente.\n"
            "- `stats()`: dict `{'aciertos': int, 'fallos': int, 'expulsiones': int}`. Un get de algo caducado es un "
            "fallo. Las purgas de caducados no cuentan como expulsiones.\n"
            "- `max_items < 1` o `ttl <= 0` -> ValueError.\n"),
        "tests/test_cache.py": (
            "from cache import TTLCache\n\n\ndef test_basico():\n    c = TTLCache(2, 10)\n    c.set('a', 1)\n"
            "    assert c.get('a') == 1 and c.get('x') is None\n"),
    },
    "hidden": (
        "import pytest\nfrom cache import TTLCache\n\n\nclass Reloj:\n    def __init__(self):\n        self.t = 0.0\n"
        "    def __call__(self):\n        return self.t\n\n\n"
        "def test_caduca():\n    r = Reloj(); c = TTLCache(3, 5, reloj=r); c.set('a', 1); r.t = 4.99\n"
        "    assert c.get('a') == 1\n    r.t = 5.0\n    assert c.get('a', 'no') == 'no'\n\n\n"
        "def test_set_reinicia():\n    r = Reloj(); c = TTLCache(3, 5, reloj=r); c.set('a', 1); r.t = 4; c.set('a', 2); r.t = 8\n"
        "    assert c.get('a') == 2\n\n\n"
        "def test_get_no_reinicia_ttl():\n    r = Reloj(); c = TTLCache(3, 5, reloj=r); c.set('a', 1); r.t = 4; c.get('a'); r.t = 5\n"
        "    assert c.get('a') is None\n\n\n"
        "def test_lru():\n    r = Reloj(); c = TTLCache(2, 100, reloj=r); c.set('a', 1); c.set('b', 2); c.get('a'); c.set('c', 3)\n"
        "    assert c.get('b') is None and c.get('a') == 1 and c.get('c') == 3\n    assert c.stats()['expulsiones'] == 1\n\n\n"
        "def test_purga_antes_de_expulsar():\n    r = Reloj(); c = TTLCache(2, 5, reloj=r); c.set('a', 1); r.t = 3; c.set('b', 2)\n"
        "    r.t = 6; c.set('c', 3)\n    assert c.get('b') == 2 and c.get('c') == 3\n    assert c.stats()['expulsiones'] == 0\n\n\n"
        "def test_len():\n    r = Reloj(); c = TTLCache(5, 5, reloj=r); c.set('a', 1); r.t = 2; c.set('b', 1); r.t = 5\n"
        "    assert len(c) == 1\n\n\n"
        "def test_stats():\n    r = Reloj(); c = TTLCache(5, 5, reloj=r); c.set('a', 1); c.get('a'); c.get('z'); r.t = 9; c.get('a')\n"
        "    assert c.stats() == {'aciertos': 1, 'fallos': 2, 'expulsiones': 0}\n\n\n"
        "def test_errores():\n    with pytest.raises(ValueError):\n        TTLCache(0, 5)\n"
        "    with pytest.raises(ValueError):\n        TTLCache(1, 0)\n"),
})

# 6. Depurar un algoritmo con un fallo sutil ---------------------------------------------------
TASKS.append({
    "name": "planificador",
    "prompt": "`planificador.orden(tareas)` debe devolver un orden de ejecución que respete las dependencias; "
              "a igualdad, alfabético. Si hay un ciclo debe lanzar `CicloError` cuyo atributo `ciclo` sea la "
              "lista de tareas del ciclo empezando y terminando por la misma (p. ej. ['a', 'b', 'a']). Ahora a "
              "veces cuelga, a veces da órdenes no deterministas y no detecta ciclos. Arréglalo y añade tests.",
    "files": {
        "planificador.py": (
            "class CicloError(Exception):\n    def __init__(self, ciclo):\n        super().__init__(' -> '.join(ciclo))\n"
            "        self.ciclo = ciclo\n\n\n"
            "def orden(tareas: dict[str, list[str]]) -> list[str]:\n"
            "    \"\"\"tareas: nombre -> lista de tareas de las que depende. Las dependencias que no son claves también\n"
            "    son tareas (sin dependencias).\"\"\"\n"
            "    pendientes = set(tareas)\n    hecho = []\n    while pendientes:\n"
            "        for t in pendientes:\n            if all(d in hecho for d in tareas.get(t, [])):\n"
            "                hecho.append(t)\n                pendientes.discard(t)\n                break\n"
            "    return hecho\n"),
        "tests/test_plan.py": (
            "from planificador import orden\n\n\ndef test_simple():\n    assert orden({'b': ['a'], 'a': []}) == ['a', 'b']\n"),
    },
    "hidden": (
        "import pytest\nfrom planificador import orden, CicloError\n\n\n"
        "def test_alfabetico():\n    assert orden({'c': [], 'b': [], 'a': []}) == ['a', 'b', 'c']\n\n\n"
        "def test_deps_no_claves():\n    assert orden({'build': ['fetch', 'config']}) == ['config', 'fetch', 'build']\n\n\n"
        "def test_diamante():\n    assert orden({'d': ['b', 'c'], 'b': ['a'], 'c': ['a'], 'a': []}) == ['a', 'b', 'c', 'd']\n\n\n"
        "def test_desbloqueo():\n    assert orden({'z': [], 'b': ['z'], 'a': ['z']}) == ['z', 'a', 'b']\n\n\n"
        "def test_ciclo():\n    with pytest.raises(CicloError) as e:\n        orden({'a': ['b'], 'b': ['c'], 'c': ['a'], 'x': []})\n"
        "    c = e.value.ciclo\n    assert c[0] == c[-1] and set(c) == {'a', 'b', 'c'} and len(c) == 4\n\n\n"
        "def test_autociclo():\n    with pytest.raises(CicloError) as e:\n        orden({'a': ['a']})\n    assert e.value.ciclo == ['a', 'a']\n"),
})
