"""I1.7 · D · Datos comunes de las pruebas del papel D: los flujos reconstruidos de I1.6 (pruebas/I17/D/flujos, copia de
C:/tmp/preventa-i16-reverif/flujo_*/lista_A.zip), el catálogo y la tarifa locales, un catálogo con plantillas de GPT-6 y
el esquema textos_cliente propuesto en docs/I1/CAMBIOS-I17-D/textos_cliente.json mientras el integrador no lo aplique."""
from __future__ import annotations

import copy
import json
import pathlib
import sys
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import esquema, hashes, textos_cliente  # noqa: E402

FLUJOS = RAIZ / "pruebas" / "I17" / "D" / "flujos"
PROPUESTO = RAIZ / "docs" / "I1" / "CAMBIOS-I17-D" / "textos_cliente.json"
LITERAL = textos_cliente.PRECIOS_CONSULTADOS


def esquema_propuesto(monkeypatch) -> None:
    """Pone en la caché del núcleo el esquema textos_cliente propuesto si el del repositorio aún no admite «precios
    consultados el» (CAMBIOS-I17-D §4). Con monkeypatch: la caché vuelve a su estado al acabar cada prueba, así que no
    tapa nada a las pruebas de otros papeles. Cuando el integrador lo aplique, no hace nada."""
    ruta = esquema._ruta_esquema("textos_cliente", None)
    if LITERAL in ruta.read_text(encoding="utf-8"):
        return
    propuesto = json.loads(PROPUESTO.read_text(encoding="utf-8"))
    monkeypatch.setitem(esquema._CACHE, ("textos_cliente", str(ruta)), propuesto)


def estado_flujo(caso: str) -> dict:
    with zipfile.ZipFile(FLUJOS / f"flujo_{caso}.zip") as z:
        return json.loads(z.read("estado.json").decode("utf-8"))


def catalogo() -> dict:
    """Integrador I1.7: el catálogo de I1.6 congelado (SHA-256 9ea85f01…ec78e), el de los flujos reales de pruebas/I17/D/flujos
    (respuestas v3 con gpt-5-mini). El catálogo vivo v5 ya declara la retirada de gpt-5-mini (2027-02-09) y trae gpt-6-luna:
    con él, esos flujos no pueden componer textos (lo que el papel D quería probar es el pie y los textos, no el catálogo)."""
    return json.loads((RAIZ / "tests" / "fixtures_i1" / "catalogo_componentes_i16.json").read_text(encoding="utf-8"))


def tarifa() -> dict:
    return json.loads((RAIZ / "tests" / "insumos" / "rate-card.sintetica.json").read_text(encoding="utf-8"))


def recomponer(estado: dict, cat: dict | None = None) -> dict:
    """El estado con textos_cliente compuesto por el núcleo local y su hash_contenido al día (lo que hace `estimar`)."""
    estado = copy.deepcopy(estado)
    estado["carga"]["textos_cliente"] = textos_cliente.componer(estado, cat or catalogo(), tarifa())
    estado["hash_contenido"] = hashes.hash_contenido(estado)
    return estado


FILTRO_GPT6 = ("serviceName eq 'Foundry Models' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' "
               "and meterName eq '6-luna ShortCo {} Std DZ 1M Tokens'")


def catalogo_gpt6(retirada: str | None = None, cat: dict | None = None) -> dict:
    """Catálogo con las plantillas de gpt-6-luna (Retail Prices EUR, swedencentral, comprobadas por el PM el 13-10-2026)
    y su ciclo de vida (Learn no publica aún su retirada: null), como las pide el contrato común (c)."""
    cat = copy.deepcopy(cat or catalogo())
    fila = next(c for c in cat["componentes"] if c["id"] == "az-foundry")
    ciclo = {"ga": "2026-09-22", "retirada": retirada,
             "fuente": "https://learn.microsoft.com/azure/foundry/openai/concepts/model-retirement-schedule"}
    for sufijo, medidor in (("entrada", "Inp"), ("salida", "Opt")):
        fila["plantillas_precio"].insert(0, {"id": f"gpt-6-luna-{sufijo}", "filtro": FILTRO_GPT6.format(medidor),
                                             "concepto": f"6-luna ShortCo {medidor} Std DZ 1M Tokens",
                                             "impulsor": "volumen", "divisor": 1000000, "ciclo_vida": dict(ciclo)})
    return cat


def a_gpt6_v4(estado: dict, override: bool = False) -> dict:
    """Pasa los dos precios de Foundry de un flujo real a gpt-6-luna con la forma v4 que deja el núcleo (CAMBIOS-I17-D
    §3): plantilla_id, factor aplicado y factor_override (null o el del modelo con su cita)."""
    estado = copy.deepcopy(estado)
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    foundry = {c["id"] for c in resp["componentes"] if c.get("catalogo_id") == "az-foundry"}
    for p in resp["precios"]:
        if p["componente_id"] not in foundry:
            continue
        salida = "outpt" in p["filtro"].lower()
        p["plantilla_id"] = "gpt-6-luna-salida" if salida else "gpt-6-luna-entrada"
        p["filtro"] = FILTRO_GPT6.format("Opt" if salida else "Inp")
        p["concepto"] = f"6-luna ShortCo {'Opt' if salida else 'Inp'} Std DZ 1M Tokens"
        p["factor"] = {"valor": 600 if salida else 4000,
                       "unidad": "tokens de salida por consulta" if salida else "tokens de entrada por consulta",
                       "fuente": "catálogo (asistente con RAG)"}
        p["factor_override"] = ({"valor": 600 if salida else 4000, "cita": "Respuestas largas con citas.",
                                 "justificacion": "El cliente pide respuestas largas."} if override else None)
    return estado
