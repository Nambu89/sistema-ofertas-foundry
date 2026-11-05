"""I1.7 · papel P: instantánea de precios (forma, huella, cobertura y edad), registrar-experto con ella y conservación
por efecto entre rondas (REVERIF16-1 y REVERIF16-2). Casos adversos con su resultado esperado. Sin red.
"""
from __future__ import annotations

import copy
import json

import pytest

from tests import i17_p_datos as D
from tests.test_i17_p_completar import BRIEF, CAT, INST, PERF, analizar, con, p_, resp
from nucleo import experto  # noqa: E402
from nucleo.errores import IntegridadRota, ReglaIncumplida  # noqa: E402


def test_instantanea_valida_y_sus_roturas():
    assert experto.errores_instantanea(INST) == [] and experto.errores_instantanea_catalogo(INST, CAT) == []
    inst = copy.deepcopy(INST)
    inst["plantillas"]["az-foundry/gpt-6-luna-entrada"]["precio_unitario"] = 0.01  # sin resellar
    assert con(experto.errores_instantanea(inst), "sha256 no es el del contenido")
    inst = copy.deepcopy(INST)
    inst["plantillas"]["az-foundry/gpt-6-luna-entrada"]["armRegionName"] = "westeurope"
    assert con(experto.errores_instantanea(D.resellar(inst)), "armRegionName «westeurope» no es el del filtro")
    inst = copy.deepcopy(INST)
    inst["plantillas"]["az-ai-search/basic"]["filtro"] += " "
    assert con(experto.errores_instantanea_catalogo(D.resellar(inst), CAT), "«az-ai-search/basic» con su filtro")
    falta = D.instantanea_i17(CAT, quitar=("az-sql-database/basic",))
    assert experto.errores_instantanea_catalogo(falta, CAT) == [
        "la instantánea no trae el precio de la plantilla «az-sql-database/basic» con su filtro del catálogo"]
    for k, v in (("moneda", "USD"), ("fecha_consulta", "2026-10-13 08:00"), ("plantillas", [])):
        assert experto.errores_instantanea(D.resellar(dict(copy.deepcopy(INST), **{k: v}))), k
    inst = copy.deepcopy(INST)
    inst["plantillas"]["az-ai-search/basic"]["articulos_devueltos"] = True
    assert experto.errores_instantanea(D.resellar(inst))


def test_clave_suelta_solo_vale_con_el_mismo_filtro():
    inst = copy.deepcopy(INST)
    inst["plantillas"]["gpt-6-luna-entrada"] = inst["plantillas"].pop("az-foundry/gpt-6-luna-entrada")
    assert analizar(resp(), inst=D.resellar(inst))[0] == []
    inst["plantillas"]["basic"] = inst["plantillas"].pop("az-ai-search/basic")
    inst["plantillas"]["basic"]["filtro"] = inst["plantillas"]["az-sql-database/basic"]["filtro"]
    assert con(analizar(resp(), inst=D.resellar(inst))[0], "precios.P-03: la instantánea de precios no trae")


@pytest.mark.parametrize("fecha, hoy, ok", [("2026-09-12T23:59:59Z", "2026-10-13", True),
                                            ("2026-09-11T00:00:00Z", "2026-10-13", False),
                                            ("2026-10-14T00:00:00Z", "2026-10-13", False)])
def test_edad_de_la_instantanea(fecha, hoy, ok):
    assert (experto.errores_edad_instantanea(fecha, hoy) == []) is ok


def _estado():
    return D.estado_brezalia()


def test_registrar_completa_y_guarda_con_la_instantanea():
    est = _estado()
    reg = experto.registrar(est, "azure", json.dumps(resp(), ensure_ascii=False), CAT, PERF, "2026-10-13", instantanea=INST)
    assert est["carga"]["respuestas_expertos"]["azure"] is reg and est["intentos"]["T2"] == 0
    assert reg["respuesta"]["valoracion_nucleo"]["instantanea"]["fecha"] == "2026-10-13"
    assert "ajustes_nucleo" not in reg


