"""I1.9 · papel P: la extracción deja una entrada por recurso con su cita entera (PR18-1), en suficiencia, el brief, el
anexo y la nota del revisor. Cada caso de suficiencia exige además la igualdad con la réplica de la puerta."""
from __future__ import annotations

import copy

import pytest

from tests import i19_p_datos as D
from nucleo import anexo_consumo, experto, suficiencia
from nucleo.errores import ReglaIncumplida

CAT = D.catalogo_i19()
H1 = "hostelia_1/lista_A"


def estado_y_textos():
    est = copy.deepcopy(D.estado_hostelia(H1))
    est["estado"] = "BORRADOR"
    return est, {"F1": D.TRANSCRIPCION}


def reglas(entradas, catalogo=CAT):
    nucleo = suficiencia.reglas_existentes(entradas, catalogo)
    assert nucleo == D.R19.existentes_requisitos_r(entradas, catalogo)
    return nucleo


def test_control_una_entrada_por_recurso_con_la_cita_entera_se_acepta():
    est, textos = estado_y_textos()
    req = D.requisitos_hostelia(H1)
    res = suficiencia.aplicar(est, req, textos, CAT)
    assert res.citas_invalidas == [] and reglas(D.entradas_existentes()) == []
    guardado = est["carga"]["requisitos"]["campos"]["ya_contratado_por_cliente"]
    assert guardado["estado"] == "CITADO" and [e["id"] for e in guardado["entradas"]] == [
        "EX-01", "EX-02", "EX-03", "EX-04", "EX-05", "EX-06"]


def test_caso_real_h1_el_resumen_que_pierde_el_app_service_y_el_api_management_se_rechaza():
    """La sesión 1 resumió la cita en «API REST de RR. HH. que ya tienen en Azure.»: falla cerrado con lo que falta."""
    resumen = [{"id": "EX-01", "servicio_catalogo": None, "valor": "API REST de RR. HH. que ya tienen en Azure.",
                "cita": D.CITA_API, "fuente": "F1", "origen": "CITADO"}]
    assert reglas(resumen) == [("EX-01", "existente_valor_no_literal"), ("EX-01", "existente_recurso_sin_entrada"),
                               ("EX-01", "existente_recurso_sin_entrada")]
    est, textos = estado_y_textos()
    with pytest.raises(ReglaIncumplida) as e:
        suficiencia.aplicar(est, D.requisitos_hostelia(H1, resumen), textos, CAT)
    assert any("la cita nombra Azure App Service" in x for x in e.value.errores)
    assert any("la cita nombra Azure API Management" in x for x in e.value.errores)


def test_la_forma_de_i18_sin_id_ni_servicio_no_valida_el_esquema():
    est, textos = estado_y_textos()
    req = D.requisitos_hostelia(H1, [{"valor": "Licencias de Microsoft 365 E3", "cita": D.CITA_LICENCIAS,
                                      "fuente": "F1", "origen": "CITADO"}])
    with pytest.raises(ReglaIncumplida, match="esquema"):
        suficiencia.aplicar(est, req, textos, CAT)


@pytest.mark.parametrize("cambio, esperado", [
    (lambda es: es[1].update(id="EX-01"), ("EX-01", "existente_id_repetido")),
    (lambda es: es[4].update(valor="Su App Service propio"), ("EX-05", "existente_valor_no_literal")),
    (lambda es: es[4].update(servicio_catalogo="az-no-existe"), ("EX-05", "existente_servicio_desconocido")),
    (lambda es: es[4].update(valor="App Service propio, publicada con API Management"),
     ("EX-05", "existente_valor_otro_servicio")),
    (lambda es: es[3].update(valor="App Service"), ("EX-04", "existente_valor_otro_servicio")),
    (lambda es: es.pop(5), ("EX-04", "existente_recurso_sin_entrada")),
])
def test_cada_regla_de_la_entrada_por_recurso(cambio, esperado):
    entradas = D.entradas_existentes()
    cambio(entradas)
    assert esperado in reglas(entradas)


def test_sin_catalogo_falla_cerrado_y_asumido_no_vale():
    assert reglas(D.entradas_existentes(), None) == [("—", "existente_sin_catalogo")]
    est, textos = estado_y_textos()
    with pytest.raises(ReglaIncumplida):
        suficiencia.aplicar(est, D.requisitos_hostelia(H1), textos)  # sin catálogo
    asumido = D.entradas_existentes()
    asumido[0].update(origen="ASUMIDO")
    with pytest.raises(ReglaIncumplida, match="esquema"):
        suficiencia.aplicar(est, D.requisitos_hostelia(H1, asumido), textos, CAT)


def test_el_brief_lleva_la_cita_entera_y_no_el_resumen():
    req = D.requisitos_hostelia(H1)
    lineas = experto.lineas_brief_existentes(req, anon=lambda t: t.replace("RR. HH.", "RR. HH."))
    assert lineas[5] == ("- EX-06 (az-api-management): «API Management». Cita: «El saldo de vacaciones y las solicitudes "
                         "de días libres van a través de la API REST de RR. HH. que ya tenemos en Azure, en un App Service "
                         "propio, publicada con API Management.»")
    assert lineas[3].startswith("- EX-04 (fuera del catálogo): «la API REST de RR. HH.». Cita: «El saldo")
    assert lineas == D.R19.lineas_brief_existentes_r(req, anon=lambda t: t.replace("RR. HH.", "RR. HH."))


def test_anexo_y_nota_dicen_que_el_recurso_es_del_cliente():
    from tests.test_i19_p_existentes import caso_h1
    r, br, req = caso_h1()
    _, c = D.analizar(r, br, req, CAT)
    clas = {x["componente_id"]: x for x in anexo_consumo.clasificar_componentes(c, CAT)}
    assert clas["C-06"]["motivo"] == anexo_consumo.MOTIVO_EXISTENTE and clas["C-06"]["facturable"] is False
    assert clas["C-06"]["motivo_no_valoracion"] == "existente_del_cliente"
    lineas = experto.lineas_para_revisor(c, CAT, requisitos=req)
    assert ("Recurso que el cliente ya tiene: EX-06 (Azure API Management, «API Management») se reutiliza como C-06 y no "
            "se valora (su nivel y su región son del cliente). Cita: «" + D.CITA_API + "». Comprobar en la transcripción "
            "que el cliente lo tiene") in lineas
    assert any(x.startswith("Recurso que el cliente ya tiene y la propuesta no usa: EX-04") for x in lineas)
    assert any(x.startswith("Servicio nuevo aunque el cliente ya tiene uno: Azure App Service (C-03) se valora y EX-05")
               for x in lineas)
