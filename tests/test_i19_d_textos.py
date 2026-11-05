"""I1.9 · D · Lo que ve el cliente en textos_cliente: presupuesto del alta (VA18-1), confianza y frases fijas (VA18-5),
sistemas que ya tiene el cliente (contrato común, PR18-8), convención de identidad (VA18-6) y lenguaje llano (VA18-12).
Sobre los estados reales de I1.8. Sin red."""
from __future__ import annotations

import copy
from decimal import Decimal

import pytest

from tests.i19_d_datos import catalogo, contrato_i19_hostelia, estado_real, tarifa
from nucleo import errores, textos_cliente as tc  # noqa: E402


def componer(estado):
    return tc.componer(estado, catalogo(), tarifa())


def todo(textos) -> str:
    return " ".join(t for _, t in tc._todas(textos))


def test_va18_1_el_presupuesto_asumido_no_llega_al_cliente():
    textos = componer(estado_real("hostelia_lista_A"))
    assert "presupuesto" not in tc._plano(todo(textos))
    assert "25.000" not in todo(textos) and "60.000" not in todo(textos)
    assert not any("R-presupuesto_orientativo" in f["hechos"] for f in textos["supuestos"])
    assert tc.presupuesto_en_textos(textos, estado_real("hostelia_lista_A")["carga"]["requisitos"]["campos"],
                                    estado_real("hostelia_lista_A")["carga"]["estimacion"]["resumen"]) == []


def test_va18_1_citado_y_en_la_prosa_del_experto_tampoco():
    estado = estado_real("hostelia_lista_A")
    campos = estado["carga"]["requisitos"]["campos"]
    campos["presupuesto_orientativo"] = {"estado": "CITADO", "entradas": [
        {"valor": "Unos 40.000 euros", "cita": "Tenemos unos 40.000 euros para esto.", "fuente": "F1", "origen": "CITADO"}]}
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    resp["supuestos"].append({"id": "S-07", "texto": "El proyecto encaja en el presupuesto del cliente.",
                              "hechos": ["R-presupuesto_orientativo"], "confianza": "ALTA"})
    resp["riesgos"].append({"id": "RG-04", "texto": "El API Management cuesta 173,45 € al mes.", "hechos": ["C-06"]})
    textos = componer(estado)
    motivos = {x["origen"]: x["motivo"] for x in textos["excluidas"]}
    assert "VA18-1" in motivos["experto S-07"]
    assert "LES-G-097.1" in motivos["experto RG-04"]
    assert "40.000" not in todo(textos) and "173,45" not in todo(textos)


def test_va18_1_la_red_final_ve_lo_que_se_colase():
    estado = estado_real("hostelia_lista_A")
    campos, resumen = estado["carga"]["requisitos"]["campos"], estado["carga"]["estimacion"]["resumen"]
    textos = copy.deepcopy(estado["carga"]["textos_cliente"])  # el publicado en I1.8 lo llevaba
    halla = tc.presupuesto_en_textos(textos, campos, resumen)
    assert any("cita el presupuesto" in h for h in halla) and any("25.000" in h for h in halla)


def test_importes_monetarios_y_lectura_espanola():
    assert tc.importes_monetarios("entre 25.000 y 60.000 euros; 173,45 € al mes; EUR 12") == [
        ("60.000", Decimal("60000")), ("173,45", Decimal("173.45")), ("12", Decimal("12"))]
    assert tc.lectura_es("22,548.75") is None and tc.lectura_es("2000") == Decimal("2000")


def test_va18_5_ningun_supuesto_con_mas_confianza_que_en_la_nota_y_frase_fija():
    textos = componer(estado_real("brezalia_final"))
    por_hecho = {f["hechos"][0]: f for f in textos["supuestos"]}
    assert por_hecho["S-01"]["nivel"] == "Confianza baja"  # S-06 (BAJA) cita los mismos componentes y uno más
    assert por_hecho["S-02"]["nivel"] == "Confianza alta"  # cita un requisito que S-06 no cita
    assert por_hecho["S-06"]["texto"].startswith("Supuesto sin confirmar sobre Microsoft Teams")
    assert por_hecho["S-06"]["nivel"] == "Confianza baja" and "NO VERIFICADO" not in todo(textos)


def test_nivel_con_tope_sin_hechos_nombrables_conserva_el_suyo():
    resp = {"supuestos": [{"id": "S-01", "confianza": "ALTA", "hechos": ["REF-01"]},
                          {"id": "S-02", "confianza": "BAJA", "hechos": ["C-01"]}], "precios": []}
    assert tc.nivel_con_tope(resp["supuestos"][0], resp, {}) == "Confianza alta"
    resp["supuestos"][0]["hechos"] = ["C-01"]
    assert tc.nivel_con_tope(resp["supuestos"][0], resp, {}) == "Confianza baja"


