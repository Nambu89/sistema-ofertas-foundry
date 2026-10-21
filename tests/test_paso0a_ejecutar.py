"""Orquestador del arnés en modo simulado: escenarios feliz y adverso de punta a punta (sin red)."""
from __future__ import annotations

import pytest

from pruebas.paso0a import comun, ejecutar, p4_hosted, simulacion


@pytest.fixture
def entorno_sim(tmp_path):
    zip_sim = simulacion.construir_zip_simulado(tmp_path / "ofa-prueba-hosted.zip")

    def crear(escenario):
        return simulacion.contexto(escenario, tmp_path / escenario, tmp_path / f"prog-{escenario}",
                                   tmp_path / f"p5-{escenario}", zip_sim)
    return crear


def _todas(ctx):
    salida = {}
    for id_, prueba in ejecutar.PRUEBAS.items():
        ctx.cliente.llamadas.clear()
        salida[id_] = ejecutar.correr(prueba, ctx)
    return salida


def test_escenario_feliz_todo_pasa(entorno_sim):
    ctx, sim = entorno_sim("feliz")
    res = _todas(ctx)
    assert {k: v["estado"] for k, v in res.items()} == {k: "PASA" for k in ejecutar.PRUEBAS}
    for id_ in ("P4a", "P4b", "P4c", "P4d"):
        assert comun.leer_json(ctx.dir_resultados / f"{id_}.json")["estado"] == "PASA"
    # El despliegue fue multipart con la cabecera de integridad y el nombre del agente de prueba.
    crear = [p for p in sim.peticiones if p.files and p.url.endswith("/agents")]
    assert crear and crear[0].cabeceras["x-ms-agent-name"] == "ofa-prueba-hosted"
    assert len(crear[0].cabeceras["x-ms-code-zip-sha256"]) == 64
    # Ninguna petición sale sin tiempo máximo ni hacia un host ajeno.
    hosts = {p.url.split("/")[2] for p in sim.peticiones}
    assert hosts <= {"management.azure.com", "mi-recurso-foundry.services.ai.azure.com"}
    # La Responses API del proyecto va sin api-version (LES-G-014).
    assert all("api-version" not in p.params for p in sim.peticiones if "/openai/v1/" in p.url)


def test_escenario_adverso_clasifica_bien(entorno_sim):
    ctx, _ = entorno_sim("adverso")
    res = _todas(ctx)
    assert {k: v["estado"] for k, v in res.items()} == {
        "P1": "FALLA", "P2": "PENDIENTE_FERNANDO", "P3": "PENDIENTE_FERNANDO", "P4": "FALLA", "P5": "FALLA"}
    sub = {i: comun.leer_json(ctx.dir_resultados / f"{i}.json")["estado"] for i in ("P4a", "P4b", "P4c", "P4d")}
    assert sub == {"P4a": "FALLA", "P4b": "PENDIENTE_FERNANDO", "P4c": "PASA", "P4d": "PASA"}
    assert "api-version" in res["P5"]["evidencia"] and "@ai-sdk/azure" in res["P5"]["evidencia"]


def test_presupuesto_corto_deja_progreso_y_continua(entorno_sim):
    ctx, _ = entorno_sim("feliz")
    ctx.presupuesto_s = 400.0          # menos que lo que necesita el turno largo de 360 s con sus pasos
    primero = ejecutar.correr(p4_hosted, ctx)
    assert isinstance(primero, comun.EnCurso)
    assert ctx.ruta_progreso("P4").is_file()
    ctx.inicio = ctx.monotono()        # nueva invocación con presupuesto renovado
    segundo = ejecutar.correr(p4_hosted, ctx)
    assert isinstance(segundo, dict) and segundo["estado"] == "PASA"
    assert not ctx.ruta_progreso("P4").exists()


def test_sin_zip_no_hay_veredicto(entorno_sim, tmp_path):
    ctx, _ = entorno_sim("feliz")
    ctx.opciones["zip"] = str(tmp_path / "no-existe.zip")
    res = ejecutar.correr(p4_hosted, ctx)
    assert isinstance(res, comun.EnCurso) and "empaquetar.py" in res.mensaje


def test_codigo_global():
    assert ejecutar.codigo_global([0, 3, 4, 1]) == 1
    assert ejecutar.codigo_global([0, 3, 4]) == 4
    assert ejecutar.codigo_global([0, 3]) == 3
    assert ejecutar.codigo_global([0, 0]) == 0
    assert ejecutar.codigo_global([1, 5]) == 5


def test_main_simulado_y_errores_de_uso(capsys):
    assert ejecutar.main(["--simular", "--solo", "P2"]) == 0
    assert "[SIMULADO" in comun.leer_json(comun.DIR_RESULTADOS / "simulado" / "feliz" / "P2.json")["evidencia"]
    assert ejecutar.main(["--simular", "--escenario", "adverso", "--solo", "P1"]) == 1
    assert ejecutar.main(["--presupuesto", "200"]) == 2
    assert ejecutar.main(["--solo", "P9"]) == 2


