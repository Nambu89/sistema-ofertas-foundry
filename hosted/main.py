"""Punto de entrada del hosted agent preventa (opción B), protocolo Responses 2.0.0.

Sin Microsoft Agent Framework: azure-ai-agentserver-responses 2.2.0 (fijado exacto en requirements.txt).
El manejador del turno, y no un modelo, ejecuta la máquina de estados del núcleo (hosted/LEEME.md).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading

from azure.ai.agentserver.responses import CreateResponse, ResponseContext, ResponsesAgentServerHost, TextResponse

from preventa_hosted import adjuntos, config
from preventa_hosted.turno import Coordinador

LOG = logging.getLogger("preventa_hosted")
_CRED_LOCK = threading.Lock()
_CRED = None


def token() -> str:
    """Token de la identidad del propio agente para https://ai.azure.com (nunca se imprime ni se guarda)."""
    global _CRED
    with _CRED_LOCK:
        if _CRED is None:
            from azure.identity import DefaultAzureCredential
            _CRED = DefaultAzureCredential()
        cred = _CRED
    return cred.get_token(config.SCOPE_FOUNDRY).token


def preparar_entorno() -> None:
    """Apunta el núcleo a los recursos canónicos empaquetados (sin pisar lo que ya venga fijado)."""
    for nombre, ruta in config.recursos().items():
        os.environ.setdefault(nombre, str(ruta))


def marcar_orquestador() -> None:
    """VER14-3 / REV-5 (I1.5): este proceso es la opción B; el núcleo lo deja escrito en estado.json y en el manifiesto.
    Se fuerza (no setdefault): un valor heredado distinto sería una marca falsa. Solo al arrancar como agente
    (`python main.py`), no al importar el módulo en las pruebas."""
    os.environ["PREVENTA_ORQUESTADOR"] = "B"


preparar_entorno()
app = ResponsesAgentServerHost()


def crear_coordinador(cfg) -> Coordinador:
    """Un coordinador por turno con la identidad del agente (las pruebas lo sustituyen por dobles)."""
    return Coordinador(cfg, token)


@app.response_handler
async def turno(request: CreateResponse, context: ResponseContext, cancellation_signal: asyncio.Event):
    try:
        cfg = config.cargar()
    except config.ErrorConfig as exc:
        return TextResponse(context, request, text=f"Configuración inválida del agente: {exc}")
    try:
        texto, ficheros = adjuntos.leer_items(await context.get_input_items())
        coordinador = crear_coordinador(cfg)
        respuesta = await asyncio.to_thread(coordinador.manejar, texto, ficheros, cancellation_signal.is_set)
    except Exception as exc:  # fallo inesperado: se dice con su motivo, nunca un error opaco
        LOG.exception("fallo inesperado en el turno")
        respuesta = (f"FALLO INESPERADO del coordinador: {type(exc).__name__}: {str(exc)[:1500]}. "
                     "El estado guardado no se ha tocado más allá del último paso que muestre ESTADO.")
    return TextResponse(context, request, text=respuesta)


if __name__ == "__main__":
    preparar_entorno()
    marcar_orquestador()
    app.run()
