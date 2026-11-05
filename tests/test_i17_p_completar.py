"""I1.7 · papel P: contrato v4 del experto, lo que pone el núcleo y sus casos adversos (LES-G-096.6). Sin red.

Datos reales: el brief y los requisitos de Brezalia (sesión 2 de B en I1.6). El catálogo lleva lo de I1.7 simulado en
tests/i17_p_datos.py hasta que llegue el derivado del papel E.
"""
from __future__ import annotations

import copy

import pytest

from tests import i17_p_datos as D
from nucleo import esquema, experto  # noqa: E402  (i17_p_datos fija sys.path)

CAT = D.catalogo_i17()
INST = D.instantanea_i17(CAT)
EST = D.estado_brezalia()
BRIEF = EST["carga"]["briefs"][0]
REQ = EST["carga"]["requisitos"]
PERF = D.perfiles(BRIEF)
HOY = "2026-10-13"


def analizar(r, brief=BRIEF, cat=CAT, inst=INST, hoy=HOY, req=REQ):
    return experto.analizar_respuesta(r, brief, cat, PERF, req, inst, hoy)


def resp():
    return D.respuesta_v4(BRIEF)


def p_(r, pid):
    return next(p for p in r["precios"] if p["id"] == pid)


def c_(r, cid):
    return next(c for c in r["componentes"] if c["id"] == cid)


def con(errores, texto):
    return any(texto in e for e in errores)


def test_control_valida_completa_y_proyecta_exacto():
    r = resp()
    errores, c = analizar(r)
    assert errores == [] and c is not None
    assert esquema.validar(c, esquema.cargar("respuesta_experto_completa")) == []
    assert experto.proyectar_modelo(c) == r
    cant = {p["id"]: p["cantidad_mensual"] for p in c["precios"]}
    assert cant == {"P-01": 5, "P-02": 0.8, "P-03": 730, "P-04": 4, "P-05": 730}
    p1 = p_(c, "P-01")
    art = INST["plantillas"]["az-foundry/gpt-6-luna-entrada"]
    assert (p1["precio"], p1["unidad"], p1["filtro"]) == (art["precio_unitario"], art["unidad"], art["filtro"])
    assert p1["base_volumen"]["factor"]["origen"] == "catalogo" and p1["concepto"] == art["meterName"]
    refs = {x["id"]: x for x in c["referencias"]}
    for comp in c["componentes"]:  # PR16-1 por construcción: la referencia es la de la fila del catálogo
        fila = next(e for e in CAT["componentes"] if e["id"] == comp["catalogo_id"])
        assert experto.normalizar_url(refs[comp["referencia_id"]]["url"]) == experto.normalizar_url(fila["referencia_url"])
    assert c["valoracion_nucleo"]["arquitectura"]["url"] == D.ARQUITECTURA["url"]


def test_una_respuesta_v3_con_precios_escritos_por_el_modelo_se_rechaza_por_esquema():
    r = resp()
    p_(r, "P-01").update({"filtro": INST["plantillas"]["az-foundry/gpt-6-luna-entrada"]["filtro"], "precio": 0.2})
    errores, c = analizar(r)
    assert c is None and con(errores, "clave no admitida «filtro»") and con(errores, "clave no admitida «precio»")


@pytest.mark.parametrize("plantilla, cid, esperado", [
    ("gpt-9-entrada", "C-01", "plantilla_id «gpt-9-entrada» no es una plantilla"),
    ("basic", "C-01", "no es una plantilla de Microsoft Foundry"),
    ("az-ai-search/basic", "C-01", "no es una plantilla de Microsoft Foundry"),
])
def test_plantilla_desconocida(plantilla, cid, esperado):
    r = resp()
    p_(r, "P-01").update({"plantilla_id": plantilla, "componente_id": cid})
    errores, c = analizar(r)
    assert c is None and con(errores, esperado)


def test_plantilla_con_prefijo_de_su_fila_y_auxiliar_atado():
    r = resp()
    p_(r, "P-03")["plantilla_id"] = "az-ai-search/basic"
    r["precios"].append({"id": "P-06", "componente_id": "C-02", "plantilla_id": "punto-conexion", "instancias": 2,
                         "base_volumen": None, "factor_override": None})
    errores, c = analizar(r)
    assert errores == [], errores
    assert p_(c, "P-06")["plantilla"] == "az-private-link/punto-conexion" and p_(c, "P-06")["cantidad_mensual"] == 1460


def test_region_distinta_de_la_de_la_instantanea():
    r = resp()
    c_(r, "C-02")["region"] = "westeurope"
    errores, _ = analizar(r)
    assert con(errores, "precios.P-03: la instantánea tiene el precio de «az-ai-search/basic» en «francecentral»")


