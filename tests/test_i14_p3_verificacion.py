"""I1.4 · papel P3: reclasificación por campo declarado (ARR13-4), SaaS por igualdad (REV13-1), eco por líneas (EA-3)
y contrato del experto (EB-5).

Incluye como regresión los 13 casos de pruebas/I13/REVERIF/sondas_reclasificacion.py (los 4 que fallaban y los 9 de
defensa) y, marcadas como xfail estricto, las pruebas de igualdad con la réplica de la puerta que el integrador aplica
desde docs/I1/CAMBIOS-I14-P3.md (al integrarla pasan a XPASS y el marcador se quita).
"""
from __future__ import annotations

import copy
import json
import pathlib

import pytest

import tests.test_i1_estado_comun  # noqa: F401  (pone sandbox/ en sys.path)
from nucleo import esquema, experto, verificacion as v  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
M = v.MARCA_TENANT
SPO = "https://learn.microsoft.com/microsoft-365/enterprise/m365-dr-workload-spo"
ENTRA = "https://learn.microsoft.com/entra/fundamentals/data-residency"
C_SEARCH = "C-03 | Azure AI Search | sku: S1 | region: swedencentral | referencia: https://learn.microsoft.com/azure/search/x"
REF_SEARCH = "REF-02 | https://learn.microsoft.com/azure/search/x | Introducción a Azure AI Search"
TEAMS = f"C-01 | Microsoft Teams | sku: n/a | region: global {M} | referencia: https://learn.microsoft.com/microsoftteams/x"

# (nombre, tipo, línea, valor correcto, fuente, campo, esperado). Las cuatro primeras daban DEGRADA en la sonda.
SONDAS = [
    ("ARR13-4: región errónea, valor = nombre oficial", "valor", C_SEARCH, "Azure AI Search", None, "region", False),
    ("ARR13-4: URL objetada, valor = su título", "valor", REF_SEARCH, "Título: Introducción a Azure AI Search", None,
     "url", False),
    ("REV13-1: indexador de SharePoint de Azure AI Search", "res",
     "C-05 | desviación: Indexador de SharePoint de Azure AI Search | sku: S1 | region: global | referencia: "
     "https://learn.microsoft.com/azure/search/x", None, SPO, "region", False),
    ("REV13-1: NotSharePoint Gateway", "res", "C-05 | desviación: NotSharePoint Gateway | sku: x | region: global | "
     "referencia: https://learn.microsoft.com/x", None, SPO, "region", False),
    ("valor = SKU", "valor", C_SEARCH, "S1", None, "sku", False),
    ("desviación con valor = nombre", "valor", "C-09 | desviación: SharePoint Online | sku: E3 | region: global | "
     "referencia: https://learn.microsoft.com/x", "desviación: SharePoint Online", None, "nombre", False),
    ("Teams con marca y fuente de residencia", "res", TEAMS, None, SPO, "region", True),
    ("fuente vecina m365-drfalso", "res", TEAMS, None, "https://learn.microsoft.com/microsoft-365/enterprise/m365-drfalso",
     "region", False),
    ("subruta data-residency-x", "res", f"C-10 | Microsoft Entra ID | sku: P1 | region: global {M} | referencia: "
     "https://learn.microsoft.com/entra/x", None, ENTRA + "-x", "region", False),
    ("Power Automate en global", "res", "C-05 | desviación: Power Automate | sku: x | region: global | referencia: "
     "https://learn.microsoft.com/x", None, SPO, "region", False),
    ("bot del catálogo en global sin marca", "res", "C-02 | Azure AI Bot Service | sku: S1 | region: global | "
     "referencia: https://learn.microsoft.com/azure/bot-service/x", None, ENTRA, "region", False),
    ("marca en una región que no es global", "res", f"C-01 | Microsoft Teams | sku: n/a | region: westeurope {M} | "
     "referencia: https://learn.microsoft.com/x", None, SPO, "region", False),
    ("fuente fuera de Learn con la ruta buena", "res", TEAMS, None,
     "https://evil.example.com/microsoft-365/enterprise/m365-dr-workload-spo", "region", False),
]


def _juzgar(mod, tipo, linea, vc, fuente, campo) -> bool:
    if tipo == "valor":
        return mod.valor_es_lo_enviado(linea, vc, campo)
    return mod.es_residencia_tenant(linea, fuente, campo)


