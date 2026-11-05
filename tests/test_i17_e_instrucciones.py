"""I1.7, papel E: bloque v4 de las instrucciones del experto (sin filtros) e instrucciones del verificador (sin lote de
precios). Sin red."""
from __future__ import annotations

import re

import pytest

from catalogo import derivar
from catalogo import plantillas_precio as pp

CAT = derivar.cargar()
EXPERTO = derivar.INSTRUCCIONES[0].read_text(encoding="utf-8")
VERIF = derivar.INSTRUCCIONES[1].read_text(encoding="utf-8")
BLOQUE = pp.bloque_v4(CAT, True)
LIMITES = re.compile(r"### Límites que comprueba el código.*?### Fin de los límites", re.S)


def _sin_limites(texto: str) -> str:
    """El bloque de límites lo genera agentes/esquemas/limites.py desde los esquemas de P (no es de E)."""
    return LIMITES.sub("", texto)


def test_bloque_v4_sin_filtros_ni_modelos_retirados():
    assert "serviceName eq" not in BLOQUE and "$filter" not in BLOQUE
    for i in ("gpt-5-entrada", "gpt-5-mini-salida", "gpt-5.4-entrada"):
        assert f"`{i}`" not in BLOQUE
    assert ("`gpt-6-luna-entrada` V/1M [f=asistente_rag.tokens_entrada_por_consulta] "
            "[o f=asistente_rag.tokens_entrada_por_accion] (por defecto)") in BLOQUE  # E19-2 (cierre, 16-10-2026)
    assert "`asistente_rag.tokens_entrada_por_consulta` = 5.656 tokens de entrada por consulta (oficial)" in BLOQUE
    assert "`gpt-5` (2027-02-09)" in BLOQUE and "`gpt-5.4` (2027-09-02)" in BLOQUE
    assert all(f"`{a['id']}`" in BLOQUE for a in CAT["arquitecturas_referencia"])
    assert "`az-app-insights` va incluido en `az-log-analytics`" in BLOQUE
    # 19,6 KB medidos el 13-10-2026; 21.147 B tras los arreglos de I1.7 (cómputo por defecto, nivel EP1, medidores
    # obligatorios y factor de Storage); que no crezca sin medirlo
    # I1.8 (LES-G-100.7 y .8, REVERIF17-2 y -3): 29.573 B medidos el 13-10-2026 con 29 factores (sin su justificación),
    # reglas de medidores, topes de instancias y plantillas sin factor; que no crezca sin medirlo
    # I1.10 (ARR1): 31.092 B medidos el 18-10-2026 (por_instancia de AI Search en las razones)
    assert len(BLOQUE.encode("utf-8")) < 31500


@pytest.mark.parametrize("texto, motivo", [
    ("a\n" + pp.INICIO + "\nx\n" + pp.FIN + "\n" + pp.INICIO_V4 + "\n" + pp.FIN_V4, "anterior a I1.7"),
    ("a\n", "faltan"),
    (pp.INICIO_V4 + "\n" + pp.INICIO_V4 + "\n" + pp.FIN_V4, "sobran"),
    (pp.FIN_V4 + "\n" + pp.INICIO_V4, "desordenadas")])
def test_insertar_bloque_v4_falla_en_alto(texto, motivo):
    with pytest.raises(ValueError, match=motivo.split()[0]):
        pp.insertar_bloque_v4(texto, "B")


def test_experto_sin_herramienta_de_precios_y_con_la_regla_v4():
    propio = _sin_limites(EXPERTO)
    assert "precios_azure" not in propio
    assert "Retail Prices LITERAL" not in propio and "### productName del filtro" not in propio
    for k in ("`plantilla_id`", "`instancias`", "`base_volumen`", "`factor_override`", "`arquitectura_id`",
              "`existente_del_cliente`", "`incluido_en`", "«precios consultados el» seguido de esa fecha"):
        assert k in propio, k  # I1.9: `motivo_cita` sale con a_cargo_del_cliente (existente_del_cliente, PR18-1)
    # I1.9: 65,5 KB medidos (recursos del cliente, razones cerradas, modelo y cómputo); 66.074 B en I1.6; 52.100 B en
    # I1.7; 62,6 KB en I1.8; 66.828 B en I1.10 (ARR1, medido el 18-10-2026)
    assert len(EXPERTO.encode("utf-8")) < 67000


def test_verificador_sin_lote_de_precios():
    propio = _sin_limites(VERIF)
    assert "**Precios**" not in propio and "P-nn | C-nn | filtro" not in propio and "prices.azure.com" not in propio
    assert "no tienes herramienta de precios" in propio and "`campo` = `motivo`" in propio
    assert "| factor: plantilla valor unidad (estándar: valor_estándar)" in propio
    assert len(VERIF.encode("utf-8")) < 24000  # 23,1 KB en I1.6; 23,7 KB en I1.9 (recurso del cliente, nivel y disponibilidad)
