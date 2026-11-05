"""I1.9, papel E: el catálogo v8 declara en TODAS las filas con niveles su valor por defecto con fuente, razones cerradas
para subir, disponibilidad por nivel y región, y lo que pedían VC18-4, VC18-5, VC18-7, VC18-9 y PR18-5."""
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
COMPUTO = set(CAT["computo_por_defecto"]["filas"])
# Decisión por fila (pruebas/I19/CATALOGO.md §2): el mínimo viable en producción con SLA, con su fuente de Learn
DEFECTOS = {"az-ai-search": "Basic", "az-cosmos-db": "Sin servidor", "az-sql-database": "Basic",
            "az-postgresql": "D2ds_v5", "az-app-service": "B1", "az-container-apps": "Dedicado D4", "az-functions": "EP1",
            "az-api-management": "Consumption", "az-logic-apps": "Consumo", "az-service-bus": "Basic",
            "az-container-registry": "Standard", "az-bot-service": "Estándar", "az-defender-cloud": "P1",
            "az-foundry-agent-service": "Hospedado 1 vCPU y 2 GiB"}


def _nivel(fila: str, nombre: str) -> dict:
    return next(n for n in FILAS[fila]["niveles"] if n["nivel"] == nombre)


def test_v8_sin_problemas_de_forma_en_ninguna_tanda():
    assert CAT["version"] == 8 and CAT["fecha"] == "2026-10-08"  # «fecha» no cambia sin rehacer todas las filas
    assert pp.problemas_i19(CAT) == [] and pp.problemas_i18(CAT) == [] and derivar.problemas_catalogo(CAT) == []


def test_cada_fila_con_niveles_tiene_su_valor_por_defecto_con_fuente():
    assert {c["id"] for c in CAT["componentes"] if c.get("niveles")} == set(DEFECTOS)
    for fid, nivel in DEFECTOS.items():
        nd = FILAS[fid]["nivel_por_defecto"]
        assert nd["nivel"] == nivel and nd["fuente"].startswith("https://learn.microsoft.com/azure/"), fid
        assert len(nd["motivo"]) >= 20 and nd["consultado"] == "2026-10-15", fid


@pytest.mark.parametrize("fid", sorted(DEFECTOS))
def test_cada_nivel_que_no_es_el_por_defecto_trae_razones_cerradas(fid):
    libre = CAT["computo_por_defecto"]["nivel"] if fid == "az-app-service" else None if fid in COMPUTO else DEFECTOS[fid]
    for n in FILAS[fid]["niveles"]:
        if n["nivel"] != libre or (n.get("instancias_max") or 1) > 1:  # Revisión E1: también las instancias de más
            assert n.get("razones_subida"), (fid, n["nivel"])
        for r in n.get("razones_subida") or []:
            assert r["tipo"] in ("umbral", "caracteristica") and r["fuente"].startswith("https://learn.microsoft.com/")
            assert (r["tipo"] == "umbral") == ("limite" in r) == ("unidad" in r) == ("palabras_clave" not in r)


def test_bajar_de_nivel_es_solo_para_lo_no_productivo():
    """PostgreSQL Burstable y Container Registry Basic no son para producción según Learn: se eligen con esa razón."""
    for fid, nivel in (("az-postgresql", "B1ms"), ("az-container-registry", "Basic"), ("az-api-management", "Developer")):
        ids = {r["id"] for r in _nivel(fid, nivel)["razones_subida"]}
        assert ids == {"no_productivo"}, (fid, ids)


def test_api_management_limites_con_sus_notas_de_learn():
    """VC18-4: «con integración con Microsoft Entra» era el inicio de sesión del portal para desarrolladores (nota 1)."""
    limites = [x for n in FILAS["az-api-management"]["niveles"] for x in n["limites"]]
    assert not any(x in limites for x in ("con integración con Microsoft Entra", "sin integración con Microsoft Entra"))
    assert any("nota 1 de Learn" in x and "portal para desarrolladores" in x for x in limites)
    assert any("nota 2 de Learn" in x for x in _nivel("az-api-management", "Consumption")["limites"])
    assert "nota 1 de Learn" in " ".join(_nivel("az-ai-search", "Basic")["limites"])  # VC18-13


