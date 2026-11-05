"""Hosted agent: la entrada de la estimación la compone el código y el núcleo la acepta tal cual (arregla H4)."""
from __future__ import annotations

import copy
import json
from datetime import date

import pytest

from tests.test_hosted_falsos import NUCLEO, RAIZ, ejemplo

from preventa_hosted import estimacion_entrada  # noqa: E402


@pytest.fixture
def nucleo():
    import sys
    sys.path.insert(0, str(NUCLEO))
    import preventa_api  # noqa: F401  (pone el paquete nucleo al alcance)
    from nucleo import esquema, estimacion
    return esquema, estimacion


def _tarifa(estimacion):
    return estimacion.cargar_tarifa(RAIZ / "tests" / "insumos" / "rate-card.sintetica.json")


def test_entrada_valida_contra_esquema_y_reglas(nucleo):
    esquema, N = nucleo
    est = ejemplo("estado")
    tarifa = _tarifa(N)
    entrada, avisos = estimacion_entrada.construir(est, N.hitos_tarifa(tarifa), date(2026, 10, 8))
    assert esquema.validar(entrada, esquema.cargar("estimacion_entrada")) == []
    assert N.validar_entrada(entrada, est, tarifa, None) == []
    propuestas = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]["tareas_propuestas"]
    assert [t["id"] for t in entrada["tareas"]] == [t["id"] for t in propuestas] + ["PM-01"]
    assert entrada["ajuste_comercial_eur"] == 0 and entrada["fecha"] == "2026-10-08"
    assert entrada["gantt"][-1]["semanas"] == list(range(1, entrada["duracion_semanas"] + 1))
    assert "contingencia" not in json.dumps(entrada, ensure_ascii=False).lower()
    assert avisos == []


def test_pm_minimo_y_textos_que_no_caben(nucleo):
    _, N = nucleo
    est = copy.deepcopy(ejemplo("estado"))
    resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    resp["tareas_propuestas"] = resp["tareas_propuestas"][:1]
    resp["tareas_propuestas"][0]["horas_base"] = 4
    resp["supuestos"] = [{"id": "S-01", "texto": "x" * 401, "confianza": "BAJA", "hechos": []},
                         {"id": "S-02", "texto": "Se reserva una contingencia del 15 %", "confianza": "BAJA", "hechos": []}]
    entrada, avisos = estimacion_entrada.construir(est, N.hitos_tarifa(_tarifa(N)), date(2026, 10, 8))
    pm = entrada["tareas"][-1]
    assert pm["tecnicas_h"] == 8 and N.horas_tarea(pm["tecnicas_h"], pm["reuniones_h"]) >= 8
    assert entrada["asunciones"] == [] and len(avisos) == 2


def test_sin_tareas_del_experto_falla_en_alto():
    est = copy.deepcopy(ejemplo("estado"))
    est["carga"]["respuestas_expertos"] = {}
    with pytest.raises(ValueError, match="tareas_propuestas"):
        estimacion_entrada.construir(est, [], date(2026, 10, 8))
