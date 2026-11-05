"""Pruebas del papel R (I1.1): H7 (restaurar --zip byte a byte), H11 (T1 a 0 con asumir), H12 (relevo tras
cada decisión) y R2 (confirmaciones locales trazadas). Sin red; B, C y D con dobles (test_i1_estado_comun)."""
from __future__ import annotations

import copy
import json
import shutil
import zipfile

import pytest

from tests.test_i1_estado_comun import ADJUNTO, Mundo, ejemplo, estado, hashes
from nucleo import decision, restaurar

F, J, JP = "Responsable comercial", "Responsable de preventa", "Responsable de área"
PAQ, REL_B = "OF-KELVARA-001-A-Paquete.zip", "OF-KELVARA-001-B-Relevo.zip"


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def contenedor_nuevo(m, tmp_path, monkeypatch, adjuntos: dict[str, bytes], n: int = 2):
    """Otro /mnt/data con la transcripción y los adjuntos «assistant-<id>-<nombre>»; devuelve la raíz vieja."""
    viejo = m.raiz
    nuevo = tmp_path / f"data{n}"
    nuevo.mkdir()
    shutil.copy(m.datos / f"assistant-F1x-{ADJUNTO}", nuevo / f"assistant-F1x-{ADJUNTO}")
    shutil.copy(m.catalogo, nuevo / m.catalogo.name)
    for i, (nombre, datos) in enumerate(adjuntos.items()):
        (nuevo / f"assistant-z{i}-{nombre}").write_bytes(datos)
    monkeypatch.setenv("PREVENTA_DATOS", str(nuevo))
    monkeypatch.setenv("PREVENTA_RAIZ", str(nuevo / "preventa"))
    m.datos, m.raiz = nuevo, nuevo / "preventa"
    return viejo


def miembros(ruta) -> dict[str, bytes]:
    with zipfile.ZipFile(ruta) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def rezipear(contenido: dict[str, bytes]) -> bytes:
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in contenido.items():
            z.writestr(n, b)
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------- H11
def test_asumir_pone_t1_a_cero(m):
    assert m.iniciar()[0] == 0
    malo = m.requisitos_modelo()
    malo["campos"]["volumetria"] = {"estado": "ASUMIDO", "entradas": [
        {"valor": "100 usuarios", "cita": None, "fuente": None, "origen": "ASUMIDO"}]}
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", malo))
    assert rc == 1 and "T1 1/3" in out
    assert m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", m.requisitos_modelo()))[0] == 1
    assert m.estado()["intentos"]["T1"] == 1
    req = ejemplo("requisitos")["campos"]
    rc, out = m.run("asumir", "--campo", "volumetria", "--valor", req["volumetria"]["entradas"][0]["valor"])
    assert rc == 0 and "INCOMPLETA" in out and "T1 1/3" in out  # aún incompleta: el contador no se toca
    rc, out = m.run("asumir", "--campo", "identidad_acl_origen", "--valor",
                    req["identidad_acl_origen"]["entradas"][0]["valor"])
    assert rc == 0 and "SUFICIENCIA: COMPLETA" in out and "estado: EN_ANALISIS" in out
    assert "T1 0/3" in out and m.estado()["intentos"]["T1"] == 0


# ---------------------------------------------------------------------------------------------- H7
def test_restaurar_zip_del_paquete_recupera_los_economicos_byte_a_byte(m, tmp_path, monkeypatch):
    m.hasta_lista()
    h, zip_a = m.hash(), (m.raiz / "salida" / PAQ).read_bytes()
    originales = miembros(m.raiz / "salida" / PAQ)
    llamadas = len(m.dobles["estimacion"].LLAMADAS)
    contenedor_nuevo(m, tmp_path, monkeypatch, {PAQ: zip_a})
    rc, out = m.run("restaurar", "--zip", PAQ)
    assert rc == 0 and "RESTAURADO" in out and f"el paquete {PAQ}" in out and m.hash() == h
    for n in ("OF-KELVARA-001-A-Estimacion.xlsx", "OF-KELVARA-001-A-Anexo-Consumo.xlsx",
              "OF-KELVARA-001-A-Anexo-Consumo.json"):
        assert f"recuperado byte a byte: salida/{n}" in out
        assert (m.raiz / "salida" / n).read_bytes() == originales[n]
    assert "--previo" not in out  # no hace falta regenerar nada
    assert (m.raiz / "estado.json").read_bytes() == originales["estado.json"]
    rc, out = m.run("restaurar", "--zip", PAQ)
    assert rc == 0  # mismo ZIP: idempotente
    for linea in (m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"), m.linea(J, "APROBADA", "Conforme"),
                  m.linea(JP, "APROBADA", "Aprobada por el área")):
        assert m.run("decision", "--linea", linea)[0] == 0
    assert m.run("paquete")[0] == 0
    final = miembros(m.raiz / "salida" / PAQ)
    for n in ("OF-KELVARA-001-A-Estimacion.xlsx", "OF-KELVARA-001-A-Anexo-Consumo.xlsx"):
        assert final[n] == originales[n]  # lo que compara el --previo de verificar_paquete
    assert len(m.dobles["estimacion"].LLAMADAS) == llamadas  # no se volvió a estimar


