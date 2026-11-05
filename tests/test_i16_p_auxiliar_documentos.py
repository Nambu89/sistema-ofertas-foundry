"""I1.6 · papel P: precio auxiliar atado a su componente (REV15-1, REV15-3), anexo sin los precios de referencia y nota
del revisor con factores, niveles, referencias y conceptos sustituidos (decisión 4). Sin red."""
from __future__ import annotations

import copy
import json
import sys

import pytest

from tests import i16_p_datos as D
from tests.test_i16_p_volumen import CAT, _b_corregida, _c, _p

for _x in (D.RAIZ / "sandbox", D.RAIZ):
    if str(_x) not in sys.path:
        sys.path.insert(0, str(_x))
from nucleo import anexo_consumo as A, experto, hashes, nota_revision  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)
from tests import i19_p_datos as D19  # noqa: E402  (I1.9: contrato v5)

pytestmark = pytest.mark.skipif(not all(p.exists() for p in D.PAQUETES_REALES.values()) or not D.MEDICION.exists(),
                                reason="faltan los paquetes reales de I1.5 o la medición de E")
AUX = ("serviceName eq 'Virtual Network' and productName eq 'Virtual Network Private Link' and armRegionName eq 'Global' "
       "and priceType eq 'Consumption' and meterName eq 'Standard Private Endpoint'")
LEGADO = ("serviceName eq 'Azure Private Link' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and "
          "meterName eq 'Standard Private Endpoint'")


def _aux(resp: dict, cid: str, filtro: str = AUX) -> dict:
    resp["precios"].append({"id": "P-09", "componente_id": cid, "filtro": filtro, "precio": 0.0088, "moneda": "EUR",
                            "unidad": "1 Hour", "region": _c(resp, cid)["region"],
                            "effectiveStartDate": "2020-02-01T00:00:00Z", "concepto": None, "cantidad_mensual": 730,
                            "supuesto_cantidad": "Un punto de conexión privado las 730 horas del mes.",
                            "base_volumen": None})
    return resp


def _validar(resp: dict, est: dict, brief: dict, perfiles: list[str], cat: dict = CAT) -> list[str]:
    return D19.validar(resp, brief, cat, perfiles, requisitos=est["carga"]["requisitos"])


def test_auxiliar_en_un_componente_que_acompana_suma_y_vale():
    est, resp, brief, perfiles = _b_corregida()
    assert _validar(_aux(resp, "C-03"), est, brief, perfiles) == []  # App Service en swedencentral


def test_rev15_1_el_auxiliar_no_cubre_al_componente():
    """La sonda de REV15-1: App Service sin precio propio y con un punto de conexión privado. Antes el núcleo y la puerta
    lo daban por valorado; ahora es «sin_precio_ni_motivo» y el componente sale «A valorar» si declara motivo."""
    est, resp, brief, perfiles = _b_corregida()
    resp["precios"] = [p for p in resp["precios"] if p["id"] != "P-02"]
    _aux(resp, "C-03")
    assert [(x["componente_id"], x["regla"]) for x in A.errores_cobertura(resp, CAT)] == [("C-03", "sin_precio_ni_motivo")]
    assert "C-03" not in A.precios_que_cubren(resp, CAT)
    errores = _validar(resp, est, brief, perfiles)
    assert any(e.startswith("componentes.C-03:") and "auxiliar" in e for e in errores), errores


@pytest.mark.parametrize("caso", ["no_acompana", "filtro_fuera_de_plantilla", "sin_plantillas", "sin_acompana"])
def test_auxiliar_mal_atado_se_rechaza(caso):
    est, resp, brief, perfiles = _b_corregida()
    cat = copy.deepcopy(CAT)
    aux = next(a for a in cat["precios_auxiliares"] if a["service_name"] == "Azure Private Link")
    cid, filtro = "C-03", AUX
    if caso == "no_acompana":
        cid = "C-02"  # Bot Service: no está en «componentes»
    elif caso == "filtro_fuera_de_plantilla":
        filtro = LEGADO  # el auxiliar de antes, por serviceName y sin plantilla
    elif caso == "sin_plantillas":
        del aux["plantillas"]
    else:
        del aux["componentes"]
    errores = _validar(_aux(resp, cid, filtro), est, brief, perfiles, cat)
    # I1.9 (PR18-4): el precio mal atado se rechaza al completarlo (no resuelve plantilla) y ya no viaja además el error
    # derivado del filtro que el núcleo no llegó a poner («el precio P-09: …»), que era consejo falso en el reintento
    assert any(e.startswith("precios.P-09: plantilla_id") for e in errores), errores
    assert not any(e.startswith(f"componentes.{cid}: el precio P-09:") for e in errores), errores


