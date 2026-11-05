"""I1.7 · papel P: factores estándar del catálogo, factor_override citado, comillas y campos de dimensionamiento.

Decisión 2 del comercial (factores en el catálogo; el experto solo los cambia citando un requisito y queda marcado) y
decisiones del PM (cita de nivel solo de campos de dimensionamiento, comillas normalizadas). Casos adversos con su
resultado esperado; PR16-4 y PR16-5 con sus textos reales de I1.6.
"""
from __future__ import annotations

import copy

import pytest

from tests import i17_p_datos as D
from tests.test_i17_p_completar import BRIEF, CAT, analizar, c_, con, p_, resp
from nucleo import experto  # noqa: E402


def _fila(cat, cid):
    return next(e for e in cat["componentes"] if e["id"] == cid)


def test_sin_factor_estandar_falla_cerrado_y_el_override_citado_lo_permite_marcado():
    cat = copy.deepcopy(CAT)
    _fila(cat, "az-foundry").pop("factores_estandar")
    errores, _ = analizar(resp(), cat=cat)
    assert con(errores, "precios.P-01: el catálogo no da factor estándar para «az-foundry/gpt-6-luna-entrada»")
    r = resp()
    for pid in ("P-01", "P-02"):
        p_(r, pid)["factor_override"] = {"valor": 3000, "cita": "Unas 2.000 consultas al mes.",
                                         "justificacion": "Cada consulta adjunta un procedimiento entero como contexto."}
    errores, c = analizar(r, cat=cat)
    assert errores == [], errores
    f = p_(c, "P-01")["base_volumen"]["factor"]
    assert (f["origen"], f["valor"], p_(c, "P-01")["cantidad_mensual"]) == ("experto", 3000, 6)
    assert any("FACTOR CAMBIADO POR EL EXPERTO" in x and "no hay" in x for x in experto.lineas_para_revisor(c, cat))


def test_override_sobre_el_estandar_se_marca_con_el_valor_estandar():
    r = resp()
    p_(r, "P-01")["factor_override"] = {"valor": 4000, "cita": "Unos 3.000 documentos.",
                                        "justificacion": "Los procedimientos son largos y se recuperan enteros."}
    errores, c = analizar(r)
    assert errores == [], errores
    linea = next(x for x in experto.lineas_para_revisor(c, CAT) if "P-01" in x)
    assert "FACTOR CAMBIADO POR EL EXPERTO" in linea and "estándar del catálogo 2500 tokens de entrada" in linea


@pytest.mark.parametrize("cita", ["Plazo deseado de unas 8 semanas.", "Unos 20.000 euros para el piloto.",
                                  "Unas 3.000 consultas al mes."])
def test_override_con_cita_que_no_es_de_dimensionamiento_se_rechaza(cita):
    r = resp()
    p_(r, "P-01")["factor_override"] = {"valor": 4000, "cita": cita, "justificacion": "Justificación de prueba larga."}
    errores, _ = analizar(r)
    assert con(errores, "precios.P-01: factor_override.cita") and con(errores, "no es una cita literal de un campo de "
                                                                               "dimensionamiento")


def test_factor_ambiguo_o_incompleto_falla_cerrado():
    cat = copy.deepcopy(CAT)
    _fila(cat, "az-foundry")["factores_estandar"].append(dict(D.FACTOR_ENTRADA, caso_uso="agente con herramientas"))
    errores, _ = analizar(resp(), cat=cat)
    assert con(errores, "el catálogo da 2 factores estándar para «az-foundry/gpt-6-luna-entrada»")
    cat = copy.deepcopy(CAT)
    _fila(cat, "az-foundry")["factores_estandar"][0].pop("fuente")
    errores, _ = analizar(resp(), cat=cat)
    assert con(errores, "está incompleto (valor > 0, unidad, fuente y justificación)")


def test_factor_en_la_plantilla_por_id_y_en_el_catalogo_con_clave_completa():
    cat = copy.deepcopy(CAT)
    fila = _fila(cat, "az-foundry")
    fila.pop("factores_estandar")
    cat["factores_estandar"] = [dict(D.FACTOR_ENTRADA, id="f-entrada", plantillas=[]),
                                dict(D.FACTOR_SALIDA, plantillas=["az-foundry/gpt-6-luna-salida"])]
    next(p for p in fila["plantillas_precio"] if p["id"] == "gpt-6-luna-entrada")["factor_estandar"] = "f-entrada"
    errores, c = analizar(resp(), cat=cat)
    assert errores == [], errores
    assert p_(c, "P-02")["cantidad_mensual"] == 0.8
    cat["factores_estandar"][1]["plantillas"] = ["gpt-6-luna-salida"]  # un id suelto en el catálogo no nombra la fila
    errores, _ = analizar(resp(), cat=cat)
    assert con(errores, "precios.P-02: el catálogo no da factor estándar")


