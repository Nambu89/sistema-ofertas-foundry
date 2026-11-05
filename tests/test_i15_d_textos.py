"""I1.5 · D · PR14-4, VER14-8 y VER14-10: rótulos en una sola viñeta con minúscula tras los dos puntos, «en» al
traducir un tipo de despliegue tras un nombre, el plazo que cita el experto sale del Gantt y las asunciones del
XLSX las compone el código sin jerga. Sin red."""
from __future__ import annotations

import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import textos_cliente as tc  # noqa: E402


@pytest.mark.parametrize("valor, esperado", [
    ("Los datos tienen que quedarse en la Unión Europea", "los datos tienen que quedarse en la Unión Europea"),
    ("RGPD", "RGPD"), ("España; plantas de Valladolid", "España; plantas de Valladolid"),
    ("Unión Europea", "Unión Europea"), ("Asistente de IA", "Asistente de IA"), ("A partir de mayo", "a partir de mayo"),
    ("Está sujeto al ENS", "está sujeto al ENS"), ("HIPAA", "HIPAA"), ("", ""),
])
def test_minuscula_inicial(valor, esperado):
    assert tc.minuscula_inicial(valor) == esperado


def test_etiquetadas_una_vineta_sin_repetir_y_sin_doble_punto():
    caso = tc.etiquetadas("Marco normativo", ["RGPD.", "Los datos tienen que quedarse en la Unión Europea.", "rgpd"],
                          "R-marco_normativo", "requisito marco_normativo")
    assert caso == [("Marco normativo: RGPD; los datos tienen que quedarse en la Unión Europea.",
                     ["R-marco_normativo"], "requisito marco_normativo")]
    assert tc.etiquetadas("Usuarios finales", ["EE. UU."], "h", "o")[0][0] == "Usuarios finales: EE. UU."
    largos = tc.etiquetadas("Objetivo", ["x" * 250, "y" * 250], "h", "o")  # no caben juntos: dos viñetas, nada perdido
    assert len(largos) == 2 and all(t.startswith("Objetivo: ") and len(t) <= 400 for t, _, _ in largos)
    assert tc.etiquetadas("Objetivo", [], "h", "o") == []


@pytest.mark.parametrize("texto, semanas, esperado, motivo", [
    ("El plazo de ocho semanas y el presupuesto podrían verse afectados.", 5,
     "El plazo de cinco semanas y el presupuesto podrían verse afectados.", False),
    ("La duración prevista de unas 8 semanas depende del acceso.", 1, "La duración prevista de una semana depende del acceso.", False),
    ("El plazo de cinco semanas es ajustado.", 5, "El plazo de cinco semanas es ajustado.", False),
    ("La aprobación de Microsoft puede tardar dos semanas.", 5, None, True),
    ("El plazo de dos meses es ajustado.", 5, None, True),
    ("El plazo de ocho semanas y otras dos semanas de margen.", 5, None, True),
    ("Sin plazos en esta frase.", 5, "Sin plazos en esta frase.", False),
    ("El plazo de ocho semanas.", None, None, True),
    ("El proyecto durará veinticuatro semanas.", 5, None, True),             # revisión independiente: más de veinte
    ("El plazo de 1000 semanas.", 5, "El plazo de cinco semanas.", False),   # sin tope de cifras
    ("Una garantía de 1.000 semanas.", 5, None, True),
    ("Un plan de treinta y dos semanas.", 5, None, True),
    ("La duración de veinticinco semanas.", 25, "La duración de 25 semanas.", False),
    ("El plazo de 5,5 semanas.", 5, None, True),                               # segunda pasada de la revisión independiente
    ("Un plan de treinta y dos semanas.", 2, None, True),
    ("Un plan de ciento veinte semanas.", 20, None, True),
    ("Unas cinco coma cinco semanas de trabajo.", 5, None, True),             # tercera pasada de la revisión independiente
    ("Las semanas 3 y 4 son de pruebas.", 5, "Las semanas 3 y 4 son de pruebas.", False),
])
def test_plazo_del_gantt(texto, semanas, esperado, motivo):
    nuevo, porque = tc.plazo_del_gantt(texto, semanas)
    assert bool(porque) is motivo, porque
    if esperado is not None:
        assert nuevo == esperado


