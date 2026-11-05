"""I1.7 · D · Diapositiva 4: la página de cada componente en el pie sin que el diagrama caiga a la tabla (REVERIF16-3),
comprobación de que ninguna falta, lectura robusta de los números del XML (D16-5) y distancia a la forma propia tras
salir de ella (REV16-5). Sin red ni PowerPoint (los PNG se miran aparte: pruebas/I17/D/)."""
from __future__ import annotations

import copy

import pytest
from lxml import etree

from tests.i17_d_datos import catalogo, esquema_propuesto, estado_flujo, recomponer
from nucleo import errores, pptx_revision as pr  # noqa: E402

NS = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')


@pytest.fixture(autouse=True)
def _esquema(monkeypatch):
    esquema_propuesto(monkeypatch)


@pytest.mark.parametrize("caso", ["B1", "B2", "A"])
def test_flujos_reales_diagrama_y_todas_las_referencias(caso):
    estado = recomponer(estado_flujo(caso))
    prs, informe = pr.construir(estado, catalogo())
    assert informe == {"modo": "diagrama", "fallos": []}
    d4 = prs.slides[3]._element
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    assert pr.referencias_faltan(d4, resp) == []
    assert pr.cortes_conectores(d4) == [] and pr.separacion_conectores(d4) == []
    textos4 = [t for d, t in pr.textos_pptx(prs) if d == "diapositiva 4"]
    assert pr.TITULO_REFERENCIAS in textos4
    if caso == "B1":  # REVERIF16-3: SharePoint con su propia página, no con la de Microsoft 365
        assert any(t.startswith("SharePoint Online: https://learn.microsoft.com/office365/") for t in textos4)
        assert any(t.startswith("Microsoft 365: https://learn.microsoft.com/microsoft-365/") for t in textos4)


def _sin_parrafo(prs, contiene):
    for sp in prs.slides[3]._element.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}sp"):
        for p in sp.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}p"):
            if contiene in "".join(t.text or "" for t in p.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")):
                p.getparent().remove(p)
                return


def test_referencias_faltan_detecta_cada_ausencia():
    estado = recomponer(estado_flujo("B1"))
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    prs, _ = pr.construir(estado, catalogo())
    _sin_parrafo(prs, "SharePoint Online: ")
    fallos = pr.referencias_faltan(prs.slides[3]._element, resp)
    assert len(fallos) == 1 and "componente C-03" in fallos[0]
    sin_ref = copy.deepcopy(resp)
    sin_ref["componentes"][0]["referencia_id"] = "REF-99"
    assert any("no tiene una referencia" in f for f in pr.referencias_faltan(prs.slides[3]._element, sin_ref))
    vacia = etree.fromstring(f"<p:spTree {NS}/>")
    assert "no tiene el pie" in pr.referencias_faltan(vacia, resp)[0]
    assert pr.referencias_faltan(etree.fromstring(f"<p:sld {NS}/>"), resp)[0].startswith("la diapositiva no tiene árbol")


def test_construir_no_publica_si_falta_una_referencia(monkeypatch):
    estado = recomponer(estado_flujo("A"))
    monkeypatch.setattr(pr, "texto_referencia", lambda r: str(r["titulo"]))  # sin URL: el pie las pierde todas
    with pytest.raises(errores.ReglaIncumplida, match="falta la página") as e:
        pr.construir(estado, catalogo())
    assert len(e.value.errores) == 7  # una por componente de A


def test_plan_del_pie():
    pocas = ["Azure AI Search: https://learn.microsoft.com/azure/search/search-what-is-azure-search"] * 3
    assert (pr.plan_pie(pocas, 3, 1)["columnas"], pr.plan_pie(pocas, 3, 1)["tam"]) == (1, 9)
    una = pr.plan_pie(pocas[:1], 5, 2)
    assert una["columnas"] == 1  # una sola referencia nunca va en una columna estrecha
    largas = [f"Componente {i}: https://learn.microsoft.com/azure/architecture/" + "x" * 90 for i in range(15)]
    plan = pr.plan_pie(largas, 5, 2)  # no cabe con las medidas base: la opción que más sitio deja al diagrama
    assert pr.alto_necesario(5, 2, pr.MEDIDAS_BASE) > plan["alto_dib"] and (plan["columnas"], plan["tam"]) == (1, 8)
    assert sum(len(g) for g in plan["grupos"]) == 15 and [x for g in plan["grupos"] for x in g] == largas
    assert pr.lineas_referencia("A: " + "u" * 200, 140) == 1 + 2


def _arbol(cuerpo):
    return etree.fromstring(f'<p:spTree {NS}><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/>'
                            f'</p:nvGrpSpPr><p:grpSpPr/>{cuerpo}</p:spTree>')


def _caja(i, nombre, x, y, cx="1000000", cy="500000"):
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{i}" name="Componente {i}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm>'
            f'<a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"/></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:p><a:r><a:t>{nombre}</a:t></a:r></a:p></p:txBody></p:sp>')


