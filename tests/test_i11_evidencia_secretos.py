"""R3 / H-V5 (I1): los scripts de captura tapan cadenas de conexión, claves y tokens antes de escribir.

Los secretos de prueba se construyen por partes para que este fichero no dispare el barrido.
"""
import json
import pathlib
import zipfile

import pytest

from lib import evidencia as ev

RAIZ = pathlib.Path(__file__).resolve().parents[1]
GUID = "05be" + "1234-abcd-4ef0-9a1b-" + "0123456789ab"
APPID = "9f8e" + "7d6c-5b4a-4321-8fed-" + "cba987654321"
CADENA_AI = ("Instrumentation" + "Key=" + GUID + ";IngestionEndpoint=https://swedencentral-0.in."
             "applicationinsights.azure.com/;ApplicationId=" + APPID)
JWT = "eyJ" + "h" * 20 + ".eyJ" + "p" * 20 + "." + "f" * 20
SECRETOS_TEXTO = [
    CADENA_AI,
    "DefaultEndpointsProtocol=https;Account" + "Key=" + "A" * 40 + "==;EndpointSuffix=core",
    "Authorization: Bearer " + "x" * 40,
    JWT,
    "https://cuenta.blob.core.windows.net/c/f?sv=2024&sig=" + "Q" * 30,
    '"api_key": "' + "k" * 32 + '"',
    "-----BEGIN RSA PRIVATE" + " KEY-----\nMIIabc\n-----END RSA PRIVATE" + " KEY-----",
]


def _sin_valores(texto):
    return all(v not in texto for v in (GUID, APPID, "A" * 40, "x" * 40, "h" * 20, "Q" * 30, "k" * 32,
                                       "MIIabc"))


def test_caso_r3_cadena_de_app_insights_anidada_se_tapa():
    conexion = {"name": "appi-preventa-ejemplo",
                "properties": {"metadata": {"ApplicationInsightsConnectionString": CADENA_AI,
                                            "ResourceId": "/subscriptions/x/id"}}}
    limpio = ev.limpiar(conexion)
    assert limpio["properties"]["metadata"]["ApplicationInsightsConnectionString"] == ev.OMITIDO
    assert limpio["properties"]["metadata"]["ResourceId"] == "/subscriptions/x/id"
    assert _sin_valores(json.dumps(limpio))


@pytest.mark.parametrize("texto", SECRETOS_TEXTO, ids=[f"forma{i}" for i in range(len(SECRETOS_TEXTO))])
def test_cada_forma_se_detecta_se_tapa_y_es_idempotente(texto):
    assert ev.buscar_secretos(texto), "no se detecta"
    tapado = ev.enmascarar_texto(texto)
    assert _sin_valores(tapado) and ev.buscar_secretos(tapado) == []
    assert ev.enmascarar_texto(tapado) == tapado
    assert ev.limpiar({"libre": texto})["libre"] == tapado  # también dentro de un valor sin nombre de clave


def test_buscar_secretos_no_devuelve_el_valor():
    hall = ev.buscar_secretos("\n\n" + CADENA_AI)
    assert {t for t, _ in hall} == {"instrumentation_key", "application_id"} and {n for _, n in hall} == {3}
    assert _sin_valores(repr(hall))


@pytest.mark.parametrize("texto", [
    "InstrumentationKey=abc;IngestionEndpoint=https://x",       # ejemplo corto de una prueba
    "InstrumentationKey=<guid>", "InstrumentationKey=<OMITIDO-VERIF>;IngestionEndpoint=https://x",
    r'r"|InstrumentationKey=[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}"',  # el código que busca secretos
    r'"account_key": re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}")',
    "InstrumentationKey=" + "0" * 8 + "-0000-0000-0000-" + "0" * 12,  # ejemplo de Learn
    "Bearer corto", "usage.input_tokens", '"max_output_tokens": 4000'],
    ids=lambda t: f"caso{len(t)}")  # ningún texto con forma de secreto en los ids (.pytest_cache)
def test_lo_que_no_es_secreto_no_salta(texto):
    assert ev.buscar_secretos(texto) == [] and ev.enmascarar_texto(texto) == texto


def test_limpiar_conserva_lo_que_tapaba_el_filtro_antiguo_y_no_toca_nulos():
    o = {"Token": "https://recurso-ejemplo.openai.azure.com/", "credentials": None,
         "key": 7, "qnaAzureSearchEndpointKey": None, "privateEndpointConnections": [],
         "primaryKey": "valor", "project_connection_id": "c1", "Token Service API": "https://x"}
    r = ev.limpiar(o)
    assert r["Token"] == r["credentials"] == r["key"] == r["primaryKey"] == ev.OMITIDO
    assert r["qnaAzureSearchEndpointKey"] is None and r["privateEndpointConnections"] == []
    assert r["project_connection_id"] == "c1" and r["Token Service API"] == "https://x"


def test_limpiar_deja_igual_la_linea_base_salvo_lo_que_ya_estaba_tapado():
    datos = RAIZ / "_baseline" / "datos"
    ficheros = sorted(datos.glob("*.json"))
    if not ficheros:
        pytest.skip("sin línea base local")
    for p in ficheros:
        o = json.loads(p.read_text(encoding="utf-8"))
        assert ev.limpiar(o) == o, p.name  # una captura nueva no da falsas diferencias en comparar.py


