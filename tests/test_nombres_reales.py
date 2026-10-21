"""Lista local de nombres reales (tests/nombres_reales.py): formato, fallos en alto y que nunca se versiona."""
from __future__ import annotations

import subprocess
import unicodedata

import pytest

from tests import nombres_reales as nr


def _fichero(tmp_path, datos: bytes):
    ruta = tmp_path / "nombres.txt"
    ruta.write_bytes(datos)
    return ruta


def test_formato(tmp_path):
    # BOM, CRLF, comentarios (también sangrados), líneas vacías, espacios de más, mayúsculas, NFD y repetidos.
    bom, nfd = chr(0xFEFF), unicodedata.normalize("NFD", "ÑANDÚ")
    texto = f"{bom}# comentario\r\n\r\n  Alfa   Beta \r\n   # sangrado\r\n{nfd}-omega\r\nalfa beta\n"
    assert nr.cargar(_fichero(tmp_path, texto.encode("utf-8"))) == ("alfa beta", "ñandú-omega")
    assert nr.normalizar(nfd) == "ñandú"


def test_sin_fichero_se_omite_con_motivo(tmp_path):
    with pytest.raises(pytest.skip.Exception, match="NO COMPROBADO: falta .*nombres-reales"):
        nr.cargar(tmp_path / "nombres-reales.local.txt")


@pytest.mark.parametrize("datos,motivo", [
    (b"# solo comentarios\n\n", "ningún nombre"),
    (b"empresa-ejemplo-uno\nalfa\n", "ficticios"),
    (b"alfa\nbeta # nota\n", "línea 2"),
    ("Ñandú\n".encode("cp1252"), "decode"),
])
def test_fichero_inservible_falla(tmp_path, datos, motivo):
    with pytest.raises(pytest.fail.Exception, match=motivo):
        nr.cargar(_fichero(tmp_path, datos))


def test_la_plantilla_solo_trae_nombres_ficticios():
    nombres = nr._nombres(nr.PLANTILLA)
    assert nombres and all(n.startswith(nr.PREFIJO_FICTICIO) for n in nombres), nombres
    with pytest.raises(pytest.fail.Exception, match="ficticios"):
        nr.cargar(nr.PLANTILLA)   # copiarla sin cambiar los nombres no da verde


@pytest.mark.parametrize("ruta,ignorado", [
    ("config/nombres-reales.local.txt", True),
    ("config/nombres-reales.local.txt~", True),
    ("config/nombres-reales.local.txt.bak", True),
    ("config/nombres-reales.local.txt.ejemplo", False),
])
def test_la_lista_local_no_se_versiona_y_la_plantilla_si(ruta, ignorado):
    r = subprocess.run(["git", "check-ignore", "-q", ruta], cwd=nr.RAIZ)
    assert r.returncode == (0 if ignorado else 1), r.returncode
