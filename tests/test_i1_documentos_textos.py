"""Pruebas de lo que ve el cliente tras I1 (H8, H9, H10, H13) y de las observaciones en la nota.

Con los módulos reales del núcleo y el catálogo y la tarifa montados. Sin red.
"""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest
from pptx import Presentation

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import anexo_consumo, errores, hashes, nota_revision, pptx_revision, textos_cliente  # noqa: E402

EJ = RAIZ / "esquemas" / "ejemplos"


def _json(ruta: pathlib.Path):
    return json.loads(ruta.read_text(encoding="utf-8"))


@pytest.fixture()
def catalogo() -> dict:
    return _json(RAIZ / "sandbox" / "datos" / "catalogo_componentes.json")


@pytest.fixture()
def tarifa() -> dict:
    return _json(RAIZ / "tests" / "insumos" / "rate-card.sintetica.json")


def recomponer(est: dict, catalogo: dict, tarifa: dict) -> dict:
    """Anexo y textos recalculados por el código, y hash_contenido resellado (como hace la CLI)."""
    est["carga"]["anexo_consumo"] = anexo_consumo.calcular(est, catalogo)
    est["carga"]["textos_cliente"] = textos_cliente.componer(est, catalogo, tarifa)
    est["hash_contenido"] = hashes.hash_contenido(est)
    return est


@pytest.fixture()
def estado(catalogo, tarifa) -> dict:
    return recomponer(_json(EJ / "estado.json"), catalogo, tarifa)


def _frases(t: dict, clave: str) -> list[str]:
    return [f["texto"] for f in t[clave]]


def test_h8_usuarios_y_marco_en_vinetas_aparte(estado):
    nec = _frases(estado["carga"]["textos_cliente"], "necesidad")
    usuarios = [x for x in nec if x.startswith("Usuarios finales: ")]
    marco = [x for x in nec if x.startswith("Marco normativo: ")]
    assert len(usuarios) == 1 and len(marco) == 1
    assert not any(" en Los " in x or ".;" in x or "; marco normativo" in x for x in nec)
    assert all(x.endswith(".") and not x.endswith("..") for x in nec)


def test_frase_final_no_deja_puntuacion_colgando():
    assert textos_cliente._frase_final("ninguno fuera.") == "ninguno fuera."
    assert textos_cliente._frase_final("dato con punto y coma;  ") == "dato con punto y coma."


@pytest.mark.parametrize("texto, interno", [
    ("El precio de Azure Cosmos DB NO VERIFICADO en Azure Retail Prices.", True),
    ("El componente no verificable por falta de fuente.", True),
    ("Los precios no verificados se revisarán.", True),
    ("Las citas deben ser verificables en el documento original.", False),
    ("Se publica una API REST conforme al RGPD UE.", False),
    ("La red privada se valida con el cliente.", False),
])
def test_h10_redaccion_interna(texto, interno):
    assert bool(textos_cliente.redaccion_interna(texto)) is interno


def test_h10_sin_repeticiones_ni_estado_interno(estado, catalogo, tarifa):
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    resp["supuestos"][0]["texto"] = "El precio de Azure AI Search NO VERIFICADO en Azure Retail Prices."
    t = recomponer(estado, catalogo, tarifa)["carga"]["textos_cliente"]
    supuestos, riesgos = _frases(t, "supuestos"), _frases(t, "riesgos")
    assert not set(supuestos) & set(riesgos)
    assert not any(r.startswith("Supuesto sin confirmar") for r in riesgos)
    publicado = [x for _, x in textos_cliente._todas(t)]
    assert not any(textos_cliente.redaccion_interna(x) for x in publicado)
    motivos = {x["origen"]: x["motivo"] for x in t["excluidas"]}
    assert "redacción interna" in motivos[f"experto {resp['supuestos'][0]['id']}"]
    asumidos = [s for s in t["supuestos"] if any(h.startswith("R-") for h in s["hechos"])]
    assert asumidos and all(s["texto"].startswith("Dato por confirmar con el cliente sobre ") and s["nivel"] == "Confianza baja"
                            for s in asumidos)


