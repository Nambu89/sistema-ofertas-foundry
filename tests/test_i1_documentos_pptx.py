"""Pruebas estructurales del PPTX de revisión (sin red). CONTRATOS.md §9.1-§9.3, P8, P10 y P12."""
from __future__ import annotations

import re
import zipfile

import pytest
from lxml import etree
from pptx import Presentation

from tests.test_i1_documentos_comun import catalogo_ejemplo, docs  # noqa: F401  (fixture)
from tests.test_i1_documentos_comun import estado_ejemplo as _estado_ejemplo_base


def estado_ejemplo() -> dict:
    """I1.9 (VA18-1, LES-G-097.1): el ejemplo de esquemas/ejemplos trae «Precio cerrado de 28025.25 EUR» (formato
    inglés, anterior a la composición por código) y el núcleo ya no publica un PPTX con un importe sin lectura española.
    Se usa con el texto que compone hoy `textos_cliente._condiciones` y la huella recalculada (CAMBIOS-I19-D §5)."""
    from nucleo import hashes
    estado = _estado_ejemplo_base()
    for f in estado["carga"]["textos_cliente"]["condiciones"]:
        f["texto"] = f["texto"].replace("28025.25 EUR", "28.025,25 €")
    estado["hash_contenido"] = hashes.hash_contenido(estado)
    return estado


NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
PERFILES = ["AI Architect / Tech Lead", "Senior AI / Foundry Engineer", "AI Engineer / Tech Lead",
            "Project Manager", "Consultor Junior"]


def rehash(docs, estado: dict) -> dict:
    estado["hash_contenido"] = docs.hashes.hash_contenido(estado)
    return estado


@pytest.fixture()
def generado(tmp_path, docs):
    ruta = tmp_path / "OF-KELVARA-001-A-Revision.pptx"
    sha = docs.pr.generar(estado_ejemplo(), catalogo_ejemplo(), ruta)
    return ruta, sha


def _xml_diapositivas(ruta) -> list[bytes]:
    with zipfile.ZipFile(ruta) as z:
        nombres = sorted(n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n))
        return [z.read(n) for n in nombres]


def _texto(diapo) -> list[str]:
    salida = []
    for forma in diapo.shapes:
        if forma.has_text_frame:
            salida += [p.text for p in forma.text_frame.paragraphs if p.text]
        if forma.has_table:
            salida += [c.text for fila in forma.table.rows for c in fila.cells if c.text]
    return salida


def test_diez_diapositivas_16_9_en_orden(docs, generado):
    ruta, sha = generado
    prs = Presentation(str(ruta))
    assert sha == docs.hashes.sha256_fichero(ruta)
    assert (prs.slide_width, prs.slide_height) == (12192000, 6858000)
    assert len(prs.slides) == 10 == len(docs.pr.DIAPOSITIVAS)
    estado = estado_ejemplo()
    assert estado["carga"]["textos_cliente"]["portada"]["titulo"] in _texto(prs.slides[0])
    for i, diapo in enumerate(list(prs.slides)[1:], start=1):
        assert _texto(diapo)[0] == docs.pr.DIAPOSITIVAS[i]


def test_montserrat_en_cada_fragmento_y_en_el_tema(docs, generado):
    ruta, _ = generado
    for xml in _xml_diapositivas(ruta):
        raiz = etree.fromstring(xml)
        rprs = raiz.findall(".//a:rPr", NS) + raiz.findall(".//a:endParaRPr", NS)
        assert rprs
        for rpr in rprs:
            for etiqueta in ("latin", "ea", "cs"):
                nodo = rpr.find(f"a:{etiqueta}", NS)
                assert nodo is not None and nodo.get("typeface") == "Montserrat"
        caras = {n.get("typeface") for etiqueta in ("latin", "ea", "cs", "sym")
                 for n in raiz.iter("{%s}%s" % (NS["a"], etiqueta))}
        assert caras == {"Montserrat"}  # también defRPr u otros portadores de fuente, si los hubiera
    with zipfile.ZipFile(ruta) as z:
        tema = etree.fromstring(z.read("ppt/theme/theme1.xml"))
    caras = {n.get("typeface") for n in tema.find(".//a:fontScheme", NS).iter() if n.get("typeface") is not None}
    assert caras == {"Montserrat"}


