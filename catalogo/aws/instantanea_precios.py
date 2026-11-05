"""Instantánea de precios de AWS en euros (pilar AWS de la preventa multinube; decisiones del comercial del 2026-11-04).

Mismo papel que catalogo/instantanea_precios.py para Azure: en cada despliegue se descargan los precios de TODAS las
plantillas de catalogo/aws/catalogo_componentes.json y se guardan, con su procedencia, en
catalogo/aws/precios_instantanea.json. El experto de AWS nunca escribe precios: elige plantilla y cantidades.

Fuentes (públicas, sin credenciales):
- Precios: ficheros de la Price List Bulk API de AWS, uno por servicio y región
  (https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<servicecode>/current/<region>/index.json). Solo en USD.
- Tipo de cambio: referencia diaria del BCE (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml).
  EUR = USD / tasa (el BCE cotiza 1 EUR = tasa USD). Se guarda el tipo y SU fecha, no la del despliegue.

Reglas (fallar en alto, LES-G-047/060/091/099):
- Solo las 6 regiones de la UE de REGIONES_UE (lista blanca exacta: Londres, Zúrich y las zonas locales, fuera).
- Cada plantilla resuelve a UN producto con UN término OnDemand vigente (o a los tramos de su única dimensión), con la
  unidad que dice el catálogo. Si una sola falla, no se escribe nada.
- Sin BCE, sin USD en el fichero del BCE, con un tipo no finito o de hace más de MAX_DIAS_TIPO días: no se escribe nada.
  Nunca un tipo antiguo ni inventado.

Uso (desde la raíz del repositorio):
  python -m catalogo.aws.instantanea_precios              # genera y escribe la instantánea
  python -m catalogo.aws.instantanea_precios --comprobar [--fecha-paquete AAAA-MM-DD]
--comprobar no descarga: rc 1 si la instantánea no casa con el catálogo, su huella no cuadra o tiene más de 31 días.
"""
from __future__ import annotations

import argparse
import datetime
import decimal
import hashlib
import json
import math
import os
import pathlib
import re
import socket
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

AQUI = pathlib.Path(__file__).resolve().parent
CATALOGO = AQUI / "catalogo_componentes.json"
DESTINO = AQUI / "precios_instantanea.json"
SCHEMA = "preventa-precios-instantanea-aws/1"
BASE_PRECIOS = "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws"
URL_BCE = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
FUENTE = BASE_PRECIOS + "/<servicecode>/current/<region>/index.json (USD, término OnDemand), convertido a EUR con el BCE"
AGENTE = "Mozilla/5.0 (preventa-multinube instantanea_precios_aws)"
MAX_DIAS = 31
# El BCE no publica en fines de semana ni festivos TARGET (Viernes Santo + Lunes de Pascua: 5 días sin tipo).
MAX_DIAS_TIPO = 7
# Lista blanca EXACTA de regiones de AWS en la UE (decisión del comercial, 2026-11-04). Nunca startswith("eu-"):
# eu-west-2 (Londres) y eu-central-2 (Zúrich) no están en la UE, y eu-central-1-ham-1 es una zona local.
REGIONES_UE = ("eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1", "eu-south-1", "eu-south-2")
# Campos admitidos en el filtro de una plantilla, en orden canónico. servicecode y termType no son atributos del
# producto: eligen el fichero y el bloque de términos.
CAMPOS = ("servicecode", "regionCode", "usagetype", "operation", "termType")
TERMINOS = ("OnDemand",)
_CONDICION = re.compile(r"([A-Za-z]+) eq '([^']*)'")
_DIVISORES = {"1K tokens": 1000}


class ErrorInstantanea(Exception):
    """La instantánea no se puede generar o no es válida: nunca se escribe a medias."""


def region_ue(region: object) -> str:
    """La región si está en la lista blanca de la UE; si no, falla en alto."""
    if not isinstance(region, str) or region not in REGIONES_UE:
        raise ErrorInstantanea(f"región {region!r} fuera de la lista blanca de la UE {REGIONES_UE}")
    return region


