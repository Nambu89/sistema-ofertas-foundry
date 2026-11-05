"""Consolidado para preventa-verificador, por lotes, y evaluación de sus respuestas (CONTRATOS.md §7 y §4.8).

El verificador señala, no corrige: su valor_correcto nunca entra en el contenido, vuelve al experto como
corrección con el texto original de lo corregido. Solo se verifica lo verificable (referencias, componentes y
precios), nunca la prosa, y en lotes pequeños para que cada llamada A2A quepa con holgura en el tope de
unos 120 s (LES-G-089, LES-G-096). Dos categorías con tratamiento distinto (LES-G-096):
- DISCREPA: de hecho, exige valor_correcto y fuente_url; sin fuente de la lista blanca, la duda bloquea.
- OBSERVACION: editorial o de regla, sin fuente; no bloquea y se guarda en verificacion.observaciones
  para la nota del revisor.
Solo se repara lo demostrablemente equivalente (LES-G-047): una URL que normaliza a la misma y un precio
a ≤ 0,5 %. El tope de rondas es estado.MAX_RONDAS: en la última, un DISCREPA efectivo bloquea.

I1.7 (decisión 1 del comercial, 13-10-2026): los precios salen de la instantánea que el código descarga al desplegar;
el verificador ya no tiene la herramienta de precios y el consolidado solo lleva referencias y componentes (sin lote
de precios). PR16-6: en las rondas 2 y 3, los lotes solo llevan lo nuevo o cambiado; lo que el verificador ya aceptó
en una ronda anterior de la misma versión y llega igual se hereda (brief.aceptados) y, si aun así se objeta, la
objeción pasa a OBSERVACION para la nota y nunca bloquea.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from nucleo import brief as brief_mod
from nucleo import esquema
from nucleo import estado as est_mod
from nucleo import experto, hashes
from nucleo.errores import Bloqueo, IntegridadRota, ReglaIncumplida, TransicionNoPermitida

UMBRAL_PRECIO = Decimal("0.005")
FUENTE_PRECIOS = "https://prices.azure.com/api/retail/prices"
_TIPO = {"REF": "referencia", "C": "componente", "P": "precio"}
_SECCION = {"REF": "## Referencias", "C": "## Componentes"}
_NOMBRE_LOTE = {"REF": "referencias", "C": "componentes"}
# Elementos por lote y tipo. Cada elemento cuesta una llamada a una herramienta: REF una lectura
# (microsoft_docs_fetch) y C una búsqueda (microsoft_docs_search). Medido en I1 (08-10-2026): el verificador
# directo tardó 37 s y 64,6 s con unos 25 elementos y hasta 12 llamadas a mslearn más las de precios; la llamada
# A2A se cortó a los 120,6 s. En I1.6 los lotes L1 a L5 (referencias y componentes) se registraron en real; solo el
# de precios (L6) abortaba, por el 429 de Retail Prices a Foundry. I1.7 lo quita (decisión 1): quedan REF y C, por
# debajo del tope de 6 lecturas y 6 búsquedas por llamada y con margen para una búsqueda extra.
LOTE_MAX = {"REF": 4, "C": 5}
_ID_LINEA = re.compile(r"^((?:REF|C|P)-\d{2}) \|")
# PR16-6 (I1.7): veredictos con los que un elemento queda aceptado para las rondas siguientes de la misma versión.
VEREDICTOS_ACEPTADOS = ("OK", "OBSERVACION", "REPARADO")
# CMP-1 (I1.3, EA-4 y EB-2). Un SaaS de Microsoft 365 o Entra no tiene región de Azure: su residencia es la geografía
# del tenant del cliente. La línea del componente lo dice con esta marca fija, y una DISCREPA de residencia de un
# componente «global» así (o sin catalogo_id y en «global») cuya fuente es una página de residencia por geografía del
# tenant pasa a OBSERVACION para la nota: es un supuesto del cliente, no un hecho erróneo de la oferta (LES-G-096).
MARCA_TENANT = "(residencia de datos: geografía del tenant del cliente; no es una región de Azure)"
# Familia «m365-dr-» (una página por servicio de Microsoft 365) y dos páginas exactas (o sus subrutas).
FUENTES_RESIDENCIA_TENANT = ("/microsoft-365/enterprise/m365-dr-", "/microsoft-365/enterprise/o365-data-locations",
                             "/entra/fundamentals/data-residency")
# REV13-1 (I1.4): una desviación sin catalogo_id solo cuenta como SaaS con residencia por tenant si su nombre, en forma
# compacta y sin «desviación: », es IGUAL a uno de esta lista cerrada de nombres de Microsoft 365 y Entra. Antes se
# buscaba por contención y «Indexador de SharePoint de Azure AI Search» o «NotSharePoint Gateway» pasaban.
SAAS_TENANT_NOMBRES = (
    "sharepoint", "sharepointonline", "microsoftsharepoint", "microsoftsharepointonline", "sharepointinmicrosoft365",
    "sharepointenmicrosoft365", "onedrive", "onedriveforbusiness", "onedriveparalaempresa", "microsoftonedrive",
    "microsoftonedriveforbusiness", "exchangeonline", "microsoftexchangeonline", "microsoft365", "office365",
    "microsoftoffice365", "teams", "microsoftteams", "entraid", "microsoftentraid")
# ARR13-4 (I1.4): el verificador declara en cada DISCREPA el campo de la línea que discute. Solo esos campos por tipo.
CAMPOS_DISCREPA = {"referencia": ("url", "titulo"),
                   "componente": ("nombre", "sku", "region", "referencia", "cantidad", "motivo"),
                   "precio": ("componente", "filtro", "precio", "unidad", "region", "effectiveStartDate", "cantidad")}
# I1.7 (CAMBIOS-I17-E §3.5): sin líneas de precios, el factor cambiado y el motivo de no valoración van en la línea del
# componente y el verificador los discute en ella («cantidad» y «motivo»).
# I1.6 (CAMBIOS-I16-E §3.3): «cantidad» es el factor de volumen de un precio (LES-G-100); el nivel de un componente se
# discute en «sku».
# EA-3 (I1.4): el eco del verificador son las tres primeras líneas completas de lo recibido, comparadas línea a línea.
ECO_LINEAS = 3
_CAMPOS_C = re.compile(r"^(?:C-\d{2}) \| (?P<nombre>.*?) \| sku: (?P<sku>.*?) \| region: (?P<region>\S+)(?P<resto>.*?)"
                       r" \| referencia: (?P<ref>\S+)$")
_CAMPOS_REF = re.compile(r"^(?:REF-\d{2}) \| (?P<url>\S+) \| (?P<titulo>.*)$")


def residencia_tenant(comp: dict, catalogo: dict) -> bool:
    """El catálogo declara que la residencia del servicio es la geografía del tenant (Teams, Entra ID)."""
    entrada = next((e for e in (catalogo or {}).get("componentes") or []
                    if isinstance(e, dict) and e.get("id") == comp.get("catalogo_id")), None)
    return bool(entrada) and entrada.get("residencia") == "geografia_tenant"


def _region_c(c: dict, catalogo: dict) -> str:
    return f"{c['region']} {MARCA_TENANT}" if residencia_tenant(c, catalogo) else c["region"]


def _region_p(p: dict, comp: dict | None, catalogo: dict) -> str:
    """La región del precio es la del componente; si Retail Prices solo lo publica con otro armRegionName (Bot
    Service, Private Link: «Global»), la línea lo dice para que no parezca una incoherencia (EB-2, R2 de B)."""
    entrada = next((e for e in (catalogo or {}).get("componentes") or []
                    if isinstance(e, dict) and comp and e.get("id") == comp.get("catalogo_id")), None)
    rp = (entrada or {}).get("region_precio")
    return f"{p['region']} (Retail Prices lo publica con armRegionName «{rp}»)" if rp else p["region"]


@dataclass(frozen=True)
class Lote:
    lote_id: str
    tipo: str
    texto: str
    sha256: str
    ids: tuple[str, ...]


@dataclass(frozen=True)
class Consolidado:
    consolidado_id: str
    texto: str
    sha256: str
    ids: tuple[str, ...]
    lotes: tuple[Lote, ...] = ()


@dataclass(frozen=True)
class ResultadoVerificacion:
    discrepa: list[dict] = field(default_factory=list)
    no_verificables: list[dict] = field(default_factory=list)
    reparados: list[dict] = field(default_factory=list)
    verificada: bool = False
    observaciones: list[dict] = field(default_factory=list)
    lote: str | None = None
    pendientes: list[str] = field(default_factory=list)

    @property
    def completa(self) -> bool:
        """False mientras falten lotes por registrar (no hay veredicto de la ronda todavía)."""
        return not self.pendientes


def _num(x: object) -> str:
    return json.dumps(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)


def _valor_req(estado: dict, campo: str) -> str:
    alta = estado["carga"]["alta"]
    entradas = ((estado["carga"]["requisitos"] or {}).get("campos", {}).get(campo) or {}).get("entradas", [])
    cliente = [alta["cliente"], alta["codigo_cliente"]]
    return " ".join(brief_mod.anonimizar("; ".join(e["valor"] for e in entradas), list(alta["terminos_sensibles"]),
                                         cliente, brief_mod._personas_heuristicas(list(alta["terminos_sensibles"]), cliente)).split())


def _plano(x: object) -> str:
    """Texto de un segmento de línea: una sola línea y sin «|», que separa los campos (I1.6)."""
    return " ".join(str(x if x is not None else "").replace("|", "/").split())


def _segmento_nivel(c: dict, anon) -> str:
    """I1.6 (decisión 4, CAMBIOS-I16-E §3.3): `| nivel: … | requisito: «…» | limite: «…» | fuente_nivel: URL` para el
    verificador, antes de `| referencia:`; "" si el componente no lleva justificacion_nivel. El requisito es una cita
    del cliente: pasa por la anonimización (la línea del componente se barre además en `consolidar`)."""
    j = c.get("justificacion_nivel")
    if not isinstance(j, dict):
        return ""
    fuente = experto.normalizar_url(j.get("fuente") if isinstance(j.get("fuente"), str) else "") or "sin fuente"
    return (f" | nivel: {_plano(j.get('nivel'))} | requisito: «{_plano(anon(_plano(j.get('requisito'))))}» | limite: "
            f"«{_plano(j.get('limite_oficial'))}» | fuente_nivel: {fuente}")


def _segmento_volumen(p: dict, anon) -> str:
    """I1.6 (decisión 4, CAMBIOS-I16-E §3.3): `| cantidad_mensual: … | base: «cita» (cantidad unidad) | factor: valor
    unidad («justificación»)` al final de la línea de un precio por volumen; "" si no lleva base_volumen. La cita ya es
    la del brief (anonimizada) y la justificación es texto libre del modelo: las dos pasan por la anonimización, porque
    las líneas P- no se barren en `consolidar` (un precio con decimales casaría como teléfono)."""
    b = p.get("base_volumen")
    if not isinstance(b, dict):
        return ""
    f = b.get("factor") if isinstance(b.get("factor"), dict) else {}
    return (f" | cantidad_mensual: {_num(p.get('cantidad_mensual'))} | base: «{_plano(anon(_plano(b.get('cita'))))}» "
            f"({_num(b.get('cantidad_base'))} {_plano(b.get('unidad_base'))}) | factor: {_num(f.get('valor'))} "
            f"{_plano(f.get('unidad'))} («{_plano(anon(_plano(f.get('justificacion'))))}»)")


def _segmento_nivel_i19(c: dict, resp: dict, catalogo: dict, requisitos, anon) -> str:
    """I1.9 (E19-9, CAMBIOS-I19-P §5.6): el segmento del nivel o del recurso del cliente lo da el núcleo del experto
    (`experto.segmento_verificador_i19`, la forma que esperan las instrucciones del verificador). Una respuesta v4
    (justificacion_nivel con `requisito`, de I1.7 e I1.8) conserva su segmento de entonces (`_segmento_nivel`), para
    que el consolidado de un estado antiguo se recomponga igual."""
    j = c.get("justificacion_nivel")
    if isinstance(j, dict) and "requisito" in j:
        return _segmento_nivel(c, anon)
    return experto.segmento_verificador_i19(c, resp, catalogo, requisitos, anon)


def _segmento_motivo(c: dict, resp: dict, anon) -> str:
    """I1.7 (CAMBIOS-I17-E §3.5): `| motivo: … | motivo_cita: «…»` (a cargo del cliente), `| motivo: … | incluido_en:
    C-nn (catalogo_id)` (incluido en otro componente) o `| motivo: …` (los demás); "" sin motivo o con «no_aplica». La
    cita es del cliente: pasa por la anonimización."""
    m = c.get("motivo_no_valoracion")
    if not isinstance(m, str) or not m or m == "no_aplica":
        return ""
    seg = f" | motivo: {_plano(m)}"
    if m == "a_cargo_del_cliente":
        seg += f" | motivo_cita: «{_plano(anon(_plano(c.get('motivo_cita'))))}»"
    elif m == "incluido_en_otro_componente":
        otro = next((x for x in resp.get("componentes") or [] if x.get("id") == c.get("incluido_en")), {})
        seg += f" | incluido_en: {_plano(c.get('incluido_en'))} ({_plano(otro.get('catalogo_id'))})"
    return seg


def _segmento_factor(c: dict, resp: dict, catalogo: dict, anon) -> str:
    """I1.7 (CAMBIOS-I17-E §3.5): por cada precio del componente cuyo factor no es el estándar del catálogo,
    `| factor: plantilla valor unidad (estándar: valor_estándar) | factor_cita: «…» | factor_justificacion: «…»`."""
    comps = {x.get("id"): x for x in resp.get("componentes") or []}
    segs = []
    for p in resp.get("precios") or []:
        b = p.get("base_volumen") if isinstance(p.get("base_volumen"), dict) else {}
        f = b.get("factor") if isinstance(b.get("factor"), dict) else {}
        o = p.get("factor_override") if isinstance(p.get("factor_override"), dict) else None
        if p.get("componente_id") != c.get("id") or f.get("origen") != "experto" or o is None:
            continue
        info = experto._info_de(p, comps, catalogo)
        # E19-9b (I1.9, CAMBIOS-I19-P §12.4): la referencia es el factor del catálogo para la base citada
        std = experto.factor_por_base(info, catalogo, b.get("cita"), b.get("unidad_base"))[0] if info else None
        estandar = f"{_num(std['valor_json'])}" if std else "no hay"
        segs.append(f" | factor: {_plano(p.get('plantilla_id'))} {_num(f.get('valor'))} {_plano(f.get('unidad'))} "
                    f"(estándar: {estandar}) | factor_cita: «{_plano(anon(_plano(o.get('cita'))))}» | "
                    f"factor_justificacion: «{_plano(anon(_plano(o.get('justificacion'))))}»")
    return "".join(segs)


def _texto(cabecera: list[str], cuerpo: list[str]) -> str:
    texto_cuerpo = "\n".join(cuerpo)
    return "\n".join(cabecera + [f"sha256_cuerpo: {hashes.sha256_texto(texto_cuerpo)}", "---"]) + "\n" + texto_cuerpo


def _trocear(lineas: list[str], n: int) -> list[list[str]]:
    return [lineas[i:i + n] for i in range(0, len(lineas), n)]


def contenido_linea(linea: object) -> str:
    """PR16-6 (I1.7): lo que dice una línea del consolidado sin su id («C-03 | X» -> «X»), con los espacios
    normalizados. El modelo renumera los ids entre rondas; lo que se acepta es el contenido."""
    t = " ".join(str(linea or "").split())
    m = _ID_LINEA.match(t)
    return t[m.end():].strip() if m else ""


def aceptados_de_brief(brief: dict | None) -> dict[str, int]:
    """contenido -> ronda en que se aceptó, según `aceptados` del brief ({} sin brief o sin la clave)."""
    salida: dict[str, int] = {}
    for a in (brief or {}).get("aceptados") or []:
        if isinstance(a, dict) and isinstance(a.get("linea"), str) and a.get("veredicto") in VEREDICTOS_ACEPTADOS:
            salida.setdefault(" ".join(a["linea"].split()), a.get("ronda") if isinstance(a.get("ronda"), int) else 0)
    return salida


def _brief_de(estado: dict, brief_id: object) -> dict | None:
    return next((b for b in estado["carga"].get("briefs") or [] if b.get("brief_id") == brief_id), None)


def a_verificar(por_tipo: dict[str, list[str]], aceptados: dict[str, int]) -> dict[str, list[str]]:
    """PR16-6: las líneas que se envían al verificador son las nuevas o cambiadas (su contenido no está aceptado). Si
    no queda ninguna (las corregidas se quitaron), se envían todas: nunca una ronda sin lotes, y lo que se objete de lo
    ya aceptado pasa a OBSERVACION en `evaluar`."""
    nuevas = {t: [ln for ln in v if contenido_linea(ln) not in aceptados] for t, v in por_tipo.items()}
    return nuevas if any(nuevas.values()) else por_tipo


def _lotes(cid: str, contexto: list[str], por_tipo: dict[str, list[str]]) -> tuple[Lote, ...]:
    """Parte las líneas verificables en lotes por tipo; cada lote repite el contexto de la cabecera."""
    trozos = [(t, grupo) for t in ("REF", "C") for grupo in _trocear(por_tipo[t], LOTE_MAX[t])]
    salida = []
    for n, (tipo, grupo) in enumerate(trozos, start=1):
        lid = f"{cid}-L{n}"
        cab = ["CONSOLIDADO-PREVENTA/1", f"consolidado_id: {lid}",
               f"lote: {n} de {len(trozos)} ({_NOMBRE_LOTE[tipo]}) del consolidado {cid}"] + contexto
        texto = _texto(cab, [_SECCION[tipo]] + grupo)
        ids = tuple(_ID_LINEA.match(ln).group(1) for ln in grupo)
        salida.append(Lote(lid, _NOMBRE_LOTE[tipo], texto, hashes.sha256_texto(texto), ids))
    return tuple(salida)


def consolidar(estado: dict, catalogo: dict) -> Consolidado:
    """§7.1. Exige respuesta válida registrada. Solo lo verificable (referencias y componentes; I1.7: sin precios),
    sin la prosa del experto, y partido en lotes (PR16-6: en las rondas 2 y 3, solo lo nuevo o cambiado). Guarda carga.consolidado, anula la verificación anterior y lo que
    depende de ella. Idempotente en EN_VERIFICACION si el texto es el mismo (no toca los lotes registrados)."""
    if not est_mod.respuesta_valida(estado):
        raise TransicionNoPermitida("consolidar exige una respuesta válida del experto registrada", [])
    cid = f"CNS-{est_mod.codigo(estado)}-R{est_mod.ronda_actual(estado)}"
    cons = componer_consolidado(estado, catalogo, cid)
    texto, ids, lotes, alta = cons.texto, cons.ids, cons.lotes, estado["carga"]["alta"]
    previo = estado["carga"].get("consolidado")
    if estado["estado"] == "EN_VERIFICACION":
        if previo and previo["consolidado_id"] == cid and previo["texto"] == texto:
            return cons
        raise IntegridadRota(f"En EN_VERIFICACION el consolidado {cid} ya existe con otro texto", [])
    # Sin los ids (llevan el código de cliente) ni las líneas de precios (un precio con muchos decimales
    # casaría como teléfono): requisitos de la cabecera, referencias y componentes.
    fuera = ("CONSOLIDADO-PREVENTA/", "consolidado_id:", "brief_id:", "sha256_cuerpo:", "---", "P-")
    revisable = "\n".join(ln for ln in texto.split("\n") if not ln.startswith(fuera))
    hallazgos = brief_mod.hallazgos_sensibles(revisable, list(alta["terminos_sensibles"]))
    if hallazgos:
        est_mod.bloquear(estado, f"El consolidado {cid} conserva datos sensibles: {'; '.join(hallazgos)[:600]}")
        raise Bloqueo(f"Consolidado {cid} con datos sensibles", hallazgos)
    est_mod.invalidar_desde(estado, "consolidado")
    estado["carga"]["verificacion"] = None
    estado["carga"]["consolidado"] = {
        "consolidado_id": cid, "sha256": cons.sha256, "texto": texto, "ids": list(ids),
        "lotes": [{"lote_id": x.lote_id, "tipo": x.tipo, "sha256": x.sha256, "texto": x.texto, "ids": list(x.ids),
                   "registrada_el": None, "respuesta": None} for x in lotes]}
    return cons


def componer_consolidado(estado: dict, catalogo: dict, consolidado_id: str) -> Consolidado:
    """Pura y determinista: el consolidado y sus lotes a partir de la respuesta del experto registrada, los
    requisitos y el catálogo. La usa consolidar y la puede usar la puerta local para recomponer y comparar
    (LES-G-097.2). IntegridadRota si un catalogo_id no está en el catálogo."""
    cid = consolidado_id
    az = estado["carga"]["respuestas_expertos"][est_mod.pilar(estado)]
    resp = az["respuesta"]
    nombres = {c["id"]: c["nombre_oficial"] for c in catalogo.get("componentes", [])}
    alta = estado["carga"]["alta"]
    sens, cli = list(alta["terminos_sensibles"]), [alta["cliente"], alta["codigo_cliente"]]

    def anon(t: str) -> str:
        """Defensa en profundidad solo sobre texto libre (títulos y servicios); filtros y precios no se tocan:
        un precio con muchos decimales casaría como teléfono."""
        return brief_mod.anonimizar(t, sens, cli, brief_mod._personas_heuristicas(sens, cli))

    nombre_c = {}
    for c in resp["componentes"]:
        if c["catalogo_id"] is not None and c["catalogo_id"] not in nombres:
            raise IntegridadRota(f"{c['id']}: catalogo_id {c['catalogo_id']} no está en el catálogo montado", [])
        nombre_c[c["id"]] = nombres[c["catalogo_id"]] if c["catalogo_id"] else f"desviación: {anon(c['servicio'])}"
    # CMP-1: una referencia respalda componentes uno a uno. La referencia va en la línea de cada componente (con su
    # URL) y se juzga allí; la línea de la referencia solo lleva lo que se comprueba de ella (existe y su título).
    url_ref = {r["id"]: experto.normalizar_url(r["url"]) for r in resp["referencias"]}
    # I1.7 (decisión 1): sin líneas de precios. El precio unitario sale de la instantánea del despliegue y la cantidad
    # la calcula el núcleo; no queda nada que el verificador pueda contrastar con una herramienta.
    por_tipo = {
        "REF": [f"{r['id']} | {url_ref[r['id']]} | {anon(r['titulo'])}" for r in resp["referencias"]],
        "C": [f"{c['id']} | {nombre_c[c['id']]} | sku: {c['sku']} | region: {_region_c(c, catalogo)}"
              f"{_segmento_nivel_i19(c, resp, catalogo, estado['carga'].get('requisitos'), anon)}"
              f"{_segmento_motivo(c, resp, anon)}{_segmento_factor(c, resp, catalogo, anon)}"
              f" | referencia: "
              f"{url_ref.get(c['referencia_id']) or c['referencia_id']}" for c in resp["componentes"]]}
    por_tipo = {k: [" ".join(ln.split()) for ln in v] for k, v in por_tipo.items()}
    cuerpo = [ln for t in ("REF", "C") for ln in [_SECCION[t]] + por_tipo[t]]
    contexto = [f"brief_id: {az['brief_id']}",
                f"ubicacion_usuarios: {_valor_req(estado, 'ubicacion_usuarios')}",
                f"marco_normativo: {_valor_req(estado, 'marco_normativo')}",
                f"tipo_suscripcion: {_valor_req(estado, 'tipo_suscripcion') or 'no indicado'}"]
    texto = _texto(["CONSOLIDADO-PREVENTA/1", f"consolidado_id: {cid}"] + contexto, cuerpo)
    ids = tuple(x["id"] for k in ("referencias", "componentes") for x in resp[k])
    aceptados = aceptados_de_brief(_brief_de(estado, az["brief_id"]))
    lotes = _lotes(cid, contexto, a_verificar(por_tipo, aceptados))
    return Consolidado(cid, texto, hashes.sha256_texto(texto), ids, lotes)


def lotes(estado: dict) -> list[dict]:
    """Lotes del consolidado vigente, en orden, con su estado (para la CLI y para la opción B, que los
    envía por código). Cada uno: lote_id, tipo, ids, sha256, texto y registrado (bool)."""
    cons = estado["carga"].get("consolidado") or {}
    return [{"lote_id": x["lote_id"], "tipo": x["tipo"], "ids": list(x["ids"]), "sha256": x["sha256"],
             "texto": x["texto"], "registrado": x.get("respuesta") is not None} for x in cons.get("lotes") or []]


def lotes_pendientes(estado: dict) -> list[dict]:
    """Lotes que faltan por registrar en EN_VERIFICACION; [] en cualquier otro estado."""
    if estado["estado"] != "EN_VERIFICACION":
        return []
    return [x for x in lotes(estado) if not x["registrado"]]


def parsear(texto: str) -> dict:
    """Mismas reglas que experto.parsear."""
    return experto.parsear(texto)


def objetivo(consolidado: dict, consolidado_id: object) -> tuple[str | None, str, list[str]] | None:
    """(lote_id o None si es el consolidado completo, texto enviado, ids esperados); None si el id no es ni
    el del consolidado vigente ni el de uno de sus lotes."""
    if consolidado_id == consolidado["consolidado_id"]:
        return None, consolidado["texto"], list(consolidado["ids"])
    for x in consolidado.get("lotes") or []:
        if consolidado_id == x["lote_id"]:
            return x["lote_id"], x["texto"], list(x["ids"])
    return None


def validar_respuesta(resp: dict, consolidado: dict) -> list[str]:
    """Esquema; consolidado_id del consolidado vigente o de uno de sus lotes; exactamente un veredicto por id de
    lo enviado; tipo coherente con el id; DISCREPA con valor_correcto y fuente_url; eco del comienzo literal."""
    errores = list(esquema.validar(resp, esquema.cargar("respuesta_verificador")))
    if errores:
        return errores
    obj = objetivo(consolidado, resp["consolidado_id"])
    if obj is None:
        validos = [consolidado["consolidado_id"]] + [x["lote_id"] for x in consolidado.get("lotes") or []]
        return [f"consolidado_id: devuelve {resp['consolidado_id']} y los vigentes son {', '.join(validos)}"]
    _, texto, esperados = obj
    vistos = [e["id"] for e in resp["elementos"]]
    errores += [f"elementos: veredicto repetido para {i}" for i in sorted({i for i in vistos if vistos.count(i) > 1})]
    errores += [f"elementos: falta el veredicto de {i}" for i in esperados if i not in vistos]
    errores += [f"elementos: {i} no está en lo enviado" for i in sorted(set(vistos) - set(esperados))]
    for e in resp["elementos"]:
        if _TIPO.get(e["id"].split("-")[0]) != e["tipo"]:
            errores.append(f"elementos.{e['id']}: tipo {e['tipo']} no corresponde al id")
        if e["veredicto"] == "DISCREPA" and (not (e["valor_correcto"] or "").strip() or not e["fuente_url"]):
            errores.append(f"elementos.{e['id']}: DISCREPA exige valor_correcto y fuente_url; sin fuente es una "
                           "OBSERVACION (redacción o regla) o NO VERIFICABLE")
        admitidos = CAMPOS_DISCREPA.get(e["tipo"], ())
        if e["veredicto"] == "DISCREPA" and e["campo"] not in admitidos:
            errores.append(f"elementos.{e['id']}: DISCREPA exige el campo discutido de la línea ({', '.join(admitidos)});"
                           f" llega «{e['campo']}»")
    errores += errores_eco(resp["entrada_recibida_inicio"], texto)
    return errores


def lineas_eco(texto: object) -> list[str]:
    """Líneas no vacías de un texto, cada una con los espacios normalizados (solo los de formato)."""
    return [ln for ln in (" ".join(x.split()) for x in str(texto or "").splitlines()) if ln]


def errores_eco(eco: object, enviado: str) -> list[str]:
    """EA-3: el eco son las ECO_LINEAS primeras líneas completas de lo enviado (o más, todas enteras y en orden),
    comparadas línea a línea. Un corte a mitad de línea ya no puede pasar ni fallar por un carácter del final."""
    recibidas, enviadas = lineas_eco(eco), lineas_eco(enviado)
    if len(recibidas) < ECO_LINEAS:
        return [f"entrada_recibida_inicio: trae {len(recibidas)} línea(s) y debe traer las {ECO_LINEAS} primeras líneas "
                "completas de lo recibido, separadas por saltos de línea"]
    if len(recibidas) > len(enviadas):
        return ["entrada_recibida_inicio: trae más líneas de las que tiene lo enviado"]
    for n, (r, s) in enumerate(zip(recibidas, enviadas), start=1):
        if r != s:
            return [f"entrada_recibida_inicio: la línea {n} no es la línea {n} literal de lo enviado"]
    return []


def _fuente_valida(url: str | None, es_precio: bool) -> bool:
    if not url:
        return False
    if experto.es_referencia_permitida(url):
        return True
    return es_precio and url.split("?")[0].rstrip("/").lower() == FUENTE_PRECIOS


def _decimal(s: object) -> Decimal | None:
    if not isinstance(s, str) or not re.fullmatch(r"\s*-?\d+(?:\.\d+)?\s*", s):
        return None
    try:
        return Decimal(s.strip())
    except InvalidOperation:
        return None


def _lineas(consolidado: dict | None) -> dict[str, str]:
    """id -> línea del consolidado: el texto original de lo que se verifica (va en las correcciones)."""
    salida = {}
    for ln in (consolidado or {}).get("texto", "").split("\n"):
        m = _ID_LINEA.match(ln)
        if m:
            salida[m.group(1)] = ln
    return salida


def _compacto_valor(t: object) -> str:
    return experto._compacto(t)


def valor_es_lo_enviado(linea: str, valor_correcto: object, campo: object) -> bool:
    """CMP-1 (EA-4) y ARR13-4 (I1.4): el valor «correcto» del verificador ES lo que se le envió EN EL CAMPO QUE
    DISCUTE (C-06 de A, R2: «Azure AI Search» frente a «Azure AI Search»). Solo dos casos: `campo` «nombre» en la línea
    de un componente del catálogo (el nombre oficial lo compone el código; nunca una desviación) y `campo` «titulo» en
    la de una referencia (con o sin «Título:»). Igualdad exacta de la forma compacta, nunca contención: es una
    equivalencia demostrable (LES-G-047). Con otro campo (región, SKU, URL…) o sin campo, la DISCREPA se queda."""
    vc = _compacto_valor(re.sub(r"^\s*t[ií]tulo\s*:\s*", "", valor_correcto, flags=re.IGNORECASE)
                         if isinstance(valor_correcto, str) else "")
    if not vc:
        return False
    m = _CAMPOS_C.match(linea or "")
    if m:
        nombre = m.group("nombre")
        return campo == "nombre" and not nombre.startswith("desviación: ") and vc == _compacto_valor(nombre)
    m = _CAMPOS_REF.match(linea or "")
    return campo == "titulo" and bool(m) and vc == _compacto_valor(m.group("titulo"))


def es_saas_tenant(nombre: str) -> bool:
    """REV13-1: «desviación: X» con X, en forma compacta, igual a un nombre de SAAS_TENANT_NOMBRES."""
    prefijo = "desviación: "
    return nombre.startswith(prefijo) and _compacto_valor(nombre[len(prefijo):]) in SAAS_TENANT_NOMBRES


def es_residencia_tenant(linea: str, fuente_url: object, campo: object) -> bool:
    """CMP-1 (EB-2): DISCREPA de la REGIÓN (`campo` «region», ARR13-4) de un componente en «global» cuya residencia es la
    geografía del tenant (la línea lleva MARCA_TENANT, o es una desviación de un SaaS de Microsoft 365 o Entra de la
    lista cerrada, REV13-1), con una fuente que es una página de residencia por geografía del tenant de Learn. Solo con
    todo: la línea la compone el código y la fuente es de la lista blanca."""
    m = _CAMPOS_C.match(linea or "")
    if campo != "region" or not m or m.group("region") != "global":
        return False
    if MARCA_TENANT not in (m.group("resto") or "") and not es_saas_tenant(m.group("nombre")):
        return False
    ruta = experto.normalizar_url(fuente_url if isinstance(fuente_url, str) else "")[len(f"https://{experto.HOST_LEARN}"):]
    return bool(ruta) and any(ruta.startswith(p) if p.endswith("-") else (ruta == p or ruta.startswith(p + "/"))
                              for p in FUENTES_RESIDENCIA_TENANT)


def _region_compacta(r: object) -> str:
    """«Sweden Central», «sweden-central» y «swedencentral» son la misma región."""
    return re.sub(r"[\s_-]+", "", r).lower() if isinstance(r, str) else ""


def _fuente_de(valor: object) -> str | None:
    if isinstance(valor, str):
        return valor
    return _fuente_de(valor.get("url") or valor.get("fuente_url")) if isinstance(valor, dict) else None


def disponibilidad_catalogo(comp: dict, precios: list, catalogo: dict | None) -> tuple[str, list[str], str] | None:
    """VC18-3 (I1.9): (nivel, regiones, fuente) en que el catálogo publica disponible el nivel que usa el componente, o
    None si el catálogo no lo declara con una fuente válida de Learn o no se sabe con certeza qué nivel usa (entonces no
    se reclasifica nada: dirección segura). `disponibilidad` de la fila: {nivel: {"regiones": [...], "fuente_url"} o
    lista de regiones con `disponibilidad_fuente_url` en la fila}. El nivel: el de las plantillas de sus precios; sin
    precios, el de `justificacion_nivel` o el `sku` si nombra un nivel; sin nada de eso, el `nivel_por_defecto`. Una fila
    sin niveles (Microsoft Foundry: la disponibilidad va por modelo) se casa por el `modelo` de las plantillas usadas o, sin
    precios, por el `sku` exacto. La fuente tiene que ser una página de Learn (el catálogo es de confianza)."""
    entrada = experto._entrada_de(comp, catalogo or {})
    disp = entrada.get("disponibilidad") if isinstance(entrada, dict) else None
    if not isinstance(disp, dict) or not disp:
        return None
    niveles = experto.niveles_de(entrada)
    usadas = {x.get("plantilla_id") for x in precios or [] if isinstance(x, dict) and x.get("componente_id") == comp.get("id")}
    if not niveles:   # por modelo (Foundry): el de las plantillas usadas o, sin precios, el sku exacto
        modelos = {p.get("modelo") for p in entrada.get("plantillas_precio") or []
                   if isinstance(p, dict) and p.get("id") in usadas and isinstance(p.get("modelo"), str)}
        nombres = {experto._plano_req(m) for m in modelos} if usadas else {experto._plano_req(comp.get("sku"))}
        niveles = [{"nombres": sorted(nombres - {""}), "etiqueta": next(iter(sorted(nombres - {""})), ""),
                    "plantillas": usadas or None}] if len(nombres - {""}) == 1 else []
    candidatos = [n for n in niveles if n["plantillas"] and usadas & n["plantillas"]]
    if not candidatos and not usadas:
        nombres = {experto._plano_req(experto._objeto(comp.get("justificacion_nivel")).get("nivel")),
                   experto._plano_req(comp.get("sku"))} - {""}
        candidatos = [n for n in niveles if nombres & set(n["nombres"])]
        if not candidatos:
            nd = experto.nivel_por_defecto(entrada)
            candidatos = [nd] if nd else []
    if len(candidatos) != 1:
        return None
    nivel = candidatos[0]
    claves = [k for k in disp if experto._plano_req(k) in nivel["nombres"]]
    if len(claves) != 1:
        return None
    valor = disp[claves[0]]
    regiones = valor.get("regiones") if isinstance(valor, dict) else valor
    fuente = _fuente_de(valor.get("fuente_url") or valor.get("fuente")) if isinstance(valor, dict) else None
    fuente = fuente or _fuente_de(entrada.get("disponibilidad_fuente_url") or entrada.get("disponibilidad_fuente"))
    if not isinstance(regiones, list) or not all(isinstance(x, str) for x in regiones) or not fuente \
            or not experto.normalizar_url(fuente):
        return None
    return nivel["etiqueta"] or claves[0], [_region_compacta(x) for x in regiones], fuente


def region_disponible_segun_catalogo(linea: str, comp: dict | None, precios: list, catalogo: dict | None) -> str | None:
    """VC18-3: el motivo de la observación si la región de la línea del componente está entre las que el catálogo
    publica para su nivel (con fuente); None si no (la DISCREPA se queda)."""
    m = _CAMPOS_C.match(linea or "")
    if not m or not isinstance(comp, dict):
        return None
    disp = disponibilidad_catalogo(comp, precios, catalogo)
    region = _region_compacta(m.group("region"))
    if disp is None or not region or region not in disp[1]:
        return None
    return (f"DISCREPA de región que contradice la disponibilidad del catálogo (VC18-3): el catálogo publica el nivel "
            f"«{disp[0]}» en «{m.group('region')}» ({disp[2]}); no bloquea; el revisor lo ve con el detalle del verificador")


def evaluar(estado: dict, resp: dict, catalogo: dict | None = None) -> ResultadoVerificacion:
    """§7.3, pura (no muta el estado). `resp` cubre todos los ids (respuesta completa o lotes combinados).
    VC18-3 (I1.9): con `catalogo`, un DISCREPA del campo «region» de un componente cuya región el catálogo publica para su
    nivel (con fuente) pasa a OBSERVACION; sin catálogo, se queda (como antes)."""
    r = estado["carga"]["respuestas_expertos"][est_mod.pilar(estado)]["respuesta"]
    comps = {x.get("id"): x for x in r.get("componentes") or [] if isinstance(x, dict)}
    refs = {x["id"]: x for x in r["referencias"]}
    precios = {x["id"]: x for x in r["precios"]}
    originales = _lineas(estado["carga"].get("consolidado"))
    discrepa, no_verif, reparados, observaciones = [], [], [], []
    for e in resp["elementos"]:
        base = {"id": e["id"], "tipo": e["tipo"], "veredicto": e["veredicto"], "valor_correcto": e["valor_correcto"],
                "fuente_url": e["fuente_url"], "detalle": e["detalle"], "texto_original": originales.get(e["id"], ""),
                "campo": e.get("campo")}
        es_precio = e["id"] in precios
        fuente_ok = _fuente_valida(e["fuente_url"], es_precio)
        vc = _decimal(e["valor_correcto"]) if es_precio else None
        if es_precio and vc is not None:
            # Igual que verificar_paquete.evaluar_verificacion: un número en valor_correcto de un precio se
            # compara siempre, diga el veredicto lo que diga (la puerta recalcula, LES-G-097).
            original = Decimal(str(precios[e["id"]]["precio"]))
            dif = abs(vc - original) / original if original != 0 else (Decimal(0) if vc == 0 else Decimal("Infinity"))
            if dif > UMBRAL_PRECIO:
                discrepa.append({**base, "motivo": f"precio {original} frente a {vc}: diferencia {dif:.4%} > 0,5 %"})
                continue
            if e["veredicto"] == "DISCREPA" and not fuente_ok:
                discrepa.append({**base, "motivo": "DISCREPA sin fuente válida: la duda bloquea"})
                continue
            # ARR13-4 (Revisión, I1.4): una DISCREPA solo se repara por la diferencia de precio si discute el precio; si
            # declara otro campo (unidad, región, filtro…), el número no demuestra nada de ese campo y sigue abajo.
            if vc != original and (e["veredicto"] != "DISCREPA" or e.get("campo") == "precio"):
                reparados.append({**base, "motivo": f"diferencia de precio {dif:.4%} ≤ 0,5 %: se acepta y se anota"})
                continue
        if e["veredicto"] == "NO VERIFICABLE":
            no_verif.append({**base, "motivo": e["detalle"]})
        elif e["veredicto"] == "OBSERVACION":
            observaciones.append({**base, "motivo": "observación editorial o de regla: no bloquea; para la nota del revisor"})
        elif e["veredicto"] == "DISCREPA":
            # ARR13-4: solo cuenta el campo que el verificador declara. Sin «campo» (contrato anterior a I1.4) no se
            # reclasifica ni se repara nada: la DISCREPA se queda (dirección segura).
            campo = e.get("campo")
            mismo = (campo == "url" and e["id"] in refs and isinstance(e["valor_correcto"], str)
                     and experto.normalizar_url(e["valor_correcto"]) != ""
                     and experto.normalizar_url(e["valor_correcto"]) == experto.normalizar_url(refs[e["id"]]["url"]))
            linea = originales.get(e["id"], "")
            if mismo and fuente_ok:
                reparados.append({**base, "motivo": "la URL correcta normaliza a la misma (equivalencia demostrable)"})
            elif fuente_ok and not es_precio and valor_es_lo_enviado(linea, e["valor_correcto"], campo):
                observaciones.append({**base, "motivo": f"DISCREPA del campo «{campo}» cuyo valor correcto es lo que se "
                                      "envió: no bloquea; va a la nota del revisor con el detalle del verificador"})
            elif fuente_ok and es_residencia_tenant(linea, e["fuente_url"], campo):
                observaciones.append({**base, "motivo": "residencia por geografía del tenant del cliente (servicio SaaS "
                                      "sin región de Azure): no bloquea; el revisor confirma la geografía del tenant"})
            elif campo == "region" and not es_precio and (motivo_disp := region_disponible_segun_catalogo(
                    linea, comps.get(e["id"]), r.get("precios") or [], catalogo)):
                observaciones.append({**base, "motivo": motivo_disp})
            else:
                discrepa.append({**base, "motivo": "DISCREPA sin fuente válida: la duda bloquea" if not fuente_ok
                                 else "DISCREPA con fuente: vuelve al experto como corrección"})
    discrepa, heredadas = separar_ya_aceptados(discrepa, aceptados_de_brief(
        _brief_de(estado, estado["carga"]["respuestas_expertos"][est_mod.pilar(estado)].get("brief_id"))))
    observaciones += heredadas
    return ResultadoVerificacion(discrepa, no_verif, reparados, verificada=not discrepa, observaciones=observaciones)


def separar_ya_aceptados(discrepa: list[dict], aceptados: dict[str, int]) -> tuple[list[dict], list[dict]]:
    """PR16-6 (decisión del PM, 13-10-2026): una DISCREPA sobre un elemento que llega sin cambios (mismo contenido de
    línea) y que el verificador ya aceptó en una ronda anterior de esta versión no bloquea: pasa a OBSERVACION para la
    nota del revisor, con la ronda en que se aceptó. Se decide por el contenido de la línea, nunca por el id."""
    quedan, pasan = [], []
    for d in discrepa:
        contenido = contenido_linea(d.get("texto_original"))
        if contenido and contenido in aceptados:
            pasan.append({**d, "motivo": f"objeción sobre un elemento sin cambios que el verificador ya aceptó en la "
                                         f"ronda {aceptados[contenido]}: no bloquea (PR16-6); va a la nota del revisor "
                                         f"con su detalle ({d.get('motivo')})"})
        else:
            quedan.append(d)
    return quedan, pasan


def herramientas_combinadas(respuestas: list[dict]) -> dict:
    """Máximo por herramienta entre las respuestas de los lotes. I1.7: las claves son las que trae el esquema vigente
    (sin precios_azure si el esquema la quita); todas las respuestas tienen que traer las mismas o IntegridadRota."""
    claves = [tuple(sorted(r["herramientas_usadas"])) for r in respuestas]
    if len(set(claves)) != 1:
        raise IntegridadRota("Las respuestas de los lotes no declaran las mismas herramientas", [repr(set(claves))])
    return {k: max(r["herramientas_usadas"][k] for r in respuestas) for k in claves[0]}


def ids_en_lotes(cons: dict) -> list[str]:
    """PR16-6: los ids que se enviaron al verificador, en el orden de consolidado.ids. Los demás se heredan."""
    enviados = {i for x in cons.get("lotes") or [] for i in x.get("ids") or []}
    return [i for i in cons.get("ids") or [] if i in enviados]


def _combinar(cons: dict) -> dict:
    """Respuesta combinada por el código cuando están todos los lotes: elementos literales en el orden de
    consolidado.ids (PR16-6: solo los enviados), resumen recalculado, herramientas_usadas = máximo por llamada (cada
    lote respeta su tope) y entrada_recibida_inicio del primer lote. Lo literal de cada llamada queda en
    consolidado.lotes[]."""
    por_id = {e["id"]: e for x in cons["lotes"] for e in x["respuesta"]["elementos"]}
    elementos = [por_id[i] for i in ids_en_lotes(cons)]

    def cuenta(v: str) -> int:
        return sum(1 for e in elementos if e["veredicto"] == v)

    return {"agente": "preventa-verificador", "consolidado_id": cons["consolidado_id"],
            "entrada_recibida_inicio": cons["lotes"][0]["respuesta"]["entrada_recibida_inicio"],
            "elementos": elementos,
            "resumen": {"ok": cuenta("OK"), "discrepa": cuenta("DISCREPA"), "observacion": cuenta("OBSERVACION"),
                        "no_verificable": cuenta("NO VERIFICABLE")},
            "herramientas_usadas": herramientas_combinadas([x["respuesta"] for x in cons["lotes"]])}


def registrar(estado: dict, texto: str, hoy: str | None = None, catalogo: dict | None = None) -> ResultadoVerificacion:
    """Valida y registra la respuesta de un lote o del consolidado completo. Mientras falten lotes devuelve
    un resultado con `pendientes` y no transita. Con todo: evalúa, guarda carga.verificacion (con
    observaciones) y transita a VERIFICADA, a EN_ANALISIS (ronda + 1) o, en la última ronda con DISCREPA, a
    BLOQUEADA (Bloqueo). Errores de forma: intento T3. Un lote ya registrado con otra respuesta, o una
    respuesta completa tras haber lotes registrados: IntegridadRota (no se elige entre respuestas)."""
    if estado["estado"] != "EN_VERIFICACION" or not estado["carga"].get("consolidado"):
        raise TransicionNoPermitida(f"registrar-verificacion exige EN_VERIFICACION con consolidado (estado {estado['estado']})", [])
    cons = estado["carga"]["consolidado"]

    def fallar(mensaje: str, errores: list[str]):
        n = est_mod.registrar_intento(estado, "T3", f"{mensaje}: " + " | ".join(errores)[:3000],
                                      "La respuesta del verificador no cumple el contrato (§7.2)")
        if estado["estado"] == "BLOQUEADA":
            raise Bloqueo(f"{mensaje} (intento {n}/3: BLOQUEADA)", errores)
        raise ReglaIncumplida(f"{mensaje} (intento {n}/3)", errores)

    try:
        resp = parsear(texto)
    except ReglaIncumplida as e:
        fallar("Respuesta del verificador ilegible", e.errores or [str(e)])
    errores = validar_respuesta(resp, cons)
    if errores:
        fallar(f"Respuesta del verificador inválida ({len(errores)} errores)", errores)
    resp = experto._nfc(resp)
    lote_id = objetivo(cons, resp["consolidado_id"])[0]
    fecha = hoy or est_mod.hoy().isoformat()
    lotes_c = cons.get("lotes") or []
    if lote_id is None:
        registrados = [x["lote_id"] for x in lotes_c if x.get("respuesta") is not None]
        if registrados:
            raise IntegridadRota("Hay lotes registrados en esta ronda: la respuesta completa no se mezcla con lotes",
                                 registrados)
        final = resp
    else:
        lote = next(x for x in lotes_c if x["lote_id"] == lote_id)
        if lote.get("respuesta") is not None and lote["respuesta"] != resp:
            raise IntegridadRota(f"El lote {lote_id} ya está registrado con otra respuesta", [lote["registrada_el"] or ""])
        if lote.get("respuesta") is None:
            lote["respuesta"], lote["registrada_el"] = resp, fecha
        estado["intentos"]["T3"] = 0
        pendientes = [x["lote_id"] for x in lotes_c if x.get("respuesta") is None]
        if pendientes:
            return ResultadoVerificacion(lote=lote_id, pendientes=pendientes)
        final = _combinar(cons)
    res = evaluar(estado, final, catalogo)   # VC18-3 (I1.9): con el catálogo montado, si quien llama lo pasa
    ronda = int(cons["consolidado_id"].rsplit("-R", 1)[1])
    estado["ronda_verificacion"] = ronda
    est_mod.invalidar_desde(estado, "verificacion")
    estado["carga"]["verificacion"] = {
        "registrada_el": fecha, "consolidado_id": cons["consolidado_id"], "respuesta": final,
        "resultado": {"verificada": res.verificada, "discrepa": res.discrepa, "no_verificables": res.no_verificables,
                      "reparados": res.reparados},
        "lotes": [x["lote_id"] for x in lotes_c] if lote_id is not None else [],
        "observaciones": res.observaciones}
    estado["intentos"]["T3"] = 0
    if res.verificada:
        est_mod.transitar(estado, "registrar-verificacion", "VERIFICADA")
    elif ronda >= est_mod.MAX_RONDAS:
        motivo = (f"Ronda {ronda} de verificación con DISCREPA efectivos (tope de {est_mod.MAX_RONDAS} rondas): "
                  + ", ".join(d["id"] for d in res.discrepa))
        est_mod.bloquear(estado, motivo)
        raise Bloqueo(motivo, [f"{d['id']}: {d['motivo']}" for d in res.discrepa])
    else:
        est_mod.transitar(estado, "registrar-verificacion", "EN_ANALISIS")
    return ResultadoVerificacion(res.discrepa, res.no_verificables, res.reparados, res.verificada,
                                 res.observaciones, lote_id, [])


def _corto(x: object, n: int = 300) -> str:
    t = " ".join(str(x).split()) if x is not None else ""
    return t if len(t) <= n else t[:n - 1] + "…"


def lineas_discrepa_turno(estado: dict) -> list[str]:
    """PR18-7 (I1.9): el motivo de cada DISCREPA efectivo de la verificación registrada, para el texto del turno (antes
    había que descargar el estado para verlo): id, campo que discute, valor correcto, fuente, detalle del verificador y
    qué hace el núcleo con él. [] si no hay verificación registrada o no tiene DISCREPA."""
    ver = (estado.get("carga") or {}).get("verificacion") or {}
    salida = []
    for d in (ver.get("resultado") or {}).get("discrepa") or []:
        if not isinstance(d, dict):
            continue
        salida.append(f"- DISCREPA {d.get('id')} · campo «{d.get('campo') or 'sin campo'}» · valor correcto "
                      f"«{_corto(d.get('valor_correcto'), 200) or 'sin valor'}» · fuente {d.get('fuente_url') or 'sin fuente'}\n"
                      f"  Motivo del verificador: {_corto(d.get('detalle'), 600) or 'sin detalle'}\n"
                      f"  Qué hace el núcleo: {_corto(d.get('motivo'), 200)}")
    return salida


def correcciones(estado: dict) -> list[dict]:
    """Correcciones para el brief de la ronda siguiente: cada DISCREPA efectivo con su texto original
    (la línea del consolidado, ya anonimizada), el valor correcto y la fuente (LES-G-096)."""
    ver = estado["carga"].get("verificacion") or {}
    return [{"id": d["id"], "veredicto": "DISCREPA", "valor_correcto": d.get("valor_correcto"),
             "fuente_url": d.get("fuente_url"), "texto_original": d.get("texto_original") or ""}
            for d in (ver.get("resultado") or {}).get("discrepa") or []]


def lineas_conservar(estado: dict) -> list[str]:
    """CMP-1 (EA-4): líneas de referencias y componentes del consolidado anterior que la verificación NO dejó como
    DISCREPA efectivo (OK, OBSERVACION, NO VERIFICABLE, reparado o, con PR16-6, heredado sin enviar porque ya estaba
    aceptado). El brief de la ronda siguiente las lleva para que el experto las conserve y solo cambie lo marcado.

    I1.7 (decisión 1): el consolidado ya no lleva precios. Las líneas P- salen de la respuesta registrada (el dato, no
    una línea reparseada, LES-G-095): los precios de los componentes sin corrección, con lo que el experto escribe en
    el contrato v4 (plantilla, instancias, base de volumen y factor propio) y la cantidad que calculó el núcleo
    (`linea_precio_brief`). Los mismos que `precios_conservar`."""
    ver = estado["carga"].get("verificacion") or {}
    cons = estado["carga"].get("consolidado") or {}
    discrepa = {d.get("id") for d in (ver.get("resultado") or {}).get("discrepa") or []}
    vistos = {e.get("id") for e in (ver.get("respuesta") or {}).get("elementos") or []}
    heredados = set(cons.get("ids") or []) - set(ids_en_lotes(cons)) if cons.get("lotes") else set()
    salida = [ln for i, ln in _lineas(cons).items()
              if not i.startswith("P-") and (i in vistos or i in heredados) and i not in discrepa]
    anon = _anonimizador(estado)
    return salida + [linea_precio_brief(p, anon) for p in _precios_conservables(estado)]


def aceptados_siguientes(estado: dict) -> list[dict]:
    """PR16-6 (I1.7): lo aceptado hasta la verificación vigente, para el brief de la ronda siguiente de la MISMA
    versión: lo que ya traía el brief de esta ronda más cada elemento de esta verificación con veredicto OK,
    OBSERVACION (también la DISCREPA que el código pasó a OBSERVACION) o reparado. NO VERIFICABLE y DISCREPA efectivo
    no cuentan como aceptados. Cada uno: {"linea": contenido sin id, "veredicto", "ronda"}; sin repetir contenido (se
    queda la ronda más antigua)."""
    ver = estado["carga"].get("verificacion") or {}
    cons = estado["carga"].get("consolidado") or {}
    previo = _brief_de(estado, est_mod.registro_experto(estado).get("brief_id"))
    salida = [dict(a) for a in (previo or {}).get("aceptados") or [] if isinstance(a, dict)]
    vistos = {a.get("linea") for a in salida}
    res = ver.get("resultado") or {}
    fuera = {d.get("id") for k in ("discrepa", "no_verificables") for d in res.get(k) or []}
    reparados = {d.get("id") for d in res.get("reparados") or []}
    observados = {d.get("id") for d in ver.get("observaciones") or []}
    lineas = _lineas(cons)
    ronda = int(str(cons.get("consolidado_id") or "-R0").rsplit("-R", 1)[1])
    for e in (ver.get("respuesta") or {}).get("elementos") or []:
        i = e.get("id")
        if i in fuera or i not in lineas or i.startswith("P-"):
            continue
        veredicto = "REPARADO" if i in reparados else "OBSERVACION" if i in observados else e.get("veredicto")
        contenido = contenido_linea(lineas[i])
        if veredicto in VEREDICTOS_ACEPTADOS and contenido and contenido not in vistos:
            salida.append({"linea": contenido, "veredicto": veredicto, "ronda": ronda})
            vistos.add(contenido)
    return salida


def _anonimizador(estado: dict):
    alta = estado["carga"]["alta"]
    sens, cli = list(alta["terminos_sensibles"]), [alta["cliente"], alta["codigo_cliente"]]
    personas = brief_mod._personas_heuristicas(sens, cli)
    return lambda t: brief_mod.anonimizar(t, sens, cli, personas)


def _respuesta(estado: dict) -> dict:
    return (est_mod.registro_experto(estado).get("respuesta") or {})


def _precios_conservables(estado: dict) -> list[dict]:
    """Precios de la respuesta registrada cuyo componente no tiene ninguna corrección del verificador (una corrección
    sobre el componente puede obligar a rehacer sus precios). IntegridadRota si un precio no trae cantidad ni clave."""
    ver = estado["carga"].get("verificacion") or {}
    discrepa = {d.get("id") for d in (ver.get("resultado") or {}).get("discrepa") or []}
    resp = _respuesta(estado)
    comps = {c.get("id") for c in resp.get("componentes") or [] if isinstance(c, dict)}
    tocados = {p.get("componente_id") for p in resp.get("precios") or [] if isinstance(p, dict)
               and p.get("id") in discrepa} | (discrepa & comps)
    salida = []
    for p in resp.get("precios") or []:
        if not isinstance(p, dict) or p.get("componente_id") in tocados:
            continue
        if not (p.get("plantilla_id") or p.get("filtro")):
            raise IntegridadRota(f"{p.get('id')}: precio sin plantilla_id ni filtro en la respuesta registrada: no se "
                                 "puede conservar", [])
        salida.append(p)
    return salida


def linea_precio_brief(p: dict, anon=lambda t: t) -> str:
    """Línea P- del brief para un precio conservado. Contrato v4 (con plantilla_id): «P-01 | C-03 | plantilla: … |
    instancias: … | base: «cita» (n unidad) | factor: estándar del catálogo | cantidad_mensual: …» (o `factor_propio:
    v («cita»)` si el experto lo cambió citando un requisito). Contrato anterior (sin plantilla_id): filtro, unidad,
    región, concepto y la cantidad con su base, como en I1.6. Las citas y justificaciones pasan por la anonimización."""
    partes = [f"{p.get('id')} | {p.get('componente_id')}"]
    if p.get("plantilla_id"):
        partes.append(f"plantilla: {_plano(p['plantilla_id'])}")
        if p.get("instancias") is not None:
            partes.append(f"instancias: {_num(p['instancias'])}")
        b = p.get("base_volumen") if isinstance(p.get("base_volumen"), dict) else None
        if b:
            partes.append(f"base: «{_plano(anon(_plano(b.get('cita'))))}» ({_num(b.get('cantidad_base'))} "
                          f"{_plano(b.get('unidad_base'))})")
            fo = p.get("factor_override") if isinstance(p.get("factor_override"), dict) else None
            partes.append(f"factor_propio: {_num(fo.get('valor'))} («{_plano(anon(_plano(fo.get('cita'))))}»)" if fo
                          else "factor: estándar del catálogo")
        partes.append(f"cantidad_mensual: {_num(p.get('cantidad_mensual'))}")
        return " ".join(" | ".join(partes).split())
    partes += [f"filtro: {_plano(p.get('filtro'))}", f"unidad: {_plano(p.get('unidad'))}",
               f"region: {_plano(p.get('region'))}", f"concepto: {_plano(p.get('concepto'))}"]
    volumen = _segmento_volumen(p, anon) or f" | cantidad_mensual: {_num(p.get('cantidad_mensual'))}"
    return " ".join((" | ".join(partes) + volumen).split())


def _clave_conservar(catalogo_id: object, p: dict) -> tuple:
    """(catalogo_id, «plantilla», id) o (catalogo_id, «filtro», filtro normalizado) si no hay plantilla_id."""
    if p.get("plantilla_id"):
        return (catalogo_id, "plantilla", p["plantilla_id"])
    return (catalogo_id, "filtro", " ".join(str(p.get("filtro") or "").split()))


def _sumar(cantidades: list) -> Decimal | None:
    """Suma exacta en Decimal; None si alguna cantidad es nula (un precio sin cantidad no se suma a otro con ella)."""
    if any(c is None for c in cantidades):
        return None
    total = Decimal(0)
    for c in cantidades:
        if isinstance(c, bool) or not isinstance(c, (int, float)) or not Decimal(str(c)).is_finite():
            raise IntegridadRota(f"cantidad_mensual no numérica o no finita: {c!r}", [])
        total += Decimal(str(c))
    return total


def _numero_json(d: Decimal | None) -> int | float | None:
    if d is None:
        return None
    return int(d) if d == d.to_integral_value() else float(d)


def _grupos(respuesta: dict) -> dict[tuple, list[dict]]:
    comps = {c.get("id"): c for c in respuesta.get("componentes") or [] if isinstance(c, dict)}
    grupos: dict[tuple, list[dict]] = {}
    for p in respuesta.get("precios") or []:
        if isinstance(p, dict):
            cat = (comps.get(p.get("componente_id")) or {}).get("catalogo_id")
            grupos.setdefault(_clave_conservar(cat, p), []).append(p)
    return grupos


def precios_conservar(estado: dict) -> list[dict]:
    """I1.8 (REV17-4 y REV17-5): lo que el experto tiene que conservar en la ronda siguiente («conservar_precios» del
    brief). El dato lo compone experto.conservar_de, por servicio, componente, plantilla y tipo (valorado o solo precio
    de referencia), con los precios de componentes sin corrección (`_precios_conservables`); una sola regla para el
    brief, registrar-experto y la puerta."""
    return experto.conservar_de(_respuesta(estado), [p.get("id") for p in _precios_conservables(estado)])


def errores_conservacion_efecto(respuesta: dict, conservar: object) -> list[dict]:
    """I1.8 (REV17-4 y REV17-5): la misma regla que registrar-experto (experto.conservacion_efecto). Cada error:
    {"id": «catalogo_id · plantilla · C-nn», "regla": conservado_ausente | conservado_cambiado | conservar_forma,
    "detalle"}. [] si cumple."""
    return experto.conservacion_efecto(respuesta, conservar)


# I1.6 (CAMBIOS-I16-E §3.3): un precio por volumen termina además en «| cantidad_mensual: … | base: … | factor: …»;
# no se conservan (el experto repite su base_volumen, regla 5) y sin ellos el patrón seguiría descartando la línea.
# Revisión I1.6: los tres segmentos van juntos o no va ninguno (una línea a medias no tiene la forma esperada).
_LINEA_P = re.compile(r"^(P-\d{2} \| [^|]+ \| filtro: [^|]+?) \| precio: [^|]* \| (unidad: [^|]+?) \| "
                      r"(region: [^|]+?)(?: \| effectiveStartDate: [^|]*)?"
                      r"(?: \| cantidad_mensual: [^|]* \| base: [^|]* \| factor: [^|]*)?$")


def linea_precio_conservar(linea: str) -> str | None:
    """«P-01 | C-03 | filtro: … | unidad: … | region: …» (sin precio ni fecha); None si la línea no tiene esa forma."""
    m = _LINEA_P.match(linea)
    return f"{m.group(1)} | {m.group(2)} | {m.group(3)}" if m else None


def lineas_correccion(c: dict, anon=lambda t: t) -> list[str]:
    """Dos líneas del brief por corrección: qué se pide y el texto original al que se refiere (sin sangría:
    el experto devuelve el brief literal y un espacio inicial es fácil de perder)."""
    valor = anon(c["valor_correcto"]) if c.get("valor_correcto") else "sin valor"
    original = " ".join((c.get("texto_original") or "no disponible").split())
    return [f"- {c['id']} | {c['veredicto']} | {valor} | {c.get('fuente_url') or 'sin fuente'}",
            f"Texto original de {c['id']}: {original}"]
