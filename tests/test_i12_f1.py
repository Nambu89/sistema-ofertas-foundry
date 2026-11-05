"""I1.2, papel F1: REV-1 (nubes con lista blanca), REV-2 (veto de región por id y alias), REV-3 (restaurar sin
canales), REV-5 (rótulo de rechazo), VERIF-9 (paso en modo lotes) y REV-4 (pruebas que faltaban). Sin red."""
from __future__ import annotations

import copy
import json
import pathlib
import sys

import pytest

from tests.test_i1_estado_comun import Mundo, ejemplo

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
sys.path.insert(0, str(RAIZ))

from nucleo import estado as est_mod, experto, suficiencia  # noqa: E402
import verificar_paquete as V  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)

CATALOGO = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


# ── REV-1: `nubes` falla cerrado con una lista blanca, igual en el núcleo y en la puerta ─────────────────────
NO_ADMITIDAS = [
    # proveedores que la lista negra no enumeraba
    "Azure y DigitalOcean", "Azure y Hetzner", "Azure y SAP BTP", "Azure y A W S", "Azure (y otra nube)",
    "Azure y Cloudflare", "Azure y Scaleway",
    # despliegue local
    "Azure y nuestro centro de datos", "Azure y servidores locales", "Azure y nuestras instalaciones",
    "Azure con VMware en local", "Azure Stack HCI en nuestras oficinas", "En local, con Azure de respaldo",
    # nube privada
    "Azure y nube privada", "Nube privada sobre Azure", "Azure Government",
    # negaciones reales: falla cerrado aunque niegue
    "Azure, no AWS", "No queremos AWS, solo Azure", "Nada de AWS: Azure", "Azure y ninguna otra nube",
    "Queremos que esto viva en Azure, no queremos abrir otra nube", "No Azure",
    # trampas de caracteres y otros textos
    "\uff21\uff5a\uff55\uff52\uff45", "Azure\u200b", "AzureDevOps", "Azure y Microsoft Teams", "Microsoft Teams", "", "   ",
]
ADMITIDAS = ["Azure", "azure", "MICROSOFT AZURE", "«Azure»", "Azure.", "Solo en Azure.", "Únicamente en Azure",
             "La solución debe vivir en Azure.", "Queremos que viva en Azure", "en Microsoft Azure"]


@pytest.mark.parametrize("valor", NO_ADMITIDAS)
def test_nubes_no_admitidas_fallan_cerrado_en_nucleo_y_puerta(valor):
    assert suficiencia.nubes_fuera_de_i1([valor]), valor
    assert V.nubes_fuera_de_i1([valor]), valor


@pytest.mark.parametrize("valor", ADMITIDAS)
def test_nubes_admitidas_pasan_en_nucleo_y_puerta(valor):
    assert suficiencia.nubes_fuera_de_i1([valor]) == [] and V.nubes_fuera_de_i1([valor]) == []


def test_lista_blanca_identica_en_nucleo_y_puerta():
    assert V.NUBES_ADMITIDAS == suficiencia.NUBES_ADMITIDAS and V.PLANTILLAS_NUBES == suficiencia.PLANTILLAS_NUBES
    assert all(suficiencia.forma_nubes(x) == x for x in suficiencia.NUBES_ADMITIDAS)


def test_nubes_no_admitida_cuenta_un_intento_y_la_cita_conserva_el_literal(m):
    m.iniciar()
    req = m.requisitos_modelo()
    req["campos"]["nubes"]["entradas"][0]["valor"] = "Azure y nuestro centro de datos"
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))
    assert rc == 1 and "fuera de I1" in out and "(intento 1/3)" in out and "el valor es «Azure»" in out, out
    req = m.requisitos_modelo()
    cita = req["campos"]["nubes"]["entradas"][0]["cita"]
    req["campos"]["nubes"]["entradas"][0]["valor"] = "Azure"
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))
    nubes = m.estado()["carga"]["requisitos"]["campos"]["nubes"]["entradas"][0]
    assert "fuera de I1" not in out and nubes == {**nubes, "valor": "Azure", "cita": cita}, out


