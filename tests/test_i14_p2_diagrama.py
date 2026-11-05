"""I1.4 · P2 · ARR13-2: la altura de las columnas sale de su número de componentes, las bandas van debajo
de la columna más alta y ninguna forma de componente se solapa con otra ni la tapa una banda. Sin red."""
from __future__ import annotations

import pathlib
import random
import sys

import pytest
from pptx import Presentation
from pptx.util import Emu

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import pptx_revision as pr  # noqa: E402

C, B = pr.PREFIJO_COMPONENTE, pr.PREFIJO_BANDA


def _comps(por_capa: dict[str, int]) -> list[dict]:
    salida, n = [], 0
    for capa, k in por_capa.items():
        for _ in range(k):
            n += 1
            salida.append({"id": f"C-{n:02d}", "nombre": f"Servicio de prueba {n}", "capa": capa})
    return salida


def _dibujar(comps: list[dict], alto: int):
    prs = Presentation()
    prs.slide_width, prs.slide_height = pr.ANCHO, pr.ALTO
    diapo = prs.slides.add_slide(prs.slide_layouts[6])
    dib = pr.dibujar_diagrama(diapo, comps, [], pr.MARGEN, Emu(1200000), pr.ANCHO_UTIL, Emu(alto))
    return diapo, dib


def test_solapes_casos_basicos():
    banda = (B + "Identidad, seguridad y red", "", 0, 1000, 5000, 500)
    dentro = (C + "2", "Entra", 100, 1100, 1000, 300)
    assert pr.solapes_diagrama([banda, dentro]) == []                                  # dentro y encima
    assert pr.solapes_diagrama([dentro, banda])                                        # dentro pero debajo
    tapado = (C + "1", "Blob", 0, 800, 1000, 400)                                      # asoma por arriba
    assert any("Blob" in f for f in pr.solapes_diagrama([tapado, banda]))
    assert any("Blob" in f for f in pr.solapes_diagrama([banda, tapado]))              # encima, pero sobresale
    otro = (C + "3", "Search", 500, 900, 1000, 200)
    assert any("se solapa" in f for f in pr.solapes_diagrama([tapado, otro]))
    contiguo = (C + "4", "Cosmos", 1000, 800, 1000, 200)                               # borde con borde
    assert pr.solapes_diagrama([tapado, contiguo]) == []
    assert pr.solapes_diagrama([(C + "5", "X", 0, 0, 0, 10)])                          # tamaño nulo
    assert pr.solapes_diagrama([(C + "5", "X", 0, 0, 1.5, 10)])                        # no entero
    titulo = ("CuadroTexto 9", "Identidad, seguridad y red", 0, 1000, 100, 100)
    assert any("sin forma" in f for f in pr.solapes_diagrama([titulo, tapado]))        # banda sin nombre
    otra_banda = (B + "Operación y observabilidad", "", 0, 1400, 5000, 500)          # pisa a la primera
    assert any("se solapa con la banda" in f for f in pr.solapes_diagrama([banda, otra_banda]))


@pytest.mark.parametrize("por_capa", [
    {"usuarios_canales": 3, "aplicacion_integracion": 3, "ia": 3, "datos_conocimiento": 3,
     "identidad_seguridad_red": 3, "operacion_observabilidad": 3},
    {"datos_conocimiento": 3, "identidad_seguridad_red": 1},                           # el caso de ARR13-2
    {"usuarios_canales": 5, "aplicacion_integracion": 5, "ia": 5, "datos_conocimiento": 5,
     "identidad_seguridad_red": 6, "operacion_observabilidad": 6},
    {"identidad_seguridad_red": 2},                                                    # solo bandas
])
def test_bandas_debajo_de_la_columna_mas_alta_y_sin_solapes(por_capa):
    comps = _comps(por_capa)
    diapo, dib = _dibujar(comps, 3470000)  # el alto que deja un pie de ocho líneas de referencias
    assert pr.comprobar_dibujo(dib, comps, []) == []
    assert pr.solapes_diagrama(pr.formas_de(diapo)) == []
    columnas = [f for c, f in dib["formas"].items() if next(k for k in comps if k["id"] == c)["capa"]
                in pr.CAPAS_COLUMNA]
    techo_bandas = min((b.top for b in dib["bandas"]), default=None)
    if columnas and techo_bandas is not None:
        assert max(f.top + f.height for f in columnas) < techo_bandas
    assert dib["fondo"] <= dib["limite"][1] + dib["limite"][3]


