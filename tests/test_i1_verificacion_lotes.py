"""Papel V (I1.1): verificación por lotes, DISCREPA frente a OBSERVACION, texto original en las correcciones,
metatexto del experto, lista blanca ampliada y límite de hechos (LES-G-096, H-V1, H-V4, H-V6 y H-V8).

Por la CLI real (Mundo) y por las funciones puras de nucleo.verificacion y nucleo.experto. Sin red."""
from __future__ import annotations

import copy
import json
import re
import sys

import pytest

from tests.test_i1_estado_comun import ESQUEMAS, Mundo, SANDBOX, ejemplo

sys.path.insert(0, str(SANDBOX))
from nucleo import esquema, experto, verificacion  # noqa: E402

PRECIOS = "https://prices.azure.com/api/retail/prices"
URL_OK = "https://learn.microsoft.com/azure/search/search-sku-tier"
# Registro parcial de un lote: la CLI actual devuelve 1 («CON DISCREPANCIAS», sin transición); con el parche
# propuesto a R (docs/I1/CAMBIOS-I11-V.md) devuelve 0. Lo que se comprueba es el estado, no ese rc.
PARCIAL = (0, 1)


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def _cons(m) -> dict:
    return m.estado()["carga"]["consolidado"]


def _resp(objetivo_id: str, texto: str, ids: list[str], cambios: dict | None = None) -> dict:
    tipos = {"REF": "referencia", "C": "componente", "P": "precio"}
    elementos = [{"id": i, "tipo": tipos[i.split("-")[0]], "veredicto": "OK", "campo": "ninguno",
                  "detalle": "Comprobado con la herramienta.", "valor_correcto": None, "fuente_url": None} for i in ids]
    for e in elementos:
        e.update((cambios or {}).get(e["id"], {}))
    cuenta = {v: sum(e["veredicto"] == k for e in elementos)
              for v, k in (("ok", "OK"), ("discrepa", "DISCREPA"), ("observacion", "OBSERVACION"),
                           ("no_verificable", "NO VERIFICABLE"))}
    return {"agente": "preventa-verificador", "consolidado_id": objetivo_id, "entrada_recibida_inicio": "\n".join(texto.split("\n")[:3]),
            "elementos": elementos, "resumen": cuenta,
            "herramientas_usadas": {"microsoft_docs_search": 2, "microsoft_docs_fetch": 2}}  # I1.7: sin precios_azure


def _registrar(m, resp: dict, nombre: str = "v.json") -> tuple[int, str]:
    return m.run("registrar-verificacion", "--respuesta", m.entrada(nombre, resp))


def _todos_los_lotes(m, cambios: dict | None = None) -> tuple[int, str]:
    rc, out = 0, ""
    for n, lote in enumerate(_cons(m)["lotes"], start=1):
        rc, out = _registrar(m, _resp(lote["lote_id"], lote["texto"], lote["ids"], cambios), f"lote{n}.json")
    return rc, out


# --- Consolidado: solo lo verificable, en lotes ---

def test_consolidado_sin_prosa_con_tipo_suscripcion_y_respalda(m):
    m.hasta_verificacion()
    c = _cons(m)
    assert "## Textos para el cliente" not in c["texto"] and not re.search(r"^(S|RG)-\d{2} \|", c["texto"], re.M)
    assert all(re.fullmatch(r"(REF|C|P)-\d{2}", i) for i in c["ids"])
    cab = c["texto"].split("\n---\n", 1)[0].split("\n")
    assert cab[:3] == ["CONSOLIDADO-PREVENTA/1", f"consolidado_id: {c['consolidado_id']}", cab[2]] and cab[2].startswith("brief_id: ")
    assert any(ln.startswith("tipo_suscripcion: ") for ln in cab)
    # CMP-1 (I1.3): la referencia se juzga en la línea de cada componente (con su URL); la de la referencia solo
    # lleva URL y título.
    refs = [ln for ln in c["texto"].split("\n") if ln.startswith("REF-")]
    assert refs and all(ln.count(" | ") == 2 and " | respalda: " not in ln for ln in refs)
    comps = [ln for ln in c["texto"].split("\n") if ln.startswith("C-")]
    assert comps and all(re.search(r" \| referencia: https://learn\.microsoft\.com/\S+$", ln) for ln in comps)


