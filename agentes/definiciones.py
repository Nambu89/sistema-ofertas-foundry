"""Definiciones de los agentes de I0 (prompt agents) y de sus agent cards A2A v1.0.

Las formas salen de la documentación descargada: tool mcp (tools_model-context-protocol.md),
openapi anónima (tools_openapi.md), code_interpreter con file_ids en la definición
(code-interpreter.md) y tool a2a v1.0 con project_connection_id (a2a.md / a2a-endpoint.md).
"""
from __future__ import annotations

import json
import pathlib

AQUI = pathlib.Path(__file__).resolve().parent

MCP_LEARN = {"type": "mcp", "server_label": "mslearn",
             "server_url": "https://learn.microsoft.com/api/mcp",
             # La API guarda la lista como filtro {"tool_names": [...]} (MCPToolFilter, prueba
             # real del 07-10-2026); se envía ya en esa forma para que la relectura sea exacta.
             "allowed_tools": {"tool_names": ["microsoft_docs_search", "microsoft_docs_fetch"]},
             "require_approval": "never"}


def instrucciones(nombre: str) -> str:
    """Lee agentes/instrucciones_<nombre>.md (UTF-8)."""
    return (AQUI / f"instrucciones_{nombre}.md").read_text(encoding="utf-8").strip()


def tool_precios() -> dict:
    """OpenAPI anónima de Azure Retail Prices (especificación probada en F3)."""
    spec = json.loads((AQUI / "prices-openapi.json").read_text(encoding="utf-8"))
    return {"type": "openapi", "openapi": {
        "name": "precios_azure",
        "description": "Precios minoristas públicos de Azure (Azure Retail Prices), sin autenticación.",
        "spec": spec, "auth": {"type": "anonymous"}}}


def def_experto_azure(modelo: str) -> dict:
    """preventa-experto-azure: Learn MCP + precios por OpenAPI anónima."""
    return {"kind": "prompt", "model": modelo, "instructions": instrucciones("experto_azure"),
            "tools": [dict(MCP_LEARN), tool_precios()]}


def def_verificador(modelo: str) -> dict:
    """preventa-verificador: crítico independiente con Learn MCP."""
    return {"kind": "prompt", "model": modelo, "instructions": instrucciones("verificador"),
            "tools": [dict(MCP_LEARN)]}


def def_coordinador(modelo: str, file_ids: list[str], conexiones_a2a: list[str]) -> dict:
    """preventa-coordinador: code_interpreter con file_ids montados y un tool a2a v1.0 por conexión."""
    tools: list[dict] = [{"type": "code_interpreter",
                          "container": {"type": "auto", "file_ids": list(file_ids)}}]
    for cid in conexiones_a2a:
        tools.append({"type": "a2a", "a2a_version": "1.0", "project_connection_id": cid})
    return {"kind": "prompt", "model": modelo, "instructions": instrucciones("coordinador"),
            "tools": tools}


CARD_EXPERTO = {
    "description": ("Experto en arquitectura Azure de Devoteam: a partir de un brief anonimizado "
                    "devuelve un JSON con referencias oficiales de Learn, componentes y precios "
                    "de Azure Retail Prices."),
    "version": "1.0",
    "skills": [{"id": "arquitectura-azure", "name": "Arquitectura Azure",
                "description": "Diseño por capas con arquitecturas de referencia oficiales y precios."}]}

CARD_VERIFICADOR = {
    "description": ("Crítico independiente: revisa referencias, componentes y precios y devuelve "
                    "OK, DISCREPA o NO VERIFICABLE por elemento."),
    "version": "1.0",
    "skills": [{"id": "verificacion", "name": "Verificación",
                "description": "Comprueba con Learn cada elemento de un JSON consolidado."}]}


# ───────────────────────────── I1 ─────────────────────────────
# Instrucciones en agentes/instrucciones/<nombre>_i1.md y text.format json_schema estricto en
# agentes/esquemas/<respuesta>.text_format.json (versión derivada de §14, sin pattern ni $ref;
# el esquema completo lo aplica siempre el código). CAMBIOS-INTERFAZ-BD.md §4.

def instrucciones_i1(nombre: str) -> str:
    """Lee agentes/instrucciones/<nombre>_i1.md (UTF-8)."""
    return (AQUI / "instrucciones" / f"{nombre}_i1.md").read_text(encoding="utf-8").strip()


def text_format(respuesta: str) -> dict:
    """Bloque text.format literal de agentes/esquemas/<respuesta>.text_format.json."""
    return json.loads((AQUI / "esquemas" / f"{respuesta}.text_format.json").read_text(encoding="utf-8"))


def def_experto_azure_i1(modelo: str) -> dict:
    """preventa-experto-azure I1: Learn MCP + salida estructurada estricta (I1.7, decisión 1: sin herramienta de precios; los pone el núcleo desde la instantánea)."""
    return {"kind": "prompt", "model": modelo, "instructions": instrucciones_i1("experto_azure"),
            "tools": [dict(MCP_LEARN)], "text": {"format": text_format("respuesta_experto")}}


def def_verificador_i1(modelo: str) -> dict:
    """preventa-verificador I1: Learn MCP (I1.7, decisión 1: sin herramienta ni lote de precios)."""
    return {"kind": "prompt", "model": modelo, "instructions": instrucciones_i1("verificador"),
            "tools": [dict(MCP_LEARN)], "text": {"format": text_format("respuesta_verificador")}}


def def_coordinador_i1(modelo: str, file_ids: list[str], conexiones_a2a: list[str]) -> dict:
    """preventa-coordinador I1: code_interpreter con los file_ids de I1 y un tool a2a v1.0 por conexión."""
    defi = def_coordinador(modelo, file_ids, conexiones_a2a)
    defi["instructions"] = instrucciones_i1("coordinador")
    return defi
