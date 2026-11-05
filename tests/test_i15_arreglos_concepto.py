"""Arreglos I1.5, VER15-1: el `concepto` que exige el núcleo viaja donde el experto lo copia.

1. Bloque de plantillas (tests/test_i15_plantillas_precio.py): «(concepto «…»)» si el meterName tiene < 3 caracteres.
2. Brief de las rondas 2 y 3: cada línea de «Precios ya verificados» acaba en `| concepto: …`, el que el núcleo ya
   aceptó. En real (B, sesión 9e94e116…180) R1 y R2 escribieron bien el concepto y R3, con un brief sin él, «B1».
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from tests.test_i13_convergencia import OTRA, m  # noqa: F401  (fixture del mundo con el catálogo real)
from tests.test_i1_verificacion_lotes import _cons, _registrar, _resp

from nucleo import anexo_consumo, verificacion  # noqa: E402,F401  (el anexo_consumo real, antes que los dobles de Mundo)
from nucleo.errores import IntegridadRota  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[1]
EXPERTO = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md").read_text(encoding="utf-8")
REAL_B = RAIZ / "pruebas" / "I15" / "ARREGLOS" / "REAL" / "B" / "sesion_1"
DISCREPA_C02 = {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": OTRA}}


def _ronda_2(m):  # noqa: F811
    m.hasta_verificacion()
    c = _cons(m)
    rc, _ = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"], DISCREPA_C02))
    assert rc == 1


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): la línea P- del brief llevaba el concepto que el modelo copiaba; imposible por construcción con el contrato v4. Lo vigente: la línea P- lleva plantilla, instancias, base y factor (tests/test_i17_r_conservacion.py)")
def test_el_brief_de_la_ronda_2_lleva_el_concepto_de_cada_precio_conservado(m):  # noqa: F811
    _ronda_2(m)
    resp = m.estado()["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    assert m.run("enrutar")[0] == 0
    b = m.estado()["carga"]["briefs"][-1]
    lineas_p = [ln for ln in b["conservar"] if ln.startswith("P-")]
    # I1.7 (R): las líneas P- salen de la respuesta registrada y solo las de componentes sin corrección (C-02 tiene una)
    libres = [p for p in resp["precios"] if p["componente_id"] != "C-02"]
    assert b["ronda"] == 2 and len(lineas_p) == len(libres) >= 1
    for p in libres:
        ln = next(x for x in lineas_p if x.startswith(p["id"] + " | "))
        # PR16-3 (arreglos I1.6): tras el concepto van la cantidad mensual y, si la tiene, la base con su factor
        assert f" | concepto: {p['concepto']} | cantidad_mensual: " in ln and f" | filtro: {p['filtro']} | " in ln
        assert f"- {ln}" in b["texto"].split("## Precios conservados", 1)[1]
    assert m.run("enrutar")[0] == 0 and m.estado()["carga"]["briefs"][-1] == b  # sigue siendo idempotente


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): un precio conservado sin filtro: desde I1.7 se conserva por plantilla y el núcleo pone el filtro; imposible por construcción con el contrato v4. Lo vigente: precio sin plantilla ni filtro → IntegridadRota en tests/test_i17_r_decision.py")
@pytest.mark.parametrize("rotura", ["sin_filtro", "filtro_vacio"])
def test_integridad_rota_si_el_precio_conservado_no_casa_con_la_respuesta(m, rotura):  # noqa: F811
    # I1.7 (R): la línea sale de la respuesta registrada, así que ya no puede «no casar» con el consolidado; lo que no
    # se puede conservar es un precio sin plantilla_id ni filtro, y eso es IntegridadRota (nunca en silencio).
    _ronda_2(m)
    est = copy.deepcopy(m.estado())
    precios = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]["precios"]
    libre = next(p for p in precios if p["componente_id"] != "C-02")
    libre["filtro"] = None if rotura == "sin_filtro" else ""
    with pytest.raises(IntegridadRota, match="sin plantilla_id ni filtro"):
        verificacion.lineas_conservar(est)


def test_la_regla_5_del_experto_manda_copiar_el_concepto_de_la_linea():
    regla = next(ln for ln in EXPERTO.splitlines() if ln.startswith("5. **Rondas 2 y 3**"))
    # I1.7 (CAMBIOS-I17-E §5): el experto no escribe concepto; conserva plantilla, instancias, base y factor_override.
    assert "la misma plantilla, `instancias`, `base_volumen` y `factor_override`" in regla and "concepto" not in regla


@pytest.mark.skipif(not (REAL_B / "estado.json").exists(), reason="sin el estado real de la prueba de los arreglos")
def test_con_el_estado_real_de_la_ronda_3_la_linea_de_b1_lleva_el_concepto_aceptado():
    """Datos reales (LES-G-078): consolidado, verificación y respuesta R2 de B. La línea P-02 (`meterName eq 'B1'`)
    lleva el concepto que el núcleo aceptó en R1 y R2; el brief R3 que se envió no lo llevaba."""
    est = json.loads((REAL_B / "estado.json").read_text(encoding="utf-8"))
    p02 = next(ln for ln in verificacion.lineas_conservar(est) if ln.startswith("P-02 | "))
    assert p02.endswith("meterName eq 'B1' | unidad: 1 Hour | region: swedencentral"
                        " | concepto: B1 (Azure App Service Basic Plan - Linux) | cantidad_mensual: 730")  # PR16-3
    enviado = next(b for b in est["carga"]["briefs"] if b["brief_id"].endswith("-R3"))
    assert not any("concepto" in ln for ln in enviado["conservar"] if ln.startswith("P-"))