def test_regresion_arr13_2_con_el_alto_reservado_antiguo():
    """Con el hueco que dejaba el pie antiguo (seis referencias largas), el tercer componente de «Datos y
    conocimiento» quedaba bajo la banda. Ahora la banda baja con la columna."""
    comps = _comps({"usuarios_canales": 2, "aplicacion_integracion": 2, "ia": 2, "datos_conocimiento": 3,
                    "identidad_seguridad_red": 1})
    diapo, dib = _dibujar(comps, 2628000)
    assert pr.comprobar_dibujo(dib, comps, []) == []
    blob = dib["formas"]["C-09"]
    assert blob.top + blob.height < dib["bandas"][0].top


def test_si_no_cabe_ni_con_las_minimas_lo_declara_y_cae_a_la_tabla():
    comps = _comps({"ia": 5, "identidad_seguridad_red": 1, "operacion_observabilidad": 1})
    _, dib = _dibujar(comps, 2000000)
    assert dib["cabe"] is False
    assert any("no cabe" in f for f in pr.comprobar_dibujo(dib, comps, []))


def test_medidas_diagrama_comprime_lo_justo():
    m, cabe = pr.medidas_diagrama(3, 1, 10 ** 7)
    assert cabe and m == pr.MEDIDAS_BASE
    base = pr.alto_necesario(5, 2, pr.MEDIDAS_BASE)
    minimo = pr.alto_necesario(5, 2, pr.MEDIDAS_MIN)
    for alto in range(minimo, base, 37011):
        m, cabe = pr.medidas_diagrama(5, 2, alto)
        assert cabe and pr.alto_necesario(5, 2, m) <= alto
        assert all(pr.MEDIDAS_MIN[k] <= m[k] <= pr.MEDIDAS_BASE[k] for k in m)
    assert pr.medidas_diagrama(5, 2, minimo - 1)[1] is False


def test_comprobar_dibujo_detecta_una_banda_encima_de_un_componente():
    comps = _comps({"datos_conocimiento": 3, "identidad_seguridad_red": 1})
    diapo, dib = _dibujar(comps, 3000000)
    dib["formas"]["C-03"].top = dib["bandas"][0].top - Emu(100000)  # lo que pasaba en ARR13-2
    assert any("tapa o corta" in f for f in pr.comprobar_dibujo(dib, comps, []))


def test_aleatoria_sin_solapes_y_con_casos_que_caen_a_la_tabla():
    """LES-G-099.5: exige casos de los dos lados, no un verde vacío."""
    azar, dibujados, no_caben = random.Random(1404), 0, 0
    for _ in range(120):
        por_capa = {c: azar.randint(0, 5) for c in pr.CAPAS_COLUMNA}
        por_capa.update({c: azar.randint(0, 6) for c in pr.CAPAS_BANDA})
        comps = _comps({k: v for k, v in por_capa.items() if v}) or _comps({"ia": 1})
        diapo, dib = _dibujar(comps, azar.randint(1800000, 4200000))
        fallos = pr.comprobar_dibujo(dib, comps, [])
        if dib["cabe"]:
            assert fallos == [] and pr.solapes_diagrama(pr.formas_de(diapo)) == []
            dibujados += 1
        else:
            assert fallos
            no_caben += 1
    assert dibujados >= 30 and no_caben >= 5, (dibujados, no_caben)
