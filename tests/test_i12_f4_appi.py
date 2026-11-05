"""lib/appi.py (I1.2, F4): consulta KQL a Application Insights por ARM, sin red (sesión HTTP falsa)."""
import json

import pytest
import requests

from lib import appi

CFG = {"suscripcion_id": "00000000-0000-0000-0000-000000000000", "grupo_recursos": "rg-preventa-ejemplo",
       "tenant_id": "00000000-0000-0000-0000-000000000000"}
TABLAS = {"tables": [{"name": "PrimaryResult", "columns": [{"name": "agente", "type": "string"},
                                                           {"name": "n", "type": "long"}],
                      "rows": [["preventa-coordinador · revisión", 3], ["experto Azure ñ", 1]]}]}


class Resp:
    def __init__(self, estado, contenido=b"", cabeceras=None):
        self.status_code, self.content, self.headers = estado, contenido, cabeceras or {}


class Sesion:
    """Devuelve las respuestas en orden; una excepción en la lista se lanza. Guarda cada POST."""

    def __init__(self, *respuestas):
        self.respuestas, self.posts = list(respuestas), []

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _consultar(sesion, **kw):
    esperas = []
    datos = appi.consultar("requests | take 2", "PT1H", cfg=CFG, sesion=sesion, token="tok-falso",
                           dormir=esperas.append, **kw)
    return datos, esperas


def test_post_a_arm_con_la_api_version_de_la_especificacion_y_utf8():
    s = Sesion(Resp(200, json.dumps(TABLAS, ensure_ascii=False).encode("utf-8")))
    datos, _ = _consultar(s)
    p = s.posts[0]
    assert p["url"] == ("https://management.azure.com/subscriptions/00000000-0000-0000-0000-000000000000"
                        "/resourcegroups/rg-preventa-ejemplo/providers/Microsoft.Insights/components/"
                        "appi-preventa-ejemplo/query?api-version=2018-04-20")
    assert "api.applicationinsights.io" not in p["url"]
    assert json.loads(p["data"].decode("utf-8")) == {"query": "requests | take 2", "timespan": "PT1H"}
    assert p["headers"]["Authorization"] == "Bearer tok-falso"
    assert appi.filas(datos)[0] == {"agente": "preventa-coordinador · revisión", "n": 3}
    assert appi.filas(datos)[1]["agente"] == "experto Azure ñ"  # tildes intactas, sin U+FFFD


def test_usa_el_token_de_arm_y_el_tenant_fijo(monkeypatch):
    from lib import azure_auth
    vistos = []
    monkeypatch.setattr(azure_auth, "obtener_token", lambda aud, ten: vistos.append((aud, ten)) or "t")
    appi.consultar("x", cfg=CFG, sesion=Sesion(Resp(200, json.dumps(TABLAS).encode())), dormir=lambda s: None)
    assert vistos == [("https://management.azure.com", CFG["tenant_id"])]


def test_bytes_utf8_aunque_la_cabecera_diga_otra_cosa():
    cuerpo = json.dumps(TABLAS, ensure_ascii=False).encode("utf-8")
    datos, _ = _consultar(Sesion(Resp(200, cuerpo, {"Content-Type": "application/json; charset=iso-8859-1"})))
    assert appi.filas(datos)[0]["agente"].endswith("revisión")


def test_respuesta_cp1252_falla_en_alto():
    malo = json.dumps(TABLAS, ensure_ascii=False).encode("cp1252", errors="replace")
    with pytest.raises(appi.ErrorAppi, match="no es UTF-8"):
        _consultar(Sesion(Resp(200, malo)))


@pytest.mark.parametrize("contenido,patron", [
    (b"{roto", "no es JSON"), (b'{"otra": 1}', "tables"),
    (json.dumps({"tables": [], "error": {"code": "PartialError"}}).encode(), "parcial"),
])
def test_200_ilegible_o_parcial_no_es_exito(contenido, patron):
    with pytest.raises(appi.ErrorAppi, match=patron):
        _consultar(Sesion(Resp(200, contenido)))


@pytest.mark.parametrize("estado", [401, 403])
def test_sin_permiso_da_el_remedio(estado):
    with pytest.raises(appi.ErrorAppi, match="az login --tenant 00000000") as e:
        _consultar(Sesion(Resp(estado, b'{"error":{"code":"AuthorizationFailed"}}')))
    assert e.value.estado == estado


def test_un_reintento_con_retry_after_acotado():
    s = Sesion(Resp(429, b"{}", {"Retry-After": "600"}), Resp(200, json.dumps(TABLAS).encode()))
    _, esperas = _consultar(s)
    assert esperas == [30.0] and len(s.posts) == 2


def test_dos_429_seguidos_fallan_con_el_estado():
    s = Sesion(Resp(429, b'{"error":"x"}'), Resp(429, b'{"error":"x"}'))
    with pytest.raises(appi.ErrorAppi) as e:
        _consultar(s)
    assert e.value.estado == 429


def test_red_caida_dos_veces_falla_en_alto():
    s = Sesion(requests.ConnectionError("dns"), requests.Timeout("t"))
    with pytest.raises(appi.ErrorAppi, match="2 intentos"):
        _consultar(s)


def test_error_http_enmascara_lo_que_parece_un_secreto():
    # JWT sintético (firma falsa), compuesto en ejecución para que el literal no dispare el barrido de secretos
    jwt = ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "c2lnbmF0dXJhLWZhbHNhLWRlLXBydWViYQ"])
    with pytest.raises(appi.ErrorAppi) as e:
        _consultar(Sesion(Resp(500, f'{{"error": "Bearer {jwt}"}}'.encode())))
    assert jwt not in str(e.value)


@pytest.mark.parametrize("sub,rg,comp", [
    ("no-guid", "rg", "app"), (CFG["suscripcion_id"], "rg/../otro", "app"),
    (CFG["suscripcion_id"], "rg", "app?api-version=1"), (CFG["suscripcion_id"], "rg", ""),
])
def test_segmentos_de_ruta_validados(sub, rg, comp):
    with pytest.raises(appi.ErrorAppi):
        appi.url_consulta(sub, rg, comp)


@pytest.mark.parametrize("ts,ok", [("PT1H", True), ("P1D", True), ("PT30M", True), ("P2DT3H", True),
                                   ("2026-10-08T10:00:00Z/2026-10-08T11:00:00Z", True),
                                   ("1h", False), ("P", False), ("PT", False), ("P1DT", False)])
def test_timespan_iso(ts, ok):
    if ok:
        assert appi.cuerpo("x", ts)["timespan"] == ts
    else:
        with pytest.raises(appi.ErrorAppi):
            appi.cuerpo("x", ts)


def test_filas_con_anchura_distinta_falla():
    with pytest.raises(appi.ErrorAppi, match="fila 0"):
        appi.filas({"tables": [{"columns": [{"name": "a"}], "rows": [[1, 2]]}]})


def test_cli_sin_red_guarda_enmascarado(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(appi, "consultar", lambda kql, ts, componente=None: TABLAS)
    destino = tmp_path / "appi.json"
    assert appi.main(["requests | take 2", "--timespan", "PT1H", "--salida", str(destino)]) == 0
    guardado = json.loads(destino.read_text(encoding="utf-8"))
    assert guardado["api_version"] == "2018-04-20" and guardado["respuesta"] == TABLAS
    assert "2 filas" in capsys.readouterr().out
