"""I1.6 · papel P: decisión 4 del comercial y LES-G-100 en el núcleo (volumen, «depende_del_volumen» y cuenta rehecha).

Incluye la reproducción de los dos casos reales de I1.5 (paquetes de Brezalia): B dejó Microsoft Foundry sin valorar
por «depende_del_volumen» con la volumetría CITADA, y A lo valoró con «1 millón de tokens de referencia» inventado.
Los dos se rechazan ahora. Casos adversos con su resultado esperado (LES-G-096.6). Sin red.
"""
from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from tests import i16_p_datos as D

import sys  # noqa: E402  (i16_p_datos ya fija RAIZ; el núcleo vive en sandbox/)
for _p in (D.RAIZ / "sandbox", D.RAIZ):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from nucleo import esquema, experto  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)
from tests import i19_p_datos as D19  # noqa: E402  (I1.9: contrato v5)

CAT = D.catalogo_i16(modelo_por_defecto="gpt-5")  # I1.9: el caso B de I1.6 valora gpt-5
pytestmark = pytest.mark.skipif(not all(p.exists() for p in D.PAQUETES_REALES.values()) or not D.MEDICION.exists(),
                                reason="faltan los paquetes reales de I1.5 o la medición de E")


def _real(x: str) -> tuple[dict, dict, dict, list[str]]:
    est = D.paquete_real(x)
    reg = est["carga"]["respuestas_expertos"]["azure"]
    brief = D.brief_de(est, reg["brief_id"])
    perfiles = brief["texto"].split("perfiles_permitidos: ")[1].split("\n")[0].split("; ")
    return est, D.a_v3(reg["respuesta"]), brief, perfiles


def _reglas(resp: dict, est: dict, brief: dict, requisitos: object = "estado") -> list[tuple[str, str]]:
    req = est["carga"]["requisitos"] if requisitos == "estado" else requisitos
    return [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(resp, brief["texto"], req, CAT)]


def _p(resp: dict, pid: str) -> dict:
    return next(p for p in resp["precios"] if p["id"] == pid)


def _c(resp: dict, cid: str) -> dict:
    return next(c for c in resp["componentes"] if c["id"] == cid)


def test_caso_real_b_foundry_sin_valorar_con_volumetria_citada_se_rechaza():
    est, resp, brief, perfiles = _real("B")
    assert est["carga"]["requisitos"]["campos"]["volumetria"]["estado"] == "CITADO"
    reglas = _reglas(resp, est, brief)
    assert ("C-05", "depende_con_volumetria_citada") in reglas and ("C-05", "depende_sin_precio_unitario") in reglas
    assert ("P-03", "volumen_sin_base") in reglas  # Bot Service: 2 × 1K mensajes sin base citada
    errores = D19.validar(resp, brief, CAT, perfiles, requisitos=est["carga"]["requisitos"])
    assert any(e.startswith("componentes.C-05:") and "volumetría no está citada" in e for e in errores), errores


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): una cantidad de volumen sin base (volumen_sin_base) del caso real A; imposible por construcción con el contrato v4 (el modelo ya no escribe filtro, precio, concepto ni cantidad). Lo vigente: la cantidad la calcula el núcleo desde base_volumen citada (tests/test_i17_p_factores_citas.py)")
def test_caso_real_a_un_millon_de_tokens_de_referencia_sin_base_se_rechaza():
    est, resp, brief, perfiles = _real("A")
    assert "Un millón de tokens" in _p(resp, "P-03")["supuesto_cantidad"]
    reglas = _reglas(resp, est, brief)
    assert ("P-03", "volumen_sin_base") in reglas and ("P-04", "volumen_sin_base") in reglas
    errores = D19.validar(resp, brief, CAT, perfiles, requisitos=est["carga"]["requisitos"])
    assert any(e.startswith("precios.P-03:") and "LES-G-100" in e for e in errores), errores


