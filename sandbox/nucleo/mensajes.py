"""Borradores de mensaje para los revisores (CONTRATOS.md §9.6). El sistema no envía nada.

Texto plano en castellano llano, firmado por Responsable comercial. Sin direcciones de correo, sin
horas ni tarifas y sin ninguna mención a herramientas de IA. La línea de decisión va con el hash
vigente ya escrito; solo quedan por rellenar «AAAA-MM-DD» y «comentarios».
"""
from __future__ import annotations

from nucleo import decision, errores, hashes, textos_cliente
from nucleo import estado as est_mod
from nucleo.pptx_revision import AUTOR, _fallo, formato_eur

REVISOR = "Responsable de preventa"
APROBADOR = "Responsable de área"


def _base(estado: dict, nombre_zip: str) -> tuple[str, str, str, dict]:
    """(codigo, titulo, hash vigente, textos_cliente) o IntegridadRota si algo no cuadra."""
    hash_vigente = hashes.hash_contenido(estado)
    if estado.get("hash_contenido") != hash_vigente:
        raise _fallo(errores.IntegridadRota, "el mensaje no se genera: el hash_contenido guardado no es el recalculado",
                     [f"guardado {estado.get('hash_contenido')}", f"recalculado {hash_vigente}"])
    if not nombre_zip or "/" in nombre_zip or "\\" in nombre_zip:
        raise _fallo(errores.IntegridadRota, f"nombre de ZIP no válido para el mensaje: {nombre_zip!r}")
    carga = estado.get("carga") or {}
    titulo = (carga.get("alta") or {}).get("titulo") or ""
    return estado.get("codigo") or "", titulo, hash_vigente, carga.get("textos_cliente") or {}


def _comprobar(texto: str) -> str:
    hallazgos = textos_cliente.marcadores(texto)
    if hallazgos:
        raise _fallo(errores.ReglaIncumplida, "el mensaje no se publica: contiene marcadores (P9)", hallazgos)
    return texto


def _precio(textos: dict) -> list[str]:
    precio = textos.get("precio") or {}
    if not precio:
        return []
    lineas = [f"  · Precio cerrado: {formato_eur(precio['precio_cerrado_eur'])} ({precio.get('iva', 'IVA no incluido')}), "
              f"en {precio.get('duracion_semanas')} semanas."]
    lineas += [f"    · {h['nombre']}: {h['porcentaje']} %, {formato_eur(h['importe_eur'])}" for h in precio.get("hitos") or []]
    return lineas


def mensaje_revisor(estado: dict, nombre_zip: str) -> str:
    codigo, titulo, hash_vigente, textos = _base(estado, nombre_zip)
    lineas = [
        f"Asunto: [Revisión preventa] {codigo} · {titulo}",
        "",
        "Hola, responsable de preventa:",
        "",
        f"Te paso para revisión la propuesta {codigo}, «{titulo}». Va todo en un único fichero, {nombre_zip}.",
        "Dentro tienes la presentación que vería el cliente, la nota de revisión interna y la estimación interna.",
        "",
        *([f"IMPORTANTE. {est_mod.AVISO_SIN_GRABACION}", ""] if est_mod.sin_grabacion(estado) else []),
        "Te pido que revises sobre todo:",
        "- La arquitectura: que el diagrama cubra todo el alcance y que los servicios sean los adecuados.",
        "- Las referencias: cada una enlaza a la documentación oficial de Microsoft que la respalda.",
        "- Los precios de consumo en la nube: cada uno indica su fuente y su fecha.",
        "- La estimación interna (fichero de estimación y apartado 7 de la nota).",
        "",
        "Los supuestos que no salieron de la reunión con el cliente están marcados como de confianza baja, y lo "
        "que no se pudo comprobar figura en el apartado de riesgos residuales de la nota.",
        "",
        f"Huella del contenido: {hash_vigente}",
        "Tu decisión solo vale para esta huella; si cambio algo, te enviaré una versión nueva.",
        "",
        "Para responder, copia la línea que corresponda, pon la fecha y tus comentarios:",
        f"DECISION | {REVISOR} | APROBADA | AAAA-MM-DD | {hash_vigente} | comentarios",
        f"DECISION | {REVISOR} | DEVUELTA | AAAA-MM-DD | {hash_vigente} | comentarios",
        "",
        "Gracias.",
        "",
        AUTOR,
    ]
    return _comprobar("\n".join(lineas) + "\n")


def mensaje_aprobador(estado: dict, nombre_zip: str) -> str:
    codigo, titulo, hash_vigente, textos = _base(estado, nombre_zip)
    revisado = (decision.firmas(estado) or {}).get("revisado")
    tras = (f"Responsable de preventa la revisó y la aprobó el {revisado['fecha']}." if revisado
            else "Te llega después de la revisión de Responsable de preventa.")
    lineas = [
        f"Asunto: [Aprobación] {codigo} · {titulo}",
        "",
        "Hola, responsable de área:",
        "",
        f"Te paso para aprobación la propuesta {codigo}, «{titulo}». {tras}",
        f"Va todo en un único fichero, {nombre_zip}.",
        "",
        "Te pido que mires sobre todo:",
        "- El diagrama de arquitectura de la presentación.",
        "- El precio cerrado y los hitos de facturación:",
        *_precio(textos),
        "",
        "El consumo en la nube es orientativo, no está incluido en el precio y lo asume el cliente.",
        "",
        f"Huella del contenido: {hash_vigente}",
        "Tu decisión solo vale para esta huella.",
        "",
        "Para responder, copia la línea que corresponda, pon la fecha y tus comentarios:",
        f"DECISION | {APROBADOR} | APROBADA | AAAA-MM-DD | {hash_vigente} | comentarios",
        f"DECISION | {APROBADOR} | DEVUELTA | AAAA-MM-DD | {hash_vigente} | comentarios",
        "",
        "Gracias.",
        "",
        AUTOR,
    ]
    return _comprobar("\n".join(lineas) + "\n")
