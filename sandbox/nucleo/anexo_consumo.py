"""Anexo de consumo cloud orientativo de I1 (constructor B; CONTRATOS.md §4.12, §8 y §9).

Determinista: solo lee carga.respuestas_expertos (precios, componentes) y carga.verificacion
(veredicto de cada precio), y el catálogo para el nombre oficial (LES-G-093). Nunca inventa ni
corrige un precio: si un dato falta o no cuadra, falla en alto. No forma parte del precio cerrado
ni toca el generador canónico. Genera <codigo>-Anexo-Consumo.json y .xlsx (Montserrat y paleta
Devoteam, LES-G-072). Nada imprime ni guarda estado.json: lo hace la CLI.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import tempfile
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

from nucleo import estado as est_mod
from nucleo.errores import EntradaInvalida, IntegridadRota, ReglaIncumplida

MESES_ANUALES = 12
ESQUEMA = "preventa-anexo-consumo/1"
FUENTE_NOMBRE = "Azure Retail Prices"
FUENTE_URL = "https://prices.azure.com/api/retail/prices"
NOTA_FIJA = "Orientativo. No incluido en el precio cerrado; lo asume el cliente."
# Microsoft Learn, «Azure Retail Prices overview», consultado el 2026-10-08: «The currency that
# Microsoft uses to price all Azure services is USD [...] Other non-USD prices returned by the API
# are for your reference to help you estimate budget expenses».
AVISO_MONEDA = ("Microsoft fija en USD el precio de todos los servicios de Azure: los importes en EUR de "
                "Azure Retail Prices son orientativos y solo sirven para estimar el presupuesto; "
                "el único precio de referencia es el USD.")
# Multinube (esquemas/MULTINUBE.md): fuente y aviso de moneda de cada pilar. Google: la Cloud Billing Catalog API
# devuelve EUR con currencyConversionRate, que «includes any surcharge collected for billing in non USD currency»
# (docs.cloud.google.com/billing/docs/reference/rest/v1/services.skus/list, 2026-11-04). AWS: solo USD en el catálogo;
# el euro lo pone el código con el tipo del BCE, que avisa de que es informativo (estudio multinube (no publicado) §7.2).
FUENTES_PILAR = {"azure": (FUENTE_NOMBRE, FUENTE_URL),
                 "gcp": ("Google Cloud Billing Catalog", "https://cloudbilling.googleapis.com/v1/services"),
                 "aws": ("AWS Price List", "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json")}
AVISO_MONEDA_GCP = ("Google Cloud publica estos precios en EUR en su Cloud Billing Catalog; incluyen el recargo de "
                    "facturar en una moneda distinta del USD y son orientativos.")
AVISO_MONEDA_AWS = ("AWS publica sus precios en USD: los importes en EUR se han convertido con el tipo de cambio de "
                    "referencia del Banco Central Europeo del {fecha} (1 EUR = {tasa} USD). Son orientativos: la factura "
                    "de AWS puede emitirse en euros al tipo que AWS aplique en el momento del cobro.")


def procedencia_anexo(pilar: str, instantanea: dict) -> tuple[dict, str]:
    """(campos de la fuente del anexo además de consultado_el, aviso de moneda) del pilar. Fuera de Azure, la procedencia
    del euro de la instantánea registrada tiene que ser la del pilar (si no, IntegridadRota: no se afirma una moneda)."""
    from nucleo import experto  # diferido: experto importa este módulo dentro de sus funciones
    nombre, url = FUENTES_PILAR[pilar]
    if pilar == est_mod.PILAR_POR_DEFECTO:
        return {"nombre": nombre, "url": url}, AVISO_MONEDA
    fm = instantanea.get("fuente_moneda")
    if instantanea.get("pilar") != pilar or fm != experto.FUENTE_MONEDA[pilar]:
        raise IntegridadRota(f"Anexo: la instantánea registrada no declara la procedencia del euro de {pilar}",
                             [f"pilar {instantanea.get('pilar')!r}, fuente_moneda {fm!r}"])
    fuente = {"nombre": nombre, "url": url, "fuente_moneda": fm}
    if pilar != "aws":
        return fuente, AVISO_MONEDA_GCP
    tasa, fecha = instantanea.get("tipo_bce"), instantanea.get("fecha_tipo_bce")
    if isinstance(tasa, bool) or not isinstance(tasa, (int, float)) or not tasa > 0 or not isinstance(fecha, str):
        raise IntegridadRota("Anexo: AWS sin tipo de cambio del BCE en la respuesta registrada", [repr(tasa), repr(fecha)])
    fuente.update(tipo_bce=tasa, fecha_tipo_bce=fecha)
    return fuente, AVISO_MONEDA_AWS.format(fecha=fecha, tasa=texto_tasa(tasa))


def texto_tasa(tasa: float) -> str:
    """Tasa del BCE como la publica (cuatro decimales) con coma decimal: 1.1179 → «1,1179»."""
    return f"{Decimal(str(tasa)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}".replace(".", ",")


ESTADO_LINEA = {"OK": "VERIFICADO", "REPARADO": "VERIFICADO", "NO VERIFICABLE": "NO VERIFICADO"}
ESTADO_TOLERANCIA = "ORIENTATIVO"
# I1.7 (decisión 1): el verificador ya no contrasta precios; el de cada línea sale de la instantánea que el código
# descargó de Azure Retail Prices al desplegar (fecha en fuente.consultado_el).
ESTADO_INSTANTANEA = "INSTANTÁNEA DE PRECIOS"
_CENT = Decimal("0.01")
FMT_EUR = '#,##0.00\\ "€"'  # mismo formato que el XLSX canónico
_SKU_RE = re.compile(r"\bskuName eq '([^']{1,80})'")

# Paleta del XLSX canónico (generar_estimacion.py) y fuente corporativa (LES-G-072).
FUENTE = "Montserrat"
ROJO, GRIS, BLANCO, BANDA, BORDE = "F8485E", "3C3C3A", "FFFFFF", "F2F2F1", "BFBFBF"
COLUMNAS = (("Servicio", 28), ("Concepto", 30), ("SKU", 22), ("Región", 16), ("Cantidad mensual", 14),
            ("Unidad", 14), ("Precio unitario", 14), ("Moneda", 9), ("Coste mensual", 15),
            ("effectiveStartDate", 21), ("Fuente (filtro de la consulta)", 60), ("Estado", 16),
            ("Supuesto de cantidad", 50))


def _eur(x: Decimal) -> str:
    return str(x.quantize(_CENT, rounding=ROUND_HALF_UP))


def _dec(x: object) -> Decimal:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ValueError(f"no es un número: {x!r}")
    d = Decimal(str(x))
    if not d.is_finite():
        raise ValueError(f"número no finito: {x!r}")
    return d


def _sha256(ruta: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _textos(obj: object, ruta: str = "$"):
    if isinstance(obj, str):
        yield ruta, obj
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            yield from _textos(x, f"{ruta}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _textos(v, f"{ruta}.{k}")


def _reemplazar(origen: pathlib.Path, destino: pathlib.Path) -> None:
    """os.replace con el mismo reintento acotado y anotado que estado.escribir_atomico (REVPR-3, ARRSN-1): solo
    en Windows y solo ante PermissionError; cada reintento sale en stderr y en estado.REINTENTOS_REPLACE, y si
    persiste, el error sale tal cual con una nota."""
    from nucleo import estado as mod_estado  # importación diferida: módulo de A
    mod_estado._reemplazar(origen, destino)


def _escribir_atomico(ruta: pathlib.Path, datos: bytes) -> None:
    """Temporal en la misma carpeta + os.replace (con el reintento de _reemplazar) + chmod 644 (un 0600 da HTTP 500
    al descargar)."""
    ruta = pathlib.Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, nombre = tempfile.mkstemp(prefix=f".{ruta.name}.", suffix=".tmp", dir=ruta.parent)  # O_EXCL
    tmp = pathlib.Path(nombre)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
        os.chmod(tmp, 0o644)
        _reemplazar(tmp, ruta)
    finally:
        if tmp.exists():
            tmp.unlink()


# I1.7 (decisión 1 del comercial): la instantánea de precios va junto al catálogo montado (en el sandbox, con su prefijo de
# file_id: «<file_id>-precios_instantanea.json»). cargar_catalogo recuerda de dónde leyó el catálogo para que
# registrar-experto la encuentre sin cambiar la firma de los subcomandos; PREVENTA_PRECIOS la fija a mano.
NOMBRE_INSTANTANEA = "precios_instantanea.json"
_RUTA_CATALOGO: list[pathlib.Path] = []


def nombre_instantanea(ruta_catalogo: pathlib.Path) -> str:
    """Multinube: la instantánea se llama como el catálogo con «precios_instantanea» en vez de «catalogo_componentes»
    y sin el prefijo de file_id: «catalogo_componentes.json» → «precios_instantanea.json» (Azure, como siempre) y
    «catalogo_componentes_gcp.json» → «precios_instantanea_gcp.json»."""
    nombre = pathlib.Path(ruta_catalogo).name
    i = nombre.find("catalogo_componentes")
    return NOMBRE_INSTANTANEA if i < 0 else nombre[i:].replace("catalogo_componentes", "precios_instantanea", 1)


def ruta_instantanea(ruta_catalogo: pathlib.Path | None = None) -> pathlib.Path:
    """PREVENTA_PRECIOS si está fijada (sin espacios); si no, el único «precios_instantanea.json» (o
    «<prefijo>-precios_instantanea.json»; fuera de Azure, nombre_instantanea) de la carpeta del catálogo.
    IntegridadRota si no hay exactamente uno."""
    fijada = (os.environ.get("PREVENTA_PRECIOS") or "").strip()
    if fijada:
        ruta = pathlib.Path(fijada)
        if not ruta.is_file():
            raise IntegridadRota(f"PREVENTA_PRECIOS no apunta a un fichero: {ruta}", [])
        return ruta
    base = ruta_catalogo or (_RUTA_CATALOGO[-1] if _RUTA_CATALOGO else None)
    if base is None:
        raise IntegridadRota("No se sabe dónde está la instantánea de precios: carga antes el catálogo", [])
    carpeta, nombre = pathlib.Path(base).parent, nombre_instantanea(pathlib.Path(base))
    exacta = carpeta / nombre
    candidatos = [exacta] if exacta.is_file() else sorted(carpeta.glob(f"*-{nombre}"))
    if len(candidatos) != 1:
        raise IntegridadRota(f"Se esperaba exactamente una instantánea de precios junto al catálogo y hay "
                             f"{len(candidatos)}", [str(c) for c in candidatos] or [str(carpeta)])
    return candidatos[0]


def cargar_instantanea(ruta: pathlib.Path) -> dict:
    """Lee la instantánea (sin claves repetidas, NaN ni infinito) y la valida (experto.errores_instantanea)."""
    from nucleo import experto  # diferido: experto importa este módulo dentro de sus funciones
    try:
        inst = experto.parsear(pathlib.Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ReglaIncumplida) as e:
        raise IntegridadRota(f"No se puede leer la instantánea de precios {ruta}: {e}", [str(e)]) from e
    errores = experto.errores_instantanea(inst)
    if errores:
        raise IntegridadRota("La instantánea de precios no valida", errores)
    return inst


def instantanea_vigente() -> dict:
    """La instantánea junto al último catálogo cargado (o la de PREVENTA_PRECIOS)."""
    return cargar_instantanea(ruta_instantanea())


# Multinube: dominios de las fuentes que puede citar el catálogo de cada pilar (el esquema admite la unión).
HOSTS_PILAR = {"azure": ("learn.microsoft.com", "azure.microsoft.com"),
               "gcp": ("cloud.google.com", "docs.cloud.google.com"),
               "aws": ("docs.aws.amazon.com", "aws.amazon.com")}


def errores_catalogo_pilar(cat: dict, pilar: str) -> list[str]:
    """El catálogo es del pilar de la solicitud: `pilar` («azure» sin la clave), ids con su prefijo, fuentes de sus
    dominios, en Azure el modelo por defecto de siempre y en AWS solo regiones de la UE. [] si cuadra."""
    import urllib.parse
    from nucleo import experto  # diferido: experto importa este módulo dentro de sus funciones
    errores = []
    if cat.get("pilar", est_mod.PILAR_POR_DEFECTO) != pilar:
        errores.append(f"el catálogo es de {cat.get('pilar', est_mod.PILAR_POR_DEFECTO)} y la solicitud, de {pilar}")
    errores += [f"componente {c['id']}: el id no es de {pilar} (prefijo «{experto.PREFIJO_ID[pilar]}»)"
                for c in cat["componentes"] if not c["id"].startswith(experto.PREFIJO_ID[pilar])]
    hosts: set[str] = set()

    def urls(o: object) -> None:
        if isinstance(o, dict):
            for v in o.values():
                urls(v)
        elif isinstance(o, list):
            for v in o:
                urls(v)
        elif isinstance(o, str) and o.startswith(("http://", "https://")):
            hosts.add(urllib.parse.urlsplit(o).hostname or o)
    urls(cat)
    errores += [f"fuente de {h} en un catálogo de {pilar} (admitidas: {', '.join(HOSTS_PILAR[pilar])})"
                for h in sorted(hosts - set(HOSTS_PILAR[pilar]))]
    modelo = cat.get("modelo_por_defecto") or {}
    if pilar == "azure" and modelo and (modelo.get("componente"), modelo.get("despliegue")) != ("az-foundry",
                                                                                               "DataZoneStandard"):
        errores.append("modelo_por_defecto de Azure: componente «az-foundry» y despliegue «DataZoneStandard»")
    if pilar == "aws":
        regiones = [("modelo_por_defecto", modelo.get("region"))] + [(c["id"], c.get("region_ue"))
                                                                      for c in cat["componentes"]]
        errores += [f"{donde}: región «{r}» fuera de la UE (admitidas: {', '.join(experto.REGIONES_UE_AWS)})"
                    for donde, r in regiones if r is not None and r not in experto.REGIONES_UE_AWS]
    return errores


def cargar_catalogo(ruta: pathlib.Path, pilar: str = est_mod.PILAR_POR_DEFECTO) -> dict:
    """Lee y valida el catálogo con el esquema catalogo_componentes y que es del `pilar` (errores_catalogo_pilar);
    IntegridadRota si no. Recuerda la ruta (la instantánea de precios va en la misma carpeta)."""
    from nucleo import esquema  # importación diferida: módulo de A
    try:
        cat = json.loads(pathlib.Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise EntradaInvalida(f"No se puede leer el catálogo {ruta}: {e}", [str(e)])
    errores = list(esquema.validar(cat, esquema.cargar_pilar("catalogo_componentes", pilar)))
    if not errores:
        ids = [c["id"] for c in cat["componentes"]]
        errores += [f"id repetido en el catálogo: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
        errores += errores_catalogo_pilar(cat, pilar)
    if errores:
        raise IntegridadRota("El catálogo de componentes no valida", errores)
    _RUTA_CATALOGO[:] = [pathlib.Path(ruta)]
    return cat


# ── Cálculo ─────────────────────────────────────────────────────────────────

def _diferencia_relativa(valor_correcto: object, precio: Decimal) -> Decimal | None:
    """|vc - precio| / precio si valor_correcto es un decimal con punto; None si no lo es."""
    if not isinstance(valor_correcto, str) or not re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", valor_correcto.strip()):
        return None
    vc = Decimal(valor_correcto.strip())
    if precio == 0:
        return Decimal(0) if vc == 0 else None
    return abs(vc - precio) / precio


def es_observacion_no_precio(veredicto: dict) -> bool:
    """INT16-2 (I1.7): una OBSERVACION, o un DISCREPA no efectivo cuyo `campo` es otro que el precio (la cantidad, el
    sku…), nunca se compara con el precio: un número suelto en su valor_correcto es un factor o una cantidad. Con
    `campo` «precio», «ninguno» o sin campo (verificador anterior a v3) sigue la regla del 0,5 % de §7.3."""
    v = veredicto if isinstance(veredicto, dict) else {}
    campo = v.get("campo")
    return v.get("veredicto") == "OBSERVACION" or (
        v.get("veredicto") == "DISCREPA" and isinstance(campo, str) and campo not in ("precio", "ninguno"))


# H9 / LES-G-062: lo que no tiene precio no da error, pero el lector lo daría por gratis. Cada
# componente de la respuesta sin línea de precio se declara «no valorado» con su motivo, por código.
NO_VALORADO = "No valorado"
MOTIVO_SIN_PRECIO_PUBLICO = "Azure Retail Prices no publica su precio de consumo"
MOTIVO_SIN_PRECIO = "No se ha obtenido su precio en Azure Retail Prices"
# REV13-3: el mismo texto para todo servicio SaaS de Microsoft que no tiene precio en Azure (Teams, Entra ID,
# SharePoint…): no es un precio que falte, es que no se factura por Azure.
MOTIVO_SAAS = "Se licencia aparte, no se factura por Azure"
_SAAS = re.compile(r"\b(sharepoint|microsoft 365|office 365|exchange online|onedrive|teams|entra|dynamics 365)\b")
# PR15-2 (decisión del comercial del 11-10-2026): cada componente facturable de Azure lleva su precio o un motivo de no
# valoración de esta lista cerrada (campo motivo_no_valoracion de esquemas/respuesta_experto.json, v2); sin ninguna de
# las dos cosas, la respuesta se rechaza al registrarla y el anexo no se compone. Al cliente (anexo y diapositiva 8) se
# le dice MOTIVO_A_VALORAR; el motivo concreto va a la nota del revisor (motivos_para_revisor).
SIN_MOTIVO = "no_aplica"
MOTIVOS_NO_VALORACION = {
    "depende_del_volumen": "el coste depende de un volumen de uso que todavía no se conoce",
    "sin_medidor_publico": "Azure Retail Prices no publica un medidor de precio para ese servicio, SKU o región",
    "a_cargo_del_cliente": "el recurso ya lo tiene o lo paga el cliente fuera de esta propuesta",
    "incluido_en_otro_componente": "su coste va incluido en el precio de otro componente de la propuesta",
    "licencia_fuera_de_azure": "se licencia fuera de Azure y no se factura por consumo de Azure",
    "fuera_del_catalogo": "no está en el catálogo de componentes: su precio no se puede contrastar y lo cotiza el revisor",
    # I1.9 (PR18-1): el componente ES un recurso que el cliente ya tiene (entrada EX-nn de los requisitos); no se valora
    "existente_del_cliente": "el cliente ya tiene ese recurso y la propuesta lo reutiliza: no se valora",
}
MOTIVO_A_VALORAR = "A valorar con el volumen real"
# I1.9 (PR18-1): lo que lee el cliente en el anexo y en la diapositiva 8 de un recurso suyo; el texto es el que propuso
# D (CAMBIOS-I19-D §3), coherente con «<nombre> (sistema del cliente)» del diagrama. No es facturable (no entra en PR14-1).
MOTIVO_EXISTENTE = "Sistema que ya tiene el cliente"


def _plano(texto: object) -> str:
    t = unicodedata.normalize("NFD", unicodedata.normalize("NFC", str(texto or "")))
    return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn").lower()).strip()


def es_saas_sin_precio(entrada: dict | None, servicio: object) -> bool:
    """¿Servicio SaaS de Microsoft que se licencia aparte? Del catálogo, solo si no tiene servicio de precios
    en Azure Retail Prices; fuera del catálogo, por su nombre y sin «Azure» en él (no es un servicio de Azure)."""
    if entrada is not None:
        return not entrada.get("service_name_precios") and bool(_SAAS.search(_plano(entrada.get("nombre_oficial"))))
    nombre = _plano(servicio)
    return bool(_SAAS.search(nombre)) and "azure" not in nombre.split()


def no_valorados(estado: dict, catalogo: dict) -> list[dict]:
    """[{"componente_id", "servicio", "motivo", "facturable", "motivo_no_valoracion"}] de cada componente sin precio.

    Pura y determinista (orden de la respuesta). El nombre es el oficial del catálogo (LES-G-093) o
    el servicio declarado si es una desviación sin catálogo. El motivo (texto para el cliente) distingue el SaaS que
    se licencia aparte (`es_saas_sin_precio`, REV13-3), el servicio que Azure Retail Prices no publica
    (`service_name_precios` nulo en el catálogo), el facturable con motivo declarado (MOTIVO_A_VALORAR, PR15-2) y el
    que no se obtuvo; `motivo_no_valoracion` lleva el motivo concreto para la nota del revisor.
    IntegridadRota si un componente cita un catalogo_id que no está en el catálogo montado.
    """
    resp = est_mod.registro_experto(estado).get("respuesta")
    if not isinstance(resp, dict):
        return []
    con_precio = set(precios_que_cubren(resp, catalogo))  # I1.6: ni el auxiliar ni el de referencia cubren
    filas = [x for x in clasificar_componentes(resp, catalogo) if x["componente_id"] not in con_precio]
    # D-C1 (I1.9, CAMBIOS-I19-D §6.5): un sistema que ya tiene el cliente se llama como en el diagrama (el oficial si el
    # valor citado lo nombra; si no, el valor citado), no con el servicio del catálogo: «Azure App Service · Sistema que
    # ya tiene el cliente» junto a un App Service valorado confundía. Una entrada que no existe lanza IntegridadRota.
    if any(x["motivo_no_valoracion"] == "existente_del_cliente" for x in filas):
        from nucleo import textos_cliente  # diferido: textos_cliente importa este módulo
        campos = ((estado.get("carga") or {}).get("requisitos") or {}).get("campos") or {}
        oficiales = {c.get("id"): c.get("nombre_oficial") for c in (catalogo or {}).get("componentes") or []}
        comps = {c.get("id"): c for c in resp.get("componentes") or [] if isinstance(c, dict)}
        for x in filas:
            comp = comps.get(x["componente_id"])
            entrada = (textos_cliente.entrada_de(comp, campos)
                       if comp is not None and x["motivo_no_valoracion"] == "existente_del_cliente" else None)
            if entrada is not None:
                x["servicio"] = unicodedata.normalize("NFC", textos_cliente.nombre_base_existente(comp, entrada, oficiales))
    return filas


def precios_que_cubren(resp: dict, catalogo: dict) -> dict[str, list[str]]:
    """{componente_id: [precio_id]} de los precios que VALORAN su componente (I1.6): con cantidad_mensual (un precio
    unitario de referencia, null, no suma) y del servicio propio del componente: un precio auxiliar de la lista blanca
    nunca cubre a otro componente (REV15-1, experto.precio_propio). Misma lógica en
    verificar_paquete.precios_que_cubren_replica."""
    from nucleo import experto  # diferido: experto importa este módulo dentro de validar_respuesta
    comps = {c.get("id"): c for c in resp.get("componentes") or [] if isinstance(c, dict)}
    salida: dict[str, list[str]] = {}
    for p in resp.get("precios") or []:
        if not isinstance(p, dict) or p.get("cantidad_mensual") is None:
            continue
        comp = comps.get(p.get("componente_id"))
        if comp is not None and experto.precio_propio(p, comp, catalogo):
            salida.setdefault(p.get("componente_id"), []).append(str(p.get("id")))
    return salida


def es_respuesta_v1(resp: object) -> bool:
    """Respuesta del contrato anterior a I1.5: tiene componentes y ninguno lleva la clave motivo_no_valoracion."""
    comps = resp.get("componentes") if isinstance(resp, dict) else None
    return (isinstance(comps, list) and bool(comps)
            and not any(isinstance(c, dict) and "motivo_no_valoracion" in c for c in comps))


def motivo_declarado(comp: dict) -> str:
    """motivo_no_valoracion del componente; SIN_MOTIVO si no lo trae (respuestas anteriores a I1.5)."""
    m = comp.get("motivo_no_valoracion") if isinstance(comp, dict) else None
    return m if isinstance(m, str) and m else SIN_MOTIVO


def clasificar_componentes(resp: dict, catalogo: dict) -> list[dict]:
    """[{"componente_id", "servicio", "motivo", "facturable", "motivo_no_valoracion"}] de TODOS los componentes.

    `motivo` es el texto para el cliente que llevaría sin precio: MOTIVO_SAAS, MOTIVO_SIN_PRECIO_PUBLICO,
    MOTIVO_A_VALORAR (facturable de Azure con motivo declarado, PR15-2) o MOTIVO_SIN_PRECIO (facturable sin motivo:
    solo en respuestas anteriores a I1.5, que la v2 del esquema ya no admite). `facturable`: servicio de Azure con
    precio publicado en Retail Prices (se factura por consumo). `motivo_no_valoracion`: el declarado; si no hay, el
    que se deduce del catálogo (licencia_fuera_de_azure para el SaaS, sin_medidor_publico sin servicio de precios) o
    None para un facturable sin motivo. IntegridadRota si un componente cita un catalogo_id que no está en el catálogo.
    """
    cat = {c["id"]: c for c in (catalogo or {}).get("componentes") or []}
    salida = []
    for comp in resp.get("componentes") or []:
        cid = comp.get("catalogo_id")
        if cid and cid not in cat:
            raise IntegridadRota(f"{comp.get('id')}: {cid} no está en el catálogo montado", [])
        entrada = cat.get(cid) if cid else None
        servicio = entrada["nombre_oficial"] if entrada else str(comp.get("servicio") or "")
        sin_publicar = entrada is not None and not entrada.get("service_name_precios")
        saas = es_saas_sin_precio(entrada, servicio)
        declarado = motivo_declarado(comp)
        codigo = (declarado if declarado != SIN_MOTIVO else "licencia_fuera_de_azure" if saas
                  else "sin_medidor_publico" if sin_publicar else None)
        existente = declarado == "existente_del_cliente"  # I1.9: un recurso del cliente no se factura en la propuesta
        facturable = not saas and not sin_publicar and not existente
        motivo = (MOTIVO_EXISTENTE if existente else MOTIVO_SAAS if saas else MOTIVO_SIN_PRECIO_PUBLICO if sin_publicar
                  else MOTIVO_A_VALORAR if codigo else MOTIVO_SIN_PRECIO)
        salida.append({"componente_id": comp.get("id"), "servicio": unicodedata.normalize("NFC", servicio),
                       "motivo": motivo, "facturable": facturable, "motivo_no_valoracion": codigo})
    return salida


def facturables_azure(resp: dict, catalogo: dict) -> list[dict]:
    """PR14-1 / VER14-1: componentes de Azure que se facturan por consumo y tienen precio publicado en Azure
    Retail Prices (ni SaaS que se licencia aparte ni servicio sin precio público). Si hay alguno, una respuesta o
    un anexo sin ningún precio enseñaría al cliente un consumo de 0,00 €: se rechaza (LES-G-062)."""
    return [x for x in clasificar_componentes(resp, catalogo) if x["facturable"]]


def motivo_sin_precios(facturables: list[dict]) -> str:
    """Motivo común (núcleo y puerta) del rechazo de PR14-1."""
    nombres = list(dict.fromkeys(x["servicio"] for x in facturables))
    return (f"no hay ningún precio de consumo y {len(nombres)} componentes de Azure se facturan por consumo "
            f"({', '.join(nombres)}): el consumo saldría a 0,00 € (PR14-1)")


def errores_cobertura(resp: dict, catalogo: dict) -> list[dict]:
    """PR15-2: [{"componente_id", "regla", "detalle"}] de cada componente que incumple la cobertura de precios, en el
    orden de la respuesta; [] si cumple. Reglas (misma lógica en verificar_paquete.errores_cobertura_replica):
    - «sin_precio_ni_motivo»: facturable de Azure sin ningún precio que lo cubra y con motivo_no_valoracion «no_aplica»;
    - «precio_y_motivo»: tiene precio que lo cubre y declara un motivo de no valoración (se contradicen);
    - «fuera_del_catalogo_con_id»: declara «fuera_del_catalogo» y lleva catalogo_id;
    - «licencia_con_precio_azure» (REV16-1): declara «licencia_fuera_de_azure» y su fila del catálogo tiene servicio de
      precios en Azure (service_name_precios): se factura por consumo de Azure;
    - «medidor_publico_en_catalogo» (REV16-1): declara «sin_medidor_publico» y su fila tiene plantillas de precio
      comprobadas en la región del componente (la region_ue de la fila, o cualquiera si la fila fija region_precio).
    «a_cargo_del_cliente» e «incluido_en_otro_componente» se comprueban con su dato (motivo_cita, incluido_en y el
    `incluye` del catálogo) en experto.errores_motivos (I1.7, decisión del PM); su motivo va a la nota del revisor.
    Cubre solo un precio propio con cantidad (precios_que_cubren, I1.6): el auxiliar (REV15-1) y el unitario de
    referencia de «depende_del_volumen» no. IntegridadRota si un componente cita un catalogo_id que no está en el
    catálogo montado."""
    con_precio = precios_que_cubren(resp, catalogo)
    comps = {c.get("id"): c for c in resp.get("componentes") or [] if isinstance(c, dict)}
    cat = {c.get("id"): c for c in (catalogo or {}).get("componentes") or [] if isinstance(c, dict)}
    admitidos = ", ".join(sorted(MOTIVOS_NO_VALORACION))
    salida = []
    for x in clasificar_componentes(resp, catalogo):
        cid, comp = x["componente_id"], comps.get(x["componente_id"]) or {}
        declarado = motivo_declarado(comp)
        if x["facturable"] and cid not in con_precio and declarado == SIN_MOTIVO:
            salida.append({"componente_id": cid, "regla": "sin_precio_ni_motivo", "detalle": (
                f"{cid} «{x['servicio']}» se factura por consumo en Azure y no tiene precio propio con cantidad ni motivo "
                f"de no valoración (un precio auxiliar o uno de referencia no lo cubren): pon una línea de consumo con "
                f"una de sus plantillas o en motivo_no_valoracion por qué no se puede valorar ({admitidos}) (PR15-2)")})
        if cid in con_precio and declarado != SIN_MOTIVO:
            salida.append({"componente_id": cid, "regla": "precio_y_motivo", "detalle": (
                f"{cid} tiene precio ({', '.join(con_precio[cid])}) y motivo_no_valoracion «{declarado}»: con precio, "
                f"el motivo es «{SIN_MOTIVO}» (PR15-2)")})
        if declarado == "fuera_del_catalogo" and comp.get("catalogo_id"):
            salida.append({"componente_id": cid, "regla": "fuera_del_catalogo_con_id", "detalle": (
                f"{cid} declara «fuera_del_catalogo» y lleva catalogo_id {comp.get('catalogo_id')}: ese motivo es solo "
                "para un componente sin catalogo_id; usa otro de la lista (PR15-2)")})
        fila = cat.get(comp.get("catalogo_id")) if comp.get("catalogo_id") else None
        if declarado == "licencia_fuera_de_azure" and fila is not None and fila.get("service_name_precios"):
            salida.append({"componente_id": cid, "regla": "licencia_con_precio_azure", "detalle": (
                f"{cid} declara «licencia_fuera_de_azure» y {fila.get('nombre_oficial')} se factura por consumo de Azure "
                f"(serviceName «{fila.get('service_name_precios')}» en Retail Prices): valóralo con una de sus "
                "plantillas (REV16-1)")})
        if declarado == "sin_medidor_publico" and medidor_publico_en_catalogo(comp, fila):
            salida.append({"componente_id": cid, "regla": "medidor_publico_en_catalogo", "detalle": (
                f"{cid} declara «sin_medidor_publico» y {fila.get('nombre_oficial')} tiene plantillas de precio "
                f"comprobadas en {fila.get('region_precio') or fila.get('region_ue')}: valóralo con una línea de consumo "
                "de su plantilla (el precio lo pone el código desde la instantánea), nunca con este motivo (REV16-1)")})
    return salida


def medidor_publico_en_catalogo(comp: dict, fila: dict | None) -> bool:
    """REV16-1: la fila del catálogo del componente tiene plantillas de precio comprobadas en su región: la fila fija
    region_precio («Global», vale para cualquier región) o la región del componente es la region_ue de la fila."""
    if not isinstance(fila, dict) or not fila.get("plantillas_precio"):
        return False
    return bool(fila.get("region_precio")) or (comp or {}).get("region") == fila.get("region_ue")


def motivos_para_revisor(sin_precio: list[dict]) -> list[str]:
    """Una línea por componente sin precio con su motivo concreto, para la nota del revisor (PR15-2). Al cliente solo
    llega el texto de `motivo` (MOTIVO_A_VALORAR para los facturables con motivo)."""
    salida = []
    for x in sin_precio:
        codigo = x.get("motivo_no_valoracion")
        if codigo in MOTIVOS_NO_VALORACION:  # VA18-10 (I1.9): la explicación, sin el código del motivo
            explicacion = MOTIVOS_NO_VALORACION[codigo]
        else:
            explicacion = "sin motivo de no valoración (respuesta anterior a I1.5)"
        salida.append(f"{x.get('servicio')} ({x.get('componente_id')}): sin valorar; {explicacion}. "
                      f"Al cliente: «{x.get('motivo')}».")
    return salida


# Clave reservada de `detalle_lineas` (nunca choca con un P-nn): lleva los no valorados al XLSX
# también cuando lo regenera paquete.py, que pasa `detalle` tal cual.
CLAVE_NO_VALORADOS = "_no_valorados"


def aviso_no_valorado(item: dict) -> str:
    """Texto del aviso del anexo para un componente sin precio (el mismo en JSON, XLSX y nota)."""
    return f"{item['servicio']}: {NO_VALORADO.lower()}. {item['motivo']}, así que no suma en el total orientativo."


def _construir(estado: dict, catalogo: dict) -> tuple[dict, dict]:
    """(anexo, detalle por precio_id con sku y estado de la línea). Falla en alto si algo no cuadra."""
    from nucleo import textos_cliente  # importación diferida: módulo de C (barrido único de §0)
    carga = estado.get("carga") or {}
    reg = est_mod.registro_de_carga(carga) or None
    ver = carga.get("verificacion")
    if not isinstance(reg, dict) or not isinstance(reg.get("respuesta"), dict):
        raise ReglaIncumplida("Anexo: no hay respuesta válida del experto", ["P2: registrar-experto antes"])
    if not isinstance(ver, dict) or (ver.get("resultado") or {}).get("verificada") is not True:
        raise ReglaIncumplida("Anexo: la verificación vigente no está superada", ["P5: registrar-verificacion antes"])
    cons = carga.get("consolidado") or {}
    if cons.get("consolidado_id") and ver.get("consolidado_id") != cons.get("consolidado_id"):
        raise IntegridadRota("Anexo: la verificación no es del consolidado vigente",
                             [f"{ver.get('consolidado_id')} frente a {cons.get('consolidado_id')}"])
    resp, resultado = reg["respuesta"], ver["resultado"]
    instantanea = ((resp.get("valoracion_nucleo") or {}).get("instantanea") or {})
    de_instantanea = bool(instantanea.get("fecha"))  # respuesta v4: precios de la instantánea (I1.7)
    nombres = {c["id"]: c["nombre_oficial"] for c in catalogo["componentes"]}
    comps = {c["id"]: c for c in resp.get("componentes") or []}
    veredictos = {e["id"]: e for e in (ver.get("respuesta") or {}).get("elementos") or []}
    no_verif = {x.get("id") for x in resultado.get("no_verificables") or [] if isinstance(x, dict)}
    discrepa = {x.get("id") for x in resultado.get("discrepa") or [] if isinstance(x, dict)}
    pilar = est_mod.pilar(estado)
    procedencia, aviso_moneda = procedencia_anexo(pilar, instantanea)
    lineas, detalle, avisos, errores = [], {}, [aviso_moneda], []
    for p in resp.get("precios") or []:
        if p.get("cantidad_mensual") is None:  # I1.6: precio unitario de referencia; no suma (va a la nota del revisor)
            continue
        pid, comp = p["id"], comps.get(p["componente_id"])
        v = veredictos.get(pid)
        if comp is None or (v is None and not de_instantanea):
            errores.append(f"{pid}: sin componente {p['componente_id']} en la respuesta o sin veredicto del verificador")
            continue
        if comp.get("catalogo_id"):
            if comp["catalogo_id"] not in nombres:
                errores.append(f"{pid}: {comp['catalogo_id']} no está en el catálogo montado")
                continue
            servicio = nombres[comp["catalogo_id"]]
        else:
            servicio = comp["servicio"]
            avisos.append(f"{pid}: servicio fuera del catálogo (desviación justificada por el experto).")
        if p.get("moneda") != "EUR":
            errores.append(f"{pid}: moneda {p.get('moneda')!r}; el anexo solo admite EUR de Azure Retail Prices")
            continue
        precio = _dec(p["precio"])
        estado_linea = None
        if pid in discrepa:
            errores.append(f"{pid}: DISCREPA efectivo del verificador; no se publica un precio en duda")
            continue
        if v is None:  # I1.7: precio de la instantánea (el código lo tomó de Azure Retail Prices; no hay veredicto)
            verif, estado_linea = "OK", ESTADO_INSTANTANEA
        elif pid in no_verif or v["veredicto"] == "NO VERIFICABLE":
            verif = "NO VERIFICABLE"
            avisos.append(f"{pid} sin contraste independiente del verificador.")
        elif v["veredicto"] == "OK" or es_observacion_no_precio(v):
            verif = "OK"  # INT16-2: una objeción no efectiva sobre otro campo (cantidad, sku) nunca toca el precio
            if v["veredicto"] != "OK":
                avisos.append(f"{pid}: observación del verificador sobre «{v.get('campo')}» (no efectiva; no cambia el "
                              "precio; va a la nota del revisor).")
        else:  # DISCREPA de precio dentro de la tolerancia del 0,5 % (§7.3): se conserva el precio del experto
            dif = _diferencia_relativa(v.get("valor_correcto"), precio)
            if dif is None or dif > Decimal("0.005"):
                errores.append(f"{pid}: DISCREPA que la verificación no registra como efectivo ni cabe en el 0,5 %")
                continue
            verif, estado_linea = "OK", ESTADO_TOLERANCIA
            avisos.append(f"{pid}: el verificador indica {v['valor_correcto']} EUR (diferencia del "
                          f"{_eur(dif * 100)} %); se conserva el precio del experto.")
        coste = (precio * _dec(p["cantidad_mensual"])).quantize(_CENT, rounding=ROUND_HALF_UP)
        lineas.append({"precio_id": pid, "componente_id": p["componente_id"], "servicio": servicio,
                       "concepto": p["concepto"], "region": p["region"], "filtro": p["filtro"],
                       "precio_unitario": p["precio"], "unidad": p["unidad"], "cantidad_mensual": p["cantidad_mensual"],
                       "supuesto_cantidad": p["supuesto_cantidad"], "effectiveStartDate": p["effectiveStartDate"],
                       "coste_mensual_eur": _eur(coste), "verificacion": verif})
        detalle[pid] = {"sku": comp.get("sku") or "", "estado": estado_linea or ESTADO_LINEA[verif]}
    if not lineas and not errores:
        facturables = facturables_azure(resp, catalogo)
        if facturables:  # PR14-1: un anexo vacío con Azure facturable enseña 0,00 € de consumo al cliente
            errores.append(f"Anexo sin líneas: {motivo_sin_precios(facturables)}; repetir el análisis con sus precios")
        else:
            avisos.append("El experto no ha declarado precios de consumo: el anexo no tiene líneas.")
    # PR15-2: un facturable sin precio ni motivo no llega al anexo (la respuesta ya se rechaza al registrarla). Una
    # respuesta v1 (anterior a I1.5) no se puede registrar ni cargar desde estado.json: solo llega aquí al recomponer
    # un paquete antiguo, que conserva su anexo de entonces y la puerta rechaza aparte (puerta de su época).
    if not errores and not es_respuesta_v1(resp):
        errores += [f"Anexo: {x['detalle']}" for x in errores_cobertura(resp, catalogo)]
    if not errores:
        sin_precio = no_valorados(estado, catalogo)
        avisos += [aviso_no_valorado(x) for x in sin_precio]
        detalle[CLAVE_NO_VALORADOS] = sin_precio
    total = sum((Decimal(x["coste_mensual_eur"]) for x in lineas), Decimal(0))
    consultado = instantanea.get("fecha") if de_instantanea else reg.get("registrada_el")
    if de_instantanea:
        avisos.append(f"Precios consultados el {consultado} en {procedencia['nombre']} (instantánea descargada por el código "
                      "al desplegar).")
    if not errores and detalle.get(CLAVE_NO_VALORADOS):
        n = len(detalle[CLAVE_NO_VALORADOS])
        avisos.append(f"El total solo suma los conceptos valorados: {n} componente{'s' if n != 1 else ''} "
                      f"{'quedan' if n != 1 else 'queda'} como «{NO_VALORADO}».")
    anexo = {"schema": ESQUEMA, "codigo": estado.get("codigo"), "moneda": "EUR",
             "fuente": {"nombre": procedencia["nombre"], "url": procedencia["url"], "consultado_el": consultado,
                        **{k: v for k, v in procedencia.items() if k not in ("nombre", "url")}},
             "lineas": lineas, "total_mensual_eur": _eur(total), "total_anual_eur": _eur(total * MESES_ANUALES),
             "avisos": avisos, "nota_fija": NOTA_FIJA}
    anexo = json.loads(json.dumps(anexo, ensure_ascii=False))  # copia independiente de la respuesta
    anexo = _nfc(anexo)
    for ruta, texto in _textos(anexo):
        errores += [f"P9 {ruta}: marcador prohibido «{m}» (LES-G-006)" for m in textos_cliente.marcadores(texto)]
    if errores:
        raise ReglaIncumplida(f"Anexo de consumo rechazado: {len(errores)} errores", errores)
    return anexo, detalle


def _nfc(obj: object) -> object:
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, list):
        return [_nfc(x) for x in obj]
    if isinstance(obj, dict):
        return {_nfc(k): _nfc(v) for k, v in obj.items()}
    return obj


def calcular(estado: dict, catalogo: dict) -> dict:
    """Bloque anexo_consumo (esquema anexo_consumo); puro: no muta el estado."""
    return _construir(estado, catalogo)[0]


def detalle_lineas(estado: dict, catalogo: dict) -> dict:
    """{precio_id: {"sku", "estado"}} para el XLSX (VERIFICADO, ORIENTATIVO o NO VERIFICADO), más
    CLAVE_NO_VALORADOS con la lista de `no_valorados` (filas «No valorado» del XLSX, H9)."""
    return _construir(estado, catalogo)[1]


# ── Ficheros ────────────────────────────────────────────────────────────────

def _exigir_esquema(anexo: dict) -> None:
    from nucleo import esquema  # importación diferida: módulo de A
    errores = list(esquema.validar(anexo, esquema.cargar("anexo_consumo")))
    if errores:
        raise IntegridadRota("El anexo no valida contra su esquema (no se escribe)", errores)


def escribir_json(anexo: dict, ruta: pathlib.Path) -> str:
    """<codigo>-Anexo-Consumo.json con indent 2 y UTF-8, escritura atómica y 0644; SHA-256."""
    _exigir_esquema(anexo)
    datos = (json.dumps(anexo, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    _escribir_atomico(pathlib.Path(ruta), datos)
    return _sha256(pathlib.Path(ruta))


ANCHO_TOTAL = sum(a for _, a in COLUMNAS)


def _alto(textos: list[tuple[str, float]], tam: int = 10) -> float:
    """Alto de fila (puntos) para que el texto ajustado no se corte: líneas estimadas por ancho."""
    lineas = max((-(-len(t) // max(1, int(a * 8 / tam))) for t, a in textos if t), default=1)
    return max(15.0, round(lineas * tam * 1.45 + 4, 1))


def _sku_de_filtro(filtro: str) -> str:
    m = _SKU_RE.search(filtro or "")
    return m.group(1) if m else "no indicado en la consulta"


def generar_xlsx(anexo: dict, ruta: pathlib.Path, detalle: dict | None = None) -> str:
    """XLSX interno del anexo: Montserrat en todas las celdas y solo la paleta Devoteam; SHA-256.

    `detalle` ({precio_id: {"sku", "estado"}}, de `detalle_lineas`) aporta el SKU del componente y el
    estado ORIENTATIVO; sin él, el SKU sale del filtro de la consulta y el estado del veredicto.
    Con CLAVE_NO_VALORADOS, cada componente sin precio lleva su fila «No valorado» y su motivo
    antes de los totales (LES-G-062); el aviso equivalente figura siempre en la cabecera.
    """
    import openpyxl  # presente en el sandbox (I0 b) y en el .venv
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    _exigir_esquema(anexo)
    detalle = detalle or {}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Anexo consumo"
    lado = Side(style="thin", color=BORDE)
    borde = Border(left=lado, right=lado, top=lado, bottom=lado)

    def poner(fila: int, col: int, valor, negrita=False, color=GRIS, fondo=None, fmt=None, tam=10):
        c = ws.cell(fila, col, valor)
        c.font = Font(name=FUENTE, size=tam, bold=negrita, color=color)
        c.alignment = Alignment(vertical="top", wrap_text=True)
        if fondo:
            c.fill = PatternFill("solid", start_color=fondo, end_color=fondo)
        if fmt:
            c.number_format = fmt
        return c

    def bloque(fila: int, texto: str, **kw) -> None:
        """Texto de cabecera a lo ancho de toda la tabla (celdas combinadas) con su alto calculado."""
        poner(fila, 1, texto, **kw)
        ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=len(COLUMNAS))
        ws.row_dimensions[fila].height = _alto([(texto, ANCHO_TOTAL)], kw.get("tam", 10))

    fuente = anexo["fuente"]
    bloque(1, f"ANEXO DE CONSUMO CLOUD ORIENTATIVO — {anexo['codigo']}", negrita=True, color=ROJO, tam=14)
    bloque(2, anexo["nota_fija"], negrita=True)
    bloque(3, f"Fuente: {fuente['nombre']} ({fuente['url']}), precios consultados el {fuente['consultado_el']}. "
              f"Moneda: {anexo['moneda']}.")
    fila = 4
    for aviso in anexo["avisos"]:
        bloque(fila, f"Aviso: {aviso}")
        fila += 1
    fila += 1
    for col, (titulo, ancho) in enumerate(COLUMNAS, 1):
        poner(fila, col, titulo, negrita=True, color=BLANCO, fondo=ROJO).border = borde
        ws.column_dimensions[openpyxl.utils.get_column_letter(col)].width = ancho
    ws.row_dimensions[fila].height = _alto([(t, a) for t, a in COLUMNAS])
    cab = fila
    for i, ln in enumerate(anexo["lineas"]):
        fila += 1
        d = detalle.get(ln["precio_id"]) or {}
        valores = (ln["servicio"], ln["concepto"], d.get("sku") or _sku_de_filtro(ln["filtro"]), ln["region"],
                   ln["cantidad_mensual"], ln["unidad"], ln["precio_unitario"], anexo["moneda"],
                   float(Decimal(ln["coste_mensual_eur"])), ln["effectiveStartDate"],
                   f"{fuente['nombre']}: {ln['filtro']}", d.get("estado") or ESTADO_LINEA[ln["verificacion"]],
                   ln["supuesto_cantidad"])
        cantidad = "#,##0" if float(ln["cantidad_mensual"]).is_integer() else "#,##0.0###"
        formatos = {5: cantidad, 7: "0.00####", 9: FMT_EUR}
        for col, v in enumerate(valores, 1):
            poner(fila, col, v, fondo=BANDA if i % 2 else BLANCO, fmt=formatos.get(col)).border = borde
        ws.row_dimensions[fila].height = _alto([(str(v), a) for v, (_, a) in zip(valores, COLUMNAS)])
    for item in detalle.get(CLAVE_NO_VALORADOS) or []:
        fila += 1
        valores = {1: item["servicio"], 2: NO_VALORADO, 9: NO_VALORADO, 12: NO_VALORADO,
                   13: f"{item['motivo']}, así que no suma en el total orientativo."}
        for col in range(1, len(COLUMNAS) + 1):
            poner(fila, col, valores.get(col), fondo=BLANCO).border = borde
        ws.row_dimensions[fila].height = _alto([(str(valores.get(c) or ""), a)
                                                for c, (_, a) in enumerate(COLUMNAS, 1)])
    # I1.6 (D): con filas «No valorado», el total solo suma lo valorado y la fila lo dice (como la diapositiva 8)
    sufijo = ", conceptos valorados" if detalle.get(CLAVE_NO_VALORADOS) else ""
    for etiqueta, importe in ((f"Total mensual (EUR{sufijo})", anexo["total_mensual_eur"]),
                              (f"Total anual (EUR, {MESES_ANUALES} meses{sufijo})", anexo["total_anual_eur"])):
        fila += 1
        poner(fila, 1, etiqueta, negrita=True, fondo=BANDA).border = borde
        poner(fila, 9, float(Decimal(importe)), negrita=True, fondo=BANDA, fmt=FMT_EUR).border = borde
    ws.freeze_panes = ws.cell(cab + 1, 1)
    # VA18-17 (I1.9): impreso o exportado a PDF, A4 horizontal y una página de ancho (ocupaba 7 u 8 y cortaba el
    # título); la cabecera de la tabla se repite en cada página
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{cab}:{cab}"
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
    wb.properties.title = f"{anexo['codigo']} · Anexo de consumo cloud orientativo"
    wb.properties.creator = "Responsable comercial"
    wb.properties.lastModifiedBy = "Responsable comercial"
    wb.properties.category = "Preventa"
    ruta = pathlib.Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, nombre = tempfile.mkstemp(prefix=f".{ruta.name}.", suffix=".xlsx", dir=ruta.parent)  # O_EXCL
    os.close(fd)
    tmp = pathlib.Path(nombre)
    try:
        wb.save(tmp)
        os.chmod(tmp, 0o644)
        _reemplazar(tmp, ruta)
    finally:
        if tmp.exists():
            tmp.unlink()
    return _sha256(ruta)


def errores_edad(estado: dict, hoy: str) -> list[str]:
    """I1.7: la instantánea de los precios registrados no tiene más de 31 días en `hoy` (experto.errores_edad_instantanea);
    [] para una respuesta anterior a la v4 (sin instantánea)."""
    from nucleo import experto  # diferido
    resp = est_mod.registro_experto(estado).get("respuesta") or {}
    fecha = ((resp.get("valoracion_nucleo") or {}).get("instantanea") or {}).get("fecha")
    return experto.errores_edad_instantanea(fecha, hoy) if fecha else []


def aplicar(estado: dict, catalogo: dict, dir_salida: pathlib.Path, hoy: str | None = None) -> dict:
    """Calcula el anexo, escribe JSON y XLSX y solo entonces muta el estado.

    Si el anexo cambia: carga.anexo_consumo y estado.invalidar_desde("anexo_consumo") (anula
    estimacion y textos_cliente, §5.3). Siempre: artefactos.anexo_xlsx y artefactos.anexo_json.
    I1.7: antes, la instantánea de los precios no puede tener más de 31 días en `hoy` (por defecto, estado.hoy()):
    IntegridadRota (redesplegar y repetir el análisis). `calcular` sigue siendo pura (la puerta lo recompone).
    """
    from nucleo import estado as mod_estado  # importación diferida: módulo de A
    edad = errores_edad(estado, hoy or mod_estado.hoy().isoformat())
    if edad:
        raise IntegridadRota("Anexo: la instantánea de precios de la respuesta registrada está caducada", edad)
    anexo, detalle = _construir(estado, catalogo)
    dir_salida = pathlib.Path(dir_salida)
    rj = dir_salida / f"{anexo['codigo']}-Anexo-Consumo.json"
    rx = dir_salida / f"{anexo['codigo']}-Anexo-Consumo.xlsx"
    # Los dos ficheros se escriben primero con nombre provisional y solo se sustituyen si salen los
    # dos: un fallo del XLSX no deja un JSON nuevo junto a un XLSX viejo.
    # Si falla la segunda sustitución, se restaura el JSON anterior (o se retira el nuevo).
    pj, px = rj.with_name(f".{rj.name}.nuevo"), rx.with_name(f".{rx.name}.nuevo.xlsx")
    anterior = rj.with_name(f".{rj.name}.anterior")
    conservar_anterior = False  # si la restauración también falla, la copia previa no se borra
    try:
        sha_j = escribir_json(anexo, pj)
        sha_x = generar_xlsx(anexo, px, detalle)
        habia_json = rj.exists()
        if habia_json:
            _reemplazar(rj, anterior)
        try:
            _reemplazar(pj, rj)
            _reemplazar(px, rx)
        except OSError:
            conservar_anterior = habia_json
            if habia_json:
                _reemplazar(anterior, rj)
                conservar_anterior = False
            elif rj.exists():
                rj.unlink()
            raise
    finally:
        for prov in (pj, px) + (() if conservar_anterior else (anterior,)):
            if prov.exists():
                prov.unlink()
    carga = estado["carga"]
    if carga.get("anexo_consumo") != anexo:
        carga["anexo_consumo"] = anexo
        mod_estado.invalidar_desde(estado, "anexo_consumo")
        if carga.get("estimacion") is not None or carga.get("textos_cliente") is not None:
            raise IntegridadRota("invalidar_desde no anuló estimacion y textos_cliente", ["§5.3"])
    art = estado.setdefault("artefactos", {})
    art["anexo_json"] = {"nombre": rj.name, "sha256": sha_j, "bytes": rj.stat().st_size}
    art["anexo_xlsx"] = {"nombre": rx.name, "sha256": sha_x, "bytes": rx.stat().st_size}
    return anexo