def _resellar(cont: dict[str, bytes], nombre: str, datos: bytes) -> dict[str, bytes]:
    """Cambia un miembro y vuelve a sellar el manifiesto (lo que haría el modelo, LES-G-097.4)."""
    cont = dict(cont)
    cont[nombre] = datos
    man = json.loads(cont["manifiesto_paquete.json"])
    for f in man["ficheros"]:
        if f["nombre"] == nombre:
            f["sha256"], f["bytes"] = hashes.sha256_bytes(datos), len(datos)
    cont["manifiesto_paquete.json"] = json.dumps(man).encode()
    return cont


@pytest.mark.parametrize("estropear, motivo", [
    ("xlsx_resellado", "distinto de artefactos.xlsx_estimacion"),
    ("miembro_extra", "que no está en manifiesto_paquete.json"),
    ("falta_miembro", "que lista manifiesto_paquete.json"),
    ("sin_resellar", "distinto del de manifiesto_paquete.json"),
    ("ruta", "miembro con ruta o nombre no admitido"),
    ("dos_anclas", "uno solo"),
    ("no_zip", "no es un ZIP válido"),
])
def test_restaurar_zip_rechaza_sin_escribir(m, tmp_path, monkeypatch, estropear, motivo):
    m.hasta_lista()
    cont = miembros(m.raiz / "salida" / PAQ)
    xlsx = "OF-KELVARA-001-A-Estimacion.xlsx"
    if estropear == "xlsx_resellado":
        cont = _resellar(cont, xlsx, cont[xlsx] + b" cambiado")
    elif estropear == "miembro_extra":
        cont["OF-KELVARA-001-A-Otro.txt"] = b"sobra"
    elif estropear == "falta_miembro":
        del cont["mensaje_revisor.txt"]
    elif estropear == "sin_resellar":
        cont[xlsx] = cont[xlsx] + b" cambiado"
    elif estropear == "ruta":
        cont["../estado.json"] = cont["estado.json"]
    elif estropear == "dos_anclas":
        cont["relevo.json"] = b"{}"
    datos = b"esto no es un zip" if estropear == "no_zip" else rezipear(cont)
    contenedor_nuevo(m, tmp_path, monkeypatch, {PAQ: datos})
    rc, out = m.run("restaurar", "--zip", PAQ)
    assert rc == 4 and motivo in out, out
    assert not (m.raiz / "estado.json").exists() and not (m.raiz / "salida").exists()


@pytest.mark.parametrize("args", [
    [], ["--estado", "estado.json"], ["--zip", PAQ, "--estado", "estado.json", "--manifiesto", "m.json"],
])
def test_restaurar_exige_un_modo(m, args):
    rc, out = m.run("restaurar", *args)
    assert rc == 2 and "o --zip" in out and "estado: SIN_ESTADO" in out


def test_restaurar_no_pisa_un_xlsx_distinto(m, tmp_path, monkeypatch):
    m.hasta_lista()
    contenedor_nuevo(m, tmp_path, monkeypatch, {PAQ: (m.raiz / "salida" / PAQ).read_bytes()})
    (m.raiz / "salida").mkdir(parents=True)
    (m.raiz / "salida" / "OF-KELVARA-001-A-Estimacion.xlsx").write_bytes(b"otro")
    rc, out = m.run("restaurar", "--zip", PAQ)
    assert rc == 4 and "no se pisan" in out and not (m.raiz / "estado.json").exists()


