"""I1.7 · Papel R · puerta local: instantánea de precios (huella y edad), datos de control del brief atados a su texto
(REVERIF16-2), PR16-6 (heredados aceptados y objeción que pasa a OBSERVACION) y briefs validados con su esquema.
Funciones de verificar_paquete.py con casos adversos y su resultado esperado. Sin red."""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import types

import pytest

import verificar_paquete as vp
from tests.fixtures_i1.construir import CATALOGO, INSTANTANEA

CAT = json.loads(CATALOGO.read_text(encoding="utf-8"))
INST = json.loads(INSTANTANEA.read_text(encoding="utf-8"))
DIA = dt.date(2026, 10, 8)


def _sellar(obj: dict) -> dict:
    obj = copy.deepcopy(obj)
    try:
        obj["sha256"] = vp.hash_instantanea_replica(obj)
    except ValueError:      # con un infinito no hay huella: la puerta lo dice y sigue
        pass
    return obj


def test_la_instantanea_de_ejemplo_vale_para_un_paquete_del_8_de_octubre():
    assert vp.errores_instantanea(INST, DIA, CAT) == []


@pytest.mark.parametrize("cambiar, dia, trozo", [
    # Integrador I1.7: la instantánea de las pruebas es la del ejemplo (consultada el 2026-10-08), no la del 01-10
    (lambda o: None, dt.date(2026, 11, 8), None),                                 # 31 días justos: vale
    (lambda o: None, dt.date(2026, 11, 9), "más de 31"),                          # 32 días: FALLA
    (lambda o: None, dt.date(2026, 10, 7), "posterior a la fecha del paquete"),
    (lambda o: None, None, "fecha del paquete"),
    (lambda o: o.update(fecha_consulta="2026-10-01T08:00:00"), DIA, "sin zona horaria"),
    (lambda o: o.update(fecha_consulta="ayer"), DIA, "no es una fecha ISO"),
    (lambda o: o.update(moneda="USD"), DIA, "en EUR"),
    (lambda o: o.update(schema="otra/1"), DIA, "no es una instantánea"),
    (lambda o: next(iter(o["plantillas"].values())).update(articulos_devueltos=0), DIA, "artículos devueltos"),
    (lambda o: next(iter(o["plantillas"].values())).update(articulos_devueltos=True), DIA, "artículos devueltos"),
    (lambda o: next(iter(o["plantillas"].values())).update(precio_unitario=-1), DIA, "finito y no negativo"),
    (lambda o: next(iter(o["plantillas"].values())).update(precio_unitario=float("inf")), DIA, "finito"),
    (lambda o: next(iter(o["plantillas"].values())).update(precio_unitario=10 ** 400), DIA, "finito"),   # Revisión 2
    (lambda o: o["plantillas"].pop(next(iter(o["plantillas"]))), DIA, "falta la plantilla"),
    (lambda o: o["plantillas"].update({"az-x/y": dict(next(iter(o["plantillas"].values())))}), DIA, "no está en el catálogo"),
    (lambda o: next(iter(o["plantillas"].values())).update(filtro="serviceName eq 'Otro'"), DIA, "el filtro no es el"),
])
def test_instantanea_casos_adversos(cambiar, dia, trozo):
    o = copy.deepcopy(INST)
    cambiar(o)
    errores = vp.errores_instantanea(_sellar(o) if o.get("schema") == INST["schema"] else o, dia, CAT)
    assert (errores == []) if trozo is None else any(trozo in e for e in errores), errores


def test_huella_interna_distinta_falla_aunque_lo_demas_valga():
    o = copy.deepcopy(INST)
    next(iter(o["plantillas"].values()))["precio_unitario"] = 9.99            # sin resellar
    assert any("huella interna" in e for e in vp.errores_instantanea(o, DIA, CAT))


def _ctx(tmp_path: pathlib.Path, declarada: object, inst: dict | None = None, generado="2026-10-08T10:11:00+02:00"):
    ruta = tmp_path / "inst.json"
    ruta.write_text(json.dumps(inst or INST), encoding="utf-8")
    montados = {} if declarada is None else {"precios_instantanea_sha256": declarada}
    return types.SimpleNamespace(precios=ruta, manifiesto={"generado_ts": generado}, catalogo_obj=CAT), montados, ruta


def test_instantanea_en_la_puerta_huella_declarada_igual_distinta_o_ausente(tmp_path):
    ctx, montados, ruta = _ctx(tmp_path, None)
    for declarada, falla in ((vp.sha256_fichero(ruta), False), ("0" * 64, True), (None, True)):
        c = vp.Comprobacion("montados", "x")
        vp._instantanea(ctx, c, {} if declarada is None else {"precios_instantanea_sha256": declarada})
        assert (c.estado == vp.FALLA) is falla, (declarada, c.estado)


