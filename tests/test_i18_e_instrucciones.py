"""I1.8, papel E: instrucciones del experto y del verificador al día (PR17-6 parte 2, REV17-1 a -3, REVERIF17-2 y -3,
VER17-6) y bloques generados en sincronía con el catálogo, los esquemas y el text.format."""
from __future__ import annotations

import json
import pathlib

import pytest

from agentes.esquemas import derivar_text_format as dtf
from agentes.esquemas import limites
from catalogo import derivar
from catalogo import plantillas_precio as pp

RAIZ = pathlib.Path(__file__).resolve().parents[1]
EXP = (RAIZ / "agentes/instrucciones/experto_azure_i1.md").read_text(encoding="utf-8")
VER = (RAIZ / "agentes/instrucciones/verificador_i1.md").read_text(encoding="utf-8")
BLOQUE = pp.bloque_v4(derivar.cargar(), True)
TF_VER = json.loads((RAIZ / "agentes/esquemas/respuesta_verificador.text_format.json").read_text(encoding="utf-8"))


def test_sincronia_de_los_bloques_generados(capsys):
    assert derivar.main(["--comprobar"]) == 0
    assert limites.main(["--comprobar"]) == 0
    assert dtf.main(["--comprobar"]) == 0
    assert "DISTINTO" not in capsys.readouterr().out
    assert BLOQUE in EXP


@pytest.mark.parametrize("frase", [
    "REINTENTO-PREVENTA/1", "Motivo literal del último rechazo del código", "sin el bloque `REINTENTO-PREVENTA/1`",
    # I1.9: «a_cargo_del_cliente» con motivo_cita sale (existente_del_cliente, PR18-1) y las instancias de más se
    # justifican con una razón cerrada de su nivel (VC18-1); tests/test_i19_e_instrucciones.py prueba lo nuevo
    "«## Lo que el cliente ya tiene o paga»", "Es la única fuente de `existente_del_cliente`",
    "El `sku` de Microsoft Foundry nombra el modelo de sus plantillas de precio y ningún otro",
    "Más de 1 solo con `justificacion_nivel` (una razón de su nivel", "**Medidores que van juntos**",
    "Azure Container Apps `Dedicado D4`", "Azure Logic Apps `Standard WS1` o `Consumo`",
    "se valoran por consulta con sus factores estándar"])
def test_el_experto_lleva_las_reglas_de_esta_tanda(frase):
    assert frase in EXP


@pytest.mark.parametrize("frase", [
    "partirla no cambia el importe", "Más de 1 instancia solo con `justificacion_nivel`", "[sin f]",
    "Reglas de medidores (con cualquier plantilla", "`gpt-6-luna-entrada`, `gpt-6-luna-salida`",
    "`ranking-semantico` → una de `basic`, `s1`", "`B1` (b1-linux) [hasta 3 instancias]",
    "`Premium` (premium-mu) [instancias 1, 2, 4, 8, 16]",
    "`Aprovisionado` (aprovisionado-100ru) [lleva `aprovisionado-100ru` y `almacenamiento`; desde 4 instancias]",
    "`Dedicado D4` (dedicado-vcpu, dedicado-memoria, dedicado-gestion) [lleva `dedicado-vcpu` y `dedicado-memoria` y "
    "`dedicado-gestion`]",
    "umbral de tokens de entrada entre contexto corto y largo de GPT-6 está NO VERIFICADO"])
def test_el_bloque_generado_dice_lo_nuevo(frase):
    assert frase in BLOQUE


def test_el_bloque_no_ofrece_modelos_fuera_por_ciclo_de_vida_en_sin_factor():
    seccion = BLOQUE.split("Plantillas de volumen sin factor estándar", 1)[1].split("\n\n", 1)[0]
    for modelo in pp.modelos_fuera_siempre(derivar.cargar()):
        assert f"`{modelo}-" not in seccion


def test_el_bloque_no_trae_la_justificacion_de_cada_factor():
    factores = BLOQUE.split("Factores estándar", 1)[1].split("\n\n", 1)[0]
    assert "Learn" not in factores and len(factores.splitlines()) == len(pp.factores(derivar.cargar())) + 1


def test_verificador_sin_precio_ni_en_el_texto_ni_en_el_text_format():
    assert "P-nn" not in VER and "no hay `tipo` para precios" in VER
    # I1.9: sale el motivo «a cargo del cliente» (su línea ya no llega); el recurso del cliente no se juzga como nuevo
    assert "existente del cliente:" in VER and "«estándar: no hay»" in VER
    props = TF_VER["schema"]["properties"]["elementos"]["items"]["properties"]
    assert props["tipo"]["enum"] == ["referencia", "componente"]
    assert props["campo"]["enum"] == ["ninguno", "url", "titulo", "nombre", "sku", "region", "referencia", "cantidad",
                                      "motivo"]


def test_el_text_format_falla_en_alto_si_el_origen_cambia_de_forma():
    with pytest.raises(dtf.EsquemaNoDerivable):
        dtf.quitar_residuos("respuesta_verificador", {"properties": {"elementos": {"items": {"properties": {}}}}})
    with pytest.raises(dtf.EsquemaNoDerivable):
        dtf.quitar_residuos("respuesta_verificador", {"properties": {"elementos": {"items": {"properties": {
            "tipo": {"type": "string", "enum": ["precio"]}, "campo": {"type": "string", "enum": ["ninguno"]}}}}}})
    assert dtf.quitar_residuos("respuesta_experto", {"x": 1}) == {"x": 1}