def test_solo_colores_de_la_paleta_sin_tema_ni_sombras(docs, generado):
    ruta, _ = generado
    for xml in _xml_diapositivas(ruta):
        raiz = etree.fromstring(xml)
        colores = {n.get("val").upper() for n in raiz.iter("{%s}srgbClr" % NS["a"])}
        assert colores and colores <= docs.pr.PALETA
        for otro in ("schemeClr", "sysClr", "prstClr", "scrgbClr", "hslClr"):
            assert raiz.find(f".//a:{otro}", NS) is None, otro  # solo srgbClr de la paleta
        assert raiz.find(".//p:style", NS) is None
        assert raiz.find(".//a:outerShdw", NS) is None and raiz.find(".//a:tableStyleId", NS) is None
    with zipfile.ZipFile(ruta) as z:
        tema = etree.fromstring(z.read("ppt/theme/theme1.xml"))
    esquema = tema.find(".//a:clrScheme", NS)
    assert {n.get("val") for n in esquema.iter("{%s}srgbClr" % NS["a"])} <= docs.pr.PALETA
    assert esquema.find(".//a:sysClr", NS) is None


def test_sin_horas_jornadas_perfiles_tarifas_ni_identificadores(docs, generado):
    ruta, _ = generado
    prs = Presentation(str(ruta))
    hash_vigente = estado_ejemplo()["hash_contenido"]
    for n, diapo in enumerate(prs.slides, start=1):
        for t in _texto(diapo):
            if n == 2 and t == hash_vigente:
                continue
            bajo = t.lower()
            assert not re.search(r"\b\d+([.,]\d+)?\s*(h|horas?)\b", bajo), t
            for prohibida in ("jornada", "tarifa", "€/h", "eur/h", "contingencia", "ajuste comercial", "días-persona"):
                assert prohibida not in bajo, t
            for perfil in PERFILES:
                assert perfil.lower() not in bajo, t
            assert not re.search(r"\b(REF|RG|BRF|CNS|R|C|P|T|S)-\d", t), t
            assert not re.search(r"\b[a-z]+_[a-z_]+\b", t) and "@" not in t, t
            assert not re.search(r"<[^<>\n]{1,60}>", t), t


def test_una_forma_por_componente_y_un_conector_pegado_por_flujo(docs, generado):
    ruta, _ = generado
    prs = Presentation(str(ruta))
    textos = estado_ejemplo()["carga"]["textos_cliente"]
    componentes = docs.pr.componentes_de(textos)
    flujos = textos["arquitectura"]["flujos"]
    diapo = prs.slides[3]
    formas = [f for f in diapo.shapes if f.name.startswith("Componente ")]
    assert sorted(f.text_frame.text for f in formas) == sorted(c["nombre"] for c in componentes)
    por_nombre = {f.text_frame.text: f.shape_id for f in formas}
    nombre_de = {c["id"]: c["nombre"] for c in componentes}
    conectores = [f for f in diapo.shapes if f.name.startswith("Flujo ")]
    assert len(conectores) == len(flujos)
    pares = set()
    for con in conectores:
        st, en = con._element.find(".//a:stCxn", NS), con._element.find(".//a:endCxn", NS)
        assert st is not None and en is not None
        assert con._element.find(".//p:txBody", NS) is None  # sin texto
        pares.add((int(st.get("id")), int(en.get("id"))))
    assert pares == {(por_nombre[nombre_de[f["origen"]]], por_nombre[nombre_de[f["destino"]]]) for f in flujos}
    assert docs.pr.AVISO_TABLA not in _texto(diapo)
    assert any("learn.microsoft.com" in t for t in _texto(diapo))


