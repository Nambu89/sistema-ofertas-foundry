"""Validador del subconjunto de JSON Schema de CONTRATOS.md §12 (sin jsonschema).

Replica la semántica de la referencia ejecutable `esquemas/comprobar_esquemas.py`; una prueba
compara los dos sobre los ejemplos y sobre casos límite.
"""
from __future__ import annotations

import json
import math
import pathlib
import re
from typing import Callable

from nucleo.errores import EntradaInvalida, IntegridadRota, ReglaIncumplida

_REPO_ESQUEMAS = pathlib.Path(__file__).resolve().parents[2] / "esquemas"
_NOMBRE = re.compile(r"^[a-z_]+$")
_TIPOS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
    and not (isinstance(v, float) and not math.isfinite(v)),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_CACHE: dict[tuple[str, str], dict] = {}


_LOCALIZADOR: Callable[[str], pathlib.Path] | None = None


def configurar(localizador: Callable[[str], pathlib.Path] | None) -> None:
    """Fija cómo se encuentra «esquema_<nombre>.json» cuando no hay esquemas/ en el repositorio.

    Lo llama la capa de arranque (preventa_run.py) con la búsqueda de su entorno: en el sandbox de
    Code Interpreter, por sufijo en /mnt/data. El localizador recibe el nombre del fichero y devuelve
    su ruta, o lanza IntegridadRota si no hay exactamente uno. None lo quita.
    """
    global _LOCALIZADOR
    _LOCALIZADOR = localizador


def _ruta_esquema(nombre: str, dir_esquemas: pathlib.Path | None) -> pathlib.Path:
    if dir_esquemas is not None:
        return pathlib.Path(dir_esquemas) / f"{nombre}.json"
    if _REPO_ESQUEMAS.is_dir():  # local: esquemas/ del repositorio
        return _REPO_ESQUEMAS / f"{nombre}.json"
    objetivo = f"esquema_{nombre}.json"  # montado junto a los datos (§1.2; un solo guion bajo)
    if _LOCALIZADOR is None:
        raise IntegridadRota(f"No hay esquemas/ ni localizador configurado para {objetivo}",
                             ["la capa de arranque debe llamar a esquema.configurar()"])
    return pathlib.Path(_LOCALIZADOR(objetivo))


def cargar(nombre: str, dir_esquemas: pathlib.Path | None = None) -> dict:
    """Esquema por nombre: esquemas/<nombre>.json, o esquema_<nombre>.json con el localizador configurado."""
    if not isinstance(nombre, str) or not _NOMBRE.match(nombre):
        raise EntradaInvalida(f"Nombre de esquema no válido: {nombre!r}", [])
    ruta = _ruta_esquema(nombre, dir_esquemas)
    clave = (nombre, str(ruta))
    if clave not in _CACHE:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise IntegridadRota(f"No se puede leer el esquema {nombre} ({ruta})", [repr(e)]) from e
        if not isinstance(datos, dict):
            raise IntegridadRota(f"El esquema {nombre} no es un objeto", [str(ruta)])
        ajenas = palabras_no_admitidas(datos)
        if ajenas:  # una palabra que no se valida se ignoraría en silencio: falla en alto
            raise IntegridadRota(f"El esquema {nombre} usa palabras clave fuera del subconjunto §12", ajenas)
        _CACHE[clave] = datos
    return json.loads(json.dumps(_CACHE[clave]))  # copia: nadie altera la caché


# Multinube (04-11-2026, esquemas/MULTINUBE.md): los esquemas de esquemas/ son los de Azure (de ellos salen las
# instrucciones y el text.format del experto de Azure, que no cambian). La variante de Google Cloud o AWS la deriva el
# código: ids con el prefijo del pilar, fuentes de sus dominios, regiones con guion, sigla del brief_id, su agente
# experto y, en el catálogo, la clave `pilar` y el modelo por defecto sin las constantes de Azure.
_DOMINIOS_PILAR = {"gcp": r"(cloud\.google\.com|docs\.cloud\.google\.com)",
                   "aws": r"(docs\.aws\.amazon\.com|aws\.amazon\.com)"}