def condiciones(filtro: object) -> list[tuple[str, str]] | None:
    """[(campo, valor)] si el filtro es exactamente «campo eq 'valor'» unidas con « and »; None si no."""
    if not isinstance(filtro, str):
        return None
    ms = [_CONDICION.fullmatch(t) for t in filtro.split(" and ")]
    return None if not all(ms) else [(m.group(1), m.group(2)) for m in ms]


def problemas_filtro(filtro: object) -> list[str]:
    """Forma exigida: campos de CAMPOS sin repetir, en orden canónico, con servicecode, regionCode (de la UE),
    usagetype y termType OnDemand."""
    pares = condiciones(filtro)
    if pares is None:
        return ["no es una serie de «campo eq 'valor'» unidas con « and »"]
    campos = [c for c, _ in pares]
    if len(set(campos)) != len(campos) or any(c not in CAMPOS for c in campos):
        return [f"campos repetidos o no admitidos: {campos}"]
    if campos != sorted(campos, key=CAMPOS.index):
        return ["las condiciones no van en el orden canónico"]
    d = dict(pares)
    m = [f"falta {c}" for c in ("servicecode", "regionCode", "usagetype", "termType") if not d.get(c)]
    if d.get("termType") and d["termType"] not in TERMINOS:
        m.append(f"termType {d['termType']!r} fuera de {TERMINOS}")
    if d.get("regionCode") and d["regionCode"] not in REGIONES_UE:
        m.append(f"regionCode {d['regionCode']!r} fuera de la lista blanca de la UE")
    return m


def divisor_de_unidad(unidad: object) -> int | None:
    """Divisor de la unidad del fichero de AWS: «1K tokens» → 1000; el resto de unidades de AWS son de 1 (precio por
    petición, por hora, por GB-mes…). None si no es texto."""
    if not isinstance(unidad, str) or not unidad.strip():
        return None
    return _DIVISORES.get(unidad, 1)


def clave(catalogo_id: str, plantilla_id: str) -> str:
    return f"{catalogo_id}/{plantilla_id}"


def plantillas(cat: dict) -> list[tuple[str, dict, dict]]:
    """[(clave, fila, plantilla)] en el orden del catálogo; falla si una clave se repite."""
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
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def huella(inst: dict) -> str:
    """SHA-256 del JSON canónico de la instantánea SIN la clave «sha256»."""
    return hashlib.sha256(_canonico({k: v for k, v in inst.items() if k != "sha256"})).hexdigest()


def _decimal_finito(texto: object, nombre: str, positivo: bool = False) -> decimal.Decimal:
    """Decimal finito (y >= 0, o > 0 si `positivo`) de un texto o número; si no, falla (NaN e Infinity, LES-G-099)."""
    if isinstance(texto, bool) or not isinstance(texto, (str, int, float, decimal.Decimal)):
        raise ErrorInstantanea(f"{nombre}: no es un número: {texto!r}")
    try:
        x = decimal.Decimal(str(texto).strip())
    except decimal.InvalidOperation as e:
        raise ErrorInstantanea(f"{nombre}: ilegible {texto!r}") from e
    if not x.is_finite() or x < 0 or (positivo and x == 0):
        raise ErrorInstantanea(f"{nombre}: no finito o fuera de rango: {texto!r}")
    return x


def a_eur(usd: object, tasa: object) -> float:
    """EUR = USD / tasa del BCE (1 EUR = tasa USD). 12 cifras significativas para no perder los precios por token."""
    eur = _decimal_finito(usd, "precio USD") / _decimal_finito(tasa, "tipo BCE", positivo=True)
    return float(f"{eur:.12g}")


