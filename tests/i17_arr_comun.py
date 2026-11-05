"""Arreglos I1.7: lo que los arreglos añadieron al esquema del catálogo del sandbox sobre el que propuso E en I1.7
(docs/I1/CAMBIOS-I17-E/catalogo_componentes.propuesto.json). No es un fichero de pruebas.

`sin_arreglos(esquema)` quita exactamente esas adiciones; la prueba de integración exige que el resultado sea el propuesto
por E, así el único cambio del esquema vigente es el documentado en pruebas/I17/ARREGLOS.md (PR17-1, PR17-3, PR17-4 y
PR17-5)."""
from __future__ import annotations

import copy

CAMPOS_COMPONENTE = ("referencia_titulo", "medidores_obligatorios")   # PR17-1 y PR17-3
CAMPOS_PLANTILLA = ("por_instancia",)                                # PR17-5
CAMPOS_RAIZ = ("computo_por_defecto",)                               # PR17-4
NIVELES_MIN_ANTES = 2                                                # PR17-4: EP1 es el único nivel Premium


def sin_arreglos(esquema: dict) -> dict:
    e = copy.deepcopy(esquema)
    comp = e["properties"]["componentes"]["items"]["properties"]
    for k in CAMPOS_COMPONENTE:
        comp.pop(k)
    for k in CAMPOS_PLANTILLA:
        comp["plantillas_precio"]["items"]["properties"].pop(k)
    comp["niveles"]["minItems"] = NIVELES_MIN_ANTES
    for k in CAMPOS_RAIZ:
        e["properties"].pop(k)
    return e
