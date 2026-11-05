"""I1.9 · papel P: réplicas para verificar_paquete.py (se pegan tal cual; CAMBIOS-I19-P.md §7).

Cada función sustituye a la del mismo nombre en la puerta o se añade. Código propio, sin importar el núcleo: la línea
`from verificar_paquete import (…)` desaparece al pegar y el bloque final «Solo para las pruebas» no se pega. Prueba de
igualdad con el núcleo en tests/test_i19_p_replicas.py (cada caso adverso de tests/test_i19_p_*.py pasa por ella).
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

from verificar_paquete import (  # noqa: F401  (al pegar, desaparece: son de la propia puerta)
    DIM_ETQ_R, DIM_SEC_R, MARCA_R, NUMERO_R, PARES_COMILLAS_R, _compacto, _computo_defecto_r, _fila_replica, _num_replica,
    _obj_replica, _plano_req_replica, _plano_saas, _lineas_req_replica, _raiz_r,
    _SAAS_REPLICA, _tokens, ARQ_R, citas_dim_r, contiene_frase, es_contrato_experto_v1, es_contrato_experto_v2,
    es_contrato_experto_v3, fila_r, filas_computo_r, limite_r, modelos_catalogo_r, modelos_en_r, normalizar_para_cita,
    numero_r, plantilla_precio_replica, plantilla_r, reglas_medidores_r, servicios_nombrados_r, sin_comillas_r, url_r,
    volumetria_replica,
    # E19-2: auxiliares de _reglas_precio_replica y _precios_r (de la puerta)
    HORAS_R, IMPULSORES_REPLICA, TIEMPO_R, _cuadra_replica, _d, _fila_de_hit, _fmt, _jn, _q, _txt, articulo_r,
    base_casa_r, con_su_unidad_r, concepto_replica, divisor_r, factor_r, numeros_replica, tramos_r)

# ── I1.9 · recursos que el cliente ya tiene (PR18-1, VC18-2) ─────────────────────────────────────────────────────────
MOTIVO_EXISTENTE_R = "existente_del_cliente"
FRASE_SIN_COMPUTO_R = "La solución no tiene cómputo propio"
CAMPOS_REQ_R = ("objetivo", "nubes", "alcance_funcional", "canales_integraciones", "ubicacion_usuarios",
                "marco_normativo", "volumetria", "identidad_acl_origen", "red_privada", "tipo_suscripcion", "plazo",
                "presupuesto_orientativo", "idioma_oferta", "fuera_de_alcance", "ya_contratado_por_cliente")
DIM_I19_R = ("volumetria", "alcance_funcional", "identidad_acl_origen", "marco_normativo", "ubicacion_usuarios",
             "canales_integraciones")
# Etiqueta de cada línea de requisitos del brief y su campo (brief.ETIQUETAS_CONTEXTO, Objetivo, Nubes y las de DIM_ETQ_R)
ETQ_CAMPO_R = (("Volumetría: ", "volumetria"), ("Identidad y permisos del origen: ", "identidad_acl_origen"),
               ("Marco normativo: ", "marco_normativo"), ("Ubicación de los usuarios finales: ", "ubicacion_usuarios"),
               ("Red privada: ", "red_privada"), ("Tipo de suscripción: ", "tipo_suscripcion"), ("Plazo: ", "plazo"),
               ("Presupuesto orientativo: ", "presupuesto_orientativo"), ("Idioma de la oferta: ", "idioma_oferta"),
               ("Objetivo: ", "objetivo"), ("Nubes: ", "nubes"))


def es_existente_r(comp) -> bool:
    return isinstance(comp, dict) and (isinstance(comp.get("existente_del_cliente"), dict)
                                       or comp.get("motivo_no_valoracion") == MOTIVO_EXISTENTE_R)


def existentes_req_r(requisitos) -> dict:
    campos = requisitos.get("campos") if isinstance(requisitos, dict) else None
    datos = campos.get("ya_contratado_por_cliente") if isinstance(campos, dict) else None
    salida: dict = {}
    for e in (datos.get("entradas") if isinstance(datos, dict) else None) or []:
        if isinstance(e, dict) and isinstance(e.get("id"), str) and e.get("origen") in ("CITADO", "ACLARACION"):
            salida.setdefault(e["id"], e)
    return salida


def lineas_brief_existentes_r(requisitos, anon=None) -> list[str]:
    """Réplica de nucleo.experto.lineas_brief_existentes (la sección «Lo que el cliente ya tiene o paga» del brief)."""
    a = anon if callable(anon) else (lambda x: x)
    return [f"- {k} ({e.get('servicio_catalogo') or 'fuera del catálogo'}): «{a(_plano_req_replica(e.get('valor')))}». "
            f"Cita: «{a(_plano_req_replica(e.get('cita')))}»" for k, e in existentes_req_r(requisitos).items()]


def valorados_r(respuesta: dict, catalogo: dict) -> dict:
    comps = {c.get("id"): c for c in respuesta.get("componentes") or [] if isinstance(c, dict)}
    salida: dict = {}
    for p in respuesta.get("precios") or []:
        if not isinstance(p, dict) or p.get("cantidad_mensual") is None:
            continue
        hit = plantilla_precio_replica(p, comps.get(p.get("componente_id")), catalogo)
        if hit is not None and not hit[1]:
            salida.setdefault(p.get("componente_id"), []).append(hit[0].get("id"))
    return salida


def existentes_requisitos_r(entradas: list, catalogo) -> list[tuple]:
    """[(id de la entrada, regla)]: réplica de nucleo.suficiencia.reglas_existentes (una entrada por recurso)."""
    if not isinstance(catalogo, dict) or not isinstance(catalogo.get("componentes"), list):
        return [("—", "existente_sin_catalogo")]
    filas = {e.get("id") for e in catalogo["componentes"] if isinstance(e, dict)}
    servicios = {e.get("servicio_catalogo") for e in entradas if isinstance(e, dict)}
    vistos, avisados, salida = set(), set(), []
    for e in entradas:
        if not isinstance(e, dict):
            continue
        ex, sc, valor, cita = e.get("id"), e.get("servicio_catalogo"), e.get("valor"), e.get("cita")
        if ex in vistos:
            salida.append((ex, "existente_id_repetido"))
        vistos.add(ex)
        if not (isinstance(valor, str) and isinstance(cita, str)
                and normalizar_para_cita(valor) in normalizar_para_cita(cita)):
            salida.append((ex, "existente_valor_no_literal"))
        hits = servicios_nombrados_r(valor, catalogo)
        if sc is not None and sc not in filas:
            salida.append((ex, "existente_servicio_desconocido"))
        elif (sc is not None and (not hits or any(sc not in h for h in hits))) or (sc is None and hits):
            salida.append((ex, "existente_valor_otro_servicio"))
        for h in servicios_nombrados_r(cita, catalogo):
            if not (h & servicios) and h not in avisados:
                avisados.add(h)
                salida.append((ex, "existente_recurso_sin_entrada"))
    return salida


# ── I1.9 · nivel por defecto y razones de subida (VC18-1, PR18-3, VC18-5) ───────────────────────────────────────────
def _texto_r(x):
    return " ".join(x.split()) if isinstance(x, str) and x.strip() else None


def _dec_r(x):
    return _num_replica(x)


def razones_r(lista):
    """Réplica de nucleo.experto.razones_validas: [] sin razones, False si alguna está mal formada."""
    if lista is None:
        return []
    if not isinstance(lista, list):
        return False
    salida, ids = [], set()
    for r in lista:
        if not isinstance(r, dict):
            return False
        rid, fuente = _texto_r(r.get("id")), _texto_r(r.get("fuente")) or _texto_r(r.get("fuente_url"))
        campo = r.get("campo")
        if not rid or rid in ids or not fuente or not fuente.startswith("https://") or (
                campo is not None and campo not in CAMPOS_REQ_R):
            return False
        ids.add(rid)
        base = {"id": rid, "tipo": r.get("tipo"), "campo": campo, "fuente": fuente,
                "texto": _texto_r(r.get("texto")) or _texto_r(r.get("descripcion"))}
        if r.get("tipo") == "umbral":
            unidad, limite = r.get("unidad"), _dec_r(r.get("limite"))
            palabras = [unidad] if isinstance(unidad, str) else unidad
            if campo is None or limite is None or limite < 0 or not isinstance(palabras, list) or not palabras or \
                    not all(isinstance(w, str) and any(len(t) >= 4 for t in _tokens(w)) for w in palabras):
                return False
            cortas = r.get("unidad_corta")
            if cortas is not None and (not isinstance(cortas, list) or not all(
                    isinstance(w, str) and _tokens(w) for w in cortas)):
                return False
            salida.append({**base, "palabras": list(palabras), "cortas": list(cortas or []), "limite": limite,
                           "limite_json": r.get("limite")})
        elif r.get("tipo") == "caracteristica":
            claves = r.get("palabras_clave")
            if not isinstance(claves, list) or not claves or not all(isinstance(w, str) and _compacto(w) for w in claves):
                return False
            salida.append({**base, "palabras_clave": list(claves)})
        else:
            return False
    return salida


VENTANA_UNIDAD_R = 3


def numeros_con_unidad_r(cita, palabras, cortas=(), ventana=None) -> list:
    texto = cita if isinstance(cita, str) else ""
    raices = [_raiz_r(t) for w in palabras if isinstance(w, str) for t in _tokens(w) if len(t) >= 4]
    exactas = {t for w in cortas or () if isinstance(w, str) for t in _tokens(w)}
    if not raices and not exactas:
        return []
    marcas, salida = list(NUMERO_R.finditer(texto)), []
    for k, m in enumerate(marcas):
        n = numero_r(m.group(0))
        if n is None:
            continue
        fin = marcas[k + 1].start() if k + 1 < len(marcas) else len(texto)
        tras = _tokens(texto[m.end():fin])
        previas = _tokens(texto[marcas[k - 1].end() if k else 0:m.start()])
        if ventana is not None:
            v = ventana if ventana > 0 else 0
            tras = tras[:v]
            previas = previas[len(previas) - v:] if len(previas) > v else previas
        cerca = tras if tras else previas
        if any(_raiz_r(t).startswith(r) for t in cerca for r in raices) or set(cerca) & exactas:
            salida.append(n)
    return salida


NEGACIONES_R = frozenset({"no", "sin", "ni", "nunca", "tampoco", "ningun", "ninguna", "ninguno", "jamas"})
NO_SOLO_R = frozenset({"solo", "solamente", "unicamente"})
NEGACION_TRAS_R = 3


def _empiezos_r(toks: list, alias: str) -> list:
    salida = []
    for i in range(len(toks)):
        acum = ""
        for p in toks[i:]:
            acum += p
            if acum == alias:
                salida.append(i)
                break
            if not alias.startswith(acum):
                break
    return salida


CLAUSULA_R = re.compile(r"[.,;:!?](?=\s|$)|[¡¿()\[\]\n]")
ORACION_R = re.compile(r"[.;!?](?=\s|$)|[¡¿\n]")
CLAUSULA_NEG_R = re.compile(r"[.,;!?](?=\s|$)|[¡¿()\[\]\n]")


def _niega_r(toks: list, hasta: int) -> bool:
    for k in range(min(hasta, len(toks))):
        if toks[k] in NEGACIONES_R and not (toks[k] == "no" and k + 1 < len(toks) and toks[k + 1] in NO_SOLO_R):
            return True
    return False


def _largo_r(toks: list, i: int, alias: str) -> int:
    acum, j = "", i
    while acum != alias:
        acum += toks[j]
        j += 1
    return j


def afirmada_r(texto, frase) -> bool:
    alias = _compacto(frase)
    for oracion in ORACION_R.split(texto if isinstance(texto, str) else ""):
        partes = [_tokens(x) for x in CLAUSULA_NEG_R.split(oracion)]
        for j, toks in enumerate(partes):
            despues = []
            for x in partes[j + 1:]:
                despues.extend(x)
            for i in _empiezos_r(toks, alias):
                if not _niega_r(toks, i) and not _niega_r(toks[_largo_r(toks, i, alias):] + despues, NEGACION_TRAS_R):
                    return True
    return False


def dice_sin_computo_r(texto) -> bool:
    frase = _tokens(FRASE_SIN_COMPUTO_R)
    for clausula in CLAUSULA_R.split(texto if isinstance(texto, str) else ""):
        toks = _tokens(clausula)
        for i in range(len(toks) - len(frase) + 1):
            if toks[i:i + len(frase)] == frase and not set(toks[:i]) & NEGACIONES_R:
                return True
    return False


def razon_cumplida_r(razon: dict, cita) -> bool:
    if razon.get("tipo") == "umbral":
        return any(n > razon["limite"]
                   for n in numeros_con_unidad_r(cita, razon["palabras"], razon.get("cortas"), VENTANA_UNIDAD_R))
    if razon.get("tipo") == "caracteristica":
        return any(afirmada_r(cita, w) for w in razon["palabras_clave"])
    return False


def citas_campos_r(requisitos, brief_texto, campos, sin_asumido=False) -> list[str]:
    """Réplica de nucleo.experto.citas_de_campos."""
    salida = []
    datos = requisitos.get("campos") if isinstance(requisitos, dict) else None
    for k in campos:
        d = datos.get(k) if isinstance(datos, dict) else None
        if sin_asumido and isinstance(d, dict) and d.get("estado") == "ASUMIDO":
            continue
        for e in (d.get("entradas") if isinstance(d, dict) else None) or []:
            if isinstance(e, dict) and not (sin_asumido and e.get("origen") == "ASUMIDO"):
                salida.append(_plano_req_replica(e.get("valor")))
    sec = None
    for ln in _lineas_req_replica(brief_texto):
        if ln.startswith("#"):
            sec = DIM_SEC_R.get(ln.strip())
            continue
        if ln.startswith("- ") and sec:
            valor, campo = ln[2:], sec
        else:
            par = next(((ln[len(e):], k) for e, k in ETQ_CAMPO_R if ln.startswith(e)), None)
            if par is None:
                continue
            valor, campo = par
        if campo not in campos or (sin_asumido and valor.endswith(MARCA_R)):
            continue
        valor = valor[:-len(MARCA_R)] if valor.endswith(MARCA_R) else valor
        salida += [_plano_req_replica(valor)] + [_plano_req_replica(x) for x in valor.split("; ")]
    vistos = []
    for s in salida:
        if s and s not in vistos:
            vistos.append(s)
    return vistos


def _niveles_r(fila) -> list[dict]:
    """Sustituye a la de la puerta: lo mismo más "razones" (razones_r) y "etiqueta" (nivel, nombre o id)."""
    salida = []
    for n in ((fila or {}).get("niveles") if isinstance(fila, dict) else None) or []:
        if not isinstance(n, dict):
            continue
        lims = (n.get("limites") if isinstance(n.get("limites"), list) else []) + [
            n.get(k) for k in ("limite_oficial", "limite") if isinstance(n.get(k), str)]
        tope = n.get("instancias_max")
        ok = isinstance(tope, int) and not isinstance(tope, bool) and tope >= 1
        mn, vs = n.get("instancias_min"), n.get("instancias_validas")
        mn_ok = isinstance(mn, int) and not isinstance(mn, bool) and mn >= 1
        vs_ok = isinstance(vs, list) and bool(vs) and all(isinstance(x, int) and not isinstance(x, bool) and x >= 1
                                                          for x in vs)
        ob = n.get("medidores_obligatorios")
        salida.append({"nombres": [_plano_req_replica(n.get(k)) for k in ("id", "nivel", "nombre")
                                   if isinstance(n.get(k), str)],
                       "etiqueta": next((_plano_req_replica(n.get(k)) for k in ("nivel", "nombre", "id")
                                         if isinstance(n.get(k), str)), ""),
                       "plantillas": set(n["plantillas"]) if isinstance(n.get("plantillas"), list) else None,
                       "limites": [_plano_req_replica(x) for x in lims if isinstance(x, str) and x.strip()],
                       "fuente": n.get("fuente_url") if isinstance(n.get("fuente_url"), str) else n.get("fuente"),
                       "obligatorios": [x for x in ob if isinstance(x, str)] if isinstance(ob, list) else [],
                       "tope": None if tope is None else tope if ok else False,
                       "minimo": None if mn is None else mn if mn_ok else False,
                       "validas": None if vs is None else vs if vs_ok else False,
                       "razones": razones_r(n.get("razones_subida"))})
    return salida


def nivel_defecto_r(fila):
    """Réplica de nucleo.experto.nivel_por_defecto: el nivel por defecto solo con {nivel, fuente https}."""
    nd = _obj_replica(fila.get("nivel_por_defecto") if isinstance(fila, dict) else None)
    nombre, fuente = _plano_req_replica(nd.get("nivel")), _texto_r(nd.get("fuente")) or _texto_r(nd.get("fuente_url"))
    if not nombre or not fuente or not fuente.startswith("https://"):
        return None
    return next((n for n in _niveles_r(fila) if nombre in n["nombres"]), None)


def por_defecto_r(fila, propias: list, catalogo: dict) -> bool:
    """Sustituye a la de la puerta (I1.9: nivel_por_defecto con fuente)."""
    if _computo_defecto_r(fila, propias, catalogo):
        return True
    if not isinstance(fila, dict) or fila.get("id") in filas_computo_r(catalogo):
        return False
    elegido = nivel_defecto_r(fila)
    if elegido is None or not elegido["plantillas"]:
        return False
    usadas = set(propias) & {i for n in _niveles_r(fila) for i in (n["plantillas"] or set())}
    return bool(usadas) and usadas <= elegido["plantillas"]


def con_modelo_r(fila) -> bool:
    return isinstance(fila, dict) and any(isinstance(x, dict) and isinstance(x.get("modelo"), str)
                                          for x in fila.get("plantillas_precio") or [])


def modelo_defecto_r(catalogo):
    m = _obj_replica((catalogo or {}).get("modelo_por_defecto")).get("modelo")
    return m if isinstance(m, str) and m.strip() else None


def razones_modelo_r(catalogo: dict, modelo):
    vistas: dict = {}
    for fila in (catalogo or {}).get("componentes") or []:
        for p in (fila.get("plantillas_precio") if isinstance(fila, dict) else None) or []:
            if not isinstance(p, dict) or p.get("modelo") != modelo or "razones_subida" not in p:
                continue
            rs = razones_r(p.get("razones_subida"))
            if rs is False:
                return False
            for r in rs:
                if r["id"] in vistas and vistas[r["id"]] != r:
                    return False
                vistas[r["id"]] = r
    return list(vistas.values())


def _reglas_razon_r(jn: dict, razones, requisitos, brief_texto) -> list[str]:
    if razones is False:
        return ["razones_no_validas"]
    if not razones:
        return ["nivel_sin_razones"]
    razon = next((r for r in razones if r["id"] == jn.get("razon")), None)
    if razon is None:
        return ["razon_desconocida"]
    campos = (razon["campo"],) if razon["campo"] else DIM_I19_R
    cita = _plano_req_replica(sin_comillas_r(jn.get("cita")))
    if cita not in citas_campos_r(requisitos, brief_texto, campos, sin_asumido=True):
        return ["requisito_no_literal"]
    return [] if razon_cumplida_r(razon, cita) else ["razon_no_cumplida"]


def _reglas_modelo_r(propios: list, jn, requisitos, brief_texto, catalogo: dict) -> list[str]:
    usados = []
    for _, pl in propios:
        if isinstance(pl.get("modelo"), str) and pl.get("modelo") not in usados:
            usados.append(pl.get("modelo"))
    if not usados:
        return ["nivel_sin_catalogo"] if jn is not None else []
    defecto = modelo_defecto_r(catalogo)
    if defecto is None:
        return ["modelo_por_defecto_no_declarado"]
    otros = [m for m in usados if m != defecto]
    if not otros:
        return ["justificacion_sobrante"] if jn is not None else []
    if jn is None:
        return ["modelo_sin_justificar"]
    if len(otros) > 1 or _compacto(jn.get("nivel")) != _compacto(otros[0]):
        return ["nivel_desconocido"]
    return _reglas_razon_r(jn, razones_modelo_r(catalogo, otros[0]), requisitos, brief_texto)


def errores_volumen_nivel_replica(respuesta: dict, texto, requisitos, catalogo: dict) -> list[tuple[str, str]]:
    """Sustituye a la de la puerta: [(id, regla)] en el orden de nucleo.experto.errores_volumen_nivel (I1.9: un recurso
    del cliente no entra; nivel por defecto sin justificación, subida con razón de la lista cerrada y modelo)."""
    comps = [x for x in respuesta.get("componentes") or [] if isinstance(x, dict)]
    por_id = {x.get("id"): x for x in comps}
    precios = [x for x in respuesta.get("precios") or [] if isinstance(x, dict)]
    estado, citas = volumetria_replica(requisitos, texto)
    hits = [plantilla_precio_replica(p, por_id.get(p.get("componente_id")), catalogo) for p in precios]
    salida = [(p.get("id"), r) for p, h in zip(precios, hits) if h is not None and p.get("componente_id") in por_id
              for r in _reglas_precio_replica(p, por_id[p.get("componente_id")], h, citas, catalogo)]
    for comp in comps:
        cid, jn = comp.get("id"), comp.get("justificacion_nivel")
        jn = jn if jn is None else _obj_replica(jn)
        if es_existente_r(comp):
            continue
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
        falta = bool(propias) and any(x not in propias for x in oblig)
        valoradas = [pl.get("id") for p, pl in propios if p.get("cantidad_mensual") is not None]
        uno_de = 0
        for rm in (reglas_medidores_r(fila) if valoradas else []):
            if rm is False:
                salida.append((cid, "regla_medidores_no_valida"))
            elif set(valoradas) & set(rm["si_usa"]):
                falta = falta or any(x not in valoradas for x in rm["exige"])
                uno_de += bool(rm["exige_uno_de"] and not set(valoradas) & set(rm["exige_uno_de"]))
        if falta:
            salida.append((cid, "falta_medidor_obligatorio"))
        salida += [(cid, "falta_medidor_obligatorio")] * uno_de
        usa_nivel = any(n["plantillas"] is None for n in niveles) or bool(
            set(propias) & {i for n in niveles for i in (n["plantillas"] or set())})
        computo = (isinstance(fila, dict) and fila.get("id") in filas_computo_r(catalogo) and bool(propios)
                   and not _computo_defecto_r(fila, propias, catalogo) and (not niveles or usa_nivel))
        sumas: dict = {}
        for p, pl in propios:
            veces = _num_replica(p.get("instancias")) if p.get("instancias") is not None else Decimal(1)
            if pl.get("impulsor") == "tiempo" and veces is not None:
                antes = sumas.get(pl.get("id"), (p.get("id"), pl, Decimal(0)))
                sumas[pl.get("id")] = (antes[0], pl, antes[2] + veces)
        varias = False
        for pid, pl, veces in sumas.values():
            nivel_p = next((n for n in niveles if n["plantillas"] and pl.get("id") in n["plantillas"]), None)
            tope = nivel_p["tope"] if nivel_p else None
            mn, vs = (nivel_p["minimo"], nivel_p["validas"]) if nivel_p else (None, None)
            if tope is False or mn is False or vs is False:
                salida.append((pid, "instancias_max_no_valido"))
            else:
                if tope and veces > tope:
                    salida.append((pid, "instancias_sobre_limite"))
                if mn and veces < mn:
                    salida.append((pid, "instancias_bajo_minimo"))
                if vs and veces not in vs:
                    salida.append((pid, "instancias_no_admitidas"))
            varias = varias or (veces > 1 and (nivel_p is not None or computo))
        if not niveles:
            if computo:
                salida.append((cid, "computo_sin_niveles"))
            if con_modelo_r(fila):
                salida += [(cid, r) for r in _reglas_modelo_r(propios, jn, requisitos, texto, catalogo)]
            elif jn is not None:
                salida.append((cid, "nivel_sin_catalogo"))
            continue
        hace_falta = (computo or usa_nivel) and not por_defecto_r(fila, propias, catalogo)
        if jn is None:
            if varias:
                salida.append((cid, "instancias_sin_justificar"))
            elif hace_falta:
                salida.append((cid, "nivel_sin_justificar"))
            continue
        if not hace_falta and not varias:
            salida.append((cid, "justificacion_sobrante"))
            continue
        nivel = next((n for n in niveles if _plano_req_replica(jn.get("nivel")) in n["nombres"]), None)
        if nivel is None:
            salida.append((cid, "nivel_desconocido"))
            continue
        de_niveles = {i for n in niveles for i in (n["plantillas"] or set())}
        if nivel["plantillas"] is not None and (set(propias) & de_niveles) - nivel["plantillas"]:
            salida.append((cid, "nivel_distinto_del_precio"))
        salida += [(cid, r) for r in _reglas_razon_r(jn, nivel["razones"], requisitos, texto)]
    for p, h in zip(precios, hits):  # I1.9 (VC18-7)
        comp = por_id.get(p.get("componente_id"))
        if comp is None or h is None or es_existente_r(comp):
            continue
        op = opcional_r(h[0])
        if op is False:
            salida.append((p.get("id"), "opcional_no_valido"))
        elif op and op["por_defecto"] == "sin" and not opcional_cumplido_r(op["razones"], requisitos, texto):
            salida.append((p.get("id"), "opcional_sin_requisito"))
    return salida


def opcional_r(plantilla):
    o = plantilla.get("opcional") if isinstance(plantilla, dict) else None
    if o is None:
        return None
    if not isinstance(o, dict) or o.get("por_defecto") not in ("sin", "con"):
        return False
    razones = razones_r(o.get("razones"))
    if razones is False:
        return False
    return {"por_defecto": o["por_defecto"], "razones": razones}


def opcional_cumplido_r(razones: list, requisitos, texto) -> bool:
    for r in razones:
        campos = (r["campo"],) if r["campo"] else DIM_I19_R
        for cita in citas_campos_r(requisitos, texto, campos, sin_asumido=True):
            if razon_cumplida_r(r, cita):
                return True
    return False


def existentes_r(respuesta: dict, requisitos, catalogo: dict) -> list[tuple]:
    """[(componente, regla)]: réplica de nucleo.experto.errores_existentes (PR18-1, VC18-2)."""
    comps = [c for c in respuesta.get("componentes") or [] if isinstance(c, dict)]
    ex, usados, salida = existentes_req_r(requisitos), {}, []
    con_precio = {p.get("componente_id") for p in respuesta.get("precios") or [] if isinstance(p, dict)}
    for c in comps:
        cid, dato = c.get("id"), c.get("existente_del_cliente")
        if isinstance(dato, dict) != (c.get("motivo_no_valoracion") == MOTIVO_EXISTENTE_R):
            salida.append((cid, "existente_sin_motivo" if isinstance(dato, dict) else "motivo_sin_existente"))
        if not isinstance(dato, dict):
            continue
        e = ex.get(dato.get("entrada"))
        if e is None:
            salida.append((cid, "existente_desconocido"))
        else:
            if dato.get("entrada") in usados:
                salida.append((cid, "existente_repetido"))
            else:
                usados[dato.get("entrada")] = cid
            if e.get("servicio_catalogo") != c.get("catalogo_id"):
                salida.append((cid, "existente_otro_servicio"))
        if cid in con_precio:
            salida.append((cid, "existente_con_precio"))
        if c.get("justificacion_nivel") is not None:
            salida.append((cid, "existente_con_nivel"))
    por_servicio: dict = {}
    for k, e in ex.items():
        if isinstance(e.get("servicio_catalogo"), str):
            por_servicio.setdefault(e["servicio_catalogo"], []).append(k)
    valorados = valorados_r(respuesta, catalogo)
    for c in comps:
        exs = por_servicio.get(c.get("catalogo_id")) or []
        if es_existente_r(c) or not exs or not valorados.get(c.get("id")):
            continue
        dj = c.get("desviacion_justificada")
        if not (isinstance(dj, str) and any(re.search(r"(?<![\w-])" + re.escape(x) + r"(?![\w-])", dj) for x in exs)):
            salida.append((c.get("id"), "existente_valorado"))
    return salida


def es_computo_valorado_r(comp: dict, valoradas: list, catalogo: dict) -> bool:
    fila = _fila_replica(catalogo, comp.get("catalogo_id"))
    if not valoradas or not isinstance(fila, dict) or fila.get("id") not in filas_computo_r(catalogo):
        return False
    niveles = _niveles_r(fila)
    return (_computo_defecto_r(fila, valoradas, catalogo) or not niveles
            or any(n["plantillas"] is None or set(valoradas) & n["plantillas"] for n in niveles))


def _capa_r(comp: dict, catalogo: dict):
    return (_fila_replica(catalogo, comp.get("catalogo_id")) or {}).get("capa") or comp.get("capa")


def _nombra_r(texto, comp: dict, catalogo: dict) -> bool:
    """Como nombra_servicio_r de la puerta (I1.8)."""
    if fila_r(catalogo, comp.get("catalogo_id")) is not None:
        return frozenset({comp.get("catalogo_id")}) in servicios_nombrados_r(texto, catalogo)
    nombre = _compacto(comp.get("servicio"))
    return len(nombre) >= 5 and contiene_frase(texto, nombre)


def arquitectura_r(respuesta: dict, catalogo: dict) -> list[tuple]:
    """[(componente, regla)]: réplica de nucleo.experto.errores_arquitectura («canal_sin_computo», VC18-2, y
    «datos_sin_salida», VA18-4)."""
    comps = [c for c in respuesta.get("componentes") or [] if isinstance(c, dict)]
    por_id = {c.get("id"): c for c in comps}
    sups = [s for s in respuesta.get("supuestos") or [] if isinstance(s, dict)]
    flujos = [f for f in respuesta.get("flujos") or [] if isinstance(f, dict)]
    valorados, salida = valorados_r(respuesta, catalogo), []
    hay = any(not es_existente_r(c) and es_computo_valorado_r(c, valorados.get(c.get("id")) or [], catalogo)
              for c in comps)
    for c in comps:
        cid = c.get("id")
        if (not hay and _capa_r(c, catalogo) == "usuarios_canales" and valorados.get(cid) and not es_existente_r(c)
                and not any(dice_sin_computo_r(s.get("texto")) and cid in (s.get("hechos") or []) for s in sups)):
            salida.append((cid, "canal_sin_computo"))
        if _capa_r(c, catalogo) != "datos_conocimiento":
            continue
        sale = any((f.get("origen") == cid and f.get("destino") in por_id and f.get("destino") != cid)
                   or (f.get("destino") == cid and f.get("origen") in por_id and f.get("origen") != cid
                       and _capa_r(por_id[f.get("origen")], catalogo) != "datos_conocimiento") for f in flujos)
        if not sale and not any(cid in (s.get("hechos") or []) and _nombra_r(s.get("texto"), c, catalogo) for s in sups):
            salida.append((cid, "datos_sin_salida"))
    return salida


def region_exige_catalogo_replica(comp) -> bool:
    """Sustituye a la de la puerta: I1.9, un recurso del cliente (sin catalogo_id) no se despliega en una región."""
    return (isinstance(comp, dict) and not comp.get("catalogo_id") and comp.get("region") != "global"
            and not es_existente_r(comp))


MOTIVOS_NO_VALORACION_REPLICA = ("depende_del_volumen", "sin_medidor_publico", "a_cargo_del_cliente",
                                 "incluido_en_otro_componente", "licencia_fuera_de_azure", "fuera_del_catalogo",
                                 "existente_del_cliente")


def facturables_azure_replica(respuesta: dict, catalogo: dict) -> list[str]:
    """Sustituye a la de la puerta: I1.9, un recurso del cliente no es facturable para la propuesta."""
    cat = {e.get("id"): e for e in (catalogo or {}).get("componentes") or [] if isinstance(e, dict)}
    salida = []
    for comp in respuesta.get("componentes") or []:
        entrada = cat.get(comp.get("catalogo_id")) if comp.get("catalogo_id") else None
        if entrada is not None:
            facturable = bool(entrada.get("service_name_precios"))
        else:
            nombre = _plano_saas(comp.get("servicio"))
            facturable = not (_SAAS_REPLICA.search(nombre) and "azure" not in nombre.split())
        if facturable and comp.get("motivo_no_valoracion") != MOTIVO_EXISTENTE_R:
            salida.append(comp.get("id"))
    return salida


def es_contrato_experto_v4(resp) -> bool:
    """Respuesta de I1.7 o I1.8 (contrato v4): completada (con valoracion_nucleo) y sin existente_del_cliente en sus
    componentes. Se valida con historico/respuesta_experto_completa_v4 y FALLA en «experto» (puerta de su época)."""
    comps = resp.get("componentes") if isinstance(resp, dict) else None
    return (isinstance(comps, list) and bool(comps) and "valoracion_nucleo" in resp
            and not any(isinstance(x, dict) and "existente_del_cliente" in x for x in comps))


def nombre_esquema_experto(resp) -> str:
    """Sustituye a la de la puerta: desde I1.9, la v4 completada se valida con su histórico."""
    if es_contrato_experto_v1(resp):
        return "historico/respuesta_experto_v1"
    if es_contrato_experto_v2(resp):
        return "historico/respuesta_experto_v2"
    if es_contrato_experto_v3(resp):
        return "historico/respuesta_experto_v3"
    return "historico/respuesta_experto_completa_v4" if es_contrato_experto_v4(resp) else "respuesta_experto_completa"


def proyectar_r(guardada: dict) -> dict:
    """Sustituye a la de la puerta: I1.9, el ajuste de la cita es justificacion_nivel.cita (antes, .requisito)."""
    r = json.loads(json.dumps(guardada, ensure_ascii=False))
    v = r.pop("valoracion_nucleo", None) or {}
    antes = {a["campo"]: a["recibido"] for a in v.get("ajustes") or [] if isinstance(a, dict) and "campo" in a}
    r["referencias"] = [{k: y for k, y in x.items() if k != "origen"} for x in r.get("referencias") or []
                        if x.get("origen") == "experto"]
    for c in r.get("componentes") or []:
        for k in ("referencia_id", "motivo_cita"):
            if f"componentes.{c['id']}.{k}" in antes:
                c[k] = antes[f"componentes.{c['id']}.{k}"]
        k = f"componentes.{c['id']}.justificacion_nivel.cita"
        if k in antes and isinstance(c.get("justificacion_nivel"), dict):
            c["justificacion_nivel"]["cita"] = antes[k]
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


def completar_r(modelo: dict, catalogo: dict, inst: dict, requisitos, brief_texto):
    """Sustituye a la de la puerta (I1.9: justificacion_nivel.cita y recurso del cliente sin referencia).
    (completada, [(id, regla)]): lo que tiene que haber puesto el núcleo. La puerta compara la completada guardada
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
            nuevo = sin_comillas_r(j.get("cita"))  # I1.9: {nivel, razon, cita}
            anota(f"componentes.{c['id']}.justificacion_nivel.cita", j.get("cita"), nuevo,
                  "comillas que envolvían la cita")
            j["cita"] = nuevo
        fila = fila_r(catalogo, c.get("catalogo_id"))
        if fila is None:
            if c.get("referencia_id") is None and not es_existente_r(c):  # I1.9: un sistema del cliente
                fallos.append((c.get("id"), "referencia_sin_id"))
            continue
        tit = fila.get("referencia_titulo")  # PR17-1 (arreglos I1.7): el título publicado de su fila del catálogo
        tit = " ".join(tit.split()) if isinstance(tit, str) and tit.strip() else None
        rid = ref(fila["referencia_url"], tit, "catalogo") if fila.get("referencia_url") and tit else None
        if rid is None:
            fallos.append((c.get("id"), "catalogo_sin_referencia"))
            continue
        anota(f"componentes.{c['id']}.referencia_id", c.get("referencia_id"), rid, "referencia de su fila del catálogo")
        c["referencia_id"] = rid
    _precios_r(r, comps, catalogo, inst, citas_dim_r(requisitos, brief_texto), fallos, anota, modelos)
    return r, fallos


