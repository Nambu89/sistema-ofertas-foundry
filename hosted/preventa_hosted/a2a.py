"""Cliente A2A JSON-RPC v1.0 (SendMessage y GetTask, cabecera A2A-Version: 1.0).

Envía EXACTAMENTE el texto que le dan (sin tocarlo), con el token de la identidad del propio
hosted agent (scope https://ai.azure.com/.default), un timeout por PETICIÓN HTTP y
una procedencia por llamada: url, método, task_id, context_id, estado, latencia, HTTP, SHA-256 del
texto enviado y del recibido, y el MOTIVO literal de cualquier error (nada de 424 opacos).
Forma de las peticiones y respuestas tomada de evidencias reales (pruebas/I0/B5/j_gettask_*.json y
pruebas/I1/CONTRATO/intento1/a2a_experto.json).

PR17-2 (I1.7): el envío es NO BLOQUEANTE (`configuration.returnImmediately: true`, A2A 1.0) y la respuesta se recoge
sondeando GetTask hasta un estado terminal, con una espera propia por tarea (no por petición). Comprobado contra el
endpoint real el 13-10-2026 (pruebas/I17/ARREGLOS/sonda_a2a_verificador.json: SendMessage en 1,5 s con
TASK_STATE_SUBMITTED y GetTask COMPLETED a los 10 s). Con el tope síncrono de 110 s se perdían respuestas que Foundry
sí terminaba y cobraba (VER17-4); si el servidor ignora la opción y responde ya terminada, se usa tal cual.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

import httpx

ESTADOS_FINALES = {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}
# PR17-2 (I1.7): estados en los que la tarea ya no avanza sola (A2A 1.0: «interrupted»): se tratan como terminales.
ESTADOS_INTERRUMPIDOS = {"TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"}
MAX_ERRORES_SONDEO = 5      # errores SEGUIDOS de GetTask durante la espera antes de dejar la tarea pendiente
# REVERIF17-1 (I1.8): A2A 1.0 TaskNotFoundError. Foundry lo devuelve para un task_id bien formado que no existe o que la
# identidad no puede leer (pruebas/I13/E2E-B/procedencia_gettask.json: -32001, reason TASK_NOT_FOUND). Es permanente: la
# tarea no se puede recoger. Se exige en NO_ENCONTRADA_SEGUIDOS sondeos seguidos (5 s entre ellos) para no tomar por
# perdida una tarea recién creada que aún no fuese visible. Un id mal formado da -32603 («Received 400»,
# pruebas/I18/R/sonda_a2a_idempotencia.json): eso no se clasifica como perdida (sigue siendo un fallo de lectura).
TAREA_NO_ENCONTRADA = -32001
NO_ENCONTRADA_SEGUIDOS = 2
# VPROT-3 (I1.9): -32001 TASK_NOT_FOUND también significa «no accesible para esta identidad» (lo vio el verificador de
# protocolo con su identidad sobre una tarea viva de B). Antes de dar la tarea por perdida, el código contrasta la
# identidad del token del sondeo con la que creó la tarea (claim «oid», guardado en a2a.jsonl). Solo si son la misma la
# tarea se da por perdida y SIGUE la reenvía; si no constan o no coinciden, queda pendiente y NO se reenvía (se pagaría
# dos veces una tarea viva): lo decide el comercial.
TOPE_SONDEO_S = 30.0        # Revisión (arreglos I1.7): un GetTask de sondeo no puede alargar la espera más de esto


def identidad_de_token(token: object) -> str | None:
    """VPROT-3: «oid» del JWT (o «sub» si no lo trae), leído sin verificar la firma: solo sirve para contrastar que el
    sondeo va con la misma identidad que creó la tarea. None si no se puede leer. El token nunca se guarda ni se imprime."""
    try:
        carga = str(token).split(".")[1]
        datos = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))
        valor = datos.get("oid") or datos.get("sub")
    except Exception:  # noqa: BLE001 - un token que no es un JWT legible no tiene identidad que contrastar
        return None
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def sha256_fichero(ruta) -> str:
    """SHA-256 de un fichero, leído por bloques (la línea PAQUETE lo contrasta con el del estado)."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


