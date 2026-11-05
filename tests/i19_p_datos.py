"""I1.9 · papel P: datos comunes de las pruebas (no es un fichero de pruebas).

- `catalogo_i19()`: el catálogo REAL del sandbox. El papel E ya trae (15-10-2026, 12:55) `nivel_por_defecto` con fuente
  y `razones_subida` por nivel y por plantilla de modelo; lo que una fila aún no traiga se completa con los datos de
  prueba de abajo (solo lo que falta: nunca se pisa lo de E).
- Hostelia (cliente ficticio de I1.8): la transcripción real del alta, los requisitos que DEBERÍA haber dado la
  extracción (una entrada por recurso, con la cita entera) y las respuestas REALES de las sesiones 1 y 2, pasadas a v5.
- `a_v5(modelo)`: pasa una respuesta v4 (lo que escribió el modelo) a la forma v5 sin cambiar nada más.
"""
from __future__ import annotations

import copy
import json

from tests.i17_p_datos import RAIZ
from nucleo import experto

LEARN = "https://learn.microsoft.com/azure/"
F_SEARCH = LEARN + "search/search-limits-quotas-capacity"
F_LIMITES = LEARN + "azure-resource-manager/management/azure-subscription-service-limits"
F_APIM = LEARN + "api-management/api-management-features"
F_FUNC = LEARN + "azure-functions/functions-premium-plan"
F_MODELOS = LEARN + "foundry/foundry-models/concepts/models-sold-directly-by-azure"
INST = json.loads((RAIZ / "sandbox" / "datos" / "precios_instantanea.json").read_text(encoding="utf-8"))
HOY = str(INST["fecha_consulta"])[:10]

POR_DEFECTO = {"az-ai-search": "Basic", "az-api-management": "Consumption"}
RAZONES = {
    ("az-ai-search", "S1"): [
        {"id": "documentos_sobre_basic", "tipo": "umbral", "campo": "volumetria", "unidad": ["documentos"],
         "limite": 100000, "fuente": F_SEARCH, "texto": "más documentos de los que caben en Basic (prueba)"}],
    ("az-app-service", "P0v3"): [
        {"id": "usuarios_sobre_basic", "tipo": "umbral", "campo": "volumetria", "unidad": ["usuarios", "empleados"],
         "limite": 5000, "fuente": F_LIMITES, "texto": "más usuarios de los que atiende B1 (prueba)"},
        {"id": "alta_disponibilidad", "tipo": "caracteristica", "palabras_clave": ["alta disponibilidad"],
         "fuente": F_LIMITES}],
    ("az-api-management", "Basic v2"): [
        {"id": "red_virtual", "tipo": "caracteristica", "campo": "red_privada",
         "palabras_clave": ["red privada", "integración con red virtual"], "fuente": F_APIM},
        {"id": "llamadas_sobre_consumo", "tipo": "umbral", "campo": "volumetria", "unidad": ["llamadas", "acciones"],
         "limite": 1000000, "fuente": F_APIM}],
    ("az-functions", "EP1"): [
        {"id": "sin_arranque_en_frio", "tipo": "caracteristica", "palabras_clave": ["sin arranque en frío"],
         "fuente": F_FUNC}]}
RAZONES_SOL = [{"id": "razonamiento_complejo", "tipo": "caracteristica", "palabras_clave": ["razonamiento complejo"],
                "fuente": F_MODELOS}]


