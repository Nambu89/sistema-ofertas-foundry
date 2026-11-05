"""Intérprete DETERMINISTA de los mensajes del comercial (sin modelo).

Gramática (una orden por línea; el resto del texto se ignora salvo en el alta):
- Alta: «- Cliente: …», «- Código de cliente: XXX · SEQOF: NNN» (o «- SEQOF: NNN» aparte),
  «- Título: …», «- Términos sensibles: a; b; c» y la confirmación del NDA (abajo). La transcripción
  va adjunta (input_file) o pegada después de una línea «TRANSCRIPCIÓN:».
- CONFIRMACIONES: «CONFIRMO: NDA» o la frase del alta «Confirmo que el NDA …».
- «ASUMIR: campo = valor» (una por línea; el valor literal).
- «ACLARACIÓN: texto» (una aclaración por mensaje; se guarda literal como fuente nueva).
- «DECISION | revisor | TIPO | AAAA-MM-DD | hash | comentarios» (literal; la valida el núcleo).
- «RESTAURAR» con estado.json y manifiesto_paquete.json adjuntos.
- «ESTADO» (solo muestra el estado) y «SIGUE» o «ADELANTE» (avanza a la fase siguiente).
"""
from __future__ import annotations

import dataclasses
import re
import unicodedata

_CAMPO = r"[a-z_]{3,40}"
_ASUMIR = re.compile(rf"^\s*ASUMIR\s*:\s*({_CAMPO})\s*=\s*(.+?)\s*$", re.M)
_DECISION = re.compile(r"^\s*(DECISION\s*\|.*\S)\s*$", re.M)
_ACLARACION = re.compile(r"^\s*ACLARACI[OÓ]N\s*:\s*(.+)\Z", re.M | re.S)
_TRANSCRIPCION = re.compile(r"^\s*TRANSCRIPCI[OÓ]N\s*:\s*\n(.+)\Z", re.M | re.S)
_NDA = re.compile(r"^\s*(?:[-*]\s*)?(?:CONFIRMO\s*:\s*NDA\b|Confirmo que el NDA\b)", re.M | re.I)
_ORDEN = re.compile(r"^\s*(RESTAURAR|ESTADO|SIGUE|ADELANTE)\s*[.!]?\s*$", re.M | re.I)
_LINEA = {
    "cliente": re.compile(r"^\s*[-*]?\s*Cliente\s*:\s*(.+?)\s*$", re.M),
    "codigo_cliente": re.compile(r"^\s*[-*]?\s*C[oó]digo de cliente\s*:\s*([A-Z0-9]{2,20})\b", re.M),
    "seqof": re.compile(r"\bSEQOF\s*:\s*([0-9]{3})\b"),
    "titulo": re.compile(r"^\s*[-*]?\s*T[ií]tulo\s*:\s*(.+?)\s*$", re.M),
    "sensibles": re.compile(r"^\s*[-*]?\s*T[eé]rminos sensibles\s*:\s*(.+?)\s*$", re.M),
}


@dataclasses.dataclass
class Alta:
    cliente: str | None = None
    codigo_cliente: str | None = None
    seqof: str | None = None
    titulo: str | None = None
    sensibles: list[str] = dataclasses.field(default_factory=list)

    def faltan(self) -> list[str]:
        nombres = {"cliente": "Cliente", "codigo_cliente": "Código de cliente", "seqof": "SEQOF",
                   "titulo": "Título", "sensibles": "Términos sensibles"}
        return [n for k, n in nombres.items() if not getattr(self, k)]


@dataclasses.dataclass
class Mensaje:
    texto: str
    alta: Alta | None = None
    nda_confirmado: bool = False
    asumir: list[tuple[str, str]] = dataclasses.field(default_factory=list)
    decisiones: list[str] = dataclasses.field(default_factory=list)
    aclaracion: str | None = None
    transcripcion_pegada: str | None = None
    ordenes: list[str] = dataclasses.field(default_factory=list)

    @property
    def vacio(self) -> bool:
        return not (self.alta or self.nda_confirmado or self.asumir or self.decisiones or self.aclaracion
                    or self.transcripcion_pegada or self.ordenes)


def _alta(texto: str) -> Alta | None:
    encontrados = {k: rx.search(texto) for k, rx in _LINEA.items()}
    if not any(encontrados.values()):
        return None
    a = Alta()
    for k, m in encontrados.items():
        if m is None:
            continue
        valor = m.group(1).strip()
        if k == "cliente":
            a.cliente = valor
        elif k == "codigo_cliente":
            a.codigo_cliente = valor
        elif k == "seqof":
            a.seqof = valor
        elif k == "titulo":
            a.titulo = valor
        else:
            vistos: list[str] = []
            for s in (x.strip().rstrip(".") for x in valor.split(";")):
                if s and s not in vistos:
                    vistos.append(s)
            a.sensibles = vistos
    return a


def interpretar(texto: str) -> Mensaje:
    """Convierte el texto del comercial en órdenes. No corrige ni completa nada: lo que no casa con la
    gramática no es una orden (y el turno lo dice)."""
    texto = unicodedata.normalize("NFC", (texto or "").replace("\r\n", "\n"))
    m = Mensaje(texto=texto)
    pegada = _TRANSCRIPCION.search(texto)
    cabecera = texto[:pegada.start()] if pegada else texto
    if pegada:
        m.transcripcion_pegada = pegada.group(1).strip("\n") + "\n"
    m.alta = _alta(cabecera)
    m.nda_confirmado = bool(_NDA.search(cabecera))
    m.asumir = [(c, v) for c, v in _ASUMIR.findall(cabecera)]
    m.decisiones = _DECISION.findall(cabecera)
    acl = _ACLARACION.search(cabecera)
    if acl:
        m.aclaracion = acl.group(1).strip()
    m.ordenes = [o.upper() for o in _ORDEN.findall(cabecera)]
    m.ordenes = ["SIGUE" if o == "ADELANTE" else o for o in m.ordenes]
    return m
