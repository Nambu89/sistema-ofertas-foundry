"""P2 · Microsoft-Decision-1: llamada real a los tres tipos de pregunta (noul, choice y score).

Formato tomado de learn.microsoft.com/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision
(ms.date 2026-10-07, leída el 18-10-2026):
- POST <your-foundry-resource-endpoint>/providers/microsoft/v1/systemone
- Token de Entra con `--resource https://cognitiveservices.azure.com` (se fija el tenant, LES-G-052).
- Cuerpo: {"model": <nombre del DESPLIEGUE>, "state": <texto o JSON>, "questions": {<nombre>: {"type": "noul"|
  "choice"|"score", "instructions": ..., "criteria": ...}}}. En noul `criteria` es {"true", "false"} (opcional);
  en choice, {opción: descripción}; en score, la lista de niveles de menor a mayor.
- Respuesta: `answers` con los nombres de las preguntas, `model` y el uso de tokens. Learn solo muestra
  `answers.<n>.type` y `answers.<n>.choice`; el campo numérico de noul y score NO VERIFICADO: se anota cuál llega.
Todo el contenido es sintético. Se guardan entrada, salida y latencia en resultados/P2-decision-io.json.
"""
from __future__ import annotations

import math
from typing import Any

from pruebas.paso0a import comun

ID = "P2"
TITULO = "Microsoft-Decision-1: noul, choice y score"
DESPLIEGUE = "Decision-1"
FICHERO_IO = "P2-decision-io.json"
TIMEOUT_DECISION_S = 15.0

PREGUNTAS: dict[str, dict] = {
    "noul": {
        "state": "Propuesta sintética de prueba: 40 horas de gestión de proyecto y una holgura del 20 % en cada tarea.",
        "nombre": "incluye_pm_minimo",
        "pregunta": {"type": "noul",
                     "instructions": "¿La propuesta incluye al menos 8 horas de gestión de proyecto?",
                     "criteria": {"true": "Incluye 8 horas o más de gestión de proyecto",
                                  "false": "No incluye gestión de proyecto o incluye menos de 8 horas"}},
    },
    "choice": {
        "state": "Necesidad sintética: un asistente que responda preguntas sobre manuales técnicos internos y cite el párrafo de origen.",
        "nombre": "patron",
        "pregunta": {"type": "choice",
                     "instructions": "¿Qué patrón de solución encaja mejor con la necesidad?",
                     "criteria": {"rag": "Búsqueda en documentos con respuesta citada",
                                  "agente_con_herramientas": "Agente que ejecuta acciones en sistemas externos",
                                  "clasificacion": "Clasificar textos en categorías fijas"}},
    },
    "score": {
        "state": "Petición sintética: entregar en dos semanas un alcance que se estimó en seis meses.",
        "nombre": "riesgo_plazo",
        "pregunta": {"type": "score",
                     "instructions": "¿Qué riesgo de plazo tiene la petición?",
                     "criteria": ["Bajo", "Medio", "Alto", "Crítico"]},
    },
}


def cuerpo(despliegue: str, tipo: str) -> dict:
    p = PREGUNTAS[tipo]
    return {"model": despliegue, "state": p["state"], "questions": {p["nombre"]: p["pregunta"]}}


