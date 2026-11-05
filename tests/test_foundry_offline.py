"""Pruebas sin red de lib/foundry.py y lib/azure_auth.py (sesión HTTP y az simulados)."""
import subprocess
import types

import pytest

from lib import azure_auth, foundry


class Resp:
    def __init__(self, estado, cuerpo=b"{}", cab=None):
        self.status_code, self.content, self.headers = estado, cuerpo, cab or {}
        self.text = cuerpo.decode()

    def json(self):
        import json
        return json.loads(self.content)


class Sesion:
    """Devuelve las respuestas en orden y guarda las peticiones (sin cabecera de auth)."""
    def __init__(self, respuestas):
        self.respuestas, self.peticiones = list(respuestas), []

    def request(self, metodo, url, **kw):
        self.peticiones.append((metodo, url, kw.get("params"), kw.get("json")))
        return self.respuestas.pop(0)


@pytest.fixture()
def cli(monkeypatch):
    monkeypatch.setattr(azure_auth, "obtener_token", lambda *a, **k: "tok-falso")
    monkeypatch.setattr(foundry.time, "sleep", lambda s: None)
    return foundry.ClienteFoundry()


def test_protecciones_de_escritura(cli):
    for nombre in ("agente-ajeno-ejemplo", "agente-ajeno-2", "otro-agente"):
        with pytest.raises(foundry.OperacionNoPermitida):
            cli.crear_version_agente(nombre, {"kind": "prompt"})
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.borrar_agente_prueba("preventa-coordinador")
    # V-M2 (I1): la conexión AppInsights ya no está protegida por nombre (apunta al recurso nuevo);
    # sigue sin poder pisarse una conexión existente sin sobrescribir=True.
    assert "conexion_appinsights_rota" not in cli.cfg["protegidos"]
    cli.obtener_conexion = lambda nombre: {"name": nombre}
    with pytest.raises(foundry.OperacionNoPermitida, match="ya existe"):
        cli.put_conexion("a2a-experto-azure", {})
    # la conexión AppInsights vigente sigue sin poder tocarse, ni con sobrescribir=True (Revisión, integración I1)
    with pytest.raises(foundry.OperacionNoPermitida, match="protegida"):
        cli.put_conexion("appi-preventa-ejemplo", {}, sobrescribir=True)
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.asignar_rol(cli.id_arm_proyecto, "a97b65f3-24c7-4388-baec-2e87135dc908", "x")


def test_reintenta_429_y_anota(cli):
    cli._sesion = Sesion([Resp(429, b"lento", {"Retry-After": "1"}), Resp(200, b'{"ok": 1}')])
    assert cli.responder("preventa-coordinador", "hola") == {"ok": 1}
    assert len(cli.registro) == 1 and cli.registro[0].estado == 429
    metodo, url, params, cuerpo = cli._sesion.peticiones[0]
    assert url.endswith("/openai/v1/responses") and params is None
    assert cuerpo["agent_reference"] == {"type": "agent_reference", "name": "preventa-coordinador"}


def test_post_no_reintenta_5xx(cli):
    cli._sesion = Sesion([Resp(500, b"fallo")])
    with pytest.raises(foundry.ErrorFoundry) as e:
        cli.crear_version_agente("preventa-experto-azure", {"kind": "prompt"})
    assert e.value.estado == 500 and cli.registro == []


def test_get_reintenta_5xx_hasta_tres(cli):
    cli._sesion = Sesion([Resp(503), Resp(502), Resp(500, b"sigue")])
    with pytest.raises(foundry.ErrorFoundry):
        cli.obtener_agente("preventa-coordinador")
    assert len(cli.registro) == 2
    assert cli._sesion.peticiones[0][2] == {"api-version": "v1"}


def test_no_reintenta_4xx(cli):
    cli._sesion = Sesion([Resp(403, b"prohibido")])
    with pytest.raises(foundry.ErrorFoundry) as e:
        cli.obtener_agente("preventa-coordinador")
    assert e.value.estado == 403 and cli.registro == []


