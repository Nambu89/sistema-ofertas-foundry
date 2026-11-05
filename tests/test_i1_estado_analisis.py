"""Pruebas de T2 y T3 por la CLI (papel BA): eco del brief, respuesta del experto, consolidado y
rondas de verificación. Sin red; B, C y D con dobles."""
from __future__ import annotations

import copy

import pytest

from tests.test_i1_estado_comun import Mundo, ejemplo
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def _registrar(m, resp, n=1):
    return m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada(f"respuesta_experto_AZ_R{n}.json", resp))


def test_eco_distinto_es_intento_t2_con_linea_y_columna(m):
    """PR19-1 (I1.10): un eco no literal ya no bloquea en el mismo turno: suma un intento T2 con el motivo (línea y
    columna) y no se registra; la cabecera ya no lleva huellas (Nubes pasa de la línea 11 a la 9)."""
    m.hasta_analisis()
    m.run("enrutar")
    resp = ejemplo("respuesta_experto")
    assert "sha256_cuerpo" not in resp["brief_recibido"] and "catalogo_sha256" not in resp["brief_recibido"]
    resp["brief_recibido"] = resp["brief_recibido"].replace("Nubes: Azure", "Nubes: Azure y AWS")
    rc, out = _registrar(m, resp)
    assert rc == 1 and "estado: BLOQUEADA" not in out and "intento 1/3" in out
    assert "brief_recibido: no es literal" in out and "línea 9" in out and "expertos: azure=BRIEF_ENVIADO" in out


def test_eco_distinto_tres_veces_bloquea(m):
    """PR19-1: el tope de T2 sigue: a la tercera respuesta con el eco no literal, BLOQUEADA (falla cerrado)."""
    m.hasta_analisis()
    m.run("enrutar")
    resp = ejemplo("respuesta_experto")
    resp["brief_recibido"] = resp["brief_recibido"].replace("Nubes: Azure", "Nubes: Azure y AWS")
    salidas = [_registrar(m, resp, n=1) for _ in range(3)]
    assert [rc for rc, _ in salidas[:2]] == [1, 1] and "intento 2/3" in salidas[1][1]
    assert "estado: BLOQUEADA" in salidas[2][1] and "intento 3/3" in salidas[2][1]


def test_eco_literal_con_brief_id_distinto_sigue_bloqueando(m):
    m.hasta_analisis()
    m.run("enrutar")
    resp = ejemplo("respuesta_experto")
    resp["brief_id"] = resp["brief_id"].replace("-R1", "-R2")
    rc, out = _registrar(m, resp)
    assert rc != 0 and "estado: BLOQUEADA" in out and "brief_id" in out


def test_eco_con_crlf_y_salto_final_es_identico(m):
    m.hasta_analisis()
    m.run("enrutar")
    resp = ejemplo("respuesta_experto")
    resp["brief_recibido"] = resp["brief_recibido"].replace("\n", "\r\n") + "\r\n"
    rc, out = _registrar(m, resp)
    assert rc == 0 and "expertos: azure=VALIDA" in out


def test_respuesta_con_valla_de_codigo_se_acepta(m):
    import json
    m.hasta_analisis()
    m.run("enrutar")
    texto = "```json\n" + json.dumps(ejemplo("respuesta_experto"), ensure_ascii=False) + "\n```"
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada("respuesta_experto_AZ_R1.json", texto))
    assert rc == 0


def test_respuesta_invalida_lista_todos_los_errores_y_cuenta_t2(m):
    m.hasta_analisis()
    m.run("enrutar")
    resp = ejemplo("respuesta_experto")
    resp["tareas_propuestas"][0]["perfil"] = "Arquitecto Cloud"
    resp["referencias"][1]["url"] = "https://learn.microsoft.com/es-es/dotnet/api/system"
    resp["componentes"][0]["catalogo_id"] = "az-no-existe"
    resp["precios"][0]["plantilla_id"] = "no-existe"  # integrador I1.7: la región del precio la pone el núcleo
    resp["riesgos"][0]["hechos"] = ["C-99"]
    resp["decisiones"][0] = "Región por decidir: TBD"
    rc, out = _registrar(m, resp)
    assert rc == 1 and "intento 1/3" in out and "T2 1/3" in out and "expertos: azure=BRIEF_ENVIADO" in out
    for trozo in ("perfil fuera de la tarifa", "fuera de la lista blanca", "az-no-existe", "plantilla_id «no-existe»",
                  "hecho C-99", "marcador 'TBD'"):
        assert trozo in out, trozo
    for _ in range(2):
        rc, out = _registrar(m, resp)
    assert rc == 1 and "estado: BLOQUEADA" in out and "T2 agotó 3/3" in out


