"""Para el comercial: bajar (o subir) ficheros de la carpeta persistente de una sesión del hosted agent.

Usa la API de ficheros de sesión de azure-ai-projects 2.8.0 (list_session_files, download_session_file y
upload_session_file) con TU identidad de Azure CLI y el tenant explícito (LES-G-052). No imprime tokens.

  hosted/.venv/Scripts/python.exe hosted/descargar_sesion.py listar --sesion <id> [--ruta preventa/trabajo/salida]
  hosted/.venv/Scripts/python.exe hosted/descargar_sesion.py descargar --sesion <id> --ruta preventa/trabajo/salida/<ZIP>
  hosted/.venv/Scripts/python.exe hosted/descargar_sesion.py subir --sesion <id> --fichero <local> [--ruta preventa/datos/<nombre>]

El id de sesión lo da el propio turno (línea PAQUETE) o la respuesta del Responses protocol (`agent_session_id`).
La ruta es relativa a la carpeta persistente de la sesión ($HOME). NO VERIFICADO hasta desplegar: que la API
resuelva las rutas desde $HOME (Learn lo dice para las subidas; el ejemplo de C# usa /mnt/agent/session).
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import sys

# Tenant y proyecto: de config/entorno.local.json (o PREVENTA_ENTORNO); sin él, falla en alto al importar.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib.config import cargar as _cargar_entorno  # noqa: E402

_ENTORNO = _cargar_entorno()
TENANT = _ENTORNO["tenant_id"]
PROYECTO = _ENTORNO["endpoints"]["proyecto"]
AGENTE = "preventa-prueba-hosted"
_RUTA = re.compile(r"^[A-Za-z0-9._ /-]{1,300}$")


def cliente(proyecto: str, tenant: str):
    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential
    return AIProjectClient(endpoint=proyecto, credential=AzureCliCredential(tenant_id=tenant))


def _ruta_valida(ruta: str) -> str:
    if not _RUTA.fullmatch(ruta) or ".." in ruta.split("/") or ruta.startswith("/"):
        raise SystemExit(f"Ruta no válida: {ruta!r} (relativa, sin «..»)")
    return ruta


def destino_libre(carpeta: pathlib.Path, nombre: str) -> pathlib.Path:
    """No pisa nada: añade -1, -2… si ya existe (la apertura con «xb» lo garantiza)."""
    base, ext = pathlib.Path(nombre).stem, pathlib.Path(nombre).suffix
    for n in range(0, 1000):
        p = carpeta / (nombre if n == 0 else f"{base}-{n}{ext}")
        if not p.exists():
            return p
    raise SystemExit(f"Demasiadas copias de {nombre} en {carpeta}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ficheros de sesión del hosted agent de preventa")
    ap.add_argument("accion", choices=("listar", "descargar", "subir"))
    ap.add_argument("--sesion", required=True)
    ap.add_argument("--ruta", default=None)
    ap.add_argument("--fichero", default=None)
    ap.add_argument("--destino", default="salidas/hosted/descargas")
    ap.add_argument("--agente", default=AGENTE)
    ap.add_argument("--proyecto", default=PROYECTO)
    ap.add_argument("--tenant", default=TENANT)
    a = ap.parse_args(argv)
    c = cliente(a.proyecto, a.tenant)
    if a.accion == "listar":
        for e in c.agents.list_session_files(a.agente, a.sesion, path=_ruta_valida(a.ruta or ".")):
            print(f"{'DIR ' if getattr(e, 'is_directory', False) else '    '}{e.name}  {getattr(e, 'size', '')}")
        return 0
    if a.accion == "descargar":
        if not a.ruta:
            raise SystemExit("descargar necesita --ruta")
        datos = b"".join(c.agents.download_session_file(a.agente, a.sesion, path=_ruta_valida(a.ruta)))
        carpeta = pathlib.Path(a.destino)
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = destino_libre(carpeta, pathlib.PurePosixPath(a.ruta).name)
        with open(destino, "xb") as f:
            f.write(datos)
        print(f"DESCARGADO: {destino} · {len(datos)} bytes · SHA-256 {hashlib.sha256(datos).hexdigest()}")
        print("Antes de enviar nada: verificar_paquete.py sobre este ZIP en tu equipo.")
        return 0
    if not a.fichero:
        raise SystemExit("subir necesita --fichero")
    local = pathlib.Path(a.fichero)
    ruta = _ruta_valida(a.ruta or f"preventa/datos/{local.name}")
    r = c.agents.upload_session_file(a.agente, a.sesion, local.read_bytes(), path=ruta)
    print(f"SUBIDO: {ruta} · {getattr(r, 'bytes_written', '?')} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