def parsear_bce(xml: bytes, hoy: datetime.date, max_dias: int = MAX_DIAS_TIPO) -> tuple[float, str]:
    """(tasa USD, fecha AAAA-MM-DD) del fichero diario del BCE. Falla si no hay USD, si la tasa no es finita y positiva,
    si la fecha es ilegible, futura o de hace más de `max_dias` días."""
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ErrorInstantanea(f"BCE: XML ilegible ({e})") from e
    dias = [n for n in raiz.iter() if n.tag.endswith("Cube") and n.get("time")]
    if len(dias) != 1:
        raise ErrorInstantanea(f"BCE: {len(dias)} bloques con fecha (se espera 1)")
    usd = [n.get("rate") for n in dias[0].iter() if n.tag.endswith("Cube") and n.get("currency") == "USD"]
    if len(usd) != 1:
        raise ErrorInstantanea("BCE: sin tipo USD (o repetido); no se convierte con un tipo antiguo ni inventado")
    tasa = float(_decimal_finito(usd[0], "tipo BCE USD", positivo=True))
    try:
        fecha = datetime.date.fromisoformat(dias[0].get("time"))
    except ValueError as e:
        raise ErrorInstantanea(f"BCE: fecha ilegible {dias[0].get('time')!r}") from e
    edad = (hoy - fecha).days
    if edad < 0 or edad > max_dias:
        raise ErrorInstantanea(f"BCE: tipo del {fecha} con {edad} días el {hoy} (máximo {max_dias})")
    return tasa, fecha.isoformat()


def _get(url: str, notas: list[str], timeout: int = 120) -> bytes:
    """GET con un único reintento ante fallo de DNS (anotado). Cualquier otro error falla en alto."""
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    for intento in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise ErrorInstantanea(f"HTTP {r.status}: {url}")
                return r.read()
        except urllib.error.HTTPError as e:
            raise ErrorInstantanea(f"HTTP {e.code}: {url}") from e
        except urllib.error.URLError as e:
            if intento == 1 and isinstance(e.reason, socket.gaierror):
                notas.append(f"DNS {e.reason!r}; reintento único tras 3 s: {url}")
                time.sleep(3)
                continue
            raise ErrorInstantanea(f"red: {e.reason!r}: {url}") from e
        except (TimeoutError, OSError) as e:
            raise ErrorInstantanea(f"sin respuesta ({e!r}): {url}") from e
    raise ErrorInstantanea("inalcanzable")


def url_fichero(servicecode: str, region: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]+", servicecode or ""):
        raise ErrorInstantanea(f"servicecode no válido {servicecode!r}")
    return f"{BASE_PRECIOS}/{servicecode}/current/{region_ue(region)}/index.json"


def descargar_fichero(servicecode: str, region: str, notas: list[str]) -> dict:
    url = url_fichero(servicecode, region)
    try:
        d = json.loads(_get(url, notas))
    except ValueError as e:
        raise ErrorInstantanea(f"JSON ilegible: {url}") from e
    if not isinstance(d, dict) or d.get("offerCode") != servicecode:
        raise ErrorInstantanea(f"el fichero no es del servicio {servicecode}: {url}")
    return d


def descargar_bce(notas: list[str], hoy: datetime.date) -> tuple[float, str]:
    return parsear_bce(_get(URL_BCE, notas, timeout=60), hoy)


