"""I1.6 · papel P: concepto fijado por el núcleo (VER15-3, REVERIF15-2), justificación del nivel (decisión 4) y precio
auxiliar atado a su componente (REV15-1, REV15-3). Casos adversos con su resultado esperado (LES-G-096.6). Sin red."""
from __future__ import annotations

import copy
import json
import sys

import pytest

from tests import i16_p_datos as D
from tests.test_i16_p_volumen import CAT, _b_corregida, _c, _p, _real

for _p_ in (D.RAIZ / "sandbox", D.RAIZ):
    if str(_p_) not in sys.path:
        sys.path.insert(0, str(_p_))
from nucleo import anexo_consumo as A, estado as est_mod, experto  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)
from tests import i19_p_datos as D19  # noqa: E402  (I1.9: contrato v5)

pytestmark = pytest.mark.skipif(not all(p.exists() for p in D.PAQUETES_REALES.values()) or not D.MEDICION.exists(),
                                reason="faltan los paquetes reales de I1.5 o la medición de E")
B1 = "B1 (Azure App Service Basic Plan - Linux)"


@pytest.mark.parametrize("recibido,anotado", [
    ("B1", True), (None, False), (B1, False), (f"  {B1.replace(' ', '  ')} ", False), ("B1 | texto", True),
    ("Lo que sea", True), ("TBD", True), ("", False), ("x" * 900, True)])
def test_el_concepto_lo_fija_el_nucleo_y_solo_se_anota_si_era_otro(recibido, anotado):
    est, resp, brief, perfiles = _b_corregida()
    _p(resp, "P-02")["concepto"] = recibido
    assert D19.validar(resp, brief, CAT, perfiles, requisitos=est["carga"]["requisitos"]) == []
    fijada, sust, errores = experto.fijar_conceptos(resp, CAT)
    assert errores == [] and _p(fijada, "P-02")["concepto"] == B1 and _p(resp, "P-02")["concepto"] == recibido
    assert [s["precio_id"] for s in sust] == (["P-02"] if anotado else [])
    if anotado:
        assert sust[0]["plantilla"] == "b1-linux" and sust[0]["fijado"] == B1 and len(sust[0]["recibido"]) <= 160
    assert _p(fijada, "P-04")["concepto"] == "GPT 5 Inpt DZone 1M Tokens"  # null → meterName de la plantilla


def test_sin_concepto_en_el_catalogo_un_meter_corto_falla_cerrado():
    est, resp, brief, perfiles = _b_corregida()
    cat = copy.deepcopy(CAT)
    pl = next(p for e in cat["componentes"] if e["id"] == "az-app-service" for p in e["plantillas_precio"]
              if p["id"] == "b1-linux")
    del pl["concepto"]
    errores = D19.validar(resp, brief, cat, perfiles, requisitos=est["carga"]["requisitos"])
    # integrador I1.7: sin concepto en la plantilla, el núcleo no puede completar el precio (falla cerrado)
    assert any(e.startswith("precios.P-02:") and "no declara concepto" in e for e in errores), errores


def _estado_en_analisis() -> tuple[dict, dict, list[str]]:
    est, resp, brief, perfiles = _b_corregida()
    est["estado"], est["intentos"]["T2"] = "EN_ANALISIS", 0
    est["ronda_verificacion"] = int(brief["brief_id"][-1]) - 1
    est["carga"]["respuestas_expertos"] = {}
    assert est_mod.brief_vigente(est)["brief_id"] == brief["brief_id"]
    return est, resp, perfiles


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): el concepto que escribía el modelo y su sustitución anotada en ajustes_nucleo; imposible por construcción con el contrato v4 (el modelo ya no escribe filtro, precio, concepto ni cantidad). Lo vigente: el núcleo pone el concepto de la plantilla al completar (tests/test_i17_p_completar.py)")
def test_registrar_guarda_el_concepto_fijado_y_anota_la_sustitucion():
    est, resp, perfiles = _estado_en_analisis()
    _p(resp, "P-02")["concepto"] = "B1"
    reg = experto.registrar(est, "azure", json.dumps(resp, ensure_ascii=False), CAT, perfiles, "2026-10-11")
    assert _p(reg["respuesta"], "P-02")["concepto"] == B1
    assert reg["ajustes_nucleo"] == {"conceptos": [{"precio_id": "P-02", "plantilla": "b1-linux", "recibido": "B1",
                                                    "fijado": B1}]}
    linea = experto.lineas_para_revisor(reg["respuesta"], CAT, reg["ajustes_nucleo"]["conceptos"])[-1]
    assert linea == f"Concepto del precio P-02 fijado por el código desde la plantilla «b1-linux»: el experto escribió «B1» y vale «{B1}»"


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): el concepto que escribía el modelo; imposible por construcción con el contrato v4 (el modelo ya no escribe filtro, precio, concepto ni cantidad). Lo vigente: tests/test_i17_p_completar.py")
def test_registrar_sin_sustituciones_no_escribe_ajustes():
    est, resp, perfiles = _estado_en_analisis()
    _p(resp, "P-02")["concepto"] = None
    reg = experto.registrar(est, "azure", json.dumps(resp, ensure_ascii=False), CAT, perfiles, "2026-10-11")
    assert "ajustes_nucleo" not in reg and _p(reg["respuesta"], "P-02")["concepto"] == B1


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): una cantidad de volumen sin base (volumen_sin_base) del caso real A; imposible por construcción con el contrato v4 (el modelo ya no escribe filtro, precio, concepto ni cantidad). Lo vigente: la cantidad de volumen la calcula el núcleo desde base_volumen citada (tests/test_i17_p_factores_citas.py)")
def test_registrar_rechaza_el_caso_real_a_con_un_intento_t2():
    est, resp, brief, perfiles = _real("A")
    est["estado"], est["intentos"]["T2"] = "EN_ANALISIS", 0
    est["ronda_verificacion"] = int(brief["brief_id"][-1]) - 1
    est["carga"]["respuestas_expertos"] = {}
    with pytest.raises(experto.ReglaIncumplida) as ex:
        experto.registrar(est, "azure", json.dumps(resp, ensure_ascii=False), CAT, perfiles, "2026-10-11")
    assert est["intentos"]["T2"] == 1 and any("precios.P-03" in e and "LES-G-100" in e for e in ex.value.errores)


