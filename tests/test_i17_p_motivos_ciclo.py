"""I1.7 · papel P: motivos con condición (REV16-1 c), ciclo de vida del modelo (LES-G-036 revisada), arquitectura y
referencias puestas por el núcleo. Casos adversos con su resultado esperado. Sin red.
"""
from __future__ import annotations

import copy
import datetime

import pytest

from tests import i17_p_datos as D
from tests.test_i17_p_completar import CAT, HOY, analizar, c_, con, p_, resp
from nucleo import estimacion, experto  # noqa: E402


def _sin_precio(r, cid, motivo, **extra):
    r["precios"] = [p for p in r["precios"] if p["componente_id"] != cid]
    c_(r, cid).update({"motivo_no_valoracion": motivo, **extra})
    return r


def _seguridad(r, **extra):
    r["componentes"].append({"id": "C-07", "catalogo_id": "az-content-safety", "servicio": "Azure AI Content Safety",
                             "capa": "ia", "sku": "Incluido", "region": "swedencentral", "cantidad": 1, "unidad": "servicio",
                             "referencia_id": None, "desviacion_justificada": None,
                             "motivo_no_valoracion": "incluido_en_otro_componente", "existente_del_cliente": None,
                             "incluido_en": "C-01", "justificacion_nivel": None, **extra})
    return r


def test_a_cargo_del_cliente_ya_no_existe_en_v5():
    """I1.9 (PR18-1): «a_cargo_del_cliente» y motivo_cita salen del contrato; un recurso del cliente se declara con
    existente_del_cliente y su entrada EX-nn (tests/test_i19_p_existentes.py)."""
    errores, _ = analizar(_sin_precio(resp(), "C-02", "a_cargo_del_cliente"))
    assert con(errores, "$.componentes[1].motivo_no_valoracion: 'a_cargo_del_cliente' fuera de")
    errores, _ = analizar(_sin_precio(resp(), "C-02", "existente_del_cliente", existente_del_cliente={"entrada": "EX-01"}))
    assert con(errores, "componentes.C-02: existente_del_cliente.entrada «EX-01» no es una entrada")


def test_incluido_en_otro_componente_exige_componente_y_declaracion_del_catalogo():
    errores, c = analizar(_seguridad(resp()))
    assert errores == [], errores
    assert any("incluido en Microsoft Foundry (C-01) según el catálogo (fuente https://learn.microsoft.com/azure/foundry/"
               in x for x in experto.lineas_para_revisor(c, CAT))
    casos = {None: "incluido_en el id del componente", "C-09": "incluido_en «C-09» no es otro componente",
             "C-07": "incluido_en «C-07» no es otro componente",
             "C-02": "el catálogo no declara que az-ai-search incluya az-content-safety"}
    for incl, esperado in casos.items():
        errores, _ = analizar(_seguridad(resp(), incluido_en=incl))
        assert con(errores, esperado), (incl, errores)
    cat = copy.deepcopy(CAT)
    next(e for e in cat["componentes"] if e["id"] == "az-foundry")["incluye"][0].pop("fuente_url")
    errores, _ = analizar(_seguridad(resp()), cat=cat)
    assert con(errores, "el catálogo no declara que az-foundry incluya az-content-safety (con fuente)")


def test_datos_de_motivo_sobrantes_se_rechazan():
    r = resp()
    c_(r, "C-05").update({"incluido_en": "C-01"})
    errores, _ = analizar(r)
    assert con(errores, "componentes.C-05: incluido_en solo va con «incluido_en_otro_componente»")
    c_(r, "C-05").update({"motivo_cita": "Microsoft Teams"})  # I1.9: motivo_cita sale del contrato v5
    assert con(analizar(r)[0], "$.componentes[4]: clave no admitida «motivo_cita»")


def _con_modelo(r, plantilla_e, plantilla_s):
    p_(r, "P-01")["plantilla_id"], p_(r, "P-02")["plantilla_id"] = plantilla_e, plantilla_s
    return r


def test_gpt5_se_retira_durante_la_explotacion_y_se_rechaza():
    errores, _ = analizar(_con_modelo(resp(), "gpt-5-entrada", "gpt-5-salida"), cat=_con_factores_gpt5())
    assert con(errores, "precios.P-01: «az-foundry/gpt-5-entrada» se retira el 2027-02-09")


def _con_factores_gpt5():
    cat = copy.deepcopy(CAT)
    fila = next(e for e in cat["componentes"] if e["id"] == "az-foundry")
    fila["factores_estandar"] += [dict(D.FACTOR_ENTRADA, plantillas=["gpt-5-entrada", "gpt-5.4-entrada"]),
                                  dict(D.FACTOR_SALIDA, plantillas=["gpt-5-salida", "gpt-5.4-salida"])]
    return cat


