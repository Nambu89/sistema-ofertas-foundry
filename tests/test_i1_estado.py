"""Pruebas de la CLI preventa_run.py (papel BA): flujo completo y cada transición. Sin red.

Los módulos de B, C y D se sustituyen por dobles con su firma pública (test_i1_estado_comun).
"""
from __future__ import annotations

import json
import shutil

import pytest

from tests.test_i1_estado_comun import ADJUNTO, Mundo, ejemplo, estado, hashes


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def test_flujo_completo_hasta_aprobada(m):
    rc, out = m.iniciar()
    assert rc == 0 and "estado: BORRADOR" in out and "codigo: OF-KELVARA-001-A" in out
    alta = m.estado()["carga"]["alta"]
    assert {"Responsable comercial", "Marta Olmedo", "Kelvara Ensayos Industriales, S.A."} <= set(alta["terminos_sensibles"])
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", m.requisitos_modelo()))
    assert rc == 1 and "estado: INFORMACION_INSUFICIENTE" in out
    assert "volumetria: ¿" in out and "identidad_acl_origen: ¿" in out and "  d) otra" in out
    req = ejemplo("requisitos")["campos"]
    rc, out = m.run("asumir", "--campo", "volumetria", "--valor", req["volumetria"]["entradas"][0]["valor"])
    assert rc == 0 and "estado: INFORMACION_INSUFICIENTE" in out
    rc, out = m.run("asumir", "--campo", "identidad_acl_origen", "--valor", req["identidad_acl_origen"]["entradas"][0]["valor"])
    assert rc == 0 and "estado: EN_ANALISIS" in out and "SIGUIENTE PASO OBLIGATORIO: enrutar" in out
    assert m.estado()["carga"]["requisitos"] == ejemplo("requisitos")
    rc, out = m.run("enrutar")
    brief_ej = ejemplo("brief")["texto"]
    assert rc == 0 and f"=== BRIEF PARA preventa-experto-azure ===\n{brief_ej}\n=== FIN BRIEF ===" in out
    assert "expertos: azure=BRIEF_ENVIADO" in out and "respuesta_experto_AZ_R1.json" in out
    r = m.entrada("respuesta_experto_AZ_R1.json", ejemplo("respuesta_experto"))
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", r)
    assert rc == 0 and "expertos: azure=VALIDA" in out and "En el siguiente: consolidar" in out
    rc, out = m.run("consolidar")
    assert rc == 0 and "estado: EN_VERIFICACION" in out
    assert ejemplo("estado")["carga"]["consolidado"]["texto"] in out
    r = m.entrada("respuesta_verificador_R1.json", ejemplo("respuesta_verificador"))
    rc, out = m.run("registrar-verificacion", "--respuesta", r)
    assert rc == 0 and "estado: VERIFICADA" in out and "NO VERIFICABLE C-06" in out and "anexo-consumo" in out, out
    rc, out = m.run("anexo-consumo")
    assert rc == 0 and "SIGUIENTE PASO OBLIGATORIO: estimar (el núcleo compone" in out  # I1.4: nadie escribe el JSON
    rc, out = m.run("estimar")
    assert rc == 0 and "SIGUIENTE PASO OBLIGATORIO: paquete" in out
    h = m.hash()
    rc, out = m.run("paquete")
    assert rc == 0 and "estado: LISTA_PARA_REVISION" in out and "OF-KELVARA-001-A-Paquete.zip" in out
    assert m.hash() == h and (m.raiz / "salida" / "OF-KELVARA-001-A-Paquete.zip").is_file()
    rc, out = m.run("decision", "--linea", m.linea("Responsable comercial", "ENVIADA_REVISION", "verificar_paquete rc=0"))
    assert rc == 0 and "estado: EN_REVISION_PREVENTA" in out
    rc, out = m.run("decision", "--linea", m.linea("responsable de preventa", "APROBADA", "Revisado"))
    assert rc == 0 and "estado: EN_APROBACION_AREA" in out
    rc, out = m.run("decision", "--linea", m.linea("Responsable de área", "APROBADA", ""))
    assert rc == 0 and "estado: APROBADA" in out and "decisiones: 3" in out
    rc, out = m.run("paquete")
    assert rc == 0 and "estado: APROBADA" in out
    est = m.estado()
    assert est["hash_contenido"] == h and est["decisiones"][1]["revisor"] == "Responsable de preventa"
    assert [c["subcomando"] for c in est["control_versiones"]][:3] == ["iniciar", "suficiencia", "asumir"]
    assert all(c["hash_despues"] == h for c in est["control_versiones"][-5:])


def test_bloque_estado_exacto(m):
    m.iniciar()
    _, out = m.run("estado")
    bloque = out[out.index("=== ESTADO PREVENTA ==="):].strip().splitlines()
    claves = [ln.split(":")[0] for ln in bloque[1:-1]]
    assert claves == ["codigo", "estado", "version", "hash_contenido", "intentos", "expertos", "verificacion",
                      "decisiones", "SIGUIENTE PASO OBLIGATORIO"]
    assert bloque[5] == "intentos: T1 0/3 · T2 0/3 · T3 0/3 · T4 0/3" and bloque[-1] == "=== FIN ESTADO ==="


def test_sin_estado(m):
    rc, out = m.run("estado")
    assert rc == 0 and "estado: SIN_ESTADO" in out
    rc, out = m.run("suficiencia", "--requisitos", "entrada/requisitos.json")
    assert rc == 2 and "FALLO [EntradaInvalida] rc=2" in out


