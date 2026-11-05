"""PPTX de revisión de prueba (forma del contrato §9.1-9.2), para ejercitar verificar_paquete.py.

No es el generador de C: es una réplica mínima y fiel al contrato (10 diapositivas, Montserrat en
latin/ea/cs, colores de la paleta, formas sin estilo de tema, conectores pegados) sobre la que
los tests introducen defectos concretos.
"""
from __future__ import annotations

import pathlib
from decimal import Decimal

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROJO, OSCURO, BLANCO, BANDA, BORDE = "F8485E", "3C3C3A", "FFFFFF", "F2F2F1", "BFBFBF"


# Integrador I1.6: centro (en pulgadas) de cada componente del ejemplo en la diapositiva 4. Integrador I1.9 (VA18-6:
# ningún tramo en la misma línea que otro, a cualquier distancia, y la identidad siempre «servicio → identidad»):
# C-03→C-04 y C-01→C-02 en horizontal (y 3,85 y 5,35), C-04→C-01 en vertical por x 6,67 y C-04→C-05 en vertical por
# x 7,27 (sale de C-04 desplazado sobre su lado de arriba, a 0,6 pulgadas del otro); C-06 sin flujos.
POSICIONES_DIAGRAMA = {"C-03": (2.67, 3.85), "C-04": (6.67, 3.85), "C-01": (6.67, 5.35), "C-02": (10.67, 5.35),
                       "C-05": (7.27, 2.35), "C-06": (2.67, 2.35)}


def eur(x: str | Decimal) -> str:
    """17852.50 -> «17.852,50 EUR»."""
    s = f"{Decimal(str(x)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} EUR"


def fuente(run, color: str = OSCURO, tam: int = 14, negrita: bool = False, cara: str = "Montserrat") -> None:
    run.font.size = Pt(tam)
    run.font.bold = negrita
    run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._r.get_or_add_rPr()
    for etiqueta in ("a:latin", "a:ea", "a:cs"):
        el = rpr.find(qn(etiqueta))
        if el is None:
            el = etree.SubElement(rpr, qn(etiqueta))
        el.set("typeface", cara)


def parrafos(tf, lineas: list[str], color: str = OSCURO, tam: int = 14, negrita: bool = False, cara: str = "Montserrat"):
    tf.clear()
    tf.word_wrap = True
    for n, texto in enumerate(lineas):
        p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
        r = p.add_run()
        r.text = texto
        fuente(r, color, tam, negrita, cara)


def sin_estilo(forma, relleno: str | None, linea: str) -> None:
    """Quita p:style (colores y sombra del tema) y fija relleno y línea explícitos."""
    estilo = forma._element.find(qn("p:style"))
    if estilo is not None:
        forma._element.remove(estilo)
    if relleno is not None:
        forma.fill.solid()
        forma.fill.fore_color.rgb = RGBColor.from_string(relleno)
    forma.line.color.rgb = RGBColor.from_string(linea)


def caja(diapo, x, y, w, h, lineas, **kw):
    tb = diapo.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    parrafos(tb.text_frame, lineas, **kw)
    return tb


def tabla(diapo, filas: list[list[str]], x, y, w, alto_fila=0.4, cara: str = "Montserrat"):
    t = diapo.shapes.add_table(len(filas), len(filas[0]), Inches(x), Inches(y), Inches(w),
                               Inches(alto_fila * len(filas))).table
    for i, fila in enumerate(filas):
        for j, texto in enumerate(fila):
            celda = t.cell(i, j)
            celda.fill.solid()
            celda.fill.fore_color.rgb = RGBColor.from_string(ROJO if i == 0 else (BANDA if i % 2 else BLANCO))
            parrafos(celda.text_frame, [texto], color=BLANCO if i == 0 else OSCURO, tam=11, negrita=i == 0, cara=cara)
    return t


def nueva(prs, titulo: str):
    d = prs.slides.add_slide(prs.slide_layouts[6])
    caja(d, 0.5, 0.3, 12.3, 0.8, [titulo], color=ROJO, tam=26, negrita=True)
    return d


def filas_no_valoradas_fixture(estado: dict, catalogo: dict, resp: dict, nombres: dict, con_precio: set) -> list:
    """REV13-3 (I1.4): una fila «No valorado» por motivo, como nucleo.pptx_revision.filas_no_valoradas. Los
    motivos salen de nucleo.anexo_consumo si existe; si no, «Sin precio publicado» (la puerta no los exige)."""
    import sys
    import verificar_paquete as vp
    try:
        if str(vp.DIR_SANDBOX) not in sys.path:
            sys.path.insert(0, str(vp.DIR_SANDBOX))
        from nucleo import anexo_consumo
        motivo = {x["componente_id"]: x["motivo"] for x in anexo_consumo.no_valorados(estado, catalogo)}
    except ImportError:
        motivo = {}
    lista = [{"servicio": nombres[c["id"]], "motivo": motivo.get(c["id"], "Sin precio publicado")}
             for c in resp["componentes"] if c["id"] not in con_precio]
    return vp.filas_no_valoradas_replica(lista)


