"""I1.7 · Papel R · VER16-5: los comentarios de la DEVUELTA y cómo se atendieron llegan a la versión siguiente.

La DEVUELTA guarda lo que se devuelve (`version_devuelta`, calculado por el código) y la versión siguiente compone la
sección «Cambios pedidos en la revisión anterior» para la nota (con importes) y el PPTX (sin importes y sin comentarios
que el barrido del cliente no admite). Y la línea P- del brief (contrato v4) con sus datos anonimizados. Sin red."""
from __future__ import annotations

import copy

import pytest

from tests.test_i15_r_brief_devuelta import J, _devolver
from tests.test_i1_estado_comun import Mundo

from nucleo import decision, verificacion  # noqa: E402


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


ANTES = {"componentes": [{"clave": "az-ai-search", "sku": "Standard S1", "region": "swedencentral"},
                         {"clave": "az-bot-service", "sku": "S1", "region": "global"}],
         "precios": [{"clave": "az-ai-search · basic", "cantidad_mensual": 730},
                     {"clave": "az-foundry · gpt-6-luna-entrada", "cantidad_mensual": 8}],
         "consumo_mensual_eur": "250.10", "precio_cerrado_eur": "30000.00"}


def _estado(version="B", antes=ANTES, comentario="Bajad AI Search a Basic: 2.000 consultas no lo justifican."):
    resp = {"componentes": [{"id": "C-01", "catalogo_id": "az-ai-search", "sku": "Basic", "region": "swedencentral"},
                            {"id": "C-02", "catalogo_id": "az-app-service", "sku": "B1", "region": "swedencentral"}],
            "precios": [{"id": "P-01", "componente_id": "C-01", "plantilla_id": "basic", "cantidad_mensual": 730},
                        {"id": "P-02", "componente_id": "C-02", "plantilla_id": "b1", "cantidad_mensual": 730}]}
    dev = {"id": "D-003", "tipo": "DEVUELTA", "version": "A", "revisor": J, "comentarios": comentario}
    if antes is not None:
        dev["version_devuelta"] = antes
    return {"version": version, "decisiones": [dev], "carga": {
        "respuestas_expertos": {"azure": {"respuesta": resp}}, "anexo_consumo": {"total_mensual_eur": "76.43"},
        "estimacion": {"resumen": {"precio_cerrado_eur": "28000.00"}}}}


def test_version_a_sin_devuelta_no_lleva_seccion():
    assert decision.cambios_pedidos(_estado(version="A")) is None
    assert decision.lineas_cambios_pedidos(_estado(version="A")) == []


def test_nota_con_comentario_literal_y_diferencias_calculadas():
    ls = decision.lineas_cambios_pedidos(_estado())
    assert ls[0] == "Cambios pedidos en la revisión anterior (versión A, DEVUELTA)"
    assert ls[1] == f"Comentario de {J} (D-003): «Bajad AI Search a Basic: 2.000 consultas no lo justifican.»"
    assert "no dice qué cambio responde a cada comentario" in ls[2]
    for x in ("- Componente añadido: az-app-service (B1, swedencentral)", "- Componente retirado: az-bot-service (S1, global)",
              "- Cambio de nivel en az-ai-search: de Standard S1 a Basic", "- Consumo añadido: az-app-service · b1 (730 al mes)",
              "- Consumo retirado: az-foundry · gpt-6-luna-entrada (8 al mes)",
              "- Consumo mensual estimado: de 250.10 € a 76.43 €", "- Precio cerrado: de 30000.00 € a 28000.00 €"):
        assert x in ls, (x, ls)


