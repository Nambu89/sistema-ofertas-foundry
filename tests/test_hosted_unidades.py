"""Hosted agent: unidades deterministas (intérprete de mensajes, cliente A2A, adjuntos, configuración)."""
from __future__ import annotations

import base64
import json

import pytest

from tests.test_hosted_falsos import NUCLEO, ALTA, PROYECTO, RAIZ, httpx

from preventa_hosted import a2a as A  # noqa: E402
from preventa_hosted import adjuntos, config, mensajes  # noqa: E402


def test_alta_del_e2e_se_interpreta_entera():
    m = mensajes.interpretar(ALTA)
    assert m.alta.cliente == "Kelvara Ensayos Industriales, S.A."
    assert (m.alta.codigo_cliente, m.alta.seqof) == ("KELVARA", "001")
    assert m.alta.titulo == "Asistente de consulta técnica con IA sobre informes de ensayo"
    assert m.alta.sensibles == ["Kelvara Ensayos Industriales", "Kelvara", "Marta Olmedo", "Iker Salaverri",
                                "Nuria Castells", "Zaragoza", "Tarragona"]
    assert m.nda_confirmado and not m.alta.faltan()


def test_ordenes_literales():
    texto = ("ASUMIR: volumetria = 150 técnicos, unos 20.000 documentos\n"
             "DECISION | Responsable de preventa | DEVUELTA | 2026-10-08 | abc | El anexo no valora el modelo\n"
             "CONFIRMO: NDA\nadelante")
    m = mensajes.interpretar(texto)
    assert m.asumir == [("volumetria", "150 técnicos, unos 20.000 documentos")]
    assert m.decisiones == ["DECISION | Responsable de preventa | DEVUELTA | 2026-10-08 | abc | El anexo no valora el modelo"]
    assert m.nda_confirmado and m.ordenes == ["SIGUE"] and m.alta is None


@pytest.mark.parametrize("texto", ["sigue con lo tuyo", "Creo que el NDA lo permite", "asumir: x = y", "DECISIÓN | a"])
def test_lo_que_no_casa_no_es_orden(texto):
    m = mensajes.interpretar(texto)
    assert m.vacio, m


def test_transcripcion_pegada_y_aclaracion():
    m = mensajes.interpretar("- Cliente: X S.A.\nTRANSCRIPCIÓN:\nMarta: hola a todos\n")
    assert m.transcripcion_pegada == "Marta: hola a todos\n" and m.alta.cliente == "X S.A."
    assert mensajes.interpretar("ACLARACIÓN: los documentos están en SharePoint").aclaracion == \
        "los documentos están en SharePoint"


def _cliente(manejador, timeout=5):
    return A.ClienteA2A(lambda a: f"{PROYECTO}/agents/{a}/endpoint/protocols/a2a", lambda: "t", timeout,
                        httpx.MockTransport(manejador))


def test_a2a_send_message_forma_real_y_procedencia():
    vistos = []

    def manejador(req):
        vistos.append(json.loads(req.content))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": vistos[-1]["id"], "result": {"task": {
            "id": "resp_1", "contextId": "ctxt_1", "status": {"state": "TASK_STATE_COMPLETED"},
            "artifacts": [{"parts": [{"text": "{\"a\":"}, {"text": "1}"}]}]}}})
    ll = _cliente(manejador).enviar("preventa-experto-azure", "texto  exacto\n con espacios ")
    assert vistos[0]["method"] == "SendMessage"
    assert vistos[0]["params"]["message"]["parts"] == [{"text": "texto  exacto\n con espacios "}]
    assert vistos[0]["params"]["message"]["role"] == "ROLE_USER"
    assert ll.ok and ll.texto == '{"a":1}' and (ll.task_id, ll.context_id) == ("resp_1", "ctxt_1")
    assert ll.sha256_enviado == A.sha256("texto  exacto\n con espacios ") and "texto" not in ll.registro()


def test_a2a_get_task_y_tarea_fallida():
    def manejador(req):
        c = json.loads(req.content)
        assert c["method"] == "GetTask" and c["params"]["id"] == "resp_9"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": c["id"], "result": {
            "id": "resp_9", "contextId": "ctxt_9", "status": {"state": "TASK_STATE_FAILED", "message": {
                "parts": [{"text": "el MCP de Learn no respondió"}]}}}})
    ll = _cliente(manejador).tarea("preventa-verificador", "resp_9")
    assert not ll.ok and "TASK_STATE_FAILED" in ll.error and "el MCP de Learn no respondió" in ll.error


def test_a2a_token_que_falla_se_dice():
    c = A.ClienteA2A(lambda a: "https://x/a2a", lambda: (_ for _ in ()).throw(RuntimeError("sin identidad")), 5,
                     httpx.MockTransport(lambda r: httpx.Response(200)))
    ll = c.enviar("x", "hola")
    assert ll.error == "RuntimeError: sin identidad" and not ll.ok


