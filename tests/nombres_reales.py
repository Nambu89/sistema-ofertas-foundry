"""Nombres reales de clientes para las comprobaciones de las pruebas, leídos de un fichero LOCAL.

Esa lista revela relaciones comerciales y no puede estar en el repositorio (regla 4 del README): vive
en `config/nombres-reales.local.txt`, que git ignora. La plantilla versionada
`config/nombres-reales.local.txt.ejemplo` explica el formato y solo lleva nombres ficticios.

Formato: UTF-8, un nombre por línea; se ignoran las líneas vacías y las que empiezan por «#». Los
nombres y los textos en los que se buscan pasan por la misma normalización (`normalizar`).

Nada pasa en silencio:
- si el fichero no existe, la prueba se OMITE con un motivo explícito que sale en el resumen;
- si existe pero no trae ningún nombre, conserva los ficticios de la plantilla, lleva un comentario
  detrás de un nombre o no es UTF-8, la prueba FALLA.
"""
from __future__ import annotations

import pathlib
import unicodedata

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
RUTA = RAIZ / "config" / "nombres-reales.local.txt"
PLANTILLA = RAIZ / "config" / "nombres-reales.local.txt.ejemplo"
PREFIJO_FICTICIO = "empresa-ejemplo-"


def normalizar(texto: str) -> str:
    """NFC y sin mayúsculas: la misma función para los nombres y para el texto en el que se buscan."""
    return unicodedata.normalize("NFC", texto).casefold()


def _nombres(ruta: pathlib.Path) -> tuple[str, ...]:
    """Nombres normalizados, sin duplicados y en el orden del fichero, sin validar la lista."""
    nombres: dict[str, None] = {}
    for n, linea in enumerate(ruta.read_text(encoding="utf-8-sig").splitlines(), 1):
        limpia = " ".join(linea.split())
        if not limpia or limpia.startswith("#"):
            continue
        if "#" in limpia:   # «nombre  # nota» dejaría de buscar el nombre sin avisar
            raise ValueError(f"línea {n}: «#» detrás de un nombre; los comentarios van en línea propia")
        nombres.setdefault(normalizar(limpia), None)
    return tuple(nombres)


def leer(ruta: pathlib.Path) -> tuple[str, ...]:
    """Nombres de la lista. FileNotFoundError si no existe; ValueError si no sirve como lista."""
    nombres = _nombres(ruta)
    if not nombres:
        raise ValueError("no trae ningún nombre")
    ficticios = [x for x in nombres if x.startswith(PREFIJO_FICTICIO)]
    if ficticios:
        raise ValueError(f"conserva nombres ficticios de la plantilla ({', '.join(ficticios)}); "
                         "sustitúyelos por los reales")
    return nombres


def _mostrar(ruta: pathlib.Path) -> str:
    try:
        return ruta.relative_to(RAIZ).as_posix()
    except ValueError:
        return str(ruta)


def cargar(ruta: pathlib.Path | None = None) -> tuple[str, ...]:
    """Nombres para una prueba: la OMITE si falta el fichero local y la hace FALLAR si no sirve."""
    __tracebackhide__ = True   # el resumen de pytest señala la prueba que llama, no este módulo
    ruta = RUTA if ruta is None else ruta
    try:
        return leer(ruta)
    except FileNotFoundError:
        pytest.skip(f"NO COMPROBADO: falta {_mostrar(ruta)}, la lista local y no versionada de nombres "
                    f"reales de clientes. Créala a partir de {_mostrar(PLANTILLA)}.")
    except ValueError as e:   # incluye UnicodeDecodeError: un fichero que no es UTF-8
        pytest.fail(f"{_mostrar(ruta)}: {e}", pytrace=False)
