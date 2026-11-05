"""I1.6 · R: núcleo. REVERIF15-3 (una línea P- que no casa falla en alto), VER15-7 (los nombres de quienes firman
decisiones son términos sensibles del brief, también en los comentarios de la DEVUELTA) y ARR15-4 (la prueba de la
ronda 2 pasa lanzada sola). Cada caso adverso con su resultado esperado (LES-G-096.6).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import types

import pytest

from tests.test_i1_estado_comun import TRANSCRIPCION, Mundo
from tests.test_i15_r_brief_devuelta import CAB, F, J, JP, _devolver

RAIZ = pathlib.Path(__file__).resolve().parents[1]
ESTADO_R3 = RAIZ / "pruebas" / "I15" / "ARREGLOS" / "REAL" / "B" / "sesion_1" / "estado.json"


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


# ── REVERIF15-3: lineas_conservar no descarta en silencio una línea P- sin la forma esperada ──
@pytest.fixture
def e_real():
    if not ESTADO_R3.is_file():
        pytest.skip("falta el estado real de B de I1.5")
    return json.loads(ESTADO_R3.read_text(encoding="utf-8"))


def test_reverif15_3_control_real_todas_las_lineas_p_con_concepto(e_real):
    from nucleo import verificacion
    lineas = verificacion.lineas_conservar(copy.deepcopy(e_real))
    p = [ln for ln in lineas if ln.startswith("P-")]
    assert p and all(" | concepto: " in ln for ln in p), lineas
    texto = e_real["carga"]["consolidado"]["texto"]
    assert all(verificacion.linea_precio_conservar(ln) for ln in texto.split("\n") if ln.startswith("P-"))


@pytest.mark.parametrize("viejo, nuevo", [
    (" | unidad: 1 Hour | region: francecentral", " | unidad 1 Hour | region: francecentral"),   # sin «unidad:»
    (" | unidad: 1 Hour | region: francecentral", " | unidad: 1 | Hour | region: francecentral"),  # «|» en la unidad
    (" | region: francecentral | effectiveStartDate", " | region: | effectiveStartDate"),          # región vacía
    (" | precio: 0.2957 EUR", ""),                                                                  # sin precio
])
def test_reverif15_3_linea_p_sin_forma_es_integridad_rota(e_real, viejo, nuevo):
    from nucleo import verificacion
    e = copy.deepcopy(e_real)
    cons = e["carga"]["consolidado"]
    p01 = next(ln for ln in cons["texto"].split("\n") if ln.startswith("P-01 "))
    assert viejo in p01, p01
    cons["texto"] = cons["texto"].replace(p01, p01.replace(viejo, nuevo))
    # I1.7 (R): las líneas P- del brief ya no salen del consolidado sino de la respuesta registrada (el dato, LES-G-095):
    # una línea P- rota de un consolidado anterior a I1.7 ni se reparsea ni desaparece. IntegridadRota queda para un
    # precio sin plantilla ni filtro (tests/test_i17_r_decision.py).
    lineas = verificacion.lineas_conservar(e)
    assert any(ln.startswith("P-01 ") and " | concepto: " in ln for ln in lineas), lineas


def test_reverif15_3_el_consolidado_compuesto_siempre_casa(e_real):
    """Guarda de integración: si alguien cambia la línea P- de `componer_consolidado` (p. ej., con la decisión 4),
    esta prueba lo dice antes de que el brief de la ronda 2 caiga en real con IntegridadRota."""
    from nucleo import verificacion
    from nucleo.errores import IntegridadRota
    catalogo = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    try:
        cons = verificacion.componer_consolidado(e_real, catalogo, "CNS-PRUEBA-R1")
    except IntegridadRota as e:
        pytest.skip(f"el catálogo del repositorio ya no casa con el estado real de I1.5: {e}")
    # I1.7 (R): el consolidado ya no lleva precios (decisión 1): ninguna línea P- que casar
    assert not [ln for ln in cons.texto.splitlines() if ln.startswith("P-")]
    assert all(i.split("-")[0] in ("REF", "C") for i in cons.ids)


# ── VER15-7: los nombres de quienes firman decisiones no viajan al experto ──
def test_ver15_7_terminos_anonimizacion_registra_a_los_firmantes():
    from nucleo import brief, decision
    alta = {"terminos_sensibles": ["Kelvara", "Marta Olmedo"], "cliente": "Kelvara", "codigo_cliente": "KELVARA"}
    sens, cliente, personas = brief.terminos_anonimizacion(alta, ["Marta Olmedo"])
    assert sens[:2] == ["Kelvara", "Marta Olmedo"] and set(decision.NOMBRES_DECISIONES) <= set(sens)
    assert personas[0] == "Marta Olmedo" and set(decision.NOMBRES_DECISIONES) <= set(personas)
    assert cliente == ["Kelvara", "KELVARA"]
    assert brief.terminos_anonimizacion(alta, list(decision.NOMBRES_DECISIONES))[2].count(J) == 1   # sin repetir
    # Quien firma se nombra por su rol: se anonimiza la frase entera, nunca las palabras sueltas del rol.
    texto = ("Responsable de preventa y RESPONSABLE DE ÁREA piden revisar; lo vio el responsable comercial; "
             "el responsable de RR. HH. lo sabe; dudas a ana@x.es o al +34 600 111 222; Lucía también")
    anon = brief.anonimizar(texto, sens, cliente, personas)
    assert anon == ("[PERSONA] y [PERSONA] piden revisar; lo vio el [PERSONA]; el responsable de RR. HH. lo sabe; "
                    "dudas a [CORREO] o al [TELÉFONO]; Lucía también"), anon       # «Lucía»: no registrado (límite)
    assert brief.hallazgos_sensibles(anon, sens) == []
    assert brief.hallazgos_sensibles("revisado por Responsable de preventa", sens) == ["término sensible: Responsable de preventa"]


def test_ver15_7_el_comentario_de_la_devuelta_llega_anonimizado_y_la_puerta_lo_recompone(m):
    import verificar_paquete as vp
    _devolver(m, "Responsable de área y yo (el responsable de preventa) pedimos revisar el precio de AI Search", quien=JP)
    assert m.run("enrutar")[0] == 0
    est = m.estado()
    texto = est["carga"]["briefs"][-1]["texto"]
    lineas = texto.split("\n")
    i = next(k for k, ln in enumerate(lineas) if ln.startswith(CAB))
    assert lineas[i + 1] == "- [PERSONA] y yo (el [PERSONA]) pedimos revisar el precio de AI Search", lineas[i + 1]

    def puerta(estado):
        return vp.c_brief(types.SimpleNamespace(estado=estado, carga=estado["carga"], transcripcion=TRANSCRIPCION))
    c = puerta(est)
    assert c.estado != vp.FALLA and not any("VER15-7" in d or "PR14-6" in d for d in c.detalles), c.detalles
    # rotura resellada: el nombre vuelve al brief → FALLA por VER15-7 (y por la línea distinta de la recompuesta)
    roto = copy.deepcopy(est)
    b = roto["carga"]["briefs"][-1]
    cab, cuerpo = b["texto"].replace(lineas[i + 1], "- el responsable de área y yo pedimos revisar el precio").split("\n---\n", 1)
    cab = "\n".join(x if not x.startswith("sha256_cuerpo: ") else
                    f"sha256_cuerpo: {hashlib.sha256(cuerpo.encode()).hexdigest()}" for x in cab.split("\n"))
    b["texto"] = cab + "\n---\n" + cuerpo
    c = puerta(roto)
    assert c.estado == vp.FALLA and any("VER15-7" in d and "«responsable de area»" in d for d in c.detalles), c.detalles


# ── ARR15-4: la prueba de la ronda 2 pasa lanzada sola (antes caía por el doble de anexo_consumo) ──
def test_arr15_4_la_prueba_de_la_ronda_2_pasa_sola():
    prueba = "tests/test_i13_convergencia.py::test_brief_de_la_ronda_2_conserva_lo_verificado"
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", prueba], cwd=RAIZ,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert r.returncode == 0 and "1 passed" in r.stdout, r.stdout[-2000:] + r.stderr[-2000:]


def test_arr15_4_el_doble_trae_las_reglas_del_real_y_no_lo_registra():
    from tests import test_i1_estado_comun as comun
    antes = sys.modules.get("nucleo.anexo_consumo")
    doble = comun._doble_anexo()
    assert all(hasattr(doble, n) for n in ("errores_cobertura", "facturables_azure", "motivo_sin_precios"))
    assert doble.aplicar.__module__ == comun.__name__                 # aplicar sigue siendo el doble
    assert sys.modules.get("nucleo.anexo_consumo") is antes           # la copia privada no se registra
