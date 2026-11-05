"""I1.7 · D · Textos del cliente: una referencia por componente deduplicada por URL (REVERIF16-3), conceptos de GPT-6,
«precios consultados el <fecha>» (decisión 1), supuesto de consumo con el factor aplicado (decisión 2, LES-G-100.5) y
ciclo de vida del modelo (regla del PM). Sin red."""
from __future__ import annotations

import copy

import pytest

from tests.i17_d_datos import a_gpt6_v4, catalogo, catalogo_gpt6, esquema_propuesto, estado_flujo, recomponer
from nucleo import errores, textos_cliente as tc  # noqa: E402  (i17_d_datos pone sandbox/ en sys.path)


@pytest.fixture(autouse=True)
def _esquema(monkeypatch):
    esquema_propuesto(monkeypatch)


def _resp(componentes, referencias):
    return {"componentes": componentes, "referencias": referencias, "flujos": [], "precios": []}


def _c(i, nombre, ref, capa="datos_conocimiento"):
    return {"id": i, "servicio": nombre, "catalogo_id": None, "referencia_id": ref, "capa": capa}


def _r(i, url):
    return {"id": i, "url": url, "titulo": "Learn", "fecha_consulta": "2026-10-13"}


SP = "https://learn.microsoft.com/office365/servicedescriptions/sharepoint-online-service-description"
M365 = "https://learn.microsoft.com/microsoft-365/enterprise/microsoft-365-overview"


def test_una_referencia_por_componente_y_por_url():
    resp = _resp([_c("C-01", "Microsoft 365", "REF-01"), _c("C-02", "SharePoint Online", "REF-02"),
                  _c("C-03", "OneDrive", "REF-02")],
                 [_r("REF-01", M365), _r("REF-02", SP + "/"),
                  _r("REF-03", "https://learn.microsoft.com/microsoft-365/enterprise/otra-pagina"),
                  _r("REF-04", "https://learn.microsoft.com/azure/architecture/ai-ml/architecture/basic-microsoft-foundry-chat"),
                  _r("REF-05", "https://learn.microsoft.com/no-tiene-tema/x")])
    comp_ = tc._Composicion([], frozenset())
    capas = tc._arquitectura(resp, {}, comp_)["capas"]
    refs = tc._referencias(resp, capas, comp_)
    assert [(r["id"], r["titulo"]) for r in refs] == [
        ("REF-01", "Documentación oficial de Microsoft sobre Microsoft 365"),
        ("REF-02", "Documentación oficial de Microsoft sobre SharePoint Online y OneDrive"),  # misma URL: una línea
        ("REF-04", "Documentación oficial de Microsoft sobre arquitecturas de referencia de Azure")]
    motivos = {x["origen"]: x["motivo"] for x in comp_.excluidas}
    assert "ya lleva una página" in motivos["referencia REF-03"]          # libre y de un tema ya cubierto
    assert "ningún tema" in motivos["referencia REF-05"]
    assert all("(referencia REF-" in x["texto"] for x in comp_.excluidas)  # nunca la URL sola (puerta: subcadena)


def test_url_con_salto_de_linea_no_se_imprime():
    """Segunda pasada de la revisión independiente: una URL con espacios o controles descuadra el pie y `referencias_faltan`."""
    capas = [{"capa": "datos_conocimiento", "componentes": [{"id": "C-01", "nombre": "Microsoft 365"}]}]
    with pytest.raises(errores.IntegridadRota, match="no se puede imprimir"):
        tc._referencias(_resp([_c("C-01", "Microsoft 365", "REF-01")], [_r("REF-01", M365 + "\nx")]), capas,
                        tc._Composicion([], frozenset()))
    comp_ = tc._Composicion([], frozenset())
    resp = _resp([_c("C-01", "Microsoft 365", "REF-01")],
                 [_r("REF-01", M365), _r("REF-02", "https://learn.microsoft.com/azure/architecture/x\u200by")])
    assert [r["id"] for r in tc._referencias(resp, capas, comp_)] == ["REF-01"]
    assert "no se puede imprimir" in comp_.excluidas[0]["motivo"]