def test_instantanea_vieja_en_la_fecha_del_paquete_falla_en_la_puerta(tmp_path):
    ctx, _m, ruta = _ctx(tmp_path, None, generado="2026-11-10T09:00:00+01:00")  # integrador I1.7: 33 días
    c = vp.Comprobacion("montados", "x")
    vp._instantanea(ctx, c, {"precios_instantanea_sha256": vp.sha256_fichero(ruta)})
    assert c.estado == vp.FALLA


def test_instantanea_ausente_falla(tmp_path):
    ctx = types.SimpleNamespace(precios=tmp_path / "no.json", manifiesto={}, catalogo_obj=CAT)
    c = vp.Comprobacion("montados", "x")
    vp._instantanea(ctx, c, {"precios_instantanea_sha256": "0" * 64})
    assert c.estado == vp.FALLA


# --- REVERIF16-2: conservar_precios atado al texto sellado del brief ---
SECCION = "## Precios conservados (repite plantilla_id …)"
LINEAS_P = ["- P-01 | C-01 | plantilla: gpt-6-luna-entrada | base: «2.000 consultas.» (2000 consultas) | factor: "
            "estándar del catálogo | cantidad_mensual: 8", "- P-03 | C-02 | plantilla: basic | cantidad_mensual: 730"]
DATO = [{"catalogo_id": "az-foundry", "plantilla_id": "gpt-6-luna-entrada", "filtro": None, "cantidad_mensual": 8,
         "precio_ids": ["P-01"], "componente_ids": ["C-01"]},
        {"catalogo_id": "az-ai-search", "plantilla_id": "basic", "filtro": None, "cantidad_mensual": 730,
         "precio_ids": ["P-03"], "componente_ids": ["C-02"]}]


def _atado(cuerpo: str, b: dict) -> vp.Comprobacion:
    c = vp.Comprobacion("brief", "x")
    vp._conservar_atado_al_texto(c, {"brief_id": "BRF-X", **b}, cuerpo)
    return c


@pytest.mark.parametrize("lineas, dato, falla", [
    (LINEAS_P, DATO, False),
    (LINEAS_P, list(reversed(DATO)), False),
    (LINEAS_P, [], True),                                       # lista vacía con líneas en el texto
    (LINEAS_P, {"x": 1}, True),                                 # otra forma
    (LINEAS_P, None, True),
    (LINEAS_P, [dict(DATO[0], cantidad_mensual=80), DATO[1]], True),
    (LINEAS_P, [DATO[0]], True),
    (LINEAS_P[:1], DATO, True),
    (LINEAS_P[:1] + ["- P-09 | C-01 | plantilla: gpt-6-luna-entrada | cantidad_mensual: 72"],
     [dict(DATO[0], cantidad_mensual=80, precio_ids=["P-01", "P-09"])], False),      # suma por plantilla
    (["- P-01 | C-01 | sin forma"], DATO[:1], True),
])
def test_conservar_atado_al_texto(lineas, dato, falla):
    cuerpo = "\n".join(["## Necesidad", "Objetivo: x", SECCION, *lineas])
    b = {} if dato is None else {"conservar_precios": dato}
    assert (_atado(cuerpo, b).estado == vp.FALLA) is falla


def test_sin_seccion_ni_dato_no_hay_nada_que_atar_y_dato_sin_seccion_falla():
    assert _atado("## Necesidad\nObjetivo: x", {"conservar_precios": []}).estado != vp.FALLA
    assert _atado("## Necesidad\nObjetivo: x", {}).estado != vp.FALLA
    assert _atado("## Necesidad\nObjetivo: x", {"conservar_precios": DATO}).estado == vp.FALLA


# --- PR16-6: aceptados atados a los briefs, heredados y objeción que pasa a OBSERVACION ---
C03 = ("C-03 | Azure App Service | sku: B1 | region: swedencentral | referencia: "
       "https://learn.microsoft.com/azure/app-service/overview")


def _brief(ronda: int, texto_cuerpo: str, aceptados=None, version="A") -> dict:
    return {"brief_id": f"BRF-OF-K-001-{version}-AZ-R{ronda}", "version": version, "ronda": ronda,
            "texto": "BRIEF-PREVENTA/1\n---\n" + texto_cuerpo, "aceptados": aceptados or []}


def _atados(briefs: list[dict], b: dict) -> vp.Comprobacion:
    c = vp.Comprobacion("brief", "x")
    vp._aceptados_atados_al_texto(types.SimpleNamespace(carga={"briefs": briefs}), c, b)
    return c


def test_aceptados_tienen_que_figurar_como_conservados_en_un_brief_de_la_version():
    acept = [{"linea": vp.contenido_linea_replica(C03), "veredicto": "OK", "ronda": 1}]
    b2 = _brief(2, "## Elementos ya verificados (…)\n- " + C03, acept)
    assert _atados([_brief(1, "## Necesidad"), b2], b2).estado != vp.FALLA
    forjado = _brief(2, "## Elementos ya verificados (…)\n- C-01 | otra cosa", acept)
    assert _atados([_brief(1, "## Necesidad"), forjado], forjado).estado == vp.FALLA
    r1 = _brief(1, "## Elementos ya verificados\n- " + C03, acept)
    assert _atados([r1], r1).estado == vp.FALLA                            # ronda 1 sin aceptados
    de_a = _brief(1, "## Elementos ya verificados\n- " + C03, version="A")
    b_b2 = _brief(2, "## Necesidad", acept, version="B")
    assert _atados([de_a, b_b2], b_b2).estado == vp.FALLA                  # lo de la versión A no se hereda en B