def test_lotes_parten_los_ids_por_tipo_y_tamano(m):
    m.hasta_verificacion()
    c = _cons(m)
    ids = [i for x in c["lotes"] for i in x["ids"]]
    assert ids == c["ids"]  # partición exacta y en orden
    lineas = {ln.split(" | ", 1)[0]: ln for ln in c["texto"].split("\n") if re.match(r"(REF|C|P)-\d{2} \|", ln)}
    for n, x in enumerate(c["lotes"], start=1):
        assert x["lote_id"] == f"{c['consolidado_id']}-L{n}"
        assert len(x["ids"]) <= verificacion.LOTE_MAX[x["ids"][0].split("-")[0]]
        assert len({i.split("-")[0] for i in x["ids"]}) == 1
        cuerpo = x["texto"].split("\n---\n", 1)[1].split("\n")
        assert cuerpo[1:] == [lineas[i] for i in x["ids"]]  # líneas idénticas a las del consolidado
        assert x["texto"].startswith(f"CONSOLIDADO-PREVENTA/1\nconsolidado_id: {x['lote_id']}\nlote: {n} de {len(c['lotes'])} (")
        assert x["sha256"] == verificacion.hashes.sha256_texto(x["texto"]) and x["respuesta"] is None


def test_tamano_de_los_lotes_con_el_maximo_del_esquema():
    # I1.7 (R): sin lote de precios (decisión 1 del comercial)
    por_tipo = {"REF": [f"REF-{i:02d} | x" for i in range(1, 16)], "C": [f"C-{i:02d} | x" for i in range(1, 21)]}
    lotes = verificacion._lotes("CNS-OF-KELVARA-001-A-R1", ["brief_id: B"], por_tipo)
    assert [len(x.ids) for x in lotes] == [4, 4, 4, 3, 5, 5, 5, 5]
    assert all(re.fullmatch(r"CNS-OF-KELVARA-001-A-R1-L\d{1,2}", x.lote_id) for x in lotes)


def test_api_de_lotes_para_la_opcion_b(m):
    m.hasta_verificacion()
    est = m.estado()
    pend = verificacion.lotes_pendientes(est)
    assert [x["lote_id"] for x in pend] == [x["lote_id"] for x in _cons(m)["lotes"]] and not any(x["registrado"] for x in pend)
    primero = pend[0]
    assert _registrar(m, _resp(primero["lote_id"], primero["texto"], primero["ids"]))[0] in PARCIAL
    est = m.estado()
    assert est["estado"] == "EN_VERIFICACION" and est["carga"]["verificacion"] is None
    assert [x["lote_id"] for x in verificacion.lotes_pendientes(est)] == [x["lote_id"] for x in pend[1:]]
    assert verificacion.lotes(est)[0]["registrado"] is True


# --- Registro por lotes, respuesta completa y combinación ---

def test_todos_los_lotes_dan_verificada_y_respuesta_combinada_valida(m):
    m.hasta_verificacion()
    rc, out = _todos_los_lotes(m)
    assert rc == 0 and "estado: VERIFICADA" in out, out
    est = m.estado()
    ver, cons = est["carga"]["verificacion"], est["carga"]["consolidado"]
    assert ver["lotes"] == [x["lote_id"] for x in cons["lotes"]] and ver["observaciones"] == []
    r = ver["respuesta"]
    assert r["consolidado_id"] == cons["consolidado_id"] and [e["id"] for e in r["elementos"]] == cons["ids"]
    assert esquema.validar(r, esquema.cargar("respuesta_verificador", ESQUEMAS)) == []
    assert r["resumen"] == {"ok": len(cons["ids"]), "discrepa": 0, "observacion": 0, "no_verificable": 0}
    assert all(x["respuesta"] is not None and x["registrada_el"] for x in cons["lotes"])


def test_respuesta_completa_sigue_valiendo(m):
    m.hasta_verificacion()
    c = _cons(m)
    rc, out = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"]))
    assert rc == 0 and "estado: VERIFICADA" in out, out
    assert m.estado()["carga"]["verificacion"]["lotes"] == []


