"""I1.9 · papel P: nivel por defecto sin justificar y subida solo con una razón de la lista cerrada del catálogo y la
cita que la cumple, comprobada por código (VC18-1, PR18-3); el modelo, igual (VC18-5). Igualdad con la réplica en cada
caso (i19_p_datos.reglas_i19). Base: la respuesta de Brezalia (i18_p_datos.base) con el catálogo real de E (I1.9):
AI Search Basic por defecto y S1 con «almacenamiento» (umbral de 45 GB, unidad gigabytes o GB); API Management
Consumption por defecto, Developer con «no_productivo» y Basic v2 con «desarrollo_y_pruebas» o «nivel_nombrado»; B1
sin razones; gpt-6-sol solo con «modelo_nombrado»."""
from __future__ import annotations

import pytest

from tests import i18_p_datos as P
from tests import i19_p_datos as D
from nucleo import experto


def caso(mutar=None, volumetria=None, alcance=None, red=None):
    br, req, r, cat = P.base()
    for campo, extra in (("volumetria", volumetria), ("alcance_funcional", alcance), ("red_privada", red)):
        for v in extra or []:
            req["campos"][campo]["entradas"].append({"valor": v, "cita": "frase literal de la transcripción",
                                                     "fuente": "F1", "origen": "CITADO"})
    if mutar:
        mutar(r, cat)
    return br, req, r, cat


def nivel(br, req, r, cat):
    return D.reglas_i19(r, br, req, cat)["volumen_nivel"]


def s1(r, cat, jn=None):
    next(p for p in r["precios"] if p["id"] == "P-03")["plantilla_id"] = "s1"
    D.comp_de(r, "C-02")["justificacion_nivel"] = jn


JN_S1 = {"nivel": "S1", "razon": "almacenamiento", "cita": "Unos 100 GB de documentos."}


def test_control_el_nivel_por_defecto_no_se_justifica():
    br, req, r, cat = caso()
    assert P.analizar(r, br, req, cat)[0] == [] and nivel(br, req, r, cat) == []
    D.comp_de(r, "C-02")["justificacion_nivel"] = dict(JN_S1, nivel="Basic")
    assert nivel(br, req, r, cat) == [("C-02", "justificacion_sobrante")]


@pytest.mark.parametrize("jn, volumetria, esperado", [
    (None, None, [("C-02", "nivel_sin_justificar")]),
    (JN_S1, ["Unos 100 GB de documentos."], []),
    (dict(JN_S1, cita="Unos 100 gigabytes de documentos."), ["Unos 100 gigabytes de documentos."], []),
    (dict(JN_S1, cita="Unos 3.000 documentos."), None, [("C-02", "razon_no_cumplida")]),   # sin GB: no dimensiona
    (dict(JN_S1, cita="Unos 40 GB de documentos."), ["Unos 40 GB de documentos."],
     [("C-02", "razon_no_cumplida")]),                                                    # por debajo de 45 GB
    (dict(JN_S1, cita="Los permisos se asignan por grupos de Entra ID y el asistente debe respetarlos."), None,
     [("C-02", "requisito_no_literal")]),                                                 # PR18-3: no es volumetría
    (dict(JN_S1, cita="Unos 100 GB de documentos sin inventar."), None, [("C-02", "requisito_no_literal")]),
    (dict(JN_S1, razon="permisos_por_grupos"), ["Unos 100 GB de documentos."], [("C-02", "razon_desconocida")]),
    (dict(JN_S1, nivel="Basic"), ["Unos 100 GB de documentos."], [("C-02", "nivel_distinto_del_precio"),
                                                                  ("C-02", "razon_desconocida")]),
])
def test_subir_de_nivel_exige_razon_de_la_lista_y_cita_que_la_cumple(jn, volumetria, esperado):
    br, req, r, cat = caso(lambda r, c: s1(r, c, jn), volumetria=volumetria)
    assert nivel(br, req, r, cat) == esperado


