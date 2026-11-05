"""PPTX de revisión de la propuesta (CONTRATOS.md §9.1-§9.3 y §13 P8, P10, P12).

Se crea desde cero con python-pptx, sin plantilla heredada. Todo el texto sale de
`carga.textos_cliente` (compuesto por código a partir de hechos, LES-G-093/094) y la diapositiva 2
de `decision.firmas(estado)`, sin tocar el contenido. Montserrat en cada fragmento, paleta
Devoteam y ningún color de tema sin sustituir (LES-G-072). El diagrama de arquitectura usa formas
nativas: una forma por componente y un conector pegado por flujo; si no se puede completar, cae a
una tabla con aviso (LES-G-062). Nunca horas, jornadas, perfiles ni tarifas (LES-G-053).
"""
from __future__ import annotations

import copy
import os
import pathlib
import re
import tempfile
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

from nucleo import anexo_consumo, decision, errores, hashes, textos_cliente
from nucleo import estado as est_mod

DIAPOSITIVAS: tuple[str, ...] = (
    "Portada",
    "Control de versiones",
    "Resumen de la necesidad",
    "Arquitectura propuesta",
    "Alcance y fuera de alcance",
    "Supuestos",
    "Precio cerrado e hitos",
    "Consumo orientativo en la nube",  # VA18-12 (I1.9): sin «cloud»
    "Riesgos",
    "Condiciones",
)

FUENTE = "Montserrat"
ROJO, OSCURO, BLANCO, BANDA, BORDE = "F8485E", "3C3C3A", "FFFFFF", "F2F2F1", "BFBFBF"
PALETA: frozenset[str] = frozenset({ROJO, OSCURO, BLANCO, BANDA, BORDE})
AUTOR = "Responsable comercial"
AVISO_TABLA = "Diagrama simplificado en tabla"
ANCHO, ALTO = Emu(12192000), Emu(6858000)  # 16:9 (33,867 × 19,05 cm)

# Capas en columnas (de izquierda a derecha) y capas transversales en bandas (abajo).
CAPAS_COLUMNA = ("usuarios_canales", "aplicacion_integracion", "ia", "datos_conocimiento")
CAPAS_BANDA = ("identidad_seguridad_red", "operacion_observabilidad")
TITULOS_CAPA = {
    "usuarios_canales": "Usuarios y canales",
    "aplicacion_integracion": "Aplicación e integración",
    "ia": "Inteligencia artificial",
    "datos_conocimiento": "Datos y conocimiento",
    "identidad_seguridad_red": "Identidad, seguridad y red",
    "operacion_observabilidad": "Operación y observabilidad",
}
MAX_POR_COLUMNA = 5
MAX_POR_BANDA = 6
_RE_ID_COMPONENTE = re.compile(r"^C-[0-9]{2}\Z")
_RE_HASH = re.compile(r"^[0-9a-f]{64}\Z")

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _rgb(hexa: str) -> RGBColor:
    return RGBColor.from_string(hexa)


