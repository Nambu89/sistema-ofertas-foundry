"""Regresión de la puerta real con las roturas de pruebas/I1/VERIF/romper.py (LES-G-097.4).

Cada caso de romper.py se aplica, en modo «simple» y «resellado», sobre paquetes REALES del núcleo
vigente (tests/fixtures_i1/paquete_real.py), con la recomposición local activa. Resellar es lo que
haría un modelo que domina su sandbox: altera el fichero y recalcula manifiesto, huellas y
hash_contenido. Toda rotura debe dar rc != 0; las tres que en I1 pasaban con rc 0 (precio,
aprobacion_copiada y xlsx_props) se comprueban además con su motivo.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import shutil
import zipfile
from xml.sax.saxutils import escape

import pytest

import verificar_paquete as vp
from tests.fixtures_i1 import paquete_real

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CATALOGO = RAIZ / "sandbox" / "datos" / "catalogo_componentes.json"


def _romper():
    spec = importlib.util.spec_from_file_location("romper_i1", RAIZ / "pruebas" / "I1" / "VERIF" / "romper.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _romper()


@pytest.fixture(scope="module")
def reales(tmp_path_factory) -> dict[str, pathlib.Path]:
    """LISTA_PARA_REVISION y APROBADA (mismo hash) generados por el núcleo vigente."""
    base = tmp_path_factory.mktemp("paquete_real")
    flujo = paquete_real.Flujo(base / "flujo")
    lista = shutil.copyfile(flujo.hasta_lista(), base / "lista.zip")
    aprobada = shutil.copyfile(flujo.aprobar(), base / "aprobada.zip")
    return {"A": pathlib.Path(lista), "AF": pathlib.Path(aprobada), "hoy": flujo.hoy}


def verificar(capsys, paquete: pathlib.Path, *extra: str) -> tuple[int, str]:
    rc = vp.main([str(paquete), "--transcripcion", str(paquete_real.TRANSCRIPCION), "--catalogo", str(CATALOGO),
                  "--sin-red", *extra])
    return rc, capsys.readouterr().out


def fallan(salida: str) -> list[str]:
    return [ln.split("]")[1].split(":")[0].strip() for ln in salida.splitlines() if ln.startswith("[FALLA]")]


# ───────────────── mutaciones de romper.py, generalizadas al paquete que se recibe ─────────────────

def _pptx(d):
    # VA18-7 (I1.9): en APROBADA el PPTX se llama «-Propuesta.pptx»
    return next(n for n in d if n.endswith("-Revision.pptx") or n.endswith("-Propuesta.pptx"))


def _eur(importe) -> str:
    from nucleo.pptx_revision import formato_eur
    return formato_eur(str(importe))


def _anadir_texto(d, diapo: int, texto: str) -> None:
    """Añade texto al último a:t de la diapositiva (como «Incluido (… 120 horas)» en romper.py)."""
    def f(t):
        i = t.rindex("</a:t>")
        return t[:i] + escape(texto) + t[i:]
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], f"ppt/slides/slide{diapo}.xml", f)


def m_horas(d, est): _anadir_texto(d, 5, " (dedicación estimada: 120 horas)")
def m_jornadas(d, est): _anadir_texto(d, 5, " unas 40 jornadas de trabajo")
def m_marcador(d, est): _anadir_texto(d, 5, " (alcance final por definir)")


def m_tarifa(d, est):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide7.xml",
                                 lambda t: t.replace("<a:t>IVA no incluido</a:t>", "<a:t>IVA no incluido · a 65 €/h</a:t>", 1))


def _precio(est) -> str:
    return _eur(est["carga"]["textos_cliente"]["precio"]["precio_cerrado_eur"])


def m_precio(d, est):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide7.xml",
                                 lambda t: t.replace(f"<a:t>{_precio(est)}</a:t>", "<a:t>19.990,00 €</a:t>", 1))


def m_precio_todo(d, est):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide7.xml", lambda t: t.replace(_precio(est), "19.990,00 €"))


def m_ajuste(d, est):
    est["carga"]["estimacion"]["entrada"]["ajuste_comercial_eur"] = -1000
    return True


def m_diagrama(d, est):
    nombre = est["carga"]["textos_cliente"]["arquitectura"]["capas"][0]["componentes"][0]["nombre"]
    def f(t):
        sps = re.findall(r"<p:sp>(?:(?!</p:sp>).)*?<a:t>" + re.escape(escape(nombre)) + r"</a:t>.*?</p:sp>", t, re.S)
        assert len(sps) == 1, f"forma de {nombre} no única: {len(sps)}"
        return t.replace(sps[0], "", 1)
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide4.xml", f)


def m_fuente(d, est):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide3.xml", lambda t: t.replace('typeface="Montserrat"', 'typeface="Arial"'))


def m_color(d, est):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide4.xml", lambda t: t.replace('val="F8485E"', 'val="00B050"'))


def m_aprobacion_copiada(d, est, reales):
    """Paquete LISTA con las decisiones del APROBADA del mismo hash; la diapositiva 2 sigue «Sin firma»."""
    otro = json.loads(R.leer_zip(reales["AF"])["estado.json"].decode("utf-8"))
    assert otro["hash_contenido"] == est["hash_contenido"], "los dos paquetes reales no comparten hash"
    est["decisiones"], est["estado"], est["estado_previo"] = otro["decisiones"], otro["estado"], otro.get("estado_previo")


# ───────────────── roturas nuevas de I1.1 (H-V2, H-V3, R1, C2) ─────────────────

def m_precio_sin_decimales(d, est):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide7.xml",
                                 lambda t: t.replace(f"<a:t>{_precio(est)}</a:t>", "<a:t>19.990 €</a:t>", 1))


def m_importe_diapo10(d, est): _anadir_texto(d, 10, " Descuento por volumen: 1.000,00 €")


def _cambiar_frase(d, est, hechos: list[str]) -> bool:
    f = est["carga"]["textos_cliente"]["alcance"][0]
    viejo, nuevo = escape(f["texto"]), "Incluye integración con SAP y soporte permanente."
    def g(t):  # el núcleo antepone la viñeta en el mismo a:t: se conserva el prefijo
        patron = re.compile(r"<a:t>([^<]{0,4})" + re.escape(viejo) + "</a:t>")
        assert len(patron.findall(t)) == 1, "la frase de alcance no está en un solo a:t"
        return patron.sub(lambda m: f"<a:t>{m.group(1)}{nuevo}</a:t>", t, count=1)
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide5.xml", g)
    f["texto"], f["hechos"] = nuevo, hechos
    return True


def m_frase_fijo_inventado(d, est): return _cambiar_frase(d, est, ["FIJO-X"])
def m_frase_hecho_valido(d, est): return _cambiar_frase(d, est, ["R-alcance_funcional"])


PNG_1X1 = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                        "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def m_imagen(d, est):
    import io
    src = zipfile.ZipFile(io.BytesIO(d[_pptx(d)]))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for i in src.infolist():
            z.writestr(i, src.read(i.filename))
        z.writestr("ppt/media/image1.png", PNG_1X1)
    d[_pptx(d)] = out.getvalue()


def m_descr(d, est):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide3.xml",
                                 lambda t: re.sub(r"<p:cNvPr ", '<p:cNvPr descr="dedicación de 120 horas" ', t, count=1))


def m_texto_en_patron(d, est):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slideLayouts/slideLayout1.xml",
                                 lambda t: re.sub(r"<a:t>[^<]+</a:t>", "<a:t>Tarifa aplicada: 65 €/h</a:t>", t, count=1))


def m_firma_inventada(d, est, reales):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide2.xml",
                                 lambda t: t.replace("<a:t>Sin firma</a:t>", f"<a:t>Responsable de preventa, {reales['hoy']}</a:t>", 1))


def m_aprobada_sin_firma(d, est, reales):
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide2.xml",
                                 lambda t: t.replace(f"<a:t>Responsable de área, {reales['hoy']}</a:t>", "<a:t>Sin firma</a:t>", 1))


def m_precio_formato_ingles(d, est):
    """El precio correcto, pero escrito «17852.50 €»: sin lectura española no casa (revisión independiente)."""
    valor = est["carga"]["textos_cliente"]["precio"]["precio_cerrado_eur"]
    d[_pptx(d)] = R.editar_ooxml(d[_pptx(d)], "ppt/slides/slide7.xml",
                                 lambda t: t.replace(f"<a:t>{_precio(est)}</a:t>", f"<a:t>{valor} €</a:t>", 1))


def m_parte_repetida(d, est):
    """Una segunda xl/worksheets/sheet1.xml dentro del XLSX: leída por nombre, colapsaría en una."""
    import io
    import warnings
    n = R.nombre(d, "-Estimacion.xlsx")
    src = zipfile.ZipFile(io.BytesIO(d[n]))
    out = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("xl/worksheets/sheet1.xml", src.read("xl/worksheets/sheet1.xml").replace(b"<v>", b"<v>9", 1))
            for i in src.infolist():
                z.writestr(i, src.read(i.filename))
    d[n] = out.getvalue()


def m_portada_y_algo_mas(d, est): _anadir_texto(d, 1, " · Incluye licencias")


# caso: (base, mutación, recibe los paquetes reales). Los 16 primeros son los de romper.py.
CASOS = {
    "horas": ("AF", m_horas, False), "jornadas": ("AF", m_jornadas, False), "tarifa": ("AF", m_tarifa, False),
    "precio": ("AF", m_precio, False), "precio_todo": ("AF", m_precio_todo, False), "ajuste": ("A", m_ajuste, False),
    "diagrama": ("AF", m_diagrama, False), "xlsx_byte": ("AF", R.m_xlsx_byte, False),
    "xlsx_props": ("AF", R.m_xlsx_props, False), "xlsx_horas": ("AF", R.m_xlsx_horas, False),
    "decision_vieja": ("AF", R.m_decision_vieja, False), "aprobacion_forjada": ("A", R.m_aprobacion_forjada, False),
    "aprobacion_copiada": ("A", m_aprobacion_copiada, True), "marcador": ("AF", m_marcador, False),
    "fuente": ("AF", m_fuente, False), "color": ("AF", m_color, False),
    "precio_sin_decimales": ("AF", m_precio_sin_decimales, False), "importe_diapo10": ("AF", m_importe_diapo10, False),
    "frase_fijo_inventado": ("A", m_frase_fijo_inventado, False), "frase_hecho_valido": ("A", m_frase_hecho_valido, False),
    "imagen": ("AF", m_imagen, False), "descr": ("AF", m_descr, False), "texto_en_patron": ("AF", m_texto_en_patron, False),
    "firma_inventada": ("A", m_firma_inventada, True), "aprobada_sin_firma": ("AF", m_aprobada_sin_firma, True),
    "precio_formato_ingles": ("AF", m_precio_formato_ingles, False), "parte_repetida": ("AF", m_parte_repetida, False),
    "portada_y_algo_mas": ("AF", m_portada_y_algo_mas, False),
}
ORIGINALES = list(CASOS)[:16]


def romper(reales, caso: str, modo: str, salida: pathlib.Path) -> pathlib.Path:
    base, fn, con_reales = CASOS[caso]
    d = R.leer_zip(reales[base])
    est = json.loads(d["estado.json"].decode("utf-8"))
    original, hash_antes = json.dumps(est, sort_keys=True), est["hash_contenido"]
    cambiada = bool(fn(d, est, reales) if con_reales else fn(d, est))
    if json.dumps(est, sort_keys=True) != original:
        d["estado.json"] = json.dumps(est, ensure_ascii=False, indent=2).encode("utf-8")
    if modo == "resellado":
        R.resellar(d, est, hash_antes, cambiada)
    R.escribir_zip(d, salida)
    return salida


# ───────────────── pruebas ─────────────────

def test_controles_positivos_de_paquetes_reales(capsys, reales):
    """Sin tocar: rc 0, recomposición idéntica byte a byte; APROBADA sin --previo queda NO VERIFICADO."""
    rc, out = verificar(capsys, reales["A"])
    assert rc == 0, out
    assert "PPTX: idéntico byte a byte al recompuesto en local" in out and "textos_cliente: idénticos" in out
    rc, out = verificar(capsys, reales["AF"])
    assert rc == 0, out
    assert "[NO VERIFICADO] decisiones" in out and "sin --previo" in out
    rc, out = verificar(capsys, reales["AF"], "--previo", str(reales["A"]))
    assert rc == 0, out
    assert "[OK] decisiones" in out and "solo cambian la diapositiva 2" in out


def test_estricto_convierte_no_verificado_en_rc_3(capsys, reales):
    rc, out = verificar(capsys, reales["A"], "--estricto")
    assert rc == 3 and "VEREDICTO: NO VERIFICADO CON --estricto rc=3" in out, out


@pytest.mark.parametrize("modo", ["simple", "resellado"])
@pytest.mark.parametrize("caso", ORIGINALES)
def test_romper_original(capsys, reales, tmp_path, caso, modo):
    rc, out = verificar(capsys, romper(reales, caso, modo, tmp_path / f"{caso}_{modo}.zip"))
    assert rc != 0, f"{caso} · {modo} pasa la puerta:\n{out}"


@pytest.mark.parametrize("caso", list(CASOS)[16:])
def test_romper_nuevo_resellado(capsys, reales, tmp_path, caso):
    rc, out = verificar(capsys, romper(reales, caso, "resellado", tmp_path / f"{caso}.zip"))
    assert rc == 1, f"{caso} pasa la puerta:\n{out}"


@pytest.mark.parametrize("caso,comprobaciones,motivo", [
    ("precio", {"coherencia", "recomposicion"}, "diapositiva 7: importe «19.990,00» que no es el precio cerrado"),
    ("aprobacion_copiada", {"coherencia", "recomposicion"}, "estado APROBADA con «Aprobado por» sin firma"),
    ("xlsx_props", {"recomposicion"}, "no es la hora interna del ZIP"),
    ("precio_sin_decimales", {"coherencia", "recomposicion"}, "diapositiva 7: importe «19.990»"),
    ("importe_diapo10", {"coherencia", "recomposicion"}, "diapositiva 10: importe «1.000,00»"),
    ("frase_fijo_inventado", {"coherencia", "recomposicion"}, "hechos inexistentes ['FIJO-X']"),
    ("frase_hecho_valido", {"recomposicion"}, "textos_cliente.alcance: distinto del recompuesto en local"),
    ("imagen", {"cliente_les_g_053", "recomposicion"}, "parte no prevista ppt/media/image1.png"),
    ("descr", {"cliente_les_g_053", "recomposicion"}, "atributo descr"),
    ("texto_en_patron", {"cliente_les_g_053", "recomposicion"}, "slideLayout1.xml: tarifa"),
    ("firma_inventada", {"coherencia", "recomposicion"}, "«Revisado por» dice «Responsable de preventa"),
    ("aprobada_sin_firma", {"coherencia", "recomposicion"}, "estado APROBADA con «Aprobado por» sin firma"),
    ("precio_formato_ingles", {"coherencia", "recomposicion"}, "diapositiva 7: importe «28025.25»"),
    ("parte_repetida", {"estructura"}, "parte repetida dentro del OOXML: xl/worksheets/sheet1.xml"),
])
def test_motivo_de_las_roturas_reselladas(capsys, reales, tmp_path, caso, comprobaciones, motivo):
    """Cada rotura salta por la regla que la describe, no por un efecto colateral (LES-G-077)."""
    rc, out = verificar(capsys, romper(reales, caso, "resellado", tmp_path / f"{caso}.zip"))
    assert rc == 1 and motivo in out, out
    assert comprobaciones <= set(fallan(out)), (fallan(out), out)
    assert "integridad" not in fallan(out), "el resellado debe dejar la integridad en verde"


def test_diagnostico_de_nucleo_distinto_del_desplegado(tmp_path, monkeypatch):
    nucleo = tmp_path / "nucleo"
    nucleo.mkdir()
    (nucleo / "hashes.py").write_text("x = 1\n", encoding="utf-8")
    man = tmp_path / "manifiesto.json"
    man.write_text(json.dumps({"ficheros": {"nucleo_hashes.py": {"sha256": vp.sha256_fichero(nucleo / "hashes.py")},
                                            "nucleo_estado.py": {"sha256": "0" * 64}}}), encoding="utf-8")
    monkeypatch.setattr(vp, "DIR_SANDBOX", tmp_path)
    assert vp.nucleo_distinto_del_desplegado(man) == ["estado.py"]


def test_previo_rechaza_una_portada_que_cambia_algo_mas_que_el_subtitulo(capsys, reales, tmp_path):
    malo = romper(reales, "portada_y_algo_mas", "resellado", tmp_path / "portada.zip")
    rc, out = verificar(capsys, malo, "--previo", str(reales["A"]))
    assert rc == 1 and "la portada cambia algo más que el subtítulo" in out, out


def test_xlsx_regenerado_solo_difiere_en_la_hora(reales, tmp_path):
    """c_previo admite el XLSX que el paso paquete rehace en un contenedor nuevo, y nada más."""
    d = R.leer_zip(reales["A"])
    n = R.nombre(d, "-Estimacion.xlsx")
    original = tmp_path / "a.xlsx"
    original.write_bytes(d[n])
    hora = tmp_path / "b.xlsx"
    hora.write_bytes(R.editar_ooxml(d[n], "docProps/core.xml", lambda t: re.sub(
        r"(<dcterms:modified[^>]*>)[^<]+", r"\g<1>2030-01-01T00:00:00Z", t)))
    hoja = tmp_path / "c.xlsx"
    hoja.write_bytes(R.editar_ooxml(d[n], "xl/worksheets/sheet1.xml", lambda t: t.replace("<v>", "<v>9", 1)))
    assert vp._xlsx_igual_salvo_hora(original, hora)
    assert not vp._xlsx_igual_salvo_hora(original, hoja)
