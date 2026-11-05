"""Pruebas del núcleo portable (papel P): carpetas como parámetro, montaje sin file_ids y API de biblioteca.

Sin red. Comprueban que los valores por defecto del sandbox no cambian, que la lógica no depende del
sufijo de montaje y que la API (preventa_api.py) da lo mismo que la CLI.
"""
from __future__ import annotations

import json
import pathlib
import re
import shutil

import pytest

from tests.test_i1_estado_comun import ADJUNTO, ESQUEMAS, TRANSCRIPCION, Mundo

import preventa_run as PR  # noqa: E402  (sandbox/ ya está en sys.path por test_i1_estado_comun)


@pytest.fixture
def sin_vars(monkeypatch):
    for v in ("PREVENTA_TRABAJO", "PREVENTA_RAIZ", "PREVENTA_DATOS", "PREVENTA_APP", "PREVENTA_TMP", "PREVENTA_MONTAJE"):
        monkeypatch.delenv(v, raising=False)


# --- opciones de carpetas -------------------------------------------------------------------------

def test_separar_globales_formas_y_resto():
    op, resto, err = PR.separar_globales(["--trabajo", "/w", "--datos=/d", "--montaje", "exacto", "estado", "--json"])
    assert op == {"trabajo": "/w", "datos": "/d", "montaje": "exacto"} and resto == ["estado", "--json"] and err == []


def test_separar_globales_repetida_vacia_y_sin_valor():
    op, resto, err = PR.separar_globales(["--app", "a", "--app", "  ", "estado"])
    assert err == ["--app repetida", "--app vacía"] and resto == ["estado"]
    op, resto, err = PR.separar_globales(["--trabajo"])  # sin valor: lo rechaza el parser con rc 2
    assert op == {} and resto == ["--trabajo"]
    op, resto, err = PR.separar_globales(["estado", "--trabajo", "x"])  # tras el subcomando no es global
    assert op == {} and resto == ["estado", "--trabajo", "x"]


# --- resolución del entorno -----------------------------------------------------------------------

def test_defectos_del_sandbox_sin_cambios(monkeypatch, sin_vars):
    llamadas = []
    monkeypatch.setattr(PR, "es_local", lambda: False)
    monkeypatch.setattr(PR, "preparar_sandbox", lambda datos, app: llamadas.append((datos, app)) or [])
    env = PR.Entorno.resolver()
    assert (env.local, env.datos, env.raiz) == (False, pathlib.Path("/mnt/data"), pathlib.Path("/mnt/data/preventa"))
    assert (env.app, env.base_tmp, env.montaje) == (pathlib.Path("/tmp/preventa/app"), pathlib.Path("/tmp/preventa"), "sufijo")
    assert llamadas == [(pathlib.Path("/mnt/data"), pathlib.Path("/tmp/preventa/app"))] and env.errores_config == []


def test_sandbox_con_carpetas_por_parametro(monkeypatch, sin_vars, tmp_path):
    monkeypatch.setattr(PR, "es_local", lambda: False)
    monkeypatch.setattr(PR, "preparar_sandbox", lambda datos, app: [])
    env = PR.Entorno.resolver(trabajo=str(tmp_path / "w"), datos=str(tmp_path / "d"), tmp=str(tmp_path / "t"))
    assert (env.raiz, env.datos, env.base_tmp, env.app) == (tmp_path / "w", tmp_path / "d", tmp_path / "t", tmp_path / "t" / "app")


def test_local_precedencia_argumento_variable_defecto(monkeypatch, sin_vars, tmp_path):
    monkeypatch.chdir(tmp_path)
    env = PR.Entorno.resolver()
    assert (env.datos, env.raiz, env.app) == (tmp_path, tmp_path / "preventa", pathlib.Path(PR.__file__).resolve().parent)
    monkeypatch.setenv("PREVENTA_RAIZ", str(tmp_path / "r"))
    assert PR.Entorno.resolver().raiz == tmp_path / "r"
    monkeypatch.setenv("PREVENTA_TRABAJO", "   ")  # solo espacios = sin fijar: no anula PREVENTA_RAIZ (LES-G-076)
    assert PR.Entorno.resolver().raiz == tmp_path / "r"
    assert PR.Entorno.resolver(trabajo=str(tmp_path / "arg")).raiz == tmp_path / "arg"


def test_configuracion_contradictoria_falla_en_alto(monkeypatch, sin_vars, tmp_path):
    monkeypatch.setenv("PREVENTA_TRABAJO", str(tmp_path / "a"))
    monkeypatch.setenv("PREVENTA_RAIZ", str(tmp_path / "b"))
    monkeypatch.setenv("PREVENTA_MONTAJE", "id")
    err = PR.Entorno.resolver().errores_config
    assert len(err) == 2 and "no coinciden" in err[0] and "montaje 'id' no válido" in err[1]


