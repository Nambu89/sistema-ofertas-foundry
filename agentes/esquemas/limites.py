"""Bloque «Límites que comprueba el código» de las instrucciones del experto y del verificador.

El text.format derivado no lleva maxItems, maxLength, minimum ni pattern (no probados en Foundry, §14),
así que el modelo no los ve; el código sí los aplica con el esquema completo. La prueba de contrato
real del 08-10-2026 lo demostró: el experto devolvió 10 `hechos` en un supuesto y el esquema admite 6
(LES-G-088). Este bloque se genera desde esquemas/ para que las instrucciones no se desincronicen.
En las del experto genera además el bloque «productName del filtro, servicio a servicio» desde el catálogo
(EB-5, I1.4). Uso: python -m agentes.esquemas.limites [--comprobar]
"""
from __future__ import annotations

import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
INICIO = "### Límites que comprueba el código (generado por agentes/esquemas/limites.py; no editar a mano)"
FIN = "### Fin de los límites"
DESTINOS = {RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md": ("respuesta_experto", "## 10. Formato de respuesta"),
            RAIZ / "agentes" / "instrucciones" / "verificador_i1.md": ("respuesta_verificador", "## 6. Formato de respuesta")}


def _rango(n: dict, a: str, b: str, unidad: str) -> str | None:
    lo, hi = n.get(a), n.get(b)
    if lo is None and hi is None:
        return None
    if lo is not None and hi is not None:
        return f"entre {lo} y {hi}{unidad}"
    return f"como mínimo {lo}{unidad}" if lo is not None else f"como mucho {hi}{unidad}"


def lineas(nodo: dict, raiz: dict, ruta: str = "") -> list[str]:
    if "$ref" in nodo:
        nodo = {**raiz["$defs"][nodo["$ref"].split("/")[-1]], **{k: v for k, v in nodo.items() if k != "$ref"}}
    partes = [p for p in (_rango(nodo, "minItems", "maxItems", " elementos"),
                          _rango(nodo, "minLength", "maxLength", " caracteres"),
                          _rango(nodo, "minimum", "maximum", "")) if p]
    if "pattern" in nodo:
        partes.append(f"con el formato `{nodo['pattern']}`")
    salida = [f"- `{ruta or '$'}`: {'; '.join(partes)}."] if partes else []
    for k, sub in (nodo.get("properties") or {}).items():
        salida += lineas(sub, raiz, f"{ruta}.{k}" if ruta else k)
    if isinstance(nodo.get("items"), dict):
        salida += lineas(nodo["items"], raiz, f"{ruta}[]")
    return salida


def bloque(nombre: str) -> str:
    esquema = json.loads((RAIZ / "esquemas" / f"{nombre}.json").read_text(encoding="utf-8"))
    cuerpo = ["Si tu JSON incumple cualquiera de estos límites, el código rechaza la respuesta entera y cuenta un "
              "intento fallido. Respétalos aunque el formato de salida no los exprese:"] + lineas(esquema, esquema)
    return "\n".join([INICIO, *cuerpo, FIN])


def _sustituir(texto: str, inicio: str, fin: str, nuevo: str, ancla: str) -> str:
    """Sustituye el bloque entre `inicio` y `fin` (incluidos) por `nuevo`; si no está, lo inserta antes de `ancla`."""
    if inicio in texto:
        antes, resto = texto.split(inicio, 1)
        if fin not in resto:
            raise SystemExit(f"Falta el cierre «{fin}»")
        return antes + nuevo + resto.split(fin, 1)[1]
    if ancla not in texto:
        raise SystemExit(f"No está el ancla «{ancla}»")
    return texto.replace(ancla, nuevo + "\n\n" + ancla, 1)


def insertar(texto: str, nombre: str, ancla: str) -> str:
    return _sustituir(texto, INICIO, FIN, bloque(nombre), ancla)


