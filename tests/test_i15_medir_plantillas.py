"""I1.5, papel E: el medidor de plantillas falla en alto (sin red: la API se simula)."""
from __future__ import annotations

import io
import json
import pathlib
import sys
import urllib.error

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from catalogo import medir_plantillas as mp  # noqa: E402

ENTRADA = {"id": "az-x", "service_name_precios": "Svc", "producto_precios": None, "region_ue": "swedencentral"}
FILTRO = ("serviceName eq 'Svc' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and skuName eq 'S1' "
          "and meterName eq 'S1 Unit'")


def _item(precio=1.0, tramo=0.0, medidor="S1 Unit", region="swedencentral", meter_id="m1"):
    return {"serviceName": "Svc", "armRegionName": region, "productName": "P", "skuName": "S1", "meterName": medidor,
            "unitOfMeasure": "1 Hour", "retailPrice": precio, "tierMinimumUnits": tramo, "meterId": meter_id}


def _api(eur: list[list[dict]], usd: list[dict], sigue=False):
    llamadas = {"EUR": iter(eur)}

    def falsa(filtro, moneda, notas, pausa):
        items = next(llamadas["EUR"]) if moneda == "EUR" else usd
        return 200, 700, items, sigue
    return falsa


def test_plantilla_buena_sin_errores(monkeypatch):
    monkeypatch.setattr(mp, "consultar", _api([[_item()]] * 3, [_item(1.136)]))
    r = mp.medir({"id": "s1", "filtro": FILTRO, "impulsor": "tiempo", "divisor": 1}, ENTRADA, 3, [], 0)
    assert r["errores"] == [] and r["comprobacion"]["sku"] == "S1" and r["comprobacion"]["articulos"] == 1 and r["comprobacion"]["bytes"] == [700] * 3


@pytest.mark.parametrize("eur, sigue, motivo", [
    ([[_item(), _item(medidor="Otro", meter_id="m2")]] * 3, False, "no es un medidor único"),
    ([[_item()], [_item()], [_item(precio=2.0)]], False, "distintos"),
    ([[_item(precio=0.0)]] * 3, False, "gratuito=False"),
    ([[_item(region="westeurope")]] * 3, False, "otra región"),
    ([[]] * 3, False, "0 artículos"),
    ([[_item()]] * 3, True, "NextPageLink"),
    ([[_item(tramo=float(i), meter_id=f"m{i}") for i in range(6)]] * 3, False, "6 artículos"),
])
def test_medir_falla_en_alto(monkeypatch, eur, sigue, motivo):
    monkeypatch.setattr(mp, "consultar", _api(eur, [_item(1.136)], sigue))
    r = mp.medir({"id": "s1", "filtro": FILTRO}, ENTRADA, 3, [], 0)
    assert any(motivo in e for e in r["errores"]), r["errores"]


def test_gratuita_declarada_con_precio_cero_es_valida(monkeypatch):
    monkeypatch.setattr(mp, "consultar", _api([[_item(precio=0.0)]] * 3, [_item(0.0)]))
    p = {"id": "s1", "filtro": FILTRO, "gratuito": True, "impulsor": "tiempo", "divisor": 1}
    assert mp.medir(p, ENTRADA, 3, [], 0)["errores"] == []


def test_desvio_por_redondeo_en_eur(monkeypatch):
    buenos = [{"ratios": [(0.88, 1.0)], "errores": []}, {"ratios": [(8.8, 10.0)], "errores": []}]
    redondeado = {"ratios": [(0.0001, 0.000143)], "errores": []}
    cero = {"ratios": [(0.0, 0.000024)], "errores": []}
    sin_usd = {"ratios": [(0.5, None)], "errores": []}
    tipo = mp.desvios(buenos + [redondeado, cero, sin_usd])
    assert tipo == pytest.approx(0.88)
    assert all(not r["errores"] for r in buenos)
    assert redondeado["errores"] and cero["errores"] and "USD" in sin_usd["errores"][0]


def _http_error(codigo, cabeceras=None):
    return urllib.error.HTTPError("u", codigo, "x", cabeceras or {}, io.BytesIO(b""))


def test_429_espera_y_reintenta_anotado(monkeypatch):
    respuestas = [_http_error(429, {"Retry-After": "0"}), None]

    class R(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        x = respuestas.pop(0)
        if x is not None:
            raise x
        return R(json.dumps({"Items": [_item()], "NextPageLink": None}).encode())
    monkeypatch.setattr(mp.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(mp.time, "sleep", lambda s: None)
    notas: list[str] = []
    http, n, items, sigue = mp.consultar(FILTRO, "EUR", notas, 0)
    assert (http, len(items), sigue) == (200, 1, False) and len(notas) == 1 and "429" in notas[0]


def test_un_400_no_se_reintenta(monkeypatch):
    llamadas = []

    def urlopen(req, timeout):
        llamadas.append(1)
        raise _http_error(400)
    monkeypatch.setattr(mp.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(mp.time, "sleep", lambda s: None)
    assert mp.consultar("Azure Bot Service", "EUR", [], 0)[0] == 400 and len(llamadas) == 1


def test_main_no_escribe_el_catalogo_si_algo_falla(monkeypatch, tmp_path):
    cat = {"componentes": [{**ENTRADA, "plantillas_precio": [{"id": "s1", "concepto": "c", "filtro": FILTRO}]}]}
    ruta = tmp_path / "cat.json"
    ruta.write_text(json.dumps(cat), encoding="utf-8")
    antes = ruta.read_bytes()
    monkeypatch.setattr(mp, "CATALOGO", ruta)
    monkeypatch.setattr(mp, "consultar", _api([[_item(precio=0.0)]] * 3, [_item(0.0)]))
    assert mp.main(["--escribir", "--pausa", "0", "--evidencia", str(tmp_path / "e.json")]) == 1
    assert ruta.read_bytes() == antes and json.loads((tmp_path / "e.json").read_text(encoding="utf-8"))["fallos"] == 1


def test_main_rechaza_argumentos_absurdos():
    for args in (["--consultas", "0"], ["--pausa", "nan"], ["--pausa", "-1"]):
        with pytest.raises(SystemExit):
            mp.main(args)
