"""I1.7, papel E: cada rotura del catálogo nuevo la detecta problemas_catalogo, y derivar.main no deriva (rc 2)."""
from __future__ import annotations

import copy
import json

import pytest

from catalogo import derivar
from catalogo import plantillas_precio as pp
from tests.i17_e_comun import ARGS_EFECTIVO, PROPUESTO, RUTA_PROPUESTO, VIGENTE_ADMITE

CAT = derivar.cargar()


def _foundry(c):
    return next(x for x in c["componentes"] if x["id"] == "az-foundry")


def _supuesto_suma_mal(c):
    c["casos_uso"][0]["factores"][1]["desglose"][0]["valor"] += 1


def _oficial_suma_de_mas(c):
    c["casos_uso"][0]["factores"][0]["desglose"][0]["valor"] += 5000


def _factor_desconocido(c):
    _foundry(c)["plantillas_precio"][0]["factor_estandar"] = "asistente_rag.no_existe"


def _factor_en_tiempo(c):
    s = next(x for x in c["componentes"] if x["id"] == "az-ai-search")
    s["plantillas_precio"][0]["factor_estandar"] = "bot.mensajes_por_consulta"


def _modelo_sin_ciclo(c):
    c["ciclo_vida_modelos"] = [x for x in c["ciclo_vida_modelos"] if x["modelo"] != "gpt-6-sol"]


def _plantilla_sin_modelo(c):
    _foundry(c)["plantillas_precio"][3].pop("modelo")


def _por_defecto_retirado(c):
    next(p for p in _foundry(c)["plantillas_precio"] if p["id"] == "gpt-5-entrada")["por_defecto"] = True


def _incluye_a_si_mismo(c):
    next(x for x in c["componentes"] if x["id"] == "az-log-analytics")["incluye"][0]["catalogo_id"] = "az-log-analytics"


def _por_defecto_incoherente(c):
    c["modelo_por_defecto"]["plantillas"] = ["gpt-6-sol-entrada", "gpt-6-sol-salida"]


def _retirada_antes_de_ga(c):
    c["ciclo_vida_modelos"][0]["retirada"] = "2020-01-01"


def _arquitectura_de_servicio(c):
    c["arquitecturas_referencia"][0]["url"] = "https://learn.microsoft.com/azure/search/search-what-is-azure-search"


def _arquitectura_repetida(c):
    c["arquitecturas_referencia"].append(dict(c["arquitecturas_referencia"][0]))


ROTURAS = [_supuesto_suma_mal, _oficial_suma_de_mas, _factor_desconocido, _factor_en_tiempo, _modelo_sin_ciclo,
           _plantilla_sin_modelo, _por_defecto_retirado, _incluye_a_si_mismo, _por_defecto_incoherente,
           _retirada_antes_de_ga, _arquitectura_de_servicio, _arquitectura_repetida]


@pytest.mark.parametrize("romper", ROTURAS, ids=[r.__name__ for r in ROTURAS])
def test_cada_rotura_la_ve_problemas_catalogo_y_derivar_no_deriva(romper, monkeypatch, capsys):
    roto = copy.deepcopy(CAT)
    romper(roto)
    assert derivar.problemas_catalogo(roto), romper.__name__
    monkeypatch.setattr(derivar, "cargar", lambda ruta=None: roto)
    assert derivar.main(ARGS_EFECTIVO + ["--comprobar"]) == 2
    assert "NO SE DERIVA" in capsys.readouterr().out


def test_la_instantanea_que_no_cubre_el_catalogo_tambien_para_la_derivacion(monkeypatch, capsys):
    roto = copy.deepcopy(CAT)
    nueva = dict(_foundry(roto)["plantillas_precio"][0], id="gpt-6-luna-nueva")
    _foundry(roto)["plantillas_precio"].append(nueva)
    monkeypatch.setattr(derivar, "cargar", lambda ruta=None: roto)
    assert derivar.main(ARGS_EFECTIVO + ["--comprobar"]) == 2
    assert "falta la plantilla az-foundry/gpt-6-luna-nueva" in capsys.readouterr().out


