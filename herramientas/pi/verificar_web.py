"""Comprobación básica del HTML: ejecutar sin errores y encajar en tres anchos."""
import json
import sys
from pathlib import Path

from skynet_tools import navegador

navegador.ROOT = Path.cwd()
try:
    for width in (390, 768, 1440):
        result = navegador.comprobar_html("index.html", ancho=width, segundos=.1)
        data = json.loads(result.content[0].text)
        print(f"{width}px: " + ("OK" if data["ok"] else "; ".join(data["errores"])))
        if not data["ok"]:
            sys.exit(1)
except Exception as e:
    print(str(e))
    sys.exit(1)
