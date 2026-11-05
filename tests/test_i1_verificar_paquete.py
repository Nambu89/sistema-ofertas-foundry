"""Pruebas de verificar_paquete.py (papel E de I1): paquetes reales buenos y malos, sin red.

Cada paquete malo introduce UN defecto y debe dar rc != 0 con su motivo en la salida (LES-G-091).
Los paquetes se construyen con el generador canónico real (tests/fixtures_i1/construir.py).
"""
from __future__ import annotations

import json
import pathlib
import zipfile

import openpyxl
import pytest

import verificar_paquete as vp
from tests.fixtures_i1 import construir as k

HOY = "2026-10-10"


@pytest.fixture(autouse=True)
def sin_nucleo(tmp_path_factory, monkeypatch, request):
    """Por defecto, réplica local: las pruebas no dependen del estado de sandbox/nucleo (A y C)."""
    if "con_nucleo_del_repositorio" not in request.node.name:
        monkeypatch.setattr(vp, "DIR_SANDBOX", tmp_path_factory.mktemp("sin_nucleo"))
    # Aislamiento declarado: estos paquetes los dibuja un PPTX sintético (pptx_fixture), no el núcleo, así
    # que la recomposición local daría FALLA en todos. Se prueba aparte, con paquetes reales del núcleo
    # vigente y las roturas reselladas de romper.py (test_i1_verificar_romper.py).
    monkeypatch.setattr(vp, "COMPROBACIONES", [f for f in vp.COMPROBACIONES if f is not vp.c_recomposicion])


def verificar(capsys, paquete, *extra, **inyectado):
    rc = vp.main(k.argumentos(paquete, *extra), **inyectado)
    return rc, capsys.readouterr().out


def fallan(salida: str) -> list[str]:
    return [ln.split("]")[1].split(":")[0].strip() for ln in salida.splitlines() if ln.startswith("[FALLA]")]


@pytest.fixture(scope="module")
def bueno(tmp_path_factory) -> pathlib.Path:
    return k.construir(tmp_path_factory.mktemp("bueno"))


def test_paquete_bueno_da_rc_0(capsys, bueno):
    rc, out = verificar(capsys, bueno)
    assert rc == 0, out
    assert "VEREDICTO: OK CON NO VERIFICADOS rc=0" in out and "ATENCIÓN: lo NO VERIFICADO" in out
    assert "[OK] diagrama" in out and "corta el texto" not in out  # I1.5: los cortes ya son FALLA (PR14-3)
    assert "[NO VERIFICADO] procedencia_a2a" in out and "[NO VERIFICADO] referencias_vivas" in out
    assert "generar_estimacion.py --verificar rc=0" in out


def test_paquete_bueno_en_carpeta(capsys, tmp_path):
    carpeta = k.construir(tmp_path, zip_=False)
    rc, out = verificar(capsys, carpeta)
    assert rc == 0, out


def test_json_del_informe(capsys, bueno, tmp_path):
    salida = tmp_path / "informe.json"
    rc, _ = verificar(capsys, bueno, "--json", str(salida))
    inf = json.loads(salida.read_text(encoding="utf-8"))
    assert rc == 0 and inf["veredicto"] == "OK CON NO VERIFICADOS" and inf["codigo"] == "OF-KELVARA-001-A"
    assert {c["id"] for c in inf["comprobaciones"]} >= {"integridad", "estimacion", "marca", "decisiones"}


def test_pm_menor_de_8_horas(capsys, tmp_path):
    def pm_corto(e):
        for t in e["carga"]["estimacion"]["entrada"]["tareas"]:
            if t["id"] == "PM-01":
                t["tecnicas_h"], t["reuniones_h"] = 4, 1
    rc, out = verificar(capsys, k.construir(tmp_path, mutar_carga=pm_corto))
    assert rc == 1 and "< 8 h (LES-G-001)" in out


def test_ajuste_encubierto_en_el_xlsx(capsys, tmp_path):
    def ajuste(entrada):
        entrada["ajuste_comercial_eur"] = -500
        entrada["ajuste_comercial_motivo"] = "Descuento acordado sin decisión registrada"
    rc, out = verificar(capsys, k.construir(tmp_path, entrada_xlsx=ajuste))
    assert rc == 1 and "sin decisión AJUSTE_COMERCIAL" in out


