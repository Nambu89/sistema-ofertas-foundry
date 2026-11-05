"""Bloque «Forma mínima de requisitos.json» de las instrucciones del coordinador (VERIF-1, H1).

En I1 y en I1.1 el coordinador escribió requisitos.json sin la envoltura {"schema", "campos"} y gastó un
intento de T1 en cada alta. El bloque sale de nucleo.suficiencia.forma_minima(), que a su vez lo genera
desde esquemas/requisitos.json, para que las instrucciones no se desincronicen del esquema.
Uso: python -m agentes.esquemas.forma_requisitos [--comprobar]
"""
from __future__ import annotations

import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "agentes" / "instrucciones" / "coordinador_i1.md"
INICIO = "### Forma mínima de requisitos.json (generada por agentes/esquemas/forma_requisitos.py; no editar a mano)"
FIN = "### Fin de la forma mínima"


def bloque() -> str:
    if str(RAIZ / "sandbox") not in sys.path:
        sys.path.insert(0, str(RAIZ / "sandbox"))
    from nucleo import suficiencia
    return "\n".join([INICIO, "", "```json", suficiencia.forma_minima(), "```", "", FIN])


def insertar(texto: str) -> str:
    i, f = texto.find(INICIO), texto.find(FIN)
    if i < 0 or f < i or texto.count(INICIO) != 1 or texto.count(FIN) != 1:
        raise ValueError("faltan, sobran o están desordenadas las líneas del bloque de la forma mínima")
    return texto[:i] + bloque() + texto[f + len(FIN):]


def main(argv: list[str] | None = None) -> int:
    comprobar = "--comprobar" in (argv if argv is not None else sys.argv[1:])
    actual = DESTINO.read_text(encoding="utf-8")
    nuevo = insertar(actual)
    if comprobar:
        print(f"{'igual' if nuevo == actual else 'DESINCRONIZADO'} {DESTINO.name}")
        return int(nuevo != actual)
    if nuevo != actual:
        DESTINO.write_text(nuevo, encoding="utf-8", newline="\n")
        print(f"escrito {DESTINO.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
