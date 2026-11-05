"""Propuesta del papel V para el integrador: CLI con lotes (`consolidar --lotes`, registro parcial) y la puerta
(`verificar_paquete`) recomponiendo el consolidado y sus lotes en local y recalculando la combinación
(LES-G-096, LES-G-097). Requiere los parches 09, 11 y 12 de docs/I1/CAMBIOS-I11-V/."""
from __future__ import annotations

import copy
import json
import types

import pytest

from tests.test_i1_estado_comun import RAIZ, Mundo
from tests.test_i1_verificacion_lotes import _cons, _registrar, _resp

import verificar_paquete as vp

# El mismo catálogo que monta Mundo (el del ejemplo): desde CMP-1 (I1.3) la residencia por tenant y la región de
# precio del catálogo real cambian las líneas, así que la recomposición se hace con el catálogo que se usó.
CATALOGO = json.loads((RAIZ / "esquemas" / "ejemplos" / "catalogo_componentes.json").read_text(encoding="utf-8"))


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def _ctx(est: dict):
    return types.SimpleNamespace(estado=est, carga=est["carga"], catalogo_obj=CATALOGO,
                                 respuesta=est["carga"]["respuestas_expertos"]["azure"]["respuesta"])


def _recompuesto(est: dict):
    c = vp.Comprobacion("recomposicion", "prueba")
    vp._recomponer_consolidado(_ctx(est), c)
    return c


def _por_lotes(m) -> dict:
    m.hasta_verificacion()
    for n, x in enumerate(_cons(m)["lotes"], start=1):
        _registrar(m, _resp(x["lote_id"], x["texto"], x["ids"]), f"l{n}.json")
    return m.estado()


def test_cli_consolidar_lotes_y_registro_parcial(m):
    m.hasta_verificacion()
    rc, out = m.run("consolidar", "--lotes")
    lotes = _cons(m)["lotes"]
    assert rc == 0 and out.count("=== LOTE ") == len(lotes) and "=== CONSOLIDADO PARA" not in out, out
    for n, x in enumerate(lotes, start=1):
        rc, out = _registrar(m, _resp(x["lote_id"], x["texto"], x["ids"]), f"l{n}.json")
        if n < len(lotes):
            assert rc == 0 and f"LOTE {x['lote_id']} registrado. Faltan {len(lotes) - n}" in out, out
            rc2, out2 = m.run("consolidar", "--lotes")
            assert rc2 == 0 and out2.count("=== LOTE ") == len(lotes) - n
    assert rc == 0 and "estado: VERIFICADA" in out, out


def test_puerta_acepta_lotes_recompuestos(m):
    est = _por_lotes(m)
    c = vp.c_verificacion(_ctx(est))
    assert c.estado != vp.FALLA, c.__dict__
    r = _recompuesto(est)
    assert r.estado != vp.FALLA, r.__dict__
    assert vp.nombre_esquema_verificador(est["carga"]) == "respuesta_verificador"


def test_puerta_detecta_combinacion_falsa(m):
    est = _por_lotes(m)
    roto = copy.deepcopy(est)
    roto["carga"]["consolidado"]["lotes"][0]["respuesta"]["elementos"][0]["veredicto"] = "NO VERIFICABLE"
    assert vp.c_verificacion(_ctx(roto)).estado == vp.FALLA


def test_puerta_detecta_linea_cambiada_y_resellada_en_consolidado_y_lote(m):
    """Lo que haría el modelo (LES-G-097.4): cambiar la línea en el consolidado y en su lote y volver a
    calcular las huellas. Solo la recomposición local desde la respuesta del experto lo detecta."""
    est = _por_lotes(m)
    roto = copy.deepcopy(est)
    cons = roto["carga"]["consolidado"]
    # integrador I1.7: sin líneas de precios ni lote de precios; se cambia la región de la primera línea de componente
    cons["texto"] = cons["texto"].replace("| region: ", "| region: x", 1)
    cons["sha256"] = vp.sha256_bytes(cons["texto"].encode("utf-8"))
    lote = next(x for x in cons["lotes"] if x["tipo"] == "componentes")
    lote["texto"] = lote["texto"].replace("| region: ", "| region: x", 1)
    lote["sha256"] = vp.sha256_bytes(lote["texto"].encode("utf-8"))
    assert vp.c_verificacion(_ctx(roto)).estado != vp.FALLA  # la coherencia interna no lo ve
    assert _recompuesto(roto).estado == vp.FALLA


def test_puerta_rechaza_discrepa_sin_fuente_o_con_fuente_ajena(m):
    m.hasta_verificacion()
    c = _cons(m)
    _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"]))
    est = m.estado()
    for fuente in (None, "https://learn.microsoft.com/answers/questions/1"):
        roto = copy.deepcopy(est)
        roto["carga"]["verificacion"]["respuesta"]["elementos"][0].update(
            {"veredicto": "DISCREPA", "valor_correcto": "https://learn.microsoft.com/azure/architecture", "fuente_url": fuente})
        assert vp.c_verificacion(_ctx(roto)).estado == vp.FALLA


def test_version_a_solo_con_las_dos_marcas(m):
    est = _por_lotes(m)
    carga = copy.deepcopy(est["carga"])
    carga["verificacion"]["respuesta"]["herramientas_usadas"].pop("precios_azure", None)  # I1.7: ya no lo lleva
    assert vp.nombre_esquema_verificador(carga) == "respuesta_verificador"  # sigue teniendo «lotes»
    del carga["consolidado"]["lotes"]
    assert vp.nombre_esquema_verificador(carga) == "historico/respuesta_verificador_v1"


def test_version_a_exige_herramientas_como_objeto(m):
    est = _por_lotes(m)
    carga = copy.deepcopy(est["carga"])
    del carga["consolidado"]["lotes"]
    carga["verificacion"]["respuesta"]["herramientas_usadas"] = None
    assert vp.nombre_esquema_verificador(carga) == "respuesta_verificador"


def test_lista_blanca_de_la_puerta_igual_que_la_del_nucleo():
    import sys
    sys.path.insert(0, str(RAIZ / "sandbox"))
    from nucleo import experto
    assert set(vp.PREF_ARQ + vp.PREF_SERV) == set(experto.PREFIJOS_REFERENCIA)
    assert vp.PREF_ARQ == experto.PREFIJOS_ARQUITECTURA


def test_consolidado_del_ejemplo_igual_que_el_del_nucleo(m):
    """El generador de ejemplos replica la composición y los lotes; tienen que coincidir con el núcleo."""
    from tests.test_i1_estado_comun import ejemplo
    m.hasta_verificacion()
    assert ejemplo("estado")["carga"]["consolidado"] == _cons(m)


def test_forma_de_version_a_fabricada_no_salta_la_recomposicion(m):
    """Integración I1.1 (Revisión): quitar «lotes» y «precios_azure» y resellar no exime de recomponer el
    consolidado: la forma de la versión A da FALLA en la recomposición, y además con una línea alterada."""
    est = _por_lotes(m)
    roto = copy.deepcopy(est)
    del roto["carga"]["consolidado"]["lotes"]
    roto["carga"]["verificacion"]["respuesta"]["herramientas_usadas"].pop("precios_azure", None)  # I1.7: ya no lo lleva
    # I1.7: sin líneas de precios en el consolidado; se altera la región de una línea de componente
    roto["carga"]["consolidado"]["texto"] = roto["carga"]["consolidado"]["texto"].replace("| region: ", "| region: x", 1)
    r = _recompuesto(roto)
    assert r.estado == vp.FALLA and any("forma de la versión A" in d for d in r.detalles), r.__dict__
