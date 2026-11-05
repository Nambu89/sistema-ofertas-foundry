"""Construye el ZIP del hosted agent (plano, determinista) para create_version_from_code (remote_build).

Contenido: main.py, requirements.txt, preventa_hosted/, el núcleo SIN tocar con la estructura del repositorio
(sandbox/preventa_run.py, sandbox/preventa_api.py, sandbox/nucleo/*.py y esquemas/*.json, para que
nucleo.esquema encuentre esquemas/) y recursos/ con el catálogo, la tarifa y el generador y la plantilla
canónicos. El generador, la plantilla y la tarifa se comprueban contra el SHA-256 de manifiesto.json: si no
coinciden, NO se empaqueta (generador canónico sin modificar, LES-G-081). Escribe MANIFIESTO-HOSTED.json
dentro del ZIP con el SHA-256 de cada fichero.

I1.7 (decisión 1 del comercial, 13-10-2026): recursos/ lleva también la instantánea de precios
(sandbox/datos/precios_instantanea.json, copia byte a byte de catalogo/precios_instantanea.json). No se empaqueta si
falta, si no es igual a la del catálogo o a la huella de manifiesto.json, si su huella interna no cuadra, si una
plantilla del catálogo falta, trae otro filtro o no tiene un precio finito, o si tiene más de MAX_DIAS_INSTANTANEA días.

Uso (desde la raíz del repositorio):
  hosted/.venv/Scripts/python.exe hosted/empaquetar.py [--salida salidas/hosted/preventa-hosted.zip]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import math
import json
import os
import pathlib
import sys
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[1]
HOSTED = REPO / "hosted"
_WINDOWS = pathlib.Path("C:/Users/usuario/Proyectos")  # solo como último recurso, si existe
PROYECTOS = pathlib.Path((os.environ.get("PREVENTA_PROYECTOS") or "").strip() or pathlib.Path.home() / "Proyectos")
PROYECTOS = PROYECTOS if PROYECTOS.is_dir() or not _WINDOWS.is_dir() or (os.environ.get("PREVENTA_PROYECTOS") or "").strip() else _WINDOWS  # fijada: se respeta
FECHA_FIJA = (2026, 1, 1, 0, 0, 0)
CANONICOS = {   # nombre en recursos/ → (ruta de origen, nombre en manifiesto.json o None)
    "generar_estimacion.py": (PROYECTOS / "_templates" / "estimacion" / "generar_estimacion.py", "generar_estimacion.py"),
    "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx": (PROYECTOS / "_templates" / "estimacion" / "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx",
                                            "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx"),
    "rate-card.json": (REPO / "salidas" / "rate-card.json", "rate-card.json"),
    "catalogo_componentes.json": (REPO / "sandbox" / "datos" / "catalogo_componentes.json", None),
    "precios_instantanea.json": (REPO / "sandbox" / "datos" / "precios_instantanea.json", "precios_instantanea.json"),
}
INSTANTANEA_CATALOGO = REPO / "catalogo" / "precios_instantanea.json"
SCHEMA_INSTANTANEA = "preventa-precios-instantanea/1"
MAX_DIAS_INSTANTANEA = 31          # la puerta local rechaza una instantánea más vieja en la fecha del paquete
MARGEN_FUTURO = dt.timedelta(minutes=5)


class ErrorEmpaquetado(RuntimeError):
    pass


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def ficheros() -> dict[str, pathlib.Path]:
    """Ruta dentro del ZIP → ruta de origen. Sin __pycache__, .venv ni pruebas."""
    d: dict[str, pathlib.Path] = {"main.py": HOSTED / "main.py", "requirements.txt": HOSTED / "requirements.txt"}
    for p in sorted((HOSTED / "preventa_hosted").glob("*.py")):
        d[f"preventa_hosted/{p.name}"] = p
    for nombre in ("preventa_run.py", "preventa_api.py"):
        d[f"sandbox/{nombre}"] = REPO / "sandbox" / nombre
    for p in sorted((REPO / "sandbox" / "nucleo").glob("*.py")):
        d[f"sandbox/nucleo/{p.name}"] = p
    for p in sorted((REPO / "esquemas").glob("*.json")):
        d[f"esquemas/{p.name}"] = p
    for nombre, (origen, _) in CANONICOS.items():
        d[f"recursos/{nombre}"] = origen
    return d


def comprobar_canonicos(manifiesto: dict) -> list[str]:
    errores = []
    for nombre, (origen, clave) in CANONICOS.items():
        if not origen.is_file():
            errores.append(f"falta {origen}")
        elif clave is not None:
            esperado = (manifiesto.get("ficheros", {}).get(clave) or {}).get("sha256")
            real = sha256(origen.read_bytes())
            if esperado != real:
                errores.append(f"{nombre}: SHA-256 {real} distinto del de manifiesto.json ({esperado})")
    return errores


def hash_instantanea(obj: dict) -> str:
    """Huella interna de la instantánea: SHA-256 del JSON canónico (el de nucleo.hashes.json_canonico) sin «sha256»."""
    sin = {k: v for k, v in obj.items() if k != "sha256"}
    return sha256(json.dumps(sin, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8"))


def _rechazar_constante(c: str):
    raise ValueError(f"constante no admitida en JSON: {c}")


def precio_finito_no_negativo(x: object) -> bool:
    """Número JSON (no booleano) finito y ≥ 0. Revisión (2.ª pasada): un entero enorme no cabe en float y
    math.isfinite lanzaría OverflowError; se trata como no válido, nunca como excepción."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x)) and x >= 0
    except OverflowError:
        return False