def _b_corregida() -> tuple[dict, dict, dict, list[str]]:
    """La respuesta real de B como debería haber llegado: Foundry valorado con la volumetría citada y AI Search con su
    nivel justificado (control: el núcleo la acepta)."""
    est, resp, brief, perfiles = _real("B")
    base = lambda f, u, j: {"cita": "Aproximadamente 2.000 consultas al mes.", "cantidad_base": 2000,
                            "unidad_base": "consultas al mes", "factor": {"valor": f, "unidad": u, "justificacion": j}}
    _p(resp, "P-03")["base_volumen"] = base(1, "mensajes por consulta", "Cada consulta es un mensaje del canal de Teams.")
    _c(resp, "C-05")["motivo_no_valoracion"] = "no_aplica"
    plantillas = {p["id"]: p for p in next(e for e in CAT["componentes"] if e["id"] == "az-foundry")["plantillas_precio"]}
    for pid, pl, precio, cant, f, j in (("P-04", "gpt-5-entrada", 1.21, 6, 3000, "Pregunta, contexto recuperado e instrucciones."),
                                        ("P-05", "gpt-5-salida", 9.6797, 1, 500, "Respuesta breve con citas.")):
        resp["precios"].append({"id": pid, "componente_id": "C-05", "filtro": plantillas[pl]["filtro"], "precio": precio,
                                "moneda": "EUR", "unidad": "1M", "region": "swedencentral",
                                "effectiveStartDate": "2025-08-01T00:00:00Z", "concepto": None, "cantidad_mensual": cant,
                                "supuesto_cantidad": "Tokens del mes según las consultas citadas.",
                                "base_volumen": base(f, "tokens por consulta", j)})
    # I1.9 (contrato v5): S1 sube sobre basic con la razón de umbral del catálogo de prueba y la cita de la volumetría
    _c(resp, "C-04")["justificacion_nivel"] = {"nivel": "s1", "razon": "documentos_sobre_basic",
                                               "cita": "Aproximadamente 3.000 documentos."}
    return est, resp, brief, perfiles


def test_control_b_corregida_se_acepta():
    est, resp, brief, perfiles = _b_corregida()
    assert D19.validar(resp, brief, CAT, perfiles, requisitos=est["carga"]["requisitos"]) == []


@pytest.mark.parametrize("cita,cantidad,regla", [
    # I1.8 (REV17-7): la base cuenta consultas y estas citas cuentan técnicos: el número no es el de su unidad
    ("entre 50 y 100 técnicos.", 50, "cantidad_sin_su_unidad"),   # el valor anonimizado que vio el experto en el brief
    ("60 técnicos.", 60, "cantidad_sin_su_unidad"),               # el valor de requisitos
    ("entre 50 y 100 técnicos.", 60, "cantidad_no_en_cita"),
    ("Unos 60 técnicos en planta", 60, "cita_no_literal"),
    ("  Aproximadamente   2.000 consultas al mes. ", 2000, None)])  # espacios colapsados
def test_la_cita_es_literal_y_el_numero_esta_en_ella(cita, cantidad, regla):
    est, resp, brief, _ = _b_corregida()
    _p(resp, "P-03")["base_volumen"].update(cita=cita, cantidad_base=cantidad)
    _p(resp, "P-03")["cantidad_mensual"] = cantidad / 1000
    reglas = [r for i, r in _reglas(resp, est, brief) if i == "P-03"]
    assert reglas == ([regla] if regla else []), reglas


@pytest.mark.parametrize("cantidad,ok", [(6, True), (6.004, True), (6.02, True), (6.1, False), (5, False), (6000, False)])
def test_el_nucleo_rehace_la_cuenta_y_solo_admite_el_redondeo(cantidad, ok):
    est, resp, brief, _ = _b_corregida()
    _p(resp, "P-04")["cantidad_mensual"] = cantidad
    assert (("P-04", "cuenta_no_cuadra") not in _reglas(resp, est, brief)) is ok


def test_base_volumen_en_un_medidor_de_tiempo_se_rechaza():
    est, resp, brief, _ = _b_corregida()
    _p(resp, "P-01")["base_volumen"] = copy.deepcopy(_p(resp, "P-03")["base_volumen"])  # AI Search S1, por horas
    assert ("P-01", "base_en_tiempo") in _reglas(resp, est, brief)


def test_precio_de_referencia_solo_con_depende_del_volumen_y_sin_base():
    est, resp, brief, _ = _b_corregida()
    _p(resp, "P-04")["cantidad_mensual"] = None  # Foundry con motivo «no_aplica»
    reglas = _reglas(resp, est, brief)
    assert ("P-04", "referencia_sin_depende") in reglas and ("P-04", "referencia_con_base") in reglas


def test_depende_del_volumen_con_volumetria_asumida_y_precio_de_referencia_vale():
    est, resp, brief, _ = _b_corregida()
    req = copy.deepcopy(est["carga"]["requisitos"])
    req["campos"]["volumetria"]["estado"] = "ASUMIDO"
    _c(resp, "C-05")["motivo_no_valoracion"] = "depende_del_volumen"
    for pid in ("P-04", "P-05"):
        _p(resp, pid).update(cantidad_mensual=None, base_volumen=None)
    assert [x for x in _reglas(resp, est, brief, req) if x[0] == "C-05" or x[0] in ("P-04", "P-05")] == []
    resp["precios"] = [p for p in resp["precios"] if p["componente_id"] != "C-05"]
    assert ("C-05", "depende_sin_precio_unitario") in _reglas(resp, est, brief, req)


