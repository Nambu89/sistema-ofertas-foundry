"""Arreglos I1.7 (núcleo y puerta, con el catálogo v6 real y la instantánea real del sandbox):

- PR17-1: la referencia de un componente del catálogo lleva el título PUBLICADO en Learn (`referencia_titulo`).
- PR17-3 / VER17-1: Storage se valora desde los documentos citados con su factor estándar, y un componente con precios
  propios lleva los medidores obligatorios de su fila (la capacidad de Storage; núcleos y memoria de Functions).
- PR17-4: el cómputo por defecto (App Service B1) no justifica su nivel; Functions Premium sí (nivel EP1).
- PR17-5: la memoria de una EP1 son 3,5 GB por instancia (730 × 3,5 = 2.555 GiB·h al mes).
Cada regla se comprueba en el núcleo y en la réplica de la puerta, con prueba de igualdad.
"""
from __future__ import annotations

import copy
import json

import pytest

from tests.i17_p_datos import RAIZ, estado_brezalia, perfiles, respuesta_v4
from nucleo import experto
import verificar_paquete as vp

CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
INST = json.loads((RAIZ / "sandbox" / "datos" / "precios_instantanea.json").read_text(encoding="utf-8"))
HOY = str(INST["fecha_consulta"])[:10]
DOCS = {"cita": "Unos 3.000 documentos.", "cantidad_base": 3000, "unidad_base": "documentos"}
# Integrador I1.9 (contrato v5): la justificación es {nivel, razon, cita}; la razón «plataforma_nombrada» de EP1 la
# cumple una entrada de los requisitos que nombra Azure Functions (Brezalia no la tiene: la añade _con_functions)
CITA_FUNCTIONS = "La lógica de integración irá en Azure Functions Premium."
EP1 = {"nivel": "EP1", "razon": "plataforma_nombrada", "cita": CITA_FUNCTIONS}


def _con_functions(req):
    req = copy.deepcopy(req)
    req["campos"]["canales_integraciones"]["entradas"].append(
        {"valor": CITA_FUNCTIONS, "cita": CITA_FUNCTIONS, "fuente": "F1", "origen": "CITADO"})  # el valor es lo que se cita
    return req


def _flujo_a(r, cid, descripcion="La aplicación lee y escribe los documentos"):
    """I1.9 (VA18-4): un componente de datos necesita un flujo con quien usa sus datos."""
    r["flujos"].append({"origen": "C-04", "destino": cid, "descripcion": descripcion})


def _base():
    est = estado_brezalia()
    brief = est["carga"]["briefs"][-1]
    r = respuesta_v4(brief)
    r["arquitectura_id"] = "foundry-chat-basica"
    for c in r["componentes"]:
        if c["id"] == "C-04":
            c["justificacion_nivel"] = None      # PR17-4: el cómputo por defecto no la necesita
    return brief, est["carga"]["requisitos"], r


def _analizar(r, brief, req):
    return experto.analizar_respuesta(r, brief, CAT, perfiles(brief), req, INST, HOY)


def _comp(r, cid, catalogo_id, servicio, capa, sku, region="swedencentral"):
    r["componentes"].append({"id": cid, "catalogo_id": catalogo_id, "servicio": servicio, "capa": capa, "sku": sku,
                             "region": region, "cantidad": 1, "unidad": "cuenta", "referencia_id": None,
                             "desviacion_justificada": None, "motivo_no_valoracion": "no_aplica", "existente_del_cliente": None,
                             "incluido_en": None, "justificacion_nivel": None})


def _precio(r, pid, cid, plantilla, instancias=None, base=None):
    r["precios"].append({"id": pid, "componente_id": cid, "plantilla_id": plantilla, "instancias": instancias,
                         "base_volumen": copy.deepcopy(base), "factor_override": None})


def _iguales(r, brief, req):
    """Núcleo y réplica de la puerta dan lo mismo: recomposición y reglas de volumen y nivel."""
    _, completada = _analizar(r, brief, req)
    assert completada is not None
    rec, fallos = vp.completar_r(vp.proyectar_r(completada), CAT, INST, req, brief["texto"])
    assert fallos == [] and rec == completada
    nucleo = [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(completada, brief["texto"], req, CAT)]
    assert nucleo == vp.errores_volumen_nivel_replica(completada, brief["texto"], req, CAT) == []
    return completada


def test_control_la_respuesta_base_pasa_con_el_cumputo_por_defecto_sin_justificar():
    brief, req, r = _base()
    errores, completada = _analizar(r, brief, req)
    assert errores == [] and completada is not None
    _iguales(r, brief, req)