def _codo(adj1="val 50000", st=("2", "3"), en=("3", "1"), off=("1000000", "250000"), ext=("1000000", "1000000"),
          prst="bentConnector3"):
    return (f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="4" name="Flujo A-B"/><p:cNvCxnSpPr><a:stCxn id="{st[0]}" idx="{st[1]}"/>'
            f'<a:endCxn id="{en[0]}" idx="{en[1]}"/></p:cNvCxnSpPr><p:nvPr/></p:nvCxnSpPr><p:spPr><a:xfrm>'
            f'<a:off x="{off[0]}" y="{off[1]}"/><a:ext cx="{ext[0]}" cy="{ext[1]}"/></a:xfrm><a:prstGeom prst="{prst}">'
            f'<a:avLst><a:gd name="adj1" fmla="{adj1}"/></a:avLst></a:prstGeom></p:spPr></p:cxnSp>')


A_B = _caja(2, "A", 0, 0) + _caja(3, "B", 2000000, 1000000)


@pytest.mark.parametrize("fmla", ["val ５", "val --5", "val 1" + "0" * 5000, "val +5", "*/ w 1 2", "val", "val 1 2"])
def test_d16_5_ajuste_mal_formado_es_fallo_y_no_excepcion(fmla):
    arbol = _arbol(A_B + _codo(fmla))
    for comprobar in (pr.cortes_conectores, pr.separacion_conectores):
        fallos = comprobar(arbol)
        assert any("geometría que no se puede comprobar: un ajuste no es un valor entero fijo" in f for f in fallos), fallos


@pytest.mark.parametrize("valor", ["１２", "+5", "1_000", " 12", "9" * 13, "abc"])
def test_d16_5_posicion_mal_formada_es_fallo_y_no_excepcion(valor):
    arbol = _arbol(_caja(2, "A", valor, 0) + _caja(3, "B", 2000000, 1000000) + _codo())
    for comprobar in (pr.cortes_conectores, pr.separacion_conectores):
        assert any("no es un número entero" in f for f in comprobar(arbol))


def test_rev16_5_forma_propia_tras_salir_de_ella():
    # control: el codo vertical en mitad del hueco (x = 1.500.000), a 500.000 de A y de B
    assert pr.separacion_conectores(_arbol(A_B + _codo("val 50000"))) == []
    # el tramo vertical corre a 10.000 EMU del borde izquierdo de B durante 250.000 antes de entrar (sonda de I1.6)
    pegado = pr.separacion_conectores(_arbol(A_B + _codo("val 99000")))
    assert pegado == ["el conector «Flujo A-B» vuelve a pasar a menos de 80.000 EMU de su forma de destino «B» tras "
                      "salir de ella"]
    # lo mismo junto a su forma de origen: el codo a 10.000 EMU del borde derecho de A, de y = 250.000 a 500.000
    junto_a = pr.separacion_conectores(_arbol(A_B + _codo("val 1000")))
    assert junto_a == ["el conector «Flujo A-B» vuelve a pasar a menos de 80.000 EMU de su forma de origen «A» tras "
                       "salir de ella"]
    # la frontera exacta: a 80.000 vale, a 79.999 no
    assert pr.separacion_conectores(_arbol(A_B + _codo("val 92000"))) == []
    assert pr.separacion_conectores(_arbol(A_B + _codo("val 92001"))) != []


def test_rev16_5_conector_de_una_forma_consigo_misma_falla():
    bucle = _codo("val 50000", st=("2", "3"), en=("2", "1"), off=("0", "100000"), ext=("1000000", "300000"))
    assert any("consigo misma" in f for f in pr.separacion_conectores(_arbol(A_B + bucle)))


def test_rev16_5_recta_y_tramos_de_salida_y_entrada_exentos():
    apiladas = _caja(2, "A", 0, 0) + _caja(3, "B", 0, 1000000)
    recta = _codo("val 0", st=("2", "2"), en=("3", "0"), off=("500000", "500000"), ext=("0", "500000"), prst="line")
    assert pr.separacion_conectores(_arbol(apiladas + recta)) == []
    # en L (bentConnector2): sale por la derecha de A y entra por arriba de B, con la esquina a 500.000 de B
    ele = _codo("val 0", st=("2", "3"), en=("3", "0"), off=("1000000", "250000"), ext=("1500000", "750000"),
                prst="bentConnector2")
    assert pr.separacion_conectores(_arbol(A_B + ele)) == []
