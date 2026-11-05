"""I1.8 · papel P: REV17-3 («a_cargo_del_cliente» solo con una entrada del campo «lo que el cliente ya tiene o paga» que
nombre el servicio) y REV17-7 (la cantidad de la base es el número de la cita que va con su unidad). Núcleo y réplica de
la puerta iguales en cada caso (tests/i18_p_datos.reglas)."""
from __future__ import annotations

import copy

from tests.i18_p_datos import CLIENTE, analizar, base, comp, con_campo_cliente, reglas
from nucleo import experto


def _log_analytics_a_cargo(r: dict, cita: str | None):
    comp(r, "C-07", "az-log-analytics", "Log Analytics", "operacion_observabilidad", "Espacio existente",
         motivo_no_valoracion="a_cargo_del_cliente", motivo_cita=cita)


def test_rev17_3_control_entrada_del_campo_que_nombra_el_servicio():
    brief, req, r, cat = base()
    con_campo_cliente(brief, req, r, [CLIENTE])
    _log_analytics_a_cargo(r, CLIENTE)
    res = reglas(r, brief, req, cat)
    assert res["motivos"] == []          # la regla de I1.8 sigue para las respuestas v4 guardadas (la puerta)
    lineas = experto.lineas_para_revisor(res["completada"], cat)
    assert any("según lo que el cliente ya tiene o paga: «El cliente ya paga" in x for x in lineas)
    # I1.9 (PR18-1): en v5 «a_cargo_del_cliente» ya no existe; el recurso se declara existente_del_cliente
    errores, completada = analizar(r, brief, req, cat)
    assert completada is None and any("'a_cargo_del_cliente' fuera de" in e for e in errores)


def test_rev17_3_cita_de_otro_campo_de_requisitos_ya_no_vale():
    for cita in ("Plazo deseado de unas 8 semanas.", "Aplican el RGPD.", "Enterprise Agreement directo con Microsoft."):
        brief, req, r, cat = base()
        _log_analytics_a_cargo(r, cita)
        res = reglas(r, brief, req, cat)
        assert res["motivos"] == [("C-07", "cita_cliente_no_literal")], cita
        assert any("el cliente no ha dicho que tenga o pague nada" in x["detalle"]
                   for x in experto.errores_motivos(res["completada"], cat, req, brief["texto"]))


def test_rev17_3_entrada_del_campo_que_no_nombra_el_servicio():
    brief, req, r, cat = base()
    con_campo_cliente(brief, req, r, ["Ya pagan las licencias de Microsoft 365."])
    _log_analytics_a_cargo(r, "Ya pagan las licencias de Microsoft 365.")
    assert reglas(r, brief, req, cat)["motivos"] == [("C-07", "cita_cliente_sin_servicio")]


def test_rev17_3_un_alias_mas_largo_de_otra_fila_no_nombra_el_servicio():
    brief, req, r, cat = base()
    texto = "El cliente ya paga el Servicio de agente de Microsoft Foundry."
    con_campo_cliente(brief, req, r, [texto])
    c1 = r["componentes"][0]
    c1.update({"motivo_no_valoracion": "a_cargo_del_cliente", "motivo_cita": texto})
    r["precios"] = [p for p in r["precios"] if p["componente_id"] != "C-01"]
    assert reglas(r, brief, req, cat)["motivos"] == [("C-01", "cita_cliente_sin_servicio")]


def test_rev17_3_sin_cita_y_con_entradas_asumidas():
    brief, req, r, cat = base()
    _log_analytics_a_cargo(r, None)
    assert reglas(r, brief, req, cat)["motivos"] == [("C-07", "cliente_sin_cita")]
    brief, req, r, cat = base()
    con_campo_cliente(brief, req, r, [CLIENTE], en_brief=False, origen="ASUMIDO")
    _log_analytics_a_cargo(r, CLIENTE)
    assert reglas(r, brief, req, cat)["motivos"] == [("C-07", "cita_cliente_no_literal")]


def test_rev17_3_la_seccion_del_brief_sola_no_basta_si_no_casa_con_los_requisitos():
    brief, req, r, cat = base()
    con_campo_cliente(brief, req, r, [CLIENTE])
    req["campos"].pop(experto.CAMPO_CLIENTE)       # el brief trae la sección y los requisitos no la tienen
    _log_analytics_a_cargo(r, CLIENTE)
    assert reglas(r, brief, req, cat)["motivos"] == [("C-07", "cita_cliente_no_literal")]
    assert experto.citas_cliente(None, brief["texto"]) == []          # sin requisitos no vale nada (falla cerrado)


