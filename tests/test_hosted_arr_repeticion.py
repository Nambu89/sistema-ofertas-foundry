"""Arreglos I1.6 · PR16-2 en el hosted, REVISADO en I1.7 (papel R). En I1.6 el aborto de Foundry por un error de
precios_azure (A2A -32603 «Received 400 from a service request») se repetía una vez con pausa. En I1.7 ni el experto ni
el verificador tienen la herramienta de precios (decisión 1 del comercial): la repetición desaparece y CUALQUIER fallo A2A,
también ese, se registra una sola vez con registrar-fallo, con su motivo literal y sin un segundo envío. Sin red."""

from __future__ import annotations

import json
import types

import pytest

pytest.importorskip("httpx")
from tests.test_hosted_falsos import NUCLEO  # noqa: E402,F401  (pone hosted/ y el núcleo en sys.path)
from preventa_hosted import a2a as A  # noqa: E402
from preventa_hosted import fases  # noqa: E402

ABORTO = ('JSON-RPC {"code": -32603, "message": "Internal error", "data": [{"@type": '
          '"type.googleapis.com/google.rpc.ErrorInfo", "reason": "INTERNAL_ERROR", "domain": "a2a-protocol.org", '
          '"metadata": {"detail": "Received 400 from a service request"}}]}')


def _ll(error=None, n=1):
    texto = "" if error else json.dumps({"ok": n})
    return A.Llamada(agente="preventa-experto-azure", url="https://x/a2a", metodo="SendMessage",
                     inicio="2026-10-11T09:00:00+00:00", jsonrpc_id=f"id-{n}", sha256_enviado="e" * 64, http=200,
                     latencia_s=5.0, task_id=None if error else f"t-{n}", estado_tarea=None if error else
                     "TASK_STATE_COMPLETED", sha256_recibido=None if error else A.sha256(texto), error=error, texto=texto)


class Cliente:
    def __init__(self, respuestas):
        self.respuestas, self.envios = list(respuestas), 0

    def enviar(self, agente, texto):
        self.envios += 1
        return self.respuestas.pop(0)

    def tarea(self, agente, task_id):
        return None  # sin relectura: queda NO VERIFICADO, no afecta a lo que se prueba


class Nucleo:
    def __init__(self):
        self.fallos = []

    def registrar_fallo(self, env, fase, error, hipotesis):
        self.fallos.append((fase, error))
        return types.SimpleNamespace(subcomando="registrar-fallo", rc=0, salida="fallo registrado")


def _delegar(tmp_path, respuestas):
    cli, P, reg = Cliente(respuestas), Nucleo(), fases.Registro()
    env = types.SimpleNamespace(raiz=str(tmp_path))
    ll = fases._delegar(P, env, cli, "preventa-experto-azure", "brief", "T2", reg, "BRF-X-R1")
    lineas = (tmp_path / "procedencia" / "a2a.jsonl").read_text(encoding="utf-8").splitlines()
    return ll, cli, P, reg, [json.loads(x)["fase"] for x in lineas]


def test_ya_no_hay_repeticion_ni_pausa():
    for nombre in ("PAUSA_REPETICION_S", "FIRMA_ABORTO_HERRAMIENTA", "es_aborto_herramienta"):
        assert not hasattr(fases, nombre), nombre
    assert not hasattr(fases, "time")                      # nada espera en un turno


@pytest.mark.parametrize("error", [ABORTO, "HTTP 429 rate_limit_exceeded", "timeout tras 110 s", None])
def test_cualquier_fallo_se_registra_una_vez_sin_segundo_envio(tmp_path, error):
    ll, cli, P, reg, fases_a2a = _delegar(tmp_path, [_ll(error or "sin motivo"), _ll(n=2)])
    assert ll is None and cli.envios == 1 and P.fallos == [("T2", error or "sin motivo")]
    assert fases_a2a == ["T2"] and reg.a2a == 1
    assert not any("repetición" in x or "repito" in x for x in reg.lineas)
    assert any(x.startswith("FALLO A2A (preventa-experto-azure)") for x in reg.lineas)


def test_una_respuesta_buena_sigue_igual(tmp_path):
    ll, cli, P, reg, fases_a2a = _delegar(tmp_path, [_ll(n=1)])
    assert ll is not None and ll.task_id == "t-1" and cli.envios == 1 and P.fallos == []
    assert fases_a2a == ["T2"]
