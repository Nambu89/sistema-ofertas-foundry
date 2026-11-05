"""I1.9 · D · Datos comunes de las pruebas del papel D: los estados y paquetes reales de la prueba real de I1.8
(pruebas/I18/REAL/B: Brezalia final APROBADA y versión B LISTA, Hostelia LISTA A), una copia congelada del catálogo con
el que se generaron y Hostelia con el contrato común de I1.9 simulado (recursos del cliente con `EX-nn` y
`existente_del_cliente`, como los dejarán E y P)."""
from __future__ import annotations

import copy
import io
import json
import pathlib
import sys
import zipfile
from decimal import Decimal

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

REAL = RAIZ / "pruebas" / "I18" / "REAL" / "B"
CATALOGO = RAIZ / "tests" / "fixtures_i19_d" / "catalogo_componentes_i18.json"
TARIFA = RAIZ / "tests" / "insumos" / "rate-card.sintetica.json"
CASOS = {"brezalia_final": REAL / "sesion_2" / "final", "brezalia_lista_B": REAL / "sesion_2" / "lista_B",
         "hostelia_lista_A": REAL / "hostelia_1" / "lista_A"}


def catalogo() -> dict:
    return json.loads(CATALOGO.read_text(encoding="utf-8"))


def tarifa() -> dict:
    return json.loads(TARIFA.read_text(encoding="utf-8"))


def estado_real(caso: str) -> dict:
    return copy.deepcopy(json.loads((CASOS[caso] / "estado.json").read_text(encoding="utf-8")))


def partes_publicadas(caso: str) -> dict:
    """Partes del PPTX que se publicó en la prueba real de I1.8."""
    from tests.evidencias import requerir
    requerir(CASOS[caso])
    zips = sorted(CASOS[caso].glob("*-Paquete.zip"))
    with zipfile.ZipFile(zips[0]) as paquete:
        nombre = next(n for n in paquete.namelist() if n.endswith(".pptx"))
        datos = paquete.read(nombre)
    with zipfile.ZipFile(io.BytesIO(datos)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def contrato_i19_hostelia(estado: dict) -> dict:
    """Hostelia con lo que dirá el alta de I1.9: una entrada por recurso, con su cita literal entera, y los componentes
    que SON recursos del cliente declarados como tales, sin precio. La API de RR. HH. pasa a ser un componente (PR18-8)."""
    e = copy.deepcopy(estado)
    campos = e["carga"]["requisitos"]["campos"]
    cita_m365 = campos["ya_contratado_por_cliente"]["entradas"][0]["cita"]
    cita_api = campos["ya_contratado_por_cliente"]["entradas"][1]["cita"]
    campos["ya_contratado_por_cliente"]["entradas"] = [
        {"id": "EX-01", "servicio_catalogo": "az-teams", "valor": "Teams", "cita": cita_m365, "fuente": "F1",
         "origen": "CITADO"},
        {"id": "EX-02", "servicio_catalogo": "az-sharepoint", "valor": "SharePoint", "cita": cita_m365, "fuente": "F1",
         "origen": "CITADO"},
        {"id": "EX-03", "servicio_catalogo": "az-app-service", "valor": "la API REST de RR. HH.", "cita": cita_api,
         "fuente": "F1", "origen": "CITADO"},
        {"id": "EX-04", "servicio_catalogo": "az-api-management", "valor": "API Management", "cita": cita_api,
         "fuente": "F1", "origen": "CITADO"}]
    resp = e["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    marca = {"C-01": "EX-01", "C-07": "EX-02", "C-06": "EX-04"}
    for c in resp["componentes"]:
        c["existente_del_cliente"] = {"entrada": marca[c["id"]]} if c["id"] in marca else None
        if c["id"] in marca:
            c["motivo_no_valoracion"], c["motivo_cita"] = "existente_del_cliente", None
    app = next(c for c in resp["componentes"] if c["id"] == "C-03")
    resp["componentes"].append({**copy.deepcopy(app), "id": "C-09", "existente_del_cliente": {"entrada": "EX-03"},
                                "motivo_no_valoracion": "existente_del_cliente", "motivo_cita": None})
    resp["flujos"].append({"origen": "C-06", "destino": "C-09", "descripcion": "API Management publica la API de RR. HH."})
    resp["precios"] = [p for p in resp["precios"] if p.get("componente_id") != "C-06"]
    anexo = e["carga"]["anexo_consumo"]
    anexo["lineas"] = [x for x in anexo["lineas"] if x.get("componente_id") != "C-06"]
    total = sum(Decimal(x["coste_mensual_eur"]) for x in anexo["lineas"])
    anexo["total_mensual_eur"], anexo["total_anual_eur"] = f"{total:.2f}", f"{total * 12:.2f}"
    return e


def recomponer(estado: dict) -> dict:
    """textos_cliente recompuesto con el núcleo nuevo, como haría `estimar`, y la huella del contenido recalculada (no es
    el paquete firmado). Las decisiones que citaban la huella vieja pasan a citar la nueva (simulación declarada)."""
    from nucleo import hashes, textos_cliente as tc
    estado["carga"]["textos_cliente"] = tc.componer(estado, catalogo(), tarifa())
    viejo = estado.get("hash_contenido")
    estado["hash_contenido"] = hashes.hash_contenido(estado)
    for d in estado.get("decisiones") or []:
        if d.get("hash_citado") == viejo:
            d["hash_citado"] = estado["hash_contenido"]
    return estado