def test_tarifa_alterada_en_el_xlsx(capsys, tmp_path):
    def subir_tarifa(ruta):
        wb = openpyxl.load_workbook(ruta)
        ws = wb[vp.HOJA_RES]
        for fila in range(7, 20):
            if ws.cell(fila, 1).value == "Consultor Junior":
                ws.cell(fila, 3).value = 70
        wb.save(ruta)
    rc, out = verificar(capsys, k.construir(tmp_path, tocar_xlsx=subir_tarifa))
    assert rc == 1 and "ajuste encubierto" in out


def k_tarifa() -> dict:
    return vp.cargar_tarifa(vp.POR_DEFECTO["rate_card"])


def _pm_inflado(e):
    """Antes de REV-1 era la forma de pasar de 100.000 EUR; ahora salta la regla de estimación del 10-10-2026."""
    tareas = e["carga"]["estimacion"]["entrada"]["tareas"]
    for n in (2, 3, 4):
        tareas.append({"id": f"PM-0{n}", "fase": "Gestión de proyecto", "tarea": f"Gestión ampliada {n}",
                       "perfil": "Project Manager", "tecnicas_h": 400, "reuniones_h": 0,
                       "descripcion": "Gestión ampliada del programa con el cliente.", "entregable": "Informe"})


def _pm_grande(e):
    """REV-1 (I1.4): un proyecto grande de verdad (400 h por tarea propuesta) y la entrada que compone la regla."""
    resp = e["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    for t in resp["tareas_propuestas"]:
        t["horas_base"] = 400
    # en estas pruebas la puerta corre sin núcleo: la entrada sale de su réplica local de la regla
    e["carga"]["estimacion"]["entrada"].update(vp.regla_estimacion_replica(resp, k_tarifa()["hitos_pago"]))


def test_pm_inflado_salta_la_regla_de_estimacion(capsys, tmp_path):
    """REV-1: XLSX, resumen y textos coherentes con la entrada inflada; solo la regla lo detecta."""
    rc, out = verificar(capsys, k.construir(tmp_path, mutar_carga=_pm_inflado))
    assert rc == 1 and fallan(out) == ["estimacion"], out
    assert "estimacion.entrada.tareas no es lo que compone la regla del 10-10-2026" in out
    assert "10 elementos y la regla da 7" in out  # PM-02 a PM-04 de más


def test_mas_de_100000_sin_stop(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, mutar_carga=_pm_grande))
    assert rc == 1 and "> 100.000 EUR sin CONFIRMA_STOP" in out and "exige --confirmo-stop" in out
    assert fallan(out) == ["estimacion"], out


def test_mas_de_100000_con_stop_confirmado(capsys, tmp_path):
    def stop(e):
        k.decision(e, "Responsable comercial", "CONFIRMA_STOP", "2026-10-08", e["hash_contenido"],
                   "Programa grande confirmado con el cliente", "STOP_PRESUPUESTO", "VERIFICADA")
    paquete = k.construir(tmp_path, mutar_carga=_pm_grande, mutar_estado=stop)
    h = json.loads(zipfile.ZipFile(paquete).read("estado.json"))["hash_contenido"]
    rc, out = verificar(capsys, paquete)  # R2: la decisión del estado sola no basta
    assert rc == 1 and "exige --confirmo-stop" in out and fallan(out) == ["estimacion"], out
    rc, out = verificar(capsys, paquete, "--confirmo-stop", "f" * 64)
    assert rc == 1 and "no es el hash vigente" in out, out
    rc, out = verificar(capsys, paquete, "--confirmo-stop", h)
    assert rc == 0, out
    assert "STOP confirmado por D-001" in out and "--confirmo-stop: confirmado en local" in out


