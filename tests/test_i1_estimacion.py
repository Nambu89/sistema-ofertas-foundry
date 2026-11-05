"""Pruebas de sandbox/nucleo/estimacion.py (constructor B). Sin red.

Las pruebas marcadas con el generador ejecutan el generador canónico REAL en local, sin
modificarlo, y exigen --verificar rc 0 (se saltan si no está en este puesto).
"""
from __future__ import annotations

import copy
import json
import pathlib
from datetime import date
from decimal import Decimal

import pytest

from tests.test_i1_estimacion_comun import (CANONICO, TARIFA, ejemplo, aislar, estado_base, preparar_nucleo,
                                            sha256_fichero)

M = preparar_nucleo()
E, errores, hashes = M["estimacion"], M["errores"], M["hashes"]


@pytest.fixture(autouse=True)
def _aislado(monkeypatch):
    aislar(monkeypatch)

HAY_GENERADOR = (CANONICO / E.GENERADOR).is_file() and (CANONICO / E.PLANTILLA).is_file()
con_generador = pytest.mark.skipif(not HAY_GENERADOR, reason="generador canónico no disponible en este puesto")


@pytest.fixture()
def tarifa() -> dict:
    return E.cargar_tarifa(TARIFA)


@pytest.fixture()
def estado() -> dict:
    return estado_base()


@pytest.fixture()
def entrada() -> dict:
    return ejemplo("estimacion_entrada")


def _rutas(tmp_path: pathlib.Path, **extra) -> E.RutasGenerador:
    return E.RutasGenerador(generador=CANONICO / E.GENERADOR, plantilla=CANONICO / E.PLANTILLA,
                            rate_card=TARIFA, base_tmp=tmp_path / "base", **extra)


def _tarifa_fichero(tmp_path: pathlib.Path, cambio) -> pathlib.Path:
    snap = json.loads(TARIFA.read_text(encoding="utf-8"))
    cambio(snap["tarifa"])
    ruta = tmp_path / "rate-card.json"
    ruta.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    return ruta


# ── Tarifa ──────────────────────────────────────────────────────────────────

def test_tarifa_v4_siete_perfiles_sin_contingencia(tarifa):
    assert len(E.perfiles(tarifa)) == 7 and E.PERFIL_PM in E.perfiles(tarifa)
    assert tarifa["contingencia_porcentaje"] == 0
    assert [h["nombre"] for h in E.hitos_tarifa(tarifa)][0] == "Hito 1 - Kick-off y Discovery completado"


@pytest.mark.parametrize("cambio", [
    lambda t: t.__setitem__("contingencia_porcentaje", 15),
    lambda t: t["perfiles"].append(dict(t["perfiles"][0])),
    lambda t: t.__setitem__("perfiles", []),
    lambda t: t["hitos_pago"][0].__setitem__("porcentaje", 30),
])
def test_tarifa_rechazada(tmp_path, cambio):
    with pytest.raises(errores.IntegridadRota):
        E.cargar_tarifa(_tarifa_fichero(tmp_path, cambio))


def test_tarifa_ilegible(tmp_path):
    (tmp_path / "x.json").write_text("{no", encoding="utf-8")
    with pytest.raises(errores.EntradaInvalida):
        E.cargar_tarifa(tmp_path / "x.json")


# ── Cálculo ─────────────────────────────────────────────────────────────────

def test_calcular_igual_al_ejemplo_de_p0(entrada, tarifa):
    assert E.calcular(entrada, tarifa) == ejemplo("estado")["carga"]["estimacion"]["resumen"]


def test_holgura_redondeo_excel():
    assert E.horas_tarea(2.5, 1) == Decimal("4.5")      # ROUND(0,5) = 1
    assert E.horas_tarea(12, 0) == Decimal("14")        # ROUND(2,4) = 2
    assert E.horas_tarea(7.5, 0) == Decimal("9.5")      # ROUND(1,5) = 2


def test_un_solo_hito_usa_round(tarifa, entrada):
    t = copy.deepcopy(tarifa)
    t["hitos_pago"] = [{"hito": 1, "porcentaje": 100, "descripcion": "Entrega única"}]
    entrada["hitos"] = E.hitos_tarifa(t)
    res = E.calcular(entrada, t)
    assert res["hitos"][0]["importe_eur"] == res["precio_cerrado_eur"]


# ── Validación (P6) ─────────────────────────────────────────────────────────