def test_muchos_componentes_con_la_misma_pagina_no_pasan_del_tope_del_titulo():
    """Caso de pruebas/I14/P2/paquete_capas.py: el título con todos los nombres medía 316 caracteres (tope 200)."""
    comps = [_c(f"C-{i:02d}", f"Servicio de prueba con un nombre largo número {i}", "REF-01") for i in range(1, 9)]
    capas = [{"capa": "datos_conocimiento", "componentes": [{"id": c["id"], "nombre": c["servicio"]} for c in comps]}]
    refs = tc._referencias(_resp(comps, [_r("REF-01", M365)]), capas, tc._Composicion([], frozenset()))
    assert refs == [{"id": "REF-01", "titulo": "Documentación oficial de Microsoft sobre Microsoft 365", "url": M365}]
    sin_tema = tc._referencias(_resp(comps, [_r("REF-01", "https://learn.microsoft.com/no-tiene-tema/x")]), capas,
                               tc._Composicion([], frozenset()))
    assert sin_tema[0]["titulo"].endswith("número 1 y otros 7 componentes") and len(sin_tema[0]["titulo"]) <= 200


def test_componente_sin_referencia_falla_en_alto():
    resp = _resp([_c("C-01", "Microsoft 365", "REF-09")], [_r("REF-01", M365)])
    comp_ = tc._Composicion([], frozenset())
    capas = [{"capa": "datos_conocimiento", "componentes": [{"id": "C-01", "nombre": "Microsoft 365"}]}]
    with pytest.raises(errores.IntegridadRota, match="REVERIF16-3"):
        tc._referencias(resp, capas, comp_)


