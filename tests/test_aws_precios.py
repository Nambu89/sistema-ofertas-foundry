"""Pilar AWS: lista blanca de regiones, conversión con el BCE e instantánea de precios. Sin red (fixtures en memoria)."""
import copy
import datetime
import json
import math

import pytest

from catalogo.aws import instantanea_precios as ip

AHORA = datetime.datetime(2026, 11, 4, 12, 0, tzinfo=datetime.timezone.utc)
FILTRO = ("servicecode eq 'AmazonBedrock' and regionCode eq 'eu-central-1' and usagetype eq 'EUC1-X-input-tokens'"
          " and termType eq 'OnDemand'")
BCE = (b"<?xml version='1.0' encoding='UTF-8'?><gesmes:Envelope xmlns:gesmes='http://www.gesmes.org/xml/2002-08-01'"
       b" xmlns='http://www.ecb.int/vocabulary/2002-08-01/eurofxref'><Cube><Cube time='2026-11-03'>"
       b"<Cube currency='USD' rate='1.1179'/><Cube currency='JPY' rate='171.2'/></Cube></Cube></gesmes:Envelope>")


def _producto(sku="SKU1", ut="EUC1-X-input-tokens", region="eu-central-1"):
    return {"sku": sku, "attributes": {"usagetype": ut, "regionCode": region}}


def _termino(dims, inicio="2026-10-01T00:00:00Z"):
    return {"effectiveDate": inicio, "priceDimensions": {f"r{i}": d for i, d in enumerate(dims)}}


def _dim(precio, desde="0", hasta="Inf", unidad="1K tokens"):
    return {"unit": unidad, "pricePerUnit": {"USD": precio}, "beginRange": desde, "endRange": hasta, "rateCode": "R"}


def _fichero(productos=None, terminos=None):
    productos = productos or [_producto()]
    terminos = terminos if terminos is not None else {"SKU1": {"T1": _termino([_dim("0.0011179")])}}
    return {"offerCode": "AmazonBedrock", "publicationDate": "2026-11-02T00:00:00Z", "version": "v1",
            "products": {p["sku"]: p for p in productos}, "terms": {"OnDemand": terminos}}


PLANTILLA = {"id": "x", "filtro": FILTRO, "unidad": "1K tokens", "divisor": 1000, "impulsor": "volumen"}
CAT = {"version": 1, "aviso_precios": "aviso", "componentes": [
    {"id": "aws-bedrock", "region_ue": "eu-central-1", "servicecode_precios": "AmazonBedrock",
     "plantillas_precio": [PLANTILLA]}]}


# --- lista blanca de regiones -----------------------------------------------------------------------------------

@pytest.mark.parametrize("region", ip.REGIONES_UE)
def test_regiones_ue_admitidas(region):
    assert ip.region_ue(region) == region


@pytest.mark.parametrize("region", ["eu-west-2", "eu-central-2", "eu-central-1-ham-1", "eu-west-3-wl1-cmn1",
                                    "eusc-de-east-1", "us-east-1", "EU-CENTRAL-1", " eu-central-1", "", None, 1])
def test_regiones_fuera_de_la_ue_rechazadas(region):
    with pytest.raises(ip.ErrorInstantanea):
        ip.region_ue(region)


def test_lista_blanca_exacta():
    assert ip.REGIONES_UE == ("eu-central-1", "eu-west-1", "eu-west-3", "eu-north-1", "eu-south-1", "eu-south-2")


def test_filtro_con_region_fuera_de_la_ue_rechazado():
    assert any("fuera de la lista blanca" in x for x in ip.problemas_filtro(FILTRO.replace("eu-central-1", "eu-west-2")))
    with pytest.raises(ip.ErrorInstantanea):
        ip.url_fichero("AmazonBedrock", "eu-central-2")


def test_filtro_forma():
    assert ip.problemas_filtro(FILTRO) == []
    assert ip.problemas_filtro(FILTRO.replace("OnDemand", "Reserved"))
    assert ip.problemas_filtro("regionCode eq 'eu-central-1' and servicecode eq 'AmazonBedrock'")  # orden y faltan
    assert ip.problemas_filtro("servicecode = 'AmazonBedrock'")


# --- conversión EUR = USD / tasa --------------------------------------------------------------------------------

