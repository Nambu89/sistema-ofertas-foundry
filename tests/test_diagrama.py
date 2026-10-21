"""Pruebas del generador del diagrama de arquitectura (docs/arquitectura/generar_diagrama.py).

No usan la red ni el juego de iconos real: fabrican iconos sintéticos con la misma estructura que los
oficiales (gradientes con id y referencias url(#id)). La última prueba usa el juego real si está en disco.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CARPETA = RAIZ / "docs" / "arquitectura"


def _cargar_modulo():
    spec = importlib.util.spec_from_file_location("generar_diagrama", CARPETA / "generar_diagrama.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gd = _cargar_modulo()

ICONO_SINTETICO = (
    '<svg id="raiz-{n}" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 18 18">'
    '<defs><linearGradient id="grad-{n}" x1="0" y1="0" x2="18" y2="18" gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#0078d4"/><stop offset="1" stop-color="#5ea0ef"/></linearGradient></defs>'
    '<title>Icon-{n}</title><rect x="1" y="1" width="16" height="16" rx="3" fill="url(#grad-{n})"/></svg>'
)


def _spec_real() -> dict:
    return json.loads((CARPETA / "arquitectura.json").read_text(encoding="utf-8"))


def _iconos_sinteticos(spec: dict, carpeta: Path) -> dict:
    """Escribe un icono sintético por clave y ajusta rutas y SHA-256 de la especificación."""
    for i, clave in enumerate(sorted(spec["iconos"])):
        rel = f"sinteticos/{clave}.svg"
        ruta = carpeta / rel
        ruta.parent.mkdir(parents=True, exist_ok=True)
        datos = ICONO_SINTETICO.format(n=i).encode("utf-8")
        ruta.write_bytes(datos)
        spec["iconos"][clave] = {"ruta": rel, "sha256": hashlib.sha256(datos).hexdigest()}
    return gd.cargar_iconos(spec, carpeta)


@pytest.fixture
def entorno(tmp_path):
    spec = _spec_real()
    iconos = _iconos_sinteticos(spec, tmp_path)
    return spec, iconos, tmp_path


# ------------------------------------------------------------------------------- completitud

def test_la_especificacion_real_es_valida():
    assert gd.validar_spec(_spec_real()) == []


def test_flujo_numerado_del_1_al_8():
    pasos = sorted(a["paso"] for a in _spec_real()["aristas"] if "paso" in a)
    assert pasos == list(range(1, 9))


def test_todas_las_salidas_contienen_todos_los_nodos_y_aristas(entorno):
    spec, iconos, _ = entorno
    salidas = gd.generar(spec, iconos)
    assert set(salidas) == {"arquitectura.es.svg", "arquitectura.en.svg", "arquitectura.es.html",
                            "arquitectura.en.html", "arquitectura.drawio"}
    for idioma in gd.IDIOMAS:
        for tipo in ("svg", "html"):
            texto = salidas[f"arquitectura.{idioma}.{tipo}"]
            for n in spec["nodos"]:
                assert f'id="n-{n["id"]}"' in texto
            for a in spec["aristas"]:
                assert f'id="e-{a["id"]}"' in texto
    drawio = salidas["arquitectura.drawio"]
    raiz = ET.fromstring(drawio)
    ids = {c.get("id") for c in raiz.iter("mxCell")}
    for idioma in gd.IDIOMAS:
        for n in spec["nodos"]:
            assert f"{idioma}-n-{n['id']}" in ids
        for a in spec["aristas"]:
            assert f"{idioma}-e-{a['id']}" in ids


def test_falta_un_nodo_en_la_salida_y_falla(entorno):
    spec, iconos, _ = entorno
    svg = gd.render_svg(spec, "es", iconos)
    roto = svg.replace('id="n-decision1"', 'id="n-otro"')
    errores = gd.comprueba_svg(spec, "es", roto, "roto.svg")
    assert any("falta el nodo decision1" in e for e in errores)


def test_falta_una_arista_en_el_drawio_y_falla(entorno):
    spec, iconos, _ = entorno
    drawio = gd.render_drawio(spec, iconos)
    roto = drawio.replace('id="en-e-escriba_storage"', 'id="en-e-otra"')
    errores = gd.comprueba_drawio(spec, roto, "roto.drawio")
    assert any("falta la arista escriba_storage" in e for e in errores)


def test_falta_el_texto_de_una_etiqueta_y_falla(entorno):
    spec, iconos, _ = entorno
    svg = gd.render_svg(spec, "en", iconos)
    roto = svg.replace(">Verifier<", "><", 1)
    errores = gd.comprueba_svg(spec, "en", roto, "roto.svg")
    assert any("verificador" in e and "Verifier" in e for e in errores)


def test_arista_hacia_un_nodo_inexistente_falla():
    spec = _spec_real()
    spec["aristas"][0]["destino"] = "no_existe"
    assert any("destino desconocido" in e for e in gd.validar_spec(spec))


def test_paso_repetido_falla():
    spec = _spec_real()
    con_paso = [a for a in spec["aristas"] if "paso" in a]
    con_paso[1]["paso"] = con_paso[0]["paso"]
    assert any("pasos del flujo" in e for e in gd.validar_spec(spec))


def test_texto_que_se_sale_del_grupo_falla():
    spec = _spec_real()
    nodo = next(n for n in spec["nodos"] if n["id"] == "web_search")
    nodo["etiqueta"]["es"][1] = "consultas genéricas sin datos de cliente ni del pliego, nunca"
    assert any("web_search" in e and "se sale" in e for e in gd.validar_spec(spec))


def test_nodos_solapados_fallan():
    spec = _spec_real()
    nodo = next(n for n in spec["nodos"] if n["id"] == "gpt6")
    otro = next(n for n in spec["nodos"] if n["id"] == "decision1")
    nodo["pos"] = [otro["pos"][0] + 20, otro["pos"][1]]
    assert any("se solapan" in e for e in gd.validar_spec(spec))


def test_extremo_de_arista_lejos_de_su_nodo_falla():
    spec = _spec_real()
    arista = next(a for a in spec["aristas"] if a["id"] == "escriba_storage")
    arista["puntos"][-1] = [1500, 850]
    assert any("no toca storage" in e for e in gd.validar_spec(spec))


def test_no_escribe_nada_si_las_comprobaciones_fallan(entorno, monkeypatch):
    spec, iconos, carpeta = entorno
    salida = carpeta / "salida"
    ruta_spec = carpeta / "spec.json"
    spec_roto = copy.deepcopy(spec)
    spec_roto["aristas"][0]["destino"] = "no_existe"
    ruta_spec.write_text(json.dumps(spec_roto), encoding="utf-8")
    rc = gd.main(["--spec", str(ruta_spec), "--iconos", str(carpeta), "--salida", str(salida)])
    assert rc == 1
    assert not salida.exists()


def test_especificacion_con_estructura_rota_sale_con_1(tmp_path):
    ruta = tmp_path / "spec.json"
    spec = _spec_real()
    spec["nodos"][0]["etiqueta"] = "no es un diccionario"
    ruta.write_text(json.dumps(spec), encoding="utf-8")
    rc = gd.main(["--spec", str(ruta), "--iconos", str(tmp_path), "--salida", str(tmp_path / "s")])
    assert rc == 1  # la especificación se valida antes de buscar los iconos
    assert not (tmp_path / "s").exists()


def test_especificacion_inexistente_es_error_de_entorno(tmp_path):
    rc = gd.main(["--spec", str(tmp_path / "no-existe.json"), "--salida", str(tmp_path / "s")])
    assert rc == 2
    assert not (tmp_path / "s").exists()


def test_si_falla_edge_no_se_escribe_nada(entorno):
    """Con --png, un fallo de Edge no deja SVG, HTML ni draw.io a medias en el destino."""
    spec, _, carpeta = entorno
    ruta_spec = carpeta / "spec.json"
    ruta_spec.write_text(json.dumps(spec), encoding="utf-8")
    salida = carpeta / "salida"
    # sys.executable con las opciones de Edge sale con 2 sin generar ningún PNG
    rc = gd.main(["--spec", str(ruta_spec), "--iconos", str(carpeta), "--salida", str(salida),
                  "--png", "--edge", sys.executable])
    assert rc == 2
    assert not salida.exists()
    rc = gd.main(["--spec", str(ruta_spec), "--iconos", str(carpeta), "--salida", str(salida),
                  "--png", "--edge", str(carpeta / "no-existe.exe")])
    assert rc == 2
    assert not salida.exists()


def test_si_falla_una_copia_no_se_toca_ninguna_salida_previa(entorno, monkeypatch):
    spec, _, carpeta = entorno
    ruta_spec = carpeta / "spec.json"
    ruta_spec.write_text(json.dumps(spec), encoding="utf-8")
    salida = carpeta / "salida"
    salida.mkdir()
    previa = salida / "arquitectura.es.svg"
    previa.write_bytes(b"version anterior")
    copiar = gd.shutil.copyfile
    llamadas = []

    def copia_que_falla(origen, destino):
        llamadas.append(destino)
        if len(llamadas) == 3:
            raise OSError("disco lleno (simulado)")
        return copiar(origen, destino)

    monkeypatch.setattr(gd.shutil, "copyfile", copia_que_falla)
    rc = gd.main(["--spec", str(ruta_spec), "--iconos", str(carpeta), "--salida", str(salida)])
    assert rc == 2
    assert previa.read_bytes() == b"version anterior"
    assert sorted(x.name for x in salida.iterdir()) == ["arquitectura.es.svg"]  # ni salidas nuevas ni temporales


def test_texto_de_arista_que_cruza_el_borde_de_un_grupo_falla():
    spec = _spec_real()
    arista = next(a for a in spec["aristas"] if a["id"] == "actions_grupo_recursos")
    arista["etiqueta_xy"] = [290, 616]
    errores = gd.validar_spec(spec)
    assert any("actions_grupo_recursos" in e and "cruza el borde de desarrollo" in e for e in errores)


def test_falta_el_pie_de_la_derecha_y_falla(entorno):
    spec, iconos, _ = entorno
    texto = spec["pie_derecha"]["es"]
    svg = gd.render_svg(spec, "es", iconos)
    assert any("pie de la derecha" in e for e in gd.comprueba_svg(spec, "es", svg.replace(texto, "x"), "roto.svg"))
    drawio = gd.render_drawio(spec, iconos)
    roto = drawio.replace('id="es-pie-derecha"', 'id="es-otro"')
    assert any("[es]: falta el pie-derecha" in e for e in gd.comprueba_drawio(spec, roto, "roto.drawio"))


def test_drawio_comprueba_cabecera_banda_y_leyenda(entorno):
    spec, iconos, _ = entorno
    drawio = gd.render_drawio(spec, iconos)
    assert gd.comprueba_drawio(spec, drawio, "ok.drawio") == []
    elemento = spec["validado"]["elementos"][3]["en"]
    leyenda = spec["leyenda"][1]["en"]
    roto = drawio.replace(gd.escape(elemento), "x").replace(gd.escape(leyenda), "y")
    errores = gd.comprueba_drawio(spec, roto, "roto.drawio")
    assert any("banda no muestra" in e and elemento in e for e in errores)
    assert any("leyenda no muestra" in e and leyenda in e for e in errores)
    roto = drawio.replace('id="en-subtitulo"', 'id="en-otro"')
    assert any("[en]: falta el subtitulo" in e for e in gd.comprueba_drawio(spec, roto, "roto.drawio"))


def test_main_sin_iconos_es_error_de_entorno(tmp_path):
    rc = gd.main(["--iconos", str(tmp_path / "no-existe"), "--salida", str(tmp_path / "s")])
    assert rc == 2


# ------------------------------------------------------------------------------------ escapado

def test_texto_con_caracteres_especiales_se_escapa(entorno):
    spec, iconos, _ = entorno
    malicioso = '<script>alert("x")</script> & «ñ»'
    nodo = next(n for n in spec["nodos"] if n["id"] == "portal")
    nodo["etiqueta"]["es"] = ["Portal", malicioso[:20]]
    arista = next(a for a in spec["aristas"] if a["id"] == "opencode_coordinador")
    arista["etiqueta"]["es"] = ["A & B <c>"]
    svg = gd.render_svg(spec, "es", iconos)
    ET.fromstring(svg)  # sigue siendo XML bien formado
    assert "<script" not in svg
    assert "&lt;script&gt;" in svg and "A &amp; B &lt;c&gt;" in svg
    drawio = gd.render_drawio(spec, iconos)
    raiz = ET.fromstring(drawio)
    valor = next(c.get("value") for c in raiz.iter("mxCell") if c.get("id") == "es-n-portal")
    # En draw.io el valor es HTML: el texto del usuario llega escapado y sin etiquetas activas
    assert "<script" not in valor and "&lt;script&gt;" in valor


def test_titulo_subtitulo_y_grupos_escapados_en_drawio(entorno):
    """draw.io interpreta como HTML las celdas con html=1: el texto tiene que llegar escapado."""
    spec, iconos, _ = entorno
    spec["titulo"]["es"] = '<img src=x> & título'
    spec["subtitulo"]["en"] = "<b>sub</b>"
    spec["grupos"][0]["titulo"]["es"] = "<i>Canales</i>"
    drawio = gd.render_drawio(spec, iconos)
    valores = {c.get("id"): c.get("value") for c in ET.fromstring(drawio).iter("mxCell")}
    assert valores["es-titulo"] == "&lt;img src=x&gt; &amp; título"
    assert valores["en-subtitulo"] == "&lt;b&gt;sub&lt;/b&gt;"
    assert valores["es-g-canales"] == "&lt;i&gt;Canales&lt;/i&gt;"
    assert gd.comprueba_drawio(spec, drawio, "ok.drawio") == []
    # Un manejador on*, aunque llegue escapado, hace fallar la comprobación global: falla cerrado.
    spec["titulo"]["es"] = "<img src=x onerror=alert(1)>"
    drawio = gd.render_drawio(spec, iconos)
    assert "&amp;lt;img src=x onerror=alert(1)&amp;gt;" in drawio  # escapado como HTML y como XML
    assert any("manejador on*" in e for e in gd.comprueba_drawio(spec, drawio, "x.drawio"))


def test_comprobacion_detecta_marcado_activo_en_un_valor_de_drawio(entorno):
    spec, iconos, _ = entorno
    drawio = gd.render_drawio(spec, iconos)
    # Valor con una etiqueta real tras interpretar el XML (como lo vería draw.io)
    roto = drawio.replace('value="Canales"', 'value="&lt;img src=x onerror=alert(1)&gt;Canales"', 1)
    assert roto != drawio
    errores = gd.comprueba_drawio(spec, roto, "roto.drawio")
    assert any("marcado no admitido" in e and "es-g-canales" in e for e in errores)


def test_clave_de_icono_y_viewbox_no_admitidos():
    spec = _spec_real()
    spec["iconos"]['mala"clave'] = spec["iconos"]["agente"]
    assert any("clave no permitida" in e for e in gd.validar_spec(spec))
    icono = ICONO_SINTETICO.format(n=1).replace('viewBox="0 0 18 18"', 'viewBox="0 0 x x"')
    with pytest.raises(gd.ErrorDiagrama, match="viewBox"):
        gd.comprueba_icono(icono, "vb")


def test_titulo_y_pie_escapados_en_html(entorno):
    spec, iconos, _ = entorno
    spec["titulo"]["es"] = "Título <b>raro</b> & más"
    svg = gd.render_svg(spec, "es", iconos)
    html = gd.render_html(spec, "es", svg)
    assert "<title>Título &lt;b&gt;raro&lt;/b&gt; &amp; más</title>" in html
    assert "<b>raro</b>" not in html


# ------------------------------------------------------------------------------------ id únicos

def test_ids_unicos_aunque_un_icono_se_repita(entorno):
    spec, iconos, _ = entorno
    usos = sum(1 for n in spec["nodos"] if n.get("icono") == "agente")
    assert usos >= 7  # el coordinador y los seis especialistas comparten icono
    for idioma in gd.IDIOMAS:
        svg = gd.render_svg(spec, idioma, iconos)
        ids = re.findall(r'\bid="([^"]+)"', svg)
        assert len(ids) == len(set(ids))
        refs = set(re.findall(r"url\(#([^)]+)\)", svg))
        assert refs <= set(ids), "toda referencia url(#…) tiene destino"


def test_el_icono_se_incrusta_sin_alterar_su_dibujo():
    original = ICONO_SINTETICO.format(n=7)
    frag = gd.icono_incrustado(original, "i-x-", 10, 20, 48)
    assert frag.startswith('<svg x="10" y="20" width="48" height="48" viewBox="0 0 18 18">')
    interior = frag[frag.index(">") + 1:-len("</svg>")]
    assert gd.desprefija(interior, "i-x-") == original


def test_sha_distinto_del_esperado_falla(entorno):
    spec, _, carpeta = entorno
    clave = "agente"
    ruta = carpeta / spec["iconos"][clave]["ruta"]
    ruta.write_bytes(ruta.read_bytes().replace(b"#0078d4", b"#ff0000"))
    with pytest.raises(gd.ErrorDiagrama, match="SHA-256"):
        gd.cargar_iconos(spec, carpeta)


def test_ruta_de_icono_con_salto_de_carpeta_falla():
    spec = _spec_real()
    spec["iconos"]["agente"]["ruta"] = "../fuera.svg"
    assert any("ruta no permitida" in e for e in gd.validar_spec(spec))


# ---------------------------------------------------------------------------------- sin scripts

@pytest.mark.parametrize("veneno", [
    '<script>alert(1)</script>',
    '<rect width="1" height="1" onload="alert(1)"/>',
    '<a href="javascript:alert(1)"><rect width="1" height="1"/></a>',
    '<style>rect{fill:red}</style>',
    '<use href="https://ejemplo.invalid/x.svg#a"/>',
    '<image width="1" height="1"/>',
    '<rect width="1" height="1" fill="url(https://ejemplo.invalid/a)"/>',
    '<g xmlns:xl="http://www.w3.org/1999/xlink" xl:href="#grad-1"/>',
])
def test_icono_con_contenido_activo_se_rechaza(veneno):
    icono = ICONO_SINTETICO.format(n=1).replace("</svg>", veneno + "</svg>")
    with pytest.raises(gd.ErrorDiagrama):
        gd.comprueba_icono(icono, "veneno")


def test_las_salidas_no_tienen_scripts_ni_manejadores(entorno):
    spec, iconos, _ = entorno
    salidas = gd.generar(spec, iconos)
    for nombre, texto in salidas.items():
        assert not re.search(r"<\s*script", texto, re.I), nombre
        assert not re.search(r"<[^>]*\son[a-z]+\s*=", texto, re.I), nombre
        assert "javascript:" not in texto.lower(), nombre


def test_comprobacion_detecta_javascript_en_una_salida(entorno):
    spec, iconos, _ = entorno
    svg = gd.render_svg(spec, "es", iconos)
    roto = svg.replace("</svg>", '<a href="javascript:alert(1)"/></svg>')
    assert any("javascript:" in e for e in gd.comprueba_svg(spec, "es", roto, "roto.svg"))


# ------------------------------------------------------------------------------- determinismo

def test_generacion_determinista(entorno):
    spec, iconos, _ = entorno
    assert gd.generar(spec, iconos) == gd.generar(copy.deepcopy(spec), iconos)


def test_sin_identificadores_sensibles_en_la_especificacion():
    texto = (CARPETA / "arquitectura.json").read_text(encoding="utf-8")
    guid = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
    assert not guid.search(texto), "sin GUID de tenant ni de suscripción"
    assert "@" not in texto, "sin correos"
    assert "€" not in texto, "sin tarifas"


# ------------------------------------------------------------------------- juego real (opcional)

def test_genera_con_el_juego_real_si_esta_disponible(tmp_path):
    carpeta = Path(gd.ICONOS_DEFECTO)
    if not carpeta.is_dir():
        pytest.skip("el juego oficial de iconos no está en este equipo")
    rc = gd.main(["--iconos", str(carpeta), "--salida", str(tmp_path)])
    assert rc == 0
    for nombre in ("arquitectura.es.svg", "arquitectura.en.svg", "arquitectura.drawio"):
        assert (tmp_path / nombre).stat().st_size > 10_000


# ------------------------------------------------------------------- genérico: sin nombres propios

PROHIBIDO = re.compile(r"devoteam|fernando|prada|\bofa-|paso 0a|step 0a|ai gateway|diseño final", re.I)
DATOS_ICONO = re.compile(r"image=data:image/svg\+xml,[A-Za-z0-9+/=]+")


def _sin_nombres(nombre: str, texto: str) -> None:
    texto = DATOS_ICONO.sub("", texto)  # el base64 de los iconos no es texto visible
    m = PROHIBIDO.search(texto)
    assert m is None, f"{nombre}: aparece «{m.group(0)}»"


def test_ninguna_salida_menciona_empresa_persona_ni_prefijos_internos(entorno):
    spec, iconos, _ = entorno
    for nombre, texto in gd.generar(spec, iconos).items():
        _sin_nombres(nombre, texto)
    for nombre in ("arquitectura.json", "README.md", "ICONOS.md"):
        _sin_nombres(nombre, (CARPETA / nombre).read_text(encoding="utf-8"))


def test_las_salidas_publicadas_tampoco_mencionan_nombres():
    """Lo que ya está en el repositorio (SVG, HTML y draw.io regenerados) cumple lo mismo."""
    for idioma in gd.IDIOMAS:
        for tipo in ("svg", "html"):
            ruta = CARPETA / f"arquitectura.{idioma}.{tipo}"
            _sin_nombres(ruta.name, ruta.read_text(encoding="utf-8"))
    _sin_nombres("arquitectura.drawio", (CARPETA / "arquitectura.drawio").read_text(encoding="utf-8"))


def test_la_comprobacion_de_nombres_detecta_un_prefijo_interno():
    with pytest.raises(AssertionError, match="ofa-"):
        _sin_nombres("x.svg", "<text>ofa-coordinador</text>")


def test_letra_minima_de_13_px_en_todas_las_salidas(entorno):
    spec, iconos, _ = entorno
    salidas = gd.generar(spec, iconos)
    for idioma in gd.IDIOMAS:
        tamanos = [float(t) for t in re.findall(r'font-size="([\d.]+)"', salidas[f"arquitectura.{idioma}.svg"])]
        assert tamanos and min(tamanos) >= 13
    tamanos = [float(t) for t in re.findall(r"fontSize=([\d.]+)", salidas["arquitectura.drawio"])]
    assert tamanos and min(tamanos) >= 13


def test_lienzo_de_1920_por_1080():
    spec = _spec_real()
    assert (spec["lienzo"]["ancho"], spec["lienzo"]["alto"]) == (1920, 1080)


# ------------------------------------------------------------------------------ límites anidados

def _caja(c):
    return (c[0], c[1], c[0] + c[2], c[1] + c[3])


def test_los_limites_anidados_contienen_a_sus_hijos():
    spec = _spec_real()
    grupos = {g["id"]: g for g in spec["grupos"]}
    por_limite = {g["limite"]: g for g in spec["grupos"] if g.get("limite")}
    cadena = [por_limite[l] for l in gd.LIMITES] + [grupos["foundry"]]
    for padre, hijo in zip(cadena, cadena[1:]):
        assert hijo["padre"] == padre["id"]
        assert gd.dentro(_caja(hijo["caja"]), _caja(padre["caja"])), f"{hijo['id']} fuera de {padre['id']}"
        assert hijo["caja"][1] >= padre["caja"][1] + gd.CABECERA, f"{hijo['id']} pisa la cabecera de {padre['id']}"
    for idioma in gd.IDIOMAS:
        for n in spec["nodos"]:
            if n["grupo"]:
                for g in gd.ancestros(grupos, n["grupo"]):
                    assert gd.dentro(gd.caja_nodo(n, idioma), _caja(grupos[g]["caja"])), (n["id"], g)
    assert por_limite["tenant"]["icono"] == "entra_id"
    assert spec["iconos"]["entra_id"]["juego"] == "entra_oct2023"


def test_un_nodo_que_invade_un_grupo_ajeno_falla():
    spec = _spec_real()
    kv = next(n for n in spec["nodos"] if n["id"] == "key_vault")
    kv["pos"] = [1340, 300]  # dentro de la región, pero encima de Microsoft Foundry
    assert any("key_vault" in e and "invade el grupo foundry" in e for e in gd.validar_spec(spec))


def test_un_limite_fuera_de_su_padre_falla():
    spec = _spec_real()
    region = next(g for g in spec["grupos"] if g["id"] == "region")
    region["caja"][2] += 40  # se sale del grupo de recursos por la derecha
    assert any("region" in e and "se sale de su grupo padre" in e for e in gd.validar_spec(spec))


def test_un_limite_con_el_padre_equivocado_falla():
    spec = _spec_real()
    rg = next(g for g in spec["grupos"] if g.get("limite") == "grupo_recursos")
    rg["padre"] = "tenant"
    assert any("grupo_recursos" in e and "padre tiene que ser" in e for e in gd.validar_spec(spec))


def test_un_hijo_que_pisa_la_cabecera_de_su_limite_falla():
    spec = _spec_real()
    foundry = next(g for g in spec["grupos"] if g["id"] == "foundry")
    foundry["caja"][1] -= 20
    foundry["caja"][3] += 20
    assert any("pisa la cabecera de region" in e for e in gd.validar_spec(spec))


def test_el_icono_de_la_cabecera_del_limite_se_incrusta(entorno):
    spec, iconos, _ = entorno
    svg = gd.render_svg(spec, "es", iconos)
    roto = re.sub(r'(<g id="g-tenant"[^>]*>.*?)<g data-icono="entra_id">.*?</svg></g>', r"\1", svg, count=1,
                  flags=re.S)
    assert roto != svg
    assert any("tenant no lleva su icono" in e for e in gd.comprueba_svg(spec, "es", roto, "roto.svg"))


# ------------------------------------------------------------------- banda de buenas prácticas

def _carpeta_catalogo() -> Path | None:
    """El catálogo verificado vive en el banco de modelos; en otra rama, por variable o carpeta vecina."""
    import os
    candidatas = [os.environ.get("CATALOGO_PRACTICAS", ""), str(RAIZ / "pruebas" / "modelos"),
                  str(RAIZ.parent / "sistema-ofertas-foundry" / "pruebas" / "modelos")]
    for c in candidatas:
        if c and (Path(c) / "catalogo_practicas.json").is_file() and (Path(c) / "catalogo_evidencia.json").is_file():
            return Path(c)
    return None


def test_cada_practica_de_la_banda_esta_en_el_catalogo_con_url_y_cita():
    carpeta = _carpeta_catalogo()
    if carpeta is None:
        pytest.skip("el catálogo verificado de buenas prácticas no está en este equipo")
    catalogo = json.loads((carpeta / "catalogo_practicas.json").read_text(encoding="utf-8"))
    evidencia = json.loads((carpeta / "catalogo_evidencia.json").read_text(encoding="utf-8"))
    por_id = {p["id"]: p for p in catalogo["practicas"]}
    pruebas = {p["id"]: p for p in evidencia["practicas"]}
    spec = _spec_real()
    nombre_pilar = {p["id"]: p["es"] for p in spec["practicas"]["pilares"]}
    assert len(spec["practicas"]["catalogo"]) >= 12
    for pr in spec["practicas"]["catalogo"]:
        ref = por_id.get(pr["id"])
        assert ref is not None, f"{pr['id']} no está en el catálogo"
        assert pr["url"] == ref["url"] and pr["url"].startswith("https://learn.microsoft.com/"), pr["id"]
        assert pr["cita"] == ref["cita"] and pr["cita"].strip(), pr["id"]
        assert pr["waf"] == ref["waf"], pr["id"]
        assert nombre_pilar[pr["pilar"]] == ref["pilar"], pr["id"]
        prueba = pruebas.get(pr["id"])
        assert prueba and prueba["estado_http"] == 200 and prueba["cita_encontrada"] is True, pr["id"]
        assert prueba["url"] == pr["url"], pr["id"]


def test_seis_pilares_con_dos_o_tres_practicas():
    spec = _spec_real()
    nombres = [p["es"] for p in spec["practicas"]["pilares"]]
    assert nombres == ["Desarrollo", "Mantenibilidad", "Escalado", "Seguridad", "Coste", "Fiabilidad"]
    for pilar, lista in gd.practicas_por_pilar(spec).items():
        assert 2 <= len(lista) <= 3, pilar


@pytest.mark.parametrize("cuantas", [1, 4])
def test_pilar_con_menos_de_dos_o_mas_de_tres_practicas_falla(cuantas):
    spec = _spec_real()
    cat = spec["practicas"]["catalogo"]
    de_coste = [p for p in cat if p["pilar"] == "coste"]
    if cuantas == 1:
        cat.remove(de_coste[0])
    else:
        for i in range(4 - len(de_coste)):
            extra = copy.deepcopy(de_coste[0])
            extra["id"] = f"COS-9{i}"
            cat.append(extra)
    assert any("pilar coste" in e and "tienen que ser 2 o 3" in e for e in gd.validar_spec(spec))


def test_practica_referenciada_inexistente_falla():
    spec = _spec_real()
    spec["nodos"][0]["practicas"] = ["SEG-99"]
    assert any("práctica inexistente 'SEG-99'" in e for e in gd.validar_spec(spec))


def test_practica_sin_url_de_learn_o_sin_cita_falla():
    spec = _spec_real()
    spec["practicas"]["catalogo"][0]["url"] = "https://ejemplo.invalid/x"
    spec["practicas"]["catalogo"][1]["cita"] = "  "
    errores = gd.validar_spec(spec)
    assert any("la URL tiene que ser de https://learn.microsoft.com/" in e for e in errores)
    assert any("sin cita" in e for e in errores)


def test_icono_de_un_juego_desconocido_falla(entorno):
    spec = _spec_real()
    spec["iconos"]["agente"]["juego"] = "juego_inventado"
    assert any("juego de iconos desconocido" in e for e in gd.validar_spec(spec))
    spec, _, carpeta = entorno
    spec["iconos"]["agente"]["juego"] = "juego_inventado"
    with pytest.raises(gd.ErrorDiagrama, match="juego de iconos desconocido"):
        gd.cargar_iconos(spec, {"azure_v24": carpeta, "entra_oct2023": carpeta})


def test_falta_la_carpeta_de_un_juego_es_error_de_entorno(entorno):
    spec, _, carpeta = entorno
    spec["iconos"]["entra_id"]["juego"] = "entra_oct2023"
    with pytest.raises(gd.ErrorEntorno, match="entra_oct2023"):
        gd.cargar_iconos(spec, {"azure_v24": carpeta, "entra_oct2023": carpeta / "no-existe"})


def test_la_banda_muestra_cada_practica_con_su_url_y_su_cita(entorno):
    spec, iconos, _ = entorno
    salidas = gd.generar(spec, iconos)
    for idioma in gd.IDIOMAS:
        svg = salidas[f"arquitectura.{idioma}.svg"]
        for pr in spec["practicas"]["catalogo"]:
            assert f'data-id="{pr["id"]}"' in svg
            assert gd.escape(pr["texto"][idioma]) in svg and gd.escape(pr["url"]) in svg
        for pil in spec["practicas"]["pilares"]:
            assert f'id="pilar-{pil["id"]}"' in svg
    pr = spec["practicas"]["catalogo"][4]
    svg = salidas["arquitectura.es.svg"]
    roto = svg.replace(f'data-id="{pr["id"]}"', 'data-id="OTR-00"')
    assert any(f"falta la práctica {pr['id']}" in e for e in gd.comprueba_svg(spec, "es", roto, "roto.svg"))
    drawio = salidas["arquitectura.drawio"]
    roto = drawio.replace(gd.escape(gd.escape(pr["texto"]["en"])), "x")
    assert any(f"práctica {pr['id']} no aparece" in e for e in gd.comprueba_drawio(spec, roto, "roto.drawio"))


def test_texto_de_practica_demasiado_largo_falla():
    spec = _spec_real()
    spec["practicas"]["catalogo"][0]["texto"]["en"] = "A practice text far too long to fit inside its pillar column"
    assert any("no cabe en su columna" in e for e in gd.validar_spec(spec))


def test_banda_que_pisa_el_diagrama_falla():
    spec = _spec_real()
    spec["validado"]["caja"][1] = 830
    assert any("la banda validado pisa el diagrama" in e for e in gd.validar_spec(spec))


def test_leyenda_con_simbolo_de_limite_y_de_validado():
    simbolos = {el["simbolo"] for el in _spec_real()["leyenda"]}
    assert {"limite", "validado", "paso", "neutro"} <= simbolos


@pytest.mark.parametrize("url", ["https://learn.microsoft.com.ejemplo.invalid/x", "http://learn.microsoft.com/x",
                                 "https://usuario@learn.microsoft.com/x"])
def test_url_que_no_es_de_learn_falla(url):
    spec = _spec_real()
    spec["practicas"]["referencia"][0]["url"] = url
    assert any("la URL tiene que ser de https://learn.microsoft.com/" in e for e in gd.validar_spec(spec))


# ------------------------------------------------------- nombre en varias líneas y nota de la banda

def test_nombre_del_servicio_en_dos_lineas_va_en_negrita(entorno):
    spec, iconos, _ = entorno
    n = next(n for n in spec["nodos"] if n.get("nombre_lineas") == 2)
    salidas = gd.generar(spec, iconos)
    raiz = ET.fromstring(salidas["arquitectura.es.svg"])
    ns = "{http://www.w3.org/2000/svg}"
    el = next(e for e in raiz.iter(ns + "g") if e.get("id") == f"n-{n['id']}")
    negritas = ["".join(t.itertext()) for t in el.iter(ns + "text") if t.get("font-weight") == "600"]
    assert negritas == n["etiqueta"]["es"][:2]
    assert f"<b>{gd.escape(n['etiqueta']['en'][1])}</b>" in gd.valor_html(n["etiqueta"]["en"], 2)


@pytest.mark.parametrize("valor", [0, 4, True, "2"])
def test_nombre_lineas_no_valido_falla(valor):
    spec = _spec_real()
    n = next(n for n in spec["nodos"] if n.get("nombre_lineas") == 2)
    n["nombre_lineas"] = valor
    assert any(f"nodo {n['id']}: nombre_lineas" in e for e in gd.validar_spec(spec))


NOTA_PRUEBA = {"es": "Nota de prueba", "en": "Test note"}


def test_la_nota_de_la_banda_validado_aparece_en_todas_las_salidas(entorno):
    spec, iconos, _ = entorno
    spec = copy.deepcopy(spec)
    spec["validado"]["nota"] = dict(NOTA_PRUEBA)
    assert gd.validar_spec(spec) == []
    salidas = gd.generar(spec, iconos)
    for idioma in gd.IDIOMAS:
        nota = spec["validado"]["nota"][idioma]
        assert gd.escape(nota) in salidas[f"arquitectura.{idioma}.svg"]
        roto = salidas[f"arquitectura.{idioma}.svg"].replace(gd.escape(nota), "x")
        assert any("la banda no muestra" in e for e in gd.comprueba_svg(spec, idioma, roto, "roto.svg"))
    assert gd.escape(gd.escape(spec["validado"]["nota"]["en"])) in salidas["arquitectura.drawio"]


def test_nota_de_la_banda_validado_que_no_cabe_o_vacia_falla():
    spec = _spec_real()
    spec["validado"]["nota"] = dict(NOTA_PRUEBA)
    spec["validado"]["nota"]["en"] = "A note far too long to fit at the end of the validated band, by any measure"
    assert any("[en] la banda validado no cabe" in e for e in gd.validar_spec(spec))
    spec["validado"]["nota"]["en"] = "  "
    assert any("[en] la nota de la banda validado está vacía" in e for e in gd.validar_spec(spec))


def test_ninguna_practica_presenta_un_presupuesto_como_freno_del_gasto():
    """Learn (REF-09): un presupuesto avisa al pasar el umbral, pero no detiene el consumo."""
    spec = _spec_real()
    for x in spec["practicas"]["catalogo"]:
        for idioma in gd.IDIOMAS:
            texto = x["texto"][idioma].lower()
            if "presupuesto" in texto or "budget" in texto:
                assert not re.search(r"barrera|freno|guardrail|limit", texto), x["id"]


@pytest.mark.parametrize("nota", ["texto suelto", None, {"es": "solo en castellano"}, {"es": 3, "en": "x"}])
def test_nota_mal_formada_es_error_de_validacion_y_no_excepcion(nota):
    spec = _spec_real()
    spec["validado"]["nota"] = nota
    assert any("la nota de la banda validado está vacía o mal formada" in e for e in gd.validar_spec(spec))


# ---------------------------------------------- términos de los iconos: nombre del servicio y terceros

def test_cada_icono_lleva_cerca_el_nombre_de_su_servicio():
    """FAQ del ZIP V24: «the full name of the service should always appear near the icon»."""
    assert gd.validar_nombres_de_servicio(_spec_real()) == []


def test_icono_sin_el_nombre_de_su_servicio_cerca_falla():
    spec = _spec_real()
    g = next(g for g in spec["grupos"] if g["id"] == "especialistas")
    g["titulo"]["es"] = "Especialistas · prompt agents"
    errores = gd.validar_spec(spec)
    assert any("[es] nodo facilitador: «Foundry Agent Service» no aparece junto a su icono" in e for e in errores)
    assert not any("nodo coordinador" in e for e in errores)  # el coordinador lo lleva en su propia etiqueta


def test_icono_usado_sin_nombre_de_servicio_declarado_falla():
    spec = _spec_real()
    del spec["nombre_servicio"]["modelos"]
    assert any("icono modelos: falta su nombre de servicio" in e for e in gd.validar_spec(spec))


def test_terceros_con_forma_neutra_y_sin_icono_de_microsoft():
    """OpenCode, GitHub, GitHub Actions y azd/Bicep no se dibujan con iconos de Microsoft."""
    nodos = {n["id"]: n for n in _spec_real()["nodos"]}
    for nid in ("opencode", "github", "github_actions", "iac"):
        assert nodos[nid]["tipo"] == "neutro" and nodos[nid]["icono"] is None, nid
    assert nodos["opencode"]["estado"] == "validado"


def test_iconos_retirados_por_representar_otro_producto():
    """Dev Console no es OpenCode y Management Portal es el portal de Azure, no el de Foundry."""
    spec = _spec_real()
    rutas = {ic["ruta"] for ic in spec["iconos"].values()}
    assert not any("Dev-Console" in r or "Management-Portal" in r for r in rutas)
    assert next(n for n in spec["nodos"] if n["id"] == "portal")["icono"] == "foundry"


# ----------------------------------------------------------------- subtítulo de grupo y leyenda

def test_el_subtitulo_del_grupo_aparece_en_todas_las_salidas(entorno):
    spec, iconos, _ = entorno
    g = next(g for g in spec["grupos"] if g.get("subtitulo"))
    salidas = gd.generar(spec, iconos)
    for idioma in gd.IDIOMAS:
        assert f">{g['subtitulo'][idioma]}</text>" in salidas[f"arquitectura.{idioma}.svg"]
    assert gd.valor_grupo_drawio(g, "en") == f"{g['titulo']['en']}<br>{g['subtitulo']['en']}"
    # En el fichero el valor HTML va escapado otra vez como atributo XML.
    original = gd.escape(gd.valor_grupo_drawio(g, "es"))
    assert original in salidas["arquitectura.drawio"]
    roto = salidas["arquitectura.drawio"].replace(original, gd.escape(gd.escape(g["titulo"]["es"])))
    assert any(f"el grupo {g['id']} no muestra su título o su subtítulo" in e
               for e in gd.comprueba_drawio(spec, roto, "roto.drawio"))


def test_subtitulo_de_grupo_que_no_cabe_o_vacio_falla():
    spec = _spec_real()
    g = next(g for g in spec["grupos"] if g.get("subtitulo"))
    g["subtitulo"]["es"] = "un subtítulo larguísimo que de ninguna manera cabe en la cabecera del grupo"
    assert any(f"[es] grupo {g['id']}: el título no cabe en su cabecera" in e for e in gd.validar_spec(spec))
    g["subtitulo"]["es"] = " "
    assert any(f"grupo {g['id']}: subtítulo vacío o mal formado" in e for e in gd.validar_spec(spec))


def test_un_nodo_que_pisa_el_subtitulo_del_grupo_falla():
    spec = _spec_real()
    n = next(n for n in spec["nodos"] if n["id"] == "facilitador")
    n["pos"] = [n["pos"][0], n["pos"][1] - 10]
    assert any("nodo facilitador: pisa la cabecera de especialistas" in e for e in gd.validar_spec(spec))


def test_la_leyenda_del_limite_muestra_el_trazo_continuo_y_el_discontinuo():
    svg, ancho = gd.simbolo_leyenda("limite", 0, 10)
    rects = re.findall(r"<rect [^>]*>", svg)
    assert len(rects) == 2 and ancho == gd.ANCHO_SIMBOLO["limite"]
    assert "stroke-dasharray" not in rects[0] and "stroke-dasharray" in rects[1]


def test_la_leyenda_aclara_que_la_marca_del_icono_de_content_safety_no_es_validado():
    """El icono oficial de Content Safety trae una marca verde de serie: la leyenda lo aclara junto al sello."""
    spec = _spec_real()
    if not any(n.get("icono") == "content_safety" for n in spec["nodos"]):
        pytest.skip("el diagrama no usa el icono de Content Safety")
    validado = next(el for el in spec["leyenda"] if el["simbolo"] == "validado")
    for idioma in gd.IDIOMAS:
        assert "Content Safety" in validado[idioma]


def test_el_coordinador_muestra_el_escalado_a_cero_que_cita_su_practica():
    """ESC-04 y REF-15 se apoyan en el escalado a cero del hosted agent: debe verse en el dibujo."""
    spec = _spec_real()
    n = next(n for n in spec["nodos"] if n["id"] == "coordinador")
    assert "escala a cero" in n["etiqueta"]["es"] and "scales to zero" in n["etiqueta"]["en"]
