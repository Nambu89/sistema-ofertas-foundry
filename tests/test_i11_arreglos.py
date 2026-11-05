"""Arreglos de I1.1 tras la verificación (pruebas/I11/ARREGLOS.md): VERIF-1, VERIF-2 y VERIF-3. Sin red."""
from __future__ import annotations

import json
import pathlib
import sys
import zipfile

import pytest

from tests.test_i1_estado_comun import Mundo

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
sys.path.insert(0, str(RAIZ))

from nucleo import estado as est_mod, experto, suficiencia  # noqa: E402
import verificar_paquete as V  # noqa: E402
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)

CATALOGO = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
BREZALIA = RAIZ / "pruebas" / "I11" / "VERIF" / "e2e" / "transcripcion_sintetica_I11V.txt"
PAQUETE_BREZALIA = RAIZ / "pruebas" / "I11" / "VERIF" / "e2e" / "descargas" / "OF-BREZALIA-001-A-Paquete.zip"


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


# ── VERIF-1 (a): forma mínima generada desde el esquema y sincronía de las listas de campos ──────────────
def test_forma_minima_sincronizada_con_el_esquema_y_las_instrucciones():
    from agentes.esquemas import forma_requisitos
    assert forma_requisitos.main(["--comprobar"]) == 0
    esq = json.loads((RAIZ / "esquemas" / "requisitos.json").read_text(encoding="utf-8"))
    forma = json.loads(suficiencia.forma_minima())
    assert forma["schema"] == "preventa-requisitos/1"
    assert list(forma["campos"]) == list(esq["properties"]["campos"]["properties"])
    assert set(forma["campos"]) == set(suficiencia.CAMPOS)


def _constante(ruta: pathlib.Path, nombre: str):
    """Valor literal de una constante de módulo sin importarlo (la opción B necesita httpx, que aquí no está)."""
    import ast
    for nodo in ast.parse(ruta.read_text(encoding="utf-8")).body:
        if not isinstance(nodo, ast.Assign):
            continue
        destino = nodo.targets[0]
        if isinstance(destino, ast.Tuple):  # A, B = "a", "b"
            for objetivo, valor in zip(destino.elts, nodo.value.elts):
                if getattr(objetivo, "id", None) == nombre:
                    return ast.literal_eval(valor)
        elif getattr(destino, "id", None) == nombre:
            return ast.literal_eval(nodo.value)
    raise AssertionError(f"{nombre} no está en {ruta}")


def test_listas_de_campos_iguales_en_nucleo_puerta_experto_y_opcion_b():
    campos_b = _constante(RAIZ / "hosted" / "preventa_hosted" / "modelo.py", "CAMPOS")
    assert set(campos_b) == set(suficiencia.CAMPOS) == set(experto.CAMPOS_REQUISITOS)
    assert V.BLOQUEANTES == suficiencia.BLOQUEANTES and V.ASUMIBLES == suficiencia.ASUMIBLES
    assert "canales_integraciones" in suficiencia.ASUMIBLES


# ── VERIF-1 (b) y REV-1: nubes con lista blanca (falla cerrado), sin reescribir, misma regla en la puerta ──
# Desde REV-1 una frase con algo más que Azure (un canal, una negación) se rechaza: el valor es «Azure» y la cita
# conserva la frase. Los casos de proveedores no enumerados, despliegue local y nube privada están en test_i12_f1.
@pytest.mark.parametrize("valor, vale", [
    ("Azure", True), ("Microsoft Azure", True), ("la solución debe vivir en Azure y utilizarse desde Microsoft Teams", False),
    ("Azure con integración en Microsoft 365", False), ("Microsoft Teams", False), ("Azure y AWS", False),
    ("On-premise y Azure", False), ("Azure, en una nube híbrida", False), ("Google Cloud", False),
    ("Queremos que esto viva en Azure, no queremos abrir otra nube", False), ("Azure, no AWS", False), ("No queremos Azure, sino AWS", False),
    ("No solo Azure, sino también AWS", False), ("Azure y no solo AWS", False), ("Azure y no solamente Google Cloud", False),
    ("La solución debe vivir en Azure.", True), ("Queremos que esto viva en Azure", True)])
def test_nubes_misma_regla_en_nucleo_y_puerta(valor, vale):
    assert (not suficiencia.nubes_fuera_de_i1([valor])) is vale
    assert (not V.nubes_fuera_de_i1([valor])) is vale


def test_nubes_en_frase_completa_la_suficiencia_sin_reescribir(m):
    m.iniciar()
    req = m.requisitos_modelo()
    frase = "La solución debe vivir en Azure."
    req["campos"]["nubes"]["entradas"][0]["valor"] = frase
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))
    assert "fuera de I1" not in out and "(intento 1/3)" not in out, out
    assert m.estado()["carga"]["requisitos"]["campos"]["nubes"]["entradas"][0]["valor"] == frase