# --- esquemas sin repositorio: el localizador lo pone el arranque ---------------------------------

@pytest.fixture
def esquema_sin_repo(monkeypatch, tmp_path):
    from nucleo import esquema
    monkeypatch.setattr(esquema, "_REPO_ESQUEMAS", tmp_path / "no-existe")
    monkeypatch.setattr(esquema, "_CACHE", {})
    yield esquema
    esquema.configurar(None)


def test_esquema_sin_localizador_es_integridad_rota(esquema_sin_repo):
    from nucleo.errores import IntegridadRota
    esquema_sin_repo.configurar(None)
    with pytest.raises(IntegridadRota, match="localizador"):
        esquema_sin_repo.cargar("estado")


@pytest.mark.parametrize("montaje, nombre", [("sufijo", "assistant-Q1-esquema_estado.json"),
                                             ("exacto", "esquema_estado.json")])
def test_esquema_por_montaje_del_entorno(esquema_sin_repo, tmp_path, montaje, nombre):
    datos = tmp_path / "d"
    datos.mkdir()
    shutil.copy(ESQUEMAS / "estado.json", datos / nombre)
    env = PR.Entorno(True, datos, datos / "preventa", [], app=pathlib.Path(PR.__file__).resolve().parent, montaje=montaje)
    PR._nucleo(env)
    assert esquema_sin_repo.cargar("estado") == json.loads((ESQUEMAS / "estado.json").read_text(encoding="utf-8"))
    if montaje == "exacto":  # con montaje exacto, un nombre con file_id no vale
        (datos / nombre).rename(datos / f"assistant-Q1-{nombre}")
        esquema_sin_repo._CACHE.clear()
        with pytest.raises(Exception, match="exactamente un esquema_estado.json"):
            esquema_sin_repo.cargar("estado")


# --- arranque del sandbox ------------------------------------------------------------------------

def test_preparar_sandbox_copia_en_la_app_indicada_y_no_borra_lo_ajeno(tmp_path, monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys, "path", list(_sys.path))
    datos = tmp_path / "montado"
    datos.mkdir()
    (datos / "x-nucleo_init.py").write_text("", encoding="utf-8")
    (datos / "x-manifiesto.json").write_text(json.dumps({"ficheros": {}}), encoding="utf-8")
    app = tmp_path / "otra-app"
    PR.preparar_sandbox(datos, app)
    assert (app / "nucleo" / "__init__.py").is_file() and str(app) in _sys.path
    (app / "importante.txt").write_text("no se borra", encoding="utf-8")
    errores = PR.preparar_sandbox(datos, app)
    assert errores == [f"La carpeta de la aplicación {app} tiene contenido ajeno al núcleo: importante.txt"]
    assert (app / "importante.txt").read_text(encoding="utf-8") == "no se borra"
    (app / "importante.txt").unlink()
    errores = PR.preparar_sandbox(datos, app)  # su propia copia sí se rehace (el manifiesto vacío da su propio error)
    assert not [e for e in errores if "carpeta de la aplicación" in e] and (app / PR.MARCA_APP).is_file()


def test_preparar_sandbox_no_borra_un_nucleo_que_no_copio(tmp_path, monkeypatch):
    import sys as _sys
    monkeypatch.setattr(_sys, "path", list(_sys.path))
    datos = tmp_path / "montado"
    datos.mkdir()
    (datos / "x-manifiesto.json").write_text(json.dumps({"ficheros": {}}), encoding="utf-8")
    app = tmp_path / "proyecto"
    (app / "nucleo").mkdir(parents=True)
    (app / "nucleo" / "mio.py").write_text("# del usuario", encoding="utf-8")
    errores = PR.preparar_sandbox(datos, app)
    assert len(errores) == 1 and "no creó el arranque" in errores[0]
    assert (app / "nucleo" / "mio.py").read_text(encoding="utf-8") == "# del usuario"


