"""I1.8 · papel R · núcleo: PR17-6 parte 2 (texto del reintento), REVERIF17-5 (cantidades con unidad) y REV17-6 (edad de
la instantánea al empaquetar). Con el núcleo real en proceso (Mundo) y casos adversos."""
from __future__ import annotations

import copy
import json
import math
import pathlib

import pytest

from tests.test_i1_estado_comun import Mundo, ejemplo

RAIZ = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def _rechazar(m, n: int = 1) -> list[str]:
    """Registra `n` respuestas del experto que el núcleo rechaza (sin tareas propuestas). Devuelve los errores."""
    for i in range(n):
        r = ejemplo("respuesta_experto")
        r["tareas_propuestas"] = []
        assert m.run("registrar-experto", "--experto", "azure", "--respuesta",
                     m.entrada(f"respuesta_rota_{i}.json", r))[0] == 1
    return [f["error"] for f in m.estado()["fallos"][-n:]]


def test_sin_rechazo_el_texto_de_envio_es_el_brief(m):
    from nucleo import brief
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    est = m.estado()
    assert brief.rechazos_vigentes(est) == [] and brief.texto_envio(est, est["carga"]["briefs"][-1]) == \
        est["carga"]["briefs"][-1]["texto"]


def test_tras_un_rechazo_el_texto_lleva_el_motivo_literal_y_el_brief_entero(m):
    from nucleo import brief
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    errores = _rechazar(m, 2)
    est = m.estado()
    b = est["carga"]["briefs"][-1]
    t = brief.texto_envio(est, b)
    bloque, _, resto = t.partition(brief.FIN_REINTENTO + "\n")
    assert t.startswith(brief.MARCA_REINTENTO + "\n") and resto == b["texto"]
    assert f"brief_id: {b['brief_id']}" in bloque and "rechazos_previos: 2" in bloque
    assert errores[-1] in bloque and errores[0] not in bloque.replace(errores[-1], "")   # el último, literal
    assert "BRIEF-PREVENTA/1" not in bloque                                             # el bloque no nombra el brief
    assert m.estado()["carga"]["briefs"][-1]["texto"] == b["texto"]                      # el brief no cambia


def test_un_fallo_a2a_no_es_un_rechazo_y_no_borra_el_anterior(m):
    from nucleo import brief
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    assert m.run("registrar-fallo", "--fase", "T2", "--error", "HTTP 503 del A2A", "--hipotesis", "red")[0] == 0
    est = m.estado()
    assert brief.rechazos_vigentes(est) == []                     # registrar-fallo no es un rechazo del núcleo
    error = _rechazar(m)[0]
    assert m.run("registrar-fallo", "--fase", "T2", "--error", "HTTP 503 del A2A", "--hipotesis", "red")[0] == 1  # 3/3
    est = m.estado()
    assert est["estado"] == "BLOQUEADA"
    assert [f["error"] for f in brief.rechazos_vigentes(est)] == [error]


def test_la_puerta_lo_recompone_hasta_el_control_del_registro(m):
    from nucleo import brief
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    _rechazar(m)
    est_antes = m.estado()
    texto = brief.texto_envio(est_antes, est_antes["carga"]["briefs"][-1])
    r = m.entrada("respuesta_buena.json", ejemplo("respuesta_experto"))
    assert m.run("registrar-experto", "--experto", "azure", "--respuesta", r)[0] == 0
    est = m.estado()
    n = brief.control_registro_experto(est)
    assert n == est["control_versiones"][-1]["n"]
    assert brief.texto_envio(est, est["carga"]["briefs"][-1], hasta_n=n) == texto
    assert brief.texto_envio(est, est["carga"]["briefs"][-1], hasta_n=1) == est["carga"]["briefs"][-1]["texto"]


def test_el_motivo_se_anonimiza_y_se_recorta():
    from nucleo import brief
    est = {"carga": {"alta": {"terminos_sensibles": ["Kelvara"], "cliente": "Kelvara Ensayos", "codigo_cliente": "KELVARA"}},
           "control_versiones": [{"n": 1, "subcomando": "enrutar", "ts": "2026-10-13T10:00:00+02:00"},
                                 {"n": 2, "subcomando": "registrar-experto", "ts": "2026-10-13T10:00:05+02:00"}],
           "fallos": [{"fase": "T2", "ts": "2026-10-13T10:00:05+02:00", "error": "cita de Kelvara: x" + "y" * 7000}]}
    t = brief.texto_envio(est, {"brief_id": "BRF-X-R1", "texto": "BRIEF-PREVENTA/1\nb"})
    assert "Kelvara" not in t and "[CLIENTE]" in t and "[recortado: " in t


