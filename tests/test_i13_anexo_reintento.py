"""I1.3, previo (REVPR-3): la reversión de anexo_consumo.aplicar con el reintento de estado._reemplazar (ARRSN-1).

Las pruebas de reversión de test_i1_estimacion_anexo.py simulan OSError, que no se reintenta; estas simulan el
PermissionError de Windows: uno pasajero se recupera y uno persistente agota los reintentos y restaura el JSON (la
restauración, denegada una vez, también se reintenta: segunda pasada de la revisión independiente).
"""
from __future__ import annotations

import copy
import json
import os
import sys
import zipfile

import pytest

from tests.test_i1_estimacion_comun import EJEMPLOS, aislar, estado_base, preparar_nucleo

M = preparar_nucleo()
A = M["anexo_consumo"]
RJ, RX = "OF-KELVARA-001-A-Anexo-Consumo.json", "OF-KELVARA-001-A-Anexo-Consumo.xlsx"


@pytest.fixture()
def estado_win(monkeypatch):
    """Instantánea del núcleo montada y el estado que usa el anexo en «modo Windows», sin esperas."""
    aislar(monkeypatch)
    E = sys.modules["nucleo.estado"]
    monkeypatch.setattr(E, "ES_WINDOWS", True)
    monkeypatch.setattr(E.time, "sleep", lambda s: None)
    monkeypatch.setattr(E, "REINTENTOS_REPLACE", [])
    return E


def _replace_xlsx_denegado(veces: int, llamadas: list, restauraciones: list | None = None):
    """Deniega `veces` la sustitución del XLSX; con `restauraciones`, deniega además una vez la restauración del JSON."""
    real = os.replace

    def falso(origen, destino):
        if str(destino).endswith(RX):
            llamadas.append(destino)
            if len(llamadas) <= veces:
                raise PermissionError(13, "Acceso denegado (WinError 5, simulado)")
        if restauraciones is not None and str(origen).endswith(".anterior") and str(destino).endswith(RJ):
            restauraciones.append(origen)
            if len(restauraciones) == 1:
                raise PermissionError(13, "Acceso denegado al restaurar (WinError 5, simulado)")
        return real(origen, destino)
    return falso


def test_permission_error_pasajero_al_sustituir_el_xlsx_se_recupera(estado_win, monkeypatch, tmp_path, capsys):
    catalogo = A.cargar_catalogo(EJEMPLOS / "catalogo_componentes.json")
    salida, llamadas = tmp_path / "salida", []
    monkeypatch.setattr(os, "replace", _replace_xlsx_denegado(2, llamadas))
    A.aplicar(estado_base(), catalogo, salida)
    assert sorted(p.name for p in salida.iterdir()) == [RJ, RX] and len(llamadas) == 3
    assert len(estado_win.REINTENTOS_REPLACE) == 2 and capsys.readouterr().err.count("AVISO: os.replace") == 2
    assert json.loads((salida / RJ).read_text(encoding="utf-8"))["codigo"] == "OF-KELVARA-001-A"
    assert zipfile.is_zipfile(salida / RX) and "xl/workbook.xml" in zipfile.ZipFile(salida / RX).namelist()


def test_permission_error_persistente_agota_los_reintentos_y_restaura_el_json(estado_win, monkeypatch, tmp_path):
    catalogo = A.cargar_catalogo(EJEMPLOS / "catalogo_componentes.json")
    salida, llamadas, restauraciones = tmp_path / "salida", [], []
    A.aplicar(estado_base(), catalogo, salida)
    (salida / RJ).write_text('{"previo": true}', encoding="utf-8")
    est = estado_base()
    antes = copy.deepcopy(est)
    monkeypatch.setattr(os, "replace", _replace_xlsx_denegado(99, llamadas, restauraciones))
    with pytest.raises(PermissionError) as e:
        A.aplicar(est, catalogo, salida)
    assert len(llamadas) == 6 and any("6 veces seguidas" in n for n in getattr(e.value, "__notes__", []))
    assert len(restauraciones) == 2  # la restauración también se reintenta: denegada una vez y hecha a la segunda
    assert sum(".anterior" in n for n in estado_win.REINTENTOS_REPLACE) == 0  # la nota cita el destino, el JSON
    assert sum(n.startswith(f"os.replace denegado sobre {salida / RJ}") for n in estado_win.REINTENTOS_REPLACE) == 1
    assert (salida / RJ).read_text(encoding="utf-8") == '{"previo": true}' and est == antes
    assert sorted(p.name for p in salida.iterdir()) == [RJ, RX]  # sin provisionales ni copia .anterior
