"""Multinube (04-11-2026, esquemas/MULTINUBE.md): el pilar como dato del núcleo y de la puerta. Sin red.

Los catálogos y las instantáneas de Google Cloud y AWS son sintéticos y mínimos, creados aquí (nunca en catalogo/).
Azure se comprueba con sus ficheros reales: el camino de siempre no cambia.
"""
from __future__ import annotations

import copy
import json
import pathlib
import shutil
import sys
from decimal import Decimal

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

import verificar_paquete as vp  # noqa: E402
from nucleo import anexo_consumo, esquema, estado, experto, hashes, textos_cliente  # noqa: E402
from nucleo.errores import EntradaInvalida, IntegridadRota  # noqa: E402

TASA = 1.1179            # BCE, 2026-11-03 (estudio de AWS y Google (no publicado) §7.2)
CONSULTA = "2026-11-04T08:00:00Z"


# ───────────────────────── datos sintéticos ─────────────────────────

def catalogo(pilar: str) -> dict:
    """Catálogo mínimo con una plantilla de precio, con la forma de esquemas/catalogo_componentes.json."""
    if pilar == "gcp":
        comp = {"id": "gcp-vertex-ai", "nombre_oficial": "Vertex AI", "capa": "ia", "service_name_precios": "Vertex AI",
                "referencia_url": "https://cloud.google.com/vertex-ai/docs", "region_ue": "europe-west1",
                "plantillas_precio": [{"id": "entrada", "concepto": "Tokens de entrada", "impulsor": "volumen",
                                       "divisor": 1000000,
                                       "filtro": "serviceName eq 'Vertex AI' and region eq 'europe-west1' and "
                                                 "skuId eq '0013-863C-A2FF'"}]}
    else:
        comp = {"id": "aws-bedrock", "nombre_oficial": "Amazon Bedrock", "capa": "ia",
                "service_name_precios": "AmazonBedrock", "referencia_url": "https://docs.aws.amazon.com/bedrock/",
                "region_ue": "eu-south-2",
                "plantillas_precio": [{"id": "entrada", "concepto": "Tokens de entrada", "impulsor": "volumen",
                                       "divisor": 1000000,
                                       "filtro": "serviceCode eq 'AmazonBedrock' and regionCode eq 'eu-south-2' and "
                                                 "sku eq 'ABCD1234EFGH5678'"}]}
    return {"schema": "preventa-catalogo/1", "version": 1, "fecha": "2026-11-04", "pilar": pilar, "componentes": [comp]}


def articulo(pilar: str, usd: float = 10.0) -> dict:
    filtro = catalogo(pilar)["componentes"][0]["plantillas_precio"][0]["filtro"]
    art = {"filtro": filtro, "unidad": "1M", "effectiveStartDate": "2026-10-01", "meterName": "Input tokens",
           "productName": "Modelo", "skuName": "Modelo entrada", "articulos_devueltos": 1, "sha256_articulo": "a" * 64}
    if pilar == "gcp":
        art.update(precio_unitario=0.25, armRegionName="europe-west1", sku_id="0013-863C-A2FF")
    else:
        art.update(precio_unitario=float(experto.eur_desde_usd(usd, TASA)), armRegionName="eu-south-2",
                   sku="ABCD1234EFGH5678", codigo_oferta="JRTCKXETXF", precio_origen_usd=usd)
    return art


def instantanea(pilar: str, **cambios) -> dict:
    clave = f"{catalogo(pilar)['componentes'][0]['id']}/entrada"
    inst = {"schema": "preventa-precios-instantanea/1", "fecha_consulta": CONSULTA, "moneda": "EUR", "pilar": pilar,
            "fuente": {"gcp": "https://cloudbilling.googleapis.com/v1/services (currencyCode=EUR)",
                       "aws": "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws (USD) y BCE eurofxref"}[pilar],
            "fuente_moneda": experto.FUENTE_MONEDA[pilar], "plantillas": {clave: articulo(pilar)}}
    if pilar == "aws":
        inst.update(tipo_bce=TASA, fecha_tipo_bce="2026-11-03")
    inst.update(cambios)
    return resellar(inst)


def resellar(inst: dict) -> dict:
    inst = {k: v for k, v in inst.items() if v is not None}
    inst["sha256"] = experto.sha256_instantanea(inst)
    return inst


