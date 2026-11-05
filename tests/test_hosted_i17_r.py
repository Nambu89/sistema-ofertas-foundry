"""I1.7 · Papel R · hosted: la instantánea de precios viaja en el ZIP (recursos/precios_instantanea.json) y
empaquetar.py no empaqueta una que falte, no sea la del catálogo, tenga la huella rota, no cubra el catálogo o tenga
más de 31 días. config.recursos la expone como PREVENTA_PRECIOS. Sin red."""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import zipfile

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "hosted"))
import empaquetar  # noqa: E402
from preventa_hosted import config  # noqa: E402

CATALOGO = RAIZ / "sandbox" / "datos" / "catalogo_componentes.json"
AHORA = dt.datetime(2026, 10, 13, 9, 0, tzinfo=dt.timezone.utc)


def instantanea_sintetica(catalogo: pathlib.Path, fecha: dt.datetime) -> dict:
    """Instantánea con la forma del contrato común (a) para TODAS las plantillas del catálogo, precio 1.0. Solo pruebas."""
    cat = json.loads(catalogo.read_text(encoding="utf-8"))
    # Integrador I1.7: el núcleo valida cada artículo (región del filtro, unidad frente al divisor): se parte de los
    # artículos reales de la instantánea del sandbox (mismo filtro) y solo cambia la fecha; si falta, uno sintético con
    # la región del filtro.
    real = json.loads((RAIZ / "sandbox" / "datos" / "precios_instantanea.json").read_text(encoding="utf-8"))["plantillas"]

    def articulo(clave: str, p: dict) -> dict:
        if clave in real and real[clave].get("filtro") == p["filtro"]:
            return dict(real[clave])
        region = re.search(r"armRegionName eq '([^']+)'", p["filtro"])
        return {"filtro": p["filtro"], "precio_unitario": 1.0, "unidad": "1 Hour",
                "effectiveStartDate": "2026-09-01T00:00:00Z", "meterName": p["id"], "productName": "sintetico",
                "skuName": "sintetico", "armRegionName": region.group(1) if region else "swedencentral",
                "articulos_devueltos": 1, "sha256_articulo": "0" * 64}
    pl = {f"{c['id']}/{p['id']}": articulo(f"{c['id']}/{p['id']}", p)
          for c in cat["componentes"] for p in c.get("plantillas_precio") or []}
    inst = {"schema": empaquetar.SCHEMA_INSTANTANEA, "fecha_consulta": fecha.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "moneda": "EUR", "plantillas": pl,   # multinube: sin la procedencia del euro (Retail Prices en EUR), se rechaza
            "fuente": "https://prices.azure.com/api/retail/prices?currencyCode='EUR' (sintetica de pruebas)"}
    inst["sha256"] = empaquetar.hash_instantanea(inst)
    return inst


