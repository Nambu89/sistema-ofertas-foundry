"""I1.6, papel E: concepto derivable (PR15-3), derivado con el esquema propuesto, auxiliar ligado (INT15-3) e
instrucciones del experto y del verificador con las reglas de LES-G-100. Sin red."""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from catalogo import derivar
from catalogo import plantillas_precio as pp
from esquemas import comprobar_esquemas as ce

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CAT = derivar.cargar()
POR_ID = {c["id"]: c for c in CAT["componentes"]}
PARES = [(c, p) for c in CAT["componentes"] for p in c.get("plantillas_precio") or []]
ESQ_HOY = json.loads((RAIZ / "esquemas" / "catalogo_componentes.json").read_text(encoding="utf-8"))
PROPUESTO = json.loads((RAIZ / "docs" / "I1" / "CAMBIOS-I16-E" / "catalogo_componentes.propuesto.json")
                       .read_text(encoding="utf-8"))
EXPERTO = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md").read_text(encoding="utf-8")
VERIF = (RAIZ / "agentes" / "instrucciones" / "verificador_i1.md").read_text(encoding="utf-8")
AUX = CAT["precios_auxiliares"][0]
# I1.7: hasta que el integrador aplique docs/I1/CAMBIOS-I17-E (esquema propuesto), el catálogo v5 no cabe en el esquema
# vigente (25 plantillas en Microsoft Foundry) y derivar.main lo rechaza sin escribir; se deriva con la propuesta.
RUTA_PROPUESTO_I17 = RAIZ / "docs" / "I1" / "CAMBIOS-I17-E" / "catalogo_componentes.propuesto.json"
PROPUESTO_I17 = json.loads(RUTA_PROPUESTO_I17.read_text(encoding="utf-8"))
VIGENTE_ADMITE = ce.validar(derivar.catalogo_componentes(CAT, esquema=ESQ_HOY), ESQ_HOY, ESQ_HOY) == []
ESQ_EFECTIVO = ESQ_HOY if VIGENTE_ADMITE else PROPUESTO_I17
ARGS_EFECTIVO = [] if VIGENTE_ADMITE else ["--esquema-sandbox", str(RUTA_PROPUESTO_I17)]
EXTRA_I17 = ("modelo", "contexto", "factor_estandar", "por_instancia", "sin_factor_motivo", "razones_subida",
             "opcional", "factores_alternativos")  # I1.9: razones del modelo, plantilla opcional y factores  # I1.8: sin_factor_motivo  # por_instancia: arreglos I1.7 (PR17-5)


@pytest.mark.parametrize("c, p", PARES, ids=[f"{c['id']}/{p['id']}" for c, p in PARES])
def test_concepto_derivado_de_la_comprobacion(c, p):
    k, concepto = p["comprobacion"], pp.concepto(p)
    assert 3 <= len(concepto) <= 160 and "None" not in concepto
    if p.get("concepto_con_sku"):
        assert concepto == f"{k['medidor']} ({k['sku']})"
    elif len(k["medidor"]) < 3:
        assert concepto == f"{k['medidor']} ({k['producto']})"
    else:
        assert concepto == k["medidor"] == dict(pp.condiciones(p["filtro"]))["meterName"]


def test_concepto_falla_en_alto_sin_el_dato_que_necesita():
    with pytest.raises(ValueError):
        pp.concepto({"id": "x", "comprobacion": {"medidor": "B1"}})
    with pytest.raises(ValueError):
        pp.concepto({"id": "y", "concepto_con_sku": True, "comprobacion": {"medidor": "vCore", "sku": None}})
    assert pp.concepto({"id": "z", "comprobacion": {"medidor": "Standard S1 Unit"}}) == "Standard S1 Unit"


