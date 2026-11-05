"""Pruebas sin red de observabilidad/: saneado de credenciales, troceado de consultas.kql, precios de la
consulta 2 sincronizados con _baseline/precios.json y consulta por REST."""
import json
import re

import pytest

from observabilidad import conectar_appinsights as ca
from observabilidad import probar_consultas as pc


def test_sanear_omite_credenciales_y_literales():
    secreto = "InstrumentationKey=abc;IngestionEndpoint=https://x"
    datos = {"properties": {"credentials": {"key": secreto}, "target": "t"},
             "error": f"fallo con {secreto} dentro", "lista": [{"ConnectionString": secreto}]}
    s = ca.sanear(datos, [secreto])
    assert s["properties"]["credentials"] == "<OMITIDO>"
    assert s["properties"]["target"] == "t"
    assert secreto not in s["error"] and "<OMITIDO>" in s["error"]
    assert s["lista"][0]["ConnectionString"] == "<OMITIDO>"


def test_sanear_ignora_secretos_vacios():
    assert ca.sanear("texto", ["", None]) == "texto"


def test_consultas_kql_se_trocean_sin_comentarios():
    qs = pc.consultas()
    assert [t.split(".")[0] for t, _ in qs] == ["0", "1", "2", "3"]
    for _, q in qs:
        assert q and not q.endswith(";")
        assert not any(l.strip().startswith("//") for l in q.splitlines())
    assert "execute_tool" in qs[1][1] and "gen_ai.usage.input_tokens" in qs[2][1]
    assert '"tool_server_error"' in qs[3][1] and '"remote_a2a_"' in qs[3][1]


def _precios_kql() -> dict:
    """Filas del datatable de la consulta 2: {(modelo, tramo): (entrada, caché, escritura, salida)}."""
    q = dict(pc.consultas())[next(t for t, _ in pc.consultas() if t.startswith("2."))]
    cuerpo = q[q.index("datatable("):q.index("];")]
    filas = re.findall(r'"([^"]+)",\s*"(corto|largo)",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', cuerpo)
    return {(m, t): tuple(float(x) for x in v) for m, t, *v in filas}


def test_precios_de_la_consulta_2_coinciden_con_baseline():
    """Prueba de sincronía (LES-G-090.7): si cambia _baseline/precios.json, la KQL tiene que cambiar."""
    tabla = json.loads((pc.RAIZ / "_baseline" / "precios.json").read_text(encoding="utf-8"))
    tabla = tabla["resumen_dz_estandar_eur_por_millon"]
    esperado = {(m, t): tuple(tabla[m][t][c]["eur"] for c in ("entrada", "cache_entrada",
                                                             "escritura_cache", "salida"))
                for m in ("gpt-6-luna", "gpt-5.6-luna") for t in ("corto", "largo")}
    assert _precios_kql() == esperado
    assert all(v > 0 for fila in esperado.values() for v in fila)


def test_umbral_y_formula_de_la_consulta_2_son_los_de_coste_eur():
    q = next(c for t, c in pc.consultas() if t.startswith("2."))
    fuente = (pc.RAIZ / "pruebas" / "I0" / "ejecutar_pruebas.py").read_text(encoding="utf-8")
    umbral = int(re.search(r"UMBRAL_LARGO = ([\d_]+)", fuente).group(1).replace("_", ""))
    assert f"let umbral_largo = {umbral};" in q and "tokens_entrada > umbral_largo" in q
    assert "tokens_entrada - cache_leida - cache_escrita" in q and 'split(modelo, "-20")[0]' in q
    assert "real(null)" in q  # sin precio no se cuenta como 0 EUR


@pytest.mark.parametrize("offset,iso", [("24h", "PT24H"), ("30m", "PT30M"), ("2d", "P2D"), (" 6H ", "PT6H")])
def test_duracion_iso(offset, iso):
    assert pc.duracion_iso(offset) == iso


@pytest.mark.parametrize("malo", ["", "24", "1w", "-1h", "1h;drop"])
def test_duracion_iso_rechaza_lo_desconocido(malo):
    with pytest.raises(SystemExit):
        pc.duracion_iso(malo)


