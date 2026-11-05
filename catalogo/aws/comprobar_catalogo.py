"""Comprueba el catálogo de AWS (catalogo/aws/catalogo_componentes.json). Equivalente a catalogo/comprobar_catalogo.py.

Sin red (siempre):
- forma de cada fila, plantilla, nivel, factor y disponibilidad; regiones solo de la lista blanca de la UE;
- todo número finito (NaN e Infinity rechazados al leer, LES-G-099);
- cada URL del catálogo está en catalogo/aws/catalogo_referencias_aws.json con HTTP 200 y, la de referencia de cada fila
  y la de cada arquitectura, con el título literal que dice el catálogo;
- el bloque generado de agentes/aws/instrucciones_experto_aws.md es el que sale de este catálogo.

Con --red (solo GET, sin credenciales): vuelve a pedir cada URL (HTTP 200, sin redirigir a otra ruta, título que no sea
un soft 404) y resuelve cada plantilla contra el fichero público vigente de AWS. --escribir guarda el resultado de las
URL en catalogo_referencias_aws.json (solo si todas pasan).

Uso (desde la raíz del repositorio):
  python -m catalogo.aws.comprobar_catalogo [--red [--escribir]] [--bloque]
rc 0 si todo pasa; rc 1 si falla algo (código de salida = veredicto, LES-G-091).
"""
from __future__ import annotations

import argparse
import datetime
import html
import json
import math
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from catalogo.aws import instantanea_precios as ip

AQUI = ip.AQUI
RAIZ = AQUI.parent.parent
CATALOGO = ip.CATALOGO
REFERENCIAS = AQUI / "catalogo_referencias_aws.json"
INSTRUCCIONES = RAIZ / "agentes" / "aws" / "instrucciones_experto_aws.md"
BLOQUE_INICIO = "### Catálogo y plantillas de AWS (generado por catalogo/aws/comprobar_catalogo.py --bloque; no editar a mano)"
BLOQUE_FIN = "### Fin del catálogo de AWS"
SCHEMA = "preventa-catalogo-aws/1"
SCHEMA_REF = "preventa-catalogo-referencias-aws/1"
CAPAS = ("usuarios_canales", "aplicacion_integracion", "ia", "datos_conocimiento", "identidad_seguridad_red",
         "operacion_observabilidad")
HOSTS = ("docs.aws.amazon.com", "aws.amazon.com", "learn.microsoft.com", "www.ecb.europa.eu",
         "pricing.us-east-1.amazonaws.com", "knowledge-mcp.global.api.aws", "awslabs.github.io")
# No se piden por GET: plantillas con <…>, la API del MCP (solo POST) y el fichero diario del BCE (lo prueba la instantánea).
NO_PEDIR = ("knowledge-mcp.global.api.aws", "www.ecb.europa.eu/stats/eurofxref/")
SOFT_404 = re.compile(r"(?i)\b404\b|not found|no se encuentra|page isn.t available")
AGENTE = "Mozilla/5.0 (preventa-multinube comprobar_catalogo_aws)"


def _rechazar_constante(nombre: str):
    raise ValueError(f"constante no admitida en JSON: {nombre}")


def leer_json(ruta: pathlib.Path) -> dict:
    """JSON estricto: NaN, Infinity y -Infinity se rechazan (json.loads los admite por defecto)."""
    return json.loads(ruta.read_text(encoding="utf-8"), parse_constant=_rechazar_constante)


def _urls(obj: object) -> set[str]:
    if isinstance(obj, str):
        return {obj} if obj.startswith(("https://", "http://")) else set()
    if isinstance(obj, dict):
        return set().union(*(_urls(v) for v in obj.values())) if obj else set()
    if isinstance(obj, list):
        return set().union(*(_urls(v) for v in obj)) if obj else set()
    return set()


def _finito(x: object, minimo: float = 0, estricto: bool = False) -> bool:
    try:  # Revisión: un entero JSON de miles de dígitos desborda math.isfinite
        return (not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)
                and (x > minimo if estricto else x >= minimo))
    except OverflowError:
        return False


