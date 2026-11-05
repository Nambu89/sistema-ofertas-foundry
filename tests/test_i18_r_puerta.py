"""I1.8 · papel R · puerta: REVERIF17-4 (brief de la ronda 1 entero), REVERIF17-5 (formato de la propuesta, también el
anterior) y PR17-6 parte 2 (lo enviado tras un rechazo). Con el núcleo real en proceso y casos adversos."""
from __future__ import annotations

import copy
import hashlib
import types

import pytest

from tests.test_i15_r_brief_devuelta import _devolver
from tests.test_i17_arr_brief import PROP, _puerta, _resellar
from tests.test_i18_r_nucleo import _rechazar
from tests.test_i1_estado_comun import Mundo, ejemplo


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def _vb(m):
    _devolver(m, "Revisad el nivel de AI Search y el consumo de Foundry.")
    assert m.run("enrutar")[0] == 0
    est = copy.deepcopy(m.estado())
    return est, est["carga"]["briefs"][-1]


def _cuerpo(b):
    return b["texto"].split("\n---\n", 1)[1]


def _r4(c):
    return [d for d in c.detalles if "REVERIF17-4" in d]


def test_brief_r1_de_b_casa_entero(m):
    est, _ = _vb(m)
    c = _puerta(est)
    assert not _r4(c) and not any("PR17-6" in d for d in c.detalles if d.startswith("FALLA")), c.detalles


def test_quitar_la_propuesta_da_falla(m):
    est, b = _vb(m)
    lineas = _cuerpo(b).split("\n")
    j = next(k for k, ln in enumerate(lineas) if ln.startswith(PROP))
    k = next((i for i in range(j + 1, len(lineas)) if lineas[i].startswith("## ")), len(lineas))
    _resellar(b, "\n".join(lineas[:j] + lineas[k:]))
    assert any("falta la propuesta" in d for d in _r4(_puerta(est))), _puerta(est).detalles


def test_mover_la_propuesta_da_falla(m):
    est, b = _vb(m)
    lineas = _cuerpo(b).split("\n")
    j = next(k for k, ln in enumerate(lineas) if ln.startswith(PROP))
    k = next((i for i in range(j + 1, len(lineas)) if lineas[i].startswith("## ")), len(lineas))
    bloque, resto = lineas[j:k], lineas[:j] + lineas[k:]
    _resellar(b, "\n".join(bloque + resto))
    c = _puerta(est)
    assert c.estado == "FALLA" and any("no es el que compone el código" in d for d in _r4(c)), c.detalles


def test_cambiar_un_requisito_del_cuerpo_da_falla(m):
    est, b = _vb(m)
    cuerpo = _cuerpo(b)
    _resellar(b, cuerpo.replace("## Necesidad\nObjetivo: ", "## Necesidad\nObjetivo: (cambiado) ", 1))
    assert _r4(_puerta(est)), _puerta(est).detalles


def test_la_propuesta_con_el_formato_de_i17_se_admite_con_nota(m):
    from nucleo import brief
    est, b = _vb(m)
    nuevas = brief.lineas_propuesta_devuelta(est)
    viejas = brief.lineas_propuesta_devuelta(est, formato=1)
    assert nuevas != viejas and any(" al mes" in x and "Consumo" in x for x in viejas)
    cuerpo = _cuerpo(b)
    for a, v in zip(nuevas, viejas):
        cuerpo = cuerpo.replace(a + "\n", v + "\n", 1) if a + "\n" in cuerpo else cuerpo.replace(a, v, 1)
    _resellar(b, cuerpo)
    c = _puerta(est)
    assert not _r4(c) and any("REVERIF17-5" in d for d in c.detalles), c.detalles


def _ctx(est, fecha):
    return types.SimpleNamespace(estado=est, carga=est["carga"], manifiesto={"generado_ts": f"{fecha}T10:00:00+02:00"})


def _sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def test_envio_esperado_tras_un_rechazo(m):
    import verificar_paquete as vp
    from nucleo import brief
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    _rechazar(m)
    r = m.entrada("respuesta_buena.json", ejemplo("respuesta_experto"))
    assert m.run("registrar-experto", "--experto", "azure", "--respuesta", r)[0] == 0
    est = m.estado()
    b = est["carga"]["briefs"][-1]
    reintento = brief.texto_envio(est, b, hasta_n=brief.control_registro_experto(est))
    assert reintento != b["texto"]
    c = vp.Comprobacion("procedencia_a2a", "x")
    assert vp._envios_esperados(_ctx(est, "2026-10-14"), c, b["brief_id"], b["texto"]) == {_sha(reintento)}
    c = vp.Comprobacion("procedencia_a2a", "x")      # paquete anterior al arreglo: también el brief idéntico, con nota
    assert vp._envios_esperados(_ctx(est, "2026-10-13"), c, b["brief_id"], b["texto"]) == {_sha(reintento), _sha(b["texto"])}
    assert any("PR17-6 parte 2" in d for d in c.detalles)


def test_envio_esperado_sin_rechazo_y_sin_control(m):
    import verificar_paquete as vp
    m.hasta_verificacion()
    est = m.estado()
    b = est["carga"]["briefs"][-1]
    c = vp.Comprobacion("procedencia_a2a", "x")
    assert vp._envios_esperados(_ctx(est, "2026-10-14"), c, b["brief_id"], b["texto"]) == {_sha(b["texto"])}
    roto = copy.deepcopy(est)
    roto["control_versiones"] = [x for x in roto["control_versiones"] if x["subcomando"] != "registrar-experto"]
    c = vp.Comprobacion("procedencia_a2a", "x")
    vp._envios_esperados(_ctx(roto, "2026-10-14"), c, b["brief_id"], b["texto"])
    assert c.estado == "FALLA" and any("control que registró" in d for d in c.detalles)
