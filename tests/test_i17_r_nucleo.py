"""I1.7 · Papel R · núcleo: verificación sin lote de precios, PR16-6 (lo ya aceptado no se reenvía ni bloquea) y la
línea de precios conservados del brief. Con el núcleo real en proceso (Mundo con el catálogo real de
tests/test_i13_convergencia.py) y con funciones puras. Casos adversos con su resultado esperado (LES-G-096.6). Sin red."""
from __future__ import annotations

import copy

from tests.test_i13_convergencia import OTRA, ejemplo, m  # noqa: F401  (fixture del mundo con el catálogo real)
from tests.test_i1_verificacion_lotes import _cons, _registrar, _resp

from nucleo import brief, verificacion  # noqa: E402

DISCREPA_C02 = {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": OTRA}}
R1 = {**DISCREPA_C02, "REF-01": {"veredicto": "OBSERVACION", "campo": "titulo"},
      "C-05": {"veredicto": "NO VERIFICABLE", "detalle": "La herramienta no devolvió nada."}}


def _lineas(c: dict) -> dict[str, str]:
    return verificacion._lineas(c)


def _ronda(m, cambios: dict, respuesta=None):  # noqa: F811
    """Registra la verificación del consolidado vigente (completa) con `cambios`, enruta y registra la respuesta del
    experto de la ronda siguiente (la misma del ejemplo salvo `respuesta`) y consolida. Devuelve el brief nuevo."""
    c = _cons(m)
    rc, out = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"], cambios), "v_full.json")
    assert rc == 1, out
    assert m.run("enrutar")[0] == 0
    b = m.estado()["carga"]["briefs"][-1]
    r = copy.deepcopy(respuesta or ejemplo("respuesta_experto"))
    r["brief_recibido"], r["brief_id"] = b["texto"], b["brief_id"]
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada(f"e{b['ronda']}.json", r))
    assert rc == 0, out
    assert m.run("consolidar")[0] == 0
    return b


# --- (a) sin lote de precios ---

def test_consolidado_y_lotes_sin_precios(m):  # noqa: F811
    m.hasta_verificacion()
    c = _cons(m)
    assert not [ln for ln in c["texto"].split("\n") if ln.startswith("P-")] and "## Precios" not in c["texto"]
    assert c["ids"] and all(i.split("-")[0] in ("REF", "C") for i in c["ids"])
    assert {x["tipo"] for x in c["lotes"]} <= {"referencias", "componentes"}
    assert [i for x in c["lotes"] for i in x["ids"]] == c["ids"]           # ronda 1: se envía todo
    assert set(verificacion.LOTE_MAX) == {"REF", "C"}


def test_tamano_de_los_lotes_sin_precios():
    por_tipo = {"REF": [f"REF-{i:02d} | x{i}" for i in range(1, 16)], "C": [f"C-{i:02d} | y{i}" for i in range(1, 21)]}
    lotes = verificacion._lotes("CNS-OF-KELVARA-001-A-R1", ["brief_id: B"], por_tipo)
    assert [len(x.ids) for x in lotes] == [4, 4, 4, 3, 5, 5, 5, 5]


def test_herramientas_combinadas_sin_precios_y_mezcla_falla():
    a = {"herramientas_usadas": {"microsoft_docs_search": 2, "microsoft_docs_fetch": 1}}
    b = {"herramientas_usadas": {"microsoft_docs_search": 1, "microsoft_docs_fetch": 3}}
    assert verificacion.herramientas_combinadas([a, b]) == {"microsoft_docs_search": 2, "microsoft_docs_fetch": 3}
    c = {"herramientas_usadas": {"microsoft_docs_search": 1, "microsoft_docs_fetch": 3, "precios_azure": 0}}
    try:
        verificacion.herramientas_combinadas([a, c])
    except verificacion.IntegridadRota:
        pass
    else:
        raise AssertionError("lotes con herramientas distintas tienen que dar IntegridadRota")


# --- (b) PR16-6 ---