def con_articulo(inst: dict, **cambios) -> dict:
    inst = copy.deepcopy(inst)
    art = next(iter(inst["plantillas"].values()))
    art.update(cambios)
    for k in [k for k, v in cambios.items() if v is None]:
        del art[k]
    return resellar(inst)


def azure_real() -> dict:
    return json.loads((RAIZ / "catalogo" / "precios_instantanea.json").read_text(encoding="utf-8"))


# ───────────────────────── pilar en el estado ─────────────────────────

def _estado(pilar: str | None) -> dict:
    alta = {"cliente": "Cliente", "codigo_cliente": "KELVARA", "seqof": "001", "titulo": "Título de prueba",
            "terminos_sensibles": ["Cliente"], "nda_confirmado": True}
    if pilar is not None:
        alta["pilar"] = pilar
    return estado.nuevo(alta, {"id": "F1", "nombre": "t.txt", "tipo": "TRANSCRIPCION", "sha256": "0" * 64, "bytes": 1,
                               "sha256_texto": "0" * 64})


def test_pilar_por_defecto_azure_y_lista_blanca():
    assert estado.pilar(_estado(None)) == "azure" and estado.pilar(None) == "azure"
    assert estado.pilar(_estado("aws")) == "aws"
    est = _estado("oracle")
    with pytest.raises(EntradaInvalida, match="Pilar no admitido"):
        estado.pilar(est)
    assert any("oracle" in e for e in estado.errores_estado(est))   # el esquema la rechaza en el borde


def test_estado_de_azure_sin_la_clave_y_brief_id_con_sigla():
    assert "pilar" not in _estado(None)["carga"]["alta"]
    assert estado.brief_id_vigente(_estado(None)).endswith("-AZ-R1")
    assert estado.brief_id_vigente(_estado("gcp")).endswith("-GCP-R1")
    assert estado.brief_id_vigente(_estado("aws")).endswith("-AWS-R1")


def test_respuesta_de_otro_pilar_en_el_estado_no_vale():
    est = _estado("gcp")
    est["carga"]["respuestas_expertos"] = {"azure": {"registrada_el": "2026-11-04", "brief_id": "B" * 10, "respuesta": {}}}
    assert any("no es el pilar de la solicitud" in e for e in estado.errores_estado(est))
    assert estado.registro_experto(est) == {}


# ───────────────────────── conversión y procedencia ─────────────────────────

def test_eur_es_usd_entre_la_tasa_nunca_multiplicado():
    assert experto.eur_desde_usd(1.1179, TASA) == Decimal("1.000000")
    assert experto.eur_desde_usd(10, TASA) == Decimal("8.945344")      # 10 / 1,1179; multiplicar daría 11,179
    with pytest.raises(ValueError):
        experto.eur_desde_usd(10, 0)


def test_azure_real_vale_sin_fuente_moneda():
    assert experto.errores_instantanea(azure_real()) == []
    assert "fuente_moneda" not in azure_real()


@pytest.mark.parametrize("cambio, motivo", [
    ({"fuente_moneda": "gcp_catalog_eur"}, "no es la de azure"),
    ({"tipo_bce": TASA, "fecha_tipo_bce": "2026-10-17"}, "solo vale en AWS"),
    ({"fuente": "https://prices.azure.com/api/retail/prices?currencyCode='USD'"}, "procedencia de la moneda"),
])
def test_azure_procedencia_rota(cambio, motivo):
    inst = resellar({**azure_real(), **cambio})
    assert any(motivo in e for e in experto.errores_instantanea(inst)), experto.errores_instantanea(inst)


@pytest.mark.parametrize("pilar", ["gcp", "aws"])
def test_instantanea_sintetica_valida(pilar):
    assert experto.errores_instantanea(instantanea(pilar)) == []
    assert esquema.validar(catalogo(pilar), esquema.cargar_pilar("catalogo_componentes", pilar)) == []
    assert esquema.validar(catalogo(pilar), esquema.cargar("catalogo_componentes")) != []   # el de Azure no lo admite
    assert anexo_consumo.errores_catalogo_pilar(catalogo(pilar), pilar) == []
    assert experto.errores_instantanea_catalogo(instantanea(pilar), catalogo(pilar)) == []


