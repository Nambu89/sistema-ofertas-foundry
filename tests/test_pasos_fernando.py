"""Pasos manuales de Fernando (paso 0b): invariantes de los scripts y funciones puras de comun.sh, sin red."""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

from tests import nombres_reales

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PASOS = RAIZ / "pasos-fernando"
SCRIPTS = sorted(PASOS.glob("0*.sh"))
TODOS = [*SCRIPTS, PASOS / "comun.sh"]
VERSIONADOS = [*TODOS, PASOS / "README.md", PASOS / "local.conf.ejemplo"]
BASH = shutil.which("bash")

necesita_bash = pytest.mark.skipif(BASH is None, reason="sin bash en el PATH")


def _sin_comentarios(texto: str) -> list[str]:
    return [l for l in texto.splitlines() if not l.lstrip().startswith("#")]


def test_estan_los_nueve_scripts():
    nombres = {p.name for p in SCRIPTS}
    assert nombres == {
        "01-roles-coordinador.sh", "02-storage.sh", "03-conexion-marcador.sh",
        "04a-rotar-azure-foundry-key.sh", "04b-rotar-nvidia-key.sh", "04c-rotar-clave-azure-filtrada.sh",
        "04d-rotar-clave-gcp.sh", "05-opencode-password.sh", "06-cerrar-p4b.sh",
    }


@pytest.mark.parametrize("ruta", VERSIONADOS, ids=lambda p: p.name)
def test_solo_lf_y_sin_marcadores(ruta):
    datos = ruta.read_bytes()
    assert b"\r" not in datos, "CR en el fichero (LES-G-099)"
    texto = datos.decode("utf-8")
    assert not re.search(r"\bTBD\b|pendiente de definir|<PLACEHOLDER>", texto)


@pytest.mark.parametrize("ruta", VERSIONADOS, ids=lambda p: p.name)
def test_sin_nombres_de_otros_proyectos(ruta):
    # La lista es local y no se versiona: sin config/nombres-reales.local.txt la prueba se omite y lo
    # dice (tests/nombres_reales.py). Aquí se busca también dentro de otras palabras.
    prohibidos = nombres_reales.cargar()
    texto = nombres_reales.normalizar(ruta.read_text(encoding="utf-8"))
    for prohibido in prohibidos:
        assert prohibido not in texto, prohibido


def test_local_conf_no_se_versiona():
    r = subprocess.run(["git", "check-ignore", "-q", "pasos-fernando/local.conf"], cwd=RAIZ)
    assert r.returncode == 0


