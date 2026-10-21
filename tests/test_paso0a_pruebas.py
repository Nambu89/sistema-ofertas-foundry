"""Funciones puras de P1…P5 y de limpiar_pruebas (sin red)."""
from __future__ import annotations

import datetime as dt
import json
import zipfile

import pytest

from pruebas.paso0a import limpiar_pruebas, p1_ciclo_vida as p1, p2_decision as p2, p3_herramientas as p3
from pruebas.paso0a import p4_hosted as p4, p5_opencode as p5
from pruebas.paso0a.hosted_prueba import empaquetar

HOY = dt.date(2026, 10, 18)


# ------------------------------------------------------------------------------------------- P1
@pytest.mark.parametrize("fecha,meses,esperado", [
    (dt.date(2026, 10, 18), 6, dt.date(2027, 4, 18)), (dt.date(2026, 1, 31), 1, dt.date(2026, 2, 28)),
    (dt.date(2028, 1, 31), 1, dt.date(2028, 2, 29)), (dt.date(2026, 12, 15), 1, dt.date(2027, 1, 15)),
    (dt.date(2026, 10, 18), 18, dt.date(2028, 4, 18)), (dt.date(2026, 8, 31), 6, dt.date(2027, 2, 28))])
def test_sumar_meses(fecha, meses, esperado):
    assert p1.sumar_meses(fecha, meses) == esperado


def test_umbral_supuesto_declarado():
    fin, umbral = p1.umbral_retirada(HOY)
    assert fin == dt.date(2027, 4, 18) and umbral == dt.date(2028, 4, 18)


@pytest.mark.parametrize("valor,esperado", [
    ("2028-01-11T00:00:00Z", dt.date(2028, 1, 11)), ("2028-01-11", dt.date(2028, 1, 11)),
    ("2028-01-11T00:00:00.0000000Z", dt.date(2028, 1, 11)), ("", None), (None, None), ("pronto", None), (42, None)])
def test_leer_fecha(valor, esperado):
    assert p1.leer_fecha(valor) == esperado


def _desp(nombre, modelo, version, sku, formato="OpenAI"):
    return {nombre: {"name": nombre, "sku": {"name": sku},
                     "properties": {"model": {"name": modelo, "version": version, "format": formato}}}}


def test_luna_2028_01_11_no_cumple_con_el_supuesto():
    """gpt-5.6-luna se retira el 2028-01-11 (LES-G-036): con fin = hoy + 6 meses, no llega a fin + 12."""
    _, umbral = p1.umbral_retirada(HOY)
    modelos = [{"name": "gpt-5.6-luna", "version": "1", "format": "OpenAI",
                "deprecation": {"inference": "2028-01-11T00:00:00Z"}}]
    r = p1.evaluar_despliegue("gpt-5.6-luna", {"sku": "DataZoneStandard"},
                              _desp("gpt-5.6-luna", "gpt-5.6-luna", "1", "DataZoneStandard"), modelos, umbral)
    assert not r["cumple"] and "2028-01-11" in r["motivo"] and r["apto_datos_reales"]


def test_fecha_mas_temprana_entre_modelo_y_sku():
    modelos = [{"model": {"name": "m", "version": "1", "deprecation": {"inference": "2030-01-01"},
                          "skus": [{"name": "GlobalStandard", "deprecationDate": "2027-06-30"},
                                   {"name": "DataZoneStandard", "deprecationDate": "2026-11-01"}]}}]
    r = p1.evaluar_despliegue("m", {}, _desp("m", "m", "1", "GlobalStandard"), modelos, dt.date(2028, 4, 18))
    assert r["retirada"] == "2027-06-30" and r["origen_fecha"].startswith("skus[") and not r["cumple"]
    assert r["apto_datos_reales"] is False


