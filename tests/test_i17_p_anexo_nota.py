"""I1.7 · papel P: anexo de consumo con los precios de la instantánea («precios consultados el <fecha>», edad máxima,
total con «No valorado») e INT16-2; y la nota del revisor con lo nuevo. Sin red.
"""
from __future__ import annotations

import copy
import json

import pytest

from tests import i17_p_datos as D
from tests.test_i17_p_completar import CAT, INST, PERF, resp
from nucleo import anexo_consumo, experto, nota_revision  # noqa: E402
from nucleo.errores import IntegridadRota, ReglaIncumplida  # noqa: E402

CNS = "CNS-OF-BREZALIA-001-A-R1"


def _estado(veredictos: dict | None = None) -> dict:
    est = D.estado_brezalia()
    experto.registrar(est, "azure", json.dumps(resp(), ensure_ascii=False), CAT, PERF, "2026-10-13", instantanea=INST)
    r = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    elementos = [{"id": x["id"], "tipo": "referencia", "veredicto": "OK"} for x in r["referencias"]]
    elementos += [{"id": x["id"], "tipo": "componente", "veredicto": "OK"} for x in r["componentes"]]
    elementos += [dict({"id": pid, "tipo": "precio"}, **v) for pid, v in (veredictos or {}).items()]
    est["carga"]["consolidado"] = {"consolidado_id": CNS}
    est["carga"]["verificacion"] = {"consolidado_id": CNS, "respuesta": {"elementos": elementos},
                                    "resultado": {"verificada": True, "discrepa": [], "no_verificables": [], "reparados": []}}
    return est


def test_anexo_con_precios_de_la_instantanea_y_su_fecha():
    est = _estado()
    anexo, detalle = anexo_consumo._construir(est, CAT)
    assert anexo["fuente"]["consultado_el"] == "2026-10-13"
    assert [x["precio_id"] for x in anexo["lineas"]] == ["P-01", "P-02", "P-03", "P-04", "P-05"]
    assert all(x["verificacion"] == "OK" and detalle[x["precio_id"]]["estado"] == anexo_consumo.ESTADO_INSTANTANEA
               for x in anexo["lineas"])
    assert any(a.startswith("Precios consultados el 2026-10-13") for a in anexo["avisos"])
    assert "El total solo suma los conceptos valorados: 2 componentes quedan como «No valorado»." in anexo["avisos"]
    p1 = anexo["lineas"][0]
    assert (p1["precio_unitario"], p1["cantidad_mensual"], p1["coste_mensual_eur"]) == (0.1056, 5, "0.53")


def test_int16_2_un_discrepa_de_cantidad_no_toca_el_precio():
    est = _estado({"P-01": {"veredicto": "DISCREPA", "campo": "cantidad", "valor_correcto": "3", "detalle": "x"}})
    anexo, _ = anexo_consumo._construir(est, CAT)
    assert anexo["lineas"][0]["precio_unitario"] == 0.1056 and anexo["lineas"][0]["verificacion"] == "OK"
    assert any("observación del verificador sobre «cantidad»" in a for a in anexo["avisos"])
    est = _estado({"P-01": {"veredicto": "DISCREPA", "campo": "precio", "valor_correcto": "0.1057"}})
    _, detalle = anexo_consumo._construir(est, CAT)
    assert detalle["P-01"]["estado"] == anexo_consumo.ESTADO_TOLERANCIA
    est = _estado({"P-01": {"veredicto": "DISCREPA", "campo": "precio", "valor_correcto": "3"}})
    with pytest.raises(ReglaIncumplida):
        anexo_consumo._construir(est, CAT)