@pytest.mark.parametrize("inst, motivo", [
    (lambda: instantanea("gcp", fuente_moneda=None), "no declara la procedencia"),
    (lambda: instantanea("gcp", fuente_moneda="aws_usd_convertido_bce"), "no es la de gcp"),
    (lambda: con_articulo(instantanea("gcp"), sku_id=None), "faltan ['sku_id']"),
    (lambda: con_articulo(instantanea("gcp"), meterId="x"), "sobran ['meterId']"),
    (lambda: instantanea("aws", tipo_bce=None), "exige tipo_bce y fecha_tipo_bce"),
    (lambda: instantanea("aws", fecha_tipo_bce="2026-10-20"), "no es un día hábil del BCE"),
    (lambda: con_articulo(instantanea("aws"), precio_unitario=11.179), "no es 10.0 USD / 1.1179"),
    (lambda: con_articulo(instantanea("aws", tipo_bce=1.11795), precio_unitario=8.945034), "cuatro decimales"),
    (lambda: instantanea("aws", fecha_tipo_bce="2026-11-01"), "no es un día hábil del BCE"),   # domingo
    (lambda: con_articulo(instantanea("aws"), codigo_oferta=None), "faltan ['codigo_oferta']"),
    (lambda: con_articulo(instantanea("aws"), armRegionName="eu-west-2",
                          filtro="serviceCode eq 'AmazonBedrock' and regionCode eq 'eu-west-2' and sku eq 'ABCD1234EF'"),
     "fuera de la UE"),
    (lambda: con_articulo(instantanea("aws"), armRegionName="eu-central-2",
                          filtro="serviceCode eq 'AmazonBedrock' and regionCode eq 'eu-central-2' and sku eq 'ABCD12'"),
     "fuera de la UE"),
    (lambda: resellar({**instantanea("aws"), "pilar": "gcp"}), "no es el region del filtro"),
])
def test_instantanea_rota_falla_en_el_nucleo_y_en_la_puerta(inst, motivo):
    obj = inst()
    errores = experto.errores_instantanea(obj)
    assert any(motivo in e for e in errores), errores
    assert vp.errores_instantanea(obj, vp.dt.date(2026, 11, 4)), "la réplica de la puerta no la rechaza (LES-G-097)"


def test_la_puerta_rechaza_una_tasa_fuera_del_rango_del_esquema():
    inst = con_articulo(instantanea("aws", tipo_bce=1000.0), precio_unitario=0.01)
    assert experto.errores_instantanea(inst) and vp.errores_instantanea(inst, vp.dt.date(2026, 11, 4))


@pytest.mark.parametrize("pilar", ["gcp", "aws"])
def test_la_puerta_acepta_la_sintetica_y_mide_la_edad(pilar):
    assert vp.errores_instantanea(instantanea(pilar), vp.dt.date(2026, 11, 4), catalogo(pilar)) == []
    vieja = vp.errores_instantanea(instantanea(pilar), vp.dt.date(2026, 12, 6))
    assert any("más de 31" in e for e in vieja), vieja


def test_instantanea_de_otro_pilar_no_vale_para_la_solicitud():
    with pytest.raises(IntegridadRota, match="no vale"):
        experto.instantanea_valida(instantanea("gcp"), catalogo("gcp"), "2026-11-04", "aws")
    assert experto.instantanea_valida(instantanea("gcp"), catalogo("gcp"), "2026-11-04", "gcp")["pilar"] == "gcp"


# ───────────────────────── catálogo por pilar ─────────────────────────

def test_catalogo_de_otro_pilar_o_con_fuentes_ajenas():
    assert any("la solicitud, de azure" in e for e in anexo_consumo.errores_catalogo_pilar(catalogo("gcp"), "azure"))
    cat = catalogo("aws")
    cat["componentes"][0]["region_ue"] = "eu-west-2"
    cat["componentes"][0]["referencia_url"] = "https://learn.microsoft.com/azure/x"
    errores = anexo_consumo.errores_catalogo_pilar(cat, "aws")
    assert any("eu-west-2" in e for e in errores) and any("learn.microsoft.com" in e for e in errores)
    cat = catalogo("gcp")
    cat["componentes"][0]["id"] = "az-vertex"
    assert any("prefijo «gcp-»" in e for e in anexo_consumo.errores_catalogo_pilar(cat, "gcp"))


