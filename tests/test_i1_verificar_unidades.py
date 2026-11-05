"""Pruebas unitarias de las utilidades de verificar_paquete.py y de lib/auditoria.py (papel E, I1)."""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

import verificar_paquete as vp
from lib import auditoria
from lib.evidencia import EvidenciaConSecreto


def test_importes_en_formatos_es_y_punto():
    assert vp.importes_en("Precio: 17.852,50 EUR y 4.463,13 EUR") == {Decimal("17852.50"), Decimal("4463.13")}
    assert vp.importes_en("Total 340.33 EUR; 1,234.56") == {Decimal("340.33"), Decimal("1234.56")}
    assert vp.importes_en("12 semanas, 25 %") == set()


def test_barrido_cliente():
    perfiles = ["Project Manager", "AI Architect / Tech Lead"]
    assert vp.barrer_replica("Precio cerrado de 17.852,50 EUR, IVA no incluido. 4 hitos.", perfiles) == []
    for texto in ("Total 279 h", "Dos jornadas", "65 EUR/h", "La tarifa", "un project manager",
                  "AI Architect / Tech Lead", "contingencia del 5", "ajuste comercial", "ver C-01",
                  "fichero estado.json", "nombre_tecnico", "correo a x@y.com"):
        assert vp.barrer_replica(texto, perfiles), texto


def test_normalizar_cita_quita_marcas_vtt():
    vtt = "WEBVTT\n\nNOTE comentario\n\n1\n00:00:01.000 --> 00:00:04.000\n<v Iker Salaverri>Queremos que esto viva en Azure.</v>\n"
    norm = vp.texto_cita_normalizado(vtt)
    assert norm == "queremos que esto viva en azure."
    assert vp.cita_valida("Queremos que ESTO viva en Azure", norm)[0]
    assert not vp.cita_valida("viva en Azure", norm)[0]          # menos de 15 caracteres o 3 palabras


def test_normalizar_url_y_lista_blanca():
    assert vp._norm_url("https://learn.microsoft.com/es-es/Azure/Search/Overview/?x=1#a") == "/azure/search/overview"
    assert vp._norm_url("http://learn.microsoft.com/azure/search") is None
    assert vp._norm_url("https://learn.microsoft.com.evil.com/azure/search") is None
    assert vp._prefijo("/azure/architecture/x", vp.PREF_ARQ)
    assert not vp._prefijo("/azure/architecturex", vp.PREF_ARQ)


def test_objetos_json_anidados():
    valor = json.dumps({"a": json.dumps({"brief_id": "BRF-X", "agente": "y"})})
    assert any(o.get("brief_id") == "BRF-X" for o in vp._objetos_json(valor))


def test_kql_literal_rechaza_inyeccion():
    assert vp._kql_literal("BRF-OF-KELVARA-001-A-AZ-R1") == '"BRF-OF-KELVARA-001-A-AZ-R1"'
    with pytest.raises(ValueError):
        vp._kql_literal('x" | take 1')


@pytest.mark.parametrize("entrada,salida", [("../../etc/passwd", "passwd"), ("a\\b\\c.zip", "c.zip"),
                                            ("informe: final?.xlsx", "informe_ final_.xlsx")])
def test_sanear_nombre(entrada, salida):
    assert auditoria.sanear_nombre(entrada) == salida


@pytest.mark.parametrize("malo", ["", "..", "CON", "nul.txt", " . "])
def test_sanear_nombre_rechaza(malo):
    with pytest.raises(auditoria.NombreNoValido):
        auditoria.sanear_nombre(malo)


def test_ruta_contenida(tmp_path):
    assert auditoria.ruta_contenida(tmp_path, "../x.zip") == (tmp_path / "x.zip").resolve()


def test_anadir_linea_solo_anade(tmp_path):
    log = tmp_path / "_audit" / "log.jsonl"
    log.parent.mkdir()
    log.write_text('{"previa": 1}', encoding="utf-8")            # sin salto final
    linea = auditoria.linea_auditoria(cliente="Kelvara", codigo="OF-KELVARA-001-A", version="A",
                                      estado="LISTA_PARA_REVISION", hash_contenido="a" * 64,
                                      precio_cerrado_eur="17852.50", horas_total="279.00",
                                      zip_nombre="p.zip", zip_sha256="b" * 64, destino="d", veredicto="OK",
                                      ts="2026-10-08T10:00:00Z", usuario="usuario")
    auditoria.anadir_linea(log, linea)
    filas = log.read_text(encoding="utf-8").splitlines()
    assert filas[0] == '{"previa": 1}' and json.loads(filas[1])["total_eur"] == 17852.5


def test_anadir_linea_rechaza_tokens(tmp_path):
    linea = {"x": "eyJ" + "a" * 40 + "." + "b" * 20 + "." + "c" * 20}
    with pytest.raises(EvidenciaConSecreto):
        auditoria.anadir_linea(tmp_path / "log.jsonl", linea)
    assert not (tmp_path / "log.jsonl").exists()


# ───────────────── I1.1 · papel G: importes, horas de servicio y confirmaciones locales ─────────────────

@pytest.mark.parametrize("texto,literal,valor", [
    ("Precio cerrado\n19.990,00 €", "19.990,00", Decimal("19990.00")),
    ("Precio cerrado\n19.990 €", "19.990", Decimal("19990")),       # sin decimales: lo que esquivaba _IMPORTE
    ("Total: EUR 22548.75", "22548.75", None),                      # formato no español: sin lectura
    ("22,548.75 euros", "22,548.75", None),
])
def test_cifras_monetarias_ve_cualquier_formato(texto, literal, valor):
    vistos = vp.cifras_monetarias(texto)
    assert any(lit == literal and (lect == {valor} if valor is not None else not lect) for lit, lect in vistos), vistos


