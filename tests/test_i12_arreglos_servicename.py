"""I1.2, arreglos de la reverificación (pruebas/I12/ARREGLOS-SERVICENAME.md). Sin red.

REVER-1: el servicio de un componente se identifica por (a) su catalogo_id, (b) el serviceName/productName del filtro
de su precio y (c) un alias como frase completa; el veto de región se cruza con (a) y (b), y lo que no se identifica
por ninguno de los dos lleva el aviso en una región con vetos. REVER-2: sin bolsas de palabras. Misma lógica en el
núcleo y en la réplica de la puerta (cada prueba compara las dos).
"""
from __future__ import annotations

import ast
import inspect
import json
import textwrap
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
sys.path.insert(0, str(RAIZ))
from nucleo import experto  # noqa: E402
import verificar_paquete as V  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)

CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
SW = "swedencentral"
FUNCIONES = ("_tokens", "contiene_frase", "alias_en_nombre", "_entradas", "valores_filtro", "servicios_de_precio",
             "_nombres", "identificar_servicio", "incoherencias_servicio", "_regiones_con_veto", "region_no_admitida",
             "aviso_fuera_de_catalogo", "alias_servicio", "alias_inequivocos", "_letras_no_latinas", "_plegar",
             "_compacto")


def _comp(servicio, region=SW, cid=None, ident="C-02"):
    return {"id": ident, "servicio": servicio, "catalogo_id": cid, "region": region}


def _precio(filtro, comp="C-02", pid="P-01"):
    return {"id": pid, "componente_id": comp, "filtro": filtro}


def _sonda(mod, comp, precios=None):
    if mod.region_no_admitida(comp, CAT, precios):
        return "VETA"
    return "AVISO" if mod.aviso_fuera_de_catalogo(comp, CAT, precios) else "NADA"


def _igual(comp, precios=None) -> str:
    """Resultado del núcleo, tras comprobar que la puerta da exactamente lo mismo (motivo, aviso e incoherencias)."""
    for f in ("region_no_admitida", "aviso_fuera_de_catalogo", "incoherencias_servicio"):
        assert getattr(experto, f)(comp, CAT, precios) == getattr(V, f)(comp, CAT, precios), f
    return _sonda(experto, comp, precios)


COG = "serviceName eq 'Azure Cognitive Search' and armRegionName eq 'swedencentral' and skuName eq 'Standard S1'"


def test_replica_de_la_puerta_con_el_mismo_codigo():
    """La réplica es el mismo código (salvo docstrings y comentarios), función a función."""
    def cuerpo(mod, f):
        nodo = ast.parse(textwrap.dedent(inspect.getsource(getattr(mod, f)))).body[0]
        if (nodo.body and isinstance(nodo.body[0], ast.Expr) and isinstance(nodo.body[0].value, ast.Constant)
                and isinstance(nodo.body[0].value.value, str)):
            nodo.body = nodo.body[1:]  # sin el docstring; ast ya descarta los comentarios
        return ast.dump(nodo)
    for f in FUNCIONES:
        assert cuerpo(experto, f) == cuerpo(V, f), f
    assert experto._INVISIBLES == V._INVISIBLES and experto.AVISO_FUERA_DE_CATALOGO == V.AVISO_FUERA_DE_CATALOGO
    assert (experto.HOMOGLIFOS, experto._PREFIJOS_MARCA, experto._ALIAS_MIN) == (V.HOMOGLIFOS, V._PREFIJOS_MARCA,
                                                                              V._ALIAS_MIN)


# ── REVER-1: el precio delata el servicio ───────────────────────────────────────────────────────────────────────
def test_busqueda_sobre_blob_con_precio_de_cognitive_search_se_veta():
    comp = _comp("Búsqueda semántica sobre Almacenamiento Blob")
    assert _igual(comp) == "AVISO"  # sin precio ya no pasa en silencio (antes callaba por el alias de Blob)
    assert _igual(comp, [_precio(COG)]) == "VETA"
    motivo = experto.region_no_admitida(comp, CAT, [_precio(COG)])
    assert motivo.startswith("Azure AI Search en swedencentral (identificado por el filtro de su precio P-01)")


