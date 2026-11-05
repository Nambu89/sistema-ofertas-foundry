"""Hosted agent (opción B): el manejador del turno con el núcleo REAL, un A2A falso y un modelo falso.

Comprueba que el CÓDIGO ejecuta la máquina de estados, que el brief y el consolidado llegan por A2A
EXACTAMENTE como los generó el núcleo, que se guarda la procedencia por llamada y que un fallo A2A
queda registrado con su motivo (sin 424 opaco).
"""
from __future__ import annotations

import datetime
import json

import pytest

from tests.test_hosted_falsos import ALTA, A2AFalso, adjunto_transcripcion, coordinador, httpx, token_prueba

# La decisión no puede ser anterior a la fecha de elaboración (hoy): una fecha fija caduca al día siguiente.
_HOY = datetime.date.today().isoformat()

ASUMIR = ("ASUMIR: volumetria = 150 técnicos usuarios y unos 20.000 documentos (informes, procedimientos y normas)\n"
          "ASUMIR: identidad_acl_origen = Documentos en SharePoint Online del tenant del cliente, con permisos por "
          "grupos de Entra ID que se respetan en las respuestas")


def _estado(c) -> dict:
    return json.loads((c.cfg.trabajo / "estado.json").read_text(encoding="utf-8"))


def _hasta_insuficiente(c):
    r = c.manejar(ALTA, [adjunto_transcripcion()])
    assert "ALTA: OK OF-KELVARA-001-A" in r, r
    assert "SUFICIENCIA: INCOMPLETA" in r and "volumetria" in r, r
    assert _estado(c)["estado"] == "INFORMACION_INSUFICIENTE"
    return r


def _sigue_hasta(c, objetivo: str, maximo: int = 12) -> str:
    """SIGUE hasta llegar a `objetivo` (con lotes del verificador hacen falta varios turnos)."""
    todo = ""
    for _ in range(maximo):
        if _estado(c)["estado"] == objetivo:
            return todo
        r = c.manejar("SIGUE", [])
        todo += r
        assert "FALLO" not in r, r
    raise AssertionError(f"no se llegó a {objetivo}: {_estado(c)['estado']} · {todo[-3000:]}")


def _textos_verificables(est: dict) -> set[str]:
    cons = est["carga"]["consolidado"]
    return {cons["texto"]} | {x["texto"] for x in cons.get("lotes") or []}


def test_recorrido_completo_hasta_paquete(tmp_path, monkeypatch):
    c, a2a, modelo = coordinador(tmp_path, monkeypatch)
    _hasta_insuficiente(c)
    assert len(modelo.peticiones) == 1 and modelo.peticiones[0]["model"] == "gpt-6-luna"
    assert modelo.peticiones[0]["text"]["format"]["strict"] is True
    r = c.manejar(ASUMIR, [])
    assert "EXPERTO: VÁLIDA" in r, r
    est = _estado(c)
    enviado = a2a.recibidos[0]["cuerpo"]["params"]["message"]["parts"][0]["text"]
    assert enviado == est["carga"]["briefs"][-1]["texto"]          # EXACTAMENTE el brief del código
    assert a2a.recibidos[0]["agente"] == "preventa-experto-azure"
    assert a2a.recibidos[0]["cabeceras"]["a2a-version"] == "1.0"
    assert a2a.recibidos[0]["cabeceras"]["authorization"] == f"Bearer {token_prueba()}"   # VPROT-3 (I1.9)
    todo = r + _sigue_hasta(c, "LISTA_PARA_REVISION")
    est = _estado(c)
    verif = [x["cuerpo"]["params"]["message"]["parts"][0]["text"] for x in a2a.recibidos[1:]]
    assert verif and all(t in _textos_verificables(est) for t in verif)   # cada lote, EXACTO
    assert len(verif) == len(set(verif))                                   # ninguno dos veces
    assert "VERIFICADA" in todo and "ESTIMACIÓN: precio cerrado" in todo, todo[-3000:]
    assert "PAQUETE: OF-KELVARA-001-A-Paquete.zip" in todo and "descargar_sesion.py descargar" in todo
    assert (c.cfg.trabajo / "salida" / "OF-KELVARA-001-A-Paquete.zip").is_file()
    todas = [json.loads(l) for l in (c.cfg.trabajo / "procedencia" / "a2a.jsonl").read_text(encoding="utf-8").splitlines()]
    proc = [p for p in todas if p["metodo"] == "SendMessage"]
    assert [p["fase"] for p in proc] == ["T2"] + ["T3"] * len(verif)
    assert all(p["task_id"].startswith("resp_falso") and p["context_id"].startswith("ctxt_falso") for p in proc)
    assert "texto" not in proc[0] and len(proc[0]["sha256_enviado"]) == 64
    # I1.4 (decisión del comercial): cada tarea se relee con GetTask y su texto queda en procedencia_a2a.json
    relect = [p for p in todas if p["metodo"] == "GetTask"]
    assert [p["fase"] for p in relect] == ["T2-relectura"] + ["T3-relectura"] * len(verif)
    assert [p["task_id"] for p in relect] == [p["task_id"] for p in proc] and len(a2a.relecturas) == len(proc)
    doc = json.loads((c.cfg.trabajo / "procedencia" / "procedencia_a2a.json").read_text(encoding="utf-8"))
    assert [t["task_id"] for t in doc["tareas"]] == [p["task_id"] for p in proc]
    assert all(t["relectura"]["coincide"] is True and t["sha256_recibido"] == p["sha256_recibido"]
               for t, p in zip(doc["tareas"], proc))
    cons = est["carga"]["consolidado"]
    lotes = [x["lote_id"] for x in cons.get("lotes") or []] or [cons["consolidado_id"]]
    assert [t["objetivo_id"] for t in doc["tareas"]] == [est["carga"]["briefs"][-1]["brief_id"]] + lotes


