"""Cliente REST mínimo del proyecto Foundry para gestionar los agentes del sistema.

Plano de datos (audiencia https://ai.azure.com, api-version=v1): listar, leer, crear agente,
crear versión y borrar agentes. Nada más: cualquier otra ruta o método se rechaza antes de pedir un token.

Guardas (fallan cerrado, antes de cualquier llamada de red):
1. Nombre de agente: solo minúsculas, dígitos y guiones, hasta 63 caracteres (también evita que
   un nombre con «/», «?» o «..» cambie la ruta de la petición).
2. Protegidos: se rechaza escribir o borrar cualquier agente de `protegidos.agentes` (sin
   distinguir mayúsculas) o que empiece por un prefijo de `protegidos.prefijos_agentes`.
3. Prefijo: solo se escribe o borra sobre agentes que empiezan por `ofa-`.
4. Borrado: por defecto solo agentes desechables `ofa-prueba-`; borrar un agente del sistema
   exige `permitir_sistema=True` explícito (un valor por defecto peligroso convierte un descuido
   en un incidente, LES-G-061).
5. Lista blanca de rutas REST por método, comprobada en el punto único por el que sale todo;
   en ese mismo punto se repite la guarda de nombre para toda petición que no sea GET.
6. El token solo viaja a los hosts del recurso y del proyecto de config/entorno.local.json.

Reintentos: solo ante 429 y, si la operación es idempotente, 5xx o fallo de red; máximo 3
intentos, cada uno anotado en `self.registro` y en stderr (P-6). Ningún mensaje de error lleva
secretos: todo pasa por `redaccion.redactar`.
"""
from __future__ import annotations

import copy
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse

import requests

from lib import azure_auth
from lib.config import HOST_DATOS, cargar as cargar_config, validar as validar_config
from lib.redaccion import redactar

REINTENTABLES = {429, 500, 502, 503, 504}
MAX_INTENTOS = 3
ESPERA_MAX_S = 30.0
_NOMBRE_AGENTE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SEG = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_VERSION = r"[A-Za-z0-9._-]{1,64}"

# Lista blanca de rutas del plano de datos (relativas al endpoint del proyecto), por método.
RUTAS_PERMITIDAS: dict[str, tuple[re.Pattern[str], ...]] = {
    "GET": (re.compile(r"^agents$"), re.compile(rf"^agents/{_SEG}$"),
            re.compile(rf"^agents/{_SEG}/versions$"),
            re.compile(rf"^agents/{_SEG}/versions/{_VERSION}$")),
    "POST": (re.compile(r"^agents$"), re.compile(rf"^agents/{_SEG}/versions$")),
    "DELETE": (re.compile(rf"^agents/{_SEG}$"),),
}


class ErrorFoundry(RuntimeError):
    """Respuesta HTTP no esperada; incluye método, URL, estado y cuerpo recortado y redactado."""

    def __init__(self, metodo: str, url: str, estado: int, cuerpo: str):
        self.metodo, self.url, self.estado = metodo, redactar(url), estado
        self.cuerpo = redactar(cuerpo)
        super().__init__(f"{metodo} {self.url} -> HTTP {estado}: {self.cuerpo[:1500]}")


class OperacionNoPermitida(PermissionError):
    """La operación tocaría un recurso o una ruta que este cliente no puede modificar."""


@dataclass
class Intento:
    """Anotación de un intento fallido reintentable (P-6: nada de reintentos silenciosos)."""
    metodo: str
    url: str
    estado: int | None
    error: str
    espera_s: float


