"""I1.6 · papel P: datos comunes de las pruebas de la decisión 4 (no es un fichero de pruebas).

- `catalogo_i16()`: el catálogo del sandbox con el contrato común de la decisión 4 (impulsor y divisor de cada plantilla,
  concepto de las de meterName corto, niveles de Azure AI Search y el auxiliar atado a sus componentes). Mientras el
  papel E no derive el catálogo con esos campos, se completa aquí desde su medición real de I1.5
  (pruebas/I15/EXPERTO/medicion_plantillas.json: unidad, medidor y producto de las 68 plantillas en Retail Prices).
- `NIVELES_AI_SEARCH`: límites de índices de Learn («Service limits in Azure AI Search», consultado el 11-10-2026).
- `paquete_real(x)`: estado.json de los paquetes reales de I1.5 (B y A, Brezalia), leído del ZIP.
- `a_v3(resp)`: la respuesta v2 con las claves nuevas a null (lo que habría devuelto el experto con el esquema v3).
"""
from __future__ import annotations

import copy
import json
import pathlib
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
MEDICION = RAIZ / "tests" / "insumos" / "medicion_plantillas.json"
PAQUETES_REALES = {
    "B": RAIZ / "pruebas" / "I15" / "ARREGLOS" / "REAL" / "B" / "sesion_2" / "OF-BREZALIA-001-A-Paquete.zip",
    "A": RAIZ / "pruebas" / "I15" / "ARREGLOS" / "REAL" / "A" / "descargas" / "OF-BREZALIA-001-A-Paquete.zip"}
# Unidad de Retail Prices → (impulsor, divisor). Lo que se factura por horas, días o meses de un recurso es «tiempo»;
# lo que cuenta mensajes, tokens, páginas, operaciones o GB, «volumen».
UNIDADES = {"1 Hour": ("tiempo", 1), "1/Hour": ("tiempo", 1), "1/Month": ("tiempo", 1), "1/Day": ("tiempo", 1),
            "1 GiB Hour": ("tiempo", 1), "1": ("volumen", 1), "1 GB": ("volumen", 1), "1 GB/Month": ("volumen", 1),
            "1K": ("volumen", 1000), "10K": ("volumen", 10000), "1M": ("volumen", 1000000)}
FUENTE_LIMITES = "https://learn.microsoft.com/azure/search/search-limits-quotas-capacity"
NIVELES_AI_SEARCH = [
    {"nivel": "basic", "plantillas": ["basic"], "limites": ["Maximum indexes: 5 or 15"], "fuente_url": FUENTE_LIMITES,
     "consultado": "2026-10-11"},
    {"nivel": "s1", "plantillas": ["s1"], "limites": ["Maximum indexes: 50"], "fuente_url": FUENTE_LIMITES,
     "consultado": "2026-10-11",
     # I1.9 (VC18-1): subir de basic exige una razón de la lista cerrada del nivel y la cita que la cumple (prueba)
     "razones_subida": [{"id": "documentos_sobre_basic", "tipo": "umbral", "campo": "volumetria",
                         "unidad": ["documentos"], "limite": 2000, "fuente": FUENTE_LIMITES},
                        {"id": "indices_sobre_basic", "tipo": "caracteristica", "palabras_clave": ["más de 15 índices"],
                         "fuente": FUENTE_LIMITES}]}]
# I1.9 (VC18-1): el nivel por defecto de AI Search en las pruebas, con su fuente
POR_DEFECTO_AI_SEARCH = {"nivel": "basic", "fuente": FUENTE_LIMITES}


def medicion() -> dict:
    """{(componente, plantilla): comprobacion} de la medición real de E."""
    datos = json.loads(MEDICION.read_text(encoding="utf-8"))
    return {(r["componente"], r["plantilla"]): r["comprobacion"] for r in datos["resultados"]}


