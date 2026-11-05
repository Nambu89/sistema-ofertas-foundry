"""Nota de revisión interna (DOCX) para Responsable de preventa y Responsable de área (CONTRATOS.md §9.5).

Documento interno: aquí sí aparecen horas por perfil e importes, porque es para los revisores.
Montserrat y la paleta de la marca en estilos, tema y cada fragmento (LES-G-072). Todo lo que
procede de un modelo o de la transcripción pasa por el barrido único de marcadores; lo que no lo
pasa se retira del documento y se declara como riesgo residual (LES-G-094).
"""
from __future__ import annotations

import json
import pathlib
import re
from decimal import Decimal, InvalidOperation

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from lxml import etree

from nucleo import anexo_consumo, decision, errores, experto, hashes, suficiencia, textos_cliente
from nucleo import estado as est_mod
from nucleo.pptx_revision import (AUTOR, BANDA, BLANCO, BORDE, FUENTE, OSCURO, PALETA, ROJO, _fallo,
                                  formato_eur, guardar_atomico, limpiar_paquete, reescribir_tema)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_ATRIB_TEMA = ("themeColor", "themeShade", "themeTint", "themeFill", "themeFillShade", "themeFillTint",
               "asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme")
_RE_VTT = re.compile(r"</?v(?:\s[^>]*)?>")
RETIRADO = "[texto retirado del documento: contiene una palabra reservada; consta en estado.json]"


# ---------------------------------------------------------------------------------------------
# Marca: estilos, tema y tabla de fuentes
# ---------------------------------------------------------------------------------------------
def _limpiar_tema_atributos(el) -> None:
    for nombre in _ATRIB_TEMA:
        el.attrib.pop(f"{{{_W}}}{nombre}", None)


def normalizar_estilos(raiz) -> None:
    """Fuerza Montserrat y la paleta en un styles.xml (lxml); sin referencias al tema."""
    for el in raiz.iter():
        _limpiar_tema_atributos(el)
        if el.tag == f"{{{_W}}}rFonts":
            for atributo in ("ascii", "hAnsi", "eastAsia", "cs"):
                el.set(f"{{{_W}}}{atributo}", FUENTE)
        elif el.tag == f"{{{_W}}}color":
            if (el.get(f"{{{_W}}}val") or "").upper() not in PALETA:
                el.set(f"{{{_W}}}val", OSCURO)
        else:
            borde = el.get(f"{{{_W}}}color")
            if borde is not None and borde.upper() not in PALETA and borde != "auto":
                el.set(f"{{{_W}}}color", BORDE)
            fondo = el.get(f"{{{_W}}}fill")
            if fondo is not None and fondo.upper() not in PALETA and fondo != "auto":
                el.set(f"{{{_W}}}fill", BANDA)
    defecto = raiz.find(f"{{{_W}}}docDefaults/{{{_W}}}rPrDefault/{{{_W}}}rPr")
    if defecto is not None and defecto.find(f"{{{_W}}}rFonts") is None:
        fuentes = etree.SubElement(defecto, f"{{{_W}}}rFonts")
        defecto.insert(0, fuentes)
        for atributo in ("ascii", "hAnsi", "eastAsia", "cs"):
            fuentes.set(f"{{{_W}}}{atributo}", FUENTE)


def _tabla_fuentes(xml: bytes) -> bytes:
    raiz = etree.fromstring(xml)
    for hijo in list(raiz):
        raiz.remove(hijo)
    etree.SubElement(raiz, f"{{{_W}}}font").set(f"{{{_W}}}name", FUENTE)
    return etree.tostring(raiz, xml_declaration=True, encoding="UTF-8", standalone=True)


def _numeracion_montserrat(doc) -> None:
    """numbering.xml de la plantilla por defecto trae viñetas en «Symbol», «Courier New» y «Wingdings»
    (LES-G-072). La nota no usa listas numeradas (las viñetas son texto «• »): se fuerzan Montserrat y
    la viñeta «•» en todos los niveles para que ninguna fuente ajena quede en el paquete
    (integración I1, hallazgo de verificar_paquete.py)."""
    try:
        raiz = doc.part.numbering_part.element
    except (KeyError, NotImplementedError):
        return
    for fuentes in raiz.iter(f"{{{_W}}}rFonts"):
        for atributo in list(fuentes.attrib):
            fuentes.attrib.pop(atributo)
        for atributo in ("ascii", "hAnsi", "eastAsia", "cs"):
            fuentes.set(f"{{{_W}}}{atributo}", FUENTE)
    for texto in raiz.iter(f"{{{_W}}}lvlText"):
        valor = texto.get(f"{{{_W}}}val") or ""
        if valor and all(0xE000 <= ord(c) <= 0xF8FF or c in "o§" for c in valor):
            texto.set(f"{{{_W}}}val", "•")
    _limpiar_tema_atributos(raiz)


def aplicar_marca(doc) -> None:
    normalizar_estilos(doc.styles.element)
    for nombre, color, tam in (("Heading 1", ROJO, 15), ("Heading 2", OSCURO, 12), ("Title", OSCURO, 22)):
        estilo = doc.styles[nombre]
        estilo.font.name = FUENTE
        estilo.font.color.rgb = RGBColor.from_string(color)
        estilo.font.size = Pt(tam)
        estilo.font.bold = True
    normal = doc.styles["Normal"]
    normal.font.name = FUENTE
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor.from_string(OSCURO)
    normalizar_estilos(doc.styles.element)
    tema = doc.part.part_related_by(RT.THEME)
    tema._blob = reescribir_tema(tema.blob)
    _numeracion_montserrat(doc)
    try:
        tabla_fuentes = doc.part.part_related_by(RT.FONT_TABLE)
        tabla_fuentes._blob = _tabla_fuentes(tabla_fuentes.blob)
    except KeyError:
        pass


def _fuente_run(run, tam: float | None, negrita: bool, color: str) -> None:
    run.font.name = FUENTE
    run.font.bold = negrita
    if tam:
        run.font.size = Pt(tam)
    run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._r.get_or_add_rPr()
    fuentes = rpr.find(qn("w:rFonts"))
    for atributo in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fuentes.set(qn(atributo), FUENTE)
    _limpiar_tema_atributos(fuentes)


def parrafo(doc_o_celda, texto: str, negrita=False, color=OSCURO, tam: float | None = None, estilo=None,
            alineacion=None):
    p = doc_o_celda.add_paragraph(style=estilo) if estilo else doc_o_celda.add_paragraph()
    if alineacion is not None:
        p.alignment = alineacion
    _fuente_run(p.add_run(str(texto)), tam, negrita, color)
    return p


