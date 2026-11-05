"""Catálogo, referencias e instrucciones del pilar Google Cloud, sin red."""
import json
import pathlib
import re

from catalogo.gcp import comprobar_catalogo as cc
from catalogo.gcp import instantanea_precios as ip
from esquemas.comprobar_esquemas import validar

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAT = json.loads(cc.CATALOGO.read_text(encoding="utf-8"))
REFS = json.loads(cc.REFERENCIAS.read_text(encoding="utf-8"))

# Errores del esquema de Azure que DESVIACIONES.md documenta (rutas con índices normalizados a []).
DESVIACIONES = [
    r"\$\.componentes\[\]\.id: no casa con \^az-",
    r"\$\.computo_por_defecto\.filas\[\]: no casa con \^az-",
    r"\$\.(componentes\[\]\.(referencia_url|nivel_por_defecto\.fuente|niveles\[\]\.fuente_url|plantillas_precio\[\]\.("
    r"ciclo_vida\.fuente|por_instancia\.fuente_url))|arquitecturas_referencia\[\]\.url|computo_por_defecto\.fuente_url|"
    r"modelo_por_defecto\.(fuente_url|region_fuente_url)): no casa con \^https://learn",
    r"\$\.componentes\[\]\.plantillas_precio\[\]: clave no admitida «(unidad_uso|fuente_sku|region_precio)»",
    r"\$\.componentes\[\]\.plantillas_precio\[\]\.ciclo_vida: clave no admitida «retirada_no_antes_de»",
    r"\$\.componentes\[\]\.region_ue: no casa con",
    r"\$\.modelo_por_defecto\.componente: debe ser 'az-foundry'",
    r"\$\.modelo_por_defecto\.despliegue: debe ser 'DataZoneStandard'",
]


def test_catalogo_y_referencias_validos():
    assert cc.problemas(CAT, REFS) == []
    assert 12 <= len(CAT["componentes"]) <= 20


def test_regiones_del_catalogo_en_la_lista_blanca():
    for c in CAT["componentes"]:
        assert c["region_ue"] in ip.REGIONES_UE | ip.MULTIRREGIONES_UE or (
            c["region_ue"] == "global" and not c.get("plantillas_precio")), c["id"]
    for _k, c, p in ip.plantillas(CAT):
        assert ip.condiciones(p["filtro"])["serviceRegion"] in ip.REGIONES_UE | ip.MULTIRREGIONES_UE | {"global"}


def test_rotura_de_region_o_factor_se_detecta():
    roto = json.loads(json.dumps(CAT))
    roto["componentes"][2]["region_ue"] = "europe-west2"
    roto["componentes"][0]["plantillas_precio"][0]["factor_estandar"] = "asistente_rag.no_existe"
    m = cc.problemas(roto)
    assert any("europe-west2" in x for x in m) and any("no_existe" in x for x in m)


def test_solo_desviaciones_documentadas_frente_al_esquema_azure():
    esquema = json.loads((RAIZ / "esquemas" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    errores = {re.sub(r"\[\d+\]", "[]", e) for e in validar(CAT, esquema, esquema)}
    no_documentados = [e for e in errores if not any(re.match(d, e) for d in DESVIACIONES)]
    assert no_documentados == []


def test_bloque_de_las_instrucciones_coincide_con_el_catalogo():
    texto = cc.INSTRUCCIONES.read_text(encoding="utf-8")
    assert cc.insertar(texto, cc.bloque(CAT)) == texto
    assert "answer_query" in texto and "preventa-experto-gcp" in texto and "europe-west2" in texto
    assert "microsoft_docs" not in texto and "learn.microsoft.com" not in texto


def test_definicion_borrador_sin_answer_query_ni_secretos():
    d = json.loads((RAIZ / "agentes" / "gcp" / "definicion_borrador.json").read_text(encoding="utf-8"))
    mcp = d["definicion"]["tools"][0]
    assert mcp["server_url"] == "https://developerknowledge.googleapis.com/mcp"
    assert mcp["allowed_tools"]["tool_names"] == ["search_documents", "get_documents"]
    assert d["conexion"]["cabecera"] == "X-Goog-Api-Key"


def test_ningun_fichero_del_pilar_lleva_una_clave():
    rutas = list((RAIZ / "catalogo" / "gcp").glob("*")) + list((RAIZ / "agentes" / "gcp").glob("*"))
    for r in rutas:
        if r.is_file():
            assert not re.search(r"AIza[0-9A-Za-z_-]{30,}", r.read_text(encoding="utf-8")), r.name


def test_comprobar_red_con_paginas_falsas():
    filas = "".join(f"<tr><td>X ({ip.condiciones(p['filtro'])['serviceId']})</td><td>{p['concepto']}</td>"
                    f"<td>{ip.condiciones(p['filtro'])['skuId']}</td><td>2026</td></tr>" for _k, _c, p in ip.plantillas(CAT))
    titulos = {c["referencia_url"]: c["referencia_titulo"] for c in CAT["componentes"]}
    titulos |= {r["url"]: r["titulo"] for r in REFS["referencias"]}

    def get(url):
        if "skus/sku-groups" in url:
            return 200, url, f"<table>{filas}</table>"
        return 200, url, f"<title>{titulos[url]} | Google Cloud Documentation</title>"
    assert cc.comprobar_red(CAT, REFS, get) == []
    roto = json.loads(json.dumps(CAT))
    roto["componentes"][0]["plantillas_precio"][0]["concepto"] = "Otro SKU"
    assert len(cc.comprobar_red(roto, REFS, get)) == 1


def test_fallo_de_red_en_comprobar_es_falla_y_no_traceback(monkeypatch):
    import urllib.error

    def caido(*a, **k):
        raise urllib.error.URLError("sin red")
    monkeypatch.setattr(cc.urllib.request, "urlopen", caido)
    estado, final, cuerpo = cc._get("https://docs.cloud.google.com/architecture")
    assert estado == 0 and cuerpo == "" and "sin respuesta" in final


def test_fecha_imposible_se_rechaza():
    assert cc._fecha_ok("2026-11-04") and not cc._fecha_ok("2026-99-99") and not cc._fecha_ok("2026-02-30")


def test_escribir_instrucciones_no_escribe_con_el_catalogo_roto(tmp_path, monkeypatch):
    roto = json.loads(json.dumps(CAT))
    roto["componentes"][2]["region_ue"] = "europe-west2"
    destino_cat, destino_ins = tmp_path / "cat.json", tmp_path / "ins.md"
    destino_cat.write_text(json.dumps(roto, ensure_ascii=False), encoding="utf-8")
    texto = cc.INSTRUCCIONES.read_text(encoding="utf-8")
    destino_ins.write_text(texto, encoding="utf-8")
    monkeypatch.setattr(cc, "CATALOGO", destino_cat)
    monkeypatch.setattr(cc, "INSTRUCCIONES", destino_ins)
    assert cc.main(["--escribir-instrucciones"]) == 1
    assert destino_ins.read_text(encoding="utf-8") == texto
