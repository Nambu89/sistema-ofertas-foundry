"""Deriva los json_schema de text.format del experto y del verificador (CONTRATOS.md §14).

En I0 (prueba e) solo se probó en Foundry esta forma: type (cadena, lista con "null", "number",
"object", "array"), enum (con "type": "string" al lado), properties, required,
additionalProperties e items. La versión derivada se queda SOLO con eso:
- se expanden los $ref (#/$defs/...) y se quitan $defs, $schema, $id, title y description;
- se quitan pattern, minLength, maxLength, minimum, maximum, exclusiveMinimum, minItems,
  maxItems, uniqueItems y const;
- un enum de cadenas sin type recibe "type": "string" (forma probada);
- "integer" pasa a "number" (integer no se probó; el código sigue exigiendo entero).
El esquema completo de esquemas/ lo aplica siempre el código: lo derivado solo da la forma.

Uso: .venv/Scripts/python.exe -m agentes.esquemas.derivar_text_format [--comprobar]
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
ORIGEN = RAIZ / "esquemas"
NOMBRES = ("respuesta_experto", "respuesta_verificador")
PROBADAS = {"type", "enum", "properties", "required", "additionalProperties", "items"}
QUITAR = {"$defs", "$schema", "$id", "title", "description", "pattern", "minLength", "maxLength",
          "minimum", "maximum", "exclusiveMinimum", "minItems", "maxItems", "uniqueItems", "const"}


class EsquemaNoDerivable(ValueError):
    """El esquema de origen usa algo que no se sabe derivar sin cambiar su significado."""


def _resolver(ref: str, raiz: dict) -> dict:
    prefijo = "#/$defs/"
    if not ref.startswith(prefijo) or ref[len(prefijo):] not in raiz.get("$defs", {}):
        raise EsquemaNoDerivable(f"$ref no admitido o inexistente: {ref}")
    return raiz["$defs"][ref[len(prefijo):]]


def _tipo(t: object) -> object:
    if isinstance(t, list):
        return ["number" if x == "integer" else x for x in t]
    return "number" if t == "integer" else t


def derivar_nodo(nodo: dict, raiz: dict, pila: tuple[str, ...] = ()) -> dict:
    nodo = dict(nodo)
    if "$ref" in nodo:
        ref = nodo.pop("$ref")
        if ref in pila:
            raise EsquemaNoDerivable(f"$ref recursivo: {ref}")
        base = derivar_nodo(_resolver(ref, raiz), raiz, pila + (ref,))
        resto = derivar_nodo(nodo, raiz, pila) if set(nodo) - QUITAR else {}
        if set(base) & set(resto):
            raise EsquemaNoDerivable(f"$ref {ref} con palabras repetidas al lado: {sorted(set(base) & set(resto))}")
        return {**base, **resto}
    salida: dict = {}
    for k, v in nodo.items():
        if k in QUITAR:
            continue
        if k not in PROBADAS:
            raise EsquemaNoDerivable(f"palabra no probada en text.format: {k}")
        if k == "properties":
            salida[k] = {p: derivar_nodo(s, raiz, pila) for p, s in v.items()}
        elif k == "items":
            salida[k] = derivar_nodo(v, raiz, pila)
        elif k == "type":
            salida[k] = _tipo(v)
        else:
            salida[k] = copy.deepcopy(v)
    if "enum" in salida and "type" not in salida:
        if not all(isinstance(x, str) for x in salida["enum"]):
            raise EsquemaNoDerivable(f"enum no textual sin type: {salida['enum']}")
        salida = {"type": "string", **salida}
    return salida


# VER17-6 (I1.8): valores que el esquema completo aún admite pero que el modelo no debe emitir. El verificador ya no
# recibe líneas de precio (I1.7): fuera `precio` de `tipo` y los campos que solo tenía una línea de precio. El esquema
# completo de esquemas/ no cambia (el código sigue aceptándolos): solo se estrecha la forma que ve el modelo.
RESIDUOS = {"respuesta_verificador": {"tipo": {"precio"},
                                      "campo": {"componente", "filtro", "precio", "unidad", "effectiveStartDate"}}}


def quitar_residuos(nombre: str, esquema: dict) -> dict:
    """Quita de los enum de elementos[] los valores de RESIDUOS. Falla en alto si la ruta ya no existe o si un enum se
    queda vacío (el esquema de origen cambió de forma y el estrechamiento hay que revisarlo)."""
    quitar = RESIDUOS.get(nombre)
    if not quitar:
        return esquema
    props = (((esquema.get("properties") or {}).get("elementos") or {}).get("items") or {}).get("properties")
    if not isinstance(props, dict):
        raise EsquemaNoDerivable(f"{nombre}: no está elementos[].properties para quitar los residuos de VER17-6")
    for campo, valores in quitar.items():
        nodo = props.get(campo)
        if not isinstance(nodo, dict) or not isinstance(nodo.get("enum"), list):
            raise EsquemaNoDerivable(f"{nombre}: elementos[].{campo} ya no es un enum (residuos de VER17-6)")
        nodo["enum"] = [v for v in nodo["enum"] if v not in valores]
        if not nodo["enum"]:
            raise EsquemaNoDerivable(f"{nombre}: elementos[].{campo} se queda sin valores")
    return esquema


def text_format(nombre: str) -> dict:
    raiz = json.loads((ORIGEN / f"{nombre}.json").read_text(encoding="utf-8"))
    return {"type": "json_schema", "name": nombre, "schema": quitar_residuos(nombre, derivar_nodo(raiz, raiz)),
            "strict": True}


def ruta_salida(nombre: str) -> pathlib.Path:
    return AQUI / f"{nombre}.text_format.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deriva los json_schema de text.format.")
    ap.add_argument("--comprobar", action="store_true")
    a = ap.parse_args(argv)
    distintos = 0
    for n in NOMBRES:
        contenido = json.dumps(text_format(n), ensure_ascii=False, indent=2) + "\n"
        ruta = ruta_salida(n)
        actual = ruta.read_text(encoding="utf-8") if ruta.exists() else None
        if actual == contenido:
            print(f"igual      {ruta.relative_to(RAIZ)}")
            continue
        distintos += 1
        if a.comprobar:
            print(f"DISTINTO   {ruta.relative_to(RAIZ)}")
        else:
            ruta.write_text(contenido, encoding="utf-8", newline="\n")
            print(f"escrito    {ruta.relative_to(RAIZ)}")
    return 1 if (a.comprobar and distintos) else 0


if __name__ == "__main__":
    sys.exit(main())