def test_hash_solo_en_diapositiva_2_y_propiedades(docs, generado):
    ruta, _ = generado
    prs = Presentation(str(ruta))
    estado = estado_ejemplo()
    h = estado["hash_contenido"]
    donde = [n for n, d in enumerate(prs.slides, start=1) if any(h in t for t in _texto(d))]
    assert donde == [2]
    cp = prs.core_properties
    assert cp.keywords == f"hash_contenido:{h}"
    assert cp.title == "OF-KELVARA-001-A · Propuesta para revisión"
    assert cp.author == cp.last_modified_by == "Responsable comercial"
    assert cp.subject == estado["carga"]["alta"]["titulo"] and cp.category == "Preventa" and cp.comments == ""
    assert all(not d.has_notes_slide for d in prs.slides)
    with zipfile.ZipFile(ruta) as z:
        assert not [n for n in z.namelist() if "comment" in n.lower() or "notesSlide" in n]


def test_diapositiva_2_sale_de_las_decisiones_sin_tocar_el_contenido(docs, tmp_path):
    estado = estado_ejemplo()
    antes = docs.hashes.hash_contenido(estado)
    estado["decisiones"] = [{
        "id": "D-001", "revisor": "Responsable de preventa", "tipo": "APROBADA", "fecha": "2026-10-09",
        "hash_citado": antes, "comentarios": "Revisado.", "version": "A", "estado_antes": "EN_REVISION_PREVENTA",
        "estado_despues": "EN_APROBACION_AREA", "registrada_ts": "2026-10-09T09:15:00+02:00",
        "linea": f"DECISION | Responsable de preventa | APROBADA | 2026-10-09 | {antes} | Revisado."}]
    estado["estado"] = "EN_APROBACION_AREA"
    assert docs.hashes.hash_contenido(estado) == antes
    ruta = tmp_path / "x.pptx"
    docs.pr.generar(estado, catalogo_ejemplo(), ruta)
    textos = _texto(Presentation(str(ruta)).slides[1])
    assert "Responsable comercial (RC)" in textos
    assert any(t.startswith("Responsable de preventa") and "2026-10-09" in t for t in textos)
    assert textos.count("Sin firma") == 1


def test_diagrama_completo_casos(docs):
    base = [{"id": "C-01", "nombre": "Microsoft Foundry", "capa": "ia"},
            {"id": "C-02", "nombre": "Azure AI Search", "capa": "datos_conocimiento"}]
    assert docs.pr.diagrama_completo(base, [{"origen": "C-01", "destino": "C-02"}])
    assert not docs.pr.diagrama_completo([], [])
    assert not docs.pr.diagrama_completo(base, [{"origen": "C-01", "destino": "C-09"}])
    assert not docs.pr.diagrama_completo(base, [{"origen": "C-01", "destino": "C-01"}])
    assert not docs.pr.diagrama_completo(base, [{"origen": "C-01", "destino": "C-02"}] * 2)
    assert not docs.pr.diagrama_completo(base + [{"id": "C-01", "nombre": "Otro", "capa": "ia"}], [])
    assert not docs.pr.diagrama_completo([{"id": "C-01", "nombre": "", "capa": "ia"}], [])
    assert not docs.pr.diagrama_completo([{"id": "C-01", "nombre": "X1", "capa": "otra"}], [])
    seis = [{"id": f"C-{i:02d}", "nombre": f"Servicio {i}", "capa": "ia"} for i in range(1, 7)]
    assert not docs.pr.diagrama_completo(seis, [])


def test_cae_a_tabla_con_aviso_si_el_diagrama_no_se_completa(docs, tmp_path, monkeypatch):
    monkeypatch.setattr(docs.pr, "diagrama_completo", lambda componentes, flujos: False)
    ruta = tmp_path / "x.pptx"
    docs.pr.generar(estado_ejemplo(), catalogo_ejemplo(), ruta)
    diapo = Presentation(str(ruta)).slides[3]
    textos = _texto(diapo)
    assert docs.pr.AVISO_TABLA in textos
    assert not [f for f in diapo.shapes if f.name.startswith(("Componente ", "Flujo "))]
    for comp in docs.pr.componentes_de(estado_ejemplo()["carga"]["textos_cliente"]):
        assert comp["nombre"] in textos