def _fecha(texto: object) -> datetime.datetime | None:
    try:
        d = datetime.datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def resolver(k: str, plantilla: dict, fichero: dict, tasa: float, ahora: datetime.datetime) -> dict:
    """Entrada de la instantánea para una plantilla. Falla si no hay exactamente un producto que case con el filtro, si
    no tiene exactamente un término vigente, si la unidad no es la del catálogo, si los tramos no empiezan en 0 o no
    son contiguos, o si un precio no es finito."""
    filtro = plantilla.get("filtro")
    malos = problemas_filtro(filtro)
    if malos:
        raise ErrorInstantanea(f"{k}: filtro no válido: {'; '.join(malos)}")
    d = dict(condiciones(filtro))
    if fichero.get("offerCode") != d["servicecode"]:
        raise ErrorInstantanea(f"{k}: el fichero es de {fichero.get('offerCode')!r}, no de {d['servicecode']!r}")
    attrs = [(c, v) for c, v in d.items() if c not in ("servicecode", "termType")]
    productos = [p for p in (fichero.get("products") or {}).values()
                 if all((p.get("attributes") or {}).get(c) == v for c, v in attrs)]
    if len(productos) != 1:
        raise ErrorInstantanea(f"{k}: {len(productos)} productos casan con el filtro (se espera 1)")
    sku = productos[0].get("sku")
    terminos = ((fichero.get("terms") or {}).get(d["termType"]) or {}).get(sku) or {}
    vigentes, futuros = [], 0
    for t in terminos.values():
        inicio = _fecha(t.get("effectiveDate"))
        if inicio is None:
            raise ErrorInstantanea(f"{k}: effectiveDate ilegible {t.get('effectiveDate')!r}")
        if inicio > ahora:
            futuros += 1
        else:
            vigentes.append(t)
    if len(vigentes) != 1:
        raise ErrorInstantanea(f"{k}: {len(vigentes)} términos {d['termType']} vigentes ({futuros} futuros); se espera 1")
    termino = vigentes[0]
    dims = list((termino.get("priceDimensions") or {}).values())
    if not dims:
        raise ErrorInstantanea(f"{k}: término sin dimensiones de precio")
    unidades = {x.get("unit") for x in dims}
    if unidades != {plantilla.get("unidad")}:
        raise ErrorInstantanea(f"{k}: unidad {sorted(map(str, unidades))} distinta de la del catálogo "
                               f"{plantilla.get('unidad')!r}")
    tramos = []
    for x in dims:
        precios = x.get("pricePerUnit") or {}
        if set(precios) != {"USD"}:
            raise ErrorInstantanea(f"{k}: monedas {sorted(precios)}; se espera solo USD")
        desde = _decimal_finito(x.get("beginRange"), f"{k}: beginRange")
        fin = x.get("endRange")
        hasta = None if fin == "Inf" else _decimal_finito(fin, f"{k}: endRange")
        tramos.append((desde, hasta, _decimal_finito(precios["USD"], f"{k}: precio USD"), x.get("rateCode")))
    tramos.sort(key=lambda t: t[0])
    if tramos[0][0] != 0:
        raise ErrorInstantanea(f"{k}: el primer tramo empieza en {tramos[0][0]}, no en 0")
    for a, b in zip(tramos, tramos[1:]):
        if a[1] is None or a[1] != b[0]:
            raise ErrorInstantanea(f"{k}: tramos no contiguos ({a[0]}-{a[1]} y {b[0]})")
    if tramos[-1][1] is not None:
        raise ErrorInstantanea(f"{k}: el último tramo no llega a Inf")
    region = d["regionCode"]
    entrada = {"filtro": filtro, "precio_unitario": a_eur(tramos[0][2], tasa), "moneda_origen": "USD",
               "precio_origen": float(tramos[0][2]), "unidad": plantilla["unidad"],
               "effectiveDate": termino.get("effectiveDate"), "usagetype": d["usagetype"], "sku": sku,
               "rateCode": tramos[0][3], "regionCode": region_ue(region),
               "productos_devueltos": len(productos), "terminos_futuros_descartados": futuros,
               "sha256_articulo": hashlib.sha256(_canonico({"producto": productos[0], "termino": termino})).hexdigest()}
    if len(tramos) > 1:
        entrada["tramos"] = [{"desde": float(t[0]), "precio_unitario": a_eur(t[2], tasa), "precio_origen": float(t[2])}
                             for t in tramos]
    return entrada


def generar(cat: dict, ahora: datetime.datetime | None = None, notas: list[str] | None = None,
            fichero=descargar_fichero, bce=descargar_bce) -> dict:
    """Instantánea completa en memoria. Primero el BCE (sin tipo no hay nada que hacer); después un fichero por servicio
    y región. Si alguna plantilla falla, lanza ErrorInstantanea con TODOS los fallos."""
    notas = [] if notas is None else notas
    ahora = ahora or datetime.datetime.now(datetime.timezone.utc)
    tasa, fecha_tipo = bce(notas, ahora.date())
    ficheros: dict[tuple[str, str], dict] = {}
    entradas, fallos = {}, []
    for k, _c, p in plantillas(cat):
        try:
            pares = condiciones(p.get("filtro"))
            if pares is None:
                raise ErrorInstantanea(f"{k}: filtro no válido")
            d = dict(pares)
            par = (d.get("servicecode", ""), region_ue(d.get("regionCode")))
            if par not in ficheros:
                ficheros[par] = fichero(par[0], par[1], notas)
            entradas[k] = resolver(k, p, ficheros[par], tasa, ahora)
        except ErrorInstantanea as e:
            fallos.append(str(e))
    if fallos:
        raise ErrorInstantanea(f"{len(fallos)} de {len(entradas) + len(fallos)} plantillas no resuelven:\n- "
                               + "\n- ".join(fallos))
    inst = {"schema": SCHEMA, "fecha_consulta": ahora.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "moneda": "EUR", "moneda_origen": "USD", "fuente": FUENTE,
            "conversion": {"fuente": URL_BCE, "regla": "EUR = USD / tipo_bce", "tipo_bce": tasa,
                           "fecha_tipo_bce": fecha_tipo},
            "regiones_ue": list(REGIONES_UE), "catalogo_version": cat.get("version"),
            "publicaciones": {f"{s}/{r}": {"url": url_fichero(s, r), "publicationDate": f.get("publicationDate"),
                                           "version": f.get("version")} for (s, r), f in sorted(ficheros.items())},
            "aviso": cat.get("aviso_precios"), "plantillas": entradas}
    inst["sha256"] = huella(inst)
    return inst