def problemas_url(url: str) -> list[str]:
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or (p.hostname or "") not in HOSTS:
        return [f"URL fuera de los dominios admitidos: {url}"]
    return []


def pedible(url: str) -> bool:
    return "<" not in url and not any(x in url for x in NO_PEDIR)


def _regiones(regs: object, donde: str) -> list[str]:
    if not isinstance(regs, list) or not regs:
        return [f"{donde}: lista de regiones vacía o no es lista"]
    return [f"{donde}: región {r!r} fuera de la lista blanca de la UE" for r in regs if r not in ip.REGIONES_UE]


def problemas_catalogo(cat: dict) -> list[str]:
    m: list[str] = []
    if cat.get("schema") != SCHEMA or cat.get("nube") != "aws" or cat.get("moneda") != "EUR":
        m.append("schema, nube o moneda distintos de los esperados")
    if cat.get("regiones_ue") != list(ip.REGIONES_UE):
        m.append(f"regiones_ue debe ser exactamente {list(ip.REGIONES_UE)}")
    if not isinstance(cat.get("version"), int) or isinstance(cat.get("version"), bool):
        m.append("version no es un entero")
    for u in sorted(_urls(cat)):
        m += problemas_url(u)
    factores = {}
    for f in cat.get("factores_estandar") or []:
        fid = f.get("id", "?")
        if fid in factores or not re.fullmatch(r"[a-z_]{3,40}\.[a-z_]{3,60}", str(fid)):
            m.append(f"factor {fid}: id repetido o con forma no válida")
        if not _finito(f.get("valor"), 0, estricto=True):
            m.append(f"factor {fid}: valor no finito o no positivo {f.get('valor')!r}")
        if f.get("tipo") not in ("oficial", "supuesto") or not f.get("justificacion") or not f.get("fuente_url"):
            m.append(f"factor {fid}: tipo, justificación o fuente ausentes")
        factores[fid] = f
    filas, ids = {}, set()
    for c in cat.get("componentes") or []:
        cid = c.get("id", "?")
        if cid in ids or not re.fullmatch(r"aws-[a-z0-9-]{2,40}", str(cid)):
            m.append(f"{cid}: id repetido o con forma no válida")
        ids.add(cid)
        filas[cid] = c
        if c.get("capa") not in CAPAS:
            m.append(f"{cid}: capa {c.get('capa')!r} fuera de {CAPAS}")
        for campo in ("nombre_oficial", "referencia_url", "referencia_titulo"):
            if not c.get(campo):
                m.append(f"{cid}: falta {campo}")
        if c.get("region_ue") not in ip.REGIONES_UE:
            m.append(f"{cid}: region_ue {c.get('region_ue')!r} fuera de la lista blanca de la UE")
        ps = {}
        for p in c.get("plantillas_precio") or []:
            pid, donde = p.get("id", "?"), f"{cid}/{p.get('id', '?')}"
            if pid in ps:
                m.append(f"{donde}: id repetido")
            ps[pid] = p
            m += [f"{donde}: {x}" for x in ip.problemas_filtro(p.get("filtro"))]
            d = dict(ip.condiciones(p.get("filtro")) or [])
            if d.get("regionCode") != c.get("region_ue"):
                m.append(f"{donde}: regionCode distinto de la region_ue de la fila")
            if d.get("servicecode") != c.get("servicecode_precios"):
                m.append(f"{donde}: servicecode distinto del servicecode_precios de la fila")
            if p.get("concepto") != d.get("usagetype"):
                m.append(f"{donde}: concepto distinto del usagetype del filtro")
            if p.get("divisor") != ip.divisor_de_unidad(p.get("unidad")):
                m.append(f"{donde}: divisor {p.get('divisor')!r} no es el de la unidad {p.get('unidad')!r}")
            if "por_defecto" in p and p["por_defecto"] is not True:
                m.append(f"{donde}: por_defecto solo true (o sin la clave)")
            if p.get("impulsor") == "tiempo":
                if p.get("periodo") not in ("hora", "mes") or "factor_estandar" in p:
                    m.append(f"{donde}: plantilla de tiempo con periodo hora|mes y sin factor_estandar")
                pi = p.get("por_instancia")
                if pi is not None and not (_finito(pi.get("valor"), 0, estricto=True) and pi.get("fuente_url")):
                    m.append(f"{donde}: por_instancia sin valor finito positivo o sin fuente")
            elif p.get("impulsor") == "volumen":
                if p.get("factor_estandar") not in factores and not p.get("sin_factor_motivo"):
                    m.append(f"{donde}: factor_estandar desconocido y sin sin_factor_motivo")
                for fa in p.get("factores_alternativos") or []:
                    if fa not in factores:
                        m.append(f"{donde}: factor alternativo desconocido {fa}")
            else:
                m.append(f"{donde}: impulsor {p.get('impulsor')!r} fuera de (tiempo, volumen)")
            cv = p.get("ciclo_vida")
            if p.get("modelo") and not (isinstance(cv, dict) and cv.get("fuente") and "retirada" in cv):
                m.append(f"{donde}: plantilla de modelo sin ciclo_vida con fuente y retirada")
        if ps and not c.get("servicecode_precios"):
            m.append(f"{cid}: plantillas sin servicecode_precios")
        for mo in c.get("medidores_obligatorios") or []:
            if mo not in ps:
                m.append(f"{cid}: medidor obligatorio {mo} sin plantilla")
        for r in c.get("reglas_medidores") or []:
            for x in (r.get("si_usa") or []) + (r.get("exige_uno_de") or []):
                if x not in ps:
                    m.append(f"{cid}: regla de medidores con plantilla desconocida {x}")
        niveles = {n.get("nivel"): n for n in c.get("niveles") or []}
        for n in niveles.values():
            for x in (n.get("plantillas") or []) + (n.get("medidores_obligatorios") or []):
                if x not in ps:
                    m.append(f"{cid}/{n.get('nivel')}: plantilla desconocida {x}")
            for r in n.get("razones_subida") or []:
                if r.get("tipo") != "caracteristica" or not r.get("palabras_clave") or not r.get("fuente") or not r.get("texto"):
                    m.append(f"{cid}/{n.get('nivel')}: razón {r.get('id')} sin tipo, palabras, fuente o texto")
        if niveles:
            npd = c.get("nivel_por_defecto") or {}
            if npd.get("nivel") not in niveles or not npd.get("fuente") or not npd.get("motivo"):
                m.append(f"{cid}: nivel_por_defecto ausente, sin fuente o fuera de sus niveles")
            for n in niveles:
                if n not in (c.get("disponibilidad") or {}):
                    m.append(f"{cid}: sin disponibilidad del nivel {n}")
        for n, dsp in (c.get("disponibilidad") or {}).items():
            m += _regiones(dsp.get("regiones"), f"{cid}: disponibilidad {n}")
            if not dsp.get("fuente") or not dsp.get("consultado"):
                m.append(f"{cid}: disponibilidad {n} sin fuente o fecha")
            if ps and c.get("region_ue") not in (dsp.get("regiones") or []):
                m.append(f"{cid}: la region_ue {c.get('region_ue')} no está en la disponibilidad {n}")
    for clave, campo in (("modelo_por_defecto", "plantillas"), ("computo_por_defecto", "plantillas")):
        b = cat.get(clave) or {}
        fila = filas.get(b.get("componente"))
        nombres = {p["id"]: p for p in (fila or {}).get("plantillas_precio") or []}
        if not fila or not b.get(campo) or any(x not in nombres for x in b.get(campo) or []):
            m.append(f"{clave}: componente o plantillas desconocidos")
        elif clave == "modelo_por_defecto" and not all(nombres[x].get("por_defecto") is True for x in b[campo]):
            m.append("modelo_por_defecto: sus plantillas deben llevar por_defecto true")
    if not cat.get("arquitecturas_referencia"):
        m.append("sin arquitecturas_referencia")
    return m