def test_aplicar_rechaza_una_instantanea_de_mas_de_31_dias(tmp_path):
    est = _estado()
    with pytest.raises(IntegridadRota):
        anexo_consumo.aplicar(est, CAT, tmp_path, hoy="2026-11-14")
    assert est["carga"]["anexo_consumo"] is None and not list(tmp_path.iterdir())
    anexo = anexo_consumo.aplicar(est, CAT, tmp_path, hoy="2026-11-13")
    import openpyxl
    ws = openpyxl.load_workbook(tmp_path / f"{anexo['codigo']}-Anexo-Consumo.xlsx").active
    assert "precios consultados el 2026-10-13" in ws.cell(3, 1).value
    assert any(str(c.value).startswith("Total mensual (EUR, conceptos valorados)") for c in ws["A"] if c.value)


def test_ruta_de_la_instantanea_junto_al_catalogo(tmp_path, monkeypatch):
    monkeypatch.delenv("PREVENTA_PRECIOS", raising=False)
    cat = tmp_path / "file-abc-catalogo_componentes.json"
    cat.write_text("{}", encoding="utf-8")
    with pytest.raises(IntegridadRota):
        anexo_consumo.ruta_instantanea(cat)
    (tmp_path / "file-xyz-precios_instantanea.json").write_text(json.dumps(INST), encoding="utf-8")
    assert anexo_consumo.ruta_instantanea(cat).name == "file-xyz-precios_instantanea.json"
    assert anexo_consumo.cargar_instantanea(anexo_consumo.ruta_instantanea(cat)) == INST
    (tmp_path / "file-otro-precios_instantanea.json").write_text("{}", encoding="utf-8")
    with pytest.raises(IntegridadRota):
        anexo_consumo.ruta_instantanea(cat)
    monkeypatch.setenv("PREVENTA_PRECIOS", str(tmp_path / "file-xyz-precios_instantanea.json"))
    assert anexo_consumo.ruta_instantanea(cat).name == "file-xyz-precios_instantanea.json"
    roto = dict(copy.deepcopy(INST), moneda="USD")
    (tmp_path / "roto.json").write_text(json.dumps(roto), encoding="utf-8")
    with pytest.raises(IntegridadRota):
        anexo_consumo.cargar_instantanea(tmp_path / "roto.json")


def test_la_copia_del_sandbox_es_la_del_catalogo_si_ya_existe():
    raiz = D.RAIZ
    a, b = raiz / "catalogo" / "precios_instantanea.json", raiz / "sandbox" / "datos" / "precios_instantanea.json"
    if not a.exists():
        pytest.skip("la instantánea real aún no está (la descarga el papel E al desplegar)")
    assert a.read_bytes() == b.read_bytes()
    inst = anexo_consumo.cargar_instantanea(b)
    cat = anexo_consumo.cargar_catalogo(raiz / "sandbox" / "datos" / "catalogo_componentes.json")
    assert experto.errores_instantanea_catalogo(inst, cat) == []


def test_nota_del_revisor_lista_lo_nuevo():
    est = _estado()
    c = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    lineas = experto.lineas_para_revisor(c, CAT, fecha="2026-10-13", semanas=experto.duracion_gantt(c))
    texto = "\n".join(lineas)
    for esperado in ("Precios de la instantánea de Azure Retail Prices consultada el 2026-10-13",
                     "Factor estándar del catálogo («asistente con RAG»)", "Ciclo de vida del modelo «gpt-6-luna-entrada»",
                     "fecha de retirada aún no publicada", "Referencias que el código puso desde el catálogo",
                     "Arquitectura de referencia elegida"):
        assert esperado in texto, esperado


def test_nota_del_ejemplo_se_construye_con_la_completada():
    ej = D.RAIZ / "esquemas" / "ejemplos"
    est = json.loads((ej / "estado.json").read_text(encoding="utf-8"))
    cat = json.loads((ej / "catalogo_componentes.json").read_text(encoding="utf-8"))
    doc = nota_revision.construir(est, cat, transcripcion=None)
    texto = "\n".join(nota_revision.textos_docx(doc))
    assert "Precios de la instantánea de Azure Retail Prices consultada el 2026-10-08" in texto
    assert "Precios del consumo" in texto and "consultados el 2026-10-08" in texto
