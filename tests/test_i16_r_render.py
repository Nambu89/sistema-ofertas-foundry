"""I1.6 · R · D15-5: `verificar_paquete.renderizar` robusto ante llamadas seguidas, sin tocar nunca una instancia de
PowerPoint ajena. Con dobles de procesos y de PowerShell (sin PowerPoint); la prueba real con COM va en
pruebas/I16/R/render_seguido.txt. Cada caso adverso con su resultado esperado (LES-G-096.6).
"""
from __future__ import annotations

import types

import pytest

import verificar_paquete as vp


class Procesos:
    """Lista de POWERPNT vivos que cambia en cada consulta (la última se repite)."""
    def __init__(self, *secuencia):
        self.secuencia, self.n = [set(s) for s in secuencia], 0

    def __call__(self):
        s = self.secuencia[min(self.n, len(self.secuencia) - 1)]
        self.n += 1
        return s


def _ps(salida="PID_PROPIO=4321\nTERMINADA_PROPIA\nRENDER_OK\n", rc=0, png=2):
    llamadas = []

    def ejecutar(args, env=None, **kw):
        llamadas.append(env)
        destino = vp.pathlib.Path(env["VP_DESTINO"])
        for i in range(png):
            (destino / f"diapositiva_{i + 1:02d}.png").write_bytes(b"png")
        return types.SimpleNamespace(stdout=salida, stderr="", returncode=rc)
    ejecutar.llamadas = llamadas
    return ejecutar


@pytest.fixture(autouse=True)
def pids_limpios(monkeypatch):
    monkeypatch.setattr(vp, "_PIDS_RENDER_PROPIOS", set())


def _render(tmp_path, procesos, ejecutar, espera_s=5.0):
    pptx = tmp_path / "x.pptx"
    pptx.write_bytes(b"pptx")
    return vp.renderizar(pptx, tmp_path / "png", espera_s=espera_s, ejecutar=ejecutar, procesos=procesos,
                         dormir=lambda s: None)


def test_sin_powerpoint_renderiza_y_anota_su_pid(tmp_path):
    ps = _ps()
    ok, msg = _render(tmp_path, Procesos(set()), ps)
    assert ok and msg.startswith("2 PNG") and vp._PIDS_RENDER_PROPIOS == {4321}, msg
    assert ps.llamadas[0]["VP_ESPERA_MS"] == "5000"


def test_llamada_seguida_espera_a_que_termine_su_propia_instancia(tmp_path):
    vp._PIDS_RENDER_PROPIOS.add(4321)
    procesos, ps = Procesos({4321}, {4321}, set()), _ps()
    ok, msg = _render(tmp_path, procesos, ps)
    assert ok and procesos.n == 3 and len(ps.llamadas) == 1, msg


def test_su_instancia_no_termina_no_arranca_otra_ni_la_cierra_desde_python(tmp_path):
    vp._PIDS_RENDER_PROPIOS.add(4321)
    ps = _ps()
    ok, msg = _render(tmp_path, Procesos({4321}), ps, espera_s=0.0)
    assert not ok and "sigue viva" in msg and not ps.llamadas, msg


@pytest.mark.parametrize("vivos", [{999}, {4321, 999}])
def test_una_instancia_ajena_es_ocupado_y_no_se_toca(tmp_path, vivos):
    vp._PIDS_RENDER_PROPIOS.add(4321)
    procesos, ps = Procesos(vivos), _ps()
    ok, msg = _render(tmp_path, procesos, ps)
    assert not ok and "ya está abierto" in msg and "no se usa ni se cierra" in msg and not ps.llamadas, msg
    assert procesos.n == 1                                             # ni espera: no es suya


@pytest.mark.parametrize("salida, rc, ok_esperado, texto", [
    ("OCUPADO\n", 3, False, "ya está abierto"),                         # apareció entre la consulta y el guion
    ("PID_PROPIO=4321\nCERRADA_PROPIA\nRENDER_OK\n", 0, True, "se cerró"),
    ("PID_PROPIO=4321\nSIGUE_PROPIA\nRENDER_OK\n", 0, True, "sigue viva tras intentar cerrarla"),
    ("PID_PROPIO=4321\nAJENAS=1\nRENDER_OK\n", 0, True, "alguien abrió otra presentación"),
    ("PID_PROPIO=AMBIGUO 2\nRENDER_OK\n", 0, True, "no se pudo identificar la instancia propia"),
    ("PID_PROPIO=4321\n", 1, False, "render fallido rc=1"),
    ("PID_PROPIO=4321\nTERMINADA_PROPIA\n", 0, False, "render fallido rc=0"),   # sin RENDER_OK no vale
])
def test_cada_salida_del_guion_con_su_resultado(tmp_path, salida, rc, ok_esperado, texto):
    ok, msg = _render(tmp_path, Procesos(set()), _ps(salida, rc))
    assert ok is ok_esperado and texto in msg, msg


def test_ambiguo_no_anota_pid_y_sin_png_no_es_ok(tmp_path):
    ok, _ = _render(tmp_path, Procesos(set()), _ps("PID_PROPIO=AMBIGUO 2\nRENDER_OK\n"))
    assert ok and vp._PIDS_RENDER_PROPIOS == set()
    otra = tmp_path / "otra"
    otra.mkdir()
    ok, msg = _render(otra, Procesos(set()), _ps(png=0))
    assert not ok and msg.startswith("0 PNG"), msg


def test_el_guion_solo_cierra_su_instancia():
    g = vp._PS_RENDER
    assert "Stop-Process" not in g and "taskkill" not in g.lower()
    assert g.count(".Kill()") == 1 and "$propio.Kill()" in g          # solo el proceso arrancado por él
    assert "if ($propio -and $ajenas -eq 0) { $pp.Quit() }" in g      # sin instancia propia o con otra presentación, no
    assert "$todos.Count -eq 1 -and $com.Count -eq 1" in g             # propia: la única viva y lanzada por COM
    assert "/AUTOMATION" in g and "-Embedding" in g and '"' not in g  # sin comillas dobles en -Command
    # la identificación va dentro de try/catch: si Get-CimInstance falla, no hay instancia propia (Revisión, 3.ª)
    ini = g.index("$propio = $null" + chr(10) + "try {")
    cim, fin = g.index("Get-CimInstance"), g.index("} catch { Write-Output ('PID_PROPIO=AMBIGUO error")
    assert ini < cim < fin < g.index("$pp.Quit()")


def test_pids_powerpoint_lee_tasklist(monkeypatch):
    salida = '"POWERPNT.EXE","4321","Console","1","120.000 K"\n"POWERPNT.EXE","77","Console","1","1 K"\n'
    monkeypatch.setattr(vp.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=salida, returncode=0))
    assert vp.pids_powerpoint() == {4321, 77}
    monkeypatch.setattr(vp.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        stdout="INFORMACIÓN: no hay tareas ejecutándose que coincidan con los criterios especificados.\n", returncode=0))
    assert vp.pids_powerpoint() == set()