def test_rechazos_de_las_sesiones_reales():
    """Recuento en estados reales: sesión 2 de I1.7 (dos rechazos del núcleo y un fallo A2A antes, en la versión B)."""
    from nucleo import brief
    est = json.loads((RAIZ / "pruebas/I17/REAL/B/sesion_2/final/estado.json").read_text(encoding="utf-8"))
    rech = brief.rechazos_vigentes(est)
    assert [f["intento"] for f in rech] == [1, 2] and all("Respuesta del experto inválida" in f["error"] for f in rech)
    sin = json.loads((RAIZ / "pruebas/I17/ARREGLOS/REAL/B/sesion_1/lista_A/estado.json").read_text(encoding="utf-8"))
    assert brief.rechazos_vigentes(sin, hasta_n=brief.control_registro_experto(sin)) == []


@pytest.mark.parametrize("valor,esperado", [(11.312, "11,312"), (2555, "2.555"), (1460.0, "1.460"), (730, "730"),
                                            (0.002, "0,002"), (1234567.5, "1.234.567,5"), (-3.25, "-3,25"),
                                            (True, "True"), (math.nan, "nan"), (math.inf, "inf"), ("7", "7")])
def test_numero_es(valor, esperado):
    from nucleo import brief
    assert brief.numero_es(valor) == esperado


@pytest.mark.parametrize("unidad,medidor,esperado", [
    ("1M", "6-luna ShortCo Inp Std DZ 1M Tokens", "millones de tokens"), ("1K", "Semantic Ranker queries", "miles de consultas"),
    ("1K", "Free Standard Channel Messages", "miles de mensajes"), ("1 Hour", "B1", "horas"),
    ("1 GB/Month", "Hot LRS Data Stored", "GB"), ("1 GiB Hour", "Premium Memory Duration", "GiB·h"),
    ("10K", "Operations", "decenas de miles de operaciones"), ("5M", "x", "lotes de 5.000.000 unidades"),
    ("raro", "x", None), (None, None, None), ("", "", None)])
def test_unidad_es(unidad, medidor, esperado):
    from nucleo import brief
    assert brief.unidad_es(unidad, medidor) == esperado


def test_propuesta_con_unidad_formato_y_sin_unidad_conocida():
    from nucleo import brief
    est = {"version": "B", "decisiones": [{"id": "D-002", "tipo": "DEVUELTA", "version": "A", "revisor": "Responsable de preventa",
                                           "comentarios": "x", "version_devuelta": {"componentes": [], "precios": [
                                               {"clave": "az-foundry · gpt-6-luna-entrada", "cantidad_mensual": 11.312},
                                               {"clave": "az-x · inexistente", "cantidad_mensual": 2000},
                                               {"clave": "az-ai-search · ranking-semantico", "cantidad_mensual": None}]}}]}
    inst = json.loads((RAIZ / "sandbox/datos/precios_instantanea.json").read_text(encoding="utf-8"))
    assert brief.lineas_propuesta_devuelta(est, instantanea=inst) == [
        "- Consumo az-foundry · gpt-6-luna-entrada: 11,312 millones de tokens al mes",
        "- Consumo az-x · inexistente: 2.000 al mes (unidad no disponible en la instantánea)",
        "- Consumo az-ai-search · ranking-semantico: sin cantidad mensual (precio de referencia)"]


def test_paquete_no_se_construye_con_la_instantanea_caducada(tmp_path, monkeypatch):
    from nucleo import errores, paquete
    est = {"estado": "LISTA_PARA_REVISION", "codigo": "OF-X-001-A", "carga": {"respuestas_expertos": {"azure": {
        "respuesta": {"valoracion_nucleo": {"instantanea": {"fecha": "2026-09-01T00:00:00Z"}}}}}}}
    monkeypatch.setattr(paquete, "_revalidar", lambda *a: None)
    monkeypatch.setattr(paquete.hashes, "hash_contenido", lambda e: "h")
    with pytest.raises(errores.IntegridadRota, match="caducada"):
        paquete.construir(copy.deepcopy(est), tmp_path, {}, {}, None, hoy="2026-10-13")
    assert not (tmp_path / "salida").exists()                       # antes de crear nada (revisión de R)
    paquete._edad_instantanea(est, "2026-10-02")                     # dentro de los 31 días: sin error
    with pytest.raises(errores.IntegridadRota):
        paquete._edad_instantanea(est, "2026-10-03")


