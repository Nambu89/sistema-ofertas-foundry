"""Arnés del paso 0a: resultados, estados y guarda del cliente HTTP (sin red)."""
from __future__ import annotations

import json

import pytest

from lib.foundry import OperacionNoPermitida
from pruebas.paso0a import comun
from tests.conftest import jwt_falso


class TransporteAnotador:
    def __init__(self, estado=200, texto="{}"):
        self.llamadas = []
        self.estado, self.texto = estado, texto

    def peticion(self, metodo, url, **kw):
        self.llamadas.append({"metodo": metodo, "url": url, **kw})
        return comun.RespuestaHTTP(self.estado, self.texto, {}, 0.01, url)


def _cliente(cfg, transporte=None):
    pedidos = []

    def tokens(aud):
        pedidos.append(aud)
        return "token-de-prueba"
    t = transporte or TransporteAnotador()
    return comun.ClientePruebas(cfg, t, tokens), t, pedidos


# ------------------------------------------------------------------------------- resultados
def test_resultado_valido_y_redactado():
    jwt = jwt_falso()
    r = comun.construir_resultado("P1", "PASA", f"evidencia con Bearer {jwt}", "comando", "2026-10-18T00:00:00Z")
    assert set(r) == {"id", "estado", "evidencia", "comando", "fecha"}
    assert jwt not in r["evidencia"] and "[REDACTADO]" in r["evidencia"]


@pytest.mark.parametrize("estado", ["OK", "pasa", "", None, "EN_CURSO"])
def test_estado_no_valido_falla_en_alto(estado):
    with pytest.raises(comun.ErrorArnes):
        comun.construir_resultado("P1", estado, "x", "c", "f")


@pytest.mark.parametrize("ev,cmd", [("", "c"), ("   ", "c"), ("x", ""), (None, "c")])
def test_sin_evidencia_o_sin_comando_no_hay_resultado(ev, cmd):
    with pytest.raises(comun.ErrorArnes):
        comun.construir_resultado("P1", "PASA", ev, cmd, "f")


@pytest.mark.parametrize("id_", ["P", "X1", "P12", "P1A", "../P1"])
def test_id_no_valido(id_):
    with pytest.raises(comun.ErrorArnes):
        comun.construir_resultado(id_, "PASA", "x", "c", "f")


def test_codigos_de_salida():
    assert comun.codigo_salida("PASA") == 0 and comun.codigo_salida("NO_APLICA") == 0
    assert comun.codigo_salida("FALLA") == 1 and comun.codigo_salida("PENDIENTE_FERNANDO") == 3
    with pytest.raises(comun.ErrorArnes):
        comun.codigo_salida("OTRO")


@pytest.mark.parametrize("estados,esperado", [
    (["PASA", "PASA"], "PASA"), (["PASA", "PENDIENTE_FERNANDO"], "PENDIENTE_FERNANDO"),
    (["PENDIENTE_FERNANDO", "FALLA", "PASA"], "FALLA"), (["NO_APLICA"], "NO_APLICA"),
    (["NO_APLICA", "PASA"], "PASA")])
def test_combinar_estados(estados, esperado):
    assert comun.combinar_estados(estados) == esperado


def test_combinar_vacio_o_raro_falla():
    with pytest.raises(comun.ErrorArnes):
        comun.combinar_estados([])
    with pytest.raises(comun.ErrorArnes):
        comun.combinar_estados(["PASA", "RARO"])


def test_escritura_atomica_utf8_lf_y_redactada(tmp_path):
    jwt = jwt_falso()
    ruta = comun.escribir_json(tmp_path / "x" / "P1.json", {"texto": f"Authorization: Bearer {jwt}", "ñ": "sí"})
    datos = ruta.read_bytes()
    assert b"\r" not in datos and jwt.encode() not in datos
    assert json.loads(datos.decode("utf-8"))["ñ"] == "sí"
    assert not list(tmp_path.rglob("*.tmp"))


def test_recortar_avisa():
    assert "recortado" in comun.recortar("a" * 50, 10)
    assert comun.recortar("abc", 10) == "abc"


def test_texto_salida():
    r = {"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": "a"},
                                                                            {"type": "refusal"}]},
                    {"type": "message", "content": [{"type": "output_text", "text": "b"}]}]}
    assert comun.texto_salida(r) == "a\nb"
    assert comun.texto_salida(None) == ""


# ------------------------------------------------------------------------------- guarda HTTP
@pytest.mark.parametrize("metodo,ruta,kw", [
    ("POST", "agents/ofa-coordinador/versions", {}),
    ("POST", "agents/Agente-De-Otro-Proyecto/versions", {}),
    ("POST", "agents/otro-proyecto-prueba-hosted/endpoint/protocols/openai/responses", {}),
    ("POST", "agents/agente-de-otro-proyecto/endpoint/protocols/openai/responses", {}),
    ("GET", "agents/ofa-coordinador/endpoint/protocols/openai/responses/caresp_1", {}),
    ("POST", "agents", {"cabeceras": {"x-ms-agent-name": "ofa-coordinador"}}),
    ("POST", "agents", {"json_body": {"name": "otro-proyecto-x"}}),
    ("POST", "agents", {"cabeceras": {"x-ms-agent-name": "ofa-prueba-a"}, "json_body": {"name": "ofa-prueba-b"}}),
    ("POST", "agents", {}),
    ("DELETE", "agents/ofa-prueba-hosted", {}),
    ("PATCH", "agents/ofa-prueba-hosted", {}),
    ("POST", "connections/x", {}),
    ("GET", "agents/ofa-prueba-a/../../x", {}),
    ("POST", "agents/ofa-prueba-a\n/versions", {}),
    ("POST", "openai/v1/responses", {}),
    ("POST", "openai/v1/responses", {"json_body": {"agent_reference": {"name": "Agente-De-Otro-Proyecto"}}}),
    ("POST", "openai/v1/responses", {"json_body": {"agent_reference": {"name": "otro-proyecto-x"}}}),
    ("POST", "openai/v1/responses", {"json_body": {"agent": {"name": "ofa-coordinador"}}}),
    ("POST", "openai/v1/responses", {"json_body": {"agent_reference": {"name": "ofa-prueba-a"},
                                                    "agent": {"name": "Agente-De-Otro-Proyecto"}}}),
    ("POST", "openai/v1/responses", {"json_body": {"agent_reference": {"name": 7}}}),
])
def test_guarda_rechaza_antes_del_token(cfg, metodo, ruta, kw):
    cli, t, pedidos = _cliente(cfg)
    with pytest.raises(OperacionNoPermitida):
        cli.datos(metodo, ruta, **kw)
    assert t.llamadas == [] and pedidos == []


