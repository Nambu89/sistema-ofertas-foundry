"""I1.8 · papel P: réplicas para verificar_paquete.py (código propio, sin importar el núcleo).

Cada función de este fichero SUSTITUYE (o se añade) a la del mismo nombre en verificar_paquete.py y se pega tal cual:
los auxiliares que usan son los que la puerta ya tiene, importados aquí con su mismo nombre (la línea `from
verificar_paquete import …` desaparece al pegar). Prueba de igualdad con el núcleo: tests/test_i18_p_replicas.py.

| Réplica | Del núcleo | Hallazgo |
|---|---|---|
| `_precios_r` | `experto._completar_precios` | REV17-1: tramos sobre la cantidad agregada por plantilla |
| `errores_volumen_nivel_replica` (+ `_reglas_precio_replica`, `_niveles_r`, `filas_computo_r`, `por_defecto_r`) | `experto.errores_volumen_nivel` | REV17-7, REVERIF17-2 y REVERIF17-3 |
| `motivos_r` (+ `citas_cliente_r`, `nombra_servicio_r`) | `experto.errores_motivos` | REV17-3 |
| `ciclo_r` (+ `modelos_catalogo_r`, `modelos_en_r`) | `experto.errores_ciclo_vida` | REV17-2 |
| `conservacion_replica` | `experto.conservacion_efecto` | REV17-4 y REV17-5 |
"""
from __future__ import annotations

import pathlib
import re
import sys
from decimal import Decimal, InvalidOperation

_RAIZ = pathlib.Path(__file__).resolve().parents[3]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from verificar_paquete import (  # noqa: E402  (al pegar en la puerta, esta línea desaparece)
    HORAS_R, IMPULSORES_REPLICA, MARCA_R, PREF_AMPLIACION, PREF_ARQ, PREF_SERV, TIEMPO_R, _cantidad_dato,
    _compacto, _cuadra_replica, _d, _fila_replica, _fmt, _iguales_replica, _jn, _lineas_req_replica, _num_replica,
    _obj_replica, _plano_req_replica, _prefijo, _q, _raiz_r, _tokens, _txt, alias_servicio, articulo_r,
    base_casa_r, citas_dim_r, concepto_replica, contiene_frase, divisor_r, factor_r, fila_r, limite_r,
    numeros_replica, plantilla_precio_replica, plantilla_r, plantillas_auxiliar_replica, precios_auxiliares,
    ruta_learn_replica, sin_comillas_r, tramos_r, volumetria_replica)

# ── REV17-7: la cantidad de la base es el número de la cita que va con su unidad ─────────────────────────────────────
NUMERO_R = re.compile(r"\d[\d.,]*\d|\d")


def numero_r(tok: str):
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?", tok):
        return Decimal(tok.replace(".", "").replace(",", "."))
    return Decimal(tok) if re.fullmatch(r"\d+\.\d+", tok) else None


def con_su_unidad_r(cita, cantidad, palabras) -> bool:
    """Como nucleo.experto.cantidad_con_su_unidad: tras el número (hasta el siguiente) hay una palabra de la unidad; si
    tras él no queda ninguna, vale la que lo precede desde el número anterior."""
    texto, objetivo = cita if isinstance(cita, str) else "", _num_replica(cantidad)
    raices = [_raiz_r(t) for w in palabras if isinstance(w, str) for t in _tokens(w) if len(t) >= 4]
    if objetivo is None or not raices:
        return False
    marcas = list(NUMERO_R.finditer(texto))
    for k, m in enumerate(marcas):
        if numero_r(m.group(0)) != objetivo:
            continue
        fin = marcas[k + 1].start() if k + 1 < len(marcas) else len(texto)
        ventana = _tokens(texto[m.end():fin]) or _tokens(texto[marcas[k - 1].end() if k else 0:m.start()])
        if any(_raiz_r(t).startswith(r) for t in ventana for r in raices):
            return True
    return False


