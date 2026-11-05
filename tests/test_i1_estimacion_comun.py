"""Utilidades comunes de las pruebas de B (estimación y anexo). Sin red.

Importa `sandbox/nucleo` del repositorio. Si un módulo de otro constructor todavía NO existe
(ModuleNotFoundError de ese módulo exacto), se registra un sustituto mínimo que sigue la firma de
CONTRATOS.md §4; cualquier otro error de importación se propaga (no se enmascara un fallo real).
`SUSTITUTOS` dice cuáles se han sustituido, para declararlo en las evidencias.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import pathlib
import re
import sys
import types
import unicodedata

RAIZ = pathlib.Path(__file__).resolve().parents[1]
SANDBOX = RAIZ / "sandbox"
ESQUEMAS = RAIZ / "esquemas"
EJEMPLOS = ESQUEMAS / "ejemplos"
TARIFA = RAIZ / "tests" / "insumos" / "rate-card.sintetica.json"
_WINDOWS = pathlib.Path("C:/Users/usuario/Proyectos")  # solo como último recurso, si existe
_PROYECTOS = pathlib.Path((os.environ.get("PREVENTA_PROYECTOS") or "").strip() or pathlib.Path.home() / "Proyectos")
_PROYECTOS = _PROYECTOS if _PROYECTOS.is_dir() or not _WINDOWS.is_dir() or (os.environ.get("PREVENTA_PROYECTOS") or "").strip() else _WINDOWS  # fijada: se respeta
CANONICO = _PROYECTOS / "_templates" / "estimacion"
SUSTITUTOS: list[str] = []

if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))
if str(ESQUEMAS) not in sys.path:
    sys.path.insert(0, str(ESQUEMAS))


def _canonico(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _stub_errores() -> types.ModuleType:
    m = types.ModuleType("nucleo.errores")

    class ErrorPreventa(Exception):
        codigo_salida = 5

        def __init__(self, mensaje: str, errores: list[str] | None = None):
            super().__init__(mensaje)
            self.mensaje, self.errores = mensaje, list(errores or [])

    for nombre, rc in (("EntradaInvalida", 2), ("ReglaIncumplida", 1), ("Bloqueo", 1),
                       ("TransicionNoPermitida", 3), ("IntegridadRota", 4)):
        setattr(m, nombre, type(nombre, (ErrorPreventa,), {"codigo_salida": rc}))
    m.ErrorPreventa = ErrorPreventa
    return m


def _stub_esquema() -> types.ModuleType:
    import comprobar_esquemas  # referencia ejecutable de §12
    m = types.ModuleType("nucleo.esquema")
    m.cargar = lambda nombre, dir_esquemas=None: json.loads(
        ((dir_esquemas or ESQUEMAS) / f"{nombre}.json").read_text(encoding="utf-8"))
    m.validar = lambda inst, esq: comprobar_esquemas.validar(inst, esq, esq)
    return m


def _stub_hashes() -> types.ModuleType:
    m = types.ModuleType("nucleo.hashes")
    m.hash_contenido = lambda est: hashlib.sha256(_canonico(est["carga"])).hexdigest()
    return m


CASCADA = {"requisitos": ("respuestas_expertos", "consolidado", "verificacion", "anexo_consumo", "estimacion", "textos_cliente"),
           "respuestas_expertos": ("consolidado", "verificacion", "anexo_consumo", "estimacion", "textos_cliente"),
           "consolidado": ("anexo_consumo", "estimacion", "textos_cliente"),
           "verificacion": ("anexo_consumo", "estimacion", "textos_cliente"),
           "anexo_consumo": ("estimacion", "textos_cliente")}


def _stub_estado() -> types.ModuleType:
    m = types.ModuleType("nucleo.estado")

    def invalidar_desde(est: dict, bloque: str) -> list[str]:
        for k in CASCADA[bloque]:
            est["carga"][k] = {} if k == "respuestas_expertos" else None
        return list(CASCADA[bloque])
    m.invalidar_desde = invalidar_desde
    return m


def _stub_decision() -> types.ModuleType:
    m = types.ModuleType("nucleo.decision")

    def vigente(est: dict, tipo: str) -> dict | None:
        h = sys.modules["nucleo.hashes"].hash_contenido(est)
        ok = [d for d in est.get("decisiones") or [] if d.get("tipo") == tipo and d.get("hash_citado") == h]
        return ok[-1] if ok else None
    m.vigente = vigente
    return m


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


def _stub_textos() -> types.ModuleType:
    m = types.ModuleType("nucleo.textos_cliente")

    def marcadores(texto: str) -> list[str]:
        hall = re.findall(r"\b(TBD|TODO|XXX|PLACEHOLDER)\b", texto)
        hall += re.findall(r"\b(pendientes?|por definir|lorem)\b", _sin_tildes(texto))
        hall += re.findall(r"<[^<>\n]{1,60}>", texto)
        return hall
    m.marcadores = marcadores
    return m


DEPENDENCIAS = ("errores", "esquema", "hashes", "estado", "decision", "textos_cliente")
_FABRICAS = {"errores": _stub_errores, "esquema": _stub_esquema, "hashes": _stub_hashes,
             "estado": _stub_estado, "decision": _stub_decision, "textos_cliente": _stub_textos}
_INSTANTANEA: dict[str, types.ModuleType] = {}


def _es_nucleo(nombre: str) -> bool:
    return nombre == "nucleo" or nombre.startswith("nucleo.")


def preparar_nucleo() -> dict[str, types.ModuleType]:
    """Importa estimacion y anexo_consumo con sus dependencias (reales o sustitutos) y DEJA
    sys.modules y el paquete `nucleo` como estaban: los sustitutos no contaminan las pruebas de otros
    papeles. Durante cada prueba propia, `aislar` vuelve a montar esta misma instantánea."""
    if _INSTANTANEA:
        return dict(_INSTANTANEA)
    previos = {k: v for k, v in sys.modules.items() if _es_nucleo(k)}
    paquete_previo = sys.modules.get("nucleo")
    atributos = dict(vars(paquete_previo)) if paquete_previo is not None else None
    try:
        paquete = importlib.import_module("nucleo")
        for nombre in DEPENDENCIAS:
            completo = f"nucleo.{nombre}"
            try:
                importlib.import_module(completo)
            except ModuleNotFoundError as e:
                if e.name != completo:
                    raise
                sys.modules[completo] = _FABRICAS[nombre]()
                setattr(paquete, nombre, sys.modules[completo])
                SUSTITUTOS.append(nombre)
        for nombre in ("estimacion", "anexo_consumo"):
            importlib.import_module(f"nucleo.{nombre}")
        _INSTANTANEA["nucleo"] = paquete
        for nombre in DEPENDENCIAS + ("estimacion", "anexo_consumo"):
            _INSTANTANEA[nombre] = sys.modules[f"nucleo.{nombre}"]
    finally:
        for k in [k for k in sys.modules if _es_nucleo(k) and k not in previos]:
            del sys.modules[k]
        sys.modules.update(previos)
        if paquete_previo is not None and atributos is not None:
            for k in [k for k in vars(paquete_previo) if k not in atributos]:
                delattr(paquete_previo, k)
            for k, v in atributos.items():
                setattr(paquete_previo, k, v)
    return dict(_INSTANTANEA)


def aislar(monkeypatch) -> None:
    """Monta la instantánea de `preparar_nucleo` solo durante la prueba (monkeypatch la retira)."""
    paquete = _INSTANTANEA["nucleo"]
    monkeypatch.setitem(sys.modules, "nucleo", paquete)
    for nombre in DEPENDENCIAS + ("estimacion", "anexo_consumo"):
        monkeypatch.setitem(sys.modules, f"nucleo.{nombre}", _INSTANTANEA[nombre])
        monkeypatch.setattr(paquete, nombre, _INSTANTANEA[nombre], raising=False)


def ejemplo(nombre: str) -> object:
    """Copia de un ejemplo de esquemas/ejemplos (nunca se edita en su sitio)."""
    return copy.deepcopy(json.loads((EJEMPLOS / f"{nombre}.json").read_text(encoding="utf-8")))


def estado_base() -> dict:
    """Estado del ejemplo OF-KELVARA-001-A llevado a VERIFICADA con anexo y sin estimación."""
    est = ejemplo("estado")
    est["estado"] = "VERIFICADA"
    est["decisiones"] = []
    est["carga"]["estimacion"] = None
    est["carga"]["textos_cliente"] = None
    for k in ("xlsx_estimacion", "pptx", "docx", "zip"):
        est["artefactos"][k] = None
    return est


def sha256_fichero(ruta: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(ruta).read_bytes()).hexdigest()
