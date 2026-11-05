"""I1.8, papel E: el catálogo contra el núcleo tal como está (lo edita otro papel). Lo que ya aplica se prueba en verde;
lo que el catálogo declaraba y el núcleo aún no aplicaba (CAMBIOS-I18-E §3: N1, N4, N5 y N7) se fijó con su estado.
I1.9 (papel E): la justificación pasa al contrato común {nivel, razon, cita} (tests/i19_e_comun.jn) y el nivel por
defecto de cada fila (PostgreSQL D2ds_v5, Cosmos DB sin servidor, AI Search Basic) va sin justificar."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
from nucleo import experto  # noqa: E402
from tests.i19_e_comun import BRIEF, CONS, REQ, jn  # noqa: E402

CAT = json.loads((RAIZ / "sandbox/datos/catalogo_componentes.json").read_text(encoding="utf-8"))
INST = json.loads((RAIZ / "sandbox/datos/precios_instantanea.json").read_text(encoding="utf-8"))
DOCS = "Unos 3.000 documentos."
FILAS = {e["id"]: e for e in CAT["componentes"]}


def _comp(catalogo_id, nivel=None, sku="estándar", razon=None):
    e = FILAS[catalogo_id]
    j = jn(nivel, razon) if razon else {"nivel": nivel, "razon": "sin_razon", "cita": CONS} if nivel else None
    return {"id": "C-01", "catalogo_id": catalogo_id, "servicio": e["nombre_oficial"], "capa": e["capa"], "sku": sku,
            "region": e.get("region_precio") or e.get("region_ue"), "cantidad": 1, "unidad": "recurso",
            "referencia_id": None, "desviacion_justificada": None, "justificacion_nivel": j,
            "motivo_no_valoracion": "no_aplica", "existente_del_cliente": None, "incluido_en": None}


def _p(i, plantilla, n=None, cita=None, base=None, unidad=None):
    b = None if cita is None else {"cita": cita, "cantidad_base": base, "unidad_base": unidad}
    return {"id": f"P-0{i}", "componente_id": "C-01", "plantilla_id": plantilla, "instancias": n if b is None else None,
            "base_volumen": b, "factor_override": None}


def _valorar(comp, precios):
    resp = {"arquitectura_id": "foundry-chat-basica", "referencias": [], "componentes": [comp], "precios": precios}
    c, errs = experto.completar(resp, CAT, INST, REQ, BRIEF)
    errs += experto.errores_volumen_nivel(c, BRIEF, REQ, CAT)
    return {e["regla"] for e in errs}, {p["id"]: p.get("cantidad_mensual") for p in c.get("precios") or []}


@pytest.mark.parametrize("comp, precios, regla", [
    (_comp("az-app-service"), [_p(1, "b1-linux", 2)], "instancias_sin_justificar"),
    (_comp("az-app-service", "B1"), [_p(1, "b1-linux", 4)], "instancias_sobre_limite"),
    (_comp("az-container-apps", "Dedicado D4", razon="microservicios"), [_p(1, "dedicado-vcpu", 1)], "falta_medidor_obligatorio"),
    (_comp("az-logic-apps", "Standard WS1", razon="privado_red"), [_p(1, "standard-vcpu", 1)], "falta_medidor_obligatorio"),
    (_comp("az-service-bus", "Standard", razon="temas_y_sesiones"), [_p(1, "standard-base", 1)], "falta_medidor_obligatorio"),
    (_comp("az-cosmos-db"), [_p(1, "sin-servidor-ru", cita=CONS, base=2000, unidad="consultas")],
     "falta_medidor_obligatorio"),
    (_comp("az-container-apps"), [_p(1, "dedicado-vcpu", 1), _p(2, "dedicado-memoria", 1),
                                  _p(3, "dedicado-gestion", 1)], "nivel_sin_justificar")],
    ids=["b1_dos", "b1_cuatro", "d4_solo_vcpu", "ws1_solo_vcpu", "sb_sin_operaciones", "cosmos_sin_capacidad",
         "d4_sin_justificar"])
def test_el_nucleo_ya_aplica_lo_del_catalogo(comp, precios, regla):
    assert regla in _valorar(comp, precios)[0]


def test_lo_correcto_pasa_y_se_cuenta_con_las_unidades_por_instancia_y_los_factores():
    reglas, cant = _valorar(_comp("az-container-apps", "Dedicado D4", razon="microservicios"), [
        _p(1, "dedicado-vcpu", 1), _p(2, "dedicado-memoria", 1), _p(3, "dedicado-gestion", 1)])
    assert reglas == set() and cant == {"P-01": 2920, "P-02": 11680, "P-03": 730}
    reglas, cant = _valorar(_comp("az-document-intelligence"), [_p(1, "lectura", cita=DOCS, base=3000, unidad="documentos")])
    assert reglas == set() and cant == {"P-01": 30}
    assert _valorar(_comp("az-foundry-agent-service"), []) == (set(), {})  # agente de solicitud, sin precios


def test_n7_almacenamiento_aprovisionado_de_postgresql():
    reglas, cant = _valorar(_comp("az-postgresql", "B1ms", razon="no_productivo"), [_p(1, "b1ms", 1), _p(2, "almacenamiento", 1)])
    assert reglas == set() and cant["P-02"] == 32


@pytest.mark.parametrize("comp, precios", [
    (_comp("az-foundry", sku="gpt-6-luna"), [_p(1, "gpt-6-luna-entrada", cita=CONS, base=2000, unidad="consultas")]),
    (_comp("az-ai-search"), [_p(1, "ranking-semantico", cita=CONS, base=2000, unidad="consultas")])],
    ids=["foundry_solo_entrada", "ranking_sin_nivel"])
def test_n1_reglas_de_medidores(comp, precios):
    assert "falta_medidor_obligatorio" in _valorar(comp, precios)[0]


@pytest.mark.parametrize("comp, precios", [
    (_comp("az-cosmos-db", "Aprovisionado", razon="varias_regiones"), [_p(1, "aprovisionado-100ru", 1), _p(2, "almacenamiento", cita=CONS,
                                                                                    base=2000, unidad="consultas")]),
    (_comp("az-service-bus", "Premium", razon="aislamiento"), [_p(1, "premium-mu", 3)])], ids=["cosmos_bajo_minimo", "sb_premium_tres"])
def test_n5_minimo_y_valores_de_instancias(comp, precios):
    assert _valorar(comp, precios)[0]  # I1.8 (integrador): N5 aplicado en el núcleo y en la réplica


# Revisión E2: un xfail no dice por qué falla. Esto fija la forma exacta del hueco de hoy; si el núcleo cambia, también avisa.
ESTADO_ACTUAL = [
    # I1.8 (integrador): N7, N1 y N5 aplicados en el núcleo y en la réplica de la puerta; N4 sigue pendiente
    ("N7", _comp("az-postgresql", "B1ms", razon="no_productivo"), [_p(1, "b1ms", 1), _p(2, "almacenamiento", 1)], set()),
    ("N1", _comp("az-foundry", sku="gpt-6-luna"), [_p(1, "gpt-6-luna-entrada", cita=CONS, base=2000, unidad="consultas")],
     {"falta_medidor_obligatorio"}),
    # I1.9 (P, E19-4/VC18-7): el ranking semántico es opcional con «sin» por defecto y la cita no lo pide
    ("N1", _comp("az-ai-search"), [_p(1, "ranking-semantico", cita=CONS, base=2000, unidad="consultas")],
     {"falta_medidor_obligatorio", "opcional_sin_requisito"}),
    ("N5", _comp("az-cosmos-db", "Aprovisionado", razon="varias_regiones"), [_p(1, "aprovisionado-100ru", 1), _p(2, "almacenamiento", cita=CONS,
                                                                                     base=2000, unidad="consultas")],
     {"instancias_bajo_minimo"}),
    ("N5", _comp("az-service-bus", "Premium", razon="aislamiento"), [_p(1, "premium-mu", 3)], {"instancias_no_admitidas"}),
    ("N4", _comp("az-foundry-agent-service"), [_p(1, "hosted-vcpu", cita=CONS, base=2000, unidad="consultas"),
                                              _p(2, "hosted-memoria", cita=CONS, base=2000, unidad="consultas")],
     {"nivel_sin_justificar"})]   # integrador I1.8 (N4): con nivel en el catálogo, se justifica como todo cómputo


@pytest.mark.parametrize("pendiente, comp, precios, reglas", ESTADO_ACTUAL,
                         ids=[f"{x[0]}_{i}" for i, x in enumerate(ESTADO_ACTUAL)])
def test_estado_actual_de_lo_pendiente(pendiente, comp, precios, reglas):
    assert _valorar(comp, precios)[0] == reglas, pendiente


HOSPEDADO = "Hospedado 1 vCPU y 2 GiB"


def test_n4_agente_hospedado_valorable_con_su_nivel_justificado():
    """Integrador I1.8 (N4, P18-4, E18-2): nivel «Hospedado» en el catálogo; como todo cómputo que no es el por
    defecto, valorable solo con justificacion_nivel (falla cerrado sin ella)."""
    reglas, cant = _valorar(_comp("az-foundry-agent-service", HOSPEDADO, razon="codigo_propio"), [
        _p(1, "hosted-vcpu", cita=CONS, base=2000, unidad="consultas"),
        _p(2, "hosted-memoria", cita=CONS, base=2000, unidad="consultas")])
    assert reglas == set() and cant == {"P-01": 600, "P-02": 1200}


@pytest.mark.parametrize("comp, precios, esperadas", [
    (_comp("az-foundry-agent-service"), [], set()),
    (_comp("az-foundry-agent-service"), [_p(1, "memoria-corto-plazo", cita=CONS, base=2000, unidad="consultas")], set()),
    (_comp("az-foundry-agent-service", HOSPEDADO, razon="codigo_propio"), [_p(1, "hosted-vcpu", cita=CONS, base=2000, unidad="consultas")],
     {"falta_medidor_obligatorio"})],
    ids=["sin_precios", "solo_memoria_no_es_computo", "hospedado_solo_vcpu"])
def test_n4_lo_que_no_usa_el_nivel_no_lo_justifica(comp, precios, esperadas):
    assert _valorar(comp, precios)[0] == esperadas


# I1.8 (integrador): lo correcto de N7, N1 y N5 pasa (sin esto, una regla que rechazase todo daría verde arriba).
@pytest.mark.parametrize("comp, precios, cant", [
    (_comp("az-postgresql", "B1ms", razon="no_productivo"), [_p(1, "b1ms", 1), _p(2, "almacenamiento", 1)], {"P-01": 730, "P-02": 32}),
    (_comp("az-foundry", sku="gpt-6-luna"), [_p(1, "gpt-6-luna-entrada", cita=CONS, base=2000, unidad="consultas"),
                                             _p(2, "gpt-6-luna-salida", cita=CONS, base=2000, unidad="consultas")],
     {"P-01": 11.312, "P-02": 2.342}),
    (_comp("az-cosmos-db", "Aprovisionado", razon="varias_regiones"), [_p(1, "aprovisionado-100ru", 4), _p(2, "almacenamiento", cita=CONS,
                                                                                    base=2000, unidad="consultas")],
     {"P-01": 2920, "P-02": 0.002}),
    (_comp("az-service-bus", "Premium", razon="aislamiento"), [_p(1, "premium-mu", 4)], {"P-01": 2920})],
    ids=["postgresql_b1ms", "foundry_entrada_y_salida", "cosmos_en_el_minimo", "sb_premium_cuatro"])
def test_lo_correcto_de_n7_n1_y_n5_pasa(comp, precios, cant):
    assert _valorar(comp, precios) == (set(), cant)
