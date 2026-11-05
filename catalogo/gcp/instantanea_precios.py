"""Instantánea de precios de Google Cloud en euros (Cloud Billing Catalog API, decisión del comercial del 2026-11-04).

Los precios salen TAL CUAL de la Cloud Billing Catalog API con `currencyCode=EUR` (la conversión la hace Google, con
su recargo incluido en `currencyConversionRate`); no se convierte nada desde USD. Procedencia `gcp_catalog_eur`.

Cada plantilla del catálogo (catalogo/gcp/catalogo_componentes.json) identifica UN SKU con un filtro
«serviceId eq '…' and skuId eq '…' and serviceRegion eq '…'». El guion pide una vez cada servicio, busca el SKU y
exige: descripción literal igual al `concepto`, uso OnDemand, la región en `serviceRegions`, un solo `pricingInfo`
vigente, `usageUnit` igual a la `unidad_uso` declarada, tramos desde 0, crecientes y finitos, y EUR en cada precio.
Si una sola plantilla no resuelve, falla en alto con TODOS los motivos y NO escribe nada (LES-G-091, LES-G-099).

La API exige clave (403 «unregistered callers» sin ella): se lee de la variable de entorno GCP_BILLING_API_KEY (en
producción, de Key Vault), viaja en la cabecera X-Goog-Api-Key (nunca en la URL) y se tapa en todo lo que se imprime.

Uso:
  python -m catalogo.gcp.instantanea_precios                    # consulta y escribe catalogo/gcp/precios_instantanea.json
  python -m catalogo.gcp.instantanea_precios --comprobar [--fecha-paquete AAAA-MM-DD]
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from lib.evidencia import enmascarar_texto
from lib.hashes import hash_json_sin, json_canonico, sha256_bytes

AQUI = pathlib.Path(__file__).resolve().parent
CATALOGO = AQUI / "catalogo_componentes.json"
DESTINO = AQUI / "precios_instantanea.json"
SCHEMA = "preventa-precios-instantanea-gcp/1"
PROCEDENCIA = "gcp_catalog_eur"
API = "https://cloudbilling.googleapis.com/v1/services/{servicio}/skus"
FUENTE = "https://cloudbilling.googleapis.com/v1/services/*/skus (currencyCode=EUR, Cloud Billing Catalog API)"
VAR_CLAVE = "GCP_BILLING_API_KEY"
MAX_DIAS = 31
MAX_PAGINAS = 40
AGENTE = "preventa-foundry instantanea_precios_gcp"

# Lista blanca EXPLÍCITA de regiones de Google Cloud en la UE (LES-G-060: nunca un startswith("europe-")).
# Fuente: https://docs.cloud.google.com/compute/docs/regions-zones (consultada el 2026-11-04). Fuera, aunque empiecen
# por «europe-»: europe-west2 (Londres, Reino Unido) y europe-west6 (Zúrich, Suiza).
REGIONES_UE = frozenset({
    "europe-central2",    # Varsovia, Polonia
    "europe-north1",      # Hamina, Finlandia
    "europe-north2",      # Estocolmo, Suecia
    "europe-southwest1",  # Madrid, España
    "europe-west1",       # St. Ghislain, Bélgica
    "europe-west3",       # Fráncfort, Alemania
    "europe-west4",       # Eemshaven, Países Bajos
    "europe-west8",       # Milán, Italia
    "europe-west9",       # París, Francia
    "europe-west10",      # Berlín, Alemania
    "europe-west12",      # Turín, Italia
})
# Multirregión «eu»: «ML processing of Customer Data … stays within … the European Union»
# (https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/locations, 2026-11-04).
MULTIRREGIONES_UE = frozenset({"eu"})
# Ámbito de precio de un SKU con precio único mundial: solo vale como region_precio, nunca como región de despliegue.
AMBITO_GLOBAL = "global"
CAMPOS = ("serviceId", "skuId", "serviceRegion")
_CONDICION = re.compile(r"([A-Za-z]+) eq '([^']+)'")
_CLAVE_GOOGLE = re.compile(r"AIza[0-9A-Za-z_-]{30,}")


class ErrorInstantanea(Exception):
    """La instantánea no se puede generar o no es válida: nunca se escribe a medias."""


# ───────────────────────────── clave y salidas ─────────────────────────────

def clave_api(entorno: dict | None = None) -> str:
    """La clave de la Catalog API desde el entorno; falla en alto (sin mostrar nada de ella) si falta o está vacía."""
    valor = (os.environ if entorno is None else entorno).get(VAR_CLAVE)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorInstantanea(
            f"falta la variable de entorno {VAR_CLAVE} (clave de API de Google Cloud restringida a la Cloud Billing "
            "API; en producción se lee de Key Vault): la Catalog API responde 403 sin clave y no se escribe nada")
    return valor.strip()


def tapar(texto: object, clave: str | None = None) -> str:
    """Texto apto para la consola o un registro: sin la clave literal, sin nada con forma de clave de Google y sin
    los secretos que reconoce lib.evidencia."""
    s = str(texto)
    if clave:
        s = s.replace(clave, "<OMITIDO-CLAVE-GCP>")
    return enmascarar_texto(_CLAVE_GOOGLE.sub("<OMITIDO-CLAVE-GCP>", s))


# ───────────────────────────── forma del catálogo ─────────────────────────────

def condiciones(filtro: object) -> dict | None:
    """{campo: valor} si el filtro es EXACTAMENTE serviceId, skuId y serviceRegion, en ese orden; None si no."""
    if not isinstance(filtro, str):
        return None
    pares = [_CONDICION.fullmatch(t) for t in filtro.split(" and ")]
    if not all(pares) or [m.group(1) for m in pares] != list(CAMPOS):
        return None
    return {m.group(1): m.group(2) for m in pares}


def region_de(fila: dict, p: dict | None = None) -> str | None:
    """serviceRegion con el que se pide el SKU: region_precio («global») de la plantilla o de la fila, o la región de
    despliegue de la fila."""
    return (p or {}).get("region_precio") or fila.get("region_precio") or fila.get("region_ue")


def problemas_region(fila: dict) -> list[str]:
    """La región de despliegue está en la lista blanca UE; «global» solo en filas sin precio (identidad, IAM)."""
    r, rp, m = fila.get("region_ue"), fila.get("region_precio"), []
    if r == AMBITO_GLOBAL:
        if fila.get("plantillas_precio"):
            m.append(f"{fila.get('id')}: region_ue «global» solo en filas sin plantillas de precio")
    elif r not in REGIONES_UE | MULTIRREGIONES_UE:
        m.append(f"{fila.get('id')}: region_ue {r!r} fuera de la lista blanca de regiones de la UE")
    if rp is not None and rp != AMBITO_GLOBAL:
        m.append(f"{fila.get('id')}: region_precio {rp!r}: solo «global» (SKU con precio único mundial)")
    return m


def problemas_plantilla(fila: dict, p: dict) -> list[str]:
    """Forma de una plantilla: filtro canónico de su fila, concepto, unidad_uso y divisor."""
    k, d, m = f"{fila.get('id')}/{p.get('id')}", condiciones(p.get("filtro")), []
    if d is None:
        return [f"{k}: el filtro no es «serviceId eq '…' and skuId eq '…' and serviceRegion eq '…'»"]
    if p.get("region_precio") not in (None, AMBITO_GLOBAL):
        m.append(f"{k}: region_precio {p['region_precio']!r}: solo «global»")
    if d["serviceRegion"] != region_de(fila, p):
        m.append(f"{k}: serviceRegion {d['serviceRegion']!r} distinto de {region_de(fila, p)!r}")
    if not re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", d["serviceId"]) or \
            not re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", d["skuId"]):
        m.append(f"{k}: serviceId o skuId sin la forma XXXX-XXXX-XXXX")
    if not isinstance(p.get("concepto"), str) or not p["concepto"].strip():
        m.append(f"{k}: sin concepto (descripción literal del SKU)")
    if p.get("unidad_uso") is not None and (not isinstance(p["unidad_uso"], str) or not p["unidad_uso"].strip()):
        m.append(f"{k}: unidad_uso vacía (null si aún no se ha visto en la API)")
    div = p.get("divisor")
    if isinstance(div, bool) or not isinstance(div, int) or div < 1:
        m.append(f"{k}: divisor {div!r}: entero de 1 o más")
    return m


def plantillas(cat: dict) -> list[tuple[str, dict, dict]]:
    """[(«fila/plantilla», fila, plantilla)] en el orden del catálogo; falla si una clave se repite."""
    salida, vistas = [], set()
    for c in cat.get("componentes") or []:
        for p in c.get("plantillas_precio") or []:
            k = f"{c['id']}/{p['id']}"
            if k in vistas:
                raise ErrorInstantanea(f"plantilla repetida en el catálogo: {k}")
            vistas.add(k)
            salida.append((k, c, p))
    return salida


# ───────────────────────────── resolución de un SKU ─────────────────────────────

def _numero(x: object) -> bool:
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)


def _fecha(texto: object) -> datetime.datetime | None:
    try:
        d = datetime.datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def dinero_eur(m: object) -> float:
    """Importe de un google.type.Money en EUR (units + nanos/1e9). Falla si no es EUR, si falta un campo, si los signos
    no casan o si no es finito o es negativo."""
    if not isinstance(m, dict) or m.get("currencyCode") != "EUR":
        raise ErrorInstantanea(f"precio que no está en EUR: {m.get('currencyCode') if isinstance(m, dict) else m!r}")
    units, nanos = m.get("units", "0"), m.get("nanos", 0)
    if not isinstance(units, str) or not re.fullmatch(r"-?[0-9]{1,15}", units):
        raise ErrorInstantanea(f"units ilegible: {units!r}")
    if isinstance(nanos, bool) or not isinstance(nanos, int) or not -999_999_999 <= nanos <= 999_999_999:
        raise ErrorInstantanea(f"nanos ilegible: {nanos!r}")
    u = int(units)
    if (u > 0 and nanos < 0) or (u < 0 and nanos > 0):
        raise ErrorInstantanea(f"units y nanos con signos distintos: {units} / {nanos}")
    valor = u + nanos / 1e9
    if not math.isfinite(valor) or valor < 0:
        raise ErrorInstantanea(f"precio negativo o no finito: {valor!r}")
    return round(valor, 9)


def resolver(k: str, p: dict, sku: object, ahora: datetime.datetime) -> dict:
    """Entrada de la instantánea para la plantilla `p` a partir de su SKU de la API. Nada se adivina: cualquier campo
    ausente, distinto de lo declarado o no finito hace fallar la plantilla."""
    d = condiciones(p.get("filtro"))
    if d is None:
        raise ErrorInstantanea(f"{k}: filtro con forma no admitida")
    if not isinstance(sku, dict) or sku.get("skuId") != d["skuId"]:
        raise ErrorInstantanea(f"{k}: el SKU {d['skuId']} no está en el servicio {d['serviceId']}")
    if sku.get("description") != p.get("concepto"):
        raise ErrorInstantanea(f"{k}: la descripción del SKU es {sku.get('description')!r}, no {p.get('concepto')!r}")
    if (sku.get("category") or {}).get("usageType") != "OnDemand":
        raise ErrorInstantanea(f"{k}: usageType {(sku.get('category') or {}).get('usageType')!r}, no OnDemand")
    regiones = sku.get("serviceRegions")
    if not isinstance(regiones, list) or d["serviceRegion"] not in regiones:
        raise ErrorInstantanea(f"{k}: la región {d['serviceRegion']!r} no está en serviceRegions {regiones!r}")
    info = sku.get("pricingInfo")
    if not isinstance(info, list) or len(info) != 1 or not isinstance(info[0], dict):
        raise ErrorInstantanea(f"{k}: pricingInfo con {len(info) if isinstance(info, list) else 'ningún'} elemento(s); "
                               "se exige exactamente uno")
    info = info[0]
    vigente = _fecha(info.get("effectiveTime"))
    if vigente is None or vigente > ahora:
        raise ErrorInstantanea(f"{k}: effectiveTime ilegible o futuro: {info.get('effectiveTime')!r}")
    tasa = info.get("currencyConversionRate")
    if not _numero(tasa) or tasa <= 0:
        raise ErrorInstantanea(f"{k}: currencyConversionRate ausente o no finito: {tasa!r}")
    expr = info.get("pricingExpression") or {}
    unidad = expr.get("usageUnit")
    if not isinstance(unidad, str) or not unidad:
        raise ErrorInstantanea(f"{k}: pricingExpression sin usageUnit")
    if p.get("unidad_uso") is None:
        raise ErrorInstantanea(f"{k}: unidad_uso sin declarar en el catálogo; la API da «{unidad}»: decláralo y revisa "
                               "el divisor de la plantilla antes de usar el precio")
    if unidad != p["unidad_uso"]:
        raise ErrorInstantanea(f"{k}: la API da la unidad «{unidad}», no «{p['unidad_uso']}»")
    tramos = expr.get("tieredRates")
    if not isinstance(tramos, list) or not tramos or not all(isinstance(t, dict) for t in tramos):
        raise ErrorInstantanea(f"{k}: sin tieredRates")
    desde, precios = [], []
    for t in tramos:
        inicio = t.get("startUsageAmount", 0)
        if not _numero(inicio) or inicio < 0:
            raise ErrorInstantanea(f"{k}: startUsageAmount no válido {inicio!r}")
        try:
            precios.append(dinero_eur(t.get("unitPrice")))
        except ErrorInstantanea as e:
            raise ErrorInstantanea(f"{k}: {e}") from None
        desde.append(float(inicio))
    if desde[0] != 0 or any(b <= a for a, b in zip(desde, desde[1:])):
        raise ErrorInstantanea(f"{k}: tramos que no empiezan en 0 o no son crecientes: {desde}")
    entrada = {"filtro": p["filtro"], "concepto": sku["description"], "precio_unitario": precios[0], "unidad": unidad,
               "effectiveStartDate": info["effectiveTime"], "service_id": d["serviceId"], "sku_id": d["skuId"],
               "service_regions": sorted(regiones), "tasa_conversion": tasa,
               "articulos_devueltos": 1, "sha256_articulo": sha256_bytes(json_canonico(sku))}
    if _numero(expr.get("displayQuantity")):
        entrada["display_quantity"] = expr["displayQuantity"]
    if len(tramos) > 1:
        entrada["tramos"] = [{"desde": a, "precio_unitario": b} for a, b in zip(desde, precios)]
    return entrada


# ───────────────────────────── red ─────────────────────────────

def _sin_nan(c: str):
    raise ValueError(f"constante no admitida en JSON: {c}")


def leer_json(datos: bytes) -> object:
    """JSON estricto: NaN, Infinity y -Infinity (que json.loads acepta por defecto) se rechazan."""
    return json.loads(datos, parse_constant=_sin_nan)


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """urllib copia las cabeceras propias (la clave) al seguir una redirección, también a otro host: no se sigue
    ninguna; un 3xx llega como HTTPError y falla en alto (Revisión, 2.ª pasada)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_ABRIR = urllib.request.build_opener(_SinRedirecciones).open


