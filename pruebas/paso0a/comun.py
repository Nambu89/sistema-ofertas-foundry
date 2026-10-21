"""Piezas comunes del arnés del paso 0a: resultados, progreso, contexto de ejecución y cliente HTTP con guarda.

Contrato de cada prueba (lo aplica `ejecutar.py`):
- Escribe `resultados/<id>.json` con {id, estado, evidencia, comando, fecha} y, si hace falta, `artefactos`.
- `estado` es PASA, FALLA, PENDIENTE_FERNANDO o NO_APLICA. La evidencia es un resumen literal y redactado.
- Una prueba que aún no tiene veredicto (despliegue en curso, turno largo, precondición sin cumplir) no
  escribe resultado: devuelve `EnCurso` y guarda su progreso en `resultados/<id>.progreso.json`.

Códigos de salida (el código de salida es el veredicto):
  0 PASA o NO_APLICA · 1 FALLA · 2 error de uso · 3 PENDIENTE_FERNANDO · 4 en curso (vuelve a ejecutar)
  · 5 autenticación (Fernando debe ejecutar «az login --tenant … --scope https://ai.azure.com/.default»).

Guarda del cliente HTTP (`ClientePruebas`), comprobada antes de pedir un token:
- Solo hosts de Microsoft: el del recurso (*.services.ai.azure.com), su alias *.cognitiveservices.azure.com
  (solo para Decision-1) y management.azure.com (solo GET, dentro del recurso de config/entorno.local.json).
- Lista blanca de rutas del proyecto por método. Toda ruta que escribe o que llama al endpoint de un agente
  exige un agente `ofa-prueba-` (y pasa además la guarda de lib/foundry.py: protegidos, forma y prefijo).
  `POST openai/v1/responses` lo exige en `agent_reference.name` (o `agent.name`) del cuerpo.
- Sin redirecciones y con tiempo máximo en cada petición. Nada de lo que se guarda lleva tokens.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode, urlparse

RAIZ_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))

from lib import azure_auth  # noqa: E402
from lib.config import cargar as cargar_config  # noqa: E402
from lib.foundry import OperacionNoPermitida, comprobar_nombre_escribible  # noqa: E402
from lib.redaccion import redactar, redactar_obj  # noqa: E402

AQUI = pathlib.Path(__file__).resolve().parent
DIR_RESULTADOS = AQUI / "resultados"
PYTHON_VENV = ".venv/Scripts/python.exe"

ESTADOS = ("PASA", "FALLA", "PENDIENTE_FERNANDO", "NO_APLICA")
RC_ESTADO = {"PASA": 0, "NO_APLICA": 0, "FALLA": 1, "PENDIENTE_FERNANDO": 3}
RC_USO, RC_EN_CURSO, RC_AUTENTICACION = 2, 4, 5

PREFIJO_PRUEBA = "ofa-prueba-"
AGENTE_HERRAMIENTAS = "ofa-prueba-herramientas"
AGENTE_HOSTED = "ofa-prueba-hosted"
CONEXION_MARCADOR = "ofa-prueba-marcador"
CLAVE_MARCADOR = "valor"
VALOR_MARCADOR = "marcador-sintetico"   # NO es un secreto: valor sintético acordado para la prueba
AUD_COGNITIVE = "https://cognitiveservices.azure.com"
HOST_ARM = "management.azure.com"
TIMEOUT_HTTP_S = 40.0
MAX_EVIDENCIA = 6000
MARCA_SIMULADO = "[SIMULADO: sin Azure ni red, datos sintéticos] "

_SEG = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_PRUEBA = r"ofa-prueba-[a-z0-9](?:[a-z0-9-]{0,50}[a-z0-9])?"
_VERSION = r"[A-Za-z0-9._-]{1,64}"
_RID = r"[A-Za-z0-9_-]{1,120}"

# Rutas del plano de datos del proyecto (relativas a endpoints.proyecto) admitidas por el arnés.
RUTAS_DATOS: dict[str, tuple[re.Pattern[str], ...]] = {
    "GET": (re.compile(rf"agents/{_SEG}"), re.compile(rf"agents/{_SEG}/versions/{_VERSION}"),
            re.compile(rf"agents/{_PRUEBA}/endpoint/protocols/openai/responses/{_RID}"),
            re.compile(rf"openai/v1/responses/{_RID}")),
    "POST": (re.compile(r"agents"), re.compile(rf"agents/{_PRUEBA}/versions"),
             re.compile(rf"agents/{_PRUEBA}/endpoint/protocols/openai/responses"),
             re.compile(r"openai/v1/responses")),
}


class ErrorArnes(RuntimeError):
    """Fallo del propio arnés (configuración, uso o precondición local); no es un veredicto de la prueba."""


# --------------------------------------------------------------------------------------- resultados
@dataclass
class EnCurso:
    """La prueba todavía no tiene veredicto. `espera_s` es lo que conviene esperar antes del siguiente paso."""
    mensaje: str
    espera_s: float = 0.0


def ahora_iso(reloj: Callable[[], float] = time.time) -> str:
    return dt.datetime.fromtimestamp(reloj(), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def recortar(texto: str, maximo: int = MAX_EVIDENCIA) -> str:
    """Recorta sin ocultar que se recortó."""
    return texto if len(texto) <= maximo else texto[:maximo] + f" […recortado: {len(texto) - maximo} caracteres más]"


def construir_resultado(id_prueba: str, estado: str, evidencia: str, comando: str, fecha: str,
                        artefactos: list[str] | None = None) -> dict:
    """Valida y redacta un resultado. Falla en alto con un estado o una evidencia no válidos."""
    if not re.fullmatch(r"P[0-9][a-z]?", str(id_prueba)):
        raise ErrorArnes(f"Identificador de prueba no válido: {id_prueba!r}")
    if estado not in ESTADOS:
        raise ErrorArnes(f"Estado no válido para {id_prueba}: {estado!r} (admitidos: {ESTADOS})")
    if not isinstance(evidencia, str) or not evidencia.strip():
        raise ErrorArnes(f"{id_prueba}: un resultado sin evidencia no es un resultado")
    if not isinstance(comando, str) or not comando.strip():
        raise ErrorArnes(f"{id_prueba}: falta el comando que produjo la evidencia")
    res = {"id": id_prueba, "estado": estado, "evidencia": recortar(redactar(evidencia)),
           "comando": recortar(redactar(comando), 3000), "fecha": fecha}
    if artefactos:
        res["artefactos"] = [str(a) for a in artefactos]
    return res


def escribir_json(ruta: pathlib.Path, datos: Any) -> pathlib.Path:
    """Escritura atómica en UTF-8 con LF y todo redactado (nunca se guarda un token)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(redactar_obj(datos), ensure_ascii=False, indent=1, default=str) + "\n"
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_bytes(texto.encode("utf-8"))
    tmp.replace(ruta)
    return ruta