def test_sin_fecha_falla_y_sin_despliegue_falla():
    modelos = [{"name": "Microsoft-Decision-1", "version": "1", "format": "Microsoft"}]
    d = _desp("Decision-1", "Microsoft-Decision-1", "1", "DataZoneStandard", "Microsoft")
    r = p1.evaluar_despliegue("Decision-1", {"sku": "DataZoneStandard"}, d, modelos, dt.date(2028, 4, 18))
    assert not r["cumple"] and "sin fecha" in r["motivo"]
    r2 = p1.evaluar_despliegue("no-existe", {}, d, modelos, dt.date(2028, 4, 18))
    assert not r2["cumple"] and "no existe" in r2["motivo"]


def test_sku_o_version_distintos_de_config_fallan():
    modelos = [{"name": "gpt-6-luna", "version": "2026-09-22", "deprecation": {"inference": "2099-01-01"}}]
    d = _desp("gpt-6-luna", "gpt-6-luna", "2026-09-22", "GlobalStandard")
    r = p1.evaluar_despliegue("gpt-6-luna", {"sku": "DataZoneStandard", "version": "2026-09-22"}, d, modelos,
                              dt.date(2028, 4, 18))
    assert not r["cumple"] and "SKU real" in r["motivo"]
    r2 = p1.evaluar_despliegue("gpt-6-luna", {"sku": "GlobalStandard", "version": "2026-10-01"}, d, modelos,
                               dt.date(2028, 4, 18))
    assert not r2["cumple"] and "versión real" in r2["motivo"]


def test_retirada_igual_al_umbral_no_cumple():
    modelos = [{"name": "m", "version": "1", "deprecation": {"inference": "2028-04-18"}}]
    r = p1.evaluar_despliegue("m", {}, _desp("m", "m", "1", "DataZoneStandard"), modelos, dt.date(2028, 4, 18))
    assert not r["cumple"]


# ------------------------------------------------------------------------------------------- P2
def test_cuerpos_decision_con_formato_de_learn():
    for tipo in ("noul", "choice", "score"):
        c = p2.cuerpo("Decision-1", tipo)
        assert c["model"] == "Decision-1" and set(c) == {"model", "state", "questions"}
        (nombre, q), = c["questions"].items()
        assert q["type"] == tipo and q["instructions"]
    assert set(p2.cuerpo("D", "noul")["questions"]["incluye_pm_minimo"]["criteria"]) == {"true", "false"}
    assert isinstance(p2.cuerpo("D", "score")["questions"]["riesgo_plazo"]["criteria"], list)


@pytest.mark.parametrize("tipo,ans,ok", [
    ("noul", {"type": "noul", "probability": 0.8}, True),
    ("noul", {"type": "noul", "probability": 1.3}, False),
    ("noul", {"type": "choice", "probability": 0.8}, False),
    ("noul", {"type": "noul", "probability": float("nan")}, False),
    ("noul", {"type": "noul", "probability": True}, False),
    ("choice", {"type": "choice", "choice": "rag"}, True),
    ("choice", {"type": "choice", "choice": "otra"}, False),
    ("score", {"type": "score", "score": 2.4}, True),
    ("score", {"type": "score", "score": 3.5}, False),
    ("score", {"type": "score", "score": 7, "probabilidad": 0.2}, False),
    ("score", {"type": "score"}, False)])
def test_validar_respuesta_decision(tipo, ans, ok):
    nombre = p2.PREGUNTAS[tipo]["nombre"]
    assert p2.validar_respuesta(tipo, {"answers": {nombre: ans}})[0] is ok


def test_validar_respuesta_sin_answers():
    assert p2.validar_respuesta("noul", {"model": "x"})[0] is False
    assert p2.validar_respuesta("noul", None)[0] is False


def test_clasificar_fallo_decision():
    assert p2.clasificar_fallo([403, 403, 403]) == "PENDIENTE_FERNANDO"
    assert p2.clasificar_fallo([200, 404, 500]) == "FALLA"


# ------------------------------------------------------------------------------------------- P3
def test_definicion_prompt_agent():
    d = p3.definicion()
    assert d["kind"] == "prompt" and d["model"] == "gpt-5.6-luna"
    mcp = d["tools"][0]
    assert mcp["allowed_tools"] == {"tool_names": ["microsoft_docs_search", "microsoft_docs_fetch"]}
    assert mcp["require_approval"] == "never" and d["tools"][1] == {"type": "web_search"}
    assert all(t["type"] != "web_search" for t in p3.definicion(con_web=False)["tools"])