def test_h9_no_valorados_con_motivo(estado, catalogo):
    nv = anexo_consumo.no_valorados(estado, catalogo)
    por_id = {x["componente_id"]: x for x in nv}
    con_precio = {p["componente_id"] for p in estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["precios"]
                  if p.get("cantidad_mensual") is not None}  # I1.6: un precio de referencia no cubre
    assert por_id and not set(por_id) & con_precio
    # REV13-3: Entra ID es SaaS que se licencia aparte; ya no es «no publica su precio»
    assert por_id["C-05"] == {"componente_id": "C-05", "servicio": "Microsoft Entra ID",
                              "motivo": anexo_consumo.MOTIVO_SAAS, "facturable": False,
                              "motivo_no_valoracion": "licencia_fuera_de_azure"}
    assert por_id["C-01"]["motivo"] == anexo_consumo.MOTIVO_A_VALORAR  # I1.5, PR15-2: declara depende_del_volumen
    avisos = estado["carga"]["anexo_consumo"]["avisos"]
    assert all(anexo_consumo.aviso_no_valorado(x) in avisos for x in nv)
    riesgos = _frases(estado["carga"]["textos_cliente"], "riesgos")
    assert any(r.startswith("El consumo de Microsoft Foundry") and "a valorar con el volumen real" in r
               for r in riesgos)
    assert "Microsoft Entra ID se licencia aparte, no se factura por Azure y no suma en el total orientativo " \
           "del anexo." in riesgos
    assert not any(r.startswith("Azure Retail Prices no publica un precio de consumo para Microsoft Entra ID")
                   for r in riesgos)
    # integrador I1.7 (decisión 1): el verificador ya no recibe precios; ningún riesgo dice que no se comprobó un precio
    assert not any(r.startswith("No se ha podido comprobar de forma independiente el precio de ") for r in riesgos)


def test_h9_desviacion_y_catalogo_ajeno(estado, catalogo):
    comp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["componentes"][0]
    comp["catalogo_id"], comp["servicio"] = None, "Servicio de ejemplo fuera del catálogo"
    assert anexo_consumo.no_valorados(estado, catalogo)[0]["servicio"] == "Servicio de ejemplo fuera del catálogo"
    comp["catalogo_id"] = "az-no-existe"
    with pytest.raises(errores.IntegridadRota):
        anexo_consumo.no_valorados(estado, catalogo)


def _textos_diapo(diapo) -> list[str]:
    salida = []
    for forma in diapo.shapes:
        if forma.has_text_frame:  # sin la viñeta dibujada
            salida += [p.text.removeprefix("• ") for p in forma.text_frame.paragraphs if p.text]
        if forma.has_table:
            salida += [" | ".join(c.text for c in fila.cells) for fila in forma.table.rows]
    return salida


def _pptx(estado: dict, catalogo: dict, tmp_path) -> list[list[str]]:
    ruta = tmp_path / f"{estado['estado']}.pptx"
    pptx_revision.generar(estado, catalogo, ruta)
    return [_textos_diapo(d) for d in Presentation(str(ruta)).slides]


def _aprobar(estado: dict) -> dict:
    h = estado["hash_contenido"]
    estado["decisiones"] = [
        {"id": f"D-00{i}", "revisor": quien, "tipo": "APROBADA", "fecha": "2026-10-09", "hash_citado": h,
         "comentarios": "Revisado y conforme.", "version": "A", "estado_antes": antes, "estado_despues": despues,
         "registrada_ts": "2026-10-09T09:15:00+02:00",
         "linea": f"DECISION | {quien} | APROBADA | 2026-10-09 | {h} | Revisado y conforme."}
        for i, (quien, antes, despues) in enumerate((("Responsable de preventa", "EN_REVISION_PREVENTA", "EN_APROBACION_AREA"),
                                                      ("Responsable de área", "EN_APROBACION_AREA", "APROBADA")), 1)]
    estado["estado"] = "APROBADA"
    assert hashes.hash_contenido(estado) == h
    return estado


def test_h13_portada_y_pie_segun_el_estado(estado, catalogo, tmp_path):
    estado["estado"] = "LISTA_PARA_REVISION"
    borrador = _pptx(estado, catalogo, tmp_path)
    assert "Propuesta para revisión interna · versión A" in borrador[0]
    aprobada = _pptx(_aprobar(copy.deepcopy(estado)), catalogo, tmp_path)
    assert "Propuesta comercial · versión A" in aprobada[0]
    assert not any("revisión interna" in t for d in aprobada for t in d)
    pie = pptx_revision.pie(estado["carga"]["textos_cliente"])
    assert pie == "OF-KELVARA-001-A · " + estado["carga"]["alta"]["cliente"]
    assert all(pie in d for d in borrador[1:]) and all(pie in d for d in aprobada[1:])
    # solo cambian la portada y las firmas: el resto de diapositivas, idénticas
    assert borrador[2:] == aprobada[2:]


