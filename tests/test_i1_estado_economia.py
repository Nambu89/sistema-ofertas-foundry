"""Pruebas de T4, decisiones, registrar-fallo, restaurar y montaje (papel BA). Sin red."""
from __future__ import annotations

import datetime
import json
import shutil
import zipfile

import pytest

from tests.test_i1_estado_comun import ADJUNTO, Mundo, ejemplo, estado, hashes


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


F, J, JP = "Responsable comercial", "Responsable de preventa", "Responsable de área"


def test_orden_t4(m):
    m.hasta_verificada()
    rc, out = m.run("estimar")
    assert rc == 3 and "Primero anexo-consumo" in out
    rc, out = m.run("paquete")
    assert rc == 3
    m.run("anexo-consumo")
    rc, out = m.run("paquete")
    assert rc == 3 and "estado: VERIFICADA" in out


def test_estimacion_invalida_cuenta_t4(m):
    m.hasta_verificada()
    m.run("anexo-consumo")
    m.dobles["estimacion"].ERRORES[:] = ["P6a: gestión de proyecto 6.00 h < 8 h"]
    rc, out = m.run("estimar")
    assert rc == 1 and "T4 1/3" in out and "P6a" in out and m.estado()["carga"]["estimacion"] is None


def test_stop_presupuesto_y_confirmacion(m):
    m.hasta_verificada()
    m.run("anexo-consumo")
    m.dobles["estimacion"].PRECIO = "120000.00"
    rc, out = m.run("estimar")
    assert rc == 1 and "estado: STOP_PRESUPUESTO" in out and f"CONFIRMA_STOP | AAAA-MM-DD | {m.hash()} | motivo" in out
    rc, out = m.run("paquete")
    assert rc == 3
    rc, out = m.run("decision", "--linea", m.linea(F, "CONFIRMA_STOP", "corto"))
    assert rc == 1 and "al menos 10" in out
    rc, out = m.run("decision", "--linea", m.linea(F, "CONFIRMA_STOP", "Cliente acepta el importe del piloto"))
    assert rc == 0 and "estado: VERIFICADA" in out
    rc, out = m.run("estimar")  # misma entrada: la confirmación sigue valiendo
    assert rc == 0 and "estado: VERIFICADA" in out
    assert m.run("paquete")[0] == 0


def test_ajuste_comercial_solo_con_decision_vigente(m):
    m.hasta_verificada()
    m.run("anexo-consumo")
    rc, out = m.run("estimar", "--aplicar-ajuste", "D-001")
    assert rc == 1 and "no es la decisión AJUSTE_COMERCIAL vigente" in out
    rc, out = m.run("decision", "--linea", m.linea(F, "AJUSTE_COMERCIAL", "importe_eur=-1500; motivo=Descuento por volumen"))
    assert rc == 1 and "dos decimales" in out
    linea = m.linea(F, "AJUSTE_COMERCIAL", "importe_eur=-1500.00; motivo=Descuento por volumen acordado")
    assert m.run("decision", "--linea", linea)[0] == 0
    rc, out = m.run("estimar", "--aplicar-ajuste", "D-001")
    assert rc == 0 and m.dobles["estimacion"].LLAMADAS[-1]["ajuste"] == "D-001"


def test_decisiones_rechazadas(m):
    m.hasta_lista()
    h = m.hash()
    rc, out = m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0", h="0" * 64))
    assert rc == 1 and f"decisión rechazada: cita {'0' * 64}, vigente {h}" in out
    rc, out = m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "enviado sin verificar"))
    assert rc == 1 and "verificar_paquete rc=0" in out
    manana = (estado.hoy() + datetime.timedelta(days=1)).isoformat()
    rc, out = m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0", fecha=manana))
    assert rc == 1 and "fecha futura" in out
    rc, out = m.run("decision", "--linea", m.linea(J, "APROBADA", "ok"))
    assert rc == 3 and "no admitida en el estado LISTA_PARA_REVISION" in out
    rc, out = m.run("decision", "--linea", m.linea("Pepe Pérez", "ENVIADA_REVISION", "verificar_paquete rc=0"))
    assert rc == 2 and "revisor desconocido" in out
    assert m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))[0] == 0
    rc, out = m.run("decision", "--linea", m.linea(JP, "APROBADA", "aprobado"))
    assert rc == 1 and "la decide Responsable de preventa" in out
    assert len(m.estado()["decisiones"]) == 1 and m.hash() == h


