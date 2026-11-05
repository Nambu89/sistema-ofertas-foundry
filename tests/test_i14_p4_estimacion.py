"""P4 de I1.4: la regla de estimación vive en el núcleo (decisión del comercial del 10-10-2026).

PM = máx(8 h, ⌈15 % de las horas técnicas⌉) y Gantt con los perfiles distintos de cada fase en paralelo:
semanas = máx(1, ⌈horas de la fase / (40 × perfiles)⌉). Se prueba con la solicitud real de Brezalia (paquete de B
del 10-10-2026) y con el generador canónico REAL, sin modificarlo, que exige --verificar rc 0. Sin red.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import subprocess
import sys
import zipfile
from datetime import date
from decimal import Decimal

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))
from nucleo import esquema, estimacion as N  # noqa: E402

_WINDOWS = pathlib.Path("C:/Users/usuario/Proyectos")  # solo como último recurso, si existe
_PROYECTOS = pathlib.Path((os.environ.get("PREVENTA_PROYECTOS") or "").strip() or pathlib.Path.home() / "Proyectos")
_PROYECTOS = _PROYECTOS if _PROYECTOS.is_dir() or not _WINDOWS.is_dir() or (os.environ.get("PREVENTA_PROYECTOS") or "").strip() else _WINDOWS  # fijada: se respeta
CANONICO = _PROYECTOS / "_templates" / "estimacion"
TARIFA = RAIZ / "tests" / "insumos" / "rate-card.sintetica.json"
BREZALIA = RAIZ / "pruebas" / "I13" / "ARREGLOS" / "REAL_B" / "descargas" / "OF-BREZALIA-001-A-Paquete.zip"
HOY = date(2026, 10, 10)
con_generador = pytest.mark.skipif(not (CANONICO / N.GENERADOR).is_file(), reason="sin generador canónico")


def _brezalia() -> dict:
    with zipfile.ZipFile(BREZALIA) as z:
        return json.loads(z.read("estado.json"))


def _tarifa() -> dict:
    return N.cargar_tarifa(TARIFA)


@pytest.mark.parametrize("tecnicas, pm", [(0, 8), (53, 8), (54, 9), (256, 39), (100, 15), (12.5, 8), (1000, 150)])
def test_pm_es_maximo_de_8_y_15_por_ciento_redondeado_arriba(tecnicas, pm):
    assert N.horas_pm(tecnicas) == pm


@pytest.mark.parametrize("horas, perfiles, semanas", [(0, 1, 1), (40, 1, 1), (41, 1, 2), (100, 1, 3), (100, 2, 2),
                                                      (100, 3, 1), (240, 2, 3), (Decimal("80.01"), 2, 2)])
def test_semanas_con_perfiles_en_paralelo(horas, perfiles, semanas):
    assert N.semanas_fase(horas, perfiles) == semanas


@pytest.mark.parametrize("malo", [0, -1, True, 1.5])
def test_semanas_rechaza_un_numero_de_perfiles_no_valido(malo):
    with pytest.raises(ValueError):
        N.semanas_fase(10, malo)


def test_brezalia_con_la_regla_nueva():
    est, tarifa = _brezalia(), _tarifa()
    entrada, avisos = N.componer_entrada(est, N.hitos_tarifa(tarifa), HOY)
    propuestas = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]["tareas_propuestas"]
    tecnicas = sum(t["horas_base"] for t in propuestas)
    # I1.5 (VER14-10, CAMBIOS-I15-D §4): las asunciones con jerga se recomponen y se dice (nada se pierde en silencio)
    assert tecnicas == 256 and avisos and all("recompuesta por el código" in a for a in avisos), avisos
    pm = [t for t in entrada["tareas"] if t["id"].startswith("PM-")]
    assert [(t["id"], t["tecnicas_h"], t["reuniones_h"]) for t in pm] == [("PM-01", 39, 11)]  # ⌈38,4⌉ = 39
    # Cada fase de Brezalia tiene un solo perfil: ⌈horas de la fase / 40⌉ semanas, una fase detrás de otra.
    assert [g["semanas"] for g in entrada["gantt"]] == [[1], [2, 3], [4, 5], [6, 7], [8, 9], [10, 11], list(range(1, 12))]
    assert entrada["duracion_semanas"] == 11 and entrada["fecha"] == "2026-10-10"
    assert esquema.validar(entrada, esquema.cargar("estimacion_entrada")) == []
    assert N.validar_entrada(entrada, est, tarifa, None) == []
    resumen = N.calcular(entrada, tarifa)
    assert (resumen["pm_h"], resumen["horas_total"], resumen["precio_cerrado_eur"]) == ("58.00", "391.00", "24797.50")


def test_perfiles_distintos_de_una_fase_trabajan_en_paralelo():
    est = _brezalia()
    resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    for t in resp["tareas_propuestas"][1:3]:  # T-02 y T-03 pasan a la fase de T-01, con perfiles distintos
        t["fase"] = resp["tareas_propuestas"][0]["fase"]
    entrada, _ = N.componer_entrada(est, N.hitos_tarifa(_tarifa()), HOY)
    # T-01 40 h (28+6+6), T-02 62 h (48+10+4) y T-03 71 h (56+11+4): 173 h con 3 perfiles -> ⌈173/120⌉ = 2 semanas.
    assert entrada["gantt"][0]["semanas"] == [1, 2] and entrada["gantt"][1]["semanas"] == [3, 4]
    assert N.validar_entrada(entrada, est, _tarifa(), None) == []


def test_pm_por_encima_de_400_h_se_reparte_en_tareas_pm():
    est = _brezalia()
    for t in est["carga"]["respuestas_expertos"]["azure"]["respuesta"]["tareas_propuestas"]:
        t["horas_base"] = 400  # 6 × 400 = 2.400 h técnicas -> PM 360 h (cabe en una tarea)
    entrada, _ = N.componer_entrada(est, N.hitos_tarifa(_tarifa()), HOY)
    assert [t["tecnicas_h"] for t in entrada["tareas"] if t["id"].startswith("PM-")] == [360]
    pm = N._tareas_pm(450, 90)
    assert [(t["id"], t["tecnicas_h"], t["reuniones_h"]) for t in pm] == [("PM-01", 400, 80), ("PM-02", 50, 10)]


def test_ajuste_decidido_y_textos_que_no_caben_se_declaran():
    est = _brezalia()
    resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    resp["supuestos"] = [{"id": "S-01", "texto": "=SUMA(A1)", "confianza": "BAJA", "hechos": []},
                         {"id": "S-02", "texto": "Se reserva contingencia", "confianza": "BAJA", "hechos": []}]
    entrada, avisos = N.componer_entrada(est, N.hitos_tarifa(_tarifa()), HOY, (Decimal("-1500.00"), "Cliente estratégico"))
    assert entrada["ajuste_comercial_eur"] == -1500.0 and entrada["ajuste_comercial_motivo"] == "Cliente estratégico"
    assert entrada["asunciones"] == [] and len(avisos) == 2 and "fórmula" in avisos[0] and "contingencia" in avisos[1]


def test_sin_tareas_o_sin_alta_falla_en_alto():
    est = _brezalia()
    est["carga"]["respuestas_expertos"] = {}
    with pytest.raises(ValueError, match="tareas_propuestas"):
        N.componer_entrada(est, [], HOY)
    est = _brezalia()
    est["carga"]["alta"]["titulo"] = ""
    with pytest.raises(ValueError, match="título"):
        N.componer_entrada(est, [], HOY)


@con_generador
def test_brezalia_con_el_generador_real_y_verificar(tmp_path):
    est, tarifa = _brezalia(), _tarifa()
    antes = copy.deepcopy(est)
    entrada, _ = N.componer_entrada(est, N.hitos_tarifa(tarifa), HOY)
    rutas = N.RutasGenerador(generador=CANONICO / N.GENERADOR, plantilla=CANONICO / N.PLANTILLA, rate_card=TARIFA,
                             base_tmp=tmp_path / "base")
    r = N.estimar(est, entrada, tarifa, rutas, tmp_path / "salida", None)
    assert r.resumen["precio_cerrado_eur"] == "24797.50" and "--verificar" in r.salida_generador
    assert est["carga"]["estimacion"]["entrada"] == entrada and antes["carga"]["estimacion"] != est["carga"]["estimacion"]
    v = subprocess.run([sys.executable, str(CANONICO / N.GENERADOR), "--verificar", str(r.ruta_xlsx)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert v.returncode == 0, v.stdout + v.stderr
    assert N.comparar(r.resumen, N.leer_xlsx(r.ruta_xlsx), "xlsx") == []


def test_b_usa_la_misma_regla_que_el_nucleo():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "estimacion_entrada_b", RAIZ / "hosted" / "preventa_hosted" / "estimacion_entrada.py")
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    est, hitos = _brezalia(), N.hitos_tarifa(_tarifa())
    assert b.construir(est, hitos, HOY) == N.componer_entrada(est, hitos, HOY)


def _verificada_brezalia(base: pathlib.Path) -> pathlib.Path:
    """El estado real de Brezalia devuelto a VERIFICADA (sin estimación), guardado en <base>/trabajo."""
    from nucleo import estado as E, hashes
    from tests.test_i14_p4_turno_restaurar import _completar_campo
    est = _brezalia()
    _completar_campo(est)  # el esquema del verificador gana «campo» en esta tanda (otro papel)
    est["estado"] = "VERIFICADA"
    est["carga"]["estimacion"] = est["carga"]["textos_cliente"] = est["artefactos"]["xlsx_estimacion"] = None
    est["hash_contenido"] = hashes.hash_contenido(est)
    for d in ("trabajo", "datos"):
        (base / d).mkdir()
    E.guardar(est, base / "trabajo")
    return base / "trabajo"


@con_generador
def test_estimar_de_a_compone_la_entrada_sin_json_del_coordinador(tmp_path, monkeypatch):
    for v in ("PREVENTA_CATALOGO", "PREVENTA_RATE_CARD", "PREVENTA_GENERADOR", "PREVENTA_PLANTILLA"):
        monkeypatch.delenv(v, raising=False)
    import preventa_api as P
    trabajo = _verificada_brezalia(tmp_path)
    env = P.abrir(str(trabajo), datos=str(tmp_path / "datos"), tmp=str(tmp_path / "tmp"), montaje="exacto")
    r = P.estimar(env)
    assert r.rc == 0, r.salida
    assert "ENTRADA DE ESTIMACIÓN compuesta por el núcleo" in r.salida and "precio cerrado 24797.50 EUR" in r.salida
    assert r.siguiente_paso.endswith("paquete")
    escrita = json.loads((trabajo / "entrada" / "estimacion_entrada.json").read_text(encoding="utf-8"))
    est = json.loads((trabajo / "estado.json").read_text(encoding="utf-8"))
    assert escrita == est["carga"]["estimacion"]["entrada"] and est["carga"]["textos_cliente"] is not None
    assert [t["tecnicas_h"] for t in escrita["tareas"] if t["id"] == "PM-01"] == [39]


def test_textos_que_no_son_texto_o_son_cortos_se_declaran():
    est = _brezalia()
    est["carga"]["respuestas_expertos"]["azure"]["respuesta"]["supuestos"] = [
        {"id": "S-01", "texto": 7}, {"id": "S-02", "texto": "abc"}, {"id": "S-03", "texto": "  "}, {"id": "S-04"}]
    entrada, avisos = N.componer_entrada(est, N.hitos_tarifa(_tarifa()), HOY)
    # I1.5 (CAMBIOS-I15-D §4): textos_cliente.asunciones_estimacion declara las cuatro; ninguna pasa ni se pierde callada
    assert entrada["asunciones"] == [] and len(avisos) == 4, avisos
    assert all("asunción omitida (tiene menos de 5 caracteres)" in a for a in avisos)
