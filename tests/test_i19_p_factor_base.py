"""I1.9 · papel P, cierre (16-10-2026): E19-2 / PR18-5, el factor se elige por la base de la cita. Cada caso compara
el núcleo con la réplica de la puerta (i19_p_datos.reglas_i19 y factor_base_r regla a regla)."""
from __future__ import annotations

import copy

import pytest

from tests import i19_p_datos as D
from tests.test_i19_p_existentes import H1, caso_h1
from nucleo import experto

CAT = D.catalogo_i19()
ACCIONES = "Aproximadamente 1.500 acciones al mes."


def con_precios(precios: list[tuple], catalogo: dict = CAT, volumetria: str | None = None):
    """H1 corregida (API Management del cliente) con precios de volumen añadidos: (id, componente, plantilla, cita,
    cantidad, unidad_base). `volumetria`: una entrada más de la volumetría (y el brief rehecho con ella)."""
    r, br, req = caso_h1()
    if volumetria:
        req["campos"]["volumetria"]["entradas"].append({"valor": volumetria, "cita": volumetria, "fuente": "F1",
                                                        "origen": "CITADO"})
        br = D.brief_hostelia(H1, req)
        r = D.con_brief(r, br)
    for pid, cid, pl, cita, n, ud in precios:
        r["precios"].append({"id": pid, "componente_id": cid, "plantilla_id": pl, "instancias": None,
                             "base_volumen": {"cita": cita, "cantidad_base": n, "unidad_base": ud},
                             "factor_override": None})
    return r, br, req


def test_las_acciones_se_valoran_con_el_factor_por_accion_y_el_revisor_lo_ve():
    """Caso real de Hostelia (PR18-5): las 1.500 acciones al mes no se podían valorar en Foundry (base_no_casa)."""
    r, br, req = con_precios([("P-07", "C-04", "gpt-6-luna-entrada", ACCIONES, 1500, "acciones al mes"),
                              ("P-08", "C-04", "gpt-6-luna-salida", ACCIONES, 1500, "acciones al mes")])
    reglas = D.reglas_i19(r, br, req, CAT)
    assert reglas["completar"] == [] and reglas["volumen_nivel"] == []
    c = reglas["completada"]
    p7 = next(p for p in c["precios"] if p["id"] == "P-07")
    assert p7["base_volumen"]["factor"]["unidad"] == "tokens de entrada por acción" and p7["cantidad_mensual"] == 8.484
    p2 = next(p for p in c["precios"] if p["id"] == "P-02")   # las consultas siguen con el estándar
    assert p2["base_volumen"]["factor"]["unidad"] == "tokens de entrada por consulta"
    linea = next(x for x in experto.lineas_para_revisor(c, CAT, requisitos=req) if "precio P-07" in x)
    assert "Factor alternativo del catálogo por «acción»" in linea and "no «consulta» o «pregunta»" in linea
    assert D.analizar(r, br, req, CAT)[0] == []


def test_api_management_por_llamadas_con_acciones_usa_su_factor_por_accion():
    info = experto.resolver_plantilla("consumo-llamadas", {"catalogo_id": "az-api-management"}, CAT)[0]
    f, problema = experto.factor_por_base(info, CAT, ACCIONES, "acciones al mes")
    assert problema is None and f["id"] == "integracion.llamadas_api_por_accion"
    f, _ = experto.factor_por_base(info, CAT, "Aproximadamente 6.000 consultas al mes.", "consultas al mes")
    assert f["id"] == "integracion.llamadas_api_por_consulta"


@pytest.mark.parametrize("cita,ud,esperado", [
    ("Unas 2.000 consultas y 1.500 acciones al mes.", "consultas y acciones", "mal"),   # casan las dos: falla cerrado
    ("Unas 2.000 consultas y 1.500 acciones al mes.", "acciones", "asistente_rag.tokens_entrada_por_accion"),
    ("Unas 2.000 consultas y 1.500 acciones al mes.", "consultas", "asistente_rag.tokens_entrada_por_consulta"),
    ("Unos 3.000 documentos.", "documentos", "asistente_rag.tokens_entrada_por_consulta"),  # ninguna: el estándar
    ("Ninguna acción al mes.", "acciones", "asistente_rag.tokens_entrada_por_accion")])
def test_eleccion_por_base_y_su_replica(cita, ud, esperado):
    info = experto.resolver_plantilla("gpt-6-luna-entrada", {"catalogo_id": "az-foundry"}, CAT)[0]
    f, problema = experto.factor_por_base(info, CAT, cita, ud)
    assert (f["id"] if f else "mal") == esperado and (problema is not None) == (esperado == "mal")
    estado, fr = D.R19.factor_base_r(info["plantilla"], info["fila"], info["clave"], CAT, cita, ud)
    assert estado == ("mal" if esperado == "mal" else "ok")
    assert fr is None if f is None else (fr["v"], fr["unidad"], fr["bases"]) == (f["valor"], f["unidad"], f["bases"])