@pytest.mark.parametrize("nombre, tipo, linea, vc, fuente, campo, esperado", SONDAS, ids=[s[0] for s in SONDAS])
def test_sondas_de_la_reverificacion_en_el_nucleo(nombre, tipo, linea, vc, fuente, campo, esperado):
    assert _juzgar(v, tipo, linea, vc, fuente, campo) is esperado


@pytest.mark.parametrize("campo", [None, "ninguno", "sku", "region", "url", "referencia"])
def test_valor_igual_al_nombre_solo_con_campo_nombre(campo):
    assert v.valor_es_lo_enviado(C_SEARCH, "Azure AI Search", campo) is False
    assert v.valor_es_lo_enviado(REF_SEARCH, "Introducción a Azure AI Search", campo) is False


def test_valor_igual_con_su_campo_si_reclasifica():
    assert v.valor_es_lo_enviado(C_SEARCH, "azure  ai-search", "nombre") is True
    assert v.valor_es_lo_enviado(REF_SEARCH, "Título: Introducción a Azure AI Search", "titulo") is True
    assert v.valor_es_lo_enviado(C_SEARCH, "Azure AI Search", "titulo") is False  # campo de otro tipo de línea


@pytest.mark.parametrize("nombre, esperado", [
    ("SharePoint Online", True), ("Microsoft SharePoint Online", True), ("SharePoint in Microsoft 365", True),
    ("OneDrive for Business", True), ("Exchange Online", True), ("Microsoft 365", True),
    ("Indexador de SharePoint de Azure AI Search", False), ("NotSharePoint Gateway", False),
    ("SharePoint Online Connector", False), ("Power Automate", False), ("", False)])
def test_saas_por_igualdad_de_la_forma_compacta(nombre, esperado):
    assert v.es_saas_tenant(f"desviación: {nombre}") is esperado
    assert v.es_saas_tenant(nombre) is False  # sin el prefijo de desviación no es una desviación


@pytest.mark.parametrize("campo", [None, "nombre", "sku", "referencia", "ninguno"])
def test_residencia_solo_si_discute_la_region(campo):
    assert v.es_residencia_tenant(TEAMS, SPO, campo) is False


# --- validar_respuesta: campo obligatorio en DISCREPA (ARR13-4) y eco por líneas (EA-3) ---

CID = "CNS-OF-KELVARA-001-A-R1"
TEXTO = "\n".join(["CONSOLIDADO-PREVENTA/1", f"consolidado_id: {CID}", "brief_id: BRF-OF-KELVARA-001-A-AZ-R1",
                   "ubicacion_usuarios: España", "sha256_cuerpo: 0", "---", "## Referencias", REF_SEARCH.replace("REF-02", "REF-01"),
                   "## Componentes", C_SEARCH.replace("C-03", "C-01")])
CONS = {"consolidado_id": CID, "texto": TEXTO, "ids": ["REF-01", "C-01"], "lotes": []}
ECO = "\n".join(TEXTO.split("\n")[:3])


def _r(cambios: dict | None = None, eco: str = ECO) -> dict:
    el = [{"id": i, "tipo": t, "veredicto": "OK", "campo": "ninguno", "detalle": "Comprobado.", "valor_correcto": None,
           "fuente_url": None} for i, t in (("REF-01", "referencia"), ("C-01", "componente"))]
    for e in el:
        e.update((cambios or {}).get(e["id"], {}))
    return {"agente": "preventa-verificador", "consolidado_id": CID, "entrada_recibida_inicio": eco, "elementos": el,
            "resumen": {"ok": 2, "discrepa": 0, "observacion": 0, "no_verificable": 0},
            "herramientas_usadas": {"microsoft_docs_search": 1, "microsoft_docs_fetch": 1}}  # I1.7: sin precios_azure


DISC = {"veredicto": "DISCREPA", "valor_correcto": "francecentral", "fuente_url": "https://learn.microsoft.com/azure/search/y"}


@pytest.mark.parametrize("campo, ok", [("region", True), ("sku", True), ("nombre", True), ("referencia", True),
                                       ("ninguno", False), ("url", False), ("precio", False)])
def test_discrepa_exige_un_campo_de_su_tipo(campo, ok):
    errores = v.validar_respuesta(_r({"C-01": {**DISC, "campo": campo}}), CONS)
    assert (errores == []) is ok, errores
    assert ok or "DISCREPA exige el campo discutido" in errores[0]


