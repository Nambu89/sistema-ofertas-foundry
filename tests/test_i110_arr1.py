"""I1.10 · arreglos de la ronda 1 sobre los hallazgos de la verificación de I1.9 (pruebas/I19/ARREGLOS.md).

- PR19-1: el eco no literal del brief es un intento T2 con su motivo (ya no bloquea en el mismo turno; lo prueba
  test_i1_estado_analisis) y la cabecera del brief ya no lleva las dos huellas hexadecimales que el experto copiaba mal.
  Un brief guardado con la cabecera anterior se respeta y la puerta comprueba las dos formas.
- VA19-1: «Incluido» lleva todo el alcance funcional y los sistemas del cliente agrupados por cita, con las licencias
  dichas como uso; la puerta exige cada entrada de alcance_funcional en la diapositiva 5.
- VC19-1: la regla de niveles en las dos direcciones (nivel_insuficiente, instancias_insuficientes e
  instancias_no_cuadran), con la réplica de la puerta igual en cada caso (i19_p_datos.reglas_i19).
Sin red."""
from __future__ import annotations

import copy
import json
import pathlib
import types

import pytest

from tests import i18_p_datos as P
from tests import i19_p_datos as D
from tests.test_i1_estado_comun import TRANSCRIPCION, Mundo
from nucleo import brief as brief_mod, errores, experto, hashes, textos_cliente as tc

RAIZ = pathlib.Path(__file__).resolve().parents[1]
HOSTELIA_I19 = RAIZ / "pruebas" / "I19" / "REAL" / "B" / "hostelia_1" / "lista_A" / "estado.json"


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


# ───────────────────────────── PR19-1 ─────────────────────────────

def _cabecera_anterior(b: dict) -> str:
    """El texto de `b` con la cabecera de antes de I1.10 (con catalogo_sha256 y sha256_cuerpo)."""
    cab, _, cuerpo = b["texto"].partition("\n---\n")
    lineas = cab.split("\n")
    i = next(k for k, ln in enumerate(lineas) if ln.startswith("perfiles_permitidos: "))
    lineas = lineas[:i] + [f"catalogo_sha256: {b['catalogo_sha256']}", lineas[i],
                           f"sha256_cuerpo: {hashes.sha256_texto(cuerpo)}"]
    return "\n".join(lineas) + "\n---\n" + cuerpo


def test_pr19_1_la_cabecera_no_lleva_huellas_y_la_entrada_si(m):
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    b = m.estado()["carga"]["briefs"][0]
    cab, sep, cuerpo = b["texto"].partition("\n---\n")
    assert sep and [ln.split(":")[0] for ln in cab.split("\n")] == [
        "BRIEF-PREVENTA/1", "brief_id", "experto", "ronda", "perfiles_permitidos"]
    assert b["sha256_cuerpo"] == hashes.sha256_texto(cuerpo) and len(b["catalogo_sha256"]) == 64


def test_pr19_1_un_brief_guardado_con_la_cabecera_anterior_se_respeta(m):
    m.hasta_analisis()
    m.run("enrutar")
    est = m.estado()
    b = est["carga"]["briefs"][0]
    b["texto"] = _cabecera_anterior(b)
    b["sha256"] = hashes.sha256_texto(b["texto"])
    nuevo = brief_mod.generar(est, b["perfiles_permitidos"], b["catalogo_sha256"])
    assert nuevo.texto == b["texto"] and len(est["carga"]["briefs"]) == 1
    with pytest.raises(errores.IntegridadRota, match="otro texto"):
        brief_mod.generar(copy.deepcopy(est), b["perfiles_permitidos"], "0" * 64)


def test_pr19_1_con_la_cabecera_nueva_otro_catalogo_sigue_siendo_integridad_rota(m):
    m.hasta_analisis()
    m.run("enrutar")
    est = m.estado()
    b = est["carga"]["briefs"][0]
    with pytest.raises(errores.IntegridadRota, match="otro catálogo"):
        brief_mod.generar(est, b["perfiles_permitidos"], "1" * 64)


def _c_brief(estado):
    import verificar_paquete as vp
    return vp.c_brief(types.SimpleNamespace(estado=estado, carga=estado["carga"], transcripcion=TRANSCRIPCION))


