"""Instantánea de precios al desplegar (I1.7, decisión 1 del comercial, 13-10-2026).

En cada despliegue se descarga de Azure Retail Prices (API pública, EUR, sin credenciales) el precio de TODAS las plantillas
del catálogo y se guarda con su fecha en catalogo/precios_instantanea.json y, byte a byte igual, en
sandbox/datos/precios_instantanea.json. El experto ya no consulta precios (Foundry aborta la ejecución entera ante un 400 o
un 429 de la herramienta, LES-G-090.9): solo elige plantilla y cantidades, y el núcleo pone el precio de aquí.

Cada plantilla tiene que resolver a UN artículo vigente (o a los tramos de un único medidor); si una sola no resuelve, el
guion falla en alto y NO escribe nada (LES-G-091). Pausa entre consultas y espera ante 429 (Retry-After o 30 s).

Uso:
  .venv/Scripts/python.exe -m catalogo.instantanea_precios            # genera y escribe las dos copias
  .venv/Scripts/python.exe -m catalogo.instantanea_precios --comprobar [--fecha-paquete AAAA-MM-DD]
--comprobar no escribe: rc 1 si la instantánea no casa con el catálogo, su huella no cuadra, las dos copias difieren o
tiene más de 31 días en la fecha indicada (por defecto, hoy).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import pathlib
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from catalogo.plantillas_precio import condiciones, divisor_de_unidad

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent
CATALOGO = AQUI / "catalogo_referencias_azure.json"
DESTINOS = (AQUI / "precios_instantanea.json", RAIZ / "sandbox" / "datos" / "precios_instantanea.json")
SCHEMA = "preventa-precios-instantanea/1"
API = "https://prices.azure.com/api/retail/prices"
FUENTE = API + " (currencyCode=EUR, priceType Consumption)"
AGENTE = "Mozilla/5.0 (preventa-foundry instantanea_precios)"
MAX_DIAS = 31
# Campo del filtro → campo del artículo de Retail Prices (priceType se llama «type» en la respuesta).
CAMPO_ARTICULO = {"priceType": "type"}


class ErrorInstantanea(Exception):
    """La instantánea no se puede generar o no es válida: nunca se escribe a medias."""


def clave(catalogo_id: str, plantilla_id: str) -> str:
    """Clave de la plantilla en la instantánea. Los ids de plantilla se repiten entre filas («basic» en AI Search y en SQL
    Database), así que la clave lleva el catalogo_id: «az-ai-search/basic»."""
    return f"{catalogo_id}/{plantilla_id}"


def plantillas(cat: dict) -> list[tuple[str, dict, dict]]:
    """[(clave, fila, plantilla)] de todas las filas con plantillas, en el orden del catálogo; falla si una clave se repite."""
    salida, vistas = [], set()
    for c in cat["componentes"]:
        for p in c.get("plantillas_precio") or []:
            k = clave(c["id"], p["id"])
            if k in vistas:
                raise ErrorInstantanea(f"plantilla repetida en el catálogo: {k}")
            vistas.add(k)
            salida.append((k, c, p))
    return salida


def _canonico(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def huella(inst: dict) -> str:
    """SHA-256 del JSON canónico (claves ordenadas, sin espacios, UTF-8) de la instantánea SIN la clave «sha256»."""
    return hashlib.sha256(_canonico({k: v for k, v in inst.items() if k != "sha256"})).hexdigest()


def _fecha(texto: object) -> datetime.datetime | None:
    try:
        d = datetime.datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def resolver(k: str, filtro: str, items: list[dict], ahora: datetime.datetime) -> dict:
    """Entrada de la instantánea para una plantilla. Falla si no hay artículos, si alguno no casa con el filtro, si hay más
    de un medidor o unidad, si dos artículos vigentes dan precios distintos para el mismo tramo o si un precio no es finito.
    Los artículos con fecha de inicio futura se descartan (no están vigentes) y se cuentan."""
    pares = condiciones(filtro)
    if pares is None:
        raise ErrorInstantanea(f"{k}: el filtro no es una serie de «campo eq 'valor'»")
    if not items:
        raise ErrorInstantanea(f"{k}: 0 artículos")
    for i in items:
        malos = [c for c, v in pares if i.get(CAMPO_ARTICULO.get(c, c)) != v]
        if malos or i.get("currencyCode") != "EUR":
            raise ErrorInstantanea(f"{k}: artículo que no casa con el filtro en {malos or ['currencyCode']}")
    vigentes, futuros = [], 0
    for i in items:
        inicio = _fecha(i.get("effectiveStartDate"))
        if inicio is None:
            raise ErrorInstantanea(f"{k}: effectiveStartDate ilegible {i.get('effectiveStartDate')!r}")
        if inicio > ahora:
            futuros += 1
        else:
            vigentes.append(i)
    if not vigentes:
        raise ErrorInstantanea(f"{k}: ningún artículo vigente ({futuros} con fecha futura)")
    for i in vigentes:  # Revisión I1.7: un tramo ausente o no finito no se convierte en «desde 0»
        tramo = i.get("tierMinimumUnits")
        if isinstance(tramo, bool) or not isinstance(tramo, (int, float)) or not math.isfinite(tramo) or tramo < 0:
            raise ErrorInstantanea(f"{k}: tierMinimumUnits ausente, no numérico o no finito: {tramo!r}")
    unicos = {(i.get("meterId"), i.get("tierMinimumUnits"), i.get("retailPrice"), i.get("unitOfMeasure")): i for i in vigentes}
    medidores = {(i.get("meterId"), i.get("unitOfMeasure")) for i in unicos.values()}
    if len(medidores) != 1:
        raise ErrorInstantanea(f"{k}: {len(medidores)} medidores o unidades distintos: no resuelve a un artículo")
    tramos = sorted(unicos.values(), key=lambda i: float(i["tierMinimumUnits"]))
    desde = [float(i["tierMinimumUnits"]) for i in tramos]
    if len(set(desde)) != len(desde):
        raise ErrorInstantanea(f"{k}: dos precios vigentes distintos para el mismo tramo")
    precios = [i.get("retailPrice") for i in tramos]
    if any(isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or p < 0 for p in precios):
        raise ErrorInstantanea(f"{k}: precio no finito o negativo {precios}")
    if desde[0] != 0:
        raise ErrorInstantanea(f"{k}: el primer tramo empieza en {desde[0]}, no en 0")
    base = tramos[0]
    entrada = {"filtro": filtro, "precio_unitario": precios[0], "unidad": base.get("unitOfMeasure"),
               "effectiveStartDate": max(i.get("effectiveStartDate") for i in tramos), "meterName": base.get("meterName"),
               "productName": base.get("productName"), "skuName": base.get("skuName"),
               "armRegionName": base.get("armRegionName"), "meterId": base.get("meterId"),
               "articulos_devueltos": len(items), "articulos_futuros_descartados": futuros,
               "sha256_articulo": hashlib.sha256(_canonico(tramos)).hexdigest()}
    if len(tramos) > 1:
        entrada["tramos"] = [{"desde": d, "precio_unitario": p} for d, p in zip(desde, precios)]
    return entrada


def consultar(filtro: str, notas: list[str], pausa: float = 1.6, max_429: int = 6) -> list[dict]:
    """Items de una consulta EUR. 429: espera Retry-After (o 30 s) hasta `max_429` veces, anotado; DNS: un reintento
    anotado. Cualquier otro HTTP, un NextPageLink o un cuerpo ilegible fallan en alto."""
    url = API + "?" + urllib.parse.urlencode({"currencyCode": "EUR", "$filter": filtro})
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    esperas, dns = 0, 0
    while True:
        time.sleep(pausa)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and esperas < max_429:
                esperas += 1
                try:
                    espera = min(max(float(e.headers.get("Retry-After") or 30), 1.0), 120.0)
                except ValueError:
                    espera = 30.0
                notas.append(f"429 (espera {esperas}/{max_429} de {espera:.0f} s): {filtro}")
                time.sleep(espera)
                continue
            raise ErrorInstantanea(f"HTTP {e.code} de Retail Prices: {filtro}") from e
        except urllib.error.URLError as e:
            if dns == 0 and isinstance(e.reason, socket.gaierror):
                dns += 1
                notas.append(f"DNS {e.reason!r}; reintento único tras 3 s: {filtro}")
                time.sleep(3)
                continue
            raise ErrorInstantanea(f"red: {e.reason!r}: {filtro}") from e
        except (ValueError, TimeoutError, OSError) as e:
            raise ErrorInstantanea(f"respuesta ilegible o sin respuesta ({e!r}): {filtro}") from e
    if d.get("NextPageLink"):
        raise ErrorInstantanea(f"la respuesta trae NextPageLink (el filtro no es de un solo medidor): {filtro}")
    items = d.get("Items")
    if not isinstance(items, list):
        raise ErrorInstantanea(f"respuesta sin lista Items: {filtro}")
    return items


def generar(cat: dict, consulta=consultar, ahora: datetime.datetime | None = None, notas: list[str] | None = None) -> dict:
    """Instantánea completa en memoria. Consulta todas las plantillas y, si alguna falla, lanza ErrorInstantanea con TODOS
    los fallos (no se escribe nada)."""
    notas = [] if notas is None else notas
    entradas, fallos = {}, []
    for k, _c, p in plantillas(cat):
        try:
            momento = ahora or datetime.datetime.now(datetime.timezone.utc)
            entradas[k] = resolver(k, p["filtro"], consulta(p["filtro"], notas), momento)
        except ErrorInstantanea as e:
            fallos.append(str(e))
    if fallos:
        raise ErrorInstantanea(f"{len(fallos)} de {len(entradas) + len(fallos)} plantillas no resuelven:\n- "
                               + "\n- ".join(fallos))
    fin = ahora or datetime.datetime.now(datetime.timezone.utc)
    inst = {"schema": SCHEMA, "fecha_consulta": fin.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "moneda": "EUR", "fuente": FUENTE, "catalogo_version": cat.get("version"), "plantillas": entradas}
    inst["sha256"] = huella(inst)
    return inst


def problemas(inst: object, cat: dict, fecha_paquete: datetime.date | None = None, max_dias: int = MAX_DIAS) -> list[str]:
    """Motivos por los que la instantánea no vale para este catálogo (y, con `fecha_paquete`, para un paquete de esa fecha:
    más de `max_dias` días o posterior al paquete). [] si vale. Es la comprobación que replican el núcleo y la puerta."""
    if not isinstance(inst, dict):
        return ["la instantánea no es un objeto JSON"]
    m = []
    if inst.get("schema") != SCHEMA or inst.get("moneda") != "EUR":
        m.append("schema o moneda distintos de los esperados")
    if inst.get("sha256") != huella(inst):
        m.append("la huella sha256 no cuadra con el contenido")
    fecha = _fecha(inst.get("fecha_consulta"))
    if fecha is None:
        m.append(f"fecha_consulta ilegible: {inst.get('fecha_consulta')!r}")
    elif fecha_paquete is not None:
        dias = (fecha_paquete - fecha.date()).days
        if dias < 0:
            m.append(f"la instantánea ({fecha.date()}) es posterior al paquete ({fecha_paquete})")
        elif dias > max_dias:
            m.append(f"la instantánea tiene {dias} días en la fecha del paquete ({fecha_paquete}): máximo {max_dias}")
    ps = inst.get("plantillas") if isinstance(inst.get("plantillas"), dict) else {}
    esperadas = {k: p for k, _c, p in plantillas(cat)}
    for k in sorted(set(esperadas) - set(ps)):
        m.append(f"falta la plantilla {k}")
    for k in sorted(set(ps) - set(esperadas)):
        m.append(f"plantilla {k} que no está en el catálogo")
    for k in sorted(set(ps) & set(esperadas)):
        e, p = ps[k], esperadas[k]
        precio = e.get("precio_unitario") if isinstance(e, dict) else None
        if not isinstance(e, dict) or e.get("filtro") != p["filtro"]:
            m.append(f"{k}: el filtro no es el del catálogo")
        elif isinstance(precio, bool) or not isinstance(precio, (int, float)) or not math.isfinite(precio) or precio < 0:
            m.append(f"{k}: precio_unitario no válido {precio!r}")
        elif divisor_de_unidad(e.get("unidad")) != p.get("divisor"):
            m.append(f"{k}: la unidad «{e.get('unidad')}» no da el divisor {p.get('divisor')} de la plantilla")
        elif "tramos" in e and not _tramos_validos(e["tramos"], precio):
            m.append(f"{k}: tramos no válidos (2 o más, el primero desde 0 con el precio_unitario, crecientes y finitos)")
    return m


def _finito(x: object, minimo: float = 0) -> bool:
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x) and x >= minimo


def _tramos_validos(tramos: object, precio: float) -> bool:
    if not isinstance(tramos, list) or len(tramos) < 2 or not all(isinstance(x, dict) for x in tramos):
        return False
    desde = [x.get("desde") for x in tramos]
    precios = [x.get("precio_unitario") for x in tramos]
    return (all(_finito(d) for d in desde) and all(_finito(p) for p in precios) and desde[0] == 0
            and precios[0] == precio and all(b > a for a, b in zip(desde, desde[1:])))


def serializar(inst: dict) -> str:
    return json.dumps(inst, ensure_ascii=False, indent=2) + "\n"


def escribir(inst: dict, cat: dict, destinos: tuple[pathlib.Path, ...] | None = None) -> None:
    """Escribe las copias solo si la instantánea vale para el catálogo; primero a temporales y después con os.replace,
    y relee cada copia para comprobar que es byte a byte igual."""
    destinos = DESTINOS if destinos is None else destinos
    fallos = problemas(inst, cat)
    if fallos:
        raise ErrorInstantanea("no se escribe: " + "; ".join(fallos))
    datos = serializar(inst).encode("utf-8")
    previos = {d: d.read_bytes() if d.exists() else None for d in destinos}
    temporales = []
    try:
        for d in destinos:
            t = d.with_name(d.name + ".tmp")
            t.write_bytes(datos)
            temporales.append((t, d))
        for t, d in temporales:
            os.replace(t, d)
    except OSError as e:  # Revisión I1.7: nunca dos copias distintas; se deja todo como estaba
        for t, _d in temporales:
            t.unlink(missing_ok=True)
        for d, previo in previos.items():
            if previo is None:
                d.unlink(missing_ok=True)
            else:
                d.write_bytes(previo)
        raise ErrorInstantanea(f"no se pudo escribir la instantánea ({e!r}); se restauraron las copias anteriores") from e
    for d in destinos:
        if d.read_bytes() != datos:
            raise ErrorInstantanea(f"la copia {d} no es igual byte a byte")


def comprobar(cat: dict, fecha_paquete: datetime.date, destinos: tuple[pathlib.Path, ...] | None = None) -> list[str]:
    """Lo que dice --comprobar: las dos copias existen, son iguales byte a byte y la instantánea vale en esa fecha."""
    destinos = DESTINOS if destinos is None else destinos
    if not all(d.exists() for d in destinos):
        return [f"falta {d}" for d in destinos if not d.exists()]
    contenidos = [d.read_bytes() for d in destinos]
    m = [] if len(set(contenidos)) == 1 else ["las copias de la instantánea no son iguales byte a byte"]
    try:
        inst = json.loads(contenidos[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return m + [f"instantánea ilegible: {e}"]
    return m + problemas(inst, cat, fecha_paquete)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Instantánea de precios de todas las plantillas del catálogo (EUR).")
    ap.add_argument("--comprobar", action="store_true", help="no consulta ni escribe: valida las copias guardadas")
    ap.add_argument("--fecha-paquete", type=datetime.date.fromisoformat, default=None,
                    help="fecha con la que se juzga la antigüedad (por defecto, hoy en UTC)")
    ap.add_argument("--pausa", type=float, default=1.6, help="segundos entre consultas (Retail Prices limita con 429)")
    a = ap.parse_args(argv)
    if not 0 <= a.pausa <= 60 or not math.isfinite(a.pausa):
        ap.error("--pausa entre 0 y 60")
    cat = json.loads(CATALOGO.read_text(encoding="utf-8"))
    if a.comprobar:
        fecha = a.fecha_paquete or datetime.datetime.now(datetime.timezone.utc).date()
        fallos = comprobar(cat, fecha)
        print("\n".join(f"FALLA {x}" for x in fallos) or f"instantánea válida para el catálogo v{cat.get('version')} el {fecha}")
        return 1 if fallos else 0
    notas: list[str] = []
    try:
        inst = generar(cat, lambda f, n: consultar(f, n, a.pausa), notas=notas)
        escribir(inst, cat)
    except (ErrorInstantanea, OSError) as e:  # Revisión I1.7: un fallo de disco al restaurar también da rc 2
        print("\n".join(notas))
        print(f"NO SE ESCRIBE NADA: {e}")
        return 2
    print("\n".join(notas))
    n = len(inst["plantillas"])
    con_tramos = sum(1 for e in inst["plantillas"].values() if "tramos" in e)
    print(f"escrita: {n} plantillas ({con_tramos} con tramos), fecha_consulta {inst['fecha_consulta']}, "
          f"sha256 {inst['sha256']}, esperas por 429 o DNS: {len(notas)}")
    for d in DESTINOS:
        print(f"  {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
