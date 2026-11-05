"""I1.9 · papel P (continuación): huecos de la lectura de una razón de subida que señalaron E (E19-8, Revisión E1) y
Revisión 2. Cada caso pasa por el núcleo y por la réplica de la puerta (i19_p_datos.reglas_i19 o la función _r)."""
from __future__ import annotations

import random

import pytest

from tests import i19_p_datos as D
from tests.test_i19_p_niveles import JN_S1, caso, nivel, s1
from nucleo import experto

CAT = D.catalogo_i19()
APIM = next(f for f in CAT["componentes"] if f["id"] == "az-api-management")
PRIVADO = next(r for n in experto.niveles_de(APIM) for r in n["razones"] or [] if r["id"] == "privado_red")
S1_GB = dict(JN_S1, cita="46 consultas al mes; el almacenamiento, en GB.")


def ambos(razon, cita):
    a, b = experto.razon_cumplida(razon, cita), D.R19.razon_cumplida_r(razon, cita)
    assert a == b, cita
    return a


def test_umbral_la_unidad_tiene_que_ir_junto_al_numero():
    """Revisión E1: «46 consultas al mes; el almacenamiento, en GB» leía 46 GB (por encima de 45): falla abierto."""
    br, req, r, cat = caso(lambda r, c: s1(r, c, S1_GB), volumetria=[S1_GB["cita"]])
    assert nivel(br, req, r, cat) == [("C-02", "razon_no_cumplida")]
    for cita in ("Unos 100 GB de documentos.", "Documentos: 100 GB.", "100 gigabytes de documentos en total."):
        br, req, r, cat = caso(lambda r, c, x=cita: s1(r, c, dict(JN_S1, cita=x)), volumetria=[cita])
        assert nivel(br, req, r, cat) == [], cita


def test_la_regla_de_i18_de_la_base_de_volumen_no_cambia():
    """La ventana es solo del umbral: cantidad_con_su_unidad (REV17-7, con réplica propia en la puerta) sigue igual."""
    cita = "46 consultas al mes; el almacenamiento, en GB"
    assert experto.numeros_con_unidad(cita, ["gigabytes"], ["GB"]) == [46]
    assert experto.numeros_con_unidad(cita, ["gigabytes"], ["GB"], experto.VENTANA_UNIDAD) == []
    assert experto.cantidad_con_su_unidad("Unas 2.000 consultas al mes de 100 técnicos.", 2000, ["consultas"])


@pytest.mark.parametrize("como", ["origen", "estado", "brief"])
def test_una_suposicion_nunca_sube_un_nivel(como):
    """Recomendación de E: una línea ASUMIDO no es una cita que cumpla una razón (las instrucciones ya lo prohíben)."""
    cita = "Unos 100 GB de documentos."
    br, req, r, cat = caso(lambda r, c: s1(r, c, JN_S1), volumetria=[] if como == "brief" else [cita])
    vol = req["campos"]["volumetria"]
    if como == "origen":
        vol["entradas"][-1]["origen"] = "ASUMIDO"
    elif como == "estado":
        vol["estado"] = "ASUMIDO"
    else:
        br["texto"] = br["texto"].replace("Volumetría: entre 50 y 100 técnicos.; Unos 3.000 documentos.; Unas 2.000 "
                                          "consultas al mes.", f"Volumetría: {cita}{experto.MARCA_ASUMIDO}")
        r["brief_recibido"] = br["texto"]
    assert nivel(br, req, r, cat) == [("C-02", "requisito_no_literal")]
    # control: la misma cita CITADA sí sube (y la regla de PR16-4 del factor_override sigue admitiendo lo ASUMIDO)
    br, req, r, cat = caso(lambda r, c: s1(r, c, JN_S1), volumetria=[cita])
    assert nivel(br, req, r, cat) == []


def test_una_negacion_tras_la_palabra_clave_anula_la_caracteristica():
    """Residual de E (E19-3): «Punto de conexión privado: no requerido.» cumplía «privado_red». Falla abierto: cerrado."""
    for cita in ("Punto de conexión privado: no requerido.", "Private Link no es necesario.",
                 "Conexiones privadas, ninguna."):
        assert not ambos(PRIVADO, cita), cita
    for cita in ("Todo privado, con punto de conexión privado en cada servicio.", "Private Link en todo. No hay prisa.",
                 "Se pide punto de conexión privado; no admiten acceso público."):
        assert ambos(PRIVADO, cita), cita


def test_no_solo_afirma():
    """Revisión 2 (media): «No solo requiere …» afirma lo que sigue; un «no» suelto sigue negando."""
    assert ambos(PRIVADO, "No solo requiere punto de conexión privado, también cifrado.")
    assert not ambos(PRIVADO, "No requiere punto de conexión privado, solo cifrado.")


def test_una_negacion_antes_de_los_dos_puntos_tambien_niega():
    """Revisión I1.9 (3, alta): «No se necesita: red privada.» afirmaba la característica porque los dos puntos cortaban
    la cláusula; para la negación anterior ya no cortan (falla cerrado). La réplica de la puerta, igual."""
    for cita in ("No se necesita: punto de conexión privado.", "Sin requisito de red: punto de conexión privado.",
                 "Nunca: Private Link."):
        assert not ambos(PRIVADO, cita), cita
    for cita in ("Requisito de red: punto de conexión privado en cada servicio.",
                 "No hay prisa. Red: punto de conexión privado.", "Sin acceso público, punto de conexión privado."):
        assert ambos(PRIVADO, cita), cita


