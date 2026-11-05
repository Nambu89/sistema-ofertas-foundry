"""I1.6 · R: la puerta local con la decisión 3 completa (REVERIF15-1: todas las tareas de la procedencia; VER15-4:
método, HTTP y estado de la relectura como lista blanca), la marca de orquestador exigida a toda respuesta v2 o
posterior (REV15-2 / R15-3) y los nombres de quienes firman decisiones fuera del brief (VER15-7).

Base: el paquete real de B de I1.3 (respuesta v1) con los ayudantes de tests/test_i14_puerta_procedencia.py y, para
REV15-2, el paquete real de B de I1.5 (respuesta v2). Cada caso adverso lleva su resultado esperado (LES-G-096.6).
"""
from __future__ import annotations

import copy
import pathlib

import pytest

import verificar_paquete as vp
from tests.test_i14_puerta_procedencia import REAL, contexto, juzgar

pytestmark = pytest.mark.skipif(not REAL.is_file(), reason="falta el paquete real de B de I1.3")
RAIZ = pathlib.Path(__file__).resolve().parents[1]
REAL_B15 = RAIZ / "pruebas" / "I15" / "ARREGLOS" / "REAL" / "B" / "sesion_2" / "OF-BREZALIA-001-A-Paquete.zip"


def _con(c: vp.Comprobacion, texto: str) -> bool:
    return any(texto in d for d in c.detalles)


def _tarea_no_usada(**relectura):
    """Añade una tarea de una ronda anterior (objetivo R0, que el núcleo no usó) con la relectura indicada."""
    def mutar(doc):
        t = copy.deepcopy(doc["tareas"][0])
        t.update(task_id="resp_rondaanterior", objetivo_id="BRF-ANTERIOR-R0", context_id="ctxt_anterior")
        t["relectura"].update(relectura)
        doc["tareas"].append(t)
    return mutar


# ── VER15-4: juicio_relectura como lista blanca ──
BUENA = {"metodo": "GetTask", "http": 200, "estado_tarea": "TASK_STATE_COMPLETED", "sha256_recibido": "a" * 64,
         "coincide": True, "error": None}


@pytest.mark.parametrize("cambio, esperado, motivo", [
    ({}, vp.OK, "HTTP 200"),
    ({"metodo": "ListTasks"}, vp.NOV, "ListTasks"),
    ({"metodo": "gettask"}, vp.NOV, "gettask"),                       # sin normalizar: exactamente GetTask
    ({"metodo": None}, vp.NOV, "None"),
    ({"http": 500}, vp.NOV, "HTTP 500"),
    ({"http": "200"}, vp.NOV, "HTTP '200'"),                          # texto, no el entero 200
    ({"http": 200.0}, vp.NOV, "HTTP 200.0"),
    ({"http": True}, vp.NOV, "HTTP True"),
    ({"http": None}, vp.NOV, "HTTP None"),
    ({"estado_tarea": "TASK_STATE_WORKING"}, vp.NOV, "TASK_STATE_WORKING"),
    ({"estado_tarea": None}, vp.NOV, "no TASK_STATE_COMPLETED"),
    ({"error": "aviso"}, vp.NOV, "error anotado"),
    ({"metodo": "ListTasks", "http": 500}, vp.NOV, "ListTasks"),      # los dos motivos en un solo NO VERIFICADO
    ({"coincide": False}, vp.FALLA, "devolvió otro texto"),
    ({"coincide": False, "metodo": "ListTasks", "http": 500}, vp.FALLA, "devolvió otro texto"),   # gana lo más severo
    ({"sha256_recibido": "b" * 64}, vp.FALLA, "dice coincidir"),
    ({"sha256_recibido": "b" * 64, "http": 500}, vp.FALLA, "dice coincidir"),
    ({"coincide": None}, vp.NOV, "decisión 3"),
    ({"coincide": "true"}, vp.NOV, "decisión 3"),
    ({"coincide": 1}, vp.NOV, "decisión 3"),
])
def test_ver15_4_juicio_relectura(cambio, esperado, motivo):
    t = {"task_id": "resp_x0001", "sha256_recibido": "a" * 64, "relectura": {**BUENA, **cambio}}
    veredicto, detalle = vp.juicio_relectura(t)
    assert veredicto == esperado and motivo in detalle, (veredicto, detalle)


def test_ver15_4_relectura_sin_forma_es_falla():
    assert vp.juicio_relectura({"task_id": "resp_x0001", "relectura": None})[0] == vp.FALLA


@pytest.mark.parametrize("cambio, motivo", [
    ({"metodo": "ListTasks", "http": 500}, "ListTasks"),
    ({"estado_tarea": "TASK_STATE_FAILED"}, "TASK_STATE_FAILED"),
    ({"error": "TaskNotFound"}, "error anotado"),
])
def test_ver15_4_en_la_tarea_usada_deja_no_verificado(tmp_path, cambio, motivo):
    c, kql = juzgar(tmp_path, lambda d: d["tareas"][0]["relectura"].update(cambio))
    assert c.estado == vp.NOV and _con(c, motivo) and _con(c, "decisión 3"), c.detalles
    assert len(kql.consultas) == 1                                    # lo demás se sigue contrastando


