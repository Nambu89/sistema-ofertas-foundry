"""Máquina de estados de I1 (CONTRATOS.md §3, §4.4, §5.3 y §11.3).

Las funciones mutan el estado en sitio y no imprimen ni guardan, salvo `guardar`, que es la
única que escribe `estado.json` (temporal + os.replace + chmod 644; en Windows, cada reintento de
os.replace se avisa en stderr, ARRSN-1). `transitar` rechaza
cualquier transición que no esté en TRANSICIONES con TransicionNoPermitida.
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import pathlib
import sys
import tempfile
import time

from nucleo import esquema, hashes
from nucleo.errores import EntradaInvalida, IntegridadRota, TransicionNoPermitida

SIN_ESTADO = "SIN_ESTADO"
ESTADOS: tuple[str, ...] = (
    "BORRADOR", "INFORMACION_INSUFICIENTE", "EN_ANALISIS", "EN_VERIFICACION", "VERIFICADA",
    "STOP_PRESUPUESTO", "LISTA_PARA_REVISION", "EN_REVISION_PREVENTA", "EN_APROBACION_AREA",
    "APROBADA", "DEVUELTA_CON_COMENTARIOS", "BLOQUEADA",
)
FASES = ("T1", "T2", "T3", "T4")
MAX_INTENTOS = 3
MAX_RONDAS = 3
REVISION = ("LISTA_PARA_REVISION", "EN_REVISION_PREVENTA", "EN_APROBACION_AREA", "APROBADA")
_TODOS_MENOS_APROBADA = tuple(e for e in ESTADOS if e not in ("APROBADA", "BLOQUEADA"))


def _f(*destinos: str) -> frozenset[str]:
    return frozenset(destinos)


TRANSICIONES: dict[str, dict[str, frozenset[str]]] = {
    "iniciar": {SIN_ESTADO: _f("BORRADOR")},
    "restaurar": {SIN_ESTADO: _f(*ESTADOS)},
    "suficiencia": {e: _f("INFORMACION_INSUFICIENTE", "EN_ANALISIS")
                    for e in ("BORRADOR", "INFORMACION_INSUFICIENTE", "DEVUELTA_CON_COMENTARIOS")},
    "asumir": {e: _f("INFORMACION_INSUFICIENTE", "EN_ANALISIS")
               for e in ("INFORMACION_INSUFICIENTE", "DEVUELTA_CON_COMENTARIOS")},
    "enrutar": {"EN_ANALISIS": _f("EN_ANALISIS"), "DEVUELTA_CON_COMENTARIOS": _f("EN_ANALISIS")},
    "registrar-experto": {"EN_ANALISIS": _f("EN_ANALISIS")},
    "consolidar": {"EN_ANALISIS": _f("EN_VERIFICACION"), "DEVUELTA_CON_COMENTARIOS": _f("EN_VERIFICACION"),
                   "EN_VERIFICACION": _f("EN_VERIFICACION")},
    "registrar-verificacion": {"EN_VERIFICACION": _f("VERIFICADA", "EN_ANALISIS")},
    "anexo-consumo": {"VERIFICADA": _f("VERIFICADA"), "DEVUELTA_CON_COMENTARIOS": _f("VERIFICADA")},
    "estimar": {e: _f("VERIFICADA", "STOP_PRESUPUESTO")
                for e in ("VERIFICADA", "STOP_PRESUPUESTO", "DEVUELTA_CON_COMENTARIOS")},
    "paquete": {"VERIFICADA": _f("LISTA_PARA_REVISION"), **{e: _f(e) for e in REVISION}},
    "decision": {
        "LISTA_PARA_REVISION": _f("EN_REVISION_PREVENTA"),
        "EN_REVISION_PREVENTA": _f("EN_APROBACION_AREA", "DEVUELTA_CON_COMENTARIOS"),
        "EN_APROBACION_AREA": _f("APROBADA", "DEVUELTA_CON_COMENTARIOS"),
        "STOP_PRESUPUESTO": _f("VERIFICADA", "STOP_PRESUPUESTO"),
        "VERIFICADA": _f("VERIFICADA"),
        "BLOQUEADA": _f(*(e for e in ESTADOS if e not in ("APROBADA", "BLOQUEADA"))),
    },
    "registrar-fallo": {**{e: _f(e, "BLOQUEADA") for e in _TODOS_MENOS_APROBADA}, "BLOQUEADA": _f("BLOQUEADA")},
    "bloquear": {e: _f("BLOQUEADA") for e in _TODOS_MENOS_APROBADA},
}
# Subcomandos que se admiten con el estado en BLOQUEADA (CONTRATOS.md §2, notas).
EN_BLOQUEADA = ("estado", "entorno", "registrar-fallo", "decision")

# §5.3: lo que se anula cuando cambia cada bloque (la clave es lo que CAMBIA).
CASCADA: dict[str, tuple[str, ...]] = {
    "requisitos": ("respuestas_expertos", "consolidado", "verificacion", "anexo_consumo", "estimacion", "textos_cliente"),
    "respuestas_expertos": ("consolidado", "verificacion", "anexo_consumo", "estimacion", "textos_cliente"),
    "consolidado": ("anexo_consumo", "estimacion", "textos_cliente"),
    "verificacion": ("anexo_consumo", "estimacion", "textos_cliente"),
    "anexo_consumo": ("estimacion", "textos_cliente"),
    "estimacion": ("textos_cliente",),
    "textos_cliente": (),
    "devuelta": ("estimacion", "textos_cliente"),
}
_VACIO = {"respuestas_expertos": {}}

# Multinube (04-11-2026, esquemas/MULTINUBE.md): pilar de la solicitud, fijado en el alta (carga.alta.pilar, dentro del
# hash). Lista blanca que falla en alto (LES-G-060); sin la clave es «azure», así que un estado anterior no cambia ni un byte.
# Notas del comercial (04-11-2026, esquemas/NOTAS_COMERCIAL.md): fuentes del alta de las que se cita un requisito
# (origen CITADO). La transcripción ya no es obligatoria: el alta trae al menos una de las dos.
FUENTES_DEL_ALTA = ("TRANSCRIPCION", "NOTAS_COMERCIAL")


def fuentes_del_alta(est: dict | None) -> list[dict]:
    """Las fuentes de la reunión y de las notas del comercial, en su orden (sin las aclaraciones)."""
    return [f for f in (((est or {}).get("carga") or {}).get("fuentes") or [])
            if isinstance(f, dict) and f.get("tipo") in FUENTES_DEL_ALTA]


def sin_grabacion(est: dict | None) -> bool:
    """Ninguna fuente del alta es una transcripción: los requisitos salen de las notas del comercial."""
    return not any(f.get("tipo") == "TRANSCRIPCION" for f in fuentes_del_alta(est))


# Frase destacada de la nota del revisor y del mensaje al responsable de preventa cuando no hay grabación (interna: nunca en el PPTX).
AVISO_SIN_GRABACION = ("Sin grabación: los requisitos salen de las notas del comercial; revisa con él lo que no esté "
                       "escrito.")


def con_notas(est: dict | None) -> bool:
    return any(f.get("tipo") == "NOTAS_COMERCIAL" for f in fuentes_del_alta(est))


PILARES = ("azure", "gcp", "aws")
PILAR_POR_DEFECTO = "azure"
SIGLA_PILAR = {"azure": "AZ", "gcp": "GCP", "aws": "AWS"}   # en el brief_id: BRF-<código>-<sigla>-R<n>


def pilar_de_carga(carga: dict | None) -> str:
    """Pilar de la solicitud (carga.alta.pilar; «azure» sin alta o sin la clave). EntradaInvalida si no es de la lista."""
    alta = (carga or {}).get("alta") or {}
    valor = alta.get("pilar", PILAR_POR_DEFECTO) if isinstance(alta, dict) else PILAR_POR_DEFECTO
    if valor not in PILARES:
        raise EntradaInvalida(f"Pilar no admitido: {valor!r}", [f"admitidos: {', '.join(PILARES)}"])
    return valor


def registro_de_carga(carga: dict | None) -> dict:
    """Registro del experto del pilar (carga.respuestas_expertos[<pilar>]); {} si no hay."""
    reg = ((carga or {}).get("respuestas_expertos") or {}).get(pilar_de_carga(carga))
    return reg if isinstance(reg, dict) else {}


def pilar(est: dict | None) -> str:
    return pilar_de_carga((est or {}).get("carga"))


def registro_experto(est: dict | None) -> dict:
    return registro_de_carga((est or {}).get("carga"))

# Esquemas propios de cada bloque (la descripción de esquemas/estado.json lo exige).
_BLOQUES = (
    ("requisitos", lambda e: [e["carga"].get("requisitos")]),
    ("brief", lambda e: list(e["carga"].get("briefs") or [])),
    # I1.7 (CAMBIOS-I17-P §5.1): el bloque guardado es la respuesta COMPLETADA por el núcleo (lo del modelo + lo que pone el código)
    ("respuesta_experto_completa", lambda e: [registro_experto(e).get("respuesta")]),
    ("respuesta_verificador", lambda e: [(e["carga"].get("verificacion") or {}).get("respuesta")]),
    ("anexo_consumo", lambda e: [e["carga"].get("anexo_consumo")]),
    ("estimacion_entrada", lambda e: [(e["carga"].get("estimacion") or {}).get("entrada")]),
    ("textos_cliente", lambda e: [e["carga"].get("textos_cliente")]),
    ("decision", lambda e: list(e.get("decisiones") or [])),
)


def _zona():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Madrid")
    except Exception:  # sin tzdata (Windows sin el paquete): hora local con su desfase
        return None


def ahora() -> datetime.datetime:
    """Fecha y hora de Europe/Madrid (o la local con desfase si no hay tzdata)."""
    z = _zona()
    return datetime.datetime.now(z) if z else datetime.datetime.now().astimezone()


def ahora_ts() -> str:
    """ISO 8601 con zona, a segundos. Solo para control_versiones, fallos y decisiones."""
    return ahora().replace(microsecond=0).isoformat()


def _dt(ts: object) -> datetime.datetime | None:
    """ts ISO con zona -> datetime con zona; None si no se puede leer o no lleva zona."""
    try:
        d = datetime.datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return d if d.tzinfo is not None else None


def _ts_no_antes_de(previos: list[tuple[object, bool]]) -> str:
    """REV-5: ahora_ts(), pero nunca antes de cada ts previo (y estrictamente después si su bool es True).

    Con marcas a segundos, un fallo y el control anterior podían compartir segundo y no se sabía cuál fue antes;
    así el registro de fallos y controles queda ordenado y rechazo_pendiente lo deduce sin ambigüedad.
    """
    t = ahora().replace(microsecond=0)
    for ts, estricto in previos:
        p = _dt(ts)
        if p is None:
            continue
        minimo = p + datetime.timedelta(seconds=1) if estricto else p
        if t < minimo:
            t = minimo  # con la zona del registro previo: el mismo instante que él (+1 s si es estricto)
    return t.isoformat()


def hoy() -> datetime.date:
    """Fecha de hoy en Europe/Madrid."""
    return ahora().date()


def nuevo(alta: dict, fuente: dict, *otras: dict) -> dict:
    """Estado v0 en BORRADOR, versión A, con `carga` completa (CLAVES_CARGA) y artefactos vacíos. `otras`: más fuentes
    del alta (las notas del comercial tras la transcripción, NOTAS_COMERCIAL.md)."""
    carga = {k: None for k in hashes.CLAVES_CARGA}
    carga.update(alta=copy.deepcopy(alta), fuentes=[copy.deepcopy(f) for f in (fuente, *otras)], briefs=[],
                 respuestas_expertos={})
    est = {
        "schema": "preventa-estado/1",
        "codigo": f"OF-{alta['codigo_cliente']}-{alta['seqof']}-A",
        "version": "A", "estado": "BORRADOR", "estado_previo": None, "motivo_bloqueo": None,
        "carga": carga, "hash_contenido": "0" * 64, "decisiones": [],
        "intentos": {f: 0 for f in FASES}, "ronda_verificacion": 0, "fallos": [], "control_versiones": [],
        "artefactos": {k: None for k in ("xlsx_estimacion", "anexo_xlsx", "anexo_json", "pptx", "docx", "zip")},
    }
    est["hash_contenido"] = hashes.hash_contenido(est)
    return est


def ruta_estado(raiz: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(raiz) / "estado.json"


def existe(raiz: pathlib.Path) -> bool:
    return ruta_estado(raiz).is_file()


def errores_estado(est: object) -> list[str]:
    """Errores de forma: esquema estado, esquema de cada bloque y coherencia de codigo/version."""
    if not isinstance(est, dict):
        return ["$: estado.json no es un objeto JSON"]
    errores = list(esquema.validar(est, esquema.cargar("estado")))
    if errores:
        return errores
    for nombre, extraer in _BLOQUES:
        sub = esquema.cargar_pilar(nombre, pilar(est))   # multinube: en Azure, el esquema de siempre
        for i, inst in enumerate(extraer(est)):
            if inst is not None:
                errores += [f"[{nombre} {i}] {e}" for e in esquema.validar(inst, sub)]
    alta = est["carga"]["alta"]
    esperado = f"OF-{alta['codigo_cliente']}-{alta['seqof']}-{est['version']}"
    if est["codigo"] != esperado:
        errores.append(f"$.codigo: {est['codigo']} no cuadra con alta y versión ({esperado})")
    ajenos = sorted(set(est["carga"].get("respuestas_expertos") or {}) - {pilar(est)})
    if ajenos:  # multinube: solo el experto del pilar de la solicitud
        errores.append(f"$.carga.respuestas_expertos: {ajenos} no es el pilar de la solicitud ({pilar(est)})")
    return errores


def cargar(raiz: pathlib.Path) -> dict:
    """Lee y valida estado.json. EntradaInvalida si no existe o no valida; IntegridadRota si el
    hash_contenido guardado no es el recalculado (alguien tocó la carga a mano)."""
    ruta = ruta_estado(raiz)
    if not ruta.is_file():
        raise EntradaInvalida(f"No existe {ruta}", ["ejecutar iniciar o restaurar"])
    try:
        est = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise EntradaInvalida(f"estado.json ilegible: {e}", [str(e)]) from e
    errores = errores_estado(est)
    if errores:
        raise EntradaInvalida("estado.json no valida contra su esquema", errores)
    recalculado = hashes.hash_contenido(est)
    if recalculado != est["hash_contenido"]:
        raise IntegridadRota("hash_contenido de estado.json no cuadra con su carga",
                             [f"guardado {est['hash_contenido']}", f"recalculado {recalculado}"])
    return est


# ARRSN-1 (I1.2): en Windows, os.replace falla con PermissionError (WinError 5) si otro proceso (antivirus,
# indexador) tiene abierto un instante el fichero destino. Reintento acotado, solo en Windows, cada uno anotado en
# REINTENTOS_REPLACE y en stderr; si persiste, el error sale tal cual con una nota. En Linux (Foundry) no aplica.
ES_WINDOWS = os.name == "nt"
ESPERAS_REPLACE: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4, 0.8)
REINTENTOS_REPLACE: list[str] = []


def _reemplazar(tmp: str, ruta: pathlib.Path) -> None:
    for n, espera in enumerate(ESPERAS_REPLACE + (None,), start=1):
        try:
            os.replace(tmp, ruta)
            return
        except PermissionError as e:
            if not ES_WINDOWS or espera is None:
                if ES_WINDOWS:
                    e.add_note(f"os.replace denegado {n} veces seguidas sobre {ruta} (ARRSN-1); no se reintenta más")
                raise
            nota = f"os.replace denegado sobre {ruta} ({e}); reintento {n}/{len(ESPERAS_REPLACE)} en {espera} s"
            REINTENTOS_REPLACE.append(nota)
            del REINTENTOS_REPLACE[:-50]  # solo los 50 últimos (Revisión, ARRPR): el aviso de stderr ya los hace visibles
            print(f"AVISO: {nota}", file=sys.stderr)
            time.sleep(espera)


def escribir_atomico(ruta: pathlib.Path, datos: bytes) -> None:
    """Temporal en el mismo directorio + os.replace + chmod 644 (un 0600 da HTTP 500 al bajarlo). En Windows, el
    os.replace se reintenta unas pocas veces ante PermissionError (ARRSN-1, _reemplazar)."""
    ruta = pathlib.Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=ruta.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(datos)
        os.chmod(tmp, 0o644)  # antes de publicar: después de os.replace ya no puede fallar nada
        _reemplazar(tmp, ruta)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def serializar(est: dict) -> bytes:
    return (json.dumps(est, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


ORQUESTADORES = ("A", "B")


def orquestador_actual() -> str:
    """VER14-3 / REV-5 (I1.5): quién ejecuta el núcleo. Lo dice PREVENTA_ORQUESTADOR, que el hosted agent de B fija al
    arrancar (hosted/main.py); sin fijar (o vacía), A. Otro valor: IntegridadRota y no se guarda nada (LES-G-076)."""
    valor = (os.environ.get("PREVENTA_ORQUESTADOR") or "").strip()
    if not valor:
        return "A"
    if valor not in ORQUESTADORES:
        raise IntegridadRota(f"PREVENTA_ORQUESTADOR={valor!r} no es A ni B", [])
    return valor


def guardar(est: dict, raiz: pathlib.Path) -> str:
    """Recalcula hash_contenido, marca el orquestador que ejecuta (VER14-3), valida y escribe de forma atómica.
    Devuelve el SHA-256 del fichero."""
    est["hash_contenido"] = hashes.hash_contenido(est)
    est["orquestador"] = orquestador_actual()
    errores = errores_estado(est)
    if errores:
        raise IntegridadRota("El estado a guardar no valida contra su esquema (no se escribe)", errores)
    datos = serializar(est)
    escribir_atomico(ruta_estado(raiz), datos)
    return hashes.sha256_bytes(datos)


def transitar(est: dict, disparador: str, destino: str) -> None:
    """Cambia el estado si (disparador, desde, destino) está en TRANSICIONES; si no, rc 3."""
    desde = est.get("estado") or SIN_ESTADO
    permitidos = TRANSICIONES.get(disparador, {}).get(desde, frozenset())
    if destino not in permitidos:
        raise TransicionNoPermitida(
            f"Transición no permitida: {disparador} desde {desde} hacia {destino}",
            [f"desde {desde}, «{disparador}» solo admite: {sorted(permitidos) or 'nada'}"])
    est["estado"] = destino


def exigir_disparador(est: dict, disparador: str) -> None:
    """TransicionNoPermitida si el subcomando no se admite en el estado actual."""
    desde = est.get("estado") or SIN_ESTADO
    if desde not in TRANSICIONES.get(disparador, {}):
        admitidos = sorted(TRANSICIONES.get(disparador, {}))
        raise TransicionNoPermitida(f"«{disparador}» no se admite en el estado {desde}",
                                    [f"estados de partida admitidos: {admitidos}"])


def bloquear(est: dict, motivo: str) -> None:
    """estado = BLOQUEADA guardando estado_previo y el motivo literal. Nunca desde APROBADA."""
    if est["estado"] == "APROBADA":
        raise TransicionNoPermitida("Una solicitud APROBADA no se bloquea", [motivo])
    if est["estado"] != "BLOQUEADA":
        est["estado_previo"] = est["estado"]
        est["estado"] = "BLOQUEADA"
    est["motivo_bloqueo"] = (motivo or "sin motivo")[:2000]


def fase_de(estado_nombre: str | None) -> str:
    """Fase (turno) a la que pertenece un estado; sirve para poner a 0 su contador al desbloquear."""
    return {"BORRADOR": "T1", "INFORMACION_INSUFICIENTE": "T1", "EN_ANALISIS": "T2",
            "EN_VERIFICACION": "T3"}.get(estado_nombre or "", "T4")


def desbloquear(est: dict) -> str:
    """BLOQUEADA -> estado_previo, con a 0 el contador de esa fase y cualquiera que esté en 3/3."""
    if est["estado"] != "BLOQUEADA" or not est.get("estado_previo"):
        raise TransicionNoPermitida("Solo se desbloquea una solicitud BLOQUEADA con estado_previo",
                                    [f"estado {est['estado']}"])
    destino = est["estado_previo"]
    transitar(est, "decision", destino)
    for f in FASES:
        if f == fase_de(destino) or est["intentos"][f] >= MAX_INTENTOS:
            est["intentos"][f] = 0
    est["estado_previo"] = None
    est["motivo_bloqueo"] = None
    return destino


def registrar_intento(est: dict, fase: str, error: str, hipotesis: str) -> int:
    """Suma un intento N/3 a la fase y lo anota en `fallos`. A 3/3 bloquea. Devuelve N."""
    if fase not in FASES:
        raise EntradaInvalida(f"Fase no válida: {fase!r}", [f"admitidas: {list(FASES)}"])
    error, hipotesis = (error or "").strip(), (hipotesis or "").strip()
    if len(error) < 3 or len(hipotesis) < 3:
        raise EntradaInvalida("registrar un intento exige el error literal y una hipótesis (≥ 3 caracteres)", [])
    n = min(est["intentos"][fase] + 1, MAX_INTENTOS)
    est["intentos"][fase] = n
    cv, previos = est.get("control_versiones") or [], est["fallos"]
    ts = _ts_no_antes_de([(cv[-1].get("ts") if cv else None, True), (previos[-1].get("ts") if previos else None, False)])
    est["fallos"].append({"ts": ts, "fase": fase, "intento": n, "error": error[:8000],
                          "hipotesis": hipotesis[:2000]})
    if n >= MAX_INTENTOS and est["estado"] not in ("BLOQUEADA", "APROBADA"):
        bloquear(est, f"{fase} agotó {MAX_INTENTOS}/{MAX_INTENTOS} intentos. Último error: {error[:600]}")
    return n


def invalidar_desde(est: dict, bloque: str) -> list[str]:
    """§5.3: anula lo que depende de `bloque` (la clave es lo que CAMBIA). Devuelve lo anulado."""
    if bloque not in CASCADA:
        raise IntegridadRota(f"invalidar_desde: bloque desconocido {bloque!r}", [f"admitidos: {sorted(CASCADA)}"])
    anuladas = []
    for clave in CASCADA[bloque]:
        vacio = copy.deepcopy(_VACIO.get(clave))
        if est["carga"].get(clave) != vacio:
            anuladas.append(clave)
        est["carga"][clave] = vacio
    return anuladas


def codigo(est: dict) -> str:
    alta = est["carga"]["alta"]
    return f"OF-{alta['codigo_cliente']}-{alta['seqof']}-{est['version']}"


def siguiente_version(letra: str) -> str:
    if len(letra) != 1 or not ("A" <= letra <= "Z"):
        raise IntegridadRota(f"Versión no válida: {letra!r}", [])
    if letra == "Z":
        raise IntegridadRota("No hay versión después de Z", [])
    return chr(ord(letra) + 1)


def ronda_actual(est: dict) -> int:
    """Ronda del brief y del consolidado en curso: rondas de verificación hechas + 1 (máx. 3)."""
    return min(est["ronda_verificacion"] + 1, MAX_RONDAS)


def brief_id_vigente(est: dict) -> str:
    return f"BRF-{codigo(est)}-{SIGLA_PILAR[pilar(est)]}-R{ronda_actual(est)}"


def brief_vigente(est: dict) -> dict | None:
    bid = brief_id_vigente(est)
    return next((b for b in est["carga"]["briefs"] if b.get("brief_id") == bid), None)


def respuesta_valida(est: dict) -> bool:
    """Hay respuesta del experto registrada; en EN_ANALISIS, además, para el brief vigente."""
    az = registro_experto(est)
    if not az:
        return False
    return az.get("brief_id") == brief_id_vigente(est) if est["estado"] == "EN_ANALISIS" else True


def estado_experto(est: dict) -> str:
    if respuesta_valida(est):
        return "VALIDA"
    if est["estado"] == "EN_ANALISIS" and brief_vigente(est):
        return "BRIEF_ENVIADO"
    return "PENDIENTE"


def _hash_actual(est: dict) -> str:
    try:
        return hashes.hash_contenido(est)
    except Exception:  # el bloque se imprime siempre, también con un estado roto
        return str(est.get("hash_contenido"))


def _confirmaciones(est: dict) -> str:
    """R2: opciones de confirmación local que exigirá verificar_paquete.py (vacío si no hacen falta)."""
    try:
        from nucleo import decision  # import tardío: decision importa este módulo
        orden = decision.orden_confirmacion(est)
    except Exception as exc:  # el bloque se imprime siempre; si no se puede calcular, se dice
        return f" (no se pudieron calcular las confirmaciones locales: {type(exc).__name__})"
    return f". En verificar_paquete.py, el comercial añade en su puesto: {orden}" if orden else ""


FASE_DE_SUBCOMANDO = {"suficiencia": "T1", "registrar-experto": "T2", "registrar-verificacion": "T3", "estimar": "T4"}
PREFIJO_RECHAZO = "Terminar el turno: presentar al comercial el error"
CON_SU_RESPUESTA = "Con su respuesta: "
# Decisión del comercial del 10-10-2026: la entrada del generador la compone el núcleo (A y B); nadie la escribe.
PASO_ESTIMAR = "estimar (el núcleo compone entrada/estimacion_entrada.json desde tareas_propuestas; no se escribe a mano)"
# EA-1: «Terminar el turno. En el siguiente: X» cierra el turno en que se completa una fase. Al EMPEZAR el turno
# siguiente (estado --turno-nuevo) ese paso se reescribe para que diga lo que toca, y no vuelva a parar el turno.
FIN_DE_TURNO = "Terminar el turno. En el siguiente: "
TURNO_NUEVO = " (turno nuevo: el turno anterior ya terminó; ejecutarlo ahora)"
CON_LA_RESPUESTA = "Con la respuesta del comercial de este turno: "
_CIERRE_PREGUNTAS = "Presentar al comercial las preguntas a/b/c/d y terminar el turno. Con su respuesta: "


def paso_turno_nuevo(t: str) -> str:
    """EA-1: el SIGUIENTE PASO tal como se lee al empezar un turno nuevo (lo demás no cambia)."""
    if t.startswith(PREFIJO_RECHAZO) and CON_SU_RESPUESTA in t:  # VERIF-1: el mensaje nuevo ES la respuesta
        resto = paso_turno_nuevo(t.split(CON_SU_RESPUESTA, 1)[1])
        return resto if resto.startswith(CON_LA_RESPUESTA) else CON_LA_RESPUESTA + resto
    if t.startswith(FIN_DE_TURNO):
        return t[len(FIN_DE_TURNO):] + TURNO_NUEVO
    if t.startswith(_CIERRE_PREGUNTAS):
        return (CON_LA_RESPUESTA + t[len(_CIERRE_PREGUNTAS):] + ". Si no responde a las preguntas, presentarlas "
                "otra vez y terminar el turno")
    return t


def rechazo_pendiente(est: dict) -> str | None:
    """VERIF-1 (H-V7): fase cuyo ÚLTIMO subcomando rechazó la entrada del modelo y contó un intento.

    Se deduce de lo que ya guarda el estado: el último control es de un subcomando de fase, no cambió el estado,
    el último fallo es de esa fase con el contador en ese intento y, sobre todo, ese fallo es POSTERIOR al control
    anterior, es decir, lo sumó el último subcomando (REV-5: antes bastaba con que no cambiara la carga, y un
    incompleto válido repetido tras un rechazo heredaba el rótulo de error). registrar_intento pone al fallo una
    marca al menos 1 s posterior al último control y anotar_control nunca la pone anterior al último fallo: un
    fallo nunca comparte marca con el control ANTERIOR (con el de su propio rechazo, sí). Cualquier otro subcomando
    mutante después (registrar-fallo, decision…) lo retira.
    """
    cv, fallos = est.get("control_versiones") or [], est.get("fallos") or []
    if not cv or not fallos:
        return None
    u, f = cv[-1], fallos[-1]
    fase = FASE_DE_SUBCOMANDO.get(u.get("subcomando"))
    if fase is None or u.get("estado_antes") != u.get("estado_despues") or u.get("estado_despues") != est.get("estado"):
        return None
    n = (est.get("intentos") or {}).get(fase) or 0
    if not n or f.get("fase") != fase or f.get("intento") != n:
        return None
    if len(cv) < 2:
        return fase
    t_fallo, t_previo = _dt(f.get("ts")), _dt(cv[-2].get("ts"))
    if t_fallo is not None and t_previo is not None:
        return fase if t_fallo > t_previo else None
    return fase if str(f.get("ts") or "") > str(cv[-2].get("ts") or "") else None


def siguiente_paso(est: dict, fallo_previo: bool = False, turno_nuevo: bool = False) -> str:
    """Texto fijo de §3.2 con los valores sustituidos. Con `turno_nuevo`, reescrito con `paso_turno_nuevo` (EA-1)."""
    e, c = est["estado"], est["carga"]
    h = _hash_actual(est)
    n = ronda_actual(est)
    if e == "BORRADOR":
        t = "Rellenar entrada/requisitos.json con citas literales y ejecutar: suficiencia --requisitos entrada/requisitos.json"
    elif e == "INFORMACION_INSUFICIENTE":
        t = ("Presentar al comercial las preguntas a/b/c/d y terminar el turno. Con su respuesta: asumir --campo CAMPO "
             "--valor VALOR o suficiencia --requisitos ... --aclaracion ...")
    elif e == "EN_ANALISIS":
        b = brief_vigente(est)
        if b is None:
            t = "enrutar"
        elif not respuesta_valida(est):
            t = (f"Enviar el brief {b['brief_id']} a preventa-experto-azure por A2A, guardar su respuesta literal en "
                 f"entrada/respuesta_experto_AZ_R{n}.json y ejecutar registrar-experto")
        else:
            t = "Terminar el turno. En el siguiente: consolidar"
    elif e == "EN_VERIFICACION":
        cons = c.get("consolidado") or {}
        cid = cons.get("consolidado_id", f"CNS-{codigo(est)}-R{n}")
        lotes = [x for x in cons.get("lotes") or [] if isinstance(x, dict) and x.get("lote_id")]
        pendientes = [x for x in lotes if x.get("respuesta") is None]
        if pendientes:  # VERIF-9: modo lotes; el fichero lleva el id del lote (…-L<k>), no se confunde con la ronda
            lid = pendientes[0]["lote_id"]
            t = (f"Enviar el lote {lid} ({lotes.index(pendientes[0]) + 1} de {len(lotes)} del consolidado {cid}, "
                 f"ronda {n}; texto en consolidados/{lid}.txt) a preventa-verificador por A2A, guardar su respuesta "
                 f"literal en entrada/respuesta_verificador_{lid}.json y ejecutar registrar-verificacion --respuesta "
                 f"entrada/respuesta_verificador_{lid}.json. Lotes pendientes: "
                 + ", ".join(x["lote_id"] for x in pendientes))
        else:
            t = (f"Enviar el consolidado {cid} a preventa-verificador por A2A, guardar su respuesta literal en "
                 f"entrada/respuesta_verificador_R{n}.json y ejecutar registrar-verificacion")
    elif e == "VERIFICADA":
        if not c.get("anexo_consumo"):
            t = "Terminar el turno. En el siguiente: anexo-consumo"
        elif not c.get("estimacion"):
            t = PASO_ESTIMAR
        else:
            t = "paquete"
    elif e == "STOP_PRESUPUESTO":
        precio = ((c.get("estimacion") or {}).get("resumen") or {}).get("precio_cerrado_eur", "desconocido")
        t = (f"Parar. Precio {precio} EUR > 100.000 EUR. El comercial decide: DECISION | Responsable comercial | "
             f"CONFIRMA_STOP | AAAA-MM-DD | {h} | motivo")
    elif e == "LISTA_PARA_REVISION":
        t = ("El comercial descarga el ZIP, ejecuta verificar_paquete.py en local y, con rc 0, envía mensaje_revisor.txt y "
             "registra DECISION … ENVIADA_REVISION") + _confirmaciones(est)
    elif e == "EN_REVISION_PREVENTA":
        t = "Esperar la decisión de Responsable de preventa y registrarla con decision --linea"
    elif e == "EN_APROBACION_AREA":
        t = "El comercial envía mensaje_aprobador.txt; esperar la decisión de Responsable de área y registrarla"
    elif e == "APROBADA":
        t = "paquete (regenera la diapositiva 2 con las firmas) y cerrar" + _confirmaciones(est)
    elif e == "DEVUELTA_CON_COMENTARIOS":
        t = (f"Versión {est['version']}. Según el comentario: suficiencia/asumir (requisitos), enrutar (análisis), "
             "consolidar (verificación) o anexo-consumo/estimar (economía). En una conversación nueva: "
             f"restaurar --zip {codigo(est)}-Relevo.zip")
    elif e == "BLOQUEADA":
        t = (f"Parar. Motivo: {est.get('motivo_bloqueo') or 'sin motivo'}. El comercial decide: DECISION | Responsable comercial "
             f"| DESBLOQUEAR | AAAA-MM-DD | {h} | motivo")
    else:
        t = f"Estado desconocido {e}: parar y avisar al comercial"
    fase = rechazo_pendiente(est)
    if fase:  # VERIF-1: un intento por fase y turno; el siguiente, con la respuesta del comercial
        t = (f"{PREFIJO_RECHAZO} ({fase} intento {est['intentos'][fase]}/{MAX_INTENTOS}), sin un segundo intento en "
             f"este turno. {CON_SU_RESPUESTA}{t}")
    if turno_nuevo:
        t = paso_turno_nuevo(t)
    if fallo_previo:
        t = 'PRIMERO: registrar-fallo --fase FASE --error "ERROR LITERAL" --hipotesis "HIPÓTESIS". Después: ' + t
    return t


def bloque_estado(est: dict | None, fallo_previo: bool = False, turno_nuevo: bool = False) -> str:
    """Bloque `estado` de §11.3, exactamente. Con est None: SIN_ESTADO. `turno_nuevo`: ver siguiente_paso (EA-1)."""
    if est is None:
        return "\n".join(["=== ESTADO PREVENTA ===", "estado: SIN_ESTADO",
                          "SIGUIENTE PASO OBLIGATORIO: iniciar … (alta nueva) o restaurar --zip … con el último "
                          "Paquete o Relevo descargado (contenedor caducado)", "=== FIN ESTADO ==="])
    i = est["intentos"]
    lineas = ["=== ESTADO PREVENTA ===", f"codigo: {est['codigo']}", f"estado: {est['estado']}",
              f"version: {est['version']}", f"hash_contenido: {_hash_actual(est)}",
              "intentos: " + " · ".join(f"{f} {i[f]}/{MAX_INTENTOS}" for f in FASES),
              f"expertos: {pilar(est)}={estado_experto(est)}", f"verificacion: ronda {est['ronda_verificacion']}/{MAX_RONDAS}",
              f"decisiones: {len(est['decisiones'])}"]
    if est["estado"] == "BLOQUEADA":
        lineas.append(f"motivo_bloqueo: {est.get('motivo_bloqueo')}")
    lineas += [f"SIGUIENTE PASO OBLIGATORIO: {siguiente_paso(est, fallo_previo, turno_nuevo)}", "=== FIN ESTADO ==="]
    return "\n".join(lineas)


def anotar_control(est: dict, subcomando: str, estado_antes: str | None, hash_antes: str | None) -> None:
    """Añade {n, subcomando, estado_antes, estado_despues, hash_antes, hash_despues, ts}; ts nunca anterior al último
    control ni al último fallo (REV-5)."""
    est["control_versiones"].append({
        "n": len(est["control_versiones"]) + 1, "subcomando": subcomando, "estado_antes": estado_antes,
        "estado_despues": est["estado"], "hash_antes": hash_antes, "hash_despues": hashes.hash_contenido(est),
        "ts": _ts_no_antes_de([(x[-1].get("ts") if x else None, False)
                               for x in (est["control_versiones"], est.get("fallos") or [])])})
