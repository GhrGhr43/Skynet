"""Prueba de extremo a extremo con el servidor simulado: `python -m pytest -q tests`."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import servidor_simulado  # noqa: E402
from comparador import __main__ as cli  # noqa: E402
from comparador.pruebas import PRUEBAS  # noqa: E402


def test_bateria_completa(tmp_path, monkeypatch):
    srv, url = servidor_simulado.arrancar()
    try:
        monkeypatch.setattr(cli, "LMSTUDIO", url)
        monkeypatch.setattr(cli, "RAIZ", tmp_path)
        mods = cli.cargar_modelos()
        assert set(mods) == {"lmstudio:listo", "lmstudio:tonto"}          # los de embeddings no se listan
        cli.ejecutar(SimpleNamespace(modelos="lmstudio:listo,lmstudio:tonto", modo="completo", categorias=None, n=1, no_abrir=True))
        js = next((tmp_path / "resultados").glob("*.json"))
        d = json.loads(js.read_text(encoding="utf-8"))
        assert js.with_suffix(".html").exists()
        listo, tonto = d["modelos"]["lmstudio:listo"]["pruebas"], d["modelos"]["lmstudio:tonto"]["pruebas"]
        assert len(listo) == len(PRUEBAS)
        malas = {k: v for k, v in listo.items() if v["nota"] is not None and v["nota"] < 1}
        assert not malas, malas
        assert listo["imagen_gen"]["estado"] == "no_compatible" and listo["control_pc"]["estado"] == "no_probado"
        assert tonto["vision_formas"]["estado"] == "no_compatible"
        puntuadas = [v["nota"] for k, v in tonto.items() if v["nota"] is not None and k != "rendimiento"]
        assert sum(puntuadas) / len(puntuadas) < 0.15
    finally:
        srv.shutdown()


def test_modos():
    rapidas = cli.seleccionar_pruebas("rapido", None)
    assert 0 < len(rapidas) < len(PRUEBAS)
    esp = cli.seleccionar_pruebas("especialidad", ["autonomo"])
    assert {p.categoria for p in esp} == {"autonomo"} and len(esp) == 6


def test_gguf_se_arrancan_solos(tmp_path, monkeypatch):
    """Árbol falso de LM Studio/Strata + llama-server falso: descubre, arranca, reintenta sin MTP y para."""
    from comparador import motor

    home = tmp_path / "home"
    m = home / ".lmstudio" / "models"
    for rel, kb in [("unsloth/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-IQ3_XXS.gguf", 1),
                    ("unsloth/Qwen3.8-27B-GGUF/mtp-Qwen3.8-27B-Q4_0.gguf", 1),
                    ("lmstudio-community/Qwen3.8-27B-GGUF/Qwen3.8-27B-Q4_K_M.gguf", 1),
                    ("lmstudio-community/Qwen3.8-27B-GGUF/mmproj-Qwen3.8-27B-BF16.gguf", 1),
                    ("unsloth/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf", 1),
                    ("nomic-ai/x/nomic-embed-text-v1.5.Q8_0.gguf", 1)]:
        (m / rel).parent.mkdir(parents=True, exist_ok=True)
        (m / rel).write_bytes(b"0" * kb)
    strata = tmp_path / "strata"
    for i in (1, 2):
        p = strata / "coder-IQ1_M" / f"Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-0000{i}-of-00002.gguf"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"0")
    exe = home / ".lmstudio" / "extensions" / "backends" / "llama.cpp-win-x86_64-vulkan-avx2-2.60.0" / "llama-server.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text(f"#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(Path(__file__).parent)!r})\n"
                   "a = sys.argv\nif '--spec-type' in a and 'Q4_K_M' in a[a.index('-m') + 1]:\n"
                   "    print('error: model has no MTP layers'); sys.exit(1)\n"
                   "import servidor_simulado as s\nsrv, url = s.arrancar(int(a[a.index('--port') + 1]))\nsrv.serve_forever()\n")
    exe.chmod(0o755)
    monkeypatch.setattr(motor, "HOME", home)
    monkeypatch.setattr(motor, "CARPETAS", [m, strata])
    monkeypatch.setattr(motor, "PUERTO", 18091)
    monkeypatch.setattr(cli, "RAIZ", tmp_path)
    monkeypatch.setattr(cli, "LMSTUDIO", "http://127.0.0.1:9/v1")
    gs = {g.nombre: g for g in motor.buscar()}
    assert set(gs) == {"Qwen3.8-27B-UD-IQ3_XXS", "Qwen3.8-27B-Q4_K_M", "Qwen3.6-35B-A3B-UD-Q4_K_M",
                       "Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M"}
    assert gs["Qwen3.8-27B-Q4_K_M"].mmproj and not gs["Qwen3.8-27B-UD-IQ3_XXS"].mmproj
    assert gs["Qwen3.6-35B-A3B-UD-Q4_K_M"].moe and gs["Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M"].moe
    assert gs["Qwen3.8-27B-UD-IQ3_XXS"].mtp and not gs["Qwen3.6-35B-A3B-UD-Q4_K_M"].mtp
    assert "--n-cpu-moe" in motor.argumentos(gs["Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M"], False)
    cli.ejecutar(SimpleNamespace(modelos="Qwen3.8-27B-Q4_K_M,Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M", modo="especialidad",
                                 categorias="vision,razonamiento", n=1, no_abrir=True))
    d = json.loads(next((tmp_path / "resultados").glob("*.json")).read_text(encoding="utf-8"))
    q4 = d["modelos"]["Qwen3.8-27B-Q4_K_M"]
    assert q4["pruebas"]["vision_formas"]["nota"] == 1 and q4["pruebas"]["razonamiento"]["nota"] == 1
    assert "--mmproj" in q4["ajustes"]["flags"] and "draft-mtp" not in q4["ajustes"]["flags"]   # reintento sin MTP
    assert d["modelos"]["Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M"]["pruebas"]["razonamiento"]["nota"] == 1
    assert not motor.puerto_ocupado(18091)                                                    # se paró