_SIGLA_PILAR = {"gcp": "GCP", "aws": "AWS"}
_PATRONES_AZURE = ((r"(learn\.microsoft\.com|azure\.microsoft\.com/en-us/pricing)", "{dom}"),
                   (r"learn\.microsoft\.com", "{dom}"), ("az-[a-z0-9-]", "{pilar}-[a-z0-9-]"),
                   ("[a-z]+[a-z0-9]*", "[a-z][a-z0-9-]*[a-z0-9]"), ("-AZ-R", "-{sigla}-R"))
_CONSTANTES_AZURE = {"az-foundry": lambda p: {"type": "string", "pattern": f"^{p}-[a-z0-9-]{{2,40}}$"},
                     "DataZoneStandard": lambda p: {"type": "string", "minLength": 2, "maxLength": 60}}


def cargar_pilar(nombre: str, pilar: str = "azure", dir_esquemas: pathlib.Path | None = None) -> dict:
    """El esquema `nombre` para un pilar: en Azure, exactamente cargar(nombre); en gcp o aws, su variante derivada.
    EntradaInvalida con otro pilar (lista blanca)."""
    base = cargar(nombre, dir_esquemas)
    if pilar == "azure":
        return base
    if pilar not in _DOMINIOS_PILAR:
        raise EntradaInvalida(f"Pilar no admitido: {pilar!r}", ["admitidos: azure, gcp, aws"])
    valores = {"dom": _DOMINIOS_PILAR[pilar], "pilar": pilar, "sigla": _SIGLA_PILAR[pilar]}

    def convertir(nodo: object) -> object:
        if isinstance(nodo, list):
            return [convertir(x) for x in nodo]
        if not isinstance(nodo, dict):
            return nodo
        if set(nodo) - {"description"} == {"const"} and nodo["const"] in _CONSTANTES_AZURE:
            return _CONSTANTES_AZURE[nodo["const"]](pilar)
        salida = {}
        for k, v in nodo.items():
            if k == "pattern" and isinstance(v, str):
                for viejo, nuevo in _PATRONES_AZURE:
                    v = v.replace(viejo, nuevo.format(**valores))
            elif k == "enum" and isinstance(v, list):
                v = [f"preventa-experto-{pilar}" if x == "preventa-experto-azure" else x for x in v]
            elif k != "description":
                v = convertir(v)
            salida[k] = v
        return salida

    variante = convertir(base)
    if nombre in ("catalogo_componentes", "brief"):
        variante["properties"]["pilar"] = {"const": pilar}
    return variante


ADMITIDAS = {"$schema", "$id", "title", "description", "type", "properties", "required", "additionalProperties",
             "items", "minItems", "maxItems", "uniqueItems", "enum", "const", "minLength", "maxLength", "pattern",
             "minimum", "maximum", "exclusiveMinimum", "$defs", "$ref"}


def palabras_no_admitidas(nodo: object, ruta: str = "$") -> list[str]:
    """Palabras clave fuera del subconjunto §12 (mismo criterio que esquemas/comprobar_esquemas.py)."""
    if not isinstance(nodo, dict):
        return []
    err = [f"{ruta}: palabra clave no admitida «{k}»" for k in nodo if k not in ADMITIDAS]
    if "additionalProperties" in nodo and not isinstance(nodo["additionalProperties"], bool):
        err.append(f"{ruta}: additionalProperties solo admite booleanos")
    if "items" in nodo and not isinstance(nodo["items"], dict):
        err.append(f"{ruta}: items solo admite un esquema (objeto)")
    for k in ("properties", "$defs"):
        for nombre, sub in (nodo.get(k) or {}).items():
            err += palabras_no_admitidas(sub, f"{ruta}.{k}.{nombre}")
    if isinstance(nodo.get("items"), dict):
        err += palabras_no_admitidas(nodo["items"], f"{ruta}.items")
    return err


