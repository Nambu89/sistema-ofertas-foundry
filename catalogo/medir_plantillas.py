"""Comprueba en red cada plantilla de filtro de precio del catálogo (solo GET a la API pública, sin credenciales).

Por plantilla: N consultas reales en EUR (3 por defecto) y una en USD. Falla si alguna no da HTTP 200, si devuelve 0
artículos, más de un medidor, más de 5 artículos, NextPageLink, otro serviceName u otra región, resultados distintos
entre consultas, precio 0 sin estar declarada gratuita o un precio en EUR desviado más de un 5 % del de USD por el
redondeo a 4 decimales (LES-G-047: un precio falso es peor que ninguno). Anota los reintentos (429 y DNS).
Uso: .venv/Scripts/python.exe -m catalogo.medir_plantillas [--escribir] [--evidencia RUTA] [--consultas 3]
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import socket
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from catalogo.plantillas_precio import concepto, condiciones, problemas_impulsor, problemas_plantilla

AQUI = pathlib.Path(__file__).resolve().parent
CATALOGO = AQUI / "catalogo_referencias_azure.json"
API = "https://prices.azure.com/api/retail/prices"
AGENTE = "Mozilla/5.0 (preventa-foundry medir_plantillas)"
MAX_ARTICULOS, DESVIO_MAX = 5, 0.05


def consultar(filtro: str, moneda: str, notas: list[str], pausa: float) -> tuple[int, int, list[dict], bool]:
    """(http, bytes, Items, hay NextPageLink). 429: espera Retry-After (o 20 s), hasta 3 veces; DNS: un reintento."""
    url = API + "?" + urllib.parse.urlencode({"currencyCode": moneda, "$filter": filtro})
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    for intento in range(1, 5):
        time.sleep(pausa)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                cuerpo = r.read()
            d = json.loads(cuerpo)
            return r.status, len(cuerpo), d.get("Items") or [], bool(d.get("NextPageLink"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento < 4:
                espera = float(e.headers.get("Retry-After") or 20)
                notas.append(f"429 de Retail Prices ({moneda}, intento {intento}); espera de {espera:.0f} s: {filtro}")
                time.sleep(espera)
                continue
            return e.code, 0, [], False
        except urllib.error.URLError as e:
            if intento == 1 and isinstance(e.reason, socket.gaierror):
                notas.append(f"DNS {e.reason!r}; reintento único tras 3 s: {filtro}")
                time.sleep(3)
                continue
            raise
    raise RuntimeError("inalcanzable")


def _firma(items: list[dict]) -> list[tuple]:
    return sorted((i.get("meterId"), i.get("retailPrice"), i.get("tierMinimumUnits")) for i in items)


def medir(plantilla: dict, entrada: dict, n: int, notas: list[str], pausa: float) -> dict:
    """Resultado de una plantilla: comprobacion (lo que se guarda en el catálogo), ratios EUR/USD y errores."""
    d = dict(condiciones(plantilla["filtro"]) or [])
    errores = problemas_plantilla(plantilla, entrada)
    tandas = [consultar(plantilla["filtro"], "EUR", notas, pausa) for _ in range(n)]
    for http, _, items, sigue in tandas:
        if http != 200 or not items:
            errores.append(f"HTTP {http}, {len(items)} artículos")
        if sigue:
            errores.append("trae NextPageLink")
    items = tandas[0][2]
    if len({json.dumps(_firma(t[2])) for t in tandas}) != 1:
        errores.append("las consultas devuelven artículos distintos")
    medidores = {(i.get("productName"), i.get("skuName"), i.get("meterName"), i.get("unitOfMeasure")) for i in items}
    if len(medidores) > 1 or len(items) > MAX_ARTICULOS:
        errores.append(f"{len(medidores)} medidores y {len(items)} artículos: no es un medidor único")
    if any(i.get("serviceName") != d.get("serviceName") or i.get("armRegionName") != d.get("armRegionName")
           for i in items):
        errores.append("algún artículo es de otro serviceName u otra región")
    precios = [i.get("retailPrice") for i in sorted(items, key=lambda i: i.get("tierMinimumUnits") or 0)]
    if items and bool(plantilla.get("gratuito")) != all(p == 0 for p in precios):
        errores.append(f"precios {precios} y gratuito={bool(plantilla.get('gratuito'))}: no casan")
    http_u, _, usd, _ = consultar(plantilla["filtro"], "USD", notas, pausa)
    por_tramo = {i.get("tierMinimumUnits"): i.get("retailPrice") for i in usd}
    ratios = [(i.get("retailPrice"), por_tramo.get(i.get("tierMinimumUnits"))) for i in items]
    k = items[0] if items else {}
    comprobacion = {"fecha": datetime.date.today().isoformat(), "consultas": n, "articulos": len(items),
                    "bytes": [t[1] for t in tandas], "medidor": k.get("meterName"), "producto": k.get("productName"),
                    "unidad": k.get("unitOfMeasure"), "precios_eur": precios,
                    "tramos": sorted(i.get("tierMinimumUnits") for i in items), "sku": k.get("skuName")}
    # I1.6: el divisor y el impulsor se contrastan con la unidad medida HOY, y el concepto se tiene que poder derivar.
    errores += [e for e in problemas_impulsor({**plantilla, "comprobacion": comprobacion}) if e not in errores]
    try:
        concepto({**plantilla, "comprobacion": comprobacion})
    except ValueError as e:
        errores.append(str(e))
    return {"comprobacion": comprobacion, "ratios": ratios, "http_usd": http_u, "errores": errores}


def desvios(resultados: list[dict]) -> float | None:
    """Tipo EUR/USD implícito (mediana de los precios de 0,01 o más) y marca el desvío por redondeo de cada plantilla."""
    muestras = [e / u for r in resultados for e, u in r["ratios"] if u and e and e >= 0.01]
    if not muestras:  # sin tipo no se puede contrastar el redondeo: falla en alto, no se da por bueno
        for r in resultados:
            r["errores"].append("sin precios de 0,01 o más no hay tipo EUR/USD implícito para contrastar el redondeo")
        return None
    tipo = statistics.median(muestras)
    for r in resultados:
        for e, u in r["ratios"]:
            if u is None:
                r["errores"].append("sin el mismo tramo en USD para contrastar el redondeo")
            elif u > 0 and abs(e - u * tipo) > DESVIO_MAX * u * tipo:
                r["errores"].append(f"EUR {e} frente a USD {u} × {tipo:.4f}: redondeo de más del 5 %")
    return tipo


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escribir", action="store_true", help="guarda la comprobación de cada plantilla en el catálogo")
    ap.add_argument("--evidencia", type=pathlib.Path)
    ap.add_argument("--consultas", type=int, default=3)
    ap.add_argument("--pausa", type=float, default=1.5, help="segundos entre consultas (Retail Prices limita: 429)")
    ap.add_argument("--solo", default="", help="ids de componente separados por comas (I1.6): mide y escribe solo esos")
    a = ap.parse_args(argv)
    if a.consultas < 1 or not 0 <= a.pausa <= 60:
        ap.error("--consultas >= 1 y --pausa entre 0 y 60")
    cat = json.loads(CATALOGO.read_text(encoding="utf-8"))
    notas: list[str] = []
    resultados = []
    solo = {s for s in a.solo.split(",") if s}
    if solo - {c["id"] for c in cat["componentes"]}:
        ap.error(f"--solo con ids que no están en el catálogo: {sorted(solo - {c['id'] for c in cat['componentes']})}")
    for c in cat["componentes"]:
        if solo and c["id"] not in solo:
            continue
        for p in c.get("plantillas_precio") or []:
            r = medir(p, c, a.consultas, notas, a.pausa)
            resultados.append({"componente": c["id"], "plantilla": p["id"], "filtro": p["filtro"], **r})
    tipo = desvios(resultados) if resultados else None
    fallos = 0
    for r in resultados:
        k = r["comprobacion"]
        fallos += bool(r["errores"])
        print(f"{'OK   ' if not r['errores'] else 'FALLA'} {r['componente']}/{r['plantilla']}: artículos={k['articulos']} "
              f"bytes={k['bytes']} precios={k['precios_eur']} {k['unidad']} {'; '.join(r['errores'])}")
    if a.escribir and not fallos:
        por_id = {(r["componente"], r["plantilla"]): r["comprobacion"] for r in resultados}
        for c in cat["componentes"]:
            for p in c.get("plantillas_precio") or []:
                if (c["id"], p["id"]) in por_id:
                    p["comprobacion"] = por_id[(c["id"], p["id"])]
        CATALOGO.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    elif a.escribir:
        print("no se escribe el catálogo: hay plantillas que fallan")
    if a.evidencia:
        a.evidencia.parent.mkdir(parents=True, exist_ok=True)
        a.evidencia.write_text(json.dumps({"fecha": datetime.date.today().isoformat(), "consultas": a.consultas,
                                           "tipo_eur_usd_implicito": tipo, "reintentos": notas, "fallos": fallos,
                                           "resultados": resultados}, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8", newline="\n")
    total = sum(sum(r["comprobacion"]["bytes"]) for r in resultados)
    print(f"plantillas={len(resultados)} fallos={fallos} consultas_eur={len(resultados) * a.consultas} "
          f"bytes_eur_total={total} reintentos={len(notas)} tipo_eur_usd={tipo}")
    return 1 if fallos or not resultados else 0


if __name__ == "__main__":
    sys.exit(main())