@pytest.mark.parametrize("extra,motivo", [
    ({7: ["Esfuerzo estimado: 279 horas"]}, "horas"),
    ({5: ["Equipo: Project Manager y Consultor Junior"]}, "nombre de perfil de la tarifa"),
    ({10: ["Tarifa aplicada: 65 €/h"]}, "importe por hora o jornada"),
    ({3: ["Ver requisitos.json y el campo catalogo_id"]}, "nombre de fichero"),
    ({6: ["Supuesto ligado a R-volumetria y C-02"]}, "id de requisito"),
])
def test_lo_que_no_puede_ver_el_cliente(capsys, tmp_path, extra, motivo):
    rc, out = verificar(capsys, k.construir(tmp_path, pptx_op={"extra": extra}))
    assert rc == 1 and "cliente_les_g_053" in fallan(out) and motivo in out, out


def test_notas_del_orador_prohibidas(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, pptx_op={"nota": "Margen interno del 20 por ciento"}))
    assert rc == 1 and "notas del orador" in out


@pytest.mark.parametrize("donde,motivo", [
    ({"pptx_op": {"extra": {3: ["Volumetría por definir con el cliente"]}}}, "marcador «por definir»"),
    ({"docx_extra": ["Revisión TBD"]}, "marcador «TBD»"),
    ({"mensaje_extra": "Adjunto <ZIP>\n"}, "marcador «<ZIP>»"),
])
def test_marcadores(capsys, tmp_path, donde, motivo):
    rc, out = verificar(capsys, k.construir(tmp_path, **donde))
    assert rc == 1 and "marcadores" in fallan(out) and motivo in out, out


def test_palabras_que_contienen_marcadores_no_son_marcadores():
    assert vp.marcadores_replica("Un verificador independiente revisa Todos los textos") == []
    assert vp.marcadores_replica("Queda pendiente") and vp.marcadores_replica("TODO: x")


def test_sin_montserrat(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, pptx_op={"cara": "Calibri"}))
    assert rc == 1 and "marca" in fallan(out) and "sin Montserrat" in out


def test_docx_sin_montserrat(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, docx_fuente="Arial"))
    assert rc == 1 and "DOCX: la fuente por defecto (docDefaults) no es Montserrat" in out


def test_anexo_con_color_fuera_de_paleta(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, anexo_color="0000FF"))
    assert rc == 1 and "fuera de la paleta" in out


def test_diagrama_incompleto(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, pptx_op={"omitir_componente": "Azure AI Search"}))
    assert rc == 1 and "diagrama" in fallan(out) and "azure ai search" in out


def test_diagrama_sustituido_por_tabla_con_aviso(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, pptx_op={"tabla_arq": True}))
    assert rc == 0, out
    assert "[AVISO] diagrama" in out


def test_hash_cambiado_tras_el_manifiesto(capsys, tmp_path):
    def tocar(carpeta):
        p = carpeta / "estado.json"
        e = json.loads(p.read_text(encoding="utf-8"))
        e["carga"]["alta"]["titulo"] += " ampliado"
        p.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    rc, out = verificar(capsys, k.construir(tmp_path, despues=tocar))
    assert rc == 1 and "integridad" in fallan(out)
    assert "distinto de estado_json_sha256" in out and "el recalculado es" in out


def test_hash_recalculado_pero_documentos_viejos(capsys, tmp_path):
    """Manipulación coherente del estado y del manifiesto: el PPTX y la nota delatan el hash viejo."""
    def tocar(carpeta):
        p = carpeta / "estado.json"
        e = json.loads(p.read_text(encoding="utf-8"))
        e["carga"]["alta"]["titulo"] += " ampliado"
        e["hash_contenido"] = vp.hash_json(e["carga"])
        p.write_bytes(json.dumps(e, ensure_ascii=False).encode("utf-8"))
        m = json.loads((carpeta / "manifiesto_paquete.json").read_text(encoding="utf-8"))
        m["hash_contenido"], m["estado_json_sha256"] = e["hash_contenido"], k.sha(p.read_bytes())
        for f in m["ficheros"]:
            if f["nombre"] == "estado.json":
                f["sha256"], f["bytes"] = k.sha(p.read_bytes()), p.stat().st_size
        (carpeta / "manifiesto_paquete.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    rc, out = verificar(capsys, k.construir(tmp_path, despues=tocar))
    assert rc == 1 and "PPTX: keywords" in out and "hash_hechos no cuadra" in out


def _en_aprobacion(hash_javier: str | None = None):
    def mutar(e):
        h = e["hash_contenido"]
        e["estado"] = "EN_APROBACION_AREA"
        k.decision(e, "Responsable comercial", "ENVIADA_REVISION", "2026-10-08", h,
                   "verificar_paquete rc=0", "LISTA_PARA_REVISION", "EN_REVISION_PREVENTA")
        k.decision(e, "Responsable de preventa", "APROBADA", "2026-10-09", hash_javier or h,
                   "Arquitectura y precios revisados", "EN_REVISION_PREVENTA", "EN_APROBACION_AREA")
    return mutar


def test_decisiones_validas(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, mutar_estado=_en_aprobacion(),
                                            firmas={"revisado": "Responsable de preventa, 2026-10-09"}))
    assert rc == 0, out