def test_instantanea_caducada_o_incompleta_no_suma_intento():
    for inst in (D.instantanea_i17(CAT, fecha="2026-09-01T00:00:00Z"), D.instantanea_i17(CAT, quitar=("az-foundry/gpt-5-salida",))):
        est = _estado()
        with pytest.raises(IntegridadRota):
            experto.registrar(est, "azure", json.dumps(resp()), CAT, PERF, "2026-10-13", instantanea=inst)
        assert est["intentos"]["T2"] == 0 and est["estado"] == "EN_ANALISIS"


def test_respuesta_v3_suma_un_intento_t2():
    est = _estado()
    r = resp()
    p_(r, "P-01")["precio"] = 0.2
    with pytest.raises(ReglaIncumplida):
        experto.registrar(est, "azure", json.dumps(r), CAT, PERF, "2026-10-13", instantanea=INST)
    assert est["intentos"]["T2"] == 1


def _conservar(c):
    """El dato por efecto del brief, compuesto por el papel R (verificacion.precios_conservar). Sin red de seguridad: si la
    función de R falla, la prueba falla (Revisión, pasada 3)."""
    from nucleo import verificacion
    est = {"carga": {"respuestas_expertos": {"azure": {"respuesta": c}}, "verificacion": None, "briefs": []}}
    return verificacion.precios_conservar(est)


def _brief_r2(conservar):
    return dict(copy.deepcopy(BRIEF), conservar_precios=conservar)


def test_conservacion_por_efecto_reverif16_1():
    _, c = analizar(resp())
    conservar = _conservar(c)
    assert conservar and all(x["plantilla_id"] for x in conservar)
    brief = _brief_r2(conservar)
    assert analizar(resp(), brief=brief)[0] == []
    r = resp()  # ids renumerados: se casa por catalogo_id y plantilla
    for p in r["precios"]:
        p["id"] = "P-1" + p["id"][-1]
    assert analizar(r, brief=brief)[0] == []
    r = resp()  # REVERIF16-1: el original intacto más un duplicado con el factor ×10
    r["precios"].append({"id": "P-09", "componente_id": "C-01", "plantilla_id": "gpt-6-luna-entrada", "instancias": None,
                         "base_volumen": copy.deepcopy(D.CONSULTAS),
                         "factor_override": {"valor": 25000, "cita": "Unos 3.000 documentos.",
                                             "justificacion": "Duplicado para esquivar la conservación."}})
    errores = analizar(r, brief=brief)[0]
    assert con(errores, "conservar_precios: az-foundry · gpt-6-luna-entrada") and con(errores, "era 5 y la respuesta da 55")
    r = resp()
    r["precios"] = [p for p in r["precios"] if p["id"] != "P-04"]
    assert con(analizar(r, brief=brief)[0], "az-bot-service · canales-estandar · C-03 desaparece de la respuesta")  # I1.8: por componente (REV17-4)
    r = resp()
    p_(r, "P-05")["instancias"] = 2
    assert con(analizar(r, brief=brief)[0], "era 730 y la respuesta da 1460")


@pytest.mark.parametrize("conservar", [{"x": 1}, [1], [{"filtro": None}], "texto"])
def test_conservar_con_otra_forma_falla_cerrado(conservar):
    errores = analizar(resp(), brief=_brief_r2(conservar))[0]
    assert errores and all("conservar_precios" in e for e in errores), errores


def test_conservar_vacio_o_ausente_no_comprueba_nada():
    assert analizar(resp(), brief=_brief_r2([]))[0] == []
    assert experto.errores_conservacion({"precios": []}, None) == []


