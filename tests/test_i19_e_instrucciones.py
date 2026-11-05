"""I1.9, papel E: instrucciones del experto y del verificador con el contrato común (recursos del cliente, valor por
defecto sin justificar, razones cerradas, modelo y disponibilidad), bloques regenerados y en sincronía."""
from __future__ import annotations

import pathlib

import pytest

from agentes.esquemas import derivar_text_format as dtf
from agentes.esquemas import limites
from catalogo import derivar
from catalogo import plantillas_precio as pp

RAIZ = pathlib.Path(__file__).resolve().parents[1]
EXP = (RAIZ / "agentes/instrucciones/experto_azure_i1.md").read_text(encoding="utf-8")
VER = (RAIZ / "agentes/instrucciones/verificador_i1.md").read_text(encoding="utf-8")
CAT = derivar.cargar()
BLOQUE = pp.bloque_v4(CAT, derivar.auxiliares_con_plantillas())
PLANO = " ".join(EXP.split())


def test_bloques_generados_en_sincronia(capsys):
    assert derivar.main(["--comprobar"]) == 0 and limites.main(["--comprobar"]) == 0 and dtf.main(["--comprobar"]) == 0
    assert "DISTINTO" not in capsys.readouterr().out
    assert EXP.count(BLOQUE) == 1 and VER.count(pp.bloque_disponibilidad(CAT)) == 1


@pytest.mark.parametrize("frase", [
    "Es la única fuente de `existente_del_cliente`", "`existente_del_cliente: {\"entrada\": \"EX-nn\"}`",
    "`motivo_no_valoracion: \"existente_del_cliente\"`", "Cada `EX-nn` casa con un solo componente y con su mismo servicio",
    "su App Service no es el cómputo de la solución", "«La solución no tiene cómputo propio»",
    "usa el nivel marcado «por defecto» con `justificacion_nivel: null`", "`justificacion_nivel` = {`nivel`, `razon`, `cita`}",
    "nunca suben un nivel", "y una razón del modelo en el bloque",
    "Un componente de datos va unido por un flujo a quien usa sus datos"])
def test_el_experto_lleva_el_contrato_comun(frase):
    assert frase in PLANO, frase


def test_el_experto_ya_no_lleva_la_forma_anterior():
    for viejo in ("`a_cargo_del_cliente`", "`motivo_cita`", "`limite_oficial`", "`requisito`: una frase LITERAL",
                  "Elige el **menor** nivel"):
        assert viejo not in EXP, viejo


@pytest.mark.parametrize("frase", [
    "`Consumption` (consumo-llamadas) por defecto", "`Basic` (basic) [hasta 9 instancias] por defecto",
    "`D2ds_v5` (d2ds-v5) [lleva `d2ds-v5` y `almacenamiento`] por defecto", "`Estándar` (canales-estandar) por defecto",
    "`P1` (servidores-p1) por defecto", "`almacenamiento` (Volumetría: más de 45 «gigabytes» o «GB»)",
    "`modelo_nombrado` («gpt-6-sol» / «GPT-6 Sol»)", "`sesiones` (Volumetría: más de 300 «simultáneas»)",
    "`privado_red` (L1; Red privada)", "Plantillas opcionales (`[opcional]`",
    "`ranking-semantico` V/1K [f=asistente_rag.consultas_ranking_por_consulta] [opcional]",
    "`orquestacion` → `movimiento-datos`"])
def test_el_bloque_dice_el_valor_por_defecto_y_las_razones(frase):
    assert frase in BLOQUE, frase


def test_el_bloque_no_copia_limites_y_ensena_los_factores_por_accion():
    niveles = BLOQUE.split(pp.INTRO_NIVELES_V8, 1)[1].split("\n\n", 1)[0]
    assert "https://" not in niveles and "«15 GB de almacenamiento" not in niveles
    assert "[o f=" in BLOQUE and "Con `[o f=…]`, el código elige" in BLOQUE  # PR18-5 (E19-2, cerrado por P)


