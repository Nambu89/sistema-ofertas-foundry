"""Instantánea de precios de Google Cloud (catalogo/gcp/instantanea_precios.py), sin red."""
import datetime
import io
import json
import math
import urllib.error

import pytest

from catalogo.gcp import instantanea_precios as ip

AHORA = datetime.datetime(2026, 11, 4, 12, 0, tzinfo=datetime.timezone.utc)
CLAVE = "AIza" + "SyFALSA_de_prueba_0123456789abcdefghij"   # falsa, partida para el barrido de publicación
SVC, SKU1, SKU2 = "152E-C115-5142", "9CE1-91CC-5746", "707E-670F-F8BA"


def _plantilla(sku=SKU1, region="europe-southwest1", concepto="CPU Madrid", unidad="s", **kw):
    p = {"id": "cpu", "filtro": f"serviceId eq '{SVC}' and skuId eq '{sku}' and serviceRegion eq '{region}'",
         "concepto": concepto, "impulsor": "tiempo", "divisor": 1, "unidad_uso": unidad,
         "fuente_sku": "https://cloud.google.com/skus/sku-groups/cloud-run"}
    p.update(kw)
    return p


def _cat(*plantillas, region="europe-southwest1"):
    return {"version": 1, "componentes": [{"id": "gcp-cloud-run", "region_ue": region, "plantillas_precio": list(plantillas)}]}


def _sku(sku=SKU1, concepto="CPU Madrid", regiones=("europe-southwest1",), unidad="s", tramos=None, moneda="EUR", **kw):
    tramos = tramos if tramos is not None else [
        {"startUsageAmount": 0, "unitPrice": {"currencyCode": moneda, "units": "0", "nanos": 0}},
        {"startUsageAmount": 180000, "unitPrice": {"currencyCode": moneda, "units": "0", "nanos": 21600}}]
    s = {"skuId": sku, "description": concepto, "category": {"usageType": "OnDemand"}, "serviceRegions": list(regiones),
         "pricingInfo": [{"effectiveTime": "2026-11-01T00:00:00Z", "currencyConversionRate": 0.9,
                          "pricingExpression": {"usageUnit": unidad, "displayQuantity": 1, "tieredRates": tramos}}]}
    s.update(kw)
    return s


# ───────────── lista blanca de regiones ─────────────

def test_lista_blanca_ue_explicita_sin_londres_ni_zurich():
    assert len(ip.REGIONES_UE) == 11
    assert "europe-west2" not in ip.REGIONES_UE and "europe-west6" not in ip.REGIONES_UE
    assert "europe-southwest1" in ip.REGIONES_UE and ip.MULTIRREGIONES_UE == {"eu"}


@pytest.mark.parametrize("region", ["europe-west2", "europe-west6", "us-central1", "europe", "EU", "global", ""])
def test_region_fuera_de_la_lista_blanca_se_rechaza(region):
    assert ip.problemas_region({"id": "x", "region_ue": region, "plantillas_precio": [{}]})


def test_global_solo_sin_plantillas_y_region_precio_solo_global():
    assert ip.problemas_region({"id": "x", "region_ue": "global"}) == []
    assert ip.problemas_region({"id": "x", "region_ue": "eu", "region_precio": "global"}) == []
    assert ip.problemas_region({"id": "x", "region_ue": "eu", "region_precio": "europe-west2"})


def test_serviceRegion_debe_ser_la_de_su_fila_o_global_declarado():
    fila = {"id": "gcp-cloud-run", "region_ue": "europe-southwest1"}
    assert ip.problemas_plantilla(fila, _plantilla(region="europe-west2"))
    assert ip.problemas_plantilla(fila, _plantilla(region="global"))
    assert ip.problemas_plantilla(fila, _plantilla(region="global", region_precio="global")) == []


# ───────────── EUR, NaN e Infinity ─────────────

def test_precio_que_no_es_eur_se_rechaza():
    with pytest.raises(ip.ErrorInstantanea, match="EUR"):
        ip.dinero_eur({"currencyCode": "USD", "units": "1", "nanos": 0})
    with pytest.raises(ip.ErrorInstantanea, match="EUR"):
        ip.resolver("k", _plantilla(), _sku(moneda="USD"), AHORA)


def test_dinero_eur_suma_units_y_nanos_y_rechaza_signos_mezclados():
    assert ip.dinero_eur({"currencyCode": "EUR", "units": "2", "nanos": 500000000}) == 2.5
    for malo in ({"currencyCode": "EUR", "units": "1", "nanos": -1}, {"currencyCode": "EUR", "units": 1},
                 {"currencyCode": "EUR", "units": "-1", "nanos": 0}, {"currencyCode": "EUR", "nanos": True}):
        with pytest.raises(ip.ErrorInstantanea):
            ip.dinero_eur(malo)


