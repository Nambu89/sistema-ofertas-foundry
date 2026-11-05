"""Evidencias sin secretos: enmascarado, escritura con red y barrido del repositorio.

- `escribir_json` es la última barrera (C4 de la revisión de I0): si el texto lleva un JWT, una
  cabecera `Bearer <valor>`, `InstrumentationKey=<guid>` o `AccountKey=<valor>`, no escribe y falla.
- `limpiar` y `enmascarar_texto` (R3 y H-V5 de I1) tapan los secretos ANTES de escribir: por nombre
  de campo (por subcadena, no solo el nombre exacto: `ApplicationInsightsConnectionString` se colaba)
  y por valor (cadenas de conexión, tokens, firmas SAS, claves privadas y claves asignadas).
- `guardar_enmascarado` = limpiar + escribir_json. Es lo que usan los scripts de captura.
- `python -m lib.evidencia barrer [--fix] [RUTA...]` recorre el repositorio, imprime fichero,
  línea y tipo (nunca el valor) y sale con 1 si queda algo sin tapar (LES-G-091).
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import zipfile
from typing import Any

OMITIDO = "<OMITIDO>"

PATRON_TOKEN = re.compile(
    r"eyJ[A-Za-z0-9_-]{20,}[.][A-Za-z0-9_-]{20,}"          # JWT
    r"|(?i:bearer)(?:\s|\\[tnr])+[A-Za-z0-9._~+/=-]{20,}"  # Authorization (b64token, RFC 6750;
    # el separador puede llegar escapado por json.dumps como \t o \n)
    r"|InstrumentationKey=[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}"  # cadena de conexión de App Insights
    r"|AccountKey=[A-Za-z0-9+/=]{20,}")                     # cadena de conexión de Storage

# Nombres de campo cuyo valor se tapa siempre, sea del tipo que sea (el filtro de antes; se conserva
# para que una captura nueva siga coincidiendo con la línea base en lo que ya estaba tapado).
CLAVES_EXACTAS = frozenset({
    "key", "keys", "apikey", "api_key", "secret", "password", "token", "accesstoken",
    "access_token", "connectionstring", "connection_string", "clientsecret", "client_secret",
    "sas", "credentials", "instrumentationkey"})
# Nombres que se tapan si contienen o terminan en esto (solo valores con contenido: un null o un
# booleano no es un secreto y taparlo rompería la comparación con la línea base).
CLAVES_SUBCADENA = ("connectionstring", "connection_string", "instrumentationkey", "accountkey",
                    "account_key", "secret", "password", "credential", "apikey", "api_key",
                    "privatekey", "private_key", "sastoken", "sas_token")
CLAVES_SUFIJO = ("key", "keys", "token")

# Un valor real no empieza por «<» (ya tapado o marcador de documentación) ni lleva metacaracteres de
# una expresión regular (el código que busca secretos no es un secreto).
_VALOR = r"(?!<)[^;\"'\s`<>\[\](){}|\\]{6,}"
# (tipo, patrón, sustitución). Formas realistas: un ejemplo de prueba corto no salta.
PATRONES_SECRETO = (
    ("clave_privada", re.compile(r"-----BEGIN ([A-Z ]*)PRIVATE KEY-----[\s\S]*?-----END \1PRIVATE KEY-----"),
     "<OMITIDO-CLAVE-PRIVADA>"),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*"), "<OMITIDO-JWT>"),
    ("bearer", re.compile(r"(?i)(bearer(?:\s|\\[tnr])+)[A-Za-z0-9._~+/=-]{20,}"), r"\1" + OMITIDO),
    # Clave de App Insights: un tramo hexadecimal de 4 o más (tapa también un prefijo impreso a medias);
    # el ejemplo de Learn, todo ceros, no cuenta.
    ("instrumentation_key", re.compile(r"(?i)\b(InstrumentationKey=)(?!0{8})[0-9a-f]{4,}[0-9a-f-]*"),
     r"\1" + OMITIDO),
    ("cadena_conexion", re.compile(r"(?i)\b(AccountKey=|SharedAccessKey=)[A-Za-z0-9+/]{20,}={0,2}"),
     r"\1" + OMITIDO),
    ("cadena_conexion", re.compile(r"(?i)\b(AccessKey|ClientSecret|Password|Pwd)(=)" + _VALOR),
     r"\1\2" + OMITIDO),
    ("application_id", re.compile(r"(?i)(;\s*ApplicationId=)[0-9a-f]{8}-[0-9a-f-]{27}"), r"\1" + OMITIDO),
    ("sas_sig", re.compile(r"([?&]sig=)[A-Za-z0-9%+/=]{20,}"), r"\1" + OMITIDO),
    ("clave_sk", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), "<OMITIDO-SK>"),
    ("clave_asignada", re.compile(
        r"(?i)([\"']?\b(?:api[-_]?key|subscription[-_]?key|access[-_]?key|account[-_]?key|"
        r"primary[-_]?key|secondary[-_]?key|key[12]|client[-_]?secret|secret|password)[\"']?"
        r"\s*[:=]\s*[\"']?)(?!<)[A-Za-z0-9+/_~.=-]{24,}"), r"\1" + OMITIDO),
)


class EvidenciaConSecreto(RuntimeError):
    """La evidencia contiene algo con forma de token o de cadena de conexión: no se escribe."""


def comprobar_sin_token(texto: str, nombre: str = "evidencia") -> None:
    """Lanza EvidenciaConSecreto si el texto contiene algo con forma de token (sin mostrarlo)."""
    m = PATRON_TOKEN.search(texto)
    if m:
        s = m.group(0)
        tipo = ("JWT" if s.startswith("eyJ") else "Bearer" if s.lower().startswith("bearer")
                else s.split("=")[0])  # nunca se muestra el valor
        raise EvidenciaConSecreto(
            f"La evidencia {nombre} contiene algo con forma de token ({tipo}): no se escribe")


def buscar_secretos(texto: str) -> list[tuple[str, int]]:
    """Devuelve (tipo, línea) de cada secreto sin tapar. Nunca devuelve el valor."""
    hall = []
    for tipo, rx, _ in PATRONES_SECRETO:
        hall += [(tipo, texto.count("\n", 0, m.start()) + 1) for m in rx.finditer(texto)]
    return sorted(hall, key=lambda h: (h[1], h[0]))


def enmascarar_texto(texto: str) -> str:
    """Tapa en un texto todos los secretos con forma reconocible. Es idempotente."""
    for _, rx, sust in PATRONES_SECRETO:
        texto = rx.sub(sust, texto)
    return texto


def es_clave_secreta(nombre: str) -> bool:
    """Indica si un nombre de campo es de credencial (exacto, por subcadena o por sufijo)."""
    k = nombre.lower().replace("-", "_")
    return (k in CLAVES_EXACTAS or nombre.lower() in CLAVES_EXACTAS
            or any(s in k for s in CLAVES_SUBCADENA) or k.endswith(CLAVES_SUFIJO))


def limpiar(o: Any) -> Any:
    """Copia de `o` con las credenciales tapadas por nombre de campo y por valor."""
    if isinstance(o, dict):
        r = {}
        for k, v in o.items():
            k_txt = str(k)
            if k_txt.lower() in CLAVES_EXACTAS or k_txt.lower().replace("-", "_") in CLAVES_EXACTAS:
                r[k] = OMITIDO  # como el filtro de antes: cualquier tipo
            elif es_clave_secreta(k_txt) and isinstance(v, (str, dict, list)) and v:
                r[k] = OMITIDO
            else:
                r[k] = limpiar(v)
        return r
    if isinstance(o, (list, tuple)):
        return [limpiar(x) for x in o]
    if isinstance(o, str):
        return enmascarar_texto(o)
    return o


def escribir_json(p: str | pathlib.Path, obj: Any, indent: int = 2) -> pathlib.Path:
    """Serializa `obj`, comprueba que no lleva tokens y solo entonces escribe el fichero."""
    p = pathlib.Path(p)
    texto = json.dumps(obj, ensure_ascii=False, indent=indent) + "\n"
    comprobar_sin_token(texto, p.name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    return p


def guardar_enmascarado(p: str | pathlib.Path, obj: Any, indent: int = 2) -> pathlib.Path:
    """Tapa los secretos de `obj`, comprueba que no queda ninguno y escribe (o falla en alto)."""
    limpio = limpiar(obj)
    texto = json.dumps(limpio, ensure_ascii=False, indent=indent)
    quedan = buscar_secretos(texto)
    if quedan:  # no debería pasar: limpiar usa los mismos patrones
        raise EvidenciaConSecreto(f"La evidencia {pathlib.Path(p).name} conserva secretos tras "
                                  f"enmascarar: {sorted({t for t, _ in quedan})}")
    return escribir_json(p, limpio, indent)


# ------------------------------------------------------------------------------------- barrido
RAIZ = pathlib.Path(__file__).resolve().parents[1]
EXCLUIR = {".venv", ".git", "__pycache__", "node_modules", ".pytest_cache"}
BINARIOS = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".ttf", ".otf", ".woff", ".woff2",
            ".npy", ".pyc", ".exe", ".dll", ".so", ".db", ".sqlite"}
CONTENEDORES = {".zip", ".xlsx", ".pptx", ".docx"}
TAM_MAX = 20_000_000
TAM_MAX_MIEMBRO = 50_000_000


def _ficheros(rutas: list[pathlib.Path]):
    for r in rutas:
        if r.is_file():
            yield r
        elif r.is_dir():
            for p in sorted(r.rglob("*")):
                if p.is_file() and not EXCLUIR.intersection(p.relative_to(r).parts):
                    yield p
        else:
            raise SystemExit(f"No existe: {r}")


def _rel(p: pathlib.Path) -> str:
    try:
        return str(p.resolve().relative_to(pathlib.Path.cwd().resolve()))
    except ValueError:
        return str(p)


def secretos_en_zip(datos: bytes, nombre: str = "zip") -> tuple[list[str], list[str]]:
    """(hallazgos, no revisados) dentro de un ZIP/OOXML en memoria. Nunca devuelve valores."""
    import io
    hall, omit = [], []
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as z:
            for i in z.infolist():
                if i.file_size > TAM_MAX_MIEMBRO:  # tope sobre el tamaño expandido
                    omit.append(f"{nombre}!{i.filename}: más de {TAM_MAX_MIEMBRO} bytes descomprimido")
                    continue
                t = z.read(i).decode("utf-8", errors="ignore")  # por ZipInfo: con nombres duplicados se leen todos
                hall += [f"{nombre}!{i.filename}:{ln}: {tipo}" for tipo, ln in buscar_secretos(t)]
    except Exception as e:  # noqa: BLE001  cualquier fallo de lectura se declara, no se silencia
        omit.append(f"{nombre}: contenedor ilegible ({type(e).__name__})")
    return hall, omit


def barrer(rutas: list[pathlib.Path], arreglar: bool = False, out=print) -> int:
    """Busca secretos sin tapar. 0 limpio; 1 quedan secretos; 3 limpio pero con ficheros sin revisar.

    Los binarios (por extensión o con NUL al principio) no se revisan: se cuentan y se declaran."""
    quedan, arreglados, omitidos, binarios, n, nz = [], [], [], {}, 0, 0
    for p in _ficheros(rutas):
        suf = p.suffix.lower()
        if suf in BINARIOS:
            binarios[suf] = binarios.get(suf, 0) + 1
            continue
        if p.stat().st_size > TAM_MAX:
            omitidos.append(f"{_rel(p)}: más de {TAM_MAX} bytes")
            continue
        b = p.read_bytes()
        if suf in CONTENEDORES:
            nz += 1
            hall_z, omit_z = secretos_en_zip(b, _rel(p))
            quedan += [h + " (no se arregla dentro de un contenedor: hay que regenerarlo)" for h in hall_z]
            omitidos += omit_z
            continue
        if b"\x00" in b[:8192]:
            binarios[suf or "(sin extensión)"] = binarios.get(suf or "(sin extensión)", 0) + 1
            continue
        n += 1
        t = b.decode("utf-8", errors="surrogateescape")  # al reescribir se conservan los bytes
        hall = buscar_secretos(t)
        if hall and arreglar:
            nuevo = enmascarar_texto(t)
            p.write_bytes(nuevo.encode("utf-8", errors="surrogateescape"))
            arreglados += [f"{_rel(p)}:{ln}: {tipo}" for tipo, ln in hall]
            hall = buscar_secretos(nuevo)
        quedan += [f"{_rel(p)}:{ln}: {tipo}" for tipo, ln in hall]
    out(f"ficheros de texto revisados: {n}; contenedores ZIP/OOXML revisados por dentro: {nz}")
    out("binarios no revisados (declarados): " + (", ".join(f"{k} {v}" for k, v in sorted(binarios.items()))
                                                 or "ninguno"))
    for linea in arreglados:
        out("TAPADO   " + linea)
    for linea in omitidos:
        out("SIN REVISAR " + linea)
    for linea in quedan:
        out("SECRETO  " + linea)
    out(f"tapados: {len(arreglados)}; secretos sin tapar: {len(quedan)}; sin revisar: {len(omitidos)}")
    return 1 if quedan else 3 if omitidos else 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m lib.evidencia", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="orden", required=True)
    b = sub.add_parser("barrer", help="busca (y con --fix tapa) secretos; nunca imprime el valor")
    b.add_argument("--fix", action="store_true", help="tapa en el sitio lo encontrado")
    b.add_argument("rutas", nargs="*", type=pathlib.Path, help="por defecto, todo el repositorio")
    a = ap.parse_args(argv)
    return barrer(a.rutas or [RAIZ], arreglar=a.fix)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
