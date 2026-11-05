"""I1.9 · papel R · la puerta local: VA18-1 (exclusividad de importes en todo el PPTX y datos internos del alta), VPROT-1
(texto alternativo, diseños y patrones), VA18-7 (entregable APROBADA) y VC18-3 (DISCREPA de región contra la
disponibilidad del catálogo, núcleo y réplica). Cada caso adverso lleva su resultado esperado y su control sin mutar.

Paquetes reales de la prueba de I1.8 (pruebas/I18/REAL/B): Hostelia lista A (el presupuesto asumido en la diapositiva 6) y
Brezalia final (APROBADA del 2026-10-14). Si faltan, esas pruebas se saltan; las unitarias no."""
from __future__ import annotations

import copy
import datetime as dt
import pathlib
import re
import sys
import zipfile

import pytest

import verificar_paquete as vp

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
from nucleo import verificacion as V  # noqa: E402

REAL = RAIZ / "pruebas" / "I18" / "REAL" / "B"
HOSTELIA = REAL / "hostelia_1" / "lista_A" / "OF-HOSTELIA-001-A-Paquete.zip"
BREZALIA_A = REAL / "sesion_2" / "lista_A" / "OF-BREZALIA-001-A-Paquete.zip"
BREZALIA_FINAL = REAL / "sesion_2" / "final" / "OF-BREZALIA-001-B-Paquete.zip"
real = pytest.mark.skipif(not (HOSTELIA.is_file() and BREZALIA_A.is_file() and BREZALIA_FINAL.is_file()),
                          reason="faltan los paquetes reales de I1.8")


def _ctx(zip_: pathlib.Path, tmp: pathlib.Path) -> vp.Contexto:
    paquete = vp.abrir_paquete(zip_, tmp / "p")
    ctx = vp.Contexto(paquete, tmp, {}, tmp, tmp, tmp, RAIZ / "catalogo" / "catalogo_referencias_azure.json", None,
                      True, dt.date(2026, 10, 15), tmp)
    ctx.manifiesto, ctx.estado = paquete.json_de("manifiesto_paquete.json"), paquete.json_de("estado.json")
    ctx.codigo = ctx.manifiesto["codigo"]
    return ctx


def _pptx_mutado(ctx: vp.Contexto, tmp: pathlib.Path, mutar) -> vp.Pptx:
    """PPTX del paquete con una parte cambiada por `mutar(nombre, texto) -> texto` (a nivel de XML)."""
    origen = ctx.fichero(ctx.sufijo_pptx())
    destino = tmp / "mutado.pptx"
    with zipfile.ZipFile(origen) as zi, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            datos = zi.read(n)
            if n.endswith(".xml"):
                datos = mutar(n, datos.decode("utf-8")).encode("utf-8")
            zo.writestr(n, datos)
    return vp.leer_pptx(destino)


def _detalles(c: vp.Comprobacion, texto: str) -> list[str]:
    return [d for d in c.detalles if texto in d]


# ───────────────────────────── VA18-1: cifras junto a la moneda ─────────────────────────────
@pytest.mark.parametrize("texto, cifras", [
    ("entre 25.000 y 60.000 euros", ["25.000", "60.000"]),
    ("de 25.000 a 60.000 €", ["25.000", "60.000"]),
    ("25.000-60.000 EUR", ["25.000", "60.000"]),
    ("EUR 25.000 y 60.000", ["25.000", "60.000"]),
    ("25.000, 30.000 o 60.000 euros", ["25.000", "30.000", "60.000"]),
    ("25 mil euros", ["25 mil"]),
    ("60k€", ["60 k"]),
    ("unos 3 millones de euros", ["3 millones de"]),
    ("Precio cerrado\n25.483,75 €", ["25.483,75"]),
])
def test_cifras_con_moneda_ve_cada_cifra_de_la_serie(texto, cifras):
    assert [x for x, _ in vp.cifras_con_moneda(texto)] == cifras


