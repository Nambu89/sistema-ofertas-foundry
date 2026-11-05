"""CMP-1 / VER13-1 (I1.3): convergencia de la verificación (EA-4 y EB-2).

Cubre: residencia por geografía del tenant como OBSERVACION, DISCREPA cuyo valor correcto es lo enviado como
OBSERVACION, referencia juzgada componente a componente, bot «global» vetado, brief que conserva lo verificado,
réplica de la puerta igual al núcleo y la repetición sobre las rondas 3 reales de A y de B.
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

from tests.test_i1_estado_comun import Mundo, ejemplo
from tests.test_i1_verificacion_lotes import _cons, _registrar, _resp, _todos_los_lotes

from nucleo import experto, verificacion  # noqa: E402
import verificar_paquete as vp  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
ENTRA_DR = "https://learn.microsoft.com/entra/fundamentals/data-residency"
SPO_DR = "https://learn.microsoft.com/microsoft-365/enterprise/m365-dr-service-spo"
OTRA = "https://learn.microsoft.com/azure/search/search-sku-tier"
M = verificacion.MARCA_TENANT
LINEAS = [
    f"C-07 | Microsoft Entra ID | sku: Microsoft Entra ID Free | region: global {M} | referencia: {ENTRA_DR}",
    "C-06 | desviación: SharePoint in Microsoft 365 | sku: SharePoint Online | region: global | referencia: " + SPO_DR,
    "C-04 | Azure AI Search | sku: Basic | region: francecentral | referencia: " + OTRA,
    "C-03 | Azure App Service | sku: B1 | region: global | referencia: https://learn.microsoft.com/azure/app-service/overview",
    "REF-05 | https://learn.microsoft.com/microsoftteams/platform/overview | Microsoft Teams developer platform overview",
    "C-08 | desviación: Azure Front Door | sku: Standard | region: global | referencia: https://learn.microsoft.com/azure/frontdoor/front-door-overview",
]


@pytest.fixture
def m(tmp_path, monkeypatch):
    """El mundo de I1 con el catálogo REAL montado (el del ejemplo no lleva la residencia por tenant ni el veto)."""
    mundo = Mundo(tmp_path, monkeypatch)
    mundo.usar_catalogo_real()  # integrador I1.7: catálogo real con su instantánea de precios
    mundo.hasta_verificacion = lambda: _hasta_verificacion(mundo)
    return mundo


def _hasta_verificacion(m) -> None:
    """Como Mundo.hasta_verificacion, con el eco del brief que genera el catálogo real (otro catalogo_sha256)."""
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    resp = ejemplo("respuesta_experto")
    b = m.estado()["carga"]["briefs"][-1]
    resp["brief_recibido"], resp["brief_id"] = b["texto"], b["brief_id"]
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada("e1.json", resp))
    assert rc == 0, out
    assert m.run("consolidar")[0] == 0


@pytest.mark.parametrize("linea, fuente, esperado", [
    (LINEAS[0], ENTRA_DR, True), (LINEAS[0], ENTRA_DR + "#core-store", True), (LINEAS[1], SPO_DR, True),
    (LINEAS[1], "https://learn.microsoft.com/es-es/microsoft-365/enterprise/m365-dr-service-spo?view=o365-worldwide", True),
    (LINEAS[0], OTRA, False), (LINEAS[2], ENTRA_DR, False), (LINEAS[3], ENTRA_DR, False), (LINEAS[4], ENTRA_DR, False),
    (LINEAS[0], "https://example.com/entra/fundamentals/data-residency", False), (LINEAS[0], None, False),
    (LINEAS[5], SPO_DR, False),  # Revisión: una desviación que no es de Microsoft 365 sigue bloqueando
    (LINEAS[0], "https://learn.microsoft.com/entra/fundamentals/data-residency-falso", False),
    (LINEAS[1], "https://learn.microsoft.com/microsoft-365/enterprise/m365-dr", False)])
def test_residencia_por_tenant_solo_con_marca_o_desviacion_y_fuente_de_residencia(linea, fuente, esperado):
    # I1.4 (ARR13-4): la DISCREPA tiene que declarar el campo «region». La igualdad con la réplica de la puerta
    # (firma nueva, con campo) está en tests/test_i14_p3_verificacion.py.
    assert verificacion.es_residencia_tenant(linea, fuente, "region") is esperado
    assert verificacion.es_residencia_tenant(linea, fuente, "sku") is False


@pytest.mark.parametrize("linea, valor, esperado", [
    (LINEAS[2], "Azure AI Search", True), (LINEAS[2], "azure  ai-search", True),
    (LINEAS[2], "Basic", False), (LINEAS[2], "francecentral", False),  # Revisión: solo el nombre oficial del catálogo
    (LINEAS[1], "SharePoint in Microsoft 365", False), (LINEAS[1], "desviación: SharePoint in Microsoft 365", False),
    (LINEAS[2], "Azure AI Search Standard S1", False), (LINEAS[2], "AI Search", False), (LINEAS[2], None, False),
    (LINEAS[4], "Título: Microsoft Teams developer platform overview", True),
    (LINEAS[4], "Microsoft Teams developer platform", False), (LINEAS[2], "", False), ("basura", "Basic", False)])
def test_valor_correcto_igual_a_lo_enviado(linea, valor, esperado):
    # I1.4 (ARR13-4): solo con el campo que corresponde a la línea («nombre» o «titulo»); con otro campo, nunca.
    campo = "titulo" if str(linea).startswith("REF-") else "nombre"
    assert verificacion.valor_es_lo_enviado(linea, valor, campo) is esperado
    assert verificacion.valor_es_lo_enviado(linea, valor, "region") is False


def test_constantes_de_la_replica_iguales_al_nucleo():
    assert vp.MARCA_TENANT == verificacion.MARCA_TENANT
    assert vp.FUENTES_RESIDENCIA_TENANT == verificacion.FUENTES_RESIDENCIA_TENANT


def test_consolidado_marca_tenant_bot_regional_y_referencia_por_componente(m):
    m.hasta_verificacion()
    lineas = verificacion._lineas(_cons(m))
    assert lineas["C-05"].startswith("C-05 | Microsoft Entra ID |") and f"region: global {M}" in lineas["C-05"]
    # integrador I1.7 (CAMBIOS-I17-E §3.5): el motivo de no valoración va en la línea, antes de la referencia
    assert ("region: westeurope | motivo: depende_del_volumen | referencia: https://learn.microsoft.com/azure/bot-service/"
            in lineas["C-03"])
    assert all(" | respalda: " not in ln for i, ln in lineas.items() if i.startswith("REF-"))


def test_bot_global_se_rechaza_al_registrar_al_experto():
    resp, br = ejemplo("respuesta_experto"), ejemplo("brief")
    next(c for c in resp["componentes"] if c["id"] == "C-03")["region"] = "global"
    errores = i17_int.validar(resp, br, CAT, br["perfiles_permitidos"])
    assert any(e.startswith("componentes.C-03: Azure AI Bot Service en global") and "westeurope" in e for e in errores)


def test_sin_aviso_fuera_de_catalogo_en_global():
    comp = {"id": "C-09", "catalogo_id": None, "servicio": "SharePoint Online", "region": "global"}
    assert experto.aviso_fuera_de_catalogo(comp, CAT, []) is None
    assert vp.aviso_fuera_de_catalogo(comp, CAT, []) is None


def test_entra_global_con_fuente_de_residencia_no_bloquea_y_va_a_observaciones(m):
    m.hasta_verificacion()
    cambios = {"C-05": {"veredicto": "DISCREPA", "campo": "region", "valor_correcto": "Geografía UE del tenant",
                        "fuente_url": ENTRA_DR}}
    rc, out = _todos_los_lotes(m, cambios)
    assert rc == 0 and "estado: VERIFICADA" in out, out
    ver = m.estado()["carga"]["verificacion"]
    assert [o["id"] for o in ver["observaciones"]] == ["C-05"] and ver["resultado"]["discrepa"] == []


def test_discrepa_de_entra_con_otra_fuente_sigue_bloqueando(m):
    m.hasta_verificacion()
    cambios = {"C-05": {"veredicto": "DISCREPA", "campo": "region", "valor_correcto": "Microsoft Entra ID P1",
                        "fuente_url": OTRA}}
    rc, out = _todos_los_lotes(m, cambios)
    assert rc == 1 and "estado: EN_ANALISIS" in out, out


def test_brief_de_la_ronda_2_conserva_lo_verificado(m):
    m.hasta_verificacion()
    c = _cons(m)
    linea_c02 = verificacion._lineas(c)["C-02"]
    rc, _ = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"],
                                {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": OTRA}}))
    assert rc == 1 and m.run("enrutar")[0] == 0
    b = m.estado()["carga"]["briefs"][-1]
    assert b["ronda"] == 2 and linea_c02 not in b["conservar"]
    # PR14-1 (I1.4): también los precios, con su filtro y sin importe ni fecha. I1.7 (R): el consolidado ya no lleva
    # precios; las líneas P- salen de la respuesta registrada, las de los componentes sin corrección.
    resp = m.estado()["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    libres = {p["id"] for p in resp["precios"] if p["componente_id"] != "C-02"}
    assert {ln.split(" |")[0] for ln in b["conservar"]} == (set(c["ids"]) - {"C-02"}) | libres
    assert all("precio:" not in ln and "effectiveStartDate" not in ln for ln in b["conservar"] if ln.startswith("P-"))
    seccion = b["texto"].split("## Elementos ya verificados", 1)[1]
    assert all(f"- {ln}" in seccion for ln in b["conservar"])
    assert m.run("enrutar")[0] == 0 and m.estado()["carga"]["briefs"][-1] == b  # idempotente


# --- VER13-1: procedencia por lote en la puerta (la respuesta combinada nunca viaja por A2A) ---

def _ctx_procedencia(est: dict, kql):
    import types
    conexiones = lambda: [{"properties": {"target": "/subscriptions/x/components/appi-preventa-ejemplo"}}]
    # REV15-2 (I1.6): una respuesta v2 sin marca de orquestador FALLA; estas pruebas son de la vía de A (sin fichero).
    return types.SimpleNamespace(sin_red=False, conexiones_appi=conexiones, consultar_kql=kql, carga=est["carga"],
                                 respuesta=est["carga"]["respuestas_expertos"]["azure"]["respuesta"],
                                 estado={"orquestador": "A"}, manifiesto={"orquestador": "A"})


def _kql_con(est: dict, alterar: str | None = None, faltar: str | None = None):
    lotes = {x["lote_id"]: x["respuesta"] for x in est["carga"]["consolidado"]["lotes"]}

    def kql(consulta: str):
        if "BRF-" in consulta:
            r = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
        else:
            lid = next(i for i in lotes if f"'{i}'" in consulta or f'"{i}"' in consulta)
            if lid == faltar:
                return []
            r = copy.deepcopy(lotes[lid])
            if lid == alterar:
                r["elementos"][0]["detalle"] += " (alterado)"
        return [{"name": "invoke_agent", "dims": json.dumps({"gen_ai.output": json.dumps(r, ensure_ascii=False)})}]
    return kql


def test_procedencia_por_lote_ok_alterado_y_ausente(m):
    m.hasta_verificacion()
    assert _todos_los_lotes(m)[0] == 0
    est = m.estado()
    ids = [x["lote_id"] for x in est["carga"]["consolidado"]["lotes"]]
    c = vp.c_procedencia(_ctx_procedencia(est, _kql_con(est)))
    assert c.estado == vp.OK and sum("coincide con la del estado" in d for d in c.detalles) == 1 + len(ids), c.detalles
    c = vp.c_procedencia(_ctx_procedencia(est, _kql_con(est, alterar=ids[1])))
    assert c.estado == vp.FALLA and any(ids[1] in d and "compatible" in d for d in c.detalles), c.detalles
    c = vp.c_procedencia(_ctx_procedencia(est, _kql_con(est, faltar=ids[-1])))
    assert c.estado == vp.NOV and any(ids[-1] in d for d in c.detalles), c.detalles
    roto = copy.deepcopy(est)
    roto["carga"]["consolidado"]["lotes"][0]["respuesta"] = None
    c = vp.c_procedencia(_ctx_procedencia(roto, _kql_con(est)))
    assert c.estado == vp.FALLA, c.detalles


# --- VER13-1: lo que destapó el primer paquete real de B en la puerta ---

def _fila_b(resp: dict, truncar: bool = False, op: str = "op-1") -> dict:
    """Como el span «chat» del verificador en las trazas de B: dims → output.messages → parts → content."""
    contenido = json.dumps(resp, ensure_ascii=False)
    if truncar:
        contenido = contenido[:300] + "... [TRUNCATED]"
    salida = json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": contenido}]}], ensure_ascii=False)
    entrada = json.dumps([{"role": "user", "parts": [{"type": "text", "content": "consolidado_id: X [TRUNCATED]"}]}])
    return {"name": "chat", "op": op,
            "dims": json.dumps({"gen_ai.output.messages": salida, "gen_ai.input.messages": entrada})}


def test_salida_truncada_solo_si_lo_truncado_es_la_salida():
    lid = "CNS-OF-BREZALIA-001-A-R2-L1"
    completa = json.dumps({"agente": "x", "consolidado_id": lid, "elementos": [{"id": "REF-01", "detalle": "y" * 50}]})
    assert vp.salida_truncada(completa[:-30] + "... [TRUNCATED]", "consolidado_id", lid)
    assert not vp.salida_truncada(completa, "consolidado_id", lid)  # completa
    assert not vp.salida_truncada(f"lote: consolidado_id: {lid} ... [TRUNCATED]", "consolidado_id", lid)  # entrada
    assert not vp.salida_truncada(completa.replace(lid, lid + "0")[:-30] + "[TRUNCATED]", "consolidado_id", lid)
    fila = _fila_b({"agente": "x", "consolidado_id": lid, "elementos": [{"detalle": "z" * 400}]}, truncar=True)
    assert any(vp.salida_truncada(h, "consolidado_id", lid) for h in vp.hojas_traza(fila))


def test_procedencia_de_b_anidada_truncada_y_con_colision(m):
    m.hasta_verificacion()
    assert _todos_los_lotes(m)[0] == 0
    est = m.estado()
    lotes = {x["lote_id"]: x["respuesta"] for x in est["carga"]["consolidado"]["lotes"]}
    experto_resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]

    def kql_con(modo: str):
        def kql(consulta: str):
            if "BRF-" in consulta:
                return [_fila_b(experto_resp)]
            lid = next(i for i in lotes if f'"{i}"' in consulta)
            otra = copy.deepcopy(lotes[lid])  # otra ejecución con el mismo id: distinta desde el principio
            otra["entrada_recibida_inicio"] = "Otra ejecución con el mismo identificador de lote, de otra solicitud."
            tarde = copy.deepcopy(lotes[lid])  # la MISMA llamada, completa, distinta solo al final (Revisión)
            tarde["herramientas_usadas"]["microsoft_docs_fetch"] += 1  # I1.7: sin precios_azure
            mala = copy.deepcopy(lotes[lid])
            mala["entrada_recibida_inicio"] = "Un comienzo que no es el del estado."
            return {"anidada": [_fila_b(lotes[lid])], "truncada": [_fila_b(lotes[lid], True), _fila_b(otra, op="op-otra-ejecucion")],
                    "distinta": [_fila_b(otra)], "enmascarada": [_fila_b(lotes[lid], True), _fila_b(tarde)],
                    "comienzo_malo": [_fila_b(mala, True)]}[modo]
        return kql

    c = vp.c_procedencia(_ctx_procedencia(est, kql_con("anidada")))
    assert c.estado == vp.OK, c.detalles  # seis niveles de anidamiento: antes no se llegaba a la salida
    c = vp.c_procedencia(_ctx_procedencia(est, kql_con("truncada")))
    assert c.estado == vp.NOV and any("truncan" in d and "otra ejecución" in d for d in c.detalles), c.detalles
    c = vp.c_procedencia(_ctx_procedencia(est, kql_con("distinta")))
    assert c.estado == vp.FALLA, c.detalles  # salida completa y distinta: sigue siendo FALLA
    c = vp.c_procedencia(_ctx_procedencia(est, kql_con("enmascarada")))
    assert c.estado == vp.FALLA, c.detalles  # Revisión: lo truncado no tapa una salida completa de la misma llamada
    c = vp.c_procedencia(_ctx_procedencia(est, kql_con("comienzo_malo")))
    assert c.estado == vp.FALLA and any("comienzo distinto" in d for d in c.detalles), c.detalles


def test_coherencia_una_fila_propia_por_linea_del_anexo():
    tablas = [[["Servicio", "Concepto", "Coste"], ["Microsoft Foundry", "GPT 5 Mini Inpt DZone", "0,24 €"],
               ["Microsoft Foundry", "GPT 5 Mini outpt DZone", "0,39 €"]]]
    usadas: list[int] = []
    assert vp._fila_propia(tablas, "Microsoft Foundry", "GPT 5 Mini outpt DZone", usadas)[2] == "0,39 €"
    assert vp._fila_propia(tablas, "Microsoft Foundry", "GPT 5 Mini Inpt DZone", usadas)[2] == "0,24 €"
    assert vp._fila_propia(tablas, "Microsoft Foundry", "GPT 5 Mini Inpt DZone", usadas) is None  # no se reutiliza


def test_salida_truncada_del_experto_empieza_por_el_brief_devuelto():
    bid = "BRF-OF-BREZALIA-001-A-AZ-R2"
    resp = {"brief_recibido": f"BRIEF-PREVENTA/1\nbrief_id: {bid}\nexperto: preventa-experto-azure\n" + "x" * 900,
            "brief_id": bid, "agente": "preventa-experto-azure"}
    hoja = json.dumps(resp, ensure_ascii=False)[:400] + "... [TRUNCATED]"
    assert vp.salida_truncada(hoja, "brief_id", bid)
    assert not vp.salida_truncada(hoja.replace(bid, bid[:-1] + "3"), "brief_id", bid)
    argumentos = json.dumps({"message": resp["brief_recibido"]})[:400] + "... [TRUNCATED]"
    assert not vp.salida_truncada(argumentos, "brief_id", bid)  # argumentos de una herramienta: no es una salida


def test_coherencia_sin_la_fila_de_su_concepto_falla_aunque_el_importe_coincida():
    tablas = [[["Servicio", "Concepto", "Coste"], ["Microsoft Foundry", "Otro concepto", "0,39 €"]]]
    assert vp._fila_propia(tablas, "Microsoft Foundry", "GPT 5 Mini outpt DZone", []) is None  # Revisión
    assert vp._fila_propia(tablas, "Microsoft Foundry", None, [])[1] == "Otro concepto"  # sin concepto: por nombre


def test_casa_prefijo_conserva_los_espacios_de_dentro_de_las_cadenas():
    obj = {"agente": "preventa-verificador", "consolidado_id": "CNS-OF-X-001-A-R1-L1", "detalle": "a b c"}
    bonito = json.dumps(obj, ensure_ascii=False, indent=2)
    assert vp.casa_prefijo(bonito[:60], obj)  # sangría y saltos de línea fuera de las cadenas: casa
    assert vp.casa_prefijo(json.dumps(obj, separators=(",", ":"))[:70], obj)
    assert not vp.casa_prefijo(json.dumps(dict(obj, detalle="ab c"), separators=(",", ":"))[:-3], obj)  # Revisión
    assert vp.sin_espacios_fuera('{ "a" : "x \\" y" ,\n "b": 1 }') == '{"a":"x \\" y","b":1}'