def titulo(doc, texto: str, nivel: int = 1):
    p = doc.add_heading(level=nivel)
    _fuente_run(p.add_run(texto), 15 if nivel == 1 else 12, True, ROJO if nivel == 1 else OSCURO)
    return p


def _bordes_tabla(tabla) -> None:
    tblpr = tabla._tbl.tblPr
    viejo = tblpr.find(qn("w:tblBorders"))
    if viejo is not None:
        tblpr.remove(viejo)
    bordes = OxmlElement("w:tblBorders")
    for lado in ("top", "left", "bottom", "right", "insideH", "insideV"):
        b = OxmlElement(f"w:{lado}")
        b.set(qn("w:val"), "single")
        b.set(qn("w:sz"), "4")
        b.set(qn("w:space"), "0")
        b.set(qn("w:color"), BORDE)
        bordes.append(b)
    siguiente = next((tblpr.find(qn(t)) for t in ("w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook")
                      if tblpr.find(qn(t)) is not None), None)
    if siguiente is not None:
        siguiente.addprevious(bordes)  # orden de CT_TblPr (LES-G-059)
    else:
        tblpr.append(bordes)


def _sombra(celda, color: str) -> None:
    tcpr = celda._tc.get_or_add_tcPr()
    viejo = tcpr.find(qn("w:shd"))
    if viejo is not None:
        tcpr.remove(viejo)
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)
    siguiente = next((tcpr.find(qn(t)) for t in ("w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText",
                                                   "w:vAlign", "w:hideMark") if tcpr.find(qn(t)) is not None), None)
    if siguiente is not None:
        siguiente.addprevious(shd)
    else:
        tcpr.append(shd)


def tabla(doc, filas: list[list[str]], anchos_cm: list[float] | None = None, tam: float = 9):
    """Tabla con cabecera oscura y texto blanco, bandas claras y bordes grises."""
    t = doc.add_table(rows=len(filas), cols=len(filas[0]))
    _bordes_tabla(t)
    for i, fila in enumerate(filas):
        for j, valor in enumerate(fila):
            celda = t.cell(i, j)
            p = celda.paragraphs[0]  # celda nueva: un párrafo vacío; `celda.text = ""` dejaría un run sin fuente
            _fuente_run(p.add_run(str(valor)), tam, i == 0, BLANCO if i == 0 else OSCURO)
            _sombra(celda, OSCURO if i == 0 else (BANDA if i % 2 == 0 else BLANCO))
            if anchos_cm:
                celda.width = Cm(anchos_cm[j])
    doc.add_paragraph()
    return t


# ---------------------------------------------------------------------------------------------
# Contenido
# ---------------------------------------------------------------------------------------------
class _Riesgos:
    """Acumula riesgos residuales y retira del documento lo que no pasa el barrido de marcadores."""

    def __init__(self) -> None:
        self.lista: list[str] = []

    def seguro(self, texto, donde: str) -> str:
        valor = _RE_VTT.sub("", str(texto if texto is not None else ""))
        if textos_cliente.marcadores(valor):
            self.lista.append(f"Texto retirado de la nota ({donde}) por contener una palabra reservada; "
                              "el original consta en estado.json.")
            return RETIRADO
        return valor


def _carga(estado: dict) -> dict:
    return estado.get("carga") or {}


def _respuesta(estado: dict) -> dict:
    return est_mod.registro_de_carga(_carga(estado)).get("respuesta") or {}


def _seccion_identificacion(doc, estado: dict, hash_vigente: str) -> None:
    carga = _carga(estado)
    alta = carga.get("alta") or {}
    fecha = ((carga.get("estimacion") or {}).get("entrada") or {}).get("fecha") or ""
    titulo(doc, "1. Identificación")
    tabla(doc, [["Dato", "Valor"],
                ["Código", estado.get("codigo") or ""],
                ["Versión", estado.get("version") or ""],
                ["Fecha de elaboración", fecha],
                ["Cliente", alta.get("cliente") or ""],
                ["Proyecto", alta.get("titulo") or ""],
                ["Estado", estado.get("estado") or ""],
                ["Huella del contenido", hash_vigente]], [4.5, 12])


LISTA_COMPROBACION = (
    "Arquitectura: el diagrama cubre todas las capacidades del alcance y los componentes son los del catálogo.",
    "Referencias: cada referencia de Learn tiene URL y respalda el componente que cita.",
    "Precios cloud: cada precio sale de la instantánea de Azure Retail Prices que el código descargó al desplegar "
    "(fecha en los apartados 6 y 7; no más de 31 días); revisar cada factor CAMBIADO POR EL EXPERTO y el ciclo de vida "
    "de los modelos.",
    "Estimación interna: horas por perfil, gestión de proyecto (mínimo 8 h) y holgura del 20 % por tarea.",
    "Supuestos [BAJA]: los valores asumidos son razonables y se confirmarán con el cliente.",
    "Riesgos residuales: lo no verificable está declarado y es aceptable para enviar la propuesta.",
    "Avisos del verificador: ningún elemento queda en DISCREPA y los NO VERIFICABLE están entendidos.",
    "Observaciones editoriales del verificador (apartado 5): leídas; si alguna obliga a cambiar el texto, se devuelve.",
    "Consumo no valorado: cada servicio sin precio figura como «No valorado» con su motivo concreto en el apartado 6 "
    "y es aceptable (al cliente se le dice «A valorar con el volumen real» o «Se licencia aparte»).",
    "Volumen y niveles (apartado 6): cada factor de volumen, su cuenta y cada nivel elegido con su requisito y su "
    "límite oficial son razonables; los conceptos que el código sustituyó no esconden otro medidor.",
    # I1.8 (CAMBIOS-I18-P §5: REV17-3, REVERIF17-3 y REV17-2; texto de P tras el tema)
    "A cargo del cliente: si algún componente sale a cargo del cliente, la frase citada está en la transcripción y "
    "habla de ese servicio.",
    "Instancias: si algún servicio lleva más de una instancia, el requisito citado obliga a escalar y no pasa del tope "
    "del nivel.",
    "Modelos de Microsoft Foundry: el modelo que nombra cada componente de Microsoft Foundry es el de sus líneas de "
    "consumo.",
    # I1.8 (VER17-2): la sección de cambios es del revisor y no va al cliente
    "Cambios pedidos (versión abierta por una devolución): cada comentario de la revisión anterior está atendido; esa "
    "sección solo figura en esta nota, nunca en la presentación del cliente.",
    "Paquete: el comercial ha ejecutado verificar_paquete.py en local con resultado rc 0.",
)