def test_razones_mal_formadas_o_sin_fuente_del_por_defecto_fallan_cerrado():
    def malas(r, cat):
        s1(r, cat, JN_S1)
        D.fila(cat, "az-ai-search")["niveles"][1]["razones_subida"][0]["tipo"] = "otro"
    br, req, r, cat = caso(malas, volumetria=["Unos 100 GB de documentos."])
    assert nivel(br, req, r, cat) == [("C-02", "razones_no_validas")]

    def sin_fuente(r, cat):
        D.fila(cat, "az-ai-search")["nivel_por_defecto"] = "Basic"  # la forma de I1.8, sin fuente
    br, req, r, cat = caso(sin_fuente)
    assert nivel(br, req, r, cat) == [("C-02", "nivel_sin_justificar")]

    def sin_razones(r, cat):
        s1(r, cat, JN_S1)
        D.fila(cat, "az-ai-search")["niveles"][1]["razones_subida"] = None
    br, req, r, cat = caso(sin_razones, volumetria=["Unos 100 GB de documentos."])
    assert nivel(br, req, r, cat) == [("C-02", "nivel_sin_razones")]


def apim(nivel_apim: str, jn=None, base=None):
    def mutar(r, cat):
        P.comp(r, "C-07", "az-api-management", "Azure API Management", "aplicacion_integracion", nivel_apim,
               justificacion_nivel=jn)
        P.precio(r, "P-06", "C-07", {"Developer": "developer", "Basic v2": "basic-v2"}[nivel_apim], instancias=1)
        r["flujos"].append({"origen": "C-04", "destino": "C-07", "descripcion": "La aplicación llama a la API"})
    return mutar


@pytest.mark.parametrize("nivel_apim, jn, red, esperado", [
    ("Developer", None, None, [("C-07", "nivel_sin_justificar")]),
    ("Developer", {"nivel": "Developer", "razon": "no_productivo", "cita": "Microsoft Teams"}, None,
     [("C-07", "razon_no_cumplida")]),
    ("Basic v2", {"nivel": "Basic v2", "razon": "nivel_nombrado", "cita": "API Management"}, None,
     [("C-07", "requisito_no_literal")]),                                          # el caso de Hostelia (PR18-3)
    ("Basic v2", {"nivel": "Basic v2", "razon": "desarrollo_y_pruebas", "cita": "No es un entorno de pruebas."},
     ["No es un entorno de pruebas."], [("C-07", "razon_no_cumplida")]),           # la negación no justifica
    ("Basic v2", {"nivel": "Basic v2", "razon": "desarrollo_y_pruebas", "cita": "Es un entorno de pruebas."},
     ["Es un entorno de pruebas."], []),
])
def test_api_management_por_defecto_consumption_y_basic_v2_solo_con_su_razon(nivel_apim, jn, red, esperado):
    br, req, r, cat = caso(apim(nivel_apim, jn), alcance=red)
    assert nivel(br, req, r, cat) == esperado


def test_dos_instancias_del_por_defecto_solo_con_una_razon_de_su_nivel():
    br, req, r, cat = caso(lambda r, c: next(p for p in r["precios"] if p["id"] == "P-05").update(instancias=2),
                           alcance=["El asistente necesita alta disponibilidad."])
    assert nivel(br, req, r, cat) == [("C-04", "instancias_sin_justificar")]
    jn = {"nivel": "B1", "razon": "alta_disponibilidad", "cita": "60 técnicos."}   # razón de B1 en el catálogo de E
    D.comp_de(r, "C-04")["justificacion_nivel"] = jn
    assert nivel(br, req, r, cat) == [("C-04", "razon_no_cumplida")]
    jn["cita"] = "El asistente necesita alta disponibilidad."
    assert nivel(br, req, r, cat) == []
    D.fila(cat, "az-app-service")["niveles"][0]["razones_subida"] = None             # sin razones: falla cerrado
    assert nivel(br, req, r, cat) == [("C-04", "nivel_sin_razones")]