def problemas_referencias(cat: dict, ref: dict) -> list[str]:
    """El fichero de referencias cubre cada URL pedible del catálogo con HTTP 200 y casa en títulos."""
    m = []
    if ref.get("schema") != SCHEMA_REF:
        m.append("catalogo_referencias_aws.json: schema distinto del esperado")
    comprobadas = {u.get("url"): u for u in ref.get("urls") or []}
    for u in sorted(x for x in _urls(cat) if pedible(x)):
        e = comprobadas.get(u)
        if not e:
            m.append(f"URL sin comprobar en catalogo_referencias_aws.json: {u}")
        elif e.get("http") != 200 or not e.get("titulo") or e.get("errores"):
            m.append(f"URL comprobada con fallo: {u} ({e.get('http')}, {e.get('errores')})")
    esperados = {c["referencia_url"]: c["referencia_titulo"] for c in cat.get("componentes") or []}
    esperados.update({a["url"]: a["titulo"] for a in cat.get("arquitecturas_referencia") or []})
    for u, t in sorted(esperados.items()):
        if u in comprobadas and comprobadas[u].get("titulo") != t:
            m.append(f"título distinto del comprobado para {u}: catálogo «{t}», página «{comprobadas[u].get('titulo')}»")
    if [(a["id"], a["url"]) for a in ref.get("arquitecturas_referencia") or []] != \
            [(a["id"], a["url"]) for a in cat.get("arquitecturas_referencia") or []]:
        m.append("las arquitecturas de catalogo_referencias_aws.json no son las del catálogo")
    return m


