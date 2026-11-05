"""I1.7, papel E: instantánea de precios al desplegar (catalogo/instantanea_precios.py). Sin red: la API se simula."""
from __future__ import annotations

import copy
import datetime as dt
import json

import pytest

from catalogo import derivar
from catalogo import instantanea_precios as ip

CAT = derivar.cargar()
AHORA = dt.datetime(2026, 10, 13, 9, 0, tzinfo=dt.timezone.utc)
VIVA = json.loads(ip.DESTINOS[0].read_text(encoding="utf-8"))
FILTRO = ("serviceName eq 'Foundry Models' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and "
          "meterName eq '6-luna ShortCo Inp Std DZ 1M Tokens'")


def art(**cambios) -> dict:
    a = {"serviceName": "Foundry Models", "armRegionName": "swedencentral", "type": "Consumption", "currencyCode": "EUR",
         "meterName": "6-luna ShortCo Inp Std DZ 1M Tokens", "productName": "Azure OpenAI GPT6", "meterId": "m1",
         "skuName": "6-luna ShortCo Inp Std DZ", "unitOfMeasure": "1M", "retailPrice": 0.1056, "tierMinimumUnits": 0.0,
         "effectiveStartDate": "2026-09-01T00:00:00Z"}
    return a | cambios


def test_resuelve_un_articulo_vigente():
    e = ip.resolver("az-foundry/x", FILTRO, [art(), art()], AHORA)  # duplicado exacto: un solo artículo
    assert (e["precio_unitario"], e["unidad"], e["articulos_devueltos"]) == (0.1056, "1M", 2) and "tramos" not in e


@pytest.mark.parametrize("items, motivo", [
    ([], "0 artículos"),
    ([art(meterId="m2", retailPrice=1.0), art()], "medidores"),
    ([art(retailPrice=0.2), art()], "mismo tramo"),
    ([art(tierMinimumUnits=5.0)], "no en 0"),
    ([art(retailPrice=float("nan"))], "no finito"),
    ([art(retailPrice=-1)], "no finito"),
    ([art(armRegionName="westeurope")], "no casa"),
    ([art(currencyCode="USD")], "no casa"),
    ([art(effectiveStartDate="2027-01-01T00:00:00Z")], "ningún artículo vigente"),
    ([art(effectiveStartDate="ayer")], "ilegible")])
def test_falla_en_alto_si_no_resuelve_a_un_articulo(items, motivo):
    with pytest.raises(ip.ErrorInstantanea, match=motivo):
        ip.resolver("az-foundry/x", FILTRO, items, AHORA)


def test_tramos_y_articulos_futuros():
    e = ip.resolver("k", FILTRO, [art(), art(tierMinimumUnits=5.0, retailPrice=0.05),
                                  art(retailPrice=0.2, effectiveStartDate="2027-01-01T00:00:00Z")], AHORA)
    assert e["tramos"] == [{"desde": 0.0, "precio_unitario": 0.1056}, {"desde": 5.0, "precio_unitario": 0.05}]
    assert e["articulos_futuros_descartados"] == 1 and e["precio_unitario"] == 0.1056


def _api(cat):
    """Respuesta simulada coherente con cada plantilla del catálogo."""
    def consulta(filtro, notas):
        d = dict(ip.condiciones(filtro))
        p = next(p for _, _, p in ip.plantillas(cat) if p["filtro"] == filtro)
        return [art(**{ip.CAMPO_ARTICULO.get(k, k): v for k, v in d.items()}, unitOfMeasure=p["comprobacion"]["unidad"])]
    return consulta


def test_generar_y_escribir_dos_copias_iguales(tmp_path):
    inst = ip.generar(CAT, _api(CAT), AHORA)
    assert ip.problemas(inst, CAT, AHORA.date()) == [] and inst["fecha_consulta"] == "2026-10-13T09:00:00Z"
    destinos = (tmp_path / "a.json", tmp_path / "b.json")
    ip.escribir(inst, CAT, destinos)
    assert destinos[0].read_bytes() == destinos[1].read_bytes() and ip.comprobar(CAT, AHORA.date(), destinos) == []
    destinos[1].write_bytes(destinos[1].read_bytes() + b" ")
    assert "no son iguales" in ip.comprobar(CAT, AHORA.date(), destinos)[0]


def test_una_plantilla_que_no_resuelve_hace_fallar_generar_con_todos_los_fallos():
    """Que además no se escriba nada lo prueba test_main_con_una_plantilla_rota_no_escribe_ninguna_copia."""
    api = _api(CAT)

    def rota(filtro, notas):
        return [] if "Basic Unit" in filtro else api(filtro, notas)
    total = sum(len(c.get("plantillas_precio") or []) for c in CAT["componentes"])  # 101 en v7 (I1.8)
    with pytest.raises(ip.ErrorInstantanea, match=f"1 de {total} plantillas no resuelven"):
        ip.generar(CAT, rota, AHORA)


@pytest.mark.parametrize("romper, motivo", [
    (lambda i: i["plantillas"]["az-ai-search/basic"].update(precio_unitario=9.9), "huella"),
    (lambda i: i["plantillas"].pop("az-ai-search/basic"), "falta la plantilla az-ai-search/basic"),
    (lambda i: i["plantillas"].update({"az-x/y": {}}), "no está en el catálogo"),
    (lambda i: i["plantillas"]["az-ai-search/basic"].update(filtro="otro"), "no es el del catálogo"),
    (lambda i: i["plantillas"]["az-ai-search/basic"].update(unidad="1K"), "no da el divisor"),
    (lambda i: i.update(moneda="USD"), "moneda")])
