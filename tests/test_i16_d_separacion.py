"""I1.6 · D · ARR15-2/D15-4: `separacion_conectores` (casos fijos de cada regla) y los dos paquetes reales de I1.5
(B y A, Brezalia) regenerados con el núcleo nuevo: sin tramos compartidos, sin conectores pegados a otra forma, sin
cruces junto a un extremo, un punto por flecha y ninguna por el lado contrario. Sin red."""
from __future__ import annotations

import json
import pathlib
import sys
import zipfile

import pytest
from lxml import etree

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import pptx_revision as pr, textos_cliente  # noqa: E402

NS = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')
REAL = RAIZ / "pruebas" / "I15" / "ARREGLOS" / "REAL"
PAQUETES = {"B": REAL / "B" / "sesion_2" / "OF-BREZALIA-001-A-Paquete.zip",
            "A": REAL / "A" / "descargas" / "OF-BREZALIA-001-A-Paquete.zip"}


def _arbol(cuerpo: str):
    return etree.fromstring(f"<p:spTree {NS}>{cuerpo}</p:spTree>")


def _caja(i, x, y, w, h, nombre=None):
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="{nombre or f"Componente {i}"}"/><p:cNvSpPr/><p:nvPr/>'
            f'</p:nvSpPr><p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:p><a:r><a:t>Caja {i}</a:t></a:r></a:p></p:txBody></p:sp>')


def _recta(i, p, q, st=None, en=None, prst="line", idx=("0", "0")):
    (x0, y0), (x1, y1) = p, q
    flips = (' flipH="1"' if x1 < x0 else "") + (' flipV="1"' if y1 < y0 else "")
    pegado = (f'<a:stCxn id="{st}" idx="{idx[0]}"/>' if st else "") + (f'<a:endCxn id="{en}" idx="{idx[1]}"/>' if en else "")
    return (f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{i}" name="Flujo {i}"/><p:cNvCxnSpPr>{pegado}</p:cNvCxnSpPr>'
            f'<p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm{flips}><a:off x="{min(x0, x1)}" y="{min(y0, y1)}"/>'
            f'<a:ext cx="{abs(x1 - x0)}" cy="{abs(y1 - y0)}"/></a:xfrm><a:prstGeom prst="{prst}"><a:avLst/>'
            f'</a:prstGeom></p:spPr></p:cxnSp>')


def _sep(*partes):
    return pr.separacion_conectores(_arbol("".join(partes)))


def test_tramos_compartidos_y_en_linea():
    assert any("comparten tramo" in f for f in _sep(_recta(1, (0, 0), (500000, 0)), _recta(2, (300000, 0), (900000, 0))))
    assert any("comparten tramo" in f for f in _sep(_recta(1, (0, 0), (500000, 0)),
                                                   _recta(2, (300000, 59999), (900000, 59999))))
    assert _sep(_recta(1, (0, 0), (500000, 0)), _recta(2, (300000, 60000), (900000, 60000))) == []
    assert any("prolongar" in f for f in _sep(_recta(1, (0, 0), (500000, 0)), _recta(2, (679999, 0), (900000, 0))))
    assert _sep(_recta(1, (0, 0), (500000, 0)), _recta(2, (680000, 0), (900000, 0))) == []


def test_cruces_y_puntos_de_conexion():
    assert _sep(_recta(1, (0, 0), (1000000, 0)), _recta(2, (500000, -400000), (500000, 400000))) == []
    junto = _sep(_recta(1, (0, 0), (1000000, 0)), _recta(2, (179999, -400000), (179999, 400000)))
    assert any("se cruzan" in f for f in junto)
    toque = _sep(_recta(1, (0, 0), (1000000, 0)), _recta(2, (500000, 0), (500000, 400000)))  # T: acaba sobre el otro
    assert any("se cruzan o se tocan" in f for f in toque)
    assert any("punto de conexión" in f for f in _sep(_recta(1, (0, 0), (0, 500000)), _recta(2, (0, 0), (700000, 0))))


def test_distancia_a_formas_ajenas():
    caja = _caja(5, 1000000, 1000000, 400000, 300000)
    assert any("pasa a menos de 80.000 EMU de la forma «Caja 5»" in f
               for f in _sep(caja, _recta(1, (0, 920001), (2000000, 920001))))
    assert _sep(caja, _recta(1, (0, 920000), (2000000, 920000))) == []
    propio = _recta(1, (1200000, 0), (1200000, 1000000), en="5")  # llega arriba de su destino: exento
    assert _sep(caja, propio) == []
    assert any("Caja 5" in f for f in _sep(caja, _recta(1, (1200000, 0), (1200000, 1000000))))  # sin pegar: no
    banda = _caja(6, 0, 900000, 3000000, 600000, nombre="Banda Identidad")
    assert _sep(banda, _recta(1, (100000, 1000000), (2000000, 1000000))) == []


