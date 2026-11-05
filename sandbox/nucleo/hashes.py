"""Huellas de I1 (CONTRATOS.md §4.3 y §5): JSON canónico, SHA-256 y hash_contenido.

`json_canonico` es idéntico a `lib/hashes.json_canonico` (hay una prueba que lo compara) y
`hash_contenido` es el SHA-256 del JSON canónico de `estado["carga"]`, que debe tener
exactamente las claves de CLAVES_CARGA. Decisiones, intentos, fallos, control de versiones y
artefactos quedan fuera por construcción: no están en `carga`.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from nucleo.errores import IntegridadRota

CLAVES_CARGA: tuple[str, ...] = (
    "alta", "fuentes", "requisitos", "briefs", "respuestas_expertos", "consolidado",
    "verificacion", "anexo_consumo", "estimacion", "textos_cliente",
)
_BLOQUE = 1024 * 1024


def json_canonico(obj: object) -> bytes:
    """Claves ordenadas, sin espacios, UTF-8 sin escapar y sin NaN ni infinito."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def sha256_bytes(b: bytes) -> str:
    """SHA-256 hexadecimal de unos bytes."""
    return hashlib.sha256(b).hexdigest()


def hash_json(obj: object) -> str:
    """SHA-256 del JSON canónico de `obj`."""
    return sha256_bytes(json_canonico(obj))


def sha256_texto(t: str) -> str:
    """SHA-256 del texto en UTF-8 tras pasar CRLF (y CR suelto) a LF."""
    return sha256_bytes(t.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))


def sha256_fichero(ruta: pathlib.Path) -> str:
    """SHA-256 de un fichero, leído por bloques."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(_BLOQUE), b""):
            h.update(bloque)
    return h.hexdigest()


def hash_contenido(estado: dict) -> str:
    """§5.1. IntegridadRota si `carga` falta o no tiene exactamente CLAVES_CARGA."""
    carga = estado.get("carga") if isinstance(estado, dict) else None
    if not isinstance(carga, dict):
        raise IntegridadRota("estado sin bloque «carga»", ["carga ausente o no es un objeto"])
    claves = set(carga)
    if claves != set(CLAVES_CARGA):
        faltan = sorted(set(CLAVES_CARGA) - claves)
        sobran = sorted(claves - set(CLAVES_CARGA))
        raise IntegridadRota("«carga» no tiene exactamente las claves del contrato",
                             [f"faltan: {faltan}", f"sobran: {sobran}"])
    try:
        return hash_json(carga)
    except (TypeError, ValueError) as e:
        raise IntegridadRota("«carga» no es serializable de forma canónica", [str(e)]) from e