def test_adjuntos_nombre_seguro_y_rechazos(tmp_path):
    with pytest.raises(adjuntos.ErrorAdjunto):
        adjuntos.nombre_seguro("../../etc/passwd")
    assert adjuntos.nombre_seguro("C:\\x\\transcripcion.txt") == "transcripcion.txt"
    with pytest.raises(adjuntos.ErrorAdjunto, match="URL"):
        adjuntos.guardar([{"file_url": "https://evil", "filename": "a.txt"}], tmp_path, PROYECTO, lambda: "t")
    b64 = base64.b64encode(b"uno").decode()
    adjuntos.guardar([{"filename": "a.txt", "file_data": b64}], tmp_path, PROYECTO, lambda: "t")
    with pytest.raises(adjuntos.ErrorAdjunto, match="distinto"):
        adjuntos.guardar([{"filename": "a.txt", "file_data": base64.b64encode(b"dos").decode()}], tmp_path,
                         PROYECTO, lambda: "t")


def test_adjunto_por_file_id(tmp_path):
    def manejador(req):
        if req.url.path.endswith("/content"):
            return httpx.Response(200, content=b"WEBVTT\n")
        return httpx.Response(200, json={"id": "assistant-abc1", "filename": "reunion.vtt"})
    n = adjuntos.guardar([{"file_id": "assistant-abc1"}], tmp_path, PROYECTO, lambda: "t", httpx.MockTransport(manejador))
    assert n == ["reunion.vtt"] and (tmp_path / "reunion.vtt").read_bytes() == b"WEBVTT\n"


@pytest.mark.parametrize("env, motivo", [
    ({}, "FOUNDRY_PROJECT_ENDPOINT"),
    ({"FOUNDRY_PROJECT_ENDPOINT": PROYECTO, "PREVENTA_A2A_TIMEOUT_S": "120"}, "fuera de"),
    ({"FOUNDRY_PROJECT_ENDPOINT": PROYECTO, "PREVENTA_A2A_TIMEOUT_S": "rápido"}, "no es un número"),
    ({"FOUNDRY_PROJECT_ENDPOINT": PROYECTO, "PREVENTA_APP_NUCLEO": "C:/no/existe"}, "No está el núcleo"),
])
def test_config_falla_en_alto(env, motivo):
    with pytest.raises(config.ErrorConfig, match=motivo):
        config.cargar({"PREVENTA_APP_NUCLEO": str(NUCLEO), **env})


def test_config_valores_por_defecto(tmp_path):
    c = config.cargar({"FOUNDRY_PROJECT_ENDPOINT": PROYECTO + "/", "PREVENTA_HOME": str(tmp_path),
                       "PREVENTA_APP_NUCLEO": str(NUCLEO), "PREVENTA_MODELO": "   "})
    assert (c.modelo, c.experto, c.verificador, c.timeout_a2a_s) == ("gpt-6-luna", "preventa-experto-azure",
                                                                    "preventa-verificador", 110.0)
    assert c.url_a2a("x") == PROYECTO + "/agents/x/endpoint/protocols/a2a" and c.trabajo == tmp_path / "preventa" / "trabajo"


def test_revision_adjuntos_grandes_y_demasiados(tmp_path, monkeypatch):
    monkeypatch.setattr(adjuntos, "MAX_BYTES", 10)
    with pytest.raises(adjuntos.ErrorAdjunto, match="máximo"):
        adjuntos.guardar([{"filename": "a.txt", "file_data": "A" * 400}], tmp_path, PROYECTO, lambda: "t")
    with pytest.raises(adjuntos.ErrorAdjunto, match="adjuntos en un turno"):
        adjuntos.guardar([{"filename": f"{i}.txt", "file_data": "QQ=="} for i in range(5)], tmp_path, PROYECTO,
                         lambda: "t")


def test_revision_proyecto_de_otro_host_se_rechaza():
    with pytest.raises(config.ErrorConfig):
        config.cargar({"FOUNDRY_PROJECT_ENDPOINT": "https://atacante.example.com/api/projects/x",
                       "PREVENTA_APP_NUCLEO": str(NUCLEO)})


def test_revision_despliegue_exige_sha_externo(tmp_path, monkeypatch):
    import datetime as dt
    import desplegar_hosted
    import empaquetar
    from tests.test_hosted_i17_r import CATALOGO, escribir, instantanea_sintetica
    # I1.7 (R): empaquetar.py exige la instantánea de precios; aquí se prueba el SHA externo, no los precios
    a, b = tmp_path / "inst_datos.json", tmp_path / "inst_cat.json"
    escribir(instantanea_sintetica(CATALOGO, dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)), a, b)
    monkeypatch.setattr(empaquetar, "CANONICOS", {**empaquetar.CANONICOS, "precios_instantanea.json": (a, None)})
    monkeypatch.setattr(empaquetar, "INSTANTANEA_CATALOGO", b)
    empaquetar.construir(tmp_path / "a.zip")
    with pytest.raises(SystemExit, match="no coincide"):
        desplegar_hosted.main(["--zip", str(tmp_path / "a.zip"), "--confirmar", "--sha256", "0" * 64])


def test_pista_de_permiso_solo_con_agent_not_found():
    real = {"code": -32099, "message": "Agent 'preventa-experto-azure' not found.",
            "data": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "AGENT_NOT_FOUND"}]}
    pista = A.pista_permiso(real)
    assert pista.startswith(" · PISTA (hipótesis):") and "Foundry Agent Consumer" in pista
    assert A.pista_permiso({"code": -32603, "message": "Internal"}) == ""
    assert A.pista_permiso("texto") == "" and A.pista_permiso({"data": "x"}) == ""