def test_rev17_3_una_vineta_del_brief_vale_por_la_entrada_con_la_que_se_empareja():
    brief, req, r, cat = base()
    con_campo_cliente(brief, req, r, ["El cliente ya paga su consumo de Microsoft Foundry."], en_brief=False)
    brief["texto"] = brief["texto"].rstrip("\n") + "\n" + experto.SECCION_CLIENTE + "\n- " + CLIENTE + "\n"
    r["brief_recibido"] = brief["texto"]                                  # Revisión I1.8: viñeta que no es la entrada
    _log_analytics_a_cargo(r, CLIENTE)
    assert reglas(r, brief, req, cat)["motivos"] == [("C-07", "cita_cliente_sin_servicio")]
    assert experto.fuentes_cliente(req, brief["texto"])[CLIENTE] == "El cliente ya paga su consumo de Microsoft Foundry."


def test_rev17_3_comillas_que_envuelven_la_cita_se_quitan():
    brief, req, r, cat = base()
    con_campo_cliente(brief, req, r, [CLIENTE])
    _log_analytics_a_cargo(r, f"«{CLIENTE}»")
    assert reglas(r, brief, req, cat)["motivos"] == []


def test_rev17_3_fuera_del_catalogo_nombra_por_su_servicio():
    brief, req, r, cat = base()
    texto = "El cliente ya paga su Plataforma Kelvara de documentos."
    con_campo_cliente(brief, req, r, [texto])
    comp(r, "C-07", None, "Plataforma Kelvara", "datos_conocimiento", "Licencia", referencia_id="REF-01",
         desviacion_justificada="Plataforma documental propia del cliente, fuera del catálogo de Azure.",
         motivo_no_valoracion="a_cargo_del_cliente", motivo_cita=texto)
    assert reglas(r, brief, req, cat)["motivos"] == []


# ── REV17-7 ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _con_volumetria(req: dict, valor: str):
    req["campos"]["volumetria"]["entradas"].append({"valor": valor, "cita": None, "fuente": None, "origen": "ASUMIDO"})


def _base_entrada(cita: str, cantidad):
    brief, req, r, cat = base()
    _con_volumetria(req, cita)
    for p in r["precios"]:
        if p["id"] == "P-01":
            p["base_volumen"] = {"cita": cita, "cantidad_base": cantidad, "unidad_base": "consultas al mes"}
    return brief, req, r, cat


def test_rev17_7_el_numero_de_otra_unidad_no_vale_como_cantidad():
    brief, req, r, cat = _base_entrada("Unas 2.000 consultas al mes de 100 técnicos.", 100)
    assert ("P-01", "cantidad_sin_su_unidad") in reglas(r, brief, req, cat)["volumen_nivel"]


def test_rev17_7_el_numero_junto_a_su_unidad_si_vale():
    brief, req, r, cat = _base_entrada("Unas 2.000 consultas al mes de 100 técnicos.", 2000)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == []


def test_rev17_7_unidad_antes_del_numero_al_final_de_la_cita():
    brief, req, r, cat = _base_entrada("Consultas al mes: 2.000", 2000)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == []
    assert experto.cantidad_con_su_unidad("Consultas: 2.000 de 100", 100, ["consulta"]) is False


def test_rev17_7_funciones_puras():
    f = experto.cantidad_con_su_unidad
    assert f("Unos 3.000 documentos.", 3000, ["documento"]) and not f("Unos 3.000 documentos.", 3000, ["consulta"])
    assert not f("entre 50 y 100 técnicos", 50, ["técnico"]) and f("entre 50 y 100 técnicos", 100, ["técnicos"])
    assert not f("2.000 consultas", 2000, []) and not f(None, 1, ["consulta"]) and not f("1 consulta", True, ["consulta"])
    assert experto.numeros_en("1.500,5 y 2.5 y 1,000,000") == [experto.Decimal("1500.5"), experto.Decimal("2.5")]
    assert copy.deepcopy(f("Unos 3.000 documentos.", 3000.0, ["documentos"])) is True
