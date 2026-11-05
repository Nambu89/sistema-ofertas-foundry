"""Integrador I1.7: la sección VER16-5 «Cambios pedidos en la revisión anterior» en la diapositiva 2 del PPTX.

- Un comentario de la DEVUELTA con un importe (moneda, decimales o una cifra de 100 o más, también sin moneda: Revisión,
  pasada 2) o demasiado largo no se copia al PPTX: remite a la nota del revisor (decision._no_apto_para_cliente).
- I1.8 · D (VER17-2): la sección salió del PPTX; tam_cambios ya no existe."""
from __future__ import annotations

import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import decision, pptx_revision  # noqa: E402

PERFILES = ["AI Engineer / Tech Lead", "Project Manager"]


@pytest.mark.parametrize("texto, no_apto", [
    ("El coste es 1200 al mes", True),            # Revisión 2: entero sin moneda
    ("Baja el precio a 15.000 €", True),
    ("El precio de 18.572,50 está alto", True),
    ("Son 3 EUR de más", True),
    ("Usar 1.500 consultas al mes", True),
    ("Revisa el nivel de Azure AI Search", False),
    ("Cambia a 2 réplicas", False),
    ("Quita el TBD del supuesto", True),          # marcador
    ("Aplicar desde 2027", True),                 # Revisión 3: conservador a propósito; el comentario sigue en la nota
])
def test_comentario_no_apto_para_el_pptx(texto, no_apto):
    assert bool(decision._no_apto_para_cliente(texto, PERFILES)) is no_apto


def test_la_seccion_ya_no_va_en_el_pptx():
    """I1.8 · D (VER17-2): la sección vive solo en la nota del revisor; ya no hay tamaño de letra que elegir en la
    diapositiva 2 (tests/test_i18_d_revision_interna.py comprueba que ningún PPTX lleva texto de la revisión)."""
    assert not hasattr(pptx_revision, "tam_cambios") and not hasattr(pptx_revision, "_cambios_pedidos")
