"""Comprueba en red el catálogo de referencias Azure (solo GET, sin credenciales).

Por cada componente:
- la URL de Learn (referencia_url o, si no hay, referencia_url_propuesta) responde HTTP 200, no
  redirige a otra ruta y su <title> no es una página de error (soft 404);
- el serviceName (y el productName, si lo hay) devuelve al menos un precio en Azure Retail Prices
  en EUR.

Uso (desde C:/demos/preventa-foundry):
    .venv/Scripts/python.exe -m catalogo.comprobar_catalogo [--escribir] [--evidencia RUTA]
--escribir actualiza el bloque comprobacion de cada entrada con el resultado de hoy.
rc 0 si todo pasa; rc 1 si falla algo (y nada se da por bueno en silencio, LES-G-091).
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import pathlib
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

AQUI = pathlib.Path(__file__).resolve().parent
CATALOGO = AQUI / "catalogo_referencias_azure.json"
PRECIOS = "https://prices.azure.com/api/retail/prices"
AGENTE = "Mozilla/5.0 (preventa-foundry comprobar_catalogo)"
SOFT_404 = re.compile(r"(?i)\b404\b|not found|no se encuentra|no encontrad|page isn.t available")
_IDIOMA = re.compile(r"^/[a-z]{2}-[a-z]{2}(?=/)")


def ruta_normalizada(url: str) -> str:
    """Ruta de Learn sin idioma, en minúsculas y sin barra final (CONTRATOS.md §6.3)."""
    p = urllib.parse.urlsplit(url)
    return _IDIOMA.sub("", p.path.lower()).rstrip("/")


def _get(url: str, reintentos: list[str]) -> tuple[int, str, bytes]:
    """GET con un único reintento ante fallo de DNS, anotado (regla de DNS intermitente)."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    for intento in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.status, r.geturl(), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.geturl() or url, b""
        except urllib.error.URLError as e:
            if intento == 1 and isinstance(e.reason, socket.gaierror):
                reintentos.append(f"{url}: {e.reason!r}; reintento único tras 3 s")
                time.sleep(3)
                continue
            raise
    raise RuntimeError("inalcanzable")


def comprobar_url(url: str, reintentos: list[str]) -> dict:
    estado, final, cuerpo = _get(url, reintentos)
    m = re.search(rb"<title[^>]*>(.*?)</title>", cuerpo, re.S | re.I)
    titulo = " ".join(html.unescape(m.group(1).decode("utf-8", "replace")).split()) if m else None
    errores = []
    if estado != 200:
        errores.append(f"HTTP {estado}")
    host = lambda u: (urllib.parse.urlsplit(u).hostname or "").lower()
    if host(final) != host(url) or ruta_normalizada(final) != ruta_normalizada(url):
        errores.append(f"redirige a {final}")
    if not titulo:
        errores.append("sin <title>")
    elif SOFT_404.search(titulo):
        errores.append(f"soft 404: {titulo!r}")
    return {"url": url, "http": estado, "final": final, "titulo": titulo, "errores": errores}


def comprobar_precio(service: str, producto: str | None, reintentos: list[str]) -> dict:
    filtro = f"serviceName eq '{service}'" + (f" and productName eq '{producto}'" if producto else "")
    url = PRECIOS + "?" + urllib.parse.urlencode({"currencyCode": "EUR", "$filter": filtro})
    estado, _, cuerpo = _get(url, reintentos)
    items = len(json.loads(cuerpo).get("Items", [])) if estado == 200 else None
    errores = [] if estado == 200 and items else [f"HTTP {estado}, items={items}"]
    return {"filtro": filtro, "http": estado, "items": items, "errores": errores}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--escribir", action="store_true")
    ap.add_argument("--evidencia", type=pathlib.Path)
    a = ap.parse_args(argv)
    cat = json.loads(CATALOGO.read_text(encoding="utf-8"))
    hoy = datetime.date.today().isoformat()
    reintentos: list[str] = []
    resultados, fallos = [], 0
    for c in cat["componentes"]:
        url = c["referencia_url"] or c["referencia_url_propuesta"]
        ru = comprobar_url(url, reintentos) if url else None
        rp = (comprobar_precio(c["service_name_precios"], c["producto_precios"], reintentos)
              if c["service_name_precios"] else None)
        err = (ru["errores"] if ru else []) + (rp["errores"] if rp else [])
        fallos += bool(err)
        resultados.append({"id": c["id"], "url": ru, "precios": rp, "errores": err})
        print(f"{'OK   ' if not err else 'FALLA'} {c['id']}: "
              f"{ru['http'] if ru else '-'} {ru['titulo'] if ru else 'sin URL'!r} | "
              f"precios={rp['items'] if rp else '-'} {'; '.join(err)}")
        if a.escribir:
            c["comprobacion"] = {"fecha": hoy, "url_http": ru["http"] if ru else None,
                                 "url_titulo": (ru["titulo"] or None) if ru else None,
                                 "precios_items": rp["items"] if rp else None}
    if a.escribir:
        cat["fecha"] = hoy
        CATALOGO.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
    if a.evidencia:
        a.evidencia.parent.mkdir(parents=True, exist_ok=True)
        a.evidencia.write_text(json.dumps({"fecha": hoy, "reintentos_dns": reintentos,
                                           "fallos": fallos, "resultados": resultados},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"componentes={len(resultados)} fallos={fallos} reintentos_dns={len(reintentos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