def _seccion_comprobacion(doc) -> None:
    titulo(doc, "2. Lista de comprobación del revisor")
    for punto in LISTA_COMPROBACION:
        parrafo(doc, f"☐ {punto}")


ORIGEN_VISIBLE = {"CITADO": "CITADO", "ASUMIDO": "ASUMIDO", "ACLARACION": "ACLARACIÓN"}
PROCEDENCIA_VISIBLE = {"TRANSCRIPCION": "reunión", "NOTAS_COMERCIAL": "notas del comercial"}
# VA18-10 (I1.9): etiqueta legible de cada campo de los requisitos (las del brief) en lo que lee el revisor
ETIQUETAS_CAMPO = {"objetivo": "Objetivo", "nubes": "Nubes", "alcance_funcional": "Alcance funcional",
                   "canales_integraciones": "Canales e integraciones",
                   "ubicacion_usuarios": "Ubicación de los usuarios finales", "marco_normativo": "Marco normativo",
                   "volumetria": "Volumetría", "identidad_acl_origen": "Identidad y permisos del origen",
                   "fuera_de_alcance": "Fuera de alcance", experto.CAMPO_CLIENTE: "Lo que el cliente ya tiene o paga",
                   **{campo: etq for campo, etq in experto.brief_mod.ETIQUETAS_CONTEXTO}}
# VA18-10: un id de hallazgo de desarrollo («(REVERIF16-3)», «; PR15-2)») no es para el revisor; los ids de los
# elementos («C-02», «EX-06», «S-01») no llevan cifra antes del guion y no se tocan
_RE_ID_HALLAZGO = re.compile(r"\s*\((?:[A-Z]{1,8}\d{1,2}-\d+(?:\.\d+)?)(?:[,;] ?[A-Z]{1,8}\d{1,2}-\d+(?:\.\d+)?)*\)"
                             r"|[,;] ?[A-Z]{1,8}\d{1,2}-\d+(?:\.\d+)?(?=\))")


def etiqueta_campo(campo: object) -> str:
    """La etiqueta del brief del campo («volumetria» → «Volumetría»); un campo desconocido, sin guiones bajos."""
    return ETIQUETAS_CAMPO.get(campo) or str(campo).replace("_", " ").capitalize()


def sin_ids_hallazgo(texto: object) -> str:
    """El texto sin los ids de hallazgos de desarrollo entre paréntesis (VA18-10)."""
    return _RE_ID_HALLAZGO.sub("", str(texto if texto is not None else ""))


def ver_veredicto(veredicto: object) -> str:
    """El veredicto como lo lee el revisor: «OBSERVACIÓN» con tilde (VA18-10); los demás, tal cual."""
    return "OBSERVACIÓN" if es_observacion(veredicto) else str(veredicto or "")


def _seccion_requisitos(doc, estado: dict, riesgos: _Riesgos) -> list[tuple[str, str]]:
    """Tabla de requisitos; devuelve [(campo, valor)] de lo ASUMIDO para la sección 4."""
    titulo(doc, "3. Requisitos con su cita y origen")
    campos = ((_carga(estado).get("requisitos") or {}).get("campos")) or {}
    filas = [["Campo", "Valor", "Origen", "Cita literal"]]
    asumidos = []
    # notas del comercial: con notas, cada cita dice si viene de la reunión o de las notas (sin notas, como siempre)
    procedencia = {f.get("id"): PROCEDENCIA_VISIBLE[f.get("tipo")] for f in est_mod.fuentes_del_alta(estado)} \
        if est_mod.con_notas(estado) else {}
    for campo, datos in campos.items():
        for entrada in (datos or {}).get("entradas") or []:
            origen = ORIGEN_VISIBLE.get(entrada.get("origen"), str(entrada.get("origen")))
            if entrada.get("fuente") in procedencia:
                origen = f"{origen} ({procedencia[entrada['fuente']]})"
            valor = riesgos.seguro(entrada.get("valor"), f"requisito {campo}")
            cita = entrada.get("cita")
            cita_txt = riesgos.seguro(cita, f"cita de {campo}") if cita else "—"
            fuente = entrada.get("fuente")
            if isinstance(entrada.get("id"), str):  # I1.9: la entrada de un recurso del cliente lleva su EX-nn
                valor = f"{entrada['id']}: {valor}"
            filas.append([etiqueta_campo(campo), valor, origen, f"{cita_txt} ({fuente})" if cita and fuente else cita_txt])
            if entrada.get("origen") == "ASUMIDO":
                asumidos.append((campo, valor))
    if len(filas) == 1:
        filas.append(["—", "Sin requisitos registrados", "—", "—"])
    tabla(doc, filas, [3.2, 5.5, 2.2, 6.5], 8)
    return asumidos


def _seccion_frases_sin_cita(doc, estado: dict, transcripcion, riesgos: _Riesgos) -> None:
    """VERIF-2: frases del cliente con forma de requisito que ningún campo cita enteras (no bloquea)."""
    de = "de la transcripción" if not est_mod.con_notas(estado) else (
        "de las notas del comercial" if est_mod.sin_grabacion(estado) else "de la reunión y de las notas del comercial")
    parrafo(doc, f"Frases {de} con forma de requisito que ningún campo cita enteras (comprobar que "
                 "lo que dicen está en el alcance, la arquitectura y el precio):", negrita=True)
    if not isinstance(transcripcion, str):
        motivo = f"{type(transcripcion).__name__}: {transcripcion}" if transcripcion is not None else "no se recibió"
        parrafo(doc, f"• No se ha podido comprobar: falta el texto de la transcripción ({riesgos.seguro(motivo, 'motivo')}). "
                     "Revisar a mano la transcripción contra la tabla anterior.")
        riesgos.lista.append("Cobertura de la transcripción sin comprobar: la nota se generó sin su texto.")
        return
    campos = ((_carga(estado).get("requisitos") or {}).get("campos")) or {}
    citas = [e.get("cita") for d in campos.values() for e in (d or {}).get("entradas") or [] if e.get("cita")]
    frases = suficiencia.frases_requisito_sin_cita(transcripcion, citas)
    for frase, suelta in frases:
        parrafo(doc, f"• «{riesgos.seguro(frase, 'frase de la transcripción')}» (sin citar: "
                     f"«{riesgos.seguro(suelta, 'frase de la transcripción')}»)")
    if not frases:
        parrafo(doc, "• Ninguna detectada.")
    parrafo(doc, suficiencia.DETECTOR_HEURISTICO, tam=8)