def leer_json(ruta: pathlib.Path) -> Any:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        raise ErrorArnes(f"JSON ilegible en {ruta}: {e}") from None


def codigo_salida(estado: str) -> int:
    if estado not in RC_ESTADO:
        raise ErrorArnes(f"Estado sin código de salida: {estado!r}")
    return RC_ESTADO[estado]


def combinar_estados(estados: list[str]) -> str:
    """FALLA domina a PENDIENTE_FERNANDO, que domina a PASA; todo NO_APLICA da NO_APLICA."""
    if not estados:
        raise ErrorArnes("No hay estados que combinar")
    for e in estados:
        if e not in ESTADOS:
            raise ErrorArnes(f"Estado no válido: {e!r}")
    for candidato in ("FALLA", "PENDIENTE_FERNANDO", "PASA"):
        if candidato in estados:
            return candidato
    return "NO_APLICA"


# ------------------------------------------------------------------------------------------- HTTP
@dataclass
class RespuestaHTTP:
    """Respuesta normalizada. `estado` = -1 si no hubo respuesta (error de red o tiempo agotado)."""
    estado: int
    texto: str = ""
    cabeceras: dict = field(default_factory=dict)
    latencia_s: float = 0.0
    url: str = ""

    def json(self) -> Any:
        try:
            return json.loads(self.texto) if self.texto else None
        except ValueError:
            return None

    def resumen(self, n: int = 600) -> str:
        return f"HTTP {self.estado}: {redactar(self.texto)[:n]}"


