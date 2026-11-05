"""I1.7 · papel P: réplicas para verificar_paquete.py (las pega el integrador; CAMBIOS-I17-P.md §5).

Código propio, sin importar el núcleo: usa los auxiliares que la puerta ya tiene (`vp.valores_filtro`, `vp._tokens`,
`vp._plano_req_replica`, `vp._lineas_req_replica`, `vp.concepto_replica`, `vp.plantillas_auxiliar_replica`) y escribe
el resto. Prueba de igualdad con el núcleo en tests/test_i17_p_replicas.py. Al pegarlo, `vp.` desaparece.
"""
from __future__ import annotations

import datetime
import json
import math
import re
import urllib.parse
from decimal import ROUND_HALF_UP, Decimal

import verificar_paquete as vp

EDAD_MAXIMA_DIAS_R = 31
HORAS_R = Decimal(730)
TIEMPO_R = {"1 Hour": (HORAS_R, "h"), "1/Hour": (HORAS_R, "h"), "1 GiB Hour": (HORAS_R, "GiB·h"),
            "1/Day": (HORAS_R / 24, "días"), "1/Month": (Decimal(1), "mes")}
DIM_R = ("volumetria", "alcance_funcional", "identidad_acl_origen", "marco_normativo", "ubicacion_usuarios",
         "canales_integraciones")
DIM_ETQ_R = (("Volumetría: ", "volumetria"), ("Identidad y permisos del origen: ", "identidad_acl_origen"),
             ("Marco normativo: ", "marco_normativo"), ("Ubicación de los usuarios finales: ", "ubicacion_usuarios"))
DIM_SEC_R = {"## Alcance funcional": "alcance_funcional", "## Canales e integraciones": "canales_integraciones"}
PARES_COMILLAS_R = ("«»", '""', "“”", "''", "‘’", "„“")
ARQ_R = ("/azure/architecture", "/azure/well-architected", "/azure/cloud-adoption-framework", "/azure/ai-foundry",
         "/azure/foundry")
MARCA_R = " [ASUMIDO, confianza baja]"


def _d(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return Decimal(str(x))


def _jn(d: Decimal):
    return int(d) if d == d.to_integral_value() else float(d)


def _txt(d) -> str:
    return str(d) if _d(d) is None else f"{_d(d).normalize():f}".replace(".", ",")


def _fmt(d: Decimal) -> str:
    return f"{d.normalize():f}".replace(".", ",")


def sin_comillas_r(t):
    if not isinstance(t, str):
        return t
    s = t.strip()
    for par in PARES_COMILLAS_R:
        a, b = par[0], par[1]
        if len(s) > 1 and s[0] == a and s[-1] == b and a not in s[1:-1] and b not in s[1:-1]:
            return s[1:-1].strip()
    return t


def url_r(url) -> str:
    """Igual que la normalización §6.3 del núcleo: '' si no es https://learn.microsoft.com/…"""
    try:
        u = urllib.parse.urlsplit((url if isinstance(url, str) else "").strip())
        if u.port is not None:
            return ""
    except ValueError:
        return ""
    if u.scheme.lower() != "https" or (u.hostname or "").lower() != "learn.microsoft.com" or "@" in u.netloc:
        return ""
    trozos = [x for x in urllib.parse.unquote(u.path).lower().split("/") if x]
    if "." in trozos or ".." in trozos:
        return ""
    if trozos and re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})+", trozos[0]):
        trozos = trozos[1:]
    return "https://learn.microsoft.com/" + "/".join(trozos) if trozos else ""


def articulo_r(inst: dict, fila: dict, pl: dict):
    arts = inst.get("plantillas") if isinstance(inst, dict) else None
    if not isinstance(arts, dict):
        return None
    a = arts.get(f"{fila.get('id')}/{pl.get('id')}")
    a = arts.get(pl.get("id")) if a is None else a
    return a if isinstance(a, dict) and a.get("filtro") == pl.get("filtro") else None


def fila_r(catalogo: dict, cid):
    return next((e for e in (catalogo or {}).get("componentes") or [] if isinstance(e, dict) and cid
                 and e.get("id") == cid), None)


