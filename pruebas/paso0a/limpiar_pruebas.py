"""Borra SOLO los agentes desechables del paso 0a (prefijo ofa-prueba-), con la guarda de lib/foundry.py.

Uso (desde la raíz del repositorio):
  .venv/Scripts/python.exe pruebas/paso0a/limpiar_pruebas.py                 # lista lo que borraría
  .venv/Scripts/python.exe pruebas/paso0a/limpiar_pruebas.py --confirmar     # borra
  .venv/Scripts/python.exe pruebas/paso0a/limpiar_pruebas.py --confirmar --forzar   # y sus sesiones activas

Cada nombre pasa por `comprobar_nombre_borrable` (protegidos, forma, prefijo ofa- y, sin permitir_sistema,
prefijo ofa-prueba-) antes de cualquier DELETE; los agentes del sistema y los protegidos no se tocan nunca.
La conexión ofa-prueba-marcador, si existe, la borra Fernando (el modo automático no gestiona conexiones).
Código de salida: 0 bien · 1 algún borrado falló · 2 uso · 5 autenticación.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from lib import azure_auth  # noqa: E402
from lib.foundry import ClienteFoundry, ErrorFoundry, OperacionNoPermitida, comprobar_nombre_borrable  # noqa: E402
from lib.redaccion import redactar  # noqa: E402

PREFIJO = "ofa-prueba-"


def seleccionar(nombres: list, cfg: dict) -> tuple[list[str], list[tuple[str, str]]]:
    """(borrables, ignorados con motivo). Solo es borrable lo que empieza por ofa-prueba- y pasa la guarda."""
    borrables, ignorados = [], []
    for n in nombres:
        if not isinstance(n, str) or not n.startswith(PREFIJO):
            ignorados.append((str(n), "no es un agente ofa-prueba-"))
            continue
        try:
            comprobar_nombre_borrable(n, cfg)
        except OperacionNoPermitida as e:
            ignorados.append((n, str(e)))
            continue
        borrables.append(n)
    return sorted(set(borrables)), ignorados


def instrucciones_conexion(cfg: dict) -> str:
    return ("Si existe la conexión ofa-prueba-marcador, Fernando la borra: az rest --method delete --url "
            f"\"https://management.azure.com/subscriptions/{cfg['suscripcion_id']}/resourceGroups/"
            f"{cfg['grupo_recursos']}/providers/Microsoft.CognitiveServices/accounts/{cfg['recurso']}/projects/"
            f"{cfg['proyecto']}/connections/ofa-prueba-marcador?api-version={cfg['api_versions']['arm_conexiones']}\"")


def main(argv: list[str] | None = None, cliente: ClienteFoundry | None = None) -> int:
    """Punto de entrada: autenticación → 5; cualquier otro fallo imprevisto → 2 (nunca el 1 de «borrado falló»)."""
    try:
        return _main(argv, cliente)
    except azure_auth.ErrorAutenticacion as e:
        print(f"PARADA rc=5 (autenticación): {redactar(str(e))}")
        return 5
    except Exception as e:   # noqa: BLE001 — ErrorConfig, ErrorAz o un fallo del propio script
        print(f"FALLO DE USO rc=2: {type(e).__name__}: {redactar(str(e))[:600]}")
        return 2


def _main(argv: list[str] | None, cliente: ClienteFoundry | None) -> int:
    ap = argparse.ArgumentParser(description="Borra los agentes ofa-prueba- del proyecto")
    ap.add_argument("--confirmar", action="store_true", help="sin esta opción solo lista")
    ap.add_argument("--forzar", action="store_true", help="force=true: borra también las sesiones activas")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    try:
        cli = cliente or ClienteFoundry()
        nombres = [ag.get("name") for ag in cli.listar_agentes()]
    except ErrorFoundry as e:
        print(f"FALLO: no se pudo listar los agentes: {redactar(str(e))[:600]}")
        return 1
    borrables, ignorados = seleccionar(nombres, cli.cfg)
    print(f"Agentes en el proyecto: {len(nombres)} · borrables (ofa-prueba-): {borrables or 'ninguno'}")
    for n, motivo in ignorados:
        if n.startswith(PREFIJO):
            print(f"  NO se borra {n}: {motivo}")
    if not a.confirmar:
        print("Sin --confirmar: no se ha borrado nada.\n" + instrucciones_conexion(cli.cfg))
        return 0
    fallos = 0
    for n in borrables:
        try:
            cli.borrar_agente(n, forzar=a.forzar)
            print(f"  borrado {n}")
        except (ErrorFoundry, OperacionNoPermitida) as e:
            fallos += 1
            print(f"  FALLO al borrar {n}: {redactar(str(e))[:600]}")
    print(instrucciones_conexion(cli.cfg))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