# I1.9 (VC18-1, contrato v5): la justificación es {nivel, razon, cita}; el límite y la fuente los pone el catálogo (ya
# no hay limite_no_oficial ni fuente_no_oficial: el experto no los escribe). Razones de prueba en i16_p_datos.
JN = {"nivel": "s1", "razon": "documentos_sobre_basic", "cita": "Aproximadamente 3.000 documentos."}


@pytest.mark.parametrize("cambio,reglas_esperadas", [
    ({}, []),
    ({"nivel": "S1"}, ["nivel_desconocido"]),
    ({"nivel": "basic"}, ["nivel_distinto_del_precio", "nivel_sin_razones"]),
    ({"razon": "limite_oficial"}, ["razon_desconocida"]),
    ({"razon": "indices_sobre_basic"}, ["razon_no_cumplida"]),
    ({"cita": "Unos tres mil documentos"}, ["requisito_no_literal"]),
    ({"cita": "Microsoft Teams."}, ["requisito_no_literal"])])
def test_justificacion_del_nivel_contra_el_catalogo_y_los_requisitos(cambio, reglas_esperadas):
    est, resp, brief, _ = _b_corregida()
    _c(resp, "C-04")["justificacion_nivel"] = {**JN, **cambio}
    reglas = [r for i, r in [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(
        resp, brief["texto"], est["carga"]["requisitos"], CAT)] if i == "C-04"]
    assert reglas == reglas_esperadas, reglas


def test_nivel_obligatorio_con_niveles_y_prohibido_sin_ellos():
    est, resp, brief, _ = _b_corregida()
    _c(resp, "C-04")["justificacion_nivel"] = None
    _c(resp, "C-03")["justificacion_nivel"] = dict(JN)  # App Service: el catálogo no le da niveles
    reglas = [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(resp, brief["texto"],
                                                                              est["carga"]["requisitos"], CAT)]
    assert ("C-04", "nivel_sin_justificar") in reglas and ("C-03", "nivel_sin_catalogo") in reglas


@pytest.mark.parametrize("plantilla,esperado", [
    ({"concepto": "  B1  (Azure App Service Basic Plan - Linux) ", "filtro": "meterName eq 'B1'"}, B1),
    ({"comprobacion": {"medidor": "B1", "producto": "Azure App Service Basic Plan - Linux"}}, B1),
    ({"comprobacion": {"medidor": "vCore", "sku": "2 vCore"}, "concepto_con_sku": True}, "vCore (2 vCore)"),
    ({"comprobacion": {"medidor": "vCore"}, "concepto_con_sku": True, "filtro": "meterName eq 'vCore'"}, None),
    ({"comprobacion": {"medidor": "Basic Unit"}}, "Basic Unit"),
    ({"filtro": "serviceName eq 'X' and meterName eq 'Standard S1 Unit'"}, "Standard S1 Unit"),
    ({"filtro": "serviceName eq 'X' and meterName eq 'B1'"}, None),
    ({"comprobacion": {"medidor": "B1"}, "filtro": "meterName eq 'B1'"}, None)])
def test_concepto_de_la_plantilla_como_lo_deriva_el_catalogo(plantilla, esperado):
    """Mismo criterio que catalogo.plantillas_precio.concepto (papel E): con el producto si el meterName es corto, con
    el sku si la plantilla lo pide; si falta el dato, None (falla cerrado, nunca « (None)»)."""
    assert experto.concepto_de_plantilla(plantilla) == esperado
