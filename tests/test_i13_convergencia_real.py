"""CMP-1 / VER13-1 (I1.3): las rondas 3 reales de A y de B, repetidas con el núcleo de los arreglos.

Datos: las evidencias de I1.3 (respuestas del experto y del verificador de la ronda 3 y el estado vivo de la sesión
de B, ambos sintéticos: Brezalia). Se recompone el consolidado con el núcleo y el catálogo actuales y se evalúan los
veredictos que dio el verificador real. Lo que bloqueó por la residencia de los SaaS pasa a OBSERVACION; el bot
«global» ya no llega a la verificación (lo rechaza el registro del experto); y la referencia que «no respalda a
todos» (REF-01) sigue siendo DISCREPA con el contrato viejo del verificador: con el nuevo se juzga en cada componente.
"""
from __future__ import annotations

import copy
import glob
import json
import pathlib

import pytest

import tests.test_i1_estado_comun  # noqa: F401  (pone sandbox/ en sys.path, como el resto de pruebas)
from nucleo import experto, verificacion  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[1]
I13 = RAIZ / "pruebas" / "I13"
from tests.i16_p_datos import a_v3, catalogo_i16  # noqa: E402  (I1.6: contrato común de la decisión 4)
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)
CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
ESTADO_B = I13 / "VERIF" / "sesion_B" / "estado.json"


def _leer(p: pathlib.Path) -> dict:
    if not p.exists():
        pytest.skip(f"falta la evidencia {p.relative_to(RAIZ)}")
    return json.loads(p.read_text(encoding="utf-8"))


def _elementos(patron: str) -> list[dict]:
    ficheros = sorted(glob.glob(str(I13 / patron)))
    if not ficheros:
        pytest.skip(f"faltan las respuestas del verificador {patron}")
    elementos = [e for f in ficheros for e in json.loads(pathlib.Path(f).read_text(encoding="utf-8"))["elementos"]]
    # Revisión 3 (I1.4): las evidencias son del contrato anterior; si alguna trajera «campo», la prueba no diría nada.
    assert elementos and all("campo" not in e for e in elementos), patron
    return elementos


def _evaluar(est: dict, elementos: list[dict]) -> verificacion.ResultadoVerificacion:
    est = copy.deepcopy(est)
    cons = verificacion.componer_consolidado(est, CAT, "CNS-OF-BREZALIA-001-A-R3")
    est["carga"]["consolidado"] = {"consolidado_id": cons.consolidado_id, "texto": cons.texto, "ids": list(cons.ids)}
    return verificacion.evaluar(est, {"elementos": elementos})


def _con_campo(elementos: list[dict], campos: dict[str, str]) -> list[dict]:
    """I1.4 (ARR13-4): las respuestas reales son del contrato anterior, sin «campo». Se declara solo el campo que el
    propio detalle real discute («la región indicada como global…»): lo que el verificador de I1.4 tiene que poner."""
    salida = copy.deepcopy(elementos)
    for e in salida:
        if e["id"] in campos:
            e["campo"] = campos[e["id"]]
    return salida


