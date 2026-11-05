"""I1.8 · integrador · REVERIF17-1: una tarea marcada como perdida nunca se recoge, aunque el registro diga además
`pendiente: true` (registro incoherente o escrito a mano). Mata el mutante de roturas_i18.py que quitaba esa guarda
(con un registro coherente, perdida ⇒ pendiente false, y el mutante era equivalente). Sin red."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("httpx")
import tests.test_hosted_falsos  # noqa: E402,F401  (pone hosted/ en sys.path)
from preventa_hosted import fases  # noqa: E402

EXPERTO, FASE, HUELLA = "preventa-experto-azure", "experto", "a" * 64


def _registro(tmp_path, **campos):
    d = tmp_path / "procedencia"
    d.mkdir(parents=True)
    linea = {"metodo": "SendMessage", "agente": EXPERTO, "fase": FASE, "task_id": "resp_tarea", "sha256_enviado": HUELLA,
             **campos}
    (d / "a2a.jsonl").write_bytes((json.dumps(linea, ensure_ascii=False) + "\n").encode("utf-8"))
    return tmp_path


def test_pendiente_sin_perdida_se_recoge(tmp_path):
    t = _registro(tmp_path, pendiente=True)
    assert fases.pendiente_previa(t, EXPERTO, FASE, HUELLA)["task_id"] == "resp_tarea"
    assert fases.perdida_previa(t, EXPERTO, FASE) is None


def test_perdida_no_se_recoge_aunque_diga_pendiente(tmp_path):
    t = _registro(tmp_path, pendiente=True, perdida=True, codigo_jsonrpc=-32001)
    assert fases.pendiente_previa(t, EXPERTO, FASE, HUELLA) is None
    assert fases.perdida_previa(t, EXPERTO, FASE)["codigo_jsonrpc"] == -32001