def _fila_de_hit(comp: dict, hit, catalogo: dict):
    """La fila de la plantilla del precio: la del componente o la del auxiliar que la trae."""
    if not hit[1]:
        return _fila_replica(catalogo, comp.get("catalogo_id"))
    for a in precios_auxiliares(catalogo):
        if (comp.get("catalogo_id") in (a.get("componentes") or [])):
            pls, fa = plantillas_auxiliar_replica(a, catalogo)
            if any(x is hit[0] for x in pls):
                return fa
    return None


def _reglas_precio_replica(p: dict, comp: dict, hit, citas: list, catalogo: dict) -> list[str]:
    pl, aux = hit
    div = pl.get("divisor")
    if pl.get("impulsor") not in IMPULSORES_REPLICA or not (
            isinstance(div, int) and not isinstance(div, bool) and div >= 1
            and (pl.get("impulsor") != "tiempo" or div == 1)):
        return ["plantilla_sin_impulsor"]
    cm, base = p.get("cantidad_mensual"), p.get("base_volumen")
    if cm is None:
        return [r for r, mal in (("referencia_auxiliar", aux),
                                 ("referencia_sin_depende", comp.get("motivo_no_valoracion") != "depende_del_volumen"),
                                 ("referencia_con_base", base is not None)) if mal]
    if pl.get("impulsor") == "tiempo":
        return ["base_en_tiempo"] if base is not None else []
    if base is None:
        return ["volumen_sin_base"]
    base = _obj_replica(base)
    reglas, cita = [], _plano_req_replica(sin_comillas_r(base.get("cita")))
    if cita not in citas:
        reglas.append("cita_no_literal")
    elif _num_replica(base.get("cantidad_base")) not in numeros_replica(cita):
        reglas.append("cantidad_no_en_cita")
    else:
        fila = _fila_de_hit(comp, hit, catalogo) or {}
        estado, std = factor_r(pl, fila, f"{fila.get('id')}/{pl.get('id')}", catalogo)
        palabras = list(std["bases"]) if estado == "ok" and std["bases"] else [base.get("unidad_base")]
        if not con_su_unidad_r(cita, base.get("cantidad_base"), palabras):
            reglas.append("cantidad_sin_su_unidad")
    if not _cuadra_replica(cm, base, div):
        reglas.append("cuenta_no_cuadra")
    return reglas


# ── REVERIF17-2 y REVERIF17-3: medidores por nivel, valor por defecto, clase cómputo y tope de instancias ─────────────
FILAS_COMPUTO_R = ("az-app-service", "az-functions", "az-container-apps", "az-logic-apps", "az-foundry-agent-service")


def _niveles_r(fila) -> list[dict]:
    salida = []
    for n in ((fila or {}).get("niveles") if isinstance(fila, dict) else None) or []:
        if not isinstance(n, dict):
            continue
        lims = (n.get("limites") if isinstance(n.get("limites"), list) else []) + [
            n.get(k) for k in ("limite_oficial", "limite") if isinstance(n.get(k), str)]
        tope = n.get("instancias_max")
        ok = isinstance(tope, int) and not isinstance(tope, bool) and tope >= 1
        ob = n.get("medidores_obligatorios")
        salida.append({"nombres": [_plano_req_replica(n.get(k)) for k in ("id", "nivel", "nombre")
                                   if isinstance(n.get(k), str)],
                       "plantillas": set(n["plantillas"]) if isinstance(n.get("plantillas"), list) else None,
                       "limites": [_plano_req_replica(x) for x in lims if isinstance(x, str) and x.strip()],
                       "fuente": n.get("fuente_url") if isinstance(n.get("fuente_url"), str) else n.get("fuente"),
                       "obligatorios": [x for x in ob if isinstance(x, str)] if isinstance(ob, list) else [],
                       "tope": None if tope is None else tope if ok else False})
    return salida


def filas_computo_r(catalogo: dict) -> tuple:
    filas = _obj_replica((catalogo or {}).get("computo_por_defecto")).get("filas")
    propias = tuple(x for x in filas if isinstance(x, str)) if isinstance(filas, list) else ()
    return propias or FILAS_COMPUTO_R


def _computo_defecto_r(fila, propias: list, catalogo: dict) -> bool:
    cp = (catalogo or {}).get("computo_por_defecto")
    return (isinstance(cp, dict) and isinstance(fila, dict) and fila.get("id") == cp.get("componente") and bool(propias)
            and set(propias) <= set(cp.get("plantillas") or []))