def test_h8_h9_h10_en_las_diapositivas(estado, catalogo, tmp_path):
    d = _pptx(estado, catalogo, tmp_path)
    assert sum(t.startswith("Usuarios finales: ") for t in d[2]) == 1
    assert sum(t.startswith("Marco normativo: ") for t in d[2]) == 1
    filas8 = [t for t in d[7] if " | " in t]
    # REV13-3: una fila «No valorado» por motivo, con sus servicios («A y B»), y ningún servicio sin fila
    nv = anexo_consumo.no_valorados(estado, catalogo)
    for fila in pptx_revision.filas_no_valoradas(nv):
        assert " | ".join(fila) in filas8
    for x in nv:
        assert any(t.startswith(x["servicio"]) or f", {x['servicio']}" in t.split(" | ")[0]
                   or f" y {x['servicio']}" in t.split(" | ")[0] for t in filas8 if t.endswith("| No valorado"))
    mensual, _ = textos_cliente.etiquetas_total(bool(nv))  # I1.6 (D): «(conceptos valorados)» si hay no valorados
    assert filas8.index(f"{mensual} |  | " + pptx_revision.formato_eur(
        estado["carga"]["anexo_consumo"]["total_mensual_eur"])) == len(filas8) - 2
    supuestos = {t.split(" | ")[0] for t in d[5] if " | " in t}
    assert not supuestos & set(d[8])
    assert not any("NO VERIFICADO" in t or "Supuesto sin confirmar" in t for x in d for t in x)


def _nota(estado: dict, catalogo: dict, tmp_path) -> str:
    from docx import Document
    ruta = tmp_path / "nota.docx"
    nota_revision.generar(estado, catalogo, ruta)
    return "\n".join(nota_revision.textos_docx(Document(str(ruta))))


def test_nota_muestra_observaciones_y_lo_no_valorado(estado, catalogo, tmp_path):
    texto = _nota(estado, catalogo, tmp_path)
    assert "El verificador no ha hecho observaciones editoriales." in texto
    assert "sin valorar: " in texto and "Microsoft Entra ID" in texto
    estado["carga"]["verificacion"]["observaciones"] = [
        {"id": "S-02", "detalle": "La frase repite la idea del supuesto anterior.", "propuesta": "Unir las dos."}]
    elementos = estado["carga"]["verificacion"]["respuesta"]["elementos"]
    elementos.append({"id": "RG-01", "tipo": "riesgo", "veredicto": "OBSERVACION", "detalle": "Falta el verbo.",
                      "valor_correcto": None, "fuente_url": None})
    estado["hash_contenido"] = hashes.hash_contenido(estado)
    obs = nota_revision.observaciones_de(estado)
    assert [o["id"] for o in obs] == ["S-02", "RG-01"] and obs[0]["propuesta"] == "Unir las dos."
    estado["carga"]["verificacion"]["observaciones"][0]["texto_original"] = "Texto observado de ejemplo."
    estado["hash_contenido"] = hashes.hash_contenido(estado)
    texto = _nota(estado, catalogo, tmp_path)
    assert "La frase repite la idea del supuesto anterior." in texto and "Unir las dos." in texto
    assert "Falta el verbo." in texto and "OBSERVACIÓN (no bloquea)" in texto
    assert "Texto observado de ejemplo." in texto


def test_observaciones_forma_tolerante():
    est = {"carga": {"verificacion": {"resultado": {"observaciones": [
        {"elemento_id": "S-01", "texto": "Concordancia."}, "Texto suelto.", 7, {"id": "S-02"}]}}}}
    assert nota_revision.observaciones_de(est) == [
        {"id": "S-01", "texto": "", "detalle": "Concordancia.", "propuesta": ""},
        {"id": "—", "texto": "", "detalle": "Texto suelto.", "propuesta": ""}]


def test_observaciones_con_la_forma_de_v():
    """Forma que deja verificacion.registrar: el elemento con su texto original y la propuesta."""
    obs = {"id": "S-03", "tipo": "supuesto", "veredicto": "OBSERVACION", "valor_correcto": "Se asume que …",
           "fuente_url": None, "detalle": "Falta el verbo principal.", "texto_original": "Documentos en SharePoint",
           "motivo": "observación editorial o de regla: no bloquea; para la nota del revisor"}
    est = {"carga": {"verificacion": {"observaciones": [obs], "respuesta": {"elementos": [dict(obs)]}}}}
    assert nota_revision.observaciones_de(est) == [{"id": "S-03", "texto": "Documentos en SharePoint",
                                                    "detalle": "Falta el verbo principal.",
                                                    "propuesta": "Se asume que …"}]


@pytest.mark.parametrize("v, es", [("OBSERVACION", True), ("Observación", True), (" observacion ", True),
                                   ("OK", False), (None, False)])
def test_observacion_con_o_sin_tilde(v, es):
    assert nota_revision.es_observacion(v) is es
