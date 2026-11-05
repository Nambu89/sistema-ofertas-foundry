"""I1.8 · papel P: REV17-1 (tramos sobre la cantidad agregada por plantilla) y REV17-2 (el ciclo de vida mira también el
modelo que nombra el sku). Cada caso: resultado esperado del núcleo y la réplica de la puerta igual (tests/i18_p_datos)."""
from __future__ import annotations

from decimal import Decimal

from tests.i18_p_datos import CLIENTE, HOY, INST, analizar, base, comp, con_campo_cliente, fila, precio, reglas
from nucleo import experto

FACTOR_LA = {"valor": 0.0025, "unidad": "GB de registros por consulta", "base": ["consulta"], "caso_uso": "prueba",
             "fuente": "https://learn.microsoft.com/azure/azure-monitor/logs/cost-logs",
             "justificacion": "Factor de prueba: trazas de una consulta del asistente."}
CONSULTAS = {"cita": "Unas 2.000 consultas al mes.", "cantidad_base": 2000, "unidad_base": "consultas al mes"}


def _con_log_analytics(lineas: int):
    brief, req, r, cat = base()
    fila(cat, "az-log-analytics")["plantillas_precio"][0]["factor_estandar"] = dict(FACTOR_LA)
    comp(r, "C-07", "az-log-analytics", "Log Analytics", "operacion_observabilidad", "Pago por uso")
    for n in range(lineas):
        precio(r, f"P-{10 + n:02d}", "C-07", "ingesta", base_volumen=CONSULTAS)
    return brief, req, r, cat


def _coste(c: dict, cid: str) -> Decimal:
    return sum((Decimal(str(p["precio"])) * Decimal(str(p["cantidad_mensual"])) for p in c["precios"]
                if p["componente_id"] == cid), Decimal(0))


def test_control_la_respuesta_base_pasa_y_la_replica_da_lo_mismo():
    brief, req, r, cat = base()
    assert analizar(r, brief, req, cat)[0] == []
    x = reglas(r, brief, req, cat)
    assert x["completar"] == x["volumen_nivel"] == x["motivos"] == x["ciclo"] == []


def test_rev17_1_una_linea_de_10_gb_paga_la_franquicia_una_vez():
    brief, req, r, cat = _con_log_analytics(1)
    x = reglas(r, brief, req, cat)
    assert x["completar"] == [] and analizar(r, brief, req, cat)[0] == []
    tramo = Decimal(str(INST["plantillas"]["az-log-analytics/ingesta"]["tramos"][1]["precio_unitario"]))
    assert abs(_coste(x["completada"], "C-07") - 0 * tramo) < Decimal("0.0001")  # 5 GB: dentro de la franquicia


def test_rev17_1_partir_en_lineas_no_multiplica_la_franquicia():
    tramo = Decimal(str(INST["plantillas"]["az-log-analytics/ingesta"]["tramos"][1]["precio_unitario"]))
    brief, req, r, cat = _con_log_analytics(2)   # 2 líneas de 5 GB: antes, 0,00 € (cada una empezaba en el tramo 0)
    x = reglas(r, brief, req, cat)
    assert x["completar"] == [] and analizar(r, brief, req, cat)[0] == []
    lineas = [p for p in x["completada"]["precios"] if p["componente_id"] == "C-07"]
    assert len({p["precio"] for p in lineas}) == 1                       # el mismo precio medio en las dos
    assert abs(_coste(x["completada"], "C-07") - 5 * tramo) < Decimal("0.0001")
    assert all("sobre el total de la plantilla (10 en 2 líneas)" in p["supuesto_cantidad"] for p in lineas)


def test_rev17_1_seis_lineas_valen_lo_mismo_que_una_con_la_suma():
    brief, req, r, cat = _con_log_analytics(6)
    seis = _coste(reglas(r, brief, req, cat)["completada"], "C-07")
    brief, req, r, cat = _con_log_analytics(1)
    fila(cat, "az-log-analytics")["plantillas_precio"][0]["factor_estandar"]["valor"] = 0.015
    una = _coste(reglas(r, brief, req, cat)["completada"], "C-07")
    assert seis > 0 and abs(seis - una) < Decimal("0.0001")