def sol(jn=None):
    def mutar(r, cat):
        for p in r["precios"]:
            p["plantilla_id"] = p["plantilla_id"].replace("gpt-6-luna", "gpt-6-sol")
        D.comp_de(r, "C-01").update(sku="gpt-6-sol Data Zone", justificacion_nivel=jn)
    return mutar


@pytest.mark.parametrize("jn, alcance, esperado", [
    (None, None, [("C-01", "modelo_sin_justificar")]),
    ({"nivel": "gpt-6-sol", "razon": "modelo_nombrado", "cita": "El cliente pide usar GPT-6 Sol."},
     ["El cliente pide usar GPT-6 Sol."], []),
    ({"nivel": "gpt-6-sol", "razon": "modelo_nombrado",
      "cita": "Buscar en procedimientos y manuales de equipos y citar el documento de origen."}, None,
     [("C-01", "razon_no_cumplida")]),
    ({"nivel": "gpt-6-sol", "razon": "razonamiento_complejo", "cita": "El cliente pide usar GPT-6 Sol."},
     ["El cliente pide usar GPT-6 Sol."], [("C-01", "razon_desconocida")]),
    ({"nivel": "gpt-6.1-sol", "razon": "modelo_nombrado", "cita": "x"}, None, [("C-01", "nivel_desconocido")]),
])
def test_el_modelo_por_defecto_es_luna_y_otro_exige_su_razon(jn, alcance, esperado):
    br, req, r, cat = caso(sol(jn), alcance=alcance)
    assert nivel(br, req, r, cat) == esperado


def test_luna_no_se_justifica_y_sin_modelo_por_defecto_falla_cerrado():
    br, req, r, cat = caso()
    D.comp_de(r, "C-01")["justificacion_nivel"] = {"nivel": "gpt-6-luna", "razon": "x", "cita": "60 técnicos."}
    assert nivel(br, req, r, cat) == [("C-01", "justificacion_sobrante")]
    br, req, r, cat = caso()
    cat.pop("modelo_por_defecto")
    assert nivel(br, req, r, cat) == [("C-01", "modelo_por_defecto_no_declarado")]


def test_la_nota_dice_el_nivel_por_defecto_y_la_subida_con_su_razon():
    br, req, r, cat = caso(lambda r, c: s1(r, c, JN_S1), volumetria=["Unos 100 GB de documentos."])
    _, c = P.analizar(r, br, req, cat)
    lineas = experto.lineas_para_revisor(c, cat, requisitos=req)
    assert any(x.startswith("Nivel de Azure AI Search (C-02): S1, por encima del valor por defecto (nivel por defecto "
                            "Basic), por la razón «almacenamiento» (") and "umbral: 100 gigabytes en la cita frente "
               "al límite de 45 del valor por defecto" in x for x in lineas)
    assert any(x.startswith("Cómputo por defecto") or x.startswith("Nivel por defecto de Azure App Service (C-04): B1")
               for x in lineas)
    assert any(x.startswith("Modelo por defecto de Microsoft Foundry (C-01): gpt-6-luna, sin justificación")
               for x in lineas)


def test_revision_una_negacion_lejana_en_la_misma_clausula_no_justifica():
    """Revisión I1.9: «No creemos que … necesite una red privada» queda fuera de una ventana de 4 palabras; se mira la
    cláusula entera antes de la palabra clave. Una negación en otra cláusula no cuenta."""
    razon = {"tipo": "caracteristica", "palabras_clave": ["red privada"]}
    assert not experto.razon_cumplida(razon, "No creemos que el cliente realmente necesite una red privada.")
    assert not D.R19.razon_cumplida_r(razon, "No creemos que el cliente realmente necesite una red privada.")
    for cita in ("Necesitan red privada.", "Sin coste adicional, necesitan red privada.", "Red privada; no admiten otra."):
        assert experto.razon_cumplida(razon, cita) and D.R19.razon_cumplida_r(razon, cita), cita
