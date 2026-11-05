"""Integrador I1.7: ayudas para que las pruebas de I1.1 a I1.6 sigan comprobando sus reglas con el contrato v4.

Desde I1.7 `experto.validar_respuesta` exige la instantánea de precios (el núcleo pone los precios desde ella). Las reglas
antiguas que siguen aplicando a lo que escribe el modelo (cobertura, niveles, volumen citado, regiones vetadas, ids,
perfiles, flujos…) se siguen probando con sus pruebas de siempre: solo hace falta pasarles la instantánea que cubre su
catálogo. La del ejemplo (esquemas/ejemplos) cubre el catálogo de ejemplo; la del sandbox, el catálogo real.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys
from decimal import Decimal

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import experto  # noqa: E402

INST_EJEMPLO = json.loads((RAIZ / "esquemas" / "ejemplos" / "precios_instantanea.json").read_text(encoding="utf-8"))
INST_REAL = json.loads((RAIZ / "sandbox" / "datos" / "precios_instantanea.json").read_text(encoding="utf-8"))


def instantanea_para(catalogo: dict) -> dict:
    """La instantánea (del ejemplo o la real) que trae TODAS las plantillas del catálogo con su filtro; si ninguna las
    trae todas (catálogo modificado por la prueba), la que trae más. Fallar cerrado lo hace el propio núcleo."""
    opciones = [INST_EJEMPLO, INST_REAL]
    faltan = [len(experto.errores_instantanea_catalogo(i, catalogo)) for i in opciones]
    return opciones[faltan.index(min(faltan))]


def es_v3(resp: object) -> bool:
    """Respuesta escrita con el contrato de I1.6 (el modelo escribía el filtro de cada precio)."""
    return isinstance(resp, dict) and "valoracion_nucleo" not in resp and (
        "arquitectura_id" not in resp or any(isinstance(p, dict) and "filtro" in p for p in resp.get("precios") or []))


def a_v4(resp: dict, catalogo: dict) -> dict:
    """SOLO PARA PRUEBAS: lo que habría escrito el modelo con el contrato v4 a partir de una respuesta v3 (I1.6).

    - arquitectura_id: la arquitectura del catálogo cuya URL ya citaba la respuesta (si ninguna, la primera);
    - componentes: motivo_cita e incluido_en a null y referencia_id a null en los del catálogo (la pone el núcleo);
    - precios: plantilla_id = la plantilla de la fila (o del auxiliar) cuyo filtro era el del precio; instancias =
      cantidad_mensual / 730 en los de tiempo si no era 730; base_volumen sin el factor; factor_override con el factor
      de la respuesta si no es el estándar del catálogo (cita = la de la base, que es de volumetría). Lo demás (filtro,
      precio, unidad, concepto, región…) lo pone el núcleo al completar, que es justo lo que ya no escribe el modelo.
    Lo que v3 permitía y v4 no puede expresar (una cantidad de volumen sin base, un concepto distinto, un filtro mal
    escrito) desaparece en la conversión: las pruebas de esas reglas ya no aplican (imposibles por construcción)."""
    r = copy.deepcopy(resp)
    filas = {e.get("id"): e for e in catalogo.get("componentes") or []}
    arqs = [a for a in catalogo.get("arquitecturas_referencia") or [] if isinstance(a, dict)]
    citadas = {experto.normalizar_url(x.get("url")) for x in r.get("referencias") or [] if isinstance(x, dict)}
    arq = next((a for a in arqs if experto.normalizar_url(a.get("url")) in citadas), arqs[0] if arqs else None)
    r.setdefault("arquitectura_id", arq["id"] if arq else "foundry-chat-base")
    comps = {c.get("id"): c for c in r.get("componentes") or [] if isinstance(c, dict)}
    for c in comps.values():
        c.setdefault("motivo_cita", None)
        c.setdefault("incluido_en", None)
        if c.get("catalogo_id") in filas:
            c["referencia_id"] = None
    nuevos = []
    for p in r.get("precios") or []:
        if not isinstance(p, dict) or "filtro" not in p:
            nuevos.append(p)
            continue
        comp = comps.get(p.get("componente_id"))
        hit = experto.plantilla_de_precio(p, comp, catalogo)
        pid = hit["plantilla"]["id"] if hit else (p.get("plantilla_id") or "plantilla-no-identificada")
        q = {"id": p.get("id"), "componente_id": p.get("componente_id"), "plantilla_id": pid, "instancias": None,
             "base_volumen": None, "factor_override": None}
        cm, base = p.get("cantidad_mensual"), p.get("base_volumen")
        if hit and hit["plantilla"].get("impulsor") == "tiempo" and cm is not None and Decimal(str(cm)) != 730:
            q["instancias"] = float(Decimal(str(cm)) / Decimal(730))
        if isinstance(base, dict):
            q["base_volumen"] = {k: base.get(k) for k in ("cita", "cantidad_base", "unidad_base")}
            f = base.get("factor") if isinstance(base.get("factor"), dict) else {}
            info = experto.resolver_plantilla(pid, comp, catalogo)[0] if hit else None
            std = experto.factor_estandar(info, catalogo)[0] if info else None
            if f.get("valor") is not None and (std is None or Decimal(str(f["valor"])) != std["valor"]):
                q["factor_override"] = {"valor": f["valor"], "cita": base.get("cita"),
                                        "justificacion": f.get("justificacion") or "Factor de la respuesta de I1.6."}
        nuevos.append(q)
    r["precios"] = nuevos
    if isinstance(r.get("herramientas_usadas"), dict):
        r["herramientas_usadas"].pop("precios_azure", None)
    return r


def es_v4(resp: object) -> bool:
    """Integrador I1.9: respuesta con la forma v4 (motivo_cita o la justificación de I1.7 con «requisito»)."""
    comps = [c for c in (resp.get("componentes") or [] if isinstance(resp, dict) else []) if isinstance(c, dict)]
    return any("motivo_cita" in c or "existente_del_cliente" not in c
               or (isinstance(c.get("justificacion_nivel"), dict) and "requisito" in c["justificacion_nivel"])
               for c in comps)


def a_v5(resp: dict, catalogo: dict) -> dict:
    """SOLO PARA PRUEBAS (integrador I1.9, CAMBIOS-I19-P §5.10): una respuesta v4 con la forma v5
    (tests/i19_p_datos.v4_a_v5: sin motivo_cita, existente_del_cliente null y la justificación {nivel, razon, cita});
    una v5 no cambia. Las pruebas de I1.1 a I1.8 siguen comprobando sus reglas con el contrato vigente."""
    from tests.i19_p_datos import v4_a_v5  # diferido: i19_p_datos usa este módulo
    return v4_a_v5(resp, catalogo) if es_v4(resp) else resp


def validar(resp: dict, brief: dict, catalogo: dict, perfiles: list[str], requisitos: dict | None = None,
            hoy: str | None = None) -> list[str]:
    """experto.validar_respuesta con la instantánea que cubre el catálogo de la prueba; una respuesta v3 (I1.6) se
    convierte antes a lo que habría escrito el modelo con el contrato v4 (a_v4) y una v4, a la v5 (a_v5, I1.9)."""
    if es_v3(resp):
        resp = a_v4(resp, catalogo)
    resp = a_v5(resp, catalogo)
    return experto.validar_respuesta(resp, brief, catalogo, perfiles, requisitos, instantanea_para(catalogo), hoy)


def analizar(resp: dict, brief: dict, catalogo: dict, perfiles: list[str], requisitos: dict | None = None,
             hoy: str | None = None) -> tuple[list[str], dict | None]:
    """experto.analizar_respuesta con la instantánea que cubre el catálogo de la prueba: (errores, completada)."""
    return experto.analizar_respuesta(resp, brief, catalogo, perfiles, requisitos, instantanea_para(catalogo), hoy)


def completar(resp: dict, catalogo: dict, requisitos: dict | None = None, brief_texto: str | None = None) -> dict:
    """Lo que guarda el núcleo: la respuesta del modelo completada desde el catálogo y la instantánea (sin validarla).
    Las reglas que juzgan lo guardado (cobertura, conceptos, cantidades) se aplican sobre esto, no sobre lo del modelo."""
    return experto.completar(resp, catalogo, instantanea_para(catalogo), requisitos, brief_texto)[0]


def hoy_para(catalogo: dict) -> str:
    """Fecha de referencia válida para la instantánea del catálogo (la de su consulta): ni posterior ni de más de 31 días."""
    return str(instantanea_para(catalogo)["fecha_consulta"])[:10]
