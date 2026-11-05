"""I1.6 · integrador: la decisión 4 con el catálogo REAL derivado por E (niveles en 8 servicios, auxiliar con su lista de
24) y las líneas nuevas que recibe el verificador (CAMBIOS-I16-E §3.3). Las pruebas de P usan niveles de prueba fijos
(tests/i16_p_datos.catalogo_i16); aquí, los del catálogo vigente y los paquetes reales de I1.5 (LES-G-078). Sin red."""
from __future__ import annotations

import copy
import json
import sys

import pytest

from tests import i16_p_datos as D

for _p_ in (D.RAIZ / "sandbox", D.RAIZ):
    if str(_p_) not in sys.path:
        sys.path.insert(0, str(_p_))
from nucleo import experto, verificacion  # noqa: E402
import verificar_paquete as vp  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)

pytestmark = pytest.mark.skipif(not all(p.exists() for p in D.PAQUETES_REALES.values()),
                                reason="faltan los paquetes reales de I1.5")
CAT = json.loads((D.RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
FILAS = {e["id"]: e for e in CAT["componentes"]}


def _p(r, i):
    return next(x for x in r["precios"] if x["id"] == i)


def _c(r, i):
    return next(x for x in r["componentes"] if x["id"] == i)


def _nivel(cid, plantilla):
    return next(n for n in FILAS[cid]["niveles"] if plantilla in n["plantillas"])


def _real(x):
    est = D.paquete_real(x)
    resp = D.a_v3(est["carga"]["respuestas_expertos"]["azure"]["respuesta"])
    brief = D.brief_de(est, resp["brief_id"])
    return est, resp, brief, brief["perfiles_permitidos"]


def _filtro(fila, plantilla):
    return next(p["filtro"] for p in FILAS[fila]["plantillas_precio"] if p["id"] == plantilla)


def _b_corregida():
    """La respuesta real de B como debería haber llegado con el catálogo vigente: Foundry valorado con la volumetría
    citada, Bot Service con su base, y AI Search y App Service con el nivel justificado con los límites reales.
    Integrador I1.9 (contrato v5, VC18-1 y VC18-5): con 3.000 documentos, AI Search va en su nivel por defecto (Basic)
    y App Service en el cómputo por defecto (B1), los dos sin justificar; Foundry con el modelo por defecto
    (gpt-6-luna). La subida a S1 con su razón la prueban _con_s1 y las pruebas de abajo."""
    est, resp, brief, perfiles = _real("B")
    base = lambda f, u, j: {"cita": "Aproximadamente 2.000 consultas al mes.", "cantidad_base": 2000,  # noqa: E731
                            "unidad_base": "consultas al mes", "factor": {"valor": f, "unidad": u, "justificacion": j}}
    _p(resp, "P-03")["base_volumen"] = base(1, "mensajes por consulta", "Cada consulta es un mensaje del canal de Teams.")
    _c(resp, "C-05")["motivo_no_valoracion"] = "no_aplica"
    pls = {p["id"]: p for p in FILAS["az-foundry"]["plantillas_precio"]}
    for pid, pl, precio, cant, f, j in (("P-04", "gpt-6-luna-entrada", 1.21, 6, 3000, "Pregunta, contexto e instrucciones."),
                                        ("P-05", "gpt-6-luna-salida", 9.6797, 1, 500, "Respuesta breve con citas.")):
        resp["precios"].append({"id": pid, "componente_id": "C-05", "filtro": pls[pl]["filtro"], "precio": precio,
                                "moneda": "EUR", "unidad": "1M", "region": "swedencentral",
                                "effectiveStartDate": "2025-08-01T00:00:00Z", "concepto": None, "cantidad_mensual": cant,
                                "supuesto_cantidad": "Tokens del mes según las consultas citadas.",
                                "base_volumen": base(f, "tokens por consulta", j)})
    p_search = next(p for p in resp["precios"] if p["componente_id"] == "C-04")
    p_search["filtro"] = _filtro("az-ai-search", "basic")
    for cid in ("C-04", "C-03"):
        _c(resp, cid)["justificacion_nivel"] = None
    return est, resp, brief, perfiles


GB_60 = "Unos 60 GB de documentos indexados."


def _con_s1(est, resp, razon="almacenamiento", cita=GB_60):
    """I1.9: AI Search en S1 con {nivel, razon, cita}; la cita de umbral (60 GB > 45 GB de Basic) se añade a la
    volumetría de los requisitos (el valor es lo que se cita)."""
    est = copy.deepcopy(est)
    est["carga"]["requisitos"]["campos"]["volumetria"]["entradas"].append(
        {"valor": GB_60, "cita": GB_60, "fuente": "F1", "origen": "CITADO"})
    next(p for p in resp["precios"] if p["componente_id"] == "C-04")["filtro"] = _filtro("az-ai-search", "s1")
    _c(resp, "C-04")["justificacion_nivel"] = {"nivel": _nivel("az-ai-search", "s1")["nivel"], "razon": razon, "cita": cita}
    return est


def _reglas(resp, est, brief):
    return [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(resp, brief["texto"],
                                                                          est["carga"]["requisitos"], CAT)]


def test_control_b_corregida_con_el_catalogo_real_se_acepta():
    est, resp, brief, perfiles = _b_corregida()
    assert i17_int.validar(resp, brief, CAT, perfiles, requisitos=est["carga"]["requisitos"]) == []
    est = _con_s1(est, resp)  # I1.9: la subida a S1 con una razón de umbral que la cita cumple también se acepta
    assert i17_int.validar(resp, brief, CAT, perfiles, requisitos=est["carga"]["requisitos"]) == []


def test_casos_reales_de_i15_se_rechazan_con_el_catalogo_real():
    est, resp, brief, _ = _real("B")
    reglas = set(_reglas(resp, est, brief))
    assert {("C-05", "depende_con_volumetria_citada"), ("C-05", "depende_sin_precio_unitario"),
            ("P-03", "volumen_sin_base"), ("C-04", "nivel_sin_justificar")} <= reglas
    # Arreglos I1.7 (PR17-4): C-03 es App Service B1, el cómputo por defecto del catálogo: ya no justifica su nivel
    assert ("C-03", "nivel_sin_justificar") not in reglas
    est, resp, brief, _ = _real("A")
    reglas = set(_reglas(resp, est, brief))
    assert {("P-03", "volumen_sin_base"), ("P-04", "volumen_sin_base")} <= reglas, reglas


def test_nivel_de_otro_servicio_o_limite_de_otro_nivel_se_rechaza():
    """I1.9: la razón de otro nivel, una cita que no cumple el umbral o un nivel que no es el del precio se rechazan
    (en v4, el límite de otro nivel daba limite_no_oficial; en v5 el experto ya no escribe límite ni fuente)."""
    est, resp, brief, _ = _b_corregida()
    est = _con_s1(est, resp, razon="razon_inventada")  # ninguna razón de S1 se llama así
    assert ("C-04", "razon_desconocida") in _reglas(resp, est, brief)
    _c(resp, "C-04")["justificacion_nivel"].update(razon="almacenamiento", cita="Aproximadamente 3.000 documentos.")
    assert ("C-04", "razon_no_cumplida") in _reglas(resp, est, brief)
    _c(resp, "C-04")["justificacion_nivel"].update(cita=GB_60)
    assert [r for r in _reglas(resp, est, brief) if r[0] == "C-04"] == []
    _c(resp, "C-04")["justificacion_nivel"].update(nivel=_nivel("az-ai-search", "basic")["nivel"])
    assert ("C-04", "nivel_distinto_del_precio") in _reglas(resp, est, brief)


def _consolidado(resp, est):
    e = copy.deepcopy(est)
    fijada, _, errores = experto.fijar_conceptos(resp, CAT)
    assert errores == []
    e["carga"]["respuestas_expertos"]["azure"]["respuesta"] = fijada
    return verificacion.componer_consolidado(e, CAT, "CNS-OF-BREZALIA-001-A-R1"), e


def test_las_lineas_del_verificador_llevan_el_nivel_y_la_base_de_volumen():
    est, resp, _, _ = _b_corregida()
    est = _con_s1(est, resp)
    cons, _ = _consolidado(resp, est)
    lineas = {ln.split(" | ")[0]: ln for ln in cons.texto.splitlines() if ln[:2] in ("C-", "P-")}
    razon = next(r for r in _nivel("az-ai-search", "s1")["razones_subida"] if r["id"] == "almacenamiento")
    # I1.9 (E19-9, CAMBIOS-I19-P §5.6): la línea lleva la razón con su texto, la cita y la fuente de la razón
    assert (f" | nivel: S1 | razon: almacenamiento («{razon['texto']}») | cita: «{GB_60}» | "
            f"fuente_nivel: {experto.normalizar_url(razon['fuente'])} | referencia: ") in lineas["C-04"]
    # I1.7 (R): el consolidado ya no lleva precios; la base y el factor viajan en la línea P- del brief, que sale de
    # la respuesta registrada (verificacion.linea_precio_brief)
    assert not [i for i in lineas if i.startswith("P-")]
    assert verificacion.linea_precio_brief(_p(resp, "P-04")).endswith(
        " | cantidad_mensual: 6 | base: «Aproximadamente 2.000 consultas al mes.» (2000 consultas al mes) | factor: 3000 "
        "tokens por consulta («Pregunta, contexto e instrucciones.»)")
    assert " | nivel: " not in lineas["C-05"] and " | base: " not in verificacion.linea_precio_brief(_p(resp, "P-01"))
    for i, ln in lineas.items():  # el verificador sigue leyendo cada línea
        m = verificacion._CAMPOS_C.match(ln)
        assert m and " | " not in m.group("region") and m.group("ref").startswith("https://"), ln


def test_la_justificacion_y_el_requisito_pasan_por_la_anonimizacion():
    est, resp, _, _ = _b_corregida()
    _p(resp, "P-04")["base_volumen"]["factor"]["justificacion"] = "Medido con Lucía Arranz en Valladolid | 3000 tokens."
    est = _con_s1(est, resp)
    _c(resp, "C-04")["justificacion_nivel"]["cita"] = "Unos 60 GB de documentos en Palencia."  # I1.9: la cita de la razón
    cons, _ = _consolidado(resp, est)
    # I1.7 (R): la justificación del factor ya no va al consolidado sino a la línea P- del brief, anonimizada igual
    p04 = verificacion.linea_precio_brief(_p(resp, "P-04"), verificacion._anonimizador(est))
    for termino in ("Lucía", "Arranz", "Valladolid", "Palencia"):
        assert termino not in cons.texto and termino not in p04, termino
    assert p04.count(" | ") == verificacion.linea_precio_brief(_p(resp, "P-04")).count(" | ")


def test_campo_cantidad_en_el_nucleo_la_puerta_el_esquema_y_el_text_format():
    assert verificacion.CAMPOS_DISCREPA == vp.CAMPOS_DISCREPA and "cantidad" in vp.CAMPOS_DISCREPA["precio"]
    for rel in ("esquemas/respuesta_verificador.json", "agentes/esquemas/respuesta_verificador.text_format.json"):
        assert '"cantidad"' in (D.RAIZ / rel).read_text(encoding="utf-8"), rel


def test_un_sufijo_de_volumen_a_medias_no_casa_con_la_linea_de_precio():
    """Revisión I1.6 (baja): `cantidad_mensual`, `base` y `factor` van los tres o ninguno; a medias, la línea no tiene la
    forma esperada y la conservación falla en alto (REVERIF15-3) en lugar de descartar el resto en silencio."""
    est, resp, _, _ = _b_corregida()
    # I1.7 (R): el consolidado ya no lleva precios; se compone la línea P- de I1.6 para la regla, que sigue en el núcleo
    p = _p(resp, "P-04")
    p04 = (f"P-04 | {p['componente_id']} | filtro: {p['filtro']} | precio: {p['precio']} EUR | unidad: {p['unidad']} | "
           f"region: {p['region']} | effectiveStartDate: {p['effectiveStartDate']}"
           + verificacion._segmento_volumen(p, lambda x: x))
    assert verificacion.linea_precio_conservar(p04) is not None
    assert verificacion.linea_precio_conservar(p04.split(" | base: ")[0]) is None