def test_rev16_4_la_cita_de_documentos_no_vale_para_un_factor_por_consulta():
    r = resp()
    p_(r, "P-01")["base_volumen"] = {"cita": "Unos 3.000 documentos.", "cantidad_base": 3000, "unidad_base": "consultas"}
    errores, _ = analizar(r)
    assert con(errores, "precios.P-01: la cita «Unos 3.000 documentos.» no habla de lo que cuenta la base")


@pytest.mark.parametrize("envuelta", ["«Unas 2.000 consultas al mes.»", '"Unas 2.000 consultas al mes."',
                                      "“Unas 2.000 consultas al mes.”", " «Unas 2.000 consultas al mes.» "])
def test_pr16_5_comillas_que_envuelven_la_cita_se_normalizan_y_se_anotan(envuelta):
    r = resp()
    p_(r, "P-01")["base_volumen"]["cita"] = envuelta
    _p0v3(r, "«Los nodos van en zonas de disponibilidad.»")  # I1.9: la cita de la justificación v5
    errores, c = analizar(r, req=_req_con("Los nodos van en zonas de disponibilidad."))
    assert errores == [], errores
    assert p_(c, "P-01")["base_volumen"]["cita"] == "Unas 2.000 consultas al mes."
    campos = {a["campo"] for a in c["valoracion_nucleo"]["ajustes"]}
    assert {"precios.P-01.base_volumen.cita", "componentes.C-04.justificacion_nivel.cita"} <= campos
    assert experto.proyectar_modelo(c) == r


def _req_con(*alcance):
    """Los requisitos de Brezalia con más capacidades citadas en el alcance funcional."""
    req = copy.deepcopy(D.estado_brezalia()["carga"]["requisitos"])
    req["campos"]["alcance_funcional"]["entradas"] += [{"valor": v, "cita": "frase literal de la transcripción",
                                                        "fuente": "F1", "origen": "CITADO"} for v in alcance]
    return req


def _p0v3(r, cita):
    """I1.9: App Service P0v3 (no es el cómputo por defecto) justificado con la razón «redundancia_zona» del catálogo."""
    p_(r, "P-05")["plantilla_id"] = "p0v3-linux"
    c_(r, "C-04")["justificacion_nivel"] = {"nivel": "P0v3", "razon": "redundancia_zona", "cita": cita}


@pytest.mark.parametrize("cita", ["«Unas 2.000» consultas al mes.", "«Unas 2.000 consultas» al «mes».",
                                  "«Unas 2.000 consultas al mes.»»"])
def test_comillas_que_no_envuelven_la_cita_entera_no_se_quitan(cita):
    r = resp()
    p_(r, "P-01")["base_volumen"]["cita"] = cita
    errores, _ = analizar(r)
    assert con(errores, "precios.P-01: base_volumen.cita")


def test_pr16_4_un_plazo_no_justifica_un_nivel_y_un_campo_de_dimensionamiento_si():
    r = resp()
    _p0v3(r, "Plazo deseado de unas 8 semanas.")  # caso real de I1.6
    errores, _ = analizar(r)
    assert con(errores, "componentes.C-04: la cita «Plazo deseado de unas 8 semanas.» no es literal de volumetria")
    # I1.9 (PR18-3): un campo de dimensionamiento ya no basta; la cita tiene que cumplir la razón (comprobado por código)
    for cita in ("Microsoft Teams", "Buscar en procedimientos y manuales de equipos y citar el documento de origen.",
                 "Los documentos están en SharePoint Online del tenant."):
        r = resp()
        _p0v3(r, cita)
        assert con(analizar(r)[0], "componentes.C-04: la razón «redundancia_zona» exige que la cita diga"), cita
    r = resp()
    _p0v3(r, "Los nodos van en zonas de disponibilidad.")
    assert analizar(r, req=_req_con("Los nodos van en zonas de disponibilidad."))[0] == []


def test_citas_de_dimensionamiento_del_brief_real():
    citas = experto.citas_dimensionamiento(None, BRIEF["texto"])
    assert "Unas 2.000 consultas al mes." in citas and "Microsoft Teams" in citas
    assert "Plazo deseado de unas 8 semanas." not in citas and "Castellano." not in citas
    assert "Para el piloto no se necesita red privada; basta con la autenticación de Entra ID." not in citas
