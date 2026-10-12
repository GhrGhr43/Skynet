"""Configuración persistente, MCP desactivado y aprobación individual de memoria."""
import pytest
from skynet_tools.personalizacion import Personalizacion


def test_memoria_no_entra_hasta_aprobar_y_no_aprueba_las_demas(home):
    options = Personalizacion(home)
    options.cambiar({"memoria_activa": True})
    a = options.proponer_memoria("Prefiero respuestas breves")
    b = options.proponer_memoria("Mi proyecto está en D:/proyecto", "entorno")
    assert options.memoria_aprobada() == ""
    options.revisar_memoria(a["id"], True)
    assert "breves" in options.memoria_aprobada()
    assert "D:/proyecto" not in options.memoria_aprobada()
    assert not options.data["memoria"][1]["aprobada"]
    assert Personalizacion(home).data["memoria"] == options.data["memoria"]


def test_mcp_apagado_no_se_conecta_ni_ofrece_herramientas(home, repo_path):
    options = Personalizacion(home)
    options.cambiar({"mcp": {"uno": {"command": "python", "args": ["{repo}"], "enabled": True},
                              "dos": {"url": "https://example.com/mcp", "enabled": False}}})
    assert options.mcp_config(repo_path) == {"mcpServers": {}}
    options.cambiar({"mcp_activo": True})
    servers = options.mcp_config(repo_path)["mcpServers"]
    assert set(servers) == {"uno"}
    assert servers["uno"]["args"] == [repo_path.as_posix()]
    options.cambiar({"mcp": {}})
    assert options.mcp_config(repo_path) == {"mcpServers": {}}


def test_opciones_invalidas_no_se_guardan(home):
    options = Personalizacion(home)
    with pytest.raises(ValueError):
        options.cambiar({"contexto": -1})
    assert options.data["contexto"] == 65536
    with pytest.raises(ValueError):
        options.cambiar({"harnesses": {"pi": {"protocolo": "protocolo-inventado"}}})
    with pytest.raises(ValueError):
        options.proponer_memoria("primera\nsegunda")


def test_harness_y_herramientas_son_independientes_del_modelo(home):
    options = Personalizacion(home)
    options.cambiar({"harnesses": {"pi": {"protocolo": "pi-rpc"},
        "alternativo": {"protocolo": "pi-rpc", "comando": "node", "args": ["agente.js"]}},
        "harness": "alternativo", "herramientas": [], "contexto": 16384, "mtp": False})
    again = Personalizacion(home)
    assert again.data["harness"] == "alternativo"
    assert again.data["herramientas"] == []
    assert not again.data["mtp"]


def test_modelo_eliminado_no_permanece_disponible(make_rt):
    rt = make_rt()
    options = rt.personalizacion
    options.cambiar({'modelos':{'otro':{'id':'llm','api_base':'http://127.0.0.1:1234/v1','razonamiento':None}}})
    options.aplicar_modelos(rt.settings)
    assert rt.settings.models['otro'].reasoning_effort is None
    options.cambiar({'modelos':{}})
    options.aplicar_modelos(rt.settings)
    assert 'otro' not in rt.settings.models
    assert 'local' in rt.settings.models


def test_catalogos_invalidos_no_corrompen_configuracion(home):
    options = Personalizacion(home)
    for changes in ({'modelos':[]}, {'modelos':{'m':{'id':'a','api_base':'http://localhost/v1','max_tokens':'mal'}}},
                    {'mcp':{'s':{'command':'python','args':[3]}}}):
        with pytest.raises(ValueError):
            options.cambiar(changes)
    assert options.data['modelos'] == {} and options.data['mcp'] == {}