def consultar_servicio(servicio: str, clave: str, notas: list[str], abrir=_ABRIR,
                       pausa: float = 0.5, max_429: int = 4) -> list[dict]:
    """Todos los SKU de un servicio en EUR, página a página. Un 200 a medias (sin `skus`, con `error`, un token de
    página repetido o más de MAX_PAGINAS) falla en alto. 429: espera Retry-After (o 30 s) hasta `max_429` veces;
    DNS: un reintento. La clave va en la cabecera, nunca en la URL, y se tapa en todo mensaje."""
    if not re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}", servicio):
        raise ErrorInstantanea(f"serviceId sin forma XXXX-XXXX-XXXX: {servicio!r}")
    skus, token, vistos = [], None, set()
    for _ in range(MAX_PAGINAS):
        params = {"currencyCode": "EUR", "pageSize": "5000"} | ({"pageToken": token} if token else {})
        url = API.format(servicio=servicio) + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"X-Goog-Api-Key": clave, "User-Agent": AGENTE,
                                                   "Accept": "application/json"})
        esperas, dns = 0, 0
        while True:
            time.sleep(pausa)
            try:
                with abrir(req, timeout=60) as r:
                    cuerpo = leer_json(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 and esperas < max_429:
                    esperas += 1
                    try:
                        espera = min(max(float(e.headers.get("Retry-After") or 30), 1.0), 120.0)
                    except (TypeError, ValueError):
                        espera = 30.0
                    notas.append(f"429 en {servicio} (espera {esperas}/{max_429} de {espera:.0f} s)")
                    time.sleep(espera)
                    continue
                try:
                    detalle = e.read()[:300].decode("utf-8", "replace")
                except Exception:  # noqa: BLE001 - el cuerpo del error es opcional; el código HTTP ya basta
                    detalle = ""
                raise ErrorInstantanea(tapar(f"HTTP {e.code} de la Catalog API en {servicio}: {detalle}", clave)) from None
            except urllib.error.URLError as e:
                if dns == 0 and isinstance(e.reason, socket.gaierror):
                    dns += 1
                    notas.append(f"DNS en {servicio}; reintento único tras 3 s")
                    time.sleep(3)
                    continue
                raise ErrorInstantanea(tapar(f"red en {servicio}: {e.reason!r}", clave)) from None
            except (ValueError, TimeoutError, OSError) as e:
                raise ErrorInstantanea(tapar(f"respuesta ilegible o sin respuesta en {servicio}: {e!r}", clave)) from None
        if not isinstance(cuerpo, dict) or "error" in cuerpo:
            raise ErrorInstantanea(tapar(f"HTTP 200 con error o sin objeto en {servicio}: {str(cuerpo)[:200]}", clave))
        pagina = cuerpo.get("skus")
        if not isinstance(pagina, list) or not all(isinstance(s, dict) for s in pagina):
            raise ErrorInstantanea(f"HTTP 200 sin lista «skus» en {servicio}: respuesta parcial, no se usa")
        skus += pagina
        token = cuerpo.get("nextPageToken") or None
        if token is None:
            return skus
        if not isinstance(token, str) or token in vistos:
            raise ErrorInstantanea(f"nextPageToken repetido o ilegible en {servicio}: paginación rota")
        vistos.add(token)
    raise ErrorInstantanea(f"más de {MAX_PAGINAS} páginas en {servicio}: no se da por completa")


# ───────────────────────────── instantánea ─────────────────────────────

def huella(inst: dict) -> str:
    return hash_json_sin(inst, ["sha256"])


def generar(cat: dict, consulta, ahora: datetime.datetime | None = None) -> dict:
    """Instantánea completa en memoria. `consulta(serviceId) -> [sku]`. Si la forma del catálogo o alguna plantilla
    falla, lanza ErrorInstantanea con TODOS los motivos."""
    ahora = ahora or datetime.datetime.now(datetime.timezone.utc)
    lista = plantillas(cat)
    forma = [x for c in cat.get("componentes") or [] for x in problemas_region(c)]
    forma += [x for _k, c, p in lista for x in problemas_plantilla(c, p)]
    if forma:
        raise ErrorInstantanea("catálogo con forma no válida:\n- " + "\n- ".join(forma))
    por_servicio: dict[str, dict[str, dict] | ErrorInstantanea] = {}
    entradas, fallos = {}, []
    for k, _c, p in lista:
        d = condiciones(p["filtro"])
        if d["serviceId"] not in por_servicio:
            try:
                indice: dict[str, dict] = {}
                for s in consulta(d["serviceId"]):
                    if s.get("skuId") in indice:
                        raise ErrorInstantanea(f"skuId repetido en {d['serviceId']}: {s.get('skuId')}")
                    indice[s.get("skuId")] = s
                por_servicio[d["serviceId"]] = indice
            except ErrorInstantanea as e:  # el servicio no se reconsulta; cada plantilla suya lleva el motivo
                por_servicio[d["serviceId"]] = e
        indice = por_servicio[d["serviceId"]]
        try:
            if isinstance(indice, ErrorInstantanea):
                raise ErrorInstantanea(f"{k}: {indice}")
            entradas[k] = resolver(k, p, indice.get(d["skuId"]), ahora)
        except ErrorInstantanea as e:
            fallos.append(str(e))
        except (AttributeError, TypeError, ValueError) as e:  # Revisión: un tipo JSON inesperado también falla en alto
            fallos.append(f"{k}: respuesta con una forma inesperada ({type(e).__name__}: {e})")
    if fallos:
        raise ErrorInstantanea(f"{len(fallos)} de {len(lista)} plantillas no resuelven:\n- " + "\n- ".join(fallos))
    inst = {"schema": SCHEMA, "procedencia": PROCEDENCIA,
            "fecha_consulta": ahora.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "moneda": "EUR", "fuente": FUENTE, "catalogo_version": cat.get("version"), "plantillas": entradas}
    inst["sha256"] = huella(inst)
    return inst


def problemas(inst: object, cat: dict, fecha_paquete: datetime.date | None = None, max_dias: int = MAX_DIAS) -> list[str]:
    """Motivos por los que la instantánea no vale para este catálogo (y, con fecha, para un paquete de esa fecha)."""
    if not isinstance(inst, dict):
        return ["la instantánea no es un objeto JSON"]
    m = []
    if inst.get("schema") != SCHEMA or inst.get("moneda") != "EUR" or inst.get("procedencia") != PROCEDENCIA:
        m.append("schema, moneda o procedencia distintos de los esperados")
    try:
        if inst.get("sha256") != huella(inst):
            m.append("la huella sha256 no cuadra con el contenido")
    except ValueError:  # json_canonico rechaza NaN e Infinity
        m.append("la instantánea contiene NaN o Infinity")
    fecha = _fecha(inst.get("fecha_consulta"))
    if fecha is None:
        m.append(f"fecha_consulta ilegible: {inst.get('fecha_consulta')!r}")
    elif fecha_paquete is not None:
        dias = (fecha_paquete - fecha.date()).days
        if dias < 0:
            m.append(f"la instantánea ({fecha.date()}) es posterior al paquete ({fecha_paquete})")
        elif dias > max_dias:
            m.append(f"la instantánea tiene {dias} días en la fecha del paquete: máximo {max_dias}")
    ps = inst.get("plantillas") if isinstance(inst.get("plantillas"), dict) else {}
    esperadas = {k: p for k, _c, p in plantillas(cat)}
    m += [f"falta la plantilla {k}" for k in sorted(set(esperadas) - set(ps))]
    m += [f"plantilla {k} que no está en el catálogo" for k in sorted(set(ps) - set(esperadas))]
    for k in sorted(set(ps) & set(esperadas)):
        e, p = ps[k], esperadas[k]
        precio = e.get("precio_unitario") if isinstance(e, dict) else None
        if not isinstance(e, dict) or e.get("filtro") != p["filtro"]:
            m.append(f"{k}: el filtro no es el del catálogo")
        elif not _numero(precio) or precio < 0:
            m.append(f"{k}: precio_unitario no válido {precio!r}")
        elif e.get("unidad") != p.get("unidad_uso"):
            m.append(f"{k}: unidad «{e.get('unidad')}» distinta de la unidad_uso del catálogo")
        elif "tramos" in e and not _tramos_validos(e["tramos"], precio):
            m.append(f"{k}: tramos no válidos")
    return m


def _tramos_validos(tramos: object, precio: float) -> bool:
    if not isinstance(tramos, list) or len(tramos) < 2 or not all(isinstance(x, dict) for x in tramos):
        return False
    desde = [x.get("desde") for x in tramos]
    precios = [x.get("precio_unitario") for x in tramos]
    return (all(_numero(d) and d >= 0 for d in desde) and all(_numero(p) and p >= 0 for p in precios)
            and desde[0] == 0 and precios[0] == precio and all(b > a for a, b in zip(desde, desde[1:])))


def escribir(inst: dict, cat: dict, destino: pathlib.Path = DESTINO) -> None:
    """Escribe solo si la instantánea vale para el catálogo: temporal y os.replace; relee y compara."""
    fallos = problemas(inst, cat)
    if fallos:
        raise ErrorInstantanea("no se escribe: " + "; ".join(fallos))
    datos = (json.dumps(inst, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    tmp = destino.with_name(destino.name + ".tmp")
    try:
        tmp.write_bytes(datos)
        os.replace(tmp, destino)
    finally:
        tmp.unlink(missing_ok=True)
    if destino.read_bytes() != datos:
        raise ErrorInstantanea(f"la copia {destino} no es igual byte a byte")


def main(argv: list[str] | None = None, entorno: dict | None = None) -> int:
    ap = argparse.ArgumentParser(description="Instantánea de precios de Google Cloud en EUR (Cloud Billing Catalog API).")
    ap.add_argument("--comprobar", action="store_true", help="no consulta ni escribe: valida la instantánea guardada")
    ap.add_argument("--fecha-paquete", type=datetime.date.fromisoformat, default=None)
    ap.add_argument("--pausa", type=float, default=0.5)
    a = ap.parse_args(argv)
    if not math.isfinite(a.pausa) or not 0 <= a.pausa <= 60:
        ap.error("--pausa entre 0 y 60")
    cat = json.loads(CATALOGO.read_text(encoding="utf-8"))
    if a.comprobar:
        fecha = a.fecha_paquete or datetime.datetime.now(datetime.timezone.utc).date()
        if not DESTINO.exists():
            print(f"FALLA no existe {DESTINO.name}: la instantánea real no se ha generado (NO VERIFICADO)")
            return 1
        try:
            inst = leer_json(DESTINO.read_bytes())
        except ValueError as e:
            print(f"FALLA instantánea ilegible: {e}")
            return 1
        fallos = problemas(inst, cat, fecha)
        print("\n".join(f"FALLA {x}" for x in fallos) or f"instantánea válida para el catálogo v{cat.get('version')} el {fecha}")
        return 1 if fallos else 0
    notas: list[str] = []
    clave = None
    try:
        clave = clave_api(entorno)
        inst = generar(cat, lambda s: consultar_servicio(s, clave, notas, pausa=a.pausa))
        escribir(inst, cat)
    except (ErrorInstantanea, OSError) as e:
        print(tapar("\n".join(notas), clave))
        print(tapar(f"NO SE ESCRIBE NADA: {e}", clave))
        return 2
    print(tapar("\n".join(notas), clave))
    print(f"escrita: {len(inst['plantillas'])} plantillas, fecha_consulta {inst['fecha_consulta']}, sha256 {inst['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
