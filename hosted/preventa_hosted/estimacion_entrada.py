"""Construye entrada/estimacion_entrada.json POR CÓDIGO desde el estado (sin modelo; arregla H4).

La regla vive en el NÚCLEO (`nucleo.estimacion.componer_entrada`, decisión del comercial del 10-10-2026) para que
A (`estimar` sin --entrada) y B la apliquen igual; aquí solo se llama:
- una tarea por cada `tareas_propuestas` del experto, con `tecnicas_h` = `horas_base` y sus `reuniones_h`;
- gestión de proyecto = máx(8 h, ⌈15 % de las horas técnicas⌉) y 1 h de seguimiento por semana;
- Gantt secuencial por fases, con los perfiles distintos de cada fase en paralelo:
  semanas = máx(1, ⌈horas de la fase / (40 × perfiles distintos)⌉);
- hitos de la tarifa, `ajuste_comercial_eur` = 0 y sin contingencia; lo que no cabe se omite y se declara.
El núcleo la vuelve a validar en `estimar`.
"""
from __future__ import annotations

from datetime import date


def construir(estado: dict, hitos: list[dict], hoy: date | None = None) -> tuple[dict, list[str]]:
    """(entrada, avisos). `hitos` = nucleo.estimacion.hitos_tarifa(tarifa). ValueError si falta algo."""
    from nucleo.estimacion import componer_entrada  # el núcleo ya está cargado por abrir()

    return componer_entrada(estado, hitos, hoy)