def _finito(x: object, minimo: float = 0) -> bool:
    try:  # Revisión: un entero JSON de miles de dígitos desborda math.isfinite
        return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x) and x >= minimo
    except OverflowError:
        return False


def problemas(inst: object, cat: dict, fecha_paquete: datetime.date | None = None, max_dias: int = MAX_DIAS) -> list[str]:
    """Motivos por los que la instantánea no vale para este catálogo (y, con `fecha_paquete`, para un paquete de esa
    fecha). [] si vale."""
    if not isinstance(inst, dict):
        return ["la instantánea no es un objeto JSON"]
    m = []
    if inst.get("schema") != SCHEMA or inst.get("moneda") != "EUR" or inst.get("moneda_origen") != "USD":
        m.append("schema o monedas distintos de los esperados")
    try:
        if inst.get("sha256") != huella(inst):
            m.append("la huella sha256 no cuadra con el contenido")
    except ValueError:
        m.append("la instantánea contiene NaN o Infinity")
    conv = inst.get("conversion") if isinstance(inst.get("conversion"), dict) else {}
    if not _finito(conv.get("tipo_bce")) or conv.get("tipo_bce") == 0:
        m.append(f"tipo_bce no válido {conv.get('tipo_bce')!r}")
    if conv.get("fuente") != URL_BCE or conv.get("regla") != "EUR = USD / tipo_bce":
        m.append("conversion sin la fuente o la regla del BCE")
    fecha_tipo, consulta = _fecha(conv.get("fecha_tipo_bce")), _fecha(inst.get("fecha_consulta"))
    if fecha_tipo is None:
        m.append(f"fecha_tipo_bce ilegible {conv.get('fecha_tipo_bce')!r}")
    elif consulta is not None and not 0 <= (consulta.date() - fecha_tipo.date()).days <= MAX_DIAS_TIPO:
        m.append(f"el tipo del BCE ({fecha_tipo.date()}) no es de los {MAX_DIAS_TIPO} días anteriores a la consulta")
    if inst.get("regiones_ue") != list(REGIONES_UE):
        m.append("regiones_ue no es la lista blanca vigente")
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
    m += [f"falta la plantilla {k}" for k in sorted(set(esperadas) - set(ps))]
    m += [f"plantilla {k} que no está en el catálogo" for k in sorted(set(ps) - set(esperadas))]
    for k in sorted(set(ps) & set(esperadas)):
        e, p = ps[k], esperadas[k]
        if not isinstance(e, dict) or e.get("filtro") != p["filtro"]:
            m.append(f"{k}: el filtro no es el del catálogo")
            continue
        if not _finito(e.get("precio_unitario")) or not _finito(e.get("precio_origen")):
            m.append(f"{k}: precio no válido {e.get('precio_unitario')!r} / {e.get('precio_origen')!r}")
        elif e.get("unidad") != p.get("unidad") or divisor_de_unidad(e.get("unidad")) != p.get("divisor"):
            m.append(f"{k}: la unidad «{e.get('unidad')}» no es la de la plantilla o no da su divisor {p.get('divisor')}")
        elif e.get("regionCode") not in REGIONES_UE:
            m.append(f"{k}: región {e.get('regionCode')!r} fuera de la UE")
        elif not _convertido(e, conv.get("tipo_bce")):
            m.append(f"{k}: precio_unitario no es precio_origen / tipo_bce (también en cada tramo)")
        elif "tramos" in e and not _tramos_validos(e["tramos"], e["precio_unitario"]):
            m.append(f"{k}: tramos no válidos (2 o más, el primero desde 0 con el precio_unitario, crecientes y finitos)")
    return m


