"""Integrador I1.7: el esquema del catálogo del sandbox es EXACTAMENTE el que propuso E (CAMBIOS-I17-E §3.1) y la copia
del sandbox es la derivada (byte a byte). Sustituye a la comprobación de I1.6 en test_i16_e_derivado_e_instrucciones.py."""
from __future__ import annotations

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def test_esquema_vigente_es_el_propuesto_por_e_en_i17():
    """Arreglos I1.7: el vigente es el propuesto por E más las adiciones documentadas (tests/i17_arr_comun.py), y nada
    más: sin ellas, es igual al propuesto."""
    import json
    from tests.i17_arr_comun import sin_arreglos
    from tests.i18_e_comun import sin_i18_e  # integrador I1.8: y sin las adiciones de E de I1.8 (CAMBIOS-I18-E §3.5)
    from tests.i19_e_comun import sin_i19_e  # integrador I1.9: y sin las de E de I1.9 (CAMBIOS-I19-E §3.5)
    vigente = json.loads((RAIZ / "esquemas" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    propuesto = json.loads((RAIZ / "docs" / "I1" / "CAMBIOS-I17-E" / "catalogo_componentes.propuesto.json")
                           .read_text(encoding="utf-8"))
    assert vigente != propuesto and sin_arreglos(sin_i18_e(sin_i19_e(vigente))) == propuesto


def test_catalogo_del_sandbox_es_el_derivado_y_su_instantanea_la_del_catalogo():
    for nombre in ("catalogo_componentes.json", "precios_instantanea.json"):
        assert (RAIZ / "sandbox" / "datos" / nombre).read_bytes() == (RAIZ / "catalogo" / nombre).read_bytes(), nombre
