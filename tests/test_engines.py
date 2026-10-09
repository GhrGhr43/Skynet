from pathlib import Path
from skynet.engines import load_engines

RAW = {
    "local": {"tipo": "llamacpp", "url": "http://127.0.0.1:8090/v1"},
    "otro": {"tipo": "lmstudio", "url": "http://127.0.0.1:1234/v1"},
    "omniroute": {"tipo": "proceso", "url": "http://127.0.0.1:20128/v1", "exe": "node", "args": ["x"],
                  "env": {"HOST": "127.0.0.1"}, "salud": "http://127.0.0.1:20128/api/health",
                  "firma": r"vendor\omniroute", "gpu": False},
}


def _engines(tmp_path, monkeypatch, on):
    e = load_engines(RAW, tmp_path)
    stopped, spawned = [], []
    monkeypatch.setattr(e, "is_on", lambda n: n in on)
    monkeypatch.setattr(e, "stop", lambda n: stopped.append(n))
    monkeypatch.setattr(e, "_spawn", lambda s, args, health, wait, env=None: spawned.append((args, health, env)) or "ok")
    return e, stopped, spawned


def test_proceso_no_apaga_los_motores_de_gpu(tmp_path, monkeypatch):
    e, stopped, spawned = _engines(tmp_path, monkeypatch, on={"local"})
    e.start("omniroute")
    assert stopped == []
    args, health, env = spawned[0]
    assert args == ["node", "x"] and health.endswith("/api/health") and env == {"HOST": "127.0.0.1"}


def test_motor_de_gpu_no_apaga_omniroute(tmp_path, monkeypatch):
    e, stopped, _ = _engines(tmp_path, monkeypatch, on={"otro", "omniroute"})
    e.start("local")
    assert stopped == ["otro"]


def test_modelo_local_elegible(tmp_path, monkeypatch):
    from skynet import modelos_locales as ml
    from skynet.engines import EngineSpec, Engines, load_engines

    m = tmp_path / "models"
    for rel in ["u/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf", "u/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-IQ3_XXS.gguf",
                "u/Qwen3.8-27B-GGUF/mtp-Qwen3.8-27B-Q4_0.gguf", "n/x/nomic-embed.gguf"]:
        (m / rel).parent.mkdir(parents=True, exist_ok=True)
        (m / rel).write_bytes(b"0")
    monkeypatch.setattr(ml, "CARPETAS", [m])
    gs = {g.nombre: g for g in ml.buscar()}
    assert set(gs) == {"Qwen3.6-35B-A3B-UD-Q4_K_M", "Qwen3.8-27B-UD-IQ3_XXS"}
    assert "--n-cpu-moe" in gs["Qwen3.6-35B-A3B-UD-Q4_K_M"].args() and "draft-mtp" not in gs["Qwen3.6-35B-A3B-UD-Q4_K_M"].args()
    assert "draft-mtp" in gs["Qwen3.8-27B-UD-IQ3_XXS"].args()
    raw = {"local": {"tipo": "llamacpp", "url": "http://127.0.0.1:8090/v1", "modelo": "x.gguf", "exe": "e"}}
    logs = tmp_path / "data" / "logs"
    assert load_engines(raw, logs).specs["local"].modelo == "x.gguf"
    ml.guardar(tmp_path / "data", "Qwen3.8-27B-UD-IQ3_XXS")
    sp = load_engines(raw, logs).specs["local"]
    assert sp.modelo.endswith("Qwen3.8-27B-UD-IQ3_XXS.gguf") and "draft-mtp" in sp.args


def test_home_en_rutas_de_proceso(tmp_path):
    raw = {"omni": {"tipo": "proceso", "url": "http://x/v1", "exe": "node",
                    "args": ["{home}/vendor/omni.mjs", "serve"], "env": {"DATA_DIR": "{home}/data"}}}
    s = load_engines(raw, tmp_path, Path("C:/Git/Skynet")).specs["omni"]
    assert s.args[0] == str(Path("C:/Git/Skynet")) + "/vendor/omni.mjs"
    assert s.env["DATA_DIR"].endswith("/data") and "{home}" not in s.env["DATA_DIR"]
