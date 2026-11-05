"""Apoyo común de las pruebas de documentos (C): rutas, fixtures y dobles de módulos ajenos.

Los dobles SOLO se instalan si falta un módulo de nucleo (el propio o uno del que depende), y
SOLO mientras dura el fixture `docs` de cada módulo de pruebas: al terminar se restauran
`sys.modules` y el paquete `nucleo` tal como estaban, para no contaminar las pruebas de otros
papeles en la misma sesión (LES-G-083). Con los módulos reales entregados, se usan los reales.
"""
from __future__ import annotations

import contextlib
import copy
import importlib
import json
import pathlib
import re
import sys
import types
import unicodedata
import warnings

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SANDBOX = RAIZ / "sandbox"
EJEMPLOS = RAIZ / "esquemas" / "ejemplos"
if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))



def _doble_errores() -> types.ModuleType:
    m = types.ModuleType("nucleo.errores")

    class ErrorPreventa(Exception):
        codigo_salida = 5

        def __init__(self, mensaje: str, errores: list[str] | None = None):
            super().__init__(mensaje)
            self.mensaje = mensaje
            self.errores = list(errores or [])

    for nombre, rc in (("EntradaInvalida", 2), ("ReglaIncumplida", 1), ("Bloqueo", 1),
                       ("TransicionNoPermitida", 3), ("IntegridadRota", 4)):
        setattr(m, nombre, type(nombre, (ErrorPreventa,), {"codigo_salida": rc}))
    m.ErrorPreventa = ErrorPreventa
    return m


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


def _doble_textos() -> types.ModuleType:
    """Réplica mínima del barrido de §0 y §9.3 (solo para pruebas; la real es de textos_cliente)."""
    m = types.ModuleType("nucleo.textos_cliente")

    def marcadores(texto: str) -> list[str]:
        h = [x for x in re.findall(r"\b(TBD|TODO|XXX|PLACEHOLDER)\b", texto)]
        h += [x for x in re.findall(r"\b(pendientes?|por definir|lorem)\b", _sin_tildes(texto))]
        h += re.findall(r"<[^<>\n]{1,60}>", texto)
        return [f"marcador {x}" for x in h]

    def barrer(texto: str, perfiles: list[str]) -> list[str]:
        h = marcadores(texto)
        bajo = _sin_tildes(texto)
        if re.search(r"\b\d+([.,]\d+)?\s*(h|horas?)\b", bajo):
            h.append("horas")
        for palabra in ("jornada", "dias-persona", "tarifa", "contingencia", "ajuste comercial", "€/h", "eur/h"):
            if palabra in bajo:
                h.append(palabra)
        for perfil in perfiles:
            if _sin_tildes(perfil) in bajo:
                h.append(f"perfil {perfil}")
        if re.search(r"\b(REF|RG|BRF|CNS|R|C|P|T|S)-[0-9A-Za-z]", texto) or re.search(r"\b[a-z]+_[a-z_]+\b", texto):
            h.append("identificador técnico")
        if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", texto):
            h.append("correo")
        return h

    m.marcadores, m.barrer = marcadores, barrer
    m.frases_excluidas = lambda textos: list(textos.get("excluidas") or [])
    return m


def _doble_decision() -> types.ModuleType:
    m = types.ModuleType("nucleo.decision")

    def firmas(estado: dict) -> dict:
        fecha = ((estado.get("carga") or {}).get("estimacion") or {}).get("entrada", {}).get("fecha")
        out = {"elaborado": {"nombre": "Responsable comercial", "iniciales": "RC", "fecha": fecha},
               "revisado": None, "aprobado": None}
        for d in estado.get("decisiones") or []:
            if d.get("tipo") != "APROBADA" or d.get("version") != estado.get("version"):
                continue
            clave = "revisado" if _sin_tildes(d["revisor"]) == "responsable de preventa" else "aprobado"
            out[clave] = {"nombre": d["revisor"], "iniciales": "", "fecha": d["fecha"]}
        return out

    m.firmas = firmas
    return m