def test_cada_factor_alternativo_del_bloque_lo_elige_el_nucleo_por_la_base():
    """LES-G-088 (cierre, 16-10-2026): cada `[o f=X]` del bloque, con la cita de acciones, es el factor que elige
    el núcleo real (`experto.factor_por_base`) con el catálogo del sandbox; con la de consultas, el `[f=…]`; con las
    dos bases en `unidad_base`, falla cerrado. Así el bloque no promete un factor que el código no aplica."""
    import json
    import re
    import sys
    sys.path.insert(0, str(RAIZ / "sandbox"))
    from nucleo import experto  # noqa: E402
    cat = json.loads((RAIZ / "sandbox/datos/catalogo_componentes.json").read_text(encoding="utf-8"))
    marcas = re.findall(r"`([a-z0-9.-]+)` V/\S+ \[f=([a-z0-9_.]+)\] \[o f=([a-z0-9_.]+)\]", BLOQUE)
    filas = {p["id"]: c["id"] for c in cat["componentes"] for p in c.get("plantillas_precio") or []
             if p.get("factores_alternativos")}
    assert {m[0] for m in marcas} == set(filas) and len(marcas) == len(filas) == 7, marcas
    acciones, consultas = "Aproximadamente 1.500 acciones al mes.", "Aproximadamente 6.000 consultas al mes."
    las_dos = "Unas 2.000 consultas y 1.500 acciones al mes."
    for plantilla, std, alt in marcas:
        info = experto.resolver_plantilla(plantilla, {"catalogo_id": filas[plantilla]}, cat)[0]
        assert experto.factor_por_base(info, cat, acciones, "acciones al mes")[0]["id"] == alt, plantilla
        assert experto.factor_por_base(info, cat, consultas, "consultas al mes")[0]["id"] == std, plantilla
        f, motivo = experto.factor_por_base(info, cat, las_dos, "consultas y acciones")
        assert f is None and "casan con más de una base" in motivo, plantilla
        # Revisión C1: el camino real (`_volumen`, que valora el precio) acepta la cita de acciones con ese factor
        errores = []
        base = {"cita": acciones, "cantidad_base": 1500, "unidad_base": "acciones al mes"}
        completada, cantidad, _ = experto._volumen({"id": "P-01", "factor_override": None}, info, base, [], cat,
                                                   lambda *a: errores.append(a), lambda *a: None)
        assert errores == [] and cantidad is not None, (plantilla, errores)
        assert completada["factor"]["unidad"].endswith("por acción"), plantilla


@pytest.mark.parametrize("frase", [
    "| razon: id («texto de la razón») | cita: «…» | fuente_nivel: URL", "| existente del cliente: EX-nn | cita: «…»",
    "**La disponibilidad por nivel y región es un dato del catálogo**", "el aviso de una columna (Premium v2) no es de otra",
    "nunca `DISCREPA` de `sku`, `region`, nivel ni `motivo`", "el código ya comprobó que la cita la cumple",
    "Azure API Management · Basic v2, Standard v2: UE7 (nivel; api-management/api-management-region-availability).",
    "Microsoft Foundry · gpt-6-luna, gpt-6-sol, gpt-6.1-sol: swedencentral"])
def test_el_verificador_no_verifica_lo_del_cliente_ni_la_disponibilidad_del_catalogo(frase):
    assert frase in VER, frase
    assert "`motivo_cita`" not in VER and "requisito: «" not in VER


def test_el_verificador_entiende_la_linea_que_genera_hoy_el_nucleo():
    """Reanudación de I1.9 (E19-9): `verificacion.py` sigue con la línea de I1.6 (`requisito:`/`limite:`) y el recurso
    del cliente solo sale como `| motivo: existente_del_cliente`. Mientras el integrador no la cambie, las
    instrucciones tienen que cubrir esa forma sin convertir la falta de datos en un DISCREPA."""
    import sys
    sys.path.insert(0, str(RAIZ / "sandbox"))
    from nucleo import verificacion  # noqa: E402
    comp = {"id": "C-03", "justificacion_nivel": {"nivel": "Standard v2", "razon": "portal_desarrolladores",
                                                  "cita": "portal para desarrolladores"},
            "motivo_no_valoracion": "existente_del_cliente", "existente_del_cliente": {"entrada": "EX-01"}}
    nivel = verificacion._segmento_nivel(comp, lambda t: t)
    motivo = verificacion._segmento_motivo(comp, {"componentes": [comp]}, lambda t: t)
    marcas_nivel = [m for m in ("razon:", "requisito:") if m in nivel]
    assert marcas_nivel and all(f"`{m}" in VER for m in marcas_nivel), nivel
    if "sin fuente" in nivel:
        assert "Si llegan vacías (`«»`) o `fuente_nivel` es «sin fuente»" in VER
    assert ("existente del cliente:" in motivo or "motivo: existente_del_cliente" in motivo), motivo
    assert "la línea trae `existente del cliente:` o `motivo: existente_del_cliente`" in VER
    assert "la falta de esos datos nunca es un `DISCREPA`" in VER
    # Revisión R1 (1 y 2): la excepción solo vale con los campos VACÍOS; con texto (también en la forma anterior) se
    # juzga como siempre, y el resto de comprobaciones del componente sigue dando DISCREPA con fuente.
    parrafo = next(lin for lin in VER.splitlines() if lin.startswith("- **Nivel del servicio**"))
    assert "Sobredimensionado o insuficiente → `DISCREPA`" in parrafo
    assert "La forma anterior (`requisito:` y `limite:`) se juzga igual que `razon` y `cita` cuando trae texto" in parrafo
    assert "Si llegan vacías (`«»`) o `fuente_nivel` es «sin fuente»" in parrafo
    assert "sigue siendo `DISCREPA` si una fuente lo contradice" in parrafo and "comprueba solo" not in parrafo
    antiguo = verificacion._segmento_nivel({"justificacion_nivel": {"nivel": "S1", "requisito": "60 GB",
                                                                    "limite_oficial": "15 GB"}}, lambda t: t)
    assert "requisito: «60 GB»" in antiguo and "limite: «15 GB»" in antiguo  # forma anterior con texto: se juzga
    assert "`existente_del_cliente` sigue la regla del recurso que el cliente ya tiene" in VER


