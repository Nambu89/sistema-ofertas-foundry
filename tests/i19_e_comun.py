"""I1.9, papel E: lo común a las pruebas del catálogo v8.

- `sin_i19_e(esquema)` deshace exactamente las adiciones de una nota de trabajo no publicada al esquema del
  sandbox (razones de subida por nivel y por plantilla, plantilla opcional, factores alternativos, nivel por defecto con
  fuente y disponibilidad). Falla con KeyError si falta alguna: el esquema cambió sin avisar.
- Requisitos y brief de prueba con una cita que cumple cada razón usada (`CITA[razon]`) y la justificación con la forma
  del contrato común (`jn(nivel, razon)`: {nivel, razon, cita}).
"""
from __future__ import annotations

import copy

CAMPOS_NIVEL = ("razones_subida",)
CAMPOS_PLANTILLA = ("razones_subida", "opcional", "factores_alternativos")
DEFECTO_I18 = {"type": "string", "minLength": 2, "maxLength": 40,
               "description": "I1.8: nivel que no necesita justificación fuera de la clase cómputo (lo lee "
                              "experto.nivel_por_defecto)."}


def sin_i19_e(esquema: dict) -> dict:
    e = copy.deepcopy(esquema)
    comp = e["properties"]["componentes"]["items"]["properties"]
    for k in CAMPOS_NIVEL:
        comp["niveles"]["items"]["properties"].pop(k)
    for k in CAMPOS_PLANTILLA:
        comp["plantillas_precio"]["items"]["properties"].pop(k)
    comp.pop("disponibilidad")
    comp["nivel_por_defecto"] = copy.deepcopy(DEFECTO_I18)
    return e


CONS, DOCS = "Aproximadamente 2.000 consultas al mes.", "Unos 3.000 documentos."
SESIONES = "Unas 1.200 sesiones simultáneas en hora punta."
GB = "Unos 60 GB de documentos."
ALCANCE = {
    "microservicios": "Microservicios con Dapr que escalan con KEDA.",
    "temas_y_sesiones": "Avisos por temas y suscripciones entre aplicaciones.",
    "aislamiento": "Mensajería con aislamiento de recursos.",
    "codigo_propio": "Un agente hospedado con LangGraph.",
    "varias_regiones": "Datos replicados en varias regiones.",
    "no_productivo": "Base de datos para una prueba de concepto.",
    "modelo_nombrado": "El cliente pide usar GPT-6 Sol.",
    "portal_desarrolladores": "Un portal para desarrolladores para los equipos internos.",
    "alta_disponibilidad": "Alta disponibilidad durante el horario laboral.",
}
RED = "Todo privado, con punto de conexión privado en cada servicio."
CITA = {**ALCANCE, "privado_red": RED, "sesiones": SESIONES, "almacenamiento": GB}


def _entrada(x: str) -> dict:
    return {"valor": x, "cita": "Cita literal de la fuente: " + x, "fuente": "F1", "origen": "CITADO"}


REQ = {"schema": "preventa-requisitos/1", "campos": {
    "volumetria": {"estado": "CITADO", "entradas": [_entrada(x) for x in (CONS, DOCS, SESIONES, GB)]},
    "alcance_funcional": {"estado": "CITADO", "entradas": [_entrada(x) for x in ALCANCE.values()]},
    "red_privada": {"estado": "CITADO", "entradas": [_entrada(RED)]}}}
BRIEF = ("BRIEF-PREVENTA/1\n## Necesidad\n- Volumetría: " + "; ".join((CONS, DOCS, SESIONES, GB)) + "\n"
         + "## Alcance funcional\n" + "".join(f"- {x}\n" for x in ALCANCE.values()) + "- Red privada: " + RED + "\n")


def jn(nivel: str, razon: str, cita: str | None = None) -> dict:
    return {"nivel": nivel, "razon": razon, "cita": CITA[razon] if cita is None else cita}
