"""I1.9 · papel P: recursos que el cliente ya tiene (PR18-1, VC18-2) en el núcleo del experto.

Cada caso fija el resultado del núcleo y exige que las réplicas de la puerta den lo mismo (i19_p_datos.reglas_i19).
Los dos casos reales de Hostelia (I1.8) se reproducen con sus respuestas registradas pasadas a v5.
"""
from __future__ import annotations

import copy

import pytest

from tests import i19_p_datos as D
from nucleo import anexo_consumo, experto

CAT = D.catalogo_i19()
H1, H2 = "hostelia_1/lista_A", "hostelia_2/bloqueada"
DESVIACION = "El App Service de EX-05 aloja la API de RR. HH. del cliente; el bot necesita su propio cómputo."


def caso_h1(existentes: dict | None = None, quitar_c06: bool = True):
    """H1 corregida: Teams, SharePoint y API Management del cliente; el App Service del bot, nuevo con su motivo."""
    req = D.requisitos_hostelia(H1)
    br = D.brief_hostelia(H1, req)
    r = D.a_v5(D.modelo_hostelia(H1), existentes if existentes is not None
               else {"C-01": "EX-02", "C-07": "EX-03", "C-06": "EX-06"})
    if quitar_c06:
        r["precios"] = [p for p in r["precios"] if p["componente_id"] != "C-06"]
    next(c for c in r["componentes"] if c["id"] == "C-03")["desviacion_justificada"] = DESVIACION
    return D.con_brief(r, br), br, req


def test_control_h1_corregida_se_acepta_y_las_replicas_dan_lo_mismo():
    r, br, req = caso_h1()
    errores, completada = D.analizar(r, br, req, CAT)
    assert errores == [] and completada is not None
    assert {k: v for k, v in D.reglas_i19(r, br, req, CAT).items() if k != "completada"} == {
        "completar": [], "volumen_nivel": [], "existentes": [], "arquitectura": [], "ciclo": []}


def test_caso_real_h1_api_management_cobrado_siendo_del_cliente_se_rechaza():
    """PR18-1/VA18-2: la sesión 1 valoró un API Management Basic v2 nuevo (173,45 € al mes) que el cliente ya tiene."""
    r, br, req = caso_h1({"C-01": "EX-02", "C-07": "EX-03"}, quitar_c06=False)
    next(c for c in r["componentes"] if c["id"] == "C-06")["justificacion_nivel"] = {
        "nivel": "Basic v2", "razon": "nivel_nombrado", "cita": "API Management"}
    errores, _ = D.analizar(r, br, req, CAT)
    assert any(e.startswith("componentes.C-06: Azure API Management se valora y el cliente ya lo tiene (EX-06")
               for e in errores)
    reglas = D.reglas_i19(r, br, req, CAT)
    assert reglas["existentes"] == [("C-06", "existente_valorado")]
    assert reglas["volumen_nivel"] == [("C-06", "razon_no_cumplida")]  # PR18-3: «API Management» no nombra Basic v2


def test_caso_real_h2_bot_a_cargo_del_cliente_citando_otro_app_service_se_rechaza():
    """VC18-2: en la sesión 2 el App Service del cliente (el de su API de RR. HH.) quedó como el cómputo del bot."""
    req = D.requisitos_hostelia(H2)
    br = D.brief_hostelia(H2, req)
    r = D.con_brief(D.a_v5(D.modelo_hostelia(H2), {"C-01": "EX-02", "C-03": "EX-03", "C-06": "EX-05",
                                                   "C-08": "EX-06"}), br)
    errores, _ = D.analizar(r, br, req, CAT)
    assert errores == [e for e in errores if e.startswith("componentes.C-02: Azure AI Bot Service se valora y la "
                                                          "propuesta no valora ningún cómputo propio")] and errores
    assert D.reglas_i19(r, br, req, CAT)["arquitectura"] == [("C-02", "canal_sin_computo")]
    # Con la línea visible para el cliente y el revisor, vale; y la nota lo enseña
    r["supuestos"].append({"id": "S-08", "texto": "La solución no tiene cómputo propio: el bot llama directamente al "
                           "agente de Microsoft Foundry.", "confianza": "MEDIA", "hechos": ["C-02", "C-05"]})
    errores, c = D.analizar(r, br, req, CAT)
    assert errores == []
    assert any(x.startswith("Canal sin cómputo propio: Azure AI Bot Service (C-02); el experto lo declara en S-08")
               for x in experto.lineas_para_revisor(c, CAT, requisitos=req))


@pytest.mark.parametrize("mutar, esperado", [
    (lambda r: r["precios"].append({"id": "P-09", "componente_id": "C-06", "plantilla_id": "basic-v2", "instancias": 1,
                                    "base_volumen": None, "factor_override": None}), ("C-06", "existente_con_precio")),
    (lambda r: D.comp_de(r, "C-06").update(justificacion_nivel={"nivel": "Basic v2", "razon": "red_virtual",
                                                                 "cita": "x"}), ("C-06", "existente_con_nivel")),
    (lambda r: D.comp_de(r, "C-06").update(existente_del_cliente={"entrada": "EX-09"}), ("C-06", "existente_desconocido")),
    (lambda r: D.comp_de(r, "C-06").update(existente_del_cliente={"entrada": "EX-05"}),
     ("C-06", "existente_otro_servicio")),
    (lambda r: D.comp_de(r, "C-07").update(existente_del_cliente={"entrada": "EX-02"}), ("C-07", "existente_repetido")),
    (lambda r: D.comp_de(r, "C-06").update(motivo_no_valoracion="no_aplica"), ("C-06", "existente_sin_motivo")),
    (lambda r: D.comp_de(r, "C-06").update(existente_del_cliente=None), ("C-06", "motivo_sin_existente")),
    (lambda r: D.comp_de(r, "C-03").update(desviacion_justificada="El bot necesita un cómputo propio para atender."),
     ("C-03", "existente_valorado")),
])
def test_reglas_del_recurso_del_cliente(mutar, esperado):
    r, br, req = caso_h1()
    mutar(r)
    assert esperado in D.reglas_i19(r, br, req, CAT)["existentes"]


def test_un_sistema_del_cliente_fuera_del_catalogo_se_dibuja_sin_desviacion_ni_referencia():
    """EX-04 (la API REST de RR. HH., fuera del catálogo): ni desviacion_justificada, ni referencia, ni región «global»."""
    r, br, req = caso_h1()
    r["componentes"].append({"id": "C-09", "catalogo_id": None, "servicio": "API REST de RR. HH. del cliente",
                             "capa": "aplicacion_integracion", "sku": "del cliente", "region": "swedencentral",
                             "cantidad": 1, "unidad": "API", "referencia_id": None, "desviacion_justificada": None,
                             "motivo_no_valoracion": "existente_del_cliente", "existente_del_cliente": {"entrada": "EX-04"},
                             "incluido_en": None, "justificacion_nivel": None})
    r["flujos"].append({"origen": "C-06", "destino": "C-09", "descripcion": "API Management publica la API del cliente"})
    errores, c = D.analizar(r, br, req, CAT)
    assert errores == [] and c is not None
    D.reglas_i19(r, br, req, CAT)
    assert experto.region_exige_catalogo(D.comp_de(r, "C-09")) is None