def test_sin_requisitos_la_volumetria_se_lee_del_brief():
    est, resp, brief, _ = _real("B")
    assert experto.estado_volumetria(None, brief["texto"]) == "CITADO"
    assert ("C-05", "depende_con_volumetria_citada") in _reglas(resp, est, brief, requisitos=None)
    asumido = brief["texto"].replace("consultas al mes.\n", "consultas al mes." + experto.MARCA_ASUMIDO + "\n", 1)
    assert experto.estado_volumetria(None, asumido) == "ASUMIDO"
    assert experto.estado_volumetria(None, "BRIEF\n---\n## Necesidad") == "FALTA"


def test_plantilla_sin_impulsor_o_con_divisor_invalido_falla_cerrado():
    est, resp, brief, _ = _b_corregida()
    cat = copy.deepcopy(CAT)
    fila = next(e for e in cat["componentes"] if e["id"] == "az-foundry")
    pl = next(p for p in fila["plantillas_precio"] if p["id"] == "gpt-5-entrada")
    del pl["impulsor"]
    assert ("P-04", "plantilla_sin_impulsor") in [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(
        resp, brief["texto"], est["carga"]["requisitos"], cat)]
    for malo in ({"divisor": 0}, {"divisor": True}, {"divisor": 1000.0}, {"divisor": "1000"}, {},
                 {"impulsor": "tiempo", "divisor": 1000}):  # contrato de E: entero ≥ 1 y 1 en las de tiempo
        assert experto.divisor_de(malo) is None, malo
    assert experto.divisor_de({"impulsor": "volumen", "divisor": 10000}) == 10000
    pl["divisor"] = 1000.0
    assert ("P-04", "plantilla_sin_impulsor") in [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(
        resp, brief["texto"], est["carga"]["requisitos"], cat)]


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): poner a null la cantidad de precios de tiempo (en v4 el núcleo calcula 730 h × instancias); imposible por construcción con el contrato v4 (el modelo ya no escribe filtro, precio, concepto ni cantidad). Lo vigente: PR14-1 con precios vacíos en tests/test_i15_p_cobertura_precios.py::test_pr14_1_sigue_vigente_aunque_todos_declaren_motivo")
def test_pr14_1_solo_cuentan_los_precios_que_suman():
    est, resp, brief, perfiles = _real("B")
    for p in resp["precios"]:
        p["cantidad_mensual"] = None
    errores = D19.validar(resp, brief, CAT, perfiles, requisitos=est["carga"]["requisitos"])
    assert any(e.startswith("precios: no hay ningún precio de consumo") for e in errores), errores


def test_numeros_en_espanol():
    assert experto.numeros_en("unos 3.000 documentos y 2.000 consultas, 1,5 h, 2.5 GB y 1,000,000") == [
        Decimal(3000), Decimal(2000), Decimal("1.5"), Decimal("2.5")]
    assert experto.numeros_en("entre 50 y 100 técnicos.") == [Decimal(50), Decimal(100)]
    assert experto.numeros_en(None) == []


def test_esquema_v3_concepto_libre_cantidad_nula_y_claves_nuevas_obligatorias():
    # integrador I1.7: el contrato v3 queda como histórico (respuestas guardadas de I1.6)
    e = __import__("json").loads((D.RAIZ / "esquemas" / "historico" / "respuesta_experto_v3.json").read_text(encoding="utf-8"))
    assert e["$id"].endswith(":3")
    precio, comp = e["$defs"]["precio"], e["$defs"]["componente"]
    assert precio["properties"]["concepto"] == {"type": ["string", "null"]}  # nunca un rechazo por concepto
    assert "base_volumen" in precio["required"] and "justificacion_nivel" in comp["required"]
    _, resp, _, _ = _real("B")
    _p(resp, "P-02")["concepto"] = "B1"
    _p(resp, "P-01")["cantidad_mensual"] = None
    assert list(esquema.validar(resp, e)) == []
    _p(resp, "P-01")["cantidad_mensual"] = 0
    assert any("P" in x or "precios" in x for x in esquema.validar(resp, e))


def test_el_historico_v2_valida_la_respuesta_real_de_su_epoca_y_la_v3_no():
    v2 = __import__("json").loads((D.RAIZ / "esquemas" / "historico" / "respuesta_experto_v2.json").read_text(encoding="utf-8"))
    assert v2["$id"].endswith(":2") and v2["description"].startswith("HISTÓRICO")
    real = D.paquete_real("B")["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    assert list(esquema.validar(real, v2)) == []
    faltan = list(esquema.validar(real, esquema.cargar("respuesta_experto")))
    assert any("justificacion_nivel" in x for x in faltan) and any("base_volumen" in x for x in faltan)


def test_requisitos_sin_el_campo_volumetria_no_degradan_el_brief_citado():
    """Revisión (I1.6): unos requisitos sin el campo no pueden convertir en FALTA una volumetría que el brief cita."""
    est, resp, brief, _ = _real("B")
    assert experto.estado_volumetria({"campos": {}}, brief["texto"]) == "CITADO"
    assert ("C-05", "depende_con_volumetria_citada") in _reglas(resp, est, brief, requisitos={"campos": {}})