def _seccion_baja(doc, estado: dict, asumidos: list[tuple[str, str]], riesgos: _Riesgos) -> None:
    titulo(doc, "4. Supuestos de confianza baja que hay que confirmar")
    lineas = [f"[BAJA] {etiqueta_campo(campo)}: {valor} (asumido por el comercial en el alta; confirmar con el cliente)"
              for campo, valor in asumidos]
    listados, textos = set(), set()  # D18-4 y VA18-11: un supuesto visible que repite uno del experto no se repite
    for s in _respuesta(estado).get("supuestos") or []:
        if s.get("confianza") == "BAJA":
            lineas.append(f"[BAJA] {s.get('id')}: {riesgos.seguro(s.get('texto'), 'supuesto del experto')}")
            listados.add(s.get("id"))
            textos.add(experto._compacto(s.get("texto")))
    for s in (_carga(estado).get("textos_cliente") or {}).get("supuestos") or []:
        hechos = [h for h in s.get("hechos") or [] if isinstance(h, str)]
        repetido = (hechos and all(h in listados for h in hechos)) or experto._compacto(s.get("texto")) in textos
        if s.get("nivel") == "Confianza baja" and not any(h.startswith("R-") for h in hechos) and not repetido:
            lineas.append(f"[BAJA] {s.get('id')}: {riesgos.seguro(s.get('texto'), 'supuesto visible')}")
            textos.add(experto._compacto(s.get("texto")))
    for linea in lineas or ["No hay supuestos de confianza baja."]:
        parrafo(doc, f"• {linea}")


OBSERVACION = "OBSERVACION"  # veredicto editorial del verificador (LES-G-096), no bloquea


def es_observacion(veredicto: object) -> bool:
    """OBSERVACION con o sin tilde, en cualquier caja: el mismo criterio en las dos tablas."""
    return str(veredicto or "").strip().upper().replace("Ó", "O") == OBSERVACION


def _texto_obs(x: dict, *claves: str) -> str:
    return next((str(x[k]).strip() for k in claves if isinstance(x.get(k), str) and x[k].strip()), "")


def observaciones_de(estado: dict) -> list[dict]:
    """[{"id", "texto", "detalle", "propuesta"}] de las OBSERVACIONES editoriales del verificador.

    Forma de V (verificacion.registrar, docs/I1/CAMBIOS-I11-D.md §3): `carga.verificacion.observaciones`,
    objetos con `id`, `detalle`, `valor_correcto` (la propuesta) y `texto_original` (lo observado). Se
    aceptan también `verificacion.resultado.observaciones` y los elementos de la respuesta con veredicto
    OBSERVACION, para no perder ninguna; sin repetidos (id y detalle) y en orden de aparición."""
    verif = _carga(estado).get("verificacion") or {}
    fuentes = [verif.get("observaciones"), (verif.get("resultado") or {}).get("observaciones"),
               [e for e in (verif.get("respuesta") or {}).get("elementos") or []
                if isinstance(e, dict) and es_observacion(e.get("veredicto"))]]
    salida, vistas = [], set()
    for lista in fuentes:
        for x in lista or []:
            if isinstance(x, str):
                x = {"detalle": x}
            if not isinstance(x, dict):
                continue
            obs = {"id": _texto_obs(x, "id", "elemento_id") or "—",
                   "texto": _texto_obs(x, "texto_original"),
                   "detalle": _texto_obs(x, "detalle", "texto", "observacion", "motivo"),
                   "propuesta": _texto_obs(x, "propuesta", "sugerencia", "valor_correcto")}
            clave = (obs["id"], obs["detalle"])
            if obs["detalle"] and clave not in vistas:
                vistas.add(clave)
                salida.append(obs)
    return salida


def _seccion_observaciones(doc, estado: dict, riesgos: _Riesgos) -> None:
    titulo(doc, "Observaciones editoriales del verificador", 2)
    obs = observaciones_de(estado)
    if not obs:
        parrafo(doc, "El verificador no ha hecho observaciones editoriales.")
        return
    parrafo(doc, "Son observaciones de redacción o de reglas, sin un hecho con fuente que las respalde: no "
                 "bloquean el paquete, pero el revisor decide si obligan a cambiar el texto.", tam=9)
    filas = [["Elemento", "Texto observado", "Observación", "Propuesta"]]
    for o in obs:
        texto = " · ".join(x.strip() for x in o["texto"].split("|")) if o["texto"] else ""  # VA18-10: sin «|»
        filas.append([o["id"], riesgos.seguro(texto, f"texto observado {o['id']}") if texto else "—",
                      riesgos.seguro(sin_ids_hallazgo(o["detalle"]), f"observación del verificador {o['id']}"),
                      riesgos.seguro(o["propuesta"], f"propuesta del verificador {o['id']}") if o["propuesta"] else "—"])
    tabla(doc, filas, [2, 5.5, 5.5, 4.5], 8)


def _seccion_verificacion(doc, estado: dict, riesgos: _Riesgos) -> list[str]:
    """Tabla por elemento; devuelve los ids NO VERIFICABLE."""
    titulo(doc, "5. Verificación por elemento")
    verif = _carga(estado).get("verificacion") or {}
    resultado = verif.get("resultado") or {}
    reparados = {x.get("id") for x in resultado.get("reparados") or []}
    no_verif = [x.get("id") for x in resultado.get("no_verificables") or []]
    discrepa = {x.get("id") for x in resultado.get("discrepa") or []}
    parrafo(doc, f"Consolidado {verif.get('consolidado_id') or '—'}; verificador independiente con un modelo "
                 f"distinto del experto. Resultado: {'VERIFICADA' if resultado.get('verificada') else 'NO VERIFICADA'}.")
    filas = [["Elemento", "Tipo", "Veredicto", "Resultado efectivo", "Detalle"]]
    for el in (verif.get("respuesta") or {}).get("elementos") or []:
        eid = el.get("id")
        efectivo = ("DISCREPA reparado" if eid in reparados else "DISCREPA" if eid in discrepa
                    else "NO VERIFICABLE" if eid in no_verif
                    else "OBSERVACIÓN (no bloquea)" if es_observacion(el.get("veredicto")) else "OK")
        filas.append([eid, el.get("tipo") or "", ver_veredicto(el.get("veredicto")), efectivo,
                      riesgos.seguro(sin_ids_hallazgo(el.get("detalle")), f"detalle del verificador {eid}")])
    if len(filas) == 1:
        filas.append(["—", "—", "—", "—", "Sin verificación registrada"])
    tabla(doc, filas, [2, 2.2, 2.6, 3.2, 7.5], 8)
    _seccion_observaciones(doc, estado, riesgos)
    return no_verif


