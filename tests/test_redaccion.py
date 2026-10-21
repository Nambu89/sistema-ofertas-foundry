"""Redacción de secretos. Los valores falsos se construyen en tiempo de ejecución."""
from __future__ import annotations

import json

import pytest

from lib.redaccion import MARCA, contiene_secretos, es_nombre_secreto, redactar, redactar_obj
from tests.conftest import jwt_falso

JWT = jwt_falso()
CLAVE_STORAGE = "Ab3+" * 21 + "xY" + "=="  # 86 caracteres de base64 + «==», como una clave de cuenta
FIRMA = "c2lnbmF0dXJhLWZhbHNh" + "%2B" + "Zm9v" + "%3D"
SECRETO = "valor-secreto-" + "123456"

CASOS = [
    ("Authorization: Bearer " + JWT, JWT),
    ("authorization=Bearer abc.def-ghi", "abc.def-ghi"),
    ('{"Authorization": "Bearer ' + JWT + '"}', JWT),
    ("token suelto " + JWT + " en un log", JWT),
    ("Bearer opaco_" + "Z" * 30, "opaco_" + "Z" * 30),
    ("https://cuenta.blob.core.windows.net/c/f.json?sv=2024-11-04&sp=r&se=2026-10-18&sig=" + FIRMA, FIRMA),
    ("DefaultEndpointsProtocol=https;AccountName=cuenta;AccountKey=" + CLAVE_STORAGE + ";EndpointSuffix=core.windows.net", CLAVE_STORAGE),
    ("Endpoint=sb://x/;SharedAccessKeyName=raiz;SharedAccessKey=" + SECRETO, SECRETO),
    ('{"api-key": "' + SECRETO + '"}', SECRETO),
    ("api_key=" + SECRETO + "&otra=1", SECRETO),
    ("x-api-key: " + SECRETO, SECRETO),
    ("Ocp-Apim-Subscription-Key: " + SECRETO, SECRETO),
    ('{"client_secret": "' + SECRETO + '"}', SECRETO),
    ("password=" + SECRETO, SECRETO),
    ('"credentials": {"key": "' + SECRETO + '"}', SECRETO),
    ("clave suelta " + CLAVE_STORAGE, CLAVE_STORAGE),
    ("ghp_" + "a1B2" * 9, "ghp_" + "a1B2" * 9),
    ("sk-" + "q" * 30, "sk-" + "q" * 30),
    # Nombres con prefijo de identificador: las variables de usuario habituales.
    ("AZURE_FOUNDRY_KEY=" + SECRETO, SECRETO),
    ("export AZURE_OPENAI_API_KEY=" + SECRETO, SECRETO),
    ("NVIDIA_API_KEY: " + SECRETO, SECRETO),
    ("OPENCODE_SERVER_PASSWORD=" + SECRETO, SECRETO),
    ('{"azure_api_key": "' + SECRETO + '"}', SECRETO),
    ("-----BEGIN PRIVATE KEY-----\nMIIE" + "x" * 40 + "\n-----END PRIVATE KEY-----", "MIIE" + "x" * 40),
]


@pytest.mark.parametrize("texto,secreto", CASOS)
def test_redacta_y_no_deja_rastro(texto, secreto):
    r = redactar(texto)
    assert secreto not in r
    assert MARCA in r
    assert contiene_secretos(texto)


@pytest.mark.parametrize("texto,secreto", CASOS)
def test_es_idempotente(texto, secreto):
    una = redactar(texto)
    assert redactar(una) == una
    assert not contiene_secretos(una)


@pytest.mark.parametrize("texto", [
    "El coordinador delega en ofa-experto-ms con contextId nuevo.",
    "max_tokens=4000 y tokens_salida: 1200",
    "sha256: 3f2a9c0d1e5b7a8c9d0e1f2a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e",
    "tenant 12345678-90ab-cdef-1234-567890abcdef, proyecto mi-proyecto-foundry",
    "https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents?view=foundry",
    "Los secretos viven en conexiones del proyecto; keyword=valor; monkey: sí",
    "OLDPWD=/c/x y input_tokens: 3, total_tokens=5, api-version=v1",
])
def test_no_toca_texto_sin_secretos(texto):
    assert redactar(texto) == texto
    assert not contiene_secretos(texto)


def test_conserva_lo_que_rodea_al_secreto():
    url = "https://c.blob.core.windows.net/x?sp=r&sig=" + FIRMA + "&spr=https"
    assert redactar(url) == "https://c.blob.core.windows.net/x?sp=r&sig=" + MARCA + "&spr=https"


def test_redactar_obj_por_nombre_de_campo_y_por_valor():
    obj = {"properties": {"authType": "ApiKey", "credentials": {"key": SECRETO}},
           "Token": 12345, "lista": ["Bearer " + JWT, {"password": SECRETO}], "normal": "texto",
           "vacio": ""}
    r = redactar_obj(obj)
    plano = json.dumps(r, ensure_ascii=False)
    assert SECRETO not in plano and JWT not in plano and "12345" not in plano
    assert r["normal"] == "texto" and r["vacio"] == ""
    assert r["properties"]["authType"] == "ApiKey"
    assert obj["properties"]["credentials"]["key"] == SECRETO  # no muta el original


@pytest.mark.parametrize("nombre,esperado", [
    ("api-key", True), ("API_KEY", True), ("AccountKey", True), ("sig", True), ("token", True),
    ("authorization", True), ("connectionString", True), ("max_tokens", False),
    ("nombre", False), ("signature_version", False),
    ("AZURE_FOUNDRY_KEY", True), ("NVIDIA_API_KEY", True), ("OPENCODE_SERVER_PASSWORD", True),
    ("azure_api_key", True), ("OLDPWD", False), ("total_tokens", False), ("api_versions", False),
])
def test_es_nombre_secreto(nombre, esperado):
    assert es_nombre_secreto(nombre) is esperado


def test_none_y_no_cadenas():
    assert redactar(None) == ""
    assert redactar(1234) == "1234"


def test_redactar_obj_y_validar_con_nombres_con_prefijo(cfg):
    from lib.config import ErrorConfig, validar
    obj = {"AZURE_OPENAI_API_KEY": SECRETO, "OPENCODE_SERVER_PASSWORD": SECRETO, "total_tokens": 5}
    r = redactar_obj(obj)
    assert SECRETO not in json.dumps(r) and r["total_tokens"] == 5
    cfg["extra"] = {"AZURE_FOUNDRY_KEY": SECRETO}
    with pytest.raises(ErrorConfig, match="secretos"):
        validar(cfg)
