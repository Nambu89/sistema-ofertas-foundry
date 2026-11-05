"""I1.6 · papel P: réplicas de la decisión 4 en verificar_paquete.py (volumen, nivel, concepto, precios que cubren y
auxiliar atado), iguales al núcleo (LES-G-097). Las integra el integrador desde docs/I1/CAMBIOS-I16-P.md: hasta
entonces, XFAIL estricto (PENDIENTE_I16); integradas, son pruebas normales. Sin red."""
from __future__ import annotations

import copy
import random
import types

import pytest

from tests import i16_p_datos as D
from tests.test_i16_p_volumen import CAT, _b_corregida, _c, _p, _real
from tests import i17_int  # noqa: E402  (integrador I1.7)
from tests.test_i16_p_auxiliar_documentos import AUX, LEGADO, _aux
from nucleo import anexo_consumo as A, experto  # noqa: E402
import verificar_paquete as vp  # noqa: E402
from tests import i19_p_datos as D19  # noqa: E402  (I1.9: contrato v5 y réplicas de I1.9)

PENDIENTE_I16 = pytest.mark.xfail(not hasattr(vp, "errores_volumen_nivel_replica"), strict=True,
                                  reason="réplicas de I1.6 pendientes de integrar (docs/I1/CAMBIOS-I16-P.md)")
pytestmark = [pytest.mark.skipif(not all(p.exists() for p in D.PAQUETES_REALES.values()) or not D.MEDICION.exists(),
                                 reason="faltan los paquetes reales de I1.5 o la medición de E"), PENDIENTE_I16]
CITAS = ["Aproximadamente 2.000 consultas al mes.", "entre 50 y 100 técnicos.", "60 técnicos.", "Unos 60 técnicos",
         " Aproximadamente  3.000 documentos. "]
# I1.9 (contrato v5): {nivel, razon, cita}; razones de prueba de i16_p_datos (documentos_sobre_basic e indices_sobre_basic)
JNS = [None, {"nivel": "s1", "razon": "documentos_sobre_basic", "cita": "Aproximadamente 3.000 documentos."},
       {"nivel": "basic", "razon": "documentos_sobre_basic", "cita": "Microsoft Teams."},
       {"nivel": "S9", "razon": "x", "cita": "x"},
       {"nivel": "s1", "razon": "indices_sobre_basic", "cita": "60 técnicos."},
       {"nivel": "s1", "razon": "documentos_sobre_basic", "cita": "60 técnicos."},
       {"nivel": "s1", "razon": "otra", "cita": "Aproximadamente 3.000 documentos."},
       {"nivel": "s1", "razon": "documentos_sobre_basic", "cita": "«Aproximadamente 3.000 documentos.»"},
       "nivel premium"]
PENDIENTE_I19 = pytest.mark.xfail(not hasattr(vp, "existentes_r"), strict=True,
                                  reason="réplicas de I1.9 pendientes de integrar (docs/I1/CAMBIOS-I19-P.md §7)")


def _variantes(n: int = 400):
    """La respuesta real de B corregida, con mutaciones al azar de cada regla (semilla fija) y requisitos variados."""
    rnd = random.Random(1611)
    est, base, brief, _ = _b_corregida()
    req = est["carga"]["requisitos"]
    asumido = copy.deepcopy(req)
    asumido["campos"]["volumetria"]["estado"] = "ASUMIDO"
    for _ in range(n):
        r = copy.deepcopy(base)
        if rnd.random() < 0.3:
            _aux(r, rnd.choice(["C-03", "C-02", "C-04"]), rnd.choice([AUX, LEGADO]))
        for c in r["componentes"]:
            if rnd.random() < 0.25:
                c["motivo_no_valoracion"] = rnd.choice(["no_aplica", "depende_del_volumen", "sin_medidor_publico"])
            if rnd.random() < 0.3:
                c["justificacion_nivel"] = copy.deepcopy(rnd.choice(JNS))
        for p in r["precios"]:
            x = rnd.random()
            if x < 0.15:
                p["cantidad_mensual"] = None
            elif x < 0.3:
                p["base_volumen"] = None
            elif x < 0.45 and p["base_volumen"]:
                p["base_volumen"]["cita"] = rnd.choice(CITAS)
                p["base_volumen"]["cantidad_base"] = rnd.choice([2000, 50, 60, 3000, 7])
            elif x < 0.55:
                p["cantidad_mensual"] = rnd.choice([1, 2, 6, 6.02, 730, 1e9])
            elif x < 0.6:
                p["base_volumen"] = copy.deepcopy(base["precios"][-1]["base_volumen"])
            elif x < 0.63:
                p["base_volumen"] = rnd.choice(["mucho", {"cita": CITAS[0], "cantidad_base": 2000, "unidad_base": "x",
                                                          "factor": "z"}])  # objetos forjados como texto
        yield r, brief["texto"], rnd.choice([req, asumido, None, {"campos": {"volumetria": "x"}}, {"campos": []}])


