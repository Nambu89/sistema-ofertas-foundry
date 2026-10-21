"""Utilidades comunes de las pruebas. Ninguna prueba llama a Azure ni a la red."""
from __future__ import annotations

import base64
import copy
import json
import os

import pytest

from lib import config

# Las pruebas usan SIEMPRE la plantilla versionada, con valores ficticios: no dependen del entorno real
# de nadie ni lo leen. Se fija aquí para todo el proceso y para los subprocesos (comun.sh la respeta).
os.environ[config.VARIABLE_RUTA] = str(config.RUTA_EJEMPLO)

TENANT = config.cargar(config.RUTA_EJEMPLO)["tenant_id"]
OTRO_TENANT = "00000000-1111-2222-3333-444444444444"


def jwt_falso(tid: str = TENANT, exp: float | None = None, extra: dict | None = None) -> str:
    """JWT sin firma válida, construido en tiempo de ejecución (no hay secretos en el repositorio)."""
    def b64(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    cuerpo = {"tid": tid, "aud": "https://ai.azure.com"}
    if exp is not None:
        cuerpo["exp"] = int(exp)
    cuerpo.update(extra or {})
    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(cuerpo)}.firma-falsa"


class Reloj:
    """Reloj controlable para simular el paso del tiempo."""

    def __init__(self, ahora: float = 1_000_000.0) -> None:
        self.ahora = ahora

    def __call__(self) -> float:
        return self.ahora

    def avanzar(self, s: float) -> None:
        self.ahora += s


class RespuestaFalsa:
    def __init__(self, estado: int = 200, cuerpo: dict | None = None, cabeceras: dict | None = None):
        self.status_code = estado
        self._cuerpo = cuerpo if cuerpo is not None else {}
        self.content = json.dumps(self._cuerpo).encode()
        self.text = self.content.decode()
        self.headers = cabeceras or {}

    def json(self) -> dict:
        return self._cuerpo


class SesionFalsa:
    """Sustituye a requests.Session: anota cada petición y devuelve respuestas preparadas."""

    def __init__(self, respuestas: list[RespuestaFalsa] | None = None) -> None:
        self.respuestas = list(respuestas or [])
        self.llamadas: list[dict] = []

    def request(self, metodo, url, **kw):
        self.llamadas.append({"metodo": metodo, "url": url, **kw})
        if not self.respuestas:
            return RespuestaFalsa(200, {"data": [], "has_more": False})
        return self.respuestas.pop(0)


@pytest.fixture
def cfg() -> dict:
    return copy.deepcopy(config.cargar())


@pytest.fixture
def reloj() -> Reloj:
    return Reloj()