def test_devuelta_sube_version_y_anula_estimacion(m):
    m.hasta_lista()
    m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))
    rc, out = m.run("decision", "--linea", m.linea(J, "DEVUELTA", "corto"))
    assert rc == 1
    rc, out = m.run("decision", "--linea", m.linea(J, "DEVUELTA", "Revisar el precio del índice de búsqueda"))
    assert rc == 0 and "estado: DEVUELTA_CON_COMENTARIOS" in out and "codigo: OF-KELVARA-001-B" in out
    assert "SIGUIENTE PASO OBLIGATORIO: Versión B." in out
    est = m.estado()
    assert est["carga"]["estimacion"] is None and est["carga"]["textos_cliente"] is None and est["ronda_verificacion"] == 0
    rc, out = m.run("estimar")
    assert rc == 0 and "estado: VERIFICADA" in out and m.dobles["estimacion"].LLAMADAS[-1]["codigo"] == "OF-KELVARA-001-B"
    assert m.run("paquete")[0] == 0 and (m.raiz / "salida" / "OF-KELVARA-001-B-Paquete.zip").is_file()


def test_devuelta_y_reanalisis(m):
    m.hasta_lista()
    m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))
    m.run("decision", "--linea", m.linea(J, "APROBADA", "ok"))
    m.run("decision", "--linea", m.linea(JP, "DEVUELTA", "Hay que revisar la arquitectura de red"))
    rc, out = m.run("enrutar")
    assert rc == 0 and "BRF-OF-KELVARA-001-B-AZ-R1" in out and "estado: EN_ANALISIS" in out


def test_registrar_fallo_cuenta_y_bloquea_sin_tocar_el_hash(m):
    m.hasta_analisis()
    h = m.hash()
    for n in (1, 2):
        rc, out = m.run("registrar-fallo", "--fase", "T2", "--error", "HTTP 424 tool_server_error", "--hipotesis",
                        "El experto falló dentro de la herramienta A2A")
        assert rc == 0 and f"T2 intento {n}/3" in out
    rc, out = m.run("registrar-fallo", "--fase", "T2", "--error", "HTTP 424 tool_server_error", "--hipotesis", "Otra vez")
    assert rc == 1 and "estado: BLOQUEADA" in out and m.hash() == h
    est = m.estado()
    assert [f["intento"] for f in est["fallos"]] == [1, 2, 3] and est["fallos"][0]["error"] == "HTTP 424 tool_server_error"
    rc, out = m.run("registrar-fallo", "--fase", "T2", "--error", "HTTP 400", "--hipotesis", "sigue bloqueada")
    assert rc == 1 and "estado: BLOQUEADA" in out and len(m.estado()["fallos"]) == 4
    rc, out = m.run("registrar-fallo", "--fase", "T9", "--error", "x", "--hipotesis", "y")
    assert rc == 2


