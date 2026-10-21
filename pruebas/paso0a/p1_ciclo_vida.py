"""P1 · Ciclo de vida de los modelos desplegados (LES-G-036) y residencia de datos por SKU.

Fuente: la API de ARM del propio recurso (lo mismo que `az cognitiveservices account list-models` y
`az cognitiveservices account deployment list`, pero con el tenant fijado en el token, LES-G-052):
  GET {cuenta}/deployments?api-version=<arm_cuenta_proyecto>   → modelo, versión y SKU REAL de cada despliegue
  GET {cuenta}/models?api-version=<arm_cuenta_proyecto>        → `deprecation.inference` y `skus[].deprecationDate`

Regla (LES-G-036): la retirada debe ser POSTERIOR al fin del proyecto más 12 meses.
SUPUESTO declarado: fin del proyecto = hoy + 6 meses (umbral = hoy + 18 meses). Sin fecha, falla.
Se toma la fecha más temprana entre la del modelo y la del SKU del despliegue (la más prudente).
DataZoneStandard se marca como apto para datos reales (el proceso queda en la zona de datos); GlobalStandard no.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from pruebas.paso0a import comun

ID = "P1"
TITULO = "Ciclo de vida de modelos y SKU de cada despliegue"
OBJETIVO = ("gpt-5.6-luna", "gpt-6-luna", "gpt-5.6-terra", "Decision-1", "text-embedding-3-large")
INFORMATIVOS = ("gpt-5.6-sol",)
MESES_PROYECTO = 6
MESES_EXPLOTACION = 12
SKU_DATOS_REALES = {"DataZoneStandard", "DataZoneProvisionedManaged", "DataZoneBatch"}
MAX_PAGINAS = 20
TIMEOUT_ARM_S = 15.0
SIN_PRESUPUESTO = "presupuesto agotado"


def sumar_meses(fecha: dt.date, meses: int) -> dt.date:
    """Suma meses de calendario; si el día no existe en el mes destino, usa el último día de ese mes."""
    indice = fecha.month - 1 + meses
    anio, mes = fecha.year + indice // 12, indice % 12 + 1
    siguiente = dt.date(anio + (mes == 12), mes % 12 + 1, 1)
    ultimo = (siguiente - dt.timedelta(days=1)).day
    return dt.date(anio, mes, min(fecha.day, ultimo))


def umbral_retirada(hoy: dt.date, meses_proyecto: int = MESES_PROYECTO,
                    meses_explotacion: int = MESES_EXPLOTACION) -> tuple[dt.date, dt.date]:
    """(fin_de_proyecto, umbral): la retirada tiene que ser estrictamente posterior al umbral."""
    fin = sumar_meses(hoy, meses_proyecto)
    return fin, sumar_meses(fin, meses_explotacion)


def leer_fecha(valor: Any) -> dt.date | None:
    """Fecha de un campo de la API ('2028-01-11', '2028-01-11T00:00:00Z'...). None si no es fecha."""
    if not isinstance(valor, str) or not valor.strip():
        return None
    texto = valor.strip().replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(texto).date()
    except ValueError:
        try:
            return dt.date.fromisoformat(texto[:10])
        except ValueError:
            return None


def normalizar_modelo(entrada: Any) -> dict:
    """La lista de modelos de la cuenta puede venir plana o envuelta en `model`; devuelve la parte del modelo."""
    if isinstance(entrada, dict) and isinstance(entrada.get("model"), dict) and "name" not in entrada:
        return entrada["model"]
    return entrada if isinstance(entrada, dict) else {}


def fechas_retirada(modelo: dict, sku: str) -> list[tuple[dt.date, str]]:
    """Fechas candidatas con su campo de origen: deprecation.inference y la del SKU del despliegue."""
    fechas: list[tuple[dt.date, str]] = []
    dep = modelo.get("deprecation") if isinstance(modelo.get("deprecation"), dict) else {}
    f = leer_fecha(dep.get("inference"))
    if f:
        fechas.append((f, "deprecation.inference"))
    for s in modelo.get("skus") or []:
        if isinstance(s, dict) and s.get("name") == sku:
            f = leer_fecha(s.get("deprecationDate"))
            if f:
                fechas.append((f, f"skus[{sku}].deprecationDate"))
    return fechas


def buscar_modelo(modelos: list[dict], nombre: str, version: str | None, formato: str | None) -> dict | None:
    """Entrada de la lista de modelos con el mismo nombre (sin distinguir mayúsculas), versión y formato."""
    candidatos = []
    for m in (normalizar_modelo(x) for x in modelos):
        if str(m.get("name", "")).casefold() != nombre.casefold():
            continue
        if version and str(m.get("version", "")) != str(version):
            continue
        if formato and m.get("format") and str(m.get("format")).casefold() != formato.casefold():
            continue
        candidatos.append(m)
    return candidatos[0] if candidatos else None


def evaluar_despliegue(nombre: str, esperado: dict, despliegues: dict[str, dict], modelos: list[dict],
                       umbral: dt.date) -> dict:
    """Veredicto de un despliegue: cumple, fecha, origen, SKU real y aptitud para datos reales."""
    d = despliegues.get(nombre)
    if d is None:
        return {"despliegue": nombre, "cumple": False, "motivo": "el despliegue no existe en el recurso"}
    props = d.get("properties") or {}
    mod = props.get("model") or {}
    sku = (d.get("sku") or {}).get("name") or ""
    res: dict[str, Any] = {"despliegue": nombre, "modelo": mod.get("name"), "version": mod.get("version"),
                           "formato": mod.get("format"), "sku": sku, "apto_datos_reales": sku in SKU_DATOS_REALES}
    problemas = []
    if esperado.get("sku") and esperado["sku"] != sku:
        problemas.append(f"SKU real {sku!r} distinto del de config/entorno.local.json ({esperado['sku']!r})")
    if esperado.get("version") and str(esperado["version"]) != str(mod.get("version")):
        problemas.append(f"versión real {mod.get('version')!r} distinta de la de config ({esperado['version']!r})")
    m = buscar_modelo(modelos, str(mod.get("name", "")), mod.get("version"), mod.get("format"))
    if m is None:
        problemas.append("el modelo no aparece en la lista de modelos de la cuenta: sin fecha de retirada")
    else:
        res["lifecycle"] = m.get("lifecycleStatus")
        fechas = fechas_retirada(m, sku)
        if not fechas:
            problemas.append("la API no publica fecha de retirada (sin fecha, falla)")
        else:
            fecha, origen = min(fechas)
            res.update({"retirada": fecha.isoformat(), "origen_fecha": origen})
            if not fecha > umbral:
                problemas.append(f"retirada {fecha.isoformat()} no es posterior al umbral {umbral.isoformat()}")
    res["cumple"] = not problemas
    if problemas:
        res["motivo"] = "; ".join(problemas)
    return res


def _paginar(ctx: comun.Contexto, sufijo: str, api: str) -> tuple[list[dict] | None, str]:
    """Lista ARM completa. Cada página tiene 15 s como máximo y no se pide si no cabe en el presupuesto."""
    if ctx.restante() < TIMEOUT_ARM_S + 1:
        return None, SIN_PRESUPUESTO
    r = ctx.cliente.arm_get(sufijo, api, timeout=TIMEOUT_ARM_S)
    items: list[dict] = []
    for _ in range(MAX_PAGINAS):
        if r.estado != 200 or not isinstance(r.json(), dict):
            return None, r.resumen()
        j = r.json()
        items += [x for x in j.get("value") or [] if isinstance(x, dict)]
        siguiente = j.get("nextLink")
        if not siguiente:
            return items, f"HTTP 200, {len(items)} elementos"
        if ctx.restante() < TIMEOUT_ARM_S + 1:
            return None, SIN_PRESUPUESTO
        r = ctx.cliente.arm_get_siguiente(siguiente, timeout=TIMEOUT_ARM_S)
    return None, f"más de {MAX_PAGINAS} páginas: lista truncada"


def ejecutar(ctx: comun.Contexto) -> dict | comun.EnCurso:
    api = ctx.cfg["api_versions"]["arm_cuenta_proyecto"]
    hoy = ctx.hoy()
    fin, umbral = umbral_retirada(hoy)
    desp, nota_d = _paginar(ctx, "/deployments", api)
    mods, nota_m = _paginar(ctx, "/models", api)
    cabecera = (f"Fuente: ARM {ctx.cliente.base_arm.split('/providers/')[0]}/…/accounts/{ctx.cfg['recurso']} "
                f"(deployments y models, api-version={api}); equivale a «az cognitiveservices account list-models». "
                f"SUPUESTO: fin de proyecto = hoy ({hoy.isoformat()}) + {MESES_PROYECTO} meses = {fin.isoformat()}; "
                f"umbral LES-G-036 = fin + {MESES_EXPLOTACION} meses = {umbral.isoformat()}.")
    if SIN_PRESUPUESTO in (nota_d, nota_m):
        return comun.EnCurso("P1: la lectura de ARM no cabe en el presupuesto; vuelve a ejecutar", 0)
    if desp is None or mods is None:
        ev = f"{cabecera}\nNo se pudo leer la fuente. deployments: {nota_d}. models: {nota_m}."
        estado = "PENDIENTE_FERNANDO" if "HTTP 403" in (nota_d + nota_m) else "FALLA"
        if estado == "PENDIENTE_FERNANDO":
            ev += (" 403: la identidad de Fernando necesita lectura del recurso (Reader o Contributor en "
                   f"{ctx.cliente.base_arm}); no es un rol que pueda asignarse él mismo.")
        return comun.construir_resultado(ID, estado, ev, ctx.comando(ID), ctx.fecha())
    por_nombre = {d.get("name"): d for d in desp}
    lineas, cumple_todo = [cabecera, f"deployments: {nota_d}; models: {nota_m}."], True
    for nombre in OBJETIVO + INFORMATIVOS:
        r = evaluar_despliegue(nombre, ctx.cfg["despliegues"].get(nombre, {}), por_nombre, mods, umbral)
        informativo = nombre in INFORMATIVOS
        if not informativo:
            cumple_todo &= r["cumple"]
        residencia = ("DataZoneStandard: apto para datos reales" if r.get("apto_datos_reales")
                      else f"{r.get('sku') or 'SKU desconocido'}: NO apto para datos reales (proceso global)")
        lineas.append(
            f"- {nombre}{' (informativo)' if informativo else ''}: modelo {r.get('modelo')} v{r.get('version')} · "
            f"retirada {r.get('retirada', 'SIN FECHA')} ({r.get('origen_fecha', '-')}, ciclo {r.get('lifecycle', '-')}) · "
            f"{residencia} · {'CUMPLE' if r['cumple'] else 'NO CUMPLE: ' + r.get('motivo', '')}")
    estado = "PASA" if cumple_todo else "FALLA"
    return comun.construir_resultado(ID, estado, "\n".join(lineas), ctx.comando(ID), ctx.fecha())
