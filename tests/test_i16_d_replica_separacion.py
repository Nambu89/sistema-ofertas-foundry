"""I1.6 · D · La réplica de `separacion_conectores` que propone docs/I1/CAMBIOS-I16-D.md §2.1 para la puerta es la
misma función que la del núcleo (LES-G-097) y da lo mismo sobre casos al azar y sobre los PPTX regenerados. Sin red."""
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
NS = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')


def _replica():
    texto = DOC.read_text(encoding="utf-8")
    bloques = [b for b in re.findall(r"```python\n(.*?)```", texto, re.S) if "def separacion_conectores_replica" in b]
    assert len(bloques) == 1, "CAMBIOS-I17-D.md tiene que traer exactamente un bloque con la réplica"
    espacio: dict = {}
    exec(compile(bloques[0], str(DOC), "exec"), espacio)  # noqa: S102 - código del propio repositorio
    return bloques[0], espacio["separacion_conectores_replica"]


def _sin_nombre(fuente: str) -> str:
    arbol = ast.parse(fuente.replace("\r\n", "\n"))
    funcion = next(n for n in arbol.body if isinstance(n, ast.FunctionDef))
    funcion.name = "f"
    return ast.dump(funcion)


def test_misma_funcion_que_la_del_nucleo():
    fuente, _ = _replica()
    assert _sin_nombre(fuente) == _sin_nombre(inspect.getsource(pr.separacion_conectores))


def _forma(azar, i):
    x, y = azar.randint(0, 2000000), azar.randint(0, 2000000)
    w, h = azar.randint(0, 400000), azar.randint(0, 400000)
    nombre = azar.choice([f"Componente {i}", f"Banda {i}", f"TextBox {i}"])
    rot = ' rot="60000"' if azar.random() < 0.02 else ""
    texto = azar.choice(["Servicio", "", "Texto"])
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{nombre}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>'
            f'<a:xfrm{rot}><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm></p:spPr><p:txBody>'
            f'<a:bodyPr/><a:p><a:r><a:t>{texto}</a:t></a:r></a:p></p:txBody></p:sp>')


def _conector(azar, i, ids, previo):
    prst = azar.choice(["line", "line", "bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5",
                        "curvedConnector3"])
    av = "".join(f'<a:gd name="adj{k}" fmla="val {azar.randint(-150000, 250000)}"/>' for k in (1, 2, 3)
                 if azar.random() < 0.7)
    flips = "".join(f' {f}="1"' for f in ("flipH", "flipV") if azar.random() < 0.4)
    x, y = azar.randint(0, 2000000), azar.randint(0, 2000000)
    if previo and azar.random() < 0.25:  # a veces arranca donde el anterior: punto de conexión compartido
        x, y = previo[-1]
    previo.append((x, y))
    w, h = azar.randint(0, 900000), azar.randint(0, 900000)
    if prst == "line" and azar.random() < 0.8:  # recta horizontal o vertical casi siempre
        w, h = (w, 0) if azar.random() < 0.5 else (0, h)
    if azar.random() < 0.05:  # de vez en cuando, un conector sin trazado
        w = h = 0
    pegado = "".join(f'<a:{e} id="{azar.choice(ids)}" idx="{azar.randint(0, 3)}"/>' for e in ("stCxn", "endCxn")
                     if azar.random() < 0.15)
    return (f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="Flujo {i}"/><p:cNvCxnSpPr>{pegado}</p:cNvCxnSpPr>'
            f'<p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm{flips}><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/>'
            f'</a:xfrm><a:prstGeom prst="{prst}"><a:avLst>{av}</a:avLst></a:prstGeom></p:spPr></p:cxnSp>')


def test_diferencial_aleatoria():
    _, replica = _replica()
    azar = random.Random(1016)
    vacios = con_fallos = 0
    tipos = {"comparten tramo": 0, "prolongar": 0, "se cruzan": 0, "punto de conexión": 0, "pasa a menos": 0,
             "extremo": 0, "longitud nula": 0}
    for _ in range(600):
        n = azar.randint(0, 3)
        cuerpo = "".join(_forma(azar, i) for i in range(1, n + 1))
        previo: list = []
        cuerpo += "".join(_conector(azar, 100 + i, [str(k) for k in range(1, n + 2)], previo)
                          for i in range(azar.randint(1, 3)))
        sld = etree.fromstring(f"<p:sld {NS}><p:cSld><p:spTree>{cuerpo}</p:spTree></p:cSld></p:sld>")
        a, b = pr.separacion_conectores(sld), replica(sld)
        assert a == b
        vacios += not a
        con_fallos += bool(a)
        for clave in tipos:
            tipos[clave] += any(clave in f for f in a)
    assert vacios >= 60 and con_fallos >= 60, (vacios, con_fallos)  # LES-G-099.5: ni verde ni rojo vacíos
    assert all(v >= 5 for v in tipos.values()), tipos  # cada regla se ejercita


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
    sld = Presentation(ruta).slides[0]._element  # lo que lee la puerta: el XML guardado
    _, replica = _replica()
    assert replica(sld) == pr.separacion_conectores(sld) == []