def comprobar_instantanea(ruta: pathlib.Path, ahora: dt.datetime, catalogo: pathlib.Path | None = None) -> list[str]:
    """I1.7: errores de la instantánea de precios ([] si vale). Igual byte a byte a la del catálogo, forma mínima del
    contrato común, huella interna, las plantillas del catálogo («catalogo_id/plantilla_id») con su mismo filtro y un
    precio finito, y edad ≤ MAX_DIAS_INSTANTANEA."""
    catalogo = INSTANTANEA_CATALOGO if catalogo is None else catalogo
    if not ruta.is_file():
        return [f"falta la instantánea de precios {ruta} (se genera al desplegar)"]
    datos = ruta.read_bytes()
    errores = [] if catalogo.is_file() and catalogo.read_bytes() == datos else [
        f"{ruta.name}: no es igual byte a byte a {catalogo}"]
    try:
        obj = json.loads(datos.decode("utf-8"), parse_constant=_rechazar_constante)
    except (UnicodeDecodeError, ValueError) as exc:
        return errores + [f"{ruta.name}: JSON ilegible ({exc})"]
    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA_INSTANTANEA or obj.get("moneda") != "EUR":
        return errores + [f"{ruta.name}: no es una instantánea {SCHEMA_INSTANTANEA} en EUR"]
    if obj.get("sha256") != hash_instantanea(obj):
        errores.append(f"{ruta.name}: la huella interna no es la del contenido")
    plantillas = obj.get("plantillas")
    if not isinstance(plantillas, dict) or not plantillas:
        errores.append(f"{ruta.name}: sin plantillas")
        plantillas = {}
    errores += errores_cobertura(plantillas, CANONICOS["catalogo_componentes.json"][0])
    for pid, p in plantillas.items():
        precio = p.get("precio_unitario") if isinstance(p, dict) else None
        n = p.get("articulos_devueltos") if isinstance(p, dict) else None
        if not isinstance(p, dict) or isinstance(n, bool) or not isinstance(n, int) or n < 1:
            errores.append(f"{ruta.name}: la plantilla {pid} no trae artículos devueltos")
        elif not precio_finito_no_negativo(precio):
            errores.append(f"{ruta.name}: la plantilla {pid} no tiene un precio_unitario finito y no negativo")
    try:
        fecha = dt.datetime.fromisoformat(str(obj.get("fecha_consulta")).replace("Z", "+00:00"))
    except ValueError:
        return errores + [f"{ruta.name}: fecha_consulta no es una fecha ISO: {obj.get('fecha_consulta')!r}"]
    if fecha.tzinfo is None:
        return errores + [f"{ruta.name}: fecha_consulta sin zona horaria (tiene que ser UTC)"]
    if fecha > ahora + MARGEN_FUTURO:
        errores.append(f"{ruta.name}: fecha_consulta {fecha.isoformat()} posterior a ahora")
    elif (ahora.astimezone(dt.timezone.utc).date() - fecha.astimezone(dt.timezone.utc).date()).days > MAX_DIAS_INSTANTANEA:
        errores.append(f"{ruta.name}: instantánea del {fecha.date().isoformat()}, más de {MAX_DIAS_INSTANTANEA} días: "
                       "vuelve a descargarla (redespliegue)")
    return errores