def test_decision_con_hash_viejo(capsys, tmp_path):
    rc, out = verificar(capsys, k.construir(tmp_path, mutar_estado=_en_aprobacion("0" * 64)))
    assert rc == 1 and "decisiones" in fallan(out) and "(hash viejo)" in out


def test_revisor_equivocado(capsys, tmp_path):
    def mutar(e):
        e["estado"] = "EN_REVISION_PREVENTA"
        k.decision(e, "Responsable de área", "ENVIADA_REVISION", "2026-10-08", e["hash_contenido"],
                   "verificar_paquete rc=0", "LISTA_PARA_REVISION", "EN_REVISION_PREVENTA")
    rc, out = verificar(capsys, k.construir(tmp_path, mutar_estado=mutar))
    assert rc == 1 and "no puede registrar ENVIADA_REVISION" in out


def test_previo_aprobado_solo_cambia_la_diapositiva_2(capsys, tmp_path):
    previo = k.construir(tmp_path / "a")
    def aprobado(e):
        _en_aprobacion()(e)
        e["estado"] = "APROBADA"
        k.decision(e, "Responsable de área", "APROBADA", "2026-10-10", e["hash_contenido"], "Conforme",
                   "EN_APROBACION_AREA", "APROBADA")
    final = k.construir(tmp_path / "b", mutar_estado=aprobado, pptx_op={"revision": 2},
                        firmas={"revisado": "Responsable de preventa, 2026-10-09", "aprobado": "Responsable de área, 2026-10-10"})
    rc, out = verificar(capsys, final, "--previo", str(previo))
    assert rc == 0, out
    assert "solo cambian la diapositiva 2" in out


def test_conector_que_corta_el_texto_de_una_forma_falla_en_diagrama(capsys, tmp_path):
    """I1.5 (PR14-3, CAMBIOS-I15-D §2): un conector pegado que atraviesa el texto de una forma es FALLA, no aviso."""
    rc, out = verificar(capsys, k.construir(tmp_path, pptx_op={"conector_cruzado": True}))
    assert rc == 1 and fallan(out) == ["diagrama"], out
    assert "corta el texto de la forma" in out and "PR14-3" in out


def test_previo_con_otra_diapositiva_cambiada(capsys, tmp_path):
    previo = k.construir(tmp_path / "a")
    final = k.construir(tmp_path / "b", pptx_op={"extra": {9: ["Riesgo añadido después de la aprobación."]}})
    rc, out = verificar(capsys, final, "--previo", str(previo))
    assert rc == 1 and "paquete_previo" in fallan(out) and "solo pueden cambiar la diapositiva 2" in out


def test_cita_que_no_esta_en_la_transcripcion(capsys, tmp_path):
    def mutar(e):
        e["carga"]["requisitos"]["campos"]["objetivo"]["entradas"][0]["cita"] = "una frase que nadie dijo en la reunión"
    rc, out = verificar(capsys, k.construir(tmp_path, mutar_carga=mutar))
    assert rc == 1 and "la cita no aparece en la fuente" in out


