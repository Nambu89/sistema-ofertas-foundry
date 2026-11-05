"""I1.7 · Papel R · conservación entre rondas POR EFECTO (LES-G-100.6, REVERIF16-1 y REVERIF16-2).

Por cada servicio del catálogo y plantilla, la cantidad mensual TOTAL de la respuesta nueva tiene que ser la conservada.
Núcleo (verificacion.errores_conservacion_efecto) y réplica de la puerta (conservacion_replica) con los mismos casos y el
mismo resultado. Contrato v4 (plantilla_id) y forma anterior (filtro). Sin red.

I1.8 (integrador): verificacion delega en experto.conservacion_efecto (REV17-4 y REV17-5); el id de cada error lleva el
componente («catalogo_id · plantilla · C-nn»)."""
from __future__ import annotations

import copy

import pytest

from tests.test_i13_convergencia import OTRA, ejemplo, m  # noqa: F401
from tests.test_i1_verificacion_lotes import _cons, _registrar, _resp

from nucleo import verificacion  # noqa: E402
import verificar_paquete as vp  # noqa: E402

V4 = {"componentes": [{"id": "C-01", "catalogo_id": "az-foundry"}, {"id": "C-02", "catalogo_id": "az-ai-search"}],
      "precios": [{"id": "P-01", "componente_id": "C-01", "plantilla_id": "gpt-6-luna-entrada", "cantidad_mensual": 8},
                  {"id": "P-02", "componente_id": "C-01", "plantilla_id": "gpt-6-luna-salida", "cantidad_mensual": 1},
                  {"id": "P-03", "componente_id": "C-02", "plantilla_id": "basic", "cantidad_mensual": 730}]}
CONSERVAR = [{"catalogo_id": "az-foundry", "plantilla_id": "gpt-6-luna-entrada", "filtro": None, "cantidad_mensual": 8,
              "precio_ids": ["P-01"], "componente_ids": ["C-01"]},
             {"catalogo_id": "az-ai-search", "plantilla_id": "basic", "filtro": None, "cantidad_mensual": 730,
              "precio_ids": ["P-03"], "componente_ids": ["C-02"]}]


def _ambos(r: dict, conservar: object) -> list[tuple[str, str]]:
    nucleo = [(x["id"], x["regla"]) for x in verificacion.errores_conservacion_efecto(r, conservar)]
    assert nucleo == vp.conservacion_replica(r, conservar), (nucleo, vp.conservacion_replica(r, conservar))
    return nucleo


def _mut(f) -> dict:
    r = copy.deepcopy(V4)
    f(r)
    return r


def test_misma_respuesta_y_ids_renumerados_pasan():
    assert _ambos(V4, CONSERVAR) == []
    r = _mut(lambda r: [p.update(id=f"P-{9 - n:02d}") for n, p in enumerate(r["precios"])])
    assert _ambos(r, CONSERVAR) == []
    r = _mut(lambda r: (r["componentes"][0].update(id="C-07"), [p.update(componente_id="C-07") for p in r["precios"]
                                                                if p["componente_id"] == "C-01"]))
    # I1.8 (REV17-4, P18-5): se casa por componente; renumerar el componente ya no conserva (sí los precios)
    assert _ambos(r, CONSERVAR) == [("az-foundry · gpt-6-luna-entrada · C-01", "conservado_ausente")]


def test_duplicado_coherente_cambia_el_total_reverif16_1():
    dup = {"id": "P-99", "componente_id": "C-01", "plantilla_id": "gpt-6-luna-entrada", "cantidad_mensual": 80}
    assert _ambos(_mut(lambda r: r["precios"].append(dup)), CONSERVAR) == [
        ("az-foundry · gpt-6-luna-entrada · C-01", "conservado_cambiado")]


def test_partir_un_precio_en_dos_con_el_mismo_total_pasa():
    def partir(r):
        r["precios"][0]["cantidad_mensual"] = 5
        r["precios"].append({"id": "P-09", "componente_id": "C-01", "plantilla_id": "gpt-6-luna-entrada",
                             "cantidad_mensual": 3})
    assert _ambos(_mut(partir), CONSERVAR) == []