# ── REV-2: el veto de región reconoce el servicio por id y por todos sus alias ────────────────────────────────
@pytest.mark.parametrize("servicio, cid", [
    ("Azure AI Search", "az-ai-search"), ("Azure AI Search", None), ("AZURE  AI  SEARCH", None),
    ("Azure Cognitive Search", None), ("Azure AI Search (S1)", None), ("AI Search", None), ("ai-search", None),
    ("Cognitive Search, nivel S1", None), ("Azure AI Search", "az-storage"), ("Búsqueda con Azure AI Search", None)])
@pytest.mark.parametrize("region", ["swedencentral", "westeurope", "northeurope", "germanywestcentral"])
def test_veto_por_id_y_por_alias_en_nucleo_y_puerta(servicio, cid, region):
    comp = {"servicio": servicio, "catalogo_id": cid, "region": region}
    motivo = experto.region_no_admitida(comp, CATALOGO)
    assert motivo and V.region_no_admitida(comp, CATALOGO) == motivo and "search-region-support" in motivo


@pytest.mark.parametrize("comp", [
    {"servicio": "Azure Cognitive Search", "catalogo_id": None, "region": "francecentral"},
    {"servicio": "Azure Blob Storage", "catalogo_id": None, "region": "swedencentral"},
    {"servicio": "Microsoft Foundry", "catalogo_id": "az-foundry", "region": "swedencentral"},
    {"servicio": "", "catalogo_id": None, "region": "swedencentral"}])
def test_sin_veto_fuera_de_las_regiones_vetadas_o_de_otro_servicio(comp):
    assert experto.region_no_admitida(comp, CATALOGO) is None and V.region_no_admitida(comp, CATALOGO) is None


def _cat_foundry_tools() -> dict:
    """Doble mínimo con el caso que señaló Revisión: «Foundry Tools» es el nombre de precios de varios servicios."""
    veto = {"region": "northeurope", "motivo": "prueba", "fuente_url": "https://learn.microsoft.com/x", "consultado": "2026-10-08"}
    return {"componentes": [
        {"id": "az-foundry-agent-service", "nombre_oficial": "Foundry Agent Service", "service_name_precios": "Foundry Tools",
         "regiones_no_admitidas": [veto]},
        {"id": "az-speech", "nombre_oficial": "Azure Speech in Foundry Tools", "service_name_precios": "Foundry Tools"}]}


@pytest.mark.parametrize("cat", [_cat_foundry_tools(), CATALOGO])
@pytest.mark.parametrize("cid", ["az-speech", None])
def test_un_alias_compartido_no_veta_a_otro_servicio(cat, cid):
    comp = {"servicio": "Azure Speech in Foundry Tools", "catalogo_id": cid, "region": "northeurope"}
    assert experto.region_no_admitida(comp, cat) is None and V.region_no_admitida(comp, cat) is None
    assert "foundrytools" not in experto.alias_inequivocos(cat)["az-foundry-agent-service"]
    assert experto.alias_inequivocos(cat) == V.alias_inequivocos(cat)
    agente = {"servicio": "Foundry Agent Service", "catalogo_id": None, "region": "northeurope"}
    assert experto.region_no_admitida(agente, cat) and V.region_no_admitida(agente, cat)


# Homoglifos con escapes (U+0435 y U+0410 cirílicas; U+0391 y U+0399 griegas): los caza el alias tras plegar,
# también con otro catalogo_id; lo que no se pliega (U+691C U+7D22, ideogramas) falla cerrado solo fuera de catálogo.
@pytest.mark.parametrize("servicio, cid", [
    ("Azure AI S\u0435arch", None), ("\u0410zure Cognitive Search", None), ("Azure \u0391\u0399 Search", None),
    ("Azure AI S\u0435arch", "az-storage")])
def test_homoglifos_los_caza_el_alias_tras_plegar(servicio, cid):
    comp = {"servicio": servicio, "catalogo_id": cid, "region": "swedencentral"}
    motivo = experto.region_no_admitida(comp, CATALOGO)
    assert motivo and "reconocido por el nombre" in motivo and V.region_no_admitida(comp, CATALOGO) == motivo
    comp["region"] = "polandcentral"  # ninguna entrada del catálogo la veta
    assert experto.region_no_admitida(comp, CATALOGO) is None and V.region_no_admitida(comp, CATALOGO) is None


