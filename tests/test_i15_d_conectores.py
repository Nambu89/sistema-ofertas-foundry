"""I1.5 · D · PR14-3/VER14-7: los conectores del diagrama van por los huecos entre las formas y nunca cortan el
texto de ninguna; `cortes_conectores` lo comprueba de forma exacta sobre el XML (y la puerta lleva su réplica,
test_i15_d_replica_cortes.py). Sin red."""
from __future__ import annotations

import pathlib
import random
import sys

import pytest
from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.util import Emu

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import pptx_revision as pr  # noqa: E402

# El caso real de I1.4 (PRUEBA-REAL §5.1, diapositiva 4): nueve componentes y once flujos; con conectores rectos,
# tres cruzaban el texto de «Foundry Agent Service» y «Microsoft Foundry». I1.9 (VA18-6): sin cruces no tiene dibujo
# y cae a la tabla (test_i14_real_sin_cruces_cae_a_la_tabla); el caso real dibujable es ahora el de I1.8 (_real).
CAPAS_I14 = [("Microsoft Teams", "usuarios_canales"), ("Azure AI Bot Service", "usuarios_canales"),
              ("Azure App Service", "aplicacion_integracion"), ("Foundry Agent Service", "ia"),
              ("Microsoft Foundry", "ia"), ("Azure AI Search", "datos_conocimiento"),
              ("SharePoint Online", "datos_conocimiento"), ("Microsoft 365", "aplicacion_integracion"),
              ("Microsoft Entra ID", "identidad_seguridad_red")]
FLUJOS_I14 = [("C-01", "C-02"), ("C-02", "C-03"), ("C-03", "C-04"), ("C-04", "C-05"), ("C-04", "C-06"),
              ("C-07", "C-06"), ("C-08", "C-07"), ("C-09", "C-01"), ("C-09", "C-06"), ("C-06", "C-03"),
              ("C-03", "C-02")]
# Brezalia, versión B de la prueba real de I1.8 (VA18-6): ocho componentes, diez flujos, dos de vuelta y la identidad
# con la convención fija «servicio → Microsoft Entra ID»
CAPAS_REAL = [("Microsoft Teams", "usuarios_canales"), ("Azure AI Bot Service", "usuarios_canales"),
              ("Azure App Service", "aplicacion_integracion"), ("SharePoint Online", "datos_conocimiento"),
              ("Azure AI Search", "datos_conocimiento"), ("Microsoft Foundry", "ia"),
              ("Microsoft Entra ID", "identidad_seguridad_red"), ("Azure Blob Storage", "datos_conocimiento")]
FLUJOS_REAL = [("C-01", "C-02"), ("C-02", "C-03"), ("C-03", "C-05"), ("C-05", "C-03"), ("C-03", "C-06"),
               ("C-06", "C-03"), ("C-04", "C-05"), ("C-04", "C-08"), ("C-03", "C-07"), ("C-05", "C-07")]


def _caso(capas, flujos):
    comps = [{"id": f"C-{i:02d}", "nombre": n, "capa": c} for i, (n, c) in enumerate(capas, start=1)]
    return comps, [{"origen": o, "destino": d} for o, d in flujos]


def _real():
    return _caso(CAPAS_REAL, FLUJOS_REAL)


def _dibujar(comps, flujos, alto=3470000):
    prs = Presentation()
    prs.slide_width, prs.slide_height = pr.ANCHO, pr.ALTO
    diapo = prs.slides.add_slide(prs.slide_layouts[6])
    dib = pr.dibujar_diagrama(diapo, comps, flujos, pr.MARGEN, Emu(1200000), pr.ANCHO_UTIL, Emu(alto))
    return diapo, dib


def test_caso_real_sin_cortes_y_con_conectores_en_codo():
    comps, flujos = _real()
    diapo, dib = _dibujar(comps, flujos)
    assert pr.comprobar_dibujo(dib, comps, flujos) == []
    assert pr.cortes_conectores(diapo.shapes._spTree) == []
    assert pr.separacion_conectores(diapo.shapes._spTree) == []  # I1.6: ARR15-2/D15-4
    assert pr.legibilidad_conectores(diapo.shapes._spTree) == []  # I1.9: VA18-6
    tipos = [c._element.spPr.find(pr.qn("a:prstGeom")).get("prst") for c in dib["conectores"]]
    assert set(tipos) <= {"line", "bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5"}
    assert any(t.startswith("bent") for t in tipos)  # los que antes cruzaban ahora rodean
    for con, flujo in zip(dib["conectores"], flujos):  # pegados a sus dos formas
        st, en = con._element.find(".//" + pr.qn("a:stCxn")), con._element.find(".//" + pr.qn("a:endCxn"))
        assert (st.get("id"), en.get("id")) == (str(dib["formas"][flujo["origen"]].shape_id),
                                                str(dib["formas"][flujo["destino"]].shape_id))


