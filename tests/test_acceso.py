"""Acceso desde el móvil: solo por Tailscale Serve, con llave por dispositivo, y lo local como siempre."""
from __future__ import annotations

import pytest
from conftest import ScriptedLLM
from starlette.testclient import TestClient

from skynet.web.acceso import Dispositivos, analizar_serve, enlace_emparejar, ip_cliente, ip_de_tailscale
from skynet.web.server import create_app

TS = "https://pc.tail1234.ts.net"
APP = "https://app.skynet.local"


def remoto(llave: str | None = None, ip: str = "100.101.102.103", origin: str | None = APP, **extra) -> dict:
    h = {"Host": "pc.tail1234.ts.net", "X-Forwarded-For": ip, "X-Forwarded-Proto": "https",
         "Tailscale-User-Login": "daniel@example.com"}
    if origin:
        h["Origin"] = origin
    if llave:
        h["Authorization"] = f"Bearer {llave}"
    h.update(extra)
    return h


@pytest.fixture
def web(make_rt):
    rt = make_rt(ScriptedLLM([]))
    app = create_app(rt, 8765)
    app.state.acceso.sondeo = lambda puerto: {"instalado": True, "conectado": True, "nombre_dns": "pc.tail1234.ts.net",
                                              "serve": True, "funnel": False, "detalle": "Listo"}
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c, rt, app


def emparejar(c, nombre="Móvil de Daniel") -> str:
    r = c.post("/api/dispositivos/emparejar", json={"nombre": nombre})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["url"] == TS and d["enlace"].startswith("skynet://emparejar?u=https%3A%2F%2Fpc.tail1234.ts.net&c=")
    r = c.post("/api/emparejar", json={"codigo": d["codigo"], "nombre": nombre}, headers=remoto())
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == APP
    return r.json()["llave"]