@pytest.mark.parametrize("comp", [
    {"servicio": "Azure AI \u691c\u7d22", "catalogo_id": None, "region": "swedencentral"},
    # Revisión, 3.\u00aa pasada: homoglifo fuera del mapa (U+0433), sin catalogo_id
    {"servicio": "Azure AI Sea\u0433ch", "catalogo_id": None, "region": "swedencentral"}])
def test_letras_no_latinas_sin_plegar_fallan_cerrado_sin_catalogo_id(comp):
    motivo = experto.region_no_admitida(comp, CATALOGO)
    assert motivo and "letras no latinas" in motivo and V.region_no_admitida(comp, CATALOGO) == motivo


def test_letras_no_latinas_con_un_catalogo_id_valido_mandan_el_id():
    """REVSN-3 (decisi\u00f3n del PM): la regla de letras no latinas solo se aplica sin catalogo_id. Con un id v\u00e1lido, el
    servicio es el del id: la oferta muestra su nombre oficial (Azure Blob Storage) y la nota avisa del nombre libre."""
    comp = {"id": "C-02", "servicio": "Azure AI Sea\u0433ch", "catalogo_id": "az-storage", "region": "swedencentral"}
    assert experto.region_no_admitida(comp, CATALOGO) is None and V.region_no_admitida(comp, CATALOGO) is None
    avisos = experto.avisos_respuesta({"componentes": [dict(comp, capa="datos_conocimiento")]}, CATALOGO)
    assert any("el nombre que vale es \u00abAzure Blob Storage\u00bb" in a for a in avisos)


def test_letras_no_latinas_con_nombre_coherente_con_su_id_no_vetan():
    ajeno = {"servicio": "Azure Blob Storage \u65e5\u672c\u8a9e", "catalogo_id": "az-storage", "region": "northeurope"}
    assert experto.region_no_admitida(ajeno, CATALOGO) is None and V.region_no_admitida(ajeno, CATALOGO) is None
    assert experto.HOMOGLIFOS == V.HOMOGLIFOS and all(k > 127 for k in experto.HOMOGLIFOS)


def test_tildes_y_signos_no_cuentan_como_letras_no_latinas():
    comp = {"servicio": "Búsqueda ñ «vectorial» – Almacén", "catalogo_id": None, "region": "swedencentral"}
    assert experto.region_no_admitida(comp, CATALOGO) is None and V.region_no_admitida(comp, CATALOGO) is None


def _doble_con_alias(alias) -> dict:
    """Doble del catálogo con el campo `alias` que añade F2 (CAMBIOS-I12-F1.md) y sin el nombre de precios."""
    cat = copy.deepcopy(CATALOGO)
    entrada = next(c for c in cat["componentes"] if c["id"] == "az-ai-search")
    entrada.pop("service_name_precios", None)
    entrada.pop("alias", None)  # el doble manda aunque F2 ya haya añadido el campo real
    if alias is not None:
        entrada["alias"] = alias
    return cat


def _entrada(alias) -> dict:
    return next(c for c in _doble_con_alias(alias)["componentes"] if c["id"] == "az-ai-search")


def test_el_campo_alias_del_catalogo_se_usa_en_nucleo_y_puerta():
    comp = {"servicio": "Azure Search (S1)", "catalogo_id": None, "region": "swedencentral"}
    assert experto.region_no_admitida(comp, _doble_con_alias(None)) is None  # sin alias no lo reconoce
    for alias in (["Azure Search", "Azure Cognitive Search"], "Azure Search",
                  [{"nombre": "Azure Search", "fuente_url": "https://learn.microsoft.com/azure/search/whats-new"}]):
        cat = _doble_con_alias(alias)
        assert experto.region_no_admitida(comp, cat) and V.region_no_admitida(comp, cat)
    assert experto.alias_servicio(_entrada(["Azure Search"])) == V.alias_servicio(_entrada(["Azure Search"]))
    assert experto.alias_servicio(_entrada(["Azure Search"])) == ["azureaisearch", "aisearch", "azuresearch"]  # nunca «search» suelto


