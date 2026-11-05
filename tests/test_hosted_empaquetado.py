"""Hosted agent: el ZIP que se despliega funciona SOLO con lo que lleva dentro.

Se construye con hosted/empaquetar.py, se extrae en una carpeta temporal y, en un proceso aparte que no ve el
repositorio para el código (solo para los dobles de prueba), se recorre del alta al paquete con el núcleo, los
esquemas y los recursos canónicos empaquetados.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile

import pytest

from tests.test_hosted_falsos import HOSTED, PROYECTO, RAIZ

sys.path.insert(0, str(HOSTED))
import empaquetar  # noqa: E402

DRIVER = r'''
import importlib.util, json, os, pathlib, sys
Z, R, H = (pathlib.Path(a) for a in sys.argv[1:4])
for v in [k for k in os.environ if k.startswith("PREVENTA_")]:
    os.environ.pop(v)
os.environ.update(FOUNDRY_PROJECT_ENDPOINT=sys.argv[4], PREVENTA_HOME=str(H), PREVENTA_MAX_A2A_POR_TURNO="1")
sys.path.insert(0, str(Z))
import main
main.marcar_orquestador()   # lo que hace `python main.py` al arrancar (I1.5, VER14-3)
from preventa_hosted import config
from preventa_hosted.turno import Coordinador
spec = importlib.util.spec_from_file_location("falsos", R / "tests" / "test_hosted_falsos.py")
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
cfg = config.cargar()
c = Coordinador(cfg, lambda: "t", transporte_a2a=F.httpx.MockTransport(F.A2AFalso()),
                transporte_http=F.httpx.MockTransport(F.ModeloFalso()))
r1 = c.manejar(F.ALTA, [F.adjunto_transcripcion()])
r2 = c.manejar("ASUMIR: volumetria = 150 técnicos usuarios y unos 20.000 documentos (informes, procedimientos y normas)\n"
               "ASUMIR: identidad_acl_origen = "
               "Documentos en SharePoint Online con permisos por grupos de Entra ID", [])
import preventa_api, nucleo.estado
print(json.dumps({"app": str(cfg.app), "api": preventa_api.__file__, "nucleo": nucleo.estado.__file__,
                  "recursos": {k: os.environ[k] for k in config.recursos()},
                  "r1": r1, "r2": r2}, ensure_ascii=False))
'''


@pytest.fixture(autouse=True)
def instantanea_de_prueba(tmp_path, monkeypatch):
    """I1.7 (R): empaquetar.py exige la instantánea de precios (huella, cobertura del catálogo y ≤ 31 días). Estas pruebas
    miran el ZIP, no los precios: una instantánea sintética de ayer, igual en las dos rutas y sin entrada en
    manifiesto.json (la de verdad la genera catalogo/instantanea_precios.py al desplegar)."""
    import datetime as dt
    from tests.test_hosted_i17_r import CATALOGO, escribir, instantanea_sintetica
    a, b = tmp_path / "instantanea_datos.json", tmp_path / "instantanea_catalogo.json"
    escribir(instantanea_sintetica(CATALOGO, dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)), a, b)
    canon = dict(empaquetar.CANONICOS)
    canon["precios_instantanea.json"] = (a, None)
    monkeypatch.setattr(empaquetar, "CANONICOS", canon)
    monkeypatch.setattr(empaquetar, "INSTANTANEA_CATALOGO", b)
    return a


def test_zip_plano_determinista_y_completo(tmp_path):
    a = empaquetar.construir(tmp_path / "a.zip")
    b = empaquetar.construir(tmp_path / "b.zip")
    assert a["sha256"] == b["sha256"]                              # determinista
    nombres = zipfile.ZipFile(tmp_path / "a.zip").namelist()
    assert "main.py" in nombres and "requirements.txt" in nombres  # plano, sin carpeta envolvente
    assert {"sandbox/preventa_api.py", "sandbox/nucleo/estado.py", "esquemas/requisitos.json",
            "recursos/generar_estimacion.py", "recursos/precios_instantanea.json", "MANIFIESTO-HOSTED.json"} <= set(nombres)
    assert not [n for n in nombres if "__pycache__" in n or ".venv" in n or n.startswith("tests/")]
    req = zipfile.ZipFile(tmp_path / "a.zip").read("requirements.txt").decode()
    assert "azure-ai-agentserver-responses==2.2.0" in req and "agent-framework" not in req


def test_canonico_modificado_no_se_empaqueta(tmp_path, monkeypatch):
    falso = tmp_path / "generar_estimacion.py"
    falso.write_text("# retocado\n", encoding="utf-8")
    canon = dict(empaquetar.CANONICOS)
    canon["generar_estimacion.py"] = (falso, "generar_estimacion.py")
    monkeypatch.setattr(empaquetar, "CANONICOS", canon)
    with pytest.raises(empaquetar.ErrorEmpaquetado, match="generar_estimacion.py: SHA-256"):
        empaquetar.construir(tmp_path / "x.zip")
    assert not (tmp_path / "x.zip").exists()


def test_recorrido_desde_el_zip_extraido(tmp_path):
    empaquetar.construir(tmp_path / "agente.zip")
    destino = tmp_path / "zip"
    zipfile.ZipFile(tmp_path / "agente.zip").extractall(destino)
    r = subprocess.run([sys.executable, "-c", DRIVER, str(destino), str(RAIZ), str(tmp_path / "home"), PROYECTO],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(tmp_path),
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=500)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    for clave in ("app", "api", "nucleo"):
        assert out[clave].startswith(str(destino)), out[clave]
    assert all(v.startswith(str(destino)) for v in out["recursos"].values()), out["recursos"]
    assert "ALTA: OK OF-KELVARA-001-A" in out["r1"], out["r1"]
    assert "EXPERTO: VÁLIDA" in out["r2"] and "$ consolidar → rc 0" in out["r2"], out["r2"]
