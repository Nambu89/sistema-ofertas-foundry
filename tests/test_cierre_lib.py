"""Pruebas sin red de los arreglos del cierre de I0 en lib/ (C2, C3, C4 y P3)."""
import pathlib

import pytest

from lib import azure_auth, evidencia, foundry
from tests.test_foundry_offline import Resp, Sesion


@pytest.fixture()
def cli(monkeypatch):
    monkeypatch.setattr(azure_auth, "obtener_token", lambda *a, **k: "tok-falso")
    monkeypatch.setattr(foundry.time, "sleep", lambda s: None)
    return foundry.ClienteFoundry()


# ---------------------------------------------------------------- C2: nombre y destino seguros
@pytest.mark.parametrize("crudo,esperado", [
    ("..\\x.xlsx", "x.xlsx"), ("..\\..\\x.xlsx", "x.xlsx"), ("../../x.xlsx", "x.xlsx"),
    ("C:\\Users\\otro\\OF-PLANTILLA.xlsx", "OF-PLANTILLA.xlsx"), ("/mnt/data/a.xlsx", "a.xlsx"),
    ("OF-EJEMPLO-001-A-Estimacion.xlsx", "OF-EJEMPLO-001-A-Estimacion.xlsx")])
def test_nombre_seguro_se_queda_con_el_ultimo_componente(crudo, esperado):
    assert foundry.ClienteFoundry.nombre_seguro(crudo) == esperado


@pytest.mark.parametrize("crudo", ["", None, ".", "..", "..\\", "C:\\", "a..b.xlsx",
                                   "x.xlsx:flujo", "x\x00.xlsx", " x.xlsx", "x?.xlsx"])
def test_nombre_seguro_rechaza(crudo):
    with pytest.raises(foundry.OperacionNoPermitida):
        foundry.ClienteFoundry.nombre_seguro(crudo)


def test_descarga_fuera_de_la_carpeta_no_pide_nada(cli, tmp_path):
    carpeta = tmp_path / "descargas"
    cli._sesion = Sesion([])  # cualquier petición fallaría con IndexError
    malos = [carpeta / ".." / "x.xlsx",                       # sube un nivel
             pathlib.Path(tmp_path.anchor) / "x.xlsx",         # ruta absoluta fuera
             carpeta / "sub" / ".." / ".." / "x.xlsx",
             carpeta / "x.xlsx:flujo"]
    for destino in malos:
        with pytest.raises(foundry.OperacionNoPermitida):
            cli.descargar_fichero_contenedor("cntr_1", "cfile_1", destino, carpeta=carpeta)
    assert cli._sesion.peticiones == []
    assert not (tmp_path / "x.xlsx").exists()


def test_descarga_valida_queda_dentro(cli, tmp_path):
    carpeta = tmp_path / "descargas"
    cli._sesion = Sesion([Resp(200, b"PK-bytes")])
    d = cli.descargar_fichero_contenedor("cntr_1", "cfile_1", carpeta / "ok.xlsx", carpeta=carpeta)
    assert d.read_bytes() == b"PK-bytes" and d.resolve().parent == carpeta.resolve()
    assert cli._sesion.peticiones[0][1].endswith("/openai/v1/containers/cntr_1/files/cfile_1/content")


# ------------------------------------------------------------------- C3: ámbito de asignar_rol
def test_asignar_rol_rechaza_ambito_ajeno(cli):
    cli._sesion = Sesion([])
    rol = cli.cfg["roles"]["foundry_agent_consumer"]
    sub = cli.cfg["suscripcion_id"]
    for ambito in (f"/subscriptions/{sub}", f"/subscriptions/{sub}/resourceGroups/rg-preventa-ejemplo",
                   cli.id_arm_cuenta.replace("recurso-ejemplo", "otro-recurso"),
                   cli.id_arm_proyecto + "/../otro", cli.id_arm_proyecto + "x", ""):
        with pytest.raises(foundry.OperacionNoPermitida, match="Ámbito"):
            cli.asignar_rol(ambito, rol, "00000000-0000-0000-0000-000000000001")
    assert cli._sesion.peticiones == []


@pytest.mark.parametrize("cual", ["cuenta", "proyecto"])
def test_asignar_rol_admite_cuenta_y_proyecto(cli, cual):
    ambito = cli.id_arm_cuenta if cual == "cuenta" else cli.id_arm_proyecto
    cli._sesion = Sesion([Resp(200, b'{"value": []}'), Resp(201, b'{"id": "asig"}')])
    r = cli.asignar_rol(ambito.upper() + "/", cli.cfg["roles"]["foundry_user"], "pid")
    assert r == {"id": "asig"}
    metodo, url, _, cuerpo = cli._sesion.peticiones[1]
    assert metodo == "PUT" and ambito.upper() in url and cuerpo["properties"]["principalId"] == "pid"