def _miles(x: float) -> str:
    """Número en formato español sin notación científica: 5656 → «5.656», 0.000001 → «0,000001»."""
    return f"{x:,.10f}".rstrip("0").rstrip(".").replace(",", " ").replace(".", ",").replace(" ", ".")


def bloque(cat: dict) -> str:
    """Bloque de las instrucciones del experto generado desde el catálogo (nunca a mano)."""
    L = [BLOQUE_INICIO, ""]
    L.append(f"Regiones admitidas (lista blanca exacta de la UE): {', '.join(f'`{r}`' for r in cat['regiones_ue'])}. "
             f"Cualquier otra, incluidas `eu-west-2` (Londres), `eu-central-2` (Zúrich) y las zonas locales, se rechaza.")
    L.append("")
    L.append("| catalogo_id | Nombre oficial | También conocido como (nunca como `servicio`) | Capa | Región UE del precio | Disponible en |")
    L.append("|---|---|---|---|---|---|")
    for c in cat["componentes"]:
        regs = sorted(set().union(*[set(d["regiones"]) for d in (c.get("disponibilidad") or {}).values()]) or {"—"},
                      key=lambda r: (r not in ip.REGIONES_UE, r))
        L.append(f"| {c['id']} | {c['nombre_oficial']} | {'; '.join(c.get('alias') or []) or '—'} | {c['capa']} | "
                 f"{c['region_ue']} | {', '.join(regs)} |")
    L.append("")
    L.append("Factores estándar (el código hace la cuenta):")
    for f in cat["factores_estandar"]:
        L.append(f"- `{f['id']}` = {_miles(f['valor'])} {f['unidad']} ({f['tipo']}).")
    L.append("")
    mp, cp = cat["modelo_por_defecto"], cat["computo_por_defecto"]
    L.append(f"Modelo por defecto: {mp['nombre']} (`{mp['modelo']}`, perfil `{mp['perfil_inferencia']}`), plantillas "
             f"{', '.join(f'`{x}`' for x in mp['plantillas'])}, con `justificacion_nivel: null`. No hay otro modelo en el catálogo.")
    L.append(f"Cómputo por defecto: {cp['componente']} (nivel `{cp['nivel']}`), plantillas "
             f"{', '.join(f'`{x}`' for x in cp['plantillas'])}, con `justificacion_nivel: null`. Fuente: {cp['fuente_url']}.")
    L.append("")
    L.append("Plantillas por servicio (`id` impulsor [factor estándar] — qué mide). `T/h`: por hora (730 al mes); "
             "`T/mes`: por mes; `V/n`: volumen, el precio es por cada n unidades:")
    for c in cat["componentes"]:
        ps = c.get("plantillas_precio") or []
        if not ps:
            continue
        trozos = []
        for p in ps:
            if p["impulsor"] == "tiempo":
                t = f"`{p['id']}` T/{'h' if p['periodo'] == 'hora' else 'mes'}"
                if p.get("por_instancia"):
                    pi = p["por_instancia"]
                    t += f" [×{_miles(pi['valor'])} {pi['unidad']}]"
            else:
                t = f"`{p['id']}` V/{_miles(p['divisor'])}"
                t += f" [f={p['factor_estandar']}]" if p.get("factor_estandar") else " [sin f]"
                for fa in p.get("factores_alternativos") or []:
                    t += f" [o f={fa}]"
            if p.get("por_defecto"):
                t += " (por defecto)"
            trozos.append(f"{t} — {p['descripcion']}")
        L.append(f"- {c['nombre_oficial']} (`{c['id']}`): " + "; ".join(trozos) + ".")
    L.append("")
    L.append("Niveles de servicio (el marcado «por defecto» va con `justificacion_nivel: null`; otro, con una de sus razones y la cita que la cumple):")
    for c in cat["componentes"]:
        for n in c.get("niveles") or []:
            defecto = " (por defecto)" if (c.get("nivel_por_defecto") or {}).get("nivel") == n["nivel"] else ""
            razones = "; ".join(f"`{r['id']}` («{'» / «'.join(r['palabras_clave'])}»)" for r in n.get("razones_subida") or [])
            L.append(f"- {c['nombre_oficial']} `{n['nivel']}`{defecto}: plantillas {', '.join(f'`{x}`' for x in n['plantillas'])}"
                     + (f"; razones: {razones}" if razones else "") + ".")
    L.append("")
    L.append("Medidores obligatorios y reglas (si el componente lleva algún precio, lleva también estos):")
    for c in cat["componentes"]:
        mo = c.get("medidores_obligatorios") or []
        reglas = [f"con `{'`, `'.join(r['si_usa'])}` lleva uno de `{'`, `'.join(r['exige_uno_de'])}`"
                  for r in c.get("reglas_medidores") or []]
        if mo or reglas:
            L.append(f"- `{c['id']}`: " + "; ".join(([f"{', '.join(f'`{x}`' for x in mo)}"] if mo else []) + reglas) + ".")
    L.append("")
    L.append("Sin plantilla a propósito (no se valoran; el supuesto dice el motivo):")
    for c in cat["componentes"]:
        for nv in c.get("no_valorables") or []:
            L.append(f"- `{c['id']}`: {nv['concepto']} (`{nv['motivo']}`).")
    L.append("")
    L.append("Arquitecturas de referencia (`arquitectura_id`; el código pone su URL):")
    for a in cat["arquitecturas_referencia"]:
        L.append(f"- `{a['id']}`: {a['titulo']} — {a['cuando_usar']}")
    L.append("")
    L.append(BLOQUE_FIN)
    return "\n".join(L)