def _fallas(c) -> list[str]:
    return [x for x in c.detalles if not x.startswith("aviso: ")]


def test_pr19_1_la_puerta_comprueba_la_huella_del_cuerpo_en_las_dos_formas(m):
    m.hasta_analisis()
    m.run("enrutar")
    est = m.estado()
    assert not any("sha256_cuerpo" in f for f in _fallas(_c_brief(est)))
    roto = copy.deepcopy(est)
    roto["carga"]["briefs"][0]["sha256_cuerpo"] = "0" * 64        # forma nueva: la huella de la entrada no cuadra
    assert any("sha256_cuerpo" in f for f in _fallas(_c_brief(roto)))
    viejo = copy.deepcopy(est)
    b = viejo["carga"]["briefs"][0]
    b["texto"] = _cabecera_anterior(b)
    assert not any("sha256_cuerpo" in f for f in _fallas(_c_brief(viejo)))
    b["texto"] = b["texto"].replace(f"sha256_cuerpo: {b['sha256_cuerpo']}", "sha256_cuerpo: " + "0" * 64)
    assert any("sha256_cuerpo" in f for f in _fallas(_c_brief(viejo)))


# ───────────────────────────── VA19-1 ─────────────────────────────

def _hostelia_i19():
    est = json.loads(HOSTELIA_I19.read_text(encoding="utf-8"))
    cat = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    tarifa = json.loads((RAIZ / "tests" / "insumos" / "rate-card.sintetica.json").read_text(encoding="utf-8"))
    return est, cat, tarifa


def test_va19_1_incluido_lleva_la_funcion_principal_y_los_sistemas_agrupados():
    est, cat, tarifa = _hostelia_i19()
    textos = tc.componer(est, cat, tarifa)
    alcance = {f["texto"]: f["hechos"] for f in textos["alcance"]}
    principal = "Responder sobre las políticas de RR. HH. usando documentos de SharePoint."
    assert principal in alcance and "R-objetivo" in alcance[principal]
    assert "Uso de Microsoft Teams y SharePoint Online, incluidos en las licencias de Microsoft 365 E3 del cliente." \
        in alcance
    # el valor citado no lleva artículo («API REST de RR. HH.»): nombre_en_frase no lo inventa
    assert ("Integración con API REST de RR. HH. que ya tiene el cliente (y sus sistemas App Service propio y Azure "
            "API Management).") in alcance
    assert not any(t.startswith(("Integración con Microsoft 365", "Integración con App Service", "Integración con "
                                 "Microsoft Teams")) for t in alcance)
    assert not any("repite el objetivo" in x["motivo"] for x in textos["excluidas"])
    # los hechos citan los componentes de cada grupo (8 como máximo)
    assert all(1 <= len(h) <= 8 for h in alcance.values())


def test_va19_1_la_puerta_exige_cada_alcance_funcional_en_incluido():
    import verificar_paquete as vp
    est, _, _ = _hostelia_i19()
    valores = [e["valor"] for e in est["carga"]["requisitos"]["campos"]["alcance_funcional"]["entradas"]]

    def puerta(textos_d5, excluidas=()):
        c = vp.Comprobacion("cliente", "prueba")
        diapos = [types.SimpleNamespace(textos=[]) for _ in range(4)] + [types.SimpleNamespace(textos=textos_d5)]
        vp._alcance_incluido(types.SimpleNamespace(carga=est["carga"]), c, {"excluidas": list(excluidas)},
                             types.SimpleNamespace(diapositivas=diapos))
        return _fallas(c)

    FUERA = ["Fuera de alcance", "Integración con sistemas de nóminas."]
    assert puerta(["Alcance", "Incluido"] + valores + FUERA) == []
    fallas = puerta(["Incluido"] + valores[1:] + FUERA)
    assert len(fallas) == 1 and "VA19-1" in fallas[0] and "políticas" in fallas[0]
    repetida = {"origen": "requisito alcance_funcional", "texto": valores[0],
                "motivo": "repite el objetivo, que ya figura en la necesidad"}
    assert len(puerta(["Incluido"] + valores[1:] + FUERA, [repetida])) == 1  # el motivo de I1.9 ya no vale
    por_forma = dict(repetida, motivo="longitud fuera de 5-400 caracteres")
    assert puerta(["Incluido"] + valores[1:] + FUERA, [por_forma]) == []
    # ARR1 (Revisión): en la columna «Fuera de alcance» no cuenta como incluido
    assert len(puerta(["Incluido"] + valores[1:] + FUERA + [valores[0]])) == 1
    # sin los dos títulos, o al revés, falla cerrado
    for malos in (valores, ["Incluido"] + valores, FUERA + ["Incluido"] + valores,
                  ["Incluido", valores[0], "Incluido"] + valores[1:] + FUERA):  # Revisión 2: «Incluido» repetido
        f = puerta(malos)
        assert len(f) == 1 and "columnas" in f[0]


