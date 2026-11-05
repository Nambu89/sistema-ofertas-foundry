"""Genera los ejemplos coherentes de esquemas/ejemplos/ (un caso sintético: OF-KELVARA-001-A).

Los ejemplos son el contrato con datos: los constructores los usan como fixtures. Todo es
inventado (empresa, personas, precios y horas); las URL de Learn son de ejemplo y no se han
comprobado. Los SHA-256 y hashes sí se calculan de verdad, para que los ejemplos cuadren entre sí.
Uso: python esquemas/ejemplos/generar_ejemplos.py   (reescribe los JSON de esta carpeta)
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(DIR.parents[1] / "sandbox"))
from nucleo import esquema as nucleo_esquema, experto as nucleo_experto  # noqa: E402  (I1.7: la completada la hace el núcleo)
from nucleo import anexo_consumo as nucleo_anexo, verificacion as nucleo_verificacion  # noqa: E402  (integrador I1.7)
TRANSCRIPCION = DIR.parents[1] / "datos_prueba" / "transcripcion_sintetica_I1.txt"
CODIGO_BASE, VERSION = "OF-KELVARA-001", "A"
CODIGO = f"{CODIGO_BASE}-{VERSION}"
FECHA = "2026-10-08"
PERFILES = ["AI Architect / Tech Lead", "Senior AI / Foundry Engineer", "Integration Engineer / Salesforce",
            "Data & BI Engineer", "AI Engineer / Tech Lead", "Project Manager", "Consultor Junior"]
# Tarifa SINTÉTICA (la de tests/insumos/rate-card.sintetica.json): la tarifa real no se publica.
TARIFAS = {"AI Architect / Tech Lead": 110.0, "Senior AI / Foundry Engineer": 100.25, "Integration Engineer / Salesforce": 95.0,
           "Data & BI Engineer": 90.0, "AI Engineer / Tech Lead": 100.0, "Project Manager": 85.0, "Consultor Junior": 70.0}
HITOS_TARIFA = ["Kick-off y Discovery completado", "Entregable principal en entorno dev",
                "Piloto/MVP en producción controlada", "Evaluación final y cierre"]


def canonico(obj: object) -> bytes:
    """JSON canónico de CONTRATOS.md §5 (igual que lib/hashes.json_canonico)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha(b: bytes | str) -> str:
    return hashlib.sha256(b.encode("utf-8") if isinstance(b, str) else b).hexdigest()


