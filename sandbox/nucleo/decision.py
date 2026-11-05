"""Decisiones del comercial y de los revisores (CONTRATOS.md §10 y §4.9).

Una decisión solo se registra si cita el hash_contenido recalculado en ese momento. Regenerar el
contenido cambia el hash y las decisiones anteriores dejan de valer solas. El sistema no envía
nada: estas líneas las copia el comercial de las respuestas de Responsable de preventa y Responsable de área.
"""
from __future__ import annotations

import datetime
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from nucleo import esquema
from nucleo import estado as est_mod
from nucleo import hashes
from nucleo.errores import EntradaInvalida, ReglaIncumplida, TransicionNoPermitida

TIPOS_REVISOR = ("APROBADA", "DEVUELTA")
TIPOS_FERNANDO = ("ENVIADA_REVISION", "CONFIRMA_STOP", "AJUSTE_COMERCIAL", "DESBLOQUEAR")
COMERCIAL, REVISOR, APROBADOR = "Responsable comercial", "Responsable de preventa", "Responsable de área"
INICIALES = {COMERCIAL: "RC", REVISOR: "RP", APROBADOR: "RA"}
# VER15-7 (I1.6): quienes firman decisiones. Sus nombres son términos sensibles del brief: un comentario de DEVUELTA
# que los cite llega al experto anonimizado (brief.terminos_anonimizacion).
NOMBRES_DECISIONES = (COMERCIAL, REVISOR, APROBADOR)
_AJUSTE = re.compile(r"^importe_eur=(-?\d+\.\d{2}); motivo=(.{10,})$", re.DOTALL)
_ENVIADA = re.compile(r"verificar_paquete(?:\.py)?\s+rc\s*=\s*0(?!\d)")
MIN_MOTIVO = 10