def test_discrepa_de_precio_mayor_del_medio_por_ciento(capsys, tmp_path):
    """Integrador I1.7 (decisión 1): el verificador ya no recibe precios; un veredicto de precio forjado en la respuesta
    del verificador (P-01 con otro precio) es un id que no se le envió: FALLA, y además se ve la diferencia de precio."""
    def mutar(e):
        els = e["carga"]["verificacion"]["respuesta"]["elementos"]
        els.append(dict(els[0], id="P-01", tipo="precio", veredicto="OK", valor_correcto="0.40", campo="ninguno"))
    rc, out = verificar(capsys, k.construir(tmp_path, mutar_carga=mutar))
    assert rc == 1 and "no hay exactamente un veredicto por id enviado al verificador" in out
    assert "DISCREPA efectivo: P-01" in out


def test_zip_con_fichero_extra_y_ruta(capsys, tmp_path):
    z = k.construir(tmp_path)
    with zipfile.ZipFile(z, "a") as zf:
        zf.writestr("../fuera.txt", "x")
        zf.writestr("otro.txt", "x")
    rc, out = verificar(capsys, z)
    assert rc == 1 and "entrada no plana o con ruta" in out and "fichero no previsto en el paquete: otro.txt" in out


def test_entrada_ilegible_da_rc_2(capsys, tmp_path):
    (tmp_path / "roto.zip").write_bytes(b"no es un zip")
    rc, out = verificar(capsys, tmp_path / "roto.zip")
    assert rc == 2 and "ENTRADA ILEGIBLE" in out


def test_archivar_y_auditar(capsys, tmp_path, bueno):
    ws = tmp_path / "workspace"
    (ws / "_clientes" / "Kelvara").mkdir(parents=True)
    rc, out = verificar(capsys, bueno, "--archivar", "Kelvara", "--workspace", str(ws))
    assert rc == 0, out
    destino = ws / "_clientes" / "Kelvara" / "docs" / ".checkpoints" / "OF-KELVARA-001-A"
    assert (destino / "OF-KELVARA-001-A-Paquete-LISTA_PARA_REVISION.zip").read_bytes() == bueno.read_bytes()
    assert (destino / "verificacion-LISTA_PARA_REVISION.json").exists()
    lineas = (ws / "_audit" / "log.jsonl").read_text(encoding="utf-8").splitlines()
    linea = json.loads(lineas[-1])
    assert linea["codigo"] == "OF-KELVARA-001-A" and linea["veredicto"] == "OK CON NO VERIFICADOS" and linea["total_eur"] == 28025.25
    rc, out = verificar(capsys, bueno, "--archivar", "Kelvara", "--workspace", str(ws))
    assert rc == 0 and "ya archivado" in out
    assert len((ws / "_audit" / "log.jsonl").read_text(encoding="utf-8").splitlines()) == 2


def test_no_se_archiva_un_paquete_malo(capsys, tmp_path):
    ws = tmp_path / "workspace"
    (ws / "_clientes" / "Kelvara").mkdir(parents=True)
    malo = k.construir(tmp_path / "m", pptx_op={"extra": {7: ["Esfuerzo: 279 horas"]}})
    rc, out = verificar(capsys, malo, "--archivar", "Kelvara", "--workspace", str(ws))
    assert rc == 1 and "NO SE ARCHIVA" in out
    assert not (ws / "_audit" / "log.jsonl").exists() and not (ws / "_clientes" / "Kelvara" / "docs").exists()


def test_archivar_en_cliente_inexistente_da_rc_2(capsys, tmp_path, bueno):
    rc, out = verificar(capsys, bueno, "--archivar", "NoExiste", "--workspace", str(tmp_path))
    assert rc == 2 and "no existe la carpeta del cliente" in out


def _con_red(paquete, *extra):
    return [a for a in k.argumentos(paquete, *extra) if a != "--sin-red"]


def _web(estado=200, titulo="Baseline Microsoft Foundry chat reference architecture - Azure Architecture Center"):
    return lambda url: (estado, url, f"<html><head><title>{titulo}</title></head></html>")