PROCEDENCIA_A2A = ("Procedencia A2A: desde el sandbox no se puede demostrar que las respuestas del experto y del "
                   "verificador llegaron por A2A y no las escribió el coordinador; verificar_paquete.py lo "
                   "comprueba en local si dispone de la traza y, si no, queda como riesgo aceptado.")


def _seccion_riesgos(doc, estado: dict, no_verif: list[str], riesgos: _Riesgos, catalogo: dict | None = None) -> None:
    titulo(doc, "6. Riesgos residuales")
    lineas = [f"{i}: NO VERIFICABLE por el verificador; el anexo lo marca sin contraste independiente."
              for i in no_verif]
    textos = _carga(estado).get("textos_cliente") or {}
    for ex in textos_cliente.frases_excluidas(textos):
        lineas.append(f"Frase excluida del PPTX ({ex.get('origen')}): "
                      f"{riesgos.seguro(ex.get('texto'), 'frase excluida').rstrip().removesuffix('.')}. Motivo: {ex.get('motivo')}")
    for aviso in (_carga(estado).get("anexo_consumo") or {}).get("avisos") or []:
        lineas.append(f"Anexo de consumo: {riesgos.seguro(aviso, 'aviso del anexo')}")
    if _carga(estado).get("anexo_consumo"):  # PR15-2: el motivo concreto de cada componente sin valorar
        for motivo in anexo_consumo.motivos_para_revisor(anexo_consumo.no_valorados(estado, catalogo or {})):
            lineas.append(f"Consumo sin valorar: {riesgos.seguro(motivo, 'motivo de no valoración')}")
    # I1.6 (decisión 4, LES-G-100): factores de volumen con su cuenta, precios unitarios de referencia que no suman,
    # niveles justificados y conceptos que el código fijó desde la plantilla (ajustes_nucleo del registro).
    # I1.7: fecha de la instantánea, factores estándar y cambiados, ciclo de vida de los modelos (con el límite de la
    # fecha de la oferta y las semanas del Gantt), motivos con su dato y lo que el código puso o sustituyó.
    registro = est_mod.registro_de_carga(_carga(estado))
    sustituciones = (registro.get("ajustes_nucleo") or {}).get("conceptos")
    entrada = (_carga(estado).get("estimacion") or {}).get("entrada") or {}
    for linea in experto.lineas_para_revisor(_respuesta(estado), catalogo or {}, sustituciones,
                                             fecha=entrada.get("fecha"), semanas=entrada.get("duracion_semanas"),
                                             requisitos=_carga(estado).get("requisitos")):
        lineas.append(riesgos.seguro(linea, "supuesto de volumen, nivel, modelo o ajuste del código"))
    for rg in _respuesta(estado).get("riesgos") or []:
        lineas.append(f"Riesgo del experto {rg.get('id')}: {riesgos.seguro(rg.get('texto'), 'riesgo del experto')} "
                      f"Mitigación: {riesgos.seguro(rg.get('mitigacion'), 'mitigación del experto')}")
    precios = _respuesta(estado).get("precios") or []  # REVER-1: el filtro del precio identifica el servicio
    for c in _respuesta(estado).get("componentes") or []:  # VER-1: nunca un nombre libre en silencio
        if isinstance(c, dict) and experto.aviso_fuera_de_catalogo(c, catalogo or {}, precios):
            lineas.append(f"Componente {c.get('id')} «{riesgos.seguro(c.get('servicio'), 'componente del experto')}» "
                          f"en {c.get('region')}: {experto.AVISO_FUERA_DE_CATALOGO}.")
    lineas.append(PROCEDENCIA_A2A)
    lineas.extend(riesgos.lista)  # lo retirado por el barrido hasta aquí
    for linea in lineas:
        parrafo(doc, f"• {sin_ids_hallazgo(linea)}")


def _datos_economicos(estado: dict, riesgos: _Riesgos, catalogo: dict) -> dict:
    """Prepara (y barre) los datos de la sección 7 antes de escribir los riesgos residuales."""
    carga = _carga(estado)
    resumen = (carga.get("estimacion") or {}).get("resumen") or {}
    anexo = carga.get("anexo_consumo") or {}
    ajuste = (carga.get("estimacion") or {}).get("ajuste")
    return {
        "resumen": resumen,
        "perfiles": [[riesgos.seguro(p.get("perfil"), "perfil"), _horas(p.get("horas")), _horas(p.get("tarifa_hora")),
                      formato_eur(p.get("importe_eur"))] for p in resumen.get("por_perfil") or []],
        "fases": [[riesgos.seguro(f.get("fase"), "fase de la estimación"), _horas(f.get("horas"))]
                  for f in resumen.get("por_fase") or []],
        "hitos": [[riesgos.seguro(h.get("nombre"), "hito"), f"{h.get('porcentaje')} %",
                   formato_eur(h.get("importe_eur"))] for h in resumen.get("hitos") or []],
        "anexo": anexo,
        "ajuste": ajuste,
        "sin_precio": anexo_consumo.no_valorados(estado, catalogo) if anexo else [],
    }


def _seccion_economica(doc, econ: dict) -> None:
    titulo(doc, "7. Resumen económico interno (no se envía al cliente)")
    r = econ["resumen"]
    if not r:
        parrafo(doc, "Sin estimación registrada.")
        return
    anexo = econ["anexo"]
    ajuste = econ["ajuste"]
    filas = [["Concepto", "Valor"],
             ["Precio cerrado (IVA no incluido)", formato_eur(r.get("precio_cerrado_eur"))],
             ["Subtotal de servicios", formato_eur(r.get("subtotal_eur"))],
             ["Ajuste comercial", formato_eur(r.get("ajuste_eur") or "0")
              + (f" (decisión {ajuste.get('decision_id')})" if ajuste else " (sin ajuste)")],
             ["Horas totales", _horas(r.get("horas_total"))],  # VA18-9: formato español
             ["Gestión de proyecto", f"{_horas(r.get('pm_h'))} h ({_horas(r.get('pm_pct'))} % del total)"],
             ["Duración", f"{r.get('duracion_semanas')} semanas"]]
    if anexo:
        sin_precio = econ.get("sin_precio") or []
        nv = (f"; sin valorar: {', '.join(x['servicio'] for x in sin_precio)} (motivo en los riesgos residuales)"
              if sin_precio else "")
        filas.append(["Consumo cloud orientativo (anexo)", f"{formato_eur(anexo.get('total_mensual_eur'))} al mes; "
                                                           f"{formato_eur(anexo.get('total_anual_eur'))} al año{nv}"])
        filas.append(["Precios del consumo", f"consultados el {(anexo.get('fuente') or {}).get('consultado_el') or '—'} "
                                             "en Azure Retail Prices (EUR)"])
    tabla(doc, filas, [6, 10.5])
    titulo(doc, "Horas e importe por perfil", 2)
    tabla(doc, [["Perfil", "Horas", "Tarifa (EUR/h)", "Importe"]] + econ["perfiles"], [6.5, 2.5, 3, 4.5])
    titulo(doc, "Horas por fase", 2)
    tabla(doc, [["Fase", "Horas"]] + econ["fases"], [12, 4.5])
    titulo(doc, "Hitos de facturación", 2)
    tabla(doc, [["Hito", "%", "Importe"]] + econ["hitos"], [10, 2, 4.5])