def test_completa_tras_un_lote_y_lote_repetido_distinto_son_integridad_rota(m):
    m.hasta_verificacion()
    c = _cons(m)
    l1 = c["lotes"][0]
    assert _registrar(m, _resp(l1["lote_id"], l1["texto"], l1["ids"]), "a.json")[0] in PARCIAL
    assert _registrar(m, _resp(l1["lote_id"], l1["texto"], l1["ids"]), "b.json")[0] in PARCIAL  # idéntica: idempotente
    assert m.estado()["estado"] == "EN_VERIFICACION"
    rc, out = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"]), "c.json")
    assert rc == 4 and "no se mezcla con lotes" in out, out
    otra = _resp(l1["lote_id"], l1["texto"], l1["ids"], {l1["ids"][0]: {"detalle": "Otra comprobación distinta."}})
    rc, out = _registrar(m, otra, "d.json")
    assert rc == 4 and "ya está registrado con otra respuesta" in out, out
    assert m.estado()["intentos"]["T3"] == 0


def test_lote_ajeno_o_con_ids_de_otro_lote_cuenta_t3(m):
    m.hasta_verificacion()
    c = _cons(m)
    l1, l2 = c["lotes"][0], c["lotes"][1]
    rc, out = _registrar(m, _resp(l1["lote_id"] + "9", l1["texto"], l1["ids"]), "a.json")
    assert rc == 1 and "consolidado_id: devuelve" in out and "T3 1/3" in out, out
    rc, out = _registrar(m, _resp(l1["lote_id"], l1["texto"], l2["ids"]), "b.json")
    assert rc == 1 and "no está en lo enviado" in out and "T3 2/3" in out, out


# --- DISCREPA de hecho frente a OBSERVACION editorial (H-V1) ---

def test_discrepa_sin_fuente_es_error_de_contrato(m):
    m.hasta_verificacion()
    c = _cons(m)
    rc, out = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"],
                                  {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic",
                                            "fuente_url": None}}))
    assert rc == 1 and "DISCREPA exige valor_correcto y fuente_url" in out and "T3 1/3" in out, out
    assert m.estado()["estado"] == "EN_VERIFICACION"


def test_observacion_no_bloquea_y_va_a_observaciones(m):
    m.hasta_verificacion()
    obs = {"REF-01": {"veredicto": "OBSERVACION", "detalle": "El título tiene una errata menor.",
                      "valor_correcto": "Arquitectura de referencia", "fuente_url": None}}
    rc, out = _todos_los_lotes(m, obs)
    assert rc == 0 and "estado: VERIFICADA" in out, out
    ver = m.estado()["carga"]["verificacion"]
    assert [o["id"] for o in ver["observaciones"]] == ["REF-01"] and ver["resultado"]["discrepa"] == []
    assert ver["observaciones"][0]["texto_original"].startswith("REF-01 | https://learn.microsoft.com/")


def test_observacion_de_precio_con_numero_distinto_es_discrepa(m):
    # I1.7 (R): el verificador ya no recibe precios; un veredicto sobre un precio es un error de contrato (T3), no una
    # DISCREPA: el precio sale de la instantánea del despliegue.
    m.hasta_verificacion()
    c = _cons(m)
    original = m.estado()["carga"]["respuestas_expertos"]["azure"]["respuesta"]["precios"][0]["precio"]
    cambio = {"P-01": {"veredicto": "OBSERVACION", "valor_correcto": str(round(original * 2 + 1, 4)), "fuente_url": None}}
    rc, out = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"] + ["P-01"], cambio))
    assert rc != 0 and "P-01 no está en lo enviado" in out and "estado: EN_VERIFICACION" in out, out


def test_discrepa_con_fuente_lleva_el_texto_original_a_las_correcciones(m):
    m.hasta_verificacion()
    c = _cons(m)
    linea_c02 = next(ln for ln in c["texto"].split("\n") if ln.startswith("C-02 |"))
    rc, out = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"],
                                  {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic",
                                            "fuente_url": URL_OK}}))
    assert rc == 1 and "estado: EN_ANALISIS" in out, out
    est = m.estado()
    corr = verificacion.correcciones(est)
    assert corr == [{"id": "C-02", "veredicto": "DISCREPA", "valor_correcto": "Basic", "fuente_url": URL_OK,
                     "texto_original": linea_c02}]
    assert verificacion.lineas_correccion(corr[0]) == [f"- C-02 | DISCREPA | Basic | {URL_OK}", f"Texto original de C-02: {linea_c02}"]


