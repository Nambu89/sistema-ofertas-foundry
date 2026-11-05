"""Descarga del sandbox los ficheros de un contenedor o la última cita de una conversación (papel E).

Uso:
    python descargar.py contenedor <container_id> [--fichero FILE_ID ...] [--destino CARPETA]
    python descargar.py conversacion <conversation_id> [--todas] [--destino CARPETA]
    python descargar.py respuesta <response_id> [--todas] [--destino CARPETA]

Usa el token del comercial (az con --tenant explícito, solo en memoria; nunca se imprime ni se
guarda). Cada nombre que llega del sandbox se sanea con lib.auditoria y el destino debe quedar
dentro de la carpeta indicada. Nunca sobrescribe: si existe un fichero distinto, añade un sufijo.
Los contenedores caducan a los 20 minutos de inactividad: hay que descargar en el momento.
Códigos de salida: 0 descargado; 1 nada que descargar o fallo de la API; 2 argumentos.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import pathlib
import sys
from typing import Any

RAIZ = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from lib.auditoria import NombreNoValido, ruta_contenida  # noqa: E402

DESTINO_POR_DEFECTO = RAIZ / "pruebas" / "I1" / "E2E" / "descargas"


def citas(items: list[dict]) -> list[dict]:
    """container_file_citation de una lista de items de salida, en orden de aparición."""
    salida = []
    for item in items or []:
        for c in item.get("content", []) or []:
            for a in c.get("annotations", []) or []:
                if a.get("type") == "container_file_citation":
                    salida.append({k: a.get(k) for k in ("container_id", "file_id", "filename")})
    return salida


def ultimas_citas(items_desc: list[dict], todas: bool) -> list[dict]:
    """Del item más reciente que tenga citas: la última cita o, con `todas`, todas las de ese item."""
    for item in items_desc:
        cs = citas([item])
        if cs:
            return cs if todas else cs[-1:]
    return []


def destino_libre(carpeta: pathlib.Path, nombre: str, datos: bytes) -> tuple[pathlib.Path, bool]:
    """(ruta, ya_existía_idéntico). Nunca devuelve una ruta que pise un fichero distinto."""
    p = ruta_contenida(carpeta, nombre)
    if p.exists():
        if p.read_bytes() == datos:
            return p, True
        sello = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        p = ruta_contenida(carpeta, f"{p.stem}-{sello}{p.suffix}")
    return p, False


def guardar(carpeta: pathlib.Path, nombre: str, datos: bytes) -> pathlib.Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    p, igual = destino_libre(carpeta, nombre, datos)
    if not igual:
        p.write_bytes(datos)
    print(f"{'YA EXISTÍA' if igual else 'DESCARGADO'}: {p} · {len(datos)} bytes · "
          f"SHA-256 {hashlib.sha256(datos).hexdigest()}")
    if p.name.endswith("-Paquete.zip"):
        print(f"  siguiente paso: python verificar_paquete.py \"{p}\" --transcripcion <ruta de la transcripción>")
    return p


def contenido(cli: Any, container_id: str, file_id: str) -> bytes:
    return cli._openai("GET", f"containers/{container_id}/files/{file_id}/content", crudo=True)


def main(argv: list[str] | None = None, cliente: Any = None) -> int:
    ap = argparse.ArgumentParser(description="Descarga ficheros del sandbox de preventa-coordinador.")
    ap.add_argument("origen", choices=("contenedor", "conversacion", "respuesta"))
    ap.add_argument("ident", help="container_id, conversation_id o response_id")
    ap.add_argument("--fichero", action="append", default=[], help="file_id concreto (solo contenedor)")
    ap.add_argument("--todas", action="store_true", help="todas las citas del último mensaje con citas")
    ap.add_argument("--destino", default=str(DESTINO_POR_DEFECTO))
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    carpeta = pathlib.Path(a.destino)
    if cliente is None:
        from lib.foundry import ClienteFoundry
        cliente = ClienteFoundry()
    try:
        if a.origen == "contenedor":
            ficheros = cliente.listar_ficheros_contenedor(a.ident)
            if a.fichero:
                ficheros = [f for f in ficheros if f.get("id") in set(a.fichero)]
            objetivos = [{"container_id": a.ident, "file_id": f.get("id"),
                          "filename": pathlib.PurePosixPath(str(f.get("path") or f.get("id"))).name}
                         for f in ficheros]
        elif a.origen == "conversacion":
            items = cliente._listar_openai(f"conversations/{a.ident}/items?order=desc")
            objetivos = ultimas_citas(items, a.todas)
        else:
            objetivos = citas(cliente.obtener_respuesta(a.ident).get("output", []))
            objetivos = objetivos if a.todas else objetivos[-1:]
        if not objetivos:
            print(f"NADA QUE DESCARGAR: {a.origen} {a.ident} sin ficheros ni citas de fichero")
            return 1
        for o in objetivos:
            guardar(carpeta, o.get("filename") or o.get("file_id"), contenido(cliente, o["container_id"], o["file_id"]))
    except NombreNoValido as e:
        print(f"FALLO rc=1: nombre de fichero no admitido: {e}")
        return 1
    except Exception as e:  # noqa: BLE001 - fail loudly con el error literal (sin token)
        texto = str(e)
        if " 404" in texto or "404:" in texto:
            texto += " (si es un contenedor, probablemente ha caducado: 20 min de inactividad)"
        print(f"FALLO rc=1: {type(e).__name__}: {texto[:800]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