def problemas_instrucciones(cat: dict, texto: str) -> list[str]:
    if bloque(cat) not in texto:
        return [f"{INSTRUCCIONES.name}: el bloque generado no coincide con el catálogo (regenéralo con --bloque)"]
    return []


def comprobar_url(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            estado, final, cuerpo = r.status, r.geturl(), r.read()
    except urllib.error.HTTPError as e:
        estado, final, cuerpo = e.code, e.geturl() or url, b""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"url": url, "http": None, "final": None, "titulo": None, "errores": [f"red: {e!r}"]}
    t = re.search(rb"<title[^>]*>(.*?)</title>", cuerpo, re.S | re.I)
    titulo = " ".join(html.unescape(t.group(1).decode("utf-8", "replace")).split()) if t else None
    errores = [] if estado == 200 else [f"HTTP {estado}"]
    # Learn añade el idioma al redirigir (/en-us/…): misma ruta sin él (CONTRATOS.md §6.3).
    norm = lambda u: (urllib.parse.urlsplit(u).hostname,
                      re.sub(r"^/[a-z]{2}-[a-z]{2}(?=/)", "", urllib.parse.urlsplit(u).path).rstrip("/"))
    if norm(final) != norm(url):
        errores.append(f"redirige a {final}")
    if not titulo:
        errores.append("sin <title>")
    elif SOFT_404.search(titulo):
        errores.append(f"soft 404: {titulo!r}")
    return {"url": url, "http": estado, "final": final, "titulo": titulo, "errores": errores}