@pytest.mark.parametrize("modulo", ["p1_ciclo_vida", "p2_decision"])
def test_sin_presupuesto_no_llama_y_pide_repetir(entorno_sim, modulo):
    import importlib
    ctx, sim = entorno_sim("feliz")
    ctx.presupuesto_s = 10.0
    res = ejecutar.correr(importlib.import_module(f"pruebas.paso0a.{modulo}"), ctx)
    assert isinstance(res, comun.EnCurso) and sim.peticiones == []


def test_tiempos_maximos_cortos_en_p1_y_p2(entorno_sim):
    from pruebas.paso0a import p1_ciclo_vida, p2_decision
    ctx, sim = entorno_sim("feliz")
    ejecutar.correr(p1_ciclo_vida, ctx)
    ejecutar.correr(p2_decision, ctx)
    assert sim.peticiones and all(p.timeout <= 15 for p in sim.peticiones)


def test_main_excepcion_imprevista_sale_con_2_y_no_con_1(monkeypatch, capsys):
    def rompe(*a, **k):
        raise KeyError("campo-inesperado")
    monkeypatch.setattr(ejecutar, "_preparar_simulacion", rompe)
    assert ejecutar.main(["--simular", "--solo", "P2"]) == comun.RC_USO
    assert "inesperado" in capsys.readouterr().out


def test_main_autenticacion_fuera_del_bucle_sale_con_5(monkeypatch, capsys):
    from lib import azure_auth

    def caduca(*a, **k):
        raise azure_auth.ErrorAutenticacion("token caducado")
    monkeypatch.setattr(ejecutar.comun, "contexto_real", caduca)
    assert ejecutar.main(["--solo", "P2"]) == comun.RC_AUTENTICACION


def _arm_fijo(ctx, estado):
    def arm_get(sufijo, api_version, timeout=0):
        ctx.cliente.llamadas.append(f"GET arm{sufijo}")
        return comun.RespuestaHTTP(estado, '{"error": {"code": "InternalServerError"}}')
    ctx.cliente.arm_get = arm_get


def test_p4_error_de_arm_en_la_conexion_es_falla_y_no_pendiente(entorno_sim):
    ctx, _ = entorno_sim("feliz")
    _arm_fijo(ctx, 500)
    res = ejecutar.correr(p4_hosted, ctx)
    while isinstance(res, comun.EnCurso):   # los reintentos anotados del transitorio
        ctx.inicio = ctx.monotono()
        res = ejecutar.correr(p4_hosted, ctx)
    assert res["estado"] == "FALLA" and "InternalServerError" in res["evidencia"]
    assert "GET arm/projects/" in res["comando"]


def test_p4_conexion_403_queda_pendiente_de_fernando(entorno_sim):
    ctx, _ = entorno_sim("feliz")
    _arm_fijo(ctx, 403)
    res = ejecutar.correr(p4_hosted, ctx)
    # El 403 no corta P4 (el hosted simulado resuelve el marcador igualmente): la conexión queda «desconocida».
    assert res["estado"] == "PASA" and "desconocida (ARM HTTP 403)" in res["evidencia"]
    estado, det = p4_hosted.evaluar_marcador('{"orden": "MARCADOR", "presente": false}', None, ctx.cfg)
    assert estado == "PENDIENTE_FERNANDO" and "403" in det


def test_p4_cada_subprueba_lleva_sus_llamadas_y_su_hora(entorno_sim):
    ctx, _ = entorno_sim("feliz")
    ctx.presupuesto_s = 400.0
    res = ejecutar.correr(p4_hosted, ctx)
    while isinstance(res, comun.EnCurso):   # varias invocaciones, como en real
        ctx.cliente.llamadas.clear()
        ctx.inicio = ctx.monotono()
        res = ejecutar.correr(p4_hosted, ctx)
    sub = {i: comun.leer_json(ctx.dir_resultados / f"{i}.json") for i in ("P4a", "P4c", "P4d")}
    assert "/endpoint/protocols/openai/responses?api-version=v1" in sub["P4a"]["comando"]
    assert "/caresp_" not in sub["P4a"]["comando"] and "/caresp_" in sub["P4c"]["comando"]
    assert "(×" in sub["P4c"]["comando"] and "hueco máximo entre sondeos" in sub["P4c"]["evidencia"]
    assert sub["P4a"]["fecha"] < sub["P4c"]["fecha"]
    assert "agents?api-version=v1" in res["comando"] and "/caresp_" not in res["comando"]
    assert "después de la subida" in res["evidencia"]