def test_precio_por_tramos_se_valora_por_tramos():
    from decimal import Decimal
    tramos = [{"desde": 0.0, "precio_unitario": 0.0}, {"desde": 1.0, "precio_unitario": 0.5}, {"desde": 10, "precio_unitario": 0.25}]
    assert experto.coste_por_tramos(Decimal(4), tramos) == Decimal("1.5")
    assert experto.coste_por_tramos(Decimal(12), tramos) == Decimal("5.0")
    assert experto.coste_por_tramos(Decimal("0.5"), tramos) == 0
    inst = copy.deepcopy(INST)
    art = inst["plantillas"]["az-bot-service/canales-estandar"]
    art.update({"precio_unitario": 0.0, "tramos": tramos})
    errores, c = analizar(resp(), inst=D.resellar(inst))
    assert errores == [], errores
    p4 = p_(c, "P-04")
    assert (p4["cantidad_mensual"], p4["precio"], p4["precio_tramos"]) == (4, 0.375, tramos)
    assert p4["supuesto_cantidad"].endswith("precio medio por tramos de Retail Prices")
    for malos in ([{"desde": 1.0, "precio_unitario": 0.0}, {"desde": 2.0, "precio_unitario": 1}],
                  [{"desde": 0.0, "precio_unitario": 0.0}, {"desde": 0.0, "precio_unitario": 1}],
                  [{"desde": 0.0, "precio_unitario": 0.1}, {"desde": 5.0, "precio_unitario": 1}]):
        art["tramos"] = malos
        assert con(experto.errores_instantanea(D.resellar(inst)), "tramos no válidos"), malos


def test_la_instantanea_real_valida_si_existe():
    ruta = D.RAIZ / "sandbox" / "datos" / "precios_instantanea.json"
    if not ruta.exists():
        pytest.skip("la instantánea real aún no está")
    from nucleo import anexo_consumo
    inst = anexo_consumo.cargar_instantanea(ruta)
    assert experto.sha256_instantanea(inst) == inst["sha256"]


def test_revision_tramos_con_cantidad_grande_no_se_redondean_a_cero():
    from decimal import Decimal
    inst = copy.deepcopy(INST)
    art = inst["plantillas"]["az-bot-service/canales-estandar"]
    art.update({"precio_unitario": 0.0, "tramos": [{"desde": 0.0, "precio_unitario": 0.0},
                                                    {"desde": 1.0, "precio_unitario": 0.000000004}]})
    r = resp()
    p_(r, "P-04")["base_volumen"] = {"cita": "Unas 2.000 consultas al mes.", "cantidad_base": 2000, "unidad_base": "consultas"}
    p_(r, "P-04")["factor_override"] = {"valor": 5000000000 / 2000 * 1000 / 1000, "cita": "Unas 2.000 consultas al mes.",
                                        "justificacion": "Caso de la revisión independiente: volumen enorme con precio diminuto por tramo."}
    errores, c = analizar(r, inst=D.resellar(inst))
    assert errores == [], errores
    p4 = p_(c, "P-04")
    coste = Decimal(str(p4["precio"])) * Decimal(str(p4["cantidad_mensual"]))
    assert abs(coste - experto.coste_por_tramos(Decimal(str(p4["cantidad_mensual"])), art["tramos"])) < Decimal("0.000001")


def test_revision_factor_enorme_da_error_y_no_excepcion():
    r = resp()
    p_(r, "P-01")["factor_override"] = {"valor": 1e100, "cita": "Unas 2.000 consultas al mes.",
                                        "justificacion": "Factor forjado para provocar una excepción."}
    errores, c = analizar(r)
    assert c is None and con(errores, "$.precios[0].factor_override.valor: 1e+100 fuera de rango")  # el esquema lo para
    cat = copy.deepcopy(CAT)
    next(e for e in cat["componentes"] if e["id"] == "az-foundry")["factores_estandar"][0]["valor"] = 1e30
    errores, c = analizar(resp(), cat=cat)
    assert c is None and con(errores, "precios.P-01: la cuenta de «az-foundry/gpt-6-luna-entrada» pasa de")


def test_plantilla_con_prefijo_se_deja_suelta_y_conserva_entre_rondas():
    _, c = analizar(resp())
    brief = _brief_r2(_conservar(c))
    r = resp()
    p_(r, "P-03")["plantilla_id"] = "az-ai-search/basic"  # la misma plantilla con el prefijo de su fila
    errores, c2 = analizar(r, brief=brief)
    assert errores == [], errores
    assert p_(c2, "P-03")["plantilla_id"] == "basic" and experto.proyectar_modelo(c2) == r
    assert any(a["campo"] == "precios.P-03.plantilla_id" for a in c2["valoracion_nucleo"]["ajustes"])
