"""Arreglos I1.6 (pruebas/I16/ARREGLOS.md): PR16-1, REV16-1 y PR16-3 en el núcleo y en la réplica de la puerta.

- PR16-1: la referencia de un componente con catalogo_id es EXACTAMENTE la `referencia_url` de su fila. Control con las
  respuestas reales de I1.6 (LES-G-078): las de B rechazan SharePoint, Entra ID y Foundry con páginas ajenas.
- REV16-1: «licencia_fuera_de_azure» y «sin_medidor_publico» se comprueban contra el catálogo; «a_cargo_del_cliente» e
  «incluido_en_otro_componente» quedan pendientes de un dato del contrato (XFAIL estrictas: decide el PM).
- PR16-3: los precios ya verificados se conservan (filtro, cantidad y base) entre rondas; el brief lleva el dato.
Sin red."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
for _p_ in (RAIZ / "sandbox", RAIZ):
    if str(_p_) not in sys.path:
        sys.path.insert(0, str(_p_))
from nucleo import anexo_consumo, experto, verificacion  # noqa: E402
import verificar_paquete as vp  # noqa: E402

CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
FILAS = {e["id"]: e for e in CAT["componentes"]}
# integrador I1.7: las reglas de cobertura juzgan lo que guarda el núcleo (la respuesta completada del ejemplo)
EJEMPLO = json.loads((RAIZ / "esquemas" / "ejemplos" / "respuesta_experto_completa.json").read_text(encoding="utf-8"))
REAL = RAIZ / "pruebas" / "I16" / "REAL" / "B"
RESPUESTAS_REALES = sorted(REAL.glob("sesion_*/respuesta_experto_AZ_R*.json")) + sorted(
    REAL.glob("sesion_1/bloqueo/respuesta_experto_AZ_R*.json"))
# Lo que objetó el verificador en real (PRUEBA-REAL.md, VERIFICACION.md §2): tiene que salir siempre.
OBJETADOS = {("sesion_1/bloqueo", "R3"): {"C-03"}, ("sesion_2", "R1"): {"C-05", "C-06", "C-07"},
             ("sesion_2", "R2"): {"C-06", "C-07"}, ("sesion_2", "R3"): {"C-07"}}


def _leer(f: pathlib.Path) -> dict:
    d = json.loads(f.read_text(encoding="utf-8"))
    return d.get("respuesta", d)


def _c(r, i):
    return next(x for x in r["componentes"] if x["id"] == i)


def _p(r, i):
    return next(x for x in r["precios"] if x["id"] == i)


# ── PR16-1 ──────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not RESPUESTAS_REALES, reason="faltan las respuestas reales de I1.6")
@pytest.mark.parametrize("fichero", RESPUESTAS_REALES, ids=lambda f: f"{f.parent.name}/{f.name}")
def test_pr16_1_respuestas_reales(fichero):
    r = _leer(fichero)
    refs = {x["id"]: x["url"] for x in r["referencias"]}
    esperados = {c["id"] for c in r["componentes"] if c.get("catalogo_id") in FILAS
                 and experto.normalizar_url(refs[c["referencia_id"]])
                 != experto.normalizar_url(FILAS[c["catalogo_id"]]["referencia_url"])}
    hallados = experto.errores_referencia_catalogo(r, CAT)
    assert {x["id"] for x in hallados} == esperados
    assert all(x["regla"] == "referencia_no_catalogo" and "usa la referencia del catálogo: https://" in x["detalle"]
               for x in hallados)
    clave = ("sesion_1/bloqueo" if fichero.parent.name == "bloqueo" else fichero.parent.name, fichero.stem[-2:])
    assert OBJETADOS.get(clave, set()) <= esperados
    assert vp.referencia_catalogo_replica(r, CAT) == [(x["id"], x["regla"]) for x in hallados]


def test_pr16_1_con_la_referencia_del_catalogo_no_hay_error_y_sin_ella_falla_cerrado():
    r = copy.deepcopy(EJEMPLO)
    assert experto.errores_referencia_catalogo(r, CAT) == [] == vp.referencia_catalogo_replica(r, CAT)
    _c(r, "C-05")["referencia_id"] = "REF-01"  # Entra ID con la arquitectura de chat de Foundry
    assert [(x["id"], x["regla"]) for x in experto.errores_referencia_catalogo(r, CAT)] == [
        ("C-05", "referencia_no_catalogo")] == vp.referencia_catalogo_replica(r, CAT)
    cat = copy.deepcopy(CAT)
    next(e for e in cat["componentes"] if e["id"] == "az-entra-id")["referencia_url"] = ""
    assert vp.referencia_catalogo_replica(r, cat) == [("C-05", "catalogo_sin_referencia")]
    assert [x["regla"] for x in experto.errores_referencia_catalogo(r, cat)] == ["catalogo_sin_referencia"]


def test_pr16_1_idioma_y_mayusculas_no_cuentan_como_otra_pagina():
    r = copy.deepcopy(EJEMPLO)
    next(x for x in r["referencias"] if x["id"] == "REF-07")["url"] = (
        "https://learn.microsoft.com/es-es/Entra/Fundamentals/What-Is-Entra/")
    assert experto.errores_referencia_catalogo(r, CAT) == [] == vp.referencia_catalogo_replica(r, CAT)


# ── REV16-1 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def _sin_precio(comp_id: str, motivo: str, region: str | None = None) -> dict:
    r = copy.deepcopy(EJEMPLO)
    r["precios"] = [p for p in r["precios"] if p["componente_id"] != comp_id]
    _c(r, comp_id)["motivo_no_valoracion"] = motivo
    if region:
        _c(r, comp_id)["region"] = region
    return r


def _reglas(r):
    nucleo = [(x["componente_id"], x["regla"]) for x in anexo_consumo.errores_cobertura(r, CAT)]
    assert nucleo == vp.errores_cobertura_replica(r, CAT)
    return nucleo


@pytest.mark.parametrize("comp, motivo, region, regla", [
    ("C-01", "sin_medidor_publico", None, "medidor_publico_en_catalogo"),     # Foundry en su region_ue
    ("C-01", "licencia_fuera_de_azure", None, "licencia_con_precio_azure"),   # Foundry se factura por Azure
    ("C-03", "sin_medidor_publico", None, "medidor_publico_en_catalogo"),     # Bot Service: la fila fija «Global»
    ("C-02", "licencia_fuera_de_azure", None, "licencia_con_precio_azure"),   # AI Search
])
def test_rev16_1_motivo_que_contradice_el_catalogo(comp, motivo, region, regla):
    assert (comp, regla) in _reglas(_sin_precio(comp, motivo, region))


@pytest.mark.parametrize("comp, motivo, region", [
    ("C-01", "sin_medidor_publico", "westeurope"),   # región distinta de la de la fila (sin region_precio): se admite
    ("C-05", "licencia_fuera_de_azure", None),       # Entra ID no tiene servicio de precios: se admite
    ("C-05", "sin_medidor_publico", None),           # sin plantillas: se admite
])
def test_rev16_1_motivo_admitido(comp, motivo, region):
    assert not [x for x in _reglas(_sin_precio(comp, motivo, region))
                if x[1] in ("medidor_publico_en_catalogo", "licencia_con_precio_azure")]


def test_rev16_1_validar_respuesta_lo_rechaza_con_su_remedio():
    r = _sin_precio("C-01", "sin_medidor_publico")
    errores = [e for x in anexo_consumo.errores_cobertura(r, CAT) for e in [x["detalle"]]]
    # I1.7: el remedio ya no es «consulta su plantilla» (el experto no consulta precios): una línea de su plantilla
    assert any("valóralo con una línea de consumo de su plantilla" in e and "REV16-1" in e for e in errores), errores


# Integrador I1.7 (CAMBIOS-I17-P §5.7): las XFAIL de REV16-1 (c) se quitan; las cubre tests/test_i17_p_motivos_ciclo.py
# (decisión del PM: a_cargo_del_cliente exige cita y incluido_en_otro_componente la inclusión declarada con fuente).


def test_rev16_1_instrucciones_ya_no_empujan_a_sin_medidor_publico():
    texto = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md").read_text(encoding="utf-8")
    assert "también cuando no encuentras el precio" not in texto
    assert "`sin_medidor_publico` si no hay artículo o plantilla" not in texto
    assert "SOLO si el servicio no tiene plantillas en el bloque" in texto
