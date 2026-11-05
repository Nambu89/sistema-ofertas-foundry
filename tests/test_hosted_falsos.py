"""Dobles para las pruebas del hosted agent: servidor A2A falso, modelo falso y un Coordinador de prueba.

No contiene pruebas. El A2A falso devuelve las respuestas de esquemas/ejemplos/ con el eco literal de lo que
recibe (como hace el experto real) y guarda todo lo recibido para comprobar que el código envía EXACTAMENTE
el brief y el consolidado que generó el núcleo.
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
import re
import sys

import pytest

# VPROT-3 (I1.9): el cliente A2A contrasta la identidad («oid» del JWT) con que se creó una tarea antes de darla por
# perdida. Token con forma de JWT compuesto en tiempo de ejecución (sin firma ni secreto: solo la carga).
OID_PRUEBA = "00000000-0000-4000-8000-0000000000b1"
OID_OTRA = "00000000-0000-4000-8000-0000000000c2"


def token_prueba(oid: str = OID_PRUEBA) -> str:
    import base64
    carga = base64.urlsafe_b64encode(json.dumps({"oid": oid}).encode()).decode().rstrip("=")
    return f"cabecera.{carga}.firma"

httpx = pytest.importorskip("httpx")

RAIZ = pathlib.Path(__file__).resolve().parents[1]
HOSTED = RAIZ / "hosted"
EJ = RAIZ / "esquemas" / "ejemplos"
TRANSCRIPCION = RAIZ / "datos_prueba" / "transcripcion_sintetica_I1.txt"
PROYECTO = "https://falso.services.ai.azure.com/api/projects/falso"
# Núcleo con el que corren las pruebas: el del repositorio o, con HOSTED_PRUEBA_NUCLEO, una copia (p. ej. con
# un parche de otro papel aún sin integrar). Debe tener sandbox/ y esquemas/ como el repositorio.
NUCLEO = pathlib.Path(os.environ.get("HOSTED_PRUEBA_NUCLEO") or RAIZ / "sandbox")
_WINDOWS = pathlib.Path("C:/Users/usuario/Proyectos")  # solo como último recurso, si existe
PROYECTOS = pathlib.Path((os.environ.get("PREVENTA_PROYECTOS") or "").strip() or pathlib.Path.home() / "Proyectos")
PROYECTOS = PROYECTOS if PROYECTOS.is_dir() or not _WINDOWS.is_dir() or (os.environ.get("PREVENTA_PROYECTOS") or "").strip() else _WINDOWS  # fijada: se respeta
if str(HOSTED) not in sys.path:
    sys.path.insert(0, str(HOSTED))

ALTA = (RAIZ / "tests" / "insumos" / "T1_alta.txt").read_text(encoding="utf-8")


def ejemplo(nombre: str) -> dict:
    return json.loads((EJ / f"{nombre}.json").read_text(encoding="utf-8"))


def entorno_recursos(monkeypatch) -> None:
    monkeypatch.setenv("PREVENTA_CATALOGO", str(RAIZ / "sandbox" / "datos" / "catalogo_componentes.json"))
    monkeypatch.setenv("PREVENTA_RATE_CARD", str(RAIZ / "tests" / "insumos" / "rate-card.sintetica.json"))
    # integrador I1.7: la instantánea de precios del catálogo montado (en el ZIP va en recursos/)
    monkeypatch.setenv("PREVENTA_PRECIOS", str(RAIZ / "sandbox" / "datos" / "precios_instantanea.json"))
    monkeypatch.setenv("PREVENTA_GENERADOR", str(PROYECTOS / "_templates" / "estimacion" / "generar_estimacion.py"))
    monkeypatch.setenv("PREVENTA_PLANTILLA", str(PROYECTOS / "_templates" / "estimacion" / "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx"))
    for v in ("PREVENTA_TRABAJO", "PREVENTA_RAIZ", "PREVENTA_DATOS", "PREVENTA_MONTAJE", "PREVENTA_APP", "PREVENTA_TMP"):
        monkeypatch.delenv(v, raising=False)


TIPOS = {"REF": "referencia", "C": "componente", "P": "precio"}
# ARR13-4: el esquema vigente del verificador puede exigir «campo» por elemento; el doble lo pone solo si lo exige.
_CAMPO = '"campo"' in (RAIZ / "esquemas" / "respuesta_verificador.json").read_text(encoding="utf-8")


def verificacion_ok(texto: str) -> dict:
    """Respuesta del verificador con todo OK, según el esquema vigente (un veredicto por id enviado)."""
    ids = re.findall(r"^((REF|C|P)-[0-9]{2}) \|", texto, re.M)
    elementos = [{"id": i, "tipo": TIPOS[t], "veredicto": "OK", "detalle": "Comprobado contra la fuente oficial.",
                  "valor_correcto": None, "fuente_url": None} for i, t in ids]
    if _CAMPO:
        for e in elementos:
            e["campo"] = "ninguno"
    return {"agente": "preventa-verificador",
            "consolidado_id": re.search(r"^consolidado_id: (\S+)$", texto, re.M).group(1),
            "entrada_recibida_inicio": "\n".join(texto.split("\n")[:3]), "elementos": elementos,
            "resumen": {"ok": len(elementos), "discrepa": 0, "observacion": 0, "no_verificable": 0},
            "herramientas_usadas": {"microsoft_docs_search": 1, "microsoft_docs_fetch": 0}}  # I1.7: sin precios_azure


class A2AFalso:
    """Servidor A2A JSON-RPC v1.0 falso. `fallos` es una cola de respuestas forzadas por SendMessage. GetTask (la
    relectura de la procedencia de B) devuelve la tarea guardada, va aparte (`relecturas`) y tiene su propia cola
    (`fallos_gettask`); `alterar_gettask` cambia el texto releído (como si la plataforma devolviera otro)."""

    def __init__(self):
        self.recibidos: list[dict] = []
        self.fallos: list = []
        self.n = 0
        self.tareas: dict[str, dict] = {}
        self.relecturas: list[dict] = []
        self.fallos_gettask: list = []
        self.alterar_gettask = False

    def _get_task(self, cuerpo: dict, agente: str) -> httpx.Response:
        self.relecturas.append({"agente": agente, "cuerpo": cuerpo})
        if self.fallos_gettask:
            f = self.fallos_gettask.pop(0)
            if isinstance(f, Exception):
                raise f
            return f
        tarea = copy.deepcopy(self.tareas.get(cuerpo["params"]["id"]))
        if tarea is None:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": cuerpo["id"], "error": {
                "code": -32001, "message": "Task does not exist or is not accessible",
                "data": [{"reason": "TASK_NOT_FOUND"}]}})
        if self.alterar_gettask:
            tarea["artifacts"][0]["parts"][0]["text"] += " "
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": cuerpo["id"], "result": tarea})

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(peticion.content)
        agente = peticion.url.path.split("/agents/")[1].split("/")[0]
        if cuerpo.get("method") == "GetTask":
            return self._get_task(cuerpo, agente)
        self.recibidos.append({"agente": agente, "cuerpo": cuerpo, "cabeceras": dict(peticion.headers)})
        if self.fallos:
            f = self.fallos.pop(0)
            if isinstance(f, Exception):
                raise f
            return f
        self.n += 1
        if cuerpo["method"] != "SendMessage":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": cuerpo["id"],
                                             "error": {"code": -32601, "message": "Method not found"}})
        texto = cuerpo["params"]["message"]["parts"][0]["text"]
        if texto.startswith(("BRIEF-PREVENTA/1", "REINTENTO-PREVENTA/1")):
            # PR17-6 parte 2 (I1.8): un reintento lleva delante el motivo del rechazo; el experto devuelve en
            # brief_recibido el brief desde la línea BRIEF-PREVENTA/1 (instrucción vigente)
            texto = texto[re.search(r"^BRIEF-PREVENTA/1$", texto, re.M).start():]
            r = ejemplo("respuesta_experto")
            r["brief_recibido"] = texto
            r["brief_id"] = re.search(r"^brief_id: (\S+)$", texto, re.M).group(1)
        else:
            r = verificacion_ok(texto)
        tarea = {"id": f"resp_falso{self.n:04d}", "contextId": f"ctxt_falso{self.n:04d}",
                 "status": {"state": "TASK_STATE_COMPLETED"},
                 "artifacts": [{"artifactId": f"msg_{self.n}", "parts": [{"text": json.dumps(r, ensure_ascii=False)}]}]}
        self.tareas[tarea["id"]] = copy.deepcopy(tarea)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": cuerpo["id"], "result": {"task": tarea}})


class ModeloFalso:
    """Responses API falsa: devuelve requisitos.json del ejemplo, con lo ASUMIDO en FALTA (como haría el modelo)."""

    def __init__(self):
        self.peticiones: list[dict] = []
        self.status = 200

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(peticion.content)
        self.peticiones.append(cuerpo)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"code": "falso", "message": "fallo forzado"}})
        req = copy.deepcopy(ejemplo("requisitos"))
        for k, v in req["campos"].items():
            if v["estado"] == "ASUMIDO":
                req["campos"][k] = {"estado": "FALTA", "entradas": []}
        salida = [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(req, ensure_ascii=False)}]}]
        return httpx.Response(200, json={"id": "resp_modelo", "model": cuerpo["model"], "status": "completed",
                                         "output": salida, "usage": {"input_tokens": 1, "output_tokens": 1}})


def coordinador(tmp_path: pathlib.Path, monkeypatch, a2a: A2AFalso | None = None, modelo: ModeloFalso | None = None,
                **env_extra):
    from preventa_hosted import config
    from preventa_hosted.turno import Coordinador
    entorno_recursos(monkeypatch)
    monkeypatch.setenv("PREVENTA_ORQUESTADOR", "B")   # lo fija main.marcar_orquestador al arrancar el agente (I1.5)
    env = {"FOUNDRY_PROJECT_ENDPOINT": PROYECTO, "PREVENTA_HOME": str(tmp_path / "home"),
           "PREVENTA_APP_NUCLEO": str(NUCLEO), **env_extra}
    cfg = config.cargar(env)
    a2a, modelo = a2a or A2AFalso(), modelo or ModeloFalso()
    c = Coordinador(cfg, token_prueba, transporte_a2a=httpx.MockTransport(a2a),
                    transporte_http=httpx.MockTransport(modelo))
    return c, a2a, modelo


def adjunto_transcripcion() -> dict:
    import base64
    datos = base64.b64encode(TRANSCRIPCION.read_bytes()).decode()
    return {"filename": "transcripcion_sintetica_I1.txt", "file_data": f"data:text/plain;base64,{datos}",
            "file_id": None, "file_url": None}
