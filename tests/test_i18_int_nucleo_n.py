"""I1.8 · integrador: N7, N1, N5 y N4 de CAMBIOS-I18-E §3, aplicados en el núcleo (experto.errores_volumen_nivel y
UNIDADES_TIEMPO) y en la réplica de la puerta. Cada caso pasa por tests/i18_p_datos.reglas, que exige que la puerta dé
exactamente lo mismo que el núcleo (LES-G-097), sobre el catálogo v7 real. N4 (agentes hospedados con su nivel y
sin justificación lo que no usa ningún nivel), al final. Sin red."""
from __future__ import annotations

import copy

import pytest

from tests.i18_p_datos import CONSULTAS, base, comp, fila, precio, reglas


def _vn(r, brief, req, cat):
    return reglas(r, brief, req, cat)["volumen_nivel"]


def _region(cat, catalogo_id):
    e = fila(cat, catalogo_id)
    return e.get("region_ue")


def _ids(r, cid):
    return [x for x in r if x[0] == cid or x[0].startswith("P-9")]


def test_n1_ranking_semantico_valorado_sin_nivel_dedicado():
    brief, req, r, cat = base()
    comp(r, "C-09", "az-ai-search", "Azure AI Search", "datos_conocimiento", "Basic", region=_region(cat, "az-ai-search"))
    precio(r, "P-90", "C-09", "ranking-semantico", base_volumen=CONSULTAS)
    assert ("C-09", "falta_medidor_obligatorio") in _vn(r, brief, req, cat)


def test_n1_foundry_solo_con_la_entrada_valorada():
    brief, req, r, cat = base()
    comp(r, "C-09", "az-foundry", "Microsoft Foundry", "ia", "gpt-6-luna")
    precio(r, "P-90", "C-09", "gpt-6-luna-entrada", base_volumen=CONSULTAS)
    assert _ids(_vn(r, brief, req, cat), "C-09") == [("C-09", "falta_medidor_obligatorio")]
    precio(r, "P-91", "C-09", "gpt-6-luna-salida", base_volumen=CONSULTAS)       # con la salida, pasa
    assert _ids(_vn(r, brief, req, cat), "C-09") == []


def test_n1_regla_mal_formada_falla_cerrado():
    brief, req, r, cat = base()
    fila(cat, "az-ai-search")["reglas_medidores"] = [{"si_usa": [], "exige_uno_de": ["basic"]}]
    comp(r, "C-09", "az-ai-search", "Azure AI Search", "datos_conocimiento", "Basic", region=_region(cat, "az-ai-search"))
    precio(r, "P-90", "C-09", "ranking-semantico", base_volumen=CONSULTAS)
    vn = _vn(r, brief, req, cat)   # también el AI Search de la base (C-02): toda fila con la regla mal formada
    assert ("C-09", "regla_medidores_no_valida") in vn and ("C-02", "regla_medidores_no_valida") in vn


def test_n7_almacenamiento_aprovisionado_de_postgresql_se_cuenta_por_tamano():
    brief, req, r, cat = base()
    comp(r, "C-09", "az-postgresql", "Azure Database for PostgreSQL", "datos_conocimiento", "B1ms")
    precio(r, "P-90", "C-09", "b1ms", instancias=1)
    precio(r, "P-91", "C-09", "almacenamiento", instancias=1)
    salida = reglas(r, brief, req, cat)
    assert ("P-91", "unidad_tiempo_desconocida") not in salida["completar"]
    p91 = next(p for p in salida["completada"]["precios"] if p["id"] == "P-91")
    assert p91["cantidad_mensual"] == 32                       # 32 GiB por instancia, por mes


@pytest.mark.parametrize("catalogo_id, sku, plantilla, veces, regla", [
    ("az-cosmos-db", "Aprovisionado", "aprovisionado-100ru", 1, "instancias_bajo_minimo"),
    ("az-service-bus", "Premium", "premium-mu", 3, "instancias_no_admitidas")])
