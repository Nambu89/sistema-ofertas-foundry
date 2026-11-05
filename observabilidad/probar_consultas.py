"""Ejecuta las consultas de observabilidad/consultas.kql contra appi-preventa-ejemplo por REST.

Separa las consultas por los bloques numerados ("// N. ..."), las lanza una a una contra Application
Insights por Azure Resource Manager (`lib.appi`: token de https://management.azure.com, api-version
2018-04-20, JSON en UTF-8) y guarda el resultado con la red de `lib.evidencia`. I1.2 (F4): antes usaba
`api.applicationinsights.io`, cuya audiencia pide un MFA aparte (VERIF-6). No usa
`az monitor app-insights query`: en Windows `az` escribe en cp1252 y las tildes llegaban como U+FFFD
(LES-G-090.8). El token vive solo en memoria.

Uso: python -m observabilidad.probar_consultas [--offset 24h] [--solo 2,3] [--salida FICHERO.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parents[1]
KQL = RAIZ / "observabilidad" / "consultas.kql"
SALIDA = RAIZ / "pruebas" / "I0" / "B4"
APP_ID = "appi-preventa-ejemplo"


def consultas() -> list[tuple[str, str]]:
    """Devuelve [(título, consulta)] sin comentarios ni el ';' final."""
    bloques = re.split(r"^// (\d+\. .*)$", KQL.read_text(encoding="utf-8"), flags=re.M)
    res = []
    for i in range(1, len(bloques) - 1, 2):
        lineas = [l for l in bloques[i + 1].splitlines() if not l.strip().startswith("//")]
        cuerpo = "\n".join(lineas).strip().rstrip(";").strip()
        res.append((bloques[i].strip(), cuerpo))
    return res


def interpretar(rc: int, stdout: str) -> tuple[int | None, object]:
    """Devuelve (filas, salida). filas=None si la consulta falló, la salida no es JSON con tablas o
    trae `error` (resultado parcial, Revisión F4: no se da por bueno aunque haya filas)."""
    if rc != 0 or not stdout:
        return None, None
    try:
        datos = json.loads(stdout)
        if datos.get("error") or not isinstance(datos.get("tables"), list):
            return None, datos
        return sum(len(tb.get("rows", [])) for tb in datos.get("tables", [])), datos
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None, stdout[-1500:]


def duracion_iso(offset: str) -> str:
    """'24h' -> 'PT24H', '30m' -> 'PT30M', '2d' -> 'P2D'. Lo demás falla en alto (LES-G-060)."""
    m = re.fullmatch(r"(\d{1,4})([mhd])", offset.strip().lower())
    if not m:
        raise SystemExit(f"--offset no admitido: {offset!r} (usa por ejemplo 30m, 6h o 2d)")
    n, u = m.groups()
    return f"P{n}D" if u == "d" else f"PT{n}{u.upper()}"


def url_consulta(cfg: dict) -> str:
    from lib import appi
    return appi.url_consulta(cfg["suscripcion_id"], cfg["grupo_recursos"], APP_ID)


def consultar(q: str, timespan: str) -> tuple[int, str, list[str]]:
    """POST de la consulta. Devuelve (estado HTTP, cuerpo en UTF-8, notas). Un fallo de red se
    reintenta una sola vez y queda anotado; 0 como estado significa que no hubo respuesta."""
    import requests
    from lib.azure_auth import AUD_ARM, obtener_token
    from lib.config import cargar
    cfg = cargar()
    url = url_consulta(cfg)  # valida los segmentos antes de pedir el token
    token = obtener_token(AUD_ARM, cfg["tenant_id"])  # solo en memoria; nunca se imprime
    notas: list[str] = []
    for intento in (1, 2):
        try:
            r = requests.post(url, json={"query": q, "timespan": timespan},
                              headers={"Authorization": f"Bearer {token}"}, timeout=180)
        except (requests.ConnectionError, requests.Timeout) as e:
            notas.append(f"intento {intento}/2: {type(e).__name__} (red, DNS o tiempo agotado)")
            if intento == 1:
                time.sleep(5)
            continue
        if r.status_code != 200:  # el cuerpo de un error solo se muestra: aquí sí vale el reemplazo
            return r.status_code, r.content.decode("utf-8", errors="replace"), notas
        try:  # un 200 se decodifica estricto (Revisión F4): un byte inválido no se convierte en U+FFFD
            return 200, r.content.decode("utf-8-sig"), notas
        except UnicodeDecodeError as e:
            return 200, "", notas + [f"la respuesta no es UTF-8 (byte {e.start}): no se da por buena"]
    return 0, "", notas


def main(argv: list[str] | None = None) -> int:
    from lib import evidencia
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offset", default="24h")
    ap.add_argument("--solo", default="", help="números de consulta separados por comas (p. ej. 2,3)")
    ap.add_argument("--salida", type=pathlib.Path, default=None)
    a = ap.parse_args(argv)
    timespan = duracion_iso(a.offset)
    todas = consultas()
    pedidas = {s.strip() for s in a.solo.split(",") if s.strip()}
    desconocidas = pedidas - {t.split(".")[0] for t, _ in todas}
    if desconocidas:
        print(f"Consultas inexistentes: {sorted(desconocidas)}", file=sys.stderr)
        return 2
    resumen, rc_global = [], 0
    for titulo, q in todas:
        if pedidas and titulo.split(".")[0] not in pedidas:
            continue
        estado, cuerpo, notas = consultar(q, timespan)
        filas, salida = interpretar(0 if estado == 200 else 1, cuerpo)
        if estado != 200 or filas is None:
            rc_global = 1  # un resultado ilegible cuenta como fallo, no como éxito
        resumen.append({"consulta": titulo, "http": estado, "filas": filas, "notas": notas,
                        "error": None if estado == 200 else cuerpo[-1500:], "salida": salida})
        print(f"{titulo[:60]:<60} http={estado} filas={filas} {' · '.join(notas)}")
        if estado != 200:
            print("   " + evidencia.enmascarar_texto(cuerpo[-600:]), file=sys.stderr)
    sello = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = a.salida or (SALIDA / f"consultas_{sello}.json")
    evidencia.guardar_enmascarado(destino, {"timespan": timespan, "consultas": resumen})
    print(f"evidencia: {destino}")
    return rc_global


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
