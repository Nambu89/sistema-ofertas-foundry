"""I1.4 · P2 · REV13-3: concepto legible de cada precio (nunca el meterName crudo), el mismo texto para el SaaS
que no se factura por Azure, filas «No valorado» agrupadas por motivo y títulos de referencia en castellano."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import anexo_consumo, pptx_revision, textos_cliente as tc  # noqa: E402

CRUDOS = ("Inpt", "outpt", "DZone", "Unit", "Channel Messages", "Hour", "1M", "1K")


def _cat() -> dict:
    return json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("linea, producto, esperado", [
    ({"servicio": "Microsoft Foundry", "concepto": "GPT 5 Mini Inpt DZone 1M Tokens", "unidad": "1M",
      "filtro": "serviceName eq 'Foundry Models' and armSkuName eq 'GPT 5 Mini Inpt DZone'"}, "Microsoft Foundry",
     "Tokens de entrada del modelo, zona de datos (por millón)"),
    ({"servicio": "Microsoft Foundry", "concepto": "GPT 5 Mini outpt DZone", "unidad": "1M", "filtro": ""}, None,
     "Tokens de salida del modelo, zona de datos (por millón)"),
    ({"servicio": "Microsoft Foundry", "concepto": "gpt-5 cached Inp glbl", "unidad": "1K", "filtro": ""}, None,
     "Tokens de entrada en caché del modelo, despliegue global (por mil)"),
    ({"servicio": "Azure AI Search", "concepto": "Basic Unit; Azure AI Search", "unidad": "1 Hour",
      "filtro": "serviceName eq 'Azure Cognitive Search' and skuName eq 'Basic'"}, "Azure AI Search",
     "Tiempo de funcionamiento, plan Basic"),
    ({"servicio": "Azure AI Bot Service", "concepto": "Free Standard Channel Messages", "unidad": "1K",
      "filtro": "skuName eq 'Free'"}, "Azure Bot Service", "Mensajes de canal, plan Free (por mil)"),  # VA18-12: mismo producto, no se repite
    ({"servicio": "Azure Blob Storage", "concepto": "Hot LRS Data Stored", "unidad": "1 GB/Month",
      "filtro": "armSkuName eq 'Hot_LRS'"}, None, "Almacenamiento de datos (por GB al mes)"),
    ({"servicio": "Azure Key Vault", "concepto": "Operations", "unidad": "10K", "filtro": ""}, None,
     "Operaciones (por cada 10.000)"),
    ({"servicio": "X", "concepto": "Algo raro", "unidad": "1 Month", "filtro": "skuName eq 'Un_plan_raro'"}, None,
     "Consumo del servicio (al mes)"),
])
def test_concepto_legible(linea, producto, esperado):
    texto = tc.concepto_legible(linea, producto)
    assert texto == esperado
    assert not [c for c in CRUDOS if c in texto] and not tc.barrer(texto, [])  # ni crudo, ni «hora» (§9.3)


def test_es_saas_sin_precio():
    cat = {c["id"]: c for c in _cat()["componentes"]}
    assert anexo_consumo.es_saas_sin_precio(cat["az-teams"], "Microsoft Teams")
    assert anexo_consumo.es_saas_sin_precio(cat["az-entra-id"], "Microsoft Entra ID")
    assert not anexo_consumo.es_saas_sin_precio(cat["az-cost-management"], "Microsoft Cost Management")
    assert not anexo_consumo.es_saas_sin_precio(cat["az-policy"], "Azure Policy")
    assert not anexo_consumo.es_saas_sin_precio(dict(cat["az-teams"], service_name_precios="Teams X"), "")
    for nombre in ("SharePoint Online", "SharePoint in Microsoft 365", "Microsoft 365", "Exchange Online"):
        assert anexo_consumo.es_saas_sin_precio(None, nombre), nombre
    for nombre in ("Azure Communication Services con Teams", "Portal web del cliente", "Base de datos propia"):
        assert not anexo_consumo.es_saas_sin_precio(None, nombre), nombre


def test_paquete_con_capas_consumo_y_referencias():
    sys.path.insert(0, str(RAIZ / "pruebas" / "I14" / "P2"))
    import paquete_capas
    est, cat, tarifa = paquete_capas.construir_estado()
    textos = est["carga"]["textos_cliente"]
    anexo = est["carga"]["anexo_consumo"]
    # mismo orden que el anexo (la puerta empareja por posición) y nada crudo
    assert [x["servicio"] for x in textos["consumo"]["lineas"]] == [x["servicio"] for x in anexo["lineas"]]
    conceptos = [x["concepto"] for x in textos["consumo"]["lineas"]]
    # integrador I1.7: gpt-6-luna lleva el contexto en el medidor («ShortCo»: contexto corto; CAMBIOS-I17-D §1)
    assert "Tokens de entrada del modelo, contexto corto, zona de datos (por millón)" in conceptos
    assert not [c for c in conceptos if any(k in c for k in CRUDOS)]
    nv = anexo_consumo.no_valorados(est, cat)
    saas = [x["servicio"] for x in nv if x["motivo"] == anexo_consumo.MOTIVO_SAAS]
    assert saas == ["Microsoft Entra ID", "Microsoft Teams", "SharePoint Online"]
    filas = pptx_revision.filas_no_valoradas(nv)
    assert ["Microsoft Entra ID, Microsoft Teams y SharePoint Online", anexo_consumo.MOTIVO_SAAS, "No valorado"] in filas
    assert len(filas) == len({x["motivo"] for x in nv})
    assert all(r["titulo"].startswith("Documentación oficial de Microsoft sobre ")
               for r in textos["arquitectura"]["referencias"])
    prs, informe = pptx_revision.construir(est, cat)
    assert informe == {"modo": "diagrama", "fallos": []}
    assert pptx_revision.solapes_diagrama(pptx_revision.formas_de(prs.slides[3])) == []


def test_medidas_consumo_crecen_con_el_texto_y_fallan_en_alto():
    corta = [["Servicio", "Concepto", "Coste"]] + [["A", "B", "1,00 €"] for _ in range(6)]
    tam, altos, margen = pptx_revision.medidas_consumo(corta)
    assert tam == 12 and margen is None and len(set(altos)) == 1
    larga = copy.deepcopy(corta)
    larga[3][0] = ", ".join(["Azure Document Intelligence in Foundry Tools"] * 8)
    _, altos2, _ = pptx_revision.medidas_consumo(larga)
    assert altos2[3] > altos2[2]
    with pytest.raises(pptx_revision.errores.ReglaIncumplida):
        pptx_revision.medidas_consumo([["Servicio", "Concepto", "Coste"]] + [["A", "B", "C"]] * 40)