@pytest.mark.parametrize("texto, esperado", [
    ("El modelo GPT-5 DataZoneStandard y la selección de regiones deben validarse.",
     "El modelo GPT-5 en un despliegue que procesa los datos solo dentro del Límite de datos de la UE y la "
     "selección de regiones deben validarse."),
    ("Se usa el despliegue DataZoneStandard del modelo.",
     "Se usa un despliegue que procesa los datos solo dentro del Límite de datos de la UE del modelo."),
    ("Con DataZoneStandard se cumple la residencia.",
     "Con un despliegue que procesa los datos solo dentro del Límite de datos de la UE se cumple la residencia."),
    ("DataZoneStandard es obligatorio.",
     "Un despliegue que procesa los datos solo dentro del Límite de datos de la UE es obligatorio."),
    ("El DataZoneStandard es obligatorio.",
     "Un despliegue que procesa los datos solo dentro del Límite de datos de la UE es obligatorio."),
    ("Usamos DataZoneStandard.", "Usamos un despliegue que procesa los datos solo dentro del Límite de datos de la UE."),
    ("Se elige Microsoft Foundry DataZoneStandard.",
     "Se elige Microsoft Foundry en un despliegue que procesa los datos solo dentro del Límite de datos de la UE."),
])
def test_traducir_skus_concuerda(texto, esperado):
    assert tc.traducir_skus(texto, ["swedencentral"]) == esperado


def _resp():
    comps = [{"id": f"C-0{i}", "servicio": n, "region": "swedencentral", "sku": s} for i, (n, s) in enumerate(
        [("Azure App Service", "B1"), ("Microsoft Foundry", "GPT-5 DataZoneStandard"), ("Azure AI Search", "S1")], 1)]
    return {"componentes": comps, "supuestos": [
        {"id": "S-01", "texto": "La suscripción permite el modelo GPT-5 seleccionado.", "hechos": ["C-02"]},
        {"id": "S-02", "texto": "Los costes de Azure App Service, Microsoft Foundry y Azure AI Search están NO "
                                "VERIFICADO en Azure Retail Prices para esta estimación.", "hechos": ["C-01", "C-02", "C-03"]},
        {"id": "S-03", "texto": "El coste de Azure AI Search está NO VERIFICADO.", "hechos": ["C-03"]},
        {"id": "S-04", "texto": "El piloto de ocho semanas basta.", "hechos": ["C-01"]},
        {"id": "S-05", "texto": "Todo queda NO VERIFICADO por el verificador.", "hechos": ["C-01"]},
        {"id": "S-06", "texto": "El modelo GPT-5 DataZoneStandard está disponible", "hechos": ["C-02"]},
    ]}


def test_asunciones_estimacion_sin_jerga_y_con_concordancia():
    asunciones, avisos = tc.asunciones_estimacion(_resp(), 5)
    assert asunciones == [
        "La suscripción permite el modelo GPT-5 seleccionado.",
        "No se han podido comprobar en Azure Retail Prices los precios de consumo de Azure App Service, Microsoft "
        "Foundry y Azure AI Search.",
        "No se ha podido comprobar en Azure Retail Prices el precio de consumo de Azure AI Search.",
        "El piloto de cinco semanas basta.",
        "El modelo GPT-5 en un despliegue que procesa los datos solo dentro del Límite de datos de la UE está disponible.",
    ]
    assert not any("NO VERIFICADO" in a or "DataZone" in a for a in asunciones)
    assert any("S-05" in a and "omitida" in a for a in avisos)          # redacción interna sin precio: fuera y avisada
    assert sum("recompuesta" in a for a in avisos) == 2


def test_asunciones_estimacion_caso_real_de_i14():
    import json
    estado = RAIZ / "pruebas" / "I14" / "REAL" / "B" / "sesion_n" / "estado.json"
    datos = json.loads(estado.read_text(encoding="utf-8"))
    resp = ((datos.get("carga") or {}).get("respuestas_expertos") or {}).get("azure", {}).get("respuesta")
    if not resp:
        pytest.skip("el estado de la sesión real no trae la respuesta del experto")
    asunciones, _ = tc.asunciones_estimacion(resp, 5)
    assert asunciones and not any(tc.redaccion_interna(a) for a in asunciones)
