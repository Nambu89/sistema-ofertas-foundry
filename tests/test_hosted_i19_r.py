"""I1.9 · papel R · VPROT-3 y PR18-7 en el orquestador B. Casos adversos con su resultado esperado.

VPROT-3: -32001 TASK_NOT_FOUND también significa «no accesible para esta identidad». La tarea solo se da por perdida (y
SIGUE la reenvía) si la identidad del sondeo es la misma que la creó; si no consta, no se lee o es otra, queda pendiente
y no se reenvía (se pagaría dos veces una tarea viva).
PR18-7: con DISCREPA efectivos, el texto del turno lleva el motivo de cada uno (antes había que descargar el estado).
"""
from __future__ import annotations

import pathlib
import sys
import types

import pytest

from tests.test_hosted_falsos import OID_OTRA, OID_PRUEBA, httpx, token_prueba
from tests.test_hosted_i17_arr_a2a import PROYECTO, Reloj, _servidor
from preventa_hosted import a2a as A
from preventa_hosted import fases

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "sandbox"))
NO_EXISTE = {"code": -32001, "message": "The specified task ID does not exist or is not accessible",
             "data": [{"reason": "TASK_NOT_FOUND"}]}


def _no_existe() -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": "x", "error": NO_EXISTE})


class _Token:
    """Token que se puede cambiar entre el envío y el sondeo (identidad distinta)."""
    def __init__(self, valor: str):
        self.valor = valor

    def __call__(self) -> str:
        return self.valor


def _cliente(manejador, token):
    reloj = Reloj()
    return A.ClienteA2A(lambda a: f"{PROYECTO}/agents/{a}/endpoint/protocols/a2a", token, 30,
                        httpx.MockTransport(manejador), espera_s=420.0, sondeo_s=5.0, dormir=reloj.dormir, reloj=reloj)


# ── identidad del token ──
@pytest.mark.parametrize("token, esperada", [
    (token_prueba(), OID_PRUEBA),
    ("sin-puntos", None),
    ("a.%%%.b", None),                 # carga que no es base64
    ("a.e30.b", None),                 # {} sin oid ni sub
])
def test_identidad_de_token(token, esperada):
    assert A.identidad_de_token(token) == esperada


def test_identidad_sub_si_no_hay_oid():
    import base64
    import json
    carga = base64.urlsafe_b64encode(json.dumps({"sub": "sujeto-1"}).encode()).decode().rstrip("=")
    assert A.identidad_de_token(f"x.{carga}.y") == "sujeto-1"


# ── VPROT-3: -32001 contrastado con la identidad ──
def test_control_misma_identidad_da_la_tarea_por_perdida():
    man, _ = _servidor([_no_existe(), _no_existe()])
    ll = _cliente(man, _Token(token_prueba())).enviar("x", "hola")
    assert ll.perdida and not ll.pendiente and ll.identidad == ll.identidad_sondeo == OID_PRUEBA
    assert "misma identidad" in ll.error and ll.registro()["identidad"] == OID_PRUEBA


def test_identidad_distinta_no_da_por_perdida_ni_reenvia():
    tok = _Token(token_prueba())
    estados = [_no_existe(), _no_existe()]
    man, vistos = _servidor(estados)

    def cambia(req):                       # tras el SendMessage, el token pasa a ser de otra identidad
        r = man(req)
        tok.valor = token_prueba(OID_OTRA)
        return r
    ll = _cliente(cambia, tok).enviar("x", "hola")
    assert not ll.perdida and ll.pendiente and ll.codigo_jsonrpc == -32001
    assert (ll.identidad, ll.identidad_sondeo) == (OID_PRUEBA, OID_OTRA)
    assert "NO ACCESIBLE" in ll.error and "VPROT-3" in ll.error and "se pagaría dos veces" in ll.error
    assert [v["method"] for v in vistos].count("SendMessage") == 1


def test_token_ilegible_no_da_por_perdida():
    man, _ = _servidor([_no_existe(), _no_existe()])
    ll = _cliente(man, _Token("token-opaco")).enviar("x", "hola")
    assert not ll.perdida and ll.pendiente and "no consta" in ll.error and "no se puede leer" in ll.error


@pytest.mark.parametrize("previa, perdida", [
    ({"identidad": OID_PRUEBA}, True),     # control: la que la creó
    ({}, False),                           # registro anterior a I1.9: no consta
    ({"identidad": OID_OTRA}, False),      # otra identidad
    ({"identidad": 7}, False),             # forma no válida
])
def test_recuperar_contrasta_con_la_identidad_del_registro(previa, perdida):
    man, _ = _servidor([_no_existe(), _no_existe()])
    ll = _cliente(man, _Token(token_prueba())).recuperar("x", "resp_1", {"sha256_enviado": "0" * 64, **previa})
    assert ll.perdida is perdida and ll.pendiente is (not perdida)