# ── VERIF-1 (c): tras un rechazo, el siguiente paso termina el turno ─────────────────────────────────────
def test_rechazo_termina_el_turno_hasta_otro_subcomando(m):
    m.iniciar()
    req = m.requisitos_modelo()
    req["campos"]["plazo"]["entradas"][0]["cita"] = "una cita que no aparece en ninguna parte de la reunión"
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))
    paso = "SIGUIENTE PASO OBLIGATORIO: Terminar el turno: presentar al comercial el error (T1 intento 1/3)"
    assert rc == 1 and paso in out and "Con su respuesta: Rellenar entrada/requisitos.json" in out
    rc, out = m.run("estado")
    assert rc == 0 and paso in out  # el turno siguiente ve lo mismo y hace lo que va tras «Con su respuesta»
    rc, out = m.run("registrar-fallo", "--fase", "T1", "--error", "HTTP 424", "--hipotesis", "corte de la herramienta")
    assert "Terminar el turno: presentar" not in out and "SIGUIENTE PASO OBLIGATORIO: Rellenar" in out


def test_rechazo_y_despues_exito_quita_el_prefijo(m):
    m.iniciar()
    req = m.requisitos_modelo()
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", {"objetivo": req["campos"]["objetivo"]}))
    assert rc == 1 and "Terminar el turno: presentar al comercial el error (T1 intento 1/3)" in out
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))
    assert "Terminar el turno: presentar" not in out and "estado: INFORMACION_INSUFICIENTE" in out


def test_opcion_b_usa_el_mismo_prefijo_de_rechazo():
    ruta = RAIZ / "hosted" / "preventa_hosted" / "turno.py"
    assert _constante(ruta, "PREFIJO_RECHAZO") == est_mod.PREFIJO_RECHAZO
    assert _constante(ruta, "CON_SU_RESPUESTA") == est_mod.CON_SU_RESPUESTA


def test_opcion_b_quita_el_prefijo_de_rechazo():
    pytest.importorskip("httpx")
    from hosted.preventa_hosted import turno
    sig = (f"{est_mod.PREFIJO_RECHAZO} (T4 intento 1/3), sin un segundo intento en este turno. "
           f"{est_mod.CON_SU_RESPUESTA}Preparar entrada/estimacion_entrada.json desde tareas_propuestas")
    assert turno._sin_rechazo(sig).startswith("Preparar entrada/estimacion_entrada.json")
    assert turno._sin_rechazo("enrutar") == "enrutar"


# ── VERIF-2: canal en su campo, en el brief y en el alcance; frases del cliente sin cita a la vista ──────
def _citas_brezalia() -> list[str]:
    est = json.loads(zipfile.ZipFile(PAQUETE_BREZALIA).read("estado.json"))
    return [e["cita"] for d in est["carga"]["requisitos"]["campos"].values() for e in d["entradas"] if e.get("cita")]


def test_frases_sin_cita_detecta_el_teams_perdido_del_paquete_real():
    texto = BREZALIA.read_text(encoding="utf-8")
    frases = suficiencia.frases_requisito_sin_cita(texto, _citas_brezalia())
    assert frases == [("Queremos que viva en Azure y que se use desde Microsoft Teams.",
                       "y que se use desde Microsoft Teams.")]
    cubierto = suficiencia.frases_requisito_sin_cita(texto, _citas_brezalia() + ["y que se use desde Microsoft Teams"])
    assert cubierto == []


def test_frases_sin_cita_ignora_a_devoteam_y_las_negaciones_no_importan():
    texto = "<v Responsable comercial>Hoy quiero entender bien la necesidad antes de proponer nada.</v>\n"
    assert suficiencia.frases_requisito_sin_cita(texto, []) == []
    texto = "<v Cliente Uno>Necesitamos exportar los informes a Excel cada semana.</v>\n"
    assert suficiencia.frases_requisito_sin_cita(texto, [])[0][1] == "Necesitamos exportar los informes a Excel cada semana."


def test_canales_en_el_brief_en_el_alcance_y_pregunta_si_falta(m):
    m.iniciar()
    req = m.requisitos_modelo()
    req["campos"]["canales_integraciones"] = {"estado": "FALTA", "entradas": []}
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))
    assert rc == 1 and "canales_integraciones: ¿Desde qué canal" in out and "a) Microsoft Teams" in out
    from tests.test_i1_estado_comun import ejemplo
    assert "## Canales e integraciones\n- Microsoft Teams\n## Usuarios y marco normativo" in ejemplo("brief")["texto"]


def test_textos_del_cliente_llevan_el_canal_en_el_alcance():
    from tests.test_i1_estado_comun import ejemplo
    from nucleo import textos_cliente
    est = ejemplo("estado")
    tarifa = json.loads((RAIZ / "tests" / "insumos" / "rate-card.sintetica.json").read_text(encoding="utf-8"))
    textos = textos_cliente.componer(est, CATALOGO, tarifa)
    alcance = [(x["texto"], x["hechos"]) for x in textos["alcance"]]
    assert ("Canal o integración: Microsoft Teams.", ["R-canales_integraciones"]) in alcance