@pytest.mark.parametrize("metodo,ruta,kw", [
    ("GET", "agents/ofa-prueba-hosted", {}),
    ("GET", "agents/ofa-prueba-hosted/versions/3", {}),
    ("POST", "agents", {"cabeceras": {"x-ms-agent-name": "ofa-prueba-hosted"}}),
    ("POST", "agents", {"json_body": {"name": "ofa-prueba-herramientas"}}),
    ("POST", "agents/ofa-prueba-hosted/versions", {}),
    ("POST", "agents/ofa-prueba-hosted/endpoint/protocols/openai/responses", {"params": {"api-version": "v1"}}),
    ("GET", "agents/ofa-prueba-hosted/endpoint/protocols/openai/responses/caresp_abc", {}),
    ("POST", "openai/v1/responses", {"json_body": {"agent_reference": {"type": "agent_reference",
                                                                       "name": "ofa-prueba-herramientas"}}}),
    ("GET", "openai/v1/responses/resp_abc", {}),
])
def test_guarda_admite_lo_del_arnes(cfg, metodo, ruta, kw):
    cli, t, pedidos = _cliente(cfg)
    cli.datos(metodo, ruta, **kw)
    llamada = t.llamadas[0]
    assert llamada["url"].startswith("https://mi-recurso-foundry.services.ai.azure.com/api/projects/mi-proyecto-foundry/")
    assert llamada["cabeceras"]["Authorization"] == "Bearer token-de-prueba"
    assert llamada["timeout"] > 0 and pedidos == ["https://ai.azure.com"]
    assert "token-de-prueba" not in " ".join(cli.llamadas)


def test_endpoint_alterado_no_recibe_token(cfg):
    cfg["endpoints"]["proyecto"] = "https://evil.example.com/api/projects/x"
    cli, t, pedidos = _cliente(cfg)
    with pytest.raises(OperacionNoPermitida):
        cli.datos("GET", "agents/ofa-prueba-hosted")
    assert pedidos == []


def test_arm_solo_dentro_del_recurso(cfg):
    cli, t, pedidos = _cliente(cfg)
    cli.arm_get("/deployments", "2025-06-01")
    assert t.llamadas[0]["url"].endswith("/accounts/mi-recurso-foundry/deployments")
    assert t.llamadas[0]["metodo"] == "GET" and pedidos == ["https://management.azure.com"]
    for malo in ("/../otra", "/x?y=1", "deployments", "/a b"):
        with pytest.raises(OperacionNoPermitida):
            cli.arm_get(malo, "2025-06-01")


def test_next_link_fuera_del_recurso(cfg):
    cli, t, _ = _cliente(cfg)
    with pytest.raises(OperacionNoPermitida):
        cli.arm_get_siguiente("https://management.azure.com/subscriptions/otra/providers/x?page=2")
    with pytest.raises(OperacionNoPermitida):
        cli.arm_get_siguiente("https://evil.example.com" + cli.base_arm.split("management.azure.com")[1] + "/models")
    cli.arm_get_siguiente(cli.base_arm + "/models?api-version=2025-06-01&$skipToken=abc")
    assert len(t.llamadas) == 1


def test_decision_solo_hosts_del_recurso(cfg):
    cli, t, pedidos = _cliente(cfg)
    with pytest.raises(OperacionNoPermitida):
        cli.decision("https://evil.example.com", {})
    cli.decision(cli.hosts_decision()[1], {"model": "Decision-1"})
    assert t.llamadas[0]["url"] == "https://mi-recurso-foundry.cognitiveservices.azure.com/providers/microsoft/v1/systemone"
    assert pedidos == [comun.AUD_COGNITIVE]


def test_contexto_progreso_y_presupuesto(cfg, tmp_path):
    reloj = {"t": 100.0}
    cli, _, _ = _cliente(cfg)
    ctx = comun.Contexto(cfg=cfg, cliente=cli, dir_resultados=tmp_path, dir_progreso=tmp_path,
                         monotono=lambda: reloj["t"], presupuesto_s=50)
    reloj["t"] += 20
    assert ctx.restante() == 30
    ctx.guardar_progreso("P4", {"paso": "activo"})
    assert ctx.leer_progreso("P4") == {"paso": "activo"}
    ctx.borrar_progreso("P4")
    assert ctx.leer_progreso("P4") == {}
    assert ctx.marcar("x") == "x"
    ctx.simulado = True
    assert ctx.marcar(ctx.marcar("x")).count("SIMULADO") == 1
