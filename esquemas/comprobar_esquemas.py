"""Comprueba los esquemas de I1 y sus ejemplos (CONTRATOS.md §12).

1. Cada esquema es JSON válido y solo usa las palabras clave admitidas.
2. Los esquemas de respuesta de agente son compatibles con text.format strict: en cada objeto,
   todas las propiedades en required y additionalProperties false.
3. Cada ejemplo de esquemas/ejemplos/<nombre>.json valida contra esquemas/<nombre>.json.

Es una referencia del subconjunto, no el validador del sandbox (ese es nucleo/esquema.py, de A).
Uso: python esquemas/comprobar_esquemas.py   (rc 0 si todo pasa, 1 si algo falla)
"""
from __future__ import annotations

import json
import math
import pathlib
import re
import sys

DIR = pathlib.Path(__file__).resolve().parent
ADMITIDAS = {
    "$schema", "$id", "title", "description", "type", "properties", "required",
    "additionalProperties", "items", "minItems", "maxItems", "uniqueItems", "enum", "const",
    "minLength", "maxLength", "pattern", "minimum", "maximum", "exclusiveMinimum", "$defs", "$ref",
}
ESTRICTOS = ("respuesta_experto", "respuesta_verificador")
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


def _igual(a: object, b: object) -> bool:
    """Igualdad JSON: un booleano nunca es igual a un número."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return a == b


def _clave_json(x: object) -> str:
    """Clave de igualdad JSON para uniqueItems: 1 y 1.0 son el mismo valor; true no es 1."""
    def norm(y: object) -> object:
        if isinstance(y, bool) or y is None or isinstance(y, str):
            return [type(y).__name__, y]
        if isinstance(y, (int, float)):
            return ["num", int(y) if float(y).is_integer() else y]
        if isinstance(y, list):
            return [norm(z) for z in y]
        return {k: norm(z) for k, z in y.items()}
    return json.dumps(norm(x), sort_keys=True)


def patron(p: str) -> re.Pattern:
    """Compila un pattern: un «$» final pasa a «\\Z» (en Python «$» casa antes de un salto final)."""
    if p.endswith("$") and not p.endswith("\\$"):
        p = p[:-1] + r"\Z"
    return re.compile(p)


def palabras_no_admitidas(nodo: object, ruta: str = "$") -> list[str]:
    """Palabras clave fuera del subconjunto (recorre properties y $defs como mapas de esquemas)."""
    if not isinstance(nodo, dict):
        return []
    err = [f"{ruta}: palabra clave no admitida «{k}»" for k in nodo if k not in ADMITIDAS]
    if "additionalProperties" in nodo and not isinstance(nodo["additionalProperties"], bool):
        err.append(f"{ruta}: additionalProperties solo admite booleanos en el subconjunto")
    if "items" in nodo and not isinstance(nodo["items"], dict):
        err.append(f"{ruta}: items solo admite un esquema (objeto) en el subconjunto")
    ref = nodo.get("$ref")
    if ref is not None and not (isinstance(ref, str) and re.fullmatch(r"#/\$defs/[A-Za-z0-9_]+", ref)):
        err.append(f"{ruta}: $ref solo admite #/$defs/<nombre> sin escapes: {ref!r}")
    for k in ("properties", "$defs"):
        for nombre, sub in nodo.get(k, {}).items():
            err += palabras_no_admitidas(sub, f"{ruta}.{k}.{nombre}")
    if isinstance(nodo.get("items"), dict):
        err += palabras_no_admitidas(nodo["items"], f"{ruta}.items")
    return err


def no_estricto(nodo: object, ruta: str = "$") -> list[str]:
    """Objetos que no cumplen text.format strict."""
    if not isinstance(nodo, dict):
        return []
    err = []
    if "properties" in nodo:
        if nodo.get("additionalProperties") is not False:
            err.append(f"{ruta}: falta additionalProperties false")
        if set(nodo.get("required", [])) != set(nodo["properties"]):
            err.append(f"{ruta}: required no contiene todas las propiedades")
    for k in ("properties", "$defs"):
        for nombre, sub in nodo.get(k, {}).items():
            err += no_estricto(sub, f"{ruta}.{k}.{nombre}")
    if isinstance(nodo.get("items"), dict):
        err += no_estricto(nodo["items"], f"{ruta}.items")
    return err


def validar(v: object, e: dict, raiz: dict, ruta: str = "$") -> list[str]:
    """Valida v contra e (subconjunto §12). Las palabras de cada tipo solo aplican a ese tipo."""
    if "$ref" in e:
        ref = e["$ref"]
        if not ref.startswith("#/$defs/"):
            return [f"{ruta}: $ref no admitida {ref}"]
        destino = raiz.get("$defs", {}).get(ref[len("#/$defs/"):])
        if not isinstance(destino, dict):
            return [f"{ruta}: $ref apunta a una definición inexistente {ref}"]
        err = validar(v, destino, raiz, ruta)
        resto = {k: x for k, x in e.items() if k != "$ref"}
        return err + (validar(v, resto, raiz, ruta) if resto else [])
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
        if "pattern" in e and not patron(e["pattern"]).search(v):
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
        for n, x in enumerate(v):
            if isinstance(e.get("items"), dict):
                err += validar(x, e["items"], raiz, f"{ruta}[{n}]")
    if isinstance(v, dict):
        props = e.get("properties", {})
        err += [f"{ruta}: falta «{k}»" for k in e.get("required", []) if k not in v]
        if e.get("additionalProperties") is False:
            err += [f"{ruta}: clave no admitida «{k}»" for k in v if k not in props]
        for k, x in v.items():
            if k in props:
                err += validar(x, props[k], raiz, f"{ruta}.{k}")
    return err


def main() -> int:
    fallos = 0
    for ruta in sorted(DIR.glob("*.json")):
        esquema = json.loads(ruta.read_text(encoding="utf-8"))
        err = palabras_no_admitidas(esquema)
        if ruta.stem in ESTRICTOS:
            err += no_estricto(esquema)
        ejemplo = DIR / "ejemplos" / ruta.name
        if not ejemplo.exists():
            err.append("falta el ejemplo en esquemas/ejemplos/")
        else:
            err += validar(json.loads(ejemplo.read_text(encoding="utf-8")), esquema, esquema)
        print(f"{'OK   ' if not err else 'FALLA'} {ruta.name}")
        for x in err:
            print(f"      - {x}")
        fallos += bool(err)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