def test_sin_campo_no_valida_contra_el_esquema_vigente():
    r = _r()
    del r["elementos"][0]["campo"]
    assert any("campo" in e for e in v.validar_respuesta(r, CONS))


@pytest.mark.parametrize("eco, ok", [
    (ECO, True), (ECO.replace("\n", "\r\n"), True), ("  " + ECO.replace("\n", " \n  ") + "\n", True),
    ("\n".join(TEXTO.split("\n")[:5]), True),
    (TEXTO[:80], False),  # un eco por caracteres (el viejo era de 100) que corta la línea 3
    (ECO.replace("\n", " "), False),  # en una sola línea: no se compara por líneas
    ("\n".join(TEXTO.split("\n")[:2]), False), (ECO[:-1], False), (ECO.replace("AZ-R1", "AZ-R2"), False),
    (ECO + "\nlínea inventada", False)])
def test_eco_por_lineas_completas(eco, ok):
    errores = v.errores_eco(eco, TEXTO)
    assert (errores == []) is ok, errores


def _estado_eval() -> dict:
    ref = {"id": "REF-01", "url": "https://learn.microsoft.com/azure/search/x", "titulo": "Introducción a Azure AI Search"}
    return {"carga": {"respuestas_expertos": {"azure": {"respuesta": {"referencias": [ref], "precios": []}}},
                      "consolidado": CONS}}


@pytest.mark.parametrize("campo, reparado", [("url", True), ("titulo", False), (None, False)])
def test_url_igual_solo_se_repara_si_discute_la_url(campo, reparado):
    e = {"id": "REF-01", "tipo": "referencia", "veredicto": "DISCREPA", "detalle": "Revisado.",
         "valor_correcto": "https://learn.microsoft.com/en-us/azure/search/x/", "fuente_url": "https://learn.microsoft.com/azure/search/x"}
    if campo:
        e["campo"] = campo
    res = v.evaluar(_estado_eval(), {"elementos": [e]})
    assert ([x["id"] for x in res.reparados] == ["REF-01"]) is reparado
    assert ([x["id"] for x in res.discrepa] == ["REF-01"]) is (not reparado)


def test_observacion_por_nombre_lleva_el_campo_en_el_motivo():
    e = {"id": "C-01", "tipo": "componente", "veredicto": "DISCREPA", "campo": "nombre", "detalle": "Revisado.",
         "valor_correcto": "Azure AI Search", "fuente_url": "https://learn.microsoft.com/azure/search/y"}
    res = v.evaluar(_estado_eval(), {"elementos": [e]})
    assert res.discrepa == [] and res.observaciones[0]["campo"] == "nombre" and "«nombre»" in res.observaciones[0]["motivo"]


# --- Esquema vigente (v3), histórico v2, text.format y bloques generados ---

def _esquema(nombre: str) -> dict:
    return json.loads((RAIZ / "esquemas" / f"{nombre}.json").read_text(encoding="utf-8"))


def test_esquema_v3_con_campo_y_v2_congelado_para_lo_anterior():
    from esquemas.comprobar_esquemas import validar
    v3, v2 = _esquema("respuesta_verificador"), _esquema("historico/respuesta_verificador_v2")
    assert v3["$id"].endswith(":4") and v2["$id"].endswith(":2") and v2["description"].startswith("HISTÓRICO")  # I1.7
    enum = v3["$defs"]["elemento"]["properties"]["campo"]["enum"]
    assert set(enum) == {"ninguno"} | {c for cs in v.CAMPOS_DISCREPA.values() for c in cs}
    viejo = _r()
    viejo["herramientas_usadas"]["precios_azure"] = 0  # integrador I1.7: la v2 (I1.1-I1.3) lo exigía
    for e in viejo["elementos"]:
        del e["campo"]
    viejo["entrada_recibida_inicio"] = TEXTO[:100]
    assert validar(viejo, v2, v2) == [] and validar(viejo, v3, v3) != []
    assert validar(_r(), v3, v3) == []


