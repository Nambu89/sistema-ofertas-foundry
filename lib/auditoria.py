"""Auditoría de paquetes verificados y saneado de nombres de fichero (papel E de I1).

- `linea_auditoria` compone la línea que `verificar_paquete.py --archivar` añade a
  `Proyectos/_audit/log.jsonl` (los hooks no ven las descargas del comercial).
- `anadir_linea` escribe en modo solo-añadir: nunca reescribe ni rota el log.
- `sanear_nombre` y `ruta_contenida` evitan que un nombre que viene de fuera (un ZIP, la API de
  contenedores, el nombre de un cliente) escape de la carpeta de destino.
"""
from __future__ import annotations

import datetime as _dt
import getpass
import json
import os
import pathlib
import re
import unicodedata

from lib.evidencia import comprobar_sin_token

RAIZ_WORKSPACE = pathlib.Path("C:/Users/usuario/Proyectos")
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
               *(f"LPT{i}" for i in range(1, 10))}
_NO_PERMITIDO = re.compile(r"[^\w.\- ]", re.UNICODE)


class NombreNoValido(ValueError):
    """El nombre no se puede sanear a algo utilizable."""


def sanear_nombre(nombre: str, max_len: int = 120) -> str:
    """Devuelve un nombre de fichero seguro: sin rutas, sin caracteres de control ni reservados.

    Se queda con el último componente (tanto `/` como `\\`), pasa a NFC, cambia lo no
    permitido por `_`, quita puntos y espacios de los extremos y rechaza los nombres
    reservados de Windows. Si no queda nada utilizable lanza `NombreNoValido`.
    """
    if not isinstance(nombre, str):
        raise NombreNoValido(f"nombre no textual: {nombre!r}")
    base = re.split(r"[\\/]", unicodedata.normalize("NFC", nombre))[-1]
    base = "".join(c for c in base if unicodedata.category(c)[0] != "C")
    base = _NO_PERMITIDO.sub("_", base).strip(" .")
    if len(base) > max_len:
        raiz, punto, ext = base.rpartition(".")
        base = (raiz[: max_len - len(ext) - 1] + "." + ext) if punto and len(ext) <= 10 else base[:max_len]
    if not base or base in (".", "..") or base.split(".")[0].upper() in _RESERVADOS:
        raise NombreNoValido(f"nombre no utilizable tras sanear: {nombre!r}")
    return base


def ruta_contenida(carpeta: pathlib.Path, nombre: str) -> pathlib.Path:
    """Ruta `carpeta/<nombre saneado>` comprobando que queda dentro de `carpeta`."""
    base = pathlib.Path(carpeta).resolve()
    destino = (base / sanear_nombre(nombre)).resolve()
    if destino.parent != base:
        raise NombreNoValido(f"el destino {destino} se sale de {base}")
    return destino


def linea_auditoria(*, cliente: str, codigo: str, version: str, estado: str, hash_contenido: str,
                    precio_cerrado_eur: str | None, horas_total: str | None, zip_nombre: str,
                    zip_sha256: str | None, destino: str, veredicto: str,
                    ts: str | None = None, usuario: str | None = None) -> dict:
    """Línea de auditoría (claves del README de `_audit` más las propias del paquete verificado)."""
    def _num(x: str | None) -> float | None:
        return float(x) if x not in (None, "") else None
    return {
        "ts": ts or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user": usuario or getpass.getuser(),
        "origen": "verificar_paquete",
        "cliente": cliente,
        "codigo": codigo,
        "version": version,
        "estado": estado,
        "hash_contenido": hash_contenido,
        "total_eur": _num(precio_cerrado_eur),
        "total_horas": _num(horas_total),
        "paquete": zip_nombre,
        "paquete_sha256": zip_sha256,
        "destino": destino,
        "veredicto": veredicto,
    }


def anadir_linea(ruta_log: pathlib.Path, linea: dict) -> None:
    """Añade una línea JSON al final del log (solo-añadir, con fsync). Nunca reescribe."""
    texto = json.dumps(linea, ensure_ascii=False, sort_keys=False, allow_nan=False)
    if "\n" in texto:
        raise ValueError("la línea de auditoría no puede contener saltos de línea")
    comprobar_sin_token(texto, "línea de auditoría")
    ruta_log = pathlib.Path(ruta_log)
    ruta_log.parent.mkdir(parents=True, exist_ok=True)
    previo = ruta_log.read_bytes()[-1:] if ruta_log.exists() and ruta_log.stat().st_size else b"\n"
    with open(ruta_log, "a", encoding="utf-8", newline="\n") as f:
        if previo != b"\n":
            f.write("\n")
        f.write(texto + "\n")
        f.flush()
        os.fsync(f.fileno())
