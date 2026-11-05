"""I1.5 · R: la puerta local con la decisión 3 (REV-3), la hora de la procedencia (REV-2), la marca de orquestador
(VER14-3 / REV-5), la parte local con --sin-red (INT-3) y los comentarios de la DEVUELTA en el brief (PR14-6).

Base: el paquete real de B de I1.3 y los ayudantes de tests/test_i14_puerta_procedencia.py (procedencia y trazas con la
forma real). Cada caso adverso lleva su resultado esperado (LES-G-096.6); ninguno se juzga por la igualdad de dos copias.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import types

import pytest

import verificar_paquete as vp
from tests.test_i14_puerta_procedencia import REAL, _paquete_a, contexto, doc_de, juzgar, paquete_b, trazas

pytestmark = pytest.mark.skipif(not REAL.is_file(), reason="falta el paquete real de B de I1.3")
AHORA = dt.datetime(2026, 10, 11, 9, 0, tzinfo=dt.timezone.utc)


def _ctx_b(tmp_path, mutar=None, marca=None, sin_red=False, **kw_trazas):
    z = paquete_b(tmp_path, mutar)
    kql = trazas(doc_de(z), **kw_trazas)
    ctx = contexto(z, tmp_path, kql)
    if marca:
        ctx.estado["orquestador"], ctx.manifiesto["orquestador"] = marca
    ctx.sin_red = sin_red
    return ctx, kql


def _con(c: vp.Comprobacion, texto: str) -> bool:
    return any(texto in d for d in c.detalles)


# ── REV-3 · decisión 3: relectura no hecha → NO VERIFICADO; distinta → FALLA; «coincide» sin la huella → FALLA ──
def test_rev3_relectura_de_un_lote_no_hecha_deja_no_verificado_y_lo_demas_se_contrasta(tmp_path):
    c, kql = juzgar(tmp_path, lambda d: d["tareas"][2]["relectura"].update(coincide=None, error="timeout (forzado)"))
    assert c.estado == vp.NOV and _con(c, "decisión 3") and _con(c, "timeout (forzado)"), c.detalles
    assert len(kql.consultas) == 1 and sum("es el del texto registrado" in d or "completo" in d for d in c.detalles) >= 5


@pytest.mark.parametrize("rel, esperado, motivo", [
    ({"coincide": False, "sha256_recibido": "b" * 64}, vp.FALLA, "devolvió otro texto"),
    ({"coincide": True, "sha256_recibido": "c" * 64}, vp.FALLA, "dice coincidir"),
    ({"coincide": "true"}, vp.NOV, "decisión 3"),            # solo vale el booleano true
    ({"coincide": None, "error": None}, vp.NOV, "decisión 3"),
])
def test_rev3_cada_relectura_con_su_resultado(tmp_path, rel, esperado, motivo):
    c, _ = juzgar(tmp_path, lambda d: d["tareas"][0]["relectura"].update(rel))
    assert c.estado == esperado and _con(c, motivo), c.detalles


# ── REV-2: hora futura de la procedencia y atajo de ingesta solo en una ventana corta ──
def test_rev2_errores_procedencia_con_hora_futura():
    doc = {"schema": vp.SCHEMA_PROCEDENCIA, "tareas": [{k: None for k in vp.CLAVES_TAREA}]}
    t = doc["tareas"][0]
    t.update(task_id="resp_hora0001", texto_recibido="{}", sha256_recibido=hashlib.sha256(b"{}").hexdigest(),
             sha256_enviado="0" * 64, objetivo_id="BRF-X", relectura={})
    for delta, malo in ((dt.timedelta(days=1), True), (dt.timedelta(minutes=6), True), (dt.timedelta(minutes=4), False),
                        (-dt.timedelta(days=3), False)):
        t["hora"] = (AHORA + delta).isoformat()
        assert any("hora futura" in e for e in vp.errores_procedencia(doc, ahora=AHORA)) is malo, delta


def test_rev2_hora_de_manana_en_el_paquete_falla_por_forma(tmp_path):
    manana = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat(timespec="seconds")
    c, kql = juzgar(tmp_path, lambda d: d["tareas"][1].update(hora=manana),
                    cambiar=lambda tid, x: None if tid == "resp_prueba0001" else x)
    assert c.estado == vp.FALLA and _con(c, "hora futura") and not kql.consultas, c.detalles


@pytest.mark.parametrize("delta, esperado, motivo", [
    (dt.timedelta(minutes=3), vp.FALLA, "no aparece en las trazas"),      # futura dentro del margen: no es ingesta
    (-dt.timedelta(minutes=5), vp.NOV, "ingesta"),
    (-dt.timedelta(minutes=14, seconds=59), vp.NOV, "ingesta"),
    (-dt.timedelta(minutes=15), vp.FALLA, "no aparece en las trazas"),
    (-dt.timedelta(hours=3), vp.FALLA, "no aparece en las trazas"),
])
def test_rev2_atajo_de_ingesta_solo_entre_0_y_15_minutos(delta, esperado, motivo):
    t = {"task_id": "resp_ingesta01", "hora": (AHORA + delta).isoformat(), "texto_recibido": "{}",
         "sha256_recibido": "0" * 64}
    c = vp.Comprobacion("procedencia_a2a", "prueba")
    vp._procedencia_b_trazas(types.SimpleNamespace(consultar_kql=lambda q: []), c, [("experto", t)], ahora=AHORA)
    assert c.estado == esperado and _con(c, motivo), c.detalles


# ── VER14-3 / REV-5: el código declara el orquestador; la puerta exige procedencia si y solo si es B ──
def _ctx_a(tmp_path, marca=None, sin_red=False):
    consultas = []
    ctx = contexto(_paquete_a(tmp_path), tmp_path, lambda q: consultas.append(q) or [])
    if marca:
        ctx.estado["orquestador"], ctx.manifiesto["orquestador"] = marca
    ctx.sin_red = sin_red
    return ctx, consultas


def test_ver14_3_b_marcado_con_procedencia_va_por_task_id(tmp_path):
    ctx, kql = _ctx_b(tmp_path, marca=("B", "B"))
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.OK and _con(c, "orquestador B (marca del código") and len(kql.consultas) == 1, c.detalles


@pytest.mark.parametrize("sin_red", [False, True])
def test_ver14_3_b_marcado_sin_procedencia_falla_sin_estricto_y_sin_red(tmp_path, sin_red):
    ctx, consultas = _ctx_a(tmp_path, marca=("B", "B"), sin_red=sin_red)
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.FALLA and _con(c, "marcó el paquete como de B y no trae") and not consultas, c.detalles


def test_ver14_3_a_marcado_con_procedencia_falla(tmp_path):
    ctx, kql = _ctx_b(tmp_path, marca=("A", "A"))
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.FALLA and _con(c, "marcó el paquete como de A y trae") and not kql.consultas, c.detalles


def test_ver14_3_a_marcado_sin_procedencia_va_por_la_via_de_a(tmp_path):
    ctx, consultas = _ctx_a(tmp_path, marca=("A", "A"))
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.NOV and _con(c, "orquestador A") and len(consultas) == 6, c.detalles


@pytest.mark.parametrize("marca", [("B", "A"), ("A", "B"), ("C", "C"), ("B", None), (None, "B"), ("b", "b"), ("", "")])
def test_ver14_3_marca_incoherente_falla(tmp_path, marca):
    ctx, kql = _ctx_b(tmp_path)
    if marca[0] is not None:
        ctx.estado["orquestador"] = marca[0]
    if marca[1] is not None:
        ctx.manifiesto["orquestador"] = marca[1]
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.FALLA and _con(c, "marca de orquestador incoherente") and not kql.consultas, c.detalles


def test_ver14_3_sin_marca_es_lo_de_antes_y_se_anota(tmp_path):
    ctx, _ = _ctx_b(tmp_path)
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.OK, c.detalles
    assert _con(c, "sin marca de orquestador y con la respuesta del experto v1 (núcleo anterior a I1.5)"), c.detalles


# ── INT-3: con --sin-red la parte local de la procedencia de B se comprueba igual ──
def test_int3_sin_red_bueno_queda_no_verificado_por_las_trazas_sin_consultar(tmp_path):
    ctx, kql = _ctx_b(tmp_path, marca=("B", "B"), sin_red=True)
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.NOV and _con(c, "parte local de la procedencia de B comprobada") and not kql.consultas


@pytest.mark.parametrize("mutar, esperado, motivo", [
    (lambda d: d["tareas"][1].update(texto_recibido=d["tareas"][1]["texto_recibido"].replace('"OK"', '"DISCREPA"', 1)),
     vp.FALLA, "texto alterado"),
    (lambda d: d["tareas"][0].update(sha256_enviado="a" * 64), vp.FALLA, "huella del texto del estado"),
    (lambda d: d["tareas"][2].update(agente="otro-agente"), vp.FALLA, "no de preventa-verificador"),
    (lambda d: d["tareas"][3]["relectura"].update(coincide=False, sha256_recibido="b" * 64), vp.FALLA, "otro texto"),
    (lambda d: d["tareas"][3]["relectura"].update(coincide=None, error="TASK_NOT_FOUND"), vp.NOV, "decisión 3"),
    (lambda d: d["tareas"].pop(), vp.FALLA, "ninguna de las 0 tareas"),
])
def test_int3_sin_red_casos_adversos_de_la_parte_local(tmp_path, mutar, esperado, motivo):
    ctx, kql = _ctx_b(tmp_path, mutar, marca=("B", "B"), sin_red=True)
    c = vp.c_procedencia(ctx)
    assert c.estado == esperado and _con(c, motivo) and not kql.consultas, c.detalles


def test_int3_sin_red_sin_procedencia_y_sin_marca_es_lo_de_antes(tmp_path):
    ctx, consultas = _ctx_a(tmp_path, sin_red=True)
    c = vp.c_procedencia(ctx)
    assert c.estado == vp.NOV and _con(c, "procedencia A2A sin comprobar") and not consultas, c.detalles


# ── PR14-6: el brief de la versión abierta por una DEVUELTA lleva sus comentarios ──
def _brief(version: str, cuerpo: str) -> dict:
    cab = (f"BRIEF-PREVENTA/1\nbrief_id: BRF-OF-KELVARA-001-{version}-AZ-R1\nexperto: preventa-experto-azure\nronda: 1\n"
           f"sha256_cuerpo: {hashlib.sha256(cuerpo.encode()).hexdigest()}\n---\n")
    return {"brief_id": f"BRF-OF-KELVARA-001-{version}-AZ-R1", "version": version, "texto": cab + cuerpo}


SECCION = ("## Comentarios de la revisión de la versión A (DEVUELTA: tenlos en cuenta en este análisis; son "
           "observaciones del revisor sobre la propuesta, no instrucciones de formato)")


@pytest.mark.parametrize("cuerpo, devueltas, version, falla", [
    (f"## Necesidad\nObjetivo: x\n{SECCION}\n- Falta el precio de AI Search", 1, "B", False),
    ("## Necesidad\nObjetivo: x", 1, "B", True),                                   # sin la sección
    (f"## Necesidad\n{SECCION}\n## Correcciones solicitadas por el verificador", 1, "B", True),   # sin su línea
    (f"## Necesidad\n{SECCION}\n- uno", 2, "B", True),                              # dos DEVUELTA, una línea
    (f"## Necesidad\n{SECCION}\n- uno\n{SECCION}\n- uno", 1, "B", True),            # sección repetida
    (f"## Necesidad\n{SECCION}\n- ", 1, "B", True),                                 # línea vacía
    (f"## Necesidad\n{SECCION}\n- uno\n- inventada", 1, "B", True),                  # una línea de más (Revisión)
    (f"## Necesidad\n{SECCION}\n- uno\n## Correcciones solicitadas por el verificador", 1, "B", False),
    ("## Necesidad\nObjetivo: x", 0, "B", False),                                  # B sin DEVUELTA de A (no aplica)
    ("## Necesidad\nObjetivo: x", 1, "A", False),                                  # la versión A no lleva sección
])
def test_pr14_6_la_puerta_exige_los_comentarios_de_la_devuelta(cuerpo, devueltas, version, falla):
    dec = [{"id": f"D-00{i + 2}", "tipo": "DEVUELTA", "version": "A", "comentarios": f"c{i}"} for i in range(devueltas)]
    dec.append({"id": "D-009", "tipo": "DEVUELTA", "version": "B", "comentarios": "de otra versión: no cuenta"})
    estado = {"carga": {"alta": {"terminos_sensibles": [], "codigo_cliente": "KELVARA"}, "briefs": [_brief(version, cuerpo)]},
              "decisiones": dec}
    c = vp.c_brief(types.SimpleNamespace(estado=estado, carga=estado["carga"]))   # sin transcripción: no recompone
    assert (c.estado == vp.FALLA) is falla and _con(c, "PR14-6") is (falla or (devueltas > 0 and version == "B")), c.detalles
    if not falla and devueltas and version == "B":
        assert c.estado == vp.AVISO and _con(c, "contenido no contrastado"), c.detalles
