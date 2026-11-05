"""Pruebas sin red de B3: sandbox/preventa_run.py, definiciones de agentes y comparación de desplegar."""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

import desplegar
from agentes import definiciones as D
from sandbox import preventa_run as PR

RAIZ = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def montaje(tmp_path, monkeypatch):
    """Simula /mnt/data con los nombres {id}-{fichero} y el manifiesto real de esos ficheros."""
    pytest.skip("CLI de I0 (I0-2) sustituida por la de I1: sus pruebas están en tests/test_i1_estado*.py "
                "(retirada por el integrador de I1, pruebas/I1/INTEGRACION.md)")
    datos = tmp_path / "data"
    datos.mkdir()
    origen = [(n, r) for n, r, _ in desplegar.ficheros_coordinador([])]
    fich = {}
    for i, (nombre, ruta) in enumerate(origen):
        shutil.copyfile(ruta, datos / f"assistant-X{i}-{nombre}")
        fich[nombre] = {"sha256": PR.sha256(str(ruta))}
    (datos / "assistant-M-manifiesto.json").write_text(json.dumps({"ficheros": fich}), encoding="utf-8")
    monkeypatch.setattr(PR, "DATOS", str(datos))
    monkeypatch.setattr(PR, "BASE", str(tmp_path / "preventa"))
    return datos


def test_entorno_p0_ok(montaje, capsys):
    assert PR.main(["entorno"]) == 0
    assert "P0 MONTAJE: OK (6 ficheros" in capsys.readouterr().out


def test_entorno_p0_detecta_cambio(montaje, capsys):
    (montaje / "assistant-X3-ejemplo.json").write_text("{}", encoding="utf-8")
    assert PR.main(["entorno"]) == 1
    assert "P0 MONTAJE: BLOQUEADA" in capsys.readouterr().out


def test_estimar_genera_y_verifica(montaje, capsys):
    assert PR.main(["estimar"]) == 0
    out = capsys.readouterr().out
    assert "ESTIMAR: OK" in out and "VERIFICACIÓN OK" in out
    salida = montaje / "OF-EJEMPLO-001-A-Estimacion.xlsx"
    assert salida.is_file()


def test_estimar_rechaza_contingencia(montaje, capsys):
    rc = montaje / "assistant-X4-rate-card.json"
    d = json.loads(rc.read_text(encoding="utf-8"))
    for valor in (15, True, "0"):
        d["tarifa"]["contingencia_porcentaje"] = valor
        rc.write_text(json.dumps(d), encoding="utf-8")
        assert PR.main(["estimar"]) == 2
        assert "BLOQUEADA" in capsys.readouterr().out


def test_estimar_rechaza_codigo_con_ruta(montaje, capsys):
    malo = montaje / "assistant-Z-malo.json"
    malo.write_text(json.dumps({"codigo": "../../etc/x"}), encoding="utf-8")
    assert PR.main(["estimar", "malo.json"]) == 2
    assert "codigo no válido" in capsys.readouterr().out


def test_buscar_ambiguo_falla(montaje):
    shutil.copyfile(montaje / "assistant-X3-ejemplo.json", montaje / "otro-ejemplo.json")
    with pytest.raises(PR.Fallo):
        PR.buscar("ejemplo.json")


def test_estado_hash_contenido_excluye_decisiones(montaje, capsys):
    est = {"estado": "BORRADOR", "version": "A", "x": 1}
    (montaje / "f-estado.json").write_text(json.dumps(est), encoding="utf-8")
    PR.main(["estado"])
    a = capsys.readouterr().out
    est["decisiones"] = [{"revisor": "R", "decision": "APROBADA"}]
    (montaje / "f-estado.json").write_text(json.dumps(est), encoding="utf-8")
    PR.main(["estado"])
    b = capsys.readouterr().out
    linea = lambda t, k: [x for x in t.splitlines() if x.startswith(k)][0]
    assert linea(a, "HASH_CONTENIDO") == linea(b, "HASH_CONTENIDO")
    assert linea(a, "HASH_CANONICO") != linea(b, "HASH_CANONICO")


def test_json_canonico_igual_que_lib():
    pytest.skip("I1: json_canonico vive en sandbox/nucleo/hashes.py y su prueba es de BA (tests/test_i1_estado_unidad.py)")
    from lib import hashes
    obj = {"b": [1, "ñ"], "a": {"z": None}}
    assert PR.json_canonico(obj) == hashes.json_canonico(obj)


def test_subcomando_desconocido():
    r = subprocess.run([sys.executable, str(RAIZ / "sandbox" / "preventa_run.py"), "borrar"],
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_definiciones():
    coord = D.def_coordinador("gpt-6-luna", ["f1", "f2"], ["/c1", "/c2"])
    assert [t["type"] for t in coord["tools"]] == ["code_interpreter", "a2a", "a2a"]
    assert coord["tools"][0]["container"]["file_ids"] == ["f1", "f2"]
    assert all(t["a2a_version"] == "1.0" for t in coord["tools"][1:])
    exp = D.def_experto_azure("gpt-6-luna")
    assert exp["tools"][0]["allowed_tools"] == {"tool_names": ["microsoft_docs_search", "microsoft_docs_fetch"]}
    assert exp["tools"][1]["openapi"]["auth"] == {"type": "anonymous"}
    assert "brief_recibido" in exp["instructions"]


def test_diferencias_admite_campos_extra_y_detecta_cambios():
    assert desplegar.diferencias({"a": 1, "l": [{"x": 1}]}, {"a": 1, "b": 2, "l": [{"x": 1, "y": 0}]}) == []
    assert desplegar.diferencias({"a": [1, 2]}, {"a": {"tool_names": [1, 2]}})
    assert desplegar.diferencias({"a": 1}, {"a": 2})
    assert desplegar.diferencias({"a": 1}, {})


def test_estimar_no_vacia_una_base_inesperada(montaje, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(PR, "BASE", str(tmp_path))
    assert PR.main(["estimar"]) == 2
    assert "BASE inesperada" in capsys.readouterr().out
    assert (tmp_path / "data").is_dir()