def test_json_con_nan_o_infinity_se_rechaza():
    for texto in (b'{"a": NaN}', b'{"a": Infinity}', b'{"a": -Infinity}'):
        with pytest.raises(ValueError):
            ip.leer_json(texto)


@pytest.mark.parametrize("valor", [math.nan, math.inf, -1])
def test_tramo_o_tasa_no_finitos_se_rechazan(valor):
    tramos = [{"startUsageAmount": valor, "unitPrice": {"currencyCode": "EUR", "units": "1", "nanos": 0}}]
    with pytest.raises(ip.ErrorInstantanea):
        ip.resolver("k", _plantilla(), _sku(tramos=tramos), AHORA)
    s = _sku()
    s["pricingInfo"][0]["currencyConversionRate"] = valor
    with pytest.raises(ip.ErrorInstantanea):
        ip.resolver("k", _plantilla(), s, AHORA)


def test_instantanea_con_nan_no_vale():
    cat = _cat(_plantilla())
    inst = ip.generar(cat, lambda s: [_sku()], ahora=AHORA)
    inst["plantillas"]["gcp-cloud-run/cpu"]["precio_unitario"] = math.nan
    assert any("NaN" in x or "precio_unitario" in x for x in ip.problemas(inst, cat))


# ───────────── resolución de un SKU ─────────────

def test_resolver_con_tramos():
    e = ip.resolver("k", _plantilla(), _sku(), AHORA)
    assert e["precio_unitario"] == 0 and e["tramos"][1] == {"desde": 180000.0, "precio_unitario": 2.16e-05}
    assert e["unidad"] == "s" and e["tasa_conversion"] == 0.9 and e["sku_id"] == SKU1


@pytest.mark.parametrize("cambio, motivo", [
    ({"concepto": "Otra cosa"}, "descripción"),
    ({"regiones": ("europe-west1",)}, "serviceRegions"),
    ({"unidad": "h"}, "unidad"),
    ({"tramos": [{"startUsageAmount": 5, "unitPrice": {"currencyCode": "EUR", "units": "1", "nanos": 0}}]}, "tramos"),
    ({"tramos": []}, "tieredRates"),
])
def test_resolver_falla_en_alto(cambio, motivo):
    with pytest.raises(ip.ErrorInstantanea, match=motivo):
        ip.resolver("k", _plantilla(), _sku(**cambio), AHORA)


def test_unidad_uso_sin_declarar_falla_y_dice_la_real():
    with pytest.raises(ip.ErrorInstantanea, match="la API da «s»"):
        ip.resolver("k", _plantilla(unidad=None), _sku(), AHORA)


def test_pricinginfo_que_no_es_unico_o_futuro_falla():
    s = _sku()
    s["pricingInfo"] = s["pricingInfo"] * 2
    with pytest.raises(ip.ErrorInstantanea, match="exactamente uno"):
        ip.resolver("k", _plantilla(), s, AHORA)
    s = _sku()
    s["pricingInfo"][0]["effectiveTime"] = "2027-01-01T00:00:00Z"
    with pytest.raises(ip.ErrorInstantanea, match="futuro"):
        ip.resolver("k", _plantilla(), s, AHORA)


def test_generar_reune_todos_los_fallos_y_no_devuelve_nada():
    cat = _cat(_plantilla(), _plantilla(sku=SKU2, id="mem", concepto="Mem"))
    with pytest.raises(ip.ErrorInstantanea) as e:
        ip.generar(cat, lambda s: [_sku()], ahora=AHORA)
    assert "1 de 2" in str(e.value) and SKU2 in str(e.value)


def test_generar_escribir_y_comprobar(tmp_path):
    cat = _cat(_plantilla(), _plantilla(sku=SKU2, id="mem", concepto="Mem"))
    inst = ip.generar(cat, lambda s: [_sku(), _sku(sku=SKU2, concepto="Mem")], ahora=AHORA)
    assert inst["procedencia"] == "gcp_catalog_eur" and inst["moneda"] == "EUR"
    assert ip.problemas(inst, cat, datetime.date(2026, 11, 5)) == []
    assert ip.problemas(inst, cat, datetime.date(2026, 12, 6))  # más de 31 días
    destino = tmp_path / "precios_instantanea.json"
    ip.escribir(inst, cat, destino)
    assert json.loads(destino.read_text(encoding="utf-8")) == inst
    inst["plantillas"]["gcp-cloud-run/cpu"]["precio_unitario"] = 1
    assert "la huella sha256 no cuadra con el contenido" in ip.problemas(inst, cat)


# ───────────── red: respuestas parciales y clave ─────────────

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _abridor(*cuerpos, vistas=None):
    cola = list(cuerpos)

    def abrir(req, timeout=60):
        if vistas is not None:
            vistas.append(req)
        c = cola.pop(0)
        if isinstance(c, Exception):
            raise c
        return _Resp(c if isinstance(c, bytes) else json.dumps(c).encode())
    return abrir