def test_consolidar_sin_respuesta_rechazado(m):
    m.hasta_analisis()
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada("r.json", ejemplo("respuesta_experto")))
    assert rc == 3 and "primero enrutar" in out
    m.run("enrutar")
    rc, out = m.run("consolidar")
    assert rc == 3 and "estado: EN_ANALISIS" in out


def test_enrutar_idempotente_y_catalogo_cambiado(m):
    m.hasta_analisis()
    _, out1 = m.run("enrutar")
    rc, out2 = m.run("enrutar")
    assert rc == 0 and len(m.estado()["carga"]["briefs"]) == 1
    m.catalogo.write_bytes(m.catalogo.read_bytes() + b"\n")
    rc, out = m.run("enrutar")
    assert rc == 4 and "otro texto" in out


def test_consolidar_reimprime_en_verificacion(m):
    m.hasta_verificacion()
    rc, out = m.run("consolidar")
    assert rc == 0 and "=== CONSOLIDADO PARA preventa-verificador ===" in out and "estado: EN_VERIFICACION" in out


def _verificador(m, cambios: dict, n=1):
    resp = ejemplo("respuesta_verificador")
    resp["consolidado_id"] = m.estado()["carga"]["consolidado"]["consolidado_id"]
    resp["entrada_recibida_inicio"] = "\n".join(m.estado()["carga"]["consolidado"]["texto"].split("\n")[:3])
    for e in resp["elementos"]:
        e.update(cambios.get(e["id"], {}))
    return m.run("registrar-verificacion", "--respuesta", m.entrada(f"respuesta_verificador_R{n}.json", resp))


def test_verificador_sin_un_veredicto_cuenta_t3(m):
    m.hasta_verificacion()
    resp = ejemplo("respuesta_verificador")
    resp["elementos"] = resp["elementos"][1:]
    rc, out = m.run("registrar-verificacion", "--respuesta", m.entrada("respuesta_verificador_R1.json", resp))
    assert rc == 1 and "falta el veredicto de REF-01" in out and "T3 1/3" in out and "estado: EN_VERIFICACION" in out


def test_discrepa_vuelve_al_experto_con_correcciones_y_ronda_3_bloquea(m):
    m.hasta_verificacion()
    url = "https://learn.microsoft.com/azure/search/search-sku-tier"
    discrepa = {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": url}}
    rc, out = _verificador(m, discrepa)
    assert rc == 1 and "estado: EN_ANALISIS" in out and "ronda 1/3" in out and "SIGUIENTE PASO OBLIGATORIO: enrutar" in out
    rc, out = m.run("enrutar")
    assert "BRF-OF-KELVARA-001-A-AZ-R2" in out and "## Correcciones solicitadas por el verificador" in out
    assert f"- C-02 | DISCREPA | Basic | {url}" in out
    for n in (2, 3):
        resp = ejemplo("respuesta_experto")
        b = m.estado()["carga"]["briefs"][-1]
        resp["brief_recibido"], resp["brief_id"] = b["texto"], b["brief_id"]
        assert _registrar(m, resp, n)[0] == 0
        assert m.run("consolidar")[0] == 0
        rc, out = _verificador(m, discrepa, n)
        if n == 2:
            assert rc == 1 and "estado: EN_ANALISIS" in out
            m.run("enrutar")
    assert rc == 1 and "estado: BLOQUEADA" in out and "Ronda 3 de verificación con DISCREPA" in out


# I1.7 (R): el verificador ya no recibe precios (decisión 1 del comercial): los tres casos de P-01 desaparecen.
@pytest.mark.parametrize("cambio, verificada", [
    ({"REF-02": {"veredicto": "DISCREPA", "campo": "url", "valor_correcto": "https://learn.microsoft.com/es-es/azure/search/search-what-is-azure-search/",
                 "fuente_url": "https://learn.microsoft.com/azure/search/search-what-is-azure-search"}}, True),
    ({"REF-01": {"veredicto": "OBSERVACION", "valor_correcto": "Título más claro", "fuente_url": None}}, True),
    ({"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": None}}, False),
])
def test_reglas_de_evaluacion(m, cambio, verificada):
    m.hasta_verificacion()
    rc, out = _verificador(m, cambio)
    assert (rc == 0) is verificada, out
    assert ("estado: VERIFICADA" in out) is verificada


