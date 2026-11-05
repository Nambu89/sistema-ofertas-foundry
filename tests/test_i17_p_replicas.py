"""I1.7 · papel P: pruebas de igualdad entre el núcleo y las réplicas para la puerta (docs/I1/CAMBIOS-I17-P/
replicas_puerta.py). Cada caso adverso también tiene su resultado esperado en las pruebas del núcleo (LES-G-096.6: dos
réplicas que se equivocan igual dan verde). Cuando el integrador las pegue en verificar_paquete.py, R pasa a ser `vp`."""
from __future__ import annotations

import copy
import sys
from decimal import Decimal

import pytest

from tests import i17_p_datos as D
from tests.test_i17_p_completar import BRIEF, CAT, HOY, INST, REQ, c_, p_, resp
from nucleo import experto  # noqa: E402

# Integrador I1.7: las réplicas ya están pegadas en la puerta; se prueban allí (antes, replicas_puerta.py)
import verificar_paquete as _vp  # noqa: E402

if hasattr(_vp, "servicios_nombrados_r"):
    R = _vp
else:  # I1.8 (papel P): hasta que el integrador pegue docs/I1/CAMBIOS-I18-P/replicas_puerta.py, sus réplicas encima
    import types
    sys.path.insert(0, str(D.RAIZ / "docs" / "I1" / "CAMBIOS-I18-P"))
    import replicas_puerta as _r18  # noqa: E402
    R = types.SimpleNamespace(**{**vars(_vp), **{k: x for k, x in vars(_r18).items() if not k.startswith("__")}})
if not hasattr(_vp, "existentes_r"):  # I1.9 (papel P): hasta que se peguen las réplicas de I1.9, encima de la puerta
    import types
    from tests.i19_p_datos import R19 as _r19  # noqa: E402
    R = types.SimpleNamespace(**{**{k: getattr(R, k) for k in dir(R) if not k.startswith("__")},
                                 **{k: x for k, x in vars(_r19).items() if not k.startswith("__")}})


def _fila(cat, cid):
    return next(e for e in cat["componentes"] if e["id"] == cid)


def _sin_factores(cat):
    _fila(cat, "az-foundry").pop("factores_estandar")


def _override(r, cita="Unas 2.000 consultas al mes.", valor=3000):
    p_(r, "P-01")["factor_override"] = {"valor": valor, "cita": cita, "justificacion": "Justificación de prueba larga."}


MUTACIONES = {
    "control": (lambda r: None, None, None),
    "comillas": (lambda r: p_(r, "P-01")["base_volumen"].update(cita="«Unas 2.000 consultas al mes.»"), None, None),
    "comillas_nivel": (lambda r: c_(r, "C-02").update(justificacion_nivel={  # I1.9: la cita de la justificación v5
        "nivel": "Basic", "razon": "sla_replicas", "cita": "“Unos 3.000 documentos.”"}), None, None),
    "plantilla_otra_fila": (lambda r: p_(r, "P-01").update(plantilla_id="basic"), None, None),
    "plantilla_prefijo": (lambda r: p_(r, "P-03").update(plantilla_id="az-ai-search/basic"), None, None),
    "auxiliar": (lambda r: r["precios"].append({"id": "P-06", "componente_id": "C-02", "plantilla_id": "punto-conexion",
                                                "instancias": 3, "base_volumen": None, "factor_override": None}), None, None),
    "region": (lambda r: c_(r, "C-02").update(region="westeurope"), None, None),
    "instancias_volumen": (lambda r: p_(r, "P-01").update(instancias=2), None, None),
    "base_tiempo": (lambda r: p_(r, "P-03").update(base_volumen=copy.deepcopy(D.CONSULTAS)), None, None),
    "instancias_fraccion": (lambda r: p_(r, "P-05").update(instancias=2.5), None, None),
    "referencia_modelo": (lambda r: c_(r, "C-05").update(referencia_id="REF-01"), None, None),
    "sin_refs": (lambda r: (r.update(referencias=[]), r["supuestos"][0].update(hechos=["R-alcance_funcional"])), None, None),
    "override": (_override, None, None),
    "override_sin_estandar": (_override, _sin_factores, None),
    "sin_estandar": (lambda r: None, _sin_factores, None),
    "override_no_dim": (lambda r: _override(r, cita="Plazo deseado de unas 8 semanas."), None, None),
    "base_no_casa": (lambda r: p_(r, "P-01").update(base_volumen={"cita": "Unos 3.000 documentos.", "cantidad_base": 3000,
                                                                   "unidad_base": "consultas"}), None, None),
    "referencia_sin_depende": (lambda r: p_(r, "P-01").update(base_volumen=None), None, None),
    "arquitectura": (lambda r: r.update(arquitectura_id="otra"), None, None),
    "unidad_dia": (lambda r: None, None, lambda i: i["plantillas"]["az-ai-search/basic"].update(unidad="1/Day")),
    "unidad_rara": (lambda r: None, None, lambda i: i["plantillas"]["az-ai-search/basic"].update(unidad="1/Week")),
    "tramos": (lambda r: None, None, lambda i: i["plantillas"]["az-bot-service/canales-estandar"].update(
        precio_unitario=0.0, tramos=[{"desde": 0.0, "precio_unitario": 0.0}, {"desde": 1.0, "precio_unitario": 0.5}])),
    "factor_enorme": (lambda r: None, lambda cat: _fila(cat, "az-foundry")["factores_estandar"][0].update(valor=1e30), None),
    "gpt5": (lambda r: p_(r, "P-01").update(plantilla_id="gpt-5-entrada"),
             lambda cat: _fila(cat, "az-foundry")["factores_estandar"].append(dict(D.FACTOR_ENTRADA, plantillas=["gpt-5-entrada"])),
             None),
}