@pytest.mark.parametrize("texto", [
    "1.200 empleados de España y Portugal", "Coste mensual estimado (EUR)\nAzure App Service", "3 eurovisiones",
    "Hito 2 - Entregable principal\n25 %", "6.000 consultas al mes", "0,002 GB por documento",
])
def test_cifras_con_moneda_sin_falsos_positivos(texto):
    assert vp.cifras_con_moneda(texto) == []


def test_con_multiplicador_no_hay_lectura_y_nunca_casa():
    assert vp.cifras_con_moneda("25 mil euros") == [("25 mil", set())]


def test_por_que_paso_la_serie_antes():
    """La regla anterior solo veía la cifra pegada a la moneda: la primera de la serie se escapaba."""
    viejas = [m.group(1) for m in vp._MONEDA_DESPUES.finditer("entre 25.000 y 60.000 euros")]
    assert viejas == ["60.000"] and "25.000" in [x for x, _ in vp.cifras_monetarias("entre 25.000 y 60.000 euros")]


# ───────────────────────────── VA18-1: exclusividad en todo el PPTX ─────────────────────────────
def _exclusividad(ctx: vp.Contexto) -> vp.Comprobacion:
    c = vp.Comprobacion("coherencia", "prueba")
    vp._exclusividad_importes(ctx, c, {d.numero: d for d in ctx.pptx().diapositivas}, ctx.xlsx())
    return c


@real
def test_hostelia_real_falla_por_el_presupuesto_de_la_diapositiva_6(tmp_path):
    c = _exclusividad(_ctx(HOSTELIA, tmp_path))
    assert c.estado == vp.FALLA
    assert _detalles(c, "diapositiva 6: importe «25.000»") and _detalles(c, "diapositiva 6: importe «60.000»")
    assert len(c.detalles) == 2, c.detalles      # las diapositivas 7, 8 y 10 no dan falsos rojos


@real
@pytest.mark.parametrize("zip_", [BREZALIA_A, BREZALIA_FINAL])
def test_control_brezalia_sin_importes_fuera_de_lugar(tmp_path, zip_):
    assert _exclusividad(_ctx(zip_, tmp_path)).detalles == []


@real
@pytest.mark.parametrize("donde, mutar, esperado", [
    ("diapositiva 3", lambda n, t: t.replace("<a:t>", "<a:t>Coste de 1.500 € al mes. ", 1)
     if n == "ppt/slides/slide3.xml" else t, "diapositiva 3: importe «1.500»"),
    ("diapositiva 9", lambda n, t: t.replace("<a:t>", "<a:t>Hasta 40 mil euros. ", 1)
     if n == "ppt/slides/slide9.xml" else t, "diapositiva 9: importe «40 mil»"),
    ("diapositiva 8", lambda n, t: t.replace("<a:t>Total mensual", "<a:t>Extra 99,99 € · Total mensual", 1)
     if n == "ppt/slides/slide8.xml" else t, "diapositiva 8: importe «99,99»"),
    ("texto alternativo", lambda n, t: re.sub(r"<p:cNvPr ", '<p:cNvPr descr="Presupuesto de 30.000 EUR" ', t, count=1)
     if n == "ppt/slides/slide4.xml" else t, "texto alternativo (ppt/slides/slide4.xml): importe «30.000»"),
    ("diseño", lambda n, t: t.replace("<a:t>", "<a:t>Desde 5.000 € ", 1)
     if n == "ppt/slideLayouts/slideLayout1.xml" else t, "diseño o patrón (ppt/slideLayouts/slideLayout1.xml): importe «5.000»"),
])
def test_rotura_importe_fuera_de_lugar_falla(tmp_path, donde, mutar, esperado):
    ctx = _ctx(BREZALIA_A, tmp_path)
    ctx._cache["pptx"] = _pptx_mutado(ctx, tmp_path, mutar)
    c = _exclusividad(ctx)
    assert c.estado == vp.FALLA and _detalles(c, esperado), (donde, c.detalles)


