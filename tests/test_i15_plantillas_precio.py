"""I1.5, papel E: plantillas de filtro de precio por servicio (decisión 1 del comercial; LES-G-090.9). Sin red."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
sys.path.insert(0, str(RAIZ))
from nucleo import experto  # noqa: E402
import verificar_paquete as V  # noqa: E402
from catalogo import derivar  # noqa: E402
from catalogo import plantillas_precio as pp  # noqa: E402
from tests.i17_e_comun import ARGS_EFECTIVO  # noqa: E402  (I1.7)

CAT = derivar.cargar()
from tests.i17_e_comun import DERIVADO_EFECTIVO  # noqa: E402  (I1.7: vista previa hasta integrar el esquema)
DERIVADO = json.loads(DERIVADO_EFECTIVO.read_text(encoding="utf-8"))
EXPERTO = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md").read_text(encoding="utf-8")
VERIF = (RAIZ / "agentes" / "instrucciones" / "verificador_i1.md").read_text(encoding="utf-8")
CON_ID = {c["id"] for c in DERIVADO["componentes"]}
PARES = [(c, p) for c in CAT["componentes"] for p in c.get("plantillas_precio") or []]
DER = {c["id"]: c for c in DERIVADO["componentes"]}


def test_cada_servicio_facturable_del_catalogo_tiene_al_menos_una_plantilla():
    for c in CAT["componentes"]:
        if c["id"] in CON_ID and c["service_name_precios"]:
            assert c.get("plantillas_precio"), c["id"]
        else:  # sin catalogo_id (no pueden llevar precio) o sin serviceName (SaaS y gratuitos)
            assert not c.get("plantillas_precio"), c["id"]


def test_las_plantillas_tienen_la_forma_exigida():
    assert len(PARES) >= 40
    for c, p in PARES:
        assert pp.problemas_plantilla(p, c) == [], (c["id"], p["id"])


def test_ids_y_filtros_unicos():
    for c in CAT["componentes"]:
        ids = [p["id"] for p in c.get("plantillas_precio") or []]
        assert len(ids) == len(set(ids)), c["id"]
    filtros = [p["filtro"] for _, p in PARES]
    assert len(filtros) == len(set(filtros))


@pytest.mark.parametrize("c, p", PARES, ids=[f"{c['id']}/{p['id']}" for c, p in PARES])
def test_comprobacion_real_de_cada_plantilla(c, p):
    k = p["comprobacion"]
    assert k["consultas"] >= 3 and len(k["bytes"]) == k["consultas"]
    assert 1 <= k["articulos"] <= 5 and len(k["precios_eur"]) == len(k["tramos"]) == k["articulos"]
    tope = float(pp._tope_kb(CAT).replace(",", ".")) * 1000  # I1.6: el bloque dice el tope medido
    assert max(k["bytes"]) < tope and f"menos de {pp._tope_kb(CAT)} KB" in pp.bloque_markdown(CAT)
    assert k["medidor"] and k["unidad"] and k["producto"]
    assert dict(pp.condiciones(p["filtro"]))["meterName"] == k["medidor"]
    assert bool(p.get("gratuito")) == all(x == 0 for x in k["precios_eur"])
    assert 3 <= len(pp.concepto(p)) <= 160


@pytest.mark.parametrize("c, p", PARES, ids=[f"{c['id']}/{p['id']}" for c, p in PARES])
def test_cada_plantilla_la_acepta_el_nucleo_y_la_puerta(c, p):
    """En su región de comprobación, con el catálogo derivado que monta el sandbox: ni el núcleo ni la puerta la
    rechazan, y el precio identifica exactamente su servicio."""
    entrada, region = DER[c["id"]], c["region_ue"]  # la región del componente; con region_precio, Global
    precio = {"id": "P-01", "componente_id": "C-01", "filtro": p["filtro"]}
    assert experto.problemas_precio(precio, entrada, region, DERIVADO) == []
    assert V.problemas_precio(precio, entrada, region, DERIVADO) == []
    conjuntos = experto.servicios_de_precio(precio, DERIVADO)
    assert len(conjuntos) == 1 and c["id"] in conjuntos[0]  # «Virtual Network» lo comparten dos filas sin productName


def test_filtro_para_region_solo_cambia_armregionname():
    c = next(x for x in CAT["componentes"] if x["id"] == "az-ai-search")
    p = c["plantillas_precio"][0]
    nuevo = pp.filtro_para_region(p, c, "westeurope")
    assert nuevo == p["filtro"].replace("'francecentral'", "'westeurope'") and nuevo != p["filtro"]
    assert pp.plantilla_de(nuevo, c, "westeurope") is p
    assert pp.filtro_para_region(p, c, "global") is None and pp.filtro_para_region(p, c, "West Europe") is None


def test_con_region_precio_global_no_cambia_nunca():
    c = next(x for x in CAT["componentes"] if x["id"] == "az-bot-service")
    p = c["plantillas_precio"][0]
    assert pp.filtro_para_region(p, c, "westeurope") == p["filtro"]
    assert pp.plantilla_de(p["filtro"], c, "westeurope") is p
    assert pp.plantilla_de(p["filtro"].replace("'Global'", "'westeurope'"), c, "westeurope") is None


@pytest.mark.parametrize("cambio", [
    lambda f: f + " ",                                            # un espacio de más
    lambda f: f.replace(" and meterName eq ", " and meterName  eq "),
    lambda f: f.split(" and meterName eq ")[0],                   # sin meterName
    lambda f: f.replace("'Standard S1 Unit'", "'standard s1 unit'"),  # mayúsculas
    lambda f: f.replace(" and productName eq 'Azure AI Search'", ""),
    lambda f: f.replace(" and ", " or ", 1),
    lambda f: "Azure AI Search",                                   # el 400 real de I1.4
])
def test_plantilla_de_rechaza_lo_que_no_es_la_plantilla(cambio):
    c = next(x for x in CAT["componentes"] if x["id"] == "az-ai-search")
    p = next(x for x in c["plantillas_precio"] if x["id"] == "s1")
    assert pp.plantilla_de(p["filtro"], c, "francecentral") is p
    assert pp.plantilla_de(cambio(p["filtro"]), c, "francecentral") is None


@pytest.mark.parametrize("filtro, motivo", [
    ("serviceName eq 'Storage' and armRegionName eq 'swedencentral'", "priceType"),
    ("serviceName eq 'Storage' or armRegionName eq 'swedencentral'", "campo eq"),
    ("serviceName eq 'Storage' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and skuName eq 'x'",
     "exige meterName"),
    ("serviceName eq 'Storage' and productName eq 'Files v2' and armRegionName eq 'swedencentral' and priceType eq "
     "'Consumption' and meterName eq 'x'", "productName"),
    ("armRegionName eq 'swedencentral' and serviceName eq 'Storage' and priceType eq 'Consumption' and skuName eq 'a' "
     "and meterName eq 'b'", "orden"),
])
def test_problemas_plantilla_falla_en_alto(filtro, motivo):
    c = next(x for x in CAT["componentes"] if x["id"] == "az-storage")
    assert any(motivo in m for m in pp.problemas_plantilla({"filtro": filtro}, c))


# --- Bloque de las instrucciones del experto (prueba de sincronía, LES-G-090.7 y LES-G-098.2) ---

def test_bloque_sincronizado_y_solo_en_el_experto():
    # I1.7 (decisión 1): las instrucciones llevan el bloque v4 (sin filtros); el de filtros ya no está en ninguna.
    assert EXPERTO.count(pp.bloque_v4(CAT, derivar.auxiliares_con_plantillas())) == 1
    assert pp.INICIO not in EXPERTO and pp.INICIO not in VERIF and pp.INICIO_V4 not in VERIF
    assert derivar.main(ARGS_EFECTIVO + ["--comprobar"]) == 0
    # el generador de I1.6 sigue disponible (lo usan las mediciones A/B de pruebas/I16/ARREGLOS/medicion)
    bloque = pp.bloque_markdown(CAT, derivar.auxiliares_con_plantillas(), completo=True)
    for c, p in PARES:
        assert f"  - `{p['id']}` {pp._nota(p)}: {p['filtro']}\n" in bloque, p["id"]
        assert f"{pp.prefijo(c)} {pp.resto(p, c)}" == p["filtro"], p["id"]
    # el modo de prefijo + resto sigue disponible (y es el que mide la variante A de la medición)
    corto = pp.bloque_markdown(CAT, derivar.auxiliares_con_plantillas())
    assert all(corto.count(f"Prefijo: `{pp.prefijo(c)}`.") == 1 for c, _ in PARES)


def test_el_ejemplo_del_bloque_es_una_plantilla_real():
    bloque = pp.bloque_markdown(CAT)
    s1 = next(p for c, p in PARES if c["id"] == "az-ai-search" and p["id"] == "s1")
    assert f"Ejemplo (`az-ai-search`, `s1`): `{s1['filtro']}`." in bloque


def test_bloque_lleva_las_reglas_duras():
    bloque = pp.bloque_markdown(CAT)
    for frase in ("EXACTAMENTE el prefijo de la fila", "carácter a carácter", "Nunca un filtro escrito a mano",
                  "sin `meterName`", "nunca `or`, `not`", "aborta tu respuesta", "sin `$skip` ni `api-version`",
                  "`armRegionName eq 'Global'` no cambia nunca", "no pruebes otro filtro", "no tiene plantilla, no consultes"):
        assert frase in " ".join(bloque.split()), frase
    # I1.6: 86 plantillas, niveles e impulsor; medido 20.725 bytes (CATALOGO.md §6). Que no crezca sin medirlo.
    # 23.180 B tras los arreglos de I1.7 (nivel EP1 y unidades por instancia); desde I1.7 las instrucciones llevan el bloque v4
    # I1.9: niveles nuevos de Bot Service y Defender y límites con sus notas de Learn: 26,8 KB (bloque de legado:
    # desde I1.7 las instrucciones llevan el bloque v4)
    assert len(bloque.encode("utf-8")) < 27500  # I1.8: niveles con [lleva …; hasta N], "el bloque viaja en cada vuelta del modelo: que no crezca sin medirlo"


def test_las_reglas_viejas_de_filtro_libre_ya_no_estan():
    assert "y, si lo conoces, `armSkuName` o `skuName`" not in EXPERTO
    assert "repite con el mismo filtro y `$skip`" not in EXPERTO
    # I1.7 (decisión 1): ni filtro literal ni herramienta de precios; el precio lo pone el código desde la instantánea
    assert "el filtro LITERAL de una plantilla" not in EXPERTO and "No tienes herramienta de precios" in EXPERTO


def test_no_valorables_con_motivo_de_la_lista_cerrada_y_en_el_bloque():
    bloque = pp.bloque_markdown(CAT)
    nv = [(c, x) for c in CAT["componentes"] for x in c.get("no_valorables") or []]
    assert nv
    for c, x in nv:
        assert x["motivo"] in pp.MOTIVOS_NO_VALORABLE and c["id"] in CON_ID
        assert f"{c['nombre_oficial']}: {x['concepto']}." in bloque
        forma = {"filtro": x.get("filtro"), "impulsor": "volumen", "divisor": 1}  # solo la forma del filtro
        assert not x.get("filtro") or pp.problemas_plantilla(forma, c) == []


@pytest.mark.parametrize("texto, motivo", [
    ("sin nada", "ancla"),
    (pp.ANCLA + "\n" + pp.ANCLA, "ancla"),
    (pp.INICIO + "\n" + pp.INICIO + "\n" + pp.FIN, "sobran"),
    (pp.FIN + "\n" + pp.INICIO, "desordenadas"),
    (pp.INICIO + "\nx", "faltan"),
])
def test_insertar_bloque_falla_en_alto(texto, motivo):
    with pytest.raises(ValueError, match=motivo):
        pp.insertar_bloque(texto, "B")


def test_insertar_bloque_antes_del_ancla_y_sustituye_despues():
    t = pp.insertar_bloque("a\n" + pp.ANCLA + " z\n", pp.INICIO + "\nuno\n" + pp.FIN)
    assert t == "a\n" + pp.INICIO + "\nuno\n" + pp.FIN + "\n" + pp.ANCLA + " z\n"
    assert pp.insertar_bloque(t, pp.INICIO + "\ndos\n" + pp.FIN).count("dos") == 1


def test_derivado_lleva_plantillas_solo_si_el_esquema_del_sandbox_las_admite():
    hoy = derivar.campos_opcionales_sandbox()
    sin = derivar.catalogo_componentes(CAT)
    assert ("plantillas_precio" in hoy) == any("plantillas_precio" in c for c in sin["componentes"])
    con = derivar.catalogo_componentes(CAT, hoy | {"plantillas_precio", "no_valorables"})
    s = next(c for c in con["componentes"] if c["id"] == "az-ai-search")
    # integrador I1.6: el esquema vigente añade concepto, impulsor y divisor (decisión 4, CAMBIOS-I16-E §3.1)
    assert s["plantillas_precio"][0].keys() == {"id", "filtro", "concepto", "impulsor", "divisor"}
    f = next(c for c in con["componentes"] if c["id"] == "az-functions")
    assert f["no_valorables"][0]["motivo"] == "precio_redondeado_en_eur"


def test_las_instrucciones_ya_no_traen_ningun_filtro():
    """I1.7 (decisión 1): el experto no escribe filtros, así que las instrucciones no enseñan ninguno (ni de ejemplo)."""
    assert "serviceName eq" not in EXPERTO and "serviceName eq" not in VERIF
    assert "$filter" not in EXPERTO and "$filter" not in VERIF


# --- I1.5 arreglos, VER15-1 / PR15-1: el bloque enseña el concepto literal cuando el meterName no basta -------------
CORTAS = [(c, p) for c, p in PARES if len(p["comprobacion"]["medidor"]) < 3]


def test_hoy_solo_b1_linux_tiene_un_meter_name_corto():
    """Si aparece otra, las pruebas siguientes la cubren igual; esta solo avisa de que el inventario ha cambiado."""
    assert [(c["id"], p["id"]) for c, p in CORTAS] == [("az-app-service", "b1-linux")]


def test_el_bloque_ya_no_ensena_el_concepto_lo_fija_el_codigo():
    """I1.6 (decisión 4, PR15-3): el concepto lo deriva el núcleo de la plantilla; el bloque solo dice que no se
    escribe. La derivación se prueba en tests/test_i16_e_derivado_e_instrucciones.py."""
    bloque = pp.bloque_markdown(CAT)
    assert "(concepto «" not in bloque and "`concepto` = `null`. No escribas el concepto" in bloque
    assert pp.concepto(CORTAS[0][1]) == "B1 (Azure App Service Basic Plan - Linux)"


def test_las_instrucciones_no_remiten_a_una_columna_concepto_inexistente():
    assert "columna «concepto»" not in EXPERTO and "indica «concepto «…»»" not in EXPERTO


def test_nota_lleva_el_impulsor_y_cuenta_tramos_distintos():
    base = {"id": "y", "impulsor": "volumen", "divisor": 1000000}
    assert pp._nota(base | {"comprobacion": {"tramos": [0.0, 13.0]}}) == "V/1M (2 tramos)"
    assert pp._nota(base | {"comprobacion": {"tramos": [0.0, 0.0]}}) == "V/1M"  # vCore de SQL: dos artículos, un tramo
    assert pp._nota({"id": "z", "impulsor": "tiempo", "divisor": 1, "gratuito": True, "comprobacion": {}}) == "T (gratuito)"


REAL_ARR = RAIZ / "pruebas" / "I15" / "ARREGLOS" / "REAL" / "B" / "sesion_2" / "respuesta_experto_AZ_R2.json"


@pytest.mark.skipif(not REAL_ARR.exists(), reason="sin la respuesta real aceptada de I1.5")
def test_el_concepto_que_deriva_el_codigo_es_el_que_acepto_la_respuesta_real():
    """Datos reales (LES-G-078). I1.6: la respuesta v2 ya no se valida con el núcleo de hoy (esquema v3, otra época);
    lo que se comprueba es que el concepto que deriva el código de cada plantilla es el que llevaba cada precio de la
    respuesta que llegó a LISTA_PARA_REVISION en I1.5 (B, sesión 2, ronda 2)."""
    resp = json.loads(REAL_ARR.read_text(encoding="utf-8"))
    por_filtro = {p["filtro"]: p for _, p in PARES}
    assert resp["precios"] and all(x["filtro"] in por_filtro for x in resp["precios"])
    for x in resp["precios"]:
        assert pp.concepto(por_filtro[x["filtro"]]) == x["concepto"], x["id"]