def test_cuerpo_respuesta_background_y_referencia():
    c = p3.cuerpo_respuesta("4", "pregunta")
    assert c["agent_reference"] == {"type": "agent_reference", "name": "ofa-prueba-herramientas", "version": "4"}
    assert c["background"] is True and c["store"] is True and c["tool_choice"] == "required"


def _resp(*items, status="completed", error=None):
    return {"status": status, "error": error, "output": list(items)}


def test_tipos_llamadas_excluye_mensajes():
    r = _resp({"type": "reasoning"}, {"type": "mcp_list_tools"}, {"type": "mcp_call"}, {"type": "message"})
    assert p3.tipos_llamadas(r) == ["mcp_list_tools", "mcp_call"]


def test_evaluar_mcp():
    ok = _resp({"type": "mcp_call", "server_label": "mslearn", "name": "microsoft_docs_search"})
    assert p3.evaluar_mcp(ok)[0] == "PASA"
    fuera = _resp({"type": "mcp_call", "server_label": "mslearn", "name": "microsoft_code_sample_search"})
    assert p3.evaluar_mcp(fuera)[0] == "FALLA"
    con_error = _resp({"type": "mcp_call", "server_label": "mslearn", "name": "microsoft_docs_fetch", "error": "x"})
    assert p3.evaluar_mcp(con_error)[0] == "FALLA"
    assert p3.evaluar_mcp(_resp({"type": "web_search_call"}))[0] == "FALLA"
    assert p3.evaluar_mcp(_resp(status="failed"))[0] == "FALLA"


def test_evaluar_web_y_clasificacion_del_bloqueo():
    assert p3.evaluar_web(_resp({"type": "web_search_call", "status": "completed"}))[0] == "PASA"
    assert p3.evaluar_web(_resp({"type": "mcp_call"}))[0] == "FALLA"
    sin_status = p3.evaluar_web(_resp({"type": "web_search_call"}))
    assert sin_status[0] == "FALLA" and "[None]" in sin_status[1]
    assert "['in_progress', 'completed']" in p3.evaluar_web(
        _resp({"type": "web_search_call", "status": "in_progress"}, {"type": "web_search_call", "status": "completed"}))[1]
    bloq = _resp(status="failed", error={"message": "Tool web_search requires Grounding with Bing"})
    assert p3.evaluar_web(bloq)[0] == "PENDIENTE_FERNANDO"
    otro = _resp(status="failed", error={"message": "server_error"})
    assert p3.evaluar_web(otro)[0] == "FALLA"
    assert p3.es_rechazo_web("OpenAI.BlockedTools.web_search") and not p3.es_rechazo_web("rate limit")


# ------------------------------------------------------------------------------------------- P4
def test_definicion_hosted_bundled_con_referencia_a_la_conexion():
    d = p4.definicion(True)
    assert d["kind"] == "hosted" and d["code_configuration"] == {
        "runtime": "python_3_13", "entry_point": ["python", "main.py"], "dependency_resolution": "bundled"}
    assert d["protocol_versions"] == [{"protocol": "responses", "version": "2.0.0"}]
    assert d["environment_variables"]["OFA_MARCADOR"] == "${{connections.ofa-prueba-marcador.credentials.valor}}"
    # Una referencia a una conexión inexistente hace fallar el despliegue (HTTP 400 real): sin conexión, no va.
    assert "OFA_MARCADOR" not in p4.definicion(False)["environment_variables"]
    assert "OFA_MARCADOR" not in p4.definicion(None)["environment_variables"]
    assert p4.definicion(True) != p4.definicion(False)   # crear la conexión fuerza una versión nueva


