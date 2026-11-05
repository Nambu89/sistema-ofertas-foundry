"""I1.9, papel E: cada rotura del catálogo v8 la ve problemas_i19 con su mensaje concreto y un único problema (y el
control sin romper da []). Si una rotura no se viera, la comprobación de clase daría verde en falso (LES-G-091)."""
from __future__ import annotations

import copy

import pytest

from catalogo import derivar
from catalogo import plantillas_precio as pp

CAT = derivar.cargar()


def _fila(cat, fid):
    return next(c for c in cat["componentes"] if c["id"] == fid)


def _nivel(cat, fid, nombre):
    return next(n for n in _fila(cat, fid)["niveles"] if n["nivel"] == nombre)


def _sin_npd(cat):
    _fila(cat, "az-sql-database").pop("nivel_por_defecto")


def _npd_ajeno(cat):
    _fila(cat, "az-service-bus")["nivel_por_defecto"]["nivel"] = "Premium v9"


def _sin_razones(cat):
    _nivel(cat, "az-api-management", "Standard v2").pop("razones_subida")


def _b1_sin_razones(cat):
    _nivel(cat, "az-app-service", "B1").pop("razones_subida")


def _computo_sin_razones(cat):
    _nivel(cat, "az-functions", "EP1").pop("razones_subida")


def _id_malo(cat):
    _nivel(cat, "az-cosmos-db", "Aprovisionado")["razones_subida"][0]["id"] = "Varias Regiones"


def _unidad_corta(cat):
    _nivel(cat, "az-sql-database", "S0")["razones_subida"][1]["unidad"] = ["GB"]


def _umbral_sin_campo(cat):
    _nivel(cat, "az-sql-database", "S1")["razones_subida"][0].pop("campo")


def _claves_vacias(cat):
    _nivel(cat, "az-service-bus", "Standard")["razones_subida"][0]["palabras_clave"] = []


def _sin_fuente(cat):
    _nivel(cat, "az-container-registry", "Premium")["razones_subida"][0]["fuente"] = "https://example.com/x"


def _disp_falta_nivel(cat):
    _fila(cat, "az-logic-apps")["disponibilidad"].pop("Consumo")


def _disp_vetada(cat):
    _fila(cat, "az-ai-search")["disponibilidad"]["S1"]["regiones"].append("swedencentral")


def _disp_sin_region_ue(cat):
    _fila(cat, "az-app-service")["disponibilidad"]["P0v3"]["regiones"].remove("swedencentral")


def _modelo_razones_distintas(cat):
    p = next(x for x in _fila(cat, "az-foundry")["plantillas_precio"] if x["id"] == "gpt-6-sol-salida")
    p["razones_subida"] = copy.deepcopy(p["razones_subida"])
    p["razones_subida"][0]["palabras_clave"] = ["gpt-6"]


def _luna_con_razones(cat):
    p = next(x for x in _fila(cat, "az-foundry")["plantillas_precio"] if x["id"] == "gpt-6-luna-entrada")
    p["razones_subida"] = copy.deepcopy(next(x for x in _fila(cat, "az-foundry")["plantillas_precio"]
                                             if x["id"] == "gpt-6-sol-entrada")["razones_subida"])
    for q in _fila(cat, "az-foundry")["plantillas_precio"]:
        if q.get("modelo") == "gpt-6-luna":
            q["razones_subida"] = p["razones_subida"]


def _opcional_sin_defecto(cat):
    p = next(x for x in _fila(cat, "az-ai-search")["plantillas_precio"] if x["id"] == "ranking-semantico")
    p["opcional"]["por_defecto"] = "a veces"


def _alternativo_desconocido(cat):
    p = next(x for x in _fila(cat, "az-api-management")["plantillas_precio"] if x["id"] == "consumo-llamadas")
    p["factores_alternativos"] = ["integracion.llamadas_por_capricho"]


ROTURAS = [
    (_sin_npd, "az-sql-database: nivel_por_defecto sin nivel"),
    (_npd_ajeno, "az-service-bus: nivel_por_defecto sin nivel"),
    (_sin_razones, "az-api-management/Standard v2: razones_subida vacías"),
    (_computo_sin_razones, "az-functions/EP1: razones_subida vacías"),
    (_b1_sin_razones, "az-app-service/B1: razones_subida vacías"),  # Revisión E1: hasta 3 instancias sin razón
    (_id_malo, "az-cosmos-db/Aprovisionado: razón sin id válido"),
    (_unidad_corta, "az-sql-database/S0/almacenamiento: cada palabra de unidad necesita una de 4 letras"),
    (_umbral_sin_campo, "az-sql-database/S1/sesiones: un umbral lleva campo"),
    (_claves_vacias, "az-service-bus/Standard/temas_y_sesiones: palabras_clave vacías"),
    (_sin_fuente, "az-container-registry/Premium/replicacion_geografica: sin fuente de Learn"),
    (_disp_falta_nivel, "az-logic-apps: disponibilidad no tiene exactamente una entrada por nivel"),
    (_disp_vetada, "az-ai-search/S1: regiones vacías, repetidas, fuera de la UE o vetadas"),
    (_disp_sin_region_ue, "az-app-service/P0v3: la «Región UE» de la fila (swedencentral) no está"),
    (_modelo_razones_distintas, "modelo gpt-6-sol: sus plantillas no llevan las mismas razones"),
    (_luna_con_razones, "modelo gpt-6-luna: el modelo por defecto no lleva razones"),
    (_opcional_sin_defecto, "az-ai-search/ranking-semantico: opcional sin valor por defecto"),
    (_alternativo_desconocido, "az-api-management/consumo-llamadas: factor alternativo"),
]


def test_control_sin_romper():
    assert pp.problemas_i19(copy.deepcopy(CAT)) == []


@pytest.mark.parametrize("romper, esperado", ROTURAS, ids=[r.__name__.strip("_") for r, _ in ROTURAS])
def test_cada_rotura_da_su_problema(romper, esperado):
    cat = copy.deepcopy(CAT)
    romper(cat)
    problemas = pp.problemas_i19(cat)
    assert len(problemas) == 1 and problemas[0].startswith(esperado), problemas