def por_defecto_r(fila, propias: list, catalogo: dict) -> bool:
    if _computo_defecto_r(fila, propias, catalogo):
        return True
    if not isinstance(fila, dict) or fila.get("id") in filas_computo_r(catalogo):
        return False
    nd = fila.get("nivel_por_defecto")
    nombre = _plano_req_replica(nd if isinstance(nd, str) else _obj_replica(nd).get("nivel"))
    niveles = _niveles_r(fila)
    elegido = next((n for n in niveles if nombre and nombre in n["nombres"]), None)
    if elegido is None or not elegido["plantillas"]:
        return False
    usadas = set(propias) & {i for n in niveles for i in (n["plantillas"] or set())}
    return bool(usadas) and usadas <= elegido["plantillas"]


def _reglas_jn_r(jn: dict, niveles: list, propias: list, citables: list) -> list[str]:
    nombre = _plano_req_replica(jn.get("nivel"))
    nivel = next((n for n in niveles if nombre in n["nombres"]), None)
    if nivel is None:
        return ["nivel_desconocido"]
    reglas = []
    if _plano_req_replica(jn.get("limite_oficial")) not in nivel["limites"]:
        reglas.append("limite_no_oficial")
    ruta = ruta_learn_replica(jn.get("fuente"))
    if not ruta or ruta != ruta_learn_replica(nivel["fuente"]) or not (
            _prefijo(ruta, PREF_ARQ) or _prefijo(ruta, PREF_SERV) or _prefijo(ruta, PREF_AMPLIACION)):
        reglas.append("fuente_no_oficial")
    if _plano_req_replica(sin_comillas_r(jn.get("requisito"))) not in citables:
        reglas.append("requisito_no_literal")
    de_niveles = {i for n in niveles for i in (n["plantillas"] or set())}
    if nivel["plantillas"] is not None and (set(propias) & de_niveles) - nivel["plantillas"]:
        reglas.append("nivel_distinto_del_precio")
    return reglas


def errores_volumen_nivel_replica(respuesta: dict, texto: object, requisitos: object,
                                  catalogo: dict) -> list[tuple[str, str]]:
    """[(id, regla)] de la decisión 4, en el orden de nucleo.experto.errores_volumen_nivel: precios y componentes."""
    comps = [x for x in respuesta.get("componentes") or [] if isinstance(x, dict)]
    por_id = {x.get("id"): x for x in comps}
    precios = [x for x in respuesta.get("precios") or [] if isinstance(x, dict)]
    estado, citas = volumetria_replica(requisitos, texto)
    hits = [plantilla_precio_replica(p, por_id.get(p.get("componente_id")), catalogo) for p in precios]
    salida = [(p.get("id"), r) for p, h in zip(precios, hits) if h is not None and p.get("componente_id") in por_id
              for r in _reglas_precio_replica(p, por_id[p.get("componente_id")], h, citas, catalogo)]
    citables = citas_dim_r(requisitos, texto)
    for comp in comps:
        cid, jn = comp.get("id"), comp.get("justificacion_nivel")
        if comp.get("motivo_no_valoracion") == "depende_del_volumen":
            if estado == "CITADO":
                salida.append((cid, "depende_con_volumetria_citada"))
            if not any(p.get("componente_id") == cid and p.get("cantidad_mensual") is None and h is not None
                       and not h[1] for p, h in zip(precios, hits)):
                salida.append((cid, "depende_sin_precio_unitario"))
        propios = [(p, h[0]) for p, h in zip(precios, hits) if p.get("componente_id") == cid and h and not h[1]]
        propias = [pl.get("id") for _, pl in propios]
        fila = _fila_replica(catalogo, comp.get("catalogo_id"))
        niveles = _niveles_r(fila)
        oblig = [x for x in (fila or {}).get("medidores_obligatorios") or [] if isinstance(x, str)]
        oblig += [x for n in niveles if n["plantillas"] and set(propias) & n["plantillas"] for x in n["obligatorios"]]
        if propias and any(x not in propias for x in oblig):
            salida.append((cid, "falta_medidor_obligatorio"))
        computo = (isinstance(fila, dict) and fila.get("id") in filas_computo_r(catalogo) and bool(propios)
                   and not _computo_defecto_r(fila, propias, catalogo))
        sumas: dict = {}   # instancias por plantilla del componente: partir en líneas no esquiva el tope
        for p, pl in propios:
            veces = _num_replica(p.get("instancias")) if p.get("instancias") is not None else Decimal(1)
            if pl.get("impulsor") == "tiempo" and veces is not None:
                antes = sumas.get(pl.get("id"), (p.get("id"), pl, Decimal(0)))
                sumas[pl.get("id")] = (antes[0], pl, antes[2] + veces)
        varias = False
        for pid, pl, veces in sumas.values():
            nivel_p = next((n for n in niveles if n["plantillas"] and pl.get("id") in n["plantillas"]), None)
            tope = nivel_p["tope"] if nivel_p else None
            if tope is False:
                salida.append((pid, "instancias_max_no_valido"))
            elif tope and veces > tope:
                salida.append((pid, "instancias_sobre_limite"))
            varias = varias or (veces > 1 and (nivel_p is not None or computo))
        if not niveles:
            if computo:
                salida.append((cid, "computo_sin_niveles"))
            if jn is not None:
                salida.append((cid, "nivel_sin_catalogo"))
            continue
        if jn is None:
            if varias:
                salida.append((cid, "instancias_sin_justificar"))
            elif not por_defecto_r(fila, propias, catalogo):
                salida.append((cid, "nivel_sin_justificar"))
            continue
        salida += [(cid, r) for r in _reglas_jn_r(_obj_replica(jn), niveles, propias, citables)]
    return salida


