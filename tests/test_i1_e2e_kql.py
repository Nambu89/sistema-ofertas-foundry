"""KQL de procedencia por REST en UTF-8 (defecto encontrado en el E2E de I1: `az` devolvía cp1252).

Desde I1.2 la vía por defecto es ARM (lib.appi, token de management.azure.com); la vía v1
(api.applicationinsights.io) queda solo con PREVENTA_KQL_VIA=v1. Un valor desconocido falla en alto.
"""
from __future__ import annotations

import json

import pytest

import verificar_paquete as vp

TILDES = {"tables": [{"columns": [{"name": "name"}, {"name": "dims"}],
                      "rows": [["execute_tool x", "{\"detalle\": \"región de la Unión → «sí»\"}"]]}]}


class _Resp:
    def __init__(self, estado: int, cuerpo: dict | str):
        self.status_code = estado
        texto = cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False)
        self.content = texto.encode("utf-8")
        self.text = texto
        self.headers: dict = {}


def _parchear(monkeypatch, resp, capturado):
    import requests

    from lib import azure_auth

    def post(url, json=None, data=None, headers=None, timeout=None):  # noqa: A002 - firma de requests
        cuerpo = json if json is not None else __import__("json").loads(data.decode("utf-8"))
        capturado.update(url=url, cuerpo=cuerpo, cabeceras=headers)
        return resp

    def token(recurso, tenant=None):
        capturado["audiencia"] = recurso
        return "tok-de-prueba"

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(azure_auth, "obtener_token", token)


def test_consulta_arm_por_defecto_conserva_tildes(monkeypatch):
    monkeypatch.delenv("PREVENTA_KQL_VIA", raising=False)
    capturado: dict = {}
    _parchear(monkeypatch, _Resp(200, TILDES), capturado)
    filas = vp.consultar_kql_real("print 1")
    assert filas == [{"name": "execute_tool x", "dims": "{\"detalle\": \"región de la Unión → «sí»\"}"}]
    assert "�" not in json.dumps(filas, ensure_ascii=False)
    assert capturado["url"].startswith("https://management.azure.com/subscriptions/")
    assert capturado["url"].endswith(f"/components/{vp.APPI_ESPERADO}/query?api-version=2018-04-20")
    assert capturado["audiencia"] == "https://management.azure.com"
    assert capturado["cuerpo"] == {"query": "print 1", "timespan": "P30D"}


@pytest.mark.parametrize("estado,cuerpo,patron", [
    (403, "Forbidden", "HTTP 403"),
    (200, {"sin": "tablas"}, "tables"),
    (200, {**TILDES, "error": {"code": "PartialError"}}, "parcial"),
])
def test_consulta_arm_error_falla_en_alto(monkeypatch, estado, cuerpo, patron):
    monkeypatch.delenv("PREVENTA_KQL_VIA", raising=False)
    _parchear(monkeypatch, _Resp(estado, cuerpo), {})
    with pytest.raises(RuntimeError, match=patron):
        vp.consultar_kql_real("print 1")


def test_consulta_v1_solo_con_la_variable(monkeypatch):
    monkeypatch.setenv("PREVENTA_KQL_VIA", " V1 ")
    capturado: dict = {}
    _parchear(monkeypatch, _Resp(200, TILDES), capturado)
    assert vp.consultar_kql_real("print 1")[0]["name"] == "execute_tool x"
    assert capturado["url"].startswith(vp.AUD_APPI + "/v1/subscriptions/")
    assert capturado["audiencia"] == vp.AUD_APPI
    _parchear(monkeypatch, _Resp(403, "Forbidden"), {})
    with pytest.raises(RuntimeError, match="HTTP 403"):
        vp.consultar_kql_real("print 1")


@pytest.mark.parametrize("valor", ["azure", "ARM2", "api"])
def test_via_desconocida_falla_en_alto(monkeypatch, valor):
    monkeypatch.setenv("PREVENTA_KQL_VIA", valor)
    _parchear(monkeypatch, _Resp(200, TILDES), {})
    with pytest.raises(RuntimeError, match="PREVENTA_KQL_VIA"):
        vp.consultar_kql_real("print 1")


def test_via_vacia_o_espacios_es_arm(monkeypatch):
    for valor in ("", "   "):
        monkeypatch.setenv("PREVENTA_KQL_VIA", valor)
        assert vp.via_kql() == "arm"


def test_filas_de_tabla_vacia_y_malformada():
    assert vp.filas_de_tabla({"tables": [{"columns": [{"name": "a"}], "rows": []}]}) == []
    with pytest.raises(RuntimeError, match="tables"):
        vp.filas_de_tabla({})
    with pytest.raises(RuntimeError, match="no casan"):
        vp.filas_de_tabla({"tables": [{"columns": [{"name": "a"}], "rows": [["x", "sobra"]]}]})