def _caso(nombre):
    mod_r, mod_cat, mod_inst = MUTACIONES[nombre]
    r, cat, inst = resp(), copy.deepcopy(CAT), copy.deepcopy(INST)
    mod_r(r)
    if mod_cat:
        mod_cat(cat)
    if mod_inst:
        mod_inst(inst)
        D.resellar(inst)
    return r, cat, inst


@pytest.mark.parametrize("nombre", sorted(MUTACIONES))
def test_completar_y_proyectar_iguales_al_nucleo(nombre):
    r, cat, inst = _caso(nombre)
    c_n, e_n = experto.completar(r, cat, inst, REQ, BRIEF["texto"])
    c_r, e_r = R.completar_r(r, cat, inst, REQ, BRIEF["texto"])
    assert c_r == c_n
    assert e_r == [(x["id"], x["regla"]) for x in e_n]
    assert R.proyectar_r(c_n) == experto.proyectar_modelo(c_n) == r


@pytest.mark.parametrize("nombre", sorted(MUTACIONES))
def test_reglas_iguales_al_nucleo(nombre):
    r, cat, inst = _caso(nombre)
    c, _ = experto.completar(r, cat, inst, REQ, BRIEF["texto"])
    semanas = experto.duracion_gantt(r)
    assert R.semanas_r(r) == semanas
    assert R.ciclo_r(c, cat, HOY, semanas) == [(x["id"], x["regla"]) for x in experto.errores_ciclo_vida(c, cat, HOY, semanas)]
    assert R.motivos_r(c, cat, REQ, BRIEF["texto"]) == [(x["id"], x["regla"]) for x in
                                                         experto.errores_motivos(c, cat, REQ, BRIEF["texto"])]


def _motivo(r, cid, motivo, **extra):
    r["precios"] = [p for p in r["precios"] if p["componente_id"] != cid]
    c_(r, cid).update({"motivo_no_valoracion": motivo, **extra})


MOTIVOS = {
    "cliente_sin_cita": lambda r: _motivo(r, "C-02", "a_cargo_del_cliente"),
    "cliente_no_literal": lambda r: _motivo(r, "C-02", "a_cargo_del_cliente", motivo_cita="Lo paga el cliente."),
    "cliente_literal": lambda r: _motivo(r, "C-02", "a_cargo_del_cliente",
                                         motivo_cita="«Los documentos están en SharePoint Online del tenant.»"),
    "incluido_ok": lambda r: r["componentes"].append(dict(copy.deepcopy(c_(r, "C-01")), id="C-07", catalogo_id="az-content-safety",
                                                          motivo_no_valoracion="incluido_en_otro_componente", incluido_en="C-01")),
    "incluido_no_declarado": lambda r: _motivo(r, "C-03", "incluido_en_otro_componente", incluido_en="C-01"),
    "incluido_sin": lambda r: _motivo(r, "C-03", "incluido_en_otro_componente"),
    "incluido_si_mismo": lambda r: _motivo(r, "C-03", "incluido_en_otro_componente", incluido_en="C-03"),
    "sobrantes": lambda r: c_(r, "C-05").update(motivo_cita="Microsoft Teams", incluido_en="C-01"),
}


@pytest.mark.parametrize("nombre", sorted(MOTIVOS))
def test_motivos_iguales_al_nucleo(nombre):
    r = resp()
    MOTIVOS[nombre](r)
    c, _ = experto.completar(r, CAT, INST, REQ, BRIEF["texto"])
    esperado = [(x["id"], x["regla"]) for x in experto.errores_motivos(c, CAT, REQ, BRIEF["texto"])]
    assert R.motivos_r(c, CAT, REQ, BRIEF["texto"]) == esperado
    assert (esperado == []) == (nombre == "incluido_ok")  # I1.8 (REV17-3): «cliente_literal» cita otro campo


def test_citas_urls_comillas_y_tramos_iguales_al_nucleo():
    for req in (REQ, None):
        assert R.citas_dim_r(req, BRIEF["texto"]) == experto.citas_dimensionamiento(req, BRIEF["texto"])
    urls = ["https://learn.microsoft.com/es-es/azure/search/x/", "https://learn.microsoft.com/zh-hans/azure/a?b=1#c",
            "http://learn.microsoft.com/azure", "https://learn.microsoft.com.evil.example/azure", "https://learn.microsoft.com/azure/../x",
            "https://learn.microsoft.com:8443/azure", "https://LEARN.microsoft.com/AZURE/Search", None, 5, ""]
    assert [R.url_r(u) for u in urls] == [experto.normalizar_url(u) if isinstance(u, str) or u is None else "" for u in urls]
    textos = ["«a»", " «a» ", "«a» y «b»", '"a"', "“a”", "'a'", "‘a’", "„a“", "«a", "a»", "«»", "«", None, 3, "«a»»"]
    assert [R.sin_comillas_r(t) for t in textos] == [experto.quitar_comillas(t) for t in textos]
    art = {"precio_unitario": 0.0, "tramos": [{"desde": 0.0, "precio_unitario": 0.0}, {"desde": 5.0, "precio_unitario": 2.6311},
                                              {"desde": 100, "precio_unitario": 1.1}]}
    for q in (None, Decimal("0.5"), Decimal(5), Decimal("7.25"), Decimal(150), Decimal("1e9")):
        assert R.tramos_r(q, art) == experto.precio_medio(q, art)


@pytest.mark.parametrize("fecha, semanas", [("2026-10-13", 8), ("2028-02-29", 0), ("2026-12-31", 52), ("x", 3)])
def test_limite_igual_al_nucleo(fecha, semanas):
    assert R.limite_r(fecha, semanas) == experto.limite_retirada(fecha, semanas)
