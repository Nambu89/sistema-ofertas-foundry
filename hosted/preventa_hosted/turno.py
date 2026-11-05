"""Manejador del turno: interpreta el mensaje (sin modelo) y ejecuta la máquina de estados del núcleo.

Quien decide el paso siguiente es el NÚCLEO (`SIGUIENTE PASO OBLIGATORIO`, texto fijo de CONTRATOS §3.2);
este módulo solo lo ejecuta. Se para cuando hace falta una persona, cuando falla algo (con su motivo) o al
llegar al máximo de llamadas A2A por turno. Una carpeta de trabajo por sesión y un cerrojo por carpeta
(API-NUCLEO §4: un solo escritor).
"""
from __future__ import annotations

import contextlib
import os
import pathlib
import sys
import threading
import zipfile

from . import a2a as A
from . import adjuntos, fases, mensajes, procedencia

_CERROJOS: dict[str, threading.Lock] = {}
_CERROJOS_LOCK = threading.Lock()
PARADAS = ("STOP_PRESUPUESTO", "LISTA_PARA_REVISION", "EN_REVISION_PREVENTA", "EN_APROBACION_AREA",
           "BLOQUEADA", "INFORMACION_INSUFICIENTE")
MAX_PASOS = 12
# VERIF-1: tras un rechazo, el núcleo antepone «Terminar el turno: presentar al comercial el error … Con su respuesta: ».
# Aquí el mensaje nuevo del comercial ES su respuesta, y en el turno del rechazo ya se paró (rc distinto de 0).
PREFIJO_RECHAZO, CON_SU_RESPUESTA = "Terminar el turno: presentar al comercial el error", "Con su respuesta: "
# VER14-3 / REV-5 (I1.5): el núcleo marca en estado.json y en el manifiesto qué orquestador ejecutó cada paso, leyendo
# esta variable (A por defecto). La fija el código del hosted al arrancar (main.py); el modelo no la toca. Sin ella el
# turno no ejecuta nada: un paquete de B marcado como A pasaría por la vía de A en la puerta local.
VAR_ORQUESTADOR = "PREVENTA_ORQUESTADOR"


def _sin_rechazo(sig: str) -> str:
    if sig.startswith(PREFIJO_RECHAZO) and CON_SU_RESPUESTA in sig:
        return sig.split(CON_SU_RESPUESTA, 1)[1]
    return sig


def _cerrojo(clave: str) -> threading.Lock:
    with _CERROJOS_LOCK:
        return _CERROJOS.setdefault(clave, threading.Lock())


@contextlib.contextmanager
def _cerrojo_fichero(carpeta: pathlib.Path):
    """Exclusión entre PROCESOS sobre la carpeta persistente (flock en Linux, msvcrt en Windows)."""
    carpeta.mkdir(parents=True, exist_ok=True)
    with open(carpeta / ".cerrojo", "a+b") as f:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _api(cfg):
    if str(cfg.app) not in sys.path:
        sys.path.insert(0, str(cfg.app))
    import preventa_api  # noqa: PLC0415  (se importa desde la carpeta del núcleo empaquetada)
    if pathlib.Path(preventa_api.__file__).resolve().parent != pathlib.Path(cfg.app).resolve():
        raise RuntimeError(f"El núcleo cargado es el de {preventa_api.__file__}, no el de {cfg.app}")
    return preventa_api