def test_ronda_3_de_b_saas_a_observacion_y_bot_global_rechazado_antes():
    est = _leer(ESTADO_B)
    assert est["estado"] == "BLOQUEADA" and "REF-01, C-06, C-07" in est["motivo_bloqueo"]
    elementos = _elementos("E2E-B/sesion/entrada/respuesta_verificador_CNS-OF-BREZALIA-001-A-R3-L*.json")
    sin_campo = _evaluar(est, elementos)  # contrato anterior: sin campo declarado, nada se reclasifica
    assert {"C-06", "C-07"} <= {d["id"] for d in sin_campo.discrepa} and sin_campo.observaciones == []
    assert "región indicada como «global»" in next(e["detalle"] for e in elementos if e["id"] == "C-06")
    res = _evaluar(est, _con_campo(elementos, {"C-06": "region", "C-07": "region"}))
    assert {o["id"] for o in res.observaciones} >= {"C-06", "C-07"}
    assert _evaluar(est, _con_campo(elementos, {"C-06": "nombre", "C-07": "sku"})).observaciones == []
    assert [d["id"] for d in res.discrepa] == ["REF-01"]  # contrato viejo: «no respalda a Bot Service»
    resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    brief = est["carga"]["briefs"][-1]
    for c in resp["componentes"]:  # I1.5: contrato v2 del experto (motivo_no_valoracion); el resto, real
        c.setdefault("motivo_no_valoracion", "no_aplica")
    resp = a_v3(resp)  # I1.6: contrato v3 (justificacion_nivel y base_volumen a null)
    errores = i17_int.validar(resp, brief, CAT, brief["perfiles_permitidos"])
    assert any(e.startswith("componentes.C-02: Azure AI Bot Service en global") for e in errores), errores


def test_ronda_3_de_a_entra_a_observacion_y_bot_global_rechazado_antes():
    est = _leer(ESTADO_B)  # misma solicitud sintética (alta y requisitos de Brezalia)
    resp_a = _leer(I13 / "E2E-A" / "respuesta_experto_T2_R3.json")
    est = copy.deepcopy(est)
    est["carga"]["respuestas_expertos"]["azure"]["respuesta"] = resp_a
    elementos = _elementos("E2E-A/verificador_R3/respuesta_verificador_CNS-OF-BREZALIA-001-A-R3-L*.json")
    sin_campo = {x["id"] for x in _evaluar(est, elementos).discrepa}
    assert {"C-04", "P-01"} <= sin_campo  # sin campo (contrato anterior): ni se reclasifica ni se repara
    # P-01: «el retailPrice obtenido es 0.088877 EUR, no 0.0889 EUR» (0,03 %): DISCREPA del precio.
    res = _evaluar(est, _con_campo(elementos, {"C-04": "region", "P-01": "precio"}))
    assert "C-04" in {o["id"] for o in res.observaciones}  # Entra ID «global», fuente data-residency
    assert {d["id"] for d in res.discrepa} == {"REF-01", "C-02"} and "P-01" in {x["id"] for x in res.reparados}
    assert "P-01" in {d["id"] for d in _evaluar(est, _con_campo(elementos, {"C-04": "region", "P-01": "unidad"})).discrepa}
    brief = {"brief_id": resp_a["brief_id"], "texto": resp_a["brief_recibido"]}
    for c in resp_a["componentes"]:  # I1.5: contrato v2 del experto (motivo_no_valoracion); el resto, real
        c.setdefault("motivo_no_valoracion", "no_aplica")
    resp_a = a_v3(resp_a)  # I1.6: contrato v3 (justificacion_nivel y base_volumen a null)
    errores = i17_int.validar(resp_a, brief, CAT, est["carga"]["briefs"][-1]["perfiles_permitidos"])
    assert any(e.startswith("componentes.C-02: Azure AI Bot Service en global") for e in errores), errores


def test_las_rondas_reales_ya_no_tienen_respalda_en_las_referencias():
    est = _leer(ESTADO_B)
    cons = verificacion.componer_consolidado(est, CAT, "CNS-OF-BREZALIA-001-A-R3")
    lineas = verificacion._lineas({"texto": cons.texto})
    assert all(" | respalda: " not in ln for ln in lineas.values())
    assert lineas["C-02"].endswith("referencia: https://learn.microsoft.com/azure/architecture/ai-ml/architecture/"
                                   "baseline-microsoft-foundry-chat")
    assert verificacion.MARCA_TENANT in lineas["C-07"] and verificacion.MARCA_TENANT in lineas["C-01"]
    # I1.7 (R): sin líneas de precios (ni lote de precios): la anotación de armRegionName solo servía al verificador
    assert not [i for i in lineas if i.startswith("P-")]
