"""Procedencia propia de B (decisión del comercial, 10-10-2026): por cada tarea A2A, el texto recibido y su SHA-256.

Lo escribe el código del hosted agent, nunca el modelo. Cada tarea correcta deja una entrada en
`trabajo/procedencia/procedencia_a2a.json` con: fase, agente (destino), url, objetivo (brief o lote) y la huella de
lo enviado, hora, task_id, context_id, el texto recibido literal y su SHA-256, y la relectura con `GetTask` hecha con
la identidad del propio hosted agent (la única que puede leer la tarea, LES-G-089.10).

El núcleo mete el fichero en el paquete y lista su SHA-256 en el manifiesto; la puerta local
(`verificar_paquete.py`, `c_procedencia`) lo contrasta con las trazas de cada task_id (las trazas cortan cada mensaje
a 1.024 caracteres: solo prueban el comienzo) y con lo que registró el núcleo.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import tempfile
import types

SCHEMA = "preventa-procedencia-a2a/1"
NOMBRE = "procedencia_a2a.json"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
CLAVES = ("fase", "agente", "url", "objetivo_id", "hora", "task_id", "context_id", "estado_tarea", "sha256_enviado",
          "bytes_enviado", "sha256_recibido", "bytes_recibido", "texto_recibido", "relectura")
# REV-2 (I1.5): una hora posterior a «ahora + margen» no es de una tarea real (reloj o fichero alterado).
MARGEN_FUTURO = dt.timedelta(minutes=5)


class FusionRechazada(ValueError):
    """REV-4 (I1.5): la procedencia del ZIP restaurado no se fusiona (relectura distinta o agente no admitido)."""


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def ruta(trabajo: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(trabajo) / "procedencia" / NOMBRE


def leida_ok(leida) -> bool:
    """La relectura se pudo hacer: sin error, HTTP 200 y con la tarea completada (si no, no hay texto que comparar).
    VER15-4 (I1.6): la misma lista blanca que aplica la puerta local (`verificar_paquete.juicio_relectura`)."""
    return (leida is not None and leida.error is None and type(leida.http) is int and leida.http == 200
            and leida.estado_tarea == "TASK_STATE_COMPLETED")


def relectura(envio, leida, intentos: int = 1) -> dict:
    """Resultado de releer la tarea con GetTask: coincide True/False si se pudo leer; None si falló (con su motivo).
    Decisión 3 del comercial (11-10-2026): todo lo que no sea `coincide: true` deja esa salida NO VERIFICADO en la puerta
    local, y con --estricto no da verde. `intentos`: lecturas hechas (el código repite una vez si la primera falla)."""
    if leida is None:
        return {"metodo": "GetTask", "hora": None, "http": None, "latencia_s": None, "estado_tarea": None,
                "sha256_recibido": None, "coincide": None, "error": "sin task_id: no se puede releer la tarea",
                "intentos": 0}
    ok = leida_ok(leida)
    if ok:
        error = None
    else:
        error = leida.error or f"la tarea está en {leida.estado_tarea}, no completada: no hay texto que comparar"
    return {"metodo": "GetTask", "hora": leida.inicio, "http": leida.http, "latencia_s": leida.latencia_s,
            "estado_tarea": leida.estado_tarea, "sha256_recibido": leida.sha256_recibido if ok else None,
            "coincide": (leida.sha256_recibido == envio.sha256_recibido) if ok else None, "error": error,
            "intentos": intentos}


def entrada(envio, objetivo_id: str, fase: str, leida) -> dict:
    """La entrada de UNA tarea correcta: lo enviado (por su huella), lo recibido (literal) y la relectura."""
    return {"fase": fase, "agente": envio.agente, "url": envio.url, "objetivo_id": objetivo_id, "hora": envio.inicio,
            "task_id": envio.task_id, "context_id": envio.context_id, "estado_tarea": envio.estado_tarea,
            "sha256_enviado": envio.sha256_enviado, "bytes_enviado": envio.bytes_enviado,
            "sha256_recibido": sha256(envio.texto), "bytes_recibido": len(envio.texto.encode("utf-8")),
            "texto_recibido": envio.texto, "relectura": relectura(envio, leida)}


def _instante(valor: object) -> dt.datetime | None:
    """ISO 8601 con zona a UTC; None si no lo es (una hora sin zona no se adivina)."""
    if not isinstance(valor, str):
        return None
    try:
        t = dt.datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(dt.timezone.utc) if t.tzinfo else None


def errores(doc: object, ahora: dt.datetime | None = None) -> list[str]:
    """Forma del documento y coherencia de cada entrada (el SHA-256 del texto es el registrado; la hora, ISO con zona y
    no posterior a «ahora + 5 min», REV-2). La misma regla la aplica la puerta local por su cuenta (no importa este
    módulo)."""
    ahora = ahora or dt.datetime.now(dt.timezone.utc)
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA or not isinstance(doc.get("tareas"), list):
        return [f"no es un documento {SCHEMA} con «tareas»"]
    e, vistos = [], set()
    for i, t in enumerate(doc["tareas"]):
        if not isinstance(t, dict) or set(t) != set(CLAVES):
            e.append(f"tareas[{i}]: claves distintas de las del contrato")
            continue
        if not isinstance(t["texto_recibido"], str) or not t["texto_recibido"]:
            e.append(f"tareas[{i}]: sin texto recibido")
        elif sha256(t["texto_recibido"]) != t["sha256_recibido"]:
            e.append(f"tareas[{i}] ({t['task_id']}): el SHA-256 del texto no es el registrado")
        if not isinstance(t["task_id"], str) or not t["task_id"]:
            e.append(f"tareas[{i}]: sin task_id")
        elif t["task_id"] in vistos:
            e.append(f"tareas[{i}]: task_id repetido {t['task_id']}")
        else:
            vistos.add(t["task_id"])
        if not isinstance(t["sha256_enviado"], str) or not _HEX64.match(t["sha256_enviado"]):
            e.append(f"tareas[{i}]: sha256_enviado no válido")
        hora = _instante(t["hora"])
        if hora is None:
            e.append(f"tareas[{i}]: hora sin formato ISO con zona: {t['hora']!r}")
        elif hora > ahora + MARGEN_FUTURO:
            e.append(f"tareas[{i}]: hora futura {t['hora']} (posterior a ahora + 5 min)")
    return e


def cargar(trabajo: pathlib.Path) -> dict:
    p = ruta(trabajo)
    if not p.is_file():
        return {"schema": SCHEMA, "tareas": []}
    doc = json.loads(p.read_bytes().decode("utf-8"))
    malos = errores(doc)
    if malos:
        raise ValueError(f"{p.name} no cuadra: {'; '.join(malos[:5])}")
    return doc


def _escribir(trabajo: pathlib.Path, doc: dict) -> None:
    """Escritura atómica (temporal y os.replace) y chmod 644: la descarga de un 0600 da HTTP 500 (LES-G-090.4)."""
    p = ruta(trabajo)
    p.parent.mkdir(parents=True, exist_ok=True)
    datos = (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=p.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
        os.chmod(tmp, 0o644)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def anadir(trabajo: pathlib.Path, nueva: dict) -> None:
    """Añade una entrada. La misma tarea dos veces con el mismo contenido no se duplica; con otro, ValueError."""
    malos = errores({"schema": SCHEMA, "tareas": [nueva]})
    if malos:
        raise ValueError("; ".join(malos))
    doc = cargar(trabajo)
    previa = next((t for t in doc["tareas"] if t["task_id"] == nueva["task_id"]), None)
    if previa is not None:
        if previa != nueva:
            raise ValueError(f"la tarea {nueva['task_id']} ya está registrada con otro contenido")
        return
    doc["tareas"].append(nueva)
    _escribir(trabajo, doc)


def fusionar(trabajo: pathlib.Path, datos: bytes, *, releer, agentes) -> tuple[int, list[str]]:
    """Tras RESTAURAR desde un ZIP (paquete o relevo), añade las tareas de su procedencia que no estén en la sesión.
    Devuelve (añadidas, avisos). Nada se pisa: una tarea con el mismo task_id y otro contenido se declara.

    REV-4 (I1.5): la relectura que trae el ZIP no se acepta tal cual. Cada tarea que se va a añadir se relee con
    `releer(agente, task_id)` (GetTask con la identidad del propio hosted, la única que puede leerla) y se guarda esa
    relectura nueva. FusionRechazada (no se añade NADA) si una tarea es de un agente que no está en `agentes` o si su
    relectura devuelve otro texto. Si GetTask no responde, la tarea se añade con la relectura fallida (coincide null):
    la puerta local deja esa salida NO VERIFICADO (decisión 3) y con --estricto no da verde."""
    try:
        doc = json.loads(datos.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return 0, [f"{NOMBRE} del ZIP ilegible: {exc}"]
    malos = errores(doc)
    if malos:
        return 0, [f"{NOMBRE} del ZIP no cuadra (no se fusiona): {'; '.join(malos[:5])}"]
    actual = cargar(trabajo)
    por_id = {t["task_id"]: t for t in actual["tareas"]}
    avisos, nuevas = [], []
    for t in doc["tareas"]:
        previa = por_id.get(t["task_id"])
        if previa is not None:
            if previa != t:
                avisos.append(f"la tarea {t['task_id']} ya está en la sesión con otro contenido: no se pisa")
            continue
        if t["agente"] not in agentes:
            raise FusionRechazada(f"la tarea {t['task_id']} es de {t['agente']!r}, que no es ninguno de los agentes de "
                                  f"esta sesión ({', '.join(sorted(agentes))})")
        try:
            leida = releer(t["agente"], t["task_id"])
        except Exception as exc:  # noqa: BLE001 - se guarda como relectura fallida, con su motivo
            leida = types.SimpleNamespace(inicio=None, http=None, latencia_s=None, estado_tarea=None,
                                          sha256_recibido=None, error=f"{type(exc).__name__}: {str(exc)[:500]}")
        rel = relectura(types.SimpleNamespace(sha256_recibido=t["sha256_recibido"]), leida)
        if rel["coincide"] is False:
            raise FusionRechazada(f"la relectura GetTask de {t['task_id']} devuelve otro texto (SHA-256 "
                                  f"{rel['sha256_recibido']} frente a {t['sha256_recibido']} del ZIP)")
        if rel["coincide"] is None:
            avisos.append(f"no he podido releer la tarea {t['task_id']} con GetTask ({str(rel['error'])[:200]}): queda "
                          "NO VERIFICADO y la puerta local con --estricto no dará verde")
        nuevas.append(dict(t, relectura=rel))
        por_id[t["task_id"]] = nuevas[-1]
    if nuevas:
        actual["tareas"].extend(nuevas)
        _escribir(trabajo, actual)
    return len(nuevas), avisos
