"""Arreglos I1.7 · PR17-6: la versión siguiente a una DEVUELTA ya no empieza de cero. El brief de su ronda 1 lleva la
propuesta devuelta (la que guardó el código en la decisión DEVUELTA), detrás de los comentarios del revisor; la puerta la
recompone en local y rechaza una alterada. Un brief guardado antes del arreglo (sin la sección) se respeta."""
from __future__ import annotations

import copy
import hashlib
import types

import pytest

from tests.test_i15_r_brief_devuelta import CAB, _devolver
from tests.test_i1_estado_comun import TRANSCRIPCION, Mundo

PROP = "## Propuesta de la versión A devuelta"


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def _resellar(b: dict, cuerpo_nuevo: str) -> None:
    cab = b["texto"].split("\n---\n", 1)[0]
    cab = "\n".join(x if not x.startswith("sha256_cuerpo: ") else
                    f"sha256_cuerpo: {hashlib.sha256(cuerpo_nuevo.encode()).hexdigest()}" for x in cab.split("\n"))
    b["texto"] = cab + "\n---\n" + cuerpo_nuevo


def _puerta(estado):
    import verificar_paquete as vp
    return vp.c_brief(types.SimpleNamespace(estado=estado, carga=estado["carga"], transcripcion=TRANSCRIPCION))


def test_el_brief_r1_de_la_version_b_lleva_la_propuesta_devuelta(m):
    from nucleo import brief
    _devolver(m, "Revisad el nivel de AI Search y el consumo de Foundry.")
    assert m.run("enrutar")[0] == 0
    est = m.estado()
    vb, va = est["carga"]["briefs"][-1], est["carga"]["briefs"][0]
    assert vb["brief_id"].endswith("-B-AZ-R1") and PROP not in va["texto"]
    lineas = vb["texto"].split("\n")
    i, j = (next(k for k, ln in enumerate(lineas) if ln.startswith(x)) for x in (CAB, PROP))
    assert j == i + 2                                     # justo detrás del único comentario
    esperadas = brief.lineas_propuesta_devuelta(est)
    vd = est["decisiones"][-1]["version_devuelta"]
    assert len(esperadas) == len(vd["componentes"]) + len(vd["precios"]) > 0
    assert lineas[j + 1:j + 1 + len(esperadas)] == esperadas
    assert any(x.startswith("- Componente az-ai-search · nivel o modelo ") for x in esperadas)
    assert any(x.startswith("- Consumo az-ai-search · ") and x.endswith(" al mes") for x in esperadas)
    c = _puerta(est)
    assert not any("PR17-6" in d for d in c.detalles), c.detalles


def test_la_puerta_rechaza_la_propuesta_alterada(m):
    _devolver(m, "Revisad el nivel de AI Search.")
    assert m.run("enrutar")[0] == 0
    roto = copy.deepcopy(m.estado())
    b = roto["carga"]["briefs"][-1]
    cuerpo = b["texto"].split("\n---\n", 1)[1]
    linea = next(ln for ln in cuerpo.split("\n") if ln.startswith("- Consumo "))
    _resellar(b, cuerpo.replace(linea, linea.replace(" al mes", "0 al mes")))
    c = _puerta(roto)
    # REVERIF17-4 (I1.8): en la ronda 1 de la versión vigente se compara el cuerpo entero (mensaje del brief completo)
    assert any("PR17-6" in d and ("no es la que compone el código" in d or "no es el que compone el código" in d)
               for d in c.detalles), c.detalles


def test_un_brief_guardado_sin_la_seccion_se_respeta(m):
    from nucleo import brief
    _devolver(m, "Revisad el nivel de AI Search.")
    assert m.run("enrutar")[0] == 0
    est = m.estado()
    viejo = copy.deepcopy(est)
    vb = viejo["carga"]["briefs"][-1]
    lineas = vb["texto"].split("\n---\n", 1)[1].split("\n")
    j = next(k for k, ln in enumerate(lineas) if ln.startswith(PROP))
    n = len(brief.lineas_propuesta_devuelta(est))
    _resellar(vb, "\n".join(lineas[:j] + lineas[j + 1 + n:]))
    assert brief.generar(viejo, vb["perfiles_permitidos"], vb["catalogo_sha256"]).texto == vb["texto"]
    otro = copy.deepcopy(est)
    otro["carga"]["briefs"][-1]["texto"] += "\n- añadido"
    from nucleo.errores import IntegridadRota
    with pytest.raises(IntegridadRota, match="otro texto"):
        brief.generar(otro, vb["perfiles_permitidos"], vb["catalogo_sha256"])


def test_sin_resumen_en_la_decision_no_hay_seccion():
    from nucleo import brief
    est = {"version": "B", "decisiones": [{"id": "D-002", "tipo": "DEVUELTA", "version": "A", "revisor": "Responsable de preventa",
                                           "comentarios": "x"}]}
    assert brief.lineas_propuesta_devuelta(est) == []
    est["decisiones"][0]["version_devuelta"] = {"componentes": [{"clave": "az-storage", "sku": "Hot", "region": "swedencentral"}],
                                                "precios": [{"clave": "az-storage · hot-lrs-datos", "cantidad_mensual": 6}]}
    # REVERIF17-5 (I1.8): la cantidad lleva su unidad (de la instantánea) y el formato español; el formato 1 (arreglos
    # de I1.7) se conserva para respetar un brief ya guardado
    inst = {"plantillas": {"az-storage/hot-lrs-datos": {"unidad": "1 GB/Month", "meterName": "Hot LRS Data Stored"}}}
    assert brief.lineas_propuesta_devuelta(est, instantanea=inst) == [
        "- Componente az-storage · nivel o modelo Hot · región swedencentral", "- Consumo az-storage · hot-lrs-datos: 6 GB al mes"]
    assert brief.lineas_propuesta_devuelta(est, formato=1) == [
        "- Componente az-storage · nivel o modelo Hot · región swedencentral", "- Consumo az-storage · hot-lrs-datos: 6 al mes"]
    assert brief.lineas_propuesta_devuelta({**est, "version": "A"}) == []
