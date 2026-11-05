"""Pasos del turno. Cada paso llama a la API del núcleo y deja su resultado literal en el registro del turno.

Lo que genera el código (brief, consolidado, entrada de la estimación) lo transporta el código, sin modelo
(LES-G-095). Cualquier fallo se registra con su motivo literal en el núcleo (`registrar-fallo`) y se dice.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import pathlib
import re
from datetime import datetime, timezone

from . import a2a as A
from . import modelo
from . import procedencia as PR

_BRF = re.compile(r"\b(BRF-[A-Z0-9-]+-R([0-9]))\b")


class Registro:
    """Lo que el turno contará al comercial, en orden."""

    def __init__(self):
        self.lineas: list[str] = []
        self.a2a = 0
        self.modelo = 0

    def nota(self, texto: str) -> None:
        self.lineas.append(texto)

    def nucleo(self, r) -> None:
        salida = _resumir_bloques(r.salida)
        self.lineas.append(f"$ {r.subcomando} → rc {r.rc}\n```\n{salida.rstrip()}\n```")


def _resumir_bloques(salida: str) -> str:
    """El brief y el consolidado no se repiten enteros en el chat: se citan con su huella (van tal cual por A2A)."""
    for ini, fin in (("=== BRIEF PARA preventa-experto-azure ===", "=== FIN BRIEF ==="),
                     ("=== CONSOLIDADO PARA preventa-verificador ===", "=== FIN CONSOLIDADO ===")):
        if ini in salida and fin in salida:
            antes, resto = salida.split(ini, 1)
            cuerpo, despues = resto.split(fin, 1)
            cuerpo = cuerpo.strip("\n")
            salida = (f"{antes}{ini}\n[{len(cuerpo.encode('utf-8'))} bytes, SHA-256 {A.sha256(cuerpo)}; lo envía el "
                      f"código tal cual]\n{fin}{despues}")
    return salida


def procedencia(trabajo: pathlib.Path, ll: A.Llamada, fase: str) -> None:
    d = trabajo / "procedencia"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "a2a.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"fase": fase, **ll.registro()}, ensure_ascii=False) + "\n")


def requisitos(P, env, est: dict, cfg, token, reg: Registro, aclaracion: str | None = None,
               transporte=None):
    """T1: el modelo rellena requisitos.json con citas; el núcleo los valida con `suficiencia`."""
    trabajo = pathlib.Path(env.raiz)
    fuentes = {}
    for f in (est.get("carga") or {}).get("fuentes") or []:
        cache = trabajo / "fuentes" / f"{f['id']}.txt"
        if cache.is_file():
            fuentes[f["id"]] = cache.read_text(encoding="utf-8")
    if not fuentes:
        reg.nota("No encuentro el texto de las fuentes en la sesión: no puedo pedir los requisitos.")
        return None
    aclaraciones = []
    if aclaracion:
        n = 1 + len(list((trabajo / "entrada").glob("aclaracion_*.txt")))
        rel = f"entrada/aclaracion_{n}.txt"
        (trabajo / "entrada").mkdir(parents=True, exist_ok=True)
        (trabajo / rel).write_text(aclaracion.strip() + "\n", encoding="utf-8")
        fuentes[f"F{len(fuentes) + 1}"] = aclaracion.strip() + "\n"   # el id lo asigna el núcleo; si no casa, falla
        aclaraciones.append(rel)
    try:   # I1.9 (PR18-1): los ids del catálogo montado para servicio_catalogo; sin catálogo, el núcleo lo rechaza
        servicios = modelo.lista_servicios(P.catalogo_montado(env))
    except Exception as exc:  # noqa: BLE001 - se dice en el turno; suficiencia falla después con su motivo
        servicios = ""
        reg.nota(f"Aviso: no he podido leer el catálogo montado para la extracción ({type(exc).__name__}: {exc}).")
    reg.modelo += 1
    try:
        req, uso = modelo.pedir_requisitos(cfg.proyecto, cfg.modelo, token, fuentes, cfg.timeout_modelo_s, transporte,
                                           servicios=servicios)
    except modelo.ErrorModelo as exc:
        reg.nota(f"El modelo no devolvió los requisitos: {exc}")
        r = P.registrar_fallo(env, fase="T1", error=str(exc)[:2000],
                              hipotesis="fallo de la llamada al modelo (red, cuota o despliegue); repetir con SIGUE")
        reg.nucleo(r)
        return r
    req, avisos = modelo.sanear(req)
    for a in avisos:
        reg.nota(f"Aviso: {a}")
    reg.nota(f"Requisitos propuestos por {uso.get('modelo')} (respuesta {uso.get('response_id')}); "
             "el código comprueba cada cita.")
    (trabajo / "entrada").mkdir(parents=True, exist_ok=True)
    (trabajo / "entrada" / "requisitos.json").write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
    r = P.suficiencia(env, requisitos="entrada/requisitos.json", aclaraciones=aclaraciones)
    reg.nucleo(r)
    return r


# I1.7 (decisión 1 del comercial, 13-10-2026): ni el experto ni el verificador llaman a la API de precios (los precios
# salen de la instantánea que el código descarga al desplegar). Desaparecen así las dos causas medidas del aborto de
# Foundry por una herramienta (filtro sin comilla final y 429 de Retail Prices, PR16-2), y con ellas la repetición
# única con pausa que añadieron los arreglos de I1.6: cualquier fallo A2A se registra con su motivo literal y SIGUE
# repite la fase (CONSTITUTION P-6: nada se repite en silencio).


METODO_ILEGIBLE = "LINEA_ILEGIBLE_AVISADA"   # REVERIF17-6 (I1.8): registro propio en a2a.jsonl, no es una llamada


class ProcedenciaIlegible(ValueError):
    """REVERIF17-6 (I1.8): a2a.jsonl tiene líneas ilegibles que nadie ha avisado todavía. `lineas`: [(número, SHA-256)]."""

    def __init__(self, lineas: list[tuple[int, str]]):
        self.lineas = lineas
        super().__init__(f"a2a.jsonl tiene {len(lineas)} línea(s) ilegible(s) sin avisar: "
                         + ", ".join(str(n) for n, _ in lineas))


def _ultimo_envio(trabajo: pathlib.Path, agente: str, fase: str) -> dict | None:
    """El último SendMessage de `fase` a `agente` en a2a.jsonl. REVERIF17-6 (I1.8): una línea ilegible ya no se salta en
    silencio ni hace reenviar sin decirlo: si nadie la ha avisado, ProcedenciaIlegible (el turno lo registra como fallo
    con su motivo y apunta el aviso); si ya se avisó (registro METODO_ILEGIBLE con su SHA-256), se ignora."""
    ruta = trabajo / "procedencia" / "a2a.jsonl"
    if not ruta.is_file():
        return None
    ultimo, ilegibles, avisadas = None, [], set()
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        if not linea.strip():
            continue
        try:
            d = json.loads(linea)
        except ValueError:
            ilegibles.append((n, hashlib.sha256(linea.encode("utf-8")).hexdigest()))
            continue
        if isinstance(d, dict) and d.get("metodo") == METODO_ILEGIBLE:
            avisadas |= {x for x in d.get("sha256_lineas") or [] if isinstance(x, str)}
        elif isinstance(d, dict) and d.get("metodo") == "SendMessage" and d.get("agente") == agente \
                and d.get("fase") == fase:
            ultimo = d
    pendientes = [(n, h) for n, h in ilegibles if h not in avisadas]
    if pendientes:
        raise ProcedenciaIlegible(pendientes)
    return ultimo


def avisar_ilegibles(trabajo: pathlib.Path, exc: ProcedenciaIlegible, agente: str, fase: str) -> None:
    """Apunta en a2a.jsonl que esas líneas ilegibles ya se avisaron (el siguiente turno las ignora y reenvía)."""
    d = trabajo / "procedencia"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "a2a.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"metodo": METODO_ILEGIBLE, "fase": fase, "agente": agente, "inicio": ahora(),
                            "lineas": [n for n, _ in exc.lineas], "sha256_lineas": [h for _, h in exc.lineas]},
                           ensure_ascii=False) + "\n")


def pendiente_previa(trabajo: pathlib.Path, agente: str, fase: str, sha256_enviado: str) -> dict | None:
    """PR17-2 (I1.7): el último SendMessage de `fase` a `agente` en a2a.jsonl, si quedó PENDIENTE (la tarea seguía viva
    en Foundry al dejar de esperar), tiene task_id y es del MISMO texto. Entonces se recoge por su task_id en vez de
    reenviar (la ejecución sigue y se cobra igual: VER17-4). REVERIF17-1 (I1.8): una tarea que GetTask ya no encuentra
    queda con `pendiente: false` y `perdida: true`, así que no se vuelve a recoger (tampoco tras DESBLOQUEAR).
    REVERIF17-6: una línea ilegible sin avisar lanza ProcedenciaIlegible."""
    ultimo = _ultimo_envio(trabajo, agente, fase)
    if (ultimo and ultimo.get("pendiente") is True and ultimo.get("perdida") is not True
            and isinstance(ultimo.get("task_id"), str) and ultimo["task_id"]
            and ultimo.get("sha256_enviado") == sha256_enviado):
        return ultimo
    return None


def perdida_previa(trabajo: pathlib.Path, agente: str, fase: str) -> dict | None:
    """REVERIF17-1 (I1.8): el último SendMessage de `fase` a `agente`, si su tarea se dio por perdida (-32001)."""
    ultimo = _ultimo_envio(trabajo, agente, fase)
    return ultimo if ultimo and ultimo.get("perdida") is True else None


def _delegar(P, env, cliente: A.ClienteA2A, agente: str, texto: str, fase: str, reg: Registro, objetivo_id: str):
    reg.a2a += 1
    trabajo = pathlib.Path(env.raiz)
    try:
        previa = pendiente_previa(trabajo, agente, fase, A.sha256(texto))
        perdida = None if previa is not None else perdida_previa(trabajo, agente, fase)
    except ProcedenciaIlegible as exc:
        # REVERIF17-6 (I1.8): no se reenvía a ciegas (podría haber una tarea pendiente de este envío y se pagaría dos
        # veces) ni se calla: se registra el fallo con su motivo y se apunta el aviso; el siguiente SIGUE reenvía.
        avisar_ilegibles(trabajo, exc, agente, fase)
        motivo = (f"{exc}. No sé si la última tarea de {fase} a {agente} quedó pendiente: no reenvío en este turno para "
                  "no pagar dos veces la misma ejecución")
        reg.nota(f"FALLO: {motivo}.")
        r = P.registrar_fallo(env, fase=fase, error=motivo[:2000],
                              hipotesis=("línea de procedencia/a2a.jsonl escrita a medias (turno interrumpido); queda "
                                         "avisada: con SIGUE se ignora y se reenvía el texto, con riesgo de una "
                                         "ejecución duplicada si aquella tarea seguía viva"))
        reg.nucleo(r)
        return None
    if previa is not None:
        reg.nota(f"La tarea {previa['task_id']} de {agente} quedó pendiente en un turno anterior: la recojo por su "
                 "task_id, sin reenviar el texto.")
        ll = cliente.recuperar(agente, previa["task_id"], previa)
    else:
        ll = cliente.enviar(agente, texto)
        if perdida is not None:   # REVERIF17-1: el reenvío lleva el task_id perdido y su motivo literal
            ll.reenvio_de, ll.motivo_reenvio = perdida.get("task_id"), str(perdida.get("error") or "sin motivo")[:2000]
            reg.nota(f"Reenvío el texto a {agente}: la tarea {ll.reenvio_de} se dio por perdida ({ll.motivo_reenvio}).")
    procedencia(trabajo, ll, fase)
    reg.nota(f"A2A {ll.metodo} a {agente}: HTTP {ll.http} · {ll.latencia_s} s · task_id {ll.task_id} · "
             f"context_id {ll.context_id} · estado {ll.estado_tarea} · enviado SHA-256 {ll.sha256_enviado} · "
             f"{'recogida' if ll.recuperada else 'no bloqueante'} con {ll.sondeos} sondeo(s) GetTask"
             + (f" ({ll.errores_sondeo} con error, repetidos)" if ll.errores_sondeo else ""))
    if not ll.ok and ll.pendiente and cliente.cancelado():
        reg.nota(f"PENDIENTE: {ll.error}. No registro fallo: la ejecución sigue en Foundry y SIGUE la recoge.")
        return None
    if not ll.ok:
        reg.nota(f"FALLO A2A ({agente}): {ll.error}")
        if ll.perdida:   # REVERIF17-1 (I1.8): clasificado por el código de la API, nunca «sigue viva»
            hipotesis = (f"la tarea {ll.task_id} ya no existe en Foundry (JSON-RPC {A.TAREA_NO_ENCONTRADA}: caducada o "
                         "purgada); se da por perdida y con SIGUE se reenvía el texto con este motivo")
        elif ll.pendiente:
            hipotesis = f"la tarea {ll.task_id} sigue viva en Foundry; con SIGUE se recoge por su task_id, sin reenviar"
        else:
            hipotesis = f"fallo de la llamada A2A a {agente}; con SIGUE se repite la fase"
        r = P.registrar_fallo(env, fase=fase, error=(ll.error or "sin motivo")[:2000], hipotesis=hipotesis)
        reg.nucleo(r)
        return None
    # Decisión del comercial (10-10-2026): el código guarda el texto recibido y su SHA-256, y relee la tarea con GetTask
    # con su propia identidad (la única que puede leerla). Va al paquete y la puerta local lo contrasta con las trazas.
    leida = cliente.tarea(agente, ll.task_id) if ll.task_id else None
    intentos = 1 if leida is not None else 0
    if leida is not None:
        procedencia(trabajo, leida, f"{fase}-relectura")
        if not PR.leida_ok(leida):   # una sola repetición, anotada (red o plataforma intermitente); nunca más
            reg.nota(f"La relectura GetTask de {ll.task_id} falló ({leida.error or leida.estado_tarea}); la repito "
                     "una vez (1/1).")
            leida, intentos = cliente.tarea(agente, ll.task_id), 2
            procedencia(trabajo, leida, f"{fase}-relectura")
    ent = PR.entrada(ll, objetivo_id, fase, leida)
    ent["relectura"]["intentos"] = intentos
    rel = ent["relectura"]
    # Decisión 3 del comercial (11-10-2026): sin relectura igual, la salida queda NO VERIFICADO en la puerta local y con
    # --estricto no da verde. La respuesta se registra igual (el núcleo la valida); lo que falta es la prueba.
    if rel["coincide"] is True:
        reg.nota(f"Relectura GetTask de {ll.task_id}: el texto coincide (SHA-256 {ent['sha256_recibido']}).")
    elif rel["coincide"] is False:
        reg.nota(f"NO VERIFICADO: la relectura GetTask de {ll.task_id} devuelve otro texto (SHA-256 "
                 f"{rel['sha256_recibido']} frente a {ent['sha256_recibido']}); queda en la procedencia y la puerta "
                 "local no dará verde con este paquete.")
    else:
        reg.nota(f"NO VERIFICADO: no he podido releer la tarea {ll.task_id} con GetTask ({intentos} intento(s)): "
                 f"{rel['error']}. La puerta local dejará esta respuesta NO VERIFICADO y con --estricto no dará verde.")
    try:
        PR.anadir(trabajo, ent)
    except (OSError, ValueError) as exc:
        motivo = f"no se pudo guardar la procedencia de la tarea {ll.task_id}: {type(exc).__name__}: {exc}"
        reg.nota(f"FALLO: {motivo}. No registro la respuesta: sin procedencia, la puerta local la rechazaría.")
        r = P.registrar_fallo(env, fase=fase, error=motivo[:2000],
                              hipotesis="fallo al escribir en la carpeta de la sesión; con SIGUE se repite la fase")
        reg.nucleo(r)
        return None
    return ll


def experto(P, env, est: dict, siguiente: str, cliente: A.ClienteA2A, cfg, reg: Registro):
    """T2: envía EXACTAMENTE el brief que generó el código y registra la respuesta literal."""
    m = _BRF.search(siguiente or "")
    briefs = [b for b in (est.get("carga") or {}).get("briefs") or [] if m and b.get("brief_id") == m.group(1)]
    if len(briefs) != 1:
        reg.nota(f"No encuentro un único brief vigente para «{siguiente}»: paro.")
        return None
    # PR17-6 parte 2 (I1.8): tras un rechazo del núcleo, el texto que se envía lleva delante el motivo literal del rechazo
    # (lo compone el núcleo, nucleo.brief.texto_envio; la puerta lo recompone). Sin rechazo, es el brief tal cual.
    try:
        texto = importlib.import_module("nucleo.brief").texto_envio(est, briefs[0])
    except Exception as exc:  # noqa: BLE001 - núcleo distinto del esperado: se dice y se para, sin enviar nada
        reg.nota(f"No puedo componer el texto de envío del brief {m.group(1)}: {type(exc).__name__}: {exc}. Paro sin "
                 "enviar nada.")
        return None
    if texto != briefs[0]["texto"]:
        reg.nota(f"Reintento del brief {m.group(1)}: el texto enviado lleva delante el motivo literal del último rechazo "
                 "del núcleo (el brief sigue igual y el experto lo devuelve sin ese bloque).")
    ll = _delegar(P, env, cliente, cfg.experto, texto, "T2", reg, m.group(1))
    if ll is None:
        return None
    rel = f"entrada/respuesta_experto_AZ_R{m.group(2)}.json"
    (pathlib.Path(env.raiz) / rel).write_bytes(ll.texto.encode("utf-8"))
    r = P.registrar_experto(env, respuesta=rel, experto="azure")
    reg.nucleo(r)
    return r


def objetivos_verificacion(est: dict) -> list[tuple[str, str]]:
    """(id, texto EXACTO) que faltan por verificar: los lotes pendientes del consolidado si el núcleo los
    genera (LES-G-096.3: cada llamada por debajo de ~120 s) o el consolidado entero si no hay lotes."""
    cons = (est.get("carga") or {}).get("consolidado") or {}
    if cons.get("lotes"):
        return [(x["lote_id"], x["texto"]) for x in cons["lotes"] if x.get("respuesta") is None]
    if cons.get("consolidado_id") and cons.get("texto"):
        return [(cons["consolidado_id"], cons["texto"])]
    return []


def verificador(P, env, est: dict, cliente: A.ClienteA2A, cfg, reg: Registro):
    """T3: envía EXACTAMENTE cada lote (o el consolidado) que generó el código y registra cada respuesta literal."""
    objetivos = objetivos_verificacion(est)
    if not objetivos:
        reg.nota("No hay consolidado ni lotes pendientes en el estado: paro.")
        return None
    r = None
    for oid, texto in objetivos:
        if not re.fullmatch(r"CNS-[A-Z0-9-]{4,60}", oid):
            reg.nota(f"Identificador de consolidado no válido: {oid!r}: paro.")
            return None
        if reg.a2a >= cfg.max_a2a_por_turno:
            reg.nota(f"Quedan {len(objetivos_verificacion(P.estado(env, como_json=True).estado or {}))} envíos al "
                     "verificador. Escribe SIGUE para continuar.")
            return None
        ll = _delegar(P, env, cliente, cfg.verificador, texto, "T3", reg, oid)
        if ll is None:
            return None
        rel = f"entrada/respuesta_verificador_{oid}.json"
        (pathlib.Path(env.raiz) / rel).write_bytes(ll.texto.encode("utf-8"))
        r = P.registrar_verificacion(env, respuesta=rel)
        reg.nucleo(r)
        if r.rc != 0:   # un lote intermedio bien registrado da rc 0 («LOTE … registrado. Faltan …»)
            motivos_discrepa(P, env, reg)
            return r
    return r


def motivos_discrepa(P, env, reg: Registro) -> None:
    """PR18-7 (I1.9): con DISCREPA efectivos, el turno dice el motivo de cada uno (campo, valor correcto, fuente y detalle
    del verificador), que antes solo se veía descargando el estado. Lo compone el núcleo desde el estado guardado
    (nucleo.verificacion.lineas_discrepa_turno); si no puede, lo dice (nunca en silencio)."""
    try:
        est = P.estado(env, como_json=True).estado or {}
        lineas = importlib.import_module("nucleo.verificacion").lineas_discrepa_turno(est)
    except Exception as exc:  # noqa: BLE001 - núcleo anterior o estado ilegible: se dice y se sigue
        reg.nota(f"No puedo leer el motivo de los DISCREPA desde el estado: {type(exc).__name__}: {exc}. Están en "
                 "estado.json (carga.verificacion.resultado.discrepa).")
        return
    if lineas:
        reg.nota("Motivo de cada DISCREPA (lo que vuelve al experto como corrección):\n" + "\n".join(lineas))


# REV-1 (I1.4): ya no hay `estimar` con entrada escrita aquí; el turno llama a `estimar` del núcleo, que compone la
# entrada con la regla decidida (nucleo.estimacion.componer_entrada) y rechaza cualquier otra (P6f).


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
