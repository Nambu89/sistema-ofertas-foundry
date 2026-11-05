"""Pruebas unitarias del núcleo de la máquina de estados (papel BA). Sin red."""
from __future__ import annotations

import copy
import datetime

import pytest

from tests.test_i1_estado_comun import (EJEMPLOS, TRANSCRIPCION, brief, decision, ejemplo, errores, estado, experto,
                                        hashes, suficiencia, verificacion)
from lib import hashes as lib_hashes


def _estado_ejemplo() -> dict:
    return copy.deepcopy(ejemplo("estado"))


def test_json_canonico_identico_a_lib():
    for obj in (ejemplo("estado"), {"b": [1, 2.5, None, True], "a": "ñ €"}, []):
        assert hashes.json_canonico(obj) == lib_hashes.json_canonico(obj)


def test_hash_contenido_es_el_del_ejemplo_y_excluye_lo_de_fuera():
    est = _estado_ejemplo()
    h = hashes.hash_contenido(est)
    assert h == est["hash_contenido"]
    est["decisiones"].append({"x": 1})
    est["intentos"]["T2"] = 2
    est["control_versiones"] = []
    est["artefactos"]["zip"] = None
    assert hashes.hash_contenido(est) == h
    est["carga"]["alta"]["titulo"] += "."
    assert hashes.hash_contenido(est) != h


def test_hash_contenido_exige_claves_exactas():
    est = _estado_ejemplo()
    est["carga"]["extra"] = 1
    with pytest.raises(errores.IntegridadRota):
        hashes.hash_contenido(est)
    del est["carga"]["extra"], est["carga"]["briefs"]
    with pytest.raises(errores.IntegridadRota):
        hashes.hash_contenido(est)


def test_sha256_texto_normaliza_crlf():
    assert hashes.sha256_texto("a\r\nb") == hashes.sha256_texto("a\nb") == hashes.sha256_bytes(b"a\nb")


@pytest.mark.parametrize("n, rango", [(1, "menos de 50"), (49, "menos de 50"), (50, "entre 50 y 100"),
                                      (99, "entre 50 y 100"), (100, "entre 100 y 500"), (499, "entre 100 y 500"),
                                      (500, "entre 500 y 1.000"), (999, "entre 500 y 1.000"),
                                      (1000, "entre 1.000 y 5.000"), (4999, "entre 1.000 y 5.000"),
                                      (5000, "más de 5.000")])
def test_rangos(n, rango):
    assert brief.rango_usuarios(n) == rango


def test_anonimizar_terminos_personas_y_casi_identificadores():
    sens = ["Kelvara Ensayos Industriales", "Kelvara", "Marta Olmedo", "Zaragoza"]
    t = ("KELVARA y kelvara ensayos industriales; marta dijo que Olmedo y Marta irán a Zaragóza; "
         "1.500 técnicos y 30 usuarios; escribe a marta@kelvara.es o al +34 976 123 456; "
         "ver https://intranet.kelvara.es/x y https://learn.microsoft.com/azure/search; Kelvarano no se toca")
    a = brief.anonimizar(t, sens, ["Kelvara Ensayos Industriales, S.A.", "KELVARA"], ["Marta Olmedo"])
    assert a.startswith("[CLIENTE] y [CLIENTE]; [PERSONA] dijo que [PERSONA] y [PERSONA] irán a [SENSIBLE]")
    assert "entre 1.000 y 5.000 técnicos" in a and "menos de 50 usuarios" in a
    assert "[CORREO]" in a and "[TELÉFONO]" in a and "[URL]" in a and "https://learn.microsoft.com/azure/search" in a
    assert "Kelvarano" in a
    assert brief.hallazgos_sensibles(a, sens) == []
    assert brief.anonimizar(a, sens, ["KELVARA"], ["Marta Olmedo"]) == a  # idempotente (rangos incluidos)


def test_hallazgos_detecta_restos():
    h = brief.hallazgos_sensibles("Visita a zaragoza con 150 técnicos; ana@x.com", ["Zaragoza"])
    assert any("Zaragoza" in x for x in h) and any("150 técnicos" in x for x in h) and any("correo" in x for x in h)


