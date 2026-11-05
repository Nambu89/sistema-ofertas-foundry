"""I1.9 · papel R · INT18-1 y VPROT-7.

INT18-1: obtener_baseline.py hace todos los GET por una sola sesión HTTP y reintenta (anotando cada intento) ante fallo
de red, 429 o 5xx; si la red falla en el último intento, para con la ruta (nunca una captura a medias que parezca entera).
VPROT-7: comparar.py compara también las conexiones (nombre, categoría, destino y autenticación) y la lista de agentes.
Sin red ni az: sesión falsa y capturas sintéticas en tmp_path."""
import importlib.util
import json
import pathlib
import sys

import pytest
import requests

from tests import comparar_comun

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "_baseline"))
spec = importlib.util.spec_from_file_location("obtener_baseline_i19", RAIZ / "_baseline" / "obtener_baseline.py")
ob = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ob)  # importar ya no pide token ni lee argumentos (antes lo hacía al importar)
spec_c = importlib.util.spec_from_file_location("comparar_i19", RAIZ / "pruebas" / "I0" / "VERIF" / "scripts" / "comparar.py")
cmp_mod = importlib.util.module_from_spec(spec_c)
spec_c.loader.exec_module(cmp_mod)


class _Resp:
    def __init__(self, estado, cuerpo=b'{"ok": 1}', cabeceras=None):
        self.status_code, self.content, self.headers = estado, cuerpo, cabeceras or {}
        self.text = cuerpo.decode("utf-8", "replace")


class _Sesion:
    """Devuelve (o lanza) por orden lo que se le da y cuenta las llamadas."""
    def __init__(self, *salidas):
        self.salidas, self.llamadas = list(salidas), []

    def get(self, url, headers, timeout):
        self.llamadas.append(url)
        x = self.salidas.pop(0)
        if isinstance(x, Exception):
            raise x
        return x


def _get(ses, ruta="/agents", crudo=False):
    esperas = []
    return ob.get(ruta, crudo, ses=ses, tok="t", dormir=esperas.append), esperas


def test_importar_no_pide_token_ni_fija_destino():
    assert ob._TOK is None and ob.OUT is None


def test_una_sola_sesion_para_toda_la_captura():
    assert ob.sesion() is ob.sesion() and isinstance(ob.sesion(), requests.Session)


@pytest.mark.parametrize("fallo", [requests.ConnectionError("WinError 10060"), requests.ConnectionError("WinError 10061"),
                                   requests.Timeout("lectura")])
def test_fallo_de_red_se_reintenta_y_se_anota(fallo, capsys):
    ses = _Sesion(fallo, fallo, _Resp(200))
    (estado, cuerpo, _), esperas = _get(ses)
    assert (estado, cuerpo) == (200, {"ok": 1}) and len(ses.llamadas) == 3 and esperas == [2.0, 4.0]
    err = capsys.readouterr().err
    assert err.count("[reintento ") == 2 and "GET /agents" in err and "Bearer" not in err


def test_red_caida_en_el_ultimo_intento_para_con_la_ruta():
    ses = _Sesion(*[requests.ConnectionError("WinError 10060")] * 3)
    with pytest.raises(SystemExit) as e:
        _get(ses, "/connections")
    assert "FALLO de red en GET /connections tras 3 intentos" in str(e.value) and len(ses.llamadas) == 3


@pytest.mark.parametrize("estado", [429, 500, 502, 503, 504])
def test_429_y_5xx_se_reintentan(estado):
    (r, _, _), esperas = _get(_Sesion(_Resp(estado), _Resp(200)))
    assert r == 200 and len(esperas) == 1


def test_retry_after_manda_y_tiene_tope():
    _, esperas = _get(_Sesion(_Resp(429, cabeceras={"Retry-After": "500"}), _Resp(200)))
    assert esperas == [60.0]


def test_un_5xx_persistente_se_devuelve_como_error_http():
    (estado, cuerpo, _), esperas = _get(_Sesion(_Resp(503, b"caido"), _Resp(503, b"caido"), _Resp(503, b"caido")))
    assert estado == 503 and cuerpo == {"error_http": 503, "cuerpo": "caido"} and len(esperas) == 2


def test_un_404_no_se_reintenta():
    ses = _Sesion(_Resp(404, b"no"))
    (estado, cuerpo, _), esperas = _get(ses)
    assert estado == 404 and cuerpo["error_http"] == 404 and esperas == [] and len(ses.llamadas) == 1


def test_crudo_devuelve_bytes():
    (estado, cuerpo, _), _ = _get(_Sesion(_Resp(200, b"PK\x03")), "/x", crudo=True)
    assert estado == 200 and cuerpo == b"PK\x03"


# ───────────────────────────── VPROT-7: conexiones y lista de agentes ─────────────────────────────

