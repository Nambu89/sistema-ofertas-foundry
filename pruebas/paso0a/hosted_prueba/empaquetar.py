"""Construye el ZIP `bundled` del hosted agent ofa-prueba-hosted (P4 del paso 0a).

Forma de Learn (deploy-hosted-agent-code, ms.date 2026-09-29): ZIP plano con main.py, requirements.txt y
packages/ con los módulos YA EXTRAÍDOS para Linux x86_64, construidos con
  pip install -r requirements.txt --target packages --platform manylinux2014_x86_64 --python-version 3.13
      --implementation cp --only-binary=:all:
Aquí se parte en tres fases para que ningún comando pase de 90 s (cada fase se puede repetir y continúa):
  1. descargar: pip download de las ruedas a _build/ruedas (la caché de pip hace rápidas las repeticiones);
  2. instalar: pip install --no-index desde esas ruedas a _build/packages;
  3. zip: ZIP determinista + MANIFIESTO-HOSTED.json con el SHA-256 de cada fichero, de cada rueda y la lista
     exacta de versiones instaladas (bloqueo). Rechaza binarios de Windows (.pyd, .dll, .exe) y .so que no sean ELF.

Uso (desde la raíz del repositorio):
  .venv/Scripts/python.exe pruebas/paso0a/hosted_prueba/empaquetar.py [--fase descargar|instalar|zip|todo]
Salida: pruebas/paso0a/_salidas/ofa-prueba-hosted.zip y su ficha .sha256.json. Código 0 si el ZIP queda listo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

AQUI = pathlib.Path(__file__).resolve().parent
BUILD = AQUI / "_build"
RUEDAS = BUILD / "ruedas"
PAQUETES = BUILD / "packages"
SALIDAS = AQUI.parent / "_salidas"
ZIP_POR_DEFECTO = SALIDAS / "ofa-prueba-hosted.zip"
FECHA_FIJA = (2026, 1, 1, 0, 0, 0)
PLATAFORMAS = ("manylinux2014_x86_64", "manylinux_2_28_x86_64")
TIMEOUT_PIP_S = 80
MAX_ZIP_BYTES = 250 * 1024 * 1024
EXTENSIONES_WINDOWS = (".pyd", ".dll", ".exe")
_RE_RUEDA = re.compile(r"^(?P<nombre>[A-Za-z0-9_.]+)-(?P<version>[A-Za-z0-9_.!+]+)-.+\.whl$")


class ErrorEmpaquetado(RuntimeError):
    pass


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def huella_fichero(ruta: pathlib.Path) -> str:
    return sha256(ruta.read_bytes())


def argumentos_plataforma() -> list[str]:
    args: list[str] = []
    for p in PLATAFORMAS:
        args += ["--platform", p]
    return args + ["--python-version", "3.13", "--implementation", "cp", "--only-binary=:all:"]


def bloqueo_desde_ruedas(nombres: list[str]) -> list[str]:
    """«nombre==versión» de cada rueda (normalizado como en PEP 503), ordenado. Falla con nombres raros."""
    bloqueo = []
    for n in nombres:
        m = _RE_RUEDA.match(n)
        if not m:
            raise ErrorEmpaquetado(f"Nombre de rueda no reconocido: {n}")
        bloqueo.append(f"{re.sub(r'[-_.]+', '-', m['nombre']).lower()}=={m['version']}")
    return sorted(set(bloqueo))


def contenido_zip(raiz_hosted: pathlib.Path, paquetes: pathlib.Path) -> dict[str, bytes]:
    """Ruta dentro del ZIP → bytes. Sin __pycache__, .pyc, ni el propio _build ni pruebas."""
    c: dict[str, bytes] = {"main.py": (raiz_hosted / "main.py").read_bytes(),
                           "requirements.txt": (raiz_hosted / "requirements.txt").read_bytes()}
    for p in sorted((raiz_hosted / "ofa_prueba_hosted").glob("*.py")):
        c[f"ofa_prueba_hosted/{p.name}"] = p.read_bytes()
    if paquetes.is_dir():
        for p in sorted(paquetes.rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            rel = p.relative_to(paquetes).as_posix()
            if rel.startswith("bin/"):   # lanzadores de consola: no hacen falta en el agente
                continue
            c[f"packages/{rel}"] = p.read_bytes()
    return c


def comprobar_contenido(contenido: dict[str, bytes]) -> list[str]:
    """Errores que harían fallar el agente en Linux o que delatan un ZIP mal formado."""
    errores = []
    if "main.py" not in contenido:
        errores.append("falta main.py en la raíz (el ZIP debe ser plano)")
    if not any(r.startswith("packages/azure/ai/agentserver/responses/") for r in contenido):
        errores.append("packages/ no contiene azure.ai.agentserver.responses (falta la fase instalar)")
    for ruta, datos in contenido.items():
        if ".." in ruta.split("/") or ruta.startswith("/") or "\\" in ruta:
            errores.append(f"ruta no válida: {ruta}")
        if ruta.lower().endswith(EXTENSIONES_WINDOWS):
            errores.append(f"binario de Windows en el ZIP: {ruta}")
        if ruta.lower().endswith(".whl"):
            errores.append(f"rueda sin extraer en el ZIP: {ruta}")
        if re.search(r"\.so(\.[0-9]+)*$", ruta) and not datos.startswith(b"\x7fELF"):
            errores.append(f"biblioteca .so que no es ELF de Linux: {ruta}")
    return errores


def escribir_zip(contenido: dict[str, bytes], salida: pathlib.Path) -> dict:
    """ZIP determinista (orden, fechas y permisos fijos). Devuelve SHA-256, bytes y número de ficheros."""
    salida.parent.mkdir(parents=True, exist_ok=True)
    tmp = salida.with_name(salida.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for ruta in sorted(contenido):
            info = zipfile.ZipInfo(ruta, date_time=FECHA_FIJA)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, contenido[ruta])
    tmp.replace(salida)
    datos = salida.read_bytes()
    if len(datos) > MAX_ZIP_BYTES:
        raise ErrorEmpaquetado(f"El ZIP ocupa {len(datos)} B, por encima del límite de 250 MB de Learn")
    return {"sha256": sha256(datos), "bytes": len(datos), "ficheros": len(contenido)}


def comprobar_zip(ruta: pathlib.Path) -> str:
    """El ZIP casa con su MANIFIESTO-HOSTED.json y tiene main.py en la raíz. Devuelve su SHA-256."""
    with zipfile.ZipFile(ruta) as z:
        nombres = set(z.namelist())
        if "main.py" not in nombres or "MANIFIESTO-HOSTED.json" not in nombres:
            raise ErrorEmpaquetado("el ZIP no tiene main.py o MANIFIESTO-HOSTED.json en la raíz")
        man = json.loads(z.read("MANIFIESTO-HOSTED.json"))
        for nombre, meta in man["ficheros"].items():
            if nombre not in nombres or sha256(z.read(nombre)) != meta["sha256"]:
                raise ErrorEmpaquetado(f"{nombre} no casa con MANIFIESTO-HOSTED.json")
        sobran = nombres - set(man["ficheros"]) - {"MANIFIESTO-HOSTED.json"}
        if sobran:
            raise ErrorEmpaquetado(f"ficheros fuera del manifiesto: {sorted(sobran)[:5]}")
    return huella_fichero(ruta)


def _pip(args: list[str]) -> None:
    cmd = [sys.executable, "-m", "pip", *args]
    print("$ " + " ".join(cmd), flush=True)
    try:
        r = subprocess.run(cmd, timeout=TIMEOUT_PIP_S)
    except subprocess.TimeoutExpired:
        raise ErrorEmpaquetado(f"pip no terminó en {TIMEOUT_PIP_S} s; vuelve a lanzar la misma fase "
                               "(lo descargado se conserva)") from None
    if r.returncode != 0:
        raise ErrorEmpaquetado(f"pip terminó con código {r.returncode}")


def _marca(ruta: pathlib.Path) -> str | None:
    try:
        return ruta.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def fase_descargar() -> None:
    req = AQUI / "requirements.txt"
    huella = huella_fichero(req)
    marca = RUEDAS / ".descarga-ok"
    if _marca(marca) == huella and any(RUEDAS.glob("*.whl")):
        print("descargar: ya hecho para este requirements.txt")
        return
    RUEDAS.mkdir(parents=True, exist_ok=True)
    _pip(["download", "-r", str(req), "-d", str(RUEDAS), *argumentos_plataforma()])
    marca.write_text(huella, encoding="utf-8")


def fase_instalar() -> None:
    req = AQUI / "requirements.txt"
    ruedas = sorted(p.name for p in RUEDAS.glob("*.whl"))
    if not ruedas:
        raise ErrorEmpaquetado("no hay ruedas: ejecuta antes la fase descargar")
    huella = sha256(("\n".join(ruedas) + huella_fichero(req)).encode("utf-8"))
    marca = BUILD / ".instalar-ok"
    if _marca(marca) == huella and PAQUETES.is_dir():
        print("instalar: ya hecho para estas ruedas")
        return
    if PAQUETES.exists():
        shutil.rmtree(PAQUETES)
    _pip(["install", "-r", str(req), "--no-index", "--find-links", str(RUEDAS), "--target", str(PAQUETES),
          "--no-compile", *argumentos_plataforma()])
    marca.write_text(huella, encoding="utf-8")


def fase_zip(salida: pathlib.Path = ZIP_POR_DEFECTO) -> dict:
    contenido = contenido_zip(AQUI, PAQUETES)
    errores = comprobar_contenido(contenido)
    if errores:
        raise ErrorEmpaquetado("No empaqueto: " + "; ".join(errores[:20]))
    ruedas = sorted(RUEDAS.glob("*.whl"))
    manifiesto = {"schema": "ofa-prueba-hosted-manifiesto/1", "dependency_resolution": "bundled",
                  "runtime": "python_3_13", "plataformas": list(PLATAFORMAS),
                  "bloqueo": bloqueo_desde_ruedas([p.name for p in ruedas]),
                  "ruedas": {p.name: huella_fichero(p) for p in ruedas},
                  "ficheros": {r: {"sha256": sha256(b), "bytes": len(b)} for r, b in sorted(contenido.items())}}
    contenido["MANIFIESTO-HOSTED.json"] = json.dumps(manifiesto, ensure_ascii=False, indent=1).encode("utf-8")
    datos = escribir_zip(contenido, salida)
    comprobar_zip(salida)
    ficha = {"zip": salida.name, **datos, "bloqueo": manifiesto["bloqueo"]}
    salida.with_name(salida.name + ".sha256.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=1) + "\n",
                                                              encoding="utf-8")
    return ficha


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Empaqueta el hosted agent de prueba (bundled)")
    ap.add_argument("--fase", choices=("descargar", "instalar", "zip", "todo"), default="todo")
    ap.add_argument("--salida", default=str(ZIP_POR_DEFECTO))
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        if a.fase in ("descargar", "todo"):
            fase_descargar()
        if a.fase in ("instalar", "todo"):
            fase_instalar()
        if a.fase in ("zip", "todo"):
            f = fase_zip(pathlib.Path(a.salida))
            print(f"ZIP: {a.salida} · {f['ficheros']} ficheros · {f['bytes']} B · SHA-256 {f['sha256']}")
    except ErrorEmpaquetado as exc:
        print(f"FALLO: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
