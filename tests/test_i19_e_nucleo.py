"""I1.9, papel E: el catálogo v8 contra el núcleo de P (experto.razones_validas, razon_cumplida, nivel_por_defecto y
errores_volumen_nivel). Toda razón del catálogo es legible y alcanzable; ninguna se cumple con las citas que en I1.8
subieron un nivel sin dimensionarlo (VC18-1, PR18-3); y los casos del contrato común dan la regla esperada."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
from nucleo import experto  # noqa: E402
from tests.i19_e_comun import ALCANCE, BRIEF, CONS, DOCS, GB, REQ, SESIONES, jn  # noqa: E402

CAT = json.loads((RAIZ / "sandbox/datos/catalogo_componentes.json").read_text(encoding="utf-8"))
INST = json.loads((RAIZ / "sandbox/datos/precios_instantanea.json").read_text(encoding="utf-8"))
FILAS = {e["id"]: e for e in CAT["componentes"]}
CON_NIVELES = [e for e in CAT["componentes"] if e.get("niveles")]
# Citas de I1.8 que justificaron un nivel sin dimensionarlo (PRUEBA-REAL §2-§4, VERIFICACION-CONSUMO §7)
NO_DIMENSIONAN = ["API Management", "API Management.", "Microsoft Teams", "Se aplica el RGPD.", DOCS,
                  "API REST de RR. HH. que ya tienen en Azure.", "Aproximadamente 800 documentos.",
                  "Responder sobre las políticas de RR. HH. usando documentos de SharePoint",
                  "Los permisos se asignan mediante grupos de Entra ID", "Aproximadamente 6.000 consultas al mes.",
                  "No se requiere red privada.", "Sin red privada: acceso público con Entra ID."]  # E19-3


def _todas_las_razones():
    for e in CON_NIVELES:
        for n in experto.niveles_de(e):
            for r in n["razones"] or []:
                yield f"{e['id']}/{n['etiqueta']}/{r['id']}", r
    for m in ("gpt-6-sol", "gpt-6.1-sol"):
        for r in experto.razones_modelo(CAT, m):
            yield f"modelo {m}/{r['id']}", r


RAZONES = list(_todas_las_razones())


def test_el_nucleo_lee_todas_las_razones_y_cada_fila_su_valor_por_defecto():
    for e in CON_NIVELES:
        assert all(n["razones"] is not False for n in experto.niveles_de(e)), e["id"]
        assert experto.nivel_por_defecto(e) is not None, e["id"]
    assert experto.modelo_por_defecto(CAT) == "gpt-6-luna"
    assert len(RAZONES) >= 40


# E19-8, cerrado por P en la reanudación de I1.9: experto.afirmada solo corta en un signo seguido de espacio o fin, y
# «gpt-6.1-sol» ya se puede nombrar (era un xfail estricto).
CASOS_RAZON = [pytest.param(d, r, id=d) for d, r in RAZONES]


@pytest.mark.parametrize("donde, razon", CASOS_RAZON)
def test_cada_razon_se_puede_cumplir_y_no_con_lo_que_no_dimensiona(donde, razon):
    if razon["tipo"] == "umbral":
        cita = f"Unos {int(razon['limite'] * 4) + 1} {razon['palabras'][0]} al mes."
    else:
        cita = f"El cliente pide {razon['palabras_clave'][0]} en la solución."
    assert experto.razon_cumplida(razon, cita), (donde, cita)
    assert not any(experto.razon_cumplida(razon, x) for x in NO_DIMENSIONAN), donde


def _comp(fid, nivel=None, razon=None, sku="estándar", cita=None):
    e = FILAS[fid]
    return {"id": "C-01", "catalogo_id": fid, "servicio": e["nombre_oficial"], "capa": e["capa"], "sku": sku,
            "region": e.get("region_precio") and "westeurope" or e.get("region_ue"), "cantidad": 1, "unidad": "recurso",
            "referencia_id": None, "desviacion_justificada": None, "motivo_no_valoracion": "no_aplica",
            "existente_del_cliente": None, "incluido_en": None,
            "justificacion_nivel": jn(nivel, razon, cita) if razon else None}


def _p(i, plantilla, n=None, cita=None, base=None, unidad=None):
    b = None if cita is None else {"cita": cita, "cantidad_base": base, "unidad_base": unidad}
    return {"id": f"P-0{i}", "componente_id": "C-01", "plantilla_id": plantilla, "instancias": n if b is None else None,
            "base_volumen": b, "factor_override": None}


def _reglas(comp, precios):
    resp = {"arquitectura_id": "foundry-chat-basica", "referencias": [], "componentes": [comp], "precios": precios}
    c, errs = experto.completar(resp, CAT, INST, REQ, BRIEF)
    return {e["regla"] for e in errs + experto.errores_volumen_nivel(c, BRIEF, REQ, CAT)}


LLAMADAS = _p(1, "consumo-llamadas", cita=CONS, base=2000, unidad="consultas")
SOL = [_p(1, "gpt-6-sol-entrada", cita=CONS, base=2000, unidad="consultas"),
       _p(2, "gpt-6-sol-salida", cita=CONS, base=2000, unidad="consultas")]
CASOS = [
    ("apim_consumo_por_defecto", _comp("az-api-management"), [LLAMADAS], set()),
    ("apim_standard_v2_con_su_razon", _comp("az-api-management", "Standard v2", "portal_desarrolladores"),
     [_p(1, "standard-v2", 1)], set()),
    ("apim_standard_v2_sin_dimensionar", _comp("az-api-management", "Standard v2", "nivel_nombrado", cita=CONS),
     [_p(1, "standard-v2", 1)], {"razon_no_cumplida"}),
    ("apim_basic_v2_sin_justificar", _comp("az-api-management"), [_p(1, "basic-v2", 1)], {"nivel_sin_justificar"}),
    ("search_basic_justificado_de_mas", _comp("az-ai-search", "Basic", "sla_replicas", cita=ALCANCE["varias_regiones"]),
     [_p(1, "basic", 1)], {"justificacion_sobrante", "nivel_insuficiente"}),  # VC19-1: 60 GB citados > 45 de Basic
    ("search_s1_por_red_privada", _comp("az-ai-search", "S1", "privado_red"), [_p(1, "s1", 1)], set()),
    ("search_s1_por_gb", _comp("az-ai-search", "S1", "almacenamiento", cita=GB), [_p(1, "s1", 1)], set()),  # 60 > 45
    ("search_s1_por_documentos", _comp("az-ai-search", "S1", "almacenamiento", cita=DOCS), [_p(1, "s1", 1)],
     {"razon_no_cumplida"}),  # «3.000 documentos» no son gigabytes: el umbral no confunde la unidad
    ("sql_s0_por_sesiones", _comp("az-sql-database", "S0", "sesiones", cita=SESIONES), [_p(1, "s0", 1)],
     {"nivel_insuficiente"}),  # VC19-1: 1.200 sesiones citadas superan las 900 de S1: hace falta GP_Gen5_2
    ("sql_basic_por_defecto", _comp("az-sql-database"), [_p(1, "basic", 1)], {"nivel_insuficiente"}),  # ídem
    ("b1_dos_sin_razon", _comp("az-app-service"), [_p(1, "b1-linux", 2)], {"instancias_sin_justificar"}),
    ("b1_dos_alta_disponibilidad", _comp("az-app-service", "B1", "alta_disponibilidad"), [_p(1, "b1-linux", 2)],
     set()),  # Revisión E2: el recorrido completo con una cita literal que cumple la razón
    ("b1_dos_cita_ajena", _comp("az-app-service", "B1", "alta_disponibilidad", cita="Alta disponibilidad 24x7."),
     [_p(1, "b1-linux", 2)], {"requisito_no_literal"}),  # la cita no está en los requisitos
    ("b1_cuatro_sobre_el_tope", _comp("az-app-service", "B1", "alta_disponibilidad"), [_p(1, "b1-linux", 4)],
     {"instancias_sobre_limite"}),
    ("sol_sin_justificar", _comp("az-foundry", sku="gpt-6-sol"), SOL, {"modelo_sin_justificar"}),
    ("sol_nombrado", _comp("az-foundry", "gpt-6-sol", "modelo_nombrado", sku="gpt-6-sol"), SOL, set()),
    ("bot_estandar", _comp("az-bot-service"), [_p(1, "canales-estandar", cita=CONS, base=2000, unidad="consultas")],
     set()),
    ("bot_premium_sin_justificar", _comp("az-bot-service"),
     [_p(1, "canales-premium", cita=CONS, base=2000, unidad="consultas")], {"nivel_sin_justificar"}),
    ("defender_solo_storage", _comp("az-defender-cloud"),
     [_p(1, "almacenamiento-malware", cita=DOCS, base=3000, unidad="documentos")], set()),
    ("defender_p2_sin_justificar", _comp("az-defender-cloud"), [_p(1, "servidores-p2", 1)], {"nivel_sin_justificar"}),
    ("adf_sin_movimiento", _comp("az-data-factory"), [_p(1, "orquestacion", cita=DOCS, base=3000, unidad="documentos")],
     {"falta_medidor_obligatorio"}),
    ("adf_con_movimiento", _comp("az-data-factory"), [
        _p(1, "orquestacion", cita=DOCS, base=3000, unidad="documentos"),
        _p(2, "movimiento-datos", cita=DOCS, base=3000, unidad="documentos")], set()),
    ("postgresql_por_defecto", _comp("az-postgresql"), [_p(1, "d2ds-v5", 1), _p(2, "almacenamiento", 1)], set()),
    ("postgresql_b1ms_sin_razon", _comp("az-postgresql"), [_p(1, "b1ms", 1), _p(2, "almacenamiento", 1)],
     {"nivel_sin_justificar"}),
]


@pytest.mark.parametrize("comp, precios, esperadas", [c[1:] for c in CASOS], ids=[c[0] for c in CASOS])
def test_casos_del_contrato_comun(comp, precios, esperadas):
    assert _reglas(comp, precios) == esperadas


def test_la_negacion_no_cumple_la_caracteristica():
    """El núcleo de P ya no da por cumplida una palabra clave negada en las 4 palabras anteriores. El catálogo además
    quitó «red privada» de las listas: «Red privada: no necesaria.» niega DESPUÉS de la palabra y la guarda no lo ve."""
    privado = next(r for n in experto.niveles_de(FILAS["az-api-management"]) for r in n["razones"] or []
                   if r["id"] == "privado_red")
    assert not experto.razon_cumplida(privado, "No se requiere punto de conexión privado.")
    assert experto.razon_cumplida(privado, "Todo privado, con punto de conexión privado en cada servicio.")
    assert not experto.razon_cumplida(privado, "Red privada: no necesaria.")  # sin «red privada» en las listas
    # E19-3, cerrado por P (NEGACION_TRAS): una negación en las palabras que siguen a la palabra clave también la anula
    assert not experto.razon_cumplida(privado, "Punto de conexión privado: no requerido.")
    assert experto.razon_cumplida(privado, "Punto de conexión privado: no solo en la base de datos.")


def test_estado_actual_e19_8_modelo_con_punto():
    """E19-8 cerrado: «gpt-6.1-sol» no se parte por su punto; un punto final de oración sigue cortando."""
    razon = experto.razones_modelo(CAT, "gpt-6.1-sol")[0]
    assert experto.razon_cumplida(razon, "El cliente pide gpt-6.1-sol en la solución.")
    assert experto.razon_cumplida(razon, "Modelo: gpt-6.1-sol.")
    assert not experto.razon_cumplida(razon, "No queremos gpt-6.1-sol.")
    assert experto.razon_cumplida(experto.razones_modelo(CAT, "gpt-6-sol")[0], "El cliente pide gpt-6-sol.")


def test_e19_3_la_unidad_del_umbral_no_se_toma_de_otra_magnitud():
    """E19-3 / Revisión E1, cerrado por P (VENTANA_UNIDAD): «46 consultas al mes; el almacenamiento, en GB» no son 46 GB."""
    razon = next(r for n in experto.niveles_de(FILAS["az-ai-search"]) for r in n["razones"] or []
                 if r["id"] == "almacenamiento")
    assert not experto.razon_cumplida(razon, "Unas 46 consultas al mes; el almacenamiento, en GB.")
    assert experto.razon_cumplida(razon, "Unos 60 GB de documentos.")
    assert not experto.razon_cumplida(razon, "Unos 40 GB de documentos.")