@pytest.mark.parametrize("filtro", [
    "serviceName eq 'Azure Cognitive Search'", "SERVICENAME  eq  'azure cognitive search'",
    "armRegionName eq 'swedencentral' and serviceName eq 'Azure\u200bCognitive Search'",
    "productName eq 'Azure AI Search' and armRegionName eq 'swedencentral'",
    "serviceName eq 'Azure Cognitive Search' and productName eq 'Azure AI Search'"])
def test_las_formas_del_filtro_que_identifican_ai_search(filtro):
    assert _igual(_comp("Indexador propio"), [_precio(filtro)]) == "VETA"


@pytest.mark.parametrize("filtro", [
    "contains(serviceName, 'Search')", "serviceName eq \"Azure Cognitive Search\"", "meterName eq 'S1'",
    "productName eq 'Azure AI Search Extra'", "xserviceName eq 'Azure Cognitive Search'"])
def test_un_filtro_que_no_identifica_nada_deja_el_aviso(filtro):
    assert _igual(_comp("Indexador propio"), [_precio(filtro)]) == "AVISO"


def test_el_precio_de_otro_componente_no_cuenta():
    assert _igual(_comp("Indexador propio"), [_precio(COG, comp="C-07")]) == "AVISO"


def test_foundry_tools_se_desambigua_por_el_product_name():
    voz = _comp("Transcripción de llamadas", region="spaincentral")
    con = [_precio("serviceName eq 'Foundry Tools' and productName eq 'Azure Speech' and armRegionName eq 'spaincentral'")]
    assert _igual(voz, con) == "VETA" and "Azure Speech in Foundry Tools" in experto.region_no_admitida(voz, CAT, con)
    assert _igual(voz, [_precio("serviceName eq 'Foundry Tools'")]) == "AVISO"  # seis servicios: no identifica
    assert _igual(dict(voz, catalogo_id="az-language"), [_precio("serviceName eq 'Foundry Tools'")]) == "NADA"
    assert experto.incoherencias_servicio(dict(voz, catalogo_id="az-language"), CAT, con)


def test_private_link_facturado_como_virtual_network_es_coherente():
    pl = _comp("Azure Private Link", cid="az-private-link")
    assert _igual(pl, [_precio("serviceName eq 'Virtual Network' and armRegionName eq 'swedencentral'")]) == "NADA"
    # ARRPR (REVSN-5): Retail Prices solo publica Private Link como «Global»; con la región del componente, rechazo
    assert experto.incoherencias_servicio(pl, CAT, [_precio("serviceName eq 'Virtual Network' and "
                                                            "armRegionName eq 'swedencentral'")])
    plantilla = next(p["filtro"] for c in CAT["componentes"] if c["id"] == "az-private-link"  # I1.5: plantilla
                     for p in c["plantillas_precio"] if p["id"] == "punto-conexion")
    assert not experto.incoherencias_servicio(pl, CAT, [_precio(plantilla)])


# ── REVER-2: frases genéricas que la regla de palabras vetaba ──────────────────────────────────────────────────
APP = "serviceName eq 'Azure App Service' and armRegionName eq 'swedencentral' and skuName eq 'P0 v3'"


def test_plataforma_de_busqueda_con_ia_sin_id_no_se_veta_y_lleva_aviso():
    assert _igual(_comp("Plataforma de búsqueda con IA")) == "AVISO"
    assert _igual(_comp("Plataforma de busqueda con IA"), [_precio(APP)]) == "NADA"  # su precio dice App Service
    # ARRPR (decisión del PM): pero con precio y sin catalogo_id, la respuesta se rechaza
    assert "no lleva un catalogo_id" in experto.incoherencias_servicio(_comp("Plataforma"), CAT, [_precio(APP)])[0]


