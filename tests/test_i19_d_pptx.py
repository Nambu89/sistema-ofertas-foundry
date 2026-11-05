"""I1.9 · D · PPTX: importes y presupuesto (VA18-1), legibilidad de los conectores (VA18-6) y sistemas del cliente
(PR18-8), sobre los PPTX publicados en la prueba real de I1.8 y los regenerados con el núcleo nuevo. Sin red."""
from __future__ import annotations

from lxml import etree

from tests.i19_d_datos import catalogo, contrato_i19_hostelia, estado_real, partes_publicadas, recomponer
from nucleo import errores, pptx_revision as pr  # noqa: E402

NS = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')


def _conector(nombre, x, y, cx, cy, flechas=("tailEnd",), prst="line", fh=False):
    extremos = "".join(f'<a:{e} type="triangle"/>' for e in flechas)
    voltea = ' flipH="1"' if fh else ""
    return (f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="9" name="{nombre}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
            f'<p:spPr><a:xfrm{voltea}><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="{prst}"><a:avLst/></a:prstGeom><a:ln>{extremos}</a:ln></p:spPr></p:cxnSp>')


def _arbol(*conectores):
    return etree.fromstring(f"<p:spTree {NS}>" + "".join(conectores) + "</p:spTree>")


def test_legibilidad_tramos_en_linea_aunque_haya_hueco():
    a = _conector("A", 0, 1000000, 1000000, 0)
    b = _conector("B", 3000000, 1030000, 1000000, 0)  # 2.000.000 de hueco a lo largo, 30.000 de lado
    assert any("misma línea" in f for f in pr.legibilidad_conectores(_arbol(a, b)))
    c = _conector("C", 3000000, 1100000, 1000000, 0)  # 100.000 de lado: paralelas, se distinguen
    assert pr.legibilidad_conectores(_arbol(a, c)) == []


def test_legibilidad_cruce_lejos_de_los_extremos_y_puntas_juntas():
    h = _conector("H", 0, 1000000, 2000000, 0)
    v = _conector("V", 1000000, 0, 0, 2000000)
    assert any("se cruzan" in f for f in pr.legibilidad_conectores(_arbol(h, v)))
    p1 = _conector("P1", 0, 0, 1000000, 0)
    p2 = _conector("P2", 1150000, 100000, 0, 500000, flechas=("headEnd",))  # su punta inicial, a 150.000
    assert any("puntas de flecha" in f for f in pr.legibilidad_conectores(_arbol(p1, p2)))


def test_legibilidad_falla_cerrado_con_geometria_que_no_sabe_leer():
    raro = _conector("R", 0, 0, 100, 100, prst="curvedConnector3")
    assert pr.legibilidad_conectores(_arbol(raro)) == ["el conector «R» tiene una geometría que no se puede comprobar"]


def test_la_diapositiva_4_publicada_de_brezalia_vb_se_detecta():
    """VA18-6: lo que vio el verificador (tramos en línea, puntas casi juntas y un cruce) en el PPTX publicado."""
    from tests.i18_d_datos import RAIZ  # noqa: F401  (rutas)
    import io
    from pptx import Presentation
    partes = partes_publicadas("brezalia_lista_B")
    datos = io.BytesIO()
    import zipfile
    with zipfile.ZipFile(datos, "w") as zf:
        for n, b in partes.items():
            zf.writestr(n, b)
    halla = pr.legibilidad_conectores(Presentation(io.BytesIO(datos.getvalue())).slides[3]._element)
    assert any("misma línea" in f for f in halla)
    assert any("se cruzan" in f for f in halla)
    assert any("puntas de flecha" in f for f in halla)


def test_brezalia_final_regenerada_se_dibuja_legible_y_con_la_identidad_hacia_entra():
    estado = recomponer(estado_real("brezalia_final"))
    prs, informe = pr.construir(estado, catalogo())
    assert informe == {"modo": "diagrama", "fallos": []}
    d4 = prs.slides[3]
    assert pr.legibilidad_conectores(d4._element) == [] == pr.separacion_conectores(d4._element)
    entra = next(s for s in d4.shapes if s.has_text_frame and s.text_frame.text == "Microsoft Entra ID").shape_id
    for c in [s for s in d4.shapes if s.name.startswith("Flujo ")]:
        st, en = c._element.find(".//" + pr.qn("a:stCxn")), c._element.find(".//" + pr.qn("a:endCxn"))
        assert st.get("id") != str(entra), "ninguna flecha sale de Microsoft Entra ID"
    assert sum(1 for c in d4.shapes if c.name.startswith("Flujo ")
               and c._element.find(".//" + pr.qn("a:endCxn")).get("id") == str(entra)) == 2