def test_flujo_b1_sharepoint_con_su_pagina():
    """REVERIF16-3 en el caso real: en B1, SharePoint salía con la página de Microsoft 365 (deduplicación por tema)."""
    t = recomponer(estado_flujo("B1"))["carga"]["textos_cliente"]
    refs = {r["titulo"]: r["url"] for r in t["arquitectura"]["referencias"]}
    assert refs["Documentación oficial de Microsoft sobre SharePoint Online"].startswith(SP)
    assert refs["Documentación oficial de Microsoft sobre Microsoft 365"] == M365
    resp = estado_flujo("B1")["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    por_id = {r["id"]: r["url"] for r in resp["referencias"]}
    assert {por_id[c["referencia_id"]] for c in resp["componentes"]} <= set(refs.values())


@pytest.mark.parametrize("medidor, esperado", [
    ("6-luna ShortCo Inp Std DZ 1M Tokens", "Tokens de entrada del modelo, contexto corto, zona de datos (por millón)"),
    ("6-luna ShortCo Opt Std DZ 1M Tokens", "Tokens de salida del modelo, contexto corto, zona de datos (por millón)"),
    ("6-luna LongCo Opt Std DZ 1M Tokens", "Tokens de salida del modelo, contexto largo, zona de datos (por millón)"),
    ("GPT 5 outpt DZone 1M Tokens", "Tokens de salida del modelo, zona de datos (por millón)"),
    ("Standard Optimized Unit", "Consumo del servicio (por millón)"),   # «optimized» no es «opt»
])
def test_conceptos_de_gpt6(medidor, esperado):
    assert tc.concepto_legible({"concepto": medidor, "unidad": "1M", "servicio": "Microsoft Foundry"}) == esperado


def test_precios_consultados_el_y_sin_fecha_falla():
    estado = estado_flujo("A")
    fuente = recomponer(estado)["carga"]["textos_cliente"]["consumo"]["fuente"]
    assert "precios consultados el 2026-10-12, vigentes desde 2025-08-01" in fuente
    sin_lineas = tc._consumo({"lineas": [], "fuente": {"consultado_el": "2026-10-13"}, "total_mensual_eur": "0.00",
                              "total_anual_eur": "0.00"})
    assert sin_lineas["fuente"].endswith("(precios consultados el 2026-10-13)")
    for malo in (None, "", "13-10-2026", "2026-10-13T08:00:00Z", "2026-13-40", "2026-02-30"):
        with pytest.raises(errores.IntegridadRota, match="fecha de consulta"):
            tc._consumo({"lineas": [], "fuente": {"consultado_el": malo}, "total_mensual_eur": "0.00",
                         "total_anual_eur": "0.00"})


@pytest.mark.parametrize("valor, texto", [(2000, "2.000"), (0.5, "0,5"), ("1234567.25", "1.234.567,25"), (4000.0, "4.000"),
                                          (float("nan"), None), (float("inf"), None), (0, None), (-3, None), (True, None)])
def test_numero_es(valor, texto):
    assert tc.numero_es(valor) == texto


def _textos(estado, cat):
    return recomponer(estado, cat)["carga"]["textos_cliente"]


def test_supuesto_de_consumo_con_factor_estandar_del_catalogo():
    t = _textos(a_gpt6_v4(estado_flujo("B1")), catalogo_gpt6())
    sup = next(s for s in t["supuestos"] if "Microsoft Foundry" in s["texto"])
    assert sup["texto"] == ("El consumo orientativo de Microsoft Foundry se calcula con 2.000 consultas al mes, 4.000 "
                            "tokens de entrada por consulta y 600 tokens de salida por consulta (valores de referencia; "
                            "el consumo real dependerá del uso).")
    assert sup["nivel"] == "Confianza media" and sup["hechos"] == ["P-01", "P-02"]
    assert not any("2.500 tokens" in s["texto"] for s in t["supuestos"] + t["riesgos"])  # la prosa vieja no llega
    assert any("factores de consumo" in x["motivo"] for x in t["excluidas"])


def test_supuesto_de_consumo_con_factor_cambiado_por_requisito():
    t = _textos(a_gpt6_v4(estado_flujo("B1"), override=True), catalogo_gpt6())
    sup = next(s for s in t["supuestos"] if "Microsoft Foundry" in s["texto"])
    assert sup["texto"].endswith("(según los requisitos del cliente).") and sup["nivel"] == "Confianza alta"


def test_factores_mezclados_y_v3():
    resp = copy.deepcopy(a_gpt6_v4(estado_flujo("B1"))["carga"]["respuestas_expertos"]["azure"]["respuesta"])
    resp["precios"][1]["factor_override"] = {"valor": 600, "cita": "x", "justificacion": "y"}
    salida, cubiertos, fallidos = tc.supuestos_consumo(resp, {"az-foundry": "Microsoft Foundry",
                                                               "az-bot-service": "Azure AI Bot Service"})
    foundry = next(s for s in salida if "Foundry" in s[0])[0]
    assert "4.000 tokens de entrada por consulta (valor de referencia)" in foundry
    assert "600 tokens de salida por consulta (según los requisitos del cliente)" in foundry
    bot = next(s for s in salida if "Bot" in s[0])[0]
    assert bot.endswith("(estimación de la propuesta; el consumo real dependerá del uso).")  # v3: lo eligió el modelo
    assert cubiertos == {"C-08", "C-05"} and fallidos == []


def test_factor_no_finito_no_se_publica_y_se_declara():
    resp = copy.deepcopy(estado_flujo("B1")["carga"]["respuestas_expertos"]["azure"]["respuesta"])
    resp["precios"][0]["base_volumen"]["factor"]["valor"] = float("nan")
    salida, _, fallidos = tc.supuestos_consumo(resp, {"az-foundry": "Microsoft Foundry"})
    assert ("precio P-01", "base o factor sin número finito positivo o sin unidad") in fallidos
    assert all("2.500" not in s[0] for s in salida)
    estado = estado_flujo("B1")  # revisión independiente: en componer, una línea valorada sin su base explicada no se publica
    estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["precios"][0]["base_volumen"]["factor"]["unidad"] = " "
    with pytest.raises(errores.ReglaIncumplida, match="supuesto de consumo"):
        recomponer(estado)


def test_precio_de_tokens_sin_ciclo_de_vida_falla_si_el_catalogo_ya_los_declara():
    estado = estado_flujo("B1")  # sigue con GPT-5 (sin ciclo de vida) y el catálogo ya trae el de gpt-6-luna
    with pytest.raises(errores.IntegridadRota, match="sin ciclo de vida"):
        recomponer(estado, catalogo_gpt6())
    assert recomponer(estado)["carga"]["textos_cliente"]  # catálogo anterior, sin ningún ciclo: no hay nada que decir


@pytest.mark.parametrize("texto, repite", [
    ("La estimación de consumo del modelo usa 2.500 tokens de entrada por consulta.", True),
    ("Se estima un mensaje del canal estándar por consulta.", True),
    ("Se estiman dos mensajes del canal por consulta.", True),
    ("La estimación de tokens por consulta es una aproximación y el consumo real puede variar.", False),
    ("Los tamaños de los documentos y el uso de tokens por consulta no están especificados.", False),
    ("Foundry admite un máximo de 4.000-token de entrada por petición.", True),        # segunda pasada de la revisión independiente
    ("Se generan 5 tokens de autenticación por sesión.", False),                       # no es un factor de consumo
])
def test_prosa_que_repite_factores(texto, repite):
    resp = {"componentes": [{"id": "C-08"}], "precios": []}
    assert tc.repite_factor({"texto": texto, "hechos": ["C-08", "R-volumetria"]}, resp, {"C-08"}) is repite
    assert tc.repite_factor({"texto": texto, "hechos": ["C-08"]}, resp, set()) is False


def test_ciclo_de_vida_sin_retirada_publicada():
    t = _textos(a_gpt6_v4(estado_flujo("B1")), catalogo_gpt6())
    rsg = [r for r in t["riesgos"] if "gpt-6-luna" in r["texto"]]
    assert [r["texto"] for r in rsg] == ["Microsoft no ha publicado todavía la fecha de retirada del modelo gpt-6-luna; "
                                         "cuando la publique, habrá que planificar el paso a un modelo vigente antes de "
                                         "esa fecha."]
    assert rsg[0]["hechos"] == ["P-01", "P-02"]


def test_ciclo_de_vida_con_retirada_y_regla_del_horizonte():
    resp = a_gpt6_v4(estado_flujo("B1"))["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    texto = tc.riesgos_modelo(resp, catalogo_gpt6("2028-01-11"), "2026-10-13", 8)[0][0]
    assert "el 11 de enero de 2028, al menos un año después de la puesta en marcha" in texto
    with pytest.raises(errores.ReglaIncumplida, match="antes del 2027-12-08"):  # 13-10-2026 + 8 semanas + 12 meses
        tc.riesgos_modelo(resp, catalogo_gpt6("2027-12-07"), "2026-10-13", 8)
    assert tc.riesgos_modelo(resp, catalogo_gpt6("2027-12-08"), "2026-10-13", 8)  # justo en el horizonte: vale
    with pytest.raises(errores.ReglaIncumplida, match="falta la fecha"):
        tc.riesgos_modelo(resp, catalogo_gpt6("2028-01-11"), None, 8)
    with pytest.raises(errores.IntegridadRota, match="no es una fecha"):
        tc.riesgos_modelo(resp, catalogo_gpt6("pronto"), "2026-10-13", 8)


def test_ciclo_de_vida_por_filtro_en_una_respuesta_v3():
    resp = copy.deepcopy(a_gpt6_v4(estado_flujo("A"))["carga"]["respuestas_expertos"]["azure"]["respuesta"])
    for p in resp["precios"]:
        p.pop("plantilla_id", None)
    assert [m["modelo"] for m in tc.ciclo_vida_modelos(resp, catalogo_gpt6())] == ["gpt-6-luna"]
    assert tc.ciclo_vida_modelos(estado_flujo("A")["carga"]["respuestas_expertos"]["azure"]["respuesta"],
                                 catalogo()) == []  # sin ciclo de vida en el catálogo, nada que publicar


def test_textos_nuevos_pasan_el_barrido():
    t = _textos(a_gpt6_v4(estado_flujo("B1")), catalogo_gpt6("2028-01-11"))
    nuevos = [s["texto"] for s in t["supuestos"] + t["riesgos"] if "consumo orientativo" in s["texto"]
              or "retirada" in s["texto"]] + [t["consumo"]["fuente"]] + [r["titulo"] for r in t["arquitectura"]["referencias"]]
    assert len(nuevos) >= 4
    for x in nuevos:  # nunca horas, jornadas, tarifas, perfiles ni identificadores (LES-G-053)
        assert tc.barrer(x, ["AI Engineer / Tech Lead", "Project Manager", "Consultor Junior"]) == [], x