# ───────────────────────────── VA18-1: datos internos del alta ─────────────────────────────
def _estado(textos_cliente=None, valor="Entre 25.000 y 60.000 euros", alta=None):
    return {"carga": {"alta": alta or {"cliente": "X"},
                      "requisitos": {"campos": {"presupuesto_orientativo": {"estado": "ASUMIDO", "entradas": [
                          {"valor": valor, "cita": None, "fuente": None, "origen": "ASUMIDO"}]}}},
                      "textos_cliente": textos_cliente or {}}}


def test_datos_internos_control_limpio():
    tc = {"supuestos": [{"id": "TX-SUP-01", "texto": "Red pública.", "hechos": ["R-red_privada"]}],
          "excluidas": [{"id": "TX-SUP-03", "texto": "x", "hechos": ["R-presupuesto_orientativo"]}]}
    assert vp.datos_internos_en_cliente(_estado(tc), [("diapositiva 6", "Red pública. Confianza baja")]) == []


@pytest.mark.parametrize("textos, tc, esperado", [
    ([("diapositiva 6", "confirmar: entre 25.000 y 60.000 euros.")], None, "presupuesto_orientativo (valor)"),
    ([("diapositiva 9", "Supuesto sin confirmar: el presupuesto orientativo")], None, "rótulo interno"),
    ([("texto alternativo (ppt/slides/slide4.xml)", "ENTRE 25.000 Y 60.000 EUROS")], None, "texto alternativo"),
    ([], {"supuestos": [{"id": "TX-SUP-03", "texto": "Parafraseado", "hechos": ["R-presupuesto_orientativo"]}]},
     "TX-SUP-03"),
    ([], {"riesgos": [{"id": "TX-RSG-01", "texto": "otra", "hechos": ["RG-01", "R-presupuesto_orientativo"]}]},
     "TX-RSG-01"),
])
def test_datos_internos_que_fallan(textos, tc, esperado):
    halla = vp.datos_internos_en_cliente(_estado(tc), textos)
    assert any(esperado in h for h in halla), halla


def test_nota_interna_del_alta_tambien_cuenta():
    est = _estado(alta={"cliente": "X", "notas_internas": "Cliente sensible al precio, negociar"})
    halla = vp.datos_internos_en_cliente(est, [("diapositiva 3", "Nota: cliente sensible al precio, negociar.")])
    assert any("alta.notas_internas" in h for h in halla), halla


def test_valor_corto_no_se_busca():
    assert vp.datos_internos_en_cliente(_estado(valor="No"), [("diapositiva 3", "No aplica")]) == []


@real
def test_hostelia_real_falla_por_dato_interno_y_brezalia_no(tmp_path):
    c = vp.Comprobacion("cliente_les_g_053", "prueba")
    vp._datos_internos(_ctx(HOSTELIA, tmp_path / "h"), c)
    assert c.estado == vp.FALLA and _detalles(c, "TX-SUP-03") and _detalles(c, "presupuesto_orientativo (valor)")
    c = vp.Comprobacion("cliente_les_g_053", "prueba")
    vp._datos_internos(_ctx(BREZALIA_FINAL, tmp_path / "b"), c)
    assert c.estado == vp.OK and _detalles(c, "datos internos: ni el presupuesto")


# ───────────────────────────── VPROT-1: revisión interna fuera de las diapositivas ─────────────────────────────
@real
@pytest.mark.parametrize("mutar, esperado", [
    (lambda n, t: re.sub(r"<p:cNvPr ", '<p:cNvPr descr="DEVUELTA por Responsable de preventa" ', t, count=1)
     if n == "ppt/slides/slide4.xml" else t, "texto alternativo (ppt/slides/slide4.xml)"),
    (lambda n, t: re.sub(r"<p:cNvPr ", '<p:cNvPr title="az-app-service" ', t, count=1)
     if n == "ppt/slides/slide3.xml" else t, "texto alternativo (ppt/slides/slide3.xml)"),
    (lambda n, t: t.replace("<a:t>", "<a:t>Cambios pedidos en la revisión anterior ", 1)
     if n == "ppt/slideLayouts/slideLayout1.xml" else t, "diseño o patrón (ppt/slideLayouts/slideLayout1.xml)"),
    (lambda n, t: t.replace("<a:t>", "<a:t>nota del revisor ", 1)
     if n == "ppt/slideMasters/slideMaster1.xml" else t, "diseño o patrón (ppt/slideMasters/slideMaster1.xml)"),
])
def test_vprot1_revision_interna_en_texto_alternativo_y_disenos(tmp_path, mutar, esperado):
    ctx = _ctx(BREZALIA_FINAL, tmp_path)
    assert vp.revision_interna_en_pptx_replica(ctx.pptx().partes, ctx.estado, ctx.catalogo_obj or {}) == []  # control
    p = _pptx_mutado(ctx, tmp_path, mutar)
    halla = vp.revision_interna_en_pptx_replica(p.partes, ctx.estado, {"componentes": [{"id": "az-app-service"}]})
    assert any(h.startswith(esperado) for h in halla), halla


