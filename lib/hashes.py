"""Huellas SHA-256 de ficheros y hash canónico de JSON (claves ordenadas, UTF-8).

El hash canónico es estable frente al orden de las claves y al espaciado, de modo que dos
documentos con el mismo contenido lógico dan la misma huella. Los floats no finitos (NaN,
infinito) se rechazan para que el hash no dependa de representaciones ambiguas.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Iterable

_BLOQUE = 1024 * 1024


def sha256_bytes(datos: bytes) -> str:
    """SHA-256 hexadecimal de unos bytes."""
    return hashlib.sha256(datos).hexdigest()


def sha256_fichero(ruta: str | pathlib.Path) -> str:
    """SHA-256 hexadecimal de un fichero, leído por bloques."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(_BLOQUE), b""):
            h.update(bloque)
    return h.hexdigest()


def json_canonico(obj: Any) -> bytes:
    """Serialización canónica: claves ordenadas, sin espacios, UTF-8 sin escapar, sin NaN."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def hash_json(obj: Any) -> str:
    """SHA-256 hexadecimal de la serialización canónica de `obj`."""
    return sha256_bytes(json_canonico(obj))


def hash_json_sin(obj: dict, excluir: Iterable[str]) -> str:
    """Hash canónico de un diccionario quitando antes las claves de primer nivel indicadas.

    Sirve, por ejemplo, para el hash_contenido de un paquete sin su bloque de decisiones.
    """
    if not isinstance(obj, dict):
        raise TypeError("hash_json_sin espera un diccionario")
    fuera = set(excluir)
    return hash_json({k: v for k, v in obj.items() if k not in fuera})


def manifiesto(rutas: Iterable[str | pathlib.Path], base: str | pathlib.Path | None = None) -> dict:
    """Diccionario {ruta_relativa_posix: sha256} ordenado, para manifiesto.json."""
    base_p = pathlib.Path(base).resolve() if base else None
    salida: dict[str, str] = {}
    for r in rutas:
        p = pathlib.Path(r).resolve()
        nombre = p.relative_to(base_p).as_posix() if base_p else p.name
        if nombre in salida:
            raise ValueError(f"Nombre duplicado en el manifiesto: {nombre}")
        salida[nombre] = sha256_fichero(p)
    return dict(sorted(salida.items()))