class Coordinador:
    def __init__(self, cfg, token, transporte_a2a=None, transporte_http=None, hoy=None):
        self.cfg, self.token, self.hoy = cfg, token, hoy
        self.t_http = transporte_http
        # PR17-2 (I1.7): envío no bloqueante y espera de la tarea sondeando GetTask; si el cliente cancela el turno, se
        # deja de esperar y la tarea queda pendiente (se recoge en el turno siguiente por su task_id).
        self.a2a = A.ClienteA2A(cfg.url_a2a, token, cfg.timeout_a2a_s, transporte_a2a,
                                espera_s=getattr(cfg, "espera_a2a_s", 420.0), sondeo_s=getattr(cfg, "sondeo_a2a_s", 5.0))
        self._cancelado = lambda: False
        self.a2a.cancelado = lambda: self._cancelado()

    def manejar(self, texto: str, ficheros: list[dict], cancelado=None) -> str:
        """`cancelado()` → True si el cliente canceló: se para antes del siguiente paso (nunca a mitad de uno)."""
        self._cancelado = cancelado or (lambda: False)
        with _cerrojo(str(self.cfg.trabajo)), _cerrojo_fichero(self.cfg.base):
            return self._manejar(texto, ficheros)

    def _manejar(self, texto: str, ficheros: list[dict]) -> str:
        P, reg = _api(self.cfg), fases.Registro()
        if self._cancelado():   # canceló mientras esperaba el cerrojo: no se toca nada
            return "Turno cancelado por el cliente antes de empezar: no he ejecutado nada."
        if (os.environ.get(VAR_ORQUESTADOR) or "").strip() != "B":
            return (f"Configuración inválida del agente: {VAR_ORQUESTADOR} debe valer B en el hosted agent (vale "
                    f"{os.environ.get(VAR_ORQUESTADOR)!r}). No he ejecutado nada.")
        try:
            nuevos = adjuntos.guardar(ficheros, self.cfg.datos, self.cfg.proyecto, self.token, self.t_http)
        except adjuntos.ErrorAdjunto as exc:
            return f"No he podido guardar el adjunto: {exc}. No he ejecutado nada más."
        if nuevos:
            reg.nota(f"Adjuntos guardados en la sesión: {', '.join(nuevos)}")
        msg = mensajes.interpretar(texto)
        env = P.abrir(self.cfg.trabajo, datos=self.cfg.datos, tmp=self.cfg.base / "tmp", montaje="exacto")
        est = P.estado(env, como_json=True).estado
        if est is None:
            self._sin_estado(P, env, msg, nuevos, reg)
        else:
            self._con_estado(P, env, msg, reg)
        return self._cierre(P, env, reg)

    # ── Sin estado: alta o restauración ──────────────────────────────────────────────────────
    def _sin_estado(self, P, env, msg, nuevos, reg) -> None:
        if "RESTAURAR" in msg.ordenes:
            zips = [n for n in nuevos if n.lower().endswith(".zip")]
            if len(zips) == 1:   # forma preferida del núcleo: Paquete o Relevo, byte a byte (H7, H12)
                r = P.ejecutar(env, ["restaurar", f"--zip={zips[0]}"])
                reg.nucleo(r)
                if r.rc == 0:
                    self._fusionar_procedencia(self.cfg.datos / zips[0], pathlib.Path(env.raiz), reg, self.a2a.tarea,
                                               {self.cfg.experto, self.cfg.verificador})
                return
            faltan = [n for n in ("estado.json", "manifiesto_paquete.json") if not (self.cfg.datos / n).is_file()]
            if len(zips) > 1 or faltan:
                reg.nota("Para restaurar adjunta UN ZIP (el último Paquete o Relevo que descargaste) o, si no lo "
                         "tienes, estado.json y manifiesto_paquete.json.")
                return
            reg.nucleo(P.restaurar(env, estado="estado.json", manifiesto="manifiesto_paquete.json"))
            return
        if not msg.alta:
            reg.nota("No hay ninguna solicitud en esta sesión. Escribe el alta (Cliente, Código de cliente, SEQOF, "
                     "Título, Términos sensibles y la confirmación del NDA) con la transcripción adjunta, o "
                     "RESTAURAR con estado.json y manifiesto_paquete.json adjuntos.")
            return
        faltan = msg.alta.faltan() + ([] if msg.nda_confirmado else ["confirmación del NDA (CONFIRMO: NDA)"])
        transcripcion = self._transcripcion(msg, nuevos)
        if transcripcion is None:
            faltan.append("la transcripción (adjunta, o pegada tras una línea «TRANSCRIPCIÓN:»)")
        if faltan:
            reg.nota("Para dar el alta me falta: " + "; ".join(faltan) + ". No he ejecutado nada.")
            return
        a = msg.alta
        r = P.iniciar(env, cliente=a.cliente, codigo_cliente=a.codigo_cliente, seqof=a.seqof, titulo=a.titulo,
                      transcripcion=transcripcion, sensibles=a.sensibles, nda_confirmado=True)
        reg.nucleo(r)
        if r.ok:
            self._avanzar(P, env, reg)

    @staticmethod
    def _fusionar_procedencia(zip_: pathlib.Path, trabajo: pathlib.Path, reg, releer, agentes: set[str]) -> None:
        """Tras restaurar, las tareas A2A de la procedencia del ZIP pasan a la sesión (el núcleo ya comprobó su
        SHA-256 contra el manifiesto). Sin ellas, el paquete siguiente no probaría las salidas de antes. REV-4: cada
        tarea se relee con GetTask antes de añadirla; si alguna difiere, no se fusiona nada y se dice en alto."""
        try:
            with zipfile.ZipFile(zip_) as zf:
                if procedencia.NOMBRE not in zf.namelist():
                    reg.nota(f"El ZIP restaurado no trae {procedencia.NOMBRE}: la procedencia de B empieza de cero.")
                    return
                datos = zf.read(procedencia.NOMBRE)
            n, avisos = procedencia.fusionar(trabajo, datos, releer=releer, agentes=agentes)
        except procedencia.FusionRechazada as exc:
            reg.nota(f"FALLO: no fusiono la procedencia A2A del ZIP: {exc}. El estado sí está restaurado, pero sin esa "
                     "procedencia el paquete siguiente no pasará la puerta local. Repite RESTAURAR con el ZIP que "
                     "descargaste tal cual o abre la solicitud de nuevo.")
            return
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            reg.nota(f"AVISO: no he podido recuperar la procedencia A2A del ZIP: {type(exc).__name__}: {exc}")
            return
        reg.nota(f"Procedencia A2A recuperada del ZIP: {n} tarea(s) añadida(s) a la sesión.")
        for a in avisos:
            reg.nota(f"AVISO: {a}")

    def _transcripcion(self, msg, nuevos: list[str]) -> str | None:
        candidatos = [n for n in nuevos if n.lower().endswith((".txt", ".vtt", ".docx", ".pdf"))]
        if msg.transcripcion_pegada:
            destino = self.cfg.datos / "transcripcion.txt"
            self.cfg.datos.mkdir(parents=True, exist_ok=True)
            destino.write_text(msg.transcripcion_pegada, encoding="utf-8")
            candidatos.append("transcripcion.txt")
        return candidatos[0] if len(candidatos) == 1 else None

    # ── Con estado: órdenes del comercial y avance ─────────────────────────────────────────────
    def _con_estado(self, P, env, msg, reg) -> None:
        if msg.vacio:
            reg.nota("No he reconocido ninguna orden (ASUMIR, ACLARACIÓN, DECISION, RESTAURAR, ESTADO o SIGUE). "
                     "No he ejecutado nada.")
            return
        if msg.alta:   # cualquier línea del alta, aunque sea parcial
            reg.nota("Ya hay una solicitud en esta sesión: para otra, abre una conversación nueva. No he ejecutado nada.")
            return
        for linea in msg.decisiones:
            r = P.decision(env, linea=linea)
            reg.nucleo(r)
            if not r.ok:
                return
        for campo, valor in msg.asumir:
            r = P.asumir(env, campo=campo, valor=valor)
            reg.nucleo(r)
            if not r.ok:
                return
        if msg.aclaracion and not self._cancelado():
            est = P.estado(env, como_json=True).estado
            r = fases.requisitos(P, env, est, self.cfg, self.token, reg, msg.aclaracion, self.t_http)
            if r is None or r.rc not in (0, 1):
                return
        if msg.ordenes == ["ESTADO"]:
            return
        self._avanzar(P, env, reg, permitir_devuelta="SIGUE" in msg.ordenes)

    def _avanzar(self, P, env, reg, permitir_devuelta: bool = False) -> None:
        """Ejecuta el SIGUIENTE PASO del núcleo hasta que haga falta una persona, falle algo o se llegue al tope."""
        hecho_paquete = False
        for _ in range(MAX_PASOS):
            if self._cancelado():
                reg.nota("Turno cancelado por el cliente: paro antes del siguiente paso. Lo hecho queda guardado.")
                return
            r = P.estado(env, como_json=True)
            est, sig = r.estado or {}, _sin_rechazo(r.siguiente_paso or "")
            st = est.get("estado")
            if st in PARADAS:
                return
            if st == "DEVUELTA_CON_COMENTARIOS" and not permitir_devuelta:
                reg.nota("DEVUELTA: responde con ASUMIR o ACLARACIÓN si cambian los requisitos, o con SIGUE para "
                         "repetir el análisis con los mismos requisitos.")
                return
            if st == "BORRADOR":
                if reg.modelo:
                    return
                paso = fases.requisitos(P, env, est, self.cfg, self.token, reg, transporte=self.t_http)
            elif sig.startswith("enrutar") or st == "DEVUELTA_CON_COMENTARIOS":
                paso = P.enrutar(env)
                reg.nucleo(paso)
            elif sig.startswith("Enviar el brief"):
                if reg.a2a >= self.cfg.max_a2a_por_turno:
                    reg.nota("Siguiente: análisis del experto por A2A. Escribe SIGUE para lanzarlo.")
                    return
                paso = fases.experto(P, env, est, sig, self.a2a, self.cfg, reg)
            elif sig.startswith("Terminar el turno. En el siguiente: consolidar"):
                paso = P.consolidar(env)
                reg.nucleo(paso)
            elif st == "EN_VERIFICACION":
                if reg.a2a >= self.cfg.max_a2a_por_turno:
                    reg.nota("Siguiente: verificación por A2A. Escribe SIGUE para lanzarla.")
                    return
                paso = fases.verificador(P, env, est, self.a2a, self.cfg, reg)
            elif sig.startswith("Terminar el turno. En el siguiente: anexo-consumo"):
                paso = P.anexo_consumo(env)
                reg.nucleo(paso)
            elif sig.startswith("estimar"):   # decisión del 10-10-2026: el núcleo compone la entrada (A y B igual; REV-1)
                paso = P.estimar(env)
                reg.nucleo(paso)
            elif sig.startswith("paquete") and not hecho_paquete:
                paso, hecho_paquete = P.paquete(env), True
                reg.nucleo(paso)
                if st == "APROBADA":
                    return
            else:
                reg.nota(f"Paro: el siguiente paso es «{sig}» y no es automático.")
                return
            if paso is None or paso.rc != 0:
                return
        reg.nota(f"Paro tras {MAX_PASOS} pasos en un turno (tope de seguridad).")

    # ── Cierre: bloque estado literal, siguiente paso y descarga ─────────────────────────────
    def _cierre(self, P, env, reg) -> str:
        r = P.estado(env)
        partes = list(reg.lineas)
        partes.append(f"```\n{r.salida.rstrip()}\n```")
        sesion = os.environ.get("FOUNDRY_AGENT_SESSION_ID") or "<id de sesión>"
        zip_ = ((r.estado or {}).get("artefactos") or {}).get("zip") or {}
        ruta = pathlib.Path(env.raiz) / "salida" / str(zip_.get("nombre") or "")
        vigente = f"{(r.estado or {}).get('codigo')}-Paquete.zip"
        if zip_.get("nombre") and zip_["nombre"] != vigente:   # PR14-5: tras una DEVUELTA, el ZIP es de otra versión
            partes.append(f"PAQUETE: todavía no hay paquete de la versión vigente ({vigente}). El último, "
                          f"{zip_['nombre']}, es de una versión anterior y no vale para enviar.")
        elif zip_.get("nombre") and ruta.is_file() and A.sha256_fichero(ruta) != zip_.get("sha256"):
            partes.append(f"PAQUETE: {zip_['nombre']} en la carpeta de la sesión no tiene el SHA-256 que registra el "
                          "estado: no lo descargues ni lo envíes (el fichero no es el que generó el núcleo).")
        elif zip_.get("nombre") and ruta.is_file():
            rel = ruta.relative_to(self.cfg.base.parent).as_posix()
            partes.append(f"PAQUETE: {zip_['nombre']} ({zip_.get('bytes')} B, SHA-256 {zip_.get('sha256')}), guardado "
                          f"en la carpeta persistente de la sesión ({rel}). Descárgalo en tu equipo con:\n"
                          f"python hosted/descargar_sesion.py descargar --sesion {sesion} --ruta {rel}\n"
                          "y pasa verificar_paquete.py antes de enviar nada.")
        codigo = (r.estado or {}).get("codigo")
        relevo = pathlib.Path(env.raiz) / "salida" / f"{codigo}-Relevo.zip"
        if codigo and relevo.is_file():
            rel = relevo.relative_to(self.cfg.base.parent).as_posix()
            partes.append(f"RELEVO: {relevo.name} (para seguir en otra sesión con RESTAURAR). Descárgalo con:\n"
                          f"python hosted/descargar_sesion.py descargar --sesion {sesion} --ruta {rel}")
        partes.append(f"SIGUIENTE PASO: {r.siguiente_paso or 'sin estado'}")
        return "\n\n".join(partes)