def test_i14_real_sin_cruces_cae_a_la_tabla():
    """VA18-6 (I1.9): el caso de I1.4 solo se dibujaba cruzando conectores; sin salto dibujado, cae a la tabla y lo
    único que falla es el camino que no existe (y el conector provisional de ese flujo), nunca un cruce publicado."""
    comps, flujos = _caso(CAPAS_I14, FLUJOS_I14)
    _, dib = _dibujar(comps, flujos)
    fallos = pr.comprobar_dibujo(dib, comps, flujos)
    sin = {f"«Flujo {k}»" for k, f in enumerate(flujos, 1) if f"{f['origen']} → {f['destino']}" in dib["sin_camino"]}
    assert dib["sin_camino"] and any("camino" in f for f in fallos)
    assert all("camino" in f or any(n in f for n in sin) for f in fallos), fallos


def test_determinista():
    """La diapositiva entera (formas, conectores y su orden) sale igual byte a byte en dos dibujos: la puerta
    compara el PPTX con una recomposición local (revisión independiente: antes solo se comparaban los conectores)."""
    comps, flujos = _real()
    a = etree.tostring(_dibujar(comps, flujos)[0].shapes._spTree)
    b = etree.tostring(_dibujar(comps, flujos)[0].shapes._spTree)
    assert a == b


def test_el_conector_recto_de_antes_daba_corte():
    """Regresión: el trazado recto de I1.4 de App Service a AI Search corta «Foundry Agent Service»."""
    comps, _ = _caso(CAPAS_I14, FLUJOS_I14)
    diapo, dib = _dibujar(comps, [])
    con = diapo.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 0, 0, 0, 0)
    con.begin_connect(dib["formas"]["C-03"], 3)
    con.end_connect(dib["formas"]["C-06"], 1)
    assert any("Foundry Agent Service" in f for f in pr.cortes_conectores(diapo.shapes._spTree))


@pytest.mark.parametrize("puntos", [
    [(0, 0), (500000, 0), (500000, 300000)],                                       # H, V
    [(0, 0), (0, 300000), (500000, 300000)],                                       # V, H (primer tramo nulo)
    [(0, 0), (200000, 0), (200000, 300000), (500000, 300000)],                     # H, V, H
    [(500000, 300000), (300000, 300000), (300000, 0), (0, 0)],                     # volteado en los dos ejes
    [(0, 0), (0, -200000), (400000, -200000), (400000, 300000)],                   # V, H, V que sale hacia atrás
    [(0, 0), (-90000, 0), (-90000, 700000), (600000, 700000), (600000, 300000)],   # H, V, H, V
    [(0, 0), (90000, 0), (90000, -50000), (700000, -50000), (700000, 300000), (800000, 300000)],  # 5 tramos
])
def test_codos_dibujan_la_polilinea(puntos):
    prs = Presentation()
    diapo = prs.slides.add_slide(prs.slide_layouts[6])
    con = diapo.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 0, 0, 0, 0)
    desplazados = [(x + 2000000, y + 2000000) for x, y in puntos]
    pr._trazado_codos(con, desplazados)
    caja = diapo.shapes.add_textbox(Emu(1), Emu(1), Emu(2), Emu(2))  # una forma con texto lejos: sin cortes
    caja.text_frame.text = "x"
    assert pr.cortes_conectores(diapo.shapes._spTree) == []
    # una forma con texto justo encima de cada tramo intermedio: la comprobación la ve cortada
    for (ax, ay), (bx, by) in zip(desplazados, desplazados[1:]):
        mx, my = (ax + bx) // 2, (ay + by) // 2
        sonda = diapo.shapes.add_textbox(Emu(mx - 120000), Emu(my - 80000), Emu(240000), Emu(160000))
        sonda.text_frame.text = "sonda"
        assert any("sonda" in f for f in pr.cortes_conectores(diapo.shapes._spTree)), (puntos, (ax, ay), (bx, by))
        sonda._element.getparent().remove(sonda._element)