def test_multipart_partes():
    partes = p4.partes_multipart(p4.metadatos(None), b"PK\x03\x04")
    assert partes["metadata"][0] is None and partes["metadata"][2] == "application/json"
    assert json.loads(partes["metadata"][1])["definition"]["kind"] == "hosted"
    assert partes["code"] == ("ofa-prueba-hosted.zip", b"PK\x03\x04", "application/zip")


def test_cuerpo_orden():
    c = p4.cuerpo_orden("ORDEN: ECO x", background=True)
    assert c["input"][0]["content"][0] == {"type": "input_text", "text": "ORDEN: ECO x"}
    assert c["background"] is True and c["store"] is True
    assert "background" not in p4.cuerpo_orden("ORDEN: SALIDA")


def test_evaluar_salida():
    tres = {"resultados": [{"url": "a", "http": 200}, {"url": "b", "http": 403}, {"url": "c", "http": 400}]}
    assert p4.evaluar_salida(json.dumps(tres))[0] == "PASA"
    tres["resultados"][2] = {"url": "c", "error": "URLError: timed out"}
    estado, det = p4.evaluar_salida(json.dumps(tres))
    assert estado == "FALLA" and "SIN SALIDA" in det
    assert p4.evaluar_salida(json.dumps({"resultados": [{"url": "a", "http": 200}]}))[0] == "FALLA"
    assert p4.evaluar_salida("no es json")[0] == "FALLA"


def _marcador(**kw):
    base = {"orden": "MARCADOR", "variable_definida": True, "presente": True, "sin_resolver": False,
            "longitud": 18, "coincide_con_sintetico": True, "borrada_de_entorno": True}
    base.update(kw)
    return json.dumps(base)


def test_evaluar_marcador(cfg):
    assert p4.evaluar_marcador(_marcador(), True, cfg)[0] == "PASA"
    assert p4.evaluar_marcador(_marcador(coincide_con_sintetico=False), True, cfg)[0] == "FALLA"
    vacio = _marcador(presente=False, longitud=0, coincide_con_sintetico=False)
    assert p4.evaluar_marcador(vacio, True, cfg)[0] == "FALLA"
    estado, det = p4.evaluar_marcador(vacio, False, cfg)
    assert estado == "PENDIENTE_FERNANDO" and "marcador-sintetico" in det and "az rest --method put" in det
    assert p4.evaluar_marcador(vacio, None, cfg)[0] == "PENDIENTE_FERNANDO"
    assert p4.evaluar_marcador("basura", False, cfg)[0] == "FALLA"


def _turno(status="completed", medidos=360.2, marca="TURNO_LARGO COMPLETADO"):
    texto = json.dumps({"resultado": marca, "segundos_medidos": medidos})
    return {"status": status, "output": [{"type": "message", "content": [{"type": "output_text", "text": texto}]}]}


def test_evaluar_turno():
    assert p4.evaluar_turno(_turno())[0] == "PASA"
    assert p4.evaluar_turno(_turno(medidos=12))[0] == "FALLA"
    assert p4.evaluar_turno(_turno(status="failed"))[0] == "FALLA"
    assert p4.evaluar_turno(_turno(marca="otra"))[0] == "FALLA"
    assert p4.evaluar_turno(None)[0] == "FALLA"


def test_evaluar_api_version():
    eco = "ECO-OFA: x"
    estado, det = p4.evaluar_api_version({"http": 200, "texto": eco}, {"http": 400, "texto": "api-version"}, eco)
    assert estado == "PASA" and "NO funciona" in det
    estado, det = p4.evaluar_api_version({"http": 200, "texto": eco}, {"http": 200, "texto": eco}, eco)
    assert estado == "PASA" and "TAMBIÉN" in det
    assert p4.evaluar_api_version({"http": 404, "texto": ""}, {"http": 200, "texto": eco}, eco)[0] == "FALLA"


# --------------------------------------------------------------------------------- empaquetado
def test_bloqueo_desde_ruedas():
    assert empaquetar.bloqueo_desde_ruedas(["azure_core-1.41.0-py3-none-any.whl",
                                            "aiohttp-3.12.0-cp313-cp313-manylinux_2_17_x86_64.whl"]) == [
        "aiohttp==3.12.0", "azure-core==1.41.0"]
    with pytest.raises(empaquetar.ErrorEmpaquetado):
        empaquetar.bloqueo_desde_ruedas(["raro.zip"])