def test_entrada_del_ejemplo_valida(entrada, estado, tarifa):
    assert E.validar_entrada(entrada, estado, tarifa, None) == []


def _errores(entrada, estado, tarifa, ajuste=None) -> str:
    return "\n".join(E.validar_entrada(entrada, estado, tarifa, ajuste))


def test_pm_minimo_bloquea(entrada, estado, tarifa):
    entrada["tareas"] = [t for t in entrada["tareas"] if t["perfil"] != E.PERFIL_PM]
    assert "P6a" in _errores(entrada, estado, tarifa)


def test_pm_por_debajo_de_8h(entrada, estado, tarifa):
    pm = next(t for t in entrada["tareas"] if t["id"].startswith("PM-"))
    pm.update(tecnicas_h=4, reuniones_h=2)   # 4 + 1 + 2 = 7 h
    assert "P6a: la gestión de proyecto suma 7.00 h" in _errores(entrada, estado, tarifa)


def test_tarea_pm_con_otro_perfil(entrada, estado, tarifa):
    next(t for t in entrada["tareas"] if t["id"].startswith("PM-"))["perfil"] = "Consultor Junior"
    assert "una tarea PM-nn solo puede ser" in _errores(entrada, estado, tarifa)


def test_tarea_no_trazable(entrada, estado, tarifa):
    entrada["tareas"][0]["tecnicas_h"] += 8
    entrada["tareas"][1]["descripcion"] = "Otra descripción distinta de la propuesta."
    texto = _errores(entrada, estado, tarifa)
    assert "tecnicas_h" in texto and "descripcion" in texto


def test_falta_tarea_propuesta_y_perfil_ajeno(entrada, estado, tarifa):
    del entrada["tareas"][0]
    entrada["tareas"].append(dict(entrada["tareas"][-1], id="PM-02", perfil="Perfil Inventado"))
    texto = _errores(entrada, estado, tarifa)
    assert "faltan tareas_propuestas" in texto and "Perfil Inventado" in texto


def test_hitos_distintos_de_la_tarifa(entrada, estado, tarifa):
    entrada["hitos"][0]["porcentaje"], entrada["hitos"][1]["porcentaje"] = 50, 0.0001
    assert "P6e" in _errores(entrada, estado, tarifa)


def test_contexto_de_t4(entrada, estado, tarifa):
    estado["carga"]["anexo_consumo"] = None
    estado["carga"]["verificacion"]["resultado"]["verificada"] = False
    texto = _errores(entrada, estado, tarifa)
    assert "falta el anexo" in texto and "P5" in texto


def test_codigo_cliente_y_marcadores(entrada, estado, tarifa):
    entrada["codigo"] = "OF-KELVARA-001-B"
    entrada["asunciones"] = ["El acceso al tenant está pendiente de confirmar."]
    entrada["exclusiones"] = ["Soporte con contingencia del 15 %."]
    texto = _errores(entrada, estado, tarifa)
    assert "codigo" in texto and "P9" in texto and "P6c" in texto


def test_palabra_que_contiene_pendiente_no_es_marcador(entrada, estado, tarifa):
    entrada["asunciones"] = ["El verificador es independiente del experto."]
    errores_ = E.validar_entrada(entrada, estado, tarifa, None)
    # REV-1: una asunción que no es la de la regla se rechaza por P6f, pero no por marcador (P9)
    assert [e[:15] for e in errores_] == ["P6f asunciones:"] and not any("P9" in e for e in errores_)


# ── Ajuste comercial (P6c) ──────────────────────────────────────────────────

def _decision_ajuste(estado, importe="-500.00", hash_citado=None, did="D-001") -> dict:
    d = {"id": did, "linea": "DECISION | Responsable comercial | AJUSTE_COMERCIAL | 2026-10-08 | h | c",
         "revisor": "Responsable comercial", "tipo": "AJUSTE_COMERCIAL", "fecha": "2026-10-08",
         "hash_citado": hash_citado or hashes.hash_contenido(estado),
         "comentarios": f"importe_eur={importe}; motivo=Descuento por volumen acordado con el cliente",
         "version": "A", "estado_antes": "VERIFICADA", "estado_despues": "VERIFICADA",
         "registrada_ts": "2026-10-08T12:00:00+02:00"}
    estado["decisiones"].append(d)
    return d