@pytest.mark.parametrize("args", [
    ["enrutar"], ["consolidar"], ["anexo-consumo"], ["paquete"], ["asumir", "--campo", "plazo", "--valor", "seis semanas"],
    ["estimar"], ["registrar-verificacion", "--respuesta", "entrada/x.json"],
    ["registrar-experto", "--experto", "azure", "--respuesta", "entrada/x.json"],
])
def test_fuera_de_orden_desde_borrador(m, args):
    m.iniciar()
    antes = (m.raiz / "estado.json").read_bytes()
    rc, out = m.run(*args)
    assert rc == 3 and "FALLO [TransicionNoPermitida] rc=3" in out and "estado: BORRADOR" in out
    assert (m.raiz / "estado.json").read_bytes() == antes  # rc 3: no se guarda nada


def test_iniciar_no_pisa_y_valida_alta(m):
    m.iniciar()
    rc, out = m.iniciar()
    assert rc == 3 and "no lo pisa" in out


@pytest.mark.parametrize("cambio, error", [
    (["--seqof", "1"], "--seqof"), (["--codigo-cliente", "kel vara"], "--codigo-cliente"),
    (["--sensible", "ab"], "menos de 3"), (["--transcripcion", "no_existe.txt"], "adjunto"),
])
def test_iniciar_rechaza(m, cambio, error):
    args = ["iniciar", "--cliente", "Kelvara", "--codigo-cliente", "KELVARA", "--seqof", "001", "--titulo",
            "Título de prueba", "--transcripcion", ADJUNTO, "--sensible", "Kelvara", "--nda-confirmado"]
    i = args.index(cambio[0])
    if cambio[0] == "--sensible":
        args += cambio
    else:
        args[i + 1] = cambio[1]
    rc, out = m.run(*args)
    assert rc == 2 and error in out and not (m.raiz / "estado.json").exists()


def test_iniciar_sin_nda(m):
    rc, out = m.run("iniciar", "--cliente", "Kelvara", "--codigo-cliente", "KELVARA", "--seqof", "001", "--titulo",
                    "Título de prueba", "--transcripcion", ADJUNTO, "--sensible", "Kelvara")
    assert rc == 2 and "--nda-confirmado" in out


def test_cita_inventada_cuenta_intento_y_bloquea_a_la_tercera(m):
    m.iniciar()
    req = m.requisitos_modelo()
    req["campos"]["plazo"]["entradas"][0]["cita"] = "tener el piloto funcionando en unos cuatro meses desde que arranquemos"
    ruta = m.entrada("requisitos.json", req)
    for n in (1, 2):
        rc, out = m.run("suficiencia", "--requisitos", ruta)
        assert rc == 1 and f"intento {n}/3" in out and "estado: BORRADOR" in out and "plazo.entradas[0]" in out
        assert m.estado()["carga"]["requisitos"] is None
    rc, out = m.run("suficiencia", "--requisitos", ruta)
    assert rc == 1 and "estado: BLOQUEADA" in out and "motivo_bloqueo: T1 agotó 3/3" in out
    rc, out = m.run("enrutar")
    assert rc == 3 and "BLOQUEADA" in out
    h = m.hash()
    rc, out = m.run("decision", "--linea", m.linea("Responsable comercial", "DESBLOQUEAR", "Cita corregida a mano"))
    assert rc == 0 and "estado: BORRADOR" in out and "T1 0/3" in out and m.hash() == h


def test_asumido_escrito_por_el_modelo_se_rechaza(m):
    m.iniciar()
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", ejemplo("requisitos")))
    assert rc == 1 and "ASUMIDO solo lo fija el comercial" in out and "intento 1/3" in out


def test_otra_nube_fuera_de_i1(m):
    m.iniciar()
    req = m.requisitos_modelo()
    req["campos"]["nubes"]["entradas"][0]["valor"] = "AWS"
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))
    assert rc == 1 and "fuera de I1" in out


def test_falta_bloqueante_pregunta(m):
    m.iniciar()
    req = m.requisitos_modelo()
    req["campos"]["marco_normativo"] = {"estado": "CITADO", "entradas": []}
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req))
    assert rc == 1 and "marco_normativo: ¿" in out and m.estado()["carga"]["requisitos"]["campos"]["marco_normativo"]["estado"] == "FALTA"
    rc, out = m.run("asumir", "--campo", "marco_normativo", "--valor", "RGPD")
    assert rc == 2 and "BLOQUEANTE" in out


def test_json_ilegible_cuenta_intento(m):
    m.iniciar()
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", "{no es json"))
    assert rc == 1 and "intento 1/3" in out and "T1 1/3" in out


def test_aclaracion_como_fuente(m):
    m.iniciar()
    req = m.requisitos_modelo()
    req["campos"]["volumetria"] = {"estado": "CITADO", "entradas": [
        {"valor": "Unos 150 técnicos", "cita": "seremos unos ciento cincuenta técnicos", "fuente": "F2", "origen": "ACLARACION"}]}
    acl = m.entrada("aclaracion_1.txt", "El comercial: seremos unos ciento cincuenta técnicos en total.")
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", req), "--aclaracion", acl)
    assert rc == 1 and "Aclaraciones registradas como fuentes: F2" in out and "Faltan: identidad_acl_origen" in out
    assert [f["tipo"] for f in m.estado()["carga"]["fuentes"]] == ["TRANSCRIPCION", "ACLARACION"]