def test_tope_de_rondas_bloquea_en_la_ultima(m):
    m.hasta_verificacion()
    discrepa = {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": URL_OK}}
    for n in range(1, verificacion.est_mod.MAX_RONDAS + 1):
        c = _cons(m)
        rc, out = _registrar(m, _resp(c["consolidado_id"], c["texto"], c["ids"], discrepa), f"v{n}.json")
        if n < verificacion.est_mod.MAX_RONDAS:
            assert rc == 1 and "estado: EN_ANALISIS" in out, out
            assert m.run("enrutar")[0] == 0
            resp = ejemplo("respuesta_experto")
            b = m.estado()["carga"]["briefs"][-1]
            resp["brief_recibido"], resp["brief_id"] = b["texto"], b["brief_id"]
            assert m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada(f"e{n}.json", resp))[0] == 0
            assert m.run("consolidar")[0] == 0
    assert rc == 1 and "estado: BLOQUEADA" in out and f"tope de {verificacion.est_mod.MAX_RONDAS} rondas" in out, out


# --- Experto: metatexto (H-V8), lista blanca ampliada y límite de hechos (H-V4) ---

@pytest.mark.parametrize("texto, esperado", [
    ("Las correcciones mencionan S-03 y S-04 previos, pero no incluyen el texto.", ["S-03", "S-04"]),
    ("Se revisará con el verificador en la ronda anterior.", ["verificador", "ronda anterior"]),
    ("El brief no indica el volumen; se asume R-volumetria.", ["brief", "R-volumetria"]),
    ("Corrección solicitada tras la consulta al agente preventa-verificador.", ["Corrección solicitada", "preventa-verificador"]),
    ("Se habilita un entorno sandbox de pruebas y el protocolo A2A entre agentes con Code Interpreter.", []),
    ("Azure AI Search S1 en swedencentral, 730 horas al mes; App Service P1v3 y Standard_D2s_v5.", []),
    ("La verificación de identidad usa Microsoft Entra ID; el consolidado mensual lo revisa el cliente.", []),
])
def test_metatexto_en_supuestos_riesgos_y_mitigaciones(texto, esperado):
    for bloque, campo in experto.CAMPOS_METATEXTO:
        x = {"id": "S-01" if bloque == "supuestos" else "RG-01", "texto": "Texto neutro del proyecto.", "mitigacion": "Neutra."}
        x[campo] = texto
        errores = experto.metatexto_en({bloque: [x]})
        if esperado:
            assert len(errores) == 1 and all(h in errores[0] for h in esperado), errores
        else:
            assert errores == []


def test_metatexto_rechaza_la_respuesta_del_experto(m):
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    resp = ejemplo("respuesta_experto")
    b = m.estado()["carga"]["briefs"][-1]
    resp["brief_recibido"], resp["brief_id"] = b["texto"], b["brief_id"]
    resp["riesgos"][0]["texto"] = "Las correcciones mencionan S-03 y S-04 previos, pero no incluyen el texto."
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", m.entrada("e.json", resp))
    assert rc == 1 and "metatexto del proceso interno" in out and "T2 1/3" in out, out


@pytest.mark.parametrize("url, ok", [
    ("https://learn.microsoft.com/es-es/azure/frontdoor/front-door-overview", True),
    ("https://learn.microsoft.com/fabric/fundamentals/microsoft-fabric-overview", True),
    ("https://learn.microsoft.com/power-bi/fundamentals/power-bi-overview", True),
    ("https://learn.microsoft.com/office365/servicedescriptions/teams-service-description", True),
    ("https://learn.microsoft.com/microsoft-365/enterprise/microsoft-365-overview", True),
    ("https://learn.microsoft.com/azure/frontdoorx/algo", False),
    ("https://learn.microsoft.com/answers/questions/1", False),
    ("https://learn.microsoft.com/training/modules/x", False),
    ("https://learn.microsoft.com/microsoft-365-copilot/extensibility/", False),
])
def test_lista_blanca_ampliada(url, ok):
    assert experto.es_referencia_permitida(url) is ok
    assert experto.es_referencia_arquitectura(url) is False


def test_prefijos_sin_duplicados_y_sin_rutas_de_contenido_ajeno():
    p = experto.PREFIJOS_REFERENCIA
    assert len(p) == len(set(p))
    assert not any(x.startswith(("/answers", "/training", "/shows", "/samples", "/archive", "/previous-versions")) for x in p)