def test_ajuste_sin_decision_rechazado(entrada, estado, tarifa):
    entrada["ajuste_comercial_eur"] = -500
    entrada["ajuste_comercial_motivo"] = "Descuento por volumen acordado con el cliente"
    texto = _errores(entrada, estado, tarifa)
    assert "sin decisión AJUSTE_COMERCIAL" in texto and "motivo sin ajuste" in texto


def test_ajuste_con_decision_vigente(entrada, estado, tarifa):
    d = _decision_ajuste(estado)
    entrada["ajuste_comercial_eur"] = -500.0
    entrada["ajuste_comercial_motivo"] = "Descuento por volumen acordado con el cliente"
    assert E.validar_entrada(entrada, estado, tarifa, d) == []
    entrada["ajuste_comercial_eur"] = -400
    assert "la decisión dice -500.00" in _errores(entrada, estado, tarifa, d)


def test_ajuste_con_hash_vencido(entrada, estado, tarifa):
    d = _decision_ajuste(estado, hash_citado="0" * 64)
    entrada["ajuste_comercial_eur"] = -500
    entrada["ajuste_comercial_motivo"] = "Descuento por volumen acordado con el cliente"
    assert "vigente" in _errores(entrada, estado, tarifa, d)


def test_leer_ajuste_forma_exacta():
    assert E.leer_ajuste({"comentarios": "importe_eur=-1500.00; motivo=Descuento por volumen"}) == \
        (Decimal("-1500.00"), "Descuento por volumen")
    with pytest.raises(ValueError):
        E.leer_ajuste({"comentarios": "importe_eur=-1500; motivo=Descuento por volumen"})


# ── Lectura de la salida del generador ──────────────────────────────────────

def test_leer_salida_generador():
    texto = ("Subtotal servicios: 17.852,50 €\nPRECIO CERRADO (IVA no incluido): 17.852,50 €\nHitos:\n"
             "  - Hito 1 - Kick-off: con dos puntos: 25 % = 4.463,13 €\n  - Hito 2 - Cierre: 75 % = 13.389,37 €\n"
             "\nVerificación del XLSX generado: OK")
    leido = E.leer_salida_generador(texto)
    assert leido["precio_cerrado_eur"] == "17852.50"
    assert leido["hitos"] == [{"nombre": "Hito 1 - Kick-off: con dos puntos", "importe_eur": "4463.13"},
                              {"nombre": "Hito 2 - Cierre", "importe_eur": "13389.37"}]
    with pytest.raises(errores.IntegridadRota):
        E.leer_salida_generador("sin precio")


def test_comparar_detecta_diferencias(entrada, tarifa):
    res = E.calcular(entrada, tarifa)
    assert len(E.comparar(res, {"precio_cerrado_eur": "1.00", "hitos": []}, "x")) == 2


# ── Generador canónico real (sin modificarlo) ───────────────────────────────

@con_generador
def test_estimar_con_generador_real(tmp_path, entrada, estado, tarifa):
    sha_gen, sha_pla = sha256_fichero(CANONICO / E.GENERADOR), sha256_fichero(CANONICO / E.PLANTILLA)
    rutas = _rutas(tmp_path, sha256_generador=sha_gen, sha256_plantilla=sha_pla)
    r = E.estimar(estado, entrada, tarifa, rutas, tmp_path / "salida", None)
    assert r.resumen["precio_cerrado_eur"] == "28025.25" and r.stop is False
    assert "Verificación del XLSX generado: OK" in r.salida_generador and "--verificar" in r.salida_generador
    assert r.ruta_xlsx.name == "OF-KELVARA-001-A-Estimacion.xlsx" and sha256_fichero(r.ruta_xlsx) == r.xlsx_sha256
    assert E.comparar(r.resumen, E.leer_xlsx(r.ruta_xlsx), "xlsx") == []
    assert estado["carga"]["estimacion"]["resumen"] == r.resumen and estado["carga"]["textos_cliente"] is None
    assert estado["carga"]["estimacion"]["ajuste"] is None
    assert estado["artefactos"]["xlsx_estimacion"]["sha256"] == r.xlsx_sha256
    assert sorted(p.name for p in (tmp_path / "salida").iterdir()) == [r.ruta_xlsx.name]
    assert list((tmp_path / "base").iterdir()) == []          # el árbol temporal se borra
    assert (sha256_fichero(CANONICO / E.GENERADOR), sha256_fichero(CANONICO / E.PLANTILLA)) == (sha_gen, sha_pla)