def test_n5_minimo_y_valores_admitidos(catalogo_id, sku, plantilla, veces, regla):
    brief, req, r, cat = base()
    comp(r, "C-09", catalogo_id, fila(cat, catalogo_id)["nombre_oficial"], fila(cat, catalogo_id)["capa"], sku)
    precio(r, "P-90", "C-09", plantilla, instancias=veces)
    assert ("P-90", regla) in _vn(r, brief, req, cat)


@pytest.mark.parametrize("campo, valor", [("instancias_min", 0), ("instancias_validas", []),
                                          ("instancias_validas", [1, "2"]), ("instancias_min", True)])
def test_n5_valores_del_catalogo_no_validos_fallan_cerrado(campo, valor):
    brief, req, r, cat = base()
    cat = copy.deepcopy(cat)
    nivel = next(n for n in fila(cat, "az-service-bus")["niveles"] if "premium-mu" in (n.get("plantillas") or []))
    nivel[campo] = valor
    comp(r, "C-09", "az-service-bus", "Azure Service Bus", fila(cat, "az-service-bus")["capa"], "Premium")
    precio(r, "P-90", "C-09", "premium-mu", instancias=1)
    assert ("P-90", "instancias_max_no_valido") in _vn(r, brief, req, cat)


# Integrador I1.8 (N4, P18-4, E18-2): nivel «Hospedado 1 vCPU y 2 GiB» en Foundry Agent Service; sin precios o solo con
# memoria de corto plazo no hay nivel que justificar; un agente hospedado es cómputo y se justifica (falla cerrado).
HOSPEDADO = "Hospedado 1 vCPU y 2 GiB"


# Integrador I1.9 (contrato v5, VC18-1): la justificación es {nivel, razon, cita}; la razón «codigo_propio» del nivel la
# cumple una entrada del alcance que nombra el agente hospedado (Brezalia no la tiene: se añade a los requisitos)
CITA_HOSPEDADO = "El asistente será un agente hospedado con Agent Framework."


def _agente(r, cat, jn=False, req=None):
    f = fila(cat, "az-foundry-agent-service")
    just = {"nivel": HOSPEDADO, "razon": "codigo_propio", "cita": CITA_HOSPEDADO} if jn else None
    if jn and req is not None:
        req["campos"]["alcance_funcional"]["entradas"].append(
            {"valor": CITA_HOSPEDADO, "cita": CITA_HOSPEDADO, "fuente": "F1", "origen": "CITADO"})
    comp(r, "C-09", "az-foundry-agent-service", f["nombre_oficial"], f["capa"], "Hosted", region=f["region_ue"],
         justificacion_nivel=just)


@pytest.mark.parametrize("plantillas, jn, esperado", [
    ((), False, []),
    (("memoria-corto-plazo",), False, []),
    (("hosted-vcpu", "hosted-memoria"), False, [("C-09", "nivel_sin_justificar")]),
    (("hosted-vcpu", "hosted-memoria"), True, []),
    (("hosted-vcpu",), True, [("C-09", "falta_medidor_obligatorio")])],
    ids=["sin_precios", "solo_memoria", "hospedado_sin_justificar", "hospedado_justificado", "hospedado_solo_vcpu"])
def test_n4_agente_de_foundry_nucleo_y_puerta(plantillas, jn, esperado):
    brief, req, r, cat = base()
    _agente(r, cat, jn, req)
    for i, pl in enumerate(plantillas):
        precio(r, f"P-9{i}", "C-09", pl, base_volumen=CONSULTAS)
    assert _ids(_vn(r, brief, req, cat), "C-09") == esperado


def test_n4_nivel_sin_plantillas_cuenta_como_usado():
    """Un nivel que no dice sus plantillas no deja saber si se usa: se exige justificación (falla cerrado)."""
    brief, req, r, cat = base()
    cat = copy.deepcopy(cat)
    fila(cat, "az-foundry-agent-service")["niveles"][0].pop("plantillas")
    _agente(r, cat)
    precio(r, "P-90", "C-09", "memoria-corto-plazo", base_volumen=CONSULTAS)
    assert ("C-09", "nivel_sin_justificar") in _vn(r, brief, req, cat)