def test_comprobar_contenido_detecta_errores():
    base = {"main.py": b"", "packages/azure/ai/agentserver/responses/__init__.py": b""}
    assert empaquetar.comprobar_contenido(base) == []
    malos = {**base, "packages/x/_c.pyd": b"MZ", "packages/y/z.so": b"MZ..", "packages/w.whl": b"PK",
             "../fuera.py": b""}
    errores = " ".join(empaquetar.comprobar_contenido(malos))
    for frag in ("Windows", "no es ELF", "sin extraer", "ruta no válida"):
        assert frag in errores
    assert empaquetar.comprobar_contenido({"packages/y/z.so.1": b"\x7fELF", "main.py": b""}) == [
        "packages/ no contiene azure.ai.agentserver.responses (falta la fase instalar)"]
    assert "falta main.py" in " ".join(empaquetar.comprobar_contenido({"carpeta/main.py": b""}))


def test_zip_determinista_y_comprobado(tmp_path):
    import hashlib
    contenido = {"main.py": b"print(1)\n", "packages/azure/ai/agentserver/responses/__init__.py": b""}
    man = {"ficheros": {r: {"sha256": hashlib.sha256(b).hexdigest()} for r, b in contenido.items()}}
    contenido["MANIFIESTO-HOSTED.json"] = json.dumps(man).encode()
    a = empaquetar.escribir_zip(contenido, tmp_path / "a.zip")
    b = empaquetar.escribir_zip(dict(reversed(list(contenido.items()))), tmp_path / "b.zip")
    assert a["sha256"] == b["sha256"]
    assert empaquetar.comprobar_zip(tmp_path / "a.zip") == a["sha256"]
    with zipfile.ZipFile(tmp_path / "c.zip", "w") as z:   # un fichero alterado tras el manifiesto
        for r, d in contenido.items():
            z.writestr(r, d if r != "main.py" else b"alterado")
    with pytest.raises(empaquetar.ErrorEmpaquetado):
        empaquetar.comprobar_zip(tmp_path / "c.zip")


def test_contenido_zip_real_excluye_cache(tmp_path):
    paquetes = tmp_path / "packages"
    (paquetes / "azure" / "__pycache__").mkdir(parents=True)
    (paquetes / "azure" / "__pycache__" / "x.pyc").write_bytes(b"")
    (paquetes / "azure" / "m.py").write_bytes(b"")
    (paquetes / "bin").mkdir()
    (paquetes / "bin" / "lanzador").write_bytes(b"")
    c = empaquetar.contenido_zip(empaquetar.AQUI, paquetes)
    assert "packages/azure/m.py" in c and "main.py" in c and "ofa_prueba_hosted/ordenes.py" in c
    assert not any("__pycache__" in r or r.startswith("packages/bin/") for r in c)
    assert "empaquetar.py" not in c and "__init__.py" not in c


# ------------------------------------------------------------------------------------------- P5
def test_configuracion_opencode(cfg):
    c = p5.configuracion(cfg)
    prov = c["provider"]["ofa-hosted"]
    assert prov["npm"] == "@ai-sdk/openai"
    assert prov["options"]["baseURL"] == ("https://mi-recurso-foundry.services.ai.azure.com/api/projects/"
                                          "mi-proyecto-foundry/agents/ofa-prueba-hosted/endpoint/protocols/openai")
    assert c["model"] == "ofa-hosted/ofa-prueba-hosted"


def test_plugin_tenant_fijo_y_sin_token(cfg):
    js = p5.plugin(cfg)
    assert '"chat.headers"' in js and cfg["tenant_id"] in js and '"--tenant", TENANT' in js
    assert "tid(r.accessToken) !== TENANT" in js and "console.log" not in js and "writeFile" not in js


