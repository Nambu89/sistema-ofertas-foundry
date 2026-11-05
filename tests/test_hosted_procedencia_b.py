"""I1.4 · P1 e I1.5 · R: procedencia propia de B en el hosted agent (decisiones del comercial del 10 y 11-10-2026).

El código guarda por cada tarea A2A el texto recibido y su SHA-256, la relee con GetTask con su identidad y lo deja en
procedencia/procedencia_a2a.json; va al ZIP con su SHA-256 en el manifiesto y RESTAURAR lo recupera. Casos adversos:
relectura distinta, GetTask caído (una repetición anotada y nunca más), procedencia que no se escribe, hora futura,
fusión de un ZIP restaurado con relectura distinta o de otro agente (REV-4), orquestador sin marcar (VER14-3) y la
línea PAQUETE tras una DEVUELTA (PR14-5).
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import types
import zipfile

import pytest

from tests.test_hosted_falsos import A2AFalso, NUCLEO, coordinador, httpx
from tests.test_hosted_turno import _HOY, ASUMIR, _estado, _hasta_insuficiente, _sigue_hasta

PROC = ("procedencia", "procedencia_a2a.json")
CON_PAQUETE = "procedencia_a2a.json" in (NUCLEO / "nucleo" / "paquete.py").read_text(encoding="utf-8")
TASK_NOT_FOUND = {"jsonrpc": "2.0", "id": "x", "error": {"code": -32001, "message": "Task does not exist or is not "
                                                         "accessible", "data": [{"reason": "TASK_NOT_FOUND"}]}}
AGENTES = {"preventa-experto-azure", "preventa-verificador"}


def _doc(c) -> dict:
    return json.loads(c.cfg.trabajo.joinpath(*PROC).read_text(encoding="utf-8"))


def test_relectura_distinta_queda_registrada_y_se_dice_no_verificado(tmp_path, monkeypatch):
    a2a = A2AFalso()
    a2a.alterar_gettask = True
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [])
    assert "EXPERTO: VÁLIDA" in r and "NO VERIFICADO: la relectura GetTask" in r, r
    t = _doc(c)["tareas"][0]
    assert t["relectura"]["coincide"] is False and t["relectura"]["sha256_recibido"] != t["sha256_recibido"]
    mias = [x for x in a2a.relecturas if x["cuerpo"]["params"]["id"] == t["task_id"]]
    assert t["relectura"]["intentos"] == 1 and len(mias) == 1   # una relectura distinta no se repite


def test_gettask_caido_una_vez_se_repite_y_coincide(tmp_path, monkeypatch):
    a2a = A2AFalso()
    a2a.fallos_gettask.append(httpx.Response(200, json=TASK_NOT_FOUND))
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [])
    assert "EXPERTO: VÁLIDA" in r and "la repito una vez (1/1)" in r and "el texto coincide" in r, r
    rel = _doc(c)["tareas"][0]["relectura"]
    assert rel["coincide"] is True and rel["intentos"] == 2 and rel["error"] is None


def test_gettask_caido_dos_veces_no_verificado_sin_tercer_intento(tmp_path, monkeypatch):
    a2a = A2AFalso()
    a2a.fallos_gettask += [httpx.Response(200, json=TASK_NOT_FOUND), httpx.ConnectError("DNS caído (forzado)")]
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _hasta_insuficiente(c)
    n0 = len(a2a.relecturas)
    r = c.manejar(ASUMIR, [])
    assert "EXPERTO: VÁLIDA" in r and "NO VERIFICADO: no he podido releer la tarea" in r and "2 intento(s)" in r, r
    rel = _doc(c)["tareas"][0]["relectura"]
    assert rel["coincide"] is None and rel["intentos"] == 2 and "DNS caído" in rel["error"]
    primera_tarea = [x for x in a2a.relecturas[n0:] if x["cuerpo"]["params"]["id"] == _doc(c)["tareas"][0]["task_id"]]
    assert len(primera_tarea) == 2


def test_sin_procedencia_no_se_registra_la_respuesta(tmp_path, monkeypatch):
    from preventa_hosted import procedencia as PR
    c, _, _ = coordinador(tmp_path, monkeypatch)
    _hasta_insuficiente(c)
    original = PR.anadir

    def roto(*_a, **_k):
        raise OSError("disco lleno (forzado)")
    monkeypatch.setattr(PR, "anadir", roto)
    r = c.manejar(ASUMIR, [])
    assert "FALLO: no se pudo guardar la procedencia" in r and "EXPERTO: VÁLIDA" not in r, r
    est = _estado(c)
    assert est["intentos"]["T2"] == 1 and not (est["carga"].get("respuestas_expertos") or {})
    monkeypatch.setattr(PR, "anadir", original)
    assert "EXPERTO: VÁLIDA" in c.manejar("SIGUE", [])


def test_sin_marca_de_orquestador_b_no_ejecuta_nada(tmp_path, monkeypatch):
    c, a2a, modelo = coordinador(tmp_path, monkeypatch)
    for valor in ("A", "", " b "):
        monkeypatch.setenv("PREVENTA_ORQUESTADOR", valor)
        r = c.manejar("ESTADO", [])
        assert "PREVENTA_ORQUESTADOR debe valer B" in r and "No he ejecutado nada" in r, r
    monkeypatch.delenv("PREVENTA_ORQUESTADOR")
    assert "debe valer B" in c.manejar("ESTADO", [])
    assert not (c.cfg.trabajo / "estado.json").exists() and not a2a.recibidos and not modelo.peticiones


def test_main_marca_el_orquestador_solo_al_arrancar():
    import importlib
    import os

    import main
    previo = os.environ.pop("PREVENTA_ORQUESTADOR", None)
    try:
        importlib.reload(main)   # al importar no toca la variable (las pruebas no heredan una marca)
        assert "PREVENTA_ORQUESTADOR" not in os.environ
        main.marcar_orquestador()
        assert os.environ["PREVENTA_ORQUESTADOR"] == "B"
        os.environ["PREVENTA_ORQUESTADOR"] = "A"
        main.marcar_orquestador()   # se fuerza: un valor heredado distinto sería una marca falsa
        assert os.environ["PREVENTA_ORQUESTADOR"] == "B"
    finally:
        os.environ.pop("PREVENTA_ORQUESTADOR", None)
        if previo is not None:
            os.environ["PREVENTA_ORQUESTADOR"] = previo


def _tarea(PR, tid: str, texto: str = "{\"a\": 1}", **kw) -> dict:
    t = {k: None for k in PR.CLAVES} | {"task_id": tid, "texto_recibido": texto, "sha256_enviado": "0" * 64,
                                        "objetivo_id": "BRF-X", "relectura": {}, "agente": "preventa-experto-azure",
                                        "hora": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    t["sha256_recibido"] = PR.sha256(texto)
    return t | kw


def _leida(texto: str | None, error: str | None = None):
    import hashlib
    return types.SimpleNamespace(inicio="2026-10-11T09:00:00+00:00", http=200, latencia_s=0.4, error=error,
                                 estado_tarea=None if error else "TASK_STATE_COMPLETED",
                                 sha256_recibido=hashlib.sha256(texto.encode()).hexdigest() if texto else None)


def test_procedencia_no_reescribe_ni_admite_hora_futura(tmp_path):
    from preventa_hosted import procedencia as PR
    t = _tarea(PR, "resp_x0001")
    PR.anadir(tmp_path, t)
    PR.anadir(tmp_path, dict(t))                                    # idéntica: no se duplica
    assert len(PR.cargar(tmp_path)["tareas"]) == 1
    with pytest.raises(ValueError, match="otro contenido"):
        PR.anadir(tmp_path, t | {"texto_recibido": "{\"a\": 2}", "sha256_recibido": PR.sha256("{\"a\": 2}")})
    with pytest.raises(ValueError, match="SHA-256"):
        PR.anadir(tmp_path, t | {"task_id": "resp_x0002", "texto_recibido": "{\"a\": 3}"})   # texto alterado
    manana = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat(timespec="seconds")
    with pytest.raises(ValueError, match="hora futura"):                                      # REV-2
        PR.anadir(tmp_path, _tarea(PR, "resp_x0003", hora=manana))
    with pytest.raises(ValueError, match="sin formato ISO"):
        PR.anadir(tmp_path, _tarea(PR, "resp_x0004", hora="2026-10-11 09:00"))
    dentro = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=3)).isoformat(timespec="seconds")
    PR.anadir(tmp_path, _tarea(PR, "resp_x0005", hora=dentro))       # dentro del margen de 5 min (relojes)


def test_fusion_relee_cada_tarea_y_rechaza_si_difiere(tmp_path):
    from preventa_hosted import procedencia as PR
    previa = _tarea(PR, "resp_y0001")
    PR.anadir(tmp_path, previa)
    nueva, otra = _tarea(PR, "resp_y0002", "{\"b\": 2}"), _tarea(PR, "resp_y0003", "{\"c\": 3}")
    zip_doc = json.dumps({"schema": PR.SCHEMA, "tareas": [previa | {"context_id": "otro"}, nueva, otra]}).encode()
    pedidas = []

    def releer(agente, tid):
        pedidas.append((agente, tid))
        return _leida({"resp_y0002": "{\"b\": 2}", "resp_y0003": "{\"c\": 3}"}[tid])
    n, avisos = PR.fusionar(tmp_path, zip_doc, releer=releer, agentes=AGENTES)
    assert n == 2 and pedidas == [("preventa-experto-azure", "resp_y0002"), ("preventa-experto-azure", "resp_y0003")]
    assert len(avisos) == 1 and "no se pisa" in avisos[0]                 # la de la sesión no se toca ni se relee
    guardadas = {t["task_id"]: t for t in PR.cargar(tmp_path)["tareas"]}
    rel = guardadas["resp_y0002"]["relectura"]   # la relectura nueva del hosted, no la que traía el ZIP ({})
    assert rel["coincide"] is True and rel["hora"] == "2026-10-11T09:00:00+00:00" and rel["intentos"] == 1
    antes = PR.ruta(tmp_path).read_bytes()
    t4, t5 = _tarea(PR, "resp_y0004", "{\"d\": 4}"), _tarea(PR, "resp_y0005", "{\"e\": 5}")
    doc2 = json.dumps({"schema": PR.SCHEMA, "tareas": [t4, t5]}).encode()
    with pytest.raises(PR.FusionRechazada, match="resp_y0005 devuelve otro texto"):           # REV-4
        PR.fusionar(tmp_path, doc2, releer=lambda a, tid: _leida("{\"d\": 4}"), agentes=AGENTES)
    assert PR.ruta(tmp_path).read_bytes() == antes                          # nada añadido: ni la t4 que sí cuadraba
    ajena = json.dumps({"schema": PR.SCHEMA, "tareas": [_tarea(PR, "resp_y0006", agente="otro-agente")]}).encode()
    with pytest.raises(PR.FusionRechazada, match="otro-agente"):
        PR.fusionar(tmp_path, ajena, releer=lambda a, tid: pytest.fail("no se relee"), agentes=AGENTES)
    caida = json.dumps({"schema": PR.SCHEMA, "tareas": [_tarea(PR, "resp_y0007", "{\"f\": 6}")]}).encode()

    def roto(agente, tid):
        raise RuntimeError("red caída (forzado)")
    n, avisos = PR.fusionar(tmp_path, caida, releer=roto, agentes=AGENTES)
    rel = {t["task_id"]: t for t in PR.cargar(tmp_path)["tareas"]}["resp_y0007"]["relectura"]
    assert n == 1 and rel["coincide"] is None and "red caída" in rel["error"] and "NO VERIFICADO" in avisos[0]
    futura = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).isoformat(timespec="seconds")
    doc3 = json.dumps({"schema": PR.SCHEMA, "tareas": [_tarea(PR, "resp_y0008", hora=futura)]}).encode()
    n, avisos = PR.fusionar(tmp_path, doc3, releer=lambda a, tid: pytest.fail("no se relee"), agentes=AGENTES)
    assert n == 0 and "hora futura" in avisos[0]


def _adjunto(zip_) -> dict:
    return {"filename": zip_.name, "file_data": "data:application/zip;base64," + base64.b64encode(zip_.read_bytes()).decode(),
            "file_id": None, "file_url": None}


@pytest.mark.skipif(not CON_PAQUETE, reason="el núcleo aún no empaqueta la procedencia (CAMBIOS-I14-P1, sin integrar)")
def test_paquete_lleva_la_procedencia_y_restaurar_la_relee(tmp_path, monkeypatch):
    c, a2a, _ = coordinador(tmp_path / "s1", monkeypatch)
    _hasta_insuficiente(c)
    c.manejar(ASUMIR, [])
    _sigue_hasta(c, "LISTA_PARA_REVISION")
    zip_ = c.cfg.trabajo / "salida" / "OF-KELVARA-001-A-Paquete.zip"
    with zipfile.ZipFile(zip_) as zf:
        datos = zf.read("procedencia_a2a.json")
        man = json.loads(zf.read("manifiesto_paquete.json"))
    assert datos == c.cfg.trabajo.joinpath(*PROC).read_bytes()
    import hashlib
    assert {"nombre": "procedencia_a2a.json", "sha256": hashlib.sha256(datos).hexdigest(),
            "bytes": len(datos)} in man["ficheros"]
    tareas = json.loads(datos)["tareas"]
    # la misma identidad (el mismo A2A falso) relee en la sesión nueva: REV-4
    c2, _, _ = coordinador(tmp_path / "s2", monkeypatch, a2a=a2a)
    n0 = len(a2a.relecturas)
    r = c2.manejar("RESTAURAR", [_adjunto(zip_)])
    assert f"Procedencia A2A recuperada del ZIP: {len(tareas)} tarea(s)" in r, r
    assert [x["cuerpo"]["params"]["id"] for x in a2a.relecturas[n0:]] == [t["task_id"] for t in tareas]
    nuevas = _doc(c2)["tareas"]
    assert [{k: v for k, v in t.items() if k != "relectura"} for t in nuevas] == \
           [{k: v for k, v in t.items() if k != "relectura"} for t in tareas]
    assert all(t["relectura"]["coincide"] is True for t in nuevas)
    # con GetTask devolviendo otro texto, no se fusiona nada y se dice en alto
    a2a.alterar_gettask = True
    c3, _, _ = coordinador(tmp_path / "s3", monkeypatch, a2a=a2a)
    r = c3.manejar("RESTAURAR", [_adjunto(zip_)])
    assert "FALLO: no fusiono la procedencia A2A del ZIP" in r and "devuelve otro texto" in r, r
    assert not c3.cfg.trabajo.joinpath(*PROC).exists() or not _doc(c3)["tareas"]


def test_devuelta_lleva_los_comentarios_al_brief_y_no_ofrece_el_zip_viejo(tmp_path, monkeypatch):
    """PR14-6 y PR14-5: tras la DEVUELTA, el brief de la versión B lleva el comentario y la línea PAQUETE ya no
    ofrece el ZIP de la versión A."""
    c, a2a, _ = coordinador(tmp_path, monkeypatch, PREVENTA_MAX_A2A_POR_TURNO="8")
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [])
    assert "LISTA_PARA_REVISION" in r and "PAQUETE: OF-KELVARA-001-A-Paquete.zip" in r, r
    h = _estado(c)["hash_contenido"]
    c.manejar(f"DECISION | Responsable comercial | ENVIADA_REVISION | {_HOY} | {h} | verificar_paquete rc=0", [])
    comentario = "Diapositiva 8: falta el precio de Azure AI Search; repetir el análisis con sus precios"
    r = c.manejar(f"DECISION | Responsable de preventa | DEVUELTA | {_HOY} | {h} | {comentario}", [])
    assert "DEVUELTA_CON_COMENTARIOS" in r, r
    assert "todavía no hay paquete de la versión vigente (OF-KELVARA-001-B-Paquete.zip)" in r, r
    assert "OF-KELVARA-001-A-Paquete.zip, es de una versión anterior" in r and "Descárgalo en tu equipo" not in r, r
    n = len(a2a.recibidos)
    r = c.manejar("SIGUE", [])
    enviado = a2a.recibidos[n]["cuerpo"]["params"]["message"]["parts"][0]["text"]
    assert "brief_id: BRF-OF-KELVARA-001-B-AZ-R1" in enviado, r
    assert "## Comentarios de la revisión de la versión A (DEVUELTA" in enviado
    assert f"\n- {comentario}" in enviado and enviado == _estado(c)["carga"]["briefs"][-1]["texto"]


CON_MARCA = "orquestador_actual" in (NUCLEO / "nucleo" / "estado.py").read_text(encoding="utf-8")


@pytest.mark.skipif(not (CON_PAQUETE and CON_MARCA),
                    reason="el núcleo aún no marca el orquestador (docs/I1/CAMBIOS-I15-R.md §2, sin integrar)")
def test_el_paquete_de_b_sale_marcado_y_la_puerta_lo_exige(tmp_path, monkeypatch):
    import verificar_paquete as vp
    from tests.evidencias import requerir
    from tests.test_hosted_falsos import PROYECTOS
    requerir(PROYECTOS / "_templates" / "estimacion" / "generar_estimacion.py", activo=True)   # el paquete exige la estimación
    c, _, _ = coordinador(tmp_path, monkeypatch, PREVENTA_MAX_A2A_POR_TURNO="8")
    _hasta_insuficiente(c)
    assert "LISTA_PARA_REVISION" in c.manejar(ASUMIR, [])
    zip_ = c.cfg.trabajo / "salida" / "OF-KELVARA-001-A-Paquete.zip"
    with zipfile.ZipFile(zip_) as zf:
        est, man = json.loads(zf.read("estado.json")), json.loads(zf.read("manifiesto_paquete.json"))
    assert est["orquestador"] == "B" and man["orquestador"] == "B" and _estado(c)["orquestador"] == "B"
    paquete = vp.abrir_paquete(zip_, tmp_path / "puerta")
    ctx = vp.Contexto(paquete, tmp_path, {}, tmp_path, tmp_path, tmp_path, tmp_path, None, True, dt.date.today(),
                      tmp_path / "puerta")
    ctx.manifiesto, ctx.estado = paquete.json_de("manifiesto_paquete.json"), paquete.json_de("estado.json")
    ctx.codigo = ctx.manifiesto["codigo"]
    assert vp.c_esquemas(ctx).estado != vp.FALLA and vp.c_estructura(ctx).estado != vp.FALLA
    p = vp.c_procedencia(ctx)
    assert p.estado == vp.NOV and any("orquestador B (marca del código" in d for d in p.detalles), p.detalles
    assert any("parte local de la procedencia de B comprobada" in d for d in p.detalles), p.detalles
