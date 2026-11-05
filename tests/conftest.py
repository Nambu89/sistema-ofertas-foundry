"""Configuración común de pytest: añade la raíz del repositorio al sys.path."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import os  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _entorno_aislado():
    """Cada prueba deja os.environ como lo encontró: hosted/main.preparar_entorno fija PREVENTA_GENERADOR y demás al
    importarse, y desde que el núcleo y la puerta leen esas variables (PREVENTA_PROYECTOS, 04-11-2026) la fuga
    cambiaba el resultado de las pruebas que venían detrás."""
    antes = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(antes)