VTT = ("WEBVTT\n\nNOTE\nnota interna que no cuenta\n\n1\n00:00:01.000 --> 00:00:04.000\n<v Ana Ruiz>Queremos que esto "
       "viva en Azure</v>\n\nc2\n00:00:05.000 --> 00:00:09.000\n<v.loud Luis Gil>y que los datos se queden en la UE\n")


def test_normalizar_para_cita_vtt_con_y_sin_identificadores():
    n = suficiencia.normalizar_para_cita(VTT)
    assert "nota interna" not in n and "-->" not in n and "ana ruiz" not in n and " c2 " not in n
    assert "queremos que esto viva en azure y que los datos se queden en la ue" in n
    assert suficiencia.hablantes(VTT) == ["Ana Ruiz", "Luis Gil"]
    assert suficiencia.hablantes("[00:01:02] María López: hola\n00:05 Pepe: adiós") == ["María López", "Pepe"]


def test_cita_valida_minimos_y_tildes():
    fuentes = {"F1": VTT}
    assert suficiencia.cita_valida("QUEREMOS que esto VIVA en Azure", fuentes)
    assert suficiencia.cita_valida("viva en azure y que los datos", fuentes)  # cruza dos cues
    assert not suficiencia.cita_valida("en Azure", fuentes)
    assert not suficiencia.cita_valida("queremos que esto viva en AWS", fuentes)
    texto = suficiencia.extraer_texto(TRANSCRIPCION)
    assert suficiencia.cita_valida("todos estan en espana. No hay usuarios fuera", {"F1": texto})


@pytest.mark.parametrize("url, norma, permitida, arq", [
    ("https://learn.microsoft.com/en-us/azure/Architecture/ai-ml/?view=x#y", "https://learn.microsoft.com/azure/architecture/ai-ml", True, True),
    ("https://learn.microsoft.com/es-es/azure/search/", "https://learn.microsoft.com/azure/search", True, False),
    ("https://learn.microsoft.com/azure/searchfoo/x", "https://learn.microsoft.com/azure/searchfoo/x", False, False),
    ("http://learn.microsoft.com/azure/search", "", False, False),
    ("https://learn.microsoft.com.evil.com/azure/search", "", False, False),
    ("https://learn.microsoft.com:8443/azure/search", "", False, False),
])
def test_urls(url, norma, permitida, arq):
    assert experto.normalizar_url(url) == norma
    assert experto.es_referencia_permitida(url) is permitida and experto.es_referencia_arquitectura(url) is arq


@pytest.mark.parametrize("texto", ['{"a": 1, "a": 2}', '{"a": NaN}', '[1]', '```\n{"a": 1}\n```\n```', 'nada'])
def test_parsear_rechaza(texto):
    with pytest.raises(errores.ReglaIncumplida):
        experto.parsear(texto)


def test_parsear_quita_solo_lo_equivalente():
    escapado = '{"a": "x' + chr(92) + 'ny"}'  # salto escapado dentro de la cadena JSON
    assert experto.parsear(chr(0xFEFF) + '  ```JSON' + chr(10) + escapado + chr(10) + '```  ') == {"a": "x" + chr(10) + "y"}


def test_url_con_puntos_no_pasa_la_lista_blanca():
    for url in ("https://learn.microsoft.com/azure/architecture/../../dotnet/api", "https://learn.microsoft.com/azure/search/%2e%2e/x"):
        assert experto.normalizar_url(url) == "" and not experto.es_referencia_permitida(url)


def test_matriz_de_transiciones_rechaza_todo_lo_no_listado():
    est = _estado_ejemplo()
    for disparador, tabla in estado.TRANSICIONES.items():
        for desde in estado.ESTADOS + (estado.SIN_ESTADO,):
            for destino in estado.ESTADOS:
                est["estado"] = desde
                if destino in tabla.get(desde, frozenset()):
                    estado.transitar(est, disparador, destino)
                    assert est["estado"] == destino
                else:
                    with pytest.raises(errores.TransicionNoPermitida):
                        estado.transitar(est, disparador, destino)
    assert "APROBADA" not in estado.TRANSICIONES["registrar-fallo"] and "APROBADA" not in estado.TRANSICIONES["bloquear"]