def test_plugin_api_version_solo_al_prefijo_del_hosted(cfg):
    js = p5.plugin(cfg)
    assert f'const PREFIJO_HOSTED = "{p5.base_url(cfg)}/"' in js
    assert "url.startsWith(PREFIJO_HOSTED)" in js and 'u.searchParams.set("api-version", "v1")' in js
    assert '!u.searchParams.has("api-version")' in js   # no pisa un api-version que ya venga


def test_preparar_directorio_y_entorno_aislado(cfg, tmp_path):
    rutas = p5.preparar_directorio(tmp_path / "oc", cfg)
    assert rutas["config"].is_file() and rutas["plugin"].as_posix().endswith(".opencode/plugin/foundry-token.js")
    assert b"\r" not in rutas["plugin"].read_bytes()
    env = p5.entorno(rutas, {"OPENCODE_CONFIG": "x", "PATH": "p"})
    assert env["XDG_CONFIG_HOME"] == str(rutas["xdg"]) and "OPENCODE_CONFIG" not in env and env["PATH"] == "p"
    assert env["XDG_DATA_HOME"] == str(rutas["datos"]) and rutas["datos"].is_dir()
    assert env["PWD"] == str(tmp_path / "oc")


def test_directorio_fijo_bajo_temp(monkeypatch, tmp_path):
    monkeypatch.setenv("TEMP", str(tmp_path))
    assert p5.directorio_fijo() == tmp_path / "ofa-p5-opencode"


def test_evaluar_bucle_por_fin_de_turno():
    salida = "\n".join(['{"eco": "ECO-OFA: p5-x"}'] * 3)
    estado, det = p5.evaluar(None, salida, "p5-x")
    assert estado == "FALLA" and "3 veces" in det and "usage" in det


def test_evaluar_opencode():
    assert p5.evaluar(0, "... ECO-OFA: p5-ab12 ...", "p5-ab12")[0] == "PASA"
    assert p5.evaluar(0, "otra cosa", "p5-ab12")[0] == "FALLA"
    estado, det = p5.evaluar(1, "Missing required query parameter 'api-version'", "p5-ab12")
    assert estado == "FALLA" and "@ai-sdk/azure" in det
    assert "no terminó" in p5.evaluar(None, "", "p5-x")[1]


# ------------------------------------------------------------------------------------- limpieza
def test_limpieza_solo_ofa_prueba(cfg):
    nombres = ["ofa-prueba-hosted", "ofa-prueba-herramientas", "ofa-coordinador", "Agente-De-Otro-Proyecto",
               "otro-proyecto-prueba-hosted", "ofa-prueba-MAL", None, "ofa-prueba-hosted"]
    borrables, ignorados = limpiar_pruebas.seleccionar(nombres, cfg)
    assert borrables == ["ofa-prueba-herramientas", "ofa-prueba-hosted"]
    assert {n for n, _ in ignorados} >= {"ofa-coordinador", "Agente-De-Otro-Proyecto", "otro-proyecto-prueba-hosted",
                                         "ofa-prueba-MAL"}


class ClienteLimpiezaFalso:
    def __init__(self, cfg, nombres):
        self.cfg, self.nombres, self.borrados = cfg, nombres, []

    def listar_agentes(self):
        return [{"name": n} for n in self.nombres]

    def borrar_agente(self, nombre, forzar=False):
        self.borrados.append((nombre, forzar))


def test_limpieza_exige_confirmar(cfg, capsys):
    cli = ClienteLimpiezaFalso(cfg, ["ofa-prueba-hosted", "ofa-coordinador", "Agente-De-Otro-Proyecto"])
    assert limpiar_pruebas.main([], cliente=cli) == 0 and cli.borrados == []
    assert limpiar_pruebas.main(["--confirmar", "--forzar"], cliente=cli) == 0
    assert cli.borrados == [("ofa-prueba-hosted", True)]