def test_pptx_sin_importes_y_comentario_no_apto_remite_a_la_nota():
    ls = decision.lineas_cambios_pedidos(_estado(), con_importes=False, perfiles=["AI Engineer / Tech Lead"])
    assert not [x for x in ls if "€" in x or "al mes" in x] and any("Cambio de nivel" in x for x in ls)
    assert "- Consumo añadido: az-app-service · b1" in ls
    malo = _estado(comentario="Sobran 40 horas del AI Engineer / Tech Lead; recortad el esfuerzo.")
    ls = decision.lineas_cambios_pedidos(malo, con_importes=False, perfiles=["AI Engineer / Tech Lead"])
    assert ls[1] == f"Comentario de {J} (D-003): recogido en la nota del revisor"
    assert "horas" in decision.lineas_cambios_pedidos(malo)[1]              # en la nota sí va literal


def test_sin_cambios_lo_marca_y_sin_resumen_remite_al_previo():
    igual = decision.resumen_version(_estado())
    ls = decision.lineas_cambios_pedidos(_estado(antes=igual))
    assert ls[-1].startswith("- Sin cambios en componentes") and len(ls) == 4
    ls = decision.lineas_cambios_pedidos(_estado(antes=None))
    assert ls[-1].startswith("- Sin resumen de la versión A") and "--previo" in ls[-1]


def test_la_devuelta_guarda_lo_que_se_devuelve_y_la_version_b_lo_compara(m):
    _devolver(m, "Revisad el nivel de AI Search y el consumo de Foundry.")
    est = m.estado()
    d = est["decisiones"][-1]
    assert d["tipo"] == "DEVUELTA" and est["version"] == "B"
    vd = d["version_devuelta"]
    # integrador I1.9 (VA18-3, CAMBIOS-I19-P §5.7): con estimación, la versión devuelta la guarda para la nota de la B
    assert set(vd) == {"componentes", "precios", "consumo_mensual_eur", "precio_cerrado_eur", "estimacion"}         and vd["componentes"]
    assert set(vd["estimacion"]) == {"duracion_semanas", "horas_total", "por_perfil", "por_fase", "tareas"}
    ls = decision.lineas_cambios_pedidos(est)
    assert ls[1].endswith("«Revisad el nivel de AI Search y el consumo de Foundry.»")
    assert ls[-1].startswith("- ")


def test_la_linea_p_del_brief_v4_lleva_lo_que_escribe_el_experto_anonimizado():
    anon = lambda t: t.replace("Kelvara", "[CLIENTE]")  # noqa: E731
    p = {"id": "P-01", "componente_id": "C-01", "plantilla_id": "gpt-6-luna-entrada", "instancias": None,
         "base_volumen": {"cita": "Kelvara hace 2.000 consultas al mes.", "cantidad_base": 2000, "unidad_base": "consultas"},
         "factor_override": None, "cantidad_mensual": 8}
    assert verificacion.linea_precio_brief(p, anon) == (
        "P-01 | C-01 | plantilla: gpt-6-luna-entrada | base: «[CLIENTE] hace 2.000 consultas al mes.» (2000 consultas) "
        "| factor: estándar del catálogo | cantidad_mensual: 8")
    q = dict(p, factor_override={"valor": 6000, "cita": "Kelvara usa documentos largos.", "justificacion": "x"})
    assert "| factor_propio: 6000 («[CLIENTE] usa documentos largos.») |" in verificacion.linea_precio_brief(q, anon)
    t = {"id": "P-02", "componente_id": "C-02", "plantilla_id": "basic", "instancias": 2, "base_volumen": None,
         "factor_override": None, "cantidad_mensual": 1460}
    assert verificacion.linea_precio_brief(t) == "P-02 | C-02 | plantilla: basic | instancias: 2 | cantidad_mensual: 1460"


def test_precio_sin_plantilla_ni_filtro_no_se_conserva_en_silencio():
    est = {"carga": {"verificacion": None, "respuestas_expertos": {"azure": {"respuesta": {
        "componentes": [{"id": "C-01"}], "precios": [{"id": "P-01", "componente_id": "C-01", "cantidad_mensual": 1}]}}}}}
    with pytest.raises(verificacion.IntegridadRota):
        verificacion._precios_conservables(copy.deepcopy(est))
