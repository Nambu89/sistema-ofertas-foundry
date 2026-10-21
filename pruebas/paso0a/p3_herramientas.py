"""P3 · Prompt agent ofa-prueba-herramientas (gpt-5.6-luna) con MCP de Microsoft Learn y Web Search de Foundry.

Formas verificadas el 18-10-2026:
- MCP: {"type": "mcp", "server_label", "server_url": "https://learn.microsoft.com/api/mcp", "allowed_tools":
  {"tool_names": [...]}, "require_approval": "never"} (forma guardada por la API, MVP agentes/definiciones.py).
  Nombres confirmados con `tools/list` contra https://learn.microsoft.com/api/mcp: microsoft_docs_search,
  microsoft_docs_fetch y microsoft_code_sample_search. Se permiten solo los dos primeros (búsqueda y lectura).
- Web Search: {"type": "web_search"} añadido directamente al prompt agent («doesn't require a toolbox or a
  separate Bing project connection», learn…/agents/how-to/tools/web-search, ms.date 2026-09-03). Aviso de
  Learn: los datos van a Grounding with Bing y salen del límite de cumplimiento: por eso solo datos sintéticos.
  Una suscripción puede bloquearlo con la característica OpenAI.BlockedTools.web_search.
- Llamada: POST {proyecto}/openai/v1/responses (sin api-version, LES-G-014) con agent_reference,
  `background: true`, `store: true` y `tool_choice: "required"`; sondeo con GET …/responses/{id}.
Evidencia: los tipos de los items de llamada a herramienta (mcp_call, web_search_call) de cada respuesta.

Pasos (cada invocación avanza lo que quepa en el presupuesto): crear → lanzar → sondear → veredicto.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pruebas.paso0a import comun

ID = "P3"
TITULO = "Prompt agent con MCP de Learn y Web Search"
AGENTE = comun.AGENTE_HERRAMIENTAS
MODELO = "gpt-5.6-luna"
HERRAMIENTAS_MCP = ("microsoft_docs_search", "microsoft_docs_fetch")
MCP_LEARN = {"type": "mcp", "server_label": "mslearn", "server_url": "https://learn.microsoft.com/api/mcp",
             "allowed_tools": {"tool_names": list(HERRAMIENTAS_MCP)}, "require_approval": "never"}
WEB_SEARCH = {"type": "web_search"}
INSTRUCCIONES = ("Eres un agente de prueba desechable del sistema de ofertas. Todo lo que recibes es sintético. "
                 "Usa exactamente la herramienta que te pida el usuario y responde en castellano, en dos líneas "
                 "como máximo, con el dato y la URL de la fuente.")
PREGUNTAS = {
    "mcp": ("Usa la herramienta microsoft_docs_search del servidor mslearn (no la búsqueda web) para averiguar "
            "qué valores admite code_configuration.runtime en los hosted agents de Microsoft Foundry."),
    "web": ("Usa la búsqueda web (no Microsoft Learn) para averiguar cuál es la última versión publicada en "
            "pypi.org del paquete de Python requests."),
}
ESPERA_SONDEO_S = 10.0
TIMEOUT_POST_S = 30.0
TIMEOUT_SONDEO_S = 15.0
MAX_SONDEO_S = 900.0
_RE_WEB_BLOQUEADA = re.compile(r"web[_ ]?search|bing|blockedtools|grounding", re.IGNORECASE)


def definicion(con_web: bool = True) -> dict:
    tools: list[dict] = [dict(MCP_LEARN)]
    if con_web:
        tools.append(dict(WEB_SEARCH))
    return {"kind": "prompt", "model": MODELO, "instructions": INSTRUCCIONES, "tools": tools}


def cuerpo_respuesta(version: str | None, pregunta: str) -> dict:
    ref: dict[str, Any] = {"type": "agent_reference", "name": AGENTE}
    if version:
        ref["version"] = str(version)
    return {"agent_reference": ref, "input": [{"role": "user", "content": pregunta}],
            "background": True, "store": True, "tool_choice": "required"}


def tipos_llamadas(respuesta: Any) -> list[str]:
    """Tipos de los items de salida que no son mensajes (las llamadas a herramientas), en orden."""
    if not isinstance(respuesta, dict):
        return []
    return [str(i.get("type")) for i in respuesta.get("output") or []
            if isinstance(i, dict) and i.get("type") not in (None, "message", "reasoning")]


def estados_literales(respuesta: dict, tipo: str) -> list:
    """Status literal (None si no viene) de cada item de salida del tipo pedido, para la evidencia."""
    return [i.get("status") for i in respuesta.get("output") or [] if isinstance(i, dict) and i.get("type") == tipo]


def items_io(respuesta: dict, maximo: int = 1500) -> list[dict]:
    """Items de salida que no son razonamiento, con su forma literal y los textos largos recortados."""
    items = []
    for i in respuesta.get("output") or []:
        if not isinstance(i, dict) or i.get("type") == "reasoning":
            continue
        copia = {}
        for k, v in i.items():
            t = v if isinstance(v, (str, int, float, bool, type(None))) else json.dumps(v, ensure_ascii=False)
            copia[k] = comun.recortar(t, maximo) if isinstance(t, str) else t
        items.append(copia)
    return items


def evaluar_mcp(respuesta: dict) -> tuple[str, str]:
    llamadas = [i for i in respuesta.get("output") or [] if isinstance(i, dict) and i.get("type") == "mcp_call"]
    buenas = [i for i in llamadas if i.get("server_label") == "mslearn" and i.get("name") in HERRAMIENTAS_MCP
              and not i.get("error")]
    tipos = tipos_llamadas(respuesta)
    if respuesta.get("status") != "completed":
        return "FALLA", f"status={respuesta.get('status')} error={respuesta.get('error')} tipos={tipos}"
    if buenas:
        return "PASA", (f"tipos={tipos}; mcp_call {[i.get('name') for i in buenas]} en mslearn sin error; "
                        f"status literal de cada mcp_call={estados_literales(respuesta, 'mcp_call')}")
    errores = [i.get("error") for i in llamadas if i.get("error")]
    return "FALLA", f"sin mcp_call válido de mslearn; tipos={tipos}; errores={errores}"


def evaluar_web(respuesta: dict) -> tuple[str, str]:
    tipos = tipos_llamadas(respuesta)
    if respuesta.get("status") != "completed":
        motivo = str(respuesta.get("error") or respuesta.get("incomplete_details") or "")
        estado = "PENDIENTE_FERNANDO" if _RE_WEB_BLOQUEADA.search(motivo) else "FALLA"
        return estado, f"status={respuesta.get('status')} motivo literal={motivo[:600]} tipos={tipos}"
    literales = estados_literales(respuesta, "web_search_call")
    # Solo cuenta un status «completed» literal: un item sin status no demuestra que la búsqueda terminara.
    if "completed" in literales:
        return "PASA", f"tipos={tipos}; status literal de cada web_search_call={literales}"
    return "FALLA", f"sin web_search_call con status completed; status literales={literales}; tipos={tipos}"


def es_rechazo_web(texto: str) -> bool:
    """¿El rechazo de la definición se debe a la herramienta Web Search (recurso, permiso o bloqueo)?"""
    return bool(_RE_WEB_BLOQUEADA.search(texto or ""))


# ------------------------------------------------------------------------------------------- pasos
def _crear(ctx: comun.Contexto, pr: dict) -> comun.EnCurso | dict | None:
    existe = ctx.cliente.datos("GET", f"agents/{AGENTE}", timeout=TIMEOUT_SONDEO_S)
    if existe.estado not in (200, 404):
        return _final(ctx, pr, "FALLA", f"No se pudo consultar el agente: {existe.resumen()}")
    for con_web in (True, False):
        defi = definicion(con_web)
        if existe.estado == 404:
            r = ctx.cliente.datos("POST", "agents", json_body={"name": AGENTE, "definition": defi,
                                                               "description": "Prueba desechable P3 (paso 0a)"},
                                  timeout=TIMEOUT_POST_S)
        else:
            r = ctx.cliente.datos("POST", f"agents/{AGENTE}/versions", json_body={"definition": defi},
                                  timeout=TIMEOUT_POST_S)
        if r.estado in (200, 201):
            j = r.json() or {}
            version = (j.get("versions") or {}).get("latest", {}).get("version") or j.get("version")
            pr.update({"version": str(version) if version else None, "con_web": con_web, "paso": "lanzar"})
            return None
        if con_web and r.estado == 400 and es_rechazo_web(r.texto):
            pr["web_rechazada"] = r.resumen(800)
            continue
        return _final(ctx, pr, "FALLA", f"La creación del agente falló: {r.resumen(800)}")
    return _final(ctx, pr, "FALLA", "La creación del agente falló también sin Web Search")


def _lanzar(ctx: comun.Contexto, pr: dict) -> comun.EnCurso | dict | None:
    pr.setdefault("respuestas", {})
    for clave in ("mcp", "web"):
        if clave == "web" and not pr.get("con_web"):
            continue
        if clave in pr["respuestas"]:
            continue
        r = ctx.cliente.datos("POST", "openai/v1/responses", json_body=cuerpo_respuesta(pr.get("version"),
                                                                                         PREGUNTAS[clave]),
                              timeout=TIMEOUT_POST_S)
        j = r.json() or {}
        if r.estado != 200 or not j.get("id"):
            pr["respuestas"][clave] = {"error_lanzar": r.resumen(800)}
            continue
        pr["respuestas"][clave] = {"id": j["id"], "status": j.get("status"), "t0": ctx.reloj()}
    pr["paso"] = "sondear"
    return None


def _sondear(ctx: comun.Contexto, pr: dict) -> comun.EnCurso | dict | None:
    pendientes = []
    for clave, info in pr["respuestas"].items():
        if "error_lanzar" in info or info.get("final"):
            continue
        r = ctx.cliente.datos("GET", f"openai/v1/responses/{info['id']}", timeout=TIMEOUT_SONDEO_S)
        j = r.json() or {}
        if r.estado != 200:
            info["errores_sondeo"] = info.get("errores_sondeo", 0) + 1
            info["ultimo_error"] = r.resumen(400)
            if info["errores_sondeo"] >= 3:
                info["final"] = {"status": "error_sondeo", "error": info["ultimo_error"]}
            else:
                pendientes.append(clave)
            continue
        if j.get("status") in comun.TERMINALES:
            info["final"] = {k: j.get(k) for k in ("id", "status", "error", "incomplete_details", "output")}
        elif ctx.reloj() - info["t0"] > MAX_SONDEO_S:
            info["final"] = {"status": "sin_terminar", "error": f"más de {MAX_SONDEO_S:.0f} s en {j.get('status')}"}
        else:
            info["status"] = j.get("status")
            pendientes.append(clave)
    if pendientes:
        return comun.EnCurso(f"P3: respuestas en curso ({', '.join(pendientes)})", ESPERA_SONDEO_S)
    pr["paso"] = "veredicto"
    return None


def _veredicto(ctx: comun.Contexto, pr: dict) -> dict:
    lineas, estados = [f"Agente {AGENTE} v{pr.get('version')} ({MODELO}); herramientas: mcp mslearn "
                       f"{list(HERRAMIENTAS_MCP)}" + (" + web_search" if pr.get("con_web") else "")], []
    for clave, evaluar in (("mcp", evaluar_mcp), ("web", evaluar_web)):
        info = pr.get("respuestas", {}).get(clave)
        if clave == "web" and not pr.get("con_web"):
            estados.append("PENDIENTE_FERNANDO")
            lineas.append(f"- web: PENDIENTE_FERNANDO. La API rechazó la herramienta al crear el agente; motivo "
                          f"literal: {pr.get('web_rechazada')}. Si menciona un recurso o el bloqueo "
                          "OpenAI.BlockedTools.web_search, Fernando decide si se habilita en la suscripción.")
            continue
        if not info:
            estados.append("FALLA")
            lineas.append(f"- {clave}: FALLA, no se lanzó la pregunta")
            continue
        if "error_lanzar" in info:
            est = "PENDIENTE_FERNANDO" if clave == "web" and es_rechazo_web(info["error_lanzar"]) else "FALLA"
            estados.append(est)
            lineas.append(f"- {clave}: {est}, el POST falló: {info['error_lanzar']}")
            continue
        est, det = evaluar(info["final"])
        estados.append(est)
        lineas.append(f"- {clave} (respuesta {info['id']}): {est} · {det}")
    io = {clave: {"id": info.get("id"), "status": (info.get("final") or {}).get("status"),
                  "items": items_io(info.get("final") or {})}
          for clave, info in pr.get("respuestas", {}).items() if isinstance(info, dict) and info.get("final")}
    if io:
        ruta_io = comun.escribir_json(ctx.dir_resultados / "P3-io.json", io)
        lineas.append(f"Salida de cada respuesta (items redactados y recortados): {ruta_io.name}")
    lineas.append("Aviso Learn: Web Search envía la consulta a Grounding with Bing, fuera del límite de "
                  "cumplimiento; en proyectos reales queda prohibido (diseño §3.3).")
    return _final(ctx, pr, comun.combinar_estados(estados), "\n".join(lineas))


def _final(ctx: comun.Contexto, pr: dict, estado: str, evidencia: str) -> dict:
    """El comando lleva todas las llamadas de la prueba, también las de invocaciones anteriores."""
    ctx.nuevas_llamadas(pr, "todas")
    llamadas = pr.get("llamadas", {}).get("todas", [])
    return comun.construir_resultado(ID, estado, evidencia, ctx.comando(ID, llamadas=llamadas), ctx.fecha())


PASOS = {"crear": (_crear, TIMEOUT_SONDEO_S + 2 * TIMEOUT_POST_S + 1), "lanzar": (_lanzar, 2 * TIMEOUT_POST_S + 1),
         "sondear": (_sondear, 2 * TIMEOUT_SONDEO_S + 1), "veredicto": (_veredicto, 1.0)}


def ejecutar(ctx: comun.Contexto) -> dict | comun.EnCurso:
    pr = ctx.leer_progreso(ID) or {"paso": "crear"}
    while True:
        funcion, duracion = PASOS[pr["paso"]]
        if ctx.restante() < duracion:
            ctx.guardar_progreso(ID, pr)
            return comun.EnCurso(f"P3: sin presupuesto para el paso {pr['paso']}; vuelve a ejecutar", 0)
        pr["_marca"] = len(ctx.cliente.llamadas)
        res = funcion(ctx, pr)
        ctx.nuevas_llamadas(pr, "todas")
        if isinstance(res, dict):
            ctx.borrar_progreso(ID)
            return res
        ctx.guardar_progreso(ID, pr)
        if isinstance(res, comun.EnCurso):
            return res