def escribir(inst: dict, *rutas: pathlib.Path) -> None:
    datos = (json.dumps(inst, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    for r in rutas:
        r.write_bytes(datos)


@pytest.fixture
def par(tmp_path):
    """(copia de sandbox/datos, copia del catálogo) iguales byte a byte y válidas."""
    a, b = tmp_path / "datos.json", tmp_path / "catalogo.json"
    escribir(instantanea_sintetica(CATALOGO, AHORA - dt.timedelta(days=2)), a, b)
    return a, b


def test_valida(par):
    assert empaquetar.comprobar_instantanea(par[0], AHORA, par[1]) == []


def test_la_huella_es_la_del_generador_de_p():
    """Misma definición que catalogo/instantanea_precios.huella (si existe): JSON canónico sin «sha256»."""
    inst = instantanea_sintetica(CATALOGO, AHORA)
    sin = {k: v for k, v in inst.items() if k != "sha256"}
    canon = json.dumps(sin, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert inst["sha256"] == hashlib.sha256(canon).hexdigest()
    gen = RAIZ / "catalogo" / "instantanea_precios.py"
    if gen.is_file():
        sys.path.insert(0, str(RAIZ))
        from catalogo import instantanea_precios
        assert instantanea_precios.huella(inst) == inst["sha256"]


@pytest.mark.parametrize("cambiar, trozo", [
    (lambda i: i.update(fecha_consulta=(AHORA - dt.timedelta(days=32)).strftime("%Y-%m-%dT%H:%M:%SZ")), "más de 31"),
    (lambda i: i.update(fecha_consulta=(AHORA + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")), "posterior"),
    (lambda i: i.update(fecha_consulta="2026-10-12T09:00:00"), "sin zona horaria"),
    (lambda i: i.update(moneda="USD"), "en EUR"),
    (lambda i: i["plantillas"].pop(next(iter(i["plantillas"]))), "falta la plantilla"),
    (lambda i: next(iter(i["plantillas"].values())).update(filtro="serviceName eq 'X'"), "el filtro no es"),
    (lambda i: next(iter(i["plantillas"].values())).update(precio_unitario=-0.5), "finito y no negativo"),
    (lambda i: next(iter(i["plantillas"].values())).update(precio_unitario=10 ** 400), "finito y no negativo"),
    (lambda i: next(iter(i["plantillas"].values())).update(articulos_devueltos=0), "artículos devueltos"),
])
def test_casos_adversos(tmp_path, cambiar, trozo):
    inst = instantanea_sintetica(CATALOGO, AHORA - dt.timedelta(days=1))
    cambiar(inst)
    inst["sha256"] = empaquetar.hash_instantanea(inst)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    escribir(inst, a, b)
    errores = empaquetar.comprobar_instantanea(a, AHORA, b)
    assert any(trozo in e for e in errores), errores


def test_31_dias_justos_vale_y_huella_rota_o_copias_distintas_no(tmp_path, par):
    inst = instantanea_sintetica(CATALOGO, AHORA - dt.timedelta(days=31))
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    escribir(inst, a, b)
    assert empaquetar.comprobar_instantanea(a, AHORA, b) == []
    roto = copy.deepcopy(inst)
    roto["fuente"] = "otra"                                  # sin resellar
    escribir(roto, a, b)
    assert any("huella interna" in e for e in empaquetar.comprobar_instantanea(a, AHORA, b))
    escribir(inst, a)
    escribir(instantanea_sintetica(CATALOGO, AHORA - dt.timedelta(days=3)), b)
    assert any("byte a byte" in e for e in empaquetar.comprobar_instantanea(a, AHORA, b))
    assert any("falta la instantánea" in e for e in empaquetar.comprobar_instantanea(tmp_path / "no.json", AHORA, b))
    a.write_text('{"schema": NaN}', encoding="utf-8")
    assert any("JSON ilegible" in e for e in empaquetar.comprobar_instantanea(a, AHORA, a))


def test_va_en_el_zip_y_sin_ella_no_se_empaqueta(tmp_path, par, monkeypatch):
    canon = dict(empaquetar.CANONICOS)
    canon["precios_instantanea.json"] = (par[0], None)        # sin entrada en manifiesto.json (la añade el integrador)
    monkeypatch.setattr(empaquetar, "CANONICOS", canon)
    monkeypatch.setattr(empaquetar, "INSTANTANEA_CATALOGO", par[1])
    r = empaquetar.construir(tmp_path / "z.zip", ahora=AHORA)
    z = zipfile.ZipFile(r["zip"])
    assert z.read("recursos/precios_instantanea.json") == par[0].read_bytes()
    man = json.loads(z.read("MANIFIESTO-HOSTED.json"))
    assert man["ficheros"]["recursos/precios_instantanea.json"]["sha256"] == hashlib.sha256(par[0].read_bytes()).hexdigest()
    with pytest.raises(empaquetar.ErrorEmpaquetado, match="más de 31"):
        empaquetar.construir(tmp_path / "v.zip", ahora=AHORA + dt.timedelta(days=40))
    assert not (tmp_path / "v.zip").exists()


def test_la_instantanea_exige_su_entrada_en_manifiesto_json():
    assert empaquetar.CANONICOS["precios_instantanea.json"][1] == "precios_instantanea.json"


def test_config_expone_precios_y_respeta_la_variable(tmp_path):
    r = config.recursos({})
    assert r["PREVENTA_PRECIOS"].name == "precios_instantanea.json" and r["PREVENTA_PRECIOS"].parent.name == "recursos"
    assert config.recursos({"PREVENTA_PRECIOS": str(tmp_path / "x.json")})["PREVENTA_PRECIOS"] == tmp_path / "x.json"
    assert config.recursos({"PREVENTA_PRECIOS": "   "})["PREVENTA_PRECIOS"].parent.name == "recursos"   # LES-G-076