def ciclo_r(guardada: dict, catalogo: dict, fecha, semanas) -> list[tuple]:
    """Sustituye a la de la puerta (I1.9: un recurso del cliente no se comprueba). [(precio o componente, regla)]: por precio, retirada antes de fecha + Gantt + 12 meses, modelo no GA, o fila con
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
        if es_existente_r(c):
            continue  # I1.9 (PR18-1): el sku de un recurso del cliente es suyo
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

# ── I1.9 · E19-2 (PR18-5): el factor por la base de la cita ─────────────────────────────────────────────────────────
def factores_alt_r(pl: dict, fila: dict, catalogo: dict):
    """('ok', [factores]) | ('mal', None). Réplica de experto.factores_alternativos."""
    lista = pl.get("factores_alternativos")
    if lista is None:
        return "ok", []
    if not isinstance(lista, list) or not all(isinstance(x, str) and x.strip() for x in lista):
        return "mal", None
    todos = [x for grupo in (fila.get("factores_estandar"), (catalogo or {}).get("factores_estandar"))
             if isinstance(grupo, list) for x in grupo if isinstance(x, dict)]
    salida = []
    for fid in lista:
        hay = [x for x in todos if x.get("id") == fid]
        if len(hay) != 1:
            return "mal", None
        estado, f = factor_r({"factor_estandar": hay[0]}, {}, "", None)  # la misma validación que el estándar
        if estado != "ok" or not f["bases"]:
            return "mal", None
        salida.append(f)
    return "ok", salida


def factor_base_r(pl: dict, fila: dict, clave: str, catalogo: dict, cita, unidad):
    """('ok', factor) | ('no', None) | ('mal', None). Réplica de experto.factor_por_base: sin alternativos, factor_r;
    con ellos, el único (estándar o alternativo) cuya base casa con la cita y la unidad; ninguno, el estándar; varios,
    'mal' (falla cerrado)."""
    estado, std = factor_r(pl, fila, clave, catalogo)
    if estado != "ok":
        return estado, std
    e_alt, alternativos = factores_alt_r(pl, fila, catalogo)
    if e_alt != "ok":
        return "mal", None
    if not alternativos:
        return "ok", std
    if not std["bases"]:
        return "mal", None
    casan = [f for f in [std] + alternativos if base_casa_r(cita, unidad, f["bases"])]
    if len(casan) > 1:
        return "mal", None
    return "ok", (casan[0] if casan else std)


def _reglas_precio_replica(p: dict, comp: dict, hit, citas: list, catalogo: dict) -> list[str]:
    """Sustituye a la de la puerta (I1.9, E19-2: el factor por la base de la cita)."""
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
        estado, std = factor_base_r(pl, fila, f"{fila.get('id')}/{pl.get('id')}", catalogo, base.get("cita"),
                                    base.get("unidad_base"))  # E19-2
        palabras = list(std["bases"]) if estado == "ok" and std["bases"] else [base.get("unidad_base")]
        if not con_su_unidad_r(cita, base.get("cantidad_base"), palabras):
            reglas.append("cantidad_sin_su_unidad")
    if not _cuadra_replica(cm, base, div):
        reglas.append("cuenta_no_cuadra")
    return reglas


def _precios_r(r: dict, comps: dict, catalogo: dict, inst: dict, citas: list[str], fallos: list, anota, modelos: list):
    """Sustituye a la de la puerta (I1.9, E19-2: el factor por la base de la cita)."""
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
            estado, std = factor_base_r(pl, fila, clave, catalogo, base.get("cita"), base.get("unidad_base"))  # E19-2
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