def test_alta_incompleta_no_ejecuta_nada(tmp_path, monkeypatch):
    c, a2a, modelo = coordinador(tmp_path, monkeypatch)
    r = c.manejar(ALTA.replace("Confirmo que el NDA", "Creo que el NDA"), [adjunto_transcripcion()])
    assert "me falta" in r and "NDA" in r, r
    assert not (c.cfg.trabajo / "estado.json").exists() and not modelo.peticiones


def test_mensaje_sin_orden_no_avanza(tmp_path, monkeypatch):
    c, a2a, _ = coordinador(tmp_path, monkeypatch)
    _hasta_insuficiente(c)
    r = c.manejar("hola, ¿cómo va?", [])
    assert "No he reconocido ninguna orden" in r and not a2a.recibidos


@pytest.mark.parametrize("fallo, motivo", [
    (lambda: httpx.Response(424, json={"error": {"code": "tool_server_error", "message": "detalle real"}}), "HTTP 424"),
    (lambda: httpx.ReadTimeout("lento"), "timeout A2A"),
    (lambda: httpx.Response(200, json={"jsonrpc": "2.0", "id": "x", "error": {"code": -32603, "message": "Internal"}}),
     "JSON-RPC"),
    # Forma real (integración I1.1, hosted agent sin el rol): AGENT_NOT_FOUND con HTTP 200, más la pista de permisos.
    (lambda: httpx.Response(200, json={"jsonrpc": "2.0", "id": "x", "error": {
        "code": -32099, "message": "Agent 'preventa-experto-azure' not found.",
        "data": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "AGENT_NOT_FOUND"}]}}),
     "PISTA (hipótesis)"),
])
def test_fallo_a2a_queda_registrado_con_su_motivo(tmp_path, monkeypatch, fallo, motivo):
    a2a = A2AFalso()
    a2a.fallos.append(fallo())
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [])
    assert f"FALLO A2A (preventa-experto-azure): " in r and motivo in r, r
    est = _estado(c)
    assert est["intentos"]["T2"] == 1 and motivo in est["fallos"][-1]["error"]
    proc = (c.cfg.trabajo / "procedencia" / "a2a.jsonl").read_text(encoding="utf-8")
    assert motivo in proc or json.dumps(motivo, ensure_ascii=False)[1:-1] in proc
    r = c.manejar("SIGUE", [])                                  # se repite la fase y ahora va bien
    assert "EXPERTO: VÁLIDA" in r, r


def test_modelo_caido_registra_fallo_t1(tmp_path, monkeypatch):
    c, _, modelo = coordinador(tmp_path, monkeypatch)
    modelo.status = 503
    r = c.manejar(ALTA, [adjunto_transcripcion()])
    assert "El modelo no devolvió los requisitos: HTTP 503" in r, r
    assert _estado(c)["intentos"]["T1"] == 1 and _estado(c)["estado"] == "BORRADOR"


def test_decision_y_devuelta(tmp_path, monkeypatch):
    c, a2a, _ = coordinador(tmp_path, monkeypatch, PREVENTA_MAX_A2A_POR_TURNO="8")
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [])
    assert "LISTA_PARA_REVISION" in r, r
    h = _estado(c)["hash_contenido"]
    r = c.manejar(f"DECISION | Responsable comercial | ENVIADA_REVISION | {_HOY} | {h} | verificar_paquete rc=0", [])
    assert "EN_REVISION_PREVENTA" in r, r
    r = c.manejar(f"DECISION | Responsable de preventa | DEVUELTA | {_HOY} | {h} | Falta el consumo de tokens del modelo", [])
    assert "DEVUELTA_CON_COMENTARIOS" in r and "SIGUE para repetir" in r, r
    n = len(a2a.recibidos)
    r = c.manejar("SIGUE", [])
    assert "BRF-OF-KELVARA-001-B-AZ-R1" in r and len(a2a.recibidos) > n, r
    assert a2a.recibidos[n]["cuerpo"]["params"]["message"]["parts"][0]["text"] == _estado(c)["carga"]["briefs"][-1]["texto"]


def test_alta_repetida_y_decision_fallida_paran(tmp_path, monkeypatch):
    c, a2a, modelo = coordinador(tmp_path, monkeypatch)
    _hasta_insuficiente(c)
    r = c.manejar(ALTA, [])
    assert "Ya hay una solicitud en esta sesión" in r and len(modelo.peticiones) == 1, r
    r = c.manejar("DECISION | Responsable comercial | ENVIADA_REVISION | 2026-10-08 | 0000 | x\n" + ASUMIR, [])
    assert "$ decision → rc" in r and "$ asumir" not in r, r
    assert _estado(c)["estado"] == "INFORMACION_INSUFICIENTE" and not a2a.recibidos


def test_cancelado_para_antes_del_siguiente_paso(tmp_path, monkeypatch):
    c, a2a, modelo = coordinador(tmp_path, monkeypatch)
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [], cancelado=lambda: True)
    assert "Turno cancelado por el cliente" in r and not a2a.recibidos, r


def test_revision2_alta_parcial_y_cancelacion_previa(tmp_path, monkeypatch):
    c, a2a, modelo = coordinador(tmp_path, monkeypatch)
    _hasta_insuficiente(c)
    r = c.manejar("- Título: otra cosa" + chr(10) + ASUMIR, [])
    assert "Ya hay una solicitud" in r and "$ asumir" not in r, r
    r = c.manejar(ASUMIR, [], cancelado=lambda: True)
    assert r.startswith("Turno cancelado por el cliente antes de empezar"), r
    assert _estado(c)["estado"] == "INFORMACION_INSUFICIENTE" and not a2a.recibidos
