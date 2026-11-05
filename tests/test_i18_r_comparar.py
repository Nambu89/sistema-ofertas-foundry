"""I1.8 · papel R · INT17-2: comparar.py admite el endpoint que la plataforma añadió a la cuenta («Voice Live Media
Gateway Calls HTTP API»), solo como «añadido» y con su valor exacto; cualquier otro cambio de los endpoints sigue
contando. Sin red: capturas sintéticas en tmp_path (como tests/test_i14_int_comparar.py)."""
import importlib.util
import json
import pathlib

import pytest

from tests import comparar_comun

RAIZ = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("comparar_i18", RAIZ / "pruebas" / "I0" / "VERIF" / "scripts" / "comparar.py")
cmp_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp_mod)

VOICE = "Voice Live Media Gateway Calls HTTP API"
URL = "https://recurso-ejemplo.cognitiveservices.azure.com/"
BASE = {"properties": {"endpoints": {"AI Foundry API": "https://recurso-ejemplo.services.ai.azure.com/"}}}


def _capturas(tmp_path, cuenta_ahora):
    base, ahora = tmp_path / "base", tmp_path / "ahora"
    for d, cuenta in ((base, BASE), (ahora, cuenta_ahora)):
        d.mkdir()
        for n in cmp_mod.PROTEGIDOS:
            (d / n).write_text(json.dumps({"respuesta": cuenta if n == "arm_cuenta.json" else {"n": n}}), encoding="utf-8")
        (d / cmp_mod.ZIP_V3).write_bytes(b"PK-v3")
    comparar_comun.escribir_listas(cmp_mod, base, ahora)  # VPROT-7 (I1.9)
    return [str(ahora), "--base", str(base)]


def _con(**endpoints):
    return {"properties": {"endpoints": {**BASE["properties"]["endpoints"], **endpoints}}}


def test_el_endpoint_de_plataforma_con_su_valor_no_cuenta(tmp_path, capsys):
    assert cmp_mod.principal(_capturas(tmp_path, _con(**{VOICE: URL}))) == 0
    out = capsys.readouterr().out
    assert "arm_cuenta.json: IGUAL" in out and "INT17-2" in out and "TODO COINCIDE" in out


@pytest.mark.parametrize("cuenta", [
    _con(**{VOICE: "https://otro-recurso.cognitiveservices.azure.com/"}),       # otro valor
    _con(**{VOICE: URL, "Otro endpoint nuevo": URL}),                            # otra clave añadida
    _con(**{VOICE: URL, "AI Foundry API": "https://cambiado.example/"}),         # un endpoint existente cambiado
    {"properties": {"endpoints": {VOICE: URL}}},                                 # uno quitado
    _con(**{VOICE: None}),                                                       # valor nulo
    {"properties": {"endpoints": {**BASE["properties"]["endpoints"], VOICE: URL}, "otra": 1}},   # otra propiedad
])
def test_cualquier_otro_cambio_sigue_contando(tmp_path, capsys, cuenta):
    assert cmp_mod.principal(_capturas(tmp_path, cuenta)) == 1
    assert "arm_cuenta.json: IGUAL" not in capsys.readouterr().out


def test_el_endpoint_admitido_en_otro_fichero_cuenta():
    d = [f"/properties/endpoints/{VOICE}: añadido"]
    assert cmp_mod.separar_endpoints("arm_proyecto.json", d, _con(**{VOICE: URL})) == (d, [])
    assert cmp_mod.separar_endpoints("arm_cuenta.json", d, _con(**{VOICE: URL})) == ([], d)
    assert cmp_mod.separar_endpoints("arm_cuenta.json", [f"/properties/endpoints/{VOICE}: eliminado"], BASE)[1] == []
    assert cmp_mod.separar_endpoints("arm_cuenta.json", d, "no es un objeto") == (d, [])