def test_derivado_con_el_esquema_vigente_valida_y_lleva_lo_de_la_decision_4():
    """Integrador I1.6: el esquema vigente es el propuesto por E con el auxiliar por referencia (forma de P)."""
    der = derivar.catalogo_componentes(CAT, esquema=ESQ_EFECTIVO)
    assert ce.validar(der, ESQ_EFECTIVO, ESQ_EFECTIVO) == []
    fuente = {(c["id"], p["id"]): p for c, p in PARES}
    admite = derivar._props(ESQ_EFECTIVO, "componentes", "items", "plantillas_precio", "items")
    cvs = pp.ciclos_vida(CAT)
    for c in der["componentes"]:
        for p in c.get("plantillas_precio") or []:
            f = fuente[(c["id"], p["id"])]
            esperado = {"id": f["id"], "filtro": f["filtro"], "concepto": pp.concepto(f), "impulsor": f["impulsor"],
                        "divisor": f["divisor"]} | ({"por_defecto": True} if f.get("por_defecto") else {})  # PR16-3
            esperado |= {k: f[k] for k in EXTRA_I17 if k in f and k in admite}  # I1.7
            if f.get("modelo") and "ciclo_vida" in admite:
                esperado["ciclo_vida"] = {k: cvs[f["modelo"]][k] for k in ("ga", "retirada", "fuente")}
            assert p == esperado
        assert ("niveles" in c) == bool(POR_ID[c["id"]].get("niveles")), c["id"]
    aux = der["precios_auxiliares"][0]
    assert aux["componentes"] == AUX["componentes"]
    assert (aux["plantillas_de"], aux["plantillas"]) == ("az-private-link", ["punto-conexion"])
    assert "plantillas_precio" not in aux and aux["plantillas_de"] in {c["id"] for c in der["componentes"]}


@pytest.mark.skip(reason="I1.7 (integrador): el esquema vigente del catálogo es el propuesto por E en I1.7 "
                         "(docs/I1/CAMBIOS-I17-E/catalogo_componentes.propuesto.json); lo comprueba "
                         "tests/test_i17_int_catalogo.py y test_i17_e_catalogo.py")