def test_e19_8_el_modelo_con_punto_se_puede_nombrar():
    razon = experto.razones_modelo(CAT, "gpt-6.1-sol")[0]
    assert razon == D.R19.razones_modelo_r(CAT, "gpt-6.1-sol")[0]
    assert ambos(razon, "El cliente pide gpt-6.1-sol en la solución.")
    assert ambos(razon, "Se usará GPT-6.1 Sol.")
    assert not ambos(razon, "No se usará gpt-6.1-sol.")
    assert not ambos(razon, "El cliente pide gpt-6. 1-sol queda fuera.")   # un punto seguido de espacio sí corta


def test_afirmada_y_numeros_iguales_a_la_replica_en_casos_al_azar():
    rnd = random.Random(19082)
    trozos = ["no", "sin", "solo", "red privada", "punto de conexión privado", "200", "GB", "gigabytes", "3.000",
              "documentos", ":", ";", ".", ",", "(", ")", "¿", "gpt-6.1-sol", "nunca", "es", "pide", "1,5", "\n"]
    for _ in range(600):
        texto = " ".join(rnd.choice(trozos) for _ in range(rnd.randint(1, 12)))
        for frase in ("red privada", "punto de conexión privado", "gpt-6.1-sol"):
            assert experto.afirmada(texto, frase) == D.R19.afirmada_r(texto, frase), (texto, frase)
        for v in (None, 0, 1, 3):
            assert experto.numeros_con_unidad(texto, ["gigabytes"], ["GB"], v) == \
                D.R19.numeros_con_unidad_r(texto, ["gigabytes"], ["GB"], v), (texto, v)


def test_e19_9_segmento_del_verificador_con_razon_y_con_recurso_del_cliente():
    """E19-9: la línea del componente lleva la forma que esperan las instrucciones del verificador (I1.9)."""
    from tests.test_i19_p_existentes import caso_h1
    r, br, req = caso_h1()
    _, c = D.analizar(r, br, req, CAT)
    apim = experto.segmento_verificador_i19(D.comp_de(c, "C-06"), c, CAT, req, lambda t: t.replace("Hostelia", "[X]"))
    assert apim.startswith(" | existente del cliente: EX-06 | cita: «") and "API Management" in apim
    assert "nivel:" not in apim and "requisito:" not in apim
    assert experto.segmento_verificador_i19(D.comp_de(c, "C-03"), c, CAT, req) == ""      # nivel por defecto
    br, req, r, cat = caso(lambda r, c: s1(r, c, JN_S1), volumetria=["Unos 100 GB de documentos."])
    _, c = D.analizar(r, br, req, cat)
    seg = experto.segmento_verificador_i19(D.comp_de(c, "C-02"), c, cat, req)
    assert seg.startswith(" | nivel: S1 | razon: almacenamiento («") and "| cita: «Unos 100 GB de documentos.» |" in seg
    assert seg.endswith(experto.normalizar_url(experto.razon_de_justificacion(D.comp_de(c, "C-02"), c, cat)["fuente"]))
    assert "fuente_nivel: https://learn.microsoft.com/" in seg and "|" not in seg.split("«")[1].split("»")[0]


BASE_RANKING = {"cita": "Unas 2.000 consultas al mes.", "cantidad_base": 2000, "unidad_base": "consultas"}


def _ranking(r, cat):
    from tests import i18_p_datos as P
    P.precio(r, "P-09", "C-02", "ranking-semantico", base_volumen=BASE_RANKING)


@pytest.mark.parametrize("alcance, origen, esperado", [
    (None, "CITADO", [("P-09", "opcional_sin_requisito")]),                      # sin requisito: el valor por defecto
    (["Las búsquedas usan ranking semántico."], "CITADO", []),
    (["Las búsquedas usan ranking semántico."], "ASUMIDO", [("P-09", "opcional_sin_requisito")]),
    (["Las búsquedas no usan ranking semántico."], "CITADO", [("P-09", "opcional_sin_requisito")]),
])
def test_vc18_7_el_ranking_semantico_solo_con_un_requisito_que_lo_pida(alcance, origen, esperado):
    br, req, r, cat = caso(_ranking, alcance=alcance)
    for e in req["campos"]["alcance_funcional"]["entradas"]:
        if alcance and e["valor"] == alcance[0]:
            e["origen"] = origen
    assert [x for x in nivel(br, req, r, cat) if x[0] == "P-09"] == esperado
    _, c = D.analizar(r, br, req, cat)
    if not esperado:
        assert c is not None
        assert any(x.startswith("Medidor opcional valorado: ranking-semantico (P-09, C-02)")
                   for x in experto.lineas_para_revisor(c, cat, requisitos=req))


def test_vc18_7_opcional_mal_formado_falla_cerrado():
    def romper(r, cat):
        _ranking(r, cat)
        pl = next(p for p in D.fila(cat, "az-ai-search")["plantillas_precio"] if p["id"] == "ranking-semantico")
        pl["opcional"]["razones"][0].pop("fuente")
    br, req, r, cat = caso(romper, alcance=["Las búsquedas usan ranking semántico."])
    assert ("P-09", "opcional_no_valido") in nivel(br, req, r, cat)