def test_pr17_1_titulo_publicado_en_learn_en_nucleo_y_puerta():
    brief, req, r = _base()
    c = _iguales(r, brief, req)
    refs = {x["id"]: x for x in c["referencias"]}
    filas = {f["id"]: f for f in CAT["componentes"]}
    for comp in c["componentes"]:
        fila = filas.get(comp["catalogo_id"])
        if fila:
            assert refs[comp["referencia_id"]]["titulo"] == fila["referencia_titulo"]
            assert "en Microsoft Learn" not in refs[comp["referencia_id"]]["titulo"]
    assert refs[c["valoracion_nucleo"]["arquitectura"]["referencia_id"]]["titulo"] == \
        "Basic Microsoft Foundry chat reference architecture"


def test_pr17_1_sin_titulo_publicado_en_la_fila_falla_cerrado():
    brief, req, r = _base()
    cat = copy.deepcopy(CAT)
    next(f for f in cat["componentes"] if f["id"] == "az-ai-search").pop("referencia_titulo")
    _, errores = experto.completar(r, cat, INST, req, brief["texto"])
    assert [(e["id"], e["regla"]) for e in errores] == [("C-02", "catalogo_sin_referencia")]
    _, fallos = vp.completar_r(r, cat, INST, req, brief["texto"])
    assert fallos == [("C-02", "catalogo_sin_referencia")]


def test_pr17_3_storage_desde_los_documentos_citados_con_el_factor_estandar():
    brief, req, r = _base()
    _comp(r, "C-07", "az-storage", "Azure Blob Storage", "datos_conocimiento", "Hot LRS")
    _flujo_a(r, "C-07")
    _precio(r, "P-06", "C-07", "hot-lrs-datos", base=DOCS)
    c = _iguales(r, brief, req)
    p = next(x for x in c["precios"] if x["id"] == "P-06")
    assert p["cantidad_mensual"] == 6 and p["base_volumen"]["factor"]["origen"] == "catalogo"
    assert p["base_volumen"]["factor"]["valor"] == 0.002 and p["precio"] == 0.0162


def test_ver17_1_storage_solo_por_escrituras_falla_por_medidor_obligatorio():
    """El caso real de la sesión 1 (versión B): escrituras de 3.000 «documentos escritos» y la capacidad sin valorar."""
    brief, req, r = _base()
    _comp(r, "C-07", "az-storage", "Azure Blob Storage", "datos_conocimiento", "Hot LRS")
    _flujo_a(r, "C-07")
    _precio(r, "P-06", "C-07", "hot-lrs-escrituras", base={**DOCS, "unidad_base": "documentos escritos"})
    r["precios"][-1]["factor_override"] = {"valor": 1, "cita": "Unos 3.000 documentos.",
                                           "justificacion": "Una escritura por documento al cargarlo."}
    errores, completada = _analizar(r, brief, req)
    assert completada is None and any("C-07" in e and "hot-lrs-datos" in e for e in errores), errores
    comp, _ = experto.completar(r, CAT, INST, req, brief["texto"])
    assert [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(comp, brief["texto"], req, CAT)] == \
        vp.errores_volumen_nivel_replica(comp, brief["texto"], req, CAT) == [("C-07", "falta_medidor_obligatorio")]


def test_pr17_4_functions_premium_exige_justificar_el_nivel_ep1():
    brief, req, r = _base()
    req = _con_functions(req)
    r["componentes"] = [c for c in r["componentes"] if c["id"] != "C-04"]
    r["precios"] = [p for p in r["precios"] if p["componente_id"] != "C-04"]
    r["flujos"] = [f for f in r["flujos"] if "C-04" not in (f["origen"], f["destino"])]
    _comp(r, "C-04", "az-functions", "Azure Functions", "aplicacion_integracion", "EP1")
    r["flujos"] += [{"origen": "C-03", "destino": "C-04", "descripcion": "El bot llama a la función"},
                    {"origen": "C-04", "destino": "C-01", "descripcion": "La función invoca el modelo"},
                    {"origen": "C-04", "destino": "C-02", "descripcion": "La función recupera fragmentos"}]
    _precio(r, "P-05", "C-04", "premium-vcpu", 1)
    _precio(r, "P-07", "C-04", "premium-memoria", 1)
    errores, completada = _analizar(r, brief, req)
    # I1.9: el mensaje dice ahora que no es el nivel por defecto y qué razones lo justificarían
    assert completada is None and any("C-04" in e and "Azure Functions no usa el nivel por defecto" in e for e in errores), errores
    comp, _ = experto.completar(r, CAT, INST, req, brief["texto"])
    assert [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(comp, brief["texto"], req, CAT)] == \
        vp.errores_volumen_nivel_replica(comp, brief["texto"], req, CAT) == [("C-04", "nivel_sin_justificar")]
    next(c for c in r["componentes"] if c["id"] == "C-04")["justificacion_nivel"] = copy.deepcopy(EP1)
    c = _iguales(r, brief, req)
    mem = next(x for x in c["precios"] if x["id"] == "P-07")
    assert mem["cantidad_mensual"] == 2555 and "3,5 (GB de memoria por instancia EP1)" in mem["supuesto_cantidad"]
    assert next(x for x in c["precios"] if x["id"] == "P-05")["cantidad_mensual"] == 730
    lineas = experto.lineas_computo(c, CAT)
    assert len(lineas) == 1 and "no es el por defecto" in lineas[0] and "EP1" in lineas[0]