def test_va18_1_hostelia_publicada_lo_llevaba_y_la_regenerada_no():
    estado = estado_real("hostelia_lista_A")
    halla = pr.importes_no_permitidos(partes_publicadas("hostelia_lista_A"), estado)
    assert any("diapositiva 6" in h and "60.000" in h for h in halla)
    assert any("presupuesto orientativo" in h for h in halla)
    nuevo = recomponer(estado)
    assert pr.importes_no_permitidos(pr.partes_de(pr.construir(nuevo, catalogo())[0]), nuevo) == []


def test_va18_1_construir_no_publica_un_importe_que_no_es_el_precio():
    estado = estado_real("hostelia_lista_A")
    estado = recomponer(estado)
    estado["carga"]["textos_cliente"]["riesgos"][0]["texto"] = "El API Management cuesta 173,45 € al mes."
    from nucleo import hashes
    estado["hash_contenido"] = hashes.hash_contenido(estado)
    try:
        pr.construir(estado, catalogo())
    except errores.ReglaIncumplida as e:
        assert any("173,45" in x for x in e.errores)
    else:
        raise AssertionError("se publicó un importe que no es el precio cerrado ni un hito")


def test_sistemas_del_cliente_dibujados_aparte():
    estado = recomponer(contrato_i19_hostelia(estado_real("hostelia_lista_A")))
    prs, informe = pr.construir(estado, catalogo())
    assert informe["modo"] == "diagrama"
    cajas = {" ".join(x.text for x in s.text_frame.paragraphs): s for s in prs.slides[3].shapes
             if s.name.startswith("Componente ")}
    api = cajas["API REST de RR. HH. (sistema del cliente)"]
    assert api.line._get_or_add_ln().find(pr.qn("a:prstDash")).get("val") == "dash"
    assert api.fill.fore_color.rgb == pr._rgb(pr.BANDA)
    assert cajas["Azure App Service"].line._get_or_add_ln().find(pr.qn("a:prstDash")) is None


def test_comprobar_textos_exige_el_nombre_del_sistema_del_cliente():
    estado = recomponer(contrato_i19_hostelia(estado_real("hostelia_lista_A")))
    for capa in estado["carga"]["textos_cliente"]["arquitectura"]["capas"]:
        for k in capa["componentes"]:
            if k["id"] == "C-06":
                k["nombre"] = "Azure API Management"
    from nucleo import hashes
    estado["hash_contenido"] = hashes.hash_contenido(estado)
    try:
        pr.comprobar_textos(estado, catalogo())
    except errores.IntegridadRota as e:
        assert any("sistema del cliente" in x for x in e.errores)
    else:
        raise AssertionError("se aceptó un sistema del cliente con el nombre de uno propuesto")


def _api_fuera_del_catalogo(existente=True, catalogo_id=None):
    """Hostelia con la API de RR. HH. como recurso del cliente FUERA del catálogo (contrato v5 de P: `referencia_id`
    null solo para él, sku «Del cliente», región «global»)."""
    estado = contrato_i19_hostelia(estado_real("hostelia_lista_A"))
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    api = next(c for c in resp["componentes"] if c["id"] == "C-09")
    api.update(catalogo_id=catalogo_id, servicio="API REST de RR. HH. del cliente", referencia_id=None,
               sku="Del cliente", region="global")
    if not existente:
        api.update(existente_del_cliente=None, motivo_no_valoracion=None)
    return estado


def test_sistema_del_cliente_fuera_del_catalogo_sin_pagina_de_learn():
    """Cierre D (I1.9): sin página de Learn no rompe la composición; se llama por el valor citado, no por el servicio
    que escribió el modelo, y el pie no la busca."""
    estado = recomponer(_api_fuera_del_catalogo())
    nombres = [k["nombre"] for c in estado["carga"]["textos_cliente"]["arquitectura"]["capas"] for k in c["componentes"]]
    assert "API REST de RR. HH. (sistema del cliente)" in nombres
    prs, informe = pr.construir(estado, catalogo())
    assert informe["modo"] == "diagrama"
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    assert pr.referencias_faltan(prs.slides[3]._element, resp) == []