def comprobar_en_red(cat: dict, escribir: bool) -> list[str]:
    m, resultados = [], []
    for u in sorted(x for x in _urls(cat) if pedible(x)):
        r = comprobar_url(u)
        resultados.append(r)
        print(f"{'OK   ' if not r['errores'] else 'FALLA'} {r['http']} {u} | {r['titulo']!r} {'; '.join(r['errores'])}")
        m += [f"{u}: {e}" for e in r["errores"]]
    notas: list[str] = []
    ficheros: dict[tuple[str, str], dict] = {}
    ahora = datetime.datetime.now(datetime.timezone.utc)
    for k, _c, p in ip.plantillas(cat):
        d = dict(ip.condiciones(p["filtro"]) or [])
        try:
            par = (d["servicecode"], ip.region_ue(d["regionCode"]))
            if par not in ficheros:
                ficheros[par] = ip.descargar_fichero(par[0], par[1], notas)
            e = ip.resolver(k, p, ficheros[par], 1.0, ahora)  # tasa 1: aquí solo se comprueba que resuelve
            print(f"OK    precio {k}: {e['precio_origen']} USD / {e['unidad']}{' (tramos)' if 'tramos' in e else ''}")
        except (ip.ErrorInstantanea, KeyError) as ex:
            print(f"FALLA precio {k}: {ex}")
            m.append(str(ex))
    if escribir:
        if m:
            print("no se escribe catalogo_referencias_aws.json: hay fallos")
        else:
            ref = {"schema": SCHEMA_REF, "fecha": ahora.date().isoformat(),
                   "metodo": "GET sin credenciales (urllib), HTTP 200, sin redirigir a otra ruta y <title> literal",
                   "arquitecturas_referencia": cat["arquitecturas_referencia"],
                   "urls": [dict(r, fecha=ahora.date().isoformat()) for r in resultados]}
            REFERENCIAS.write_text(json.dumps(ref, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"escrito {REFERENCIAS}")
    return m


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--red", action="store_true", help="comprueba URL y plantillas contra las fuentes públicas")
    ap.add_argument("--escribir", action="store_true", help="con --red, guarda catalogo_referencias_aws.json")
    ap.add_argument("--bloque", action="store_true", help="imprime el bloque generado de las instrucciones y sale")
    a = ap.parse_args(argv)
    try:
        cat = leer_json(CATALOGO)
    except ValueError as e:
        print(f"FALLA catálogo ilegible: {e}")
        return 1
    if a.bloque:
        print(bloque(cat))
        return 0
    try:
        fallos = problemas_catalogo(cat)
    except (AttributeError, TypeError, KeyError) as e:  # Revisión: una forma mal tipada da FALLA, no una traza
        print(f"FALLA catálogo con forma no válida: {e!r}")
        return 1
    if a.red:
        fallos += comprobar_en_red(cat, a.escribir)
    try:
        fallos += problemas_referencias(cat, leer_json(REFERENCIAS))
    except (OSError, ValueError, AttributeError, TypeError, KeyError) as e:
        fallos.append(f"catalogo_referencias_aws.json ilegible o ausente: {e}")
    try:
        fallos += problemas_instrucciones(cat, INSTRUCCIONES.read_text(encoding="utf-8"))
    except OSError as e:
        fallos.append(f"instrucciones ilegibles o ausentes: {e}")
    for f in fallos:
        print(f"FALLA {f}")
    n = sum(len(c.get("plantillas_precio") or []) for c in cat["componentes"])
    print(f"catálogo AWS v{cat.get('version')}: componentes={len(cat['componentes'])} plantillas={n} fallos={len(fallos)}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
