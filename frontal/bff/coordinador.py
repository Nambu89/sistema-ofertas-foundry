"""Transportes hacia el coordinador B (hosted agent `preventa-prueba-hosted`).

- TransporteFoundry: el real. Responses API por el endpoint del agente con `background: true` y sondeo GET hasta
  un estado terminal. Token de Entra de la sesión `az` del usuario
  con tenant fijo (lib/azure_auth.py vía lib/foundry.py); nunca se guarda ni se imprime.
- TransporteReproduccion: devuelve, en orden, turnos reales ya guardados (saneados para publicar) y un ZIP
  reducido con solo lo que lee el frontal (reproduccion/paquete/LEEME.txt). Sirve para las pruebas del contrato y la interfaz; el frontal lo anuncia en pantalla.
"""
from __future__ import annotations

import base64
import json
import pathlib
import sys
import threading
import time
import uuid

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

AGENTE = "preventa-prueba-hosted"
TERMINALES = {"completed", "failed", "cancelled", "incomplete"}
MIME = {".txt": "text/plain", ".vtt": "text/vtt",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


class ErrorCoordinador(RuntimeError):
    """Fallo con un mensaje que se puede enseñar tal cual al comercial (sin tokens)."""


def texto_salida(r: dict) -> str:
    return "\n".join(c.get("text", "") for it in r.get("output") or [] if it.get("type") == "message"
                     for c in it.get("content") or [] if c.get("type") == "output_text")


def _cuerpo(texto: str, adjunto: tuple[str, bytes] | None, previa: dict | None) -> dict:
    contenido: list = [{"type": "input_text", "text": texto}]
    if adjunto:
        nombre, datos = adjunto
        mime = MIME[pathlib.PurePath(nombre).suffix.lower()]
        contenido.append({"type": "input_file", "filename": nombre,
                          "file_data": f"data:{mime};base64,{base64.b64encode(datos).decode('ascii')}"})
    cuerpo: dict = {"input": [{"type": "message", "role": "user", "content": contenido}], "store": True,
                    "background": True}
    if previa:
        cuerpo["previous_response_id"] = previa["response_id"]
        if previa.get("agent_session_id"):
            cuerpo["agent_session_id"] = previa["agent_session_id"]
    return cuerpo


class TransporteFoundry:
    modo = "real"

    def __init__(self, espera_max_s: float = 900.0):
        from lib import azure_auth
        from lib.foundry import ClienteFoundry
        self._auth = azure_auth
        self.c = ClienteFoundry()
        self.tenant = self.c.cfg["tenant_id"]
        self.url = f"{self.c.ep_proyecto}/agents/{AGENTE}/endpoint/protocols/openai/responses"
        self.espera_max_s = espera_max_s

    def _tok(self) -> str:
        return self._auth.token_datos(self.tenant)

    def comprobar_sesion(self) -> None:
        """Lanza ErrorCoordinador con la orden exacta si no hay sesión az válida en el tenant de config."""
        try:
            self._tok()
        except self._auth.ErrorAutenticacion:
            raise ErrorCoordinador(f"No hay sesión de Azure válida. Ejecuta en una terminal: "
                                   f"az login --tenant {self.tenant}") from None
        except self._auth.ErrorAz as e:
            raise ErrorCoordinador(f"La CLI de Azure no ha podido dar un token: {e}") from None

    def _peticion(self, metodo: str, url: str, **kw):
        from lib.evidencia import enmascarar_texto
        from lib.foundry import ErrorFoundry
        try:
            return self.c._peticion(metodo, url, lambda: self._tok(), **kw)
        except self._auth.ErrorAutenticacion:
            raise ErrorCoordinador(f"La sesión de Azure ha caducado. Ejecuta: az login --tenant {self.tenant}") \
                from None
        except ErrorFoundry as e:
            raise ErrorCoordinador(f"El coordinador respondió HTTP {e.estado}: "
                                   f"{enmascarar_texto(e.cuerpo[:600])}") from None

    def turno(self, texto: str, adjunto: tuple[str, bytes] | None, previa: dict | None) -> dict:
        r = self._peticion("POST", self.url, params={"api-version": "v1"}, json_body=_cuerpo(texto, adjunto, previa))
        sesion = r.get("agent_session_id") or (previa or {}).get("agent_session_id")
        t0, errores = time.monotonic(), 0
        while r.get("status") not in TERMINALES:
            if time.monotonic() - t0 > self.espera_max_s:
                raise ErrorCoordinador(f"El turno {r.get('id')} sigue en curso tras {int(self.espera_max_s)} s; "
                                       "no se cancela: vuelve a consultarlo más tarde.")
            time.sleep(5)
            try:
                # solo api-version: es la variante que respondió en la prueba real de I1.9 (sondeo_variante)
                nuevo = self._peticion("GET", f"{self.url}/{r['id']}", params={"api-version": "v1"})
            except ErrorCoordinador:
                errores += 1
                if errores >= 3:   # tres lecturas fallidas seguidas no son «sigue en curso»
                    raise
                continue
            errores, r = 0, {**nuevo, "agent_session_id": nuevo.get("agent_session_id") or sesion}
        return r

    def descargar(self, sesion: str, ruta: str) -> bytes:
        url = f"{self.c.ep_proyecto}/agents/{AGENTE}/endpoint/sessions/{sesion}/files/content"
        return self._peticion("GET", url, params={"path": ruta, "api-version": "v1"}, crudo=True)


class TransporteReproduccion:
    """Turnos reales de la serie H2 de I1.9 (Hostelia, cliente sintético), saneados, y un paquete reducido."""
    modo = "reproduccion"
    CARPETA = pathlib.Path(__file__).resolve().parent / "reproduccion"
    TURNOS = ("H2_T1", "H2_T2", *(f"H2A_sigue{n}" for n in range(1, 7)))

    def __init__(self, pausa_s: float = 0.0):
        self.pausa_s = pausa_s
        self.enviados: list[str] = []
        self._cursor: dict[str, int] = {}   # id de respuesta devuelta -> siguiente turno de esa solicitud
        self._cerrojo = threading.Lock()

    def comprobar_sesion(self) -> None:
        return None

    def turno(self, texto: str, adjunto: tuple[str, bytes] | None, previa: dict | None) -> dict:
        with self._cerrojo:   # cada solicitud sigue su propia cadena de respuestas (alta nueva = turno 0)
            n = 0 if previa is None else self._cursor.get(previa.get("response_id") or "")
            if n is None:
                raise ErrorCoordinador("La reproducción no reconoce el turno anterior de esta solicitud.")
            if n >= len(self.TURNOS):
                raise ErrorCoordinador("La reproducción no tiene más turnos guardados.")
            self.enviados.append(texto)
            r = json.loads((self.CARPETA / "turnos" / f"turno_ARR1_{self.TURNOS[n]}.json")
                           .read_text(encoding="utf-8"))["respuesta"]
            r["id"] = f"{r['id']}-{uuid.uuid4().hex[:8]}"
            self._cursor[r["id"]] = n + 1
        time.sleep(self.pausa_s)
        return r

    def descargar(self, sesion: str, ruta: str) -> bytes:
        return (self.CARPETA / "paquete" / pathlib.PurePosixPath(ruta).name).read_bytes()
