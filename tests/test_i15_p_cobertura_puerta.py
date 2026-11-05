"""I1.5 · papel P: réplica de la cobertura de precios (PR15-2) y de REVERIF14-2 en verificar_paquete.py, igual al
núcleo (LES-G-097). La réplica la integra el integrador desde docs/I1/CAMBIOS-I15-P.md: hasta entonces estas pruebas
dan XFAIL estricto (PENDIENTE_REPLICA); integrada, son pruebas normales. Sin red."""
from __future__ import annotations

import copy
import json
import pathlib
import random
import types
import zipfile

import pytest

from tests.test_i15_p_cobertura_precios import CAT, RAIZ, _ej, con_motivos
from nucleo import anexo_consumo as A, experto  # noqa: E402
import verificar_paquete as vp  # noqa: E402
from tests import i19_p_datos as D19  # noqa: E402  (I1.9: pegado simulado de las réplicas)

PENDIENTE_REPLICA = pytest.mark.xfail(not hasattr(vp, "errores_cobertura_replica"), strict=True,
                                      reason="réplica de PR15-2 pendiente de integrar (docs/I1/CAMBIOS-I15-P.md)")
# I1.6 (decisión 4, REV15-1): el núcleo ya no cuenta como cobertura un precio auxiliar ni uno de referencia (cantidad
# null); la réplica de I1.5 sí. Hasta integrar la réplica de docs/I1/CAMBIOS-I16-P.md, XFAIL estricto.
PENDIENTE_I16 = pytest.mark.xfail(not hasattr(vp, "precios_que_cubren_replica"), strict=True,
                                  reason="réplica de la cobertura de I1.6 pendiente de integrar (docs/I1/CAMBIOS-I16-P.md)")
REAL_I14 = RAIZ / "pruebas" / "I14" / "REAL" / "B" / "descargas_A" / "OF-BREZALIA-001-A-Paquete.zip"
INSTRUCCIONES = RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md"


def _variantes(n: int = 300):
    """Respuestas del ejemplo con motivos, precios, catalogo_id y regiones al azar (semilla fija)."""
    rnd = random.Random(1511)
    base = con_motivos(_ej("respuesta_experto_completa"))
    motivos = [A.SIN_MOTIVO, *A.MOTIVOS_NO_VALORACION]
    for _ in range(n):
        resp = copy.deepcopy(base)
        resp["precios"] = [p for p in resp["precios"] if rnd.random() < 0.6]
        for c in resp["componentes"]:
            c["motivo_no_valoracion"] = rnd.choice(motivos)
            if rnd.random() < 0.25:
                c.update(catalogo_id=None, servicio=rnd.choice(["Azure Front Door", "SharePoint Online", "Bot de Teams"]),
                         region=rnd.choice(["global", "westeurope"]))
        yield resp


def _ctx(resp: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(respuesta=resp, catalogo_obj=CAT, estado={})


@PENDIENTE_REPLICA
@PENDIENTE_I16
def test_replica_de_la_cobertura_igual_al_nucleo_en_300_casos(monkeypatch):
    D19.pegar_replicas_i19(monkeypatch)  # I1.9: la puerta con las réplicas de CAMBIOS-I19-P pegadas
    vistas = set()
    for resp in _variantes():
        nucleo = [(x["componente_id"], x["regla"]) for x in A.errores_cobertura(resp, CAT)]
        assert vp.errores_cobertura_replica(resp, CAT) == nucleo
        for c in resp["componentes"]:
            assert vp.region_exige_catalogo_replica(c) == bool(experto.region_exige_catalogo(c))
        vistas |= {r for _, r in nucleo}
    # nada de verdes vacíos; REV16-1 (arreglos I1.6) añade las dos reglas que comprueban el motivo contra el catálogo
    assert vistas == {"sin_precio_ni_motivo", "precio_y_motivo", "fuera_del_catalogo_con_id",
                      "licencia_con_precio_azure", "medidor_publico_en_catalogo"}
    assert vp.MOTIVOS_NO_VALORACION_REPLICA == tuple(A.MOTIVOS_NO_VALORACION) and vp.SIN_MOTIVO_REPLICA == A.SIN_MOTIVO


@PENDIENTE_REPLICA
@PENDIENTE_I16
def test_la_puerta_da_ok_con_el_ejemplo_y_falla_con_cada_caso_adverso(monkeypatch):
    D19.pegar_replicas_i19(monkeypatch)  # I1.9: la puerta con las réplicas de CAMBIOS-I19-P pegadas
    c = vp.Comprobacion("experto", "x")
    vp._cobertura_precios(_ctx(con_motivos(_ej("respuesta_experto_completa"))), c)
    assert c.estado == "OK", c.detalles
    for cid, campo, valor, esperado in (("C-03", "motivo_no_valoracion", "no_aplica", "sin_precio_ni_motivo"),
                                        ("C-02", "motivo_no_valoracion", "a_cargo_del_cliente", "precio_y_motivo"),
                                        ("C-03", "catalogo_id", None, "REVERIF14-2")):
        resp = con_motivos(_ej("respuesta_experto_completa"))
        next(x for x in resp["componentes"] if x["id"] == cid)[campo] = valor
        c = vp.Comprobacion("experto", "x")
        vp._cobertura_precios(_ctx(resp), c)
        assert c.estado == "FALLA" and esperado in "\n".join(c.detalles), (cid, c.detalles)


@PENDIENTE_REPLICA
def test_la_puerta_falla_con_una_respuesta_anterior_a_i15_y_la_valida_con_su_esquema():
    with zipfile.ZipFile(REAL_I14) as z:
        resp = json.loads(z.read("estado.json"))["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    assert vp.nombre_esquema_experto(resp) == "historico/respuesta_experto_v1"
    assert vp.validar_esquema(resp, "historico/respuesta_experto_v1") == []
    assert vp.validar_esquema(resp, "respuesta_experto")  # con la v2 falla: falta motivo_no_valoracion
    # con motivo y sin justificacion_nivel es el contrato v2 de I1.5: desde I1.6 se valida con su histórico
    v2 = "historico/respuesta_experto_v2" if hasattr(vp, "es_contrato_experto_v2") else "respuesta_experto"
    assert vp.nombre_esquema_experto(con_motivos(copy.deepcopy(resp))) == v2
    c = vp.Comprobacion("experto", "x")
    vp._cobertura_precios(_ctx(resp), c)
    assert c.estado == "FALLA" and "anterior a I1.5" in "\n".join(c.detalles)


@PENDIENTE_REPLICA
def test_la_puerta_falla_si_no_puede_contrastar_con_el_nucleo():
    resp = con_motivos(_ej("respuesta_experto_completa"))
    resp["componentes"][0]["catalogo_id"] = "az-no-existe"
    c = vp.Comprobacion("experto", "x")
    vp._cobertura_precios(_ctx(resp), c)
    assert c.estado == "FALLA" and "no se pudo contrastar" in "\n".join(c.detalles)


@pytest.mark.xfail("existente_del_cliente" not in INSTRUCCIONES.read_text(encoding="utf-8"), strict=True,
                   reason="instrucciones del experto pendientes de integrar (docs/I1/CAMBIOS-I19-P.md §5.5)")
def test_las_instrucciones_del_experto_ensenan_cada_motivo():
    texto = INSTRUCCIONES.read_text(encoding="utf-8")
    # I1.9: «a_cargo_del_cliente» solo queda en el código para las respuestas v4 guardadas; el experto ya no lo usa
    assert all(f"`{m}`" in texto for m in (A.SIN_MOTIVO, *A.MOTIVOS_NO_VALORACION) if m != "a_cargo_del_cliente")