def _numero(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def validar_respuesta(tipo: str, payload: Any) -> tuple[bool, str]:
    """Comprueba la forma de la respuesta para un tipo. Devuelve (válida, detalle literal)."""
    p = PREGUNTAS[tipo]
    if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
        return False, "respuesta sin objeto answers"
    ans = payload["answers"].get(p["nombre"])
    if not isinstance(ans, dict):
        return False, f"answers sin la pregunta {p['nombre']}"
    if ans.get("type") != tipo:
        return False, f"answers.{p['nombre']}.type = {ans.get('type')!r}, se esperaba {tipo!r}"
    if tipo == "choice":
        opciones = set(p["pregunta"]["criteria"])
        if ans.get("choice") not in opciones:
            return False, f"choice {ans.get('choice')!r} fuera de las opciones {sorted(opciones)}"
        return True, f"choice={ans.get('choice')}"
    if tipo == "noul":
        campos = [(k, v) for k, v in ans.items() if k != "type" and _numero(v) and 0.0 <= float(v) <= 1.0]
        if not campos:
            return False, "noul sin ningún número entre 0 y 1"
        k, v = campos[0]
        return True, f"{k}={v} (campo NO VERIFICADO en Learn)"
    niveles = len(p["pregunta"]["criteria"])
    campos = [(k, v) for k, v in ans.items() if k != "type" and _numero(v) and 0.0 <= float(v) <= niveles - 1]
    if "score" in ans and not any(k == "score" for k, _ in campos):
        return False, f"score fuera de 0..{niveles - 1}: {ans.get('score')!r}"
    if not campos:
        return False, f"score sin ningún número entre 0 y {niveles - 1}"
    k, v = next(((k, v) for k, v in campos if k == "score"), campos[0])
    return True, f"{k}={v} (escala 0..{niveles - 1})"


def clasificar_fallo(estados_http: list[int]) -> str:
    """403 → falta un rol que asigna Fernando; cualquier otro fallo es FALLA."""
    return "PENDIENTE_FERNANDO" if 403 in estados_http else "FALLA"


def ejecutar(ctx: comun.Contexto) -> dict | comun.EnCurso:
    despliegue = DESPLIEGUE
    sku = (ctx.cfg["despliegues"].get(despliegue) or {}).get("sku")
    registros, lineas, ok_todos, estados_http = [], [], True, []
    base_elegida = None
    for tipo in ("noul", "choice", "score"):
        c = cuerpo(despliegue, tipo)
        intentos = []
        bases = [base_elegida] if base_elegida else ctx.cliente.hosts_decision()
        r = None
        for base in bases:
            if ctx.restante() < TIMEOUT_DECISION_S + 1:
                return comun.EnCurso("P2: las llamadas a Decision-1 no caben en el presupuesto; vuelve a ejecutar", 0)
            r = ctx.cliente.decision(base, c, timeout=TIMEOUT_DECISION_S)
            intentos.append({"endpoint": base, "http": r.estado, "latencia_s": r.latencia_s})
            if r.estado != 404:
                break
        estados_http.append(r.estado)
        payload = r.json()
        valido, detalle = (validar_respuesta(tipo, payload) if r.estado == 200
                           else (False, r.resumen(400)))
        if r.estado != 404:   # el primer host que no da 404 es el bueno: no se repite la búsqueda
            base_elegida = intentos[-1]["endpoint"]
        ok_todos &= valido
        registros.append({"tipo": tipo, "entrada": c, "intentos": intentos, "http": r.estado,
                          "latencia_s": r.latencia_s, "salida": payload if payload is not None else r.texto[:2000]})
        modelo = payload.get("model") if isinstance(payload, dict) else None
        lineas.append(f"- {tipo}: HTTP {r.estado} en {r.latencia_s:.3f} s · modelo={modelo} · "
                      f"{'VÁLIDA' if valido else 'NO VÁLIDA'}: {detalle}")
    ruta_io = comun.escribir_json(ctx.dir_resultados / FICHERO_IO,
                                  {"fuente": "use-foundry-models-microsoft-decision (Learn, 2026-10-07)",
                                   "despliegue": despliegue, "sku_config": sku, "llamadas": registros})
    cab = (f"Decision-1 (despliegue {despliegue}, SKU en config {sku}) por "
           f"<endpoint>/providers/microsoft/v1/systemone con token de Entra (aud {comun.AUD_COGNITIVE}, tenant fijo). "
           f"Endpoint que respondió: {base_elegida or 'ninguno'}.")
    if ok_todos:
        estado = "PASA"
    else:
        estado = clasificar_fallo(estados_http)
        if estado == "PENDIENTE_FERNANDO":
            lineas.append("403: la identidad de Fernando necesita un rol de inferencia sobre el recurso. Fernando "
                          "puede asignarse Foundry User: az role assignment create --assignee <su object id> "
                          f"--role {ctx.cfg['roles']['foundry_user']} --scope {ctx.cliente.base_arm.replace('https://management.azure.com', '')}")
    return comun.construir_resultado(ID, estado, cab + "\n" + "\n".join(lineas), ctx.comando(ID), ctx.fecha(),
                                     artefactos=[str(ruta_io.relative_to(comun.RAIZ_REPO)) if ruta_io.is_relative_to(
                                         comun.RAIZ_REPO) else str(ruta_io)])
