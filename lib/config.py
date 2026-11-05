"""Carga y validación de la configuración del entorno.

Se lee `config/entorno.local.json` (ignorado por git, con los valores reales) o la ruta de la variable
`PREVENTA_ENTORNO`. La plantilla versionada `config/entorno.ejemplo.json` solo lleva valores ficticios: si falta
el fichero local, la carga falla en alto en lugar de caer a la plantilla.

Comprueba que están todas las claves obligatorias, que los agentes llevan el prefijo
preventa-, que el verificador usa un modelo distinto del de los expertos y que el
fichero no contiene nada con aspecto de secreto.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
from urllib.parse import urlparse

RAIZ = pathlib.Path(__file__).resolve().parent.parent
RUTA_POR_DEFECTO = RAIZ / "config" / "entorno.local.json"
RUTA_EJEMPLO = RAIZ / "config" / "entorno.ejemplo.json"

OBLIGATORIAS = ("tenant_id", "suscripcion_id", "grupo_recursos", "recurso", "proyecto",
                "endpoints", "api_versions", "agentes", "conexiones", "roles", "protegidos")
HOST_DATOS = ".services.ai.azure.com"
HOST_ARM = "https://management.azure.com"
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CLAVES_SECRETAS = re.compile(r"(key|secret|password|token|sas|connection_?string)", re.I)
_VALOR_SECRETO = re.compile(r"(eyJ[A-Za-z0-9_-]{20,}|AccountKey=|sig=|-----BEGIN)")


class ErrorConfig(ValueError):
    """La configuración no es válida."""


def _buscar_secretos(obj, ruta="$"):
    """Devuelve las rutas JSON con nombre o valor sospechoso de ser secreto."""
    hallazgos = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _CLAVES_SECRETAS.search(k):
                hallazgos.append(f"{ruta}.{k}")
            hallazgos += _buscar_secretos(v, f"{ruta}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hallazgos += _buscar_secretos(v, f"{ruta}[{i}]")
    elif isinstance(obj, str) and _VALOR_SECRETO.search(obj):
        hallazgos.append(ruta)
    return hallazgos


def validar(cfg: dict) -> dict:
    """Valida el diccionario de configuración; devuelve el mismo objeto o lanza ErrorConfig."""
    faltan = [k for k in OBLIGATORIAS if k not in cfg]
    if faltan:
        raise ErrorConfig(f"Faltan claves obligatorias: {faltan}")
    for k in ("tenant_id", "suscripcion_id"):
        if not _GUID.match(str(cfg[k])):
            raise ErrorConfig(f"{k} no es un GUID: {cfg[k]!r}")
    # Los tokens solo pueden viajar a hosts de Microsoft conocidos (evita fugas por config).
    ep = cfg["endpoints"]
    for k in ("proyecto", "recurso"):
        u = urlparse(str(ep.get(k, "")))
        if u.scheme != "https" or not (u.hostname or "").endswith(HOST_DATOS):
            raise ErrorConfig(f"endpoints.{k} debe ser https://*{HOST_DATOS}")
    if not str(ep.get("proyecto", "")).startswith(str(ep.get("recurso", "")).rstrip("/") + "/api/projects/"):
        raise ErrorConfig("endpoints.proyecto debe colgar de endpoints.recurso (/api/projects/...)")
    if str(ep.get("arm", "")).rstrip("/") != HOST_ARM:
        raise ErrorConfig(f"endpoints.arm debe ser {HOST_ARM}")
    prefijo = cfg.get("prefijo_agentes", "preventa-")
    for rol, ag in cfg["agentes"].items():
        if not ag.get("nombre", "").startswith(prefijo):
            raise ErrorConfig(f"El agente {rol} no lleva el prefijo {prefijo}")
        if not ag.get("modelo"):
            raise ErrorConfig(f"El agente {rol} no tiene modelo")
    ver = cfg["agentes"].get("verificador")
    if ver:
        otros = {a["modelo"] for r, a in cfg["agentes"].items() if r != "verificador"}
        if ver["modelo"] in otros:
            raise ErrorConfig("El verificador debe usar un modelo distinto del de los demás agentes")
    protegidos = set(cfg["protegidos"].get("agentes", []))
    choque = protegidos & {a["nombre"] for a in cfg["agentes"].values()}
    if choque:
        raise ErrorConfig(f"Nombres de agente que chocan con agentes protegidos: {choque}")
    secretos = _buscar_secretos(cfg)
    if secretos:
        raise ErrorConfig(f"La configuración no puede contener secretos: {secretos}")
    return cfg


def cargar(ruta: str | pathlib.Path | None = None) -> dict:
    """Lee y valida el fichero de configuración (UTF-8): `ruta`, `PREVENTA_ENTORNO` o el local."""
    p = pathlib.Path(ruta or os.environ.get("PREVENTA_ENTORNO") or RUTA_POR_DEFECTO)
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ErrorConfig(f"No existe el fichero de configuración: {p}. Créalo a partir de "
                          f"{RUTA_EJEMPLO.relative_to(RAIZ).as_posix()} con los valores de tu entorno.") from None
    except json.JSONDecodeError as e:
        raise ErrorConfig(f"JSON no válido en {p}: {e}") from None
    if not isinstance(cfg, dict):
        raise ErrorConfig("La raíz de la configuración debe ser un objeto JSON")
    return validar(cfg)