# ───────────────────────────── VC19-1 ─────────────────────────────

def _caso(precio_basic=None, instancias=None, jn=None, volumetria=(), alcance=(), asumido=False):
    br, req, r, cat = P.base()
    for v in volumetria:
        req["campos"]["volumetria"]["entradas"].append({"valor": v, "cita": "frase literal de la transcripción",
                                                        "fuente": "F1", "origen": "ASUMIDO" if asumido else "CITADO"})
    for v in alcance:
        req["campos"]["alcance_funcional"]["entradas"].append({"valor": v, "cita": "frase literal de la transcripción",
                                                               "fuente": "F1", "origen": "CITADO"})
    p = next(x for x in r["precios"] if x["id"] == "P-03")
    p["plantilla_id"] = precio_basic or "basic"
    p["instancias"] = instancias
    D.comp_de(r, "C-02")["justificacion_nivel"] = jn
    return D.reglas_i19(r, br, req, cat)["volumen_nivel"]


JN_PART = {"nivel": "Basic", "razon": "particiones_almacenamiento", "cita": "Unos 30 GB de documentos."}


@pytest.mark.parametrize("kw, esperado", [
    ({}, []),                                                                               # control: 1,6 GB no cita GB
    ({"volumetria": ["Unos 200 GB de documentos."]}, [("C-02", "nivel_insuficiente")]),     # N11 (sin pedir particiones)
    ({"volumetria": ["Unos 200 GB de documentos."], "asumido": True}, []),                  # lo ASUMIDO no obliga
    ({"volumetria": ["Unos 30 GB de documentos."]}, [("C-02", "instancias_insuficientes")]),  # B3: Basic × 1
    ({"volumetria": ["Unos 30 GB de documentos."], "instancias": 2, "jn": JN_PART}, []),    # la banda tiene salida
    ({"volumetria": ["Unos 30 GB de documentos."], "instancias": 3, "jn": JN_PART},
     [("C-02", "instancias_no_cuadran")]),
    ({"volumetria": ["Unos 30 GB de documentos."], "instancias": 2},
     [("C-02", "instancias_sin_justificar")]),
    ({"volumetria": ["Unos 30 GB de documentos."], "alcance": ["Necesitamos alta disponibilidad."], "instancias": 2,
      "jn": {"nivel": "Basic", "razon": "sla_replicas", "cita": "Necesitamos alta disponibilidad."}}, []),
    ({"volumetria": ["Unos 12 GB de documentos."], "instancias": 2, "jn": dict(JN_PART, cita="Unos 12 GB de documentos.")},
     [("C-02", "razon_no_cumplida")]),
    ({"volumetria": ["Unos 200 GB de documentos."], "precio_basic": "s1",
      "jn": {"nivel": "S1", "razon": "almacenamiento", "cita": "Unos 200 GB de documentos."}},
     [("C-02", "instancias_insuficientes")]),                                               # 160 GB por partición en S1
    ({"volumetria": ["Unos 200 GB de documentos."], "precio_basic": "s1", "instancias": 2,
      "jn": {"nivel": "S1", "razon": "almacenamiento", "cita": "Unos 200 GB de documentos."}}, []),
    ({"volumetria": ["Unos 100 GB de documentos."], "precio_basic": "s1",
      "jn": {"nivel": "S1", "razon": "almacenamiento", "cita": "Unos 100 GB de documentos."}}, []),
])
def test_vc19_1_la_regla_de_niveles_obliga_tambien_a_subir(kw, esperado):
    assert _caso(**kw) == esperado


