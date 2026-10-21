"""P5 · OpenCode como cliente del hosted agent ofa-prueba-hosted (canales-opencode-teams.md, punto 3).

Usa un directorio de trabajo FIJO bajo $TEMP (`ofa-p5-opencode`; nunca toca ~/.config/opencode, los datos
globales de OpenCode ni la carpeta Proyectos). Es fijo para que OpenCode instale una sola vez las dependencias
del plugin: la primera ejecución en un directorio nuevo tarda más de 75 s (comprobado el 18-10-2026).
- opencode.json con un proveedor propio `@ai-sdk/openai` cuyo baseURL es el endpoint openai del hosted
  ({proyecto}/agents/ofa-prueba-hosted/endpoint/protocols/openai; @ai-sdk/openai añade «/responses»).
- .opencode/plugin/foundry-token.js:
  · hook `chat.headers` (@opencode-ai/plugin 1.17.9, dist/index.d.ts:216) que pide a az un token de Entra con
    el tenant FIJO, comprueba su `tid` y lo pone en Authorization. El token nunca se escribe ni se imprime.
  · envoltorio de `fetch` que añade `?api-version=v1` SOLO a las URL que empiezan por el baseURL exacto del
    hosted. Motivo (comprobado el 18-10-2026): el endpoint responde 400 «Missing required query parameter:
    api-version» sin el parámetro, y OpenCode 1.18.33 pide `${baseURL}/responses` sin consulta tanto con
    @ai-sdk/openai como con @ai-sdk/azure (con este último también, aunque se le dé `apiVersion`).
- Aislamiento: XDG_CONFIG_HOME y XDG_DATA_HOME apuntan a subdirectorios del de trabajo (no se carga la
  configuración global ni se escribe en la base de datos de sesiones del usuario) y se desactivan la
  autoactualización, la lectura de ficheros de Claude Code y la descarga de modelos.
Ejecuta «opencode run --dir <directorio> -m ofa-hosted/ofa-prueba-hosted "ORDEN: ECO p5-<aleatorio>"» con tiempo máximo de
75 s (la fase de ejecución prohíbe comandos de más de 90 s; antes eran 120 s). Evidencia: la respuesta
del hosted («ECO-OFA: p5-<aleatorio>»). Si la primera ejecución en el directorio agota el tiempo sin salida, se
marca el directorio como calentado y sale «en curso» (4): la siguiente invocación da el veredicto.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import shutil
import subprocess
import tempfile
from typing import Any

from pruebas.paso0a import comun

ID = "P5"
TITULO = "OpenCode como cliente del hosted"
PROVEEDOR = "ofa-hosted"
MODELO = comun.AGENTE_HOSTED
TIMEOUT_OPENCODE_S = 75  # regla de la fase de ejecución: ningún comando de más de 90 s (antes 120)
DIRECTORIO_FIJO = "ofa-p5-opencode"
MARCA_CALENTADO = ".calentado"
PLUGIN = """// Inyecta un token de Entra (tenant fijo, LES-G-052) en las peticiones al proveedor {proveedor} y añade
// ?api-version=v1 a las URL del endpoint del hosted (que lo exige y OpenCode no lo pone).
// Generado por pruebas/paso0a/p5_opencode.py. No guarda ni imprime el token.
import {{ execFileSync }} from "node:child_process"

const TENANT = "{tenant}"
const PROVEEDOR = "{proveedor}"
const PREFIJO_HOSTED = "{prefijo}"
let cache = {{ token: "", expira: 0 }}

const fetchOriginal = globalThis.fetch
globalThis.fetch = async (input, init) => {{
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input?.url
  if (typeof url !== "string" || !url.startsWith(PREFIJO_HOSTED)) return fetchOriginal(input, init)
  const u = new URL(url)
  if (!u.searchParams.has("api-version")) u.searchParams.set("api-version", "v1")
  const destino = (typeof input === "string" || input instanceof URL) ? u.href : new Request(u.href, input)
  return fetchOriginal(destino, init)
}}

function tid(token) {{
  const cuerpo = token.split(".")[1] || ""
  return JSON.parse(Buffer.from(cuerpo, "base64url").toString("utf8")).tid
}}

function pedirToken() {{
  const windows = process.platform === "win32"
  const salida = execFileSync(windows ? "az.cmd" : "az",
    ["account", "get-access-token", "--tenant", TENANT, "--resource", "https://ai.azure.com", "-o", "json"],
    {{ encoding: "utf8", timeout: 60000, shell: windows, windowsHide: true }})
  const r = JSON.parse(salida)
  if (tid(r.accessToken) !== TENANT) throw new Error("token de otro tenant: az login --tenant " + TENANT)
  cache = {{ token: r.accessToken, expira: Number(r.expires_on) * 1000 }}
}}