def test_sistemas_del_cliente_nombrados_y_en_el_alcance():
    textos = componer(contrato_i19_hostelia(estado_real("hostelia_lista_A")))
    nombres = {k["id"]: k["nombre"] for c in textos["arquitectura"]["capas"] for k in c["componentes"]}
    assert nombres["C-06"] == "Azure API Management (sistema del cliente)"
    assert nombres["C-09"] == "API REST de RR. HH. (sistema del cliente)"
    assert nombres["C-03"] == "Azure App Service"
    alcance = [f["texto"] for f in textos["alcance"]]
    # VA19-1 (I1.10): los recursos que comparten cita van en una sola frase (antes, una por recurso), y los servicios de
    # licencia como uso; dentro de la frase, con el artículo del valor citado («la API REST de RR. HH.»)
    assert "Integración con Azure API Management y la API REST de RR. HH., que ya tiene el cliente." in alcance
    assert "Uso de Microsoft Teams y SharePoint Online, que ya tiene el cliente." in alcance
    assert not any(t.startswith("Integración con Microsoft Teams") for t in alcance)
    assert not any(t.startswith("Canal o integración: API") for t in alcance)
    assert any(f["texto"].startswith("Licencias y consumo de los sistemas que ya tiene el cliente")
               and f["texto"].endswith(" y la API REST de RR. HH.") for f in textos["fuera_de_alcance"])
    assert not any("API Management" in f["texto"] for f in textos["riesgos"])


def test_nombre_base_existente_es_el_oficial_o_un_trozo_del_valor():
    oficiales = {"az-app-service": "Azure App Service"}
    comp = {"id": "C-09", "catalogo_id": "az-app-service"}
    assert tc.nombre_base_existente(comp, {"valor": "la API REST de RR. HH."}, oficiales) == "API REST de RR. HH."
    assert tc.nombre_base_existente(comp, {"valor": "App Service"}, oficiales) == "Azure App Service"
    largo = "una aplicación interna muy larga que no cabe en una caja del diagrama"
    assert tc.nombre_base_existente(comp, {"valor": largo}, oficiales) == "Azure App Service"
    assert tc.nombre_base_existente(comp, {"valor": "mi_api_rrhh"}, oficiales) == "Azure App Service"
    # cierre D: fuera del catálogo manda el valor citado, aunque el servicio del modelo lo contenga (LES-G-093)
    fuera = {"id": "C-09", "catalogo_id": None, "servicio": "API REST de RR. HH. del cliente"}
    assert tc.nombre_base_existente(fuera, {"valor": "la API REST de RR. HH."}, oficiales) == "API REST de RR. HH."
    assert tc.nombre_base_existente(fuera, {"valor": "mi_api_rrhh"}, oficiales) == "API REST de RR. HH. del cliente"


def test_nombre_en_frase_recupera_solo_el_articulo_del_valor():
    assert tc.nombre_en_frase({"valor": "la plataforma de nóminas."}, "Plataforma de nóminas") == "la plataforma de nóminas"
    assert tc.nombre_en_frase({"valor": "API Management"}, "Azure API Management") == "Azure API Management"
    assert tc.nombre_en_frase({"valor": "nuestra API de RR. HH."}, "API de RR. HH.") == "API de RR. HH."
    assert tc.nombre_en_frase({"valor": "la API Management"}, "Azure API Management") == "Azure API Management"


def test_existente_que_cita_una_entrada_inexistente_falla_en_alto():
    with pytest.raises(errores.IntegridadRota):
        tc.entrada_de({"id": "C-01", "existente_del_cliente": {"entrada": "EX-09"}}, {})


def test_va18_6_convencion_de_identidad_y_sin_duplicados():
    resp = {"componentes": [{"id": "C-01", "capa": "aplicacion_integracion"}, {"id": "C-02", "capa": "identidad_seguridad_red"}],
            "flujos": [{"origen": "C-02", "destino": "C-01"}, {"origen": "C-01", "destino": "C-02"}]}
    assert tc.flujos_cliente(resp) == [{"origen": "C-01", "destino": "C-02"}]


