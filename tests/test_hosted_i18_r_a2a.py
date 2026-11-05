"""I1.8 · papel R · REVERIF17-1 y REVERIF17-6 (cliente A2A y turno del hosted). Casos adversos.

REVERIF17-1: una tarea pendiente que GetTask ya no encuentra (JSON-RPC -32001, forma real en
pruebas/I13/E2E-B/procedencia_gettask.json) se da por perdida: se registra con su motivo (sin la hipótesis falsa «sigue
viva»), el siguiente SIGUE reenvía el texto con ese motivo y, tras DESBLOQUEAR, no se intenta recoger una tarea que no
existe. Era la prueba xfail estricta de pruebas/I17/REVERIF/sondas/test_reverif_a2a.py.
"""
from __future__ import annotations

import json

from tests.test_hosted_falsos import coordinador, httpx
from tests.test_hosted_turno import _HOY, ASUMIR, _estado, _hasta_insuficiente
from tests.test_hosted_i17_arr_a2a import A2ALento, _a2a, _cliente, _rapido, _servidor, _tarea
from preventa_hosted import a2a as A
from preventa_hosted import fases

EXPERTO = "preventa-experto-azure"
NO_EXISTE = {"code": -32001, "message": "The specified task ID does not exist or is not accessible",
             "data": [{"reason": "TASK_NOT_FOUND"}]}


def _no_existe(cid: str = "x") -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": cid, "error": NO_EXISTE})


class A2APerdida(A2ALento):
    """La tarea queda en curso; con `perdida`, el GetTask de sondeo responde -32001 (caducada o purgada)."""

    def __init__(self, en_curso: int):
        super().__init__(en_curso)
        self.perdida = False

    def _get_task(self, cuerpo, agente):
        if self.perdida and cuerpo["params"].get("historyLength") == 0:
            return _no_existe(cuerpo["id"])
        return super()._get_task(cuerpo, agente)


def _envios(a2a):
    return [x for x in a2a.recibidos if x["agente"] == EXPERTO]


def test_tarea_perdida_se_registra_se_reenvia_y_no_se_recoge_tras_desbloquear(tmp_path, monkeypatch):
    a2a = A2APerdida(en_curso=10_000)
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _rapido(c, espera=60)
    _hasta_insuficiente(c)
    assert "pendiente" in c.manejar(ASUMIR, []) and len(_envios(a2a)) == 1
    a2a.perdida = True
    r = c.manejar("SIGUE", [])                       # recoge la pendiente: GetTask -32001 dos veces → perdida
    est = _estado(c)
    ultimo = [x for x in _a2a(c) if x["metodo"] == "SendMessage" and x["agente"] == EXPERTO][-1]
    assert ultimo["recuperada"] and ultimo["perdida"] and not ultimo["pendiente"] and ultimo["codigo_jsonrpc"] == -32001
    assert "-32001" in ultimo["error"] and "TASK_NOT_FOUND" in ultimo["error"], ultimo["error"]
    assert est["intentos"]["T2"] == 2 and "sigue viva" not in est["fallos"][-1]["hipotesis"]
    assert "ya no existe" in est["fallos"][-1]["hipotesis"] and "-32001" in est["fallos"][-1]["error"], r
    assert len(_envios(a2a)) == 1                     # recoger no reenvía
    assert fases.pendiente_previa(c.cfg.trabajo, EXPERTO, "T2", ultimo["sha256_enviado"]) is None
    r = c.manejar("SIGUE", [])                        # reenvía, con el task_id perdido y su motivo
    assert len(_envios(a2a)) == 2 and "se dio por perdida" in r, r
    reenvio = [x for x in _a2a(c) if x["metodo"] == "SendMessage" and x["agente"] == EXPERTO][-1]
    assert reenvio["reenvio_de"] == ultimo["task_id"] and "-32001" in reenvio["motivo_reenvio"]
    est = _estado(c)                                  # el reenvío también se pierde: 3/3
    assert est["estado"] == "BLOQUEADA" and "sigue viva" not in est["fallos"][-1]["hipotesis"]
    h = est["hash_contenido"]
    a2a.perdida, a2a.en_curso = False, 0
    r = c.manejar(f"DECISION | Responsable comercial | DESBLOQUEAR | {_HOY} | {h} | la tarea se perdió en Foundry", [])
    assert len(_envios(a2a)) == 3, r                  # tras DESBLOQUEAR: envío nuevo, no recogida de una inexistente
    assert not any(x.get("recuperada") for x in _a2a(c)[-3:] if x["metodo"] == "SendMessage" and x["agente"] == EXPERTO)
    assert "EXPERTO: VÁLIDA" in r, r