# ───────────────────────────── VA18-7: entregable en APROBADA ─────────────────────────────
@pytest.mark.parametrize("estado, fecha, sufijo, titulo", [
    ("APROBADA", dt.date(2026, 10, 15), "Propuesta.pptx", "OF-X-001-A · Propuesta comercial"),
    ("APROBADA", None, "Propuesta.pptx", "OF-X-001-A · Propuesta comercial"),        # sin fecha: regla nueva
    ("APROBADA", dt.date(2026, 10, 14), "Revision.pptx", "OF-X-001-A · Propuesta para revisión"),
    ("LISTA_PARA_REVISION", dt.date(2026, 10, 20), "Revision.pptx", "OF-X-001-A · Propuesta para revisión"),
    ("EN_APROBACION_AREA", None, "Revision.pptx", "OF-X-001-A · Propuesta para revisión"),
])
def test_va18_7_nombre_y_titulo(estado, fecha, sufijo, titulo):
    assert vp.sufijo_pptx(estado, fecha) == sufijo and vp.titulo_pptx("OF-X-001-A", estado, fecha) == titulo
    assert vp.nombres_paquete("OF-X-001-A", estado, fecha)[3] == f"OF-X-001-A-{sufijo}"


def test_va18_7_nucleo_nombra_el_pptx_igual():
    from nucleo import paquete
    assert paquete.nombres_zip("OF-X-001-A", "APROBADA")[3] == "OF-X-001-A-Propuesta.pptx"
    assert paquete.nombres_zip("OF-X-001-A", "EN_REVISION_PREVENTA")[3] == "OF-X-001-A-Revision.pptx"
    assert paquete.nombres_zip("OF-X-001-A") == vp.nombres_paquete("OF-X-001-A")


@real
def test_va18_7_aprobada_anterior_se_admite_con_nota(tmp_path):
    c = vp.c_estructura(_ctx(BREZALIA_FINAL, tmp_path))
    assert not _detalles(c, "falta en el paquete") and _detalles(c, "anterior a 2026-10-15"), c.detalles


@real
def test_va18_7_aprobada_nueva_con_revision_pptx_falla(tmp_path):
    ctx = _ctx(BREZALIA_FINAL, tmp_path)
    ctx.manifiesto["generado_ts"] = "2026-10-15T09:00:00+00:00"
    c = vp.c_estructura(ctx)
    assert c.estado == vp.FALLA and _detalles(c, "falta en el paquete: OF-BREZALIA-001-B-Propuesta.pptx")
    assert _detalles(c, "fichero no previsto en el paquete: OF-BREZALIA-001-B-Revision.pptx"), c.detalles


@real
def test_va18_7_titulo_de_una_aprobada_nueva_se_exige(tmp_path):
    ctx = _ctx(BREZALIA_FINAL, tmp_path)
    p = ctx.pptx()          # se lee con la fecha real (Revision.pptx); luego la fecha pasa a la de la regla nueva
    ctx.manifiesto["generado_ts"] = "2026-10-15T09:00:00+00:00"
    assert p.props.get("title") == "OF-BREZALIA-001-B · Propuesta para revisión"
    assert vp.titulo_pptx(ctx.codigo, ctx.estado.get("estado"), ctx.fecha_paquete()) != p.props.get("title")


