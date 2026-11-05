"""Pruebas de descargar.py (papel E de I1) con un cliente simulado: sin red ni tokens."""
from __future__ import annotations

import hashlib

import descargar


def _mensaje(*citas):
    return {"type": "message", "content": [{"type": "output_text", "text": "x", "annotations": [
        {"type": "container_file_citation", "container_id": c, "file_id": f, "filename": n} for c, f, n in citas]}]}


class ClienteFalso:
    def __init__(self, items=None, ficheros=None, respuesta=None):
        self.items, self.ficheros, self.respuesta = items or [], ficheros or [], respuesta or {}
        self.pedidos = []

    def _listar_openai(self, ruta):
        assert ruta.startswith("conversations/")
        return self.items

    def listar_ficheros_contenedor(self, cid):
        return self.ficheros

    def obtener_respuesta(self, rid):
        return self.respuesta

    def _openai(self, metodo, ruta, crudo=False):
        self.pedidos.append(ruta)
        return f"contenido de {ruta}".encode()


def test_ultima_cita_de_la_conversacion(tmp_path, capsys):
    items = [_mensaje(("cnt_1", "f_2", "OF-KELVARA-001-A-Paquete.zip")), _mensaje(("cnt_0", "f_1", "viejo.zip"))]
    cli = ClienteFalso(items=items)
    assert descargar.main(["conversacion", "conv_1", "--destino", str(tmp_path)], cliente=cli) == 0
    assert cli.pedidos == ["containers/cnt_1/files/f_2/content"]
    p = tmp_path / "OF-KELVARA-001-A-Paquete.zip"
    out = capsys.readouterr().out
    assert p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() in out and "verificar_paquete.py" in out


def test_nombre_con_ruta_se_sanea_y_queda_dentro(tmp_path):
    cli = ClienteFalso(items=[_mensaje(("c", "f", "../../fuera/../malo.zip"))])
    assert descargar.main(["conversacion", "x", "--destino", str(tmp_path)], cliente=cli) == 0
    assert (tmp_path / "malo.zip").exists() and not (tmp_path.parent / "malo.zip").exists()


def test_nunca_sobrescribe_un_fichero_distinto(tmp_path):
    (tmp_path / "a.zip").write_bytes(b"otro contenido")
    cli = ClienteFalso(items=[_mensaje(("c", "f", "a.zip"))])
    assert descargar.main(["conversacion", "x", "--destino", str(tmp_path)], cliente=cli) == 0
    assert (tmp_path / "a.zip").read_bytes() == b"otro contenido"
    assert len(list(tmp_path.glob("a-*.zip"))) == 1


def test_contenedor_todos_los_ficheros(tmp_path):
    cli = ClienteFalso(ficheros=[{"id": "f1", "path": "/mnt/data/preventa/salida/x.pptx"}, {"id": "f2", "path": "/mnt/data/y.json"}])
    assert descargar.main(["contenedor", "cnt", "--destino", str(tmp_path)], cliente=cli) == 0
    assert {p.name for p in tmp_path.iterdir()} == {"x.pptx", "y.json"}


def test_sin_citas_da_rc_1(tmp_path, capsys):
    cli = ClienteFalso(items=[{"type": "message", "content": []}])
    assert descargar.main(["conversacion", "x", "--destino", str(tmp_path)], cliente=cli) == 1
    assert "NADA QUE DESCARGAR" in capsys.readouterr().out


def test_fallo_de_api_falla_en_alto(tmp_path, capsys):
    class Caducado(ClienteFalso):
        def _openai(self, metodo, ruta, crudo=False):
            raise RuntimeError("GET https://x/containers/c/files/f/content -> 404: not found")
    cli = Caducado(respuesta={"output": [_mensaje(("c", "f", "p.zip"))]})
    assert descargar.main(["respuesta", "r", "--destino", str(tmp_path)], cliente=cli) == 1
    assert "caducado" in capsys.readouterr().out
