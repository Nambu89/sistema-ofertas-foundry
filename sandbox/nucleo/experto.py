"""Respuesta de preventa-experto-azure (CONTRATOS.md §6.3, §6.4 y §4.7).

Esquema cerrado (LES-G-060), eco literal del brief, lista blanca de Learn, componentes del
catálogo o desviación justificada, precios completos, perfiles solo de la tarifa y cero
marcadores. `parsear` solo quita lo demostrablemente equivalente (BOM, espacios y UNA valla de
código envolvente; LES-G-047). Un eco distinto suma un intento T2 con su motivo, como cualquier otro fallo (PR19-1,
I1.10); un brief_id distinto con el eco literal bloquea.
"""
from __future__ import annotations

import datetime
import importlib
import json
import math
import re
import unicodedata
import urllib.parse
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from nucleo import brief as brief_mod
from nucleo import esquema
from nucleo import estado as est_mod
from nucleo.errores import Bloqueo, EntradaInvalida, IntegridadRota, ReglaIncumplida, TransicionNoPermitida

PREFIJOS_ARQUITECTURA: tuple[str, ...] = (
    "/azure/architecture", "/azure/well-architected", "/azure/cloud-adoption-framework", "/azure/ai-foundry",
    "/azure/foundry")
PREFIJOS_REFERENCIA: tuple[str, ...] = PREFIJOS_ARQUITECTURA + (
    "/azure/search", "/azure/ai-services", "/azure/foundry-classic", "/azure/security", "/azure/private-link",
    "/azure/virtual-network", "/azure/app-service", "/azure/container-apps", "/azure/azure-functions",
    "/azure/storage", "/azure/cosmos-db", "/azure/key-vault", "/azure/azure-monitor", "/azure/api-management",
    "/azure/reliability", "/azure/defender-for-cloud", "/azure/governance", "/azure/role-based-access-control",
    "/azure/cost-management-billing", "/azure/logic-apps", "/azure/bot-service", "/entra", "/purview",
    "/compliance", "/security/benchmark/azure", "/microsoftteams/platform",
    # Ampliación I11 (08-10-2026): cada prefijo comprobado hoy con HTTP 200 y título en una página
    # representativa (docs/I1/CAMBIOS-I11-V.md). Son documentación de producto de Microsoft; siguen fuera
    # /answers, /training, /shows, /samples, /archive y /previous-versions.
    "/azure/frontdoor", "/azure/web-application-firewall", "/azure/firewall", "/azure/application-gateway",
    "/azure/dns", "/azure/bastion", "/azure/ddos-protection", "/azure/networking", "/azure/expressroute",
    "/azure/vpn-gateway", "/azure/event-grid", "/azure/service-bus-messaging", "/azure/azure-sql",
    "/azure/postgresql", "/azure/data-factory", "/azure/databricks", "/azure/aks", "/azure/container-registry",
    "/azure/machine-learning", "/azure/redis", "/azure/sentinel", "/azure/backup", "/azure/azure-resource-manager",
    "/fabric", "/power-bi", "/office365", "/microsoft-365", "/microsoft-copilot-studio")
HOST_LEARN = "learn.microsoft.com"
_IDIOMA = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})+$")
_TOPES = {"microsoft_docs_search": 3, "microsoft_docs_fetch": 2}
CAMPOS_REQUISITOS = ("objetivo", "nubes", "alcance_funcional", "canales_integraciones", "ubicacion_usuarios", "marco_normativo", "volumetria",
                     "identidad_acl_origen", "red_privada", "tipo_suscripcion", "plazo", "presupuesto_orientativo",
                     "idioma_oferta", "fuera_de_alcance", "ya_contratado_por_cliente")
# REV17-3 (I1.8, decisión del PM): lo que el cliente ya tiene o paga es un campo propio de requisitos, capturado en la
# suficiencia con cita literal de la fuente; «a_cargo_del_cliente» solo vale citando una entrada de ese campo. El brief lo
# pinta como sección con viñetas (brief.generar; docs/I1/CAMBIOS-I18-P.md §4).
CAMPO_CLIENTE = "ya_contratado_por_cliente"
SECCION_CLIENTE = "## Lo que el cliente ya tiene o paga"
# H-V8: los textos que ve el cliente (o la nota) no hablan del proceso interno. Sin distinguir mayúsculas
# (también «c-02»). Se rechaza (intento T2), no se repara. Fuera a propósito: «sandbox», «A2A» y «Code
# Interpreter», que una oferta de Foundry puede citar con todo derecho (un entorno sandbox, el protocolo A2A).
_META_IDS = re.compile(r"\b(?:REF|RG|S|C|P|T)-\d{2}\b|\b(?:BRF|CNS)-OF-|\bR-(?:" + "|".join(CAMPOS_REQUISITOS) + r")\b", re.IGNORECASE)
_META_PALABRAS = re.compile(
    r"\bverificador(?:es|as?)?\b|\bbriefs?\b|\bconsolidado CNS|\bpreventa-[a-z]+"
    r"|\bronda(?:s)? (?:de verificaci[oó]n|anterior(?:es)?|previas?)\b"
    r"|\bcorrecci(?:ón|on|ones) (?:solicitad[ao]s?|previas?|anteriores?|del verificador)\b", re.IGNORECASE)
CAMPOS_METATEXTO = (("supuestos", "texto"), ("riesgos", "texto"), ("riesgos", "mitigacion"))


def metatexto_en(resp: dict) -> list[str]:
    """Referencias al proceso interno en supuestos, riesgos y mitigaciones (H-V8)."""
    salida = []
    for bloque, campo in CAMPOS_METATEXTO:
        for x in resp.get(bloque) or []:
            texto = str(x.get(campo) or "")
            hallados = [m.group(0) for r in (_META_IDS, _META_PALABRAS) for m in r.finditer(texto)]
            if hallados:
                salida.append(f"{bloque}.{x.get('id')}.{campo}: metatexto del proceso interno "
                              f"({', '.join(dict.fromkeys(hallados))}); lo que ve el cliente no habla de ids, "
                              "del verificador, del brief ni de las rondas")
    return salida


def normalizar_url(url: str) -> str:
    """https://learn.microsoft.com/<ruta> sin idioma, en minúsculas, sin consulta, fragmento ni barra
    final. Devuelve "" si el esquema no es https o el host no es exactamente learn.microsoft.com."""
    try:
        p = urllib.parse.urlsplit((url if isinstance(url, str) else "").strip())  # I1.7 (Revisión): un número no lanza
        puerto = p.port  # I1.6 (Revisión): un puerto mal formado lanzaba ValueError fuera del try
    except ValueError:
        return ""
    # I1.7 (Revisión): con «@» en la parte de red (usuario o contraseña, aunque vayan vacíos) no es una página de Learn.
    if p.scheme.lower() != "https" or (p.hostname or "").lower() != HOST_LEARN or puerto is not None or "@" in p.netloc:
        return ""
    segmentos = [s for s in urllib.parse.unquote(p.path).lower().split("/") if s]
    if any(s in (".", "..") for s in segmentos):  # «/azure/architecture/../../x» no sigue bajo el prefijo
        return ""
    if segmentos and _IDIOMA.match(segmentos[0]):
        segmentos = segmentos[1:]
    return f"https://{HOST_LEARN}/" + "/".join(segmentos) if segmentos else ""


def _ruta(url: str) -> str:
    n = normalizar_url(url)
    return n[len(f"https://{HOST_LEARN}"):] if n else ""


def _bajo(ruta: str, prefijos: tuple[str, ...]) -> bool:
    return bool(ruta) and any(ruta == p or ruta.startswith(p + "/") for p in prefijos)


def es_referencia_permitida(url: str) -> bool:
    return _bajo(_ruta(url), PREFIJOS_REFERENCIA)


def es_referencia_arquitectura(url: str) -> bool:
    return _bajo(_ruta(url), PREFIJOS_ARQUITECTURA)


def _sin_duplicados(pares: list) -> dict:
    claves = [k for k, _ in pares]
    repetidas = sorted({k for k in claves if claves.count(k) > 1})
    if repetidas:
        raise ValueError(f"claves repetidas en un objeto JSON: {repetidas}")
    return dict(pares)


def _rechazar_constante(nombre: str):
    raise ValueError(f"constante no admitida en JSON: {nombre}")


def parsear(texto: str) -> dict:
    """Quita BOM, espacios y UNA valla ``` envolvente (con o sin «json»); nada más. ReglaIncumplida
    si no es un objeto JSON (claves repetidas, NaN e infinito también se rechazan)."""
    t = (texto or "").lstrip("\ufeff").replace("\r\n", "\n").strip()  # CRLF->LF: JSON no admite saltos crudos en cadenas
    m = re.fullmatch(r"```(?:json)?[ \t]*\n(.*)\n```", t, flags=re.DOTALL | re.IGNORECASE)
    if m:
        t = m.group(1).strip()
    try:
        obj = json.loads(t, object_pairs_hook=_sin_duplicados, parse_constant=_rechazar_constante)
    except (json.JSONDecodeError, ValueError) as e:
        raise ReglaIncumplida(f"La respuesta no es JSON válido: {e}", [str(e)]) from e
    if not isinstance(obj, dict):
        raise ReglaIncumplida("La respuesta no es un objeto JSON", [type(obj).__name__])
    return obj


