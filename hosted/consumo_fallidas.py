"""PR14-7 (I1.5): consumo de las llamadas A2A fallidas (sin task_id), atribuido por ventana y por conversation.id.

Una llamada al experto que acaba en 429 o en 400 no devuelve task_id, así que su consumo no se lee por tarea
(LES-G-089.5). Pero el agente destino sí deja en las trazas su span `invoke_agent`, con `gen_ai.agent.name`,
`gen_ai.response.id`, `gen_ai.conversation.id` y, si falló, `error.type` (p. ej. rate_limit_exceeded,
pruebas/I14/REAL/diag/claves_429.json). Este script lee el `a2a.jsonl` de la sesión (descargado con
descargar_sesion.py) y, por cada SendMessage fallido sin task_id, busca los `invoke_agent` del agente destino que
empiezan dentro de su ventana [inicio - margen, inicio + latencia + margen] y que no son tareas conocidas de la sesión:
- uno solo → se atribuye, y su consumo es el de los spans `chat` de su conversation.id (o de su operation_Id). Si no
  hay ninguno con uso de tokens (lo observado el 11-10-2026 en los 429 y 400: la traza de una ejecución abortada solo
  trae `invoke_agent` con `error.type` y los `execute_tool`), el consumo queda NO_MEDIBLE, nunca 0 € (LES-G-099);
- ninguno → SIN_SPAN (la llamada no llegó a ejecutar el agente o la traza no está); ninguno se inventa;
- varios → AMBIGUA (otra llamada al mismo agente a la vez: A y B no se lanzan juntos, EA-8); no se suma nada.
El coste usa la tabla de precios de pruebas/I13/E2E-B/kql_coste.kql (la misma de las métricas). rc 1 si un span no
tiene precio, falla una consulta o se alcanza el tope de filas; rc 3 si alguna llamada queda sin atribuir o sin
consumo medible; rc 0 solo si todas quedan medidas. Solo lee trazas: no escribe en Azure.

  .venv/Scripts/python.exe hosted/consumo_fallidas.py --a2a <a2a.jsonl> --salida <informe.json>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
KQL_COSTE = RAIZ / "pruebas" / "I13" / "E2E-B" / "kql_coste.kql"
MARGEN = dt.timedelta(seconds=10)
TOPE = 5000
_RESP, _CONV, _OP = re.compile(r"resp_[A-Za-z0-9]{10,100}"), re.compile(r"conv_[A-Za-z0-9]{10,100}"), re.compile(r"[0-9a-f]{32}")
_AGENTE = re.compile(r"[a-z0-9-]{3,63}")


def _t(valor: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"hora sin zona: {valor!r}")
    return t.astimezone(dt.timezone.utc)


def _k(t: dt.datetime) -> str:
    return f"datetime({t.strftime('%Y-%m-%dT%H:%M:%S.%fZ')})"


def precios(texto: str) -> tuple[dict, int]:
    """(precios por (modelo_base, tramo) → (entrada, caché leída, caché escrita, salida) en EUR/millón, umbral)."""
    filas = re.findall(r'"(gpt-[\w.-]+)",\s*"(corto|largo)",\s*([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)', texto)
    umbral = re.search(r"let umbral_largo = (\d+);", texto)
    if not filas or not umbral:
        raise ValueError("no encuentro la tabla de precios ni el umbral en kql_coste.kql")
    return {(m, t): tuple(float(x) for x in v) for m, t, *v in filas}, int(umbral.group(1))


def fallidas(llamadas: list[dict]) -> list[dict]:
    """Cada SendMessage fallido sin task_id, con su ventana. Las relecturas (GetTask) no consumen modelo."""
    salida = []
    for i, ll in enumerate(llamadas):
        if ll.get("metodo") != "SendMessage" or ll.get("task_id") or not ll.get("error"):
            continue
        if not _AGENTE.fullmatch(str(ll.get("agente") or "")):
            raise ValueError(f"línea {i + 1}: agente no válido {ll.get('agente')!r}")
        ini = _t(ll["inicio"])
        fin = ini + dt.timedelta(seconds=float(ll.get("latencia_s") or 0))
        salida.append({"linea": i + 1, "fase": ll.get("fase"), "agente": ll["agente"], "inicio": ll["inicio"],
                       "latencia_s": ll.get("latencia_s"), "motivo": str(ll["error"])[:300],
                       "desde": ini - MARGEN, "hasta": fin + MARGEN})
    return salida


def consulta_invocaciones(ventanas: list[dict]) -> str:
    agentes = sorted({v["agente"] for v in ventanas})
    desde, hasta = min(v["desde"] for v in ventanas), max(v["hasta"] for v in ventanas)
    return ("dependencies "
            f"| where timestamp between ({_k(desde)} .. {_k(hasta)}) | where name startswith 'invoke_agent' "
            "| extend agente = tostring(customDimensions['gen_ai.agent.name']) "
            f"| where agente in ({', '.join(chr(34) + a + chr(34) for a in agentes)}) "
            "| project timestamp, agente, respuesta = tostring(customDimensions['gen_ai.response.id']), "
            "conversacion = tostring(customDimensions['gen_ai.conversation.id']), op = operation_Id, "
            f"err = tostring(customDimensions['error.type']) | order by timestamp asc | take {TOPE}")


def consulta_consumo(atribuidas: list[dict], hasta: dt.datetime, desde: dt.datetime) -> str:
    convs = [a["conversacion"] for a in atribuidas if _CONV.fullmatch(a["conversacion"] or "")]
    ops = [a["op"] for a in atribuidas if _OP.fullmatch(a["op"] or "")]
    lista = lambda xs: ", ".join(f'"{x}"' for x in xs) or '""'  # noqa: E731
    return ("union requests, dependencies "
            f"| where timestamp between ({_k(desde)} .. {_k(hasta + dt.timedelta(minutes=30))}) "
            "| extend conversacion = tostring(customDimensions['gen_ai.conversation.id']) "
            f"| where conversacion in ({lista(convs)}) or operation_Id in ({lista(ops)}) "
            "| extend fase = coalesce(tostring(customDimensions['gen_ai.operation.name']), tostring(split(name, ' ')[0])) "
            "| where fase in ('chat', 'execute_tool') "
            "| project timestamp, fase, conversacion, op = operation_Id, "
            "entrada = tolong(customDimensions['gen_ai.usage.input_tokens']), "
            "salida = tolong(customDimensions['gen_ai.usage.output_tokens']), "
            "cache_leida = tolong(customDimensions['gen_ai.usage.cache_read.input_tokens']), "
            "cache_escrita = tolong(customDimensions['gen_ai.usage.cache_creation.input_tokens']), "
            "modelo = coalesce(tostring(customDimensions['gen_ai.response.model']), "
            f"tostring(customDimensions['gen_ai.request.model'])) | take {TOPE}")


def coste_span(f: dict, tabla: dict, umbral: int) -> float | None:
    ent, sal = int(f.get("entrada") or 0), int(f.get("salida") or 0)
    cl, ce = int(f.get("cache_leida") or 0), int(f.get("cache_escrita") or 0)
    p = tabla.get((str(f.get("modelo") or "").split("-20")[0], "largo" if ent > umbral else "corto"))
    if p is None:
        return None
    return (max(ent - cl - ce, 0) * p[0] + cl * p[1] + ce * p[2] + sal * p[3]) / 1e6


def atribuir(ventanas: list[dict], invocaciones: list[dict], conocidas: set[str]) -> list[dict]:
    """Para cada llamada fallida, el invoke_agent de su agente que empieza en su ventana (sin las tareas conocidas)."""
    for v in ventanas:
        cand = [x for x in invocaciones if x.get("agente") == v["agente"] and x.get("respuesta") not in conocidas
                and v["desde"] <= _t(x["timestamp"]) <= v["hasta"]]
        con_error = [x for x in cand if x.get("err")]
        elegidas = con_error or cand
        v["candidatas"] = [x.get("respuesta") for x in cand]
        if len(elegidas) == 1:
            x = elegidas[0]
            v.update(atribucion="ATRIBUIDA", respuesta=x.get("respuesta"), conversacion=x.get("conversacion"),
                     op=x.get("op"), error_traza=x.get("err") or None)
        else:
            v.update(atribucion="SIN_SPAN" if not elegidas else "AMBIGUA", respuesta=None, conversacion=None, op=None,
                     error_traza=None)
    # Revisión (I1.5): dos llamadas atribuidas a la misma conversación u operación sumarían dos veces los mismos spans:
    # ninguna se atribuye (AMBIGUA), mejor que un consumo duplicado.
    hechas = [v for v in ventanas if v["atribucion"] == "ATRIBUIDA"]
    for v in hechas:
        if any(w is not v and ((v["conversacion"] and w["conversacion"] == v["conversacion"]) or w["op"] == v["op"])
               for w in hechas):
            v["compartida"] = True
    for v in hechas:
        if v.pop("compartida", False):
            v.update(atribucion="AMBIGUA", motivo_ambigua="conversación u operación compartida con otra llamada fallida",
                     respuesta=None, conversacion=None, op=None)
    return ventanas


def main(argv: list[str] | None = None, consultar=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a2a", type=pathlib.Path, required=True, help="a2a.jsonl descargado de la sesión")
    ap.add_argument("--salida", type=pathlib.Path, required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if consultar is None:
        sys.path.insert(0, str(RAIZ))
        from lib import appi  # noqa: PLC0415 - KQL por ARM con el tenant fijo (lib/azure_auth.py)
        consultar = lambda kql: appi.filas(appi.consultar(kql, "P30D"))  # noqa: E731
    llamadas = [json.loads(x) for x in a.a2a.read_text(encoding="utf-8").splitlines() if x.strip()]
    conocidas = {ll["task_id"] for ll in llamadas if ll.get("task_id")}
    ventanas = fallidas(llamadas)
    tabla, umbral = precios(KQL_COSTE.read_text(encoding="utf-8"))
    informe: dict = {"a2a": str(a.a2a), "llamadas": len(llamadas), "fallidas_sin_task_id": len(ventanas),
                     "margen_s": MARGEN.total_seconds(), "fallidas": []}
    rc = 0
    if ventanas:
        try:
            inv = consultar(consulta_invocaciones(ventanas))
            if len(inv) >= TOPE:
                raise RuntimeError(f"tope de {TOPE} filas alcanzado en invoke_agent: resultado incompleto")
            atribuir(ventanas, inv, conocidas)
            hechas = [v for v in ventanas if v["atribucion"] == "ATRIBUIDA"]
            spans = consultar(consulta_consumo(hechas, max(v["hasta"] for v in ventanas),
                                               min(v["desde"] for v in ventanas))) if hechas else []
            if len(spans) >= TOPE:
                raise RuntimeError(f"tope de {TOPE} filas alcanzado en los spans chat: resultado incompleto")
        except Exception as e:  # noqa: BLE001 - fail loudly con el motivo
            informe["error"] = f"{type(e).__name__}: {str(e)[:500]}"
            spans, rc = [], 1
            for v in ventanas:
                v.setdefault("atribucion", "NO_MEDIDA")
        def casa(v: dict, f: dict) -> bool:
            return v.get("atribucion") == "ATRIBUIDA" and (
                (bool(v.get("conversacion")) and f.get("conversacion") == v["conversacion"]) or f.get("op") == v.get("op"))
        # Revisión (2.ª pasada): un span que casa con dos llamadas (conversación de una, operación de otra) no se suma a
        # ninguna: esas llamadas quedan AMBIGUA, mejor que un consumo contado dos veces.
        for f in spans:
            cruzadas = [v for v in ventanas if casa(v, f)]
            if len(cruzadas) > 1:
                for v in cruzadas:
                    v.update(atribucion="AMBIGUA", motivo_ambigua="un span casa con varias llamadas fallidas")
        for v in ventanas:
            suyos = [f for f in spans if casa(v, f)]
            mios = [f for f in suyos if f.get("fase") == "chat" and (f.get("entrada") is not None or f.get("salida") is not None)]
            costes = [coste_span(f, tabla, umbral) for f in mios]
            sin_precio = sum(c is None for c in costes)
            rc = rc or (1 if sin_precio else 0)
            medido = v.get("atribucion") == "ATRIBUIDA" and bool(mios) and not sin_precio
            informe["fallidas"].append({k: (x.isoformat() if isinstance(x, dt.datetime) else x) for k, x in v.items()}
                                       | {"consumo": "MEDIDO" if medido else "NO_MEDIBLE",
                                          "llamadas_herramienta": sum(f.get("fase") == "execute_tool" for f in suyos),
                                          "spans_chat": len(mios), "sin_precio": sin_precio,
                                          "tokens_entrada": sum(int(f.get("entrada") or 0) for f in mios),
                                          "tokens_cache_leida": sum(int(f.get("cache_leida") or 0) for f in mios),
                                          "tokens_salida": sum(int(f.get("salida") or 0) for f in mios),
                                          "coste_eur": round(sum(c for c in costes if c is not None), 4) if medido else None})
    informe["coste_medido_eur"] = round(sum(f["coste_eur"] or 0 for f in informe["fallidas"]), 4)
    informe["no_atribuidas"] = sum(f["atribucion"] != "ATRIBUIDA" for f in informe["fallidas"])
    informe["no_medibles"] = sum(f["consumo"] != "MEDIDO" for f in informe["fallidas"])
    if rc == 0 and informe["no_medibles"]:
        rc = 3
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(informe, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for f in informe["fallidas"]:
        print(f"{f['inicio']} {f['agente']} {f['atribucion']} {f.get('respuesta')} error_traza={f.get('error_traza')} "
              f"herramientas={f['llamadas_herramienta']} spans_chat={f['spans_chat']} consumo={f['consumo']} "
              f"coste={f['coste_eur']} EUR")
    print(f"fallidas sin task_id: {len(informe['fallidas'])} · no atribuidas: {informe['no_atribuidas']} · sin consumo "
          f"medible: {informe['no_medibles']} · coste medido {informe['coste_medido_eur']} EUR · rc {rc}"
          + (f" · {informe['error']}" if "error" in informe else ""))
    return rc


if __name__ == "__main__":
    sys.exit(main())