def test_el_precio_de_referencia_no_suma_en_el_anexo_y_el_componente_sale_a_valorar():
    est = copy.deepcopy(json.loads((D.RAIZ / "esquemas" / "ejemplos" / "estado.json").read_text(encoding="utf-8")))
    cat = json.loads((D.RAIZ / "esquemas" / "ejemplos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    assert [p["id"] for p in resp["precios"] if p["cantidad_mensual"] is None] == ["P-04", "P-05"]
    anexo = A.calcular(est, cat)
    assert [x["precio_id"] for x in anexo["lineas"]] == ["P-01", "P-02", "P-03"]
    assert anexo["total_mensual_eur"] == "287.33"  # I1.9: el ejemplo valora el cómputo por defecto (App Service B1)
    assert [x["componente_id"] for x in A.no_valorados(est, cat)] == ["C-01", "C-03", "C-05"]


def test_la_nota_lista_factores_niveles_referencias_y_conceptos():
    est, resp, brief, _ = _b_corregida()
    sust = [{"precio_id": "P-02", "plantilla": "b1-linux", "recibido": "TBD", "fijado": "B1 (x)"}]
    lineas = experto.lineas_para_revisor(experto.fijar_conceptos(resp, CAT)[0], CAT, sust)
    texto = "\n".join(lineas)
    # I1.9 (VA18-9, D18-5): formato español con millares y sin «× 1M al mes»
    assert ("Supuesto de volumen de Microsoft Foundry (C-05), precio P-04 («GPT 5 Inpt DZone 1M Tokens»): 2.000 "
            "consultas al mes (cita «Aproximadamente 2.000 consultas al mes.») × 3.000 tokens por consulta ÷ 1.000.000 = "
            "6 al mes en la unidad de precio «1M». Factor: Pregunta, contexto recuperado e instrucciones.") in lineas
    # I1.9: la línea del nivel dice la razón de la lista cerrada y cómo la cumple la cita, calculado por código
    assert ("Nivel de Azure AI Search (C-04): s1, por encima del valor por defecto (nivel por defecto basic), por la "
            "razón «documentos_sobre_basic»; umbral: 3000 documentos en la cita frente al límite de 2000") in texto
    assert "el experto escribió «TBD»" in texto
    _c(resp, "C-05")["motivo_no_valoracion"] = "depende_del_volumen"
    _p(resp, "P-04").update(cantidad_mensual=None, base_volumen=None)
    assert any(x.startswith("Precio unitario de referencia de Microsoft Foundry (C-05), precio P-04: 1,21 EUR por 1M")
               for x in experto.lineas_para_revisor(resp, CAT))


def test_nota_del_revisor_del_ejemplo_trae_las_referencias_y_retira_un_marcador():
    est = json.loads((D.RAIZ / "esquemas" / "ejemplos" / "estado.json").read_text(encoding="utf-8"))
    cat = json.loads((D.RAIZ / "esquemas" / "ejemplos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    est["carga"]["respuestas_expertos"]["azure"]["ajustes_nucleo"] = {"conceptos": [
        {"precio_id": "P-01", "plantilla": "s1", "recibido": "TBD", "fijado": "Standard S1 Unit"}]}
    est["hash_contenido"] = hashes.hash_contenido(est)
    textos = nota_revision.textos_docx(nota_revision.construir(est, cat))
    assert any(t.startswith("• Precio unitario de referencia de Microsoft Foundry (C-01), precio P-04") for t in textos)
    assert any(t.startswith("• Precio unitario de referencia de Azure AI Bot Service (C-03), precio P-05") for t in textos)
    assert not any("TBD" in t for t in textos)  # el barrido de marcadores retira la línea y lo declara
    assert any("Volumen y niveles (apartado 6)" in t for t in textos)


def test_objetos_forjados_como_texto_y_url_con_puerto_mal_formado_no_lanzan():
    """Revisión (I1.6): un paquete editado puede traer texto donde va un objeto, o una URL con un puerto que no es número;
    el núcleo lo rechaza con su regla, nunca con una excepción."""
    est, resp, brief, _ = _b_corregida()
    _c(resp, "C-04")["justificacion_nivel"] = "nivel premium"
    _p(resp, "P-04")["base_volumen"] = "mucho"
    _p(resp, "P-05")["base_volumen"]["factor"] = "x"
    reglas = [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(resp, brief["texto"],
                                                                              est["carga"]["requisitos"], CAT)]
    assert ("C-04", "nivel_desconocido") in reglas and ("P-04", "cita_no_literal") in reglas
    assert ("P-05", "cuenta_no_cuadra") in reglas
    assert experto.lineas_para_revisor(resp, CAT)  # tampoco la nota
    assert experto.normalizar_url("https://learn.microsoft.com:abc/azure/search") == ""
