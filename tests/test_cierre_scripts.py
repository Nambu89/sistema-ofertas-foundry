"""Pruebas sin red de publicar_rate_card (P2), _baseline/salida.py (R1) y comparar.py (R2)."""
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def _cargar(ruta, nombre):
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------- P2: evidencia intermedia antes de releer
def test_publicar_deja_el_id_en_disco_si_falla_la_relectura(monkeypatch, tmp_path):
    from tarifa import publicar_rate_card as prc
    vistos = {}

    class Cli:
        registro, cfg = [], {"protegidos": {"toolbox": "t"}}
    monkeypatch.setattr(prc, "RAIZ", tmp_path)
    monkeypatch.setattr(prc, "ClienteFoundry", Cli)
    monkeypatch.setattr(prc.rc, "cargar_fuente", lambda: {})
    monkeypatch.setattr(prc.rc, "datos_skill", lambda f: {"perfiles": 7})
    monkeypatch.setattr(prc.rc, "construir_instrucciones", lambda d: "cuerpo")
    monkeypatch.setattr(prc.rc, "validar", lambda cuerpo: {"perfiles": 7})
    monkeypatch.setattr(prc.rc, "quitar_front_matter", lambda md: md)
    monkeypatch.setattr(prc.acceso, "obtener_skill", lambda c: {"default_version": "3"})
    monkeypatch.setattr(prc.acceso, "listar_versiones", lambda c: [{"version": "3"}])
    monkeypatch.setattr(prc.acceso, "descargar_skill_md", lambda c, v=None: "cuerpo viejo")
    monkeypatch.setattr(prc, "buscar_version_igual", lambda c, vs, o: None)
    monkeypatch.setattr(prc.acceso, "crear_version",
                        lambda c, d, o: {"id": "skill_x:9", "name": "rate-card", "version": 9})

    def fijar(c, v):  # cuando se fija el default, el id de la versión creada ya está en disco
        vistos["al_fijar"] = [json.loads(p.read_text(encoding="utf-8"))
                              for p in (tmp_path / "salidas").glob("*.json")]
        return {"default_version": v}
    monkeypatch.setattr(prc.acceso, "fijar_default", fijar)

    def releer(*a):
        raise prc.rc.TarifaInvalida("relectura distinta")
    monkeypatch.setattr(prc, "releer_y_comprobar", releer)
    with pytest.raises(prc.rc.TarifaInvalida):
        prc.main([])
    assert vistos["al_fijar"][0]["creada"]["id"] == "skill_x:9"
    final = [json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "salidas").glob("*.json")]
    assert len(final) == 1 and final[0]["creada"]["version"] == 9
    assert final[0]["estado"] == "FALLO en la relectura" and "relectura distinta" in final[0]["fallo_relectura"]
    assert final[0]["fijar_default"] == {"default_version": "9"}


# ----------------------------------------------------- R1: crear frente a sobrescribir
# Imita a los dos scripts reales: piden destino a salida.py al importar, crean la carpeta y escriben.
ESCRITOR = ("import pathlib\nimport salida\nOUT = salida.destino(salida.DATOS)\n"
            "OUT.mkdir(parents=True, exist_ok=True)\n"
            "(OUT / ('{p}_' + pathlib.Path(__file__).name + '.json')).write_text('{{}}')\n")


def _base_temporal(tmp_path):
    base = tmp_path / "_baseline"
    base.mkdir()
    shutil.copy(RAIZ / "_baseline" / "salida.py", base / "salida.py")
    for nombre, pref in (("obtener_baseline.py", "agente"), ("obtener_arm.py", "arm")):
        (base / nombre).write_text(ESCRITOR.format(p=pref), encoding="utf-8")
    return base