def test_catalogo_azure_real_sigue_valiendo():
    cat = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    assert anexo_consumo.errores_catalogo_pilar(cat, "azure") == []


def test_nombre_de_la_instantanea_junto_al_catalogo(tmp_path):
    assert anexo_consumo.nombre_instantanea(pathlib.Path("assistant-X1-catalogo_componentes.json")) == \
        "precios_instantanea.json"
    assert anexo_consumo.nombre_instantanea(pathlib.Path("assistant-X1-catalogo_componentes_aws.json")) == \
        "precios_instantanea_aws.json"
    (tmp_path / "x-catalogo_componentes_gcp.json").write_text(json.dumps(catalogo("gcp")), encoding="utf-8")
    (tmp_path / "x-precios_instantanea.json").write_text("{}", encoding="utf-8")   # la de Azure no se coge
    (tmp_path / "y-precios_instantanea_gcp.json").write_text(json.dumps(instantanea("gcp")), encoding="utf-8")
    ruta = anexo_consumo.ruta_instantanea(tmp_path / "x-catalogo_componentes_gcp.json")
    assert ruta.name == "y-precios_instantanea_gcp.json"
    assert anexo_consumo.cargar_instantanea(ruta)["pilar"] == "gcp"
    cat = anexo_consumo.cargar_catalogo(tmp_path / "x-catalogo_componentes_gcp.json", "gcp")
    assert cat["pilar"] == "gcp"
    with pytest.raises(IntegridadRota):
        anexo_consumo.cargar_catalogo(tmp_path / "x-catalogo_componentes_gcp.json")   # en Azure no vale


# ───────────────────────── respuesta del experto ─────────────────────────

def test_respuesta_de_otro_agente_o_region_fuera_de_la_ue():
    assert experto.errores_pilar_respuesta({"agente": "preventa-experto-aws", "componentes": [], "precios": []}, "aws") == []
    errores = experto.errores_pilar_respuesta({"agente": "preventa-experto-azure",
                                               "componentes": [{"id": "C-01", "region": "eu-west-2"}],
                                               "precios": [{"id": "P-01", "region": "eu-south-2"}]}, "aws")
    assert any("agente" in e for e in errores) and any("C-01" in e and "eu-west-2" in e for e in errores)
    assert not any("P-01" in e for e in errores)
    assert experto.errores_pilar_respuesta({"agente": "preventa-experto-azure"}, "azure") == []


# ───────────────────────── textos al cliente ─────────────────────────

def _anexo(pilar: str) -> dict:
    fuente, aviso = anexo_consumo.procedencia_anexo(pilar, {k: v for k, v in instantanea(pilar).items()
                                                            if k in ("pilar", "fuente_moneda", "tipo_bce",
                                                                     "fecha_tipo_bce")})
    return {"fuente": {**fuente, "consultado_el": "2026-11-04"}, "total_mensual_eur": "1.00", "total_anual_eur": "12.00",
            "lineas": [{"servicio": "S", "concepto": "Concepto", "coste_mensual_eur": "1.00", "region": "eu-south-2",
                        "effectiveStartDate": "2026-10-01"}]}, aviso


def test_frase_de_precios_por_pilar_y_conforme_al_esquema():
    patron = esquema.cargar("textos_cliente")["properties"]["consumo"]["properties"]["fuente"]
    anexo, aviso = _anexo("aws")
    frase = textos_cliente._consumo(anexo)["fuente"]
    assert frase.startswith("AWS Price List (pricing.us-east-1.amazonaws.com), región ")
    assert ("convertidos a euros con el tipo de referencia del BCE del 2026-11-03 (1 EUR = 1,1179 USD), importes "
            "orientativos") in frase
    assert "(1 EUR = 1,1179 USD)" in aviso
    anexo_g, aviso_g = _anexo("gcp")
    frase_g = textos_cliente._consumo(anexo_g)["fuente"]
    assert frase_g.startswith("Google Cloud Billing Catalog (cloudbilling.googleapis.com)") and "BCE" not in frase_g
    assert "recargo" in aviso_g
    for f in (frase, frase_g):
        assert esquema.validar(f, patron) == [], f
    azure = {"fuente": {"nombre": "Azure Retail Prices", "url": anexo_consumo.FUENTE_URL, "consultado_el": "2026-11-04"},
             "lineas": [], "total_mensual_eur": "0.00", "total_anual_eur": "0.00"}
    assert textos_cliente._consumo(azure)["fuente"] == ("Azure Retail Prices (prices.azure.com): ningún componente tiene "
                                                        "precio de consumo en esta propuesta (precios consultados el "
                                                        "2026-11-04)")