def test_replicas_iguales_al_nucleo_en_400_casos():
    vistas = set()
    for r, texto, req in _variantes():
        nucleo = [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(r, texto, req, CAT)]
        assert D19.R19.errores_volumen_nivel_replica(r, texto, req, CAT) == nucleo  # I1.9: la réplica nueva
        assert vp.precios_que_cubren_replica(r, CAT) == A.precios_que_cubren(r, CAT)
        assert vp.errores_cobertura_replica(r, CAT) == [(x["componente_id"], x["regla"]) for x in A.errores_cobertura(r, CAT)]
        fijada, _, _ = experto.fijar_conceptos(r, CAT)
        assert [(pid, f) for pid, _, f in vp.conceptos_replica(r, CAT)] == [
            (p["id"], p["concepto"]) for p in fijada["precios"] if experto.plantilla_de_precio(
                p, _c(r, p["componente_id"]), CAT) is not None]
        for c in r["componentes"]:
            assert vp.incoherencias_servicio(c, CAT, r["precios"]) == experto.incoherencias_servicio(c, CAT, r["precios"])
        vistas |= {regla for _, regla in nucleo}
    faltan = {"volumen_sin_base", "cita_no_literal", "cantidad_no_en_cita", "cuenta_no_cuadra", "referencia_sin_depende",
              "referencia_con_base", "base_en_tiempo", "depende_con_volumetria_citada", "depende_sin_precio_unitario",
              "nivel_sin_justificar", "nivel_desconocido", "razon_desconocida", "razon_no_cumplida",
              "requisito_no_literal", "nivel_sin_catalogo", "nivel_distinto_del_precio"} - vistas
    assert not faltan, faltan  # nada de verdes vacíos (LES-G-099.5)


def _ctx(est: dict, resp: dict) -> types.SimpleNamespace:
    carga = copy.deepcopy(est["carga"])
    carga["respuestas_expertos"]["azure"]["respuesta"] = resp
    return types.SimpleNamespace(respuesta=resp, carga=carga, catalogo_obj=CAT, estado={"carga": carga})


def _guardada(est, resp, brief):
    """Integrador I1.7: lo que habría guardado el núcleo con el contrato v4 (la respuesta real convertida y completada)."""
    return i17_int.completar(D19.v4_a_v5(i17_int.a_v4(resp, CAT), CAT), CAT, est["carga"]["requisitos"],
                             brief["texto"])


def test_la_puerta_da_ok_con_b_corregida_y_falla_con_los_casos_reales(monkeypatch):
    D19.pegar_replicas_i19(monkeypatch)  # I1.9: la puerta con las réplicas de CAMBIOS-I19-P pegadas
    est, resp, brief, _ = _b_corregida()
    c = vp.Comprobacion("experto", "x")
    vp._decision_4(_ctx(est, _guardada(est, resp, brief)), c)
    assert c.estado == "OK", c.detalles
    # I1.7: el caso real A (volumen_sin_base) ya no se puede expresar en v4: la cantidad la calcula el núcleo
    e, r, b, _ = _real("B")
    c = vp.Comprobacion("experto", "x")
    vp._decision_4(_ctx(e, _guardada(e, r, b)), c)
    assert c.estado == "FALLA" and "depende_con_volumetria_citada" in "\n".join(c.detalles), c.detalles


def test_la_puerta_falla_con_un_concepto_que_no_es_el_de_la_plantilla_o_un_ajuste_falso():
    est, resp, brief, _ = _b_corregida()
    resp = _guardada(est, resp, brief)  # integrador I1.7: el concepto guardado lo puso el núcleo; aquí se altera
    _p(resp, "P-02")["concepto"] = "B1 | texto"
    c = vp.Comprobacion("experto", "x")
    vp._decision_4(_ctx(est, resp), c)
    assert c.estado == "FALLA" and "VER15-3" in "\n".join(c.detalles)
    resp = experto.fijar_conceptos(resp, CAT)[0]
    ctx = _ctx(est, resp)
    ctx.carga["respuestas_expertos"]["azure"]["ajustes_nucleo"] = {"conceptos": [
        {"precio_id": "P-02", "plantilla": "b1-linux", "recibido": "B1", "fijado": "otro"}]}
    c = vp.Comprobacion("experto", "x")
    vp._decision_4(ctx, c)
    assert c.estado == "FALLA" and "ajustes_nucleo" in "\n".join(c.detalles)


def test_la_puerta_valida_el_paquete_v2_con_su_esquema_y_falla_por_su_epoca():
    resp = D.paquete_real("B")["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    assert vp.es_contrato_experto_v2(resp) and vp.nombre_esquema_experto(resp) == "historico/respuesta_experto_v2"
    assert vp.validar_esquema(resp, "historico/respuesta_experto_v2") == []
    assert vp.nombre_esquema_experto(D.a_v3(resp)) == "historico/respuesta_experto_v3"  # I1.7: v3 es histórico
    c = vp.Comprobacion("experto", "x")
    vp._cobertura_precios(types.SimpleNamespace(respuesta=resp, catalogo_obj=CAT, estado={}, carga={}), c)
    assert c.estado == "FALLA" and "anterior a I1.6" in "\n".join(c.detalles)