@pytest.mark.parametrize("fallo", ["ConnectionError", "Timeout"])
def test_consultar_reintenta_una_vez_y_lo_anota(monkeypatch, fallo):
    import requests
    import lib.azure_auth
    import lib.config
    llamadas = []

    class Resp:
        status_code, content = 200, '{"tables": [{"rows": [["ñ"]]}]}'.encode("utf-8")

    def post(*_a, **_k):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise getattr(requests, fallo)("dns")
        return Resp()

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(lib.azure_auth, "obtener_token", lambda *_a, **_k: "t")
    monkeypatch.setattr(lib.config, "cargar", lambda: {"tenant_id": "x", "grupo_recursos": "g",
                        "suscripcion_id": "00000000-0000-0000-0000-000000000000"})
    monkeypatch.setattr(pc.time, "sleep", lambda _s: None)
    estado, cuerpo, notas = pc.consultar("q", "PT1H")
    assert estado == 200 and "ñ" in cuerpo and notas == [f"intento 1/2: {fallo} (red, DNS o tiempo agotado)"]


def test_interpretar_salida_ilegible_es_fallo_sin_excepcion():
    assert pc.interpretar(0, "{no es json") == (None, "{no es json")
    assert pc.interpretar(0, '{"tables": [{"rows": [[1], [2]]}]}')[0] == 2
    assert pc.interpretar(1, '{"tables": []}') == (None, None)
    assert pc.interpretar(0, "[1, 2]")[0] is None


def test_consultar_va_por_arm_con_el_token_de_arm(monkeypatch):
    """I1.2 (F4): la consulta ya no depende de la audiencia api.applicationinsights.io (MFA aparte)."""
    import requests
    import lib.azure_auth
    import lib.config
    vistos = {}

    class Resp:
        status_code, content = 200, b'{"tables": []}'

    def post(url, **_k):
        vistos["url"] = url
        return Resp()

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(lib.azure_auth, "obtener_token", lambda aud, _t: vistos.setdefault("aud", aud) and "t")
    monkeypatch.setattr(lib.config, "cargar", lambda: {"tenant_id": "x", "grupo_recursos": "rg-preventa-ejemplo",
                        "suscripcion_id": "00000000-0000-0000-0000-000000000000"})
    assert pc.consultar("q", "PT1H")[0] == 200
    assert vistos["aud"] == "https://management.azure.com"
    assert vistos["url"].startswith("https://management.azure.com/subscriptions/00000000")
    assert vistos["url"].endswith("/components/appi-preventa-ejemplo/query?api-version=2018-04-20")


@pytest.mark.parametrize("cuerpo", ['{"tables": [{"rows": [[1]]}], "error": {"code": "PartialError"}}',
                                    '{"otra": 1}'])
def test_interpretar_parcial_o_sin_tablas_no_es_exito(cuerpo):
    """Revisión F4: un 200 con `error` (resultado parcial) o sin `tables` no cuenta como consulta buena."""
    assert pc.interpretar(0, cuerpo)[0] is None


def test_consultar_200_que_no_es_utf8_no_se_da_por_bueno(monkeypatch):
    import requests
    import lib.azure_auth
    import lib.config

    class Resp:
        status_code, content = 200, '{"tables": [{"rows": [["revisión"]]}]}'.encode("cp1252")

    monkeypatch.setattr(requests, "post", lambda *_a, **_k: Resp())
    monkeypatch.setattr(lib.azure_auth, "obtener_token", lambda *_a, **_k: "t")
    monkeypatch.setattr(lib.config, "cargar", lambda: {"tenant_id": "x", "grupo_recursos": "g",
                        "suscripcion_id": "00000000-0000-0000-0000-000000000000"})
    estado, cuerpo, notas = pc.consultar("q", "PT1H")
    assert estado == 200 and cuerpo == "" and "no es UTF-8" in notas[-1]
    assert pc.interpretar(0, cuerpo)[0] is None
