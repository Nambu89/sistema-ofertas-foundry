"""I1.8, papel E: el catálogo v7 aplica REVERIF17-2 y -3 y LES-G-100.7 y .8 a TODAS las filas, no solo a las del caso."""
from __future__ import annotations

import json

import pytest

from catalogo import derivar
from catalogo import plantillas_precio as pp
from esquemas import comprobar_esquemas as ce

CAT = derivar.cargar()
FILAS = {c["id"]: c for c in CAT["componentes"]}
DERIVADO = json.loads(derivar.DERIVADO.read_text(encoding="utf-8"))
SANDBOX = {c["id"]: c for c in DERIVADO["componentes"]}
ESQ = json.loads(derivar.ESQUEMA_SANDBOX.read_text(encoding="utf-8"))


def _nivel(fila: str, nombre: str) -> dict:
    return next(n for n in FILAS[fila]["niveles"] if n["nivel"] == nombre)


def test_el_catalogo_v7_no_tiene_problemas_de_forma():
    assert CAT["version"] == 8  # I1.9: v8, con lo de I1.8 intacto
    assert pp.problemas_i18(CAT) == []
    assert derivar.problemas_catalogo(CAT) == []


def test_cada_plantilla_de_volumen_trae_factor_o_motivo_y_el_factor_existe():
    fs = pp.factores(CAT)
    for c in CAT["componentes"]:
        for p in c.get("plantillas_precio") or []:
            if p["impulsor"] != "volumen":
                assert "factor_estandar" not in p and "sin_factor_motivo" not in p, (c["id"], p["id"])
                continue
            assert bool(p.get("factor_estandar")) != bool(p.get("sin_factor_motivo")), (c["id"], p["id"])
            if p.get("factor_estandar"):
                assert p["factor_estandar"] in fs, (c["id"], p["id"])


def test_sin_factor_solo_en_las_plantillas_que_dependen_de_un_requisito():
    sin = {(c["id"], p["id"]) for c in CAT["componentes"] for p in c.get("plantillas_precio") or []
           if p.get("sin_factor_motivo")}
    fuera_foundry = {k for k in sin if k[0] != "az-foundry"}
    assert fuera_foundry == {("az-purview", "gobierno-basico")}
    for _, pid in sin - fuera_foundry:
        p = next(x for x in FILAS["az-foundry"]["plantillas_precio"] if x["id"] == pid)
        assert "cache" in pid or p.get("contexto") == "largo" or p["modelo"] in pp.modelos_fuera_siempre(CAT)


@pytest.mark.parametrize("fila,esperados", [
    ("az-storage", ["hot-lrs-datos"]), ("az-functions", ["premium-vcpu", "premium-memoria"]),
    ("az-container-apps", ["dedicado-vcpu", "dedicado-memoria", "dedicado-gestion"]),
    ("az-cosmos-db", ["almacenamiento"]),
    ("az-postgresql", ["almacenamiento"]), ("az-log-analytics", ["ingesta"]), ("az-private-link", ["punto-conexion"]),
    ("az-data-factory", ["orquestacion"])])
def test_medidores_obligatorios_de_fila(fila, esperados):
    assert FILAS[fila]["medidores_obligatorios"] == esperados


@pytest.mark.parametrize("fila,nivel,esperados", [
    ("az-functions", "EP1", ["premium-vcpu", "premium-memoria"]),
    ("az-container-apps", "Dedicado D4", ["dedicado-vcpu", "dedicado-memoria", "dedicado-gestion"]),
    ("az-logic-apps", "Standard WS1", ["standard-vcpu", "standard-memoria"]),
    ("az-service-bus", "Standard", ["standard-base", "standard-operaciones"]),
    ("az-cosmos-db", "Sin servidor", ["sin-servidor-ru", "almacenamiento"]),
    ("az-cosmos-db", "Aprovisionado", ["aprovisionado-100ru", "almacenamiento"]),
    ("az-sql-database", "GP_Gen5_2", ["gp-2vcore", "gp-almacenamiento"]),
    ("az-postgresql", "B1ms", ["b1ms", "almacenamiento"]), ("az-postgresql", "D2ds_v5", ["d2ds-v5", "almacenamiento"]),
    ("az-foundry-agent-service", "Hospedado 1 vCPU y 2 GiB", ["hosted-vcpu", "hosted-memoria"])])
def test_medidores_obligatorios_de_nivel(fila, nivel, esperados):
    assert _nivel(fila, nivel)["medidores_obligatorios"] == esperados