def plantilla_r(pid, comp, catalogo: dict):
    """(plantilla, fila, auxiliar, clave) o None: la fila del componente primero; después cada auxiliar que lo acompaña."""
    propia = fila_r(catalogo, (comp or {}).get("catalogo_id"))
    if propia is None or not isinstance(pid, str):
        return None
    pref, _, suelto = pid.rpartition("/")
    opciones = [(propia, False, None)]
    for a in (catalogo or {}).get("precios_auxiliares") or []:
        if isinstance(a, dict) and propia.get("id") in (a.get("componentes") or []):
            pls, fa = vp.plantillas_auxiliar_replica(a, catalogo)
            if fa:
                opciones.append((fa, True, {x.get("id") for x in pls}))
    for fila, aux, permitidas in opciones:
        for pl in fila.get("plantillas_precio") or []:
            if isinstance(pl, dict) and (permitidas is None or pl.get("id") in permitidas) \
                    and pl.get("id") == suelto and pref in ("", fila.get("id")):
                return pl, fila, aux, f"{fila.get('id')}/{pl.get('id')}"
    return None


def divisor_r(pl: dict):
    v = pl.get("divisor")
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        return None
    return None if pl.get("impulsor") == "tiempo" and v != 1 else v


def factor_r(pl: dict, fila: dict, clave: str, catalogo: dict):
    """('ok', factor) | ('no', None) | ('mal', None)."""
    todos = [(x, False) for x in fila.get("factores_estandar") or [] if isinstance(x, dict)]
    todos += [(x, True) for x in (catalogo or {}).get("factores_estandar") or [] if isinstance(x, dict)]
    propio = pl.get("factor_estandar")
    if isinstance(propio, dict):
        hay = [propio]
    elif isinstance(propio, str):
        hay = [x for x, _ in todos if x.get("id") == propio]
        if not hay:
            return "mal", None
    else:
        hay = []
        for x, global_ in todos:
            nombres = [x.get("plantilla")] + (x["plantillas"] if isinstance(x.get("plantillas"), list) else [])
            if clave in nombres or (not global_ and pl.get("id") in nombres):
                hay.append(x)
    if not hay:
        return "no", None
    if len(hay) != 1:
        return "mal", None
    f = hay[0]
    limpio = {k: " ".join(f[k].split()) if isinstance(f.get(k), str) and f[k].strip() else None
              for k in ("unidad", "justificacion", "fuente", "fuente_url", "caso_uso")}
    v = _d(f.get("valor"))
    if v is None or v <= 0 or not limpio["unidad"] or not limpio["justificacion"] or not (limpio["fuente"] or limpio["fuente_url"]):
        return "mal", None
    b = f.get("base")
    bases = [x for x in (b if isinstance(b, list) else [b]) if isinstance(x, str) and x.strip()]
    return "ok", {"v": v, "json": f.get("valor"), "unidad": limpio["unidad"], "justificacion": limpio["justificacion"],
                  "fuente": limpio["fuente"] or limpio["fuente_url"], "bases": bases, "caso_uso": limpio["caso_uso"]}


def citas_dim_r(requisitos, brief_texto) -> list[str]:
    salida = []
    campos = requisitos.get("campos") if isinstance(requisitos, dict) else None
    for k in DIM_R:
        datos = campos.get(k) if isinstance(campos, dict) else None
        for e in (datos.get("entradas") if isinstance(datos, dict) else None) or []:
            if isinstance(e, dict):
                salida.append(vp._plano_req_replica(e.get("valor")))
    sec = None
    for ln in vp._lineas_req_replica(brief_texto):
        if ln.startswith("#"):
            sec = DIM_SEC_R.get(ln.strip())
            continue
        valor = ln[2:] if (ln.startswith("- ") and sec) else next((ln[len(e):] for e, _ in DIM_ETQ_R if ln.startswith(e)), None)
        if valor is None:
            continue
        valor = valor[:-len(MARCA_R)] if valor.endswith(MARCA_R) else valor
        salida += [vp._plano_req_replica(valor)] + [vp._plano_req_replica(x) for x in valor.split("; ")]
    vistos = []
    for s in salida:
        if s and s not in vistos:
            vistos.append(s)
    return vistos


def _raiz_r(p: str) -> str:
    if p.endswith("es") and len(p) >= 6:
        return p[:-2]
    return p[:-1] if p.endswith("s") and len(p) >= 5 else p


def base_casa_r(cita, unidad, bases) -> bool:
    c = [_raiz_r(t) for t in vp._tokens(cita)]
    u = [_raiz_r(t) for t in vp._tokens(unidad)]
    if bases:
        r = [_raiz_r(t) for b in bases for t in vp._tokens(b) if len(t) >= 4]
        return any(x.startswith(y) for x in c for y in r) and any(x.startswith(y) for x in u for y in r)
    for w in u:
        if len(w) >= 4 and any(x.startswith(w) or (len(x) >= 4 and w.startswith(x)) for x in c):
            return True
    return False


