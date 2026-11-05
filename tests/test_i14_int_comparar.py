"""VER13-4 (I1.4, integrador): comparar.py no da falso rojo porque la API del toolbox incruste «updated_at» y
«versions: {latest: …}», pero sigue contando cualquier cambio real del toolbox protegido.

Sin red: capturas sintéticas en tmp_path, como tests/test_i12_f4_verif7.py.
"""
import copy
import importlib.util
import json
import pathlib

import pytest

from tests import comparar_comun

RAIZ = pathlib.Path(__file__).resolve().parents[1]
COMPARAR = RAIZ / "pruebas" / "I0" / "VERIF" / "scripts" / "comparar.py"
spec = importlib.util.spec_from_file_location("comparar_i14", COMPARAR)
cmp_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp_mod)

V6 = {"metadata": {}, "id": "toolbox_x:6", "name": "toolbox-ajena-ejemplo", "version": "6", "created_at": 1,
      "tools": [{"type": "web_search", "name": "web_search_a"}], "skills": [{"type": "skill_reference", "name": "pptx"}]}
V5 = {**V6, "id": "toolbox_x:5", "version": "5", "skills": []}
TOOLBOX = {"id": "toolbox_x", "name": "toolbox-ajena-ejemplo", "default_version": "6", "object": "toolbox"}


def _capturas(tmp_path, toolbox_ahora, lista_ahora=None):
    base, ahora = tmp_path / "base", tmp_path / "ahora"
    cuerpos_base = {"toolbox_toolbox-ajena-ejemplo.json": TOOLBOX, "toolboxes_lista.json": {"data": [TOOLBOX]},
                    "toolbox_toolbox-ajena-ejemplo_versiones.json": {"data": [V6, V5]}}
    cuerpos_ahora = {**cuerpos_base, "toolbox_toolbox-ajena-ejemplo.json": toolbox_ahora,
                     "toolboxes_lista.json": lista_ahora if lista_ahora is not None else {"data": [toolbox_ahora]}}
    for d, cuerpos in ((base, cuerpos_base), (ahora, cuerpos_ahora)):
        d.mkdir()
        for n in cmp_mod.PROTEGIDOS:
            (d / n).write_text(json.dumps({"respuesta": cuerpos.get(n, {"n": n})}), encoding="utf-8")
        (d / cmp_mod.ZIP_V3).write_bytes(b"PK-v3")
    comparar_comun.escribir_listas(cmp_mod, base, ahora)  # VPROT-7 (I1.9)
    return [str(ahora), "--base", str(base)]


def _con(latest=V6, **extra):
    return {**TOOLBOX, "updated_at": 1789721025, "versions": {"latest": copy.deepcopy(latest)}, **extra}


def test_caso_real_updated_at_y_latest_igual_a_la_base_no_cuentan(tmp_path, capsys):
    assert cmp_mod.principal(_capturas(tmp_path, _con())) == 0
    out = capsys.readouterr().out
    assert "toolbox_toolbox-ajena-ejemplo.json: IGUAL" in out and "toolboxes_lista.json: IGUAL" in out
    assert "/versions/latest: igual a la v6 de la línea base" in out and "/updated_at: ignorado" in out


def test_solo_updated_at_no_cuenta(tmp_path):
    assert cmp_mod.principal(_capturas(tmp_path, {**TOOLBOX, "updated_at": 5})) == 0


@pytest.mark.parametrize("toolbox", [
    _con(latest={**V6, "skills": [{"type": "skill_reference", "name": "otra"}]}),  # latest cambiada con el mismo número
    _con(latest={**V6, "id": "toolbox_x:7", "version": "7"}),                     # versión nueva que no está en la base
    {**TOOLBOX, "versions": {"latest": V6, "v7": V6}},                            # forma desconocida
    {**TOOLBOX, "versions": [V6]},
    _con(default_version="5"),                                                    # cambia la versión por defecto
    _con(name_extra="x"),                                                         # cualquier otro campo sigue contando
])
def test_un_cambio_real_del_toolbox_cuenta(tmp_path, toolbox):
    assert cmp_mod.principal(_capturas(tmp_path, toolbox)) == 1


def test_otro_toolbox_en_la_lista_cuenta(tmp_path):
    otro = {**TOOLBOX, "id": "toolbox_y", "name": "otro", "updated_at": 1, "versions": {"latest": V6}}
    assert cmp_mod.principal(_capturas(tmp_path, _con(), {"data": [_con(), otro]})) == 1


def test_normalizar_no_toca_otros_objetos():
    obj = {"name": "otro", "updated_at": 1, "versions": {"latest": {}}}
    assert cmp_mod.normalizar_toolbox(obj, [V6]) == (obj, [], [])


def _sin_versiones(tmp_path, toolbox):
    args = _capturas(tmp_path, toolbox)
    for d in ("base", "ahora"):  # el fichero de versiones queda igual en los dos lados, pero sin «data»
        (tmp_path / d / "toolbox_toolbox-ajena-ejemplo_versiones.json").write_text('{"respuesta": {"n": 1}}', encoding="utf-8")
    return args


def test_sin_versiones_en_la_base_versions_cuenta(tmp_path, capsys):
    assert cmp_mod.principal(_sin_versiones(tmp_path, _con())) == 1
    assert "no se puede juzgar" in capsys.readouterr().out


def test_sin_versiones_en_la_base_lo_demas_compara(tmp_path):
    assert cmp_mod.principal(_sin_versiones(tmp_path, {**TOOLBOX, "updated_at": 5})) == 0


@pytest.mark.parametrize("lista_ahora", [{}, {"data": None}, {"data": "x"}])
def test_lista_sin_data_valida_cuenta(tmp_path, lista_ahora):
    """Revisión (I1.4): una «data» ausente o que no es lista no se normaliza a [] en silencio."""
    assert cmp_mod.principal(_capturas(tmp_path, _con(), lista_ahora)) == 1


@pytest.mark.parametrize("ahora", [{}, {"data": None}])
def test_caso_de_revision_base_vacia_frente_a_data_ausente(ahora):
    d, _ = cmp_mod.comparar_toolbox("toolboxes_lista.json", {"data": []}, ahora, [V6])
    assert d, "una «data» ausente o null frente a [] tiene que contar"