# ───────────────────────────── VC18-3: DISCREPA de región contra el catálogo ─────────────────────────────
FUENTE = "https://learn.microsoft.com/azure/api-management/api-management-region-availability"
CATALOGO = {"componentes": [{
    "id": "az-api-management", "nombre_oficial": "Azure API Management",
    "niveles": [{"nivel": "Basic v2", "plantillas": ["basic-v2"]}, {"nivel": "Standard v2", "plantillas": ["standard-v2"]}],
    "nivel_por_defecto": {"nivel": "Basic v2"},
    "disponibilidad": {"Standard v2": {"regiones": ["swedencentral", "francecentral"], "alcance": "nivel",
                                       "fuente": FUENTE, "consultado": "2026-10-15"},
                       "Basic v2": {"regiones": ["francecentral"], "fuente": FUENTE}}}, {
    "id": "az-foundry", "plantillas_precio": [{"id": "luna-in", "modelo": "gpt-6-luna"}],
    "disponibilidad": {"gpt-6-luna": {"regiones": ["swedencentral"], "fuente": FUENTE}}}]}
LINEA = "C-08 | Azure API Management | sku: Standard v2 | region: {r} | nivel: Standard v2 | referencia: https://x"
COMP = {"id": "C-08", "catalogo_id": "az-api-management", "sku": "Standard v2",
        "justificacion_nivel": {"nivel": "Standard v2"}}


def _ambos(linea, comp, precios, catalogo):
    nuc = V.region_disponible_segun_catalogo(linea, comp, precios, catalogo) is not None
    rep = vp.region_disponible_replica(linea, comp, precios, catalogo)
    assert nuc == rep, (nuc, rep)        # núcleo y réplica, mismo veredicto
    return nuc


def test_vc18_3_control_region_publicada_pasa_a_observacion():
    assert _ambos(LINEA.format(r="swedencentral"), COMP, [], CATALOGO)
    assert _ambos(LINEA.format(r="Sweden-Central"), COMP, [], CATALOGO)


def _sin_fuente():
    c = copy.deepcopy(CATALOGO)
    del c["componentes"][0]["disponibilidad"]["Standard v2"]["fuente"]
    return c


def _fuente_ajena():
    c = copy.deepcopy(CATALOGO)
    c["componentes"][0]["disponibilidad"]["Standard v2"]["fuente"] = "https://example.com/regiones"
    return c


@pytest.mark.parametrize("linea, comp, precios, catalogo", [
    (LINEA.format(r="westeurope"), COMP, [], CATALOGO),                                     # región no publicada
    (LINEA.format(r="swedencentral"), COMP, [], _sin_fuente()),                             # sin fuente
    (LINEA.format(r="swedencentral"), COMP, [], _fuente_ajena()),                           # fuente fuera de Learn
    (LINEA.format(r="swedencentral"), COMP, [{"componente_id": "C-08", "plantilla_id": "basic-v2"}], CATALOGO),  # usa Basic
    (LINEA.format(r="swedencentral"), {**COMP, "catalogo_id": "az-otro"}, [], CATALOGO),    # fila sin disponibilidad
    (LINEA.format(r="swedencentral"), COMP, [], None),                                      # sin catálogo
    ("P-01 | algo | region: swedencentral", COMP, [], CATALOGO),                            # no es línea de componente
    (LINEA.format(r="swedencentral"), {**COMP, "sku": "Premium v2", "justificacion_nivel": {"nivel": "Premium v2"}},
     [], CATALOGO),                                                                         # nivel desconocido: por defecto
])
def test_vc18_3_casos_en_que_la_discrepa_se_queda(linea, comp, precios, catalogo):
    assert not _ambos(linea, comp, precios, catalogo)


def test_vc18_3_foundry_por_modelo():
    linea = "C-02 | Microsoft Foundry | sku: gpt-6-luna | region: swedencentral | referencia: https://x"
    comp = {"id": "C-02", "catalogo_id": "az-foundry", "sku": "gpt-6-luna"}
    assert _ambos(linea, comp, [{"componente_id": "C-02", "plantilla_id": "luna-in"}], CATALOGO)
    assert not _ambos(linea.replace("swedencentral", "northeurope"), comp, [], CATALOGO)


