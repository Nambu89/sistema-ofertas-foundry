"""Pruebas de _baseline/salida.py: la captura nunca pisa la línea base sin pedirlo (H2 de VERIF-I0)."""
import importlib.util
import pathlib

import pytest

RUTA = pathlib.Path(__file__).resolve().parents[1] / "_baseline" / "salida.py"


@pytest.fixture()
def salida(tmp_path, monkeypatch):
    """Carga el módulo con la línea base redirigida a una carpeta temporal ya poblada."""
    spec = importlib.util.spec_from_file_location("salida_baseline", RUTA)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = tmp_path / "_baseline"
    datos = base / "datos"
    datos.mkdir(parents=True)
    (datos / "arm_cuenta.json").write_text("{}", encoding="utf-8")
    precios = base / "precios.json"
    precios.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mod, "DATOS", datos)
    monkeypatch.setattr(mod, "PRECIOS", precios)
    monkeypatch.setattr(mod, "PROTEGIDOS", (datos, precios))
    return mod


def test_sin_salida_y_linea_base_existente_falla(salida):
    with pytest.raises(SystemExit, match="ya existe"):
        salida.destino(salida.DATOS, [])
    with pytest.raises(SystemExit, match="ya existe"):
        salida.destino(salida.PRECIOS, [])


def test_salida_dentro_de_la_linea_base_falla(salida):
    for ruta in (salida.DATOS, salida.DATOS / "sub", salida.DATOS.parent):
        with pytest.raises(SystemExit, match="pisa la línea base"):
            salida.destino(salida.DATOS, ["--salida", str(ruta)])


def test_salida_aparte_escribe_fuera(salida, tmp_path):
    otra = tmp_path / "comparacion"
    assert salida.destino(salida.DATOS, ["--salida", str(otra)]) == otra.resolve()
    assert salida.destino(salida.PRECIOS, ["--salida", str(otra)]) == otra.resolve() / "precios.json"
    assert otra.is_dir()


def test_sobrescribir_explicito(salida):
    assert salida.destino(salida.DATOS, ["--sobrescribir-linea-base"]) == salida.DATOS


def test_linea_base_vacia_se_crea(salida):
    (salida.DATOS / "arm_cuenta.json").unlink()
    assert salida.destino(salida.DATOS, []) == salida.DATOS


def test_argumento_desconocido_falla(salida):
    with pytest.raises(SystemExit, match="no reconocido"):
        salida.destino(salida.DATOS, ["--salid", "x"])
    with pytest.raises(SystemExit, match="no reconocido"):
        salida.destino(salida.DATOS, ["--salida"])