def test_referencias_vivas_y_trazas_no_apuntadas(capsys, bueno):
    conexiones = lambda: [{"properties": {"category": "AppInsights", "target": "/subscriptions/x/components/otro"}}]
    rc = vp.main(_con_red(bueno), http_get=_web(), conexiones_appi=conexiones)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "[OK] referencias_vivas" in out
    assert "no apunta a appi-preventa-ejemplo" in out and "[NO VERIFICADO] procedencia_a2a" in out


@pytest.mark.parametrize("web,motivo", [(_web(404), "HTTP 404"), (_web(200, "Page not found"), "soft 404"),
                                        (_web(200, ""), "sin título")])
def test_referencia_muerta(capsys, bueno, web, motivo):
    rc = vp.main(_con_red(bueno), http_get=web, conexiones_appi=lambda: [])
    out = capsys.readouterr().out
    assert rc == 1 and motivo in out


def _trazas(cambiar: bool):
    estado = json.loads((k.EJEMPLOS / "estado.json").read_text(encoding="utf-8"))
    def kql(consulta):
        if "BRF-" in consulta:
            r = dict(estado["carga"]["respuestas_expertos"]["azure"]["respuesta"])
        else:
            r = dict(estado["carga"]["verificacion"]["respuesta"])
        if cambiar:
            r["agente"] = r["agente"] + "-falso"
        return [{"name": "execute_tool a2a", "dims": json.dumps({"gen_ai.tool.call.result": json.dumps(r)})}]
    return kql


@pytest.mark.parametrize("cambiar,esperado", [(False, 0), (True, 1)])
def test_procedencia_por_trazas(capsys, bueno, cambiar, esperado):
    conexiones = lambda: [{"properties": {"category": "AppInsights",
                                          "target": "/subscriptions/x/components/appi-preventa-ejemplo"}}]
    rc = vp.main(_con_red(bueno), http_get=_web(), conexiones_appi=conexiones, consultar_kql=_trazas(cambiar))
    out = capsys.readouterr().out
    assert rc == esperado, out
    if cambiar:
        assert "no coincide con la del estado" in out
    else:
        assert "coincide con la del estado" in out and "[OK] procedencia_a2a" in out


def test_modulo_de_nucleo_roto_no_se_toma_por_ausente(capsys, bueno, tmp_path, monkeypatch):
    import sys
    nucleo = tmp_path / "sandbox" / "nucleo"
    nucleo.mkdir(parents=True)
    (nucleo / "__init__.py").write_text("", encoding="utf-8")
    (nucleo / "hashes.py").write_text("import modulo_que_no_existe\n", encoding="utf-8")
    monkeypatch.setattr(vp, "DIR_SANDBOX", tmp_path / "sandbox")
    for m in [m for m in sys.modules if m == "nucleo" or m.startswith("nucleo.")]:
        monkeypatch.delitem(sys.modules, m)
    try:
        rc, out = verificar(capsys, bueno)
    finally:
        for m in [m for m in sys.modules if m == "nucleo" or m.startswith("nucleo.")]:
            del sys.modules[m]
        while str(tmp_path / "sandbox") in sys.path:
            sys.path.remove(str(tmp_path / "sandbox"))
    assert rc == 1 and "modulo_que_no_existe" in out


def test_paquete_bueno_con_nucleo_del_repositorio(capsys, bueno):
    """Con sandbox/nucleo completo, hash y barridos de nucleo deben coincidir con la réplica."""
    import importlib
    import sys
    try:
        sys.path.insert(0, str(vp.RAIZ / "sandbox"))
        for m in ("hashes", "textos_cliente"):
            importlib.import_module(f"nucleo.{m}")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"sandbox/nucleo aún no está completo: {type(e).__name__}: {e}")
    rc, out = verificar(capsys, bueno)
    assert rc == 0, out


def test_previo_incompleto_no_sirve_de_referencia(capsys, tmp_path, bueno):
    previo = k.construir(tmp_path / "a", zip_=False)
    (previo / "OF-KELVARA-001-A-Anexo-Consumo.xlsx").unlink()
    rc, out = verificar(capsys, bueno, "--previo", str(previo))
    assert rc == 1 and "no sirve como referencia" in out