@dataclasses.dataclass
class Llamada:
    """Procedencia de UNA llamada A2A (se guarda tal cual en procedencia/a2a.jsonl)."""
    agente: str
    url: str
    metodo: str
    inicio: str
    jsonrpc_id: str
    sha256_enviado: str | None = None
    bytes_enviado: int | None = None
    http: int | None = None
    latencia_s: float | None = None
    task_id: str | None = None
    context_id: str | None = None
    estado_tarea: str | None = None
    sha256_recibido: str | None = None
    bytes_recibido: int | None = None
    error: str | None = None          # motivo literal (HTTP, JSON-RPC, timeout, red, tarea fallida)
    # PR17-2 (I1.7): SendMessage no bloqueante y sondeo con GetTask hasta un estado terminal.
    modo: str | None = None           # «no_bloqueante» en los envíos; None en las relecturas
    sondeos: int = 0                  # GetTask hechos mientras la tarea seguía en curso
    errores_sondeo: int = 0           # GetTask fallidos durante la espera (red o plataforma), en total
    pendiente: bool = False           # la tarea seguía viva al dejar de esperar: se puede recoger por su task_id
    recuperada: bool = False          # recogió una tarea pendiente de un turno anterior, sin reenviar nada
    # REVERIF17-1 (I1.8): GetTask ya no encuentra la tarea (-32001): no se puede recoger; SIGUE reenvía el texto.
    perdida: bool = False
    codigo_jsonrpc: int | None = None # código del error JSON-RPC, si lo hubo (se clasifica por él, LES-G-048 c)
    reenvio_de: str | None = None     # task_id de la tarea perdida a la que sustituye este envío
    motivo_reenvio: str | None = None # motivo literal por el que se dio por perdida
    # VPROT-3 (I1.9): identidad («oid» del token con que fue la petición; en un envío, la que creó la tarea; en una tarea
    # recogida, la del registro del envío original) y la del GetTask que devolvió el segundo -32001
    identidad: str | None = None
    identidad_sondeo: str | None = None
    texto: str = dataclasses.field(default="", repr=False)

    @property
    def ok(self) -> bool:
        return self.error is None and self.estado_tarea == "TASK_STATE_COMPLETED" and bool(self.texto)

    def registro(self) -> dict:
        d = dataclasses.asdict(self)
        d.pop("texto")
        return d


def texto_de_resultado(res: dict) -> tuple[str, dict]:
    """Texto (artifacts, status.message o message) e ids de un `result` A2A v1.0."""
    tarea = res.get("task") or (res if res.get("status") else None)
    msg = res.get("message")
    partes: list[str] = []
    ids: dict = {}
    if tarea:
        ids = {"task_id": tarea.get("id"), "context_id": tarea.get("contextId"),
               "estado": (tarea.get("status") or {}).get("state")}
        for art in tarea.get("artifacts") or []:
            partes += [p["text"] for p in art.get("parts") or [] if isinstance(p.get("text"), str)]
        if not partes:
            sm = (tarea.get("status") or {}).get("message") or {}
            partes += [p["text"] for p in sm.get("parts") or [] if isinstance(p.get("text"), str)]
    if msg:
        ids.setdefault("task_id", msg.get("taskId"))
        ids["context_id"] = ids.get("context_id") or msg.get("contextId")
        ids.setdefault("estado", "TASK_STATE_COMPLETED")
        partes += [p["text"] for p in msg.get("parts") or [] if isinstance(p.get("text"), str)]
    return "".join(partes), ids


def pista_permiso(error: object) -> str:
    """AGENT_NOT_FOUND con la identidad del hosted agent suele ser un permiso disfrazado: el mismo agente responde
    con el token del comercial (integración I1.1, 08-10-2026). Se añade como hipótesis, sin tocar el motivo literal."""
    razones = [d.get("reason") for d in (error.get("data") or []) if isinstance(d, dict)] if isinstance(error, dict) else []
    if "AGENT_NOT_FOUND" not in razones:
        return ""
    return (" · PISTA (hipótesis): si el agente existe, a la identidad de este hosted agent probablemente le falta el "
            "rol Foundry Agent Consumer sobre el agente destino (lo asigna el comercial con agentes/asignar_roles_hosted.sh)")


