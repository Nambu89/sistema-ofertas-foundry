"""Configuración del hosted agent: variables de entorno, carpetas de la sesión y recursos del núcleo.

Todo falla en alto (ErrorConfig) si un valor es inválido; un valor vacío o con solo espacios cuenta
como no fijado (LES-G-076). No lee ni guarda secretos: la identidad sale de DefaultAzureCredential.
"""
from __future__ import annotations

import dataclasses
import os
import pathlib
import re

RAIZ_PAQUETE = pathlib.Path(__file__).resolve().parents[1]   # carpeta de main.py (raíz del ZIP)
SCOPE_FOUNDRY = "https://ai.azure.com/.default"
TOPE_A2A_S = 115.0          # por debajo del corte de ~120 s observado en A2A (LES-G-089.8, LES-G-096.3)
# PR17-2 (I1.7): con SendMessage no bloqueante el tope de arriba es por PETICIÓN HTTP; la espera de una tarea en curso
# (sondeando GetTask) es aparte. El experto llegó a 112,6 s en real: la espera por defecto le da casi 4 veces eso.
ESPERA_A2A_S, SONDEO_A2A_S = 420.0, 5.0


class ErrorConfig(ValueError):
    """Configuración inválida: el turno no se ejecuta y se dice qué variable falla."""


def _v(env: dict, nombre: str) -> str | None:
    valor = env.get(nombre)
    if valor is None or not str(valor).strip():
        return None
    return str(valor).strip()


def _num(env: dict, nombre: str, defecto: float, minimo: float, maximo: float) -> float:
    crudo = _v(env, nombre)
    if crudo is None:
        return defecto
    try:
        valor = float(crudo)
    except ValueError as exc:
        raise ErrorConfig(f"{nombre}={crudo!r} no es un número") from exc
    if not minimo <= valor <= maximo:
        raise ErrorConfig(f"{nombre}={valor} fuera de {minimo}..{maximo}")
    return valor


@dataclasses.dataclass(frozen=True)
class Config:
    proyecto: str               # https://<cuenta>.services.ai.azure.com/api/projects/<proyecto>
    modelo: str                 # despliegue para rellenar requisitos (gpt-6-luna)
    experto: str                # nombre del agente destino A2A del análisis
    verificador: str            # nombre del agente destino A2A de la verificación
    timeout_a2a_s: float        # por petición HTTP A2A (< TOPE_A2A_S)
    timeout_modelo_s: float
    max_a2a_por_turno: int      # llamadas A2A como máximo en un turno (el resto, en el siguiente)
    base: pathlib.Path          # $HOME/preventa (persistente en la sesión)
    app: pathlib.Path           # carpeta que contiene preventa_api.py y nucleo/
    espera_a2a_s: float = ESPERA_A2A_S   # PR17-2: espera de UNA tarea A2A en curso, sondeando GetTask
    sondeo_a2a_s: float = SONDEO_A2A_S   # PR17-2: pausa entre sondeos

    @property
    def datos(self) -> pathlib.Path:
        return self.base / "datos"

    @property
    def trabajo(self) -> pathlib.Path:
        return self.base / "trabajo"

    def url_a2a(self, agente: str) -> str:
        return f"{self.proyecto}/agents/{agente}/endpoint/protocols/a2a"


def recursos(env: dict | None = None) -> dict[str, pathlib.Path]:
    """Rutas de los recursos canónicos dentro del ZIP (o las que fijen las variables PREVENTA_*)."""
    env = os.environ if env is None else env
    r = RAIZ_PAQUETE / "recursos"
    return {
        "PREVENTA_CATALOGO": pathlib.Path(_v(env, "PREVENTA_CATALOGO") or r / "catalogo_componentes.json"),
        "PREVENTA_RATE_CARD": pathlib.Path(_v(env, "PREVENTA_RATE_CARD") or r / "rate-card.json"),
        "PREVENTA_GENERADOR": pathlib.Path(_v(env, "PREVENTA_GENERADOR") or r / "generar_estimacion.py"),
        "PREVENTA_PLANTILLA": pathlib.Path(_v(env, "PREVENTA_PLANTILLA")
                                           or r / "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx"),
        # I1.7 (decisión 1): instantánea de precios descargada al desplegar (copia byte a byte de
        # catalogo/precios_instantanea.json; empaquetar.py comprueba su huella y su edad antes de meterla en el ZIP).
        "PREVENTA_PRECIOS": pathlib.Path(_v(env, "PREVENTA_PRECIOS") or r / "precios_instantanea.json"),
    }


def cargar(env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    proyecto = _v(env, "PREVENTA_PROYECTO") or _v(env, "FOUNDRY_PROJECT_ENDPOINT")
    if not proyecto or not re.fullmatch(r"https://[a-z0-9-]{2,64}\.services\.ai\.azure\.com/api/projects/[A-Za-z0-9_-]{2,64}/?",
                                         proyecto):
        raise ErrorConfig("Falta FOUNDRY_PROJECT_ENDPOINT (o PREVENTA_PROYECTO) con la forma "
                          "https://<cuenta>.services.ai.azure.com/api/projects/<proyecto>")
    timeout = _num(env, "PREVENTA_A2A_TIMEOUT_S", 110.0, 5.0, TOPE_A2A_S)
    home = _v(env, "PREVENTA_HOME") or _v(env, "HOME") or str(pathlib.Path.home())
    app = pathlib.Path(_v(env, "PREVENTA_APP_NUCLEO") or RAIZ_PAQUETE / "sandbox")
    if not (app / "preventa_api.py").is_file() or not (app / "nucleo" / "estado.py").is_file():
        raise ErrorConfig(f"No está el núcleo en {app} (preventa_api.py y nucleo/estado.py)")
    return Config(
        proyecto=proyecto.rstrip("/"),
        modelo=_v(env, "PREVENTA_MODELO") or "gpt-6-luna",
        experto=_v(env, "PREVENTA_EXPERTO") or "preventa-experto-azure",
        verificador=_v(env, "PREVENTA_VERIFICADOR") or "preventa-verificador",
        timeout_a2a_s=timeout,
        timeout_modelo_s=_num(env, "PREVENTA_MODELO_TIMEOUT_S", 100.0, 5.0, 300.0),
        max_a2a_por_turno=int(_num(env, "PREVENTA_MAX_A2A_POR_TURNO", 2, 1, 8)),
        espera_a2a_s=_num(env, "PREVENTA_A2A_ESPERA_S", ESPERA_A2A_S, 30.0, 1800.0),
        sondeo_a2a_s=_num(env, "PREVENTA_A2A_SONDEO_S", SONDEO_A2A_S, 1.0, 60.0),
        base=pathlib.Path(home) / "preventa",
        app=app,
    )