NOMBRES_ARTEFACTO = (("xlsx_estimacion", "Estimación interna (XLSX canónico, sin modificar)"),
                     ("anexo_xlsx", "Anexo de consumo (XLSX)"), ("anexo_json", "Anexo de consumo (JSON)"),
                     ("pptx", "Propuesta para revisión (PPTX)"))


def _seccion_ficheros(doc, estado: dict) -> None:
    titulo(doc, "8. Ficheros del paquete")
    artefactos = estado.get("artefactos") or {}
    filas = [["Fichero", "Contenido", "SHA-256"]]
    for clave, descripcion in NOMBRES_ARTEFACTO:
        a = artefactos.get(clave)
        if a:
            filas.append([a.get("nombre") or "", descripcion, a.get("sha256") or ""])
    if len(filas) == 1:
        filas.append(["—", "Sin ficheros registrados", "—"])
    tabla(doc, filas, [5.5, 4.5, 6.5], 7.5)
    parrafo(doc, "El SHA-256 de esta nota, de los mensajes, de estado.json y del ZIP figura en "
                 "manifiesto_paquete.json, dentro del mismo paquete.")


# ───────────── VER17-2 (I1.8): «Cambios pedidos en la revisión anterior», solo en la nota del revisor ─────────────
AVISO_CAMBIOS = ("Sección interna para el revisor: el comentario y cómo se atendió no se copian en la presentación "
                 "del cliente.")


def nombres_claves(estado: dict, catalogo: dict) -> dict[str, str]:
    """R17-4/INT17-4: {clave técnica de decision.resumen_version: nombre legible} de la versión devuelta y la vigente.
    «az-app-service» da «Azure App Service»; «az-app-service · p0v3-linux», «Azure App Service, P0v3 App» (el
    concepto de la plantilla en el catálogo); «desviación: X», «X (fuera del catálogo)». Una clave que el catálogo
    no conoce se queda como está (se ve, no se inventa un nombre)."""
    comps = {c.get("id"): c for c in (catalogo or {}).get("componentes") or [] if isinstance(c, dict)}
    devueltas = decision.comentarios_devuelta(estado)
    registro = next((d for d in reversed(estado.get("decisiones") or [])
                     if devueltas and d.get("id") == devueltas[-1]["id"]), {})
    resumenes = [r for r in (registro.get("version_devuelta"), decision.resumen_version(estado)) if isinstance(r, dict)]
    claves = {str(x.get("clave")) for r in resumenes for campo in ("componentes", "precios")
              for x in r.get(campo) or [] if isinstance(x, dict) and x.get("clave")}
    salida = {}
    for clave in claves:
        cat, _, plantilla = clave.partition(" · ")
        comp = comps.get(cat)
        if clave.startswith("desviación: "):
            salida[clave] = f"{clave.removeprefix('desviación: ')} (fuera del catálogo)"
        elif comp is None:
            continue
        elif not plantilla:
            salida[clave] = comp.get("nombre_oficial") or clave
        else:
            fila = next((p for p in comp.get("plantillas_precio") or [] if p.get("id") == plantilla), None)
            concepto = (fila or {}).get("concepto") or f"consulta de precios propia ({plantilla})"
            salida[clave] = f"{comp.get('nombre_oficial') or cat}, {concepto}"
    return salida


def lineas_cambios_nota(estado: dict, catalogo: dict) -> list[str]:
    """VER17-2 (I1.8): líneas de «Cambios pedidos en la revisión anterior» para la nota del revisor ([] si no aplica):
    las de decision.lineas_cambios_pedidos con importes y el comentario literal, más el aviso de que no van al cliente,
    con el nombre legible de cada servicio y plantilla en lugar de su clave técnica (nombres_claves). El comentario del
    revisor se copia tal cual, sin sustituir nada dentro. La puerta busca cada línea en la nota (CAMBIOS-I18-D.md)."""
    lineas = decision.lineas_cambios_pedidos(estado, con_importes=True)
    if not lineas:
        return []
    literales = tuple(f"Comentario de {c['revisor']} ({c['id']}): " for c in decision.comentarios_devuelta(estado))
    nombres = nombres_claves(estado, catalogo)
    patron = (re.compile(r"(?<![\w-])(" + "|".join(re.escape(k) for k in sorted(nombres, key=len, reverse=True))
                         + r")(?![\w-])") if nombres else None)
    salida = []
    for ln in lineas:
        if patron is None or ln.startswith(literales):
            salida.append(ln)
        else:
            salida.append(_cifras_es(patron.sub(lambda m: nombres[m.group(1)], ln)))
    devueltas = decision.comentarios_devuelta(estado)
    registro = next((d for d in reversed(estado.get("decisiones") or [])
                     if devueltas and d.get("id") == devueltas[-1]["id"]), {})
    devuelta = registro.get("version_devuelta")
    antes = devuelta.get("estimacion") if isinstance(devuelta, dict) else None
    return salida[:1] + [AVISO_CAMBIOS] + salida[1:] + lineas_estimacion(antes, resumen_estimacion(estado))


# ───────────── VA18-3 (I1.9): lo que cambia en la estimación, calculado por código (solo para el revisor) ─────────────
AVISO_SIN_ESTIMACION = ("Estimación: la versión devuelta no guardó su estimación (decisión anterior a I1.9), así que la "
                        "duración, las horas y los perfiles que cambian no se pueden calcular aquí; compara las dos "
                        "estimaciones antes de aprobar.")


