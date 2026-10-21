"""Simulación del arnés sin Azure ni red: transporte, reloj y procesos falsos con dos escenarios.

- «feliz»: todo responde como se espera; `ejecutar.py --simular` debe salir con 0.
- «adverso»: fechas de retirada que no cumplen, 403 en Decision-1, Web Search bloqueada, conexión inexistente,
  un destino sin salida, endpoint sin api-version rechazado y OpenCode fallando por api-version. Sirve para
  comprobar que el arnés falla en alto y clasifica bien (FALLA frente a PENDIENTE_FERNANDO).
Todos los datos son sintéticos y se marcan como tales; las fechas del escenario feliz (2099-12-31) son
deliberadamente imposibles para que nadie las confunda con fechas reales.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from pruebas.paso0a import comun
from pruebas.paso0a.hosted_prueba.ofa_prueba_hosted import ordenes

INICIO_SIMULADO = 1_792_314_000.0   # 2026-10-18T09:00:00Z
ESCENARIOS = ("feliz", "adverso")


class RelojSimulado:
    """Reloj de pared y monótono compartidos; dormir avanza el tiempo sin esperar."""

    def __init__(self, inicio: float = INICIO_SIMULADO) -> None:
        self.t = inicio

    def __call__(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.t += max(0.0, float(s))


@dataclass
class PeticionSimulada:
    metodo: str
    url: str
    params: dict
    json_body: Any
    files: Any
    cabeceras: dict
    timeout: float


@dataclass
class Simulador:
    escenario: str
    reloj: RelojSimulado
    peticiones: list[PeticionSimulada] = field(default_factory=list)
    agentes: dict[str, dict] = field(default_factory=dict)
    respuestas: dict[str, dict] = field(default_factory=dict)
    sondeos: dict[str, int] = field(default_factory=dict)

    @property
    def adverso(self) -> bool:
        return self.escenario == "adverso"

    # -------------------------------------------------------------------------- transporte
    def peticion(self, metodo: str, url: str, *, params: dict | None = None, json_body: Any = None,
                 files: Any = None, data: Any = None, cabeceras: dict | None = None,
                 timeout: float | None = None) -> comun.RespuestaHTTP:
        if timeout is None or timeout <= 0:
            raise AssertionError("toda petición debe llevar tiempo máximo")
        cab = dict(cabeceras or {})
        if not str(cab.get("Authorization", "")).startswith("Bearer "):
            raise AssertionError("petición sin token")
        cab["Authorization"] = "Bearer [simulado]"
        self.peticiones.append(PeticionSimulada(metodo, url, dict(params or {}), json_body, files, cab, timeout))
        estado, cuerpo = self._manejar(metodo, url, dict(params or {}), json_body, files, cab)
        texto = cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False)
        return comun.RespuestaHTTP(estado, texto, {"x-agent-session-id": "ses_simulada"}, 0.05, url)

    def _manejar(self, metodo, url, params, cuerpo, files, cab) -> tuple[int, Any]:
        u = urlparse(url)
        ruta = u.path
        if u.hostname == comun.HOST_ARM:
            return self._arm(ruta)
        if ruta.endswith("/providers/microsoft/v1/systemone"):
            return self._decision(cuerpo)
        m = re.search(r"/api/projects/[^/]+/(.*)$", ruta)
        if not m:
            return 404, {"error": {"message": f"ruta simulada desconocida {ruta}"}}
        return self._datos(metodo, m.group(1), params, cuerpo, files, cab)

    # ------------------------------------------------------------------------------- ARM
    def _arm(self, ruta: str) -> tuple[int, Any]:
        if ruta.endswith("/deployments"):
            desp = []
            for nombre, d in comun.cargar_config()["despliegues"].items():
                desp.append({"name": nombre, "sku": {"name": d["sku"]},
                             "properties": {"model": {"format": "Microsoft" if "Decision" in d["modelo"] else "OpenAI",
                                                      "name": d["modelo"], "version": d.get("version", "1")}}})
            return 200, {"value": desp}
        if ruta.endswith("/models"):
            modelos = []
            for nombre, d in comun.cargar_config()["despliegues"].items():
                fecha = "2099-12-31T00:00:00Z"   # SINTÉTICA, imposible a propósito
                if self.adverso and d["modelo"] == "gpt-5.6-luna":
                    fecha = "2028-01-11T00:00:00Z"
                entrada = {"format": "Microsoft" if "Decision" in d["modelo"] else "OpenAI",
                           "name": d["modelo"], "version": d.get("version", "1"),
                           "lifecycleStatus": "GenerallyAvailable",
                           "skus": [{"name": d["sku"], "deprecationDate": fecha}]}
                if not (self.adverso and d["modelo"] == "Microsoft-Decision-1"):
                    entrada["deprecation"] = {"inference": fecha}
                else:
                    entrada["skus"] = [{"name": d["sku"]}]
                modelos.append({"model": entrada} if nombre == "text-embedding-3-large" else entrada)
            return 200, {"value": modelos}
        if "/connections/" in ruta:
            if self.adverso:
                return 404, {"error": {"code": "NotFound", "message": "Connection not found (simulado)"}}
            return 200, {"name": comun.CONEXION_MARCADOR, "properties": {"category": "CustomKeys", "credentials": None}}
        return 404, {"error": {"message": "ARM simulado: ruta desconocida"}}

    # -------------------------------------------------------------------------- Decision-1
    def _decision(self, cuerpo: dict) -> tuple[int, Any]:
        if self.adverso:
            return 403, {"error": {"code": "PermissionDenied", "message": "The principal lacks the data action (simulado)"}}
        nombre, q = next(iter(cuerpo["questions"].items()))
        if q["type"] == "noul":
            ans = {"type": "noul", "probability": 0.97}
        elif q["type"] == "choice":
            ans = {"type": "choice", "choice": "rag", "probabilities": {"rag": 0.9, "agente_con_herramientas": 0.07,
                                                                        "clasificacion": 0.03}}
        else:
            ans = {"type": "score", "score": 2.6, "probabilities": [0.0, 0.1, 0.2, 0.7]}
        return 200, {"model": "microsoft-decision-1", "answers": {nombre: ans},
                     "usage": {"input_tokens": 50, "output_tokens": 1}}

    # ------------------------------------------------------------------------ plano de datos
    def _datos(self, metodo, ruta, params, cuerpo, files, cab) -> tuple[int, Any]:
        partes = ruta.split("/")
        if partes[0] == "agents" and len(partes) == 1 and metodo == "POST":
            return self._crear_agente(cuerpo, files, cab)
        if partes[0] == "agents" and len(partes) == 2 and metodo == "GET":
            a = self.agentes.get(partes[1])
            return (200, a) if a else (404, {"error": {"code": "not_found", "message": "Agent not found"}})
        if partes[0] == "agents" and len(partes) == 3 and partes[2] == "versions" and metodo == "POST":
            return self._crear_agente(cuerpo, files, cab, nombre=partes[1])
        if partes[0] == "agents" and len(partes) == 4 and partes[2] == "versions":
            return self._version(partes[1], partes[3])
        if partes[0] == "agents" and "endpoint" in partes:
            return self._hosted(metodo, partes, params, cuerpo)
        if ruta == "openai/v1/responses" and metodo == "POST":
            return self._lanzar_prompt(cuerpo)
        if ruta.startswith("openai/v1/responses/") and metodo == "GET":
            return self._sondear_prompt(partes[-1])
        return 404, {"error": {"message": f"ruta de datos simulada desconocida {ruta}"}}

    def _crear_agente(self, cuerpo, files, cab, nombre: str | None = None) -> tuple[int, Any]:
        if files:
            meta = json.loads(files["metadata"][1])
            nombre = nombre or cab.get("x-ms-agent-name")
            if not cab.get("x-ms-code-zip-sha256"):
                return 400, {"error": {"message": "falta x-ms-code-zip-sha256"}}
            defi = meta["definition"]
        else:
            nombre = nombre or cuerpo.get("name")
            defi = cuerpo["definition"]
        if self.adverso and any(t.get("type") == "web_search" for t in defi.get("tools") or []):
            return 400, {"error": {"code": "invalid_request_error",
                                   "message": "Tool 'web_search' is blocked for this subscription "
                                              "(OpenAI.BlockedTools.web_search) (simulado)"}}
        previo = self.agentes.get(nombre)
        version = str(int(previo["versions"]["latest"]["version"]) + 1) if previo else "1"
        estado = "creating" if defi.get("kind") == "hosted" else "active"
        self.agentes[nombre] = {"name": nombre, "versions": {"latest": {"version": version, "status": estado}},
                                "_sondeos_version": 0}
        return 200, self.agentes[nombre]

    def _version(self, nombre: str, version: str) -> tuple[int, Any]:
        a = self.agentes.get(nombre)
        if not a:
            return 404, {"error": {"message": "Agent not found"}}
        a["_sondeos_version"] += 1
        estado = "active" if a["_sondeos_version"] >= 2 else "creating"
        return 200, {"name": nombre, "version": version, "status": estado}

    def _lanzar_prompt(self, cuerpo: dict) -> tuple[int, Any]:
        texto = json.dumps(cuerpo.get("input"), ensure_ascii=False)
        tipo = "mcp" if "microsoft_docs_search" in texto else "web"
        rid = f"resp_sim_{len(self.respuestas) + 1}"
        self.respuestas[rid] = {"tipo": tipo, "t0": self.reloj()}
        return 200, {"id": rid, "status": "queued"}

    def _sondear_prompt(self, rid: str) -> tuple[int, Any]:
        info = self.respuestas.get(rid)
        if not info:
            return 404, {"error": {"message": "response not found"}}
        self.sondeos[rid] = self.sondeos.get(rid, 0) + 1
        if self.sondeos[rid] < 2:
            return 200, {"id": rid, "status": "in_progress"}
        if info["tipo"] == "mcp":
            salida = [{"type": "mcp_list_tools", "server_label": "mslearn"},
                      {"type": "mcp_call", "server_label": "mslearn", "name": "microsoft_docs_search", "error": None},
                      {"type": "message", "content": [{"type": "output_text", "text": "python_3_13, python_3_14 (simulado)"}]}]
        else:
            salida = [{"type": "web_search_call", "status": "completed"},
                      {"type": "message", "content": [{"type": "output_text", "text": "requests (simulado)"}]}]
        return 200, {"id": rid, "status": "completed", "output": salida}

    def _hosted(self, metodo, partes, params, cuerpo) -> tuple[int, Any]:
        if metodo == "GET":
            rid = partes[-1]
            info = self.respuestas.get(rid)
            if not info:
                return 404, {"error": {"message": "response not found"}}
            if self.reloj() - info["t0"] < info["segundos"]:
                return 200, {"id": rid, "status": "in_progress"}
            res = {"orden": "TURNO_LARGO", "resultado": "TURNO_LARGO COMPLETADO",
                   "segundos_pedidos": info["segundos"], "segundos_medidos": float(info["segundos"]) + 0.4}
            return 200, self._respuesta_texto(rid, res)
        if "api-version" not in params and self.adverso:
            return 400, {"error": {"code": "missing_api_version",
                                   "message": "Missing required query parameter 'api-version' (simulado)"}}
        texto = ordenes.ultimo_texto_usuario(cuerpo.get("input"))
        orden, arg = ordenes.interpretar(texto)
        if orden == "TURNO_LARGO" and cuerpo.get("background"):
            rid = f"caresp_sim{len(self.respuestas) + 1}"
            self.respuestas[rid] = {"t0": self.reloj(), "segundos": ordenes.segundos_turno(arg)}
            return 200, {"id": rid, "status": "in_progress", "agent_session_id": "ses_simulada"}
        if orden == "SALIDA":
            res = {"orden": "SALIDA", "resultados": [
                {"url": ordenes.URLS_SALIDA[0], "http": 200, "segundos": 0.2},
                {"url": ordenes.URLS_SALIDA[1], "http": 200, "segundos": 0.3},
                ({"url": ordenes.URLS_SALIDA[2], "error": "URLError: [Errno -2] Name or service not known (simulado)",
                  "segundos": 0.1} if self.adverso else {"url": ordenes.URLS_SALIDA[2], "http": 400, "segundos": 0.1})]}
        elif orden == "MARCADOR":
            entorno = {} if self.adverso else {ordenes.VARIABLE_MARCADOR: ordenes.VALOR_SINTETICO}
            res = {"orden": "MARCADOR", **ordenes.leer_marcador(entorno)}
        elif orden == "ECO":
            res = ordenes.eco(arg)
        else:
            res = ordenes.ayuda()
        return 200, self._respuesta_texto(f"caresp_sim{len(self.respuestas) + 100}", res)

    @staticmethod
    def _respuesta_texto(rid: str, res: dict) -> dict:
        return {"id": rid, "status": "completed",
                "output": [{"type": "message", "role": "assistant",
                            "content": [{"type": "output_text", "text": json.dumps(res, ensure_ascii=False)}]}]}

    # ----------------------------------------------------------------------------- procesos
    def proceso(self, cmd: list[str], **kw) -> subprocess.CompletedProcess:
        """Doble de subprocess.run para `opencode run`. Comprueba el aislamiento antes de «ejecutar»."""
        env = kw.get("env") or {}
        if "XDG_CONFIG_HOME" not in env or not pathlib.Path(kw.get("cwd", "")).joinpath("opencode.json").is_file():
            raise AssertionError("opencode debe correr aislado en su directorio temporal")
        arg = cmd[-1]
        m = re.search(r"ORDEN:\s*ECO\s+(\S+)", arg)
        if self.adverso:
            return subprocess.CompletedProcess(cmd, 1, "", "AI_APICallError: Missing required query parameter "
                                                           "'api-version' (simulado)")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(ordenes.eco(m.group(1) if m else "")), "")


def contexto(escenario: str, dir_resultados: pathlib.Path, dir_progreso: pathlib.Path,
             dir_temporal: pathlib.Path, zip_simulado: pathlib.Path) -> tuple[comun.Contexto, Simulador]:
    if escenario not in ESCENARIOS:
        raise comun.ErrorArnes(f"Escenario desconocido: {escenario!r} (admitidos: {ESCENARIOS})")
    reloj = RelojSimulado()
    sim = Simulador(escenario, reloj)
    cfg = comun.cargar_config()
    cliente = comun.ClientePruebas(cfg, sim, lambda aud: "token-simulado", monotono=reloj)
    ctx = comun.Contexto(cfg=cfg, cliente=cliente, dir_resultados=dir_resultados, dir_progreso=dir_progreso,
                         reloj=reloj, monotono=reloj, dormir=reloj.dormir, proceso=sim.proceso, simulado=True,
                         presupuesto_s=1e9, escribir=lambda s: None,
                         opciones={"zip": str(zip_simulado), "dir_temporal": str(dir_temporal),
                                   "opencode": "opencode", "nonce": "simulado"})
    return ctx, sim


def construir_zip_simulado(destino: pathlib.Path) -> pathlib.Path:
    """ZIP pequeño con la forma real (main.py, órdenes y un paquete mínimo) para el paso de comprobación."""
    from pruebas.paso0a.hosted_prueba import empaquetar
    contenido = empaquetar.contenido_zip(empaquetar.AQUI, pathlib.Path("no-existe"))
    contenido["packages/azure/ai/agentserver/responses/__init__.py"] = b"# simulado\n"
    import hashlib
    man = {"schema": "ofa-prueba-hosted-manifiesto/1", "simulado": True,
           "ficheros": {r: {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for r, b in sorted(contenido.items())}}
    contenido["MANIFIESTO-HOSTED.json"] = json.dumps(man).encode("utf-8")
    empaquetar.escribir_zip(contenido, destino)
    return destino