def generar(estado: dict, catalogo: dict, ruta: pathlib.Path, firmas: dict | None = None, **op) -> None:
    """Genera el PPTX de revisión desde carga.textos_cliente. `op` introduce defectos de prueba:
    extra={n: [líneas]}, omitir_componente=nombre, cara=fuente, nota=texto, sin_hash=True, tabla_arq=True.
    """
    carga, h = estado["carga"], estado["hash_contenido"]
    tc = carga["textos_cliente"]
    cara = op.get("cara", "Montserrat")
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    pt = tc["portada"]
    d = prs.slides.add_slide(prs.slide_layouts[6])  # portada sin título: solo lo de textos_cliente.portada
    caja(d, 0.5, 2.0, 12, 3, [pt["titulo"], pt["cliente"], (f"Propuesta comercial · versión {estado['version']}"
                                  if estado["estado"] == "APROBADA" else pt["subtitulo"]),
          pt["codigo"], f"Fecha: {pt['fecha']}"],
         cara=cara)
    d = nueva(prs, "Control de versiones")
    f = firmas or {}
    tabla(d, [["Versión", "Fecha", "Elaborado por", "Revisado por", "Aprobado por"],
              [estado["version"], pt["fecha"], "Responsable comercial (RC)",
               f.get("revisado", "Sin firma"), f.get("aprobado", "Sin firma")]], 0.5, 1.5, 12.3)
    if not op.get("sin_hash"):
        caja(d, 0.5, 3.0, 12.3, 0.8, ["Huella del contenido:", h], tam=10)
    d = nueva(prs, "Resumen de la necesidad")
    caja(d, 0.5, 1.3, 12.3, 5.5, [x["texto"] for x in tc["necesidad"]])
    d = nueva(prs, "Arquitectura propuesta")
    cat = {c["id"]: c["nombre_oficial"] for c in catalogo["componentes"]}
    comps = carga["respuestas_expertos"]["azure"]["respuesta"]["componentes"]
    nombres = {c["id"]: cat.get(c["catalogo_id"], c["servicio"]) for c in comps}
    if op.get("tabla_arq"):
        caja(d, 0.5, 1.2, 12, 0.5, ["Diagrama simplificado en tabla"], tam=12)
        tabla(d, [["Capa", "Componente"]] + [[c["capa"].replace("_", " "), nombres[c["id"]]] for c in comps],
              0.5, 1.8, 8)
    else:
        formas, centros = {}, {}
        for n, c in enumerate(comps):
            if nombres[c["id"]] == op.get("omitir_componente"):
                continue
            # Integrador I1.6 (ARR15-2): posiciones fijas para que cada flujo del ejemplo sea un tramo recto horizontal
            # o vertical entre lados enfrentados, sin compartir tramo ni punto y lejos de las demás formas (la puerta
            # ya no admite tramos oblicuos). Antes (I1.5), en elipse con conectores oblicuos.
            cx_, cy_ = POSICIONES_DIAGRAMA.get(c["id"], (2.67 + 2.8 * (n % 4), 5.35))
            s = d.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(cx_ - 1.2), Inches(cy_ - 0.3),
                                   Inches(2.4), Inches(0.6))
            centros[c["id"]] = (cx_, cy_)
            sin_estilo(s, BANDA, BORDE)
            parrafos(s.text_frame, [nombres[c["id"]]], tam=12, cara=cara)
            formas[c["id"]] = s
        capa = {c["id"]: c["capa"] for c in comps}
        for fl in carga["respuestas_expertos"]["azure"]["respuesta"]["flujos"]:
            if fl["origen"] in formas and fl["destino"] in formas:
                o_, d_ = fl["origen"], fl["destino"]
                if capa.get(o_) == "identidad_seguridad_red" and capa.get(d_) != "identidad_seguridad_red":
                    o_, d_ = d_, o_  # I1.9 (VA18-6): la flecha va del servicio a la identidad, como en el núcleo
                cx = d.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 0, 0, Emu(1), Emu(1))
                (ox, oy), (dx_, dy_) = centros[o_], centros[d_]
                if abs(dx_ - ox) / 2.4 >= abs(dy_ - oy) / 0.6:  # sitios: 0 arriba, 1 izquierda, 2 abajo, 3 derecha
                    sitios = (3, 1) if dx_ > ox else (1, 3)
                else:
                    sitios = (2, 0) if dy_ > oy else (0, 2)
                cx.begin_connect(formas[o_], sitios[0])
                cx.end_connect(formas[d_], sitios[1])
                # I1.9 (VA18-6): el extremo inicial se desliza por su lado hasta quedar enfrente del final (recto y sin
                # compartir línea con otro conector del mismo lado); el pegado (stCxn e idx) no cambia
                if sitios[0] in (0, 2) and abs(dx_ - ox) < 1.2:
                    cx.begin_x = cx.end_x  # el mismo EMU que el final: Inches() puede redondear distinto
                elif sitios[0] in (1, 3) and abs(dy_ - oy) < 0.3:
                    cx.begin_y = cx.end_y
                sin_estilo(cx, None, OSCURO)
        if op.get("conector_cruzado") and len(formas) > 1:  # I1.5: pegado, pero atraviesa el texto de su origen
            ids = list(formas)
            cx = d.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 0, 0, Emu(1), Emu(1))
            cx.begin_connect(formas[ids[0]], 1)
            # I1.9: con las posiciones nuevas, el lado izquierdo de C-01 (6,67; 5,35) al de C-02 (10,67; 5,35) cruza en
            # horizontal el texto de su origen (antes, al de ids[len // 2], que ahora queda en la misma vertical)
            destino = next((i for i in ids[1:] if centros[i][1] == centros[ids[0]][1] and centros[i][0] > centros[ids[0]][0]),
                           ids[len(ids) // 2])
            cx.end_connect(formas[destino], 1)
            sin_estilo(cx, None, OSCURO)
    refs = tc["arquitectura"].get("referencias", [])
    pie = caja(d, 0.5, 6.6, 12.3, 0.6, [f"{r['titulo']}: {r['url']}" for r in refs], tam=9)
    pie.name = "Referencias de arquitectura 1"  # integrador I1.7: la puerta busca el pie por su nombre (REVERIF16-3)
    d = nueva(prs, "Alcance y fuera de alcance")
    # como el real (pptx_revision._alcance): cada columna con su título; la puerta lee solo «Incluido» (VA19-1)
    caja(d, 0.5, 1.3, 6, 5.5, ["Incluido"] + [x["texto"] for x in tc["alcance"]], tam=12)
    caja(d, 6.8, 1.3, 6, 5.5, ["Fuera de alcance"] + [x["texto"] for x in tc["fuera_de_alcance"]], tam=12)
    d = nueva(prs, "Supuestos")
    caja(d, 0.5, 1.3, 12.3, 5.5, [f"{x['nivel']}: {x['texto']}" for x in tc["supuestos"]], tam=12)
    d = nueva(prs, "Precio cerrado e hitos")
    pr = tc["precio"]
    caja(d, 0.5, 1.2, 12, 1, [f"Precio cerrado: {eur(pr['precio_cerrado_eur'])}", pr["iva"],
                              f"Duración: {pr['duracion_semanas']} semanas"])
    tabla(d, [["Hito", "%", "Importe"]] + [[x["nombre"], f"{x['porcentaje']} %", eur(x["importe_eur"])]
                                          for x in pr["hitos"]], 0.5, 2.8, 12)
    d = nueva(prs, "Consumo cloud orientativo")
    co = tc["consumo"]
    resp = carga["respuestas_expertos"]["azure"]["respuesta"]
    # Integrador I1.6 (REV15-1, decisión 4): un precio de referencia (cantidad null) no cubre al componente.
    con_precio = {x.get("componente_id") for x in resp.get("precios") or [] if x.get("cantidad_mensual") is not None}
    sin_precio = filas_no_valoradas_fixture(estado, catalogo, resp, nombres, con_precio)
    tabla(d, [["Servicio", "Concepto", "Coste mensual estimado (EUR)"]] +
          [[x["servicio"], x["concepto"], eur(x["coste_mensual_eur"])] for x in co["lineas"]] + sin_precio,
          0.5, 1.3, 12)
    caja(d, 0.5, 4.2, 12, 2, [f"Total mensual: {eur(co['total_mensual_eur'])}",
                              f"Total anual: {eur(co['total_anual_eur'])}", co["fuente"], co["aviso"]], tam=11)
    d = nueva(prs, "Riesgos")
    caja(d, 0.5, 1.3, 12.3, 5.5, [x["texto"] for x in tc["riesgos"]], tam=12)
    d = nueva(prs, "Condiciones")
    caja(d, 0.5, 1.3, 12.3, 5.5, [x["texto"] for x in tc["condiciones"]], tam=12)
    for n, lineas in (op.get("extra") or {}).items():
        caja(prs.slides[n - 1], 0.5, 6.9, 12, 0.4, lineas, tam=9)
    if op.get("nota"):
        prs.slides[0].notes_slide.notes_text_frame.text = op["nota"]
    cp = prs.core_properties
    cp.title, cp.author, cp.last_modified_by = f"{estado['codigo']} · Propuesta para revisión", \
        "Responsable comercial", "Responsable comercial"
    cp.subject, cp.keywords, cp.category, cp.comments = carga["alta"]["titulo"], f"hash_contenido:{h}", "Preventa", ""
    cp.revision = op.get("revision", 1)
    if not op.get("miniatura"):  # como nucleo.pptx_revision.limpiar_paquete: sin la miniatura de la plantilla
        from pptx.opc.constants import RELATIONSHIP_TYPE as RT
        rels = prs.part.package.rels if hasattr(prs.part.package, "rels") else prs.part.package._rels
        for rid, rel in list(rels.items()):
            if rel.reltype == RT.THUMBNAIL:
                rels.pop(rid)
    prs.save(ruta)
