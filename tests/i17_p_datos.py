"""I1.7 · papel P: datos comunes de las pruebas del contrato v4 (no es un fichero de pruebas).

- `catalogo_i17()`: el catálogo real del sandbox con lo que añade el papel E en I1.7, simulado aquí hasta que llegue su
  derivado: lista de arquitecturas de referencia, plantillas de gpt-6-luna (por defecto), ciclo de vida de los modelos
  (tabla de retiradas de Learn, actualizada el 2026-09-23), factores estándar con fuente y una inclusión con fuente.
- `instantanea_i17(cat)`: una instantánea con TODAS las plantillas; precios y unidades de la medición real de E
  (catalogo/catalogo_referencias_azure.json, comprobacion) y los de gpt-6-luna que comprobó el PM el 12/13-10-2026.
- `estado_brezalia()`: el estado real de la sesión 2 de B en I1.6 (Brezalia), devuelto a EN_ANALISIS en la ronda 1.
- `respuesta_v4(brief)`: una respuesta v4 válida para ese brief (control: el núcleo la acepta).
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
for _p in (RAIZ / "sandbox", RAIZ):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from nucleo import experto  # noqa: E402

LEARN = "https://learn.microsoft.com/azure/"
FUENTE_MODELOS = LEARN + "foundry/foundry-models/concepts/models-sold-directly-by-azure"
FUENTE_RETIRADAS = LEARN + "foundry/openai/concepts/model-retirement-schedule"
FILTRO_FM = "serviceName eq 'Foundry Models' and armRegionName eq 'swedencentral' and priceType eq 'Consumption' and meterName eq '{}'"
LUNA = {"gpt-6-luna-entrada": ("6-luna ShortCo Inp Std DZ 1M Tokens", 0.1056),
        "gpt-6-luna-salida": ("6-luna ShortCo Opt Std DZ 1M Tokens", 0.528)}
RETIRADAS = {"gpt-5": "2027-02-09", "gpt-5-mini": "2027-02-09", "gpt-5-nano": "2027-02-09", "gpt-5.4": "2027-09-02"}
ARQUITECTURA = {"id": "chat-foundry-base", "titulo": "Arquitectura de referencia de chat con Microsoft Foundry",
                "url": LEARN + "architecture/ai-ml/architecture/baseline-microsoft-foundry-chat"}
FACTOR_ENTRADA = {"plantillas": ["gpt-6-luna-entrada"], "valor": 2500, "unidad": "tokens de entrada por consulta",
                  "base": ["consulta"], "caso_uso": "asistente con RAG",
                  "fuente": LEARN + "foundry/openai/how-to/manage-costs",
                  "justificacion": "Pregunta, instrucciones del sistema y unos 5 fragmentos recuperados por consulta."}
FACTOR_SALIDA = {"plantillas": ["gpt-6-luna-salida"], "valor": 400, "unidad": "tokens de salida por consulta",
                 "base": ["consulta"], "caso_uso": "asistente con RAG",
                 "fuente": LEARN + "foundry/openai/how-to/manage-costs",
                 "justificacion": "Respuesta breve con las citas de los documentos de origen."}
FACTOR_BOT = {"valor": 2, "unidad": "mensajes por consulta", "base": "consulta", "caso_uso": "bot",
              "fuente": LEARN + "bot-service/bot-service-overview",
              "justificacion": "La pregunta del usuario y la respuesta del bot: dos mensajes de canal por consulta."}
INCLUYE_SEGURIDAD = {"catalogo_id": "az-content-safety", "fuente_url": LEARN + "foundry/openai/concepts/content-filter",
                     "nota": "El filtrado de contenido de los modelos va incluido en el precio de Foundry Models."}


def catalogo_i17(base: dict | None = None) -> dict:
    cat = copy.deepcopy(base) if base is not None else json.loads(
        (RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    cat["arquitecturas_referencia"] = [copy.deepcopy(ARQUITECTURA)]
    for e in cat["componentes"]:
        if e["id"] == "az-foundry":
            for p in e["plantillas_precio"]:
                p.pop("por_defecto", None)
                modelo = next((p["id"][:-len(s)] for s in ("-entrada-cache", "-entrada", "-salida")
                               if p["id"].endswith(s)), p["id"])
                p["ciclo_vida"] = {"ga": "2025-08-07", "retirada": RETIRADAS.get(modelo), "fuente": FUENTE_RETIRADAS}
            for pid, (medidor, _) in LUNA.items():
                e["plantillas_precio"].insert(0, {"id": pid, "filtro": FILTRO_FM.format(medidor), "concepto": medidor,
                                                  "impulsor": "volumen", "divisor": 1000000, "por_defecto": True,
                                                  "ciclo_vida": {"ga": "2026-09-22", "retirada": None,
                                                                 "fuente": FUENTE_MODELOS}})
            e["factores_estandar"] = [copy.deepcopy(FACTOR_ENTRADA), copy.deepcopy(FACTOR_SALIDA)]
            e["incluye"] = [copy.deepcopy(INCLUYE_SEGURIDAD)]
        if e["id"] == "az-bot-service":
            for p in e["plantillas_precio"]:
                p["factor_estandar"] = copy.deepcopy(FACTOR_BOT)
    from tests.i19_p_datos import catalogo_i19  # I1.9: nivel por defecto y razones de subida (contrato con E, simulado)
    return catalogo_i19(cat)


def _medicion() -> dict:
    ref = json.loads((RAIZ / "catalogo" / "catalogo_referencias_azure.json").read_text(encoding="utf-8"))
    return {(e["id"], p["id"]): p.get("comprobacion") or {} for e in ref["componentes"] for p in e.get("plantillas_precio") or []}


def instantanea_i17(cat: dict, fecha: str = "2026-10-13T08:00:00Z", quitar: tuple = ()) -> dict:
    med, arts = _medicion(), {}
    for e in cat["componentes"]:
        for p in e.get("plantillas_precio") or []:
            clave = f"{e['id']}/{p['id']}"
            if clave in quitar:
                continue
            k = med.get((e["id"], p["id"]), {})
            medidor, precio = LUNA.get(p["id"], (k.get("medidor") or p["concepto"], (k.get("precios_eur") or [0.01])[0]))
            region = experto.valores_filtro(p["filtro"], "armRegionName")[0]
            unidad = "1M" if p["id"] in LUNA else k.get("unidad") or ("1 Hour" if p["impulsor"] == "tiempo" else "1K")
            arts[clave] = {"filtro": p["filtro"], "precio_unitario": precio, "unidad": unidad,
                           "effectiveStartDate": "2026-09-01T00:00:00Z" if p["id"] in LUNA else "2025-08-01T00:00:00Z",
                           "meterName": medidor, "productName": k.get("producto") or "Azure OpenAI GPT6",
                           "skuName": k.get("sku") or "DZ", "armRegionName": region, "articulos_devueltos": 1,
                           "sha256_articulo": hashlib.sha256(clave.encode()).hexdigest()}
    inst = {"schema": experto.ESQUEMA_INSTANTANEA, "fecha_consulta": fecha, "moneda": "EUR",
            "fuente": "https://prices.azure.com/api/retail/prices?currencyCode='EUR'", "plantillas": arts}
    inst["sha256"] = experto.sha256_instantanea(inst)
    return inst


def resellar(inst: dict) -> dict:
    inst["sha256"] = experto.sha256_instantanea(inst)
    return inst


def estado_brezalia() -> dict:
    e = json.loads((RAIZ / "pruebas" / "I16" / "REAL" / "B" / "sesion_2" / "estado.json").read_text(encoding="utf-8"))
    e["estado"], e["estado_previo"], e["motivo_bloqueo"], e["ronda_verificacion"] = "EN_ANALISIS", None, None, 0
    e["intentos"] = {"T1": 0, "T2": 0, "T3": 0, "T4": 0}
    c = e["carga"]
    c["briefs"] = [b for b in c["briefs"] if b["brief_id"].endswith("-R1")]
    for k in ("consolidado", "verificacion", "anexo_consumo", "estimacion", "textos_cliente"):
        c[k] = None
    c["respuestas_expertos"] = {}
    return e


def perfiles(brief: dict) -> list[str]:
    return brief["texto"].split("perfiles_permitidos: ")[1].split("\n")[0].split("; ")


TAREAS = [("T-01", "F0 - Arranque", "Análisis y arquitectura detallada", "AI Architect / Tech Lead", 24, 6),
          ("T-02", "F1 - Construcción", "Ingesta e indexación de procedimientos", "Senior AI / Foundry Engineer", 48, 4),
          ("T-03", "F1 - Construcción", "Asistente en Teams con citas", "AI Engineer / Tech Lead", 40, 4),
          ("T-04", "F2 - Piloto", "Pruebas de calidad y piloto", "Consultor Junior", 24, 4)]
COMPONENTES = [("C-01", "az-foundry", "Microsoft Foundry", "ia", "gpt-6-luna Data Zone", "swedencentral", "despliegue"),
               ("C-02", "az-ai-search", "Azure AI Search", "datos_conocimiento", "Basic", "francecentral", "servicio"),
               ("C-03", "az-bot-service", "Azure AI Bot Service", "usuarios_canales", "Standard", "westeurope", "bot"),
               ("C-04", "az-app-service", "Azure App Service", "aplicacion_integracion", "B1", "swedencentral", "instancia"),
               ("C-05", "az-entra-id", "Microsoft Entra ID", "identidad_seguridad_red", "Incluido en el tenant", "global",
                "tenant"),
               ("C-06", "az-teams", "Microsoft Teams", "usuarios_canales", "Incluido en Microsoft 365", "global", "tenant")]
CONSULTAS = {"cita": "Unas 2.000 consultas al mes.", "cantidad_base": 2000, "unidad_base": "consultas al mes"}
# I1.9 (contrato v5): AI Search Basic y App Service B1 son el valor por defecto del catálogo (nivel_por_defecto con
# fuente y cómputo por defecto): su justificacion_nivel va null. Las de I1.7 (requisito, límite y fuente) ya no valen.
NIVELES: dict = {}


def respuesta_v4(brief: dict) -> dict:
    precios = [("P-01", "C-01", "gpt-6-luna-entrada", None, CONSULTAS), ("P-02", "C-01", "gpt-6-luna-salida", None, CONSULTAS),
               ("P-03", "C-02", "basic", None, None), ("P-04", "C-03", "canales-estandar", None, CONSULTAS),
               ("P-05", "C-04", "b1-linux", 1, None)]
    return {
        "brief_recibido": brief["texto"], "brief_id": brief["brief_id"], "agente": "preventa-experto-azure",
        "arquitectura_id": ARQUITECTURA["id"],
        "referencias": [{"id": "REF-01", "url": LEARN + "search/retrieval-augmented-generation-overview",
                         "titulo": "Generación aumentada por recuperación en Azure AI Search", "fecha_consulta": "2026-10-13"}],
        "componentes": [{"id": i, "catalogo_id": ca, "servicio": s, "capa": cp, "sku": sk, "region": r, "cantidad": 1,
                         "unidad": u, "referencia_id": None, "desviacion_justificada": None,
                         "motivo_no_valoracion": "no_aplica", "existente_del_cliente": None, "incluido_en": None,
                         "justificacion_nivel": copy.deepcopy(NIVELES.get(i))} for i, ca, s, cp, sk, r, u in COMPONENTES],
        "flujos": [{"origen": "C-06", "destino": "C-03", "descripcion": "Teams entrega la pregunta al bot"},
                   {"origen": "C-03", "destino": "C-04", "descripcion": "El bot llama a la aplicación"},
                   {"origen": "C-04", "destino": "C-01", "descripcion": "La aplicación invoca el modelo"},
                   {"origen": "C-04", "destino": "C-02", "descripcion": "La aplicación recupera fragmentos"},
                   {"origen": "C-05", "destino": "C-04", "descripcion": "Autenticación del usuario"}],
        "decisiones": ["Modelo gpt-6-luna en Data Zone UE para mantener los datos en la Unión Europea."],
        "alternativas_descartadas": ["Aplicación móvil propia: queda fuera de alcance."],
        "supuestos": [{"id": "S-01", "texto": "Los permisos de los documentos se respetan con filtros por grupo de Entra ID.",
                       "confianza": "MEDIA", "hechos": ["R-identidad_acl_origen", "REF-01"]}],
        "riesgos": [{"id": "RG-01", "texto": "La calidad de las respuestas depende de la vigencia de los procedimientos.",
                     "mitigacion": "Batería de preguntas de prueba validada con mantenimiento antes del piloto.",
                     "hechos": ["R-alcance_funcional", "C-01"]}],
        "preguntas": ["Confirmar si los procedimientos tienen versiones en otros idiomas."],
        "tareas_propuestas": [{"id": i, "fase": f, "tarea": ta, "perfil": pe, "horas_base": h, "reuniones_h": rh,
                               "descripcion": f"{ta}, revisado con el equipo del cliente.", "entregable": f"Entregable: {ta.lower()}"}
                              for i, f, ta, pe, h, rh in TAREAS],
        "precios": [{"id": i, "componente_id": c, "plantilla_id": pl, "instancias": n,
                     "base_volumen": copy.deepcopy(b), "factor_override": None} for i, c, pl, n, b in precios],
        "herramientas_usadas": {"microsoft_docs_search": 2, "microsoft_docs_fetch": 1},
    }
