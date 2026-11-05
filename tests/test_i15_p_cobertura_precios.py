"""I1.5 · papel P: cobertura de precios (PR15-2, decisión del comercial del 11-10-2026) y REVERIF14-2 en el núcleo.

Cada componente facturable de Azure lleva precio o un motivo de no valoración de la lista cerrada; sin ninguna de las
dos cosas, la respuesta se rechaza al registrarla. Todo componente con región de Azure lleva catalogo_id. Casos
adversos con su resultado esperado (LES-G-096.6). Sin red.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
for p in (RAIZ / "sandbox", RAIZ):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from nucleo import anexo_consumo as A, esquema, experto  # noqa: E402
from nucleo.errores import ReglaIncumplida  # noqa: E402

# I1.6: el catálogo del sandbox con el contrato común de la decisión 4 (impulsor, divisor, niveles y auxiliar atado),
# que se completa desde la medición de E mientras el catálogo derivado no lo traiga (tests/i16_p_datos.py).
from tests.i16_p_datos import catalogo_i16  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)
CAT = catalogo_i16(json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8")),
                   niveles=False)  # sin niveles: el ejemplo solo justifica el de AI Search si el catálogo los trae
EJ = RAIZ / "esquemas" / "ejemplos"
# Los dos facturables sin precio del ejemplo (Microsoft Foundry y Azure AI Bot Service) declaran su motivo.
MOTIVOS_EJEMPLO = {"C-01": "depende_del_volumen", "C-03": "depende_del_volumen"}


def _ej(nombre: str) -> dict:
    return json.loads((EJ / f"{nombre}.json").read_text(encoding="utf-8"))


def con_motivos(resp: dict) -> dict:
    """La respuesta del ejemplo con el contrato v2 (vale antes y después de regenerar los ejemplos)."""
    for c in resp["componentes"]:
        c.setdefault("motivo_no_valoracion", MOTIVOS_EJEMPLO.get(c["id"], A.SIN_MOTIVO))
    return resp


def _errores(resp: dict) -> list[str]:
    br = _ej("brief")
    return i17_int.validar(resp, br, CAT, br["perfiles_permitidos"])


def _comp(resp: dict, cid: str) -> dict:
    return next(c for c in resp["componentes"] if c["id"] == cid)


def test_la_lista_cerrada_del_esquema_es_la_del_codigo():
    enum = esquema.cargar("respuesta_experto")["$defs"]["componente"]["properties"]["motivo_no_valoracion"]["enum"]
    # I1.9: «a_cargo_del_cliente» sigue en la lista del código para juzgar las respuestas v4 guardadas; la v5 no lo admite
    assert set(enum) == {A.SIN_MOTIVO, *A.MOTIVOS_NO_VALORACION} - {"a_cargo_del_cliente"}
    assert "existente_del_cliente" in enum and "a_cargo_del_cliente" not in enum
    req = esquema.cargar("respuesta_experto")["$defs"]["componente"]["required"]
    assert "motivo_no_valoracion" in req  # text.format strict: todas las propiedades en required


def test_el_ejemplo_con_sus_motivos_es_valido():
    assert _errores(con_motivos(_ej("respuesta_experto"))) == []


def test_respuesta_sin_el_campo_no_valida_contra_el_esquema_v2():
    resp = con_motivos(_ej("respuesta_experto"))
    del resp["componentes"][0]["motivo_no_valoracion"]
    assert any("motivo_no_valoracion" in e for e in _errores(resp))


@pytest.mark.parametrize("cid,motivo,regla", [
    ("C-03", "no_aplica", "sin_precio_ni_motivo"),          # Bot Service sin precio ni motivo
    ("C-01", "no_aplica", "sin_precio_ni_motivo"),          # Microsoft Foundry sin precio ni motivo
    ("C-02", "depende_del_volumen", "precio_y_motivo"),     # AI Search tiene P-01 y además un motivo
    ("C-03", "fuera_del_catalogo", "fuera_del_catalogo_con_id"),  # catálogo y «fuera del catálogo»
])
def test_cobertura_adversa_se_rechaza_con_su_regla(cid, motivo, regla):
    resp = con_motivos(_ej("respuesta_experto"))
    _comp(resp, cid)["motivo_no_valoracion"] = motivo
    hallados = A.errores_cobertura(i17_int.completar(resp, CAT), CAT)
    assert [(x["componente_id"], x["regla"]) for x in hallados] == [(cid, regla)]
    errores = _errores(resp)
    assert any(e.startswith(f"componentes.{cid}: {cid}") and "PR15-2" in e for e in errores), errores


@pytest.mark.parametrize("motivo", sorted(set(A.MOTIVOS_NO_VALORACION) - {"fuera_del_catalogo"}))
def test_cada_motivo_de_la_lista_vale_para_un_facturable_del_catalogo(motivo):
    resp = con_motivos(_ej("respuesta_experto"))
    _comp(resp, "C-03")["motivo_no_valoracion"] = motivo
    if motivo != "depende_del_volumen":  # I1.6: el precio de referencia P-05 solo vale con «depende_del_volumen»
        resp["precios"] = [p for p in resp["precios"] if p["id"] != "P-05"]
    # REV16-1 (arreglos I1.6): Bot Service tiene serviceName y plantillas en «Global»: esos dos motivos lo contradicen
    regla = {"licencia_fuera_de_azure": "licencia_con_precio_azure",
             "sin_medidor_publico": "medidor_publico_en_catalogo"}.get(motivo)
    if motivo == "a_cargo_del_cliente":  # integrador I1.7 (decisión del PM, REV16-1 c): exige una cita literal
        _comp(resp, "C-03")["motivo_cita"] = _ej("requisitos")["campos"]["canales_integraciones"]["entradas"][0]["valor"]
    if regla:
        assert [(x["componente_id"], x["regla"]) for x in A.errores_cobertura(i17_int.completar(resp, CAT), CAT)] == [("C-03", regla)]
    elif motivo == "incluido_en_otro_componente":  # I1.7: exige el componente y la inclusión declarada en el catálogo
        assert any("«incluido_en_otro_componente» exige en incluido_en" in e for e in _errores(resp)), _errores(resp)
    elif motivo == "a_cargo_del_cliente":  # I1.9: sale de la v5 (lo sustituye existente_del_cliente)
        assert any("'a_cargo_del_cliente' fuera de" in e for e in _errores(resp)), _errores(resp)
    elif motivo == "existente_del_cliente":  # I1.9 (PR18-1): exige su entrada EX-nn de los requisitos
        _comp(resp, "C-03")["existente_del_cliente"] = {"entrada": "EX-01"}
        assert any("existente_del_cliente.entrada «EX-01» no es una entrada" in e for e in _errores(resp)), _errores(resp)
    else:
        assert _errores(resp) == []


def test_saas_y_sin_precio_publico_no_exigen_motivo_y_se_deduce():
    resp = con_motivos(_ej("respuesta_experto"))
    url = next(e["referencia_url"] for e in CAT["componentes"] if e["id"] == "az-cost-management")
    resp["referencias"].append({**copy.deepcopy(resp["referencias"][0]), "id": "REF-08", "url": url})  # PR16-1
    resp["componentes"].append({**copy.deepcopy(_comp(resp, "C-05")), "id": "C-07", "catalogo_id": "az-cost-management",
                                "servicio": "Microsoft Cost Management", "capa": "operacion_observabilidad",
                                "referencia_id": "REF-08"})
    assert _errores(resp) == []
    clase = {x["componente_id"]: x for x in A.clasificar_componentes(i17_int.completar(resp, CAT), CAT)}
    assert clase["C-05"]["motivo_no_valoracion"] == "licencia_fuera_de_azure" and not clase["C-05"]["facturable"]
    assert clase["C-07"]["motivo_no_valoracion"] == "sin_medidor_publico" and not clase["C-07"]["facturable"]
    assert clase["C-03"]["motivo"] == A.MOTIVO_A_VALORAR and clase["C-03"]["facturable"]


def test_fuera_del_catalogo_en_global_exige_motivo_y_admite_fuera_del_catalogo():
    resp = con_motivos(_ej("respuesta_experto"))
    resp["componentes"].append({**copy.deepcopy(_comp(resp, "C-04")), "id": "C-07", "catalogo_id": None,
                                "servicio": "Azure Front Door", "region": "global", "capa": "aplicacion_integracion",
                                "desviacion_justificada": "Punto de entrada global con WAF delante de la aplicación web.",
                                "justificacion_nivel": None,   # integrador I1.6: C-04 ya lleva la de App Service
                                "referencia_id": "REF-01"})  # integrador I1.7: en v4, C-04 (del catálogo) va con null
    assert [x["regla"] for x in A.errores_cobertura(i17_int.completar(resp, CAT), CAT)] == ["sin_precio_ni_motivo"]
    _comp(resp, "C-07")["motivo_no_valoracion"] = "fuera_del_catalogo"
    assert _errores(resp) == []


def test_pr14_1_sigue_vigente_aunque_todos_declaren_motivo():
    resp = con_motivos(_ej("respuesta_experto"))
    resp["precios"] = []
    for c in resp["componentes"]:
        c["motivo_no_valoracion"] = "depende_del_volumen"
    assert A.errores_cobertura(i17_int.completar(resp, CAT), CAT) == []
    assert any(e.startswith("precios: no hay ningún precio de consumo") for e in _errores(resp))
