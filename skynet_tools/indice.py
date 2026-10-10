"""Índice de nombres de archivo de todo el PC, para encontrar un archivo en milisegundos (D21).

Solo nombres, carpetas, tamaño y fecha (nunca el contenido), en SQLite FTS5 con trigramas: «brot» encuentra
«Brotato.exe». Recorre RAICES saltándose Windows, ProgramData, AppData, el ruido de Program Files y ruido de desarrollo (node_modules, .git, cachés). Se construye en un proceso aparte
(`python -m skynet_tools.indice actualizar --db data/indice.db`) en un archivo temporal que luego reemplaza al
bueno, así que buscar nunca ve un índice a medias. La herramienta `sistema.buscar_archivo` lo lanza sola si falta
o tiene más de MAX_EDAD_H horas.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

RAICES = ["C:/"]
MAX_EDAD_H = 12
# Carpetas que no se recorren (en minúsculas, por nombre). Windows, ProgramData y AppData no se indexan: ahí no
# están los archivos de Daniel y serían millones de entradas de ruido. Program Files sí (programas y juegos),
# menos SDKs, .NET, Visual Studio y componentes de Windows.
SALTAR = {"windows", "programdata", "appdata", "$recycle.bin", "windowsapps", "windows kits", "microsoft sdks",
          "reference assemblies", "dotnet", "microsoft visual studio", "msbuild", "common files", "windows defender",
          "windows defender advanced threat protection", "windows nt", "windows mail", "windows media player",
          "windows photo viewer", "windows sidebar", "windows portable devices", "internet explorer",
          "modifiablewindowsapps", "windows security", "microsoft update health tools",
          "system volume information", "$windows.~bt", "$windows.~ws", "recovery", "msocache",
          "node_modules", ".git", "__pycache__", ".venv", "venv", ".cache", ".npm", ".gradle", "site-packages"}


def _filas(raices: list[str]):
    pila = [Path(r) for r in raices]
    while pila:
        d = pila.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.name.lower() not in SALTAR and not e.name.startswith("$"):
                                pila.append(Path(e.path))
                            continue
                        st = e.stat(follow_symlinks=False)
                        yield e.name, str(d), st.st_size, int(st.st_mtime)
                    except OSError:
                        continue
        except OSError:  # sin permiso o desaparecida: se salta
            continue


def actualizar(db: Path, raices: list[str] | None = None) -> int:
    db.parent.mkdir(parents=True, exist_ok=True)
    tmp = db.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    # Solo el nombre lleva trigramas; la carpeta se guarda para filtrar (indexarla multiplicaba el tamaño).
    con.execute("CREATE VIRTUAL TABLE archivos USING fts5(nombre, carpeta UNINDEXED, tam UNINDEXED, mtime UNINDEXED, "
                "tokenize='trigram')")
    con.execute("CREATE TABLE meta(clave TEXT PRIMARY KEY, valor TEXT)")
    n, lote = 0, []
    for fila in _filas(raices or RAICES):
        lote.append(fila)
        if len(lote) >= 5000:
            con.executemany("INSERT INTO archivos VALUES(?,?,?,?)", lote)
            n += len(lote)
            lote.clear()
    con.executemany("INSERT INTO archivos VALUES(?,?,?,?)", lote)
    n += len(lote)
    con.execute("INSERT INTO meta VALUES('creado', ?)", (str(int(time.time())),))
    con.commit()
    con.close()
    os.replace(tmp, db)
    return n


def edad_h(db: Path) -> float | None:
    if not db.exists():
        return None
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
            creado = int(con.execute("SELECT valor FROM meta WHERE clave='creado'").fetchone()[0])
        return (time.time() - creado) / 3600
    except (sqlite3.Error, TypeError, ValueError):
        return None


def lanzar_actualizacion(db: Path) -> None:
    """Reconstruye el índice en un proceso aparte (no bloquea a quien lo pide). Uno solo a la vez."""
    marca = db.with_suffix(".actualizando")
    if marca.exists() and time.time() - marca.stat().st_mtime < 3600:
        return
    marca.parent.mkdir(parents=True, exist_ok=True)
    marca.write_text(str(os.getpid()), encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([sys.executable, "-m", "skynet_tools.indice", "actualizar", "--db", str(db)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def buscar(db: Path, texto: str, limite: int = 20) -> list[tuple[str, str, int, int]]:
    """(nombre, carpeta, tamaño, mtime) de los archivos con todas las palabras de `texto` en el nombre o la ruta.
    La palabra más larga se busca en el nombre con el índice; el resto filtra nombre y carpeta."""
    palabras = [p.lower() for p in texto.replace('"', " ").split() if p]
    if not palabras:
        return []
    clave = max(palabras, key=len)
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        if len(clave) >= 3:  # trigramas; la palabra va entre comillas, nunca como sintaxis FTS
            filas = con.execute("SELECT nombre, carpeta, tam, mtime FROM archivos WHERE nombre MATCH ? "
                                "ORDER BY mtime DESC LIMIT 5000", (f'"{clave}"',)).fetchall()
        else:
            filas = con.execute("SELECT nombre, carpeta, tam, mtime FROM archivos WHERE nombre LIKE ? "
                                "ORDER BY mtime DESC LIMIT 5000", (f"%{clave}%",)).fetchall()
    filas = [f for f in filas if all(p in f"{f[1]}/{f[0]}".lower() for p in palabras)]
    # Primero el nombre exacto, luego los que empiezan igual y después el resto (todos de más reciente a más antiguo).
    texto_l = " ".join(palabras)
    filas.sort(key=lambda f: (f[0].lower() != texto_l, not f[0].lower().startswith(clave)))
    return [(n, c, int(t), int(m)) for n, c, t, m in filas[:limite]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["actualizar"])
    ap.add_argument("--db", required=True)
    a = ap.parse_args()
    db = Path(a.db)
    try:
        print(f"{actualizar(db)} archivos indexados en {db}")
    finally:
        db.with_suffix(".actualizando").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