# ── REV17-3: «a_cargo_del_cliente» solo con una entrada de «lo que el cliente ya tiene o paga» que nombre el servicio ─
CAMPO_CLIENTE_R = "ya_contratado_por_cliente"
SECCION_CLIENTE_R = "## Lo que el cliente ya tiene o paga"


def fuentes_cliente_r(requisitos, brief_texto) -> dict:
    """{texto citable: valor de la entrada de requisitos de la que sale}; sin requisitos, nada (falla cerrado)."""
    campos = requisitos.get("campos") if isinstance(requisitos, dict) else None
    datos = campos.get(CAMPO_CLIENTE_R) if isinstance(campos, dict) else None
    entradas = [_plano_req_replica(e.get("valor")) for e in (datos.get("entradas") if isinstance(datos, dict) else None)
                or [] if isinstance(e, dict) and e.get("origen") in ("CITADO", "ACLARACION")]
    vinetas, dentro = [], False
    for ln in _lineas_req_replica(brief_texto):
        if ln.startswith("#"):
            dentro = ln.strip() == SECCION_CLIENTE_R
        elif dentro and ln.startswith("- "):
            vinetas.append(_plano_req_replica(ln[2:]))
    salida = {}
    for v in entradas:
        if v and v not in salida:
            salida[v] = v
    if len(vinetas) == len(entradas):
        for vineta, valor in zip(vinetas, entradas):
            if vineta and valor and vineta not in salida:
                salida[vineta] = valor
    return salida


def servicios_nombrados_r(texto, catalogo: dict) -> list:
    duenos: dict = {}
    for fila in (catalogo or {}).get("componentes") or []:
        if isinstance(fila, dict):
            for a in alias_servicio(fila):
                duenos.setdefault(a, set()).add(fila.get("id"))
    toks, salida, i = _tokens(texto), [], 0
    while i < len(toks):
        fin, clave, acum = None, None, ""
        for j in range(i, len(toks)):
            acum += toks[j]
            if acum in duenos:
                fin, clave = j + 1, acum
            if not any(a.startswith(acum) for a in duenos):
                break
        if fin is None:
            i += 1
            continue
        salida.append(frozenset(duenos[clave]))
        i = fin
    return salida


