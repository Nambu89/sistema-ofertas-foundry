"""Omite con motivo explícito una prueba que necesita evidencias o activos que no se publican."""
from __future__ import annotations

import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def requerir(*rutas: pathlib.Path, activo: bool = False) -> None:
    """OMITE la prueba si falta alguna ruta (las evidencias de `pruebas/` o un activo privado), nombrándola."""
    for r in rutas:
        if not r.exists():
            try:
                rel = r.resolve().relative_to(RAIZ).as_posix()
            except ValueError:
                rel = str(r)
            pytest.skip(f"{'ACTIVO PRIVADO' if activo else 'EVIDENCIA NO PUBLICADA (requiere evidencias privadas no publicadas)'}: necesita {rel}")