def test_utilidades():
    assert ip_de_tailscale("100.64.0.1") and ip_de_tailscale("100.127.255.254") and ip_de_tailscale("fd7a:115c:a1e0::1")
    assert not ip_de_tailscale("192.168.1.10") and not ip_de_tailscale("8.8.8.8") and not ip_de_tailscale(None)
    assert ip_cliente("1.2.3.4, 100.100.1.1") == "100.100.1.1"
    assert enlace_emparejar(None, "x") is None
    cfg = {"Web": {"pc.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}},
           "AllowFunnel": {"pc.ts.net:443": True}}
    assert analizar_serve(cfg, 8765) == (True, True)
    assert analizar_serve({"Web": {}}, 8765) == (False, False)


def test_local_sigue_igual(web):
    c, _, _ = web
    assert c.get("/api/estado").status_code == 200
    assert c.get("/api/yo").json() == {"remoto": False, "dispositivo": None}
    assert c.get("/api/estado", headers={"Host": "evil.example:8765"}).status_code == 403


def test_emparejar_y_usar_desde_el_movil(web):
    c, rt, _ = web
    llave = emparejar(c)
    h = remoto(llave)
    r = c.get("/api/estado", headers=h)
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == APP
    assert c.get("/api/yo", headers=h).json()["dispositivo"]["nombre"] == "Móvil de Daniel"
    assert c.post("/api/mensaje", json={"texto": "hola"}, headers=h).json()["ok"]
    lista = c.get("/api/dispositivos").json()
    assert lista["dispositivos"][0]["nombre"] == "Móvil de Daniel" and "hash" not in lista["dispositivos"][0]
    assert lista["acceso"]["url"] == TS
    eventos = [e for e in rt.store.events(limit=50) if e.get("tool") in ("skynet.dispositivos", "skynet.remoto")]
    assert {e["decision"] for e in eventos} >= {"emparejado", "mensaje"}


def test_codigo_de_un_solo_uso_y_malo(web):
    c, _, _ = web
    d = c.post("/api/dispositivos/emparejar", json={}).json()
    assert c.post("/api/emparejar", json={"codigo": d["codigo"]}, headers=remoto()).status_code == 200
    assert c.post("/api/emparejar", json={"codigo": d["codigo"]}, headers=remoto()).status_code == 403
    assert c.post("/api/emparejar", json={"codigo": "inventado"}, headers=remoto()).status_code == 403


def test_codigo_caduca(tmp_path):
    t = [1000.0]
    d = Dispositivos(tmp_path / "d.json", reloj=lambda: t[0])
    codigo, _ = d.nuevo_codigo("x")
    t[0] += 11 * 60
    with pytest.raises(Exception):
        d.emparejar(codigo, "x", None)


def test_sin_llave_o_llave_mala_401(web):
    c, _, _ = web
    r = c.get("/api/estado", headers=remoto())
    assert r.status_code == 401 and r.json()["reautorizar"] is True
    assert r.headers["access-control-allow-origin"] == APP  # el móvil puede leer el motivo
    assert c.get("/api/estado", headers=remoto("inventada")).status_code == 401


def test_revocar(web):
    c, _, _ = web
    llave = emparejar(c)
    did = c.get("/api/dispositivos").json()["dispositivos"][0]["id"]
    assert c.post(f"/api/dispositivos/{did}/revocar", json={}).status_code == 200
    assert c.get("/api/estado", headers=remoto(llave)).status_code == 401


def test_llaves_persisten(make_rt):
    rt = make_rt(ScriptedLLM([]))
    app = create_app(rt, 8765)
    app.state.acceso.sondeo = lambda p: {"instalado": True, "conectado": True, "nombre_dns": "pc.tail1234.ts.net",
                                         "serve": True, "funnel": False, "detalle": ""}
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        llave = emparejar(c)
    app2 = create_app(rt, 8765)
    with TestClient(app2, base_url="http://127.0.0.1:8765") as c:
        assert c.get("/api/estado", headers=remoto(llave)).status_code == 200
    assert llave not in (rt.settings.home / "data" / "dispositivos.json").read_text(encoding="utf-8")


def test_solo_por_tailscale_y_sin_funnel(web):
    c, _, _ = web
    llave = emparejar(c)
    assert c.get("/api/estado", headers=remoto(llave, ip="8.8.8.8")).status_code == 403
    assert c.get("/api/estado", headers=remoto(llave, ip="192.168.1.20")).status_code == 403
    assert c.get("/api/estado", headers=remoto(llave, **{"Tailscale-Funnel-Request": "?1"})).status_code == 403
    assert c.get("/api/estado", headers=remoto(llave, Host="evil.example")).status_code == 403
    # el Host del PC con cabeceras de proxy tampoco cuela
    h = remoto(llave, Host="127.0.0.1:8765")
    assert c.get("/api/estado", headers=h).status_code == 403


def test_cors_y_origenes(web):
    c, _, _ = web
    llave = emparejar(c)
    r = c.options("/api/estado", headers=remoto(**{"Access-Control-Request-Method": "GET",
                                                   "Access-Control-Request-Headers": "authorization"}))
    assert r.status_code == 204 and "Authorization" in r.headers["access-control-allow-headers"]
    assert c.get("/api/estado", headers=remoto(llave, origin="https://evil.example")).status_code == 403
    assert c.get("/api/estado", headers=remoto(llave, origin=None)).status_code == 200  # sin navegador


def test_limites_en_remoto(web):
    c, _, _ = web
    h = remoto(emparejar(c))
    assert c.get("/", headers=h).status_code == 404
    assert c.get("/static/js/main.js", headers=h).status_code == 404
    assert c.get("/api/dispositivos", headers=h).status_code == 403
    assert c.post("/api/dispositivos/emparejar", json={}, headers=h).status_code == 403
    assert c.post("/api/repos", json={"nombre": "x", "ruta": "C:/"}, headers=h).status_code == 403
    r = c.post("/api/ajustes", json={"sin_preguntar": {"modelo": "local", "activar": True}, "confirmar": True}, headers=h)
    assert r.status_code == 403
    assert c.post("/api/ajustes", json={"razonamiento": "high"}, headers=h).status_code == 200


def test_usuarios_permitidos(make_rt):
    rt = make_rt(ScriptedLLM([]))
    rt.settings.acceso = {"usuarios_tailscale": ["otra@example.com"]}
    app = create_app(rt, 8765)
    app.state.acceso.sondeo = lambda p: {"instalado": True, "conectado": True, "nombre_dns": "pc.tail1234.ts.net",
                                         "serve": True, "funnel": False, "detalle": ""}
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        d = c.post("/api/dispositivos/emparejar", json={}).json()
        assert c.post("/api/emparejar", json={"codigo": d["codigo"]}, headers=remoto()).status_code == 403


def test_sin_tailscale_no_hay_enlace(make_rt):
    rt = make_rt(ScriptedLLM([]))
    app = create_app(rt, 8765)
    app.state.acceso.sondeo = lambda p: {"instalado": False, "conectado": False, "nombre_dns": None, "serve": None,
                                         "funnel": None, "detalle": "Tailscale no está instalado en este PC."}
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        d = c.post("/api/dispositivos/emparejar", json={}).json()
        assert d["url"] is None and d["enlace"] is None and d["codigo"]
