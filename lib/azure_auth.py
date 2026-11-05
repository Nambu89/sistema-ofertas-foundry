"""Tokens de Entra ID obtenidos con la CLI de Azure, con tenant fijo y caché en memoria.

El token nunca se imprime ni se escribe en disco: vive solo en la memoria del proceso.
Si az pide MFA o el inicio de sesión ha caducado, se lanza ErrorAutenticacion con el
texto literal de az para que el comercial ejecute `az login`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time

TENANT_POR_DEFECTO = "00000000-0000-0000-0000-000000000000"
AUD_DATOS = "https://ai.azure.com"
AUD_ARM = "https://management.azure.com"
_MARGEN_S = 300  # se renueva el token 5 minutos antes de caducar

# Fragmentos de error de az que indican que hace falta volver a iniciar sesión.
_SENALES_LOGIN = ("AADSTS50076", "AADSTS50078", "AADSTS50079", "AADSTS700082",
                  "AADSTS50173", "AADSTS70043", "az login", "interaction_required",
                  "expired", "caducad")


class ErrorAutenticacion(RuntimeError):
    """az no pudo emitir el token: requiere `az login` (MFA o sesión caducada)."""


class ErrorAz(RuntimeError):
    """az falló por un motivo distinto de la autenticación."""


_cache: dict[tuple[str, str], tuple[str, float]] = {}
_cerrojo = threading.Lock()


def _ejecutable_az() -> str:
    """Localiza az (en Windows es az.cmd)."""
    ruta = shutil.which("az") or shutil.which("az.cmd")
    if not ruta:
        raise ErrorAz("No se encuentra la CLI de Azure (az) en el PATH.")
    return ruta


def _pedir_a_az(recurso: str, tenant: str) -> tuple[str, float]:
    """Llama a `az account get-access-token` con tenant explícito; devuelve (token, expira_epoch)."""
    cmd = [_ejecutable_az(), "account", "get-access-token", "--tenant", tenant,
           "--resource", recurso, "-o", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        if any(s.lower() in err.lower() for s in _SENALES_LOGIN):
            raise ErrorAutenticacion(
                "az necesita volver a iniciar sesión (MFA o sesión caducada). Ejecuta "
                f"'az login --tenant {tenant}'. Error literal de az: {err[:800]}")
        raise ErrorAz(f"az get-access-token falló (rc={r.returncode}): {err[:800]}")
    try:
        datos = json.loads(r.stdout)
        token = datos["accessToken"]
    except (ValueError, KeyError) as e:
        raise ErrorAz(f"Respuesta de az sin accessToken legible ({type(e).__name__}).") from None
    expira = float(datos.get("expires_on") or 0) or time.time() + 1800
    return token, expira


def obtener_token(recurso: str = AUD_DATOS, tenant: str = TENANT_POR_DEFECTO,
                  forzar: bool = False) -> str:
    """Devuelve un token válido para `recurso`, reutilizando la caché si no está a punto de caducar."""
    clave = (tenant, recurso)
    with _cerrojo:
        if not forzar and clave in _cache:
            token, expira = _cache[clave]
            if expira - time.time() > _MARGEN_S:
                return token
        token, expira = _pedir_a_az(recurso, tenant)
        _cache[clave] = (token, expira)
        return token


def token_datos(tenant: str = TENANT_POR_DEFECTO) -> str:
    """Token del plano de datos de Foundry (audiencia https://ai.azure.com)."""
    return obtener_token(AUD_DATOS, tenant)


def token_arm(tenant: str = TENANT_POR_DEFECTO) -> str:
    """Token de Azure Resource Manager (audiencia https://management.azure.com)."""
    return obtener_token(AUD_ARM, tenant)


def olvidar_tokens() -> None:
    """Vacía la caché en memoria (por ejemplo, tras un 401)."""
    with _cerrojo:
        _cache.clear()


if __name__ == "__main__":
    # Comprobación manual: confirma que hay token sin mostrarlo.
    t = token_datos()
    sys.stdout.write(f"token de datos obtenido ({len(t)} caracteres, no se muestra)\n")