def test_listar_pagina_con_cursor(cli):
    cli._sesion = Sesion([Resp(200, b'{"data":[{"id":"a"}],"has_more":true,"last_id":"a"}'),
                          Resp(200, b'{"data":[{"id":"b"}],"has_more":false}')])
    assert [x["id"] for x in cli.listar("agents")] == ["a", "b"]
    assert cli._sesion.peticiones[1][2] == {"api-version": "v1", "after": "a"}


def test_propiedades_remote_a2a_y_citas(cli):
    p = cli.propiedades_remote_a2a("preventa-experto-azure")
    assert p["category"] == "RemoteA2A" and p["authType"] == "AgenticIdentityToken"
    assert p["target"].endswith("/agents/preventa-experto-azure/endpoint/protocols/a2a")
    r = {"output": [{"type": "message", "content": [{"text": "hecho", "annotations": [
        {"type": "container_file_citation", "container_id": "cntr_1", "file_id": "cfile_1",
         "filename": "x.xlsx"}]}]}]}
    assert cli.citas_de_ficheros(r) == [{"container_id": "cntr_1", "file_id": "cfile_1",
                                         "filename": "x.xlsx"}]
    assert cli.texto_de(r) == "hecho"


def test_auth_mfa_da_error_claro(monkeypatch):
    azure_auth.olvidar_tokens()
    monkeypatch.setattr(azure_auth, "_ejecutable_az", lambda: "az")
    falso = types.SimpleNamespace(returncode=1, stdout="",
                                  stderr="AADSTS50076: Due to a configuration change...")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: falso)
    with pytest.raises(azure_auth.ErrorAutenticacion, match="az login"):
        azure_auth.obtener_token(forzar=True)


def test_auth_cachea_en_memoria(monkeypatch):
    azure_auth.olvidar_tokens()
    llamadas = []
    monkeypatch.setattr(azure_auth, "_ejecutable_az", lambda: "az")

    def run(*a, **k):
        llamadas.append(1)
        return types.SimpleNamespace(returncode=0, stderr="",
                                     stdout='{"accessToken": "t", "expires_on": 9999999999}')
    monkeypatch.setattr(subprocess, "run", run)
    assert azure_auth.token_datos() == "t" and azure_auth.token_datos() == "t"
    assert len(llamadas) == 1
    azure_auth.olvidar_tokens()


def test_post_reintenta_si_no_se_envio(cli):
    import requests

    class SesionDNS(Sesion):
        def request(self, metodo, url, **kw):
            if not self.peticiones:
                self.peticiones.append("dns")
                raise requests.ConnectionError("NameResolutionError: getaddrinfo failed")
            return super().request(metodo, url, **kw)
    cli._sesion = SesionDNS([Resp(200, b'{"id": "r1"}')])
    assert cli.responder("preventa-coordinador", "hola") == {"id": "r1"}
    assert len(cli.registro) == 1 and cli.registro[0].estado is None


def test_post_no_reintenta_corte_a_mitad(cli):
    import requests

    class SesionCorte(Sesion):
        def request(self, metodo, url, **kw):
            raise requests.ConnectionError("Connection aborted: RemoteDisconnected")
    cli._sesion = SesionCorte([])
    with pytest.raises(foundry.ErrorFoundry):
        cli.responder("preventa-coordinador", "hola")
    assert cli.registro == []


def test_no_envia_token_a_host_ajeno(cli):
    cli._sesion = Sesion([])
    with pytest.raises(foundry.OperacionNoPermitida):
        cli._peticion("GET", "https://atacante.example.com/x", lambda: "tok")
    assert cli._sesion.peticiones == []


def test_has_more_sin_datos_falla(cli):
    cli._sesion = Sesion([Resp(200, b'{"data":[],"has_more":true}')])
    with pytest.raises(foundry.ErrorFoundry, match="truncada"):
        cli.listar("agents")


def test_no_envia_token_a_otro_recurso_de_foundry(cli):
    cli._sesion = Sesion([])
    with pytest.raises(foundry.OperacionNoPermitida):
        cli._peticion("GET", "https://otro-recurso.services.ai.azure.com/x", lambda: "tok")
    assert cli._sesion.peticiones == []