def resumen_estimacion(estado: dict) -> dict:
    """VA18-3 (I1.9): duración, horas totales, horas por perfil y por fase y tareas de la estimación vigente
    (carga.estimacion); {} si no hay. La DEVUELTA lo guarda en version_devuelta.estimacion (decision.resumen_version,
    propuesta en docs/I1/CAMBIOS-I19-P.md) para que la versión siguiente diga qué cambió."""
    est = _carga(estado).get("estimacion") or {}
    entrada, resumen = est.get("entrada") or {}, est.get("resumen") or {}
    if not isinstance(entrada, dict) or not isinstance(resumen, dict) or not (entrada or resumen):
        return {}
    return {"duracion_semanas": entrada.get("duracion_semanas"), "horas_total": resumen.get("horas_total"),
            "por_perfil": [{"perfil": x.get("perfil"), "horas": x.get("horas")} for x in resumen.get("por_perfil") or []
                           if isinstance(x, dict)],
            "por_fase": [{"fase": x.get("fase"), "horas": x.get("horas")} for x in resumen.get("por_fase") or []
                         if isinstance(x, dict)],
            "tareas": [{k: t.get(k) for k in ("fase", "tarea", "perfil", "tecnicas_h", "reuniones_h")}
                       for t in entrada.get("tareas") or [] if isinstance(t, dict)]}


def _horas(x: object) -> str:
    """Horas en formato español: «197», «213,5», «1.200»; «0» para cero; el texto tal cual si no es un número."""
    try:
        d = Decimal(str(x))
    except (InvalidOperation, ValueError):
        return str(x)
    if not d.is_finite():
        return str(x)
    return "0" if d == 0 else ("-" if d < 0 else "") + (textos_cliente.numero_es(abs(d)) or str(x))


def _comparar_horas(antes: list, ahora: list, clave: str, de: str, articulo: str) -> list[str]:
    """Una línea por perfil o fase que cambia de horas, sale o entra (en el orden de la versión devuelta)."""
    a = {str(x.get(clave)): x.get("horas") for x in antes if isinstance(x, dict)}
    b = {str(x.get(clave)): x.get("horas") for x in ahora if isinstance(x, dict)}
    salida = []
    for k in list(a) + [k for k in b if k not in a]:
        if k in a and k in b:
            if _horas(a[k]) != _horas(b[k]):
                salida.append(f"Estimación: horas {de} «{k}» de {_horas(a[k])} a {_horas(b[k])}")
        elif k in a:
            salida.append(f"Estimación: sale {articulo} «{k}» ({_horas(a[k])} h)")
        else:
            salida.append(f"Estimación: entra {articulo} «{k}» ({_horas(b[k])} h)")
    return salida


def lineas_estimacion(antes: object, ahora: dict) -> list[str]:
    """VA18-3 (I1.9): líneas de «Cambios pedidos…» con lo que cambia en la estimación entre la versión devuelta
    (`antes`, su resumen_estimacion) y la vigente: duración, horas totales, horas por perfil y por fase (lo que entra y
    lo que sale) y si las tareas se han replanificado. Sin `antes`, AVISO_SIN_ESTIMACION (no se calla)."""
    if not isinstance(antes, dict) or not antes:
        return [AVISO_SIN_ESTIMACION]
    salida = []
    da, db = antes.get("duracion_semanas"), ahora.get("duracion_semanas")
    salida.append(f"Estimación: duración de {da} a {db} semanas" if da != db
                  else f"Estimación: duración sin cambios ({db} semanas)")
    ha, hb = antes.get("horas_total"), ahora.get("horas_total")
    try:
        dif = Decimal(str(hb)) - Decimal(str(ha))
    except (InvalidOperation, ValueError):
        dif = None
    if dif is None or not dif.is_finite():
        salida.append(f"Estimación: horas totales de {_horas(ha)} a {_horas(hb)}")
    elif dif:
        salida.append(f"Estimación: horas totales de {_horas(ha)} a {_horas(hb)} ({'+' if dif > 0 else ''}{_horas(dif)} h)")
    else:
        salida.append(f"Estimación: horas totales sin cambios ({_horas(hb)})")
    salida += _comparar_horas(antes.get("por_perfil") or [], ahora.get("por_perfil") or [], "perfil", "del perfil",
                              "el perfil")
    salida += _comparar_horas(antes.get("por_fase") or [], ahora.get("por_fase") or [], "fase", "de la fase", "la fase")
    ta, tb = antes.get("tareas") or [], ahora.get("tareas") or []
    resto = [json.dumps(x, sort_keys=True, ensure_ascii=False) for x in ta]
    iguales = 0
    for x in tb:
        k = json.dumps(x, sort_keys=True, ensure_ascii=False)
        if k in resto:
            resto.remove(k)
            iguales += 1
    if iguales < len(ta) or iguales < len(tb):
        salida.append(f"Estimación: tareas de {len(ta)} a {len(tb)}, {iguales} sin cambios: la estimación se ha "
                      + ("recalculado entera" if iguales == 0 else "replanificado") + " (ver las dos estimaciones)")
    return salida


_RE_IMPORTE_CAMBIO = re.compile(r"(?<![\w.,])(\d+(?:\.\d+)?) €")
_RE_CANTIDAD_CAMBIO = re.compile(r"(?:(?<=\()|(?<=: de )|(?<= a ))(\d+(?:\.\d+)?)(?= al mes| a \d)")


def _cifras_es(linea: str) -> str:
    """Importes («23457.50 €» → «23.457,50 €») y cantidades mensuales («(6 al mes)», «de 1200 a 1500 al mes») en
    formato español (LES-G-037). Solo esos dos patrones: una cifra dentro de un nombre («P0v3», «gpt-5.4») no se toca."""
    linea = _RE_IMPORTE_CAMBIO.sub(lambda m: formato_eur(m.group(1)), linea)
    return _RE_CANTIDAD_CAMBIO.sub(lambda m: textos_cliente.numero_es(m.group(1)) or m.group(1), linea)


def lineas_decision(estado: dict, hash_vigente: str) -> list[tuple[str, str]]:
    """[(quién, línea)] listas para copiar, con el hash vigente ya escrito (§10)."""
    return [
        ("El comercial, tras verificar_paquete.py con rc 0",
         f"DECISION | Responsable comercial | ENVIADA_REVISION | AAAA-MM-DD | {hash_vigente} | verificar_paquete rc=0"),
        ("Responsable de preventa, si aprueba",
         f"DECISION | Responsable de preventa | APROBADA | AAAA-MM-DD | {hash_vigente} | comentarios"),
        ("Responsable de preventa, si devuelve (comentario de al menos 10 caracteres)",
         f"DECISION | Responsable de preventa | DEVUELTA | AAAA-MM-DD | {hash_vigente} | comentarios"),
        ("Responsable de área, si aprueba (después del responsable de preventa)",
         f"DECISION | Responsable de área | APROBADA | AAAA-MM-DD | {hash_vigente} | comentarios"),
        ("Responsable de área, si devuelve",
         f"DECISION | Responsable de área | DEVUELTA | AAAA-MM-DD | {hash_vigente} | comentarios"),
    ]