def test_nota_lista_las_frases_sin_cita_y_declara_si_no_hay_transcripcion():
    from tests.test_i1_estado_comun import ejemplo
    from nucleo import nota_revision
    est = ejemplo("estado")
    textos = nota_revision.textos_docx(nota_revision.construir(est, CATALOGO, "<v Cliente Uno>Hay que exportar "
                                                                              "los informes a Excel cada semana.</v>\n"))
    assert any("Hay que exportar los informes a Excel cada semana." in t for t in textos)
    assert any("Detector heurístico" in t for t in textos)
    sin = nota_revision.textos_docx(nota_revision.construir(est, CATALOGO, None))
    assert any("No se ha podido comprobar: falta el texto de la transcripción" in t for t in sin)


# ── VERIF-3: Azure AI Search no se propone en una región que Learn veta, ni con catalogo_id null ─────────
@pytest.mark.parametrize("comp, vetado", [
    ({"catalogo_id": "az-ai-search", "servicio": "Azure AI Search", "region": "swedencentral"}, True),
    ({"catalogo_id": None, "servicio": "Azure  AI Search", "region": "westeurope"}, True),
    ({"catalogo_id": "az-ai-search", "servicio": "Azure AI Search", "region": "francecentral"}, False),
    ({"catalogo_id": "az-foundry", "servicio": "Microsoft Foundry", "region": "swedencentral"}, False)])
def test_region_vetada_misma_regla_en_nucleo_y_puerta(comp, vetado):
    assert bool(experto.region_no_admitida(comp, CATALOGO)) is vetado
    assert bool(V.region_no_admitida(comp, CATALOGO)) is vetado
    if vetado:
        assert "search-region-support" in experto.region_no_admitida(comp, CATALOGO)


def test_respuesta_con_ai_search_en_swedencentral_se_rechaza():
    from tests.test_i1_estado_comun import ejemplo
    resp, br = ejemplo("respuesta_experto"), ejemplo("brief")
    assert not [e for e in i17_int.validar(resp, br, CATALOGO, ejemplo("estado")["carga"]["briefs"][0]
                                                         ["perfiles_permitidos"]) if "región" in e]
    for c in resp["componentes"]:
        if c["catalogo_id"] == "az-ai-search":
            c["region"] = "swedencentral"
    errores = i17_int.validar(resp, br, CATALOGO, br["perfiles_permitidos"])
    assert any("Azure AI Search en swedencentral" in e and "high demand" in e for e in errores)


def test_frases_sin_cita_une_una_frase_partida_entre_cues_del_mismo_hablante():
    texto = ("WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\n<v Cliente Uno>Hay que</v>\n\n"
             "2\n00:00:04.000 --> 00:00:09.000\n<v Cliente Uno>exportar los informes a Excel cada semana.</v>\n\n"
             "00:00:09.000 --> 00:00:12.000\n<v Responsable comercial>Necesitamos confirmar el plazo con calma.</v>\n")
    frases = suficiencia.frases_requisito_sin_cita(texto, [])
    assert frases == [("Hay que exportar los informes a Excel cada semana.",
                       "Hay que exportar los informes a Excel cada semana.")]
    assert suficiencia.frases_requisito_sin_cita(texto, ["Hay que exportar los informes a Excel cada semana"]) == []


def test_intervenciones_cambio_de_hablante_cue_sin_hablante_y_texto_plano():
    vtt = ("WEBVTT\n\nNOTE\nComentario que no cuenta.\n\n7\n00:00:01.000 --> 00:00:03.000\n<v Responsable comercial>Hay que</v>\n\n"
           "00:00:03.000 --> 00:00:06.000\nexportar los informes a Excel cada semana.\n\n"
           "00:00:06.000 --> 00:00:09.000\n<v Cliente Uno>Necesitamos que funcione en catalán también.</v>\n")
    assert suficiencia._intervenciones(vtt) == [
        ("responsable comercial", "Hay que"), (None, "exportar los informes a Excel cada semana."),
        ("cliente uno", "Necesitamos que funcione en catalán también.")]
    plano = ("[00:01] Cliente Uno: Hay que exportar\nlos informes a Excel cada semana.\n"
             "[00:09] Responsable Comercial: Queremos verlo antes del viernes.")
    assert suficiencia._intervenciones(plano) == [
        ("cliente uno", "Hay que exportar los informes a Excel cada semana."),
        ("responsable comercial", "Queremos verlo antes del viernes.")]
    assert [f for f, _ in suficiencia.frases_requisito_sin_cita(plano, [])] == [
        "Hay que exportar los informes a Excel cada semana."]


def test_una_cita_que_corta_una_palabra_no_la_da_por_citada():
    texto = "<v Cliente Uno>Necesitamos exportar los informes a Excel cada semana.</v>\n"
    frases = suficiencia.frases_requisito_sin_cita(texto, ["Necesitamos exportar los informes a Exc"])
    assert frases == [("Necesitamos exportar los informes a Excel cada semana.", "Excel cada semana.")]
