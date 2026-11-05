"""Arreglos I1.6, PR16-3: los precios ya verificados se conservan entre rondas (filtro, cantidad mensual y base).

En real, el factor de Microsoft Foundry cambió en cada ronda (4.000, 1.200 y 2.500 tokens por consulta en la sesión 1 de
B) porque el brief no lo llevaba y nadie lo comprobaba. Ahora el brief lleva el dato (`conservar_precios` y la línea con
cantidad, base y factor) y registrar-experto rechaza el cambio salvo que una corrección toque ese componente. Datos
reales de I1.6 (LES-G-078) y el flujo del núcleo con el catálogo real. Sin red."""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from tests.test_i13_convergencia import OTRA, ejemplo, m  # noqa: F401  (fixture del mundo con el catálogo real)
from tests.test_i1_verificacion_lotes import _cons, _registrar, _resp

from nucleo import experto, verificacion  # noqa: E402
import verificar_paquete as vp  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[1]
REAL = RAIZ / "pruebas" / "I16" / "REAL" / "B" / "sesion_1"
DISCREPA_C02 = {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": OTRA}}


def _leer(f: pathlib.Path) -> dict:
    d = json.loads(f.read_text(encoding="utf-8"))
    return d.get("respuesta", d)


def _conservar_de(r: dict) -> list[dict]:
    comps = {c["id"]: c for c in r["componentes"]}
    # integrador I1.7: con la respuesta completada (v4) cada precio lleva plantilla_id y se conserva por plantilla
    return [{"precio_id": p["id"], "componente_id": p["componente_id"],
             "catalogo_id": comps[p["componente_id"]]["catalogo_id"], "filtro": p["filtro"],
             **({"plantilla_id": p["plantilla_id"]} if p.get("plantilla_id") else {}),
             "cantidad_mensual": p["cantidad_mensual"], "base_volumen": p["base_volumen"]} for p in r["precios"]]


def _clave(r: dict, pid: str) -> str:
    """I1.7 (R, LES-G-100.6): la conservación se compara por efecto y el id de cada error es «catalogo_id · filtro» (o
    plantilla), no el del precio."""
    comps = {c["id"]: c for c in r["componentes"]}
    p = next(x for x in r["precios"] if x["id"] == pid)
    return f"{comps[p['componente_id']]['catalogo_id']} · {p.get('plantilla_id') or ' '.join(p['filtro'].split())}"


def _ambos(r, conservar):
    nucleo = [(x["id"], x["regla"]) for x in experto.errores_conservacion(r, conservar)]
    assert nucleo == vp.conservacion_replica(r, conservar)
    return nucleo


@pytest.mark.skipif(not (REAL / "respuesta_experto_AZ_R2.json").exists(), reason="faltan las respuestas reales de I1.6")
def test_pr16_3_con_las_respuestas_reales_de_b():
    r1, r2 = _leer(REAL / "respuesta_experto_AZ_R1.json"), _leer(REAL / "respuesta_experto_AZ_R2.json")
    conservar = _conservar_de(r1)
    assert _ambos(r1, conservar) == []
    # R2 real: Foundry de 4.000 a 1.500 tokens de entrada y de 500 a 400 de salida; Bot Service de 2 a 1 mensaje
    assert _ambos(r2, conservar) == [(_clave(r1, "P-01"), "conservado_cambiado"),
                                     (_clave(r1, "P-02"), "conservado_cambiado"),
                                     (_clave(r1, "P-03"), "conservado_cambiado")]


def test_pr16_3_renumerar_vale_y_quitar_o_cambiar_no():
    r = copy.deepcopy(ejemplo("respuesta_experto_completa"))  # integrador I1.7: lo que guarda el núcleo
    conservar = _conservar_de(r)
    renumerada = copy.deepcopy(r)
    for n, p in enumerate(reversed(renumerada["precios"]), 1):
        p["id"] = f"P-{n:02d}"
    assert _ambos(renumerada, conservar) == []
    sin = copy.deepcopy(r)
    sin["precios"] = [p for p in sin["precios"] if p["id"] != "P-02"]
    assert _ambos(sin, conservar) == [(_clave(r, "P-02"), "conservado_ausente")]
    otra = copy.deepcopy(r)
    next(p for p in otra["precios"] if p["id"] == "P-02")["cantidad_mensual"] = 744
    assert _ambos(otra, conservar) == [(_clave(r, "P-02"), "conservado_cambiado")]
    ref = copy.deepcopy(r)  # un precio de referencia (null) que pasa a sumar también cambia
    next(p for p in ref["precios"] if p["id"] == "P-04")["cantidad_mensual"] = 1
    # I1.8 (REV17-5): lo valorado se separa de lo que es solo precio de referencia: el de referencia desaparece
    assert _ambos(ref, conservar) == [(_clave(r, "P-04") + " (precio de referencia)", "conservado_ausente")]
    assert _ambos(r, None) == [] == _ambos(r, [])


def test_pr16_3_la_base_compara_numeros_y_no_redaccion():
    r = copy.deepcopy(ejemplo("respuesta_experto_completa"))  # integrador I1.7: lo que guarda el núcleo
    p = next(x for x in r["precios"] if x["id"] == "P-04")
    p.update(cantidad_mensual=6, base_volumen={"cita": "Unas 2.000 consultas al mes.", "cantidad_base": 2000,
                                               "unidad_base": "consultas", "factor": {
                                                   "valor": 3000, "unidad": "tokens de entrada por consulta",
                                                   "justificacion": "Pregunta, contexto e instrucciones."}})
    conservar = _conservar_de(r)
    otra = copy.deepcopy(r)
    q = next(x for x in otra["precios"] if x["id"] == "P-04")
    q["base_volumen"]["factor"]["justificacion"] = "Otra redacción del mismo supuesto."
    q["base_volumen"]["cantidad_base"] = 2000.0
    assert _ambos(otra, conservar) == []
    q["base_volumen"]["factor"]["valor"] = 2500
    q["cantidad_mensual"] = 5
    assert _ambos(otra, conservar) == [(_clave(r, "P-04"), "conservado_cambiado")]


def _ronda_2(m):  # noqa: F811
    m.hasta_verificacion()
    c = _cons(m)
    rc, _ = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"], DISCREPA_C02))
    assert rc == 1
    assert m.run("enrutar")[0] == 0
    return m.estado()["carga"]["briefs"][-1]


def test_pr16_3_el_brief_de_la_ronda_2_lleva_cantidad_base_y_el_dato_estructurado(m):  # noqa: F811
    b = _ronda_2(m)
    resp = m.estado()["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    # DISCREPA en C-02: su precio (P-01) queda libre; los demás se conservan
    # I1.7 (R): por efecto, una entrada por servicio y filtro con sus precio_ids
    assert sorted(i for x in b["conservar_precios"] for i in x["precio_ids"]) == sorted(
        p["id"] for p in resp["precios"] if p["componente_id"] != "C-02")
    for ln in (x for x in b["conservar"] if x.startswith("P-")):
        assert " | cantidad_mensual: " in ln
    assert "comprueba que la cantidad mensual total de cada plantilla no cambia" in b["texto"]


def _registrar_r2(m, b, cambiar=None):  # noqa: F811
    resp = ejemplo("respuesta_experto")
    resp["brief_recibido"], resp["brief_id"] = b["texto"], b["brief_id"]
    if cambiar:
        cambiar(resp)
    return m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada("e2.json", resp))


def test_pr16_3_registrar_rechaza_un_precio_conservado_cambiado(m):  # noqa: F811
    b = _ronda_2(m)
    # integrador I1.7: el modelo cambia la cantidad con `instancias` (el núcleo calcula 730 h × instancias)
    rc, out = _registrar_r2(m, b, lambda r: next(p for p in r["precios"] if p["id"] == "P-02").update(instancias=2))
    assert rc != 0 and "cantidad mensual total era 730" in out, out
    assert m.estado()["intentos"]["T2"] == 1


def test_pr16_3_el_precio_del_componente_corregido_puede_cambiar(m):  # noqa: F811
    b = _ronda_2(m)
    rc, out = _registrar_r2(m, b, lambda r: next(p for p in r["precios"] if p["id"] == "P-01").update(instancias=2))
    assert rc == 0, out
