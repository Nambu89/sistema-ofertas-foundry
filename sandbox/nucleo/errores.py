"""Excepciones del núcleo de preventa (CONTRATOS.md §4.1 y §11.1).

Todas se construyen como Clase(mensaje, errores): `mensaje` es el resumen y `errores` la lista
completa de hallazgos (fail loudly: nunca solo el primero). `codigo_salida` es el rc de la CLI.
"""
from __future__ import annotations


class ErrorPreventa(Exception):
    """Base. .mensaje: str; .errores: list[str]; .codigo_salida: int."""

    codigo_salida = 5

    def __init__(self, mensaje: str, errores: list[str] | None = None):
        super().__init__(mensaje)
        self.mensaje = str(mensaje)
        self.errores = [str(e) for e in (errores or [])]


class EntradaInvalida(ErrorPreventa):
    """rc 2: argumentos o ficheros de la CLI; no se guarda nada."""

    codigo_salida = 2


class ReglaIncumplida(ErrorPreventa):
    """rc 1: regla de negocio; la CLI guarda el estado (contadores)."""

    codigo_salida = 1


class Bloqueo(ErrorPreventa):
    """rc 1: quien la lanza ya llamó a estado.bloquear(); la CLI guarda."""

    codigo_salida = 1


class TransicionNoPermitida(ErrorPreventa):
    """rc 3: no se guarda nada."""

    codigo_salida = 3


class IntegridadRota(ErrorPreventa):
    """rc 4: manifiesto, hash o SHA-256 que no cuadran; no se guarda nada."""

    codigo_salida = 4