def _falta_fichero_nucleo(exc: ImportError) -> bool:
    """¿El ImportError se debe a un módulo de nucleo cuyo fichero NO existe todavía en el repositorio?

    Si el fichero existe y aun así falla, es un error real del módulo y no se tapa con un doble.
    """
    if isinstance(exc, ModuleNotFoundError) and (exc.name or "").startswith("nucleo."):
        falta = exc.name.split(".", 1)[1]
    elif exc.name == "nucleo":
        m = re.search(r"cannot import name '(\w+)'", str(exc))
        if not m:
            return False
        falta = m.group(1)
    else:
        return False
    return not (SANDBOX / "nucleo" / f"{falta.split('.')[0]}.py").exists()


def instalar_dobles() -> list[str]:
    """Instala los dobles que hagan falta y devuelve sus nombres. Usar solo dentro de `entorno_documentos`."""
    import nucleo  # noqa: F401  (paquete real de A)

    instalados = []
    for nombre, fabrica, api in (("errores", _doble_errores, ("IntegridadRota", "ReglaIncumplida")),
                                 ("textos_cliente", _doble_textos, ("marcadores", "barrer", "frases_excluidas")),
                                 ("decision", _doble_decision, ("firmas",))):
        completo = f"nucleo.{nombre}"
        ajeno = sys.modules.get(completo)
        if ajeno is not None and getattr(ajeno, "__file__", None) is None and not all(hasattr(ajeno, a) for a in api):
            # Doble de otro papel que se ha quedado en sys.modules y no trae la API que usa BC:
            # se sustituye solo mientras dura el fixture (entorno_documentos lo devuelve al salir).
            sys.modules.pop(completo)
            modulo = fabrica()
            sys.modules[completo] = modulo
            setattr(sys.modules["nucleo"], nombre, modulo)
            instalados.append(nombre)
            warnings.warn(f"pruebas de documentos: doble ajeno incompleto de nucleo.{nombre} sustituido "
                          f"temporalmente (le falta {[a for a in api if not hasattr(ajeno, a)]})", stacklevel=2)
            continue
        try:
            importlib.import_module(completo)
        except ImportError as exc:
            # Solo si lo que falta es un módulo de nucleo (el propio o uno del que depende y que su
            # dueño aún no ha entregado). Cualquier otro error de importación se propaga.
            if not _falta_fichero_nucleo(exc):
                raise
            sys.modules.pop(completo, None)
            modulo = fabrica()
            sys.modules[completo] = modulo
            setattr(sys.modules["nucleo"], nombre, modulo)
            instalados.append(nombre)
            warnings.warn(f"pruebas de documentos con DOBLE de nucleo.{nombre}: {exc}", stacklevel=2)
    return instalados


def _es_nucleo(nombre: str) -> bool:
    return nombre == "nucleo" or nombre.startswith("nucleo.")


@contextlib.contextmanager
def entorno_documentos():
    """Dobles + módulos de BC importados; al salir, sys.modules y `nucleo` quedan como estaban."""
    previos = {k: v for k, v in sys.modules.items() if _es_nucleo(k)}
    paquete = sys.modules.get("nucleo")
    atributos = dict(vars(paquete)) if paquete is not None else None
    try:
        instalados = instalar_dobles()
        pr = importlib.import_module("nucleo.pptx_revision")
        nr = importlib.import_module("nucleo.nota_revision")
        me = importlib.import_module("nucleo.mensajes")
        # errores y hashes: los mismos objetos que usan los módulos probados
        yield types.SimpleNamespace(pr=pr, nr=nr, me=me, errores=pr.errores, hashes=pr.hashes, dobles=instalados)
    finally:
        for k in [k for k in sys.modules if _es_nucleo(k) and k not in previos]:
            del sys.modules[k]
        sys.modules.update(previos)
        if paquete is not None:
            for k in [k for k in vars(paquete) if k not in atributos]:
                delattr(paquete, k)
            for k, v in atributos.items():
                setattr(paquete, k, v)


def cargar_json(nombre: str) -> dict:
    return json.loads((EJEMPLOS / nombre).read_text(encoding="utf-8"))


def estado_ejemplo() -> dict:
    return copy.deepcopy(cargar_json("estado.json"))


def catalogo_ejemplo() -> dict:
    return copy.deepcopy(cargar_json("catalogo_componentes.json"))


@pytest.fixture(scope="module")
def docs():
    with entorno_documentos() as ns:
        yield ns
