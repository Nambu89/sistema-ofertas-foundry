"""Hosted agent desechable ofa-prueba-hosted (paso 0a): protocolo Responses 2.0.0, sin modelo y sin MAF.

Dependencias bundled en packages/ (Learn, deploy-hosted-agent-code: «You ship prebuilt Linux dependencies in
packages/»). Se añade packages/ a sys.path por si el runtime no lo hace. Las órdenes viven en
ofa_prueba_hosted/ordenes.py; la respuesta es siempre un JSON en texto.

`response.completed` lleva siempre `usage` (a cero: este agente no llama a ningún modelo). Comprobado el
18-10-2026 con OpenCode 1.18.33: con `"usage": null` (lo que emite `TextResponse`), su SDK no reconoce el fin
del turno, deja el motivo de fin en «unknown» y OpenCode repite la petición en bucle hasta el tiempo máximo.
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sys

_PAQUETES = pathlib.Path(__file__).resolve().parent / "packages"
if _PAQUETES.is_dir() and str(_PAQUETES) not in sys.path:
    sys.path.insert(0, str(_PAQUETES))

from ofa_prueba_hosted import ordenes  # noqa: E402

# Se lee una sola vez al arrancar y se borra de os.environ; nunca se registra ni se devuelve el valor.
MARCADOR = ordenes.leer_marcador(os.environ)

from azure.ai.agentserver.responses import (  # noqa: E402
    CreateResponse, ResponseContext, ResponseEventStream, ResponsesAgentServerHost)

LOG = logging.getLogger("ofa_prueba_hosted")
app = ResponsesAgentServerHost()
USO_CERO = {"input_tokens": 0, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 0,
            "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 0}


async def _eventos(context: ResponseContext, request: CreateResponse, texto):
    """Mismos eventos que `TextResponse` con texto de una sola vez, pero con `usage` en el cierre."""
    stream = ResponseEventStream(response_id=context.response_id, request=request)
    yield stream.emit_created()
    yield stream.emit_in_progress()
    mensaje = stream.add_output_item_message()
    yield mensaje.emit_added()
    contenido = mensaje.add_text_content()
    yield contenido.emit_added()
    resultado = await texto()
    yield contenido.emit_delta(resultado)
    yield contenido.emit_text_done(resultado)
    yield contenido.emit_done()
    yield mensaje.emit_done()
    yield stream.emit_completed(usage=dict(USO_CERO))


@app.response_handler
async def turno(request: CreateResponse, context: ResponseContext, cancellation_signal):
    items = await context.get_input_items()
    orden, argumento = ordenes.interpretar(ordenes.ultimo_texto_usuario(items))

    async def producir() -> str:
        try:
            res = await ordenes.ejecutar(orden, argumento, marcador=MARCADOR, cancelado=cancellation_signal.is_set)
        except Exception as exc:  # noqa: BLE001 - se devuelve el motivo, nunca un error opaco
            LOG.exception("fallo en la orden %s", orden)
            res = {"orden": orden, "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
        return json.dumps(res, ensure_ascii=False)

    return _eventos(context, request, producir)


if __name__ == "__main__":
    app.run()