def _q(d: Decimal, paso: str) -> Decimal:
    return d.quantize(Decimal(paso), rounding=ROUND_HALF_UP)


def tramos_r(cantidad, art: dict):
    """(precio de la línea, tramos copiados o None), como el núcleo: precio medio de la cantidad por tramos."""
    t = art.get("tramos")
    if not t:
        return art.get("precio_unitario"), None
    copia = [{"desde": x["desde"], "precio_unitario": x["precio_unitario"]} for x in t]
    if cantidad is None:
        return art.get("precio_unitario"), copia
    coste = Decimal(0)
    for i, x in enumerate(t):
        hasta = Decimal(str(t[i + 1]["desde"])) if i + 1 < len(t) else cantidad
        trozo = min(cantidad, hasta) - Decimal(str(x["desde"]))
        coste += trozo * Decimal(str(x["precio_unitario"])) if trozo > 0 else 0
    medio = coste / cantidad
    return (int(medio) if medio == medio.to_integral_value() else float(medio)), copia


def completar_r(modelo: dict, catalogo: dict, inst: dict, requisitos, brief_texto):
    """(completada, [(id, regla)]): lo que tiene que haber puesto el núcleo. La puerta compara la completada guardada
    con completar_r(proyectar_r(guardada), …) y FALLA si no es igual (LES-G-097: recompone y compara)."""
    r = json.loads(json.dumps(modelo, ensure_ascii=False))
    fallos, ajustes, modelos = [], [], []
    refs = r["referencias"]
    for x in refs:
        x["origen"] = "experto"
    usados = [int(x["id"][4:]) for x in refs if re.fullmatch(r"REF-\d\d", str(x.get("id")))]
    n = [max(usados) + 1 if usados else 1]
    f = str((catalogo or {}).get("fecha") or "")
    fecha = f if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f) else str(inst.get("fecha_consulta") or "")[:10]

    def anota(campo, antes, despues, motivo):
        if antes != despues:
            ajustes.append({"campo": campo, "recibido": antes, "puesto": despues, "motivo": motivo})

    def ref(url, titulo, origen):
        u = url_r(url)
        ya = next((x["id"] for x in refs if url_r(x.get("url")) == u), None)
        if ya or not u or n[0] > 99:
            return ya
        refs.append({"id": f"REF-{n[0]:02d}", "url": url, "titulo": titulo[:200], "fecha_consulta": fecha, "origen": origen})
        n[0] += 1
        return refs[-1]["id"]

    arq = next((a for a in (catalogo or {}).get("arquitecturas_referencia") or []
                if isinstance(a, dict) and a.get("id") == r.get("arquitectura_id")), None)
    val = {"instantanea": {"fecha_consulta": inst.get("fecha_consulta"), "fecha": str(inst.get("fecha_consulta") or "")[:10],
                           "sha256": inst.get("sha256"), "moneda": inst.get("moneda"), "fuente": inst.get("fuente")},
           "arquitectura": None, "ajustes": ajustes, "modelos": modelos}
    ruta = url_r(arq.get("url")) if arq else ""
    es_arq = bool(ruta) and any(ruta[len("https://learn.microsoft.com"):] == p
                                or ruta[len("https://learn.microsoft.com"):].startswith(p + "/") for p in ARQ_R)
    if arq is None:
        fallos.append((None, "arquitectura_desconocida"))
    elif not es_arq or not (isinstance(arq.get("titulo"), str) and arq["titulo"].strip()):
        fallos.append((None, "arquitectura_no_oficial"))
    else:
        val["arquitectura"] = {"id": arq["id"], "url": arq["url"], "titulo": arq["titulo"][:200],
                               "referencia_id": ref(arq["url"], arq["titulo"], "arquitectura")}
    r["valoracion_nucleo"] = val
    comps = {}
    for c in r.get("componentes") or []:
        comps[c.get("id")] = c
        if c.get("motivo_cita") is not None:
            nuevo = sin_comillas_r(c["motivo_cita"])
            anota(f"componentes.{c['id']}.motivo_cita", c["motivo_cita"], nuevo, "comillas que envolvían la cita")
            c["motivo_cita"] = nuevo
        if isinstance(c.get("justificacion_nivel"), dict):
            j = c["justificacion_nivel"]
            nuevo = sin_comillas_r(j.get("requisito"))
            anota(f"componentes.{c['id']}.justificacion_nivel.requisito", j.get("requisito"), nuevo,
                  "comillas que envolvían la cita")
            j["requisito"] = nuevo
        fila = fila_r(catalogo, c.get("catalogo_id"))
        if fila is None:
            if c.get("referencia_id") is None:
                fallos.append((c.get("id"), "referencia_sin_id"))
            continue
        rid = ref(fila["referencia_url"], f"{fila.get('nombre_oficial')} en Microsoft Learn", "catalogo") \
            if fila.get("referencia_url") else None
        if rid is None:
            fallos.append((c.get("id"), "catalogo_sin_referencia"))
            continue
        anota(f"componentes.{c['id']}.referencia_id", c.get("referencia_id"), rid, "referencia de su fila del catálogo")
        c["referencia_id"] = rid
    _precios_r(r, comps, catalogo, inst, citas_dim_r(requisitos, brief_texto), fallos, anota, modelos)
    return r, fallos


