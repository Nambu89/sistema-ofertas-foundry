"""Lo que ve el cliente: composición por código a partir de hechos (CONTRATOS.md §4.13 y §9.3-9.4).

LES-G-093/094: el texto lo compone el CÓDIGO con plantillas fijas y valores de hechos (nombres
oficiales del catálogo, valores de requisitos con su cita, importes del resumen, precios con su
fuente). La prosa del experto (supuestos y riesgos) solo entra si cita hechos existentes, pasa el
barrido y el verificador no la marcó DISCREPA. Lo que no pasa va a `excluidas` y a la nota.

`marcadores` es el barrido ÚNICO de §0 (palabra completa, LES-G-077) que usan todos los módulos.
`barrer` es el barrido de §9.3 (LES-G-053); `verificar_paquete.py` usa la unión de su réplica y este.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from nucleo import errores, hashes
from nucleo import estado as est_mod

SCHEMA = "preventa-textos-cliente/1"

# ───────────────────────────── barridos ─────────────────────────────

_MARC_MAYUS = re.compile(r"\b(TBD|TODO|XXX|PLACEHOLDER)\b")
_MARC_LIBRE = re.compile(r"(?<!\w)(pendientes?|por definir|lorem)(?!\w)")
_MARC_ANGULO = re.compile(r"<[^<>\n]{1,60}>")


def _nfc(t: str) -> str:
    return unicodedata.normalize("NFC", t)


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def _plano(t: str) -> str:
    return re.sub(r"\s+", " ", _sin_tildes(_nfc(t)).lower()).strip()


def marcadores(texto: str) -> list[str]:
    """Marcadores de §0 por palabra completa; [] si no hay. Nunca por subcadena (LES-G-077)."""
    if not isinstance(texto, str) or not texto:
        return []
    t = _nfc(texto)
    halla = [f"marcador «{m.group(0)}»" for m in _MARC_MAYUS.finditer(t)]
    halla += [f"marcador «{m.group(0)}»" for m in _MARC_LIBRE.finditer(_sin_tildes(t).lower())]
    halla += [f"marcador «{m.group(0)}»" for m in _MARC_ANGULO.finditer(t)]
    return halla


_PROHIBIDO = [
    (re.compile(r"\d\s*(h|hrs?|horas?)\b", re.I), "horas tras un número"),
    (re.compile(r"\bhoras?\b", re.I), "horas"),
    (re.compile(r"\bjornadas?\b", re.I), "jornadas"),
    (re.compile(r"\bd[ií]as?[- ]persona\b", re.I), "días-persona"),
    (re.compile(r"(€|eur|euros?)\s*/\s*(h|hora|jornada)\b", re.I), "importe por hora o jornada"),
    (re.compile(r"\btarifas?\b", re.I), "tarifa"),
    (re.compile(r"\bcontingencias?\b", re.I), "contingencia"),
    (re.compile(r"\bajustes? comercial(es)?\b", re.I), "ajuste comercial"),
    (re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b", re.I), "identificador snake_case"),
    (re.compile(r"\b(REF|RG|BRF|CNS|TX|PM|[CPTS])-\d{1,3}\b"), "id técnico"),
    (re.compile(r"\b(BRF|CNS)-OF-"), "id técnico"),
    (re.compile(r"\bR-[a-z_]{3,}\b"), "id de requisito"),
    (re.compile(r"\bcatalogo_id\b", re.I), "identificador técnico"),
    (re.compile(r"\b[\w.-]+\.(json|xlsx|pptx|docx|py|txt|zip|vtt|csv)\b", re.I), "nombre de fichero"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "correo"),
]


def barrer(texto: str, perfiles: list[str]) -> list[str]:
    """Hallazgos de §9.3 (horas, jornadas, €/h, tarifa, perfiles, contingencia, ajuste comercial,
    identificadores técnicos, nombres de fichero, correos y marcadores); [] si está limpio."""
    if not isinstance(texto, str) or not texto:
        return []
    halla: list[str] = []
    for rx, motivo in _PROHIBIDO:
        halla += [f"{motivo}: «{m.group(0)}»" for m in rx.finditer(texto)]
    pl = _plano(texto)
    for p in perfiles or []:
        if p and re.search(r"(?<!\w)" + re.escape(_plano(p)) + r"(?!\w)", pl):
            halla.append(f"nombre de perfil de la tarifa: «{p}»")
    return halla + marcadores(texto)


def frases_excluidas(textos: dict) -> list[dict]:
    """Frases retiradas (para la nota): [{"origen", "texto", "motivo"}]."""
    return [dict(x) for x in ((textos or {}).get("excluidas") or [])]


def formato_eur(importe: str) -> str:
    """«17852.50» → «17.852,50 €» (misma forma que pptx_revision.formato_eur)."""
    try:
        d = Decimal(str(importe)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as e:
        raise errores.IntegridadRota(f"importe no numérico: {importe!r}", []) from e
    signo = "-" if d < 0 else ""
    entero, dec = f"{abs(d):.2f}".split(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return f"{signo}{'.'.join(grupos)},{dec} €"


# ───────────────────────────── composición ─────────────────────────────

CAPAS = (("usuarios_canales", "Usuarios y canales"), ("aplicacion_integracion", "Aplicación e integración"),
         ("ia", "Inteligencia artificial"), ("datos_conocimiento", "Datos y conocimiento"),
         ("identidad_seguridad_red", "Identidad, seguridad y red"),
         ("operacion_observabilidad", "Operación y observabilidad"))
ETIQUETAS = {"volumetria": "Volumetría", "identidad_acl_origen": "Identidad y permisos del origen",
             "red_privada": "Red privada", "tipo_suscripcion": "Tipo de suscripción", "plazo": "Plazo",
             "presupuesto_orientativo": "Presupuesto orientativo", "idioma_oferta": "Idioma de la oferta",
             "objetivo": "Objetivo", "nubes": "Nubes", "alcance_funcional": "Alcance funcional",
             "canales_integraciones": "Canales e integraciones",
             "ubicacion_usuarios": "Ubicación de los usuarios finales", "marco_normativo": "Marco normativo",
             "fuera_de_alcance": "Fuera de alcance"}
NIVEL = {"ALTA": "Confianza alta", "MEDIA": "Confianza media", "BAJA": "Confianza baja"}
# VA18-12 (I1.9): el dato asumido se presenta con su artículo («Dato por confirmar con el cliente sobre la red privada»)
ARTICULOS = {"volumetria": "la volumetría", "identidad_acl_origen": "la identidad y los permisos del origen",
             "red_privada": "la red privada", "tipo_suscripcion": "el tipo de suscripción", "plazo": "el plazo",
             "idioma_oferta": "el idioma de la oferta", "objetivo": "el objetivo", "nubes": "las nubes",
             "alcance_funcional": "el alcance funcional", "canales_integraciones": "los canales e integraciones",
             "ubicacion_usuarios": "la ubicación de los usuarios finales", "marco_normativo": "el marco normativo",
             "fuera_de_alcance": "lo que queda fuera de alcance"}
# VA18-1 (I1.9, LES-G-053): el presupuesto del alta es un dato comercial interno; nunca llega a lo que ve el cliente,
# ni CITADO ni ASUMIDO (se queda en la nota del revisor)
CAMPOS_INTERNOS = frozenset({"presupuesto_orientativo"})
# I1.9 (contrato común): un componente que ES un recurso que el cliente ya tiene se dibuja y se nombra como suyo
SUFIJO_EXISTENTE = " (sistema del cliente)"
MAX_NOMBRE_EXISTENTE = 50
FIJO_EXCLUSIONES = "Licencias y consumo en la nube, que asume el cliente."
FIJO_SOPORTE = "Soporte posterior a la aceptación del proyecto."
AVISO_CONSUMO = "Orientativo. No incluido en el precio cerrado; lo asume el cliente."
PRECIOS_CONSULTADOS = "precios consultados el"  # I1.7: literal que exige la decisión 1 del comercial (13-10-2026)
LIMITES = {"necesidad": 8, "alcance": 15, "fuera_de_alcance": 15, "supuestos": 25, "riesgos": 20}

# REV13-3: el título de Learn llega en inglés y traducirlo no tiene fuente. El código compone el título en
# castellano desde el tema de la ruta de la URL (la lista blanca de experto.PREFIJOS_REFERENCIA, §6.3): el
# prefijo más largo que la contiene da el tema. Una URL sin tema se retira y va a la nota (LES-G-094).
REFERENCIA = "Documentación oficial de Microsoft sobre {tema}"
MAX_TITULO_REFERENCIA = 200  # el tope de `titulo` en esquemas/textos_cliente.json
TEMAS_REFERENCIA: dict[str, str] = {
    "/azure/architecture": "arquitecturas de referencia de Azure",
    "/azure/well-architected": "el marco de buena arquitectura de Azure",
    "/azure/cloud-adoption-framework": "el marco de adopción de la nube de Azure",
    "/azure/ai-foundry": "Microsoft Foundry", "/azure/foundry": "Microsoft Foundry",
    "/azure/foundry-classic": "Microsoft Foundry", "/azure/search": "Azure AI Search",
    "/azure/ai-services": "Foundry Tools", "/azure/security": "la seguridad en Azure",
    "/azure/private-link": "Azure Private Link", "/azure/virtual-network": "Azure Virtual Network",
    "/azure/app-service": "Azure App Service", "/azure/container-apps": "Azure Container Apps",
    "/azure/azure-functions": "Azure Functions", "/azure/storage": "Azure Storage",
    "/azure/cosmos-db": "Azure Cosmos DB", "/azure/key-vault": "Azure Key Vault",
    "/azure/azure-monitor": "Azure Monitor", "/azure/api-management": "Azure API Management",
    "/azure/reliability": "la fiabilidad en Azure", "/azure/defender-for-cloud": "Microsoft Defender for Cloud",
    "/azure/governance": "la gobernanza en Azure",
    "/azure/role-based-access-control": "el control de acceso basado en roles de Azure",
    "/azure/cost-management-billing": "Microsoft Cost Management", "/azure/logic-apps": "Azure Logic Apps",
    "/azure/bot-service": "Azure AI Bot Service", "/entra": "Microsoft Entra", "/purview": "Microsoft Purview",
    "/compliance": "el cumplimiento normativo con Microsoft Purview",
    "/security/benchmark/azure": "la referencia de seguridad en la nube de Microsoft",
    "/microsoftteams/platform": "la plataforma de desarrollo de Microsoft Teams",
    "/azure/frontdoor": "Azure Front Door", "/azure/web-application-firewall": "Azure Web Application Firewall",
    "/azure/firewall": "Azure Firewall", "/azure/application-gateway": "Azure Application Gateway",
    "/azure/dns": "Azure DNS", "/azure/bastion": "Azure Bastion", "/azure/ddos-protection": "la protección de Azure contra ataques de denegación de servicio",
    "/azure/networking": "las redes de Azure", "/azure/expressroute": "Azure ExpressRoute",
    "/azure/vpn-gateway": "Azure VPN Gateway", "/azure/event-grid": "Azure Event Grid",
    "/azure/service-bus-messaging": "Azure Service Bus", "/azure/azure-sql": "Azure SQL",
    "/azure/postgresql": "Azure Database for PostgreSQL", "/azure/data-factory": "Azure Data Factory",
    "/azure/databricks": "Azure Databricks", "/azure/aks": "Azure Kubernetes Service",
    "/azure/container-registry": "Azure Container Registry", "/azure/machine-learning": "Azure Machine Learning",
    "/azure/redis": "Azure Managed Redis", "/azure/sentinel": "Microsoft Sentinel", "/azure/backup": "Azure Backup",
    "/azure/azure-resource-manager": "Azure Resource Manager", "/fabric": "Microsoft Fabric",
    "/power-bi": "Power BI", "/office365": "Microsoft 365", "/microsoft-365": "Microsoft 365",
    "/microsoft-copilot-studio": "Microsoft Copilot Studio",
}


# PR17-9 (arreglos I1.7): páginas concretas cuyo tema no es el de su prefijo de la lista blanca (la de límites de las
# suscripciones salía como «Azure Resource Manager»). TEMAS_REFERENCIA sigue siendo exactamente la lista blanca.
TEMAS_PAGINA: dict[str, str] = {
    "/azure/azure-resource-manager/management/azure-subscription-service-limits":
        "los límites de las suscripciones y los servicios de Azure",
}


def titulo_referencia(url: str) -> str | None:
    """«Documentación oficial de Microsoft sobre <tema>» para una URL de Learn; None si no tiene tema."""
    from nucleo import experto  # diferido: experto importa módulos de A
    ruta = experto._ruta(url)
    if ruta in TEMAS_PAGINA:
        return REFERENCIA.format(tema=TEMAS_PAGINA[ruta])
    candidatos = [p for p in TEMAS_REFERENCIA if ruta == p or ruta.startswith(p + "/")]
    return REFERENCIA.format(tema=TEMAS_REFERENCIA[max(candidatos, key=len)]) if candidatos else None


# REV13-3 (LES-G-093): el concepto de un precio no es el meterName crudo («GPT 5 Mini Inpt DZone»). Lo
# compone el código con el tipo de medidor (palabras del meterName y unidad), el plan (skuName del filtro,
# si es legible) y el producto de precios del catálogo cuando no coincide con el servicio de la fila.
_MEDIDOR_TOKENS = (
    (re.compile(r"\b(cached|cchd)\b"), "Tokens de entrada en caché del modelo"),
    (re.compile(r"\b(input|inpt|inp)\b"), "Tokens de entrada del modelo"),
    (re.compile(r"\b(output|outpt|outp|opt)\b"), "Tokens de salida del modelo"),  # I1.7: «6-luna … Opt …»
)
# PR17-9 (arreglos I1.7): dos medidores por tiempo del mismo servicio (Functions Premium: núcleos y memoria) salían los
# dos como «Tiempo de funcionamiento»; se distinguen por el medidor.
_MEDIDOR_TIEMPO = ((re.compile(r"\bvcpu\b"), "Tiempo de funcionamiento de los núcleos"),
                   (re.compile(r"\bmemory\b"), "Tiempo de funcionamiento de la memoria"))
_MEDIDOR_OTROS = (
    # D18-2 (I1.8): «Semantic Ranker queries» de Azure AI Search salía como «Consumo del servicio (por mil)»
    (re.compile(r"\bsemantic rank(er|ing)\b"), "Consultas de ranking semántico"),
    (re.compile(r"\bmessages?\b"), "Mensajes de canal"),
    (re.compile(r"\b(data stored|storage|capacity)\b"), "Almacenamiento de datos"),
    (re.compile(r"\b(transactions?|operations?|requests?|calls?)\b"), "Operaciones"),
)
_ZONAS_MEDIDOR = ((re.compile(r"\b(dzone|data ?zone|dz)\b"), ", zona de datos"),  # I1.7: «… Std DZ 1M Tokens»
                  (re.compile(r"\b(glbl|global)\b"), ", despliegue global"),
                  (re.compile(r"\b(rgnl|regional)\b"), ", despliegue regional"))
# I1.7 (GPT-6, Retail Prices EUR, 13-10-2026): «ShortCo» y «LongCo» separan el precio de contexto corto y largo, que
# decide el número de tokens de entrada de cada petición; el cliente ve de cuál de los dos es la línea
_CONTEXTO_MEDIDOR = ((re.compile(r"\bshortco\b"), ", contexto corto"), (re.compile(r"\blongco\b"), ", contexto largo"))
_SKU_FILTRO = re.compile(r"(?<![A-Za-z])skuName eq '([^']{1,80})'")
_PLAN_LEGIBLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+.-]{0,15}(?: [A-Za-z0-9+.-]{1,15}){0,2}")
_UNIDAD = re.compile(r"(\d+)\s*([km](?![a-z]))?\s*(.*)")  # «1 month» no es «1 m» + «onth»


def _unidad_legible(unidad: object) -> str:
    """« (por millón)», « (por mil)», « (por GB al mes)»…; "" si es por hora (§9.3) o no se reconoce."""
    u = _plano(str(unidad or ""))
    m = _UNIDAD.fullmatch(u)
    if not m or "hour" in u:
        return ""
    cantidad = int(m.group(1)) * {None: 1, "k": 1000, "m": 1000000}[m.group(2)]
    resto = m.group(3).strip().lstrip("/").strip()
    if resto in ("", "tokens", "token", "messages", "count", "units", "unit"):
        nombres = {1: "", 1000: " (por mil)", 1000000: " (por millón)"}
        return nombres.get(cantidad, f" (por cada {cantidad:,})".replace(",", "."))
    if cantidad == 1 and re.fullmatch(r"gb\s*/\s*month|gb/mes", resto):
        return " (por GB al mes)"
    if cantidad == 1 and resto in ("gb", "tb"):
        return f" (por {resto.upper()})"
    return {"month": " (al mes)", "day": " (al día)"}.get(resto, "") if cantidad == 1 else ""


_MARCAS_PRODUCTO = frozenset({"azure", "ai", "microsoft"})


def mismo_producto(producto: object, servicio: object) -> bool:
    """VA18-12 (I1.9): «Azure Bot Service» (producto de precios) y «Azure AI Bot Service» (servicio de la fila) son el
    mismo producto: sus palabras coinciden sin contar «Azure», «AI» ni «Microsoft». Entonces el concepto no lo repite
    con otro nombre en la misma fila."""
    def palabras(t):
        return set(re.findall(r"\w+", _plano(str(t or "")))) - _MARCAS_PRODUCTO
    return _plano(str(producto or "")) == _plano(str(servicio or "")) or palabras(producto) == palabras(servicio)


def concepto_legible(linea: dict, producto: str | None = None) -> str:
    """Concepto de una línea del anexo para el cliente, compuesto por código (nunca el meterName crudo)."""
    medidor = _plano(re.sub(r"[;,()]", " ", str(linea.get("concepto") or "")))
    servicio = str(linea.get("servicio") or "")
    tipo = next((t for rx, t in _MEDIDOR_TOKENS if rx.search(medidor)), None)
    de_tokens = tipo is not None
    if tipo is None and "hour" in _plano(str(linea.get("unidad") or "")):
        tipo = next((t for rx, t in _MEDIDOR_TIEMPO if rx.search(medidor)), "Tiempo de funcionamiento")
    tipo = tipo or next((t for rx, t in _MEDIDOR_OTROS if rx.search(medidor)), "Consumo del servicio")
    if producto and not mismo_producto(producto, servicio):
        tipo += f" de {producto}"
    if de_tokens:
        tipo += next((z for rx, z in _CONTEXTO_MEDIDOR if rx.search(medidor)), "")
        tipo += next((z for rx, z in _ZONAS_MEDIDOR if rx.search(medidor)), "")
    else:
        sku = _SKU_FILTRO.search(str(linea.get("filtro") or ""))
        if sku and _PLAN_LEGIBLE.fullmatch(sku.group(1).strip()):
            tipo += f", plan {sku.group(1).strip()}"
    return _nfc(tipo + _unidad_legible(linea.get("unidad")))


def productos_precio(resp: dict, catalogo: dict) -> dict[str, str]:
    """{componente_id: producto de precios}: `producto_precios` del catálogo o, si no hay, el nombre oficial."""
    cat = {c["id"]: c for c in (catalogo or {}).get("componentes") or []}
    salida = {}
    for comp in (resp or {}).get("componentes") or []:
        entrada = cat.get(comp.get("catalogo_id")) if comp.get("catalogo_id") else None
        if entrada:
            salida[comp.get("id")] = entrada.get("producto_precios") or entrada.get("nombre_oficial")
    return salida


def hechos_de(carga: dict) -> dict:
    """Objeto cuya huella es hash_hechos (§9.4): exactamente esas seis claves."""
    return {"alta": carga.get("alta"), "requisitos": carga.get("requisitos"),
            "respuestas_expertos": carga.get("respuestas_expertos"), "verificacion": carga.get("verificacion"),
            "anexo_consumo": carga.get("anexo_consumo"),
            "estimacion_resumen": (carga.get("estimacion") or {}).get("resumen")}


def _frase_final(valor: str) -> str:
    """Una sola frase terminada en punto; sin «;», «,» ni «:» colgando antes del punto (H8)."""
    v = re.sub(r"\s+", " ", _nfc(str(valor))).strip().rstrip(";,:").rstrip()
    return v if v.endswith((".", "!", "?")) else v + "."


# ── I1.5 (D): rótulos, plazo del Gantt y asunciones de la estimación ──

# Palabras comunes (lista blanca, LES-G-098.3): tras los dos puntos van en minúscula (VER14-8) y, delante de un
# tipo de despliegue, no piden «en» (PR14-4). Un nombre propio («España», «Unión Europea») no está aquí y no cambia.
PALABRAS_COMUNES = frozenset(_plano(w) for w in (
    "el la lo los las un una unos unas al del se no si sí solo todo todos toda todas cada cualquier ningún ninguna "
    "algún alguna algunos algunas este esta estos estas ese esa esos esas su sus nuestro nuestra nuestros nuestras "
    "a en de desde para por con sin sobre entre hasta según durante mediante ante bajo tras y o ni pero que como "
    "cuando donde debe deben debería deberían tiene tienen tenemos hay es son está están será serán puede pueden "
    "aplica aplican aplicamos cumplimos cumplir cumplimiento datos información normativa protección seguridad "
    "acceso uso usuarios usar utilizar mediante").split())
# VA18-12 (E1, I1.9): «Objetivo: Implementar…» → «Objetivo: implementar…». Lista blanca de infinitivos con los que
# suele empezar un objetivo o una capacidad (LES-G-098.3): un sufijo «-ar/-er/-ir» no basta («Power BI», «Partner»).
VERBOS_INFINITIVO = frozenset(_plano(w) for w in (
    "implementar crear desarrollar construir disponer ofrecer facilitar reducir mejorar automatizar responder "
    "permitir proporcionar habilitar desplegar integrar centralizar agilizar consultar ayudar resolver gestionar "
    "atender buscar generar analizar optimizar digitalizar contar acelerar simplificar unificar garantizar asegurar "
    "evaluar validar diseñar migrar modernizar sustituir reemplazar apoyar informar localizar encontrar obtener "
    "acceder conectar publicar aprovechar extraer clasificar resumir traducir detectar predecir monitorizar "
    "controlar supervisar revisar preparar elaborar redactar priorizar asistir orientar guiar registrar dar poner "
    "incorporar explotar recuperar citar cumplir mantener poder").split())


def minuscula_inicial(valor: str) -> str:
    """«Los datos tienen…» → «los datos tienen…» si la primera palabra es común; si no (sigla, nombre), igual."""
    m = re.match(r"(\w+)", valor)
    if m and m.group(1)[0].isupper() and (m.group(1)[1:] == "" or m.group(1)[1:].islower()) \
            and _plano(m.group(1)) in PALABRAS_COMUNES | VERBOS_INFINITIVO:
        return valor[0].lower() + valor[1:]
    return valor


def _sin_punto_final(valor: str) -> str:
    """Quita el punto final de un valor para unirlo con «; », salvo abreviaturas («EE. UU.») y puntos suspensivos."""
    v = re.sub(r"\s+", " ", _nfc(str(valor))).strip().rstrip(";,:").rstrip()
    if v.endswith("...") or re.search(r"(?:^|\s)[A-ZÁÉÍÓÚÑ]{1,2}\.$", v):
        return v
    return v.removesuffix(".")


def etiquetadas(etiqueta: str, valores: list[str], hecho: str, origen: str) -> list[tuple[str, list[str], str]]:
    """VER14-8: una sola viñeta por rótulo («Marco normativo: RGPD; los datos tienen que…»), con los valores sin
    repetir unidos con «; » y en minúscula tras los dos puntos y el punto y coma si empiezan por una palabra
    común. Si no cabe en 400 caracteres, sigue en otra viñeta con el mismo rótulo (nada se pierde en silencio)."""
    salida, actual, vistos = [], [], set()
    for v in valores:
        v = minuscula_inicial(_sin_punto_final(v))
        if not v or _plano(v) in vistos:
            continue
        vistos.add(_plano(v))
        if actual and len(_frase_final(f"{etiqueta}: " + "; ".join(actual + [v]))) > 400:
            salida.append((_frase_final(f"{etiqueta}: " + "; ".join(actual)), [hecho], origen))
            actual = []
        actual.append(v)
    if actual:
        salida.append((_frase_final(f"{etiqueta}: " + "; ".join(actual)), [hecho], origen))
    return salida


# PR14-4: el plazo que cita la prosa del experto sale del Gantt. «El plazo de ocho semanas» (el plazo que deseaba
# el cliente) se reescribe con la duración del Gantt; cualquier otra cantidad de semanas o meses que no sea esa
# no se publica y va a la nota (falla cerrado: no se puede saber si contradice el plan).
_NUMEROS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
            "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
            "dieciséis": 16, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20}
_NUMEROS.update({"veintiuno": 21, "veintiuna": 21, "veintidós": 22, "veintidos": 22, "veintitrés": 23,
                 "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiséis": 26, "veintiseis": 26,
                 "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40,
                 "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100})
_EN_LETRA = {n: w for w, n in _NUMEROS.items() if w not in ("un", "uno", "dieciseis") and n <= 20}
# revisión independiente (I1.5): sin tope de cifras («1000 semanas», «1.000 semanas») y con las decenas en letra; lo
# compuesto («treinta y dos semanas») casa por su último número y, si no es el del Gantt, se retira
_CANTIDAD = r"(?P<n>\d{1,3}(?:\.\d{3})+|\d+|" + "|".join(sorted(_NUMEROS, key=len, reverse=True)) + r")"
_RE_PLAZO = re.compile(r"(?<!\w)(?P<ctx>plazo|duraci[oó]n|calendario|cronograma|planificaci[oó]n|proyecto|piloto)"
                       r"(?P<medio>\s+(?:(?:total|previst[oa]|estimad[oa]|deseado|objetivo)\s+)?de\s+)"
                       r"(?:(?:unas?|aproximadamente|alrededor\s+de|cerca\s+de)\s+)?" + _CANTIDAD +
                       r"\s+(?P<u>semanas?|meses?)(?!\w)", re.I)
_RE_TIEMPO = re.compile(r"(?<!\w)" + _CANTIDAD + r"\s+(?P<u>semanas?|meses?)(?!\w)", re.I)
# segunda pasada de la revisión independiente (I1.5): una cantidad con decimales («5,5 semanas») o compuesta en letra («treinta y dos»,
# «ciento veinte») no se interpreta por su último número: se declara no interpretable y la frase va a la nota
_RE_ANTES_COMPUESTO = re.compile(r"(?:\d[.,]|(?<!\w)(?:" + "|".join(sorted(_NUMEROS, key=len, reverse=True)) +
                                 r"|ciento|cientos|mil)\s+(?:y\s+)?|(?<!\w)(?:coma|punto)\s+)$", re.I)


def semanas_en_letra(n: int) -> str:
    """1 → «una semana»; 5 → «cinco semanas»; 30 → «30 semanas»."""
    return "una semana" if n == 1 else f"{_EN_LETRA.get(n, str(n))} semanas"


def plazo_del_gantt(texto: str, semanas: object) -> tuple[str, str | None]:
    """(texto con el plazo del Gantt, motivo para no publicarlo o None)."""
    t = _nfc(str(texto or ""))
    if not _RE_TIEMPO.search(t):
        return t, None
    raros = [m.group(0) for m in _RE_TIEMPO.finditer(t) if _RE_ANTES_COMPUESTO.search(t[:m.start()])]
    if raros:
        return t, f"cita un plazo que no se puede interpretar («…{raros[0]}») (PR14-4)"
    if isinstance(semanas, bool) or not isinstance(semanas, int) or semanas < 1:
        return t, "cita un plazo y no hay un Gantt con el que contrastarlo (PR14-4)"
    meses = [m.group(0) for m in _RE_PLAZO.finditer(t) if m.group("u").lower().startswith("mes")]
    if meses:
        return t, f"cita un plazo en meses («{meses[0]}») y el Gantt dura {semanas_en_letra(semanas)} (PR14-4)"
    t = _RE_PLAZO.sub(lambda m: f"{m.group('ctx')}{m.group('medio')}{semanas_en_letra(semanas)}", t)

    def cantidad(m) -> int:
        n = m.group("n").lower()
        return int(n.replace(".", "")) if n[:1].isdigit() else _NUMEROS[n]
    otras = [m.group(0) for m in _RE_TIEMPO.finditer(t)
             if m.group("u").lower().startswith("mes") or cantidad(m) != semanas]
    if otras:
        return t, f"cita «{otras[0]}» y el Gantt dura {semanas_en_letra(semanas)}: no se sabe si lo contradice (PR14-4)"
    return t, None


# H10: lo que el modelo escribe como estado interno («NO VERIFICADO», «no verificable», palabras en
# mayúsculas seguidas) no llega al cliente; lo dice el código en castellano llano (riesgos de consumo).
_RE_ESTADO_INTERNO = re.compile(r"(?<!\w)no\s+(verificad[oa]s?|verificables?|comprobad[oa]s?\s+por\s+el\s+verificador)(?!\w)",
                                re.I)
_RE_GRITO = re.compile(r"(?<!\w)[A-ZÁÉÍÓÚÑÜ]{2,}(?:\s+[A-ZÁÉÍÓÚÑÜ]{2,})+(?!\w)")


def redaccion_interna(texto: str) -> list[str]:
    """Motivos por los que una frase del modelo es redacción interna y no texto para el cliente."""
    t = _nfc(str(texto or ""))
    halla = [f"estado interno «{m.group(0)}»" for m in _RE_ESTADO_INTERNO.finditer(t)]
    # dos o más palabras en mayúsculas con al menos una de 6 letras: «NO VERIFICADO» sí; siglas
    # seguidas como «API REST» o «RGPD UE», no
    halla += [f"mayúsculas «{m.group(0)}»" for m in _RE_GRITO.finditer(t)
              if any(len(w) >= 6 for w in m.group(0).split())]
    # VA18-12 (I1.9): el catálogo de componentes es una herramienta interna; el cliente no lo conoce
    halla += [f"referencia al catálogo interno «{m.group(0)}»" for m in _RE_CATALOGO_INTERNO.finditer(t)]
    return halla


# VERIF-8: los tipos de despliegue de Foundry son identificadores de SKU y no llegan al cliente; se
# traducen a castellano llano. Nombres de Learn, «Deployment types for Microsoft Foundry Models»
# (https://learn.microsoft.com/azure/foundry/foundry-models/concepts/deployment-types, consultado el
# 2026-10-08). La zona de datos de la UE sigue el Límite de datos de la UE de Microsoft (misma página).
# Orden: primero los nombres más largos. Si delante va «el despliegue», «la modalidad», «SKU»…, se
# absorbe para no decir «despliegue despliegue»; la traducción lleva su propio artículo.
# PR14-4: también se absorbe un artículo suelto («el DataZoneStandard»); el grupo «previo» dice si se absorbió algo.
_PREVIO_SKU = (r"(?P<previo>(?:(?:el|la|los|las|un|una)\s+)?(?:tipo\s+de\s+despliegue|despliegue|modalidad|sku)\s+"
               r"(?:de\s+)?|(?:el|la|los|las|un|una)\s+)?")
_SKU_LLANO = tuple((re.compile(r"(?<![\w-])" + _PREVIO_SKU + r"(?:" + rx + r")(?![\w-])", re.I), plantilla)
                   for rx, plantilla in (
    (r"Data\s*Zone\s*Provisioned(?:\s*Managed)?", "una capacidad reservada que procesa los datos solo {dentro}"),
    (r"Data\s*Zone\s*Batch", "un procesamiento por lotes solo {dentro}"),
    (r"Data\s*Zone\s*Standard", "un despliegue que procesa los datos solo {dentro}"),
    (r"Global\s*Provisioned(?:\s*Managed)?",
     "una capacidad reservada global que puede procesar los datos fuera de la región elegida"),
    (r"Global\s*Batch", "un procesamiento por lotes global que puede procesar los datos fuera de la región elegida"),
    (r"Global\s*Standard", "un despliegue global que puede procesar los datos fuera de la región elegida"),
    (r"Regional\s*Provisioned(?:\s*Managed)?|Provisioned\s*Managed", "una capacidad reservada en la región elegida"),
    (r"Developer\s*Tier", "un despliegue de evaluación sin acuerdo de nivel de servicio"),
))
# Regiones cuya zona de datos se conoce (lista blanca: una región que no está aquí no se traduce y la
# frase se retira, LES-G-098.3). UE: solo regiones de estados miembros.
_ZONAS = (
    ("dentro del Límite de datos de la UE", frozenset({
        "swedencentral", "swedensouth", "francecentral", "francesouth", "germanywestcentral", "germanynorth",
        "italynorth", "polandcentral", "spaincentral", "northeurope", "westeurope"})),
    ("dentro de EE. UU.", frozenset({
        "eastus", "eastus2", "westus", "westus2", "westus3", "centralus", "northcentralus", "southcentralus",
        "westcentralus"})),
)


def _dentro_de_zona(regiones) -> str | None:
    """Zona de datos de un conjunto de regiones, o None si está vacío, mezcla zonas o no se conoce."""
    rs = {re.sub(r"\s+", "", str(r)).lower() for r in regiones or [] if str(r or "").strip()}
    return next((frase for frase, zona in _ZONAS if rs and rs <= zona), None)


def traducir_skus(texto: str, regiones=()) -> str:
    """Sustituye los tipos de despliegue por su explicación en castellano llano. Los de zona de datos
    necesitan la región; si no se conoce, se dejan tal cual y `jerga_tecnica` retira la frase."""
    t, dentro = _nfc(str(texto or "")), _dentro_de_zona(regiones)
    for rx, plantilla in _SKU_LLANO:
        if "{dentro}" in plantilla and dentro is None:
            continue
        llano = plantilla.format(dentro=dentro or "")

        def _poner(m, llano=llano, t=t):  # mayúscula si abre la frase; sin doble punto tras «EE. UU.»
            antes = t[:m.start()]
            inicio = m.start() == 0 or re.search(r"[.!?]\s+$", antes)
            sale = llano[0].upper() + llano[1:] if inicio else llano
            # PR14-4: tras un nombre («El modelo GPT-5 DataZoneStandard y…») la traducción necesita «en» para
            # concordar («El modelo GPT-5 en un despliegue que…»); tras una preposición o un verbo, no
            previa = re.search(r"([\w.-]+)\s+$", antes)
            palabra = previa.group(1) if previa else ""
            primera = previa is not None and (previa.start(1) == 0 or re.search(r"[.!?]\s+$", antes[:previa.start(1)]))
            nombre = bool(re.search(r"\d|.[A-ZÁÉÍÓÚÑ]", palabra)) or (not primera and palabra[:1].isupper())
            if not inicio and not m.group("previo") and nombre and _plano(palabra) not in PALABRAS_COMUNES:
                sale = "en " + sale  # «Usamos RegionalProvisioned…» no lleva «en»: «Usamos» abre la frase
            return sale[:-1] if sale.endswith(".") and t[m.end():m.end() + 1] == "." else sale
        t = rx.sub(_poner, t)
    return t


# Nombres de producto con mayúscula interna que sí puede leer el cliente (lista blanca, LES-G-098.3).
# Cualquier otra palabra con una minúscula seguida de una mayúscula («DataZoneStandard», «gpt5Mini»)
# es un identificador técnico y la frase no se publica.
MARCAS_ADMITIDAS = frozenset({
    "sharepoint", "onedrive", "onenote", "onelake", "powerpoint", "powershell", "powerbi", "openai", "devops",
    "devsecops", "finops", "github", "linkedin", "youtube", "whatsapp", "javascript", "typescript", "postgresql",
    "mysql", "nosql", "graphql", "iot", "ios", "macos", "ipad", "iphone", "saas", "paas", "iaas", "genai",
    "signalr", "expressroute", "biztalk", "servicenow", "opentelemetry", "openshift", "websocket", "websockets",
    "bitlocker", "cosmosdb",
})
_RE_CAMEL = re.compile(r"\b\w*[a-záéíóúñü][A-ZÁÉÍÓÚÑÜ]\w*\b")


def jerga_tecnica(texto: str, admitidas=frozenset()) -> list[str]:
    """Identificadores técnicos en prosa del cliente (VERIF-8): palabras con mayúscula interna fuera de la
    lista blanca (más `admitidas`, p. ej. el nombre del cliente) y tipos de despliegue sin traducir."""
    t = _nfc(str(texto or ""))
    permitidas = MARCAS_ADMITIDAS | {_plano(a) for a in admitidas or ()}
    halla = [f"identificador técnico «{m.group(0)}»" for m in _RE_CAMEL.finditer(t)
             if _plano(m.group(0)) not in permitidas]
    halla += [f"tipo de despliegue sin traducir «{m.group(0)}»" for rx, _ in _SKU_LLANO for m in rx.finditer(t)]
    return list(dict.fromkeys(halla))


def palabras_admitidas(*textos: str) -> frozenset:
    """Palabras de nombres propios fiables (cliente, catálogo) que `jerga_tecnica` no debe retirar."""
    return frozenset(w for t in textos for w in re.findall(r"\w+", _nfc(str(t or ""))))


# Repetición entre frases (VERIF-8): raíz de 5 letras de las palabras de 4 o más letras, sin vacías
# normalizadas con la misma función que el texto (LES-G-084).
_VACIAS = frozenset(_plano(w) for w in ("como cuando desde entre para sobre siempre tambien todo todos toda todas "
                                        "esta este estos estas cada donde según").split())


def _raices(texto: str) -> set[str]:
    return {w[:5] for w in re.findall(r"\w+", _plano(texto)) if len(w) >= 4 and w not in _VACIAS}


def repite(frase: str, otra: str) -> bool:
    """True si `frase` dice lo mismo que `otra`: comparten 3 o más raíces y al menos el 60 % de las de
    `frase`. Una coincidencia de una o dos palabras nunca basta."""
    a, comunes = _raices(frase), _raices(frase) & _raices(otra)
    return len(comunes) >= 3 and len(comunes) >= 0.6 * len(a)


def _lista_y(nombres: list[str]) -> str:
    """«A», «A y B», «A, B y C» (sin repetidos, en orden)."""
    n = list(dict.fromkeys(nombres))
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " y " + n[-1]


lista_y = _lista_y  # pública: la usa pptx_revision para las filas «No valorado» agrupadas (REV13-3)

# I1.6 (D): con filas «No valorado», el total solo suma lo valorado y su fila lo dice (diapositiva 8 y anexo).
CONCEPTOS_VALORADOS = "conceptos valorados"


def etiquetas_total(hay_no_valorados: bool) -> tuple[str, str]:
    """(fila del total mensual, fila del total anual) de la tabla de consumo de la diapositiva 8."""
    sufijo = f" ({CONCEPTOS_VALORADOS})" if hay_no_valorados else ""
    return f"Total mensual{sufijo}", f"Total anual{sufijo}"


def _valores(campos: dict, campo: str) -> list[str]:
    return [re.sub(r"\s+", " ", _nfc(str(e.get("valor", "")))).strip()
            for e in ((campos.get(campo) or {}).get("entradas") or []) if str(e.get("valor", "")).strip()]


# ── I1.9 (D): importes, lenguaje llano y regiones ──

_RE_MONEDA = re.compile(r"(?<![\w.,])(\d[\d.,]*\d|\d)\s*(?:€|EUR\b|euros?\b)|(?:€|\bEUR)\s*(\d[\d.,]*\d|\d)(?![\d])", re.I)


# Revisión (I1.9): una cifra con espacio de millar («25 000», también duro o fino) es una sola cifra, no «25» y «000»
_RE_CIFRA = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ \u00a0\u202f.]\d{3})+(?:,\d{1,2})?|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
                       r"|\d+(?:[.,]\d+)?)(?![\w])")


def presupuesto_con_cifra(texto: object) -> bool:
    """VA18-1 (Revisión, pasadas 1 y 2): ¿habla de un presupuesto con una cifra? «presupuesto» (o «presupuestado»…) y, en la
    misma frase, una cifra de 1.000 o más o seguida de «mil», «millón» o «millones». Un año suelto (1900-2100, sin
    separador) no cuenta, ni una cifra pequeña («para 3 regiones»)."""
    for frase in re.split(r"[.;!?]\s", _plano(str(texto or ""))):
        if "presupuest" not in frase:
            continue
        for m in _RE_CIFRA.finditer(frase):
            cifra, cola = m.group(1), frase[m.end():m.end() + 10]
            if re.match(r"\s*(mil|millon|millones)\b", cola):
                return True
            valor = lectura_amplia(cifra)
            if valor is not None and valor >= 1000 and not re.fullmatch(r"(19|20)\d\d", cifra):
                return True
    return False


def cifras_de(texto: object) -> set:
    """Decimales de 100 o más de cada cifra del texto (con millares por punto o por espacio), con `lectura_amplia`."""
    salida = set()
    for m in _RE_CIFRA.finditer(_nfc(str(texto or ""))):
        d = lectura_amplia(m.group(1))
        if d is not None and d >= 100:
            salida.add(d.quantize(Decimal("0.01")))
    return salida


def lectura_es(cifra: str):
    """Decimal de una cifra en formato español («25.483,75», «60.000», «0,10», «2000»); None si no tiene esa lectura
    («22,548.75», «19.99»): una cifra ambigua no casa por la lectura que convenga (como la puerta)."""
    s = str(cifra or "").strip()
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?", s):
        return Decimal(s.replace(".", "").replace(",", "."))
    return None


def lectura_amplia(cifra: str):
    """Cierre D (16-10, Revisión): para DETECTAR el presupuesto del alta, la lectura española y, si la cifra no la
    tiene, la inglesa («120,000» o «120000.50»); con el espacio de millar como punto. Nunca sirve para admitir un
    importe con moneda (eso sigue con `lectura_es`, que no adivina). Igual que en pptx_revision.importes_no_permitidos."""
    s = re.sub(r"[ \u00a0\u202f]", ".", str(cifra or "").strip())
    valor = lectura_es(s)
    if valor is None and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+", s):
        valor = Decimal(s.replace(",", ""))
    return valor


def importes_monetarios(texto: str) -> list[tuple[str, object]]:
    """VA18-1 (I1.9): [(literal, Decimal o None)] de cada cifra pegada a «€», «EUR», «euro» o «euros»."""
    t = _nfc(str(texto or "")).replace("\u00a0", " ").replace("\u202f", " ")
    return [((m.group(1) or m.group(2)), lectura_es(m.group(1) or m.group(2))) for m in _RE_MONEDA.finditer(t)]


# VA18-12 (E9): nombre de cada región tal como lo publica Microsoft en español («Lista de regiones de Azure»,
# https://learn.microsoft.com/es-es/azure/reliability/regions-list, consultada el 2026-10-15; donde la página deja el
# nombre en inglés, se deja así). Lista blanca: una región que no está aquí se publica con su código.
REGIONES_LEGIBLES = {
    "swedencentral": "Centro de Suecia", "francecentral": "Centro de Francia", "francesouth": "Sur de Francia",
    "westeurope": "West Europe", "northeurope": "Norte de Europa", "germanywestcentral": "Centro-oeste de Alemania",
    "spaincentral": "Centro de España", "italynorth": "Norte de Italia", "polandcentral": "Centro de Polonia",
    "austriaeast": "Este de Austria", "belgiumcentral": "Centro de Bélgica", "denmarkeast": "Este de Dinamarca",
    "switzerlandnorth": "Norte de Suiza", "norwayeast": "Norway East", "uksouth": "UK South", "ukwest": "UK West",
    "eastus": "East US", "eastus2": "Este de EE. UU. 2", "westus": "West US", "westus2": "Oeste de EE. UU. 2",
    "westus3": "Oeste de EE. UU. 3", "centralus": "Central US", "northcentralus": "Centro-norte de EE. UU.",
    "southcentralus": "Centro-sur de EE. UU.", "westcentralus": "Centro-oeste de EE. UU.",
}


def region_legible(region: object) -> str:
    """«swedencentral» → «Centro de Suecia»; una región desconocida, tal cual."""
    codigo = re.sub(r"\s+", "", str(region or "")).lower()
    return REGIONES_LEGIBLES.get(codigo, str(region or ""))


# VA18-12 (E4, E6 y miles): arreglos de la prosa del experto con equivalencia demostrable (LES-G-047): una glosa que
# conserva el término, quitar «el factor de catálogo de» delante del valor que sigue y el separador de miles delante de
# una unidad contable. Nada más se reescribe.
_RE_TENANT = re.compile(r"(?<![\w(])(tenants?)(?!\w|\s*\()", re.I)
_RE_FACTOR_CATALOGO = re.compile(r"(?<!\w)(?:el|un)\s+factor\s+(?:de|del)\s+cat[aá]logo\s+de\s+", re.I)
_RE_MILES = re.compile(r"(?<![\d.,])(\d{4,})(?=\s+(?:consultas|documentos|usuarios|empleados|mensajes|tokens|llamadas|"
                       r"peticiones|conversaciones|preguntas|páginas|ficheros|archivos|registros|solicitudes|"
                       r"interacciones)(?!\w))", re.I)
_RE_CATALOGO_INTERNO = re.compile(r"(?<!\w)(?:(?:factor|valor|nivel|plantilla)\s+(?:de|del)\s+cat[aá]logo|cat[aá]logo\s+"
                                  r"de\s+(?:componentes|referencias|precios|servicios)|del\s+cat[aá]logo)(?!\w)", re.I)


def llano_cliente(texto: str) -> str:
    """Prosa del experto con las glosas y formatos de VA18-12; el resto, igual."""
    t = _RE_TENANT.sub(lambda m: ("inquilinos" if m.group(1).lower().endswith("s") else "inquilino") + f" ({m.group(1)})",
                       _nfc(str(texto or "")))
    t = _RE_FACTOR_CATALOGO.sub("", t)
    return _RE_MILES.sub(lambda m: numero_es(int(m.group(1))) or m.group(1), t)


def importes_permitidos(resumen: dict) -> set:
    """VA18-1 (LES-G-097.1): los únicos importes que puede llevar una frase para el cliente: el precio cerrado y cada
    hito (el consumo en la nube va en su tabla, que no es prosa)."""
    salida = set()
    for valor in [(resumen or {}).get("precio_cerrado_eur")] + [h.get("importe_eur") for h in (resumen or {}).get("hitos") or []
                                                              if isinstance(h, dict)]:
        try:
            salida.add(Decimal(str(valor)).quantize(Decimal("0.01")))
        except (InvalidOperation, ValueError):
            continue
    return salida


def nombra_existente(valor: str, comp: dict, base: str, campos: dict, oficiales: dict) -> bool:
    """¿El canal o la integración `valor` nombra el sistema que ya tiene el cliente (su nombre, el oficial o el valor de
    su entrada, en cualquier sentido de inclusión)? Un valor de menos de 4 letras no casa con nada."""
    v = _plano(_sin_punto_final(valor))
    if len(v) < 4:
        return False
    entrada = entrada_de(comp, campos) or {}
    nombres = {_plano(base), _plano(_nombre_componente(comp, oficiales)), _plano(_sin_punto_final(entrada.get("valor") or ""))}
    return any(n and len(n) >= 4 and (v in n or n in v) for n in nombres)


def presupuesto_en_textos(textos: dict, campos: dict, resumen: dict) -> list[str]:
    """VA18-1 (I1.9, LES-G-053): el presupuesto del alta en lo que se publica. [] si no está. Cuenta: una frase que lo cite
    como hecho, el rótulo «presupuesto orientativo» y cualquier cifra de 100 o más de su valor o de su cita que no sea el
    precio cerrado ni un hito."""
    permitidos = importes_permitidos(resumen)
    cifras = set()
    for campo in CAMPOS_INTERNOS:
        for e in ((campos or {}).get(campo) or {}).get("entradas") or []:
            for texto in (e.get("valor"), e.get("cita")):
                cifras |= cifras_de(texto) - permitidos
    halla = []
    frases = [(k, f) for k in ("necesidad", "alcance", "fuera_de_alcance", "supuestos", "riesgos", "condiciones")
              for f in textos.get(k) or []]
    for k, f in frases:
        if any(h == f"R-{c}" for h in f.get("hechos") or [] for c in CAMPOS_INTERNOS):
            halla.append(f"{k} {f.get('id')}: cita el presupuesto orientativo del alta (VA18-1)")
    for donde, texto in _todas(textos):
        if "presupuesto orientativo" in _plano(texto) or presupuesto_con_cifra(texto):
            halla.append(f"{donde}: nombra el presupuesto orientativo del alta o un presupuesto con cifra (VA18-1)")
        vistas = cifras_de(texto) & cifras
        halla += [f"{donde}: lleva la cifra {numero_es(d) or d} del presupuesto orientativo del alta (VA18-1)"
                  for d in sorted(vistas)]
    return halla


class _Composicion:
    """Acumula frases y exclusiones con su motivo (LES-G-094)."""

    def __init__(self, perfiles: list[str], admitidas=frozenset(), permitidos=None):
        self.perfiles = perfiles
        self.admitidas = admitidas
        self.permitidos = permitidos  # VA18-1: importes que el cliente sí puede ver (precio cerrado e hitos)
        self.excluidas: list[dict] = []

    def limpia(self, texto: str, origen: str) -> bool:
        hallazgos = barrer(texto, self.perfiles) + jerga_tecnica(texto, self.admitidas)
        if self.permitidos is not None:
            hallazgos += [f"importe «{literal}» que no es el precio cerrado ni un hito (LES-G-097.1)"
                          for literal, valor in importes_monetarios(texto) if valor not in self.permitidos]
            if presupuesto_con_cifra(texto):  # VA18-1: un presupuesto con cifra no es texto del cliente
                hallazgos.append("habla de un presupuesto con una cifra (VA18-1)")
        if hallazgos:
            self.excluidas.append({"origen": origen[:40], "texto": texto[:600],
                                   "motivo": ("no pasa el barrido de lo que ve el cliente: " + "; ".join(hallazgos))[:300]})
            return False
        return True

    def excluir(self, origen: str, texto: str, motivo: str) -> None:
        self.excluidas.append({"origen": origen[:40], "texto": (texto or "")[:600], "motivo": motivo[:300]})

    def lista(self, seccion: str, prefijo: str, candidatas: list[tuple[str, list[str], str]]) -> list[dict]:
        """candidatas = [(texto, hechos, origen)] → frases TX-<prefijo>-nn limpias y dentro del límite."""
        salida = []
        for texto, hechos, origen in candidatas:
            if not self.limpia(texto, origen):
                continue
            if len(salida) >= LIMITES.get(seccion, 10):
                self.excluir(origen, texto, f"supera el máximo de {LIMITES.get(seccion, 10)} frases de la sección")
                continue
            if not 5 <= len(texto) <= 400:
                self.excluir(origen, texto, "longitud fuera de 5-400 caracteres")
                continue
            salida.append({"id": f"TX-{prefijo}-{len(salida) + 1:02d}", "texto": texto, "hechos": hechos})
        return salida


def _nombre_componente(comp: dict, oficiales: dict) -> str:
    """Nombre oficial del catálogo (LES-G-093); el servicio solo si es una desviación sin catálogo."""
    cat = comp.get("catalogo_id")
    if cat is None:
        return str(comp.get("servicio") or "")
    if cat not in oficiales:
        raise errores.IntegridadRota(f"{comp.get('id')}: catalogo_id {cat} no está en el catálogo montado", [])
    return oficiales[cat]


nombre_oficial = _nombre_componente  # pública: la usa pptx_revision.comprobar_textos


# ── I1.9 (D, contrato común): recursos que el cliente ya tiene ──
_RE_ARTICULO_INICIAL = re.compile(r"^(?:el|la|los|las|un|una|unos|unas|su|sus|mi|mis|nuestro|nuestra|nuestros|nuestras)\s+",
                                  re.I)


def entradas_existentes(campos: dict) -> dict[str, dict]:
    """{"EX-nn": entrada} de requisitos.ya_contratado_por_cliente (las entradas sin id, de antes de I1.9, no cuentan)."""
    dato = (campos or {}).get("ya_contratado_por_cliente") or {}
    return {str(e["id"]): e for e in dato.get("entradas") or []
            if isinstance(e, dict) and re.fullmatch(r"EX-[0-9]{2}", str(e.get("id") or ""))}


def entrada_de(comp: dict, campos: dict) -> dict | None:
    """Entrada de lo que el cliente ya tiene a la que corresponde el componente; None si no es un recurso existente.
    IntegridadRota si `existente_del_cliente` no es null y no cita una entrada que exista (no se adivina)."""
    existente = comp.get("existente_del_cliente") if isinstance(comp, dict) else None
    if existente is None:
        return None
    clave = existente.get("entrada") if isinstance(existente, dict) else None
    entrada = entradas_existentes(campos).get(str(clave or ""))
    if entrada is None:
        raise errores.IntegridadRota(f"{comp.get('id')}: existente_del_cliente cita la entrada {clave!r}, que no está en "
                                     "requisitos.ya_contratado_por_cliente", [])
    return entrada


def nombre_base_existente(comp: dict, entrada: dict, oficiales: dict) -> str:
    """Cómo se llama el sistema del cliente: el nombre oficial si el valor citado lo nombra (o al revés: «API Management»
    y «Azure API Management»); si no, el valor citado sin el artículo inicial («API REST de RR. HH.») cuando es corto y
    pasa los barridos; si no, el nombre oficial. Siempre es el oficial o un trozo literal del valor citado."""
    oficial = _nombre_componente(comp, oficiales)
    valor = _sin_punto_final(_RE_ARTICULO_INICIAL.sub("", re.sub(r"\s+", " ", _nfc(str(entrada.get("valor") or ""))).strip()))
    valor = valor[:1].upper() + valor[1:]
    pv, po = _plano(valor), _plano(oficial)
    valido = 3 <= len(valor) <= MAX_NOMBRE_EXISTENTE and not barrer(valor, []) \
        and not jerga_tecnica(valor, palabras_admitidas(oficial))
    # cierre D (I1.9): fuera del catálogo, «oficial» es el `servicio` que escribió el modelo, sin fuente (LES-G-093): manda
    # el valor citado, aunque el servicio lo contenga («API REST de RR. HH. del cliente» frente a «API REST de RR. HH.»)
    if comp.get("catalogo_id") is None and valido:
        return valor
    if po and pv and (pv in po or po in pv):
        return oficial
    if valido:
        return valor
    return oficial or "Sistema"


def nombre_en_frase(entrada: dict, base: str) -> str:
    """Cierre D (I1.9): el nombre del sistema del cliente dentro de una frase («Integración con la API REST de RR. HH.»).
    Si el nombre es el valor citado y este empezaba por «el», «la», «los» o «las», recupera ese artículo y la minúscula
    inicial del valor; si no (nombre oficial, otro determinante o sin artículo), el nombre tal cual."""
    crudo = _sin_punto_final(re.sub(r"\s+", " ", _nfc(str((entrada or {}).get("valor") or ""))).strip())
    m = re.match(r"(el|la|los|las)\s+(.+)$", crudo, re.I)
    if m and base == m.group(2)[:1].upper() + m.group(2)[1:]:
        return f"{m.group(1).lower()} {m.group(2)}"
    return base


SUITES_LICENCIAS = ("az-microsoft-365",)  # VA19-1: la suite de cuyas licencias salen los demás servicios de licencia


def de_licencia(comp: dict, filas: dict) -> bool:
    """VA19-1 (I1.10): servicio que el cliente usa con sus licencias (Microsoft 365, Teams, SharePoint, Entra ID): su fila
    del catálogo no tiene precio en Azure (service_name_precios null) y su residencia es la geografía del inquilino."""
    fila = filas.get(comp.get("catalogo_id")) if isinstance(comp, dict) else None
    return isinstance(fila, dict) and fila.get("service_name_precios") is None and fila.get("residencia") == "geografia_tenant"


def _nombre_suite(entrada: dict, base: str) -> str:
    """El nombre de la suite de licencias: el valor citado si contiene el nombre del sistema y es más preciso («Microsoft
    365 E3» frente a «Microsoft 365») y pasa los barridos; si no, el nombre del sistema."""
    crudo = re.sub(r"\s+", " ", _nfc(str((entrada or {}).get("valor") or ""))).strip()
    valor = _sin_punto_final(_RE_ARTICULO_INICIAL.sub("", crudo))
    if _plano(base) and _plano(base) in _plano(valor) and len(valor) <= MAX_NOMBRE_EXISTENTE and not barrer(valor, []) \
            and not jerga_tecnica(valor, palabras_admitidas(base)):
        return valor
    return base


def frases_existentes(existentes: list, campos: dict, filas: dict, en_frase: dict) -> list[tuple[str, list[str], str]]:
    """VA19-1 (I1.10): las frases de «Incluido» sobre los sistemas que ya tiene el cliente, una por cita (los recursos que
    salen de la misma frase del cliente son un mismo sistema), nunca una por recurso:
    - los servicios de licencia se dicen como uso: «Uso de Microsoft Teams y SharePoint Online, incluidos en las licencias
      de Microsoft 365 E3 del cliente.» (sin la suite: «…, que ya tiene el cliente.»; solo la suite: «Uso de las licencias
      de … que ya tiene el cliente.»);
    - el resto, como una sola integración con el sistema propio del cliente (fuera del catálogo) y, entre paréntesis, los
      recursos de Azure que lo acompañan: «Integración con la API REST de RR. HH. que ya tiene el cliente (y sus sistemas
      App Service propio y Azure API Management).»; sin sistema propio, «Integración con A y B, que ya tiene el cliente.»
    Hechos: R-ya_contratado_por_cliente y los componentes del grupo (8 como máximo, por el esquema)."""
    grupos: dict[str, list] = {}
    for c, _base in existentes:
        clave = _plano(str((entrada_de(c, campos) or {}).get("cita") or "")) or str(c.get("id"))
        grupos.setdefault(clave, []).append(c)
    salida = []
    for comps in grupos.values():
        ids = [str(c.get("id")) for c in comps]
        hechos = (["R-ya_contratado_por_cliente"] + ids)[:8]
        suites = [c for c in comps if c.get("catalogo_id") in SUITES_LICENCIAS]
        licencias = [c for c in comps if c not in suites and de_licencia(c, filas)]
        propios = [c for c in comps if c not in suites and c not in licencias and c.get("catalogo_id") is None]
        recursos = [c for c in comps if c not in suites and c not in licencias and c not in propios]
        origen = "existente " + ", ".join(ids)
        suite = _lista_y([_nombre_suite(entrada_de(c, campos), en_frase[c["id"]]) for c in suites]) if suites else ""
        if licencias:
            usos = _lista_y([en_frase[c["id"]] for c in licencias])
            salida.append((f"Uso de {usos}, incluidos en las licencias de {suite} del cliente." if suite
                           else f"Uso de {usos}, que ya tiene el cliente.", hechos, origen))
        elif suite:
            salida.append((f"Uso de las licencias de {suite} que ya tiene el cliente.", hechos, origen))
        if propios:
            texto = f"Integración con {_lista_y([en_frase[c['id']] for c in propios])} que ya tiene el cliente"
            if recursos:
                texto += f" (y sus sistemas {_lista_y([en_frase[c['id']] for c in recursos])})"
            salida.append((texto + ".", hechos, origen))
        elif recursos:
            salida.append((f"Integración con {_lista_y([en_frase[c['id']] for c in recursos])}, que ya tiene el cliente.",
                           hechos, origen))
    return salida


def nombre_en_diagrama(comp: dict, campos: dict, oficiales: dict) -> str:
    """Nombre del componente para el cliente: el oficial (LES-G-093) o, si es un recurso que ya tiene el cliente,
    «<nombre> (sistema del cliente)» (I1.9, PR18-8)."""
    entrada = entrada_de(comp, campos)
    if entrada is None:
        return _nombre_componente(comp, oficiales)
    return nombre_base_existente(comp, entrada, oficiales) + SUFIJO_EXISTENTE


CAPA_IDENTIDAD = "identidad_seguridad_red"


def flujos_cliente(resp: dict) -> list[dict]:
    """VA18-6 (I1.9): convención fija para la identidad: toda flecha con un componente de «Identidad, seguridad y red»
    va del servicio a ese componente («servicio → Microsoft Entra ID»), y dos flujos que quedan iguales se dibujan una
    vez. Los demás flujos, como los escribió el experto y en su orden."""
    capa = {c.get("id"): c.get("capa") for c in resp.get("componentes") or [] if isinstance(c, dict)}
    salida, vistos = [], set()
    for f in resp.get("flujos") or []:
        o, d = f["origen"], f["destino"]
        if capa.get(o) == CAPA_IDENTIDAD and capa.get(d) != CAPA_IDENTIDAD:
            o, d = d, o
        if (o, d) not in vistos:
            vistos.add((o, d))
            salida.append({"origen": o, "destino": d})
    return salida


def _arquitectura(resp: dict, oficiales: dict, comp_: _Composicion, campos: dict | None = None) -> dict:
    capas, campos = [], campos or {}
    for capa, titulo in CAPAS:
        comps = [{"id": c["id"], "nombre": nombre_en_diagrama(c, campos, oficiales)}
                 for c in resp.get("componentes") or [] if c.get("capa") == capa]
        if comps:
            capas.append({"capa": capa, "titulo": titulo, "componentes": comps})
    # el pie de referencias nombra el servicio (la página de Learn es la del servicio, no la del sistema del cliente)
    refs = [{**c, "componentes": [{**k, "nombre": _nombre_componente(
        next(x for x in resp.get("componentes") or [] if x.get("id") == k["id"]), oficiales)} for k in c["componentes"]]}
        for c in capas]
    return {"capas": capas, "flujos": flujos_cliente(resp), "referencias": _referencias(resp, refs, comp_)}


def url_publicable(url: object) -> bool:
    """Una URL que se puede imprimir en una línea del pie: https, sin espacios ni caracteres de control dentro (segunda
    pasada de la revisión independiente, I1.7: un salto de línea en la URL descuadraría el pie y `referencias_faltan`)."""
    u = str(url or "").strip()
    return u.startswith("https://") and not any(c.isspace() or unicodedata.category(c).startswith("C") for c in u)


def clave_url(url: object) -> str:
    """Clave con la que se deduplican las referencias del pie y con la que la puerta las busca: la URL tal cual, sin
    espacios alrededor ni barra final (REVERIF16-3). Dos páginas distintas nunca comparten clave."""
    return str(url or "").strip().rstrip("/")


def sin_pagina_propia(comp: object) -> bool:
    """I1.9 (cierre D, contrato v5 de P): un recurso que el cliente ya tiene y que no está en el catálogo no tiene página
    de Learn (`referencia_id` null, que la completada v5 admite solo para él). Exige las tres cosas: con cualquiera
    distinta, el componente necesita su página en el pie como siempre (falla cerrado)."""
    return (isinstance(comp, dict) and isinstance(comp.get("existente_del_cliente"), dict)
            and comp.get("catalogo_id") is None and comp.get("referencia_id") is None)


def _referencias(resp: dict, capas: list[dict], comp_: _Composicion) -> list[dict]:
    """REVERIF16-3 (I1.7): el pie de la diapositiva 4 lleva la página propia de CADA componente, deduplicada por URL y
    no por tema (con el tema, SharePoint salía con la página de Microsoft 365). El título nombra a los componentes que
    respaldan esa página («… sobre SharePoint Online»), en el orden del diagrama. Detrás, las referencias que no son de
    ningún componente (la arquitectura de referencia), una por tema que no cubra ya otra; las demás van a la nota con su
    motivo (LES-G-094). Un componente sin referencia existente es un fallo: el pie no puede quedarse sin su página."""
    refs = {r.get("id"): r for r in resp.get("referencias") or [] if isinstance(r, dict)}
    salida, por_clave, temas = [], {}, set()
    for capa in capas:  # el orden del diagrama: capas y, dentro, el de la respuesta
        for comp in capa["componentes"]:
            origen = next((c for c in resp.get("componentes") or [] if c.get("id") == comp["id"]), {})
            if sin_pagina_propia(origen):  # I1.9 (cierre D): sistema del cliente fuera del catálogo, sin página de Learn
                continue
            ref = refs.get(origen.get("referencia_id"))
            if ref is None or not url_publicable(ref.get("url")):
                raise errores.IntegridadRota(f"{comp['id']}: referencia_id {origen.get('referencia_id')} no existe o su URL "
                                             "no se puede imprimir: el pie de la diapositiva 4 se quedaría sin su página "
                                             "(REVERIF16-3)", [])
            clave = clave_url(ref["url"])
            if clave not in por_clave:
                por_clave[clave] = {"id": ref["id"], "url": ref["url"], "nombres": []}
                salida.append(por_clave[clave])
            por_clave[clave]["nombres"].append(comp["nombre"])
            temas.add(titulo_referencia(str(ref["url"])))
    publicadas = []
    for r in salida:
        titulo = REFERENCIA.format(tema=_lista_y(r["nombres"]))
        if len(titulo) > MAX_TITULO_REFERENCIA:  # muchos componentes con la misma página: el tema de la URL o un resumen
            nombres = list(dict.fromkeys(r["nombres"]))
            titulo = titulo_referencia(str(r["url"])) or REFERENCIA.format(
                tema=f"{nombres[0][:60]} y otros {len(nombres) - 1} componentes")
        # el nombre de un componente no pasa por `jerga_tecnica` (como en el diagrama), pero sí por el barrido de §9.3
        hallazgos = barrer(titulo, comp_.perfiles)
        if hallazgos:
            raise errores.ReglaIncumplida(f"referencia {r['id']}: el título «{titulo[:80]}» no pasa el barrido y el "
                                          "componente se quedaría sin su página (REVERIF16-3)", hallazgos)
        publicadas.append({"id": r["id"], "titulo": titulo, "url": r["url"]})
    # PR17-7 (arreglos I1.7): la arquitectura de referencia ELEGIDA (valoracion_nucleo.arquitectura) va antes que las
    # demás páginas sin componente: con «una por tema», la guía de RAG ocupaba el tema y la elegida se quedaba fuera.
    elegida = ((resp.get("valoracion_nucleo") or {}).get("arquitectura") or {}).get("referencia_id")
    sueltas = [r for r in resp.get("referencias") or [] if isinstance(r, dict)]
    sueltas.sort(key=lambda r: elegida is None or r.get("id") != elegida)
    for r in sueltas:
        if clave_url(r.get("url")) in por_clave:
            continue  # la misma página ya figura con el nombre de su componente
        # REV13-3: el título de Learn viene en inglés; el que se publica lo compone el código en castellano desde el tema
        # de la URL (TEMAS_REFERENCIA). Como texto de la exclusión va la URL con el id, nunca la URL sola: una URL que
        # fuera el comienzo de otra publicada haría creer a la puerta que la exclusión se publicó.
        compuesto, aparte = titulo_referencia(str(r.get("url") or "")), f"{r.get('url')} (referencia {r.get('id')})"
        if compuesto is None or not url_publicable(r.get("url")):
            comp_.excluir(f"referencia {r.get('id')}", aparte,
                          "la dirección no corresponde a ningún tema de la lista de documentación de Microsoft o no se "
                          "puede imprimir en una línea")
        elif compuesto in temas:
            comp_.excluir(f"referencia {r.get('id')}", aparte, "el pie ya lleva una página de Microsoft sobre ese tema "
                          "(una por tema para las que no son de ningún componente; REVERIF16-3)")
        elif comp_.limpia(compuesto, f"referencia {r.get('id')}"):
            temas.add(compuesto)
            por_clave[clave_url(r["url"])] = r
            publicadas.append({"id": r["id"], "titulo": compuesto, "url": r["url"]})
    return publicadas


def _discrepados(carga: dict) -> set[str]:
    ver = ((carga.get("verificacion") or {}).get("respuesta") or {})
    return {e.get("id") for e in ver.get("elementos") or [] if e.get("veredicto") == "DISCREPA"}


def _hechos_validos(carga: dict, resp: dict) -> set[str]:
    validos = {f"R-{k}" for k in ((carga.get("requisitos") or {}).get("campos") or {})}
    for clave in ("referencias", "componentes", "precios", "supuestos", "riesgos"):
        validos |= {x.get("id") for x in resp.get(clave) or []}
    return validos


def _componentes_citados(x: dict, resp: dict) -> set[str]:
    """Ids de componente que cita una frase del experto: directos (C-nn) o a través de un precio (P-nn)."""
    hechos = set(x.get("hechos") or [])
    comps = {c.get("id") for c in resp.get("componentes") or [] if c.get("id") in hechos}
    return comps | {p.get("componente_id") for p in resp.get("precios") or [] if p.get("id") in hechos}


def _regiones_citadas(x: dict, resp: dict) -> list[str]:
    """Regiones de lo que cita la frase; si no cita ningún componente con región, las de los componentes
    cuyo SKU nombra un tipo de despliegue que aparece en la frase."""
    citados = _componentes_citados(x, resp)
    regiones = [c.get("region") for c in resp.get("componentes") or [] if c.get("id") in citados and c.get("region")]
    if regiones:
        return regiones
    texto = str(x.get("texto", ""))
    tipos = [rx for rx, _ in _SKU_LLANO if rx.search(texto)]
    return [c.get("region") for c in resp.get("componentes") or []
            if c.get("region") and any(rx.search(str(c.get("sku", ""))) for rx in tipos)]


# VERIF-8: un riesgo del experto que dice que el precio de un componente no se ha obtenido o comprobado
# repite el riesgo de consumo que compone el código para ese mismo componente.
_RE_PRECIO = re.compile(r"(?<!\w)(precios?|costes?|consumo|importes?)(?!\w)", re.I)
_RE_SIN_CONTRASTE = re.compile(
    r"(?<!\w)(no\s+se\s+(?:ha\s+|han\s+)?(?:podido\s+)?(?:verific|obten|obtuv|comprob|confirm|valor|contrast)\w*"
    r"|sin\s+(?:verificar|confirmar|comprobar|contrastar|valorar|precio)"
    r"|no\s+(?:est[aá]n?|queda[n]?)\s+(?:verificad|valorad|cerrad|confirmad|comprobad)\w*)", re.I)


def _repite_consumo(x: dict, resp: dict, declarados: dict[str, set]) -> bool:
    """True si el riesgo habla del precio sin contrastar de un componente que el código ya declara
    (`declarados`: id de componente → nombres con los que se le puede citar)."""
    texto = _nfc(str(x.get("texto", "")))
    if not (_RE_PRECIO.search(texto) and _RE_SIN_CONTRASTE.search(_sin_tildes(texto))):
        return False
    if _componentes_citados(x, resp) & set(declarados):
        return True
    pl = _plano(texto)
    return any(n and re.search(r"(?<!\w)" + re.escape(_plano(n)) + r"(?!\w)", pl)
               for nombres in declarados.values() for n in nombres)


def _prosa(resp: dict, clave: str, carga: dict, comp_: _Composicion, por_forma: list | None = None) -> list[dict]:
    """Supuestos o riesgos del experto admisibles: hechos existentes y sin DISCREPA (§9.4). VA18-5 (I1.9): lo que se
    retira solo por su forma (redacción interna) se añade a `por_forma`, para sustituirlo por una frase fija."""
    validos, discrepa, salida = _hechos_validos(carga, resp), _discrepados(carga), []
    semanas = ((carga.get("estimacion") or {}).get("resumen") or {}).get("duracion_semanas")
    for x in resp.get(clave) or []:
        # VERIF-8: los tipos de despliegue se traducen con la región de lo que cita la frase; VA18-12: glosas
        texto = traducir_skus(llano_cliente(_nfc(str(x.get("texto", ""))).strip()), _regiones_citadas(x, resp))
        texto, motivo_plazo = plazo_del_gantt(texto, semanas)
        x = {**x, "texto": texto}
        hechos = list(x.get("hechos") or [])
        malos = [h for h in hechos if h not in validos]
        if not hechos or malos:
            comp_.excluir(f"experto {x.get('id')}", texto, f"cita hechos inexistentes o ninguno: {malos}")
        elif any(h == f"R-{c}" for h in hechos for c in CAMPOS_INTERNOS):  # VA18-1 (LES-G-053)
            comp_.excluir(f"experto {x.get('id')}", texto, "cita el presupuesto orientativo del alta, que es un dato "
                          "comercial interno y no se enseña al cliente (VA18-1)")
        elif x.get("id") in discrepa:
            comp_.excluir(f"experto {x.get('id')}", texto, "el verificador la marcó DISCREPA")
        elif motivo_plazo:
            comp_.excluir(f"experto {x.get('id')}", texto, motivo_plazo)
        elif redaccion_interna(texto):
            comp_.excluir(f"experto {x.get('id')}", texto,
                          "redacción interna (" + "; ".join(redaccion_interna(texto)) + "): lo no comprobado "
                          "lo declara el código en la diapositiva 8 y en los riesgos de consumo")
            if por_forma is not None:
                por_forma.append(x)
        else:
            salida.append(x)
    return salida


# ── I1.7 (D): factores de consumo y ciclo de vida del modelo, compuestos por el código (decisión 2, LES-G-100.5) ──

def numero_es(valor: object) -> str | None:
    """2000 → «2.000»; 0.5 → «0,5»; None si no es un número finito mayor que cero (LES-G-099: ni NaN ni infinito)."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str, Decimal)):
        return None
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        return None
    if not d.is_finite() or d <= 0:
        return None
    entero, _, dec = f"{d.normalize():f}".partition(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    return ".".join([entero, *grupos]) + (f",{dec}" if dec else "")


# De dónde sale cada factor y cómo se le dice al cliente (una etiqueta por factor y otra para todos a la vez)
ORIGEN_FACTOR = {"catalogo": ("valor de referencia", "valores de referencia; el consumo real dependerá del uso"),
                 "requisito": ("según los requisitos del cliente", "según los requisitos del cliente"),
                 "propuesta": ("estimación de la propuesta", "estimación de la propuesta; el consumo real dependerá del uso")}


def factor_aplicado(precio: dict) -> tuple[dict | None, str | None]:
    """(factor que aplicó el núcleo, origen: «catalogo», «requisito» o «propuesta»). Contrato v4 (CAMBIOS-I17-D §3): el
    núcleo deja en el precio `factor` {valor, unidad, …} (el estándar del catálogo o el cambiado) y `factor_override`
    (el que escribió el modelo citando un requisito, objeto o null). Una respuesta v3 lo trae en `base_volumen.factor`:
    lo eligió el modelo sin estándar ni cita, así que es una «estimación de la propuesta», nunca «del cliente»."""
    base = precio.get("base_volumen") if isinstance(precio.get("base_volumen"), dict) else None
    if base is None:
        return None, None
    if isinstance(precio.get("factor"), dict):
        return precio["factor"], "requisito" if isinstance(precio.get("factor_override"), dict) else "catalogo"
    return (base.get("factor"), "propuesta") if isinstance(base.get("factor"), dict) else (None, None)


# Una cantidad (en cifra o en letra) y, a tres palabras como mucho, «tokens» o «mensajes»: es dar un factor. «La
# estimación de tokens por consulta es una aproximación» no da ninguno y se queda (es un riesgo, no un factor).
_RE_CANTIDAD_FACTOR = re.compile(r"(?<!\w)(?:\d[\d.,]*|" + "|".join(sorted(_NUMEROS, key=len, reverse=True)) +
                                 r")(?:\s+[^\s\d]+){0,3}?\s+(?:tokens?|mensajes?)(?!\w)", re.I)
_RE_TOKENS_CIFRA = re.compile(r"\d[\d.,]*[\s-]+tokens?(?!\w)", re.I)  # Revisión: también «4.000-token»
# segunda pasada de la revisión independiente: «5 tokens de autenticación por sesión» no es un factor de consumo; lo es por consulta, por
# respuesta o de entrada o salida
_RE_UNIDAD_FACTOR = re.compile(r"(?<!\w)(por\s+(consulta|petici[oó]n|respuesta|pregunta|mensaje|conversaci[oó]n)|de\s+entrada"
                               r"|de\s+salida)(?!\w)", re.I)


# D18-1 (I1.8): «1 consultas de ranking semántico por consulta» salía así al cliente (LES-G-037). Con la cantidad 1, las
# palabras plurales conocidas de la unidad pasan a singular hasta la primera preposición; una que no está en la lista se
# queda como está (nunca se inventa una forma).
_SINGULAR = {"consultas": "consulta", "mensajes": "mensaje", "tokens": "token", "documentos": "documento",
             "peticiones": "petición", "páginas": "página", "conversaciones": "conversación",
             "preguntas": "pregunta", "respuestas": "respuesta", "usuarios": "usuario", "imágenes": "imagen",
             "minutos": "minuto", "almacenados": "almacenado", "escritos": "escrito", "procesados": "procesado",
             "llamadas": "llamada", "ejecuciones": "ejecución", "operaciones": "operación"}
_PREPOSICIONES = frozenset({"de", "del", "por", "al", "a", "en", "con", "para"})


def concordar(cantidad: str, unidad: str) -> str:
    """La unidad en singular si la cantidad (ya en formato español) es «1»: «consultas de ranking semántico por
    consulta» → «consulta de ranking semántico por consulta»; «GB almacenados por documento» → «GB almacenado por
    documento». Solo hasta la primera preposición y solo palabras de _SINGULAR; con otra cantidad, la unidad tal cual."""
    if cantidad != "1":
        return unidad
    palabras = unidad.split(" ")
    for i, w in enumerate(palabras):
        if w.lower() in _PREPOSICIONES:
            break
        singular = _SINGULAR.get(w.lower())
        if singular:
            palabras[i] = singular[0].upper() + singular[1:] if w[:1].isupper() else singular
    return " ".join(palabras)


def supuestos_consumo(resp: dict, oficiales: dict) -> tuple[list[tuple], set[str], list[tuple[str, str]]]:
    """([(texto, hechos, origen, nivel)], ids de componente cubiertos, [(origen, motivo)] de lo que no se pudo componer).

    Una frase por componente y base citada: «El consumo orientativo de Microsoft Foundry se calcula con 2.000 consultas
    al mes, 4.000 tokens de entrada por consulta y 500 tokens de salida por consulta (valores de referencia; …)». Si el
    experto cambió un factor citando un requisito, lo dice («según los requisitos del cliente»); a quién y por qué lo
    cambió va a la nota del revisor, no al cliente."""
    comps = {c.get("id"): c for c in resp.get("componentes") or [] if isinstance(c, dict)}
    grupos: dict[tuple, list] = {}
    fallidos: list[tuple[str, str]] = []
    for p in resp.get("precios") or []:
        factor, origen = factor_aplicado(p) if isinstance(p, dict) else (None, None)
        if factor is None:
            if isinstance(p, dict) and isinstance(p.get("base_volumen"), dict):
                fallidos.append((f"precio {p.get('id')}", "precio por volumen sin factor legible"))
            continue
        base = p["base_volumen"]
        n_base, n_valor = numero_es(base.get("cantidad_base")), numero_es(factor.get("valor"))
        unidad_b, unidad_f = (re.sub(r"\s+", " ", str(x or "")).strip() for x in (base.get("unidad_base"), factor.get("unidad")))
        if not (n_base and n_valor and unidad_b and unidad_f):
            fallidos.append((f"precio {p.get('id')}", "base o factor sin número finito positivo o sin unidad"))
            continue
        clave = (p.get("componente_id"), str(base.get("cita")), n_base, unidad_b)
        grupos.setdefault(clave, []).append((p.get("id"), f"{n_valor} {concordar(n_valor, unidad_f)}", origen))
    salida, cubiertos = [], set()
    for (cid, _, n_base, unidad_b), factores in grupos.items():
        comp = comps.get(cid) or {}
        servicio = oficiales.get(comp.get("catalogo_id")) or str(comp.get("servicio") or "")
        if not servicio:
            fallidos.append((f"componente {cid}", "precio por volumen de un componente que no existe"))
            continue
        vistos = list(dict.fromkeys((f, c) for _, f, c in factores))
        todos = {c for _, c in vistos}
        if len(todos) == 1:
            partes, cola = [f for f, _ in vistos], f" ({ORIGEN_FACTOR[next(iter(todos))][1]})"
        else:
            partes, cola = [f"{f} ({ORIGEN_FACTOR[c][0]})" for f, c in vistos], ""
        texto = _frase_final(f"El consumo orientativo de {servicio} se calcula con "
                             f"{_lista_y([f'{n_base} {concordar(n_base, unidad_b)}', *partes])}"
                             + cola)
        salida.append((texto, [i for i, _, _ in factores][:8], f"consumo {cid}",
                       "Confianza alta" if todos == {"requisito"} else "Confianza media"))
        cubiertos.add(cid)
    return salida, cubiertos, fallidos


def repite_factor(x: dict, resp: dict, cubiertos: set[str]) -> bool:
    """True si una frase del experto vuelve a dar los factores de consumo que ya declara el código (y podría contradecir
    los que aplicó el núcleo, LES-G-095): da una cifra de tokens, o cita un componente cubierto (o un precio suyo) y da
    una cantidad de tokens o de mensajes («un mensaje del canal por consulta»)."""
    texto = _nfc(str(x.get("texto", "")))
    if not cubiertos or not _RE_UNIDAD_FACTOR.search(texto):  # sin «por consulta», «de entrada»…, no es un factor
        return False
    if _RE_TOKENS_CIFRA.search(texto):
        return True
    return bool(_componentes_citados(x, resp) & cubiertos) and bool(_RE_CANTIDAD_FACTOR.search(texto))


_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre")
_RE_FECHA = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_RE_MODELO_PLANTILLA = re.compile(r"(.+?)-(?:entrada|salida)(?:-[a-z0-9-]+)?")


def _fecha(valor: object):
    """date de «AAAA-MM-DD» (lo que sigue, p. ej. la hora de un ISO, se ignora); None si no es una fecha válida."""
    import datetime
    m = _RE_FECHA.match(str(valor or ""))
    try:
        return datetime.date(*map(int, m.groups())) if m else None
    except ValueError:
        return None


def fecha_es(fecha) -> str:
    """date(2028, 1, 11) → «11 de enero de 2028»."""
    return f"{fecha.day} de {_MESES[fecha.month - 1]} de {fecha.year}"


def ciclo_vida_modelos(resp: dict, catalogo: dict) -> list[dict]:
    """[{"modelo", "retirada" (date o None), "precios": [ids]}] de los modelos que valora la respuesta, según el
    `ciclo_vida` de la plantilla de cada precio en el catálogo (I1.7, contrato común c). La plantilla se busca por
    `plantilla_id` (v4) o por el filtro exacto (v3) entre las de la fila del componente; el nombre es `modelo` de la
    plantilla o de su ciclo de vida y, si no lo trae, el id sin «-entrada»/«-salida». IntegridadRota si la retirada no
    es null ni una fecha: no se publica un ciclo de vida que no se sabe leer."""
    filas = {c.get("id"): c for c in (catalogo or {}).get("componentes") or [] if isinstance(c, dict)}
    comps = {c.get("id"): c for c in resp.get("componentes") or [] if isinstance(c, dict)}
    modelos: dict[str, dict] = {}
    # revisión independiente (I1.7): con un catálogo que ya declara ciclos de vida (contrato común c), un precio de tokens de
    # modelo sin el suyo es un hueco y falla en alto; con uno anterior (ninguno declarado) no hay nada que publicar
    con_ciclos = any(isinstance(x, dict) and isinstance(x.get("ciclo_vida"), dict)
                     for f in filas.values() for x in f.get("plantillas_precio") or [])
    for p in resp.get("precios") or []:
        fila = filas.get((comps.get(p.get("componente_id")) or {}).get("catalogo_id")) if isinstance(p, dict) else None
        pl = next((x for x in (fila or {}).get("plantillas_precio") or [] if isinstance(x, dict) and (
            x.get("id") == p.get("plantilla_id") if p.get("plantilla_id") else x.get("filtro") == p.get("filtro"))), None)
        ciclo = (pl or {}).get("ciclo_vida")
        if not isinstance(ciclo, dict):
            medidor = _plano(re.sub(r"[;,()]", " ", str((p or {}).get("concepto") or "")))
            if con_ciclos and any(rx.search(medidor) for rx, _ in _MEDIDOR_TOKENS):
                raise errores.IntegridadRota(f"{p.get('id')}: precio de tokens de un modelo sin ciclo de vida en el "
                                             "catálogo: no se puede decir al cliente cuándo se retira", [])
            continue
        m = _RE_MODELO_PLANTILLA.fullmatch(str(pl.get("id") or ""))
        nombre = str(pl.get("modelo") or ciclo.get("modelo") or (m.group(1) if m else "")).strip()
        retirada = _fecha(ciclo.get("retirada")) if ciclo.get("retirada") is not None else None
        if not nombre or (ciclo.get("retirada") is not None and retirada is None):
            raise errores.IntegridadRota(f"plantilla {pl.get('id')}: ciclo de vida sin modelo o con una retirada que no "
                                         f"es una fecha ({ciclo.get('retirada')!r})", [])
        entrada = modelos.setdefault(nombre, {"modelo": nombre, "retirada": retirada, "precios": []})
        if entrada["retirada"] != retirada:
            raise errores.IntegridadRota(f"el modelo {nombre} tiene dos fechas de retirada en el catálogo", [])
        entrada["precios"].append(p.get("id"))
    return list(modelos.values())


def riesgos_modelo(resp: dict, catalogo: dict, fecha_oferta: object, semanas: object) -> list[tuple[str, list[str], str]]:
    """Riesgo para el cliente con el ciclo de vida de cada modelo valorado. Con retirada publicada, la regla del PM
    (13-10-2026) exige que caiga después de la fecha de la oferta + la duración del Gantt + 12 meses: si no, falla en alto
    (ReglaIncumplida), aunque el experto ya debía haberlo rechazado; sin retirada publicada, se dice que no consta."""
    salida = []
    for m in ciclo_vida_modelos(resp, catalogo):
        if m["retirada"] is None:
            texto = (f"Microsoft no ha publicado todavía la fecha de retirada del modelo {m['modelo']}; cuando la publique, "
                     "habrá que planificar el paso a un modelo vigente antes de esa fecha.")
        else:
            import datetime
            inicio = _fecha(fecha_oferta)
            if inicio is None or isinstance(semanas, bool) or not isinstance(semanas, int) or semanas < 1:
                raise errores.ReglaIncumplida(f"no se puede comprobar el ciclo de vida del modelo {m['modelo']}: falta la "
                                              "fecha de la oferta o la duración del Gantt", [])
            fin = inicio + datetime.timedelta(weeks=semanas)
            horizonte = fin.replace(year=fin.year + 1) if (fin.month, fin.day) != (2, 29) else fin + datetime.timedelta(days=365)
            if m["retirada"] < horizonte:
                raise errores.ReglaIncumplida(f"el modelo {m['modelo']} se retira el {m['retirada']}, antes del "
                                              f"{horizonte} (fecha de la oferta + Gantt + 12 meses): no se puede proponer", [])
            texto = (f"Microsoft tiene prevista la retirada del modelo {m['modelo']} el {fecha_es(m['retirada'])}, al "
                     "menos un año después de la puesta en marcha; antes de esa fecha habrá que pasar a un modelo vigente.")
        salida.append((texto, list(dict.fromkeys(m["precios"]))[:7], f"ciclo de vida {m['modelo']}"[:40]))
    return salida


_RANGO = {"Confianza baja": 0, "Confianza media": 1, "Confianza alta": 2}
SUSTITUTO = "Supuesto sin confirmar sobre {lista}: se revisará con el cliente al inicio del proyecto."
SUSTITUTO_SIN_NOMBRE = "Supuesto técnico sin confirmar: se revisará con el cliente al inicio del proyecto."


def hechos_nombrables(hechos, resp: dict) -> set[str]:
    """Componentes (C-nn, también a través de un precio P-nn) y requisitos (R-campo) que cita una frase."""
    precios = {p.get("id"): p.get("componente_id") for p in resp.get("precios") or [] if isinstance(p, dict)}
    salida = set()
    for h in hechos or []:
        h = str(h)
        if re.fullmatch(r"C-[0-9]{2}|R-[a-z_]+", h):
            salida.add(h)
        elif h in precios and precios[h]:
            salida.add(str(precios[h]))
    return salida


def nivel_con_tope(s: dict, resp: dict, campos: dict) -> str:
    """VA18-5 (I1.9): el nivel de un supuesto del experto nunca supera el de otro supuesto (o dato ASUMIDO) que la nota
    da con menos confianza sobre los mismos hechos: si todos los componentes y requisitos que cita están entre los de
    ese otro, se queda con su nivel. Sin hechos nombrables, su propio nivel."""
    nivel = NIVEL.get(str(s.get("confianza", "")).upper(), "Confianza baja")
    propios = hechos_nombrables(s.get("hechos"), resp)
    if not propios:
        return nivel
    fuentes = [(NIVEL.get(str(t.get("confianza", "")).upper(), "Confianza baja"), hechos_nombrables(t.get("hechos"), resp))
               for t in resp.get("supuestos") or [] if isinstance(t, dict) and t.get("id") != s.get("id")]
    fuentes += [("Confianza baja", {f"R-{c}"}) for c, d in campos.items()
                if any(e.get("origen") == "ASUMIDO" for e in (d or {}).get("entradas") or [])]
    for otro, suyos in fuentes:
        if propios <= suyos and _RANGO[otro] < _RANGO[nivel]:
            nivel = otro
    return nivel


def frase_sustituta(s: dict, resp: dict, nombres: dict[str, str]) -> str:
    """VA18-5 (I1.9): frase fija con los mismos hechos que un supuesto retirado por su forma (nunca su texto)."""
    lista = []
    for h in sorted(hechos_nombrables(s.get("hechos"), resp), key=lambda x: (not x.startswith("C-"), x)):
        lista.append(nombres.get(h) if h.startswith("C-") else ARTICULOS.get(h[2:]))
    lista = [x for x in dict.fromkeys(lista) if x]
    if not lista:
        return SUSTITUTO_SIN_NOMBRE
    if len(lista) > 4:
        lista = lista[:3] + [f"otros {len(lista) - 3} elementos"]
    return SUSTITUTO.format(lista=_lista_y(lista))


def frase_asumido(campo: str, valor: object) -> str:
    """VA18-12 (E7): «Dato por confirmar con el cliente sobre la red privada: no, acceso público con autenticación.»"""
    sujeto = ARTICULOS.get(campo) or f"el dato de {ETIQUETAS.get(campo, campo.replace('_', ' ')).lower()}"
    return _frase_final(f"Dato por confirmar con el cliente sobre {sujeto}: {minuscula_inicial(str(valor or '').strip())}")


def _supuestos(campos: dict, prosa: list[dict], comp_: _Composicion, consumo=(), resp=None, nombres=None,
               por_forma=()) -> list[dict]:
    """Supuestos del PPTX: lo ASUMIDO siempre en «Confianza baja» (salvo los campos internos: VA18-1), en una frase con
    verbo; después los del consumo que compone el código (I1.7) y los del experto en su orden, con su nivel acotado por
    `nivel_con_tope` y, en el sitio de cada uno retirado por su forma, su frase fija (VA18-5). No se repiten en Riesgos
    (H10): el nivel ya dice que falta confirmarlos."""
    resp, nombres = resp or {}, nombres or {}
    cand = []
    for campo, dato in campos.items():
        if campo in CAMPOS_INTERNOS:
            continue  # VA18-1: se queda en la nota del revisor (apartados 3 y 4)
        for e in dato.get("entradas") or []:
            if e.get("origen") == "ASUMIDO":
                cand.append((frase_asumido(campo, e.get("valor")), [f"R-{campo}"], f"requisito {campo}",
                             "Confianza baja", None))
    cand += [(*c, None) for c in consumo]
    admitidos = {s.get("id"): s for s in prosa}
    retirados = {s.get("id"): s for s in por_forma}
    orden = [s.get("id") for s in resp.get("supuestos") or [] if isinstance(s, dict)]
    orden += [i for i in list(admitidos) + list(retirados) if i not in orden]
    for sid in orden:
        if sid in admitidos:
            s = admitidos[sid]
            cand.append((_frase_final(s["texto"]), [sid], f"experto {sid}", nivel_con_tope(s, resp, campos), s))
        elif sid in retirados:
            cand.append((frase_sustituta(retirados[sid], resp, nombres), [sid], f"sustituto de {sid}",
                         "Confianza baja", None))
    salida, vistos = [], set()
    for texto, hechos, origen, nivel, original in cand:
        if texto in vistos:
            comp_.excluir(origen, texto, "repite otra frase de supuestos ya publicada")
            continue
        if not comp_.limpia(texto, origen) or not 10 <= len(texto) <= 400:
            if not 10 <= len(texto) <= 400:
                comp_.excluir(origen, texto, "fuera de 10-400 caracteres")
            if original is None:
                continue
            texto, origen, nivel = frase_sustituta(original, resp, nombres), f"sustituto de {hechos[0]}", "Confianza baja"
            if texto in vistos:
                comp_.excluir(origen, texto, "repite otra frase de supuestos ya publicada")
                continue
            if not comp_.limpia(texto, origen):
                continue
        if len(salida) >= LIMITES["supuestos"]:
            comp_.excluir(origen, texto, "fuera del límite de supuestos")
            continue
        vistos.add(texto)
        salida.append({"id": f"TX-SUP-{len(salida) + 1:02d}", "texto": texto, "hechos": hechos, "nivel": nivel})
    return salida


def _riesgos_consumo(anexo: dict, sin_precio: list[dict], existentes=frozenset()) -> list[tuple[str, list[str], str]]:
    """Riesgos del consumo en la nube compuestos por código en castellano llano (H9, H10, LES-G-062):
    lo que no tiene precio y lo que el verificador no pudo contrastar, cada grupo en una frase. I1.9: un sistema que ya
    tiene el cliente no es un riesgo de consumo (lo dice su exclusión en «Fuera de alcance»)."""
    from nucleo import anexo_consumo  # diferido: evita el ciclo con el barrido único
    sin_precio = [x for x in sin_precio if x.get("componente_id") not in existentes]
    salida = []
    for motivo, plantilla in (
            (anexo_consumo.MOTIVO_SIN_PRECIO,
             "No se ha podido obtener en Azure Retail Prices el precio de {lista}: su consumo no está valorado "
             "en el anexo y el consumo real será mayor que el total orientativo."),
            (anexo_consumo.MOTIVO_SIN_PRECIO_PUBLICO,
             "Azure Retail Prices no publica un precio de consumo para {lista}: no se valora en el anexo y, si "
             "tiene coste para el cliente, no está incluido en el total orientativo."),
            # PR15-2: facturable con motivo de no valoración; el motivo concreto solo va a la nota del revisor
            (anexo_consumo.MOTIVO_A_VALORAR,
             "El consumo de {lista} queda a valorar con el volumen real y no suma en el total orientativo del "
             "anexo.")):
        grupo = [x for x in sin_precio if x["motivo"] == motivo]
        if grupo:
            ids = list(dict.fromkeys(x["componente_id"] for x in grupo if x.get("componente_id")))[:7]
            salida.append((plantilla.format(lista=_lista_y([x["servicio"] for x in grupo])), ["ANEXO", *ids],
                           "consumo no valorado"))
    # REV13-3: el SaaS que se licencia aparte (Teams, Entra ID, SharePoint) va en una sola frase con el mismo
    # texto que su fila de la diapositiva 8
    saas = [x for x in sin_precio if x["motivo"] == anexo_consumo.MOTIVO_SAAS]
    if saas:
        ids = list(dict.fromkeys(x["componente_id"] for x in saas if x.get("componente_id")))[:7]
        nombres = list(dict.fromkeys(x["servicio"] for x in saas))
        verbo = ("se licencia aparte, no se factura por Azure y no suma" if len(nombres) == 1
                 else "se licencian aparte, no se facturan por Azure y no suman")
        salida.append((f"{_lista_y(nombres)} {verbo} en el total orientativo del anexo.", ["ANEXO", *ids],
                       "consumo no valorado"))
    dudosas = [x for x in anexo.get("lineas") or [] if x.get("verificacion") == "NO VERIFICABLE"]
    if dudosas:
        ids = list(dict.fromkeys(x["componente_id"] for x in dudosas))[:7]
        servicios = list(dict.fromkeys(x["servicio"] for x in dudosas))
        cola = ("su importe en el anexo es orientativo" if len(servicios) == 1
                else "sus importes en el anexo son orientativos")
        salida.append((f"No se ha podido comprobar de forma independiente el precio de {_lista_y(servicios)}; {cola}.",
                       ["ANEXO", *ids], "consumo sin contraste"))
    return salida


def _declarados(resp: dict, oficiales: dict, sin_precio: list[dict], anexo: dict) -> dict[str, set]:
    """Componentes cuyo precio sin obtener o sin contrastar declara el código, con todos sus nombres
    (el publicado, el oficial del catálogo y el que escribió el experto)."""
    ids = [x.get("componente_id") for x in sin_precio]
    ids += [x.get("componente_id") for x in anexo.get("lineas") or [] if x.get("verificacion") == "NO VERIFICABLE"]
    por_id = {c.get("id"): c for c in resp.get("componentes") or []}
    nombres = {x.get("componente_id"): x.get("servicio") for x in [*sin_precio, *(anexo.get("lineas") or [])]}
    salida = {}
    for cid in filter(None, ids):
        comp = por_id.get(cid) or {}
        salida[cid] = {str(n) for n in (nombres.get(cid), oficiales.get(comp.get("catalogo_id")), comp.get("servicio")) if n}
    return salida


def _consumo(anexo: dict, productos: dict[str, str] | None = None) -> dict:
    """Bloque de la diapositiva 8; el concepto de cada línea es `concepto_legible` (REV13-3), en el mismo
    orden que las líneas del anexo (la puerta empareja por posición)."""
    productos = productos or {}
    lineas = anexo.get("lineas") or []
    # I1.7 (decisión 1 del comercial, 13-10-2026): los precios salen de la instantánea que el despliegue descarga de Retail
    # Prices, y la oferta dice «precios consultados el <fecha>» con la fecha de esa instantánea (`fuente.consultado_el`
    # del anexo). Sin una fecha AAAA-MM-DD no se afirma una consulta que no consta: falla en alto.
    consultado = str((anexo.get("fuente") or {}).get("consultado_el") or "")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", consultado) or _fecha(consultado) is None:  # Revisión: «2026-13-40»
        raise errores.IntegridadRota("el anexo no trae la fecha de consulta de los precios (fuente.consultado_el): "
                                     "la diapositiva 8 no puede decir cuándo se consultaron", [repr(consultado)[:40]])
    regiones = list(dict.fromkeys(region_legible(x.get("region")) for x in lineas if x.get("region")))  # VA18-12
    fechas = [str(x.get("effectiveStartDate"))[:10] for x in lineas if x.get("effectiveStartDate")]
    origen, conversion = _origen_precios(anexo.get("fuente") or {})
    if regiones and fechas:
        fuente = (f"{origen}, {'región' if len(regiones) == 1 else 'regiones'} "
                  f"{_lista_y(regiones)}: {PRECIOS_CONSULTADOS} {consultado}, vigentes desde {max(fechas)}{conversion}")
    else:  # VER14-1: sin líneas no se afirma ni región ni vigencia de unos precios que no hay
        fuente = (f"{origen}: ningún componente tiene precio de consumo en esta "
                  f"propuesta ({PRECIOS_CONSULTADOS} {consultado})")
    return {"lineas": [{"servicio": x["servicio"], "concepto": concepto_legible(x, productos.get(x.get("componente_id"))),
                        "coste_mensual_eur": x["coste_mensual_eur"]} for x in lineas],
            "total_mensual_eur": anexo["total_mensual_eur"], "total_anual_eur": anexo["total_anual_eur"],
            "fuente": fuente, "aviso": AVISO_CONSUMO}


# Multinube (esquemas/MULTINUBE.md): de qué fuente sale el euro de la diapositiva 8, por la fuente del anexo (lista
# blanca: otra fuente o procedencia, IntegridadRota). En AWS, la conversión con el tipo del BCE va dicha con su fecha.
ORIGEN_AZURE = "Azure Retail Prices (prices.azure.com)"
ORIGEN_PRECIOS = {("Google Cloud Billing Catalog", "gcp_catalog_eur"):
                      "Google Cloud Billing Catalog (cloudbilling.googleapis.com)",
                  ("AWS Price List", "aws_usd_convertido_bce"): "AWS Price List (pricing.us-east-1.amazonaws.com)"}


def _origen_precios(fuente: dict) -> tuple[str, str]:
    """(origen de los precios, sufijo de conversión) desde anexo.fuente. Sin fuente_moneda, Azure como siempre (el anexo
    de Azure no la escribe y su nombre lo fija su esquema)."""
    if "fuente_moneda" not in fuente:
        return ORIGEN_AZURE, ""
    clave = (fuente.get("nombre"), fuente.get("fuente_moneda"))
    if clave not in ORIGEN_PRECIOS:
        raise errores.IntegridadRota("el anexo no trae una fuente de precios conocida con su procedencia del euro",
                                     [repr(clave)[:120]])
    if clave[1] != "aws_usd_convertido_bce":
        return ORIGEN_PRECIOS[clave], ""
    tasa, fecha = fuente.get("tipo_bce"), str(fuente.get("fecha_tipo_bce") or "")
    if isinstance(tasa, bool) or not isinstance(tasa, (int, float)) or not tasa > 0 \
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", fecha) or _fecha(fecha) is None:
        raise errores.IntegridadRota("el anexo de AWS no trae el tipo de cambio del BCE con su fecha",
                                     [repr(tasa), repr(fecha)])
    tasa_txt = f"{Decimal(str(tasa)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}".replace(".", ",")
    return ORIGEN_PRECIOS[clave], (f"; publicados en USD y convertidos a euros con el tipo de referencia del BCE del "
                                   f"{fecha} (1 EUR = {tasa_txt} USD), importes orientativos")


def _condiciones(resumen: dict, tarifa: dict) -> list[tuple[str, list[str], str]]:
    hitos = resumen.get("hitos") or []
    pcts = ", ".join(f"{h['porcentaje']:g} %" if isinstance(h.get("porcentaje"), (int, float)) else str(h.get("porcentaje"))
                     for h in hitos)
    pago = _nfc(str(tarifa.get("condiciones_pago", ""))).strip()
    validez = tarifa.get("validez_oferta_dias")
    return [(f"Precio cerrado de {formato_eur(resumen['precio_cerrado_eur'])}, IVA no incluido.", ["ESTIMACION"], "fijo precio"),
            (f"Facturación por hitos: {len(hitos)} hitos ({pcts}), según la tabla de hitos de pago.",
             ["TARIFA", "ESTIMACION"], "fijo hitos"),
            (f"Condiciones de pago: {pago}. Validez de la oferta: {validez} días.", ["TARIFA"], "fijo pago"),
            ("El consumo en la nube no está incluido y lo asume el cliente.", ["FIJO-CONDICIONES", "ANEXO"], "fijo consumo")]


def _perfiles(estado: dict, tarifa: dict) -> list[str]:
    vistos = [p.get("nombre") for p in (tarifa or {}).get("perfiles") or [] if p.get("nombre")]
    for b in (estado.get("carga") or {}).get("briefs") or []:
        vistos += list(b.get("perfiles_permitidos") or [])
    return sorted(set(vistos))


def componer(estado: dict, catalogo: dict, tarifa: dict) -> dict:
    """Bloque textos_cliente (esquema textos_cliente), puro y determinista. Cada frase cita sus hechos.
    IntegridadRota si faltan hechos; ReglaIncumplida si el resultado no valida (p. ej. todo excluido)."""
    from nucleo import esquema  # diferido: evita ciclos al importar
    carga = estado.get("carga") or {}
    faltan = [k for k in ("alta", "requisitos", "respuestas_expertos", "verificacion", "anexo_consumo", "estimacion")
              if not carga.get(k)]
    resp = est_mod.registro_de_carga(carga).get("respuesta")
    if faltan or not resp or not (carga.get("estimacion") or {}).get("resumen"):
        raise errores.IntegridadRota("No se pueden componer los textos del cliente: faltan hechos",
                                     [f"falta carga.{k}" for k in faltan] or ["falta la respuesta o el resumen"])
    tarifa = (tarifa or {}).get("tarifa", tarifa) or {}
    alta, campos = carga["alta"], carga["requisitos"]["campos"]
    resumen, entrada = carga["estimacion"]["resumen"], carga["estimacion"].get("entrada") or {}
    oficiales = {c["id"]: c["nombre_oficial"] for c in (catalogo or {}).get("componentes") or []}
    comp_ = _Composicion(_perfiles(estado, tarifa),
                         palabras_admitidas(alta.get("cliente"), alta.get("titulo"), *oficiales.values()),
                         importes_permitidos(resumen))
    codigo = estado["codigo"]
    # I1.9 (contrato común): los recursos que el cliente ya tiene, con el nombre con el que se le enseñan
    existentes = [(c, nombre_base_existente(c, entrada_de(c, campos), oficiales))
                  for c in resp.get("componentes") or [] if isinstance(c, dict) and entrada_de(c, campos) is not None]
    nombres = {c.get("id"): _nombre_componente(c, oficiales) for c in resp.get("componentes") or [] if isinstance(c, dict)}
    nombres.update({c.get("id"): base for c, base in existentes})

    # H8 y VER14-8: cada rótulo en una sola viñeta, con sus valores unidos por «; » y en minúscula tras los dos
    # puntos si empiezan por una palabra común (nunca dos viñetas «Marco normativo»)
    nec = etiquetadas("Objetivo", _valores(campos, "objetivo"), "R-objetivo", "requisito objetivo")
    nec += etiquetadas("Usuarios finales", _valores(campos, "ubicacion_usuarios"), "R-ubicacion_usuarios",
                       "requisito ubicacion_usuarios")
    nec += etiquetadas("Marco normativo", _valores(campos, "marco_normativo"), "R-marco_normativo",
                       "requisito marco_normativo")
    objetivos, alcance = _valores(campos, "objetivo"), []
    for v in _valores(campos, "alcance_funcional"):
        # VA19-1 (I1.10): «Incluido» (diap. 5) lleva TODO el alcance funcional, también la función que repite el objetivo
        # (antes se excluía de la lista única y desaparecía del alcance). Esa frase cita además R-objetivo y solo se omite
        # en «Capacidades principales» (diap. 3), donde el objetivo ya está a la vista (VERIF-8).
        hechos = ["R-alcance_funcional"] + (["R-objetivo"] if any(repite(v, o) for o in objetivos) else [])
        alcance.append((_frase_final(v), hechos, "requisito alcance_funcional"))
    # VERIF-2: el canal o la integración que pidió el cliente (p. ej., Teams) forma parte del alcance
    # I1.9 (E10): un canal que es un sistema que ya tiene el cliente se dice como integración con su sistema
    en_frase = {c["id"]: nombre_en_frase(entrada_de(c, campos), base) for c, base in existentes}
    filas = {x.get("id"): x for x in (catalogo or {}).get("componentes") or [] if isinstance(x, dict)}
    frases_ex = frases_existentes(existentes, campos, filas, en_frase)  # VA19-1: agrupadas por cita; licencias como uso
    for v in _valores(campos, "canales_integraciones"):
        suyo = next((base for c, base in existentes if nombra_existente(v, c, base, campos, oficiales)), None)
        if suyo is None:
            alcance.append((_frase_final(f"Canal o integración: {v}"), ["R-canales_integraciones"],
                            "requisito canales_integraciones"))
        elif not (_plano(v).rstrip(" .") and any(re.search(r"(?<!\w)" + re.escape(_plano(v).rstrip(" .")) + r"(?!\w)",
                                                         _plano(f)) for f, _, _ in frases_ex)):  # palabra entera
            # ARR1 (I1.10): solo se declara excluido lo que no se publica; un canal que es el nombre del sistema
            # («Microsoft Teams») ya está, literal, en la frase de los sistemas del cliente (la puerta lo exige así)
            comp_.excluir("requisito canales_integraciones", v, f"es un sistema que ya tiene el cliente ({suyo}): "
                          "figura en el alcance entre los sistemas que ya tiene el cliente")
    alcance += frases_ex
    fda = [(_frase_final(v), ["R-fuera_de_alcance"], "requisito fuera_de_alcance") for v in _valores(campos, "fuera_de_alcance")]
    if existentes:
        fda.append((_frase_final("Licencias y consumo de los sistemas que ya tiene el cliente: "
                                 + _lista_y([en_frase[c["id"]] for c, _ in existentes])),
                    ["R-ya_contratado_por_cliente", *[c["id"] for c, _ in existentes]][:8], "fijo existentes"))
    fda += [(FIJO_EXCLUSIONES, ["FIJO-EXCLUSIONES"], "fijo exclusiones"), (FIJO_SOPORTE, ["FIJO-SOPORTE"], "fijo soporte")]
    from nucleo import anexo_consumo  # diferido: evita el ciclo con el barrido único
    # I1.7 (decisión 2, LES-G-100.5): la base citada y los factores aplicados los declara el código; la prosa del experto
    # que vuelve a dar factores (y podría contradecir los que aplicó el núcleo) va a la nota (LES-G-095)
    consumo, cubiertos, fallidos = supuestos_consumo(resp, oficiales)
    if fallidos:  # revisión independiente (I1.7): una línea valorada sin su base explicada no se publica (fail closed)
        raise errores.ReglaIncumplida("no se puede componer el supuesto de consumo de un precio por volumen",
                                      [f"{origen}: {motivo}" for origen, motivo in fallidos])
    motivo_factor = "repite los factores de consumo que declara el código en su supuesto de consumo (LES-G-100.5)"
    prosa_sup, por_forma = [], []
    for s in _prosa(resp, "supuestos", carga, comp_, por_forma):
        if repite_factor(s, resp, cubiertos):
            comp_.excluir(f"experto {s['id']}", s["texto"], motivo_factor)
        else:
            prosa_sup.append(s)
    supuestos = _supuestos(campos, prosa_sup, comp_, consumo, resp, nombres, por_forma)
    sin_precio = anexo_consumo.no_valorados(estado, catalogo)
    riesgos = []
    declarados = _declarados(resp, oficiales, sin_precio, carga["anexo_consumo"])
    for r in _prosa(resp, "riesgos", carga, comp_):
        if _repite_consumo(r, resp, declarados):  # VERIF-8: lo dice el código en los riesgos de consumo
            comp_.excluir(f"experto {r['id']}", r["texto"], "repite un riesgo de consumo que ya declara el código")
        elif repite_factor(r, resp, cubiertos):
            comp_.excluir(f"experto {r['id']}", r["texto"], motivo_factor)
        else:
            riesgos.append((_frase_final(r["texto"]), [r["id"]], f"experto {r['id']}"))
    riesgos += riesgos_modelo(resp, catalogo, entrada.get("fecha"), resumen.get("duracion_semanas"))  # I1.7
    riesgos += _riesgos_consumo(carga["anexo_consumo"], sin_precio, {c["id"] for c, _ in existentes})

    textos = {
        "schema": SCHEMA, "codigo": codigo, "hash_hechos": hashes.hash_json(hechos_de(carga)),
        "portada": {"titulo": _nfc(alta["titulo"]), "cliente": _nfc(alta["cliente"]), "codigo": codigo,
                    "fecha": entrada.get("fecha") or "", "subtitulo": f"Propuesta para revisión interna · versión {estado['version']}"},
        "necesidad": comp_.lista("necesidad", "NEC", nec),
        "arquitectura": _arquitectura(resp, oficiales, comp_, campos),
        "alcance": comp_.lista("alcance", "ALC", alcance),
        "fuera_de_alcance": comp_.lista("fuera_de_alcance", "FDA", fda),
        "supuestos": supuestos,
        "precio": {"precio_cerrado_eur": resumen["precio_cerrado_eur"], "iva": "IVA no incluido",
                   "duracion_semanas": resumen["duracion_semanas"],
                   "hitos": [{"nombre": h["nombre"], "porcentaje": h["porcentaje"], "importe_eur": h["importe_eur"]}
                             for h in resumen.get("hitos") or []]},
        "consumo": _consumo(carga["anexo_consumo"], productos_precio(resp, catalogo)),
        "riesgos": comp_.lista("riesgos", "RSG", riesgos),
        "condiciones": comp_.lista("condiciones", "CON", _condiciones(resumen, tarifa)),
        "excluidas": comp_.excluidas,
    }
    errs = esquema.validar(textos, esquema.cargar("textos_cliente"))
    # barrido final de TODO lo publicado: nombres de componente (el servicio de una desviación es prosa
    # del modelo), conceptos de consumo, portada y referencias (revisión independiente del integrador)
    errs += [f"{donde}: {h}" for donde, t in _todas(textos) for h in barrer(t, comp_.perfiles)]
    # VERIF-8: ningún identificador técnico en la prosa (los nombres de componente y los conceptos de
    # consumo son datos del catálogo y de Azure Retail Prices, y la portada lleva el nombre del cliente)
    errs += [f"{donde}: {h}" for donde, t in _todas(textos) if not donde.startswith(("componente", "consumo", "portada", "referencia"))
             for h in jerga_tecnica(t, comp_.admitidas)]
    errs += presupuesto_en_textos(textos, campos, resumen)  # VA18-1: red final, por si algo lo coló
    if errs:
        raise errores.ReglaIncumplida("Los textos del cliente no se pueden publicar", errs)
    return textos


def _todas(textos: dict):
    """(ubicación, texto) de todo lo que se publica (para el barrido final de marcadores)."""
    for k in ("necesidad", "alcance", "fuera_de_alcance", "supuestos", "riesgos", "condiciones"):
        for f in textos.get(k) or []:
            yield f"{k} {f['id']}", f["texto"]
    for k, v in (textos.get("portada") or {}).items():
        yield f"portada {k}", str(v)
    for c in (textos.get("arquitectura") or {}).get("capas") or []:
        for x in c["componentes"]:
            yield f"componente {x['id']}", x["nombre"]
    for r in (textos.get("arquitectura") or {}).get("referencias") or []:
        yield f"referencia {r['id']}", r["titulo"]
    for x in (textos.get("consumo") or {}).get("lineas") or []:
        yield "consumo", f"{x['servicio']} {x['concepto']}"
# VER14-10 (I1.5, D): las asunciones del XLSX interno salen de los supuestos del experto con la misma red que
# los del PPTX: tipos de despliegue traducidos, plazo del Gantt y sin redacción interna. Un supuesto que declara
# el precio sin comprobar («Los costes de … están NO VERIFICADO en Azure Retail Prices») lo vuelve a decir el
# código, con concordancia y sin jerga; lo demás que no pasa se omite y se avisa (nunca en silencio).
def asunciones_estimacion(resp: dict, semanas: object) -> tuple[list[str], list[str]]:
    """(asunciones, avisos) para `estimacion.componer_entrada`, en el orden de los supuestos del experto."""
    componentes = {c.get("id"): c for c in (resp or {}).get("componentes") or [] if isinstance(c, dict)}
    salida, avisos = [], []
    for s in (resp or {}).get("supuestos") or []:
        if not isinstance(s, dict):
            continue
        texto = traducir_skus(_nfc(str(s.get("texto", ""))).strip(), _regiones_citadas(s, resp))
        texto, motivo = plazo_del_gantt(texto, semanas)
        if motivo:
            avisos.append(f"asunción {s.get('id')} omitida ({motivo}): «{texto[:80]}»")
            continue
        interna = redaccion_interna(texto) + [h for h in jerga_tecnica(texto) if "sin traducir" in h]
        if not interna:
            salida.append(_frase_final(texto))
            continue
        nombres = [str(componentes[h].get("servicio") or "").strip() for h in s.get("hechos") or []
                   if h in componentes and str(componentes[h].get("servicio") or "").strip()]
        if _RE_PRECIO.search(texto) and _RE_ESTADO_INTERNO.search(texto) and nombres:
            nombres = list(dict.fromkeys(nombres))
            salida.append("No se ha podido comprobar en Azure Retail Prices el precio de consumo de "
                          f"{nombres[0]}." if len(nombres) == 1 else
                          "No se han podido comprobar en Azure Retail Prices los precios de consumo de "
                          f"{_lista_y(nombres)}.")
            avisos.append(f"asunción {s.get('id')} recompuesta por el código (redacción interna: {'; '.join(interna)})")
        else:
            avisos.append(f"asunción {s.get('id')} omitida (redacción interna: {'; '.join(interna)}): «{texto[:80]}»")
    return salida, avisos
