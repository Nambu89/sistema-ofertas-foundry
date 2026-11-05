"""I1.6, papel E: catálogo ampliado (P15-1), impulsor y divisor y niveles (decisión 4, LES-G-100), precio auxiliar
ligado a componentes (INT15-3) y concepto derivable en el catálogo del sandbox (PR15-3). Sin red."""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from catalogo import derivar
from catalogo import plantillas_precio as pp
from esquemas import comprobar_esquemas as ce

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CAT = derivar.cargar()
POR_ID = {c["id"]: c for c in CAT["componentes"]}
PARES = [(c, p) for c in CAT["componentes"] for p in c.get("plantillas_precio") or []]
FUENTES = {f["url"]: f for f in CAT["fuentes_comprobadas"]}
ESQ_HOY = json.loads((RAIZ / "esquemas" / "catalogo_componentes.json").read_text(encoding="utf-8"))
PROPUESTO = json.loads((RAIZ / "docs" / "I1" / "CAMBIOS-I16-E" / "catalogo_componentes.propuesto.json")
                       .read_text(encoding="utf-8"))
NUEVOS_AZURE = {"az-sql-database", "az-postgresql", "az-service-bus", "az-event-grid", "az-container-registry",
                "az-data-factory"}
NUEVOS_SAAS = {"az-sharepoint", "az-microsoft-365"}
CON_NIVELES = {"az-container-apps", "az-logic-apps", "az-ai-search", "az-app-service", "az-sql-database", "az-postgresql", "az-cosmos-db", "az-service-bus",
               "az-api-management", "az-container-registry", "az-functions",  # az-functions: EP1 (arreglos I1.7)
               "az-foundry-agent-service",  # integrador I1.8 (P18-4): nivel «Hospedado 1 vCPU y 2 GiB»
               "az-bot-service", "az-defender-cloud"}  # I1.9 (VC18-9): canales estándar o premium y planes P1 o P2


def test_los_servicios_nuevos_entran_en_el_derivado_de_hoy():
    der = {c["id"]: c for c in derivar.catalogo_componentes(CAT)["componentes"]}
    assert NUEVOS_AZURE | NUEVOS_SAAS <= set(der)
    for i in NUEVOS_AZURE:
        assert der[i]["plantillas_precio"] and der[i]["region_ue"] == "swedencentral", i
        assert not POR_ID[i].get("regiones_no_admitidas"), "sin veto sin fuente"
    for i in NUEVOS_SAAS:
        assert der[i]["service_name_precios"] is None and der[i]["residencia"] == "geografia_tenant", i


def test_la_lista_del_catalogo_solo_amplia_lo_declarado():
    assert set(derivar.PREFIJOS_CATALOGO_AMPLIACION) <= set(derivar.PREFIJOS_REFERENCIA_AMPLIACION)
    assert derivar.en_lista_blanca("https://learn.microsoft.com/azure/azure-sql/database/sql-database-paas-overview")
    assert derivar.en_lista_blanca("https://learn.microsoft.com/es-es/microsoft-365/enterprise/microsoft-365-overview")
    for fuera in ("azure/frontdoor/front-door-overview", "fabric/fundamentals/microsoft-fabric-overview",
                  "power-bi/fundamentals/power-bi-overview", "azure/azure-sqlx/algo"):
        assert not derivar.en_lista_blanca("https://learn.microsoft.com/" + fuera), fuera


@pytest.mark.parametrize("c, p", PARES, ids=[f"{c['id']}/{p['id']}" for c, p in PARES])
def test_impulsor_y_divisor_casan_con_la_unidad_medida(c, p):
    assert pp.problemas_impulsor(p) == [] and pp.problemas_plantilla(p, c) == []
    unidad = p["comprobacion"]["unidad"]
    assert p["divisor"] == pp.divisor_de_unidad(unidad)
    if p["impulsor"] == "tiempo":  # horas, días o meses de un recurso desplegado
        # I1.8 (N7): «1 GB/Month» es el almacenamiento aprovisionado de SQL Database y PostgreSQL (1 mes por instancia)
        assert unidad in {"1 Hour", "1/Hour", "1/Day", "1/Month", "1 GiB Hour", "1 GB/Month"}, (unidad, p["id"])
    assert "descripcion" in p and "concepto" not in p, "el concepto lo deriva el código (PR15-3)"


@pytest.mark.parametrize("unidad, divisor", [("1M", 1000000), ("1K", 1000), ("10K", 10000), ("100K", 100000),
                                             ("50K", 50000), ("1 Hour", 1), ("1/Day", 1), ("1 GB/Month", 1), ("1", 1),
                                             ("100 Hours", None), ("2 GB", None), ("", None), (None, None)])
def test_divisor_de_unidad(unidad, divisor):
    assert pp.divisor_de_unidad(unidad) == divisor


@pytest.mark.parametrize("cambio, motivo", [({"impulsor": "uso"}, "impulsor"), ({"divisor": 0}, "entero"),
                                            ({"divisor": True}, "entero"), ({"divisor": 1000}, "distinto"),
                                            ({"impulsor": "tiempo", "divisor": 1000000}, "tiempo lleva divisor 1")])
def test_problemas_impulsor_falla_en_alto(cambio, motivo):
    p = {"impulsor": "volumen", "divisor": 1000000, "comprobacion": {"unidad": "1M"}} | cambio
    assert any(motivo in m for m in pp.problemas_impulsor(p)), pp.problemas_impulsor(p)


def test_niveles_validos_con_fuente_comprobada():
    assert {c["id"] for c in CAT["componentes"] if c.get("niveles")} == CON_NIVELES
    for i in CON_NIVELES:
        assert pp.problemas_niveles(POR_ID[i]) == [], i
        for n in POR_ID[i]["niveles"]:
            f = FUENTES[n["fuente_url"]]
            assert f["http"] == 200 and f["titulo"] and f["consultado"] == n["consultado"], (i, n["nivel"])
            assert derivar.normalizar_url(n["fuente_url"]) == n["fuente_url"]


def _por_dia(p: dict) -> float:
    k = p["comprobacion"]
    return k["precios_eur"][0] * {"1 Hour": 24, "1/Hour": 24, "1/Day": 1}[k["unidad"]]


@pytest.mark.parametrize("cid", sorted(CON_NIVELES))
def test_niveles_de_menor_a_mayor_cuando_el_precio_es_comparable(cid):
    c = POR_ID[cid]
    plantilla = {p["id"]: p for p in c["plantillas_precio"]}
    primeras = [plantilla[n["plantillas"][0]] for n in c["niveles"]]
    if all(p["impulsor"] == "tiempo" for p in primeras):
        costes = [_por_dia(p) for p in primeras]
        assert costes == sorted(costes), (cid, costes)


@pytest.mark.parametrize("cambio, motivo", [
    (lambda c: c["niveles"].append(copy.deepcopy(c["niveles"][0])), "repetido"),
    (lambda c: c["niveles"][0].update(plantillas=["no-existe"]), "ajenas"),
    (lambda c: c["niveles"][0].update(limites=[]), "límites"),
    (lambda c: c["niveles"][0].update(fuente_url="https://example.com/x"), "fuente")])
def test_problemas_niveles_falla_en_alto(cambio, motivo):
    c = copy.deepcopy(POR_ID["az-ai-search"])
    cambio(c)
    assert any(motivo in m for m in pp.problemas_niveles(c)), pp.problemas_niveles(c)
