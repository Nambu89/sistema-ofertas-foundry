"""Constructor de paquetes de preventa de prueba (caso sintético OF-KELVARA-001-A).

Parte de `esquemas/ejemplos/estado.json` (P0) y produce un paquete real: XLSX con el generador
canónico SIN modificar, anexo XLSX y JSON, PPTX y DOCX de revisión, mensajes, estado.json,
manifiesto y ZIP. Los ganchos permiten introducir un defecto concreto en cada test.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import zipfile
from decimal import Decimal
from typing import Callable

import openpyxl
from openpyxl.styles import Font, PatternFill

RAIZ = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
import verificar_paquete as vp  # noqa: E402
from tests.fixtures_i1 import pptx_fixture  # noqa: E402

EJEMPLOS = RAIZ / "esquemas" / "ejemplos"
TRANSCRIPCION = RAIZ / "datos_prueba" / "transcripcion_sintetica_I1.txt"
CATALOGO = EJEMPLOS / "catalogo_componentes.json"
RATE_CARD = RAIZ / "tests" / "insumos" / "rate-card.sintetica.json"
# I1.7 (R): instantánea de precios sintética del catálogo de ejemplo, anterior a generado_ts de los paquetes de prueba
# (la genera pruebas/I17/R/generar_instantanea_ejemplo.py). Su huella va en montados y la puerta la recibe con --precios.
INSTANTANEA = pathlib.Path(__file__).resolve().parent / "precios_instantanea_ejemplo.json"
_CACHE_XLSX: dict[str, bytes] = {}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def estado_base() -> dict:
    return json.loads((EJEMPLOS / "estado.json").read_text(encoding="utf-8"))


def catalogo() -> dict:
    return json.loads(CATALOGO.read_text(encoding="utf-8"))


def generar_xlsx(entrada: dict, destino: pathlib.Path, trabajo: pathlib.Path) -> None:
    """Ejecuta el generador canónico, sin tocarlo, en un árbol temporal como el sandbox."""
    clave = vp.hash_json(entrada)
    if clave not in _CACHE_XLSX:
        base = trabajo / f"base_{clave[:12]}"
        est = base / "_templates" / "estimacion"
        est.mkdir(parents=True)
        (base / "_config").mkdir()
        shutil.copyfile(vp.POR_DEFECTO["generador"], est / "generar_estimacion.py")
        shutil.copyfile(vp.POR_DEFECTO["plantilla"], est / vp.POR_DEFECTO["plantilla"].name)
        tarifa = json.loads(RATE_CARD.read_text(encoding="utf-8"))["tarifa"]
        (base / "_config" / "rate-card.json").write_text(json.dumps(tarifa, ensure_ascii=False), encoding="utf-8")
        datos = base / "entrada.json"
        datos.write_text(json.dumps(entrada, ensure_ascii=False), encoding="utf-8")
        salida = base / "salida.xlsx"
        r = subprocess.run([sys.executable, str(est / "generar_estimacion.py"), str(datos), str(salida)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"generador canónico rc={r.returncode}: {r.stdout[-800:]} {r.stderr[-400:]}")
        _CACHE_XLSX[clave] = salida.read_bytes()
    destino.write_bytes(_CACHE_XLSX[clave])


def recalcular_economia(estado: dict, xlsx: pathlib.Path) -> None:
    """Deja resumen y textos_cliente coherentes con el XLSX generado (para aislar cada defecto)."""
    x = vp.leer_xlsx_canonico(xlsx)
    carga = estado["carga"]
    res = carga["estimacion"]["resumen"]
    res["precio_cerrado_eur"] = f"{x.precio:.2f}"
    res["subtotal_eur"] = f"{x.subtotal:.2f}"
    res["ajuste_eur"] = f"{(x.ajuste or Decimal(0)):.2f}"
    res["horas_total"], res["pm_h"] = f"{x.horas_total:.2f}", f"{x.pm_h:.2f}"
    for h, hx in zip(res["hitos"], x.hitos):
        h["importe_eur"] = f"{hx['importe']:.2f}"
    tc = carga["textos_cliente"]
    tc["precio"]["precio_cerrado_eur"] = res["precio_cerrado_eur"]
    tc["precio"]["hitos"] = copy.deepcopy(res["hitos"])
    for f in tc["condiciones"]:
        if f["id"] == "TX-CON-01":
            f["texto"] = f"Precio cerrado de {pptx_fixture.eur(res['precio_cerrado_eur'])}, IVA no incluido."
    atar_textos(estado)


def atar_textos(estado: dict) -> None:
    carga = estado["carga"]
    base = {k: carga[k] for k in ("alta", "requisitos", "respuestas_expertos", "verificacion", "anexo_consumo")}
    base["estimacion_resumen"] = carga["estimacion"]["resumen"]
    carga["textos_cliente"]["hash_hechos"] = vp.hash_json(base)


_CACHE_ANEXO: dict[str, bytes] = {}


def anexo_xlsx(anexo: dict, ruta: pathlib.Path, color_fuera: str | None = None) -> None:
    """Anexo XLSX; se cachea por contenido porque openpyxl escribe fechas (como en el sandbox,
    donde `paquete` no lo regenera)."""
    clave = vp.hash_json([anexo, color_fuera])
    if clave not in _CACHE_ANEXO:
        _anexo_xlsx(anexo, ruta, color_fuera)
        _CACHE_ANEXO[clave] = ruta.read_bytes()
    ruta.write_bytes(_CACHE_ANEXO[clave])


def _anexo_xlsx(anexo: dict, ruta: pathlib.Path, color_fuera: str | None) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Consumo"
    cab = ["Servicio", "Concepto", "Precio unitario", "Unidad", "Cantidad mensual", "Coste mensual (EUR)"]
    for j, t in enumerate(cab, 1):
        c = ws.cell(1, j, t)
        c.font = Font(name="Montserrat", bold=True, color=color_fuera or "FFFFFF")
        c.fill = PatternFill("solid", fgColor="F8485E")
    for i, ln in enumerate(anexo["lineas"], 2):
        for j, v in enumerate([ln["servicio"], ln["concepto"], ln["precio_unitario"], ln["unidad"],
                               ln["cantidad_mensual"], float(ln["coste_mensual_eur"])], 1):
            ws.cell(i, j, v).font = Font(name="Montserrat", color="3C3C3A")
    wb.save(ruta)


_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def nota_docx(estado: dict, ruta: pathlib.Path, extra: list[str] | None = None, fuente: str = "Montserrat") -> None:
    """DOCX mínimo de la nota de revisión (forma de §9.5), sin python-docx."""
    carga, h = estado["carga"], estado["hash_contenido"]
    lineas = ["Nota de revisión", f"Código: {estado['codigo']}", f"Versión: {estado['version']}",
              f"Huella del contenido: {h}", "Requisitos con su cita y origen"]
    for campo, info in carga["requisitos"]["campos"].items():
        for e in info["entradas"]:
            lineas.append(f"{campo}: {e['valor']} · {e['origen']}" + (f" · «{e['cita']}»" if e.get("cita") else ""))
    res = carga["estimacion"]["resumen"]
    lineas += ["Resumen económico interno", f"Precio cerrado: {res['precio_cerrado_eur']} EUR",
               f"Horas totales: {res['horas_total']}",
               f"Cómo decidir: DECISION | Responsable de preventa | APROBADA | AAAA-MM-DD | {h} | comentarios"]
    lineas += extra or []
    rpr = f'<w:rPr><w:rFonts w:ascii="{fuente}" w:hAnsi="{fuente}" w:cs="{fuente}" w:eastAsia="{fuente}"/>' \
          '<w:color w:val="3C3C3A"/></w:rPr>'
    cuerpo = "".join(f'<w:p><w:r>{rpr}<w:t xml:space="preserve">{_esc(t)}</w:t></w:r></w:p>' for t in lineas)
    partes = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/></Relationships>',
        "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        "word/document.xml": f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{_W}"><w:body>{cuerpo}</w:body></w:document>',
        "word/styles.xml": f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{_W}"><w:docDefaults><w:rPrDefault>{rpr}</w:rPrDefault></w:docDefaults></w:styles>',
        "docProps/core.xml": '<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                             f'<dc:title>{estado["codigo"]} · Nota de revisión</dc:title><dc:creator>Responsable comercial</dc:creator>'
                             f'<cp:keywords>hash_contenido:{h}</cp:keywords></cp:coreProperties>',
    }
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as z:
        for n, t in partes.items():
            z.writestr(n, t.encode("utf-8"))


def mensajes(estado: dict, zip_nombre: str) -> tuple[str, str]:
    h, cod, tit = estado["hash_contenido"], estado["codigo"], estado["carga"]["alta"]["titulo"]
    jav = (f"Asunto: [Revisión preventa] {cod} · {tit}\n\nHola, responsable de preventa:\n\nTe adjunto {zip_nombre} para su revisión "
           f"(arquitectura, referencias, precios cloud y estimación interna).\nHuella del contenido: {h}\n\n"
           f"Respuesta:\nDECISION | Responsable de preventa | APROBADA | AAAA-MM-DD | {h} | comentarios\n\nResponsable comercial\n")
    jp = (f"Asunto: [Aprobación preventa] {cod} · {tit}\n\nHola, responsable de área:\n\nTras la revisión del responsable de preventa, te "
          f"adjunto {zip_nombre} (diagrama, precio cerrado e hitos).\nHuella del contenido: {h}\n\nRespuesta:\n"
          f"DECISION | Responsable de área | APROBADA | AAAA-MM-DD | {h} | comentarios\n\nResponsable comercial\n")
    return jav, jp


def decision(estado: dict, revisor: str, tipo: str, fecha: str, hash_citado: str, comentarios: str,
             antes: str, despues: str) -> dict:
    n = len(estado["decisiones"]) + 1
    canonico = {vp.plano(x): x for x in ("Responsable comercial", "Responsable de preventa", "Responsable de área")}
    d = {"id": f"D-{n:03d}", "linea": f"DECISION | {revisor} | {tipo} | {fecha} | {hash_citado} | {comentarios}",
         "revisor": canonico.get(vp.plano(revisor), revisor), "tipo": tipo, "fecha": fecha, "hash_citado": hash_citado, "comentarios": comentarios,
         "version": estado["version"], "estado_antes": antes, "estado_despues": despues,
         "registrada_ts": f"{fecha}T10:00:00+02:00"}
    estado["decisiones"].append(d)
    return d


def construir(destino: pathlib.Path, *, mutar_carga: Callable[[dict], None] | None = None,
              entrada_xlsx: Callable[[dict], None] | None = None, coherente: bool = True,
              mutar_estado: Callable[[dict], None] | None = None, pptx_op: dict | None = None,
              firmas: dict | None = None, docx_extra: list[str] | None = None, docx_fuente: str = "Montserrat",
              anexo_color: str | None = None, mensaje_extra: str = "",
              despues: Callable[[pathlib.Path], None] | None = None, zip_: bool = True,
              tocar_xlsx: Callable[[pathlib.Path], None] | None = None) -> pathlib.Path:
    """Construye el paquete en `destino` y devuelve la ruta del ZIP (o de la carpeta si zip_=False).

    Orden: mutar_carga → XLSX (entrada_xlsx solo cambia lo que recibe el generador) → resumen y
    textos coherentes con el XLSX (si `coherente`) → hash → mutar_estado (decisiones) → ficheros →
    manifiesto → despues (manipulación posterior al manifiesto) → ZIP.
    """
    destino.mkdir(parents=True, exist_ok=True)
    carpeta = destino / "contenido"
    carpeta.mkdir()
    estado = estado_base()
    if mutar_carga:
        mutar_carga(estado)
    cod = estado["codigo"]
    entrada = copy.deepcopy(estado["carga"]["estimacion"]["entrada"])
    if entrada_xlsx:
        entrada_xlsx(entrada)
    xlsx = carpeta / f"{cod}-Estimacion.xlsx"
    generar_xlsx(entrada, xlsx, destino)
    if tocar_xlsx:
        tocar_xlsx(xlsx)
    if coherente:
        recalcular_economia(estado, xlsx)
    estado["hash_contenido"] = vp.hash_json(estado["carga"])
    estado.setdefault("orquestador", "A")   # REV15-2 (I1.6): el núcleo desde I1.5 marca estado y manifiesto
    if mutar_estado:
        mutar_estado(estado)
    cat = catalogo()
    zip_nombre = f"{cod}-Paquete.zip"
    (carpeta / f"{cod}-Anexo-Consumo.json").write_text(
        json.dumps(estado["carga"]["anexo_consumo"], ensure_ascii=False, indent=2), encoding="utf-8")
    anexo_xlsx(estado["carga"]["anexo_consumo"], carpeta / f"{cod}-Anexo-Consumo.xlsx", anexo_color)
    pptx_fixture.generar(estado, cat, carpeta / f"{cod}-Revision.pptx", firmas, **(pptx_op or {}))
    nota_docx(estado, carpeta / f"{cod}-Nota-Revision.docx", docx_extra, docx_fuente)
    jav, jp = mensajes(estado, zip_nombre)
    (carpeta / "mensaje_revisor.txt").write_text(jav + mensaje_extra, encoding="utf-8")
    (carpeta / "mensaje_aprobador.txt").write_text(jp, encoding="utf-8")
    art = estado["artefactos"]
    for clave, suf in (("xlsx_estimacion", "Estimacion.xlsx"), ("anexo_xlsx", "Anexo-Consumo.xlsx"),
                       ("anexo_json", "Anexo-Consumo.json"), ("pptx", "Revision.pptx"),
                       ("docx", "Nota-Revision.docx")):
        datos = (carpeta / f"{cod}-{suf}").read_bytes()
        art[clave] = {"nombre": f"{cod}-{suf}", "sha256": sha(datos), "bytes": len(datos)}
    (carpeta / "estado.json").write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    ficheros = []
    for n in vp.nombres_paquete(cod):
        if n == "manifiesto_paquete.json":
            continue
        datos = (carpeta / n).read_bytes()
        ficheros.append({"nombre": n, "sha256": sha(datos), "bytes": len(datos)})
    manifiesto = {"schema": "preventa-manifiesto-paquete/1", "codigo": cod, "version": estado["version"],
                  "estado": estado["estado"], "hash_contenido": estado["hash_contenido"],
                  "estado_json_sha256": sha((carpeta / "estado.json").read_bytes()), "ficheros": ficheros,
                  "montados": {"rate_card_sha256": sha(RATE_CARD.read_bytes()),
                               "generador_sha256": sha(vp.POR_DEFECTO["generador"].read_bytes()),
                               "plantilla_sha256": sha(vp.POR_DEFECTO["plantilla"].read_bytes()),
                               "catalogo_sha256": sha(CATALOGO.read_bytes()),
                               "precios_instantanea_sha256": sha(INSTANTANEA.read_bytes())},
                  "generado_ts": "2026-10-08T10:11:00+02:00",
                  **({"orquestador": estado["orquestador"]} if "orquestador" in estado else {})}
    (carpeta / "manifiesto_paquete.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2),
                                                     encoding="utf-8")
    if despues:
        despues(carpeta)
    if not zip_:
        return carpeta
    ruta_zip = destino / zip_nombre
    with zipfile.ZipFile(ruta_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(carpeta.iterdir()):
            z.write(p, p.name)
    return ruta_zip


def argumentos(paquete: pathlib.Path, *extra: str) -> list[str]:
    """Argumentos de verificar_paquete.main para un paquete de prueba (sin red, catálogo de ejemplo)."""
    return [str(paquete), "--transcripcion", str(TRANSCRIPCION), "--catalogo", str(CATALOGO),
            "--rate-card", str(RATE_CARD), "--precios", str(INSTANTANEA), "--sin-red", "--hoy", "2026-10-10", *extra]