def test_va18_12_lenguaje_llano():
    assert tc.llano_cliente("la geografía del tenant") == "la geografía del inquilino (tenant)"
    assert tc.llano_cliente("se dimensiona con el factor de catálogo de 0,002 GB") == "se dimensiona con 0,002 GB"
    assert tc.llano_cliente("unas 2000 consultas al mes en 2026") == "unas 2.000 consultas al mes en 2026"
    assert tc.redaccion_interna("según el valor del catálogo")
    assert tc.minuscula_inicial("Implementar un asistente") == "implementar un asistente"
    assert tc.minuscula_inicial("Power BI") == "Power BI"
    assert tc.mismo_producto("Azure Bot Service", "Azure AI Bot Service")
    assert not tc.mismo_producto("Foundry Models", "Microsoft Foundry")
    assert tc.region_legible("swedencentral") == "Centro de Suecia" and tc.region_legible("marte1") == "marte1"
    assert tc.frase_asumido("red_privada", "No, acceso público") == ("Dato por confirmar con el cliente sobre la red "
                                                                   "privada: no, acceso público.")


def test_revision_presupuesto_con_espacio_de_millar_y_con_otras_palabras():
    """Revisión (I1.9, pasada 1): «25 000» es una sola cifra, y «presupuesto disponible» con una cifra también cuenta."""
    estado = estado_real("hostelia_lista_A")
    campos, resumen = estado["carga"]["requisitos"]["campos"], estado["carga"]["estimacion"]["resumen"]
    campos["presupuesto_orientativo"]["entradas"][0]["valor"] = "Presupuesto disponible: 25 000"
    textos = copy.deepcopy(componer(estado))
    assert tc.presupuesto_en_textos(textos, campos, resumen) == []
    textos["riesgos"][0]["texto"] = "El cliente cuenta con 25 000 para el proyecto."
    assert any("25.000" in h for h in tc.presupuesto_en_textos(textos, campos, resumen))
    textos["riesgos"][0]["texto"] = "El presupuesto disponible es de 30 mil."
    assert any("con cifra" in h for h in tc.presupuesto_en_textos(textos, campos, resumen))
    assert tc.cifras_de("unos 25 000 y 1.500,5") == {Decimal("25000.00"), Decimal("1500.50")}


@pytest.mark.parametrize("texto, esperado", [
    ("El presupuesto disponible es de 30 mil.", True), ("Presupuesto disponible: 25 000.", True),
    ("Tenemos 40.000 euros de presupuesto.", True), ("El presupuesto está previsto para 3 regiones.", False),
    ("El presupuesto se revisará en 2027.", False), ("Asistente de presupuestos de obra.", False),
    ("Presupuesto cerrado. Atiende 5.000 consultas.", False), ("Un presupuesto de 2027 millones.", True)])
def test_revision_presupuesto_con_cifra_sin_falsos_rojos(texto, esperado):
    """Revisión (I1.9, pasada 2): una cifra pequeña o un año cerca de «presupuesto» no lo convierten en un presupuesto."""
    assert tc.presupuesto_con_cifra(texto) is esperado


@pytest.mark.parametrize("cifra, esperado", [
    ("120,000", Decimal("120000")), ("120000.50", Decimal("120000.50")), ("120,000.50", Decimal("120000.50")),
    ("120.000", Decimal("120000")), ("25 000", Decimal("25000")), ("1.500,5", Decimal("1500.5")), ("abc", None)])
def test_cierre_lectura_amplia_solo_lee_en_ingles_lo_que_no_tiene_lectura_espanola(cifra, esperado):
    """Cierre D (16-10, Revisión 6): «120.000» sigue siendo 120.000 (lectura española), no 120."""
    assert tc.lectura_amplia(cifra) == esperado


def test_cierre_presupuesto_del_alta_en_formato_ingles_tambien_se_detecta():
    """Cierre D (16-10, Revisión 6): «120,000» o «120000.50» en el alta o en el texto ya no escapan a la detección."""
    assert tc.presupuesto_con_cifra("Se ha presupuestado 120000.50 para el proyecto.") is True
    assert tc.presupuesto_con_cifra("El presupuesto es de 120,000.") is True
    estado = estado_real("hostelia_lista_A")
    campos, resumen = estado["carga"]["requisitos"]["campos"], estado["carga"]["estimacion"]["resumen"]
    campos["presupuesto_orientativo"]["entradas"][0]["valor"] = "Up to 120,000 USD"
    textos = copy.deepcopy(componer(estado))
    assert tc.presupuesto_en_textos(textos, campos, resumen) == []
    textos["riesgos"][0]["texto"] = "El cliente cuenta con 120,000 para el proyecto."
    # el hallazgo da la cifra en formato español («120.000»): lo lee una persona
    assert any("la cifra 120.000 del presupuesto" in h for h in tc.presupuesto_en_textos(textos, campos, resumen))