def nombra_servicio_r(texto, comp: dict, catalogo: dict) -> bool:
    if fila_r(catalogo, comp.get("catalogo_id")) is not None:
        return frozenset({comp.get("catalogo_id")}) in servicios_nombrados_r(texto, catalogo)
    nombre = _compacto(comp.get("servicio"))
    return len(nombre) >= 5 and contiene_frase(texto, nombre)


def motivos_r(r: dict, catalogo: dict, requisitos, brief_texto) -> list[tuple]:
    """[(componente, regla)] de los motivos con condición (decisión del PM, REV16-1 c; REV17-3 en I1.8)."""
    comps = {c.get("id"): c for c in r.get("componentes") or [] if isinstance(c, dict)}
    fuentes = fuentes_cliente_r(requisitos, brief_texto)
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
            elif _plano_req_replica(sin_comillas_r(cita)) not in fuentes:
                salida.append((cid, "cita_cliente_no_literal"))
            elif not nombra_servicio_r(fuentes[_plano_req_replica(sin_comillas_r(cita))], c, catalogo):
                salida.append((cid, "cita_cliente_sin_servicio"))
        if m == "incluido_en_otro_componente":
            otro = comps.get(c.get("incluido_en"))
            if c.get("incluido_en") is None:
                salida.append((cid, "incluido_sin_componente"))
            elif otro is None or c.get("incluido_en") == cid:
                salida.append((cid, "incluido_inexistente"))
            else:
                fila = fila_r(catalogo, otro.get("catalogo_id")) or {}
                ok = any(isinstance(x, dict) and c.get("catalogo_id")
                         and (x.get("catalogo_id") or x.get("id")) == c.get("catalogo_id")
                         and any(isinstance(x.get(k), str) and x[k].strip() for k in ("fuente_url", "fuente"))
                         for x in fila.get("incluye") or [])
                if not ok:
                    salida.append((cid, "inclusion_no_declarada"))
    return salida


# ── REV17-2: el ciclo de vida mira también el modelo que nombra el sku del componente ──────────────────────────────
def modelos_catalogo_r(catalogo: dict) -> dict:
    salida: dict = {}
    for fila in (catalogo or {}).get("componentes") or []:
        for pl in (fila.get("plantillas_precio") if isinstance(fila, dict) else None) or []:
            m = pl.get("modelo") if isinstance(pl, dict) else None
            if not isinstance(m, str) or not _tokens(m):
                continue
            cv = pl.get("ciclo_vida") if isinstance(pl.get("ciclo_vida"), dict) else None
            if cv is None or (m in salida and salida[m] is None):
                salida[m] = None
                continue
            antes = salida.get(m) or {}
            gas = [x for x in (antes.get("ga"), cv.get("ga")) if x]
            rets = [x for x in (antes.get("retirada"), cv.get("retirada")) if x]
            salida[m] = {"ga": max(gas, key=str) if gas else None, "retirada": min(rets, key=str) if rets else None,
                         "fuente": antes.get("fuente") or cv.get("fuente") or cv.get("fuente_url")}
    return salida


def modelos_en_r(texto, nombres) -> list[str]:
    formas = sorted(((n, _tokens(n)) for n in nombres if _tokens(n)), key=lambda x: -len(x[1]))
    toks, hallados, i = _tokens(texto), [], 0
    while i < len(toks):
        hit = next(((n, t) for n, t in formas if toks[i:i + len(t)] == t), None)
        if hit and hit[0] not in hallados:
            hallados.append(hit[0])
        i += len(hit[1]) if hit else 1
    return hallados