@pytest.mark.parametrize("mutar, esperado", [
    (lambda r: r["precios"].pop(0), [("az-foundry · gpt-6-luna-entrada · C-01", "conservado_ausente")]),
    (lambda r: r["precios"][0].update(componente_id="C-02"), [("az-foundry · gpt-6-luna-entrada · C-01", "conservado_ausente")]),
    (lambda r: r["precios"][0].update(plantilla_id="gpt-6-sol-entrada"),
     [("az-foundry · gpt-6-luna-entrada · C-01", "conservado_ausente")]),
    (lambda r: r["precios"][2].update(cantidad_mensual=1460), [("az-ai-search · basic · C-02", "conservado_cambiado")]),
    (lambda r: r["precios"][0].update(cantidad_mensual=8.0000001), []),                 # a 6 decimales
    (lambda r: r["precios"][0].update(cantidad_mensual=8.00001), [("az-foundry · gpt-6-luna-entrada · C-01",
                                                                   "conservado_cambiado")]),
    # I1.8 (REV17-5): sin cantidad pasa a precio de referencia y el valorado desaparece
    (lambda r: r["precios"][0].update(cantidad_mensual=None), [("az-foundry · gpt-6-luna-entrada · C-01",
                                                               "conservado_ausente")]),
    (lambda r: r["precios"][0].update(cantidad_mensual="8"), [("az-foundry · gpt-6-luna-entrada · C-01",
                                                              "conservado_cambiado")]),
    (lambda r: r["precios"][1].update(cantidad_mensual=99), []),       # salida no estaba en conservar
])
def test_casos_adversos_de_la_respuesta(mutar, esperado):
    assert _ambos(_mut(mutar), CONSERVAR) == esperado


@pytest.mark.parametrize("conservar, esperado", [
    (None, []),                                                         # brief sin la clave: nada que conservar
    ([], []),
    ({"catalogo_id": "az-foundry"}, [("conservar_precios", "conservar_forma")]),   # REVERIF16-2
    ("x", [("conservar_precios", "conservar_forma")]),
    ([{"catalogo_id": "az-foundry", "plantilla_id": "gpt-6-luna-entrada"}], [("conservar_precios[0]", "conservar_forma")]),
    ([{"catalogo_id": "az-foundry", "cantidad_mensual": 8}], [("conservar_precios[0]", "conservar_forma")]),
    ([dict(CONSERVAR[0], cantidad_mensual="8")], [("conservar_precios", "conservar_forma")]),
    ([dict(CONSERVAR[0], cantidad_mensual=float("nan"))], [("conservar_precios", "conservar_forma")]),
    ([dict(CONSERVAR[0], cantidad_mensual=True)], [("conservar_precios", "conservar_forma")]),
    ([dict(CONSERVAR[0], cantidad_mensual=4), dict(CONSERVAR[0], cantidad_mensual=4)], []),   # se suman
])
def test_casos_adversos_del_dato_de_control(conservar, esperado):
    assert _ambos(V4, conservar) == esperado


def test_forma_de_i16_se_agrupa_por_filtro():
    # integrador I1.7 (P17-4): lo guardado es la completada; sin plantilla_id es la forma de I1.6 (se agrupa por filtro)
    r = ejemplo("respuesta_experto_completa")
    for p in r["precios"]:
        p.pop("plantilla_id")
    comps = {c["id"]: c for c in r["componentes"]}
    viejo = [{"precio_id": p["id"], "componente_id": p["componente_id"], "catalogo_id": comps[p["componente_id"]]["catalogo_id"],
              "filtro": p["filtro"], "cantidad_mensual": p["cantidad_mensual"], "base_volumen": p.get("base_volumen")}
             for p in r["precios"]]
    assert _ambos(r, viejo) == []
    r2 = copy.deepcopy(r)
    r2["precios"].append(dict(r2["precios"][0], id="P-99", cantidad_mensual=7300))
    assert [x[1] for x in _ambos(r2, viejo)] == ["conservado_cambiado"]


def test_el_brief_de_la_ronda_2_lleva_el_dato_por_efecto_y_registrar_lo_aplica(m):  # noqa: F811
    m.hasta_verificacion()
    c = _cons(m)
    disc = {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": OTRA}}
    assert _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"], disc))[0] == 1
    assert m.run("enrutar")[0] == 0
    b = m.estado()["carga"]["briefs"][-1]
    resp = m.estado()["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    libres = {p["id"] for p in resp["precios"] if p["componente_id"] == "C-02"}
    assert {i for x in b["conservar_precios"] for i in x["precio_ids"]} == {p["id"] for p in resp["precios"]} - libres
    assert all(set(x) == {"catalogo_id", "plantilla_id", "filtro", "cantidad_mensual", "precio_ids", "componente_ids"}
               for x in b["conservar_precios"])
    assert "## Precios conservados" in b["texto"] and "precios_azure" not in b["texto"]
    seccion = vp.lineas_seccion(b["texto"].partition("\n---\n")[2], vp.SECCIONES_PRECIOS_BRIEF)
    texto, dato = vp.efecto_desde_texto(seccion), vp.efecto_desde_conservar(b["conservar_precios"])
    assert set(texto) == set(dato) and all(vp._iguales_replica(texto[k], dato[k]) for k in texto)
    r = copy.deepcopy(ejemplo("respuesta_experto"))
    r["brief_recibido"], r["brief_id"] = b["texto"], b["brief_id"]
    r["precios"].append(dict(next(p for p in r["precios"] if p["componente_id"] == "C-04"), id="P-09"))
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada("e2.json", r))
    assert rc != 0 and "cantidad mensual total" in out, out
