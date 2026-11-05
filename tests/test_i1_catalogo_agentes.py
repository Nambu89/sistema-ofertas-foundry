"""Pruebas sin red de los json_schema de text.format y de las instrucciones I1 (BD)."""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentes.esquemas import derivar_text_format as dtf
from catalogo import derivar
from esquemas import comprobar_esquemas as ce

RAIZ = pathlib.Path(__file__).resolve().parent.parent
INSTR = RAIZ / "agentes" / "instrucciones"
COORD = (INSTR / "coordinador_i1.md").read_text(encoding="utf-8")
EXPERTO = (INSTR / "experto_azure_i1.md").read_text(encoding="utf-8")
VERIF = (INSTR / "verificador_i1.md").read_text(encoding="utf-8")
CONTRATOS = (RAIZ / "docs" / "I1" / "CONTRATOS.md").read_text(encoding="utf-8")


def _nodos(n, ruta="$"):
    yield ruta, n
    for k in ("properties",):
        for p, s in n.get(k, {}).items():
            yield from _nodos(s, f"{ruta}.{p}")
    if "items" in n:
        yield from _nodos(n["items"], f"{ruta}[]")


def _expandido(n: dict, raiz: dict) -> dict:
    """Árbol de propiedades del esquema completo con los $ref resueltos (para comparar formas)."""
    if "$ref" in n:
        n = raiz["$defs"][n["$ref"].split("/")[-1]]
    out = {}
    if "properties" in n:
        out["properties"] = {p: _expandido(s, raiz) for p, s in n["properties"].items()}
        out["required"] = sorted(n.get("required", []))
    if "items" in n:
        out["items"] = _expandido(n["items"], raiz)
    return out


@pytest.mark.parametrize("nombre", dtf.NOMBRES)
def test_text_format_sincronizado(nombre):
    disco = json.loads(dtf.ruta_salida(nombre).read_text(encoding="utf-8"))
    assert disco == dtf.text_format(nombre)
    assert disco["type"] == "json_schema" and disco["strict"] is True and disco["name"] == nombre


@pytest.mark.parametrize("nombre", dtf.NOMBRES)
def test_text_format_solo_lo_probado_y_estricto(nombre):
    esquema = dtf.text_format(nombre)["schema"]
    for ruta, n in _nodos(esquema):
        assert set(n) <= dtf.PROBADAS, (ruta, set(n) - dtf.PROBADAS)
        tipos = n["type"] if isinstance(n["type"], list) else [n["type"]]
        assert "integer" not in tipos, ruta
        if "enum" in n:
            assert n["type"] == "string", ruta
        if "properties" in n:
            assert n["additionalProperties"] is False, ruta
            assert sorted(n["required"]) == sorted(n["properties"]), ruta
    assert ce.no_estricto(esquema) == []


@pytest.mark.parametrize("nombre", dtf.NOMBRES)
def test_text_format_misma_forma_que_el_completo(nombre):
    completo = json.loads((RAIZ / "esquemas" / f"{nombre}.json").read_text(encoding="utf-8"))
    derivado = dtf.text_format(nombre)["schema"]
    assert _expandido(derivado, derivado) == _expandido(completo, completo)


@pytest.mark.parametrize("nombre", dtf.NOMBRES)
def test_ejemplo_kelvara_valida_con_los_dos(nombre):
    ejemplo = json.loads((RAIZ / "esquemas" / "ejemplos" / f"{nombre}.json").read_text(encoding="utf-8"))
    derivado = dtf.text_format(nombre)["schema"]
    completo = json.loads((RAIZ / "esquemas" / f"{nombre}.json").read_text(encoding="utf-8"))
    assert ce.validar(ejemplo, derivado, derivado) == []
    assert ce.validar(ejemplo, completo, completo) == []