def lineas_registro_decisiones(estado: dict) -> list[str]:
    """VA18-18 (I1.9): una línea por decisión registrada, en orden: id, fecha, quién, qué, versión, huella citada y
    comentarios. Es lo que sustituye a «Cómo decidir» en la nota de una propuesta APROBADA."""
    salida = []
    for d in estado.get("decisiones") or []:
        if not isinstance(d, dict):
            continue
        com = " ".join(str(d.get("comentarios") or "").split())
        salida.append(f"{d.get('id')} · {d.get('fecha')} · {d.get('revisor')} · {d.get('tipo')} · versión "
                      f"{d.get('version')} · huella {str(d.get('hash_citado') or '')[:12]}…"
                      + (f" · «{com}»" if com else ""))
    return salida


def _seccion_registro(doc, estado: dict, hash_vigente: str) -> None:
    """VA18-18 (I1.9): en la APROBADA no quedan decisiones que tomar; se registra quién decidió qué y cuándo."""
    titulo(doc, "9. Registro de decisiones")
    parrafo(doc, f"Propuesta aprobada con la huella {hash_vigente}. Decisiones registradas, en orden (el original de "
                 "cada una consta en estado.json):")
    riesgos = _Riesgos()
    for ln in lineas_registro_decisiones(estado):
        parrafo(doc, riesgos.seguro(ln, "registro de decisiones"), tam=8.5)
    for r in riesgos.lista:
        parrafo(doc, r, tam=8.5)


def _seccion_decidir(doc, estado: dict, hash_vigente: str) -> None:
    if estado.get("estado") == "APROBADA":  # VA18-18 (I1.9)
        _seccion_registro(doc, estado, hash_vigente)
        return
    titulo(doc, "9. Cómo decidir")
    parrafo(doc, "Copie la línea que corresponda, sustituya AAAA-MM-DD por la fecha y «comentarios» por sus "
                 "observaciones, y devuélvasela al comercial. Una decisión solo vale si cita esta huella; si el "
                 "contenido cambia, la huella cambia y hay que volver a revisar.")
    for quien, linea in lineas_decision(estado, hash_vigente):
        parrafo(doc, quien, negrita=True)
        parrafo(doc, linea, tam=8.5)


# ---------------------------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------------------------
def textos_docx(doc) -> list[str]:
    """Texto de cada párrafo del cuerpo y de cada celda, y de las propiedades del documento."""
    salida = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for fila in t.rows:
            salida.extend(c.text for c in fila.cells)
    cp = doc.core_properties
    salida.extend(getattr(cp, campo) or "" for campo in ("title", "author", "last_modified_by", "subject",
                                                          "comments", "category"))
    return [x for x in salida if x]


def construir(estado: dict, catalogo: dict, transcripcion=None):
    """Documento en memoria (sin guardar). `catalogo` da los nombres oficiales de lo no valorado (H9)."""
    hash_vigente = hashes.hash_contenido(estado)
    if estado.get("hash_contenido") != hash_vigente:
        raise _fallo(errores.IntegridadRota, "la nota no se genera: el hash_contenido guardado no es el recalculado",
                     [f"guardado {estado.get('hash_contenido')}", f"recalculado {hash_vigente}"])
    doc = Document()
    seccion = doc.sections[0]
    seccion.page_width, seccion.page_height = Cm(21), Cm(29.7)
    for lado in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(seccion, lado, Cm(2))
    aplicar_marca(doc)
    riesgos = _Riesgos()
    alta = _carga(estado).get("alta") or {}
    parrafo(doc, "Nota de revisión interna", negrita=True, color=OSCURO, tam=22)
    parrafo(doc, f"{estado.get('codigo')} · {riesgos.seguro(alta.get('titulo'), 'título')}", color=ROJO, tam=12,
            negrita=True)
    parrafo(doc, "Documento interno para Responsable de preventa (revisión de preventa) y Responsable de área (aprobación "
                 "del área). No se envía al cliente: contiene horas, perfiles e importes internos.", tam=9)
    if est_mod.sin_grabacion(estado):   # notas del comercial (NOTAS_COMERCIAL.md): aviso destacado, solo en lo interno
        parrafo(doc, est_mod.AVISO_SIN_GRABACION, negrita=True, color=ROJO, tam=11)
    _seccion_identificacion(doc, estado, hash_vigente)
    _seccion_comprobacion(doc)
    cambios = lineas_cambios_nota(estado, catalogo)  # VER16-5 (I1.7) y VER17-2 (I1.8): solo en la nota
    if cambios:  # VA18-8 (I1.9): la primera línea es el título de la sección (una vez, no dos)
        titulo(doc, cambios[0])
        for ln in cambios[1:]:
            parrafo(doc, ln, tam=9)
    asumidos = _seccion_requisitos(doc, estado, riesgos)
    _seccion_frases_sin_cita(doc, estado, transcripcion, riesgos)
    _seccion_baja(doc, estado, asumidos, riesgos)
    no_verif = _seccion_verificacion(doc, estado, riesgos)
    econ = _datos_economicos(estado, riesgos, catalogo)
    _seccion_riesgos(doc, estado, no_verif, riesgos, catalogo)
    _seccion_economica(doc, econ)
    _seccion_ficheros(doc, estado)
    _seccion_decidir(doc, estado, hash_vigente)
    cp = doc.core_properties
    cp.title = f"{estado.get('codigo')} · Nota de revisión"
    cp.author = AUTOR
    cp.last_modified_by = AUTOR
    cp.subject = alta.get("titulo") or ""
    cp.keywords = f"hash_contenido:{hash_vigente}"
    cp.comments = ""
    cp.category = "Preventa"
    cp.revision = 1
    cp.language = "es-ES"
    limpiar_paquete(doc.part.package)
    hallazgos = sorted({f"{h} en «{t[:80]}»" for t in textos_docx(doc) for h in textos_cliente.marcadores(t)})
    if hallazgos:
        raise _fallo(errores.ReglaIncumplida, "la nota no se publica: contiene marcadores (P9)", hallazgos)
    return doc


def generar(estado: dict, catalogo: dict, ruta: pathlib.Path, transcripcion=None) -> str:
    """Genera la nota de revisión en `ruta` y devuelve su SHA-256 (CONTRATOS.md §4.15).

    `transcripcion`: texto de F1 (o la excepción por la que no se pudo leer) para el apartado de frases sin cita.
    """
    return guardar_atomico(construir(estado, catalogo, transcripcion), ruta)
