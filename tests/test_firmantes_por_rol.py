"""Quien firma decisiones se nombra por su rol (Responsable comercial, de preventa y de área).

El rol entero se trata como un nombre: no sale al cliente en el PPTX y llega anonimizado al experto en el brief. Sus
palabras sueltas o por pares («responsable de», «de preventa») son corrientes y no se tocan. Sin evidencias reales:
un PPTX mínimo y el estado sintético de esquemas/ejemplos.
"""
from __future__ import annotations

import json
import pathlib
import sys

from pptx import Presentation
from pptx.util import Emu

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
from nucleo import brief, decision, pptx_revision as pr  # noqa: E402

ESTADO = json.loads((RAIZ / "esquemas" / "ejemplos" / "estado.json").read_text(encoding="utf-8"))
CATALOGO = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))


def _hallazgos(lineas: list[str]) -> list[str]:
    prs = Presentation()
    diapo = prs.slides.add_slide(prs.slide_layouts[6])
    pr.texto(diapo, Emu(500000), Emu(500000), Emu(8000000), Emu(2000000), lineas, 10)
    return pr.revision_interna_en_pptx(pr.partes_de(prs), ESTADO, CATALOGO)


def test_el_rol_entero_no_sale_al_cliente():
    halla = "\n".join(_hallazgos(["Lo pidió el Responsable de área en la revisión", "Según el responsable comercial"]))
    assert "«responsable de area»" in halla and "«responsable comercial»" in halla, halla


def test_las_palabras_del_rol_sueltas_no_son_un_nombre():
    assert _hallazgos(["El responsable de RR. HH. valida los datos de preventa del área comercial"]) == []


def test_el_brief_anonimiza_el_rol_entero_y_no_sus_palabras():
    alta = {"terminos_sensibles": ["Kelvara"], "cliente": "Kelvara", "codigo_cliente": "KELVARA"}
    sens, cliente, personas = brief.terminos_anonimizacion(alta, [])
    assert set(decision.NOMBRES_DECISIONES) <= set(personas)
    texto = "Lo revisó el Responsable de preventa; el responsable de RR. HH. de Kelvara lo valida"
    assert brief.anonimizar(texto, sens, cliente, personas) == (
        "Lo revisó el [PERSONA]; el responsable de RR. HH. de [CLIENTE] lo valida")
