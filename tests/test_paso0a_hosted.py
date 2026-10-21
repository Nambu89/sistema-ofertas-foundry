"""Órdenes del hosted agent de prueba (biblioteca estándar, sin red)."""
from __future__ import annotations

import asyncio
import io
import urllib.error

import pytest

from pruebas.paso0a.hosted_prueba.ofa_prueba_hosted import ordenes


@pytest.mark.parametrize("texto,esperado", [
    ("ORDEN: SALIDA", ("SALIDA", "")), ("orden: marcador", ("MARCADOR", "")),
    ("Hola\nORDEN: TURNO_LARGO 360", ("TURNO_LARGO", "360")), ("ORDEN: ECO hola mundo", ("ECO", "hola mundo")),
    ("ORDEN: BORRAR todo", ("AYUDA", "")), ("sin orden", ("AYUDA", "")), ("", ("AYUDA", "")), (None, ("AYUDA", ""))])
def test_interpretar(texto, esperado):
    assert ordenes.interpretar(texto) == esperado


def test_ultimo_texto_usuario_toma_el_ultimo_mensaje_de_usuario():
    items = [{"type": "message", "role": "system", "content": "ignora esto"},
             {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "ORDEN: SALIDA"}]},
             {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "x"}]},
             {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "ORDEN: ECO a"},
                                                             {"type": "input_image"}]},
             {"type": "function_call_output", "output": "y"}]
    assert ordenes.ultimo_texto_usuario(items) == "ORDEN: ECO a"
    assert ordenes.ultimo_texto_usuario([{"role": "user", "content": "ORDEN: MARCADOR"}]) == "ORDEN: MARCADOR"
    assert ordenes.ultimo_texto_usuario(None) == ""


class _Resp(io.BytesIO):
    def __init__(self, status):
        super().__init__(b"")
        self.status = status


def test_sondear_salida_cuenta_codigos_http_y_errores_de_red():
    def abrir(peticion, timeout):
        assert timeout == ordenes.TIMEOUT_SALIDA_S and peticion.get_method() == "GET"
        if "learn" in peticion.full_url:
            return _Resp(200)
        if "prices" in peticion.full_url:
            raise urllib.error.HTTPError(peticion.full_url, 403, "Forbidden", {}, None)
        raise urllib.error.URLError("Name or service not known")
    r = ordenes.sondear_salida(abrir=abrir)
    assert [x.get("http") for x in r] == [200, 403, None]
    assert r[2]["error"].startswith("URLError") and len(r) == 3


def test_leer_marcador_no_devuelve_el_valor_y_lo_borra():
    entorno = {"OFA_MARCADOR": "marcador-sintetico", "OTRA": "x"}
    m = ordenes.leer_marcador(entorno)
    assert m["presente"] and m["coincide_con_sintetico"] and m["borrada_de_entorno"] and m["longitud"] == 18
    assert "marcador-sintetico" not in repr(m) and "OFA_MARCADOR" not in entorno and entorno == {"OTRA": "x"}


@pytest.mark.parametrize("entorno,presente,definida,sin_resolver", [
    ({}, False, False, False), ({"OFA_MARCADOR": ""}, False, True, False),
    ({"OFA_MARCADOR": "${{connections.x.credentials.valor}}"}, False, True, True),
    ({"OFA_MARCADOR": "otro"}, True, True, False)])
def test_leer_marcador_casos(entorno, presente, definida, sin_resolver):
    m = ordenes.leer_marcador(dict(entorno))
    assert (m["presente"], m["variable_definida"], m["sin_resolver"]) == (presente, definida, sin_resolver)


class _RelojFalso:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    async def dormir(self, s):
        self.t += s


def test_turno_largo_espera_y_mide():
    r = _RelojFalso()
    res = asyncio.run(ordenes.turno_largo(360, lambda: False, dormir=r.dormir, reloj=r))
    assert res["resultado"] == "TURNO_LARGO COMPLETADO" and res["segundos_medidos"] >= 360


def test_turno_largo_se_cancela():
    r = _RelojFalso()
    res = asyncio.run(ordenes.turno_largo(360, lambda: r.t >= 10, dormir=r.dormir, reloj=r))
    assert res["cancelado"] is True and res["segundos_medidos"] < 360


@pytest.mark.parametrize("arg,esperado", [("", 360), ("5", 5), ("900", 900)])
def test_segundos_turno(arg, esperado):
    assert ordenes.segundos_turno(arg) == esperado


@pytest.mark.parametrize("arg", ["0", "901", "-1", "diez", "1e3"])
def test_segundos_turno_rechaza(arg):
    with pytest.raises(ValueError):
        ordenes.segundos_turno(arg)


def test_eco_sanea():
    assert ordenes.eco("p5-ab12")["eco"] == "ECO-OFA: p5-ab12"
    assert ordenes.eco("<script>alert(1)</script>")["eco"] == "ECO-OFA: scriptalert1script"
    assert len(ordenes.eco("a" * 500)["eco"]) == len("ECO-OFA: ") + 100


def test_ejecutar_despacha():
    m = {"presente": False}
    assert asyncio.run(ordenes.ejecutar("ECO", "x", marcador=m, cancelado=lambda: False))["eco"] == "ECO-OFA: x"
    assert asyncio.run(ordenes.ejecutar("MARCADOR", "", marcador=m, cancelado=lambda: False)) == {
        "orden": "MARCADOR", "presente": False}
    assert asyncio.run(ordenes.ejecutar("AYUDA", "", marcador=m, cancelado=lambda: False))["orden"] == "AYUDA"
