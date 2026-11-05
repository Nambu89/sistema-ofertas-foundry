"""I1.8 · D · VER17-2: ningún PPTX lleva texto de la revisión interna (pptx_revision.revision_interna_en_pptx), con la
lista blanca de la firma de la diapositiva 2 y de las propiedades. Sobre el PPTX real publicado en I1.7 (que lo llevaba)
y sobre el que genera el núcleo nuevo con los mismos estados. Sin red."""
from __future__ import annotations

import copy

import pytest
from pptx.util import Emu

from tests.i18_d_datos import COMENTARIO_D002, catalogo, estado_real, partes_publicadas
from nucleo import decision, pptx_revision as pr  # noqa: E402


@pytest.fixture(scope="module")
def generados():
    """{caso: (estado, prs)} con el núcleo nuevo."""
    salida = {}
    for caso in ("lista_B", "aprobada_B"):
        estado = estado_real(caso)
        salida[caso] = (estado, pr.construir(estado, catalogo())[0])
    return salida


def _otra(estado):
    """Presentación nueva del mismo estado, para modificarla sin tocar la del módulo."""
    return pr.construir(estado, catalogo())[0]


def _hallazgos(prs, estado):
    return pr.revision_interna_en_pptx(pr.partes_de(prs), estado, catalogo())


@pytest.mark.parametrize("caso", ["lista_B", "aprobada_B"])
def test_el_pptx_publicado_en_i17_lo_llevaba_y_se_detecta(caso):
    halla = "\n".join(pr.revision_interna_en_pptx(partes_publicadas(caso), estado_real(caso), catalogo()))
    assert "diapositiva 2: comentario de la decisión D-002" in halla
    assert "nombre de quien decide «responsable de preventa»" in halla
    assert "id de decisión" in halla and "marcador de la revisión «cambios pedidos»" in halla
    assert "«calculadas por el codigo»" in halla and "identificador del catálogo" in halla


@pytest.mark.parametrize("caso", ["lista_B", "aprobada_B"])
def test_el_nucleo_nuevo_no_lleva_nada_de_la_revision(generados, caso):
    estado, prs = generados[caso]
    assert _hallazgos(prs, estado) == []
    publicado = " ".join(t for _, t in pr.textos_pptx(prs))
    assert decision.TITULO_CAMBIOS not in publicado and "Comentario de" not in publicado
    assert len(prs.slides) == 10 and not hasattr(pr, "tam_cambios")


def test_firmas_de_la_diapositiva_2_admitidas_y_el_nombre_fuera_no(generados):
    estado, prs = generados["aprobada_B"]
    celdas = [c.text for f in prs.slides[1].shapes if f.has_table for fila in f.table.rows for c in fila.cells]
    assert "Responsable de preventa, 2026-10-13" in celdas and "Responsable de área, 2026-10-13" in celdas
    prs = _otra(estado)
    pr.texto(prs.slides[8], Emu(500000), Emu(5000000), Emu(6000000), Emu(300000), "Revisado con Responsable de preventa", 10)
    assert any("diapositiva 9: nombre de quien decide «responsable de preventa»" in h for h in _hallazgos(prs, estado))


def test_firma_en_otra_celda_o_con_texto_de_mas_no_se_admite(generados):
    estado, prs = generados["aprobada_B"]
    prs = _otra(estado)
    tabla = next(f for f in prs.slides[1].shapes if f.has_table).table
    tabla.cell(1, 3).text = "Responsable de preventa, 2026-10-13: devuelta por el almacenamiento"
    tabla.cell(1, 1).text = "Responsable de área, 2026-10-13"
    halla = "\n".join(_hallazgos(prs, estado))
    assert "«responsable de preventa»" in halla and "«responsable de area»" in halla


def test_propiedades_solo_admiten_al_firmante_y_la_huella(generados):
    estado, prs = generados["lista_B"]
    prs = _otra(estado)
    assert prs.core_properties.author == "Responsable comercial" and _hallazgos(prs, estado) == []
    prs.core_properties.subject = "Devuelta por Responsable de preventa"
    prs.core_properties.keywords = "hash_contenido:abc · catalogo_id"
    halla = "\n".join(_hallazgos(prs, estado))
    assert "propiedad subject: nombre de quien decide" in halla and "propiedad keywords: nombre de campo interno" in halla