def ciclo_r(guardada: dict, catalogo: dict, fecha, semanas) -> list[tuple]:
    """[(precio o componente, regla)]: por precio, retirada antes de fecha + Gantt + 12 meses, modelo no GA, o fila con
    ciclo sin el de la plantilla; por componente (REV17-2), el modelo que nombra el sku."""
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
    tabla = modelos_catalogo_r(catalogo)
    for cid, c in comps.items():
        nombrados = modelos_en_r(c.get("sku"), tabla)
        de_precios = []
        for p in guardada.get("precios") or []:
            if not isinstance(p, dict):
                continue
            hit = plantilla_r(p.get("plantilla_id"), c, catalogo) if p.get("componente_id") == cid else None
            m = hit[0].get("modelo") if hit and not hit[2] else None
            if isinstance(m, str) and m not in de_precios:
                de_precios.append(m)
        fila = fila_r(catalogo, c.get("catalogo_id")) or {}
        con_modelo = any(isinstance(x, dict) and isinstance(x.get("modelo"), str) for x in fila.get("plantillas_precio") or [])
        if con_modelo and de_precios and any(m not in de_precios for m in nombrados):
            salida.append((cid, "modelo_sku_distinto"))
        elif con_modelo and not de_precios and not nombrados:
            salida.append((cid, "modelo_sin_plantilla"))
        for m in nombrados:
            if m in de_precios:
                continue
            cv = tabla.get(m)
            if cv is None:
                salida.append((cid, "ciclo_vida_desconocido"))
                continue
            if cv.get("ga") and str(cv["ga"]) > str(fecha)[:10]:
                salida.append((cid, "modelo_no_disponible"))
            if cv.get("retirada") and (lim is None or str(cv["retirada"]) < lim.isoformat()):
                salida.append((cid, "modelo_retirado"))
    return salida


# ── REV17-4 y REV17-5: conservación por servicio, componente, plantilla y tipo (valorado o de referencia) ───────────
def _clave_cons_r(cat, cids, x: dict) -> tuple:
    if x.get("plantilla_id"):
        return (cat, cids, "plantilla", x["plantilla_id"], x.get("cantidad_mensual") is None)
    return (cat, cids, "filtro", " ".join(str(x.get("filtro") or "").split()), x.get("cantidad_mensual") is None)


def _suma_cons_r(valores: list) -> Decimal:
    total = Decimal(0)
    for v in valores:
        d = _cantidad_dato(v)
        if d is None:
            raise ValueError("cantidad nula en un grupo valorado")
        total += d
    return total


def conservacion_replica(respuesta: dict, conservar: object) -> list[tuple[str, str]]:
    """Réplica propia de nucleo.experto.conservacion_efecto (I1.8): [(etiqueta, regla)] por cada servicio, componentes,
    plantilla y tipo que el brief manda conservar: «conservado_ausente» o «conservado_cambiado» (solo los valorados);
    «conservar_forma» si el dato no es lista o un elemento no trae clave, cantidad o componente_ids."""
    if conservar is None:
        return []
    if not isinstance(conservar, list):
        return [("conservar_precios", "conservar_forma")]
    salida, pedidos = [], {}
    for n, cp in enumerate(conservar):
        cids = cp.get("componente_ids") if isinstance(cp, dict) else None
        legado = isinstance(cp, dict) and "componente_ids" not in cp   # dato de I1.6: todos los de su catalogo_id
        if (not isinstance(cp, dict) or not (cp.get("plantilla_id") or cp.get("filtro")) or "cantidad_mensual" not in cp
                or (not legado and (not isinstance(cids, list) or not cids or not all(isinstance(x, str) for x in cids)))):
            salida.append((f"conservar_precios[{n}]", "conservar_forma"))
            continue
        pedidos.setdefault(_clave_cons_r(cp.get("catalogo_id"), None if legado else tuple(sorted(set(cids))), cp),
                           []).append(cp.get("cantidad_mensual"))
    try:
        esperados = {k: None if k[4] else _suma_cons_r(v) for k, v in pedidos.items()}
    except (ValueError, ArithmeticError):
        return salida + [("conservar_precios", "conservar_forma")]
    comps = {x.get("id"): x for x in respuesta.get("componentes") or [] if isinstance(x, dict)}
    precios = [x for x in respuesta.get("precios") or [] if isinstance(x, dict)]
    for (cat, cids, tipo, valor, ref), esperado in esperados.items():
        etiqueta = f"{cat} · {valor}" + (f" · {', '.join(cids)}" if cids else "") + (" (precio de referencia)" if ref else "")
        hay = [x for x in precios if (cids is None or x.get("componente_id") in cids) and _clave_cons_r(
            _obj_replica(comps.get(x.get("componente_id"))).get("catalogo_id"), None, x) == (cat, None, tipo, valor, ref)]
        if not hay:
            salida.append((etiqueta, "conservado_ausente"))
            continue
        if ref:
            continue
        try:
            obtenido = _suma_cons_r([x.get("cantidad_mensual") for x in hay])
        except (ValueError, ArithmeticError):
            salida.append((etiqueta, "conservado_cambiado"))
            continue
        try:
            igual = _iguales_replica(esperado, obtenido)
        except InvalidOperation:
            igual = esperado == obtenido
        if not igual:
            salida.append((etiqueta, "conservado_cambiado"))
    return salida


