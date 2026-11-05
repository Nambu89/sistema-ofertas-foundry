"""I1.4 · P1: la puerta local con la procedencia propia de B y REV13-2 (ventana de la ejecución, orden y tope).

Base: el paquete real de B (Brezalia, I1.3). Se le añade procedencia_a2a.json (como lo escribe el hosted) y su línea en
el manifiesto; las trazas son falsas con la forma real (gen_ai.response.id = task_id, contenido cortado a 1.024
caracteres con «... [TRUNCATED]», sonda pruebas/I14/P1/sonda_tareas.txt). Casos adversos con su resultado esperado.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import pathlib
import zipfile

import pytest

import verificar_paquete as vp

RAIZ = pathlib.Path(__file__).resolve().parents[1]
REAL = RAIZ / "pruebas" / "I13" / "ARREGLOS" / "REAL_B" / "descargas" / "OF-BREZALIA-001-A-Paquete.zip"
pytestmark = pytest.mark.skipif(not REAL.is_file(), reason="falta el paquete real de B de I1.3")
def CONEXIONES() -> list[dict]:
    return [{"properties": {"target": "/subscriptions/x/components/appi-preventa-ejemplo"}}]


HACE_UNA_HORA = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat(timespec="seconds")


def sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def tareas_de(estado: dict) -> list[dict]:
    """Una tarea por salida que usó el núcleo, con el texto que la reproduce (como la guarda el hosted)."""
    c = estado["carga"]
    resp = c["respuestas_expertos"]["azure"]["respuesta"]
    brief = next(b for b in c["briefs"] if b["brief_id"] == resp["brief_id"])
    # integrador I1.7: lo que recibió el hosted es lo que escribió el modelo (la proyección de la completada guardada)
    salida_experto = vp.proyectar_r(resp) if "valoracion_nucleo" in resp else resp
    objetivos = [("T2", "preventa-experto-azure", brief["brief_id"], brief["texto"], salida_experto)]
    objetivos += [("T3", "preventa-verificador", x["lote_id"], x["texto"], x["respuesta"]) for x in c["consolidado"]["lotes"]]
    salida = []
    for i, (fase, agente, oid, enviado, guardado) in enumerate(objetivos):
        texto = json.dumps(guardado, ensure_ascii=False)
        salida.append({"fase": fase, "agente": agente, "url": f"https://x/agents/{agente}/endpoint/protocols/a2a",
                       "objetivo_id": oid, "hora": HACE_UNA_HORA, "task_id": f"resp_prueba{i:04d}",
                       "context_id": f"ctxt_prueba{i:04d}", "estado_tarea": "TASK_STATE_COMPLETED",
                       "sha256_enviado": sha(enviado), "bytes_enviado": len(enviado.encode()), "sha256_recibido": sha(texto),
                       "bytes_recibido": len(texto.encode()), "texto_recibido": texto,
                       "relectura": {"metodo": "GetTask", "hora": HACE_UNA_HORA, "http": 200, "latencia_s": 1.0,
                                     "estado_tarea": "TASK_STATE_COMPLETED", "sha256_recibido": sha(texto),
                                     "coincide": True, "error": None}})
    return salida


def paquete_b(tmp: pathlib.Path, mutar=None, en_manifiesto: bool = True, bytes_otros: bool = False) -> pathlib.Path:
    with zipfile.ZipFile(REAL) as zf:
        miembros = {n: zf.read(n) for n in zf.namelist()}
    doc = {"schema": vp.SCHEMA_PROCEDENCIA, "tareas": tareas_de(json.loads(miembros["estado.json"]))}
    if mutar:
        mutar(doc)
    datos = (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    man = json.loads(miembros["manifiesto_paquete.json"])
    if en_manifiesto:
        man["ficheros"].append({"nombre": vp.NOMBRE_PROCEDENCIA, "sha256": hashlib.sha256(datos).hexdigest(),
                                "bytes": len(datos)})
    miembros["manifiesto_paquete.json"] = (json.dumps(man, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    miembros[vp.NOMBRE_PROCEDENCIA] = datos + (b" " if bytes_otros else b"")
    destino = tmp / "OF-BREZALIA-001-A-Paquete.zip"
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, b in miembros.items():
            zf.writestr(n, b)
    return destino


def trazas(doc_o_tareas, cambiar=None, extra=None, error=None, filas_extra=0):
    """KQL falsa: filas de chat con gen_ai.response.id; `cambiar(tid, contenido)` altera lo que conserva la traza."""
    tareas = doc_o_tareas["tareas"] if isinstance(doc_o_tareas, dict) else doc_o_tareas
    consultas: list[str] = []

    def kql(consulta: str):
        consultas.append(consulta)
        if error:
            raise RuntimeError(error)
        filas = []
        for t in tareas + (extra or []):
            if f'"{t["task_id"]}"' not in consulta:
                continue
            texto = t["texto_recibido"]
            contenido = texto if len(texto) <= 1024 else texto[:1009] + "... [TRUNCATED]"
            if cambiar:
                contenido = cambiar(t["task_id"], contenido)
            if contenido is None:
                continue
            salida = json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": contenido}]}])
            filas.append({"timestamp": t["hora"], "itemType": "dependency", "name": "chat gpt-6-luna", "op": "op",
                          "tid": t["task_id"], "dims": json.dumps({"gen_ai.response.id": t["task_id"],
                                                                   "gen_ai.output.messages": salida})})
        return filas + [{"tid": "otro", "dims": "{}"}] * filas_extra
    kql.consultas = consultas
    return kql


def contexto(zip_: pathlib.Path, tmp: pathlib.Path, kql) -> vp.Contexto:
    paquete = vp.abrir_paquete(zip_, tmp)
    ctx = vp.Contexto(paquete, tmp, {}, tmp, tmp, tmp, tmp, None, False, dt.date.today(), tmp,
                      conexiones_appi=CONEXIONES, consultar_kql=kql)
    ctx.manifiesto, ctx.estado = paquete.json_de("manifiesto_paquete.json"), paquete.json_de("estado.json")
    ctx.codigo = ctx.manifiesto["codigo"]
    return ctx


def doc_de(zip_: pathlib.Path) -> dict:
    with zipfile.ZipFile(zip_) as zf:
        return json.loads(zf.read(vp.NOMBRE_PROCEDENCIA))


def juzgar(tmp_path, mutar=None, **kw_trazas):
    z = paquete_b(tmp_path, mutar)
    kql = trazas(doc_de(z), **kw_trazas)
    c = vp.c_procedencia(contexto(z, tmp_path, kql))
    return c, kql


def test_b_con_procedencia_da_verde_por_task_id(tmp_path):
    c, kql = juzgar(tmp_path)
    assert c.estado == vp.OK, c.detalles
    assert sum("es el del texto registrado" in d for d in c.detalles) >= 1, c.detalles   # salidas largas: comienzo
    assert sum("completo" in d for d in c.detalles) >= 1, c.detalles                    # cortas: enteras
    assert len(kql.consultas) == 1 and "gen_ai.response.id" in kql.consultas[0] and "between (datetime(" in kql.consultas[0]


def _alterar_texto(doc):
    doc["tareas"][1]["texto_recibido"] = doc["tareas"][1]["texto_recibido"].replace('"OK"', '"DISCREPA"', 1)


def _alterar_y_resellar(doc):
    _alterar_texto(doc)
    doc["tareas"][1]["sha256_recibido"] = sha(doc["tareas"][1]["texto_recibido"])


@pytest.mark.parametrize("mutar, motivo", [
    (_alterar_texto, "texto alterado"),
    (_alterar_y_resellar, "trae el texto que registró el núcleo"),
    (lambda d: d["tareas"][0].update(sha256_enviado="a" * 64), "huella del texto del estado"),
    (lambda d: d["tareas"][2].update(agente="otro-agente"), "no de preventa-verificador"),
    (lambda d: d["tareas"][3]["relectura"].update(coincide=False, sha256_recibido="b" * 64), "relectura GetTask"),
    (lambda d: d["tareas"].pop(), "ninguna de las 0 tareas"),
    (lambda d: d["tareas"][0].update(hora="ayer"), "hora sin formato"),
])
def test_b_casos_adversos_de_la_procedencia(tmp_path, mutar, motivo):
    c, _ = juzgar(tmp_path, mutar)
    assert c.estado == vp.FALLA and any(motivo in d for d in c.detalles), c.detalles


def test_b_comienzo_distinto_y_task_id_ajeno(tmp_path):
    z = paquete_b(tmp_path)
    doc = doc_de(z)
    c = vp.c_procedencia(contexto(z, tmp_path, trazas(doc, cambiar=lambda tid, x: "{\"otro\"" + x[7:]
                                                      if tid == "resp_prueba0000" else x)))
    assert c.estado == vp.FALLA and any("resp_prueba0000" in d and "comienzo distinto" in d for d in c.detalles)


def test_b_task_id_ajeno(tmp_path):
    """La tarea registrada dice ser una llamada que sí está en las trazas, pero esa llamada devolvió otro texto."""
    z = paquete_b(tmp_path, lambda d: d["tareas"][1].update(task_id="resp_ajena0001"))
    doc = doc_de(z)
    ajena = dict(doc["tareas"][1], texto_recibido=doc["tareas"][3]["texto_recibido"])
    otras = [t for t in doc["tareas"] if t["task_id"] != "resp_ajena0001"]
    c = vp.c_procedencia(contexto(z, tmp_path, trazas(otras, extra=[ajena])))
    assert c.estado == vp.FALLA and any("resp_ajena0001" in d and "comienzo distinto" in d for d in c.detalles)


def test_b_task_id_ausente_tope_y_error_de_consulta(tmp_path):
    c, _ = juzgar(tmp_path, cambiar=lambda tid, x: None if tid == "resp_prueba0001" else x)
    assert c.estado == vp.FALLA and any("resp_prueba0001 no aparece en las trazas" in d for d in c.detalles)
    reciente = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    (tmp_path / "r").mkdir()
    c, _ = juzgar(tmp_path / "r", lambda d: [t.update(hora=reciente) for t in d["tareas"]],
                  cambiar=lambda tid, x: None if tid == "resp_prueba0001" else x)
    assert c.estado == vp.NOV and any("ingesta" in d for d in c.detalles), c.detalles
    (tmp_path / "t").mkdir()   # tope alcanzado y una tarea sin filas: no se juzga, FALLA en alto
    c, _ = juzgar(tmp_path / "t", filas_extra=vp.TOPE_FILAS_TAREAS,
                  cambiar=lambda tid, x: None if tid == "resp_prueba0001" else x)
    assert c.estado == vp.FALLA and any("tope" in d and "no todas" in d for d in c.detalles), c.detalles
    (tmp_path / "t2").mkdir()  # tope alcanzado pero cada tarea probada: vale (Revisión, I1.4)
    c, _ = juzgar(tmp_path / "t2", filas_extra=vp.TOPE_FILAS_TAREAS)
    assert c.estado == vp.OK and any("cada tarea queda probada" in d for d in c.detalles), c.detalles
    (tmp_path / "e").mkdir()
    c, _ = juzgar(tmp_path / "e", error="sin red")
    assert c.estado == vp.NOV and any("sin red" in d for d in c.detalles)


def _detalles_procedencia(c: vp.Comprobacion) -> list[str]:
    return [d for d in c.detalles if vp.NOMBRE_PROCEDENCIA in d or "procedencia" in d]


def test_estructura_e_integridad_con_la_procedencia(tmp_path):
    for sub, kw, motivo in (("ok", {}, None), ("sin_man", {"en_manifiesto": False}, "el manifiesto no lo lista"),
                            ("bytes", {"bytes_otros": True}, None)):
        (tmp_path / sub).mkdir()
        z = paquete_b(tmp_path / sub, **kw)
        ctx = contexto(z, tmp_path / sub, None)
        est = vp.c_estructura(ctx)
        integ = vp.c_integridad(ctx)
        if motivo:
            assert est.estado == vp.FALLA and any(motivo in d for d in est.detalles), est.detalles
        else:
            assert not _detalles_procedencia(est) and est.estado != vp.FALLA, est.detalles
        tocado = [d for d in integ.detalles if d.startswith(vp.NOMBRE_PROCEDENCIA)]
        assert bool(tocado) == (sub == "bytes"), integ.detalles   # el SHA-256 del manifiesto lo cubre
    (tmp_path / "sin_fichero").mkdir()
    z = paquete_b(tmp_path / "sin_fichero")
    with zipfile.ZipFile(z) as zf:
        miembros = {n: zf.read(n) for n in zf.namelist() if n != vp.NOMBRE_PROCEDENCIA}
    with zipfile.ZipFile(z, "w") as zf:
        for n, b in miembros.items():
            zf.writestr(n, b)
    est = vp.c_estructura(contexto(z, tmp_path / "sin_fichero", None))
    assert est.estado == vp.FALLA and any("lo lista y no está" in d for d in est.detalles)


def _paquete_a(tmp: pathlib.Path, mutar_estado=None) -> pathlib.Path:
    """El paquete real tal cual (sin procedencia: camino de A), con el estado opcionalmente cambiado."""
    with zipfile.ZipFile(REAL) as zf:
        miembros = {n: zf.read(n) for n in zf.namelist()}
    if mutar_estado:
        est = json.loads(miembros["estado.json"])
        mutar_estado(est)
        miembros["estado.json"] = json.dumps(est, ensure_ascii=False).encode("utf-8")
    destino = tmp / REAL.name
    with zipfile.ZipFile(destino, "w") as zf:
        for n, b in miembros.items():
            zf.writestr(n, b)
    return destino


def test_a_sin_procedencia_ventana_de_la_ejecucion_orden_y_tope(tmp_path):
    """REV13-2: desde el enrutar/consolidar de la ejecución hasta su registro, por hora descendente y con tope."""
    consultas = []

    def kql(q):
        consultas.append(q)
        return []
    z = _paquete_a(tmp_path)
    c = vp.c_procedencia(contexto(z, tmp_path, kql))
    assert c.estado == vp.NOV and len(consultas) == 6, c.detalles
    # experto: enrutar n=12 (23:02:41+02:00) menos 5 min, hasta registrar-experto n=14 (23:07:03+02:00) más 5 min
    assert "between (datetime(2026-10-09T20:57:41Z) .. datetime(2026-10-09T21:12:03Z))" in consultas[0]
    assert "BRF-OF-BREZALIA-001-A-AZ-R2" in consultas[0]
    # lotes: consolidar n=15 (23:07:03) a registrar-verificacion n=20 (23:09:10)
    assert all("between (datetime(2026-10-09T21:02:03Z) .. datetime(2026-10-09T21:14:10Z))" in q for q in consultas[1:])
    assert all(q.rstrip().endswith(f"| order by timestamp desc | take {vp.TOPE_FILAS}") for q in consultas)


def test_a_tope_alcanzado_falla_salvo_coincidencia_completa(tmp_path):
    est = json.loads(zipfile.ZipFile(REAL).read("estado.json"))
    resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]

    def lleno(con_buena):
        def kql(q):
            filas = [{"op": f"op{i}", "dims": json.dumps({"x": "BRF-OF-BREZALIA-001-A-AZ-R2"})} for i in range(vp.TOPE_FILAS)]
            if con_buena and "BRF-" in q:
                filas[0] = {"op": "buena", "dims": json.dumps({"gen_ai.output": json.dumps(resp, ensure_ascii=False)})}
            return filas
        return kql
    (tmp_path / "1").mkdir()
    c = vp.c_procedencia(contexto(_paquete_a(tmp_path / "1"), tmp_path / "1", lleno(False)))
    assert c.estado == vp.FALLA and any("experto" in d and "tope de 200 filas" in d for d in c.detalles), c.detalles
    (tmp_path / "2").mkdir()
    c = vp.c_procedencia(contexto(_paquete_a(tmp_path / "2"), tmp_path / "2", lleno(True)))
    assert any(d.startswith("experto: la salida A2A registrada") for d in c.detalles), c.detalles


def test_a_ventana_por_fecha_si_no_hay_control_de_versiones(tmp_path):
    consultas = []
    z = _paquete_a(tmp_path, lambda e: e.update(control_versiones=[]))
    vp.c_procedencia(contexto(z, tmp_path, lambda q: consultas.append(q) or []))
    assert "between (datetime(2026-10-08T00:00:00Z) .. datetime(2026-10-11T00:00:00Z))" in consultas[0]


def test_b_relectura_no_hecha_es_no_verificado(tmp_path):
    """Decisión 3 del comercial (11-10-2026, REV-3): sin relectura, esa salida queda NO VERIFICADO (antes, AVISO)."""
    c, _ = juzgar(tmp_path, lambda d: d["tareas"][0]["relectura"].update(coincide=None, error="TASK_NOT_FOUND"))
    assert c.estado == vp.NOV and any("TASK_NOT_FOUND" in d and "decisión 3" in d for d in c.detalles), c.detalles