def test_pr17_4_functions_sin_memoria_falla_por_medidor_obligatorio():
    brief, req, r = _base()
    req = _con_functions(req)
    _comp(r, "C-07", "az-functions", "Azure Functions", "aplicacion_integracion", "EP1")
    r["componentes"][-1]["justificacion_nivel"] = copy.deepcopy(EP1)
    _precio(r, "P-06", "C-07", "premium-vcpu", 1)
    comp, _ = experto.completar(r, CAT, INST, req, brief["texto"])
    assert ("C-07", "falta_medidor_obligatorio") in vp.errores_volumen_nivel_replica(comp, brief["texto"], req, CAT)
    assert {"id": "C-07", "regla": "falta_medidor_obligatorio"} in [
        {k: x[k] for k in ("id", "regla")} for x in experto.errores_volumen_nivel(comp, brief["texto"], req, CAT)]


def test_pr17_4_app_service_premium_sigue_exigiendo_justificacion():
    brief, req, r = _base()
    next(p for p in r["precios"] if p["id"] == "P-05")["plantilla_id"] = "p1v3-linux"
    comp, _ = experto.completar(r, CAT, INST, req, brief["texto"])
    assert [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(comp, brief["texto"], req, CAT)] == \
        vp.errores_volumen_nivel_replica(comp, brief["texto"], req, CAT) == [("C-04", "nivel_sin_justificar")]


def test_pr17_5_por_instancia_alterado_se_detecta_en_la_puerta():
    """Una completada con la memoria a 1 GB por instancia (lo de I1.7) ya no es la que recompone la puerta."""
    brief, req, r = _base()
    req = _con_functions(req)
    _comp(r, "C-07", "az-functions", "Azure Functions", "aplicacion_integracion", "EP1")
    r["componentes"][-1]["justificacion_nivel"] = copy.deepcopy(EP1)
    _precio(r, "P-06", "C-07", "premium-vcpu", 1)
    _precio(r, "P-08", "C-07", "premium-memoria", 2)
    c = _iguales(r, brief, req)
    assert next(x for x in c["precios"] if x["id"] == "P-08")["cantidad_mensual"] == 5110
    roto = copy.deepcopy(c)
    next(x for x in roto["precios"] if x["id"] == "P-08")["cantidad_mensual"] = 1460
    rec, _ = vp.completar_r(vp.proyectar_r(roto), CAT, INST, req, brief["texto"])
    assert rec != roto


@pytest.mark.parametrize("valor", [0, -1, 1001, "3,5"])
def test_pr17_5_por_instancia_no_valido_falla_cerrado(valor):
    brief, req, r = _base()
    cat = copy.deepcopy(CAT)
    fila = next(f for f in cat["componentes"] if f["id"] == "az-functions")
    next(p for p in fila["plantillas_precio"] if p["id"] == "premium-memoria")["por_instancia"]["valor"] = valor
    _comp(r, "C-07", "az-functions", "Azure Functions", "aplicacion_integracion", "EP1")
    _precio(r, "P-06", "C-07", "premium-memoria", 1)
    _, errores = experto.completar(r, cat, INST, req, brief["texto"])
    assert ("P-06", "por_instancia_no_valido") in [(e["id"], e["regla"]) for e in errores]
    assert ("P-06", "por_instancia_no_valido") in vp.completar_r(r, cat, INST, req, brief["texto"])[1]