# ── REV17-1: tramos sobre la cantidad agregada por plantilla (sustituye a _precios_r) ──────────────────────────────
def _precios_r(r: dict, comps: dict, catalogo: dict, inst: dict, citas: list[str], fallos: list, anota, modelos: list):
    listos: list = []
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
        concepto, div = concepto_replica(pl), divisor_r(pl)
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
            pi = pl.get("por_instancia")  # PR17-5 (arreglos I1.7): unidades por instancia de la plantilla
            ud = (" ".join(pi["unidad"].split()) if isinstance(pi, dict) and isinstance(pi.get("unidad"), str)
                  and pi["unidad"].strip() else None)
            por = _d(pi.get("valor")) if isinstance(pi, dict) else Decimal(1)
            if por is None or not Decimal(0) < por <= Decimal(1000) or (isinstance(pi, dict) and ud is None):
                fallos.append((pid, "por_instancia_no_valido"))
                continue
            cant = _q(horas * veces * por, "0.000001")
            if isinstance(pi, dict):
                sup = (f"{_fmt(veces)} instancia(s) × {_fmt(por)} ({ud}) × {_fmt(_q(horas, '0.0001'))} "
                       f"{'h' if horas == HORAS_R else texto} al mes")[:300]
            else:
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
                if _plano_req_replica(oc) not in citas:
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
        listos.append((p, art, cant, sup, {
            "plantilla": clave, "filtro": pl.get("filtro"), "moneda": inst.get("moneda"), "unidad": art.get("unidad"),
            "region": comp.get("region"), "effectiveStartDate": art.get("effectiveStartDate"), "concepto": concepto,
            "cantidad_mensual": None if cant is None else _jn(cant), "sha256_articulo": art.get("sha256_articulo"),
            "base_volumen": base}))
        cv = pl.get("ciclo_vida")
        if isinstance(cv, dict) and clave not in [m["plantilla"] for m in modelos]:
            modelos.append({"plantilla": clave, "ga": cv.get("ga"), "retirada": cv.get("retirada"),
                            "fuente": cv.get("fuente") or cv.get("fuente_url")})
    # REV17-1 (I1.8): tramos sobre la cantidad agregada de cada plantilla; cada línea lleva el precio medio del total
    por_plantilla: dict = {}
    for _p, art, cant, _s, campos in listos:
        if art.get("tramos") and cant is not None:
            por_plantilla.setdefault(campos["plantilla"], []).append(cant)
    for p, art, cant, sup, campos in listos:
        grupo = por_plantilla.get(campos["plantilla"]) if art.get("tramos") and cant is not None else None
        total = sum(grupo, Decimal(0)) if grupo else cant
        precio, tramos = tramos_r(total, art)
        if tramos:
            extra = f" sobre el total de la plantilla ({_fmt(total)} en {len(grupo)} líneas)" if grupo and len(grupo) > 1 else ""
            sup = f"{sup}; precio medio por tramos de Retail Prices{extra}"[:300]
        p.update(dict(campos, precio=precio, precio_tramos=tramos, supuesto_cantidad=sup))


# ── Solo para las pruebas (NO se pega en la puerta): completar_r de la puerta no cambia; aquí se enlaza con el
# _precios_r de este fichero para recomponer como lo hará la puerta una vez pegado. ───────────────────────────────────
def _enlazar_completar_r():
    import types
    import verificar_paquete as vp
    return types.FunctionType(vp.completar_r.__code__, {**vars(vp), "_precios_r": _precios_r}, "completar_r")


completar_r = _enlazar_completar_r()

