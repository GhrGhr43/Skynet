"""Servidor OpenAI simulado para probar el comparador sin GPU.

Sirve dos "modelos": `listo` (responde bien a cada prueba, como haría un modelo perfecto) y
`tonto` (responde siempre lo mismo). Si el comparador puntúa ~100 % al primero y ~0 % al
segundo, la tubería (cliente, pruebas, bucle agéntico, verificadores, informe) funciona.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from soluciones_ref import REF  # noqa: E402

COD = {
    "parse_duracion": "import re\ndef parse_duracion(s):\n    m = re.fullmatch(r'(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?', s)\n"
                      "    if not s or not m: raise ValueError(s)\n    h, mi, se = (int(x or 0) for x in m.groups())\n"
                      "    return h*3600 + mi*60 + se\n",
    "huecos": "def huecos(ocupado, inicio, fin, minimo):\n    out, t = [], inicio\n"
              "    for a, b in sorted(ocupado):\n        a, b = max(a, inicio), min(b, fin)\n        if b <= a: continue\n"
              "        if a - t >= minimo: out.append((t, a))\n        t = max(t, b)\n"
              "    if fin - t >= minimo: out.append((t, fin))\n    return out\n",
    "es_bisiesto": "from sol import es_bisiesto\n\ndef test_a():\n    assert es_bisiesto(2024)\n    assert not es_bisiesto(1900)\n"
                   "    assert es_bisiesto(2000)\n    assert not es_bisiesto(2023)\n",
    "mediana": "def mediana(xs):\n    if not xs: raise ValueError\n    s = sorted(xs); n = len(s)\n"
               "    return s[n//2] if n % 2 else (s[n//2-1] + s[n//2]) / 2\n",
    "busqueda": "def busqueda_binaria(xs, x):\n    lo, hi = 0, len(xs) - 1\n    while lo <= hi:\n        mid = (lo+hi)//2\n"
                "        if xs[mid] < x: lo = mid + 1\n        elif xs[mid] > x: hi = mid - 1\n        else: return mid\n    return -1\n",
}


def responder_listo(body: dict) -> dict:
    msgs = body["messages"]
    ultimo = msgs[-1]
    user = next(m for m in reversed(msgs) if m["role"] == "user")
    t = user["content"] if isinstance(user["content"], str) else " ".join(
        c.get("text", "") for c in user["content"] if isinstance(c, dict))
    tools = body.get("tools")
    # --- bucle agéntico: escribe la solución de referencia y termina
    if tools and any(x["function"]["name"] == "write_file" for x in tools):
        if ultimo["role"] == "tool":
            return {"content": "Hecho y comprobado con los tests."}
        nombre = next((n for n, k in [("factura", "facturas"), ("renombrar", "calc_total"), ("cli_json", "--formato"),
                                      ("logs", "logs/"), ("cache_ttl", "SPEC.md"), ("planificador", "planificador")]
                       if k in t), None)
        calls = [{"id": f"c{i}", "type": "function", "function": {"name": "write_file",
                  "arguments": json.dumps({"path": p, "content": c})}} for i, (p, c) in enumerate(REF[nombre].items())]
        if nombre == "cli_json":
            calls.append({"id": "cx", "type": "function", "function": {"name": "write_file", "arguments": json.dumps(
                {"path": "tests/test_json.py", "content": "def test_json():\n    assert 'json'\n"})}})
        return {"content": "", "tool_calls": calls}
    # --- herramientas
    if tools:
        if ultimo["role"] == "tool":
            return {"content": "Mañana llueve en Sevilla, así que no he creado el evento."}
        def call(n, a):
            return {"content": "", "tool_calls": [{"id": "t1", "type": "function",
                    "function": {"name": n, "arguments": json.dumps(a)}}]}
        if "vuelos" in t:
            return call("buscar_vuelos", {"origen": "Madrid", "destino": "Lisboa", "fecha": "2026-10-20"})
        if "dentista" in t:
            return {"content": "¿A qué hora quieres la cita?"}
        if "Bilbao" in t:
            return call("tiempo", {"ciudad": "Bilbao", "fecha": "2026-10-10"})
        return call("tiempo", {"ciudad": "Sevilla", "fecha": "2026-10-09"})
    # --- resto
    for clave, cod in [("parse_duracion", "parse_duracion"), ("huecos", "huecos"), ("pytest", "es_bisiesto"),
                       ("mediana", "mediana"), ("binaria", "busqueda")]:
        if clave in t:
            return {"content": f"```python\n{COD[cod]}```"}
    if "media móvil" in t:
        return {"content": '{"linea": 6, "arreglo": "suma += xs[i] - xs[i - k]"}'}
    if "ciudades" in t:
        return {"content": '{"ciudades": [{"nombre": "Londres", "pais": "UK", "poblacion_millones": 9.0}, '
                           '{"nombre": "Madrid", "pais": "ES", "poblacion_millones": 3.4}, '
                           '{"nombre": "Roma", "pais": "IT", "poblacion_millones": 2.8}], "total": 15.2}'}
    if "viñetas" in t:
        return {"content": "- Evitan perder trabajo\n- Protegen frente a virus\n- Permiten volver atrás\n"
                           "- Dan tranquilidad\nFIN"}
    for q, sol in [("Ana es mayor", "Bea"), ("tren", "12:40"), ("divisibles", "41"), ("cajas", "manzanas")]:
        if q in t:
            return {"content": f"Razonamiento...\nRESPUESTA: {sol}"}
    if "Teruel" in t:
        return {"content": "Abrió en 2019 con 48 empleados."}
    if "presidió" in t:
        return {"content": "NO CONSTA"}
    if "Mundial" in t:
        return {"content": "No lo sé con seguridad; la premisa podría ser falsa."}
    if "contabilidad" in t:
        return {"content": "Factura 2231 del proveedor por 340 €, vence el 15/11."}
    if "Traduce" in t:
        return {"content": "Antes de fusionar, haz rebase de tu rama sobre main, ejecuta los tests y comprueba que "
                           "la compilación pasa en Windows."}
    if "usted" in t:
        return {"content": "Estimados compañeros: les informo de que mañana no podré asistir. Vuelvo el jueves. "
                           "Un saludo."}
    if "no vengo" in t:
        return {"content": "Chicos, mañana no vengo."}
    if "cuadrados" in t:
        return {"content": '{"rojos": 3, "azules": 2, "arriba": "rojo"}'}
    return {"content": "Una caché LRU guarda los elementos usados recientemente. " * 20}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code: int, d: dict) -> None:
        b = json.dumps(d).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._json(200, {"status": "ok"})
        self._json(200, {"data": [{"id": "listo"}, {"id": "tonto"}, {"id": "texto-embed"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body["model"] == "tonto":
            if any(isinstance(m.get("content"), list) for m in body["messages"]):
                return self._json(400, {"error": "this model does not support image input"})
            msg = {"content": "No estoy seguro."}
        else:
            msg = responder_listo(body)
        msg = {"role": "assistant", **msg}
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for w in re.findall(r"\S+\s*", msg["content"]):
                self.wfile.write(f"data: {json.dumps({'choices': [{'delta': {'content': w}}]})}\n\n".encode())
            u = {"prompt_tokens": len(str(body["messages"])) // 4, "completion_tokens": len(msg["content"].split())}
            self.wfile.write(f"data: {json.dumps({'choices': [], 'usage': u})}\n\ndata: [DONE]\n\n".encode())
            return
        self._json(200, {"choices": [{"message": msg, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": len(str(body["messages"])) // 4, "completion_tokens": 50}})


def arrancar(puerto: int = 0) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


if __name__ == "__main__":
    s, url = arrancar(int(sys.argv[1]) if len(sys.argv) > 1 else 1234)
    print("Simulador en", url)
    s.serve_forever()