def test_respuesta_con_alias_y_sin_catalogo_id_se_rechaza():
    resp, br = ejemplo("respuesta_experto"), ejemplo("brief")
    c = next(x for x in resp["componentes"] if x["catalogo_id"] == "az-ai-search")
    c.update(catalogo_id=None, servicio="Azure Cognitive Search", region="swedencentral",
             desviacion_justificada="Servicio de búsqueda vectorial gestionado para el índice documental.")
    # integrador I1.7 (decisión 1): el modelo ya no escribe filtros; un precio en un componente sin catalogo_id no tiene
    # plantilla (el núcleo lo rechaza) y, sin precio, el nombre lo sigue reconociendo (REVER-1)
    errores = i17_int.validar(resp, br, CATALOGO, br["perfiles_permitidos"])
    assert any("una línea de consumo solo vale para un componente del catálogo" in e for e in errores), errores
    resp["precios"] = [p for p in resp["precios"] if p["componente_id"] != c["id"]]
    errores = i17_int.validar(resp, br, CATALOGO, br["perfiles_permitidos"])
    assert any("swedencentral (reconocido por el nombre «Azure Cognitive Search»)" in e for e in errores), errores


# ── REV-3: un estado antiguo en EN_ANALISIS sin canales_integraciones vuelve a INFORMACION_INSUFICIENTE ────────
def _relevo_antiguo(m) -> tuple[str, bytes]:
    """Relevo de un estado «de antes de VERIF-2»: EN_ANALISIS, brief R1 sin la sección de canales y sin el campo."""
    from nucleo import restaurar
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    est = m.estado()
    del est["carga"]["requisitos"]["campos"]["canales_integraciones"]
    for b in est["carga"]["briefs"]:
        b["texto"] = b["texto"].replace(restaurar.SECCION_CANALES, "## Otros datos")
    est_mod.guardar(est, m.raiz)
    return restaurar.nombre_relevo(est["codigo"]), restaurar.componer_relevo(est, m.raiz)["zip"]


def test_restaurar_estado_antiguo_sin_canales_pregunta_y_tiene_salida(m, tmp_path, monkeypatch):
    from tests.test_i1_restaurar_relevo import contenedor_nuevo
    nombre, datos = _relevo_antiguo(m)
    contenedor_nuevo(m, tmp_path, monkeypatch, {nombre: datos})
    rc, out = m.run("restaurar", "--zip", nombre)
    assert rc == 0 and "MIGRADO: EN_ANALISIS -> INFORMACION_INSUFICIENTE" in out and "brief retirado" in out, out
    assert "canales_integraciones: ¿Desde qué canal" in out and "a) Microsoft Teams" in out
    assert "estado: INFORMACION_INSUFICIENTE" in out and "Presentar al comercial las preguntas a/b/c/d" in out
    est = m.estado()
    assert est["carga"]["briefs"] == [] and est["control_versiones"][-1]["subcomando"] == "restaurar"
    assert est["control_versiones"][-1]["estado_antes"] == "EN_ANALISIS"
    rc, out = m.run("asumir", "--campo", "canales_integraciones", "--valor", "Microsoft Teams")
    assert rc == 0 and "estado: EN_ANALISIS" in out, out
    rc, out = m.run("enrutar")
    assert rc == 0 and "## Canales e integraciones\n- Microsoft Teams [ASUMIDO" in out, out


def test_migrar_no_toca_un_estado_con_canales_ni_otros_estados():
    from nucleo import restaurar
    est = ejemplo("estado")
    assert restaurar.migrar_sin_canales(copy.deepcopy(est)) == []  # LISTA_PARA_REVISION
    est["estado"] = "EN_ANALISIS"
    assert restaurar.migrar_sin_canales(est) == [] and est["estado"] == "EN_ANALISIS"  # con canales


# ── REV-5: el rótulo de error solo tras un rechazo real del último subcomando ─────────────────────────────────
def test_incompleto_valido_repetido_tras_un_rechazo_no_hereda_el_rotulo(m):
    m.iniciar()
    req = m.requisitos_modelo()
    assert m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))[0] == 1
    malo = copy.deepcopy(req)
    malo["campos"]["plazo"]["entradas"][0]["cita"] = "una cita que no aparece en ninguna parte de la reunión"
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", malo))
    assert rc == 1 and "Terminar el turno: presentar al comercial el error (T1 intento 1/3)" in out
    for args in (("suficiencia", "--requisitos", m.entrada("requisitos.json", req)), ("estado",)):
        rc, out = m.run(*args)
        assert "Terminar el turno: presentar" not in out, out
        assert "SIGUIENTE PASO OBLIGATORIO: Presentar al comercial las preguntas a/b/c/d" in out


