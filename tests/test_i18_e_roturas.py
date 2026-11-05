"""I1.8, papel E: cada rotura de lo nuevo del catálogo v7 la detecta problemas_i18 (y derivar no deriva)."""
from __future__ import annotations

import copy

import pytest

from catalogo import derivar
from catalogo import plantillas_precio as pp

CAT = derivar.cargar()


def _fila(c, cid):
    return next(x for x in c["componentes"] if x["id"] == cid)


def _pl(c, cid, pid):
    return next(p for p in _fila(c, cid)["plantillas_precio"] if p["id"] == pid)


def _nivel(c, cid, nombre):
    return next(n for n in _fila(c, cid)["niveles"] if n["nivel"] == nombre)


ROTURAS = {
    "volumen_sin_factor_ni_motivo": lambda c: _pl(c, "az-key-vault", "operaciones").pop("factor_estandar"),
    "volumen_con_factor_y_motivo": lambda c: _pl(c, "az-key-vault", "operaciones").update(sin_factor_motivo="x" * 30),
    "motivo_en_plantilla_de_tiempo": lambda c: _pl(c, "az-app-service", "b1-linux").update(sin_factor_motivo="x" * 30),
    "motivo_en_blanco": lambda c: _pl(c, "az-purview", "gobierno-basico").update(sin_factor_motivo="   "),
    "base_de_dos_letras": lambda c: c["casos_uso"][0]["factores"][0].update(base=["GB"]),
    "unidad_de_tiempo_desconocida": lambda c: _pl(c, "az-app-service", "b1-linux")["comprobacion"].update(unidad="1 Week"),
    "obligatorio_de_nivel_ajeno": lambda c: _nivel(c, "az-service-bus", "Standard").update(
        medidores_obligatorios=["standard-base", "no-existe"]),
    "obligatorio_de_nivel_vacio": lambda c: _nivel(c, "az-service-bus", "Standard").update(medidores_obligatorios=[]),
    "tope_cero": lambda c: _nivel(c, "az-app-service", "B1").update(instancias_max=0),
    "tope_booleano": lambda c: _nivel(c, "az-app-service", "B1").update(instancias_max=True),
    "tope_texto": lambda c: _nivel(c, "az-app-service", "B1").update(instancias_max="3"),
    "tope_sin_su_literal": lambda c: _nivel(c, "az-app-service", "B1").update(instancias_max=4),
    "minimo_mayor_que_tope": lambda c: _nivel(c, "az-app-service", "B1").update(instancias_min=5),
    "validas_por_encima_del_tope": lambda c: _nivel(c, "az-service-bus", "Premium").update(
        instancias_validas=[1, 2, 32]),
    "validas_vacias": lambda c: _nivel(c, "az-service-bus", "Premium").update(instancias_validas=[]),
    "regla_con_id_ajeno": lambda c: _fila(c, "az-ai-search")["reglas_medidores"][0].update(exige_uno_de=["s9"]),
    "regla_sin_exige": lambda c: _fila(c, "az-ai-search")["reglas_medidores"][0].pop("exige_uno_de"),
    "regla_sin_si_usa": lambda c: _fila(c, "az-ai-search")["reglas_medidores"][0].update(si_usa=[]),
    # integrador I1.8: quitar todos los niveles da además «sin niveles»; aquí solo una plantilla de tiempo sale del nivel
    "computo_con_tiempo_fuera_de_niveles": lambda c: _fila(c, "az-container-apps")["niveles"][0]["plantillas"].remove(
        "dedicado-gestion"),
    "computo_sin_niveles": lambda c: _fila(c, "az-foundry-agent-service").pop("niveles"),   # integrador I1.8 (P18-4)
}