# ---------------------------------------------------------------------------------------------- H12
def test_relevo_tras_devuelta_continua_en_conversacion_nueva(m, tmp_path, monkeypatch):
    m.hasta_lista()
    assert m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))[0] == 0
    rc, out = m.run("decision", "--linea", m.linea(J, "DEVUELTA", "Revisar el alcance de la integración"))
    assert rc == 0 and f"RELEVO: salida/{REL_B}" in out and f"restaurar --zip {REL_B}" in out
    est_b, h = m.estado(), m.hash()
    rel = miembros(m.raiz / "salida" / REL_B)
    assert rel["estado.json"] == (m.raiz / "estado.json").read_bytes()
    man = json.loads(rel["relevo.json"])
    assert man["decisiones"] == 2 and man["ultima_decision"] == "D-002" and man["estado"] == "DEVUELTA_CON_COMENTARIOS"
    contenedor_nuevo(m, tmp_path, monkeypatch, {REL_B: (m.raiz / "salida" / REL_B).read_bytes()})
    rc, out = m.run("restaurar", "--zip", REL_B)
    assert rc == 0 and f"el relevo {REL_B}" in out and "estado: DEVUELTA_CON_COMENTARIOS" in out
    assert "version: B" in out and "decisiones: 2" in out and m.hash() == h
    assert m.estado()["decisiones"] == est_b["decisiones"]
    rc, out = m.run("anexo-consumo")  # sigue la versión B sin volver a pegar ninguna decisión
    assert rc == 0 and "estado: VERIFICADA" in out


def test_relevo_resellado_o_incoherente_se_rechaza(m, tmp_path, monkeypatch):
    m.hasta_lista()
    m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))
    cont = miembros(m.raiz / "salida" / "OF-KELVARA-001-A-Relevo.zip")
    man = json.loads(cont["relevo.json"])
    man["decisiones"] = 0
    cont["relevo.json"] = json.dumps(man).encode()
    contenedor_nuevo(m, tmp_path, monkeypatch, {"OF-KELVARA-001-A-Relevo.zip": rezipear(cont)})
    rc, out = m.run("restaurar", "--zip", "OF-KELVARA-001-A-Relevo.zip")
    assert rc == 4 and "relevo: 0 decisiones" in out and not (m.raiz / "estado.json").exists()


def test_relevo_lleva_la_aclaracion_y_la_repone(m, tmp_path, monkeypatch):
    assert m.iniciar()[0] == 0
    acl = m.entrada("aclaracion.txt", "El comercial aclara que los usuarios finales están en España y Portugal.\n")
    assert m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", m.requisitos_modelo()),
                 "--aclaracion", acl)[0] == 1
    for _ in range(3):
        m.run("registrar-fallo", "--fase", "T1", "--error", "HTTP 424 tool_server_error", "--hipotesis", "corte A2A")
    assert m.estado()["estado"] == "BLOQUEADA"
    rc, out = m.run("decision", "--linea", m.linea(F, "DESBLOQUEAR", "Corte transitorio de la herramienta"))
    assert rc == 0 and "RELEVO: salida/OF-KELVARA-001-A-Relevo.zip" in out
    texto_f2 = (m.raiz / "fuentes" / "F2.txt").read_bytes()
    zip_rel = (m.raiz / "salida" / "OF-KELVARA-001-A-Relevo.zip").read_bytes()
    contenedor_nuevo(m, tmp_path, monkeypatch, {"OF-KELVARA-001-A-Relevo.zip": zip_rel})
    rc, out = m.run("restaurar", "--zip", "OF-KELVARA-001-A-Relevo.zip")
    assert rc == 0 and "recuperado byte a byte: fuentes/F2.txt" in out
    assert (m.raiz / "fuentes" / "F2.txt").read_bytes() == texto_f2
    rc, out = m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", m.requisitos_modelo()))
    assert rc == 1 and "Falta el texto de la fuente" not in out and "INCOMPLETA" in out


def test_decision_sin_relevo_deja_el_estado_como_estaba(m, monkeypatch):
    m.hasta_lista()
    antes = (m.raiz / "estado.json").read_bytes()

    def romper(relevo, raiz):
        raise restaurar.IntegridadRota("disco lleno de prueba", [])
    monkeypatch.setattr(restaurar, "publicar_relevo", romper)
    rc, out = m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))
    assert rc == 4 and "disco lleno de prueba" in out and "estado: LISTA_PARA_REVISION" in out
    assert (m.raiz / "estado.json").read_bytes() == antes


