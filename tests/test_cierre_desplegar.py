"""Pruebas sin red del respaldo de modelo de desplegar.py (P1) y de la descarga de pruebas_b3 (C2)."""
import pytest

import desplegar
import pruebas_b3
from lib import azure_auth, foundry
from lib.foundry import ErrorFoundry
from tests.test_foundry_offline import Resp, Sesion

MODELOS = {"experto_azure": "gpt-6-luna", "verificador": "gpt-5.6-luna", "coordinador": "gpt-6-luna"}


class Falso:
    def __init__(self):
        self.cfg = foundry.cargar_config()


def _err(cuerpo, estado=400):
    return ErrorFoundry("POST", "https://x/agents", estado, cuerpo)


@pytest.mark.parametrize("cuerpo,estado,esperado", [
    ('{"error":{"message":"The model gpt-6-luna is not available for this tool"}}', 400, True),
    ('{"error":{"message":"Tool type a2a is not supported"}}', 400, True),
    ('{"error":{"message":"This model does not support code_interpreter"}}', 400, True),
    ('{"error":{"message":"Invalid value for instructions: too long"}}', 400, False),
    ('{"error":{"message":"Unsupported parameter: temperature"}}', 400, False),
    ('{"error":{"message":"gpt-6-luna overloaded"}}', 500, False),
    ('{"error":{"message":"Invalid value for instructions (model gpt-6-luna)"}}', 400, False),
    ("The deployment for model gpt-6-luna was not found", 400, True),
    ('{"error":{"message":"Invalid instructions for the gpt-6-luna agent","detail":"' + "x" * 200
     + ' deployment other-model was not found"}}', 400, False),   # modelo y rechazo, lejos
    ('{"error":{"message":"Model config ok","detail":"' + "x" * 200 + ' parameter seed unsupported"}}',
     400, False),
    ("", 400, False)])
def test_rechaza_modelo(cuerpo, estado, esperado):
    assert desplegar.rechaza_modelo(_err(cuerpo, estado), "gpt-6-luna") is esperado


@pytest.fixture()
def llamadas(monkeypatch):
    """asegurar_agente falso: el primer intento lanza el error preparado; el resto devuelve."""
    estado = {"error": None, "modelos": []}

    def falso(c, nombre, definicion, descripcion, reg):
        estado["modelos"].append(definicion["model"])
        if len(estado["modelos"]) == 1 and estado["error"]:
            raise estado["error"]
        return {"version": "1"}
    monkeypatch.setattr(desplegar, "asegurar_agente", falso)
    return estado


def _asegurar(clave, respaldo, modelos=MODELOS):
    reg = []
    v, m = desplegar.asegurar_con_respaldo(Falso(), "preventa-x", lambda mo: {"model": mo},
                                           modelos[clave], respaldo, "d", reg, clave,
                                           {**modelos, "respaldo": respaldo})
    return m, reg


def test_sin_respaldo_no_hay_segundo_intento(llamadas):
    llamadas["error"] = _err("model gpt-6-luna is not supported")
    with pytest.raises(ErrorFoundry):
        _asegurar("coordinador", None)
    assert llamadas["modelos"] == ["gpt-6-luna"]


def test_400_generico_no_activa_el_respaldo(llamadas):
    llamadas["error"] = _err("Invalid value for instructions")
    with pytest.raises(ErrorFoundry):
        _asegurar("coordinador", "gpt-5.5")
    assert llamadas["modelos"] == ["gpt-6-luna"]


def test_respaldo_nunca_con_el_modelo_del_verificador(llamadas):
    llamadas["error"] = _err("model gpt-6-luna is not supported")
    for clave in ("coordinador", "experto_azure"):
        llamadas["modelos"].clear()
        with pytest.raises(desplegar.FalloDespliegue):
            _asegurar(clave, "gpt-5.6-luna")
        assert llamadas["modelos"] == ["gpt-6-luna"]


def test_verificador_no_cae_al_modelo_de_los_demas(llamadas):
    llamadas["error"] = _err("model gpt-5.6-luna is not supported")
    with pytest.raises(desplegar.FalloDespliegue):
        _asegurar("verificador", "gpt-6-luna")
    assert llamadas["modelos"] == ["gpt-5.6-luna"]


def test_respaldo_valido_tras_rechazo_del_modelo(llamadas):
    llamadas["error"] = _err('{"error":{"message":"Tool code_interpreter is not supported with gpt-6-luna"}}')
    m, reg = _asegurar("coordinador", "gpt-5.5")
    assert m == "gpt-5.5" and llamadas["modelos"] == ["gpt-6-luna", "gpt-5.5"]
    assert "RESPALDO USADO" in reg[-1]["aviso"] and "error_literal" in reg[-1]


@pytest.mark.parametrize("argv", [["--respaldo", "gpt-5.6-luna"], ["--modelo-experto", "gpt-5.6-luna"],
                                  ["--modelo-verificador", "gpt-6-luna"]])
def test_main_rechaza_modelos_que_rompen_la_independencia(argv, capsys):
    with pytest.raises(SystemExit) as e:
        desplegar.main(argv + ["--pasos", "card"])
    err = capsys.readouterr().err
    assert e.value.code == 2 and "verificador" in err


def test_respaldo_sin_valor_por_defecto(monkeypatch):
    vistos = {}

    def capturar(cfg, modelos):
        vistos.update(modelos)
        raise SystemExit(9)  # se para antes de cualquier paso
    monkeypatch.setattr(desplegar, "ClienteFoundry", Falso)
    monkeypatch.setattr(desplegar, "modelos_validos", capturar)
    with pytest.raises(SystemExit):
        desplegar.main(["--pasos", "card"])
    assert vistos["respaldo"] is None


# ----------------------------------------------------- C2: descarga de pruebas_b3 con nombre hostil
@pytest.fixture()
def cli(monkeypatch):
    monkeypatch.setattr(azure_auth, "obtener_token", lambda *a, **k: "tok-falso")
    return foundry.ClienteFoundry()


def _resp_con_cita(nombre):
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "x", "annotations": [
        {"type": "container_file_citation", "container_id": "cntr_1", "file_id": "cfile_1",
         "filename": nombre}]}]}]}


@pytest.mark.parametrize("nombre", ["..\\..\\malo.xlsx", "C:\\Users\\otro\\OF-PLANTILLA.xlsx",
                                    "/mnt/data/bueno.xlsx"])
def test_descargar_xlsx_queda_en_la_carpeta(cli, tmp_path, nombre):
    carpeta = tmp_path / "descargas"
    cli._sesion = Sesion([Resp(200, b"PK")])
    ev = {}
    d = pruebas_b3.descargar_xlsx(cli, _resp_con_cita(nombre), ev, carpeta)
    assert d is not None and d.resolve().parent == carpeta.resolve() and d.read_bytes() == b"PK"
    assert ev["nombre_saneado"]["guardado"] == d.name
    assert list(tmp_path.rglob("*.xlsx")) == [d]


@pytest.mark.parametrize("nombre", ["a..xlsx", "x.xlsx:flujo.xlsx", "..xlsx", "x\x07.xlsx"])
def test_descargar_xlsx_rechaza_y_lo_anota(cli, tmp_path, nombre):
    cli._sesion = Sesion([])
    ev = {}
    assert pruebas_b3.descargar_xlsx(cli, _resp_con_cita(nombre), ev, tmp_path / "d") is None
    assert "descarga_rechazada" in ev and cli._sesion.peticiones == []