def test_sin_procedencia_no_hay_frase():
    with pytest.raises(IntegridadRota):
        anexo_consumo.procedencia_anexo("aws", {"pilar": "aws", "fuente_moneda": "aws_usd_convertido_bce"})
    with pytest.raises(IntegridadRota):
        anexo_consumo.procedencia_anexo("gcp", {"pilar": "gcp"})
    anexo, _ = _anexo("aws")
    anexo["fuente"]["fuente_moneda"] = "gcp_catalog_eur"
    with pytest.raises(IntegridadRota):
        textos_cliente._consumo(anexo)


# ───────────────────────── CLI y API ─────────────────────────

def _api_iniciar(tmp_path, monkeypatch, **kw):
    import preventa_api as P
    datos, trabajo = tmp_path / "datos", tmp_path / "trabajo"
    datos.mkdir()
    origen = RAIZ / "datos_prueba" / "transcripcion_sintetica_I1.txt"
    shutil.copyfile(origen, datos / origen.name)
    env = P.abrir(str(trabajo), datos=str(datos), tmp=str(tmp_path / "tmp"), montaje="exacto")
    r = P.iniciar(env, cliente="Kelvara Ensayos Industriales", codigo_cliente="KELVARA", seqof="001",
                  titulo="Asistente de prueba", transcripcion=origen.name, sensibles=["Kelvara"], nda_confirmado=True, **kw)
    return P, env, r


def test_iniciar_con_pilar(tmp_path, monkeypatch):
    _, _, r = _api_iniciar(tmp_path, monkeypatch, pilar="gcp")
    assert r.ok and r.estado["carga"]["alta"]["pilar"] == "gcp" and "expertos: gcp=" in r.salida


def test_iniciar_sin_pilar_o_azure_no_escribe_la_clave(tmp_path, monkeypatch):
    for sub, kw in (("a", {}), ("b", {"pilar": "azure"})):
        (tmp_path / sub).mkdir()
        _, _, r = _api_iniciar(tmp_path / sub, monkeypatch, **kw)
        assert r.ok and "pilar" not in r.estado["carga"]["alta"]


def test_iniciar_con_pilar_desconocido_falla_en_alto(tmp_path, monkeypatch):
    _, env, r = _api_iniciar(tmp_path, monkeypatch, pilar="oracle")
    assert r.rc == 2 and r.estado is None


def test_catalogo_del_pilar_por_variable_de_entorno(tmp_path, monkeypatch):
    import preventa_run
    P, env, r = _api_iniciar(tmp_path, monkeypatch, pilar="aws")
    carpeta = tmp_path / "aws"
    carpeta.mkdir()
    (carpeta / "catalogo_componentes.json").write_text(json.dumps(catalogo("aws")), encoding="utf-8")
    (carpeta / "precios_instantanea.json").write_text(json.dumps(instantanea("aws")), encoding="utf-8")
    monkeypatch.setenv("PREVENTA_CATALOGO_AWS", str(carpeta / "catalogo_componentes.json"))
    cat, sha = preventa_run._catalogo(env, r.estado)
    assert cat["pilar"] == "aws" and sha == hashes.sha256_fichero(carpeta / "catalogo_componentes.json")
    assert anexo_consumo.instantanea_vigente()["pilar"] == "aws"
    assert preventa_run.nombre_catalogo("aws") == "catalogo_componentes_aws.json"
    assert preventa_run.nombre_catalogo("azure") == "catalogo_componentes.json"


# ───────────────────────── puerta: pilar del paquete ─────────────────────────

