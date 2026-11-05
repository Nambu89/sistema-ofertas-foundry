"""Arreglos I1.7 · textos del cliente:

- PR17-7: el pie de la diapositiva 4 publica la arquitectura de referencia ELEGIDA (valoracion_nucleo.arquitectura)
  aunque otra página sin componente del mismo tema (la guía de RAG) venga antes en la respuesta.
- PR17-9: las dos líneas de Functions Premium se distinguen (núcleos y memoria) y la página de límites de las
  suscripciones no se rotula «Azure Resource Manager». Sin red.
"""
from __future__ import annotations

from tests.i17_p_datos import RAIZ  # noqa: F401  (pone sandbox/ en sys.path)
from nucleo import textos_cliente as tc

ARQ = "https://learn.microsoft.com/azure/architecture/ai-ml/architecture/basic-microsoft-foundry-chat"
RAG = "https://learn.microsoft.com/azure/architecture/ai-ml/guide/rag/rag-solution-design-and-evaluation-guide"
LIMITES = "https://learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits"
SEARCH = "https://learn.microsoft.com/azure/search/search-what-is-azure-search"


def _resp(elegida: str | None):
    refs = [{"id": "REF-01", "url": SEARCH, "titulo": "What is Azure AI Search?", "fecha_consulta": "2026-10-13"},
            {"id": "REF-02", "url": RAG, "titulo": "Design and develop a RAG solution", "fecha_consulta": "2026-10-13"},
            {"id": "REF-03", "url": ARQ, "titulo": "Basic Microsoft Foundry chat reference architecture",
             "fecha_consulta": "2026-10-13"}]
    r = {"componentes": [{"id": "C-01", "servicio": "Azure AI Search", "catalogo_id": None, "referencia_id": "REF-01",
                          "capa": "datos_conocimiento"}], "referencias": refs, "flujos": [], "precios": []}
    if elegida:
        r["valoracion_nucleo"] = {"arquitectura": {"id": "foundry-chat-basica", "url": ARQ, "referencia_id": elegida}}
    return r


def _pie(resp):
    comp_ = tc._Composicion([], frozenset())
    capas = tc._arquitectura(resp, {}, comp_)["capas"]
    return [r["url"] for r in tc._referencias(resp, capas, comp_)], comp_


def test_pr17_7_la_arquitectura_elegida_ocupa_el_tema_y_la_guia_va_a_la_nota():
    urls, comp_ = _pie(_resp("REF-03"))
    assert urls == [SEARCH, ARQ]
    assert any(x["origen"] == "referencia REF-02" and "ya lleva una página" in x["motivo"] for x in comp_.excluidas)


def test_pr17_7_sin_arquitectura_elegida_se_conserva_el_orden_de_la_respuesta():
    urls, _ = _pie(_resp(None))
    assert urls == [SEARCH, RAG]


def test_pr17_9_nucleos_y_memoria_se_distinguen():
    base = {"servicio": "Azure Functions", "filtro": "serviceName eq 'Functions'"}
    vcpu = tc.concepto_legible({**base, "concepto": "Premium vCPU Duration", "unidad": "1 Hour"})
    mem = tc.concepto_legible({**base, "concepto": "Premium Memory Duration", "unidad": "1 GiB Hour"})
    assert vcpu == "Tiempo de funcionamiento de los núcleos" and mem == "Tiempo de funcionamiento de la memoria"
    assert tc.concepto_legible({**base, "concepto": "B1", "unidad": "1 Hour"}) == "Tiempo de funcionamiento"
    assert not tc.jerga_tecnica(vcpu) and not tc.jerga_tecnica(mem)


def test_pr17_9_pagina_de_limites_con_su_tema():
    assert tc.titulo_referencia(LIMITES) == ("Documentación oficial de Microsoft sobre los límites de las suscripciones "
                                            "y los servicios de Azure")
    assert tc.titulo_referencia("https://learn.microsoft.com/azure/azure-resource-manager/management/overview") == \
        "Documentación oficial de Microsoft sobre Azure Resource Manager"
