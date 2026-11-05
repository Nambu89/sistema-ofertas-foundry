"""Barrido previo a publicar: busca datos que no pueden salir del entorno privado.

Uso: python herramientas/barrido_publicacion.py [--terminos RUTA]

Recorre lo que git publicaría (versionado y nuevo no ignorado) y busca:
- los términos prohibidos de un fichero LOCAL e ignorado por git (por defecto
  `config/terminos-prohibidos.local.txt`; plantilla en `config/terminos-prohibidos.local.txt.ejemplo`):
  nombres de personas y de clientes, identificadores de tenant o suscripción, dominios de correo…;
- patrones de secreto (claves de cuenta de almacenamiento, firmas SAS, claves de Google, JWT, claves hex);
- cualquier GUID que no sea un identificador público e integrado de Azure (roles y directivas).

Nunca imprime el valor encontrado entero: solo la ruta, la línea y la regla.
Código de salida = veredicto: 0 limpio; 1 hay hallazgos; 2 configuración inválida (falta la lista local,
está vacía o conserva los términos ficticios de la plantilla).
"""
from __future__ import annotations

import argparse
import io
import pathlib
import re
import subprocess
import sys
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parent.parent
TERMINOS = RAIZ / "config" / "terminos-prohibidos.local.txt"
PREFIJO_FICTICIO = "termino-ejemplo-"

SECRETOS = {
    "clave de cuenta de almacenamiento": re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    "firma SAS": re.compile(r"sig=[A-Za-z0-9%]{20,}"),
    "clave de Google": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "JWT": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\."),
    "cabecera de clave de API de voz": re.compile("xi-" + "api-key", re.I),   # partido: el script no se detecta a sí mismo
    "clave hex junto a un nombre de clave": re.compile(
        r"(?:key|clave|secret|token|password|pwd)[\"'\s:=]{1,6}[0-9a-fA-F]{32,}", re.I),
    # Las huellas SHA-256 (64 hex) son públicas por diseño; 32 hex sueltos es el formato de clave de Azure AI.
    "32 hex sueltos": re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])"),
}
GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
# Identificadores integrados de Azure, iguales en todos los tenants y publicados en Microsoft Learn.
GUIDS_PUBLICOS = {
    "00000000-0000-0000-0000-000000000000",
    "00000000-0000-0000-0000-000000000002",  # Cosmos DB Built-in Data Contributor
    "53ca6127-db72-4b80-b1b0-d745d6d5456d",  # Azure AI User (Foundry User)
    "eed3b665-ab3a-47b6-8f48-c9382fb1dad6",  # Foundry Agent Consumer
    "7f951dda-4ed3-4680-a7ca-43fe172d538d",  # AcrPull
    "8311e382-0749-4cb8-b61a-304f252e45ec",  # AcrPush
    "358470bc-b998-42bd-ab17-a7e34c199c0f",  # Container Apps Contributor
    "4633458b-17de-408a-b874-0445c86b69e6",  # Key Vault Secrets User
    "b86a8fe4-44ce-4948-aee5-eccb2c155cd7",  # Key Vault Secrets Officer
    "17d1049b-9a84-46fb-8f53-869881c3d3ab",  # Storage Account Contributor
    "ba92f5b4-2d11-453d-a403-e96b0029c9fe",  # Storage Blob Data Contributor
    "b7e6dc6d-f1e8-4753-8033-0f276bb0955b",  # Storage Blob Data Owner
    "8ebe5a00-799e-43f5-93ac-243d3dce84a7",  # Search Index Data Contributor
    "7ca78c08-252a-4471-8644-bb5ff32d4ba0",  # Search Service Contributor
    "230815da-be43-4aae-9cb4-875f7bd000aa",  # Cosmos DB Operator
    "71ef260a-8f18-47b7-abcb-62d0673d94dc",  # directiva: Azure AI Services sin autenticación local
    "037eea7a-bd0a-46c5-9a66-03aea78705d3",  # directiva: Azure AI Services con acceso de red restringido
    "a97b65f3-24c7-4388-baec-2e87135dc908",  # Cognitive Services User
}
# GUID que no identifican a nadie, cada uno solo en su sitio exacto: los ficticios que empiezan por ceros, el valor de
# un `"meterId"` de la Retail Prices API o la celda de la columna «meterId» de una tabla Markdown, y los id internos
# de los iconos que pone el generador del diagrama (`i-<nombre>-<GUID>`) en un SVG, HTML o drawio.
GUID_FICTICIO = re.compile(r"^00000000-0000-")
ANTES_DE_METERID = re.compile(r'"meterId":\s*"$')
ANTES_DE_ID_ICONO = re.compile(r'(?:id="|url\(#|href="#)i-[\w-]*-$')
SUFIJOS_DIAGRAMA = (".svg", ".html", ".drawio")
MAX_ANIDADO = 3
SEPARADOR_TABLA = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def leer_terminos(ruta: pathlib.Path) -> list[tuple[str, re.Pattern[str]]]:
    """Una regla por línea: literal con límites de palabra y sensible a mayúsculas, o `re:` + expresión."""
    reglas: list[tuple[str, re.Pattern[str]]] = []
    for n, linea in enumerate(ruta.read_text(encoding="utf-8-sig").splitlines(), 1):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#"):
            continue
        if limpia.casefold().startswith(PREFIJO_FICTICIO):
            raise ValueError(f"línea {n}: conserva un término ficticio de la plantilla")
        if limpia.startswith("re:"):
            reglas.append((f"término local, línea {n}", re.compile(limpia[3:])))
        else:
            izq = r"\b" if re.match(r"\w", limpia) else ""
            der = r"\b" if re.search(r"\w$", limpia) else ""
            reglas.append((f"término local, línea {n}", re.compile(izq + re.escape(limpia) + der)))
    if not reglas:
        raise ValueError("no trae ningún término")
    return reglas