def test_marcas_de_tiempo_ordenadas_entre_fallos_y_controles():
    est = ejemplo("estado")
    est["control_versiones"][-1]["ts"] = "2999-01-01T10:00:00+01:00"  # control «en el futuro»: mismo segundo o más
    est["estado"] = "EN_ANALISIS"
    est_mod.registrar_intento(est, "T2", "error de prueba", "hipótesis de prueba")
    assert est["fallos"][-1]["ts"] == "2999-01-01T10:00:01+01:00"
    est_mod.anotar_control(est, "registrar-experto", "EN_ANALISIS", None)
    assert est["control_versiones"][-1]["ts"] == "2999-01-01T10:00:01+01:00"
    assert est_mod.rechazo_pendiente(est) == "T2"


# ── VERIF-9: en modo lotes, el SIGUIENTE PASO nombra el lote pendiente y su fichero ──────────────────────────
def test_siguiente_paso_en_modo_lotes_nombra_el_lote_y_su_fichero():
    est = ejemplo("estado")
    est["estado"], est["ronda_verificacion"] = "EN_VERIFICACION", 0
    lotes = est["carga"]["consolidado"]["lotes"]
    lotes[0]["respuesta"] = {"registrada": True}
    paso = est_mod.siguiente_paso(est)
    lid = lotes[1]["lote_id"]
    assert paso.startswith(f"Enviar el lote {lid} (2 de {len(lotes)} del consolidado") and "ronda 1" in paso, paso
    assert f"entrada/respuesta_verificador_{lid}.json" in paso and f"consolidados/{lid}.txt" in paso
    assert "respuesta_verificador_R" not in paso and lotes[0]["lote_id"] + "," not in paso
    assert paso.endswith("Lotes pendientes: " + ", ".join(x["lote_id"] for x in lotes[1:]))


def test_restaurar_en_verificacion_repone_los_ficheros_de_cada_lote(m, tmp_path, monkeypatch):
    from nucleo import restaurar
    from tests.test_i1_restaurar_relevo import contenedor_nuevo
    m.hasta_verificacion()
    est = m.estado()
    nombre = restaurar.nombre_relevo(est["codigo"])
    contenedor_nuevo(m, tmp_path, monkeypatch, {nombre: restaurar.componer_relevo(est, m.raiz)["zip"]})
    rc, out = m.run("restaurar", "--zip", nombre)
    lotes = est["carga"]["consolidado"]["lotes"]
    assert rc == 0 and lotes and f"SIGUIENTE PASO OBLIGATORIO: Enviar el lote {lotes[0]['lote_id']}" in out, out
    for x in lotes:
        assert (m.raiz / "consolidados" / f"{x['lote_id']}.txt").read_text(encoding="utf-8") == x["texto"] + "\n"
    perdido = m.raiz / "consolidados" / f"{lotes[-1]['lote_id']}.txt"  # mismo estado ya presente: repone lo que falte
    perdido.unlink()
    rc, out = m.run("restaurar", "--zip", nombre)
    assert rc == 0 and perdido.read_text(encoding="utf-8") == lotes[-1]["texto"] + "\n", out


# ── REV-4: negaciones de verdad en el aviso de frases y brief.generar con el canal ───────────────────────────
@pytest.mark.parametrize("frase", ["No queremos que los datos salgan de España.", "No hace falta integrarlo con SAP.",
                                   "Tampoco necesitamos exportar los informes a Excel."])
def test_frases_sin_cita_detecta_las_negaciones_de_verdad(frase):
    texto = f"<v Cliente Uno>{frase}</v>\n"
    assert [x[0] for x in suficiencia.frases_requisito_sin_cita(texto, [])] == [frase]
    assert suficiencia.frases_requisito_sin_cita(texto, [frase]) == []


def test_brief_generar_lleva_el_canal_de_los_requisitos(m):
    m.hasta_analisis()
    rc, out = m.run("enrutar")
    canales = m.estado()["carga"]["requisitos"]["campos"]["canales_integraciones"]["entradas"]
    linea = "\n".join(f"- {e['valor']}" for e in canales)
    texto = m.estado()["carga"]["briefs"][-1]["texto"]
    assert rc == 0 and f"## Canales e integraciones\n{linea}\n" in texto, texto
