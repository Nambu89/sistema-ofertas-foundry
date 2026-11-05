"""Comprueba el catálogo de Google Cloud (catalogo/gcp/catalogo_componentes.json). Código de salida = veredicto.

Sin red (siempre): forma de cada fila y plantilla (lista blanca de regiones de la UE, filtro canónico, factores,
niveles, modelo y cómputo por defecto), las referencias de catalogo_referencias_gcp.json y que el bloque generado de
agentes/gcp/instrucciones_experto_gcp.md coincide con el catálogo. Las plantillas sin `unidad_uso` se listan como
NO VERIFICADO (sin clave de la Catalog API no se puede ver la unidad): no rompen la forma, pero la instantánea fallará
con ellas hasta que se declaren.

Con --red (solo GET públicos, sin credenciales): cada URL responde 200 sin cambiar de ruta y con el título guardado,
y cada SKU aparece en su página pública de grupo de SKU (cloud.google.com/skus/sku-groups/…) con su servicio, su
descripción literal y su skuId.

Uso:
  python -m catalogo.gcp.comprobar_catalogo [--red] [--escribir-instrucciones]
rc 0 si todo pasa; rc 1 si falla algo.
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from catalogo.gcp import instantanea_precios as ip

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
CATALOGO = AQUI / "catalogo_componentes.json"
REFERENCIAS = AQUI / "catalogo_referencias_gcp.json"
INSTRUCCIONES = RAIZ / "agentes" / "gcp" / "instrucciones_experto_gcp.md"
INICIO = "### Catálogo y plantillas de Google Cloud (generado por catalogo/gcp/comprobar_catalogo.py; no editar a mano)"
FIN = "### Fin del catálogo de Google Cloud"
CAPAS = ("usuarios_canales", "aplicacion_integracion", "ia", "datos_conocimiento", "identidad_seguridad_red",
         "operacion_observabilidad")
DOMINIOS = ("https://docs.cloud.google.com/", "https://cloud.google.com/")
AGENTE = "Mozilla/5.0 (preventa-foundry comprobar_catalogo_gcp)"


def _fecha_ok(x: object) -> bool:
    """AAAA-MM-DD y fecha real del calendario (2026-99-99 no vale)."""
    if not isinstance(x, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", x):
        return False
    try:
        datetime.date.fromisoformat(x)
    except ValueError:
        return False
    return True


def _url_ok(x: object, prefijos: tuple[str, ...] = DOMINIOS) -> bool:
    return isinstance(x, str) and x.startswith(prefijos) and " " not in x and "#" not in x and "?" not in x


def problemas(cat: dict, refs: dict | None = None) -> list[str]:
    """Forma del catálogo (y de las referencias, si se pasan). [] si todo está bien."""
    m: list[str] = []
    if cat.get("schema") != "preventa-catalogo/1" or not isinstance(cat.get("version"), int) or not _fecha_ok(cat.get("fecha")):
        m.append("schema, version o fecha no válidos")
    factores = {f.get("id"): f for f in cat.get("factores_estandar") or []}
    for k, f in factores.items():
        partes = [d.get("valor") for d in f.get("desglose") or []]
        if f.get("tipo") not in ("oficial", "supuesto") or not partes:
            m.append(f"factor {k}: tipo o desglose no válidos")
        elif f["tipo"] == "supuesto" and (None in partes or abs(sum(partes) - f.get("valor", 0)) > 1e-9):
            m.append(f"factor {k}: un supuesto lleva todo el desglose con valor y su suma es el factor")
    filas, ids = {}, []
    for c in cat.get("componentes") or []:
        cid = c.get("id")
        ids.append(cid)
        filas[cid] = c
        if not isinstance(cid, str) or not re.fullmatch(r"gcp-[a-z0-9-]{2,40}", cid):
            m.append(f"id {cid!r} sin la forma gcp-…")
        if c.get("capa") not in CAPAS:
            m.append(f"{cid}: capa {c.get('capa')!r} no admitida")
        if not _url_ok(c.get("referencia_url")) or not c.get("referencia_titulo"):
            m.append(f"{cid}: referencia_url fuera de docs.cloud.google.com/cloud.google.com o sin título")
        m += ip.problemas_region(c)
        pls = c.get("plantillas_precio") or []
        if pls and not c.get("service_name_precios"):
            m.append(f"{cid}: plantillas sin service_name_precios")
        pids = [p.get("id") for p in pls]
        if len(set(pids)) != len(pids):
            m.append(f"{cid}: ids de plantilla repetidos")
        for p in pls:
            k = f"{cid}/{p.get('id')}"
            m += ip.problemas_plantilla(c, p)
            if p.get("impulsor") not in ("tiempo", "volumen"):
                m.append(f"{k}: impulsor {p.get('impulsor')!r}")
            if p.get("impulsor") == "tiempo" and p.get("divisor") != 1:
                m.append(f"{k}: una plantilla de tiempo lleva divisor 1")
            con_f, sin_f = bool(p.get("factor_estandar")), bool(str(p.get("sin_factor_motivo") or "").strip())
            if p.get("impulsor") == "volumen" and con_f == sin_f:
                m.append(f"{k}: plantilla de volumen con factor estándar y motivo a la vez, o sin ninguno")
            if con_f and p["factor_estandar"] not in factores:
                m.append(f"{k}: factor_estandar {p['factor_estandar']!r} desconocido")
            if "por_defecto" in p and p["por_defecto"] is not True:
                m.append(f"{k}: por_defecto solo true (o sin la clave)")
            if not _url_ok(p.get("fuente_sku"), ("https://cloud.google.com/skus/sku-groups/",)):
                m.append(f"{k}: fuente_sku no es una página pública de grupo de SKU")
            if "modelo" in p:
                cv = p.get("ciclo_vida") or {}
                if not _fecha_ok(cv.get("ga")) or not _url_ok(cv.get("fuente")) or (
                        cv.get("retirada") is not None and not _fecha_ok(cv.get("retirada"))):
                    m.append(f"{k}: plantilla de modelo sin ciclo de vida válido")
        for lista in [c.get("medidores_obligatorios") or []] + [n.get("plantillas") or [] for n in c.get("niveles") or []]:
            if set(lista) - set(pids):
                m.append(f"{cid}: medidores o plantillas de nivel ajenos a la fila: {sorted(set(lista) - set(pids))}")
        npd = c.get("nivel_por_defecto")
        if npd and npd.get("nivel") not in [n.get("nivel") for n in c.get("niveles") or []]:
            m.append(f"{cid}: nivel_por_defecto que no es uno de sus niveles")
        for nombre, d in (c.get("disponibilidad") or {}).items():
            if not set(d.get("regiones") or []) <= ip.REGIONES_UE | ip.MULTIRREGIONES_UE or not _url_ok(d.get("fuente")):
                m.append(f"{cid}: disponibilidad de {nombre} con regiones fuera de la UE o sin fuente")
    if len(set(ids)) != len(ids):
        m.append("ids de componente repetidos")
    d = cat.get("modelo_por_defecto") or {}
    fila = filas.get(d.get("componente")) or {}
    defecto = sorted(p["id"] for p in fila.get("plantillas_precio") or [] if p.get("por_defecto") is True)
    modelos = {p.get("modelo") for p in fila.get("plantillas_precio") or [] if p["id"] in (d.get("plantillas") or [])}
    if not d or defecto != sorted(d.get("plantillas") or []) or modelos != {d.get("modelo")} or d.get("region") != fila.get("region_ue"):
        m.append("modelo_por_defecto no casa con las plantillas «por defecto», su modelo o la región de la fila")
    cp = cat.get("computo_por_defecto") or {}
    fila = filas.get(cp.get("componente")) or {}
    nivel = next((n for n in fila.get("niveles") or [] if n.get("nivel") == cp.get("nivel")), None)
    if not nivel or sorted(nivel.get("plantillas") or []) != sorted(cp.get("plantillas") or []) or \
            not set(cp.get("filas") or []) <= set(filas):
        m.append("computo_por_defecto no casa con un nivel de su fila o nombra filas ajenas")
    arq = [a.get("id") for a in cat.get("arquitecturas_referencia") or []]
    if not arq or len(set(arq)) != len(arq) or not all(
            _url_ok(a.get("url"), ("https://docs.cloud.google.com/architecture/",)) for a in cat["arquitecturas_referencia"]):
        m.append("arquitecturas_referencia vacías, con ids repetidos o fuera del Cloud Architecture Center")
    if refs is not None:
        rids = [r.get("id") for r in refs.get("referencias") or []]
        if not rids or len(set(rids)) != len(rids):
            m.append("catalogo_referencias_gcp.json sin referencias o con ids repetidos")
        for r in refs.get("referencias") or []:
            if not _url_ok(r.get("url")) or not r.get("titulo") or r.get("http") != 200 or not _fecha_ok(r.get("consultado")):
                m.append(f"referencia {r.get('id')}: url, título, http 200 o fecha no válidos")
        por_url = {r.get("url"): r.get("titulo") for r in refs.get("referencias") or []}
        for a in cat.get("arquitecturas_referencia") or []:
            if a.get("url") not in por_url:
                m.append(f"arquitectura {a.get('id')}: su URL no está en catalogo_referencias_gcp.json")
    return m


def no_verificadas(cat: dict) -> list[str]:
    return [k for k, _c, p in ip.plantillas(cat) if p.get("unidad_uso") is None]


# ───────────────────────────── bloque de las instrucciones ─────────────────────────────

def _num(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".") if float(v).is_integer() else str(v).replace(".", ",")


def bloque(cat: dict) -> str:
    """Bloque Markdown del catálogo para las instrucciones del experto (determinista)."""
    out = [INICIO, "", "| catalogo_id | Nombre oficial | También conocido como (nunca como `servicio`) | Capa | Región UE |",
           "|---|---|---|---|---|"]
    for c in cat["componentes"]:
        region = c["region_ue"] + (" (precio global)" if c.get("region_precio") else "")
        out.append(f"| `{c['id']}` | {c['nombre_oficial']} | {', '.join(c.get('alias') or [])} | `{c['capa']}` | `{region}` |")
    out += ["", "Plantillas de precio (`T` = tiempo, una instancia 730 h al mes; `V/n` = volumen, cantidad ÷ n; "
            "`[f=…]` factor estándar; `[sin f]` exige `factor_override`):", ""]
    fs = {f["id"]: f for f in cat.get("factores_estandar") or []}
    for c in cat["componentes"]:
        for p in c.get("plantillas_precio") or []:
            tipo = "T" if p["impulsor"] == "tiempo" else f"V/{_num(p['divisor'])}"
            f = fs.get(p.get("factor_estandar"))
            fac = f"[f={_num(f['valor'])} {f['unidad']}]" if f else "[sin f]" if p["impulsor"] == "volumen" else ""
            extra = " (por defecto)" if p.get("por_defecto") else ""
            out.append(f"- `{c['id']}` / `{p['id']}`: {p['concepto']} {tipo} {fac}{extra}".rstrip())
    out += ["", "Medidores obligatorios:"]
    out += [f"- `{c['id']}`: {', '.join(f'`{x}`' for x in c['medidores_obligatorios'])}"
            for c in cat["componentes"] if c.get("medidores_obligatorios")]
    out += ["", "Niveles de servicio:"]
    for c in cat["componentes"]:
        for n in c.get("niveles") or []:
            defecto = " (por defecto)" if (c.get("nivel_por_defecto") or {}).get("nivel") == n["nivel"] else ""
            out.append(f"- `{c['id']}` «{n['nivel']}»{defecto}: {'; '.join(n['limites'])}")
    d, cp = cat["modelo_por_defecto"], cat["computo_por_defecto"]
    out += ["", f"Modelo por defecto: `{d['modelo']}` en `{d['componente']}` ({d['despliegue']}), plantillas "
            f"{', '.join(f'`{x}`' for x in d['plantillas'])}.",
            f"Cómputo por defecto: `{cp['componente']}` nivel «{cp['nivel']}», plantillas "
            f"{', '.join(f'`{x}`' for x in cp['plantillas'])}, 1 instancia.", "", "Arquitecturas de referencia:"]
    out += [f"- `{a['id']}`: {a['titulo']} ({a['url']}). {a['cuando_usar']}" for a in cat["arquitecturas_referencia"]]
    return "\n".join(out + ["", FIN])


def insertar(texto: str, nuevo: str) -> str:
    i, j = texto.find(INICIO), texto.find(FIN)
    if i < 0 or j < i:
        raise ValueError("las instrucciones no tienen las marcas del bloque del catálogo")
    return texto[:i] + nuevo + texto[j + len(FIN):]


# ───────────────────────────── red ─────────────────────────────

def _get(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.geturl(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.geturl() or url, ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:  # Revisión: un fallo de red es un FALLA, no un traceback
        return 0, f"{url} (sin respuesta: {type(e).__name__})", ""


def titulo(cuerpo: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", cuerpo, re.S | re.I)
    if not m:
        return None
    return " ".join(html.unescape(m.group(1)).split()).split(" | ")[0].strip()


def filas_sku(cuerpo: str) -> set[tuple[str, str, str]]:
    """{(serviceId, descripción, skuId)} de la tabla pública de un grupo de SKU."""
    salida = set()
    for fila in re.findall(r"<tr[^>]*>(.*?)</tr>", cuerpo, re.S):
        celdas = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", x)).split())
                  for x in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)]
        if len(celdas) >= 3:
            m = re.search(r"\(([0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4})\)\s*$", celdas[0])
            if m:
                salida.add((m.group(1), celdas[1], celdas[2]))
    return salida


def comprobar_red(cat: dict, refs: dict, get=_get) -> list[str]:
    m, paginas = [], {}
    urls = {c["referencia_url"]: c.get("referencia_titulo") for c in cat["componentes"]}
    urls |= {r["url"]: r["titulo"] for r in refs.get("referencias") or []}
    for url, esperado in sorted(urls.items()):
        estado, final, cuerpo = get(url)
        t = titulo(cuerpo)
        ok = estado == 200 and urllib.parse.urlsplit(final).path.rstrip("/") == urllib.parse.urlsplit(url).path.rstrip("/")
        if not ok or t != esperado:
            m.append(f"{url}: HTTP {estado}, final {final}, título {t!r} (esperado {esperado!r})")
        print(f"{'OK   ' if ok and t == esperado else 'FALLA'} {estado} {url} {t!r}")
    for k, _c, p in ip.plantillas(cat):
        d = ip.condiciones(p["filtro"])
        if p["fuente_sku"] not in paginas:
            estado, _f, cuerpo = get(p["fuente_sku"])
            paginas[p["fuente_sku"]] = filas_sku(cuerpo) if estado == 200 else set()
        ok = (d["serviceId"], p["concepto"], d["skuId"]) in paginas[p["fuente_sku"]]
        if not ok:
            m.append(f"{k}: ({d['serviceId']}, {p['concepto']!r}, {d['skuId']}) no aparece en {p['fuente_sku']}")
        print(f"{'OK   ' if ok else 'FALLA'} SKU {k}: {d['skuId']} «{p['concepto']}»")
    return m


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Comprueba el catálogo de Google Cloud.")
    ap.add_argument("--red", action="store_true", help="comprueba URL, títulos y SKU contra las páginas públicas")
    ap.add_argument("--escribir-instrucciones", action="store_true", help="regenera el bloque de las instrucciones")
    a = ap.parse_args(argv)
    cat = json.loads(CATALOGO.read_text(encoding="utf-8"))
    refs = json.loads(REFERENCIAS.read_text(encoding="utf-8"))
    fallos = problemas(cat, refs)
    texto = INSTRUCCIONES.read_text(encoding="utf-8")
    nuevo = insertar(texto, bloque(cat))
    if a.escribir_instrucciones and nuevo != texto and not fallos:  # Revisión: con el catálogo roto no se escribe
        INSTRUCCIONES.write_text(nuevo, encoding="utf-8", newline="\n")
        texto = nuevo
    if nuevo != texto:
        fallos.append("el bloque del catálogo de las instrucciones no coincide con el catálogo (--escribir-instrucciones)")
    if a.red:
        fallos += comprobar_red(cat, refs)
    nv = no_verificadas(cat)
    for x in fallos:
        print(f"FALLA {x}")
    print(f"NO VERIFICADO (unidad_uso sin ver en la Catalog API, la instantánea fallará con ellas): {len(nv)} de "
          f"{len(ip.plantillas(cat))} plantillas")
    print(f"componentes={len(cat['componentes'])} plantillas={len(ip.plantillas(cat))} fallos={len(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