def _ctx_verif(aceptados: list[dict], elementos: list[dict], lotes_ids: list[list[str]] | None):
    texto = ("CONSOLIDADO-PREVENTA/1\nbrief_id: BRF-OF-K-001-A-AZ-R2\n---\n## Componentes\n" + C03.replace("C-03", "C-01")
             + "\nC-02 | Azure AI Search | sku: Basic | region: swedencentral | referencia: "
             "https://learn.microsoft.com/azure/search/")
    cons = {"consolidado_id": "CNS-OF-K-001-A-R2", "texto": texto, "ids": ["C-01", "C-02"], "lotes": []}
    for n, ids in enumerate(lotes_ids or [], 1):
        cons["lotes"].append({"lote_id": f"CNS-OF-K-001-A-R2-L{n}", "ids": ids, "texto": texto, "respuesta": {
            "consolidado_id": f"CNS-OF-K-001-A-R2-L{n}", "elementos": [e for e in elementos if e["id"] in ids],
            "entrada_recibida_inicio": "\n".join(texto.split("\n")[:3])}})
    resp = {"elementos": elementos, "consolidado_id": cons["consolidado_id"]}
    b = _brief(2, "## Elementos ya verificados\n- " + C03.replace("C-03", "C-01"), aceptados)
    carga = {"briefs": [b], "consolidado": cons, "respuestas_expertos": {"azure": {
        "brief_id": b["brief_id"], "respuesta": {"referencias": [], "precios": []}}},
        "verificacion": {"respuesta": resp, "lotes": [x["lote_id"] for x in cons["lotes"]]}}
    return types.SimpleNamespace(carga=carga, respuesta=carga["respuestas_expertos"]["azure"]["respuesta"]), cons, resp


def _el(i, veredicto="OK", **k):
    return {"id": i, "tipo": "componente", "veredicto": veredicto, "campo": k.get("campo", "ninguno"), "detalle": "det",
            "valor_correcto": k.get("vc"), "fuente_url": k.get("fuente")}


ACEPT_C01 = [{"linea": vp.contenido_linea_replica(C03), "veredicto": "OK", "ronda": 1}]
DISC = dict(vc="S1", campo="sku", fuente="https://learn.microsoft.com/azure/app-service/overview")


def test_objecion_sobre_aceptado_sin_cambios_pasa_a_observacion_y_la_otra_bloquea():
    ctx, _c, _r = _ctx_verif(ACEPT_C01, [_el("C-01", "DISCREPA", **DISC), _el("C-02", "DISCREPA", **DISC)], None)
    discrepa, _nov, _rep, obs = vp.evaluar_verificacion(ctx)
    assert obs == ["C-01"] and [d.split(":")[0] for d in discrepa] == ["C-02"]
    ctx, _c, _r = _ctx_verif([], [_el("C-01", "DISCREPA", **DISC)], None)
    assert [d.split(":")[0] for d in vp.evaluar_verificacion(ctx)[0]] == ["C-01"]       # sin aceptar, bloquea


def _contrato(aceptados, elementos, lotes_ids) -> vp.Comprobacion:
    ctx, cons, resp = _ctx_verif(aceptados, elementos, lotes_ids)
    c = vp.Comprobacion("verificacion", "x")
    vp._comprobar_contrato_y_lotes(c, ctx, cons, ctx.carga["verificacion"], resp)
    return c


def test_heredado_sin_veredicto_solo_si_esta_aceptado():
    c = _contrato(ACEPT_C01, [_el("C-02")], [["C-02"]])
    assert c.estado != vp.FALLA, c.detalles
    c = _contrato([], [_el("C-02")], [["C-02"]])
    assert c.estado == vp.FALLA and any("PR16-6" in d for d in c.detalles)
    assert _contrato(ACEPT_C01, [_el("C-02"), _el("C-01")], [["C-02", "C-01"]]).estado == vp.FALLA   # desordenado
    assert _contrato(ACEPT_C01, [_el("C-02")], [["C-02"], ["C-02"]]).estado == vp.FALLA             # repetido


def test_los_nucleos_y_la_puerta_leen_igual_el_contenido_de_una_linea():
    from nucleo import verificacion
    for ln in (C03, "  C-03 |  Azure  App Service | x ", "REF-01 | https://learn.microsoft.com/a | T", "sin id", ""):
        assert verificacion.contenido_linea(ln) == vp.contenido_linea_replica(ln)
