"""I1.5 · D · La réplica de `cortes_conectores` que propone docs/I1/CAMBIOS-I15-D.md §2.1 para la puerta es la
misma función que la del núcleo (LES-G-097) y da lo mismo sobre casos al azar y sobre el PPTX generado. Sin red."""
from __future__ import annotations

import ast
import inspect
import pathlib
import random
import re
import sys

from lxml import etree

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import pptx_revision as pr  # noqa: E402

DOC = RAIZ / "docs" / "I1" / "CAMBIOS-I17-D.md"  # I1.7 (D16-5 y REV16-5): la réplica vigente está en CAMBIOS-I17-D §7


def _replica():
    texto = DOC.read_text(encoding="utf-8")
    bloques = [b for b in re.findall(r"```python\n(.*?)```", texto, re.S) if "def cortes_conectores_replica" in b]
    assert len(bloques) == 1, "CAMBIOS-I17-D.md tiene que traer exactamente un bloque con la réplica"
    espacio: dict = {}
    exec(compile(bloques[0], str(DOC), "exec"), espacio)  # noqa: S102 - código del propio repositorio
    return bloques[0], espacio["cortes_conectores_replica"]


def _sin_nombre(fuente: str) -> str:
    arbol = ast.parse(fuente.replace("\r\n", "\n"))
    funcion = next(n for n in arbol.body if isinstance(n, ast.FunctionDef))
    funcion.name = "f"
    return ast.dump(funcion)


def test_misma_funcion_que_la_del_nucleo():
    fuente, _ = _replica()
    assert _sin_nombre(fuente) == _sin_nombre(inspect.getsource(pr.cortes_conectores))


NS = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')


def _forma(azar, i):
    x, y = azar.randint(0, 400000), azar.randint(0, 400000)  # escala EMU: los márgenes por defecto son 91.440
    w, h = azar.randint(0, 300000), azar.randint(0, 300000)
    ins = "".join(f' {k}="{azar.randint(0, 30000)}"' for k in ("lIns", "tIns", "rIns", "bIns") if azar.random() < 0.5)
    texto = azar.choice(["Texto", "", "Servicio"])
    rot = ' rot="60000"' if azar.random() < 0.03 else ""
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Forma {i}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>'
            f'<a:xfrm{rot}><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm></p:spPr><p:txBody>'
            f'<a:bodyPr{ins}/><a:p><a:r><a:t>{texto}</a:t></a:r></a:p></p:txBody></p:sp>')


def _conector(azar, i):
    prst = azar.choice(["line", "straightConnector1", "bentConnector2", "bentConnector3", "bentConnector4",
                        "bentConnector5", "curvedConnector3"])
    av = "".join(f'<a:gd name="adj{k}" fmla="val {azar.randint(-150000, 250000)}"/>' for k in (1, 2, 3)
                 if azar.random() < 0.7)
    flips = "".join(f' {f}="1"' for f in ("flipH", "flipV") if azar.random() < 0.4)
    x, y, w, h = (azar.randint(0, 500000) for _ in range(4))
    return (f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="Flujo {i}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm{flips}><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            f'<a:prstGeom prst="{prst}"><a:avLst>{av}</a:avLst></a:prstGeom></p:spPr></p:cxnSp>')


def test_diferencial_aleatoria():
    _, replica = _replica()
    azar = random.Random(1015)
    con_cortes = sin_cortes = 0
    for _ in range(600):
        cuerpo = "".join(_forma(azar, i) for i in range(azar.randint(1, 4)))
        cuerpo += "".join(_conector(azar, 100 + i) for i in range(azar.randint(1, 3)))
        sld = etree.fromstring(f"<p:sld {NS}><p:cSld><p:spTree>{cuerpo}</p:spTree></p:cSld></p:sld>")
        a, b = pr.cortes_conectores(sld), replica(sld)
        assert a == b
        con_cortes += any("corta" in f for f in a)
        sin_cortes += not a
    assert con_cortes >= 60 and sin_cortes >= 60, (con_cortes, sin_cortes)  # LES-G-099.5: ni verde ni rojo vacíos


def test_sobre_el_diagrama_generado(tmp_path):
    from pptx import Presentation
    from pptx.util import Emu
    sys.path.insert(0, str(RAIZ / "tests"))
    import test_i15_d_conectores as t
    comps, flujos = t._real()
    prs = Presentation()
    prs.slide_width, prs.slide_height = pr.ANCHO, pr.ALTO
    diapo = prs.slides.add_slide(prs.slide_layouts[6])
    pr.dibujar_diagrama(diapo, comps, flujos, pr.MARGEN, Emu(1200000), pr.ANCHO_UTIL, Emu(3470000))
    ruta = tmp_path / "diagrama.pptx"
    prs.save(ruta)
    from pptx import Presentation as Abrir
    sld = Abrir(ruta).slides[0]._element  # lo que lee la puerta: el XML guardado, no el objeto en memoria
    _, replica = _replica()
    assert replica(sld) == pr.cortes_conectores(sld) == []