def comprobar_nombre_escribible(nombre: Any, cfg: dict) -> str:
    """Devuelve `nombre` si se puede crear o modificar; si no, OperacionNoPermitida.

    Orden: forma del nombre → protegidos (nombre exacto y prefijos) → prefijo ofa-.
    """
    if not isinstance(nombre, str) or not nombre:
        raise OperacionNoPermitida(f"Nombre de agente no válido: {nombre!r}")
    prot = cfg.get("protegidos") or {}
    plegado = nombre.casefold()
    if plegado in {str(n).casefold() for n in prot.get("agentes", [])}:
        raise OperacionNoPermitida(f"El agente {nombre} está protegido: no se modifica ni se borra.")
    for pref in prot.get("prefijos_agentes", []):
        if plegado.startswith(str(pref).casefold()):
            raise OperacionNoPermitida(f"El agente {nombre} lleva el prefijo protegido {pref}.")
    if not _NOMBRE_AGENTE.fullmatch(nombre):
        raise OperacionNoPermitida(f"Nombre de agente con caracteres no admitidos: {nombre!r}")
    prefijo = cfg.get("prefijo_agentes")
    if prefijo != "ofa-":
        raise OperacionNoPermitida(f"Configuración sin el prefijo ofa-: {prefijo!r}")
    if not nombre.startswith(prefijo):
        raise OperacionNoPermitida(f"El agente {nombre} no lleva el prefijo {prefijo}.")
    return nombre


def comprobar_nombre_borrable(nombre: Any, cfg: dict, permitir_sistema: bool = False) -> str:
    """Como `comprobar_nombre_escribible` y, salvo `permitir_sistema`, exige el prefijo ofa-prueba-."""
    comprobar_nombre_escribible(nombre, cfg)
    pref_prueba = cfg.get("prefijo_agentes_prueba")
    if pref_prueba != "ofa-prueba-":
        raise OperacionNoPermitida(f"Configuración sin el prefijo de prueba ofa-prueba-: {pref_prueba!r}")
    if not permitir_sistema and not nombre.startswith(pref_prueba):
        raise OperacionNoPermitida(f"Solo se borran agentes {pref_prueba} salvo permitir_sistema=True: "
                                   f"{nombre}")
    return nombre


def comprobar_ruta(metodo: str, ruta: str) -> None:
    """Falla cerrado si (método, ruta) no está en la lista blanca."""
    patrones = RUTAS_PERMITIDAS.get(metodo.upper(), ())
    if not any(p.fullmatch(ruta) for p in patrones):
        raise OperacionNoPermitida(f"Ruta REST fuera de la lista blanca: {metodo.upper()} {ruta}")