def test_text_format_del_verificador_lleva_campo_obligatorio_y_su_enum():
    from agentes.esquemas import derivar_text_format as dtf
    el = dtf.text_format("respuesta_verificador")["schema"]["properties"]["elementos"]["items"]
    assert "campo" in el["required"] and el["properties"]["campo"]["type"] == "string"
    # integrador I1.8 (VER17-6, CAMBIOS-I18-E §3.8): el text.format no ofrece los valores residuales de precio
    completo = _esquema("respuesta_verificador")["$defs"]["elemento"]["properties"]["campo"]["enum"]
    residuos = dtf.RESIDUOS["respuesta_verificador"]["campo"]
    assert residuos <= set(completo)
    assert el["properties"]["campo"]["enum"] == [x for x in completo if x not in residuos]
    assert dtf.main(["--comprobar"]) == 0


def _clase_product_name(entrada: dict) -> str:
    from agentes.esquemas import limites
    g, pp = limites.grupos_product_name(CAT), entrada.get("producto_precios")
    if pp and f"{entrada['nombre_oficial']} → `{pp}`" in g["obligatorio"]:
        return "obligatorio"
    if pp and f"{entrada['nombre_oficial']} → `{pp}`" in g["opcional"]:
        return "opcional"
    assert entrada["nombre_oficial"] in g["ninguno"], entrada["id"]
    return "ninguno"


@pytest.mark.parametrize("entrada", [e for e in CAT["componentes"] if e.get("service_name_precios")],
                         ids=lambda e: e["id"])
def test_bloque_product_name_sincronizado_con_el_codigo(entrada):
    """EB-5: lo que el bloque generado dice de cada servicio es lo que acepta nucleo.experto.problemas_precio."""
    clase, pp = _clase_product_name(entrada), entrada.get("producto_precios")
    region = entrada.get("region_precio") or entrada.get("region_ue") or "swedencentral"
    base = f"serviceName eq '{entrada['service_name_precios']}' and armRegionName eq '{region}' and priceType eq 'Consumption'"

    def problemas(filtro: str) -> list[str]:
        r = entrada.get("region_ue") if entrada.get("region_ue") not in (None, "global") else "westeurope"
        return [m for m in experto.problemas_precio({"filtro": filtro}, entrada, r, CAT) if "productName" in m]

    assert problemas(base + " and productName eq 'Producto Inventado'")  # nunca un productName ajeno
    assert (problemas(base) != []) is (clase == "obligatorio")
    if pp:
        assert problemas(base + f" and productName eq '{pp}'") == []


def test_instrucciones_con_las_reglas_de_i14():
    verif = (RAIZ / "agentes" / "instrucciones" / "verificador_i1.md").read_text(encoding="utf-8")
    exp = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md").read_text(encoding="utf-8")
    assert "**tres primeras líneas completas**" in verif and "`campo`, `detalle`" in verif
    assert "`campo`: el campo de la línea" in verif and "100 caracteres" not in verif
    assert "**Rondas 2 y 3**" in exp and "**1 búsqueda y 1 lectura**" in exp and "«F1»" in exp
    from agentes.esquemas import limites
    # integrador I1.7 (CAMBIOS-I17-E §3.2): el experto ya no escribe filtros; el bloque de productName ya no va
    assert limites.main(["--comprobar"]) == 0 and limites.bloque_product_name(CAT) not in exp


# --- Igualdad con la réplica de la puerta (docs/I1/CAMBIOS-I14-P3.md). Mientras la puerta no la tenga (sin
# SAAS_TENANT_NOMBRES), xfail estricto y solo con los errores esperables de la puerta vieja. En cuanto la tiene, el
# marcador se desactiva solo y estas pruebas cuentan como cualquier otra: un fallo es un fallo (Revisión 2, I1.4). ---

# Integrado el 10-10-2026 (I1.4): la puerta ya tiene la réplica y se retira el marcador xfail.


@pytest.mark.parametrize("nombre, tipo, linea, vc, fuente, campo, esperado", SONDAS, ids=[s[0] for s in SONDAS])
def test_sondas_igual_en_la_puerta(nombre, tipo, linea, vc, fuente, campo, esperado):
    import verificar_paquete as vp
    assert _juzgar(vp, tipo, linea, vc, fuente, campo) is esperado


