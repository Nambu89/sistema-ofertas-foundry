"""REV-6 (I1.2, F4): el redespliegue exige una sesión de az con 30 minutos de margen en las dos audiencias.

Sin red ni az real: `ejecutar` y `shutil.which` son falsos. La prueba del .sh usa un az.cmd falso que pide MFA.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import types

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
RUTA = RAIZ / "pruebas" / "I11" / "ARREGLOS" / "comprobar_sesion_az.py"
spec = importlib.util.spec_from_file_location("comprobar_sesion_az", RUTA)
ses = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ses)
AHORA = 1_800_000_000.0
# Git Bash, no el bash de WSL de System32 (que CreateProcess encontraría antes con "bash" a secas)
_GIT = pathlib.Path("C:/Program Files/Git/bin/bash.exe")
BASH = str(_GIT) if _GIT.is_file() else shutil.which("bash")


def _az(respuestas):
    """Falso subprocess.run: respuestas[audiencia] = (rc, stdout, stderr). Guarda los comandos."""
    vistos = []

    def ejecutar(cmd, **_k):
        vistos.append(cmd)
        rc, out, err = respuestas[cmd[cmd.index("--resource") + 1]]
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=err)
    return ejecutar, vistos


@pytest.fixture(autouse=True)
def az_en_path(monkeypatch):
    monkeypatch.setattr(ses.shutil, "which", lambda n: "C:/az/az.cmd")


def _ok(min_ai, min_arm):
    return {"https://ai.azure.com": (0, json.dumps({"expires_on": AHORA + min_ai * 60}), ""),
            "https://management.azure.com": (0, json.dumps({"expires_on": int(AHORA + min_arm * 60)}), "")}


def test_las_dos_con_margen_pasan_y_nunca_piden_el_token():
    ejecutar, vistos = _az(_ok(55, 70))
    lineas = ses.comprobar(30, ejecutar=ejecutar, ahora=lambda: AHORA)
    assert len(lineas) == 2 and "55 min" in lineas[0]
    for cmd in vistos:
        assert cmd[cmd.index("--tenant") + 1] == ses.TENANT
        assert "accessToken" not in cmd[cmd.index("--query") + 1]


@pytest.mark.parametrize("min_ai,min_arm", [(29, 60), (60, 10), (-5, 60)])
def test_una_sola_audiencia_corta_para(min_ai, min_arm):
    ejecutar, _ = _az(_ok(min_ai, min_arm))
    with pytest.raises(ses.SinSesion):
        ses.comprobar(30, ejecutar=ejecutar, ahora=lambda: AHORA)


def test_mfa_pendiente_es_sin_sesion_y_mira_las_dos():
    r = _ok(60, 60)
    r["https://ai.azure.com"] = (1, "", "AADSTS50076: Due to a configuration change... Run 'az login'")
    ejecutar, vistos = _az(r)
    with pytest.raises(ses.SinSesion, match="AADSTS50076"):
        ses.comprobar(30, ejecutar=ejecutar, ahora=lambda: AHORA)
    assert len(vistos) == 2


def test_expireson_local_si_falta_expires_on():
    import datetime as dt
    local = dt.datetime.fromtimestamp(AHORA + 45 * 60).strftime("%Y-%m-%d %H:%M:%S.%f")
    assert ses.caducidad({"expiresOn": local}) == pytest.approx(AHORA + 45 * 60, abs=1)


@pytest.mark.parametrize("datos", [{}, {"expiresOn": "mañana"}, {"expires_on": "x"}])
def test_caducidad_ilegible_falla_en_alto(datos):
    with pytest.raises(ses.AzIlegible):
        ses.caducidad(datos)


def test_main_sin_sesion_rc2_y_comando_exacto(monkeypatch, capsys):
    monkeypatch.setattr(ses, "comprobar", lambda m: (_ for _ in ()).throw(ses.SinSesion("x: caduca en 3 min")))
    assert ses.main([]) == 2
    assert f"az login --tenant {ses.TENANT}" in capsys.readouterr().err


@pytest.mark.skipif(not BASH or sys.platform != "win32", reason="Git Bash en Windows")
def test_script_para_antes_de_desplegar_si_az_pide_mfa(tmp_path):
    (tmp_path / "az.cmd").write_text("@echo AADSTS50076 AZ-FALSO-F4: interaction_required. Run 'az login' 1>&2\r\n"
                                     "@exit /b 1\r\n", encoding="ascii")
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ["PATH"])
    r = subprocess.run([BASH, "pruebas/I11/ARREGLOS/redesplegar_tras_mfa.sh"], cwd=RAIZ, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "AZ-FALSO-F4" in r.stderr  # respondió el az falso, nunca el real
    assert f"az login --tenant {ses.TENANT}" in r.stderr
    assert "PARADO antes del bloque 1" in r.stdout and "== ficheros" not in r.stdout


@pytest.mark.skipif(not BASH, reason="sin bash")
def test_script_rechaza_desde_desconocido():
    env = dict(os.environ, DESDE="2")
    r = subprocess.run([BASH, "pruebas/I11/ARREGLOS/redesplegar_tras_mfa.sh"], cwd=RAIZ, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 1 and "DESDE tiene que ser" in r.stdout


@pytest.mark.parametrize("valor", ["nan", "inf", "-1"])
def test_margen_no_valido_se_rechaza(valor, capsys):
    with pytest.raises(SystemExit) as e:  # Revisión F4: con «nan» cualquier token pasaba
        ses.main(["--minutos", valor])
    assert e.value.code == 2 and "--minutos" in capsys.readouterr().err
    with pytest.raises(ValueError):
        ses.comprobar(float(valor))


@pytest.mark.parametrize("bruto", ["nan", "inf", float("nan")])
def test_expires_on_no_finito_es_ilegible(bruto):
    with pytest.raises(ses.AzIlegible):
        ses.caducidad({"expires_on": bruto})