def formato_eur(importe: str) -> str:
    """«17852.5» o «17852.50» -> «17.852,50 €» (formato español, dos decimales, ROUND_HALF_UP)."""
    try:
        valor = Decimal(str(importe)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise errores.IntegridadRota(f"importe no numérico en textos_cliente: {importe!r}") from exc
    signo = "-" if valor < 0 else ""
    entero, dec = f"{abs(valor):.2f}".split(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return f"{signo}{'.'.join(grupos)},{dec} €"


# ---------------------------------------------------------------------------------------------
# Tema: fuentes y colores del tema sustituidos por Montserrat y la paleta, para que ni siquiera
# lo heredado del patrón de diapositivas salga de la marca.
# ---------------------------------------------------------------------------------------------
_CLR_SCHEME = {
    "dk1": OSCURO, "lt1": BLANCO, "dk2": OSCURO, "lt2": BANDA,
    "accent1": ROJO, "accent2": OSCURO, "accent3": BORDE, "accent4": BANDA,
    "accent5": ROJO, "accent6": OSCURO, "hlink": ROJO, "folHlink": OSCURO,
}


def reescribir_tema(xml: bytes) -> bytes:
    """Devuelve el theme1.xml con el esquema de colores y de fuentes de la marca."""
    raiz = etree.fromstring(xml)
    ns = {"a": _A}
    esquema = raiz.find(".//a:clrScheme", ns)
    if esquema is not None:
        for hijo in list(esquema):
            esquema.remove(hijo)
        esquema.set("name", "Devoteam")
        for nombre, hexa in _CLR_SCHEME.items():
            nodo = etree.SubElement(esquema, f"{{{_A}}}{nombre}")
            etree.SubElement(nodo, f"{{{_A}}}srgbClr").set("val", hexa)
    fuentes = raiz.find(".//a:fontScheme", ns)
    if fuentes is not None:
        fuentes.set("name", "Devoteam")
        for grupo in ("majorFont", "minorFont"):
            nodo = fuentes.find(f"a:{grupo}", ns)
            if nodo is None:
                continue
            for hijo in list(nodo):
                nodo.remove(hijo)
            for etiqueta in ("latin", "ea", "cs"):
                etree.SubElement(nodo, f"{{{_A}}}{etiqueta}").set("typeface", FUENTE)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


# ---------------------------------------------------------------------------------------------
# Texto, formas y tablas con la marca forzada
# ---------------------------------------------------------------------------------------------
def _fuente_run(run, tam: float, negrita: bool, color: str) -> None:
    fuente = run.font
    fuente.size = Pt(tam)
    fuente.bold = negrita
    fuente.color.rgb = _rgb(color)
    fuente.name = FUENTE  # crea a:latin después de a:solidFill (orden OOXML, LES-G-059)
    rpr = run._r.get_or_add_rPr()
    latin = rpr.find(qn("a:latin"))
    for etiqueta in ("a:cs", "a:ea"):
        viejo = rpr.find(qn(etiqueta))
        if viejo is not None:
            rpr.remove(viejo)
    ea = etree.SubElement(rpr, qn("a:ea"))
    ea.set("typeface", FUENTE)
    cs = etree.SubElement(rpr, qn("a:cs"))
    cs.set("typeface", FUENTE)
    latin.addnext(ea)
    ea.addnext(cs)


def _fin_parrafo(parrafo, tam: float, color: str) -> None:
    """endParaRPr con Montserrat y color de la paleta (también los párrafos vacíos)."""
    p = parrafo._p
    viejo = p.find(qn("a:endParaRPr"))
    if viejo is not None:
        p.remove(viejo)
    fin = etree.SubElement(p, qn("a:endParaRPr"))
    fin.set("lang", "es-ES")
    fin.set("sz", str(int(tam * 100)))
    relleno = etree.SubElement(fin, qn("a:solidFill"))
    etree.SubElement(relleno, qn("a:srgbClr")).set("val", color)
    for etiqueta in ("a:latin", "a:ea", "a:cs"):
        etree.SubElement(fin, qn(etiqueta)).set("typeface", FUENTE)


def escribir(marco, lineas, tam: float = 14, negrita: bool = False, color: str = OSCURO,
             alineacion=PP_ALIGN.LEFT, vinetas: bool = False, ancla=MSO_ANCHOR.TOP) -> None:
    """Sustituye el texto del marco por `lineas` (cadena o lista), una por párrafo."""
    if isinstance(lineas, str):
        lineas = [lineas]
    marco.clear()
    marco.word_wrap = True
    marco.vertical_anchor = ancla
    for i, linea in enumerate(lineas):
        parrafo = marco.paragraphs[0] if i == 0 else marco.add_paragraph()
        parrafo.alignment = alineacion
        if vinetas:
            parrafo.space_after = Pt(4)
        run = parrafo.add_run()
        run.text = ("• " if vinetas else "") + str(linea)
        _fuente_run(run, tam, negrita, color)
        _fin_parrafo(parrafo, tam, color)


def _sin_estilo(forma) -> None:
    """Quita p:style (referencias a colores y efectos del tema: sombras incluidas)."""
    estilo = forma._element.find(qn("p:style"))
    if estilo is not None:
        forma._element.remove(estilo)


def caja(diapo, x, y, w, h, texto="", tam=12, relleno: str | None = BLANCO, borde: str | None = BORDE,
         color=OSCURO, negrita=False, forma=MSO_SHAPE.RECTANGLE, alineacion=PP_ALIGN.CENTER,
         ancla=MSO_ANCHOR.MIDDLE, nombre: str | None = None):
    """Autoforma con relleno y borde explícitos de la paleta, sin estilo de tema ni sombra."""
    sh = diapo.shapes.add_shape(forma, x, y, w, h)
    _sin_estilo(sh)
    if relleno is None:
        sh.fill.background()
    else:
        sh.fill.solid()
        sh.fill.fore_color.rgb = _rgb(relleno)
    if borde is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = _rgb(borde)
        sh.line.width = Pt(1)
    if nombre:
        sh.name = nombre
    marco = sh.text_frame
    marco.margin_left = marco.margin_right = Emu(72000)
    escribir(marco, texto, tam, negrita, color, alineacion, ancla=ancla)
    return sh


def texto(diapo, x, y, w, h, lineas, tam=14, negrita=False, color=OSCURO, alineacion=PP_ALIGN.LEFT,
          vinetas=False, ancla=MSO_ANCHOR.TOP):
    """Cuadro de texto sin relleno ni borde."""
    sh = diapo.shapes.add_textbox(x, y, w, h)
    escribir(sh.text_frame, lineas, tam, negrita, color, alineacion, vinetas, ancla)
    return sh


def _borde_celda(tcpr, etiqueta: str) -> None:
    ln = etree.SubElement(tcpr, qn(etiqueta))
    ln.set("w", "9525")
    relleno = etree.SubElement(ln, qn("a:solidFill"))
    etree.SubElement(relleno, qn("a:srgbClr")).set("val", BORDE)


def tabla(diapo, x, y, w, filas: list[list[str]], anchos: list[float], tam=11, alto_fila=Emu(330000),
          derecha: tuple[int, ...] = (), totales: int = 0, margen_v: int | None = None):
    """Tabla con cabecera oscura, bandas claras y bordes grises; sin estilo de tabla del tema.

    `derecha`: columnas alineadas a la derecha (importes); `totales`: últimas filas en negrita;
    `margen_v`: margen superior e inferior de cada celda (EMU) si hay que compactar las filas;
    `alto_fila`: un alto común o la lista con el alto de cada fila.
    """
    nf, nc = len(filas), len(filas[0])
    altos = [Emu(int(a)) for a in alto_fila] if isinstance(alto_fila, (list, tuple)) else [alto_fila] * nf
    if len(altos) != nf:
        raise errores.IntegridadRota(f"tabla: {len(altos)} altos de fila para {nf} filas")
    marco = diapo.shapes.add_table(nf, nc, x, y, w, Emu(sum(altos)))
    tbl = marco.table
    tblpr = tbl._tbl.tblPr
    for atributo in ("firstRow", "bandRow"):
        tblpr.set(atributo, "0")
    for hijo in list(tblpr):
        if hijo.tag == qn("a:tableStyleId"):
            tblpr.remove(hijo)
    total = sum(anchos)
    for j, a in enumerate(anchos):
        tbl.columns[j].width = Emu(int(w * a / total))
    for i, fila in enumerate(filas):
        tbl.rows[i].height = altos[i]
        for j, valor in enumerate(fila):
            celda = tbl.cell(i, j)
            cabecera = i == 0
            fondo = OSCURO if cabecera else (BANDA if i % 2 == 0 else BLANCO)
            negrita = cabecera or i >= nf - totales
            escribir(celda.text_frame, str(valor), tam, negrita, BLANCO if cabecera else OSCURO,
                     PP_ALIGN.RIGHT if j in derecha else PP_ALIGN.LEFT, ancla=MSO_ANCHOR.MIDDLE)
            celda.margin_left = celda.margin_right = Emu(72000)
            if margen_v is not None:
                celda.margin_top = celda.margin_bottom = Emu(margen_v)
            celda.vertical_anchor = MSO_ANCHOR.MIDDLE  # el ancla de una celda vive en tcPr, no en bodyPr
            tcpr = celda._tc.get_or_add_tcPr()
            for hijo in list(tcpr):
                tcpr.remove(hijo)
            for etiqueta in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):  # orden de CT_TableCellProperties
                _borde_celda(tcpr, etiqueta)
            relleno = etree.SubElement(tcpr, qn("a:solidFill"))
            etree.SubElement(relleno, qn("a:srgbClr")).set("val", fondo)
    return marco


# ---------------------------------------------------------------------------------------------
# Diagrama de arquitectura (formas nativas por capas)
# ---------------------------------------------------------------------------------------------
def componentes_de(textos: dict) -> list[dict]:
    """Aplana textos_cliente.arquitectura.capas en [{id, nombre, capa}] en orden de aparición."""
    salida = []
    for capa in (textos.get("arquitectura") or {}).get("capas") or []:
        for comp in capa.get("componentes") or []:
            salida.append({"id": comp.get("id"), "nombre": comp.get("nombre"), "capa": capa.get("capa")})
    return salida


def diagrama_completo(componentes: list[dict], flujos: list[dict]) -> bool:
    """P10 (LES-G-062): ¿se puede dibujar el diagrama entero sin dejar nada fuera?

    Exige ids únicos con forma C-nn, nombre no vacío, capa conocida, cabida en su columna o banda
    y que cada flujo una dos componentes distintos que existen, sin flujos repetidos.
    """
    if not componentes:
        return False
    ids: set[str] = set()
    por_capa: dict[str, int] = {}
    for comp in componentes:
        cid, nombre, capa = comp.get("id"), comp.get("nombre"), comp.get("capa")
        if not isinstance(cid, str) or not _RE_ID_COMPONENTE.match(cid) or cid in ids:
            return False
        if not isinstance(nombre, str) or not nombre.strip() or capa not in TITULOS_CAPA:
            return False
        ids.add(cid)
        por_capa[capa] = por_capa.get(capa, 0) + 1
    for capa, n in por_capa.items():
        if n > (MAX_POR_COLUMNA if capa in CAPAS_COLUMNA else MAX_POR_BANDA):
            return False
    vistos: set[tuple[str, str]] = set()
    for flujo in flujos or []:
        par = (flujo.get("origen"), flujo.get("destino"))
        if par[0] not in ids or par[1] not in ids or par[0] == par[1] or par in vistos:
            return False
        vistos.add(par)
    return True


def _flecha(conector) -> None:
    ln = conector.line._get_or_add_ln()
    for viejo in ln.findall(qn("a:tailEnd")):
        ln.remove(viejo)
    fin = etree.SubElement(ln, qn("a:tailEnd"))
    fin.set("type", "triangle")


def _sitios(a, b) -> tuple[int, int]:
    """Puntos de conexión (0 arriba, 1 izquierda, 2 abajo, 3 derecha) según la posición relativa."""
    ax, ay = a.left + a.width // 2, a.top + a.height // 2
    bx, by = b.left + b.width // 2, b.top + b.height // 2
    if abs(bx - ax) >= abs(by - ay):
        return (3, 1) if bx > ax else (1, 3)
    return (2, 0) if by > ay else (0, 2)


# ARR13-2: la altura de las columnas sale del número de componentes de la capa más poblada y las bandas
# van debajo de esa columna. Si no cabe con las medidas base, se comprime hacia las mínimas; si ni así
# cabe, `comprobar_dibujo` lo declara y el diagrama cae a la tabla (LES-G-062). Medidas en EMU.
CABECERA_COLUMNA = 450000  # título de la capa (330000) más la raya roja y el aire (120000)
# D15-4 (I1.6): «pasillo» es el hueco entre las columnas y la primera banda. Con las medidas base deja tres
# carriles para los conectores que van de una banda a una columna (2 · HOLGURA + 2 · CARRIL y algo de aire);
# con las mínimas es una separación de banda más, así que el alto mínimo no cambia.
MEDIDAS_BASE = {"caja_h": 520000, "caja_sep": 180000, "banda_h": 560000, "banda_sep": 110000, "pasillo": 320000}
MEDIDAS_MIN = {"caja_h": 360000, "caja_sep": 50000, "banda_h": 440000, "banda_sep": 70000, "pasillo": 70000}
ANCHO_MAX_EN_BANDA = 2600000  # un componente solo en su banda no se estira a todo el ancho
PREFIJO_COMPONENTE, PREFIJO_BANDA = "Componente ", "Banda "


def alto_necesario(n_max: int, n_bandas: int, m: dict) -> int:
    """Alto del diagrama con `n_max` cajas en la columna más alta, `n_bandas` bandas y las medidas `m`."""
    columnas = CABECERA_COLUMNA + n_max * m["caja_h"] + (n_max - 1) * m["caja_sep"] if n_max else 0
    pasillo = m.get("pasillo", m["banda_sep"]) - (m["banda_sep"] if n_bandas else 0) if n_max else 0
    return columnas + n_bandas * (m["banda_h"] + m["banda_sep"]) + pasillo


def medidas_diagrama(n_max: int, n_bandas: int, alto: int) -> tuple[dict, bool]:
    """(medidas, cabe): las base si caben en `alto`; si no, comprimidas lo justo hacia las mínimas."""
    base, minimo = alto_necesario(n_max, n_bandas, MEDIDAS_BASE), alto_necesario(n_max, n_bandas, MEDIDAS_MIN)
    if base <= alto:
        return dict(MEDIDAS_BASE), True
    if minimo > alto:
        return dict(MEDIDAS_MIN), False
    t = Decimal(base - alto) / Decimal(base - minimo)
    medidas = {k: int(MEDIDAS_BASE[k] - (t * (MEDIDAS_BASE[k] - MEDIDAS_MIN[k])).to_integral_value(ROUND_HALF_UP))
               for k in MEDIDAS_BASE}
    exceso = alto_necesario(n_max, n_bandas, medidas) - alto  # unos EMU de redondeo, a lo sumo
    if exceso > 0:
        medidas["banda_sep"] = max(MEDIDAS_MIN["banda_sep"], medidas["banda_sep"] - (-(-exceso // max(n_bandas, 1))))
        exceso = alto_necesario(n_max, n_bandas, medidas) - alto
    if exceso > 0 and n_max > 1:
        medidas["caja_sep"] = max(MEDIDAS_MIN["caja_sep"], medidas["caja_sep"] - (-(-exceso // (n_max - 1))))
    return medidas, alto_necesario(n_max, n_bandas, medidas) <= alto


def _compacta(forma, margen: int = 18000) -> None:
    """Márgenes verticales cortos: dos líneas de 10 pt caben en la caja mínima."""
    marco = forma.text_frame
    marco.margin_top = marco.margin_bottom = Emu(margen)


# PR14-3 (I1.5) y ARR15-2/D15-4 (I1.6, LES-G-072): los conectores van en ángulo recto por los huecos entre las
# formas y nunca cortan el texto de ninguna. Además, ningún tramo se solapa con el de otro conector (ni colineal
# ni a menos de SEPARACION), cada conector guarda DISTANCIA con las formas que no une, dos conectores no se cruzan
# a menos de EXTREMO de sus extremos, cada flecha tiene su propio punto de conexión en el lado y no se sale ni se
# entra por el lado contrario a la otra forma si hay otro libre. Rejilla con las coordenadas de los huecos (con
# carriles), Dijkstra con penalización por codo, por cruce, por punto desviado del centro y por lado contrario.
# Todo con enteros: determinista. `separacion_conectores` lo comprueba sobre el XML (la puerta lleva su réplica).
SEPARACION = 60000   # mínimo entre tramos paralelos de dos conectores, y entre dos extremos (EMU)
DISTANCIA = 80000    # mínimo entre un conector y el borde de una forma que no es su origen ni su destino
EXTREMO = 180000     # un cruce entre dos conectores queda al menos a esto de los extremos de los dos
MARGEN_REDONDEO = 2000  # el enrutador deja algo más que la comprobación: los ajustes del codo se redondean
HOLGURA = DISTANCIA + MARGEN_REDONDEO  # aire entre una línea y cualquier forma del diagrama
SALIDA = HOLGURA     # tramo perpendicular con el que la línea sale de su forma y entra en la otra
CARRIL = 72000       # separación entre líneas paralelas que comparten un hueco (más que SEPARACION)
PUERTO = 110000      # separación entre los puntos de conexión candidatos de un mismo lado
MIN_PUERTO = 90000   # dos flechas en un mismo lado, al menos a esto (también la recta, que no va a la rejilla)
ORDENES_EXTRA = 12   # VA18-6 (I1.9): órdenes de enrutado de más, con semilla fija, antes de caer a la tabla
MAX_BUSQUEDAS = 400  # VA18-6 (I1.9): tope de búsquedas de camino por diagrama (unos segundos), contado: determinista
PUNTAS = 200000      # VA18-6 (I1.9): dos puntas de flecha, al menos a esto (tres anchos de punta): se distingue cuál es cuál
RADIO = 16667        # esquina del rectángulo redondeado (ajuste por defecto), en 1/100000 del lado menor
PENAL_CODO, PENAL_CRUCE = 400000, 1500000
PENAL_PUERTO, PENAL_MEZCLA, PENAL_CONTRARIO = 200000, 600000, 5000000
MAX_TRAMOS = 5      # bentConnector5 es el conector en codo con más tramos que trae PowerPoint
PASILLO = 270000    # a cada lado del diagrama, dentro del margen de la diapositiva: una sola columna a todo
                    # el ancho no deja otro hueco por el que rodear (prueba aleatoria de I1.5)
_NORMALES = ((0, -1), (-1, 0), (0, 1), (1, 0))  # sitios 0 arriba, 1 izquierda, 2 abajo, 3 derecha


EMPUJE = 1000  # 0,16 px: lo que se desplaza el extremo final de un camino en U para que tenga ancho o alto


def dibujable(s: tuple, e: tuple, vertical: bool, tramos: int) -> bool:
    """¿Un conector en codo de PowerPoint dibuja un camino ortogonal de `tramos` tramos de s a e que empieza en
    vertical o en horizontal? PowerPoint no admite geometría libre en un conector (abre el PPTX como dañado):
    solo bentConnector2-5, que empiezan en horizontal; para empezar en vertical se usa un primer tramo nulo
    (adj1 = 0), que gasta un tramo. Sus ajustes se miden en proporción al ancho y al alto de la caja del
    conector: un camino en U (ancho o alto nulo) se dibuja desplazando el extremo final EMPUJE EMU (`_empujar`,
    D15-4), así que solo cuenta el número de tramos. `s` y `e` se mantienen por compatibilidad."""
    return 1 <= tramos <= (MAX_TRAMOS - 1 if vertical else MAX_TRAMOS)


def _empujar(puntos: list[tuple]) -> list[tuple]:
    """Si el camino necesita ancho (o alto) y lo tiene nulo, desplaza el extremo final EMPUJE EMU en ese eje:
    hacia atrás por el último tramo si ese tramo corre en ese eje (queda fuera de la forma de destino), o a lo
    largo del lado, con el penúltimo punto, si no. Invisible (0,16 px) y con ajustes enteros y acotados."""
    puntos = [tuple(p) for p in puntos]
    n, vertical = len(puntos) - 1, puntos[0][0] == puntos[1][0]
    for eje in (0, 1):
        necesita = n >= 4 or (n == 3 and (eje == 1) == vertical)
        if not necesita or puntos[-1][eje] != puntos[0][eje]:
            continue
        a, b = list(puntos[-2]), list(puntos[-1])
        if a[1 - eje] == b[1 - eje]:  # el último tramo corre en este eje: se acorta
            b[eje] += EMPUJE if a[eje] > b[eje] else -EMPUJE
        else:  # el último tramo es perpendicular: se desplaza entero, y el anterior se alarga
            a[eje] += EMPUJE
            b[eje] += EMPUJE
        puntos[-2:] = [tuple(a), tuple(b)]
    return puntos


def _codos(puntos: list[tuple]) -> tuple[str, list[int], bool, bool, tuple[int, int, int, int]]:
    """(prst, ajustes, flipH, flipV, (x, y, ancho, alto)) del conector en codo que dibuja la polilínea ortogonal
    `puntos` (de 3 a 6 puntos, tramos alternos). En la caja local el camino va de (0, 0) a (ancho, alto)."""
    vertical, n = puntos[0][0] == puntos[1][0], len(puntos) - 1
    if not dibujable(puntos[0], puntos[-1], vertical, n):
        raise errores.IntegridadRota(f"camino de {n} tramos que ningún conector en codo dibuja: {puntos}")
    puntos = _empujar(puntos)  # un camino en U gana EMPUJE EMU de ancho o de alto
    (sx, sy), (ex, ey) = puntos[0], puntos[-1]
    ancho, alto = abs(ex - sx), abs(ey - sy)
    fh, fv = ex < sx, ey < sy

    def u(x):  # coordenada horizontal local, en 1/100000 del ancho (redondeo exacto y determinista)
        return round(Fraction((x - sx) * (-1 if fh else 1) * 100000, ancho))

    def v(y):
        return round(Fraction((y - sy) * (-1 if fv else 1) * 100000, alto))

    # ajustes en orden: x del primer tramo vertical, y del segundo horizontal, x del segundo vertical
    if vertical:  # primer tramo horizontal nulo (adj1 = 0)
        prst = ("bentConnector3", "bentConnector4", "bentConnector5")[n - 2]
        ajustes = [0] + ([v(puntos[1][1])] if n >= 3 else []) + ([u(puntos[2][0])] if n >= 4 else [])
    else:
        prst = ("bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5")[n - 2]
        ajustes = ([u(puntos[1][0])] if n >= 3 else []) + ([v(puntos[2][1])] if n >= 4 else []) \
            + ([u(puntos[3][0])] if n >= 5 else [])
    return prst, ajustes, fh, fv, (min(sx, ex), min(sy, ey), ancho, alto)


def _rect(forma) -> tuple[int, int, int, int]:
    return int(forma.left), int(forma.top), int(forma.left + forma.width), int(forma.top + forma.height)


def _sitio(r: tuple, k: int) -> tuple[int, int]:
    """Punto de conexión k del rectángulo r = (x0, y0, x1, y1), como lo calcula python-pptx."""
    cx, cy = r[0] + (r[2] - r[0]) // 2, r[1] + (r[3] - r[1]) // 2
    return ((cx, r[1]), (r[0], cy), (cx, r[3]), (r[2], cy))[k]


def _libre(p: tuple, q: tuple, obstaculos) -> bool:
    """¿El tramo horizontal o vertical p-q queda fuera del interior abierto de todos los obstáculos?"""
    for r in obstaculos:
        if p[1] == q[1]:
            if r[1] < p[1] < r[3] and max(min(p[0], q[0]), r[0]) < min(max(p[0], q[0]), r[2]):
                return False
        elif r[0] < p[0] < r[2] and max(min(p[1], q[1]), r[1]) < min(max(p[1], q[1]), r[3]):
            return False
    return True


def _coordenadas(bordes, lo: int, hi: int) -> set[int]:
    """Punto medio entre cada par de bordes consecutivos y, si el hueco da para ello, carriles a los lados."""
    b = sorted({lo, hi, *(v for v in bordes if lo < v < hi)})
    salida: set[int] = set()
    for a, c in zip(b, b[1:]):
        m = (a + c) // 2
        salida.add(m)
        salida.update(m + s * k * CARRIL for k in (1, 2) for s in (-1, 1) if c - a > 2 * k * CARRIL)
    return salida


def _tramo(p: tuple, q: tuple) -> tuple:
    """(orientación, coordenada fija, desde, hasta) de un tramo horizontal o vertical."""
    if p[1] == q[1]:
        return "h", p[1], min(p[0], q[0]), max(p[0], q[0])
    return "v", p[0], min(p[1], q[1]), max(p[1], q[1])


def _inflar(r: tuple, d: int = HOLGURA) -> tuple:
    return r[0] - d, r[1] - d, r[2] + d, r[3] + d


def _util(r: tuple, k: int) -> tuple[int, int]:
    """(coordenada del centro del lado k a lo largo del lado, desvío máximo de un punto de conexión sin entrar
    en la esquina redondeada)."""
    w, h = r[2] - r[0], r[3] - r[1]
    centro = _sitio(r, k)[0 if k % 2 == 0 else 1]
    return centro, max(0, (w if k % 2 == 0 else h) // 2 - min(w, h) * RADIO // 100000 - 20000)


def _puertos(r: tuple, k: int) -> list[tuple[int, tuple[int, int]]]:
    """Puntos de conexión candidatos del lado k de r en orden de preferencia: el centro y, a PUERTO y a
    2·PUERTO, a uno y otro lado. [(coordenada a lo largo del lado, punto)]."""
    centro, util = _util(r, k)
    s = _sitio(r, k)
    return [(centro + o, (s[0] + o, s[1]) if k % 2 == 0 else (s[0], s[1] + o))
            for o in (0, -PUERTO, PUERTO, -2 * PUERTO, 2 * PUERTO) if abs(o) <= util]


def _contrario(r: tuple, k: int, otro: tuple) -> bool:
    """¿El lado k de r mira al lado contrario de la otra forma (que queda entera al otro lado de r)?"""
    return (otro[1] >= r[3], otro[0] >= r[2], otro[3] <= r[1], otro[2] <= r[0])[k]


def _cruces(p: tuple, q: tuple, colocados: list) -> list | None:
    """None si el tramo p-q no se puede usar; si no, [] (los puntos de cruce, que ya no se admiten). VA18-6 (I1.9,
    LES-G-072): no se puede usar si va en la misma línea que un tramo de otro conector (paralelo a menos de
    SEPARACION, a cualquier distancia a lo largo: dos tramos alineados se leen como una sola línea) ni si cruza o toca
    a otro conector en cualquier punto (un cruce sin salto se lee mal; si no hay otro camino, el diagrama cae a la
    tabla). `colocados`: [(puntos, extremos)]. Con un margen de redondeo, como `legibilidad_conectores`."""
    o, c, lo, hi = _tramo(p, q)
    tope, m = SEPARACION + MARGEN_REDONDEO, MARGEN_REDONDEO
    for puntos, _ in colocados:
        for a, b in zip(puntos, puntos[1:]):
            o2, c2, lo2, hi2 = _tramo(a, b)
            if o2 == o:
                if abs(c - c2) < tope:
                    return None  # en la misma línea: comparten tramo o se leen como una sola
            elif lo - m <= c2 <= hi + m and lo2 - m <= c <= hi2 + m:
                return None  # se cruzan o se tocan
    return []


def _choque(p: tuple, q: tuple, colocados: list) -> int | None:
    """Número de cruces del tramo p-q con los conectores ya puestos, o None si no se puede usar (`_cruces`)."""
    puntos = _cruces(p, q, colocados)
    return None if puntos is None else len(puntos)


def _recta(ra: tuple, rb: tuple, infl: list, ocupados: dict, colocados: list) -> tuple | None:
    """Recta entre dos lados enfrentados, sin otra forma cerca ni cruces: la conexión más legible."""
    frente = {2: ra[3] < rb[1], 0: rb[3] < ra[1], 3: ra[2] < rb[0], 1: rb[2] < ra[0]}  # rb al otro lado de ka
    for ka, kb in ((2, 0), (0, 2), (3, 1), (1, 3)):
        if not frente[ka]:
            continue
        (ca, ua), (cb, ub) = _util(ra, ka), _util(rb, kb)
        lo, hi = max(ca - ua, cb - ub), min(ca + ua, cb + ub)
        if lo > hi:
            continue
        medio = (lo + hi) // 2
        candidatos = sorted({c for c, _ in _puertos(ra, ka) + _puertos(rb, kb) if lo <= c <= hi} | {medio},
                            key=lambda c: (abs(c - medio), c))
        otros = [o for o in infl if o not in (_inflar(ra), _inflar(rb))]
        for c in candidatos:
            if any(abs(c - u) < MIN_PUERTO for r, k in ((ra, ka), (rb, kb)) for u, _ in ocupados.get((r, k), ())):
                continue
            p = (c, _sitio(ra, ka)[1]) if ka % 2 == 0 else (_sitio(ra, ka)[0], c)
            q = (c, _sitio(rb, kb)[1]) if ka % 2 == 0 else (_sitio(rb, kb)[0], c)
            if _punta_cerca(q, ocupados):
                continue  # VA18-6: la punta, lejos de las demás
            if _libre(p, q, otros) and _choque(p, q, colocados) == 0:
                return [p, q], (ka, c), (kb, c), abs(q[0] - p[0]) + abs(q[1] - p[1])
    return None


def _punta_cerca(punto: tuple, ocupados: dict) -> bool:
    """VA18-6 (I1.9): ¿hay ya una punta de flecha a menos de PUNTAS (Chebyshov, con margen) de este punto?"""
    return any(max(abs(punto[0] - x[0]), abs(punto[1] - x[1])) < PUNTAS + MARGEN_REDONDEO
               for x in ocupados.get("puntas", ()))


def _extremos(r: tuple, otro: tuple, papel: str, infl: list, limite: tuple, ocupados: dict, colocados: list) -> list:
    """Puntos de conexión libres de r para unirla con `otro`: los tres primeros libres de cada lado, con su coste.
    [(coste, lado, coordenada, punto, fin del tramo de salida)]."""
    propio = _inflar(r)
    otros = [o for o in infl if o != propio]
    salida = []
    for k, (nx, ny) in enumerate(_NORMALES):
        usados = ocupados.get((r, k), ())
        libres = 0
        for rango, (c, s) in enumerate(_puertos(r, k)):
            s2 = (s[0] + nx * SALIDA, s[1] + ny * SALIDA)
            if any(abs(c - u) < MIN_PUERTO for u, _ in usados) or not (limite[0] <= s2[0] <= limite[2]) \
                    or (papel == "llega" and _punta_cerca(s, ocupados)) \
                    or not (limite[1] <= s2[1] <= limite[3]) or not _libre(s, s2, otros) \
                    or _choque(s, s2, colocados) != 0:  # ningún cruce en el tramo de salida: está junto al extremo
                continue
            coste = SALIDA + PENAL_PUERTO * rango + (PENAL_CONTRARIO if _contrario(r, k, otro) else 0) \
                + (PENAL_MEZCLA if any(p != papel for _, p in usados) else 0)
            salida.append((coste, k, c, s, s2))
            libres += 1
            if libres == 3:
                break
    return salida


def _camino(ra: tuple, rb: tuple, infl: list, base: tuple, limite: tuple, ocupados: dict, colocados: list,
            cache: dict) -> tuple | None:
    """Dijkstra por la rejilla de huecos con los puntos de conexión libres de ra y rb. (puntos, (lado, coord) de
    origen, (lado, coord) de destino, coste) o None. Estado: (nodo, dirección, tramos hasta aquí, punto de salida);
    un estado con menos coste y no más tramos domina al resto con el mismo nodo y dirección."""
    import heapq
    inicios = _extremos(ra, rb, "sale", infl, limite, ocupados, colocados)
    finales = _extremos(rb, ra, "llega", infl, limite, ocupados, colocados)
    xs = sorted(base[0] | {e[4][0] for e in inicios + finales})
    ys = sorted(base[1] | {e[4][1] for e in inicios + finales})
    ix, iy = {x: i for i, x in enumerate(xs)}, {y: j for j, y in enumerate(ys)}
    cerca = EXTREMO + MARGEN_REDONDEO

    def valido(i, j):
        clave = ("n", xs[i], ys[j])
        if clave not in cache:
            cache[clave] = not any(r[0] < xs[i] < r[2] and r[1] < ys[j] < r[3] for r in infl)
        return cache[clave]

    cruces_de: dict = {}  # tramo de la rejilla -> puntos donde cruza a los conectores ya puestos (None: prohibido)

    def junto(puntos, extremo):  # ¿algún cruce a menos de EXTREMO de este extremo propio?
        return any(max(abs(c[0] - extremo[0]), abs(c[1] - extremo[1])) < cerca for c in puntos)

    def paso(i, j, d, a):  # (nodo vecino, largo, cruces) o None
        n = (i + _NORMALES[d][0], j + _NORMALES[d][1])
        if not (0 <= n[0] < len(xs) and 0 <= n[1] < len(ys)) or not valido(*n):
            return None
        p, q = (xs[i], ys[j]), (xs[n[0]], ys[n[1]])
        clave = (p + q if p < q else q + p)
        if ("t",) + clave not in cache:
            cache[("t",) + clave] = _libre(p, q, infl)
        if not cache[("t",) + clave]:
            return None
        if clave not in cruces_de:
            cruces_de[clave] = _cruces(p, q, colocados)
        puntos = cruces_de[clave]
        if puntos is None or junto(puntos, inicios[a][3]):
            return None
        return n, abs(q[0] - p[0]) + abs(q[1] - p[1]), len(puntos)

    def cruces_del_camino(estado):  # puntos de cruce del camino que acaba en `estado`
        salida = []
        while not (isinstance(previo[estado], tuple) and previo[estado][0] == "ini"):
            anterior = previo[estado]
            p, q = (xs[anterior[0][0]], ys[anterior[0][1]]), (xs[estado[0][0]], ys[estado[0][1]])
            salida += cruces_de.get(p + q if p < q else q + p) or []
            estado = anterior
        return salida

    metas: dict = {}
    for f, e in enumerate(finales):
        metas.setdefault((ix[e[4][0]], iy[e[4][1]]), []).append(f)
    cola, orden, previo, mejores, vistos = [], 0, {}, {}, set()
    for a, e in enumerate(inicios):
        nodo = (ix[e[4][0]], iy[e[4][1]])
        if valido(*nodo):
            cola.append((e[0], orden, (nodo, e[1], 1, a), ("ini", a)))
            orden += 1
    heapq.heapify(cola)
    hallado = None
    while cola:
        coste, _, estado, de = heapq.heappop(cola)
        if estado[0] == "fin":
            if estado in vistos:
                continue
            previo[estado] = de
            hallado, coste_final = estado, coste
            break
        (i, j), d, tramos_n, a = estado
        clave = ((i, j), d)  # el punto de salida no cuenta: `dibujable` ya no depende de los extremos
        if mejores.get(clave, MAX_TRAMOS + 1) <= tramos_n:
            continue  # dominado: ya salió este nodo, en esta dirección, con menos coste y no más tramos
        mejores[clave] = tramos_n
        previo[estado] = de
        cruces_aqui = None
        for f in metas.get((i, j), []):  # se entra en el destino en sentido contrario a la normal de su lado
            kf = finales[f][1]
            total = tramos_n + (0 if d == (kf + 2) % 4 else 1)
            if d == kf or not dibujable(inicios[a][3], finales[f][3], inicios[a][1] % 2 == 0, total):
                continue  # media vuelta sobre el mismo tramo, o un camino que ningún conector en codo dibuja
            if cruces_aqui is None:
                cruces_aqui = cruces_del_camino(estado)
            if junto(cruces_aqui, finales[f][3]):
                continue  # un cruce junto a la punta de la flecha
            giro = 0 if d == (kf + 2) % 4 else PENAL_CODO
            heapq.heappush(cola, (coste + giro + finales[f][0], orden, ("fin", f, a), estado))
            orden += 1
        for d2 in range(4):
            if d2 == (d + 2) % 4 or (d2 != d and tramos_n >= MAX_TRAMOS):
                continue
            r = paso(i, j, d2, a)
            if r is None:
                continue
            n, largo, cruces = r
            extra = (PENAL_CODO if d2 != d else 0) + PENAL_CRUCE * cruces
            heapq.heappush(cola, (coste + largo + extra, orden, (n, d2, tramos_n + (d2 != d), a), estado))
            orden += 1
    if hallado is None:
        return None
    nodos, estado = [], previo[hallado]
    while not (isinstance(estado, tuple) and estado[0] == "ini"):
        nodos.append(estado[0])
        estado = previo[estado]
    nodos.reverse()
    ini, fin = inicios[hallado[2]], finales[hallado[1]]
    puntos = [ini[3]] + [(xs[i], ys[j]) for i, j in nodos] + [fin[3]]
    limpios = [puntos[0]]
    for p, q in zip(puntos[1:], puntos[2:] + [None]):
        a = limpios[-1]
        if q is not None and ((a[0] == p[0] == q[0]) or (a[1] == p[1] == q[1])):
            continue  # vértice en mitad de un tramo recto
        if p != a:
            limpios.append(p)
    return limpios, (ini[1], ini[2]), (fin[1], fin[2]), coste_final


def enrutar(pares: list[tuple], obstaculos: list[tuple], limite: tuple) -> list:
    """Camino ortogonal de cada par (rect_origen, rect_destino) sin entrar en ningún obstáculo inflado con
    HOLGURA ni salir de `limite` = (x0, y0, x1, y1). Devuelve, por par y en su orden, (puntos, sitio de origen,
    sitio de destino) o None si no hay camino que cumpla las reglas de `separacion_conectores`. Enrutado voraz:
    cada flujo toma la recta entre lados enfrentados o, si no la hay, el camino más barato por la rejilla, y
    evita los tramos, los extremos y los puntos de conexión de los anteriores. Como el orden decide quién se
    queda los huecos, se empieza del más corto al más largo y, si un flujo no encuentra camino, se repite con los
    que fallaron delante (dos veces como mucho); si aun así falta alguno, se prueba lo mismo del más largo al más
    corto, en el orden de la respuesta, en el inverso y en ORDENES_EXTRA órdenes con semilla fija. En cada intento, un
    flujo sin camino puede desplazar a uno ya puesto (el arreglo más barato en que salen los dos; VA18-6). Todo con un
    tope de MAX_BUSQUEDAS búsquedas por diagrama, contado y no medido en tiempo: determinista. Gana el intento con más
    flujos dibujados y, a igualdad, el de menor coste total."""
    infl = [_inflar(r) for r in obstaculos]
    lx0, ly0, lx1, ly1 = limite
    base = (_coordenadas([v for r in infl for v in (r[0], r[2])], lx0, lx1),
            _coordenadas([v for r in infl for v in (r[1], r[3])], ly0, ly1))
    cache: dict = {}  # nodos y tramos libres de obstáculos: no dependen del par ni del orden

    def largo(n):
        (a, b) = pares[n]
        return abs(a[0] + a[2] - b[0] - b[2]) + abs(a[1] + a[3] - b[1] - b[3])

    def poner(n: int, ruta: tuple, ocupados: dict, colocados: list) -> None:
        ra, rb = pares[n]
        puntos, (ka, ca), (kb, cb), _ = ruta
        ocupados.setdefault((ra, ka), []).append((ca, "sale"))
        ocupados.setdefault((rb, kb), []).append((cb, "llega"))
        ocupados.setdefault("puntas", []).append(puntos[-1])  # VA18-6: la punta de la flecha
        colocados.append((puntos, (puntos[0], puntos[-1])))

    busquedas = [0]  # VA18-6: tope contado de búsquedas (MAX_BUSQUEDAS), para que un diagrama imposible no tarde minutos

    def agotado() -> bool:
        return busquedas[0] >= MAX_BUSQUEDAS

    def buscar(n: int, ocupados: dict, colocados: list):
        busquedas[0] += 1
        ra, rb = pares[n]
        return _recta(ra, rb, infl, ocupados, colocados) or _camino(ra, rb, infl, base, limite, ocupados, colocados, cache)

    def estado_sin(rutas: dict, fuera: int) -> tuple[dict, list]:
        ocupados: dict = {}
        colocados: list = []
        for m, ruta in rutas.items():
            if m != fuera:
                poner(m, ruta, ocupados, colocados)
        return ocupados, colocados

    def intento(orden: list) -> tuple[int, int, list]:
        ocupados: dict = {}   # (rect, lado) -> [(coordenada a lo largo del lado, papel)]
        colocados: list = []  # [(puntos, (extremo inicial, extremo final))]
        rutas: dict = {}      # n -> (puntos, (lado, coord) de origen, (lado, coord) de destino, coste), en orden
        for n in orden:
            ruta = buscar(n, ocupados, colocados)
            if ruta is not None:
                poner(n, ruta, ocupados, colocados)
                rutas[n] = ruta
        # VA18-6 (I1.9): rehacer un camino ya puesto. Para cada flujo sin camino, se quita cada uno de los puestos, se busca
        # el que falta y se vuelve a buscar el quitado; de los arreglos en los que salen los dos, el de menor coste total
        # (a igualdad, el primero en orden de colocación). Determinista.
        for n in [k for k in orden if k not in rutas]:
            mejor_arreglo = None
            for m in list(rutas):
                if agotado():
                    break
                ocupados, colocados = estado_sin(rutas, m)
                nueva = buscar(n, ocupados, colocados)
                if nueva is None:
                    continue
                poner(n, nueva, ocupados, colocados)
                otra = buscar(m, ocupados, colocados)
                if otra is not None:
                    candidato = {**{k: v for k, v in rutas.items() if k != m}, n: nueva, m: otra}
                    coste = sum(r[3] for r in candidato.values())
                    if mejor_arreglo is None or coste < mejor_arreglo[0]:
                        mejor_arreglo = (coste, candidato)
            if mejor_arreglo is not None:
                rutas = mejor_arreglo[1]
        salida: list = [None] * len(pares)
        for n, (puntos, (ka, _), (kb, _), _) in rutas.items():
            salida[n] = (puntos, ka, kb)
        return sum(r is None for r in salida), sum(r[3] for r in rutas.values()), salida

    mejor = None
    # VA18-6 (I1.9): sin cruces ni tramos alineados hay menos caminos; además de los dos órdenes por largo, se prueban el
    # de la respuesta, su inverso y ORDENES_EXTRA permutaciones con semilla fija (deterministas) antes de caer a la tabla
    import random
    ordenes = [sorted(range(len(pares)), key=lambda n: (s * largo(n), n)) for s in (1, -1)]
    ordenes += [list(range(len(pares))), list(range(len(pares)))[::-1]]
    azar = random.Random(len(pares))
    for _ in range(ORDENES_EXTRA):
        ordenes.append(azar.sample(range(len(pares)), len(pares)))
    for orden in ordenes:
        if mejor is not None and agotado():
            break
        for _ in range(3):  # el primer intento y dos reintentos con los fallidos delante
            fallos, total, resultado = intento(orden)
            if mejor is None or (fallos, total) < mejor[:2]:
                mejor = (fallos, total, resultado)
            nuevo = [n for n in orden if resultado[n] is None] + [n for n in orden if resultado[n] is not None]
            if not fallos or nuevo == orden:
                break
            orden = nuevo
        if mejor[0] == 0:
            break  # del más corto al más largo da los diagramas más legibles: el otro orden solo si falta alguno
    return mejor[2]


def es_del_cliente(comp: dict) -> bool:
    """I1.9 (PR18-8): ¿el componente es un sistema que ya tiene el cliente? Lo dice su nombre, que compone
    textos_cliente.nombre_en_diagrama y `comprobar_textos` exige igual al de la respuesta."""
    return str(comp.get("nombre") or "").endswith(textos_cliente.SUFIJO_EXISTENTE)


def lineas_caja(comp: dict):
    """Texto de la caja: el nombre; el de un sistema del cliente, en dos párrafos («API REST de RR. HH.» y «(sistema del
    cliente)»), que unidos con un espacio dan el nombre (así lo leen la puerta y `formas_de_arbol`)."""
    nombre = str(comp.get("nombre") or "")
    if es_del_cliente(comp):
        return [nombre[:-len(textos_cliente.SUFIJO_EXISTENTE)], textos_cliente.SUFIJO_EXISTENTE.strip()]
    return nombre


def _si_es_del_cliente(forma, comp: dict) -> None:
    """Un sistema del cliente se dibuja distinto de lo que se propone: relleno gris claro y borde oscuro discontinuo."""
    if es_del_cliente(comp):
        forma.fill.solid()
        forma.fill.fore_color.rgb = _rgb(BANDA)
        forma.line.color.rgb = _rgb(OSCURO)
        forma.line.dash_style = MSO_LINE_DASH_STYLE.DASH


def dibujar_diagrama(diapo, componentes: list[dict], flujos: list[dict], x0, y0, w, h) -> dict:
    """Dibuja columnas y bandas. Devuelve {"formas": {id: forma}, "bandas": [...], "conectores": [...],
    "otras": [...], "limite": (x0, y0, w, h), "fondo": y del borde inferior, "cabe": bool}."""
    columnas = [c for c in CAPAS_COLUMNA if any(k["capa"] == c for k in componentes)]
    bandas = [c for c in CAPAS_BANDA if any(k["capa"] == c for k in componentes)]
    formas: dict[str, object] = {}
    otras: list = []
    figuras_banda: list = []
    n_max = max((sum(1 for k in componentes if k["capa"] == c) for c in columnas), default=0)
    m, cabe = medidas_diagrama(n_max, len(bandas), int(h))
    caja_h, caja_sep, banda_h, sep = (Emu(m[k]) for k in ("caja_h", "caja_sep", "banda_h", "banda_sep"))
    tam_col = 11 if caja_h >= 450000 else 10
    alto_col = n_max * caja_h + max(n_max - 1, 0) * caja_sep
    hueco = Emu(380000)
    n = max(len(columnas), 1)
    col_w = int((w - (n - 1) * hueco) / n)
    titulo_h = Emu(330000)
    for i, capa in enumerate(columnas):
        x = x0 + i * (col_w + hueco)
        otras.append(texto(diapo, x, y0, col_w, titulo_h, TITULOS_CAPA[capa], 11, True, OSCURO,
                           PP_ALIGN.CENTER, ancla=MSO_ANCHOR.BOTTOM))
        otras.append(caja(diapo, x, y0 + titulo_h + Emu(30000), col_w, Emu(36000), relleno=ROJO, borde=None))
        miembros = [k for k in componentes if k["capa"] == capa]
        bloque = len(miembros) * caja_h + (len(miembros) - 1) * caja_sep
        y = y0 + CABECERA_COLUMNA + (alto_col - bloque) // 2  # centrada respecto a la columna más alta
        for comp in miembros:
            formas[comp["id"]] = caja(diapo, x, y, col_w, caja_h, lineas_caja(comp), tam_col,
                                      forma=MSO_SHAPE.ROUNDED_RECTANGLE,
                                      nombre=f"{PREFIJO_COMPONENTE}{len(formas) + 1}")
            _compacta(formas[comp["id"]])
            _si_es_del_cliente(formas[comp["id"]], comp)
            y += caja_h + caja_sep
    yb = y0 + (CABECERA_COLUMNA + alto_col + Emu(m["pasillo"]) if columnas else 0)  # D15-4: carriles
    tam_banda = 10 if banda_h >= 520000 else 9
    for capa in bandas:
        figuras_banda.append(caja(diapo, x0, yb, w, banda_h, "", relleno=OSCURO, borde=None,
                                  nombre=f"{PREFIJO_BANDA}{TITULOS_CAPA[capa]}"))
        etiqueta_w = Emu(2700000)
        otras.append(texto(diapo, x0 + Emu(90000), yb, etiqueta_w, banda_h, TITULOS_CAPA[capa], 11, True,
                           BLANCO, ancla=MSO_ANCHOR.MIDDLE))
        miembros = [k for k in componentes if k["capa"] == capa]
        disp = w - etiqueta_w - Emu(180000)
        cw = min(int((disp - (len(miembros) - 1) * Emu(90000)) / max(len(miembros), 1)), ANCHO_MAX_EN_BANDA)
        cx = x0 + etiqueta_w + Emu(90000)
        for comp in miembros:
            formas[comp["id"]] = caja(diapo, cx, yb + Emu(60000), cw, banda_h - Emu(120000), lineas_caja(comp),
                                      tam_banda, forma=MSO_SHAPE.ROUNDED_RECTANGLE,
                                      nombre=f"{PREFIJO_COMPONENTE}{len(formas) + 1}")
            _compacta(formas[comp["id"]])
            _si_es_del_cliente(formas[comp["id"]], comp)
            cx += cw + Emu(90000)
        yb += banda_h + sep
    # cada banda suma su separación al final; sin bandas, el pasillo queda bajo las columnas (D15-4)
    fondo = yb - sep if bandas else y0 + (CABECERA_COLUMNA + alto_col + Emu(m["pasillo"]) if columnas else 0)
    conectores, sin_camino = [], []
    obstaculos = [_rect(f) for f in formas.values()] + [_rect(o) for o in otras]
    pares = [(_rect(formas[f["origen"]]), _rect(formas[f["destino"]])) for f in flujos or []]
    limite = (int(x0) - PASILLO, int(y0), int(x0 + w) + PASILLO, int(fondo))
    rutas = enrutar(pares, obstaculos, limite) if pares else []
    for k, (flujo, ruta) in enumerate(zip(flujos or [], rutas), start=1):
        a, b = formas[flujo["origen"]], formas[flujo["destino"]]
        if ruta is None:  # sin camino por los huecos: `comprobar_dibujo` lo declara y cae a la tabla
            sin_camino.append(f"{flujo['origen']} → {flujo['destino']}")
            ruta = ([], *_sitios(a, b))
        puntos, sa, sb = ruta
        con = diapo.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 0, 0, 0, 0)
        _sin_estilo(con)
        if len(puntos) >= 2:  # ARR15-2: el punto puede ir desviado del centro del lado (uno propio por flecha)
            _trazado_codos(con, puntos)
            con._connect_begin_to(a, sa)  # pegado sin mover: el trazado ya sale y llega a ese lado
            con._connect_end_to(b, sb)
        else:
            con.begin_connect(a, sa)
            con.end_connect(b, sb)
        con.line.color.rgb = _rgb(ROJO)
        con.line.width = Pt(1.75)
        _flecha(con)
        con.name = f"Flujo {k}"
        conectores.append(con)
    return {"formas": formas, "bandas": figuras_banda, "conectores": conectores, "otras": otras,
            "limite": (int(x0), int(y0), int(w), int(h)), "fondo": int(fondo), "cabe": cabe,
            "sin_camino": sin_camino}


def _trazado_codos(con, puntos: list[tuple]) -> None:
    """Convierte el conector en el conector en codo que dibuja la polilínea `puntos` (véase `_codos`), o en una
    recta («line») si son dos puntos."""
    if len(puntos) == 2:
        (sx, sy), (ex, ey) = puntos
        prst, ajustes, fh, fv = "line", [], ex < sx, ey < sy
        x0, y0, ancho, alto = min(sx, ex), min(sy, ey), abs(ex - sx), abs(ey - sy)
    else:
        prst, ajustes, fh, fv, (x0, y0, ancho, alto) = _codos(puntos)
    sppr = con._element.spPr
    xfrm = sppr.find(qn("a:xfrm"))
    for atributo in ("flipH", "flipV", "rot"):
        xfrm.attrib.pop(atributo, None)
    if fh:
        xfrm.set("flipH", "1")
    if fv:
        xfrm.set("flipV", "1")
    xfrm.find(qn("a:off")).set("x", str(x0))
    xfrm.find(qn("a:off")).set("y", str(y0))
    xfrm.find(qn("a:ext")).set("cx", str(ancho))
    xfrm.find(qn("a:ext")).set("cy", str(alto))
    geo = sppr.find(qn("a:prstGeom"))
    geo.set("prst", prst)
    for hijo in list(geo):
        geo.remove(hijo)
    lista = etree.SubElement(geo, qn("a:avLst"))
    for i, valor in enumerate(ajustes, start=1):
        gd = etree.SubElement(lista, qn("a:gd"))
        gd.set("name", f"adj{i}")
        gd.set("fmla", f"val {valor}")


# Títulos de las bandas: si la diapositiva los pinta, tiene que haber formas «Banda …» que comprobar.
TITULOS_BANDA: tuple[str, ...] = tuple(TITULOS_CAPA[c] for c in CAPAS_BANDA)


def solapes_diagrama(formas: list[tuple]) -> list[str]:
    """ARR13-2 (LES-G-062): ninguna forma de componente tapa a otra ni la tapa una banda.

    `formas`: [(nombre, texto, x, y, ancho, alto)] de cada forma de la diapositiva en orden de dibujo (el
    del árbol de formas: la que va después queda encima). Cuentan las de nombre «Componente …» y «Banda …»:
    - dos componentes no pueden cortarse con área positiva;
    - un componente que corta una banda tiene que estar entero dentro de ella y dibujado después;
    - si hay títulos de banda pero ninguna forma «Banda …», no se puede comprobar: es un fallo.
    Pura y determinista; `verificar_paquete.py` lleva una réplica idéntica. [] si no hay solapes.
    """
    comps, bandas, fallos, titulos = [], [], [], set()
    for z, forma in enumerate(formas):
        nombre, texto_forma = str(forma[0] or ""), str(forma[1] or "")
        if texto_forma in TITULOS_BANDA:
            titulos.add(texto_forma)
        if not nombre.startswith((PREFIJO_COMPONENTE, PREFIJO_BANDA)):
            continue
        geo = forma[2:6]
        if len(geo) != 4 or not all(isinstance(v, int) and not isinstance(v, bool) for v in geo) \
                or geo[2] <= 0 or geo[3] <= 0:
            fallos.append(f"la forma «{nombre}» no tiene una posición y un tamaño válidos")
            continue
        (comps if nombre.startswith(PREFIJO_COMPONENTE) else bandas).append((z, texto_forma or nombre, *geo))

    def corta(a, b) -> bool:
        return min(a[2] + a[4], b[2] + b[4]) > max(a[2], b[2]) and min(a[3] + a[5], b[3] + b[5]) > max(a[3], b[3])

    def dentro(a, b) -> bool:
        return a[2] >= b[2] and a[3] >= b[3] and a[2] + a[4] <= b[2] + b[4] and a[3] + a[5] <= b[3] + b[5]

    for i, a in enumerate(comps):
        for b in comps[i + 1:]:
            if corta(a, b):
                fallos.append(f"la forma «{a[1]}» se solapa con la forma «{b[1]}»")
        for b in bandas:
            if corta(a, b) and not (dentro(a, b) and a[0] > b[0]):
                fallos.append(f"la banda «{b[1]}» tapa o corta la forma «{a[1]}»")
    for i, a in enumerate(bandas):  # revisión independiente (I1.4): una banda tampoco tapa a otra
        for b in bandas[i + 1:]:
            if corta(a, b):
                fallos.append(f"la banda «{a[1]}» se solapa con la banda «{b[1]}»")
    if titulos and not bandas:
        fallos.append(f"hay bandas ({', '.join(sorted(titulos))}) sin forma «{PREFIJO_BANDA}…»: no se puede "
                      "comprobar si tapan algún componente")
    return fallos


def formas_de(diapo) -> list[tuple]:
    """[(nombre, texto, x, y, ancho, alto)] de cada autoforma de la diapositiva en orden de dibujo."""
    return formas_de_arbol(diapo.shapes._spTree)


def formas_de_arbol(arbol) -> list[tuple]:
    """Lo mismo que `formas_de` sobre el árbol de formas (p:spTree) ya localizado."""
    salida = []
    for sp in arbol.iter(qn("p:sp")):
        nv = sp.find(qn("p:nvSpPr") + "/" + qn("p:cNvPr"))
        xfrm = sp.find(".//" + qn("a:xfrm"))
        off = xfrm.find(qn("a:off")) if xfrm is not None else None
        ext = xfrm.find(qn("a:ext")) if xfrm is not None else None
        if nv is None or off is None or ext is None:
            continue
        textos = ["".join(t.text or "" for t in p.iter(qn("a:t"))) for p in sp.iter(qn("a:p"))]
        salida.append((nv.get("name") or "", " ".join(textos).strip(), int(off.get("x", 0)), int(off.get("y", 0)),
                       int(ext.get("cx", 0)), int(ext.get("cy", 0))))
    return salida


def cortes_conectores(raiz) -> list[str]:
    """PR14-3 (LES-G-072): conectores que cortan el texto de una forma. [] si ninguno.

    `raiz`: la diapositiva (p:sld) o su árbol de formas (p:spTree). Zona de texto de cada p:sp con texto: su
    caja menos los márgenes interiores de a:bodyPr (91.440 y 45.720 EMU si no constan). Trazado de cada
    p:cxnSp: recta (prstGeom «line» o «straightConnector1») o codo (bentConnector2 a bentConnector5 con sus
    ajustes «val N»; 50000 si no constan), con sus volteos. Otra geometría (custGeom incluida: PowerPoint no
    la abre en un conector), un giro o un grupo no se pueden comprobar: también son fallo, igual que un número
    o un ajuste mal formado (D16-5: con su motivo, nunca una excepción). Pura y determinista (fracciones
    exactas); verificar_paquete.py lleva una réplica idéntica (CAMBIOS-I17-D).
    """
    from fractions import Fraction
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    arbol = raiz if raiz.tag == f"{p_}spTree" else raiz.find(f"{p_}cSld/{p_}spTree")
    if arbol is None:
        return ["la diapositiva no tiene árbol de formas: no se pueden comprobar los conectores"]
    fallos, zonas, trazados = [], [], []

    def entero(valor, nombre):  # D16-5 (I1.7): solo cifras ASCII, un signo menos y 12 cifras; si no, fallo, nunca excepción
        if isinstance(valor, int) and not isinstance(valor, bool):
            return valor
        texto = valor if isinstance(valor, str) else ""
        cifras = texto[1:] if texto.startswith("-") else texto
        if not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
            fallos.append(f"«{nombre}» tiene un valor que no es un número entero ({valor!r}): no se puede comprobar")
            return None
        return int(texto)

    def caja(el, nombre):
        xf = el.find(f"{p_}spPr/{a_}xfrm")
        off = xf.find(f"{a_}off") if xf is not None else None
        ext = xf.find(f"{a_}ext") if xf is not None else None
        if off is None or ext is None:
            fallos.append(f"«{nombre}» no tiene posición ni tamaño: no se puede comprobar")
            return None
        if xf.get("rot") not in (None, "0"):
            fallos.append(f"«{nombre}» está girada: no se puede comprobar")
            return None
        medidas = [entero(v, nombre) for v in (off.get("x", "0"), off.get("y", "0"), ext.get("cx", "0"), ext.get("cy", "0"))]
        if None in medidas:
            return None
        return (*medidas, xf.get("flipH") in ("1", "true"), xf.get("flipV") in ("1", "true"))

    for el in arbol:
        nv = el.find(f"*/{p_}cNvPr")
        nombre = (nv.get("name") if nv is not None else None) or el.tag.rsplit("}", 1)[-1]
        if el.tag == f"{p_}grpSp":
            fallos.append(f"grupo de formas «{nombre}»: no se pueden comprobar sus conectores")
        elif el.tag == f"{p_}sp":
            texto = " ".join("".join(t.text or "" for t in p.iter(f"{a_}t")) for p in el.iter(f"{a_}p")).strip()
            c = caja(el, nombre) if texto else None
            if c:
                bp = el.find(f"{p_}txBody/{a_}bodyPr")
                ins = [entero(bp.get(k, d), nombre) if bp is not None else d
                       for k, d in (("lIns", 91440), ("tIns", 45720), ("rIns", 91440), ("bIns", 45720))]
                if None in ins:
                    continue
                z = (c[0] + ins[0], c[1] + ins[1], c[0] + c[2] - ins[2], c[1] + c[3] - ins[3])
                if z[0] < z[2] and z[1] < z[3]:
                    zonas.append((texto, z))
        elif el.tag == f"{p_}cxnSp":
            c = caja(el, nombre)
            if not c:
                continue
            x, y, cx, cy, fh, fv = c
            geo = el.find(f"{p_}spPr/{a_}prstGeom")
            tipo = geo.get("prst") if geo is not None and el.find(f"{p_}spPr/{a_}custGeom") is None else None
            adj = {}
            ajustes_malos = []
            for gd in geo.findall(f"{a_}avLst/{a_}gd") if geo is not None else []:
                # D16-5 (I1.7): «val» y un entero de cifras ASCII con un signo menos como mucho y 12 cifras; lo demás
                # (cifras Unicode, «--5», un número desmesurado, una fórmula) es un fallo con su motivo, nunca un ValueError
                partes = (gd.get("fmla") or "").split()
                cifras = (partes[1][1:] if partes[1].startswith("-") else partes[1]) if len(partes) == 2 else ""
                if len(partes) != 2 or partes[0] != "val" or not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
                    ajustes_malos.append(gd.get("fmla"))
                else:
                    adj[gd.get("name")] = int(partes[1])
            if ajustes_malos:
                fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar: un ajuste no es un "
                              f"valor entero fijo ({ajustes_malos[0]!r})")
                continue
            if tipo in ("line", "straightConnector1"):
                local = [(0, 0), (cx, cy)]
            elif tipo in ("bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5"):
                x1 = Fraction(cx * adj.get("adj1", 50000), 100000)
                y2 = Fraction(cy * adj.get("adj2", 50000), 100000)
                x3 = Fraction(cx * adj.get("adj3", 50000), 100000)
                local = {"bentConnector2": [(0, 0), (cx, 0), (cx, cy)],
                         "bentConnector3": [(0, 0), (x1, 0), (x1, cy), (cx, cy)],
                         "bentConnector4": [(0, 0), (x1, 0), (x1, y2), (cx, y2), (cx, cy)],
                         "bentConnector5": [(0, 0), (x1, 0), (x1, y2), (x3, y2), (x3, cy), (cx, cy)]}[tipo]
            else:
                fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar")
                continue
            puntos = [(x + (cx - u if fh else u), y + (cy - v if fv else v)) for u, v in local]
            trazados.append((nombre, puntos))

    def corta(p, q, z) -> bool:  # Liang-Barsky con desigualdades estrictas: interior abierto de z
        lo, hi = Fraction(0), Fraction(1)
        dx, dy = q[0] - p[0], q[1] - p[1]
        for a, b in ((-dx, p[0] - z[0]), (dx, z[2] - p[0]), (-dy, p[1] - z[1]), (dy, z[3] - p[1])):
            if a == 0:
                if b <= 0:
                    return False
            elif a > 0:
                hi = min(hi, Fraction(b) / a)
            else:
                lo = max(lo, Fraction(b) / a)
        return lo < hi

    for nombre, puntos in trazados:
        for texto, z in zonas:
            if any(corta(p, q, z) for p, q in zip(puntos, puntos[1:])):
                fallos.append(f"el conector «{nombre}» corta el texto de la forma «{texto[:60]}»")
    return sorted(set(fallos))


def separacion_conectores(raiz) -> list[str]:
    """ARR15-2/D15-4 (LES-G-072): conectores que se confunden entre sí o van pegados a una forma. [] si ninguno.

    `raiz`: la diapositiva (p:sld) o su árbol de formas (p:spTree). Trazado de cada p:cxnSp como en
    `cortes_conectores`: recta o codo (bentConnector2 a bentConnector5 con sus ajustes «val N») con sus volteos;
    otra geometría, un giro, un grupo o un tramo que no sea horizontal ni vertical no se pueden comprobar y son
    fallo. Distancias de Chebyshov en EMU, con fracciones exactas. Entre cada par de conectores:
    - dos tramos paralelos a menos de 60.000 con un hueco a lo largo menor que 180.000 comparten tramo (si se
      solapan) o van en línea y uno parece prolongar al otro;
    - un cruce o un toque a menos de 180.000 de un extremo de cualquiera de los dos se lee mal;
    - dos extremos a menos de 60.000 comparten punto de conexión.
    Y ningún tramo pasa a menos de 80.000 de la caja de una forma p:sp; su forma de origen (stCxn) solo se exime en
    el tramo de salida y la de destino (endCxn) en el de entrada (REV16-5); las «Banda …» no cuentan porque contienen
    a sus componentes. Cada extremo pegado está en el lado (`idx` 0 arriba, 1 izquierda, 2 abajo, 3 derecha) de su
    forma, a 2.000 como mucho, y un conector sin trazado (longitud nula) es fallo: no se ve. Un número o un ajuste mal
    formado es un fallo con su motivo, nunca una excepción (D16-5). Pura y determinista; verificar_paquete.py lleva
    una réplica idéntica (CAMBIOS-I17-D).
    """
    from fractions import Fraction
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    separacion, distancia, extremo, pegado = 60000, 80000, 180000, 2000
    arbol = raiz if raiz.tag == f"{p_}spTree" else raiz.find(f"{p_}cSld/{p_}spTree")
    if arbol is None:
        return ["la diapositiva no tiene árbol de formas: no se pueden comprobar los conectores"]
    fallos, cajas, trazados = [], [], []

    def entero(valor, nombre):  # D16-5 (I1.7): solo cifras ASCII, un signo menos y 12 cifras; si no, fallo, nunca excepción
        if isinstance(valor, int) and not isinstance(valor, bool):
            return valor
        texto = valor if isinstance(valor, str) else ""
        cifras = texto[1:] if texto.startswith("-") else texto
        if not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
            fallos.append(f"«{nombre}» tiene un valor que no es un número entero ({valor!r}): no se puede comprobar")
            return None
        return int(texto)

    def caja(el, nombre):
        xf = el.find(f"{p_}spPr/{a_}xfrm")
        off = xf.find(f"{a_}off") if xf is not None else None
        ext = xf.find(f"{a_}ext") if xf is not None else None
        if off is None or ext is None:
            fallos.append(f"«{nombre}» no tiene posición ni tamaño: no se puede comprobar")
            return None
        if xf.get("rot") not in (None, "0"):
            fallos.append(f"«{nombre}» está girada: no se puede comprobar")
            return None
        medidas = [entero(v, nombre) for v in (off.get("x", "0"), off.get("y", "0"), ext.get("cx", "0"), ext.get("cy", "0"))]
        if None in medidas:
            return None
        return (*medidas, xf.get("flipH") in ("1", "true"), xf.get("flipV") in ("1", "true"))

    for el in arbol:
        nv = el.find(f"*/{p_}cNvPr")
        nombre = (nv.get("name") if nv is not None else None) or el.tag.rsplit("}", 1)[-1]
        if el.tag == f"{p_}grpSp":
            fallos.append(f"grupo de formas «{nombre}»: no se pueden comprobar sus conectores")
        elif el.tag == f"{p_}sp" and not nombre.startswith("Banda "):
            c = caja(el, nombre)
            if c:
                texto = " ".join("".join(t.text or "" for t in p.iter(f"{a_}t")) for p in el.iter(f"{a_}p")).strip()
                cajas.append((nv.get("id") if nv is not None else None, texto or nombre,
                              (c[0], c[1], c[0] + c[2], c[1] + c[3])))
        elif el.tag == f"{p_}cxnSp":
            c = caja(el, nombre)
            if not c:
                continue
            x, y, cx, cy, fh, fv = c
            geo = el.find(f"{p_}spPr/{a_}prstGeom")
            tipo = geo.get("prst") if geo is not None and el.find(f"{p_}spPr/{a_}custGeom") is None else None
            adj = {}
            ajustes_malos = []
            for gd in geo.findall(f"{a_}avLst/{a_}gd") if geo is not None else []:
                # D16-5 (I1.7): «val» y un entero de cifras ASCII con un signo menos como mucho y 12 cifras; lo demás
                # (cifras Unicode, «--5», un número desmesurado, una fórmula) es un fallo con su motivo, nunca un ValueError
                partes = (gd.get("fmla") or "").split()
                cifras = (partes[1][1:] if partes[1].startswith("-") else partes[1]) if len(partes) == 2 else ""
                if len(partes) != 2 or partes[0] != "val" or not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
                    ajustes_malos.append(gd.get("fmla"))
                else:
                    adj[gd.get("name")] = int(partes[1])
            if ajustes_malos:
                fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar: un ajuste no es un "
                              f"valor entero fijo ({ajustes_malos[0]!r})")
                continue
            if tipo in ("line", "straightConnector1"):
                local = [(0, 0), (cx, cy)]
            elif tipo in ("bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5"):
                x1 = Fraction(cx * adj.get("adj1", 50000), 100000)
                y2 = Fraction(cy * adj.get("adj2", 50000), 100000)
                x3 = Fraction(cx * adj.get("adj3", 50000), 100000)
                local = {"bentConnector2": [(0, 0), (cx, 0), (cx, cy)],
                         "bentConnector3": [(0, 0), (x1, 0), (x1, cy), (cx, cy)],
                         "bentConnector4": [(0, 0), (x1, 0), (x1, y2), (cx, y2), (cx, cy)],
                         "bentConnector5": [(0, 0), (x1, 0), (x1, y2), (x3, y2), (x3, cy), (cx, cy)]}[tipo]
            else:
                fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar")
                continue
            puntos = [(x + (cx - u if fh else u), y + (cy - v if fv else v)) for u, v in local]
            tramos = [(p, q) for p, q in zip(puntos, puntos[1:]) if p != q]
            if any(p[0] != q[0] and p[1] != q[1] for p, q in tramos):
                fallos.append(f"el conector «{nombre}» tiene un tramo que no es horizontal ni vertical: no se puede comprobar")
                continue
            if not tramos:  # revisión independiente (I1.6): un conector de longitud nula no se ve
                fallos.append(f"el conector «{nombre}» no tiene trazado (longitud nula)")
                continue
            pegas = [(etiqueta, punto, e.get("id"), e.get("idx")) for etiqueta, punto, e in
                     (("inicial", puntos[0], el.find(f"{p_}nvCxnSpPr/{p_}cNvCxnSpPr/{a_}stCxn")),
                      ("final", puntos[-1], el.find(f"{p_}nvCxnSpPr/{p_}cNvCxnSpPr/{a_}endCxn"))) if e is not None]
            trazados.append((nombre, puntos[0], puntos[-1], tramos, {g[2] for g in pegas if g[2]}, pegas))

    def tramo(p, q):  # (orientación, coordenada fija, desde, hasta)
        if p[1] == q[1]:
            return "h", p[1], min(p[0], q[0]), max(p[0], q[0])
        return "v", p[0], min(p[1], q[1]), max(p[1], q[1])

    def cheb(a, b):
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

    en_dist, en_ext = (f"{v:,}".replace(",", ".") for v in (distancia, extremo))  # 80.000 y 180.000

    por_id = {id_forma: (texto, r) for id_forma, texto, r in cajas}
    for nombre, _, _, _, _, pegas in trazados:  # revisión independiente (I1.6): el extremo está donde dice estar pegado
        for etiqueta, punto, id_forma, idx in pegas:
            if id_forma not in por_id or idx not in ("0", "1", "2", "3"):
                fallos.append(f"el extremo {etiqueta} del conector «{nombre}» está pegado a una forma o a un punto "
                              "que no existe")
                continue
            texto, r = por_id[id_forma]
            lado = {"0": (r[0], r[1], r[2], r[1]), "1": (r[0], r[1], r[0], r[3]),
                    "2": (r[0], r[3], r[2], r[3]), "3": (r[2], r[1], r[2], r[3])}[idx]
            if max(lado[0] - punto[0], punto[0] - lado[2], lado[1] - punto[1], punto[1] - lado[3],
                   abs(punto[0] - lado[0]) if idx in ("1", "3") else 0,
                   abs(punto[1] - lado[1]) if idx in ("0", "2") else 0) > pegado:
                fallos.append(f"el extremo {etiqueta} del conector «{nombre}» no está en el lado "
                              f"{('de arriba', 'izquierdo', 'de abajo', 'derecho')[int(idx)]} de la forma «{texto[:60]}»")
    for nombre, _, _, tramos, _, pegas in trazados:
        origen = next((g[2] for g in pegas if g[0] == "inicial" and g[2]), None)
        destino = next((g[2] for g in pegas if g[0] == "final" and g[2]), None)
        if origen is not None and origen == destino:  # segunda pasada de la revisión independiente: sin exención que cubra un tramo entero
            fallos.append(f"el conector «{nombre}» une una forma consigo misma: no se puede comprobar")
            continue
        for n, (p, q) in enumerate(tramos):
            for id_forma, texto, r in cajas:
                hueco = max(r[0] - max(p[0], q[0]), min(p[0], q[0]) - r[2], r[1] - max(p[1], q[1]),
                            min(p[1], q[1]) - r[3], 0)
                # REV16-5 (I1.7): la forma de origen solo se exime en el tramo de salida y la de destino en el de entrada;
                # tras salir de su forma, el conector guarda la misma distancia con ella que con cualquier otra
                propia = id_forma is not None and id_forma in (origen, destino)
                if hueco >= distancia or (propia and ((n == 0 and id_forma == origen)
                                                      or (n == len(tramos) - 1 and id_forma == destino))):
                    continue
                fallos.append(f"el conector «{nombre}» vuelve a pasar a menos de {en_dist} EMU de su forma de "
                              f"{'origen' if id_forma == origen else 'destino'} «{texto[:60]}» tras salir de ella" if propia
                              else f"el conector «{nombre}» pasa a menos de {en_dist} EMU de la forma «{texto[:60]}»")
    for i, (n1, i1, f1, t1, _, _) in enumerate(trazados):
        for n2, i2, f2, t2, _, _ in trazados[i + 1:]:
            par = f"los conectores «{n1}» y «{n2}»"
            if any(cheb(a, b) < separacion for a in (i1, f1) for b in (i2, f2)):
                fallos.append(f"{par} comparten punto de conexión")
            for p, q in t1:
                o, c, lo, hi = tramo(p, q)
                for a, b in t2:
                    o2, c2, lo2, hi2 = tramo(a, b)
                    if o == o2 and abs(c - c2) < separacion and max(lo, lo2) < min(hi, hi2) + extremo:
                        fallos.append(f"{par} comparten tramo" if max(lo, lo2) < min(hi, hi2)
                                      else f"{par} van en línea: uno parece prolongar al otro")
                    elif o != o2 and lo <= c2 <= hi and lo2 <= c <= hi2:
                        punto = (c2, c) if o == "h" else (c, c2)
                        if any(cheb(punto, e) < extremo for e in (i1, f1, i2, f2)):
                            fallos.append(f"{par} se cruzan o se tocan a menos de {en_ext} EMU de un extremo")
    return sorted(set(fallos))


def legibilidad_conectores(raiz) -> list[str]:
    """VA18-6 (I1.9, LES-G-072): conectores que se leen mal aunque estén bien pegados. [] si ninguno.

    `raiz`: la diapositiva (p:sld) o su árbol de formas (p:spTree). Trazado de cada p:cxnSp como en
    `separacion_conectores` (recta o codo bentConnector2 a bentConnector5 con sus ajustes «val N» y sus volteos); otra
    geometría, un giro, un grupo, un tramo oblicuo o un número mal formado no se pueden comprobar y son fallo, nunca una
    excepción. Distancias de Chebyshov en EMU, con fracciones exactas. Entre cada par de conectores:
    - dos tramos paralelos a menos de 60.000 van en la misma línea, a cualquier distancia a lo largo (se leen como una
      sola línea, aunque haya hueco entre ellos);
    - dos conectores que se cruzan o se tocan en cualquier punto se leen mal: no hay salto dibujado, así que el núcleo
      cae a la tabla (LES-G-062);
    - dos puntas de flecha (`a:tailEnd` en el extremo final, `a:headEnd` en el inicial, de tipo distinto de «none») a
      menos de 200.000 no se distinguen.
    Pura y determinista; verificar_paquete.py lleva una réplica idéntica (CAMBIOS-I19-D)."""
    from fractions import Fraction
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    separacion, puntas = 60000, 200000
    arbol = raiz if raiz.tag == f"{p_}spTree" else raiz.find(f"{p_}cSld/{p_}spTree")
    if arbol is None:
        return ["la diapositiva no tiene árbol de formas: no se pueden comprobar los conectores"]
    fallos, trazados = [], []

    def entero(valor, nombre):
        if isinstance(valor, int) and not isinstance(valor, bool):
            return valor
        texto = valor if isinstance(valor, str) else ""
        cifras = texto[1:] if texto.startswith("-") else texto
        if not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
            fallos.append(f"«{nombre}» tiene un valor que no es un número entero ({valor!r}): no se puede comprobar")
            return None
        return int(texto)

    for el in arbol:
        nv = el.find(f"*/{p_}cNvPr")
        nombre = (nv.get("name") if nv is not None else None) or el.tag.rsplit("}", 1)[-1]
        if el.tag == f"{p_}grpSp":
            fallos.append(f"grupo de formas «{nombre}»: no se pueden comprobar sus conectores")
            continue
        if el.tag != f"{p_}cxnSp":
            continue
        xf = el.find(f"{p_}spPr/{a_}xfrm")
        off = xf.find(f"{a_}off") if xf is not None else None
        ext = xf.find(f"{a_}ext") if xf is not None else None
        if off is None or ext is None:
            fallos.append(f"«{nombre}» no tiene posición ni tamaño: no se puede comprobar")
            continue
        if xf.get("rot") not in (None, "0"):
            fallos.append(f"«{nombre}» está girada: no se puede comprobar")
            continue
        medidas = [entero(v, nombre) for v in (off.get("x", "0"), off.get("y", "0"), ext.get("cx", "0"), ext.get("cy", "0"))]
        if None in medidas:
            continue
        x, y, cx, cy = medidas
        fh, fv = xf.get("flipH") in ("1", "true"), xf.get("flipV") in ("1", "true")
        geo = el.find(f"{p_}spPr/{a_}prstGeom")
        tipo = geo.get("prst") if geo is not None and el.find(f"{p_}spPr/{a_}custGeom") is None else None
        adj, malos = {}, []
        for gd in geo.findall(f"{a_}avLst/{a_}gd") if geo is not None else []:
            partes = (gd.get("fmla") or "").split()
            cifras = (partes[1][1:] if partes[1].startswith("-") else partes[1]) if len(partes) == 2 else ""
            if len(partes) != 2 or partes[0] != "val" or not (cifras.isascii() and cifras.isdigit()) or len(cifras) > 12:
                malos.append(gd.get("fmla"))
            else:
                adj[gd.get("name")] = int(partes[1])
        if malos:
            fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar: un ajuste no es un "
                          f"valor entero fijo ({malos[0]!r})")
            continue
        if tipo in ("line", "straightConnector1"):
            local = [(0, 0), (cx, cy)]
        elif tipo in ("bentConnector2", "bentConnector3", "bentConnector4", "bentConnector5"):
            x1 = Fraction(cx * adj.get("adj1", 50000), 100000)
            y2 = Fraction(cy * adj.get("adj2", 50000), 100000)
            x3 = Fraction(cx * adj.get("adj3", 50000), 100000)
            local = {"bentConnector2": [(0, 0), (cx, 0), (cx, cy)],
                     "bentConnector3": [(0, 0), (x1, 0), (x1, cy), (cx, cy)],
                     "bentConnector4": [(0, 0), (x1, 0), (x1, y2), (cx, y2), (cx, cy)],
                     "bentConnector5": [(0, 0), (x1, 0), (x1, y2), (x3, y2), (x3, cy), (cx, cy)]}[tipo]
        else:
            fallos.append(f"el conector «{nombre}» tiene una geometría que no se puede comprobar")
            continue
        puntos = [(x + (cx - u if fh else u), y + (cy - v if fv else v)) for u, v in local]
        tramos = [(p, q) for p, q in zip(puntos, puntos[1:]) if p != q]
        if not tramos or any(p[0] != q[0] and p[1] != q[1] for p, q in tramos):
            fallos.append(f"el conector «{nombre}» no tiene un trazado horizontal y vertical que se pueda comprobar")
            continue
        ln = el.find(f"{p_}spPr/{a_}ln")
        flechas = [punto for etiqueta, punto in (("headEnd", puntos[0]), ("tailEnd", puntos[-1]))
                   if ln is not None and ln.find(f"{a_}{etiqueta}") is not None
                   and ln.find(f"{a_}{etiqueta}").get("type", "none") != "none"]
        trazados.append((nombre, tramos, flechas))

    def tramo(p, q):
        if p[1] == q[1]:
            return "h", p[1], min(p[0], q[0]), max(p[0], q[0])
        return "v", p[0], min(p[1], q[1]), max(p[1], q[1])

    en_puntas = f"{puntas:,}".replace(",", ".")
    for i, (n1, t1, f1) in enumerate(trazados):
        for n2, t2, f2 in trazados[i + 1:]:
            par = f"los conectores «{n1}» y «{n2}»"
            if any(max(abs(a[0] - b[0]), abs(a[1] - b[1])) < puntas for a in f1 for b in f2):
                fallos.append(f"{par} tienen las puntas de flecha a menos de {en_puntas} EMU: no se distingue cuál es cuál")
            for p, q in t1:
                o, c, lo, hi = tramo(p, q)
                for a, b in t2:
                    o2, c2, lo2, hi2 = tramo(a, b)
                    if o == o2 and abs(c - c2) < separacion:
                        fallos.append(f"{par} van en la misma línea: se leen como una sola")
                    elif o != o2 and lo <= c2 <= hi and lo2 <= c <= hi2:
                        fallos.append(f"{par} se cruzan o se tocan sin salto")
    return sorted(set(fallos))


def comprobar_dibujo(dibujo: dict, componentes: list[dict], flujos: list[dict]) -> list[str]:
    """Cuenta lo dibujado (una forma por componente con su nombre y un conector pegado por flujo),
    comprueba que cabe en su espacio y que ninguna forma tapa a otra (ARR13-2)."""
    fallos = []
    formas = dibujo["formas"]
    if dibujo.get("cabe") is False or (dibujo.get("limite") and dibujo.get("fondo") is not None
                                       and dibujo["fondo"] > dibujo["limite"][1] + dibujo["limite"][3]):
        fallos.append("el diagrama no cabe en su espacio ni con las medidas mínimas")
    figuras = list(formas.values()) + list(dibujo.get("bandas") or [])
    if figuras:
        arbol = figuras[0]._element.getparent()
        fallos += solapes_diagrama(formas_de_arbol(arbol))
        fallos += cortes_conectores(arbol)  # PR14-3: ningún conector corta el texto de una forma
        fallos += separacion_conectores(arbol)  # ARR15-2/D15-4: ni tramos compartidos ni pegados a una forma
        fallos += legibilidad_conectores(arbol)  # VA18-6: ni en línea, ni cruces, ni puntas juntas
    fallos += [f"el flujo {f} no encuentra un camino por los huecos entre las formas"
               for f in dibujo.get("sin_camino") or []]
    for comp in componentes:
        forma = formas.get(comp["id"])
        if forma is None or " ".join(p.text for p in forma.text_frame.paragraphs) != comp["nombre"]:
            fallos.append(f"componente sin forma o con otro texto: {comp['nombre']}")
    if len(formas) != len(componentes):
        fallos.append(f"formas {len(formas)} != componentes {len(componentes)}")
    if len(dibujo["conectores"]) != len(flujos or []):
        fallos.append(f"conectores {len(dibujo['conectores'])} != flujos {len(flujos or [])}")
    for con, flujo in zip(dibujo["conectores"], flujos or []):
        st = con._element.find(".//" + qn("a:stCxn"))
        en = con._element.find(".//" + qn("a:endCxn"))
        esperado = (str(formas[flujo["origen"]].shape_id), str(formas[flujo["destino"]].shape_id))
        if st is None or en is None or (st.get("id"), en.get("id")) != esperado:
            fallos.append(f"conector {con.name} no pegado por los dos extremos")
    return fallos


def _quitar(formas) -> None:
    for forma in formas:
        el = forma._element
        el.getparent().remove(el)


# ---------------------------------------------------------------------------------------------
# Diapositivas
# ---------------------------------------------------------------------------------------------
MARGEN = Emu(540000)
ANCHO_UTIL = ANCHO - 2 * MARGEN
Y_CUERPO = Emu(1300000)


SUBTITULO_APROBADA = "Propuesta comercial · versión {version}"


def pie(textos: dict) -> str:
    """Pie de las diapositivas 2-10: el mismo en todos los estados (H13), así un cambio de estado
    solo toca la portada y la diapositiva 2, nunca el contenido ni el resto de diapositivas."""
    return f"{textos['codigo']} · {textos['portada']['cliente']}"


def subtitulo_portada(estado: dict, textos: dict) -> str:
    """Subtítulo que se dibuja en la portada según el estado (H13), sin tocar hash_contenido.

    APROBADA ya no es un borrador: «Propuesta comercial · versión X». En cualquier otro estado, el
    subtítulo de textos_cliente («Propuesta para revisión interna · versión X»)."""
    if estado.get("estado") == "APROBADA":
        return SUBTITULO_APROBADA.format(version=estado.get("version") or "")
    return textos["portada"]["subtitulo"]


def _nueva(prs, titulo: str, textos: dict, numero: int):
    diapo = prs.slides.add_slide(prs.slide_layouts[6])
    texto(diapo, MARGEN, Emu(300000), ANCHO_UTIL - Emu(2400000), Emu(650000), titulo, 24, True, OSCURO,
          ancla=MSO_ANCHOR.MIDDLE)
    caja(diapo, MARGEN, Emu(980000), Emu(900000), Emu(54000), relleno=ROJO, borde=None)
    texto(diapo, MARGEN, ALTO - Emu(420000), ANCHO_UTIL - Emu(900000), Emu(300000),
          pie(textos), 9, False, OSCURO, ancla=MSO_ANCHOR.MIDDLE)
    texto(diapo, ANCHO - MARGEN - Emu(900000), ALTO - Emu(420000), Emu(900000), Emu(300000), str(numero), 9,
          True, ROJO, PP_ALIGN.RIGHT, ancla=MSO_ANCHOR.MIDDLE)
    return diapo


def _tam_lista(lineas: list[str], base: float = 16) -> float:
    """Tamaño de letra que cabe: baja con el número de líneas y de caracteres."""
    carga = len(lineas) + sum(len(x) for x in lineas) / 110
    for limite, tam in ((7, base), (10, base - 2), (14, base - 4), (19, base - 5), (25, base - 6)):
        if carga <= limite:
            return tam
    return max(base - 7, 9)


def _portada(prs, textos: dict, subtitulo: str) -> None:
    portada = textos["portada"]
    diapo = prs.slides.add_slide(prs.slide_layouts[6])
    caja(diapo, 0, 0, Emu(420000), ALTO, relleno=ROJO, borde=None)
    caja(diapo, Emu(420000), ALTO - Emu(1500000), ANCHO - Emu(420000), Emu(1500000), relleno=OSCURO, borde=None)
    texto(diapo, Emu(1100000), Emu(1500000), ANCHO - Emu(2200000), Emu(1700000), portada["titulo"], 32, True,
          OSCURO, ancla=MSO_ANCHOR.BOTTOM)
    texto(diapo, Emu(1100000), Emu(3350000), ANCHO - Emu(2200000), Emu(500000), portada["cliente"], 20, False,
          OSCURO)
    texto(diapo, Emu(1100000), Emu(3900000), ANCHO - Emu(2200000), Emu(450000), subtitulo, 16, True,
          ROJO)
    texto(diapo, Emu(1100000), ALTO - Emu(1150000), ANCHO - Emu(2200000), Emu(800000),
          [portada["codigo"], f"Fecha: {portada['fecha']}"], 14, False, BLANCO, ancla=MSO_ANCHOR.MIDDLE)


def _fila_firma(firma: dict | None) -> str:
    if not firma:
        return "Sin firma"
    return f"{firma['nombre']}, {firma['fecha']}"


# VER17-2 (I1.8, LES-G-053): la sección «Cambios pedidos en la revisión anterior» ya no va en ningún PPTX (ni en la
# diapositiva 2, que firma y recibe el cliente): vive solo en la nota del revisor (nota_revision.lineas_cambios_nota),
# y revision_interna_en_pptx comprueba que ningún texto de la revisión interna llega a la presentación.


def _control_versiones(prs, estado: dict, textos: dict, firmas: dict, hash_vigente: str) -> None:
    diapo = _nueva(prs, DIAPOSITIVAS[1], textos, 2)
    elaborado = firmas.get("elaborado") or {}
    if not elaborado.get("nombre"):
        raise errores.IntegridadRota("decision.firmas no devuelve quién elabora la propuesta")
    filas = [["Versión", "Fecha", "Elaborado por", "Revisado por", "Aprobado por"],
             [estado.get("version") or "", elaborado.get("fecha") or textos["portada"]["fecha"],
              f"{elaborado['nombre']} ({elaborado.get('iniciales') or 'RC'})",
              _fila_firma(firmas.get("revisado")), _fila_firma(firmas.get("aprobado"))]]
    tabla(diapo, MARGEN, Y_CUERPO + Emu(200000), ANCHO_UTIL, filas, [1, 1.3, 2.6, 2.4, 2.4], 12, Emu(480000))
    texto(diapo, MARGEN, Y_CUERPO + Emu(1700000), ANCHO_UTIL, Emu(350000), "Huella del contenido:", 12, True)
    texto(diapo, MARGEN, Y_CUERPO + Emu(2050000), ANCHO_UTIL, Emu(400000), hash_vigente, 12, False, OSCURO)
    texto(diapo, MARGEN, Y_CUERPO + Emu(2650000), ANCHO_UTIL, Emu(900000),
          "La huella identifica el contenido técnico y económico de esta versión. Cualquier cambio de "
          "contenido genera una huella nueva y deja sin efecto las firmas anteriores.", 11)


def _textos_de(frases: list[dict]) -> list[str]:
    return [f["texto"] for f in frases or []]


def _necesidad(prs, textos: dict) -> None:
    diapo = _nueva(prs, DIAPOSITIVAS[2], textos, 3)
    lineas = _textos_de(textos["necesidad"])
    # VA19-1 (I1.10): «Capacidades principales» omite la frase del alcance que repite el objetivo (cita R-objetivo), que
    # ya está a la vista en la necesidad; «Incluido» (diap. 5) las lleva todas
    capacidades = [f["texto"] for f in textos["alcance"] or [] if "R-objetivo" not in (f.get("hechos") or [])] \
        or _textos_de(textos["alcance"])  # si todo repite el objetivo, todo (nunca una lista vacía)
    texto(diapo, MARGEN, Y_CUERPO, ANCHO_UTIL, Emu(1900000), lineas, _tam_lista(lineas), vinetas=True)
    texto(diapo, MARGEN, Y_CUERPO + Emu(2050000), ANCHO_UTIL, Emu(380000), "Capacidades principales", 14, True,
          ROJO)
    texto(diapo, MARGEN, Y_CUERPO + Emu(2450000), ANCHO_UTIL, Emu(2600000), capacidades,
          _tam_lista(capacidades, 14), vinetas=True)


CARACTERES_LINEA_REF = 140  # a 9 pt y a todo el ancho útil
ALTO_LINEA_REF = 150000     # una línea de 9 pt (9 pt × 1,2 = 137.160 EMU y algo de aire)
TITULO_REFERENCIAS = "Referencias de arquitectura (documentación oficial de Microsoft)"
NOMBRE_REFERENCIAS = "Referencias de arquitectura"  # prefijo del nombre de cada cuadro del pie (lo busca la puerta)
OPCIONES_PIE = ((1, 9), (2, 9), (1, 8), (2, 8))  # (columnas, puntos), de la más legible a la más compacta
HUECO_COLUMNAS_REF = 300000
MIN_ALTO_DIBUJO = 1000000   # por debajo, ni el diagrama ni la tabla caben: las referencias no se publican a medias


def texto_referencia(ref: dict) -> str:
    """«SharePoint Online: https://…»: el título sin «Documentación oficial de Microsoft sobre» (lo dice el rótulo
    del pie) y la URL entera al final, que es lo que busca `referencias_faltan` (REVERIF16-3)."""
    prefijo = textos_cliente.REFERENCIA.format(tema="")
    titulo = str(ref["titulo"])
    sujeto = titulo[len(prefijo):] if titulo.startswith(prefijo) and len(titulo) > len(prefijo) else titulo
    return f"{sujeto[0].upper()}{sujeto[1:]}: {ref['url']}"


def lineas_referencia(linea: str, caracteres: int) -> int:
    """Líneas que ocupa una referencia: una si cabe; si no, las del sujeto más las de la URL, que PowerPoint baja
    entera a la línea siguiente cuando no cabe tras el sujeto (cota superior: nunca se queda corta)."""
    if len(linea) <= caracteres:
        return 1
    sujeto, _, url = linea.rpartition(" ")
    return -(-len(sujeto) // caracteres) + -(-len(url) // caracteres)


def plan_pie(refs: list[str], n_max: int, n_bandas: int) -> dict:
    """REVERIF16-3: reparto de las referencias del pie sin perder ninguna. La opción más legible con la que el diagrama
    cabe con sus medidas base; si ninguna, la más compacta, que es la que más sitio le deja al comprimirse (si ni así
    cabe con las mínimas, cae a la tabla, LES-G-062). {columnas, tam, grupos, alto_pie, alto_dib, ancho}."""
    planes = []
    for columnas, tam in OPCIONES_PIE:
        if columnas == 2 and len(refs) < 2:
            continue  # una sola referencia no se reparte: la columna estrecha solo le quitaría sitio
        ancho = (ANCHO_UTIL - (columnas - 1) * HUECO_COLUMNAS_REF) // columnas
        caracteres = max(20, CARACTERES_LINEA_REF * 9 * int(ancho) // (tam * int(ANCHO_UTIL)))
        lineas = [lineas_referencia(r, caracteres) for r in refs]
        corte = len(refs)
        if columnas == 2:  # en orden: la primera mitad a la izquierda, la columna más alta lo menor
            corte = min(range(1, len(refs)), key=lambda k: (max(sum(lineas[:k]), sum(lineas[k:])), k))
        grupos = [g for g in (refs[:corte], refs[corte:]) if g] or [[]]
        alto_linea = ALTO_LINEA_REF * tam // 9
        alto_pie = alto_linea * max(max(sum(lineas[:corte]), sum(lineas[corte:])), 1) + 300000
        planes.append({"columnas": len(grupos), "tam": tam, "grupos": grupos, "alto_pie": alto_pie, "ancho": ancho,
                       "alto_dib": int(ALTO - Y_CUERPO - alto_pie - 550000)})
    elegido = next((p for p in planes if alto_necesario(n_max, n_bandas, MEDIDAS_BASE) <= p["alto_dib"]), None)
    # si el diagrama no cabe con sus medidas base, se comprime: la opción del pie que más sitio le deja (las flechas
    # entre cajas apiladas siguen viéndose); a igualdad, la primera, que es la más legible
    return elegido or min(planes, key=lambda p: p["alto_pie"])


def _arquitectura(prs, textos: dict) -> dict:
    """Devuelve {"modo": "diagrama"|"tabla", "fallos": [...]} para la nota y las pruebas (el pie, `plan_pie`)."""
    diapo = _nueva(prs, DIAPOSITIVAS[3], textos, 4)
    arq = textos["arquitectura"]
    componentes = componentes_de(textos)
    flujos = arq.get("flujos") or []
    # VERIF-8 y REVERIF16-3: el título ya viene compuesto en castellano y nombra a sus componentes
    refs = [texto_referencia(r) for r in arq.get("referencias") or []]
    columnas = [c for c in CAPAS_COLUMNA if any(k["capa"] == c for k in componentes)]
    n_max = max((sum(1 for k in componentes if k["capa"] == c) for c in columnas), default=0)
    plan = plan_pie(refs, n_max, sum(1 for c in CAPAS_BANDA if any(k["capa"] == c for k in componentes)))
    if plan["alto_dib"] < MIN_ALTO_DIBUJO:
        raise _fallo(errores.ReglaIncumplida, "el PPTX no se genera: las referencias de arquitectura no caben en la "
                     "diapositiva 4 ni en dos columnas a 8 puntos", [f"{len(refs)} referencias"])
    alto_pie, alto_dib = Emu(plan["alto_pie"]), Emu(plan["alto_dib"])
    y_pie = ALTO - alto_pie - Emu(480000)
    resultado = {"modo": "diagrama", "fallos": []}
    if diagrama_completo(componentes, flujos):
        dibujo = dibujar_diagrama(diapo, componentes, flujos, MARGEN, Y_CUERPO - Emu(100000), ANCHO_UTIL, alto_dib)
        fallos = comprobar_dibujo(dibujo, componentes, flujos)
        if fallos:
            _quitar(list(dibujo["formas"].values()) + dibujo["bandas"] + dibujo["conectores"] + dibujo["otras"])
            resultado = {"modo": "tabla", "fallos": fallos}
        else:  # las referencias siguen al diagrama, nunca por encima de su sitio reservado
            y_pie = min(y_pie, dibujo["fondo"] + Emu(250000))
    else:
        resultado = {"modo": "tabla", "fallos": ["el diagrama no se puede completar (diagrama_completo)"]}
    if resultado["modo"] == "tabla":
        filas = [["Capa", "Componente"]] + [[TITULOS_CAPA.get(c["capa"], str(c["capa"])), str(c["nombre"])]
                                            for c in componentes]
        texto(diapo, MARGEN, Y_CUERPO - Emu(150000), ANCHO_UTIL, Emu(320000), AVISO_TABLA, 12, True, ROJO)
        alto = min(Emu(330000), int(alto_dib / max(len(filas), 1)))
        tabla(diapo, MARGEN, Y_CUERPO + Emu(220000), ANCHO_UTIL, filas, [1, 1.6], 10 if len(filas) > 10 else 11,
              Emu(alto))
    texto(diapo, MARGEN, y_pie, ANCHO_UTIL, Emu(280000), TITULO_REFERENCIAS, 10, True, ROJO)
    for i, grupo in enumerate(plan["grupos"]):
        cuadro = texto(diapo, MARGEN + i * (plan["ancho"] + HUECO_COLUMNAS_REF), y_pie + Emu(270000), Emu(plan["ancho"]),
                       alto_pie - Emu(270000), grupo or [""], plan["tam"])
        cuadro.name = f"{NOMBRE_REFERENCIAS} {i + 1}"
    return resultado


def referencias_faltan(raiz, respuesta: dict) -> list[str]:
    """REVERIF16-3 (LES-G-062): componentes de la respuesta cuya página de referencia no está en el pie de la
    diapositiva 4. [] si están todas.

    `raiz`: la diapositiva (p:sld) o su árbol de formas (p:spTree). Cuenta cada párrafo de las formas p:sp cuyo nombre
    empieza por «Referencias de arquitectura» que termina en una URL https (la de la referencia, entera). Cada
    componente busca la URL de su `referencia_id` sin espacios alrededor ni barra final: si no la encuentra, o no tiene
    referencia, es un fallo; y sin ningún cuadro de referencias, también (no se puede comprobar). Excepción (I1.9, cierre
    D): un recurso que el cliente ya tiene fuera del catálogo (`existente_del_cliente` objeto, `catalogo_id` y
    `referencia_id` null) no tiene página de Learn y no se busca. Pura y determinista; verificar_paquete.py lleva una
    réplica idéntica (CAMBIOS-I17-D, con el cambio de CAMBIOS-I19-D §2.4)."""
    import re as re_
    a_ = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    p_ = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    arbol = raiz if raiz.tag == f"{p_}spTree" else raiz.find(f"{p_}cSld/{p_}spTree")
    if arbol is None:
        return ["la diapositiva no tiene árbol de formas: no se pueden comprobar las referencias"]
    publicadas, cuadros = set(), 0
    for sp in arbol.iter(f"{p_}sp"):
        nv = sp.find(f"{p_}nvSpPr/{p_}cNvPr")
        if nv is None or not (nv.get("name") or "").startswith("Referencias de arquitectura"):
            continue
        cuadros += 1
        for p in sp.iter(f"{a_}p"):
            m = re_.search(r"(https://\S+)$", "".join(t.text or "" for t in p.iter(f"{a_}t")).strip())
            if m:
                publicadas.add(m.group(1).rstrip("/"))
    if not cuadros:
        return ["la diapositiva 4 no tiene el pie «Referencias de arquitectura»: no se puede comprobar que esté la página "
                "de cada componente"]
    refs = {r.get("id"): r for r in respuesta.get("referencias") or [] if isinstance(r, dict)}
    fallos = []
    for comp in respuesta.get("componentes") or []:
        if not isinstance(comp, dict):
            continue
        if isinstance(comp.get("existente_del_cliente"), dict) and comp.get("catalogo_id") is None \
                and comp.get("referencia_id") is None:
            continue
        clave = str((refs.get(comp.get("referencia_id")) or {}).get("url") or "").strip().rstrip("/")
        if not clave:
            fallos.append(f"el componente {comp.get('id')} no tiene una referencia con URL en la respuesta")
        elif clave not in publicadas:
            fallos.append(f"falta en el pie de la diapositiva 4 la página del componente {comp.get('id')} ({clave})")
    return sorted(set(fallos))


def _alcance(prs, textos: dict) -> None:
    diapo = _nueva(prs, DIAPOSITIVAS[4], textos, 5)
    mitad = int((ANCHO_UTIL - Emu(400000)) / 2)
    incluidas, excluidas = _textos_de(textos["alcance"]), _textos_de(textos["fuera_de_alcance"])
    tam = min(_tam_lista(incluidas), _tam_lista(excluidas))
    for i, (titulo, lineas) in enumerate((("Incluido", incluidas), ("Fuera de alcance", excluidas))):
        x = MARGEN + i * (mitad + Emu(400000))
        caja(diapo, x, Y_CUERPO, mitad, Emu(420000), titulo, 14, relleno=OSCURO if i == 0 else ROJO, borde=None,
             color=BLANCO, negrita=True)
        texto(diapo, x, Y_CUERPO + Emu(520000), mitad, ALTO - Y_CUERPO - Emu(1100000), lineas, tam, vinetas=True)


def _supuestos(prs, textos: dict) -> None:
    diapo = _nueva(prs, DIAPOSITIVAS[5], textos, 6)
    supuestos = textos.get("supuestos") or []
    filas = [["Supuesto", "Nivel"]] + [[s["texto"], s["nivel"]] for s in supuestos]
    if len(filas) == 1:
        filas.append(["No se han declarado supuestos adicionales.", ""])
    disponible = ALTO - Y_CUERPO - Emu(700000)
    alto = Emu(min(520000, int(disponible / len(filas))))
    tam = 12 if len(filas) <= 8 else (10 if len(filas) <= 14 else 8)
    tabla(diapo, MARGEN, Y_CUERPO, ANCHO_UTIL, filas, [5, 1.2], tam, alto)


def _precio(prs, textos: dict) -> None:
    diapo = _nueva(prs, DIAPOSITIVAS[6], textos, 7)
    precio = textos["precio"]
    caja(diapo, MARGEN, Y_CUERPO, Emu(4300000), Emu(1250000),
         ["Precio cerrado", formato_eur(precio["precio_cerrado_eur"])], 24, relleno=OSCURO, borde=None,
         color=BLANCO, negrita=True)
    texto(diapo, MARGEN + Emu(4600000), Y_CUERPO + Emu(150000), Emu(5000000), Emu(1000000),
          [precio["iva"], f"Duración: {precio['duracion_semanas']} semanas"], 16, ancla=MSO_ANCHOR.MIDDLE)
    filas = [["Hito", "%", "Importe"]] + [[h["nombre"], f"{h['porcentaje']} %", formato_eur(h["importe_eur"])]
                                          for h in precio["hitos"]]
    filas.append(["Total", "100 %", formato_eur(precio["precio_cerrado_eur"])])
    tabla(diapo, MARGEN, Y_CUERPO + Emu(1550000), ANCHO_UTIL, filas, [5, 1, 1.6], 12, Emu(400000),
          derecha=(1, 2), totales=1)


ANCHOS_CONSUMO = (2.2, 2.6, 1.6)


def _lineas_celda(valor: str, ancho: int, tam: int) -> int:
    """Líneas que ocupa un texto en una celda: unos 0,6 em por carácter de Montserrat, menos los márgenes."""
    por_linea = max(1, int((ancho - 144000) / (tam * 12700 * 0.6)))
    return max(1, -(-len(valor) // por_linea))


def medidas_consumo(filas: list[list[str]]) -> tuple[int, list[int], int | None]:
    """(tamaño de letra, alto de cada fila, margen vertical) de la tabla de la diapositiva 8.

    PowerPoint no encoge una fila por debajo de su texto (líneas × letra × 1,25 más los márgenes): si el
    alto repartido no llega, la tabla crece y tapa la fuente y el aviso (visto en el render de I1.4). Se
    compacta (márgenes cortos, 9 y 8 pt) y, si ni así cabe, falla en alto (P-6)."""
    disponible = ALTO - Y_CUERPO - Emu(1900000)
    anchos = [int(ANCHO_UTIL * a / sum(ANCHOS_CONSUMO)) for a in ANCHOS_CONSUMO]
    reparto = min(400000, int(disponible / len(filas)))
    primero = 12 if len(filas) <= 9 else (10 if len(filas) <= 13 else 9)
    for tam, margen in ((primero, None), (9, 18000), (8, 18000)):
        linea, m = int(tam * 12700 * 1.25), (45720 if margen is None else margen)
        justos = [max(_lineas_celda(str(v), a, tam) for v, a in zip(fila, anchos)) * linea + 2 * m for fila in filas]
        holgados = [max(reparto, j) for j in justos]  # el aire de antes, si cabe; si no, el alto justo
        for altos in (holgados, justos):
            if sum(altos) <= disponible:
                return tam, altos, margen
    raise _fallo(errores.ReglaIncumplida, "el PPTX no se genera: la tabla de consumo no cabe en la diapositiva 8",
                 [f"{len(filas)} filas, ni con letra de 8 pt"])


def filas_no_valoradas(sin_precio: list[dict]) -> list[list[str]]:
    """Una fila por motivo con sus servicios («A, B y C»), en el orden de `no_valorados` (REV13-3, H9).

    Antes iba una fila por servicio: con veinte componentes, la tabla no cabía. El anexo XLSX, el JSON y
    la nota siguen con una línea por servicio."""
    grupos: dict[str, list[str]] = {}
    for x in sin_precio:
        grupos.setdefault(x["motivo"], []).append(x["servicio"])
    return [[textos_cliente.lista_y(nombres), motivo, anexo_consumo.NO_VALORADO] for motivo, nombres in grupos.items()]


def _consumo(prs, textos: dict, sin_precio: list[dict]) -> None:
    """Tabla del anexo; los componentes sin precio van en filas «No valorado» agrupadas por motivo, después
    de las líneas con precio y antes de los totales, que no los suman (H9, LES-G-062)."""
    diapo = _nueva(prs, DIAPOSITIVAS[7], textos, 8)
    consumo = textos["consumo"]
    filas = [["Servicio", "Concepto", "Coste mensual estimado (EUR)"]]
    filas += [[x["servicio"], x["concepto"], formato_eur(x["coste_mensual_eur"])] for x in consumo["lineas"]]
    filas += filas_no_valoradas(sin_precio)
    mensual, anual = textos_cliente.etiquetas_total(bool(sin_precio))  # I1.6: el total no suma lo no valorado
    filas.append([mensual, "", formato_eur(consumo["total_mensual_eur"])])
    filas.append([anual, "", formato_eur(consumo["total_anual_eur"])])
    tam, altos, margen_v = medidas_consumo(filas)
    tabla(diapo, MARGEN, Y_CUERPO, ANCHO_UTIL, filas, list(ANCHOS_CONSUMO), tam, altos,
          derecha=(2,), totales=2, margen_v=margen_v)
    y = Y_CUERPO + sum(altos) + Emu(200000)
    texto(diapo, MARGEN, y, ANCHO_UTIL, Emu(450000), consumo["fuente"], 11)
    caja(diapo, MARGEN, y + Emu(520000), ANCHO_UTIL, Emu(420000), consumo["aviso"], 12, relleno=BANDA, borde=None,
         negrita=True, alineacion=PP_ALIGN.LEFT)


def _lista(prs, numero: int, textos: dict, clave: str, vacio: str) -> None:
    diapo = _nueva(prs, DIAPOSITIVAS[numero - 1], textos, numero)
    lineas = _textos_de(textos.get(clave)) or [vacio]
    texto(diapo, MARGEN, Y_CUERPO, ANCHO_UTIL, ALTO - Y_CUERPO - Emu(600000), lineas, _tam_lista(lineas),
          vinetas=True)


# ---------------------------------------------------------------------------------------------
# Comprobaciones previas, barrido final y generación
# ---------------------------------------------------------------------------------------------
def _fallo(clase, mensaje: str, lista: list[str] | None = None):
    """Instancia una excepción de nucleo.errores con su lista de errores (fail loudly, P-6)."""
    try:
        exc = clase(mensaje, list(lista or []))
    except TypeError:
        exc = clase(mensaje)
    if not getattr(exc, "errores", None):
        try:
            exc.errores = list(lista or [])
        except AttributeError:
            pass
    return exc


def hechos_de(carga: dict) -> dict:
    """Objeto cuya huella es textos_cliente.hash_hechos (CONTRATOS.md §9.4)."""
    return {
        "alta": carga.get("alta"),
        "requisitos": carga.get("requisitos"),
        "respuestas_expertos": carga.get("respuestas_expertos"),
        "verificacion": carga.get("verificacion"),
        "anexo_consumo": carga.get("anexo_consumo"),
        "estimacion_resumen": (carga.get("estimacion") or {}).get("resumen"),
    }


def comprobar_textos(estado: dict, catalogo: dict) -> tuple[dict, str]:
    """Devuelve (textos_cliente, hash_contenido vigente) o lanza IntegridadRota con TODOS los motivos."""
    carga = estado.get("carga") or {}
    textos = carga.get("textos_cliente")
    if not isinstance(textos, dict) or not textos:
        raise _fallo(errores.IntegridadRota, "falta carga.textos_cliente: hay que ejecutar estimar antes")
    motivos = []
    hash_vigente = hashes.hash_contenido(estado)
    if estado.get("hash_contenido") != hash_vigente:
        motivos.append(f"hash_contenido guardado {estado.get('hash_contenido')} != recalculado {hash_vigente}")
    if textos.get("hash_hechos") != hashes.hash_json(hechos_de(carga)):
        motivos.append("textos_cliente.hash_hechos no cuadra con los hechos de carga: el texto no es el comprobado")
    codigo = estado.get("codigo")
    if textos.get("codigo") != codigo or (textos.get("portada") or {}).get("codigo") != codigo:
        motivos.append(f"el código de textos_cliente no es el del estado ({codigo})")
    respuesta = est_mod.registro_de_carga(carga).get("respuesta") or {}
    por_id = {c.get("id"): c for c in respuesta.get("componentes") or []}
    oficiales = {c.get("id"): c.get("nombre_oficial") for c in (catalogo or {}).get("componentes") or []}
    campos = (carga.get("requisitos") or {}).get("campos") or {}
    dibujados = componentes_de(textos)
    if sorted(c["id"] for c in dibujados) != sorted(por_id):
        motivos.append("los componentes del diagrama no son los de la respuesta del experto (P11)")
    for comp in dibujados:
        origen = por_id.get(comp["id"])
        if origen is None:
            continue
        cat = origen.get("catalogo_id")
        if cat is not None and cat not in oficiales:
            motivos.append(f"{comp['id']}: catalogo_id {cat} no está en el catálogo montado")
            continue
        # I1.9: el oficial (LES-G-093) o, si es un sistema que ya tiene el cliente, el que compone nombre_en_diagrama
        try:
            esperado = textos_cliente.nombre_en_diagrama(origen, campos, oficiales)
        except errores.IntegridadRota as e:
            motivos.append(str(e))
            continue
        if comp["nombre"] != esperado:
            motivos.append(f"{comp['id']}: el nombre «{comp['nombre']}» no es el esperado «{esperado}» (LES-G-093)")
    if motivos:
        raise _fallo(errores.IntegridadRota, "el PPTX no se genera: textos_cliente no cuadra", motivos)
    return textos, hash_vigente


def perfiles_de(estado: dict) -> list[str]:
    """Perfiles de la tarifa que constan en el estado (brief y estimación), para el barrido."""
    carga = estado.get("carga") or {}
    vistos: list[str] = []
    for brief in carga.get("briefs") or []:
        vistos.extend(brief.get("perfiles_permitidos") or [])
    resumen = (carga.get("estimacion") or {}).get("resumen") or {}
    vistos.extend(p.get("perfil") for p in resumen.get("por_perfil") or [] if p.get("perfil"))
    return sorted(set(vistos))


def textos_pptx(prs) -> list[tuple[str, str]]:
    """[(ubicación, texto)] de cada párrafo de formas y tablas, notas y propiedades del documento."""
    salida: list[tuple[str, str]] = []
    for n, diapo in enumerate(prs.slides, start=1):
        for forma in diapo.shapes:
            marcos = []
            if forma.has_text_frame:
                marcos.append(forma.text_frame)
            if getattr(forma, "has_table", False) and forma.has_table:
                marcos.extend(c.text_frame for fila in forma.table.rows for c in fila.cells)
            for marco in marcos:
                for p in marco.paragraphs:
                    if p.text:
                        salida.append((f"diapositiva {n}", p.text))
        if diapo.has_notes_slide:
            salida.append((f"notas {n}", diapo.notes_slide.notes_text_frame.text))
    cp = prs.core_properties
    for campo in ("title", "author", "last_modified_by", "subject", "comments", "category"):
        salida.append((f"propiedad {campo}", getattr(cp, campo) or ""))
    return salida


def barrido(prs, perfiles: list[str], hash_vigente: str) -> list[str]:
    """§9.3 y P9 sobre lo generado. Solo se exime el hash de la diapositiva 2 (y keywords)."""
    hallazgos = []
    for donde, valor in textos_pptx(prs):
        if donde == "diapositiva 2" and valor == hash_vigente:
            continue
        for h in textos_cliente.barrer(valor, perfiles) + textos_cliente.marcadores(valor):
            hallazgos.append(f"{donde}: {h} en «{valor[:80]}»")
    return sorted(set(hallazgos))


def partes_de(prs) -> dict:
    """{nombre de la parte: bytes} del PPTX tal como se guardaría (para revision_interna_en_pptx)."""
    import io
    import zipfile
    buffer = io.BytesIO()
    prs.save(buffer)
    with zipfile.ZipFile(buffer) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def revision_interna_en_pptx(partes: dict, estado: dict, catalogo: dict) -> list[str]:
    """VER17-2 (I1.8, LES-G-053): texto de la revisión interna que aparece en el PPTX; [] si no hay ninguno.

    `partes`: {nombre de la parte: bytes} del ZIP del PPTX. Recorre cada párrafo de las diapositivas (en el orden de
    presentation.xml), de las notas y de los comentarios, y cada valor de docProps. Busca: (1) el comentario de
    cualquier decisión del estado, entero (16 caracteres o más) o un tramo de 30 o más, sin contar lo que el revisor
    cita entre «» o comillas (es texto del propio documento); (2) el nombre de quien decide (los tres firmantes y los
    del estado); (3) los identificadores del catálogo (`catalogo_id`, las plantillas con guion y cualquier «az-…»);
    (4) los marcadores de la revisión interna: ids y tipos de decisión, rótulos de la sección de cambios, «calculadas
    por el código», «nota del revisor» y nombres de campos internos. LISTA BLANCA (lo único que sí puede salir): en la
    fila 2 de la tabla de la diapositiva 2, columnas 3 a 5, «<firmante> (<iniciales>)», «<firmante>, AAAA-MM-DD» o
    «Sin firma»; creator y lastModifiedBy de docProps/core.xml iguales a un firmante; keywords igual a
    «hash_contenido:<64 hex>»; y las URL de learn.microsoft.com no se miran por identificadores (son las referencias
    oficiales). Autónoma (biblioteca estándar y lxml): la puerta la lleva copiada (CAMBIOS-I18-D.md), y una parte que
    falte o no se pueda leer lanza la excepción (quien llama falla en alto, nunca da el PPTX por limpio)."""
    import re
    import unicodedata
    from lxml import etree

    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)

    def plano(t):
        t = unicodedata.normalize("NFD", unicodedata.normalize("NFC", str(t or "")))
        return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).lower().strip()

    def xml(nombre):
        return etree.fromstring(partes[nombre], parser)

    def parrafos(raiz):  # [((fila, columna) si está en una tabla, o None; texto del párrafo)]
        salida = []
        for par in raiz.iter(f"{{{ns_a}}}p"):
            texto = "".join((el.text or "") if el.tag == f"{{{ns_a}}}t" else " "  # Revisión I1.8: a:br separa palabras
                            for el in par.iter(f"{{{ns_a}}}t", f"{{{ns_a}}}br"))
            if not texto.strip():
                continue
            tc = next(par.iterancestors(f"{{{ns_a}}}tc"), None)
            celda = None
            if tc is not None:
                tr = tc.getparent()
                celda = (list(tr.getparent().iterchildren(f"{{{ns_a}}}tr")).index(tr) + 1,
                         list(tr.iterchildren(f"{{{ns_a}}}tc")).index(tc) + 1)
            salida.append((celda, texto))
        return salida

    textos = []  # (dónde, celda, texto)
    destino = {r.get("Id"): r.get("Target")
               for r in xml("ppt/_rels/presentation.xml.rels").iter(f"{{{ns_rel}}}Relationship")}
    for n, sld in enumerate(xml("ppt/presentation.xml").iter(f"{{{ns_p}}}sldId"), 1):
        parte = "ppt/" + destino[sld.get(f"{{{ns_r}}}id")].lstrip("/").removeprefix("ppt/")
        textos += [(f"diapositiva {n}", celda, t) for celda, t in parrafos(xml(parte))]
    # VPROT-1 (I1.9): también el texto alternativo (descr y title de cada cNvPr), que lee un lector de pantalla, de las
    # diapositivas, los diseños y los patrones, y los párrafos de los diseños y patrones, que se dibujan en la diapositiva
    for nombre in sorted(partes):
        diseno = re.fullmatch(r"ppt/(?:slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml", nombre)
        if not (diseno or re.fullmatch(r"ppt/slides/slide\d+\.xml", nombre)):
            continue
        for el in xml(nombre).iter():
            if isinstance(el.tag, str) and etree.QName(el).localname == "cNvPr":
                textos += [(f"texto alternativo ({nombre})", None, el.get(k)) for k in ("descr", "title")
                           if (el.get(k) or "").strip()]
        if diseno:
            textos += [(f"diseño o patrón ({nombre})", None, x) for _, x in parrafos(xml(nombre))]
    for nombre in sorted(partes):
        if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", nombre):
            textos += [(f"notas ({nombre})", None, t) for _, t in parrafos(xml(nombre))]
        elif nombre.endswith(".xml") and re.search(r"(^|/)(comments/|comment\w*\.xml|modernComment|commentAuthors)",
                                                   nombre):
            textos += [(f"comentarios ({nombre})", None, t) for t in xml(nombre).itertext() if t.strip()]
    for nombre in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
        if nombre in partes:
            textos += [(f"propiedad {etree.QName(el).localname}", None, el.text) for el in xml(nombre).iter()
                       if isinstance(el.tag, str) and len(el) == 0 and (el.text or "").strip()]

    firmantes = {"Responsable comercial", "Responsable de preventa", "Responsable de área"}
    decisiones = [d for d in estado.get("decisiones") or [] if isinstance(d, dict)]
    firmantes |= {" ".join(str(d.get("revisor")).split()) for d in decisiones if str(d.get("revisor") or "").strip()}

    def admitido(donde, celda, texto):
        t = " ".join(texto.split())
        if donde == "diapositiva 2" and celda is not None and celda[0] == 2 and celda[1] in (3, 4, 5):
            return t == "Sin firma" or any(re.fullmatch(re.escape(f) + r"(?: \([A-ZÁÉÍÓÚÑ]{2,4}\)|, \d{4}-\d{2}-\d{2})",
                                                        t) for f in firmantes)
        if donde in ("propiedad creator", "propiedad lastModifiedBy"):
            return t in firmantes
        return donde == "propiedad keywords" and re.fullmatch(r"hash_contenido:[0-9a-f]{64}", t) is not None

    comentarios = []  # (id de la decisión, texto plano que no puede aparecer)
    for d in decisiones:
        sin_citas = re.sub(r"«[^«»]*»|\"[^\"]*\"|“[^“”]*”", " ", str(d.get("comentarios") or ""))
        entero = plano(sin_citas)
        tramos = [plano(x) for x in re.split(r"[.;:!?¡¿()\[\]\n]+", sin_citas)]
        comentarios += [(d.get("id"), x) for x in ([entero] if len(entero) >= 16 else []) + tramos if len(x) >= 16
                        and (x == entero or len(x) >= 30)]
    nombres = {plano(f) for f in firmantes if len(plano(f)) >= 5}
    # Revisión I1.8: también cada par de palabras seguidas («Responsable comercial», «Responsable comercial», «Responsable de área»), salvo el que
    # solo tiene nombres de pila («El responsable de área»): sería un falso rojo con cualquier otra persona que se llame así
    de_pila = {"juan", "pablo", "jose", "maria", "luis", "carlos", "miguel", "angel", "antonio", "manuel", "francisco",
               "ana", "carmen", "pedro", "jesus", "david", "daniel", "alberto", "alejandro",
               # quien firma se nombra por su rol: sus palabras sueltas son corrientes y se busca solo la frase entera
               "responsable", "comercial", "de", "preventa", "area"}
    for f in list(nombres):
        palabras = f.split(" ")
        nombres |= {" ".join(palabras[i:i + 2]) for i in range(len(palabras) - 1)
                    if not {palabras[i], palabras[i + 1]} <= de_pila}
    nombres = sorted(nombres)
    ids = set()
    for comp in (catalogo or {}).get("componentes") or []:
        if isinstance(comp, dict):
            ids.add(str(comp.get("id") or ""))
            ids |= {str(p.get("id") or "") for p in comp.get("plantillas_precio") or []
                    if isinstance(p, dict) and "-" in str(p.get("id") or "")}
    ids = sorted(x for x in ids if len(x) >= 3)
    marcas = ((r"(?<![\w-])D-\d{3}(?![\w-])", 0, "id de decisión"),
              (r"\b(?:DEVUELTA|APROBADA|ENVIADA_REVISION|DISCREPA|VERIFICADA|OBSERVACI[OÓ]N|NO VERIFICABLE|"
               r"NO VERIFICADO|DECISION)\b", 0, "rótulo de la revisión interna"),
              (r"\b(?:catalogo_id|plantilla_id|version_devuelta|hash_citado|componente_id)\b", re.I,
               "nombre de campo interno"),
              (r"(?<![\w.-])az-[a-z0-9]+(?:-[a-z0-9]+)*(?![\w-])", re.I, "identificador del catálogo"))
    frases = ("cambios pedidos", "como se atendio", "calculadas por el codigo", "calculados por el codigo",
              "calculado por el codigo", "calculada por el codigo", "nota del revisor", "nota de revision",
              "revision de preventa", "aprobacion del area", "recogido en la nota", "version devuelta",
              "devuelta con comentarios", "no dice que cambio responde")

    hallazgos = set()
    por_sitio = {}
    for donde, celda, texto in textos:
        if admitido(donde, celda, texto):
            continue
        pl = plano(texto)
        por_sitio.setdefault(donde, []).append(pl)
        sin_url = re.sub(r"https://learn\.microsoft\.com/\S*", " ", texto)
        motivos = [m for rx, banderas, m in marcas if re.search(rx, sin_url, banderas)]
        motivos += [f"identificador del catálogo «{x}»" for x in ids
                    if re.search(r"(?<![\w.-])" + re.escape(x) + r"(?![\w-])", sin_url, re.I)]
        motivos += [f"nombre de quien decide «{x}»" for x in nombres if re.search(r"(?<!\w)" + re.escape(x) + r"(?!\w)", pl)]
        motivos += [f"marcador de la revisión «{x}»" for x in frases if re.search(r"(?<!\w)" + re.escape(x) + r"(?!\w)", pl)]
        hallazgos |= {f"{donde}: {m} en «{texto[:80]}»" for m in motivos}
    for donde, pls in por_sitio.items():
        junto = " ".join(pls)
        hallazgos |= {f"{donde}: comentario de la decisión {i} («{x[:60]}»)" for i, x in comentarios if x in junto}
    return sorted(hallazgos)


def importes_no_permitidos(partes: dict, estado: dict) -> list[str]:
    """VA18-1 (I1.9, LES-G-053 y LES-G-097.1): importes y datos del presupuesto del alta que el cliente no puede ver en
    el PPTX; [] si no hay ninguno.

    `partes`: {nombre de la parte: bytes} del ZIP del PPTX. Recorre cada párrafo de las diapositivas (en el orden de
    presentation.xml, con sus tablas), de las notas y de los diseños y patrones, y el texto alternativo (`descr` y
    `title` de cada cNvPr) de las diapositivas, los diseños y los patrones (las superficies de VPROT-1). (1) Exclusividad de importes: toda cifra pegada a «€», «EUR»,
    «euro» o «euros» tiene que tener lectura española y ser el precio cerrado o un hito (`carga.estimacion.resumen`) o,
    solo en la diapositiva 8, una línea o un total del anexo de consumo (`carga.anexo_consumo`). (2) Presupuesto del alta
    (`requisitos.campos.presupuesto_orientativo`, CITADO o ASUMIDO): ni el rótulo «presupuesto orientativo» ni ninguna
    cifra de 100 o más de su valor o de su cita, salvo que sea uno de los importes admitidos en esa diapositiva. Autónoma
    (biblioteca estándar y lxml): la puerta la lleva copiada (CAMBIOS-I19-D). Una parte que falte o no se pueda leer
    lanza la excepción: quien llama falla en alto, nunca da el PPTX por limpio."""
    import re
    import unicodedata
    from decimal import Decimal, InvalidOperation
    from lxml import etree

    ns_a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns_p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    ns_r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    ns_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)

    def xml(nombre):
        return etree.fromstring(partes[nombre], parser)

    def plano(t):
        t = unicodedata.normalize("NFD", unicodedata.normalize("NFC", str(t or "")))
        return re.sub(r"\s+", " ", "".join(c for c in t if unicodedata.category(c) != "Mn")).lower().strip()

    def lectura(cifra):
        s = str(cifra or "").strip()
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:,\d{1,2})?", s):
            return Decimal(s.replace(".", "").replace(",", ".")).quantize(Decimal("0.01"))
        return None

    def importe(valor):
        try:
            return Decimal(str(valor)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None

    def lectura_amplia(texto_cifra):
        # cierre (16-10, Revisión): para el presupuesto del alta, una cifra sin lectura española se lee en inglés
        # («120,000», «120000.50»); nunca sirve para admitir un importe con moneda
        s = re.sub(r"[ \u00a0\u202f]", ".", str(texto_cifra or "").strip())
        valor = lectura(s)
        if valor is None and re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+", s):
            valor = importe(s.replace(",", ""))
        return valor

    def parrafos(raiz):
        salida = []
        for par in raiz.iter(f"{{{ns_a}}}p"):
            texto = "".join((el.text or "") if el.tag == f"{{{ns_a}}}t" else " "
                            for el in par.iter(f"{{{ns_a}}}t", f"{{{ns_a}}}br"))
            if texto.strip():
                salida.append(texto.replace("\u00a0", " ").replace("\u202f", " "))
        return salida

    carga = estado.get("carga") or {}
    resumen = (carga.get("estimacion") or {}).get("resumen") or {}
    anexo = carga.get("anexo_consumo") or {}
    base = {importe(resumen.get("precio_cerrado_eur"))} | {importe(h.get("importe_eur")) for h in resumen.get("hitos") or []
                                                            if isinstance(h, dict)}
    consumo = {importe(x.get("coste_mensual_eur")) for x in anexo.get("lineas") or [] if isinstance(x, dict)}
    consumo |= {importe(anexo.get("total_mensual_eur")), importe(anexo.get("total_anual_eur"))}
    base.discard(None)
    consumo.discard(None)
    # Revisión (I1.9): «25 000» (millar con espacio, también duro o fino) es una sola cifra
    cifra = re.compile(r"(?<![\w.,])(\d{1,3}(?:[ \u00a0\u202f.]\d{3})+(?:,\d{1,2})?|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
                       r"|\d+(?:[.,]\d+)?)(?![\w])")
    cifras_presupuesto = set()
    campos = (carga.get("requisitos") or {}).get("campos") or {}
    for e in (campos.get("presupuesto_orientativo") or {}).get("entradas") or []:
        for texto in (e.get("valor"), e.get("cita")) if isinstance(e, dict) else ():
            cifras_presupuesto |= {d for d in (lectura_amplia(m) for m in cifra.findall(str(texto or "")))
                                   if d is not None and d >= 100}

    textos = []  # (dónde, número de diapositiva o None, texto)
    destino = {r.get("Id"): r.get("Target")
               for r in xml("ppt/_rels/presentation.xml.rels").iter(f"{{{ns_rel}}}Relationship")}
    for n, sld in enumerate(xml("ppt/presentation.xml").iter(f"{{{ns_p}}}sldId"), 1):
        parte = "ppt/" + destino[sld.get(f"{{{ns_r}}}id")].lstrip("/").removeprefix("ppt/")
        textos += [(f"diapositiva {n}", n, t) for t in parrafos(xml(parte))]
    for nombre in sorted(partes):
        if re.fullmatch(r"ppt/notesSlides/notesSlide\d+\.xml", nombre):
            textos += [(f"notas ({nombre})", None, t) for t in parrafos(xml(nombre))]
    for nombre in sorted(partes):  # cierre (16-10, Revisión 7): también lo que se dibuja o se lee fuera de los párrafos
        diseno = re.fullmatch(r"ppt/(?:slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml", nombre)
        if not (diseno or re.fullmatch(r"ppt/slides/slide\d+\.xml", nombre)):
            continue
        raiz = xml(nombre)
        textos += [(f"texto alternativo ({nombre})", None, el.get(k)) for el in raiz.iter()
                   if isinstance(el.tag, str) and etree.QName(el).localname == "cNvPr"
                   for k in ("descr", "title") if (el.get(k) or "").strip()]
        textos += [(f"diseño o patrón ({nombre})", None, t) for t in parrafos(raiz)] if diseno else []

    moneda = re.compile(r"(?<![\w.,])(\d[\d.,]*\d|\d)\s*(?:€|EUR\b|euros?\b)|(?:€|\bEUR)\s*(\d[\d.,]*\d|\d)(?![\d])", re.I)
    hallazgos = set()
    for donde, n, texto in textos:
        admitidos = base | consumo if n == 8 else base
        for m in moneda.finditer(texto):
            literal = m.group(1) or m.group(2)
            valor = lectura(literal)
            if valor is None:
                hallazgos.add(f"{donde}: importe «{literal}» sin lectura en formato español en «{texto[:80]}»")
            elif valor not in admitidos:
                hallazgos.add(f"{donde}: importe «{literal}» que no es el precio cerrado ni un hito"
                              + (" ni una línea del anexo de consumo" if n == 8 else "") + f" en «{texto[:80]}»")
        con_cifra = False  # Revisión (I1.9, pasada 2): cifra de 1.000 o más (o «mil», «millón») en la frase; un año, no
        for frase in re.split(r"[.;!?]\s", plano(texto)):
            for m in cifra.finditer(frase) if "presupuest" in frase else ():
                valor = lectura_amplia(m.group(1))
                con_cifra |= bool(re.match(r"\s*(mil|millon|millones)\b", frase[m.end():m.end() + 10])) or (
                    valor is not None and valor >= 1000 and not re.fullmatch(r"(19|20)\d\d", m.group(1)))
        if "presupuesto orientativo" in plano(texto) or con_cifra:
            hallazgos.add(f"{donde}: nombra el presupuesto orientativo del alta o un presupuesto con cifra en «{texto[:80]}»")
        for m in cifra.finditer(texto):
            valor = lectura_amplia(m.group(1))
            if valor is not None and valor in cifras_presupuesto and valor not in admitidos:
                hallazgos.add(f"{donde}: cifra «{m.group(1)}» del presupuesto orientativo del alta en «{texto[:80]}»")
    return sorted(hallazgos)


TITULO_APROBADA = "{codigo} · Propuesta comercial"   # VA18-7 (I1.9): el entregable del cliente ya no es un borrador


def _propiedades(prs, textos: dict, hash_vigente: str, aprobada: bool = False) -> None:
    cp = prs.core_properties
    cp.title = (TITULO_APROBADA.format(codigo=textos["codigo"]) if aprobada
                else f"{textos['codigo']} · Propuesta para revisión")
    cp.author = AUTOR
    cp.last_modified_by = AUTOR
    cp.subject = textos["portada"]["titulo"]
    cp.keywords = f"hash_contenido:{hash_vigente}"
    cp.comments = ""
    cp.category = "Preventa"
    cp.revision = 1
    cp.language = "es-ES"


_EP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"


def limpiar_paquete(paquete, formato: str | None = None, diapositivas: int | None = None) -> None:
    """Sustituye docProps/app.xml por uno mínimo y quita la miniatura heredada de la plantilla."""
    rels = paquete.rels if hasattr(paquete, "rels") else paquete._rels  # python-docx / python-pptx
    for rid, rel in list(rels.items()):
        if rel.reltype == RT.THUMBNAIL:
            rels.pop(rid)
    app = paquete.part_related_by(RT.EXTENDED_PROPERTIES)
    hijos = [("Company", "Devoteam")]  # orden de CT_Properties
    if formato:
        hijos.append(("PresentationFormat", formato))
    if diapositivas is not None:
        hijos += [("Slides", str(diapositivas)), ("Notes", "0"), ("HiddenSlides", "0")]
    raiz = etree.Element(f"{{{_EP}}}Properties", nsmap={None: _EP})
    for etiqueta, valor in hijos:
        etree.SubElement(raiz, f"{{{_EP}}}{etiqueta}").text = valor
    app._blob = etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def _marca_tema(prs) -> None:
    tema = prs.slide_master.part.part_related_by(RT.THEME)
    tema._blob = reescribir_tema(tema.blob)


def construir(estado: dict, catalogo: dict) -> tuple[object, dict]:
    """Presentación en memoria (sin guardar) e informe {"modo", "fallos"} del diagrama."""
    textos, hash_vigente = comprobar_textos(estado, catalogo)
    firmas = decision.firmas(estado)
    prs = Presentation()
    prs.slide_width, prs.slide_height = ANCHO, ALTO
    _marca_tema(prs)
    _portada(prs, textos, subtitulo_portada(estado, textos))
    _control_versiones(prs, estado, textos, firmas, hash_vigente)
    _necesidad(prs, textos)
    informe = _arquitectura(prs, textos)
    respuesta = est_mod.registro_experto(estado).get("respuesta") or {}
    faltan = referencias_faltan(prs.slides[3]._element, respuesta)  # REVERIF16-3: ningún componente sin su página
    if faltan:
        raise _fallo(errores.ReglaIncumplida, "el PPTX no se publica: falta la página de algún componente en el pie "
                     "de la diapositiva 4", faltan)
    _alcance(prs, textos)
    _supuestos(prs, textos)
    _precio(prs, textos)
    _consumo(prs, textos, anexo_consumo.no_valorados(estado, catalogo))
    _lista(prs, 9, textos, "riesgos", "No se han identificado riesgos adicionales.")
    _lista(prs, 10, textos, "condiciones", "Condiciones según la oferta.")
    _propiedades(prs, textos, hash_vigente, aprobada=estado.get("estado") == "APROBADA")   # VA18-7
    limpiar_paquete(prs.part.package, "Panorámica (16:9)", len(prs.slides))
    hallazgos = barrido(prs, perfiles_de(estado), hash_vigente)
    if hallazgos:
        raise _fallo(errores.ReglaIncumplida, "el PPTX no se publica: el barrido de §9.3 encuentra texto prohibido",
                     hallazgos)
    partes = partes_de(prs)
    internos = revision_interna_en_pptx(partes, estado, catalogo)  # VER17-2 (I1.8, LES-G-053)
    if internos:
        raise _fallo(errores.ReglaIncumplida, "el PPTX no se publica: contiene texto de la revisión interna, que solo "
                     "va en la nota del revisor", internos)
    importes = importes_no_permitidos(partes, estado)  # VA18-1 (I1.9, LES-G-053 y LES-G-097.1)
    if importes:
        raise _fallo(errores.ReglaIncumplida, "el PPTX no se publica: lleva importes o datos del presupuesto que el "
                     "cliente no puede ver", importes)
    return prs, informe


def guardar_atomico(prs_o_doc, ruta: pathlib.Path) -> str:
    """Guarda en un temporal del mismo directorio, os.replace y chmod 644; devuelve el SHA-256."""
    ruta = pathlib.Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=ruta.suffix, dir=str(ruta.parent))
    os.close(fd)
    try:
        prs_o_doc.save(tmp)
        os.replace(tmp, ruta)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)  # limpieza de cortesía: nunca tapa el error original de save
            except OSError:
                pass
    os.chmod(ruta, 0o644)
    return hashes.sha256_fichero(ruta)


def generar(estado: dict, catalogo: dict, ruta: pathlib.Path) -> str:
    """Genera el PPTX de revisión en `ruta` y devuelve su SHA-256 (CONTRATOS.md §4.14)."""
    prs, _ = construir(estado, catalogo)
    return guardar_atomico(prs, ruta)