def test_constantes_y_funciones_de_la_replica_iguales_al_nucleo():
    import verificar_paquete as vp
    assert vp.SAAS_TENANT_NOMBRES == v.SAAS_TENANT_NOMBRES and vp.CAMPOS_DISCREPA == v.CAMPOS_DISCREPA
    assert vp.ECO_LINEAS == v.ECO_LINEAS
    for campo in (None, "ninguno", "nombre", "titulo", "region", "url", "sku"):
        for linea in (C_SEARCH, REF_SEARCH, TEAMS):
            for vc in ("Azure AI Search", "Introducción a Azure AI Search", "S1"):
                assert vp.valor_es_lo_enviado(linea, vc, campo) == v.valor_es_lo_enviado(linea, vc, campo)
            for fuente in (SPO, ENTRA, None):
                assert vp.es_residencia_tenant(linea, fuente, campo) == v.es_residencia_tenant(linea, fuente, campo)
    for nombre in ("desviación: SharePoint Online", "desviación: NotSharePoint Gateway", "SharePoint Online"):
        assert vp.es_saas_tenant(nombre) == v.es_saas_tenant(nombre)
    for eco in (ECO, TEXTO[:80], ECO.replace("\n", " "), ECO + "\notra"):
        assert (vp.errores_eco(eco, TEXTO) == []) == (v.errores_eco(eco, TEXTO) == [])


def test_contrato_v2_en_la_puerta_con_su_esquema_historico():
    import verificar_paquete as vp
    viejo = _r()
    for e in viejo["elementos"]:
        del e["campo"]
    assert vp.es_contrato_v2(viejo) and not vp.es_contrato_v2(_r()) and not vp.es_contrato_v2({"elementos": []})
    assert vp.nombre_esquema_verificador({"consolidado": {"lotes": []}, "verificacion": {"respuesta": viejo}}) == \
        "historico/respuesta_verificador_v2"
    assert vp.nombre_esquema_verificador({"consolidado": {"lotes": []}, "verificacion": {"respuesta": _r()}}) == \
        "respuesta_verificador"


@pytest.mark.parametrize("veredicto, campo, esperado", [
    ("DISCREPA", "precio", "reparados"), ("DISCREPA", "region", "discrepa"), ("DISCREPA", "unidad", "discrepa"),
    ("DISCREPA", None, "discrepa"), ("OBSERVACION", "ninguno", "reparados")])
def test_precio_dentro_del_umbral_solo_se_repara_si_discute_el_precio(veredicto, campo, esperado):
    """Revisión (I1.4): un número a ≤ 0,5 % no demuestra nada de la unidad, la región o el filtro."""
    est = _estado_eval()
    est["carga"]["respuestas_expertos"]["azure"]["respuesta"]["precios"] = [{"id": "P-01", "precio": 100.0}]
    e = {"id": "P-01", "tipo": "precio", "veredicto": veredicto, "detalle": "Revisado.", "valor_correcto": "100.2",
         "fuente_url": "https://prices.azure.com/api/retail/prices" if veredicto == "DISCREPA" else None}
    if campo:
        e["campo"] = campo
    res = v.evaluar(est, {"elementos": [e]})
    assert [x["id"] for x in getattr(res, esperado)] == ["P-01"]


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    from tests.test_i1_estado_comun import Mundo
    return Mundo(tmp_path, monkeypatch)


def _sin_campo(est: dict) -> dict:
    est = copy.deepcopy(est)
    for e in est["carga"]["verificacion"]["respuesta"]["elementos"]:
        e.pop("campo", None)
    for x in est["carga"]["consolidado"]["lotes"]:
        for e in x["respuesta"]["elementos"]:
            e.pop("campo", None)
    return est


def test_puerta_falla_con_respuestas_sin_campo_y_con_eco_cortado(mundo):
    """Revisión (I1.4): quitar «campo» y resellar no da las reglas viejas; un eco por caracteres tampoco pasa."""
    import verificar_paquete as vp
    from tests.test_i1_verificacion_integracion_v import _ctx, _por_lotes
    est = _por_lotes(mundo)
    assert est["estado"] == "VERIFICADA" and vp.c_verificacion(_ctx(est)).estado != vp.FALLA
    roto = vp.c_verificacion(_ctx(_sin_campo(est)))
    assert roto.estado == vp.FALLA and any("anterior a I1.4" in str(x) for x in roto.detalles)
    cortado = copy.deepcopy(est)
    lote = cortado["carga"]["consolidado"]["lotes"][0]
    lote["respuesta"]["entrada_recibida_inicio"] = lote["texto"][:80]
    assert vp.c_verificacion(_ctx(cortado)).estado == vp.FALLA