def test_instancias_en_volumen_y_base_en_tiempo():
    r = resp()
    p_(r, "P-01")["instancias"] = 1
    p_(r, "P-03")["base_volumen"] = copy.deepcopy(D.CONSULTAS)
    errores, _ = analizar(r)
    assert con(errores, "precios.P-01: la plantilla «az-foundry/gpt-6-luna-entrada» se factura por volumen: instancias")
    assert con(errores, "precios.P-03: la plantilla «az-ai-search/basic» se factura por tiempo")


def test_unidad_de_tiempo_desconocida_falla_cerrado():
    inst = copy.deepcopy(INST)
    inst["plantillas"]["az-ai-search/basic"]["unidad"] = "1/Week"
    errores, _ = analizar(resp(), inst=D.resellar(inst))
    assert con(errores, "la unidad «1/Week» de «az-ai-search/basic» no es una unidad de tiempo conocida")


def test_dias_y_meses_se_cuentan_por_su_unidad():
    inst = copy.deepcopy(INST)
    inst["plantillas"]["az-ai-search/basic"]["unidad"] = "1/Day"
    inst["plantillas"]["az-app-service/b1-linux"]["unidad"] = "1/Month"
    errores, c = analizar(resp(), inst=D.resellar(inst))
    assert errores == [], errores
    assert p_(c, "P-03")["cantidad_mensual"] == 30.416667 and p_(c, "P-05")["cantidad_mensual"] == 1


def test_sin_referencias_del_modelo_el_nucleo_pone_las_suyas():
    r = resp()
    r["referencias"], r["supuestos"][0]["hechos"] = [], ["R-identidad_acl_origen"]
    errores, c = analizar(r)
    assert errores == [], errores
    assert len(c["referencias"]) == 7 and all(x["origen"] in ("catalogo", "arquitectura") for x in c["referencias"])
    assert experto.proyectar_modelo(c) == r


def test_instancias_no_enteras_van_a_la_nota():
    r = resp()
    p_(r, "P-05")["instancias"] = 0.5
    errores, c = analizar(r)
    assert errores == [] and p_(c, "P-05")["cantidad_mensual"] == 365
    assert any("Instancias no enteras" in x and "P-05" in x for x in experto.lineas_para_revisor(c, CAT))


@pytest.mark.parametrize("url", ["https://:secreto@learn.microsoft.com/azure/architecture/x",
                                 "https://usuario@learn.microsoft.com/azure/search", "https://@learn.microsoft.com/azure/search"])
def test_revision_una_url_con_credenciales_no_es_de_learn(url):
    assert experto.normalizar_url(url) == "" and not experto.es_referencia_permitida(url)
    assert not experto.es_referencia_arquitectura(url)
    r = resp()
    r["referencias"][0]["url"] = url  # en la respuesta ya la para el patrón del esquema
    assert con(analizar(r)[0], "$.referencias[0].url: no casa con")
    cat = copy.deepcopy(CAT)  # en el catálogo, la para normalizar_url
    cat["arquitecturas_referencia"][0]["url"] = url
    assert con(analizar(resp(), cat=cat)[0], "no trae título y URL de arquitectura de Learn")


def test_revision_frontera_de_la_cantidad_maxima():
    from decimal import Decimal
    assert experto._cantidad(Decimal("1e12")) == Decimal("1e12")
    assert experto._cantidad(Decimal("1000000000000.000001")) is None
    cat = copy.deepcopy(CAT)
    factor = next(e for e in cat["componentes"] if e["id"] == "az-foundry")["factores_estandar"][0]
    factor["valor"] = 500000000000000  # 2.000 consultas × 5e14 ÷ 1e6 = 1e12 justo: vale
    errores, c = analizar(resp(), cat=cat)
    assert errores == [] and p_(c, "P-01")["cantidad_mensual"] == 1000000000000
    factor["valor"] = 500000000000001
    assert con(analizar(resp(), cat=cat)[0], "precios.P-01: la cuenta de «az-foundry/gpt-6-luna-entrada» pasa de")


@pytest.mark.parametrize("url", [123, None, ["https://learn.microsoft.com/azure"], {"u": 1}])
def test_revision_url_de_otro_tipo_no_lanza(url):
    assert experto.normalizar_url(url) == "" and not experto.es_referencia_permitida(url)
    cat = copy.deepcopy(CAT)
    cat["arquitecturas_referencia"][0]["url"] = url
    assert con(analizar(resp(), cat=cat)[0], "no trae título y URL de arquitectura de Learn")
