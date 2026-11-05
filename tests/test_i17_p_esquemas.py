"""I1.7 · papel P: esquemas v4 (lo que escribe el modelo y lo que guarda el núcleo), su text.format derivado, el esquema
de la instantánea y los ejemplos. Sin red."""
from __future__ import annotations

import json

from tests import i17_p_datos as D
from nucleo import esquema, experto  # noqa: E402

ESQ = D.RAIZ / "esquemas"


def _cargar(nombre: str) -> dict:
    return json.loads((ESQ / f"{nombre}.json").read_text(encoding="utf-8"))


def test_la_completa_contiene_cada_campo_del_modelo_con_el_mismo_esquema():
    m, c = _cargar("respuesta_experto"), _cargar("respuesta_experto_completa")
    assert set(m["required"]) <= set(c["required"]) and set(c["required"]) - set(m["required"]) == {"valoracion_nucleo"}
    for k, v in m["properties"].items():
        if k != "referencias":
            assert c["properties"][k] == v, k
    for d, sub in m["$defs"].items():
        cd = c["$defs"][d]
        assert set(sub.get("required", [])) <= set(cd.get("required", [])), d
        for k, v in (sub.get("properties") or {}).items():
            if (d, k) not in {("componente", "referencia_id"), ("precio", "base_volumen")}:
                assert cd["properties"][k] == v, (d, k)


def test_el_modelo_ya_no_escribe_precio_filtro_ni_cantidad():
    m = _cargar("respuesta_experto")
    precio = set(m["$defs"]["precio"]["properties"])
    assert precio == {"id", "componente_id", "plantilla_id", "instancias", "base_volumen", "factor_override"}
    assert "precios_azure" not in m["properties"]["herramientas_usadas"]["properties"]
    assert "factor" not in m["$defs"]["base_volumen"]["properties"]


def test_text_format_derivado_esta_al_dia_y_es_estricto():
    from agentes.esquemas import derivar_text_format as d
    actual = json.loads(d.ruta_salida("respuesta_experto").read_text(encoding="utf-8"))
    assert actual == d.text_format("respuesta_experto")

    def estricto(n):
        if isinstance(n, dict):
            if "properties" in n:
                assert set(n["required"]) == set(n["properties"]) and n["additionalProperties"] is False
            for v in n.values():
                estricto(v)
        elif isinstance(n, list):
            for v in n:
                estricto(v)
    estricto(actual["schema"])


def test_historico_v3_es_el_contrato_anterior():
    v3 = json.loads((ESQ / "historico" / "respuesta_experto_v3.json").read_text(encoding="utf-8"))
    assert v3["$id"].endswith(":3") and "filtro" in v3["$defs"]["precio"]["properties"]


def test_los_ejemplos_casan_entre_si():
    ej = ESQ / "ejemplos"
    modelo = json.loads((ej / "respuesta_experto.json").read_text(encoding="utf-8"))
    completa = json.loads((ej / "respuesta_experto_completa.json").read_text(encoding="utf-8"))
    inst = json.loads((ej / "precios_instantanea.json").read_text(encoding="utf-8"))
    estado = json.loads((ej / "estado.json").read_text(encoding="utf-8"))
    assert experto.errores_instantanea(inst) == []
    assert experto.proyectar_modelo(completa) == modelo
    assert estado["carga"]["respuestas_expertos"]["azure"]["respuesta"] == completa
    assert esquema.validar(modelo, esquema.cargar("respuesta_experto")) == []
    assert esquema.validar(completa, esquema.cargar("respuesta_experto_completa")) == []
    assert completa["valoracion_nucleo"]["instantanea"]["sha256"] == inst["sha256"]


def _bloques_integrados(monkeypatch):
    """CAMBIOS-I17-P §5.1: el integrador cambia en estado._BLOQUES «respuesta_experto» por «respuesta_experto_completa»."""
    from nucleo import estado
    nuevos = tuple(("respuesta_experto_completa", f) if n == "respuesta_experto" else (n, f) for n, f in estado._BLOQUES)
    monkeypatch.setattr(estado, "_BLOQUES", nuevos)
    return estado


def test_con_el_cambio_de_estado_py_el_estado_con_la_completada_valida(monkeypatch):
    import json as _json
    from tests.test_i17_p_completar import CAT, INST, PERF, resp
    estado = _bloques_integrados(monkeypatch)
    est = D.estado_brezalia()
    experto.registrar(est, "azure", _json.dumps(resp(), ensure_ascii=False), CAT, PERF, "2026-10-13", instantanea=INST)
    est["carga"]["briefs"][0].pop("aceptados", None)  # campo de R en curso (esquemas/brief.json aún no lo admite)
    assert [e for e in estado.errores_estado(est) if not e.startswith("[brief ")] == []
    ejemplo = _json.loads((ESQ / "ejemplos" / "estado.json").read_text(encoding="utf-8"))
    assert estado.errores_estado(ejemplo) == []


def test_con_el_cambio_de_estado_py_aplicado_la_completada_del_ejemplo_valida():
    """Integrador I1.7: aplicado CAMBIOS-I17-P §5.1, el bloque guardado se valida con respuesta_experto_completa (antes
    esta prueba fijaba que, sin el cambio, el ejemplo no validaba)."""
    from nucleo import estado
    ejemplo = json.loads((ESQ / "ejemplos" / "estado.json").read_text(encoding="utf-8"))
    assert not any("respuesta_experto" in e for e in estado.errores_estado(ejemplo))
    assert ("respuesta_experto_completa" in [n for n, _ in estado._BLOQUES]
            and "respuesta_experto" not in [n for n, _ in estado._BLOQUES])