def test_limite_de_retirada_en_la_frontera_y_sin_fecha_publicada():
    r = resp()
    semanas = experto.duracion_gantt(r)
    limite = experto.limite_retirada(HOY, semanas)
    cat = copy.deepcopy(CAT)
    pl = next(p for e in cat["componentes"] if e["id"] == "az-foundry" for p in e["plantillas_precio"]
              if p["id"] == "gpt-6-luna-entrada")
    pl["ciclo_vida"]["retirada"] = limite.isoformat()
    assert analizar(r, cat=cat)[0] == []
    pl["ciclo_vida"]["retirada"] = (limite - datetime.timedelta(days=1)).isoformat()
    assert con(analizar(r, cat=cat)[0], "precios.P-01: «az-foundry/gpt-6-luna-entrada» se retira el")
    pl["ciclo_vida"].update({"retirada": None, "ga": "2026-11-01"})
    assert con(analizar(r, cat=cat)[0], "no es GA hasta el 2026-11-01")
    errores, c = analizar(r)
    lineas = experto.lineas_para_revisor(c, CAT, fecha=HOY, semanas=semanas)
    assert any("fecha de retirada aún no publicada" in x and f"límite exigido {limite}" in x for x in lineas)


def test_fila_con_ciclo_de_vida_y_plantilla_sin_el_falla_cerrado():
    cat = copy.deepcopy(CAT)
    pl = next(p for e in cat["componentes"] if e["id"] == "az-foundry" for p in e["plantillas_precio"]
              if p["id"] == "gpt-6-luna-salida")
    pl.pop("ciclo_vida")
    assert con(analizar(resp(), cat=cat)[0], "precios.P-02: la plantilla «az-foundry/gpt-6-luna-salida» no trae ciclo")


@pytest.mark.parametrize("fecha, semanas, esperado", [("2026-10-13", 8, "2027-12-08"), ("2028-01-10", 7, "2029-02-28"),
                                                       ("2026-02-28", 52, "2028-02-27")])
def test_limite_de_retirada(fecha, semanas, esperado):
    assert experto.limite_retirada(fecha, semanas).isoformat() == esperado


def test_duracion_gantt_igual_que_la_estimacion():
    r = resp()
    est = {"codigo": "OF-BREZALIA-001-A", "carga": {"alta": {"cliente": "Brezalia", "titulo": "Asistente de pruebas"},
                                                    "respuestas_expertos": {"azure": {"respuesta": r}}, "requisitos": {}}}
    entrada, _ = estimacion.componer_entrada(est, [{"nombre": "Hito 1", "porcentaje": 100}])
    assert experto.duracion_gantt(r) == entrada["duracion_semanas"]


def test_arquitectura_por_id_del_catalogo():
    r = resp()
    r["arquitectura_id"] = "otra-arquitectura"
    assert con(analizar(r)[0], "arquitectura_id «otra-arquitectura» no está en la lista del catálogo")
    cat = copy.deepcopy(CAT)
    cat["arquitecturas_referencia"][0]["url"] = "https://learn.microsoft.com/azure/search/search-what-is-azure-search"
    assert con(analizar(resp(), cat=cat)[0], "no trae título y URL de arquitectura de Learn")
    cat.pop("arquitecturas_referencia")
    assert con(analizar(resp(), cat=cat)[0], "ninguna: catálogo sin arquitecturas")


def test_referencia_de_otro_servicio_se_sustituye_y_se_anota():
    r = resp()
    c_(r, "C-05")["referencia_id"] = "REF-01"  # Entra ID con la página de RAG de AI Search (caso real de I1.6)
    errores, c = analizar(r)
    assert errores == [], errores
    aj = next(a for a in c["valoracion_nucleo"]["ajustes"] if a["campo"] == "componentes.C-05.referencia_id")
    assert aj["recibido"] == "REF-01" and aj["puesto"] != "REF-01"
    assert any("el experto había puesto REF-01" in x for x in experto.lineas_para_revisor(c, CAT))
    assert experto.proyectar_modelo(c) == r


def test_componente_fuera_del_catalogo_necesita_su_referencia():
    r = resp()
    r["componentes"].append({"id": "C-07", "catalogo_id": None, "servicio": "Portal interno del cliente",
                             "capa": "usuarios_canales", "sku": "Existente", "region": "global", "cantidad": 1,
                             "unidad": "portal", "referencia_id": None,
                             "desviacion_justificada": "El cliente ya tiene un portal interno que enlaza con Teams.",
                             "motivo_no_valoracion": "fuera_del_catalogo", "existente_del_cliente": None,
                             "incluido_en": None,
                             "justificacion_nivel": None})
    assert con(analizar(r)[0], "componentes.C-07: un componente sin catalogo_id lleva la referencia_id")
    r["componentes"][-1]["referencia_id"] = "REF-01"
    assert analizar(r)[0] == []