def _estado_verif(campo: str, region: str = "swedencentral") -> tuple[dict, dict]:
    linea = LINEA.format(r=region)
    estado = {"carga": {"respuestas_expertos": {"azure": {"respuesta": {
        "referencias": [], "precios": [], "componentes": [COMP]}, "brief_id": None}},
        "consolidado": {"texto": "cabecera\n" + linea}, "briefs": []}}
    resp = {"elementos": [{"id": "C-08", "tipo": "componente", "veredicto": "DISCREPA", "campo": campo,
                           "valor_correcto": "Basic v2", "fuente_url": FUENTE,
                           "detalle": "Sweden Central está temporalmente no disponible para Standard v2"}]}
    return estado, resp


def test_vc18_3_evaluar_con_catalogo_reclasifica_y_sin_catalogo_no():
    estado, resp = _estado_verif("region")
    con = V.evaluar(estado, resp, CATALOGO)
    assert con.verificada and [o["id"] for o in con.observaciones] == ["C-08"] and "VC18-3" in con.observaciones[0]["motivo"]
    sin = V.evaluar(estado, resp)
    assert not sin.verificada and [d["id"] for d in sin.discrepa] == ["C-08"]


@pytest.mark.parametrize("campo, region", [("sku", "swedencentral"), ("region", "westeurope"), (None, "swedencentral")])
def test_vc18_3_evaluar_otro_campo_u_otra_region_sigue_bloqueando(campo, region):
    estado, resp = _estado_verif(campo, region)
    assert not V.evaluar(estado, resp, CATALOGO).verificada


def test_vc18_3_discrepa_sin_fuente_tambien_pasa_si_contradice_el_catalogo():
    estado, resp = _estado_verif("region")
    resp["elementos"][0]["fuente_url"] = None
    assert V.evaluar(estado, resp, CATALOGO).verificada


@real
def test_va18_7_aprobada_anterior_conserva_el_titulo_de_antes(tmp_path):
    ctx = _ctx(BREZALIA_FINAL, tmp_path)
    assert ctx.pptx().props.get("title") == vp.titulo_pptx(ctx.codigo, "APROBADA", ctx.fecha_paquete())


@real
def test_va18_7_previo_con_aprobada_nueva_sin_propuesta_falla(tmp_path):
    ctx = _ctx(BREZALIA_FINAL, tmp_path)
    ctx.previo = BREZALIA_FINAL.parent.parent / "lista_B" / "OF-BREZALIA-001-B-Paquete.zip"
    assert not _detalles(vp.c_previo(ctx), "VA18-7")                       # control: las dos con la regla de antes
    ctx2 = _ctx(BREZALIA_FINAL, tmp_path / "n")
    ctx2.previo, ctx2.manifiesto["generado_ts"] = ctx.previo, "2026-10-15T09:00:00+00:00"
    c = vp.c_previo(ctx2)
    assert c.estado == vp.FALLA and _detalles(c, "no traen el PPTX que corresponde a su estado (VA18-7)"), c.detalles