def _precios_r(r: dict, comps: dict, catalogo: dict, inst: dict, citas: list[str], fallos: list, anota, modelos: list):
    for p in r.get("precios") or []:
        pid, comp = p.get("id"), comps.get(p.get("componente_id"))
        if comp is None:
            continue
        hit = plantilla_r(p.get("plantilla_id"), comp, catalogo)
        if hit is None:
            fallos.append((pid, "plantilla_desconocida"))
            continue
        pl, fila, _aux, clave = hit
        corto = str(p.get("plantilla_id")).split("/")[-1]
        otro = plantilla_r(corto, comp, catalogo)
        if corto != p.get("plantilla_id") and otro is not None and otro[3] == clave:
            anota(f"precios.{pid}.plantilla_id", p.get("plantilla_id"), corto, "id de plantilla sin el prefijo de su fila")
            p["plantilla_id"] = corto
        art = articulo_r(inst, fila, pl)
        esperada = fila.get("region_precio") or fila.get("region_ue")
        if art is None or art.get("armRegionName") != esperada:
            fallos.append((pid, "sin_precio_en_instantanea" if art is None else "instantanea_otra_region"))
            continue
        if not fila.get("region_precio") and comp.get("region") != fila.get("region_ue"):
            fallos.append((pid, "region_sin_instantanea"))
            continue
        concepto, div = vp.concepto_replica(pl), divisor_r(pl)
        if concepto is None or pl.get("impulsor") not in ("tiempo", "volumen") or div is None:
            fallos.append((pid, "plantilla_sin_impulsor"))
            continue
        base, over, cant = p.get("base_volumen"), p.get("factor_override"), None
        if pl["impulsor"] == "tiempo":
            if base is not None or over is not None:
                fallos.append((pid, "base_en_tiempo"))
                continue
            if art.get("unidad") not in TIEMPO_R:
                fallos.append((pid, "unidad_tiempo_desconocida"))
                continue
            horas, texto = TIEMPO_R[art["unidad"]]
            veces = _d(p["instancias"]) if p.get("instancias") is not None else Decimal(1)
            cant = _q(horas * veces, "0.000001")
            sup = f"{_fmt(veces)} instancia(s) × {_fmt(_q(horas, '0.0001'))} {texto} al mes"
        elif p.get("instancias") is not None:
            fallos.append((pid, "instancias_en_volumen"))
            continue
        elif base is None:
            if over is not None:
                fallos.append((pid, "override_sin_base"))
                continue
            sup = "Precio unitario de referencia: no suma en el total; el componente se valora con el volumen real"
        else:
            cita = sin_comillas_r(base.get("cita"))
            anota(f"precios.{pid}.base_volumen.cita", base.get("cita"), cita, "comillas que envolvían la cita")
            base = dict(base, cita=cita)
            estado, std = factor_r(pl, fila, clave, catalogo)
            if isinstance(over, dict):
                oc = sin_comillas_r(over.get("cita"))
                anota(f"precios.{pid}.factor_override.cita", over.get("cita"), oc, "comillas que envolvían la cita")
                if vp._plano_req_replica(oc) not in citas:
                    fallos.append((pid, "override_cita_no_literal"))
                    continue
                v = _d(over.get("valor"))
                factor = {"valor": over.get("valor"),
                          "unidad": std["unidad"] if std else f"{base.get('unidad_base')} (factor)",
                          "justificacion": over.get("justificacion"), "fuente": f"requisito citado: «{oc}»"[:300],
                          "origen": "experto", "caso_uso": std["caso_uso"] if std else None}
            elif estado != "ok":
                fallos.append((pid, "factor_estandar_no_valido" if estado == "mal" else "factor_sin_estandar"))
                continue
            else:
                v = std["v"]
                factor = {"valor": std["json"], "unidad": std["unidad"], "justificacion": std["justificacion"],
                          "fuente": std["fuente"], "origen": "catalogo", "caso_uso": std["caso_uso"]}
            if not base_casa_r(base.get("cita"), base.get("unidad_base"), std["bases"] if std else []):
                fallos.append((pid, "base_no_casa"))
                continue
            bruto = _d(base.get("cantidad_base")) * v / Decimal(div)
            if abs(bruto) > Decimal("1e12"):
                fallos.append((pid, "cantidad_fuera_de_rango"))
                continue
            cant = _q(bruto, "0.000001")
            sup = (f"{_txt(base.get('cantidad_base'))} {base.get('unidad_base')} × {_txt(factor['valor'])} "
                   f"{factor['unidad']} ÷ {_txt(div)}")[:300]
            base = {"cita": base.get("cita"), "cantidad_base": base.get("cantidad_base"),
                    "unidad_base": base.get("unidad_base"), "factor": factor}
            if cant <= 0:
                fallos.append((pid, "cantidad_nula"))
                continue
        precio, tramos = tramos_r(cant, art)
        if tramos:
            sup = f"{sup}; precio medio por tramos de Retail Prices"[:300]
        p.update({"plantilla": clave, "filtro": pl.get("filtro"), "precio": precio, "precio_tramos": tramos,
                  "moneda": inst.get("moneda"), "unidad": art.get("unidad"), "region": comp.get("region"),
                  "effectiveStartDate": art.get("effectiveStartDate"), "concepto": concepto,
                  "cantidad_mensual": None if cant is None else _jn(cant), "supuesto_cantidad": sup,
                  "sha256_articulo": art.get("sha256_articulo"), "base_volumen": base})
        cv = pl.get("ciclo_vida")
        if isinstance(cv, dict) and clave not in [m["plantilla"] for m in modelos]:
            modelos.append({"plantilla": clave, "ga": cv.get("ga"), "retirada": cv.get("retirada"),
                            "fuente": cv.get("fuente") or cv.get("fuente_url")})


