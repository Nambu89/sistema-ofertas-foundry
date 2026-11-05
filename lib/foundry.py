"""Cliente REST mínimo del proyecto Foundry proyecto-ejemplo y de las piezas ARM que usa I0.

Plano de datos (audiencia https://ai.azure.com, api-version=v1): agentes y versiones,
ficheros (purpose=assistants), Responses API con agent_reference, contenedores y descarga.
ARM (audiencia https://management.azure.com): conexiones del proyecto y asignaciones de rol.

Reglas: solo reintenta ante 429 y 5xx (máximo 3 intentos, cada uno anotado en
`self.registro` y en stderr); nunca escribe ni imprime tokens; se niega a escribir sobre
agentes protegidos o sin el prefijo preventa-, y solo borra agentes preventa-prueba-.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from lib import azure_auth
from lib.config import cargar as cargar_config

REINTENTABLES = {429, 500, 502, 503, 504}
MAX_INTENTOS = 3


class ErrorFoundry(RuntimeError):
    """Respuesta HTTP no esperada; incluye método, URL sin secretos, estado y cuerpo recortado."""

    def __init__(self, metodo: str, url: str, estado: int, cuerpo: str):
        self.metodo, self.url, self.estado, self.cuerpo = metodo, url, estado, cuerpo
        super().__init__(f"{metodo} {url} -> HTTP {estado}: {cuerpo[:1500]}")


class OperacionNoPermitida(PermissionError):
    """La operación tocaría un recurso que I0 no puede modificar."""


@dataclass
class Intento:
    """Anotación de un intento fallido reintentable (P-6: nada de reintentos silenciosos)."""
    metodo: str
    url: str
    estado: int | None
    error: str
    espera_s: float


@dataclass
class ClienteFoundry:
    """Cliente del proyecto. `cfg` es el diccionario de config/entorno.local.json."""
    cfg: dict = field(default_factory=cargar_config)
    timeout_s: float = 300.0
    registro: list[Intento] = field(default_factory=list)
    _sesion: requests.Session = field(default_factory=requests.Session, repr=False)

    # ------------------------------------------------------------------ utilidades
    @property
    def ep_proyecto(self) -> str:
        return self.cfg["endpoints"]["proyecto"].rstrip("/")

    @property
    def ep_recurso(self) -> str:
        return self.cfg["endpoints"]["recurso"].rstrip("/")

    @property
    def id_arm_cuenta(self) -> str:
        c = self.cfg
        return (f"/subscriptions/{c['suscripcion_id']}/resourceGroups/{c['grupo_recursos']}"
                f"/providers/Microsoft.CognitiveServices/accounts/{c['recurso']}")

    @property
    def id_arm_proyecto(self) -> str:
        return f"{self.id_arm_cuenta}/projects/{self.cfg['proyecto']}"

    def _tok_datos(self) -> str:
        return azure_auth.obtener_token(azure_auth.AUD_DATOS, self.cfg["tenant_id"])

    def _tok_arm(self) -> str:
        return azure_auth.obtener_token(azure_auth.AUD_ARM, self.cfg["tenant_id"])

    def _peticion(self, metodo: str, url: str, token_fn: Callable[[], str], *,
                  params: dict | None = None, json_body: Any = None,
                  files: dict | None = None, data: dict | None = None,
                  cabeceras: dict | None = None, esperado: tuple[int, ...] = (200,),
                  crudo: bool = False, idempotente: bool | None = None) -> Any:
        """Ejecuta la petición; reintenta solo ante 429/5xx o fallo de red, anotando cada intento.

        El 429 siempre se reintenta (la petición no se procesó). Los 5xx y los fallos de red
        solo si la operación es idempotente (GET/PUT/PATCH/DELETE por defecto; POST no),
        para no duplicar versiones de agente ni respuestas.
        """
        if idempotente is None:
            idempotente = metodo.upper() != "POST"
        host = (urlparse(url).hostname or "") if urlparse(url).scheme == "https" else ""
        permitidos = {urlparse(self.ep_recurso).hostname, urlparse(self.ep_proyecto).hostname,
                      urlparse(self.cfg["endpoints"]["arm"]).hostname}
        if host not in permitidos:
            raise OperacionNoPermitida(f"Destino no autorizado para enviar un token: {url}")
        ultimo: Exception | None = None
        for n in range(1, MAX_INTENTOS + 1):
            h = {"Authorization": "Bearer " + token_fn(), "Accept": "*/*" if crudo else "application/json"}
            h.update(cabeceras or {})
            try:
                r = self._sesion.request(metodo, url, params=params, json=json_body, files=files,
                                         data=data, headers=h, timeout=self.timeout_s)
            except requests.RequestException as e:
                ultimo = e
                # Si la conexión ni siquiera se abrió (DNS, conexión rechazada) la petición no
                # salió, así que también se puede repetir un POST sin riesgo de duplicar.
                no_enviada = isinstance(e, requests.ConnectionError) and any(
                    m in str(e) for m in ("NameResolutionError", "NewConnectionError"))
                if not (idempotente or no_enviada) or n == MAX_INTENTOS:
                    raise ErrorFoundry(metodo, url, -1, f"{type(e).__name__}: {e}"[:500]) from None
                self._anotar(metodo, url, None, f"{type(e).__name__}: {e}"[:500], n)
                continue
            if r.status_code in esperado:
                if crudo:
                    return r.content
                return r.json() if r.content else None
            cuerpo = r.text[:2000]
            reintentable = r.status_code == 429 or (idempotente and r.status_code in REINTENTABLES)
            if reintentable and n < MAX_INTENTOS:
                self._anotar(metodo, url, r.status_code, cuerpo, n, r.headers.get("Retry-After"))
                continue
            raise ErrorFoundry(metodo, url, r.status_code, cuerpo)
        raise ErrorFoundry(metodo, url, -1, f"Sin respuesta tras {MAX_INTENTOS} intentos: {ultimo}")

    def _anotar(self, metodo: str, url: str, estado: int | None, error: str, n: int,
                retry_after: str | None = None) -> None:
        """Registra el intento fallido y espera (Retry-After si viene, si no 2^n s; tope 60 s)."""
        try:
            espera = min(float(retry_after), 60.0) if retry_after else float(2 ** n)
        except ValueError:
            espera = float(2 ** n)
        self.registro.append(Intento(metodo, url, estado, error, espera))
        sys.stderr.write(f"[reintento {n}/{MAX_INTENTOS}] {metodo} {url} -> {estado}: "
                         f"{error[:300]} (espera {espera:.0f} s)\n")
        time.sleep(espera)

    # ------------------------------------------------------------- plano de datos
    def _url(self, ruta: str) -> str:
        return f"{self.ep_proyecto}/{ruta.lstrip('/')}"

    def _datos(self, metodo: str, ruta: str, *, params: dict | None = None,
               preview: bool = False, **kw) -> Any:
        """Petición al plano de datos del proyecto con api-version=v1."""
        p = {"api-version": self.cfg["api_versions"]["datos_proyecto"]}
        p.update(params or {})
        cab = kw.pop("cabeceras", {}) or {}
        if preview:
            cab["Foundry-Features"] = self.cfg.get("foundry_features", "")
        return self._peticion(metodo, self._url(ruta), self._tok_datos, params=p,
                              cabeceras=cab, **kw)

    def _openai(self, metodo: str, ruta: str, **kw) -> Any:
        """Petición a la superficie OpenAI v1 del proyecto (sin api-version, LES-G-014)."""
        return self._peticion(metodo, self._url("openai/v1/" + ruta.lstrip("/")),
                              self._tok_datos, **kw)

    def _paginar(self, pedir: Callable[[dict | None], Any], url: str,
                 max_paginas: int = 50) -> list[dict]:
        """Sigue data + has_more/last_id con `after`. Falla en alto si la lista quedaría truncada."""
        items: list[dict] = []
        after = None
        for _ in range(max_paginas):
            j = pedir({"after": after} if after else None)
            datos = j.get("data", j.get("value", [])) if isinstance(j, dict) else []
            items += datos
            if not (isinstance(j, dict) and j.get("has_more")):
                return items
            if not datos:
                raise ErrorFoundry("GET", url, 200, "has_more sin datos: lista truncada")
            nuevo = j.get("last_id") or datos[-1].get("id") or datos[-1].get("name")
            if not nuevo or nuevo == after:
                raise ErrorFoundry("GET", url, 200, "Paginación sin cursor válido")
            after = nuevo
        raise ErrorFoundry("GET", url, 200, f"Más de {max_paginas} páginas: lista truncada")

    def listar(self, ruta: str, preview: bool = False, max_paginas: int = 50) -> list[dict]:
        """GET paginado del plano de datos del proyecto (api-version=v1)."""
        return self._paginar(lambda p: self._datos("GET", ruta, params=p, preview=preview),
                             self._url(ruta), max_paginas)

    def _listar_openai(self, ruta: str, max_paginas: int = 50) -> list[dict]:
        """GET paginado de la superficie OpenAI v1 (ficheros, ficheros de contenedor): P3."""
        return self._paginar(lambda p: self._openai("GET", ruta, params=p),
                             self._url("openai/v1/" + ruta.lstrip("/")), max_paginas)

    # ------------------------------------------------------------------ protecciones
    def _exigir_escribible(self, nombre: str) -> None:
        """Solo se escribe sobre agentes con el prefijo preventa- y nunca sobre los protegidos."""
        if nombre in self.cfg["protegidos"].get("agentes", []):
            raise OperacionNoPermitida(f"El agente {nombre} está protegido: no se modifica.")
        if not nombre.startswith(self.cfg.get("prefijo_agentes", "preventa-")):
            raise OperacionNoPermitida(f"El agente {nombre} no lleva el prefijo preventa-.")

    # ----------------------------------------------------------------------- agentes
    def listar_agentes(self) -> list[dict]:
        return self.listar("agents")

    def obtener_agente(self, nombre: str) -> dict:
        return self._datos("GET", f"agents/{nombre}")

    def listar_versiones_agente(self, nombre: str) -> list[dict]:
        return self.listar(f"agents/{nombre}/versions")

    def obtener_version_agente(self, nombre: str, version: str) -> dict:
        return self._datos("GET", f"agents/{nombre}/versions/{version}")

    def crear_agente(self, nombre: str, definicion: dict, descripcion: str | None = None,
                     metadata: dict | None = None) -> dict:
        """POST /agents: crea el agente con su primera versión."""
        self._exigir_escribible(nombre)
        cuerpo = {"name": nombre, "definition": definicion}
        if descripcion:
            cuerpo["description"] = descripcion
        if metadata:
            cuerpo["metadata"] = metadata
        return self._datos("POST", "agents", json_body=cuerpo, esperado=(200, 201))

    def crear_version_agente(self, nombre: str, definicion: dict, descripcion: str | None = None,
                             metadata: dict | None = None) -> dict:
        """POST /agents/{nombre}/versions: nueva versión inmutable del agente."""
        self._exigir_escribible(nombre)
        cuerpo: dict[str, Any] = {"definition": definicion}
        if descripcion:
            cuerpo["description"] = descripcion
        if metadata:
            cuerpo["metadata"] = metadata
        return self._datos("POST", f"agents/{nombre}/versions", json_body=cuerpo,
                           esperado=(200, 201))

    def actualizar_agente(self, nombre: str, cambios: dict) -> dict:
        """PATCH /agents/{nombre} (p. ej. agent_card y agent_endpoint para exponer A2A)."""
        self._exigir_escribible(nombre)
        return self._datos("PATCH", f"agents/{nombre}", json_body=cambios)

    def exponer_a2a(self, nombre: str, agent_card: dict) -> dict:
        """Activa los protocolos responses y a2a con su agent card en un único PATCH (Learn)."""
        return self.actualizar_agente(nombre, {
            "agent_card": agent_card,
            "agent_endpoint": {"protocol_configuration": {"responses": {}, "a2a": {}}}})

    def borrar_agente_prueba(self, nombre: str) -> Any:
        """DELETE solo para agentes desechables preventa-prueba- creados en I0."""
        if not nombre.startswith(self.cfg.get("prefijo_agentes_desechables", "preventa-prueba-")):
            raise OperacionNoPermitida(f"Solo se borran agentes preventa-prueba-: {nombre}")
        self._exigir_escribible(nombre)
        return self._datos("DELETE", f"agents/{nombre}", esperado=(200, 202, 204))

    # --------------------------------------------------------- ficheros y respuestas
    def subir_fichero(self, ruta: str | pathlib.Path, purpose: str = "assistants") -> dict:
        """POST {proyecto}/openai/v1/files (multipart) con purpose=assistants.

        Nota de Learn: para montar ficheros en el Code Interpreter de un TOOLBOX hay que subirlos
        al endpoint de recurso con x-aml-project-id (subir_fichero_recurso); para prompt agents
        vale el endpoint del proyecto.
        """
        p = pathlib.Path(ruta)
        contenido = p.read_bytes()  # bytes, no manejador: un reintento reenvía el fichero entero
        return self._openai("POST", "files", files={"file": (p.name, contenido)},
                            data={"purpose": purpose}, esperado=(200, 201))

    def subir_fichero_recurso(self, ruta: str | pathlib.Path, id_interno_proyecto: str,
                              purpose: str = "assistants") -> dict:
        """POST {recurso}/openai/v1/files con x-aml-project-id (caso toolbox, ver Learn)."""
        p = pathlib.Path(ruta)
        return self._peticion("POST", f"{self.ep_recurso}/openai/v1/files", self._tok_datos,
                              files={"file": (p.name, p.read_bytes())}, data={"purpose": purpose},
                              cabeceras={"x-aml-project-id": id_interno_proyecto},
                              esperado=(200, 201))

    def obtener_fichero(self, file_id: str) -> dict:
        return self._openai("GET", f"files/{file_id}")

    def listar_ficheros(self) -> list[dict]:
        """Todos los ficheros del proyecto, siguiendo has_more/last_id (P3)."""
        return self._listar_openai("files")

    def responder(self, agente: str, entrada: Any, *, conversacion: str | None = None,
                  previa: str | None = None, extra: dict | None = None,
                  version: str | None = None) -> dict:
        """POST {proyecto}/openai/v1/responses con agent_reference (no reintenta 5xx)."""
        ref: dict[str, Any] = {"type": "agent_reference", "name": agente}
        if version:
            ref["version"] = version
        cuerpo: dict[str, Any] = {"agent_reference": ref, "input": entrada}
        if conversacion:
            cuerpo["conversation"] = conversacion
        if previa:
            cuerpo["previous_response_id"] = previa
        cuerpo.update(extra or {})
        return self._openai("POST", "responses", json_body=cuerpo)

    def obtener_respuesta(self, response_id: str) -> dict:
        return self._openai("GET", f"responses/{response_id}")

    def obtener_contenedor(self, container_id: str) -> dict:
        return self._openai("GET", f"containers/{container_id}")

    def listar_ficheros_contenedor(self, container_id: str) -> list[dict]:
        """Todos los ficheros del contenedor, siguiendo has_more/last_id (P3)."""
        return self._listar_openai(f"containers/{container_id}/files")

    def subir_a_contenedor(self, container_id: str, ruta: str | pathlib.Path) -> dict:
        """POST /containers/{id}/files (multipart), forma probada en F2/upload.log."""
        p = pathlib.Path(ruta)
        return self._openai("POST", f"containers/{container_id}/files",
                            files={"file": (p.name, p.read_bytes())}, esperado=(200, 201))

    @staticmethod
    def nombre_seguro(nombre: Any) -> str:
        """Nombre de fichero que se puede escribir en local (C2): se queda con el último
        componente (separadores de Windows y POSIX) y rechaza el vacío, «.», «..», cualquier
        «..», los caracteres reservados de Windows y los de control. El nombre de una cita lo
        decide lo que corre en el sandbox, así que nunca se usa sin pasar por aquí."""
        crudo = "" if nombre is None else str(nombre)
        n = pathlib.PurePosixPath(pathlib.PureWindowsPath(crudo).name).name
        if (not n or n != n.strip() or ".." in n or n == "."
                or any(ch in n for ch in ':*?"<>|') or any(ord(ch) < 32 for ch in n)):
            raise OperacionNoPermitida(f"Nombre de fichero no admitido: {crudo[:120]!r}")
        return n

    def descargar_fichero_contenedor(self, container_id: str, file_id: str,
                                     destino: str | pathlib.Path,
                                     carpeta: str | pathlib.Path | None = None) -> pathlib.Path:
        """GET /containers/{c}/files/{f}/content y lo guarda (caducan a los 20 min de inactividad).

        Antes de pedir nada exige que el nombre de `destino` sea un nombre seguro, que la ruta no
        lleve «..» y que `destino.resolve()` quede dentro de `carpeta` (por defecto, la carpeta
        de `destino`). Si no, OperacionNoPermitida y no se escribe nada (C2)."""
        d = pathlib.Path(destino)
        base = pathlib.Path(carpeta) if carpeta is not None else d.parent
        if ".." in d.parts or d.name != self.nombre_seguro(d.name):
            raise OperacionNoPermitida(f"Destino de descarga no admitido: {str(d)[:200]!r}")
        base_r, d_r = base.resolve(), d.resolve()
        if base_r not in d_r.parents:
            raise OperacionNoPermitida(f"El destino {d_r} queda fuera de la carpeta de descargas {base_r}")
        b = self._openai("GET", f"containers/{container_id}/files/{file_id}/content", crudo=True)
        d_r.parent.mkdir(parents=True, exist_ok=True)
        d_r.write_bytes(b)
        return d

    @staticmethod
    def citas_de_ficheros(respuesta: dict) -> list[dict]:
        """Extrae las anotaciones container_file_citation (container_id, file_id, filename)."""
        citas = []
        for item in respuesta.get("output", []) or []:
            for c in item.get("content", []) or []:
                for a in c.get("annotations", []) or []:
                    if a.get("type") == "container_file_citation":
                        citas.append({k: a.get(k) for k in ("container_id", "file_id", "filename")})
        return citas

    @staticmethod
    def texto_de(respuesta: dict) -> str:
        """Concatena el texto de salida de los mensajes de una respuesta."""
        partes = []
        for item in respuesta.get("output", []) or []:
            if item.get("type") == "message":
                partes += [c.get("text", "") for c in item.get("content", []) or []]
        return "".join(partes)

    # --------------------------------------------------------------------------- ARM
    def _arm(self, metodo: str, id_recurso: str, api_version: str, **kw) -> Any:
        """Petición ARM sobre un id de recurso que empieza por /subscriptions/..."""
        url = f"{self.cfg['endpoints']['arm'].rstrip('/')}{id_recurso}"
        params = {"api-version": api_version}
        params.update(kw.pop("params", None) or {})
        return self._peticion(metodo, url, self._tok_arm, params=params, **kw)

    def obtener_conexion(self, nombre: str) -> dict | None:
        """GET de una conexión del proyecto; None si no existe (404)."""
        try:
            return self._arm("GET", f"{self.id_arm_proyecto}/connections/{nombre}",
                             self.cfg["api_versions"]["arm_conexiones"])
        except ErrorFoundry as e:
            if e.estado == 404:
                return None
            raise

    def put_conexion(self, nombre: str, propiedades: dict, sobrescribir: bool = False) -> dict:
        """PUT de una conexión del proyecto (RemoteA2A, AppInsights...). No pisa la existente
        salvo `sobrescribir=True` y nunca toca la conexión rota de App Insights."""
        if nombre in (self.cfg["protegidos"].get("conexion_appinsights_rota"), self.cfg.get("conexion_appinsights")):
            raise OperacionNoPermitida(f"La conexión {nombre} está protegida: no se modifica.")
        if not sobrescribir and self.obtener_conexion(nombre) is not None:
            raise OperacionNoPermitida(f"La conexión {nombre} ya existe; usa sobrescribir=True.")
        return self._arm("PUT", f"{self.id_arm_proyecto}/connections/{nombre}",
                         self.cfg["api_versions"]["arm_conexiones"],
                         json_body={"properties": propiedades}, esperado=(200, 201))

    def propiedades_remote_a2a(self, agente_destino: str) -> dict:
        """Propiedades de una conexión RemoteA2A con AgenticIdentityToken (Learn, sin ruta de card)."""
        return {"authType": "AgenticIdentityToken", "category": "RemoteA2A",
                "target": f"{self.ep_proyecto}/agents/{agente_destino}/endpoint/protocols/a2a",
                "audience": self.cfg["audiencias"]["datos"], "Credentials": {}, "metadata": {}}

    def listar_asignaciones_rol(self, ambito: str, principal_id: str | None = None) -> list[dict]:
        """GET roleAssignments en un ámbito ARM (opcionalmente filtrado por principalId)."""
        params = {"$filter": f"principalId eq '{principal_id}'"} if principal_id else None
        j = self._arm("GET", f"{ambito}/providers/Microsoft.Authorization/roleAssignments",
                      self.cfg["api_versions"]["arm_roles"], params=params)
        return j.get("value", []) if isinstance(j, dict) else []

    def asignar_rol(self, ambito: str, rol_guid: str, principal_id: str,
                    principal_type: str = "ServicePrincipal") -> dict:
        """PUT roleAssignments con nombre nuevo. Si ya existe la misma asignación en ese ámbito,
        la devuelve sin crear otra (idempotente a nivel lógico).

        Solo admite como ámbito la cuenta o el proyecto de config/entorno.local.json (C3): cualquier
        otro ámbito ARM se rechaza antes de llamar a Azure."""
        ambitos = {self.id_arm_cuenta.lower(), self.id_arm_proyecto.lower()}
        if str(ambito).rstrip("/").lower() not in ambitos:
            raise OperacionNoPermitida(f"Ámbito {ambito!r} fuera de los autorizados para I0: "
                                       f"{sorted(ambitos)}")
        ambito = str(ambito).rstrip("/")
        permitidos = set(self.cfg["roles"].values())
        if rol_guid not in permitidos:
            raise OperacionNoPermitida(f"Rol {rol_guid} fuera de los autorizados para I0: {permitidos}")
        def_id = (f"/subscriptions/{self.cfg['suscripcion_id']}/providers/"
                  f"Microsoft.Authorization/roleDefinitions/{rol_guid}")
        for a in self.listar_asignaciones_rol(ambito, principal_id):
            pr = a.get("properties", {})
            if (pr.get("roleDefinitionId", "").lower() == def_id.lower()
                    and pr.get("scope", "").lower() == ambito.lower()):
                return a
        cuerpo = {"properties": {"roleDefinitionId": def_id, "principalId": principal_id,
                                 "principalType": principal_type}}
        return self._arm("PUT", f"{ambito}/providers/Microsoft.Authorization/roleAssignments/"
                         f"{uuid.uuid4()}", self.cfg["api_versions"]["arm_roles"],
                         json_body=cuerpo, esperado=(200, 201))