def test_esquema_vigente_es_el_propuesto_con_el_auxiliar_por_referencia_y_copia_del_sandbox_igual():
    vig, prop = json.loads(json.dumps(ESQ_HOY)), json.loads(json.dumps(PROPUESTO))
    va = vig["properties"]["precios_auxiliares"]["items"]["properties"]
    pa = prop["properties"]["precios_auxiliares"]["items"]["properties"]
    assert set(va) - set(pa) == {"plantillas_de", "plantillas"} and set(pa) - set(va) == {"plantillas_precio"}
    for k in ("plantillas_de", "plantillas", "plantillas_precio"):
        va.pop(k, None), pa.pop(k, None)
    # Arreglos I1.6 (PR16-3): la única diferencia más es `por_defecto` en las plantillas de cada componente
    pl = vig["properties"]["componentes"]["items"]["properties"]["plantillas_precio"]["items"]["properties"]
    assert pl.pop("por_defecto")["const"] is True
    assert vig == prop
    assert (RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_bytes() == derivar.DERIVADO.read_bytes()


def test_auxiliar_ligado_a_componentes_con_plantilla_global():
    ps = pp.plantillas_de_auxiliar(AUX, CAT)
    assert [p["id"] for p in ps] == ["punto-conexion"] and "'Global'" in ps[0]["filtro"]
    assert pp.problemas_plantilla(ps[0], POR_ID["az-private-link"]) == []
    assert set(AUX["componentes"]) <= {c["id"] for c in CAT["componentes"] if c.get("service_name_precios")}
    assert "az-private-link" not in AUX["componentes"] and "az-virtual-network" not in AUX["componentes"]
    assert AUX["componentes_fuente_url"] in {f["url"] for f in CAT["fuentes_comprobadas"]}


@pytest.mark.parametrize("cambio", [{"plantillas_de": "az-ai-search"}, {"plantillas": ["no-existe"]},
                                    {"plantillas_de": "az-no-existe"}])
def test_auxiliar_mal_referenciado_falla_en_alto(cambio):
    with pytest.raises(ValueError, match="no resuelven"):
        pp.plantillas_de_auxiliar(AUX | cambio, CAT)


def test_el_auxiliar_solo_se_ensena_cuando_el_esquema_del_sandbox_lo_admite():
    # Integrador I1.6: el esquema vigente admite el auxiliar por referencia (plantillas_de, plantillas, componentes);
    # la forma propuesta por E (plantillas copiadas dentro del auxiliar) ya no es la integrada.
    assert derivar.auxiliares_con_plantillas(ESQ_HOY) and not derivar.auxiliares_con_plantillas(PROPUESTO)
    hoy, con = pp.bloque_markdown(CAT), pp.bloque_markdown(CAT, True)
    assert "Precio auxiliar `Azure Private Link`" not in hoy and "Precio auxiliar `Azure Private Link`" in con
    assert all(f"`{i}`" in con.split("Precio auxiliar")[1] for i in AUX["componentes"])
    # I1.7: el auxiliar se explica en el bloque v4 (por id de plantilla), no en la tabla, que ya no lleva filtros
    assert "Precio auxiliar `Azure Private Link`" in pp.bloque_v4(CAT, True)
    assert "Precio auxiliar `Azure Private Link`" not in pp.bloque_v4(CAT, False)


def test_instrucciones_sincronizadas_y_bloque_con_impulsor_y_niveles():
    assert derivar.main(ARGS_EFECTIVO + ["--comprobar"]) == 0
    bloque = pp.bloque_v4(CAT, derivar.auxiliares_con_plantillas(ESQ_EFECTIVO))
    assert EXPERTO.count(bloque) == 1 and "Precio auxiliar `Azure Private Link`" in bloque
    fuera = pp.modelos_fuera_siempre(CAT)
    for c, p in PARES:
        assert (f"`{p['id']}` {pp._marca_v4(p)}" in bloque) == (p.get("modelo") not in fuera), p["id"]
    for c in CAT["componentes"]:
        for n in c.get("niveles") or []:
            linea = next(x for x in bloque.splitlines() if x.startswith(f"- {c['nombre_oficial']} (`{c['id']}`)")
                         and "«" in x)
            # I1.9: el bloque ya no copia límites ni fuente (la justificación es razón y cita): nivel y razones
            assert f"`{n['nivel']}` (" in linea
            assert all(f"`{r['id']}` (" in linea for r in n.get("razones_subida") or [])
    # I1.7: sin filtros ni productName el experto baja de 66.074 a unos 48 KB; que no vuelva a crecer sin medirlo
    # I1.9: 65,5 KB medidos (recursos del cliente, razones cerradas, modelo y cómputo); I1.6 funcionó con 66.074 B
    # I1.10 (ARR1): 66.828 B medidos el 18-10-2026 (regla de niveles en las dos direcciones y por_instancia)
    assert len(EXPERTO.encode("utf-8")) < 67000  # 52.100 B tras los arreglos de I1.7; 62,6 KB en I1.8 (medido)


def test_experto_con_las_reglas_de_les_g_100():
    plano = " ".join(EXPERTO.split())
    for frase in ("SOLO si la volumetría no está citada", "precio de referencia de una de sus plantillas",
                  "`base_volumen` = {`cita`, `cantidad_base`, `unidad_base`}", "Nunca «1 millón de referencia»",
                  "`justificacion_nivel` = {`nivel`, `razon`, `cita`}", "usa el nivel marcado «por defecto»",  # I1.9
                  "nunca escribes filtro, precio, unidad ni concepto", "`factor_override` = {`valor`, `cita`, `justificacion`}",
                  "`existente_del_cliente: {\"entrada\": \"EX-nn\"}`", "`incluido_en` = el `C-nn`",  # I1.9
                  "«A valorar con el volumen real»",
                  "Volumetría, Alcance funcional, Identidad y permisos del origen, Marco normativo, Ubicación de los "
                  "usuarios finales o Canales e integraciones", "`referencia_id: null`", "`arquitectura_id`"):
        assert frase in plano, frase
    assert "indica «concepto «…»»" not in EXPERTO and "(concepto «" not in EXPERTO
    assert "`depende_del_volumen`: el coste depende de un volumen de uso que el brief no da" not in EXPERTO


def test_verificador_comprueba_nivel_y_factor_contra_fuentes():
    plano = " ".join(VERIF.split())
    for frase in ("**Nivel del servicio**", "Sobredimensionado o insuficiente", "`campo` = `sku`", "**Factor cambiado**",
                  "`campo` = `cantidad`", "`fuente_nivel`", "`| factor:", "**Motivo de no valoración**",
                  "`campo` = `motivo`", "no tienes herramienta de precios"):
        assert frase in plano, frase
    assert re.search(r"Exchange Online|Microsoft 365 sin `catalogo_id`", VERIF) and "como SharePoint Online" not in VERIF


def test_el_ejemplo_de_la_herramienta_de_precios_es_una_plantilla_real():
    """I1.6: la descripción de `$filter` de agentes/prices-openapi.json enseñaba un filtro amplio, sin meterName y en
    una región vetada para Azure AI Search (swedencentral). Ahora es la plantilla `s1`, exacta."""
    if not (RAIZ / "agentes" / "prices-openapi.json").exists():  # I1.7: la herramienta de precios se retira
        pytest.skip("agentes/prices-openapi.json ya no existe (I1.7, decisión 1)")
    spec = json.loads((RAIZ / "agentes" / "prices-openapi.json").read_text(encoding="utf-8"))
    texto = json.dumps(spec, ensure_ascii=False)
    ejemplo = re.search(r"Ejemplo: (serviceName eq [^\"]+)\"", texto).group(1)
    assert ejemplo in {p["filtro"] for _, p in PARES}


@pytest.mark.parametrize("quitar", ["plantillas", "plantillas_de", "componentes", "componentes_fuente_url"])
def test_auxiliar_con_el_vinculo_a_medias_falla_en_alto(quitar):
    """Revisión I1.6 (media, cierta): sin una de las cuatro claves, el vínculo se perdía en silencio."""
    a = {k: v for k, v in AUX.items() if k != quitar}
    with pytest.raises(ValueError, match="a medias"):
        pp.plantillas_de_auxiliar(a, CAT)


def test_auxiliar_con_un_componente_sin_plantillas_falla_en_alto():
    with pytest.raises(ValueError, match="no son filas con plantillas"):
        pp.plantillas_de_auxiliar(AUX | {"componentes": AUX["componentes"] + ["az-teams"]}, CAT)


def test_derivar_no_deriva_un_catalogo_con_niveles_o_plantillas_mal(monkeypatch, capsys):
    """Revisión I1.6 (media, cierta): la forma se comprobaba solo en pytest; ahora derivar.main falla en alto (rc 2)."""
    import copy
    roto = copy.deepcopy(CAT)
    s = next(c for c in roto["componentes"] if c["id"] == "az-ai-search")
    s["niveles"][0]["plantillas"] = ["no-existe"]
    s["plantillas_precio"][0]["divisor"] = 1000
    monkeypatch.setattr(derivar, "cargar", lambda ruta=None: roto)
    assert derivar.main(["--comprobar"]) == 2
    salida = capsys.readouterr().out
    assert "NO SE DERIVA" in salida and "az-ai-search: nivel Basic" in salida and "az-ai-search/basic: divisor" in salida
    assert derivar.problemas_catalogo(CAT) == []


def test_auxiliar_con_las_claves_vacias_falla_en_alto():
    """Revisión I1.6, 2.ª pasada (baja, cierta): las cuatro claves presentes y vacías no son «sin vínculo»."""
    vacio = AUX | {"plantillas": [], "plantillas_de": "", "componentes": [], "componentes_fuente_url": ""}
    with pytest.raises(ValueError, match="a medias"):
        pp.plantillas_de_auxiliar(vacio, CAT)
    sin = {k: v for k, v in AUX.items() if k not in ("plantillas", "plantillas_de", "componentes",
                                                      "componentes_fuente_url")}
    assert pp.plantillas_de_auxiliar(sin, CAT) == []
