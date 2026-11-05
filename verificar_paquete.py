"""Puerta real de I1: verifica en local, sin LLM, un paquete de preventa descargado del sandbox.

Uso (CONTRATOS.md §4.18 y §13, columna «Local (E)»):

    python verificar_paquete.py <ZIP o carpeta> --transcripcion <ruta> [--rate-card RUTA]
        [--generador RUTA] [--plantilla RUTA] [--catalogo RUTA] [--aclaracion F2=RUTA ...]
        [--previo <ZIP o carpeta>] [--sin-red] [--json SALIDA] [--render CARPETA]
        [--archivar <Cliente>] [--auditar] [--workspace RUTA] [--hoy AAAA-MM-DD]
        [--confirmo-stop <hash>] [--confirmo-ajuste <hash>] [--estricto]

No se fía de ningún sello del sandbox: recalcula cada regla leyendo los ficheros del paquete, la
transcripción local, la tarifa local, el catálogo local y el generador canónico del workspace, y
recompone en local lo que el sandbox compone para el cliente (LES-G-097): los textos, el PPTX
completo y el XLSX canónico.
Código de salida = veredicto (LES-G-091): 0 solo si ninguna comprobación FALLA; 1 si alguna
falla (se imprimen todas); 2 si la entrada no se puede leer; 3 si, con --estricto, queda algo
NO VERIFICADO. Sin --estricto, NO VERIFICADO es un aviso explícito, no un aprobado silencioso.

Las decisiones que mueven dinero no se aceptan solo desde estado.json, que pudo escribir el modelo:
un precio por encima de 100.000 EUR exige --confirmo-stop <hash vigente> y un ajuste comercial
distinto de 0, --confirmo-ajuste <hash vigente>, tecleados por el comercial en su línea de órdenes.
"""
from __future__ import annotations

import argparse
import dataclasses
import gc
import datetime as dt
import hashlib
import io
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
import zipfile
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Callable

RAIZ = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
# Las mismas variables que el núcleo (sandbox/preventa_run.py, Entorno.montado y raiz_proyectos): PREVENTA_PROYECTOS
# (por defecto ~/Proyectos, nunca una ruta fija de un puesto), PREVENTA_RATE_CARD, PREVENTA_GENERADOR y
# PREVENTA_PLANTILLA. Un valor con solo espacios cuenta como no fijado (LES-G-076). Precedencia: opción > variable >
# valor por defecto. Se resuelven al llamar a main (por_defecto), no al importar.
VARIABLES = {"rate_card": "PREVENTA_RATE_CARD", "generador": "PREVENTA_GENERADOR", "plantilla": "PREVENTA_PLANTILLA"}


def _variable(nombre: str) -> str:
    return (os.environ.get(nombre) or "").strip()


_RAIZ_WINDOWS = "C:/Users/usuario/Proyectos"   # misma resolución que desplegar.py


def raiz_proyectos() -> pathlib.Path:
    if _variable("PREVENTA_PROYECTOS"):
        return pathlib.Path(_variable("PREVENTA_PROYECTOS"))
    casa, windows = pathlib.Path.home() / "Proyectos", pathlib.Path(_RAIZ_WINDOWS)
    return casa if casa.is_dir() or not windows.is_dir() else windows   # la de Windows, solo como último recurso


def por_defecto() -> dict[str, pathlib.Path]:
    """POR_DEFECTO con las variables de entorno vigentes."""
    canon = raiz_proyectos() / "_templates" / "estimacion"
    base = {**POR_DEFECTO, "generador": canon / "generar_estimacion.py",
            "plantilla": canon / "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx"}
    return {k: pathlib.Path(_variable(VARIABLES[k])) if k in VARIABLES and _variable(VARIABLES[k]) else v
            for k, v in base.items()}


WORKSPACE = raiz_proyectos()   # valor al importar (--workspace se resuelve en main)
CANON = WORKSPACE / "_templates" / "estimacion"
POR_DEFECTO = {
    "rate_card": RAIZ / "salidas" / "rate-card.json",
    "generador": CANON / "generar_estimacion.py",
    "plantilla": CANON / "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx",
    "catalogo": RAIZ / "sandbox" / "datos" / "catalogo_componentes.json",
    # I1.7 (decisión 1 del comercial, 13-10-2026): instantánea de precios descargada al desplegar (copia byte a byte de
    # catalogo/precios_instantanea.json). Su huella va en manifiesto_paquete.montados y la puerta mira su edad.
    "precios": RAIZ / "sandbox" / "datos" / "precios_instantanea.json",
}
# Multinube (esquemas/MULTINUBE.md): fuera de Azure, el catálogo y la instantánea de confianza son los del pilar.
PILARES = ("azure", "gcp", "aws")
POR_DEFECTO_PILAR = {p: {"catalogo": RAIZ / "catalogo" / p / "catalogo_componentes.json",
                         "precios": RAIZ / "catalogo" / p / "precios_instantanea.json"} for p in ("gcp", "aws")}
ESQUEMAS = RAIZ / "esquemas"
APPI_ESPERADO = "appi-preventa-ejemplo"
# Opcional: solo lo trae el paquete de B. Procedencia propia del hosted agent (decisión del comercial, 10-10-2026): texto
# recibido de cada tarea A2A y su SHA-256, releído con GetTask. Va en el ZIP y en el manifiesto (CAMBIOS-I14-P1).
NOMBRE_PROCEDENCIA = "procedencia_a2a.json"
SCHEMA_PROCEDENCIA = "preventa-procedencia-a2a/1"
DIR_SANDBOX = RAIZ / "sandbox"  # de aquí sale `nucleo` (código de confianza del repositorio)

OK, FALLA, AVISO, NOV = "OK", "FALLA", "AVISO", "NO VERIFICADO"
CLAVES_CARGA = ("alta", "fuentes", "requisitos", "briefs", "respuestas_expertos", "consolidado",
                "verificacion", "anexo_consumo", "estimacion", "textos_cliente")
PALETA = {"F8485E", "3C3C3A", "FFFFFF", "F2F2F1", "BFBFBF"}
FUENTE = "Montserrat"
PERSONAS = {"responsable comercial": "COMERCIAL", "responsable de preventa": "REVISOR",
            "responsable de area": "APROBADOR"}
UMBRAL_STOP = Decimal("100000.00")
PM_MINIMO = Decimal("8")
PERFIL_PM, FASE_PM = "Project Manager", "Gestión de proyecto"
MAX_DESCOMPRIMIDO = 200 * 1024 * 1024
C2 = Decimal("0.01")
# Hechos fijos que puede citar una frase (lista cerrada: los que usa nucleo.textos_cliente; R1).
HECHOS_FIJOS = frozenset({"ALTA", "TARIFA", "ESTIMACION", "ANEXO",
                          "FIJO-EXCLUSIONES", "FIJO-SOPORTE", "FIJO-CONDICIONES"})
# Partes que genera nucleo.pptx_revision (C2). Cualquier otra (imágenes, gráficos, SmartArt, objetos
# incrustados, notas, comentarios, propiedades personalizadas, miniatura) hace FALLA.
PARTES_PPTX = re.compile(
    r"\[Content_Types\]\.xml|_rels/\.rels|docProps/(core|app)\.xml"
    r"|ppt/(presentation|presProps|viewProps|tableStyles)\.xml|ppt/_rels/presentation\.xml\.rels"
    r"|ppt/theme/theme\d+\.xml"
    r"|ppt/(slideMasters/slideMaster|slideLayouts/slideLayout|slides/slide)\d+\.xml"
    r"|ppt/(slideMasters|slideLayouts|slides)/_rels/(slideMaster|slideLayout|slide)\d+\.xml\.rels"
    r"|ppt/printerSettings/printerSettings\d+\.bin")
# Binarios admitidos por SHA-256: el de la plantilla por defecto de python-pptx.
BINARIOS_PPTX = {"d7768f87e07d29634782e448ece1cddd05a52b9499254222b1190bc8f6dc579e": "printerSettings de python-pptx"}
# Imágenes admitidas por SHA-256. pptx_revision no inserta ninguna: la lista blanca está vacía.
IMAGENES_PERMITIDAS: dict[str, str] = {}
URI_TABLA = "http://schemas.openxmlformats.org/drawingml/2006/table"
CABECERA_FIRMAS = ["Versión", "Fecha", "Elaborado por", "Revisado por", "Aprobado por"]
FIRMANTES = {"REVISOR": "Responsable de preventa", "APROBADOR": "Responsable de área"}
SUBCOMANDOS_XLSX = ("estimar", "paquete")  # pasos del núcleo que pueden generar el XLSX canónico
VENTANA_XLSX = (dt.timedelta(seconds=300), dt.timedelta(seconds=120))  # antes y después de su ts


# VA18-7 (I1.9): en APROBADA el PPTX ya no es un borrador: el entregable del cliente se llama «<codigo>-Propuesta.pptx»
# y su title es «<codigo> · Propuesta comercial». En los demás estados, «-Revision.pptx» y «· Propuesta para revisión».
# Un paquete APROBADA generado antes de FECHA_PROPUESTA_APROBADA (generado_ts del manifiesto) conserva el nombre y el
# title de antes, con nota; sin fecha legible se aplica la regla nueva (falla cerrado).
SUFIJO_PPTX_REVISION = "Revision.pptx"
SUFIJO_PPTX_APROBADA = "Propuesta.pptx"
TITULO_PPTX_REVISION = "{codigo} · Propuesta para revisión"
TITULO_PPTX_APROBADA = "{codigo} · Propuesta comercial"
FECHA_PROPUESTA_APROBADA = dt.date(2026, 10, 15)


def es_entregable_aprobado(estado_paquete: object, fecha: "dt.date | None") -> bool:
    """VA18-7: el paquete lleva el entregable final (Propuesta.pptx) si está APROBADA y no es anterior a la regla."""
    return estado_paquete == "APROBADA" and (fecha is None or fecha >= FECHA_PROPUESTA_APROBADA)


def sufijo_pptx(estado_paquete: object, fecha: "dt.date | None" = None) -> str:
    return SUFIJO_PPTX_APROBADA if es_entregable_aprobado(estado_paquete, fecha) else SUFIJO_PPTX_REVISION


def titulo_pptx(codigo: str, estado_paquete: object, fecha: "dt.date | None" = None) -> str:
    plantilla = TITULO_PPTX_APROBADA if es_entregable_aprobado(estado_paquete, fecha) else TITULO_PPTX_REVISION
    return plantilla.format(codigo=codigo)


def nombres_paquete(codigo: str, estado_paquete: object = None, fecha: "dt.date | None" = None) -> list[str]:
    """Los nueve ficheros del ZIP (§8), en el orden del contrato; el PPTX según el estado (VA18-7)."""
    return [f"{codigo}-Estimacion.xlsx", f"{codigo}-Anexo-Consumo.xlsx", f"{codigo}-Anexo-Consumo.json",
            f"{codigo}-{sufijo_pptx(estado_paquete, fecha)}", f"{codigo}-Nota-Revision.docx", "estado.json",
            "manifiesto_paquete.json", "mensaje_revisor.txt", "mensaje_aprobador.txt"]


class EntradaIlegible(Exception):
    """El paquete o un fichero de entrada no se puede leer (rc 2)."""


@dataclasses.dataclass
class Comprobacion:
    id: str
    titulo: str
    estado: str = OK
    detalles: list[str] = dataclasses.field(default_factory=list)

    def falla(self, msg: str) -> None:
        self.estado = FALLA
        self.detalles.append(msg)

    def aviso(self, msg: str) -> None:
        if self.estado == OK:
            self.estado = AVISO
        self.detalles.append(f"aviso: {msg}")

    def no_verificado(self, msg: str) -> None:
        if self.estado in (OK, AVISO):
            self.estado = NOV
        self.detalles.append(f"NO VERIFICADO: {msg}")

    def nota(self, msg: str) -> None:
        self.detalles.append(msg)


@dataclasses.dataclass
class Paquete:
    """Paquete extraído en una carpeta temporal de confianza (nunca se ejecuta nada de él)."""
    origen: pathlib.Path
    dir: pathlib.Path
    es_zip: bool
    zip_sha256: str | None
    ficheros: dict[str, pathlib.Path]
    extra: list[str]

    def bytes_de(self, nombre: str) -> bytes:
        return self.ficheros[nombre].read_bytes()

    def json_de(self, nombre: str) -> Any:
        try:
            return json.loads(self.bytes_de(nombre).decode("utf-8"), parse_constant=_sin_nan)
        except (UnicodeDecodeError, ValueError) as e:
            raise EntradaIlegible(f"{nombre}: JSON ilegible ({e})") from None


def _sin_nan(x: str) -> Any:
    raise ValueError(f"constante JSON no admitida: {x}")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_fichero(p: pathlib.Path) -> str:
    return sha256_bytes(pathlib.Path(p).read_bytes())


# ───────────────────────────── lectura del paquete ─────────────────────────────

def abrir_paquete(origen: pathlib.Path, tmp: pathlib.Path) -> Paquete:
    """Extrae el ZIP (plano, sin rutas, con tope de tamaño) o toma la carpeta tal cual."""
    origen = pathlib.Path(origen)
    if origen.is_dir():
        ficheros = {p.name: p for p in sorted(origen.iterdir()) if p.is_file()}
        return Paquete(origen, origen, False, None, ficheros, [])
    if not origen.is_file():
        raise EntradaIlegible(f"no existe el paquete {origen}")
    datos = origen.read_bytes()
    try:
        zf = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile as e:
        raise EntradaIlegible(f"{origen.name}: no es un ZIP válido ({e})") from None
    destino = tmp / "paquete"
    destino.mkdir(parents=True)
    ficheros: dict[str, pathlib.Path] = {}
    extra: list[str] = []
    total = 0
    with zf:
        for info in zf.infolist():
            nombre = info.filename
            if info.is_dir() or "/" in nombre or "\\" in nombre or nombre in ("", ".", "..") \
                    or ":" in nombre or nombre != nombre.strip():
                extra.append(f"entrada no plana o con ruta: {nombre!r}")
                continue
            if nombre in ficheros:
                extra.append(f"nombre repetido en el ZIP: {nombre}")
                continue
            total += info.file_size
            if total > MAX_DESCOMPRIMIDO:
                raise EntradaIlegible(f"{origen.name}: más de {MAX_DESCOMPRIMIDO} bytes descomprimidos")
            p = destino / nombre
            p.write_bytes(zf.read(info))
            ficheros[nombre] = p
    return Paquete(origen, destino, True, sha256_bytes(datos), ficheros, extra)


# ───────────────────────────── utilidades de texto ─────────────────────────────

def nfc(t: str) -> str:
    return unicodedata.normalize("NFC", t)


def sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def plano(t: str) -> str:
    """Minúsculas, sin tildes y con los espacios colapsados (comparaciones de nombres)."""
    return re.sub(r"\s+", " ", sin_tildes(nfc(t)).lower()).strip()


_MARC_MAYUS = re.compile(r"\b(TBD|TODO|XXX|PLACEHOLDER)\b")
_MARC_LIBRE = re.compile(r"\b(pendientes?|por definir|lorem)\b")
_MARC_ANGULO = re.compile(r"<[^<>\n]{1,60}>")


def marcadores_replica(texto: str) -> list[str]:
    """Réplica del barrido único de §0 (palabra completa; nunca por subcadena, LES-G-077)."""
    t = nfc(texto)
    halla = [f"marcador «{m.group(0)}»" for m in _MARC_MAYUS.finditer(t)]
    halla += [f"marcador «{m.group(0)}»" for m in _MARC_LIBRE.finditer(sin_tildes(t).lower())]
    halla += [f"marcador «{m.group(0)}»" for m in _MARC_ANGULO.finditer(t)]
    return halla


_PROHIBIDO_CLIENTE = [
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


def barrer_replica(texto: str, perfiles: list[str]) -> list[str]:
    """Réplica del barrido LES-G-053 de §9.3 (horas, perfiles, tarifas, ids, correos, marcadores)."""
    halla: list[str] = []
    for rx, motivo in _PROHIBIDO_CLIENTE:
        for m in rx.finditer(texto):
            halla.append(f"{motivo}: «{m.group(0)}»")
    pl = plano(texto)
    for p in perfiles:
        if re.search(r"(?<!\w)" + re.escape(plano(p)) + r"(?!\w)", pl):
            halla.append(f"nombre de perfil de la tarifa: «{p}»")
    return halla + marcadores_replica(texto)


# ──────────────────── puente con sandbox/nucleo (código de confianza) ────────────────────

def _nucleo(modulo: str) -> Any | None:
    """Importa `nucleo.<modulo>` del repositorio (nunca del ZIP). None solo si el fichero no existe.

    Si el fichero existe pero no se puede importar (una dependencia rota), el error se propaga y la
    comprobación que lo usa FALLA: un módulo roto nunca se toma por ausente.
    """
    import importlib
    if not (DIR_SANDBOX / "nucleo" / f"{modulo}.py").is_file():
        return None
    if str(DIR_SANDBOX) not in sys.path:
        sys.path.insert(0, str(DIR_SANDBOX))
    return importlib.import_module(f"nucleo.{modulo}")


def marcadores(texto: str) -> list[str]:
    """Barrido de §0: unión de la réplica local y de `textos_cliente.marcadores` si existe."""
    tc = _nucleo("textos_cliente")
    extra = list(tc.marcadores(texto)) if tc and hasattr(tc, "marcadores") else []
    return marcadores_replica(texto) + [f"(nucleo) {h}" for h in extra]


def barrer(texto: str, perfiles: list[str], servicios: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Barrido de §9.3: unión de la réplica local y de `textos_cliente.barrer` si existe.

    Con `servicios`, las horas de servicio de un servicio cloud («730 horas mensuales» junto a
    «Azure AI Search») se enmascaran antes de barrer (H-V12); las horas de esfuerzo, nunca.
    """
    texto = enmascarar_horas_servicio(texto, servicios)
    tc = _nucleo("textos_cliente")
    extra = list(tc.barrer(texto, perfiles)) if tc and hasattr(tc, "barrer") else []
    return barrer_replica(texto, perfiles) + [f"(nucleo) {h}" for h in extra]


# «730 horas mensuales», «24 horas al día», «720 h/mes»: cantidad de horas por periodo de calendario.
_HORAS_SERVICIO = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:horas?|h)\s*"
    r"(?:(mensuales|al mes|por mes|/\s*mes|de funcionamiento al mes)|(diarias|al d[ií]a|por d[ií]a|/\s*d[ií]a))(?!\w)",
    re.I)
# Vocabulario de esfuerzo: si aparece en el mismo párrafo, las horas son de trabajo y no se eximen.
_ESFUERZO = re.compile(r"\b(dedicaci[oó]n|esfuerzo|consultor\w*|equipo|trabajo|personas?|perfil\w*|jornadas?|"
                       r"desarrollo|implantaci[oó]n|servicios profesionales|gesti[oó]n|t[eé]cnicos?|ingenier\w*|"
                       r"horas[- ]hombre|soporte)\b", re.I)


def enmascarar_horas_servicio(texto: str, servicios: list[str] | tuple[str, ...]) -> str:
    """Quita del texto, párrafo a párrafo, las horas de servicio de un servicio del catálogo (H-V12).

    Solo se eximen si el párrafo nombra un servicio de `servicios`, no tiene vocabulario de esfuerzo
    y la cifra cabe en el periodo (≤ 744 al mes, ≤ 24 al día). Todo lo demás se barre igual.
    """
    nombres = [plano(s) for s in servicios if s and len(plano(s)) >= 4]
    if not nombres:
        return texto
    salida = []
    for parrafo in texto.split("\n"):
        pl = plano(parrafo)
        if not any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", pl) for n in nombres) or _ESFUERZO.search(parrafo):
            salida.append(parrafo)
            continue

        def tapar(m: re.Match) -> str:
            cifra = Decimal(m.group(1).replace(",", "."))
            tope = Decimal(744) if m.group(2) else Decimal(24)
            return " " * len(m.group(0)) if cifra <= tope else m.group(0)
        salida.append(_HORAS_SERVICIO.sub(tapar, parrafo))
    return "\n".join(salida)


def json_canonico(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def hash_json(obj: Any) -> str:
    return sha256_bytes(json_canonico(obj))


def hash_contenido(estado: dict) -> str:
    """§5.1, recalculado aquí; si existe `nucleo.hashes`, debe dar exactamente lo mismo."""
    carga = estado.get("carga")
    if not isinstance(carga, dict) or set(carga) != set(CLAVES_CARGA):
        raise ValueError(f"carga sin exactamente las claves {CLAVES_CARGA}: "
                         f"{sorted(carga) if isinstance(carga, dict) else type(carga).__name__}")
    propio = hash_json(carga)
    nh = _nucleo("hashes")
    if nh and hasattr(nh, "hash_contenido"):
        otro = nh.hash_contenido(estado)
        if otro != propio:
            raise ValueError(f"nucleo.hashes da {otro} y la réplica local {propio}")
    return propio


_VTT_TIEMPO = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?[.,]\d{3}\s*-->.*$", re.M)


def normalizar_para_cita(texto: str) -> str:
    """§3.3: NFC, minúsculas, sin tildes, sin marcas VTT y con los espacios colapsados."""
    t = nfc(texto).replace("\r\n", "\n").replace("\r", "\n")
    lineas, en_nota = [], False
    for ln in t.split("\n"):
        s = ln.strip()
        if en_nota:
            en_nota = bool(s)
            continue
        if s.startswith("WEBVTT") or _VTT_TIEMPO.match(ln):
            continue
        if s == "NOTE" or s.startswith("NOTE ") or s.startswith("NOTE\t"):
            en_nota = True
            continue
        lineas.append(ln)
    t = "\n".join(lineas)
    t = re.sub(r"</?v(\s[^>]*)?>", " ", t)
    t = sin_tildes(t).lower()
    return re.sub(r"\s+", " ", t).strip()


def quitar_ids_cue(texto: str) -> str:
    """Quita las líneas identificador de cue (las que preceden a una línea de tiempo)."""
    ls = nfc(texto).replace("\r\n", "\n").split("\n")
    fuera = {i - 1 for i, ln in enumerate(ls) if i and _VTT_TIEMPO.match(ln) and ls[i - 1].strip()}
    return "\n".join(ln for i, ln in enumerate(ls) if i not in fuera)


def texto_cita_normalizado(transcripcion: str) -> str:
    return normalizar_para_cita(quitar_ids_cue(transcripcion))


def cita_valida(cita: str, normalizado_fuente: str) -> tuple[bool, str]:
    c = normalizar_para_cita(cita or "")
    if len(c) < 15 or len(c.split()) < 3:
        return False, "cita de menos de 15 caracteres o 3 palabras"
    if c not in normalizado_fuente:
        return False, "la cita no aparece en la fuente"
    return True, ""


# ───────────────────────────── importes ─────────────────────────────

def dec(x: Any) -> Decimal:
    if isinstance(x, bool) or x is None:
        raise ValueError(f"importe no válido: {x!r}")
    try:
        d = Decimal(str(x))
    except InvalidOperation:
        raise ValueError(f"importe no válido: {x!r}") from None
    if not d.is_finite():
        raise ValueError(f"importe no finito: {x!r}")
    return d


def q2(d: Decimal) -> Decimal:
    return d.quantize(C2, rounding=ROUND_HALF_UP)


def round0(d: Decimal) -> Decimal:
    return d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


_IMPORTE = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+,\d{2}|\d{1,3}(?:,\d{3})+\.\d{2}|\d+[.,]\d{2})(?![\d])")


def importes_en(texto: str) -> set[Decimal]:
    """Importes con dos decimales escritos en formato español (17.852,50) o con punto (17852.50)."""
    salida: set[Decimal] = set()
    for m in _IMPORTE.finditer(texto.replace("\u00a0", " ").replace("\u202f", " ")):
        s = m.group(1)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", s) or re.fullmatch(r"\d+,\d{2}", s):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
        salida.add(Decimal(s))
    return salida


_PORCENTAJE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
_NUM = r"(\d{1,3}(?:[.,\u00a0\u202f ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_MONEDA_DESPUES = re.compile(r"(?<![\d.,])" + _NUM + r"\s*(?:€|EUR\b|euros?\b)", re.I)
_MONEDA_ANTES = re.compile(r"(?:€|\bEUR)\s*" + _NUM + r"(?![\d])", re.I)
_CIFRA = re.compile(r"(?<![\w.,])(\d[\d.,]*\d|\d)(?![\w])")


def lecturas_numero(s: str) -> set[Decimal]:
    """Lectura de una cifra en formato español (miles con punto, decimales con coma), o vacío.

    Solo vale la lectura española, la de formato_eur: «19.990» es 19990 y nunca 19,99, y «22548.75» o
    «22,548.75» no tienen lectura y hacen FALLA. Una cifra ambigua no casa por la lectura que convenga.
    """
    s = re.sub(r"[\s\u00a0\u202f]", "", s)
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?", s):
        return set()
    return {Decimal(s.replace(".", "").replace(",", "."))}


def cifras_monetarias(texto: str) -> list[tuple[str, set[Decimal]]]:
    """(literal, lecturas) de cada importe: con dos decimales o pegado a €/EUR/euros (H-V2) y, desde I1.9, cada cifra
    de una serie que acaba o empieza en la moneda (VA18-1)."""
    t = _PORCENTAJE.sub(" ", texto.replace("\u00a0", " ").replace("\u202f", " "))
    vistos: list[tuple[str, set[Decimal]]] = []
    posiciones = set()
    for rx in (_MONEDA_DESPUES, _MONEDA_ANTES, _IMPORTE):
        for m in rx.finditer(t):
            vistos.append((m.group(1).strip(), lecturas_numero(m.group(1))))
            posiciones.add(m.start(1))
    # VA18-1 (I1.9): también cada cifra de una serie junto a la moneda que no haya visto ya otra regla en esa posición
    return vistos + [(lit, lect) for pos, lit, lect in _cifras_con_moneda_pos(t) if pos not in posiciones]


# VA18-1 (I1.9, LES-G-097.1): la moneda puede ir junto a la ÚLTIMA cifra de una serie («entre 25.000 y 60.000 euros»,
# «de 25.000 a 60.000 €», «25.000-60.000 EUR») o detrás de un multiplicador («25 mil euros», «60k€»). _MONEDA_DESPUES
# solo veía la cifra pegada a la moneda (60.000), nunca la primera (25.000). Los separadores no cruzan líneas: una
# celda de tabla es un párrafo, y «Hito 2» no se une con el importe de la celda siguiente.
_ESP = r"[ \t\u00a0\u202f]*"
_SEP_SERIE = _ESP + r"(?:,|y|e|o|u|a|al|hasta|-|–|—|/)" + _ESP
_MULTIPLICADOR = r"(?P<mult>" + _ESP + r"(?:mil(?:[ \t]+millones)?|millones|mill[oó]n|k|mm?)(?:[ \t]+de)?)?"
_SERIE_DESPUES = re.compile(r"(?<![\d.,\w])" + _NUM + r"(?:" + _SEP_SERIE + _NUM + r")*" + _MULTIPLICADOR + _ESP
                            + r"(?:€|EUR\b|euros?\b)", re.I)
_SERIE_ANTES = re.compile(r"(?:€|\bEUR\b|\beuros?\b)" + _ESP + _NUM + r"(?:" + _SEP_SERIE + _NUM + r")*(?![\d])", re.I)
_UNA_CIFRA = re.compile(_NUM)


def cifras_con_moneda(texto: str) -> list[tuple[str, set[Decimal]]]:
    """VA18-1: (literal, lecturas) de CADA cifra de una serie junto a €/EUR/euros, antes o después. Con multiplicador
    («25 mil euros») no hay lectura: nunca casa con un importe permitido y falla cerrado."""
    t = _PORCENTAJE.sub(" ", texto.replace("\u00a0", " ").replace("\u202f", " "))
    return [(lit, lect) for _, lit, lect in _cifras_con_moneda_pos(t)]


def _cifras_con_moneda_pos(t: str) -> list[tuple[int, str, set[Decimal]]]:
    """(posición en `t`, literal, lecturas) de cada cifra de serie, sin repetir posición entre las dos reglas."""
    salida: dict[int, tuple[str, set[Decimal]]] = {}
    for rx in (_SERIE_DESPUES, _SERIE_ANTES):
        for m in rx.finditer(t):
            mult = (m.groupdict().get("mult") or "").strip()
            fin = m.start("mult") if mult else m.end()
            for n in _UNA_CIFRA.finditer(t, m.start(), fin):
                salida.setdefault(n.start(1), (n.group(1).strip() + (f" {mult}" if mult else ""),
                                               set() if mult else lecturas_numero(n.group(1))))
    return [(pos, lit, lect) for pos, (lit, lect) in sorted(salida.items())]


def cifras_sueltas(texto: str) -> list[tuple[str, set[Decimal]]]:
    """(literal, lecturas) de toda cifra de 100 o más, o sin lectura española, con o sin moneda."""
    t = _PORCENTAJE.sub(" ", texto.replace("\u00a0", " ").replace("\u202f", " "))
    salida = []
    for m in _CIFRA.finditer(t):
        lect = lecturas_numero(m.group(1))
        if not lect or max(lect) >= 100:
            salida.append((m.group(1), lect))
    return salida


# ───────────────────────────── lectura de OOXML ─────────────────────────────

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _xml(zf: zipfile.ZipFile, parte: str):
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(zf.read(parte), parser)


def _texto_parrafos(raiz, prefijo: str) -> list[str]:
    """Texto por párrafo (a:p o w:p), concatenando sus runs."""
    etiqueta_p, etiqueta_t = (f"{{{NS[prefijo]}}}p", f"{{{NS[prefijo]}}}t")
    return ["".join(t.text or "" for t in p.iter(etiqueta_t)) for p in raiz.iter(etiqueta_p)]


@dataclasses.dataclass
class Diapositiva:
    numero: int
    parte: str
    raiz: Any
    textos: list[str]
    tablas: list[list[list[str]]]


@dataclasses.dataclass
class Pptx:
    diapositivas: list[Diapositiva]
    partes: dict[str, bytes]
    notas: list[str]
    comentarios: list[str]
    props: dict[str, str]
    props_texto: list[str]


def leer_pptx(ruta: pathlib.Path) -> Pptx:
    from lxml import etree  # noqa: F401  (comprobación temprana de la dependencia)
    with zipfile.ZipFile(ruta) as zf:
        partes = {n: zf.read(n) for n in zf.namelist()}
        pres = _xml(zf, "ppt/presentation.xml")
        rels = _xml(zf, "ppt/_rels/presentation.xml.rels")
        destino = {r.get("Id"): r.get("Target") for r in rels.iter(f"{{{NS['rel']}}}Relationship")}
        orden = [destino[s.get(f"{{{NS['r']}}}id")] for s in pres.iter(f"{{{NS['p']}}}sldId")]
        diapos = []
        for n, objetivo in enumerate(orden, 1):
            parte = "ppt/" + objetivo.lstrip("/").removeprefix("ppt/")
            raiz = _xml(zf, parte)
            tablas = []
            for tbl in raiz.iter(f"{{{NS['a']}}}tbl"):
                filas = [["\n".join(_texto_parrafos(tc, "a")) for tc in tr.iter(f"{{{NS['a']}}}tc")]
                         for tr in tbl.iter(f"{{{NS['a']}}}tr")]
                tablas.append(filas)
            diapos.append(Diapositiva(n, parte, raiz, _texto_parrafos(raiz, "a"), tablas))
        notas = [t for n in partes if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", n)
                 for t in _texto_parrafos(_xml(zf, n), "a") if t.strip()]
        comentarios = [n for n in partes if re.search(r"(^|/)(comments/|comment\d+\.xml|modernComment)", n)]
        props, props_texto = _props(zf, partes)
    return Pptx(diapos, partes, notas, comentarios, props, props_texto)


def _props(zf: zipfile.ZipFile, partes: dict[str, bytes]) -> tuple[dict[str, str], list[str]]:
    """Propiedades de docProps: core como diccionario y todo el texto de app/custom."""
    props: dict[str, str] = {}
    texto: list[str] = []
    if "docProps/core.xml" in partes:
        core = _xml(zf, "docProps/core.xml")
        for el in core:
            nombre = el.tag.split("}")[-1]
            props[nombre] = el.text or ""
    for parte in ("docProps/app.xml", "docProps/custom.xml"):
        if parte in partes:
            texto += [t.strip() for t in _xml(zf, parte).itertext() if t and t.strip()]
    return props, texto


def leer_docx(ruta: pathlib.Path) -> tuple[list[str], dict[str, str], dict[str, bytes]]:
    """Párrafos de documento, cabeceras y pies; propiedades core; partes en bruto."""
    with zipfile.ZipFile(ruta) as zf:
        partes = {n: zf.read(n) for n in zf.namelist()}
        textos: list[str] = []
        for n in sorted(partes):
            if re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml", n):
                textos += _texto_parrafos(_xml(zf, n), "w")
        props, extra = _props(zf, partes)
    return textos + extra, props, partes


# ───────────────────────── XLSX canónico: lectura y recálculo ─────────────────────────

HOJA_EST, HOJA_RES = "Estimación Esfuerzo", "Resumen Económico"


@dataclasses.dataclass
class XlsxCanonico:
    tareas: list[dict]          # fila, fase, tarea, perfil, E, G, D (Decimal), formulas
    tarifas: dict[str, Decimal]
    ajuste: Decimal | None
    ajuste_etiqueta: str | None
    hitos: list[dict]           # nombre, porcentaje (Decimal, en %), importe
    subtotal: Decimal
    precio: Decimal
    horas_total: Decimal
    pm_h: Decimal
    textos: list[str]
    errores: list[str]


def leer_xlsx_canonico(ruta: pathlib.Path) -> XlsxCanonico:
    """Lee el XLSX canónico (fórmulas, sin valores en caché) y recalcula en Decimal como Excel."""
    import openpyxl
    wb = openpyxl.load_workbook(ruta)
    errores: list[str] = []
    textos = [c.value for ws in wb for fila in ws.iter_rows() for c in fila if isinstance(c.value, str)]
    ws = wb[HOJA_EST]
    tareas, r = [], 2
    while ws.cell(r, 1).value not in (None, "TOTALES") and r < 2000:
        e, g = ws.cell(r, 5).value, ws.cell(r, 7).value
        try:
            ed, gd = dec(e), dec(g)
        except ValueError as ex:
            errores.append(f"{HOJA_EST}!E/G{r}: {ex}")
            ed = gd = Decimal(0)
        tareas.append({"fila": r, "fase": ws.cell(r, 1).value, "tarea": ws.cell(r, 2).value,
                       "perfil": ws.cell(r, 3).value, "E": ed, "G": gd,
                       "D": ed + round0(ed * Decimal("0.2")) + gd,
                       "formula_D": ws.cell(r, 4).value, "formula_F": ws.cell(r, 6).value})
        r += 1
    wr = wb[HOJA_RES]
    tarifas: dict[str, Decimal] = {}
    ajuste = etiqueta = None
    hitos: list[dict] = []
    fila, en_hitos, precio_fila = 7, False, None
    while fila < 400:
        a = wr.cell(fila, 1).value
        if isinstance(a, str):
            if a == "SUBTOTAL SERVICIOS":
                pass
            elif a.startswith("AJUSTE COMERCIAL"):
                etiqueta = a
                try:
                    ajuste = dec(wr.cell(fila, 6).value)
                except ValueError as ex:
                    errores.append(f"{HOJA_RES}!F{fila}: ajuste no literal ({ex})")
            elif a.startswith("PRECIO CERRADO"):
                precio_fila = fila
            elif a == "Hito":
                en_hitos = True
            elif a == "TOTAL HITOS":
                break
            elif en_hitos:
                try:
                    pct = q2(dec(wr.cell(fila, 2).value) * 100)
                except ValueError as ex:
                    errores.append(f"{HOJA_RES}!B{fila}: {ex}")
                    pct = Decimal(0)
                hitos.append({"nombre": a, "porcentaje": pct})
            elif precio_fila is None and fila >= 7 and wr.cell(fila, 3).value is not None:
                try:
                    tarifas[a] = dec(wr.cell(fila, 3).value)
                except ValueError as ex:
                    errores.append(f"{HOJA_RES}!C{fila}: {ex}")
        fila += 1
    horas: dict[str, Decimal] = {}
    for t in tareas:
        horas[t["perfil"]] = horas.get(t["perfil"], Decimal(0)) + t["D"]
    for p in horas:
        if p not in tarifas:
            errores.append(f"perfil «{p}» del esfuerzo sin fila de tarifa en {HOJA_RES}")
    subtotal = q2(sum((tarifas.get(p, Decimal(0)) * h for p, h in horas.items()), Decimal(0)))
    precio = q2(subtotal + (ajuste or Decimal(0)))
    acumulado = Decimal(0)
    for k, h in enumerate(hitos):
        if k < len(hitos) - 1 or k == 0:
            h["importe"] = q2(h["porcentaje"] / 100 * precio)
        else:
            h["importe"] = precio - acumulado
        acumulado += h["importe"]
    return XlsxCanonico(tareas, tarifas, ajuste, etiqueta, hitos, subtotal, precio,
                        sum((t["D"] for t in tareas), Decimal(0)),
                        sum((t["D"] for t in tareas if t["perfil"] == PERFIL_PM), Decimal(0)),
                        textos, errores)


# ───────────────────────────── contexto de la verificación ─────────────────────────────

def pilar_ctx(ctx: Any) -> str:
    """Multinube: el de carga.alta.pilar del estado («azure» sin la clave; también en los contextos mínimos de las
    pruebas, sin estado); el del manifiesto lo contrasta _pilar_paquete."""
    carga = getattr(ctx, "carga", None)
    if not isinstance(carga, dict):
        carga = (getattr(ctx, "estado", None) or {}).get("carga") or {}
    alta = carga.get("alta") if isinstance(carga.get("alta"), dict) else {}
    return alta.get("pilar", "azure")


@dataclasses.dataclass
class Contexto:
    paquete: Paquete
    transcripcion: pathlib.Path
    aclaraciones: dict[str, pathlib.Path]
    rate_card: pathlib.Path
    generador: pathlib.Path
    plantilla: pathlib.Path
    catalogo: pathlib.Path
    previo: pathlib.Path | None
    sin_red: bool
    hoy: dt.date
    tmp: pathlib.Path
    http_get: Callable[[str], tuple[int, str, str]] | None = None
    conexiones_appi: Callable[[], list[dict]] | None = None
    consultar_kql: Callable[[str], list[dict]] | None = None
    confirmo_stop: str | None = None      # hash tecleado por el comercial en la línea de órdenes (R2)
    confirmo_ajuste: str | None = None
    estado: dict = dataclasses.field(default_factory=dict)
    manifiesto: dict = dataclasses.field(default_factory=dict)
    precios: pathlib.Path | None = None   # I1.7: instantánea local de confianza (POR_DEFECTO si None)
    notas: pathlib.Path | None = None     # notas del comercial (NOTAS_COMERCIAL.md): copia local, si el alta las trae
    explicitas: frozenset = frozenset()   # multinube: opciones de ruta fijadas en la línea de órdenes (no se sustituyen)
    tarifa: dict = dataclasses.field(default_factory=dict)
    catalogo_obj: dict = dataclasses.field(default_factory=dict)
    codigo: str = ""
    _cache: dict = dataclasses.field(default_factory=dict)

    @property
    def carga(self) -> dict:
        return self.estado.get("carga") or {}

    @property
    def perfiles(self) -> list[str]:
        return [p["nombre"] for p in self.tarifa.get("perfiles", [])]

    @property
    def pilar(self) -> str:
        return pilar_ctx(self)

    @property
    def respuesta(self) -> dict:
        return ((self.carga.get("respuestas_expertos") or {}).get(self.pilar) or {}).get("respuesta") or {}

    def fichero(self, sufijo: str) -> pathlib.Path:
        return self.paquete.ficheros[f"{self.codigo}-{sufijo}"]

    def fecha_paquete(self) -> "dt.date | None":
        return fecha_del_paquete(self.manifiesto or {})

    def sufijo_pptx(self) -> str:
        """VA18-7: «Propuesta.pptx» en APROBADA (desde FECHA_PROPUESTA_APROBADA); si no, «Revision.pptx»."""
        return sufijo_pptx(self.estado.get("estado"), self.fecha_paquete())

    def ruta_pptx(self) -> pathlib.Path:
        """El PPTX que corresponde al estado; si falta y está el del otro estado, ese (`estructura` ya da FALLA por el
        nombre, VA18-7): así las demás comprobaciones siguen diciendo sus motivos en vez de un KeyError."""
        nombre = f"{self.codigo}-{self.sufijo_pptx()}"
        if nombre not in self.paquete.ficheros:
            for sufijo in (SUFIJO_PPTX_APROBADA, SUFIJO_PPTX_REVISION):
                if f"{self.codigo}-{sufijo}" in self.paquete.ficheros:
                    return self.paquete.ficheros[f"{self.codigo}-{sufijo}"]
        return self.paquete.ficheros[nombre]

    def pptx(self) -> Pptx:
        if "pptx" not in self._cache:
            self._cache["pptx"] = leer_pptx(self.ruta_pptx())
        return self._cache["pptx"]

    def xlsx(self) -> XlsxCanonico:
        if "xlsx" not in self._cache:
            self._cache["xlsx"] = leer_xlsx_canonico(self.fichero("Estimacion.xlsx"))
        return self._cache["xlsx"]

    def docx(self) -> tuple[list[str], dict[str, str], dict[str, bytes]]:
        if "docx" not in self._cache:
            self._cache["docx"] = leer_docx(self.fichero("Nota-Revision.docx"))
        return self._cache["docx"]

    def hash_vigente(self) -> str:
        if "hash" not in self._cache:
            self._cache["hash"] = hash_contenido(self.estado)
        return self._cache["hash"]


def _esquema(nombre: str) -> dict:
    return json.loads((ESQUEMAS / f"{nombre}.json").read_text(encoding="utf-8"))


def validar_esquema(instancia: Any, nombre: str) -> list[str]:
    """Valida con la referencia ejecutable de P0 (`esquemas/comprobar_esquemas.validar`)."""
    from esquemas.comprobar_esquemas import validar
    e = _esquema(nombre)
    return validar(instancia, e, e)


def cargar_tarifa(ruta: pathlib.Path) -> dict:
    datos = json.loads(pathlib.Path(ruta).read_text(encoding="utf-8"))
    tarifa = datos.get("tarifa", datos)
    if not tarifa.get("perfiles"):
        raise EntradaIlegible(f"{ruta}: tarifa sin perfiles")
    return tarifa


def preparar(ctx: Contexto) -> None:
    """Carga lo mínimo para empezar; cualquier fallo aquí es rc 2 (entrada ilegible)."""
    if "manifiesto_paquete.json" not in ctx.paquete.ficheros or "estado.json" not in ctx.paquete.ficheros:
        raise EntradaIlegible("el paquete no trae manifiesto_paquete.json y estado.json")
    ctx.manifiesto = ctx.paquete.json_de("manifiesto_paquete.json")
    ctx.estado = ctx.paquete.json_de("estado.json")
    if not isinstance(ctx.manifiesto, dict) or not isinstance(ctx.estado, dict):
        raise EntradaIlegible("manifiesto o estado no son objetos JSON")
    ctx.codigo = str(ctx.manifiesto.get("codigo") or "")
    if not re.fullmatch(r"OF-[A-Z0-9]{2,20}-\d{3}-[A-Z]", ctx.codigo):
        raise EntradaIlegible(f"código de oferta no válido en el manifiesto: {ctx.codigo!r}")
    for nombre, ruta in (("transcripción", ctx.transcripcion), ("notas del comercial", ctx.notas),
                         ("tarifa", ctx.rate_card), ("generador", ctx.generador), ("plantilla", ctx.plantilla)):
        if ruta is None and nombre in ("transcripción", "notas del comercial"):
            continue   # c_suficiencia exige la copia de cada fuente que registre el alta
        if not pathlib.Path(ruta).is_file():
            como = {"tarifa": "--rate-card o PREVENTA_RATE_CARD",
                    "generador": "--generador, PREVENTA_GENERADOR o PREVENTA_PROYECTOS",
                    "plantilla": "--plantilla, PREVENTA_PLANTILLA o PREVENTA_PROYECTOS"}.get(nombre)
            raise EntradaIlegible(f"no existe la {nombre}: {ruta}" + (f" (fíjala con {como})" if como else ""))
    ctx.tarifa = cargar_tarifa(ctx.rate_card)
    if ctx.pilar in POR_DEFECTO_PILAR:   # multinube: sin --catalogo/--precios explícitos, los de confianza del pilar
        if "catalogo" not in ctx.explicitas and pathlib.Path(ctx.catalogo) == POR_DEFECTO["catalogo"]:
            ctx.catalogo = POR_DEFECTO_PILAR[ctx.pilar]["catalogo"]
        if "precios" not in ctx.explicitas and (ctx.precios is None or pathlib.Path(ctx.precios) == POR_DEFECTO["precios"]):
            ctx.precios = POR_DEFECTO_PILAR[ctx.pilar]["precios"]
    if pathlib.Path(ctx.catalogo).is_file():
        ctx.catalogo_obj = json.loads(pathlib.Path(ctx.catalogo).read_text(encoding="utf-8"))


def ejecutar(ctx: Contexto, comprobaciones: list[Callable[[Contexto], Comprobacion]]) -> list[Comprobacion]:
    """Ejecuta todas; un error inesperado en una es FALLA de esa, nunca un aprobado."""
    resultados = []
    for fn in comprobaciones:
        try:
            resultados.append(fn(ctx))
        except Exception as e:  # noqa: BLE001 - fail loudly por comprobación, sin parar las demás
            c = Comprobacion(fn.__name__.removeprefix("c_"), (fn.__doc__ or fn.__name__).strip().split("\n")[0])
            c.falla(f"error inesperado: {type(e).__name__}: {e}")
            resultados.append(c)
    return resultados


# ───────────────────────────── comprobaciones ─────────────────────────────

def c_estructura(ctx: Contexto) -> Comprobacion:
    """P13 · Estructura: los nueve ficheros del contrato, más procedencia_a2a.json si el paquete es de B (con su SHA-256 en el manifiesto), ninguno de más y manifiesto conforme."""
    c = Comprobacion("estructura", c_estructura.__doc__.split("·")[1].strip())
    esperados = nombres_paquete(ctx.codigo, ctx.estado.get("estado"), ctx.fecha_paquete())
    presentes = set(ctx.paquete.ficheros)
    if ctx.estado.get("estado") == "APROBADA" and not es_entregable_aprobado("APROBADA", ctx.fecha_paquete()):
        c.nota(f"paquete APROBADA anterior a {FECHA_PROPUESTA_APROBADA}: se admite «-{SUFIJO_PPTX_REVISION}» (VA18-7)")
    for n in esperados:
        if n not in presentes:
            c.falla(f"falta en el paquete: {n}")
    sobran = sorted(presentes - set(esperados) - {NOMBRE_PROCEDENCIA})
    for n in sobran:
        (c.falla if ctx.paquete.es_zip else c.aviso)(f"fichero no previsto en el paquete: {n}")
    for e in ctx.paquete.extra:
        c.falla(e)
    # La procedencia de B (opcional) se valida aparte: así la puerta vale con el esquema del manifiesto de antes y con
    # el que la admite. Si está en el paquete, tiene que estar en el manifiesto con su SHA-256, y al revés.
    ficheros_man = ctx.manifiesto.get("ficheros", [])
    proc = [f for f in ficheros_man if isinstance(f, dict) and f.get("nombre") == NOMBRE_PROCEDENCIA]         if isinstance(ficheros_man, list) else []
    sin_proc = {**ctx.manifiesto, "ficheros": [f for f in ficheros_man if not any(f is x for x in proc)]}         if isinstance(ficheros_man, list) else ctx.manifiesto
    for e in validar_esquema(sin_proc, "manifiesto_paquete"):
        c.falla(f"manifiesto: {e}")
    for f in proc:
        if set(f) != {"nombre", "sha256", "bytes"} or not re.fullmatch(r"[0-9a-f]{64}", str(f.get("sha256")))                 or not isinstance(f.get("bytes"), int) or isinstance(f.get("bytes"), bool) or f["bytes"] < 1:
            c.falla(f"manifiesto: la entrada de {NOMBRE_PROCEDENCIA} no es {{nombre, sha256, bytes}} válida")
    if bool(proc) != (NOMBRE_PROCEDENCIA in presentes):
        c.falla(f"{NOMBRE_PROCEDENCIA}: " + ("el manifiesto lo lista y no está en el paquete" if proc else
                                             "está en el paquete y el manifiesto no lo lista (sin SHA-256 no vale)"))
    nombres = [f.get("nombre") for f in ficheros_man if isinstance(f, dict)] if isinstance(ficheros_man, list) else []
    if len(nombres) != len(set(nombres)):
        c.falla("el manifiesto repite nombres de fichero")
    if sorted(n for n in nombres if n != NOMBRE_PROCEDENCIA) != sorted(n for n in esperados if n != "manifiesto_paquete.json"):
        c.falla(f"el manifiesto no lista exactamente los otros ocho ficheros: {sorted(nombres)}")
    for suf in ("Estimacion.xlsx", "Anexo-Consumo.xlsx", ctx.sufijo_pptx(), "Nota-Revision.docx"):
        ruta = ctx.paquete.ficheros.get(f"{ctx.codigo}-{suf}")
        if ruta is not None:
            for e in partes_ooxml_ambiguas(ruta):
                c.falla(f"{ruta.name}: {e}")
    return c


def partes_ooxml_ambiguas(ruta: pathlib.Path) -> list[str]:
    """Miembros repetidos o con ruta rara dentro de un OOXML (revisión independiente, 2.ª pasada).

    Al leer por nombre, un miembro repetido colapsa en uno solo: la puerta compararía uno y el visor
    podría mostrar el otro. Un paquete ambiguo no se verifica: FALLA.
    """
    try:
        with zipfile.ZipFile(ruta) as zf:
            nombres = zf.namelist()
    except zipfile.BadZipFile as e:
        return [f"no es un ZIP válido ({e})"]
    vistos, malos = set(), []
    for nombre in nombres:
        clave = nombre.replace("\\", "/").lower()
        if clave in vistos:
            malos.append(f"parte repetida dentro del OOXML: {nombre}")
        vistos.add(clave)
        if nombre.startswith("/") or ".." in nombre.split("/") or "\\" in nombre:
            malos.append(f"parte con ruta no válida dentro del OOXML: {nombre!r}")
    return malos


def c_integridad(ctx: Contexto) -> Comprobacion:
    """P13 · Integridad: SHA-256 contra el manifiesto y hash_contenido recalculado en todas partes."""
    c = Comprobacion("integridad", c_integridad.__doc__.split("·")[1].strip())
    for f in ctx.manifiesto.get("ficheros", []):
        nombre = f.get("nombre")
        p = ctx.paquete.ficheros.get(nombre)
        if p is None:
            continue
        datos = p.read_bytes()
        if sha256_bytes(datos) != f.get("sha256"):
            c.falla(f"{nombre}: SHA-256 {sha256_bytes(datos)} distinto del manifiesto {f.get('sha256')}")
        if len(datos) != f.get("bytes"):
            c.falla(f"{nombre}: {len(datos)} bytes, el manifiesto dice {f.get('bytes')}")
    est_sha = sha256_fichero(ctx.paquete.ficheros["estado.json"])
    if est_sha != ctx.manifiesto.get("estado_json_sha256"):
        c.falla(f"estado.json: SHA-256 {est_sha} distinto de estado_json_sha256 del manifiesto")
    try:
        vigente = ctx.hash_vigente()
    except ValueError as e:
        c.falla(f"no se puede recalcular hash_contenido: {e}")
        return c
    c.nota(f"hash_contenido recalculado: {vigente}")
    faltan = [m for m in ("hashes", "textos_cliente") if _nucleo(m) is None]
    if faltan:
        c.aviso(f"sandbox/nucleo sin {faltan}: hash y barridos solo con la réplica local de E")
    if ctx.estado.get("hash_contenido") != vigente:
        c.falla(f"estado.json declara {ctx.estado.get('hash_contenido')} y el recalculado es {vigente}")
    if ctx.manifiesto.get("hash_contenido") != vigente:
        c.falla(f"el manifiesto declara {ctx.manifiesto.get('hash_contenido')} y el recalculado es {vigente}")
    for k in ("codigo", "version", "estado"):
        if ctx.manifiesto.get(k) != ctx.estado.get(k):
            c.falla(f"{k}: manifiesto {ctx.manifiesto.get(k)!r} ≠ estado {ctx.estado.get(k)!r}")
    if ctx.estado.get("codigo") != f"OF-{ctx.carga.get('alta', {}).get('codigo_cliente')}-" \
                                   f"{ctx.carga.get('alta', {}).get('seqof')}-{ctx.estado.get('version')}":
        c.falla("el código no es OF-<codigo_cliente>-<seqof>-<versión> del alta")
    art = (ctx.estado.get("artefactos") or {}).get("xlsx_estimacion") or {}
    xl = ctx.paquete.ficheros.get(f"{ctx.codigo}-Estimacion.xlsx")
    if xl is not None and art.get("sha256") != sha256_fichero(xl):
        c.falla("el XLSX canónico no es el registrado en artefactos.xlsx_estimacion (se ha regenerado o tocado)")
    if any(f"{ctx.codigo}-{s}" in ctx.paquete.ficheros for s in (SUFIJO_PPTX_REVISION, SUFIJO_PPTX_APROBADA)):
        p = ctx.pptx()
        if p.props.get("keywords") != f"hash_contenido:{vigente}":
            c.falla(f"PPTX: keywords {p.props.get('keywords')!r} ≠ hash_contenido:{vigente}")
        con_hash = [d.numero for d in p.diapositivas if vigente in " ".join(d.textos)]
        if con_hash != [2]:
            c.falla(f"PPTX: el hash debe aparecer solo y completo en la diapositiva 2; aparece en {con_hash}")
    if f"{ctx.codigo}-Nota-Revision.docx" in ctx.paquete.ficheros:
        textos, props, _ = ctx.docx()
        if vigente not in " ".join(textos):
            c.falla("DOCX: la nota de revisión no lleva el hash_contenido vigente en el texto")
        if props.get("keywords") not in (None, "", f"hash_contenido:{vigente}"):
            c.falla(f"DOCX: keywords {props.get('keywords')!r} no es el hash vigente")
    return c


def es_version_a(cons: object, resp: object) -> bool:
    """Paquete de la versión A (I1, anterior a I1.1): consolidado sin la clave «lotes», que el núcleo nuevo
    escribe siempre, y respuesta del verificador sin precios_azure, que en la v2 es obligatorio. Hacen
    falta las dos: quitar solo una no basta para que se aplique el contrato anterior (papel V, LES-G-096)."""
    herramientas = resp.get("herramientas_usadas") if isinstance(resp, dict) else None
    return (isinstance(cons, dict) and "lotes" not in cons and isinstance(herramientas, dict)
            and "precios_azure" not in herramientas)


def nombre_esquema_verificador(carga: dict) -> str:
    """Esquema con el que se valida la respuesta guardada: el histórico congelado para la versión A y para las
    respuestas anteriores a I1.4 (sin «campo», es_contrato_v2)."""
    resp = (carga.get("verificacion") or {}).get("respuesta")
    if es_version_a(carga.get("consolidado"), resp):
        return "historico/respuesta_verificador_v1"
    if es_contrato_v2(resp):
        return "historico/respuesta_verificador_v2"
    herramientas = resp.get("herramientas_usadas") if isinstance(resp, dict) else None
    if isinstance(herramientas, dict) and "precios_azure" in herramientas:  # I1.4 a I1.6 (integrador I1.7)
        return "historico/respuesta_verificador_v3"
    return "respuesta_verificador"


def c_esquemas(ctx: Contexto) -> Comprobacion:
    """Esquemas · estado.json y sus bloques conformes a esquemas/ (referencia ejecutable de P0)."""
    c = Comprobacion("esquemas", c_esquemas.__doc__.split("·")[1].strip())
    for e in validar_esquema(ctx.estado, "estado"):
        c.falla(f"estado.json {e}")
    carga = ctx.carga
    pares = [("requisitos", carga.get("requisitos")), (nombre_esquema_experto(ctx.respuesta), ctx.respuesta),
             (nombre_esquema_verificador(carga), (carga.get("verificacion") or {}).get("respuesta")),
             ("anexo_consumo", carga.get("anexo_consumo")), ("textos_cliente", carga.get("textos_cliente"))]
    for nombre, inst in pares:
        if inst in (None, {}, []):
            c.falla(f"{nombre}: ausente en carga")
            continue
        for e in validar_esquema(inst, nombre):
            c.falla(f"{nombre} {e}")
    for d in ctx.estado.get("decisiones") or []:
        for e in validar_esquema(d, "decision"):
            c.falla(f"decisión {d.get('id')}: {e}")
    # REVERIF16-2 (I1.7): cada brief con su esquema (lo exige la descripción de esquemas/estado.json), y un dato de
    # control con otra forma no apaga su regla en silencio: conservar_precios o aceptados que no son lista, FALLA.
    for b in carga.get("briefs") or []:
        bid = b.get("brief_id") if isinstance(b, dict) else None
        for e in validar_esquema(b, "brief"):
            c.falla(f"brief {bid}: {e}")
        for clave in ("conservar_precios", "aceptados"):
            if isinstance(b, dict) and clave in b and not isinstance(b[clave], list):
                c.falla(f"brief {bid}: {clave} no es una lista ({type(b[clave]).__name__}): apagaría su regla sin aviso")
    try:
        anexo_fichero = ctx.paquete.json_de(f"{ctx.codigo}-Anexo-Consumo.json")
    except (KeyError, EntradaIlegible) as e:
        c.falla(f"anexo JSON ilegible: {e}")
    else:
        if anexo_fichero != carga.get("anexo_consumo"):
            c.falla("el anexo JSON del paquete no es igual a carga.anexo_consumo")
    return c


SCHEMA_INSTANTANEA = "preventa-precios-instantanea/1"
MAX_DIAS_INSTANTANEA = 31   # decisión 1 del comercial (13-10-2026): más vieja en la fecha del paquete, FALLA


def hash_instantanea_replica(obj: dict) -> str:
    """Huella interna de la instantánea: SHA-256 del JSON canónico sin la clave «sha256» (CAMBIOS-I17-R §3)."""
    return hash_json({k: v for k, v in obj.items() if k != "sha256"})


def fecha_del_paquete(manifiesto: dict) -> dt.date | None:
    """Fecha del paquete: la de generado_ts del manifiesto (None si no es una fecha ISO)."""
    try:
        return dt.datetime.fromisoformat(str(manifiesto.get("generado_ts") or "").replace("Z", "+00:00")).date()
    except ValueError:
        return None


def precio_finito_no_negativo(x: object) -> bool:
    """Número JSON (no booleano) finito y ≥ 0. Revisión (2.ª pasada): un entero enorme no cabe en float y
    math.isfinite lanzaría OverflowError; se trata como no válido, nunca como excepción."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x)) and x >= 0
    except OverflowError:
        return False


# Multinube: réplica con código propio de nucleo.experto.errores_procedencia (procedencia del euro, identificador de
# precio de cada nube, regiones de AWS en la UE y EUR = USD / tipo del BCE con 6 decimales).
FUENTE_MONEDA_R = {"azure": "azure_retail_eur", "gcp": "gcp_catalog_eur", "aws": "aws_usd_convertido_bce"}
REGIONES_UE_AWS_R = frozenset({"eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1", "eu-south-1", "eu-south-2"})
ID_PRECIO_R = {"azure": set(), "gcp": {"sku_id"}, "aws": {"sku", "codigo_oferta", "precio_origen_usd"}}
PREFIJO_R = {"azure": "az-", "gcp": "gcp-", "aws": "aws-"}
DIAS_TIPO_BCE_R = 7


def errores_procedencia_r(obj: dict) -> list[str]:
    pilar = obj.get("pilar", "azure")
    if pilar not in FUENTE_MONEDA_R:
        return [f"pilar {pilar!r} fuera de la lista blanca {PILARES}"]
    fm, errores = obj.get("fuente_moneda"), []
    if fm is None:
        if pilar != "azure":
            errores.append("precios sin procedencia de la moneda (fuente_moneda)")
    elif fm != FUENTE_MONEDA_R[pilar]:
        errores.append(f"fuente_moneda {fm!r} no es la de {pilar}")
    fuente = str(obj.get("fuente"))
    if pilar == "azure" and ("prices.azure.com/api/retail/prices" not in fuente or not re.search(
            r"currencyCode\s*=\s*'?EUR'?(?![A-Za-z])", fuente)):   # Azure: Retail Prices en EUR, con clave o sin ella
        errores.append("precios de Azure sin procedencia de la moneda (fuente: Retail Prices con currencyCode=EUR)")
    tasa, fecha_tasa = obj.get("tipo_bce"), obj.get("fecha_tipo_bce")
    if pilar != "aws":
        if tasa is not None or fecha_tasa is not None:
            errores.append("tipo del BCE en una instantánea que no es de AWS")
        tasa = None
    else:
        try:
            f_tasa = dt.date.fromisoformat(str(fecha_tasa))
            dias = -1 if f_tasa.isoweekday() > 5 else (dt.date.fromisoformat(str(obj.get("fecha_consulta"))[:10]) - f_tasa).days
        except ValueError:
            dias = -1
        if not precio_finito_no_negativo(tasa) or not 0 < tasa <= 100 or not 0 <= dias <= DIAS_TIPO_BCE_R \
                or Decimal(str(tasa)).as_tuple().exponent < -4:
            errores.append(f"AWS sin tipo del BCE válido y reciente (tipo_bce {tasa!r}, fecha_tipo_bce {fecha_tasa!r})")
            tasa = None
    plantillas = obj.get("plantillas") if isinstance(obj.get("plantillas"), dict) else {}
    for clave, pl in plantillas.items():
        if not isinstance(pl, dict):
            continue
        if "/" in clave and not clave.startswith(PREFIJO_R[pilar]):
            errores.append(f"plantilla {clave}: no es de {pilar}")
        propios = set(pl) & {"sku_id", "sku", "codigo_oferta", "precio_origen_usd", "meterId"}
        if propios - ID_PRECIO_R[pilar] - ({"meterId"} if pilar == "azure" else set()) \
                or ID_PRECIO_R[pilar] - propios:
            errores.append(f"plantilla {clave}: identificador de precio que no es el de {pilar}")
            continue
        if pilar != "aws":
            continue
        if pl.get("armRegionName") not in REGIONES_UE_AWS_R:
            errores.append(f"plantilla {clave}: región {pl.get('armRegionName')!r} fuera de la UE")
        if tasa is None:
            continue
        for usd, eur in [(pl.get("precio_origen_usd"), pl.get("precio_unitario"))] + [
                (t.get("precio_origen_usd"), t.get("precio_unitario")) for t in pl.get("tramos") or [] if isinstance(t, dict)]:
            if not (precio_finito_no_negativo(usd) and precio_finito_no_negativo(eur)) or Decimal(str(eur)) != (
                    Decimal(str(usd)) / Decimal(str(tasa))).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP):
                errores.append(f"plantilla {clave}: {eur!r} EUR no es {usd!r} USD / {tasa} (BCE, 6 decimales)")
                break
    return errores


def errores_instantanea(obj: object, fecha_paquete: dt.date | None, catalogo: dict | None = None) -> list[str]:
    """Forma mínima del contrato común (a), huella interna, las plantillas del catálogo de confianza («catalogo_id/
    plantilla_id», con su mismo filtro) con precio finito y no negativo, y edad: fecha_consulta no posterior a la fecha
    del paquete ni más de MAX_DIAS_INSTANTANEA días anterior. Réplica parcial de catalogo/instantanea_precios.problemas
    (de P): la unidad frente al divisor de cada plantilla la comprueba el núcleo."""
    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA_INSTANTANEA or obj.get("moneda") != "EUR":
        return [f"no es una instantánea {SCHEMA_INSTANTANEA} en EUR"]
    try:
        huella = hash_instantanea_replica(obj)
    except (TypeError, ValueError) as e:   # un NaN o infinito no tiene JSON canónico
        errores = [f"la huella interna no se puede calcular: {e}"]
    else:
        errores = [] if obj.get("sha256") == huella else ["la huella interna no es la del contenido"]
    plantillas = obj.get("plantillas")
    if not isinstance(plantillas, dict) or not plantillas:
        errores.append("sin plantillas")
    if isinstance(plantillas, dict) and catalogo:
        esperadas = {f"{f.get('id')}/{pl.get('id')}": pl.get("filtro") for f in _entradas(catalogo)
                     for pl in f.get("plantillas_precio") or [] if isinstance(pl, dict)}
        errores += [f"falta la plantilla {k} del catálogo" for k in sorted(set(esperadas) - set(plantillas))]
        errores += [f"plantilla {k} que no está en el catálogo" for k in sorted(set(plantillas) - set(esperadas))]
        errores += [f"{k}: el filtro no es el del catálogo" for k in sorted(set(esperadas) & set(plantillas))
                    if not isinstance(plantillas[k], dict) or plantillas[k].get("filtro") != esperadas[k]]
    for pid, pl in (plantillas if isinstance(plantillas, dict) else {}).items():
        precio = pl.get("precio_unitario") if isinstance(pl, dict) else None
        n = pl.get("articulos_devueltos") if isinstance(pl, dict) else None
        if not isinstance(pl, dict) or isinstance(n, bool) or not isinstance(n, int) or n < 1:
            errores.append(f"la plantilla {pid} no trae artículos devueltos")
        elif not precio_finito_no_negativo(precio):
            errores.append(f"la plantilla {pid} no tiene un precio_unitario finito y no negativo")
    errores += errores_procedencia_r(obj)
    try:
        consulta = dt.datetime.fromisoformat(str(obj.get("fecha_consulta")).replace("Z", "+00:00"))
    except ValueError:
        return errores + [f"fecha_consulta no es una fecha ISO: {obj.get('fecha_consulta')!r}"]
    if consulta.tzinfo is None:
        return errores + ["fecha_consulta sin zona horaria (tiene que ser UTC)"]
    dia = consulta.astimezone(dt.timezone.utc).date()
    if fecha_paquete is None:
        errores.append("el manifiesto no trae una fecha del paquete (generado_ts) con la que medir la edad")
    elif dia > fecha_paquete:
        errores.append(f"instantánea del {dia.isoformat()}, posterior a la fecha del paquete ({fecha_paquete.isoformat()})")
    elif (fecha_paquete - dia).days > MAX_DIAS_INSTANTANEA:
        errores.append(f"instantánea del {dia.isoformat()}: {(fecha_paquete - dia).days} días en la fecha del paquete "
                       f"({fecha_paquete.isoformat()}), más de {MAX_DIAS_INSTANTANEA}: hay que redesplegar y regenerar")
    return errores


def _instantanea(ctx: Contexto, c: Comprobacion, montados: dict) -> None:
    """I1.7 (decisión 1): la instantánea local de confianza es la que declara el paquete (huella en montados) y no tiene
    más de MAX_DIAS_INSTANTANEA días en la fecha del paquete. Sin huella declarada, FALLA (fallar cerrado)."""
    ruta = pathlib.Path(ctx.precios or POR_DEFECTO["precios"])
    declarada = montados.get("precios_instantanea_sha256")
    if not ruta.is_file():
        c.falla(f"no existe la instantánea de precios local de confianza: {ruta}")
        return
    local = sha256_fichero(ruta)
    if declarada is None:
        c.falla("el manifiesto no declara precios_instantanea_sha256: paquete anterior a I1.7 o generado sin la "
                "instantánea de precios del despliegue")
    elif declarada != local:
        c.falla(f"precios_instantanea_sha256: el paquete dice {declarada} y la local ({ruta}) es {local}")
    try:
        obj = json.loads(ruta.read_text(encoding="utf-8"), parse_constant=_sin_nan)
    except (UnicodeDecodeError, ValueError) as e:
        c.falla(f"instantánea de precios ilegible ({ruta}): {e}")
        return
    errores = errores_instantanea(obj, fecha_del_paquete(ctx.manifiesto), ctx.catalogo_obj)
    errores += _pilar_paquete(ctx, obj)
    for e in errores:
        c.falla(f"instantánea de precios: {e}")
    if not errores:
        c.nota(f"instantánea de precios consultada el {obj.get('fecha_consulta')}: {len(obj['plantillas'])} plantillas")


def _pilar_paquete(ctx: Contexto, inst: dict) -> list[str]:
    """Multinube: el pilar del manifiesto (sin la clave, azure), el del estado, el de la instantánea y el del catálogo
    de confianza son el mismo y de la lista blanca; en AWS, toda región del paquete está en la UE."""
    pilar = pilar_ctx(ctx)
    pilares = {"manifiesto": (getattr(ctx, "manifiesto", None) or {}).get("pilar", "azure"), "estado": pilar,
               "instantánea": inst.get("pilar", "azure"),
               "catálogo": (getattr(ctx, "catalogo_obj", None) or {}).get("pilar", "azure")}
    errores = [f"pilar del {k} {v!r} fuera de la lista blanca {PILARES}" for k, v in pilares.items() if v not in PILARES]
    if len(set(pilares.values())) != 1:
        errores.append(f"el pilar no coincide: {pilares}")
    if pilar == "aws":
        r, anexo = ctx.respuesta, ctx.carga.get("anexo_consumo") or {}
        regiones = [(f"{b} {x.get('id')}", x.get("region")) for b in ("componentes", "precios")
                    for x in r.get(b) or [] if isinstance(x, dict)]
        regiones += [(f"anexo {x.get('precio_id')}", x.get("region")) for x in anexo.get("lineas") or []
                     if isinstance(x, dict)]
        errores += [f"{donde}: región {reg!r} fuera de la UE" for donde, reg in regiones
                    if reg not in (None, "") and reg not in REGIONES_UE_AWS_R]
    return errores


def c_montados(ctx: Contexto) -> Comprobacion:
    """P0 · Ficheros montados: tarifa, generador, plantilla, catálogo e instantánea de precios = los locales de confianza."""
    c = Comprobacion("montados", c_montados.__doc__.split("·")[1].strip())
    m = ctx.manifiesto.get("montados") or {}
    pares = (("rate_card_sha256", ctx.rate_card), ("generador_sha256", ctx.generador),
             ("plantilla_sha256", ctx.plantilla), ("catalogo_sha256", ctx.catalogo))
    for clave, ruta in pares:
        if not pathlib.Path(ruta).is_file():
            c.falla(f"no existe la copia local de confianza para {clave}: {ruta}")
            continue
        local = sha256_fichero(ruta)
        if m.get(clave) != local:
            c.falla(f"{clave}: el paquete dice {m.get(clave)} y el local ({ruta}) es {local}")
    vigente = _brief_vigente(ctx) or {}
    for b in ctx.carga.get("briefs") or []:
        # PR19-1 (I1.10): desde I1.10 la cabecera del brief no lleva la línea catalogo_sha256 (el experto la copiaba
        # mal); la huella va en la entrada de carga.briefs. Un brief anterior la lleva en el texto y se exige allí.
        cab = b.get("texto", "").partition("\n---\n")[0]
        linea = re.search(r"^catalogo_sha256: ([0-9a-f]{64})$", cab, re.M)
        guardado = linea.group(1) if linea else b.get("catalogo_sha256")
        if guardado != m.get("catalogo_sha256") or b.get("catalogo_sha256") not in (None, guardado):
            msg = f"{b.get('brief_id')}: el brief no se generó con el catálogo montado"
            (c.falla if b.get("brief_id") == vigente.get("brief_id") else c.aviso)(msg)
    _instantanea(ctx, c, m)
    return c


BLOQUEANTES = ("objetivo", "nubes", "alcance_funcional", "ubicacion_usuarios", "marco_normativo")
ASUMIBLES = ("canales_integraciones", "volumetria", "identidad_acl_origen", "red_privada", "tipo_suscripcion",
             "plazo", "presupuesto_orientativo", "idioma_oferta")
# REV-1: réplica de nucleo.suficiencia.nubes_fuera_de_i1 (si el núcleo está, debe dar lo mismo). LISTA BLANCA:
# falla cerrado ante cualquier valor que no sea una de estas formas (LES-G-098.3), también ante las negaciones.
NUBES_I1 = ("azure", "microsoft azure")
PLANTILLAS_NUBES = ("{}", "en {}", "solo {}", "solo en {}", "unicamente en {}", "debe vivir en {}",
                    "la solucion debe vivir en {}", "queremos que viva en {}", "queremos que esto viva en {}")
NUBES_ADMITIDAS = frozenset(p.format(n) for p in PLANTILLAS_NUBES for n in NUBES_I1)
NUBES_PILAR_R = {"azure": NUBES_I1, "gcp": ("google cloud", "google cloud platform", "gcp"),
                 "aws": ("aws", "amazon web services")}   # multinube: réplica de suficiencia.NUBES_PILAR
_BORDES_NUBES = " .,;:!?¡¿«»\"'"
# VER-2: solo se colapsan los espacios horizontales; los separadores de línea se quedan y hacen fallar la lista blanca.
_ESPACIOS_H_NUBES = re.compile(r"[^\S\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]+")
# REV-2: prefijos que se quitan para el alias corto («Azure AI Search» → «AI Search»), si quedan 2 palabras.
_PREFIJOS_MARCA = ("azure", "microsoft")
_ALIAS_MIN = 5


# REV-2: réplica de nucleo.experto.HOMOGLIFOS (cirílico y griego, en minúsculas, a su letra latina).
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
    """REV-2: plegado y solo letras y dígitos ASCII (sin espacios ni signos), para comparar alias."""
    return "".join(ch for ch in _plegar(texto) if "a" <= ch <= "z" or "0" <= ch <= "9")


def alias_servicio(entrada: dict) -> list[str]:
    """REV-2: réplica de nucleo.experto.alias_servicio (nombre oficial, `alias` del catálogo, nombre de precios
    y la forma sin «Azure»/«Microsoft» de cada uno), en forma compacta y sin repetir."""
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
    """Réplica de nucleo.experto.alias_inequivocos: {id: alias} sin los que aparecen dentro de algún alias de OTRA
    entrada (un alias compartido, como «Foundry Tools», no identifica el servicio)."""
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
# Réplica de nucleo.experto, con el catálogo LOCAL (nunca el del ZIP); prueba de igualdad en
# tests/test_i12_arreglos_servicename.py.
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
    latinas, falla cerrado (REVSN-3: con su id, manda el id). Réplica de nucleo.experto.region_no_admitida.
    I1.9 (CAMBIOS-I19-P §7): la región de un recurso del cliente no se veta, como en el núcleo (mismo código: es_existente
    es el alias de la réplica es_existente_r).
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
    no aplica o si region_no_admitida ya lo rechaza. Réplica de nucleo.experto.aviso_fuera_de_catalogo."""
    region = str(comp.get("region") or "").strip().casefold()
    # CMP-1 (I1.3): «global» se veta para Bot Service (bot regional en la UE), pero no es una región en la que se
    # «compruebe disponibilidad»: un SaaS sin catalogo_id (SharePoint) en «global» no lleva este aviso.
    if region == "global" or region not in _regiones_con_veto(catalogo) or region_no_admitida(comp, catalogo, precios):
        return None
    if identificar_servicio(comp, catalogo, precios)["id"] is not None:
        return None
    return f"{comp.get('id')} «{comp.get('servicio')}» en {comp.get('region')}: {AVISO_FUERA_DE_CATALOGO}"


def forma_nubes(valor: object) -> str:
    """VER-2: réplica de nucleo.suficiencia.forma_nubes (prueba de igualdad en tests/test_i12_arreglos_ver.py).
    NFC, minúsculas, sin tildes, espacios horizontales colapsados y sin puntuación en los extremos; NO usa
    normalizar_para_cita (que borra la sintaxis VTT): un salto de línea, «-->», «<v …>» o NOTE no casan nunca."""
    t = unicodedata.normalize("NFC", valor if isinstance(valor, str) else "").lower()
    t = unicodedata.normalize("NFC", "".join(ch for ch in unicodedata.normalize("NFD", t)
                                             if unicodedata.category(ch) != "Mn"))
    return _ESPACIOS_H_NUBES.sub(" ", t).strip(_BORDES_NUBES)


def nubes_fuera_de_i1(valores: list, pilar: str = "azure") -> list[str]:
    """Valores de `nubes` que I1 no cubre: los que no son una forma de NUBES_ADMITIDAS (lista blanca), con los nombres de
    la nube del pilar (multinube; azure por defecto)."""
    admitidas = NUBES_ADMITIDAS if pilar == "azure" else frozenset(
        p.format(n) for p in PLANTILLAS_NUBES for n in NUBES_PILAR_R.get(pilar, ()))
    malos = []
    for v in valores:
        n = forma_nubes(v)
        if n not in admitidas:
            malos.append(str(v))
    return malos


def FUENTES_LOCALES(ctx: Any) -> dict[str, tuple[str, str, Any]]:   # noqa: N802
    """Notas del comercial: copia local de confianza de cada fuente del alta, por tipo (en el orden del alta)."""
    return {"TRANSCRIPCION": ("la transcripción", "--transcripcion", getattr(ctx, "transcripcion", None)),
            "NOTAS_COMERCIAL": ("las notas del comercial", "--notas", getattr(ctx, "notas", None))}


def texto_del_alta_local(ctx: Any, sf: Any, hs: Any) -> str | None:
    """El texto de la reunión y de las notas del comercial como lo une el núcleo (preventa_run.texto_del_alta), desde
    las copias locales comprobadas por su sha256_texto; None si falta alguna o no cuadra."""
    locales = {t: r for t, (_, _, r) in FUENTES_LOCALES(ctx).items()}
    textos = []
    for f in ctx.carga.get("fuentes") or []:
        if not isinstance(f, dict) or f.get("tipo") not in locales:
            continue
        ruta = locales[f["tipo"]]
        if not ruta or not pathlib.Path(ruta).is_file():
            return None
        texto = sf.extraer_texto(pathlib.Path(ruta))
        if hs.sha256_texto(texto) != f.get("sha256_texto"):
            return None
        textos.append(texto)
    return "\n\n".join(textos) if textos else None


AVISO_SIN_GRABACION_R = ("Sin grabación: los requisitos salen de las notas del comercial; revisa con él lo que no esté "
                         "escrito.")


def _aviso_sin_grabacion(ctx: Contexto, c: Comprobacion, fuentes: dict) -> None:
    """Notas del comercial: sin transcripción en el alta, la nota del revisor y el mensaje al responsable de preventa dicen, en un párrafo
    propio (LES-G-077), que los requisitos salen de las notas del comercial; con transcripción, no lo dicen."""
    if not any(isinstance(f, dict) and f.get("tipo") == "NOTAS_COMERCIAL" for f in fuentes.values()):
        return   # alta de siempre: nada que mirar
    sin = not any(isinstance(f, dict) and f.get("tipo") == "TRANSCRIPCION" for f in fuentes.values())
    try:
        nota = [nfc(t).strip() for t in ctx.docx()[0]]
        mensaje = [ln.strip() for ln in ctx.paquete.bytes_de("mensaje_revisor.txt").decode("utf-8").splitlines()]
    except (KeyError, OSError, UnicodeDecodeError, zipfile.BadZipFile) as e:
        c.falla(f"aviso de notas del comercial: no se pudo leer la nota o el mensaje ({type(e).__name__}: {e})")
        return
    for donde, lineas, esperado in (("nota del revisor", nota, AVISO_SIN_GRABACION_R),
                                    ("mensaje al responsable de preventa", mensaje, f"IMPORTANTE. {AVISO_SIN_GRABACION_R}")):
        if sin and lineas.count(esperado) != 1:
            c.falla(f"{donde}: sin grabación y sin el aviso «{AVISO_SIN_GRABACION_R}» en un párrafo propio")
        elif not sin and esperado in lineas:
            c.falla(f"{donde}: dice «sin grabación» y el alta trae transcripción")


def c_suficiencia(ctx: Contexto) -> Comprobacion:
    """P1 · Suficiencia: bloqueantes citados, asumibles citados o ASUMIDO y citas en la transcripción."""
    c = Comprobacion("suficiencia", c_suficiencia.__doc__.split("·")[1].strip())
    fuentes = {f.get("id"): f for f in ctx.carga.get("fuentes") or []}
    textos = {}
    locales = FUENTES_LOCALES(ctx)
    registradas = {t: [f for f in fuentes.values() if isinstance(f, dict) and f.get("tipo") == t] for t in locales}
    faltan = [f"el alta registra {que} en {registradas[t][0].get('id')} y no se ha dado su copia local ({opcion})"
              for t, (que, opcion, ruta) in locales.items() if ruta is None and registradas[t]]
    for motivo in faltan:
        c.falla(motivo)
    if faltan:
        return c
    for tipo, (que, opcion, ruta) in locales.items():
        if ruta is None:
            continue
        if not registradas[tipo] and tipo != "TRANSCRIPCION":
            c.falla(f"se ha dado {opcion} y el alta no registra {que}")
            return c
        f = registradas[tipo][0] if registradas[tipo] else {"id": "F1"}   # sin transcripción: el mensaje de siempre
        datos = pathlib.Path(ruta).read_bytes()
        if sha256_bytes(datos) != f.get("sha256"):
            local = "local" if tipo == "TRANSCRIPCION" else "locales"
            c.falla(f"{que} {local} ({sha256_bytes(datos)}) no {'es la registrada' if tipo == 'TRANSCRIPCION' else 'son las registradas'} "
                    f"en {f.get('id')} ({f.get('sha256')})")
            return c
        textos[f["id"]] = texto_cita_normalizado(datos.decode("utf-8-sig"))
    for fid, ruta in ctx.aclaraciones.items():
        b = pathlib.Path(ruta).read_bytes()
        if sha256_bytes(b) != (fuentes.get(fid) or {}).get("sha256"):
            c.falla(f"la aclaración local {ruta} no es la registrada en {fid}")
            continue
        textos[fid] = texto_cita_normalizado(b.decode("utf-8-sig"))
    _aviso_sin_grabacion(ctx, c, fuentes)
    campos = (ctx.carga.get("requisitos") or {}).get("campos") or {}
    for campo in BLOQUEANTES + ASUMIBLES:
        info = campos.get(campo)
        if not info or not info.get("entradas"):
            c.falla(f"{campo}: falta (es {'BLOQUEANTE' if campo in BLOQUEANTES else 'ASUMIBLE'})")
            continue
        for n, ent in enumerate(info["entradas"]):
            donde, origen = f"{campo}[{n}]", ent.get("origen")
            if origen == "ASUMIDO":
                if campo in BLOQUEANTES:
                    c.falla(f"{donde}: un campo BLOQUEANTE no se puede asumir (LES-G-042)")
                if ent.get("cita") is not None:
                    c.falla(f"{donde}: ASUMIDO con cita")
                continue
            fid = ent.get("fuente")
            if fid not in textos:
                c.no_verificado(f"{donde}: cita de {fid}, sin copia local (usa --aclaracion {fid}=RUTA)")
                continue
            ok, motivo = cita_valida(ent.get("cita") or "", textos[fid])
            if not ok:
                c.falla(f"{donde}: {motivo}: «{(ent.get('cita') or '')[:80]}»")
    nubes = [e.get("valor") for e in (campos.get("nubes") or {}).get("entradas", [])]
    malos = nubes_fuera_de_i1(nubes, pilar_ctx(ctx))
    if malos and pilar_ctx(ctx) == "azure":
        c.falla(f"nubes = {malos}: en I1 solo Azure, y el valor debe ser una forma admitida («Azure», «Microsoft "
                f"Azure», «La solución debe vivir en Azure»…; lista blanca, REV-1)")
    elif malos:   # multinube: el motivo con la nube del pilar (Revisión)
        c.falla(f"nubes = {malos}: la solicitud es de {pilar_ctx(ctx)} y el valor debe ser una forma admitida con "
                f"{' o '.join(NUBES_PILAR_R.get(pilar_ctx(ctx), ()))} (lista blanca, REV-1)")
    suf = _nucleo("suficiencia")
    if suf is not None and bool(suf.nubes_fuera_de_i1([str(v or "") for v in nubes], pilar_ctx(ctx))) != bool(malos):
        c.falla("nubes: la réplica local y nucleo.suficiencia no dan el mismo resultado")
    entradas = (campos.get("ya_contratado_por_cliente") or {}).get("entradas") or []
    if entradas:  # I1.9 (PR18-1, CAMBIOS-I19-P §7): una entrada por recurso, con su servicio y su cita entera
        pares = existentes_requisitos_r(entradas, ctx.catalogo_obj)
        for ex_id, regla in pares:
            c.falla(f"ya_contratado_por_cliente {ex_id}: {regla}; una entrada por recurso, con su servicio del catálogo "
                    "y la cita entera (PR18-1)")
        if suf is None:
            c.aviso("ya_contratado_por_cliente: sin núcleo local; decide solo la réplica (no se ha contrastado)")
        elif not hasattr(suf, "reglas_existentes"):
            c.falla("ya_contratado_por_cliente: el núcleo local no tiene suficiencia.reglas_existentes (anterior a I1.9)")
        elif suf.reglas_existentes(entradas, ctx.catalogo_obj) != pares:
            c.falla("ya_contratado_por_cliente: la réplica local y nucleo.suficiencia no dan lo mismo (LES-G-097)")
    return c


def _norm_url(url: str) -> str | None:
    """§6.3: https, host learn.microsoft.com, sin idioma, minúsculas, sin consulta ni barra final."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url.strip())
        puerto = u.port  # P16-6 (I1.6): un puerto mal formado lanzaba ValueError fuera del try, como en el núcleo
    except ValueError:
        return None
    # I1.9 (Revisión): «puerto is not None», como el núcleo; con «or puerto» pasaba «:0» (falso para Python)
    if u.scheme != "https" or u.hostname != "learn.microsoft.com" or puerto is not None or u.username or "@" in u.netloc:
        return None  # P17-5 (I1.7): también «https://:x@learn…» (sin usuario y con contraseña)
    ruta = re.sub(r"^/[a-z]{2}-[a-z]{2}(?=/|$)", "", u.path.lower()).rstrip("/")
    return ruta or "/"


PREF_ARQ = ("/azure/architecture", "/azure/well-architected", "/azure/cloud-adoption-framework",
            "/azure/ai-foundry", "/azure/foundry")
PREF_SERV = ("/azure/search", "/azure/ai-services", "/azure/foundry-classic", "/azure/security",
             "/azure/private-link", "/azure/virtual-network", "/azure/app-service", "/azure/container-apps",
             "/azure/azure-functions", "/azure/storage", "/azure/cosmos-db", "/azure/key-vault",
             "/azure/azure-monitor", "/azure/api-management", "/azure/reliability",
             "/azure/defender-for-cloud", "/azure/governance", "/azure/role-based-access-control",
             "/azure/cost-management-billing", "/azure/logic-apps", "/azure/bot-service", "/entra",
             "/purview", "/compliance", "/security/benchmark/azure", "/microsoftteams/platform")
PREF_AMPLIACION = (
    "/azure/frontdoor", "/azure/web-application-firewall", "/azure/firewall", "/azure/application-gateway",
    "/azure/dns", "/azure/bastion", "/azure/ddos-protection", "/azure/networking",
    "/azure/expressroute", "/azure/vpn-gateway", "/azure/event-grid", "/azure/service-bus-messaging",
    "/azure/azure-sql", "/azure/postgresql", "/azure/data-factory", "/azure/databricks",
    "/azure/aks", "/azure/container-registry", "/azure/machine-learning", "/azure/redis",
    "/azure/sentinel", "/azure/backup", "/azure/azure-resource-manager", "/fabric",
    "/power-bi", "/office365", "/microsoft-365", "/microsoft-copilot-studio",
)
PREF_SERV = PREF_SERV + PREF_AMPLIACION


def _prefijo(ruta: str | None, prefijos: tuple[str, ...]) -> bool:
    return bool(ruta) and any(ruta == p or ruta.startswith(p + "/") for p in prefijos)


def _eco(t: str) -> str:
    return (t or "").replace("\r\n", "\n").rstrip()


def _strings(obj: Any, ruta: str = "$", saltar: tuple[str, ...] = ()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in saltar:
                yield from _strings(v, f"{ruta}.{k}", saltar)
    elif isinstance(obj, list):
        for n, v in enumerate(obj):
            yield from _strings(v, f"{ruta}[{n}]", saltar)
    elif isinstance(obj, str):
        yield ruta, obj


def _brief_vigente(ctx: Contexto) -> dict | None:
    bid = ((ctx.carga.get("respuestas_expertos") or {}).get(pilar_ctx(ctx)) or {}).get("brief_id")
    return next((b for b in ctx.carga.get("briefs") or [] if b.get("brief_id") == bid), None)


def ids_repetidos(lista: Any, que: str) -> list[str]:
    """REVPR-1 (I1.3): el mismo motivo que `nucleo.experto._repetidos` («<bloque>: id repetido <id>»). Un id repetido
    colapsa en un dict y esconde la copia que no gana; por eso la puerta falla, como el núcleo, y recorre listas.
    Admite ids no hashables o de otro tipo (un paquete forjado puede traerlos): compara por igualdad."""
    ids = [x.get("id") if isinstance(x, dict) else x for x in (lista if isinstance(lista, list) else [])]
    repetidos: list = []
    for i in ids:
        if ids.count(i) > 1 and i not in repetidos:
            repetidos.append(i)
    return [f"{que}: id repetido {i}" for i in sorted(repetidos, key=str)]


def _exigir_aviso_en_nota(c: Comprobacion, ctx: Contexto, cid: str, comp: dict) -> None:
    """VER-1: la nota de revisión tiene que llevar el aviso del componente fuera de catálogo (con su id y su región)."""
    if f"{ctx.codigo}-Nota-Revision.docx" not in ctx.paquete.ficheros:
        return  # sin nota en el paquete (LISTA o anterior): lo exige c_estructura si toca
    textos, _, _ = ctx.docx()
    fin = f" en {comp.get('region')}: {AVISO_FUERA_DE_CATALOGO}"
    if not any(f"Componente {cid} «" in t and fin in t for t in textos):
        c.falla(f"{cid}: la nota de revisión no lleva el aviso «{AVISO_FUERA_DE_CATALOGO}» (VER-1)")


def c_experto(ctx: Contexto) -> Comprobacion:
    """P2-P4 · Respuesta del experto: eco del brief, lista blanca, componentes, precios y tareas."""
    c = Comprobacion("experto", c_experto.__doc__.split("·")[1].strip())
    r = ctx.respuesta
    if not r:
        c.falla(f"no hay respuesta válida del experto en carga.respuestas_expertos.{pilar_ctx(ctx)}")
        return c
    brief = _brief_vigente(ctx)
    if brief is None:
        c.falla(f"el brief {r.get('brief_id')} de la respuesta no está en carga.briefs")
    else:
        if sha256_bytes(brief.get("texto", "").encode("utf-8")) != brief.get("sha256"):
            c.falla(f"{brief.get('brief_id')}: el SHA-256 registrado no es el de su texto")
        if _eco(r.get("brief_recibido")) != _eco(brief.get("texto")):
            c.falla("brief_recibido no es el brief enviado, literal (el núcleo debía rechazarla: intento T2)")
        if r.get("brief_id") != brief.get("brief_id"):
            c.falla("brief_id de la respuesta distinto del brief vigente")
    # REVPR-1 (I1.3): ids repetidos, con el motivo del núcleo, y se recorren las listas, no los dicts (el dict solo
    # guarda la última copia de cada id: un C-02 vetado delante del original no se comprobaba)
    for que in ("referencias", "componentes", "precios", "tareas_propuestas", "supuestos", "riesgos"):
        for m in ids_repetidos(r.get(que, []), que):
            c.falla(m)
    refs = {x.get("id"): x for x in r.get("referencias", [])}
    rutas = {}
    for ref in r.get("referencias", []):
        rid = ref.get("id")
        ruta = _norm_url(ref.get("url", ""))
        rutas[rid] = ruta
        if not (_prefijo(ruta, PREF_ARQ) or _prefijo(ruta, PREF_SERV)):
            c.falla(f"{rid}: URL fuera de la lista blanca §6.3: {ref.get('url')}")
    if not any(_prefijo(x, PREF_ARQ) for x in rutas.values()):
        c.falla("no hay ninguna referencia de arquitectura (§6.3)")
    cat = {x.get("id"): x for x in ctx.catalogo_obj.get("componentes", [])}
    comps = {x.get("id"): x for x in r.get("componentes", [])}
    for comp in r.get("componentes", []):
        cid = comp.get("id")
        existente = es_existente_r(comp)  # I1.9 (CAMBIOS-I19-P §5.9): un sistema del cliente no es una desviación
        if comp.get("referencia_id") not in refs and not (existente and comp.get("referencia_id") is None):
            c.falla(f"{cid}: referencia_id {comp.get('referencia_id')} inexistente")
        if comp.get("catalogo_id") is None:
            if not existente and len((comp.get("desviacion_justificada") or "").strip()) < 30:
                c.falla(f"{cid}: fuera de catálogo sin desviación justificada de ≥ 30 caracteres")
        elif comp.get("catalogo_id") not in cat:
            c.falla(f"{cid}: catalogo_id {comp.get('catalogo_id')!r} no está en el catálogo local")
        precios = r.get("precios") or []  # REVER-1 y REVSN: catalogo_id obligatorio y filtro que casa entero
        veto = region_no_admitida(comp, ctx.catalogo_obj, precios)
        if veto:
            c.falla(f"{cid}: {veto} (VERIF-3)")
        incoherencias = incoherencias_servicio(comp, ctx.catalogo_obj, precios)
        for m in incoherencias:
            c.falla(f"{cid}: {m} (REVER-1, REVSN)")
        ex = _nucleo("experto")
        if ex is not None and bool(ex.region_no_admitida(comp, ctx.catalogo_obj, precios)) != bool(veto):
            c.falla(f"{cid}: región: la réplica local y nucleo.experto no dan el mismo resultado")
        if ex is not None and ex.incoherencias_servicio(comp, ctx.catalogo_obj, precios) != incoherencias:
            c.falla(f"{cid}: servicio del precio: la réplica local y nucleo.experto no dan el mismo resultado")
        aviso = aviso_fuera_de_catalogo(comp, ctx.catalogo_obj, precios)  # VER-1: se acepta, nunca en silencio
        if aviso:
            c.aviso(aviso)
            _exigir_aviso_en_nota(c, ctx, cid, comp)
        if ex is not None and ex.aviso_fuera_de_catalogo(comp, ctx.catalogo_obj, precios) != aviso:
            c.falla(f"{cid}: aviso de catálogo: la réplica local y nucleo.experto no dan el mismo resultado")
    for f in r.get("flujos", []):  # como el núcleo; los flujos no tienen id (§6.4): sus extremos tienen que existir
        for extremo in ("origen", "destino"):
            if f.get(extremo) not in comps:
                c.falla(f"flujos: {extremo} {f.get(extremo)} no es un componente")
    for p in r.get("precios", []):
        pid, comp = p.get("id"), comps.get(p.get("componente_id"))
        if comp is None:
            c.falla(f"{pid}: componente {p.get('componente_id')} inexistente")
        elif p.get("region") != comp.get("region"):
            c.falla(f"{pid}: región {p.get('region')} ≠ la del componente {comp.get('region')}")
        if p.get("moneda") != "EUR" or not (p.get("filtro") or "").strip() or not (p.get("unidad") or "").strip():
            c.falla(f"{pid}: exige filtro, moneda EUR y unidad")
        try:
            dt.date.fromisoformat(str(p.get("effectiveStartDate", ""))[:10])
            cantidad = p.get("cantidad_mensual")  # I1.6: null = precio unitario de referencia (decisión 4)
            if dec(p.get("precio")) < 0 or (cantidad is not None and dec(cantidad) <= 0):
                c.falla(f"{pid}: precio negativo o cantidad mensual no positiva")
        except ValueError as e:
            c.falla(f"{pid}: {e}")
    _sin_precios_con_azure(ctx, c, "respuesta del experto",  # I1.6: solo cuentan los precios que suman
                           not [p for p in r.get("precios") or [] if isinstance(p, dict)
                                and p.get("cantidad_mensual") is not None])
    _cobertura_precios(ctx, c)  # PR15-2 y REVERIF14-2 (I1.5)
    _decision_4(ctx, c)  # I1.6: volumen, nivel y concepto (LES-G-100, VER15-3)
    _existentes_y_arquitectura(ctx, c)  # I1.9: recursos del cliente, canal sin cómputo y datos sin salida
    _referencias_y_conservacion(ctx, c)  # arreglos I1.6: PR16-1 y PR16-3
    _contrato_i17(ctx, c)  # I1.7: recomposición de la completada, motivos y ciclo de vida (CAMBIOS-I17-P §6)
    for t in r.get("tareas_propuestas", []):
        if t.get("perfil") not in ctx.perfiles:
            c.falla(f"{t.get('id')}: perfil «{t.get('perfil')}» fuera de la tarifa")
    hechos_ok = {f"R-{k}" for k in ((ctx.carga.get("requisitos") or {}).get("campos") or {})}
    hechos_ok |= set(refs) | set(comps) | {p.get("id") for p in r.get("precios", [])}
    for x in r.get("supuestos", []) + r.get("riesgos", []):
        malos = [h for h in x.get("hechos", []) if h not in hechos_ok]
        if malos or not x.get("hechos"):
            c.falla(f"{x.get('id')}: hechos inexistentes o vacíos {malos}")
    for ruta, s in _strings(r, saltar=("brief_recibido",)):
        for h in marcadores(s):
            c.falla(f"respuesta del experto {ruta}: {h}")
    return c


_CUASI = re.compile(r"\b\d[\d.\s]*\s+(usuarios|personas|empleados|t[ée]cnicos|analistas|investigadores)\b", re.I)


def c_brief(ctx: Contexto) -> Comprobacion:
    """P15 · Briefs anonimizados: sin términos sensibles, correos, teléfonos ni cifras de usuarios."""
    c = Comprobacion("brief", c_brief.__doc__.split("·")[1].strip())
    sensibles = (ctx.carga.get("alta") or {}).get("terminos_sensibles") or []
    if not ctx.carga.get("briefs"):
        c.falla("no hay ningún brief registrado")
    for b in ctx.carga.get("briefs") or []:
        texto, bid = b.get("texto", ""), b.get("brief_id")
        cab, sep, cuerpo = texto.partition("\n---\n")
        m = re.search(r"^sha256_cuerpo: ([0-9a-f]{64})$", cab, re.M)
        real = sha256_bytes(cuerpo.encode("utf-8"))
        # PR19-1 (I1.10): sin la línea en la cabecera (briefs desde I1.10), la huella es la de la entrada de carga.briefs
        if not sep or (m.group(1) if m else b.get("sha256_cuerpo")) != real \
                or b.get("sha256_cuerpo") not in (None, real):
            c.falla(f"{bid}: sha256_cuerpo no cuadra con el cuerpo del brief")
        # El brief_id lleva el código de cliente por contrato (§0); se revisa todo lo demás.
        pl = plano(re.sub(r"^brief_id: .*$", " ", texto, flags=re.M))
        for s in sensibles:
            if re.search(r"(?<!\w)" + re.escape(plano(s)) + r"(?!\w)", pl):
                c.falla(f"{bid}: contiene un término sensible declarado")
        # VER15-7 (I1.6): los nombres de quienes firman decisiones tampoco viajan al experto; un comentario de DEVUELTA
        # que los cite llega como [PERSONA]. Quien firma se nombra por su rol: se busca la frase entera, como el núcleo.
        pl_cuerpo = plano(cuerpo)
        for palabra in sorted(PERSONAS):
            if re.search(r"(?<!\w)" + re.escape(palabra) + r"(?!\w)", pl_cuerpo):
                c.falla(f"{bid}: el cuerpo nombra a quien firma decisiones («{palabra}»): debe ir como [PERSONA] "
                        "(VER15-7)")
        codigo_cliente = plano((ctx.carga.get("alta") or {}).get("codigo_cliente") or "")
        if codigo_cliente and codigo_cliente in plano(bid or ""):
            c.aviso(f"{bid}: el identificador del brief lleva el código de cliente (lo fija el contrato §0)")
        if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", texto):
            c.falla(f"{bid}: contiene un correo")
        for tel in re.findall(r"\+?\d[\d \-.]{7,}\d", cuerpo):
            if sum(ch.isdigit() for ch in tel) >= 9:
                c.falla(f"{bid}: contiene un teléfono")
        for mm in _CUASI.finditer(cuerpo):
            antes = cuerpo[max(0, mm.start() - 40):mm.start()]
            if not re.search(r"(entre [\d.]+ y|menos de|m[aá]s de)\s*$", antes, re.I):
                c.falla(f"{bid}: cifra exacta de personas «{mm.group(0)}» (debe ir en rango)")
        if len(texto.encode("utf-8")) > 20 * 1024:
            c.falla(f"{bid}: supera 20 KB")
        _comentarios_devuelta_en_brief(ctx, c, b, cuerpo)
        _propuesta_devuelta_en_brief(ctx, c, b, cuerpo)    # PR17-6 (arreglos I1.7)
        _conservar_atado_al_texto(c, b, cuerpo)          # REVERIF16-2 (I1.7)
        _aceptados_atados_al_texto(ctx, c, b)            # PR16-6 (I1.7)
    return c


def anonimizador_brief(ctx: Contexto):
    """La anonimización que aplica el núcleo al brief (términos del alta y hablantes de la transcripción local F1,
    comprobada por su SHA-256), con el módulo del repositorio; None si no se puede recomponer."""
    br, sf, hs = _nucleo("brief"), _nucleo("suficiencia"), _nucleo("hashes")
    alta = ctx.carga.get("alta") or {}
    texto = texto_del_alta_local(ctx, sf, hs) if br is not None and sf is not None and hs is not None else None
    if texto is None:   # notas del comercial: hablantes de la reunión y de las notas, como el núcleo
        return None
    sens, cliente = list(alta.get("terminos_sensibles") or []), [alta.get("cliente") or "", alta.get("codigo_cliente") or ""]
    personas = sf.hablantes(texto)
    if hasattr(br, "terminos_anonimizacion"):
        sens, cliente, personas = br.terminos_anonimizacion({"terminos_sensibles": sens, "cliente": cliente[0],
                                                             "codigo_cliente": cliente[1]}, personas)
    return lambda x: " ".join(br.anonimizar(x, sens, cliente, personas).split())


def _cuerpo_ronda_1_vigente(ctx: Contexto, c: Comprobacion, b: dict, cuerpo: str, lineas: list[str] | None) -> None:
    """REVERIF17-4 (I1.8): el brief de la ronda 1 de la versión vigente, si esa versión la abrió una DEVUELTA que guardó
    `version_devuelta`, es ENTERO el que compone el núcleo (nucleo.brief.cuerpos_ronda_1, con la anonimización y la
    instantánea locales): la propuesta devuelta no puede faltar, moverse ni cambiar. Se admite la composición de los
    arreglos de I1.7 (anterior a REVERIF17-5) con una nota; sin `version_devuelta`, también las anteriores a PR17-6."""
    est, bid = getattr(ctx, "estado", None) or {}, b.get("brief_id")
    br, anon = _nucleo("brief"), anonimizador_brief(ctx)
    if br is None or not hasattr(br, "cuerpos_ronda_1") or anon is None:
        if lineas is not None or (br is not None and hasattr(br, "resumen_devuelto") and br.resumen_devuelto(est)):
            c.aviso(f"{bid}: el brief de la ronda 1 de una versión devuelta no se ha podido recomponer en local (falta la "
                    "transcripción F1 o el núcleo del repositorio): contenido no contrastado (REVERIF17-4)")
        return
    try:
        resumen = br.resumen_devuelto(est)
        if resumen is None and lineas is None:
            return
        cuerpos = br.cuerpos_ronda_1(est, anon, instantanea=_instantanea_de_confianza(ctx))
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"{bid}: no se pudo recomponer el brief de la ronda 1 de la versión devuelta: {type(e).__name__}: {e} "
                "(REVERIF17-4)")
        return
    admitidos = ["vigente", "propuesta_formato_1"] + ([] if resumen is not None else ["sin_propuesta", "sin_devuelta"])
    casa = next((k for k in admitidos if k in cuerpos
                 and unicodedata.normalize("NFC", "\n".join(cuerpos[k])) == cuerpo), None)
    if casa is None:
        motivo = ("falta la propuesta de la versión devuelta, y la decisión DEVUELTA guardó version_devuelta"
                  if resumen is not None and lineas is None else
                  "no es el que compone el código (requisitos, comentarios de la DEVUELTA y propuesta devuelta, en ese "
                  "orden y con esas líneas)")
        c.falla(f"{bid}: el brief de la ronda 1 de la versión {b.get('version')} {motivo} (REVERIF17-4, PR17-6)")
    elif casa == "propuesta_formato_1":
        c.nota(f"{bid}: propuesta devuelta con la composición de los arreglos de I1.7 (cantidades sin unidad; anterior a "
               "REVERIF17-5): casa entera con la recompuesta")
    elif casa != "vigente":
        c.nota(f"{bid}: brief guardado antes de PR17-6 ({casa}), sin version_devuelta en la decisión: casa entero")


def _propuesta_devuelta_en_brief(ctx: Contexto, c: Comprobacion, b: dict, cuerpo: str) -> None:
    """PR17-6 (arreglos I1.7): «Propuesta de la versión X devuelta» solo en la ronda 1 de una versión abierta por una
    DEVUELTA, con las líneas que compone el núcleo desde `version_devuelta` de esa decisión (recompuestas en local).
    REVERIF17-4 (I1.8): en la ronda 1 de la versión vigente se compara además el cuerpo entero (_cuerpo_ronda_1_vigente):
    quitar o mover la sección ya no pasa."""
    lineas, bid, v = lineas_seccion(cuerpo, ("## Propuesta de la versión",)), b.get("brief_id"), b.get("version")
    if lineas is not None and (not isinstance(v, str) or len(v) != 1 or not "B" <= v <= "Z" or b.get("ronda") != 1):
        c.falla(f"{bid}: lleva la propuesta de una versión devuelta y no es la ronda 1 de una versión abierta por una "
                "DEVUELTA (PR17-6)")
        return
    if b.get("ronda") == 1 and v == (getattr(ctx, "estado", None) or {}).get("version"):
        _cuerpo_ronda_1_vigente(ctx, c, b, cuerpo, lineas)
        return
    if lineas is None:
        return
    br, anon = _nucleo("brief"), anonimizador_brief(ctx)
    if br is None or not hasattr(br, "lineas_propuesta_devuelta") or anon is None:
        c.aviso(f"{bid}: la propuesta de la versión devuelta está, pero no se ha podido recomponer en local (falta la "
                "transcripción F1 o el núcleo del repositorio): contenido no contrastado (PR17-6)")
        return
    estado = dict(getattr(ctx, "estado", None) or {}, version=v)
    try:
        inst = _instantanea_de_confianza(ctx)
        esperadas = [[unicodedata.normalize("NFC", x) for x in br.lineas_propuesta_devuelta(estado, anon, **kw)]
                     for kw in ({"instantanea": inst}, {"formato": 1})]   # REVERIF17-5: también la composición de I1.7
    except TypeError:   # núcleo anterior a REVERIF17-5
        esperadas = [[unicodedata.normalize("NFC", x) for x in br.lineas_propuesta_devuelta(estado, anon)]]
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"{bid}: no se pudo recomponer la propuesta de la versión devuelta: {type(e).__name__}: {e} (PR17-6)")
        return
    if [x for x in lineas if x.strip()] not in esperadas:
        c.falla(f"{bid}: la propuesta de la versión devuelta no es la que compone el código desde la decisión DEVUELTA "
                f"({len(lineas)} líneas frente a {len(esperadas[0])}; PR17-6)")


def lineas_devuelta_esperadas(ctx: Contexto, dev: list[dict]) -> list[str] | None:
    """Las líneas que el núcleo escribe para cada comentario de DEVUELTA (brief.generar): el comentario anonimizado con
    los términos del alta y los hablantes de la transcripción local (F1, comprobada por su SHA-256), con el módulo del
    repositorio. None si no se puede recomponer (sin transcripción, sin núcleo o F1 distinta)."""
    br, sf, hs = _nucleo("brief"), _nucleo("suficiencia"), _nucleo("hashes")
    alta = ctx.carga.get("alta") or {}
    texto = texto_del_alta_local(ctx, sf, hs) if br is not None and sf is not None and hs is not None else None
    if texto is None:   # notas del comercial: hablantes de la reunión y de las notas, como el núcleo
        return None
    sens, cliente = list(alta.get("terminos_sensibles") or []), [alta.get("cliente") or "", alta.get("codigo_cliente") or ""]
    personas = sf.hablantes(texto)
    if hasattr(br, "terminos_anonimizacion"):   # VER15-7 (I1.6): también los nombres de quienes firman decisiones
        sens, cliente, personas = br.terminos_anonimizacion({"terminos_sensibles": sens, "cliente": cliente[0],
                                                             "codigo_cliente": cliente[1]}, personas)
    return ["- " + " ".join(br.anonimizar(d.get("comentarios") or "", sens, cliente, personas).split()) for d in dev]


def _comentarios_devuelta_en_brief(ctx: Contexto, c: Comprobacion, b: dict, cuerpo: str) -> None:
    """PR14-6 (I1.5): el brief de una versión abierta por una DEVUELTA lleva, una línea por decisión, los comentarios
    del revisor anonimizados por el núcleo. Se recomponen esas líneas en local (LES-G-097.2) y se comparan; si no se
    pueden recomponer, se comprueba la sección y su número de líneas y se avisa."""
    v, bid = b.get("version"), b.get("brief_id")
    if not isinstance(v, str) or len(v) != 1 or not "B" <= v <= "Z":
        return
    previa = chr(ord(v) - 1)
    dev = [d for d in (getattr(ctx, "estado", None) or {}).get("decisiones") or []
           if isinstance(d, dict) and d.get("tipo") == "DEVUELTA" and d.get("version") == previa]
    if not dev:
        return
    lineas = cuerpo.split("\n")
    cab = [i for i, ln in enumerate(lineas)
           if ln.startswith(f"## Comentarios de la revisión de la versión {previa} (DEVUELTA")]
    sig = lineas[cab[0] + 1:cab[0] + 1 + len(dev)] if len(cab) == 1 else []
    detras = lineas[cab[0] + 1 + len(dev)] if len(cab) == 1 and len(lineas) > cab[0] + 1 + len(dev) else None
    if len(cab) != 1 or len(sig) != len(dev) or not all(ln.startswith("- ") and ln[2:].strip() for ln in sig):
        c.falla(f"{bid}: la versión {v} sale de una DEVUELTA de la {previa} y el brief no lleva sus {len(dev)} "
                "comentario(s) (PR14-6): el experto repetiría el análisis sin saber por qué se devolvió")
        return
    if detras is not None and not detras.startswith("## "):   # Revisión (2.ª pasada): ni una línea más en la sección
        c.falla(f"{bid}: la sección de la DEVUELTA lleva más líneas que decisiones ({len(dev)}): {detras[:120]!r} "
                "no sale de ninguna decisión (PR14-6)")
        return
    esperadas = lineas_devuelta_esperadas(ctx, dev)
    if esperadas is None:
        c.aviso(f"{bid}: la sección de la DEVUELTA está, pero su texto no se ha podido recomponer en local (falta la "
                "transcripción F1 o el núcleo del repositorio): contenido no contrastado (PR14-6)")
    elif sig != [unicodedata.normalize("NFC", x) for x in esperadas]:
        n = next(i for i, (a, e) in enumerate(zip(sig, esperadas)) if a != unicodedata.normalize("NFC", e))
        c.falla(f"{bid}: el comentario {n + 1} de la DEVUELTA no es el de la decisión {dev[n].get('id')} anonimizado "
                f"(PR14-6): el brief dice {sig[n][:120]!r}")



# ─────────── I1.7: datos de control del brief atados a su texto sellado (REVERIF16-2 y PR16-6) ───────────
SECCIONES_PRECIOS_BRIEF = ("## Precios conservados", "## Precios ya verificados")
_ID_LINEA_REPLICA = re.compile(r"^((?:REF|C|P)-\d{2}) \|")
_RX_PLANTILLA_BRIEF = re.compile(r" \| plantilla: ([^|]+?)(?: \||$)")
_RX_FILTRO_BRIEF = re.compile(r" \| filtro: (.+?) \| unidad: ")
_RX_CANTIDAD_BRIEF = re.compile(r" \| cantidad_mensual: ([^|]+?)(?: \||$)")
_SEIS = Decimal("0.000001")


def contenido_linea_replica(linea: object) -> str:
    """Réplica de nucleo.verificacion.contenido_linea: la línea sin su id y con los espacios normalizados."""
    t = " ".join(str(linea or "").split())
    m = _ID_LINEA_REPLICA.match(t)
    return t[m.end():].strip() if m else ""


def aceptados_replica(brief: dict | None) -> set[str]:
    """Contenidos de línea que el brief da por aceptados (PR16-6; réplica de verificacion.aceptados_de_brief)."""
    return {" ".join(a["linea"].split()) for a in (brief or {}).get("aceptados") or []
            if isinstance(a, dict) and isinstance(a.get("linea"), str) and a.get("veredicto") in ("OK", "OBSERVACION", "REPARADO")}


def lineas_seccion(cuerpo: str, prefijos: tuple[str, ...]) -> list[str] | None:
    """Líneas de la sección cuyo encabezado empieza por uno de los prefijos, hasta el siguiente «## »; None sin ella."""
    lineas, dentro, salida = cuerpo.split("\n"), False, None
    for ln in lineas:
        if ln.startswith("## "):
            dentro = ln.startswith(prefijos)
            if dentro and salida is None:
                salida = []
            continue
        if dentro:
            salida.append(ln)
    return salida


def _cantidad_replica(x: object) -> Decimal | None:
    if x is None or str(x).strip() in ("None", "null"):
        return None
    if isinstance(x, bool):
        raise ValueError(f"cantidad booleana: {x!r}")
    d = Decimal(str(x).strip())
    if not d.is_finite():
        raise ValueError(f"cantidad no finita: {x!r}")
    return d


def _sumar_replica(valores: list) -> Decimal | None:
    total = Decimal(0)
    for v in valores:
        if v is None:
            return None
        total += v
    return total


def efecto_desde_texto(lineas: list[str]) -> dict[tuple, Decimal | None]:
    """(«plantilla»|«filtro», valor) -> cantidad mensual total, leído de las líneas P- de la sección de precios del
    brief. ValueError si una línea P- no trae plantilla o filtro y cantidad_mensual."""
    grupos: dict[tuple, list] = {}
    for ln in lineas:
        if not ln.startswith("- P-"):
            continue
        mp, mf, mc = _RX_PLANTILLA_BRIEF.search(ln), _RX_FILTRO_BRIEF.search(ln), _RX_CANTIDAD_BRIEF.search(ln)
        if not (mp or mf) or not mc:
            raise ValueError(f"línea de precio sin plantilla o filtro y cantidad_mensual: {ln[:120]!r}")
        clave = ("plantilla", mp.group(1).strip()) if mp else ("filtro", " ".join(mf.group(1).split()))
        grupos.setdefault(clave, []).append(_cantidad_replica(mc.group(1)))
    return {k: _sumar_replica(v) for k, v in grupos.items()}


def efecto_desde_conservar(items: list) -> dict[tuple, Decimal | None]:
    """Lo mismo desde conservar_precios (forma de I1.7 o de I1.6), sin catalogo_id (el texto no lo lleva)."""
    grupos: dict[tuple, list] = {}
    for it in items:
        it = it if isinstance(it, dict) else {}
        clave = (("plantilla", str(it.get("plantilla_id")).strip()) if it.get("plantilla_id")
                 else ("filtro", " ".join(str(it.get("filtro") or "").split())))
        grupos.setdefault(clave, []).append(_cantidad_dato(it.get("cantidad_mensual")))
    return {k: _sumar_replica(v) for k, v in grupos.items()}


def _iguales_replica(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a.quantize(_SEIS) == b.quantize(_SEIS)


def _conservar_atado_al_texto(c: Comprobacion, b: dict, cuerpo: str) -> None:
    """REVERIF16-2: conservar_precios (dato de control) dice lo mismo que las líneas P- del texto sellado del brief:
    mismas plantillas o filtros y la misma cantidad total de cada una. Una lista vacía con líneas en el texto, o al
    revés, FALLA."""
    bid, lineas = b.get("brief_id"), lineas_seccion(cuerpo, SECCIONES_PRECIOS_BRIEF)
    conservar = b.get("conservar_precios")
    if lineas is None and not conservar:
        return
    if not isinstance(conservar, list):
        c.falla(f"{bid}: el texto lleva precios que conservar y conservar_precios no es una lista (REVERIF16-2)")
        return
    try:
        texto, dato = efecto_desde_texto(lineas or []), efecto_desde_conservar(conservar)
    except (ValueError, ArithmeticError) as e:
        c.falla(f"{bid}: conservar_precios o su sección del texto no se pueden leer: {e} (REVERIF16-2)")
        return
    if set(texto) != set(dato) or not all(_iguales_replica(texto[k], dato[k]) for k in texto):
        c.falla(f"{bid}: conservar_precios no es lo que dice el texto sellado del brief (texto {sorted(texto)}, dato "
                f"{sorted(dato)}): el dato de control no casa con lo enviado (REVERIF16-2)")


def _aceptados_atados_al_texto(ctx: Contexto, c: Comprobacion, b: dict) -> None:
    """PR16-6: lo que el brief da por aceptado (y que el consolidado ya no envía) tiene que figurar en «Elementos ya
    verificados» del texto sellado de un brief de la misma versión hasta esta ronda (lo NO VERIFICABLE va en «Elementos
    sin verificar» y no vale; Revisión, I1.7); en la ronda 1, nada."""
    aceptados, bid = b.get("aceptados"), b.get("brief_id")
    if not isinstance(aceptados, list) or not aceptados:
        return
    if b.get("ronda") == 1:
        c.falla(f"{bid}: un brief de la ronda 1 no puede traer elementos aceptados (PR16-6)")
        return
    vistos = set()
    for x in ctx.carga.get("briefs") or []:
        if isinstance(x, dict) and x.get("version") == b.get("version") and (x.get("ronda") or 0) <= (b.get("ronda") or 0):
            cuerpo_x = str(x.get("texto") or "").partition("\n---\n")[2]
            verificados = lineas_seccion(cuerpo_x, ("## Elementos ya verificados",)) or []
            vistos |= {contenido_linea_replica(ln[2:]) for ln in verificados if ln.startswith(("- REF-", "- C-"))}
    for a in aceptados:
        linea = " ".join(str((a or {}).get("linea") or "").split()) if isinstance(a, dict) else ""
        if not linea or linea not in vistos:
            c.falla(f"{bid}: el elemento aceptado {linea[:100]!r} no figura como conservado en ningún brief de la "
                    f"versión {b.get('version')} (PR16-6): no se puede heredar sin verificar")


def http_get_real(url: str) -> tuple[int, str, str]:
    """GET con redirecciones; (estado, URL final, primeros 300 KB). Un solo reintento ante DNS."""
    import requests
    cab = {"User-Agent": "verificar_paquete/1 (preventa Devoteam)", "Accept-Language": "es-ES,es;q=0.9"}
    for intento in (1, 2):
        try:
            r = requests.get(url, headers=cab, timeout=25, allow_redirects=True)
            return r.status_code, r.url, r.content[:300_000].decode("utf-8", errors="replace")
        except requests.ConnectionError as e:
            if intento == 2 or "NameResolution" not in str(e) and "getaddrinfo" not in str(e):
                raise
            subprocess.run(["nslookup", "learn.microsoft.com"], capture_output=True, timeout=20)
    raise RuntimeError("inalcanzable")


_SOFT404 = re.compile(r"\b404\b|not found|no se (ha )?encontr|p[aá]gina no encontrada|page doesn.t exist", re.I)


def c_referencias_vivas(ctx: Contexto) -> Comprobacion:
    """P3 · Referencias vivas: cada URL responde 200 con título y sin soft 404."""
    c = Comprobacion("referencias_vivas", c_referencias_vivas.__doc__.split("·")[1].strip())
    if ctx.sin_red:
        c.no_verificado("--sin-red: no se han comprobado las URL de referencia")
        return c
    get = ctx.http_get or http_get_real
    for ref in ctx.respuesta.get("referencias", []):
        url = ref.get("url", "")
        try:
            estado, final, cuerpo = get(url)
        except Exception as e:  # noqa: BLE001 - se informa, no se aprueba
            c.falla(f"{ref.get('id')}: {url} inalcanzable ({type(e).__name__}: {str(e)[:160]})")
            continue
        m = re.search(r"<title[^>]*>(.*?)</title>", cuerpo, re.S | re.I)
        titulo = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        ruta_final = _norm_url(final)
        if estado != 200:
            c.falla(f"{ref.get('id')}: HTTP {estado} en {url}")
        elif not titulo:
            c.falla(f"{ref.get('id')}: respuesta sin título en {url}")
        elif _SOFT404.search(titulo) or (ruta_final or "").endswith("/404"):
            c.falla(f"{ref.get('id')}: soft 404 («{titulo[:80]}») en {url}")
        elif not (_prefijo(ruta_final, PREF_ARQ) or _prefijo(ruta_final, PREF_SERV)):
            c.falla(f"{ref.get('id')}: redirige fuera de la lista blanca: {final}")
        else:
            if ruta_final != _norm_url(url):
                c.aviso(f"{ref.get('id')}: redirige a {final}")
            c.nota(f"{ref.get('id')}: 200 «{titulo[:90]}»")
    return c


# CMP-1 (I1.3): réplica de nucleo.verificacion (MARCA_TENANT, FUENTES_RESIDENCIA_TENANT, valor_es_lo_enviado y
# es_residencia_tenant), con su propio código; prueba de igualdad en tests/test_i13_convergencia.py.
MARCA_TENANT = "(residencia de datos: geografía del tenant del cliente; no es una región de Azure)"
FUENTES_RESIDENCIA_TENANT = ("/microsoft-365/enterprise/m365-dr-", "/microsoft-365/enterprise/o365-data-locations",
                             "/entra/fundamentals/data-residency")
# I1.4 (P3, ARR13-4, REV13-1 y EA-3): réplica de nucleo.verificacion (SAAS_TENANT_NOMBRES, CAMPOS_DISCREPA,
# ECO_LINEAS, es_saas_tenant, valor_es_lo_enviado, es_residencia_tenant, lineas_eco y errores_eco), con su propio
# código; prueba de igualdad en tests/test_i14_p3_verificacion.py. Las respuestas anteriores a I1.4 (elementos sin
# «campo», es_contrato_v2) se validan con historico/respuesta_verificador_v2 y FALLAN (puerta de su época).
SAAS_TENANT_NOMBRES = (
    "sharepoint", "sharepointonline", "microsoftsharepoint", "microsoftsharepointonline", "sharepointinmicrosoft365",
    "sharepointenmicrosoft365", "onedrive", "onedriveforbusiness", "onedriveparalaempresa", "microsoftonedrive",
    "microsoftonedriveforbusiness", "exchangeonline", "microsoftexchangeonline", "microsoft365", "office365",
    "microsoftoffice365", "teams", "microsoftteams", "entraid", "microsoftentraid")
CAMPOS_DISCREPA = {"referencia": ("url", "titulo"),
                   "componente": ("nombre", "sku", "region", "referencia", "cantidad", "motivo"),  # I1.7 (E §3.5)
                   "precio": ("componente", "filtro", "precio", "unidad", "region", "effectiveStartDate",
                              "cantidad")}  # I1.6: factor de volumen (CAMBIOS-I16-E §3.3)
ECO_LINEAS = 3
_LINEA_C = re.compile(r"^(?:C-\d{2}) \| (?P<nombre>.*?) \| sku: (?P<sku>.*?) \| region: (?P<region>\S+)(?P<resto>.*?)"
                      r" \| referencia: (?P<ref>\S+)$")
_LINEA_REF = re.compile(r"^(?:REF-\d{2}) \| (?P<url>\S+) \| (?P<titulo>.*)$")


def lineas_consolidado(texto: str) -> dict[str, str]:
    """id -> línea del consolidado (las que empiezan por «REF-nn |», «C-nn |» o «P-nn |»)."""
    salida = {}
    for ln in (texto or "").split("\n"):
        m = re.match(r"^((?:REF|C|P)-\d{2}) \|", ln)
        if m:
            salida[m.group(1)] = ln
    return salida


def es_contrato_v2(resp: object) -> bool:
    """Respuesta del verificador anterior a I1.4: tiene elementos y ninguno lleva la clave «campo»."""
    elementos = resp.get("elementos") if isinstance(resp, dict) else None
    return (isinstance(elementos, list) and bool(elementos)
            and not any(isinstance(e, dict) and "campo" in e for e in elementos))


def _valor_compacto(valor_correcto: object) -> str:
    if not isinstance(valor_correcto, str):
        return ""
    return _compacto(re.sub(r"^\s*t[ií]tulo\s*:\s*", "", valor_correcto, flags=re.IGNORECASE))


def valor_es_lo_enviado(linea: str, valor_correcto: object, campo: object) -> bool:
    """ARR13-4: el valor «correcto» de una DISCREPA es lo enviado EN EL CAMPO QUE DISCUTE: «nombre» en la línea de un
    componente del catálogo (nunca una desviación) o «titulo» en la de una referencia; forma compacta e igualdad exacta."""
    vc = _valor_compacto(valor_correcto)
    if not vc:
        return False
    m = _LINEA_C.match(linea or "")
    if m:
        return (campo == "nombre" and not m.group("nombre").startswith("desviación: ")
                and vc == _compacto(m.group("nombre")))
    m = _LINEA_REF.match(linea or "")
    return campo == "titulo" and bool(m) and vc == _compacto(m.group("titulo"))


def es_saas_tenant(nombre: str) -> bool:
    """REV13-1: «desviación: X» con X, en forma compacta, IGUAL a un nombre de SAAS_TENANT_NOMBRES."""
    prefijo = "desviación: "
    return nombre.startswith(prefijo) and _compacto(nombre[len(prefijo):]) in SAAS_TENANT_NOMBRES


def _residencia_tenant_linea(linea: str, fuente_url: object) -> bool:
    m = _LINEA_C.match(linea or "")
    if not m or m.group("region") != "global":
        return False
    if MARCA_TENANT not in m.group("resto") and not es_saas_tenant(m.group("nombre")):
        return False
    ruta = _norm_url(fuente_url) if isinstance(fuente_url, str) else None
    if not ruta:
        return False
    return any(ruta.startswith(p) if p.endswith("-") else (ruta == p or ruta.startswith(p + "/"))
               for p in FUENTES_RESIDENCIA_TENANT)


def es_residencia_tenant(linea: str, fuente_url: object, campo: object) -> bool:
    """DISCREPA de la región (campo «region») de un componente en «global» con la marca de residencia por tenant (o
    desviación de un SaaS de la lista cerrada) y una fuente de Learn de residencia por geografía del tenant."""
    return campo == "region" and _residencia_tenant_linea(linea, fuente_url)


def lineas_eco(texto: object) -> list[str]:
    return [ln for ln in (" ".join(x.split()) for x in str(texto or "").splitlines()) if ln]


def errores_eco(eco: object, enviado: str) -> list[str]:
    """EA-3: las ECO_LINEAS primeras líneas completas de lo enviado (o más, enteras y en orden), línea a línea."""
    recibidas, enviadas = lineas_eco(eco), lineas_eco(enviado)
    if len(recibidas) < ECO_LINEAS:
        return [f"el eco trae {len(recibidas)} línea(s) y debe traer las {ECO_LINEAS} primeras completas"]
    if len(recibidas) > len(enviadas):
        return ["el eco trae más líneas de las que tiene lo enviado"]
    for n, (r, s) in enumerate(zip(recibidas, enviadas), start=1):
        if r != s:
            return [f"la línea {n} del eco no es la línea {n} literal de lo enviado"]
    return []


_LINEA_C_R = re.compile(r"^(?:C-\d{2}) \| (?P<nombre>.*?) \| sku: (?P<sku>.*?) \| region: (?P<region>\S+)(?P<resto>.*?)"
                        r" \| referencia: (?P<ref>\S+)$")


def _region_compacta_r(r: object) -> str:
    return re.sub(r"[\s_-]+", "", r).lower() if isinstance(r, str) else ""


def disponibilidad_catalogo_replica(comp: dict, precios: list, catalogo: dict | None) -> tuple[str, list[str], str] | None:
    """VC18-3 (I1.9): réplica de nucleo.verificacion.disponibilidad_catalogo: (nivel, regiones compactas, fuente) en que
    el catálogo publica disponible el nivel que usa el componente; None si no lo declara con fuente válida de Learn o el
    nivel no es único (dirección segura: la DISCREPA se queda)."""
    fila = next((x for x in (catalogo or {}).get("componentes") or [] if isinstance(x, dict) and isinstance(comp, dict)
                 and comp.get("catalogo_id") and x.get("id") == comp.get("catalogo_id")), None)
    disp = fila.get("disponibilidad") if isinstance(fila, dict) else None
    if not isinstance(disp, dict) or not disp:
        return None
    niveles = _niveles_r(fila)
    usadas = {x.get("plantilla_id") for x in precios or [] if isinstance(x, dict) and x.get("componente_id") == comp.get("id")}
    if not niveles:   # por modelo (Foundry): el de las plantillas usadas o, sin precios, el sku exacto
        modelos = {p.get("modelo") for p in fila.get("plantillas_precio") or []
                   if isinstance(p, dict) and p.get("id") in usadas and isinstance(p.get("modelo"), str)}
        nombres = {_plano_req_replica(m) for m in modelos} if usadas else {_plano_req_replica(comp.get("sku"))}
        niveles = [{"nombres": sorted(nombres - {""}), "plantillas": usadas or None}] if len(nombres - {""}) == 1 else []
    candidatos = [n for n in niveles if n["plantillas"] and usadas & n["plantillas"]]
    if not candidatos and not usadas:
        nombres = {_plano_req_replica(_obj_replica(comp.get("justificacion_nivel")).get("nivel")),
                   _plano_req_replica(comp.get("sku"))} - {""}
        candidatos = [n for n in niveles if nombres & set(n["nombres"])]
        if not candidatos:   # como experto.nivel_por_defecto: solo {nivel, fuente https}; una cadena o sin fuente, no
            nd = _obj_replica(fila.get("nivel_por_defecto"))
            nombre = _plano_req_replica(nd.get("nivel"))
            f_nd = next((" ".join(v.split()) for v in (nd.get("fuente"), nd.get("fuente_url"))
                         if isinstance(v, str) and v.strip()), "")
            candidatos = [n for n in niveles if nombre and nombre in n["nombres"]][:1] if f_nd.startswith("https://") else []
    if len(candidatos) != 1:
        return None
    claves = [k for k in disp if _plano_req_replica(k) in candidatos[0]["nombres"]]
    if len(claves) != 1:
        return None
    valor = disp[claves[0]]

    def fuente_de(v):
        if isinstance(v, str):
            return v
        return fuente_de(v.get("url") or v.get("fuente_url")) if isinstance(v, dict) else None
    regiones = valor.get("regiones") if isinstance(valor, dict) else valor
    fuente = fuente_de(valor.get("fuente_url") or valor.get("fuente")) if isinstance(valor, dict) else None
    fuente = fuente or fuente_de(fila.get("disponibilidad_fuente_url") or fila.get("disponibilidad_fuente"))
    if not isinstance(regiones, list) or not all(isinstance(x, str) for x in regiones) or not _fuente_learn_r(fuente):
        return None
    return claves[0], [_region_compacta_r(x) for x in regiones], fuente


def _fuente_learn_r(url: object) -> bool:
    """Réplica de experto.normalizar_url(url) != "" (Revisión, 2.ª pasada de I1.9): https, host learn.microsoft.com, sin
    puerto ni «@», y la ruta, ya decodificada, con algún segmento tras el de idioma y ninguno «.» o «..» («%2e%2e»)."""
    from urllib.parse import unquote, urlsplit
    if not isinstance(url, str) or _norm_url(url) is None:
        return False
    segmentos = [s for s in unquote(urlsplit(url.strip()).path).lower().split("/") if s]
    if any(s in (".", "..") for s in segmentos):
        return False
    if segmentos and re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})+", segmentos[0]):
        segmentos = segmentos[1:]
    return bool(segmentos)


def region_disponible_replica(linea: str, comp: dict | None, precios: list, catalogo: dict | None) -> bool:
    """VC18-3: la región de la línea del componente está entre las que el catálogo publica para su nivel (con fuente)."""
    m = _LINEA_C_R.match(linea or "")
    if not m or not isinstance(comp, dict):
        return False
    disp = disponibilidad_catalogo_replica(comp, precios, catalogo)
    region = _region_compacta_r(m.group("region"))
    return disp is not None and bool(region) and region in disp[1]


def evaluar_verificacion(ctx: Contexto) -> tuple[list[str], list[str], list[str], list[str]]:
    """§7.3 recalculado: (DISCREPA efectivos, NO VERIFICABLE, reparados, DISCREPA que pasan a OBSERVACION).
    VC18-3 (I1.9): un DISCREPA del campo «region» de un componente cuya región el catálogo publica para su nivel pasa a
    OBSERVACION (la puerta usa siempre el catálogo de confianza)."""
    resp = (ctx.carga.get("verificacion") or {}).get("respuesta") or {}
    comps = {x.get("id"): x for x in ctx.respuesta.get("componentes", []) if isinstance(x, dict)}
    refs = {x.get("id"): x for x in ctx.respuesta.get("referencias", [])}
    precios = {x.get("id"): x for x in ctx.respuesta.get("precios", [])}
    lineas = lineas_consolidado((ctx.carga.get("consolidado") or {}).get("texto", ""))
    aceptados = aceptados_replica(_brief_vigente(ctx))
    discrepa, nov, reparados, observaciones = [], [], [], []
    for el in resp.get("elementos", []):
        eid, ver, vc = el.get("id"), el.get("veredicto"), el.get("valor_correcto")
        campo, linea = el.get("campo"), lineas.get(el.get("id"), "")
        dif = None
        if eid in precios and vc is not None:
            try:
                base = dec(precios[eid].get("precio"))
                dif = abs(dec(vc) - base) / base if base else (Decimal(0) if dec(vc) == 0 else Decimal(1))
            except ValueError:
                dif = None
        if dif is not None and dif > Decimal("0.005"):
            discrepa.append(f"{eid}: diferencia de precio {q2(dif * 100)} % (> 0,5 %)")
        elif ver == "DISCREPA":
            # ARR13-4: solo cuenta el campo declarado; sin «campo» no se repara ni se reclasifica nada.
            if (campo == "url" and eid in refs and vc and _norm_url(vc)
                    and _norm_url(vc) == _norm_url(refs[eid].get("url", ""))):
                reparados.append(eid)
            elif dif is not None and dif != 0 and campo == "precio":
                reparados.append(eid)
            elif (eid not in precios and _fuente_permitida(el.get("fuente_url"), False)
                  and (valor_es_lo_enviado(linea, vc, campo) or es_residencia_tenant(linea, el.get("fuente_url"), campo))):
                observaciones.append(eid)
            elif campo == "region" and eid not in precios and region_disponible_replica(
                    linea, comps.get(eid), ctx.respuesta.get("precios") or [], ctx.catalogo_obj):
                observaciones.append(eid)   # VC18-3 (I1.9): contradice la disponibilidad publicada en el catálogo
            elif contenido_linea_replica(linea) in aceptados:
                observaciones.append(eid)   # PR16-6 (I1.7): ya aceptado en una ronda anterior y sin cambios
            else:
                discrepa.append(f"{eid}: DISCREPA ({(el.get('detalle') or '')[:100]})")
        elif ver == "NO VERIFICABLE":
            nov.append(eid)
    return discrepa, nov, reparados, observaciones


_FUENTE_PRECIOS = "https://prices.azure.com/api/retail/prices"


def _fuente_permitida(url: object, es_precio: bool) -> bool:
    """Misma regla que nucleo.verificacion._fuente_valida, con la réplica local de la lista blanca."""
    if not isinstance(url, str) or not url:
        return False
    if _prefijo(_norm_url(url), PREF_ARQ + PREF_SERV):
        return True
    return es_precio and url.split("?")[0].rstrip("/").lower() == _FUENTE_PRECIOS


def _comprobar_contrato_y_lotes(c: Comprobacion, ctx: Contexto, cons: dict, ver: dict, resp: dict) -> None:
    """Todo DISCREPA trae valor_correcto y una fuente permitida. Con lotes, cada respuesta de lote es un
    veredicto por id del lote, con el eco de su comienzo, y la respuesta combinada es la de los lotes."""
    precios = {x.get("id") for x in ctx.respuesta.get("precios", [])}
    for e in resp.get("elementos", []):
        if e.get("veredicto") == "DISCREPA" and (not str(e.get("valor_correcto") or "").strip()
                                                 or not _fuente_permitida(e.get("fuente_url"), e.get("id") in precios)):
            c.falla(f"{e.get('id')}: DISCREPA sin valor_correcto o sin una fuente permitida (LES-G-096)")
    if es_contrato_v2(resp) and not es_version_a(cons, resp):
        # Revisión (I1.4): la forma «sin campo» se fabrica quitando una clave y resellando; no se le aplican las reglas
        # viejas (reclasificación sin campo, eco por caracteres). Como con la versión A: se verifica con la puerta de
        # su época.
        c.falla("respuesta del verificador del contrato anterior a I1.4 (elementos sin «campo»): esta puerta no la "
                "juzga con las reglas viejas; un paquete anterior a I1.4 se verifica con la puerta de su época")
    for e in resp.get("elementos", []):
        if e.get("veredicto") == "DISCREPA" and e.get("campo") not in CAMPOS_DISCREPA.get(e.get("tipo"), ()):
            c.falla(f"{e.get('id')}: DISCREPA sin el campo discutido de su tipo (ARR13-4)")
    if es_version_a(cons, resp):
        c.nota("paquete de la versión A: contrato anterior del verificador, sin lotes")
        return
    lotes = cons.get("lotes") or []
    enviados = [i for x in lotes for i in (x.get("ids") or [])]
    # PR16-6 (I1.7): los lotes llevan lo nuevo o cambiado, en el orden del consolidado y sin repetir; lo demás se
    # hereda y tiene que estar aceptado en el brief vigente (y ese dato, atado a su texto en c_brief).
    if (len(enviados) != len(set(enviados)) or [i for i in cons.get("ids") or [] if i in set(enviados)] != enviados
            or (lotes and not enviados)):
        c.falla("los lotes no son una partición ordenada de ids del consolidado")
    aceptados = aceptados_replica(_brief_vigente(ctx))
    lineas = lineas_consolidado(cons.get("texto", ""))
    for i in [i for i in cons.get("ids") or [] if i not in set(enviados)] if lotes else []:
        if contenido_linea_replica(lineas.get(i, "")) not in aceptados:
            c.falla(f"{i}: no se envió al verificador y el brief vigente no lo da por aceptado en una ronda anterior "
                    "(PR16-6): un elemento sin veredicto no se hereda")
    usados = ver.get("lotes") or []
    if not usados:
        if any(x.get("respuesta") is not None for x in lotes):
            c.falla("hay lotes con respuesta, pero la verificación dice que llegó una respuesta completa")
        return
    if usados != [x.get("lote_id") for x in lotes]:
        c.falla(f"verificacion.lotes no son los lotes del consolidado: {usados}")
        return
    por_id = {}
    for x in lotes:
        lid, lt, r = x.get("lote_id"), x.get("texto", ""), x.get("respuesta") or {}
        ids_r = [e.get("id") for e in r.get("elementos", [])]
        if r.get("consolidado_id") != lid or sorted(ids_r) != sorted(x.get("ids") or []) or len(ids_r) != len(set(ids_r)):
            c.falla(f"{lid}: la respuesta del lote no es un veredicto por cada id del lote")
        for error in errores_eco(r.get("entrada_recibida_inicio"), lt):
            c.falla(f"{lid}: entrada_recibida_inicio: {error} (EA-3)")
        por_id.update({e.get("id"): e for e in r.get("elementos", [])})
    if [por_id.get(i) for i in enviados] != resp.get("elementos"):
        c.falla("la respuesta combinada no es la de los lotes registrados")


def _recomponer_consolidado(ctx: Contexto, c: Comprobacion) -> None:
    """LES-G-097.2 y .4: el consolidado y sus lotes se recomponen en local desde la respuesta del experto y el
    catálogo de confianza (nucleo.verificacion.componer_consolidado) y deben ser idénticos. Detecta una línea
    cambiada y resellada a la vez en el consolidado y en su lote. Los paquetes de la versión A no se recomponen."""
    cons = ctx.carga.get("consolidado") or {}
    resp = (ctx.carga.get("verificacion") or {}).get("respuesta") or {}
    if es_version_a(cons, resp):
        # Revisión (integración I1.1): la forma «versión A» se fabrica quitando dos campos y resellando, y saltaría
        # esta recomposición. El núcleo de I1.1 escribe siempre «lotes»; un paquete de A tampoco recompone sus
        # textos ni su PPTX con este núcleo (FALLA igualmente), así que aquí no hay nada legítimo que eximir.
        c.falla("consolidado sin lotes ni precios_azure (forma de la versión A, anterior a I1.1): esta puerta no lo "
                "puede recomponer; un paquete de A se verifica con la puerta de su época (lo empezado en A se "
                "termina en A)")
        return
    rec = _nucleo("verificacion").componer_consolidado(ctx.estado, ctx.catalogo_obj, cons.get("consolidado_id"))
    if rec.texto != cons.get("texto") or list(rec.ids) != list(cons.get("ids") or []):
        c.falla("consolidado: no es el que se recompone en local desde la respuesta del experto")
    elif [(x.lote_id, x.texto, x.sha256, list(x.ids)) for x in rec.lotes] != \
            [(x.get("lote_id"), x.get("texto"), x.get("sha256"), list(x.get("ids") or [])) for x in cons.get("lotes") or []]:
        c.falla("consolidado: los lotes no son los que se recomponen en local")
    else:
        c.nota(f"consolidado {cons.get('consolidado_id')} y sus {len(rec.lotes)} lotes: idénticos al recompuesto en local")


def c_verificacion(ctx: Contexto) -> Comprobacion:
    """P5 · Verificación: un veredicto por id del consolidado y cero DISCREPA efectivos."""
    c = Comprobacion("verificacion", c_verificacion.__doc__.split("·")[1].strip())
    cons, ver = ctx.carga.get("consolidado") or {}, ctx.carga.get("verificacion") or {}
    resp = ver.get("respuesta") or {}
    if not cons or not resp:
        c.falla("faltan el consolidado o la respuesta del verificador")
        return c
    texto = cons.get("texto", "")
    if sha256_bytes(texto.encode("utf-8")) != cons.get("sha256"):
        c.falla("el SHA-256 del consolidado no es el de su texto")
    ids_texto = re.findall(r"^((?:REF|C|P|S|RG)-\d{2}) \|", texto, re.M)
    if ids_texto != list(cons.get("ids", [])):
        c.falla(f"los ids del consolidado no son los de su texto: {cons.get('ids')} vs {ids_texto}")
    m = re.search(r"^brief_id: (\S+)$", texto, re.M)
    if not m or m.group(1) != ctx.respuesta.get("brief_id"):
        c.falla("el consolidado no corresponde al brief de la respuesta vigente")
    if resp.get("consolidado_id") != cons.get("consolidado_id") or ver.get("consolidado_id") != cons.get("consolidado_id"):
        c.falla("consolidado_id de la respuesta del verificador distinto del consolidado vigente")
    ids_resp = [e.get("id") for e in resp.get("elementos", [])]
    # PR16-6 (I1.7): con lotes, un veredicto por id ENVIADO; los heredados se comprueban en _comprobar_contrato_y_lotes.
    esperados = ([i for x in cons.get("lotes") or [] for i in (x.get("ids") or [])] if ver.get("lotes")
                 else list(cons.get("ids", [])))
    if sorted(ids_resp) != sorted(esperados) or len(ids_resp) != len(set(ids_resp)):
        c.falla(f"no hay exactamente un veredicto por id enviado al verificador: {sorted(ids_resp)}")
    _comprobar_contrato_y_lotes(c, ctx, cons, ver, resp)
    discrepa, nov, reparados, observaciones = evaluar_verificacion(ctx)
    for d in discrepa:
        c.falla(f"DISCREPA efectivo: {d}")
    for x in nov:
        c.aviso(f"{x}: NO VERIFICABLE (debe figurar como riesgo residual en la nota)")
    for x in reparados:
        c.nota(f"{x}: reparado por equivalencia demostrable")
    guardadas = {o.get("id"): o for o in _observaciones_estado(ctx)}
    elementos = {e.get("id"): e for e in resp.get("elementos", [])}
    for x in observaciones:
        c.aviso(f"{x}: DISCREPA que pasa a OBSERVACION (residencia por tenant, valor igual a lo enviado, elemento ya "
                "aceptado sin cambios o región que el catálogo publica para su nivel; CMP-1, PR16-6 y VC18-3)")
        o, e = guardadas.get(x) or {}, elementos.get(x) or {}
        # Revisión (I1.3): no basta el id; lo guardado para la nota tiene que ser el veredicto que se observa.
        if not o or any(o.get(k) != e.get(k) for k in ("veredicto", "campo", "valor_correcto", "fuente_url", "detalle")):
            c.falla(f"{x}: el estado no lo guarda como observación para la nota del revisor (o no es el veredicto real)")
    return c


def _observaciones_estado(ctx: Contexto) -> list[dict]:
    ver = ctx.carga.get("verificacion") or {}
    return [o for o in ver.get("observaciones") or [] if isinstance(o, dict)]


def _decisiones(ctx: Contexto, tipo: str, version: str | None = None) -> list[dict]:
    return [d for d in ctx.estado.get("decisiones") or []
            if d.get("tipo") == tipo and (version is None or d.get("version") == version)]


# REV-1 / VER14-2 (I1.4): réplica LOCAL de la regla de estimación decidida por el comercial el 10-10-2026
# (nucleo.estimacion.componer_entrada, horas_pm y semanas_fase). Solo las partes que mueven dinero o plazo: tareas
# (PM incluido), fases, Gantt, duración e hitos. Si el núcleo está, su recomposición completa debe dar lo mismo.
PM_PORCENTAJE_REGLA, HORAS_SEMANA_PERFIL_REGLA = Decimal("0.15"), 40
MAX_PM_TECNICAS_REGLA, MAX_PM_REUNIONES_REGLA, MAX_CONTENIDO_GANTT_REGLA = 400, 80, 200
TAREA_PM_REGLA = "Coordinación, seguimiento y reporting"
DESCRIPCION_PM_REGLA = "Planificación, seguimiento del avance, gestión de riesgos y reporting al cliente."
ENTREGABLE_PM_REGLA, CONTENIDO_PM_REGLA = "Informes de seguimiento", "Coordinación y seguimiento"


def _techo(d: Decimal) -> int:
    return int(d.to_integral_value(rounding=ROUND_CEILING))


def regla_estimacion_replica(respuesta: dict, hitos_pago: list) -> dict:
    """{tareas, fases, gantt, duracion_semanas, hitos} que compone la regla. ValueError si faltan horas o tareas."""
    propuestas = [t for t in respuesta.get("tareas_propuestas") or [] if isinstance(t, dict)]
    if not propuestas:
        raise ValueError("no hay tareas_propuestas del experto")
    tareas = [{"id": p.get("id"), "fase": p.get("fase"), "tarea": p.get("tarea"), "perfil": p.get("perfil"),
               "tecnicas_h": p.get("horas_base"), "reuniones_h": p.get("reuniones_h"),
               "descripcion": p.get("descripcion"), "entregable": p.get("entregable")} for p in propuestas]
    fases = list(dict.fromkeys(t["fase"] for t in tareas))
    horas = [dec(t["tecnicas_h"]) + round0(dec(t["tecnicas_h"]) * Decimal("0.2")) + dec(t["reuniones_h"]) for t in tareas]
    tecnicas = sum((dec(t["tecnicas_h"]) for t in tareas), Decimal(0))
    gantt, semana = [], 1
    for f in fases:
        de_fase = [i for i, t in enumerate(tareas) if t["fase"] == f]
        perfiles_fase = len({tareas[i]["perfil"] for i in de_fase})
        n = max(1, _techo(sum((horas[i] for i in de_fase), Decimal(0)) / (HORAS_SEMANA_PERFIL_REGLA * perfiles_fase)))
        nombres = "; ".join(str(tareas[i]["tarea"]) for i in de_fase)
        contenido = nombres if len(nombres) <= MAX_CONTENIDO_GANTT_REGLA else \
            f"{len(de_fase)} tareas de {f}"[:MAX_CONTENIDO_GANTT_REGLA]
        gantt.append({"fase": f, "contenido": contenido, "semanas": list(range(semana, semana + n))})
        semana += n
    duracion = semana - 1
    pm = max(int(PM_MINIMO), _techo(tecnicas * PM_PORCENTAJE_REGLA))
    trozos = max(1, -(-pm // MAX_PM_TECNICAS_REGLA), -(-duracion // MAX_PM_REUNIONES_REGLA))
    for i in range(trozos):
        tareas.append({"id": f"PM-{i + 1:02d}", "fase": FASE_PM, "tarea": TAREA_PM_REGLA, "perfil": PERFIL_PM,
                       "tecnicas_h": min(MAX_PM_TECNICAS_REGLA, max(0, pm - i * MAX_PM_TECNICAS_REGLA)),
                       "reuniones_h": min(MAX_PM_REUNIONES_REGLA, max(0, duracion - i * MAX_PM_REUNIONES_REGLA)),
                       "descripcion": DESCRIPCION_PM_REGLA, "entregable": ENTREGABLE_PM_REGLA})
    gantt.append({"fase": FASE_PM, "contenido": CONTENIDO_PM_REGLA, "semanas": list(range(1, duracion + 1))})
    orden = sorted(hitos_pago or [], key=lambda h: h.get("hito", 0))
    hitos = [{"nombre": f"Hito {h.get('hito', i)} - {h['descripcion']}", "porcentaje": h["porcentaje"]}
             for i, h in enumerate(orden, 1)]
    return {"tareas": tareas, "fases": fases + [FASE_PM], "gantt": gantt, "duracion_semanas": duracion, "hitos": hitos}


def _canon_regla(x: Any) -> str:
    """JSON canónico en NFC (24 y 24.0, o 1 y true, son distintos)."""
    def nfc(o: Any) -> Any:
        if isinstance(o, str):
            return unicodedata.normalize("NFC", o)
        if isinstance(o, list):
            return [nfc(v) for v in o]
        if isinstance(o, dict):
            return {nfc(k): nfc(v) for k, v in o.items()}
        return o
    return json.dumps(nfc(x), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _primera_dif_regla(a: Any, b: Any) -> str:
    """El primer elemento distinto (con su id y sus campos) o los dos valores, recortados."""
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            if _canon_regla(x) != _canon_regla(y):
                if isinstance(x, dict) and isinstance(y, dict):
                    campos = sorted(k for k in set(x) | set(y) if _canon_regla(x.get(k)) != _canon_regla(y.get(k)))
                    return (f"[{i}] ({x.get('id') or x.get('fase')}): {_canon_regla({k: x.get(k) for k in campos})[:160]}"
                            f" y la regla da {_canon_regla({k: y.get(k) for k in campos})[:160]}")
                return f"[{i}]: {_canon_regla(x)[:120]} y la regla da {_canon_regla(y)[:120]}"
        return f"{len(a)} elementos y la regla da {len(b)}"
    return f"{_canon_regla(a)[:160]} y la regla da {_canon_regla(b)[:160]}"


def _regla_estimacion(ctx: Contexto, c: Comprobacion, entrada: dict) -> None:
    """REV-1: FALLA si la entrada guardada no es la que compone la regla (réplica local y núcleo)."""
    try:
        esperada = regla_estimacion_replica(ctx.respuesta, ctx.tarifa.get("hitos_pago") or [])
    except (ValueError, KeyError, TypeError) as e:
        c.falla(f"regla de estimación: no se puede recomponer en local ({e})")
        return
    distintos = [k for k in ("tareas", "fases", "gantt", "duracion_semanas", "hitos")
                 if _canon_regla(entrada.get(k)) != _canon_regla(esperada[k])]
    for k in distintos:
        c.falla(f"estimacion.entrada.{k} no es lo que compone la regla del 10-10-2026 (PM = máx(8 h, ⌈15 %⌉) y "
                f"Gantt con los perfiles de cada fase en paralelo): {_primera_dif_regla(entrada.get(k), esperada[k])} "
                "(REV-1, LES-G-097.2)")
    if not distintos:
        pm = sum((dec(t["tecnicas_h"]) for t in esperada["tareas"] if t["perfil"] == PERFIL_PM), Decimal(0))
        c.nota(f"regla de estimación recompuesta en local: PM {pm} h técnicas, {esperada['duracion_semanas']} semanas")
    em = _nucleo("estimacion")
    if em is not None:
        del_nucleo = em.errores_regla(entrada, ctx.estado, ctx.tarifa)
        for e in del_nucleo:
            c.falla(f"regla de estimación (núcleo): {e}")
        if not del_nucleo and distintos:
            c.falla("regla de estimación: la réplica local y nucleo.estimacion no dan el mismo resultado (LES-G-097)")


def c_estimacion(ctx: Contexto) -> Comprobacion:
    """P6-P7 · Estimación: --verificar canónico, regla de PM y Gantt, holgura, ajuste, trazabilidad, hitos y STOP."""
    c = Comprobacion("estimacion", c_estimacion.__doc__.split("·")[1].strip())
    ruta = ctx.fichero("Estimacion.xlsx")
    copia = ctx.tmp / "verificar_canonico" / ruta.name
    copia.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ruta, copia)
    v = subprocess.run([sys.executable, str(ctx.generador), "--verificar", str(copia)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=300)
    if v.returncode != 0:
        c.falla(f"generar_estimacion.py --verificar rc={v.returncode}: {(v.stdout + v.stderr).strip()[-600:]}")
    else:
        c.nota("generar_estimacion.py --verificar rc=0")
    x = ctx.xlsx()
    for e in x.errores:
        c.falla(f"XLSX: {e}")
    for t in x.tareas:
        if t["formula_F"] != f"=ROUND(E{t['fila']}*0.2,0)" or t["formula_D"] != f"=E{t['fila']}+F{t['fila']}+G{t['fila']}":
            c.falla(f"XLSX fila {t['fila']}: holgura o total sin la fórmula canónica (LES-G-002)")
    if not any(t["perfil"] == PERFIL_PM for t in x.tareas) or x.pm_h < PM_MINIMO:
        c.falla(f"gestión de proyecto {x.pm_h} h < 8 h (LES-G-001)")
    c.nota(f"PM {x.pm_h} h de {x.horas_total} h; precio recalculado {x.precio} EUR")
    tarifa_rc = {p["nombre"]: dec(p["tarifa_hora"]) for p in ctx.tarifa.get("perfiles", [])}
    for p, t in x.tarifas.items():
        if tarifa_rc.get(p) != t:
            c.falla(f"XLSX: tarifa de «{p}» {t} ≠ tarifa local {tarifa_rc.get(p)} (ajuste encubierto)")
    est = ctx.carga.get("estimacion") or {}
    entrada, resumen, ajuste = est.get("entrada") or {}, est.get("resumen") or {}, est.get("ajuste")
    if dec(ctx.tarifa.get("contingencia_porcentaje", 0)) != 0 or any("contingencia" in k.lower() for k in entrada):
        c.falla("contingencia distinta de 0 (LES-G-081)")
    aj_entrada = entrada.get("ajuste_comercial_eur", 0) or 0
    if ajuste is None:
        if x.ajuste is not None or dec(aj_entrada) != 0 or dec(resumen.get("ajuste_eur", "0")) != 0:
            c.falla("ajuste comercial sin decisión AJUSTE_COMERCIAL que cite el hash (LES-G-081)")
    else:
        d = next((d for d in _decisiones(ctx, "AJUSTE_COMERCIAL") if d.get("id") == ajuste.get("decision_id")), None)
        m = re.fullmatch(r"importe_eur=(-?\d+\.\d{2}); motivo=(.{10,})", (d or {}).get("comentarios", ""), re.S)
        if d is None or d.get("hash_citado") != ajuste.get("hash_base"):
            c.falla(f"ajuste {ajuste.get('decision_id')}: sin decisión AJUSTE_COMERCIAL que cite su hash base")
        elif not m or dec(m.group(1)) != dec(ajuste.get("importe_eur")) or x.ajuste != dec(m.group(1)) \
                or dec(aj_entrada) != dec(m.group(1)):
            c.falla("ajuste comercial: el importe del XLSX, la entrada y la decisión no coinciden")
        base_vista = {e.get("hash_despues") for e in ctx.estado.get("control_versiones") or []}
        if ajuste.get("hash_base") not in base_vista:
            c.aviso("el hash base del ajuste no aparece en control_versiones")
    tps = {t.get("id"): t for t in ctx.respuesta.get("tareas_propuestas", [])}
    vistas = set()
    for t in entrada.get("tareas", []):
        tid = t.get("id", "")
        if tid.startswith("PM-"):
            if t.get("perfil") != PERFIL_PM or t.get("fase") != FASE_PM:
                c.falla(f"{tid}: solo Project Manager en «{FASE_PM}»")
            continue
        tp = tps.get(tid)
        vistas.add(tid)
        pares = [("fase", "fase"), ("tarea", "tarea"), ("perfil", "perfil"), ("tecnicas_h", "horas_base"),
                 ("reuniones_h", "reuniones_h"), ("descripcion", "descripcion"), ("entregable", "entregable")]
        if tp is None or any(t.get(a) != tp.get(b) for a, b in pares):
            c.falla(f"{tid}: no es igual a su tarea propuesta por el experto (P6d)")
    for tid in sorted(set(tps) - vistas):
        c.falla(f"{tid}: tarea propuesta no incluida en la estimación")
    _regla_estimacion(ctx, c, entrada)
    filas = [(t["fase"], t["tarea"], t["perfil"], t["E"], t["G"]) for t in x.tareas]
    esperado = [(t.get("fase"), t.get("tarea"), t.get("perfil"), dec(t.get("tecnicas_h", 0)),
                 dec(t.get("reuniones_h", 0))) for t in entrada.get("tareas", [])]
    if filas != esperado:
        c.falla("las tareas del XLSX no son las de estimacion.entrada (orden, fase, perfil u horas)")
    hitos_rc = [(f"Hito {h['hito']} - {h['descripcion']}", q2(dec(h["porcentaje"])))
                for h in ctx.tarifa.get("hitos_pago", [])]
    if [(h["nombre"], h["porcentaje"]) for h in x.hitos] != hitos_rc:
        c.falla("los hitos del XLSX no son los hitos_pago de la tarifa (P6e)")
    if [(h.get("nombre"), q2(dec(h.get("porcentaje")))) for h in resumen.get("hitos", [])] != hitos_rc:
        c.falla("los hitos del resumen no son los hitos_pago de la tarifa (P6e)")
    if dec(resumen.get("precio_cerrado_eur", "-1")) != x.precio:
        c.falla(f"precio del resumen {resumen.get('precio_cerrado_eur')} ≠ recalculado del XLSX {x.precio}")
    if [dec(h.get("importe_eur")) for h in resumen.get("hitos", [])] != [h["importe"] for h in x.hitos]:
        c.falla("importes de hitos del resumen ≠ recalculados del XLSX")
    if x.precio > UMBRAL_STOP:
        stop = [d for d in _decisiones(ctx, "CONFIRMA_STOP", ctx.estado.get("version"))
                if d.get("hash_citado") == ctx.hash_vigente()]
        if not stop:
            c.falla(f"precio {x.precio} EUR > 100.000 EUR sin CONFIRMA_STOP con el hash vigente (LES-G-004)")
        else:
            c.nota(f"STOP confirmado por {stop[-1].get('id')}")
    importe_ajuste = x.ajuste or dec(aj_entrada) or dec(resumen.get("ajuste_eur", "0")) \
        or dec((ajuste or {}).get("importe_eur", "0") or "0")
    # R-4 (I1.1): qué decisión trazada respalda cada confirmación (None si ninguna), con la misma regla que
    # nucleo.decision.confirmaciones_locales; las FALLA de arriba ya cubren su ausencia, esto la hace visible.
    d_stop = stop[-1] if x.precio > UMBRAL_STOP and stop else None
    d_aj = next((d for d in _decisiones(ctx, "AJUSTE_COMERCIAL") if ajuste and d.get("id") == ajuste.get("decision_id")
                 and d.get("hash_citado") == ajuste.get("hash_base")), None)
    _confirmacion_local(ctx, c, "--confirmo-stop", ctx.confirmo_stop, x.precio > UMBRAL_STOP,
                        f"precio {x.precio} EUR por encima de 100.000 EUR (STOP, LES-G-004)",
                        respaldo=_respaldo(d_stop, f"precio {x.precio} EUR"))
    _confirmacion_local(ctx, c, "--confirmo-ajuste", ctx.confirmo_ajuste, importe_ajuste != 0,
                        f"ajuste comercial de {importe_ajuste} EUR (precio final {x.precio} EUR, LES-G-081)",
                        respaldo=_respaldo(d_aj, f"ajuste {importe_ajuste} EUR"))
    return c


def _respaldo(d: dict | None, importe: str) -> str | None:
    """Descripción de la decisión que respalda una confirmación local: id, importe y huella de su línea."""
    if d is None:
        return None
    huella = hashlib.sha256(str(d.get("linea", "")).encode("utf-8")).hexdigest()
    return f"{d.get('id')} ({importe}; huella de la línea {huella[:16]}…)"


def _confirmacion_local(ctx: Contexto, c: Comprobacion, opcion: str, dado: str | None, exigido: bool,
                        motivo: str, respaldo: str | None = "") -> None:
    """R2 · LES-G-097.3: lo que mueve dinero exige que el comercial teclee el hash vigente en local.

    Una decisión de estado.json la pudo escribir el modelo; la confirmación de la línea de órdenes, no.
    Una confirmación con otro hash es FALLA aunque no haga falta: confirma un contenido que no es este.
    """
    vigente = ctx.hash_vigente()
    if dado is not None and dado.strip().lower() != vigente:
        c.falla(f"{opcion} {dado.strip()[:16]}… no es el hash vigente {vigente}: confirma otro contenido")
    elif exigido and dado is None:
        c.falla(f"{motivo}: exige {opcion} {vigente} en la línea de órdenes del comercial; "
                "una decisión en estado.json no basta (R2, LES-G-097)")
    elif exigido and respaldo is None:
        c.falla(f"{opcion} tecleado, pero no hay una decisión trazada que lo respalde ({motivo}): "
                "confirmas algo que nadie decidió (R-4, LES-G-097.3)")
    elif exigido:
        c.nota(f"{opcion}: confirmado en local con el hash vigente · {motivo}"
               + (f" · respaldado por {respaldo}" if respaldo else ""))
    elif dado is not None:
        c.aviso(f"{opcion} dado sin que haga falta (no hay {motivo.split(' ')[0]} que confirmar)")


def _texto_diapo(d: Diapositiva, quitar: str = "") -> str:
    t = "\n".join(d.textos)
    return t.replace(quitar, " ") if quitar else t


def c_cliente(ctx: Contexto) -> Comprobacion:
    """P8 · Lo que ve el cliente (LES-G-053): sin horas, jornadas, perfiles, tarifas, ids ni texto de la revisión interna en el PPTX."""
    c = Comprobacion("cliente_les_g_053", c_cliente.__doc__.split("·")[1].strip())
    p, h = ctx.pptx(), ctx.hash_vigente()
    servicios = servicios_cloud(ctx)
    for d in p.diapositivas:
        for hallazgo in barrer(_texto_diapo(d, h if d.numero == 2 else ""), ctx.perfiles, servicios):
            c.falla(f"diapositiva {d.numero}: {hallazgo}")
    _partes_pptx(ctx, c, p, h, servicios)
    for t in p.notas:
        c.falla(f"notas del orador con texto (prohibidas): «{t[:60]}»")
    for n in p.comentarios:
        c.falla(f"comentarios en el PPTX: {n}")
    for k, v in p.props.items():
        if k == "keywords" or not v:
            continue
        for hallazgo in barrer(v, ctx.perfiles):
            c.falla(f"docProps core {k}: {hallazgo}")
    for v in p.props_texto:
        for hallazgo in barrer(v, ctx.perfiles):
            c.falla(f"docProps app/custom: {hallazgo}")
    _revision_interna(ctx, c)
    _datos_internos(ctx, c)
    _importes_cliente(ctx, c)  # VA18-1 (I1.9, CAMBIOS-I19-D §2.1)
    return c


# ── I1.9 · VA18-1 (CAMBIOS-I19-D §2.1): réplica de pptx_revision.importes_no_permitidos y su llamada ──
def importes_no_permitidos_replica(partes: dict, estado: dict) -> list[str]:
    """VA18-1 (I1.9, LES-G-053 y LES-G-097.1): importes y datos del presupuesto del alta que el cliente no puede ver en
    el PPTX; [] si no hay ninguno.

    `partes`: {nombre de la parte: bytes} del ZIP del PPTX. Recorre cada párrafo de las diapositivas (en el orden de
    presentation.xml, con sus tablas), de las notas y de los diseños y patrones, y el texto alternativo (`descr` y
    `title` de cada cNvPr) de las diapositivas, los diseños y los patrones (las superficies de VPROT-1). (1) Exclusividad de importes: toda cifra pegada a «€», «EUR»,
    «euro» o «euros» tiene que tener lectura española y ser el precio cerrado o un hito (`carga.estimacion.resumen`) o,
    solo en la diapositiva 8, una línea o un total del anexo de consumo (`carga.anexo_consumo`). (2) Presupuesto del alta
    (`requisitos.campos.presupuesto_orientativo`, CITADO o ASUMIDO): ni el rótulo «presupuesto orientativo» ni ninguna
    cifra de 100 o más de su valor o de su cita, salvo que sea uno de los importes admitidos en esa diapositiva. Autónoma
    (biblioteca estándar y lxml): la puerta la lleva copiada (CAMBIOS-I19-D). Una parte que falte o no se pueda leer
    lanza la excepción: quien llama falla en alto, nunca da el PPTX por limpio."""
    import re
    import unicodedata
    from decimal import Decimal, InvalidOperation
    from lxml import etree

    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)

    def xml(nombre):
        return etree.fromstring(partes[nombre], parser)

    def plano(t):
        t = unicodedata.normalize("NFD", unicodedata.normalize("NFC", str(t or "")))
        return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).lower().strip()

    def lectura(cifra):
        s = str(cifra or "").strip()
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?", s):
            return Decimal(s.replace(".", "").replace(",", ".")).quantize(Decimal("0.01"))
        return None

    def importe(valor):
        try:
            return Decimal(str(valor)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None

    def lectura_amplia(texto_cifra):
        # cierre (16-10, Revisión): para el presupuesto del alta, una cifra sin lectura española se lee en inglés
        # («120,000», «120000.50»); nunca sirve para admitir un importe con moneda
        s = re.sub(r"[ \u00a0\u202f]", ".", str(texto_cifra or "").strip())
        valor = lectura(s)
        if valor is None and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+", s):
            valor = importe(s.replace(",", ""))
        return valor

    def parrafos(raiz):
        salida = []
        for par in raiz.iter(f"{{{ns_a}}}p"):
            texto = "".join((el.text or "") if el.tag == f"{{{ns_a}}}t" else " "
                            for el in par.iter(f"{{{ns_a}}}t", f"{{{ns_a}}}br"))
            if texto.strip():
                salida.append(texto.replace("\u00a0", " ").replace("\u202f", " "))
        return salida

    carga = estado.get("carga") or {}
    resumen = (carga.get("estimacion") or {}).get("resumen") or {}
    anexo = carga.get("anexo_consumo") or {}
    base = {importe(resumen.get("precio_cerrado_eur"))} | {importe(h.get("importe_eur")) for h in resumen.get("hitos") or []
                                                            if isinstance(h, dict)}
    consumo = {importe(x.get("coste_mensual_eur")) for x in anexo.get("lineas") or [] if isinstance(x, dict)}
    consumo |= {importe(anexo.get("total_mensual_eur")), importe(anexo.get("total_anual_eur"))}
    base.discard(None)
    consumo.discard(None)
    # Revisión (I1.9): «25 000» (millar con espacio, también duro o fino) es una sola cifra
    cifra = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ \u00a0\u202f.]\d{3})+(?:,\d{1,2})?|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
                       r"|\d+(?:[.,]\d+)?)(?![\w])")
    cifras_presupuesto = set()
    campos = (carga.get("requisitos") or {}).get("campos") or {}
    for e in (campos.get("presupuesto_orientativo") or {}).get("entradas") or []:
        for texto in (e.get("valor"), e.get("cita")) if isinstance(e, dict) else ():
            cifras_presupuesto |= {d for d in (lectura_amplia(m) for m in cifra.findall(str(texto or "")))
                                   if d is not None and d >= 100}

    textos = []  # (dónde, número de diapositiva o None, texto)
    destino = {r.get("Id"): r.get("Target")
               for r in xml("ppt/_rels/presentation.xml.rels").iter(f"{{{ns_rel}}}Relationship")}
    for n, sld in enumerate(xml("ppt/presentation.xml").iter(f"{{{ns_p}}}sldId"), 1):
        parte = "ppt/" + destino[sld.get(f"{{{ns_r}}}id")].lstrip("/").removeprefix("ppt/")
        textos += [(f"diapositiva {n}", n, t) for t in parrafos(xml(parte))]
    for nombre in sorted(partes):
        if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", nombre):
            textos += [(f"notas ({nombre})", None, t) for t in parrafos(xml(nombre))]
    for nombre in sorted(partes):  # cierre (16-10, Revisión 7): también lo que se dibuja o se lee fuera de los párrafos
        diseno = re.fullmatch(r"ppt/(?:slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml", nombre)
        if not (diseno or re.fullmatch(r"ppt/slides/slide\d+\.xml", nombre)):
            continue
        raiz = xml(nombre)
        textos += [(f"texto alternativo ({nombre})", None, el.get(k)) for el in raiz.iter()
                   if isinstance(el.tag, str) and etree.QName(el).localname == "cNvPr"
                   for k in ("descr", "title") if (el.get(k) or "").strip()]
        textos += [(f"diseño o patrón ({nombre})", None, t) for t in parrafos(raiz)] if diseno else []

    moneda = re.compile(r"(?<![\w.,])(\d[\d.,]*\d|\d)\s*(?:€|EUR\b|euros?\b)|(?:€|\bEUR)\s*(\d[\d.,]*\d|\d)(?![\d])", re.I)
    hallazgos = set()
    for donde, n, texto in textos:
        admitidos = base | consumo if n == 8 else base
        for m in moneda.finditer(texto):
            literal = m.group(1) or m.group(2)
            valor = lectura(literal)
            if valor is None:
                hallazgos.add(f"{donde}: importe «{literal}» sin lectura en formato español en «{texto[:80]}»")
            elif valor not in admitidos:
                hallazgos.add(f"{donde}: importe «{literal}» que no es el precio cerrado ni un hito"
                              + (" ni una línea del anexo de consumo" if n == 8 else "") + f" en «{texto[:80]}»")
        con_cifra = False  # Revisión (I1.9, pasada 2): cifra de 1.000 o más (o «mil», «millón») en la frase; un año, no
        for frase in re.split(r"[.;!?]\s", plano(texto)):
            for m in cifra.finditer(frase) if "presupuest" in frase else ():
                valor = lectura_amplia(m.group(1))
                con_cifra |= bool(re.match(r"\s*(mil|millon|millones)\b", frase[m.end():m.end() + 10])) or (
                    valor is not None and valor >= 1000 and not re.fullmatch(r"(19|20)\d\d", m.group(1)))
        if "presupuesto orientativo" in plano(texto) or con_cifra:
            hallazgos.add(f"{donde}: nombra el presupuesto orientativo del alta o un presupuesto con cifra en «{texto[:80]}»")
        for m in cifra.finditer(texto):
            valor = lectura_amplia(m.group(1))
            if valor is not None and valor in cifras_presupuesto and valor not in admitidos:
                hallazgos.add(f"{donde}: cifra «{m.group(1)}» del presupuesto orientativo del alta en «{texto[:80]}»")
    return sorted(hallazgos)


def _importes_cliente(ctx: Contexto, c: Comprobacion) -> None:
    """VA18-1 (I1.9, LES-G-053 y LES-G-097.1): ningún importe que no sea el precio o un hito (salvo el anexo en la
    diapositiva 8) y nada del presupuesto del alta en el PPTX. Réplica propia y contraste con el núcleo."""
    try:
        partes = ctx.pptx().partes
        halla = importes_no_permitidos_replica(partes, ctx.estado)
    except Exception as e:  # noqa: BLE001 - un PPTX que no se puede leer no está limpio
        c.falla(f"importes: no se pudo comprobar el PPTX: {type(e).__name__}: {e}")
        return
    for h in halla[:10]:
        c.falla(f"PPTX con un importe o un dato del presupuesto que el cliente no puede ver: {h} (VA18-1)")
    pr = _nucleo("pptx_revision")
    if pr is None or not hasattr(pr, "importes_no_permitidos"):
        c.aviso("importes: el núcleo local no tiene pptx_revision.importes_no_permitidos (anterior a I1.9)")
    elif pr.importes_no_permitidos(partes, ctx.estado) != halla:
        c.falla("importes: la réplica y nucleo.pptx_revision.importes_no_permitidos discrepan (LES-G-097)")


# VA18-1 (I1.9, LES-G-053): datos comerciales internos del alta que el cliente nunca ve, ni CITADO ni ASUMIDO. Los
# requisitos con esos campos solo van a la nota del revisor (apartados 3 y 4). En el alta, cualquier clave de notas,
# comentarios, presupuesto o uso interno (hoy no hay ninguna; si aparece, ya está cubierta).
CAMPOS_INTERNOS = ("presupuesto_orientativo",)
_CLAVE_ALTA_INTERNA = re.compile(r"nota|intern|comentario|presupuesto", re.I)
ROTULOS_INTERNOS = ("presupuesto orientativo", "sin grabacion", "notas del comercial")   # notas: procedencia, interna
LARGO_MINIMO_INTERNO = 8


def datos_internos_en_cliente(estado: dict, textos: list[tuple[str, str]]) -> list[str]:
    """VA18-1: [hallazgo] si un dato interno del alta llega al cliente; [] si no. `textos`: [(dónde, texto)] de todo lo
    que ve el cliente en el PPTX. Mira (1) las frases publicadas de textos_cliente (todo salvo `excluidas`) que citan
    como hecho `R-<campo interno>`, aunque el texto lo parafrasee; (2) el valor y la cita de cada entrada de esos campos
    (8 caracteres o más, sin tildes ni mayúsculas) y los valores de texto de las claves internas del alta; y (3) el
    rótulo «presupuesto orientativo»."""
    carga = estado.get("carga") or {}
    campos = (carga.get("requisitos") or {}).get("campos") or {}
    valores = []
    for campo in CAMPOS_INTERNOS:
        for e in (campos.get(campo) or {}).get("entradas") or []:
            valores += [(f"{campo} ({k})", plano(e.get(k))) for k in ("valor", "cita")
                        if isinstance(e, dict) and isinstance(e.get(k), str)]
    for k, v in (carga.get("alta") or {}).items():
        if _CLAVE_ALTA_INTERNA.search(str(k)):
            valores += [(f"alta.{k}", plano(s)) for s in (v if isinstance(v, list) else [v]) if isinstance(s, str)]
    valores = [(n, v) for n, v in valores if len(v) >= LARGO_MINIMO_INTERNO]
    hechos_internos = {f"R-{campo}" for campo in CAMPOS_INTERNOS}
    hallazgos = set()

    def recorrer(o, ruta):
        if isinstance(o, dict):
            if isinstance(o.get("hechos"), list) and set(map(str, o["hechos"])) & hechos_internos:
                hallazgos.add(f"textos_cliente{ruta} ({o.get('id')}): frase publicada con un dato interno del alta "
                              f"{sorted(set(map(str, o['hechos'])) & hechos_internos)}")
            for k, v in o.items():
                if not (ruta == "" and k == "excluidas"):
                    recorrer(v, f"{ruta}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                recorrer(v, f"{ruta}[{i}]")
    recorrer(carga.get("textos_cliente") or {}, "")
    for donde, texto in textos:
        pl = plano(texto)
        hallazgos |= {f"{donde}: dato interno del alta {n} en «{texto[:80]}»" for n, v in valores if v in pl}
        hallazgos |= {f"{donde}: rótulo interno «{r}» en «{texto[:80]}»" for r in ROTULOS_INTERNOS
                      if re.search(r"(?<!\w)" + re.escape(r) + r"(?!\w)", pl)}
    return sorted(hallazgos)


def textos_pptx_cliente(p: Pptx) -> list[tuple[str, str]]:
    """Todo el texto del PPTX que ve el cliente: párrafos de cada diapositiva (también tablas), notas, propiedades del
    documento, texto alternativo y diseños y patrones (VPROT-1)."""
    textos = [(f"diapositiva {d.numero}", x) for d in p.diapositivas for x in d.textos if x.strip()]
    textos += [("notas", x) for x in p.notas]
    textos += [(f"propiedad {k}", v) for k, v in p.props.items() if isinstance(v, str) and k != "keywords"]
    textos += [("propiedades app/custom", v) for v in p.props_texto if isinstance(v, str)]
    return textos + textos_fuera_de_diapositivas(p.partes)


def _datos_internos(ctx: Contexto, c: Comprobacion) -> None:
    """VA18-1 (I1.9): ningún dato interno del alta (presupuesto orientativo, notas internas) en lo que ve el cliente.
    Réplica en la puerta de la comprobación del núcleo (papel D): la puerta recalcula (LES-G-097)."""
    try:
        halla = datos_internos_en_cliente(ctx.estado, textos_pptx_cliente(ctx.pptx()))
    except Exception as e:  # noqa: BLE001 - un PPTX que no se puede leer no está limpio
        c.falla(f"datos internos: no se pudo comprobar el PPTX: {type(e).__name__}: {e}")
        return
    for h in halla[:10]:
        c.falla(f"lo que ve el cliente lleva un dato interno del alta (va solo en la nota del revisor): {h} "
                "(VA18-1, LES-G-053)")
    if len(halla) > 10:
        c.falla(f"datos internos del alta en lo que ve el cliente: {len(halla) - 10} hallazgo(s) más (VA18-1)")
    if not halla:
        c.nota("datos internos: ni el presupuesto orientativo ni notas internas del alta en el PPTX ni en las frases "
               "publicadas (VA18-1)")


def revision_interna_en_pptx_replica(partes: dict, estado: dict, catalogo: dict) -> list[str]:
    """VER17-2 (I1.8, LES-G-053): texto de la revisión interna que aparece en el PPTX; [] si no hay ninguno.

    `partes`: {nombre de la parte: bytes} del ZIP del PPTX. Recorre cada párrafo de las diapositivas (en el orden de
    presentation.xml), de las notas y de los comentarios, y cada valor de docProps. Busca: (1) el comentario de
    cualquier decisión del estado, entero (16 caracteres o más) o un tramo de 30 o más, sin contar lo que el revisor
    cita entre «» o comillas (es texto del propio documento); (2) el nombre de quien decide (los tres firmantes y los
    del estado); (3) los identificadores del catálogo (`catalogo_id`, las plantillas con guion y cualquier «az-…»);
    (4) los marcadores de la revisión interna: ids y tipos de decisión, rótulos de la sección de cambios, «calculadas
    por el código», «nota del revisor» y nombres de campos internos. LISTA BLANCA (lo único que sí puede salir): en la
    fila 2 de la tabla de la diapositiva 2, columnas 3 a 5, «<firmante> (<iniciales>)», «<firmante>, AAAA-MM-DD» o
    «Sin firma»; creator y lastModifiedBy de docProps/core.xml iguales a un firmante; keywords igual a
    «hash_contenido:<64 hex>»; y las URL de learn.microsoft.com no se miran por identificadores (son las referencias
    oficiales). Autónoma (biblioteca estándar y lxml): la puerta la lleva copiada (CAMBIOS-I18-D.md), y una parte que
    falte o no se pueda leer lanza la excepción (quien llama falla en alto, nunca da el PPTX por limpio)."""
    import re
    import unicodedata
    from lxml import etree

    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)

    def plano(t):
        t = unicodedata.normalize("NFD", unicodedata.normalize("NFC", str(t or "")))
        return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).lower().strip()

    def xml(nombre):
        return etree.fromstring(partes[nombre], parser)

    def parrafos(raiz):  # [((fila, columna) si está en una tabla, o None; texto del párrafo)]
        salida = []
        for par in raiz.iter(f"{{{ns_a}}}p"):
            texto = "".join((el.text or "") if el.tag == f"{{{ns_a}}}t" else " "  # Revisión I1.8: a:br separa palabras
                            for el in par.iter(f"{{{ns_a}}}t", f"{{{ns_a}}}br"))
            if not texto.strip():
                continue
            tc = next(par.iterancestors(f"{{{ns_a}}}tc"), None)
            celda = None
            if tc is not None:
                tr = tc.getparent()
                celda = (list(tr.getparent().iterchildren(f"{{{ns_a}}}tr")).index(tr) + 1,
                         list(tr.iterchildren(f"{{{ns_a}}}tc")).index(tc) + 1)
            salida.append((celda, texto))
        return salida

    textos = []  # (dónde, celda, texto)
    destino = {r.get("Id"): r.get("Target")
               for r in xml("ppt/_rels/presentation.xml.rels").iter(f"{{{ns_rel}}}Relationship")}
    for n, sld in enumerate(xml("ppt/presentation.xml").iter(f"{{{ns_p}}}sldId"), 1):
        parte = "ppt/" + destino[sld.get(f"{{{ns_r}}}id")].lstrip("/").removeprefix("ppt/")
        textos += [(f"diapositiva {n}", celda, t) for celda, t in parrafos(xml(parte))]
    # VPROT-1 (I1.9): también el texto alternativo (descr y title de cada cNvPr), que lee un lector de pantalla, de las
    # diapositivas, los diseños y los patrones, y los párrafos de los diseños y patrones, que se dibujan en la diapositiva
    for nombre in sorted(partes):
        diseno = re.fullmatch(r"ppt/(?:slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml", nombre)
        if not (diseno or re.fullmatch(r"ppt/slides/slide\d+\.xml", nombre)):
            continue
        for el in xml(nombre).iter():
            if isinstance(el.tag, str) and etree.QName(el).localname == "cNvPr":
                textos += [(f"texto alternativo ({nombre})", None, el.get(k)) for k in ("descr", "title")
                           if (el.get(k) or "").strip()]
        if diseno:
            textos += [(f"diseño o patrón ({nombre})", None, x) for _, x in parrafos(xml(nombre))]
    for nombre in sorted(partes):
        if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", nombre):
            textos += [(f"notas ({nombre})", None, t) for _, t in parrafos(xml(nombre))]
        elif nombre.endswith(".xml") and re.search(r"(^|/)(comments/|comment\w*\.xml|modernComment|commentAuthors)",
                                                   nombre):
            textos += [(f"comentarios ({nombre})", None, t) for t in xml(nombre).itertext() if t.strip()]
    for nombre in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
        if nombre in partes:
            textos += [(f"propiedad {etree.QName(el).localname}", None, el.text) for el in xml(nombre).iter()
                       if isinstance(el.tag, str) and len(el) == 0 and (el.text or "").strip()]

    firmantes = {"Responsable comercial", "Responsable de preventa", "Responsable de área"}
    decisiones = [d for d in estado.get("decisiones") or [] if isinstance(d, dict)]
    firmantes |= {" ".join(str(d.get("revisor")).split()) for d in decisiones if str(d.get("revisor") or "").strip()}

    def admitido(donde, celda, texto):
        t = " ".join(texto.split())
        if donde == "diapositiva 2" and celda is not None and celda[0] == 2 and celda[1] in (3, 4, 5):
            return t == "Sin firma" or any(re.fullmatch(re.escape(f) + r"(?: \([A-ZÁÉÍÓÚÑ]{2,4}\)|, \d{4}-\d{2}-\d{2})",
                                                        t) for f in firmantes)
        if donde in ("propiedad creator", "propiedad lastModifiedBy"):
            return t in firmantes
        return donde == "propiedad keywords" and re.fullmatch(r"hash_contenido:[0-9a-f]{64}", t) is not None

    comentarios = []  # (id de la decisión, texto plano que no puede aparecer)
    for d in decisiones:
        sin_citas = re.sub(r"«[^«»]*»|\"[^\"]*\"|“[^“”]*”", " ", str(d.get("comentarios") or ""))
        entero = plano(sin_citas)
        tramos = [plano(x) for x in re.split(r"[.;:!?¡¿()\[\]\n]+", sin_citas)]
        comentarios += [(d.get("id"), x) for x in ([entero] if len(entero) >= 16 else []) + tramos if len(x) >= 16
                        and (x == entero or len(x) >= 30)]
    nombres = {plano(f) for f in firmantes if len(plano(f)) >= 5}
    # Revisión I1.8: también cada par de palabras seguidas («Responsable comercial», «Responsable comercial», «Responsable de área»), salvo el que
    # solo tiene nombres de pila («El responsable de área»): sería un falso rojo con cualquier otra persona que se llame así
    de_pila = {"juan", "pablo", "jose", "maria", "luis", "carlos", "miguel", "angel", "antonio", "manuel", "francisco",
               "ana", "carmen", "pedro", "jesus", "david", "daniel", "alberto", "alejandro",
               # quien firma se nombra por su rol: sus palabras sueltas son corrientes y se busca solo la frase entera
               "responsable", "comercial", "de", "preventa", "area"}
    for f in list(nombres):
        palabras = f.split(" ")
        nombres |= {" ".join(palabras[i:i + 2]) for i in range(len(palabras) - 1)
                    if not {palabras[i], palabras[i + 1]} <= de_pila}
    nombres = sorted(nombres)
    ids = set()
    for comp in (catalogo or {}).get("componentes") or []:
        if isinstance(comp, dict):
            ids.add(str(comp.get("id") or ""))
            ids |= {str(p.get("id") or "") for p in comp.get("plantillas_precio") or []
                    if isinstance(p, dict) and "-" in str(p.get("id") or "")}
    ids = sorted(x for x in ids if len(x) >= 3)
    marcas = ((r"(?<![\w-])D-\d{3}(?![\w-])", 0, "id de decisión"),
              (r"\b(?:DEVUELTA|APROBADA|ENVIADA_REVISION|DISCREPA|VERIFICADA|OBSERVACI[OÓ]N|NO VERIFICABLE|"
               r"NO VERIFICADO|DECISION)\b", 0, "rótulo de la revisión interna"),
              (r"\b(?:catalogo_id|plantilla_id|version_devuelta|hash_citado|componente_id)\b", re.I,
               "nombre de campo interno"),
              (r"(?<![\w.-])az-[a-z0-9]+(?:-[a-z0-9]+)*(?![\w-])", re.I, "identificador del catálogo"))
    frases = ("cambios pedidos", "como se atendio", "calculadas por el codigo", "calculados por el codigo",
              "calculado por el codigo", "calculada por el codigo", "nota del revisor", "nota de revision",
              "revision de preventa", "aprobacion del area", "recogido en la nota", "version devuelta",
              "devuelta con comentarios", "no dice que cambio responde")

    hallazgos = set()
    por_sitio = {}
    for donde, celda, texto in textos:
        if admitido(donde, celda, texto):
            continue
        pl = plano(texto)
        por_sitio.setdefault(donde, []).append(pl)
        sin_url = re.sub(r"https://learn\.microsoft\.com/\S*", " ", texto)
        motivos = [m for rx, banderas, m in marcas if re.search(rx, sin_url, banderas)]
        motivos += [f"identificador del catálogo «{x}»" for x in ids
                    if re.search(r"(?<![\w.-])" + re.escape(x) + r"(?![\w-])", sin_url, re.I)]
        motivos += [f"nombre de quien decide «{x}»" for x in nombres if re.search(r"(?<!\w)" + re.escape(x) + r"(?!\w)", pl)]
        motivos += [f"marcador de la revisión «{x}»" for x in frases if re.search(r"(?<!\w)" + re.escape(x) + r"(?!\w)", pl)]
        hallazgos |= {f"{donde}: {m} en «{texto[:80]}»" for m in motivos}
    for donde, pls in por_sitio.items():
        junto = " ".join(pls)
        hallazgos |= {f"{donde}: comentario de la decisión {i} («{x[:60]}»)" for i, x in comentarios if x in junto}
    return sorted(hallazgos)


def _revision_interna(ctx: Contexto, c: Comprobacion) -> None:
    """VER17-2 (I1.8, LES-G-053): ningún texto de la revisión interna en el PPTX (comentarios de decisión, nombres de
    quien decide fuera de la firma de la diapositiva 2, identificadores del catálogo y marcadores). Réplica propia y
    contraste con el núcleo (LES-G-097): si discrepan, FALLA."""
    try:
        partes = ctx.pptx().partes
        halla = revision_interna_en_pptx_replica(partes, ctx.estado, ctx.catalogo_obj)
    except Exception as e:  # noqa: BLE001 - nunca en silencio: un PPTX que no se puede leer no está limpio
        c.falla(f"revisión interna: no se pudo comprobar el PPTX: {type(e).__name__}: {e}")
        return
    for h in halla[:10]:
        c.falla(f"PPTX con texto de la revisión interna (va solo en la nota del revisor): {h} (VER17-2)")
    if len(halla) > 10:
        c.falla(f"PPTX con texto de la revisión interna: {len(halla) - 10} hallazgo(s) más (VER17-2)")
    pr = _nucleo("pptx_revision")
    if pr is None:  # integrador I1.8: sin núcleo local, como en los demás contrastes, decide la réplica (que ya ha corrido)
        c.aviso("revisión interna: sin núcleo local; decide solo la réplica (no se ha contrastado)")
    elif not hasattr(pr, "revision_interna_en_pptx"):
        c.falla("revisión interna: el núcleo local no tiene pptx_revision.revision_interna_en_pptx (anterior a I1.8)")
    else:
        try:
            if pr.revision_interna_en_pptx(partes, ctx.estado, ctx.catalogo_obj) != halla:
                c.falla("revisión interna: la réplica y nucleo.pptx_revision.revision_interna_en_pptx discrepan "
                        "(LES-G-097)")
        except Exception as e:  # noqa: BLE001
            c.falla(f"revisión interna: el núcleo no pudo comprobar el PPTX: {type(e).__name__}: {e}")
    if not halla:
        c.nota("revisión interna: ningún comentario, nombre de quien decide, identificador ni marcador en el PPTX "
               "(lista blanca: firmas de la diapositiva 2, autor y huella)")


def servicios_cloud(ctx: Contexto) -> list[str]:
    """Nombres de servicio con fuente de confianza: catálogo local y líneas del anexo (H-V12)."""
    nombres = [x.get("nombre_oficial", "") for x in ctx.catalogo_obj.get("componentes", [])]
    nombres += [ln.get("servicio", "") for ln in (ctx.carga.get("anexo_consumo") or {}).get("lineas", [])]
    return sorted({n for n in nombres if isinstance(n, str) and n.strip()})


_PROHIBIDOS_PPTX = {"pic": "imagen (p:pic)", "oleObj": "objeto incrustado", "AlternateContent": "contenido alternativo",
                    "contentPart": "tinta o contenido externo", "audioFile": "audio", "videoFile": "vídeo",
                    "quickTimeFile": "vídeo", "wavAudioFile": "audio"}


def _partes_pptx(ctx: Contexto, c: Comprobacion, p: Pptx, h: str, servicios: list[str]) -> None:
    """C2: solo las partes que genera pptx_revision; todo el texto de todas las partes, barrido."""
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    for parte, datos in sorted(p.partes.items()):
        if not PARTES_PPTX.fullmatch(parte):
            sha = sha256_bytes(datos)
            if re.search(r"\.(png|jpe?g|gif|bmp|tiff?|emf|wmf|svg)$", parte, re.I) and sha in IMAGENES_PERMITIDAS:
                continue
            c.falla(f"PPTX: parte no prevista {parte} (imágenes, gráficos, SmartArt, notas u objetos: C2)")
            continue
        if parte.endswith(".bin"):
            if sha256_bytes(datos) not in BINARIOS_PPTX:
                c.falla(f"PPTX: binario {parte} fuera de la lista blanca (SHA-256 {sha256_bytes(datos)[:16]}…)")
            continue
        try:
            raiz = etree.fromstring(datos, parser)
        except etree.XMLSyntaxError as e:
            c.falla(f"PPTX: {parte} no es XML válido ({e})")
            continue
        if parte.endswith(".rels"):
            for r in raiz.iter(f"{{{NS['rel']}}}Relationship"):
                if (r.get("TargetMode") or "").lower() == "external":
                    c.falla(f"PPTX: {parte} enlaza fuera del paquete ({r.get('Target')!r})")
            continue
        for el in raiz.iter():
            if not isinstance(el.tag, str):
                continue
            local = el.tag.split("}")[-1]
            if local in _PROHIBIDOS_PPTX:
                c.falla(f"PPTX {parte}: {_PROHIBIDOS_PPTX[local]}")
            elif local == "blip" or el.get(f"{{{NS['r']}}}embed") or el.get(f"{{{NS['r']}}}link"):
                c.falla(f"PPTX {parte}: referencia a una imagen o recurso ({local})")
            elif local == "graphicData" and el.get("uri") != URI_TABLA:
                c.falla(f"PPTX {parte}: marco gráfico que no es tabla ({el.get('uri')}: gráfico o SmartArt)")
            for atr in ("descr", "title", "name"):
                if el.get(atr) and local in ("cNvPr", "cSld"):
                    for hallazgo in barrer(el.get(atr), ctx.perfiles, servicios):
                        c.falla(f"PPTX {parte}: atributo {atr} «{el.get(atr)[:40]}»: {hallazgo}")
        if parte.startswith("ppt/slides/slide"):
            continue  # el texto de las diapositivas ya se ha barrido arriba, párrafo a párrafo
        texto = "\n".join(_texto_parrafos(raiz, "a")).replace(h, " ")
        for hallazgo in barrer(texto, ctx.perfiles, servicios):
            c.falla(f"PPTX {parte}: {hallazgo}")


def _citas(ctx: Contexto) -> list[str]:
    campos = (ctx.carga.get("requisitos") or {}).get("campos") or {}
    return sorted({e.get("cita") for v in campos.values() for e in v.get("entradas", []) if e.get("cita")},
                  key=len, reverse=True)


def c_marcadores(ctx: Contexto) -> Comprobacion:
    """P9 · Cero marcadores (LES-G-006) en PPTX, DOCX, anexo, mensajes, estado.json y XLSX."""
    c = Comprobacion("marcadores", c_marcadores.__doc__.split("·")[1].strip())

    def barrer_en(origen: str, texto: str) -> None:
        for hallazgo in marcadores(texto):
            c.falla(f"{origen}: {hallazgo}")
    for d in ctx.pptx().diapositivas:
        barrer_en(f"PPTX diapositiva {d.numero}", _texto_diapo(d))
    textos_docx, props_docx, _ = ctx.docx()
    docx = "\n".join(textos_docx + [v for v in props_docx.values() if v])
    excluidas = [x.get("texto", "") for x in (ctx.carga.get("textos_cliente") or {}).get("excluidas", [])]
    for cita in _citas(ctx) + sorted(excluidas, key=len, reverse=True):
        docx = docx.replace(cita, " ")  # citas (entrada) y frases excluidas declaradas: no se barren
    barrer_en("DOCX", docx)
    for ruta, s in _strings(ctx.paquete.json_de(f"{ctx.codigo}-Anexo-Consumo.json")):
        barrer_en(f"anexo JSON {ruta}", s)
    import openpyxl
    for nombre in (f"{ctx.codigo}-Anexo-Consumo.xlsx", f"{ctx.codigo}-Estimacion.xlsx"):
        wb = openpyxl.load_workbook(ctx.paquete.ficheros[nombre])
        for ws in wb:
            for fila in ws.iter_rows():
                for celda in fila:
                    if isinstance(celda.value, str) and not celda.value.startswith("="):
                        barrer_en(f"{nombre}!{ws.title}!{celda.coordinate}", celda.value)
    for nombre in ("mensaje_revisor.txt", "mensaje_aprobador.txt"):
        barrer_en(nombre, ctx.paquete.bytes_de(nombre).decode("utf-8", errors="replace"))
    saltar = ("cita", "decisiones", "fallos", "control_versiones", "motivo_bloqueo", "excluidas")
    for ruta, s in _strings({k: v for k, v in ctx.estado.items() if k not in saltar}, saltar=saltar):
        barrer_en(f"estado.json {ruta}", s)
    return c


def _nombre_componente(ctx: Contexto, comp: dict) -> str:
    cat = {x.get("id"): x for x in ctx.catalogo_obj.get("componentes", [])}
    if comp.get("catalogo_id") in cat:
        return cat[comp["catalogo_id"]].get("nombre_oficial", "")
    return comp.get("servicio", "")


def _formas(diapo: Diapositiva) -> tuple[list[tuple[str, str]], list[tuple[str | None, str | None, str]]]:
    """(id, texto) de cada forma con texto y (inicio, fin, texto) de cada conector."""
    a, p = NS["a"], NS["p"]
    formas = []
    for sp in diapo.raiz.iter(f"{{{p}}}sp"):
        nv = sp.find(f"{{{p}}}nvSpPr/{{{p}}}cNvPr")
        texto = " ".join(_texto_parrafos(sp, "a")).strip()
        if nv is not None and texto:
            formas.append((nv.get("id"), texto))
    conectores = []
    for cx in diapo.raiz.iter(f"{{{p}}}cxnSp"):
        st, en = cx.find(f".//{{{a}}}stCxn"), cx.find(f".//{{{a}}}endCxn")
        conectores.append((st.get("id") if st is not None else None, en.get("id") if en is not None else None,
                           " ".join(_texto_parrafos(cx, "a")).strip()))
    return formas, conectores


# PR14-3 (I1.5) y D16-5 (I1.7): réplica de nucleo.pptx_revision.cortes_conectores, idéntica a propósito (LES-G-097)
def cortes_conectores_replica(raiz) -> list[str]:
    """PR14-3 (LES-G-072): conectores que cortan el texto de una forma. [] si ninguno.

    `raiz`: la diapositiva (p:sld) o su árbol de formas (p:spTree). Zona de texto de cada p:sp con texto: su
    caja menos los márgenes interiores de a:bodyPr (91.440 y 45.720 EMU si no constan). Trazado de cada
    p:cxnSp: recta (prstGeom «line» o «straightConnector1») o codo (bentConnector2 a bentConnector5 con sus
    ajustes «val N»; 50000 si no constan), con sus volteos. Otra geometría (custGeom incluida: PowerPoint no
    la abre en un conector), un giro o un grupo no se pueden comprobar: también son fallo, igual que un número
    o un ajuste mal formado (D16-5: con su motivo, nunca una excepción). Pura y determinista (fracciones
    exactas); verificar_paquete.py lleva una réplica idéntica (CAMBIOS-I17-D).
    """
    from fractions import Fraction
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    arbol = raiz if raiz.tag == f"{p_}spTree" else raiz.find(f"{p_}cSld/{p_}spTree")
    if arbol is None:
        return ["la diapositiva no tiene árbol de formas: no se pueden comprobar los conectores"]
    fallos, zonas, trazados = [], [], []

    def entero(valor, nombre):  # D16-5 (I1.7): solo cifras ASCII, un signo menos y 12 cifras; si no, fallo, nunca excepción
        if isinstance(valor, int) and not isinstance(valor, bool):
            return valor
        texto = valor if isinstance(valor, str) else ""
        cifras = texto[1:] if texto.startswith("-") else texto
        if not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
            fallos.append(f"«{nombre}» tiene un valor que no es un número entero ({valor!r}): no se puede comprobar")
            return None
        return int(texto)

    def caja(el, nombre):
        xf = el.find(f"{p_}spPr/{a_}xfrm")
        off = xf.find(f"{a_}off") if xf is not None else None
        ext = xf.find(f"{a_}ext") if xf is not None else None
        if off is None or ext is None:
            fallos.append(f"«{nombre}» no tiene posición ni tamaño: no se puede comprobar")
            return None
        if xf.get("rot") not in (None, "0"):
            fallos.append(f"«{nombre}» está girada: no se puede comprobar")
            return None
        medidas = [entero(v, nombre) for v in (off.get("x", "0"), off.get("y", "0"), ext.get("cx", "0"), ext.get("cy", "0"))]
        if None in medidas:
            return None
        return (*medidas, xf.get("flipH") in ("1", "true"), xf.get("flipV") in ("1", "true"))

    for el in arbol:
        nv = el.find(f"*/{p_}cNvPr")
        nombre = (nv.get("name") if nv is not None else None) or el.tag.rsplit("}", 1)[-1]
        if el.tag == f"{p_}grpSp":
            fallos.append(f"grupo de formas «{nombre}»: no se pueden comprobar sus conectores")
        elif el.tag == f"{p_}sp":
            texto = " ".join("".join(t.text or "" for t in p.iter(f"{a_}t")) for p in el.iter(f"{a_}p")).strip()
            c = caja(el, nombre) if texto else None
            if c:
                bp = el.find(f"{p_}txBody/{a_}bodyPr")
                ins = [entero(bp.get(k, d), nombre) if bp is not None else d
                       for k, d in (("lIns", 91440), ("tIns", 45720), ("rIns", 91440), ("bIns", 45720))]
                if None in ins:
                    continue
                z = (c[0] + ins[0], c[1] + ins[1], c[0] + c[2] - ins[2], c[1] + c[3] - ins[3])
                if z[0] < z[2] and z[1] < z[3]:
                    zonas.append((texto, z))
        elif el.tag == f"{p_}cxnSp":
            c = caja(el, nombre)
            if not c:
                continue
            x, y, cx, cy, fh, fv = c
            geo = el.find(f"{p_}spPr/{a_}prstGeom")
            tipo = geo.get("prst") if geo is not None and el.find(f"{p_}spPr/{a_}custGeom") is None else None
            adj = {}
            ajustes_malos = []
            for gd in geo.findall(f"{a_}avLst/{a_}gd") if geo is not None else []:
                # D16-5 (I1.7): «val» y un entero de cifras ASCII con un signo menos como mucho y 12 cifras; lo demás
                # (cifras Unicode, «--5», un número desmesurado, una fórmula) es un fallo con su motivo, nunca un ValueError
                partes = (gd.get("fmla") or "").split()
                cifras = (partes[1][1:] if partes[1].startswith("-") else partes[1]) if len(partes) == 2 else ""
                if len(partes) != 2 or partes[0] != "val" or not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
                    ajustes_malos.append(gd.get("fmla"))
                else:
                    adj[gd.get("name")] = int(partes[1])
            if ajustes_malos:
                fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar: un ajuste no es un "
                              f"valor entero fijo ({ajustes_malos[0]!r})")
                continue
            if tipo in ("line", "straightConnector1"):
                local = [(0, 0), (cx, cy)]
            elif tipo in ("bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5"):
                x1 = Fraction(cx * adj.get("adj1", 50000), 100000)
                y2 = Fraction(cy * adj.get("adj2", 50000), 100000)
                x3 = Fraction(cx * adj.get("adj3", 50000), 100000)
                local = {"bentConnector2": [(0, 0), (cx, 0), (cx, cy)],
                         "bentConnector3": [(0, 0), (x1, 0), (x1, cy), (cx, cy)],
                         "bentConnector4": [(0, 0), (x1, 0), (x1, y2), (cx, y2), (cx, cy)],
                         "bentConnector5": [(0, 0), (x1, 0), (x1, y2), (x3, y2), (x3, cy), (cx, cy)]}[tipo]
            else:
                fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar")
                continue
            puntos = [(x + (cx - u if fh else u), y + (cy - v if fv else v)) for u, v in local]
            trazados.append((nombre, puntos))

    def corta(p, q, z) -> bool:  # Liang-Barsky con desigualdades estrictas: interior abierto de z
        lo, hi = Fraction(0), Fraction(1)
        dx, dy = q[0] - p[0], q[1] - p[1]
        for a, b in ((-dx, p[0] - z[0]), (dx, z[2] - p[0]), (-dy, p[1] - z[1]), (dy, z[3] - p[1])):
            if a == 0:
                if b <= 0:
                    return False
            elif a > 0:
                hi = min(hi, Fraction(b) / a)
            else:
                lo = max(lo, Fraction(b) / a)
        return lo < hi

    for nombre, puntos in trazados:
        for texto, z in zonas:
            if any(corta(p, q, z) for p, q in zip(puntos, puntos[1:])):
                fallos.append(f"el conector «{nombre}» corta el texto de la forma «{texto[:60]}»")
    return sorted(set(fallos))


# ARR15-2/D15-4 (I1.6), D16-5 y REV16-5 (I1.7): réplica de nucleo.pptx_revision.separacion_conectores, idéntica a propósito (LES-G-097)
def separacion_conectores_replica(raiz) -> list[str]:
    """ARR15-2/D15-4 (LES-G-072): conectores que se confunden entre sí o van pegados a una forma. [] si ninguno.

    `raiz`: la diapositiva (p:sld) o su árbol de formas (p:spTree). Trazado de cada p:cxnSp como en
    `cortes_conectores`: recta o codo (bentConnector2 a bentConnector5 con sus ajustes «val N») con sus volteos;
    otra geometría, un giro, un grupo o un tramo que no sea horizontal ni vertical no se pueden comprobar y son
    fallo. Distancias de Chebyshov en EMU, con fracciones exactas. Entre cada par de conectores:
    - dos tramos paralelos a menos de 60.000 con un hueco a lo largo menor que 180.000 comparten tramo (si se
      solapan) o van en línea y uno parece prolongar al otro;
    - un cruce o un toque a menos de 180.000 de un extremo de cualquiera de los dos se lee mal;
    - dos extremos a menos de 60.000 comparten punto de conexión.
    Y ningún tramo pasa a menos de 80.000 de la caja de una forma p:sp; su forma de origen (stCxn) solo se exime en
    el tramo de salida y la de destino (endCxn) en el de entrada (REV16-5); las «Banda …» no cuentan porque contienen
    a sus componentes. Cada extremo pegado está en el lado (`idx` 0 arriba, 1 izquierda, 2 abajo, 3 derecha) de su
    forma, a 2.000 como mucho, y un conector sin trazado (longitud nula) es fallo: no se ve. Un número o un ajuste mal
    formado es un fallo con su motivo, nunca una excepción (D16-5). Pura y determinista; verificar_paquete.py lleva
    una réplica idéntica (CAMBIOS-I17-D).
    """
    from fractions import Fraction
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    separacion, distancia, extremo, pegado = 60000, 80000, 180000, 2000
    arbol = raiz if raiz.tag == f"{p_}spTree" else raiz.find(f"{p_}cSld/{p_}spTree")
    if arbol is None:
        return ["la diapositiva no tiene árbol de formas: no se pueden comprobar los conectores"]
    fallos, cajas, trazados = [], [], []

    def entero(valor, nombre):  # D16-5 (I1.7): solo cifras ASCII, un signo menos y 12 cifras; si no, fallo, nunca excepción
        if isinstance(valor, int) and not isinstance(valor, bool):
            return valor
        texto = valor if isinstance(valor, str) else ""
        cifras = texto[1:] if texto.startswith("-") else texto
        if not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
            fallos.append(f"«{nombre}» tiene un valor que no es un número entero ({valor!r}): no se puede comprobar")
            return None
        return int(texto)

    def caja(el, nombre):
        xf = el.find(f"{p_}spPr/{a_}xfrm")
        off = xf.find(f"{a_}off") if xf is not None else None
        ext = xf.find(f"{a_}ext") if xf is not None else None
        if off is None or ext is None:
            fallos.append(f"«{nombre}» no tiene posición ni tamaño: no se puede comprobar")
            return None
        if xf.get("rot") not in (None, "0"):
            fallos.append(f"«{nombre}» está girada: no se puede comprobar")
            return None
        medidas = [entero(v, nombre) for v in (off.get("x", "0"), off.get("y", "0"), ext.get("cx", "0"), ext.get("cy", "0"))]
        if None in medidas:
            return None
        return (*medidas, xf.get("flipH") in ("1", "true"), xf.get("flipV") in ("1", "true"))

    for el in arbol:
        nv = el.find(f"*/{p_}cNvPr")
        nombre = (nv.get("name") if nv is not None else None) or el.tag.rsplit("}", 1)[-1]
        if el.tag == f"{p_}grpSp":
            fallos.append(f"grupo de formas «{nombre}»: no se pueden comprobar sus conectores")
        elif el.tag == f"{p_}sp" and not nombre.startswith("Banda "):
            c = caja(el, nombre)
            if c:
                texto = " ".join("".join(t.text or "" for t in p.iter(f"{a_}t")) for p in el.iter(f"{a_}p")).strip()
                cajas.append((nv.get("id") if nv is not None else None, texto or nombre,
                              (c[0], c[1], c[0] + c[2], c[1] + c[3])))
        elif el.tag == f"{p_}cxnSp":
            c = caja(el, nombre)
            if not c:
                continue
            x, y, cx, cy, fh, fv = c
            geo = el.find(f"{p_}spPr/{a_}prstGeom")
            tipo = geo.get("prst") if geo is not None and el.find(f"{p_}spPr/{a_}custGeom") is None else None
            adj = {}
            ajustes_malos = []
            for gd in geo.findall(f"{a_}avLst/{a_}gd") if geo is not None else []:
                # D16-5 (I1.7): «val» y un entero de cifras ASCII con un signo menos como mucho y 12 cifras; lo demás
                # (cifras Unicode, «--5», un número desmesurado, una fórmula) es un fallo con su motivo, nunca un ValueError
                partes = (gd.get("fmla") or "").split()
                cifras = (partes[1][1:] if partes[1].startswith("-") else partes[1]) if len(partes) == 2 else ""
                if len(partes) != 2 or partes[0] != "val" or not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
                    ajustes_malos.append(gd.get("fmla"))
                else:
                    adj[gd.get("name")] = int(partes[1])
            if ajustes_malos:
                fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar: un ajuste no es un "
                              f"valor entero fijo ({ajustes_malos[0]!r})")
                continue
            if tipo in ("line", "straightConnector1"):
                local = [(0, 0), (cx, cy)]
            elif tipo in ("bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5"):
                x1 = Fraction(cx * adj.get("adj1", 50000), 100000)
                y2 = Fraction(cy * adj.get("adj2", 50000), 100000)
                x3 = Fraction(cx * adj.get("adj3", 50000), 100000)
                local = {"bentConnector2": [(0, 0), (cx, 0), (cx, cy)],
                         "bentConnector3": [(0, 0), (x1, 0), (x1, cy), (cx, cy)],
                         "bentConnector4": [(0, 0), (x1, 0), (x1, y2), (cx, y2), (cx, cy)],
                         "bentConnector5": [(0, 0), (x1, 0), (x1, y2), (x3, y2), (x3, cy), (cx, cy)]}[tipo]
            else:
                fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar")
                continue
            puntos = [(x + (cx - u if fh else u), y + (cy - v if fv else v)) for u, v in local]
            tramos = [(p, q) for p, q in zip(puntos, puntos[1:]) if p != q]
            if any(p[0] != q[0] and p[1] != q[1] for p, q in tramos):
                fallos.append(f"el conector «{nombre}» tiene un tramo que no es horizontal ni vertical: no se puede comprobar")
                continue
            if not tramos:  # revisión independiente (I1.6): un conector de longitud nula no se ve
                fallos.append(f"el conector «{nombre}» no tiene trazado (longitud nula)")
                continue
            pegas = [(etiqueta, punto, e.get("id"), e.get("idx")) for etiqueta, punto, e in
                     (("inicial", puntos[0], el.find(f"{p_}nvCxnSpPr/{p_}cNvCxnSpPr/{a_}stCxn")),
                      ("final", puntos[-1], el.find(f"{p_}nvCxnSpPr/{p_}cNvCxnSpPr/{a_}endCxn"))) if e is not None]
            trazados.append((nombre, puntos[0], puntos[-1], tramos, {g[2] for g in pegas if g[2]}, pegas))

    def tramo(p, q):  # (orientación, coordenada fija, desde, hasta)
        if p[1] == q[1]:
            return "h", p[1], min(p[0], q[0]), max(p[0], q[0])
        return "v", p[0], min(p[1], q[1]), max(p[1], q[1])

    def cheb(a, b):
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

    en_dist, en_ext = (f"{v:,}".replace(",", ".") for v in (distancia, extremo))  # 80.000 y 180.000

    por_id = {id_forma: (texto, r) for id_forma, texto, r in cajas}
    for nombre, _, _, _, _, pegas in trazados:  # revisión independiente (I1.6): el extremo está donde dice estar pegado
        for etiqueta, punto, id_forma, idx in pegas:
            if id_forma not in por_id or idx not in ("0", "1", "2", "3"):
                fallos.append(f"el extremo {etiqueta} del conector «{nombre}» está pegado a una forma o a un punto "
                              "que no existe")
                continue
            texto, r = por_id[id_forma]
            lado = {"0": (r[0], r[1], r[2], r[1]), "1": (r[0], r[1], r[0], r[3]),
                    "2": (r[0], r[3], r[2], r[3]), "3": (r[2], r[1], r[2], r[3])}[idx]
            if max(lado[0] - punto[0], punto[0] - lado[2], lado[1] - punto[1], punto[1] - lado[3],
                   abs(punto[0] - lado[0]) if idx in ("1", "3") else 0,
                   abs(punto[1] - lado[1]) if idx in ("0", "2") else 0) > pegado:
                fallos.append(f"el extremo {etiqueta} del conector «{nombre}» no está en el lado "
                              f"{('de arriba', 'izquierdo', 'de abajo', 'derecho')[int(idx)]} de la forma «{texto[:60]}»")
    for nombre, _, _, tramos, _, pegas in trazados:
        origen = next((g[2] for g in pegas if g[0] == "inicial" and g[2]), None)
        destino = next((g[2] for g in pegas if g[0] == "final" and g[2]), None)
        if origen is not None and origen == destino:  # segunda pasada de la revisión independiente: sin exención que cubra un tramo entero
            fallos.append(f"el conector «{nombre}» une una forma consigo misma: no se puede comprobar")
            continue
        for n, (p, q) in enumerate(tramos):
            for id_forma, texto, r in cajas:
                hueco = max(r[0] - max(p[0], q[0]), min(p[0], q[0]) - r[2], r[1] - max(p[1], q[1]),
                            min(p[1], q[1]) - r[3], 0)
                # REV16-5 (I1.7): la forma de origen solo se exime en el tramo de salida y la de destino en el de entrada;
                # tras salir de su forma, el conector guarda la misma distancia con ella que con cualquier otra
                propia = id_forma is not None and id_forma in (origen, destino)
                if hueco >= distancia or (propia and ((n == 0 and id_forma == origen)
                                                      or (n == len(tramos) - 1 and id_forma == destino))):
                    continue
                fallos.append(f"el conector «{nombre}» vuelve a pasar a menos de {en_dist} EMU de su forma de "
                              f"{'origen' if id_forma == origen else 'destino'} «{texto[:60]}» tras salir de ella" if propia
                              else f"el conector «{nombre}» pasa a menos de {en_dist} EMU de la forma «{texto[:60]}»")
    for i, (n1, i1, f1, t1, _, _) in enumerate(trazados):
        for n2, i2, f2, t2, _, _ in trazados[i + 1:]:
            par = f"los conectores «{n1}» y «{n2}»"
            if any(cheb(a, b) < separacion for a in (i1, f1) for b in (i2, f2)):
                fallos.append(f"{par} comparten punto de conexión")
            for p, q in t1:
                o, c, lo, hi = tramo(p, q)
                for a, b in t2:
                    o2, c2, lo2, hi2 = tramo(a, b)
                    if o == o2 and abs(c - c2) < separacion and max(lo, lo2) < min(hi, hi2) + extremo:
                        fallos.append(f"{par} comparten tramo" if max(lo, lo2) < min(hi, hi2)
                                      else f"{par} van en línea: uno parece prolongar al otro")
                    elif o != o2 and lo <= c2 <= hi and lo2 <= c <= hi2:
                        punto = (c2, c) if o == "h" else (c, c2)
                        if any(cheb(punto, e) < extremo for e in (i1, f1, i2, f2)):
                            fallos.append(f"{par} se cruzan o se tocan a menos de {en_ext} EMU de un extremo")
    return sorted(set(fallos))


# REVERIF16-3 (I1.7, CAMBIOS-I17-D §7.3): réplica de nucleo.pptx_revision.referencias_faltan, idéntica a propósito (LES-G-097)
# ── I1.9 · VA18-6 (CAMBIOS-I19-D §2.2): réplica de pptx_revision.legibilidad_conectores ──
def legibilidad_conectores_replica(raiz) -> list[str]:
    """VA18-6 (I1.9, LES-G-072): conectores que se leen mal aunque estén bien pegados. [] si ninguno.

    `raiz`: la diapositiva (p:sld) o su árbol de formas (p:spTree). Trazado de cada p:cxnSp como en
    `separacion_conectores` (recta o codo bentConnector2 a bentConnector5 con sus ajustes «val N» y sus volteos); otra
    geometría, un giro, un grupo, un tramo oblicuo o un número mal formado no se pueden comprobar y son fallo, nunca una
    excepción. Distancias de Chebyshov en EMU, con fracciones exactas. Entre cada par de conectores:
    - dos tramos paralelos a menos de 60.000 van en la misma línea, a cualquier distancia a lo largo (se leen como una
      sola línea, aunque haya hueco entre ellos);
    - dos conectores que se cruzan o se tocan en cualquier punto se leen mal: no hay salto dibujado, así que el núcleo
      cae a la tabla (LES-G-062);
    - dos puntas de flecha (`a:tailEnd` en el extremo final, `a:headEnd` en el inicial, de tipo distinto de «none») a
      menos de 200.000 no se distinguen.
    Pura y determinista; verificar_paquete.py lleva una réplica idéntica (CAMBIOS-I19-D)."""
    from fractions import Fraction
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    separacion, puntas = 60000, 200000
    arbol = raiz if raiz.tag == f"{p_}spTree" else raiz.find(f"{p_}cSld/{p_}spTree")
    if arbol is None:
        return ["la diapositiva no tiene árbol de formas: no se pueden comprobar los conectores"]
    fallos, trazados = [], []

    def entero(valor, nombre):
        if isinstance(valor, int) and not isinstance(valor, bool):
            return valor
        texto = valor if isinstance(valor, str) else ""
        cifras = texto[1:] if texto.startswith("-") else texto
        if not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
            fallos.append(f"«{nombre}» tiene un valor que no es un número entero ({valor!r}): no se puede comprobar")
            return None
        return int(texto)

    for el in arbol:
        nv = el.find(f"*/{p_}cNvPr")
        nombre = (nv.get("name") if nv is not None else None) or el.tag.rsplit("}", 1)[-1]
        if el.tag == f"{p_}grpSp":
            fallos.append(f"grupo de formas «{nombre}»: no se pueden comprobar sus conectores")
            continue
        if el.tag != f"{p_}cxnSp":
            continue
        xf = el.find(f"{p_}spPr/{a_}xfrm")
        off = xf.find(f"{a_}off") if xf is not None else None
        ext = xf.find(f"{a_}ext") if xf is not None else None
        if off is None or ext is None:
            fallos.append(f"«{nombre}» no tiene posición ni tamaño: no se puede comprobar")
            continue
        if xf.get("rot") not in (None, "0"):
            fallos.append(f"«{nombre}» está girada: no se puede comprobar")
            continue
        medidas = [entero(v, nombre) for v in (off.get("x", "0"), off.get("y", "0"), ext.get("cx", "0"), ext.get("cy", "0"))]
        if None in medidas:
            continue
        x, y, cx, cy = medidas
        fh, fv = xf.get("flipH") in ("1", "true"), xf.get("flipV") in ("1", "true")
        geo = el.find(f"{p_}spPr/{a_}prstGeom")
        tipo = geo.get("prst") if geo is not None and el.find(f"{p_}spPr/{a_}custGeom") is None else None
        adj, malos = {}, []
        for gd in geo.findall(f"{a_}avLst/{a_}gd") if geo is not None else []:
            partes = (gd.get("fmla") or "").split()
            cifras = (partes[1][1:] if partes[1].startswith("-") else partes[1]) if len(partes) == 2 else ""
            if len(partes) != 2 or partes[0] != "val" or not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
                malos.append(gd.get("fmla"))
            else:
                adj[gd.get("name")] = int(partes[1])
        if malos:
            fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar: un ajuste no es un "
                          f"valor entero fijo ({malos[0]!r})")
            continue
        if tipo in ("line", "straightConnector1"):
            local = [(0, 0), (cx, cy)]
        elif tipo in ("bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5"):
            x1 = Fraction(cx * adj.get("adj1", 50000), 100000)
            y2 = Fraction(cy * adj.get("adj2", 50000), 100000)
            x3 = Fraction(cx * adj.get("adj3", 50000), 100000)
            local = {"bentConnector2": [(0, 0), (cx, 0), (cx, cy)],
                     "bentConnector3": [(0, 0), (x1, 0), (x1, cy), (cx, cy)],
                     "bentConnector4": [(0, 0), (x1, 0), (x1, y2), (cx, y2), (cx, cy)],
                     "bentConnector5": [(0, 0), (x1, 0), (x1, y2), (x3, y2), (x3, cy), (cx, cy)]}[tipo]
        else:
            fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar")
            continue
        puntos = [(x + (cx - u if fh else u), y + (cy - v if fv else v)) for u, v in local]
        tramos = [(p, q) for p, q in zip(puntos, puntos[1:]) if p != q]
        if not tramos or any(p[0] != q[0] and p[1] != q[1] for p, q in tramos):
            fallos.append(f"el conector «{nombre}» no tiene un trazado horizontal y vertical que se pueda comprobar")
            continue
        ln = el.find(f"{p_}spPr/{a_}ln")
        flechas = [punto for etiqueta, punto in (("headEnd", puntos[0]), ("tailEnd", puntos[-1]))
                   if ln is not None and ln.find(f"{a_}{etiqueta}") is not None
                   and ln.find(f"{a_}{etiqueta}").get("type", "none") != "none"]
        trazados.append((nombre, tramos, flechas))

    def tramo(p, q):
        if p[1] == q[1]:
            return "h", p[1], min(p[0], q[0]), max(p[0], q[0])
        return "v", p[0], min(p[1], q[1]), max(p[1], q[1])

    en_puntas = f"{puntas:,}".replace(",", ".")
    for i, (n1, t1, f1) in enumerate(trazados):
        for n2, t2, f2 in trazados[i + 1:]:
            par = f"los conectores «{n1}» y «{n2}»"
            if any(max(abs(a[0] - b[0]), abs(a[1] - b[1])) < puntas for a in f1 for b in f2):
                fallos.append(f"{par} tienen las puntas de flecha a menos de {en_puntas} EMU: no se distingue cuál es cuál")
            for p, q in t1:
                o, c, lo, hi = tramo(p, q)
                for a, b in t2:
                    o2, c2, lo2, hi2 = tramo(a, b)
                    if o == o2 and abs(c - c2) < separacion:
                        fallos.append(f"{par} van en la misma línea: se leen como una sola")
                    elif o != o2 and lo <= c2 <= hi and lo2 <= c <= hi2:
                        fallos.append(f"{par} se cruzan o se tocan sin salto")
    return sorted(set(fallos))


def referencias_faltan_replica(raiz, respuesta: dict) -> list[str]:
    """REVERIF16-3 (LES-G-062): componentes de la respuesta cuya página de referencia no está en el pie de la
    diapositiva 4. [] si están todas.

    `raiz`: la diapositiva (p:sld) o su árbol de formas (p:spTree). Cuenta cada párrafo de las formas p:sp cuyo nombre
    empieza por «Referencias de arquitectura» que termina en una URL https (la de la referencia, entera). Cada
    componente busca la URL de su `referencia_id` sin espacios alrededor ni barra final: si no la encuentra, o no tiene
    referencia, es un fallo; y sin ningún cuadro de referencias, también (no se puede comprobar). Pura y determinista;
    verificar_paquete.py lleva una réplica idéntica (CAMBIOS-I17-D)."""
    import re as re_
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    arbol = raiz if raiz.tag == f"{p_}spTree" else raiz.find(f"{p_}cSld/{p_}spTree")
    if arbol is None:
        return ["la diapositiva no tiene árbol de formas: no se pueden comprobar las referencias"]
    publicadas, cuadros = set(), 0
    for sp in arbol.iter(f"{p_}sp"):
        nv = sp.find(f"{p_}nvSpPr/{p_}cNvPr")
        if nv is None or not (nv.get("name") or "").startswith("Referencias de arquitectura"):
            continue
        cuadros += 1
        for p in sp.iter(f"{a_}p"):
            m = re_.search(r"(https://\S+)$", "".join(t.text or "" for t in p.iter(f"{a_}t")).strip())
            if m:
                publicadas.add(m.group(1).rstrip("/"))
    if not cuadros:
        return ["la diapositiva 4 no tiene el pie «Referencias de arquitectura»: no se puede comprobar que esté la página "
                "de cada componente"]
    refs = {r.get("id"): r for r in respuesta.get("referencias") or [] if isinstance(r, dict)}
    fallos = []
    for comp in respuesta.get("componentes") or []:
        if not isinstance(comp, dict):
            continue
        if isinstance(comp.get("existente_del_cliente"), dict) and comp.get("catalogo_id") is None \
                and comp.get("referencia_id") is None:
            continue
        clave = str((refs.get(comp.get("referencia_id")) or {}).get("url") or "").strip().rstrip("/")
        if not clave:
            fallos.append(f"el componente {comp.get('id')} no tiene una referencia con URL en la respuesta")
        elif clave not in publicadas:
            fallos.append(f"falta en el pie de la diapositiva 4 la página del componente {comp.get('id')} ({clave})")
    return sorted(set(fallos))


# ARR13-2 (I1.4, P2): réplica de nucleo.pptx_revision.solapes_diagrama, idéntica a propósito (LES-G-097); la
# comprobación `diagrama` contrasta las dos sobre las mismas formas y falla si discrepan.
PREFIJO_COMPONENTE, PREFIJO_BANDA = "Componente ", "Banda "
TITULOS_BANDA = ("Identidad, seguridad y red", "Operación y observabilidad")


def formas_diagrama(diapo: Diapositiva) -> list[tuple]:
    """[(nombre, texto, x, y, ancho, alto)] de cada p:sp de la diapositiva en orden de dibujo (z-order)."""
    p, a = NS["p"], NS["a"]
    salida = []
    for sp in diapo.raiz.iter(f"{{{p}}}sp"):
        nv = sp.find(f"{{{p}}}nvSpPr/{{{p}}}cNvPr")
        xf = sp.find(f".//{{{a}}}xfrm")
        off = xf.find(f"{{{a}}}off") if xf is not None else None
        ext = xf.find(f"{{{a}}}ext") if xf is not None else None
        if nv is None or off is None or ext is None:
            continue
        salida.append((nv.get("name") or "", " ".join(_texto_parrafos(sp, "a")).strip(), int(off.get("x", 0)),
                       int(off.get("y", 0)), int(ext.get("cx", 0)), int(ext.get("cy", 0))))
    return salida


def solapes_diagrama_replica(formas: list[tuple]) -> list[str]:
    """Ninguna forma «Componente …» corta a otra ni la tapa o corta una «Banda …» (la banda solo puede
    contenerla entera y por debajo); títulos de banda sin forma «Banda …» también es fallo."""
    comps, bandas, fallos, titulos = [], [], [], set()
    for z, forma in enumerate(formas):
        nombre, texto_forma = str(forma[0] or ""), str(forma[1] or "")
        if texto_forma in TITULOS_BANDA:
            titulos.add(texto_forma)
        if not nombre.startswith((PREFIJO_COMPONENTE, PREFIJO_BANDA)):
            continue
        geo = forma[2:6]
        if len(geo) != 4 or not all(isinstance(v, int) and not isinstance(v, bool) for v in geo) \
                or geo[2] <= 0 or geo[3] <= 0:
            fallos.append(f"la forma «{nombre}» no tiene una posición y un tamaño válidos")
            continue
        (comps if nombre.startswith(PREFIJO_COMPONENTE) else bandas).append((z, texto_forma or nombre, *geo))

    def corta(a, b) -> bool:
        return min(a[2] + a[4], b[2] + b[4]) > max(a[2], b[2]) and min(a[3] + a[5], b[3] + b[5]) > max(a[3], b[3])

    def dentro(a, b) -> bool:
        return a[2] >= b[2] and a[3] >= b[3] and a[2] + a[4] <= b[2] + b[4] and a[3] + a[5] <= b[3] + b[5]

    for i, a in enumerate(comps):
        for b in comps[i + 1:]:
            if corta(a, b):
                fallos.append(f"la forma «{a[1]}» se solapa con la forma «{b[1]}»")
        for b in bandas:
            if corta(a, b) and not (dentro(a, b) and a[0] > b[0]):
                fallos.append(f"la banda «{b[1]}» tapa o corta la forma «{a[1]}»")
    for i, a in enumerate(bandas):
        for b in bandas[i + 1:]:
            if corta(a, b):
                fallos.append(f"la banda «{a[1]}» se solapa con la banda «{b[1]}»")
    if titulos and not bandas:
        fallos.append(f"hay bandas ({', '.join(sorted(titulos))}) sin forma «{PREFIJO_BANDA}…»: no se puede "
                      "comprobar si tapan algún componente")
    return fallos


# PR14-1 / VER14-1 (I1.4): réplica de nucleo.anexo_consumo.es_saas_sin_precio y facturables_azure, con el catálogo
# LOCAL. Un componente de Azure con precio publicado en Retail Prices se factura por consumo: si ninguno trae precio,
# la diapositiva 8 enseña al cliente 0,00 € de consumo.
_SAAS_REPLICA = re.compile(r"\b(sharepoint|microsoft 365|office 365|exchange online|onedrive|teams|entra|dynamics 365)\b")


def _plano_saas(texto: Any) -> str:
    t = unicodedata.normalize("NFD", unicodedata.normalize("NFC", str(texto or "")))
    return re.sub(r"\s+", " ", "".join(ch for ch in t if unicodedata.category(ch) != "Mn").lower()).strip()


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


def _sin_precios_con_azure(ctx: Contexto, c: Comprobacion, que: str, vacio: bool) -> None:
    """PR14-1: FALLA si `vacio` (sin precios o anexo sin líneas) y hay Azure facturable; réplica contra el núcleo."""
    facturables = facturables_azure_replica(ctx.respuesta, ctx.catalogo_obj)
    if vacio and facturables:
        c.falla(f"{que}: ningún precio de consumo y {len(facturables)} componentes de Azure se facturan por consumo "
                f"({', '.join(map(str, facturables))}): la diapositiva 8 enseñaría 0,00 € (PR14-1, LES-G-062)")
    ac = _nucleo("anexo_consumo")
    if ac is not None and hasattr(ac, "facturables_azure"):
        try:
            del_nucleo = [x["componente_id"] for x in ac.facturables_azure(ctx.respuesta, ctx.catalogo_obj)]
        except Exception as e:  # noqa: BLE001 - Revisión (arreglos I1.4): nunca en silencio, también un catalogo_id ajeno
            c.falla(f"{que}: no se pudo contrastar la lista de facturables con nucleo.anexo_consumo: "
                    f"{type(e).__name__}: {e}")
            return
        if del_nucleo != facturables:
            c.falla(f"{que}: componentes facturables: la réplica local {facturables} y nucleo.anexo_consumo "
                    f"{del_nucleo} no dan lo mismo (LES-G-097)")


# I1.5 (papel P, PR15-2 y REVERIF14-2): réplica de nucleo.anexo_consumo.errores_cobertura y de
# nucleo.experto.region_exige_catalogo, con su propio código; prueba de igualdad en tests/test_i15_p_cobertura_puerta.py.
# Las respuestas del experto anteriores a I1.5 (componentes sin «motivo_no_valoracion», es_contrato_experto_v1) se
# validan con historico/respuesta_experto_v1 y FALLAN en «experto» (puerta de su época).
SIN_MOTIVO_REPLICA = "no_aplica"
MOTIVOS_NO_VALORACION_REPLICA = ("depende_del_volumen", "sin_medidor_publico", "a_cargo_del_cliente",
                                 "incluido_en_otro_componente", "licencia_fuera_de_azure", "fuera_del_catalogo",
                                 "existente_del_cliente")


def es_contrato_experto_v1(resp: object) -> bool:
    """Respuesta del experto anterior a I1.5: tiene componentes y ninguno lleva la clave «motivo_no_valoracion»."""
    comps = resp.get("componentes") if isinstance(resp, dict) else None
    return (isinstance(comps, list) and bool(comps)
            and not any(isinstance(x, dict) and "motivo_no_valoracion" in x for x in comps))


def nombre_esquema_experto(resp) -> str:
    """Sustituye a la de la puerta: desde I1.9, la v4 completada se valida con su histórico."""
    if es_contrato_experto_v1(resp):
        return "historico/respuesta_experto_v1"
    if es_contrato_experto_v2(resp):
        return "historico/respuesta_experto_v2"
    if es_contrato_experto_v3(resp):
        return "historico/respuesta_experto_v3"
    return "historico/respuesta_experto_completa_v4" if es_contrato_experto_v4(resp) else "respuesta_experto_completa"


def region_exige_catalogo_replica(comp) -> bool:
    """Sustituye a la de la puerta: I1.9, un recurso del cliente (sin catalogo_id) no se despliega en una región."""
    return (isinstance(comp, dict) and not comp.get("catalogo_id") and comp.get("region") != "global"
            and not es_existente_r(comp))


def errores_cobertura_replica(respuesta: dict, catalogo: dict) -> list[tuple[str, str]]:
    """[(componente_id, regla)] en el orden de la respuesta: «sin_precio_ni_motivo» (facturable de Azure sin precio y
    con motivo «no_aplica»), «precio_y_motivo» (con precio y con motivo) y «fuera_del_catalogo_con_id»."""
    facturables = set(facturables_azure_replica(respuesta, catalogo))
    con_precio = set(precios_que_cubren_replica(respuesta, catalogo))  # I1.6: ni auxiliar ni referencia cubren
    salida = []
    for comp in respuesta.get("componentes") or []:
        if not isinstance(comp, dict):
            continue
        cid, m = comp.get("id"), comp.get("motivo_no_valoracion")
        declarado = m if isinstance(m, str) and m else SIN_MOTIVO_REPLICA
        if cid in facturables and cid not in con_precio and declarado == SIN_MOTIVO_REPLICA:
            salida.append((cid, "sin_precio_ni_motivo"))
        if cid in con_precio and declarado != SIN_MOTIVO_REPLICA:
            salida.append((cid, "precio_y_motivo"))
        if declarado == "fuera_del_catalogo" and comp.get("catalogo_id"):
            salida.append((cid, "fuera_del_catalogo_con_id"))
        fila = _fila_replica(catalogo, comp.get("catalogo_id"))  # REV16-1 (arreglos I1.6): el motivo se comprueba
        if declarado == "licencia_fuera_de_azure" and fila is not None and fila.get("service_name_precios"):
            salida.append((cid, "licencia_con_precio_azure"))
        if (declarado == "sin_medidor_publico" and fila is not None and fila.get("plantillas_precio")
                and (fila.get("region_precio") or comp.get("region") == fila.get("region_ue"))):
            salida.append((cid, "medidor_publico_en_catalogo"))
    return salida


def _cobertura_precios(ctx: Contexto, c: Comprobacion) -> None:
    """PR15-2 y REVERIF14-2: FALLA por cada componente sin cobertura de precios o con región sin catalogo_id, y si la
    réplica y el núcleo no dan lo mismo; si el contraste no se puede hacer, FALLA con el motivo (nunca en silencio)."""
    r = ctx.respuesta or {}
    if es_contrato_experto_v1(r):
        c.falla("respuesta del experto anterior a I1.5 (ningún componente lleva motivo_no_valoracion): repetir el "
                "análisis con el contrato vigente (PR15-2, puerta de su época)")
        return
    if es_contrato_experto_v2(r):  # I1.6
        c.falla("respuesta del experto anterior a I1.6 (contrato v2: sin justificacion_nivel ni base_volumen): repetir "
                "el análisis con el contrato vigente (decisión 4, LES-G-100; puerta de su época)")
        return
    if es_contrato_experto_v3(r):  # I1.7
        c.falla("respuesta del experto anterior a I1.7 (contrato v3: el modelo escribía filtros y precios; sin "
                "valoracion_nucleo): repetir el análisis con el contrato vigente (decisión 1 del comercial del 13-10-2026; "
                "puerta de su época)")
        return
    if es_contrato_experto_v4(r):  # I1.9 (CAMBIOS-I19-P §7)
        c.falla("respuesta del experto anterior a I1.9 (contrato v4: sin existente_del_cliente y con la justificación "
                "de I1.7): repetir el análisis con el contrato vigente (puerta de su época)")
        return
    _contrastar_cobertura_i16(ctx, c)
    comps = [x for x in r.get("componentes") or [] if isinstance(x, dict)]
    for comp in comps:
        if region_exige_catalogo_replica(comp):
            c.falla(f"{comp.get('id')}: región «{comp.get('region')}» sin catalogo_id: todo componente con región de "
                    "Azure lleva el catalogo_id de su servicio (REVERIF14-2)")
    hallados = errores_cobertura_replica(r, ctx.catalogo_obj)
    for cid, regla in hallados:
        c.falla(f"{cid}: cobertura de precios: {regla}; cada facturable de Azure lleva precio o motivo de no "
                "valoración de la lista cerrada (PR15-2, LES-G-062)")
    ac, ex = _nucleo("anexo_consumo"), _nucleo("experto")
    if ac is None or ex is None:  # sin núcleo local decide solo la réplica, y se dice
        c.aviso("cobertura de precios: sin núcleo local; decide solo la réplica (no se ha contrastado)")
    for mod, nombre in ((ac, "anexo_consumo.errores_cobertura"), (ex, "experto.region_exige_catalogo")):
        if mod is not None and not hasattr(mod, nombre.split(".")[1]):
            c.falla(f"cobertura de precios: el núcleo local no tiene {nombre}: es anterior a I1.5 o distinto del "
                    "desplegado; no se puede contrastar")
    if ac is not None and hasattr(ac, "errores_cobertura"):
        try:
            del_nucleo = [(x["componente_id"], x["regla"]) for x in ac.errores_cobertura(r, ctx.catalogo_obj)]
        except Exception as e:  # noqa: BLE001 - nunca en silencio, también un catalogo_id ajeno
            c.falla(f"cobertura de precios: no se pudo contrastar con nucleo.anexo_consumo: {type(e).__name__}: {e}")
            return
        if del_nucleo != hallados:
            c.falla(f"cobertura de precios: la réplica local {hallados} y nucleo.anexo_consumo {del_nucleo} no dan "
                    "lo mismo (LES-G-097)")
        motivos = tuple(getattr(ac, "MOTIVOS_NO_VALORACION", ()))
        if motivos != MOTIVOS_NO_VALORACION_REPLICA or getattr(ac, "SIN_MOTIVO", None) != SIN_MOTIVO_REPLICA:
            c.falla("cobertura de precios: la lista cerrada de motivos de la réplica y la del núcleo no coinciden")
    if ex is not None and hasattr(ex, "region_exige_catalogo"):
        for comp in comps:
            if bool(ex.region_exige_catalogo(comp)) != region_exige_catalogo_replica(comp):
                c.falla(f"{comp.get('id')}: región sin catalogo_id: la réplica local y nucleo.experto no dan el mismo "
                        "resultado")


# I1.6 (papel P; decisión 4 del comercial, LES-G-100, REV15-1, REV15-3 y VER15-3): réplicas con código propio de
# nucleo.anexo_consumo.precios_que_cubren, del precio auxiliar atado (nucleo.experto.problemas_auxiliar), del concepto
# fijado desde la plantilla (nucleo.experto.fijar_conceptos) y de nucleo.experto.errores_volumen_nivel. Prueba de
# igualdad en tests/test_i16_p_puerta.py. Las respuestas de I1.5 (contrato v2, sin justificacion_nivel) se validan con
# historico/respuesta_experto_v2 y FALLAN en «experto» (puerta de su época).
IMPULSORES_REPLICA = ("tiempo", "volumen")
MARCA_ASUMIDO_REPLICA = " [ASUMIDO, confianza baja]"
ETIQUETAS_BRIEF_REPLICA = ("Objetivo", "Nubes", "Ubicación de los usuarios finales", "Marco normativo", "Volumetría",
                           "Identidad y permisos del origen", "Red privada", "Tipo de suscripción", "Plazo",
                           "Presupuesto orientativo", "Idioma de la oferta")
CORTE_BRIEF_REPLICA = ("## Comentarios de la revisión", "## Correcciones solicitadas", "## Elementos ya verificados",
                       "## Precios ya verificados", "## Precios conservados",   # I1.7: secciones nuevas del brief
                       "## Elementos sin verificar", "## Propuesta de la versión")  # PR17-6 (arreglos I1.7)


def es_contrato_experto_v2(resp: object) -> bool:
    """Respuesta de I1.5 (contrato v2): tiene motivo_no_valoracion y ningún componente lleva «justificacion_nivel»."""
    comps = resp.get("componentes") if isinstance(resp, dict) else None
    return (isinstance(comps, list) and bool(comps) and not es_contrato_experto_v1(resp)
            and not any(isinstance(x, dict) and "justificacion_nivel" in x for x in comps))


def _fila_replica(catalogo: dict, cid: object) -> dict | None:
    return next((e for e in (catalogo or {}).get("componentes") or [] if isinstance(e, dict) and cid
                 and e.get("id") == cid), None)


def _servicios_replica(filtro: object) -> list[str]:
    return list(dict.fromkeys(valores_filtro(filtro, "serviceName")))


def precios_que_cubren_replica(respuesta: dict, catalogo: dict) -> dict[str, list[str]]:
    """{componente_id: [precio_id]}: precios con cantidad_mensual y del servicio propio del componente (REV15-1)."""
    comps = {x.get("id"): x for x in respuesta.get("componentes") or [] if isinstance(x, dict)}
    salida: dict[str, list[str]] = {}
    for p in respuesta.get("precios") or []:
        if not isinstance(p, dict) or p.get("cantidad_mensual") is None or p.get("componente_id") not in comps:
            continue
        fila = _fila_replica(catalogo, comps[p.get("componente_id")].get("catalogo_id"))
        if fila is None or _servicios_replica(p.get("filtro")) == [fila.get("service_name_precios")]:
            salida.setdefault(p.get("componente_id"), []).append(str(p.get("id")))
    return salida


def plantillas_auxiliar_replica(aux: dict, catalogo: dict) -> tuple[list[dict], dict]:
    fila = _fila_replica(catalogo, aux.get("plantillas_de"))
    ids = [i for i in aux.get("plantillas") or [] if isinstance(i, str)]
    hay = {p.get("id"): p for p in (fila or {}).get("plantillas_precio") or [] if isinstance(p, dict)}
    if fila is None or not ids or any(i not in hay for i in ids):
        return [], {}
    return [hay[i] for i in ids], fila


def auxiliar_de_filtro(filtro: object, region: object, catalogo: dict) -> dict | None:
    if not isinstance(filtro, str):
        return None
    for a in precios_auxiliares(catalogo):
        pls, fila = plantillas_auxiliar_replica(a, catalogo)
        if any(_filtro_de_plantilla(p, fila, region) == filtro for p in pls):
            return a
    return None


def problemas_auxiliar(filtro: object, aux: dict, entrada: dict, region: object, catalogo: dict) -> list[str]:
    """Réplica de nucleo.experto.problemas_auxiliar: mismos motivos y mismo texto, y el mismo nombre (problemas_precio
    tiene que ser el mismo código en el núcleo y en la puerta: tests/test_i15_int_replicas.py)."""
    nombre, servicio = f"{entrada.get('nombre_oficial')} ({entrada.get('id')})", aux.get("service_name")
    componentes = [x for x in aux.get("componentes") or [] if isinstance(x, str)]
    motivos = []
    if entrada.get("id") not in componentes:
        motivos.append(f"el precio auxiliar «{servicio}» no acompaña a {nombre} (acompaña a: "
                       f"{', '.join(componentes) or 'ninguno: el catálogo montado no lo declara'}); un auxiliar va en "
                       "el componente al que sirve y nunca sustituye a su precio propio")
    pls, fila = plantillas_auxiliar_replica(aux, catalogo)
    if not pls:
        motivos.append(f"el catálogo montado no trae plantillas de filtro para el precio auxiliar «{servicio}»: no se "
                       "puede comprobar (falla cerrado)")
    elif all(_filtro_de_plantilla(p, fila, region) != filtro for p in pls):
        motivos.append(f"el filtro no es el de ninguna plantilla del precio auxiliar «{servicio}»: cópiala carácter a "
                       "carácter")
    return motivos


def plantilla_precio_replica(p: dict, comp: object, catalogo: dict) -> tuple[dict, bool] | None:
    """(plantilla, es_auxiliar) cuyo filtro, en la región del componente, es exactamente el del precio; None si no."""
    fila = _fila_replica(catalogo, comp.get("catalogo_id")) if isinstance(comp, dict) else None
    f = p.get("filtro") if isinstance(p, dict) else None
    if fila is None or not isinstance(f, str):
        return None
    if _servicios_replica(f) == [fila.get("service_name_precios")]:
        return next(((x, False) for x in fila.get("plantillas_precio") or [] if isinstance(x, dict)
                     and _filtro_de_plantilla(x, fila, comp.get("region")) == f), None)
    for a in precios_auxiliares(catalogo):
        if fila.get("id") in (a.get("componentes") or []):
            pls, fa = plantillas_auxiliar_replica(a, catalogo)
            hit = next((x for x in pls if _filtro_de_plantilla(x, fa, comp.get("region")) == f), None)
            if hit is not None:
                return hit, True
    return None


def concepto_replica(pl: dict) -> str | None:
    """Concepto de la plantilla, como lo fija nucleo.experto.concepto_de_plantilla."""
    c = pl.get("concepto")
    if isinstance(c, str) and 3 <= len(" ".join(c.split())) <= 160:
        return " ".join(c.split())
    k = pl.get("comprobacion") if isinstance(pl.get("comprobacion"), dict) else {}
    med = k.get("medidor") if isinstance(k.get("medidor"), str) else ""
    if pl.get("concepto_con_sku"):
        return f"{med} ({k.get('sku')})" if med and k.get("sku") else None
    if len(med) >= 3:
        return med
    if med and k.get("producto"):
        return f"{med} ({k.get('producto')})"
    meters = list(dict.fromkeys(valores_filtro(pl.get("filtro"), "meterName")))
    return meters[0] if len(meters) == 1 and len(meters[0]) >= 3 else None


def conceptos_replica(respuesta: dict, catalogo: dict) -> list[tuple[str, object, str | None]]:
    """[(precio_id, concepto guardado, concepto de su plantilla)] de cada precio cuyo filtro es una plantilla."""
    comps = {x.get("id"): x for x in respuesta.get("componentes") or [] if isinstance(x, dict)}
    salida = []
    for p in respuesta.get("precios") or []:
        hit = plantilla_precio_replica(p, comps.get(p.get("componente_id")), catalogo) if isinstance(p, dict) else None
        if hit is not None:
            salida.append((p.get("id"), p.get("concepto"), concepto_replica(hit[0])))
    return salida


def _plano_req_replica(t: object) -> str:
    return " ".join(unicodedata.normalize("NFC", t).split()) if isinstance(t, str) else ""


def _lineas_req_replica(texto: object) -> list[str]:
    t = texto if isinstance(texto, str) else ""
    _, sep, cuerpo = t.partition("\n---\n")
    lineas = (cuerpo if sep else t).split("\n")
    fin = next((i for i, x in enumerate(lineas) if x.startswith(CORTE_BRIEF_REPLICA)), len(lineas))
    return lineas[:fin]


def _sin_marca_replica(t: str) -> str:
    return t[:-len(MARCA_ASUMIDO_REPLICA)] if t.endswith(MARCA_ASUMIDO_REPLICA) else t


def _campos_req_replica(requisitos: object) -> dict:
    campos = requisitos.get("campos") if isinstance(requisitos, dict) else None
    return campos if isinstance(campos, dict) else {}


def _valores_req_replica(requisitos: object, campo: str | None) -> list[object]:
    salida = []
    for k, v in _campos_req_replica(requisitos).items():
        entradas = v.get("entradas") if isinstance(v, dict) else None
        if campo in (None, k) and isinstance(entradas, list):
            salida += [e.get("valor") for e in entradas if isinstance(e, dict)]
    return salida


def volumetria_replica(requisitos: object, texto: object) -> tuple[str, list[str]]:
    """(estado de la volumetría, citas válidas para base_volumen), como nucleo.experto."""
    linea = next((x[len("Volumetría: "):] for x in _lineas_req_replica(texto) if x.startswith("Volumetría: ")), None)
    campo = _campos_req_replica(requisitos).get("volumetria")
    if isinstance(campo, dict) and campo.get("estado"):
        estado = campo["estado"]
    else:  # sin requisitos o sin el campo: lo que dice el brief
        estado = "FALTA" if linea is None else "ASUMIDO" if linea.endswith(MARCA_ASUMIDO_REPLICA) else "CITADO"
    valores = _valores_req_replica(requisitos, "volumetria")
    citas = [_plano_req_replica(v) for v in valores]
    if linea is not None:
        trozos = _sin_marca_replica(linea).split("; ")
        if not isinstance(requisitos, dict) or len(trozos) == len(valores):
            citas += [_plano_req_replica(s) for s in trozos]
    return estado, [x for x in dict.fromkeys(citas) if x]


def citas_requisito_replica(requisitos: object, texto: object) -> list[str]:
    citas = [_plano_req_replica(v) for v in _valores_req_replica(requisitos, None)]
    for x in _lineas_req_replica(texto):
        if not x.strip() or x.startswith("#"):
            continue
        t = x[2:] if x.startswith("- ") else x
        etq = next((e for e in ETIQUETAS_BRIEF_REPLICA if t.startswith(e + ": ")), None)
        t = _sin_marca_replica(t[len(etq) + 2:] if etq else t)
        citas += [_plano_req_replica(t)] + [_plano_req_replica(s) for s in t.split("; ")]
    return [x for x in dict.fromkeys(citas) if x]


def numeros_replica(texto: object) -> list[Decimal]:
    salida = []
    for tok in re.findall(r"\d[\d.,]*\d|\d", texto if isinstance(texto, str) else ""):
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?", tok):
            salida.append(Decimal(tok.replace(".", "").replace(",", ".")))
        elif re.fullmatch(r"\d+\.\d+", tok):
            salida.append(Decimal(tok))
    return salida


def _num_replica(x: object) -> Decimal | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        d = Decimal(str(x))
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _obj_replica(x: object) -> dict:
    return x if isinstance(x, dict) else {}


def ruta_learn_replica(url: object) -> str:
    """Como nucleo.experto.normalizar_url, con código propio: ruta de https://learn.microsoft.com sin idioma, en
    minúsculas, sin consulta ni barra final; "" si no es Learn o lleva «.» o «..» (Revisión, I1.6: _norm_url no sirve aquí)."""
    from urllib.parse import unquote, urlsplit
    try:
        u = urlsplit(url.strip()) if isinstance(url, str) else None
    except ValueError:
        return ""
    if u is None or u.scheme.lower() != "https" or (u.hostname or "").lower() != "learn.microsoft.com":
        return ""
    try:
        puerto = u.port
    except ValueError:  # puerto mal formado
        return ""
    if puerto is not None or u.username:
        return ""
    trozos = [x for x in unquote(u.path).lower().split("/") if x]
    if "." in trozos or ".." in trozos:
        return ""
    if trozos and re.match(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})+$", trozos[0]):
        trozos = trozos[1:]
    return "/" + "/".join(trozos) if trozos else ""


def _cuadra_replica(cm: object, base: dict, div: int) -> bool | None:
    """None si base_volumen no trae números; si no, si cantidad_mensual cuadra con la cuenta (solo el redondeo)."""
    b, f = _num_replica(base.get("cantidad_base")), _num_replica(_obj_replica(base.get("factor")).get("valor"))
    if b is None or f is None:
        return None
    esperada, c = b * f / Decimal(div), _num_replica(cm)
    return c is not None and abs(c - esperada) <= max(Decimal("0.01"), abs(esperada) * Decimal("0.005"))


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


# ── REVERIF17-2 y REVERIF17-3: medidores por nivel, valor por defecto, clase cómputo y tope de instancias ─────────────
FILAS_COMPUTO_R = ("az-app-service", "az-functions", "az-container-apps", "az-logic-apps", "az-foundry-agent-service")


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


def reglas_medidores_r(fila) -> list:
    """I1.8 (N1): réplica de nucleo.experto.reglas_medidores_de (una regla mal formada va como False)."""
    salida: list = []
    for r in ((fila or {}).get("reglas_medidores") if isinstance(fila, dict) else None) or []:
        ls = {k: r.get(k) if isinstance(r, dict) else None for k in ("si_usa", "exige", "exige_uno_de")}
        ok = (isinstance(ls["si_usa"], list) and bool(ls["si_usa"])
              and all(v is None or isinstance(v, list) and all(isinstance(x, str) for x in v) for v in ls.values())
              and bool(ls["exige"] or ls["exige_uno_de"]))
        salida.append({k: list(v or []) for k, v in ls.items()} if ok else False)
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
        insuf, veces_nivel = insuficiencia_r(niveles, propias, sumas, requisitos, texto)  # VC19-1 (I1.10)
        salida += [(cid, r) for r in insuf]
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
        salida += [(cid, r) for r in _reglas_razon_r(jn, nivel["razones"], requisitos, texto, veces_nivel)]
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


def _existentes_y_arquitectura(ctx: Contexto, c: Comprobacion) -> None:
    """I1.9 (PR18-1, VC18-2 y VA18-4; CAMBIOS-I19-P §7): FALLA por cada (id, regla) de los recursos que el cliente ya
    tiene (existentes_r) y de la arquitectura (arquitectura_r: canal sin cómputo, datos sin salida), y si el núcleo no da
    lo mismo, no los tiene o no se puede contrastar (nunca en silencio). Las respuestas de contratos anteriores ya
    FALLAN en _cobertura_precios."""
    r = ctx.respuesta or {}
    if (es_contrato_experto_v1(r) or es_contrato_experto_v2(r) or es_contrato_experto_v3(r)
            or es_contrato_experto_v4(r)):
        return
    req, cat = ctx.carga.get("requisitos"), ctx.catalogo_obj
    try:
        hallados_ex, hallados_arq = existentes_r(r, req, cat), arquitectura_r(r, cat)
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"recursos del cliente y arquitectura: no se pudieron comprobar: {type(e).__name__}: {e}")
        return
    for cid, regla in hallados_ex:
        c.falla(f"{cid}: recurso que el cliente ya tiene: {regla}; un recurso del cliente no se valora y casa con un "
                "solo componente de su servicio (PR18-1, VC18-2)")
    for cid, regla in hallados_arq:
        c.falla(f"{cid}: arquitectura: {regla}; un canal valorado necesita cómputo valorado o «La solución no tiene "
                "cómputo propio», y un componente de datos, salida o un supuesto que lo explique (VC18-2, VA18-4)")
    ex = _nucleo("experto")
    if ex is None:
        c.aviso("recursos del cliente y arquitectura: sin núcleo local; decide solo la réplica (no se ha contrastado)")
        return
    if not all(hasattr(ex, n) for n in ("errores_existentes", "errores_arquitectura")):
        c.falla("recursos del cliente y arquitectura: el núcleo local no tiene errores_existentes o "
                "errores_arquitectura: es anterior a I1.9 o distinto del desplegado; no se puede contrastar")
        return
    try:
        del_ex = [(x["id"], x["regla"]) for x in ex.errores_existentes(r, req, cat)]
        del_arq = [(x["id"], x["regla"]) for x in ex.errores_arquitectura(r, cat)]
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"recursos del cliente y arquitectura: no se pudo contrastar con nucleo.experto: {type(e).__name__}: {e}")
        return
    if del_ex != hallados_ex:
        c.falla(f"recursos del cliente: la réplica local {hallados_ex} y nucleo.experto {del_ex} no dan lo mismo (LES-G-097)")
    if del_arq != hallados_arq:
        c.falla(f"arquitectura: la réplica local {hallados_arq} y nucleo.experto {del_arq} no dan lo mismo (LES-G-097)")


def _decision_4(ctx: Contexto, c: Comprobacion) -> None:
    """I1.6 (decisión 4, LES-G-100; VER15-3): FALLA por cada regla de volumen, «depende_del_volumen» y nivel que
    incumple la respuesta, por cada concepto guardado distinto del de su plantilla y por cada sustitución anotada que no
    es la guardada; y si la réplica y el núcleo no dan lo mismo o no se pueden contrastar (nunca en silencio)."""
    r = ctx.respuesta or {}
    if (es_contrato_experto_v1(r) or es_contrato_experto_v2(r) or es_contrato_experto_v3(r)
            or es_contrato_experto_v4(r)):
        return  # ya FALLA en _cobertura_precios: puerta de su época
    texto = (_brief_vigente(ctx) or {}).get("texto")
    req = ctx.carga.get("requisitos")
    hallados = errores_volumen_nivel_replica(r, texto, req, ctx.catalogo_obj)
    for i, regla in hallados:
        c.falla(f"{i}: decisión 4: {regla}; las cantidades de volumen salen de la volumetría citada con factor "
                "explícito y el nivel se justifica con el catálogo (LES-G-100)")
    for pid, guardado, fijado in conceptos_replica(r, ctx.catalogo_obj):
        if fijado is None:
            c.falla(f"{pid}: el catálogo local no permite fijar el concepto de su plantilla (VER15-3)")
        elif guardado != fijado:
            c.falla(f"{pid}: concepto «{guardado}» distinto del de su plantilla «{fijado}»: lo fija el código (VER15-3)")
    registro = (ctx.carga.get("respuestas_expertos") or {}).get(pilar_ctx(ctx)) or {}
    precios = {p.get("id"): p for p in r.get("precios") or [] if isinstance(p, dict)}
    for s in (registro.get("ajustes_nucleo") or {}).get("conceptos") or []:
        p = precios.get(s.get("precio_id")) if isinstance(s, dict) else None
        if p is None or p.get("concepto") != s.get("fijado"):
            c.falla(f"ajustes_nucleo: la sustitución de concepto {s!r} no es la guardada en la respuesta (VER15-3)")
    ex = _nucleo("experto")
    if ex is None:
        c.aviso("decisión 4: sin núcleo local; decide solo la réplica (no se ha contrastado)")
        return
    if not all(hasattr(ex, n) for n in ("errores_volumen_nivel", "fijar_conceptos")):
        c.falla("decisión 4: el núcleo local no tiene errores_volumen_nivel o fijar_conceptos: es anterior a I1.6 o "
                "distinto del desplegado; no se puede contrastar")
        return
    try:
        del_nucleo = [(x["id"], x["regla"]) for x in ex.errores_volumen_nivel(r, texto, req, ctx.catalogo_obj)]
        _, sustituciones, errores = ex.fijar_conceptos(r, ctx.catalogo_obj)
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"decisión 4: no se pudo contrastar con nucleo.experto: {type(e).__name__}: {e}")
        return
    if del_nucleo != hallados:
        c.falla(f"decisión 4: la réplica local {hallados} y nucleo.experto {del_nucleo} no dan lo mismo (LES-G-097)")
    if sustituciones or errores:
        c.falla(f"decisión 4: nucleo.experto fijaría otros conceptos ({sustituciones or errores}): la respuesta guardada "
                "no es la que registra el núcleo (VER15-3)")


def _contrastar_cobertura_i16(ctx: Contexto, c: Comprobacion) -> None:
    """REV15-1 (I1.6): qué precios cubren cada componente, réplica frente a nucleo.anexo_consumo.precios_que_cubren."""
    ac = _nucleo("anexo_consumo")
    if ac is None:
        return  # ya avisado en _cobertura_precios
    if not hasattr(ac, "precios_que_cubren"):
        c.falla("cobertura de precios: el núcleo local no tiene anexo_consumo.precios_que_cubren: es anterior a I1.6 "
                "o distinto del desplegado; no se puede contrastar")
        return
    try:
        del_nucleo = ac.precios_que_cubren(ctx.respuesta or {}, ctx.catalogo_obj)
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"cobertura de precios: no se pudo contrastar precios_que_cubren: {type(e).__name__}: {e}")
        return
    replica = precios_que_cubren_replica(ctx.respuesta or {}, ctx.catalogo_obj)
    if del_nucleo != replica:
        c.falla(f"cobertura de precios: precios que cubren, réplica {replica} y núcleo {del_nucleo} distintos (LES-G-097)")


# Arreglos I1.6 (PR16-1 y PR16-3): réplicas con código propio de nucleo.experto.errores_referencia_catalogo y
# nucleo.experto.errores_conservacion; prueba de igualdad en tests/test_i16_arr_puerta.py.
def referencia_catalogo_replica(respuesta: dict, catalogo: dict) -> list[tuple[str, str]]:
    """[(componente_id, regla)]: la referencia de un componente con catalogo_id del catálogo es exactamente la
    `referencia_url` de su fila («referencia_no_catalogo»); sin esa URL en la fila, «catalogo_sin_referencia»."""
    refs = {x.get("id"): x for x in respuesta.get("referencias") or [] if isinstance(x, dict)}
    salida = []
    for comp in respuesta.get("componentes") or []:
        if not isinstance(comp, dict):
            continue
        fila, ref = _fila_replica(catalogo, comp.get("catalogo_id")), refs.get(comp.get("referencia_id"))
        if fila is None or ref is None:
            continue
        propia = ruta_learn_replica(fila.get("referencia_url"))
        if not propia:
            salida.append((comp.get("id"), "catalogo_sin_referencia"))
        elif ruta_learn_replica(ref.get("url")) != propia:
            salida.append((comp.get("id"), "referencia_no_catalogo"))
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


def _cantidad_dato(x: object) -> Decimal | None:
    """Cantidad de un dato estructurado: None, o un número JSON finito (ni texto ni booleano), como el núcleo."""
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise ValueError(f"cantidad no numérica: {x!r}")
    d = Decimal(str(x))
    if not d.is_finite():
        raise ValueError(f"cantidad no finita: {x!r}")
    return d


def _referencias_y_conservacion(ctx: Contexto, c: Comprobacion) -> None:
    """PR16-1: FALLA por cada componente del catálogo cuya referencia no es la de su fila. PR16-3 y LES-G-100.6 (I1.7):
    FALLA por cada servicio y plantilla del brief vigente cuya cantidad total no se conserva. Y si la réplica y el
    núcleo (verificacion.errores_conservacion_efecto y, si existe, experto.errores_conservacion, que registrar-experto
    aplica) no dan lo mismo."""
    r = ctx.respuesta or {}
    if (es_contrato_experto_v1(r) or es_contrato_experto_v2(r) or es_contrato_experto_v3(r)
            or es_contrato_experto_v4(r)):
        return  # ya FALLA en _cobertura_precios: puerta de su época
    vigente = _brief_vigente(ctx) or {}
    conservar = vigente.get("conservar_precios", [])
    refs, cons = referencia_catalogo_replica(r, ctx.catalogo_obj), conservacion_replica(r, conservar)
    for cid, regla in refs:
        c.falla(f"{cid}: {regla}: la referencia de un componente del catálogo es la página de Learn de su fila (PR16-1)")
    for clave, regla in cons:
        c.falla(f"{clave}: {regla}: lo conservado se compara por efecto, la cantidad mensual total de cada servicio y "
                "plantilla (LES-G-100.6)")
    ex, ve = _nucleo("experto"), _nucleo("verificacion")
    if ex is None or ve is None:
        c.aviso("referencias y conservación: sin núcleo local; decide solo la réplica (no se ha contrastado)")
        return
    if not hasattr(ex, "errores_referencia_catalogo") or not hasattr(ve, "errores_conservacion_efecto"):
        c.falla("referencias y conservación: el núcleo local no tiene errores_referencia_catalogo o "
                "errores_conservacion_efecto: es anterior a I1.7 o distinto del desplegado; no se puede contrastar")
        return
    try:
        n_refs = [(x["id"], x["regla"]) for x in ex.errores_referencia_catalogo(r, ctx.catalogo_obj)]
        n_cons = [(x["id"], x["regla"]) for x in ve.errores_conservacion_efecto(r, conservar)]
        e_cons = ([(x["id"], x["regla"]) for x in ex.errores_conservacion(r, conservar)]
                  if hasattr(ex, "errores_conservacion") else n_cons)
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"referencias y conservación: no se pudo contrastar con el núcleo: {type(e).__name__}: {e}")
        return
    if n_refs != refs or n_cons != cons:
        c.falla(f"referencias y conservación: la réplica local {refs + cons} y el núcleo {n_refs + n_cons} no dan "
                "lo mismo (LES-G-097)")
    if e_cons != n_cons:
        c.falla(f"conservación: experto.errores_conservacion {e_cons} no aplica la regla por efecto de "
                f"verificacion.errores_conservacion_efecto {n_cons}: registrar-experto y la puerta no juzgan igual "
                "(LES-G-100.6; CAMBIOS-I17-R)")


# I1.7 (papel P, CAMBIOS-I17-P §6): réplicas con código propio de nucleo.experto.completar, proyectar_modelo,
# errores_motivos, errores_ciclo_vida (con duracion_gantt) y citas_dimensionamiento. Prueba de igualdad en
# tests/test_i17_p_replicas.py; la instantánea (huella, edad y cobertura) la comprueba _instantanea en c_montados.
EDAD_MAXIMA_DIAS_R = 31
HORAS_R = Decimal(730)
TIEMPO_R = {"1 Hour": (HORAS_R, "h"), "1/Hour": (HORAS_R, "h"), "1 GiB Hour": (HORAS_R, "GiB·h"),
            "1/Day": (HORAS_R / 24, "días"), "1/Month": (Decimal(1), "mes"),
            "1 GB/Month": (Decimal(1), "GB·mes")}   # I1.8 (N7): almacenamiento aprovisionado
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
            pls, fa = plantillas_auxiliar_replica(a, catalogo)
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
                salida.append(_plano_req_replica(e.get("valor")))
    sec = None
    for ln in _lineas_req_replica(brief_texto):
        if ln.startswith("#"):
            sec = DIM_SEC_R.get(ln.strip())
            continue
        valor = ln[2:] if (ln.startswith("- ") and sec) else next((ln[len(e):] for e, _ in DIM_ETQ_R if ln.startswith(e)), None)
        if valor is None:
            continue
        valor = valor[:-len(MARCA_R)] if valor.endswith(MARCA_R) else valor
        salida += [_plano_req_replica(valor)] + [_plano_req_replica(x) for x in valor.split("; ")]
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
    c = [_raiz_r(t) for t in _tokens(cita)]
    u = [_raiz_r(t) for t in _tokens(unidad)]
    if bases:
        r = [_raiz_r(t) for b in bases for t in _tokens(b) if len(t) >= 4]
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
                           "sha256": inst.get("sha256"), "moneda": inst.get("moneda"), "fuente": inst.get("fuente"),
                           **({} if inst.get("pilar", "azure") == "azure" else {   # multinube: procedencia del euro
                               k: inst[k] for k in ("pilar", "fuente_moneda", "tipo_bce", "fecha_tipo_bce") if k in inst})},
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


# ── REV17-1: tramos sobre la cantidad agregada por plantilla (sustituye a _precios_r) ──────────────────────────────
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
        d = dt.date.fromisoformat(str(fecha)[:10]) + dt.timedelta(days=7 * int(semanas or 0))
    except (ValueError, TypeError):
        return None
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


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


def es_contrato_experto_v3(resp: object) -> bool:
    """Respuesta de I1.6 (contrato v3): ni v1 ni v2 (lleva justificacion_nivel) y sin valoracion_nucleo, que el núcleo
    añade desde I1.7 al completar lo que escribió el modelo."""
    comps = resp.get("componentes") if isinstance(resp, dict) else None
    return (isinstance(comps, list) and bool(comps) and not es_contrato_experto_v1(resp)
            and not es_contrato_experto_v2(resp) and "valoracion_nucleo" not in resp)


def fecha_oferta(ctx: Contexto) -> str:
    """Fecha de la oferta para el ciclo de vida: estimacion.entrada.fecha o, si falta, la del manifiesto."""
    f = ((ctx.carga.get("estimacion") or {}).get("entrada") or {}).get("fecha")
    return str(f) if f else str((ctx.manifiesto or {}).get("generado_ts") or "")[:10]


def _instantanea_de_confianza(ctx: Contexto) -> dict | None:
    ruta = pathlib.Path(getattr(ctx, "precios", None) or POR_DEFECTO["precios"])   # REVERIF17-4: contextos mínimos de las pruebas
    try:
        obj = json.loads(ruta.read_text(encoding="utf-8"), parse_constant=_sin_nan)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _contrato_i17(ctx: Contexto, c: Comprobacion) -> None:
    """I1.7 (decisiones 1 y 2 del comercial y del PM, CAMBIOS-I17-P §6): la respuesta guardada es la que compone el código
    desde lo que escribió el modelo, el catálogo local y la instantánea local de confianza (recompone y compara, LES-G-097);
    los motivos con condición y el ciclo de vida de los modelos se cumplen; y las réplicas dan lo mismo que el núcleo. Si
    algo no se puede contrastar, FALLA con el motivo (nunca en silencio)."""
    r = ctx.respuesta or {}
    if (es_contrato_experto_v1(r) or es_contrato_experto_v2(r) or es_contrato_experto_v3(r)
            or es_contrato_experto_v4(r)):
        return  # ya FALLA en _cobertura_precios: puerta de su época
    texto = (_brief_vigente(ctx) or {}).get("texto")
    req, cat = ctx.carga.get("requisitos"), ctx.catalogo_obj
    inst = _instantanea_de_confianza(ctx)
    usada = ((r.get("valoracion_nucleo") or {}).get("instantanea") or {}).get("sha256")
    try:
        modelo = proyectar_r(r)
    except (KeyError, TypeError, AttributeError) as e:
        c.falla(f"contrato v4: la respuesta guardada no se puede proyectar a lo que escribió el modelo: {type(e).__name__}")
        return
    rec = fallos = None
    if inst is None:
        c.falla("contrato v4: no hay instantánea local de confianza legible: no se puede recomponer la respuesta")
    elif usada != inst.get("sha256"):
        c.falla(f"contrato v4: la instantánea del paquete ({usada}) no es la del despliegue ({inst.get('sha256')}): la "
                "respuesta se completó con otros precios (decisión 1)")
    else:
        try:
            rec, fallos = completar_r(modelo, cat, inst, req, texto)
        except (KeyError, TypeError, AttributeError, ValueError, ArithmeticError) as e:
            c.falla(f"contrato v4: no se pudo recomponer la respuesta: {type(e).__name__}: {e}")
        else:
            for i, regla in fallos:
                c.falla(f"{i}: contrato v4: {regla}; lo que pone el código desde el catálogo y la instantánea no se puede "
                        "componer (CAMBIOS-I17-P §3)")
            if rec != r:
                c.falla("contrato v4: la respuesta guardada no es la que compone el código desde lo que escribió el modelo, "
                        "el catálogo y la instantánea de confianza (precio, cantidad, factor, referencia o ajuste "
                        "cambiados tras registrar; LES-G-097)")
    motivos = motivos_r(r, cat, req, texto)
    for cid, regla in motivos:
        c.falla(f"{cid}: motivo de no valoración: {regla}; «a_cargo_del_cliente» exige una entrada de «Lo que el "
                "cliente ya tiene o paga» que nombre el servicio (REV17-3) e «incluido_en_otro_componente» el "
                "componente y la inclusión declarada en el catálogo con fuente (decisión del PM, REV16-1 c)")
    fecha, semanas = fecha_oferta(ctx), semanas_r(modelo)
    hay_fecha = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha))
    if not hay_fecha:  # fallar cerrado con su motivo, no con un «modelo_no_disponible» engañoso
        c.falla("ciclo de vida del modelo: el paquete no trae la fecha de la oferta (estimacion.entrada.fecha ni "
                "generado_ts): no se puede comprobar")
    ciclo = ciclo_r(r, cat, fecha, semanas) if hay_fecha else []
    for pid, regla in ciclo:
        c.falla(f"{pid}: ciclo de vida del modelo: {regla}; ningún modelo cuya retirada publicada caiga antes de fecha de "
                f"la oferta ({fecha}) + Gantt ({semanas} semanas) + 12 meses (LES-G-036)")
    ex = _nucleo("experto")
    if ex is None:
        c.aviso("contrato v4: sin núcleo local; decide solo la réplica (no se ha contrastado)")
        return
    faltan = [n for n in ("completar", "proyectar_modelo", "errores_motivos", "errores_ciclo_vida", "duracion_gantt")
              if not hasattr(ex, n)]
    if faltan:
        c.falla(f"contrato v4: el núcleo local no tiene {', '.join(faltan)}: es anterior a I1.7 o distinto del "
                "desplegado; no se puede contrastar")
        return
    try:
        n_modelo = ex.proyectar_modelo(r)
        n_motivos = [(x["id"], x["regla"]) for x in ex.errores_motivos(r, cat, req, texto)]
        n_ciclo = ([(x["id"], x["regla"]) for x in ex.errores_ciclo_vida(r, cat, fecha, ex.duracion_gantt(n_modelo))]
                   if hay_fecha else [])
        n_rec = None
        if rec is not None:
            completada, errs = ex.completar(n_modelo, cat, inst, req, texto)
            n_rec = (completada, [(x["id"], x["regla"]) for x in errs])
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"contrato v4: no se pudo contrastar con nucleo.experto: {type(e).__name__}: {e}")
        return
    if n_modelo != modelo:
        c.falla("contrato v4: la proyección de la réplica y nucleo.experto.proyectar_modelo no dan lo mismo (LES-G-097)")
    if n_motivos != motivos or n_ciclo != ciclo:
        c.falla(f"contrato v4: motivos o ciclo de vida, réplica {motivos + ciclo} y núcleo {n_motivos + n_ciclo} no dan "
                "lo mismo (LES-G-097)")
    if rec is not None and n_rec != (rec, fallos):
        c.falla("contrato v4: la recomposición de la réplica y nucleo.experto.completar no dan lo mismo (LES-G-097)")


def filas_no_valoradas_replica(sin_precio: list[dict]) -> list[list[str]]:
    """Réplica de nucleo.pptx_revision.filas_no_valoradas: una fila por motivo, servicios «A, B y C» sin repetir."""
    grupos: dict[str, list[str]] = {}
    for x in sin_precio:
        grupos.setdefault(x["motivo"], []).append(x["servicio"])
    salida = []
    for motivo, nombres in grupos.items():
        n = list(dict.fromkeys(nombres))
        salida.append([n[0] if len(n) == 1 else ", ".join(n[:-1]) + " y " + n[-1], motivo, "No valorado"])
    return salida


def c_diagrama(ctx: Contexto) -> Comprobacion:
    """P10 · Diagrama completo (LES-G-062): una forma por componente, un conector pegado por flujo, ningún conector que corte el texto de una forma y ninguno que comparta tramo, punto o cruce junto a un extremo con otro, ni que pase pegado a otra forma, ni a la suya tras salir de ella, y con la página de cada componente en el pie."""
    from collections import Counter
    c = Comprobacion("diagrama", c_diagrama.__doc__.split("·")[1].strip())
    diapos = ctx.pptx().diapositivas
    if len(diapos) < 4:
        c.falla("el PPTX no tiene diapositiva 4 (arquitectura)")
        return c
    d4 = diapos[3]
    pr = _nucleo("pptx_revision")  # sin núcleo (pruebas aisladas), manda la réplica (I1.7: también en la rama de la tabla)
    comps = ctx.respuesta.get("componentes", [])
    # I1.9 (CAMBIOS-I19-D §2.3): un sistema del cliente se llama «<nombre> (sistema del cliente)»
    nombres, campos = {}, (ctx.carga.get("requisitos") or {}).get("campos") or {}
    entradas = {str(e.get("id")): e for e in (campos.get("ya_contratado_por_cliente") or {}).get("entradas") or []
                if isinstance(e, dict) and e.get("id")}
    for x in comps:
        oficial = _nombre_componente(ctx, x)
        ex = x.get("existente_del_cliente")
        if ex is None:
            nombres[x.get("id")] = oficial
            continue
        entrada = entradas.get(str((ex or {}).get("entrada") if isinstance(ex, dict) else ""))
        publicado = str(next((k.get("nombre") for capa in ((ctx.carga.get("textos_cliente") or {}).get("arquitectura")
                              or {}).get("capas") or [] for k in capa.get("componentes") or []
                              if k.get("id") == x.get("id")), "") or "")
        base = publicado[:-len(" (sistema del cliente)")] if publicado.endswith(" (sistema del cliente)") else None
        # cierre (16-10, Revisión): el valor citado ENTERO sin el determinante inicial ni la puntuación final, nunca un
        # trozo cualquiera («A (sistema del cliente)» pasaba con el valor «la API REST de RR. HH.»)
        citado = re.sub(r"^(?:el|la|los|las|un|una|unos|unas|su|sus|mi|mis|nuestro|nuestra|nuestros|nuestras)\s+", "",
                        re.sub(r"\s+", " ", str((entrada or {}).get("valor") or "")).strip(), flags=re.I)
        es_citado = base is not None and 3 <= len(base) <= 50 and plano(base).rstrip(" .;,:") == plano(citado).rstrip(" .;,:")
        if entrada is None or base is None or not (base == oficial or es_citado):
            c.falla(f"diagrama: {x.get('id')} es un sistema del cliente y su nombre «{publicado}» no es el oficial ni un "
                    "valor citado sin su determinante, con « (sistema del cliente)» (I1.9)")
        nombres[x.get("id")] = publicado
    formas, conectores = _formas(d4)
    texto4 = plano(_texto_diapo(d4))
    if "diagrama simplificado en tabla" in texto4:
        celdas = {plano(cel) for t in d4.tablas for fila in t for cel in fila}
        faltan = [n for n in nombres.values() if plano(n) not in celdas]
        if faltan:
            c.falla(f"tabla de arquitectura sin los componentes {faltan}")
        else:
            c.aviso("diagrama sustituido por tabla con aviso (LES-G-062): revisar si era evitable")
        faltan = referencias_faltan_replica(d4.raiz, ctx.respuesta)  # REVERIF16-3 (I1.7): el pie va en los dos modos
        for f in faltan:
            c.falla(f"diagrama: {f} (REVERIF16-3, LES-G-062)")
        if pr is not None and not hasattr(pr, "referencias_faltan"):
            c.falla("diagrama: el núcleo no tiene referencias_faltan; no se puede contrastar la réplica (núcleo antiguo)")
        elif pr is not None and pr.referencias_faltan(d4.raiz, ctx.respuesta) != faltan:
            c.falla("diagrama: la réplica de referencias y nucleo.pptx_revision.referencias_faltan discrepan (LES-G-097)")
        return c
    esperados = Counter(plano(n) for n in nombres.values())
    hallados = Counter(plano(t) for _, t in formas if plano(t) in esperados)
    for n, k in esperados.items():
        if hallados.get(n, 0) != k:
            c.falla(f"diagrama: «{n}» aparece en {hallados.get(n, 0)} formas y hay {k} componentes")
    id_forma: dict[str, list[str]] = {}
    for fid, t in formas:
        id_forma.setdefault(plano(t), []).append(fid)
    for cx in conectores:
        if cx[2]:
            c.falla(f"conector con texto «{cx[2][:40]}» (deben ir sin texto)")
        if cx[0] is None or cx[1] is None:
            c.falla("conector sin pegar por los dos extremos")
    pares = [(st, en) for st, en, _ in conectores]
    for fl in ctx.respuesta.get("flujos", []):
        o = id_forma.get(plano(nombres.get(fl.get("origen"), "")), [])
        de = id_forma.get(plano(nombres.get(fl.get("destino"), "")), [])
        if not any((st in o and en in de) or (st in de and en in o) for st, en in pares):
            c.falla(f"flujo {fl.get('origen')} → {fl.get('destino')} sin conector pegado entre sus formas")
    # VA18-6 (I1.9, CAMBIOS-I19-D §2.3): convención fija «servicio → identidad»
    capa_de = {plano(nombres.get(x.get("id"), "")): x.get("capa") for x in comps}
    texto_de = {fid: plano(t) for fid, t in formas}
    for st, en, _ in conectores:
        if capa_de.get(texto_de.get(st)) == "identidad_seguridad_red" and capa_de.get(texto_de.get(en)) != "identidad_seguridad_red":
            c.falla("diagrama: una flecha sale de un componente de identidad; la convención es «servicio → identidad» (VA18-6)")
    formas_geo = formas_diagrama(d4)
    solapes = solapes_diagrama_replica(formas_geo)
    for s in solapes:
        c.falla(f"diagrama: {s} (ARR13-2, LES-G-062)")
    if pr is not None and not hasattr(pr, "solapes_diagrama"):
        c.falla("diagrama: el núcleo no tiene solapes_diagrama; no se puede contrastar la réplica (núcleo antiguo)")
    elif pr is not None and pr.solapes_diagrama(formas_geo) != solapes:
        c.falla("diagrama: la réplica de solapes y nucleo.pptx_revision.solapes_diagrama discrepan (LES-G-097)")
    cortes = cortes_conectores_replica(d4.raiz)  # PR14-3 (I1.5, CAMBIOS-I15-D §2)
    for s in cortes:
        c.falla(f"diagrama: {s} (PR14-3, LES-G-072)")
    if pr is not None and not hasattr(pr, "cortes_conectores"):
        c.falla("diagrama: el núcleo no tiene cortes_conectores; no se puede contrastar la réplica (núcleo antiguo)")
    elif pr is not None and pr.cortes_conectores(d4.raiz) != cortes:
        c.falla("diagrama: la réplica de cortes y nucleo.pptx_revision.cortes_conectores discrepan (LES-G-097)")
    separacion = separacion_conectores_replica(d4.raiz)  # ARR15-2/D15-4 (I1.6, CAMBIOS-I16-D §2)
    for s in separacion:
        c.falla(f"diagrama: {s} (ARR15-2, LES-G-072)")
    if pr is not None and not hasattr(pr, "separacion_conectores"):
        c.falla("diagrama: el núcleo no tiene separacion_conectores; no se puede contrastar la réplica (núcleo antiguo)")
    elif pr is not None and pr.separacion_conectores(d4.raiz) != separacion:
        c.falla("diagrama: la réplica de separación y nucleo.pptx_revision.separacion_conectores discrepan (LES-G-097)")
    legibilidad = legibilidad_conectores_replica(d4.raiz)  # VA18-6 (I1.9, CAMBIOS-I19-D §2.2)
    for s in legibilidad:
        c.falla(f"diagrama: {s} (VA18-6, LES-G-072)")
    if pr is not None and not hasattr(pr, "legibilidad_conectores"):
        c.falla("diagrama: el núcleo no tiene legibilidad_conectores; no se puede contrastar la réplica (núcleo antiguo)")
    elif pr is not None and pr.legibilidad_conectores(d4.raiz) != legibilidad:
        c.falla("diagrama: la réplica de legibilidad y nucleo.pptx_revision.legibilidad_conectores discrepan (LES-G-097)")
    faltan = referencias_faltan_replica(d4.raiz, ctx.respuesta)  # REVERIF16-3 (I1.7, CAMBIOS-I17-D §2)
    for f in faltan:
        c.falla(f"diagrama: {f} (REVERIF16-3, LES-G-062)")
    if pr is not None and not hasattr(pr, "referencias_faltan"):
        c.falla("diagrama: el núcleo no tiene referencias_faltan; no se puede contrastar la réplica (núcleo antiguo)")
    elif pr is not None and pr.referencias_faltan(d4.raiz, ctx.respuesta) != faltan:
        c.falla("diagrama: la réplica de referencias y nucleo.pptx_revision.referencias_faltan discrepan (LES-G-097)")
    if len(conectores) != len(ctx.respuesta.get("flujos", [])):
        c.aviso(f"{len(conectores)} conectores para {len(ctx.respuesta.get('flujos', []))} flujos")
    return c


def _fila_con(tablas: list[list[list[str]]], primera: str) -> list[str] | None:
    for t in tablas:
        for fila in t:
            if fila and plano(fila[0]) == plano(primera):
                return fila
    return None


def _fila_propia(tablas: list[list[list[str]]], primera: str, concepto: object, usadas: list[int]) -> list[str] | None:
    """VER13-1 (I1.3): una fila PROPIA por línea del anexo. Un servicio con dos precios (Foundry: tokens de entrada y de
    salida) tiene dos filas con el mismo nombre: se busca la que además lleva su concepto y no se ha usado ya. Antes se
    tomaba siempre la primera y la segunda línea daba un falso FALLA."""
    filas = [(id(f), f) for t in tablas for f in t if f and plano(f[0]) == plano(primera) and id(f) not in usadas]
    if isinstance(concepto, str) and concepto.strip():
        # Revisión (I1.3): con concepto, la fila tiene que llevarlo; sin él no se elige otra del mismo servicio.
        elegida = next(((i, f) for i, f in filas if len(f) > 1 and plano(f[1]) == plano(concepto)), None)
    else:
        elegida = filas[0] if filas else None
    if elegida is None:
        return None
    usadas.append(elegida[0])
    return elegida[1]


def c_coherencia(ctx: Contexto) -> Comprobacion:
    """P11 · Coherencia PPTX-XLSX-anexo y textos atados a sus hechos (LES-G-093/094)."""
    c = Comprobacion("coherencia", c_coherencia.__doc__.split("·")[1].strip())
    p, x, carga = ctx.pptx(), ctx.xlsx(), ctx.carga
    tc, anexo = carga.get("textos_cliente") or {}, carga.get("anexo_consumo") or {}
    diapos = {d.numero: d for d in p.diapositivas}
    if len(diapos) != 10:
        c.falla(f"el PPTX tiene {len(diapos)} diapositivas; el contrato fija 10")
    d7, d8 = diapos.get(7), diapos.get(8)
    if d7 is not None:
        if x.precio not in importes_en(_texto_diapo(d7)):
            c.falla(f"diapositiva 7: no muestra el precio cerrado recalculado {x.precio} EUR")
        for h in x.hitos:
            fila = _fila_con(d7.tablas, h["nombre"])
            if fila is None or h["importe"] not in importes_en(" ".join(fila)):
                c.falla(f"diapositiva 7: hito «{h['nombre']}» sin fila o con importe ≠ {h['importe']}")
    _exclusividad_importes(ctx, c, diapos, x)
    _firmas_diapositiva_2(ctx, c, diapos.get(2))
    _portada(ctx, c, diapos.get(1), tc)
    if d8 is not None:
        t8 = importes_en(_texto_diapo(d8))
        for k in ("total_mensual_eur", "total_anual_eur"):
            if dec(anexo.get(k, "-1")) not in t8:
                c.falla(f"diapositiva 8: no muestra {k} = {anexo.get(k)} del anexo")
        usadas: list[int] = []
        conceptos = [x.get("concepto") for x in (tc.get("consumo") or {}).get("lineas", [])]
        if len(conceptos) != len(anexo.get("lineas", [])):
            c.falla(f"diapositiva 8: textos_cliente.consumo tiene {len(conceptos)} líneas y el anexo "
                    f"{len(anexo.get('lineas', []))}")
        for i, ln in enumerate(anexo.get("lineas", [])):
            serv = ln.get("servicio") or ln.get("nombre_oficial") or ""
            # REV13-3: la fila lleva el concepto legible de textos_cliente (recompuesto en local por R1), no el meterName
            fila = _fila_propia(d8.tablas, serv, conceptos[i] if i < len(conceptos) else None, usadas)
            coste = ln.get("coste_mensual_eur")
            if fila is None or (coste is not None and dec(coste) not in importes_en(" ".join(fila))):
                c.falla(f"diapositiva 8: línea «{serv}» sin fila o con coste ≠ {coste}")
        ac = _nucleo("anexo_consumo")
        if ac and hasattr(ac, "no_valorados"):  # como antes: sin núcleo no hay lista de no valorados que exigir
            filas8 = [[plano(x) for x in f] for t in d8.tablas for f in t]
            esperadas = filas_no_valoradas_replica(ac.no_valorados(ctx.estado, ctx.catalogo_obj))
            for fila in esperadas:  # REV13-3: una fila por motivo con sus servicios, recompuesta en local
                if [plano(x) for x in fila] not in filas8:
                    c.falla(f"diapositiva 8: falta la fila «No valorado» de «{fila[0]}» ({fila[1]}) (LES-G-062)")
            sobrantes = sum(1 for f in filas8 if "no valorado" in f) - len(esperadas)
            if sobrantes > 0:  # exclusividad (LES-G-097.1): ninguna fila «No valorado» que el código no compone
                c.falla(f"diapositiva 8: {sobrantes} filas «No valorado» de más")
    _sin_precios_con_azure(ctx, c, "anexo de consumo", not anexo.get("lineas"))
    if dec((tc.get("precio") or {}).get("precio_cerrado_eur", "-1")) != x.precio:
        c.falla("textos_cliente.precio ≠ precio recalculado del XLSX")
    if dec((tc.get("consumo") or {}).get("total_mensual_eur", "-1")) != dec(anexo.get("total_mensual_eur", "-2")):
        c.falla("textos_cliente.consumo ≠ total mensual del anexo")
    base = {k: carga.get(k) for k in ("alta", "requisitos", "respuestas_expertos", "verificacion", "anexo_consumo")}
    base["estimacion_resumen"] = (carga.get("estimacion") or {}).get("resumen")
    if tc.get("hash_hechos") != hash_json(base):
        c.falla("textos_cliente.hash_hechos no cuadra: el texto no está atado a los hechos vigentes")
    if tc.get("codigo") != ctx.codigo:
        c.falla(f"textos_cliente.codigo {tc.get('codigo')} ≠ {ctx.codigo}")
    for capa in (tc.get("arquitectura") or {}).get("capas", []):
        for comp in capa.get("componentes", []):
            real = next((y for y in ctx.respuesta.get("componentes", []) if y.get("id") == comp.get("id")), None)
            if real is not None and isinstance(real.get("existente_del_cliente"), dict):
                # I1.9 (PR18-8, integrador): un sistema que ya tiene el cliente se llama «<nombre> (sistema del cliente)»
                if not _nombre_existente_valido(ctx, real, comp.get("nombre")):
                    c.falla(f"arquitectura: «{comp.get('nombre')}» no es el nombre de {comp.get('id')}, sistema del "
                            "cliente: el oficial o el valor citado sin su determinante, con « (sistema del cliente)» "
                            "(LES-G-093, I1.9)")
            elif real is None or comp.get("nombre") != _nombre_componente(ctx, real):
                c.falla(f"arquitectura: «{comp.get('nombre')}» no es el nombre oficial de {comp.get('id')} (LES-G-093)")
    _frases(ctx, c, tc, p)
    return c


def _nombre_existente_valido(ctx: Contexto, x: dict, publicado: object) -> bool:
    """I1.9 (PR18-8, integrador): misma regla que c_diagrama (CAMBIOS-I19-D §2.3) para el nombre publicado de un sistema
    del cliente: su entrada EX existe y el nombre es «<base> (sistema del cliente)», con <base> el oficial o el valor
    citado entero sin el determinante inicial ni la puntuación final (de 3 a 50 caracteres)."""
    campos = (ctx.carga.get("requisitos") or {}).get("campos") or {}
    entradas = {str(e.get("id")): e for e in (campos.get("ya_contratado_por_cliente") or {}).get("entradas") or []
                if isinstance(e, dict) and e.get("id")}
    ex = x.get("existente_del_cliente")
    entrada = entradas.get(str(ex.get("entrada") if isinstance(ex, dict) else ""))
    publicado = str(publicado or "")
    sufijo = " (sistema del cliente)"
    if entrada is None or not publicado.endswith(sufijo):
        return False
    base = publicado[:-len(sufijo)]
    citado = re.sub(r"^(?:el|la|los|las|un|una|unos|unas|su|sus|mi|mis|nuestro|nuestra|nuestros|nuestras)\s+", "",
                    re.sub(r"\s+", " ", str(entrada.get("valor") or "")).strip(), flags=re.I)
    return base == _nombre_componente(ctx, x) or (
        3 <= len(base) <= 50 and plano(base).rstrip(" .;,:") == plano(citado).rstrip(" .;,:"))


def _exclusividad_importes(ctx: Contexto, c: Comprobacion, diapos: dict[int, Diapositiva], x: XlsxCanonico) -> None:
    """H-V2 · LES-G-097.1: todo importe que ve el cliente es el precio o un hito recalculado (diapositivas 7 y 10) o un
    importe del anexo (diapositiva 8, VA18-1).

    En las 7 y 10, que el precio aparezca no basta: cualquier otra cifra monetaria, o cualquier cifra de 100 o más que
    no sea un importe permitido (un precio escrito sin «€»), hace FALLA. En la 8, toda cifra monetaria es una línea o
    un total del anexo. En las demás diapositivas, en el texto alternativo y en los diseños y patrones, ninguna cifra
    junto a €, EUR o euros (cada cifra de una serie: «entre 25.000 y 60.000 euros»).

    VA18-1 (I1.9): por qué pasó «entre 25.000 y 60.000 euros» en la diapositiva 6 de Hostelia. Esta comprobación solo
    recorría las diapositivas 7 y 10, y ninguna otra miraba importes; además, la primera cifra de la serie no va pegada
    a la moneda y _MONEDA_DESPUES solo veía la segunda.
    """
    permitidos = {x.precio} | {h["importe"] for h in x.hitos}
    anexo = ctx.carga.get("anexo_consumo") or {}
    del_anexo: set[Decimal] = set()
    for v in [ln.get("coste_mensual_eur") for ln in anexo.get("lineas") or [] if isinstance(ln, dict)] + [
            anexo.get("total_mensual_eur"), anexo.get("total_anual_eur")]:
        try:
            del_anexo.add(dec(v))
        except ValueError:
            pass  # una línea sin coste no admite ninguna cifra; el resto de c_coherencia ya la señala
    huella = ctx.hash_vigente()
    for n, d in sorted(diapos.items()):
        texto = _texto_diapo(d).replace(ctx.codigo, " ").replace(huella, " ")
        if n in (7, 10):
            for literal, lecturas in cifras_monetarias(texto) + cifras_sueltas(texto):
                if not lecturas & permitidos:
                    c.falla(f"diapositiva {n}: importe «{literal}» que no es el precio cerrado {x.precio} EUR "
                            f"ni un hito recalculado del XLSX (H-V2, LES-G-097)")
        elif n == 8:
            for literal, lecturas in cifras_monetarias(texto):
                if not lecturas & del_anexo:
                    c.falla(f"diapositiva 8: importe «{literal}» que no es una línea ni un total del anexo de consumo "
                            "(LES-G-097.1)")
        else:
            for literal, _ in cifras_con_moneda(texto):
                c.falla(f"diapositiva {n}: importe «{literal}» fuera de las diapositivas de precio y consumo: el cliente "
                        "solo ve el precio cerrado, los hitos y el anexo (VA18-1, LES-G-053, LES-G-097.1)")
    for donde, texto in textos_fuera_de_diapositivas(ctx.pptx().partes):
        for literal, _ in cifras_con_moneda(texto):
            c.falla(f"{donde}: importe «{literal}» que el cliente ve fuera de las diapositivas de precio y consumo "
                    "(VA18-1, VPROT-1)")


def textos_fuera_de_diapositivas(partes: dict) -> list[tuple[str, str]]:
    """VPROT-1 (I1.9): texto que el cliente ve o escucha y que no está en los párrafos de las diapositivas: el texto
    alternativo (`descr` y `title` de cada `cNvPr`), que lee un lector de pantalla, de las diapositivas, los diseños y
    los patrones; y los párrafos de los diseños y patrones, que se dibujan en la diapositiva. [(dónde, texto)].
    Una parte que no se puede leer lanza la excepción: quien llama falla en alto."""
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    salida = []
    for nombre in sorted(partes):
        diseno = re.fullmatch(r"ppt/(?:slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml", nombre)
        if not (diseno or re.fullmatch(r"ppt/slides/slide\d+\.xml", nombre)):
            continue
        raiz = etree.fromstring(partes[nombre], parser)
        for el in raiz.iter():
            if isinstance(el.tag, str) and etree.QName(el).localname == "cNvPr":
                salida += [(f"texto alternativo ({nombre})", el.get(k)) for k in ("descr", "title")
                           if (el.get(k) or "").strip()]
        if diseno:
            salida += [(f"diseño o patrón ({nombre})", x) for x in _texto_parrafos(raiz, "a") if x.strip()]
    return salida


def firmas_esperadas(ctx: Contexto) -> dict[str, str]:
    """Texto de «Revisado por» y «Aprobado por» que deben verse según estado.decisiones (H-V3).

    Misma regla que nucleo.decision.firmas: la última APROBADA de cada revisor que cite el hash vigente.
    """
    vigente, salida = ctx.hash_vigente(), {}
    for clave, persona in (("revisado", "REVISOR"), ("aprobado", "APROBADOR")):
        d = next((d for d in reversed(ctx.estado.get("decisiones") or []) if d.get("tipo") == "APROBADA"
                  and d.get("version") == ctx.estado.get("version") and d.get("hash_citado") == vigente
                  and PERSONAS.get(plano(d.get("revisor") or "")) == persona), None)
        salida[clave] = f"{FIRMANTES[persona]}, {d.get('fecha')}" if d else "Sin firma"
    return salida


def _firmas_diapositiva_2(ctx: Contexto, c: Comprobacion, d2: Diapositiva | None) -> None:
    """H-V3: la tabla de firmas refleja las decisiones vigentes y el estado del paquete."""
    if d2 is None:
        return
    tablas = [t for t in d2.tablas if t and [nfc(x).strip() for x in t[0]] == CABECERA_FIRMAS]
    if len(tablas) != 1 or len(tablas[0]) != 2 or len(tablas[0][1]) != 5:
        c.falla(f"diapositiva 2: debe haber una sola tabla de firmas {CABECERA_FIRMAS} con una fila")
        return
    version, fecha, elaborado, revisado, aprobado = (nfc(x).strip() for x in tablas[0][1])
    esperadas, estado = firmas_esperadas(ctx), ctx.estado.get("estado")
    fechas = {str(((ctx.carga.get("estimacion") or {}).get("entrada") or {}).get("fecha", "")),
              str((ctx.carga.get("textos_cliente") or {}).get("portada", {}).get("fecha", ""))}
    if version != ctx.estado.get("version"):
        c.falla(f"diapositiva 2: versión «{version}» ≠ {ctx.estado.get('version')!r} del estado")
    if fecha not in fechas or elaborado != "Responsable comercial (RC)":
        c.falla(f"diapositiva 2: fecha «{fecha}» o «Elaborado por» «{elaborado}» no son los de la elaboración")
    for etiqueta, visto, clave in (("Revisado por", revisado, "revisado"), ("Aprobado por", aprobado, "aprobado")):
        if visto != esperadas[clave]:
            c.falla(f"diapositiva 2: «{etiqueta}» dice «{visto}» y las decisiones vigentes dan «{esperadas[clave]}»")
    if estado in ESTADOS_PAQUETE[2:] and revisado == "Sin firma":
        c.falla(f"diapositiva 2: estado {estado} con «Revisado por» sin firma (H-V3)")
    if estado == "APROBADA" and aprobado == "Sin firma":
        c.falla("diapositiva 2: estado APROBADA con «Aprobado por» sin firma (H-V3)")
    if estado in ESTADOS_PAQUETE[:2] and (revisado, aprobado) != ("Sin firma", "Sin firma"):
        c.falla(f"diapositiva 2: estado {estado} con firmas que el estado no justifica")


SUBTITULO_APROBADA = "Propuesta comercial · versión {version}"  # réplica de nucleo.pptx_revision (H13)


def subtitulo_portada(ctx: Contexto, tc: dict) -> str:
    """Subtítulo que corresponde al estado: el de APROBADA o el de textos_cliente (H13)."""
    if ctx.estado.get("estado") == "APROBADA":
        pr = _nucleo("pptx_revision")
        plantilla = getattr(pr, "SUBTITULO_APROBADA", SUBTITULO_APROBADA) if pr else SUBTITULO_APROBADA
        return plantilla.format(version=ctx.estado.get("version") or "")
    return nfc(str((tc.get("portada") or {}).get("subtitulo", ""))).strip()


def _portada(ctx: Contexto, c: Comprobacion, d1: Diapositiva | None, tc: dict) -> None:
    """H-V3: la portada solo dice lo que fija textos_cliente.portada (título, cliente, código, fecha)."""
    if d1 is None:
        return
    pt = tc.get("portada") or {}
    subtitulo = subtitulo_portada(ctx, tc)
    permitidos = {nfc(str(pt.get(k, ""))).strip() for k in ("titulo", "cliente", "codigo", "fecha")} | {subtitulo}
    permitidos.add(f"Fecha: {pt.get('fecha', '')}")
    vistos = [nfc(t).strip() for t in d1.textos if t.strip()]
    if subtitulo not in vistos:
        c.falla(f"portada: el subtítulo para el estado {ctx.estado.get('estado')} es «{subtitulo}» y no aparece (H13, H-V3)")
    for t in vistos:
        if t not in permitidos:
            c.falla(f"portada: texto «{t[:60]}» que no sale de textos_cliente.portada")
    for k in ("titulo", "cliente", "codigo"):
        if nfc(str(pt.get(k, ""))).strip() not in vistos:
            c.falla(f"portada: no muestra {k} = {pt.get(k)!r}")
    if pt.get("codigo") != ctx.codigo:
        c.falla(f"portada: código {pt.get('codigo')!r} ≠ {ctx.codigo}")


def _frases(ctx: Contexto, c: Comprobacion, tc: dict, p: Pptx) -> None:
    """LES-G-094: cada frase cita hechos existentes y aparece publicada; las excluidas no."""
    r = ctx.respuesta
    validos = {f"R-{k}" for k in ((ctx.carga.get("requisitos") or {}).get("campos") or {})}
    for clave in ("referencias", "componentes", "precios", "supuestos", "riesgos"):
        validos |= {y.get("id") for y in r.get(clave, [])}
    publicado = plano(" ".join(" ".join(d.textos) for d in p.diapositivas))
    for seccion in ("necesidad", "alcance", "fuera_de_alcance", "supuestos", "riesgos", "condiciones"):
        for f in tc.get(seccion, []):
            hechos = f.get("hechos") or []
            malos = [h for h in hechos if h not in validos and h not in HECHOS_FIJOS]
            if not hechos or malos:
                c.falla(f"{f.get('id')}: frase sin hechos o con hechos inexistentes {malos}")
            if plano(f.get("texto", "")) not in publicado:
                c.falla(f"{f.get('id')}: la frase compuesta no aparece en el PPTX")
    for f in tc.get("excluidas", []):
        if len(plano(f.get("texto", ""))) >= 12 and plano(f.get("texto", "")) in publicado:
            c.falla(f"frase excluida publicada en el PPTX: «{f.get('texto', '')[:60]}»")
    _alcance_incluido(ctx, c, tc, p)


def _alcance_incluido(ctx: Contexto, c: Comprobacion, tc: dict, p: Pptx) -> None:
    """VA19-1 (I1.10): «Incluido» (diapositiva 5) lleva cada entrada de requisitos.alcance_funcional. Solo se admite que
    falte si textos_cliente.excluidas la retira por su forma con su motivo; «repite el objetivo» ya no saca nada del
    alcance (la frase solo se omite en «Capacidades principales», donde el objetivo está a la vista)."""
    campos = (ctx.carga.get("requisitos") or {}).get("campos") or {}
    entradas = (campos.get("alcance_funcional") or {}).get("entradas") or []
    if not entradas:
        return
    if len(p.diapositivas) < 5:
        c.falla("el PPTX no tiene diapositiva 5 («Incluido»): no se puede comprobar el alcance (VA19-1)")
        return
    # ARR1 (Revisión): solo la columna «Incluido», del párrafo de su título al de «Fuera de alcance»; un requisito que
    # aparezca en la otra columna no cuenta como incluido. Sin los dos títulos en ese orden, falla cerrado.
    parrafos = [nfc(t).strip() for t in p.diapositivas[4].textos]
    try:
        if parrafos.count("Incluido") != 1 or parrafos.count("Fuera de alcance") != 1:
            raise ValueError("títulos repetidos")  # ARR1 (Revisión 2): un «Incluido» suelto no abre la columna
        ini = parrafos.index("Incluido")
        fin = parrafos.index("Fuera de alcance", ini + 1)
    except ValueError:
        c.falla("la diapositiva 5 no tiene las columnas «Incluido» y «Fuera de alcance», una vez y en ese orden: no se puede "
                "comprobar el alcance (VA19-1)")
        return
    incluido = plano(" ".join(parrafos[ini + 1:fin]))
    retiradas = [(plano(f.get("texto", "")), plano(f.get("motivo", ""))) for f in tc.get("excluidas", [])
                 if str(f.get("origen", "")).startswith("requisito alcance_funcional")]
    for e in entradas:
        v = plano(str(e.get("valor") or "")).rstrip(" .;,:")
        if not v or v in incluido:
            continue
        motivo = next((m for t, m in retiradas if t.rstrip(" .;,:") == v), None)
        if motivo is None or "repite el objetivo" in motivo:
            c.falla(f"alcance_funcional «{str(e.get('valor'))[:70]}» no está en «Incluido» (diapositiva 5)"
                    + (f" y se retiró por «{motivo[:60]}»" if motivo else "") + " (VA19-1)")


def c_recomposicion(ctx: Contexto) -> Comprobacion:
    """P11b · Recomposición local (LES-G-097.2): textos, PPTX y XLSX = los que da el código de confianza."""
    c = Comprobacion("recomposicion", c_recomposicion.__doc__.split("·")[1].strip())
    faltan = [m for m in ("textos_cliente", "pptx_revision", "estimacion", "decision", "hashes", "verificacion")
              if not (DIR_SANDBOX / "nucleo" / f"{m}.py").is_file()]
    if faltan:
        c.falla(f"no se puede recomponer en local: falta sandbox/nucleo/{faltan} (la puerta no se fía del sandbox)")
        return c
    _recomponer_textos(ctx, c)
    _recomponer_consolidado(ctx, c)
    _recomponer_pptx(ctx, c)
    _recomponer_xlsx(ctx, c)
    _cambios_pedidos(ctx, c)
    if c.estado == FALLA:
        cambiados = nucleo_distinto_del_desplegado()
        if cambiados:
            c.nota(f"diagnóstico: el núcleo local no es el desplegado según manifiesto.json en {cambiados}; "
                   "un paquete del despliegue anterior no pasa hasta redesplegar (no es un fallo que se pueda "
                   "dar por bueno: la puerta compara con el código vigente del repositorio)")
    return c


def _cambios_pedidos(ctx: Contexto, c: Comprobacion) -> None:
    """VER16-5 (I1.7) y VER17-2 (I1.8): en una versión abierta por una DEVUELTA, la nota del revisor lleva «Cambios
    pedidos en la revisión anterior» (comentario literal, cómo se atendió y nombres legibles), recompuesta con
    nucleo.nota_revision.lineas_cambios_nota (LES-G-097.2), cada línea en su párrafo (LES-G-077). El PPTX no la
    lleva: lo exige _revision_interna en c_cliente."""
    nr = _nucleo("nota_revision")
    if nr is None or not hasattr(nr, "lineas_cambios_nota"):
        c.falla("cambios pedidos: el núcleo local no tiene nota_revision.lineas_cambios_nota (anterior a I1.8)")
        return
    try:
        nota = nr.lineas_cambios_nota(ctx.estado, ctx.catalogo_obj)
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"cambios pedidos: no se pudieron recomponer: {type(e).__name__}: {e}")
        return
    if not nota:
        return
    try:
        parrafos = {plano(x) for x in ctx.docx()[0]}
    except (KeyError, OSError, zipfile.BadZipFile) as e:
        c.falla(f"cambios pedidos: no se pudo leer la nota: {e}")
        return
    faltan = [x for x in nota if plano(x) not in parrafos]
    for x in faltan[:5]:
        c.falla(f"nota del revisor sin la línea de «Cambios pedidos en la revisión anterior»: {x[:140]!r} (VER16-5)")
    if not faltan:
        c.nota(f"cambios pedidos en la revisión anterior: {len(nota)} línea(s) en la nota del revisor, ninguna en el PPTX")


def nucleo_distinto_del_desplegado(manifiesto: pathlib.Path | None = None) -> list[str]:
    """Módulos de sandbox/nucleo cuyo SHA-256 no es el de manifiesto.json (diagnóstico, nunca un aprobado)."""
    ruta = manifiesto or RAIZ / "manifiesto.json"
    try:
        ficheros = json.loads(ruta.read_text(encoding="utf-8")).get("ficheros") or {}
    except (OSError, ValueError):
        return ["manifiesto.json ilegible"]
    distintos = []
    for nombre, info in sorted(ficheros.items()):
        if not nombre.startswith("nucleo_") or not isinstance(info, dict):
            continue
        local = DIR_SANDBOX / "nucleo" / ("__init__.py" if nombre == "nucleo_init.py" else nombre[len("nucleo_"):])
        if not local.is_file() or sha256_fichero(local) != info.get("sha256"):
            distintos.append(local.name)
    return distintos


def _recomponer_textos(ctx: Contexto, c: Comprobacion) -> None:
    """R1: textos_cliente = nucleo.textos_cliente.componer con el catálogo y la tarifa locales."""
    tcm = _nucleo("textos_cliente")
    publicado = ctx.carga.get("textos_cliente") or {}
    try:
        local = tcm.componer(ctx.estado, ctx.catalogo_obj, ctx.tarifa)
    except Exception as e:  # noqa: BLE001 - un error del núcleo es FALLA con su motivo, nunca un aprobado
        c.falla(f"textos_cliente: componer en local falla ({type(e).__name__}: {e}; "
                f"{list(getattr(e, 'errores', []) or [])[:3]})")
        return
    if local == publicado:
        c.nota("textos_cliente: idénticos a los recompuestos en local con el catálogo y la tarifa de confianza")
        return
    for k in sorted(set(local) | set(publicado)):
        if local.get(k) == publicado.get(k):
            continue
        a, b = local.get(k), publicado.get(k)
        if isinstance(a, list) and isinstance(b, list):
            ia = {x.get("id"): x for x in a if isinstance(x, dict)}
            ib = {x.get("id"): x for x in b if isinstance(x, dict)}
            difs = sorted(i for i in set(ia) | set(ib) if ia.get(i) != ib.get(i)) or ["orden"]
            c.falla(f"textos_cliente.{k}: distinto del recompuesto en local en {difs[:6]} (R1, LES-G-097)")
        else:
            c.falla(f"textos_cliente.{k}: distinto del recompuesto en local (R1, LES-G-097)")


def _recomponer_pptx(ctx: Contexto, c: Comprobacion) -> None:
    """El PPTX publicado = nucleo.pptx_revision.construir(estado, catálogo local), parte a parte."""
    pr = _nucleo("pptx_revision")
    try:
        prs, _ = pr.construir(ctx.estado, ctx.catalogo_obj)
        buf = io.BytesIO()
        prs.save(buf)
    except Exception as e:  # noqa: BLE001
        c.falla(f"PPTX: construir en local falla ({type(e).__name__}: {e}; {list(getattr(e, 'errores', []) or [])[:3]})")
        return
    ruta = ctx.tmp / "recompuesto.pptx"
    ruta.write_bytes(buf.getvalue())
    local, publicado = leer_pptx(ruta), ctx.pptx()
    for parte in sorted(set(local.partes) - set(publicado.partes)):
        c.falla(f"PPTX: falta la parte {parte} que genera el código")
    for parte in sorted(set(publicado.partes) - set(local.partes)):
        c.falla(f"PPTX: sobra la parte {parte}, que el código no genera")
    distintas = [x for x in sorted(set(local.partes) & set(publicado.partes)) if local.partes[x] != publicado.partes[x]]
    textos_l = {d.parte: d for d in local.diapositivas}
    for parte in distintas:
        d_l = textos_l.get(parte)
        d_p = next((d for d in publicado.diapositivas if d.parte == parte), None)
        if d_l is not None and d_p is not None and (d_l.textos != d_p.textos or d_l.tablas != d_p.tablas):
            dif = next(((a, b) for a, b in zip(d_l.textos + [""], d_p.textos + [""]) if a != b), ("", ""))
            c.falla(f"PPTX diapositiva {d_p.numero}: el texto no es el recompuesto en local "
                    f"(se esperaba «{dif[0][:50]}», hay «{dif[1][:50]}»)")
        else:
            c.falla(f"PPTX: la parte {parte} no es byte a byte la que genera el código (forma, posición, "
                    "formato u oculto; si solo difiere la versión de python-pptx del sandbox, alinearla)")
    if not distintas and set(local.partes) == set(publicado.partes):
        c.nota("PPTX: idéntico byte a byte al recompuesto en local")


def _recomponer_xlsx(ctx: Contexto, c: Comprobacion) -> None:
    """XLSX canónico = el que da el generador canónico (sin modificar) con la entrada y la tarifa locales.

    Solo puede diferir dcterms:modified, que se ata a la hora interna del propio ZIP y a la hora del
    paso del núcleo que lo generó (estimar o paquete en control_versiones); H-V10.
    """
    est = _nucleo("estimacion")
    entrada = (ctx.carga.get("estimacion") or {}).get("entrada") or {}
    destino = ctx.tmp / "recompuesto" / ctx.fichero("Estimacion.xlsx").name
    rutas = est.RutasGenerador(pathlib.Path(ctx.generador), pathlib.Path(ctx.plantilla), pathlib.Path(ctx.rate_card),
                               ctx.tmp / "recompuesto_trabajo")
    try:
        est.generar_xlsx(entrada, rutas, destino)
    except Exception as e:  # noqa: BLE001
        c.falla(f"XLSX: el generador canónico no reproduce el XLSX en local ({type(e).__name__}: {e})")
        return
    with zipfile.ZipFile(destino) as zl, zipfile.ZipFile(ctx.fichero("Estimacion.xlsx")) as zp:
        pl, pp = {n: zl.read(n) for n in zl.namelist()}, {n: zp.read(n) for n in zp.namelist()}
        info_core = next((i for i in zp.infolist() if i.filename == "docProps/core.xml"), None)
    if set(pl) != set(pp):
        c.falla(f"XLSX: partes distintas de las que genera el canónico: {sorted(set(pl) ^ set(pp))}")
        return
    quitar = re.compile(rb"<dcterms:modified[^>]*>[^<]*</dcterms:modified>")
    for n in sorted(pl):
        a, b = (quitar.sub(b"", pl[n]), quitar.sub(b"", pp[n])) if n == "docProps/core.xml" else (pl[n], pp[n])
        if a != b:
            c.falla(f"XLSX: la parte {n} no es la que genera el canónico con la entrada del estado")
    _hora_xlsx(ctx, c, pp.get("docProps/core.xml", b""), info_core)


def _hora_xlsx(ctx: Contexto, c: Comprobacion, core: bytes, info: zipfile.ZipInfo | None) -> None:
    m = re.search(rb"<dcterms:modified[^>]*>([^<]+)</dcterms:modified>", core)
    try:
        hora = dt.datetime.fromisoformat(m.group(1).decode().replace("Z", "+00:00")) if m else None
    except ValueError:
        hora = None
    if hora is None or hora.tzinfo is None or info is None:
        c.falla("XLSX: dcterms:modified ausente o ilegible")
        return
    interna = dt.datetime(*info.date_time)
    desfase = abs((interna - hora.replace(tzinfo=None)).total_seconds())
    if desfase > 14 * 3600 + 2 or min(desfase % 3600, 3600 - desfase % 3600) > 2:
        c.falla(f"XLSX: dcterms:modified {hora.isoformat()} no es la hora interna del ZIP {interna} "
                "(propiedades tocadas después de generar; H-V10)")
    pasos = []
    for e in ctx.estado.get("control_versiones") or []:
        try:
            if e.get("subcomando") in SUBCOMANDOS_XLSX:
                pasos.append(dt.datetime.fromisoformat(str(e.get("ts"))))
        except ValueError:
            continue
    antes, despues = VENTANA_XLSX
    if not any(p.tzinfo and p - antes <= hora <= p + despues for p in pasos):
        c.falla(f"XLSX: dcterms:modified {hora.isoformat()} no cae junto a ningún paso estimar o paquete "
                "de control_versiones (H-V10)")


def _color_ok(val: str | None) -> bool:
    return bool(val) and val.upper()[-6:] in PALETA


def c_marca(ctx: Contexto) -> Comprobacion:
    """P12 · Marca (LES-G-072): Montserrat, paleta, sin colores de tema ni sombras y propiedades §9.2."""
    c = Comprobacion("marca", c_marca.__doc__.split("·")[1].strip())
    a, pns = NS["a"], NS["p"]
    p = ctx.pptx()
    for d in p.diapositivas:
        for run in list(d.raiz.iter(f"{{{a}}}r")) + list(d.raiz.iter(f"{{{a}}}fld")):
            rpr = run.find(f"{{{a}}}rPr")
            caras = {t: (rpr.find(f"{{{a}}}{t}") if rpr is not None else None) for t in ("latin", "ea", "cs")}
            if any(el is None or el.get("typeface") != FUENTE for el in caras.values()):
                c.falla(f"diapositiva {d.numero}: texto «{''.join(run.itertext())[:30]}» sin Montserrat en latin/ea/cs")
            relleno = rpr.find(f"{{{a}}}solidFill/{{{a}}}srgbClr") if rpr is not None else None
            if relleno is None:
                c.falla(f"diapositiva {d.numero}: texto «{''.join(run.itertext())[:30]}» sin color explícito de la paleta")
        for tc in d.raiz.iter(f"{{{a}}}tc"):
            tcpr = tc.find(f"{{{a}}}tcPr")
            if tcpr is None or (tcpr.find(f"{{{a}}}solidFill") is None and tcpr.find(f"{{{a}}}noFill") is None):
                c.falla(f"diapositiva {d.numero}: celda de tabla con el relleno del estilo del tema")
                break
        for el in d.raiz.iter():
            tf = el.get("typeface")
            if tf is not None and tf != FUENTE:
                c.falla(f"diapositiva {d.numero}: fuente «{tf}»")
            if el.tag == f"{{{a}}}srgbClr" and not _color_ok(el.get("val")):
                c.falla(f"diapositiva {d.numero}: color {el.get('val')} fuera de la paleta")
            if el.tag == f"{{{a}}}outerShdw":
                c.falla(f"diapositiva {d.numero}: forma con sombra")
        _estilos_tema(d, c)
    props = p.props
    esperado = {"title": titulo_pptx(ctx.codigo, ctx.estado.get("estado"), ctx.fecha_paquete()),  # VA18-7
                "creator": "Responsable comercial",
                "lastModifiedBy": "Responsable comercial", "category": "Preventa",
                "subject": (ctx.carga.get("alta") or {}).get("titulo")}
    for k, v in esperado.items():
        if props.get(k) != v:
            c.falla(f"PPTX docProps {k} = {props.get(k)!r}; se esperaba {v!r}")
    if props.get("description"):
        c.falla("PPTX docProps comments (description) debe ir vacío")
    _marca_docx(ctx, c)
    _marca_anexo(ctx, c)
    return c


def _estilos_tema(d: Diapositiva, c: Comprobacion) -> None:
    """Colores de tema: fuera de p:style, prohibidos; dentro, solo si el spPr/runs los sustituyen."""
    a, pns = NS["a"], NS["p"]
    estilos = set()
    for st in d.raiz.iter(f"{{{pns}}}style"):
        estilos |= set(st.iter())
        forma = st.getparent()
        sppr = forma.find(f"{{{pns}}}spPr")
        hijos = {h.tag.split("}")[-1] for h in sppr} if sppr is not None else set()
        ln = sppr.find(f"{{{a}}}ln") if sppr is not None else None
        ln_hijos = {h.tag.split("}")[-1] for h in ln} if ln is not None else set()
        es_sp = forma.tag == f"{{{pns}}}sp"
        if es_sp and not hijos & {"solidFill", "noFill", "gradFill"}:
            c.falla(f"diapositiva {d.numero}: forma con relleno del tema sin sustituir")
        if not ln_hijos & {"solidFill", "noFill"}:
            c.falla(f"diapositiva {d.numero}: línea del tema sin sustituir")
        er = st.find(f"{{{a}}}effectRef")
        if er is not None and er.get("idx", "0") != "0" and "effectLst" not in hijos:
            c.falla(f"diapositiva {d.numero}: efectos (sombra) del tema sin anular")
        for run in forma.iter(f"{{{a}}}r"):
            rpr = run.find(f"{{{a}}}rPr")
            if rpr is None or rpr.find(f"{{{a}}}solidFill") is None:
                c.falla(f"diapositiva {d.numero}: texto con el color de fuente del tema")
                break
    for el in d.raiz.iter(f"{{{a}}}schemeClr"):
        if el not in estilos:
            c.falla(f"diapositiva {d.numero}: color de tema «{el.get('val')}» sin sustituir")


def _marca_docx(ctx: Contexto, c: Comprobacion) -> None:
    w = NS["w"]
    _, _, partes = ctx.docx()
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    estilos = partes.get("word/styles.xml")
    if estilos is None:
        c.falla("DOCX sin styles.xml")
    else:
        raiz = etree.fromstring(estilos, parser)
        rf = raiz.find(f"{{{w}}}docDefaults/{{{w}}}rPrDefault/{{{w}}}rPr/{{{w}}}rFonts")
        if rf is None or rf.get(f"{{{w}}}ascii") != FUENTE or rf.get(f"{{{w}}}hAnsi") != FUENTE:
            c.falla("DOCX: la fuente por defecto (docDefaults) no es Montserrat")
    for nombre, datos in partes.items():
        if not re.fullmatch(r"word/(document|styles|header\d*|footer\d*|numbering)\.xml", nombre):
            continue
        for el in etree.fromstring(datos, parser).iter():
            for atr, val in el.attrib.items():
                local = atr.split("}")[-1]
                if el.tag == f"{{{w}}}rFonts" and local in ("ascii", "hAnsi", "cs", "eastAsia") and val != FUENTE:
                    c.falla(f"DOCX {nombre}: fuente «{val}»")
                elif el.tag == f"{{{w}}}rFonts" and local.endswith("Theme"):
                    c.falla(f"DOCX {nombre}: fuente del tema ({local}={val}) sin sustituir")
                elif local in ("themeColor", "themeFill", "themeShade", "themeTint"):
                    c.falla(f"DOCX {nombre}: color de tema ({local}={val})")
                elif (el.tag == f"{{{w}}}color" and local == "val") or (el.tag == f"{{{w}}}shd" and local == "fill"):
                    if val.lower() != "auto" and not _color_ok(val):
                        c.falla(f"DOCX {nombre}: color {val} fuera de la paleta")


def _marca_anexo(ctx: Contexto, c: Comprobacion) -> None:
    import openpyxl
    wb = openpyxl.load_workbook(ctx.fichero("Anexo-Consumo.xlsx"))
    usadas = set()
    for ws in wb:
        for fila in ws.iter_rows():
            for celda in fila:
                if celda.value is None:
                    continue
                usadas.add(celda.font.name)
                for col in (celda.font.color, celda.fill.fgColor if celda.fill.fill_type else None):
                    if col is not None and col.type == "rgb" and not _color_ok(col.rgb):
                        c.falla(f"anexo {ws.title}!{celda.coordinate}: color {col.rgb} fuera de la paleta")
    if usadas - {FUENTE}:
        c.falla(f"anexo XLSX: celdas con fuentes {sorted(usadas - {FUENTE})}")
    registradas = {f.name for f in wb._fonts if f.name}
    if registradas - {FUENTE}:
        c.aviso(f"anexo XLSX: fuentes registradas sin uso {sorted(registradas - {FUENTE})}")


TIPOS_POR_PERSONA = {"COMERCIAL": {"ENVIADA_REVISION", "CONFIRMA_STOP", "AJUSTE_COMERCIAL", "DESBLOQUEAR"},
                     "REVISOR": {"APROBADA", "DEVUELTA"}, "APROBADOR": {"APROBADA", "DEVUELTA"}}
REQUIERE_HASH_VIGENTE = {"ENVIADA_REVISION", "APROBADA", "DEVUELTA"}
ESTADOS_PAQUETE = ("LISTA_PARA_REVISION", "EN_REVISION_PREVENTA", "EN_APROBACION_AREA", "APROBADA")


def c_decisiones(ctx: Contexto) -> Comprobacion:
    """P14 · Decisiones: solo con el hash vigente, revisor correcto, fechas coherentes y estado justificado."""
    c = Comprobacion("decisiones", c_decisiones.__doc__.split("·")[1].strip())
    vigente, version, estado = ctx.hash_vigente(), ctx.estado.get("version"), ctx.estado.get("estado")
    if estado not in ESTADOS_PAQUETE:
        c.falla(f"estado {estado}: un paquete revisable debe estar en {ESTADOS_PAQUETE}")
    elaboracion = str(((ctx.carga.get("estimacion") or {}).get("entrada") or {}).get("fecha", ""))
    fechas: dict[tuple[str, str], str] = {}
    decs = ctx.estado.get("decisiones") or []
    for n, d in enumerate(decs, 1):
        did = d.get("id")
        if did != f"D-{n:03d}":
            c.falla(f"{did}: los ids de decisión deben ser D-001, D-002… en orden")
        partes = [x.strip() for x in (d.get("linea") or "").split("|", 5)]
        if len(partes) != 6 or partes[0] != "DECISION" or plano(partes[1]) != plano(d.get("revisor") or "") \
                or partes[2:5] != [d.get("tipo"), d.get("fecha"), d.get("hash_citado")] \
                or partes[5] != (d.get("comentarios") or "").strip():
            c.falla(f"{did}: la línea literal no coincide con los campos registrados")
        persona = PERSONAS.get(plano(d.get("revisor") or ""))
        if persona is None or d.get("tipo") not in TIPOS_POR_PERSONA.get(persona, set()):
            c.falla(f"{did}: {d.get('revisor')!r} no puede registrar {d.get('tipo')}")
        try:
            f = dt.date.fromisoformat(d.get("fecha") or "")
            if f > ctx.hoy:
                c.falla(f"{did}: fecha futura {f}")
        except ValueError:
            c.falla(f"{did}: fecha no válida {d.get('fecha')!r}")
            continue
        if d.get("version") == version:
            if d.get("tipo") in REQUIERE_HASH_VIGENTE and d.get("hash_citado") != vigente:
                c.falla(f"{did}: {d.get('tipo')} cita {d.get('hash_citado')}, vigente {vigente} (hash viejo)")
            if d.get("tipo") in REQUIERE_HASH_VIGENTE and elaboracion and d.get("fecha") < elaboracion:
                c.falla(f"{did}: fecha {d.get('fecha')} anterior a la elaboración {elaboracion}")
            if d.get("tipo") == "CONFIRMA_STOP" and d.get("hash_citado") != vigente:
                c.aviso(f"{did}: CONFIRMA_STOP de un contenido anterior (ya no vale)")
            fechas[(persona or "?", d.get("tipo"))] = d.get("fecha")
    def hay(persona: str, tipo: str) -> bool:
        return any(d.get("version") == version and d.get("tipo") == tipo and d.get("hash_citado") == vigente
                   and PERSONAS.get(plano(d.get("revisor") or "")) == persona for d in decs)
    if estado in ESTADOS_PAQUETE[1:] and ctx.previo is None:
        c.no_verificado(f"estado {estado} sin --previo: las decisiones de estado.json no tienen ancla externa "
                        "(un paquete descargado antes); su autoría no se comprueba (R2, H-V3)")
    if estado in ESTADOS_PAQUETE[1:]:
        env = [d for d in decs if d.get("version") == version and d.get("tipo") == "ENVIADA_REVISION"
               and d.get("hash_citado") == vigente]
        if not env:
            c.falla(f"estado {estado} sin ENVIADA_REVISION con el hash vigente")
        elif "verificar_paquete rc=0" not in (env[-1].get("comentarios") or ""):
            c.falla("ENVIADA_REVISION sin «verificar_paquete rc=0» en los comentarios")
    if estado in ESTADOS_PAQUETE[2:] and not hay("REVISOR", "APROBADA"):
        c.falla(f"estado {estado} sin APROBADA de Responsable de preventa con el hash vigente")
    if estado == "APROBADA" and not hay("APROBADOR", "APROBADA"):
        c.falla("estado APROBADA sin APROBADA de Responsable de área con el hash vigente")
    fj, fjp, fe = fechas.get(("REVISOR", "APROBADA")), fechas.get(("APROBADOR", "APROBADA")), \
        fechas.get(("COMERCIAL", "ENVIADA_REVISION"))
    if fj and fe and fj < fe:
        c.falla("la revisión de Responsable de preventa es anterior al envío a revisión")
    if fjp and fj and fjp < fj:
        c.falla("la aprobación de Responsable de área es anterior a la revisión de Responsable de preventa")
    if estado == "EN_APROBACION_AREA" and hay("APROBADOR", "APROBADA"):
        c.falla("hay APROBADA de Responsable de área pero el estado no es APROBADA")
    return c


CORE_CONTROL = {"modified", "revision", "lastPrinted"}


def _xlsx_igual_salvo_hora(a: pathlib.Path, b: pathlib.Path) -> bool:
    """Dos XLSX con las mismas partes y el mismo contenido salvo dcterms:modified (regenerado por paquete)."""
    quitar = re.compile(rb"<dcterms:modified[^>]*>[^<]*</dcterms:modified>")
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        if sorted(za.namelist()) != sorted(zb.namelist()):
            return False
        return all(quitar.sub(b"", za.read(n)) == quitar.sub(b"", zb.read(n)) for n in za.namelist())


def c_previo(ctx: Contexto) -> Comprobacion:
    """Previo · Entre el paquete previo y este solo cambian la diapositiva 2, las propiedades del documento y, al aprobarse, el subtítulo de la portada."""
    c = Comprobacion("paquete_previo", c_previo.__doc__.split("·")[1].strip())
    if ctx.previo is None:
        c.nota("sin paquete previo con el que comparar")
        return c
    ant = abrir_paquete(ctx.previo, ctx.tmp / "previo")
    try:
        man_ant = ant.json_de("manifiesto_paquete.json")
    except (KeyError, EntradaIlegible) as e:
        c.falla(f"el paquete previo no se puede leer: {e}")
        return c
    if man_ant.get("codigo") != ctx.codigo:
        c.falla(f"el paquete previo es de {man_ant.get('codigo')}, no de {ctx.codigo}")
        return c
    if man_ant.get("hash_contenido") != ctx.hash_vigente():
        c.falla("el paquete previo tiene otro hash_contenido: el contenido ha cambiado")
    for suf in ("Estimacion.xlsx", "Anexo-Consumo.xlsx", "Anexo-Consumo.json"):
        n = f"{ctx.codigo}-{suf}"
        if n not in ant.ficheros:
            c.falla(f"el paquete previo no trae {n}: no sirve como referencia")
        elif ant.bytes_de(n) != ctx.paquete.bytes_de(n) and not (
                suf.endswith(".xlsx") and _xlsx_igual_salvo_hora(ant.ficheros[n], ctx.paquete.ficheros[n])):
            c.falla(f"{n} ha cambiado respecto al paquete previo")
        elif ant.bytes_de(n) != ctx.paquete.bytes_de(n):
            c.nota(f"{n}: regenerado; igual al previo salvo dcterms:modified (contenido idéntico)")
    fecha_ant = fecha_del_paquete(man_ant)
    n = f"{ctx.codigo}-{sufijo_pptx(man_ant.get('estado'), fecha_ant)}"
    if n not in ant.ficheros or f"{ctx.codigo}-{ctx.sufijo_pptx()}" not in ctx.paquete.ficheros:
        c.falla("el paquete previo o este no traen el PPTX que corresponde a su estado (VA18-7)")
        return c
    p_ant, p_act = leer_pptx(ant.ficheros[n]), ctx.pptx()
    d2 = {p_ant.diapositivas[1].parte if len(p_ant.diapositivas) > 1 else "",
          p_act.diapositivas[1].parte if len(p_act.diapositivas) > 1 else ""}
    permitidas = d2 | {"docProps/core.xml", "docProps/app.xml"}
    if ctx.estado.get("estado") == "APROBADA" and man_ant.get("estado") != "APROBADA"             and p_ant.diapositivas and p_act.diapositivas:
        # H13: al aprobarse cambia el subtítulo de la portada y nada más de ella
        tc = ctx.carga.get("textos_cliente") or {}
        antes, ahora = list(p_ant.diapositivas[0].textos), list(p_act.diapositivas[0].textos)
        viejo, nuevo = nfc(str((tc.get("portada") or {}).get("subtitulo", ""))).strip(), subtitulo_portada(ctx, tc)
        if [nuevo if nfc(x).strip() == viejo else x for x in antes] != ahora:
            c.falla(f"PPTX: la portada cambia algo más que el subtítulo «{viejo}» → «{nuevo}» al aprobarse (H13)")
        permitidas.add(p_act.diapositivas[0].parte)
    for parte in sorted(set(p_ant.partes) | set(p_act.partes)):
        if parte not in permitidas and p_ant.partes.get(parte) != p_act.partes.get(parte):
            c.falla(f"PPTX: la parte {parte} ha cambiado (solo pueden cambiar la diapositiva 2, las propiedades y, al aprobarse, el subtítulo de la portada)")
    titulos = (titulo_pptx(ctx.codigo, man_ant.get("estado"), fecha_ant),
               titulo_pptx(ctx.codigo, ctx.estado.get("estado"), ctx.fecha_paquete()))
    for k in sorted(set(p_ant.props) | set(p_act.props)):
        if k == "title" and (p_ant.props.get(k), p_act.props.get(k)) == titulos and titulos[0] != titulos[1]:
            c.nota(f"PPTX: title «{titulos[0]}» → «{titulos[1]}» al aprobarse (VA18-7)")
            continue
        if k not in CORE_CONTROL and p_ant.props.get(k) != p_act.props.get(k):
            c.falla(f"PPTX: la propiedad {k} ha cambiado ({p_ant.props.get(k)!r} → {p_act.props.get(k)!r})")
    if not c.detalles:
        c.nota(f"comparado con el paquete previo en estado {man_ant.get('estado')}: solo cambian la "
               "diapositiva 2 y las propiedades de control")
    return c


def conexiones_appi_real() -> list[dict]:
    from lib.foundry import ClienteFoundry
    cli = ClienteFoundry()
    r = cli._arm("GET", f"{cli.id_arm_proyecto}/connections", cli.cfg["api_versions"]["arm_conexiones"])
    return [x for x in r.get("value", []) if (x.get("properties") or {}).get("category") == "AppInsights"]


AUD_APPI = "https://api.applicationinsights.io"


def url_consulta_appi(cfg: dict) -> str:
    return (f"{AUD_APPI}/v1/subscriptions/{cfg['suscripcion_id']}/resourceGroups/{cfg['grupo_recursos']}"
            f"/providers/microsoft.insights/components/{APPI_ESPERADO}/query")


def filas_de_tabla(cuerpo: dict) -> list[dict]:
    """Filas de la primera tabla. Una respuesta sin tabla o con filas que no casan con las columnas
    falla en alto: una forma inesperada no puede pasar por «consulta válida sin resultados»."""
    tablas = cuerpo.get("tables") if isinstance(cuerpo, dict) else None
    if not isinstance(tablas, list) or not tablas or not isinstance(tablas[0], dict):
        raise RuntimeError("respuesta KQL sin «tables»: forma inesperada")
    cols = [col.get("name") for col in tablas[0].get("columns", [])]
    filas = tablas[0].get("rows", [])
    if any(not isinstance(f, list) or len(f) != len(cols) for f in filas):
        raise RuntimeError("respuesta KQL con filas que no casan con las columnas")
    return [dict(zip(cols, fila)) for fila in filas]


VIAS_KQL = ("arm", "v1")  # lista blanca de PREVENTA_KQL_VIA (LES-G-060: un valor desconocido falla en alto)


def via_kql() -> str:
    """Vía de la consulta KQL: `arm` (por defecto, lib.appi con el token de ARM) o `v1` (api.applicationinsights.io,
    que en el tenant de Devoteam pide un MFA aparte). `v1` es solo la vuelta atrás si ARM no admitiera la ruta."""
    valor = (os.environ.get("PREVENTA_KQL_VIA") or "").strip().lower() or "arm"
    if valor not in VIAS_KQL:
        raise RuntimeError(f"PREVENTA_KQL_VIA={valor!r} no es válida: use {' o '.join(VIAS_KQL)}")
    return valor


def consultar_kql_real(consulta: str) -> list[dict]:
    """KQL contra App Insights. Por defecto por ARM (lib.appi: api-version 2018-04-20, UTF-8 estricto, 200 sin
    `tables` o con `error` parcial = fallo). No se usa `az monitor app-insights query`: en Windows `az` escribe
    en cp1252 y las tildes llegaban como U+FFFD (falso FALLA de procedencia en el E2E de I1)."""
    if via_kql() == "arm":
        from lib import appi
        try:
            return filas_de_tabla(appi.consultar(consulta, "P30D", componente=APPI_ESPERADO))
        except appi.ErrorAppi as e:
            raise RuntimeError(f"consulta KQL por ARM: {e}") from None
    return consultar_kql_v1(consulta)


def consultar_kql_v1(consulta: str) -> list[dict]:
    """Vía antigua (PREVENTA_KQL_VIA=v1): REST de api.applicationinsights.io, JSON en UTF-8."""
    import requests
    from lib.azure_auth import obtener_token
    from lib.config import cargar
    cfg = cargar()
    token = obtener_token(AUD_APPI, cfg["tenant_id"])  # solo en memoria; nunca se imprime
    r = requests.post(url_consulta_appi(cfg), json={"query": consulta, "timespan": "P30D"},
                      headers={"Authorization": f"Bearer {token}"}, timeout=180)
    if r.status_code != 200:
        from lib.evidencia import enmascarar_texto
        raise RuntimeError(f"consulta KQL HTTP {r.status_code}: {enmascarar_texto(r.text[:400])}")
    return filas_de_tabla(json.loads(r.content.decode("utf-8")))


def _objetos_json(valor: Any, profundidad: int = 0):
    """Objetos JSON contenidos en un valor de traza (cadenas JSON anidadas incluidas). VER13-1 (I1.3): la salida de un
    agente llamado por A2A directo (opción B) está en customDimensions → gen_ai.output.messages (cadena JSON) → lista →
    mensaje → parts → content (cadena JSON): seis niveles; con el tope de 4 no se llegaba nunca a ella."""
    if profundidad > 8:
        return
    if isinstance(valor, dict):
        yield valor
        for v in valor.values():
            yield from _objetos_json(v, profundidad + 1)
    elif isinstance(valor, list):
        for v in valor:
            yield from _objetos_json(v, profundidad + 1)
    elif isinstance(valor, str) and "{" in valor:
        for ini in [m.start() for m in re.finditer(r"\{", valor)][:50]:
            try:
                obj, _ = json.JSONDecoder().raw_decode(valor[ini:])
            except ValueError:
                continue
            yield from _objetos_json(obj, profundidad + 1)


def _kql_literal(s: str) -> str:
    if not re.fullmatch(r"[A-Z0-9-]{5,80}", s or ""):
        raise ValueError(f"identificador no apto para KQL: {s!r}")
    return f'"{s}"'


def hojas_traza(valor: Any, profundidad: int = 0):
    """Cada cadena de un valor de traza, entrando en las cadenas que son JSON completo (customDimensions →
    gen_ai.output.messages → parts → content)."""
    if profundidad > 8:
        return
    if isinstance(valor, dict):
        for v in valor.values():
            yield from hojas_traza(v, profundidad + 1)
    elif isinstance(valor, list):
        for v in valor:
            yield from hojas_traza(v, profundidad + 1)
    elif isinstance(valor, str):
        yield valor
        if valor.lstrip()[:1] in ("{", "["):
            try:
                obj = json.loads(valor)
            except ValueError:
                return
            yield from hojas_traza(obj, profundidad + 1)


# Primera clave de una salida de los agentes (la del verificador empieza por «agente»; la del experto, por
# «brief_recibido», que va antes que «brief_id» y es lo que se trunca primero). Los argumentos de una herramienta
# (`{"message": …}`) o la entrada en texto no empiezan así.
_INICIO_SALIDA = re.compile(r'^\{\s*"(?:agente|brief_recibido|brief_id|consolidado_id)"\s*:')


def salida_truncada(hoja: str, clave: str, ident: str) -> bool:
    """Una cadena de la traza que es la SALIDA JSON de un agente (empieza por una de sus claves, _INICIO_SALIDA), que no
    es JSON válido, que menciona el id (la clave entre comillas `"consolidado_id": "CNS-…-L1"` o, en el experto, el
    brief devuelto con `brief_id: BRF-…`) y que, después de esa mención, lleva la marca «[TRUNCATED]» de Foundry. La
    entrada (el lote o el brief en texto) y las demás cadenas de la fila no cuentan: así una entrada truncada no tapa
    una salida completa que no coincide (eso sigue siendo FALLA)."""
    if not isinstance(hoja, str) or not _INICIO_SALIDA.match(hoja.lstrip()):
        return False
    try:
        json.loads(hoja)
        return False  # completa: no está truncada
    except ValueError:
        pass
    m = re.search(re.escape(f'"{clave}"') + r"\s*:\s*" + re.escape(f'"{ident}"'), hoja)
    if m is None and clave == "brief_id":
        # En la salida sin decodificar, el brief devuelto lleva los saltos de línea escapados («\n» literal).
        m = re.search(r"(?:\\n|\n)brief_id: " + re.escape(ident) + r"(?:\\n|\n)", hoja)
    return bool(m) and hoja.find("[TRUNCATED]", m.end()) >= 0


def prefijo_salida(hoja: str) -> str:
    """Lo que la traza conserva de una salida truncada: hasta la marca «... [TRUNCATED]» (o «[TRUNCATED]»)."""
    i = hoja.find("... [TRUNCATED]")
    return hoja[:i if i >= 0 else hoja.find("[TRUNCATED]")]


def sin_espacios_fuera(texto: str) -> str:
    """Quita los espacios en blanco que están FUERA de las cadenas JSON (los del formato: sangría, saltos, «: »); los
    de dentro de una cadena se conservan, así un «a b» frente a «ab» no casa (Revisión, I1.3). Sirve para un JSON
    truncado: recorre el texto llevando la cuenta de si está dentro de una cadena y de los escapes."""
    salida, dentro, escape = [], False, False
    for ch in texto or "":
        if dentro:
            salida.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                dentro = False
        elif ch == '"':
            dentro = True
            salida.append(ch)
        elif not ch.isspace():
            salida.append(ch)
    return "".join(salida)


def _formas_salida(obj: Any) -> list[str]:
    """Serializaciones de una salida JSON (con o sin escapes Unicode), en NFC y sin espacios fuera de las cadenas,
    para comparar con lo que la traza conserva del texto que escribió el modelo."""
    return [sin_espacios_fuera(unicodedata.normalize("NFC", json.dumps(obj, ensure_ascii=asc))) for asc in (False, True)]


def casa_prefijo(prefijo: str, obj: Any) -> bool:
    """El comienzo truncado de la traza es el comienzo de la salida `obj` (en NFC y sin espacios fuera de las cadenas)."""
    p = sin_espacios_fuera(unicodedata.normalize("NFC", prefijo or ""))
    return bool(p) and any(f.startswith(p) for f in _formas_salida(obj))


def juzgar_procedencia(filas: list[dict], clave: str, ident: str, guardado: dict) -> tuple[str, str]:
    """VER13-1 (I1.3). Agrupa las filas por llamada (operation_Id) y juzga cada una con lo que la traza conserva de la
    salida: completa (objeto con la clave y «agente») o truncada (comienzo hasta «[TRUNCATED]»). Así un mismo id
    reutilizado en otra ejecución (otra solicitud con el mismo código) no tapa ni condena a esta.
    - OK: en alguna llamada, una salida completa es la del estado.
    - NO VERIFICADO: ninguna llamada la prueba entera, pero alguna tiene un comienzo truncado que es el del estado y
      ninguna salida completa distinta (la plataforma trunca el contenido: la procedencia completa no se puede probar).
    - FALLA: hay salidas con ese id y ninguna llamada es compatible con el estado.
    - NO VERIFICADO: ninguna salida con ese id."""
    grupos: dict[object, list[dict]] = {}
    for f in filas:
        grupos.setdefault(f.get("op"), []).append(f)
    con_salida, solo_comienzo, maximo = 0, 0, 0
    for fs in grupos.values():
        completas = [o for f in fs for v in f.values() for o in _objetos_json(v)
                     if isinstance(o, dict) and o.get(clave) == ident and "agente" in o]
        prefijos = [prefijo_salida(h) for f in fs for h in hojas_traza(f) if salida_truncada(h, clave, ident)]
        if any(hash_json(o) == hash_json(guardado) for o in completas):
            return OK, "la salida A2A registrada en las trazas coincide con la del estado"
        if completas or prefijos:
            con_salida += 1
        if prefijos and not completas and all(casa_prefijo(x, guardado) for x in prefijos):
            solo_comienzo += 1
            maximo = max([maximo] + [len(sin_espacios_fuera(x)) for x in prefijos])
    if solo_comienzo:
        n = con_salida - solo_comienzo
        otras = (f"; {n} llamada{'s' if n > 1 else ''} más con ese id {'son' if n > 1 else 'es'} de otra ejecución"
                 if n else "")
        return NOV, (f"las trazas truncan la salida («[TRUNCATED]»); solo su comienzo ({maximo} caracteres) "
                     f"coincide con el estado{otras}: la procedencia completa por trazas no se puede probar")
    if con_salida:
        return FALLA, (f"la salida A2A de las trazas no coincide con la del estado: ninguna de las {con_salida} "
                       f"llamadas con {clave}={ident} es compatible (completa distinta o comienzo distinto)")
    return NOV, f"ninguna salida A2A con {clave}={ident} en las trazas ({len(filas)} filas)"


# ── Procedencia propia de B (decisión del comercial, 10-10-2026) ──────────────────────────────────────────────────────
# El hosted agent (código, no el modelo) guarda por cada tarea A2A el texto recibido y su SHA-256, y lo relee con GetTask
# con su identidad (la única que puede leer la tarea, LES-G-089.10). La puerta exige para cada salida que usó el núcleo:
# la tarea en la procedencia con la huella de lo enviado, el texto que reproduce lo registrado, su task_id en las trazas
# y que el comienzo que conserva la traza (Foundry corta cada mensaje a 1.024 caracteres) sea el del texto registrado.
CLAVES_TAREA = ("fase", "agente", "url", "objetivo_id", "hora", "task_id", "context_id", "estado_tarea",
                "sha256_enviado", "bytes_enviado", "sha256_recibido", "bytes_recibido", "texto_recibido", "relectura")
AGENTE_VERIFICADOR = "preventa-verificador"
MIN_COMIENZO_TRAZA = 1000  # 1.024 con «... [TRUNCATED]» = 1.009 de texto (sonda de I1.4, pruebas/I14/P1)
MARGEN_TRAZAS = dt.timedelta(minutes=5)
INGESTA_TRAZAS = dt.timedelta(minutes=15)  # App Insights tarda unos minutos en tener las trazas
MARGEN_FUTURO = dt.timedelta(minutes=5)    # REV-2 (I1.5): una hora posterior a ahora + 5 min no es de una tarea real
ORQUESTADORES = ("A", "B")                 # VER14-3 / REV-5 (I1.5): marca del código en estado.json y en el manifiesto
TOPE_FILAS = 200
TOPE_FILAS_TAREAS = 2000
_TASK_ID = re.compile(r"[A-Za-z0-9_-]{5,120}")


def instante(valor: object) -> dt.datetime | None:
    """ISO 8601 con zona (o «Z») a UTC; None si no lo es (una hora sin zona no se adivina)."""
    if not isinstance(valor, str):
        return None
    try:
        t = dt.datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(dt.timezone.utc) if t.tzinfo else None


def kql_instante(t: dt.datetime) -> str:
    return f"datetime({t.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')})"


def errores_procedencia(doc: object, ahora: dt.datetime | None = None) -> list[str]:
    """Forma de procedencia_a2a.json y coherencia de cada tarea (el SHA-256 del texto es el registrado; la hora, ISO con
    zona y no posterior a «ahora + 5 min», REV-2: una hora futura no puede pasar por «aún en ingesta»)."""
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA_PROCEDENCIA or not isinstance(doc.get("tareas"), list):
        return [f"no es un documento {SCHEMA_PROCEDENCIA} con «tareas»"]
    e, vistos = [], set()
    for i, t in enumerate(doc["tareas"]):
        if not isinstance(t, dict) or set(t) != set(CLAVES_TAREA):
            e.append(f"tareas[{i}]: claves distintas de las del contrato")
            continue
        tid = t["task_id"]
        if not isinstance(tid, str) or not _TASK_ID.fullmatch(tid):
            e.append(f"tareas[{i}]: task_id no válido {tid!r}")
        elif tid in vistos:
            e.append(f"tareas[{i}]: task_id repetido {tid}")
        else:
            vistos.add(tid)
        if not isinstance(t["texto_recibido"], str) or not t["texto_recibido"]:
            e.append(f"tareas[{i}] ({tid}): sin texto recibido")
        elif sha256_bytes(t["texto_recibido"].encode("utf-8")) != t["sha256_recibido"]:
            e.append(f"tareas[{i}] ({tid}): el SHA-256 del texto recibido no es el registrado (texto alterado)")
        if not isinstance(t["sha256_enviado"], str) or not re.fullmatch(r"[0-9a-f]{64}", t["sha256_enviado"]):
            e.append(f"tareas[{i}] ({tid}): sha256_enviado no válido")
        if instante(t["hora"]) is None:
            e.append(f"tareas[{i}] ({tid}): hora sin formato ISO con zona: {t['hora']!r}")
        elif instante(t["hora"]) > ahora + MARGEN_FUTURO:
            e.append(f"tareas[{i}] ({tid}): hora futura {t['hora']} (posterior a ahora + 5 min): no es de una tarea real")
        if not isinstance(t["objetivo_id"], str) or not isinstance(t["relectura"], dict):
            e.append(f"tareas[{i}] ({tid}): objetivo_id o relectura con forma no válida")
    return e


def salida_como_la_registra_el_nucleo(texto: str) -> Any:
    """Lo que el núcleo guarda de un texto recibido: `experto.parsear` (BOM, CRLF, una valla ```) y NFC. Se usa el
    módulo del repositorio; si no existe, la réplica local de esas dos reglas. ValueError si no es un objeto JSON."""
    ex = _nucleo("experto")
    if ex is not None:
        try:
            return ex._nfc(ex.parsear(texto))
        except Exception as e:  # noqa: BLE001 - ReglaIncumplida del núcleo
            raise ValueError(str(e)) from None
    t = (texto or "").lstrip("\ufeff").replace("\r\n", "\n").strip()
    m = re.fullmatch(r"```(?:json)?[ \t]*\n(.*)\n```", t, flags=re.DOTALL | re.IGNORECASE)
    obj = json.loads(m.group(1).strip() if m else t, parse_constant=_sin_nan)
    if not isinstance(obj, dict):
        raise ValueError("no es un objeto JSON")
    return json.loads(unicodedata.normalize("NFC", json.dumps(obj, ensure_ascii=False)))


def comienzo_en_traza(texto: str, hojas: list[str]) -> tuple[str, int]:
    """(«completa», n) si alguna cadena de la traza ES el texto; («comienzo», n) si alguna está cortada con
    «[TRUNCATED]» y lo que conserva (n ≥ MIN_COMIENZO_TRAZA caracteres) es literalmente el comienzo del texto;
    («», 0) si no."""
    if any(h == texto for h in hojas):
        return "completa", len(texto)
    mejor = 0
    for h in hojas:
        if "[TRUNCATED]" in h:
            p = prefijo_salida(h)
            if len(p) >= MIN_COMIENZO_TRAZA and len(p) < len(texto) and texto.startswith(p):
                mejor = max(mejor, len(p))
    return ("comienzo", mejor) if mejor else ("", 0)


def _objetivos_b(ctx: Contexto) -> list[tuple[str, str, Any, str | None, str, bool]]:
    """(quién, id del brief o lote, salida guardada por el núcleo, texto enviado, agente, es_experto) de cada salida A2A
    que usó el núcleo para este paquete."""
    resp = ctx.respuesta
    bid = resp.get("brief_id") if isinstance(resp, dict) else None
    brief = next((b for b in ctx.carga.get("briefs") or [] if isinstance(b, dict) and b.get("brief_id") == bid), {})
    salida_experto = resp
    if isinstance(resp, dict) and "valoracion_nucleo" in resp:
        # Integrador I1.7: lo guardado es la respuesta COMPLETADA por el núcleo; la salida A2A es lo que escribió el
        # modelo, que se recupera exacto con la proyección (CAMBIOS-I17-P §1). Si no se puede proyectar, no casa (FALLA).
        try:
            salida_experto = proyectar_r(resp)
        except (KeyError, TypeError, AttributeError, ValueError):
            salida_experto = resp
    salida = [("experto", bid, salida_experto, brief.get("texto"), brief.get("experto") or "preventa-experto-azure", True)]
    cons, ver = ctx.carga.get("consolidado") or {}, ctx.carga.get("verificacion") or {}
    if ver.get("lotes"):
        for x in cons.get("lotes") or []:
            salida.append((f"verificador {x.get('lote_id')}", x.get("lote_id"), x.get("respuesta"), x.get("texto"),
                           AGENTE_VERIFICADOR, False))
    else:
        salida.append(("verificador", cons.get("consolidado_id"), ver.get("respuesta"), cons.get("texto"),
                       AGENTE_VERIFICADOR, False))
    return salida


RELECTURA_METODO, RELECTURA_HTTP, RELECTURA_ESTADO = "GetTask", 200, "TASK_STATE_COMPLETED"


def juicio_relectura(t: dict) -> tuple[str, str]:
    """Decisión 3 (vigente en I1.6) sobre la relectura de UNA tarea, como lista blanca (LES-G-098.3, VER15-4):
    distinta (`coincide: false`) o «coincide» con otra huella, FALLA (más severo que NO VERIFICADO, se mantiene);
    sin `coincide: true`, o con un método distinto de GetTask, un HTTP distinto de 200, la tarea no completada o un
    error anotado, NO VERIFICADO; OK solo si todo lo anterior es exactamente lo esperado."""
    rel, tid = t.get("relectura"), t.get("task_id")
    if not isinstance(rel, dict):
        return FALLA, f"la tarea {tid} no trae relectura con forma válida"
    if rel.get("coincide") is False:
        return FALLA, f"la relectura GetTask de {tid} devolvió otro texto ({rel.get('sha256_recibido')})"
    if rel.get("coincide") is not True:
        return NOV, (f"la tarea {tid} no se pudo releer con GetTask (decisión 3: sin relectura, NO VERIFICADO): "
                     f"{str(rel.get('error'))[:200]}")
    if rel.get("sha256_recibido") != t.get("sha256_recibido"):
        return FALLA, (f"la relectura de {tid} dice coincidir, pero su SHA-256 {rel.get('sha256_recibido')} no es el "
                       "del texto registrado")
    http = rel.get("http")
    motivos = [m for m, mal in (
        (f"método {rel.get('metodo')!r} en vez de {RELECTURA_METODO}", rel.get("metodo") != RELECTURA_METODO),
        (f"HTTP {http!r} en vez de {RELECTURA_HTTP}", type(http) is not int or http != RELECTURA_HTTP),
        (f"tarea en {rel.get('estado_tarea')!r}, no {RELECTURA_ESTADO}", rel.get("estado_tarea") != RELECTURA_ESTADO),
        (f"error anotado {str(rel.get('error'))[:120]!r}", rel.get("error") is not None)) if mal]
    if motivos:
        return NOV, (f"la relectura de {tid} dice coincidir, pero no es una lectura GetTask válida "
                     f"({'; '.join(motivos)}): decisión 3, NO VERIFICADO")
    return OK, f"relectura GetTask de {tid}: HTTP 200, completada y con la misma huella"


def _procedencia_b_local(ctx: Contexto, c: Comprobacion, doc: object) -> list[tuple[str, dict]]:
    """INT-3 (I1.5): la parte de la procedencia de B que no necesita trazas, que se ejecuta también con --sin-red.
    Forma, texto igual a la salida del estado, huella de lo enviado, agente y relectura. Devuelve las tareas que
    quedan para contrastar con las trazas, [] si falla la forma.
    Decisión 3 del comercial (11-10-2026, ampliada en I1.6): la relectura se juzga en TODAS las tareas de la procedencia,
    también en las que no usó el núcleo (REVERIF15-1), con `juicio_relectura` (VER15-4). Solo las usadas se
    contrastan después con las trazas."""
    for e in errores_procedencia(doc):
        c.falla(f"{NOMBRE_PROCEDENCIA}: {e}")
    if c.estado == FALLA:
        return []
    tareas, usadas, juzgadas = doc["tareas"], [], set()
    for quien, ident, guardado, enviado, agente, es_experto in _objetivos_b(ctx):
        if not isinstance(ident, str) or not ident or not isinstance(guardado, dict) or not guardado \
                or not isinstance(enviado, str):
            c.falla(f"{quien}: el estado no guarda el identificador, lo enviado o la salida A2A que hay que contrastar")
            continue
        cand = [t for t in tareas if t["objetivo_id"] == ident]
        iguales = []
        for t in cand:
            try:
                if hash_json(salida_como_la_registra_el_nucleo(t["texto_recibido"])) == hash_json(guardado):
                    iguales.append(t)
            except ValueError:
                pass
        if not iguales:
            c.falla(f"{quien}: ninguna de las {len(cand)} tareas de la procedencia con objetivo {ident} trae el texto "
                    "que registró el núcleo")
            continue
        esperados = _envios_esperados(ctx, c, ident, enviado) if es_experto else {sha256_bytes(enviado.encode("utf-8"))}
        for t in iguales:
            tid, ok = t["task_id"], True
            if t["sha256_enviado"] not in esperados:
                c.falla(f"{quien}: la tarea {tid} no se envió con la huella del texto del estado ({t['sha256_enviado']})"
                        + (": tras un rechazo del núcleo, el reintento lleva delante el motivo literal del rechazo y "
                           "nunca es el brief idéntico (PR17-6 parte 2)" if len(esperados) == 1
                           and sha256_bytes(enviado.encode("utf-8")) not in esperados else ""))
                ok = False
            if t["agente"] != agente:
                c.falla(f"{quien}: la tarea {tid} es de {t['agente']!r}, no de {agente}")
                ok = False
            juzgadas.add(tid)
            veredicto_rel, detalle = juicio_relectura(t)
            if veredicto_rel == FALLA:
                c.falla(f"{quien}: {detalle}")
                ok = False
            elif veredicto_rel == NOV:
                c.no_verificado(f"{quien}: {detalle}")
            if ok:
                usadas.append((quien, t))
    # REVERIF15-1: la decisión 3 habla de toda tarea A2A, no solo de las que usó el núcleo. Las demás (rondas
    # anteriores, repeticiones) no se contrastan con las trazas, pero su relectura local se juzga igual.
    otras = [t for t in tareas if t["task_id"] not in juzgadas]
    buenas = 0
    for t in otras:
        veredicto_rel, detalle = juicio_relectura(t)
        quien = f"tarea no usada por el núcleo ({t.get('fase')}, {t.get('agente')}, objetivo {t.get('objetivo_id')})"
        if veredicto_rel == FALLA:
            c.falla(f"{quien}: {detalle}")
        elif veredicto_rel == NOV:
            c.no_verificado(f"{quien}: {detalle}")
        else:
            buenas += 1
    if otras:
        c.nota(f"{len(otras)} tarea(s) de la procedencia no son las que usó el núcleo (rondas anteriores, repeticiones o "
               f"fallos de forma): no se contrastan con las trazas; su relectura local sí (decisión 3): {buenas} de "
               f"{len(otras)} correctas")
    return usadas


# PR17-6 parte 2 (I1.8): desde esta fecha de paquete, la tarea que usó el núcleo tras un rechazo suyo tiene que llevar el
# bloque REINTENTO-PREVENTA/1 con el motivo literal (nucleo.brief.texto_envio). Antes, el hosted reenviaba el brief
# idéntico (comportamiento documentado de I1.7) y se admite con una nota.
FECHA_REINTENTO_CON_MOTIVO = dt.date(2026, 10, 14)


def _envios_esperados(ctx: Contexto, c: Comprobacion, brief_id: str, brief_texto: str) -> set[str]:
    """Huellas admitidas para lo que se envió al experto con el brief `brief_id`: el texto que compone el núcleo hasta el
    control que registró la respuesta (sin rechazos, el brief tal cual; con rechazos, el bloque del motivo y el brief)."""
    br, est = _nucleo("brief"), getattr(ctx, "estado", None) or {}
    solo_brief = {sha256_bytes(brief_texto.encode("utf-8"))}
    if br is None or not hasattr(br, "texto_envio"):
        c.aviso(f"{brief_id}: sin nucleo.brief.texto_envio no se comprueba el texto del reintento (PR17-6 parte 2)")
        return solo_brief
    brief = next((b for b in ctx.carga.get("briefs") or [] if isinstance(b, dict) and b.get("brief_id") == brief_id), None)
    n = br.control_registro_experto(est)
    if brief is None or n is None:
        c.falla(f"{brief_id}: no se encuentra en el estado el brief o el control que registró la respuesta del experto "
                "(PR17-6 parte 2)")
        return solo_brief
    try:
        texto = br.texto_envio(est, brief, hasta_n=n)
    except Exception as e:  # noqa: BLE001 - nunca en silencio
        c.falla(f"{brief_id}: no se pudo recomponer el texto de envío del brief: {type(e).__name__}: {e} (PR17-6 parte 2)")
        return solo_brief
    if texto == brief_texto:
        return solo_brief
    rechazos = len(br.rechazos_vigentes(est, hasta_n=n))
    fecha = fecha_del_paquete(getattr(ctx, "manifiesto", None) or {})
    if fecha is not None and fecha < FECHA_REINTENTO_CON_MOTIVO:
        c.nota(f"{brief_id}: {rechazos} rechazo(s) del núcleo antes de la respuesta registrada; paquete del {fecha} "
               f"(anterior a {FECHA_REINTENTO_CON_MOTIVO}): se admite también el brief idéntico (PR17-6 parte 2)")
        return solo_brief | {sha256_bytes(texto.encode("utf-8"))}
    c.nota(f"{brief_id}: {rechazos} rechazo(s) del núcleo antes de la respuesta registrada: la tarea usada tiene que "
           "llevar el motivo literal del último (PR17-6 parte 2)")
    return {sha256_bytes(texto.encode("utf-8"))}


def _procedencia_b(ctx: Contexto, c: Comprobacion, doc: object) -> None:
    """Procedencia de B completa (parte local y trazas), como antes de partirla (INT-3)."""
    _procedencia_b_trazas(ctx, c, _procedencia_b_local(ctx, c, doc))


def _procedencia_b_trazas(ctx: Contexto, c: Comprobacion, usadas: list[tuple[str, dict]],
                          ahora: dt.datetime | None = None) -> None:
    """El task_id de cada tarea en las trazas y el comienzo que conserva la traza igual al del texto registrado."""
    if not usadas:
        return
    horas = [instante(t["hora"]) for _, t in usadas]
    desde, hasta = min(horas) - MARGEN_TRAZAS, max(horas) + MARGEN_TRAZAS + INGESTA_TRAZAS
    lista = ", ".join(f'"{t["task_id"]}"' for _, t in usadas)
    consulta = ("union requests, dependencies, traces, customEvents "
                f"| where timestamp between ({kql_instante(desde)} .. {kql_instante(hasta)}) "
                "| extend tid = tostring(customDimensions['gen_ai.response.id']) "
                f"| where tid in ({lista}) "
                "| project timestamp, itemType, name, op = operation_Id, tid, dims = tostring(customDimensions) "
                f"| order by timestamp desc | take {TOPE_FILAS_TAREAS}")
    try:
        filas = (ctx.consultar_kql or consultar_kql_real)(consulta)
    except Exception as e:  # noqa: BLE001
        c.no_verificado(f"consulta KQL de las tareas de B fallida: {type(e).__name__}: {str(e)[:300]}")
        return
    # Revisión (I1.4): con el tope alcanzado, lo que falta son las filas más antiguas; si aun así cada tarea queda probada,
    # vale; si alguna no, no se juzga con un resultado que puede estar incompleto: FALLA en alto.
    tope = len(filas) >= TOPE_FILAS_TAREAS
    ahora, juicios = ahora or dt.datetime.now(dt.timezone.utc), []
    for quien, t in usadas:
        tid, filas_t = t["task_id"], [f for f in filas if f.get("tid") == t["task_id"]]
        if not filas_t:
            # REV-2 (I1.5): solo una hora real y reciente (0 ≤ ahora - hora < 15 min) se puede achacar a la ingesta.
            if dt.timedelta(0) <= ahora - instante(t["hora"]) < INGESTA_TRAZAS:
                juicios.append((NOV, f"{quien}: la tarea {tid} aún no está en las trazas (ingesta de unos minutos): "
                                     "repetir"))
            else:
                juicios.append((FALLA, f"{quien}: el task_id {tid} no aparece en las trazas de {APPI_ESPERADO}"))
            continue
        modo, n = comienzo_en_traza(t["texto_recibido"], [h for f in filas_t for h in hojas_traza(f)])
        if modo == "completa":
            juicios.append((OK, f"{quien}: tarea {tid}: la traza trae el texto registrado completo ({n} caracteres)"))
        elif modo == "comienzo":
            juicios.append((OK, f"{quien}: tarea {tid}: el comienzo de la traza ({n} caracteres; Foundry corta a "
                                f"1.024) es el del texto registrado, cuyo SHA-256 {t['sha256_recibido']} es el que usó "
                                "el núcleo"))
        else:
            juicios.append((FALLA, f"{quien}: tarea {tid}: ningún comienzo de su traza coincide con el texto registrado "
                                   f"(comienzo distinto; {len(filas_t)} filas)"))
    if tope and any(v != OK for v, _ in juicios):
        c.falla(f"la consulta de las tareas de B alcanzó el tope de {TOPE_FILAS_TAREAS} filas y no todas quedan "
                "probadas: el resultado puede estar incompleto y no se juzga")
        return
    if tope:
        c.nota(f"la consulta alcanzó el tope de {TOPE_FILAS_TAREAS} filas, pero cada tarea queda probada")
    for v, msg in juicios:
        {OK: c.nota, NOV: c.no_verificado, FALLA: c.falla}[v](msg)


def ventana_a(ctx: Contexto, es_experto: bool) -> tuple[dt.datetime, dt.datetime, str] | None:
    """REV13-2: la ventana de la ejecución que registró la salida. Por `control_versiones`: del último `enrutar`
    (experto) o `consolidar` (verificador) anterior al último registro, hasta ese registro, con 5 min de margen. Si el
    estado no lo trae, por la fecha de registro (desde el día anterior hasta dos días después). None si tampoco."""
    ini_sub, fin_sub = ("enrutar", "registrar-experto") if es_experto else ("consolidar", "registrar-verificacion")
    estado = getattr(ctx, "estado", None) or {}  # los contextos mínimos de las pruebas de I1.3 no lo traen
    cv = [x for x in estado.get("control_versiones") or [] if isinstance(x, dict)]
    fines = [x for x in cv if x.get("subcomando") == fin_sub and instante(x.get("ts"))]
    if fines:
        fin = fines[-1]
        inis = [x for x in cv if x.get("subcomando") == ini_sub and instante(x.get("ts"))
                and isinstance(x.get("n"), int) and isinstance(fin.get("n"), int) and x["n"] < fin["n"]]
        if inis:
            return (instante(inis[-1]["ts"]) - MARGEN_TRAZAS, instante(fin["ts"]) + MARGEN_TRAZAS,
                    f"{ini_sub} n={inis[-1]['n']} a {fin_sub} n={fin['n']}")
    if es_experto:
        fecha = ((ctx.carga.get("respuestas_expertos") or {}).get(pilar_ctx(ctx)) or {}).get("registrada_el")
    else:
        fecha = (ctx.carga.get("verificacion") or {}).get("registrada_el")
    try:
        d = dt.datetime.combine(dt.date.fromisoformat(str(fecha)), dt.time(), dt.timezone.utc)
    except ValueError:
        return None
    return d - dt.timedelta(days=1), d + dt.timedelta(days=2), f"fecha de registro {fecha}"


def orquestador_declarado(ctx: Contexto, c: Comprobacion, con_fichero: bool) -> str | None:
    """VER14-3 / REV-5 (I1.5): el orquestador que declaró el código (el núcleo lo escribe en estado.json y en el
    manifiesto desde PREVENTA_ORQUESTADOR, que en B fija main.py del hosted). Exige procedencia_a2a.json si y solo si
    es B. Sin marca en ninguno de los dos: si la respuesta del experto es v1 (núcleo anterior a I1.5), la vía la decide
    el fichero, como antes, y se anota; si es v2 o posterior, FALLA (REV15-2)."""
    de_est = (getattr(ctx, "estado", None) or {}).get("orquestador")
    de_man = (getattr(ctx, "manifiesto", None) or {}).get("orquestador")
    if de_est is None and de_man is None:
        # REV15-2 / R15-3 (I1.6): el núcleo escribe la marca desde I1.5, cuando nació la respuesta v2 del experto. Un
        # paquete con respuesta v2 o posterior y sin marca solo sale de un estado editado y resellado (quitar marca y
        # procedencia de B para ir por la vía de A, que no pide relectura): FALLA. La vía heredada queda para v1.
        if not es_contrato_experto_v1(getattr(ctx, "respuesta", None)):
            c.falla("paquete con la respuesta del experto posterior a I1.5 (v2 o posterior) y sin marca de orquestador "
                    "en estado.json ni en el manifiesto: el núcleo de su época siempre la escribe (REV15-2)")
            return None
        c.nota(f"paquete sin marca de orquestador y con la respuesta del experto v1 (núcleo anterior a I1.5): la vía de "
               f"A o de B la decide que traiga {NOMBRE_PROCEDENCIA}")
        return None
    if de_est not in ORQUESTADORES or de_man != de_est:
        c.falla(f"marca de orquestador incoherente: estado.json dice {de_est!r} y el manifiesto {de_man!r} (deben ser "
                "A o B, y la misma)")
        return None
    if de_est == "B" and not con_fichero:
        c.falla(f"el código marcó el paquete como de B y no trae {NOMBRE_PROCEDENCIA}: sin ella nada prueba de dónde "
                "salen las respuestas del experto y del verificador")
    elif de_est == "A" and con_fichero:
        c.falla(f"el código marcó el paquete como de A y trae {NOMBRE_PROCEDENCIA}, que solo escribe el hosted de B")
    else:
        c.nota(f"orquestador {de_est} (marca del código en estado.json y en el manifiesto)")
    return de_est


def c_procedencia(ctx: Contexto) -> Comprobacion:
    """Procedencia · Salidas A2A registradas en las trazas = las del estado (si hay trazas)."""
    c = Comprobacion("procedencia_a2a", c_procedencia.__doc__.split("·")[1].strip())
    doc_b = None
    con_fichero = NOMBRE_PROCEDENCIA in (getattr(getattr(ctx, "paquete", None), "ficheros", None) or {})
    if con_fichero:
        try:
            doc_b = json.loads(ctx.paquete.bytes_de(NOMBRE_PROCEDENCIA).decode("utf-8"), parse_constant=_sin_nan)
        except (UnicodeDecodeError, ValueError) as e:
            c.falla(f"{NOMBRE_PROCEDENCIA}: ilegible ({e})")
            return c
    orquestador_declarado(ctx, c, con_fichero)
    if c.estado == FALLA:
        return c
    usadas: list[tuple[str, dict]] = []
    if doc_b is not None:
        # INT-3 (I1.5): la parte local se comprueba siempre, también con --sin-red; solo la de trazas necesita red.
        c.nota(f"paquete con {NOMBRE_PROCEDENCIA} (opción B): se contrasta por task_id")
        usadas = _procedencia_b_local(ctx, c, doc_b)
        if c.estado == FALLA or not usadas:
            return c
    if ctx.sin_red:
        if doc_b is not None:
            c.no_verificado("--sin-red: parte local de la procedencia de B comprobada; el task_id y el comienzo de cada "
                            "tarea en las trazas, sin comprobar (riesgo residual)")
        else:
            c.no_verificado("--sin-red: procedencia A2A sin comprobar; va como riesgo residual")
        return c
    try:
        conexiones = (ctx.conexiones_appi or conexiones_appi_real)()
    except Exception as e:  # noqa: BLE001 - se declara, no se aprueba
        c.no_verificado(f"no se pudo leer la conexión de App Insights del proyecto: {type(e).__name__}: {str(e)[:300]}")
        return c
    destinos = [str((x.get("properties") or {}).get("target") or "") for x in conexiones]
    if not any(t.rstrip("/").lower().endswith(f"/components/{APPI_ESPERADO}") for t in destinos):
        c.no_verificado(f"la conexión de App Insights del proyecto no apunta a {APPI_ESPERADO} "
                        f"(apunta a {destinos or 'ninguna'}): procedencia A2A NO VERIFICADA")
        return c
    if doc_b is not None:
        _procedencia_b_trazas(ctx, c, usadas)
        return c
    pares = [("experto", ctx.respuesta.get("brief_id"), "brief_id", ctx.respuesta, True)]
    cons, ver = ctx.carga.get("consolidado") or {}, ctx.carga.get("verificacion") or {}
    if ver.get("lotes"):
        # VER13-1 (I1.3): con lotes, la respuesta combinada la compone el código y nunca viaja por A2A; lo que tiene
        # que estar en las trazas es la salida de cada lote (su consolidado_id es el del lote). Un lote del estado
        # sin respuesta guardada falla: no hay nada que contrastar.
        for x in cons.get("lotes") or []:
            pares.append((f"verificador {x.get('lote_id')}", x.get("lote_id"), "consolidado_id", x.get("respuesta"),
                          False))
    else:
        pares.append(("verificador", cons.get("consolidado_id"), "consolidado_id", ver.get("respuesta") or {}, False))
    for quien, ident, clave, guardado, es_experto in pares:
        if not isinstance(ident, str) or not ident or not isinstance(guardado, dict) or not guardado:
            c.falla(f"{quien}: el estado no guarda el identificador o la salida A2A que hay que contrastar")
            continue
        ventana = ventana_a(ctx, es_experto)
        if ventana is None:
            filtro = "| where timestamp > ago(30d) "
            c.aviso(f"{quien}: el estado no permite acotar la ventana de la ejecución: se busca en 30 días")
        else:
            filtro = f"| where timestamp between ({kql_instante(ventana[0])} .. {kql_instante(ventana[1])}) "
        consulta = ("union requests, dependencies, traces, customEvents " + filtro +
                    f"| where tostring(customDimensions) has {_kql_literal(ident)} "
                    "or tostring(column_ifexists('message', '')) has " + _kql_literal(ident) +
                    " | project timestamp, itemType, name, op = operation_Id, dims = tostring(customDimensions), "
                    f"message = tostring(column_ifexists('message', '')) | order by timestamp desc | take {TOPE_FILAS}")
        try:
            filas = (ctx.consultar_kql or consultar_kql_real)(consulta)
        except Exception as e:  # noqa: BLE001
            c.no_verificado(f"{quien}: consulta KQL fallida: {type(e).__name__}: {str(e)[:300]}")
            continue
        veredicto, detalle = juzgar_procedencia(filas, clave, ident, guardado)
        if len(filas) >= TOPE_FILAS and veredicto != OK:
            c.falla(f"{quien}: la consulta alcanzó el tope de {TOPE_FILAS} filas en la ventana "
                    f"({ventana[2] if ventana else '30 días'}): el resultado puede estar incompleto ({detalle})")
        elif veredicto == OK:
            c.nota(f"{quien}: {detalle}")
        elif veredicto == NOV:
            c.no_verificado(f"{quien}: {detalle}")
        else:
            c.falla(f"{quien}: {detalle}")
    return c


# ══ I1.9 · réplicas de P (docs/I1/CAMBIOS-I19-P/replicas_puerta.py, §7, §7.1 y §12.3; pegadas por el integrador) ══
# Las que sustituyen a una de la puerta están en el sitio de la anterior; estas son las que se añaden.

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


es_existente = es_existente_r  # I1.9: el nombre del núcleo, para que region_no_admitida sea el mismo código (test_i12)


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
            por = r.get("por_instancia")  # VC19-1 (I1.10)
            por_dec = _dec_r(por) if por is not None else None
            if por is not None and (isinstance(por, bool) or por_dec is None or por_dec <= 0):
                return False
            salida.append({**base, "palabras": list(palabras), "cortas": list(cortas or []), "limite": limite,
                           "limite_json": r.get("limite"), "por_instancia": por_dec})
        elif r.get("tipo") == "caracteristica":
            claves = r.get("palabras_clave")
            if not isinstance(claves, list) or not claves or not all(isinstance(w, str) and _compacto(w) for w in claves) \
                    or r.get("por_instancia") is not None:
                return False
            salida.append({**base, "palabras_clave": list(claves)})
        else:
            return False
    return salida


VENTANA_UNIDAD_R = 3


MILLARES_ESPACIO_R = re.compile(r"(?<![\d.,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)")  # réplica de experto (ARR1)


def sin_espacios_de_millar_r(m) -> str:
    """Réplica de experto._sin_espacios_de_millar."""
    sigue_decimal = re.match(r"\.\d", m.string[m.end():m.end() + 2]) is not None
    return re.sub(r"[ \u00a0\u202f]", "" if sigue_decimal else ".", m.group(0))


def numeros_con_unidad_r(cita, palabras, cortas=(), ventana=None) -> list:
    texto = cita if isinstance(cita, str) else ""
    raices = [_raiz_r(t) for w in palabras if isinstance(w, str) for t in _tokens(w) if len(t) >= 4]
    exactas = {t for w in cortas or () if isinstance(w, str) for t in _tokens(w)}
    if not raices and not exactas:
        return []
    texto = MILLARES_ESPACIO_R.sub(sin_espacios_de_millar_r, texto)  # ARR1 (Revisión)
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


def nivel_defecto_r(fila):
    """Réplica de nucleo.experto.nivel_por_defecto: el nivel por defecto solo con {nivel, fuente https}."""
    nd = _obj_replica(fila.get("nivel_por_defecto") if isinstance(fila, dict) else None)
    nombre, fuente = _plano_req_replica(nd.get("nivel")), _texto_r(nd.get("fuente")) or _texto_r(nd.get("fuente_url"))
    if not nombre or not fuente or not fuente.startswith("https://"):
        return None
    return next((n for n in _niveles_r(fila) if nombre in n["nombres"]), None)


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


def necesarias_r(razon: dict, cita) -> int | None:
    """Réplica de nucleo.experto.instancias_necesarias (VC19-1)."""
    if not razon.get("por_instancia"):
        return None
    nums = numeros_con_unidad_r(cita, razon["palabras"], razon.get("cortas"), VENTANA_UNIDAD_R)
    return int((max(nums) / razon["por_instancia"]).to_integral_value(rounding=ROUND_CEILING)) if nums else None


def insuficiencia_r(niveles: list, propias: list, sumas: dict, requisitos, brief_texto) -> tuple[list[str], object]:
    """Réplica de nucleo.experto._insuficiencia (VC19-1, I1.10): (reglas, instancias del nivel usado)."""
    usado = next((k for k, n in enumerate(niveles) if n["plantillas"] and set(propias) & n["plantillas"]), None)
    if usado is None:
        return [], None
    nivel, reglas = niveles[usado], []
    veces = max((v for _, pl, v in sumas.values() if pl.get("id") in nivel["plantillas"]), default=None)
    for superior in niveles[usado + 1:]:
        razones = superior["razones"] if isinstance(superior["razones"], list) else []
        if any(r["tipo"] == "umbral" and not r.get("por_instancia") and any(
                razon_cumplida_r(r, x) for x in citas_campos_r(requisitos, brief_texto, (r["campo"],), sin_asumido=True))
               for r in razones):
            reglas[:] = ["nivel_insuficiente"]  # una sola por componente, como el núcleo (ARR1, I1.10)
    for r in (nivel["razones"] if isinstance(nivel["razones"], list) and not reglas else []):
        if r["tipo"] != "umbral" or not r.get("por_instancia"):
            continue
        ns = [necesarias_r(r, x) for x in citas_campos_r(requisitos, brief_texto, (r["campo"],), sin_asumido=True)
              if razon_cumplida_r(r, x)]
        ns = [n for n in ns if n is not None]
        if ns and veces is not None and veces < max(ns):
            reglas.append("instancias_insuficientes")
    return reglas, veces


def _reglas_razon_r(jn: dict, razones, requisitos, brief_texto, veces=None) -> list[str]:
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
    if not razon_cumplida_r(razon, cita):
        return ["razon_no_cumplida"]
    n = necesarias_r(razon, cita)
    return ["instancias_no_cuadran"] if n is not None and veces is not None and veces != n else []


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


def es_contrato_experto_v4(resp) -> bool:
    """Respuesta de I1.7 o I1.8 (contrato v4): completada (con valoracion_nucleo) y sin existente_del_cliente en sus
    componentes. Se valida con historico/respuesta_experto_completa_v4 y FALLA en «experto» (puerta de su época)."""
    comps = resp.get("componentes") if isinstance(resp, dict) else None
    return (isinstance(comps, list) and bool(comps) and "valoracion_nucleo" in resp
            and not any(isinstance(x, dict) and "existente_del_cliente" in x for x in comps))


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


COMPROBACIONES = [c_estructura, c_integridad, c_esquemas, c_montados, c_suficiencia, c_experto, c_brief,
                  c_referencias_vivas, c_verificacion, c_estimacion, c_cliente, c_marcadores, c_diagrama,
                  c_coherencia, c_recomposicion, c_marca, c_decisiones, c_previo, c_procedencia]


# ───────────────────────────── render, archivo e informe ─────────────────────────────

_PS_RENDER = r"""
$ErrorActionPreference = 'Stop'
if (Get-Process -Name POWERPNT -ErrorAction SilentlyContinue) { Write-Output 'OCUPADO'; exit 3 }
$limite = (Get-Date).AddSeconds(-1)
$pp = New-Object -ComObject PowerPoint.Application
# D15-5: la instancia propia es el ÚNICO POWERPNT vivo, arrancado después de comprobar que no había ninguno y lanzado
# por COM (/AUTOMATION -Embedding). Un PowerPoint que abra el usuario en ese intervalo no lleva esa línea de órdenes:
# entonces no hay instancia propia identificada y no se cierra ni se espera nada.
$propio = $null
try {
  $todos = @(Get-Process -Name POWERPNT -ErrorAction SilentlyContinue)
  $com = @(Get-CimInstance -ClassName Win32_Process | Where-Object { $_.Name -eq 'POWERPNT.EXE' -and $_.CreationDate -ge $limite -and $_.CommandLine -match '/AUTOMATION' -and $_.CommandLine -match '-Embedding' })
  if ($todos.Count -eq 1 -and $com.Count -eq 1 -and $todos[0].Id -eq $com[0].ProcessId) { $propio = $todos[0]; Write-Output ('PID_PROPIO=' + $propio.Id) }
  else { Write-Output ('PID_PROPIO=AMBIGUO ' + $todos.Count + ' ' + $com.Count) }
} catch { Write-Output ('PID_PROPIO=AMBIGUO error ' + $_.Exception.GetType().Name) }
$ajenas = 0
$M = [Runtime.InteropServices.Marshal]
try {
  $col = $pp.Presentations
  $pres = $col.Open($env:VP_PPTX, $true, $false, $false)
  try {
    # Cada objeto COM se libera al usarlo: una referencia viva (diapositiva, colección) mantiene POWERPNT abierto
    # después de Quit y la espera de abajo no acabaría nunca.
    $diapos = $pres.Slides
    $n = $diapos.Count
    for ($i = 1; $i -le $n; $i++) {
      $s = $diapos.Item($i)
      try { $s.Export((Join-Path $env:VP_DESTINO ('diapositiva_{0:D2}.png' -f $i)), 'PNG', 1920, 1080) }
      finally { [void]$M::ReleaseComObject($s); $s = $null }
    }
    [void]$M::ReleaseComObject($diapos); $diapos = $null
  } finally { $pres.Close(); [void]$M::ReleaseComObject($pres); $pres = $null }
} finally {
  # Si alguien abrió otra presentación en esta instancia mientras se exportaba, no se cierra (sería suya).
  try { $ajenas = $col.Count } catch { $ajenas = -1 }
  if ($col) { [void]$M::ReleaseComObject($col); $col = $null }
  if ($propio -and $ajenas -eq 0) { $pp.Quit() }
  elseif ($ajenas -ne 0) { Write-Output ('AJENAS=' + $ajenas) }
  else { Write-Output 'SIN_QUIT' }
  [void]$M::ReleaseComObject($pp); $pp = $null
  [GC]::Collect(); [GC]::WaitForPendingFinalizers(); [GC]::Collect()
  # Esperar a que termine la instancia propia: si sigue viva, la apertura siguiente falla («could not open the file»).
  if ($propio -and $ajenas -eq 0) {
    if ($propio.WaitForExit([int]$env:VP_ESPERA_MS)) { Write-Output 'TERMINADA_PROPIA' }
    else {
      try { $propio.Kill(); [void]$propio.WaitForExit(10000) } catch { }
      if ($propio.HasExited) { Write-Output 'CERRADA_PROPIA' } else { Write-Output 'SIGUE_PROPIA' }
    }
  }
}
Write-Output 'RENDER_OK'
"""
_PIDS_RENDER_PROPIOS: set[int] = set()   # PID de las instancias de PowerPoint que abrió esta puerta (D15-5)


def pids_powerpoint() -> set[int]:
    """PID de los procesos POWERPNT.EXE vivos (tasklist, sin tocar ninguno)."""
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq POWERPNT.EXE", "/FO", "CSV", "/NH"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=30)
    return {int(m.group(1)) for m in re.finditer(r'^"POWERPNT\.EXE","(\d+)"', r.stdout, re.M | re.I)}


def renderizar(pptx: pathlib.Path, destino: pathlib.Path, espera_s: float = 30.0,
               ejecutar: Callable[..., Any] = subprocess.run, procesos: Callable[[], set[int]] = pids_powerpoint,
               dormir: Callable[[float], None] | None = None) -> tuple[bool, str]:
    """Exporta cada diapositiva a PNG con PowerPoint por COM, en una instancia propia.

    PowerPoint es de instancia única: si ya está abierto, COM se engancharía a la instancia de
    el comercial y Quit cerraría sus presentaciones. En ese caso no se renderiza y se avisa.
    D15-5 (I1.6): robusto ante llamadas seguidas. El guion espera a que termine SU instancia (la que arrancó él) y,
    si no termina, la cierra; nunca cierra otra. Antes de arrancar, si los POWERPNT vivos son todos instancias que
    abrió esta puerta (PID anotado), espera a que terminen; si hay uno que no es suyo, OCUPADO, sin tocarlo.
    """
    import time
    dormir = dormir or time.sleep
    vivos, fin = procesos(), time.monotonic() + espera_s
    while vivos and vivos <= _PIDS_RENDER_PROPIOS and time.monotonic() < fin:
        dormir(1.0)
        vivos = procesos()
    if vivos and vivos <= _PIDS_RENDER_PROPIOS:
        return False, (f"la instancia de PowerPoint que abrió esta puerta (PID {sorted(vivos)}) sigue viva tras "
                       f"{espera_s:.0f} s: no se arranca otra; repite --render cuando termine")
    if vivos:
        return False, "PowerPoint ya está abierto: ciérralo y repite con --render (no se usa ni se cierra tu instancia)"
    destino.mkdir(parents=True, exist_ok=True)
    entorno = dict(os.environ, VP_PPTX=str(pptx.resolve()), VP_DESTINO=str(destino.resolve()),
                   VP_ESPERA_MS=str(int(espera_s * 1000)))
    r = ejecutar(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_RENDER], env=entorno,
                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300 + 2 * espera_s)
    salida = r.stdout or ""
    _PIDS_RENDER_PROPIOS.update(int(p) for p in re.findall(r"^PID_PROPIO=(\d+)\s*$", salida, re.M))
    if "OCUPADO" in salida:
        return False, "PowerPoint ya está abierto: ciérralo y repite con --render (no se usa ni se cierra tu instancia)"
    if r.returncode != 0 or "RENDER_OK" not in salida:
        return False, f"render fallido rc={r.returncode}: {(r.stderr or salida).strip()[-400:]}"
    notas = []
    if "CERRADA_PROPIA" in salida:
        notas.append(f"la instancia propia no terminó en {espera_s:.0f} s y se cerró")
    if "SIGUE_PROPIA" in salida:
        notas.append("la instancia propia sigue viva tras intentar cerrarla: el siguiente --render esperará")
    if "AJENAS=" in salida:
        notas.append("PowerPoint queda abierto: alguien abrió otra presentación en esa instancia durante el render")
    if "PID_PROPIO=AMBIGUO" in salida:
        notas.append("no se pudo identificar la instancia propia (más de un POWERPNT o uno no lanzado por COM): no se ha "
                     "cerrado ni esperado nada y PowerPoint puede quedar abierto")
    pngs = sorted(destino.glob("diapositiva_*.png"))
    return bool(pngs), f"{len(pngs)} PNG en {destino}" + (f" ({'; '.join(notas)})" if notas else "")


def carpeta_checkpoint(workspace: pathlib.Path, cliente: str, codigo: str) -> pathlib.Path:
    from lib.auditoria import sanear_nombre
    if sanear_nombre(cliente) != cliente:
        raise EntradaIlegible(f"nombre de cliente no apto como carpeta: {cliente!r}")
    base = workspace / "_clientes" / cliente
    if not base.is_dir():
        raise EntradaIlegible(f"no existe la carpeta del cliente {base} (no se crea por si es una errata)")
    return base / "docs" / ".checkpoints" / codigo


def _destino_libre(carpeta: pathlib.Path, nombre: str, datos_sha: str) -> tuple[pathlib.Path, bool]:
    """Destino sin sobrescribir nunca: (ruta, ya_existía_idéntico)."""
    p = carpeta / nombre
    if p.exists():
        if sha256_fichero(p) == datos_sha:
            return p, True
        raiz, _, ext = nombre.rpartition(".")
        p = carpeta / f"{raiz}-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
    return p, False


def archivar(ctx: Contexto, carpeta: pathlib.Path, informe: dict) -> list[str]:
    """Copia el paquete y el informe a la carpeta de checkpoints; nunca sobrescribe."""
    carpeta.mkdir(parents=True, exist_ok=True)
    estado, notas = ctx.estado.get("estado"), []
    if ctx.paquete.es_zip:
        sha = ctx.paquete.zip_sha256 or ""
        dest, igual = _destino_libre(carpeta, f"{ctx.codigo}-Paquete-{estado}.zip", sha)
        if not igual:
            shutil.copyfile(ctx.paquete.origen, dest)
        notas.append(f"{'ya archivado' if igual else 'archivado'}: {dest}")
    else:
        sub = carpeta / str(estado)
        sub.mkdir(exist_ok=True)
        for nombre in nombres_paquete(ctx.codigo, estado, ctx.fecha_paquete()):
            dest, igual = _destino_libre(sub, nombre, sha256_fichero(ctx.paquete.ficheros[nombre]))
            if not igual:
                shutil.copyfile(ctx.paquete.ficheros[nombre], dest)
        notas.append(f"archivado en {sub}")
    texto = json.dumps(informe, ensure_ascii=False, indent=2)
    dest, igual = _destino_libre(carpeta, f"verificacion-{estado}.json", sha256_bytes(texto.encode("utf-8")))
    if not igual:
        dest.write_text(texto, encoding="utf-8", newline="\n")
    return notas


def previo_archivado(carpeta: pathlib.Path, codigo: str, sha_actual: str | None) -> pathlib.Path | None:
    if not carpeta.is_dir():
        return None
    zips = [p for p in carpeta.glob(f"{codigo}-Paquete*.zip") if sha256_fichero(p) != sha_actual]
    return max(zips, key=lambda p: p.stat().st_mtime) if zips else None


def veredicto(rc: int, nov: list[str]) -> str:
    if rc == 3:
        return "NO VERIFICADO CON --estricto"
    return "FALLA" if rc else ("OK CON NO VERIFICADOS" if nov else "OK")


def informe_dict(ctx: Contexto, resultados: list[Comprobacion], rc: int) -> dict:
    try:
        h = ctx.hash_vigente()
    except Exception:  # noqa: BLE001
        h = None
    nov = [r.id for r in resultados if r.estado == NOV]
    return {"veredicto": veredicto(rc, nov), "rc": rc,
            "no_verificados": nov, "paquete": str(ctx.paquete.origen),
            "paquete_sha256": ctx.paquete.zip_sha256, "codigo": ctx.codigo, "estado": ctx.estado.get("estado"),
            "hash_contenido_recalculado": h, "hoy": ctx.hoy.isoformat(),
            "comprobaciones": [dataclasses.asdict(r) for r in resultados]}


def imprimir(ctx: Contexto, resultados: list[Comprobacion], rc: int) -> None:
    print(f"=== VERIFICAR PAQUETE · {ctx.codigo} · {ctx.estado.get('estado')} ===")
    for r in resultados:
        print(f"[{r.estado}] {r.id}: {r.titulo}")
        for d in r.detalles:
            print(f"    - {d}")
    fallan = [r.id for r in resultados if r.estado == FALLA]
    nov = [r.id for r in resultados if r.estado == NOV]
    print(f"VEREDICTO: {veredicto(rc, nov)} rc={rc} · fallan {len(fallan)} {fallan} · NO VERIFICADO {len(nov)} {nov}")
    if rc == 0 and nov:
        print("ATENCIÓN: lo NO VERIFICADO no está comprobado; debe figurar como riesgo residual en la nota.")
    if rc == 3:
        print("ATENCIÓN: con --estricto, lo NO VERIFICADO bloquea (rc 3): verifica con red y con --previo.")


def main(argv: list[str] | None = None, **inyectado: Any) -> int:
    ap = argparse.ArgumentParser(description="Puerta real de I1: verifica un paquete de preventa en local.")
    ap.add_argument("paquete", help="ZIP del paquete o carpeta con sus ficheros")
    ap.add_argument("--transcripcion", help="transcripción local (su SHA-256 debe ser el de su fuente del alta)")
    ap.add_argument("--notas", help="notas del comercial locales (NOTAS_COMERCIAL.md); al menos una de las dos")
    ap.add_argument("--aclaracion", action="append", default=[], metavar="Fn=RUTA")
    defectos = por_defecto()
    for clave in defectos:
        ap.add_argument(f"--{clave.replace('_', '-')}", default=None)   # None: no fijada (precedencia, Revisión)
    ap.add_argument("--previo", help="paquete previo del mismo código (ZIP o carpeta)")
    ap.add_argument("--sin-red", action="store_true", help="no consulta URL ni trazas (quedan NO VERIFICADO)")
    ap.add_argument("--json", help="escribe el informe en este fichero")
    ap.add_argument("--render", metavar="CARPETA", help="exporta las diapositivas a PNG con PowerPoint")
    ap.add_argument("--archivar", metavar="CLIENTE", help="con rc 0, copia a _clientes/<CLIENTE>/docs/.checkpoints")
    ap.add_argument("--auditar", action="store_true", help="con rc 0, añade una línea a _audit/log.jsonl")
    ap.add_argument("--workspace", default=str(raiz_proyectos()))
    ap.add_argument("--hoy", help="fecha de referencia AAAA-MM-DD (por defecto, hoy)")
    ap.add_argument("--confirmo-stop", metavar="HASH", help="El comercial confirma en local el STOP (> 100.000 EUR) de este hash")
    ap.add_argument("--confirmo-ajuste", metavar="HASH", help="El comercial confirma en local el ajuste comercial de este hash")
    ap.add_argument("--estricto", action="store_true", help="lo NO VERIFICADO da rc 3 en vez de rc 0 (R4)")
    a = ap.parse_args(argv)
    explicitas = frozenset(k for k in defectos if getattr(a, k) is not None)
    for k, ruta in defectos.items():
        if getattr(a, k) is None:
            setattr(a, k, str(ruta))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    # ignore_cleanup_errors: un manejador que deja abierto openpyxl sobre un XLSX corrupto no debe
    # convertir el veredicto ya impreso en una excepción (el rc lo decide la verificación, no la limpieza)
    with tempfile.TemporaryDirectory(prefix="verificar_paquete_", ignore_cleanup_errors=True) as tmpd:
        tmp = pathlib.Path(tmpd)
        try:
            acl = dict(x.split("=", 1) for x in a.aclaracion)
            hoy = dt.date.fromisoformat(a.hoy) if a.hoy else dt.date.today()
            paquete = abrir_paquete(pathlib.Path(a.paquete), tmp)
            if not a.transcripcion and not a.notas:
                raise EntradaIlegible("falta la fuente: --transcripcion, --notas o las dos")
            ctx = Contexto(paquete, pathlib.Path(a.transcripcion) if a.transcripcion else None,
                           {k: pathlib.Path(v) for k, v in acl.items()},
                           pathlib.Path(a.rate_card), pathlib.Path(a.generador), pathlib.Path(a.plantilla),
                           pathlib.Path(a.catalogo), pathlib.Path(a.previo) if a.previo else None, a.sin_red, hoy,
                           tmp, **inyectado)
            ctx.confirmo_stop, ctx.confirmo_ajuste = a.confirmo_stop, a.confirmo_ajuste
            ctx.precios = pathlib.Path(a.precios)
            ctx.notas = pathlib.Path(a.notas) if a.notas else None
            ctx.explicitas = explicitas
            preparar(ctx)
            carpeta = carpeta_checkpoint(pathlib.Path(a.workspace), a.archivar, ctx.codigo) if a.archivar else None
            if carpeta is not None and ctx.previo is None:
                ctx.previo = previo_archivado(carpeta, ctx.codigo, paquete.zip_sha256)
        except (EntradaIlegible, ValueError, OSError) as e:
            print(f"ENTRADA ILEGIBLE rc=2: {type(e).__name__}: {e}")
            return 2
        resultados = ejecutar(ctx, COMPROBACIONES)
        rc = 1 if any(r.estado == FALLA for r in resultados) else 0
        if rc == 0 and a.estricto and any(r.estado == NOV for r in resultados):
            rc = 3  # R4: con --estricto, lo no verificado no se lee como un verde (LES-G-091)
        informe = informe_dict(ctx, resultados, rc)
        imprimir(ctx, resultados, rc)
        if a.render:
            ok, msg = renderizar(ctx.ruta_pptx(), pathlib.Path(a.render))
            print(f"RENDER: {'OK' if ok else 'NO REALIZADO'} · {msg} · la revisión visual (LES-G-072) la hace el comercial")
            informe["render"] = {"ok": ok, "detalle": msg}
        if a.json:
            pathlib.Path(a.json).write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
        if (a.archivar or a.auditar) and rc != 0:
            print("NO SE ARCHIVA NI SE AUDITA: el veredicto no es OK")
        elif a.archivar or a.auditar:
            from lib.auditoria import anadir_linea, linea_auditoria
            notas = archivar(ctx, carpeta, informe) if carpeta is not None else []
            for n in notas:
                print(f"ARCHIVO: {n}")
            resumen = (ctx.carga.get("estimacion") or {}).get("resumen") or {}
            linea = linea_auditoria(cliente=a.archivar or ctx.carga.get("alta", {}).get("cliente", ""),
                                    codigo=ctx.codigo, version=ctx.estado.get("version"),
                                    estado=ctx.estado.get("estado"), hash_contenido=ctx.hash_vigente(),
                                    precio_cerrado_eur=str(ctx.xlsx().precio),
                                    horas_total=resumen.get("horas_total"), zip_nombre=paquete.origen.name,
                                    zip_sha256=paquete.zip_sha256,
                                    destino=str(carpeta) if carpeta is not None else "",
                                    veredicto=informe["veredicto"])
            anadir_linea(pathlib.Path(a.workspace) / "_audit" / "log.jsonl", linea)
            print(f"AUDITORÍA: línea añadida a {pathlib.Path(a.workspace) / '_audit' / 'log.jsonl'}")
        ctx._cache.clear()
        gc.collect()  # cierra los ZIP que retienen los ciclos de las excepciones antes de borrar
        return rc


if __name__ == "__main__":
    sys.exit(main())