def _convertido(e: dict, tasa: object) -> bool:
    """El EUR guardado es exactamente la conversión de su USD con el tipo guardado (la huella no lo garantiza)."""
    pares = [(e.get("precio_unitario"), e.get("precio_origen"))]
    if isinstance(e.get("tramos"), list):
        pares += [(t.get("precio_unitario"), t.get("precio_origen")) for t in e["tramos"] if isinstance(t, dict)]
    try:
        return all(eur == a_eur(usd, tasa) for eur, usd in pares)
    except ErrorInstantanea:
        return False


def _tramos_validos(tramos: object, precio: float) -> bool:
    if not isinstance(tramos, list) or len(tramos) < 2 or not all(isinstance(x, dict) for x in tramos):
        return False
    desde = [x.get("desde") for x in tramos]
    precios = [x.get("precio_unitario") for x in tramos]
    return (all(_finito(d) for d in desde) and all(_finito(p) for p in precios)
            and all(_finito(x.get("precio_origen")) for x in tramos) and desde[0] == 0
            and precios[0] == precio and all(b > a for a, b in zip(desde, desde[1:])))


def serializar(inst: dict) -> str:
    return json.dumps(inst, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def escribir(inst: dict, cat: dict, destino: pathlib.Path = DESTINO) -> None:
    """Escribe solo si la instantánea vale para el catálogo: primero a un temporal y después con os.replace."""
    fallos = problemas(inst, cat)
    if fallos:
        raise ErrorInstantanea("no se escribe: " + "; ".join(fallos))
    datos = serializar(inst).encode("utf-8")
    tmp = destino.with_name(destino.name + ".tmp")
    try:
        tmp.write_bytes(datos)
        os.replace(tmp, destino)
    finally:
        tmp.unlink(missing_ok=True)
    if destino.read_bytes() != datos:
        raise ErrorInstantanea(f"la copia {destino} no es igual byte a byte")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Instantánea de precios de AWS en EUR (Bulk API pública + tipo del BCE).")
    ap.add_argument("--comprobar", action="store_true", help="no descarga: valida la instantánea guardada")
    ap.add_argument("--fecha-paquete", type=datetime.date.fromisoformat, default=None)
    a = ap.parse_args(argv)
    cat = json.loads(CATALOGO.read_text(encoding="utf-8"))
    if a.comprobar:
        fecha = a.fecha_paquete or datetime.datetime.now(datetime.timezone.utc).date()
        if not DESTINO.exists():
            print(f"FALLA falta {DESTINO}")
            return 1
        try:
            inst = json.loads(DESTINO.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            print(f"FALLA instantánea ilegible: {e}")
            return 1
        fallos = problemas(inst, cat, fecha)
        print("\n".join(f"FALLA {x}" for x in fallos) or f"instantánea AWS válida para el catálogo v{cat.get('version')} "
                                                           f"el {fecha}")
        return 1 if fallos else 0
    notas: list[str] = []
    try:
        inst = generar(cat, notas=notas)
        escribir(inst, cat)
    except (ErrorInstantanea, OSError) as e:
        print("\n".join(notas))
        print(f"NO SE ESCRIBE NADA: {e}")
        return 2
    print("\n".join(notas))
    n = len(inst["plantillas"])
    con_tramos = sum(1 for e in inst["plantillas"].values() if "tramos" in e)
    c = inst["conversion"]
    print(f"escrita: {n} plantillas ({con_tramos} con tramos) de {len(inst['publicaciones'])} ficheros, "
          f"fecha_consulta {inst['fecha_consulta']}, tipo BCE {c['tipo_bce']} del {c['fecha_tipo_bce']}, "
          f"sha256 {inst['sha256']}")
    print(f"  {DESTINO}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