def test_lo_que_el_revisor_cita_entre_comillas_no_cuenta(generados):
    estado, prs = generados["lista_B"]
    estado = copy.deepcopy(estado)
    supuesto = next(t for d, t in pr.textos_pptx(prs) if d == "diapositiva 6" and t.startswith("El almacenamiento"))
    estado["decisiones"][1]["comentarios"] = f"Revisad «{supuesto}»"
    assert _hallazgos(prs, estado) == []
    estado["decisiones"][1]["comentarios"] = f"Revisad esto: {supuesto}"  # sin comillas: es texto de la revisión
    assert any("comentario de la decisión D-002" in h for h in _hallazgos(prs, estado))


def test_un_tramo_del_comentario_partido_en_dos_parrafos_se_detecta(generados):
    estado, prs = generados["lista_B"]
    prs = _otra(estado)
    mitad = COMENTARIO_D002.index("no es")
    pr.texto(prs.slides[8], Emu(500000), Emu(5000000), Emu(9000000), Emu(600000),
             [COMENTARIO_D002[:mitad], COMENTARIO_D002[mitad:]], 10)
    assert any("diapositiva 9: comentario de la decisión D-002" in h for h in _hallazgos(prs, estado))


@pytest.mark.parametrize("texto, motivo", [
    ("Cómo se atendió: se añade Storage", "«como se atendio»"),
    ("Ver la nota del revisor", "«nota del revisor»"),
    ("Servicio az-app-service · p0v3-linux", "identificador del catálogo"),
    ("Plantilla hot-lrs-datos", "identificador del catálogo «hot-lrs-datos»"),
    ("Versión A DEVUELTA (D-002)", "id de decisión"),
    ("Coste calculado por el código", "«calculado por el codigo»"),
])
def test_marcadores_internos(generados, texto, motivo):
    estado, prs = generados["lista_B"]
    prs = _otra(estado)
    pr.texto(prs.slides[9], Emu(500000), Emu(5000000), Emu(9000000), Emu(300000), texto, 10)
    assert any(h.startswith("diapositiva 10:") and motivo in h for h in _hallazgos(prs, estado)), texto


def test_las_url_de_learn_no_se_miran_por_identificadores(generados):
    estado, prs = generados["lista_B"]
    prs = _otra(estado)
    pr.texto(prs.slides[9], Emu(500000), Emu(5000000), Emu(9000000), Emu(300000),
             "https://learn.microsoft.com/azure/app-service/az-app-service-hot-lrs-datos", 10)
    assert _hallazgos(prs, estado) == []


def test_rol_del_firmante_entero_si_y_sus_palabras_sueltas_no(generados):
    """Quien firma se nombra por su rol. El rol entero («Responsable de área», «Responsable comercial») no sale al
    cliente; sus palabras sueltas o por pares («responsable de», «de preventa») son corrientes y no cuentan."""
    estado, _ = generados["lista_B"]
    prs = _otra(estado)
    pr.texto(prs.slides[8], Emu(500000), Emu(5000000), Emu(9000000), Emu(600000),
             ["Lo pidió el Responsable de área en la revisión", "Según el responsable comercial"], 10)
    halla = "\n".join(_hallazgos(prs, estado))
    assert "«responsable de area»" in halla and "«responsable comercial»" in halla, halla
    prs = _otra(estado)
    pr.texto(prs.slides[8], Emu(500000), Emu(5000000), Emu(9000000), Emu(300000),
             "El responsable de RR. HH. valida los datos de preventa del área comercial", 10)
    assert _hallazgos(prs, estado) == []


def test_salto_de_linea_dentro_del_parrafo_separa_palabras(generados):
    """Revisión (I1.8): un a:br entre runs no pega las palabras y el comentario sigue encontrándose."""
    estado, _ = generados["lista_B"]
    prs = _otra(estado)
    caja = pr.texto(prs.slides[8], Emu(500000), Emu(5000000), Emu(9000000), Emu(600000), "x", 10)
    parrafo = caja.text_frame.paragraphs[0]
    corte = COMENTARIO_D002.index(" ", 40)  # el salto sustituye al espacio: sin él, las dos palabras se pegarían
    parrafo.runs[0].text = COMENTARIO_D002[:corte]
    parrafo.add_line_break()
    parrafo.add_run().text = COMENTARIO_D002[corte + 1:]
    assert any("diapositiva 9: comentario de la decisión D-002" in h for h in _hallazgos(prs, estado))