def test_cifra_ambigua_solo_tiene_la_lectura_espanola():
    """Revisión de la revisión independiente: «19.990» no puede casar con un precio de 19,99 por la lectura inglesa."""
    assert vp.lecturas_numero("19.990") == {Decimal("19990")}
    assert vp.lecturas_numero("19,990") == set() and vp.lecturas_numero("1.5") == set()
    assert vp.lecturas_numero("22.548,75") == {Decimal("22548.75")}


def test_cifras_monetarias_no_pega_porcentajes_ni_celdas_vecinas():
    texto = "Hito 1 - Arranque\n30 %\n5.355,75 €\nHito 2 - Entrega\n33.33 %\n100 %"
    vistos = vp.cifras_monetarias(texto)
    assert [lit for lit, _ in vistos] == ["5.355,75", "5.355,75"], vistos   # moneda y dos decimales
    assert vp.cifras_sueltas("Duración: 12 semanas · validez 30 días") == []
    assert [x for x, _ in vp.cifras_sueltas("Precio cerrado 19990")] == ["19990"]


@pytest.mark.parametrize("texto,servicios,exime", [
    ("Azure AI Search: 730 horas mensuales de funcionamiento", ["Azure AI Search"], True),
    ("Microsoft Foundry disponible 24 horas al día", ["Microsoft Foundry"], True),
    ("Azure AI Search: 730 horas mensuales", [], False),                                  # sin servicio con fuente
    ("Dedicación del equipo: 160 horas mensuales con Azure AI Search", ["Azure AI Search"], False),  # esfuerzo
    ("Azure AI Search: 1.000 horas mensuales", ["Azure AI Search"], False),               # no cabe en un mes
    ("Azure AI Search: 800 horas mensuales", ["Azure AI Search"], False),
    ("Azure AI Search y 120 horas de soporte", ["Azure AI Search"], False),               # horas sin periodo
])
def test_horas_de_servicio_frente_a_horas_de_esfuerzo(texto, servicios, exime):
    hallazgos = [h for h in vp.barrer_replica(vp.enmascarar_horas_servicio(texto, servicios), []) if "hora" in h]
    assert (not hallazgos) is exime, hallazgos


class _Ctx:
    def __init__(self, vigente: str, **kw):
        self._h, self.confirmo_stop, self.confirmo_ajuste = vigente, kw.get("stop"), kw.get("ajuste")
        self.estado = kw.get("estado", {})

    def hash_vigente(self) -> str:
        return self._h


@pytest.mark.parametrize("dado,exigido,estado,motivo", [
    (None, True, "FALLA", "exige --confirmo-ajuste " + "a" * 64),
    ("b" * 64, True, "FALLA", "no es el hash vigente"),
    ("b" * 64, False, "FALLA", "confirma otro contenido"),
    ("A" * 64, True, "OK", "confirmado en local"),        # sin distinguir mayúsculas
    ("a" * 64, False, "AVISO", "dado sin que haga falta"),
    (None, False, "OK", ""),
])
def test_confirmacion_local_r2(dado, exigido, estado, motivo):
    c = vp.Comprobacion("estimacion", "x")
    vp._confirmacion_local(_Ctx("a" * 64), c, "--confirmo-ajuste", dado, exigido, "ajuste comercial de -1000 EUR")
    assert c.estado == estado and motivo in " ".join(c.detalles), c.detalles


@pytest.mark.parametrize("respaldo,estado,motivo", [
    ("D-007 (ajuste -1000.00 EUR; huella de la línea ffff…)", "OK", "respaldado por D-007 (ajuste -1000.00 EUR"),
    (None, "FALLA", "no hay una decisión trazada que lo respalde (ajuste comercial de -1000 EUR)"),
])
def test_confirmacion_local_exige_decision_trazada_r4(respaldo, estado, motivo):
    c = vp.Comprobacion("estimacion", "x")
    vp._confirmacion_local(_Ctx("a" * 64), c, "--confirmo-ajuste", "a" * 64, True, "ajuste comercial de -1000 EUR",
                           respaldo=respaldo)
    assert c.estado == estado and motivo in " ".join(c.detalles), c.detalles


def test_respaldo_describe_la_decision():
    assert vp._respaldo(None, "x") is None
    r = vp._respaldo({"id": "D-001", "linea": "DECISION | Responsable comercial | CONFIRMA_STOP | …"}, "precio 104252.50 EUR")
    assert r.startswith("D-001 (precio 104252.50 EUR; huella de la línea ") and r.endswith("…)")


def test_hechos_fijos_lista_cerrada():
    assert "FIJO-X" not in vp.HECHOS_FIJOS and {"FIJO-SOPORTE", "FIJO-EXCLUSIONES", "FIJO-CONDICIONES"} <= vp.HECHOS_FIJOS
    assert not hasattr(vp, "_HECHO_FIJO")


def test_veredicto_estricto():
    assert vp.veredicto(3, ["procedencia_a2a"]) == "NO VERIFICADO CON --estricto"
    assert vp.veredicto(0, ["procedencia_a2a"]) == "OK CON NO VERIFICADOS" and vp.veredicto(1, []) == "FALLA"
