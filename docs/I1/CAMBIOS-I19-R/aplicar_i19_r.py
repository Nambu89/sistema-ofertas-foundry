"""I1.9 · papel R · cambios en ficheros de OTROS papeles, para el integrador (docs/I1/CAMBIOS-I19-R.md §3).

Uso: python docs/I1/CAMBIOS-I19-R/aplicar_i19_r.py <raíz del repositorio> [--comprobar]

Cada cambio es un reemplazo literal que tiene que aparecer exactamente una vez; si ya está aplicado, se salta y se dice.
Conserva los finales de línea de cada fichero (cuenta los CR antes y después). Con --comprobar no escribe nada: dice qué
está aplicado, qué falta y qué no encuentra (rc 1 si falta algo o no encuentra el anclaje).

1. esquemas/manifiesto_paquete.json (P0): el nombre del PPTX admite «Propuesta.pptx» (VA18-7, entregable en APROBADA).
2. sandbox/nucleo/pptx_revision.py (D): title «<codigo> · Propuesta comercial» en APROBADA (VA18-7); y VPROT-1 en
   revision_interna_en_pptx (texto alternativo, diseños y patrones), las mismas líneas que la réplica de la puerta.
3. sandbox/preventa_run.py (integrador): registrar-verificacion pasa el catálogo montado a verificacion.registrar
   (VC18-3) e imprime el motivo de cada DISCREPA con verificacion.lineas_discrepa_turno (PR18-7, también en A).
"""
from __future__ import annotations

import pathlib
import sys

CAMBIOS = [
    ("esquemas/manifiesto_paquete.json", "VA18-7 · nombre Propuesta.pptx",
     r"|Revision\\.pptx|Nota-Revision\\.docx)",
     r"|Revision\\.pptx|Propuesta\\.pptx|Nota-Revision\\.docx)"),
    ("sandbox/nucleo/pptx_revision.py", "VA18-7 · title en APROBADA (definición)",
     '''def _propiedades(prs, textos: dict, hash_vigente: str) -> None:
    cp = prs.core_properties
    cp.title = f"{textos['codigo']} · Propuesta para revisión"''',
     '''TITULO_APROBADA = "{codigo} · Propuesta comercial"   # VA18-7 (I1.9): el entregable del cliente ya no es un borrador


def _propiedades(prs, textos: dict, hash_vigente: str, aprobada: bool = False) -> None:
    cp = prs.core_properties
    cp.title = (TITULO_APROBADA.format(codigo=textos["codigo"]) if aprobada
                else f"{textos['codigo']} · Propuesta para revisión")'''),
    ("sandbox/nucleo/pptx_revision.py", "VA18-7 · title en APROBADA (llamada)",
     "    _propiedades(prs, textos, hash_vigente)\n",
     "    _propiedades(prs, textos, hash_vigente, aprobada=estado.get(\"estado\") == \"APROBADA\")   # VA18-7\n"),
    ("sandbox/nucleo/pptx_revision.py", "VPROT-1 · texto alternativo, diseños y patrones",
     '''        textos += [(f"diapositiva {n}", celda, t) for celda, t in parrafos(xml(parte))]
    for nombre in sorted(partes):''',
     '''        textos += [(f"diapositiva {n}", celda, t) for celda, t in parrafos(xml(parte))]
    # VPROT-1 (I1.9): también el texto alternativo (descr y title de cada cNvPr), que lee un lector de pantalla, de las
    # diapositivas, los diseños y los patrones, y los párrafos de los diseños y patrones, que se dibujan en la diapositiva
    for nombre in sorted(partes):
        diseno = re.fullmatch(r"ppt/(?:slideLayouts/slideLayout|slideMasters/slideMaster)\\d+\\.xml", nombre)
        if not (diseno or re.fullmatch(r"ppt/slides/slide\\d+\\.xml", nombre)):
            continue
        for el in xml(nombre).iter():
            if isinstance(el.tag, str) and etree.QName(el).localname == "cNvPr":
                textos += [(f"texto alternativo ({nombre})", None, el.get(k)) for k in ("descr", "title")
                           if (el.get(k) or "").strip()]
        if diseno:
            textos += [(f"diseño o patrón ({nombre})", None, x) for _, x in parrafos(xml(nombre))]
    for nombre in sorted(partes):'''),
    ("sandbox/preventa_run.py", "VC18-3 y PR18-7 · registrar-verificacion",
     '''    res = verificacion.registrar(est, texto, estado.hoy().isoformat())''',
     '''    catalogo, _ = _catalogo(env)   # VC18-3 (I1.9): la región de un DISCREPA se contrasta con la disponibilidad
    res = verificacion.registrar(est, texto, estado.hoy().isoformat(), catalogo=catalogo)'''),
    ("sandbox/preventa_run.py", "PR18-7 · motivo de cada DISCREPA en la salida",
     '''    for d in res.discrepa:
        print(f"- DISCREPA {d['id']}: {d['motivo']}")''',
     '''    for linea in verificacion.lineas_discrepa_turno(est):   # PR18-7 (I1.9): campo, valor, fuente y detalle
        print(linea)'''),
]


def aplicar(raiz: pathlib.Path, comprobar: bool) -> int:
    """Dos fases (Revisión 1): primero se calculan todos los ficheros nuevos en memoria; si algún anclaje no aparece
    exactamente una vez (y el cambio no estaba ya aplicado), no se escribe NADA y sale con rc 1."""
    textos: dict[str, tuple[str, int]] = {}
    faltan, pendientes = 0, []
    for rel, que, viejo, nuevo in CAMBIOS:
        if rel not in textos:
            b = (raiz / rel).read_bytes()
            textos[rel] = (b.decode("utf-8"), b.count(b"\r\n"))
        t, crlf = textos[rel]
        v, n = (viejo.replace("\n", "\r\n"), nuevo.replace("\n", "\r\n")) if crlf else (viejo, nuevo)
        if t.count(n) == 1 and t.count(v) == 0:
            print(f"YA APLICADO  {rel}: {que}")
            continue
        if t.count(v) != 1:
            print(f"NO ENCONTRADO {rel}: {que} (el anclaje aparece {t.count(v)} veces)")
            faltan += 1
            continue
        print(f"{'FALTA       ' if comprobar else 'SE APLICARÁ '} {rel}: {que}")
        textos[rel] = (t.replace(v, n), crlf)
        pendientes.append(rel)
    if comprobar:
        return 1 if faltan or pendientes else 0
    if faltan:
        print(f"NO SE ESCRIBE NADA: {faltan} anclaje(s) sin encontrar (el árbol queda como estaba)")
        return 1
    for rel in dict.fromkeys(pendientes):
        t, crlf = textos[rel]
        nb = t.encode("utf-8")
        if crlf and nb.count(b"\n") != nb.count(b"\r\n"):
            raise SystemExit(f"{rel}: quedarían finales de línea mezclados; no se escribe")
        (raiz / rel).write_bytes(nb)
        despues = nb.count(b"\r\n")
        print(f"ESCRITO      {rel} (CRLF {crlf} → {despues})")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        raise SystemExit(__doc__.splitlines()[2])
    sys.exit(aplicar(pathlib.Path(sys.argv[1]), "--comprobar" in sys.argv[2:]))