def test_conversion_divide_por_la_tasa():
    assert ip.a_eur("1.1179", 1.1179) == 1.0
    assert ip.a_eur("0.000429", 1.1179) == pytest.approx(0.000429 / 1.1179, rel=1e-11)
    assert ip.a_eur("0.000429", 1.1179) < 0.000429  # multiplicar en lugar de dividir inflaría el precio


@pytest.mark.parametrize("malo", ["NaN", "Infinity", "-Infinity", "-1", "abc", float("nan"), float("inf"), True, None])
def test_conversion_rechaza_no_finitos(malo):
    with pytest.raises(ip.ErrorInstantanea):
        ip.a_eur(malo, 1.1)
    with pytest.raises(ip.ErrorInstantanea):
        ip.a_eur("1", malo)


def test_conversion_rechaza_tasa_cero():
    with pytest.raises(ip.ErrorInstantanea):
        ip.a_eur("1", "0")


def test_bce_lee_usd_y_su_fecha():
    assert ip.parsear_bce(BCE, datetime.date(2026, 11, 4)) == (1.1179, "2026-11-03")


@pytest.mark.parametrize("xml", [
    b"no es xml",
    BCE.replace(b"currency='USD'", b"currency='GBP'"),
    BCE.replace(b"rate='1.1179'", b"rate='NaN'"),
    BCE.replace(b"rate='1.1179'", b"rate='Infinity'"),
    BCE.replace(b"rate='1.1179'", b"rate='0'"),
    BCE.replace(b"time='2026-11-03'", b"time='2026-13-03'"),
])
def test_bce_falla_en_alto(xml):
    with pytest.raises(ip.ErrorInstantanea):
        ip.parsear_bce(xml, datetime.date(2026, 11, 4))


def test_bce_antiguo_o_futuro_rechazado():
    with pytest.raises(ip.ErrorInstantanea, match="días"):
        ip.parsear_bce(BCE, datetime.date(2026, 11, 20))
    with pytest.raises(ip.ErrorInstantanea, match="días"):
        ip.parsear_bce(BCE, datetime.date(2026, 11, 1))


def test_sin_bce_no_se_genera_nada():
    def sin_bce(notas, hoy):
        raise ip.ErrorInstantanea("red: BCE caído")
    llamado = []
    with pytest.raises(ip.ErrorInstantanea, match="BCE"):
        ip.generar(CAT, AHORA, fichero=lambda *a: llamado.append(a), bce=sin_bce)
    assert llamado == []  # ni siquiera se descargan precios


# --- resolución de plantillas -----------------------------------------------------------------------------------

def test_resuelve_y_convierte():
    e = ip.resolver("aws-bedrock/x", PLANTILLA, _fichero(), 1.1179, AHORA)
    assert e["precio_origen"] == 0.0011179 and e["precio_unitario"] == pytest.approx(0.001)
    assert e["moneda_origen"] == "USD" and e["regionCode"] == "eu-central-1" and "tramos" not in e


def test_tramos():
    terminos = {"SKU1": {"T1": _termino([_dim("0.2", "0", "100"), _dim("0.1", "100", "Inf")])}}
    e = ip.resolver("k", PLANTILLA, _fichero(terminos=terminos), 2.0, AHORA)
    assert e["tramos"] == [{"desde": 0.0, "precio_unitario": 0.1, "precio_origen": 0.2},
                           {"desde": 100.0, "precio_unitario": 0.05, "precio_origen": 0.1}]


@pytest.mark.parametrize("fichero, motivo", [
    (_fichero(productos=[_producto(), _producto("SKU2")]), "2 productos"),
    (_fichero(productos=[_producto(region="eu-central-1-ham-1")]), "0 productos"),
    (_fichero(terminos={"SKU1": {"T1": _termino([_dim("NaN")])}}), "no finito"),
    (_fichero(terminos={"SKU1": {"T1": _termino([_dim("Infinity")])}}), "no finito"),
    (_fichero(terminos={"SKU1": {"T1": _termino([_dim("0.1", unidad="Requests")])}}), "unidad"),
    (_fichero(terminos={"SKU1": {"T1": _termino([{**_dim("0.1"), "pricePerUnit": {"CNY": "1"}}])}}), "monedas"),
    (_fichero(terminos={"SKU1": {"T1": _termino([_dim("0.1", "5")])}}), "no en 0"),
    (_fichero(terminos={"SKU1": {"T1": _termino([_dim("0.2", "0", "100"), _dim("0.1", "200")])}}), "contiguos"),
    (_fichero(terminos={"SKU1": {"T1": _termino([_dim("0.1")]), "T2": _termino([_dim("0.2")])}}), "2 términos"),
    (_fichero(terminos={"SKU1": {"T1": _termino([_dim("0.1")], "2027-01-01T00:00:00Z")}}), "0 términos"),
    (_fichero(terminos={}), "0 términos"),
])
def test_resolver_falla_en_alto(fichero, motivo):
    with pytest.raises(ip.ErrorInstantanea, match=motivo):
        ip.resolver("k", PLANTILLA, fichero, 1.1, AHORA)