def test_dos_bases_a_la_vez_falla_cerrado_y_ninguna_lista_todas_las_bases():
    ambas = "Unas 2.000 consultas y 1.500 acciones al mes."
    r, br, req = con_precios([("P-07", "C-04", "gpt-6-luna-entrada", ambas, 1500, "consultas y acciones")],
                             volumetria=ambas)
    assert ("P-07", "factor_estandar_no_valido") in D.reglas_i19(r, br, req, CAT)["completar"]
    errores, _ = D.analizar(r, br, req, CAT)
    assert any("casan con más de una base" in e for e in errores)
    r, br, req = con_precios([("P-07", "C-04", "gpt-6-luna-entrada", "Aproximadamente 800 documentos.", 800,
                               "documentos")])
    assert D.reglas_i19(r, br, req, CAT)["completar"] == [("P-07", "base_no_casa")]
    errores, _ = D.analizar(r, br, req, CAT)
    assert any("el factor del catálogo es por «consulta» o «pregunta» o «acción»" in e for e in errores)


def test_la_unidad_de_la_cantidad_se_lee_con_la_base_elegida():
    """REV17-7 con E19-2: en una cita con consultas y acciones, la cantidad es el número que va con la base elegida."""
    cat = copy.deepcopy(CAT)
    r, br, req = con_precios([("P-07", "C-04", "gpt-6-luna-entrada", ACCIONES, 1500, "acciones al mes")], cat)
    c = D.reglas_i19(r, br, req, cat)["completada"]
    assert not [e for e in experto.errores_volumen_nivel(c, br["texto"], req, cat)
                if e["regla"] == "cantidad_sin_su_unidad"]
    info = experto.resolver_plantilla("gpt-6-luna-entrada", {"catalogo_id": "az-foundry"}, cat)[0]
    base = {"cita": "Unas 2.000 consultas y 1.500 acciones al mes.", "unidad_base": "acciones"}
    assert experto.palabras_de_base(info, base, cat) == ["acción"]
    assert experto.cantidad_con_su_unidad(base["cita"], 1500, ["acción"])
    assert not experto.cantidad_con_su_unidad(base["cita"], 2000, ["acción"])


@pytest.mark.parametrize("rotura", ["id_desconocido", "sin_base", "mal_formado", "incompleto"])
def test_catalogo_roto_falla_cerrado_en_nucleo_y_replica(rotura):
    cat = copy.deepcopy(CAT)
    fila = next(e for e in cat["componentes"] if e["id"] == "az-foundry")
    pl = next(p for p in fila["plantillas_precio"] if p["id"] == "gpt-6-luna-entrada")
    alt = next(f for f in cat["factores_estandar"] if f["id"] == "asistente_rag.tokens_entrada_por_accion")
    {"id_desconocido": lambda: pl.update(factores_alternativos=["asistente_rag.no_existe"]),
     "sin_base": lambda: alt.pop("base"),
     "mal_formado": lambda: pl.update(factores_alternativos="asistente_rag.tokens_entrada_por_accion"),
     "incompleto": lambda: [alt.pop(k, None) for k in ("fuente", "fuente_url")]}[rotura]()
    info = experto.resolver_plantilla("gpt-6-luna-entrada", {"catalogo_id": "az-foundry"}, cat)[0]
    f, problema = experto.factor_por_base(info, cat, ACCIONES, "acciones al mes")
    assert f is None and problema
    assert D.R19.factor_base_r(info["plantilla"], info["fila"], info["clave"], cat, ACCIONES, "acciones al mes") == \
        ("mal", None)
    r, br, req = con_precios([("P-07", "C-04", "gpt-6-luna-entrada", ACCIONES, 1500, "acciones al mes")], cat)
    # Falla cerrado para todo precio de esa plantilla, también el de consultas (P-02)
    assert D.reglas_i19(r, br, req, cat)["completar"] == [("P-02", "factor_estandar_no_valido"),
                                                         ("P-07", "factor_estandar_no_valido")]


def test_revision_con_factor_cambiado_la_nota_no_llama_estandar_al_alternativo():
    """Revisión (cierre): con factor_override sobre una cita de acciones, el revisor ve el factor del catálogo para esa
    base y, aparte, el estándar por consulta; antes el alternativo salía como «estándar del catálogo»."""
    r, br, req = con_precios([("P-07", "C-04", "gpt-6-luna-entrada", ACCIONES, 1500, "acciones al mes")])
    r["precios"][-1]["factor_override"] = {"valor": 3000, "cita": ACCIONES,
                                           "justificacion": "Cada acción lleva menos contexto que una consulta"}
    c = D.reglas_i19(r, br, req, CAT)["completada"]
    linea = next(x for x in experto.lineas_para_revisor(c, CAT, requisitos=req) if "precio P-07" in x)
    assert ("FACTOR CAMBIADO POR EL EXPERTO (revisar): factor del catálogo para esa base 5656 tokens de entrada por "
            "acción (estándar del catálogo 5656 tokens de entrada por consulta)") in linea
    r, br, req = con_precios([("P-07", "C-04", "gpt-6-luna-entrada", "Aproximadamente 6.000 consultas al mes.", 6000,
                               "consultas al mes")])
    r["precios"][-1]["factor_override"] = {"valor": 3000, "cita": ACCIONES, "justificacion": "Contexto corto"}
    c = D.reglas_i19(r, br, req, CAT)["completada"]
    linea = next(x for x in experto.lineas_para_revisor(c, CAT, requisitos=req) if "precio P-07" in x)
    assert "(revisar): estándar del catálogo 5656 tokens de entrada por consulta;" in linea
