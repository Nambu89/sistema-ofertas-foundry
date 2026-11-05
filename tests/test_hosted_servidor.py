"""Hosted agent: el servidor real de azure-ai-agentserver-responses 2.2.0 (ASGI en proceso) con el núcleo real.

Comprueba la forma real del protocolo Responses: el turno llega como POST /responses con un input_file
(file_data en data URL) y la respuesta es un `response` con el texto del coordinador.
Solo corre con hosted/.venv (donde está el paquete fijado); en el .venv del repositorio se omite.
"""
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("azure.ai.agentserver.responses")

from tests.test_hosted_falsos import NUCLEO, ALTA, PROYECTO, RAIZ, adjunto_transcripcion, coordinador, httpx  # noqa: E402


def _post(app, cuerpo: dict) -> httpx.Response:
    async def _ir():
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://agente") as c:
            return await c.post("/responses", json=cuerpo, timeout=120)
    return asyncio.run(_ir())


def _texto(resp: dict) -> str:
    return "".join(c.get("text", "") for it in resp.get("output") or [] if it.get("type") == "message"
                   for c in it.get("content") or [])


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", PROYECTO)
    monkeypatch.setenv("PREVENTA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PREVENTA_APP_NUCLEO", str(NUCLEO))
    monkeypatch.setenv("AGENTSERVER_STATE_ROOT", str(tmp_path / "agentserver"))
    import main
    c, a2a, modelo = coordinador(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "crear_coordinador", lambda cfg: c)
    return main.app, c, a2a, modelo


def test_turno_por_el_protocolo_responses(servidor):
    app, c, a2a, modelo = servidor
    adj = adjunto_transcripcion()
    cuerpo = {"model": "preventa", "input": [{"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": ALTA},
        {"type": "input_file", "filename": adj["filename"], "file_data": adj["file_data"]}]}]}
    r = _post(app, cuerpo)
    assert r.status_code == 200, r.text
    resp = r.json()
    assert resp["status"] == "completed", json.dumps(resp)[:800]
    texto = _texto(resp)
    assert "Adjuntos guardados en la sesión: transcripcion_sintetica_I1.txt" in texto, texto
    assert "ALTA: OK OF-KELVARA-001-A" in texto and "SIGUIENTE PASO:" in texto, texto
    assert (c.cfg.datos / "transcripcion_sintetica_I1.txt").read_bytes() == (
        RAIZ / "datos_prueba" / "transcripcion_sintetica_I1.txt").read_bytes()


def test_config_invalida_se_dice(servidor, monkeypatch):
    app = servidor[0]
    monkeypatch.setenv("PREVENTA_A2A_TIMEOUT_S", "300")
    import main
    monkeypatch.setattr(main, "crear_coordinador", lambda cfg: pytest.fail("no debe llegar al coordinador"))
    r = _post(app, {"model": "preventa", "input": "ESTADO"})
    assert r.status_code == 200
    assert "Configuración inválida del agente: PREVENTA_A2A_TIMEOUT_S=300.0 fuera de" in _texto(r.json())


def test_readiness(servidor):
    async def _ir():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=servidor[0]), base_url="http://agente") as c:
            return await c.get("/readiness")
    assert asyncio.run(_ir()).status_code == 200