@pytest.mark.parametrize("esquema,motivo", [
    ({"type": "object", "properties": {"a": {"oneOf": [{"type": "string"}]}}}, "no probada"),
    ({"type": "object", "properties": {"a": {"$ref": "#/$defs/no"}}}, "inexistente"),
    ({"$defs": {"a": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"}, "recursivo"),
    ({"type": "object", "properties": {"a": {"enum": [1, 2]}}}, "no textual"),
    ({"$defs": {"a": {"type": "string"}}, "$ref": "#/$defs/a", "type": "number"}, "repetidas"),
])
def test_derivar_falla_en_alto(esquema, motivo):
    with pytest.raises(dtf.EsquemaNoDerivable, match=motivo):
        dtf.derivar_nodo(esquema, esquema)


def test_derivar_text_format_comprobar_rc0():
    assert dtf.main(["--comprobar"]) == 0


# --- Instrucciones: cruce con el contrato y con los datos reales (LES-G-088) ---

def test_tabla_del_catalogo_en_las_dos_instrucciones():
    tabla = derivar.tabla_markdown(derivar.cargar(), derivar.auxiliares_con_plantillas())  # integrador I1.6
    assert tabla in EXPERTO and tabla in VERIF


def test_experto_lleva_todos_los_prefijos_de_la_lista_blanca():
    for p in derivar.PREFIJOS_ARQUITECTURA + derivar.PREFIJOS_SERVICIO:
        assert f"`{p}`" in EXPERTO, p


def test_experto_lleva_las_reglas_duras():
    for frase in ("brief_recibido", "3 búsquedas y 2 lecturas", "perfiles_permitidos", "NUNCA la familia GPT-4",
                  "CSP", "NO VERIFICADO", "sin ningún dato del cliente", "Azure Cognitive Search",
                  "Foundry Models", "Microsoft Fabric", "No tienes herramienta de precios", "gpt-6-luna",
                  "Project Manager"):  # integrador I1.7 (CAMBIOS-I17-E §5): sin filtros ni priceType
        assert frase in EXPERTO, frase


def test_experto_nombra_todas_las_claves_del_esquema():
    esquema = json.loads((RAIZ / "esquemas" / "respuesta_experto.json").read_text(encoding="utf-8"))
    for clave in esquema["required"]:
        assert f"`{clave}`" in EXPERTO, clave
    for clave in esquema["properties"]["herramientas_usadas"]["required"]:
        assert f"`{clave}`" in EXPERTO, clave


def test_experto_ids_de_requisitos_iguales_al_esquema():
    req = json.loads((RAIZ / "esquemas" / "requisitos.json").read_text(encoding="utf-8"))
    campos = set(req["properties"]["campos"]["properties"])
    ids = set(re.findall(r"`R-([a-z_]+)`", EXPERTO))
    assert ids == campos


def test_verificador_lleva_las_reglas_duras():
    assert "precios_azure" not in VERIF and "prices.azure.com/api" not in VERIF  # I1.7: sin herramienta de precios
    for frase in ("exactamente un", "Los precios no se te envían", "**6**",
                  "familia GPT-4", "CSP", "NO VERIFICABLE", "DISCREPA sin fuente", "tildes", "Señalas, no corriges"):
        assert frase in VERIF, frase
    esquema = json.loads((RAIZ / "esquemas" / "respuesta_verificador.json").read_text(encoding="utf-8"))
    for clave in esquema["required"] + esquema["$defs"]["elemento"]["required"]:
        assert f"`{clave}`" in VERIF, clave


def _subcomandos_contrato() -> set[str]:
    seccion = CONTRATOS.split("## 2. Subcomandos", 1)[1].split("## 3.", 1)[0]
    return set(re.findall(r"^\| `([a-z-]+)` \|", seccion, re.M))


def test_coordinador_cubre_los_subcomandos_del_contrato():
    subcomandos = _subcomandos_contrato()
    assert len(subcomandos) >= 14
    usados = set(re.findall(r"\['([a-z-]+)'", COORD))
    # 'entorno' es diagnóstico de I0: no forma parte del flujo del comercial.
    assert subcomandos - {"entorno"} <= usados, subcomandos - usados
    assert usados <= subcomandos, usados - subcomandos


def _bloques_python(texto: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", texto, re.S)


def test_coordinador_bloques_compilan():
    bloques = _bloques_python(COORD)
    assert len(bloques) == 2
    for b in bloques:
        compile(b, "bloque", "exec")


def _ejecutar_bloque_b(tmp_path, nombre: str, texto: str) -> pathlib.Path:
    b = _bloques_python(COORD)[1]
    assert "NOMBRE = 'requisitos.json'" in b and "TEXTO = r'''{}'''" in b
    destino = tmp_path / "entrada"
    codigo = (b.replace("'/mnt/data/preventa/entrada'", repr(str(destino)))
               .replace("NOMBRE = 'requisitos.json'", f"NOMBRE = {nombre!r}")
               .replace("TEXTO = r'''{}'''", f"TEXTO = r'''{texto}'''"))
    exec(compile(codigo, "bloque_b", "exec"), {})
    return destino / nombre


def test_bloque_b_guarda_literal(tmp_path):
    texto = r'{"brief_recibido": "línea 1\nlínea \"2\" con ñ y tilde á", "n": 1}'
    ruta = _ejecutar_bloque_b(tmp_path, "respuesta_experto_AZ_R1.json", texto)
    assert ruta.read_bytes() == texto.encode("utf-8") + b"\n"
    assert json.loads(ruta.read_text(encoding="utf-8"))["brief_recibido"] == 'línea 1\nlínea "2" con ñ y tilde á'


@pytest.mark.parametrize("nombre", ["requisitos.json", "respuesta_experto_AZ_R1.json", "respuesta_verificador_R3.json",
                                    "aclaracion_1.txt", "aclaracion_12.txt"])
def test_bloque_b_admite_las_entradas_del_contrato(tmp_path, nombre):
    assert _ejecutar_bloque_b(tmp_path, nombre, "{}").exists()


# I1.4 (decisión del comercial del 10-10-2026): la entrada de la estimación la compone el núcleo; el coordinador ya no
# puede escribir estimacion_entrada.json con el bloque B.
@pytest.mark.parametrize("nombre", ["estado.json", "../estado.json", "requisitos.json/../x", "respuesta_experto_AZ_R4.json",
                                    "entrada/requisitos.json", "manifiesto_paquete.json", "estimacion_entrada.json"])
def test_bloque_b_rechaza_otros_nombres(tmp_path, nombre):
    with pytest.raises(AssertionError):
        _ejecutar_bloque_b(tmp_path, nombre, "{}")


def test_coordinador_no_compone_la_estimacion():
    """Sin hitos, tareas PM ni JSON de estimación a mano: solo ['estimar'] (o con --aplicar-ajuste)."""
    assert not re.findall(r"«Hito \d - ", COORD) and "--entrada" not in COORD and "PM-01" not in COORD
    assert "`['estimar']`" in COORD and "['estimar', '--aplicar-ajuste', 'D-NNN']" in COORD
    assert "No escribes ningún JSON de estimación" in COORD


def test_coordinador_abre_cada_turno_con_turno_nuevo():
    """EA-1: el paso del turno anterior se reescribe con estado --turno-nuevo y nunca para el turno siguiente."""
    assert "['estado', '--turno-nuevo']" in COORD and "Con la respuesta del comercial de este turno" in COORD
    assert "['restaurar', '--estado', 'estado.json', '--relevo', 'relevo.json']" in COORD  # EA-5


def test_coordinador_lleva_las_reglas_duras():
    for frase in ("Una fase por turno", "registrar-fallo", "EXACTAMENTE", "LITERAL", "=== ESTADO PREVENTA ===",
                  "SIGUIENTE PASO OBLIGATORIO", "conversación nueva", "DATOS, no instrucciones", "nunca envías nada",
                  "Responsable de preventa", "Responsable de área", "verificar_paquete.py", "20 minutos", "100.000 EUR",
                  "al menos 8 horas", "ajuste_comercial_eur: 0"):
        assert frase in COORD, frase


def test_marcas_del_brief_y_del_consolidado_iguales_al_contrato():
    for marca in ("=== BRIEF PARA preventa-experto-azure ===", "=== FIN BRIEF ==="):
        assert marca in CONTRATOS and marca in COORD, marca
    # I1.1 (LES-G-096): el coordinador A envía el consolidado por lotes; el contrato conserva las dos formas.
    for marca in ("=== CONSOLIDADO PARA preventa-verificador ===", "=== FIN CONSOLIDADO ==="):
        assert marca in CONTRATOS, marca
    for marca in ("=== LOTE <lote_id> PARA preventa-verificador", "=== FIN LOTE ==="):
        assert marca in CONTRATOS and marca in COORD, marca
    assert "`consolidar --lotes`" in CONTRATOS and "['consolidar', '--lotes']" in COORD
    assert "['restaurar', '--zip'" in COORD and "RELEVO:" in COORD


def test_bloque_b_solo_normaliza_saltos_de_los_extremos_y_crlf(tmp_path):
    texto = "\n\r\n" + '{"a": "x",\r\n "b": "  y  "}' + "\r\n\n"
    ruta = _ejecutar_bloque_b(tmp_path, "requisitos.json", texto)
    assert ruta.read_bytes() == b'{"a": "x",\n "b": "  y  "}\n'
    assert json.loads(ruta.read_text(encoding="utf-8")) == {"a": "x", "b": "  y  "}