def test_vc19_1_por_instancia_mal_declarado_falla_cerrado():
    base = {"id": "x", "tipo": "umbral", "campo": "volumetria", "unidad": ["gigabytes"], "limite": 15,
            "fuente": "https://learn.microsoft.com/azure/search/search-limits-quotas-capacity"}
    assert experto.razones_validas([dict(base, por_instancia=15)])[0]["por_instancia"] == 15
    for malo in (0, -1, True, "15"):
        assert experto.razones_validas([dict(base, por_instancia=malo)]) is False
    caract = {"id": "y", "tipo": "caracteristica", "palabras_clave": ["SLA"], "por_instancia": 2,
              "fuente": base["fuente"]}
    assert experto.razones_validas([caract]) is False


def test_arr1_un_solo_nivel_insuficiente_con_el_nivel_mas_alto_que_exige_la_cita():
    """ARR1 (I1.10): SQL Basic con 1.200 sesiones citadas superaba S0, S1 y GP a la vez y salían tres reglas; ahora
    una, que pide GP_Gen5_2 (el único que basta), y la réplica de la puerta da la misma lista."""
    import verificar_paquete as vp
    from tests import test_i19_e_nucleo as N
    resp = {"arquitectura_id": "foundry-chat-basica", "referencias": [], "componentes": [N._comp("az-sql-database")],
            "precios": [N._p(1, "basic", 1)]}
    c, _ = experto.completar(resp, N.CAT, N.INST, N.REQ, N.BRIEF)
    errs = [e for e in experto.errores_volumen_nivel(c, N.BRIEF, N.REQ, N.CAT) if e["regla"] == "nivel_insuficiente"]
    assert len(errs) == 1 and "«GP_Gen5_2»" in errs[0]["detalle"] and "«Basic»" in errs[0]["detalle"]
    gp = {"arquitectura_id": "foundry-chat-basica", "referencias": [],
          "componentes": [N._comp("az-sql-database", "GP_Gen5_2", "sesiones", cita=N.SESIONES)],
          "precios": [N._p(1, "gp-2vcore", 1), N._p(2, "gp-almacenamiento", 1)]}
    c2, errs2 = experto.completar(gp, N.CAT, N.INST, N.REQ, N.BRIEF)
    assert [e for e in errs2 + experto.errores_volumen_nivel(c2, N.BRIEF, N.REQ, N.CAT)
            if e["regla"] in ("nivel_insuficiente", "razon_no_cumplida", "nivel_sin_justificar")] == []
    assert vp.insuficiencia_r.__doc__ and "nivel_insuficiente" not in str(vp.insuficiencia_r([], [], {}, {}, ""))


@pytest.mark.parametrize("malo", ["15", 0, -15, True, float("nan"), float("inf")])
def test_arr1_el_validador_del_catalogo_ve_un_por_instancia_mal_declarado(malo):
    """ARR1 (Revisión): problemas_i19 rechaza lo mismo que experto.razones_validas, con un único problema."""
    from catalogo import plantillas_precio as pp
    cat = copy.deepcopy(_CAT_DERIVADO())
    assert pp.problemas_i19(copy.deepcopy(cat)) == []
    fila = next(e for e in cat["componentes"] if e["id"] == "az-ai-search")
    razon = next(r for r in fila["niveles"][0]["razones_subida"] if r.get("por_instancia"))
    razon["por_instancia"] = malo
    problemas = pp.problemas_i19(cat)
    assert len(problemas) == 1 and "por_instancia" in problemas[0], problemas
    assert experto.razones_validas(fila["niveles"][0]["razones_subida"]) is False


def test_arr1_por_instancia_en_una_caracteristica_tambien_lo_ve():
    from catalogo import plantillas_precio as pp
    cat = copy.deepcopy(_CAT_DERIVADO())
    fila = next(e for e in cat["componentes"] if e["id"] == "az-ai-search")
    next(r for r in fila["niveles"][0]["razones_subida"] if r["tipo"] == "caracteristica")["por_instancia"] = 2
    problemas = pp.problemas_i19(cat)
    assert len(problemas) == 1 and "por_instancia" in problemas[0], problemas