def test_puerta_pilar_del_manifiesto_estado_instantanea_y_catalogo():
    from types import SimpleNamespace as NS
    est = {"carga": {"alta": {"pilar": "aws"}, "respuestas_expertos": {"aws": {"respuesta": {
        "componentes": [{"id": "C-01", "region": "eu-west-2"}], "precios": []}}},
        "anexo_consumo": {"lineas": [{"precio_id": "P-01", "region": "eu-central-2"}]}}}
    ctx = NS(estado=est, carga=est["carga"], manifiesto={"pilar": "aws"}, catalogo_obj=catalogo("aws"),
             respuesta=est["carga"]["respuestas_expertos"]["aws"]["respuesta"])
    errores = vp._pilar_paquete(ctx, instantanea("aws"))
    assert any("C-01" in e for e in errores) and any("P-01" in e for e in errores)
    assert not any("no coincide" in e for e in errores)
    ctx.manifiesto = {}
    assert any("no coincide" in e for e in vp._pilar_paquete(ctx, instantanea("aws")))
    azure = NS(estado={"carga": {"alta": {}}}, carga={"alta": {}}, manifiesto={}, catalogo_obj={})
    assert vp._pilar_paquete(azure, azure_real()) == []


# ───────────────────────── esquemas por pilar ─────────────────────────

@pytest.mark.parametrize("nombre", ["respuesta_experto", "respuesta_experto_completa", "brief", "catalogo_componentes",
                                    "estado", "precios_instantanea"])
def test_azure_usa_el_esquema_de_siempre(nombre):
    assert esquema.cargar_pilar(nombre, "azure") == esquema.cargar(nombre)
    with pytest.raises(EntradaInvalida):
        esquema.cargar_pilar(nombre, "oracle")


def test_variante_de_aws_del_contrato_del_experto():
    variante = esquema.cargar_pilar("respuesta_experto", "aws")
    assert variante["properties"]["agente"] == {"enum": ["preventa-experto-aws"]}
    variante.pop("title"), variante.pop("description")
    texto = json.dumps(variante, ensure_ascii=False)
    assert "^aws-[a-z0-9-]{2,40}$" in texto and "az-[" not in texto and "-AWS-R" in texto
    assert "learn\\\\.microsoft" not in texto and "docs\\\\.aws\\\\.amazon\\\\.com" in texto
    catalogo_g = esquema.cargar_pilar("catalogo_componentes", "gcp")
    assert catalogo_g["properties"]["pilar"] == {"const": "gcp"}
    assert esquema.validar({**catalogo("gcp"), "pilar": "aws"}, catalogo_g) != []


def test_catalogo_montado_de_la_api_con_y_sin_estado(tmp_path, monkeypatch):
    import preventa_api as P
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    env = P.abrir(str(vacio / "trabajo"), datos=str(vacio), tmp=str(tmp_path / "t0"), montaje="exacto")
    assert P.catalogo_montado(env)["componentes"]   # sin estado: el de Azure (Revisión: llamaba a _catalogo sin estado)
    _, env, r = _api_iniciar(tmp_path, monkeypatch, pilar="gcp")
    carpeta = tmp_path / "gcp"
    carpeta.mkdir()
    (carpeta / "catalogo_componentes.json").write_text(json.dumps(catalogo("gcp")), encoding="utf-8")
    monkeypatch.setenv("PREVENTA_CATALOGO_GCP", str(carpeta / "catalogo_componentes.json"))
    assert P.catalogo_montado(env)["pilar"] == "gcp"


def test_nubes_por_pilar_en_el_nucleo_y_en_la_puerta():
    from nucleo import suficiencia
    for pilar, bien, mal in (("azure", "Azure", "AWS"), ("gcp", "Google Cloud", "Azure"),
                             ("aws", "La solución debe vivir en AWS.", "Google Cloud")):
        assert suficiencia.nubes_fuera_de_i1([bien], pilar) == [] == vp.nubes_fuera_de_i1([bien], pilar), pilar
        assert suficiencia.nubes_fuera_de_i1([mal], pilar) and vp.nubes_fuera_de_i1([mal], pilar), pilar
    assert suficiencia.nubes_fuera_de_i1(["Azure"]) == []   # sin pilar, Azure como siempre


def test_azure_con_fuente_moneda_pero_sin_retail_eur_no_vale():
    inst = resellar({**azure_real(), "fuente_moneda": "azure_retail_eur", "fuente": "sintetica de pruebas"})
    assert any("Retail Prices" in e for e in experto.errores_instantanea(inst))
    assert vp.errores_instantanea(inst, vp.dt.date(2026, 10, 20))
