"""Decisión del PM tras REVERIFICACION-SERVICENAME.md (I1.2, 09-10-2026): en el camino con precio, lista blanca.

Todo componente con precio exige un catalogo_id del catálogo, y el filtro de cada precio casa ENTERO con ese servicio
(serviceName, productName y armRegionName; solo «and»), salvo los precios_auxiliares del catálogo. REVSN-1, REVSN-2,
REVSN-3, REVSN-5, ARRSN-1 y REVSN-4. Cada caso compara el núcleo con la réplica de la puerta (verificar_paquete).
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib
import sys
import textwrap

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
sys.path.insert(0, str(RAIZ))
from nucleo import estado as est_mod  # noqa: E402
from nucleo import experto  # noqa: E402
import verificar_paquete as V  # noqa: E402
from catalogo import derivar  # noqa: E402
from catalogo import plantillas_precio as PP  # noqa: E402

from tests.i16_p_datos import a_v3, catalogo_i16  # noqa: E402  (I1.6: contrato común de la decisión 4)
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)
CAT = catalogo_i16(json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8")), niveles=False)
# Integrador I1.6: el catálogo derivado tal cual (niveles reales y auxiliar con su lista de 24), para las pruebas
# que comparan con el derivado o validan el ejemplo entero.
CAT_REAL = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
SW = "swedencentral"
FUNCIONES = ("_literales_filtro", "valores_filtro", "forma_filtro", "precios_auxiliares", "_lista", "problemas_precio",
             "incoherencias_servicio", "servicios_de_precio", "identificar_servicio", "region_no_admitida",
             "aviso_fuera_de_catalogo", "_regiones_con_veto", "_letras_no_latinas", "alias_inequivocos", "_entradas",
             "_nombres", "contiene_frase", "alias_en_nombre", "_tokens", "_plegar", "_compacto", "alias_servicio",
             "_filtro_de_plantilla")
ENT = {c["id"]: c for c in CAT["componentes"]}


def _plantilla(cid: str, pid: str, region: str = "{}") -> str:
    """I1.5 (decisión 1): el filtro de la plantilla `pid` de la fila `cid`; con region «{}» queda para .format()."""
    f = next(x["filtro"] for x in ENT[cid]["plantillas_precio"] if x["id"] == pid)
    base = ENT[cid].get("region_precio") or ENT[cid].get("region_ue")
    return f.replace(f"armRegionName eq '{base}'", f"armRegionName eq '{region}'", 1)


def _comp(servicio, cid=None, region=SW, ident="C-02"):
    return {"id": ident, "servicio": servicio, "catalogo_id": cid, "region": region}


def _precio(filtro, comp="C-02", pid="P-01"):
    return {"id": pid, "componente_id": comp, "filtro": filtro}


def _motivos(comp, *filtros) -> list[str]:
    """Incoherencias del núcleo, tras comprobar que la puerta da lo mismo (también el veto y el aviso)."""
    precios = [_precio(f, comp["id"], f"P-{n:02d}") for n, f in enumerate(filtros, start=1)]
    for f in ("incoherencias_servicio", "region_no_admitida", "aviso_fuera_de_catalogo"):
        assert getattr(experto, f)(comp, CAT, precios) == getattr(V, f)(comp, CAT, precios), f
    return experto.incoherencias_servicio(comp, CAT, precios)


def test_replica_de_la_puerta_con_el_mismo_codigo():
    def cuerpo(mod, f):
        nodo = ast.parse(textwrap.dedent(inspect.getsource(getattr(mod, f)))).body[0]
        if (nodo.body and isinstance(nodo.body[0], ast.Expr) and isinstance(nodo.body[0].value, ast.Constant)
                and isinstance(nodo.body[0].value.value, str)):
            nodo.body = nodo.body[1:]
        return ast.dump(nodo)
    for f in FUNCIONES:
        assert cuerpo(experto, f) == cuerpo(V, f), f
    assert experto.CAMPOS_FILTRO == V.CAMPOS_FILTRO == ("serviceName", "productName", "armRegionName")
    assert (experto._CONECTOR_NO_ADMITIDO.pattern, experto._CONECTOR_NO_ADMITIDO.flags) == (
        V._CONECTOR_NO_ADMITIDO.pattern, V._CONECTOR_NO_ADMITIDO.flags)


# ── E9-E13 de la reverificación: ahora se rechazan ─────────────────────────────────────────────────────────────
SA = "and armRegionName eq 'swedencentral' and priceType eq 'Consumption'"
E9_10 = f"serviceName eq 'Storage' and productName eq 'Azure AI Search' {SA}"
E11_12 = f"serviceName eq 'Azure AI Search' and productName eq 'Azure AI Search' {SA}"
E13 = f"serviceName eq 'Foundry Tools' and productName eq 'Azure AI Search' {SA}"


@pytest.mark.parametrize("caso,comp,filtro,motivo", [
    ("E9", _comp("Almacenamiento Blob"), E9_10, "no lleva un catalogo_id del catálogo"),
    ("E10", _comp("Almacenamiento Blob", "az-storage"), E9_10,
     "productName «Azure AI Search» no es de Azure Blob Storage (az-storage) (admite ninguno: quita el productName)"),
    ("E11", _comp("Almacenamiento Blob", "az-storage"), E11_12,
     "serviceName «Azure AI Search» no es el de Azure Blob Storage (az-storage)"),
    ("E12", _comp("Indexador propio"), E11_12, "no lleva un catalogo_id del catálogo"),
    ("E13", _comp("Lenguaje de Azure", "az-language"), E13,
     "productName «Azure AI Search» no es de Azure Language in Foundry Tools (az-language) (admite «Azure Language»)"),
])
def test_e9_a_e13_se_rechazan(caso, comp, filtro, motivo):
    motivos = _motivos(comp, filtro)
    assert len(motivos) == 1 and motivo in motivos[0], (caso, motivos)


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): un filtro de otro servicio escrito por el modelo en la respuesta entera (E9, E11); imposible por construcción con el contrato v4 (el modelo ya no escribe filtros: los pone el núcleo desde la plantilla). Lo vigente: plantilla_desconocida en tests/test_i17_p_completar.py; las reglas del filtro siguen probadas aquí sobre filtros sueltos (test_e9_a_e13_se_rechazan)")
@pytest.mark.parametrize("caso,cid,filtro", [("E9", None, E9_10), ("E11", "az-storage", E11_12)])
def test_validar_respuesta_rechaza_e9_y_e11_en_la_respuesta_entera(caso, cid, filtro):
    from tests.test_i12_f1 import ejemplo
    resp, br = ejemplo("respuesta_experto"), ejemplo("brief")
    c4 = next(c for c in resp["componentes"] if c["id"] == "C-04")
    c4.update(catalogo_id=cid, servicio="Almacenamiento Blob",
              desviacion_justificada=None if cid else "Almacén propio de documentos que no está en el catálogo.")
    next(p for p in resp["precios"] if p["componente_id"] == "C-04")["filtro"] = filtro
    errores = i17_int.validar(resp, br, CAT, br["perfiles_permitidos"])
    assert any(e.startswith("componentes.C-04: ") and "P-02" in e for e in errores), (caso, errores)


def test_el_ejemplo_del_contrato_sigue_siendo_valido_con_el_catalogo_real():
    """P-03 factura Private Link con «Azure Private Link», que entra por la lista blanca de auxiliares."""
    from tests.test_i12_f1 import ejemplo
    resp, br = ejemplo("respuesta_experto"), ejemplo("brief")
    assert i17_int.validar(resp, br, CAT_REAL, br["perfiles_permitidos"]) == []
    completada = i17_int.completar(resp, CAT_REAL, None, br["texto"])  # integrador I1.7: el filtro lo pone el núcleo
    assert any(p["filtro"].startswith("serviceName eq 'Virtual Network' and productName eq 'Virtual Network Private "
                                      "Link'") for p in completada["precios"])  # I1.6: la fila real, no el auxiliar


# ── REVSN-5: el armRegionName del filtro se cruza con la región (o con la región de precio del catálogo) ─────────
APP = _plantilla("az-app-service", "p0v3-linux")  # I1.5: filtro de plantilla


def test_precio_de_otra_region_se_rechaza():
    (m,) = _motivos(_comp("Azure App Service", "az-app-service"), APP.format("francecentral"))
    assert "armRegionName «francecentral» no es «swedencentral» (la región del componente)" in m
    assert not _motivos(_comp("Azure App Service", "az-app-service"), APP.format(SW))


@pytest.mark.parametrize("filtro", ["serviceName eq 'Azure Cognitive Search' and armRegionName eq 'swedencentral'",
                                    "serviceName eq 'Azure Cognitive Search' and armRegionName eq 'global'"])
def test_z3_ai_search_en_global_se_rechaza(filtro):
    (m,) = _motivos(_comp("Azure AI Search", "az-ai-search", region="global"), filtro)
    assert "se factura por región en Retail Prices" in m


def test_servicios_que_solo_se_publican_como_global():
    bot = _comp("Azure AI Bot Service", "az-bot-service", region="global")
    assert not _motivos(bot, _plantilla("az-bot-service", "canales-estandar", "Global"))
    assert "no es «Global»" in _motivos(bot, _plantilla("az-bot-service", "canales-estandar", "global"))[0]
    pl = _comp("Azure Private Link", "az-private-link")
    ok = _plantilla("az-private-link", "punto-conexion")
    assert not _motivos(pl, ok.format("Global"))
    assert "(la región de precio de Azure Private Link (az-private-link) en el catálogo)" in _motivos(
        pl, ok.format(SW))[0]


# ── Lista blanca de precios auxiliares ─────────────────────────────────────────────────────────────────────────
AUX = "serviceName eq 'Azure Private Link' and armRegionName eq 'swedencentral' and meterName eq 'Standard Private Endpoint'"


AUX_I16 = next(p["filtro"] for e in CAT["componentes"] if e["id"] == "az-private-link"
               for p in e["plantillas_precio"] if p["id"] == "punto-conexion")  # I1.6: plantilla de E


@pytest.mark.parametrize("cid,acepta", [("az-private-link", True), ("az-storage", True), ("az-cosmos-db", False)])
def test_auxiliar_de_la_lista_blanca_se_acepta_en_un_componente_identificado(cid, acepta):
    """I1.6 (REV15-3): el auxiliar va con una plantilla suya y solo en los componentes de su lista; el de antes, sin
    plantilla, ya no vale en ninguno (en az-private-link el filtro es su plantilla propia)."""
    assert (not _motivos(_comp("Componente", cid), AUX_I16)) is acepta
    assert _motivos(_comp("Componente", cid), AUX)


def test_auxiliar_no_identifica_ni_sirve_sin_catalogo_id():
    comp = _comp("Punto de conexión privado")
    assert experto.identificar_servicio(comp, CAT, [_precio(AUX)])["id"] is None
    assert "no lleva un catalogo_id del catálogo" in _motivos(comp, AUX)[0]
    assert any("admite ninguno" in m for m in _motivos(_comp("X", "az-storage"),
                                                       AUX + " and productName eq 'Private Link'"))
    assert any("no es «swedencentral»" in m for m in _motivos(_comp("X", "az-storage"), AUX.replace(SW, "francecentral")))


@pytest.mark.parametrize("servicio", ["Azure Private Endpoint", "Azure Firewall", "Private Link", "Bandwidth"])
def test_auxiliar_fuera_de_la_lista_blanca_se_rechaza(servicio):
    (m,) = _motivos(_comp("Azure Blob Storage", "az-storage"), AUX.replace("Azure Private Link", servicio))
    assert f"serviceName «{servicio}» no es el de Azure Blob Storage (az-storage) ni un precio auxiliar" in m
    assert "admite exactamente uno de: «Storage», «Azure Private Link»" in m


# ── Forma del filtro: solo «campo eq '…'» unidos con and, valores exactos ──────────────────────────────────────
ST = "serviceName eq 'Storage' and armRegionName eq 'swedencentral'"


@pytest.mark.parametrize("filtro,motivo", [
    (ST + " or serviceName eq 'Azure Cognitive Search'", "«or»"),
    (ST + " or meterName eq 'Standard S1'", "«or»"),
    ("not (" + ST + ")", "«not»"),
    (ST + " and contains(productName, 'Search')", "productName fuera de la forma"),
    (ST + " and tolower(serviceName) eq 'storage'", "serviceName fuera de la forma"),
    (ST + " and serviceName ne 'Azure Cognitive Search'", "serviceName fuera de la forma"),
    (ST + " and skuName eq 'Hot", "literal sin cerrar"),
    ("serviceName eq 'Sto\N{ZERO WIDTH SPACE}rage' and armRegionName eq 'swedencentral'",
     "invisibles o de compatibilidad"),
    ("serviceName eq '\N{FULLWIDTH LATIN CAPITAL LETTER S}torage' and armRegionName eq 'swedencentral'",
     "invisibles o de compatibilidad"),
    ("serviceName eq 'storage' and armRegionName eq 'swedencentral'", "serviceName «storage» no es el de"),
    ("serviceName eq 'Storage ' and armRegionName eq 'swedencentral'", "serviceName «Storage » no es el de"),
    ("serviceName eq 'Storage' and armRegionName eq 'SwedenCentral'", "no es «swedencentral»"),
    ("serviceName eq 'Storage'", "lleva 0 armRegionName"),
    (ST + " and armRegionName eq 'francecentral'", "lleva 2 armRegionName"),
    ("armRegionName eq 'swedencentral' and meterName eq 'Hot LRS'", "serviceName ninguno no es el de"),
])
def test_forma_y_valores_del_filtro_fuera_de_la_lista_blanca(filtro, motivo):
    motivos = _motivos(_comp("Azure Blob Storage", "az-storage"), filtro)
    assert any(motivo in m for m in motivos), motivos


@pytest.mark.parametrize("cid", ["az-speech", "az-language", "az-content-safety", "az-foundry-agent-service"])
def test_service_name_compartido_exige_su_product_name(cid):
    """Sin productName, «Foundry Tools» casaría también precios de los otros cinco servicios (un medidor de Speech
    facturado como Language en una región donde Speech está vetado)."""
    filtro = "serviceName eq 'Foundry Tools' and armRegionName eq 'swedencentral' and meterName eq 'S1 Speech to Text'"
    (m,) = _motivos(_comp("Servicio", cid), filtro)
    assert "lo comparten varios servicios del catálogo: el filtro exige el productName" in m
    assert not _motivos(_comp("Servicio", cid), _filtro(cid))


def test_service_name_compartido_sin_product_name_en_el_catalogo_no_lo_exige():
    assert not _motivos(_comp("Azure Virtual Network", "az-virtual-network"),
                        _plantilla("az-virtual-network", "ip-publica-estandar", SW))


def test_parentesis_pasan_la_forma_pero_no_son_una_plantilla():
    """I1.5: los paréntesis siguen siendo forma válida, pero el filtro tiene que ser EXACTAMENTE una plantilla."""
    (m,) = _motivos(_comp("Azure Blob Storage", "az-storage"),
                    "(serviceName eq 'Storage') and (armRegionName eq 'swedencentral') and skuName eq 'Hot LRS' "
                    "and priceType eq 'Consumption' and meterName eq 'Hot LRS Data Stored'")
    assert "el filtro no es el de ninguna plantilla de Azure Blob Storage (az-storage)" in m
    assert not _motivos(_comp("Azure Blob Storage", "az-storage"), _plantilla("az-storage", "hot-lrs-datos", SW))


def test_filtro_amplio_sin_meter_name_se_rechaza_y_la_region_se_cambia_solo_en_su_valor():
    """I1.5 (decisión 1): un filtro sin meterName (cientos de artículos y 429) ya no pasa; la plantilla se acepta en otra
    región solo si cambia únicamente el valor de armRegionName, y la réplica es la de catalogo.plantillas_precio."""
    (m,) = _motivos(_comp("Azure App Service", "az-app-service"),
                    "serviceName eq 'Azure App Service' and armRegionName eq 'swedencentral' and priceType eq 'Consumption'")
    assert "no es el de ninguna plantilla" in m
    assert not _motivos(_comp("Azure App Service", "az-app-service", region="westeurope"), APP.format("westeurope"))
    for e in CAT["componentes"]:
        for pl in e.get("plantillas_precio") or []:
            for reg in ("swedencentral", "westeurope", "global", "Sweden Central"):
                assert experto._filtro_de_plantilla(pl, e, reg) == PP.filtro_para_region(pl, e, reg), (e["id"], reg)


# ── F1-F8 de la reverificación: nombres genéricos con su id y su precio correcto, en swedencentral ───────────────
def _filtro(cid, region=SW):
    """I1.5 (decisión 1): la primera plantilla de la fila, para la región del componente."""
    e = ENT[cid]
    return PP.filtro_para_region(e["plantillas_precio"][0], e, region)


FALSOS = [("F1", "az-app-service", "Búsqueda con IA"), ("F2", "az-foundry", "Búsqueda semántica con IA generativa"),
          ("F3", "az-cosmos-db", "Búsqueda vectorial de IA"), ("F4", "az-language", "IA de búsqueda de entidades"),
          ("F5", "az-functions", "Search AI indexer"), ("F6", "az-container-apps", "Motor de búsqueda cognitiva"),
          ("F7", "az-document-intelligence", "Extracción con IA para el buscador"),
          ("F8", "az-bot-service", "Bot de búsqueda con IA")]


@pytest.mark.parametrize("caso,cid,nombre", FALSOS)
def test_f1_a_f8_no_se_vetan_ni_se_rechazan(caso, cid, nombre):
    comp = _comp(nombre, cid)
    assert not _motivos(comp, _filtro(cid)), caso
    precios = [_precio(_filtro(cid))]
    assert experto.region_no_admitida(comp, CAT, precios) is None, caso
    assert experto.aviso_fuera_de_catalogo(comp, CAT, precios) is None, caso


# ── REVSN-3: la regla de letras no latinas solo sin catalogo_id ─────────────────────────────────────────────────
@pytest.mark.parametrize("nombre", ["Portal Łódź", "API Ø", "Búsqueda con IA (検索)"])
def test_letras_latinas_no_ascii_o_no_latinas_con_su_id_y_su_precio_no_se_vetan(nombre):
    comp = _comp(nombre, "az-app-service")
    assert not _motivos(comp, _filtro("az-app-service"))
    assert experto.region_no_admitida(comp, CAT, [_precio(_filtro("az-app-service"))]) is None
    sin_id = _comp(nombre)  # sin catalogo_id sigue fallando cerrado (y sin precio, como pide la decisión)
    assert "letras no latinas" in experto.region_no_admitida(sin_id, CAT) == V.region_no_admitida(sin_id, CAT)


def test_sin_precio_y_sin_catalogo_id_en_region_con_vetos_sigue_el_aviso():
    comp = _comp("Plataforma de búsqueda con IA")
    assert _motivos(comp) == [] and experto.aviso_fuera_de_catalogo(comp, CAT, []) is not None


# ── Catálogo: lista blanca de auxiliares y región de precio ────────────────────────────────────────────────────
def test_catalogo_derivado_lleva_la_lista_blanca_y_la_region_de_precio():
    assert [a["service_name"] for a in CAT_REAL["precios_auxiliares"]] == ["Azure Private Link"]
    assert {c["id"]: c["region_precio"] for c in CAT_REAL["componentes"] if "region_precio" in c} == {
        "az-bot-service": "Global", "az-private-link": "Global"}
    fuente = derivar.cargar()
    assert all(c["region_precio_comprobacion"]["precios_items"] > 0 for c in fuente["componentes"]
               if "region_precio" in c)
    assert CAT_REAL == derivar.catalogo_componentes(fuente)


def test_un_auxiliar_que_identificaria_un_servicio_falla_en_alto():
    fuente = derivar.cargar()
    for nombre in ("Azure Cognitive Search", "azure ai search", "Foundry Tools", "AI Search"):
        fuente["precios_auxiliares"] = [{"service_name": nombre, "motivo": "prueba de colisión con el catálogo"}]
        with pytest.raises(ValueError, match="nunca puede identificar un servicio"):
            derivar.precios_auxiliares(fuente)


def test_las_instrucciones_ensenan_el_contrato_nuevo():
    texto = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md").read_text(encoding="utf-8")
    # integrador I1.7 (CAMBIOS-I17-E §5): ni filtros ni armRegionName del precio; la región es la «Región UE» de la fila
    for frase in ("«Región UE» de su fila", "Precio auxiliar `Azure Private Link`", "No tienes herramienta de precios",
                  "Solo llevan precio los componentes con `catalogo_id`", "Van SIN precio"):
        assert frase in texto, frase
    assert derivar.main(["--comprobar"]) == 0


# ── ARRSN-1: os.replace con reintento acotado y anotado, solo en Windows ───────────────────────────────────────
def _replace_que_falla(veces: int, llamadas: list):
    real = est_mod.os.replace

    def falso(origen, destino):
        llamadas.append(destino)
        if len(llamadas) <= veces:
            raise PermissionError(13, "Acceso denegado (WinError 5, simulado)")
        return real(origen, destino)
    return falso


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(est_mod, "ES_WINDOWS", True)
    monkeypatch.setattr(est_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(est_mod, "REINTENTOS_REPLACE", [])


def test_replace_denegado_dos_veces_se_reintenta_y_se_anota(windows, monkeypatch, tmp_path, capsys):
    llamadas: list = []
    monkeypatch.setattr(est_mod.os, "replace", _replace_que_falla(2, llamadas))
    est_mod.escribir_atomico(tmp_path / "estado.json", b"{}\n")
    assert (tmp_path / "estado.json").read_bytes() == b"{}\n" and len(llamadas) == 3
    assert len(est_mod.REINTENTOS_REPLACE) == 2 and "reintento 2/5" in est_mod.REINTENTOS_REPLACE[1]
    assert capsys.readouterr().err.count("AVISO: os.replace denegado") == 2
    assert [p.name for p in tmp_path.iterdir()] == ["estado.json"]  # sin temporales sueltos


def test_replace_denegado_siempre_no_se_oculta(windows, monkeypatch, tmp_path):
    llamadas: list = []
    monkeypatch.setattr(est_mod.os, "replace", _replace_que_falla(99, llamadas))
    with pytest.raises(PermissionError) as e:
        est_mod.escribir_atomico(tmp_path / "estado.json", b"{}\n")
    assert len(llamadas) == 1 + len(est_mod.ESPERAS_REPLACE) == 6
    assert any("6 veces seguidas" in n for n in getattr(e.value, "__notes__", []))
    assert list(tmp_path.iterdir()) == []  # el temporal se borra y el destino no existe


def test_fuera_de_windows_no_se_reintenta(monkeypatch, tmp_path):
    llamadas: list = []
    monkeypatch.setattr(est_mod, "ES_WINDOWS", False)
    monkeypatch.setattr(est_mod.os, "replace", _replace_que_falla(1, llamadas))
    with pytest.raises(PermissionError):
        est_mod.escribir_atomico(tmp_path / "estado.json", b"{}\n")
    assert len(llamadas) == 1


def test_otros_errores_de_replace_no_se_reintentan(windows, monkeypatch, tmp_path):
    def roto(origen, destino):
        raise FileNotFoundError(2, "no existe")
    monkeypatch.setattr(est_mod.os, "replace", roto)
    with pytest.raises(FileNotFoundError):
        est_mod.escribir_atomico(tmp_path / "estado.json", b"{}\n")
    assert est_mod.REINTENTOS_REPLACE == []


# ── REVSN-4: ningún retroceso literal (0x08) en el código ni en las pruebas ────────────────────────────────────
def test_sin_bytes_de_control_en_el_codigo_y_las_pruebas():
    rutas = [p for d in ("tests", "sandbox", "catalogo", "esquemas", "agentes") for p in (RAIZ / d).rglob("*")
             if p.is_file() and p.suffix in (".py", ".json", ".md") and "__pycache__" not in p.parts]
    rutas.append(RAIZ / "verificar_paquete.py")
    sucios = [str(p.relative_to(RAIZ)) for p in rutas if any(b < 32 and b not in (9, 10, 13) for b in p.read_bytes())]
    assert len(rutas) > 100 and sucios == [], sucios
