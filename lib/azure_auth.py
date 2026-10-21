"""Tokens de Entra ID con tenant fijo, caché en memoria y renovación con margen de 5 minutos.

- El tenant se fija siempre (LES-G-052): sin `--tenant`, az emite el token de la suscripción
  activa y alternar entre tenants da 401 intermitentes. El tenant sale de `tenant_id` en la
  configuración local (config/entorno.local.json, ver lib/config.py); no se escribe en el código. Además se comprueba el `tid` del token
  recibido: si no es el tenant fijado, se rechaza.
- El token vive solo en la memoria del proceso: nunca se imprime, nunca se escribe en disco y no
  aparece en `repr` ni en los mensajes de error (que pasan por `redaccion.redactar`).
- Se renueva cuando le quedan 5 minutos o menos.
- Dos proveedores: la CLI de Azure (portátil, solo para construir y desplegar) y una credencial
  de azure-identity (identidad gestionada del agente hosted). Las pruebas inyectan uno simulado.
- Si az pide MFA o la sesión ha caducado, se lanza ErrorAutenticacion: hay que parar y que
  Fernando ejecute `az login --tenant <tenant> --scope https://ai.azure.com/.default`.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable

from lib.redaccion import redactar

AUD_DATOS = "https://ai.azure.com"
AUD_ARM = "https://management.azure.com"
MARGEN_RENOVACION_S = 300
TIMEOUT_AZ_S = 60  # por debajo del vigilante de 90 s

# Audiencias equivalentes que Entra puede devolver en la reclamación `aud`.
_ALIAS_AUD = {AUD_ARM: {AUD_ARM, "https://management.core.windows.net"}}

_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Fragmentos de error de az que indican que hace falta volver a iniciar sesión.
_SENALES_LOGIN = ("AADSTS50076", "AADSTS50078", "AADSTS50079", "AADSTS700082",
                  "AADSTS50173", "AADSTS70043", "az login", "interaction_required",
                  "expired", "caducad")

# Un proveedor recibe (audiencia, tenant) y devuelve (token, expira_epoch_segundos).
Proveedor = Callable[[str, str], "tuple[str, float]"]


class ErrorAutenticacion(RuntimeError):
    """No hay token válido: requiere `az login` (MFA o sesión caducada) o el token no es del tenant."""


class ErrorAz(RuntimeError):
    """az falló por un motivo distinto de la autenticación."""


def tenant_configurado() -> str:
    """`tenant_id` de la configuración local; lanza lib.config.ErrorConfig si falta o no es válida."""
    from lib import config  # import diferido: el agente hosted no lleva la configuración del repositorio
    return config.cargar()["tenant_id"]


def mensaje_login(tenant: str) -> str:
    return f"az login --tenant {tenant} --scope https://ai.azure.com/.default"


def reclamaciones_jwt(token: str) -> dict:
    """Decodifica (sin validar la firma) el cuerpo de un JWT. Lanza ErrorAutenticacion si no es JWT."""
    partes = token.split(".") if isinstance(token, str) else []
    if len(partes) != 3:
        raise ErrorAutenticacion("El token recibido no tiene forma de JWT (tres segmentos).")
    cuerpo = partes[1] + "=" * (-len(partes[1]) % 4)
    try:
        datos = json.loads(base64.urlsafe_b64decode(cuerpo.encode("ascii")))
    except (ValueError, UnicodeError) as e:
        raise ErrorAutenticacion(f"El cuerpo del token no es JSON legible ({type(e).__name__}).") from None
    if not isinstance(datos, dict):
        raise ErrorAutenticacion("El cuerpo del token no es un objeto JSON.")
    return datos


# ------------------------------------------------------------------------- proveedores
def _ejecutable_az() -> str:
    """Localiza az (en Windows es az.cmd)."""
    ruta = shutil.which("az") or shutil.which("az.cmd")
    if not ruta:
        raise ErrorAz("No se encuentra la CLI de Azure (az) en el PATH.")
    return ruta


def proveedor_az_cli(audiencia: str, tenant: str) -> tuple[str, float]:
    """`az account get-access-token --tenant <tenant> --resource <audiencia>`; devuelve (token, expira)."""
    cmd = [_ejecutable_az(), "account", "get-access-token", "--tenant", tenant,
           "--resource", audiencia, "-o", "json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT_AZ_S)
    except subprocess.TimeoutExpired:
        raise ErrorAz(f"az get-access-token no respondió en {TIMEOUT_AZ_S} s.") from None
    if r.returncode != 0:
        err = redactar((r.stderr or "").strip())[:800]
        if any(s.lower() in err.lower() for s in _SENALES_LOGIN):
            raise ErrorAutenticacion("az necesita volver a iniciar sesión (MFA o sesión caducada). "
                                     f"Fernando debe ejecutar: {mensaje_login(tenant)}. Error de az: {err}")
        raise ErrorAz(f"az get-access-token falló (rc={r.returncode}): {err}")
    try:
        datos = json.loads(r.stdout)
        token = datos["accessToken"]
    except (ValueError, KeyError, TypeError) as e:
        raise ErrorAz(f"Respuesta de az sin accessToken legible ({type(e).__name__}).") from None
    expira = datos.get("expires_on")
    try:
        expira_f = float(expira) if expira not in (None, "") else 0.0
    except (TypeError, ValueError):
        expira_f = 0.0
    return token, expira_f


def proveedor_credencial(credencial: Any, pasar_tenant: bool = True) -> Proveedor:
    """Adapta una credencial de azure-identity (`get_token`) al contrato de proveedor.

    Con identidad gestionada el tenant es el de la propia identidad (`pasar_tenant=False`); en ese
    caso el tenant fijo se sigue exigiendo comprobando el `tid` del token recibido.
    """
    def _proveedor(audiencia: str, tenant: str) -> tuple[str, float]:
        alcance = audiencia.rstrip("/") + "/.default"
        t = credencial.get_token(alcance, tenant_id=tenant) if pasar_tenant else credencial.get_token(alcance)
        return t.token, float(t.expires_on)
    return _proveedor


def proveedor_identidad_gestionada(client_id: str | None = None) -> Proveedor:
    """Proveedor con ManagedIdentityCredential (para el agente hosted en Foundry)."""
    from azure.identity import ManagedIdentityCredential  # import diferido: solo en la nube

    cred = ManagedIdentityCredential(client_id=client_id) if client_id else ManagedIdentityCredential()
    return proveedor_credencial(cred, pasar_tenant=False)


# ------------------------------------------------------------------------------ gestor
class GestorTokens:
    """Caché de tokens por audiencia para UN tenant fijo, con renovación anticipada."""

    def __init__(self, tenant: str | None = None, proveedor: Proveedor | None = None,
                 reloj: Callable[[], float] = time.time,
                 margen_s: float = MARGEN_RENOVACION_S) -> None:
        if tenant is None:
            tenant = tenant_configurado()
        if not isinstance(tenant, str) or not _GUID.fullmatch(tenant):
            raise ValueError(f"El tenant debe ser un GUID en minúsculas: {tenant!r}")
        if margen_s <= 0:
            raise ValueError("El margen de renovación debe ser positivo.")
        self.tenant = tenant
        self._proveedor = proveedor or proveedor_az_cli
        self._reloj = reloj
        self._margen = float(margen_s)
        self._cache: dict[str, tuple[str, float]] = {}
        self._cerrojo = threading.Lock()
        self.peticiones = 0  # cuántas veces se ha pedido un token al proveedor

    def __repr__(self) -> str:  # nunca muestra tokens
        return f"GestorTokens(tenant={self.tenant!r}, audiencias={sorted(self._cache)})"

    def _validar(self, audiencia: str, token: Any, expira: float) -> float:
        """Comprueba el token recibido y devuelve la caducidad efectiva (epoch)."""
        if not isinstance(token, str) or not token.strip():
            raise ErrorAutenticacion(f"El proveedor devolvió un token vacío para {audiencia}.")
        rec = reclamaciones_jwt(token)
        tid = rec.get("tid")
        if tid != self.tenant:
            raise ErrorAutenticacion(f"El token es del tenant {tid!r} y no del fijado {self.tenant!r}. "
                                     f"Fernando debe ejecutar: {mensaje_login(self.tenant)}")
        aud = rec.get("aud")
        auds = {str(x).rstrip("/") for x in (aud if isinstance(aud, list) else [aud]) if x}
        esperadas = {x.rstrip("/") for x in _ALIAS_AUD.get(audiencia.rstrip("/"), {audiencia})}
        if not auds & esperadas:
            raise ErrorAutenticacion(f"El token es para la audiencia {aud!r} y no para {audiencia!r}.")
        exp_jwt = rec.get("exp")
        candidatos = [float(x) for x in (expira, exp_jwt) if isinstance(x, (int, float)) and x > 0]
        if not candidatos:
            raise ErrorAutenticacion("El token no indica cuándo caduca (ni expires_on ni exp).")
        efectiva = min(candidatos)  # la más prudente
        if efectiva <= self._reloj():
            raise ErrorAutenticacion(f"El proveedor devolvió un token ya caducado para {audiencia}. "
                                     f"Fernando debe ejecutar: {mensaje_login(self.tenant)}")
        return efectiva

    def token(self, audiencia: str = AUD_DATOS, forzar: bool = False) -> str:
        """Token válido para `audiencia`; renueva si le quedan `margen_s` segundos o menos."""
        with self._cerrojo:
            if not forzar and audiencia in self._cache:
                tok, expira = self._cache[audiencia]
                if expira - self._reloj() > self._margen:
                    return tok
            self.peticiones += 1
            tok, expira = self._proveedor(audiencia, self.tenant)
            efectiva = self._validar(audiencia, tok, expira)
            self._cache[audiencia] = (tok, efectiva)
            return tok

    def caduca_en(self, audiencia: str = AUD_DATOS) -> float | None:
        """Segundos que le quedan al token en caché (None si no hay)."""
        with self._cerrojo:
            if audiencia not in self._cache:
                return None
            return self._cache[audiencia][1] - self._reloj()

    def olvidar(self, audiencia: str | None = None) -> None:
        """Vacía la caché de una audiencia (por ejemplo, tras un 401) o entera si no se indica."""
        with self._cerrojo:
            if audiencia is None:
                self._cache.clear()
            else:
                self._cache.pop(audiencia, None)


_gestor_por_defecto: GestorTokens | None = None
_cerrojo_global = threading.Lock()


def gestor_por_defecto() -> GestorTokens:
    """Gestor compartido del proceso, con el tenant de la configuración local y la CLI de Azure."""
    global _gestor_por_defecto
    with _cerrojo_global:
        if _gestor_por_defecto is None:
            _gestor_por_defecto = GestorTokens()
        return _gestor_por_defecto


def token_datos() -> str:
    """Token del plano de datos de Foundry (audiencia https://ai.azure.com)."""
    return gestor_por_defecto().token(AUD_DATOS)


def token_arm() -> str:
    """Token de Azure Resource Manager (audiencia https://management.azure.com)."""
    return gestor_por_defecto().token(AUD_ARM)


if __name__ == "__main__":
    # Comprobación manual: confirma que hay token sin mostrarlo.
    g = gestor_por_defecto()
    t = g.token(AUD_DATOS)
    sys.stdout.write(f"token de datos obtenido para el tenant {g.tenant} "
                     f"({len(t)} caracteres, no se muestra; caduca en {g.caduca_en():.0f} s)\n")
