"""I1.5 · papel P: REVERIF14-2 (región de Azure exige catalogo_id), rechazo al registrar, y lo que ven el cliente
(anexo, diapositiva 8, riesgos) y el revisor (nota) de cada componente sin valorar. Sin red."""
from __future__ import annotations

import copy

import openpyxl
import pytest

from tests.test_i15_p_cobertura_precios import CAT, _comp, _ej, _errores, con_motivos
from nucleo import anexo_consumo as A, estado as est_mod, experto, pptx_revision, textos_cliente  # noqa: E402
from nucleo.errores import ReglaIncumplida  # noqa: E402


def _estado() -> dict:
    est = _ej("estado")
    con_motivos(est["carga"]["respuestas_expertos"]["azure"]["respuesta"])
    return est


def test_reverif14_2_la_evasion_con_nombre_de_saas_y_region_ya_no_pasa():
    """La sonda de REVERIF14-2: los facturables fuera del catálogo con nombre de SaaS, en su región y sin precios."""
    resp = con_motivos(_ej("respuesta_experto"))
    resp["precios"] = []
    for c in resp["componentes"]:
        if c["catalogo_id"] != "az-entra-id":
            c.update(catalogo_id=None, servicio=f"Bot de Microsoft Teams {c['id']}", motivo_no_valoracion="no_aplica",
                     desviacion_justificada="Bot publicado en el canal de Teams de la organización del cliente.")
    errores = _errores(resp)
    regionales = [c["id"] for c in resp["componentes"] if c["catalogo_id"] is None and c["region"] != "global"]
    assert regionales and all(any(e.startswith(f"componentes.{i}: región") and "REVERIF14-2" in e for e in errores)
                              for i in regionales), errores


def test_saas_fuera_del_catalogo_con_region_se_rechaza_con_el_remedio():
    """Caso real de E2E-B R2: «SharePoint in Microsoft 365» sin catalogo_id en westeurope."""
    comp = {"id": "C-06", "catalogo_id": None, "servicio": "SharePoint in Microsoft 365", "region": "westeurope"}
    motivo = experto.region_exige_catalogo(comp)
    assert motivo and "«global»" in motivo and "REVERIF14-2" in motivo
    assert experto.region_exige_catalogo({**comp, "region": "global"}) is None
    assert experto.region_exige_catalogo({**comp, "catalogo_id": "az-teams"}) is None


def test_residual_saas_global_sin_catalogo_se_acepta_y_el_revisor_lo_ve():
    """Residuo declarado: con nombre de SaaS y en «global» se acepta como SaaS, pero nunca en silencio."""
    resp = con_motivos(_ej("respuesta_experto"))
    _comp(resp, "C-03").update(catalogo_id=None, servicio="Bot de Microsoft Teams", region="global",
                               motivo_no_valoracion="no_aplica",
                               desviacion_justificada="Bot publicado en el canal de Teams de la organización.",
                               referencia_id="REF-01")  # integrador I1.7: en v4 los del catálogo van con null
    resp["precios"] = [p for p in resp["precios"] if p["componente_id"] != "C-03"]  # I1.6: sin su precio de referencia
    assert _errores(resp) == []
    sin = [x for x in A.clasificar_componentes(resp, CAT) if x["componente_id"] == "C-03"]
    assert A.MOTIVOS_NO_VALORACION["licencia_fuera_de_azure"] in A.motivos_para_revisor(sin)[0]  # I1.9: sin el código