def test_lo_que_el_cliente_ya_tiene_va_tras_fuera_de_alcance_solo_citado():
    """CAMBIOS-I18-P §4.1 (REV17-3): la sección sale de las entradas citadas, en su orden; lo asumido no.
    Integrador I1.9 (PR18-1, CAMBIOS-I19-P §5.2): una viñeta por entrada EX con su servicio, el fragmento y la cita
    ENTERA (no el resumen de I1.8); una entrada sin id (forma de I1.8) ya no sale."""
    from nucleo import brief
    req = {k: {"estado": "CITADO", "entradas": [{"valor": f"v-{k}", "origen": "CITADO"}]}
           for k in ("objetivo", "nubes", "alcance_funcional", "canales_integraciones", "ubicacion_usuarios",
                     "marco_normativo", "fuera_de_alcance")}
    cita = "Ya pagamos las licencias de Microsoft 365 con Teams y nuestro Log Analytics."
    req["ya_contratado_por_cliente"] = {"estado": "CITADO", "entradas": [
        {"id": "EX-01", "servicio_catalogo": None, "valor": "licencias de Microsoft 365 con Teams", "cita": cita,
         "fuente": "F1", "origen": "CITADO"},
        {"id": "EX-02", "servicio_catalogo": None, "valor": "inventado", "cita": cita, "fuente": "F1", "origen": "ASUMIDO"},
        {"valor": "sin id, de I1.8", "origen": "CITADO"},
        {"id": "EX-03", "servicio_catalogo": "az-log-analytics", "valor": "Log Analytics", "cita": cita, "fuente": "F2",
         "origen": "ACLARACION"}]}
    lineas = brief._lineas_base(req, lambda t: t)
    i = lineas.index("## Lo que el cliente ya tiene o paga")
    assert lineas[i - 2:i] == ["## Fuera de alcance", "- v-fuera_de_alcance"]
    assert lineas[i + 1:] == [f"- EX-01 (fuera del catálogo): «licencias de Microsoft 365 con Teams». Cita: «{cita}»",
                              f"- EX-03 (az-log-analytics): «Log Analytics». Cita: «{cita}»"]
    del req["ya_contratado_por_cliente"]
    assert "## Lo que el cliente ya tiene o paga" not in brief._lineas_base(req, lambda t: t)


def test_rechazos_de_una_ronda_o_version_anterior_no_cuentan():
    """Revisión 2 de R: tras una DEVUELTA o en la ronda 2, el recuento empieza en el último enrutar."""
    from nucleo import brief

    def c(n, sub, seg):
        return {"n": n, "subcomando": sub, "ts": f"2026-10-13T10:00:{seg:02d}+02:00"}
    est = {"control_versiones": [c(1, "enrutar", 0), c(2, "registrar-experto", 5), c(3, "registrar-experto", 9),
                                 c(4, "decision", 20), c(5, "enrutar", 30), c(6, "registrar-experto", 40)],
           "fallos": [{"fase": "T2", "ts": "2026-10-13T10:00:05+02:00", "error": "rechazo de la versión A"}]}
    assert brief.control_registro_experto(est) == 6
    assert brief.rechazos_vigentes(est, hasta_n=6) == [] and brief.rechazos_vigentes(est) == []
    assert [f["error"] for f in brief.rechazos_vigentes(est, hasta_n=3)] == ["rechazo de la versión A"]
    est["control_versiones"].insert(5, c(6, "registrar-experto", 35))
    est["control_versiones"][-1]["n"] = 7
    est["fallos"].append({"fase": "T2", "ts": "2026-10-13T10:00:35+02:00", "error": "rechazo de la versión B"})
    assert brief.control_registro_experto(est) == 7
    assert [f["error"] for f in brief.rechazos_vigentes(est, hasta_n=7)] == ["rechazo de la versión B"]