def test_con_el_esquema_vigente_corto_derivar_falla_en_alto_y_no_toca_el_sandbox(capsys):
    if VIGENTE_ADMITE:
        pytest.skip("el integrador ya aplicó el esquema propuesto de I1.7")
    antes = derivar.SANDBOX.read_bytes(), derivar.DERIVADO.read_bytes()
    assert derivar.main([]) == 2  # sin --comprobar: tampoco escribe
    salida = capsys.readouterr().out
    assert "25 elementos fuera de rango" in salida and "CAMBIOS-I17-E" in salida
    assert (derivar.SANDBOX.read_bytes(), derivar.DERIVADO.read_bytes()) == antes


def test_integracion_simulada_con_el_esquema_propuesto(tmp_path, monkeypatch):
    """Lo que hizo el integrador: copiar el esquema propuesto sobre el vigente y derivar; una segunda pasada da «igual».
    Arreglos I1.7: el vigente es el propuesto más las adiciones documentadas (tests/i17_arr_comun.py) y el derivado ya no
    es la vista previa de E, sino el catálogo v6 del repositorio."""
    from tests.i17_arr_comun import sin_arreglos
    from tests.i18_e_comun import sin_i18_e
    from tests.i19_e_comun import sin_i19_e
    vigente = json.loads(derivar.ESQUEMA_SANDBOX.read_text(encoding="utf-8"))
    # I1.8 e I1.9: el vigente suma además lo de E de cada tanda (i18_e_comun e i19_e_comun)
    assert sin_arreglos(sin_i18_e(sin_i19_e(vigente))) == PROPUESTO
    esq = tmp_path / "catalogo_componentes.json"
    esq.write_text(derivar.ESQUEMA_SANDBOX.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    der, sb = tmp_path / "derivado.json", tmp_path / "sandbox.json"
    ins = []
    for r in derivar.INSTRUCCIONES:
        copia = tmp_path / r.name
        copia.write_bytes(r.read_bytes())
        ins.append(copia)
    for k, v in {"ESQUEMA_SANDBOX": esq, "DERIVADO": der, "SANDBOX": sb, "INSTRUCCIONES": tuple(ins),
                 "RAIZ": tmp_path}.items():
        monkeypatch.setattr(derivar, k, v)
    assert derivar.main([]) == 0 and derivar.main(["--comprobar"]) == 0
    assert sb.read_bytes() == der.read_bytes() == (derivar.AQUI / "catalogo_componentes.json").read_bytes()
    assert all(c.read_bytes() == r.read_bytes() for c, r in zip(ins, derivar.INSTRUCCIONES))
    d = json.loads(sb.read_text(encoding="utf-8"))
    assert {f["id"] for f in d["factores_estandar"]} == set(pp.factores(CAT))
    assert set(PROPUESTO["properties"]) >= {"factores_estandar", "modelo_por_defecto", "arquitecturas_referencia"}


def _modelo_repetido(c):
    c["ciclo_vida_modelos"].append(dict(c["ciclo_vida_modelos"][0], retirada="2030-01-01"))


def _factor_repetido(c):
    c["casos_uso"][0]["factores"].append(dict(c["casos_uso"][0]["factores"][0], valor=1))


@pytest.mark.parametrize("romper", [_modelo_repetido, _factor_repetido], ids=["modelo", "factor"])
def test_ids_repetidos_no_se_esconden_al_colapsar(romper):
    """Revisión I1.7, 2.ª pasada (baja, cierta): un mapa por id se quedaba con el último repetido sin avisar."""
    roto = copy.deepcopy(CAT)
    romper(roto)
    assert any("ids repetidos" in x for x in pp.problemas_i17(roto))
