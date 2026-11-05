"""Texto y adjuntos del turno, desde los input items del Responses protocol.

Un adjunto llega como `input_file` con `file_data` (data URL o base64), con `file_id` (subido antes a
/openai/v1/files: se descarga con la identidad del agente) o ya está en la carpeta de datos de la
sesión (subido por la API de ficheros de sesión). `file_url` se rechaza: el agente no descarga URLs
arbitrarias. El nombre se reduce a su base y a una lista blanca de caracteres (sin rutas).
"""
from __future__ import annotations

import base64
import binascii
import pathlib
import re
from collections.abc import Mapping
from typing import Callable

import httpx

_NOMBRE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,120}\.(txt|vtt|docx|pdf|json|zip)$")
MAX_BYTES = 50 * 1024 * 1024   # el tope de subida de la API de ficheros de sesión
MAX_ADJUNTOS = 4


class ErrorAdjunto(ValueError):
    """Adjunto rechazado, con el motivo."""


def _get(obj, clave: str):
    if isinstance(obj, Mapping):
        return obj.get(clave)
    try:
        return obj[clave]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, clave, None)


def nombre_seguro(nombre: str | None) -> str:
    base = pathlib.PurePosixPath(str(nombre or "").replace("\\", "/")).name.strip()
    if not _NOMBRE.fullmatch(base) or ".." in base:
        raise ErrorAdjunto(f"nombre de adjunto no admitido: {nombre!r} (solo .txt, .vtt, .docx, .pdf, .json o .zip, "
                           "sin rutas)")
    return base


def _decodificar(file_data: str) -> bytes:
    payload = file_data.split(",", 1)[1] if file_data.lower().startswith("data:") else file_data
    if len(payload) * 3 // 4 > MAX_BYTES:   # se comprueba ANTES de decodificar
        raise ErrorAdjunto(f"adjunto de unos {len(payload) * 3 // 4} bytes; el máximo es {MAX_BYTES}")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ErrorAdjunto(f"file_data no es base64 válido: {exc}") from exc


def leer_items(items) -> tuple[str, list[dict]]:
    """(texto del usuario, ficheros) de los input items. Cada fichero: nombre, file_data, file_id, file_url."""
    textos, ficheros = [], []
    for it in items or []:
        if _get(it, "type") not in (None, "message") or _get(it, "role") not in (None, "user"):
            continue
        contenido = _get(it, "content")
        if isinstance(contenido, str):
            textos.append(contenido)
            continue
        for c in contenido or []:
            tipo = _get(c, "type")
            if tipo == "input_text":
                textos.append(_get(c, "text") or "")
            elif tipo == "input_file":
                ficheros.append({k: _get(c, k) for k in ("filename", "file_data", "file_id", "file_url")})
    return "\n".join(textos), ficheros


def guardar(ficheros: list[dict], datos: pathlib.Path, proyecto: str, token: Callable[[], str],
            transporte: httpx.BaseTransport | None = None) -> list[str]:
    """Guarda cada adjunto en `datos/<nombre>`. No pisa un fichero distinto con el mismo nombre."""
    datos.mkdir(parents=True, exist_ok=True)
    if len(ficheros) > MAX_ADJUNTOS:
        raise ErrorAdjunto(f"{len(ficheros)} adjuntos en un turno; el máximo es {MAX_ADJUNTOS}")
    guardados = []
    for f in ficheros:
        if f.get("file_url"):
            raise ErrorAdjunto("adjunto por URL no admitido: adjúntalo como fichero")
        if f.get("file_data"):
            contenido = _decodificar(f["file_data"])
            nombre = nombre_seguro(f.get("filename"))
        elif f.get("file_id"):
            contenido, nombre_api = _descargar(f["file_id"], proyecto, token, transporte)
            nombre = nombre_seguro(f.get("filename") or nombre_api)
        else:
            raise ErrorAdjunto("input_file sin file_data ni file_id")
        if len(contenido) > MAX_BYTES:
            raise ErrorAdjunto(f"{nombre}: {len(contenido)} bytes; el máximo es {MAX_BYTES}")
        destino = datos / nombre
        if destino.exists() and destino.read_bytes() != contenido:
            raise ErrorAdjunto(f"ya hay un {nombre} distinto en la sesión: renómbralo o abre una conversación nueva")
        destino.write_bytes(contenido)
        guardados.append(nombre)
    return guardados


def _descargar(file_id: str, proyecto: str, token: Callable[[], str],
               transporte: httpx.BaseTransport | None) -> tuple[bytes, str | None]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,80}", file_id or ""):
        raise ErrorAdjunto(f"file_id no válido: {file_id!r}")
    cab = {"Authorization": f"Bearer {token()}"}
    try:
        with httpx.Client(timeout=60, transport=transporte) as c:
            meta = c.get(f"{proyecto}/openai/v1/files/{file_id}", headers=cab)
            cuerpo = c.get(f"{proyecto}/openai/v1/files/{file_id}/content", headers=cab)
    except Exception as exc:
        raise ErrorAdjunto(f"no se pudo descargar {file_id}: {type(exc).__name__}: {str(exc)[:300]}") from exc
    if cuerpo.status_code != 200:
        raise ErrorAdjunto(f"no se pudo descargar {file_id}: HTTP {cuerpo.status_code}: {cuerpo.text[:500]}")
    nombre = meta.json().get("filename") if meta.status_code == 200 else None
    return cuerpo.content, nombre