# EB-5 (I1.4): en E2E-B el experto puso productName en dos servicios cuya celda es «—» (Microsoft Foundry y Azure
# Functions). La regla ya estaba en prosa; ahora va servicio a servicio, generada desde el catálogo con la misma lógica
# que nucleo.experto.problemas_precio (productName obligatorio si el serviceName se repite en el catálogo).
INICIO_PN = ("### productName del filtro, servicio a servicio (generado por agentes/esquemas/limites.py desde el "
             "catálogo; no editar a mano)")
FIN_PN = "### Fin del productName"
DESTINO_PN = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md", "- Si la respuesta trae `NextPageLink`")
CATALOGO = RAIZ / "sandbox" / "datos" / "catalogo_componentes.json"


def grupos_product_name(catalogo: dict) -> dict[str, list[str]]:
    """{"obligatorio": [...], "opcional": [...], "ninguno": [...]}: un texto por servicio con precio en Retail Prices."""
    entradas = [e for e in catalogo.get("componentes") or [] if isinstance(e, dict) and e.get("service_name_precios")]
    grupos: dict[str, list[str]] = {"obligatorio": [], "opcional": [], "ninguno": []}
    for e in entradas:
        sn, pp = e["service_name_precios"], e.get("producto_precios")
        compartido = sum(x["service_name_precios"] == sn for x in entradas) > 1
        if pp:
            grupos["obligatorio" if compartido else "opcional"].append(f"{e['nombre_oficial']} → `{pp}`")
        else:
            grupos["ninguno"].append(e["nombre_oficial"])
    for a in catalogo.get("precios_auxiliares") or []:
        if isinstance(a, dict) and a.get("service_name"):
            productos = [x for x in a.get("productos") or [] if isinstance(x, str) and x]
            if productos:
                grupos["opcional"].append(f"el precio auxiliar con serviceName `{a['service_name']}` → "
                                          + " o ".join(f"`{x}`" for x in productos))
            else:
                grupos["ninguno"].append(f"el precio auxiliar con serviceName `{a['service_name']}`")
    return grupos


def bloque_product_name(catalogo: dict) -> str:
    g = grupos_product_name(catalogo)
    return "\n".join([
        INICIO_PN,
        "El `productName` del filtro sale de esta lista, nunca de los artículos que devuelve Retail Prices. Si el "
        "servicio está en «Sin productName», tu filtro NO lleva `productName` aunque los artículos traigan uno (por "
        "ejemplo «Azure OpenAI GPT5» en Microsoft Foundry o «Flex Consumption» en Azure Functions): para elegir el "
        "artículo usa `skuName`, `armSkuName` o `meterName`. Un `productName` que no sea el de la lista hace que el "
        "código rechace la respuesta entera.",
        "- Con `productName` obligatorio (exactamente este valor): " + "; ".join(g["obligatorio"]) + ".",
        "- Con `productName` opcional (si lo pones, exactamente este valor): " + "; ".join(g["opcional"]) + ".",
        "- Sin `productName`: " + "; ".join(g["ninguno"]) + ".",
        FIN_PN])


def insertar_product_name(texto: str, catalogo: dict) -> str:
    return _sustituir(texto, INICIO_PN, FIN_PN, bloque_product_name(catalogo), DESTINO_PN[1])


def main(argv: list[str] | None = None) -> int:
    comprobar = "--comprobar" in (argv if argv is not None else sys.argv[1:])
    rc = 0
    catalogo = json.loads(CATALOGO.read_text(encoding="utf-8"))
    for ruta, (nombre, ancla) in DESTINOS.items():
        actual = ruta.read_text(encoding="utf-8")
        nuevo = insertar(actual, nombre, ancla)
        # I1.7 (decisión 1, papel E): el experto ya no escribe filtros de precio; el bloque de productName ya no va.
        if INICIO_PN in nuevo:
            raise SystemExit("Las instrucciones siguen llevando el bloque de productName (anterior a I1.7)")
        if comprobar:
            print(f"{'igual' if nuevo == actual else 'DESINCRONIZADO'} {ruta.name}")
            rc |= nuevo != actual
        elif nuevo != actual:
            ruta.write_text(nuevo, encoding="utf-8", newline="\n")
            print(f"escrito {ruta.name}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