def test_r2_hereda_lo_aceptado_y_solo_envia_lo_nuevo_o_no_aceptado(m):  # noqa: F811
    m.hasta_verificacion()
    lineas_r1 = _lineas(_cons(m))
    b = _ronda(m, R1)
    acept = {a["linea"]: a for a in b["aceptados"]}
    esperados = {verificacion.contenido_linea(ln) for i, ln in lineas_r1.items() if i not in ("C-02", "C-05")}
    assert set(acept) == esperados and all(a["ronda"] == 1 for a in acept.values())
    assert acept[verificacion.contenido_linea(lineas_r1["REF-01"])]["veredicto"] == "OBSERVACION"
    c = _cons(m)
    assert verificacion.ids_en_lotes(c) == ["C-02", "C-05"]                 # la DISCREPA y el NO VERIFICABLE
    assert c["ids"] == list(lineas_r1)                                       # el consolidado sigue entero
    lote = c["lotes"][0]
    rc, out = _registrar(m, _resp(lote["lote_id"], lote["texto"], lote["ids"]), "l1.json")
    assert rc == 0 and "estado: VERIFICADA" in out, out
    ver = m.estado()["carga"]["verificacion"]
    assert [e["id"] for e in ver["respuesta"]["elementos"]] == ["C-02", "C-05"]


def test_r2_objecion_sobre_un_aceptado_sin_cambios_pasa_a_observacion(m):  # noqa: F811
    m.hasta_verificacion()
    _ronda(m, R1)
    c = _cons(m)
    otra = {"C-03": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "S1", "fuente_url": OTRA}}
    rc, out = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"], otra), "v2.json")
    assert rc == 0 and "estado: VERIFICADA" in out, out                      # respuesta completa: no bloquea
    obs = {o["id"]: o for o in m.estado()["carga"]["verificacion"]["observaciones"]}
    assert "PR16-6" in obs["C-03"]["motivo"] and "ronda 1" in obs["C-03"]["motivo"]


def test_r2_objecion_sobre_lo_no_aceptado_sigue_bloqueando_la_ronda(m):  # noqa: F811
    m.hasta_verificacion()
    _ronda(m, R1)
    lote = _cons(m)["lotes"][0]
    rc, out = _registrar(m, _resp(lote["lote_id"], lote["texto"], lote["ids"], DISCREPA_C02), "l1.json")
    assert rc == 1 and "EN_ANALISIS" in out, out                             # C-02 no estaba aceptado


def test_r3_acumula_lo_aceptado_de_las_dos_rondas(m):  # noqa: F811
    m.hasta_verificacion()
    _ronda(m, R1)
    lote = _cons(m)["lotes"][0]
    assert _registrar(m, _resp(lote["lote_id"], lote["texto"], lote["ids"], DISCREPA_C02), "l1.json")[0] == 1
    assert m.run("enrutar")[0] == 0
    b3 = m.estado()["carga"]["briefs"][-1]
    rondas = {a["linea"]: a["ronda"] for a in b3["aceptados"]}
    c05 = verificacion.contenido_linea(_lineas(_cons(m))["C-05"])
    assert b3["ronda"] == 3 and rondas[c05] == 2 and sorted(set(rondas.values())) == [1, 2]
    assert not any(verificacion.contenido_linea(_lineas(_cons(m))["C-02"]) == k for k in rondas)


def test_r2_lo_no_verificable_va_en_su_seccion_y_lo_aceptado_en_verificados(m):  # noqa: F811
    m.hasta_verificacion()
    lineas_r1 = _lineas(_cons(m))
    b = _ronda(m, R1)
    cuerpo = b["texto"].partition("\n---\n")[2]
    import verificar_paquete as vp
    verificados = vp.lineas_seccion(cuerpo, ("## Elementos ya verificados",))
    sin = vp.lineas_seccion(cuerpo, ("## Elementos sin verificar",))
    assert sin and [verificacion.contenido_linea(ln[2:]) for ln in sin] == [verificacion.contenido_linea(lineas_r1["C-05"])]
    assert not any(verificacion.contenido_linea(lineas_r1["C-05"]) == verificacion.contenido_linea(ln[2:])
                   for ln in verificados)
    assert {verificacion.contenido_linea(ln[2:]) for ln in verificados} == {a["linea"] for a in b["aceptados"]}
    assert brief.SECCION_SIN_VERIFICAR in b["texto"]
    c = vp.Comprobacion("brief", "x")
    vp._aceptados_atados_al_texto(__import__("types").SimpleNamespace(carga=m.estado()["carga"]), c, b)
    assert c.estado != vp.FALLA, c.detalles
    forjado = dict(b, aceptados=b["aceptados"] + [{"linea": verificacion.contenido_linea(lineas_r1["C-05"]),
                                                     "veredicto": "OK", "ronda": 1}])
    c = vp.Comprobacion("brief", "x")
    vp._aceptados_atados_al_texto(__import__("types").SimpleNamespace(carga=m.estado()["carga"]), c, forjado)
    assert c.estado == vp.FALLA                       # Revisión: un NO VERIFICABLE no se puede dar por aceptado