@pytest.mark.parametrize("nombre, ajuste, esperado", [
    ("BORRADOR", {}, "Rellenar entrada/requisitos.json"),
    ("INFORMACION_INSUFICIENTE", {}, "Presentar al comercial las preguntas a/b/c/d"),
    ("EN_ANALISIS", {"sin_brief": True}, "enrutar"),
    ("EN_ANALISIS", {"sin_respuesta": True}, "Enviar el brief BRF-OF-KELVARA-001-A-AZ-R1 a preventa-experto-azure"),
    ("EN_ANALISIS", {}, "Terminar el turno. En el siguiente: consolidar"),
    # PR16-1 (arreglos I1.6): el ejemplo trae 7 referencias, una por servicio del catálogo: dos lotes de referencias
    # integrador I1.7: sin lote de precios, el ejemplo tiene 4 lotes (referencias y componentes)
    ("EN_VERIFICACION", {}, "Enviar el lote CNS-OF-KELVARA-001-A-R1-L1 (1 de 4 del consolidado CNS-OF-KELVARA-001-A-R1"),
    ("EN_VERIFICACION", {"sin_lotes": True}, "Enviar el consolidado CNS-OF-KELVARA-001-A-R1 a preventa-verificador"),
    ("VERIFICADA", {"sin": ("anexo_consumo", "estimacion")}, "Terminar el turno. En el siguiente: anexo-consumo"),
    ("VERIFICADA", {"sin": ("estimacion",)}, "estimar (el núcleo compone entrada/estimacion_entrada.json"),
    ("VERIFICADA", {}, "paquete"),
    ("STOP_PRESUPUESTO", {}, "Parar. Precio 28025.25 EUR > 100.000 EUR"),
    ("LISTA_PARA_REVISION", {}, "El comercial descarga el ZIP, ejecuta verificar_paquete.py"),
    ("EN_REVISION_PREVENTA", {}, "Esperar la decisión de Responsable de preventa"),
    ("EN_APROBACION_AREA", {}, "El comercial envía mensaje_aprobador.txt"),
    ("APROBADA", {}, "paquete (regenera la diapositiva 2"),
    ("DEVUELTA_CON_COMENTARIOS", {}, "Versión A. Según el comentario"),
    ("BLOQUEADA", {}, "Parar. Motivo: prueba. El comercial decide: DECISION | Responsable comercial | DESBLOQUEAR"),
])
def test_siguiente_paso_por_estado(nombre, ajuste, esperado):
    est = _estado_ejemplo()
    est["estado"], est["motivo_bloqueo"] = nombre, "prueba"
    if ajuste.get("sin_brief"):
        est["carga"]["briefs"] = []
    if ajuste.get("sin_respuesta"):
        est["carga"]["respuestas_expertos"] = {}
    if ajuste.get("sin_lotes"):
        est["carga"]["consolidado"]["lotes"] = []
    if nombre == "EN_ANALISIS" and not ajuste:
        est["ronda_verificacion"] = 0
    if nombre in ("EN_ANALISIS", "EN_VERIFICACION"):
        est["ronda_verificacion"] = 0
    for k in ajuste.get("sin", ()):
        est["carga"][k] = None
    paso = estado.siguiente_paso(est)
    assert paso.startswith(esperado), paso
    assert "<" not in paso and ">" not in paso.replace("-> ", "").replace(" > ", " ")
    assert estado.siguiente_paso(est, fallo_previo=True).startswith("PRIMERO: registrar-fallo --fase")


