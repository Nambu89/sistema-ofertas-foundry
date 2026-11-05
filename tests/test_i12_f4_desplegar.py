"""ARR-2 (I1.2, F4): paso_ficheros no vacía el mapa antes de subir y main captura ErrorAutenticacion.

Sin red: un ClienteFoundry falso sube y relee ficheros en memoria; ESTADO, MANIFIESTO y EVID van a tmp_path.
"""
import pytest

import desplegar
from lib import hashes
from lib.azure_auth import ErrorAutenticacion

NOMBRES = ["a.py", "b.py", "c.py"]


class Cliente:
    """Sube con ids correlativos y puede caer con ErrorAutenticacion en la subida número `caer_en`."""

    def __init__(self, caer_en=None):
        self.cfg = {"proyecto": "p", "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "agentes": {k: {"modelo": "m"} for k in ("experto_azure", "verificador", "coordinador")}}
        self.registro, self.subidas, self.caer_en, self.remotos = [], [], caer_en, {}

    def subir_fichero(self, ruta):
        if self.caer_en is not None and len(self.subidas) + 1 == self.caer_en:
            raise ErrorAutenticacion("az necesita volver a iniciar sesión (AADSTS50076)")
        fid = f"file-nuevo-{len(self.subidas) + 1}"
        self.subidas.append(ruta.name)
        self.remotos[fid] = {"filename": ruta.name, "bytes": ruta.stat().st_size}
        return {"id": fid, "bytes": ruta.stat().st_size, "status": "processed", "purpose": "assistants"}

    def obtener_fichero(self, fid):
        if fid not in self.remotos:
            raise desplegar.ErrorFoundry("GET", fid, 404, "no existe")
        return self.remotos[fid]


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    rutas = []
    for n in NOMBRES:
        (tmp_path / n).write_text(f"contenido de {n}\n", encoding="utf-8")
        rutas.append((n, tmp_path / n, "repo"))
    monkeypatch.setattr(desplegar, "ficheros_coordinador_i1", lambda reg: list(rutas))
    monkeypatch.setattr(desplegar, "ESTADO", tmp_path / "estado" / "despliegue.json")
    monkeypatch.setattr(desplegar, "MANIFIESTO", tmp_path / "manifiesto.json")
    monkeypatch.setattr(desplegar, "EVID", tmp_path / "evid")
    monkeypatch.setattr(desplegar, "EVID_I1", tmp_path / "evid")
    monkeypatch.setattr(desplegar, "INCREMENTO", "I1")
    return tmp_path


def _desplegado(tmp_path, cli):
    """Estado de un despliegue completo anterior, con los ficheros remotos que lo respaldan."""
    est = {"ficheros": {}, "manifiesto": {"sha256": "x", "bytes": 1, "file_id": "file-man-viejo"}}
    for i, n in enumerate(NOMBRES):
        ruta = tmp_path / n
        est["ficheros"][n] = {"sha256": "viejo", "bytes": ruta.stat().st_size, "file_id": f"file-viejo-{i}",
                              "origen": "repo"}
        cli.remotos[f"file-viejo-{i}"] = {"filename": n, "bytes": ruta.stat().st_size}
    desplegar.escribir_json(desplegar.ESTADO, est)
    return est


def test_fallo_a_mitad_conserva_las_entradas_que_faltan(entorno):
    cli = Cliente(caer_en=2)
    est = _desplegado(entorno, cli)
    with pytest.raises(ErrorAutenticacion):
        desplegar.paso_ficheros(cli, est, [])
    guardado = desplegar.leer_json(desplegar.ESTADO, {})
    ids = {n: f["file_id"] for n, f in guardado["ficheros"].items()}
    assert ids == {"a.py": "file-nuevo-1", "b.py": "file-viejo-1", "c.py": "file-viejo-2"}
    assert guardado["ficheros_huerfanos"] == ["file-viejo-0"]  # el sustituido queda anotado
    assert guardado[desplegar.FICHEROS_INCOMPLETO] is True
    with pytest.raises(desplegar.FalloDespliegue, match="no terminó"):
        desplegar.file_ids(guardado)


def test_reintento_tras_el_fallo_completa_y_quita_la_marca(entorno):
    cli = Cliente(caer_en=2)
    est = _desplegado(entorno, cli)
    with pytest.raises(ErrorAutenticacion):
        desplegar.paso_ficheros(cli, est, [])
    cli.caer_en = None
    est = desplegar.leer_json(desplegar.ESTADO, {})
    desplegar.paso_ficheros(cli, est, [])
    assert cli.subidas == ["a.py", "b.py", "c.py", "manifiesto.json"]  # a.py no se vuelve a subir
    assert desplegar.FICHEROS_INCOMPLETO not in est
    assert sorted(est["ficheros_huerfanos"]) == ["file-man-viejo", "file-viejo-0", "file-viejo-1", "file-viejo-2"]
    assert len(desplegar.file_ids(est)) == 4


def test_todo_reutilizado_no_toca_el_estado(entorno):
    cli = Cliente()
    est = {"ficheros": {}}
    desplegar.paso_ficheros(cli, est, [])
    desplegar.escribir_json(desplegar.ESTADO, est)
    antes = desplegar.ESTADO.read_bytes()
    n = len(cli.subidas)
    desplegar.paso_ficheros(cli, est, [])
    assert len(cli.subidas) == n and desplegar.ESTADO.read_bytes() == antes


def test_un_fichero_que_ya_no_se_monta_es_huerfano_al_final(entorno):
    cli = Cliente()
    est = _desplegado(entorno, cli)
    est["ficheros"]["viejo.py"] = {"sha256": "s", "bytes": 1, "file_id": "file-retirado", "origen": "repo"}
    cli.caer_en = 1
    with pytest.raises(ErrorAutenticacion):
        desplegar.paso_ficheros(cli, est, [])
    assert "file-retirado" not in est.get("ficheros_huerfanos", [])  # nada a medias: se anota al terminar
    cli.caer_en = None
    desplegar.paso_ficheros(cli, est, [])
    assert "file-retirado" in est["ficheros_huerfanos"] and "viejo.py" not in est["ficheros"]


def test_main_captura_error_de_autenticacion_y_deja_el_estado_intacto(entorno, monkeypatch, capsys):
    cli = Cliente(caer_en=1)
    _desplegado(entorno, cli)
    antes = desplegar.ESTADO.read_bytes()
    monkeypatch.setattr(desplegar, "ClienteFoundry", lambda: cli)
    monkeypatch.setattr(desplegar, "modelos_validos", lambda cfg, modelos: None)
    rc = desplegar.main(["--pasos", "ficheros"])
    assert rc == 1
    assert desplegar.ESTADO.read_bytes() == antes  # la primera subida falló: nada cambió
    assert not desplegar.MANIFIESTO.exists()
    err = capsys.readouterr().err
    assert "az login --tenant 00000000-0000-0000-0000-000000000000" in err
    evid = list((entorno / "evid").glob("desplegar_*.json"))
    assert len(evid) == 1 and "ErrorAutenticacion" in evid[0].read_text(encoding="utf-8")


def test_sha_del_fichero_real_se_guarda(entorno):
    cli = Cliente()
    est = {}
    desplegar.paso_ficheros(cli, est, [])
    assert est["ficheros"]["a.py"]["sha256"] == hashes.sha256_fichero(entorno / "a.py")