def _cadenas(obj: object, ruta: str = "$"):
    if isinstance(obj, str):
        yield ruta, obj
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            yield from _cadenas(x, f"{ruta}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _cadenas(v, f"{ruta}.{k}")


def marcadores_en(obj: object, excluir: tuple[str, ...] = ()) -> list[str]:
    """Barrido único de §0 (textos_cliente.marcadores, de C) sobre cada cadena del objeto."""
    marcadores = importlib.import_module("nucleo.textos_cliente").marcadores
    salida = []
    for ruta, s in _cadenas(obj):
        if ruta in excluir:
            continue
        salida += [f"{ruta}: marcador {h!r}" for h in marcadores(s)]
    return salida


def _fecha_iso(s: str) -> bool:
    try:
        if "T" in s:
            datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            datetime.date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def _repetidos(ids: list[str], que: str) -> list[str]:
    return [f"{que}: id repetido {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]


# REV-2 (LES-G-098.5): el veto de región identifica el servicio por id Y por todos sus alias. Prefijos de marca que
# se quitan para derivar el alias corto («Azure AI Search» → «AI Search»), solo si quedan 2 palabras o más (nunca
# «Search» suelto); un alias de menos de 5 letras no cuenta.
_PREFIJOS_MARCA = ("azure", "microsoft")
_ALIAS_MIN = 5


# Homoglifos habituales (cirílico y griego, ya en minúsculas) que se pliegan a su letra latina antes de comparar.
HOMOGLIFOS = str.maketrans({
    "\u0430": "a", "\u0432": "b", "\u0435": "e", "\u043a": "k", "\u043c": "m", "\u043d": "h", "\u043e": "o",
    "\u0440": "p", "\u0441": "c", "\u0442": "t", "\u0443": "y", "\u0445": "x", "\u0456": "i", "\u0458": "j",
    "\u0455": "s", "\u0501": "d", "\u04bb": "h", "\u04cf": "l", "\u051b": "q", "\u051d": "w", "\u03b1": "a",
    "\u03b2": "b", "\u03b5": "e", "\u03b7": "h", "\u03b9": "i", "\u03ba": "k", "\u03bc": "m", "\u03bf": "o",
    "\u03c1": "p", "\u03c4": "t", "\u03c5": "y", "\u03c7": "x", "\u03b6": "z"})


def _plegar(texto: object) -> str:
    """NFKD, sin tildes, minúsculas y con los homoglifos de HOMOGLIFOS pasados a su letra latina."""
    t = unicodedata.normalize("NFKD", texto if isinstance(texto, str) else "")
    return "".join(ch for ch in t if not unicodedata.combining(ch)).casefold().translate(HOMOGLIFOS)


def _compacto(texto: object) -> str:
    """Plegado y solo letras y dígitos ASCII: «AZURE  AI-Search (S1)» → «azureaisearchs1»."""
    return "".join(ch for ch in _plegar(texto) if "a" <= ch <= "z" or "0" <= ch <= "9")


def alias_servicio(entrada: dict) -> list[str]:
    """Alias compactos de una entrada del catálogo, sin repetir: nombre oficial, `alias` (lista de {"nombre",
    "fuente_url"} que añade el catálogo, docs/I1/CAMBIOS-I12-F1.md; se admite también texto), nombre de la API
    de precios (el antiguo: «Azure Cognitive Search») y la forma sin «Azure»/«Microsoft» de cada uno.
    Misma regla en verificar_paquete.alias_servicio."""
    extra = entrada.get("alias") or []
    extra = extra if isinstance(extra, list) else [extra]
    nombres = [entrada.get("nombre_oficial"), entrada.get("service_name_precios")]
    nombres += [a.get("nombre") if isinstance(a, dict) else a for a in extra]  # {"nombre", "fuente_url"} o texto
    salida: list[str] = []
    for nombre in nombres:
        if not isinstance(nombre, str):
            continue
        palabras = nombre.split()
        formas = [nombre] + ([" ".join(palabras[1:])]
                             if len(palabras) >= 3 and _compacto(palabras[0]) in _PREFIJOS_MARCA else [])
        for forma in formas:
            c = _compacto(forma)
            if len(c) >= _ALIAS_MIN and c not in salida:
                salida.append(c)
    return salida


def alias_inequivocos(catalogo: dict) -> dict:
    """{id: alias} quitando los que aparecen dentro de algún alias de OTRA entrada: un alias compartido («Foundry
    Tools», nombre de precios de seis servicios) no identifica el servicio y vetaría a los demás (Revisión, I1.2)."""
    entradas = [e for e in (catalogo or {}).get("componentes") or [] if isinstance(e, dict)]
    todos = [(e.get("id"), alias_servicio(e)) for e in entradas]
    return {i: [a for a in al if not any(a in b for k, (j, otros) in enumerate(todos) if k != n for b in otros)]
            for n, (i, al) in enumerate(todos)}


def _letras_no_latinas(texto: object) -> bool:
    """Tras plegar (homoglifos incluidos), quedan letras que no son a-z: el alias no se puede comprobar."""
    return any(ch.isalpha() and not ("a" <= ch <= "z") for ch in _plegar(texto))


# REVER-1 y REVER-2 (I1.2, LES-G-098.5): el servicio de un componente se identifica por un dato estructurado, en este
# orden: (a) su catalogo_id válido; (b) el serviceName (y, si lo hay, el productName) del filtro de sus precios, que
# viene de la API de precios, mapeado al catálogo por service_name_precios (y producto_precios); (c) solo como red, un
# alias del catálogo como FRASE completa del nombre. Sin bolsas de palabras: «API de búsqueda con IA» no es AI Search.
# Misma lógica en verificar_paquete (prueba de igualdad en tests/test_i12_arreglos_servicename.py).
_INVISIBLES = ("Cf", "Mn", "Me")  # guion blando, anchura cero, selectores de variante: no cortan una palabra


def _tokens(texto: object) -> list[str]:
    """Palabras del texto plegado; los invisibles se quitan antes de cortar («Bús» + U+00AD + «queda» es una palabra)."""
    limpio = "".join(ch for ch in _plegar(texto) if unicodedata.category(ch) not in _INVISIBLES)
    return [p for p in re.split(r"[^a-z0-9]+", limpio) if p]


def contiene_frase(texto: object, alias: str) -> bool:
    """El alias (compacto) es exactamente una secuencia de palabras seguidas del texto, de borde a borde:
    «AI-Search (S1)» y «AzureAISearch» contienen «aisearch»; «Kai Search» y «Search AI» no."""
    palabras = _tokens(texto)
    for i in range(len(palabras)):
        acumulado = ""
        for p in palabras[i:]:
            acumulado += p
            if acumulado == alias:
                return True
            if not alias.startswith(acumulado):
                break
    return False


def alias_en_nombre(servicio: object, alias: list[str]) -> str | None:
    """El primer alias (compacto) que el nombre contiene como frase completa, o None."""
    return next((a for a in alias if contiene_frase(servicio, a)), None)


def _entradas(catalogo: dict) -> list[dict]:
    return [e for e in (catalogo or {}).get("componentes") or [] if isinstance(e, dict)]


def _literales_filtro(filtro: object) -> tuple[list[tuple[str, str]], list[str], bool]:
    """Recorre un filtro OData tras NFKC y sin los caracteres de formato (Cf): ([(texto fuera de literales que precede
    al literal, valor del literal)], [cada trozo fuera de literales, el último incluido], cerrado). '' dentro de un
    literal es una comilla; tras un literal sin cerrar no se lee nada más (cerrado = False)."""
    if not isinstance(filtro, str):
        return [], [], True
    t = "".join(ch for ch in unicodedata.normalize("NFKC", filtro) if unicodedata.category(ch) != "Cf")
    pares, trozos, fuera, i = [], [], "", 0
    while i < len(t):
        if t[i] != "'":
            fuera, i = fuera + t[i], i + 1
            continue
        valor, j = [], i + 1
        while j < len(t) and (t[j] != "'" or t[j + 1:j + 2] == "'"):
            valor.append(t[j])
            j += 2 if t[j] == "'" else 1
        trozos.append(fuera)
        if j >= len(t):
            return pares, trozos, False  # literal sin cerrar
        pares.append((fuera, "".join(valor)))
        fuera, i = "", j + 1
    trozos.append(fuera)
    return pares, trozos, True


def valores_filtro(filtro: object, campo: str) -> list[str]:
    """Valores de «campo eq '…'» en un filtro OData de la API de precios (el campo sin distinguir mayúsculas; '' es
    una comilla), tras NFKC y sin los caracteres de formato (Cf). Recorre los literales: un «serviceName eq» escrito
    DENTRO de otro literal no cuenta ni tapa al real (Revisión, I1.2), y tras un literal sin cerrar no cuenta nada.
    Otra forma (contains, in) no identifica nada."""
    antes = re.compile(r"(?<!\w)" + re.escape(campo) + r"\s+eq\s+$", re.IGNORECASE)
    return [valor for fuera, valor in _literales_filtro(filtro)[0] if antes.search(fuera)]


def servicios_de_precio(precio: dict, catalogo: dict) -> list[frozenset[str]]:
    """Por cada serviceName del filtro que esté en el catálogo, los ids que lo comparten; si son varios («Foundry
    Tools»: seis), el productName los reduce por producto_precios. Sin serviceName, el productName solo."""
    entradas = _entradas(catalogo)
    filtro = precio.get("filtro") if isinstance(precio, dict) else None
    productos = {c for p in valores_filtro(filtro, "productName") if (c := _compacto(p))}
    por_producto = frozenset(e.get("id") for e in entradas if _compacto(e.get("producto_precios")) in productos)
    servicios = [c for s in valores_filtro(filtro, "serviceName") if (c := _compacto(s))]
    salida: list[frozenset[str]] = []
    for s in servicios:
        candidatos = frozenset(e.get("id") for e in entradas if _compacto(e.get("service_name_precios")) == s)
        if len(candidatos) > 1 and candidatos & por_producto:
            candidatos &= por_producto
        if candidatos:
            salida.append(candidatos)
    if not servicios and por_producto:
        salida.append(por_producto)
    return salida


def _nombres(ids: object, catalogo: dict) -> str:
    oficiales = {e.get("id"): e.get("nombre_oficial") for e in _entradas(catalogo)}
    return " o ".join(f"{oficiales.get(i)} ({i})" for i in sorted(ids))


def identificar_servicio(comp: dict, catalogo: dict, precios: list | None = None) -> dict:
    """{"id", "por" ("catalogo_id", "precio" o None), "precio" (id del precio que lo identifica), "incoherencias"}.
    (a) catalogo_id del catálogo; si no, (b) el servicio único de sus precios. Un precio cuyo servicio no incluye el
    identificado es una incoherencia: el precio y el componente hablan de servicios distintos."""
    ids = {e.get("id") for e in _entradas(catalogo)}
    cid = comp.get("catalogo_id")
    propios = [p for p in precios or [] if isinstance(p, dict) and p.get("componente_id") == comp.get("id")]
    conjuntos = [(p, c) for p in propios for c in servicios_de_precio(p, catalogo)]
    sid, por, pid = (cid, "catalogo_id", None) if cid in ids else (None, None, None)
    if sid is None:
        unico = next(((p, c) for p, c in conjuntos if len(c) == 1), None)
        if unico:
            sid, por, pid = next(iter(unico[1])), "precio", unico[0].get("id")
    incoherencias = []
    for p, c in conjuntos:
        if sid is not None and sid not in c:
            servicios = ", ".join(f"«{s}»" for s in valores_filtro(p.get("filtro"), "serviceName")) or "su productName"
            declarado = (f"declara {_nombres([sid], catalogo)}" if por == "catalogo_id"
                         else f"tiene otro precio ({pid}) de {_nombres([sid], catalogo)}")
            incoherencias.append(f"el precio {p.get('id')} (serviceName {servicios}) es de {_nombres(c, catalogo)} y "
                                 f"el componente {declarado}: el precio y el componente hablan de servicios distintos; "
                                 "asocia cada precio al componente de su servicio o corrige el catalogo_id")
    return {"id": sid, "por": por, "precio": pid, "incoherencias": list(dict.fromkeys(incoherencias))}


# REVSN-1, REVSN-2 y REVSN-5 (I1.2, decisión del PM; LES-G-098.3: fallar cerrado es una lista blanca). En el camino
# con precio ya no hay heurísticas de nombres: todo componente con precio lleva un catalogo_id del catálogo, y el
# filtro de cada precio casa ENTERO con ese servicio. Un solo serviceName, el suyo (service_name_precios) o uno de los
# precios_auxiliares del catálogo; productName solo si es el suyo (producto_precios, o los del auxiliar); un solo
# armRegionName, la región del componente o la region_precio que el catálogo declara para los servicios que Retail
# Prices solo publica como «Global»; y solo condiciones unidas con «and». Los valores se comparan EXACTOS, como los
# casa la API (distingue mayúsculas: «global» devuelve 0 artículos y «Global» 3; consulta del 09-10-2026).
CAMPOS_FILTRO = ("serviceName", "productName", "armRegionName")
_CONECTOR_NO_ADMITIDO = re.compile(r"(?<!\w)(?:or|not)(?!\w)", re.IGNORECASE)


def forma_filtro(filtro: object) -> list[str]:
    """Lo que el filtro tiene fuera de la forma admitida, o []: una cadena sin invisibles ni formas de compatibilidad
    (NFKC), sin literales sin cerrar, con las condiciones unidas solo con «and» (ni «or» ni «not») y serviceName,
    productName y armRegionName solo como «campo eq '…'» (ni contains, ni ne, ni tolower): así ninguna otra condición
    puede ampliar el precio a otro servicio u otra región."""
    if not isinstance(filtro, str):
        return ["no es una cadena"]
    _, trozos, cerrado = _literales_filtro(filtro)
    plano = "".join(ch for ch in unicodedata.normalize("NFKC", filtro) if unicodedata.category(ch) != "Cf")
    motivos = [] if plano == filtro else ["lleva caracteres invisibles o de compatibilidad que la API no casa"]
    motivos += [] if cerrado else ["tiene un literal sin cerrar"]
    conectores = sorted({m.group(0).lower() for t in trozos for m in _CONECTOR_NO_ADMITIDO.finditer(t)})
    if conectores:
        motivos.append(f"usa {' y '.join(f'«{c}»' for c in conectores)}: las condiciones solo se unen con «and»")
    for campo in CAMPOS_FILTRO:
        apariciones = sum(len(re.findall(r"(?<!\w)" + campo + r"(?!\w)", t, re.IGNORECASE)) for t in trozos)
        if apariciones > len(valores_filtro(filtro, campo)):
            motivos.append(f"usa {campo} fuera de la forma «{campo} eq '…'»")
    return motivos


def precios_auxiliares(catalogo: dict) -> list[dict]:
    """Lista blanca del catálogo: serviceName de servicios auxiliares sin componente propio (p. ej. «Azure Private
    Link»). Solo valen como precio auxiliar de un componente con catalogo_id y nunca identifican un servicio."""
    return [a for a in (catalogo or {}).get("precios_auxiliares") or [] if isinstance(a, dict)]


def _lista(valores: list) -> str:
    return ", ".join(f"«{v}»" for v in valores if isinstance(v, str) and v) or "ninguno"


# REV15-1 y REV15-3 (I1.6): el precio auxiliar va ligado a un componente y a una plantilla suya. Contrato del catálogo
# (papel E, INT15-3): `componentes` (catalogo_ids a los que puede acompañar) y `plantillas_de` + `plantillas` (ids de las
# plantillas de esa fila, que fija la región con region_precio). Sin esos datos, falla cerrado. Nunca cubre al componente.
def plantillas_auxiliar(auxiliar: dict, catalogo: dict) -> tuple[list[dict], dict]:
    """(plantillas, fila) del precio auxiliar: las de la fila `plantillas_de` con los ids `plantillas`; ([], {}) si la
    referencia no resuelve entera."""
    fila = next((e for e in _entradas(catalogo) if e.get("id") == auxiliar.get("plantillas_de")), None)
    ids = [i for i in auxiliar.get("plantillas") or [] if isinstance(i, str)]
    por_id = {p.get("id"): p for p in (fila or {}).get("plantillas_precio") or [] if isinstance(p, dict)}
    if fila is None or not ids or set(ids) - set(por_id):
        return [], {}
    return [por_id[i] for i in ids], fila


def auxiliar_de_filtro(filtro: object, region: object, catalogo: dict) -> dict | None:
    """El precio auxiliar del catálogo una de cuyas plantillas es EXACTAMENTE `filtro` (en `region`); None si ninguno."""
    for a in precios_auxiliares(catalogo):
        plantillas, fila = plantillas_auxiliar(a, catalogo)
        if isinstance(filtro, str) and any(_filtro_de_plantilla(p, fila, region) == filtro for p in plantillas):
            return a
    return None


def problemas_auxiliar(filtro: object, auxiliar: dict, entrada: dict, region: object, catalogo: dict) -> list[str]:
    """Motivos por los que el precio auxiliar no puede ir en el componente de `entrada` (en `region`); [] si puede."""
    nombre = f"{entrada.get('nombre_oficial')} ({entrada.get('id')})"
    servicio = auxiliar.get("service_name")
    componentes = [x for x in auxiliar.get("componentes") or [] if isinstance(x, str)]
    motivos = []
    if entrada.get("id") not in componentes:
        lista = ", ".join(componentes) or "ninguno: el catálogo montado no lo declara"
        motivos.append(f"el precio auxiliar «{servicio}» no acompaña a {nombre} (acompaña a: {lista}); un auxiliar va "
                       "en el componente al que sirve y nunca sustituye a su precio propio")
    plantillas, fila = plantillas_auxiliar(auxiliar, catalogo)
    if not plantillas:
        motivos.append(f"el catálogo montado no trae plantillas de filtro para el precio auxiliar «{servicio}»: no se "
                       "puede comprobar (falla cerrado)")
    elif not any(_filtro_de_plantilla(p, fila, region) == filtro for p in plantillas):
        motivos.append(f"el filtro no es el de ninguna plantilla del precio auxiliar «{servicio}»: cópiala carácter a "
                       "carácter")
    return motivos



def _filtro_de_plantilla(plantilla: object, entrada: dict, region: object) -> str | None:
    """I1.5 (CAMBIOS-I15-E; réplica de catalogo.plantillas_precio.filtro_para_region): el filtro de la plantilla para un
    componente en `region`. Con region_precio («Global») no cambia; si no, solo el valor de armRegionName."""
    f = plantilla.get("filtro") if isinstance(plantilla, dict) else None
    if not isinstance(f, str) or entrada.get("region_precio"):
        return f
    if not isinstance(region, str) or not re.fullmatch(r"[a-z]+[a-z0-9]*", region) or region == "global":
        return None
    base = entrada.get("region_ue")
    return f.replace(f" and armRegionName eq '{base}' and ", f" and armRegionName eq '{region}' and ", 1)

def problemas_precio(precio: dict, entrada: dict, region: object, catalogo: dict) -> list[str]:
    """Motivos por los que el filtro del precio no casa ENTERO con `entrada` (el servicio del catalogo_id de su
    componente, desplegado en `region`); [] si casa. Lista blanca: cualquier valor desconocido se rechaza."""
    filtro = precio.get("filtro") if isinstance(precio, dict) else None
    leidos = {campo: list(dict.fromkeys(valores_filtro(filtro, campo))) for campo in CAMPOS_FILTRO}
    nombre = f"{entrada.get('nombre_oficial')} ({entrada.get('id')})"
    propio = entrada.get("service_name_precios")
    auxiliar = next((a for a in precios_auxiliares(catalogo)
                     if isinstance(a.get("service_name"), str) and leidos["serviceName"] == [a.get("service_name")]),
                    None)
    motivos = forma_filtro(filtro)
    es_propio = isinstance(propio, str) and leidos["serviceName"] == [propio]
    exacto = None if es_propio else auxiliar_de_filtro(filtro, region, catalogo)
    if exacto is not None:  # I1.6: el filtro es una plantilla de un auxiliar: solo falta que acompañe al componente
        return motivos + problemas_auxiliar(filtro, exacto, entrada, region, catalogo)
    if es_propio:
        productos, region_precio = [entrada.get("producto_precios")], entrada.get("region_precio")
    elif auxiliar is not None:
        productos, region_precio = list(auxiliar.get("productos") or []), auxiliar.get("region_precio")
        motivos += problemas_auxiliar(filtro, auxiliar, entrada, region, catalogo)
    else:
        admitidos = _lista([propio] + [a.get("service_name") for a in precios_auxiliares(catalogo)])
        return motivos + [f"serviceName {_lista(leidos['serviceName'])} no es el de {nombre} ni un precio auxiliar "
                          f"del catálogo (admite exactamente uno de: {admitidos}): el precio y el componente hablan de "
                          "servicios distintos; asocia cada precio al componente de su servicio o corrige el catalogo_id"]
    for v in leidos["productName"]:
        if v not in [p for p in productos if isinstance(p, str) and p]:
            lista = _lista(productos)
            motivos.append(f"productName «{v}» no es de {nombre} (admite "
                           f"{'ninguno: quita el productName' if lista == 'ninguno' else lista})")
    compartido = sum(e.get("service_name_precios") == propio for e in _entradas(catalogo)) > 1
    if es_propio and compartido and entrada.get("producto_precios") and not leidos["productName"]:
        motivos.append(f"serviceName «{propio}» lo comparten varios servicios del catálogo: el filtro exige el "
                       f"productName de {nombre} («{entrada.get('producto_precios')}»)")
    esperada = region_precio or region
    if not region_precio and region == "global":
        motivos.append(f"{nombre} se factura por región en Retail Prices: un componente con precio no va en «global»; "
                       "pon la región donde se despliega")
    elif len(leidos["armRegionName"]) != 1:
        motivos.append(f"lleva {len(leidos['armRegionName'])} armRegionName distintos y exige exactamente uno: "
                       f"«{esperada}»")
    elif leidos["armRegionName"][0] != esperada:
        de = f"la región de precio de {nombre} en el catálogo" if region_precio else "la región del componente"
        motivos.append(f"armRegionName «{leidos['armRegionName'][0]}» no es «{esperada}» ({de})")
    # I1.5 (decisión 1 del comercial, CAMBIOS-I15-E): con plantillas en el catálogo, el filtro es EXACTAMENTE una.
    plantillas = (entrada.get("plantillas_precio") or []) if es_propio else []
    if es_propio and not plantillas:  # falla cerrado: sin plantillas en el catálogo montado no hay con qué comprobar
        motivos.append(f"el catálogo montado no trae plantillas de filtro de precio para {nombre}: el precio no se "
                       "puede comprobar (catálogo sin derivar con el esquema del sandbox de I1.5)")
    elif es_propio and not motivos and not any(_filtro_de_plantilla(p, entrada, region) == filtro
                                               for p in plantillas):  # integrador I1.5: el auxiliar no lleva plantillas
        motivos.append(f"el filtro no es el de ninguna plantilla de {nombre} en el catálogo: copia el prefijo de su "
                       "fila y el resto de una plantilla, carácter a carácter (solo cambia armRegionName si la región "
                       "del componente es otra y la fila no la fija)")
    return motivos


def incoherencias_servicio(comp: dict, catalogo: dict, precios: list | None = None) -> list[str]:
    """Motivos de rechazo de los precios del componente: si tiene alguno, exige un catalogo_id del catálogo (un
    servicio fuera del catálogo va sin precio y lo cotiza el revisor), y cada filtro tiene que casar entero con el
    servicio de ese catalogo_id (problemas_precio). [] si no tiene precios o si todos casan."""
    propios = [p for p in precios or [] if isinstance(p, dict) and p.get("componente_id") == comp.get("id")]
    if not propios:
        return []
    entrada = next((e for e in _entradas(catalogo) if e.get("id") == comp.get("catalogo_id")), None)
    if entrada is None:
        return [f"tiene precio ({', '.join(str(p.get('id')) for p in propios)}) y no lleva un catalogo_id del "
                "catálogo: todo componente con precio lleva el catalogo_id de su servicio; un servicio que no está "
                "en el catálogo va sin precio, con un supuesto, y lo cotiza el revisor"]
    return list(dict.fromkeys(f"el precio {p.get('id')}: {m}" for p in propios
                              for m in problemas_precio(p, entrada, comp.get("region"), catalogo)))


# ── I1.6 · decisión 4 del comercial (LES-G-100): concepto, volumen y niveles ──────────────────────────────────────────
# Contrato común con el catálogo (papel E, catalogo/plantillas_precio.py): cada plantilla lleva `impulsor` («tiempo» o
# «volumen») y `divisor` (entero ≥ 1, el de la unidad del medidor: 1, 1000 para «1K», 10000 para «10K», 1000000 para
# «1M»; 1 en las de tiempo) y su concepto (`concepto`, o `comprobacion` con medidor, producto y sku y
# `concepto_con_sku`). Un servicio con niveles lleva `niveles`: [{nivel, plantillas, limites, fuente_url, consultado}].
# Lo que falte en el catálogo montado falla cerrado (LES-G-098.3).
IMPULSORES = ("tiempo", "volumen")
TOLERANCIA_RELATIVA, TOLERANCIA_ABSOLUTA = Decimal("0.005"), Decimal("0.01")  # redondeo de cantidad_mensual
MARCA_ASUMIDO = " [ASUMIDO, confianza baja]"  # la que pone brief._valor a un campo ASUMIDO


def _entrada_de(comp: object, catalogo: dict) -> dict | None:
    cid = comp.get("catalogo_id") if isinstance(comp, dict) else None
    return next((e for e in _entradas(catalogo) if cid and e.get("id") == cid), None)


def divisor_de(plantilla: object) -> int | None:
    """`divisor` de la plantilla: entero ≥ 1 (ni booleano ni decimal) y 1 si su impulsor es «tiempo»; None si no."""
    v = plantilla.get("divisor") if isinstance(plantilla, dict) else None
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        return None
    return v if plantilla.get("impulsor") != "tiempo" or v == 1 else None


def concepto_de_plantilla(plantilla: object) -> str | None:
    """Concepto del precio que fija el código (VER15-3, REVERIF15-2), en este orden: el `concepto` de la plantilla; el
    que sale de su `comprobacion` como lo deriva catalogo.plantillas_precio.concepto (medidor; con `concepto_con_sku`,
    «medidor (sku)»; con medidor de menos de 3 caracteres, «medidor (producto)»); o su meterName si tiene 3 caracteres o
    más y no pide el sku. None si no se puede fijar (catálogo sin derivar con I1.6): falla cerrado."""
    if not isinstance(plantilla, dict):
        return None
    propio = plantilla.get("concepto")
    if isinstance(propio, str) and 3 <= len(" ".join(propio.split())) <= 160:
        return " ".join(propio.split())
    k = plantilla.get("comprobacion") if isinstance(plantilla.get("comprobacion"), dict) else {}
    medidor = k.get("medidor") if isinstance(k.get("medidor"), str) else ""
    con_sku = bool(plantilla.get("concepto_con_sku"))
    extra = k.get("sku") if con_sku else None if len(medidor) >= 3 else k.get("producto")
    if medidor and (extra or (not con_sku and len(medidor) >= 3)):
        return f"{medidor} ({extra})" if extra else medidor
    medidores = list(dict.fromkeys(valores_filtro(plantilla.get("filtro"), "meterName")))
    return medidores[0] if not con_sku and len(medidores) == 1 and len(medidores[0]) >= 3 else None


def plantilla_de_precio(precio: object, comp: object, catalogo: dict) -> dict | None:
    """{"plantilla", "auxiliar", "fila"}: la plantilla cuyo filtro, en la región del componente, es EXACTAMENTE el del
    precio, de la fila del servicio del componente o de un precio auxiliar que lo acompaña; None si no hay."""
    entrada = _entrada_de(comp, catalogo)
    filtro = precio.get("filtro") if isinstance(precio, dict) else None
    if entrada is None or not isinstance(filtro, str):
        return None
    servicios = list(dict.fromkeys(valores_filtro(filtro, "serviceName")))
    if servicios == [entrada.get("service_name_precios")]:
        filas = [(entrada.get("plantillas_precio") or [], entrada, False)]
    else:
        filas = [(*plantillas_auxiliar(a, catalogo), True) for a in precios_auxiliares(catalogo)
                 if entrada.get("id") in (a.get("componentes") or [])]
    for plantillas, fila, auxiliar in filas:
        for p in plantillas:
            if isinstance(p, dict) and _filtro_de_plantilla(p, fila, comp.get("region")) == filtro:
                return {"plantilla": p, "auxiliar": auxiliar, "fila": fila}
    return None


def precio_propio(precio: object, comp: object, catalogo: dict) -> bool:
    """El precio es del servicio del componente (su serviceName es el service_name_precios de su catalogo_id): solo
    esos cubren al componente (REV15-1). Sin catalogo_id del catálogo, True (respuestas anteriores a I1.2)."""
    entrada = _entrada_de(comp, catalogo)
    if entrada is None:
        return True
    filtro = precio.get("filtro") if isinstance(precio, dict) else None
    return list(dict.fromkeys(valores_filtro(filtro, "serviceName"))) == [entrada.get("service_name_precios")]


def fijar_conceptos(resp: dict, catalogo: dict) -> tuple[dict, list[dict], list[str]]:
    """(copia de la respuesta con el `concepto` de cada precio fijado desde su plantilla, sustituciones, errores).

    Equivalencia demostrable (LES-G-047): el concepto sale del filtro, que ya es exactamente una plantilla. Un precio
    sin plantilla se deja como está (otro error lo rechaza). Sustitución = el modelo trajo un texto no vacío distinto
    (sin contar espacios): {"precio_id", "plantilla", "recibido" (160 caracteres como mucho), "fijado"}; va a la nota.
    Error = la plantilla no permite fijar el concepto (catálogo montado sin `concepto` para un meterName corto)."""
    copia = json.loads(json.dumps(resp, ensure_ascii=False))
    comps = {c.get("id"): c for c in copia.get("componentes") or [] if isinstance(c, dict)}
    sustituciones, errores = [], []
    for p in copia.get("precios") or []:
        if not isinstance(p, dict):
            continue
        info = plantilla_de_precio(p, comps.get(p.get("componente_id")), catalogo)
        if info is None:
            continue
        fijado = concepto_de_plantilla(info["plantilla"])
        if fijado is None:
            errores.append(f"precios.{p.get('id')}: la plantilla «{info['plantilla'].get('id')}» del catálogo montado no "
                           "permite fijar el concepto (meterName de menos de 3 caracteres y sin «concepto»): catálogo "
                           "sin derivar con I1.6")
            continue
        recibido = p.get("concepto")
        if isinstance(recibido, str) and recibido.strip() and " ".join(recibido.split()) != fijado:
            sustituciones.append({"precio_id": p.get("id"), "plantilla": info["plantilla"].get("id"),
                                  "recibido": recibido[:160], "fijado": fijado})
        p["concepto"] = fijado
    return copia, sustituciones, errores


def _plano_req(texto: object) -> str:
    """NFC y espacios colapsados: así se compara una cita con su requisito (la anonimización del brief los colapsa)."""
    return " ".join(unicodedata.normalize("NFC", texto).split()) if isinstance(texto, str) else ""


# Etiquetas de las líneas de requisitos del brief (brief.generar); lo que va tras «Etiqueta: » son valores con «; ».
_ETIQUETAS_BRIEF = ("Objetivo", "Nubes", "Ubicación de los usuarios finales", "Marco normativo") + tuple(
    e for _, e in brief_mod.ETIQUETAS_CONTEXTO)
_FIN_REQUISITOS = ("## Comentarios de la revisión", "## Correcciones solicitadas", "## Elementos ya verificados",
                   "## Precios ya verificados", "## Precios conservados",  # I1.7 (CAMBIOS-I17-R §2.4)
                   "## Elementos sin verificar", "## Propuesta de la versión")  # PR17-6 (arreglos I1.7)


def _lineas_requisitos(brief_texto: object) -> list[str]:
    """Líneas del cuerpo del brief hasta la primera sección que no es de requisitos (DEVUELTA, correcciones, conservar)."""
    texto = brief_texto if isinstance(brief_texto, str) else ""
    cuerpo = texto.split("\n---\n", 1)[1] if "\n---\n" in texto else texto
    salida = []
    for ln in cuerpo.split("\n"):
        if ln.startswith(_FIN_REQUISITOS):
            break
        salida.append(ln)
    return salida


def volumetria_del_brief(brief_texto: object) -> tuple[list[str], bool] | None:
    """(valores de la línea «Volumetría: …» del brief, ASUMIDO); None si el brief no la trae."""
    for ln in _lineas_requisitos(brief_texto):
        if ln.startswith("Volumetría: "):
            valor = ln[len("Volumetría: "):]
            asumido = valor.endswith(MARCA_ASUMIDO)
            return (valor[:-len(MARCA_ASUMIDO)] if asumido else valor).split("; "), asumido
    return None


def _campos_req(requisitos: object) -> dict:
    """requisitos.campos, o {} si no es un objeto (un paquete forjado nunca lanza una excepción)."""
    return _objeto(_objeto(requisitos).get("campos"))


def _entradas_req(requisitos: object, campo: str | None = None) -> list[dict]:
    campos = _campos_req(requisitos)
    nombres = [campo] if campo else list(campos)
    listas = [_objeto(campos.get(k)).get("entradas") for k in nombres]
    return [e for x in listas if isinstance(x, list) for e in x if isinstance(e, dict)]


def estado_volumetria(requisitos: object, brief_texto: object) -> str:
    """CITADO, ASUMIDO o FALTA: el de requisitos.campos.volumetria si lo traen; si no (sin requisitos o sin ese campo,
    Revisión I1.6), el que dice el brief (sin la marca de ASUMIDO, CITADO; sin la línea, FALTA)."""
    campo = _campos_req(requisitos).get("volumetria")
    if isinstance(campo, dict) and campo.get("estado"):
        return campo["estado"]
    vb = volumetria_del_brief(brief_texto)
    return "FALTA" if vb is None else "ASUMIDO" if vb[1] else "CITADO"


def citas_volumetria(requisitos: object, brief_texto: object) -> list[str]:
    """Textos que vale como base_volumen.cita: el valor de cada entrada de la volumetría y, si casan uno a uno, los
    valores de la línea «Volumetría» del brief (anonimizados: «entre 50 y 100 técnicos» por «60 técnicos»)."""
    entradas = [e.get("valor") for e in _entradas_req(requisitos, "volumetria")]
    salida = [_plano_req(v) for v in entradas]
    vb = volumetria_del_brief(brief_texto)
    if vb and (not isinstance(requisitos, dict) or len(vb[0]) == len(entradas)):
        salida += [_plano_req(s) for s in vb[0]]
    return [s for s in dict.fromkeys(salida) if s]


def citas_requisitos(requisitos: object, brief_texto: object) -> list[str]:
    """Textos que vale como justificacion_nivel.requisito: el valor de cualquier entrada de los requisitos y cada valor
    de las líneas de requisitos del brief (sin guion, etiqueta ni marca de ASUMIDO, entero y partido por «; »)."""
    salida = [_plano_req(e.get("valor")) for e in _entradas_req(requisitos)]
    for ln in _lineas_requisitos(brief_texto):
        if not ln.strip() or ln.startswith("#"):
            continue
        t = ln[2:] if ln.startswith("- ") else ln
        t = next((t[len(e) + 2:] for e in _ETIQUETAS_BRIEF if t.startswith(e + ": ")), t)
        t = t[:-len(MARCA_ASUMIDO)] if t.endswith(MARCA_ASUMIDO) else t
        salida += [_plano_req(t)] + [_plano_req(s) for s in t.split("; ")]
    return [s for s in dict.fromkeys(salida) if s]


_NUMERO = re.compile(r"\d[\d.,]*\d|\d")


def leer_numero(tok: str) -> Decimal | None:
    """Un número escrito en español: «3.000» es 3000, «1,5» es 1.5 y «2.5» es 2.5; «1,000,000» no se lee (None)."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", tok) or re.fullmatch(r"\d+(?:,\d+)?", tok):
        return Decimal(tok.replace(".", "").replace(",", "."))
    return Decimal(tok) if re.fullmatch(r"\d+\.\d+", tok) else None


def numeros_en(texto: object) -> list[Decimal]:
    """Números de un texto en español (leer_numero), en orden."""
    return [d for tok in _NUMERO.findall(texto if isinstance(texto, str) else "") if (d := leer_numero(tok)) is not None]


def cantidad_con_su_unidad(cita: object, cantidad: object, palabras: list) -> bool:
    """REV17-7 (I1.8): `cantidad` es un número de la cita seguido de una palabra de su unidad (raíz de una palabra de 4
    letras o más de `palabras`) antes del siguiente número; si tras el número no queda ninguna palabra («documentos:
    3.000»), vale la que lo precede desde el número anterior. En «Unas 2.000 consultas al mes de 100 técnicos.», 2.000
    son consultas y 100 no lo son."""
    objetivo = _dec(cantidad)
    return objetivo is not None and objetivo in numeros_con_unidad(cita, palabras)


_MILLARES_ESPACIO = re.compile(r"(?<![\d.,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)")


def _sin_espacios_de_millar(m: re.Match) -> str:
    """Cada separador pasa a punto («1 200» → «1.200»); si sigue un decimal con punto («1 200.5»), se quitan («1200.5»),
    que es como leer_numero entiende ese decimal."""
    sigue_decimal = re.match(r"\.\d", m.string[m.end():m.end() + 2]) is not None
    return re.sub(r"[ \u00a0\u202f]", "" if sigue_decimal else ".", m.group(0))


def millares_con_espacio(texto: str) -> str:
    """ARR1 (Revisión, I1.10): «1 200 GB» (separador de millares con espacio, también el duro y el estrecho, como recomienda
    la RAE) se lee 1.200 y no 200; «1 200.5 GB», 1200,5."""
    return _MILLARES_ESPACIO.sub(_sin_espacios_de_millar, texto)


VENTANA_UNIDAD = 3  # I1.9 (Revisión E1): en un umbral, la unidad va en las 3 palabras que siguen al número (o preceden)


def numeros_con_unidad(cita: object, palabras: list, cortas: object = (), ventana: int | None = None) -> list[Decimal]:
    """Números de la cita que van con una palabra de su unidad (la regla de cantidad_con_su_unidad), en orden. I1.9: la
    misma lectura decide si una cita de volumetría supera el umbral de un nivel («200 gigabytes» frente a 45). `cortas`
    son formas cortas de la unidad que solo valen como palabra entera («GB»: el catálogo las da en unidad_corta).
    `ventana` (I1.9, umbral): solo cuentan las `ventana` palabras que siguen al número (o, si no le sigue ninguna, las
    que lo preceden): «46 consultas al mes; el almacenamiento, en GB» no lee 46 GB. Sin ventana, la regla de I1.8."""
    texto = cita if isinstance(cita, str) else ""
    raices = [_raiz(t) for w in palabras if isinstance(w, str) for t in _tokens(w) if len(t) >= 4]
    exactas = {t for w in cortas or () if isinstance(w, str) for t in _tokens(w)}
    if not raices and not exactas:
        return []
    texto = millares_con_espacio(texto)
    marcas, salida = list(_NUMERO.finditer(texto)), []
    for k, m in enumerate(marcas):
        n = leer_numero(m.group(0))
        if n is None:
            continue
        despues = _tokens(texto[m.end():marcas[k + 1].start() if k + 1 < len(marcas) else len(texto)])
        antes = _tokens(texto[marcas[k - 1].end() if k else 0:m.start()])
        if ventana is not None:
            despues, antes = despues[:max(ventana, 0)], antes[max(len(antes) - max(ventana, 0), 0):]
        cerca = despues or antes
        if any(_raiz(t).startswith(r) for t in cerca for r in raices) or set(cerca) & exactas:
            salida.append(n)
    return salida


def palabras_de_base(info: dict | None, base: dict, catalogo: dict) -> list:
    """Palabras de la unidad que cuenta la base: las `base` del factor estándar de la plantilla si las declara; si no,
    la unidad_base que escribió el experto (la misma elección que base_casa en _volumen)."""
    std = factor_por_base(info, catalogo, base.get("cita"), base.get("unidad_base"))[0] if info else None  # E19-2
    return list(std["bases"]) if std and std["bases"] else [base.get("unidad_base")]


def _dec(x: object) -> Decimal | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        d = Decimal(str(x))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _objeto(x: object) -> dict:
    """El dict, o {} si no lo es (un paquete forjado puede traer texto donde va un objeto: nunca una excepción)."""
    return x if isinstance(x, dict) else {}


def cantidad_esperada(base: dict, divisor: int) -> Decimal | None:
    """cantidad_base × factor.valor / divisor, en Decimal; None si falta un número."""
    base = _objeto(base)
    b, f = _dec(base.get("cantidad_base")), _dec(_objeto(base.get("factor")).get("valor"))
    return None if b is None or f is None or not divisor else b * f / Decimal(divisor)


def cuadra(cantidad: object, esperada: Decimal) -> bool:
    """|cantidad − esperada| ≤ máx(0,01; 0,5 % de la esperada): solo admite el redondeo."""
    c = _dec(cantidad)
    return c is not None and abs(c - esperada) <= max(TOLERANCIA_ABSOLUTA, abs(esperada) * TOLERANCIA_RELATIVA)


def niveles_de(entrada: object) -> list[dict]:
    """Niveles del servicio en el catálogo: [{"nombres", "plantillas" (None si no las dice), "limites", "fuente",
    "obligatorios" (I1.8: medidores obligatorios del nivel), "instancias_max" (I1.8: entero ≥ 1, None si no lo declara;
    un valor declarado que no es entero ≥ 1 es False y falla cerrado), "instancias_min" (I1.8, N5: igual) e
    "instancias_validas" (I1.8, N5: lista de enteros ≥ 1, None si no la declara, False si no es válida)}]."""
    salida = []
    for n in (entrada.get("niveles") if isinstance(entrada, dict) else None) or []:
        if not isinstance(n, dict):
            continue
        limites = n.get("limites") if isinstance(n.get("limites"), list) else []
        limites = limites + [n.get(k) for k in ("limite_oficial", "limite") if isinstance(n.get(k), str)]
        plantillas, tope = n.get("plantillas"), n.get("instancias_max")
        valido = isinstance(tope, int) and not isinstance(tope, bool) and tope >= 1
        minimo, validas = n.get("instancias_min"), n.get("instancias_validas")
        min_ok = isinstance(minimo, int) and not isinstance(minimo, bool) and minimo >= 1
        val_ok = isinstance(validas, list) and bool(validas) and all(
            isinstance(x, int) and not isinstance(x, bool) and x >= 1 for x in validas)
        salida.append({"nombres": [_plano_req(n.get(k)) for k in ("id", "nivel", "nombre") if isinstance(n.get(k), str)],
                       "etiqueta": next((_plano_req(n.get(k)) for k in ("nivel", "nombre", "id") if isinstance(n.get(k), str)),
                                        ""),
                       "plantillas": set(plantillas) if isinstance(plantillas, list) else None,
                       "limites": [_plano_req(x) for x in limites if isinstance(x, str) and x.strip()],
                       "fuente": n.get("fuente_url") if isinstance(n.get("fuente_url"), str) else n.get("fuente"),
                       "obligatorios": [x for x in n.get("medidores_obligatorios") or [] if isinstance(x, str)]
                       if isinstance(n.get("medidores_obligatorios"), list) else [],
                       "instancias_max": None if tope is None else tope if valido else False,
                       "instancias_min": None if minimo is None else minimo if min_ok else False,
                       "instancias_validas": None if validas is None else validas if val_ok else False,
                       "razones": razones_validas(n.get("razones_subida"))})
    return salida


def razones_validas(lista: object) -> list[dict] | bool:
    """I1.9 (VC18-1, PR18-3; decisión del PM): las razones de subida de un nivel (o de un modelo) del catálogo, ya
    normalizadas; [] si no declara ninguna y False si alguna está mal formada (falla cerrado: no se aplica a medias).
    Cada razón: `id`, `fuente` (URL https) y su `tipo`:
    - «umbral»: `campo` (de los requisitos, normalmente «volumetria»), `unidad` (texto o lista de palabras de 4 letras o
      más) y `limite` (número ≥ 0: el límite del nivel por defecto que hay que superar);
    - «caracteristica»: `palabras_clave` (lista no vacía) y, opcional, `campo`.
    `texto` (o `descripcion`), opcional, es la explicación para el revisor."""
    if lista is None:
        return []
    if not isinstance(lista, list):
        return False
    salida, ids = [], set()
    for r in lista:
        if not isinstance(r, dict):
            return False
        rid, fuente = _texto_no_vacio(r.get("id")), _texto_no_vacio(r.get("fuente")) or _texto_no_vacio(r.get("fuente_url"))
        if not rid or rid in ids or not fuente or not fuente.startswith("https://"):
            return False
        ids.add(rid)
        campo = r.get("campo")
        if campo is not None and campo not in CAMPOS_REQUISITOS:
            return False
        base = {"id": rid, "tipo": r.get("tipo"), "campo": campo, "fuente": fuente,
                "texto": _texto_no_vacio(r.get("texto")) or _texto_no_vacio(r.get("descripcion"))}
        if r.get("tipo") == "umbral":
            unidad, limite = r.get("unidad"), _dec(r.get("limite"))
            palabras = [unidad] if isinstance(unidad, str) else unidad
            if campo is None or limite is None or limite < 0 or not isinstance(palabras, list) or not palabras or not all(
                    isinstance(w, str) and any(len(t) >= 4 for t in _tokens(w)) for w in palabras):
                return False
            cortas = r.get("unidad_corta")
            if cortas is not None and (not isinstance(cortas, list) or not all(
                    isinstance(w, str) and _tokens(w) for w in cortas)):
                return False
            # VC19-1 (I1.10): `por_instancia` (número > 0, opcional): la razón justifica instancias de su nivel, una por
            # cada `por_instancia` unidades citadas (AI Search Basic: una partición por cada 15 GB)
            por = r.get("por_instancia")
            por_dec = _dec(por) if por is not None else None
            if por is not None and (isinstance(por, bool) or por_dec is None or por_dec <= 0):
                return False
            salida.append({**base, "palabras": list(palabras), "cortas": list(cortas or []), "limite": limite,
                           "limite_json": r.get("limite"), "por_instancia": por_dec})
        elif r.get("tipo") == "caracteristica":
            claves = r.get("palabras_clave")
            if not isinstance(claves, list) or not claves or not all(
                    isinstance(w, str) and _compacto(w) for w in claves) or r.get("por_instancia") is not None:
                return False
            salida.append({**base, "palabras_clave": list(claves)})
        else:
            return False
    return salida


def mayor_con_unidad(razon: dict, cita: object) -> Decimal | None:
    """VC19-1 (I1.10): el mayor número de la cita que va con la unidad de una razón «umbral»; None si no hay ninguno."""
    nums = numeros_con_unidad(cita, razon["palabras"], razon.get("cortas"), VENTANA_UNIDAD)
    return max(nums) if nums else None


def instancias_necesarias(razon: dict, cita: object) -> int | None:
    """VC19-1: instancias que exige una razón con `por_instancia` para la cita: techo(mayor número ÷ por_instancia);
    None si la razón no lo declara o la cita no trae un número con su unidad."""
    mayor = mayor_con_unidad(razon, cita) if razon.get("por_instancia") else None
    if mayor is None:
        return None
    return int((mayor / razon["por_instancia"]).to_integral_value(rounding=ROUND_CEILING))  # Decimal: // trunca


def razon_cumplida(razon: dict, cita: object) -> bool:
    """I1.9: la cita cumple la razón, comprobado por código: «umbral», algún número de la cita que va con su unidad
    (numeros_con_unidad) es MAYOR que el límite del nivel por defecto; «caracteristica», la cita contiene una de las
    palabras clave como secuencia de palabras seguidas y sin negación cerca (afirmada: «no se necesita red privada»,
    «no creemos que necesiten una red privada» o «Punto de conexión privado: no requerido» no justifican la red privada;
    una negación parafraseada o lejana no se detecta: lo ve el revisor en la nota)."""
    if razon.get("tipo") == "umbral":
        return any(n > razon["limite"] for n in numeros_con_unidad(cita, razon["palabras"], razon.get("cortas"),
                                                                    VENTANA_UNIDAD))
    if razon.get("tipo") == "caracteristica":
        return any(afirmada(cita, w) for w in razon["palabras_clave"])
    return False


NEGACIONES = frozenset({"no", "sin", "ni", "nunca", "tampoco", "ningun", "ninguna", "ninguno", "jamas"})
NO_SOLO = frozenset({"solo", "solamente", "unicamente"})  # «no solo X» afirma X (Revisión I1.9)
NEGACION_TRAS = 3  # palabras tras la frase (en su oración) donde una negación la anula: «X: no requerido»
# E19-8: un signo de puntuación corta solo si le sigue un espacio o el fin («gpt-6.1-sol» o «1.500» no se parten)
_CLAUSULA = re.compile(r"[.,;:!?](?=\s|$)|[¡¿()\[\]\n]")
_ORACION = re.compile(r"[.;!?](?=\s|$)|[¡¿\n]")
# Revisión I1.9 (3): para la negación ANTERIOR los dos puntos no cortan («No se necesita: red privada.» no la afirma)
_CLAUSULA_NEG = re.compile(r"[.,;!?](?=\s|$)|[¡¿()\[\]\n]")


def _negaciones(toks: list) -> list[int]:
    """Índices de las negaciones de verdad (NEGACIONES salvo un «no» seguido de «solo»)."""
    return [k for k, t in enumerate(toks)
            if t in NEGACIONES and not (t == "no" and k + 1 < len(toks) and toks[k + 1] in NO_SOLO)]


def afirmada(texto: object, frase: object) -> bool:
    """`frase` aparece en `texto` como secuencia de palabras seguidas, sin una negación antes de ella en su misma
    cláusula (cortes en . , ; ! ? seguidos de espacio o fin, ¡ ¿ paréntesis, corchetes y saltos de línea; los dos puntos
    NO cortan: «No se necesita: red privada.» no la afirma) y sin una en las NEGACION_TRAS palabras que la siguen
    dentro de su oración (cortes en . ; ! ? seguidos de espacio o fin, ¡ ¿ y saltos de línea). «no solo» no niega."""
    alias = _compacto(frase)
    for oracion in _ORACION.split(texto if isinstance(texto, str) else ""):
        partes = [_tokens(p) for p in _CLAUSULA_NEG.split(oracion)]
        for j, toks in enumerate(partes):
            resto = [t for p in partes[j + 1:] for t in p]
            for i, fin in tramos_frase(toks, alias):
                antes = [k for k in _negaciones(toks) if k < i]
                tras = [k for k in _negaciones(toks[fin:] + resto) if k < NEGACION_TRAS]
                if not antes and not tras:
                    return True
    return False


def tramos_frase(toks: list, alias: str) -> list[tuple[int, int]]:
    """(inicio, fin) de cada aparición de `alias` (compacto) como secuencia de palabras seguidas; fin no incluido."""
    salida = []
    for i in range(len(toks)):
        acumulado = ""
        for j, p in enumerate(toks[i:], start=i + 1):
            acumulado += p
            if acumulado == alias:
                salida.append((i, j))
                break
            if not alias.startswith(acumulado):
                break
    return salida


def posiciones_frase(toks: list, alias: str) -> list[int]:
    """Índices de las palabras donde empieza `alias` (compacto) como secuencia de palabras seguidas (contiene_frase)."""
    salida = []
    for i in range(len(toks)):
        acumulado = ""
        for p in toks[i:]:
            acumulado += p
            if acumulado == alias:
                salida.append(i)
                break
            if not alias.startswith(acumulado):
                break
    return salida


def razones_modelo(catalogo: dict, modelo: object) -> list[dict] | bool:
    """I1.9 (VC18-5): razones de subida de un modelo que no es el por defecto: la unión, por id, de las `razones_subida`
    de las plantillas del catálogo con ese `modelo`; False si alguna está mal formada o un mismo id trae datos
    distintos (falla cerrado); [] si no declara ninguna."""
    vistas: dict = {}
    for e in _entradas(catalogo):
        for p in e.get("plantillas_precio") or []:
            if not isinstance(p, dict) or p.get("modelo") != modelo or "razones_subida" not in p:
                continue
            rs = razones_validas(p.get("razones_subida"))
            if rs is False:
                return False
            for r in rs:
                if r["id"] in vistas and vistas[r["id"]] != r:
                    return False
                vistas[r["id"]] = r
    return list(vistas.values())


def modelo_por_defecto(catalogo: dict) -> str | None:
    """I1.9 (VC18-5): el modelo por defecto del catálogo (`modelo_por_defecto.modelo`, gpt-6-luna); None si no lo
    declara (falla cerrado: entonces ningún modelo se puede valorar sin decir cuál es el por defecto)."""
    m = _objeto((catalogo or {}).get("modelo_por_defecto")).get("modelo")
    return m if isinstance(m, str) and m.strip() else None


def reglas_medidores_de(entrada: object) -> list:
    """I1.8 (N1, CAMBIOS-I18-E §3.3): reglas de medidores de la fila del catálogo, [{"si_usa", "exige", "exige_uno_de"}]
    con listas de ids de plantilla. Una regla mal formada (si_usa vacío, una lista que no es de textos o sin ninguna
    exigencia) va como False: no se aplica a medias y el componente de esa fila con precios propios falla cerrado."""
    salida: list = []
    for r in (entrada.get("reglas_medidores") if isinstance(entrada, dict) else None) or []:
        listas = {k: r.get(k) if isinstance(r, dict) else None for k in ("si_usa", "exige", "exige_uno_de")}
        ok = (isinstance(listas["si_usa"], list) and bool(listas["si_usa"])
              and all(v is None or isinstance(v, list) and all(isinstance(x, str) for x in v) for v in listas.values())
              and bool(listas["exige"] or listas["exige_uno_de"]))
        salida.append({k: list(v or []) for k, v in listas.items()} if ok else False)
    return salida


REMEDIO_VOLUMEN = ("pon en base_volumen la cita literal de una entrada de la volumetría del brief, el número que trae, "
                   "su unidad y el factor (valor, unidad y por qué), y cantidad_mensual = cantidad_base × factor.valor / "
                   "divisor de la plantilla (LES-G-100)")


def errores_volumen_nivel(resp: dict, brief_texto: object, requisitos: object, catalogo: dict) -> list[dict]:
    """Decisión 4 (I1.6, LES-G-100): [{"id", "regla", "detalle"}] en el orden de la respuesta; [] si cumple.
    Misma lógica en verificar_paquete.errores_volumen_nivel_replica (prueba de igualdad en tests/test_i16_p_puerta.py)."""
    comps = [c for c in resp.get("componentes") or [] if isinstance(c, dict)]
    por_id = {c.get("id"): c for c in comps}
    precios = [p for p in resp.get("precios") or [] if isinstance(p, dict)]
    estado_vol, citas_vol = estado_volumetria(requisitos, brief_texto), citas_volumetria(requisitos, brief_texto)
    salida: list[dict] = []

    def mal(i: object, regla: str, detalle: str) -> None:
        salida.append({"id": i, "regla": regla, "detalle": detalle})

    info = {id(p): plantilla_de_precio(p, por_id.get(p.get("componente_id")), catalogo) for p in precios}
    for p in precios:
        pid, comp, i = p.get("id"), por_id.get(p.get("componente_id")), info[id(p)]
        if comp is None or i is None:
            continue  # componente inexistente o filtro sin plantilla: ya es un error de arriba
        pl, cm, base = i["plantilla"], p.get("cantidad_mensual"), p.get("base_volumen")
        impulsor, divisor = pl.get("impulsor"), divisor_de(pl)
        if impulsor not in IMPULSORES or divisor is None:
            mal(pid, "plantilla_sin_impulsor", f"la plantilla «{pl.get('id')}» del catálogo montado no declara su "
                "impulsor («tiempo» o «volumen») y su divisor de unidad: no se puede comprobar la cantidad (falla "
                "cerrado; catálogo sin derivar con I1.6)")
            continue
        if cm is None:
            if i["auxiliar"]:
                mal(pid, "referencia_auxiliar", "un precio de referencia (cantidad_mensual null) es de una plantilla "
                    "del servicio del componente, no de un precio auxiliar")
            if comp.get("motivo_no_valoracion") != "depende_del_volumen":
                mal(pid, "referencia_sin_depende", f"cantidad_mensual null solo vale como precio unitario de referencia "
                    f"de un componente con motivo_no_valoracion «depende_del_volumen» ({comp.get('id')} declara "
                    f"«{comp.get('motivo_no_valoracion')}»): pon la cantidad mensual")
            if base is not None:
                mal(pid, "referencia_con_base", "un precio de referencia no suma: base_volumen va null")
            continue
        if impulsor == "tiempo":
            if base is not None:
                mal(pid, "base_en_tiempo", f"la plantilla «{pl.get('id')}» se factura por tiempo: base_volumen va null "
                    "y cantidad_mensual son las horas (o unidades de tiempo) del mes")
            continue
        if base is None:
            mal(pid, "volumen_sin_base", f"la plantilla «{pl.get('id')}» se factura por volumen y cantidad_mensual "
                f"{cm} no sale de ningún dato: {REMEDIO_VOLUMEN}; si la volumetría no está citada, "
                "«depende_del_volumen» con este precio y cantidad_mensual null")
            continue
        base = _objeto(base)
        cita = _plano_req(quitar_comillas(base.get("cita")))
        if cita not in citas_vol:
            mal(pid, "cita_no_literal", f"base_volumen.cita «{cita}» no es literal: copia una de estas, carácter a "
                f"carácter: {'; '.join(f'«{c}»' for c in citas_vol) or 'ninguna (el brief no trae volumetría)'}")
        elif _dec(base.get("cantidad_base")) not in numeros_en(cita):
            mal(pid, "cantidad_no_en_cita", f"base_volumen.cantidad_base {base.get('cantidad_base')} no es un número de "
                f"la cita «{cita}» (números: {', '.join(str(n) for n in numeros_en(cita)) or 'ninguno'})")
        elif not cantidad_con_su_unidad(cita, base.get("cantidad_base"), palabras := palabras_de_base(
                {**i, "clave": clave_plantilla(i["fila"], pl)}, base, catalogo)):
            mal(pid, "cantidad_sin_su_unidad", f"base_volumen.cantidad_base {base.get('cantidad_base')} no es el número de "
                f"la cita «{cita}» que cuenta la unidad de la base ({', '.join(map(str, palabras))}): pon el número que "
                "va junto a esa palabra (REV17-7)")
        esperada = cantidad_esperada(base, divisor)
        if esperada is None:
            mal(pid, "cuenta_no_cuadra", "base_volumen sin números válidos: no se puede rehacer la cuenta")
        elif not cuadra(cm, esperada):
            mal(pid, "cuenta_no_cuadra", f"cantidad_mensual {cm} no es cantidad_base × factor.valor / {divisor} = "
                f"{esperada.normalize():f} (solo se admite el redondeo)")
    for c in comps:
        cid, entrada, jn = c.get("id"), _entrada_de(c, catalogo), c.get("justificacion_nivel")
        jn = jn if jn is None else _objeto(jn)
        if es_existente(c):
            continue  # I1.9 (PR18-1): un recurso del cliente no se valora ni justifica nivel (errores_existentes)
        if c.get("motivo_no_valoracion") == "depende_del_volumen":
            if estado_vol == "CITADO":
                mal(cid, "depende_con_volumetria_citada", "«depende_del_volumen» solo vale si la volumetría no está "
                    f"citada, y en este brief lo está: valora el componente con ella; {REMEDIO_VOLUMEN}")
            if not any(p.get("componente_id") == cid and p.get("cantidad_mensual") is None and info[id(p)] is not None
                       and not info[id(p)]["auxiliar"] for p in precios):
                mal(cid, "depende_sin_precio_unitario", "«depende_del_volumen» exige al menos un precio unitario de "
                    "referencia de una plantilla del componente, con cantidad_mensual null (no suma al total)")
        propios = [(p, info[id(p)]["plantilla"]) for p in precios if p.get("componente_id") == cid
                   and info[id(p)] is not None and not info[id(p)]["auxiliar"]]
        propias = [pl.get("id") for _, pl in propios]
        niveles = niveles_de(entrada)
        # PR17-3 (arreglos I1.7): cubrir el componente con cualquier precio no basta (VER17-1: Storage valorado solo por
        # escrituras y la capacidad, que es lo que más pesa, sin valorar ni motivo). Con algún precio propio, los
        # medidores obligatorios de su fila tienen que estar (con cantidad, o de referencia si depende del volumen).
        # I1.8 (REVERIF17-2): también los de cada nivel cuyas plantillas usa (Service Bus Standard frente a Premium).
        obligatorios = [x for x in ((entrada or {}).get("medidores_obligatorios") or []) if isinstance(x, str)]
        obligatorios += [x for n in niveles if n["plantillas"] and set(propias) & n["plantillas"] for x in n["obligatorios"]]
        faltan = [x for x in dict.fromkeys(obligatorios) if x not in propias] if propias else []
        # I1.8 (N1): reglas de medidores de la fila, sobre las líneas VALORADAS (las que suman: un precio de referencia
        # no infravalora nada): si una usa alguna plantilla de «si_usa», van valoradas todas las de «exige» (entrada y
        # salida del mismo modelo) y al menos una de «exige_uno_de» (ranking semántico con un nivel dedicado,
        # almacenamiento con su cómputo). Una regla mal formada falla cerrado.
        valoradas = [pl.get("id") for p, pl in propios if p.get("cantidad_mensual") is not None]
        uno_de = []
        for rm in reglas_medidores_de(entrada) if valoradas else []:
            if rm is False:
                mal(cid, "regla_medidores_no_valida", f"{entrada.get('nombre_oficial')}: el catálogo declara una regla de "
                    "medidores mal formada: no se puede comprobar (falla cerrado)")
            elif set(valoradas) & set(rm["si_usa"]):
                faltan += [x for x in rm["exige"] if x not in valoradas and x not in faltan]
                if rm["exige_uno_de"] and not set(valoradas) & set(rm["exige_uno_de"]):
                    uno_de.append(rm["exige_uno_de"])
        if faltan:
            mal(cid, "falta_medidor_obligatorio", f"{entrada.get('nombre_oficial')} lleva precios propios y le falta "
                f"{', '.join(faltan)}: el catálogo los declara obligatorios (lo que más factura el servicio); añádelos "
                "con su cantidad (con volumetría citada, desde ella y su factor estándar)")
        for grupo in uno_de:
            mal(cid, "falta_medidor_obligatorio", f"{entrada.get('nombre_oficial')} usa un medidor que se cobra además de "
                f"otro y le falta uno de {', '.join(grupo)} (reglas de medidores del catálogo): añade el que corresponda, "
                "con su nivel justificado si lo tiene")
        # I1.8 (REVERIF17-2): un cómputo que no es el por defecto del catálogo se justifica con su nivel, y sin niveles en
        # el catálogo no se puede justificar (falla cerrado). REVERIF17-3: tope de instancias del nivel y, con más de una,
        # justificación citada (la ve el revisor).
        # I1.8 (N4, integrador): en una fila de la clase cómputo con niveles, valora cómputo quien usa una plantilla de
        # algún nivel (la memoria de corto plazo de Foundry Agent Service no es cómputo); un nivel que no dice sus
        # plantillas no deja saberlo y cuenta como usado (falla cerrado).
        de_niveles = set().union(*(n["plantillas"] or set() for n in niveles))
        usa_nivel = any(n["plantillas"] is None for n in niveles) or bool(set(propias) & de_niveles)
        computo = (isinstance(entrada, dict) and entrada.get("id") in filas_computo(catalogo) and bool(propios)
                   and not es_computo_por_defecto(entrada, propias, catalogo) and (not niveles or usa_nivel))
        varias = []
        for pid, pl, veces in instancias_por_plantilla(propios):  # partir en líneas no esquiva el tope (como REV17-1)
            nivel_p = next((n for n in niveles if n["plantillas"] and pl.get("id") in n["plantillas"]), None)
            tope = nivel_p["instancias_max"] if nivel_p else None
            minimo = nivel_p["instancias_min"] if nivel_p else None        # I1.8 (N5)
            validas = nivel_p["instancias_validas"] if nivel_p else None
            if tope is False or minimo is False or validas is False:
                mal(pid, "instancias_max_no_valido", f"el catálogo declara para el nivel «{nivel_p['etiqueta']}» "
                    "un tope, un mínimo o unos valores de instancias que no son enteros ≥ 1: no se puede comprobar (falla "
                    "cerrado)")
            else:
                if tope and veces > tope:
                    mal(pid, "instancias_sobre_limite", f"{_fmt_dec(veces)} instancias de «{pl.get('id')}» en el componente "
                        f"y el nivel «{nivel_p['etiqueta']}» admite {tope} como máximo (límites del catálogo: "
                        f"{'; '.join(nivel_p['limites']) or 'sin texto'}): usa otro nivel, justificado, o menos instancias")
                if minimo and veces < minimo:
                    mal(pid, "instancias_bajo_minimo", f"{_fmt_dec(veces)} instancias de «{pl.get('id')}» en el componente y "
                        f"el nivel «{nivel_p['etiqueta']}» exige {minimo} como mínimo (límites del catálogo: "
                        f"{'; '.join(nivel_p['limites']) or 'sin texto'}): pon al menos el mínimo")
                if validas and veces not in validas:
                    mal(pid, "instancias_no_admitidas", f"{_fmt_dec(veces)} instancias de «{pl.get('id')}» en el "
                        f"componente y el nivel «{nivel_p['etiqueta']}» solo admite "
                        f"{', '.join(str(x) for x in validas)}: usa uno de esos valores")
            if veces > 1 and (nivel_p is not None or computo):
                varias.append(pid)
        if not niveles:
            if computo:
                mal(cid, "computo_sin_niveles", f"{entrada.get('nombre_oficial')} no es el cómputo por defecto del catálogo y "
                    "el catálogo no le da niveles con los que justificarlo: usa el cómputo por defecto "
                    f"({_objeto((catalogo or {}).get('computo_por_defecto')).get('componente')} "
                    f"{_objeto((catalogo or {}).get('computo_por_defecto')).get('nivel')})")
            if con_modelo(entrada):  # I1.9 (VC18-5): el modelo, como un nivel con su valor por defecto
                _reglas_modelo(cid, propios, jn, requisitos, brief_texto, catalogo, mal)
            elif jn is not None:
                mal(cid, "nivel_sin_catalogo", "el catálogo no da niveles para este servicio: justificacion_nivel va null")
            continue
        veces_nivel = _insuficiencia(cid, entrada, niveles, propias, propios, requisitos, brief_texto, mal)
        # I1.9 (VC18-1, PR18-3; decisión del PM): el nivel por defecto (nivel_por_defecto de la fila, con fuente, o el
        # cómputo por defecto) no se justifica; subir exige una razón de razones_subida del nivel usado y la cita de
        # los requisitos que la cumple, comprobada por código (umbral con su número o característica con su palabra).
        defecto = es_por_defecto(entrada, propias, catalogo)
        hace_falta = (computo or usa_nivel) and not defecto
        if jn is None:
            if varias:
                mal(cid, "instancias_sin_justificar", f"{', '.join(varias)} lleva(n) más de una instancia: "
                    "justificacion_nivel con el nivel, una razón de subida de ese nivel en el catálogo y la cita de los "
                    "requisitos que la cumple; sin razón que lo obligue, una instancia")
            elif hace_falta:
                mal(cid, "nivel_sin_justificar", f"{entrada.get('nombre_oficial')} no usa el nivel por defecto del "
                    f"catálogo ({texto_por_defecto(entrada, catalogo)}): justificacion_nivel con el nivel, una razón de "
                    f"subida de ese nivel ({_ids_razones(niveles, propias)}) y la cita de los requisitos que la cumple; "
                    "sin ninguna, el nivel por defecto")
            continue
        if not hace_falta and not varias:
            mal(cid, "justificacion_sobrante", f"{entrada.get('nombre_oficial')} usa el nivel por defecto del catálogo "
                f"({texto_por_defecto(entrada, catalogo)}): el nivel por defecto no se justifica; justificacion_nivel va "
                "null (VC18-1)")
            continue
        nivel = next((n for n in niveles if _plano_req(jn.get("nivel")) in n["nombres"]), None)
        if nivel is None:
            mal(cid, "nivel_desconocido", f"nivel «{jn.get('nivel')}» no está en el catálogo (admite: "
                f"{', '.join(n['nombres'][0] for n in niveles if n['nombres'])})")
            continue
        usadas = set(propias)
        de_niveles = set().union(*(n["plantillas"] or set() for n in niveles))
        if nivel["plantillas"] is not None and (usadas & de_niveles) - nivel["plantillas"]:
            mal(cid, "nivel_distinto_del_precio", f"el nivel justificado es «{jn.get('nivel')}» y los precios usan la "
                f"plantilla de otro nivel ({', '.join(sorted((usadas & de_niveles) - nivel['plantillas']))})")
        _reglas_razon(cid, jn, nivel["razones"], f"el nivel «{nivel['etiqueta']}»", requisitos, brief_texto, mal,
                      veces_nivel)
    for p in precios:  # I1.9 (VC18-7, E19-4): un medidor opcional con valor por defecto «sin» solo con requisito
        comp, i = por_id.get(p.get("componente_id")), info[id(p)]
        if comp is None or i is None or es_existente(comp):
            continue
        op = opcional_de(i["plantilla"])
        if op is False:
            mal(p.get("id"), "opcional_no_valido", f"la plantilla «{i['plantilla'].get('id')}» declara «opcional» mal "
                "formado en el catálogo: no se puede comprobar (falla cerrado)")
        elif op and op["por_defecto"] == "sin" and cumple_opcional(op["razones"], requisitos, brief_texto) is None:
            mal(p.get("id"), "opcional_sin_requisito", f"la plantilla «{i['plantilla'].get('id')}» es opcional y su valor "
                f"por defecto es no usarla ({op['motivo'] or 'catálogo'}); ninguna cita de los requisitos (lo ASUMIDO no "
                f"cuenta) cumple sus razones ({', '.join(r['id'] for r in op['razones']) or 'ninguna'}): quita este precio")
    return salida


def opcional_de(plantilla: object) -> dict | None | bool:
    """I1.9 (VC18-7): {"por_defecto": «sin» o «con», "motivo", "razones"} de una plantilla `opcional` del catálogo;
    None si no lo es y False si está mal formada (falla cerrado)."""
    o = _objeto(plantilla).get("opcional")
    if o is None:
        return None
    razones = razones_validas(o.get("razones")) if isinstance(o, dict) else False
    if not isinstance(o, dict) or o.get("por_defecto") not in ("sin", "con") or razones is False:
        return False
    return {"por_defecto": o["por_defecto"], "motivo": _texto_no_vacio(o.get("motivo")), "razones": razones}


def cumple_opcional(razones: list, requisitos: object, brief_texto: object) -> tuple[dict, str] | None:
    """(razón, cita) de la primera cita de los requisitos (sin lo ASUMIDO) que cumple una de las razones; None si no."""
    for r in razones:
        for cita in citas_de_campos(requisitos, brief_texto, (r["campo"],) if r["campo"] else CAMPOS_DIMENSIONAMIENTO,
                                    sin_asumido=True):
            if razon_cumplida(r, cita):
                return r, cita
    return None


def instancias_por_plantilla(propios: list) -> list[tuple]:
    """[(id del primer precio, plantilla, instancias totales)] de las plantillas de tiempo de un componente, en orden de
    aparición: la suma de las instancias de todas sus líneas (null = 1). Una línea con instancias no numéricas no suma
    (ya la rechaza el esquema)."""
    salida: dict = {}
    for p, pl in propios:
        veces = _dec(p.get("instancias")) if p.get("instancias") is not None else Decimal(1)
        if pl.get("impulsor") != "tiempo" or veces is None:
            continue
        pid, _, total = salida.get(pl.get("id"), (p.get("id"), pl, Decimal(0)))
        salida[pl.get("id")] = (pid, pl, total + veces)
    return list(salida.values())


def es_computo_por_defecto(entrada: object, propias: list, catalogo: dict) -> bool:
    """PR17-4 (arreglos I1.7): el componente es el cómputo por defecto del catálogo (su fila y solo sus plantillas, con al
    menos una). Con el por defecto no hace falta justificacion_nivel; cualquier otro cómputo con niveles la exige."""
    cp = (catalogo or {}).get("computo_por_defecto")
    return (isinstance(cp, dict) and isinstance(entrada, dict) and entrada.get("id") == cp.get("componente")
            and bool(propias) and set(propias) <= set(cp.get("plantillas") or []))


def filas_computo(catalogo: dict) -> tuple:
    """I1.8 (REVERIF17-2): filas de la clase «cómputo» (alternativas al cómputo por defecto): `computo_por_defecto.filas`
    del catálogo si las declara (lista de ids no vacía); si no, FILAS_COMPUTO."""
    filas = _objeto((catalogo or {}).get("computo_por_defecto")).get("filas")
    propias = tuple(x for x in filas if isinstance(x, str)) if isinstance(filas, list) else ()
    return propias or FILAS_COMPUTO


def nivel_por_defecto(entrada: object) -> dict | None:
    """El nivel que la fila declara por defecto, tal como lo da niveles_de (con "fuente_defecto"); None si no lo
    declara, si no es uno de sus niveles o, desde I1.9 (VC18-1), si no es un objeto {"nivel", "fuente"} con la fuente
    (URL https) que lo hace el mínimo viable en producción con SLA: sin fuente, se exige justificación (falla cerrado)."""
    nd = _objeto(entrada.get("nivel_por_defecto") if isinstance(entrada, dict) else None)
    nombre, fuente = _plano_req(nd.get("nivel")), _texto_no_vacio(nd.get("fuente")) or _texto_no_vacio(nd.get("fuente_url"))
    if not nombre or not fuente or not fuente.startswith("https://"):
        return None
    n = next((x for x in niveles_de(entrada) if nombre in x["nombres"]), None)
    return {**n, "fuente_defecto": fuente} if n else None


def texto_por_defecto(entrada: object, catalogo: dict) -> str:
    """El valor por defecto de la fila para los mensajes: el cómputo por defecto en la clase cómputo, su
    nivel_por_defecto fuera de ella, o que el catálogo no lo declara."""
    if isinstance(entrada, dict) and entrada.get("id") in filas_computo(catalogo):
        cp = _objeto((catalogo or {}).get("computo_por_defecto"))
        return f"cómputo por defecto {cp.get('componente')} {cp.get('nivel')}"
    nd = nivel_por_defecto(entrada)
    return f"nivel por defecto {nd['etiqueta']}" if nd else "el catálogo no declara nivel por defecto con fuente"


def _ids_razones(niveles: list, propias: list) -> str:
    """Las razones de subida de los niveles cuyas plantillas usa el componente, para el remedio del mensaje."""
    usados = [n for n in niveles if n["plantillas"] is None or set(propias) & n["plantillas"]]
    ids = [r["id"] for n in usados if isinstance(n["razones"], list) for r in n["razones"]]
    return "razones admitidas: " + ", ".join(ids) if ids else "el catálogo no da razones para ese nivel"


def con_modelo(entrada: object) -> bool:
    """La fila tiene plantillas de modelo (Microsoft Foundry)."""
    return isinstance(entrada, dict) and any(isinstance(x, dict) and isinstance(x.get("modelo"), str)
                                             for x in entrada.get("plantillas_precio") or [])


def _reglas_razon(cid: object, jn: dict, razones: object, que: str, requisitos: object, brief_texto: object, mal,
                  veces: Decimal | None = None) -> None:
    """I1.9: la justificación de un nivel o de un modelo: razón de la lista cerrada del catálogo y cita literal de los
    requisitos que la cumple (razon_cumplida). Una lista mal formada o vacía falla cerrado. VC19-1 (I1.10): con una razón
    que declara `por_instancia`, las instancias del nivel (`veces`) son las que exige la cita, ni una más ni una menos."""
    if razones is False:
        mal(cid, "razones_no_validas", f"el catálogo declara para {que} razones de subida mal formadas: no se puede "
            "comprobar (falla cerrado)")
        return
    if not razones:
        mal(cid, "nivel_sin_razones", f"el catálogo no da razones para subir a {que}: usa el valor por defecto (y, si "
            "eran varias instancias, una)")
        return
    razon = next((r for r in razones if r["id"] == jn.get("razon")), None)
    if razon is None:
        mal(cid, "razon_desconocida", f"razon «{jn.get('razon')}» no es una razón de subida de {que} (admite: "
            f"{', '.join(r['id'] for r in razones)})")
        return
    campos = (razon["campo"],) if razon["campo"] else CAMPOS_DIMENSIONAMIENTO
    cita = _plano_req(quitar_comillas(jn.get("cita")))
    citas = citas_de_campos(requisitos, brief_texto, campos, sin_asumido=True)
    if cita not in citas:
        mal(cid, "requisito_no_literal", f"la cita «{cita}» no es literal de {', '.join(campos)} en los requisitos (lo "
            f"ASUMIDO no cuenta): copia una carácter a carácter "
            f"({'; '.join(f'«{x}»' for x in citas[:8]) or 'el brief no trae ninguna'})")
        return
    if razon_cumplida(razon, cita):
        necesarias = instancias_necesarias(razon, cita)
        if necesarias is not None and veces is not None and veces != necesarias:
            mal(cid, "instancias_no_cuadran", f"la razón «{razon['id']}» da una instancia por cada "
                f"{_fmt_dec(razon['por_instancia'])} {razon['palabras'][0]}: con «{cita}» son {necesarias} y el componente "
                f"lleva {_fmt_dec(veces)}")
        return
    if razon["tipo"] == "umbral":
        con_unidad = numeros_con_unidad(cita, razon["palabras"], razon.get("cortas"), VENTANA_UNIDAD)
        mal(cid, "razon_no_cumplida", f"la razón «{razon['id']}» exige un número de {', '.join(razon['palabras'])} mayor "
            f"que {_fmt_dec(razon['limite'])} (límite del valor por defecto) y la cita «{cita}» no lo trae (con esa unidad: "
            f"{', '.join(_fmt_dec(n) for n in con_unidad) or 'ninguno'}): sin él, el valor por defecto")
    else:
        mal(cid, "razon_no_cumplida", f"la razón «{razon['id']}» exige que la cita diga "
            f"{' o '.join(f'«{w}»' for w in razon['palabras_clave'])} y «{cita}» no lo dice: sin ella, el valor por defecto")


def _insuficiencia(cid: object, entrada: object, niveles: list, propias: list, propios: list, requisitos: object,
                   brief_texto: object, mal) -> Decimal | None:
    """VC19-1 (I1.10, decisión del PM): la regla de niveles en las dos direcciones (LES-G-100.7 y .8). Con el nivel que
    usan los precios del componente (el primero, en el orden del catálogo, cuyas plantillas usa):
    - nivel_insuficiente: una cita CITADA (no ASUMIDA) del campo de una razón «umbral» sin `por_instancia` de un nivel
      POSTERIOR en el catálogo (ordenado de menos a más capacidad) la cumple: el nivel usado no basta; la salida (ese
      nivel justificado con esa razón y esa cita) siempre existe;
    - instancias_insuficientes: una cita CITADA cumple una razón con `por_instancia` del nivel usado y las instancias
      son menos de las que exige (techo del número citado ÷ por_instancia).
    Devuelve las instancias del nivel usado (las de su plantilla de tiempo con más instancias) o None."""
    usado = next((k for k, n in enumerate(niveles) if n["plantillas"] and set(propias) & n["plantillas"]), None)
    if usado is None:
        return None
    nivel = niveles[usado]
    veces = max((v for _, pl, v in instancias_por_plantilla(propios) if pl.get("id") in nivel["plantillas"]),
                default=None)
    # Una sola regla por componente, con el nivel MÁS ALTO cuya razón cumple la cita (ARR1, I1.10): con SQL Basic y
    # 1.200 sesiones citadas se pedía S0, S1 y GP a la vez y subir solo a S0 gastaba otro intento T2.
    exigido = None
    for superior in niveles[usado + 1:]:
        for r in superior["razones"] if isinstance(superior["razones"], list) else []:
            if r["tipo"] != "umbral" or r.get("por_instancia"):
                continue
            cumple = [x for x in citas_de_campos(requisitos, brief_texto, (r["campo"],), sin_asumido=True)
                      if razon_cumplida(r, x)]
            if cumple:
                exigido = (superior, r, cumple[0])
                break
    insuficiente = exigido is not None
    if exigido:
        superior, r, cita = exigido
        mal(cid, "nivel_insuficiente", f"la cita «{cita}» supera {_fmt_dec(r['limite'])} {r['palabras'][0]}: el "
            f"nivel «{nivel['etiqueta']}» ({'; '.join(nivel['limites'])[:200]}) no basta; usa «{superior['etiqueta']}» "
            f"con justificacion_nivel {{nivel, razon: «{r['id']}», cita}}")
    # con el nivel ya insuficiente, el remedio es el nivel: no se piden además instancias del que no basta
    for r in (nivel["razones"] if isinstance(nivel["razones"], list) and not insuficiente else []):
        if r["tipo"] != "umbral" or not r.get("por_instancia"):
            continue
        necesarias = [(n, x) for x in citas_de_campos(requisitos, brief_texto, (r["campo"],), sin_asumido=True)
                      for n in [instancias_necesarias(r, x)] if n is not None and razon_cumplida(r, x)]
        if necesarias and veces is not None:
            n, x = max(necesarias)
            if veces < n:
                mal(cid, "instancias_insuficientes", f"la cita «{x}» exige {n} instancias del nivel "
                    f"«{nivel['etiqueta']}» (una por cada {_fmt_dec(r['por_instancia'])} {r['palabras'][0]}) y el "
                    f"componente lleva {_fmt_dec(veces)}: justificacion_nivel {{nivel, razon: «{r['id']}», cita}} con "
                    f"{n} instancias, o un nivel superior justificado")
    return veces


def _reglas_modelo(cid: object, propios: list, jn: dict | None, requisitos: object, brief_texto: object, catalogo: dict,
                   mal) -> None:
    """I1.9 (VC18-5): el modelo por defecto del catálogo (gpt-6-luna) no se justifica; otro modelo exige
    justificacion_nivel con el modelo en «nivel», una razón de subida de ese modelo y la cita que la cumple."""
    usados = list(dict.fromkeys(pl.get("modelo") for _, pl in propios if isinstance(pl.get("modelo"), str)))
    if not usados:
        if jn is not None:
            mal(cid, "nivel_sin_catalogo", "sin precios de modelo no hay nada que justificar: justificacion_nivel va null")
        return
    defecto = modelo_por_defecto(catalogo)
    if defecto is None:
        mal(cid, "modelo_por_defecto_no_declarado", "el catálogo no declara modelo_por_defecto: no se puede saber si el "
            "modelo necesita justificación (falla cerrado)")
        return
    otros = [m for m in usados if m != defecto]
    if not otros:
        if jn is not None:
            mal(cid, "justificacion_sobrante", f"{defecto} es el modelo por defecto del catálogo: no se justifica; "
                "justificacion_nivel va null (VC18-5)")
        return
    if jn is None:
        mal(cid, "modelo_sin_justificar", f"{', '.join(otros)} no es el modelo por defecto del catálogo ({defecto}): "
            "justificacion_nivel con el modelo en «nivel», una razón de subida de ese modelo en el catálogo y la cita de "
            f"los requisitos que la cumple; sin ninguna, {defecto}")
        return
    if len(otros) > 1 or _compacto(jn.get("nivel")) != _compacto(otros[0]):
        mal(cid, "nivel_desconocido", f"nivel «{jn.get('nivel')}» no es el modelo que valoran los precios "
            f"({', '.join(otros)}): un componente justifica un solo modelo distinto del por defecto")
        return
    _reglas_razon(cid, jn, razones_modelo(catalogo, otros[0]), f"el modelo «{otros[0]}»", requisitos, brief_texto, mal)


def es_por_defecto(entrada: object, propias: list, catalogo: dict) -> bool:
    """El componente usa el valor por defecto del catálogo y no tiene que justificar su nivel: el cómputo por defecto
    (PR17-4) o, fuera de la clase cómputo, el `nivel_por_defecto` de su fila (con alguna plantilla de nivel usada y todas
    de ese nivel). En la clase cómputo solo vale el cómputo por defecto del catálogo (I1.8, decisión del PM)."""
    if es_computo_por_defecto(entrada, propias, catalogo):
        return True
    if not isinstance(entrada, dict) or entrada.get("id") in filas_computo(catalogo):
        return False
    nd = nivel_por_defecto(entrada)
    if nd is None or not nd["plantillas"]:
        return False
    usadas = set(propias) & set().union(*(n["plantillas"] or set() for n in niveles_de(entrada)))
    return bool(usadas) and usadas <= nd["plantillas"]


def _num(x: object) -> str:
    d = _dec(x)
    return str(x) if d is None else f"{d.normalize():f}".replace(".", ",")


def _num_es(x: object) -> str:
    """VA18-9 (I1.9): un número para el revisor en formato español, con separador de millares («2.000», «0,5»,
    «1.234,25»); lo que no es un número, tal cual. _num se conserva: supuesto_cantidad tiene réplica en la puerta."""
    d = _dec(x)
    if d is None:
        return str(x)
    entero, _, decimales = f"{abs(d).normalize():f}".partition(".")
    return ("-" if d < 0 else "") + f"{int(entero):,}".replace(",", ".") + (f",{decimales}" if decimales else "")


def lineas_por_defecto(resp: dict, catalogo: dict) -> list[str]:
    """PR16-3 (arreglos I1.6): una línea para el revisor por componente cuya fila del catálogo marca plantillas «por
    defecto» (el modelo de Microsoft Foundry) y que se valora con otras plantillas de la fila y ninguna de esas. No
    rechaza: el modelo puede cambiarse si el brief lo pide, pero el revisor lo ve (en A y en B el modelo cambiaba)."""
    salida = []
    for c in resp.get("componentes") or []:
        entrada = _entrada_de(c, catalogo)
        defecto = [p.get("id") for p in (entrada or {}).get("plantillas_precio") or []
                   if isinstance(p, dict) and p.get("por_defecto") is True]
        if not defecto:
            continue
        usadas = list(dict.fromkeys(i["plantilla"].get("id") for p in resp.get("precios") or []
                                    if isinstance(p, dict) and p.get("componente_id") == c.get("id")
                                    and (i := plantilla_de_precio(p, c, catalogo)) is not None and not i["auxiliar"]))
        if usadas and not set(usadas) & set(defecto):
            salida.append(f"Plantillas de {entrada.get('nombre_oficial')} ({c.get('id')}): el catálogo marca por defecto "
                          f"{', '.join(defecto)} y la valoración usa {', '.join(usadas)}; comprobar que el brief pide "
                          "ese cambio")
    return salida + lineas_computo(resp, catalogo)


CAPA_COMPUTO = "aplicacion_integracion"
FILAS_COMPUTO = ("az-app-service", "az-functions", "az-container-apps", "az-logic-apps", "az-foundry-agent-service")


def lineas_computo(resp: dict, catalogo: dict) -> list[str]:
    """PR17-4 (arreglos I1.7): con la misma solicitud, una sesión eligió Functions Premium (116,29 €) y otra App Service
    B1 (11,53 €). Una línea para el revisor por cada cómputo valorado que no es el por defecto del catálogo, con la
    justificación de su nivel si la trae (el núcleo ya exige una cita de dimensionamiento a los cómputos con niveles)."""
    cp = (catalogo or {}).get("computo_por_defecto")
    if not isinstance(cp, dict):
        return []
    salida = []
    for c in resp.get("componentes") or []:
        entrada = _entrada_de(c, catalogo)
        if not isinstance(c, dict) or not entrada or entrada.get("id") not in filas_computo(catalogo):
            continue
        hits = [i["plantilla"] for p in resp.get("precios") or [] if isinstance(p, dict)
                and p.get("componente_id") == c.get("id") and (i := plantilla_de_precio(p, c, catalogo)) is not None
                and not i["auxiliar"]]
        usadas = list(dict.fromkeys(pl.get("id") for pl in hits))
        if es_computo_por_defecto(entrada, usadas, catalogo) or not usadas:
            continue
        jn = c.get("justificacion_nivel") if isinstance(c.get("justificacion_nivel"), dict) else {}
        porque = (f"nivel {jn.get('nivel')} por la razón «{jn.get('razon')}» con la cita «{jn.get('cita')}»"
                  if jn else "sin justificación (el núcleo la exige desde I1.8: revisar)")
        salida.append(f"Cómputo de {entrada.get('nombre_oficial')} ({c.get('id')}, {', '.join(usadas)}): no es el por "
                      f"defecto del catálogo ({cp.get('componente')} {cp.get('nivel')}); {porque}. Comprobar que el "
                      "requisito obliga a este cómputo (PR17-4)")
    return salida


def _detalle_razon(razon: dict, cita: object) -> str:
    """Cómo cumple la cita la razón, calculado por código (para el revisor)."""
    if razon.get("tipo") == "umbral":
        numeros = [n for n in numeros_con_unidad(cita, razon["palabras"], razon.get("cortas"), VENTANA_UNIDAD)
                   if n > razon["limite"]]
        return (f"umbral: {', '.join(_fmt_dec(n) for n in numeros) or 'ningún número'} "
                f"{razon['palabras'][0]} en la cita frente al límite de {_fmt_dec(razon['limite'])} del valor por defecto")
    claves = [w for w in razon.get("palabras_clave") or [] if afirmada(cita, w)]
    return f"característica: la cita dice «{'», «'.join(claves) or 'ninguna palabra clave'}»"


def razon_de_justificacion(comp: object, resp: dict, catalogo: dict) -> dict | None:
    """I1.9: la razón del catálogo que cita `justificacion_nivel.razon` (la del nivel que usan sus precios o, si no se
    sabe, el de ese nombre; en una fila sin niveles, la del modelo de `nivel`); None si no hay o no casa."""
    comp = _objeto(comp)
    jn, entrada = _objeto(comp.get("justificacion_nivel")), _entrada_de(comp, catalogo)
    if not jn or entrada is None:
        return None
    niveles = niveles_de(entrada)
    if niveles:
        propias = {i["plantilla"].get("id") for p in _objeto(resp).get("precios") or [] if isinstance(p, dict)
                   and p.get("componente_id") == comp.get("id") and (i := plantilla_de_precio(p, comp, catalogo))
                   and not i["auxiliar"]}
        usado = next((n for n in niveles if n["plantillas"] and propias & n["plantillas"]), None) or next(
            (n for n in niveles if _compacto(jn.get("nivel")) in {_compacto(x) for x in n["nombres"]}), None)
        razones = usado["razones"] if usado else None
    else:
        razones = razones_modelo(catalogo, jn.get("nivel"))
    return next((r for r in razones or [] if r["id"] == jn.get("razon")), None)


def segmento_verificador_i19(comp: object, resp: dict, catalogo: dict, requisitos: object, anon=None) -> str:
    """I1.9 (E19-9): el segmento de la línea del componente en el consolidado, en la forma que esperan las instrucciones
    del verificador: `| existente del cliente: EX-nn | cita: «…»` para un recurso del cliente (la cita de su entrada) y
    `| nivel: … | razon: id («texto») | cita: «…» | fuente_nivel: URL` (la de la razón en el catálogo) para un nivel o
    un modelo justificados; "" si no hay nada. Las citas son del cliente: pasan por `anon`. Sustituye a
    verificacion._segmento_nivel (que leía `requisito` y `limite_oficial`, de la v4)."""
    a = anon if callable(anon) else (lambda t: t)

    def plano(x: object) -> str:
        return " ".join(str(x if x is not None else "").replace("|", "/").split())

    comp = _objeto(comp)
    if es_existente(comp):
        k = _objeto(comp.get("existente_del_cliente")).get("entrada")
        e = existentes_req(requisitos).get(k) if isinstance(k, str) else None
        return f" | existente del cliente: {plano(k) or 'sin entrada'}" + (
            f" | cita: «{plano(a(_plano_req(e.get('cita'))))}»" if e else "")
    jn = _objeto(comp.get("justificacion_nivel"))
    if not jn:
        return ""
    r = razon_de_justificacion(comp, resp, catalogo)
    texto = f" («{plano(r.get('texto'))}»)" if r and _texto_no_vacio(r.get("texto")) else ""
    fuente = (normalizar_url(r["fuente"]) if r and isinstance(r.get("fuente"), str) else "") or "sin fuente"
    return (f" | nivel: {plano(jn.get('nivel'))} | razon: {plano(jn.get('razon'))}{texto} | cita: "
            f"«{plano(a(_plano_req(quitar_comillas(jn.get('cita')))))}» | fuente_nivel: {fuente}")


def lineas_revisor_i19(resp: dict, catalogo: dict, requisitos: object = None) -> list[str]:
    """I1.9 (decisión del PM): lo que el revisor tiene que leer de los recursos que el cliente ya tiene (reutilizados, no
    usados o valorados de nuevo con su motivo), del nivel de cada servicio (el por defecto, con su fuente, o la subida
    con su razón y cómo la cumple la cita), del modelo, del canal sin cómputo propio y de los datos sin salida."""
    comps = [c for c in resp.get("componentes") or [] if isinstance(c, dict)]
    nombre = {e.get("id"): e.get("nombre_oficial") for e in _entradas(catalogo)}
    ex, salida = existentes_req(requisitos), []
    usados = {c["existente_del_cliente"].get("entrada"): c for c in comps if isinstance(c.get("existente_del_cliente"), dict)}
    for k, e in ex.items():
        que = f"{k} ({nombre.get(e.get('servicio_catalogo')) or 'fuera del catálogo'}, «{e.get('valor')}»)"
        if k in usados:
            salida.append(f"Recurso que el cliente ya tiene: {que} se reutiliza como {usados[k].get('id')} y no se valora "
                          f"(su nivel y su región son del cliente). Cita: «{e.get('cita')}». Comprobar en la transcripción "
                          "que el cliente lo tiene")
        else:
            salida.append(f"Recurso que el cliente ya tiene y la propuesta no usa: {que}. Cita: «{e.get('cita')}». "
                          "Comprobar que la solución no lo necesita")
    valorados = valorados_de(resp, catalogo)
    for c in comps:
        exs = [k for k, e in ex.items() if e.get("servicio_catalogo") == c.get("catalogo_id")]
        if exs and not es_existente(c) and valorados.get(c.get("id")):
            salida.append(f"Servicio nuevo aunque el cliente ya tiene uno: {nombre.get(c.get('catalogo_id'))} "
                          f"({c.get('id')}) se valora y {', '.join(exs)} dice que el cliente ya lo tiene. Motivo del "
                          f"experto: «{c.get('desviacion_justificada')}». Comprobar que hace falta uno nuevo")
    for c in comps:
        entrada, jn = _entrada_de(c, catalogo), _objeto(c.get("justificacion_nivel"))
        if es_existente(c) or entrada is None:
            continue
        propias = [i["plantilla"].get("id") for p in resp.get("precios") or [] if isinstance(p, dict)
                   and p.get("componente_id") == c.get("id") and (i := plantilla_de_precio(p, c, catalogo))
                   and not i["auxiliar"]]
        que = f"{entrada.get('nombre_oficial')} ({c.get('id')})"
        niveles = niveles_de(entrada)
        usado = next((n for n in niveles if n["plantillas"] and set(propias) & n["plantillas"]), None)
        if usado and es_por_defecto(entrada, propias, catalogo) and not jn:
            nd = nivel_por_defecto(entrada)
            fuente = (nd or {}).get("fuente_defecto") or _objeto((catalogo or {}).get("computo_por_defecto")).get("fuente_url")
            salida.append(f"Nivel por defecto de {que}: {usado['etiqueta']}, sin justificación: es el mínimo viable en "
                          f"producción con SLA según el catálogo (fuente {fuente})")
        elif usado and jn:
            razon = next((r for r in usado["razones"] or [] if r["id"] == jn.get("razon")), None)
            salida.append(f"Nivel de {que}: {jn.get('nivel')}, por encima del valor por defecto "
                          f"({texto_por_defecto(entrada, catalogo)}), por la razón «{jn.get('razon')}»"
                          + (f" ({razon['texto']})" if razon and razon.get("texto") else "")
                          + (f"; {_detalle_razon(razon, jn.get('cita'))}; fuente {razon['fuente']}" if razon else "")
                          + f". Cita: «{jn.get('cita')}». Comprobar que el requisito obliga a subir")
        modelos = list(dict.fromkeys(i["plantilla"].get("modelo") for p in resp.get("precios") or []
                                     if isinstance(p, dict) and p.get("componente_id") == c.get("id")
                                     and (i := plantilla_de_precio(p, c, catalogo)) and not i["auxiliar"]
                                     and isinstance(i["plantilla"].get("modelo"), str)))
        defecto = modelo_por_defecto(catalogo)
        if modelos and not niveles and modelos == [defecto]:
            salida.append(f"Modelo por defecto de {que}: {defecto}, sin justificación (fuente "
                          f"{_objeto((catalogo or {}).get('modelo_por_defecto')).get('fuente_url')})")
        elif modelos and not niveles and jn:
            rs = razones_modelo(catalogo, jn.get("nivel"))
            razon = next((r for r in rs or [] if r["id"] == jn.get("razon")), None)
            salida.append(f"Modelo de {que}: {jn.get('nivel')} en lugar del modelo por defecto ({defecto}), por la razón "
                          f"«{jn.get('razon')}»" + (f"; {_detalle_razon(razon, jn.get('cita'))}; fuente {razon['fuente']}"
                                                    if razon else "")
                          + f". Cita: «{jn.get('cita')}». Comprobar que el requisito obliga a cambiar de modelo")
    supuestos = [s for s in resp.get("supuestos") or [] if isinstance(s, dict)]
    for c in comps:
        for s in supuestos:
            if c.get("id") in (s.get("hechos") or []) and _dice_sin_computo(s.get("texto")) and \
                    _capa(c, catalogo) == CAPA_CANALES:
                salida.append(f"Canal sin cómputo propio: {c.get('servicio')} ({c.get('id')}); el experto lo declara en "
                              f"{s.get('id')}: «{s.get('texto')}». Comprobar quién atiende los mensajes del canal")
    sin_salida = {x["id"] for x in errores_arquitectura({**resp, "supuestos": []}, catalogo) if x["regla"] == "datos_sin_salida"}
    for c in comps:
        if c.get("id") in sin_salida:
            motivo = next((s for s in supuestos if c.get("id") in (s.get("hechos") or [])
                           and nombra_servicio(s.get("texto"), c, catalogo)), None)
            salida.append(f"Componente de datos sin salida hacia la solución: {c.get('servicio')} ({c.get('id')}); "
                          + (f"se conserva por {motivo.get('id')}: «{motivo.get('texto')}»" if motivo else
                             "sin supuesto que lo explique") + ". Comprobar que alguien usa esos datos")
    por_id = {c.get("id"): c for c in comps}
    for p in resp.get("precios") or []:  # VC18-7: un medidor opcional valorado, con la razón y la cita que lo piden
        i = plantilla_de_precio(p, por_id.get(p.get("componente_id")), catalogo) if isinstance(p, dict) else None
        op = opcional_de(i["plantilla"]) if i else None
        hecho = cumple_opcional(op["razones"], requisitos, None) if op and op["por_defecto"] == "sin" else None
        if hecho:
            salida.append(f"Medidor opcional valorado: {i['plantilla'].get('id')} ({p.get('id')}, {p.get('componente_id')}); "
                          f"el valor por defecto es no usarlo y se valora por la razón «{hecho[0]['id']}» con la cita "
                          f"«{hecho[1]}» (fuente {hecho[0]['fuente']}). Comprobar que el cliente lo necesita")
    return salida


def lineas_para_revisor(resp: dict, catalogo: dict, sustituciones: list | None = None, fecha: object = None,
                        semanas: object = None, requisitos: object = None) -> list[str]:
    """Lo que el revisor tiene que leer de cada valoración, para la nota (apartado 6). Decisión 4 (I1.6): factores de
    volumen con su cuenta, precios unitarios de referencia, niveles y conceptos sustituidos. I1.7: fecha de la
    instantánea de precios, factor estándar o CAMBIADO por el experto, ciclo de vida de cada modelo (con el límite si se
    conocen `fecha` de la oferta y `semanas` del Gantt), motivos con su dato y lo que el núcleo puso o sustituyó.
    Pura; tolera respuestas anteriores (sin esos campos no hay líneas)."""
    nombres = {e.get("id"): e.get("nombre_oficial") for e in _entradas(catalogo)}
    comps = {c.get("id"): c for c in resp.get("componentes") or [] if isinstance(c, dict)}
    v = _objeto(resp.get("valoracion_nucleo"))

    def servicio(cid: object) -> str:
        c = comps.get(cid) or {}
        return f"{nombres.get(c.get('catalogo_id')) or c.get('servicio')} ({cid})"

    salida = []
    inst = _objeto(v.get("instantanea"))
    if inst:
        salida.append(f"Precios de la instantánea de Azure Retail Prices consultada el {inst.get('fecha')} (EUR, SHA-256 "
                      f"{str(inst.get('sha256'))[:12]}…): el código pone filtro, precio, unidad, vigencia y concepto de "
                      "cada línea desde su plantilla; ni el experto ni el verificador consultan precios")
    for p in resp.get("precios") or []:
        if not isinstance(p, dict):
            continue
        base, cid = p.get("base_volumen"), p.get("componente_id")
        if isinstance(base, dict):
            f = _objeto(base.get("factor"))
            i = plantilla_de_precio(p, comps.get(cid), catalogo)
            divisor = divisor_de(i["plantilla"]) if i else None
            linea = (f"Supuesto de volumen de {servicio(cid)}, precio {p.get('id')} («{p.get('concepto')}»): "
                     f"{_num_es(base.get('cantidad_base'))} {base.get('unidad_base')} (cita «{base.get('cita')}») × "
                     f"{_num_es(f.get('valor'))} {f.get('unidad')} ÷ {_num_es(divisor)} = "
                     f"{_num_es(p.get('cantidad_mensual'))} al mes en la unidad de precio «{p.get('unidad')}». ")
            info_p = _info_de(p, comps, catalogo)
            std = factor_estandar(info_p, catalogo)[0] if info_p else None
            # E19-2: el factor que el código elige por la base de la cita (el estándar o uno de sus alternativos)
            elegido = factor_por_base(info_p, catalogo, base.get("cita"), base.get("unidad_base"))[0] if info_p else None
            if f.get("origen") == "experto":
                estandar = f"estándar del catálogo {_num(std['valor_json'])} {std['unidad']}" if std else \
                    "estándar del catálogo no hay"
                if elegido and std and elegido.get("id") != std.get("id"):  # Revisión (cierre): no llamarlo estándar
                    estandar = (f"factor del catálogo para esa base {_num(elegido['valor_json'])} {elegido['unidad']} "
                                f"({estandar})")
                linea += (f"FACTOR CAMBIADO POR EL EXPERTO (revisar): {estandar}; "
                          f"{f.get('fuente')}; motivo: {f.get('justificacion')}")
            elif f.get("origen") == "catalogo" and elegido and std and elegido.get("id") != std.get("id"):
                caso = f" («{f.get('caso_uso')}»)" if f.get("caso_uso") else ""
                linea += (f"Factor alternativo del catálogo por «{'» o «'.join(elegido['bases'])}»{caso}, elegido por el "
                          f"código porque la base cuenta eso y no «{'» o «'.join(std['bases'])}» (fuente "
                          f"{f.get('fuente')}): {f.get('justificacion')}")
            elif f.get("origen") == "catalogo":
                caso = f" («{f.get('caso_uso')}»)" if f.get("caso_uso") else ""
                linea += f"Factor estándar del catálogo{caso} (fuente {f.get('fuente')}): {f.get('justificacion')}"
            else:
                linea += f"Factor: {f.get('justificacion')}"
            salida.append(linea)
        elif "cantidad_mensual" in p and p.get("cantidad_mensual") is None:
            salida.append(f"Precio unitario de referencia de {servicio(cid)}, precio {p.get('id')}: "
                          f"{_num_es(p.get('precio'))} EUR por {p.get('unidad')} («{p.get('concepto')}»); no suma en el "
                          "total porque el componente se valora con el volumen real")
        n = _dec(p.get("instancias"))
        if n is not None and n != n.to_integral_value():
            salida.append(f"Instancias no enteras en {servicio(cid)}, precio {p.get('id')}: {_num_es(p.get('instancias'))} "
                          f"(«{p.get('supuesto_cantidad')}»); comprobar que el uso parcial está justificado")
    for cid, c in comps.items():  # I1.8 (REVERIF17-3): más de una instancia por plantilla, con su tope y su justificación
        propios = [(p, i["plantilla"]) for p in resp.get("precios") or [] if isinstance(p, dict)
                   and p.get("componente_id") == cid and (i := plantilla_de_precio(p, c, catalogo)) and not i["auxiliar"]]
        for pid, pl, veces in instancias_por_plantilla(propios):
            if veces <= 1:
                continue
            nivel = next((x for x in niveles_de(_entrada_de(c, catalogo)) if x["plantillas"]
                          and pl.get("id") in x["plantillas"]), None)
            jn = _objeto(c.get("justificacion_nivel"))
            tope = (f"tope del nivel {nivel['etiqueta']}: {nivel['instancias_max']}" if nivel and nivel["instancias_max"]
                    else "el catálogo no declara tope")
            porque = (f"justificadas por la razón «{jn.get('razon')}» con «{jn.get('cita') or jn.get('requisito')}»"
                      if jn else "sin justificación")
            salida.append(f"Instancias de {servicio(cid)}, plantilla {pl.get('id')} (desde el precio {pid}): "
                          f"{_fmt_dec(veces)} ({tope}); {porque}. Comprobar que el requisito obliga a escalar")
    salida += lineas_revisor_i19(resp, catalogo, requisitos)
    for c in comps.values():
        jn = c.get("justificacion_nivel")
        if isinstance(jn, dict) and "requisito" in jn:  # respuestas v4 (I1.8): requisito, límite y fuente del experto
            salida.append(f"Nivel de {servicio(c.get('id'))}: {jn.get('nivel')}. Requisito: «{jn.get('requisito')}». "
                          f"Límite oficial: «{jn.get('limite_oficial')}» (fuente {jn.get('fuente')})")
        if c.get("motivo_no_valoracion") == "a_cargo_del_cliente":
            salida.append(f"Motivo de {servicio(c.get('id'))}: a cargo del cliente, según lo que el cliente ya tiene o "
                          f"paga: «{c.get('motivo_cita')}». Comprobar en la transcripción que el cliente lo dice")
        if c.get("motivo_no_valoracion") == "incluido_en_otro_componente":
            otro = comps.get(c.get("incluido_en")) or {}
            decl = _incluye(_entrada_de(otro, catalogo), c.get("catalogo_id")) or {}
            salida.append(f"Motivo de {servicio(c.get('id'))}: incluido en {servicio(c.get('incluido_en'))} según el "
                          f"catálogo (fuente {decl.get('fuente_url') or decl.get('fuente') or 'no encontrada'})")
    limite = limite_retirada(fecha, semanas) if fecha else None
    for m in v.get("modelos") or []:
        if not isinstance(m, dict):
            continue
        ret = m.get("retirada") or "fecha de retirada aún no publicada"
        exigido = (f"; límite exigido {limite} (oferta del {str(fecha)[:10]} + {semanas or 0} semanas + "
                   f"{MESES_EXPLOTACION} meses)" if limite else "")
        plantilla = str(m.get("plantilla")).split("/", 1)[-1]  # D18-5: sin el prefijo «az-foundry/» del catálogo
        salida.append(f"Ciclo de vida del modelo «{plantilla}»: GA {m.get('ga') or 'sin fecha'}; retirada: {ret} "
                      f"(fuente {m.get('fuente')}){exigido}")
    salida += lineas_por_defecto(resp, catalogo)
    ajustes = [a for a in v.get("ajustes") or [] if isinstance(a, dict)]
    puestas = [a for a in ajustes if str(a.get("campo")).endswith(".referencia_id")]
    if puestas:
        salida.append("Referencias que el código puso desde el catálogo (la página de Learn de cada fila): " + "; ".join(
            f"{str(a.get('campo')).split('.')[1]} → {a.get('puesto')}"
            + (f" (el experto había puesto {a.get('recibido')})" if a.get("recibido") else "") for a in puestas))
    for a in ajustes:
        if a not in puestas:
            salida.append(f"Ajuste del código en {a.get('campo')}: «{a.get('recibido')}» pasa a «{a.get('puesto')}» "
                          f"({a.get('motivo')})")
    arq = _objeto(v.get("arquitectura"))
    if arq:
        salida.append(f"Arquitectura de referencia elegida: «{arq.get('titulo')}» ({arq.get('url')}, {arq.get('id')})")
    for s in sustituciones or []:
        if isinstance(s, dict):
            salida.append(f"Concepto del precio {s.get('precio_id')} fijado por el código desde la plantilla "
                          f"«{s.get('plantilla')}»: el experto escribió «{s.get('recibido')}» y vale «{s.get('fijado')}»")
    return salida


def _info_de(p: dict, comps: dict, catalogo: dict) -> dict | None:
    return resolver_plantilla(p.get("plantilla_id"), comps.get(p.get("componente_id")), catalogo)[0]


def _regiones_con_veto(catalogo: dict) -> set[str]:
    return {str(v.get("region") or "").strip().casefold() for e in _entradas(catalogo)
            for v in e.get("regiones_no_admitidas") or [] if isinstance(v, dict)}


def region_no_admitida(comp: dict, catalogo: dict, precios: list | None = None) -> str | None:
    """VERIF-3, REV-2 y REVER-1: motivo si el componente usa una región que el catálogo veta para su servicio, o None.

    El servicio vetado se reconoce, en este orden: por el identificado con (a) su catalogo_id o (b) el serviceName o
    productName del filtro de sus precios (identificar_servicio); así el nombre libre ya no esconde un servicio cuyo
    precio lo delata. Como red, también si el nombre contiene como frase completa un alias inequívoco del servicio
    vetado (con null, otro id o el nombre antiguo: «Azure Cognitive Search», «AI Search (S1)»). Los homoglifos
    habituales se pliegan antes; si el componente no lleva un catalogo_id del catálogo y aun así quedan letras no
    latinas, falla cerrado (REVSN-3: con su id, manda el id). Misma regla en verificar_paquete.region_no_admitida.
    I1.9 (PR18-1): un recurso que el cliente ya tiene no se despliega: su región es suya y no se veta.
    """
    region = str(comp.get("region") or "").strip().casefold()
    if region not in _regiones_con_veto(catalogo) or es_existente(comp):
        return None
    servicio, cid = comp.get("servicio"), comp.get("catalogo_id")
    inequivocos, ids = alias_inequivocos(catalogo), {e.get("id") for e in _entradas(catalogo)}
    ident = identificar_servicio(comp, catalogo, precios)
    for entrada in _entradas(catalogo):
        veto = next((v for v in entrada.get("regiones_no_admitidas") or []
                     if isinstance(v, dict) and str(v.get("region") or "").strip().casefold() == region), None)
        if veto is None:
            continue
        if ident["id"] is not None and ident["id"] == entrada.get("id"):
            por = "" if ident["por"] == "catalogo_id" else f" (identificado por el filtro de su precio {ident['precio']})"
        elif alias_en_nombre(servicio, inequivocos.get(entrada.get("id"), [])):
            otro = (f"; si el componente es {_nombres([ident['id']], catalogo)}, quita ese nombre"
                    if ident["id"] is not None else "")
            por = f" (reconocido por el nombre «{servicio}»{otro})"
        elif cid not in ids and _letras_no_latinas(servicio):
            # REVSN-3: solo sin catalogo_id del catálogo; con él, manda el id («Portal Łódź» con az-app-service pasa)
            por = f" (el nombre «{servicio}» lleva letras no latinas y no se puede descartar que sea este servicio)"
        else:
            continue
        return (f"{entrada.get('nombre_oficial')} en {veto.get('region')}{por}: {veto.get('motivo')} "
                f"(fuente {veto.get('fuente_url')}, consultada {veto.get('consultado')})")
    return None


AVISO_FUERA_DE_CATALOGO = "componente fuera del catálogo en una región con restricciones: comprobar disponibilidad"


def aviso_fuera_de_catalogo(comp: dict, catalogo: dict, precios: list | None = None) -> str | None:
    """VER-1 y REVER-1: en una región que el catálogo veta para ALGÚN servicio, todo componente que no se identifica
    por (a) su catalogo_id ni por (b) el filtro de sus precios se acepta con este aviso, que va a la nota del revisor,
    AUNQUE su nombre contenga el alias de otro servicio (el silencio solo se gana con un dato estructurado). None si
    no aplica o si region_no_admitida ya lo rechaza. Misma regla en verificar_paquete.aviso_fuera_de_catalogo."""
    region = str(comp.get("region") or "").strip().casefold()
    # CMP-1 (I1.3): «global» se veta para Bot Service (bot regional en la UE), pero no es una región en la que se
    # «compruebe disponibilidad»: un SaaS sin catalogo_id (SharePoint) en «global» no lleva este aviso.
    if region == "global" or region not in _regiones_con_veto(catalogo) or region_no_admitida(comp, catalogo, precios):
        return None
    if identificar_servicio(comp, catalogo, precios)["id"] is not None:
        return None
    return f"{comp.get('id')} «{comp.get('servicio')}» en {comp.get('region')}: {AVISO_FUERA_DE_CATALOGO}"


# REVERIF14-2 (I1.5): un componente con región de Azure (cualquiera distinta de «global») lleva el catalogo_id de su
# servicio. Sin él, un servicio facturable se podía declarar con nombre de SaaS y quedar fuera de la cobertura de
# precios (PR14-1, PR15-2) con solo un aviso. El SaaS que se licencia aparte y no está en el catálogo va en «global».
# Misma regla en verificar_paquete.region_exige_catalogo_replica.
def region_exige_catalogo(comp: dict) -> str | None:
    """Motivo de rechazo si el componente no lleva catalogo_id y su región no es «global»; None si cumple. I1.9: un
    recurso que el cliente ya tiene (es_existente) no se despliega y no lo exige."""
    if not isinstance(comp, dict) or comp.get("catalogo_id") or comp.get("region") == "global" or es_existente(comp):
        return None
    return (f"región «{comp.get('region')}» sin catalogo_id: todo componente con región de Azure lleva el catalogo_id "
            "de su servicio; un servicio que se licencia aparte y no está en el catálogo (p. ej. SharePoint) va en "
            "«global» (REVERIF14-2)")


# PR16-1 (I1.6, arreglos; LES-G-098.2): el catálogo trae la página de Learn propia de cada servicio (`referencia_url`) y
# el código la impone: la referencia de un componente con catalogo_id es EXACTAMENTE esa (URL normalizada). Antes bastaba
# cualquier URL de la lista blanca y el experto respaldaba SharePoint con la página de RAG de AI Search o Entra ID con la
# de autenticación de bots de Teams; el verificador objetaba una distinta en cada ronda y la solicitud se bloqueaba en R3.
# Misma regla en verificar_paquete.referencia_catalogo_replica (prueba de igualdad en tests/test_i16_arr_*.py).
def errores_referencia_catalogo(resp: dict, catalogo: dict) -> list[dict]:
    """[{"id", "regla", "detalle"}] de cada componente con catalogo_id del catálogo cuya referencia no es la
    `referencia_url` de su fila; [] si todas lo son. Un componente sin catalogo_id (o con uno desconocido, que ya es otro
    error) no entra; una referencia_id inexistente tampoco (ya es otro error)."""
    refs = {r.get("id"): r for r in resp.get("referencias") or [] if isinstance(r, dict)}
    salida = []
    for c in resp.get("componentes") or []:
        entrada = _entrada_de(c, catalogo)
        ref = refs.get(c.get("referencia_id")) if isinstance(c, dict) else None
        if entrada is None or ref is None:
            continue
        propia = normalizar_url(entrada.get("referencia_url"))
        if not propia:
            salida.append({"id": c.get("id"), "regla": "catalogo_sin_referencia", "detalle": (
                f"el catálogo montado no trae la referencia de Learn de {entrada.get('nombre_oficial')}: no se puede "
                "comprobar (falla cerrado)")})
        elif normalizar_url(ref.get("url")) != propia:
            salida.append({"id": c.get("id"), "regla": "referencia_no_catalogo", "detalle": (
                f"la referencia {c.get('referencia_id')} ({ref.get('url')}) no es la página de Learn de "
                f"{entrada.get('nombre_oficial')} en el catálogo: usa la referencia del catálogo: {entrada['referencia_url']} "
                "(añádela a referencias si no está; las demás páginas pueden ir como referencias de supuestos y "
                "riesgos) (PR16-1)")})
    return salida


# PR16-3 (I1.6) y REVERIF16-1 (I1.7, decisión del PM; LES-G-100.6): lo conservado entre rondas se compara por EFECTO
# (la suma de cantidad_mensual por servicio del catálogo y plantilla). La regla y el dato del brief son del papel R
# (verificacion.precios_conservar y errores_conservacion_efecto, CAMBIOS-I17-R §2): aquí solo se delega, para que el
# núcleo, el brief y la puerta usen una sola regla. Con any() se esquivaba añadiendo un duplicado con otro factor.
def _fmt_dec(d: Decimal | None) -> str:
    return "no numérico" if d is None else f"{d.normalize():f}".replace(".", ",")


def errores_conservacion(resp: dict, conservar: object, catalogo: dict | None = None) -> list[dict]:
    """[{"id", "regla", "detalle"}]: «conservado_ausente», «conservado_cambiado» o «conservar_forma» (dato de control
    con otra forma: falla cerrado, REVERIF16-2). I1.8: la regla vive aquí (conservacion_efecto, REV17-4 y REV17-5) y
    verificacion.errores_conservacion_efecto delega en ella (docs/I1/CAMBIOS-I18-P.md §6)."""
    return conservacion_efecto(resp, conservar)


# REV17-4 y REV17-5 (I1.8, decisión del PM): lo conservado se casa por servicio, COMPONENTE y plantilla, y lo valorado
# se separa de lo que es solo precio de referencia. Antes (I1.7) el dato quitaba los precios del componente corregido y
# la comprobación los sumaba igual: falso «conservado_cambiado» sin arreglo posible. Y un total nulo (un precio de
# referencia en el grupo) absorbía al valorado: null = null con cualquier cantidad.
def _clave_conservar(catalogo_id: object, componente_id: object, p: dict) -> tuple:
    """(catalogo_id, componente_id, «plantilla»|«filtro», valor, es_referencia)."""
    tipo, valor = (("plantilla", p["plantilla_id"]) if p.get("plantilla_id")
                   else ("filtro", " ".join(str(p.get("filtro") or "").split())))
    return (catalogo_id, componente_id, tipo, valor, p.get("cantidad_mensual") is None)


def _sumar_cantidades(cantidades: list) -> Decimal:
    """Suma exacta en Decimal de cantidades numéricas finitas (IntegridadRota con cualquier otra cosa)."""
    total = Decimal(0)
    for x in cantidades:
        d = _dec(x)
        if d is None:
            raise IntegridadRota(f"cantidad_mensual no numérica o no finita: {x!r}", [])
        total += d
    return total


def conservar_de(respuesta: dict, precio_ids: object = None) -> list[dict]:
    """El dato «conservar_precios» del brief de la ronda siguiente (forma de esquemas/brief.json): una entrada por
    servicio del catálogo, componente, plantilla (o filtro) y tipo, con la cantidad mensual TOTAL de sus precios
    valorados, o null si son precios de referencia. Solo los de `precio_ids` (los conservables que elige
    verificacion._precios_conservables; None = todos). IntegridadRota si una cantidad no es numérica."""
    comps = {c.get("id"): c for c in respuesta.get("componentes") or [] if isinstance(c, dict)}
    elegidos = None if precio_ids is None else set(precio_ids)
    grupos: dict[tuple, list[dict]] = {}
    for p in respuesta.get("precios") or []:
        if not isinstance(p, dict) or (elegidos is not None and p.get("id") not in elegidos):
            continue
        cid = p.get("componente_id")
        grupos.setdefault(_clave_conservar((comps.get(cid) or {}).get("catalogo_id"), cid, p), []).append(p)
    salida = []
    for (cat, cid, tipo, valor, ref), precios in grupos.items():
        total = None if ref else _sumar_cantidades([p.get("cantidad_mensual") for p in precios])
        salida.append({"catalogo_id": cat, "plantilla_id": valor if tipo == "plantilla" else None,
                       "filtro": valor if tipo == "filtro" else None,
                       "cantidad_mensual": None if total is None else _num_json(total),
                       "precio_ids": [p.get("id") for p in precios], "componente_ids": [cid]})
    return salida


def _iguales_6(a: Decimal, b: Decimal) -> bool:
    """Iguales a 6 decimales; si un número es tan grande que no se puede cuantizar, iguales exactos."""
    try:
        return a.quantize(CUANTO_CANTIDAD) == b.quantize(CUANTO_CANTIDAD)
    except InvalidOperation:
        return a == b


def _error_cons(ident: str, regla: str, detalle: str) -> dict:
    return {"id": ident, "regla": regla, "detalle": detalle}


def conservacion_efecto(respuesta: dict, conservar: object) -> list[dict]:
    """Por cada entrada de conservar_precios (servicio, componentes, plantilla y tipo), los precios de la respuesta
    nueva con esa clave en esos componentes: si es valorada, su suma de cantidad_mensual tiene que ser la conservada (a 6
    decimales; los ids de precio se pueden renumerar); si es de referencia, tiene que seguir habiendo alguno. Errores:
    «conservado_ausente», «conservado_cambiado» o «conservar_forma» (no es lista, o una entrada sin plantilla ni filtro,
    sin cantidad_mensual o con componente_ids que no es una lista de ids: nunca se apaga en silencio). Una entrada de
    I1.7 (varios componentes) se compara con la suma de todos ellos, y una de I1.6 (sin la clave componente_ids), con la
    de todos los componentes de su catalogo_id, como entonces."""
    if conservar is None:
        return []
    if not isinstance(conservar, list):
        return [_error_cons("conservar_precios", "conservar_forma", f"conservar_precios no es una lista "
                            f"({type(conservar).__name__}): no se apaga la conservación en silencio (REVERIF16-2)")]
    errores, pedidos = [], {}
    for n, c in enumerate(conservar):
        comps_c = c.get("componente_ids") if isinstance(c, dict) else None
        legado = isinstance(c, dict) and "componente_ids" not in c
        if (not isinstance(c, dict) or not (c.get("plantilla_id") or c.get("filtro")) or "cantidad_mensual" not in c
                or not legado and (not isinstance(comps_c, list) or not comps_c
                                   or not all(isinstance(x, str) for x in comps_c))):
            errores.append(_error_cons(f"conservar_precios[{n}]", "conservar_forma", f"conservar_precios[{n}] sin "
                                       "plantilla_id ni filtro, sin cantidad_mensual o con componente_ids no válido"))
            continue
        k = _clave_conservar(c.get("catalogo_id"), None if legado else tuple(sorted(set(comps_c))), c)
        pedidos.setdefault(k, []).append(c.get("cantidad_mensual"))
    try:
        esperados = {k: None if k[4] else _sumar_cantidades(v) for k, v in pedidos.items()}
    except IntegridadRota as e:
        return errores + [_error_cons("conservar_precios", "conservar_forma", str(e))]
    comps = {c.get("id"): c for c in (respuesta if isinstance(respuesta, dict) else {}).get("componentes") or []
             if isinstance(c, dict)}
    precios = [p for p in (respuesta if isinstance(respuesta, dict) else {}).get("precios") or [] if isinstance(p, dict)]
    for (cat, cids, tipo, valor, ref), total in esperados.items():
        etiqueta = f"{cat} · {valor}" + (f" · {', '.join(cids)}" if cids else "") + (" (precio de referencia)" if ref else "")
        hay = [p for p in precios if (cids is None or p.get("componente_id") in cids)
               and _clave_conservar((comps.get(p.get("componente_id")) or {}).get("catalogo_id"), None, p)
               == (cat, None, tipo, valor, ref)]
        if not hay:
            errores.append(_error_cons(etiqueta, "conservado_ausente", f"conservar_precios: {etiqueta} desaparece de la "
                                       "respuesta; consérvalo" + (f" en {', '.join(cids)}" if cids else "") + ("" if ref else " con "
                                       f"cantidad_mensual total {_fmt_dec(total)}")))
            continue
        if ref:
            continue
        try:
            nuevo = _sumar_cantidades([p.get("cantidad_mensual") for p in hay])
        except IntegridadRota as e:
            errores.append(_error_cons(etiqueta, "conservado_cambiado", f"conservar_precios: {etiqueta}: {e}"))
            continue
        if not _iguales_6(nuevo, total):
            errores.append(_error_cons(etiqueta, "conservado_cambiado", f"conservar_precios: {etiqueta}: la cantidad "
                                       f"mensual total era {_fmt_dec(total)} y la respuesta da {_fmt_dec(nuevo)} en "
                                       f"{len(hay)} precio(s); conserva plantilla y cantidades"))
    return errores


# ── I1.7 · contrato v4 (decisiones del comercial del 13-10-2026 y decisiones del PM, fallar cerrado) ──────────────────────
# (1) Precios por instantánea: el código descarga al desplegar el precio de TODAS las plantillas del catálogo
#     (catalogo/precios_instantanea.json, copia byte a byte en sandbox/datos/); el experto solo elige plantilla y
#     cantidades, y el núcleo pone filtro, precio, unidad, vigencia y concepto (LES-G-090.9, LES-G-095.4).
# (2) Factores en el catálogo con su fuente; el código hace la cuenta y el experto solo los cambia citando un requisito
#     de dimensionamiento (factor_override), marcado para el revisor (LES-G-100.5). Modelo por defecto: el del catálogo.
# Reglas del PM: ciclo de vida del modelo, motivos con condición, campos de dimensionamiento para el nivel, comillas
# normalizadas en las citas y conservación por efecto entre rondas (LES-G-100.6). docs/I1/CAMBIOS-I17-P.md.
ESQUEMA_INSTANTANEA = "preventa-precios-instantanea/1"
NOMBRE_INSTANTANEA = "precios_instantanea.json"
EDAD_MAXIMA_INSTANTANEA_DIAS = 31
HORAS_MES = Decimal(730)
# Unidad de Retail Prices de una plantilla de tiempo → cantidad al mes por instancia (730 h; «1/Day», 730/24 días).
UNIDADES_TIEMPO = {"1 Hour": HORAS_MES, "1/Hour": HORAS_MES, "1 GiB Hour": HORAS_MES, "1/Day": HORAS_MES / 24,
                   "1/Month": Decimal(1), "1 GB/Month": Decimal(1)}
# I1.8 (N7, CAMBIOS-I18-E §3.1): «1 GB/Month» es el almacenamiento APROVISIONADO (SQL Database GP, PostgreSQL): se paga
# el tamaño configurado, no los datos; por instancia y mes, multiplicado por los GB por instancia de la plantilla.
UNIDADES_TIEMPO_TEXTO = {"1 Hour": "h", "1/Hour": "h", "1 GiB Hour": "GiB·h", "1/Day": "días", "1/Month": "mes",
                         "1 GB/Month": "GB·mes"}
CUANTO_CANTIDAD = Decimal("0.000001")  # cantidad_mensual con 6 decimales, ROUND_HALF_UP
MESES_EXPLOTACION = 12
CAMPOS_DIMENSIONAMIENTO = ("volumetria", "alcance_funcional", "identidad_acl_origen", "marco_normativo",
                           "ubicacion_usuarios", "canales_integraciones")
# Etiqueta o sección del brief de cada campo de dimensionamiento (brief.generar).
_DIM_ETIQUETAS = {"Volumetría": "volumetria", "Identidad y permisos del origen": "identidad_acl_origen",
                  "Marco normativo": "marco_normativo", "Ubicación de los usuarios finales": "ubicacion_usuarios"}
_DIM_SECCIONES = {"## Alcance funcional": "alcance_funcional", "## Canales e integraciones": "canales_integraciones"}
# I1.9: etiqueta de cada línea de requisitos del brief y su campo (una razón de subida puede pedir, p. ej., red_privada)
_ETIQUETAS_CAMPO = {**_DIM_ETIQUETAS, **{etq: campo for campo, etq in brief_mod.ETIQUETAS_CONTEXTO},
                    "Objetivo": "objetivo", "Nubes": "nubes"}
# Pares de comillas que pueden envolver una cita entera; solo se quita un par y solo si dentro no queda ninguna de las dos.
COMILLAS = (("«", "»"), ('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’"), ("„", "“"))
_CLAVE_PLANTILLA = re.compile(r"^((az|gcp|aws)-[a-z0-9-]{2,40}/)?[a-z0-9][a-z0-9.-]{0,59}$")

# ── Multinube (04-11-2026, esquemas/MULTINUBE.md) · procedencia de la moneda y forma propia de cada pilar ─────────────
# Todo importe es EUR; la instantánea dice de dónde sale ese euro (fuente_moneda). Sin la clave solo vale en Azure, y
# solo si su `fuente` es la consulta de Retail Prices en EUR (la instantánea vigente de Azure no cambia ni un byte).
# AWS publica en USD: EUR = USD / tipo de referencia del BCE (1 EUR = tasa USD), con 6 decimales ROUND_HALF_UP.
FUENTE_MONEDA = {"azure": "azure_retail_eur", "gcp": "gcp_catalog_eur", "aws": "aws_usd_convertido_bce"}
# Regiones de AWS en la UE (Knowledge MCP de AWS, 2026-11-04; estudio de AWS y Google (no publicado) §7.1): lista
# blanca, nunca «empieza por eu-» (eu-west-2 es Londres y eu-central-2, Zúrich).
REGIONES_UE_AWS = ("eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1", "eu-south-1", "eu-south-2")
CLAVE_REGION_FILTRO = {"azure": "armRegionName", "gcp": "region", "aws": "regionCode"}
PREFIJO_ID = {"azure": "az-", "gcp": "gcp-", "aws": "aws-"}
CAMPOS_ID_PRECIO = {"azure": (), "gcp": ("sku_id",), "aws": ("sku", "codigo_oferta", "precio_origen_usd")}
_CAMPOS_ID_TODOS = frozenset(c for v in CAMPOS_ID_PRECIO.values() for c in v) | {"meterId"}
CUANTO_EUR_AWS = Decimal("0.000001")
# El BCE no publica en fines de semana ni en cierres TARGET (Semana Santa: 4 días): un tipo de más de 7 días antes de la
# consulta es un tipo viejo puesto en silencio (LES-G-047), no el último publicado.
MAX_DIAS_TIPO_BCE = 7
# Procedencia implícita de Azure: la fuente es Retail Prices consultada en EUR (las dos formas de las instantáneas vigentes:
# «(currencyCode=EUR, …)» y «?currencyCode='EUR'»).
_FUENTE_RETAIL_EUR = re.compile(r"prices\.azure\.com/api/retail/prices\b.*\bcurrencyCode\s*=\s*'?EUR'?(?![A-Za-z])")


def eur_desde_usd(usd: object, tasa: object) -> Decimal:
    """EUR = USD / tasa (1 EUR = tasa USD), 6 decimales ROUND_HALF_UP. ValueError si no son números finitos > 0."""
    from decimal import ROUND_HALF_UP
    u, t = (Decimal(str(x)) if isinstance(x, (int, float)) and not isinstance(x, bool) else Decimal("NaN")
            for x in (usd, tasa))
    if not (u.is_finite() and t.is_finite()) or u < 0 or t <= 0:
        raise ValueError(f"precio USD {usd!r} o tipo {tasa!r} no válido")
    return (u / t).quantize(CUANTO_EUR_AWS, rounding=ROUND_HALF_UP)


def pilar_instantanea(inst: object) -> str:
    """Pilar de la instantánea («azure» sin la clave); el esquema ya lo limita a la lista blanca."""
    return inst.get("pilar", est_mod.PILAR_POR_DEFECTO) if isinstance(inst, dict) else est_mod.PILAR_POR_DEFECTO


def errores_procedencia(inst: dict) -> list[str]:
    """Procedencia de la moneda y campos propios del pilar de una instantánea que ya valida su esquema; [] si cuadra."""
    pilar = pilar_instantanea(inst)
    fm = inst.get("fuente_moneda")
    errores = []
    if fm is None and pilar != "azure":
        errores.append(f"la instantánea no declara la procedencia de la moneda (fuente_moneda; para {pilar}: "
                       f"«{FUENTE_MONEDA[pilar]}»)")
    elif fm is not None and fm != FUENTE_MONEDA[pilar]:
        errores.append(f"fuente_moneda «{fm}» no es la de {pilar} («{FUENTE_MONEDA[pilar]}»)")
    if pilar == "azure" and not _FUENTE_RETAIL_EUR.search(str(inst.get("fuente"))):   # con la clave o sin ella (Revisión)
        errores.append("la instantánea de Azure no declara la procedencia de la moneda (fuente: Retail Prices con "
                       "currencyCode=EUR)")
    bce = [k for k in ("tipo_bce", "fecha_tipo_bce") if k in inst]
    consulta = fecha_instantanea(inst)
    if pilar != "aws" and bce:
        errores.append(f"{', '.join(bce)} solo vale en AWS (precios en USD convertidos con el BCE)")
    elif pilar == "aws":
        if len(bce) != 2:
            errores.append("AWS exige tipo_bce y fecha_tipo_bce (EUR = USD / tipo de referencia del BCE)")
        else:
            try:
                fecha_bce = datetime.date.fromisoformat(inst["fecha_tipo_bce"])
                dias = (datetime.date.fromisoformat(consulta) - fecha_bce).days
            except ValueError:
                fecha_bce = dias = None
            tasa = Decimal(str(inst["tipo_bce"]))
            if tasa != tasa.quantize(Decimal("0.0001")):   # el BCE publica con cuatro decimales (Revisión)
                errores.append(f"tipo_bce {inst['tipo_bce']} no tiene los cuatro decimales con los que publica el BCE")
            if dias is None or not 0 <= dias <= MAX_DIAS_TIPO_BCE or fecha_bce.weekday() >= 5:
                errores.append(f"fecha_tipo_bce {inst['fecha_tipo_bce']} no es un día hábil del BCE de los "
                               f"{MAX_DIAS_TIPO_BCE} anteriores a la consulta ({consulta})")
    for clave, art in inst["plantillas"].items():
        if "/" in clave and not clave.startswith(PREFIJO_ID[pilar]):
            errores.append(f"plantillas.{clave}: el id de catálogo no es de {pilar} (prefijo «{PREFIJO_ID[pilar]}»)")
        exigidos = set(CAMPOS_ID_PRECIO[pilar])
        faltan = sorted(exigidos - set(art))
        ajenos = sorted((set(art) & _CAMPOS_ID_TODOS) - exigidos - ({"meterId"} if pilar == "azure" else set()))
        ajenos += ["tramos[].precio_origen_usd"] if pilar != "aws" and any(
            "precio_origen_usd" in x for x in art.get("tramos") or []) else []
        if faltan or ajenos:
            errores.append(f"plantillas.{clave}: identificador de precio de {pilar}: faltan {faltan or '-'}, sobran "
                           f"{ajenos or '-'}")
            continue
        if pilar != "aws" or len(bce) != 2:
            continue
        if art.get("armRegionName") not in REGIONES_UE_AWS:
            errores.append(f"plantillas.{clave}: región «{art.get('armRegionName')}» fuera de la UE (admitidas: "
                           f"{', '.join(REGIONES_UE_AWS)})")
        pares = [(art["precio_origen_usd"], art["precio_unitario"])] + [
            (x.get("precio_origen_usd"), x["precio_unitario"]) for x in art.get("tramos") or []]
        for usd, eur in pares:
            try:
                bien = eur_desde_usd(usd, inst["tipo_bce"]) == Decimal(str(eur))
            except ValueError:
                bien = False
            if not bien:
                errores.append(f"plantillas.{clave}: {eur} EUR no es {usd!r} USD / {inst['tipo_bce']} con 6 decimales")
                break
    return errores


def quitar_comillas(texto: object) -> object:
    """La cita sin UN par de comillas que la envuelva entera (equivalencia demostrable: dentro no queda ninguna de las
    dos). Lo que no es texto se devuelve igual; «a» y «b» no se toca."""
    if not isinstance(texto, str):
        return texto
    t = texto.strip()
    for a, b in COMILLAS:
        if len(t) >= 2 and t.startswith(a) and t.endswith(b) and a not in t[1:-1] and b not in t[1:-1]:
            return t[1:-1].strip()
    return texto


def sha256_instantanea(inst: dict) -> str:
    """SHA-256 del JSON canónico (hashes.json_canonico) de la instantánea sin su clave «sha256»."""
    from nucleo import hashes
    return hashes.hash_json({k: v for k, v in inst.items() if k != "sha256"})


def errores_instantanea(inst: object) -> list[str]:
    """Forma, huella y artículos de la instantánea de precios; [] si es válida."""
    if not isinstance(inst, dict):
        return ["la instantánea de precios no es un objeto JSON"]
    raiz = esquema.cargar("precios_instantanea")
    errores = list(esquema.validar(inst, raiz))
    if errores:
        return errores
    articulo = {"$defs": raiz["$defs"], "$ref": "#/$defs/articulo"}
    region_filtro = CLAVE_REGION_FILTRO[pilar_instantanea(inst)]
    for clave, art in inst["plantillas"].items():
        if not _CLAVE_PLANTILLA.match(clave):
            errores.append(f"plantillas.{clave}: clave no válida (se espera «<catalogo_id>/<plantilla_id>»)")
        propios = [f"plantillas.{clave}{e[1:]}" for e in esquema.validar(art, articulo)]
        if not propios and valores_filtro(art.get("filtro"), region_filtro) != [art.get("armRegionName")]:
            propios.append(f"plantillas.{clave}: armRegionName «{art.get('armRegionName')}» no es el "
                           f"{'' if region_filtro == 'armRegionName' else region_filtro + ' '}del filtro")
        if not propios and not math.isfinite(art["precio_unitario"]):
            propios.append(f"plantillas.{clave}: precio_unitario no finito")
        if not propios and "tramos" in art:
            desde = [x["desde"] for x in art["tramos"]]
            primero = art["tramos"][0]["precio_unitario"] != art["precio_unitario"]
            if desde[0] != 0 or any(b <= a for a, b in zip(desde, desde[1:])) or primero:
                propios.append(f"plantillas.{clave}: tramos no válidos (el primero desde 0 con el precio_unitario, "
                               "y luego crecientes)")
        errores += propios
    if not inst["plantillas"]:
        errores.append("la instantánea no trae ninguna plantilla")
    try:
        datetime.datetime.fromisoformat(inst["fecha_consulta"].replace("Z", "+00:00"))
    except ValueError:
        errores.append(f"fecha_consulta no es una fecha ISO: {inst['fecha_consulta']}")
    if not errores:
        errores += errores_procedencia(inst)
    if not errores and sha256_instantanea(inst) != inst["sha256"]:
        errores.append("sha256 no es el del contenido de la instantánea (alterada o escrita a mano)")
    return errores


def fecha_instantanea(inst: dict) -> str:
    """AAAA-MM-DD (UTC) de la consulta de la instantánea."""
    return str(inst.get("fecha_consulta") or "")[:10]


def errores_edad_instantanea(fecha_consulta: object, fecha_ref: object) -> list[str]:
    """La instantánea vale si se consultó entre 0 y EDAD_MAXIMA_INSTANTANEA_DIAS días antes de fecha_ref (AAAA-MM-DD)."""
    try:
        consulta = datetime.date.fromisoformat(str(fecha_consulta)[:10])
        ref = datetime.date.fromisoformat(str(fecha_ref)[:10])
    except ValueError:
        return [f"no se puede comparar la fecha de la instantánea ({fecha_consulta!r}) con {fecha_ref!r}"]
    dias = (ref - consulta).days
    if dias > EDAD_MAXIMA_INSTANTANEA_DIAS:
        return [f"la instantánea de precios se consultó el {consulta} ({dias} días antes del {ref}; el máximo es "
                f"{EDAD_MAXIMA_INSTANTANEA_DIAS}): redesplegar para descargar precios nuevos"]
    if dias < 0:
        return [f"la instantánea de precios ({consulta}) es posterior a la fecha de referencia ({ref})"]
    return []


def clave_plantilla(fila: dict, plantilla: dict) -> str:
    return f"{fila.get('id')}/{plantilla.get('id')}"


def articulo_instantanea(inst: dict, fila: dict, plantilla: dict) -> dict | None:
    """El artículo de la plantilla en la instantánea: por «<catalogo_id>/<plantilla_id>» o, si no está, por el id suelto;
    en los dos casos su filtro tiene que ser EXACTAMENTE el de la plantilla del catálogo (si no, None)."""
    arts = (inst if isinstance(inst, dict) else {}).get("plantillas")
    if not isinstance(arts, dict):
        return None
    art = arts.get(clave_plantilla(fila, plantilla))
    if art is None:
        art = arts.get(plantilla.get("id"))
    return art if isinstance(art, dict) and art.get("filtro") == plantilla.get("filtro") else None


def errores_instantanea_catalogo(inst: dict, catalogo: dict) -> list[str]:
    """Cada plantilla del catálogo montado tiene su artículo en la instantánea con el mismo filtro (decisión 1: TODAS)."""
    return [f"la instantánea no trae el precio de la plantilla «{clave_plantilla(e, p)}» con su filtro del catálogo"
            for e in _entradas(catalogo) for p in e.get("plantillas_precio") or []
            if isinstance(p, dict) and articulo_instantanea(inst, e, p) is None]


def resolver_plantilla(plantilla_id: object, comp: object, catalogo: dict) -> tuple[dict | None, str | None]:
    """({"plantilla", "fila", "auxiliar", "clave"}, None) o (None, motivo). `plantilla_id` es el id de una plantilla de la
    fila del componente o de un precio auxiliar que lo acompaña; con prefijo «<catalogo_id>/», esa fila exactamente."""
    entrada = _entrada_de(comp, catalogo)
    if entrada is None:
        return None, ("una línea de consumo solo vale para un componente del catálogo (un servicio fuera del catálogo va "
                      "sin precio, con su motivo «fuera_del_catalogo», y lo cotiza el revisor)")
    pid = plantilla_id if isinstance(plantilla_id, str) else ""
    prefijo, _, suelto = pid.rpartition("/")
    candidatos = [(entrada, False)] + [(fila, True) for a in precios_auxiliares(catalogo)
                                       if entrada.get("id") in (a.get("componentes") or [])
                                       for fila in [plantillas_auxiliar(a, catalogo)[1]] if fila]
    admitidas = []
    for fila, auxiliar in candidatos:
        ids_aux = None
        if auxiliar:
            ids_aux = {p.get("id") for a in precios_auxiliares(catalogo) if a.get("plantillas_de") == fila.get("id")
                       for p in plantillas_auxiliar(a, catalogo)[0]}
        for p in fila.get("plantillas_precio") or []:
            if not isinstance(p, dict) or (ids_aux is not None and p.get("id") not in ids_aux):
                continue
            admitidas.append(clave_plantilla(fila, p))
            if p.get("id") == suelto and prefijo in ("", fila.get("id")):
                return {"plantilla": p, "fila": fila, "auxiliar": auxiliar, "clave": clave_plantilla(fila, p)}, None
    return None, (f"plantilla_id «{pid}» no es una plantilla de {entrada.get('nombre_oficial')} ({entrada.get('id')}) "
                  f"ni de un precio auxiliar que lo acompañe (admite: {', '.join(admitidas) or 'ninguna'})")


def _texto_no_vacio(x: object) -> str | None:
    return " ".join(x.split()) if isinstance(x, str) and x.strip() else None


def factor_estandar(info: dict, catalogo: dict) -> tuple[dict | None, str | None]:
    """(factor, None), (None, None) si el catálogo no da factor para la plantilla, o (None, motivo) si lo da incompleto o
    ambiguo (falla cerrado). Se busca, en este orden y sin mezclar: `factor_estandar` de la plantilla (objeto o id), y
    las entradas de `factores_estandar` de la fila y del catálogo que la nombran en `plantilla` o `plantillas` (id suelto
    en la fila; «<catalogo_id>/<id>» en el catálogo) o cuyo `id` cita la plantilla. Cada factor: valor > 0, unidad,
    fuente y justificación; `base` (texto o lista: la palabra de la unidad de base, «consulta») y `caso_uso` opcionales."""
    pl, fila = info["plantilla"], info["fila"]
    propio = pl.get("factor_estandar")
    listas = [(fila.get("factores_estandar"), False), ((catalogo or {}).get("factores_estandar"), True)]
    entradas = [(x, q) for lista, q in listas if isinstance(lista, list) for x in lista if isinstance(x, dict)]
    if isinstance(propio, dict):
        hallados = [propio]
    elif isinstance(propio, str):
        hallados = [x for x, _ in entradas if x.get("id") == propio]
        if not hallados:
            return None, f"la plantilla «{info['clave']}» cita el factor «{propio}», que el catálogo no trae"
    else:
        def nombra(x: dict, q: bool) -> bool:
            varias = x.get("plantillas")
            ids = [x.get("plantilla")] + (varias if isinstance(varias, list) else [])
            return (info["clave"] in ids) or (not q and pl.get("id") in ids)
        hallados = [x for x, q in entradas if nombra(x, q)]
    if not hallados:
        return None, None
    if len(hallados) > 1:
        return None, (f"el catálogo da {len(hallados)} factores estándar para «{info['clave']}» y el código no puede "
                      "elegir uno (falla cerrado): usa factor_override con un requisito citado")
    return _factor_valido(hallados[0], info["clave"])


def _factor_valido(f: dict, clave: str) -> tuple[dict | None, str | None]:
    """(factor normalizado, None) o (None, motivo) si le falta valor > 0, unidad, fuente o justificación."""
    info = {"clave": clave}
    valor = _dec(f.get("valor"))
    campos = {k: _texto_no_vacio(f.get(k)) for k in ("unidad", "justificacion")}
    fuente = _texto_no_vacio(f.get("fuente")) or _texto_no_vacio(f.get("fuente_url"))
    if valor is None or valor <= 0 or not all(campos.values()) or not fuente:
        return None, (f"el factor estándar del catálogo para «{info['clave']}» está incompleto (valor > 0, unidad, "
                      "fuente y justificación): no se puede valorar con él (falla cerrado)")
    base = f.get("base")
    bases = [b for b in (base if isinstance(base, list) else [base]) if _texto_no_vacio(b)]
    return {"valor": valor, "valor_json": f.get("valor"), "unidad": campos["unidad"], "justificacion": campos["justificacion"],
            "fuente": fuente, "bases": bases, "caso_uso": _texto_no_vacio(f.get("caso_uso")),
            "id": _texto_no_vacio(f.get("id"))}, None


def factores_alternativos(info: dict, catalogo: dict) -> tuple[list[dict], str | None]:
    """E19-2 (I1.9, PR18-5): los factores de `factores_alternativos` de la plantilla (ids de `factores_estandar` de la
    fila o del catálogo), validados como el estándar. ([], None) si no declara ninguno; ([], motivo) si uno no existe,
    está repetido, está incompleto o no declara su `base` (sin base el código no puede elegirlo: falla cerrado)."""
    lista = info["plantilla"].get("factores_alternativos")
    if lista is None:
        return [], None
    if not isinstance(lista, list) or not all(isinstance(x, str) and x.strip() for x in lista):
        return [], f"la plantilla «{info['clave']}» trae factores_alternativos mal formados (falla cerrado)"
    entradas = [x for lista_f in (info["fila"].get("factores_estandar"), (catalogo or {}).get("factores_estandar"))
                if isinstance(lista_f, list) for x in lista_f if isinstance(x, dict)]
    salida = []
    for fid in lista:
        hallados = [x for x in entradas if x.get("id") == fid]
        if len(hallados) != 1:
            return [], (f"el factor alternativo «{fid}» de «{info['clave']}» no está (o está repetido) en el catálogo "
                        "(falla cerrado)")
        f, problema = _factor_valido(hallados[0], info["clave"])
        if problema:
            return [], problema
        if not f["bases"]:
            return [], f"el factor alternativo «{fid}» de «{info['clave']}» no declara su base (falla cerrado)"
        salida.append(f)
    return salida, None


def factor_por_base(info: dict, catalogo: dict, cita: object, unidad_base: object) -> tuple[dict | None, str | None]:
    """E19-2 (I1.9, PR18-5): el factor del catálogo que cuenta lo que dice la base. Sin factores alternativos, el
    estándar (como en I1.8). Con ellos, el único entre el estándar y los alternativos cuya `base` casa con la cita y con
    unidad_base (base_casa): «1.500 acciones al mes» con unidad_base «acciones» elige el factor por acción. Si no casa
    ninguno, el estándar (y base_no_casa lo dirá); si casa más de uno, (None, motivo): falla cerrado."""
    std, problema = factor_estandar(info, catalogo)
    if problema or std is None:
        return std, problema
    alternativos, problema = factores_alternativos(info, catalogo)
    if problema:
        return None, problema
    if not alternativos:
        return std, None
    if not std["bases"]:
        return None, (f"el factor estándar de «{info['clave']}» no declara su base y la plantilla tiene factores "
                      "alternativos: el código no puede elegir (falla cerrado)")
    casan = [f for f in [std] + alternativos if base_casa(cita, unidad_base, f["bases"])]
    if len(casan) > 1:
        return None, (f"la cita «{cita}» y unidad_base «{unidad_base}» casan con más de una base de «{info['clave']}» "
                      f"(«{'», «'.join(b for f in casan for b in f['bases'])}»): pon en unidad_base solo la palabra de "
                      "lo que cuenta la base, y la cita de esa magnitud (falla cerrado)")
    return (casan[0] if casan else std), None


def bases_admitidas(info: dict | None, catalogo: dict) -> list[str]:
    """Las bases del factor estándar y de sus alternativos (para decirle al experto qué puede contar la base)."""
    if not info:
        return []
    std = factor_estandar(info, catalogo)[0]
    alternativos = factores_alternativos(info, catalogo)[0]
    return list(dict.fromkeys(b for f in ([std] if std else []) + alternativos for b in f["bases"]))


def citas_dimensionamiento(requisitos: object, brief_texto: object) -> list[str]:
    """Textos que valen como cita de una justificación de nivel o de un factor_override: el valor de cada entrada de los
    campos de CAMPOS_DIMENSIONAMIENTO y, en el brief, los valores de sus líneas (enteras y partidas por «; ») y las
    viñetas de «Alcance funcional» y «Canales e integraciones», sin la marca de ASUMIDO. Decisión del PM (PR16-4)."""
    return citas_de_campos(requisitos, brief_texto, CAMPOS_DIMENSIONAMIENTO)


def citas_de_campos(requisitos: object, brief_texto: object, campos: tuple, sin_asumido: bool = False) -> list[str]:
    """Textos que valen como cita de los campos `campos` (en ese orden): el valor de cada entrada de esos campos en los
    requisitos y, en el brief, los valores de sus líneas (enteras y partidas por «; ») y las viñetas de «Alcance
    funcional» y «Canales e integraciones», sin la marca de ASUMIDO. I1.9: una razón de subida de nivel de tipo
    «umbral» solo admite citas de su campo (la volumetría). `sin_asumido` (I1.9, razón de subida): nada ASUMIDO vale
    (ni un campo en ASUMIDO, ni una entrada de origen ASUMIDO, ni una línea del brief con la marca): una suposición
    nunca sube un nivel ni cambia el modelo."""
    salida = [_plano_req(e.get("valor")) for k in campos for e in _entradas_req(requisitos, k)
              if not sin_asumido or (e.get("origen") != "ASUMIDO"
                                     and _objeto(_campos_req(requisitos).get(k)).get("estado") != "ASUMIDO")]
    seccion = None
    for ln in _lineas_requisitos(brief_texto):
        if ln.startswith("#"):
            seccion = _DIM_SECCIONES.get(ln.strip())
            continue
        t, campo = None, None
        if ln.startswith("- ") and seccion:
            t, campo = ln[2:], seccion
        else:
            for etq, k in _ETIQUETAS_CAMPO.items():
                if ln.startswith(etq + ": "):
                    t, campo = ln[len(etq) + 2:], k
        if t is None or campo is None or campo not in campos or (sin_asumido and t.endswith(MARCA_ASUMIDO)):
            continue
        t = t[:-len(MARCA_ASUMIDO)] if t.endswith(MARCA_ASUMIDO) else t
        salida += [_plano_req(t)] + [_plano_req(s) for s in t.split("; ")]
    return [s for s in dict.fromkeys(salida) if s]


def _raiz(palabra: str) -> str:
    """Raíz para casar singular y plural: sin la «s» o «es» final si quedan 4 letras o más."""
    for fin in ("es", "s"):
        if palabra.endswith(fin) and len(palabra) - len(fin) >= 4:
            return palabra[:-len(fin)]
    return palabra


def base_casa(cita: object, unidad_base: object, bases: list[str]) -> bool:
    """REV16-4: la cita habla de la unidad de base. Con `bases` del factor estándar, la cita y unidad_base contienen una
    palabra con la raíz de alguna; sin ellas, la cita contiene la raíz de una palabra de 4 letras o más de unidad_base."""
    tc, tu = [_raiz(t) for t in _tokens(cita)], [_raiz(t) for t in _tokens(unidad_base)]
    if bases:
        raices = [_raiz(t) for b in bases for t in _tokens(b) if len(t) >= 4]
        return any(t.startswith(r) for r in raices for t in tc) and any(t.startswith(r) for r in raices for t in tu)
    return any(len(u) >= 4 and any(t.startswith(u) or u.startswith(t) and len(t) >= 4 for t in tc) for u in tu)


CANTIDAD_MAXIMA = Decimal("1e12")  # por encima, la cuenta no es de un consumo real (y el Decimal no la cuantiza)


def _cantidad(d: Decimal) -> Decimal | None:
    """cantidad_mensual con 6 decimales (ROUND_HALF_UP); None si pasa de CANTIDAD_MAXIMA (Revisión I1.7: con un factor de
    1e100 la cuantización lanzaba InvalidOperation fuera de control)."""
    from decimal import ROUND_HALF_UP
    return None if abs(d) > CANTIDAD_MAXIMA else d.quantize(CUANTO_CANTIDAD, rounding=ROUND_HALF_UP)


def _num_json(d: Decimal) -> int | float:
    """Número JSON de un Decimal ya cuantizado: entero si no tiene decimales."""
    return int(d) if d == d.to_integral_value() else float(d)


def _fecha_ref(catalogo: dict, inst: dict) -> str:
    f = str((catalogo or {}).get("fecha") or "")
    return f if re.fullmatch(r"\d{4}-\d{2}-\d{2}", f) else fecha_instantanea(inst)


def _volumen(p: dict, info: dict, base: dict, citas_dim: list[str], catalogo: dict, mal, ajuste) -> tuple:
    """(base completada con su factor, cantidad Decimal, supuesto) o (None, None, None) si no se puede completar."""
    pid, cl = p.get("id"), info["clave"]
    std, problema = factor_por_base(info, catalogo, base.get("cita"), base.get("unidad_base"))  # E19-2
    over = p.get("factor_override")
    if isinstance(over, dict):
        cita_o = quitar_comillas(over.get("cita"))
        ajuste(f"precios.{pid}.factor_override.cita", over.get("cita"), cita_o, "comillas que envolvían la cita")
        if _plano_req(cita_o) not in citas_dim:
            mal(pid, "override_cita_no_literal", f"factor_override.cita «{cita_o}» no es una cita literal de un campo de "
                f"dimensionamiento ({', '.join(CAMPOS_DIMENSIONAMIENTO)}): copia una del brief, carácter a carácter")
            return None, None, None
        valor = _dec(over.get("valor"))
        factor = {"valor": over.get("valor"), "unidad": std["unidad"] if std else f"{base.get('unidad_base')} (factor)",
                  "justificacion": over.get("justificacion"), "fuente": f"requisito citado: «{cita_o}»"[:300],
                  "origen": "experto", "caso_uso": std["caso_uso"] if std else None}
    elif problema:
        mal(pid, "factor_estandar_no_valido", problema)
        return None, None, None
    elif std is None:
        mal(pid, "factor_sin_estandar", f"el catálogo no da factor estándar para «{cl}»: no se puede valorar con él "
            "salvo con factor_override y un requisito de dimensionamiento citado que lo justifique (LES-G-100.5)")
        return None, None, None
    else:
        valor = std["valor"]
        factor = {"valor": std["valor_json"], "unidad": std["unidad"], "justificacion": std["justificacion"],
                  "fuente": std["fuente"], "origen": "catalogo", "caso_uso": std["caso_uso"]}
    if not base_casa(base.get("cita"), base.get("unidad_base"), (std or {}).get("bases") or []):
        admitidas = bases_admitidas(info, catalogo)  # E19-2: la del estándar y las de sus alternativos
        quien = f"el factor del catálogo es por «{'» o «'.join(admitidas)}»" if std and std["bases"] else \
            f"unidad_base «{base.get('unidad_base')}»"
        mal(pid, "base_no_casa", f"la cita «{base.get('cita')}» no habla de lo que cuenta la base: {quien} (REV16-4)")
        return None, None, None
    divisor, cb = divisor_de(info["plantilla"]), _dec(base.get("cantidad_base"))
    cantidad = _cantidad(cb * valor / Decimal(divisor))
    if cantidad is None:
        mal(pid, "cantidad_fuera_de_rango", f"la cuenta de «{cl}» pasa de {CANTIDAD_MAXIMA:,.0f} unidades al mes: revisa "
            "la base y el factor")
        return None, None, None
    supuesto = (f"{_num(base.get('cantidad_base'))} {base.get('unidad_base')} × {_num(factor['valor'])} "
                f"{factor['unidad']} ÷ {_num(divisor)}")[:300]
    return {**{k: base.get(k) for k in ("cita", "cantidad_base", "unidad_base")}, "factor": factor}, cantidad, supuesto


def completar(resp: dict, catalogo: dict, inst: dict, requisitos: object = None,
              brief_texto: object = None) -> tuple[dict, list[dict]]:
    """(respuesta completada, errores [{"id", "regla", "detalle"}]). `resp` es una respuesta v4 que ya valida con su
    esquema. El núcleo pone, desde el catálogo y la instantánea: la referencia de cada componente del catálogo y la de la
    arquitectura elegida; y en cada precio, filtro, precio, moneda, unidad, región, vigencia, concepto, cantidad_mensual
    (tiempo: 730 h × instancias; volumen: cantidad_base × factor ÷ divisor) y supuesto_cantidad. Lo que normaliza o
    sustituye queda en valoracion_nucleo.ajustes (con lo recibido: proyectar_modelo lo deshace exacto)."""
    c = json.loads(json.dumps(resp, ensure_ascii=False))
    errores, ajustes = [], []
    citas_dim = citas_dimensionamiento(requisitos, brief_texto)

    def mal(i: object, regla: str, detalle: str) -> None:
        errores.append({"id": i, "regla": regla, "detalle": detalle})

    def ajuste(campo: str, recibido: object, puesto: object, motivo: str) -> None:
        if recibido != puesto:
            ajustes.append({"campo": campo, "recibido": recibido, "puesto": puesto, "motivo": motivo})

    refs = c["referencias"]  # lista del esquema; `or []` la desataría si viene vacía
    for r in refs:
        r["origen"] = "experto"
    numeros = [int(r["id"][4:]) for r in refs if re.fullmatch(r"REF-\d{2}", str(r.get("id")))]
    siguiente = [max(numeros, default=0) + 1]
    fecha_ref = _fecha_ref(catalogo, inst)

    def poner_ref(url: str, titulo: str, origen: str) -> str | None:
        n = normalizar_url(url)
        hecho = next((r["id"] for r in refs if normalizar_url(r.get("url")) == n), None)
        if hecho or not n:
            return hecho
        if siguiente[0] > 99:
            return None
        rid = f"REF-{siguiente[0]:02d}"
        siguiente[0] += 1
        refs.append({"id": rid, "url": url, "titulo": titulo[:200], "fecha_consulta": fecha_ref, "origen": origen})
        return rid

    arqs = [a for a in (catalogo or {}).get("arquitecturas_referencia") or [] if isinstance(a, dict)]
    arq = next((a for a in arqs if a.get("id") == c.get("arquitectura_id")), None)
    # multinube: fuera de Azure, la procedencia del euro viaja con la respuesta (la usan el anexo y la frase al cliente)
    procedencia = {} if pilar_instantanea(inst) == est_mod.PILAR_POR_DEFECTO else {
        k: inst[k] for k in ("pilar", "fuente_moneda", "tipo_bce", "fecha_tipo_bce") if k in inst}
    valoracion = {"instantanea": {"fecha_consulta": inst.get("fecha_consulta"), "fecha": fecha_instantanea(inst),
                                  "sha256": inst.get("sha256"), "moneda": inst.get("moneda"), "fuente": inst.get("fuente"),
                                  **procedencia},
                  "arquitectura": None, "ajustes": ajustes, "modelos": []}
    if arq is None:
        mal(None, "arquitectura_desconocida", f"arquitectura_id «{c.get('arquitectura_id')}» no está en la lista del "
            f"catálogo (admite: {', '.join(str(a.get('id')) for a in arqs) or 'ninguna: catálogo sin arquitecturas'})")
    elif not es_referencia_arquitectura(arq.get("url")) or not _texto_no_vacio(arq.get("titulo")):
        mal(None, "arquitectura_no_oficial", f"la arquitectura «{arq.get('id')}» del catálogo no trae título y URL de "
            "arquitectura de Learn (falla cerrado)")
    else:
        rid = poner_ref(arq["url"], arq["titulo"], "arquitectura")
        valoracion["arquitectura"] = {"id": arq["id"], "url": arq["url"], "titulo": arq["titulo"][:200], "referencia_id": rid}
    c["valoracion_nucleo"] = valoracion
    comps = {x.get("id"): x for x in c.get("componentes") or []}
    for x in comps.values():
        entrada = _entrada_de(x, catalogo)
        if x.get("motivo_cita") is not None:
            nuevo = quitar_comillas(x["motivo_cita"])
            ajuste(f"componentes.{x['id']}.motivo_cita", x["motivo_cita"], nuevo, "comillas que envolvían la cita")
            x["motivo_cita"] = nuevo
        jn = x.get("justificacion_nivel")
        if isinstance(jn, dict):  # I1.9: {nivel, razon, cita}
            nuevo = quitar_comillas(jn.get("cita"))
            ajuste(f"componentes.{x['id']}.justificacion_nivel.cita", jn.get("cita"), nuevo,
                   "comillas que envolvían la cita")
            jn["cita"] = nuevo
        if entrada is None:
            if x.get("referencia_id") is None and not es_existente(x):  # I1.9: un sistema del cliente no lleva página
                mal(x.get("id"), "referencia_sin_id", "un componente sin catalogo_id lleva la referencia_id de una "
                    "referencia de Learn que lo respalde")
            continue
        propia = entrada.get("referencia_url")
        # PR17-1 (arreglos I1.7): el título es el PUBLICADO en Learn (`referencia_titulo` de la fila, leído al construir el
        # catálogo), no uno de cortesía: el verificador objetaba «<servicio> en Microsoft Learn» en la ronda 1 (9 y 7
        # DISCREPA) y gastaba una de las 3 rondas. Sin título publicado en la fila, falla cerrado.
        titulo = _texto_no_vacio(entrada.get("referencia_titulo"))
        rid = poner_ref(propia, titulo, "catalogo") if propia and titulo else None
        if rid is None:
            mal(x.get("id"), "catalogo_sin_referencia", f"el catálogo montado no trae una referencia de Learn válida con "
                f"su título publicado de {entrada.get('nombre_oficial')} (o ya hay 99 referencias): no se puede poner "
                "(falla cerrado)")
            continue
        ajuste(f"componentes.{x['id']}.referencia_id", x.get("referencia_id"), rid, "referencia de su fila del catálogo")
        x["referencia_id"] = rid
    _completar_precios(c, comps, catalogo, inst, citas_dim, mal, ajuste, valoracion)
    return c, errores


def _completar_precios(c: dict, comps: dict, catalogo: dict, inst: dict, citas_dim: list[str], mal, ajuste,
                       valoracion: dict) -> None:
    """Pone en cada precio de `c` lo que sale de su plantilla y de la instantánea (ver `completar`)."""
    pendientes: list[tuple] = []
    for p in c.get("precios") or []:
        pid, comp = p.get("id"), comps.get(p.get("componente_id"))
        if comp is None:
            continue  # componente inexistente: ya es un error de la validación
        info, motivo = resolver_plantilla(p.get("plantilla_id"), comp, catalogo)
        if info is None:
            mal(pid, "plantilla_desconocida", motivo)
            continue
        pl, fila, region = info["plantilla"], info["fila"], comp.get("region")
        # Un id con el prefijo de su fila se deja suelto si el suelto resuelve a la misma plantilla (equivalencia
        # demostrable; se anota): el dato por efecto del brief agrupa por plantilla_id y no debe ver dos formas.
        suelto = str(p.get("plantilla_id")).rpartition("/")[2]
        mismo = resolver_plantilla(suelto, comp, catalogo)[0]
        if suelto != p.get("plantilla_id") and mismo is not None and mismo["clave"] == info["clave"]:
            ajuste(f"precios.{pid}.plantilla_id", p.get("plantilla_id"), suelto, "id de plantilla sin el prefijo de su fila")
            p["plantilla_id"] = suelto
        art = articulo_instantanea(inst, fila, pl)
        esperada = fila.get("region_precio") or fila.get("region_ue")
        if art is None:
            mal(pid, "sin_precio_en_instantanea", f"la instantánea de precios no trae «{info['clave']}» con el filtro del "
                "catálogo: redesplegar (falla cerrado)")
            continue
        if art.get("armRegionName") != esperada:
            mal(pid, "instantanea_otra_region", f"el artículo de «{info['clave']}» es de «{art.get('armRegionName')}» y el "
                f"catálogo lo mide en «{esperada}» (falla cerrado)")
            continue
        if not fila.get("region_precio") and region != fila.get("region_ue"):
            mal(pid, "region_sin_instantanea", f"la instantánea tiene el precio de «{info['clave']}» en «{esperada}», la "
                f"región UE del catálogo, y el componente {comp.get('id')} va en «{region}»: pon el componente en "
                f"«{esperada}» (o declara por qué no se puede valorar)")
            continue
        concepto, impulsor, divisor = concepto_de_plantilla(pl), pl.get("impulsor"), divisor_de(pl)
        if concepto is None or impulsor not in IMPULSORES or divisor is None:
            mal(pid, "plantilla_sin_impulsor", f"la plantilla «{info['clave']}» del catálogo montado no declara concepto, "
                "impulsor y divisor: no se puede valorar con ella (falla cerrado)")
            continue
        base, cantidad, supuesto = p.get("base_volumen"), None, None
        if impulsor == "tiempo":
            if base is not None or p.get("factor_override") is not None:
                mal(pid, "base_en_tiempo", f"la plantilla «{info['clave']}» se factura por tiempo: base_volumen y "
                    "factor_override van null y la cantidad sale de instancias (730 h al mes cada una)")
                continue
            mult = UNIDADES_TIEMPO.get(art.get("unidad"))
            if mult is None:
                mal(pid, "unidad_tiempo_desconocida", f"la unidad «{art.get('unidad')}» de «{info['clave']}» no es una "
                    f"unidad de tiempo conocida ({', '.join(UNIDADES_TIEMPO)}): falla cerrado")
                continue
            n = _dec(p.get("instancias")) if p.get("instancias") is not None else Decimal(1)
            # PR17-5 (arreglos I1.7): unidades del medidor por instancia (EP1: 3,5 GB de memoria, Learn); sin ellas, 1.
            pi = pl.get("por_instancia")
            upi = _dec(pi.get("valor")) if isinstance(pi, dict) else Decimal(1)
            if upi is None or upi <= 0 or upi > 1000 or (isinstance(pi, dict) and not _texto_no_vacio(pi.get("unidad"))):
                mal(pid, "por_instancia_no_valido", f"la plantilla «{info['clave']}» declara unidades por instancia no "
                    "válidas (valor > 0 y hasta 1000, con su unidad): no se puede valorar con ella (falla cerrado)")
                continue
            cantidad = _cantidad(mult * n * upi)  # instancias ≤ 1000 y upi ≤ 1000: nunca None
            if isinstance(pi, dict):
                texto = "h" if mult == HORAS_MES else UNIDADES_TIEMPO_TEXTO[art.get("unidad")]
                supuesto = (f"{_fmt_dec(n)} instancia(s) × {_fmt_dec(upi)} ({_texto_no_vacio(pi.get('unidad'))}) × "
                            f"{_fmt_dec(mult.quantize(Decimal('0.0001')))} {texto} al mes")[:300]
            else:
                supuesto = (f"{_fmt_dec(n)} instancia(s) × {_fmt_dec(mult.quantize(Decimal('0.0001')))} "
                            f"{UNIDADES_TIEMPO_TEXTO[art.get('unidad')]} al mes")
        elif p.get("instancias") is not None:
            mal(pid, "instancias_en_volumen", f"la plantilla «{info['clave']}» se factura por volumen: instancias va null "
                "y la cantidad sale de base_volumen (cita de la volumetría × factor del catálogo)")
            continue
        elif base is None:
            if p.get("factor_override") is not None:
                mal(pid, "override_sin_base", "factor_override solo vale con base_volumen")
                continue
            supuesto = "Precio unitario de referencia: no suma en el total; el componente se valora con el volumen real"
        else:
            cita = quitar_comillas(base.get("cita"))
            ajuste(f"precios.{pid}.base_volumen.cita", base.get("cita"), cita, "comillas que envolvían la cita")
            base = {**base, "cita": cita}
            base, cantidad, supuesto = _volumen(p, info, base, citas_dim, catalogo, mal, ajuste)
            if base is None:
                continue
            if cantidad <= 0:
                mal(pid, "cantidad_nula", f"la cuenta da {cantidad} (menos de una millonésima): revisa la base")
                continue
        pendientes.append((p, art, cantidad, supuesto, {
            "plantilla": info["clave"], "filtro": pl.get("filtro"), "moneda": inst.get("moneda"), "unidad": art.get("unidad"),
            "region": region, "effectiveStartDate": art.get("effectiveStartDate"), "concepto": concepto,
            "cantidad_mensual": None if cantidad is None else _num_json(cantidad),
            "sha256_articulo": art.get("sha256_articulo"), "base_volumen": base}))
        cv = pl.get("ciclo_vida")
        if isinstance(cv, dict) and not any(m["plantilla"] == info["clave"] for m in valoracion["modelos"]):
            valoracion["modelos"].append({"plantilla": info["clave"], "ga": cv.get("ga"), "retirada": cv.get("retirada"),
                                          "fuente": cv.get("fuente") or cv.get("fuente_url")})
    # REV17-1 (I1.8): los tramos de Retail Prices se aplican a la cantidad AGREGADA de cada plantilla de la respuesta, no
    # línea a línea (partir 30 GB de Log Analytics en 6 líneas de 5 GB contaba 6 veces la franquicia gratuita: 0,00 €).
    # Cada línea lleva el precio medio del total, así la suma de sus importes es el coste por tramos del total.
    totales: dict[str, list[Decimal]] = {}
    for _p, art, cantidad, _s, campos in pendientes:
        if art.get("tramos") and cantidad is not None:
            totales.setdefault(campos["plantilla"], []).append(cantidad)
    for p, art, cantidad, supuesto, campos in pendientes:
        grupo = totales.get(campos["plantilla"]) if art.get("tramos") and cantidad is not None else None
        total = sum(grupo, Decimal(0)) if grupo else cantidad
        precio, tramos = precio_medio(total, art)
        if tramos:
            varias = (f" sobre el total de la plantilla ({_fmt_dec(total)} en {len(grupo)} líneas)"
                      if grupo and len(grupo) > 1 else "")
            supuesto = f"{supuesto}; precio medio por tramos de Retail Prices{varias}"[:300]
        p.update({k: campos[k] for k in ("plantilla", "filtro")})
        p.update({"precio": precio, "precio_tramos": tramos})
        p.update({k: campos[k] for k in ("moneda", "unidad", "region", "effectiveStartDate", "concepto", "cantidad_mensual")})
        p.update({"supuesto_cantidad": supuesto, "sha256_articulo": campos["sha256_articulo"],
                  "base_volumen": campos["base_volumen"]})


def _incluye(fila: object, catalogo_id: object) -> dict | None:
    """La entrada de `incluye` de la fila que declara la inclusión de `catalogo_id`, con fuente; None si no la hay."""
    for x in (fila.get("incluye") if isinstance(fila, dict) else None) or []:
        if isinstance(x, dict) and catalogo_id and (x.get("catalogo_id") or x.get("id")) == catalogo_id \
                and (_texto_no_vacio(x.get("fuente_url")) or _texto_no_vacio(x.get("fuente"))):
            return x
    return None


def fuentes_cliente(requisitos: object, brief_texto: object) -> dict[str, str]:
    """REV17-3 (I1.8): {texto que vale como motivo_cita de «a_cargo_del_cliente»: valor de la entrada de requisitos de la
    que sale}. Valen el valor de cada entrada CITADO o ACLARACION de requisitos.campos.ya_contratado_por_cliente
    (suficiencia ya exige su cita literal de la fuente) y, emparejada por posición con esas entradas y solo si son tantas
    como ellas, cada viñeta de la sección SECCION_CLIENTE del brief (el valor anonimizado que ve el experto). Sin
    requisitos no vale nada (falla cerrado): lo que se comprueba es la entrada, no la viñeta (Revisión I1.8)."""
    entradas = [_plano_req(e.get("valor")) for e in _entradas_req(requisitos, CAMPO_CLIENTE)
                if e.get("origen") in ("CITADO", "ACLARACION")]
    vinetas, dentro = [], False
    for ln in _lineas_requisitos(brief_texto):
        if ln.startswith("#"):
            dentro = ln.strip() == SECCION_CLIENTE
        elif dentro and ln.startswith("- "):
            vinetas.append(_plano_req(ln[2:]))
    salida = {v: v for v in entradas if v}
    if len(vinetas) == len(entradas):
        for vineta, valor in zip(vinetas, entradas):
            if vineta and valor:
                salida.setdefault(vineta, valor)
    return salida


def citas_cliente(requisitos: object, brief_texto: object) -> list[str]:
    """Los textos que valen como motivo_cita de «a_cargo_del_cliente» (fuentes_cliente), en orden."""
    return list(fuentes_cliente(requisitos, brief_texto))


def servicios_nombrados(texto: object, catalogo: dict) -> list[frozenset]:
    """Servicios del catálogo que el texto nombra: en cada posición, el alias (alias_servicio) más largo que forma una
    secuencia de palabras seguidas, con las filas que lo usan; se sigue tras él. «Servicio de agente de Microsoft
    Foundry» nombra el servicio de agentes, no también Microsoft Foundry; «Foundry Tools» es de varias filas."""
    duenos: dict[str, set] = {}
    for e in _entradas(catalogo):
        for a in alias_servicio(e):
            duenos.setdefault(a, set()).add(e.get("id"))
    toks, salida, i = _tokens(texto), [], 0
    while i < len(toks):
        mejor, acumulado = None, ""
        for j in range(i, len(toks)):
            acumulado += toks[j]
            if acumulado in duenos:
                mejor = (j + 1, acumulado)
            if not any(a.startswith(acumulado) for a in duenos):
                break
        if mejor:
            salida.append(frozenset(duenos[mejor[1]]))
        i = mejor[0] if mejor else i + 1
    return salida


def nombra_servicio(texto: object, comp: dict, catalogo: dict) -> bool:
    """REV17-3: el texto nombra el servicio del componente: para uno del catálogo, un alias que solo es de su fila
    (servicios_nombrados); fuera del catálogo, su nombre `servicio` (5 letras o más) como frase completa."""
    if _entrada_de(comp, catalogo):
        return frozenset({comp.get("catalogo_id")}) in servicios_nombrados(texto, catalogo)
    nombre = _compacto(comp.get("servicio"))
    return len(nombre) >= _ALIAS_MIN and contiene_frase(texto, nombre)


def errores_motivos(resp: dict, catalogo: dict, requisitos: object, brief_texto: object) -> list[dict]:
    """Decisión del PM (REV16-1 c; REV17-3 en I1.8): [{"id", "regla", "detalle"}].
    - «a_cargo_del_cliente» exige motivo_cita, una cita literal de una entrada del campo de requisitos «lo que el cliente
      ya tiene o paga» (citas_cliente) que nombre el servicio del componente (nombra_servicio);
    - «incluido_en_otro_componente» exige incluido_en (otro componente de la respuesta) y que la fila del catálogo de ese
      componente declare en `incluye` la del incluido, con fuente;
    - con cualquier otro motivo, motivo_cita e incluido_en van null (un dato que no se comprueba no se acepta)."""
    comps = {c.get("id"): c for c in resp.get("componentes") or [] if isinstance(c, dict)}
    fuentes = fuentes_cliente(requisitos, brief_texto)
    citas = list(fuentes)
    salida = []

    def mal(i: object, regla: str, detalle: str) -> None:
        salida.append({"id": i, "regla": regla, "detalle": detalle})

    for cid, c in comps.items():
        m, cita, incl = c.get("motivo_no_valoracion"), c.get("motivo_cita"), c.get("incluido_en")
        if m != "a_cargo_del_cliente" and cita is not None:
            mal(cid, "motivo_cita_sobrante", f"motivo_cita solo va con «a_cargo_del_cliente» ({cid} declara «{m}»): null")
        if m != "incluido_en_otro_componente" and incl is not None:
            mal(cid, "incluido_en_sobrante", f"incluido_en solo va con «incluido_en_otro_componente» ({cid} declara «{m}»)")
        if m == "a_cargo_del_cliente":
            if not _texto_no_vacio(cita):
                mal(cid, "cliente_sin_cita", "«a_cargo_del_cliente» exige en motivo_cita la cita literal de lo que el "
                    "cliente ya tiene o paga (sección del brief «Lo que el cliente ya tiene o paga»)")
            elif _plano_req(quitar_comillas(cita)) not in citas:
                mal(cid, "cita_cliente_no_literal", f"motivo_cita «{cita}» no es una entrada literal de «Lo que el cliente "
                    "ya tiene o paga» (" + ("; ".join(f"«{x}»" for x in citas) or "el brief no trae ninguna: el cliente "
                    "no ha dicho que tenga o pague nada; valora el componente o usa otro motivo") + "); un plazo, un "
                    "presupuesto o el marco normativo no ponen un coste a cargo del cliente (REV17-3)")
            elif not nombra_servicio(fuentes[_plano_req(quitar_comillas(cita))], c, catalogo):
                mal(cid, "cita_cliente_sin_servicio", f"motivo_cita «{cita}» no nombra {c.get('servicio')}: la entrada "
                    "citada tiene que decir que el cliente ya tiene o paga ESE servicio (REV17-3)")
        if m == "incluido_en_otro_componente":
            otro = comps.get(incl)
            if incl is None:
                mal(cid, "incluido_sin_componente", "«incluido_en_otro_componente» exige en incluido_en el id del "
                    "componente cuyo precio lo incluye")
            elif otro is None or incl == cid:
                mal(cid, "incluido_inexistente", f"incluido_en «{incl}» no es otro componente de la respuesta")
            elif _incluye(_entrada_de(otro, catalogo), c.get("catalogo_id")) is None:
                mal(cid, "inclusion_no_declarada", f"el catálogo no declara que {otro.get('catalogo_id') or incl} incluya "
                    f"{c.get('catalogo_id') or cid} (con fuente): valóralo con su plantilla o usa otro motivo")
    return salida


# ── I1.9 · recursos que el cliente ya tiene (PR18-1, VC18-2) y arquitectura (VC18-2, VA18-4) ─────────────────────────
MOTIVO_EXISTENTE = "existente_del_cliente"
FRASE_SIN_COMPUTO = "La solución no tiene cómputo propio"
CAPA_DATOS, CAPA_CANALES = "datos_conocimiento", "usuarios_canales"


def es_existente(comp: object) -> bool:
    """I1.9: el componente es un recurso que el cliente ya tiene (existente_del_cliente con su entrada, o el motivo)."""
    return isinstance(comp, dict) and (isinstance(comp.get("existente_del_cliente"), dict)
                                       or comp.get("motivo_no_valoracion") == MOTIVO_EXISTENTE)


def existentes_req(requisitos: object) -> dict[str, dict]:
    """{«EX-nn»: entrada} de requisitos.campos.ya_contratado_por_cliente (CITADO o ACLARACION con id; el primero si se
    repite, que suficiencia ya rechaza)."""
    salida: dict[str, dict] = {}
    for e in _entradas_req(requisitos, CAMPO_CLIENTE):
        if isinstance(e.get("id"), str) and e.get("origen") in ("CITADO", "ACLARACION"):
            salida.setdefault(e["id"], e)
    return salida


def lineas_brief_existentes(requisitos: object, anon=None) -> list[str]:
    """I1.9 (PR18-1): las viñetas de SECCION_CLIENTE del brief, una por entrada EX, con su servicio del catálogo, el
    fragmento que nombra el recurso y la cita ENTERA de la fuente (no un resumen), anonimizadas con `anon`:
    «- EX-06 (az-api-management): «API Management». Cita: «El saldo de vacaciones … publicada con API Management.»».
    El experto declara el componente con existente_del_cliente {entrada: «EX-06»}. [] si no hay entradas."""
    a = anon if callable(anon) else (lambda x: x)
    return [f"- {k} ({e.get('servicio_catalogo') or 'fuera del catálogo'}): «{a(_plano_req(e.get('valor')))}». "
            f"Cita: «{a(_plano_req(e.get('cita')))}»" for k, e in existentes_req(requisitos).items()]


def valorados_de(resp: dict, catalogo: dict) -> dict[str, list]:
    """{componente_id: [ids de plantilla]} de las líneas propias VALORADAS (con cantidad_mensual) de cada componente."""
    comps = {c.get("id"): c for c in resp.get("componentes") or [] if isinstance(c, dict)}
    salida: dict[str, list] = {}
    for p in resp.get("precios") or []:
        if not isinstance(p, dict) or p.get("cantidad_mensual") is None:
            continue
        i = plantilla_de_precio(p, comps.get(p.get("componente_id")), catalogo)
        if i is not None and not i["auxiliar"]:
            salida.setdefault(p.get("componente_id"), []).append(i["plantilla"].get("id"))
    return salida


def errores_existentes(resp: dict, requisitos: object, catalogo: dict) -> list[dict]:
    """I1.9 (PR18-1 y VC18-2; decisión del PM, falla cerrado): [{"id", "regla", "detalle"}] en el orden de la respuesta.
    - existente_del_cliente y el motivo «existente_del_cliente» van juntos («existente_sin_motivo»,
      «motivo_sin_existente»); la entrada es una «EX-nn» de los requisitos («existente_desconocido»), casa con un solo
      componente («existente_repetido») y con su servicio del catálogo, o con null fuera del catálogo
      («existente_otro_servicio»); sin precios («existente_con_precio») ni justificacion_nivel («existente_con_nivel»);
    - un componente VALORADO de un servicio que el cliente ya tiene exige desviacion_justificada que cite esa EX-nn
      (la ve el revisor): «existente_valorado» (Hostelia: API Management Basic v2 nuevo, 173,45 € al mes)."""
    comps = [c for c in resp.get("componentes") or [] if isinstance(c, dict)]
    ex, usados, salida = existentes_req(requisitos), {}, []

    def mal(i: object, regla: str, detalle: str) -> None:
        salida.append({"id": i, "regla": regla, "detalle": detalle})

    con_precio = {p.get("componente_id") for p in resp.get("precios") or [] if isinstance(p, dict)}
    for c in comps:
        cid, dato, m = c.get("id"), c.get("existente_del_cliente"), c.get("motivo_no_valoracion")
        if isinstance(dato, dict) != (m == MOTIVO_EXISTENTE):
            mal(cid, "existente_sin_motivo" if isinstance(dato, dict) else "motivo_sin_existente",
                "existente_del_cliente {entrada: «EX-nn»} y el motivo «existente_del_cliente» van juntos: los dos o "
                "ninguno")
        if not isinstance(dato, dict):
            continue
        entrada = dato.get("entrada")
        e = ex.get(entrada)
        if e is None:
            mal(cid, "existente_desconocido", f"existente_del_cliente.entrada «{entrada}» no es una entrada de «Lo que "
                f"el cliente ya tiene o paga» (hay: {', '.join(ex) or 'ninguna: el cliente no ha dicho que tenga nada'})")
        else:
            if entrada in usados:
                mal(cid, "existente_repetido", f"{entrada} ya es {usados[entrada]}: cada recurso del cliente casa con un "
                    "solo componente (VC18-2)")
            else:
                usados[entrada] = cid
            if e.get("servicio_catalogo") != c.get("catalogo_id"):
                mal(cid, "existente_otro_servicio", f"{entrada} es «{e.get('valor')}» "
                    f"({e.get('servicio_catalogo') or 'fuera del catálogo'}) y {cid} es "
                    f"{c.get('catalogo_id') or 'un componente fuera del catálogo'}: el componente existente es ESE "
                    "recurso, con su mismo servicio; otro recurso del cliente no cubre este componente (VC18-2)")
        if cid in con_precio:
            mal(cid, "existente_con_precio", f"{cid} es un recurso que el cliente ya tiene: no se valora; quita sus "
                "líneas de consumo")
        if c.get("justificacion_nivel") is not None:
            mal(cid, "existente_con_nivel", f"{cid} es un recurso que el cliente ya tiene: su nivel es del cliente; "
                "justificacion_nivel va null")
    por_servicio: dict[str, list] = {}
    for k, e in ex.items():
        if isinstance(e.get("servicio_catalogo"), str):
            por_servicio.setdefault(e["servicio_catalogo"], []).append(k)
    valorados = valorados_de(resp, catalogo)
    for c in comps:
        exs = por_servicio.get(c.get("catalogo_id")) or []
        if es_existente(c) or not exs or not valorados.get(c.get("id")):
            continue
        dj = c.get("desviacion_justificada")
        if not (isinstance(dj, str) and any(re.search(r"(?<![\w-])" + re.escape(x) + r"(?![\w-])", dj) for x in exs)):
            mal(c.get("id"), "existente_valorado", f"{c.get('servicio')} se valora y el cliente ya lo tiene ("
                + "; ".join(f"{x}: «{ex[x].get('valor')}»" for x in exs) + "): declara el componente con "
                f"existente_del_cliente {{entrada: «{exs[0]}»}}, sin precios, o, si hace falta uno nuevo, explícalo en "
                f"desviacion_justificada citando {exs[0]} (lo ve el revisor)")
    return salida


def es_computo_valorado(comp: dict, valoradas: list, catalogo: dict) -> bool:
    """El componente valora cómputo: su fila es de la clase cómputo y, si tiene niveles, usa una plantilla de nivel (o
    es el cómputo por defecto); la memoria de corto plazo de Foundry Agent Service sola no es cómputo (N4)."""
    entrada = _entrada_de(comp, catalogo)
    if not valoradas or not isinstance(entrada, dict) or entrada.get("id") not in filas_computo(catalogo):
        return False
    niveles = niveles_de(entrada)
    return (es_computo_por_defecto(entrada, valoradas, catalogo) or not niveles
            or any(n["plantillas"] is None or set(valoradas) & n["plantillas"] for n in niveles))


def _capa(comp: dict, catalogo: dict) -> object:
    return (_entrada_de(comp, catalogo) or {}).get("capa") or comp.get("capa")


def _dice_sin_computo(texto: object) -> bool:
    """El texto afirma FRASE_SIN_COMPUTO (sin otra negación antes en su cláusula: «No es cierto que la solución no
    tiene…» no vale). La frase ya trae su «no»: se busca lo que le sigue y se mira la cláusula antes de ese «no»."""
    for clausula in _CLAUSULA.split(texto if isinstance(texto, str) else ""):
        toks = _tokens(clausula)
        frase = _tokens(FRASE_SIN_COMPUTO)
        for i in range(len(toks) - len(frase) + 1):
            if toks[i:i + len(frase)] == frase and not set(toks[:i]) & NEGACIONES:
                return True
    return False


def errores_arquitectura(resp: dict, catalogo: dict) -> list[dict]:
    """I1.9 (decisión del PM): [{"id", "regla", "detalle"}] en el orden de la respuesta.
    - «canal_sin_computo» (VC18-2): un canal valorado (Bot Service: capa usuarios_canales) exige un cómputo valorado
      (es_computo_valorado, nunca un recurso del cliente) o un supuesto que cite el canal y diga FRASE_SIN_COMPUTO;
    - «datos_sin_salida» (VA18-4): un componente de datos tiene un flujo que sale de él hacia otro componente, o uno que
      llega desde un componente de fuera de la capa de datos (quien lo consulta); si no, un supuesto que lo cite y
      nombre su servicio explica por qué se conserva (lo ven el cliente y el revisor)."""
    comps = [c for c in resp.get("componentes") or [] if isinstance(c, dict)]
    por_id = {c.get("id"): c for c in comps}
    supuestos = [s for s in resp.get("supuestos") or [] if isinstance(s, dict)]
    flujos = [f for f in resp.get("flujos") or [] if isinstance(f, dict)]
    valorados, salida = valorados_de(resp, catalogo), []
    hay_computo = any(not es_existente(c) and es_computo_valorado(c, valorados.get(c.get("id")) or [], catalogo)
                      for c in comps)
    for c in comps:
        cid = c.get("id")
        if (not hay_computo and _capa(c, catalogo) == CAPA_CANALES and valorados.get(cid) and not es_existente(c)
                and not any(_dice_sin_computo(s.get("texto")) and cid in (s.get("hechos") or []) for s in supuestos)):
            salida.append({"id": cid, "regla": "canal_sin_computo", "detalle": (
                f"{c.get('servicio')} se valora y la propuesta no valora ningún cómputo propio (un recurso del cliente no "
                "cuenta): valora el cómputo que atiende al canal o, si de verdad no lo hay, un supuesto que cite "
                f"{cid} y diga «{FRASE_SIN_COMPUTO}» (VC18-2)")})
        if _capa(c, catalogo) != CAPA_DATOS:
            continue
        sale = any((f.get("origen") == cid and f.get("destino") in por_id and f.get("destino") != cid)
                   or (f.get("destino") == cid and f.get("origen") in por_id and f.get("origen") != cid
                       and _capa(por_id[f.get("origen")], catalogo) != CAPA_DATOS) for f in flujos)
        if not sale and not any(cid in (s.get("hechos") or []) and nombra_servicio(s.get("texto"), c, catalogo)
                                for s in supuestos):
            salida.append({"id": cid, "regla": "datos_sin_salida", "detalle": (
                f"{c.get('servicio')} es un componente de datos y ningún flujo lo une con quien usa sus datos: dibuja el "
                "flujo hacia el componente que los lee (o desde el que los consulta) o, si se conserva sin uso, un "
                f"supuesto que cite {cid} y nombre el servicio diga por qué (VA18-4)")})
    return salida


def duracion_gantt(resp: dict) -> int | None:
    """Semanas del Gantt que compondrá la estimación con estas tareas (misma regla que estimacion.componer_entrada:
    fases en orden, cada una máx(1, ⌈horas / (40 × perfiles distintos)⌉)); None si no se puede calcular."""
    from nucleo import estimacion  # diferido: módulo de B
    tareas = [t for t in resp.get("tareas_propuestas") or [] if isinstance(t, dict)]
    fases = list(dict.fromkeys(t.get("fase") for t in tareas))
    try:
        return sum(estimacion.semanas_fase(sum((estimacion.horas_tarea(t.get("horas_base"), t.get("reuniones_h"))
                                                for t in tareas if t.get("fase") == f), Decimal(0)),
                                           len({t.get("perfil") for t in tareas if t.get("fase") == f}))
                   for f in fases) or None
    except (ValueError, TypeError, ArithmeticError):
        return None


def limite_retirada(fecha_oferta: object, semanas: object) -> datetime.date | None:
    """fecha de la oferta + semanas del Gantt + MESES_EXPLOTACION meses (el 29 de febrero pasa al 28)."""
    try:
        d = datetime.date.fromisoformat(str(fecha_oferta)[:10]) + datetime.timedelta(weeks=int(semanas or 0))
    except (ValueError, TypeError):
        return None
    anios, mes = divmod(d.month - 1 + MESES_EXPLOTACION, 12)
    y, m = d.year + anios, mes + 1
    try:
        return d.replace(year=y, month=m)
    except ValueError:
        return d.replace(year=y, month=m, day=28)


def errores_ciclo_vida(completada: dict, catalogo: dict, fecha_oferta: object, semanas: object) -> list[dict]:
    """Regla del PM (LES-G-036 revisada): ningún modelo cuya retirada publicada caiga antes de fecha de la oferta + Gantt +
    12 meses, ni uno que aún no sea GA en la fecha de la oferta. Sin fecha publicada se admite (la nota lo dice). Si una
    fila declara ciclo_vida en alguna plantilla, todas las que se usen de esa fila lo llevan (falla cerrado)."""
    comps = {c.get("id"): c for c in completada.get("componentes") or [] if isinstance(c, dict)}
    limite, salida = limite_retirada(fecha_oferta, semanas), []
    for p in completada.get("precios") or []:
        info = resolver_plantilla(p.get("plantilla_id"), comps.get(p.get("componente_id")), catalogo)[0]
        if info is None:
            continue
        cv = info["plantilla"].get("ciclo_vida")
        con_ciclo = any(isinstance(x, dict) and "ciclo_vida" in x for x in info["fila"].get("plantillas_precio") or [])
        if not isinstance(cv, dict):
            if con_ciclo:
                salida.append({"id": p.get("id"), "regla": "ciclo_vida_desconocido", "detalle": (
                    f"la plantilla «{info['clave']}» no trae ciclo de vida en el catálogo y su fila sí: no se puede "
                    "comprobar su retirada (falla cerrado)")})
            continue
        ga, ret = cv.get("ga"), cv.get("retirada")
        if ga and str(ga) > str(fecha_oferta)[:10]:
            salida.append({"id": p.get("id"), "regla": "modelo_no_disponible", "detalle": (
                f"«{info['clave']}» no es GA hasta el {ga} y la oferta es del {str(fecha_oferta)[:10]}: usa el modelo por "
                "defecto del catálogo")})
        if ret and (limite is None or str(ret) < limite.isoformat()):
            salida.append({"id": p.get("id"), "regla": "modelo_retirado", "detalle": (
                f"«{info['clave']}» se retira el {ret} (fuente {cv.get('fuente') or cv.get('fuente_url')}), antes del "
                f"{limite} (oferta del {str(fecha_oferta)[:10]} + {semanas or 0} semanas de proyecto + "
                f"{MESES_EXPLOTACION} meses de explotación): usa el modelo por defecto del catálogo")})
    salida += errores_modelo_sku(completada, catalogo, fecha_oferta, semanas)
    return salida


def modelos_catalogo(catalogo: dict) -> dict:
    """{modelo: ciclo} de las plantillas del catálogo con `modelo` (en cualquier fila). Si varias plantillas del mismo
    modelo dan ciclos distintos, el más estricto: la GA más tardía y la retirada más temprana. Ciclo None si alguna
    plantilla del modelo no trae `ciclo_vida` (falla cerrado al comprobarlo)."""
    salida: dict = {}
    for e in _entradas(catalogo):
        for p in e.get("plantillas_precio") or []:
            m = p.get("modelo") if isinstance(p, dict) else None
            if not isinstance(m, str) or not _tokens(m):
                continue
            cv = p.get("ciclo_vida") if isinstance(p.get("ciclo_vida"), dict) else None
            previo = salida.get(m, {}) if m in salida else {}
            if cv is None or (m in salida and previo is None):
                salida[m] = None
                continue
            ga = max([x for x in ((previo or {}).get("ga"), cv.get("ga")) if x], default=None, key=str)
            ret = min([x for x in ((previo or {}).get("retirada"), cv.get("retirada")) if x], default=None, key=str)
            salida[m] = {"ga": ga, "retirada": ret, "fuente": (previo or {}).get("fuente") or cv.get("fuente")
                         or cv.get("fuente_url")}
    return salida


def modelos_en(texto: object, nombres: object) -> list[str]:
    """Modelos de `nombres` que el texto nombra como secuencia de palabras (la coincidencia más larga en cada sitio:
    «gpt-5-mini» no cuenta también como «gpt-5»), en orden de aparición y sin repetir."""
    formas = sorted(((n, _tokens(n)) for n in nombres if _tokens(n)), key=lambda x: -len(x[1]))
    toks, hallados, i = _tokens(texto), [], 0
    while i < len(toks):
        hit = next(((n, t) for n, t in formas if toks[i:i + len(t)] == t), None)
        if hit:
            hallados.append(hit[0])
        i += len(hit[1]) if hit else 1
    return list(dict.fromkeys(hallados))


def errores_modelo_sku(completada: dict, catalogo: dict, fecha_oferta: object, semanas: object) -> list[dict]:
    """REV17-2 (I1.8): el modelo que el cliente lee en el sku del componente también cumple el ciclo de vida. Por
    componente, en el orden de la respuesta:
    - en una fila con plantillas de modelo: si sus precios usan modelos, el sku no puede nombrar otro
      («modelo_sku_distinto»); sin precios de modelo, el sku tiene que nombrar uno del catálogo («modelo_sin_plantilla»);
    - en cualquier componente, cada modelo del catálogo que nombra el sku y no se comprobó por sus precios cumple la regla
      de errores_ciclo_vida («modelo_no_disponible», «modelo_retirado»; sin ciclo publicado, «ciclo_vida_desconocido»)."""
    comps = [c for c in completada.get("componentes") or [] if isinstance(c, dict)]
    catalogo_m, limite, salida = modelos_catalogo(catalogo), limite_retirada(fecha_oferta, semanas), []
    for c in comps:
        cid, fila = c.get("id"), _entrada_de(c, catalogo)
        if es_existente(c):
            continue  # I1.9 (PR18-1): el sku de un recurso del cliente es suyo, no de la propuesta
        nombrados = modelos_en(c.get("sku"), catalogo_m)
        de_precios = []
        for p in completada.get("precios") or []:
            if not isinstance(p, dict):
                continue  # Revisión I1.8: un precio que no es objeto (dato forjado) no lanza una excepción aquí
            info = resolver_plantilla(p.get("plantilla_id"), c, catalogo)[0] if p.get("componente_id") == cid else None
            m = info["plantilla"].get("modelo") if info and not info["auxiliar"] else None
            if isinstance(m, str) and m not in de_precios:
                de_precios.append(m)
        con_modelo = any(isinstance(x, dict) and isinstance(x.get("modelo"), str)
                         for x in (fila or {}).get("plantillas_precio") or [])
        if con_modelo and de_precios and [m for m in nombrados if m not in de_precios]:
            salida.append({"id": cid, "regla": "modelo_sku_distinto", "detalle": (
                f"el sku «{c.get('sku')}» nombra {', '.join(m for m in nombrados if m not in de_precios)} y los precios "
                f"valoran {', '.join(de_precios)}: el sku dice el modelo de sus plantillas (REV17-2)")})
        elif con_modelo and not de_precios and not nombrados:
            salida.append({"id": cid, "regla": "modelo_sin_plantilla", "detalle": (
                f"{c.get('servicio')} no tiene precios de modelo y su sku «{c.get('sku')}» no nombra ningún modelo del "
                f"catálogo: nombra el modelo en el sku ({', '.join(catalogo_m)}) para comprobar su ciclo de vida (REV17-2)")})
        for m in nombrados:
            if m in de_precios:
                continue
            cv = catalogo_m.get(m)
            if cv is None:
                salida.append({"id": cid, "regla": "ciclo_vida_desconocido", "detalle": (
                    f"el sku nombra «{m}» y el catálogo no trae su ciclo de vida: no se puede comprobar (falla cerrado)")})
                continue
            if cv.get("ga") and str(cv["ga"]) > str(fecha_oferta)[:10]:
                salida.append({"id": cid, "regla": "modelo_no_disponible", "detalle": (
                    f"el sku nombra «{m}», que no es GA hasta el {cv['ga']}: usa el modelo por defecto del catálogo")})
            if cv.get("retirada") and (limite is None or str(cv["retirada"]) < limite.isoformat()):
                salida.append({"id": cid, "regla": "modelo_retirado", "detalle": (
                    f"el sku nombra «{m}», que se retira el {cv['retirada']} (fuente {cv.get('fuente')}), antes del "
                    f"{limite}: usa el modelo por defecto del catálogo (REV17-2)")})
    return salida


def coste_por_tramos(cantidad: Decimal, tramos: list) -> Decimal:
    """Coste de `cantidad` (en la unidad del medidor) con precios por tramo [{desde, precio_unitario}] (desde creciente,
    el primero 0): cada tramo factura lo que cae entre su «desde» y el del siguiente."""
    total = Decimal(0)
    for i, tr in enumerate(tramos):
        ini = Decimal(str(tr["desde"]))
        fin = Decimal(str(tramos[i + 1]["desde"])) if i + 1 < len(tramos) else None
        dentro = (min(cantidad, fin) if fin is not None else cantidad) - ini
        if dentro > 0:
            total += dentro * Decimal(str(tr["precio_unitario"]))
    return total


def precio_medio(cantidad: Decimal | None, art: dict) -> tuple[object, list | None]:
    """(precio, tramos) de la línea: sin tramos, el precio_unitario del artículo; con tramos y cantidad, el precio medio de
    esa cantidad (coste_por_tramos ÷ cantidad en Decimal, guardado como número JSON sin redondear: con 8 decimales, una
    cantidad grande amplificaba el error hasta publicar 0,00 €, Revisión I1.7); un precio de referencia (sin cantidad)
    lleva el del primer tramo."""
    tramos = art.get("tramos")
    if not tramos:
        return art.get("precio_unitario"), None
    copia = [{"desde": x["desde"], "precio_unitario": x["precio_unitario"]} for x in tramos]
    if cantidad is None:
        return art.get("precio_unitario"), copia
    medio = coste_por_tramos(cantidad, tramos) / cantidad
    return (int(medio) if medio == medio.to_integral_value() else float(medio)), copia


def proyectar_modelo(completada: dict) -> dict:
    """Lo que escribió el modelo: la completada sin lo que puso el núcleo y con lo recibido de cada ajuste."""
    c = json.loads(json.dumps(completada, ensure_ascii=False))
    v = c.pop("valoracion_nucleo", None) or {}
    recibido = {a.get("campo"): a.get("recibido") for a in v.get("ajustes") or [] if isinstance(a, dict)}
    c["referencias"] = [{k: x for k, x in r.items() if k != "origen"} for r in c.get("referencias") or []
                        if r.get("origen") == "experto"]
    for x in c.get("componentes") or []:
        for campo in ("referencia_id", "motivo_cita"):
            if f"componentes.{x['id']}.{campo}" in recibido:
                x[campo] = recibido[f"componentes.{x['id']}.{campo}"]
        clave = f"componentes.{x['id']}.justificacion_nivel.cita"
        if clave in recibido and isinstance(x.get("justificacion_nivel"), dict):
            x["justificacion_nivel"]["cita"] = recibido[clave]
    modelo = ("id", "componente_id", "plantilla_id", "instancias", "base_volumen", "factor_override")
    for i, p in enumerate(c.get("precios") or []):
        q = {k: p.get(k) for k in modelo}
        q["plantilla_id"] = recibido.get(f"precios.{p['id']}.plantilla_id", q["plantilla_id"])
        if isinstance(q["base_volumen"], dict):
            q["base_volumen"] = {k: q["base_volumen"].get(k) for k in ("cita", "cantidad_base", "unidad_base")}
            q["base_volumen"]["cita"] = recibido.get(f"precios.{p['id']}.base_volumen.cita", q["base_volumen"]["cita"])
        if isinstance(q["factor_override"], dict):
            q["factor_override"]["cita"] = recibido.get(f"precios.{p['id']}.factor_override.cita",
                                                        q["factor_override"]["cita"])
        c["precios"][i] = q
    return c


def _formato(x: dict) -> str:
    i = str(x.get("id") or "")
    bloque = "componentes" if i.startswith("C-") else "precios" if i.startswith("P-") else "respuesta"
    return f"{bloque}.{i}: {x['detalle']}" if i else f"{bloque}: {x['detalle']}"


def analizar_respuesta(resp: dict, brief: dict, catalogo: dict, perfiles: list[str], requisitos: dict | None = None,
                       instantanea: dict | None = None, hoy: str | None = None) -> tuple[list[str], dict | None]:
    """(errores, completada) de una respuesta v4 (§6.4 y CAMBIOS-I17-P): todos los errores, no solo el primero, y la
    respuesta completada por el núcleo si no hay ninguno (None si los hay). `instantanea` es obligatoria (IntegridadRota si
    falta: sin ella no hay precios); `hoy` (AAAA-MM-DD) activa la regla de ciclo de vida con el Gantt de las tareas."""
    pilar = (brief or {}).get("pilar", est_mod.PILAR_POR_DEFECTO)   # multinube: el brief de Azure no lleva la clave
    errores = list(esquema.validar(resp, esquema.cargar_pilar("respuesta_experto", pilar)))
    if errores:
        return errores, None
    if not isinstance(instantanea, dict):
        raise IntegridadRota("No hay instantánea de precios: el núcleo no puede poner los precios (redesplegar)", [])
    texto_brief = brief.get("texto")
    if resp["brief_id"] != brief["brief_id"]:
        errores.append(f"brief_id: devuelve {resp['brief_id']} y el vigente es {brief['brief_id']}")
    if not brief_mod.eco_identico(texto_brief, resp["brief_recibido"]):
        errores.append("brief_recibido: no es literal; " + brief_mod.primera_diferencia(texto_brief, resp["brief_recibido"]))
    c, faltas = completar(resp, catalogo, instantanea, requisitos, texto_brief)
    errores += [_formato(x) for x in faltas]
    # PR18-4 (I1.9): un precio rechazado al completarlo no recibe filtro ni cantidad. Las reglas siguientes se comprueban
    # sobre la respuesta SIN los precios rechazados (c_ok) y se callan solo las que dan error POR esa ausencia en su
    # componente (falta un medidor, una cobertura, una cantidad conservada, el cómputo del canal): viajarían al experto
    # como consejo falso en el reintento («no es una cadena», «corrige el catalogo_id»). Se comprueban en el reintento.
    derivado = _derivados(faltas, c, catalogo)
    precios_ok = [p for p in c["precios"] if p.get("id") not in derivado["precios"]]
    c_ok = {**c, "precios": precios_ok}
    refs = {r["id"]: r for r in c["referencias"]}
    errores += _repetidos([r["id"] for r in resp["referencias"]], "referencias")
    errores += [f"referencias.{r['id']}: URL fuera de la lista blanca: {r['url']}" for r in c["referencias"]
                if not es_referencia_permitida(r["url"])]
    cat = {x["id"]: x for x in catalogo.get("componentes", [])}
    comps = {x["id"]: x for x in c["componentes"]}
    errores += _repetidos([x["id"] for x in resp["componentes"]], "componentes")
    for x in c["componentes"]:
        existente = es_existente(x)  # I1.9: un sistema del cliente no es una desviación ni se despliega en una región
        if x["referencia_id"] is not None and x["referencia_id"] not in refs:
            errores.append(f"componentes.{x['id']}: referencia_id {x['referencia_id']} no existe")
        if x["catalogo_id"] is None:
            if not existente and (not x["desviacion_justificada"] or len(x["desviacion_justificada"].strip()) < 30):
                errores.append(f"componentes.{x['id']}: sin catalogo_id exige desviacion_justificada de ≥ 30 caracteres")
        elif x["catalogo_id"] not in cat:
            errores.append(f"componentes.{x['id']}: catalogo_id {x['catalogo_id']} no está en el catálogo montado")
        sin_id = region_exige_catalogo(x)
        if sin_id:
            errores.append(f"componentes.{x['id']}: {sin_id}")
        veto = region_no_admitida(x, catalogo, precios_ok)
        if veto:
            errores.append(f"componentes.{x['id']}: {veto}; usa otra región de la UE (la «Región UE» de la tabla)")
        errores += [f"componentes.{x['id']}: {m}" for m in incoherencias_servicio(x, catalogo, precios_ok)]
    errores += [f"componentes.{x['id']}: {x['detalle']}" for x in errores_referencia_catalogo(c, catalogo)]
    for f in c["flujos"]:
        for extremo in ("origen", "destino"):
            if f[extremo] not in comps:
                errores.append(f"flujos: {extremo} {f[extremo]} no es un componente")
    errores += _repetidos([p["id"] for p in c["precios"]], "precios")
    errores += [f"precios.{p['id']}: componente_id {p['componente_id']} no existe" for p in c["precios"]
                if p["componente_id"] not in comps]
    from nucleo import anexo_consumo  # diferido: módulo de B
    if not derivado["precios"] and not [p for p in c["precios"] if p.get("cantidad_mensual") is not None]:  # PR14-1
        try:
            facturables = anexo_consumo.facturables_azure(c, catalogo)
        except IntegridadRota:
            facturables = []  # un catalogo_id desconocido ya es un error de arriba
        if facturables:
            errores.append(f"precios: {anexo_consumo.motivo_sin_precios(facturables)}. Pon una línea de consumo con la "
                           "plantilla de cada uno")
    try:  # PR15-2: cada facturable de Azure lleva precio o motivo de no valoración de la lista cerrada
        errores += [f"componentes.{x['componente_id']}: {x['detalle']}" for x in anexo_consumo.errores_cobertura(c_ok, catalogo)
                    if not _es_derivado({"id": x["componente_id"], "regla": x["regla"]}, derivado)]
    except IntegridadRota:
        pass  # un catalogo_id desconocido ya es un error de arriba
    errores += [_formato(x) for x in errores_motivos(c, catalogo, requisitos, texto_brief)]
    errores += [_formato(x) for x in errores_existentes(c_ok, requisitos, catalogo) if not _es_derivado(x, derivado)]
    errores += [_formato(x) for x in errores_arquitectura(c_ok, catalogo) if not _es_derivado(x, derivado)]
    errores += [_formato(x) for x in errores_volumen_nivel(c_ok, texto_brief, requisitos, catalogo)
                if not _es_derivado(x, derivado)]
    if hoy is not None:
        errores += [_formato(x) for x in errores_ciclo_vida(c_ok, catalogo, hoy, duracion_gantt(resp))
                    if not _es_derivado(x, derivado)]
    errores += [_formato(x) for x in errores_conservacion(c_ok, brief.get("conservar_precios"))
                if not _es_derivado(x, derivado)]
    errores += _repetidos([t["id"] for t in resp["tareas_propuestas"]], "tareas_propuestas")
    errores += [f"tareas_propuestas.{t['id']}: perfil fuera de la tarifa: {t['perfil']}"
                for t in resp["tareas_propuestas"] if t["perfil"] not in perfiles]
    errores += _repetidos([s["id"] for s in resp["supuestos"]], "supuestos")
    errores += _repetidos([r["id"] for r in resp["riesgos"]], "riesgos")
    existentes = set(refs) | set(comps) | {p["id"] for p in c["precios"]}
    for bloque in ("supuestos", "riesgos"):
        for x in resp[bloque]:
            for h in x["hechos"]:
                ok = h[2:] in CAMPOS_REQUISITOS if h.startswith("R-") else h in existentes
                if not ok:
                    errores.append(f"{bloque}.{x['id']}: hecho {h} no existe")
    for k, tope in _TOPES.items():
        if resp["herramientas_usadas"][k] > tope:
            errores.append(f"herramientas_usadas.{k}: {resp['herramientas_usadas'][k]} supera el tope {tope}")
    errores += marcadores_en(resp, excluir=("$.brief_recibido",))
    errores += metatexto_en(resp)
    if not errores:
        errores += [f"respuesta completada: {e}" for e in esquema.validar(
            c, esquema.cargar_pilar("respuesta_experto_completa", pilar))]
    return errores, (c if not errores else None)


def _derivados(faltas: list, completada: dict, catalogo: dict | None = None) -> dict:
    """PR18-4 (I1.9): {"precios": ids de los precios rechazados al completar, "componentes": sus componentes,
    "computo": algún rechazado era de un componente de la clase cómputo (su ausencia puede explicar canal_sin_computo)}."""
    precios = {x.get("id") for x in faltas if isinstance(x.get("id"), str) and x["id"].startswith("P-")}
    comps = {p.get("componente_id") for p in completada.get("precios") or [] if isinstance(p, dict) and p.get("id") in precios}
    clase = filas_computo(catalogo or {})
    computo = any(isinstance(c, dict) and c.get("id") in comps and c.get("catalogo_id") in clase
                  for c in completada.get("componentes") or [])
    return {"precios": precios, "componentes": comps, "computo": computo}


# PR18-4: reglas que dan error por la AUSENCIA de un precio (en la respuesta sin los rechazados) y no por lo que hay.
POR_AUSENCIA = frozenset({"falta_medidor_obligatorio", "sin_precio_ni_motivo", "depende_sin_precio_unitario",
                          "conservado_ausente", "conservado_cambiado"})


def _es_derivado(x: dict, derivado: dict) -> bool:
    """El error lo provoca la ausencia de un precio rechazado: una regla de POR_AUSENCIA en su componente (o en una clave
    de conservación de ese componente, «catalogo_id · plantilla · C-nn»), o el cómputo del canal si se rechazó un precio
    de un componente de la clase cómputo (Revisión I1.9: con otro rechazado, el error sí viaja). Se comprueba en el
    reintento (PR18-4)."""
    if not derivado["precios"]:
        return False
    if x.get("regla") == "canal_sin_computo":
        return bool(derivado.get("computo"))
    i = x.get("id")
    if x.get("regla") not in POR_AUSENCIA or not isinstance(i, str):
        return False
    return i in derivado["componentes"] or (" · " in i and any(
        re.search(r"(?<![\w-])" + re.escape(str(cid)) + r"(?![\w-])", i.split(" · ", 2)[-1])
        for cid in derivado["componentes"]))


def validar_respuesta(resp: dict, brief: dict, catalogo: dict, perfiles: list[str], requisitos: dict | None = None,
                      instantanea: dict | None = None, hoy: str | None = None) -> list[str]:
    """§6.4 con el contrato v4: los errores de analizar_respuesta. [] si es válida."""
    return analizar_respuesta(resp, brief, catalogo, perfiles, requisitos, instantanea, hoy)[0]


def avisos_respuesta(resp: dict, catalogo: dict) -> list[str]:
    """§6.4.10: capa o nombre distintos de los del catálogo (vale el catálogo; aviso para la nota)."""
    cat = {c["id"]: c for c in catalogo.get("componentes", [])}
    avisos = []
    for c in resp.get("componentes", []):
        oficial = cat.get(c.get("catalogo_id"))
        if oficial and c.get("capa") != oficial["capa"]:
            avisos.append(f"{c['id']}: capa {c.get('capa')} distinta de la del catálogo ({oficial['capa']}); vale la del catálogo")
        if oficial and c.get("servicio") != oficial["nombre_oficial"]:
            avisos.append(f"{c['id']}: servicio «{c.get('servicio')}»; el nombre que vale es «{oficial['nombre_oficial']}»")
    return avisos + avisos_fuera_de_catalogo(resp, catalogo)


def avisos_fuera_de_catalogo(resp: dict, catalogo: dict) -> list[str]:
    """VER-1 y REVER-1: un aviso por componente no identificado (ni por id ni por precio) en una región con
    restricciones (nota del revisor)."""
    return [a for c in resp.get("componentes") or [] if isinstance(c, dict)
            if (a := aviso_fuera_de_catalogo(c, catalogo, resp.get("precios")))]


def _nfc(obj: object) -> object:
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, list):
        return [_nfc(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _nfc(v) for k, v in obj.items()}
    return obj


def _fallar(estado: dict, mensaje: str, errores: list[str]):
    """Suma el intento T2 y lanza ReglaIncumplida, o Bloqueo si era el 3/3."""
    n = est_mod.registrar_intento(estado, "T2", f"{mensaje}: " + " | ".join(errores)[:3000],
                                  "La respuesta del experto no cumple el contrato (§6.4); revisar instrucciones y brief")
    if estado["estado"] == "BLOQUEADA":
        raise Bloqueo(f"{mensaje} (intento {n}/3: BLOQUEADA)", errores)
    raise ReglaIncumplida(f"{mensaje} (intento {n}/3)", errores)


def instantanea_valida(instantanea: object, catalogo: dict, hoy: str, pilar: str = est_mod.PILAR_POR_DEFECTO) -> dict:
    """La instantánea de precios lista para usar: forma y huella, cubre TODAS las plantillas del catálogo montado y no
    tiene más de EDAD_MAXIMA_INSTANTANEA_DIAS días en `hoy`. IntegridadRota si no (no es un fallo del experto: no suma
    intento; se redespliega). Sin `instantanea`, la que está junto al catálogo cargado (anexo_consumo.instantanea_vigente)."""
    if instantanea is None:
        from nucleo import anexo_consumo  # diferido: módulo de B
        instantanea = anexo_consumo.instantanea_vigente()
    errores = errores_instantanea(instantanea)
    if not errores and pilar_instantanea(instantanea) != pilar:
        errores = [f"la instantánea es de {pilar_instantanea(instantanea)} y la solicitud, de {pilar}"]
    if not errores:
        errores = errores_instantanea_catalogo(instantanea, catalogo) + errores_edad_instantanea(
            instantanea["fecha_consulta"], hoy)
    if errores:
        raise IntegridadRota("La instantánea de precios no vale: redesplegar para descargarla de nuevo", errores)
    return instantanea


def errores_pilar_respuesta(resp: object, pilar: str) -> list[str]:
    """La respuesta es del experto del pilar (el pilar de la respuesta es su `agente`, preventa-experto-<pilar>: el
    contrato del modelo es strict y no lleva más claves) y, en AWS, toda región que declara está en la UE
    (REGIONES_UE_AWS). [] si cuadra."""
    if not isinstance(resp, dict):
        return []   # la forma la juzga analizar_respuesta
    errores = []
    if resp.get("agente") != brief_mod.experto_de(pilar):
        errores.append(f"agente: {resp.get('agente')!r} y el del pilar es «{brief_mod.experto_de(pilar)}»")
    if pilar == "aws":
        for bloque in ("componentes", "precios"):
            for x in resp.get(bloque) or []:
                region = x.get("region") if isinstance(x, dict) else None
                if region not in (None, "") and region not in REGIONES_UE_AWS:
                    errores.append(f"{bloque} {x.get('id')}: región «{region}» fuera de la UE (admitidas: "
                                   f"{', '.join(REGIONES_UE_AWS)})")
    return errores


def registrar(estado: dict, experto: str, texto: str, catalogo: dict, perfiles: list[str], hoy: str,
              instantanea: dict | None = None) -> dict:
    """Valida, completa y registra la respuesta v4 del experto para el brief vigente (EN_ANALISIS).

    Antes de leerla, la instantánea de precios tiene que valer (instantanea_valida: IntegridadRota sin sumar intento).
    Brief no devuelto literal o con otro id -> bloquear + Bloqueo. Otros errores -> intento T2 + ReglaIncumplida (a 3/3,
    Bloqueo). Válida -> carga.respuestas_expertos[experto] con la respuesta COMPLETADA por el núcleo (esquema
    respuesta_experto_completa), la cascada de §5.3 y el contador T2 a 0. Devuelve lo registrado.
    """
    pilar = est_mod.pilar(estado)
    if experto != pilar:
        raise EntradaInvalida(f"Experto no admitido: {experto!r}", [f"el pilar de la solicitud es «{pilar}»"])
    if estado["estado"] != "EN_ANALISIS":
        raise TransicionNoPermitida(f"registrar-experto exige EN_ANALISIS y el estado es {estado['estado']}", [])
    brief = est_mod.brief_vigente(estado)
    if brief is None:
        raise TransicionNoPermitida("No hay brief vigente: primero enrutar", [est_mod.brief_id_vigente(estado)])
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", hoy or ""):
        raise EntradaInvalida(f"Fecha de registro no válida: {hoy!r}", [])
    instantanea = instantanea_valida(instantanea, catalogo, hoy, pilar)
    try:
        resp = parsear(texto)
    except ReglaIncumplida as e:
        _fallar(estado, "Respuesta del experto ilegible", e.errores or [str(e)])
    recibido = resp.get("brief_recibido")
    # PR19-1 (I1.10, LES-G-095 y LES-G-097.3): un eco no literal ya no bloquea en el mismo turno. El texto lo transporta el
    # código (el hosted, con su procedencia A2A) y el modelo lo copia mal a veces (3 de 7 en I1.9): analizar_respuesta lo
    # da como error («brief_recibido: no es literal; línea L, columna C…»), suma un intento T2 n/3 y el reintento lleva
    # ese motivo. Nunca se registra una respuesta con el eco distinto (falla cerrado) y a la tercera queda BLOQUEADA.
    if isinstance(recibido, str) and brief_mod.eco_identico(brief["texto"], recibido) \
            and resp.get("brief_id") != brief["brief_id"]:
        motivo = f"El experto devolvió el brief_id {resp.get('brief_id')!r} y el vigente es {brief['brief_id']}"
        est_mod.bloquear(estado, motivo)
        raise Bloqueo(motivo, [motivo])
    errores, completada = analizar_respuesta(resp, brief, catalogo, perfiles, estado["carga"].get("requisitos"),
                                             instantanea, hoy)
    errores = errores + errores_pilar_respuesta(resp, pilar)   # multinube: agente del pilar y, en AWS, regiones de la UE
    if errores:
        _fallar(estado, f"Respuesta del experto inválida ({len(errores)} errores)", errores)
    registro = {"registrada_el": hoy, "brief_id": brief["brief_id"], "respuesta": _nfc(completada)}
    est_mod.invalidar_desde(estado, "respuestas_expertos")
    estado["carga"]["respuestas_expertos"] = {pilar: registro}
    estado["intentos"]["T2"] = 0
    return registro
