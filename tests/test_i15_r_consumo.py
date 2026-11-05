"""I1.5 · R · PR14-7: consumo de las llamadas A2A fallidas atribuido por ventana y por conversation.id.

Trazas falsas con la forma real (invoke_agent con gen_ai.response.id, gen_ai.conversation.id y error.type; spans chat
con gen_ai.usage.*; pruebas/I14/REAL/diag/claves_429.json). Casos adversos: ninguna candidata, varias, tarea conocida,
otro agente, fuera de ventana, sin uso de tokens (NO_MEDIBLE, nunca 0 €), modelo sin precio y consulta caída.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "hosted"))
import consumo_fallidas as CF  # noqa: E402

EXP = "preventa-experto-azure"


def _ll(inicio, latencia=30.0, task_id=None, error="JSON-RPC Internal error: Received 429", metodo="SendMessage",
        agente=EXP):
    return {"fase": "T2", "agente": agente, "metodo": metodo, "inicio": inicio, "latencia_s": latencia,
            "task_id": task_id, "error": error}


def _inv(ts, resp, conv, err="rate_limit_exceeded", agente=EXP, op=None):
    return {"timestamp": ts, "agente": agente, "respuesta": resp, "conversacion": conv, "err": err,
            "op": op or "a" * 32}


def test_precios_de_la_tabla_de_las_metricas():
    tabla, umbral = CF.precios(CF.KQL_COSTE.read_text(encoding="utf-8"))
    assert umbral == 272000 and tabla[("gpt-6-luna", "corto")] == (0.1056, 0.0106, 0.132, 0.528)
    with pytest.raises(ValueError):
        CF.precios("let ventana = 3h;")


def test_solo_cuentan_los_sendmessage_fallidos_sin_task_id():
    llamadas = [_ll("2026-10-10T18:00:00+00:00", task_id="resp_bien0000001", error=None),
                _ll("2026-10-10T18:01:00+00:00", metodo="GetTask"),
                _ll("2026-10-10T18:02:00+00:00", latencia=20.0)]
    v = CF.fallidas(llamadas)
    assert [x["linea"] for x in v] == [3] and v[0]["hasta"].isoformat() == "2026-10-10T18:02:30+00:00"
    with pytest.raises(ValueError, match="agente no válido"):
        CF.fallidas([_ll("2026-10-10T18:02:00+00:00", agente="x\"; drop")])
    with pytest.raises(ValueError, match="sin zona"):
        CF.fallidas([_ll("2026-10-10T18:02:00")])


def test_atribucion_por_ventana_con_sus_casos_adversos():
    v = CF.fallidas([_ll("2026-10-10T18:00:00+00:00"), _ll("2026-10-10T18:10:00+00:00"),
                     _ll("2026-10-10T18:20:00+00:00"), _ll("2026-10-10T18:30:00+00:00")])
    inv = [_inv("2026-10-10T18:00:01.5Z", "resp_fallo0000001", "conv_uno00000001"),
           _inv("2026-10-10T18:00:05Z", "resp_ok000000001", "conv_ok000000001", err=""),        # sin error: se descarta
           _inv("2026-10-10T18:10:02Z", "resp_dos00000001", "conv_dos00000001"),
           _inv("2026-10-10T18:10:03Z", "resp_dos00000002", "conv_dos00000002"),                # dos con error: ambigua
           _inv("2026-10-10T18:20:01Z", "resp_conocida0001", "conv_tres0000001"),               # tarea conocida
           _inv("2026-10-10T18:20:02Z", "resp_otro00000001", "conv_otro0000001", agente="preventa-verificador"),
           _inv("2026-10-10T18:31:00Z", "resp_tarde0000001", "conv_tarde000001")]               # fuera de ventana
    CF.atribuir(v, inv, {"resp_conocida0001"})
    assert [x["atribucion"] for x in v] == ["ATRIBUIDA", "AMBIGUA", "SIN_SPAN", "SIN_SPAN"]
    assert v[0]["respuesta"] == "resp_fallo0000001" and v[0]["error_traza"] == "rate_limit_exceeded"
    assert v[1]["candidatas"] == ["resp_dos00000001", "resp_dos00000002"] and v[1]["conversacion"] is None


def _correr(tmp_path, llamadas, invocaciones, spans, error=None):
    a2a = tmp_path / "a2a.jsonl"
    a2a.write_text("\n".join(json.dumps(x) for x in llamadas) + "\n", encoding="utf-8")
    consultas = []

    def consultar(kql):
        consultas.append(kql)
        if error:
            raise RuntimeError(error)
        return invocaciones if kql.startswith("dependencies") else spans
    rc = CF.main(["--a2a", str(a2a), "--salida", str(tmp_path / "inf.json")], consultar=consultar)
    return rc, json.loads((tmp_path / "inf.json").read_text(encoding="utf-8")), consultas


def test_consumo_medido_no_medible_sin_precio_y_consulta_caida(tmp_path):
    ll = [_ll("2026-10-10T18:00:00+00:00")]
    inv = [_inv("2026-10-10T18:00:01Z", "resp_fallo0000001", "conv_uno00000001")]
    chat = {"fase": "chat", "conversacion": "conv_uno00000001", "op": "b" * 32, "entrada": 100000, "salida": 2000,
            "cache_leida": 40000, "cache_escrita": 0, "modelo": "gpt-6-luna-2026-09-22"}
    rc, inf, consultas = _correr(tmp_path, ll, inv, [chat, {"fase": "execute_tool", "conversacion": "conv_uno00000001"}])
    esperado = round((60000 * 0.1056 + 40000 * 0.0106 + 2000 * 0.528) / 1e6, 4)
    f = inf["fallidas"][0]
    assert rc == 0 and f["consumo"] == "MEDIDO" and f["coste_eur"] == esperado and f["llamadas_herramienta"] == 1
    assert '"conv_uno00000001"' in consultas[1] and inf["coste_medido_eur"] == esperado
    rc, inf, _ = _correr(tmp_path, ll, inv, [{"fase": "execute_tool", "conversacion": "conv_uno00000001"}])
    f = inf["fallidas"][0]   # lo observado en real: sin spans chat con uso → NO_MEDIBLE, nunca 0 €
    assert rc == 3 and f["consumo"] == "NO_MEDIBLE" and f["coste_eur"] is None and inf["no_medibles"] == 1
    rc, inf, _ = _correr(tmp_path, ll, inv, [dict(chat, modelo="gpt-9-desconocido")])
    assert rc == 1 and inf["fallidas"][0]["sin_precio"] == 1 and inf["fallidas"][0]["coste_eur"] is None
    rc, inf, _ = _correr(tmp_path, ll, inv, [], error="sin red (forzado)")
    assert rc == 1 and "sin red" in inf["error"] and inf["fallidas"][0]["atribucion"] == "NO_MEDIDA"
    rc, inf, _ = _correr(tmp_path, ll, [inv[0]] * CF.TOPE, [])
    assert rc == 1 and "tope" in inf["error"]
    rc, inf, consultas = _correr(tmp_path, [_ll("2026-10-10T18:00:00+00:00", task_id="resp_x0000000001", error=None)],
                                 inv, [])
    assert rc == 0 and not consultas and inf["fallidas_sin_task_id"] == 0


def test_la_consulta_solo_lleva_identificadores_validados():
    q = CF.consulta_consumo([{"conversacion": "conv_bien0000001", "op": "c" * 32},
                             {"conversacion": "conv_x' or 1==1 //", "op": "no-hex"}],
                            CF._t("2026-10-10T18:00:00Z"), CF._t("2026-10-10T17:59:00Z"))
    assert '"conv_bien0000001"' in q and "or 1==1" not in q and "no-hex" not in q and f'"{"c" * 32}"' in q


def test_conversacion_compartida_no_se_suma_dos_veces():
    """Revisión (I1.5): si dos fallidas casan con la misma conversación, ninguna se atribuye (AMBIGUA)."""
    v = CF.fallidas([_ll("2026-10-10T18:00:00+00:00"), _ll("2026-10-10T18:10:00+00:00"),
                     _ll("2026-10-10T18:20:00+00:00")])
    inv = [_inv("2026-10-10T18:00:01Z", "resp_a000000001", "conv_compartida01", op="1" * 32),
           _inv("2026-10-10T18:10:01Z", "resp_b000000001", "conv_compartida01", op="2" * 32),
           _inv("2026-10-10T18:20:01Z", "resp_c000000001", "conv_sola0000001", op="2" * 32)]   # misma operación que b
    CF.atribuir(v, inv, set())
    assert [x["atribucion"] for x in v] == ["AMBIGUA", "AMBIGUA", "AMBIGUA"]
    assert all(x["conversacion"] is None and "compartida" in x["motivo_ambigua"] for x in v)


def test_un_span_que_casa_con_dos_llamadas_no_se_suma_a_ninguna(tmp_path):
    """Revisión (2.ª pasada): conversación de una llamada y operación de otra en el mismo span."""
    ll = [_ll("2026-10-10T18:00:00+00:00"), _ll("2026-10-10T18:10:00+00:00")]
    inv = [_inv("2026-10-10T18:00:01Z", "resp_a000000001", "conv_uno00000001", op="1" * 32),
           _inv("2026-10-10T18:10:01Z", "resp_b000000001", "conv_dos00000001", op="2" * 32)]
    cruzado = {"fase": "chat", "conversacion": "conv_uno00000001", "op": "2" * 32, "entrada": 10, "salida": 1,
               "cache_leida": 0, "cache_escrita": 0, "modelo": "gpt-6-luna-2026-09-22"}
    rc, inf, _ = _correr(tmp_path, ll, inv, [cruzado])
    assert rc == 3 and [f["atribucion"] for f in inf["fallidas"]] == ["AMBIGUA", "AMBIGUA"], inf
    assert all(f["coste_eur"] is None and f["spans_chat"] == 0 for f in inf["fallidas"])