def test_el_experto_pone_la_region_global_y_la_ex_en_la_desviacion():
    assert "`region`: `global` (nunca la que diga la cita" in PLANO and "`region`: la que diga la cita" not in PLANO
    assert "con la `EX-nn` escrita en el texto" in PLANO  # experto.errores_existentes: «existente_valorado»


def test_la_ex_en_la_desviacion_es_lo_que_exige_el_nucleo():
    """Revisión R1 (3): la frase de las instrucciones casa con la regla real `existente_valorado` del núcleo."""
    import sys
    sys.path.insert(0, str(RAIZ / "sandbox"))
    from nucleo import experto  # noqa: E402
    import json
    cat = json.loads((RAIZ / "sandbox/datos/catalogo_componentes.json").read_text(encoding="utf-8"))
    req = {"campos": {"ya_contratado_por_cliente": {"estado": "CITADO", "entradas": [
        {"id": "EX-06", "servicio_catalogo": "az-api-management", "valor": "API Management",
         "cita": "Ya publicamos la API de RR. HH. con nuestro API Management.", "fuente": "F1", "origen": "CITADO"}]}}}

    fila = next(f for f in cat["componentes"] if f["id"] == "az-api-management")
    plantilla = next(x for x in fila["plantillas_precio"] if x["id"] == "consumo-llamadas")
    region = fila["region_ue"]
    precio = {"id": "P-01", "componente_id": "C-05", "plantilla_id": "consumo-llamadas", "cantidad_mensual": 1,
              "filtro": experto._filtro_de_plantilla(plantilla, fila, region)}

    def reglas(desviacion):
        comp = {"id": "C-05", "catalogo_id": "az-api-management", "servicio": "Azure API Management", "region": region,
                "existente_del_cliente": None, "motivo_no_valoracion": None, "desviacion_justificada": desviacion}
        resp = {"componentes": [comp], "precios": [precio]}
        return {e["regla"] for e in experto.errores_existentes(resp, req, cat)}
    assert experto.valorados_de({"componentes": [{"id": "C-05", "catalogo_id": "az-api-management", "region": region}],
                                 "precios": [precio]}, cat) == {"C-05": ["consumo-llamadas"]}  # control: valorado
    assert "existente_valorado" in reglas(None)
    assert "existente_valorado" in reglas("Hace falta otra pasarela aparte de la del cliente por aislamiento.")
    assert "existente_valorado" not in reglas("EX-06 publica otra API y su capacidad no admite esta carga.")


def test_el_verificador_describe_cada_campo_del_segmento_real_del_nucleo():
    """LES-G-088 (I1.9, tercera vuelta): la salida REAL de `experto.segmento_verificador_i19` (P cerró E19-9) pasa por
    lo que dicen las instrucciones: cada etiqueta que emite el núcleo aparece en el formato de línea del verificador."""
    import re
    import sys
    sys.path.insert(0, str(RAIZ / "sandbox"))
    from nucleo import experto  # noqa: E402
    if not hasattr(experto, "segmento_verificador_i19"):
        pytest.fail("el núcleo ya no expone segmento_verificador_i19: revisar el formato del verificador")
    from tests import i19_p_datos as D
    from tests.test_i19_p_existentes import caso_h1
    from tests.test_i19_p_niveles import JN_S1, caso, s1
    cat = D.catalogo_i19()
    r, br, req = caso_h1()
    _, c = D.analizar(r, br, req, cat)
    existente = experto.segmento_verificador_i19(D.comp_de(c, "C-06"), c, cat, req)
    br, req2, r, cat2 = caso(lambda r, c: s1(r, c, JN_S1), volumetria=["Unos 100 GB de documentos."])
    _, c2 = D.analizar(r, br, req2, cat2)
    nivel = experto.segmento_verificador_i19(D.comp_de(c2, "C-02"), c2, cat2, req2)
    formato = "\n".join(VER.splitlines()[:20])
    for seg, esperadas in ((existente, {"existente del cliente", "cita"}),
                           (nivel, {"nivel", "razon", "cita", "fuente_nivel"})):
        etiquetas = set(re.findall(r"\| ([a-z_ ]+?): ", seg))
        assert etiquetas == esperadas, seg
        assert all(f"| {e}: " in formato for e in etiquetas), (seg, etiquetas)


def test_tamanos_medidos():
    """El bloque viaja en cada vuelta del modelo: que no crezca sin medirlo (I1.9: 30,4 KB; el experto, 65,5 KB; el
    verificador, 23,7 KB tras la reanudación; I1.10, VC19-1: el bloque, 31,1 KB, y el experto, 66,9 KB)."""
    assert len(BLOQUE.encode("utf-8")) < 31500 and len(EXP.encode("utf-8")) < 67500 and len(VER.encode("utf-8")) < 24000