def test_agentes_hospedados_obligatorios_en_su_nivel_y_no_en_la_fila():
    """Integrador I1.8 (P18-4, E18-2): la memoria de corto plazo sola no exige los medidores del agente hospedado."""
    assert "medidores_obligatorios" not in FILAS["az-foundry-agent-service"]


@pytest.mark.parametrize("fila,nivel,tope,literal", [
    ("az-app-service", "B1", 3, "Basic: 3 instancias dedicadas como máximo"),
    ("az-app-service", "P0v3", 30, "Premium v3: 30 instancias dedicadas como máximo"),
    ("az-app-service", "P1v3", 30, "Premium v3: 30 instancias dedicadas como máximo"),
    ("az-functions", "EP1", 20, "Premium: hasta 20 instancias siempre preparadas por aplicación"),
    ("az-ai-search", "Basic", 9, "3 particiones y 3 réplicas como máximo (9 unidades de búsqueda; nota 1 de Learn)"),
    ("az-ai-search", "S1", 36, "36 unidades de búsqueda como máximo"),
    ("az-api-management", "Developer", 1, "Developer: 1 unidad de escala como máximo"),
    ("az-api-management", "Basic v2", 10, "Basic v2: 10 unidades de escala como máximo"),
    ("az-api-management", "Standard v2", 10, "Standard v2: 10 unidades de escala como máximo"),
    ("az-service-bus", "Premium", 16, "Premium: 1, 2, 4, 8 o 16 unidades de mensajería por espacio de nombres")])
def test_tope_de_instancias_con_su_limite_literal(fila, nivel, tope, literal):
    n = _nivel(fila, nivel)
    assert n["instancias_max"] == tope and literal in n["limites"]


def test_las_filas_de_computo_tienen_niveles_para_todo_su_tiempo():
    assert CAT["computo_por_defecto"]["filas"] == ["az-app-service", "az-functions", "az-container-apps",
                                                   "az-logic-apps", "az-foundry-agent-service"]
    for cid in CAT["computo_por_defecto"]["filas"]:
        c = FILAS[cid]
        tiempo = {p["id"] for p in c["plantillas_precio"] if p["impulsor"] == "tiempo"}
        en_niveles = set().union(*(set(n["plantillas"]) for n in c.get("niveles") or []))
        assert tiempo <= en_niveles, cid
    assert "peticiones" not in {p["id"] for p in FILAS["az-container-apps"]["plantillas_precio"]}
    hosted = {p["id"]: p for p in FILAS["az-foundry-agent-service"]["plantillas_precio"]}
    assert hosted["hosted-vcpu"]["impulsor"] == hosted["hosted-memoria"]["impulsor"] == "volumen"


def test_unidades_por_instancia_de_la_clase():
    pi = {(c["id"], p["id"]): p["por_instancia"]["valor"] for c in CAT["componentes"]
          for p in c.get("plantillas_precio") or [] if p.get("por_instancia")}
    assert pi == {("az-functions", "premium-vcpu"): 1, ("az-functions", "premium-memoria"): 3.5,
                  ("az-container-apps", "dedicado-vcpu"): 4, ("az-container-apps", "dedicado-memoria"): 16,
                  ("az-logic-apps", "standard-vcpu"): 1, ("az-logic-apps", "standard-memoria"): 3.5,
                  ("az-sql-database", "gp-almacenamiento"): 41.6, ("az-postgresql", "almacenamiento"): 32}


def test_el_derivado_lleva_lo_nuevo_y_valida_con_el_esquema_del_sandbox():
    assert ce.validar(DERIVADO, ESQ, ESQ) == []
    assert DERIVADO["computo_por_defecto"]["filas"] == CAT["computo_por_defecto"]["filas"]
    assert SANDBOX["az-foundry"]["reglas_medidores"] == FILAS["az-foundry"]["reglas_medidores"]
    b1 = next(n for n in SANDBOX["az-app-service"]["niveles"] if n["nivel"] == "B1")
    assert b1["instancias_max"] == 3
    sb = next(n for n in SANDBOX["az-service-bus"]["niveles"] if n["nivel"] == "Premium")
    assert sb["instancias_validas"] == [1, 2, 4, 8, 16]
    sin = [p for p in SANDBOX["az-purview"]["plantillas_precio"] if p["id"] == "gobierno-basico"]
    assert sin and sin[0]["sin_factor_motivo"]
    assert len(DERIVADO["factores_estandar"]) == len(pp.factores(CAT)) == 32  # I1.9: tres factores por acción