def test_app_que_no_contiene_el_nucleo_cargado_da_sin_nucleo(m, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PREVENTA_APP", str(tmp_path / "vacia"))
    assert m.cli.main(["estado"]) == 4
    out = capsys.readouterr().out
    assert "no desde la carpeta de la aplicación" in out and "estado: SIN_NUCLEO" in out


# --- CLI con carpetas por argumento y montaje exacto ---------------------------------------------

@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def test_cli_carpetas_por_argumento_montaje_exacto(m, tmp_path, monkeypatch):
    for v in ("PREVENTA_DATOS", "PREVENTA_RAIZ"):
        monkeypatch.delenv(v)
    datos, trabajo = tmp_path / "entrada-b", tmp_path / "trabajo-b"
    datos.mkdir()
    shutil.copy(TRANSCRIPCION, datos / ADJUNTO)
    (datos / f"assistant-ZZ-{ADJUNTO}").write_bytes(b"con file_id: el montaje exacto no lo ve")
    globales = ["--trabajo", str(trabajo), "--datos", str(datos), "--montaje", "exacto"]
    m.raiz = trabajo
    m.run = lambda *a: Mundo.run(m, *globales, *a)
    rc, out = m.iniciar()
    assert rc == 0 and "ALTA: OK OF-KELVARA-001-A" in out and (trabajo / "estado.json").is_file()
    assert not (datos / "preventa").exists()
    rc, out = Mundo.run(m, "--montaje", "otro", "estado")
    assert rc == 2 and "Configuración de carpetas no válida" in out
    rc, out = Mundo.run(m, "estado", "--trabajo", str(trabajo))  # detrás del subcomando no se acepta
    assert rc == 2 and "Argumentos no válidos" in out


# --- API de biblioteca: lo mismo que la CLI -------------------------------------------------------

def _flujo(m) -> list[int]:
    rcs = []
    original = m.run
    m.run = lambda *a: (lambda r: rcs.append(r[0]) or r)(original(*a))
    m.hasta_lista()
    for revisor, tipo, comentario in (("Responsable comercial", "ENVIADA_REVISION", "verificar_paquete rc=0"),
                                      ("responsable de preventa", "APROBADA", "Revisado")):
        rcs.append(m.run("decision", "--linea", m.linea(revisor, tipo, comentario))[0])
    m.run = original
    return rcs


def test_api_flujo_completo_igual_que_la_cli(tmp_path, monkeypatch):
    import preventa_api as API
    cli = Mundo(tmp_path / "cli", monkeypatch) if (tmp_path / "cli").mkdir() is None else None
    rcs_cli, est_cli = _flujo(cli), cli.estado()
    api = Mundo(tmp_path / "api", monkeypatch) if (tmp_path / "api").mkdir() is None else None
    datos = tmp_path / "api" / "exacto"
    datos.mkdir()
    shutil.copy(TRANSCRIPCION, datos / ADJUNTO)  # sin file_id
    env = API.abrir(tmp_path / "api" / "trabajo", datos=datos, montaje="exacto")
    api.raiz = env.raiz
    resultados = []
    api.run = lambda *a: (lambda r: resultados.append(r) or (r.rc, r.salida))(API.ejecutar(env, a))
    rcs_api, est_api = _flujo(api), api.estado()
    assert rcs_api == rcs_cli and rcs_cli[-2:] == [0, 0] and all(r.subcomando for r in resultados)
    ts = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
    sin_ts = lambda e: ts.sub("TS", json.dumps(  # noqa: E731  (las marcas de hora cambian de una ejecución a otra)
        {k: v for k, v in e.items() if k not in ("control_versiones", "hash_contenido")}, sort_keys=True))
    assert ts.search(json.dumps(est_cli)) and sin_ts(est_api) == sin_ts(est_cli)
    final = resultados[-1]
    assert final.ok and final.error is None and final.estado == est_api and final.siguiente_paso
    assert "=== ESTADO PREVENTA ===" in final.salida


def test_api_funciones_por_subcomando_y_error_estructurado(tmp_path, monkeypatch):
    import preventa_api as API
    m = Mundo(tmp_path, monkeypatch)
    datos = tmp_path / "d"
    datos.mkdir()
    shutil.copy(TRANSCRIPCION, datos / ADJUNTO)
    env = API.abrir(tmp_path / "w", datos=datos)
    r = API.estado(env)
    assert r.rc == 0 and r.estado is None and r.subcomando == "estado"
    r = API.enrutar(env)
    assert r.rc == 2 and r.error["tipo"] == "EntradaInvalida" and "No hay estado.json" in r.error["mensaje"]
    r = API.iniciar(env, cliente="Kelvara Ensayos Industriales, S.A.", codigo_cliente="KELVARA", seqof="001",
                    titulo="-Asistente con un título que empieza por guion", transcripcion=ADJUNTO,
                    sensibles=["Kelvara", "Marta Olmedo"], nda_confirmado=True)
    assert r.ok and r.estado["codigo"] == "OF-KELVARA-001-A" and r.estado["carga"]["alta"]["titulo"].startswith("-")
    assert set(API.SUBCOMANDOS) == set(PR.MANEJADORES) and env.montaje == "exacto"
    monkeypatch.setenv("PREVENTA_MONTAJE", "sufijo")  # argumento > variable > «exacto»
    assert API.abrir(tmp_path / "w", datos=datos).montaje == "sufijo"
    assert API.abrir(tmp_path / "w", datos=datos, montaje="exacto").montaje == "exacto"
    assert m.raiz != env.raiz  # la API usa su propia carpeta, no la de las variables PREVENTA_*
