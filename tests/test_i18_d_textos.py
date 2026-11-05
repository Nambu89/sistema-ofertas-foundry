"""I1.8 · D · Dos defectos de texto para el cliente vistos al mirar el render de la versión B real de I1.7:
D18-1 «1 consultas de ranking semántico por consulta» (concordancia, LES-G-037) y D18-2 el medidor «Semantic Ranker
queries» como «Consumo del servicio (por mil)». Sin red."""
from __future__ import annotations

import pytest

from tests.i18_d_datos import RAIZ  # noqa: F401  (pone sandbox en sys.path)
from nucleo import textos_cliente as tc  # noqa: E402


@pytest.mark.parametrize("cantidad, unidad, esperada", [
    ("1", "consultas de ranking semántico por consulta", "consulta de ranking semántico por consulta"),
    ("1", "GB almacenados por documento", "GB almacenado por documento"),
    ("1", "tokens de entrada por consulta", "token de entrada por consulta"),
    ("1", "Consultas al mes", "Consulta al mes"),
    ("1", "unidades raras por consulta", "unidades raras por consulta"),   # no está en la lista: no se inventa
    ("2", "mensajes por consulta", "mensajes por consulta"),
    ("1,5", "consultas al mes", "consultas al mes"),
    ("1.000", "consultas al mes", "consultas al mes"),
])
def test_concordar(cantidad, unidad, esperada):
    assert tc.concordar(cantidad, unidad) == esperada


def test_supuesto_con_factor_uno_en_singular():
    resp = {"componentes": [{"id": "C-01", "catalogo_id": "az-ai-search"}],
            "precios": [{"id": "P-01", "componente_id": "C-01",
                         "base_volumen": {"cantidad_base": 2000, "unidad_base": "consultas al mes", "cita": "2.000"},
                         "factor": {"valor": 1, "unidad": "consultas de ranking semántico por consulta"},
                         "factor_override": None}]}
    frases, _, fallidos = tc.supuestos_consumo(resp, {"az-ai-search": "Azure AI Search"})
    assert fallidos == [] and len(frases) == 1
    assert "2.000 consultas al mes y 1 consulta de ranking semántico por consulta" in frases[0][0]
    assert "1 consultas" not in frases[0][0]


def test_ranking_semantico_con_nombre():
    linea = {"concepto": "Semantic Ranker queries", "unidad": "1K", "servicio": "Azure AI Search"}
    assert tc.concepto_legible(linea) == "Consultas de ranking semántico (por mil)"
    assert tc.barrer(tc.concepto_legible(linea), []) == []