def ficheros_publicables(raiz: pathlib.Path) -> list[pathlib.Path]:
    salida = subprocess.run(["git", "-C", str(raiz), "ls-files", "-z", "--cached", "--others",
                             "--exclude-standard"], check=True, capture_output=True).stdout
    vistos = {p for p in salida.decode("utf-8").split("\0") if p}
    return [raiz / p for p in sorted(vistos) if (raiz / p).is_file()]


def barrer(ficheros: list[pathlib.Path], reglas: list[tuple[str, re.Pattern[str]]],
           raiz: pathlib.Path) -> list[str]:
    hallazgos = []
    todas = reglas + list(SECRETOS.items())
    for f in ficheros:
        rel = f.relative_to(raiz).as_posix()
        for donde, datos in _contenidos(f, rel):
            for texto in _textos(datos):
                hallazgos += _barrer_texto(texto, donde, todas)
        # El nombre del fichero también se publica.
        for nombre, patron in reglas:
            if patron.search(rel):
                hallazgos.append(f"{rel}: {nombre} en la ruta")
    return hallazgos


def _contenidos(f: pathlib.Path, rel: str):
    """El fichero tal cual (los binarios también: un PNG puede llevar texto en claro) y, si es un ZIP, cada miembro
    descomprimido con su nombre, también dentro de ZIP anidados (un PPTX o un DOCX dentro de un paquete), porque
    DEFLATE esconde el texto a una búsqueda sobre los bytes."""
    yield from _miembros(f.read_bytes(), rel, 0)


def _textos(datos: bytes) -> list[str]:
    """UTF-8 siempre; si hay bytes nulos, también UTF-16 en los dos órdenes (un UTF-16 intercala ceros entre letras)."""
    textos = [datos.decode("utf-8", errors="replace")]
    if b"\x00" in datos:
        textos += [datos.decode(c, errors="replace") for c in ("utf-16-le", "utf-16-be")]
    return textos


def _miembros(datos: bytes, rel: str, nivel: int):
    yield rel, datos
    if not zipfile.is_zipfile(io.BytesIO(datos)):   # también con preámbulo delante de la firma
        return
    if nivel >= MAX_ANIDADO:
        raise ValueError(f"{rel}: ZIP anidado más de {MAX_ANIDADO} niveles; revísalo a mano")
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        for m in z.infolist():
            if not m.is_dir():
                yield f"{rel}!{m.filename} (nombre)", m.filename.encode("utf-8")
                yield from _miembros(z.read(m), f"{rel}!{m.filename}", nivel + 1)


def _celda_meterid(linea: str, inicio: int, columna: int | None) -> bool:
    """El GUID ocupa entera la celda de la columna «meterId» de la tabla Markdown en curso."""
    if columna is None:
        return False
    celdas = linea.strip().strip("|").split("|")
    indice = linea[:inicio].count("|") - 1   # la fila empieza por «|»
    g = GUID.match(linea, inicio).group(0)
    return indice == columna and indice < len(celdas) and celdas[indice].strip().strip("`") == g


def _barrer_texto(texto: str, rel: str, todas) -> list[str]:
    hallazgos = []
    columna_meterid = None   # índice de la columna «meterId» de la tabla Markdown en curso
    diagrama = rel.split("!")[-1].endswith(SUFIJOS_DIAGRAMA)
    anterior = ""
    for n, linea in enumerate(texto.splitlines(), 1):
        for nombre, patron in todas:
            if patron.search(linea):
                hallazgos.append(f"{rel}:{n}: {nombre}")
        if SEPARADOR_TABLA.match(linea):   # cabecera nueva = la línea anterior al separador
            cab = [c.strip() for c in anterior.strip().strip("|").split("|")]
            columna_meterid = cab.index("meterId") if "meterId" in cab else None
        elif not linea.lstrip().startswith("|"):
            columna_meterid = None
        anterior = linea
        for m in GUID.finditer(linea):
            g, antes = m.group(0).lower(), linea[max(0, m.start() - 80):m.start()]
            if (g in GUIDS_PUBLICOS or GUID_FICTICIO.match(g) or ANTES_DE_METERID.search(antes)
                    or _celda_meterid(linea, m.start(), columna_meterid)
                    or (diagrama and ANTES_DE_ID_ICONO.search(antes))):
                continue
            hallazgos.append(f"{rel}:{n}: GUID no público ({g[:4]}…)")
    return hallazgos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--terminos", type=pathlib.Path, default=TERMINOS)
    ap.add_argument("--raiz", type=pathlib.Path, default=RAIZ)
    args = ap.parse_args(argv)
    try:
        reglas = leer_terminos(args.terminos)
    except FileNotFoundError:
        print(f"CONFIGURACIÓN: falta {args.terminos}; créalo desde la plantilla .ejemplo", file=sys.stderr)
        return 2
    except (ValueError, re.error) as e:
        print(f"CONFIGURACIÓN: {args.terminos}: {e}", file=sys.stderr)
        return 2
    ficheros = ficheros_publicables(args.raiz.resolve())
    hallazgos = barrer(ficheros, reglas, args.raiz.resolve())
    for h in hallazgos:
        print(h)
    print(f"{len(ficheros)} ficheros, {len(reglas)} términos locales, {len(hallazgos)} hallazgos")
    return 1 if hallazgos else 0


if __name__ == "__main__":
    sys.exit(main())