def catalogo_i16(base: dict | None = None, niveles: bool = True, modelo_por_defecto: str | None = None) -> dict:
    cat = copy.deepcopy(base) if base is not None else json.loads(
        (RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    med = medicion()
    for e in cat["componentes"]:
        for p in e.get("plantillas_precio") or []:
            k = med.get((e["id"], p["id"]))
            if k is None:
                continue
            impulsor, divisor = UNIDADES[k["unidad"]]
            p.setdefault("impulsor", impulsor)
            p.setdefault("divisor", divisor)
            if len(k["medidor"]) < 3:
                p.setdefault("concepto", f"{k['medidor']} ({k['producto']})")
        # Integrador I1.6: el catálogo derivado de E ya trae niveles reales en 8 servicios. Con niveles=True, las pruebas
        # de las reglas se aíslan de los textos del catálogo con niveles de prueba fijos (AI Search con
        # NIVELES_AI_SEARCH y ningún otro servicio con niveles); con niveles=False, los niveles reales tal cual. Los
        # niveles reales con los casos de I1.5 se prueban en tests/test_i16_int_catalogo_real.py.
        if niveles:
            e.pop("niveles", None)
            if e["id"] == "az-ai-search":
                e["niveles"] = copy.deepcopy(NIVELES_AI_SEARCH)
                e["nivel_por_defecto"] = dict(POR_DEFECTO_AI_SEARCH)
    for a in cat.get("precios_auxiliares") or []:  # contrato de E (INT15-3): plantillas_de + plantillas + componentes
        if a.get("service_name") == "Azure Private Link":
            a["plantillas_de"], a["plantillas"] = "az-private-link", ["punto-conexion"]
            # integrador I1.6: lista de prueba fija (el catálogo real de E la amplía a 24, Cosmos DB incluido)
            a["componentes"] = ["az-app-service", "az-ai-search", "az-storage", "az-foundry"]
    # I1.9 (VC18-5): estas pruebas de I1.6 valoran gpt-5 (el modelo de su época) y no prueban la regla del modelo: en su
    # catálogo de prueba, gpt-5 es el modelo por defecto (la regla del modelo se prueba en tests/test_i19_p_niveles.py)
    if modelo_por_defecto and isinstance(cat.get("modelo_por_defecto"), dict):
        cat["modelo_por_defecto"] = dict(cat["modelo_por_defecto"], modelo=modelo_por_defecto)
    return cat


def paquete_real(x: str) -> dict:
    with zipfile.ZipFile(PAQUETES_REALES[x]) as z:
        return json.loads(z.read("estado.json").decode("utf-8"))


def a_v3(resp: dict) -> dict:
    r = copy.deepcopy(resp)
    for c in r["componentes"]:
        c.setdefault("justificacion_nivel", None)
    for p in r["precios"]:
        p.setdefault("base_volumen", None)
    return con_referencias_del_catalogo(r)


def con_referencias_del_catalogo(r: dict) -> dict:
    """Arreglos I1.6 (PR16-1): la referencia de cada componente del catálogo es la `referencia_url` de su fila; se añade
    la referencia si la respuesta no la trae (las respuestas reales de I1.5 respaldaban servicios con páginas ajenas)."""
    cat = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    filas = {e["id"]: e for e in cat["componentes"]}
    por_url = {x["url"].rstrip("/"): x["id"] for x in r["referencias"]}
    for c in r["componentes"]:
        fila = filas.get(c.get("catalogo_id"))
        if fila is None:
            continue
        url = fila["referencia_url"]
        if url.rstrip("/") not in por_url:
            rid = f"REF-{len(r['referencias']) + 1:02d}"
            r["referencias"].append({"id": rid, "url": url, "titulo": f"Documentación de {fila['nombre_oficial']}",
                                     "fecha_consulta": r["referencias"][0]["fecha_consulta"]})
            por_url[url.rstrip("/")] = rid
        c["referencia_id"] = por_url[url.rstrip("/")]
    return r


def brief_de(estado: dict, brief_id: str) -> dict:
    return next(b for b in estado["carga"]["briefs"] if b["brief_id"] == brief_id)