def test_respuesta_con_crlf_y_valla(m):
    import json
    m.hasta_analisis()
    m.run("enrutar")
    texto = "```json\r\n" + json.dumps(ejemplo("respuesta_experto"), ensure_ascii=False, indent=1).replace("\n", "\r\n") + "\r\n```"
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada("respuesta_experto_AZ_R1.json", texto))
    assert rc == 0, out


def test_consolidado_no_toca_precios_anonimiza_titulos_y_no_lleva_prosa(m):
    m.hasta_analisis()
    m.run("enrutar")
    resp = ejemplo("respuesta_experto")
    # integrador I1.7: el modelo ya no escribe precios (decisión 1); el número largo ya no puede llegar al consolidado
    resp["referencias"][1]["titulo"] = "Guía revisada por Marta Olmedo sobre Azure AI Search"
    resp["riesgos"][0]["texto"] = "La calidad de los informes de origen debe validarse antes de indexarlos."
    rc, out = _registrar(m, resp)
    assert rc == 0, out
    rc, out = m.run("consolidar")
    # I1.7 (R): el consolidado ya no lleva precios (ni el número largo que casaría como teléfono)
    assert rc == 0 and "0.000123456" not in out and "Guía revisada por [PERSONA]" in out
    assert "RG-01 |" not in out and "calidad de los informes" not in out  # la prosa no se verifica (LES-G-096)


def test_asumir_rechaza_marcadores(m):
    m.iniciar()
    m.run("suficiencia", "--requisitos", m.entrada("requisitos.json", m.requisitos_modelo()))
    rc, out = m.run("asumir", "--campo", "volumetria", "--valor", "Volumen pendiente de confirmar")
    assert rc == 2 and "marcadores" in out


@pytest.mark.parametrize("estropear, error", [
    (lambda r: r["componentes"][0].update(catalogo_id=None, desviacion_justificada="corta pero de más de"), "desviacion_justificada"),
    # integrador I1.7: la referencia de arquitectura la pone el núcleo desde arquitectura_id (lista del catálogo)
    (lambda r: r.update(arquitectura_id="arquitectura-inventada"), "arquitectura_id «arquitectura-inventada»"),
    (lambda r: r["flujos"].append({"origen": "C-01", "destino": "C-42", "descripcion": "Flujo inventado"}), "destino C-42"),
    (lambda r: r["precios"][0].update(effectiveStartDate="2024-13-45"), "effectiveStartDate"),
    (lambda r: r["componentes"].append(dict(r["componentes"][0])), "id repetido C-01"),
    (lambda r: r.update(extra=1), "extra"),
    (lambda r: r["tareas_propuestas"][0].update(horas_base=500), "horas_base"),
])
def test_validar_respuesta_experto_casos(estropear, error, monkeypatch):
    from tests.test_i1_estado_comun import experto, marcadores_doble
    import sys
    import types
    monkeypatch.setitem(sys.modules, "nucleo.textos_cliente", types.SimpleNamespace(marcadores=marcadores_doble))
    resp, br = ejemplo("respuesta_experto"), ejemplo("brief")
    perfiles = br["perfiles_permitidos"]
    assert i17_int.validar(copy.deepcopy(resp), br, ejemplo("catalogo_componentes"), perfiles) == []
    estropear(resp)
    errores = i17_int.validar(resp, br, ejemplo("catalogo_componentes"), perfiles)
    assert any(error in e for e in errores), errores
