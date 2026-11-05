"""I1.8 · papel P: REV17-4 (lo conservado se casa por servicio, componente y plantilla) y REV17-5 (lo valorado se separa
de lo que es solo precio de referencia). experto.conservar_de compone el dato y experto.conservacion_efecto lo aplica;
la réplica de la puerta (conservacion_replica) da lo mismo en cada caso."""
from __future__ import annotations

import copy

import pytest

from tests.i18_p_datos import R, analizar, base
from nucleo import experto
from nucleo.errores import IntegridadRota


def _resp(precios: list[tuple]) -> dict:
    comps = {"C-03": "az-storage", "C-04": "az-storage", "C-05": "az-foundry"}
    return {"componentes": [{"id": c, "catalogo_id": cat} for c, cat in comps.items()],
            "precios": [{"id": i, "componente_id": c, "plantilla_id": pl, "cantidad_mensual": q} for i, c, pl, q in precios]}


DOS_CUENTAS = [("P-01", "C-03", "hot-lrs-datos", 500), ("P-02", "C-04", "hot-lrs-datos", 20),
               ("P-03", "C-05", "gpt-6-luna-entrada", 11.312)]


def _comprobar(resp: dict, conservar) -> list[tuple]:
    nucleo = [(x["id"], x["regla"]) for x in experto.conservacion_efecto(resp, conservar)]
    assert nucleo == R.conservacion_replica(resp, conservar)
    assert nucleo == [(x["id"], x["regla"]) for x in experto.errores_conservacion(resp, conservar)]
    return nucleo


def test_rev17_4_el_dato_va_por_componente():
    dato = experto.conservar_de(_resp(DOS_CUENTAS), ["P-01", "P-03"])     # C-04 tiene una corrección
    assert dato == [{"catalogo_id": "az-storage", "plantilla_id": "hot-lrs-datos", "filtro": None, "cantidad_mensual": 500,
                     "precio_ids": ["P-01"], "componente_ids": ["C-03"]},
                    {"catalogo_id": "az-foundry", "plantilla_id": "gpt-6-luna-entrada", "filtro": None,
                     "cantidad_mensual": 11.312, "precio_ids": ["P-03"], "componente_ids": ["C-05"]}]


def test_rev17_4_corregir_la_otra_cuenta_de_la_misma_plantilla_ya_no_bloquea():
    resp = _resp(DOS_CUENTAS)
    dato = experto.conservar_de(resp, ["P-01", "P-03"])
    assert _comprobar(copy.deepcopy(resp), dato) == []                    # I1.7: «conservado_cambiado» sin arreglo
    otra = _resp([("P-01", "C-03", "hot-lrs-datos", 500), ("P-02", "C-04", "hot-lrs-datos", 80),
                  ("P-03", "C-05", "gpt-6-luna-entrada", 11.312)])
    assert _comprobar(otra, dato) == []                                   # la corregida cambia libremente


def test_rev17_4_cambiar_o_mover_lo_conservado_sigue_fallando():
    dato = experto.conservar_de(_resp(DOS_CUENTAS), ["P-01", "P-03"])
    cambiada = _resp([("P-01", "C-03", "hot-lrs-datos", 5000), ("P-02", "C-04", "hot-lrs-datos", 20),
                      ("P-03", "C-05", "gpt-6-luna-entrada", 11.312)])
    assert _comprobar(cambiada, dato) == [("az-storage · hot-lrs-datos · C-03", "conservado_cambiado")]
    movida = _resp([("P-02", "C-04", "hot-lrs-datos", 520), ("P-03", "C-05", "gpt-6-luna-entrada", 11.312)])
    assert _comprobar(movida, dato) == [("az-storage · hot-lrs-datos · C-03", "conservado_ausente")]
    duplicada = _resp(DOS_CUENTAS + [("P-04", "C-03", "hot-lrs-datos", 4500)])
    assert _comprobar(duplicada, dato) == [("az-storage · hot-lrs-datos · C-03", "conservado_cambiado")]
    renumerada = _resp([("P-09", "C-03", "hot-lrs-datos", 500), ("P-08", "C-05", "gpt-6-luna-entrada", 11.312)])
    assert _comprobar(renumerada, dato) == []


