"""I1.6 · R · VER15-4 en el hosted: la relectura GetTask solo cuenta como hecha con HTTP 200, sin error y con la tarea
completada (la misma lista blanca que `verificar_paquete.juicio_relectura`). Sin red."""
from __future__ import annotations

import types

import pytest

pytest.importorskip("httpx")
from tests.test_hosted_falsos import NUCLEO  # noqa: E402,F401  (pone hosted/ y el núcleo en sys.path)
from preventa_hosted import procedencia as PR  # noqa: E402


def _leida(**kw):
    base = dict(inicio="2026-10-11T09:00:00+00:00", http=200, latencia_s=0.4, error=None,
                estado_tarea="TASK_STATE_COMPLETED", sha256_recibido="a" * 64)
    return types.SimpleNamespace(**{**base, **kw})


@pytest.mark.parametrize("cambio, ok", [
    ({}, True),
    ({"http": 500}, False),          # sin error anotado pero con otro HTTP: no es una lectura válida
    ({"http": 202}, False),
    ({"http": None}, False),
    ({"http": 200.0}, False),        # solo el entero 200, como la puerta
    ({"http": "200"}, False),
    ({"http": True}, False),
    ({"error": "TaskNotFound"}, False),
    ({"estado_tarea": "TASK_STATE_WORKING"}, False),
])
def test_leida_ok_es_lista_blanca(cambio, ok):
    assert PR.leida_ok(_leida(**cambio)) is ok
    envio = types.SimpleNamespace(sha256_recibido="a" * 64)
    rel = PR.relectura(envio, _leida(**cambio))
    assert rel["coincide"] is (True if ok else None) and rel["metodo"] == "GetTask"
    assert (rel["sha256_recibido"] is None) is (not ok)


def test_leida_none_no_cuenta():
    assert PR.leida_ok(None) is False
    rel = PR.relectura(types.SimpleNamespace(sha256_recibido="a" * 64), None)
    assert rel["coincide"] is None and rel["intentos"] == 0