# Revisión E2: cada rotura, con el diagnóstico concreto que tiene que salir (no basta con «algún problema»).
MENSAJE = {
    "volumen_sin_factor_ni_motivo": "az-key-vault/operaciones: plantilla de volumen con factor estándar y motivo",
    "volumen_con_factor_y_motivo": "az-key-vault/operaciones: plantilla de volumen con factor estándar y motivo",
    "motivo_en_plantilla_de_tiempo": "az-app-service/b1-linux: sin_factor_motivo solo en plantillas de volumen",
    "motivo_en_blanco": "az-purview/gobierno-basico: plantilla de volumen con factor estándar y motivo",
    "base_de_dos_letras": "palabras de base sin ninguna palabra de 4 letras o más ['GB']",
    "unidad_de_tiempo_desconocida": "az-app-service/b1-linux: unidad de tiempo «1 Week»",
    "obligatorio_de_nivel_ajeno": "az-service-bus/Standard: medidores_obligatorios vacíos o ajenos",
    "obligatorio_de_nivel_vacio": "az-service-bus/Standard: medidores_obligatorios vacíos o ajenos",
    "tope_cero": "az-app-service/B1: instancias_max 0 no es un entero",
    "tope_booleano": "az-app-service/B1: instancias_max True no es un entero",
    "tope_texto": "az-app-service/B1: instancias_max '3' no es un entero",
    "tope_sin_su_literal": "az-app-service/B1: instancias_max 4 sin su límite literal",
    "minimo_mayor_que_tope": "az-app-service/B1: instancias_min mayor que instancias_max",
    "validas_por_encima_del_tope": "az-service-bus/Premium: instancias_validas vacías o fuera",
    "validas_vacias": "az-service-bus/Premium: instancias_validas vacías o fuera",
    "regla_con_id_ajeno": "az-ai-search: regla de medidores con ids ajenos",
    "regla_sin_exige": "az-ai-search: regla de medidores con ids ajenos a la fila o sin «exige»",
    "regla_sin_si_usa": "az-ai-search: regla de medidores con ids ajenos",
    "computo_con_tiempo_fuera_de_niveles": "az-container-apps: fila de cómputo con plantillas de tiempo fuera de todo nivel",
    "computo_sin_niveles": "az-foundry-agent-service: fila de cómputo sin niveles",
}


@pytest.mark.parametrize("nombre", sorted(ROTURAS))
def test_cada_rotura_la_detecta_problemas_i18(nombre):
    c = copy.deepcopy(CAT)
    ROTURAS[nombre](c)
    problemas = pp.problemas_i18(c)
    assert any(MENSAJE[nombre] in x for x in problemas), (nombre, problemas)
    assert len(problemas) == 1, (nombre, problemas)  # solo lo roto


def test_la_copia_sin_romper_no_da_problemas():
    assert pp.problemas_i18(copy.deepcopy(CAT)) == []


def test_derivar_no_deriva_con_una_rotura(monkeypatch, tmp_path, capsys):
    c = copy.deepcopy(CAT)
    ROTURAS["tope_sin_su_literal"](c)
    monkeypatch.setattr(derivar, "cargar", lambda ruta=derivar.FUENTE: c)
    escritos = []
    monkeypatch.setattr(derivar.pathlib.Path, "write_text", lambda self, *a, **k: escritos.append(self))
    assert derivar.main(["--comprobar"]) == 2
    assert "instancias_max 4 sin su límite literal" in capsys.readouterr().out
    assert escritos == []


def test_problemas_i18_no_lanza_con_campos_ausentes():
    """Solo que no lance: la presencia de cada campo la exigen el esquema y las pruebas de la clase completa
    (test_i18_e_catalogo.py), no problemas_i18, que juzga la forma de lo que hay (Revisión E2)."""
    c = copy.deepcopy(CAT)
    for fila in c["componentes"]:
        for k in ("niveles", "reglas_medidores", "plantillas_precio"):
            fila.pop(k, None)
    c.pop("computo_por_defecto")
    assert isinstance(pp.problemas_i18(c), list)