class ClienteA2A:
    def __init__(self, url_de: Callable[[str], str], token: Callable[[], str], timeout_s: float,
                 transporte: httpx.BaseTransport | None = None, espera_s: float = 420.0, sondeo_s: float = 5.0,
                 dormir: Callable[[float], None] = time.sleep, reloj: Callable[[], float] = time.monotonic):
        """`timeout_s`: por petición HTTP. `espera_s`: lo que se espera a UNA tarea en curso, sondeando cada
        `sondeo_s` (PR17-2). `cancelado()` lo fija el turno: si el cliente cancela, se deja de esperar y la tarea queda
        pendiente (se recoge en el turno siguiente por su task_id, sin reenviar)."""
        self._url_de, self._token, self._timeout = url_de, token, timeout_s
        self._transporte = transporte
        self._espera, self._sondeo, self._dormir, self._reloj = espera_s, sondeo_s, dormir, reloj
        self.cancelado: Callable[[], bool] = lambda: False

    def _rpc(self, agente: str, metodo: str, params: dict, ll: Llamada, timeout: float | None = None) -> dict | None:
        cuerpo = {"jsonrpc": "2.0", "id": ll.jsonrpc_id, "method": metodo, "params": params}
        tope = timeout or self._timeout
        t0 = time.monotonic()
        try:
            token = self._token()
            ll.identidad = identidad_de_token(token)   # VPROT-3 (I1.9): la del token con que va ESTA petición
            cabeceras = {"Authorization": f"Bearer {token}", "A2A-Version": "1.0",
                         "Content-Type": "application/json"}
            with httpx.Client(timeout=tope, transport=self._transporte) as c:
                r = c.post(ll.url, json=cuerpo, headers=cabeceras)
        except httpx.TimeoutException as exc:
            ll.error = f"timeout A2A a los {tope:.0f} s ({type(exc).__name__}) sin respuesta de {agente}"
            return None
        except Exception as exc:  # red, DNS o credencial: motivo literal, sin secretos
            ll.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            return None
        finally:
            ll.latencia_s = round(time.monotonic() - t0, 1)
        ll.http = r.status_code
        if r.status_code != 200:
            ll.error = f"HTTP {r.status_code}: {r.text[:1500]}"
            return None
        try:
            j = r.json()
        except ValueError:
            ll.error = f"HTTP 200 con cuerpo que no es JSON: {r.text[:500]}"
            return None
        if j.get("error"):
            codigo = j["error"].get("code") if isinstance(j["error"], dict) else None
            ll.codigo_jsonrpc = codigo if type(codigo) is int else None
            ll.error = f"JSON-RPC {json.dumps(j['error'], ensure_ascii=False)[:1500]}" + pista_permiso(j["error"])
            return None
        return j.get("result") or {}

    def _cerrar(self, ll: Llamada, res: dict | None) -> Llamada:
        if res is None:
            return ll
        texto, ids = texto_de_resultado(res)
        ll.task_id, ll.context_id, ll.estado_tarea = ids.get("task_id"), ids.get("context_id"), ids.get("estado")
        ll.texto = texto
        ll.sha256_recibido, ll.bytes_recibido = sha256(texto), len(texto.encode("utf-8"))
        if ll.estado_tarea not in (None, "TASK_STATE_COMPLETED"):
            ll.error = f"la tarea {ll.task_id} terminó en {ll.estado_tarea}: {texto[:1000]}"
        elif not texto:
            ll.error = f"respuesta sin texto (tarea {ll.task_id}, estado {ll.estado_tarea})"
        return ll

    def _nueva(self, agente: str, metodo: str) -> Llamada:
        return Llamada(agente=agente, url=self._url_de(agente), metodo=metodo,
                       inicio=datetime.now(timezone.utc).isoformat(timespec="seconds"), jsonrpc_id=str(uuid.uuid4()))

    def enviar(self, agente: str, texto: str) -> Llamada:
        """SendMessage NO bloqueante con el texto EXACTO (una sola parte de texto, sin saludo ni contexto) y espera de la
        tarea con GetTask. Si el servidor responde ya con la tarea terminada (o con un mensaje), se usa tal cual."""
        ll = self._nueva(agente, "SendMessage")
        ll.modo = "no_bloqueante"
        ll.sha256_enviado, ll.bytes_enviado = sha256(texto), len(texto.encode("utf-8"))
        params = {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": texto}]},
                  "configuration": {"returnImmediately": True}}
        t0 = self._reloj()
        res = self._rpc(agente, "SendMessage", params, ll)
        if res is None:
            return ll
        _, ids = texto_de_resultado(res)   # un `message` directo llega como COMPLETED (texto_de_resultado)
        ll.task_id, ll.context_id, ll.estado_tarea = ids.get("task_id"), ids.get("context_id"), ids.get("estado")
        if ll.estado_tarea in ESTADOS_FINALES | ESTADOS_INTERRUMPIDOS:
            return self._cerrar(ll, res)
        if not ll.task_id:
            ll.error = f"SendMessage no bloqueante sin task_id ni tarea terminada (estado {ll.estado_tarea}): no se puede esperar"
            return ll
        return self._esperar(agente, ll, t0)

    def recuperar(self, agente: str, task_id: str, previa: dict) -> Llamada:
        """Recoge una tarea PENDIENTE de un turno anterior (mismo envío: `previa` es su registro de a2a.jsonl), sin
        reenviar nada. La procedencia conserva la hora y la huella de lo que se envió entonces."""
        ll = self._nueva(agente, "SendMessage")
        ll.modo, ll.recuperada, ll.task_id = "no_bloqueante", True, task_id
        ll.inicio = str(previa.get("inicio") or ll.inicio)
        ll.context_id = previa.get("context_id")
        ll.sha256_enviado, ll.bytes_enviado = previa.get("sha256_enviado"), previa.get("bytes_enviado")
        ll.identidad = previa.get("identidad") if isinstance(previa.get("identidad"), str) else None  # VPROT-3
        return self._esperar(agente, ll, self._reloj())

    def _esperar(self, agente: str, ll: Llamada, t0: float) -> Llamada:
        """Sondea GetTask hasta un estado terminal. Un GetTask fallido es una LECTURA que se repite en el siguiente
        sondeo (se cuenta y se dice); tras MAX_ERRORES_SONDEO seguidos, o al agotar la espera o si el cliente cancela,
        la tarea queda PENDIENTE con su task_id y el motivo literal (nunca en silencio)."""
        seguidos, ultimo, no_encontrada = 0, None, 0
        while True:
            if self.cancelado():
                ll.pendiente = True
                ll.error = (f"tarea {ll.task_id} pendiente en {agente} (estado {ll.estado_tarea}): el cliente canceló el "
                            "turno; se recoge por su task_id con SIGUE, sin reenviar")
                break
            queda = self._espera - (self._reloj() - t0)
            if queda <= 0:
                ll.pendiente = True
                ll.error = (f"tarea {ll.task_id} pendiente en {agente}: sigue en {ll.estado_tarea} tras "
                            f"{self._espera:.0f} s de espera ({ll.sondeos} sondeos, {ll.errores_sondeo} con error"
                            + (f"; último: {ultimo}" if ultimo else "") + "); se recoge por su task_id con SIGUE")
                break
            self._dormir(min(self._sondeo, queda))   # Revisión: no se duerme más allá del final de la espera
            if self.cancelado():
                continue                              # la cancelación se atiende arriba, antes de otro GetTask
            g = self._nueva(agente, "GetTask")
            res = self._rpc(agente, "GetTask", {"id": ll.task_id, "historyLength": 0}, g,
                            timeout=min(self._timeout, TOPE_SONDEO_S))
            ll.sondeos += 1
            if res is not None and texto_de_resultado(res)[1].get("task_id") is None:
                # REVERIF17-6 (I1.8): una respuesta de sondeo sin id de tarea no se acepta como la propia: es una lectura
                # fallida (se repite en el siguiente sondeo y cuenta para MAX_ERRORES_SONDEO)
                g.error, res = f"GetTask de {ll.task_id} respondió sin id de tarea: no se acepta como la tarea propia", None
            if res is None:
                ll.errores_sondeo, seguidos, ultimo = ll.errores_sondeo + 1, seguidos + 1, g.error
                no_encontrada = no_encontrada + 1 if g.codigo_jsonrpc == TAREA_NO_ENCONTRADA else 0
                if no_encontrada >= NO_ENCONTRADA_SEGUIDOS:
                    actual = g.identidad   # la del token del GetTask que devolvió este -32001 (Revisión 1)
                    ll.codigo_jsonrpc, ll.identidad_sondeo = TAREA_NO_ENCONTRADA, actual
                    if ll.identidad and actual and ll.identidad == actual:
                        ll.perdida, ll.pendiente = True, False
                        ll.error = (f"tarea {ll.task_id} perdida en {agente}: GetTask respondió JSON-RPC "
                                    f"{TAREA_NO_ENCONTRADA} (la tarea no existe o ya no es accesible: caducada o purgada) "
                                    f"en {no_encontrada} sondeos seguidos con la misma identidad que la creó "
                                    f"({actual}); no se puede recoger y con SIGUE se reenvía el texto. Respuesta literal: "
                                    f"{g.error}")
                    else:
                        ll.perdida, ll.pendiente = False, True
                        ll.error = (f"tarea {ll.task_id} NO ACCESIBLE en {agente}: GetTask respondió JSON-RPC "
                                    f"{TAREA_NO_ENCONTRADA} en {no_encontrada} sondeos seguidos, pero la identidad con "
                                    f"que se creó ({ll.identidad or 'no consta'}) no es la del sondeo "
                                    f"({actual or 'no se puede leer'}). -32001 también significa «no accesible para esta "
                                    "identidad» (VPROT-3): no se da por perdida ni se reenvía, porque se pagaría dos veces "
                                    "una tarea viva. Decide el comercial: volver a la identidad que la creó o abrir una sesión "
                                    f"nueva. Respuesta literal: {g.error}")
                    break
                if seguidos >= MAX_ERRORES_SONDEO:
                    ll.pendiente = True
                    ll.error = (f"tarea {ll.task_id} pendiente en {agente}: {seguidos} GetTask seguidos fallaron "
                                f"(último: {ultimo}); se recoge por su task_id con SIGUE")
                    break
                continue
            seguidos, no_encontrada = 0, 0   # una lectura buena corta la racha (también la de -32001)
            ll.http = g.http
            _, ids = texto_de_resultado(res)
            if ids.get("task_id") != ll.task_id:
                # Revisión (arreglos I1.7): la tarea propia sigue viva y sin leer: queda pendiente (se recoge por su task_id
                # con SIGUE) en vez de reenviar el texto y pagar otra ejecución
                ll.pendiente = True
                ll.error = (f"GetTask de {ll.task_id} devolvió otra tarea ({ids.get('task_id')}): no se usa; la tarea "
                            "queda pendiente y se recoge por su task_id con SIGUE")
                break
            ll.context_id = ids.get("context_id") or ll.context_id
            ll.estado_tarea = ids.get("estado") or ll.estado_tarea
            if ll.estado_tarea in ESTADOS_FINALES | ESTADOS_INTERRUMPIDOS:
                task_id = ll.task_id
                self._cerrar(ll, res)
                ll.task_id = ll.task_id or task_id
                break
        ll.latencia_s = round(self._reloj() - t0, 1)
        return ll

    def tarea(self, agente: str, task_id: str) -> Llamada:
        """GetTask (en v1.0 no existe tasks/get) para releer una tarea y su procedencia. REVERIF17-6 (I1.8): una respuesta
        sin el id pedido (ausente u otro) no es la relectura de esa tarea: queda con error (la puerta: NO VERIFICADO)."""
        ll = self._nueva(agente, "GetTask")
        self._cerrar(ll, self._rpc(agente, "GetTask", {"id": task_id, "historyLength": 10}, ll))
        if ll.error is None and ll.task_id != task_id:
            ll.error = f"la relectura GetTask de {task_id} devolvió la tarea {ll.task_id!r}: no es la pedida"
        return ll
