"""Pruebas sin red de los esquemas de I1, de sus ejemplos y del comprobador del subconjunto."""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib

import pytest

DIR = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("comprobar_esquemas", DIR / "comprobar_esquemas.py")
ce = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ce)

NOMBRES = sorted(p.stem for p in DIR.glob("*.json"))


def _cargar(ruta: pathlib.Path) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def _par(nombre: str) -> tuple[dict, dict]:
    return _cargar(DIR / f"{nombre}.json"), _cargar(DIR / "ejemplos" / f"{nombre}.json")


def test_estan_los_once_esquemas():
    # I1.7 (papel P): más precios_instantanea y respuesta_experto_completa (lo que guarda el núcleo)
    assert NOMBRES == ["anexo_consumo", "brief", "catalogo_componentes", "decision", "estado", "estimacion_entrada",
                       "manifiesto_paquete", "precios_instantanea", "requisitos", "respuesta_experto",
                       "respuesta_experto_completa", "respuesta_verificador", "textos_cliente"]


@pytest.mark.parametrize("nombre", NOMBRES)
def test_esquema_en_subconjunto_y_ejemplo_valido(nombre):
    esquema, ejemplo = _par(nombre)
    assert esquema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert ce.palabras_no_admitidas(esquema) == []
    assert ce.validar(ejemplo, esquema, esquema) == []


@pytest.mark.parametrize("nombre", ce.ESTRICTOS)
def test_respuestas_de_agente_compatibles_con_strict(nombre):
    esquema, _ = _par(nombre)
    assert ce.no_estricto(esquema) == []


def test_bloques_del_estado_validan_con_su_esquema():
    est = _cargar(DIR / "ejemplos" / "estado.json")
    carga = est["carga"]
    pares = [("requisitos", carga["requisitos"]), ("brief", carga["briefs"][0]),
             ("respuesta_experto_completa", carga["respuestas_expertos"]["azure"]["respuesta"]),  # I1.7
             ("respuesta_verificador", carga["verificacion"]["respuesta"]), ("anexo_consumo", carga["anexo_consumo"]),
             ("estimacion_entrada", carga["estimacion"]["entrada"]), ("textos_cliente", carga["textos_cliente"])]
    for nombre, bloque in pares:
        esquema = _cargar(DIR / f"{nombre}.json")
        assert ce.validar(bloque, esquema, esquema) == [], nombre


def test_hash_contenido_del_ejemplo_es_el_de_la_carga():
    est = _cargar(DIR / "ejemplos" / "estado.json")
    assert ce_hash(est["carga"]) == est["hash_contenido"]


def ce_hash(carga: dict) -> str:
    import hashlib
    datos = json.dumps(carga, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(datos).hexdigest()


def test_eco_del_brief_en_el_ejemplo():
    resp = _cargar(DIR / "ejemplos" / "respuesta_experto.json")
    br = _cargar(DIR / "ejemplos" / "brief.json")
    assert resp["brief_recibido"] == br["texto"] and resp["brief_id"] == br["brief_id"]


@pytest.mark.parametrize("mutacion, esperado", [
    (lambda d: d.update(extra=1), "clave no admitida"),
    (lambda d: d.pop("brief_id"), "falta «brief_id»"),
    (lambda d: d.update(brief_id="BRF-mal"), "no casa"),
    (lambda d: d["herramientas_usadas"].update(microsoft_docs_search=True), "tipo bool"),
    (lambda d: d["herramientas_usadas"].update(microsoft_docs_search=4), "fuera de rango"),
    (lambda d: d["precios"][0].update(instancias=0), "debe ser > 0"),  # I1.7: el modelo ya no escribe moneda
    (lambda d: d["precios"][0].update(filtro="serviceName eq 'X'"), "clave no admitida «filtro»"),
    (lambda d: d["precios"][0].update(plantilla_id="Basic Unit"), "no casa"),
    (lambda d: d["componentes"][0].update(desviacion_justificada="corta"), "longitud"),
    (lambda d: d["tareas_propuestas"][0].update(horas_base=float("nan")), "tipo float"),
    (lambda d: d["componentes"].clear(), "elementos fuera de rango"),  # I1.7: referencias ya no tiene mínimo
])
def test_respuesta_experto_rechaza(mutacion, esperado):
    esquema, ejemplo = _par("respuesta_experto")
    malo = copy.deepcopy(ejemplo)
    mutacion(malo)
    errores = ce.validar(malo, esquema, esquema)
    assert any(esperado in e for e in errores), errores


def test_estimacion_rechaza_contingencia_y_condiciones():
    esquema, ejemplo = _par("estimacion_entrada")
    for clave in ("contingencia_porcentaje", "condiciones_pago", "validez_dias"):
        malo = dict(ejemplo, **{clave: 1})
        assert any("clave no admitida" in e for e in ce.validar(malo, esquema, esquema)), clave


def test_const_booleano_no_acepta_uno():
    esquema, ejemplo = _par("estado")
    malo = copy.deepcopy(ejemplo)
    malo["carga"]["alta"]["nda_confirmado"] = 1
    assert ce.validar(malo, esquema, esquema)


def test_dolar_final_no_admite_salto_de_linea():
    esquema = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    assert ce.validar("a" * 64, esquema, esquema) == []
    assert ce.validar("a" * 64 + "\n", esquema, esquema)


def test_unique_items_usa_igualdad_json():
    esquema = {"type": "array", "uniqueItems": True}
    assert ce.validar([1, 1.0], esquema, esquema)
    assert ce.validar([True, 1], esquema, esquema) == []
    assert ce.validar([{"a": 1}, {"a": 1.0}], esquema, esquema)


def test_formas_fuera_del_subconjunto_se_rechazan():
    assert ce.palabras_no_admitidas({"type": "object", "additionalProperties": {"type": "integer"}})
    assert ce.palabras_no_admitidas({"type": "array", "items": True})
    assert ce.palabras_no_admitidas({"$ref": "#/$defs/a~1b"})


def test_ref_inexistente_da_error_y_no_excepcion():
    esquema = {"$ref": "#/$defs/no_existe", "$defs": {}}
    assert any("inexistente" in x for x in ce.validar(1, esquema, esquema))


def test_palabra_clave_no_admitida_se_detecta():
    assert ce.palabras_no_admitidas({"type": "object", "properties": {"a": {"oneOf": []}}})
    assert ce.no_estricto({"type": "object", "properties": {"a": {"type": "string"}}, "required": []})
