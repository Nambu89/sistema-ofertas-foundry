"""Pruebas sin red de I1.2 F2: alias por componente y disponibilidad por región UE del catálogo."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

from catalogo import derivar
from esquemas import comprobar_esquemas as ce
from tests.i17_e_comun import ARGS_EFECTIVO, DERIVADO_EFECTIVO, ESQ_EFECTIVO  # noqa: E402  (I1.7)

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "sandbox"))
sys.path.insert(0, str(RAIZ))
from nucleo import experto  # noqa: E402  (regla real del veto, de F1)
import verificar_paquete as V  # noqa: E402
CAT = derivar.cargar()
COMPS = CAT["componentes"]
ESQ_SANDBOX = json.loads((RAIZ / "esquemas" / "catalogo_componentes.json").read_text(encoding="utf-8"))
UE = {"swedencentral", "francecentral", "westeurope", "northeurope", "germanywestcentral", "spaincentral",
      "italynorth"}
FUENTES = {f["url"]: f for f in CAT["fuentes_comprobadas"]}
DERIVADOS = [c for c in COMPS if c["referencia_url"] and derivar.en_lista_blanca(c["referencia_url"])]
VETADOS = {c["id"] for c in COMPS if c.get("regiones_no_admitidas")}
SANDBOX = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
# Servicios sin región ni precio propios (sin serviceName); se documenta en CAMBIOS-I12-F2.md.
SIN_REGION = {"az-teams", "az-cost-management", "az-policy"}
# Propuesta para esquemas/catalogo_componentes.json (CAMBIOS-I12-F2.md §2), copia literal.
ALIAS_SANDBOX = {"type": "array", "maxItems": 12, "uniqueItems": True,
                 "items": {"type": "string", "minLength": 2, "maxLength": 80}}


def _urls_usadas(c: dict) -> list[str]:
    return ([a["fuente_url"] for a in c["alias"]] + ([c["region_fuente_url"]] if c.get("region_fuente_url") else [])
            + ([c["residencia_fuente_url"]] if c.get("residencia_fuente_url") else [])  # CMP-1 (I1.3)
            + [v["fuente_url"] for k in ("regiones_no_admitidas", "regiones_con_restricciones")
               for v in c.get(k) or []])


def test_cada_fuente_usada_esta_comprobada_hoy_con_200_y_titulo():
    for c in COMPS:
        for u in _urls_usadas(c):
            f = FUENTES.get(u)
            assert f, f"{c['id']}: {u} no está en fuentes_comprobadas"
            assert f["http"] == 200 and f["titulo"] and "404" not in f["titulo"], (c["id"], f)
            assert f["consultado"] >= CAT["fecha"], (c["id"], u)  # I1.3 añade fuentes consultadas el 2026-10-09


# CMP-1 (I1.3): el veto de residencia del bot «global» (usuarios en la UE) se consultó en Learn el 2026-10-09.
VETO_CMP1 = ("az-bot-service", "regiones_no_admitidas", "global", "2026-10-09")


def test_vetos_y_restricciones_fechados_el_dia_de_la_consulta():
    for c in COMPS:
        for k in ("regiones_no_admitidas", "regiones_con_restricciones"):
            for v in c.get(k) or []:
                if (c["id"], k, v["region"], v["consultado"]) == VETO_CMP1:
                    continue
                # I1.7: una restricción revisada después lleva la fecha de su revisión, con la fuente consultada ese día
                revisada = {f["consultado"] for f in CAT["fuentes_comprobadas"] if f["url"] == v["fuente_url"]}
                assert v["consultado"] in {CAT["fecha"]} | revisada and v["region"] in UE, (c["id"], v)


def test_veto_cmp1_del_bot_global_con_fuente_y_region_ue_regional():
    bot = next(c for c in COMPS if c["id"] == "az-bot-service")
    veto = [v for v in bot["regiones_no_admitidas"] if v["region"] == "global"]
    assert len(veto) == 1 and veto[0]["fuente_url"].startswith("https://learn.microsoft.com/azure/bot-service/")
    assert bot["region_ue"] == "westeurope" and bot["region_precio"] == "Global"
    assert {c["id"] for c in COMPS if c.get("residencia") == "geografia_tenant"} == {
        "az-teams", "az-entra-id", "az-sharepoint", "az-microsoft-365"}  # I1.6: SaaS de Microsoft 365 (P15-1)


def test_alias_unicos_y_distintos_de_cualquier_nombre_oficial():
    """En la forma compacta del núcleo (F1): un alias no puede ser de dos servicios ni un nombre oficial ajeno."""
    oficiales = {experto._compacto(c["nombre_oficial"]): c["id"] for c in COMPS}
    vistos: dict[str, str] = {}
    for c in COMPS:
        for a in c["alias"]:
            n = experto._compacto(a["nombre"])
            assert len(n) >= 5 or c["id"] not in VETADOS, f"{c['id']}: alias corto {a['nombre']!r} no vetaría"
            assert n not in oficiales, f"{c['id']}: el alias {a['nombre']!r} es el nombre oficial de {oficiales[n]}"
            assert n not in vistos, f"{a['nombre']!r} repetido en {vistos.get(n)} y {c['id']}"
            vistos[n] = c["id"]


def test_ningun_alias_de_un_servicio_vetado_esta_dentro_del_nombre_de_otro():
    """Los alias y nombres de F2 no provocan falsos vetos por sí solos (sin service_name_precios, ver F2-4)."""
    for v in COMPS:
        if v["id"] not in VETADOS:
            continue
        propios = {experto._compacto(n) for n in [v["nombre_oficial"]] + [a["nombre"] for a in v["alias"]]}
        for o in COMPS:
            if o["id"] == v["id"]:
                continue
            for n in [o["nombre_oficial"]] + [a["nombre"] for a in o["alias"]]:
                assert not any(p in experto._compacto(n) for p in propios), (v["id"], o["id"], n)

def test_region_ue_en_todos_los_derivados_salvo_los_declarados():
    for c in DERIVADOS:
        if c["id"] in SIN_REGION:
            assert "region_ue" not in c, c["id"]
            continue
        assert c.get("region_ue") in UE | {"global"} and c.get("region_fuente_url"), c["id"]
        assert c["region_ue"] not in {v["region"] for v in c.get("regiones_no_admitidas") or []}, c["id"]


def test_la_region_ue_tiene_precios_publicados():
    """El experto busca el precio con armRegionName = region_ue: debe existir (consulta del día)."""
    for c in DERIVADOS:
        r = c.get("region_ue")
        if r and r != "global" and c["service_name_precios"] and not c.get("region_precio"):  # con region_precio, el precio va en ella
            assert (c["precios_items_ue"][r] or 0) > 0, (c["id"], r)


def test_ai_search_conserva_los_cuatro_vetos_de_verif_3():
    s = next(c for c in COMPS if c["id"] == "az-ai-search")
    assert s["region_ue"] == "francecentral"
    assert {v["region"] for v in s["regiones_no_admitidas"]} == {"swedencentral", "westeurope", "northeurope",
                                                                 "germanywestcentral"}


def _con_alias() -> dict:
    """El derivado tal como quedará cuando el integrador admita `alias` en el esquema del sandbox."""
    return derivar.catalogo_componentes(CAT, derivar.campos_opcionales_sandbox() | {"alias"})


@pytest.mark.parametrize("servicio,region", [
    ("Azure Cognitive Search", "swedencentral"), ("Azure AI Search (S1)", "westeurope"), ("Azure Search", "northeurope"),
    ("AI Search", "germanywestcentral"), ("Azure AI Content Understanding", "francecentral"),
    ("Azure AI Speech", "spaincentral"), ("Azure AI Agent Service", "northeurope"), ("Content Safety", "northeurope")])
def test_veto_de_f1_reconoce_los_alias_con_catalogo_id_null(servicio, region):
    comp = {"servicio": servicio, "catalogo_id": None, "region": region}
    assert experto.region_no_admitida(comp, _con_alias())
    assert V.region_no_admitida(comp, _con_alias()) == experto.region_no_admitida(comp, _con_alias())


@pytest.mark.parametrize("cual", ["sandbox_en_disco", "con_alias"])
def test_ningun_servicio_propio_vetado_por_el_nombre_de_otro(cual):
    cat = SANDBOX if cual == "sandbox_en_disco" else _con_alias()
    falsos = []
    for c in cat["componentes"]:
        propias = {v["region"] for v in c.get("regiones_no_admitidas") or []}
        for r in sorted(UE - propias):
            motivo = experto.region_no_admitida({"servicio": c["nombre_oficial"], "catalogo_id": c["id"], "region": r},
                                                cat)
            if motivo:
                falsos.append(f"{c['id']} en {r}: {motivo[:60]}")
    assert falsos == []

def test_derivado_sin_alias_mientras_el_esquema_del_sandbox_no_lo_admita():
    deriv = derivar.catalogo_componentes(CAT, esquema=ESQ_EFECTIVO)
    assert ("alias" in derivar.campos_opcionales_sandbox()) == any("alias" in c for c in deriv["componentes"])
    assert ce.validar(deriv, ESQ_EFECTIVO, ESQ_EFECTIVO) == []


def test_derivado_con_alias_valida_contra_el_esquema_propuesto():
    esq = copy.deepcopy(ESQ_EFECTIVO)
    esq["properties"]["componentes"]["items"]["properties"]["alias"] = ALIAS_SANDBOX
    assert ce.palabras_no_admitidas(esq) == []
    deriv = derivar.catalogo_componentes(CAT, derivar.campos_opcionales_sandbox() | {"alias"}, esquema=esq)
    assert ce.validar(deriv, esq, esq) == []
    s = next(c for c in deriv["componentes"] if c["id"] == "az-ai-search")
    # VER-1 (I1.2): más los nombres de Learn en castellano (es-es), comprobados el 2026-10-08.
    assert s["alias"] == ["Azure Cognitive Search", "Azure Search", "AI Search", "Búsqueda de Azure AI",
                          "Búsqueda cognitiva de Azure"]
    sin_alias = {"az-monitor", "az-policy", "az-microsoft-365"}  # I1.6: Learn no publica otro nombre de Microsoft 365
    assert all(c["alias"] for c in deriv["componentes"] if c["id"] not in sin_alias)


def test_tabla_de_instrucciones_lleva_los_alias():
    tabla = derivar.tabla_markdown(CAT)
    fila = next(l for l in tabla.splitlines() if l.startswith("| az-ai-search |"))
    assert "Azure Cognitive Search; Azure Search; AI Search" in fila and "francecentral" in fila
