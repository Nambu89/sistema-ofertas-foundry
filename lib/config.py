"""Carga y validación de la configuración del entorno: config/entorno.local.json.

El fichero real (tenant, suscripción, recurso, proyecto y nombres protegidos de otros proyectos) es
local y git lo ignora. Se versiona solo la plantilla config/entorno.ejemplo.json, con valores
ficticios: se copia a config/entorno.local.json y se rellenan los valores reales. Si el fichero local
no existe, `cargar` falla en alto con ese mismo aviso.

La variable OFA_ENTORNO apunta a otro fichero (las pruebas la usan con la plantilla). Si está definida
pero vacía o solo con espacios, se rechaza nombrándola (LES-G-076): no se cae en silencio al valor por
defecto.

Falla en alto (ErrorConfig) si falta una clave obligatoria, si un GUID no lo es, si un endpoint
no es de Microsoft, si un agente del sistema no lleva el prefijo ofa-, si choca con un protegido,
si un despliegue no declara su SKU o si el fichero contiene algo con aspecto de secreto.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
from urllib.parse import urlparse

from lib.redaccion import contiene_secretos, es_nombre_secreto

RAIZ = pathlib.Path(__file__).resolve().parent.parent
RUTA_POR_DEFECTO = RAIZ / "config" / "entorno.local.json"
RUTA_EJEMPLO = RAIZ / "config" / "entorno.ejemplo.json"
VARIABLE_RUTA = "OFA_ENTORNO"
# Valores ficticios de la plantilla: un fichero que no sea la propia plantilla y conserve alguno se rechaza.
GUID_FICTICIO = "00000000-0000-0000-0000-000000000000"
VALORES_PLANTILLA = {"tenant_id": GUID_FICTICIO, "suscripcion_id": GUID_FICTICIO,
                     "grupo_recursos": "rg-ejemplo", "recurso": "mi-recurso-foundry",
                     "proyecto": "mi-proyecto-foundry"}

PREFIJO_SISTEMA = "ofa-"
PREFIJO_PRUEBA = "ofa-prueba-"
OBLIGATORIAS = ("tenant_id", "suscripcion_id", "grupo_recursos", "recurso", "proyecto",
                "endpoints", "audiencias", "api_versions", "prefijo_agentes",
                "prefijo_agentes_prueba", "protegidos", "despliegues", "agentes", "roles")
HOST_DATOS = ".services.ai.azure.com"
HOST_ARM = "https://management.azure.com"
SKUS_ADMITIDOS = {"DataZoneStandard", "GlobalStandard", "Standard", "DataZoneProvisionedManaged",
                  "GlobalProvisionedManaged", "ProvisionedManaged", "GlobalBatch", "DataZoneBatch"}
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ErrorConfig(ValueError):
    """La configuración no es válida."""


def _buscar_secretos(obj, ruta="$") -> list[str]:
    """Rutas JSON con nombre o valor de aspecto secreto."""
    hallazgos: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if es_nombre_secreto(str(k)):
                hallazgos.append(f"{ruta}.{k}")
            hallazgos += _buscar_secretos(v, f"{ruta}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hallazgos += _buscar_secretos(v, f"{ruta}[{i}]")
    elif isinstance(obj, str) and contiene_secretos(obj):
        hallazgos.append(ruta)
    return hallazgos


def validar(cfg: dict) -> dict:
    """Valida el diccionario de configuración; devuelve el mismo objeto o lanza ErrorConfig."""
    if not isinstance(cfg, dict):
        raise ErrorConfig("La raíz de la configuración debe ser un objeto JSON")
    faltan = [k for k in OBLIGATORIAS if k not in cfg]
    if faltan:
        raise ErrorConfig(f"Faltan claves obligatorias: {faltan}")
    secretos = _buscar_secretos(cfg)
    if secretos:
        raise ErrorConfig(f"La configuración no puede contener secretos: {secretos}")
    for k in ("tenant_id", "suscripcion_id"):
        if not _GUID.fullmatch(str(cfg[k])):
            raise ErrorConfig(f"{k} no es un GUID en minúsculas: {cfg[k]!r}")
    # Los tokens solo pueden viajar a hosts de Microsoft conocidos (evita fugas por configuración).
    ep = cfg["endpoints"]
    for k in ("proyecto", "recurso"):
        u = urlparse(str(ep.get(k, "")))
        if (u.scheme != "https" or not (u.hostname or "").endswith(HOST_DATOS)
                or u.port is not None or u.username or u.password or u.query or u.fragment):
            raise ErrorConfig(f"endpoints.{k} debe ser https://*{HOST_DATOS} sin puerto, "
                              f"credenciales, consulta ni fragmento")
    if not str(ep.get("proyecto", "")).startswith(str(ep.get("recurso", "")).rstrip("/") + "/api/projects/"):
        raise ErrorConfig("endpoints.proyecto debe colgar de endpoints.recurso (/api/projects/...)")
    if str(ep.get("arm", "")).rstrip("/") != HOST_ARM:
        raise ErrorConfig(f"endpoints.arm debe ser {HOST_ARM}")
    # Prefijos fijos: no se pueden relajar desde la configuración (LES-G-061).
    if cfg["prefijo_agentes"] != PREFIJO_SISTEMA:
        raise ErrorConfig(f"prefijo_agentes debe ser exactamente {PREFIJO_SISTEMA!r}")
    if cfg["prefijo_agentes_prueba"] != PREFIJO_PRUEBA:
        raise ErrorConfig(f"prefijo_agentes_prueba debe ser exactamente {PREFIJO_PRUEBA!r}")
    prot = cfg["protegidos"]
    if not isinstance(prot, dict) or not prot.get("agentes") or not prot.get("prefijos_agentes"):
        raise ErrorConfig("protegidos debe declarar 'agentes' y 'prefijos_agentes' no vacíos")
    # Una cadena en lugar de una lista se recorrería carácter a carácter y desactivaría la guarda.
    for campo in ("agentes", "prefijos_agentes", "toolboxes"):
        lista = prot.get(campo, [])
        if not isinstance(lista, list) or not all(isinstance(x, str) and x.strip() for x in lista):
            raise ErrorConfig(f"protegidos.{campo} debe ser una lista de cadenas no vacías")
    for pref in prot["prefijos_agentes"]:
        if PREFIJO_SISTEMA.lower().startswith(str(pref).lower()) or str(pref).lower().startswith(PREFIJO_SISTEMA):
            raise ErrorConfig(f"El prefijo protegido {pref!r} se solapa con {PREFIJO_SISTEMA!r}")
    protegidos = {str(n).casefold() for n in prot["agentes"]}
    for rol, ag in cfg["agentes"].items():
        nombre = str(ag.get("nombre", ""))
        if not nombre.startswith(PREFIJO_SISTEMA) or nombre.startswith(PREFIJO_PRUEBA):
            raise ErrorConfig(f"El agente {rol} ({nombre!r}) debe llevar el prefijo {PREFIJO_SISTEMA} "
                              f"y no el de prueba")
        if nombre.casefold() in protegidos:
            raise ErrorConfig(f"El agente {rol} ({nombre!r}) choca con un agente protegido")
        if ag.get("tipo") not in ("hosted", "prompt"):
            raise ErrorConfig(f"El agente {rol} debe tener tipo 'hosted' o 'prompt'")
    for nombre, d in cfg["despliegues"].items():
        if not isinstance(d, dict) or d.get("sku") not in SKUS_ADMITIDOS or not d.get("modelo"):
            raise ErrorConfig(f"El despliegue {nombre!r} debe declarar modelo y un SKU conocido")
    return cfg


def ruta_configurada() -> pathlib.Path:
    """Fichero que se cargará: OFA_ENTORNO si está definida, si no config/entorno.local.json."""
    valor = os.environ.get(VARIABLE_RUTA)
    if valor is None:
        return RUTA_POR_DEFECTO
    if not valor.strip():
        raise ErrorConfig(f"La variable {VARIABLE_RUTA} está definida pero vacía: quítala o pon la ruta "
                          f"del fichero de configuración")
    return pathlib.Path(valor.strip())


def cargar(ruta: str | pathlib.Path | None = None) -> dict:
    """Lee y valida el fichero de configuración (UTF-8). Sin `ruta`, usa `ruta_configurada()`."""
    p = ruta_configurada() if ruta is None else pathlib.Path(ruta)
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if p == RUTA_POR_DEFECTO:
            raise ErrorConfig(
                f"No existe el fichero de configuración: {p}. Copia la plantilla "
                f"{RUTA_EJEMPLO.relative_to(RAIZ).as_posix()} a {p.relative_to(RAIZ).as_posix()} "
                f"y sustituye los valores ficticios por los de tu entorno (git lo ignora).") from None
        raise ErrorConfig(f"No existe el fichero de configuración: {p}") from None
    except json.JSONDecodeError as e:
        raise ErrorConfig(f"JSON no válido en {p}: {e}") from None
    validar(cfg)
    # Una copia de la plantilla sin rellenar no es un entorno: sus valores ficticios solo valen en la propia
    # plantilla (que usan las pruebas). Si no, los comandos llegarían a Azure con identificadores inventados.
    if p.resolve() != RUTA_EJEMPLO.resolve():  # la ruta exacta de la plantilla, no cualquier fichero con su nombre
        ficticios = [k for k, v in VALORES_PLANTILLA.items() if str(cfg.get(k, "")).casefold() == v]
        if ficticios:
            raise ErrorConfig(f"{p} conserva valores ficticios de la plantilla en {ficticios}: sustitúyelos "
                              f"por los de tu entorno")
    return cfg
