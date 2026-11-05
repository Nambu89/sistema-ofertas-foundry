"""Pruebas de los borradores de mensaje (sin red). CONTRATOS.md §9.6."""
from __future__ import annotations

import re

import pytest

from tests.test_i1_documentos_comun import estado_ejemplo, docs  # noqa: F401  (fixture)


ZIP = "OF-KELVARA-001-A-Paquete.zip"
PROHIBIDAS = ("hora", "jornada", "tarifa", "€/h", "eur/h", "project manager", "consultor junior", "claude",
              "chatgpt", "gpt", "copilot", "generado automáticamente", "inteligencia artificial generativa", "@")


def _comunes(texto: str, nombre: str, asunto: str) -> None:
    h = estado_ejemplo()["hash_contenido"]
    lineas = texto.splitlines()
    assert lineas[0] == f"{asunto} OF-KELVARA-001-A · Asistente de consulta técnica con IA sobre informes de ensayo"
    assert f"DECISION | {nombre} | APROBADA | AAAA-MM-DD | {h} | comentarios" in lineas
    assert f"DECISION | {nombre} | DEVUELTA | AAAA-MM-DD | {h} | comentarios" in lineas
    assert f"Huella del contenido: {h}" in lineas
    assert lineas[-1] == "Responsable comercial" and texto.endswith("\n")
    assert ZIP in texto
    bajo = texto.lower()
    for palabra in PROHIBIDAS:
        assert palabra not in bajo, palabra
    assert not re.search(r"<[^<>\n]{1,60}>", texto)
    assert not re.search(r"\b(TBD|TODO|XXX|PLACEHOLDER)\b", texto)
    assert not re.search(r"\b(pendientes?|por definir)\b", bajo)


def test_mensaje_revisor(docs):
    texto = docs.me.mensaje_revisor(estado_ejemplo(), ZIP)
    _comunes(texto, "Responsable de preventa", "Asunto: [Revisión preventa]")
    assert "Hola, responsable de preventa:" in texto and "arquitectura" in texto and "precios" in texto.lower()


def test_mensaje_aprobador_con_y_sin_firma_de_javier(docs):
    estado = estado_ejemplo()
    texto = docs.me.mensaje_aprobador(estado, ZIP)
    _comunes(texto, "Responsable de área", "Asunto: [Aprobación]")
    assert "después de la revisión de Responsable de preventa" in texto
    assert "28.025,25 €" in texto and "Hito 4 - Evaluación final y cierre: 25 %, 7.006,32 €" in texto
    estado["decisiones"] = [{"id": "D-001", "revisor": "Responsable de preventa", "tipo": "APROBADA", "fecha": "2026-10-09",
                             "version": "A", "hash_citado": estado["hash_contenido"]}]
    assert "la aprobó el 2026-10-09" in docs.me.mensaje_aprobador(estado, ZIP)


def test_hash_vencido_o_zip_invalido(docs):
    estado = estado_ejemplo()
    estado["hash_contenido"] = "a" * 64
    with pytest.raises(docs.errores.IntegridadRota):
        docs.me.mensaje_revisor(estado, ZIP)
    with pytest.raises(docs.errores.IntegridadRota):
        docs.me.mensaje_aprobador(estado_ejemplo(), "../otro.zip")


def test_el_mensaje_no_cambia_el_contenido(docs):
    estado = estado_ejemplo()
    antes = docs.hashes.hash_contenido(estado)
    docs.me.mensaje_revisor(estado, ZIP)
    docs.me.mensaje_aprobador(estado, ZIP)
    assert docs.hashes.hash_contenido(estado) == antes == estado["hash_contenido"]


def test_los_dobles_no_tapan_un_error_real_de_un_modulo_existente():
    from tests.test_i1_documentos_comun import _falta_fichero_nucleo
    assert _falta_fichero_nucleo(ModuleNotFoundError("x", name="nucleo.no_existe_aun"))
    assert not _falta_fichero_nucleo(ModuleNotFoundError("x", name="nucleo.hashes"))  # existe: error real
    assert not _falta_fichero_nucleo(ImportError("cannot import name 'hashes' from 'nucleo'", name="nucleo"))
    assert _falta_fichero_nucleo(ImportError("cannot import name 'no_existe_aun' from 'nucleo'", name="nucleo"))
    assert not _falta_fichero_nucleo(ModuleNotFoundError("x", name="otro_paquete"))
