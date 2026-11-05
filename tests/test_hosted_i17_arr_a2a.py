"""PR17-2 (arreglos I1.7): SendMessage no bloqueante (returnImmediately) y espera de la tarea con GetTask.

Hechos de partida: el experto real tardó 111,9 y 112,6 s y el tope síncrono de 110 s las cortó, aunque Foundry terminó
las dos ejecuciones (VER17-4). El endpoint real admite returnImmediately (pruebas/I17/ARREGLOS/sonda_a2a_verificador.json).
"""
from __future__ import annotations

import copy
import json

import pytest

from tests.test_hosted_falsos import A2AFalso, PROYECTO, adjunto_transcripcion, coordinador, httpx, token_prueba
from tests.test_hosted_turno import ASUMIR, _estado, _hasta_insuficiente
from preventa_hosted import a2a as A
from preventa_hosted import config


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.t += s


def _tarea(tid: str, estado: str, texto: str | None = None) -> dict:
    t = {"id": tid, "contextId": "ctxt_" + tid, "status": {"state": estado}}
    if texto is not None:
        t["artifacts"] = [{"parts": [{"text": texto}]}]
    return t


def _cliente(manejador, espera=420.0, sondeo=5.0):
    reloj = Reloj()
    c = A.ClienteA2A(lambda a: f"{PROYECTO}/agents/{a}/endpoint/protocols/a2a", token_prueba, 30,
                     httpx.MockTransport(manejador), espera_s=espera, sondeo_s=sondeo, dormir=reloj.dormir, reloj=reloj)
    return c, reloj


def _servidor(estados_get: list, final_texto='{"ok":1}', send_estado="TASK_STATE_SUBMITTED"):
    """SendMessage → tarea en `send_estado`; cada GetTask consume un elemento de `estados_get` (estado, excepción o
    respuesta httpx); agotada la lista, la tarea está COMPLETED con `final_texto`."""
    vistos = []

    def manejador(req):
        c = json.loads(req.content)
        vistos.append(c)
        if c["method"] == "SendMessage":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"], "result": {"task": _tarea("resp_1", send_estado)}})
        if estados_get:
            x = estados_get.pop(0)
            if isinstance(x, Exception):
                raise x
            if isinstance(x, httpx.Response):
                return x
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"], "result": _tarea("resp_1", x)})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"],
                                         "result": _tarea("resp_1", "TASK_STATE_COMPLETED", final_texto)})
    return manejador, vistos


def test_envio_no_bloqueante_y_espera_hasta_completar():
    man, vistos = _servidor(["TASK_STATE_WORKING", "TASK_STATE_WORKING"])
    c, reloj = _cliente(man)
    ll = c.enviar("preventa-experto-azure", "brief exacto\n")
    assert vistos[0]["method"] == "SendMessage" and vistos[0]["params"]["configuration"] == {"returnImmediately": True}
    assert vistos[0]["params"]["message"]["parts"] == [{"text": "brief exacto\n"}]
    assert [v["method"] for v in vistos[1:]] == ["GetTask"] * 3 and all(v["params"]["id"] == "resp_1" for v in vistos[1:])
    assert ll.ok and ll.texto == '{"ok":1}' and ll.task_id == "resp_1" and ll.sondeos == 3 and ll.latencia_s == 15.0
    assert ll.modo == "no_bloqueante" and not ll.pendiente and ll.registro()["sondeos"] == 3


def test_una_respuesta_de_112_s_ya_no_se_pierde():
    """El caso real: 112,6 s con el antiguo tope de 110 s. Ahora se espera hasta la respuesta."""
    man, _ = _servidor(["TASK_STATE_WORKING"] * 22)   # 23 sondeos de 5 s = 115 s
    c, _ = _cliente(man)
    ll = c.enviar("preventa-experto-azure", "brief")
    assert ll.ok and ll.latencia_s == 115.0 and ll.sondeos == 23


def test_servidor_que_ignora_return_immediately_se_usa_tal_cual():
    man, vistos = _servidor([], send_estado="TASK_STATE_COMPLETED")

    def manejador(req):
        c = json.loads(req.content)
        vistos.append(c)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"],
                                         "result": {"task": _tarea("resp_1", "TASK_STATE_COMPLETED", "{}")}})
    c, _ = _cliente(manejador)
    ll = c.enviar("x", "hola")
    assert ll.ok and ll.sondeos == 0 and [v["method"] for v in vistos] == ["SendMessage"]


def test_get_task_fallido_se_repite_y_se_cuenta():
    errores = [httpx.ConnectError("DNS"), httpx.Response(503, text="ocupado")]
    man, _ = _servidor(errores + ["TASK_STATE_WORKING"])
    c, _ = _cliente(man)
    ll = c.enviar("x", "hola")
    assert ll.ok and ll.errores_sondeo == 2 and ll.sondeos == 4


def test_cinco_errores_seguidos_dejan_la_tarea_pendiente():
    man, _ = _servidor([httpx.ConnectError("DNS")] * A.MAX_ERRORES_SONDEO)
    c, _ = _cliente(man)
    ll = c.enviar("x", "hola")
    assert not ll.ok and ll.pendiente and ll.task_id == "resp_1" and "5 GetTask seguidos" in ll.error


