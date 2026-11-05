"""Raíz de Proyectos por variable (PREVENTA_PROYECTOS, por defecto ~/Proyectos) en el núcleo y en la puerta, con las
mismas variables para generador, plantilla y tarifa. Nunca una ruta fija de un puesto. Sin red."""
from __future__ import annotations

import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

import preventa_run  # noqa: E402
import verificar_paquete as vp  # noqa: E402


def test_la_ruta_de_windows_solo_como_ultimo_recurso(monkeypatch, tmp_path):
    monkeypatch.delenv("PREVENTA_PROYECTOS", raising=False)
    casa = tmp_path / "casa"
    (casa / "Proyectos").mkdir(parents=True)
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: casa))
    assert preventa_run.raiz_proyectos() == casa / "Proyectos" == vp.raiz_proyectos()
    windows = tmp_path / "win"
    windows.mkdir()
    for mod in (preventa_run, vp):
        monkeypatch.setattr(mod, "_RAIZ_WINDOWS", str(windows))
    assert preventa_run.raiz_proyectos() == casa / "Proyectos" == vp.raiz_proyectos()   # existe ~/Proyectos: esa
    (casa / "Proyectos").rmdir()
    assert preventa_run.raiz_proyectos() == windows == vp.raiz_proyectos()   # solo si no existe y la otra sí
    monkeypatch.setenv("PREVENTA_PROYECTOS", str(tmp_path / "no_existe"))
    assert preventa_run.raiz_proyectos() == tmp_path / "no_existe" == vp.raiz_proyectos()   # fijada: se respeta


@pytest.mark.parametrize("valor, esperado", [(None, pathlib.Path.home() / "Proyectos"), ("   ", None), ("/srv/p", "/srv/p")])
def test_raiz_por_variable_o_home(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("PREVENTA_PROYECTOS", raising=False)
    else:
        monkeypatch.setenv("PREVENTA_PROYECTOS", valor)
    esperado = pathlib.Path(esperado) if esperado else pathlib.Path.home() / "Proyectos"   # solo espacios = no fijada
    assert preventa_run.raiz_proyectos() == esperado == vp.raiz_proyectos()


def test_la_puerta_toma_las_variables_del_nucleo(monkeypatch, tmp_path):
    monkeypatch.setenv("PREVENTA_PROYECTOS", str(tmp_path))
    monkeypatch.setenv("PREVENTA_RATE_CARD", str(tmp_path / "tarifa.json"))
    monkeypatch.delenv("PREVENTA_GENERADOR", raising=False)
    monkeypatch.setenv("PREVENTA_PLANTILLA", "  ")
    d = vp.por_defecto()
    assert d["generador"] == tmp_path / "_templates" / "estimacion" / "generar_estimacion.py"
    assert d["plantilla"] == tmp_path / "_templates" / "estimacion" / "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx"
    assert d["rate_card"] == tmp_path / "tarifa.json"


def test_ruta_inexistente_falla_nombrando_la_variable(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PREVENTA_PROYECTOS", str(tmp_path / "no_existe"))
    import preventa_api as P
    env = P.abrir(str(tmp_path / "trabajo"), datos=str(tmp_path), tmp=str(tmp_path / "tmp"), montaje="exacto")
    with pytest.raises(Exception, match="PREVENTA_GENERADOR o PREVENTA_PROYECTOS"):
        env.montado(preventa_run.GENERADOR)
    paquete = tmp_path / "p"
    paquete.mkdir()
    (paquete / "manifiesto_paquete.json").write_text('{"codigo": "OF-KELVARA-001-A"}', encoding="utf-8")
    (paquete / "estado.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("PREVENTA_GENERADOR", raising=False)
    rc = vp.main([str(paquete), "--transcripcion", str(RAIZ / "datos_prueba" / "transcripcion_sintetica_I1.txt"),
                  "--rate-card", str(RAIZ / "datos_prueba" / "transcripcion_sintetica_I1.txt")])
    out = capsys.readouterr().out
    assert rc == 2 and "no existe la generador" in out and "PREVENTA_PROYECTOS" in out, out


def test_una_ruta_explicita_de_catalogo_no_se_sustituye_por_la_del_pilar(monkeypatch):
    from types import SimpleNamespace as NS
    capturado = {}

    def preparar(ctx):
        capturado["explicitas"] = ctx.explicitas
        raise vp.EntradaIlegible("parada de prueba")
    monkeypatch.setattr(vp, "preparar", preparar)
    monkeypatch.setattr(vp, "abrir_paquete", lambda ruta, tmp: NS())
    assert vp.main(["x", "--notas", "n.txt", "--catalogo", str(vp.POR_DEFECTO["catalogo"])]) == 2
    assert capturado["explicitas"] == frozenset({"catalogo"})