class TransporteRequests:
    """Transporte real con requests: sin redirecciones y con tiempo máximo obligatorio."""

    def __init__(self) -> None:
        import requests  # import diferido: la simulación no lo necesita
        self._requests = requests
        self._sesion = requests.Session()

    def peticion(self, metodo: str, url: str, *, params: dict | None = None, json_body: Any = None,
                 files: Any = None, data: Any = None, cabeceras: dict | None = None,
                 timeout: float = TIMEOUT_HTTP_S, monotono: Callable[[], float] = time.monotonic) -> RespuestaHTTP:
        t0 = monotono()
        try:
            r = self._sesion.request(metodo, url, params=params, json=json_body, files=files, data=data,
                                     headers=cabeceras, timeout=timeout, allow_redirects=False)
        except self._requests.RequestException as e:
            return RespuestaHTTP(-1, f"{type(e).__name__}: {redactar(str(e))[:500]}", {},
                                 round(monotono() - t0, 3), redactar(url))
        return RespuestaHTTP(r.status_code, r.text or "", dict(r.headers), round(monotono() - t0, 3), redactar(r.url))


class ClientePruebas:
    """Cliente HTTP del arnés con guarda de hosts, rutas y nombres (ver el docstring del módulo)."""

    def __init__(self, cfg: dict, transporte: Any, tokens: Callable[[str], str],
                 monotono: Callable[[], float] = time.monotonic) -> None:
        self.cfg = cfg
        self.transporte = transporte
        self._tokens = tokens
        self._monotono = monotono
        self.llamadas: list[str] = []   # «MÉTODO url» redactadas, para el campo `comando`

    # ------------------------------------------------------------------ propiedades
    @property
    def ep_proyecto(self) -> str:
        return self.cfg["endpoints"]["proyecto"].rstrip("/")

    @property
    def ep_recurso(self) -> str:
        return self.cfg["endpoints"]["recurso"].rstrip("/")

    def hosts_decision(self) -> list[str]:
        """Endpoints del recurso para Decision-1, en orden de prueba (Learn: «<resource-endpoint>»)."""
        return [self.ep_recurso, f"https://{self.cfg['recurso']}.cognitiveservices.azure.com"]

    @property
    def base_arm(self) -> str:
        c = self.cfg
        return (f"https://{HOST_ARM}/subscriptions/{c['suscripcion_id']}/resourceGroups/{c['grupo_recursos']}"
                f"/providers/Microsoft.CognitiveServices/accounts/{c['recurso']}")

    # -------------------------------------------------------------------- guardas
    @staticmethod
    def _url_limpia(url: str, host: str) -> bool:
        u = urlparse(url)
        return (u.scheme == "https" and u.hostname == host and u.port is None
                and not u.username and not u.password and not u.query and not u.fragment)

    def comprobar_datos(self, metodo: str, ruta: str, cabeceras: dict | None = None,
                        json_body: Any = None) -> str:
        """Lista blanca del plano de datos; devuelve el agente de prueba afectado ('' si no hay)."""
        metodo = metodo.upper()
        if not any(p.fullmatch(ruta) for p in RUTAS_DATOS.get(metodo, ())):
            raise OperacionNoPermitida(f"Ruta fuera de la lista blanca del arnés: {metodo} {ruta}")
        partes = ruta.split("/")
        agente = ""
        if partes[0] == "agents":
            if len(partes) == 1:   # POST /agents: el nombre va en x-ms-agent-name (ZIP) o en el cuerpo
                de_cabecera = (cabeceras or {}).get("x-ms-agent-name")
                de_cuerpo = json_body.get("name") if isinstance(json_body, dict) else None
                if de_cabecera is not None and de_cuerpo is not None and de_cabecera != de_cuerpo:
                    raise OperacionNoPermitida("El nombre de la cabecera y el del cuerpo no coinciden")
                agente = str(de_cabecera if de_cabecera is not None else (de_cuerpo or ""))
            else:
                agente = partes[1]
        elif metodo == "POST" and ruta == "openai/v1/responses":
            # Con agent_reference (o agent) en el cuerpo se invoca cualquier agente del proyecto: el nombre
            # del cuerpo pasa la misma guarda. Sin agente, el arnés no tiene nada que llamar (falla cerrado).
            nombres = set()
            if isinstance(json_body, dict):
                for campo in ("agent_reference", "agent"):
                    ref = json_body.get(campo)
                    if ref is not None:
                        nombres.add(ref.get("name") if isinstance(ref, dict) else ref)
            if len(nombres) != 1:
                raise OperacionNoPermitida("POST openai/v1/responses exige un único agente en agent_reference.name")
            agente = nombres.pop()
            if not isinstance(agente, str):
                raise OperacionNoPermitida(f"Nombre de agente no válido en agent_reference: {agente!r}")
        escribe = metodo != "GET" or "endpoint" in partes
        if (escribe and partes[0] == "agents") or ruta == "openai/v1/responses":
            if not re.fullmatch(_PRUEBA, agente):
                raise OperacionNoPermitida(f"El arnés solo escribe o llama a agentes {PREFIJO_PRUEBA}: {agente!r}")
            comprobar_nombre_escribible(agente, self.cfg)
        return agente

    # ------------------------------------------------------------------- peticiones
    def _enviar(self, metodo: str, url: str, audiencia: str, *, params: dict | None = None,
                json_body: Any = None, files: Any = None, cabeceras: dict | None = None,
                timeout: float = TIMEOUT_HTTP_S) -> RespuestaHTTP:
        cab = {"Accept": "application/json", **(cabeceras or {})}
        cab["Authorization"] = "Bearer " + self._tokens(audiencia)
        visible = url + ("?" + urlencode(params) if params else "")
        self.llamadas.append(f"{metodo} {redactar(visible)}")
        return self.transporte.peticion(metodo, url, params=params, json_body=json_body, files=files,
                                        cabeceras=cab, timeout=timeout)

    def params_datos(self, ruta: str, params: dict | None) -> dict | None:
        """La gestión de agentes (`agents`, `agents/{n}`, `…/versions…`) exige `api-version`; se pone la de la
        configuración salvo que la llamada traiga la suya. Comprobado contra Azure el 18-10-2026: sin ella, HTTP
        400 «Missing required query parameter: api-version». No se toca `openai/v1/…` (LES-G-014) ni el
        endpoint del hosted (`…/endpoint/protocols/…`), donde P4d mide a propósito la llamada sin parámetro."""
        partes = ruta.strip("/").split("/")
        if partes[0] != "agents" or "endpoint" in partes or "api-version" in (params or {}):
            return params
        return {"api-version": self.cfg["api_versions"]["datos_proyecto"], **(params or {})}

    def datos(self, metodo: str, ruta: str, *, params: dict | None = None, json_body: Any = None,
              files: Any = None, cabeceras: dict | None = None, timeout: float = TIMEOUT_HTTP_S) -> RespuestaHTTP:
        """Petición al proyecto (audiencia https://ai.azure.com). La guarda va antes del token."""
        ruta = ruta.strip("/")
        self.comprobar_datos(metodo, ruta, cabeceras, json_body)
        url = f"{self.ep_proyecto}/{ruta}"
        host = urlparse(self.ep_recurso).hostname or ""
        if not host.endswith(".services.ai.azure.com") or not self._url_limpia(url, host):
            raise OperacionNoPermitida(f"Destino no autorizado: {url}")
        params = self.params_datos(ruta, params)
        return self._enviar(metodo.upper(), url, azure_auth.AUD_DATOS, params=params, json_body=json_body,
                            files=files, cabeceras=cabeceras, timeout=timeout)

    def arm_get(self, sufijo: str, api_version: str, timeout: float = TIMEOUT_HTTP_S) -> RespuestaHTTP:
        """GET de ARM dentro del recurso de la configuración (solo lectura)."""
        if not re.fullmatch(r"(/[A-Za-z0-9._-]+)*", sufijo) or ".." in sufijo:
            raise OperacionNoPermitida(f"Sufijo ARM no admitido: {sufijo!r}")
        url = self.base_arm + sufijo
        if not self._url_limpia(url, HOST_ARM):
            raise OperacionNoPermitida(f"Destino ARM no autorizado: {url}")
        return self._enviar("GET", url, azure_auth.AUD_ARM, params={"api-version": api_version}, timeout=timeout)

    def arm_get_siguiente(self, next_link: str, timeout: float = TIMEOUT_HTTP_S) -> RespuestaHTTP:
        """Sigue un nextLink de ARM solo si apunta al mismo recurso y host."""
        u = urlparse(next_link)
        if u.scheme != "https" or u.hostname != HOST_ARM or not (u.path + "/").lower().startswith(
                urlparse(self.base_arm).path.lower() + "/") or u.port is not None:
            raise OperacionNoPermitida(f"nextLink fuera del recurso: {redactar(next_link)}")
        self.llamadas.append(f"GET {redactar(next_link)}")
        cab = {"Accept": "application/json", "Authorization": "Bearer " + self._tokens(azure_auth.AUD_ARM)}
        return self.transporte.peticion("GET", next_link, cabeceras=cab, timeout=timeout)

    def decision(self, base: str, cuerpo: dict, timeout: float = TIMEOUT_HTTP_S) -> RespuestaHTTP:
        """POST {endpoint del recurso}/providers/microsoft/v1/systemone (audiencia cognitiveservices)."""
        if base not in self.hosts_decision():
            raise OperacionNoPermitida(f"Endpoint de Decision-1 no autorizado: {base}")
        url = base + "/providers/microsoft/v1/systemone"
        host = urlparse(base).hostname or ""
        if not self._url_limpia(url, host):
            raise OperacionNoPermitida(f"Destino no autorizado: {url}")
        return self._enviar("POST", url, AUD_COGNITIVE, json_body=cuerpo,
                            cabeceras={"Content-Type": "application/json"}, timeout=timeout)