def test_dibujable_cuenta_tramos_y_la_u_se_empuja():
    """I1.6 (D15-4): un camino en U (ancho o alto nulo) ya se dibuja desplazando el extremo final EMPUJE EMU;
    solo cuenta el número de tramos. Abierto por COM sin problema (una nota de trabajo no publicada)."""
    assert pr.dibujable((0, 0), (10, 0), False, 1)
    assert pr.dibujable((0, 0), (0, 10), False, 3)              # U con ancho nulo: se empuja
    assert not pr.dibujable((0, 0), (10, 10), True, 5)         # empezar en vertical gasta un tramo
    assert not pr.dibujable((0, 0), (10, 10), False, 6)
    u = [(0, 0), (300000, 0), (300000, 500000), (0, 500000)]   # H, V, H de vuelta al mismo x
    prst, ajustes, fh, fv, (x, y, ancho, alto) = pr._codos(u)
    assert (prst, ancho, alto) == ("bentConnector3", pr.EMPUJE, 500000)
    assert ajustes == [300000 * 100000 // pr.EMPUJE] and all(abs(a) < 2 ** 31 for a in ajustes)
    assert pr._empujar(u)[-1] == (pr.EMPUJE, 500000)             # se acorta el último tramo: queda fuera
    v = [(0, 0), (0, 200000), (400000, 200000), (400000, 0)]    # V, H, V de vuelta al mismo y
    assert pr._empujar(v)[-1] == (400000, pr.EMPUJE)
    with pytest.raises(Exception):
        pr._codos([(0, 0), (5, 0), (5, 10), (8, 10), (8, 20), (12, 20), (12, 30)])  # 6 tramos


def _sp(xml_cuerpo: str) -> etree._Element:
    ns = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" ' \
         'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    return etree.fromstring(f"<p:spTree {ns}>{xml_cuerpo}</p:spTree>")


FORMA = ('<p:sp><p:nvSpPr><p:cNvPr id="2" name="Caja"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm>'
         '<a:off x="1000" y="1000"/><a:ext cx="1000" cy="400"/></a:xfrm></p:spPr><p:txBody><a:bodyPr lIns="0" '
         'tIns="0" rIns="0" bIns="0"/><a:p><a:r><a:t>Texto</a:t></a:r></a:p></p:txBody></p:sp>')


def _cxn(prst="line", off=(0, 1200), ext=(3000, 0), extra="", av=""):
    return (f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="9" name="Flujo 1"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm {extra}><a:off x="{off[0]}" y="{off[1]}"/><a:ext cx="{ext[0]}" cy="{ext[1]}"/></a:xfrm>'
            f'<a:prstGeom prst="{prst}"><a:avLst>{av}</a:avLst></a:prstGeom></p:spPr></p:cxnSp>')


def test_cortes_casos_fijos():
    assert pr.cortes_conectores(_sp(FORMA + _cxn())) == ['el conector «Flujo 1» corta el texto de la forma «Texto»']
    assert pr.cortes_conectores(_sp(FORMA + _cxn(off=(0, 1400)))) == []            # justo por el borde: no corta
    assert pr.cortes_conectores(_sp(FORMA + _cxn(off=(0, 900)))) == []             # por encima
    # codo que rodea la caja por abajo: H hasta x=500, V hasta y=1800 y H hasta 3000 (bentConnector3, adj1 = 1/6)
    rodea = _cxn("bentConnector3", off=(0, 1200), ext=(3000, 600), av='<a:gd name="adj1" fmla="val 16667"/>')
    assert pr.cortes_conectores(_sp(FORMA + rodea)) == []
    corta = _cxn("bentConnector3", off=(0, 1200), ext=(3000, 600))               # adj1 por defecto: x=1500
    assert pr.cortes_conectores(_sp(FORMA + corta)) == ['el conector «Flujo 1» corta el texto de la forma «Texto»']
    por_fuera = _cxn("bentConnector2", off=(0, 900), ext=(3000, 1000))           # H por encima y V a la derecha
    assert pr.cortes_conectores(_sp(FORMA + por_fuera)) == []
    volteado = _cxn("bentConnector2", off=(0, 900), ext=(3000, 1000), extra='flipH="1"')  # H por y=900 y V por x=0
    assert pr.cortes_conectores(_sp(FORMA + volteado)) == []
    girado = _cxn(extra='rot="5400000"')
    assert any("girada" in f for f in pr.cortes_conectores(_sp(FORMA + girado)))
    curvo = _cxn("curvedConnector3")
    assert any("geometría" in f for f in pr.cortes_conectores(_sp(FORMA + curvo)))
    formula = _cxn("bentConnector3", av='<a:gd name="adj1" fmla="*/ w 1 2"/>')
    assert any("geometría" in f for f in pr.cortes_conectores(_sp(FORMA + formula)))
    grupo = '<p:grpSp><p:nvGrpSpPr><p:cNvPr id="5" name="Grupo"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr></p:grpSp>'
    assert any("grupo" in f for f in pr.cortes_conectores(_sp(FORMA + grupo)))
    libre = _cxn().replace('<a:prstGeom prst="line"><a:avLst></a:avLst></a:prstGeom>',
                           '<a:custGeom><a:pathLst><a:path w="1" h="1"><a:moveTo><a:pt x="0" y="0"/></a:moveTo>'
                           '</a:path></a:pathLst></a:custGeom>')
    assert any("geometría" in f for f in pr.cortes_conectores(_sp(FORMA + libre)))
    mal = _cxn().replace('cx="3000"', 'cx="3000.5"')                          # revisión independiente: fallo, no excepción
    assert any("no es un número entero" in f for f in pr.cortes_conectores(_sp(FORMA + mal)))
    margen_raro = FORMA.replace('lIns="0"', 'lIns="cero"')
    assert any("no es un número entero" in f for f in pr.cortes_conectores(_sp(margen_raro + _cxn())))
    sin_texto = FORMA.replace("<a:t>Texto</a:t>", "<a:t></a:t>")
    assert pr.cortes_conectores(_sp(sin_texto + _cxn())) == []                     # sin texto no hay nada que cortar


def test_aleatoria_diagramas_con_flujos():
    """Diagramas y flujos al azar: o se dibujan sin un solo corte o caen a la tabla con su motivo; nunca un
    diagrama con un conector sobre un texto. Exige una tasa mínima de diagramas dibujados (LES-G-099.5)."""
    azar = random.Random(1511)
    capas = list(pr.CAPAS_COLUMNA) + list(pr.CAPAS_BANDA)
    dibujados = 0
    casos = 40
    for _ in range(casos):
        comps = []
        for capa in capas:
            for _ in range(azar.randint(0, 3 if capa in pr.CAPAS_COLUMNA else 2)):
                comps.append({"id": f"C-{len(comps) + 1:02d}", "nombre": f"Servicio {len(comps) + 1}", "capa": capa})
        if len(comps) < 2:
            continue
        pares = {(a["id"], b["id"]) for a in comps for b in comps if a is not b}
        flujos = [{"origen": o, "destino": d} for o, d in azar.sample(sorted(pares), min(len(pares), azar.randint(1, 10)))]
        diapo, dib = _dibujar(comps, flujos)
        fallos = pr.comprobar_dibujo(dib, comps, flujos)
        if not fallos:
            dibujados += 1
            assert pr.cortes_conectores(diapo.shapes._spTree) == []
            assert pr.separacion_conectores(diapo.shapes._spTree) == []
            assert pr.legibilidad_conectores(diapo.shapes._spTree) == []  # I1.9: VA18-6
        else:  # I1.6: lo único que puede fallar es el conector recto provisional de un flujo sin camino
            sin = {f"«Flujo {k}»" for k, f in enumerate(flujos, 1)
                   if f"{f['origen']} → {f['destino']}" in dib["sin_camino"]}
            assert all("camino" in f or "cabe" in f or any(n in f for n in sin) for f in fallos), fallos
            assert any("camino" in f or "cabe" in f for f in fallos), fallos
    # I1.6: 38 de 40 con la semilla 1511; I1.9 (VA18-6, sin cruces ni tramos alineados): 30 de 40, el resto a la tabla
    assert dibujados >= 30, dibujados