@pytest.mark.parametrize("precios", [None, [_precio(APP)]])
def test_api_de_busqueda_con_ia_con_su_id_no_se_veta(precios):
    for nombre in ("API de búsqueda con IA", "API de busqueda con IA"):
        assert _igual(_comp(nombre, cid="az-app-service"), precios) == "NADA"


# ── Incoherencia: el id y el precio hablan de servicios distintos ──────────────────────────────────────────────
def test_id_de_un_servicio_y_precio_de_otro_es_incoherente():
    comp = _comp("Azure App Service", cid="az-app-service")
    (motivo,) = experto.incoherencias_servicio(comp, CAT, [_precio(COG)])
    # ARRPR: mensaje de la lista blanca (el filtro tiene que casar entero con el servicio del catalogo_id)
    assert "el precio P-01: serviceName «Azure Cognitive Search» no es el de Azure App Service (az-app-service)" in motivo
    assert "hablan de servicios distintos" in motivo
    assert V.incoherencias_servicio(comp, CAT, [_precio(COG)]) == [motivo]


def test_sin_id_dos_precios_de_servicios_distintos_es_incoherente():
    comp = _comp("Componente mixto")
    precios = [_precio(APP), _precio(COG, pid="P-02")]
    (motivo,) = experto.incoherencias_servicio(comp, CAT, precios)
    # ARRPR (decisión del PM): con precio, el catalogo_id es obligatorio; el motivo nombra los dos precios
    assert "(P-01, P-02)" in motivo and "no lleva un catalogo_id del catálogo" in motivo
    assert V.incoherencias_servicio(comp, CAT, precios) == [motivo]


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): un precio con el filtro de otro servicio en la respuesta del modelo; imposible por construcción con el contrato v4 (el modelo ya no escribe filtros: los pone el núcleo desde la plantilla). Lo vigente: las reglas de incoherencia se siguen probando aquí sobre precios sueltos y la puerta las aplica a la respuesta completada")
def test_validar_respuesta_rechaza_la_incoherencia():
    from tests.test_i12_f1 import ejemplo
    resp, br = ejemplo("respuesta_experto"), ejemplo("brief")
    p = next(x for x in resp["precios"] if x["componente_id"] == "C-04")
    p["filtro"] = "serviceName eq 'Azure Cognitive Search' and armRegionName eq 'swedencentral'"
    errores = i17_int.validar(resp, br, CAT, br["perfiles_permitidos"])
    assert any(e.startswith("componentes.C-04: el precio P-02") and "servicios distintos" in e for e in errores), errores


# ── Los 21 casos de la reverificación (REVERIFICACION-VER.md §1), sin precio que los identifique ───────────────
CASOS_REVERIF = [  # (caso, región, nombre, catalogo_id, resultado con las reglas nuevas)
    ("M1", SW, "Búsqueda inteligente de Azure", None, "AVISO"), ("M2", SW, "Busqueda de IA de Azure", None, "AVISO"),
    ("M3", SW, "Cognitiva Azure Búsqueda", None, "AVISO"), ("M4", SW, "Búsq. IA Azure", None, "AVISO"),
    ("M5", SW, "Azure AI (Estándar S1, 2 réplicas) Search", None, "AVISO"),
    ("M6", SW, "bÚsQuEdA CoGnItIvA dE aZuRe", None, "VETA"),
    ("M7", SW, "Búsqueda\u00a0de\u2009Azure\u202fAI", None, "VETA"),
    ("M8", "northeurope", "Agentes de Microsoft Foundry", None, "AVISO"),
    ("X1", SW, "Azure AI B\u200búsqueda", None, "AVISO"), ("X2", SW, "Bús\u00adqueda de Azure AI", None, "VETA"),
    ("X3", SW, "Búsqueda\nde Azure AI", None, "VETA"),
    ("X4", SW, "Búsqueda semántica sobre Almacenamiento Blob", None, "AVISO"),
    ("X5", SW, "Buscador vectorial de Microsoft Foundry", None, "AVISO"),
    ("X6", "northeurope", "Agentes de Foundry", None, "AVISO"),
    ("X7", "northeurope", "Seguridad de contenido de Azure AI", None, "AVISO"),
    ("X8", "spaincentral", "Voz de IA de Azure", None, "AVISO"),
    ("X9", "francecentral", "Comprensión de contenido (Foundry Tools)", None, "AVISO"),
    ("F1", SW, "Plataforma de búsqueda con IA", None, "AVISO"),
    ("F2", SW, "API de búsqueda con IA", "az-app-service", "NADA"),
    ("F3", SW, "Azure App Service (API de búsqueda)", "az-app-service", "NADA"),
    ("F4", SW, "Voz de Azure", None, "AVISO")]