def test_generar_y_problemas():
    inst = ip.generar(CAT, AHORA, fichero=lambda s, r, n: _fichero(), bce=lambda n, h: (1.1179, "2026-11-03"))
    assert inst["conversion"] == {"fuente": ip.URL_BCE, "regla": "EUR = USD / tipo_bce", "tipo_bce": 1.1179,
                                  "fecha_tipo_bce": "2026-11-03"}
    assert ip.problemas(inst, CAT, datetime.date(2026, 11, 4)) == []
    assert ip.problemas(inst, CAT, datetime.date(2026, 12, 15))  # más de 31 días
    alterada = copy.deepcopy(inst)
    alterada["plantillas"]["aws-bedrock/x"]["precio_unitario"] = 9.0
    assert "la huella sha256 no cuadra con el contenido" in ip.problemas(alterada, CAT)
    nan = copy.deepcopy(inst)
    nan["plantillas"]["aws-bedrock/x"]["precio_unitario"] = math.nan
    assert ip.problemas(nan, CAT)  # NaN rechazado (la huella no se puede ni calcular)
    with pytest.raises(ValueError):
        ip.serializar(nan)


def test_generar_acumula_todos_los_fallos_y_no_escribe(tmp_path):
    cat = copy.deepcopy(CAT)
    cat["componentes"][0]["plantillas_precio"].append(dict(PLANTILLA, id="y", unidad="Requests", divisor=1))
    with pytest.raises(ip.ErrorInstantanea, match="1 de 2 plantillas"):
        ip.generar(cat, AHORA, fichero=lambda s, r, n: _fichero(), bce=lambda n, h: (1.1, "2026-11-03"))
    destino = tmp_path / "inst.json"
    with pytest.raises(ip.ErrorInstantanea):
        ip.escribir({"schema": "otro"}, CAT, destino)
    assert not destino.exists()


def test_instantanea_guardada_valida_para_el_catalogo():
    cat = json.loads(ip.CATALOGO.read_text(encoding="utf-8"))
    inst = json.loads(ip.DESTINO.read_text(encoding="utf-8"))
    fecha = datetime.date.fromisoformat(inst["fecha_consulta"][:10])
    assert ip.problemas(inst, cat, fecha) == []
    assert inst["regiones_ue"] == list(ip.REGIONES_UE)
    assert all(e["regionCode"] in ip.REGIONES_UE for e in inst["plantillas"].values())


def test_precio_eur_incoherente_aunque_se_reselle():
    inst = ip.generar(CAT, AHORA, fichero=lambda s, r, n: _fichero(), bce=lambda n, h: (1.1179, "2026-11-03"))
    alterada = copy.deepcopy(inst)
    alterada["plantillas"]["aws-bedrock/x"]["precio_unitario"] = 0.0011179  # USD copiado como EUR
    alterada["sha256"] = ip.huella(alterada)
    assert any("precio_origen / tipo_bce" in x for x in ip.problemas(alterada, CAT))
    vieja = copy.deepcopy(inst)
    vieja["conversion"]["fecha_tipo_bce"] = "2026-10-01"
    vieja["sha256"] = ip.huella(vieja)
    assert any("tipo del BCE" in x for x in ip.problemas(vieja, CAT))


def test_entero_enorme_no_revienta():
    inst = ip.generar(CAT, AHORA, fichero=lambda s, r, n: _fichero(), bce=lambda n, h: (1.1179, "2026-11-03"))
    inst["conversion"]["tipo_bce"] = 10 ** 400
    assert any("tipo_bce no válido" in x for x in ip.problemas(inst, CAT))
