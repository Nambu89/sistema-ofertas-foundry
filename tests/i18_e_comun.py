"""I1.8, papel E: lo que el esquema del sandbox gana en esta tanda, para comparar con los esquemas de tandas anteriores.

`sin_i18_e(esquema)` deshace exactamente las adiciones de una nota de trabajo no publicada (medidores
obligatorios, topes y valores de instancias por nivel; reglas de medidores y nivel por defecto por fila; motivo sin factor
por plantilla; filas de cómputo; tope de 40 factores). Falla con KeyError si falta alguna: el esquema cambió sin avisar.
"""
from __future__ import annotations

import copy

CAMPOS_NIVEL = ("medidores_obligatorios", "instancias_max", "instancias_min", "instancias_validas")
CAMPOS_COMPONENTE = ("reglas_medidores", "nivel_por_defecto")
CAMPOS_PLANTILLA = ("sin_factor_motivo",)
FACTORES_MAX_ANTES = 30


def sin_i18_e(esquema: dict) -> dict:
    e = copy.deepcopy(esquema)
    comp = e["properties"]["componentes"]["items"]["properties"]
    for k in CAMPOS_NIVEL:
        comp["niveles"]["items"]["properties"].pop(k)
    for k in CAMPOS_COMPONENTE:
        comp.pop(k)
    for k in CAMPOS_PLANTILLA:
        comp["plantillas_precio"]["items"]["properties"].pop(k)
    e["properties"]["computo_por_defecto"]["properties"].pop("filas")
    e["properties"]["factores_estandar"]["maxItems"] = FACTORES_MAX_ANTES
    return e