def test_extremos_pegados_donde_dicen():
    """Revisión de la revisión independiente (I1.6): el extremo pegado está en el lado de su forma (con 2.000 de tolerancia)."""
    caja = _caja(5, 1000000, 1000000, 400000, 300000)
    assert _sep(caja, _recta(1, (1200000, 0), (1200000, 998000), en="5")) == []           # 2.000 por encima
    assert any("no está en el lado de arriba" in f for f in _sep(caja, _recta(1, (1200000, 0), (1200000, 997999), en="5")))
    assert any("no está en el lado izquierdo" in f
               for f in _sep(caja, _recta(1, (1200000, 0), (1200000, 1000000), en="5", idx=("0", "1"))))
    assert any("no existe" in f for f in _sep(caja, _recta(1, (1200000, 0), (1200000, 1000000), en="9")))
    assert any("no existe" in f for f in _sep(caja, _recta(1, (1200000, 0), (1200000, 1000000), en="5", idx=("0", "7"))))


def test_lo_que_no_se_puede_comprobar_falla():
    assert any("longitud nula" in f for f in _sep(_recta(1, (5000, 5000), (5000, 5000))))
    enorme = _recta(1, (0, 0), (300000, 200000), prst="bentConnector3").replace(
        "<a:avLst/>", f'<a:avLst><a:gd name="adj1" fmla="val {"9" * 5000}"/></a:avLst>')
    assert any("geometría" in f for f in _sep(enorme))  # ni excepción por un número desmesurado
    unicode = enorme.replace("9" * 5000, "²")
    assert any("geometría" in f for f in _sep(unicode))
    dos_signos = enorme.replace("9" * 5000, "--1")  # segunda revisión independiente: fallo, no ValueError
    assert any("geometría" in f for f in _sep(dos_signos))
    assert any("horizontal ni vertical" in f for f in _sep(_recta(1, (0, 0), (300000, 200000))))
    assert any("geometría" in f for f in _sep(_recta(1, (0, 0), (300000, 0), prst="curvedConnector3")))
    grupo = '<p:grpSp><p:nvGrpSpPr><p:cNvPr id="5" name="Grupo"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr></p:grpSp>'
    assert any("grupo" in f for f in _sep(grupo))
    assert pr.separacion_conectores(etree.fromstring(f"<p:sld {NS}/>")) != []


def _estado(x: str) -> dict:
    with zipfile.ZipFile(PAQUETES[x]) as z:
        return json.loads(z.read("estado.json").decode("utf-8"))


def _catalogo() -> dict:
    return json.loads((RAIZ / "catalogo" / "catalogo_componentes.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("x", ["B", "A"])
def test_paquetes_reales_regenerados(x):
    prs, informe = pr.construir(_estado(x), _catalogo())
    assert informe == {"modo": "diagrama", "fallos": []}
    d4 = prs.slides[3]
    arbol = d4.shapes._spTree
    assert pr.cortes_conectores(arbol) == [] and pr.separacion_conectores(arbol) == []
    rects = {str(s.shape_id): pr._rect(s) for s in d4.shapes if s.name.startswith(pr.PREFIJO_COMPONENTE)}
    for con in (c for c in d4.shapes if c.name.startswith("Flujo ")):
        st, en = (con._element.find(".//" + pr.qn(f"a:{e}")) for e in ("stCxn", "endCxn"))
        a, b = rects[st.get("id")], rects[en.get("id")]
        assert not pr._contrario(a, int(st.get("idx")), b), con.name  # ni sale por el lado contrario
        assert not pr._contrario(b, int(en.get("idx")), a), con.name  # ni entra por él


@pytest.mark.parametrize("x,motivo", [("B", "comparten tramo"), ("A", "se cruzan"),
                                      ("A", "pasa a menos de 80.000 EMU de la forma «SharePoint Online»")])
def test_los_pptx_de_i15_fallan(x, motivo):
    """Regresión: los PPTX empaquetados en I1.5 tenían ARR15-2 y la comprobación nueva lo ve."""
    from pptx import Presentation
    with zipfile.ZipFile(PAQUETES[x]) as z:
        nombre = next(n for n in z.namelist() if n.endswith("-Revision.pptx"))
        import io
        prs = Presentation(io.BytesIO(z.read(nombre)))
    assert any(motivo in f for f in pr.separacion_conectores(prs.slides[3]._element))


def test_total_de_conceptos_valorados():
    assert textos_cliente.etiquetas_total(False) == ("Total mensual", "Total anual")
    assert textos_cliente.etiquetas_total(True) == ("Total mensual (conceptos valorados)",
                                                    "Total anual (conceptos valorados)")
    prs, _ = pr.construir(_estado("B"), _catalogo())  # B deja Microsoft Foundry «No valorado»
    celdas = [c.text_frame.text for s in prs.slides[7].shapes if s.has_table for f in s.table.rows for c in f.cells]
    assert "Total mensual (conceptos valorados)" in celdas and "Total anual (conceptos valorados)" in celdas
    assert "No valorado" in celdas and "Total mensual" not in celdas
    assert any("A valorar con el volumen real" in c for c in celdas)  # el literal del comercial, intacto