def test_limite_de_hechos_doce():
    sch = esquema.cargar("respuesta_experto", ESQUEMAS)
    resp = ejemplo("respuesta_experto")
    resp["supuestos"][0]["hechos"] = ["R-objetivo"] * 12
    assert esquema.validar(resp, sch) == []
    resp["supuestos"][0]["hechos"] = ["R-objetivo"] * 13
    assert any("hechos" in e for e in esquema.validar(resp, sch))


# --- Instrucciones y formato derivado ---

def test_instrucciones_del_verificador_con_el_contrato_nuevo():
    from tests.test_i1_estado_comun import RAIZ
    t = (RAIZ / "agentes" / "instrucciones" / "verificador_i1.md").read_text(encoding="utf-8")
    for frase in ("`OBSERVACION`", "Sin fuente no hay DISCREPA", "-Ln", "`tipo_suscripcion`",
                  "menos de 90 segundos", "La prosa para el cliente no se te envía", "`observacion`"):
        assert frase in t, frase
    assert "S-nn" not in t and "## Textos" not in t
    assert "- `elementos`: entre 1 y 65 elementos." in t.splitlines()
    assert "precios_azure" not in t  # integrador I1.7 (decisión 1): el verificador ya no tiene herramienta de precios


def test_instrucciones_del_experto_con_lista_y_reglas_nuevas():
    from tests.test_i1_estado_comun import RAIZ
    t = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md").read_text(encoding="utf-8")
    for p in experto.PREFIJOS_REFERENCIA:
        assert f"`{p}`" in t, p
    assert "Texto original de <id>:" in t and "nunca del proceso interno" in t
    assert "- `supuestos[].hechos`: entre 1 y 12 elementos." in t.splitlines()


def test_text_format_del_verificador_con_observacion_y_precios():
    from agentes.esquemas import derivar_text_format as dtf
    s = dtf.text_format("respuesta_verificador")["schema"]
    assert s["properties"]["elementos"]["items"]["properties"]["veredicto"]["enum"] == ["OK", "DISCREPA", "OBSERVACION", "NO VERIFICABLE"]
    assert s["properties"]["herramientas_usadas"]["required"] == ["microsoft_docs_search", "microsoft_docs_fetch"]  # I1.7
    assert "observacion" in s["properties"]["resumen"]["required"]


def test_metatexto_con_ids_en_minusculas():
    errores = experto.metatexto_en({"riesgos": [{"id": "RG-01", "texto": "El identificador c-02 y r-plazo siguen abiertos.",
                                                  "mitigacion": "Neutra y sin referencias internas."}]})
    assert len(errores) == 1 and "c-02" in errores[0] and "r-plazo" in errores[0]


def test_esquema_historico_v1_para_paquetes_de_la_version_a():
    """Los paquetes de A validan con el histórico congelado y no con el vigente; el discriminante es
    precios_azure en herramientas_usadas (obligatorio en la v2, inexistente en la v1). La puerta lo carga
    como «historico/respuesta_verificador_v1» (docs/I1/CAMBIOS-I11-V.md, fragmento 12)."""
    from esquemas.comprobar_esquemas import validar
    v1 = json.loads((ESQUEMAS / "historico" / "respuesta_verificador_v1.json").read_text(encoding="utf-8"))
    v2 = json.loads((ESQUEMAS / "historico" / "respuesta_verificador_v3.json").read_text(encoding="utf-8"))  # I1.4-I1.6
    assert v1["$id"] == "urn:preventa:esquemas:respuesta_verificador:1" and v1["description"].startswith("HISTÓRICO")
    assert "precios_azure" not in v1["properties"]["herramientas_usadas"]["properties"]
    assert "precios_azure" in v2["properties"]["herramientas_usadas"]["required"]
    a = {"agente": "preventa-verificador", "consolidado_id": "CNS-OF-KELVARA-001-A-R1",
         "entrada_recibida_inicio": "CONSOLIDADO-PREVENTA/1 consolidado_id", "resumen": {"ok": 1, "discrepa": 0, "no_verificable": 0},
         "elementos": [{"id": "S-01", "tipo": "texto", "veredicto": "OK", "detalle": "Revisado.", "valor_correcto": None,
                        "fuente_url": None}],
         "herramientas_usadas": {"microsoft_docs_search": 1, "microsoft_docs_fetch": 1}}
    assert validar(a, v1, v1) == [] and validar(a, v2, v2) != []