def _CAT_DERIVADO():
    """El catálogo de entrada de catalogo.derivar (el que valida problemas_i19, como en test_i19_e_roturas)."""
    from catalogo import derivar
    return derivar.cargar()


JN_MIL = {"nivel": "S1", "razon": "almacenamiento", "cita": "Unos 1 200 GB de documentos."}


@pytest.mark.parametrize("sep", [" ", "\u00a0", "\u202f"])
@pytest.mark.parametrize("instancias, esperado", [(2, [("C-02", "instancias_insuficientes")]), (8, [])])
def test_arr1_millares_con_espacio_se_leen_enteros(sep, instancias, esperado):
    """ARR1 (Revisión): «1 200 GB» son 1.200 GB (8 particiones de S1 de 160 GB), no 200 GB (2); igual con el espacio
    duro y el estrecho. La réplica de la puerta da lo mismo (reglas_i19 compara las dos)."""
    cita = f"Unos 1{sep}200 GB de documentos."
    assert experto.numeros_con_unidad(cita, ["gigabytes"], ["GB"]) == [1200]
    import verificar_paquete as vp
    assert vp.numeros_con_unidad_r(cita, ["gigabytes"], ["GB"]) == [1200]
    if sep == " ":
        assert _caso(volumetria=[cita], precio_basic="s1", instancias=instancias, jn=JN_MIL) == esperado


def test_arr1_millares_con_espacio_no_confunde_cantidades_separadas():
    assert experto.numeros_con_unidad("Entre 2 y 300 GB de documentos.", ["gigabytes"], ["GB"]) == [300]
    assert experto.numeros_con_unidad("Unos 1 2000 GB.", ["gigabytes"], ["GB"]) == [2000]
    assert experto.numeros_con_unidad("Unos 12 500,5 GB.", ["gigabytes"], ["GB"]) == [__import__("decimal").Decimal("12500.5")]


def test_arr1_millares_con_espacio_y_decimal_con_punto():
    """Revisión 2: «1 200.5 GB» no se pierde (antes del arreglo, «1.200.5» no era un número)."""
    import decimal
    import verificar_paquete as vp
    for f in (experto.numeros_con_unidad, vp.numeros_con_unidad_r):
        assert f("Unos 1 200.5 GB.", ["gigabytes"], ["GB"]) == [decimal.Decimal("1200.5")]
        assert f("Unos 1 200 GB. 5 GB más.", ["gigabytes"], ["GB"]) == [1200, 5]


HOSTELIA_ARR1 = RAIZ / "pruebas" / "I19" / "ARREGLOS" / "REAL" / "B" / "hostelia_1" / "lista_A" / "estado.json"


def test_arr1_un_canal_que_es_el_nombre_del_sistema_no_se_declara_excluido():
    """Prueba real de los arreglos (18-10, B v18): los canales extraídos fueron «Microsoft Teams», «SharePoint Online» y
    «API REST de RR. HH.», a secas; se declaraban excluidos y salían literales en la frase de los sistemas del cliente,
    y la puerta daba FALLA en coherencia («frase excluida publicada»). Ahora no se declaran: ya están publicados."""
    est = json.loads(HOSTELIA_ARR1.read_text(encoding="utf-8"))
    cat = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    tarifa = json.loads((RAIZ / "tests" / "insumos" / "rate-card.sintetica.json").read_text(encoding="utf-8"))
    textos = tc.componer(est, cat, tarifa)
    assert not [x for x in textos["excluidas"] if x["origen"] == "requisito canales_integraciones"]
    publicado = " ".join(f["texto"] for f in textos["alcance"])
    for v in ("Microsoft Teams", "SharePoint Online", "API REST de RR. HH."):
        assert v in publicado


def test_arr1_un_canal_con_mas_texto_sigue_declarado_excluido():
    """Con el estado de I1.9 («Microsoft Teams como canal de uso para los empleados.») la frase no se publica literal:
    sigue en excluidas, con su motivo, para la nota."""
    est, cat, tarifa = _hostelia_i19()
    textos = tc.componer(est, cat, tarifa)
    canales = [x for x in textos["excluidas"] if x["origen"] == "requisito canales_integraciones"]
    assert len(canales) == 3 and all("ya tiene el cliente" in x["motivo"] for x in canales)