# ── REVERIF15-1: la relectura se juzga en todas las tareas de la procedencia ──
def test_reverif15_1_tarea_no_usada_correcta_no_cambia_el_verde(tmp_path):
    c, kql = juzgar(tmp_path, _tarea_no_usada())
    assert c.estado == vp.OK and _con(c, "su relectura local sí (decisión 3): 1 de 1 correctas"), c.detalles
    assert len(kql.consultas) == 1 and "resp_rondaanterior" not in kql.consultas[0]   # no se contrasta con trazas


@pytest.mark.parametrize("relectura, esperado, motivo", [
    ({"coincide": False, "sha256_recibido": "0" * 64}, vp.FALLA, "devolvió otro texto"),
    ({"coincide": True, "sha256_recibido": "f" * 64}, vp.FALLA, "dice coincidir"),
    ({"coincide": None, "http": 404, "sha256_recibido": None, "error": "TaskNotFound"}, vp.NOV, "decisión 3"),
    ({"metodo": "ListTasks"}, vp.NOV, "ListTasks"),
    ({"http": 500}, vp.NOV, "HTTP 500"),
    ({"estado_tarea": "TASK_STATE_WORKING"}, vp.NOV, "TASK_STATE_WORKING"),
])
def test_reverif15_1_tarea_no_usada_con_relectura_mala(tmp_path, relectura, esperado, motivo):
    c, kql = juzgar(tmp_path, _tarea_no_usada(**relectura))
    assert c.estado == esperado and _con(c, "tarea no usada por el núcleo") and _con(c, motivo), c.detalles
    assert _con(c, "0 de 1 correctas"), c.detalles
    assert (len(kql.consultas) == 0) is (esperado == vp.FALLA)        # con FALLA no se consulta nada más


def test_reverif15_1_tambien_sin_red(tmp_path):
    from tests.test_i14_puerta_procedencia import paquete_b, trazas, doc_de
    z = paquete_b(tmp_path, _tarea_no_usada(coincide=False, sha256_recibido="0" * 64))
    ctx = contexto(z, tmp_path, trazas(doc_de(z)))
    ctx.sin_red = True
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.FALLA and _con(c, "tarea no usada por el núcleo"), c.detalles


# ── REV15-2 / R15-3: con respuesta v2 o posterior, la marca es obligatoria; la vía heredada, solo para v1 ──
def test_rev15_2_respuesta_v1_sin_marca_sigue_la_via_heredada(tmp_path):
    c, _ = juzgar(tmp_path)                                           # el paquete de I1.3 trae la respuesta v1
    assert c.estado == vp.OK and _con(c, "respuesta del experto v1"), c.detalles


@pytest.mark.skipif(not REAL_B15.is_file(), reason="falta el paquete real de B de I1.5")
@pytest.mark.parametrize("quitar, esperado", [
    ((), "nota"),                                   # control: con las dos marcas, la vía es B
    (("estado", "manifiesto"), vp.FALLA),
    (("estado",), vp.FALLA),                        # marca solo en uno: incoherente (como antes)
    (("manifiesto",), vp.FALLA),
])
def test_rev15_2_respuesta_v2_exige_la_marca(tmp_path, quitar, esperado):
    ctx = contexto(REAL_B15, tmp_path, lambda q: [])
    assert not vp.es_contrato_experto_v1(ctx.respuesta)
    for donde in quitar:
        (ctx.estado if donde == "estado" else ctx.manifiesto).pop("orquestador")
    c = vp.Comprobacion("procedencia_a2a", "prueba")
    marca = vp.orquestador_declarado(ctx, c, con_fichero=True)
    if esperado == "nota":
        assert marca == "B" and c.estado == vp.OK, c.detalles
    else:
        assert marca is None and c.estado == vp.FALLA, c.detalles
        assert _con(c, "REV15-2" if len(quitar) == 2 else "incoherente"), c.detalles


@pytest.mark.skipif(not REAL_B15.is_file(), reason="falta el paquete real de B de I1.5")
def test_rev15_2_c_procedencia_completa_sin_marca_falla_sin_consultar(tmp_path):
    consultas = []
    ctx = contexto(REAL_B15, tmp_path, lambda q: consultas.append(q) or [])
    ctx.estado.pop("orquestador"), ctx.manifiesto.pop("orquestador")
    for sin_red in (False, True):
        ctx.sin_red = sin_red
        c = vp.c_procedencia(ctx)
        assert c.estado == vp.FALLA and _con(c, "REV15-2") and not consultas, c.detalles


@pytest.mark.parametrize("respuesta", [None, {}, {"componentes": []}, {"componentes": [{"id": "C-01",
                                                                                       "motivo_no_valoracion": "no_aplica"}]}])
def test_rev15_2_sin_marca_y_sin_respuesta_v1_falla_cerrado(respuesta):
    import types
    ctx = types.SimpleNamespace(estado={}, manifiesto={}, respuesta=respuesta)
    c = vp.Comprobacion("procedencia_a2a", "prueba")
    assert vp.orquestador_declarado(ctx, c, con_fichero=False) is None and c.estado == vp.FALLA, c.detalles