# ---------------------------------------------------------------------------------------------- R2
def test_stop_queda_trazado_para_la_confirmacion_local(m):
    m.hasta_verificada()
    m.run("anexo-consumo")
    m.dobles["estimacion"].PRECIO = "140000.00"
    assert m.run("estimar")[0] == 1
    h = m.hash()
    rc, out = m.run("decision", "--linea", m.linea(F, "CONFIRMA_STOP", "Cliente acepta el importe del piloto"))
    d = m.estado()["decisiones"][-1]
    assert rc == 0 and d["tipo"] == "CONFIRMA_STOP" and d["hash_citado"] == h
    huella = hashes.sha256_texto(d["linea"])
    assert (f"CONFIRMACIÓN LOCAL OBLIGATORIA: CONFIRMA_STOP · 140000.00 EUR · {d['id']} (huella de la línea {huella})"
            in out) and f"--confirmo-stop {h}" in out
    rc, out = m.run("paquete")
    assert rc == 0 and f"--confirmo-stop {h}" in out
    assert f"En verificar_paquete.py, el comercial añade en su puesto: --confirmo-stop {h}" in out  # siguiente paso


def _con_estimacion(precio: str, ajuste: bool) -> dict:
    est = copy.deepcopy(ejemplo("estado"))
    est["carga"]["estimacion"]["resumen"]["precio_cerrado_eur"] = precio
    est["decisiones"] = []
    if ajuste:
        base = "b" * 64
        linea = f"DECISION | {F} | AJUSTE_COMERCIAL | 2026-10-08 | {base} | importe_eur=-1500.00; motivo=Cliente estratégico"
        est["decisiones"].append({"id": "D-001", "linea": linea, "revisor": F, "tipo": "AJUSTE_COMERCIAL",
                                  "fecha": "2026-10-08", "hash_citado": base,
                                  "comentarios": "importe_eur=-1500.00; motivo=Cliente estratégico",
                                  "version": est["version"], "estado_antes": "VERIFICADA", "estado_despues": "VERIFICADA",
                                  "registrada_ts": "2026-10-08T10:00:00+02:00"})
        est["carga"]["estimacion"]["ajuste"] = {"decision_id": "D-001", "importe_eur": "-1500.00",
                                                "motivo": "Cliente estratégico", "hash_base": base}
    return est


def test_confirmaciones_locales_unidad():
    assert decision.confirmaciones_locales(_con_estimacion("90000.00", False)) == []
    assert decision.orden_confirmacion(_con_estimacion("90000.00", False)) == ""
    est = _con_estimacion("150000.00", True)
    stop, aj = decision.confirmaciones_locales(est)
    assert stop["tipo"] == "CONFIRMA_STOP" and stop["decision_id"] is None  # falta la decisión: se dice
    assert stop["hash"] == hashes.hash_contenido(est) and stop["precio_eur"] == "150000.00"
    assert stop["hash_decision"] is None
    assert aj == {"tipo": "AJUSTE_COMERCIAL", "opcion": "--confirmo-ajuste", "hash": hashes.hash_contenido(est),
                  "hash_decision": "b" * 64, "decision_id": "D-001",
                  "huella_linea": hashes.sha256_texto(est["decisiones"][0]["linea"]),
                  "linea": est["decisiones"][0]["linea"], "importe_eur": "-1500.00"}
    vig = hashes.hash_contenido(est)  # lo que compara verificar_paquete.py (_confirmacion_local)
    assert decision.orden_confirmacion(est) == f"--confirmo-stop {vig} --confirmo-ajuste {vig}"
    est["decisiones"][0]["hash_citado"] = "c" * 64  # la decisión no respalda el ajuste aplicado
    assert decision.confirmaciones_locales(est)[1]["decision_id"] is None


def test_aclaracion_repetida_repone_su_texto(m):
    assert m.iniciar()[0] == 0
    acl = m.entrada("aclaracion.txt", "El comercial aclara que los usuarios finales están en España y Portugal.\n")
    req = m.entrada("requisitos.json", m.requisitos_modelo())
    assert m.run("suficiencia", "--requisitos", req, "--aclaracion", acl)[0] == 1
    (m.raiz / "fuentes" / "F2.txt").unlink()  # como tras restaurar desde un paquete, que no la lleva
    rc, out = m.run("suficiencia", "--requisitos", req, "--aclaracion", acl)
    assert rc == 1 and "Falta el texto de la fuente" not in out
    assert (m.raiz / "fuentes" / "F2.txt").is_file() and len(m.estado()["carga"]["fuentes"]) == 2


