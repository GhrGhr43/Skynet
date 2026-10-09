"""Instalar juegos de Steam sin pulsar nada: manifiesto en la biblioteca + reinicio de Steam (simulado)."""
from __future__ import annotations

from pathlib import Path

from skynet_tools.steam import PENDIENTE, Entorno, install, libraries, parse_vdf, state, write_manifest

LIBRARYFOLDERS = '''"libraryfolders"
{
	"0"
	{
		"path"		"%s"
		"apps" { "228980" "0" }
	}
	"1"
	{
		"path"		"%s"
	}
}
'''


def _steam(tmp_path: Path) -> tuple[Path, Path]:
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    other = tmp_path / "Juegos"
    (other / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        LIBRARYFOLDERS % (str(steam).replace("\\", "\\\\"), str(other).replace("\\", "\\\\")), encoding="utf-8")
    return steam, other


def _env(steam: Path, **kw) -> tuple[Entorno, list]:
    calls: list = []
    base = dict(steam_dir=lambda: steam, game_running=lambda: False, restart=lambda s: calls.append("reinicio"),
                name=lambda a: "Brotato", dialog=lambda a, s: calls.append("dialogo") or "sin_dialogo",
                sleep=lambda s: None)
    base.update(kw)
    return Entorno(**base), calls


def test_vdf_and_libraries(tmp_path):
    steam, other = _steam(tmp_path)
    assert libraries(steam) == [steam / "steamapps", other / "steamapps"]
    f = write_manifest(steam / "steamapps", 1942280, "Brotato: «Edición» ™")
    st = parse_vdf(f.read_text())["AppState"]
    assert st["appid"] == "1942280" and st["StateFlags"] == str(PENDIENTE) and st["installdir"] == "Brotato «Edición»"
    assert state(steam, 1942280)[0] == f


def test_installs_without_clicks_when_steam_starts_downloading(tmp_path):
    steam, _ = _steam(tmp_path)

    def restart(s):  # Steam arranca, lee el manifiesto y empieza a descargar
        calls.append("reinicio")
        (s / "steamapps" / "downloading" / "1942280").mkdir(parents=True)

    env, calls = _env(steam, restart=restart)
    msg = install(1942280, 30, env)
    assert "descargándose" in msg and "Brotato" in msg
    assert calls == ["reinicio"]                              # sin diálogo: no hubo que pulsar nada
    assert (steam / "steamapps" / "appmanifest_1942280.acf").is_file()


def test_no_restart_with_a_game_open(tmp_path):
    steam, _ = _steam(tmp_path)
    env, calls = _env(steam, game_running=lambda: True)
    msg = install(1942280, 30, env)
    assert calls == [] and "no reinicio Steam" in msg
    assert (steam / "steamapps" / "appmanifest_1942280.acf").is_file()  # queda en cola para el próximo arranque


def test_fallback_to_dialog_when_no_download(tmp_path):
    steam, _ = _steam(tmp_path)
    env, calls = _env(steam, dialog=lambda a, s: calls.append("dialogo") or "pulsado")
    msg = install(570, 9, env)
    assert calls == ["reinicio", "dialogo"] and "aceptada" in msg
    assert not (steam / "steamapps" / "appmanifest_570.acf").exists()  # no deja un manifiesto huérfano


def test_already_installed(tmp_path):
    steam, other = _steam(tmp_path)
    (other / "steamapps" / "appmanifest_730.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"730"\n\t"name"\t\t"Counter-Strike 2"\n\t"StateFlags"\t\t"4"\n}\n')
    env, calls = _env(steam)
    assert "ya está instalado" in install(730, 30, env) and calls == []


def test_no_steam():
    env, _ = _env(None, steam_dir=lambda: None)
    assert "No encuentro Steam" in install(730, 30, env)