def _plegar(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn")
    return " ".join(t.lower().split())


def persona(nombre: str) -> str | None:
    """Nombre canónico de una de las tres personas (sin tildes ni mayúsculas) o None."""
    return next((p for p in (COMERCIAL, REVISOR, APROBADOR) if _plegar(p) == _plegar(nombre)), None)


def parsear_linea(linea: str) -> dict:
    """«DECISION | revisor | TIPO | AAAA-MM-DD | hash | comentarios» (el sexto campo admite «|»)."""
    if not isinstance(linea, str) or "\n" in linea.strip():
        raise EntradaInvalida("La decisión es una sola línea", [])
    partes = [p.strip() for p in linea.strip().split("|", 5)]
    if len(partes) == 5:
        partes.append("")
    if len(partes) != 6 or partes[0] != "DECISION":
        raise EntradaInvalida("Formato: DECISION | revisor | TIPO | AAAA-MM-DD | hash_contenido | comentarios",
                              [repr(linea[:200])])
    _, revisor, tipo, fecha, hash_citado, comentarios = partes
    errores = []
    canon = persona(revisor)
    if canon is None:
        errores.append(f"revisor desconocido: {revisor!r} (admitidos: {COMERCIAL}, {REVISOR}, {APROBADOR})")
    if tipo not in TIPOS_REVISOR + TIPOS_FERNANDO:
        errores.append(f"tipo no válido: {tipo!r}")
    try:
        f = datetime.date.fromisoformat(fecha)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
            raise ValueError(fecha)
    except ValueError:
        f = None
        errores.append(f"fecha no válida: {fecha!r} (AAAA-MM-DD)")
    if not re.fullmatch(r"[0-9a-f]{64}", hash_citado):
        errores.append(f"hash_contenido no válido: {hash_citado[:80]!r} (64 hexadecimales en minúsculas)")
    if errores:
        raise EntradaInvalida("Línea de decisión no válida", errores)
    comentarios = unicodedata.normalize("NFC", comentarios)
    return {"revisor": canon, "tipo": tipo, "fecha": f, "hash_citado": hash_citado, "comentarios": comentarios,
            "linea": f"DECISION | {canon} | {tipo} | {fecha} | {hash_citado} | {comentarios}"}


def _del_estado(estado: dict, tipo: str, revisor: str | None = None) -> list[dict]:
    return [d for d in estado["decisiones"] if d["tipo"] == tipo and d["version"] == estado["version"]
            and (revisor is None or d["revisor"] == revisor)]


def comentarios_devuelta(estado: dict) -> list[dict]:
    """PR14-6 (I1.5): los comentarios de la DEVUELTA que abrió la versión vigente (las decisiones DEVUELTA de la versión
    anterior), en orden. [] en la versión A. Cada uno: id, version (la devuelta), revisor y comentarios literales (NFC).
    El brief de la versión vigente los lleva para que el experto vea por qué se devolvió (brief.generar)."""
    v = estado.get("version")
    if not isinstance(v, str) or len(v) != 1 or not "B" <= v <= "Z":
        return []
    previa = chr(ord(v) - 1)
    return [{"id": d["id"], "version": d["version"], "revisor": d["revisor"], "comentarios": d["comentarios"]}
            for d in estado.get("decisiones") or [] if d.get("tipo") == "DEVUELTA" and d.get("version") == previa]


def vigente(estado: dict, tipo: str) -> dict | None:
    """Última decisión de ese tipo cuyo hash_citado es el hash_contenido vigente."""
    h = hashes.hash_contenido(estado)
    return next((d for d in reversed(estado["decisiones"]) if d["tipo"] == tipo and d["hash_citado"] == h), None)


def firmas(estado: dict) -> dict:
    """{"elaborado": {...}, "revisado": {...} | None, "aprobado": {...} | None} de la versión vigente
    (solo decisiones que citan el hash vigente)."""
    h = hashes.hash_contenido(estado)
    fecha_el = ((estado["carga"].get("estimacion") or {}).get("entrada") or {}).get("fecha")

    def firma(revisor: str) -> dict | None:
        d = next((x for x in reversed(_del_estado(estado, "APROBADA", revisor)) if x["hash_citado"] == h), None)
        return {"nombre": revisor, "iniciales": INICIALES[revisor], "fecha": d["fecha"]} if d else None

    return {"elaborado": {"nombre": COMERCIAL, "iniciales": INICIALES[COMERCIAL], "fecha": fecha_el},
            "revisado": firma(REVISOR), "aprobado": firma(APROBADOR)}


# (tipo, estado de partida) -> (revisor exigido, estado de llegada; None = el mismo)
_REGLAS = {
    ("ENVIADA_REVISION", "LISTA_PARA_REVISION"): (COMERCIAL, "EN_REVISION_PREVENTA"),
    ("APROBADA", "EN_REVISION_PREVENTA"): (REVISOR, "EN_APROBACION_AREA"),
    ("APROBADA", "EN_APROBACION_AREA"): (APROBADOR, "APROBADA"),
    ("DEVUELTA", "EN_REVISION_PREVENTA"): (REVISOR, "DEVUELTA_CON_COMENTARIOS"),
    ("DEVUELTA", "EN_APROBACION_AREA"): (APROBADOR, "DEVUELTA_CON_COMENTARIOS"),
    ("CONFIRMA_STOP", "STOP_PRESUPUESTO"): (COMERCIAL, "VERIFICADA"),
    ("AJUSTE_COMERCIAL", "VERIFICADA"): (COMERCIAL, None),
    ("AJUSTE_COMERCIAL", "STOP_PRESUPUESTO"): (COMERCIAL, None),
    ("DESBLOQUEAR", "BLOQUEADA"): (COMERCIAL, "__previo__"),
}


def registrar(estado: dict, linea: str, hoy: datetime.date) -> dict:
    """Valida la línea contra el estado y el hash vigente, la guarda (D-NNN) y transita (§10)."""
    d = parsear_linea(linea)
    e = estado["estado"]
    regla = _REGLAS.get((d["tipo"], e))
    if regla is None:
        admitidos = sorted(s for (t, s) in _REGLAS if t == d["tipo"])
        raise TransicionNoPermitida(f"Decisión {d['tipo']} no admitida en el estado {e}",
                                    [f"{d['tipo']} solo se admite en: {admitidos}"])
    revisor, destino = regla
    errores = []
    if d["revisor"] != revisor:
        errores.append(f"en {e}, {d['tipo']} la decide {revisor}, no {d['revisor']}")
    vigente_h = hashes.hash_contenido(estado)
    if d["hash_citado"] != vigente_h:
        errores.append(f"decisión rechazada: cita {d['hash_citado']}, vigente {vigente_h}")
    if d["fecha"] > hoy:
        errores.append(f"fecha futura: {d['fecha'].isoformat()} es posterior a hoy ({hoy.isoformat()})")
    fecha_el = ((estado["carga"].get("estimacion") or {}).get("entrada") or {}).get("fecha")
    if d["tipo"] in ("ENVIADA_REVISION", "APROBADA", "DEVUELTA") and fecha_el and d["fecha"].isoformat() < fecha_el:
        errores.append(f"fecha {d['fecha'].isoformat()} anterior a la de elaboración ({fecha_el})")
    if (d["tipo"], e) == ("APROBADA", "EN_APROBACION_AREA"):
        rev = next((x for x in reversed(_del_estado(estado, "APROBADA", REVISOR)) if x["hash_citado"] == vigente_h), None)
        if rev is None:
            errores.append("no hay revisión de Responsable de preventa vigente para esta versión")
        elif d["fecha"].isoformat() < rev["fecha"]:
            errores.append(f"la aprobación ({d['fecha'].isoformat()}) es anterior a la revisión ({rev['fecha']})")
    com = d["comentarios"]
    if d["tipo"] == "ENVIADA_REVISION" and not _ENVIADA.search(com):
        errores.append("ENVIADA_REVISION exige en los comentarios «verificar_paquete rc=0»")
    if d["tipo"] in ("DEVUELTA", "CONFIRMA_STOP", "DESBLOQUEAR") and len(com.strip()) < MIN_MOTIVO:
        errores.append(f"{d['tipo']} exige comentarios o motivo de al menos {MIN_MOTIVO} caracteres")
    if d["tipo"] == "AJUSTE_COMERCIAL" and not _AJUSTE.match(com):
        errores.append("AJUSTE_COMERCIAL exige «importe_eur=-1500.00; motivo=…» (dos decimales y motivo de ≥ 10 caracteres)")
    if errores:
        raise ReglaIncumplida(f"Decisión {d['tipo']} rechazada", errores)
    llegada = estado["estado_previo"] if destino == "__previo__" else (destino or e)
    registro = {"id": f"D-{len(estado['decisiones']) + 1:03d}", "linea": d["linea"], "revisor": d["revisor"],
                "tipo": d["tipo"], "fecha": d["fecha"].isoformat(), "hash_citado": d["hash_citado"],
                "comentarios": com, "version": estado["version"], "estado_antes": e, "estado_despues": llegada,
                "registrada_ts": est_mod.ahora_ts()}
    if d["tipo"] == "DEVUELTA":   # VER16-5 (I1.7): lo que se devuelve, antes de invalidar nada
        registro["version_devuelta"] = resumen_version(estado)
    errores = esquema.validar(registro, esquema.cargar("decision"))
    if errores:
        raise ReglaIncumplida("La decisión no cabe en su esquema", errores)
    if destino == "__previo__":
        est_mod.desbloquear(estado)
    elif destino is not None:
        est_mod.transitar(estado, "decision", destino)
    if d["tipo"] == "DEVUELTA":
        estado["version"] = est_mod.siguiente_version(estado["version"])
        estado["codigo"] = est_mod.codigo(estado)
        estado["ronda_verificacion"] = 0
        est_mod.invalidar_desde(estado, "devuelta")
    estado["decisiones"].append(registro)
    return registro


# R2 (LES-G-097.3): una decisión que mueve dinero no se acepta desde un estado que pudo escribir el modelo.
# Aquí solo queda TRAZADA; la puerta local (verificar_paquete.py) exige además la confirmación por línea de
# órdenes con el hash que cita la decisión.
UMBRAL_STOP_EUR = Decimal("100000.00")
OPCION_CONFIRMACION = {"CONFIRMA_STOP": "--confirmo-stop", "AJUSTE_COMERCIAL": "--confirmo-ajuste"}


def huella(d: dict) -> str:
    """SHA-256 de la línea literal de la decisión (UTF-8): la identifica sin depender del id."""
    return hashes.sha256_texto(d["linea"])


def confirmaciones_locales(estado: dict) -> list[dict]:
    """Confirmaciones locales que exigirá la puerta para la versión vigente, en orden: STOP y ajuste.

    Cada elemento: tipo, opcion, hash (el que se teclea en local: el hash_contenido VIGENTE, que es el que compara
    verificar_paquete.py), hash_decision (el que cita la decisión: el vigente en el STOP, el hash_base en el ajuste),
    decision_id (None si falta la decisión o no la respalda), huella_linea, linea y el importe (precio_eur del STOP o
    importe_eur del ajuste). Lista vacía si no hace falta."""
    est = estado["carga"].get("estimacion") or {}
    vigente_h = hashes.hash_contenido(estado)
    salida = []
    try:
        precio = Decimal(str((est.get("resumen") or {})["precio_cerrado_eur"]))
    except (KeyError, InvalidOperation):
        precio = None
    if precio is not None and precio > UMBRAL_STOP_EUR:
        d = vigente(estado, "CONFIRMA_STOP")
        salida.append({"tipo": "CONFIRMA_STOP", "opcion": OPCION_CONFIRMACION["CONFIRMA_STOP"],
                       "hash": vigente_h, "hash_decision": d["hash_citado"] if d else None,
                       "decision_id": d["id"] if d else None, "huella_linea": huella(d) if d else None,
                       "linea": d["linea"] if d else None, "precio_eur": f"{precio:.2f}"})
    aj = est.get("ajuste")
    if aj:
        d = next((x for x in estado["decisiones"] if x["id"] == aj["decision_id"]), None)
        valida = d is not None and d["tipo"] == "AJUSTE_COMERCIAL" and d["hash_citado"] == aj["hash_base"]
        salida.append({"tipo": "AJUSTE_COMERCIAL", "opcion": OPCION_CONFIRMACION["AJUSTE_COMERCIAL"],
                       "hash": vigente_h, "hash_decision": aj["hash_base"], "decision_id": d["id"] if valida else None,
                       "huella_linea": huella(d) if valida else None, "linea": d["linea"] if valida else None,
                       "importe_eur": aj["importe_eur"]})
    return salida


def orden_confirmacion(estado: dict) -> str:
    """Opciones que el comercial añade a verificar_paquete.py (vacía si no hacen falta)."""
    return " ".join(f"{c['opcion']} {c['hash']}" for c in confirmaciones_locales(estado))


# ───────────── VER16-5 (I1.7): cambios pedidos en la revisión anterior y cómo se atendieron ─────────────
TITULO_CAMBIOS = "Cambios pedidos en la revisión anterior"
_MAX_CAMBIOS = 40
MAX_COMENTARIO_PPTX = 280    # integrador I1.7: el PPTX lleva la sección en la diapositiva 2 (sitio acotado)
MAX_DIFERENCIAS_PPTX = 6
# Revisión (pasada 2 del integrador): también un entero de 100 o más sin moneda («1200 al mes»), con el mismo criterio que
# la exclusividad de importes de la puerta (toda cifra de 100 o más que no sea el precio o un hito)
_IMPORTE_COMENTARIO = re.compile(r"€|\bEUR\b|\beuros?\b|\d[.,]\d{2}\b|\d{3,}|\d{1,3}(?:[.,]\d{3})+", re.I)


def resumen_version(estado: dict) -> dict:
    """Lo que se devuelve en una DEVUELTA, calculado por el código: componentes (servicio, nivel y región), precios por
    efecto (cantidad mensual total por servicio del catálogo y plantilla), consumo mensual del anexo y precio cerrado.
    Lo guarda la decisión DEVUELTA (`version_devuelta`) para comparar con la versión siguiente."""
    from nucleo import verificacion  # diferido: verificacion importa brief, que importa este módulo
    carga = estado["carga"]
    resp = est_mod.registro_de_carga(carga).get("respuesta") or {}
    comps = [{"clave": c.get("catalogo_id") or f"desviación: {c.get('servicio')}", "sku": c.get("sku"),
              "region": c.get("region")} for c in resp.get("componentes") or [] if isinstance(c, dict)]
    precios = [{"clave": f"{cat} · {valor}", "cantidad_mensual": verificacion._numero_json(
                verificacion._sumar([p.get("cantidad_mensual") for p in ps]))}
               for (cat, _tipo, valor), ps in verificacion._grupos(resp).items()]
    resumen = (carga.get("estimacion") or {}).get("resumen") or {}
    salida = {"componentes": comps, "precios": precios,
              "consumo_mensual_eur": _texto_o_none((carga.get("anexo_consumo") or {}).get("total_mensual_eur")),
              "precio_cerrado_eur": _texto_o_none(resumen.get("precio_cerrado_eur"))}
    # VA18-3 (I1.9, CAMBIOS-I19-P §5.7): la estimación de la versión devuelta, para que la nota de la siguiente diga,
    # calculado por el código, la duración, las horas y los perfiles que cambian. Sin estimación no se guarda la clave
    # (la nota dice entonces AVISO_SIN_ESTIMACION, como con las DEVUELTA anteriores a I1.9).
    from nucleo import nota_revision  # diferido: nota_revision importa este módulo
    est = nota_revision.resumen_estimacion(estado)
    if est:
        salida["estimacion"] = est
    return salida


def _texto_o_none(x: object) -> str | None:
    return None if x is None else str(x)


def _diferencias(antes: dict, ahora: dict, con_importes: bool) -> list[str]:
    salida = []
    ca = {c["clave"]: c for c in antes.get("componentes") or []}
    cb = {c["clave"]: c for c in ahora.get("componentes") or []}
    for k in sorted(set(cb) - set(ca)):
        salida.append(f"Componente añadido: {k} ({cb[k].get('sku')}, {cb[k].get('region')})")
    for k in sorted(set(ca) - set(cb)):
        salida.append(f"Componente retirado: {k} ({ca[k].get('sku')}, {ca[k].get('region')})")
    for k in sorted(set(ca) & set(cb)):
        for campo, nombre in (("sku", "nivel"), ("region", "región")):
            if ca[k].get(campo) != cb[k].get(campo):
                salida.append(f"Cambio de {nombre} en {k}: de {ca[k].get(campo)} a {cb[k].get(campo)}")
    pa = {p["clave"]: p.get("cantidad_mensual") for p in antes.get("precios") or []}
    pb = {p["clave"]: p.get("cantidad_mensual") for p in ahora.get("precios") or []}
    # Sin importes (PPTX), tampoco cantidades: una cantidad con decimales parecería un importe y la puerta exige que
    # todo importe visible del PPTX sea el precio o un hito.
    for k in sorted(set(pb) - set(pa)):
        salida.append(f"Consumo añadido: {k}" + (f" ({pb[k]} al mes)" if con_importes else ""))
    for k in sorted(set(pa) - set(pb)):
        salida.append(f"Consumo retirado: {k}" + (f" ({pa[k]} al mes)" if con_importes else ""))
    salida += [f"Cantidad cambiada en {k}" + (f": de {pa[k]} a {pb[k]} al mes" if con_importes else "")
               for k in sorted(set(pa) & set(pb)) if pa[k] != pb[k]]
    if con_importes:
        for campo, nombre in (("consumo_mensual_eur", "Consumo mensual estimado"), ("precio_cerrado_eur", "Precio cerrado")):
            if antes.get(campo) != ahora.get(campo):
                salida.append(f"{nombre}: de {antes.get(campo) or 'sin dato'} € a {ahora.get(campo) or 'sin dato'} €")
    return salida


def cambios_pedidos(estado: dict, con_importes: bool = True) -> dict | None:
    """VER16-5: los comentarios de la DEVUELTA que abrió la versión vigente y las diferencias, calculadas por el código,
    entre la versión devuelta y la vigente. None en la versión A o sin DEVUELTA. El código no sabe qué cambio responde a
    qué comentario: lo dice, y si no hay ninguna diferencia lo marca para que el revisor lo compruebe."""
    devueltas = comentarios_devuelta(estado)
    if not devueltas:
        return None
    registro = next((d for d in reversed(estado.get("decisiones") or []) if d.get("id") == devueltas[-1]["id"]), {})
    antes = registro.get("version_devuelta")
    cambios = _diferencias(antes, resumen_version(estado), con_importes) if isinstance(antes, dict) else None
    return {"version_anterior": devueltas[0]["version"], "comentarios": devueltas,
            "cambios": None if cambios is None else cambios[:_MAX_CAMBIOS],
            "recortados": 0 if cambios is None else max(0, len(cambios) - _MAX_CAMBIOS)}


def lineas_cambios_pedidos(estado: dict, con_importes: bool = True, perfiles: list[str] | None = None) -> list[str]:
    """Líneas de la sección «Cambios pedidos en la revisión anterior» ([] si no aplica). Nota del revisor: con importes
    y el comentario literal. PPTX: `con_importes=False` (la puerta exige que todo importe visible sea el precio o un
    hito) y `perfiles` de la tarifa: un comentario con algo que el barrido del cliente no admite (horas, perfiles,
    marcadores) no se copia y remite a la nota."""
    cp = cambios_pedidos(estado, con_importes)
    if cp is None:
        return []
    salida = [f"{TITULO_CAMBIOS} (versión {cp['version_anterior']}, DEVUELTA)"]
    for c in cp["comentarios"]:
        texto = " ".join(str(c["comentarios"]).split())
        # Integrador I1.7: en el PPTX (diapositiva 2, sitio acotado) un comentario largo remite también a la nota
        if perfiles is not None and (_no_apto_para_cliente(texto, perfiles) or len(texto) > MAX_COMENTARIO_PPTX):
            salida.append(f"Comentario de {c['revisor']} ({c['id']}): recogido en la nota del revisor")
        else:
            salida.append(f"Comentario de {c['revisor']} ({c['id']}): «{texto}»")
    salida.append(f"Cómo se atendió (diferencias entre la versión {cp['version_anterior']} devuelta y esta versión, "
                  "calculadas por el código; no dice qué cambio responde a cada comentario):")
    if cp["cambios"] is None:
        salida.append(f"- Sin resumen de la versión {cp['version_anterior']} en la decisión DEVUELTA (anterior a I1.7): "
                      "el revisor compara con el paquete anterior (--previo)")
    elif not cp["cambios"]:
        salida.append("- Sin cambios en componentes, niveles, regiones, cantidades ni importes: el revisor comprueba si "
                      "el comentario se atendió de otra forma")
    else:
        cambios, recortados = cp["cambios"], cp["recortados"]
        if perfiles is not None and len(cambios) > MAX_DIFERENCIAS_PPTX:  # PPTX: el detalle completo va en la nota
            cambios, recortados = cambios[:MAX_DIFERENCIAS_PPTX], recortados + len(cambios) - MAX_DIFERENCIAS_PPTX
        salida += [f"- {x}" for x in cambios]
        if recortados:
            salida.append(f"- … y {recortados} diferencia(s) más" + (": detalle en la nota del revisor"
                                                                      if perfiles is not None else ""))
    return salida


def _no_apto_para_cliente(texto: str, perfiles: list[str]) -> bool:
    """Lo que el barrido del cliente no admite (horas, perfiles, marcadores) y, desde I1.7 (integrador), un importe: el
    PPTX sale sin importes ni cantidades."""
    from nucleo import textos_cliente  # diferido: solo para el PPTX
    return bool(textos_cliente.barrer(texto, perfiles) or textos_cliente.marcadores(texto)
                or _IMPORTE_COMENTARIO.search(texto))