def test_espera_agotada_deja_la_tarea_pendiente_con_su_task_id():
    man, _ = _servidor(["TASK_STATE_WORKING"] * 1000)
    c, _ = _cliente(man, espera=60, sondeo=5)
    ll = c.enviar("x", "hola")
    assert not ll.ok and ll.pendiente and ll.task_id == "resp_1" and "tras 60 s" in ll.error and ll.sondeos == 12


def test_cancelacion_deja_la_tarea_pendiente():
    man, _ = _servidor(["TASK_STATE_WORKING"] * 10)
    c, _ = _cliente(man)
    n = {"v": 0}

    def cancelado():
        n["v"] += 1
        return n["v"] > 2
    c.cancelado = cancelado
    ll = c.enviar("x", "hola")
    assert not ll.ok and ll.pendiente and "canceló" in ll.error


@pytest.mark.parametrize("estado", ["TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_INPUT_REQUIRED"])
def test_estado_terminal_no_completado_es_error(estado):
    man, _ = _servidor(["TASK_STATE_WORKING", estado])
    c, _ = _cliente(man)
    ll = c.enviar("x", "hola")
    assert not ll.ok and not ll.pendiente and estado in ll.error


def test_get_task_de_otra_tarea_no_se_usa():
    def manejador(req):
        c = json.loads(req.content)
        if c["method"] == "SendMessage":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"],
                                             "result": {"task": _tarea("resp_1", "TASK_STATE_WORKING")}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"],
                                         "result": _tarea("resp_OTRA", "TASK_STATE_COMPLETED", "{}")})
    c, _ = _cliente(manejador)
    ll = c.enviar("x", "hola")
    assert not ll.ok and "otra tarea" in ll.error


def test_config_espera_y_sondeo():
    from tests.test_hosted_falsos import NUCLEO
    base = {"FOUNDRY_PROJECT_ENDPOINT": PROYECTO, "PREVENTA_APP_NUCLEO": str(NUCLEO)}
    c = config.cargar(base)
    assert (c.espera_a2a_s, c.sondeo_a2a_s) == (420.0, 5.0)
    with pytest.raises(config.ErrorConfig, match="fuera de"):
        config.cargar({**base, "PREVENTA_A2A_ESPERA_S": "5"})
    with pytest.raises(config.ErrorConfig, match="no es un número"):
        config.cargar({**base, "PREVENTA_A2A_SONDEO_S": "nan-no"})


# ── Con el coordinador y el núcleo reales ──────────────────────────────────────────────────────────────────────────
class A2ALento(A2AFalso):
    """Como A2AFalso, pero SendMessage con returnImmediately devuelve la tarea en curso y GetTask la da en WORKING
    mientras `en_curso` > 0 (la relectura posterior, ya terminada, devuelve la tarea guardada como siempre)."""

    def __init__(self, en_curso: int):
        super().__init__()
        self.en_curso = en_curso

    def _get_task(self, cuerpo, agente):
        if cuerpo["params"].get("historyLength") == 0 and self.en_curso > 0:
            self.en_curso -= 1
            t = self.tareas[cuerpo["params"]["id"]]
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": cuerpo["id"], "result": {
                "id": t["id"], "contextId": t["contextId"], "status": {"state": "TASK_STATE_WORKING"}}})
        return super()._get_task(cuerpo, agente)

    def __call__(self, peticion):
        r = super().__call__(peticion)
        cuerpo = json.loads(peticion.content)
        if cuerpo.get("method") != "SendMessage" or r.status_code != 200 or "result" not in r.json():
            return r
        t = copy.deepcopy(r.json()["result"]["task"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": cuerpo["id"], "result": {"task": {
            "id": t["id"], "contextId": t["contextId"], "status": {"state": "TASK_STATE_SUBMITTED"}}}})


def _rapido(c, espera=420.0):
    reloj = Reloj()
    c.a2a._dormir, c.a2a._reloj, c.a2a._espera = reloj.dormir, reloj, espera
    return reloj


def _a2a(c) -> list[dict]:
    return [json.loads(x) for x in (c.cfg.trabajo / "procedencia" / "a2a.jsonl").read_text(encoding="utf-8").splitlines()]


def test_coordinador_recoge_la_respuesta_lenta_y_la_registra(tmp_path, monkeypatch):
    a2a = A2ALento(en_curso=23)
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _rapido(c)
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [])
    assert "EXPERTO: VÁLIDA" in r and "no bloqueante con 24 sondeo(s)" in r, r
    envio = [x for x in _a2a(c) if x["metodo"] == "SendMessage"][0]
    assert envio["modo"] == "no_bloqueante" and envio["sondeos"] == 24 and envio["latencia_s"] == 120.0
    doc = json.loads((c.cfg.trabajo / "procedencia" / "procedencia_a2a.json").read_text(encoding="utf-8"))
    assert doc["tareas"][0]["relectura"]["coincide"] is True and _estado(c)["intentos"]["T2"] == 0