def _capturas(tmp_path, conexiones_ahora=None, agentes_ahora=None, base_conexiones=None):
    base, ahora = tmp_path / "base", tmp_path / "ahora"
    for d in (base, ahora):
        d.mkdir()
        for n in cmp_mod.PROTEGIDOS:
            (d / n).write_text(json.dumps({"respuesta": {"n": n}}), encoding="utf-8")
        (d / cmp_mod.ZIP_V3).write_bytes(b"PK-v3")
    comparar_comun.escribir_listas(cmp_mod, base, ahora, conexiones_ahora, agentes_ahora)
    for n, cuerpo in (base_conexiones or {}).items():
        (base / n).write_text(json.dumps({"respuesta": cuerpo}), encoding="utf-8")
    return [str(ahora), "--base", str(base)]


def _plano(*filas):
    return {"conexiones.json": {"data": list(filas)}}


AUT = comparar_comun.conexiones_autorizadas(cmp_mod, arm=False)["data"]


def test_control_conexiones_y_agentes_autorizados_dan_igual(tmp_path, capsys):
    ag = {"data": [{"name": "agente-ajeno-ejemplo"}, {"name": "preventa-coordinador"}, {"name": "preventa-prueba-x"}]}
    assert cmp_mod.principal(_capturas(tmp_path, agentes_ahora=ag)) == 0
    out = capsys.readouterr().out
    assert "conexiones.json: IGUAL" in out and "agentes_lista.json: IGUAL" in out and "agente propio" in out


@pytest.mark.parametrize("filas, texto", [
    (AUT[:2], "falta"),                                                                        # la de trazas, quitada
    (AUT + [{"name": "nueva", "type": "CustomKeys", "target": "https://x"}], "no autorizada"),  # una nueva
    (AUT[:2] + [{**AUT[2], "target": AUT[2]["target"] + "-otra"}], "->"),                      # trazas reapuntada
    (AUT[:2] + [{**AUT[2], "name": "appi-otra"}], "no autorizada"),                            # AppInsights renombrada
    (AUT + [AUT[0]], "repetida"),                                                              # repetida
])
def test_conexiones_que_cuentan(tmp_path, capsys, filas, texto):
    assert cmp_mod.principal(_capturas(tmp_path, conexiones_ahora=_plano(*filas))) == 1
    out = capsys.readouterr().out
    assert "conexiones.json: IGUAL" not in out and texto in out


def test_en_arm_cuenta_la_autenticacion(tmp_path, capsys):
    arm = comparar_comun.conexiones_autorizadas(cmp_mod, arm=True)
    arm["value"][0]["properties"]["authType"] = "ApiKey"
    assert cmp_mod.principal(_capturas(tmp_path, conexiones_ahora={"arm_conexiones_cuenta.json": arm})) == 1
    assert "arm_conexiones_cuenta.json: 1 diferencias" in capsys.readouterr().out


def test_una_conexion_de_la_linea_base_que_desaparece_cuenta_y_appinsights_no(tmp_path, capsys):
    base = {"data": [{"name": "conexion-ajena", "type": "CustomKeys", "target": "https://ajeno"},
                     {"name": "vieja-appi", "type": "AppInsights", "target": "/x"}]}
    assert cmp_mod.principal(_capturas(tmp_path, base_conexiones={"conexiones.json": base})) == 1
    out = capsys.readouterr().out
    assert "/conexion-ajena: falta" in out and "vieja-appi" not in out


@pytest.mark.parametrize("agentes, texto", [
    ({"data": [{"name": "agente-ajeno-ejemplo"}, {"name": "intruso"}]}, "agente nuevo no autorizado"),
    ({"data": [{"name": "preventa-coordinador"}]}, "falta en la lista"),
    ({"data": [{"name": "agente-ajeno-ejemplo"}, {"name": "agente-ajeno-ejemplo"}]}, "repetido"),
    ({"data": [{"name": "agente-ajeno-ejemplo"}, {"name": "preventa-otro"}]}, "agente nuevo no autorizado"),
    ({"n": 1}, "no se puede comparar"),
])
def test_lista_de_agentes_que_cuenta(tmp_path, capsys, agentes, texto):
    assert cmp_mod.principal(_capturas(tmp_path, agentes_ahora=agentes)) == 1
    assert texto in capsys.readouterr().out


def test_lista_mal_formada_cuenta(tmp_path, capsys):
    assert cmp_mod.principal(_capturas(tmp_path, conexiones_ahora={"conexiones.json": {"n": 1}})) == 1
    assert "no se puede comparar" in capsys.readouterr().out


def test_la_captura_real_del_verificador_da_igual(capsys):
    ahora = RAIZ / "pruebas" / "I18" / "VERIF-PROTOCOLO" / "ahora"
    if not (ahora / "conexiones.json").is_file():
        pytest.skip("sin la captura de I1.8")
    assert cmp_mod.principal([str(ahora)]) == 0