# ----------------------------------------------------------------------------------------- contexto
@dataclass
class Contexto:
    """Todo lo que una prueba necesita del exterior; la simulación sustituye cada pieza."""
    cfg: dict
    cliente: ClientePruebas
    dir_resultados: pathlib.Path
    dir_progreso: pathlib.Path
    reloj: Callable[[], float] = time.time
    monotono: Callable[[], float] = time.monotonic
    dormir: Callable[[float], None] = time.sleep
    proceso: Callable[..., Any] | None = None       # subprocess.run o un doble
    simulado: bool = False
    presupuesto_s: float = 80.0
    inicio: float = 0.0
    escribir: Callable[[str], None] = print
    opciones: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.inicio:
            self.inicio = self.monotono()

    def restante(self) -> float:
        return self.presupuesto_s - (self.monotono() - self.inicio)

    def hoy(self) -> dt.date:
        return dt.datetime.fromtimestamp(self.reloj(), dt.timezone.utc).date()

    def fecha(self) -> str:
        return ahora_iso(self.reloj)

    def marcar(self, evidencia: str) -> str:
        """En simulación, la evidencia lo dice delante para que nadie la tome por una prueba real."""
        return (MARCA_SIMULADO + evidencia) if self.simulado and not evidencia.startswith(MARCA_SIMULADO) else evidencia

    # ----------------------------------------------------------------- progreso
    def ruta_progreso(self, id_prueba: str) -> pathlib.Path:
        return self.dir_progreso / f"{id_prueba}.progreso.json"

    def leer_progreso(self, id_prueba: str) -> dict:
        return leer_json(self.ruta_progreso(id_prueba)) or {}

    def guardar_progreso(self, id_prueba: str, progreso: dict) -> None:
        escribir_json(self.ruta_progreso(id_prueba), progreso)

    def borrar_progreso(self, id_prueba: str) -> None:
        self.ruta_progreso(id_prueba).unlink(missing_ok=True)

    def comando(self, id_prueba: str, extra: str = "", llamadas: list[str] | None = None) -> str:
        """Comando reproducible del arnés más las llamadas HTTP que produjeron la evidencia.

        Sin `llamadas`, las de esta invocación. Una prueba que dura varias invocaciones pasa las que acumuló en
        su progreso, para que el comando no sea solo el último sondeo."""
        base = f"{PYTHON_VENV} pruebas/paso0a/ejecutar.py --solo {id_prueba}{extra}"
        if self.simulado:
            base += " --simular"
        texto = resumir_llamadas(self.cliente.llamadas if llamadas is None else llamadas)
        return base + (f" :: {texto}" if texto else "")

    def nuevas_llamadas(self, progreso: dict, clave: str) -> None:
        """Pasa a `progreso['llamadas'][clave]` las llamadas hechas desde `progreso['_marca']` y mueve la marca."""
        marca = int(progreso.get("_marca", 0))
        nuevas = self.cliente.llamadas[marca:]
        if nuevas:
            progreso.setdefault("llamadas", {}).setdefault(clave, []).extend(nuevas)
        progreso["_marca"] = len(self.cliente.llamadas)