def test_disponibilidad_por_nivel_y_region():
    """VC18-3 y VC18-11: Standard v2 y Basic v2 sí están en swedencentral (el aviso de Learn es de Premium v2)."""
    apim = FILAS["az-api-management"]["disponibilidad"]
    assert all("swedencentral" in apim[n]["regiones"] and apim[n]["alcance"] == "nivel" for n in ("Basic v2", "Standard v2"))
    assert "Premium v2" in apim["Standard v2"]["nota"]
    modelos = FILAS["az-foundry"]["disponibilidad"]
    assert set(modelos) == {"gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol"}
    assert "swedencentral" in modelos["gpt-6-luna"]["regiones"] and "northeurope" not in modelos["gpt-6-luna"]["regiones"]
    assert FILAS["az-ai-search"]["disponibilidad"]["Basic"]["regiones"] == ["francecentral", "italynorth"]


def test_modelo_por_defecto_sin_razones_y_los_demas_solo_si_se_nombran():
    """VC18-5: gpt-6-luna por defecto; gpt-6-sol y gpt-6.1-sol solo con la razón «modelo_nombrado»."""
    pls = FILAS["az-foundry"]["plantillas_precio"]
    assert all("razones_subida" not in p for p in pls if p.get("modelo") == "gpt-6-luna")
    for m in ("gpt-6-sol", "gpt-6.1-sol"):
        rs = [p["razones_subida"] for p in pls if p.get("modelo") == m]
        assert rs and all(x == rs[0] for x in rs) and [r["id"] for r in rs[0]] == ["modelo_nombrado"]
        assert m in rs[0][0]["palabras_clave"]


def test_data_factory_exige_el_movimiento_y_el_ranking_es_opcional():
    """VC18-7."""
    reglas = FILAS["az-data-factory"]["reglas_medidores"]
    assert {"si_usa": ["orquestacion"], "exige": ["movimiento-datos"]}.items() <= reglas[-1].items()
    rs = next(p for p in FILAS["az-ai-search"]["plantillas_precio"] if p["id"] == "ranking-semantico")["opcional"]
    assert rs["por_defecto"] == "sin" and "free plan (default)" in rs["motivo"]


def test_factores_por_accion_como_alternativos():
    """PR18-5: base «acción»; el bloque los enseña desde que el núcleo elige el factor por la base (E19-2, P 16-10)."""
    fs = pp.factores(CAT)
    for k in ("asistente_rag.tokens_entrada_por_accion", "asistente_rag.tokens_salida_por_accion",
              "integracion.llamadas_api_por_accion"):
        assert fs[k]["base"] == ["acción"] and fs[k]["tipo"] == "supuesto"
    alt = {p["id"]: p["factores_alternativos"] for c in CAT["componentes"] for p in c.get("plantillas_precio") or []
           if p.get("factores_alternativos")}
    assert alt["consumo-llamadas"] == ["integracion.llamadas_api_por_accion"]
    assert alt["gpt-6-luna-entrada"] == ["asistente_rag.tokens_entrada_por_accion"]
    assert pp.FACTORES_ALTERNATIVOS_EN_BLOQUE is True
    assert "[o f=asistente_rag.tokens_entrada_por_accion]" in pp.bloque_v4(CAT, True)


def test_bot_y_defender_con_niveles_y_valor_por_defecto():
    """VC18-9: canales estándar y Defender P1 por defecto; Defender for Storage sigue fuera de los niveles (N4)."""
    assert [n["nivel"] for n in FILAS["az-bot-service"]["niveles"]] == ["Estándar", "Premium"]
    assert [n["nivel"] for n in FILAS["az-defender-cloud"]["niveles"]] == ["P1", "P2"]
    sueltas = {p["id"] for p in FILAS["az-defender-cloud"]["plantillas_precio"]} - {
        x for n in FILAS["az-defender-cloud"]["niveles"] for x in n["plantillas"]}
    assert sueltas == {"almacenamiento-malware"}


def test_el_derivado_lleva_lo_nuevo_y_valida():
    assert ce.validar(DERIVADO, ESQ, ESQ) == []
    for fid in DEFECTOS:
        assert SANDBOX[fid]["nivel_por_defecto"] == FILAS[fid]["nivel_por_defecto"]
        assert SANDBOX[fid]["disponibilidad"] == FILAS[fid]["disponibilidad"]
        assert [n.get("razones_subida") for n in SANDBOX[fid]["niveles"]] == [
            n.get("razones_subida") for n in FILAS[fid]["niveles"]]
    sol = next(p for p in SANDBOX["az-foundry"]["plantillas_precio"] if p["id"] == "gpt-6-sol-entrada")
    assert sol["razones_subida"][0]["id"] == "modelo_nombrado"
    assert derivar.SANDBOX.read_bytes() == derivar.DERIVADO.read_bytes()