@pytest.mark.parametrize("tope, motivo", [("MAX_BYTES_TOTAL", "descomprimidos"), ("MAX_BYTES_ZIP", "demasiado grande")])
def test_restaurar_zip_con_topes_de_tamano(m, tmp_path, monkeypatch, tope, motivo):
    m.hasta_lista()
    contenedor_nuevo(m, tmp_path, monkeypatch, {PAQ: (m.raiz / "salida" / PAQ).read_bytes()})
    monkeypatch.setattr(restaurar, tope, 100)
    rc, out = m.run("restaurar", "--zip", PAQ)
    assert rc == 4 and motivo in out and not (m.raiz / "estado.json").exists()


def test_relevo_con_nombre_no_textual_es_integridad_rota(m, tmp_path, monkeypatch):
    m.hasta_lista()
    m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))
    cont = miembros(m.raiz / "salida" / "OF-KELVARA-001-A-Relevo.zip")
    man = json.loads(cont["relevo.json"])
    man["ficheros"][0]["nombre"] = ["estado.json"]
    cont["relevo.json"] = json.dumps(man).encode()
    contenedor_nuevo(m, tmp_path, monkeypatch, {"OF-KELVARA-001-A-Relevo.zip": rezipear(cont)})
    rc, out = m.run("restaurar", "--zip", "OF-KELVARA-001-A-Relevo.zip")
    assert rc == 4 and "nombre no válido o repetido" in out and not (m.raiz / "estado.json").exists()


def test_relevo_que_no_se_compone_no_escribe_nada(m, monkeypatch):
    m.hasta_lista()
    antes = (m.raiz / "estado.json").read_bytes()

    def romper(est, raiz):
        raise restaurar.IntegridadRota("no se puede componer de prueba", [])
    monkeypatch.setattr(restaurar, "componer_relevo", romper)
    rc, out = m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))
    assert rc == 4 and "no se puede componer de prueba" in out
    assert (m.raiz / "estado.json").read_bytes() == antes and not list((m.raiz / "salida").glob("*-Relevo.zip"))


def test_doble_fallo_relevo_y_vuelta_atras_se_dice_en_alto(m, monkeypatch):
    m.hasta_lista()
    real = estado.guardar
    llamadas = []

    def guardar(est, raiz):
        llamadas.append(est["estado"])
        if len(llamadas) == 2:
            raise OSError(28, "No space left on device")
        return real(est, raiz)

    def romper(relevo, raiz):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(restaurar, "publicar_relevo", romper)
    monkeypatch.setattr(estado, "guardar", guardar)
    rc, out = m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))
    assert rc == 4 and "quedó guardada SIN relevo y no se pudo volver atrás" in out and "parar y avisar" in out


def test_restaurar_rechaza_artefactos_con_el_mismo_nombre(m, tmp_path, monkeypatch):
    m.hasta_lista()
    cont = miembros(m.raiz / "salida" / PAQ)
    est = json.loads(cont["estado.json"])
    est["artefactos"]["anexo_json"] = dict(est["artefactos"]["anexo_xlsx"])  # mismo nombre, otro artefacto
    cont = _resellar(cont, "estado.json", json.dumps(est, ensure_ascii=False, indent=2).encode("utf-8"))
    man = json.loads(cont["manifiesto_paquete.json"])
    man["estado_json_sha256"] = hashes.sha256_bytes(cont["estado.json"])
    cont["manifiesto_paquete.json"] = json.dumps(man).encode()
    contenedor_nuevo(m, tmp_path, monkeypatch, {PAQ: rezipear(cont)})
    rc, out = m.run("restaurar", "--zip", PAQ)
    assert rc == 4 and "no acaba en -Anexo-Consumo.json" in out and not (m.raiz / "estado.json").exists()


@pytest.mark.filterwarnings("ignore:Duplicate name")  # el repetido es el caso que se prueba
def test_restaurar_zip_con_demasiados_miembros_o_repetidos(m, tmp_path, monkeypatch):
    m.hasta_lista()
    cont = miembros(m.raiz / "salida" / PAQ)
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, b in cont.items():
            z.writestr(n, b)
        z.writestr("mensaje_revisor.txt", b"repetido")
    contenedor_nuevo(m, tmp_path, monkeypatch, {PAQ: buf.getvalue()})
    rc, out = m.run("restaurar", "--zip", PAQ)
    assert rc == 4 and "miembro repetido: mensaje_revisor.txt" in out
    monkeypatch.setattr(restaurar, "MAX_MIEMBROS", 3)
    rc, out = m.run("restaurar", "--zip", PAQ)
    assert rc == 4 and "(máximo 3)" in out and not (m.raiz / "estado.json").exists()