@con_generador
def test_generar_xlsx_directo_pasa_verificar(tmp_path, entrada):
    sha = E.generar_xlsx(entrada, _rutas(tmp_path), tmp_path / "a.xlsx")
    assert sha == sha256_fichero(tmp_path / "a.xlsx")


@con_generador
def test_estimar_entrada_invalida_no_muta(tmp_path, entrada, estado, tarifa):
    entrada["tareas"] = [t for t in entrada["tareas"] if t["perfil"] != E.PERFIL_PM]
    antes = copy.deepcopy(estado)
    with pytest.raises(errores.ReglaIncumplida) as ex:
        E.estimar(estado, entrada, tarifa, _rutas(tmp_path), tmp_path / "salida", None)
    assert any("P6a" in e for e in ex.value.errores)
    assert estado == antes and not (tmp_path / "salida").exists()


@con_generador
def test_sha_del_generador_distinto_del_manifiesto(tmp_path, entrada, estado, tarifa):
    antes = copy.deepcopy(estado)
    with pytest.raises(errores.IntegridadRota):
        E.estimar(estado, entrada, tarifa, _rutas(tmp_path, sha256_generador="0" * 64), tmp_path / "salida", None)
    assert estado == antes


@con_generador
def test_estimar_con_ajuste_decidido(tmp_path, entrada, estado, tarifa):
    _decision_ajuste(estado)
    entrada["ajuste_comercial_eur"] = -500
    entrada["ajuste_comercial_motivo"] = "Descuento por volumen acordado con el cliente"
    hash_antes = hashes.hash_contenido(estado)
    r = E.estimar(estado, entrada, tarifa, _rutas(tmp_path), tmp_path / "salida", "D-001")
    assert (r.resumen["ajuste_eur"], r.resumen["precio_cerrado_eur"]) == ("-500.00", "18072.50")
    assert estado["carga"]["estimacion"]["ajuste"] == {"decision_id": "D-001", "importe_eur": "-500.00",
                                                       "motivo": "Descuento por volumen acordado con el cliente",
                                                       "hash_base": hash_antes}
    assert E.leer_xlsx(r.ruta_xlsx)["ajuste_eur"] == "-500.00"


def test_estimar_con_decision_inexistente(tmp_path, entrada, estado, tarifa):
    with pytest.raises(errores.ReglaIncumplida) as ex:
        E.estimar(estado, entrada, tarifa, _rutas(tmp_path), tmp_path / "salida", "D-009")
    assert any("no existe la decisión D-009" in e for e in ex.value.errores)


@con_generador
def test_stop_por_encima_de_100000(tmp_path, entrada, estado, tarifa):
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    for p in resp["tareas_propuestas"]:
        p["horas_base"] = 400
    entrada = E.componer_entrada(estado, E.hitos_tarifa(tarifa), date.fromisoformat(entrada["fecha"]))[0]  # REV-1
    r = E.estimar(estado, entrada, tarifa, _rutas(tmp_path), tmp_path / "salida", None)
    assert Decimal(r.resumen["precio_cerrado_eur"]) > E.UMBRAL_STOP_EUR and r.stop is True
    assert E.requiere_stop(estado) is True
    estado["decisiones"].append({"id": "D-001", "tipo": "CONFIRMA_STOP", "hash_citado": hashes.hash_contenido(estado)})
    assert E.requiere_stop(estado) is False
    estado["decisiones"][-1]["hash_citado"] = "f" * 64          # hash vencido: vuelve a parar
    assert E.requiere_stop(estado) is True


@con_generador
def test_medio_centimo_no_rompe_el_contraste(tmp_path, entrada, estado, tarifa):
    """Precio 18.735,625: el generador imprime 18.735,62 (redondeo al par) y la réplica 18735.63."""
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    resp["tareas_propuestas"][0]["horas_base"] = 25.5
    entrada = E.componer_entrada(estado, E.hitos_tarifa(tarifa), date.fromisoformat(entrada["fecha"]))[0]  # REV-1
    r = E.estimar(estado, entrada, tarifa, _rutas(tmp_path), tmp_path / "salida", None)
    assert r.resumen["precio_cerrado_eur"] == "18735.63"
    assert "PRECIO CERRADO (IVA no incluido): 18.735,62 €" in r.salida_generador
    assert E.comparar(r.resumen, E.leer_xlsx(r.ruta_xlsx), "xlsx") == []
    assert E.comparar(r.resumen, E.leer_salida_generador(r.salida_generador), "g") != []   # sin tolerancia sí difiere