def test_guardar_enmascarado_escribe_sin_secretos(tmp_path):
    p = ev.guardar_enmascarado(tmp_path / "c.json", {"stderr": "fallo " + CADENA_AI,
                                                     "respuesta": [{"connectionString": CADENA_AI}]})
    t = p.read_text(encoding="utf-8")
    assert _sin_valores(t) and ev.buscar_secretos(t) == [] and json.loads(t)["respuesta"][0] == {
        "connectionString": ev.OMITIDO}


def test_barrer_detecta_sin_mostrar_tapa_y_conserva_el_resto_de_bytes(tmp_path):
    f = tmp_path / "sub" / "captura.json"
    f.parent.mkdir()
    original = ("línea 1\r\n" + CADENA_AI + "\r\n").encode("utf-8") + b"\xff fin\r\n"  # CRLF y un byte no UTF-8
    f.write_bytes(original)
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "x.txt").write_text(CADENA_AI, encoding="utf-8")  # excluido
    salida = []
    assert ev.barrer([tmp_path], out=salida.append) == 1
    texto = "\n".join(salida)
    assert "captura.json:2: instrumentation_key" in texto and ".venv" not in texto and _sin_valores(texto)
    assert f.read_bytes() == original  # sin --fix no toca nada
    salida.clear()
    assert ev.barrer([tmp_path], arreglar=True, out=salida.append) == 0
    nuevo = f.read_bytes()
    assert _sin_valores(nuevo.decode("utf-8", "replace")) and b"\r\n" in nuevo and nuevo.endswith(b"\xff fin\r\n")
    assert "TAPADO" in "\n".join(salida) and ev.barrer([tmp_path], out=lambda _l: None) == 0


def test_barrer_un_contenedor_con_secreto_falla_aunque_se_pida_fix(tmp_path):
    z = tmp_path / "paquete.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("dentro.txt", CADENA_AI)
    salida = []
    assert ev.barrer([tmp_path], arreglar=True, out=salida.append) == 1
    assert "paquete.zip!dentro.txt:1" in "\n".join(salida) and _sin_valores("\n".join(salida))


def test_barrer_declara_lo_que_no_revisa(tmp_path, monkeypatch):
    (tmp_path / "grande.txt").write_text("x" * 50, encoding="utf-8")
    monkeypatch.setattr(ev, "TAM_MAX", 10)
    salida = []
    assert ev.barrer([tmp_path], out=salida.append) == 3 and "SIN REVISAR" in "\n".join(salida)


def test_barrer_ruta_inexistente_falla_en_alto(tmp_path):
    with pytest.raises(SystemExit, match="No existe"):
        ev.barrer([tmp_path / "no-hay"])


@pytest.mark.parametrize("ruta", ["_baseline/obtener_arm.py", "_baseline/obtener_baseline.py",
                                  "pruebas/I0/VERIF/scripts/arm_ahora.py",
                                  "observabilidad/conectar_appinsights.py"])
def test_los_scripts_de_captura_escriben_por_lib_evidencia(ruta):
    t = (RAIZ / ruta).read_text(encoding="utf-8")
    assert "from lib import evidencia" in t and "evidencia.guardar_enmascarado(" in t
    assert "write_text(json.dumps" not in t and "SECRETOS = {" not in t


def test_barrer_declara_los_binarios_y_los_contenedores_rotos(tmp_path):
    (tmp_path / "foto.png").write_bytes(b"\x89PNG" + CADENA_AI.encode())
    (tmp_path / "sin_ext").write_bytes(b"\x00\x01" + CADENA_AI.encode())
    (tmp_path / "roto.zip").write_bytes(b"PK\x03\x04 no es un zip")
    salida = []
    assert ev.barrer([tmp_path], out=salida.append) == 3
    texto = "\n".join(salida)
    assert "binarios no revisados (declarados): (sin extensión) 1, .png 1" in texto
    assert "SIN REVISAR " in texto and "roto.zip: contenedor ilegible (BadZipFile)" in texto


def test_secretos_en_zip_respeta_el_tope_por_miembro(monkeypatch):
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("grande.txt", "a" * 5000)
        z.writestr("ok.txt", CADENA_AI)
    monkeypatch.setattr(ev, "TAM_MAX_MIEMBRO", 1000)
    hall, omit = ev.secretos_en_zip(buf.getvalue(), "p.zip")
    assert sorted(hall) == ["p.zip!ok.txt:1: application_id", "p.zip!ok.txt:1: instrumentation_key"]
    assert omit == ["p.zip!grande.txt: más de 1000 bytes descomprimido"]


def test_secretos_en_zip_lee_todos_los_miembros_aunque_se_repita_el_nombre():
    import io
    import warnings
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # zipfile avisa del nombre duplicado
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("x.txt", CADENA_AI)
            z.writestr("x.txt", "inofensivo")
    hall, omit = ev.secretos_en_zip(buf.getvalue(), "d.zip")
    assert sorted(hall) == ["d.zip!x.txt:1: application_id", "d.zip!x.txt:1: instrumentation_key"] and omit == []