export const FoundryToken = async () => ({{
  "chat.headers": async (input, output) => {{
    const proveedor = input?.model?.providerID ?? input?.provider?.info?.id ?? input?.provider?.id
    if (proveedor !== PROVEEDOR) return
    if (Date.now() > cache.expira - 300000) pedirToken()
    output.headers["Authorization"] = "Bearer " + cache.token
  }},
}})
"""


def resolver_opencode(ruta: str | None) -> str | None:
    """En Windows, npm instala un lanzador .cmd; se prefiere el opencode.exe real para que el tiempo
    máximo mate al proceso que trabaja y no solo a cmd.exe."""
    if not ruta:
        return None
    p = pathlib.Path(ruta)
    if p.suffix.lower() in (".cmd", ".bat", ""):
        exe = p.parent / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
        if exe.is_file():
            return str(exe)
    return str(p)


def base_url(cfg: dict) -> str:
    return f"{cfg['endpoints']['proyecto'].rstrip('/')}/agents/{comun.AGENTE_HOSTED}/endpoint/protocols/openai"


def configuracion(cfg: dict) -> dict:
    return {"$schema": "https://opencode.ai/config.json",
            "provider": {PROVEEDOR: {"npm": "@ai-sdk/openai", "name": "Hosted de prueba (paso 0a)",
                                     "options": {"baseURL": base_url(cfg), "apiKey": "lo-sustituye-el-plugin"},
                                     "models": {MODELO: {"name": "ofa-prueba-hosted",
                                                         "limit": {"context": 128000, "output": 8000}}}}},
            "model": f"{PROVEEDOR}/{MODELO}"}


def plugin(cfg: dict) -> str:
    return PLUGIN.format(tenant=cfg["tenant_id"], proveedor=PROVEEDOR, prefijo=base_url(cfg) + "/")


def preparar_directorio(destino: pathlib.Path, cfg: dict) -> dict[str, pathlib.Path]:
    destino.mkdir(parents=True, exist_ok=True)
    rutas = {"config": destino / "opencode.json", "plugin": destino / ".opencode" / "plugin" / "foundry-token.js",
             "xdg": destino / "xdg-config", "datos": destino / "xdg-data"}
    rutas["plugin"].parent.mkdir(parents=True, exist_ok=True)
    rutas["xdg"].mkdir(exist_ok=True)
    rutas["datos"].mkdir(exist_ok=True)
    rutas["config"].write_bytes((json.dumps(configuracion(cfg), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    rutas["plugin"].write_bytes(plugin(cfg).encode("utf-8"))
    return rutas


def directorio_fijo() -> pathlib.Path:
    """Directorio de trabajo fijo de P5 bajo $TEMP (nunca dentro del repositorio ni de la carpeta Proyectos)."""
    base = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
    return pathlib.Path(base) / DIRECTORIO_FIJO


def entorno(rutas: dict[str, pathlib.Path], base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    # OpenCode (Bun) toma el directorio del proyecto de PWD antes que del cwd real del proceso: con el PWD
    # heredado del shell, la sesión se abría en el repositorio, sin el proveedor ni el plugin, y fallaba con
    # UnknownError (visto el 18-10-2026 en su registro: «creating instance» con el directorio del repositorio).
    env.update({"PWD": str(rutas["config"].parent),
                "XDG_CONFIG_HOME": str(rutas["xdg"]), "XDG_DATA_HOME": str(rutas["datos"]),
                "OPENCODE_DISABLE_AUTOUPDATE": "1",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1"})
    for clave in ("OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT"):
        env.pop(clave, None)
    return env


MAX_SALIDA_PASA = 800


_RE_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def sin_ruta_personal(texto: str) -> str:
    """Quita los códigos de color ANSI y sustituye la carpeta personal (lleva el nombre de usuario) por «~»."""
    texto = _RE_ANSI.sub("", texto)
    casa = str(pathlib.Path.home())
    for variante in {casa, casa.replace("\\", "/")}:
        texto = texto.replace(variante, "~")
    return texto


def evaluar(rc: int | None, salida: str, nonce: str) -> tuple[str, str]:
    esperado = f"ECO-OFA: {nonce}"
    if rc == 0 and esperado in salida:
        # La salida va pegada también cuando pasa (LES-G-058: comando y salida, no solo la afirmación).
        return "PASA", (f"opencode rc=0 y la respuesta del hosted contiene «{esperado}» "
                        f"({salida.count(esperado)} vez/veces); salida literal (redactada, últimos "
                        f"{MAX_SALIDA_PASA} caracteres): {salida.strip()[-MAX_SALIDA_PASA:]}")
    detalle = f"opencode rc={rc}; salida: {salida[-1500:]}"
    if "api-version" in salida.lower() or "api_version" in salida.lower():
        detalle += (" | El fallo menciona api-version: OpenCode 1.18.33 pide `${baseURL}/responses` sin consulta, "
                    "con @ai-sdk/openai y también con @ai-sdk/azure (comprobado el 18-10-2026). Corrección: el "
                    "envoltorio de `fetch` del plugin, que añade ?api-version=v1 solo al prefijo del hosted; "
                    "revisar que el plugin se cargó y que el prefijo coincide con el baseURL.")
    elif rc is None:
        detalle += f" | opencode no terminó en {TIMEOUT_OPENCODE_S} s"
        if salida.count(esperado) > 1:
            detalle += (f" y repitió la respuesta {salida.count(esperado)} veces: OpenCode no reconoce el fin del "
                        "turno (motivo de fin «unknown»); el hosted debe enviar `usage` en response.completed")
    return "FALLA", detalle


def ejecutar(ctx: comun.Contexto) -> dict | comun.EnCurso:
    existe = ctx.cliente.datos("GET", f"agents/{comun.AGENTE_HOSTED}")
    if existe.estado == 404:
        return comun.EnCurso("P5 necesita el hosted desplegado: ejecuta antes --solo P4", 0)
    if existe.estado in (-1, 408, 429) or existe.estado >= 500:
        # Sin respuesta (DNS, red, tiempo agotado) o error transitorio del servicio: no es un veredicto sobre
        # OpenCode. Visto el 18-10-2026: getaddrinfo falló una vez justo después de un P4 correcto.
        return comun.EnCurso(f"P5: comprobación del hosted transitoria ({existe.resumen()}); vuelve a ejecutar "
                             "--solo P5", 10.0)
    if existe.estado != 200:
        return comun.construir_resultado(ID, "FALLA", f"No se pudo comprobar el hosted: {existe.resumen()}",
                                         ctx.comando(ID), ctx.fecha())
    if ctx.restante() < TIMEOUT_OPENCODE_S + 5:
        return comun.EnCurso(f"P5 necesita {TIMEOUT_OPENCODE_S + 5} s de presupuesto: usa --solo P5", 0)
    ejecutable = ctx.opciones.get("opencode") or resolver_opencode(shutil.which("opencode"))
    if not ejecutable:
        return comun.construir_resultado(ID, "FALLA", "No se encuentra opencode en el PATH", ctx.comando(ID), ctx.fecha())
    nonce = "p5-" + (ctx.opciones.get("nonce") or secrets.token_hex(4))
    directorio = pathlib.Path(ctx.opciones.get("dir_temporal") or directorio_fijo())
    calentado = (directorio / MARCA_CALENTADO).is_file()
    rutas = preparar_directorio(directorio, ctx.cfg)
    cmd = [ejecutable, "run", "--dir", str(directorio), "-m", f"{PROVEEDOR}/{MODELO}", f"ORDEN: ECO {nonce}"]
    rc: int | None
    try:
        r: Any = ctx.proceso(cmd, cwd=str(directorio), env=entorno(rutas), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=TIMEOUT_OPENCODE_S)
        rc, salida = r.returncode, (r.stdout or "") + "\n" + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        rc, salida = None, f"{e.stdout or ''}\n{e.stderr or ''}"
        if isinstance(salida, bytes):
            salida = salida.decode("utf-8", "replace")
    finally:
        # El directorio es fijo y se conserva: guarda las dependencias del plugin ya instaladas.
        (directorio / MARCA_CALENTADO).write_bytes(b"")
    salida = sin_ruta_personal(comun.redactar(salida))
    if rc is None and not calentado and not salida.strip():
        return comun.EnCurso(f"P5: primera ejecución de OpenCode en {directorio.name} (instala las dependencias del "
                             f"plugin) sin salida en {TIMEOUT_OPENCODE_S} s; vuelve a ejecutar --solo P5", 0)
    estado, det = evaluar(rc, salida, nonce)
    previo = comun.leer_json(ctx.dir_resultados / "P4-estado.json") or {}
    if previo.get("api_version_sin_funciona") is not None:
        det += f" | P4d: el endpoint {'SÍ' if previo['api_version_sin_funciona'] else 'NO'} responde sin api-version."
    ev = (f"Directorio de trabajo {directorio.name} bajo $TEMP (fijo, se conserva); "
          f"proveedor {PROVEEDOR} (@ai-sdk/openai) con baseURL {base_url(ctx.cfg)}; plugin con chat.headers (tenant "
          "fijo) y envoltorio de fetch que añade ?api-version=v1 solo al prefijo del hosted. "
          f"Comando: timeout {TIMEOUT_OPENCODE_S} opencode run --dir {directorio.name} -m {PROVEEDOR}/{MODELO} \"ORDEN: ECO {nonce}\".\n{det}")
    return comun.construir_resultado(ID, estado, ev, ctx.comando(ID) + f" :: {sin_ruta_personal(' '.join(cmd[1:]))}", ctx.fecha())
