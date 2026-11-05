"""I1.8 · papel P: REV17-3 en la suficiencia. «ya_contratado_por_cliente» (lo que el cliente ya tiene o paga) es un campo
opcional de requisitos que solo se acepta con cita literal de la fuente: ni se asume ni lo escribe el modelo como
ASUMIDO. Es la única cita que admite «a_cargo_del_cliente» en el experto."""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from tests.i17_p_datos import estado_brezalia
from nucleo import esquema, experto, suficiencia
from nucleo.errores import EntradaInvalida, ReglaIncumplida

FRASE = "Log Analytics ya lo pagamos nosotros desde la suscripción de sistemas"


def _estado_y_fuentes():
    est = estado_brezalia()
    req = copy.deepcopy(est["carga"]["requisitos"])
    citas = [e["cita"] for c in req["campos"].values() for e in c["entradas"] if e.get("cita")]
    fuentes = {f["id"]: " ".join(citas) + " " + FRASE + "." for f in est["carga"]["fuentes"]}
    return est, req, fuentes


CAT = json.loads((pathlib.Path(__file__).resolve().parents[1] / "sandbox" / "datos" / "catalogo_componentes.json")
                 .read_text(encoding="utf-8"))


def _entrada(origen="CITADO", cita=FRASE):
    """I1.9 (PR18-1): una entrada por recurso, con id, servicio del catálogo, fragmento literal y la cita entera."""
    return {"id": "EX-01", "servicio_catalogo": "az-log-analytics", "valor": "Log Analytics", "cita": cita,
            "fuente": None if origen == "ASUMIDO" else "F1", "origen": origen}


def test_el_campo_es_opcional_y_esta_en_todas_las_listas():
    assert experto.CAMPO_CLIENTE in suficiencia.OPCIONALES and experto.CAMPO_CLIENTE in suficiencia.SOLO_CITADOS
    assert experto.CAMPO_CLIENTE not in suficiencia.ASUMIBLES + suficiencia.BLOQUEANTES
    assert experto.CAMPO_CLIENTE in experto.CAMPOS_REQUISITOS and set(suficiencia.CAMPOS) == set(experto.CAMPOS_REQUISITOS)
    esq = esquema.cargar("requisitos")
    assert experto.CAMPO_CLIENTE in esq["properties"]["campos"]["properties"]
    assert experto.CAMPO_CLIENTE not in esq["properties"]["campos"]["required"]
    assert f'"{experto.CAMPO_CLIENTE}"' in suficiencia.forma_minima()
    assert "ya tiene o paga el cliente" in suficiencia.preguntas_para(experto.CAMPO_CLIENTE)


def test_con_cita_literal_se_acepta_y_no_cuenta_como_falta():
    est, req, fuentes = _estado_y_fuentes()
    req["campos"][experto.CAMPO_CLIENTE] = {"estado": "CITADO", "entradas": [_entrada()]}
    res = suficiencia.aplicar(est, req, fuentes, CAT)
    assert res.citas_invalidas == [] and experto.CAMPO_CLIENTE not in res.faltan
    assert est["carga"]["requisitos"]["campos"][experto.CAMPO_CLIENTE]["estado"] == "CITADO"
    assert list(experto.existentes_req(est["carga"]["requisitos"])) == ["EX-01"]


def test_sin_el_campo_los_requisitos_siguen_validando():
    est, req, fuentes = _estado_y_fuentes()
    req["campos"].pop(experto.CAMPO_CLIENTE, None)
    assert suficiencia.aplicar(est, req, fuentes).citas_invalidas == []


def test_asumido_escrito_por_el_modelo_se_rechaza_con_su_motivo():
    est, req, fuentes = _estado_y_fuentes()
    req["campos"][experto.CAMPO_CLIENTE] = {"estado": "ASUMIDO", "entradas": [_entrada("ASUMIDO", None)]}
    with pytest.raises(ReglaIncumplida, match="esquema") as e:   # I1.9: el esquema ya no admite ASUMIDO en el campo
        suficiencia.aplicar(est, req, fuentes, CAT)
    assert any("ASUMIDO" in x for x in e.value.errores)


def test_fernando_no_puede_asumirlo():
    est, req, fuentes = _estado_y_fuentes()
    suficiencia.aplicar(est, req, fuentes)
    with pytest.raises(EntradaInvalida):
        suficiencia.asumir(est, experto.CAMPO_CLIENTE, "El cliente ya paga Log Analytics")


def test_cita_que_no_esta_en_la_fuente_no_se_guarda():
    est, req, fuentes = _estado_y_fuentes()
    antes = json.dumps(est["carga"]["requisitos"], sort_keys=True)
    req["campos"][experto.CAMPO_CLIENTE] = {"estado": "CITADO", "entradas": [
        _entrada(cita="Log Analytics lo paga el cliente con todo el consumo de Azure")]}
    res = suficiencia.aplicar(est, req, fuentes, CAT)
    assert res.citas_invalidas and json.dumps(est["carga"]["requisitos"], sort_keys=True) == antes
