"""Deriva, desde catalogo/catalogo_referencias_azure.json, lo que consumen los demás:

1. catalogo/catalogo_componentes.json, conforme a esquemas/catalogo_componentes.json (el que B
   monta en el sandbox como sandbox/datos/catalogo_componentes.json). Solo entran los componentes
   con referencia_url en la lista blanca de CONTRATOS.md §6.3.
2. La tabla del catálogo de las instrucciones del experto y del verificador
   (agentes/instrucciones/*_i1.md), entre las líneas CATALOGO_INICIO y CATALOGO_FIN.
3. El bloque de plantillas de precio de las instrucciones del experto (catalogo/plantillas_precio.py; v4 desde I1.7).
4. I1.9: el bloque de disponibilidad por nivel y región de las instrucciones del verificador.
Antes comprueba la forma del catálogo y que catalogo/precios_instantanea.json cubre todas sus plantillas.

Uso: .venv/Scripts/python.exe -m catalogo.derivar [--comprobar]
--comprobar no escribe: rc 1 si algún fichero derivado no coincide con lo que se generaría.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.parse

from catalogo import instantanea_precios, plantillas_precio
from esquemas import comprobar_esquemas

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent
FUENTE = AQUI / "catalogo_referencias_azure.json"
DERIVADO = AQUI / "catalogo_componentes.json"
SANDBOX = RAIZ / "sandbox" / "datos" / "catalogo_componentes.json"
ESQUEMA_SANDBOX = RAIZ / "esquemas" / "catalogo_componentes.json"
# I1.7: vista previa del derivado con el esquema propuesto por el papel E (no es el catálogo vivo del sandbox).
PROPUESTA = RAIZ / "docs" / "I1" / "CAMBIOS-I17-E"
DERIVADO_PROPUESTO = PROPUESTA / "catalogo_componentes.derivado_propuesto.json"
INSTRUCCIONES = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md",
                 RAIZ / "agentes" / "instrucciones" / "verificador_i1.md")
CATALOGO_INICIO = "### Catálogo de componentes (generado por catalogo/derivar.py; no editar a mano)"
CATALOGO_FIN = "### Fin del catálogo de componentes"

# CONTRATOS.md §6.3 (copia literal; ampliarla es cambio de contrato de P0).
PREFIJOS_ARQUITECTURA = ("/azure/architecture", "/azure/well-architected",
                         "/azure/cloud-adoption-framework", "/azure/ai-foundry", "/azure/foundry")
PREFIJOS_SERVICIO = (
    "/azure/search", "/azure/ai-services", "/azure/foundry-classic", "/azure/security",
    "/azure/private-link", "/azure/virtual-network", "/azure/app-service", "/azure/container-apps",
    "/azure/azure-functions", "/azure/storage", "/azure/cosmos-db", "/azure/key-vault",
    "/azure/azure-monitor", "/azure/api-management", "/azure/reliability",
    "/azure/defender-for-cloud", "/azure/governance", "/azure/role-based-access-control",
    "/azure/cost-management-billing", "/azure/logic-apps", "/azure/bot-service", "/entra",
    "/purview", "/compliance", "/security/benchmark/azure", "/microsoftteams/platform")
# CONTRATOS.md §6.3, «Ampliación de referencias»: valen como referencia (núcleo), no para el catálogo.
PREFIJOS_REFERENCIA_AMPLIACION = (
    "/azure/frontdoor",
    "/azure/web-application-firewall",
    "/azure/firewall",
    "/azure/application-gateway",
    "/azure/dns",
    "/azure/bastion",
    "/azure/ddos-protection",
    "/azure/networking",
    "/azure/expressroute",
    "/azure/vpn-gateway",
    "/azure/event-grid",
    "/azure/service-bus-messaging",
    "/azure/azure-sql",
    "/azure/postgresql",
    "/azure/data-factory",
    "/azure/databricks",
    "/azure/aks",
    "/azure/container-registry",
    "/azure/machine-learning",
    "/azure/redis",
    "/azure/sentinel",
    "/azure/backup",
    "/azure/azure-resource-manager",
    "/fabric",
    "/power-bi",
    "/office365",
    "/microsoft-365",
    "/microsoft-copilot-studio")


# I1.6 (P15-1, decisión 2 del comercial: «se resuelve AMPLIANDO el catálogo»): prefijos de la ampliación de §6.3 que
# también valen como referencia de un componente DEL CATÁLOGO (bases de datos, mensajería, integración y SaaS de
# Microsoft 365). El resto de la ampliación (Front Door, Fabric, Power BI…) sigue fuera: no tienen plantillas de precio.
PREFIJOS_CATALOGO_AMPLIACION = ("/azure/azure-sql", "/azure/postgresql", "/azure/service-bus-messaging",
                                "/azure/event-grid", "/azure/container-registry", "/azure/data-factory", "/office365",
                                "/microsoft-365")
assert set(PREFIJOS_CATALOGO_AMPLIACION) <= set(PREFIJOS_REFERENCIA_AMPLIACION)

_IDIOMA = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})+$")


def normalizar_url(url: str) -> str:
    """§6.3, misma semántica que nucleo.experto.normalizar_url (A): https, host exactamente
    learn.microsoft.com sin puerto ni usuario, ruta decodificada en minúsculas, sin segmento de
    idioma, sin segmentos vacíos, consulta, fragmento ni barra final. '' si no es válida."""
    try:
        p = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return ""
    if p.scheme.lower() != "https" or (p.hostname or "").lower() != "learn.microsoft.com"             or p.port is not None or p.username:
        return ""
    segmentos = [s for s in urllib.parse.unquote(p.path).lower().split("/") if s]
    if segmentos and _IDIOMA.match(segmentos[0]):
        segmentos = segmentos[1:]
    return "https://learn.microsoft.com/" + "/".join(segmentos) if segmentos else ""


def _con_prefijo(ruta: str, prefijos: tuple[str, ...]) -> bool:
    return any(ruta == p or ruta.startswith(p + "/") for p in prefijos)


def en_lista_blanca(url: str) -> bool:
    n = normalizar_url(url)
    ruta = n.removeprefix("https://learn.microsoft.com")
    return bool(n) and _con_prefijo(ruta, PREFIJOS_ARQUITECTURA + PREFIJOS_SERVICIO + PREFIJOS_CATALOGO_AMPLIACION)


def cargar(ruta: pathlib.Path = FUENTE) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def campos_opcionales_sandbox(ruta: pathlib.Path = ESQUEMA_SANDBOX) -> frozenset[str]:
    """Campos opcionales que el esquema del sandbox admite hoy en cada componente.

    El esquema es de B/integrador (additionalProperties: false): un campo que no declare no se
    deriva, para que el catálogo montado siga validando. Así `alias` entra solo cuando el
    integrador aplique docs/I1/CAMBIOS-I12-F2.md, sin tocar este módulo.
    """
    esq = json.loads(ruta.read_text(encoding="utf-8"))
    item = esq["properties"]["componentes"]["items"]
    return frozenset(item["properties"]) - frozenset(item.get("required", ()))


def _props(esquema: dict, *ruta: str) -> frozenset[str]:
    """Propiedades que admite el esquema en esa ruta (componentes → items → …); vacío si no existe."""
    nodo = esquema
    for k in ruta:
        nodo = (nodo.get("properties") or {}).get(k) if k != "items" else nodo.get("items")
        if not isinstance(nodo, dict):
            return frozenset()
    return frozenset(nodo.get("properties") or ())


def _esquema(ruta: pathlib.Path = ESQUEMA_SANDBOX) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def plantilla_sandbox(p: dict, campos: frozenset[str], ciclos: dict | None = None) -> dict:
    """Plantilla para el sandbox: id y filtro siempre; concepto (PR15-3: lo deriva el núcleo, equivalente a lo que
    devolvió la API), impulsor y divisor (decisión 4) solo si el esquema del sandbox los admite. I1.7: modelo, contexto,
    factor estándar y ciclo de vida del modelo ({ga, retirada, fuente}), también solo si el esquema los admite."""
    d = {"id": p["id"], "filtro": p["filtro"]}
    cv = (ciclos or {}).get(p.get("modelo")) if p.get("modelo") else None
    extra = {"concepto": plantillas_precio.concepto(p), "impulsor": p.get("impulsor"), "divisor": p.get("divisor"),
             "por_defecto": True if p.get("por_defecto") is True else None,  # PR16-3 (arreglos I1.6)
             "modelo": p.get("modelo"), "contexto": p.get("contexto"), "factor_estandar": p.get("factor_estandar"),
             "ciclo_vida": {k: cv[k] for k in ("ga", "retirada", "fuente")} if cv else None,
             "por_instancia": p.get("por_instancia"),  # PR17-5 (arreglos I1.7): unidades por instancia (EP1)
             "sin_factor_motivo": p.get("sin_factor_motivo"),  # I1.8 (LES-G-100.8): volumen sin factor, con su motivo
             # I1.9: razones cerradas de un modelo que no es el por defecto (VC18-5), plantilla opcional (VC18-7) y
             # factores para otras bases de volumen (PR18-5)
             "razones_subida": p.get("razones_subida"), "opcional": p.get("opcional"),
             "factores_alternativos": p.get("factores_alternativos")}
    return d | {k: v for k, v in extra.items() if k in campos and v is not None}


def factores_sandbox(cat: dict) -> list[dict]:
    """Factores estándar para el sandbox (I1.7): lista plana con id «caso_uso.factor» (el que cita `factor_estandar` de la
    plantilla) y `caso_uso`, que es la forma que lee experto.factor_estandar del núcleo."""
    return [{"id": k, "caso_uso": k.split(".", 1)[0], **{c: v for c, v in f.items() if c != "id"}}
            for k, f in plantillas_precio.factores(cat).items()]


def catalogo_componentes(cat: dict, admitidos: frozenset[str] | None = None, esquema: dict | None = None) -> dict:
    """Bloque conforme a esquemas/catalogo_componentes.json (solo referencias de la lista blanca). `esquema` permite
    derivar con un esquema propuesto (pruebas de CAMBIOS-I16-E); sin él, el del sandbox."""
    esquema = _esquema() if esquema is None else esquema
    item = esquema["properties"]["componentes"]["items"]
    if admitidos is None:
        admitidos = frozenset(item["properties"]) - frozenset(item.get("required", ()))
    campos_pl = _props(esquema, "componentes", "items", "plantillas_precio", "items")
    campos_nv = _props(esquema, "componentes", "items", "niveles", "items")
    comps = []
    for c in cat["componentes"]:
        if not (c["referencia_url"] and en_lista_blanca(c["referencia_url"])):
            continue
        d = {"id": c["id"], "nombre_oficial": c["nombre_oficial"], "capa": c["capa"],
             "service_name_precios": c["service_name_precios"], "referencia_url": c["referencia_url"]}
        if "referencia_titulo" in admitidos and c.get("referencia_titulo"):  # PR17-1: título publicado en Learn
            d["referencia_titulo"] = c["referencia_titulo"]
        if "alias" in admitidos and c.get("alias"):  # REV-2: el veto también por alias
            d["alias"] = [a["nombre"] for a in c["alias"]]
        # REVER-1: producto_precios desambigua un serviceName compartido al identificar el servicio de un precio.
        # REVSN-5: region_precio es el armRegionName de los servicios que Retail Prices solo publica como «Global».
        # CMP-1 (I1.3): residencia = «geografia_tenant» en los SaaS de Microsoft 365 y Entra.
        d.update({k: c[k] for k in ("producto_precios", "region_ue", "region_precio", "regiones_no_admitidas", "residencia")
                  if k in admitidos and c.get(k)})
        # I1.5 (decisión 1): plantillas de filtro de precio y conceptos no valorables, solo si el esquema del sandbox
        # los admite (CAMBIOS-I15-E.md): el núcleo y la puerta comprueban que cada filtro sigue una plantilla.
        if "plantillas_precio" in admitidos and c.get("plantillas_precio"):
            d["plantillas_precio"] = [plantilla_sandbox(p, campos_pl, plantillas_precio.ciclos_vida(cat))
                                      for p in c["plantillas_precio"]]
        if "niveles" in admitidos and c.get("niveles"):  # I1.6 (decisión 4): límites oficiales por nivel
            d["niveles"] = [{k: n[k] for k in n if k in campos_nv} for n in c["niveles"]]
        if "incluye" in admitidos and c.get("incluye"):  # I1.7: inclusiones con fuente (incluido_en_otro_componente)
            d["incluye"] = [{k: x[k] for k in ("catalogo_id", "concepto", "fuente_url")} for x in c["incluye"]]
        if "no_valorables" in admitidos and c.get("no_valorables"):
            d["no_valorables"] = [{"concepto": x["concepto"], "motivo": x["motivo"]} for x in c["no_valorables"]]
        if "medidores_obligatorios" in admitidos and c.get("medidores_obligatorios"):  # PR17-3 (arreglos I1.7)
            d["medidores_obligatorios"] = list(c["medidores_obligatorios"])
        # I1.8 (REVERIF17-2): reglas de medidores que los niveles no expresan y nivel por defecto de la fila.
        d.update({k: c[k] for k in ("reglas_medidores", "nivel_por_defecto") if k in admitidos and c.get(k)})
        # I1.9 (VC18-3, VC18-11): disponibilidad por nivel (o modelo) y región, que el núcleo contrasta con los DISCREPA
        d.update({k: c[k] for k in ("disponibilidad",) if k in admitidos and c.get(k)})
        comps.append(d)
    salida = {"schema": "preventa-catalogo/1", "version": cat["version"], "fecha": cat["fecha"]}
    # I1.7 (decisiones 1 y 2 del comercial): factores estándar, modelo por defecto y arquitecturas de referencia por id,
    # solo si el esquema del sandbox los admite (docs/I1/CAMBIOS-I17-E/catalogo_componentes.propuesto.json).
    if "factores_estandar" in esquema["properties"] and cat.get("casos_uso"):
        salida["factores_estandar"] = factores_sandbox(cat)
    for k in ("modelo_por_defecto", "computo_por_defecto", "arquitecturas_referencia"):  # PR17-4: cómputo por defecto
        if k in esquema["properties"] and cat.get(k):
            salida[k] = cat[k]
    if "precios_auxiliares" in esquema["properties"] and cat.get("precios_auxiliares"):
        salida["precios_auxiliares"] = precios_auxiliares(cat, esquema)
        ids = {d["id"] for d in comps}  # integrador I1.6: la fila de las plantillas tiene que llegar al sandbox
        fuera = [a["plantillas_de"] for a in salida["precios_auxiliares"] if a.get("plantillas_de") not in (None, *ids)]
        if fuera:
            raise ValueError(f"precio auxiliar: plantillas_de {fuera} no es una fila del catálogo del sandbox")
    salida["componentes"] = comps
    return salida


def auxiliares_admitidos(ruta: pathlib.Path = ESQUEMA_SANDBOX) -> bool:
    """El esquema del sandbox admite la lista blanca de precios auxiliares (nivel superior del catálogo)."""
    return "precios_auxiliares" in json.loads(ruta.read_text(encoding="utf-8"))["properties"]


def auxiliares_con_plantillas(esquema: dict | None = None) -> bool:
    """INT15-3: el esquema del sandbox admite plantillas y componentes en los precios auxiliares; solo entonces las
    instrucciones enseñan el filtro exacto del auxiliar (el núcleo que lo exige se integra con el mismo esquema)."""
    # Integrador I1.6: forma de P (CAMBIOS-I16-P §2), por referencia a la fila que tiene las plantillas.
    return {"plantillas_de", "plantillas", "componentes"} <= _props(_esquema() if esquema is None else esquema,
                                                                    "precios_auxiliares", "items")


def precios_auxiliares(cat: dict, esquema: dict | None = None) -> list[dict]:
    """Lista blanca de precios auxiliares para el sandbox (decisión del PM, I1.2): serviceName de servicios sin
    componente propio que solo valen como precio auxiliar de un componente con catalogo_id. Falla en alto si uno es
    el serviceName o el productName de un servicio del catálogo, o un nombre o alias de un servicio con vetos: entonces
    identificaría un servicio."""
    prohibidos = {(n or "").casefold() for c in cat["componentes"]
                  for n in [c.get("service_name_precios"), c.get("producto_precios")]
                  + ([c["nombre_oficial"]] + [a["nombre"] for a in c.get("alias") or []]
                     if c.get("regiones_no_admitidas") else [])}
    salida = []
    for a in cat["precios_auxiliares"]:
        if a["service_name"].casefold() in prohibidos:
            raise ValueError(f"precio auxiliar {a['service_name']!r}: es el serviceName, el productName o un nombre de "
                             "un servicio del catálogo; un auxiliar nunca puede identificar un servicio")
        d = {k: a[k] for k in ("service_name", "productos", "region_precio", "motivo") if a.get(k)}
        if esquema is not None and auxiliares_con_plantillas(esquema) and a.get("plantillas"):
            plantillas_precio.plantillas_de_auxiliar(a, cat)  # falla en alto si el vínculo no resuelve
            d.update({"plantillas_de": a["plantillas_de"], "plantillas": list(a["plantillas"]),
                      "componentes": list(a["componentes"])})
        salida.append(d)
    return salida


def _celda(v: str | None) -> str:
    return "—" if v is None else str(v).replace("|", "/")


def _region_ue(c: dict) -> str:
    """Celda «Región UE»: los SaaS cuya residencia es la geografía del tenant van en «global» y lo dicen (CMP-1)."""
    if c.get("residencia") == "geografia_tenant":
        return f"{c.get('region_ue') or 'global'} (residencia: geografía del tenant del cliente)"
    return _celda(c.get("region_ue"))


def tabla_markdown(cat: dict, aux_con_plantillas: bool = False) -> str:
    """Tabla del catálogo para las instrucciones del experto y del verificador (I1.7): sin las columnas de Retail Prices,
    porque ninguno de los dos consulta precios (los pone el código desde la instantánea). `aux_con_plantillas` se conserva
    por compatibilidad de firma: el auxiliar se explica en el bloque de plantillas."""
    si = [c for c in cat["componentes"] if c["referencia_url"] and en_lista_blanca(c["referencia_url"])]
    no = [c for c in cat["componentes"] if c not in si]
    lineas = [CATALOGO_INICIO, "",
              "| catalogo_id | Nombre oficial | También conocido como (nunca como `servicio`) | Capa | Referencia de Learn "
              "| Región UE | Regiones no admitidas |",
              "|---|---|---|---|---|---|---|"]
    for c in si:
        vetadas = ", ".join(v["region"] for v in c.get("regiones_no_admitidas") or [])
        alias = "; ".join(a["nombre"] for a in c.get("alias") or [])
        lineas.append(f"| {c['id']} | {c['nombre_oficial']} | {_celda(alias or None)} | {c['capa']} | "
                      f"{c['referencia_url']} | {_region_ue(c)} | {vetadas or '—'} |")
    lineas += ["", "La «Referencia de Learn» de cada fila la pone el código en el componente: es la única que vale para él. "
               "La región de un componente con precio es su «Región UE» (el precio de la instantánea es el de esa región)."]
    if no:
        lineas += ["", "Servicios SIN catalogo_id (no están en el catálogo): si hacen falta, `catalogo_id: null`, "
                   "`desviacion_justificada` de al menos 30 caracteres y `referencia_id` de una referencia de la lista "
                   "blanca. Van SIN precio y con un supuesto de confianza `BAJA` para que lo cotice el revisor.",
                   "", "| Servicio | Capa |", "|---|---|"]
        lineas += [f"| {c['nombre_oficial']} | {c['capa']} |" for c in no]
    lineas += ["", CATALOGO_FIN]
    return "\n".join(lineas)


def insertar_tabla(texto: str, tabla: str) -> str:
    """Sustituye el bloque entre CATALOGO_INICIO y CATALOGO_FIN (ambas líneas incluidas)."""
    i, f = texto.find(CATALOGO_INICIO), texto.find(CATALOGO_FIN)
    if i < 0 or f < i or texto.count(CATALOGO_INICIO) != 1 or texto.count(CATALOGO_FIN) != 1:
        raise ValueError("faltan, sobran o están desordenadas las líneas del bloque del catálogo")
    return texto[:i] + tabla + texto[f + len(CATALOGO_FIN):]


def problemas_catalogo(cat: dict) -> list[str]:
    """Forma de lo que se deriva: cada plantilla (filtro, impulsor y divisor), sus niveles, el vínculo de los precios
    auxiliares y, desde I1.7, factores, ciclo de vida, modelo por defecto, «incluye» y arquitecturas. [] si todo está bien."""
    m = [f"{c['id']}/{p['id']}: {x}" for c in cat["componentes"] for p in c.get("plantillas_precio") or []
         for x in plantillas_precio.problemas_plantilla(p, c)]
    m += [f"{c['id']}: {x}" for c in cat["componentes"] for x in plantillas_precio.problemas_niveles(c)]
    for a in cat.get("precios_auxiliares") or []:
        try:
            plantillas_precio.plantillas_de_auxiliar(a, cat)
        except ValueError as e:
            m.append(str(e))
    m += plantillas_precio.problemas_i17(cat)
    m += problemas_arreglos_i17(cat)
    m += plantillas_precio.problemas_i18(cat)  # I1.8: la clase completa (REVERIF17-2 y -3, LES-G-100.7 y .8)
    m += plantillas_precio.problemas_i19(cat)  # I1.9: por defecto, razones y disponibilidad en todas las filas
    ids = [a["id"] for a in cat.get("arquitecturas_referencia") or []]
    if len(set(ids)) != len(ids):
        m.append("arquitecturas_referencia: ids repetidos")
    for a in cat.get("arquitecturas_referencia") or []:
        ruta = normalizar_url(a["url"]).removeprefix("https://learn.microsoft.com")
        if not _con_prefijo(ruta, PREFIJOS_ARQUITECTURA):
            m.append(f"arquitectura {a['id']}: la URL no es de los prefijos de arquitectura de §6.3")
    return m


def problemas_arreglos_i17(cat: dict) -> list[str]:
    """Arreglos de I1.7: cada fila que llega al sandbox trae el título publicado de su referencia (PR17-1); los medidores
    obligatorios son plantillas de su fila (PR17-3); el cómputo por defecto es un nivel de su fila con esas plantillas
    exactas (PR17-4); `por_instancia` solo en plantillas de tiempo (PR17-5)."""
    m, filas = [], {c["id"]: c for c in cat["componentes"]}
    for c in cat["componentes"]:
        ids = {p["id"] for p in c.get("plantillas_precio") or []}
        if c.get("referencia_url") and en_lista_blanca(c["referencia_url"]) and not str(c.get("referencia_titulo") or "").strip():
            m.append(f"{c['id']}: sin referencia_titulo (título publicado de su referencia en Learn, PR17-1)")
        fuera = set(c.get("medidores_obligatorios") or []) - ids
        if fuera:
            m.append(f"{c['id']}: medidores_obligatorios {sorted(fuera)} no son plantillas de la fila")
        for p in c.get("plantillas_precio") or []:
            if p.get("por_instancia") is not None and p.get("impulsor") != "tiempo":
                m.append(f"{c['id']}/{p['id']}: por_instancia solo vale en una plantilla de tiempo")
    d = cat.get("computo_por_defecto")
    if d:
        fila = filas.get(d["componente"]) or {}
        nivel = next((n for n in fila.get("niveles") or [] if n["nivel"] == d["nivel"]), None)
        if nivel is None or sorted(nivel["plantillas"]) != sorted(d["plantillas"]):
            m.append("computo_por_defecto: el nivel no es de su fila o sus plantillas no son las del nivel")
    for a in cat.get("arquitecturas_referencia") or []:
        if not str(a.get("titulo") or "").strip():
            m.append(f"arquitectura {a.get('id')}: sin título publicado")
    return m


def problemas_instantanea(cat: dict) -> list[str]:
    """I1.7: la instantánea guardada cubre exactamente las plantillas del catálogo con sus filtros (sin mirar la
    antigüedad, que juzgan el núcleo y la puerta con la fecha del paquete). Si falta, se pide generarla."""
    faltan = [d for d in instantanea_precios.DESTINOS if not d.exists()]
    if faltan:
        return [f"falta {d}: genérala con python -m catalogo.instantanea_precios" for d in faltan]
    copias = [d.read_bytes() for d in instantanea_precios.DESTINOS]
    m = [] if len(set(copias)) == 1 else ["instantánea: las copias del catálogo y del sandbox no son iguales byte a byte"]
    try:
        inst = json.loads(copias[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return m + [f"instantánea ilegible: {e}"]
    return m + [f"instantánea: {x}" for x in instantanea_precios.problemas(inst, cat)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Deriva el catálogo del sandbox y las tablas.")
    ap.add_argument("--comprobar", action="store_true")
    ap.add_argument("--esquema-sandbox", type=pathlib.Path, default=ESQUEMA_SANDBOX,
                    help="esquema con el que se deriva y se valida (I1.7). Si no es el vigente, el derivado va a "
                         "docs/I1/CAMBIOS-I17-E/catalogo_componentes.derivado_propuesto.json y no al sandbox")
    a = ap.parse_args(argv)
    cat = cargar()
    problemas = problemas_catalogo(cat) + problemas_instantanea(cat)
    if problemas:  # Revisión I1.6: la forma del catálogo se comprueba al derivar, no solo en pytest (LES-G-091)
        print("NO SE DERIVA: el catálogo fuente tiene problemas:\n- " + "\n- ".join(problemas))
        return 2
    esquema = _esquema(a.esquema_sandbox)
    vigente = a.esquema_sandbox.resolve() == ESQUEMA_SANDBOX.resolve()
    aux = auxiliares_con_plantillas(esquema)
    derivado = catalogo_componentes(cat, esquema=esquema)
    # I1.7 (LES-G-091): el núcleo valida el catálogo del sandbox con su esquema y da IntegridadRota si no valida; un
    # derivado que no valida no se escribe nunca (antes se escribía y el fallo salía al cargar el núcleo).
    errores = comprobar_esquemas.validar(derivado, esquema, esquema)
    if errores:
        print(f"NO SE DERIVA: el catálogo derivado no valida contra {a.esquema_sandbox}:\n- " + "\n- ".join(errores)
              + "\nSi el esquema vigente se ha quedado corto, aplica docs/I1/CAMBIOS-I17-E.md (esquema propuesto).")
        return 2
    texto_derivado = json.dumps(derivado, ensure_ascii=False, indent=2) + "\n"
    if vigente:
        objetivos = {DERIVADO: texto_derivado, SANDBOX: texto_derivado}  # I1.6: copia del sandbox byte a byte igual
    else:
        objetivos = {DERIVADO_PROPUESTO: texto_derivado}
    tabla = tabla_markdown(cat, aux)
    for md in INSTRUCCIONES:
        objetivos[md] = insertar_tabla(md.read_text(encoding="utf-8"), tabla)
    # I1.7 (decisión 1): el experto ya no consulta precios; su bloque es el compacto v4 (plantillas por id, factores
    # estándar, modelo por defecto, ciclo de vida, niveles, inclusiones y arquitecturas), sin filtros.
    objetivos[INSTRUCCIONES[0]] = plantillas_precio.insertar_bloque_v4(objetivos[INSTRUCCIONES[0]],
                                                                        plantillas_precio.bloque_v4(cat, aux))
    # I1.9 (VC18-3): la disponibilidad por nivel y región es un dato del catálogo que el verificador no discute
    objetivos[INSTRUCCIONES[1]] = plantillas_precio.insertar_bloque_disponibilidad(
        objetivos[INSTRUCCIONES[1]], plantillas_precio.bloque_disponibilidad(cat))
    distintos = 0
    for ruta, contenido in objetivos.items():
        actual = ruta.read_text(encoding="utf-8") if ruta.exists() else None
        if actual == contenido:
            print(f"igual      {ruta.relative_to(RAIZ)}")
            continue
        distintos += 1
        if a.comprobar:
            print(f"DISTINTO   {ruta.relative_to(RAIZ)}")
        else:
            ruta.write_text(contenido, encoding="utf-8", newline="\n")
            print(f"escrito    {ruta.relative_to(RAIZ)}")
    return 1 if (a.comprobar and distintos) else 0


if __name__ == "__main__":
    sys.exit(main())