# ───────────────────────────── aplicador de cambios en ficheros de otros papeles ─────────────────────────────
def _aplicador():
    import importlib.util
    spec = importlib.util.spec_from_file_location("aplicar_i19_r", RAIZ / "docs" / "I1" / "CAMBIOS-I19-R" / "aplicar_i19_r.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _arbol(tmp_path, quitar=None, crlf=False):
    m = _aplicador()
    por_fichero: dict[str, list[str]] = {}
    for rel, que, viejo, _ in m.CAMBIOS:
        if que != quitar:
            por_fichero.setdefault(rel, []).append(viejo)
    for rel, trozos in por_fichero.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        texto = "\nseparador\n".join(trozos) + "\n"
        p.write_bytes((texto.replace("\n", "\r\n") if crlf else texto).encode("utf-8"))
    return m


@pytest.mark.parametrize("crlf", [False, True])
def test_aplicador_aplica_todo_y_la_segunda_vez_no_hace_nada(tmp_path, capsys, crlf):
    m = _arbol(tmp_path, crlf=crlf)
    assert m.aplicar(tmp_path, comprobar=False) == 0
    assert m.aplicar(tmp_path, comprobar=True) == 0 and capsys.readouterr().out.count("YA APLICADO") == len(m.CAMBIOS)
    for rel in {c[0] for c in m.CAMBIOS}:
        b = (tmp_path / rel).read_bytes()
        assert (b.count(b"\r\n") == b.count(b"\n")) if crlf else b"\r" not in b


def test_aplicador_con_un_anclaje_ausente_no_escribe_nada(tmp_path, capsys):
    m = _arbol(tmp_path, quitar="PR18-7 · motivo de cada DISCREPA en la salida")
    antes = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert m.aplicar(tmp_path, comprobar=False) == 1
    assert "NO SE ESCRIBE NADA" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == antes


# Revisión (2.ª pasada, I1.9): la réplica tiene que fallar cerrado en los mismos casos que el núcleo.
def _defecto(valor):
    c = copy.deepcopy(CATALOGO)
    c["componentes"][0]["nivel_por_defecto"] = valor
    return c


DESCONOCIDO = {**COMP, "sku": "Premium v2", "justificacion_nivel": {"nivel": "Premium v2"}}


@pytest.mark.parametrize("valor, esperado", [
    ({"nivel": "Basic v2", "fuente": FUENTE}, True),               # control: por defecto con fuente de Learn
    ({"nivel": "Basic v2"}, False),                                 # sin fuente: el núcleo no lo toma por defecto
    ("Basic v2", False),                                            # cadena: el núcleo exige {nivel, fuente}
    ({"nivel": "Basic v2", "fuente": "http://learn.microsoft.com/x"}, False),   # no https
    ({"nivel": "Basic v3", "fuente": FUENTE}, False),               # no es uno de sus niveles
])
def test_vc18_3_nivel_por_defecto_igual_que_el_nucleo(valor, esperado):
    assert _ambos(LINEA.format(r="francecentral"), DESCONOCIDO, [], _defecto(valor)) is esperado


@pytest.mark.parametrize("fuente", [
    "https://learn.microsoft.com/azure/api-management/%2e%2e/%2e%2e/x",    # «..» codificado
    "https://learn.microsoft.com/azure/./api-management",                  # segmento «.»
    "https://learn.microsoft.com/",                                         # sin ruta
    "https://learn.microsoft.com:443/azure/api-management",                # con puerto
    "https://learn.microsoft.com:0/azure/api-management",                  # puerto 0 (falso para Python; Revisión)
    "https://evil.example/azure/api-management",                            # otro host
])
def test_vc18_3_fuente_rara_falla_cerrado_en_los_dos(fuente):
    c = copy.deepcopy(CATALOGO)
    c["componentes"][0]["disponibilidad"]["Standard v2"]["fuente"] = fuente
    assert not _ambos(LINEA.format(r="swedencentral"), COMP, [], c)


# Revisión (1.ª pasada, I1.9): «un importe en ppt/charts escapa a VA18-1». Falso positivo: la lista blanca C2 de partes
# del PPTX (PARTES_PPTX) no admite gráficos ni objetos incrustados; esta prueba lo demuestra con un importe dentro.
@real
@pytest.mark.parametrize("parte", ["ppt/charts/chart1.xml", "ppt/embeddings/oleObject1.bin"])
def test_va18_1_grafico_u_objeto_con_importe_falla_por_c2(tmp_path, parte):
    ctx = _ctx(HOSTELIA, tmp_path)
    origen, destino = ctx.fichero(ctx.sufijo_pptx()), tmp_path / "con_grafico.pptx"
    with zipfile.ZipFile(origen) as zi, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            zo.writestr(n, zi.read(n))
        zo.writestr(parte, '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart">'
                           '<c:v>25.000 €</c:v></c:chartSpace>')
    ctx._cache["pptx"] = vp.leer_pptx(destino)
    c = vp.c_cliente(ctx)
    assert c.estado == vp.FALLA and _detalles(c, f"parte no prevista {parte}"), c.detalles