def test_registrar_rechaza_sin_precio_ni_motivo_y_cuenta_un_intento_t2():
    est = _ej("estado")
    est["estado"], est["intentos"]["T2"], est["ronda_verificacion"] = "EN_ANALISIS", 0, 0  # brief R1 vigente
    est["carga"]["respuestas_expertos"] = {}
    resp = con_motivos(_ej("respuesta_experto"))
    resp["brief_id"] = est_mod.brief_vigente(est)["brief_id"]
    resp["brief_recibido"] = est_mod.brief_vigente(est)["texto"]
    _comp(resp, "C-03")["motivo_no_valoracion"] = "no_aplica"
    perfiles = est_mod.brief_vigente(est)["perfiles_permitidos"]
    with pytest.raises(ReglaIncumplida) as ex:
        i17 = __import__("tests.i17_int", fromlist=["x"])  # integrador I1.7: con la instantánea de su catálogo
        experto.registrar(est, "azure", __import__("json").dumps(resp), CAT, perfiles, i17.hoy_para(CAT),
                          instantanea=i17.instantanea_para(CAT))
    assert est["intentos"]["T2"] == 1 and any("C-03" in e and "PR15-2" in e for e in ex.value.errores), ex.value.errores


def test_el_anexo_dice_a_valorar_y_no_se_compone_sin_motivo(tmp_path):
    est = _estado()
    anexo, detalle = A._construir(est, CAT)
    avisos = [a for a in anexo["avisos"] if A.MOTIVO_A_VALORAR in a]
    assert [a.split(":")[0] for a in avisos] == ["Microsoft Foundry", "Azure AI Bot Service"]
    assert all("depende_del_volumen" not in a for a in anexo["avisos"])  # el motivo concreto no va al cliente
    ruta = tmp_path / "anexo.xlsx"
    A.generar_xlsx(anexo, ruta, detalle)
    celdas = [str(c.value) for fila in openpyxl.load_workbook(ruta).active.iter_rows() for c in fila if c.value]
    assert sum(1 for c in celdas if c.startswith(A.MOTIVO_A_VALORAR)) == 2
    _comp(est["carga"]["respuestas_expertos"]["azure"]["respuesta"], "C-01")["motivo_no_valoracion"] = "no_aplica"
    with pytest.raises(ReglaIncumplida) as ex:
        A.calcular(est, CAT)
    assert any(e.startswith("Anexo: C-01") and "PR15-2" in e for e in ex.value.errores)


def test_diapositiva_8_y_riesgos_dicen_a_valorar_con_el_volumen_real():
    sin = A.no_valorados(_estado(), CAT)
    filas = pptx_revision.filas_no_valoradas(sin)
    assert ["Microsoft Foundry y Azure AI Bot Service", A.MOTIVO_A_VALORAR, A.NO_VALORADO] in filas
    frases = [t for t, _, _ in textos_cliente._riesgos_consumo({"lineas": []}, sin)]
    frase = next(t for t in frases if "a valorar con el volumen real" in t)
    assert "Microsoft Foundry y Azure AI Bot Service" in frase and textos_cliente.barrer(frase, []) == []
    assert all(c not in t for t in frases for c in A.MOTIVOS_NO_VALORACION)


def test_la_nota_lista_cada_motivo(tmp_path):
    from tests.test_i1_documentos_comun import catalogo_ejemplo, entorno_documentos
    est = _estado()
    with entorno_documentos() as docs:
        est["hash_contenido"] = docs.hashes.hash_contenido(est)
        ruta = tmp_path / "OF-KELVARA-001-A-Nota-Revision.docx"
        docs.nr.generar(est, catalogo_ejemplo(), ruta)
        from docx import Document
        texto = "\n".join(docs.nr.textos_docx(Document(ruta)))
    from nucleo.anexo_consumo import MOTIVOS_NO_VALORACION as M  # I1.9 (VA18-10): la explicación, sin el código
    for servicio, cid in (("Microsoft Foundry", "C-01"), ("Azure AI Bot Service", "C-03")):
        assert f"Consumo sin valorar: {servicio} ({cid}): sin valorar; {M['depende_del_volumen']}" in texto
    assert f"Consumo sin valorar: Microsoft Entra ID (C-05): sin valorar; {M['licencia_fuera_de_azure']}" in texto
    assert "«depende_del_volumen»" not in texto and "«licencia_fuera_de_azure»" not in texto