def errores_cobertura(plantillas: dict, ruta_catalogo: pathlib.Path) -> list[str]:
    """Las claves de la instantánea son exactamente las plantillas del catálogo empaquetado, con el mismo filtro."""
    try:
        cat = json.loads(ruta_catalogo.read_text(encoding="utf-8"))
        esperadas = {f"{c['id']}/{p['id']}": p.get("filtro") for c in cat["componentes"]
                     for p in c.get("plantillas_precio") or []}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"no puedo leer las plantillas del catálogo {ruta_catalogo}: {exc}"]
    errores = [f"falta la plantilla {k} del catálogo" for k in sorted(set(esperadas) - set(plantillas))]
    errores += [f"plantilla {k} que no está en el catálogo" for k in sorted(set(plantillas) - set(esperadas))]
    errores += [f"{k}: el filtro no es el del catálogo" for k in sorted(set(esperadas) & set(plantillas))
                if not isinstance(plantillas[k], dict) or plantillas[k].get("filtro") != esperadas[k]]
    return errores


def construir(salida: pathlib.Path, ahora: dt.datetime | None = None) -> dict:
    manifiesto = json.loads((REPO / "manifiesto.json").read_text(encoding="utf-8"))
    errores = comprobar_canonicos(manifiesto)
    errores += comprobar_instantanea(CANONICOS["precios_instantanea.json"][0],
                                     ahora or dt.datetime.now(dt.timezone.utc))
    if errores:
        raise ErrorEmpaquetado("No empaqueto: " + "; ".join(errores))
    contenido = {ruta: origen.read_bytes() for ruta, origen in ficheros().items()}
    nombres_raros = [r for r in contenido if ".." in r or r.startswith("/") or "\\" in r]
    if nombres_raros:
        raise ErrorEmpaquetado(f"rutas no válidas en el ZIP: {nombres_raros}")
    resumen = {"schema": "preventa-hosted-manifiesto/1",
               "ficheros": {r: {"sha256": sha256(b), "bytes": len(b)} for r, b in sorted(contenido.items())}}
    contenido["MANIFIESTO-HOSTED.json"] = json.dumps(resumen, ensure_ascii=False, indent=1).encode("utf-8")
    salida.parent.mkdir(parents=True, exist_ok=True)
    temporal = salida.with_suffix(".tmp")
    with zipfile.ZipFile(temporal, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for ruta in sorted(contenido):
            info = zipfile.ZipInfo(ruta, date_time=FECHA_FIJA)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, contenido[ruta])
    temporal.replace(salida)
    datos = salida.read_bytes()
    return {"zip": str(salida), "sha256": sha256(datos), "bytes": len(datos), "ficheros": len(contenido)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--salida", default=str(REPO / "salidas" / "hosted" / "preventa-hosted.zip"))
    a = ap.parse_args(argv)
    try:
        r = construir(pathlib.Path(a.salida))
    except ErrorEmpaquetado as exc:
        print(f"FALLO: {exc}")
        return 1
    print(f"ZIP: {r['zip']} · {r['ficheros']} ficheros · {r['bytes']} B · SHA-256 {r['sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