def catalogo_i19(base: dict | None = None) -> dict:
    cat = copy.deepcopy(base) if base is not None else json.loads(
        (RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    for e in cat["componentes"]:
        if e["id"] in POR_DEFECTO and "nivel_por_defecto" not in e:
            fuente = next(n.get("fuente_url") for n in e["niveles"] if n.get("nivel") == POR_DEFECTO[e["id"]])
            e["nivel_por_defecto"] = {"nivel": POR_DEFECTO[e["id"]], "fuente": fuente}
        for n in e.get("niveles") or []:
            if (e["id"], n.get("nivel")) in RAZONES and "razones_subida" not in n:
                n["razones_subida"] = copy.deepcopy(RAZONES[(e["id"], n.get("nivel"))])
        for p in e.get("plantillas_precio") or []:
            if p.get("modelo") == "gpt-6-sol" and "razones_subida" not in p:
                p["razones_subida"] = copy.deepcopy(RAZONES_SOL)
    return cat


def fila(catalogo: dict, cid: str) -> dict:
    return next(e for e in catalogo["componentes"] if e["id"] == cid)


# ── Hostelia (I1.8, cliente ficticio): transcripción y estados reales de B ───────────────────────────────────────────
DIR_REAL = RAIZ / "pruebas" / "I18" / "REAL" / "B"
TRANSCRIPCION = (RAIZ / "datos_prueba" / "transcripcion_sintetica_I18_hostelia.txt").read_text(encoding="utf-8")
CITA_LICENCIAS = "Ya tenemos licencias de Microsoft 365 E3 para todos los empleados, con Teams y SharePoint incluidos."
CITA_API = ("El saldo de vacaciones y las solicitudes de días libres van a través de la API REST de RR. HH. que ya "
            "tenemos en Azure, en un App Service propio, publicada con API Management.")
EXISTENTES = [("EX-01", "az-microsoft-365", "Microsoft 365", CITA_LICENCIAS), ("EX-02", "az-teams", "Teams", CITA_LICENCIAS),
              ("EX-03", "az-sharepoint", "SharePoint", CITA_LICENCIAS),
              ("EX-04", None, "la API REST de RR. HH.", CITA_API), ("EX-05", "az-app-service", "App Service", CITA_API),
              ("EX-06", "az-api-management", "API Management", CITA_API)]


def entradas_existentes(lista=EXISTENTES) -> list[dict]:
    return [{"id": i, "servicio_catalogo": s, "valor": v, "cita": c, "fuente": "F1", "origen": "CITADO"}
            for i, s, v, c in lista]


def estado_hostelia(sesion: str = "hostelia_1/lista_A") -> dict:
    return json.loads((DIR_REAL / sesion / "estado.json").read_text(encoding="utf-8"))


def requisitos_hostelia(sesion: str = "hostelia_1/lista_A", existentes=None) -> dict:
    """Los requisitos reales de la sesión con lo que el cliente ya tiene como DEBIÓ extraerse: una entrada por recurso."""
    req = copy.deepcopy(estado_hostelia(sesion)["carga"]["requisitos"])
    req["campos"]["ya_contratado_por_cliente"] = {"estado": "CITADO", "entradas": existentes if existentes is not None
                                                  else entradas_existentes()}
    return req


def brief_hostelia(sesion: str, req: dict) -> dict:
    """El brief real de la sesión con la sección «Lo que el cliente ya tiene o paga» en la forma de I1.9 (cita entera)."""
    br = copy.deepcopy(estado_hostelia(sesion)["carga"]["briefs"][-1])
    cuerpo = br["texto"].split(experto.SECCION_CLIENTE)[0].rstrip("\n")
    lineas = experto.lineas_brief_existentes(req)
    br["texto"] = cuerpo + ("\n" + experto.SECCION_CLIENTE + "\n" + "\n".join(lineas) if lineas else "") + "\n"
    return br


def modelo_hostelia(sesion: str = "hostelia_1/lista_A") -> dict:
    """Lo que escribió el modelo en la respuesta registrada de la sesión (v4)."""
    return experto.proyectar_modelo(estado_hostelia(sesion)["carga"]["respuestas_expertos"]["azure"]["respuesta"])


def a_v5(modelo: dict, existentes: dict | None = None, niveles: dict | None = None) -> dict:
    """Respuesta v4 → v5: sin motivo_cita; «a_cargo_del_cliente» pasa a «existente_del_cliente» con la entrada que
    dice `existentes` ({C-nn: EX-nn}; sin ella, «no_aplica»); justificacion_nivel según `niveles` ({C-nn: jn v5 o None};
    las que no estén pasan a None)."""
    r = copy.deepcopy(modelo)
    for c in r["componentes"]:
        c.pop("motivo_cita", None)
        ex = (existentes or {}).get(c["id"])
        if c.get("motivo_no_valoracion") == "a_cargo_del_cliente" or ex:
            c["motivo_no_valoracion"] = "existente_del_cliente" if ex else "no_aplica"
        c["existente_del_cliente"] = {"entrada": ex} if ex else None
        c["justificacion_nivel"] = copy.deepcopy((niveles or {}).get(c["id"]))
        orden = ["id", "catalogo_id", "servicio", "capa", "sku", "region", "cantidad", "unidad", "referencia_id",
                 "desviacion_justificada", "motivo_no_valoracion", "existente_del_cliente", "incluido_en",
                 "justificacion_nivel"]
        for k in list(c):
            c[k] = c.pop(k)
        c.update({k: c.pop(k) for k in orden})
    return r


def con_brief(r: dict, br: dict) -> dict:
    r = copy.deepcopy(r)
    r["brief_recibido"], r["brief_id"] = br["texto"], br["brief_id"]
    return r


def perfiles_de(br: dict) -> list[str]:
    return br["texto"].split("perfiles_permitidos: ")[1].split("\n")[0].split("; ")


def analizar(r: dict, br: dict, req: dict, catalogo: dict):
    return experto.analizar_respuesta(r, br, catalogo, perfiles_de(br), req, INST, HOY)


def reglas_de(errores: list[str]) -> list[str]:
    """Los errores tal como los da analizar_respuesta, para buscar en ellos."""
    return list(errores)


# ── Igualdad con las réplicas de la puerta (docs/I1/CAMBIOS-I19-P/replicas_puerta.py) ──────────────────────────────
import sys  # noqa: E402

import verificar_paquete as vp  # noqa: E402

import importlib.util  # noqa: E402

# Con nombre propio: «replicas_puerta» ya es el módulo de I1.7 o I1.8 si otra prueba lo importó antes (sys.modules)
_spec = importlib.util.spec_from_file_location("replicas_puerta_i19",
                                               RAIZ / "docs" / "I1" / "CAMBIOS-I19-P" / "replicas_puerta.py")
R19 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R19)

if hasattr(vp, "existentes_r") and hasattr(vp, "arquitectura_r"):
    R19 = vp  # noqa: F811  (integrador I1.9: ya pegadas; se compara contra la puerta)


def reglas_i19(r: dict, br: dict, req: dict, catalogo: dict) -> dict:
    """Reglas del núcleo sobre la completada (lo que tocó I1.9) y la misma lista de las réplicas, que tiene que ser igual
    regla a regla y en el mismo orden (LES-G-097). Devuelve {grupo: [(id, regla)]} y la completada."""
    c, faltas = experto.completar(r, catalogo, INST, req, br["texto"])
    rec, fallos = R19.completar_r(R19.proyectar_r(c), catalogo, INST, req, br["texto"])
    assert rec == c and fallos == [(x["id"], x["regla"]) for x in faltas]
    assert R19.proyectar_r(c) == experto.proyectar_modelo(c)
    salida = {"completar": [(x["id"], x["regla"]) for x in faltas],
              "volumen_nivel": [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(c, br["texto"], req, catalogo)],
              "existentes": [(x["id"], x["regla"]) for x in experto.errores_existentes(c, req, catalogo)],
              "arquitectura": [(x["id"], x["regla"]) for x in experto.errores_arquitectura(c, catalogo)],
              "ciclo": [(x["id"], x["regla"]) for x in experto.errores_ciclo_vida(
                  c, catalogo, HOY, experto.duracion_gantt(experto.proyectar_modelo(c)))]}
    assert salida["volumen_nivel"] == R19.errores_volumen_nivel_replica(c, br["texto"], req, catalogo)
    assert salida["existentes"] == R19.existentes_r(c, req, catalogo)
    assert salida["arquitectura"] == R19.arquitectura_r(c, catalogo)
    assert salida["ciclo"] == R19.ciclo_r(c, catalogo, HOY, vp.semanas_r(R19.proyectar_r(c)))
    from nucleo import anexo_consumo
    assert [x["componente_id"] for x in anexo_consumo.facturables_azure(c, catalogo)] == \
        R19.facturables_azure_replica(c, catalogo)
    for comp in c["componentes"]:
        assert bool(experto.region_exige_catalogo(comp)) == R19.region_exige_catalogo_replica(comp)
    assert experto.lineas_brief_existentes(req) == R19.lineas_brief_existentes_r(req)
    salida["completada"] = c
    return salida


def comp_de(r: dict, cid: str) -> dict:
    return next(c for c in r["componentes"] if c["id"] == cid)


def v4_a_v5(resp: dict, catalogo: dict) -> dict:
    """SOLO PARA PRUEBAS: una respuesta del modelo v4 (o v3 ya pasada a v4) con la forma v5: sin motivo_cita, con
    existente_del_cliente null y la justificacion_nivel de I1.7 ({nivel, requisito, límite, fuente}) como {nivel, razon:
    la primera razón de ese nivel en el catálogo (o «sin_razon»), cita: el requisito}."""
    r = copy.deepcopy(resp)
    filas = {e.get("id"): e for e in catalogo.get("componentes") or [] if isinstance(e, dict)}
    for c in r.get("componentes") or []:
        if not isinstance(c, dict):
            continue
        c.pop("motivo_cita", None)
        c.setdefault("existente_del_cliente", None)
        jn = c.get("justificacion_nivel")
        if isinstance(jn, dict) and "requisito" in jn:
            nivel = next((n for n in experto.niveles_de(filas.get(c.get("catalogo_id")))
                          if experto._plano_req(jn.get("nivel")) in n["nombres"]), None)
            razones = nivel["razones"] if nivel and isinstance(nivel["razones"], list) else []
            c["justificacion_nivel"] = {"nivel": jn.get("nivel"), "razon": razones[0]["id"] if razones else "sin_razon",
                                        "cita": jn.get("requisito")}
    return r


def validar(resp: dict, brief: dict, catalogo: dict, perfiles: list[str], requisitos: dict | None = None,
            hoy: str | None = None) -> list[str]:
    """Como tests/i17_int.validar, con la respuesta pasada a v5 (v4_a_v5) antes de validarla."""
    from tests import i17_int
    if i17_int.es_v3(resp):
        resp = i17_int.a_v4(resp, catalogo)
    return experto.validar_respuesta(v4_a_v5(resp, catalogo), brief, catalogo, perfiles, requisitos,
                                     i17_int.instantanea_para(catalogo), hoy)


def pegar_replicas_i19(monkeypatch) -> None:
    """Simula el pegado de docs/I1/CAMBIOS-I19-P/replicas_puerta.py en verificar_paquete (§7): cada nombre público de
    las réplicas sustituye al de la puerta durante la prueba (las funciones de la puerta los buscan en su módulo al
    llamarlos). Si el integrador ya las pegó, no hace nada."""
    if hasattr(vp, "existentes_r") and hasattr(vp, "arquitectura_r"):
        return
    for nombre, valor in vars(R19).items():
        if not nombre.startswith("__") and not isinstance(valor, type(sys)):   # funciones y constantes, no módulos
            monkeypatch.setattr(vp, nombre, valor, raising=False)
