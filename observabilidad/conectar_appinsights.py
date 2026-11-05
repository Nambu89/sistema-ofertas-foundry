"""Conecta el Application Insights de I0 al proyecto proyecto-ejemplo como recurso de trazas.

Lee la cadena de conexión del componente por ARM y la pasa directamente al PUT de la conexión, sin
imprimirla ni guardarla. Las evidencias se guardan con las credenciales omitidas. Uso:
    python -m observabilidad.conectar_appinsights --comprobar   (solo GET)
    python -m observabilidad.conectar_appinsights --crear       (PUT y después GET)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

from lib import evidencia
from lib.foundry import ClienteFoundry, ErrorFoundry, OperacionNoPermitida

RAIZ = pathlib.Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "pruebas" / "I0" / "B4"
NOMBRE_CONEXION = "appi-preventa-ejemplo"
API_COMPONENTE = "2020-02-02"


def id_componente(c: ClienteFoundry) -> str:
    """Id ARM del Application Insights creado en B4."""
    return (f"/subscriptions/{c.cfg['suscripcion_id']}/resourceGroups/{c.cfg['grupo_recursos']}"
            f"/providers/microsoft.insights/components/{NOMBRE_CONEXION}")


def _quitar_literales(obj, secretos: list[str]):
    """Sustituye cualquier aparición literal de los secretos conocidos."""
    if isinstance(obj, dict):
        return {k: _quitar_literales(v, secretos) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_quitar_literales(x, secretos) for x in obj]
    if isinstance(obj, str):
        for s in secretos:
            if s:
                obj = obj.replace(s, "<OMITIDO>")
    return obj


def sanear(obj, secretos: list[str]):
    """Omite los literales conocidos y después todo lo que `lib.evidencia` reconoce como secreto."""
    return evidencia.limpiar(_quitar_literales(obj, secretos))


def guardar(nombre: str, datos, secretos: list[str]) -> None:
    """Escribe la evidencia saneada en pruebas/I0/B4 (con la red de lib.evidencia)."""
    evidencia.guardar_enmascarado(SALIDA / nombre, sanear(datos, secretos))


def resumen_conexiones(c: ClienteFoundry) -> list[dict]:
    """Lista las conexiones del proyecto con los campos que importan para las trazas."""
    r = c._arm("GET", f"{c.id_arm_proyecto}/connections", c.cfg["api_versions"]["arm_conexiones"])
    return [{"name": x["name"], "category": x["properties"].get("category"),
             "authType": x["properties"].get("authType"),
             "isDefault": x["properties"].get("isDefault"),
             "target": x["properties"].get("target"), "error": x["properties"].get("error")}
            for x in r.get("value", [])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--comprobar", action="store_true")
    g.add_argument("--crear", action="store_true")
    a = ap.parse_args()
    c = ClienteFoundry()
    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    secretos: list[str] = []
    if a.crear:
        comp = c._arm("GET", id_componente(c), API_COMPONENTE)
        cadena = comp["properties"]["ConnectionString"]
        secretos = [cadena, comp["properties"].get("InstrumentationKey", "")]
        props = {"authType": "ApiKey", "category": "AppInsights", "target": comp["id"],
                 "isSharedToAll": False, "credentials": {"key": cadena},
                 "metadata": {"ApiType": "Azure", "ResourceId": comp["id"],
                              "displayName": NOMBRE_CONEXION}}
        try:
            r = c.put_conexion(NOMBRE_CONEXION, props)
            guardar(f"put_conexion_{sello}.json", {"estado": "ok", "respuesta": r}, secretos)
        except (ErrorFoundry, OperacionNoPermitida) as e:
            guardar(f"put_conexion_{sello}.json",
                    {"estado": "error", "http": getattr(e, "estado", None), "error": str(e),
                     "intentos_anotados": [vars(i) for i in c.registro]}, secretos)
            print(sanear(str(e), secretos), file=sys.stderr)
            return 2
    actual = c.obtener_conexion(NOMBRE_CONEXION)
    lista = resumen_conexiones(c)
    guardar(f"get_conexion_{sello}.json", {"conexion": actual, "conexiones_proyecto": lista},
            secretos)
    print(json.dumps(sanear({"conexion_existe": actual is not None, "conexiones": lista},
                            secretos), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