def proyectar_r(guardada: dict) -> dict:
    """Lo que escribió el modelo: sin lo que pone el núcleo y con lo recibido de cada ajuste."""
    r = json.loads(json.dumps(guardada, ensure_ascii=False))
    v = r.pop("valoracion_nucleo", None) or {}
    antes = {a["campo"]: a["recibido"] for a in v.get("ajustes") or [] if isinstance(a, dict) and "campo" in a}
    r["referencias"] = [{k: y for k, y in x.items() if k != "origen"} for x in r.get("referencias") or []
                        if x.get("origen") == "experto"]
    for c in r.get("componentes") or []:
        for k in ("referencia_id", "motivo_cita"):
            if f"componentes.{c['id']}.{k}" in antes:
                c[k] = antes[f"componentes.{c['id']}.{k}"]
        k = f"componentes.{c['id']}.justificacion_nivel.requisito"
        if k in antes and isinstance(c.get("justificacion_nivel"), dict):
            c["justificacion_nivel"]["requisito"] = antes[k]
    nuevos = []
    for p in r.get("precios") or []:
        q = {k: p.get(k) for k in ("id", "componente_id", "plantilla_id", "instancias", "base_volumen", "factor_override")}
        q["plantilla_id"] = antes.get(f"precios.{p['id']}.plantilla_id", q["plantilla_id"])
        if isinstance(q["base_volumen"], dict):
            b = q["base_volumen"]
            q["base_volumen"] = {"cita": antes.get(f"precios.{p['id']}.base_volumen.cita", b.get("cita")),
                                 "cantidad_base": b.get("cantidad_base"), "unidad_base": b.get("unidad_base")}
        if isinstance(q["factor_override"], dict):
            q["factor_override"] = dict(q["factor_override"], cita=antes.get(f"precios.{p['id']}.factor_override.cita",
                                                                             q["factor_override"].get("cita")))
        nuevos.append(q)
    r["precios"] = nuevos
    return r