# ------------------------------------------------------------------ C4: red anti-JWT/Bearer
JWT = "eyJ" + "a" * 30 + "." + "b" * 30 + ".firma"
MALOS = [{"t": JWT}, {"h": "Bearer " + "x" * 40}, {"h": "bearer " + "x" * 40}, {"h": "BEARER " + "x" * 40},
         {"h": "Bearer    " + "x" * 30 + "+/=="}, {"h": "Bearer\t" + "x" * 40},
         ["InstrumentationKey=" + "0" * 8 + "-1111-2222-3333-" + "4" * 12],
         {"c": "DefaultEndpointsProtocol=https;AccountKey=" + "A" * 40}]


@pytest.mark.parametrize("obj", MALOS)
def test_evidencia_rechaza_tokens_y_no_escribe(tmp_path, obj):
    p = tmp_path / "ev.json"
    with pytest.raises(evidencia.EvidenciaConSecreto) as e:
        evidencia.escribir_json(p, obj)
    assert not p.exists()
    assert "x" * 40 not in str(e.value) and "a" * 30 not in str(e.value)  # no muestra el valor


@pytest.mark.parametrize("obj", MALOS)
def test_desplegar_escribir_json_usa_la_red(tmp_path, obj):
    import desplegar
    with pytest.raises(evidencia.EvidenciaConSecreto):
        desplegar.escribir_json(tmp_path / "d.json", obj)
    assert not (tmp_path / "d.json").exists()


def test_evidencia_normal_se_escribe(tmp_path):
    import desplegar
    obj = {"a": "Bearer corto", "b": "InstrumentationKey=abc", "c": "texto con eyJ suelto", "ñ": 1}
    desplegar.escribir_json(tmp_path / "ok.json", obj)
    assert '"ñ": 1' in (tmp_path / "ok.json").read_text(encoding="utf-8")


# ------------------------------------------------------------------------- P3: paginación
@pytest.mark.parametrize("metodo,args,ruta", [("listar_ficheros", (), "/openai/v1/files"),
                                              ("listar_ficheros_contenedor", ("cntr_9",),
                                               "/openai/v1/containers/cntr_9/files")])
def test_listados_openai_siguen_has_more(cli, metodo, args, ruta):
    cli._sesion = Sesion([Resp(200, b'{"data": [{"id": "f1"}], "has_more": true, "last_id": "f1"}'),
                          Resp(200, b'{"data": [{"id": "f2"}], "has_more": false}')])
    assert [f["id"] for f in getattr(cli, metodo)(*args)] == ["f1", "f2"]
    (_, u1, p1, _), (_, u2, p2, _) = cli._sesion.peticiones
    assert u1.endswith(ruta) and u2.endswith(ruta) and p1 is None and p2 == {"after": "f1"}


def test_listado_openai_truncado_falla(cli):
    cli._sesion = Sesion([Resp(200, b'{"data": [], "has_more": true}')])
    with pytest.raises(foundry.ErrorFoundry, match="truncada"):
        cli.listar_ficheros()


def test_desplegar_escribir_json_rechaza_enlaces(tmp_path):
    """Integración I1.1 (Revisión): una evidencia no se escribe a través de un enlace simbólico."""
    import desplegar
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    enlace = tmp_path / "evid"
    try:
        enlace.symlink_to(fuera, target_is_directory=True)
    except OSError:
        pytest.skip("este Windows no permite crear enlaces simbólicos sin privilegios")
    with pytest.raises(desplegar.FalloDespliegue):
        desplegar.escribir_json(enlace / "x.json", {"a": 1})
    assert not (fuera / "x.json").exists()


def test_desplegar_escribir_json_rechaza_enlaces_simulados(tmp_path, monkeypatch):
    """La misma guarda sin privilegios para crear enlaces: se simula que la carpeta es un enlace."""
    import pathlib
    import desplegar
    carpeta = (tmp_path / "evid").absolute()
    carpeta.mkdir()
    real = pathlib.Path.is_symlink
    monkeypatch.setattr(pathlib.Path, "is_symlink", lambda self: self == carpeta or real(self))
    with pytest.raises(desplegar.FalloDespliegue, match="enlace simbólico"):
        desplegar.escribir_json(carpeta / "x.json", {"a": 1})
    assert not (carpeta / "x.json").exists()
    desplegar.escribir_json(tmp_path / "otra.json", {"a": 1})  # sin enlace en la ruta: se escribe
    assert (tmp_path / "otra.json").exists()
