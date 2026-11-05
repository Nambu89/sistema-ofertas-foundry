"""I1.7, papel E: GPT-6 en el catálogo, ciclo de vida, factores estándar, «incluye», arquitecturas por id y comprobaciones
que fallan en alto. Sin red (las comprobaciones contra la API y Learn están en pruebas/I17/CATALOGO/)."""
from __future__ import annotations

import datetime as dt

import pytest

from catalogo import derivar
from catalogo import plantillas_precio as pp

CAT = derivar.cargar()
FOUNDRY = next(c for c in CAT["componentes"] if c["id"] == "az-foundry")
PL = {p["id"]: p for p in FOUNDRY["plantillas_precio"]}
# Retail Prices EUR, swedencentral, consultado por el PM (12/13-10) y medido por E el 13-10 (medicion_foundry.txt)
PRECIOS_GPT6 = {"gpt-6-luna-entrada": 0.1056, "gpt-6-luna-salida": 0.528, "gpt-6-luna-entrada-largo": 0.2112,
                "gpt-6-luna-salida-largo": 0.792, "gpt-6-sol-entrada": 2.1119, "gpt-6-sol-salida": 10.5597}


def test_plantillas_gpt6_data_zone_con_su_precio_medido():
    luna = [i for i in PL if i.startswith("gpt-6-luna")]
    assert len(luna) == 8 and len([i for i in PL if i.startswith("gpt-6-sol")]) == 4
    assert len([i for i in PL if i.startswith("gpt-6.1-sol")]) == 4
    assert not [i for i in PL if "astra" in i]  # Learn: gpt-6-astra no está en Data Zone Standard de Europa
    for i, precio in PRECIOS_GPT6.items():
        k = PL[i]["comprobacion"]
        assert k["precios_eur"] == [precio] and k["producto"] == "Azure OpenAI GPT6" and k["articulos"] == 1, i
    for i in luna + [i for i in PL if "sol" in i]:
        m = dict(pp.condiciones(PL[i]["filtro"]))["meterName"]
        assert " Std DZ 1M Tokens" in m and (("LongCo" in m) == i.endswith("-largo")), i
        assert PL[i]["contexto"] == ("largo" if i.endswith("-largo") else "corto")


def test_modelo_por_defecto_gpt6_luna_y_gpt5_sin_por_defecto():
    assert sorted(i for i, p in PL.items() if p.get("por_defecto")) == ["gpt-6-luna-entrada", "gpt-6-luna-salida"]
    d = CAT["modelo_por_defecto"]
    assert (d["modelo"], d["region"], d["despliegue"]) == ("gpt-6-luna", FOUNDRY["region_ue"], "DataZoneStandard")
    assert "semana 1" in d["motivo"] and d["fuente_url"] in {f["url"] for f in CAT["fuentes_comprobadas"]}


def test_ciclo_vida_de_todos_los_modelos_con_fuente():
    cvs = pp.ciclos_vida(CAT)
    assert {p["modelo"] for p in PL.values()} == set(cvs)
    assert {m: cvs[m]["retirada"] for m in ("gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.4")} == {
        "gpt-5": "2027-02-09", "gpt-5-mini": "2027-02-09", "gpt-5-nano": "2027-02-09", "gpt-5.4": "2027-09-02"}
    assert all(cvs[m]["retirada"] is None for m in ("gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol"))
    assert pp.modelos_fuera_siempre(CAT) == ["gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5.4"]
    assert all(cv["fuente"] in {f["url"] for f in CAT["fuentes_comprobadas"]} for cv in cvs.values())


@pytest.mark.parametrize("retirada, semanas, admitido", [
    (None, 8, True), ("2027-02-09", 0, False), ("2027-12-08", 8, True), ("2027-12-07", 8, False), ("2028-01-11", 8, True)])
def test_regla_de_ciclo_de_vida(retirada, semanas, admitido):
    cv = {"ga": "2026-01-01", "retirada": retirada, "fuente": "x"}
    ok, nota = pp.modelo_admisible(cv, dt.date(2026, 10, 13), semanas)  # límite con 8 semanas: 2027-12-08
    assert ok is admitido and (nota == "fecha de retirada aún no publicada") == (retirada is None)


def test_regla_de_ciclo_de_vida_falla_cerrada():
    assert pp.modelo_admisible(None, dt.date(2026, 10, 13), 8)[0] is False
    for malo in (-1, float("nan"), True, "8"):
        with pytest.raises(ValueError):
            pp.limite_ciclo_vida(dt.date(2026, 10, 13), malo)
    assert pp.limite_ciclo_vida(dt.date(2026, 1, 31), 0) == dt.date(2027, 1, 31)
    assert pp._mas_meses(dt.date(2027, 1, 31), 1) == dt.date(2027, 2, 28)
    assert pp._mas_meses(dt.date(2027, 12, 31), 2) == dt.date(2028, 2, 29)


def test_factores_estandar_con_fuente_y_desglose():
    fs = pp.factores(CAT)
    assert {k: f["valor"] for k, f in fs.items()}.items() >= {
        "asistente_rag.tokens_entrada_por_consulta": 5656, "asistente_rag.tokens_salida_por_consulta": 1171,
        "asistente_rag.consultas_ranking_por_consulta": 1, "bot.mensajes_por_consulta": 2,
        "almacen_documentos.gb_por_documento": 0.002}.items()   # arreglos I1.7 (PR17-3): capacidad de Storage por documento
    assert len(fs) == 32  # I1.9: tres factores por acción (PR18-5). I1.8 (LES-G-100.8): un factor por medidor de volumen (tests/test_i18_e_catalogo.py)
    for f in fs.values():
        numeros = [d["valor"] for d in f["desglose"] if d["valor"] is not None]
        assert abs(sum(numeros) - f["valor"]) < 1e-9 and f["base"] and f["fuente_url"].startswith("https://")
    usados = {p.get("factor_estandar") for c in CAT["componentes"] for p in c.get("plantillas_precio") or []} - {None}
    # I1.9 (PR18-5): los factores por acción se usan como factores alternativos, no como estándar
    usados |= {x for c in CAT["componentes"] for p in c.get("plantillas_precio") or []
               for x in p.get("factores_alternativos") or []}
    assert usados == set(fs)
    assert {i for i, p in PL.items() if p.get("factor_estandar")} == {
        f"{m}-{s}" for m in ("gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol") for s in ("entrada", "salida")}
    assert {i for i, p in PL.items() if p.get("sin_factor_motivo")} == set(PL) - {  # I1.8: el resto, con su motivo
        f"{m}-{s}" for m in ("gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol") for s in ("entrada", "salida")}


def test_incluye_y_arquitecturas_con_fuente():
    la = next(c for c in CAT["componentes"] if c["id"] == "az-log-analytics")
    assert [x["catalogo_id"] for x in la["incluye"]] == ["az-app-insights"]
    assert "billing for data ingestion and retention is done by the workspace" in la["incluye"][0]["cita"]
    ids = [a["id"] for a in CAT["arquitecturas_referencia"]]
    assert len(ids) == len(set(ids)) == 5 and "foundry-chat-base" in ids
    vistas = {f["url"]: f for f in CAT["fuentes_comprobadas"]}
    assert all(vistas[a["url"]]["http"] == 200 for a in CAT["arquitecturas_referencia"])
    assert derivar.problemas_catalogo(CAT) == [] and pp.problemas_i17(CAT) == []