def resumir_llamadas(llamadas: list[str]) -> str:
    """«MÉTODO url» en orden de primera aparición, con «(×N)» si se repitió (los sondeos)."""
    cuenta: dict[str, int] = {}
    for c in llamadas:
        cuenta[c] = cuenta.get(c, 0) + 1
    return "; ".join(c + (f" (×{n})" if n > 1 else "") for c, n in cuenta.items())


def contexto_real(presupuesto_s: float = 80.0, opciones: dict | None = None) -> Contexto:
    """Contexto contra Azure con el token de Fernando (az CLI, tenant fijo, LES-G-052)."""
    import subprocess
    cfg = cargar_config()
    gestor = azure_auth.GestorTokens(tenant=cfg["tenant_id"])
    cliente = ClientePruebas(cfg, TransporteRequests(), gestor.token)
    return Contexto(cfg=cfg, cliente=cliente, dir_resultados=DIR_RESULTADOS, dir_progreso=DIR_RESULTADOS,
                    proceso=subprocess.run, presupuesto_s=presupuesto_s, opciones=dict(opciones or {}))


def directorio_temporal(prefijo: str) -> pathlib.Path:
    """Directorio nuevo y vacío bajo $TEMP (nunca dentro del repositorio ni de la carpeta Proyectos)."""
    base = os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir()
    return pathlib.Path(tempfile.mkdtemp(prefix=prefijo, dir=base))


def texto_salida(respuesta: dict | None) -> str:
    """Concatena los output_text de los mensajes de una respuesta de Responses."""
    if not isinstance(respuesta, dict):
        return ""
    trozos = []
    for item in respuesta.get("output") or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for c in item.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "output_text":
                    trozos.append(str(c.get("text", "")))
    return "\n".join(trozos)


TERMINALES = {"completed", "failed", "cancelled", "incomplete"}