def _correr(base, script, *args):
    return subprocess.run([sys.executable, str(base / script), *args], cwd=base,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_creacion_completa_desde_cero_en_dos_scripts(tmp_path):
    base = _base_temporal(tmp_path)
    r1 = _correr(base, "obtener_baseline.py")
    assert r1.returncode == 0, r1.stderr
    assert (base / ".creacion_datos.json").is_file()
    r2 = _correr(base, "obtener_arm.py")
    assert r2.returncode == 0, r2.stderr
    assert sorted(p.name for p in (base / "datos").iterdir()) == [
        "agente_obtener_baseline.py.json", "arm_obtener_arm.py.json"]
    assert not (base / ".creacion_datos.json").exists()  # creación cerrada
    for script in ("obtener_baseline.py", "obtener_arm.py"):  # ya no se sobrescribe
        r = _correr(base, script)
        assert r.returncode != 0 and "ya existe" in r.stderr
    assert _correr(base, "obtener_arm.py", "--sobrescribir-linea-base").returncode == 0


def test_repetir_el_mismo_script_durante_la_creacion_es_sobrescribir(tmp_path):
    base = _base_temporal(tmp_path)
    assert _correr(base, "obtener_baseline.py").returncode == 0
    r = _correr(base, "obtener_baseline.py")
    assert r.returncode != 0 and "ya escribió" in r.stderr


def test_marca_vieja_con_carpeta_vacia_no_bloquea(tmp_path):
    base = _base_temporal(tmp_path)
    (base / "datos").mkdir()
    (base / ".creacion_datos.json").write_text('{"escritos": ["obtener_baseline.py"]}', encoding="utf-8")
    assert _correr(base, "obtener_baseline.py").returncode == 0


# ----------------------------------------------------------- R2: código de salida de comparar
COMPARAR = RAIZ / "pruebas" / "I0" / "VERIF" / "scripts" / "comparar.py"


def _capturas(tmp_path):
    cmp_mod = _cargar(COMPARAR, "comparar_r2")
    base, ahora = tmp_path / "base", tmp_path / "ahora"
    for d in (base, ahora):
        d.mkdir()
        for n in cmp_mod.PROTEGIDOS + ["skill_rate-card.json", "skill_otra.json"]:
            (d / n).write_text(json.dumps({"respuesta": {"n": n, "v": 1}}), encoding="utf-8")
        (d / cmp_mod.ZIP_V3).write_bytes(b"PK-v3")
    from tests import comparar_comun  # VPROT-7 (I1.9): comparar.py también compara conexiones y agentes
    comparar_comun.escribir_listas(cmp_mod, base, ahora)
    return cmp_mod, base, ahora


def test_comparar_rc0_solo_si_todo_coincide(tmp_path, capsys):
    cmp_mod, base, ahora = _capturas(tmp_path)
    assert cmp_mod.principal([str(ahora), "--base", str(base)]) == 0
    (ahora / "skill_rate-card.json").write_text('{"respuesta": {"v": 4}}', encoding="utf-8")
    assert cmp_mod.principal([str(ahora), "--base", str(base)]) == 0  # rate-card no cuenta
    assert "TODO COINCIDE" in capsys.readouterr().out


@pytest.mark.parametrize("estropear", ["protegido", "skill", "zip", "falta", "json_roto", "skill_nueva"])
def test_comparar_rc1_con_diferencias(tmp_path, estropear):
    cmp_mod, base, ahora = _capturas(tmp_path)
    if estropear == "protegido":
        (ahora / "arm_cuenta.json").write_text('{"respuesta": {"v": 2}}', encoding="utf-8")
    elif estropear == "skill":
        (ahora / "skill_otra.json").write_text('{"respuesta": {"v": 2}}', encoding="utf-8")
    elif estropear == "zip":
        (ahora / cmp_mod.ZIP_V3).write_bytes(b"PK-otro")
    elif estropear == "skill_nueva":  # solo existe en la captura nueva
        (ahora / "skill_nueva.json").write_text('{"respuesta": {}}', encoding="utf-8")
    elif estropear == "falta":
        (ahora / "toolbox_toolbox-ajena-ejemplo.json").unlink()
    else:
        (ahora / "arm_proyecto.json").write_text("{roto", encoding="utf-8")
    assert cmp_mod.principal([str(ahora), "--base", str(base)]) == 1


def test_comparar_como_script_devuelve_el_codigo(tmp_path):
    _, base, ahora = _capturas(tmp_path)
    ok = subprocess.run([sys.executable, str(COMPARAR), str(ahora), "--base", str(base)],
                        capture_output=True, text=True, encoding="utf-8")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    (ahora / "arm_cuenta.json").write_text('{"respuesta": {}}', encoding="utf-8")
    mal = subprocess.run([sys.executable, str(COMPARAR), str(ahora), "--base", str(base)],
                         capture_output=True, text=True, encoding="utf-8")
    assert mal.returncode == 1 and "HAY DIFERENCIAS" in mal.stdout
    misma = subprocess.run([sys.executable, str(COMPARAR), str(base), "--base", str(base)],
                           capture_output=True, text=True, encoding="utf-8")
    assert misma.returncode != 0 and "propia línea base" in misma.stderr