@pytest.mark.parametrize("caso, region, nombre, cid, esperado", CASOS_REVERIF, ids=[c[0] for c in CASOS_REVERIF])
def test_los_21_casos_de_la_reverificacion(caso, region, nombre, cid, esperado):
    assert _igual(_comp(nombre, region, cid)) == esperado
    assert esperado != "NADA" or cid is not None  # sin id ni precio, nunca en silencio en una región con vetos


# ── (c) alias como frase completa, de borde a borde ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("texto, alias, casa", [
    ("AI-Search (S1)", "aisearch", True), ("AzureAISearch", "azureaisearch", True),
    ("Azure  AI\tSearch", "azureaisearch", True), ("B\u00fas\u00adqueda de Azure AI", "busquedadeazureai", True),
    ("\u0410zure AI Search", "azureaisearch", True),  # «A» cirílica, plegada por HOMOGLIFOS
    ("AzureAISearch", "aisearch", False), ("Kai Search", "aisearch", False), ("Search AI", "aisearch", False),
    ("AI Searching", "aisearch", False), ("Azure AI Search\u2122", "azureaisearch", False)])
def test_contiene_frase_de_borde_a_borde(texto, alias, casa):
    assert experto.contiene_frase(texto, alias) is casa is V.contiene_frase(texto, alias)


def test_el_catalogo_identifica_cada_producto_de_precios_sin_ambiguedad():
    pares = [(c.get("service_name_precios"), c.get("producto_precios")) for c in CAT["componentes"]
             if c.get("producto_precios")]
    assert len(pares) == len(set(pares)) and ("Foundry Tools", "Azure Speech") in pares
    for c in CAT["componentes"]:
        if c.get("service_name_precios"):
            filtro = f"serviceName eq '{c['service_name_precios']}'" + (
                f" and productName eq '{c['producto_precios']}'" if c.get("producto_precios") else "")
            ids = experto.servicios_de_precio(_precio(filtro), CAT)
            assert ids and c["id"] in ids[0], c["id"]


@pytest.mark.parametrize("filtro, valores", [  # Revisión, I1.2: un «serviceName eq» dentro de otro literal no cuenta
    ("skuName eq ' serviceName eq ' and serviceName eq 'Azure Cognitive Search'", ["Azure Cognitive Search"]),
    ("tag eq 'x and serviceName eq ''Azure Cognitive Search'''", []),
    ("meterName eq 'a serviceName eq ' and x eq 'Azure Cognitive Search'", []),
    ("serviceName eq 'O''Brien'", ["O'Brien"]), ("serviceName eq 'Azure Cognitive Search", []),
    ("\u00f1serviceName eq 'Azure Cognitive Search'", []),  # Revisión, I1.2: pegado a una letra no ASCII
    ("serviceName\u00a0eq\u2003'Storage'", ["Storage"])])
def test_valores_filtro_respeta_los_literales(filtro, valores):
    assert experto.valores_filtro(filtro, "serviceName") == valores == V.valores_filtro(filtro, "serviceName")


def test_un_service_name_escondido_tras_un_literal_trampa_sigue_delatando_el_servicio():
    trampa = "skuName eq ' serviceName eq ' and serviceName eq 'Azure Cognitive Search'"
    assert _igual(_comp("Indexador propio"), [_precio(trampa)]) == "VETA"
    assert experto.incoherencias_servicio(_comp("Azure Blob Storage", cid="az-storage"), CAT, [_precio(trampa)])
