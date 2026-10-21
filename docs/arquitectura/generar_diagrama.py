#!/usr/bin/env python3
"""Genera el diagrama de arquitectura a partir de arquitectura.json.

Salidas (en la carpeta de este fichero, o en --salida):
  arquitectura.es.svg, arquitectura.en.svg    SVG con los iconos oficiales incrustados
  arquitectura.es.html, arquitectura.en.html  HTML autocontenido con título y pie
  arquitectura.drawio                         editable en diagrams.net (una página por idioma)
  arquitectura.es.png, arquitectura.en.png    solo con --png (Microsoft Edge en modo headless)

Reglas:
- Solo biblioteca estándar y salida determinista: misma entrada, mismos bytes.
- Los iconos oficiales (Azure V24 y Microsoft Entra, oct. 2023) se incrustan sin alterar su dibujo. Su SHA-256 tiene que coincidir con
  el de arquitectura.json; la única transformación es prefijar sus id (y las referencias a ellos) por
  aparición, y se comprueba que quitar el prefijo devuelve el original byte a byte. El escalado es
  uniforme y va por fuera, en un <svg> envoltorio con el mismo viewBox cuadrado.
- Todo nodo y toda arista del JSON tienen que aparecer en cada salida (LES-G-062). Si falta algo, si un
  texto se sale de su grupo o se solapa, o si aparece <script, un manejador on* o javascript:, no se
  escribe nada y se sale con 1.
- Todas las salidas (también los PNG) se preparan en una carpeta temporal y solo se copian al destino
  cuando todo ha salido bien: un fallo de Edge no deja salidas a medias.

Códigos de salida: 0 todo correcto; 1 la especificación o una salida no pasan las comprobaciones;
2 error de entorno (falta un juego de iconos, Edge no responde, no se puede leer o escribir un fichero)
o argumentos de línea de órdenes no válidos (lo devuelve argparse).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from xml.sax.saxutils import escape, quoteattr
import xml.etree.ElementTree as ET

AQUI = Path(__file__).resolve().parent
SPEC_DEFECTO = AQUI / "arquitectura.json"
ICONOS_DEFECTO = os.environ.get(
    "ICONOS_AZURE", "C:/demos/_iconos-azure/V24/Azure_Public_Service_Icons/Icons")
ICONOS_ENTRA_DEFECTO = os.environ.get(
    "ICONOS_ENTRA", "C:/demos/_iconos-azure/entra/Oct2023/Microsoft Entra architecture icons - Oct 2023")
JUEGOS = ("azure_v24", "entra_oct2023")
EDGE_DEFECTO = os.environ.get(
    "EDGE_PATH", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")
IDIOMAS = ("es", "en")
ESTADOS = {"validado", "previsto", "futuro"}
LIMITES = ("tenant", "suscripcion", "grupo_recursos", "region")
ESTILOS = {"flujo", "normal", "futuro", "traza"}
TIPOS = {"icono", "contenedor", "pieza", "neutro"}
RE_ID = re.compile(r"^[a-z][a-z0-9_]*$")

FUENTE = "'Segoe UI', 'Segoe UI Web (West European)', -apple-system, 'Helvetica Neue', Arial, sans-serif"
AZUL = "#0078D4"
TEXTO = "#1B1B1B"
TEXTO_2 = "#505050"
GRIS = "#8A8886"
VERDE = "#107C10"
VERDE_SELLO = "#0B5A0B"

# Tamaños de letra
T_NOMBRE, T_DETALLE, T_ARISTA, T_GRUPO, T_SUBGRUPO, T_PIE = 14, 13, 13, 15, 14, 13
T_MINIMO = 13  # ninguna letra del diagrama por debajo de 13 px
CABECERA = 28  # alto de la cabecera de cada grupo o límite: nada de su interior puede pisarla
PILARES_POR_FILA = 6
INTERLINEA = 17
TOLERANCIA = 12  # px entre el extremo de una arista y la caja de su origen o destino

ESTILO_ARISTA = {
    "flujo": {"color": AZUL, "ancho": 2.4, "trazo": None},
    "normal": {"color": GRIS, "ancho": 1.6, "trazo": None},
    "futuro": {"color": GRIS, "ancho": 1.6, "trazo": "6 4"},
    "traza": {"color": "#A19F9D", "ancho": 1.6, "trazo": "2 4"},
}


class ErrorDiagrama(Exception):
    """La especificación, un icono o una salida no pasan las comprobaciones."""


class ErrorEntorno(Exception):
    """Falta algo del entorno (iconos, Edge) que no es culpa de la especificación."""


# --------------------------------------------------------------------------------------------- texto

def ancho_texto(s: str, tam: float, negrita: bool = False) -> float:
    """Estimación prudente del ancho en px (Segoe UI): sirve para detectar desbordes y solapes."""
    factor = 0.58 if negrita else 0.53
    estrechas = sum(1 for c in s if c in "ilI.,:;·'|!()[] ")
    return (len(s) - estrechas * 0.45) * tam * factor


def bloque_etiqueta(lineas: list[str], negritas: int = 1) -> tuple[float, float]:
    """Ancho y alto del bloque de etiqueta de un nodo (las primeras `negritas` líneas, el nombre, en negrita)."""
    ancho = max(ancho_texto(l, T_NOMBRE if i < negritas else T_DETALLE, i < negritas) for i, l in enumerate(lineas))
    return ancho, INTERLINEA * len(lineas)


def lineas_nombre(n: dict) -> int:
    """Líneas que ocupa el nombre del servicio: un nombre largo se parte sin dejar de ser completo."""
    return n.get("nombre_lineas", 1)


def solapan(a: tuple, b: tuple, margen: float = 0) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return ax0 < bx1 - margen and bx0 < ax1 - margen and ay0 < by1 - margen and by0 < ay1 - margen


def dentro(caja: tuple, marco: tuple, margen: float = 0) -> bool:
    return (caja[0] >= marco[0] + margen and caja[1] >= marco[1] + margen
            and caja[2] <= marco[2] - margen and caja[3] <= marco[3] - margen)


def a_xyxy(caja: list) -> tuple:
    x, y, w, h = caja
    return (x, y, x + w, y + h)


# ------------------------------------------------------------------------------------- geometría

def caja_icono(n: dict) -> tuple:
    x, y = n["pos"]
    m = n["lado"] / 2
    return (x - m, y - m, x + m, y + m)


def lineas_etiqueta(n: dict, idioma: str) -> list[str]:
    return n["etiqueta"][idioma]


def y_primera_linea(n: dict) -> float:
    return n["pos"][1] + n["lado"] / 2 + 17


def caja_etiqueta(n: dict, idioma: str) -> tuple:
    ancho, alto = bloque_etiqueta(lineas_etiqueta(n, idioma), lineas_nombre(n))
    x = n["pos"][0]
    y0 = y_primera_linea(n) - 12
    return (x - ancho / 2, y0, x + ancho / 2, y0 + alto)


def caja_nodo(n: dict, idioma: str) -> tuple:
    """Caja ocupada por el nodo (icono y etiqueta, o su rectángulo)."""
    if n["tipo"] in ("pieza", "contenedor"):
        return a_xyxy(n["caja"])
    ci, ce = caja_icono(n), caja_etiqueta(n, idioma)
    return (min(ci[0], ce[0]), ci[1], max(ci[2], ce[2]), ce[3])


def cajas_nodo(n: dict, idioma: str) -> list[tuple]:
    """Cajas reales del nodo para detectar solapes: el icono y su etiqueta por separado."""
    if n["tipo"] in ("pieza", "contenedor"):
        return [a_xyxy(n["caja"])]
    return [caja_icono(n), caja_etiqueta(n, idioma)]


def solapan_nodo(caja: tuple, n: dict, idioma: str, margen: float = 1) -> bool:
    return any(solapan(caja, c, margen) for c in cajas_nodo(n, idioma))


def caja_texto_arista(a: dict, idioma: str) -> tuple | None:
    if "etiqueta" not in a:
        return None
    lineas = a["etiqueta"][idioma]
    ancho = max(ancho_texto(l, T_ARISTA) for l in lineas)
    x, y = a["etiqueta_xy"]
    ancla = a.get("ancla", "middle")
    x0 = x - ancho / 2 if ancla == "middle" else (x - ancho if ancla == "end" else x)
    return (x0, y - 11, x0 + ancho, y - 11 + INTERLINEA * len(lineas))


def distancia_a_caja(p: list, caja: tuple) -> float:
    x, y = p
    dx = max(caja[0] - x, 0, x - caja[2])
    dy = max(caja[1] - y, 0, y - caja[3])
    return (dx * dx + dy * dy) ** 0.5


def punto_paso(a: dict) -> tuple:
    if "paso_xy" in a:
        return tuple(a["paso_xy"])
    mejor, largo = None, -1.0
    for p, q in zip(a["puntos"], a["puntos"][1:]):
        d = abs(q[0] - p[0]) + abs(q[1] - p[1])
        if d > largo:
            mejor, largo = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), d
    return mejor


# ------------------------------------------------------------------------------ especificación

def cargar_spec(ruta: Path) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))


def validar_spec(spec: dict) -> list[str]:
    """Devuelve la lista de errores de la especificación (vacía si es válida)."""
    e: list[str] = []
    ancho, alto = spec["lienzo"]["ancho"], spec["lienzo"]["alto"]
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (ancho, alto)):
        return ["lienzo: ancho y alto tienen que ser enteros positivos"]
    lienzo = (0, 0, ancho, alto)
    for clave in ("titulo", "subtitulo", "pie", "pie_derecha"):
        for idioma in IDIOMAS:
            if not str(spec.get(clave, {}).get(idioma, "")).strip():
                e.append(f"falta {clave}.{idioma}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(spec.get("fecha", ""))):
        e.append("fecha ausente o sin formato AAAA-MM-DD")

    iconos = spec.get("iconos", {})
    for clave, ic in iconos.items():
        if not RE_ID.match(clave):
            e.append(f"icono con clave no permitida: {clave!r}")
        r = ic.get("ruta", "")
        partes = PurePosixPath(r).parts
        if not r or r.startswith(("/", "\\")) or ":" in r or ".." in partes or "\\" in r:
            e.append(f"icono {clave}: ruta no permitida {r!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", ic.get("sha256", "")):
            e.append(f"icono {clave}: sha256 ausente o mal formado")
        if ic.get("juego", "azure_v24") not in JUEGOS or ic.get("juego", "azure_v24") not in spec.get("juegos", {}):
            e.append(f"icono {clave}: juego de iconos desconocido {ic.get('juego')!r}")

    grupos = {g["id"]: g for g in spec["grupos"]}
    nodos = {n["id"]: n for n in spec["nodos"]}
    todos = [g["id"] for g in spec["grupos"]] + [n["id"] for n in spec["nodos"]] + [a["id"] for a in spec["aristas"]]
    vistos: set[str] = set()
    for i in todos:
        if not RE_ID.match(i):
            e.append(f"id con caracteres no permitidos: {i!r}")
        if i in vistos:
            e.append(f"id repetido: {i}")
        vistos.add(i)

    for g in spec["grupos"]:
        for idioma in IDIOMAS:
            if not g["titulo"].get(idioma, "").strip():
                e.append(f"grupo {g['id']}: falta el título en {idioma}")
        if not dentro(a_xyxy(g["caja"]), lienzo):
            e.append(f"grupo {g['id']}: se sale del lienzo")
        if g.get("padre"):
            if g["padre"] not in grupos:
                e.append(f"grupo {g['id']}: padre desconocido {g['padre']}")
            elif not dentro(a_xyxy(g["caja"]), a_xyxy(grupos[g["padre"]]["caja"])):
                e.append(f"grupo {g['id']}: se sale de su grupo padre")

    for n in spec["nodos"]:
        nid = n["id"]
        if n.get("tipo") not in TIPOS:
            e.append(f"nodo {nid}: tipo desconocido {n.get('tipo')!r}")
            continue
        if n.get("estado") not in ESTADOS:
            e.append(f"nodo {nid}: estado desconocido {n.get('estado')!r}")
        for idioma in IDIOMAS:
            lineas = n.get("etiqueta", {}).get(idioma)
            if not lineas or not all(isinstance(l, str) and l.strip() for l in lineas):
                e.append(f"nodo {nid}: falta la etiqueta en {idioma}")
        if n["tipo"] in ("icono", "contenedor") and n.get("icono") not in iconos:
            e.append(f"nodo {nid}: icono desconocido {n.get('icono')!r}")
        k = n.get("nombre_lineas", 1)
        if "nombre_lineas" in n and (not isinstance(k, int) or isinstance(k, bool) or k < 1 or n["tipo"] == "pieza"
                                     or any(k >= len(n.get("etiqueta", {}).get(i) or []) for i in IDIOMAS)):
            e.append(f"nodo {nid}: nombre_lineas tiene que ser un entero entre 1 y las líneas de la etiqueta menos una")
        if n["tipo"] == "neutro" and not str(n.get("texto_neutro", "")).strip():
            e.append(f"nodo {nid}: forma neutra sin texto")
        g = n.get("grupo")
        if g is not None and g not in grupos:
            e.append(f"nodo {nid}: grupo desconocido {g}")
        if n["tipo"] == "pieza" and n.get("dentro") not in nodos:
            e.append(f"nodo {nid}: contenedor desconocido {n.get('dentro')!r}")
    if e:
        return e  # sin estructura válida no tiene sentido seguir con la geometría

    # Geometría: todo dentro de su grupo y del lienzo, sin solapes entre nodos ni con textos de arista.
    for idioma in IDIOMAS:
        cajas = {}
        for n in spec["nodos"]:
            c = caja_nodo(n, idioma)
            cajas[n["id"]] = c
            marco = a_xyxy(grupos[n["grupo"]]["caja"]) if n["grupo"] else lienzo
            if n["tipo"] == "pieza":
                marco = a_xyxy(nodos[n["dentro"]]["caja"])
                for i, l in enumerate(n["etiqueta"][idioma]):
                    if ancho_texto(l, T_NOMBRE if i == 0 else T_DETALLE, i == 0) > n["caja"][2] - 20:
                        e.append(f"[{idioma}] pieza {n['id']}: el texto «{l}» no cabe en la caja")
                if len(n["etiqueta"][idioma]) > 2:
                    e.append(f"[{idioma}] pieza {n['id']}: más de dos líneas")
            if not dentro(c, marco, 2):
                e.append(f"[{idioma}] nodo {n['id']}: se sale de su grupo o contenedor")
            if n["tipo"] == "contenedor":
                ce = caja_etiqueta(n, idioma)
                if not dentro(ce, c, 4) or not dentro(caja_icono(n), c, 4):
                    e.append(f"[{idioma}] contenedor {n['id']}: icono o etiqueta fuera de su marco")
        lista = [n for n in spec["nodos"] if n["tipo"] != "contenedor"]
        for i, a in enumerate(lista):
            for b in lista[i + 1:]:
                if any(solapan_nodo(c, b, idioma) for c in cajas_nodo(a, idioma)):
                    e.append(f"[{idioma}] los nodos {a['id']} y {b['id']} se solapan")
        for n in spec["nodos"]:
            if n["tipo"] == "contenedor":
                ce = caja_etiqueta(n, idioma)
                for p in lista:
                    if p.get("dentro") == n["id"] and solapan(ce, cajas[p["id"]], 1):
                        e.append(f"[{idioma}] la etiqueta de {n['id']} pisa la pieza {p['id']}")
        for a in spec["aristas"]:
            ct = caja_texto_arista(a, idioma)
            if ct is None:
                continue
            if not dentro(ct, lienzo):
                e.append(f"[{idioma}] arista {a['id']}: el texto se sale del lienzo")
            for n in lista:
                if solapan_nodo(ct, n, idioma):
                    e.append(f"[{idioma}] arista {a['id']}: el texto pisa el nodo {n['id']}")
            marcos = [(g["id"], a_xyxy(g["caja"])) for g in spec["grupos"]]
            marcos += [(n["id"], a_xyxy(n["caja"])) for n in spec["nodos"] if n["tipo"] == "contenedor"]
            for mid, marco in marcos:
                if solapan(ct, marco) and not dentro(ct, marco, 2):
                    e.append(f"[{idioma}] arista {a['id']}: el texto cruza el borde de {mid}")

    pasos = []
    for a in spec["aristas"]:
        aid = a["id"]
        if a.get("estilo") not in ESTILOS:
            e.append(f"arista {aid}: estilo desconocido {a.get('estilo')!r}")
        for extremo in ("origen", "destino"):
            if a.get(extremo) not in nodos and a.get(extremo) not in grupos:
                e.append(f"arista {aid}: {extremo} desconocido {a.get(extremo)!r}")
        pts = a.get("puntos", [])
        if len(pts) < 2:
            e.append(f"arista {aid}: necesita al menos dos puntos")
            continue
        for p, q in zip(pts, pts[1:]):
            if p[0] != q[0] and p[1] != q[1]:
                e.append(f"arista {aid}: tramo no ortogonal {p} → {q}")
        if "etiqueta" in a:
            for idioma in IDIOMAS:
                if not a["etiqueta"].get(idioma) or not all(str(l).strip() for l in a["etiqueta"][idioma]):
                    e.append(f"arista {aid}: falta la etiqueta en {idioma}")
            if "etiqueta_xy" not in a:
                e.append(f"arista {aid}: etiqueta sin posición")
        if a.get("ancla", "middle") not in ("start", "middle", "end"):
            e.append(f"arista {aid}: ancla desconocida")
        if "paso" in a:
            pasos.append(a["paso"])
            if a.get("estilo") != "flujo":
                e.append(f"arista {aid}: un paso numerado tiene que tener estilo flujo")
        for extremo, p in (("origen", pts[0]), ("destino", pts[-1])):
            ref = a.get(extremo)
            if ref not in grupos and ref not in nodos:
                continue  # ya anotado como desconocido
            caja = a_xyxy(grupos[ref]["caja"]) if ref in grupos else caja_nodo(nodos[ref], "es")
            if distancia_a_caja(p, caja) > TOLERANCIA:
                e.append(f"arista {aid}: el {extremo} {p} no toca {ref}")
    if sorted(pasos) != list(range(1, 9)):
        e.append(f"los pasos del flujo tienen que ser 1 a 8 sin repetir; hay {sorted(pasos)}")
    e += validar_limites(spec)
    e += validar_nombres_de_servicio(spec)
    e += validar_practicas(spec)
    e += validar_bandas(spec)
    return e


RE_PRACTICA = re.compile(r"^[A-Z]{3}-\d{2}$")
LEARN = "https://learn.microsoft.com/"


def geometria_practicas(spec: dict) -> dict:
    """Posiciones de la banda de pilares: una columna por pilar, una línea por práctica."""
    x, y, w, h = spec["practicas"]["caja"]
    col = (w - 28) / PILARES_POR_FILA
    return {"x": x, "y": y, "w": w, "h": h, "col": col, "y_titulo": y + 21, "y_pilar": y + 44, "sangria_id": 62,
            "y_linea": y + 63, "x_col": [x + 14 + i * col for i in range(PILARES_POR_FILA)]}


def practicas_por_pilar(spec: dict) -> dict[str, list[dict]]:
    salida: dict[str, list[dict]] = {p["id"]: [] for p in spec["practicas"]["pilares"]}
    for pr in spec["practicas"]["catalogo"]:
        salida.setdefault(pr["pilar"], []).append(pr)
    return salida


def validar_practicas(spec: dict) -> list[str]:
    """Banda «Buenas prácticas aplicadas»: 6 pilares con 2 o 3 prácticas, cada una con URL de Learn y cita."""
    e: list[str] = []
    pr = spec.get("practicas", {})
    pilares = pr.get("pilares", [])
    ids_pilar = [p.get("id") for p in pilares]
    if len(pilares) != PILARES_POR_FILA or len(set(ids_pilar)) != len(ids_pilar):
        return [f"practicas: tiene que haber {PILARES_POR_FILA} pilares distintos"]
    for p in pilares:
        for idioma in IDIOMAS:
            if not str(p.get(idioma, "")).strip():
                e.append(f"pilar {p['id']}: falta el nombre en {idioma}")
    vistos: set[str] = set()
    for lista, campo in ((pr.get("catalogo", []), "texto"), (pr.get("referencia", []), "tema")):
        for x in lista:
            pid = x.get("id", "")
            if not RE_PRACTICA.match(pid) or pid in vistos:
                e.append(f"práctica con id no válido o repetido: {pid!r}")
            vistos.add(pid)
            if x.get("pilar") not in ids_pilar:
                e.append(f"práctica {pid}: pilar desconocido {x.get('pilar')!r}")
            url = urlsplit(str(x.get("url", "")))
            if url.scheme != "https" or url.hostname != "learn.microsoft.com" or url.username or url.port:
                e.append(f"práctica {pid}: la URL tiene que ser de {LEARN}")
            if not str(x.get("cita", "")).strip():
                e.append(f"práctica {pid}: sin cita")
            for idioma in IDIOMAS:
                if not str(x.get(campo, {}).get(idioma, "")).strip():
                    e.append(f"práctica {pid}: falta el {campo} en {idioma}")
    for pilar, lista in practicas_por_pilar(spec).items():
        if not 2 <= len(lista) <= 3:
            e.append(f"pilar {pilar}: tiene {len(lista)} prácticas en la banda; tienen que ser 2 o 3")
    for n in spec["nodos"]:
        for ref in n.get("practicas", []):
            if ref not in vistos:
                e.append(f"nodo {n['id']}: práctica inexistente {ref!r}")
    if e:
        return e
    geo = geometria_practicas(spec)
    if geo["h"] < geo["y_linea"] + 2 * INTERLINEA + 6 - geo["y"]:
        e.append("la banda de prácticas es demasiado baja para tres líneas")
    for idioma in IDIOMAS:
        if 14 + ancho_texto(pr["titulo"][idioma], 15, True) > geo["w"] - 14:
            e.append(f"[{idioma}] el título de la banda de prácticas no cabe")
        por_pilar = practicas_por_pilar(spec)
        for p in pilares:
            if ancho_texto(p[idioma], T_NOMBRE, True) > geo["col"] - 12:
                e.append(f"[{idioma}] pilar {p['id']}: el nombre no cabe en su columna")
            for x in por_pilar[p["id"]]:
                if ancho_texto(x["id"], T_DETALLE, True) > geo["sangria_id"] - 10:
                    e.append(f"[{idioma}] práctica {x['id']}: el id no cabe en su sangría")
                ancho = geo["sangria_id"] + ancho_texto(x["texto"][idioma], T_DETALLE)
                if ancho > geo["col"] - 12:
                    e.append(f"[{idioma}] práctica {x['id']}: «{x['texto'][idioma]}» no cabe en su columna")
    return e


def ancestros(grupos: dict, gid: str | None) -> list[str]:
    """El grupo y todos sus padres, de dentro afuera."""
    salida = []
    while gid:
        if gid in salida:  # ciclo: lo anota validar_limites
            break
        salida.append(gid)
        gid = grupos[gid].get("padre") if gid in grupos else None
    return salida


def alto_cabecera(g: dict) -> float:
    """Alto de la cabecera de un grupo: una línea de título, más otra si el grupo trae subtítulo."""
    return CABECERA + (INTERLINEA - 3 if g.get("subtitulo") else 0)


def caja_titulo_grupo(g: dict, idioma: str) -> tuple:
    """Caja ocupada por el icono, el título y el subtítulo (si lo hay) de la cabecera de un grupo o límite."""
    x, y = g["caja"][0], g["caja"][1]
    tam = T_SUBGRUPO if g["nivel"] == 2 else T_GRUPO
    x0 = x + (38 if g.get("icono") else 14)
    ancho = ancho_texto(g["titulo"][idioma], tam, True)
    if g.get("subtitulo"):
        ancho = max(ancho, ancho_texto(g["subtitulo"][idioma], T_DETALLE))
    return (x + 8, y + 4, x0 + ancho, y + alto_cabecera(g) - 4)


def textos_cercanos(spec: dict, n: dict, idioma: str) -> str:
    """Texto que acompaña al icono de un nodo: su etiqueta y la cabecera de su grupo (título y subtítulo)."""
    grupos = {g["id"]: g for g in spec["grupos"]}
    partes = list(n["etiqueta"][idioma])
    g = grupos.get(n.get("grupo"))
    if g is not None and n["tipo"] != "contenedor":
        partes += [g["titulo"][idioma], (g.get("subtitulo") or {}).get(idioma, "")]
    return " ".join(partes).casefold()


def validar_nombres_de_servicio(spec: dict) -> list[str]:
    """Términos de los iconos: el nombre completo del servicio tiene que aparecer junto a cada icono.

    nombre_servicio[icono] es {es, en} o null (icono de persona, no de un servicio). Cuenta como «junto al
    icono» la etiqueta del nodo o la cabecera del grupo que lo contiene; para el icono de la cabecera de un
    grupo o límite, el título de ese grupo.
    """
    e: list[str] = []
    nombres = spec.get("nombre_servicio")
    if not isinstance(nombres, dict):
        return ["falta nombre_servicio: el nombre completo de cada servicio dibujado con icono"]
    for clave in sorted(iconos_usados(spec)):
        if clave not in nombres:
            e.append(f"icono {clave}: falta su nombre de servicio en nombre_servicio")
        elif nombres[clave] is not None and not all(str((nombres[clave] or {}).get(i, "")).strip() for i in IDIOMAS):
            e.append(f"icono {clave}: nombre de servicio vacío en algún idioma")
    if e:
        return e
    for idioma in IDIOMAS:
        for n in spec["nodos"]:
            nombre = nombres.get(n.get("icono")) if n.get("icono") else None
            if nombre and nombre[idioma].casefold() not in textos_cercanos(spec, n, idioma):
                e.append(f"[{idioma}] nodo {n['id']}: «{nombre[idioma]}» no aparece junto a su icono")
        for g in spec["grupos"]:
            nombre = nombres.get(g.get("icono")) if g.get("icono") else None
            if nombre and nombre[idioma].casefold() not in g["titulo"][idioma].casefold():
                e.append(f"[{idioma}] grupo {g['id']}: «{nombre[idioma]}» no aparece en su título")
    return e


def validar_limites(spec: dict) -> list[str]:
    """Límites anidados y rotulados, cabeceras libres y nodos que no invaden grupos ajenos."""
    e: list[str] = []
    grupos = {g["id"]: g for g in spec["grupos"]}
    for g in spec["grupos"]:
        if g.get("icono") is not None and g["icono"] not in spec["iconos"]:
            e.append(f"grupo {g['id']}: icono desconocido {g['icono']!r}")
        if g.get("limite") is not None and g["limite"] not in LIMITES:
            e.append(f"grupo {g['id']}: límite desconocido {g['limite']!r}")
        cadena, gid = [], g["id"]
        while gid in grupos and gid not in cadena:
            cadena.append(gid)
            gid = grupos[gid].get("padre")
        if gid in cadena:
            e.append(f"grupo {g['id']}: ciclo de padres")
    # El orden de los límites: cada uno dentro del anterior (tenant ⊃ suscripción ⊃ grupo ⊃ región).
    orden = spec.get("limites", {}).get("orden", [])
    if list(orden) != list(LIMITES):
        e.append(f"limites.orden tiene que ser {list(LIMITES)}")
    por_limite = {g["limite"]: g for g in spec["grupos"] if g.get("limite")}
    for i, lim in enumerate(LIMITES):
        g = por_limite.get(lim)
        if g is None:
            e.append(f"falta el límite {lim}")
            continue
        if i and por_limite.get(LIMITES[i - 1]) and g.get("padre") != por_limite[LIMITES[i - 1]]["id"]:
            e.append(f"límite {lim}: su padre tiene que ser el límite {LIMITES[i - 1]}")
    if e:
        return e
    for g in spec["grupos"]:
        sub = g.get("subtitulo")
        if sub is not None and not (isinstance(sub, dict) and all(str(sub.get(i, "")).strip() for i in IDIOMAS)):
            e.append(f"grupo {g['id']}: subtítulo vacío o mal formado")
    if e:
        return e
    for idioma in IDIOMAS:
        for g in spec["grupos"]:
            x, y, w, h = g["caja"]
            cab = (x, y, x + w, y + alto_cabecera(g))
            if caja_titulo_grupo(g, idioma)[2] > x + w - 8:
                e.append(f"[{idioma}] grupo {g['id']}: el título no cabe en su cabecera")
            for h_ in spec["grupos"]:
                if h_.get("padre") == g["id"] and solapan(a_xyxy(h_["caja"]), cab):
                    e.append(f"[{idioma}] grupo {h_['id']}: pisa la cabecera de {g['id']}")
            for n in spec["nodos"]:
                if n["grupo"] == g["id"] and any(solapan(c, cab) for c in cajas_nodo(n, idioma)):
                    e.append(f"[{idioma}] nodo {n['id']}: pisa la cabecera de {g['id']}")
        # Dos grupos que no son uno antepasado del otro no pueden solaparse.
        lista = spec["grupos"]
        for i, g in enumerate(lista):
            for h_ in lista[i + 1:]:
                if g["id"] in ancestros(grupos, h_["id"]) or h_["id"] in ancestros(grupos, g["id"]):
                    continue
                if solapan(a_xyxy(g["caja"]), a_xyxy(h_["caja"])):
                    e.append(f"los grupos {g['id']} y {h_['id']} se solapan sin estar anidados")
        # Un nodo no puede invadir un grupo que no sea el suyo ni uno de sus antepasados.
        for n in spec["nodos"]:
            if n["tipo"] == "pieza":
                continue
            propios = set(ancestros(grupos, n["grupo"]))
            for g in spec["grupos"]:
                if g["id"] not in propios and any(solapan(c, a_xyxy(g["caja"])) for c in cajas_nodo(n, idioma)):
                    e.append(f"[{idioma}] nodo {n['id']}: invade el grupo {g['id']}, que no es el suyo")
        # El texto de una arista no puede tapar el título de un grupo.
        for a in spec["aristas"]:
            ct = caja_texto_arista(a, idioma)
            if ct is None:
                continue
            for g in spec["grupos"]:
                if solapan(ct, caja_titulo_grupo(g, idioma)):
                    e.append(f"[{idioma}] arista {a['id']}: el texto tapa el título de {g['id']}")
    return sorted(set(e), key=e.index)


# ------------------------------------------------------------------------------------- iconos

def limpia_cabecera(texto: str) -> str:
    texto = texto.lstrip("\ufeff")
    return re.sub(r"^\s*<\?xml[^>]*\?>\s*", "", texto)


def ids_de(texto: str) -> list[str]:
    return re.findall(r'\bid="([^"]+)"', texto)


def prefija(texto: str, prefijo: str) -> str:
    ids = set(ids_de(texto))

    def sub(m):
        return m.group(1) + (prefijo + m.group(2) if m.group(2) in ids else m.group(2)) + m.group(3)

    t = re.sub(r'(\bid=")([^"]+)(")', sub, texto)
    t = re.sub(r"(url\(#)([^)]+)(\))", sub, t)
    t = re.sub(r'(href="#)([^"]+)(")', sub, t)
    return t


def desprefija(texto: str, prefijo: str) -> str:
    return (texto.replace('id="' + prefijo, 'id="').replace("url(#" + prefijo, "url(#")
            .replace('href="#' + prefijo, 'href="#'))


PROHIBIDO_ICONO = re.compile(
    r"<script|<style|<foreignObject|<image|\bclass=|\bstyle=|javascript:|<[^>]*\son[a-z]+\s*=", re.I)


# Lista blanca: lo único que usan los iconos oficiales revisados. Cualquier otra cosa falla cerrado.
ELEMENTOS_ICONO = {"svg", "defs", "linearGradient", "radialGradient", "stop", "path", "rect", "circle",
                   "ellipse", "polygon", "polyline", "line", "g", "title"}


def comprueba_icono(texto: str, nombre: str) -> None:
    """Rechaza un icono que traiga algo que el renombrado de id no cubre o que pueda ejecutar código."""
    m = PROHIBIDO_ICONO.search(texto)
    if m:
        raise ErrorDiagrama(f"icono {nombre}: contenido no admitido ({m.group(0)[:30]!r})")
    raiz = ET.fromstring(texto)
    if not raiz.tag.endswith("svg"):
        raise ErrorDiagrama(f"icono {nombre}: la raíz no es <svg>")
    for el in raiz.iter():
        etiqueta = el.tag.split("}", 1)[-1]
        if etiqueta not in ELEMENTOS_ICONO:
            raise ErrorDiagrama(f"icono {nombre}: elemento no admitido <{etiqueta}>")
        for attr, valor in el.attrib.items():
            if "href" in attr.lower():
                raise ErrorDiagrama(f"icono {nombre}: atributo de enlace no admitido ({attr})")
            for ref in re.findall(r"url\(([^)]*)\)", valor):
                if not ref.startswith("#"):
                    raise ErrorDiagrama(f"icono {nombre}: referencia externa no admitida url({ref})")
    vb = (raiz.get("viewBox") or "").split()
    if len(vb) != 4 or vb[2] != vb[3] or not all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in vb):
        raise ErrorDiagrama(f"icono {nombre}: viewBox ausente o no cuadrado")
    ids = ids_de(texto)
    if len(ids) != len(set(ids)):
        raise ErrorDiagrama(f"icono {nombre}: id repetidos dentro del propio icono")
    refs = set(re.findall(r"url\(#([^)]+)\)", texto)) | set(re.findall(r'href="#([^"]+)"', texto))
    if refs - set(ids):
        raise ErrorDiagrama(f"icono {nombre}: referencias sin destino {sorted(refs - set(ids))}")


def iconos_usados(spec: dict) -> set[str]:
    """Iconos que dibuja el diagrama: los de los nodos y los de las cabeceras de grupo o límite."""
    return ({n["icono"] for n in spec["nodos"] if n.get("icono")}
            | {g["icono"] for g in spec["grupos"] if g.get("icono")})


def cargar_iconos(spec: dict, carpetas: dict[str, Path] | Path) -> dict[str, str]:
    """Lee los iconos usados, comprueba su SHA-256 y su estructura. Devuelve clave → texto original.

    carpetas: juego → carpeta raíz de ese juego oficial (o una sola carpeta para todos los juegos).
    """
    if not isinstance(carpetas, dict):
        carpetas = {j: carpetas for j in JUEGOS}
    usados = iconos_usados(spec)
    for juego in sorted({spec["iconos"][c].get("juego", "azure_v24") for c in usados}):
        if juego not in carpetas:
            raise ErrorDiagrama(f"juego de iconos desconocido: {juego!r}")
        if not Path(carpetas[juego]).is_dir():
            raise ErrorEntorno(f"no existe la carpeta del juego de iconos {juego}: {carpetas[juego]}")
    salida = {}
    for clave in sorted(usados):
        ic = spec["iconos"][clave]
        carpeta = Path(carpetas[ic.get("juego", "azure_v24")])
        ruta = carpeta / Path(*PurePosixPath(ic["ruta"]).parts)
        if not ruta.is_file():
            raise ErrorEntorno(f"falta el icono {clave}: {ruta}")
        datos = ruta.read_bytes()
        sha = hashlib.sha256(datos).hexdigest()
        if sha != ic["sha256"]:
            raise ErrorDiagrama(f"icono {clave}: SHA-256 {sha} distinto del esperado {ic['sha256']}")
        texto = limpia_cabecera(datos.decode("utf-8"))
        comprueba_icono(texto, clave)
        salida[clave] = texto
    return salida


def icono_incrustado(original: str, prefijo: str, x: float, y: float, lado: float) -> str:
    """Fragmento con el icono intacto por dentro y el escalado uniforme por fuera."""
    vb = ET.fromstring(original).get("viewBox")
    interior = prefija(original, prefijo)
    if desprefija(interior, prefijo) != original:
        raise ErrorDiagrama(f"icono {prefijo}: el renombrado de id no es reversible")
    ids = ids_de(interior)
    if any(not i.startswith(prefijo) for i in ids):
        raise ErrorDiagrama(f"icono {prefijo}: quedan id sin prefijo")
    return (f'<svg x="{fmt(x)}" y="{fmt(y)}" width="{fmt(lado)}" height="{fmt(lado)}" '
            f'viewBox="{vb}">{interior}</svg>')


# ------------------------------------------------------------------------------------- SVG

def fmt(v: float) -> str:
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else f"{v:g}"


def texto_svg(x, y, s, tam, color=TEXTO, negrita=False, ancla="middle", halo=False, extra="") -> str:
    attrs = [f'x="{fmt(x)}"', f'y="{fmt(y)}"', f'font-size="{tam}"', f'fill="{color}"',
             f'text-anchor="{ancla}"']
    if negrita:
        attrs.append('font-weight="600"')
    if halo:
        attrs.append('stroke="#FFFFFF" stroke-width="4" stroke-linejoin="round" paint-order="stroke"')
    if extra:
        attrs.append(extra)
    return f"<text {' '.join(attrs)}>{escape(s)}</text>"


def marca_validado(cx: float, cy: float, r: float = 8) -> str:
    """Sello «Validado en Azure»: disco verde oscuro con aro exterior. Es distinto a propósito de la marca
    verde clara que algunos iconos oficiales (Content Safety) traen de serie y que no se puede alterar."""
    return (f'<g class="validado"><circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(r + 3)}" fill="#FFFFFF" '
            f'stroke="{VERDE_SELLO}" stroke-width="1.6"/>'
            f'<circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="{fmt(r - 0.5)}" fill="{VERDE_SELLO}"/>'
            f'<path d="M{fmt(cx - r * 0.45)},{fmt(cy + r * 0.02)} '
            f'L{fmt(cx - r * 0.1)},{fmt(cy + r * 0.38)} L{fmt(cx + r * 0.5)},{fmt(cy - r * 0.35)}" '
            f'fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" '
            f'stroke-linejoin="round"/></g>')


def circulo_paso(cx: float, cy: float, n: int) -> str:
    return (f'<g class="paso" data-paso="{n}"><circle cx="{fmt(cx)}" cy="{fmt(cy)}" r="12" fill="{AZUL}" '
            f'stroke="#FFFFFF" stroke-width="2"/>'
            + texto_svg(cx, cy + 4.5, str(n), 13, "#FFFFFF", True) + "</g>")


def etiqueta_nodo_svg(n: dict, idioma: str) -> str:
    x, y0 = n["pos"][0], y_primera_linea(n)
    k = lineas_nombre(n)
    partes = []
    for i, l in enumerate(lineas_etiqueta(n, idioma)):
        partes.append(texto_svg(x, y0 + i * INTERLINEA, l, T_NOMBRE if i < k else T_DETALLE,
                                TEXTO if i < k else TEXTO_2, i < k))
    return "".join(partes)


def nodo_svg(n: dict, idioma: str, iconos: dict) -> str:
    nid = n["id"]
    datos = f'id="n-{nid}" data-estado="{n["estado"]}"'
    if n["tipo"] == "pieza":
        x, y, w, h = n["caja"]
        l = lineas_etiqueta(n, idioma)
        cuerpo = (f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="8" '
                  f'fill="#EEF5FC" stroke="#9CC3EB" stroke-width="1.2"/>'
                  + texto_svg(x + 14, y + 22, l[0], T_NOMBRE, TEXTO, True, "start"))
        if len(l) > 1:
            cuerpo += texto_svg(x + 14, y + 40, l[1], T_DETALLE, TEXTO_2, False, "start")
        return f"<g {datos}>{cuerpo}</g>"
    partes = []
    if n["tipo"] == "contenedor":
        x, y, w, h = n["caja"]
        partes.append(f'<rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" rx="12" '
                      f'fill="#FFFFFF" stroke="{AZUL}" stroke-width="1.6"/>')
    if n["estado"] == "futuro":
        c = caja_nodo(n, idioma)
        partes.append(f'<rect x="{fmt(c[0] - 10)}" y="{fmt(c[1] - 8)}" width="{fmt(c[2] - c[0] + 20)}" '
                      f'height="{fmt(c[3] - c[1] + 14)}" rx="8" fill="none" stroke="{GRIS}" '
                      f'stroke-width="1.2" stroke-dasharray="6 4"/>')
    x0, y0, x1, _ = caja_icono(n)
    if n["tipo"] == "neutro":
        partes.append(f'<rect x="{fmt(x0)}" y="{fmt(y0)}" width="{fmt(n["lado"])}" height="{fmt(n["lado"])}" '
                      f'rx="8" fill="#FFFFFF" stroke="{GRIS}" stroke-width="1.5"/>'
                      + texto_svg(n["pos"][0], n["pos"][1] + 5, n["texto_neutro"], T_DETALLE, "#605E5C", True))
    else:
        partes.append(f'<g data-icono="{n["icono"]}">'
                      + icono_incrustado(iconos[n["icono"]], f"i-{nid}-", x0, y0, n["lado"]) + "</g>")
    if n["estado"] == "validado":
        partes.append(marca_validado(x1 + 2, y0 + 2))
    partes.append(etiqueta_nodo_svg(n, idioma))
    return f"<g {datos}>{''.join(partes)}</g>"


def estilo_grupo(g: dict) -> dict:
    """Relleno, borde, trazo y título de un grupo: los límites tienen un estilo propio por nivel."""
    if g.get("limite"):
        est = dict(ESTILO_LIMITE[g["limite"]])
        est.update(tam=T_GRUPO, color=TEXTO, rx=6)
        return est
    if g["nivel"] == 1:
        relleno, borde = ("#F3F8FD", "#B7D3F0") if g.get("acento") else ("#F7F8FA", "#D2D6DC")
        return {"relleno": relleno, "borde": borde, "trazo": None, "ancho": 1.2, "tam": T_GRUPO,
                "color": AZUL if g.get("acento") else TEXTO, "rx": 12}
    return {"relleno": "#FFFFFF", "borde": "#D6DEE8", "trazo": None, "ancho": 1.2, "tam": T_SUBGRUPO,
            "color": TEXTO_2, "rx": 10}


def grupo_svg(g: dict, idioma: str, iconos: dict) -> str:
    x, y, w, h = g["caja"]
    est = estilo_grupo(g)
    trazo = f' stroke-dasharray="{est["trazo"]}"' if est["trazo"] else ""
    limite = f' data-limite="{g["limite"]}"' if g.get("limite") else ""
    partes = [f'<g id="g-{g["id"]}"{limite}><rect x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" '
              f'rx="{est["rx"]}" fill="{est["relleno"]}" stroke="{est["borde"]}" stroke-width="{est["ancho"]}"'
              f'{trazo}/>']
    xt = x + 14
    if g.get("icono"):
        partes.append(f'<g data-icono="{g["icono"]}">'
                      + icono_incrustado(iconos[g["icono"]], f"i-g-{g['id']}-", x + 12, y + 5, 18) + "</g>")
        xt = x + 38
    partes.append(texto_svg(xt, y + 19, g["titulo"][idioma], est["tam"], est["color"], True, "start"))
    if g.get("subtitulo"):
        partes.append(texto_svg(xt, y + 19 + INTERLINEA - 1, g["subtitulo"][idioma], T_DETALLE, TEXTO_2, False,
                                "start"))
    return "".join(partes) + "</g>"


def arista_svg(a: dict, idioma: str) -> str:
    est = ESTILO_ARISTA[a["estilo"]]
    pts = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in a["puntos"])
    trazo = f' stroke-dasharray="{est["trazo"]}"' if est["trazo"] else ""
    partes = [f'<polyline points="{pts}" fill="none" stroke="{est["color"]}" stroke-width="{est["ancho"]}"'
              f'{trazo} stroke-linejoin="round" marker-end="url(#m-{a["estilo"]})"/>']
    if "etiqueta" in a:
        x, y = a["etiqueta_xy"]
        for i, l in enumerate(a["etiqueta"][idioma]):
            partes.append(texto_svg(x, y + i * INTERLINEA, l, T_ARISTA, "#323130" if a["estilo"] == "flujo"
                                    else TEXTO_2, a["estilo"] == "flujo", a.get("ancla", "middle"), True))
    if "paso" in a:
        cx, cy = punto_paso(a)
        partes.append(circulo_paso(cx, cy, a["paso"]))
    paso = f' data-paso="{a["paso"]}"' if "paso" in a else ""
    return (f'<g id="e-{a["id"]}" data-origen="{a["origen"]}" data-destino="{a["destino"]}"{paso}>'
            + "".join(partes) + "</g>")


def marcadores() -> str:
    out = []
    for nombre, est in ESTILO_ARISTA.items():
        out.append(f'<marker id="m-{nombre}" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="9" '
                   f'markerHeight="9" markerUnits="userSpaceOnUse" orient="auto">'
                   f'<path d="M0,0 L10,5 L0,10 z" fill="{est["color"]}"/></marker>')
    return "<defs>" + "".join(out) + "</defs>"


ESTILO_LIMITE = {
    "tenant": {"relleno": "#F7F7F7", "borde": "#605E5C", "trazo": None, "ancho": 1.4},
    "suscripcion": {"relleno": "#FFFFFF", "borde": "#8A8886", "trazo": "8 4", "ancho": 1.4},
    "grupo_recursos": {"relleno": "#FAFAFA", "borde": "#8A8886", "trazo": "3 3", "ancho": 1.4},
    "region": {"relleno": "#FFFFFF", "borde": "#2B88D8", "trazo": "6 3", "ancho": 1.4},
}


def simbolo_leyenda(simbolo: str, x: float, y: float) -> tuple[str, float]:
    """Dibuja el símbolo de una entrada de la leyenda; devuelve el SVG y su ancho."""
    if simbolo == "paso":
        return circulo_paso(x + 12, y, 1), 24
    if simbolo in ESTILO_ARISTA:
        est = ESTILO_ARISTA[simbolo]
        trazo = f' stroke-dasharray="{est["trazo"]}"' if est["trazo"] else ""
        return (f'<line x1="{fmt(x)}" y1="{fmt(y)}" x2="{fmt(x + 34)}" y2="{fmt(y)}" stroke="{est["color"]}" '
                f'stroke-width="{est["ancho"]}"{trazo} marker-end="url(#m-{simbolo})"/>'), 36
    if simbolo == "validado":
        return marca_validado(x + 11, y), 22
    if simbolo == "limite":
        # Las dos variantes del dibujo: el tenant con trazo continuo y, dentro, los demás con trazo discontinuo.
        t, s = ESTILO_LIMITE["tenant"], ESTILO_LIMITE["suscripcion"]
        return (f'<rect x="{fmt(x)}" y="{fmt(y - 10)}" width="30" height="20" rx="4" fill="{t["relleno"]}" '
                f'stroke="{t["borde"]}" stroke-width="{t["ancho"]}"/>'
                f'<rect x="{fmt(x + 5)}" y="{fmt(y - 5)}" width="20" height="10" rx="2" fill="{s["relleno"]}" '
                f'stroke="{s["borde"]}" stroke-width="{s["ancho"]}" stroke-dasharray="4 2"/>'), 30
    if simbolo == "pieza":
        return (f'<rect x="{fmt(x)}" y="{fmt(y - 9)}" width="30" height="18" rx="5" fill="#EEF5FC" '
                f'stroke="#9CC3EB" stroke-width="1.2"/>'), 30
    if simbolo == "neutro":
        return (f'<rect x="{fmt(x)}" y="{fmt(y - 10)}" width="20" height="20" rx="5" fill="#FFFFFF" '
                f'stroke="{GRIS}" stroke-width="1.5"/>'), 20
    raise ErrorDiagrama(f"símbolo de leyenda desconocido: {simbolo}")


ANCHO_SIMBOLO = {"paso": 24, "flujo": 36, "normal": 36, "futuro": 36, "traza": 36, "validado": 22,
                 "limite": 30, "pieza": 30, "neutro": 20}


def geometria_validado(spec: dict, idioma: str) -> tuple[list[tuple[str, float, float]], float]:
    """Fichas de la banda «Validado en Azure»: (texto, x, ancho) y la x donde acaba la última."""
    x = spec["validado"]["caja"][0] + 44
    x += ancho_texto(spec["validado"]["titulo"][idioma], 15, True) + 24
    fichas = []
    for el in spec["validado"]["elementos"]:
        w = ancho_texto(el[idioma], T_DETALLE) + 24
        fichas.append((el[idioma], x, w))
        x += w + 10
    return fichas, x - 10


def geometria_leyenda(spec: dict, idioma: str) -> tuple[list[tuple[dict, float, float]], float]:
    """Entradas de la leyenda: (entrada, x del símbolo, x del texto) y la x donde acaba la última."""
    x = 24 + ancho_texto("Leyenda" if idioma == "es" else "Legend", T_DETALLE, True) + 18
    entradas = []
    for el in spec["leyenda"]:
        if el["simbolo"] not in ANCHO_SIMBOLO:
            raise ErrorDiagrama(f"símbolo de leyenda desconocido: {el['simbolo']}")
        xt = x + ANCHO_SIMBOLO[el["simbolo"]] + 8
        entradas.append((el, x, xt))
        x = xt + ancho_texto(el[idioma], T_DETALLE) + 26
    return entradas, x - 26


def extension_diagrama(spec: dict) -> float:
    """Borde inferior de todo lo que está por encima de las bandas (grupos y nodos en los dos idiomas)."""
    abajo = [g["caja"][1] + g["caja"][3] for g in spec["grupos"]]
    for idioma in IDIOMAS:
        abajo += [caja_nodo(n, idioma)[3] for n in spec["nodos"]]
    return max(abajo)


def validar_bandas(spec: dict) -> list[str]:
    """Bandas de abajo: sin pisar el diagrama ni entre sí, dentro del lienzo y con todo su texto dentro."""
    e: list[str] = []
    ancho, alto = spec["lienzo"]["ancho"], spec["lienzo"]["alto"]
    try:
        bv = a_xyxy(spec["validado"]["caja"])
        bp = a_xyxy(spec["practicas"]["caja"])
        ly, py = float(spec["lienzo"]["leyenda_y"]), float(spec["lienzo"]["pie_y"])
    except (KeyError, TypeError, ValueError):
        return ["faltan validado.caja, practicas.caja, lienzo.leyenda_y o lienzo.pie_y"]
    for nombre, caja in (("validado", bv), ("practicas", bp)):
        if not dentro(caja, (0, 0, ancho, alto), 8):
            e.append(f"la banda {nombre} se sale del lienzo")
    if bv[1] <= extension_diagrama(spec) + 4:
        e.append("la banda validado pisa el diagrama")
    if bp[1] <= bv[3] + 4:
        e.append("la banda de prácticas pisa la banda validado")
    if ly - 12 <= bp[3] + 4:
        e.append("la leyenda pisa la banda de prácticas")
    if py <= ly + 12 or py + 22 + 4 > alto:
        e.append("el pie no cabe entre la leyenda y el final del lienzo")
    for idioma in IDIOMAS:
        _, fin = geometria_validado(spec, idioma)
        if "nota" in spec["validado"]:
            nota = spec["validado"]["nota"]
            nota = nota.get(idioma, "") if isinstance(nota, dict) else ""
            if not isinstance(nota, str) or not nota.strip():
                nota = ""
                e.append(f"[{idioma}] la nota de la banda validado está vacía o mal formada")
            fin += 24 + ancho_texto(nota, T_DETALLE)
        if fin > bv[2] - 12:
            e.append(f"[{idioma}] la banda validado no cabe ({fmt(fin)} px)")
        _, fin = geometria_leyenda(spec, idioma)
        if fin > ancho - 16:
            e.append(f"[{idioma}] la leyenda no cabe ({fmt(fin)} px)")
        pie = f"{spec['pie'][idioma]} · {fecha_larga(spec['fecha'], idioma)}"
        if 24 + ancho_texto(pie, T_PIE) + 40 + ancho_texto(spec["pie_derecha"][idioma], T_PIE) > ancho - 24:
            e.append(f"[{idioma}] los dos textos del pie se pisan")
    return e


def banda_practicas_svg(spec: dict, idioma: str) -> str:
    """Banda de los 6 pilares; cada práctica lleva su URL de Learn y su cita como <title> (tooltip)."""
    pr = spec["practicas"]
    geo = geometria_practicas(spec)
    p = [f'<g id="banda-practicas"><rect x="{fmt(geo["x"])}" y="{fmt(geo["y"])}" width="{fmt(geo["w"])}" '
         f'height="{fmt(geo["h"])}" rx="10" fill="#F5F9FD" stroke="#B7D3F0" stroke-width="1.2"/>',
         texto_svg(geo["x"] + 14, geo["y_titulo"], pr["titulo"][idioma], 15, AZUL, True, "start")]
    por_pilar = practicas_por_pilar(spec)
    for i, pil in enumerate(pr["pilares"]):
        x = geo["x_col"][i]
        if i:
            p.append(f'<line x1="{fmt(x - 6)}" y1="{fmt(geo["y_pilar"] - 14)}" x2="{fmt(x - 6)}" '
                     f'y2="{fmt(geo["y"] + geo["h"] - 8)}" stroke="#D6E4F3" stroke-width="1"/>')
        p.append(f'<g id="pilar-{pil["id"]}">' + texto_svg(x + 6, geo["y_pilar"], pil[idioma], T_NOMBRE, TEXTO,
                                                           True, "start"))
        for j, x_ in enumerate(por_pilar[pil["id"]]):
            y = geo["y_linea"] + j * INTERLINEA
            p.append(f'<g class="practica" data-id="{escape(x_["id"])}">'
                     f'<title>{escape(x_["id"] + " · " + x_["url"] + " · " + x_["cita"])}</title>'
                     + texto_svg(x + 6, y, x_["id"], T_DETALLE, AZUL, True, "start")
                     + texto_svg(x + 6 + geo["sangria_id"], y, x_["texto"][idioma], T_DETALLE, TEXTO_2, False, "start")
                     + "</g>")
        p.append("</g>")
    p.append("</g>")
    return "".join(p)


def banda_y_leyenda(spec: dict, idioma: str) -> str:
    ancho = spec["lienzo"]["ancho"]
    partes = []
    # Banda «Validado en Azure»
    bx, by, bw, bh = spec["validado"]["caja"]
    partes.append(f'<g id="banda-validado"><rect x="{fmt(bx)}" y="{fmt(by)}" width="{fmt(bw)}" height="{fmt(bh)}" '
                  f'rx="10" fill="#F1F8F1" stroke="#9BCB9B" stroke-width="1.2"/>')
    partes.append(marca_validado(bx + 27, by + bh / 2, 10))
    partes.append(texto_svg(bx + 44, by + bh / 2 + 5, spec["validado"]["titulo"][idioma], 15, "#0B5A0B", True,
                            "start"))
    fichas, _ = geometria_validado(spec, idioma)
    for s, x, w in fichas:
        partes.append(f'<rect x="{fmt(x)}" y="{fmt(by + bh / 2 - 12)}" width="{fmt(w)}" height="24" rx="12" '
                      f'fill="#FFFFFF" stroke="#9BCB9B" stroke-width="1"/>'
                      + texto_svg(x + w / 2, by + bh / 2 + 4.5, s, T_DETALLE, "#1E4620", False))
    if spec["validado"].get("nota"):
        partes.append(texto_svg(bx + bw - 14, by + bh / 2 + 4.5, spec["validado"]["nota"][idioma], T_DETALLE,
                                "#3B6E3B", False, "end", extra='font-style="italic"'))
    partes.append("</g>")
    partes.append(banda_practicas_svg(spec, idioma))
    # Leyenda
    ly = spec["lienzo"]["leyenda_y"]
    titulo = "Leyenda" if idioma == "es" else "Legend"
    partes.append('<g id="leyenda">' + texto_svg(24, ly + 5, titulo, T_DETALLE, TEXTO, True, "start"))
    entradas, _ = geometria_leyenda(spec, idioma)
    for el, xs, xt in entradas:
        partes.append(simbolo_leyenda(el["simbolo"], xs, ly)[0])
        partes.append(texto_svg(xt, ly + 4.5, el[idioma], T_DETALLE, TEXTO_2, False, "start"))
    partes.append("</g>")
    # Pie
    py = spec["lienzo"]["pie_y"]
    partes.append('<g id="pie">'
                  f'<line x1="24" y1="{fmt(py)}" x2="{ancho - 24}" y2="{fmt(py)}" stroke="#E1E4E8" stroke-width="1"/>'
                  + texto_svg(24, py + 22, f"{spec['pie'][idioma]} · {fecha_larga(spec['fecha'], idioma)}", T_PIE,
                              TEXTO_2, False, "start")
                  + texto_svg(ancho - 24, py + 22, spec["pie_derecha"][idioma], T_PIE, TEXTO_2, False, "end")
                  + "</g>")
    return "".join(partes)


MESES = {"es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
                "octubre", "noviembre", "diciembre"],
         "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                "October", "November", "December"]}


def fecha_larga(fecha: str, idioma: str) -> str:
    a, m, d = (int(x) for x in fecha.split("-"))
    mes = MESES[idioma][m - 1]
    return f"{d} de {mes} de {a}" if idioma == "es" else f"{mes} {d}, {a}"


def render_svg(spec: dict, idioma: str, iconos: dict) -> str:
    ancho, alto = spec["lienzo"]["ancho"], spec["lienzo"]["alto"]
    titulo = spec["titulo"][idioma]
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" height="{alto}" '
         f'viewBox="0 0 {ancho} {alto}" font-family={quoteattr(FUENTE)} role="img" '
         f'aria-labelledby="titulo-diagrama" lang="{idioma}">',
         f'<title id="titulo-diagrama">{escape(titulo)}</title>',
         marcadores(),
         f'<rect width="{ancho}" height="{alto}" fill="#FFFFFF"/>',
         '<g id="cabecera">'
         f'<rect x="24" y="18" width="6" height="58" rx="3" fill="{AZUL}"/>'
         + texto_svg(44, 46, titulo, 28, TEXTO, True, "start")
         + texto_svg(44, 71, spec["subtitulo"][idioma], 16, TEXTO_2, False, "start")
         + "</g>"]
    grupos = {g["id"]: g for g in spec["grupos"]}
    for g in sorted(spec["grupos"], key=lambda g: (len(ancestros(grupos, g["id"])), g["nivel"])):
        p.append(grupo_svg(g, idioma, iconos))
    contenedores = [n for n in spec["nodos"] if n["tipo"] == "contenedor"]
    for n in contenedores:
        p.append(nodo_svg(n, idioma, iconos))
    # Aristas por debajo de los nodos: las discontinuas primero para que las continuas queden encima
    orden = {"futuro": 0, "traza": 1, "normal": 2, "flujo": 3}
    aristas = sorted(spec["aristas"], key=lambda a: orden[a["estilo"]])
    p.append('<g id="aristas">' + "".join(arista_svg(a, idioma) for a in aristas
                                            if "etiqueta" not in a and "paso" not in a) + "</g>")
    for n in spec["nodos"]:
        if n["tipo"] != "contenedor":
            p.append(nodo_svg(n, idioma, iconos))
    # Las aristas con texto o paso se dibujan al final para que su texto no quede tapado
    p.append('<g id="aristas-con-texto">' + "".join(arista_svg(a, idioma) for a in aristas
                                                    if "etiqueta" in a or "paso" in a) + "</g>")
    p.append(banda_y_leyenda(spec, idioma))
    p.append("</svg>")
    return "".join(p)


# ------------------------------------------------------------------------------------- HTML

def render_html(spec: dict, idioma: str, svg: str) -> str:
    ancho, alto = spec["lienzo"]["ancho"], spec["lienzo"]["alto"]
    titulo = escape(spec["titulo"][idioma])
    pie = escape(f"{spec['pie'][idioma]} · {fecha_larga(spec['fecha'], idioma)}")
    return ("<!DOCTYPE html>\n"
            f'<html lang="{idioma}">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width={ancho}">\n'
            f"<title>{titulo}</title>\n"
            "<style>html,body{margin:0;padding:0;background:#fff}"
            f"main{{width:{ancho}px;height:{alto}px;overflow:hidden}}svg{{display:block}}"
            f"footer{{font:13px {FUENTE};color:#505050;padding:12px 24px}}"
            ".oculto{position:absolute;left:-10000px}</style>\n</head>\n<body>\n"
            f'<header class="oculto"><h1>{titulo}</h1></header>\n'
            f"<main>{svg}</main>\n<footer>{pie}</footer>\n</body>\n</html>\n")


# ------------------------------------------------------------------------------------- draw.io

def valor_html(lineas: list[str], negritas: int = 1) -> str:
    """Valor HTML de draw.io: el nombre (primeras líneas) en negrita. Cada línea se escapa como HTML."""
    out = [f"<b>{escape(l)}</b>" for l in lineas[:negritas]] + [escape(l) for l in lineas[negritas:]]
    return "<br>".join(out)


def celda(cid: str, valor: str, estilo: str, x, y, w, h, extra: str = "") -> str:
    return (f'<mxCell id={quoteattr(cid)} value={quoteattr(valor)} style={quoteattr(estilo)} vertex="1" '
            f'parent="1"{extra}><mxGeometry x="{fmt(x)}" y="{fmt(y)}" width="{fmt(w)}" height="{fmt(h)}" '
            f'as="geometry"/></mxCell>')


def longitud_mitad(pts: list) -> tuple:
    total = sum(abs(q[0] - p[0]) + abs(q[1] - p[1]) for p, q in zip(pts, pts[1:]))
    resto = total / 2
    for p, q in zip(pts, pts[1:]):
        d = abs(q[0] - p[0]) + abs(q[1] - p[1])
        if resto <= d and d > 0:
            t = resto / d
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        resto -= d
    return tuple(pts[-1])


def valor_grupo_drawio(g: dict, idioma: str) -> str:
    """Valor HTML de la celda de un grupo en draw.io: el título y, si lo hay, el subtítulo en otra línea."""
    valor = escape(g["titulo"][idioma])
    if g.get("subtitulo"):
        valor += "<br>" + escape(g["subtitulo"][idioma])
    return valor


def pagina_drawio(spec: dict, idioma: str, iconos: dict) -> str:
    pre = f"{idioma}-"
    c = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    ancho = spec["lienzo"]["ancho"]
    c.append(celda(pre + "titulo", escape(spec["titulo"][idioma]),
                   "text;html=1;align=left;verticalAlign=middle;fontSize=28;fontStyle=1;fontColor=#1B1B1B;",
                   40, 20, 1500, 34))
    c.append(celda(pre + "subtitulo", escape(spec["subtitulo"][idioma]),
                   "text;html=1;align=left;verticalAlign=middle;fontSize=16;fontColor=#505050;", 40, 56, 1500, 22))
    grupos = {g["id"]: g for g in spec["grupos"]}
    for g in sorted(spec["grupos"], key=lambda g: (len(ancestros(grupos, g["id"])), g["nivel"])):
        x, y, w, h = g["caja"]
        est = estilo_grupo(g)
        trazo = f"dashed=1;dashPattern={est['trazo']};" if est["trazo"] else ""
        sangria = 34 if g.get("icono") else 10
        c.append(celda(pre + "g-" + g["id"], valor_grupo_drawio(g, idioma),
                       f"rounded=1;arcSize=2;html=1;whiteSpace=wrap;fillColor={est['relleno']};"
                       f"strokeColor={est['borde']};strokeWidth={est['ancho']};{trazo}verticalAlign=top;align=left;"
                       f"spacingLeft={sangria};spacingTop=2;fontStyle=1;fontSize={est['tam']};"
                       f"fontColor={est['color']};container=0;", x, y, w, h))
        if g.get("icono"):
            datos = base64.b64encode(iconos[g["icono"]].encode("utf-8")).decode("ascii")
            c.append(celda(pre + "g-" + g["id"] + "-icono", "",
                           f"shape=image;aspect=fixed;imageAspect=1;html=1;image=data:image/svg+xml,{datos};",
                           x + 12, y + 5, 18, 18))
    for n in spec["nodos"]:
        nid = pre + "n-" + n["id"]
        lineas = n["etiqueta"][idioma]
        if n["tipo"] == "contenedor":
            x, y, w, h = n["caja"]
            c.append(celda(nid, "", f"rounded=1;arcSize=3;html=1;fillColor=#FFFFFF;strokeColor={AZUL};"
                                    "strokeWidth=1.6;", x, y, w, h))
            nid = nid + "-icono"
        if n["tipo"] == "pieza":
            x, y, w, h = n["caja"]
            c.append(celda(nid, valor_html(lineas), "rounded=1;arcSize=12;html=1;whiteSpace=wrap;align=left;"
                           "spacingLeft=12;fillColor=#EEF5FC;strokeColor=#9CC3EB;fontSize=13;fontColor=#1B1B1B;",
                           x, y, w, h))
            continue
        x0, y0, _, _ = caja_icono(n)
        etiqueta = ("verticalLabelPosition=bottom;verticalAlign=top;labelPosition=center;align=center;"
                    "html=1;fontSize=13;fontColor=#1B1B1B;labelBackgroundColor=none;")
        discontinuo = "dashed=1;" if n["estado"] == "futuro" else ""
        if n["tipo"] == "neutro":
            estilo = (f"rounded=1;arcSize=16;fillColor=#FFFFFF;strokeColor={GRIS};strokeWidth=1.5;"
                      f"{discontinuo}{etiqueta}")
        else:
            datos = base64.b64encode(iconos[n["icono"]].encode("utf-8")).decode("ascii")
            estilo = (f"shape=image;aspect=fixed;imageAspect=1;{etiqueta}"
                      f"image=data:image/svg+xml,{datos};")
        sufijo = "  ✔" if n["estado"] == "validado" else ""
        k = lineas_nombre(n)
        valor = valor_html(lineas[:k - 1] + [lineas[k - 1] + sufijo] + lineas[k:], k)
        c.append(celda(nid, valor, estilo, x0, y0, n["lado"], n["lado"]))
        if n["estado"] == "futuro":
            caja = caja_nodo(n, idioma)
            c.append(celda(nid + "-futuro", "", f"rounded=1;arcSize=8;fillColor=none;strokeColor={GRIS};dashed=1;",
                           caja[0] - 10, caja[1] - 8, caja[2] - caja[0] + 20, caja[3] - caja[1] + 14))
    nodos = {n["id"] for n in spec["nodos"]}
    for a in spec["aristas"]:
        est = ESTILO_ARISTA[a["estilo"]]
        estilo = (f"html=1;rounded=0;edgeStyle=none;endArrow=block;endFill=1;strokeColor={est['color']};"
                  f"strokeWidth={est['ancho']};fontSize=13;fontColor=#323130;labelBackgroundColor=#FFFFFF;")
        if est["trazo"]:
            estilo += f"dashed=1;dashPattern={est['trazo']};"
        ref = {}
        for extremo in ("origen", "destino"):
            r = a[extremo]
            ref[extremo] = pre + ("n-" if r in nodos else "g-") + r
        pts = a["puntos"]
        valor = "<br>".join(escape(l) for l in a.get("etiqueta", {}).get(idioma, []))
        intermedios = "".join(f'<mxPoint x="{fmt(x)}" y="{fmt(y)}"/>' for x, y in pts[1:-1])
        desplazamiento = ""
        if valor:
            mx, my = longitud_mitad(pts)
            lx, ly = a["etiqueta_xy"]
            lineas = len(a["etiqueta"][idioma])
            desplazamiento = (f'<mxPoint x="{fmt(lx - mx)}" y="{fmt(ly - my + (lineas - 1) * 8 - 4)}" '
                              f'as="offset"/>')
        c.append(f'<mxCell id={quoteattr(pre + "e-" + a["id"])} value={quoteattr(valor)} '
                 f'style={quoteattr(estilo)} edge="1" parent="1" source={quoteattr(ref["origen"])} '
                 f'target={quoteattr(ref["destino"])}><mxGeometry relative="1" as="geometry">'
                 f'<mxPoint x="{fmt(pts[0][0])}" y="{fmt(pts[0][1])}" as="sourcePoint"/>'
                 f'<mxPoint x="{fmt(pts[-1][0])}" y="{fmt(pts[-1][1])}" as="targetPoint"/>'
                 f'<Array as="points">{intermedios}</Array>{desplazamiento}</mxGeometry></mxCell>')
        if "paso" in a:
            cx, cy = punto_paso(a)
            c.append(celda(f"{pre}paso-{a['paso']}", str(a["paso"]),
                           f"ellipse;html=1;fillColor={AZUL};strokeColor=#FFFFFF;strokeWidth=2;fontColor=#FFFFFF;"
                           "fontStyle=1;fontSize=13;", cx - 12, cy - 12, 24, 24))
    bx, by, bw, bh = spec["validado"]["caja"]
    textos = [spec["validado"]["titulo"][idioma] + ":"] + ["✔ " + e[idioma] for e in spec["validado"]["elementos"]]
    if spec["validado"].get("nota"):
        textos.append(spec["validado"]["nota"][idioma])
    c.append(celda(pre + "banda-validado", "   ·   ".join(escape(t) for t in textos),
                   "rounded=1;arcSize=20;html=1;whiteSpace=wrap;fillColor=#F1F8F1;strokeColor=#9BCB9B;"
                   "align=left;spacingLeft=16;fontSize=13;fontColor=#0B5A0B;", bx, by, bw, bh))
    geo = geometria_practicas(spec)
    c.append(celda(pre + "banda-practicas", escape(spec["practicas"]["titulo"][idioma]),
                   "rounded=1;arcSize=6;html=1;whiteSpace=wrap;fillColor=#F5F9FD;strokeColor=#B7D3F0;"
                   "verticalAlign=top;align=left;spacingLeft=12;spacingTop=2;fontStyle=1;fontSize=15;"
                   f"fontColor={AZUL};", geo["x"], geo["y"], geo["w"], geo["h"]))
    por_pilar = practicas_por_pilar(spec)
    for i, pil in enumerate(spec["practicas"]["pilares"]):
        lineas = [f"<b>{escape(pil[idioma])}</b>"] + [f"<b>{escape(x['id'])}</b> {escape(x['texto'][idioma])}"
                                                      for x in por_pilar[pil["id"]]]
        c.append(celda(pre + "pilar-" + pil["id"], "<br>".join(lineas),
                       "text;html=1;whiteSpace=wrap;align=left;verticalAlign=top;spacingLeft=6;fontSize=13;"
                       "fontColor=#505050;", geo["x_col"][i], geo["y_pilar"] - 16, geo["col"], geo["h"] - 30))
    ly, py = spec["lienzo"]["leyenda_y"], spec["lienzo"]["pie_y"]
    leyenda = ("Leyenda: " if idioma == "es" else "Legend: ") + "   ·   ".join(e[idioma] for e in spec["leyenda"])
    c.append(celda(pre + "leyenda", escape(leyenda), "text;html=1;align=left;fontSize=13;fontColor=#505050;",
                   24, ly - 12, ancho - 48, 24))
    pie = f"{spec['pie'][idioma]} · {fecha_larga(spec['fecha'], idioma)}"
    c.append(celda(pre + "pie", escape(pie), "text;html=1;align=left;fontSize=13;fontColor=#505050;",
                   24, py + 8, 1200, 22))
    c.append(celda(pre + "pie-derecha", escape(spec["pie_derecha"][idioma]),
                   "text;html=1;align=right;fontSize=13;fontColor=#505050;", ancho - 624, py + 8, 600, 22))
    nombre = "Español" if idioma == "es" else "English"
    alto = spec["lienzo"]["alto"]
    return (f'<diagram id="diagrama-{idioma}" name="{nombre}"><mxGraphModel dx="{ancho}" dy="{alto}" grid="0" '
            f'gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
            f'pageWidth="{ancho}" pageHeight="{spec["lienzo"]["alto"]}" background="#FFFFFF" math="0" '
            f'shadow="0"><root>{"".join(c)}</root></mxGraphModel></diagram>')


def render_drawio(spec: dict, iconos: dict) -> str:
    paginas = "".join(pagina_drawio(spec, i, iconos) for i in IDIOMAS)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<mxfile host="generar_diagrama.py" version="1" type="device">{paginas}</mxfile>\n')


# ------------------------------------------------------------------------------- comprobaciones

PELIGROSO = [
    (re.compile(r"<\s*script", re.I), "<script"),
    (re.compile(r"<[^>]*\son[a-z]+\s*=", re.I), "manejador on*"),
    (re.compile(r"javascript\s*:", re.I), "javascript:"),
    (re.compile(r"<\s*(iframe|object|embed|foreignObject)\b", re.I), "elemento activo"),
]


ETIQUETAS_DRAWIO = {"<b>", "</b>", "<br>"}


def comprueba_seguridad(texto: str, nombre: str) -> list[str]:
    return [f"{nombre}: contiene {desc}" for rx, desc in PELIGROSO if rx.search(texto)]


def texto_xml(s: str) -> str:
    return escape(s)


def comprueba_svg(spec: dict, idioma: str, svg: str, nombre: str) -> list[str]:
    e = comprueba_seguridad(svg, nombre)
    try:
        raiz = ET.fromstring(svg)
    except ET.ParseError as ex:
        return e + [f"{nombre}: XML mal formado ({ex})"]
    ns = "{http://www.w3.org/2000/svg}"
    por_id = {el.get("id"): el for el in raiz.iter() if el.get("id")}
    ids = [el.get("id") for el in raiz.iter() if el.get("id")]
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        e.append(f"{nombre}: id repetidos {repetidos[:5]}")

    def textos(el) -> list[str]:
        return ["".join(t.itertext()) for t in el.iter(ns + "text")]

    for n in spec["nodos"]:
        el = por_id.get(f"n-{n['id']}")
        if el is None:
            e.append(f"{nombre}: falta el nodo {n['id']}")
            continue
        presentes = textos(el)
        for l in n["etiqueta"][idioma]:
            if l not in presentes:
                e.append(f"{nombre}: el nodo {n['id']} no muestra «{l}»")
        if n.get("icono"):
            iconos = [s for s in el.iter(ns + "svg")]
            if len(iconos) < 2:  # envoltorio + svg original
                e.append(f"{nombre}: el nodo {n['id']} no lleva su icono incrustado")
        if n["estado"] == "validado" and not any(g.get("class") == "validado" for g in el.iter(ns + "g")):
            e.append(f"{nombre}: el nodo {n['id']} no lleva la marca de validado")
    for a in spec["aristas"]:
        el = por_id.get(f"e-{a['id']}")
        if el is None:
            e.append(f"{nombre}: falta la arista {a['id']}")
            continue
        if el.find(ns + "polyline") is None:
            e.append(f"{nombre}: la arista {a['id']} no tiene trazo")
        presentes = textos(el)
        for l in a.get("etiqueta", {}).get(idioma, []):
            if l not in presentes:
                e.append(f"{nombre}: la arista {a['id']} no muestra «{l}»")
        if "paso" in a and str(a["paso"]) not in presentes:
            e.append(f"{nombre}: la arista {a['id']} no muestra el paso {a['paso']}")
    for g in spec["grupos"]:
        el = por_id.get(f"g-{g['id']}")
        if el is None or g["titulo"][idioma] not in textos(el):
            e.append(f"{nombre}: falta el grupo {g['id']} o su título")
        elif g.get("subtitulo") and g["subtitulo"][idioma] not in textos(el):
            e.append(f"{nombre}: el grupo {g['id']} no muestra su subtítulo")
        elif g.get("icono") and len(list(el.iter(ns + "svg"))) < 2:
            e.append(f"{nombre}: el grupo {g['id']} no lleva su icono incrustado")
    banda = por_id.get("banda-practicas")
    if banda is None or spec["practicas"]["titulo"][idioma] not in textos(banda):
        e.append(f"{nombre}: falta la banda de prácticas o su título")
    else:
        practicas = {g.get("data-id"): g for g in banda.iter(ns + "g") if g.get("class") == "practica"}
        for pil in spec["practicas"]["pilares"]:
            el = por_id.get(f"pilar-{pil['id']}")
            if el is None or pil[idioma] not in textos(el):
                e.append(f"{nombre}: falta el pilar {pil['id']} o su nombre")
        for x in spec["practicas"]["catalogo"]:
            el = practicas.get(x["id"])
            if el is None:
                e.append(f"{nombre}: falta la práctica {x['id']}")
                continue
            if x["id"] not in textos(el) or x["texto"][idioma] not in textos(el):
                e.append(f"{nombre}: la práctica {x['id']} no muestra su id y su texto")
            tit = el.find(ns + "title")
            if tit is None or x["url"] not in (tit.text or "") or x["cita"] not in (tit.text or ""):
                e.append(f"{nombre}: la práctica {x['id']} no lleva su URL y su cita")
    todo = ["".join(t.itertext()) for t in raiz.iter(ns + "text")]
    for clave in ("subtitulo",):
        if spec[clave][idioma] not in todo:
            e.append(f"{nombre}: falta el {clave}")
    if spec["titulo"][idioma] not in todo:
        e.append(f"{nombre}: falta el título")
    if not any(spec["pie"][idioma] in t for t in todo):
        e.append(f"{nombre}: falta el pie con el crédito de los iconos")
    if spec["pie_derecha"][idioma] not in todo:
        e.append(f"{nombre}: falta el pie de la derecha")
    if spec["validado"]["titulo"][idioma] not in todo:
        e.append(f"{nombre}: falta el título de la banda validado")
    for el in spec["validado"]["elementos"] + ([spec["validado"]["nota"]] if spec["validado"].get("nota") else []):
        if el[idioma] not in todo:
            e.append(f"{nombre}: la banda no muestra «{el[idioma]}»")
    for el in spec["leyenda"]:
        if el[idioma] not in todo:
            e.append(f"{nombre}: la leyenda no muestra «{el[idioma]}»")
    return e


def comprueba_html(spec: dict, idioma: str, html: str, nombre: str) -> list[str]:
    e = comprueba_seguridad(html, nombre)
    m = re.search(r"<main>(.*)</main>", html, re.S)
    if not m:
        return e + [f"{nombre}: no contiene el SVG"]
    e += comprueba_svg(spec, idioma, m.group(1), nombre)
    if f"<title>{escape(spec['titulo'][idioma])}</title>" not in html:
        e.append(f"{nombre}: falta el <title>")
    if escape(spec["pie"][idioma]) not in html.split("</main>", 1)[1]:
        e.append(f"{nombre}: falta el pie")
    return e


def comprueba_drawio(spec: dict, drawio: str, nombre: str) -> list[str]:
    e = comprueba_seguridad(drawio, nombre)
    try:
        raiz = ET.fromstring(drawio)
    except ET.ParseError as ex:
        return e + [f"{nombre}: XML mal formado ({ex})"]
    paginas = {d.get("id"): d for d in raiz.iter("diagram")}
    ids_fichero = [c.get("id") for c in raiz.iter("mxCell")]
    repetidos = sorted({i for i in ids_fichero if ids_fichero.count(i) > 1 and i not in ("0", "1")})
    if repetidos:
        e.append(f"{nombre}: id de celda repetidos {repetidos[:5]}")
    for idioma in IDIOMAS:
        d = paginas.get(f"diagrama-{idioma}")
        if d is None:
            e.append(f"{nombre}: falta la página {idioma}")
            continue
        celdas = {c.get("id"): c for c in d.iter("mxCell")}
        valores = " ".join(c.get("value") or "" for c in celdas.values())
        pre = f"{idioma}-"
        # Con html=1, draw.io interpreta el valor como HTML: solo se admiten <b>, </b> y <br>.
        for cid, cel in celdas.items():
            for etiqueta in re.findall(r"<[^>]*>?", cel.get("value") or ""):
                if etiqueta not in ETIQUETAS_DRAWIO:
                    e.append(f"{nombre} [{idioma}]: la celda {cid} trae marcado no admitido {etiqueta[:30]!r}")
        fijos = {"titulo": spec["titulo"][idioma], "subtitulo": spec["subtitulo"][idioma],
                 "pie": spec["pie"][idioma], "pie-derecha": spec["pie_derecha"][idioma]}
        for cid, texto in fijos.items():
            if pre + cid not in celdas or escape(texto) not in (celdas[pre + cid].get("value") or ""):
                e.append(f"{nombre} [{idioma}]: falta el {cid}")
        def valor(cid: str) -> str:
            return (celdas[cid].get("value") or "") if cid in celdas else ""

        banda = valor(pre + "banda-validado")
        nota = [spec["validado"]["nota"][idioma]] if spec["validado"].get("nota") else []
        for texto in [spec["validado"]["titulo"][idioma]] + [el[idioma] for el in spec["validado"]["elementos"]] + nota:
            if escape(texto) not in banda:
                e.append(f"{nombre} [{idioma}]: la banda no muestra «{texto}»")
        leyenda = valor(pre + "leyenda")
        for el in spec["leyenda"]:
            if escape(el[idioma]) not in leyenda:
                e.append(f"{nombre} [{idioma}]: la leyenda no muestra «{el[idioma]}»")
        for n in spec["nodos"]:
            if pre + "n-" + n["id"] not in celdas:
                e.append(f"{nombre} [{idioma}]: falta el nodo {n['id']}")
            for l in n["etiqueta"][idioma]:
                if escape(l) not in valores:
                    e.append(f"{nombre} [{idioma}]: no aparece «{l}» del nodo {n['id']}")
            if n.get("icono"):
                cid = pre + "n-" + n["id"] + ("-icono" if n["tipo"] == "contenedor" else "")
                estilo = (celdas.get(cid).get("style") if cid in celdas else "") or ""
                if "image=data:image/svg+xml," not in estilo:
                    e.append(f"{nombre} [{idioma}]: el nodo {n['id']} no lleva su icono incrustado")
        for a in spec["aristas"]:
            cel = celdas.get(pre + "e-" + a["id"])
            if cel is None or cel.get("edge") != "1":
                e.append(f"{nombre} [{idioma}]: falta la arista {a['id']}")
                continue
            for extremo, attr in (("origen", "source"), ("destino", "target")):
                if cel.get(attr) not in celdas:
                    e.append(f"{nombre} [{idioma}]: la arista {a['id']} apunta a un {extremo} inexistente")
            for l in a.get("etiqueta", {}).get(idioma, []):
                if escape(l) not in (cel.get("value") or ""):
                    e.append(f"{nombre} [{idioma}]: la arista {a['id']} no muestra «{l}»")
            if "paso" in a and pre + f"paso-{a['paso']}" not in celdas:
                e.append(f"{nombre} [{idioma}]: falta el círculo del paso {a['paso']}")
        for g in spec["grupos"]:
            if pre + "g-" + g["id"] not in celdas:
                e.append(f"{nombre} [{idioma}]: falta el grupo {g['id']}")
            elif valor_grupo_drawio(g, idioma) != valor(pre + "g-" + g["id"]):
                e.append(f"{nombre} [{idioma}]: el grupo {g['id']} no muestra su título o su subtítulo")
            icono = celdas.get(pre + "g-" + g["id"] + "-icono")
            if g.get("icono") and (icono is None or "image=data:image/svg+xml," not in (icono.get("style") or "")):
                e.append(f"{nombre} [{idioma}]: el grupo {g['id']} no lleva su icono incrustado")
        if escape(spec["practicas"]["titulo"][idioma]) not in valor(pre + "banda-practicas"):
            e.append(f"{nombre} [{idioma}]: falta la banda de prácticas o su título")
        por_pilar = practicas_por_pilar(spec)
        for pil in spec["practicas"]["pilares"]:
            texto = valor(pre + "pilar-" + pil["id"])
            if f"<b>{escape(pil[idioma])}</b>" not in texto:
                e.append(f"{nombre} [{idioma}]: falta el pilar {pil['id']} o su nombre")
            for x in por_pilar[pil["id"]]:
                if f"<b>{escape(x['id'])}</b> {escape(x['texto'][idioma])}" not in texto:
                    e.append(f"{nombre} [{idioma}]: la práctica {x['id']} no aparece en su pilar")
    return e


# ---------------------------------------------------------------------------------- generación

def generar(spec: dict, iconos: dict) -> dict[str, str]:
    """Construye todas las salidas en memoria y las comprueba. No escribe nada."""
    errores = validar_spec(spec)
    if errores:
        raise ErrorDiagrama("especificación no válida:\n  " + "\n  ".join(errores))
    salidas: dict[str, str] = {}
    for idioma in IDIOMAS:
        svg = render_svg(spec, idioma, iconos)
        salidas[f"arquitectura.{idioma}.svg"] = svg
        salidas[f"arquitectura.{idioma}.html"] = render_html(spec, idioma, svg)
    salidas["arquitectura.drawio"] = render_drawio(spec, iconos)
    errores = []
    for idioma in IDIOMAS:
        errores += comprueba_svg(spec, idioma, salidas[f"arquitectura.{idioma}.svg"], f"arquitectura.{idioma}.svg")
        errores += comprueba_html(spec, idioma, salidas[f"arquitectura.{idioma}.html"],
                                  f"arquitectura.{idioma}.html")
    errores += comprueba_drawio(spec, salidas["arquitectura.drawio"], "arquitectura.drawio")
    if errores:
        raise ErrorDiagrama("las salidas no pasan las comprobaciones:\n  " + "\n  ".join(errores))
    return salidas


def escribir(salidas: dict[str, str], carpeta: Path) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    for nombre, texto in salidas.items():
        (carpeta / nombre).write_bytes(texto.encode("utf-8"))  # LF y UTF-8 sin BOM, también en Windows


def tamano_png(ruta: Path) -> tuple[int, int]:
    datos = ruta.read_bytes()[:24]
    if len(datos) < 24 or datos[:8] != b"\x89PNG\r\n\x1a\n" or datos[12:16] != b"IHDR":
        raise ErrorDiagrama(f"{ruta.name}: no es un PNG válido")
    return struct.unpack(">II", datos[16:24])


def renderizar_png(spec: dict, carpeta: Path, edge: str) -> None:
    if not Path(edge).is_file():
        raise ErrorEntorno(f"no encuentro Microsoft Edge en {edge}")
    ancho, alto = spec["lienzo"]["ancho"], spec["lienzo"]["alto"]
    for idioma in IDIOMAS:
        html = (carpeta / f"arquitectura.{idioma}.html").resolve()
        png = (carpeta / f"arquitectura.{idioma}.png").resolve()
        if png.exists():
            png.unlink()
        cmd = [edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--screenshot={png}",
               f"--window-size={ancho},{alto}", "--default-background-color=FFFFFFFF",
               "--force-device-scale-factor=1",
               # Sin esta opción, Edge a veces captura antes de pintar todas las teselas (ronda 3: leyenda a medias).
               "--run-all-compositor-stages-before-draw", html.as_uri()]
        try:
            r = subprocess.run(cmd, check=False, timeout=80, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE)
        except subprocess.TimeoutExpired as ex:
            raise ErrorEntorno(f"Edge no terminó en 80 s con {html.name}") from ex
        if r.returncode != 0:
            detalle = r.stderr.decode("utf-8", "replace").strip()[-300:]
            raise ErrorEntorno(f"Edge salió con {r.returncode} con {html.name}: {detalle}")
        if not png.is_file():
            raise ErrorEntorno(f"Edge no generó {png.name}")
        if tamano_png(png) != (ancho, alto):
            raise ErrorDiagrama(f"{png.name}: mide {tamano_png(png)}, se esperaba {(ancho, alto)}")


def publicar(origen: Path, destino: Path, nombres: list[str]) -> None:
    """Copia primero cada salida a un temporal junto al destino y solo después renombra (os.replace).

    Si falla una copia (espacio, permisos), se borran los temporales y no se toca ninguna salida previa.
    Si fallara un renombrado ya empezado (raro en la misma carpeta), la excepción sube y main sale con 2:
    la publicación puede quedar a medias y basta con volver a ejecutar.
    """
    destino.mkdir(parents=True, exist_ok=True)
    pares: list[tuple[Path, Path]] = []
    try:
        for nombre in nombres:
            temporal = destino / f".{nombre}.{os.getpid()}.tmp"  # sin choques entre ejecuciones
            pares.append((temporal, destino / nombre))
            shutil.copyfile(origen / nombre, temporal)
        for temporal, final in pares:
            os.replace(temporal, final)
    finally:
        for temporal, _ in pares:
            if temporal.exists():
                temporal.unlink()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Genera el diagrama de arquitectura desde arquitectura.json.")
    ap.add_argument("--spec", type=Path, default=SPEC_DEFECTO)
    ap.add_argument("--iconos", type=Path, default=Path(ICONOS_DEFECTO),
                    help="carpeta Icons/ del juego oficial Azure Architecture Icons (también ICONOS_AZURE)")
    ap.add_argument("--iconos-entra", type=Path, default=Path(ICONOS_ENTRA_DEFECTO),
                    help="carpeta raíz del juego oficial Microsoft Entra architecture icons (también ICONOS_ENTRA)")
    ap.add_argument("--salida", type=Path, default=AQUI)
    ap.add_argument("--png", action="store_true", help="renderiza los PNG con Microsoft Edge en modo headless")
    ap.add_argument("--edge", default=EDGE_DEFECTO)
    args = ap.parse_args(argv)
    try:
        spec = cargar_spec(args.spec)
        errores = validar_spec(spec)  # antes de los iconos: un JSON mal hecho es 1, no error de entorno
        if errores:
            raise ErrorDiagrama("especificación no válida:\n  " + "\n  ".join(errores))
        iconos = cargar_iconos(spec, {"azure_v24": args.iconos, "entra_oct2023": args.iconos_entra})
        salidas = generar(spec, iconos)
        with tempfile.TemporaryDirectory(prefix="diagrama-") as tmp:
            preparada = Path(tmp)
            escribir(salidas, preparada)
            nombres = list(salidas)
            if args.png:
                renderizar_png(spec, preparada, args.edge)
                nombres += [f"arquitectura.{idioma}.png" for idioma in IDIOMAS]
            publicar(preparada, args.salida, nombres)
        for nombre in nombres:
            medida = f" {spec['lienzo']['ancho']}x{spec['lienzo']['alto']}" if nombre.endswith(".png") else ""
            print(f"OK {nombre}{medida}")
    except ErrorEntorno as ex:
        print(f"ERROR DE ENTORNO: {ex}", file=sys.stderr)
        return 2
    except (ErrorDiagrama, ET.ParseError, KeyError, ValueError, TypeError, AttributeError, IndexError) as ex:
        print(f"FALLA: {ex}", file=sys.stderr)
        return 1
    except OSError as ex:
        print(f"ERROR DE ENTORNO: {ex}", file=sys.stderr)
        return 2
    print(f"VEREDICTO: OK · {len(spec['nodos'])} nodos y {len(spec['aristas'])} aristas en todas las salidas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