def test_resolver_opencode_prefiere_el_exe(tmp_path):
    cmd = tmp_path / "opencode.CMD"
    cmd.write_text("@echo off\n")
    assert p5.resolver_opencode(str(cmd)) == str(cmd)
    exe = tmp_path / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    assert p5.resolver_opencode(str(cmd)) == str(exe)
    assert p5.resolver_opencode(None) is None


class _ClienteHostedFalso:
    def __init__(self, estado):
        self.estado = estado
        self.llamadas = []

    def datos(self, metodo, ruta, **_):
        from pruebas.paso0a import comun
        return comun.RespuestaHTTP(self.estado, "sin respuesta sintética")


@pytest.mark.parametrize("estado", [-1, 408, 429, 500, 503])
def test_p5_comprobacion_transitoria_no_es_falla(cfg, tmp_path, estado):
    from pruebas.paso0a import comun
    ctx = comun.Contexto(cfg=cfg, cliente=_ClienteHostedFalso(estado), dir_resultados=tmp_path,
                         dir_progreso=tmp_path, simulado=True)
    r = p5.ejecutar(ctx)
    assert isinstance(r, comun.EnCurso) and "transitoria" in r.mensaje


def test_p5_comprobacion_403_si_es_falla(cfg, tmp_path):
    from pruebas.paso0a import comun
    ctx = comun.Contexto(cfg=cfg, cliente=_ClienteHostedFalso(403), dir_resultados=tmp_path,
                         dir_progreso=tmp_path, simulado=True)
    r = p5.ejecutar(ctx)
    assert isinstance(r, dict) and r["estado"] == "FALLA"


class ClienteLimpiezaQueCaduca(ClienteLimpiezaFalso):
    def borrar_agente(self, nombre, forzar=False):
        from lib import azure_auth
        raise azure_auth.ErrorAutenticacion("MFA pendiente")


def test_limpieza_codigos_de_salida_de_autenticacion_y_uso(cfg, monkeypatch, capsys):
    cli = ClienteLimpiezaQueCaduca(cfg, ["ofa-prueba-hosted"])
    assert limpiar_pruebas.main(["--confirmar"], cliente=cli) == 5

    def config_rota(*a, **k):
        from lib.config import ErrorConfig
        raise ErrorConfig("configuración rota")
    monkeypatch.setattr(limpiar_pruebas, "ClienteFoundry", config_rota)
    assert limpiar_pruebas.main([]) == 2


def test_items_io_recorta_y_omite_el_razonamiento():
    r = _resp({"type": "reasoning", "summary": "x"},
              {"type": "mcp_call", "name": "microsoft_docs_search", "output": "a" * 5000, "arguments": {"q": 1}})
    items = p3.items_io(r, maximo=100)
    assert [i["type"] for i in items] == ["mcp_call"]
    assert len(items[0]["output"]) < 200 and "recortado" in items[0]["output"]
    assert items[0]["arguments"] == '{"q": 1}'


def test_p5_pasa_guarda_la_salida_y_sin_ruta_personal():
    estado, det = p5.evaluar(0, 'linea previa\n{"orden": "ECO", "eco": "ECO-OFA: p5-ab12"}', "p5-ab12")
    assert estado == "PASA" and '"eco": "ECO-OFA: p5-ab12"' in det and "1 vez" in det
    import pathlib
    casa = str(pathlib.Path.home())
    assert casa not in p5.sin_ruta_personal(f"dir {casa}/x y {casa.replace(chr(92), '/')}/y")


def test_resumir_llamadas_cuenta_repeticiones():
    from pruebas.paso0a import comun as c
    assert c.resumir_llamadas(["GET a", "GET b", "GET a"]) == "GET a (×2); GET b"


def test_p5_quita_colores_ansi():
    esc = chr(27)
    assert p5.sin_ruta_personal(f"{esc}[0m> build{esc}[1;32m ok") == "> build ok"


def test_limpieza_tolera_agentes_sin_nombre(cfg, capsys):
    cli = ClienteLimpiezaFalso(cfg, [None, "ofa-prueba-hosted"])
    assert limpiar_pruebas.main([], cliente=cli) == 0 and cli.borrados == []