@pytest.mark.parametrize("cuerpo", [{}, {"skus": None}, {"skus": [], "error": {"code": 500}}, [1], b'{"skus": [NaN]}'])
def test_http_200_parcial_se_rechaza(cuerpo):
    with pytest.raises(ip.ErrorInstantanea):
        ip.consultar_servicio(SVC, CLAVE, [], abrir=_abridor(cuerpo), pausa=0)


def test_paginacion_completa_y_token_repetido():
    skus = ip.consultar_servicio(SVC, CLAVE, [], abrir=_abridor({"skus": [{"skuId": "a"}], "nextPageToken": "t1"},
                                                                {"skus": [{"skuId": "b"}]}), pausa=0)
    assert [s["skuId"] for s in skus] == ["a", "b"]
    with pytest.raises(ip.ErrorInstantanea, match="paginación"):
        ip.consultar_servicio(SVC, CLAVE, [], abrir=_abridor({"skus": [], "nextPageToken": "t"},
                                                             {"skus": [], "nextPageToken": "t"}), pausa=0)


def test_clave_en_cabecera_nunca_en_la_url():
    vistas = []
    ip.consultar_servicio(SVC, CLAVE, [], abrir=_abridor({"skus": []}, vistas=vistas), pausa=0)
    assert CLAVE not in vistas[0].full_url and vistas[0].get_header("X-goog-api-key") == CLAVE
    assert "currencyCode=EUR" in vistas[0].full_url


def test_clave_nunca_en_el_error_aunque_la_devuelva_google():
    err = urllib.error.HTTPError("https://x", 400, "Bad", {}, io.BytesIO(f"API key {CLAVE} not valid".encode()))
    with pytest.raises(ip.ErrorInstantanea) as e:
        ip.consultar_servicio(SVC, CLAVE, [], abrir=_abridor(err), pausa=0)
    assert CLAVE not in str(e.value) and "OMITIDO" in str(e.value)
    assert CLAVE[:12] not in ip.tapar(f"otra clave {CLAVE}")


@pytest.mark.parametrize("entorno", [{}, {ip.VAR_CLAVE: ""}, {ip.VAR_CLAVE: "   "}])
def test_clave_ausente_falla_en_alto_con_mensaje_claro(entorno, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ip, "DESTINO", tmp_path / "precios_instantanea.json")
    with pytest.raises(ip.ErrorInstantanea, match=ip.VAR_CLAVE):
        ip.clave_api(entorno)
    assert ip.main([], entorno=entorno) == 2
    salida = capsys.readouterr().out
    assert ip.VAR_CLAVE in salida and "NO SE ESCRIBE NADA" in salida
    assert not (tmp_path / "precios_instantanea.json").exists()


def test_main_no_imprime_la_clave_ni_escribe_si_falla(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ip, "DESTINO", tmp_path / "precios_instantanea.json")
    original = ip.consultar_servicio
    err = urllib.error.HTTPError("https://x", 403, "No", {}, io.BytesIO(f"bad key={CLAVE}".encode()))
    monkeypatch.setattr(ip, "consultar_servicio", lambda s, c, n, pausa: original(s, c, n, abrir=_abridor(err), pausa=0))
    assert ip.main(["--pausa", "0"], entorno={ip.VAR_CLAVE: CLAVE}) == 2
    salida = capsys.readouterr().out
    assert CLAVE not in salida and "HTTP 403" in salida
    assert not (tmp_path / "precios_instantanea.json").exists()


def test_comprobar_sin_instantanea_real_da_rc_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ip, "DESTINO", tmp_path / "no_existe.json")
    assert ip.main(["--comprobar"]) == 1
    assert "NO VERIFICADO" in capsys.readouterr().out


def test_tipos_json_inesperados_fallan_en_alto_sin_traceback():
    cat = _cat(_plantilla())
    for cambio in ({"category": "OnDemand"}, {"pricingInfo": [{"pricingExpression": "x", "effectiveTime":
                                                               "2026-11-01T00:00:00Z", "currencyConversionRate": 1}]}):
        with pytest.raises(ip.ErrorInstantanea, match="forma inesperada|pricingExpression|usageUnit"):
            ip.generar(cat, lambda s, c=cambio: [_sku(**c)], ahora=AHORA)


def test_no_se_sigue_ninguna_redireccion_con_la_clave():
    import urllib.request
    h = ip._SinRedirecciones()
    req = urllib.request.Request("https://cloudbilling.googleapis.com/v1/x", headers={"X-Goog-Api-Key": CLAVE})
    assert h.redirect_request(req, None, 302, "Found", {}, "https://otro.example/") is None
    assert ip.consultar_servicio.__defaults__[0] is ip._ABRIR