def motivos_r(r: dict, catalogo: dict, requisitos, brief_texto) -> list[tuple]:
    """[(componente, regla)] de los motivos con condición (decisión del PM, REV16-1 c)."""
    comps = {c.get("id"): c for c in r.get("componentes") or [] if isinstance(c, dict)}
    citas = set(vp._plano_req_replica(x) for x in vp._valores_req_replica(requisitos, None))
    for ln in vp._lineas_req_replica(brief_texto):
        if ln.strip() and not ln.startswith("#"):
            t = ln[2:] if ln.startswith("- ") else ln
            t = next((t[len(e) + 2:] for e in vp.ETIQUETAS_BRIEF_REPLICA if t.startswith(e + ": ")), t)
            t = t[:-len(MARCA_R)] if t.endswith(MARCA_R) else t
            citas |= {vp._plano_req_replica(t)} | {vp._plano_req_replica(x) for x in t.split("; ")}
    citas.discard("")
    salida = []
    for cid, c in comps.items():
        m = c.get("motivo_no_valoracion")
        if m != "a_cargo_del_cliente" and c.get("motivo_cita") is not None:
            salida.append((cid, "motivo_cita_sobrante"))
        if m != "incluido_en_otro_componente" and c.get("incluido_en") is not None:
            salida.append((cid, "incluido_en_sobrante"))
        if m == "a_cargo_del_cliente":
            cita = c.get("motivo_cita")
            if not (isinstance(cita, str) and cita.strip()):
                salida.append((cid, "cliente_sin_cita"))
            elif vp._plano_req_replica(sin_comillas_r(cita)) not in citas:
                salida.append((cid, "cita_cliente_no_literal"))
        if m == "incluido_en_otro_componente":
            otro = comps.get(c.get("incluido_en"))
            if c.get("incluido_en") is None:
                salida.append((cid, "incluido_sin_componente"))
            elif otro is None or c.get("incluido_en") == cid:
                salida.append((cid, "incluido_inexistente"))
            else:
                fila = fila_r(catalogo, otro.get("catalogo_id")) or {}
                ok = any(isinstance(x, dict) and c.get("catalogo_id") and (x.get("catalogo_id") or x.get("id")) == c.get("catalogo_id")
                         and any(isinstance(x.get(k), str) and x[k].strip() for k in ("fuente_url", "fuente"))
                         for x in fila.get("incluye") or [])
                if not ok:
                    salida.append((cid, "inclusion_no_declarada"))
    return salida


def semanas_r(modelo: dict) -> int | None:
    """Semanas del Gantt (regla del 10-10-2026: por fase, máx(1, ⌈horas con holgura / (40 × perfiles)⌉))."""
    tareas = [t for t in modelo.get("tareas_propuestas") or [] if isinstance(t, dict)]
    total = 0
    for fase in dict.fromkeys(t.get("fase") for t in tareas):
        de = [t for t in tareas if t.get("fase") == fase]
        horas = Decimal(0)
        for t in de:
            b, g = _d(t.get("horas_base")), _d(t.get("reuniones_h"))
            if b is None or g is None:
                return None
            horas += b + _q(b * Decimal("0.2"), "1") + g
        perfiles = len({t.get("perfil") for t in de})
        total += max(1, int((horas / (40 * perfiles)).to_integral_value(rounding="ROUND_CEILING")))
    return total or None


def limite_r(fecha, semanas):
    try:
        d = datetime.date.fromisoformat(str(fecha)[:10]) + datetime.timedelta(days=7 * int(semanas or 0))
    except (ValueError, TypeError):
        return None
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def ciclo_r(guardada: dict, catalogo: dict, fecha, semanas) -> list[tuple]:
    """[(precio, regla)]: retirada antes de fecha + Gantt + 12 meses, modelo no GA, o fila con ciclo sin el de la plantilla."""
    comps = {c.get("id"): c for c in guardada.get("componentes") or [] if isinstance(c, dict)}
    lim, salida = limite_r(fecha, semanas), []
    for p in guardada.get("precios") or []:
        hit = plantilla_r(p.get("plantilla_id"), comps.get(p.get("componente_id")), catalogo)
        if hit is None:
            continue
        pl, fila = hit[0], hit[1]
        cv = pl.get("ciclo_vida")
        if not isinstance(cv, dict):
            if any(isinstance(x, dict) and "ciclo_vida" in x for x in fila.get("plantillas_precio") or []):
                salida.append((p.get("id"), "ciclo_vida_desconocido"))
            continue
        if cv.get("ga") and str(cv["ga"]) > str(fecha)[:10]:
            salida.append((p.get("id"), "modelo_no_disponible"))
        if cv.get("retirada") and (lim is None or str(cv["retirada"]) < lim.isoformat()):
            salida.append((p.get("id"), "modelo_retirado"))
    return salida
