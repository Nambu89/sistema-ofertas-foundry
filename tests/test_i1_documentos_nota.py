"""Pruebas estructurales de la nota de revisión (DOCX interno, sin red). CONTRATOS.md §9.5, P9 y P12."""
from __future__ import annotations

import re
import zipfile

import pytest
from docx import Document
from lxml import etree

from tests.test_i1_documentos_comun import catalogo_ejemplo, estado_ejemplo, docs  # noqa: F401  (fixture)


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SECCIONES = ["1. Identificación", "2. Lista de comprobación del revisor", "3. Requisitos con su cita y origen",
             "4. Supuestos de confianza baja que hay que confirmar", "5. Verificación por elemento",
             "6. Riesgos residuales", "7. Resumen económico interno (no se envía al cliente)",
             "8. Ficheros del paquete", "9. Cómo decidir"]


def rehash(docs, estado: dict) -> dict:
    estado["hash_contenido"] = docs.hashes.hash_contenido(estado)
    return estado


def _generar(docs, tmp_path, estado=None):
    ruta = tmp_path / "OF-KELVARA-001-A-Nota-Revision.docx"
    sha = docs.nr.generar(estado or estado_ejemplo(), catalogo_ejemplo(), ruta)
    return ruta, sha


def _todo(docs, doc) -> str:
    return "\n".join(docs.nr.textos_docx(doc))


def test_secciones_en_orden_hash_y_propiedades(docs, tmp_path):
    ruta, sha = _generar(docs, tmp_path)
    assert sha == docs.hashes.sha256_fichero(ruta)
    doc = Document(str(ruta))
    titulos = [p.text for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert titulos == SECCIONES
    h = estado_ejemplo()["hash_contenido"]
    assert h in _todo(docs, doc)
    cp = doc.core_properties
    assert cp.keywords == f"hash_contenido:{h}" and cp.author == "Responsable comercial"
    assert cp.title == "OF-KELVARA-001-A · Nota de revisión" and cp.category == "Preventa"


def test_contenido_interno_horas_por_perfil_supuestos_y_lineas_de_decision(docs, tmp_path):
    ruta, _ = _generar(docs, tmp_path)
    texto = _todo(docs, Document(str(ruta)))
    assert "Project Manager" in texto and "28.025,25 €" in texto
    assert "39.00" not in texto  # I1.9 (VA18-9): horas en formato español
    assert "[BAJA] Volumetría" in texto and "[BAJA] Identidad y permisos del origen" in texto  # VA18-10
    assert "NO VERIFICABLE" in texto and "Procedencia A2A" in texto
    h = estado_ejemplo()["hash_contenido"]
    assert f"DECISION | Responsable de preventa | APROBADA | AAAA-MM-DD | {h} | comentarios" in texto
    assert f"DECISION | Responsable de área | APROBADA | AAAA-MM-DD | {h} | comentarios" in texto
    for clave in ("xlsx_estimacion", "anexo_xlsx", "anexo_json", "pptx"):
        assert estado_ejemplo()["artefactos"][clave]["sha256"] in texto


def test_montserrat_y_paleta_en_documento_estilos_y_tema(docs, tmp_path):
    ruta, _ = _generar(docs, tmp_path)
    with zipfile.ZipFile(ruta) as z:
        partes = {n: etree.fromstring(z.read(n)) for n in ("word/document.xml", "word/styles.xml")}
        tema = etree.fromstring(z.read("word/theme/theme1.xml"))
        fuentes = etree.fromstring(z.read("word/fontTable.xml"))
    for nombre, raiz in partes.items():
        for rf in raiz.iter(f"{{{W}}}rFonts"):
            assert {rf.get(f"{{{W}}}{a}") for a in ("ascii", "hAnsi", "eastAsia", "cs")} == {"Montserrat"}, nombre
        for el in raiz.iter():
            assert not [a for a in el.attrib if a.startswith(f"{{{W}}}") and "heme" in a], (nombre, el.tag)
            if el.tag == f"{{{W}}}color":
                assert el.get(f"{{{W}}}val").upper() in docs.pr.PALETA | {"AUTO"}, nombre
            for atributo in ("fill", "color"):
                valor = el.get(f"{{{W}}}{atributo}")
                if valor is not None and el.tag != f"{{{W}}}color":
                    assert valor.upper() in docs.pr.PALETA | {"AUTO"}, (nombre, el.tag, valor)
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    caras = {n.get("typeface") for n in tema.find(f".//{{{a}}}fontScheme").iter() if n.get("typeface") is not None}
    assert caras == {"Montserrat"}
    assert [f.get(f"{{{W}}}name") for f in fuentes] == ["Montserrat"]
    doc = Document(str(ruta))
    runs = [r for p in doc.paragraphs for r in p.runs] + [
        r for t in doc.tables for fila in t.rows for c in fila.cells for p in c.paragraphs for r in p.runs]
    assert runs and all(r.font.name == "Montserrat" for r in runs)


def test_marcador_en_prosa_del_verificador_se_retira_y_se_declara(docs, tmp_path):
    estado = estado_ejemplo()
    estado["carga"]["verificacion"]["respuesta"]["elementos"][0]["detalle"] = "Precio pendiente de confirmar <x>"
    rehash(docs, estado)
    ruta, _ = _generar(docs, tmp_path, estado)
    texto = _todo(docs, Document(str(ruta)))
    assert not re.search(r"\bpendiente\b", texto.lower()) and "<x>" not in texto  # palabra completa (LES-G-077)
    assert docs.nr.RETIRADO in texto
    assert "Texto retirado de la nota (detalle del verificador REF-01)" in texto


def test_cita_con_etiqueta_vtt_se_muestra_sin_la_etiqueta(docs, tmp_path):
    estado = estado_ejemplo()
    entrada = estado["carga"]["requisitos"]["campos"]["objetivo"]["entradas"][0]
    entrada["cita"] = "<v Ana Pérez>" + entrada["cita"] + "</v>"
    rehash(docs, estado)
    ruta, _ = _generar(docs, tmp_path, estado)
    texto = _todo(docs, Document(str(ruta)))
    assert "<v" not in texto and "</v>" not in texto
    assert entrada["cita"].replace("<v Ana Pérez>", "").replace("</v>", "") in texto


def test_hash_vencido_no_genera_nada(docs, tmp_path):
    estado = estado_ejemplo()
    estado["hash_contenido"] = "f" * 64
    with pytest.raises(docs.errores.IntegridadRota):
        _generar(docs, tmp_path, estado)
    assert not list(tmp_path.glob("*.docx"))


def test_sin_marcadores_en_todo_el_documento(docs, tmp_path):
    ruta, _ = _generar(docs, tmp_path)
    texto = _todo(docs, Document(str(ruta)))
    assert not re.search(r"\b(TBD|TODO|XXX|PLACEHOLDER)\b", texto)
    assert not re.search(r"<[^<>\n]{1,60}>", texto)
    assert not re.search(r"\b(pendientes?|por definir|lorem)\b", texto.lower())


def test_sin_miniatura_heredada_ni_app_xml_de_la_plantilla(docs, tmp_path):
    ruta, _ = _generar(docs, tmp_path)
    with zipfile.ZipFile(ruta) as z:
        assert not [n for n in z.namelist() if "thumbnail" in n]
        app = z.read("docProps/app.xml").decode("utf-8")
    assert "Macintosh" not in app and "Normal.dotm" not in app
