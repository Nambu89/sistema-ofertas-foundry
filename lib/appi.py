"""Consultas KQL a Application Insights a través de Azure Resource Manager, con la respuesta en UTF-8.

Por qué ARM: la vía v1 (`https://api.applicationinsights.io`) pide un token de esa audiencia, y en el tenant
de Devoteam eso exige un MFA aparte (VERIF-6). Por ARM basta el token de `https://management.azure.com`, el
mismo que ya usa el despliegue.

Fuente de la ruta y la api-version (leída sin autenticar el 08-10-2026, detalle en
`observabilidad/learn/arm_appinsights_query_2018-04-20.md`): especificación oficial
`Azure/azure-rest-api-specs`, `specification/applicationinsights/data-plane/Insights/preview/2018-04-20/swagger.json`,
host `management.azure.com`, operación `Query_Execute`:
    POST /subscriptions/{sub}/resourcegroups/{rg}/providers/Microsoft.Insights/components/{app}/query?api-version=2018-04-20
Learn solo renderiza la vista v1 de esa API. NO VERIFICADO en real todavía: se prueba en la siguiente tanda.

El token vive solo en memoria (lib.azure_auth); nunca se imprime ni se guarda. Los bytes se decodifican como
UTF-8 aunque la cabecera diga otra cosa (en Windows, `az` devolvía cp1252: LES-G-090.8).

Uso (siguiente tanda, con sesión de az):
    python -m lib.appi "requests | take 1" --timespan PT1H --salida pruebas/I12/F4/salidas/appi_arm.json
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

ARM = "https://management.azure.com"
API_VERSION = "2018-04-20"
COMPONENTE_POR_DEFECTO = "appi-preventa-ejemplo"
_NOMBRE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._()-]{0,259}")  # sin «/», «?», «#» ni «..»: nada sale de la ruta
_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_TIMESPAN = re.compile(r"P(?=\d|T\d)(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?|\S+/\S+")
_REINTENTABLES = (429, 502, 503, 504)


class ErrorAppi(RuntimeError):
    """La consulta no devolvió tablas legibles. `estado` es el HTTP (0 si no hubo respuesta)."""

    def __init__(self, mensaje: str, estado: int = 0):
        super().__init__(mensaje)
        self.estado = estado


def url_consulta(suscripcion: str, grupo: str, componente: str) -> str:
    """URL ARM de Query_Execute. Valida cada segmento: un nombre con «/» o «?» no puede cambiar la ruta."""
    if not _GUID.fullmatch(suscripcion or ""):
        raise ErrorAppi(f"suscripción no válida: {suscripcion!r}")
    for valor, que in ((grupo, "grupo de recursos"), (componente, "componente")):
        if not _NOMBRE.fullmatch(valor or "") or ".." in valor:
            raise ErrorAppi(f"{que} no válido: {valor!r}")
    return (f"{ARM}/subscriptions/{suscripcion}/resourcegroups/{grupo}/providers/Microsoft.Insights"
            f"/components/{componente}/query?api-version={API_VERSION}")


def cuerpo(kql: str, timespan: str | None = None) -> dict:
    """Cuerpo `queryBody` de la especificación: `query` obligatorio y `timespan` ISO 8601 opcional."""
    if not isinstance(kql, str) or not kql.strip():
        raise ErrorAppi("la consulta KQL está vacía")
    c: dict[str, Any] = {"query": kql}
    if timespan is not None:
        if not _TIMESPAN.fullmatch(timespan):
            raise ErrorAppi(f"timespan no es un periodo ISO 8601: {timespan!r} (por ejemplo PT1H, P1D)")
        c["timespan"] = timespan
    return c


def decodificar(estado: int, contenido: bytes) -> dict:
    """Bytes de la respuesta → dict con `tables`. Falla en alto si no es UTF-8, no es JSON o trae `error`."""
    from lib import evidencia
    try:
        texto = contenido.decode("utf-8-sig")  # estricto: un byte inválido es un fallo, no un U+FFFD
    except UnicodeDecodeError as e:
        raise ErrorAppi(f"la respuesta no es UTF-8 (byte {e.start})", estado) from None
    if estado != 200:
        raise ErrorAppi(f"HTTP {estado}: {evidencia.enmascarar_texto(texto)[-1500:]}", estado)
    try:
        datos = json.loads(texto)
    except ValueError:
        raise ErrorAppi("la respuesta 200 no es JSON", estado) from None
    if not isinstance(datos, dict) or not isinstance(datos.get("tables"), list):
        raise ErrorAppi("la respuesta 200 no trae «tables»", estado)
    if datos.get("error"):  # resultado parcial: no se da por bueno en silencio
        raise ErrorAppi(f"respuesta parcial: {evidencia.enmascarar_texto(json.dumps(datos['error'], ensure_ascii=False))[:1500]}", estado)
    return datos


def filas(datos: dict, tabla: int = 0) -> list[dict]:
    """Filas de una tabla como dicts {columna: valor}. Una fila con otra anchura es un fallo, no se recorta."""
    try:
        t = datos["tables"][tabla]
        cols = [c["name"] for c in t["columns"]]
    except (KeyError, IndexError, TypeError):
        raise ErrorAppi(f"no hay tabla {tabla} con columnas") from None
    out = []
    for i, fila in enumerate(t.get("rows", [])):
        if len(fila) != len(cols):
            raise ErrorAppi(f"fila {i}: {len(fila)} valores para {len(cols)} columnas")
        out.append(dict(zip(cols, fila)))
    return out


def consultar(kql: str, timespan: str | None = None, *, cfg: dict | None = None,
              componente: str | None = None, sesion=None, token: str | None = None,
              timeout: float = 180, dormir=time.sleep) -> dict:
    """POST de la consulta por ARM. Devuelve el dict con `tables` (ver `filas`).

    Reintenta una sola vez si no hubo respuesta (red, DNS, tiempo agotado) o si ARM responde 429/502/503/504,
    esperando `Retry-After` con un tope de 30 s. Lo demás falla en alto con ErrorAppi; un 401/403 trae el
    remedio. `sesion` y `token` solo existen para las pruebas sin red.
    """
    import requests
    if cfg is None:
        from lib.config import cargar
        cfg = cargar()
    comp = componente or cfg.get("appinsights_componente") or COMPONENTE_POR_DEFECTO
    url = url_consulta(cfg["suscripcion_id"], cfg["grupo_recursos"], comp)
    datos = cuerpo(kql, timespan)
    if token is None:
        from lib.azure_auth import AUD_ARM, obtener_token
        token = obtener_token(AUD_ARM, cfg["tenant_id"])  # solo en memoria; nunca se imprime
    http = sesion or requests
    cabeceras = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8",
                 "Accept": "application/json"}
    for intento in (1, 2):
        try:
            r = http.post(url, data=json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                          headers=cabeceras, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            if intento == 2:
                raise ErrorAppi(f"sin respuesta de ARM tras 2 intentos: {type(e).__name__}") from None
            dormir(5)
            continue
        if r.status_code in _REINTENTABLES and intento == 1:
            try:
                espera = min(30.0, max(1.0, float(r.headers.get("Retry-After", 5))))
            except (TypeError, ValueError):
                espera = 5.0
            dormir(espera)
            continue
        if r.status_code in (401, 403):
            raise ErrorAppi(f"HTTP {r.status_code}: sin permiso o sesión caducada. Sesión: "
                            f"az login --tenant {cfg['tenant_id']}; permiso: lector del componente {comp}.",
                            r.status_code)
        return decodificar(r.status_code, r.content)
    raise ErrorAppi("sin respuesta válida de ARM")  # no se alcanza: el bucle siempre devuelve o lanza


def main(argv: list[str] | None = None) -> int:
    """CLI: consulta, imprime el número de filas por tabla y guarda la respuesta enmascarada si se pide."""
    import argparse
    import pathlib
    import sys
    from lib import evidencia
    ap = argparse.ArgumentParser(description="Consulta KQL a Application Insights por ARM (api-version "
                                             f"{API_VERSION}).")
    ap.add_argument("kql")
    ap.add_argument("--timespan", default=None, help="ISO 8601, por ejemplo PT1H o P1D")
    ap.add_argument("--componente", default=None)
    ap.add_argument("--salida", type=pathlib.Path, default=None)
    a = ap.parse_args(argv)
    try:
        datos = consultar(a.kql, a.timespan, componente=a.componente)
    except ErrorAppi as e:
        print(f"FALLO ({e.estado}): {evidencia.enmascarar_texto(str(e))}", file=sys.stderr)
        return 1
    for i, t in enumerate(datos["tables"]):
        print(f"tabla {i} {t.get('name')}: {len(t.get('rows', []))} filas")
    if a.salida:
        evidencia.guardar_enmascarado(a.salida, {"api_version": API_VERSION, "kql": a.kql,
                                                 "timespan": a.timespan, "respuesta": datos})
        print(f"evidencia: {a.salida}")
    return 0


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
