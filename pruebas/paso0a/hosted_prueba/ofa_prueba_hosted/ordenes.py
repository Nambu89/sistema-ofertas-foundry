"""Órdenes de prueba del hosted agent ofa-prueba-hosted (paso 0a). Solo biblioteca estándar.

Cada orden llega como texto del ÚLTIMO mensaje del usuario, con la forma «ORDEN: <NOMBRE> [argumento]», y
devuelve un objeto JSON (la respuesta del agente es ese JSON en texto). Órdenes:
- SALIDA: GET con tiempo máximo a las tres URL de `URLS_SALIDA`; cualquier código HTTP demuestra que hay
  salida a Internet, un error de red no. Devuelve el código o el error de cada una.
- MARCADOR: informa de si la variable OFA_MARCADOR llegó resuelta desde la conexión del proyecto. Nunca
  devuelve el valor: solo si estaba presente, su longitud y si coincide con el valor sintético acordado.
  La variable se lee UNA vez al arrancar y se borra de os.environ (patrón del diseño, §7).
- TURNO_LARGO [segundos]: espera (360 s por defecto, como máximo 900) y responde al final con lo medido.
- ECO <texto>: devuelve «ECO-OFA: <texto>» (texto saneado), para comprobar clientes como OpenCode.
Cualquier otra cosa devuelve la ayuda; nada se ejecuta sin una orden reconocida.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Callable

# El tercer destino prueba la salida a *.blob.core.windows.net con una cuenta pública de Microsoft que existe
# (Azure Open Datasets). Corregido el 18-10-2026: «<proyecto>.blob…» no existe (NXDOMAIN también en 8.8.8.8),
# así que su error de DNS no decía nada sobre la salida del hosted.
URLS_SALIDA = ("https://learn.microsoft.com",
               "https://prices.azure.com/api/retail/prices?$top=1",
               "https://azureopendatastorage.blob.core.windows.net/")
TIMEOUT_SALIDA_S = 15.0
VARIABLE_MARCADOR = "OFA_MARCADOR"
VALOR_SINTETICO = "marcador-sintetico"
SEGUNDOS_TURNO_LARGO = 360
MAX_SEGUNDOS_TURNO = 900
ORDENES = ("SALIDA", "MARCADOR", "TURNO_LARGO", "ECO")
_RE_ORDEN = re.compile(r"ORDEN:\s*([A-Z_]+)(?:[ \t]+([^\r\n]*))?", re.IGNORECASE)
_RE_ECO = re.compile(r"[^A-Za-z0-9 _.\-]")


def _texto_de_contenido(contenido: Any) -> str:
    if isinstance(contenido, str):
        return contenido
    trozos = []
    for parte in contenido or []:
        if isinstance(parte, Mapping) and parte.get("type") in ("input_text", "text", "output_text"):
            trozos.append(str(parte.get("text") or ""))
    return "\n".join(trozos)


def ultimo_texto_usuario(items: Any) -> str:
    """Texto del último mensaje con rol de usuario. Clientes como OpenCode reenvían todo el historial."""
    texto = ""
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        if item.get("type", "message") == "message" and item.get("role", "user") == "user":
            texto = _texto_de_contenido(item.get("content"))
    return texto


def interpretar(texto: str) -> tuple[str, str]:
    """(orden, argumento). Una orden desconocida o ausente devuelve ('AYUDA', '')."""
    m = _RE_ORDEN.search(texto or "")
    if not m:
        return "AYUDA", ""
    orden = m.group(1).upper()
    if orden not in ORDENES:
        return "AYUDA", ""
    return orden, (m.group(2) or "").strip()


def sondear_salida(urls: tuple[str, ...] = URLS_SALIDA, abrir: Callable[..., Any] = urllib.request.urlopen,
                   timeout: float = TIMEOUT_SALIDA_S, reloj: Callable[[], float] = time.monotonic) -> list[dict]:
    """GET a cada URL. HTTPError (4xx/5xx) también es salida: se anota su código."""
    resultados = []
    for url in urls:
        t0 = reloj()
        peticion = urllib.request.Request(url, method="GET", headers={"User-Agent": "ofa-prueba-hosted/1"})
        try:
            with abrir(peticion, timeout=timeout) as r:
                resultados.append({"url": url, "http": int(r.status), "segundos": round(reloj() - t0, 3)})
        except urllib.error.HTTPError as e:
            resultados.append({"url": url, "http": int(e.code), "segundos": round(reloj() - t0, 3)})
        except Exception as e:  # noqa: BLE001 - error de red: se informa con su tipo y motivo
            resultados.append({"url": url, "error": f"{type(e).__name__}: {str(e)[:300]}",
                               "segundos": round(reloj() - t0, 3)})
    return resultados


def leer_marcador(entorno: dict) -> dict:
    """Lee OFA_MARCADOR, la BORRA del entorno y devuelve solo metadatos (nunca el valor)."""
    presente_en_entorno = VARIABLE_MARCADOR in entorno
    valor = entorno.pop(VARIABLE_MARCADOR, None)
    texto = valor if isinstance(valor, str) else ""
    sin_resolver = texto.startswith("${{")
    return {"variable_definida": presente_en_entorno, "presente": bool(texto) and not sin_resolver,
            "sin_resolver": sin_resolver, "longitud": len(texto),
            "coincide_con_sintetico": texto == VALOR_SINTETICO,
            "huella_sha256_8": hashlib.sha256(texto.encode("utf-8")).hexdigest()[:8] if texto else None,
            "borrada_de_entorno": VARIABLE_MARCADOR not in entorno}


async def turno_largo(segundos: int, cancelado: Callable[[], bool],
                      dormir: Callable[[float], Any] = asyncio.sleep,
                      reloj: Callable[[], float] = time.monotonic, paso_s: float = 1.0) -> dict:
    """Espera `segundos` (en pasos cortos, atento a la cancelación) y devuelve lo medido."""
    t0 = reloj()
    while reloj() - t0 < segundos:
        if cancelado():
            return {"orden": "TURNO_LARGO", "cancelado": True, "segundos_medidos": round(reloj() - t0, 1)}
        await dormir(min(paso_s, segundos - (reloj() - t0)))
    return {"orden": "TURNO_LARGO", "resultado": "TURNO_LARGO COMPLETADO", "segundos_pedidos": segundos,
            "segundos_medidos": round(reloj() - t0, 1)}


def segundos_turno(argumento: str) -> int:
    if not argumento:
        return SEGUNDOS_TURNO_LARGO
    if not re.fullmatch(r"\d{1,4}", argumento.strip()):
        raise ValueError(f"TURNO_LARGO admite un número de segundos: {argumento!r}")
    n = int(argumento)
    if not 1 <= n <= MAX_SEGUNDOS_TURNO:
        raise ValueError(f"TURNO_LARGO: entre 1 y {MAX_SEGUNDOS_TURNO} segundos")
    return n


def eco(argumento: str) -> dict:
    limpio = _RE_ECO.sub("", argumento or "")[:100]
    return {"orden": "ECO", "eco": f"ECO-OFA: {limpio}"}


def ayuda() -> dict:
    return {"orden": "AYUDA", "uso": "ORDEN: SALIDA | MARCADOR | TURNO_LARGO [segundos] | ECO <texto>"}


async def ejecutar(orden: str, argumento: str, *, marcador: dict, cancelado: Callable[[], bool]) -> dict:
    if orden == "SALIDA":
        return {"orden": "SALIDA", "resultados": await asyncio.to_thread(sondear_salida)}
    if orden == "MARCADOR":
        return {"orden": "MARCADOR", **marcador}
    if orden == "TURNO_LARGO":
        return await turno_largo(segundos_turno(argumento), cancelado)
    if orden == "ECO":
        return eco(argumento)
    return ayuda()
