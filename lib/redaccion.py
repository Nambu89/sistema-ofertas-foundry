"""Redacción de secretos en cualquier texto antes de guardarlo, registrarlo o imprimirlo.

Cubre tokens Bearer y JWT, cabeceras de autorización, claves de API y de cuenta de Storage,
cadenas de conexión, firmas SAS (`sig=`), claves privadas PEM y campos con nombre de secreto
en JSON, cabeceras HTTP y pares `clave=valor`.

Reglas:
- Es idempotente: redactar dos veces da lo mismo que redactar una.
- Nunca devuelve el secreto, ni recortado ni en parte: lo sustituye entero por un marcador.
- No es una lista exhaustiva. Es la última red antes del disco o la consola, no un permiso para
  pasar secretos por donde no deben: el código no debe tenerlos en el texto en primer lugar.
"""
from __future__ import annotations

import re
from typing import Any

MARCA = "[REDACTADO]"

# Nombres de campo cuyo valor se considera secreto (JSON, cabeceras, consulta, clave=valor).
_NOMBRES_SECRETOS = (
    r"api[-_]?key|apikey|x-api-key|ocp-apim-subscription-key|subscription[-_]?key"
    r"|client[-_]?secret|secret|password|passwd|pwd"
    r"|access[-_]?token|refresh[-_]?token|id[-_]?token|token"
    r"|account[-_]?key|accountkey|primary[-_]?key|secondary[-_]?key|key1|key2"
    r"|shared[-_]?access[-_]?key|sharedaccesskey|sharedaccesssignature|sas[-_]?token|sas"
    r"|connection[-_]?string|connectionstring|sig|authorization|credentials?|key"
)
# Prefijo de identificador opcional, separado por «_» o «-»: AZURE_OPENAI_API_KEY, NVIDIA_API_KEY,
# OPENCODE_SERVER_PASSWORD, azure_api_key. Exige el separador para no confundir OLDPWD o monkey.
_PREFIJO_NOMBRE = r"(?:[A-Za-z0-9]+[_-])*"
_RE_NOMBRE_SECRETO = re.compile(rf"^{_PREFIJO_NOMBRE}(?:{_NOMBRES_SECRETOS})$", re.IGNORECASE)

_PATRONES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Bloques PEM de clave privada completos.
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
                re.DOTALL), MARCA),
    # Cabecera Authorization con cualquier esquema (Bearer, Basic, SharedKey...).
    (re.compile(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(?!(?:bearer\s+)?\[REDACTADO\])"
                r"(?:(?:bearer|basic|sharedkey|sharedaccesssignature)\s+)?[^\s\"',;}]+"), r"\1" + MARCA),
    # Token Bearer suelto.
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9\-._~+/]+=*"), r"\1" + MARCA),
    # JWT (cabecera.cuerpo.firma) aunque no lleve Bearer delante.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), MARCA),
    # Segmentos de cadenas de conexión: AccountKey=...; SharedAccessKey=...; SharedAccessSignature=...
    (re.compile(r"(?i)\b(AccountKey|SharedAccessKey|SharedAccessSignature|Password|Pwd)=([^;\s\"']+)"),
     r"\1=" + MARCA),
    # Firma de una SAS en una URL o consulta.
    (re.compile(r"(?i)([?&;]sig=)[^&\s\"'#]+"), r"\1" + MARCA),
    # Pares nombre-valor con nombre de secreto, con o sin prefijo: "api-key": "x", api_key=x,
    # x-api-key: x, AZURE_FOUNDRY_KEY=x, "azure_api_key": "x".
    (re.compile(rf"(?i)(?<![A-Za-z0-9_-])({_PREFIJO_NOMBRE}(?:{_NOMBRES_SECRETOS})[\"']?\s*[:=]\s*[\"']?)"
                r"(?![{\[])[^\s\"',;&}]+"), r"\1" + MARCA),
    # Clave de cuenta de Storage suelta (88 caracteres en base64 terminados en ==).
    (re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{86}==(?![A-Za-z0-9+/=])"), MARCA),
    # Tokens personales de GitHub y claves con prefijo sk-.
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"), MARCA),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), MARCA),
)


def redactar(texto: Any) -> str:
    """Devuelve `texto` (convertido a str) con todos los secretos reconocidos sustituidos."""
    s = "" if texto is None else str(texto)
    for patron, sustituto in _PATRONES:
        s = patron.sub(sustituto, s)
    return s


def es_nombre_secreto(nombre: str) -> bool:
    """True si el nombre de un campo indica que su valor es un secreto."""
    return bool(_RE_NOMBRE_SECRETO.fullmatch(str(nombre).strip()))


def redactar_obj(obj: Any) -> Any:
    """Copia de `obj` (dict, list, tuple o escalar) con los secretos redactados.

    El valor de cualquier campo con nombre de secreto se sustituye entero, sea del tipo que sea;
    las cadenas se pasan además por `redactar`.
    """
    if isinstance(obj, dict):
        return {k: (MARCA if es_nombre_secreto(str(k)) and v not in (None, "") else redactar_obj(v))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(redactar_obj(v) for v in obj)
    if isinstance(obj, str):
        return redactar(obj)
    return obj


def contiene_secretos(texto: Any) -> bool:
    """True si `redactar` cambiaría el texto (sirve como comprobación antes de guardar)."""
    s = "" if texto is None else str(texto)
    return redactar(s) != s
