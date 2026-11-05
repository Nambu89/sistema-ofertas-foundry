"""Lectura de la salida del coordinador B por sus marcadores explícitos (LES-G-030).

El turno de B termina siempre con bloques que escribe el código del núcleo, no un modelo:
«=== ESTADO PREVENTA === … === FIN ESTADO ===», «=== PREGUNTAS PARA EL COMERCIAL === … === FIN PREGUNTAS ===» y la
línea «PAQUETE: <nombre>.zip (<n> B, SHA-256 <hex>)». Aquí solo se leen esos bloques; el resto del texto se
muestra tal cual en el registro y nunca decide nada. Contrato comprobado con turnos reales guardados en
bff/reproduccion/turnos (test_bff.py).
"""
from __future__ import annotations

import re

# Orden del núcleo (sandbox/nucleo/estado.py) para dibujar el avance. INFORMACION_INSUFICIENTE va entre el
# borrador y el análisis; los de revisión no se recorren desde el frontal.
ORDEN_FASES = ("BORRADOR", "INFORMACION_INSUFICIENTE", "EN_ANALISIS", "EN_VERIFICACION", "VERIFICADA",
               "LISTA_PARA_REVISION")
# Mismas paradas que hosted/preventa_hosted/turno.py (PARADAS) más las que esperan a una persona.
PARADAS = frozenset({"STOP_PRESUPUESTO", "LISTA_PARA_REVISION", "EN_REVISION_PREVENTA", "EN_APROBACION_AREA",
                     "BLOQUEADA", "INFORMACION_INSUFICIENTE", "DEVUELTA_CON_COMENTARIOS", "APROBADA"})

_ESTADO = re.compile(r"^=== ESTADO PREVENTA ===\n(.*?)^=== FIN ESTADO ===", re.M | re.S)
_PREGUNTAS = re.compile(r"^=== PREGUNTAS PARA EL COMERCIAL ===\n(.*?)^=== FIN PREGUNTAS ===", re.M | re.S)
_OPCION = re.compile(r"^\s+([a-d])\)\s+(.+?)\s*$")
_CAMPO = re.compile(r"^([a-z_]{3,40}):\s+(.+?)\s*$")
# La línea del coordinador lleva el nombre justo detrás; la del núcleo dice «PAQUETE: OK salida/…» y no casa.
_PAQUETE = re.compile(r"^PAQUETE: (OF-[A-Z0-9]+-[0-9]{3}-[A-Z]-Paquete\.zip) \((\d+) B, SHA-256 ([0-9a-f]{64})\)",
                      re.M)
_PRECIO = re.compile(r"^ESTIMACIÓN: precio cerrado ([0-9]+(?:\.[0-9]+)?) EUR", re.M)
_CONSUMO = re.compile(r"^ANEXO DE CONSUMO: .*?([0-9]+(?:\.[0-9]+)?) EUR/mes", re.M)
_LOTE = re.compile(r"\((\d+) de (\d+) del consolidado")


def ultimo_estado(texto: str) -> dict[str, str] | None:
    """Campos del último bloque de estado del turno, o None si el turno no trae ninguno."""
    bloques = _ESTADO.findall(texto or "")
    if not bloques:
        return None
    campos: dict[str, str] = {}
    for linea in bloques[-1].splitlines():
        clave, sep, valor = linea.partition(": ")
        if sep and clave and " " not in clave:
            campos[clave] = valor.strip()
        elif linea.startswith("SIGUIENTE PASO OBLIGATORIO:"):
            campos["siguiente"] = linea.split(":", 1)[1].strip()
    return campos if "estado" in campos else None


def preguntas(texto: str) -> list[dict]:
    """Preguntas a/b/c/d del último bloque. La opción d («otra») se marca como texto libre."""
    bloques = _PREGUNTAS.findall(texto or "")
    if not bloques:
        return []
    salida: list[dict] = []
    for linea in bloques[-1].splitlines():
        m = _OPCION.match(linea)
        if m and salida:
            libre = m.group(2).lower().startswith("otra")
            salida[-1]["opciones"].append({"letra": m.group(1), "texto": m.group(2), "libre": libre})
            continue
        m = _CAMPO.match(linea)
        if m:
            salida.append({"campo": m.group(1), "pregunta": m.group(2), "opciones": []})
    return salida


def paquete(texto: str) -> dict | None:
    m = list(_PAQUETE.finditer(texto or ""))
    if not m:
        return None
    nombre, n, sha = m[-1].groups()
    return {"nombre": nombre, "bytes": int(n), "sha256": sha}


def economia(texto: str) -> dict:
    """Precio cerrado y consumo mensual tal como los imprime el núcleo (último valor del turno)."""
    precio = _PRECIO.findall(texto or "")
    consumo = _CONSUMO.findall(texto or "")
    return {k: float(v[-1]) for k, v in (("precio_cerrado_eur", precio), ("consumo_mes_eur", consumo)) if v}


def lote(siguiente: str) -> dict | None:
    m = _LOTE.search(siguiente or "")
    return {"actual": int(m.group(1)), "total": int(m.group(2))} if m else None


def indice_fase(estado: str | None) -> int:
    return ORDEN_FASES.index(estado) if estado in ORDEN_FASES else -1