@necesita_bash
@pytest.mark.parametrize("ruta", TODOS, ids=lambda p: p.name)
def test_sintaxis_bash(ruta):
    r = subprocess.run([BASH, "-n", str(ruta)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("ruta", SCRIPTS, ids=lambda p: p.name)
def test_contrato_de_cada_script(ruta):
    texto = ruta.read_text(encoding="utf-8")
    codigo = "\n".join(_sin_comentarios(texto))
    assert 'source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"' in texto
    assert "--confirmar) CONFIRMAR=1" in texto
    assert re.search(r"^\s*(confirmar|.*\bconfirmar) \"", codigo, re.M), "no pide confirmación"
    assert "Uso:" in texto
    assert "az account set" not in codigo
    assert "set -x" not in codigo


def test_regenerar_nunca_imprime_las_claves():
    for ruta in TODOS:
        for linea in _sin_comentarios(ruta.read_text(encoding="utf-8")):
            if "keys regenerate" in linea:
                assert "-o none" in linea, f"{ruta.name}: {linea}"
    comun = (PASOS / "comun.sh").read_text(encoding="utf-8")
    assert "keys regenerate" in comun


SECRETOS = ("CLAVE", "NUEVA", "ACT", "ANT", "PW", "K1", "K2", "TOKEN", "OFA_VALOR", "OFA_CLAVE", "v")
IMPRIME = re.compile(r"^\s*(echo|printf|info|ok|aviso|progreso|fallo)\b")


@pytest.mark.parametrize("ruta", TODOS, ids=lambda p: p.name)
def test_ninguna_linea_que_imprime_muestra_un_secreto(ruta):
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if not IMPRIME.match(linea):
            continue
        if re.match(r"^\s*printf -v ", linea) or "| curl -s -K -" in linea:
            continue  # asigna a una variable o alimenta la entrada estándar de curl: no imprime
        # Funciones que reciben la clave pero solo devuelven una huella o un código HTTP.
        limpia = re.sub(r'\$\((huella|codigo_con_cabecera|probar) [^)]*\)', "", linea)
        limpia = re.sub(r"\$\{#\w+\}", "", limpia)
        for s in SECRETOS:
            assert not re.search(r"\$\{?" + s + r"\b(?![(\[])", limpia), f"{ruta.name}:{n}: {linea.strip()}"


def test_los_secretos_no_van_en_la_linea_de_ordenes_de_curl():
    comun = (PASOS / "comun.sh").read_text(encoding="utf-8")
    assert "curl -s -K -" in comun
    for ruta in SCRIPTS:
        for linea in _sin_comentarios(ruta.read_text(encoding="utf-8")):
            if "curl " in linea:
                assert "-H \"Authorization" not in linea and "api-key:" not in linea, f"{ruta.name}: {linea}"


def _bash_comun(guion: str, entrada: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-c", f'source "{PASOS.as_posix()}/comun.sh"; {guion}'],
                          input=entrada, capture_output=True, text=True, encoding="utf-8", timeout=60)


@necesita_bash
def test_comun_carga_la_configuracion():
    r = _bash_comun('echo "$TENANT|$SUB|$RECURSO|$COORD_DEF|$AGENTES|$ROL_CONSUMER"')
    assert r.returncode == 0, r.stderr
    tenant, sub, recurso, coord, agentes, rol = r.stdout.strip().split("|")
    # conftest fija OFA_ENTORNO en la plantilla: valores ficticios, nunca el entorno real.
    assert tenant == sub == "00000000-0000-0000-0000-000000000000"
    assert recurso == "mi-recurso-foundry"
    assert coord == "ofa-coordinador"
    assert agentes.split() == ["ofa-facilitador", "ofa-investigador", "ofa-experto-ms", "ofa-arquitecto",
                               "ofa-estimador", "ofa-verificador"]
    assert rol == "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"


@necesita_bash
def test_confirmar_sin_terminal_ni_flag_sale_con_3_sin_hacer_nada():
    r = _bash_comun('confirmar "prueba"; echo HECHO')
    assert r.returncode == 3
    assert "HECHO" not in r.stdout
    assert "SOLO PLAN" in r.stdout


@necesita_bash
def test_confirmar_con_flag_sigue():
    r = _bash_comun('CONFIRMAR=1; confirmar "prueba"; echo HECHO')
    assert r.returncode == 0 and "HECHO" in r.stdout


@necesita_bash
def test_huella_y_valor_seguro():
    r = _bash_comun('huella abc; valor_seguro "abc" && echo SI1; valor_seguro "a\\"b" || echo NO2; '
                    'valor_seguro "" || echo NO3')
    lineas = r.stdout.split()
    assert lineas[0] == "ba7816bf8f01"  # SHA-256 de «abc»
    assert lineas[1:] == ["SI1", "NO2", "NO3"]


@necesita_bash
def test_cargar_local_solo_admite_claves_rot(tmp_path):
    (tmp_path / "local.conf").write_text("# comentario\nROT_UNO=valor con espacios\nOTRA=no\nROT_DOS=b=c\n",
                                         encoding="utf-8", newline="\n")
    r = _bash_comun(f'DIR_PASOS="{tmp_path.as_posix()}"; cargar_local; '
                    'echo "${LOCAL_ROT_UNO}|${LOCAL_ROT_DOS}|${LOCAL_OTRA:-vacía}"')
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "valor con espacios|b=c|vacía"


@necesita_bash
def test_fallo_sale_con_el_codigo_pedido():
    r = _bash_comun('fallo 4 "algo"; echo NO')
    assert r.returncode == 4 and "NO" not in r.stdout and "FALLO: algo" in r.stderr


@necesita_bash
@pytest.mark.parametrize("salida,error,codigo_az,rc,esperado", [
    ("CustomKeys\nCustomKeys\nhttps://x\n", "", 0, 0, "CustomKeys CustomKeys https://x"),
    ("", "Not Found({\"error\":{\"code\":\"NotFound\"}})", 1, 4, ""),
    ("", "ConnectionResetError: conexión reiniciada", 1, 1, ""),
])
def test_leer_conexion_distingue_no_existe_de_error(tmp_path, salida, error, codigo_az, rc, esperado):
    falso = tmp_path / "az"
    falso.write_text(f"#!/usr/bin/env bash\nprintf '%s' '{salida}'\nprintf '%s' '{error}' >&2\nexit {codigo_az}\n",
                     encoding="utf-8", newline="\n")
    falso.chmod(0o755)
    r = _bash_comun(f'export PATH="$(cygpath -u "{tmp_path.as_posix()}"):$PATH"; x="$(leer_conexion https://arm/x)" || exit $?; '
                    'printf "%s" "$x"')
    assert r.returncode == rc, r.stderr
    assert r.stdout == esperado


@necesita_bash
@pytest.mark.parametrize("valor,mensaje", [
    ("   ", "OFA_ENTORNO está definida pero vacía"),
    ("C:/no-existe/entorno.local.json", "Copia config/entorno.ejemplo.json a config/entorno.local.json"),
])
def test_comun_sin_configuracion_valida_falla_en_alto(monkeypatch, valor, mensaje):
    monkeypatch.setenv("OFA_ENTORNO", valor)
    r = _bash_comun('echo "$TENANT"')
    assert r.returncode == 1 and mensaje in r.stderr and not r.stdout.strip(), (r.returncode, r.stderr)


@necesita_bash
@pytest.mark.parametrize("nombre", ["entorno.local.json", "entorno.ejemplo.json"])
def test_comun_rechaza_una_copia_sin_rellenar_de_la_plantilla(monkeypatch, tmp_path, nombre):
    copia = tmp_path / nombre  # también con el mismo nombre que la plantilla, fuera de config/
    copia.write_bytes((RAIZ / "config" / "entorno.ejemplo.json").read_bytes())
    monkeypatch.setenv("OFA_ENTORNO", copia.as_posix())
    r = _bash_comun('echo "$TENANT"')
    assert r.returncode == 1 and "conserva valores ficticios de la plantilla" in r.stderr, (r.returncode, r.stderr)
    assert "tenant_id suscripcion_id grupo_recursos recurso proyecto" in r.stderr and not r.stdout.strip()