def _igual(a: object, b: object) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _clave_json(x: object) -> str:
    def norm(y: object) -> object:
        if isinstance(y, bool) or y is None or isinstance(y, str):
            return [type(y).__name__, y]
        if isinstance(y, (int, float)):
            return ["num", int(y) if float(y).is_integer() else y]
        if isinstance(y, list):
            return [norm(z) for z in y]
        return {k: norm(z) for k, z in y.items()}
    return json.dumps(norm(x), sort_keys=True)


def _patron(p: str) -> re.Pattern:
    if p.endswith("$") and not p.endswith("\\$"):
        p = p[:-1] + r"\Z"
    return re.compile(p)


def _validar(v: object, e: dict, raiz: dict, ruta: str) -> list[str]:
    if "$ref" in e:
        ref = e["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/$defs/"):
            return [f"{ruta}: $ref no admitida {ref!r}"]
        destino = raiz.get("$defs", {}).get(ref[len("#/$defs/"):])
        if not isinstance(destino, dict):
            return [f"{ruta}: $ref apunta a una definición inexistente {ref}"]
        err = _validar(v, destino, raiz, ruta)
        resto = {k: x for k, x in e.items() if k != "$ref"}
        return err + (_validar(v, resto, raiz, ruta) if resto else [])
    tipos = e.get("type")
    if tipos is not None:
        tipos = tipos if isinstance(tipos, list) else [tipos]
        if not any(_TIPOS[t](v) for t in tipos):
            return [f"{ruta}: tipo {type(v).__name__}, se esperaba {tipos}"]
    err: list[str] = []
    if "const" in e and not _igual(v, e["const"]):
        err.append(f"{ruta}: debe ser {e['const']!r}")
    if "enum" in e and not any(_igual(v, x) for x in e["enum"]):
        err.append(f"{ruta}: {v!r} fuera de {e['enum']}")
    if isinstance(v, str):
        if len(v) < e.get("minLength", 0) or len(v) > e.get("maxLength", math.inf):
            err.append(f"{ruta}: longitud {len(v)} fuera de rango")
        if "pattern" in e and not _patron(e["pattern"]).search(v):
            err.append(f"{ruta}: no casa con {e['pattern']}")
    if _TIPOS["number"](v):
        if v < e.get("minimum", -math.inf) or v > e.get("maximum", math.inf):
            err.append(f"{ruta}: {v} fuera de rango")
        if "exclusiveMinimum" in e and not v > e["exclusiveMinimum"]:
            err.append(f"{ruta}: {v} debe ser > {e['exclusiveMinimum']}")
    if isinstance(v, list):
        if len(v) < e.get("minItems", 0) or len(v) > e.get("maxItems", math.inf):
            err.append(f"{ruta}: {len(v)} elementos fuera de rango")
        if e.get("uniqueItems") and len({_clave_json(x) for x in v}) != len(v):
            err.append(f"{ruta}: elementos repetidos")
        if isinstance(e.get("items"), dict):
            for n, x in enumerate(v):
                err += _validar(x, e["items"], raiz, f"{ruta}[{n}]")
    if isinstance(v, dict):
        props = e.get("properties", {})
        err += [f"{ruta}: falta «{k}»" for k in e.get("required", []) if k not in v]
        if e.get("additionalProperties") is False:
            err += [f"{ruta}: clave no admitida «{k}»" for k in v if k not in props]
        for k, x in v.items():
            if k in props:
                err += _validar(x, props[k], raiz, f"{ruta}.{k}")
    return err


def validar(instancia: object, esquema: dict) -> list[str]:
    """Errores con ruta JSON («$.campos.objetivo.entradas[0].cita: ...»); [] si es válido."""
    if not isinstance(esquema, dict):
        raise IntegridadRota("El esquema no es un objeto", [repr(type(esquema))])
    return _validar(instancia, esquema, esquema, "$")


def exigir(instancia: object, nombre: str, como: type = ReglaIncumplida) -> None:
    """Lanza `como(mensaje, errores)` con TODOS los errores si la instancia no valida."""
    errores = validar(instancia, cargar(nombre))
    if errores:
        raise como(f"{nombre} no valida contra su esquema ({len(errores)} errores)", errores)