def test_sin_pagina_solo_para_un_sistema_del_cliente_fuera_del_catalogo():
    """Control: la misma falta de referencia en un componente propuesto, o en uno del catálogo, sigue fallando."""
    for estado in (_api_fuera_del_catalogo(existente=False), _api_fuera_del_catalogo(catalogo_id="az-app-service")):
        try:
            recomponer(estado)
        except errores.IntegridadRota as e:
            assert "referencia_id" in str(e)
        else:
            raise AssertionError("se aceptó un componente sin página de Learn que no es un sistema del cliente")
    estado = recomponer(_api_fuera_del_catalogo())
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    diapo = pr.construir(estado, catalogo())[0].slides[3]._element
    next(c for c in resp["componentes"] if c["id"] == "C-09")["existente_del_cliente"] = None
    assert any("C-09" in f for f in pr.referencias_faltan(diapo, resp))


def test_cierre_presupuesto_en_formato_ingles_lo_ven_nucleo_y_replica():
    """Cierre D (16-10, Revisión 6): con el alta en formato inglés («60,000.00»), la cifra «60.000» que llevaba la
    diapositiva 6 publicada de Hostelia se reconoce como del presupuesto, en el núcleo y en la réplica (§2.1)."""
    from tests.test_i19_d_replicas import replica
    estado = estado_real("hostelia_lista_A")
    estado["carga"]["requisitos"]["campos"]["presupuesto_orientativo"]["entradas"][0]["valor"] = "Up to 60,000.00"
    partes = partes_publicadas("hostelia_lista_A")
    halla = pr.importes_no_permitidos(partes, estado)
    assert any("cifra «60.000» del presupuesto" in h for h in halla)
    assert replica("importes_no_permitidos")[1](partes, estado) == halla

def test_cierre_presupuesto_en_texto_alternativo_y_disenos_lo_ven_nucleo_y_replica():
    """Cierre D (16-10, Revisión 7): el presupuesto del alta sin moneda en el texto alternativo de una forma o en un
    párrafo de un diseño (superficies de VPROT-1) también se detecta, en el núcleo y en la réplica (§2.1)."""
    from tests.test_i19_d_replicas import replica
    estado = estado_real("hostelia_lista_A")
    estado["carga"]["requisitos"]["campos"]["presupuesto_orientativo"]["entradas"][0]["valor"] = "Up to 120,000"
    nuevo = recomponer(estado)
    limpio = pr.partes_de(pr.construir(nuevo, catalogo())[0])
    assert pr.importes_no_permitidos(limpio, nuevo) == replica("importes_no_permitidos")[1](limpio, nuevo) == []
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    alt = dict(limpio)
    raiz = etree.fromstring(alt["ppt/slides/slide1.xml"])
    next(raiz.iter(f"{p_}cNvPr")).set("descr", "Presupuesto orientativo: 120,000")
    alt["ppt/slides/slide1.xml"] = etree.tostring(raiz)
    halla = pr.importes_no_permitidos(alt, nuevo)
    assert any(h.startswith("texto alternativo (ppt/slides/slide1.xml)") and "presupuesto" in h for h in halla)
    assert replica("importes_no_permitidos")[1](alt, nuevo) == halla
    disenos = sorted(n for n in limpio if n.startswith("ppt/slideLayouts/slideLayout") and n.endswith(".xml"))
    diseno = dict(limpio)
    raiz = etree.fromstring(diseno[disenos[0]])
    cuerpo = next(raiz.iter(f"{p_}spTree"))
    forma = etree.SubElement(cuerpo, f"{p_}sp")
    txt = etree.SubElement(etree.SubElement(etree.SubElement(forma, f"{p_}txBody"), f"{a_}p"), f"{a_}r")
    etree.SubElement(txt, f"{a_}t").text = "Margen disponible 120.000"
    diseno[disenos[0]] = etree.tostring(raiz)
    halla = pr.importes_no_permitidos(diseno, nuevo)
    assert any(h.startswith(f"diseño o patrón ({disenos[0]})") and "120.000" in h for h in halla)
    assert replica("importes_no_permitidos")[1](diseno, nuevo) == halla