def test_registrar_fallo_no_en_aprobada(m):
    m.hasta_lista()
    for linea in (m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"), m.linea(J, "APROBADA", "ok")):
        m.run("decision", "--linea", linea)
    m.run("decision", "--linea", m.linea(JP, "APROBADA", "ok"))
    rc, out = m.run("registrar-fallo", "--fase", "T4", "--error", "HTTP 400", "--hipotesis", "corte")
    assert rc == 3 and "estado: APROBADA" in out


def _adjuntar_ancla(m, destino_datos):
    salida = m.raiz / "salida"
    with zipfile.ZipFile(salida / f"{m.estado()['codigo']}-Paquete.zip") as z:
        (destino_datos / "assistant-e1-estado.json").write_bytes(z.read("estado.json"))
        (destino_datos / "assistant-m1-manifiesto_paquete.json").write_bytes(z.read("manifiesto_paquete.json"))


def _contenedor_nuevo(m, tmp_path, monkeypatch):
    nuevo = tmp_path / "data2"
    nuevo.mkdir()
    monkeypatch.setenv("PREVENTA_DATOS", str(nuevo))
    monkeypatch.setenv("PREVENTA_RAIZ", str(nuevo / "preventa"))
    shutil.copy(m.datos / f"assistant-F1x-{ADJUNTO}", nuevo / f"assistant-F1x-{ADJUNTO}")
    m.datos, m.raiz = nuevo, nuevo / "preventa"
    return nuevo


def test_restaurar_con_ancla_externa(m, tmp_path, monkeypatch):
    m.hasta_lista()
    h = m.hash()
    viejo = m.datos
    nuevo = _contenedor_nuevo(m, tmp_path, monkeypatch)
    _adjuntar_ancla(type("X", (), {"raiz": viejo / "preventa", "estado": lambda s: json.loads(
        (viejo / "preventa" / "estado.json").read_text(encoding="utf-8"))})(), nuevo)
    rc, out = m.run("restaurar", "--estado", "estado.json", "--manifiesto", "manifiesto_paquete.json")
    assert rc == 0 and "RESTAURADO" in out and "estado: LISTA_PARA_REVISION" in out and m.hash() == h
    assert (m.raiz / "briefs" / "BRF-OF-KELVARA-001-A-AZ-R1.txt").is_file()
    rc, out = m.run("restaurar", "--estado", "estado.json", "--manifiesto", "manifiesto_paquete.json")
    assert rc == 0  # mismo fichero: idempotente
    assert m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))[0] == 0


@pytest.mark.parametrize("estropear, motivo", [
    ("estado", "distinto de estado_json_sha256"), ("manifiesto_hash", "distinto del hash_contenido del manifiesto"),
    ("carga", "hash recalculado"),
])
def test_restaurar_rechaza(m, tmp_path, monkeypatch, estropear, motivo):
    m.hasta_lista()
    viejo = m.raiz
    nuevo = _contenedor_nuevo(m, tmp_path, monkeypatch)
    with zipfile.ZipFile(viejo / "salida" / "OF-KELVARA-001-A-Paquete.zip") as z:
        est_b, man = z.read("estado.json"), json.loads(z.read("manifiesto_paquete.json"))
    if estropear == "estado":
        est_b = est_b.replace(b'"decisiones": []', b'"decisiones": [ ]')
    elif estropear == "manifiesto_hash":
        man["hash_contenido"] = "f" * 64
    else:
        est = json.loads(est_b)
        est["carga"]["alta"]["titulo"] = "Título manipulado tras el paquete"
        est_b = json.dumps(est, ensure_ascii=False).encode()
        man["estado_json_sha256"] = hashes.sha256_bytes(est_b)
    (nuevo / "x-estado.json").write_bytes(est_b)
    (nuevo / "x-manifiesto_paquete.json").write_text(json.dumps(man), encoding="utf-8")
    rc, out = m.run("restaurar", "--estado", "estado.json", "--manifiesto", "manifiesto_paquete.json")
    assert rc == 4 and motivo in out and not (m.raiz / "estado.json").exists()


def test_paquete_que_falla_deja_el_estado_como_estaba(m):
    m.hasta_verificada()
    m.run("anexo-consumo")
    m.run("estimar")
    antes = m.estado()
    m.dobles["paquete"].FALLAR = True
    rc, out = m.run("paquete")
    despues = m.estado()
    assert rc == 1 and "estado: VERIFICADA" in out
    assert {k: v for k, v in despues.items() if k != "control_versiones"} == {k: v for k, v in antes.items() if k != "control_versiones"}
    ultimo = despues["control_versiones"][-1]
    assert (ultimo["subcomando"], ultimo["estado_antes"], ultimo["estado_despues"]) == ("paquete", "VERIFICADA", "VERIFICADA")