def eur(x: Decimal) -> str:
    return str(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _cit(valor: str, cita: str) -> dict:
    return {"valor": valor, "cita": cita, "fuente": "F1", "origen": "CITADO"}


def _asu(valor: str) -> dict:
    return {"valor": valor, "cita": None, "fuente": None, "origen": "ASUMIDO"}


def requisitos() -> dict:
    c = {
        "objetivo": [_cit("Asistente de IA que responda en lenguaje natural a los técnicos y cite siempre el informe o la norma de origen",
                          "un asistente de IA que responda en lenguaje natural y cite siempre el informe o la norma")],
        "nubes": [_cit("Azure", "Queremos que esto viva en Azure, no queremos abrir otra nube")],
        "alcance_funcional": [
            _cit("Búsqueda en informes de ensayo y procedimientos internos con cita al documento y a la página",
                 "buscar en los informes de ensayo y en los procedimientos internos y responder con la cita al documento y a la página"),
            _cit("Resumen de un informe largo en un párrafo comprensible para el equipo comercial",
                 "resumir un informe largo en un párrafo que entienda un comercial"),
            _cit("Comparación de dos ensayos del mismo material indicando qué ha cambiado",
                 "comparar dos ensayos del mismo material y decir qué ha cambiado entre ellos"),
            _cit("Respuesta explícita cuando no encuentra la información, sin inventar",
                 "diga claramente cuando no encuentra la respuesta, en vez de inventarse algo")],
        "canales_integraciones": [_cit("Microsoft Teams", "Desde Microsoft Teams, que es donde trabaja todo el mundo")],
        "ubicacion_usuarios": [_cit("España (laboratorios de Zaragoza y Tarragona)", "todos están en España. No hay usuarios fuera")],
        "marco_normativo": [_cit("RGPD, con datos en la Unión Europea",
                                 "Por tanto aplica el RGPD. Y nos pedirán que los datos se queden en la Unión Europea")],
        "volumetria": [_asu("150 técnicos usuarios y unos 20.000 documentos (informes, procedimientos y normas)")],
        "identidad_acl_origen": [_asu("Documentos en SharePoint Online del tenant del cliente, con permisos por grupos de Entra ID que se respetan en las respuestas")],
        "red_privada": [_cit("Servicios sin exposición a internet, con acceso privado y puntos de conexión privados donde se pueda",
                             "los servicios no queden expuestos a internet: acceso privado desde nuestra red")],
        "tipo_suscripcion": [_cit("Enterprise Agreement directo con Microsoft",
                                  "un contrato Enterprise Agreement directo con Microsoft, no a través de un revendedor")],
        "plazo": [_cit("Piloto funcionando en unos tres meses desde el arranque",
                       "tener el piloto funcionando en unos tres meses desde que arranquemos")],
        "presupuesto_orientativo": [_cit("Entre cuarenta y cincuenta mil euros para el piloto, sin consumo de Azure",
                                         "una cifra orientativa de entre cuarenta y cincuenta mil euros, sin contar el consumo de Azure")],
        "idioma_oferta": [_cit("Castellano", "Sí, la propuesta en castellano, por favor")],
        "fuera_de_alcance": [
            _cit("Integración con el LIMS, el sistema de gestión del laboratorio",
                 "La integración con el LIMS, el sistema de gestión del laboratorio, queda fuera de esta fase"),
            _cit("Integración con SAP", "Y nada de SAP por ahora. Eso sería, como mucho, una fase posterior")],
    }
    campos = {k: {"estado": "ASUMIDO" if v[0]["origen"] == "ASUMIDO" else "CITADO", "entradas": v} for k, v in c.items()}
    return {"schema": "preventa-requisitos/1", "campos": campos}


def catalogo() -> dict:
    # PR16-1 (arreglos I1.6): la referencia_url de cada fila es la del catálogo real (el núcleo la impone).
    filas = [
        ("az-foundry", "Microsoft Foundry", "ia", "Foundry Models", "https://learn.microsoft.com/azure/foundry/what-is-foundry"),
        ("az-ai-search", "Azure AI Search", "datos_conocimiento", "Azure Cognitive Search", "https://learn.microsoft.com/azure/search/search-what-is-azure-search"),
        ("az-bot-service", "Azure AI Bot Service", "usuarios_canales", "Azure Bot Service", "https://learn.microsoft.com/azure/bot-service/bot-overview"),
        ("az-app-service", "Azure App Service", "aplicacion_integracion", "Azure App Service", "https://learn.microsoft.com/azure/app-service/overview"),
        ("az-entra-id", "Microsoft Entra ID", "identidad_seguridad_red", None, "https://learn.microsoft.com/entra/fundamentals/what-is-entra"),
        ("az-private-link", "Azure Private Link", "identidad_seguridad_red", "Virtual Network", "https://learn.microsoft.com/azure/private-link/private-link-overview"),
        ("az-monitor", "Azure Monitor", "operacion_observabilidad", "Azure Monitor", "https://learn.microsoft.com/azure/azure-monitor/overview"),
    ]
    comps = [{"id": i, "nombre_oficial": n, "capa": c, "service_name_precios": s, "referencia_url": u} for i, n, c, s, u in filas]
    # PR17-1 (arreglos I1.7): el núcleo titula la referencia de cada componente con el título PUBLICADO de su página
    # (leído en Learn el 13-10-2026, pruebas/I17/ARREGLOS/titulos_learn.json), como el catálogo real v6.
    for comp in comps:
        comp["referencia_titulo"] = TITULOS_LEARN[comp["id"]]
    # I1.5 (decisión 1, CAMBIOS-I15-E): el filtro de cada precio es EXACTAMENTE una plantilla de su fila, como en el
    # catálogo real (las dos primeras, copiadas de catalogo/catalogo_componentes.json; la de Private Link, la del ejemplo).
    # I1.6 (decisión 4, contrato común con E): cada plantilla lleva su impulsor («tiempo» o «volumen») y su divisor de
    # unidad; las de Foundry (gpt-5-mini-entrada) y Bot Service (canales-premium) son las del catálogo real, para los
    # precios unitarios de referencia de los dos componentes con «depende_del_volumen» (la volumetría del ejemplo está
    # ASUMIDA, no CITADA).
    t, v = {"impulsor": "tiempo", "divisor": 1}, {"impulsor": "volumen"}
    # I1.7 (decisión 2 del comercial): modelo por defecto gpt-6-luna (Data Zone, Sweden Central) con su ciclo de vida y los
    # factores estándar en el catálogo, con fuente (CAMBIOS-I17-P §2; el catálogo real lo deriva el papel E).
    extra = {"az-foundry": {"region_ue": "swedencentral",
                            "plantillas_precio": [{"id": "gpt-6-luna-entrada", "filtro": "serviceName eq 'Foundry Models' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and meterName eq '6-luna ShortCo Inp Std DZ 1M Tokens'", **v, "divisor": 1000000,
                                                   "por_defecto": True, "modelo": "gpt-6-luna", "contexto": "corto",
                                                   "factor_estandar": FACTOR_ENTRADA["id"], "ciclo_vida": CICLO_LUNA}]},
             "az-ai-search": {"producto_precios": "Azure AI Search", "region_ue": "francecentral",
                              "plantillas_precio": [{"id": "s1", "filtro": "serviceName eq 'Azure Cognitive Search' and productName eq 'Azure AI Search' and armRegionName eq 'francecentral' and priceType eq 'Consumption' and meterName eq 'Standard S1 Unit'", **t}]},
             "az-bot-service": {"producto_precios": "Azure Bot Service", "region_ue": "westeurope", "region_precio": "Global",
                                "plantillas_precio": [{"id": "canales-estandar", "filtro": "serviceName eq 'Azure Bot Service' and productName eq 'Azure Bot Service' and armRegionName eq 'Global' and priceType eq 'Consumption' and meterName eq 'Free Standard Channel Messages'", **v, "divisor": 1000,
                                                       "factor_estandar": FACTOR_BOT["id"]},
                                                      {"id": "canales-premium", "filtro": "serviceName eq 'Azure Bot Service' and productName eq 'Azure Bot Service' and armRegionName eq 'Global' and priceType eq 'Consumption' and meterName eq 'S1 Premium Channel Messages'", **v, "divisor": 1000,
                                                       "factor_estandar": FACTOR_BOT["id"]}]},
             "az-app-service": {"region_ue": "swedencentral",
                                "plantillas_precio": [{"id": "b1-linux", "filtro": "serviceName eq 'Azure App Service' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and meterName eq 'B1'", **t,
                                                       "concepto": "B1 (Azure App Service Basic Plan - Linux)"},
                                                      {"id": "p0v3-linux", "filtro": "serviceName eq 'Azure App Service' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and armSkuName eq 'Azure_App_Service_Premium_v3_Plan_Linux_P0_v3' and meterName eq 'P0v3 App'", **t}]},
             # I1.6 (REV15-3): la fila real de Private Link (serviceName «Virtual Network», producto propio y precio Global);
             # antes el ejemplo usaba el auxiliar «Azure Private Link», que ya no cubre ni acompaña a su propio servicio.
             "az-private-link": {"producto_precios": "Virtual Network Private Link", "region_ue": "global", "region_precio": "Global",
                                 "plantillas_precio": [{"id": "punto-conexion", "filtro": "serviceName eq 'Virtual Network' and productName eq 'Virtual Network Private Link' and armRegionName eq 'Global' and priceType eq 'Consumption' and meterName eq 'Standard Private Endpoint'", **t}]}}
    for comp in comps:
        comp.update(extra.get(comp["id"], {}))
        for pl in comp.get("plantillas_precio") or []:  # integrador I1.6: el esquema de E exige el concepto
            pl.setdefault("concepto", pl["filtro"].rsplit("meterName eq '", 1)[1].rstrip("'"))
    for cid in ("az-ai-search", "az-app-service"):  # I1.6: niveles del catálogo real (los deriva E), si ya los trae
        niveles = con_razones(cid)  # integrador I1.6: también App Service (C-04 lleva justificacion_nivel)
        if niveles:
            fila = next(c for c in comps if c["id"] == cid)
            fila["niveles"] = niveles
            real = next((c.get("nivel_por_defecto") for c in json.loads((DIR.parents[1] / "sandbox" / "datos" /
                         "catalogo_componentes.json").read_text(encoding="utf-8"))["componentes"] if c["id"] == cid), None)
            if real or cid in POR_DEFECTO_I19:  # I1.9: el nivel por defecto con su fuente (VC18-1), el real si lo hay
                fila["nivel_por_defecto"] = dict(real or POR_DEFECTO_I19[cid])
    # Integrador I1.7: la forma del catálogo real (esquema de E): factores en la raíz, citados por id desde la plantilla
    return {"schema": "preventa-catalogo/1", "version": 1, "fecha": FECHA, "factores_estandar": [FACTOR_ENTRADA, FACTOR_BOT],
            "modelo_por_defecto": MODELO_POR_DEFECTO, "computo_por_defecto": computo_real(),
            "arquitecturas_referencia": [ARQUITECTURA], "componentes": comps}


def computo_real() -> dict:
    """I1.9: el cómputo por defecto del catálogo real (App Service B1), para que el ejemplo valore B1 sin justificar."""
    real = json.loads((DIR.parents[1] / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    return copy.deepcopy(real["computo_por_defecto"])


L17 = "https://learn.microsoft.com/azure/"
TITULOS_LEARN = {"az-foundry": "What is Microsoft Foundry?", "az-ai-search": "What is Azure AI Search?",
                 "az-bot-service": "Choose the right chatbot solution for your use case",
                 "az-app-service": "App Service overview", "az-entra-id": "What is Microsoft Entra?",
                 "az-private-link": "What is Azure Private Link?", "az-monitor": "Azure Monitor overview"}
CICLO_LUNA = {"ga": "2026-09-22", "retirada": None, "fuente": L17 + "foundry/foundry-models/concepts/models-sold-directly-by-azure"}
FACTOR_ENTRADA = {"id": "asistente_rag.tokens_entrada_por_consulta", "caso_uso": "asistente_rag", "valor": 2500,
                  "unidad": "tokens de entrada por consulta", "unidad_base": "consultas", "base": ["consulta"],
                  "tipo": "supuesto", "fuente_url": L17 + "foundry/openai/how-to/manage-costs", "consultado": FECHA,
                  "justificacion": "Pregunta, instrucciones del sistema y unos 5 fragmentos recuperados por consulta.",
                  "desglose": [{"parte": "pregunta, instrucciones y fragmentos recuperados", "valor": 2500,
                                "origen": "valor de ejemplo del contrato"}]}
FACTOR_BOT = {"id": "bot.mensajes_por_consulta", "caso_uso": "bot", "valor": 2, "unidad": "mensajes por consulta",
              "unidad_base": "consultas", "base": ["consulta"], "tipo": "oficial",
              "fuente_url": L17 + "bot-service/bot-service-overview", "consultado": FECHA,
              "justificacion": "La pregunta del usuario y la respuesta del bot: dos mensajes de canal por consulta.",
              "desglose": [{"parte": "pregunta y respuesta", "valor": 2, "origen": "un mensaje de canal cada una"}]}
# Integrador I1.7: el id y la URL son los del catálogo real (las pruebas de flujo completan el ejemplo con él)
ARQUITECTURA = {"id": "foundry-chat-base", "titulo": "Arquitectura de referencia de chat con Microsoft Foundry",
                "url": L17 + "architecture/ai-ml/architecture/baseline-microsoft-foundry-chat", "consultado": FECHA,
                "cuando_usar": "Chat con Microsoft Foundry en producción, con red privada y alta disponibilidad."}
# I1.9 (VC18-5): el modelo por defecto, como en el catálogo real (gpt-6-luna, Data Zone, Sweden Central)
MODELO_POR_DEFECTO = {"componente": "az-foundry", "modelo": "gpt-6-luna", "plantillas": ["gpt-6-luna-entrada"],
                      "region": "swedencentral", "despliegue": "DataZoneStandard",
                      "motivo": "Decisión del comercial (13-10-2026): modelo por defecto de la propuesta.",
                      "fuente_url": L17 + "foundry/foundry-models/concepts/models-sold-directly-by-azure",
                      "region_fuente_url": L17 + "foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability",
                      "consultado": FECHA}
CLAVES_I17_FILA = ("factores_estandar", "incluye")
CLAVES_I17_PLANTILLA = ("ciclo_vida", "factor_estandar")


def catalogo_para_escribir(cat: dict) -> tuple[dict, bool]:
    """(catálogo de ejemplo, completo). Mientras el esquema del catálogo (papel E) no admita lo de I1.9 (nivel por
    defecto y razones de subida) o lo de I1.7, el ejemplo sale sin esos campos (primero sin los de I1.9 y, si aún no
    valida, también sin los de I1.7) y se avisa; la completada de ejemplo se calcula siempre con el catálogo completo."""
    def valida(c: dict) -> bool:
        return not nucleo_esquema.validar(c, nucleo_esquema.cargar("catalogo_componentes"))

    if valida(cat):
        return cat, True
    base = copy.deepcopy(cat)
    for e in base["componentes"]:
        e.pop("nivel_por_defecto", None)
        for n in e.get("niveles") or []:
            n.pop("razones_subida", None)
    if valida(base):
        return base, False
    base.pop("arquitecturas_referencia", None)
    if not valida(base):
        base.pop("modelo_por_defecto", None)
    for e in base["componentes"]:
        for k in CLAVES_I17_FILA:
            e.pop(k, None)
        for p in e.get("plantillas_precio") or []:
            for k in CLAVES_I17_PLANTILLA:
                p.pop(k, None)
    return base, False


def instantanea(cat: dict) -> dict:
    """Instantánea de ejemplo con TODAS las plantillas del catálogo (precios del ejemplo anterior, de Retail Prices)."""
    precios = {"gpt-6-luna-entrada": (0.1056, "1M", "2026-09-01T00:00:00Z"), "s1": (0.3426, "1 Hour", "2024-11-01"),
               "b1-linux": (0.0158, "1 Hour", "2021-06-08T00:00:00Z"),
               "canales-estandar": (0.0, "1K", "2017-12-13T00:00:00Z"),
               "canales-premium": (0.44, "1K", "2017-12-13T00:00:00Z"), "p0v3-linux": (0.0864, "1 Hour", "2024-06-01"),
               "punto-conexion": (0.0088, "1 Hour", "2020-02-01T00:00:00Z")}
    arts = {}
    for e in cat["componentes"]:
        for p in e.get("plantillas_precio") or []:
            pr, unidad, desde = precios[p["id"]]
            region = p["filtro"].split("armRegionName eq '")[1].split("'")[0]
            arts[f"{e['id']}/{p['id']}"] = {"filtro": p["filtro"], "precio_unitario": pr, "unidad": unidad,
                                            "effectiveStartDate": desde, "meterName": p["concepto"],
                                            "productName": e.get("producto_precios") or e["service_name_precios"],
                                            "skuName": p["concepto"].split(" ")[0], "armRegionName": region,
                                            "articulos_devueltos": 1, "sha256_articulo": sha(f"ejemplo:{e['id']}/{p['id']}")}
    inst = {"schema": "preventa-precios-instantanea/1", "fecha_consulta": f"{FECHA}T07:30:00Z", "moneda": "EUR",
            "fuente": "https://prices.azure.com/api/retail/prices?currencyCode='EUR'", "plantillas": arts}
    inst["sha256"] = nucleo_experto.sha256_instantanea(inst)
    return inst


def niveles_ai_search(cid: str = "az-ai-search") -> list:
    """Niveles de la fila `cid` (por defecto Azure AI Search) del catálogo real del sandbox (contrato de la decisión 4,
    papel E); [] si no los trae."""
    real = json.loads((DIR.parents[1] / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    return next((c.get("niveles") or [] for c in real["componentes"] if c["id"] == cid), [])


def justificacion_s1(br: dict) -> dict | None:
    """justificacion_nivel de AI Search S1 (I1.9, contrato v5): la primera razón de subida del nivel que se cumple con una
    cita de los requisitos del ejemplo (umbral o característica, comprobado por el núcleo); None si el catálogo no da
    niveles (entonces el código exige null)."""
    return _justificacion("az-ai-search", "s1", br)


def _justificacion(cid: str, plantilla: str, br: dict) -> dict | None:
    nivel = next((n for n in con_razones(cid) if plantilla in (n.get("plantillas") or [])), None)
    if nivel is None:
        return None
    req = requisitos()
    for razon in nucleo_experto.razones_validas(nivel.get("razones_subida")) or []:
        campos = (razon["campo"],) if razon["campo"] else nucleo_experto.CAMPOS_DIMENSIONAMIENTO
        for cita in nucleo_experto.citas_de_campos(req, br["texto"], campos):
            if nucleo_experto.razon_cumplida(razon, cita):
                return {"nivel": nivel["nivel"], "razon": razon["id"], "cita": cita}
    raise SystemExit(f"el ejemplo no tiene una cita que cumpla una razón de subida de {cid} {nivel['nivel']}")


# I1.9 (VC18-1, contrato común con E): nivel por defecto con fuente y razones de subida por nivel. Si el catálogo real
# ya las trae se usan las suyas; si no, el ejemplo pone estas (sintéticas, con fuente de Learn) para que sea válido.
FUENTE_SEARCH = "https://learn.microsoft.com/azure/search/search-limits-quotas-capacity"
FUENTE_LIMITES = "https://learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits"
POR_DEFECTO_I19 = {"az-ai-search": {"nivel": "Basic", "fuente": FUENTE_SEARCH}}
RAZONES_I19 = {
    ("az-ai-search", "s1"): [{"id": "documentos_sobre_basic", "tipo": "umbral", "campo": "volumetria",
                              "unidad": ["documentos"], "limite": 10000, "fuente": FUENTE_SEARCH,
                              "texto": "Ejemplo sintético: más documentos de los que caben con holgura en Basic"}],
    ("az-app-service", "p0v3-linux"): [{"id": "acceso_privado", "tipo": "caracteristica", "campo": "red_privada",
                                        "palabras_clave": ["acceso privado"], "fuente": FUENTE_LIMITES,
                                        "texto": "Ejemplo sintético: acceso privado a la aplicación"}]}


def con_razones(cid: str) -> list:
    """Niveles de `cid` del catálogo real con las razones de subida de RAZONES_I19 donde no traiga ninguna (cuando el
    catálogo real aún no traía razones)."""
    salida = []
    for n in copy.deepcopy(niveles_ai_search(cid)):
        for pl in n.get("plantillas") or []:
            if (cid, pl) in RAZONES_I19 and not n.get("razones_subida"):
                n["razones_subida"] = copy.deepcopy(RAZONES_I19[(cid, pl)])
        salida.append(n)
    return salida


ETIQUETAS = {"volumetria": "Volumetría", "identidad_acl_origen": "Identidad y permisos del origen",
             "red_privada": "Red privada", "tipo_suscripcion": "Tipo de suscripción", "plazo": "Plazo",
             "presupuesto_orientativo": "Presupuesto orientativo", "idioma_oferta": "Idioma de la oferta"}
SUSTITUCIONES = [("Zaragoza", "[SENSIBLE]"), ("Tarragona", "[SENSIBLE]"), ("150 técnicos", "entre 100 y 500 técnicos")]


def _anon(texto: str) -> str:
    """Anonimización del caso de ejemplo (la regla general es brief.anonimizar, de A)."""
    for a, b in SUSTITUCIONES:
        texto = texto.replace(a, b)
    return texto


def _linea(campo: dict) -> str:
    e = campo["entradas"][0]
    return _anon(e["valor"]) + (" [ASUMIDO, confianza baja]" if e["origen"] == "ASUMIDO" else "")


def brief(req: dict, catalogo_sha: str) -> dict:
    c = req["campos"]
    cuerpo = ["## Necesidad", f"Objetivo: {_linea(c['objetivo'])}", f"Nubes: {_linea(c['nubes'])}", "## Alcance funcional"]
    cuerpo += [f"- {_anon(e['valor'])}" for e in c["alcance_funcional"]["entradas"]]
    cuerpo += ["## Canales e integraciones"] + [f"- {_anon(e['valor'])}" for e in c["canales_integraciones"]["entradas"]]
    cuerpo += ["## Usuarios y marco normativo", f"Ubicación de los usuarios finales: {_linea(c['ubicacion_usuarios'])}",
               f"Marco normativo: {_linea(c['marco_normativo'])}", "## Contexto"]
    cuerpo += [f"{etq}: {_linea(c[k])}" for k, etq in ETIQUETAS.items()]
    cuerpo += ["## Fuera de alcance"] + [f"- {_anon(e['valor'])}" for e in c["fuera_de_alcance"]["entradas"]]
    texto_cuerpo = "\n".join(cuerpo)
    brief_id = f"BRF-{CODIGO}-AZ-R1"
    # PR19-1 (I1.10): sin las dos huellas en la cabecera (van en la entrada del brief), como compone el núcleo
    cabecera = ["BRIEF-PREVENTA/1", f"brief_id: {brief_id}", "experto: preventa-experto-azure", "ronda: 1",
                f"perfiles_permitidos: {'; '.join(PERFILES)}", "---"]
    texto = "\n".join(cabecera) + "\n" + texto_cuerpo
    return {"brief_id": brief_id, "experto": "preventa-experto-azure", "version": VERSION, "ronda": 1, "texto": texto,
            "sha256": sha(texto), "sha256_cuerpo": sha(texto_cuerpo), "catalogo_sha256": catalogo_sha,
            "perfiles_permitidos": PERFILES, "correcciones": [], "conservar": [], "conservar_precios": [], "aceptados": []}


# PR15-2 (I1.5): los dos facturables de Azure sin precio del ejemplo (Microsoft Foundry y Azure AI Bot Service) declaran
# su motivo de no valoración; los demás llevan «no_aplica» (con precio, o SaaS como Entra ID).
MOTIVOS_SIN_PRECIO = {"C-01": "depende_del_volumen", "C-03": "depende_del_volumen"}
# I1.6 (decisión 4): «depende_del_volumen» exige un precio unitario de referencia de una plantilla del componente con
# cantidad_mensual null (no suma al total; va a la nota del revisor). Datos reales de Azure Retail Prices en EUR: GPT 5
# Mini (respuesta real del experto en pruebas/I13/E2E-A) y S1 Premium Channel Messages (consulta pública del 11-10-2026).
PRECIOS_REFERENCIA = [
    ("P-04", "C-01", "serviceName eq 'Foundry Models' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and meterName eq 'GPT 5 Mini Inpt DZone 1M Tokens'",
     0.242, "1M", "2025-08-01T00:00:00Z", "GPT 5 Mini Inpt DZone 1M Tokens", None, "Precio de referencia por millón de tokens de entrada; el consumo depende del volumen real de consultas."),
    ("P-05", "C-03", "serviceName eq 'Azure Bot Service' and productName eq 'Azure Bot Service' and armRegionName eq 'Global' and priceType eq 'Consumption' and meterName eq 'S1 Premium Channel Messages'",
     0.44, "1K", "2017-12-13T00:00:00Z", "S1 Premium Channel Messages", None, "Precio de referencia por mil mensajes de canal premium; el volumen de mensajes no se conoce todavía.")]
REGION_PRECIO = {"C-02": "francecentral", "C-03": "westeurope"}


def respuesta_experto(br: dict) -> dict:
    L = "https://learn.microsoft.com/azure/"
    refs = [("REF-01", L + "architecture/ai-ml/architecture/baseline-microsoft-foundry-chat", "Arquitectura de referencia de chat con Microsoft Foundry"),
            ("REF-02", L + "search/search-what-is-azure-search", "Qué es Azure AI Search"),
            ("REF-03", L + "bot-service/bot-overview", "Qué es Azure AI Bot Service"),
            ("REF-04", L + "private-link/private-link-overview", "Qué es Azure Private Link"),
            # PR16-1 (arreglos I1.6): la referencia de cada componente del catálogo es la página de Learn de su fila.
            ("REF-05", L + "foundry/what-is-foundry", "Qué es Microsoft Foundry"),
            ("REF-06", L + "app-service/overview", "Información general de Azure App Service"),
            ("REF-07", "https://learn.microsoft.com/entra/fundamentals/what-is-entra", "Qué es Microsoft Entra")]
    comp = [("C-01", "az-foundry", "Microsoft Foundry", "ia", "gpt-6-luna DataZoneStandard", "swedencentral", 1, "despliegue", "REF-05"),
            ("C-02", "az-ai-search", "Azure AI Search", "datos_conocimiento", "Standard S1", "francecentral", 1, "unidad de búsqueda", "REF-02"),
            ("C-03", "az-bot-service", "Azure AI Bot Service", "usuarios_canales", "Estándar", "westeurope", 1, "bot", "REF-03"),
            ("C-04", "az-app-service", "Azure App Service", "aplicacion_integracion", "B1", "swedencentral", 1, "instancia", "REF-06"),
            ("C-05", "az-entra-id", "Microsoft Entra ID", "identidad_seguridad_red", "Incluido en el tenant", "global", 1, "tenant", "REF-07"),
            ("C-06", "az-private-link", "Azure Private Link", "identidad_seguridad_red", "Punto de conexión privado", "swedencentral", 4, "punto de conexión", "REF-04")]
    tareas = [("T-01", "F0 - Arranque y análisis", "Análisis de requisitos y arquitectura detallada", "AI Architect / Tech Lead", 24, 6),
              ("T-02", "F1 - Construcción", "Ingesta e indexación de informes y procedimientos", "Senior AI / Foundry Engineer", 40, 2),
              ("T-03", "F1 - Construcción", "Agente de consulta con citas, resumen y comparación", "Senior AI / Foundry Engineer", 56, 4),
              ("T-04", "F1 - Construcción", "Publicación en Microsoft Teams y red privada", "AI Engineer / Tech Lead", 24, 2),
              ("T-05", "F2 - Pruebas y piloto", "Batería de pruebas de calidad de respuesta", "Consultor Junior", 32, 0),
              ("T-06", "F2 - Pruebas y piloto", "Piloto con usuarios, ajustes y traspaso", "AI Architect / Tech Lead", 16, 8)]
    # I1.7 (contrato v4): el modelo solo elige plantilla e instancias (o base de volumen); el filtro, el precio, la
    # unidad, la vigencia, el concepto y la cantidad los pone el núcleo (experto.completar) desde el catálogo y la
    # instantánea. P-04 y P-05 son precios de referencia (sin base) de los dos componentes con «depende_del_volumen».
    # I1.9 (VC18-1): B1 es el cómputo por defecto y los canales estándar, el nivel por defecto del bot (sin justificar)
    precios = [("P-01", "C-02", "s1", None), ("P-02", "C-04", "b1-linux", None), ("P-03", "C-06", "punto-conexion", 4),
               ("P-04", "C-01", "gpt-6-luna-entrada", None), ("P-05", "C-03", "canales-estandar", None)]
    return {
        "brief_recibido": br["texto"], "brief_id": br["brief_id"], "agente": "preventa-experto-azure",
        "arquitectura_id": ARQUITECTURA["id"],
        "referencias": [{"id": i, "url": u, "titulo": t, "fecha_consulta": FECHA} for i, u, t in refs],
        "componentes": [{"id": i, "catalogo_id": ca, "servicio": s, "capa": cp, "sku": sk, "region": r, "cantidad": q,
                         "unidad": un, "referencia_id": None, "desviacion_justificada": None,
                         "motivo_no_valoracion": MOTIVOS_SIN_PRECIO.get(i, "no_aplica"), "existente_del_cliente": None,
                         "incluido_en": None,
                         "justificacion_nivel": justificacion_s1(br) if i == "C-02" else None}
                        for i, ca, s, cp, sk, r, q, un, rf in comp],
        "flujos": [{"origen": "C-03", "destino": "C-04", "descripcion": "Teams entrega la pregunta a la aplicación"},
                   {"origen": "C-04", "destino": "C-01", "descripcion": "La aplicación invoca el agente"},
                   {"origen": "C-01", "destino": "C-02", "descripcion": "El agente recupera fragmentos citables"},
                   {"origen": "C-05", "destino": "C-04", "descripcion": "Autenticación del usuario"}],
        "decisiones": ["Región Sweden Central con despliegue Data Zone UE para cumplir la residencia de datos en la UE; Azure AI Search en France Central, porque Sweden Central no admite servicios de búsqueda nuevos."],
        "alternativas_descartadas": ["Interfaz web propia: el cliente pidió explícitamente Microsoft Teams."],
        "supuestos": [{"id": "S-01", "texto": "El cliente concede acceso de lectura a las bibliotecas documentales antes de la construcción.",
                       "confianza": "MEDIA", "hechos": ["R-identidad_acl_origen", "C-02"]}],
        "riesgos": [{"id": "RG-01", "texto": "La calidad de las respuestas depende de la calidad y vigencia de los informes de origen.",
                     "mitigacion": "Batería de preguntas de prueba validada por calidad antes del piloto.", "hechos": ["R-alcance_funcional", "C-01"]}],
        "preguntas": ["Confirmar el número de técnicos usuarios y el volumen de documentos."],
        "tareas_propuestas": [{"id": i, "fase": f, "tarea": t, "perfil": p, "horas_base": h, "reuniones_h": rh,
                               "descripcion": f"{t}, con revisión del resultado junto al equipo del cliente.", "entregable": f"Entregable de {t.lower()}"}
                              for i, f, t, p, h, rh in tareas],
        "precios": [{"id": i, "componente_id": c, "plantilla_id": pl, "instancias": n, "base_volumen": None,
                     "factor_override": None} for i, c, pl, n in precios],
        "herramientas_usadas": {"microsoft_docs_search": 3, "microsoft_docs_fetch": 2},
    }


def _techo(d: Decimal) -> int:
    return int(d.to_integral_value(rounding=ROUND_CEILING))


def estimacion_entrada(resp: dict, req: dict) -> dict:
    """Regla de estimación del comercial del 10-10-2026 (REV-1, I1.4; la oficial es nucleo.estimacion.componer_entrada):
    una tarea por propuesta, PM = máx(8 h, ⌈15 % de las horas técnicas⌉) con 1 h de seguimiento por semana y Gantt
    secuencial con los perfiles distintos de cada fase en paralelo: máx(1, ⌈horas de la fase / (40 × perfiles)⌉)."""
    tareas = [{"id": t["id"], "fase": t["fase"], "tarea": t["tarea"], "perfil": t["perfil"], "tecnicas_h": t["horas_base"],
               "reuniones_h": t["reuniones_h"], "descripcion": t["descripcion"], "entregable": t["entregable"]}
              for t in resp["tareas_propuestas"]]
    fases = list(dict.fromkeys(t["fase"] for t in tareas))
    horas = [Decimal(str(t["tecnicas_h"])) + (Decimal(str(t["tecnicas_h"])) * Decimal("0.2")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP) + Decimal(str(t["reuniones_h"])) for t in tareas]
    gantt, semana = [], 1
    for f in fases:
        de_fase = [i for i, t in enumerate(tareas) if t["fase"] == f]
        n = max(1, _techo(sum((horas[i] for i in de_fase), Decimal(0)) / (40 * len({tareas[i]["perfil"] for i in de_fase}))))
        nombres = "; ".join(tareas[i]["tarea"] for i in de_fase)
        gantt.append({"fase": f, "contenido": nombres if len(nombres) <= 200 else f"{len(de_fase)} tareas de {f}"[:200],
                      "semanas": list(range(semana, semana + n))})
        semana += n
    duracion = semana - 1
    pm = max(8, _techo(sum((Decimal(str(t["tecnicas_h"])) for t in tareas), Decimal(0)) * Decimal("0.15")))
    tareas.append({"id": "PM-01", "fase": "Gestión de proyecto", "tarea": "Coordinación, seguimiento y reporting",
                   "perfil": "Project Manager", "tecnicas_h": pm, "reuniones_h": duracion,
                   "descripcion": "Planificación, seguimiento del avance, gestión de riesgos y reporting al cliente.",
                   "entregable": "Informes de seguimiento"})
    gantt.append({"fase": "Gestión de proyecto", "contenido": "Coordinación y seguimiento", "semanas": list(range(1, duracion + 1))})
    return {
        "codigo": CODIGO, "cliente": "Kelvara Ensayos Industriales, S.A.",
        "titulo": "Asistente de consulta técnica con IA sobre informes de ensayo", "fecha": FECHA, "duracion_semanas": duracion,
        "fases": fases + ["Gestión de proyecto"], "tareas": tareas,
        "hitos": [{"nombre": f"Hito {n} - {d}", "porcentaje": 25} for n, d in enumerate(HITOS_TARIFA, 1)],
        "gantt": gantt,
        "asunciones": [s["texto"] for s in resp["supuestos"]],
        "exclusiones": [e["valor"] for e in req["campos"]["fuera_de_alcance"]["entradas"]],
        "ajuste_comercial_eur": 0,
    }


def resumen(ent: dict) -> dict:
    """Réplica en Decimal de generar_estimacion.calcular (la oficial es estimacion.calcular, de B)."""
    filas = []
    for t in ent["tareas"]:
        e, g = Decimal(str(t["tecnicas_h"])), Decimal(str(t["reuniones_h"]))
        filas.append((t, e + (e * Decimal("0.2")).quantize(Decimal("1"), rounding=ROUND_HALF_UP) + g))
    por_perfil = [(p, sum((d for t, d in filas if t["perfil"] == p), Decimal(0))) for p in PERFILES]
    por_perfil = [(p, h) for p, h in por_perfil if h]
    total = sum((d for _, d in filas), Decimal(0))
    subtotal = sum((h * Decimal(str(TARIFAS[p])) for p, h in por_perfil), Decimal(0))
    precio = subtotal + Decimal(str(ent.get("ajuste_comercial_eur", 0)))
    hitos, acum = [], Decimal(0)
    for i, h in enumerate(ent["hitos"]):
        imp = (Decimal(str(h["porcentaje"])) / 100 * precio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        imp = imp if i < len(ent["hitos"]) - 1 else precio - acum
        acum += imp
        hitos.append({"nombre": h["nombre"], "porcentaje": h["porcentaje"], "importe_eur": eur(imp)})
    pm = dict(por_perfil).get("Project Manager", Decimal(0))
    return {"horas_total": eur(total), "por_perfil": [{"perfil": p, "horas": eur(h), "tarifa_hora": TARIFAS[p],
                                                        "importe_eur": eur(h * Decimal(str(TARIFAS[p])))} for p, h in por_perfil],
            "por_fase": [{"fase": f, "horas": eur(sum((d for t, d in filas if t["fase"] == f), Decimal(0)))} for f in ent["fases"]],
            "pm_h": eur(pm), "pm_pct": eur(pm / total * 100), "subtotal_eur": eur(subtotal),
            "ajuste_eur": eur(Decimal(str(ent.get("ajuste_comercial_eur", 0)))), "precio_cerrado_eur": eur(precio),
            "hitos": hitos, "duracion_semanas": ent["duracion_semanas"]}


LOTE_MAX = {"REF": 4, "C": 5, "P": 6}  # réplica de nucleo.verificacion.LOTE_MAX (papel V, LES-G-096)
SECCION = {"REF": "## Referencias", "C": "## Componentes", "P": "## Precios"}
NOMBRE_LOTE = {"REF": "referencias", "C": "componentes", "P": "precios"}


def consolidado(resp: dict, cat: dict, req: dict) -> dict:
    """Solo lo verificable (sin prosa), con tipo_suscripcion y los lotes por tipo (LES-G-096). CMP-1 (I1.3): la
    referencia va en la línea de cada componente (con su URL), la residencia por tenant y la región de precio
    publicada se dicen en la línea; réplica de nucleo.verificacion.componer_consolidado."""
    entradas = {c["id"]: c for c in cat["componentes"]}
    nombres = {i: e["nombre_oficial"] for i, e in entradas.items()}
    url_ref = {r["id"]: r["url"] for r in resp["referencias"]}
    comp = {c["id"]: c for c in resp["componentes"]}
    marca = "(residencia de datos: geografía del tenant del cliente; no es una región de Azure)"

    def region_c(c: dict) -> str:
        return f"{c['region']} {marca}" if entradas[c["catalogo_id"]].get("residencia") == "geografia_tenant" else c["region"]

    def region_p(p: dict) -> str:
        rp = entradas[comp[p["componente_id"]]["catalogo_id"]].get("region_precio")
        return f"{p['region']} (Retail Prices lo publica con armRegionName «{rp}»)" if rp else p["region"]

    def nivel_c(c: dict) -> str:  # integrador I1.6 (CAMBIOS-I16-E §3.3): el nivel justificado va en la línea
        j = c.get("justificacion_nivel")
        return (f" | nivel: {j['nivel']} | razon: {j['razon']} | cita: «{j['cita']}»") if j else ""  # I1.9

    por_tipo = {
        "REF": [f"{r['id']} | {r['url']} | {r['titulo']}" for r in resp["referencias"]],
        "C": [f"{c['id']} | {nombres[c['catalogo_id']]} | sku: {c['sku']} | region: {region_c(c)}{nivel_c(c)} | referencia: "
              f"{url_ref[c['referencia_id']]}" for c in resp["componentes"]],
        "P": [f"{p['id']} | {p['componente_id']} | filtro: {p['filtro']} | precio: {p['precio']} EUR | unidad: {p['unidad']} "
              f"| region: {region_p(p)} | effectiveStartDate: {p['effectiveStartDate']}" for p in resp["precios"]]}
    cid = f"CNS-{CODIGO}-R1"
    contexto = [f"brief_id: {resp['brief_id']}", "ubicacion_usuarios: España (laboratorios de [SENSIBLE] y [SENSIBLE])",
                "marco_normativo: RGPD, con datos en la Unión Europea",
                f"tipo_suscripcion: {'; '.join(e['valor'] for e in req['campos']['tipo_suscripcion']['entradas']) or 'no indicado'}"]

    def componer(cabecera: list[str], cuerpo: list[str]) -> str:
        texto_cuerpo = "\n".join(cuerpo)
        return "\n".join(cabecera + [f"sha256_cuerpo: {sha(texto_cuerpo)}", "---"]) + "\n" + texto_cuerpo

    texto = componer(["CONSOLIDADO-PREVENTA/1", f"consolidado_id: {cid}"] + contexto,
                     [ln for t in ("REF", "C", "P") for ln in [SECCION[t]] + por_tipo[t]])
    trozos = [(t, por_tipo[t][i:i + LOTE_MAX[t]]) for t in ("REF", "C", "P") for i in range(0, len(por_tipo[t]), LOTE_MAX[t])]
    lotes = []
    for n, (tipo, grupo) in enumerate(trozos, start=1):
        lid = f"{cid}-L{n}"
        lt = componer(["CONSOLIDADO-PREVENTA/1", f"consolidado_id: {lid}",
                       f"lote: {n} de {len(trozos)} ({NOMBRE_LOTE[tipo]}) del consolidado {cid}"] + contexto, [SECCION[tipo]] + grupo)
        lotes.append({"lote_id": lid, "tipo": NOMBRE_LOTE[tipo], "sha256": sha(lt), "texto": lt,
                      "ids": [ln.split(" | ", 1)[0] for ln in grupo], "registrada_el": None, "respuesta": None})
    ids = [x["id"] for k in ("referencias", "componentes", "precios") for x in resp[k]]
    return {"consolidado_id": cid, "sha256": sha(texto), "texto": texto, "ids": ids, "lotes": lotes}


def consolidado_nucleo(resp: dict, cat: dict, req: dict, br: dict) -> dict:
    """Integrador I1.7: el consolidado del ejemplo lo compone el núcleo (nucleo.verificacion.componer_consolidado), sin
    precios (decisión 1) y con los segmentos de motivo y factor de la línea del componente (CAMBIOS-I17-E §3.5)."""
    alta = {"cliente": "Kelvara Ensayos Industriales, S.A.", "codigo_cliente": "KELVARA",
            "terminos_sensibles": ["Kelvara Ensayos Industriales, S.A.", "Kelvara Ensayos Industriales", "Kelvara",
                                   "Marta Olmedo", "Iker Salaverri", "Nuria Castells", "Zaragoza", "Tarragona", "Responsable comercial"]}
    est = {"carga": {"alta": alta, "requisitos": req, "briefs": [br],
                     "respuestas_expertos": {"azure": {"brief_id": br["brief_id"], "respuesta": resp}}}}
    cid = f"CNS-{CODIGO}-R1"
    c = nucleo_verificacion.componer_consolidado(est, cat, cid)
    return {"consolidado_id": c.consolidado_id, "sha256": c.sha256, "texto": c.texto, "ids": list(c.ids),
            "lotes": [{"lote_id": x.lote_id, "tipo": x.tipo, "sha256": x.sha256, "texto": x.texto, "ids": list(x.ids),
                       "registrada_el": None, "respuesta": None} for x in c.lotes]}


def respuesta_verificador(cons: dict) -> dict:
    # Integrador I1.7 (decisión 1): el consolidado ya no lleva precios; ni lote ni herramienta de precios
    # (C-06 NO VERIFICABLE, como el ejemplo que propuso R en CAMBIOS-I17-R §2.3)
    tipo = {"REF": "referencia", "C": "componente"}
    nv = "C-06"
    elems = [{"id": i, "tipo": tipo[i.split("-")[0]], "veredicto": "NO VERIFICABLE" if i == nv else "OK", "campo": "ninguno",
              "detalle": ("microsoft_docs_search no devolvió la página del punto de conexión privado en la región indicada; "
                          "no se puede confirmar la disponibilidad.") if i == nv else "Comprobado contra la fuente oficial.",
              "valor_correcto": None,
              "fuente_url": None if i == nv else "https://learn.microsoft.com/azure/search/search-sku-tier"} for i in cons["ids"]]
    return {"agente": "preventa-verificador", "consolidado_id": cons["consolidado_id"], "entrada_recibida_inicio": "\n".join(cons["texto"].split("\n")[:3]),
            "elementos": elems, "resumen": {"ok": len(elems) - 1, "discrepa": 0, "observacion": 0, "no_verificable": 1},
            "herramientas_usadas": {"microsoft_docs_search": 3, "microsoft_docs_fetch": 3}}


def _referencias_ejemplo(resp, capas):
    """CAMBIOS-I17-D §4: la página de cada componente (una por URL, en el orden de las capas) y detrás REF-01."""
    url = {r["id"]: r["url"] for r in resp["referencias"]}
    de_c = {c["id"]: c["referencia_id"] for c in resp["componentes"]}
    vistas = {}
    for capa in (c for c in capas if c["componentes"]):
        for x in capa["componentes"]:
            vistas.setdefault(url[de_c[x["id"]]], (de_c[x["id"]], []))[1].append(x["nombre"])
    referencias = [{"id": i, "url": u, "titulo": "Documentación oficial de Microsoft sobre " +
                    (n[0] if len(n) == 1 else ", ".join(n[:-1]) + " y " + n[-1])} for u, (i, n) in vistas.items()]
    ref01 = next(r for r in resp["referencias"] if r["id"] == "REF-01")
    if ref01["url"] not in vistas:
        referencias.append({"id": "REF-01", "url": ref01["url"],
                            "titulo": "Documentación oficial de Microsoft sobre arquitecturas de referencia de Azure"})
    return referencias


def anexo(resp: dict, ver: dict, cat: dict) -> dict:
    nombres = {c["id"]: c["nombre_oficial"] for c in cat["componentes"]}
    comp = {c["id"]: c for c in resp["componentes"]}
    estado_v = {e["id"]: e["veredicto"] for e in ver["elementos"]}
    lineas = []
    for p in resp["precios"]:
        if p["cantidad_mensual"] is None:  # I1.6: precio unitario de referencia; no suma (nota del revisor)
            continue
        coste = Decimal(str(p["precio"])) * Decimal(str(p["cantidad_mensual"]))
        lineas.append({"precio_id": p["id"], "componente_id": p["componente_id"], "servicio": nombres[comp[p["componente_id"]]["catalogo_id"]],
                       "concepto": p["concepto"], "region": p["region"], "filtro": p["filtro"], "precio_unitario": p["precio"],
                       "unidad": p["unidad"], "cantidad_mensual": p["cantidad_mensual"], "supuesto_cantidad": p["supuesto_cantidad"],
                       "effectiveStartDate": p["effectiveStartDate"], "coste_mensual_eur": eur(coste), "verificacion": estado_v[p["id"]]})
    total = sum((Decimal(x["coste_mensual_eur"]) for x in lineas), Decimal(0))
    return {"schema": "preventa-anexo-consumo/1", "codigo": CODIGO, "moneda": "EUR",
            "fuente": {"nombre": "Azure Retail Prices", "url": "https://prices.azure.com/api/retail/prices", "consultado_el": FECHA},
            "lineas": lineas, "total_mensual_eur": eur(total), "total_anual_eur": eur(total * 12),
            "avisos": ["P-03 sin contraste independiente del verificador."],
            "nota_fija": "Orientativo. No incluido en el precio cerrado; lo asume el cliente."}


def _eur_es(importe: object) -> str:
    """I1.9 (CAMBIOS-I19-D §3): el importe con lectura española, como lo compone textos_cliente («28.025,25 €»)."""
    from nucleo import textos_cliente as nucleo_textos  # diferido: solo para el texto de la condición
    return nucleo_textos.formato_eur(str(importe))


def _f(prefijo: str, n: int, texto: str, hechos: list[str]) -> dict:
    return {"id": f"TX-{prefijo}-{n:02d}", "texto": texto, "hechos": hechos}


def textos_cliente(carga: dict, cat: dict) -> dict:
    """Forma de ejemplo; la composición oficial es textos_cliente.componer (C)."""
    req, resp = carga["requisitos"]["campos"], carga["respuestas_expertos"]["azure"]["respuesta"]
    res, anx = carga["estimacion"]["resumen"], carga["anexo_consumo"]
    nombres = {c["id"]: c["nombre_oficial"] for c in cat["componentes"]}
    titulos = {"usuarios_canales": "Usuarios y canales", "aplicacion_integracion": "Aplicación e integración", "ia": "Inteligencia artificial",
               "datos_conocimiento": "Datos y conocimiento", "identidad_seguridad_red": "Identidad, seguridad y red",
               "operacion_observabilidad": "Operación y observabilidad"}
    capas = [{"capa": k, "titulo": t, "componentes": [{"id": c["id"], "nombre": nombres[c["catalogo_id"]]} for c in resp["componentes"] if c["capa"] == k]}
             for k, t in titulos.items()]
    hechos_base = {k: carga[k] for k in ("alta", "requisitos", "respuestas_expertos", "verificacion", "anexo_consumo")}
    hechos_base["estimacion_resumen"] = res
    return {
        "schema": "preventa-textos-cliente/1", "codigo": CODIGO, "hash_hechos": sha(canonico(hechos_base)),
        "portada": {"titulo": carga["alta"]["titulo"], "cliente": carga["alta"]["cliente"], "codigo": CODIGO, "fecha": FECHA,
                    "subtitulo": f"Propuesta para revisión interna · versión {VERSION}"},
        "necesidad": [_f("NEC", 1, f"Objetivo: {req['objetivo']['entradas'][0]['valor']}.", ["R-objetivo"]),
                      _f("NEC", 2, f"Usuarios finales en {req['ubicacion_usuarios']['entradas'][0]['valor']}; marco normativo: "
                                   f"{req['marco_normativo']['entradas'][0]['valor']}.", ["R-ubicacion_usuarios", "R-marco_normativo"])],
        "arquitectura": {"capas": [c for c in capas if c["componentes"]],
                         "flujos": [{"origen": f["origen"], "destino": f["destino"]} for f in resp["flujos"]],
                         "referencias": _referencias_ejemplo(resp, capas)},
        "alcance": [_f("ALC", n, e["valor"] + ".", ["R-alcance_funcional"]) for n, e in enumerate(req["alcance_funcional"]["entradas"], 1)],
        "fuera_de_alcance": [_f("FDA", n, e["valor"] + ".", ["R-fuera_de_alcance"]) for n, e in enumerate(req["fuera_de_alcance"]["entradas"], 1)]
        + [_f("FDA", 3, "Licencias y consumo cloud, que asume el cliente.", ["FIJO-EXCLUSIONES"])],
        "supuestos": [{"id": "TX-SUP-01", "texto": f"Volumetría: {req['volumetria']['entradas'][0]['valor']}.", "hechos": ["R-volumetria"], "nivel": "Confianza baja"},
                      {"id": "TX-SUP-02", "texto": f"Origen de los documentos: {req['identidad_acl_origen']['entradas'][0]['valor']}.",
                       "hechos": ["R-identidad_acl_origen"], "nivel": "Confianza baja"},
                      {"id": "TX-SUP-03", "texto": resp["supuestos"][0]["texto"], "hechos": ["S-01"], "nivel": "Confianza media"}],
        "precio": {"precio_cerrado_eur": res["precio_cerrado_eur"], "iva": "IVA no incluido", "duracion_semanas": res["duracion_semanas"],
                   "hitos": res["hitos"]},
        "consumo": {"lineas": [{"servicio": x["servicio"], "concepto": x["concepto"], "coste_mensual_eur": x["coste_mensual_eur"]} for x in anx["lineas"]],
                    "total_mensual_eur": anx["total_mensual_eur"], "total_anual_eur": anx["total_anual_eur"],
                    "fuente": f"Azure Retail Prices (prices.azure.com), región swedencentral: precios consultados el {anx['fuente']['consultado_el']}, vigentes desde 2024-11-01",
                    "aviso": anx["nota_fija"]},
        "riesgos": [_f("RSG", 1, resp["riesgos"][0]["texto"], ["RG-01"]),
                    _f("RSG", 2, "Supuesto sin confirmar: la volumetría de usuarios y documentos.", ["R-volumetria"])],
        "condiciones": [_f("CON", 1, f"Precio cerrado de {_eur_es(res['precio_cerrado_eur'])}, IVA no incluido.",  # I1.9 (D)
                           ["ESTIMACION"]),
                        _f("CON", 2, "Facturación por hitos: cuatro hitos del 25 % cada uno.", ["TARIFA", "ESTIMACION"]),
                        _f("CON", 3, "Condiciones de pago: 30 días fecha factura. Validez de la oferta: 30 días.", ["TARIFA"]),
                        _f("CON", 4, "El consumo cloud no está incluido y lo asume el cliente.", ["FIJO-CONDICIONES", "ANEXO"])],
        "excluidas": [],
    }


def _artefacto(nombre: str) -> dict:
    return {"nombre": nombre, "sha256": sha("ejemplo:" + nombre), "bytes": 1000 + len(nombre)}


def estado(carga: dict) -> dict:
    h = sha(canonico(carga))
    zipn = f"{CODIGO}-Paquete.zip"
    ctrl = [("iniciar", None, "BORRADOR"), ("suficiencia", "BORRADOR", "INFORMACION_INSUFICIENTE"),
            ("asumir", "INFORMACION_INSUFICIENTE", "INFORMACION_INSUFICIENTE"), ("asumir", "INFORMACION_INSUFICIENTE", "EN_ANALISIS"),
            ("enrutar", "EN_ANALISIS", "EN_ANALISIS"), ("registrar-experto", "EN_ANALISIS", "EN_ANALISIS"),
            ("consolidar", "EN_ANALISIS", "EN_VERIFICACION"), ("registrar-verificacion", "EN_VERIFICACION", "VERIFICADA"),
            ("anexo-consumo", "VERIFICADA", "VERIFICADA"), ("estimar", "VERIFICADA", "VERIFICADA"), ("paquete", "VERIFICADA", "LISTA_PARA_REVISION")]
    hashes = [sha(f"ejemplo:paso{n}") for n in range(len(ctrl) - 1)] + [h]
    control = [{"n": n, "subcomando": s, "estado_antes": a, "estado_despues": d, "hash_antes": hashes[n - 2] if n > 1 else None,
                "hash_despues": hashes[n - 1], "ts": f"{FECHA}T10:{n:02d}:00+02:00"} for n, (s, a, d) in enumerate(ctrl, 1)]
    return {"schema": "preventa-estado/1", "codigo": CODIGO, "version": VERSION, "estado": "LISTA_PARA_REVISION", "estado_previo": None,
            "motivo_bloqueo": None, "carga": carga, "hash_contenido": h, "decisiones": [],
            "intentos": {"T1": 0, "T2": 0, "T3": 0, "T4": 0}, "ronda_verificacion": 1, "fallos": [], "control_versiones": control,
            "artefactos": {"xlsx_estimacion": _artefacto(f"{CODIGO}-Estimacion.xlsx"), "anexo_xlsx": _artefacto(f"{CODIGO}-Anexo-Consumo.xlsx"),
                           "anexo_json": _artefacto(f"{CODIGO}-Anexo-Consumo.json"), "pptx": _artefacto(f"{CODIGO}-Revision.pptx"),
                           "docx": _artefacto(f"{CODIGO}-Nota-Revision.docx"), "zip": _artefacto(zipn)}}


def decision(est: dict) -> dict:
    h = est["hash_contenido"]
    linea = f"DECISION | Responsable de preventa | APROBADA | 2026-10-09 | {h} | Arquitectura y precios revisados; sin comentarios."
    return {"id": "D-002", "linea": linea, "revisor": "Responsable de preventa", "tipo": "APROBADA", "fecha": "2026-10-09", "hash_citado": h,
            "comentarios": "Arquitectura y precios revisados; sin comentarios.", "version": VERSION,
            "estado_antes": "EN_REVISION_PREVENTA", "estado_despues": "EN_APROBACION_AREA", "registrada_ts": "2026-10-09T09:15:00+02:00"}


def manifiesto(est: dict, estado_sha: str, cat_sha: str, precios_sha: str) -> dict:
    nombres = [f"{CODIGO}-Estimacion.xlsx", f"{CODIGO}-Anexo-Consumo.xlsx", f"{CODIGO}-Anexo-Consumo.json", f"{CODIGO}-Revision.pptx",
               f"{CODIGO}-Nota-Revision.docx", "estado.json", "mensaje_revisor.txt", "mensaje_aprobador.txt"]
    fich = [_artefacto(n) for n in nombres]
    fich[5] = {"nombre": "estado.json", "sha256": estado_sha, "bytes": (DIR / "estado.json").stat().st_size}
    return {"schema": "preventa-manifiesto-paquete/1", "codigo": CODIGO, "version": VERSION, "estado": "LISTA_PARA_REVISION",
            "hash_contenido": est["hash_contenido"], "estado_json_sha256": estado_sha, "ficheros": fich,
            "montados": {"rate_card_sha256": "45491cc035cc6b0e2ff32621b35a347fd9214ad98bff4664f79469122c9866d4",
                         "generador_sha256": "50aa3ac88be8fba0eb96b8d61126e7d5b810221a26acceb4abc9e37f116e65f3",
                         "plantilla_sha256": "fbb1e2c0fb0308e975a606670c66d0b35261512c59d92e980d16f0cddbe55602",
                         "catalogo_sha256": cat_sha, "precios_instantanea_sha256": precios_sha},
            "generado_ts": f"{FECHA}T10:11:00+02:00"}


def _norm(t: str) -> str:
    """Normalización de cita de CONTRATOS.md §3.3, simplificada para el ejemplo."""
    import re
    import unicodedata
    t = re.sub(r"</?v[^>]*>", " ", t)
    t = "".join(ch for ch in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(ch) != "Mn")
    return " ".join(t.split())


def escribir(nombre: str, obj: object) -> str:
    datos = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (DIR / f"{nombre}.json").write_bytes(datos)
    return sha(datos)


def main() -> int:
    texto_fuente = TRANSCRIPCION.read_bytes()
    texto = texto_fuente.decode("utf-8").replace("\r\n", "\n")
    req = requisitos()
    malas = [e["cita"] for c in req["campos"].values() for e in c["entradas"] if e["cita"] and _norm(e["cita"]) not in _norm(texto)]
    if malas:
        raise SystemExit(f"Citas que no están en la transcripción: {malas}")
    cat = catalogo()
    cat_escrito, completo = catalogo_para_escribir(cat)
    if not completo:
        print("AVISO: el esquema del catálogo aún no admite los campos de I1.9 (o de I1.7) del papel E: el ejemplo del "
              "catálogo va sin ellos; la completada de ejemplo se calcula con el catálogo completo")
    cat_sha = escribir("catalogo_componentes", cat_escrito)
    br = brief(req, cat_sha)
    modelo = respuesta_experto(br)
    inst = instantanea(cat)
    resp, faltas = nucleo_experto.completar(modelo, cat, inst, req, br["texto"])
    if faltas:
        raise SystemExit(f"La respuesta de ejemplo no se completa: {faltas}")
    cons = consolidado_nucleo(resp, cat, req, br)
    ver = respuesta_verificador(cons)
    ent = estimacion_entrada(resp, req)
    alta = {"cliente": "Kelvara Ensayos Industriales, S.A.", "codigo_cliente": "KELVARA", "seqof": "001",
            "titulo": ent["titulo"], "nda_confirmado": True,
            "terminos_sensibles": sorted({"Kelvara Ensayos Industriales, S.A.", "Kelvara Ensayos Industriales", "Kelvara", "Marta Olmedo",
                                          "Iker Salaverri", "Nuria Castells", "Zaragoza", "Tarragona", "Responsable comercial"})}
    carga = {"alta": alta, "fuentes": [{"id": "F1", "nombre": TRANSCRIPCION.name, "tipo": "TRANSCRIPCION", "sha256": sha(texto_fuente),
                                        "bytes": len(texto_fuente), "sha256_texto": sha(texto)}],
             "requisitos": req, "briefs": [br], "respuestas_expertos": {"azure": {"registrada_el": FECHA, "brief_id": br["brief_id"], "respuesta": resp}},
             "consolidado": cons,
             "verificacion": {"registrada_el": FECHA, "consolidado_id": cons["consolidado_id"], "respuesta": ver,
                              "resultado": {"verificada": True, "discrepa": [], "no_verificables": [{"id": "C-06"}], "reparados": []},
                              "lotes": [], "observaciones": []},
             "anexo_consumo": None, "estimacion": {"entrada": ent, "resumen": resumen(ent), "ajuste": None},
             "textos_cliente": None}
    carga["anexo_consumo"] = nucleo_anexo.calcular(estado(copy.deepcopy(carga)), cat)  # integrador I1.7: el del núcleo
    carga["textos_cliente"] = textos_cliente(carga, cat)
    est = estado(carga)
    for nombre, obj in (("requisitos", req), ("brief", br), ("respuesta_experto", modelo),
                        ("respuesta_experto_completa", resp), ("precios_instantanea", inst), ("respuesta_verificador", ver),
                        ("estimacion_entrada", ent), ("anexo_consumo", carga["anexo_consumo"]), ("textos_cliente", carga["textos_cliente"]),
                        ("decision", decision(est))):
        escribir(nombre, obj)
    estado_sha = escribir("estado", est)
    escribir("manifiesto_paquete", manifiesto(est, estado_sha, cat_sha, sha((DIR / "precios_instantanea.json").read_bytes())))
    (DIR / "brief_ejemplo.txt").write_text(br["texto"] + "\n", encoding="utf-8", newline="\n")
    (DIR / "consolidado_ejemplo.txt").write_text(cons["texto"] + "\n", encoding="utf-8", newline="\n")
    print(f"Ejemplos escritos en {DIR}; hash_contenido {est['hash_contenido']}; precio {carga['estimacion']['resumen']['precio_cerrado_eur']} EUR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
