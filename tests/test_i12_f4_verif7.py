"""VERIF-7 (I1.2, F4): sin falsos rojos permanentes en comparar.py ni en obtener_arm.py.

Sin red: comparar.py se prueba con capturas sintéticas y obtener_arm.py con un az.cmd falso en el PATH.
"""
import copy
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

import pytest

from tests import comparar_comun

RAIZ = pathlib.Path(__file__).resolve().parents[1]
COMPARAR = RAIZ / "pruebas" / "I0" / "VERIF" / "scripts" / "comparar.py"
OBTENER_ARM = RAIZ / "_baseline" / "obtener_arm.py"
spec = importlib.util.spec_from_file_location("comparar_f4", COMPARAR)
cmp_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp_mod)

CUENTA = {"name": "recurso-ejemplo", "properties": {
    "provisioningState": "Succeeded",
    "callRateLimit": {"rules": [{"key": "x", "matchPatterns": [{"path": "a"}]}]},
    "callRateLimitNotas": "campo hermano inventado: SÍ cuenta"}}


def _capturas(tmp_path, cuenta_ahora):
    base, ahora = tmp_path / "base", tmp_path / "ahora"
    for d, cuenta in ((base, CUENTA), (ahora, cuenta_ahora)):
        d.mkdir()
        for n in cmp_mod.PROTEGIDOS:
            cuerpo = cuenta if n == "arm_cuenta.json" else {"n": n}
            (d / n).write_text(json.dumps({"respuesta": cuerpo}), encoding="utf-8")
        (d / cmp_mod.ZIP_V3).write_bytes(b"PK-v3")
    comparar_comun.escribir_listas(cmp_mod, base, ahora)  # VPROT-7 (I1.9)
    return [str(ahora), "--base", str(base)]


def _cambiar(f):
    c = copy.deepcopy(CUENTA)
    f(c["properties"])
    return c


@pytest.mark.parametrize("cambio", [
    lambda p: p["callRateLimit"]["rules"][0]["matchPatterns"].append({"path": "b"}),  # el caso real
    lambda p: p["callRateLimit"]["rules"].append({"key": "y"}),
    lambda p: p.pop("callRateLimit"),
    lambda p: p.__setitem__("callRateLimit", None),
])
def test_call_rate_limit_no_cuenta_pero_se_lista(tmp_path, capsys, cambio):
    assert cmp_mod.principal(_capturas(tmp_path, _cambiar(cambio))) == 0
    out = capsys.readouterr().out
    assert "arm_cuenta.json: IGUAL" in out and "/properties/callRateLimit" in out and "no cuentan" in out


@pytest.mark.parametrize("cambio", [
    lambda p: p.__setitem__("provisioningState", "Failed"),
    lambda p: p.__setitem__("callRateLimitNotas", "otra"),  # mismo prefijo de texto, otro campo
])
def test_lo_demas_sigue_contando(tmp_path, cambio):
    assert cmp_mod.principal(_capturas(tmp_path, _cambiar(cambio))) == 1


def test_separar_solo_tapa_el_subarbol():
    d = ["/properties/callRateLimit: añadido", "/properties/callRateLimit/rules[1]/k: 'a' -> 'b'",
         "/properties/callRateLimitX: añadido", "no se puede comparar: KeyError: 'respuesta'",
         "/otra/properties/callRateLimit: añadido"]
    cuentan, ignoradas = cmp_mod.separar(d)
    assert ignoradas == d[:2] and cuentan == d[2:]


@pytest.mark.skipif(sys.platform != "win32", reason="az.cmd falso: solo Windows")
def test_obtener_arm_ya_no_captura_la_conexion_rota(tmp_path):
    falso = tmp_path / "bin"
    falso.mkdir()
    (falso / "az.cmd").write_text("@echo {}\r\n@exit /b 0\r\n", encoding="ascii")
    salida = tmp_path / "captura"
    env = dict(os.environ, PATH=str(falso) + os.pathsep + os.environ["PATH"], PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(OBTENER_ARM), "--salida", str(salida)], cwd=falso, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    nombres = sorted(p.name for p in salida.iterdir())
    assert "arm_conexion_appinsights_rota.json" not in nombres
    assert "arm_cuenta.json" in nombres and "arm_conexiones_proyecto.json" in nombres
    for p in salida.iterdir():  # respondió el az falso: ninguna captura salió de Azure
        assert json.loads(p.read_text(encoding="utf-8"))["respuesta"] == {}