def test_montaje_roto_bloquea_y_da_rc4(m):
    m.hasta_analisis()
    env = m.cli.Entorno(True, m.datos, m.raiz, ["generar_estimacion.py: SHA-256 distinto del manifiesto"])
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m.cli._nucleo()
        rc = m.cli.ejecutar(["enrutar"], env)
    out = buf.getvalue()
    assert rc == 4 and "FALLO [IntegridadRota] rc=4" in out and "estado: BLOQUEADA" in out
    assert "IntegridadRota del montaje" in m.estado()["motivo_bloqueo"]
    with contextlib.redirect_stdout(io.StringIO()):
        assert m.cli.ejecutar(["estado"], env) == 0


def test_estado_manipulado_a_mano_da_rc4(m):
    m.iniciar()
    est = m.estado()
    est["carga"]["alta"]["titulo"] = "Otro título distinto"
    (m.raiz / "estado.json").write_text(json.dumps(est, ensure_ascii=False), encoding="utf-8")
    rc, out = m.run("estado")
    assert rc == 4 and "hash_contenido de estado.json no cuadra" in out


def test_paquete_sin_zip_o_sin_catalogo_no_cambia_el_estado(m):
    m.hasta_verificada()
    m.run("anexo-consumo")
    m.run("estimar")
    antes = (m.raiz / "estado.json").read_bytes()
    original = m.catalogo.read_bytes()
    m.catalogo.unlink()
    rc, out = m.run("paquete")
    assert rc == 4 and (m.raiz / "estado.json").read_bytes() == antes
    m.catalogo.write_bytes(original)
    m.dobles["paquete"].construir = lambda *a, **k: {"ficheros": []}
    rc, out = m.run("paquete")
    assert rc == 4 and "sin escribir" in out and (m.raiz / "estado.json").read_bytes() == antes


def test_p0_detecta_modulo_no_listado(tmp_path, monkeypatch):
    import json as _json
    from tests.test_i1_estado_comun import Mundo as _M
    m = _M(tmp_path, monkeypatch)
    datos = tmp_path / "montado"
    datos.mkdir()
    (datos / "x-nucleo_estado.py").write_text("# a", encoding="utf-8")
    (datos / "x-nucleo_intruso.py").write_text("# b", encoding="utf-8")
    sha = hashes.sha256_fichero(datos / "x-nucleo_estado.py")
    (datos / "x-manifiesto.json").write_text(_json.dumps({"ficheros": {"nucleo_estado.py": {"sha256": sha}}}), encoding="utf-8")
    import sys as _sys
    monkeypatch.setattr(_sys, "path", list(_sys.path))  # preparar_sandbox añade su ruta
    monkeypatch.setattr(m.cli, "APP", tmp_path / "app")
    errores = m.cli.preparar_sandbox(datos)
    assert errores == ["x-nucleo_intruso.py: módulo del núcleo montado que no está en el manifiesto"]


def test_regenerar_no_acepta_un_zip_antiguo(m):
    m.hasta_lista()
    zip_ = m.raiz / "salida" / "OF-KELVARA-001-A-Paquete.zip"
    viejo = zip_.read_bytes()
    antes = (m.raiz / "estado.json").read_bytes()
    m.dobles["paquete"].construir = lambda *a, **k: {"ficheros": []}  # no escribe ZIP nuevo
    rc, out = m.run("paquete")
    assert rc == 4 and "sin escribir" in out
    assert zip_.read_bytes() == viejo and (m.raiz / "estado.json").read_bytes() == antes
    assert not zip_.with_name(zip_.name + ".anterior").exists()