def test_problemas_detecta_cada_rotura(romper, motivo):
    roto = copy.deepcopy(VIVA)
    romper(roto)
    if motivo != "huella":
        roto["sha256"] = ip.huella(roto)  # resellada: la rotura la tiene que ver la comprobación, no la huella
    assert any(motivo in x for x in ip.problemas(roto, CAT)), ip.problemas(roto, CAT)


@pytest.mark.parametrize("dias, falla", [(0, False), (31, False), (32, True), (-1, True)])
def test_edad_maxima_31_dias_en_la_fecha_del_paquete(dias, falla):
    fecha = dt.date.fromisoformat(VIVA["fecha_consulta"][:10]) + dt.timedelta(days=dias)
    assert bool(ip.problemas(VIVA, CAT, fecha)) is falla


def test_la_instantanea_de_hoy_vale_y_su_huella_es_la_del_nucleo():
    import sys
    sys.path.insert(0, str(derivar.RAIZ / "sandbox"))
    from nucleo import hashes
    assert ip.problemas(VIVA, CAT) == [] and ip.DESTINOS[0].read_bytes() == ip.DESTINOS[1].read_bytes()
    assert VIVA["sha256"] == hashes.sha256_bytes(hashes.json_canonico({k: v for k, v in VIVA.items() if k != "sha256"}))
    assert len(VIVA["plantillas"]) == len(ip.plantillas(CAT)) and VIVA["moneda"] == "EUR"
    assert VIVA["plantillas"]["az-foundry/gpt-6-luna-entrada"]["precio_unitario"] == 0.1056


# --- Arreglos de la pasada 1 de la revisión independiente (I1.7) ---------------------------------------------------------------------------

@pytest.mark.parametrize("tramo", [None, float("inf"), -1, "0", True])
def test_tramo_ausente_o_no_finito_falla(tramo):
    with pytest.raises(ip.ErrorInstantanea, match="tierMinimumUnits"):
        ip.resolver("k", FILTRO, [art(tierMinimumUnits=tramo)], AHORA)


@pytest.mark.parametrize("tramos", [
    [{"desde": 0, "precio_unitario": 0.0}],
    [{"desde": 0, "precio_unitario": 0.0}, {"desde": float("inf"), "precio_unitario": 1}],
    [{"desde": 0, "precio_unitario": 0.0}, {"desde": 0, "precio_unitario": 1}],
    [{"desde": 1, "precio_unitario": 0.0}, {"desde": 5, "precio_unitario": 1}],
    [{"desde": 0, "precio_unitario": 9.0}, {"desde": 5, "precio_unitario": 1}]])
def test_problemas_valida_los_tramos_guardados(tramos):
    roto = copy.deepcopy(VIVA)
    roto["plantillas"]["az-log-analytics/ingesta"]["tramos"] = tramos
    roto["sha256"] = ip.huella(roto)
    assert any("tramos no válidos" in x for x in ip.problemas(roto, CAT))


def test_main_con_una_plantilla_rota_no_escribe_ninguna_copia(tmp_path, monkeypatch, capsys):
    destinos = (tmp_path / "a.json", tmp_path / "b.json")
    destinos[1].write_text("previa", encoding="utf-8")
    api = _api(CAT)
    monkeypatch.setattr(ip, "DESTINOS", destinos)
    monkeypatch.setattr(ip, "consultar", lambda f, n, pausa=1.6: [] if "Basic Unit" in f else api(f, n))
    assert ip.main(["--pausa", "0"]) == 2
    assert "NO SE ESCRIBE NADA" in capsys.readouterr().out
    assert not destinos[0].exists() and destinos[1].read_text(encoding="utf-8") == "previa"


def test_si_falla_un_reemplazo_se_restauran_las_copias(tmp_path, monkeypatch):
    destinos = (tmp_path / "a.json", tmp_path / "b.json")
    for d in destinos:
        d.write_text("previa", encoding="utf-8")
    inst = ip.generar(CAT, _api(CAT), AHORA)
    real, n = ip.os.replace, []

    def replace(origen, destino):
        n.append(destino)
        if len(n) == 2:
            raise OSError("disco lleno")
        real(origen, destino)
    monkeypatch.setattr(ip.os, "replace", replace)
    with pytest.raises(ip.ErrorInstantanea, match="restauraron"):
        ip.escribir(inst, CAT, destinos)
    assert [d.read_text(encoding="utf-8") for d in destinos] == ["previa", "previa"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.json", "b.json"]


def test_derivar_ve_las_dos_copias_de_la_instantanea(tmp_path, monkeypatch):
    destinos = (tmp_path / "a.json", tmp_path / "b.json")
    destinos[0].write_bytes(ip.DESTINOS[0].read_bytes())
    monkeypatch.setattr(ip, "DESTINOS", destinos)
    assert any("falta" in x for x in derivar.problemas_instantanea(CAT))
    destinos[1].write_bytes(ip.DESTINOS[0].read_bytes() + b"\n")
    assert any("no son iguales" in x for x in derivar.problemas_instantanea(CAT))
    destinos[1].write_bytes(destinos[0].read_bytes())
    assert derivar.problemas_instantanea(CAT) == []


def test_main_convierte_un_oserror_en_rc_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ip, "DESTINOS", (tmp_path / "a.json", tmp_path / "b.json"))
    monkeypatch.setattr(ip, "consultar", lambda f, n, pausa=1.6: _api(CAT)(f, n))
    monkeypatch.setattr(ip, "escribir", lambda inst, cat: (_ for _ in ()).throw(OSError("restauración fallida")))
    assert ip.main(["--pausa", "0"]) == 2 and "restauración fallida" in capsys.readouterr().out