def test_pendiente_por_identidad_se_vuelve_a_recoger_y_no_se_reenvia(tmp_path):
    """Lo que escribe a2a.jsonl con identidad distinta: pendiente_previa la devuelve (se recoge), perdida_previa no."""
    ll = A.Llamada(agente="preventa-experto-azure", url="u", metodo="SendMessage", inicio="2026-10-15T10:00:00+00:00",
                   jsonrpc_id="1", sha256_enviado="a" * 64, task_id="resp_1", pendiente=True, perdida=False,
                   identidad=OID_PRUEBA, identidad_sondeo=OID_OTRA, error="NO ACCESIBLE")
    fases.procedencia(tmp_path, ll, "T2")
    assert fases.pendiente_previa(tmp_path, "preventa-experto-azure", "T2", "a" * 64)["identidad"] == OID_PRUEBA
    assert fases.perdida_previa(tmp_path, "preventa-experto-azure", "T2") is None


# ── PR18-7: el motivo de cada DISCREPA en el texto del turno ──
def _estado_con_discrepa(discrepa):
    return {"carga": {"verificacion": {"resultado": {"verificada": not discrepa, "discrepa": discrepa}}}}


def _p(estado):
    return types.SimpleNamespace(estado=lambda env, como_json=True: types.SimpleNamespace(estado=estado))


def test_motivo_de_cada_discrepa_sale_en_el_turno():
    d = {"id": "C-08", "campo": "region", "valor_correcto": "Basic v2", "detalle": "Sweden Central no está disponible",
         "fuente_url": "https://learn.microsoft.com/azure/api-management/x", "motivo": "DISCREPA con fuente: vuelve"}
    reg = fases.Registro()
    fases.motivos_discrepa(_p(_estado_con_discrepa([d])), None, reg)
    texto = "\n".join(reg.lineas)
    for parte in ("C-08", "campo «region»", "«Basic v2»", "Sweden Central no está disponible",
                  "https://learn.microsoft.com/azure/api-management/x", "DISCREPA con fuente"):
        assert parte in texto, texto


def test_sin_discrepa_no_anade_nada():
    reg = fases.Registro()
    fases.motivos_discrepa(_p(_estado_con_discrepa([])), None, reg)
    assert reg.lineas == []


def test_estado_ilegible_se_dice():
    def roto(env, como_json=True):
        raise RuntimeError("estado roto")
    reg = fases.Registro()
    fases.motivos_discrepa(types.SimpleNamespace(estado=roto), None, reg)
    assert len(reg.lineas) == 1 and "No puedo leer el motivo" in reg.lineas[0] and "estado roto" in reg.lineas[0]


def test_detalle_muy_largo_se_recorta_sin_perder_el_id():
    d = {"id": "P-03", "campo": "precio", "valor_correcto": "1" * 500, "detalle": "x" * 5000, "fuente_url": None,
         "motivo": "m"}
    import nucleo.verificacion as V
    lineas = V.lineas_discrepa_turno(_estado_con_discrepa([d, "no es un dict"]))
    assert len(lineas) == 1 and lineas[0].startswith("- DISCREPA P-03") and "sin fuente" in lineas[0]
    assert len(lineas[0]) < 1200 and "…" in lineas[0]


# ── Revisión 1 (media-alta): la identidad es la del token con que va cada petición, no otra lectura del proveedor ──
class _TokenPorLlamada:
    """Devuelve, por orden, un token de cada identidad de la lista (la última se repite)."""
    def __init__(self, *oids: str):
        self.oids, self.n = list(oids), 0

    def __call__(self) -> str:
        oid = self.oids[min(self.n, len(self.oids) - 1)]
        self.n += 1
        return token_prueba(oid)


def test_la_identidad_de_creacion_es_la_del_token_del_send_message():
    man, _ = _servidor([_no_existe(), _no_existe()])
    tok = _TokenPorLlamada(OID_PRUEBA, OID_PRUEBA, OID_PRUEBA)
    ll = _cliente(man, tok).enviar("x", "hola")
    assert tok.n == 3 and ll.identidad == OID_PRUEBA and ll.perdida      # una lectura del token por petición


def test_el_contraste_usa_el_token_del_get_task_que_dio_el_segundo_32001():
    man, _ = _servidor([_no_existe(), _no_existe()])
    ll = _cliente(man, _TokenPorLlamada(OID_PRUEBA, OID_PRUEBA, OID_OTRA)).enviar("x", "hola")
    assert (ll.identidad, ll.identidad_sondeo) == (OID_PRUEBA, OID_OTRA) and ll.pendiente and not ll.perdida