@dataclass
class ClienteFoundry:
    """Cliente del proyecto. `cfg` es el diccionario de config/entorno.local.json."""
    cfg: dict = field(default_factory=cargar_config)
    gestor: azure_auth.GestorTokens | None = None
    timeout_s: float = 60.0
    registro: list[Intento] = field(default_factory=list)
    sesion: Any = field(default_factory=requests.Session, repr=False)
    dormir: Callable[[float], None] = field(default=time.sleep, repr=False)

    def __post_init__(self) -> None:
        # Copia propia: mutar después el diccionario del llamante no relaja las guardas.
        self.cfg = copy.deepcopy(validar_config(self.cfg))
        if self.gestor is None:
            self.gestor = azure_auth.GestorTokens(tenant=self.cfg["tenant_id"])
        elif self.gestor.tenant != self.cfg["tenant_id"]:
            raise OperacionNoPermitida("El gestor de tokens no usa el tenant de la configuración.")

    # ------------------------------------------------------------------ utilidades
    @property
    def ep_proyecto(self) -> str:
        return self.cfg["endpoints"]["proyecto"].rstrip("/")

    def _host_permitido(self, url: str) -> bool:
        """El token solo sale por https hacia el host del recurso, que debe ser *.services.ai.azure.com."""
        u = urlparse(url)
        recurso = urlparse(self.cfg["endpoints"]["recurso"]).hostname or ""
        return (u.scheme == "https" and bool(u.hostname) and u.hostname == recurso
                and recurso.endswith(HOST_DATOS) and u.port is None
                and not u.username and not u.password)

    def _peticion(self, metodo: str, ruta: str, *, params: dict | None = None,
                  json_body: Any = None, esperado: tuple[int, ...] = (200,)) -> Any:
        """Punto único de salida: lista blanca de rutas, host autorizado y reintentos anotados."""
        metodo = metodo.upper()
        ruta = ruta.strip("/")
        comprobar_ruta(metodo, ruta)
        if metodo != "GET":
            comprobar_nombre_escribible(self._nombre_destino(ruta, json_body), self.cfg)
        url = f"{self.ep_proyecto}/{ruta}"
        if not self._host_permitido(url):
            raise OperacionNoPermitida(f"Destino no autorizado para enviar un token: {url}")
        p = {"api-version": self.cfg["api_versions"]["datos_proyecto"]}
        p.update(params or {})
        idempotente = metodo != "POST"
        ultimo = ""
        for n in range(1, MAX_INTENTOS + 1):
            cab = {"Authorization": "Bearer " + self.gestor.token(azure_auth.AUD_DATOS),
                   "Accept": "application/json"}
            try:
                # Sin redirecciones: el token no sigue a otro destino aunque el servidor lo pida.
                r = self.sesion.request(metodo, url, params=p, json=json_body, headers=cab,
                                        timeout=self.timeout_s, allow_redirects=False)
            except requests.RequestException as e:
                ultimo = f"{type(e).__name__}: {e}"
                if not idempotente or n == MAX_INTENTOS:
                    raise ErrorFoundry(metodo, url, -1, ultimo[:500]) from None
                self._anotar(metodo, url, None, ultimo, n)
                continue
            if r.status_code in esperado:
                return r.json() if r.content else None
            cuerpo = r.text[:2000]
            if r.status_code == 401 and n < MAX_INTENTOS:
                # Token rechazado: se olvida y se pide otro una vez anotado (no es silencioso).
                self.gestor.olvidar(azure_auth.AUD_DATOS)
                self._anotar(metodo, url, 401, cuerpo, n, "0")
                continue
            reintentable = r.status_code == 429 or (idempotente and r.status_code in REINTENTABLES)
            if reintentable and n < MAX_INTENTOS:
                self._anotar(metodo, url, r.status_code, cuerpo, n, r.headers.get("Retry-After"))
                continue
            raise ErrorFoundry(metodo, url, r.status_code, cuerpo)
        raise ErrorFoundry(metodo, url, -1, f"Sin respuesta tras {MAX_INTENTOS} intentos: {ultimo}")

    @staticmethod
    def _nombre_destino(ruta: str, json_body: Any) -> Any:
        """Agente al que apunta una escritura: el segmento de la ruta o, en POST /agents, el cuerpo."""
        partes = ruta.split("/")
        if len(partes) >= 2:
            return partes[1]
        return json_body.get("name") if isinstance(json_body, dict) else None

    def _anotar(self, metodo: str, url: str, estado: int | None, error: str, n: int,
                retry_after: str | None = None) -> None:
        """Registra el intento fallido y espera (Retry-After si viene, si no 2^n s; tope 30 s)."""
        try:
            espera = min(float(retry_after), ESPERA_MAX_S) if retry_after else float(2 ** n)
        except ValueError:
            espera = float(2 ** n)
        error_r = redactar(error)[:300]
        self.registro.append(Intento(metodo, redactar(url), estado, error_r, espera))
        sys.stderr.write(f"[reintento {n}/{MAX_INTENTOS}] {metodo} {redactar(url)} -> {estado}: "
                         f"{error_r} (espera {espera:.0f} s)\n")
        self.dormir(espera)

    def _paginar(self, ruta: str, max_paginas: int = 50) -> list[dict]:
        """Sigue data + has_more/last_id con `after`. Falla en alto si la lista quedaría truncada."""
        items: list[dict] = []
        after = None
        for _ in range(max_paginas):
            j = self._peticion("GET", ruta, params={"after": after} if after else None)
            if not isinstance(j, dict):
                raise ErrorFoundry("GET", ruta, 200, "Respuesta de lista que no es un objeto JSON")
            datos = j.get("data", j.get("value"))
            if not isinstance(datos, list):
                raise ErrorFoundry("GET", ruta, 200, "Respuesta de lista sin 'data'")
            items += datos
            if not j.get("has_more"):
                return items
            if not datos:
                raise ErrorFoundry("GET", ruta, 200, "has_more sin datos: lista truncada")
            nuevo = j.get("last_id") or datos[-1].get("id") or datos[-1].get("name")
            if not nuevo or nuevo == after:
                raise ErrorFoundry("GET", ruta, 200, "Paginación sin cursor válido")
            after = nuevo
        raise ErrorFoundry("GET", ruta, 200, f"Más de {max_paginas} páginas: lista truncada")

    # ----------------------------------------------------------------------- agentes
    def listar_agentes(self) -> list[dict]:
        """Todos los agentes del proyecto (lectura; incluye los ajenos, que no se tocan)."""
        return self._paginar("agents")

    def obtener_agente(self, nombre: str) -> dict:
        if not isinstance(nombre, str) or not _NOMBRE_AGENTE.fullmatch(nombre):
            raise OperacionNoPermitida(f"Nombre de agente con caracteres no admitidos: {nombre!r}")
        return self._peticion("GET", f"agents/{nombre}")

    def listar_versiones_agente(self, nombre: str) -> list[dict]:
        if not isinstance(nombre, str) or not _NOMBRE_AGENTE.fullmatch(nombre):
            raise OperacionNoPermitida(f"Nombre de agente con caracteres no admitidos: {nombre!r}")
        return self._paginar(f"agents/{nombre}/versions")

    def obtener_version_agente(self, nombre: str, version: str) -> dict:
        if not isinstance(nombre, str) or not _NOMBRE_AGENTE.fullmatch(nombre):
            raise OperacionNoPermitida(f"Nombre de agente con caracteres no admitidos: {nombre!r}")
        if not re.fullmatch(_VERSION, str(version)):
            raise OperacionNoPermitida(f"Versión no admitida: {version!r}")
        return self._peticion("GET", f"agents/{nombre}/versions/{version}")

    @staticmethod
    def _cuerpo(definicion: dict, descripcion: str | None, metadata: dict | None) -> dict[str, Any]:
        if not isinstance(definicion, dict) or definicion.get("kind") not in ("prompt", "hosted"):
            raise ValueError("La definición del agente debe ser un objeto con kind 'prompt' o 'hosted'.")
        cuerpo: dict[str, Any] = {"definition": definicion}
        if descripcion:
            cuerpo["description"] = descripcion
        if metadata:
            cuerpo["metadata"] = metadata
        return cuerpo

    def crear_agente(self, nombre: str, definicion: dict, descripcion: str | None = None,
                     metadata: dict | None = None) -> dict:
        """POST /agents: crea el agente con su primera versión."""
        comprobar_nombre_escribible(nombre, self.cfg)
        cuerpo = {"name": nombre, **self._cuerpo(definicion, descripcion, metadata)}
        return self._peticion("POST", "agents", json_body=cuerpo, esperado=(200, 201))

    def crear_version_agente(self, nombre: str, definicion: dict, descripcion: str | None = None,
                             metadata: dict | None = None) -> dict:
        """POST /agents/{nombre}/versions: nueva versión inmutable de un agente existente."""
        comprobar_nombre_escribible(nombre, self.cfg)
        return self._peticion("POST", f"agents/{nombre}/versions",
                              json_body=self._cuerpo(definicion, descripcion, metadata),
                              esperado=(200, 201))

    def borrar_agente(self, nombre: str, permitir_sistema: bool = False, forzar: bool = False) -> Any:
        """DELETE /agents/{nombre}. Por defecto solo agentes ofa-prueba-.

        `forzar=True` añade `force=true`, que según Learn borra también las sesiones activas de un
        hosted agent (sin él, la API responde 409 «Agent has active sessions»).
        """
        comprobar_nombre_borrable(nombre, self.cfg, permitir_sistema=permitir_sistema)
        return self._peticion("DELETE", f"agents/{nombre}", params={"force": "true"} if forzar else None,
                              esperado=(200, 202, 204))