def test_rev17_5_un_precio_de_referencia_no_absorbe_al_valorado():
    resp = _resp([("P-01", "C-05", "gpt-6-luna-entrada", 16.968), ("P-02", "C-05", "gpt-6-luna-entrada", None)])
    dato = experto.conservar_de(resp)
    assert [x["cantidad_mensual"] for x in dato] == [16.968, None]
    x10 = _resp([("P-01", "C-05", "gpt-6-luna-entrada", 169.68), ("P-02", "C-05", "gpt-6-luna-entrada", None)])
    assert _comprobar(x10, dato) == [("az-foundry · gpt-6-luna-entrada · C-05", "conservado_cambiado")]
    sin_ref = _resp([("P-01", "C-05", "gpt-6-luna-entrada", 16.968)])
    assert _comprobar(sin_ref, dato) == [("az-foundry · gpt-6-luna-entrada · C-05 (precio de referencia)",
                                          "conservado_ausente")]
    a_referencia = _resp([("P-01", "C-05", "gpt-6-luna-entrada", None)])
    assert _comprobar(a_referencia, dato) == [("az-foundry · gpt-6-luna-entrada · C-05", "conservado_ausente")]


def test_forma_del_dato_falla_cerrado():
    resp = _resp(DOS_CUENTAS)
    assert _comprobar(resp, None) == []
    assert _comprobar(resp, {"x": 1}) == [("conservar_precios", "conservar_forma")]
    for comps_mal in ([], "C-03", [3], None):
        mal = [{"catalogo_id": "az-storage", "plantilla_id": "hot-lrs-datos", "filtro": None, "cantidad_mensual": 500,
                "componente_ids": comps_mal}]
        assert _comprobar(resp, mal) == [("conservar_precios[0]", "conservar_forma")], comps_mal
    sin_clave = [{"catalogo_id": "az-storage", "plantilla_id": "hot-lrs-datos", "filtro": None, "cantidad_mensual": 520}]
    assert _comprobar(resp, sin_clave) == []                              # dato de I1.6: todos los de su catalogo_id
    assert _comprobar(_resp(DOS_CUENTAS[:1]), sin_clave) == [("az-storage · hot-lrs-datos", "conservado_cambiado")]
    texto = [{"catalogo_id": "az-storage", "plantilla_id": "hot-lrs-datos", "filtro": None, "cantidad_mensual": "500",
              "componente_ids": ["C-03"]}]
    assert _comprobar(resp, texto) == [("conservar_precios", "conservar_forma")]
    assert _comprobar(resp, [dict(texto[0], cantidad_mensual=float("nan"))]) == [("conservar_precios", "conservar_forma")]


def test_dato_de_i17_con_varios_componentes_se_compara_contra_su_suma():
    viejo = [{"catalogo_id": "az-storage", "plantilla_id": "hot-lrs-datos", "filtro": None, "cantidad_mensual": 520,
              "precio_ids": ["P-01", "P-02"], "componente_ids": ["C-03", "C-04"]}]
    assert _comprobar(_resp(DOS_CUENTAS), viejo) == []
    assert _comprobar(_resp(DOS_CUENTAS[:1]), viejo) == [("az-storage · hot-lrs-datos · C-03, C-04", "conservado_cambiado")]


def test_conservar_de_falla_en_alto_con_una_cantidad_no_numerica():
    with pytest.raises(IntegridadRota):
        experto.conservar_de(_resp([("P-01", "C-03", "hot-lrs-datos", "500")]))


def test_registrar_aplica_la_regla_nueva_con_el_dato_del_brief():
    brief, req, r, cat = base()
    errores, c = analizar(r, brief, req, cat)
    assert errores == []
    brief["conservar_precios"] = experto.conservar_de(c, [p["id"] for p in c["precios"] if p["componente_id"] != "C-01"])
    assert analizar(r, brief, req, cat)[0] == []
    r["precios"][2]["plantilla_id"] = "s1"
    assert any("az-ai-search · basic · C-02 desaparece" in e for e in analizar(r, brief, req, cat)[0])