def test_cae_a_tabla_si_el_recuento_del_dibujo_falla(docs, tmp_path, monkeypatch):
    monkeypatch.setattr(docs.pr, "comprobar_dibujo", lambda dibujo, componentes, flujos: ["forzado"])
    prs, informe = docs.pr.construir(estado_ejemplo(), catalogo_ejemplo())
    assert informe == {"modo": "tabla", "fallos": ["forzado"]}
    diapo = prs.slides[3]
    assert docs.pr.AVISO_TABLA in _texto(diapo)
    assert not [f for f in diapo.shapes if f.name.startswith(("Componente ", "Flujo "))]


def test_integridad_rota_sin_textos_o_con_hechos_cambiados(docs, tmp_path):
    estado = estado_ejemplo()
    estado["carga"]["textos_cliente"] = None
    rehash(docs, estado)
    with pytest.raises(docs.errores.IntegridadRota):
        docs.pr.generar(estado, catalogo_ejemplo(), tmp_path / "a.pptx")
    estado = estado_ejemplo()
    estado["carga"]["estimacion"]["resumen"]["precio_cerrado_eur"] = "99999.99"
    rehash(docs, estado)
    with pytest.raises(docs.errores.IntegridadRota) as exc:
        docs.pr.generar(estado, catalogo_ejemplo(), tmp_path / "b.pptx")
    assert any("hash_hechos" in e for e in exc.value.errores)
    estado = estado_ejemplo()
    estado["hash_contenido"] = "0" * 64
    with pytest.raises(docs.errores.IntegridadRota):
        docs.pr.generar(estado, catalogo_ejemplo(), tmp_path / "c.pptx")
    assert not list(tmp_path.glob("*.pptx"))


def test_nombre_que_no_es_el_oficial_del_catalogo(docs, tmp_path):
    estado = estado_ejemplo()
    estado["carga"]["textos_cliente"]["arquitectura"]["capas"][2]["componentes"][0]["nombre"] = "az foundry"
    rehash(docs, estado)
    with pytest.raises(docs.errores.IntegridadRota) as exc:
        docs.pr.generar(estado, catalogo_ejemplo(), tmp_path / "a.pptx")
    assert any("LES-G-093" in e for e in exc.value.errores)


def test_barrido_final_impide_publicar_un_perfil_o_un_marcador(docs, tmp_path):
    for intruso in ("Coordina el Project Manager del proyecto.", "Plazo por definir con el cliente."):
        estado = estado_ejemplo()
        estado["carga"]["textos_cliente"]["riesgos"][0]["texto"] = intruso
        rehash(docs, estado)
        with pytest.raises(docs.errores.ReglaIncumplida) as exc:
            docs.pr.generar(estado, catalogo_ejemplo(), tmp_path / "a.pptx")
        assert exc.value.errores
        assert not (tmp_path / "a.pptx").exists()


def test_formato_eur(docs):
    assert docs.pr.formato_eur("17852.50") == "17.852,50 €"
    assert docs.pr.formato_eur("4463.125") == "4.463,13 €"
    assert docs.pr.formato_eur("0") == "0,00 €"
    assert docs.pr.formato_eur("-1500.00") == "-1.500,00 €"
    assert docs.pr.formato_eur("1234567.8") == "1.234.567,80 €"
    with pytest.raises(docs.errores.IntegridadRota):
        docs.pr.formato_eur("abc")


def test_sin_miniatura_heredada_y_app_xml_16_9(docs, generado):
    ruta, _ = generado
    with zipfile.ZipFile(ruta) as z:
        assert not [n for n in z.namelist() if "thumbnail" in n]
        app = z.read("docProps/app.xml").decode("utf-8")
    assert "Panorámica (16:9)" in app and "<Slides>10</Slides>" in app
    assert "4:3" not in app and "Macintosh" not in app
