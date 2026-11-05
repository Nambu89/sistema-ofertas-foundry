"""API de biblioteca del núcleo de preventa: una función por subcomando de preventa_run.py.

Cada función recibe la carpeta de trabajo (o un Entorno ya abierto) y devuelve un ResultadoNucleo.
Por dentro llama a la MISMA función de despacho que la CLI (preventa_run._despachar): mismas
transiciones, mismo guardado de estado.json, mismos códigos de salida (§11.1) y mismo texto
impreso, que se devuelve en `salida`. Documentación: docs/I1/API-NUCLEO.md.

No es reentrante: el texto se captura redirigiendo sys.stdout y el localizador de esquemas es
global del proceso, así que un cerrojo serializa las llamadas dentro del proceso.
"""
from __future__ import annotations

import contextlib
import copy
import dataclasses
import io
import os
import pathlib
import re
import sys
import threading
from typing import Iterable, Union

if str(pathlib.Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import preventa_run as _run  # noqa: E402

Entorno = _run.Entorno
_CERROJO = threading.RLock()
_SIGUIENTE = re.compile(r"^SIGUIENTE PASO OBLIGATORIO:\s*(.*)$", re.M)
Carpeta = Union[str, os.PathLike, Entorno]


@dataclasses.dataclass(frozen=True)
class ResultadoNucleo:
    """Resultado estructurado de un subcomando."""
    subcomando: str
    rc: int                       # 0 bien; 1 regla o pendiente; 2 entrada; 3 transición; 4 integridad; 5 inesperado
    estado: dict | None           # estado final (el que describe el bloque estado); copia independiente
    salida: str                   # todo lo que la CLI habría impreso, bloque estado incluido
    error: dict | None            # {"tipo", "mensaje", "errores"} si hubo error; None si no
    siguiente_paso: str | None    # línea «SIGUIENTE PASO OBLIGATORIO» del bloque estado

    @property
    def ok(self) -> bool:
        return self.rc == 0


def abrir(trabajo: str | os.PathLike | None = None, *, datos=None, app=None, tmp=None,
          montaje: str | None = None) -> Entorno:
    """Resuelve las carpetas y carga el núcleo. Montaje: argumento > PREVENTA_MONTAJE > «exacto» (sin file_ids).

    Lo no indicado sale de las variables PREVENTA_* y, si tampoco están, del valor por defecto del
    modo (local: datos = carpeta actual, trabajo = <datos>/preventa). Lanza la excepción del
    arranque si el núcleo no se puede cargar; un error de configuración sale en cada resultado (rc 2).
    """
    montaje = _run._normalizado(montaje) or _run._normalizado(os.environ.get("PREVENTA_MONTAJE")) or "exacto"
    with _CERROJO:
        env = Entorno.resolver(trabajo=None if trabajo is None else os.fspath(trabajo), datos=datos,
                               app=app, tmp=tmp, montaje=montaje)
        _run._nucleo(env)
        return env


def ejecutar(carpeta: Carpeta, argv: Iterable[str]) -> ResultadoNucleo:
    """Ejecuta un subcomando con argumentos de CLI ya formados (sin opciones de carpetas)."""
    argv = [str(a) for a in argv]
    with _CERROJO:
        env = carpeta if isinstance(carpeta, Entorno) else abrir(carpeta)
        _run._nucleo(env)  # vuelve a apuntar el localizador de esquemas a este entorno
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            d = _run._despachar(argv, env)
    salida = buf.getvalue()
    error = None
    if d.error is not None:
        error = {"tipo": type(d.error).__name__, "mensaje": getattr(d.error, "mensaje", None) or str(d.error),
                 "errores": [str(e) for e in (getattr(d.error, "errores", None) or [])]}
    pasos = _SIGUIENTE.findall(salida)
    return ResultadoNucleo(subcomando=argv[0] if argv else "", rc=d.rc, estado=copy.deepcopy(d.estado),
                           salida=salida, error=error, siguiente_paso=pasos[-1].strip() if pasos else None)


def _op(nombre: str, valor) -> str:
    return f"--{nombre}={valor}"  # forma «=»: un valor que empiece por «-» no se confunde con una opción


def entorno(carpeta: Carpeta) -> ResultadoNucleo:
    return ejecutar(carpeta, ["entorno"])


def iniciar(carpeta: Carpeta, *, cliente: str, codigo_cliente: str, seqof: str, titulo: str,
            transcripcion: str | None = None, sensibles: Iterable[str], nda_confirmado: bool = False,
            pilar: str | None = None, notas_comercial: str | None = None) -> ResultadoNucleo:
    argv = ["iniciar", _op("cliente", cliente), _op("codigo-cliente", codigo_cliente), _op("seqof", seqof),
            _op("titulo", titulo)]
    argv += [_op("transcripcion", transcripcion)] if transcripcion is not None else []
    argv += [_op("notas-comercial", notas_comercial)] if notas_comercial is not None else []   # nombre de adjunto
    argv += [_op("sensible", s) for s in sensibles]
    argv += [_op("pilar", pilar)] if pilar is not None else []   # multinube: la CLI lo valida (lista blanca, rc 2)
    return ejecutar(carpeta, argv + (["--nda-confirmado"] if nda_confirmado else []))


def suficiencia(carpeta: Carpeta, *, requisitos: str, aclaraciones: Iterable[str] = ()) -> ResultadoNucleo:
    return ejecutar(carpeta, ["suficiencia", _op("requisitos", requisitos)] + [_op("aclaracion", a) for a in aclaraciones])


def asumir(carpeta: Carpeta, *, campo: str, valor: str) -> ResultadoNucleo:
    return ejecutar(carpeta, ["asumir", _op("campo", campo), _op("valor", valor)])


def enrutar(carpeta: Carpeta) -> ResultadoNucleo:
    return ejecutar(carpeta, ["enrutar"])


def registrar_experto(carpeta: Carpeta, *, respuesta: str, experto: str = "azure") -> ResultadoNucleo:
    return ejecutar(carpeta, ["registrar-experto", _op("experto", experto), _op("respuesta", respuesta)])


def registrar_fallo(carpeta: Carpeta, *, fase: str, error: str, hipotesis: str) -> ResultadoNucleo:
    return ejecutar(carpeta, ["registrar-fallo", _op("fase", fase), _op("error", error), _op("hipotesis", hipotesis)])


def consolidar(carpeta: Carpeta, *, lotes: bool = False) -> ResultadoNucleo:
    """Con lotes=True imprime los lotes pendientes (I1.1, LES-G-096); sin él, el consolidado completo."""
    return ejecutar(carpeta, ["consolidar", "--lotes"] if lotes else ["consolidar"])


def registrar_verificacion(carpeta: Carpeta, *, respuesta: str) -> ResultadoNucleo:
    return ejecutar(carpeta, ["registrar-verificacion", _op("respuesta", respuesta)])


def anexo_consumo(carpeta: Carpeta) -> ResultadoNucleo:
    return ejecutar(carpeta, ["anexo-consumo"])


def estimar(carpeta: Carpeta, *, aplicar_ajuste: str | None = None) -> ResultadoNucleo:
    """El núcleo compone la entrada desde tareas_propuestas (decisión del 10-10-2026; REV-1: sin forma heredada)."""
    return ejecutar(carpeta, ["estimar"] + ([_op("aplicar-ajuste", aplicar_ajuste)] if aplicar_ajuste is not None else []))


def paquete(carpeta: Carpeta) -> ResultadoNucleo:
    return ejecutar(carpeta, ["paquete"])


def decision(carpeta: Carpeta, *, linea: str) -> ResultadoNucleo:
    return ejecutar(carpeta, ["decision", _op("linea", linea)])


def estado(carpeta: Carpeta, *, como_json: bool = False, turno_nuevo: bool = False) -> ResultadoNucleo:
    """`turno_nuevo` (EA-1): primera orden de un turno; el SIGUIENTE PASO dice lo que toca ahora."""
    return ejecutar(carpeta, ["estado"] + (["--json"] if como_json else []) + (["--turno-nuevo"] if turno_nuevo else []))


def restaurar(carpeta: Carpeta, *, estado: str | None = None, manifiesto: str | None = None,
              zip: str | None = None, relevo: str | None = None) -> ResultadoNucleo:  # noqa: A002
    """Tres formas excluyentes: zip= (Paquete o Relevo, preferida desde I1.1), estado= y relevo= (los JSON del relevo
    sueltos, EA-5) o estado= y manifiesto= (forma antigua)."""
    if zip is not None:
        if estado is not None or manifiesto is not None or relevo is not None:
            raise ValueError("restaurar: zip= excluye estado=, manifiesto= y relevo=")
        return ejecutar(carpeta, ["restaurar", _op("zip", zip)])
    if estado is None or (manifiesto is None) == (relevo is None):
        raise ValueError("restaurar: hace falta zip=, o estado= con relevo= o con manifiesto= (uno de los dos)")
    if relevo is not None:
        return ejecutar(carpeta, ["restaurar", _op("estado", estado), _op("relevo", relevo)])
    return ejecutar(carpeta, ["restaurar", _op("estado", estado), _op("manifiesto", manifiesto)])


def catalogo_montado(carpeta: Carpeta) -> dict:
    """I1.9 (PR18-1): el catálogo de componentes montado en el entorno (solo lectura; no es un subcomando). B lo usa
    para dar al modelo de la extracción los ids de servicio_catalogo. Lanza la excepción si no se puede leer."""
    with _CERROJO:
        env = carpeta if isinstance(carpeta, Entorno) else abrir(carpeta)
        est = _run.estado.cargar(env.raiz) if _run.estado.existe(env.raiz) else None   # multinube: el del pilar
        return _run._catalogo(env, est)[0]


SUBCOMANDOS = {
    "entorno": entorno, "iniciar": iniciar, "suficiencia": suficiencia, "asumir": asumir, "enrutar": enrutar,
    "registrar-experto": registrar_experto, "registrar-fallo": registrar_fallo, "consolidar": consolidar,
    "registrar-verificacion": registrar_verificacion, "anexo-consumo": anexo_consumo, "estimar": estimar,
    "paquete": paquete, "decision": decision, "estado": estado, "restaurar": restaurar,
}
