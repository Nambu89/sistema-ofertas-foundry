"""I1.1 (integración): restaurar con zip= y consolidar con lotes= en preventa_api (R-5, H-5)."""
from __future__ import annotations

import pytest

import tests.test_i1_estado_comun  # noqa: F401  (pone sandbox/ en sys.path)
import preventa_api  # noqa: E402


@pytest.fixture
def capturado(monkeypatch):
    llamadas = []
    monkeypatch.setattr(preventa_api, "ejecutar", lambda carpeta, args: llamadas.append(args) or "ok")
    return llamadas


def test_restaurar_con_zip(capturado):
    assert preventa_api.restaurar("c", zip="OF-X-001-A-Relevo.zip") == "ok"
    assert capturado == [["restaurar", "--zip=OF-X-001-A-Relevo.zip"]]


def test_restaurar_forma_anterior_sigue(capturado):
    preventa_api.restaurar("c", estado="estado.json", manifiesto="manifiesto_paquete.json")
    assert capturado == [["restaurar", "--estado=estado.json", "--manifiesto=manifiesto_paquete.json"]]


@pytest.mark.parametrize("kw", [
    {"zip": "a.zip", "estado": "estado.json"},
    {"zip": "a.zip", "manifiesto": "m.json"},
    {"estado": "estado.json"},
    {},
])
def test_restaurar_formas_mezcladas_o_incompletas_fallan_en_alto(capturado, kw):
    with pytest.raises(ValueError):
        preventa_api.restaurar("c", **kw)
    assert capturado == []


def test_consolidar_con_y_sin_lotes(capturado):
    preventa_api.consolidar("c")
    preventa_api.consolidar("c", lotes=True)
    assert capturado == [["consolidar"], ["consolidar", "--lotes"]]
