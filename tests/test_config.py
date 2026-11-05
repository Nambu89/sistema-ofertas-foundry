"""Pruebas de lib/config.py: carga y validación de la configuración del entorno (aquí, la plantilla de ejemplo)."""
import copy
import json

import pytest

from lib import config


@pytest.fixture()
def cfg():
    return config.cargar()


def test_carga_el_fichero_real(cfg):
    assert cfg["proyecto"] == "proyecto-ejemplo"
    assert cfg["tenant_id"] == "00000000-0000-0000-0000-000000000000"
    assert cfg["agentes"]["coordinador"]["nombre"] == "preventa-coordinador"
    assert cfg["agentes"]["coordinador"]["modelo"] == "gpt-6-luna"
    assert cfg["agentes"]["verificador"]["modelo"] == "gpt-5.6-luna"
    assert cfg["conexiones"] == {"experto_azure": "a2a-experto-azure", "verificador": "a2a-verificador"}


def _escribir(tmp_path, datos):
    p = tmp_path / "entorno.json"
    p.write_text(json.dumps(datos), encoding="utf-8")
    return p


def test_falta_clave_obligatoria(cfg, tmp_path):
    malo = copy.deepcopy(cfg)
    del malo["tenant_id"]
    with pytest.raises(config.ErrorConfig, match="tenant_id"):
        config.cargar(_escribir(tmp_path, malo))


def test_rechaza_agente_sin_prefijo(cfg):
    malo = copy.deepcopy(cfg)
    malo["agentes"]["coordinador"]["nombre"] = "coordinador"
    with pytest.raises(config.ErrorConfig, match="prefijo"):
        config.validar(malo)


def test_verificador_con_el_mismo_modelo(cfg):
    malo = copy.deepcopy(cfg)
    malo["agentes"]["verificador"]["modelo"] = "gpt-6-luna"
    with pytest.raises(config.ErrorConfig, match="distinto"):
        config.validar(malo)


def test_rechaza_nombre_de_agente_protegido(cfg):
    malo = copy.deepcopy(cfg)
    malo["prefijo_agentes"] = ""
    malo["agentes"]["coordinador"]["nombre"] = "agente-ajeno-ejemplo"
    with pytest.raises(config.ErrorConfig, match="protegidos"):
        config.validar(malo)


@pytest.mark.parametrize("clave,valor", [
    ("api_key", "x"),
    ("nota", "eyJ" + "0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.abc"),   # JWT falso, partido para el barrido de publicación
    ("cadena", "DefaultEndpointsProtocol=https;AccountKey=abc"),
])
def test_rechaza_secretos(cfg, clave, valor):
    malo = copy.deepcopy(cfg)
    malo["extra"] = {clave: valor}
    with pytest.raises(config.ErrorConfig, match="secretos"):
        config.validar(malo)


def test_guid_no_valido(cfg):
    malo = copy.deepcopy(cfg)
    malo["suscripcion_id"] = "no-es-guid"
    with pytest.raises(config.ErrorConfig, match="GUID"):
        config.validar(malo)


def test_json_roto_y_fichero_inexistente(tmp_path):
    p = tmp_path / "roto.json"
    p.write_text("{", encoding="utf-8")
    with pytest.raises(config.ErrorConfig, match="JSON no válido"):
        config.cargar(p)
    with pytest.raises(config.ErrorConfig, match="No existe"):
        config.cargar(tmp_path / "nada.json")


@pytest.mark.parametrize("clave,valor", [
    ("proyecto", "https://atacante.example.com/api/projects/proyecto-ejemplo"),
    ("recurso", "http://recurso-ejemplo.services.ai.azure.com"),
    ("arm", "https://management.azure.com.example.com"),
])
def test_rechaza_endpoints_fuera_de_microsoft(cfg, clave, valor):
    malo = copy.deepcopy(cfg)
    malo["endpoints"][clave] = valor
    with pytest.raises(config.ErrorConfig):
        config.validar(malo)