def test_un_solo_no_encontrada_seguido_de_la_tarea_no_es_perdida():
    """Una tarea recién creada que aún no es visible (un -32001 suelto) no se da por perdida."""
    man, _ = _servidor([_no_existe(), "TASK_STATE_WORKING"])
    c, _ = _cliente(man)
    ll = c.enviar("x", "hola")
    assert ll.ok and not ll.perdida and ll.errores_sondeo == 1


def test_no_encontrada_separada_por_una_lectura_buena_no_es_perdida():
    """Revisión propia: la racha de -32001 la corta una lectura buena (WORKING) entre medias."""
    man, _ = _servidor([_no_existe(), "TASK_STATE_WORKING", _no_existe(), "TASK_STATE_WORKING"])
    c, _ = _cliente(man)
    ll = c.enviar("x", "hola")
    assert ll.ok and not ll.perdida and ll.errores_sondeo == 2


def test_otro_error_permanente_no_se_clasifica_como_perdida():
    """-32603 («Received 400», id mal formado en la sonda real) no es TaskNotFound: pendiente, nunca perdida."""
    malo = httpx.Response(200, json={"jsonrpc": "2.0", "id": "x", "error": {"code": -32603, "message": "Internal error"}})
    man, _ = _servidor([malo] * 6)
    c, _ = _cliente(man)
    ll = c.enviar("x", "hola")
    assert ll.pendiente and not ll.perdida and ll.codigo_jsonrpc is None and "5 GetTask seguidos" in ll.error


def test_no_encontrada_alternada_con_otros_errores_no_suma_seguidas():
    malo = httpx.Response(200, json={"jsonrpc": "2.0", "id": "x", "error": {"code": -32603, "message": "Internal"}})
    man, _ = _servidor([_no_existe(), malo, _no_existe(), malo, _no_existe()])
    c, _ = _cliente(man)
    ll = c.enviar("x", "hola")
    assert ll.pendiente and not ll.perdida


def test_sondeo_sin_id_de_tarea_no_se_acepta_como_la_propia():
    """REVERIF17-6: un GetTask que devuelve una tarea COMPLETED sin id no se toma por la tarea propia."""
    sin_id = httpx.Response(200, json={"jsonrpc": "2.0", "id": "x", "result": {
        "status": {"state": "TASK_STATE_COMPLETED"}, "artifacts": [{"parts": [{"text": "ajeno"}]}]}})
    man, _ = _servidor([sin_id] * 5)
    c, _ = _cliente(man)
    ll = c.enviar("x", "hola")
    assert not ll.ok and ll.pendiente and ll.texto == "" and "sin id de tarea" in ll.error


def test_relectura_con_otro_id_o_sin_id_es_error():
    for res in ({"task": _tarea("resp_otra", "TASK_STATE_COMPLETED", "t")},
                {"status": {"state": "TASK_STATE_COMPLETED"}, "artifacts": [{"parts": [{"text": "t"}]}]}):
        c, _ = _cliente(lambda req, res=res: httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": res}))
        ll = c.tarea("x", "resp_1")
        assert ll.error and "no es la pedida" in ll.error and not A.Llamada.ok.fget(ll)