def test_rev17_1_una_linea_sola_conserva_el_supuesto_de_antes():
    brief, req, r, cat = _con_log_analytics(1)
    p = [p for p in reglas(r, brief, req, cat)["completada"]["precios"] if p["componente_id"] == "C-07"][0]
    assert p["supuesto_cantidad"].endswith("; precio medio por tramos de Retail Prices")


def test_rev17_2_sku_con_otro_modelo_que_sus_precios_falla():
    brief, req, r, cat = base()
    r["componentes"][0]["sku"] = "gpt-5-mini Data Zone"
    x = reglas(r, brief, req, cat)
    assert x["ciclo"] == [("C-01", "modelo_sku_distinto"), ("C-01", "modelo_retirado")]
    assert any("modelo_sku_distinto" not in e and "gpt-5-mini" in e for e in analizar(r, brief, req, cat)[0])


def test_rev17_2_gpt_5_mini_no_cuenta_tambien_como_gpt_5():
    assert experto.modelos_en("GPT-5 mini (Data Zone Standard)", experto.modelos_catalogo(base()[3])) == ["gpt-5-mini"]
    assert experto.modelos_en("gpt-6-luna y gpt-6.1-sol", experto.modelos_catalogo(base()[3])) == ["gpt-6-luna",
                                                                                                    "gpt-6.1-sol"]


def test_rev17_2_sin_precios_el_sku_tiene_que_nombrar_el_modelo_y_se_comprueba():
    for sku, esperado in (("gpt-5-mini en la suscripción del cliente", [("C-01", "modelo_retirado")]),
                          ("Despliegue que ya tiene el cliente", [("C-01", "modelo_sin_plantilla")]),
                          ("gpt-6-luna Data Zone", [])):
        brief, req, r, cat = base()
        con_campo_cliente(brief, req, r, ["El cliente ya paga su consumo de Microsoft Foundry."])
        c1 = r["componentes"][0]
        c1.update({"sku": sku, "motivo_no_valoracion": "a_cargo_del_cliente",
                   "motivo_cita": "El cliente ya paga su consumo de Microsoft Foundry."})
        r["precios"] = [p for p in r["precios"] if p["componente_id"] != "C-01"]
        x = reglas(r, brief, req, cat)
        assert x["motivos"] == [] and x["ciclo"] == esperado, sku


def test_rev17_2_fuera_de_la_fila_de_modelos_tambien_se_comprueba_el_sku():
    brief, req, r, cat = base()
    comp(r, "C-07", None, "Servicio de resúmenes propio", "ia", "gpt-5-mini Global", motivo_no_valoracion="fuera_del_catalogo",
         referencia_id="REF-01", desviacion_justificada="Servicio propio del cliente para resúmenes, fuera del catálogo.")
    assert reglas(r, brief, req, cat)["ciclo"] == [("C-07", "modelo_retirado")]


def test_rev17_2_modelo_sin_ciclo_en_el_catalogo_falla_cerrado():
    brief, req, r, cat = base()
    for p in fila(cat, "az-foundry")["plantillas_precio"]:
        if p.get("modelo") == "gpt-5-nano":
            p.pop("ciclo_vida")
    comp(r, "C-07", None, "Clasificador propio", "ia", "gpt-5-nano", motivo_no_valoracion="fuera_del_catalogo",
         referencia_id="REF-01", desviacion_justificada="Clasificador propio del cliente, fuera del catálogo de servicios.")
    assert ("C-07", "ciclo_vida_desconocido") in reglas(r, brief, req, cat)["ciclo"]
    assert experto.modelos_catalogo(cat)["gpt-5-nano"] is None and HOY