def test_cascada_de_invalidacion():
    est = _estado_ejemplo()
    assert estado.invalidar_desde(est, "anexo_consumo") == ["estimacion", "textos_cliente"]
    est = _estado_ejemplo()
    anuladas = estado.invalidar_desde(est, "requisitos")
    assert anuladas == ["respuestas_expertos", "consolidado", "verificacion", "anexo_consumo", "estimacion", "textos_cliente"]
    assert est["carga"]["respuestas_expertos"] == {} and est["carga"]["briefs"] and est["carga"]["requisitos"]
    with pytest.raises(errores.IntegridadRota):
        estado.invalidar_desde(est, "otra_cosa")


def test_registrar_intento_y_desbloquear_por_fase():
    est = _estado_ejemplo()
    est["estado"] = "EN_VERIFICACION"
    for n in (1, 2, 3):
        assert estado.registrar_intento(est, "T3", "HTTP 400 tool_user_error", "hipótesis") == n
    assert est["estado"] == "BLOQUEADA" and est["estado_previo"] == "EN_VERIFICACION"
    assert estado.registrar_intento(est, "T3", "otro", "otra") == 3 and est["estado_previo"] == "EN_VERIFICACION"
    assert estado.desbloquear(est) == "EN_VERIFICACION" and est["intentos"]["T3"] == 0 and est["motivo_bloqueo"] is None
    with pytest.raises(errores.EntradaInvalida):
        estado.registrar_intento(est, "T3", "", "x")


def test_siguiente_version():
    assert estado.siguiente_version("A") == "B"
    with pytest.raises(errores.IntegridadRota):
        estado.siguiente_version("Z")


def test_parsear_linea_admite_barras_en_comentarios_y_normaliza_revisor():
    h = "a" * 64
    d = decision.parsear_linea(f"  DECISION|RESPONSABLE DE PREVENTA |APROBADA| 2026-10-08 |{h}| ok | con | barras ")
    assert d["revisor"] == "Responsable de preventa" and d["comentarios"] == "ok | con | barras"
    assert d["linea"] == f"DECISION | Responsable de preventa | APROBADA | 2026-10-08 | {h} | ok | con | barras"
    for mala in ("DECISIÓN | x", f"DECISION | Responsable de preventa | OTRO | 2026-10-08 | {h} | x",
                 f"DECISION | Responsable de preventa | APROBADA | 2026-13-01 | {h} | x",
                 "DECISION | Responsable de preventa | APROBADA | 2026-10-08 | ABC | x"):
        with pytest.raises(errores.EntradaInvalida):
            decision.parsear_linea(mala)


def test_firmas_solo_con_hash_vigente():
    est = _estado_ejemplo()
    est["estado"] = "EN_REVISION_PREVENTA"
    hoy = datetime.date(2026, 10, 9)
    linea = f"DECISION | Responsable de preventa | APROBADA | 2026-10-09 | {est['hash_contenido']} | ok"
    decision.registrar(est, linea, hoy)
    f = decision.firmas(est)
    assert f["elaborado"]["iniciales"] == "RC" and f["revisado"]["fecha"] == "2026-10-09" and f["aprobado"] is None
    est["carga"]["alta"]["titulo"] += "."
    assert decision.firmas(est)["revisado"] is None  # contenido regenerado: la firma deja de valer


def test_aprobacion_anterior_a_la_revision_se_rechaza():
    est = _estado_ejemplo()
    est["estado"] = "EN_REVISION_PREVENTA"
    h = est["hash_contenido"]
    decision.registrar(est, f"DECISION | Responsable de preventa | APROBADA | 2026-10-10 | {h} | ok", datetime.date(2026, 10, 10))
    with pytest.raises(errores.ReglaIncumplida) as e:
        decision.registrar(est, f"DECISION | Responsable de área | APROBADA | 2026-10-09 | {h} | ok", datetime.date(2026, 10, 10))
    assert any("anterior a la revisión" in x for x in e.value.errores)
    est2 = _estado_ejemplo()
    est2["estado"] = "EN_REVISION_PREVENTA"
    with pytest.raises(errores.ReglaIncumplida) as e:
        decision.registrar(est2, f"DECISION | Responsable de preventa | APROBADA | 2026-10-01 | {h} | ok", datetime.date(2026, 10, 10))
    assert any("anterior a la de elaboración" in x for x in e.value.errores)
