"""Estimación económica de I1 (constructor B; CONTRATOS.md §4.11 y §13, reglas P6 y P7).

Convierte las `tareas_propuestas` validadas del experto en la entrada del generador canónico
(`_templates/estimacion/generar_estimacion.py`, que NUNCA se modifica; LES-G-081), aplica las
puertas de negocio como código y ejecuta el generador en un árbol temporal, como en I0:

  <base>/<tmp>/_templates/estimacion/{generar_estimacion.py, OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx}
  <base>/<tmp>/_config/rate-card.json

Puertas: PM >= 8 h (bloquea; el generador solo avisa, LES-G-001), perfiles y tarifas solo de la
tarifa, contingencia 0, ajuste comercial 0 salvo decisión AJUSTE_COMERCIAL que cite el hash
vigente, hitos iguales a los de la tarifa, tareas trazables y STOP por encima de 100.000 EUR
(LES-G-004). Las puertas del sandbox ayudan pero no controlan: la puerta real es
`verificar_paquete.py` en local. Nada imprime ni guarda: lo hace la CLI.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

from nucleo import estado as est_mod
from nucleo.errores import EntradaInvalida, IntegridadRota, ReglaIncumplida

PERFIL_PM = "Project Manager"
FASE_PM = "Gestión de proyecto"
PM_MINIMO_H = Decimal("8")
UMBRAL_STOP_EUR = Decimal("100000.00")
HOLGURA = Decimal("0.2")
GENERADOR = "generar_estimacion.py"
PLANTILLA = "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx"
HOJA_EST = "Estimación Esfuerzo"
HOJA_RES = "Resumen Económico"
TIMEOUT_S = 300
_CAMPOS_TRAZA = ("fase", "tarea", "perfil", "descripcion", "entregable")
_AJUSTE_RE = re.compile(r"^importe_eur=(-?[0-9]+\.[0-9]{2}); motivo=(.{10,400})$", re.S)
_CONTINGENCIA_RE = re.compile(r"contingencia", re.I)
_CENT = Decimal("0.01")
TOLERANCIA_GENERADOR = Decimal("0.01")  # ver comparar()


@dataclass(frozen=True)
class RutasGenerador:
    """Rutas de los ficheros canónicos montados y del directorio temporal de trabajo.

    `sha256_generador` y `sha256_plantilla` son los del manifiesto (opcionales en local); si se
    dan y no coinciden con el fichero, IntegridadRota (CAMBIOS-INTERFAZ-B.md, punto 1).
    """
    generador: pathlib.Path
    plantilla: pathlib.Path
    rate_card: pathlib.Path
    base_tmp: pathlib.Path
    sha256_generador: str | None = None
    sha256_plantilla: str | None = None


@dataclass(frozen=True)
class ResultadoEstimacion:
    """Resultado de `estimar`. `stop` es conservador: ver `requiere_stop` (CAMBIOS-INTERFAZ-B.md)."""
    resumen: dict
    stop: bool
    ruta_xlsx: pathlib.Path
    xlsx_sha256: str
    salida_generador: str = ""


# ── Utilidades ──────────────────────────────────────────────────────────────

def _dec(x: object) -> Decimal:
    """Decimal exacto de un número JSON (sin booleanos, NaN ni infinito)."""
    if isinstance(x, bool) or not isinstance(x, (int, float, Decimal)):
        raise ValueError(f"no es un número: {x!r}")
    d = Decimal(str(x))
    if not d.is_finite():
        raise ValueError(f"número no finito: {x!r}")
    return d


def _eur(x: Decimal) -> str:
    """Importe u horas como cadena con dos decimales (ROUND_HALF_UP, igual que ROUND de Excel)."""
    return str(x.quantize(_CENT, rounding=ROUND_HALF_UP))


def _nfc(obj: object) -> object:
    """Copia profunda con todas las cadenas (claves incluidas) en NFC."""
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, list):
        return [_nfc(x) for x in obj]
    if isinstance(obj, dict):
        return {_nfc(k): _nfc(v) for k, v in obj.items()}
    return obj


def _textos(obj: object, ruta: str = "$"):
    """Recorre todas las cadenas de un JSON con su ruta."""
    if isinstance(obj, str):
        yield ruta, obj
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            yield from _textos(x, f"{ruta}[{i}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _textos(v, f"{ruta}.{k}")


def _sha256(ruta: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def horas_tarea(tecnicas_h: object, reuniones_h: object) -> Decimal:
    """D = E + ROUND(E*0,2; 0) + G, como la fórmula del XLSX canónico (LES-G-002).

    La holgura se redondea igual que `generar_estimacion.redondeo_excel` (producto en coma flotante
    leído con repr y ROUND_HALF_UP), para que la réplica coincida también en los casos límite.
    """
    e, g = _dec(tecnicas_h), _dec(reuniones_h)
    f = Decimal(repr(float(e) * 0.2)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return e + f + g


# ── Tarifa ──────────────────────────────────────────────────────────────────

def cargar_tarifa(ruta: pathlib.Path) -> dict:
    """Bloque «tarifa» de la instantánea rate-card.json (skill rate-card v4).

    EntradaInvalida si no se puede leer; IntegridadRota si la contingencia no es 0, hay perfiles
    repetidos, no hay perfiles o los hitos de pago no son coherentes.
    """
    try:
        snap = json.loads(pathlib.Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise EntradaInvalida(f"No se puede leer la tarifa {ruta}: {e}", [str(e)])
    t = snap.get("tarifa", snap) if isinstance(snap, dict) else None
    errores = []
    if not isinstance(t, dict):
        raise IntegridadRota("rate-card.json no contiene un objeto de tarifa", ["sin bloque tarifa"])
    cont = t.get("contingencia_porcentaje", 0)
    if isinstance(cont, bool) or not isinstance(cont, (int, float)) or cont != 0:
        errores.append(f"contingencia_porcentaje = {cont!r}; debe ser 0 (LES-G-081)")
    perf = t.get("perfiles")
    if not isinstance(perf, list) or not perf:
        errores.append("la tarifa no tiene perfiles")
        perf = []
    nombres = []
    for i, p in enumerate(perf):
        if not isinstance(p, dict) or not isinstance(p.get("nombre"), str) or not p["nombre"].strip():
            errores.append(f"perfiles[{i}]: sin nombre")
            continue
        nombres.append(p["nombre"])
        th = p.get("tarifa_hora")
        if isinstance(th, bool) or not isinstance(th, (int, float)) or not th > 0:
            errores.append(f"perfiles[{i}] «{p['nombre']}»: tarifa_hora {th!r} no válida")
        if not isinstance(p.get("nivel"), str):
            errores.append(f"perfiles[{i}] «{p['nombre']}»: sin nivel")
    repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
    if repetidos:
        errores.append(f"perfiles repetidos: {', '.join(repetidos)}")
    hitos = t.get("hitos_pago")
    if not isinstance(hitos, list) or not hitos:
        errores.append("la tarifa no tiene hitos_pago")
    else:
        try:
            suma = sum((_dec(h["porcentaje"]) for h in hitos), Decimal(0))
            if suma != 100 or any(not isinstance(h.get("descripcion"), str) for h in hitos):
                errores.append(f"hitos_pago incoherentes (suman {suma})")
        except (KeyError, TypeError, ValueError) as e:
            errores.append(f"hitos_pago no válidos: {e}")
    if errores:
        raise IntegridadRota("Tarifa rechazada", errores)
    return _nfc(t)


def perfiles(tarifa: dict) -> list[str]:
    """Nombres de perfil de la tarifa, en su orden."""
    return [p["nombre"] for p in tarifa["perfiles"]]


def hitos_tarifa(tarifa: dict) -> list[dict]:
    """Hitos que debe llevar la entrada: «Hito n - descripción» y porcentaje, en orden de hito."""
    orden = sorted(tarifa["hitos_pago"], key=lambda h: h.get("hito", 0))
    return [{"nombre": f"Hito {h.get('hito', i)} - {h['descripcion']}", "porcentaje": h["porcentaje"]}
            for i, h in enumerate(orden, 1)]


def tarifa_para_generador(tarifa: dict) -> dict:
    """Convierte el bloque tarifa al formato de _config/rate-card.json que lee el generador."""
    return {"pilar": tarifa.get("pilar", "Microsoft"), "empresa": tarifa.get("empresa", "Devoteam M Cloud"),
            "moneda": tarifa.get("moneda", "EUR"), "contingencia_porcentaje": 0,
            "perfiles": [{"nombre": p["nombre"], "nivel": p["nivel"], "tarifa_hora": p["tarifa_hora"],
                          "descripcion": p.get("descripcion", "")} for p in tarifa["perfiles"]],
            "hitos_pago_defecto": tarifa.get("hitos_pago", []),
            "condiciones_pago": tarifa.get("condiciones_pago", "30 días fecha factura"),
            "validez_oferta_dias": tarifa.get("validez_oferta_dias", 30)}


def _tarifas(tarifa: dict) -> dict[str, Decimal]:
    return {p["nombre"]: _dec(p["tarifa_hora"]) for p in tarifa["perfiles"]}


# ── Composición de la entrada por código (regla del comercial del 10-10-2026) ──
# La usan igual A (`estimar` sin --entrada) y B (hosted/preventa_hosted/estimacion_entrada.py): ningún modelo
# escribe la entrada del generador. El generador canónico no cambia; `validar_entrada` la vuelve a validar.

PM_PORCENTAJE = Decimal("0.15")
HORAS_SEMANA_PERFIL = 40
MAX_TEXTO, MAX_LISTA = 400, 30  # asunciones y exclusiones (esquema estimacion_entrada)
MAX_PM_TECNICAS, MAX_PM_REUNIONES = 400, 80  # topes de tecnicas_h y reuniones_h por tarea (esquema)
MAX_CONTENIDO_GANTT = 200
TAREA_PM = "Coordinación, seguimiento y reporting"
DESCRIPCION_PM = "Planificación, seguimiento del avance, gestión de riesgos y reporting al cliente."
ENTREGABLE_PM = "Informes de seguimiento"


def horas_pm(tecnicas: object) -> int:
    """Horas técnicas de gestión de proyecto: máx(8 h, ⌈15 % de las horas técnicas⌉) (LES-G-001)."""
    quince = (_dec(tecnicas) * PM_PORCENTAJE).to_integral_value(rounding=ROUND_CEILING)
    return int(max(PM_MINIMO_H, quince))


def semanas_fase(horas: object, perfiles_distintos: int) -> int:
    """Semanas de una fase con sus perfiles distintos en paralelo: máx(1, ⌈horas / (40 × perfiles)⌉)."""
    if isinstance(perfiles_distintos, bool) or not isinstance(perfiles_distintos, int) or perfiles_distintos < 1:
        raise ValueError(f"número de perfiles no válido: {perfiles_distintos!r}")
    capacidad = Decimal(HORAS_SEMANA_PERFIL * perfiles_distintos)
    return int(max(Decimal(1), (_dec(horas) / capacidad).to_integral_value(rounding=ROUND_CEILING)))


def _trozos(total: int, tope: int, n: int) -> list[int]:
    """Reparte `total` en `n` trozos de como mucho `tope`, los primeros llenos."""
    return [min(tope, max(0, total - i * tope)) for i in range(n)]


def _tareas_pm(tecnicas: int, reuniones: int) -> list[dict]:
    """PM-01, PM-02… con los topes del esquema por tarea (solo hace falta más de una por encima de 400 h)."""
    n = max(1, -(-tecnicas // MAX_PM_TECNICAS), -(-reuniones // MAX_PM_REUNIONES))
    return [{"id": f"PM-{i + 1:02d}", "fase": FASE_PM, "tarea": TAREA_PM, "perfil": PERFIL_PM, "tecnicas_h": t,
             "reuniones_h": r, "descripcion": DESCRIPCION_PM, "entregable": ENTREGABLE_PM}
            for i, (t, r) in enumerate(zip(_trozos(tecnicas, MAX_PM_TECNICAS, n), _trozos(reuniones, MAX_PM_REUNIONES, n)))]


def _textos_admitidos(candidatos: list, que: str, avisos: list[str]) -> list[str]:
    """Textos que caben en el esquema y pasan las reglas de `validar_entrada`; lo demás se omite y se declara."""
    from nucleo import textos_cliente  # importación diferida: módulo de C
    salida = []
    for t in candidatos:
        if isinstance(t, str) and not t.strip():
            continue  # texto vacío: no hay nada que perder (un None sí se declara)
        motivo = None
        if not isinstance(t, str):
            motivo, t = "no es un texto", repr(t)
        elif len(t.strip()) < 5:
            motivo = "tiene menos de 5 caracteres"
        elif len(t) > MAX_TEXTO:
            motivo = f"supera {MAX_TEXTO} caracteres"
        elif _CONTINGENCIA_RE.search(t):
            motivo = "menciona contingencia (LES-G-081)"
        elif t.lstrip()[:1] in ("=", "+", "@"):
            motivo = "empieza como una fórmula de Excel"
        elif textos_cliente.marcadores(t):
            motivo = f"lleva un marcador prohibido ({', '.join(textos_cliente.marcadores(t))})"
        elif len(salida) >= MAX_LISTA:
            motivo = f"supera las {MAX_LISTA} admitidas"
        if motivo:
            avisos.append(f"{que} omitida ({motivo}): «{t[:80]}»")
        else:
            salida.append(t)
    return salida


def componer_entrada(estado: dict, hitos: list[dict], hoy: date | None = None,
                     ajuste: tuple[Decimal, str] | None = None) -> tuple[dict, list[str]]:
    """(entrada del generador, avisos) compuesta desde las `tareas_propuestas` del experto registrado.

    - Una tarea por cada propuesta, con los mismos campos, `tecnicas_h` = `horas_base` y sus `reuniones_h` (P6d).
    - Fases en el orden de aparición más «Gestión de proyecto». Gantt secuencial por fases; dentro de cada fase
      sus perfiles distintos trabajan en paralelo: semanas = máx(1, ⌈horas de la fase / (40 × perfiles)⌉), con las
      horas de la fase como en el XLSX (técnicas + holgura del 20 % + reuniones).
    - Gestión de proyecto: máx(8 h, ⌈15 % de las horas técnicas⌉) y 1 h de seguimiento por semana, en todas.
    - Hitos = `hitos` (los de la tarifa, `hitos_tarifa`); ajuste 0 salvo `ajuste` = (importe, motivo) de la
      decisión AJUSTE_COMERCIAL (`leer_ajuste`); sin contingencia.
    - Asunciones = supuestos del experto; exclusiones = `fuera_de_alcance`. Lo que no cabe se omite y se avisa.
    ValueError si falta algo para componerla. No muta `estado`.
    """
    carga = estado.get("carga") or {}
    resp = est_mod.registro_de_carga(carga).get("respuesta") or {}
    propuestas = [t for t in resp.get("tareas_propuestas") or [] if isinstance(t, dict)]
    if not propuestas:
        raise ValueError("No hay tareas_propuestas del experto registradas: no se puede componer la estimación")
    alta = carga.get("alta") or {}
    if not estado.get("codigo") or not alta.get("cliente") or not alta.get("titulo"):
        raise ValueError("El estado no tiene código, cliente o título del alta")
    tareas, fases = [], []
    for p in propuestas:
        tareas.append({"id": p.get("id"), "fase": p.get("fase"), "tarea": p.get("tarea"), "perfil": p.get("perfil"),
                       "tecnicas_h": p.get("horas_base"), "reuniones_h": p.get("reuniones_h"),
                       "descripcion": p.get("descripcion"), "entregable": p.get("entregable")})
        if p.get("fase") not in fases:
            fases.append(p.get("fase"))
    try:
        horas = [horas_tarea(t["tecnicas_h"], t["reuniones_h"]) for t in tareas]
        tecnicas = sum((_dec(t["tecnicas_h"]) for t in tareas), Decimal(0))
    except ValueError as e:
        raise ValueError(f"tareas_propuestas con horas no numéricas: {e}") from e
    gantt, semana = [], 1
    for f in fases:
        de_fase = [i for i, t in enumerate(tareas) if t["fase"] == f]
        perfiles_fase = {tareas[i]["perfil"] for i in de_fase}
        n = semanas_fase(sum((horas[i] for i in de_fase), Decimal(0)), len(perfiles_fase))
        nombres = "; ".join(str(tareas[i]["tarea"]) for i in de_fase)
        contenido = nombres if len(nombres) <= MAX_CONTENIDO_GANTT else f"{len(de_fase)} tareas de {f}"[:MAX_CONTENIDO_GANTT]
        gantt.append({"fase": f, "contenido": contenido, "semanas": list(range(semana, semana + n))})
        semana += n
    duracion = semana - 1
    tareas += _tareas_pm(horas_pm(tecnicas), duracion)
    gantt.append({"fase": FASE_PM, "contenido": "Coordinación y seguimiento", "semanas": list(range(1, duracion + 1))})
    avisos: list[str] = []
    from nucleo import textos_cliente  # diferido, como en _textos_admitidos (VER14-10, CAMBIOS-I15-D §4)
    supuestos, avisos_supuestos = textos_cliente.asunciones_estimacion(resp, duracion)
    avisos += avisos_supuestos
    fda = (((carga.get("requisitos") or {}).get("campos") or {}).get("fuera_de_alcance") or {}).get("entradas") or []
    entrada = {
        "codigo": estado["codigo"], "cliente": alta["cliente"], "titulo": alta["titulo"],
        "fecha": (hoy or date.today()).isoformat(), "duracion_semanas": duracion, "fases": fases + [FASE_PM],
        "tareas": tareas, "hitos": [dict(h) for h in hitos], "gantt": gantt,
        "asunciones": _textos_admitidos(supuestos, "asunción", avisos),
        "exclusiones": _textos_admitidos([e.get("valor") for e in fda if isinstance(e, dict)], "exclusión", avisos),
        "ajuste_comercial_eur": 0,
    }
    if ajuste is not None:
        importe, motivo = ajuste
        entrada["ajuste_comercial_eur"] = float(_dec(importe))
        entrada["ajuste_comercial_motivo"] = motivo
    return entrada, avisos


# ── Validación de la entrada (P6) ───────────────────────────────────────────

def _contexto(estado: dict) -> tuple[dict, list[str]]:
    """Respuesta del experto vigente y precondiciones de T4 (P2 y orden anexo → estimar)."""
    carga = estado.get("carga") or {}
    errores = []
    resp = est_mod.registro_de_carga(carga).get("respuesta")
    if not isinstance(resp, dict):
        errores.append("P2: no hay respuesta válida de preventa-experto-azure registrada")
        resp = {}
    resultado = (carga.get("verificacion") or {}).get("resultado") or {}
    if resultado.get("verificada") is not True:
        errores.append("P5: la verificación vigente no está superada (sin DISCREPA efectivos)")
    anexo = carga.get("anexo_consumo")
    if not isinstance(anexo, dict):
        errores.append("Orden de T4: falta el anexo de consumo; ejecutar antes anexo-consumo")
    elif anexo.get("codigo") != estado.get("codigo"):
        errores.append(f"El anexo es de {anexo.get('codigo')!r} y el estado de {estado.get('codigo')!r}")
    return resp, errores


def _errores_tareas(entrada: dict, resp: dict, tarifa: dict) -> list[str]:
    """P6d (trazabilidad), perfiles de la tarifa, fases y P6a (PM >= 8 h)."""
    errores = []
    validos = set(perfiles(tarifa))
    fases = entrada.get("fases") or []
    propuestas = {t.get("id"): t for t in resp.get("tareas_propuestas") or [] if isinstance(t, dict)}
    vistos, pm_h = [], Decimal(0)
    for i, t in enumerate(entrada.get("tareas") or []):
        if not isinstance(t, dict):
            continue
        tid, donde = t.get("id"), f"tareas[{i}] ({t.get('id')})"
        if tid in vistos:
            errores.append(f"{donde}: id repetido")
        vistos.append(tid)
        if t.get("perfil") not in validos:
            errores.append(f"{donde}: el perfil «{t.get('perfil')}» no está en rate-card.json")
        if t.get("fase") not in fases:
            errores.append(f"{donde}: la fase «{t.get('fase')}» no está en «fases»")
        if isinstance(tid, str) and tid.startswith("T-"):
            p = propuestas.get(tid)
            if p is None:
                errores.append(f"P6d {donde}: no existe en tareas_propuestas del experto")
            else:
                for k in _CAMPOS_TRAZA:
                    if t.get(k) != p.get(k):
                        errores.append(f"P6d {donde}.{k}: «{t.get(k)}» distinto de tareas_propuestas «{p.get(k)}»")
                try:
                    if _dec(t.get("tecnicas_h")) != _dec(p.get("horas_base")):
                        errores.append(f"P6d {donde}.tecnicas_h: {t.get('tecnicas_h')} distinto de horas_base {p.get('horas_base')}")
                    if _dec(t.get("reuniones_h")) != _dec(p.get("reuniones_h")):
                        errores.append(f"P6d {donde}.reuniones_h: {t.get('reuniones_h')} distinto de la propuesta {p.get('reuniones_h')}")
                except ValueError as e:
                    errores.append(f"P6d {donde}: horas no numéricas ({e})")
        elif isinstance(tid, str) and tid.startswith("PM-"):
            if t.get("perfil") != PERFIL_PM or t.get("fase") != FASE_PM:
                errores.append(f"P6d {donde}: una tarea PM-nn solo puede ser «{PERFIL_PM}» en «{FASE_PM}»")
        if t.get("perfil") == PERFIL_PM:
            try:
                pm_h += horas_tarea(t.get("tecnicas_h"), t.get("reuniones_h"))
            except ValueError:
                pass  # ya lo señala el esquema
    faltan = sorted(set(propuestas) - set(vistos), key=str)
    if faltan:
        errores.append(f"P6d: faltan tareas_propuestas en la estimación: {', '.join(map(str, faltan))}")
    if pm_h < PM_MINIMO_H:
        errores.append(f"P6a: la gestión de proyecto suma {_eur(pm_h)} h y el mínimo es {PM_MINIMO_H} h (LES-G-001). "
                       f"Añadir una tarea PM-nn de «{PERFIL_PM}» en la fase «{FASE_PM}»")
    return errores


def _errores_estructura(entrada: dict, tarifa: dict) -> list[str]:
    """Hitos de la tarifa (P6e), Gantt, orden de perfiles y textos prohibidos."""
    errores = []
    esperados = hitos_tarifa(tarifa)
    hitos = entrada.get("hitos") or []
    if len(hitos) != len(esperados):
        errores.append(f"P6e: {len(hitos)} hitos y la tarifa tiene {len(esperados)}")
    for i, (h, e) in enumerate(zip(hitos, esperados)):
        try:
            mismo_pct = isinstance(h, dict) and _dec(h.get("porcentaje")) == _dec(e["porcentaje"])
        except ValueError:
            mismo_pct = False
        if not isinstance(h, dict) or h.get("nombre") != e["nombre"] or not mismo_pct:
            errores.append(f"P6e hitos[{i}]: debe ser «{e['nombre']}» con {e['porcentaje']} %")
    fases = entrada.get("fases") or []
    sem = entrada.get("duracion_semanas")
    vistas = set()
    for i, g in enumerate(entrada.get("gantt") or []):
        if not isinstance(g, dict):
            continue
        if g.get("fase") not in fases:
            errores.append(f"gantt[{i}]: la fase «{g.get('fase')}» no está en «fases»")
        if g.get("fase") in vistas:
            errores.append(f"gantt[{i}]: fase «{g.get('fase')}» repetida")
        vistas.add(g.get("fase"))
        if isinstance(sem, int) and any(isinstance(s, int) and not 1 <= s <= sem for s in g.get("semanas") or []):
            errores.append(f"gantt[{i}]: semanas fuera de 1..{sem}")
    if "perfiles" in entrada:
        usados = {t.get("perfil") for t in entrada.get("tareas") or [] if isinstance(t, dict)}
        orden = entrada.get("perfiles") or []
        ajenos = [p for p in orden if p not in perfiles(tarifa)]
        if ajenos:
            errores.append(f"perfiles: no están en la tarifa: {', '.join(map(str, ajenos))}")
        if usados - set(orden):
            errores.append(f"perfiles: faltan perfiles usados: {', '.join(sorted(map(str, usados - set(orden))))}")
    for ruta, texto in _textos(entrada):
        if _CONTINGENCIA_RE.search(texto):
            errores.append(f"P6c {ruta}: no puede mencionar contingencia (LES-G-081)")
        if texto.lstrip()[:1] in ("=", "+", "@"):
            errores.append(f"{ruta}: no puede empezar por «{texto.lstrip()[:1]}» (fórmula de Excel)")
    return errores


def leer_ajuste(decision: dict) -> tuple[Decimal, str]:
    """(importe, motivo) de los comentarios de una decisión AJUSTE_COMERCIAL (§10, forma exacta)."""
    m = _AJUSTE_RE.match(unicodedata.normalize("NFC", str(decision.get("comentarios") or "")).strip())
    if not m:
        raise ValueError("comentarios sin la forma «importe_eur=-1500.00; motivo=…» (§10)")
    return Decimal(m.group(1)), m.group(2).strip()


def _errores_ajuste(entrada: dict, estado: dict, ajuste: dict | None) -> list[str]:
    """P6c: ajuste_comercial_eur = 0 salvo decisión AJUSTE_COMERCIAL vigente con el mismo importe y motivo."""
    from nucleo import hashes  # importación diferida: módulo de A
    errores = []
    try:
        importe = _dec(entrada.get("ajuste_comercial_eur", 0))
    except ValueError:
        return ["P6c ajuste_comercial_eur: debe ser un número"]
    motivo = entrada.get("ajuste_comercial_motivo")
    if ajuste is None:
        if importe != 0:
            errores.append(f"P6c: ajuste_comercial_eur = {importe} sin decisión AJUSTE_COMERCIAL del comercial "
                           "(estimar --aplicar-ajuste D-NNN; LES-G-081)")
        if motivo is not None:
            errores.append("P6c: ajuste_comercial_motivo sin ajuste comercial decidido")
        return errores
    if ajuste.get("tipo") != "AJUSTE_COMERCIAL":
        errores.append(f"P6c: la decisión {ajuste.get('id')} es {ajuste.get('tipo')}, no AJUSTE_COMERCIAL")
    vigente = hashes.hash_contenido(estado)
    if ajuste.get("hash_citado") != vigente:
        errores.append(f"P6c: la decisión {ajuste.get('id')} cita {ajuste.get('hash_citado')}, vigente {vigente}")
    try:
        imp_d, mot_d = leer_ajuste(ajuste)
    except ValueError as e:
        return errores + [f"P6c: decisión {ajuste.get('id')}: {e}"]
    if imp_d == 0:
        errores.append("P6c: un ajuste comercial de 0,00 EUR no es un ajuste")
    if importe != imp_d:
        errores.append(f"P6c: ajuste_comercial_eur = {importe} y la decisión dice {imp_d}")
    if not isinstance(motivo, str) or motivo.strip() != mot_d:
        errores.append("P6c: ajuste_comercial_motivo distinto del motivo de la decisión")
    return errores


# REV-1 (I1.4): la entrada vale solo si es EXACTAMENTE la que compone la regla decidida. Fuera de la comparación,
# lo que no sale de la regla: la fecha (es la entrada de la propia recomposición) y el ajuste, que P6c contrasta
# con la decisión AJUSTE_COMERCIAL que cite el hash vigente.
CAMPOS_FUERA_DE_REGLA = ("fecha", "ajuste_comercial_eur", "ajuste_comercial_motivo")


def _canon(x: object) -> str:
    """JSON canónico en NFC: 24 y 24.0, o 1 y true, son distintos (una comparación con == los igualaría)."""
    return json.dumps(_nfc(x), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _primera_diferencia(a: object, b: object) -> str:
    """Dónde difieren dos valores de la entrada: el primer elemento distinto de una lista (con su id) o el valor."""
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            if _canon(x) != _canon(y):
                donde = f"[{i}]" + (f" ({x.get('id') or x.get('fase')})" if isinstance(x, dict) else "")
                if isinstance(x, dict) and isinstance(y, dict):
                    campos = [k for k in sorted(set(x) | set(y)) if _canon(x.get(k)) != _canon(y.get(k))]
                    return f"{donde}: {', '.join(campos)} ({_canon({k: x.get(k) for k in campos})[:160]} y la regla da " \
                           f"{_canon({k: y.get(k) for k in campos})[:160]})"
                return f"{donde}: {_canon(x)[:120]} y la regla da {_canon(y)[:120]}"
        return f"{len(a)} elementos y la regla da {len(b)}"
    return f"{_canon(a)[:160]} y la regla da {_canon(b)[:160]}"


def diferencias_regla(entrada: dict, esperada: dict) -> list[str]:
    """P6f: diferencias entre una entrada y la que compone `componer_entrada` (sin CAMPOS_FUERA_DE_REGLA)."""
    errores = []
    for k in sorted((set(entrada) | set(esperada)) - set(CAMPOS_FUERA_DE_REGLA)):
        if k not in esperada:
            errores.append(f"P6f {k}: la regla de estimación no lleva este campo")
        elif k not in entrada:
            errores.append(f"P6f {k}: falta; lo compone la regla de estimación")
        elif _canon(entrada[k]) != _canon(esperada[k]):
            errores.append(f"P6f {k}: no es lo que compone la regla de estimación del 10-10-2026: "
                           f"{_primera_diferencia(entrada[k], esperada[k])}")
    return errores


def errores_regla(entrada: dict, estado: dict, tarifa: dict) -> list[str]:
    """P6f (REV-1): recompone la entrada con `componer_entrada` (con la fecha de la entrada) y la compara entera.

    PM = máx(8 h, ⌈15 %⌉), tareas, fases, Gantt por perfiles, duración, hitos, asunciones y exclusiones salen de la
    regla; cualquier diferencia mueve dinero o texto del cliente sin que nadie lo haya decidido (LES-G-097.3).
    """
    try:
        hoy = date.fromisoformat(str(entrada.get("fecha")))
    except ValueError:
        return [f"P6f fecha: {entrada.get('fecha')!r} no es una fecha ISO; no se puede recomponer la regla"]
    try:
        esperada, _ = componer_entrada(estado, hitos_tarifa(tarifa), hoy)
    except (ValueError, KeyError, TypeError) as e:
        return [f"P6f: no se puede recomponer la entrada con la regla de estimación: {e}"]
    return diferencias_regla(entrada, esperada)


def validar_entrada(entrada: dict, estado: dict, tarifa: dict, ajuste: dict | None) -> list[str]:
    """Todas las reglas de la entrada de estimación (§13, P6a-P6f, P9); [] si es válida.

    `ajuste` es la decisión AJUSTE_COMERCIAL (dict del esquema decision) o None. P6f exige que la entrada sea la
    que compone la regla decidida (`errores_regla`): ni el coordinador ni nadie la escribe a mano.
    """
    from nucleo import esquema, textos_cliente  # importaciones diferidas: módulos de A y C
    if not isinstance(entrada, dict):
        return ["$: la entrada de estimación debe ser un objeto JSON"]
    errores = [f"esquema {e}" for e in esquema.validar(entrada, esquema.cargar("estimacion_entrada"))]
    resp, err_ctx = _contexto(estado)
    errores += err_ctx
    alta = (estado.get("carga") or {}).get("alta") or {}
    if entrada.get("codigo") != estado.get("codigo"):
        errores.append(f"codigo: {entrada.get('codigo')!r} distinto del estado {estado.get('codigo')!r}")
    for k in ("cliente", "titulo"):
        if entrada.get(k) != alta.get(k):
            errores.append(f"{k}: «{entrada.get(k)}» distinto del alta «{alta.get(k)}»")
    errores += _errores_tareas(entrada, resp, tarifa)
    errores += _errores_estructura(entrada, tarifa)
    errores += _errores_ajuste(entrada, estado, ajuste)
    errores += errores_regla(entrada, estado, tarifa)
    for ruta, texto in _textos(entrada):
        for m in textos_cliente.marcadores(texto):
            errores.append(f"P9 {ruta}: marcador prohibido «{m}» (LES-G-006)")
    return errores


# ── Cálculo (réplica en Decimal de generar_estimacion.calcular) ──────────────

def _hitos(hitos: list[dict], precio: Decimal) -> list[dict]:
    """ROUND(% × precio; 2) por hito y el último absorbe el resto (fórmulas del XLSX canónico)."""
    salida, acum = [], Decimal(0)
    for i, h in enumerate(hitos):
        if i < len(hitos) - 1 or i == 0 and len(hitos) == 1:
            imp = (_dec(h["porcentaje"]) / 100 * precio).quantize(_CENT, rounding=ROUND_HALF_UP)
        else:
            imp = precio - acum
        acum += imp
        salida.append({"nombre": h["nombre"], "porcentaje": h["porcentaje"], "importe_eur": _eur(imp)})
    return salida


def calcular(entrada: dict, tarifa: dict) -> dict:
    """Bloque «resumen» del esquema estado (importes y horas en cadena con dos decimales)."""
    tarifas = _tarifas(tarifa)
    filas = [(t, horas_tarea(t["tecnicas_h"], t["reuniones_h"])) for t in entrada["tareas"]]
    usados = [p for p in perfiles(tarifa) if any(t["perfil"] == p for t, _ in filas)]
    orden = entrada.get("perfiles") or usados  # mismo orden que el generador
    por_perfil = [(p, sum((d for t, d in filas if t["perfil"] == p), Decimal(0))) for p in orden]
    total = sum((d for _, d in filas), Decimal(0))
    subtotal = sum((h * tarifas[p] for p, h in por_perfil), Decimal(0))
    ajuste = _dec(entrada.get("ajuste_comercial_eur", 0))
    precio = subtotal + ajuste
    pm = dict(por_perfil).get(PERFIL_PM, Decimal(0))
    tarifa_num = {p["nombre"]: p["tarifa_hora"] for p in tarifa["perfiles"]}
    return {
        "horas_total": _eur(total),
        "por_perfil": [{"perfil": p, "horas": _eur(h), "tarifa_hora": tarifa_num[p], "importe_eur": _eur(h * tarifas[p])}
                       for p, h in por_perfil],
        "por_fase": [{"fase": f, "horas": _eur(sum((d for t, d in filas if t["fase"] == f), Decimal(0)))}
                     for f in entrada["fases"]],
        "pm_h": _eur(pm),
        "pm_pct": _eur(pm / total * 100 if total else Decimal(0)),
        "subtotal_eur": _eur(subtotal),
        "ajuste_eur": _eur(ajuste),
        "precio_cerrado_eur": _eur(precio),
        "hitos": _hitos(entrada["hitos"], precio),
        "duracion_semanas": entrada["duracion_semanas"],
    }


# ── Ejecución del generador canónico (sin modificarlo) ──────────────────────

def _ejecutar(cmd: list[str], cwd: pathlib.Path) -> tuple[int, str]:
    """Ejecuta y devuelve (rc, salida literal con stdout y stderr)."""
    entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT_S, env=entorno, cwd=str(cwd))
    except subprocess.TimeoutExpired as e:
        return 124, f"tiempo agotado ({TIMEOUT_S} s): {e}"
    texto = r.stdout.rstrip()
    if r.stderr.strip():
        texto += ("\n" if texto else "") + "[stderr] " + r.stderr.rstrip()
    return r.returncode, texto


def _preparar_arbol(rutas: RutasGenerador, tarifa: dict) -> tuple[pathlib.Path, pathlib.Path]:
    """Crea <base_tmp>/estimacion-XXXX/{_templates/estimacion, _config}; devuelve (raíz, generador)."""
    for ruta, esperado, nombre in ((rutas.generador, rutas.sha256_generador, GENERADOR),
                                   (rutas.plantilla, rutas.sha256_plantilla, PLANTILLA)):
        if not pathlib.Path(ruta).is_file():
            raise EntradaInvalida(f"No existe {nombre}: {ruta}", [str(ruta)])
        if esperado is not None and _sha256(ruta) != esperado:
            raise IntegridadRota(f"{nombre} no coincide con el manifiesto",
                                 [f"{nombre}: SHA-256 {_sha256(ruta)} distinto de {esperado}"])
    base = pathlib.Path(rutas.base_tmp)
    base.mkdir(parents=True, exist_ok=True)
    raiz = pathlib.Path(tempfile.mkdtemp(prefix="estimacion-", dir=base))
    dir_est, dir_cfg = raiz / "_templates" / "estimacion", raiz / "_config"
    dir_est.mkdir(parents=True)
    dir_cfg.mkdir()
    gen = dir_est / GENERADOR
    shutil.copyfile(rutas.generador, gen)
    shutil.copyfile(rutas.plantilla, dir_est / PLANTILLA)
    for origen, copia in ((rutas.generador, gen), (rutas.plantilla, dir_est / PLANTILLA)):
        if _sha256(origen) != _sha256(copia):
            raise IntegridadRota(f"La copia de {copia.name} no coincide con el original", [str(copia)])
    (dir_cfg / "rate-card.json").write_text(json.dumps(tarifa_para_generador(tarifa), ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    return raiz, gen


def _generar(entrada: dict, rutas: RutasGenerador, salida: pathlib.Path,
             tarifa: dict | None = None) -> tuple[str, str]:
    """Genera y verifica el XLSX; lo deja en `salida` con 0644. Devuelve (SHA-256, salida literal)."""
    tarifa = tarifa if tarifa is not None else cargar_tarifa(rutas.rate_card)
    salida = pathlib.Path(salida)
    if salida.suffix.lower() != ".xlsx":
        raise EntradaInvalida(f"La salida debe ser .xlsx: {salida}", [str(salida)])
    raiz, gen = _preparar_arbol(rutas, tarifa)
    try:
        datos = raiz / "estimacion_entrada.json"
        datos.write_text(json.dumps(entrada, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp = raiz / salida.name
        rc, txt = _ejecutar([sys.executable, str(gen), str(datos), str(tmp)], raiz)
        literal = f"$ {GENERADOR} {datos.name} {tmp.name} -> rc={rc}\n{txt}"
        if rc != 0 or not tmp.is_file():
            raise ReglaIncumplida(f"El generador canónico devolvió rc={rc}", [literal])
        rc_v, txt_v = _ejecutar([sys.executable, str(gen), "--verificar", str(tmp)], raiz)
        literal += f"\n$ {GENERADOR} --verificar {tmp.name} -> rc={rc_v}\n{txt_v}"
        if rc_v != 0:
            raise ReglaIncumplida(f"--verificar devolvió rc={rc_v}", [literal])
        salida.parent.mkdir(parents=True, exist_ok=True)
        provisional = salida.with_name(salida.name + ".tmp")
        shutil.copyfile(tmp, provisional)
        os.chmod(provisional, 0o644)  # un fichero 0600 da HTTP 500 al descargarlo (I0)
        os.replace(provisional, salida)
        return _sha256(salida), literal
    finally:
        shutil.rmtree(raiz, ignore_errors=True)  # solo el directorio que ha creado mkdtemp


def generar_xlsx(entrada: dict, rutas: RutasGenerador, salida: pathlib.Path) -> str:
    """Ejecuta el generador canónico sin tocarlo, exige --verificar rc 0 y devuelve el SHA-256."""
    return _generar(entrada, rutas, salida)[0]


# ── Lectura del XLSX generado y del resumen impreso por el generador ────────

def _celda_num(ws, fila: int, col: int, donde: str) -> Decimal:
    v = ws.cell(fila, col).value
    try:
        return _dec(v)
    except ValueError:
        raise IntegridadRota(f"XLSX: {donde} no es un número literal", [f"{ws.title}!R{fila}C{col} = {v!r}"])


def leer_xlsx(ruta: pathlib.Path) -> dict:
    """Recalcula precio, hitos y horas desde las celdas literales del XLSX canónico (openpyxl).

    El XLSX solo guarda fórmulas sin valor en caché, así que se leen los literales (E, G, tarifas,
    ajuste y % de hito), se comprueba que las fórmulas son las canónicas y se evalúan en Decimal.
    """
    import openpyxl  # presente en el sandbox (I0 b) y en el .venv
    wb = openpyxl.load_workbook(ruta)
    ws = wb[HOJA_EST]
    tareas, r = [], 2
    while ws.cell(r, 1).value not in (None, "TOTALES"):
        if ws.cell(r, 4).value != f"=E{r}+F{r}+G{r}" or ws.cell(r, 6).value != f"=ROUND(E{r}*0.2,0)":
            raise IntegridadRota("XLSX: fórmula de tarea no canónica", [f"fila {r}: D={ws.cell(r, 4).value!r} F={ws.cell(r, 6).value!r}"])
        e, g = _celda_num(ws, r, 5, "E"), _celda_num(ws, r, 7, "G")
        tareas.append((ws.cell(r, 3).value, horas_tarea(e, g)))
        r += 1
    rs = wb[HOJA_RES]
    por_perfil, r = [], 7
    while rs.cell(r, 1).value not in (None, "SUBTOTAL SERVICIOS"):
        perfil = rs.cell(r, 1).value
        horas = sum((d for p, d in tareas if p == perfil), Decimal(0))
        por_perfil.append((perfil, horas, _celda_num(rs, r, 3, "tarifa")))
        r += 1
    if rs.cell(r, 1).value != "SUBTOTAL SERVICIOS":
        raise IntegridadRota("XLSX: no se encuentra SUBTOTAL SERVICIOS", [f"fila {r}"])
    sub = r
    subtotal = sum((h * t for _, h, t in por_perfil), Decimal(0))
    ajuste, r = Decimal(0), sub + 1
    if str(rs.cell(r, 1).value or "").startswith("AJUSTE COMERCIAL"):
        ajuste, r = _celda_num(rs, r, 6, "ajuste comercial"), r + 1
    if rs.cell(r, 1).value != "PRECIO CERRADO (IVA no incluido)":
        raise IntegridadRota("XLSX: no se encuentra PRECIO CERRADO", [f"fila {r}: {rs.cell(r, 1).value!r}"])
    formula = f"=F{sub}" if ajuste == 0 else f"=F{sub}+F{sub + 1}"
    if rs.cell(r, 6).value != formula:
        raise IntegridadRota("XLSX: fórmula de precio no canónica", [f"{rs.cell(r, 6).value!r} en vez de {formula!r}"])
    while r <= rs.max_row and not (rs.cell(r, 1).value == "Hito" and rs.cell(r, 2).value == "%"):
        r += 1
    hitos, r = [], r + 1
    while r <= rs.max_row and rs.cell(r, 1).value not in (None, "TOTAL HITOS"):
        hitos.append({"nombre": rs.cell(r, 1).value, "porcentaje": _celda_num(rs, r, 2, "% de hito") * 100})
        r += 1
    if not hitos:
        raise IntegridadRota("XLSX: no se encuentran los hitos", [str(ruta)])
    precio = subtotal + ajuste
    total = sum((d for _, d in tareas), Decimal(0))
    pm = sum((d for p, d in tareas if p == PERFIL_PM), Decimal(0))
    return {"horas_total": _eur(total), "pm_h": _eur(pm), "subtotal_eur": _eur(subtotal), "ajuste_eur": _eur(ajuste),
            "precio_cerrado_eur": _eur(precio),
            "hitos": [{"nombre": h["nombre"], "importe_eur": h["importe_eur"]} for h in _hitos(hitos, precio)],
            "por_perfil": [{"perfil": p, "horas": _eur(h), "tarifa_hora": _eur(t)} for p, h, t in por_perfil]}


def _importe_es(texto: str) -> Decimal:
    """«17.852,50» -> Decimal("17852.50") (formato de generar_estimacion.eur)."""
    return Decimal(texto.replace(".", "").replace(",", "."))


def leer_salida_generador(texto: str) -> dict:
    """Precio cerrado e hitos del resumen que imprime el generador (cálculo propio en coma flotante)."""
    m = re.search(r"^PRECIO CERRADO \(IVA no incluido\): (-?[0-9.]+,[0-9]{2}) €$", texto, re.M)
    if not m:
        raise IntegridadRota("La salida del generador no trae la línea PRECIO CERRADO", [texto[-500:]])
    hitos, en_hitos = [], False
    for linea in texto.splitlines():
        if linea == "Hitos:":
            en_hitos = True
            continue
        mh = re.match(r"^  - (.+): [0-9.,]+ % = (-?[0-9.]+,[0-9]{2}) €$", linea) if en_hitos else None
        if mh:
            hitos.append({"nombre": mh.group(1), "importe_eur": _eur(_importe_es(mh.group(2)))})
        elif en_hitos and linea.strip():
            en_hitos = False
    return {"precio_cerrado_eur": _eur(_importe_es(m.group(1))), "hitos": hitos}


def comparar(resumen: dict, leido: dict, origen: str, tolerancia: Decimal = Decimal(0)) -> list[str]:
    """Diferencias entre el resumen calculado y lo leído (mismas claves que trae `leido`).

    `tolerancia` (EUR) solo se usa contra el resumen IMPRESO por el generador, que calcula en coma
    flotante y formatea con redondeo al par: puede diferir en un céntimo de la réplica en Decimal en
    los casos límite. Contra el XLSX releído la comparación es exacta.
    """
    def distinto(a: str, b: str) -> bool:
        return abs(Decimal(a) - Decimal(b)) > tolerancia

    dif = []
    for k in ("horas_total", "pm_h", "subtotal_eur", "ajuste_eur", "precio_cerrado_eur"):
        if k in leido and distinto(leido[k], resumen[k]):
            dif.append(f"{origen}.{k}: {leido[k]} y el cálculo da {resumen[k]}")
    esperado = [{"nombre": h["nombre"], "importe_eur": h["importe_eur"]} for h in resumen["hitos"]]
    obtenido = leido.get("hitos") or []
    if len(obtenido) != len(esperado) or any(
            o.get("nombre") != e["nombre"] or "importe_eur" not in o or distinto(o["importe_eur"], e["importe_eur"])
            for o, e in zip(obtenido, esperado)):
        dif.append(f"{origen}.hitos: {obtenido} y el cálculo da {esperado}")
    if "por_perfil" in leido:
        esp = [{"perfil": p["perfil"], "horas": p["horas"], "tarifa_hora": _eur(_dec(p["tarifa_hora"]))}
               for p in resumen["por_perfil"]]
        if leido["por_perfil"] != esp:
            dif.append(f"{origen}.por_perfil: {leido['por_perfil']} y el cálculo da {esp}")
    return dif


# ── Orquestación de `estimar` ───────────────────────────────────────────────

def _buscar_decision(estado: dict, decision_id: str) -> dict | None:
    for d in estado.get("decisiones") or []:
        if isinstance(d, dict) and d.get("id") == decision_id:
            return d
    return None


def requiere_stop(estado: dict) -> bool:
    """P7: precio de carga.estimacion > 100.000 EUR sin CONFIRMA_STOP que cite el hash vigente.

    La CLI lo llama DESPUÉS de componer textos_cliente (el hash final), y `paquete` antes de escribir.
    """
    from nucleo import decision  # importación diferida: módulo de A
    est = (estado.get("carga") or {}).get("estimacion")
    if not isinstance(est, dict):
        return False
    if Decimal(est["resumen"]["precio_cerrado_eur"]) <= UMBRAL_STOP_EUR:
        return False
    return decision.vigente(estado, "CONFIRMA_STOP") is None


def estimar(estado: dict, entrada: dict, tarifa: dict, rutas: RutasGenerador, dir_salida: pathlib.Path,
            ajuste_decision_id: str | None) -> ResultadoEstimacion:
    """Valida, calcula, genera el XLSX canónico, lo contrasta y guarda carga.estimacion.

    ReglaIncumplida con TODOS los errores si la entrada no vale (no muta nada). IntegridadRota si el
    XLSX o la salida del generador no cuadran con la réplica en Decimal (no muta nada). Si es válida:
    carga.estimacion = {entrada, resumen, ajuste}, carga.textos_cliente = None (la CLI lo vuelve a
    componer) y artefactos.xlsx_estimacion. La transición de estado la hace la CLI.
    """
    from nucleo import hashes  # importación diferida: módulo de A
    entrada = _nfc(copy.deepcopy(entrada))
    ajuste, errores = None, []
    if ajuste_decision_id is not None:
        ajuste = _buscar_decision(estado, ajuste_decision_id)
        if ajuste is None:
            errores.append(f"P6c: no existe la decisión {ajuste_decision_id}")
            ajuste = {"id": ajuste_decision_id, "tipo": None}
    errores += validar_entrada(entrada, estado, tarifa, ajuste)
    if errores:
        raise ReglaIncumplida(f"Estimación rechazada: {len(errores)} errores", errores)
    resumen = calcular(entrada, tarifa)
    hash_base = hashes.hash_contenido(estado)
    dir_salida = pathlib.Path(dir_salida)
    ruta = dir_salida / f"{entrada['codigo']}-Estimacion.xlsx"
    provisional = dir_salida / f".{entrada['codigo']}-Estimacion.nuevo.xlsx"
    try:
        sha, literal = _generar(entrada, rutas, provisional, tarifa)
        dif = comparar(resumen, leer_salida_generador(literal), "generador", TOLERANCIA_GENERADOR)
        dif += comparar(resumen, leer_xlsx(provisional), "xlsx")
        if dif:
            raise IntegridadRota("El XLSX canónico no cuadra con la réplica en Decimal", dif)
        os.replace(provisional, ruta)
    finally:
        if provisional.exists():
            provisional.unlink()
    aj = None
    if ajuste is not None:
        imp, mot = leer_ajuste(ajuste)
        aj = {"decision_id": ajuste["id"], "importe_eur": _eur(imp), "motivo": mot, "hash_base": hash_base}
    carga = estado["carga"]
    carga["estimacion"] = {"entrada": entrada, "resumen": resumen, "ajuste": aj}
    carga["textos_cliente"] = None
    estado.setdefault("artefactos", {})["xlsx_estimacion"] = {"nombre": ruta.name, "sha256": sha,
                                                               "bytes": ruta.stat().st_size}
    return ResultadoEstimacion(resumen=resumen, stop=requiere_stop(estado), ruta_xlsx=ruta,
                               xlsx_sha256=sha, salida_generador=literal)
