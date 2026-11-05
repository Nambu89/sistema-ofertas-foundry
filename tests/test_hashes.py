"""Pruebas de lib/hashes.py: SHA-256 de ficheros y hash canónico de JSON."""
import hashlib
import math

import pytest

from lib import hashes


def test_sha256_fichero_coincide_con_hashlib(tmp_path):
    f = tmp_path / "a.bin"
    datos = b"preventa" * 300000  # más de un bloque de lectura
    f.write_bytes(datos)
    assert hashes.sha256_fichero(f) == hashlib.sha256(datos).hexdigest()


def test_sha256_fichero_vacio(tmp_path):
    f = tmp_path / "vacio"
    f.write_bytes(b"")
    assert hashes.sha256_fichero(f) == hashlib.sha256(b"").hexdigest()


def test_hash_json_no_depende_del_orden_ni_del_espaciado():
    a = {"b": 1, "a": {"y": [1, 2], "x": "ñ"}}
    b = {"a": {"x": "ñ", "y": [1, 2]}, "b": 1}
    assert hashes.hash_json(a) == hashes.hash_json(b)


def test_json_canonico_utf8_sin_escapar_y_sin_espacios():
    assert hashes.json_canonico({"b": "€", "a": 1}) == '{"a":1,"b":"€"}'.encode("utf-8")


def test_hash_json_distingue_orden_de_listas_y_tipos():
    assert hashes.hash_json([1, 2]) != hashes.hash_json([2, 1])
    assert hashes.hash_json({"a": 1}) != hashes.hash_json({"a": "1"})


def test_hash_json_rechaza_nan():
    with pytest.raises(ValueError):
        hashes.hash_json({"a": math.nan})


def test_hash_json_sin_excluye_claves_de_primer_nivel():
    base = {"contenido": {"x": 1}, "version": "A"}
    con_decisiones = dict(base, decisiones=[{"quien": "El responsable de preventa", "ok": True}])
    assert hashes.hash_json_sin(con_decisiones, ["decisiones"]) == hashes.hash_json(base)
    with pytest.raises(TypeError):
        hashes.hash_json_sin([1], ["x"])


def test_manifiesto_relativo_ordenado_y_sin_duplicados(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "b.txt").write_bytes(b"b")
    (tmp_path / "sub" / "a.txt").write_bytes(b"a")
    m = hashes.manifiesto([tmp_path / "b.txt", tmp_path / "sub" / "a.txt"], base=tmp_path)
    assert list(m) == ["b.txt", "sub/a.txt"]
    assert m["sub/a.txt"] == hashlib.sha256(b"a").hexdigest()
    with pytest.raises(ValueError):
        hashes.manifiesto([tmp_path / "b.txt", tmp_path / "b.txt"], base=tmp_path)