def test_tarea_pendiente_por_espera_se_recoge_con_sigue_sin_reenviar(tmp_path, monkeypatch):
    a2a = A2ALento(en_curso=10_000)
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _rapido(c, espera=60)
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [])
    assert "FALLO A2A (preventa-experto-azure): tarea resp_falso0001 pendiente" in r, r
    est = _estado(c)
    assert est["intentos"]["T2"] == 1 and "se recoge por su task_id" in est["fallos"][-1]["hipotesis"]
    experto = lambda: [x for x in a2a.recibidos if x["agente"] == "preventa-experto-azure"]
    enviados = len(experto())
    a2a.en_curso = 3
    r = c.manejar("SIGUE", [])
    assert "quedó pendiente en un turno anterior: la recojo" in r and "EXPERTO: VÁLIDA" in r, r
    assert len(experto()) == enviados == 1               # no se reenvió el brief
    ultimo = [x for x in _a2a(c) if x["metodo"] == "SendMessage" and x["agente"] == "preventa-experto-azure"][-1]
    assert ultimo["recuperada"] is True and ultimo["task_id"] == "resp_falso0001" and ultimo["pendiente"] is False
    assert _estado(c)["intentos"]["T2"] == 0


def test_cancelacion_no_gasta_intento_y_sigue_recoge(tmp_path, monkeypatch):
    a2a = A2ALento(en_curso=10_000)
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _rapido(c)
    _hasta_insuficiente(c)
    antes = len(a2a.recibidos)

    def cancelado():
        return len(a2a.recibidos) > antes    # cancela cuando el brief ya se envió (durante la espera)
    r = c.manejar(ASUMIR, [], cancelado=cancelado)
    assert "PENDIENTE:" in r and "No registro fallo" in r, r
    assert _estado(c)["intentos"]["T2"] == 0
    a2a.en_curso = 0
    r = c.manejar("SIGUE", [])
    assert "la recojo por su task_id" in r and "EXPERTO: VÁLIDA" in r, r


def test_pendiente_de_otro_texto_no_se_recoge(tmp_path):
    from preventa_hosted import fases
    d = tmp_path / "procedencia"
    d.mkdir()
    reg = {"fase": "T2", "metodo": "SendMessage", "agente": "e", "task_id": "resp_1", "pendiente": True,
           "sha256_enviado": A.sha256("brief A")}
    (d / "a2a.jsonl").write_text(json.dumps(reg) + "\n", encoding="utf-8")
    assert fases.pendiente_previa(tmp_path, "e", "T2", A.sha256("brief A"))["task_id"] == "resp_1"
    assert fases.pendiente_previa(tmp_path, "e", "T2", A.sha256("brief B")) is None
    assert fases.pendiente_previa(tmp_path, "otro", "T2", A.sha256("brief A")) is None
    with open(d / "a2a.jsonl", "a", encoding="utf-8") as f:   # un envío posterior del mismo texto ya no está pendiente
        f.write(json.dumps({**reg, "pendiente": False}) + "\n")
    assert fases.pendiente_previa(tmp_path, "e", "T2", A.sha256("brief A")) is None


# ── Revisión (arreglos I1.7): espera estricta, cancelación tras dormir y tarea ajena ─────────────────────────────────────
def test_la_espera_no_se_pasa_del_tope():
    man, _ = _servidor(["TASK_STATE_WORKING"] * 1000)
    c, _ = _cliente(man, espera=12, sondeo=5)
    ll = c.enviar("x", "hola")
    assert ll.pendiente and ll.sondeos == 3 and ll.latencia_s == 12.0


def test_cancelar_mientras_duerme_no_hace_otro_get_task():
    man, vistos = _servidor(["TASK_STATE_WORKING"] * 10)
    c, reloj = _cliente(man)
    c.cancelado = lambda: reloj.t >= 10
    ll = c.enviar("x", "hola")
    assert ll.pendiente and "canceló" in ll.error and ll.sondeos == 1
    assert [v["method"] for v in vistos] == ["SendMessage", "GetTask"]


def test_tarea_ajena_deja_la_propia_pendiente():
    def manejador(req):
        c = json.loads(req.content)
        if c["method"] == "SendMessage":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"],
                                             "result": {"task": _tarea("resp_1", "TASK_STATE_WORKING")}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"],
                                         "result": _tarea("resp_OTRA", "TASK_STATE_COMPLETED", "{}")})
    c, _ = _cliente(manejador)
    ll = c.enviar("x", "hola")
    assert not ll.ok and ll.pendiente and ll.task_id == "resp_1" and "otra tarea" in ll.error


def test_el_get_task_de_sondeo_usa_un_tope_corto(monkeypatch):
    man, _ = _servidor(["TASK_STATE_WORKING"])
    c, _ = _cliente(man)
    topes = []
    original = c._rpc

    def espia(agente, metodo, params, ll, timeout=None):
        topes.append((metodo, timeout))
        return original(agente, metodo, params, ll, timeout)
    monkeypatch.setattr(c, "_rpc", espia)
    assert c.enviar("x", "hola").ok
    assert topes[0] == ("SendMessage", None) and all(m == "GetTask" and t == A.TOPE_SONDEO_S for m, t in topes[1:])
