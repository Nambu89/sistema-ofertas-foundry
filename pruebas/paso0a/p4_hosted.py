"""P4 · Hosted agent ofa-prueba-hosted desplegado por ZIP (python_3_13, dependencias bundled).

Despliegue por REST multipart (Learn, deploy-hosted-agent-code, ms.date 2026-09-29):
- Crear: POST {proyecto}/agents?api-version=v1 con `x-ms-agent-name` y `x-ms-code-zip-sha256`, partes
  `metadata` (application/json) y `code` (application/zip, filename=<agente>.zip).
- Versión nueva: POST {proyecto}/agents/{agente}/versions?api-version=v1 con el mismo cuerpo. El servicio solo
  crea versión si cambia el SHA-256 del ZIP o la definición («content-addressable versioning»).
- Sondeo: GET {proyecto}/agents/{agente}/versions/{v}?api-version=v1 hasta `active` o `failed`.
- Variable desde conexión: OFA_MARCADOR = ${{connections.ofa-prueba-marcador.credentials.valor}} (CustomKeys
  → «credentials.<clave>»). Si la conexión no existe, «the variable is empty» (deploy-hosted-agent, 2026-09-16):
  el despliegue sigue y la prueba del marcador queda PENDIENTE_FERNANDO con las instrucciones exactas.
Llamadas al agente: POST {proyecto}/agents/{agente}/endpoint/protocols/openai/responses[?api-version=v1].

Subpruebas (cada una con su resultado P4a…P4d; P4 es el agregado):
  P4a SALIDA · P4b MARCADOR · P4c TURNO LARGO (background + sondeo, cada sondeo un comando corto) · P4d API-VERSION
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

from pruebas.paso0a import comun
from pruebas.paso0a.hosted_prueba import empaquetar

ID = "P4"
TITULO = "Hosted agent por ZIP bundled: salida, marcador, turno largo y api-version"
AGENTE = comun.AGENTE_HOSTED
RUTA_ENDPOINT = f"agents/{AGENTE}/endpoint/protocols/openai/responses"
VARIABLE_MARCADOR = "OFA_MARCADOR"
REFERENCIA_MARCADOR = "${{connections.%s.credentials.%s}}" % (comun.CONEXION_MARCADOR, comun.CLAVE_MARCADOR)
SEGUNDOS_TURNO = 360
MAX_ESPERA_TURNO_S = 1200.0
MAX_ESPERA_ACTIVO_S = 900.0
TIMEOUT_AGENTE_S = 60.0
TIMEOUT_SUBIDA_S = 65.0
TIMEOUT_CONSULTA_S = 10.0
TIMEOUT_ECO_S = 35.0
TIMEOUT_SONDEO_S = 15.0
MAX_REINTENTOS = 3
TRANSITORIOS = {-1, 424, 429, 500, 502, 503, 504}
SUBPRUEBAS = {"P4a": "SALIDA", "P4b": "MARCADOR", "P4c": "TURNO LARGO", "P4d": "API-VERSION"}
PASOS_SUB = {"P4a": ("salida",), "P4b": ("marcador",), "P4c": ("turno_iniciar", "turno_sondear"),
             "P4d": ("api_version",)}
PASOS_DESPLIEGUE = ("zip", "conexion", "desplegar", "activo")


# ------------------------------------------------------------------------------------ piezas puras
def definicion(conexion_existe: bool | None) -> dict:
    """Definición hosted con código bundled. La marca de la conexión cambia la definición cuando Fernando crea
    la conexión, de modo que el servicio cree una versión nueva que resuelva la referencia.

    La referencia `${{connections…}}` solo se incluye si la conexión existe: comprobado contra Azure el
    18-10-2026, el servicio rechaza el despliegue con HTTP 400 «The following workspace connections referenced
    in environment variable templates were not found» (falla en alto al desplegar, no arranca con la variable
    vacía). Sin conexión, el agente se despliega sin la variable y P4b queda PENDIENTE_FERNANDO."""
    variables = {"OFA_CONEXION_MARCADOR_AL_DESPLEGAR": {True: "existe", False: "no-existe"}.get(
        conexion_existe, "desconocida")}
    if conexion_existe is True:
        variables[VARIABLE_MARCADOR] = REFERENCIA_MARCADOR
    return {"kind": "hosted", "protocol_versions": [{"protocol": "responses", "version": "2.0.0"}],
            "cpu": "1", "memory": "2Gi",
            "code_configuration": {"runtime": "python_3_13", "entry_point": ["python", "main.py"],
                                   "dependency_resolution": "bundled"},
            "environment_variables": variables}


def metadatos(conexion_existe: bool | None) -> dict:
    return {"description": "Prueba desechable P4 del paso 0a (sin modelo, datos sintéticos)",
            "definition": definicion(conexion_existe)}


def partes_multipart(meta: dict, zip_bytes: bytes) -> dict:
    """Partes para requests: `metadata` JSON y `code` ZIP con filename <agente>.zip."""
    return {"metadata": (None, json.dumps(meta, ensure_ascii=False), "application/json"),
            "code": (f"{AGENTE}.zip", zip_bytes, "application/zip")}


def cuerpo_orden(orden: str, background: bool = False) -> dict:
    c: dict[str, Any] = {"input": [{"type": "message", "role": "user",
                                    "content": [{"type": "input_text", "text": orden}]}], "store": True}
    if background:
        c["background"] = True
    return c


def json_del_agente(texto: str) -> dict | None:
    try:
        j = json.loads(texto)
    except (TypeError, ValueError):
        return None
    return j if isinstance(j, dict) else None


def evaluar_salida(texto: str) -> tuple[str, str]:
    j = json_del_agente(texto)
    if not j or not isinstance(j.get("resultados"), list):
        return "FALLA", f"respuesta no interpretable: {texto[:400]}"
    lineas, todas = [], True
    for r in j["resultados"]:
        if isinstance(r.get("http"), int):
            lineas.append(f"{r.get('url')} → HTTP {r['http']} ({r.get('segundos')} s)")
        else:
            todas = False
            lineas.append(f"{r.get('url')} → SIN SALIDA: {r.get('error')}")
    if len(j["resultados"]) != 3:
        todas = False
        lineas.append(f"se esperaban 3 destinos y llegaron {len(j['resultados'])}")
    return ("PASA" if todas else "FALLA"), "; ".join(lineas)


def instrucciones_conexion(cfg: dict) -> str:
    base = (f"/subscriptions/{cfg['suscripcion_id']}/resourceGroups/{cfg['grupo_recursos']}/providers/"
            f"Microsoft.CognitiveServices/accounts/{cfg['recurso']}/projects/{cfg['proyecto']}/connections/"
            f"{comun.CONEXION_MARCADOR}")
    cuerpo = json.dumps({"properties": {"category": "CustomKeys", "authType": "CustomKeys",
                                        "target": "https://learn.microsoft.com", "isSharedToAll": False,
                                        "credentials": {"keys": {comun.CLAVE_MARCADOR: comun.VALOR_MARCADOR}},
                                        "metadata": {"uso": "prueba P4b del paso 0a"}}}, ensure_ascii=False)
    return (f"Fernando crea la conexión (valor NO secreto «{comun.VALOR_MARCADOR}»). Portal de Foundry → proyecto "
            f"{cfg['proyecto']} → Recursos conectados → Nueva conexión → Claves personalizadas (Custom keys): nombre "
            f"«{comun.CONEXION_MARCADOR}», clave «{comun.CLAVE_MARCADOR}», valor «{comun.VALOR_MARCADOR}». "
            f"Alternativa por CLI (forma de ARM NO VERIFICADA; si falla, usa el portal): az rest --method put "
            f"--url \"https://management.azure.com{base}?api-version={cfg['api_versions']['arm_conexiones']}\" "
            f"--body '{cuerpo}'. Después: {comun.PYTHON_VENV} pruebas/paso0a/ejecutar.py --solo P4 --repetir "
            "(la definición cambia sola y el servicio crea una versión que resuelve la referencia).")


def evaluar_marcador(texto: str, conexion_existe: bool | None, cfg: dict) -> tuple[str, str]:
    j = json_del_agente(texto)
    if not j or j.get("orden") != "MARCADOR":
        return "FALLA", f"respuesta no interpretable: {texto[:400]}"
    datos = {k: j.get(k) for k in ("variable_definida", "presente", "sin_resolver", "longitud",
                                   "coincide_con_sintetico", "borrada_de_entorno")}
    if j.get("presente") and j.get("coincide_con_sintetico") and j.get("borrada_de_entorno"):
        return "PASA", f"variable resuelta desde la conexión y borrada del entorno: {datos}"
    if j.get("presente") and not j.get("coincide_con_sintetico"):
        return "FALLA", f"la variable llegó con un valor distinto del sintético acordado: {datos}"
    if conexion_existe is True:
        return "FALLA", (f"la conexión existía al desplegar y la variable llegó vacía o sin resolver: {datos}")
    previo = "no existe" if conexion_existe is False else "no se pudo comprobar (ARM respondió 403: sin permiso de lectura)"
    return "PENDIENTE_FERNANDO", (f"la conexión {comun.CONEXION_MARCADOR} {previo}; el agente se desplegó sin la "
                                  "referencia (con ella, el servicio rechaza el despliegue con HTTP 400 «workspace "
                                  f"connections … were not found») y la variable no llega: {datos}. "
                                  f"{instrucciones_conexion(cfg)}")


def evaluar_turno(respuesta: dict | None, segundos: int = SEGUNDOS_TURNO) -> tuple[str, str]:
    if not isinstance(respuesta, dict):
        return "FALLA", "sin respuesta final"
    if respuesta.get("status") != "completed":
        return "FALLA", f"status={respuesta.get('status')} error={respuesta.get('error')}"
    j = json_del_agente(comun.texto_salida(respuesta)) or {}
    medidos = j.get("segundos_medidos")
    if j.get("resultado") == "TURNO_LARGO COMPLETADO" and isinstance(medidos, (int, float)) and medidos >= segundos:
        return "PASA", f"completed tras {medidos} s medidos en el contenedor (pedidos {segundos})"
    return "FALLA", f"respuesta completed pero sin la marca esperada: {comun.texto_salida(respuesta)[:400]}"


def evaluar_api_version(con: dict, sin: dict, eco_esperado: str) -> tuple[str, str]:
    det = (f"con ?api-version=v1 → HTTP {con.get('http')}: {con.get('texto', '')[:300]} | "
           f"sin api-version → HTTP {sin.get('http')}: {sin.get('texto', '')[:300]}")
    ok_con = con.get("http") == 200 and eco_esperado in con.get("texto", "")
    ok_sin = sin.get("http") == 200 and eco_esperado in sin.get("texto", "")
    nota = ("; SIN api-version TAMBIÉN funciona: OpenCode puede usar baseURL directo" if ok_sin else
            "; sin api-version NO funciona: OpenCode (@ai-sdk/openai no añade parámetros de consulta) necesitará "
            "una corrección (ver P5)")
    return ("PASA" if ok_con else "FALLA"), det + nota


# ------------------------------------------------------------------------------------------- pasos
def _invocar(ctx: comun.Contexto, orden: str, *, api_version: bool = True, background: bool = False,
             timeout: float = TIMEOUT_AGENTE_S):
    return ctx.cliente.datos("POST", RUTA_ENDPOINT, params={"api-version": "v1"} if api_version else None,
                             json_body=cuerpo_orden(orden, background), timeout=timeout)


def _transitorio(ctx: comun.Contexto, pr: dict, paso: str, r) -> comun.EnCurso | None:
    """Arranque en frío (424, 5xx, tiempo agotado): hasta 3 intentos anotados (P-6), luego fallo visible."""
    if r.estado in TRANSITORIOS or (r.estado == 400 and "still being provisioned" in r.texto):
        n = pr.setdefault("reintentos", {}).get(paso, 0) + 1
        pr["reintentos"][paso] = n
        if n < MAX_REINTENTOS:
            ctx.escribir(f"[reintento {n}/{MAX_REINTENTOS}] P4 {paso}: {r.resumen(200)}")
            return comun.EnCurso(f"P4 {paso}: respuesta transitoria ({r.estado}), se reintenta", 15.0)
    return None


def _llamadas(ctx: comun.Contexto, pr: dict, pasos: tuple[str, ...]) -> list[str]:
    """Llamadas acumuladas en el progreso para esos pasos (incluidas las del paso en marcha)."""
    ctx.nuevas_llamadas(pr, pr.get("_paso_actual", "-"))
    return [c for paso in pasos for c in pr.get("llamadas", {}).get(paso, [])]


def _sub(ctx: comun.Contexto, pr: dict, id_sub: str, estado: str, evidencia: str) -> None:
    """Resultado de una subprueba con su hora de medición y las llamadas que lo produjeron."""
    pr.setdefault("sub", {})[id_sub] = {"estado": estado, "evidencia": evidencia, "fecha": ctx.fecha(),
                                        "llamadas": _llamadas(ctx, pr, PASOS_SUB[id_sub])}


def _paso_zip(ctx: comun.Contexto, pr: dict):
    ruta = pathlib.Path(ctx.opciones.get("zip") or empaquetar.ZIP_POR_DEFECTO)
    if not ruta.is_file():
        return comun.EnCurso(f"P4: falta el ZIP {ruta}. Ejecuta antes (cada fase dura menos de 90 s): "
                             f"{comun.PYTHON_VENV} pruebas/paso0a/hosted_prueba/empaquetar.py", 0)
    try:
        pr["zip_sha256"] = empaquetar.comprobar_zip(ruta)
    except (empaquetar.ErrorEmpaquetado, OSError, ValueError, KeyError) as e:
        return _final(ctx, pr, "FALLA", f"El ZIP no supera la comprobación del manifiesto: {e}")
    pr.update({"zip": str(ruta), "zip_bytes": ruta.stat().st_size, "paso": "conexion"})
    return None


def _paso_conexion(ctx: comun.Contexto, pr: dict):
    r = ctx.cliente.arm_get(f"/projects/{ctx.cfg['proyecto']}/connections/{comun.CONEXION_MARCADOR}",
                            ctx.cfg["api_versions"]["arm_conexiones"])
    if r.estado not in (200, 404, 403):
        en_curso = _transitorio(ctx, pr, "conexion", r)
        if en_curso:
            return en_curso
        # Un fallo técnico de ARM no es «pendiente de Fernando»: solo el 403 (sin permiso de lectura) lo es.
        pr["conexion_http"] = r.estado
        return _final(ctx, pr, "FALLA", f"ARM no pudo consultar la conexión {comun.CONEXION_MARCADOR}: "
                                         f"{r.resumen(800)}")
    pr["conexion_existe"] = True if r.estado == 200 else False if r.estado == 404 else None
    pr["conexion_http"] = r.estado
    pr["paso"] = "desplegar"
    return None


def _paso_desplegar(ctx: comun.Contexto, pr: dict):
    zip_bytes = pathlib.Path(pr["zip"]).read_bytes()
    if comun_sha(zip_bytes) != pr["zip_sha256"]:
        return _final(ctx, pr, "FALLA", "El ZIP cambió entre la comprobación y la subida")
    meta = metadatos(pr.get("conexion_existe"))
    cab = {"x-ms-code-zip-sha256": pr["zip_sha256"]}
    existe = ctx.cliente.datos("GET", f"agents/{AGENTE}", timeout=TIMEOUT_CONSULTA_S)
    if existe.estado == 404:
        r = ctx.cliente.datos("POST", "agents", files=partes_multipart(meta, zip_bytes),
                              cabeceras={**cab, "x-ms-agent-name": AGENTE}, timeout=TIMEOUT_SUBIDA_S)
    elif existe.estado == 200:
        r = ctx.cliente.datos("POST", f"agents/{AGENTE}/versions", files=partes_multipart(meta, zip_bytes),
                              cabeceras=cab, timeout=TIMEOUT_SUBIDA_S)
    else:
        return _transitorio(ctx, pr, "desplegar", existe) or _final(
            ctx, pr, "FALLA", f"No se pudo consultar el agente antes de desplegar: {existe.resumen()}")
    j = r.json() or {}
    if r.estado not in (200, 201):
        # Repetir la subida es seguro: el servicio deduplica por SHA-256 del ZIP y definición (Learn).
        return _transitorio(ctx, pr, "desplegar", r) or _final(
            ctx, pr, "FALLA", f"El despliegue por ZIP falló: {r.resumen(1500)}")
    version = j.get("version") or ((j.get("versions") or {}).get("latest") or {}).get("version")
    if not version:
        return _final(ctx, pr, "FALLA", f"El despliegue no devolvió versión: {r.resumen(800)}")
    pr.update({"version": str(version), "estado_version": j.get("status"), "estado_al_subir": j.get("status"),
               "t_despliegue": ctx.reloj(), "sondeos_activo": 0, "paso": "activo"})
    return None


def comun_sha(datos: bytes) -> str:
    return empaquetar.sha256(datos)


def _paso_activo(ctx: comun.Contexto, pr: dict):
    r = ctx.cliente.datos("GET", f"agents/{AGENTE}/versions/{pr['version']}")
    j = r.json() or {}
    if r.estado != 200:
        return _transitorio(ctx, pr, "activo", r) or _final(ctx, pr, "FALLA", f"Sondeo de versión: {r.resumen()}")
    estado = j.get("status")
    pr["estado_version"] = estado
    pr["sondeos_activo"] = pr.get("sondeos_activo", 0) + 1
    if estado == "active":
        pr["s_hasta_activo"] = round(ctx.reloj() - pr["t_despliegue"], 1)
        pr["paso"] = "salida"
        return None
    if estado == "failed":
        return _final(ctx, pr, "FALLA", f"La versión {pr['version']} quedó en failed: {json.dumps(j.get('error'))[:1500]}")
    if ctx.reloj() - pr["t_despliegue"] > MAX_ESPERA_ACTIVO_S:
        return _final(ctx, pr, "FALLA", f"La versión {pr['version']} sigue en {estado} tras {MAX_ESPERA_ACTIVO_S:.0f} s")
    return comun.EnCurso(f"P4: versión {pr['version']} en {estado}", 10.0)


def _paso_orden(ctx: comun.Contexto, pr: dict, paso: str, id_sub: str, orden: str, siguiente: str, evaluar):
    r = _invocar(ctx, orden)
    if r.estado != 200:
        en_curso = _transitorio(ctx, pr, paso, r)
        if en_curso:
            return en_curso
        _sub(ctx, pr, id_sub, "FALLA", f"POST {RUTA_ENDPOINT}?api-version=v1 «{orden}» → {r.resumen(800)}")
    else:
        estado, det = evaluar(comun.texto_salida(r.json()))
        _sub(ctx, pr, id_sub, estado, f"«{orden}» → HTTP 200 en {r.latencia_s:.1f} s · {det}")
    pr["paso"] = siguiente
    return None


def _paso_salida(ctx, pr):
    return _paso_orden(ctx, pr, "salida", "P4a", "ORDEN: SALIDA", "marcador", evaluar_salida)


def _paso_marcador(ctx, pr):
    return _paso_orden(ctx, pr, "marcador", "P4b", "ORDEN: MARCADOR", "api_version",
                       lambda t: evaluar_marcador(t, pr.get("conexion_existe"), ctx.cfg))


def _paso_api_version(ctx: comun.Contexto, pr: dict):
    eco = "api-version-p4d"
    resultados = {}
    for clave, con_av in (("con", True), ("sin", False)):
        r = _invocar(ctx, f"ORDEN: ECO {eco}", api_version=con_av, timeout=TIMEOUT_ECO_S)
        if clave == "con" and r.estado != 200:
            en_curso = _transitorio(ctx, pr, "api_version", r)
            if en_curso:
                return en_curso
        resultados[clave] = {"http": r.estado, "texto": comun.texto_salida(r.json()) if r.estado == 200
                             else comun.redactar(r.texto)[:600]}
    estado, det = evaluar_api_version(resultados["con"], resultados["sin"], f"ECO-OFA: {eco}")
    _sub(ctx, pr, "P4d", estado, det)
    pr["api_version_sin_funciona"] = resultados["sin"]["http"] == 200
    pr["paso"] = "turno_iniciar"
    return None


def _paso_turno_iniciar(ctx: comun.Contexto, pr: dict):
    r = _invocar(ctx, f"ORDEN: TURNO_LARGO {SEGUNDOS_TURNO}", background=True)
    j = r.json() or {}
    if r.estado != 200 or not j.get("id"):
        en_curso = _transitorio(ctx, pr, "turno_iniciar", r)
        if en_curso:
            return en_curso
        _sub(ctx, pr, "P4c", "FALLA", f"POST background → {r.resumen(800)}")
        pr["paso"] = "veredicto"
        return None
    sesion = j.get("agent_session_id") or {k.lower(): v for k, v in r.cabeceras.items()}.get("x-agent-session-id")
    pr["turno"] = {"id": j["id"], "status": j.get("status"), "t0": ctx.reloj(), "lanzado": ctx.fecha(),
                   "sesion": sesion, "sondeos": 0, "marcas": []}
    pr["paso"] = "turno_sondear"
    return comun.EnCurso(f"P4c: turno largo lanzado ({j['id']}, status {j.get('status')}); se sondea", 20.0)


def _paso_turno_sondear(ctx: comun.Contexto, pr: dict):
    t = pr["turno"]
    ruta = f"{RUTA_ENDPOINT}/{t['id']}"
    r = ctx.cliente.datos("GET", ruta, params={"api-version": "v1"}, timeout=TIMEOUT_SONDEO_S)
    if r.estado == 404 and t.get("sesion"):   # forma vista en el MVP: el sondeo puede exigir la sesión
        r = ctx.cliente.datos("GET", ruta, params={"api-version": "v1", "agent_session_id": t["sesion"]},
                              timeout=TIMEOUT_SONDEO_S)
    t["sondeos"] += 1
    transcurrido = ctx.reloj() - t["t0"]
    j = r.json() or {}
    # Hora, segundo desde el lanzamiento, HTTP y status de cada sondeo: el hueco entre sondeos queda registrado.
    t.setdefault("marcas", []).append([ctx.fecha(), round(transcurrido, 1), r.estado, j.get("status")])
    if r.estado != 200:
        t["errores"] = t.get("errores", 0) + 1
        if t["errores"] >= MAX_REINTENTOS:
            _sub(ctx, pr, "P4c", "FALLA", f"{MAX_REINTENTOS} sondeos seguidos fallidos; último: {r.resumen(600)}"
                                          f" · {resumen_sondeos(t)}")
            pr["paso"] = "veredicto"
            return None
        return comun.EnCurso(f"P4c: sondeo fallido {t['errores']}/{MAX_REINTENTOS} ({r.estado})", 20.0)
    t["errores"] = 0
    if j.get("status") in comun.TERMINALES:
        estado, det = evaluar_turno(j)
        _sub(ctx, pr, "P4c", estado, f"background + {t['sondeos']} sondeos cortos; {transcurrido:.0f} s de reloj "
                                     f"local · {det} · {resumen_sondeos(t)}")
        pr["paso"] = "veredicto"
        return None
    if transcurrido > MAX_ESPERA_TURNO_S:
        _sub(ctx, pr, "P4c", "FALLA", f"sigue en {j.get('status')} tras {transcurrido:.0f} s (máximo "
                                      f"{MAX_ESPERA_TURNO_S:.0f}) · {resumen_sondeos(t)}")
        pr["paso"] = "veredicto"
        return None
    return comun.EnCurso(f"P4c: {j.get('status')} a los {transcurrido:.0f} s de {SEGUNDOS_TURNO}", 20.0)


def resumen_sondeos(t: dict) -> str:
    """Lanzamiento, cada sondeo (hora UTC, segundo, HTTP, status) y el hueco máximo entre dos consecutivos."""
    marcas = t.get("marcas") or []
    segundos = [0.0] + [float(m[1]) for m in marcas]
    hueco = max((b - a for a, b in zip(segundos, segundos[1:])), default=0.0)
    detalle = ", ".join(f"{m[0]} +{m[1]:.0f} s HTTP {m[2]} {m[3]}" for m in marcas)
    return (f"lanzado {t.get('lanzado', '-')}; sondeos: {detalle or 'ninguno'}; hueco máximo entre sondeos "
            f"{hueco:.0f} s")


def _paso_veredicto(ctx: comun.Contexto, pr: dict):
    lineas, estados, artefactos = [], [], []
    for id_sub, nombre in SUBPRUEBAS.items():
        s = pr.get("sub", {}).get(id_sub) or {"estado": "FALLA", "evidencia": "no se llegó a ejecutar"}
        res = comun.construir_resultado(id_sub, s["estado"], ctx.marcar(f"{nombre}: {s['evidencia']}"),
                                        ctx.comando(ID, llamadas=s.get("llamadas", [])),
                                        s.get("fecha") or ctx.fecha())
        ruta = comun.escribir_json(ctx.dir_resultados / f"{id_sub}.json", res)
        artefactos.append(ruta.name)
        estados.append(s["estado"])
        lineas.append(f"- {id_sub} {nombre}: {s['estado']} · {s['evidencia']}")
    return _final(ctx, pr, comun.combinar_estados(estados), "\n".join(lineas), artefactos)


def _final(ctx: comun.Contexto, pr: dict, estado: str, evidencia: str, artefactos: list[str] | None = None) -> dict:
    cab = (f"Agente {AGENTE} v{pr.get('version', '-')} (estado {pr.get('estado_version', '-')}); ZIP bundled "
           f"python_3_13 SHA-256 {pr.get('zip_sha256', '-')} ({pr.get('zip_bytes', '-')} B); conexión "
           f"{comun.CONEXION_MARCADOR}: {'existe' if pr.get('conexion_existe') else 'no existe' if pr.get('conexion_existe') is False else 'desconocida'} "
           f"(ARM HTTP {pr.get('conexion_http', '-')}).")
    if pr.get("s_hasta_activo") is not None:
        cab += (f" Estado al subir: {pr.get('estado_al_subir')}; active {pr['s_hasta_activo']} s después de la subida "
                f"({pr.get('sondeos_activo')} sondeos de versión).")
    # El comando de P4 son las llamadas del despliegue; cada P4x lleva las suyas.
    llamadas = _llamadas(ctx, pr, PASOS_DESPLIEGUE)
    return comun.construir_resultado(ID, estado, cab + "\n" + evidencia, ctx.comando(ID, llamadas=llamadas),
                                     ctx.fecha(), artefactos)


PASOS = {"zip": (_paso_zip, 2.0), "conexion": (_paso_conexion, comun.TIMEOUT_HTTP_S + 1),
         "desplegar": (_paso_desplegar, TIMEOUT_CONSULTA_S + TIMEOUT_SUBIDA_S + 1),
         "activo": (_paso_activo, comun.TIMEOUT_HTTP_S + 1),
         "salida": (_paso_salida, TIMEOUT_AGENTE_S + 1), "marcador": (_paso_marcador, TIMEOUT_AGENTE_S + 1),
         "api_version": (_paso_api_version, 2 * TIMEOUT_ECO_S + 1),
         "turno_iniciar": (_paso_turno_iniciar, TIMEOUT_AGENTE_S + 1),
         "turno_sondear": (_paso_turno_sondear, 2 * TIMEOUT_SONDEO_S + 1),
         "veredicto": (_paso_veredicto, 1.0)}


def ejecutar(ctx: comun.Contexto) -> dict | comun.EnCurso:
    pr = ctx.leer_progreso(ID)
    if not pr:   # comienzo limpio: fuera los resultados parciales de una ejecución anterior
        pr = {"paso": "zip"}
        for id_sub in (*SUBPRUEBAS, "P4-estado"):
            (ctx.dir_resultados / f"{id_sub}.json").unlink(missing_ok=True)
    while True:
        funcion, duracion = PASOS[pr["paso"]]
        if ctx.restante() < duracion:
            ctx.guardar_progreso(ID, pr)
            return comun.EnCurso(f"P4: sin presupuesto para el paso {pr['paso']} (necesita ~{duracion:.0f} s); "
                                 "vuelve a ejecutar", 0)
        pr["_paso_actual"] = pr["paso"]
        pr["_marca"] = len(ctx.cliente.llamadas)
        res = funcion(ctx, pr)
        ctx.nuevas_llamadas(pr, pr["_paso_actual"])
        if isinstance(res, dict):
            ctx.borrar_progreso(ID)
            estado_previo = {"version": pr.get("version"), "api_version_sin_funciona": pr.get("api_version_sin_funciona")}
            comun.escribir_json(ctx.dir_resultados / "P4-estado.json", estado_previo)
            return res
        ctx.guardar_progreso(ID, pr)
        if isinstance(res, comun.EnCurso):
            return res
