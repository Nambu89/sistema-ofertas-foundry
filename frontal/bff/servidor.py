"""BFF local del frontal de preventa: sirve la interfaz y habla con el coordinador B.

Solo escucha en 127.0.0.1 (LES-G-032). Sin inicio de sesión: es para la demo local. Una solicitud activa a la vez
(nunca dos sesiones de B contra el experto, DESPLEGAR-Y-PROBAR §1). Los turnos corren en un hilo y la interfaz
sondea GET /api/solicitudes/<id>; el avance solo sube (LES-G-031).

  python frontal/bff/servidor.py                    # contra el coordinador real (sesión az del usuario)
  python frontal/bff/servidor.py --reproduccion     # turnos reales guardados, sin red (pruebas y ensayo)
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import pathlib
import re
import sys
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import protocolo  # noqa: E402
from coordinador import RAIZ, ErrorCoordinador, TransporteFoundry, TransporteReproduccion, texto_salida  # noqa: E402

from lib.evidencia import enmascarar_texto  # noqa: E402

HOST = "127.0.0.1"
DIST = pathlib.Path(__file__).resolve().parents[1] / "web" / "dist"
DESCARGAS = pathlib.Path(__file__).resolve().parents[1] / ".descargas"
MAX_ADJUNTO = 5 * 1024 * 1024
MAX_CUERPO = MAX_ADJUNTO * 4 // 3 + 64 * 1024
MAX_TURNOS_SEGUIDOS = 15   # tope local de SIGUE automáticos por tanda; el núcleo ya limita a 3 intentos por fase
EXTENSIONES = (".txt", ".vtt", ".docx")
PILARES_ACTIVOS = {"microsoft"}
PILARES = {"microsoft", "google", "aws"}
_NOMBRE = re.compile(r"^[A-Za-z0-9._ -]{1,100}$")
_CODIGO = re.compile(r"^[A-Z0-9]{2,20}$")
_SEQOF = re.compile(r"^[0-9]{3}$")
_ID = re.compile(r"^[0-9a-f]{32}$")
_SESION = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class ErrorEntrada(ValueError):
    pass


class Ocupado(ErrorEntrada):
    """Conflicto de estado (HTTP 409): otra solicitud en marcha o esta todavía trabajando."""


def _linea(valor, nombre: str, minimo: int = 2, maximo: int = 200) -> str:
    """Un campo de una línea: sin saltos, para que nadie cuele una orden de la gramática (ASUMIR:, DECISION…)."""
    if not isinstance(valor, str):
        raise ErrorEntrada(f"Falta «{nombre}».")
    valor = " ".join(valor.split())
    if not minimo <= len(valor) <= maximo:
        raise ErrorEntrada(f"«{nombre}» debe tener entre {minimo} y {maximo} caracteres.")
    return valor


def _adjunto(datos) -> tuple[str, bytes]:
    if not isinstance(datos, dict):
        raise ErrorEntrada("Falta la transcripción adjunta.")
    nombre = datos.get("nombre")
    if not isinstance(nombre, str) or not _NOMBRE.fullmatch(nombre) or not nombre.lower().endswith(EXTENSIONES):
        raise ErrorEntrada("La transcripción debe ser .txt, .vtt o .docx, con un nombre sin rutas.")
    b64 = datos.get("base64")
    if not isinstance(b64, str) or len(b64) > MAX_ADJUNTO * 4 // 3 + 4:
        raise ErrorEntrada("La transcripción supera los 5 MB.")
    try:
        contenido = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        raise ErrorEntrada("La transcripción no ha llegado bien (base64 no válido).") from None
    if not contenido or len(contenido) > MAX_ADJUNTO:
        raise ErrorEntrada("La transcripción está vacía o supera los 5 MB.")
    if nombre.lower().endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                if "word/document.xml" not in z.namelist():
                    raise ErrorEntrada("El .docx no es un documento de Word válido.")
        except zipfile.BadZipFile:
            raise ErrorEntrada("El .docx no es un documento de Word válido.") from None
    else:
        try:
            contenido.decode("utf-8")
        except UnicodeDecodeError:
            raise ErrorEntrada("La transcripción de texto debe estar en UTF-8.") from None
    return nombre, contenido


def mensaje_alta(d: dict) -> tuple[str, tuple[str, bytes]]:
    """Valida el formulario y compone el alta con la gramática de hosted/preventa_hosted/mensajes.py."""
    pilar = d.get("pilar")
    if pilar not in PILARES:
        raise ErrorEntrada("Pilar desconocido.")
    if pilar not in PILARES_ACTIVOS:
        raise ErrorEntrada("Ese pilar está en construcción: hoy solo funciona Microsoft.")
    cliente = _linea(d.get("cliente"), "Cliente")
    codigo = _linea(d.get("codigo_cliente"), "Código de cliente").upper()
    if not _CODIGO.fullmatch(codigo):
        raise ErrorEntrada("El código de cliente va en mayúsculas y cifras, de 2 a 20 caracteres, sin espacios.")
    seqof = _linea(d.get("seqof") or "001", "SEQOF", 3, 3)
    if not _SEQOF.fullmatch(seqof):
        raise ErrorEntrada("SEQOF son tres cifras (por ejemplo, 001).")
    titulo = _linea(d.get("titulo"), "Título", 5, 160)
    sensibles = [_linea(s, "Término sensible", 2, 80).replace(";", ",") for s in d.get("sensibles") or []]
    if not sensibles:
        raise ErrorEntrada("Indica al menos un término sensible (el nombre del cliente, por ejemplo).")
    if d.get("nda") is not True:
        raise ErrorEntrada("Hay que confirmar que el NDA permite tratar la información con IA.")
    explicacion = d.get("explicacion") or ""
    # En una sola línea y al final: la gramática del alta ignora el texto libre y así no puede casar con una orden.
    explicacion = _linea(explicacion, "Explicación", 0, 2000) if explicacion else ""
    adj = _adjunto(d.get("adjunto"))
    texto = (f"Alta de solicitud nueva desde el frontal de preventa. Adjunto la transcripción {adj[0]}.\n\n"
             f"- Cliente: {cliente}\n- Código de cliente: {codigo} · SEQOF: {seqof}\n- Título: {titulo}\n"
             f"- Términos sensibles: {'; '.join(sensibles)}\n"
             "- Confirmo que el NDA con el cliente permite tratar esta información con IA en nuestro entorno de Microsoft Foundry.\n"
             "- Idioma de la oferta: castellano.\n")
    if explicacion:
        texto += f"\nExplicación del comercial: {explicacion}\n"
    return texto, adj


@dataclass
class Solicitud:
    id: str
    pilar: str
    titulo: str
    creada: float = field(default_factory=time.time)
    ocupado: bool = False
    estado: str | None = None
    fase_max: int = -1
    siguiente: str = ""
    lote: dict | None = None
    preguntas: list = field(default_factory=list)
    turnos: list = field(default_factory=list)
    error: str | None = None
    paquete: dict | None = None
    economia: dict = field(default_factory=dict)
    previa: dict | None = None
    zip: bytes | None = None

    def publico(self) -> dict:
        return {"id": self.id, "pilar": self.pilar, "titulo": self.titulo, "ocupado": self.ocupado,
                "estado": self.estado, "fase_max": self.fase_max, "fases": list(protocolo.ORDEN_FASES),
                "siguiente": self.siguiente, "lote": self.lote, "preguntas": self.preguntas, "error": self.error,
                "paquete": self.paquete and {**self.paquete, "descargado": self.zip is not None},
                "economia": self.economia, "turnos": self.turnos}


class Gestor:
    def __init__(self, transporte):
        self.t = transporte
        self.sol: dict[str, Solicitud] = {}
        self._cerrojo = threading.Lock()

    def crear(self, d: dict, en_hilo: bool = True) -> Solicitud:
        texto, adj = mensaje_alta(d)
        with self._cerrojo:
            if any(s.ocupado for s in self.sol.values()):
                raise Ocupado("Ya hay una solicitud en marcha: espera a que pare antes de abrir otra.")
            s = Solicitud(id=uuid.uuid4().hex, pilar=d["pilar"], titulo=" ".join(str(d.get("titulo")).split()))
            s.ocupado = True
            self.sol[s.id] = s
        self._lanzar(s, texto, adj, en_hilo)
        return s

    def responder(self, s: Solicitud, respuestas, en_hilo: bool = True) -> None:
        campos = {p["campo"] for p in s.preguntas}
        if not isinstance(respuestas, dict) or not respuestas or not set(respuestas) <= campos:
            raise ErrorEntrada("Responde a las preguntas que ha hecho el coordinador.")
        lineas = [f"ASUMIR: {c} = {_linea(v, c, 2, 600)}" for c, v in respuestas.items()]
        with self._cerrojo:
            if s.ocupado:
                raise Ocupado("El coordinador sigue trabajando en esta solicitud.")
            if s.estado != "INFORMACION_INSUFICIENTE":
                raise ErrorEntrada("Esta solicitud no está esperando respuestas.")
            s.ocupado, s.error = True, None
        self._lanzar(s, "\n".join(lineas) + "\n", None, en_hilo)

    def continuar(self, s: Solicitud, en_hilo: bool = True) -> None:
        """Reintenta con SIGUE tras un fallo (el núcleo cuenta los intentos)."""
        with self._cerrojo:
            if s.ocupado or s.previa is None or s.estado in protocolo.PARADAS:
                raise ErrorEntrada("No hay nada que continuar en esta solicitud.")
            s.ocupado, s.error = True, None
        self._lanzar(s, "SIGUE\n", None, en_hilo)

    def reintentar_descarga(self, s: Solicitud) -> None:
        """Tras un fallo al bajar el ZIP con el paquete ya listo: se vuelve a pedir a la sesión."""
        with self._cerrojo:
            if s.ocupado or s.estado != "LISTA_PARA_REVISION" or not s.paquete:
                raise ErrorEntrada("Esta solicitud no tiene un paquete pendiente de descargar.")
            s.ocupado = True
        try:
            self.descargar(s)
            s.error = None
        except ErrorCoordinador as e:
            s.error = f"No se ha podido descargar el paquete: {e}"
        finally:
            s.ocupado = False

    def _lanzar(self, s, texto, adj, en_hilo):
        if en_hilo:
            threading.Thread(target=self._ejecutar, args=(s, texto, adj), daemon=True).start()
        else:
            self._ejecutar(s, texto, adj)

    def _ejecutar(self, s: Solicitud, texto: str, adj) -> None:
        try:
            for _ in range(MAX_TURNOS_SEGUIDOS):
                if not self._un_turno(s, texto, adj):
                    return
                texto, adj = "SIGUE\n", None
            s.error = (f"He parado tras {MAX_TURNOS_SEGUIDOS} turnos seguidos sin llegar a una parada. "
                       "Pulsa «Continuar» para seguir o revisa el registro.")
        except ErrorCoordinador as e:
            s.error = str(e)
        except Exception as e:  # noqa: BLE001 - fail loudly: nunca un hilo que muere en silencio
            s.error = f"Fallo inesperado del frontal: {type(e).__name__}: {enmascarar_texto(str(e))[:400]}"
        finally:
            s.ocupado = False

    def _un_turno(self, s: Solicitud, texto: str, adj) -> bool:
        """Un turno con B. Devuelve True si hay que seguir con SIGUE."""
        t0 = time.monotonic()
        r = self.t.turno(texto, adj, s.previa)
        salida = enmascarar_texto(texto_salida(r))
        s.previa = {"response_id": r.get("id"),
                    "agent_session_id": r.get("agent_session_id") or (s.previa or {}).get("agent_session_id")}
        est = protocolo.ultimo_estado(salida)
        s.turnos.append({"n": len(s.turnos) + 1, "enviado": texto.splitlines()[0][:120],
                         "estado": est and est["estado"], "segundos": round(time.monotonic() - t0, 1),
                         "texto": salida})
        if r.get("status") != "completed":
            raise ErrorCoordinador(f"El turno terminó con estado «{r.get('status')}»: "
                                   f"{enmascarar_texto(json.dumps(r.get('error'), ensure_ascii=False))[:400]}")
        if "FALLO INESPERADO" in salida:
            raise ErrorCoordinador("El coordinador ha devuelto un FALLO INESPERADO: mira el último turno del registro.")
        if est is None:
            raise ErrorCoordinador("El coordinador no ha devuelto el bloque de estado: mira el último turno.")
        s.estado, s.siguiente = est["estado"], est.get("siguiente", "")
        s.fase_max = max(s.fase_max, protocolo.indice_fase(s.estado))   # LES-G-031: solo avanza
        s.lote = protocolo.lote(s.siguiente) if s.estado == "EN_VERIFICACION" else None
        s.preguntas = protocolo.preguntas(salida) if s.estado == "INFORMACION_INSUFICIENTE" else []
        s.economia.update(protocolo.economia(salida))
        paq = protocolo.paquete(salida)
        if paq:
            s.paquete, s.zip = paq, None
        if s.estado == "LISTA_PARA_REVISION" and s.paquete:
            try:   # en el mismo turno: no se espera a que caduque nada en la sesión
                self.descargar(s)
            except ErrorCoordinador as e:
                s.error = f"No se ha podido descargar el paquete: {e} Pulsa «Reintentar descarga»."
        return s.estado not in protocolo.PARADAS

    def descargar(self, s: Solicitud) -> bytes:
        if s.zip is not None:
            return s.zip
        if not s.paquete or not s.previa or not _SESION.fullmatch(s.previa.get("agent_session_id") or ""):
            raise ErrorCoordinador("Todavía no hay paquete que descargar.")
        datos = self.t.descargar(s.previa["agent_session_id"], f"preventa/trabajo/salida/{s.paquete['nombre']}")
        if len(datos) != s.paquete["bytes"] or hashlib.sha256(datos).hexdigest() != s.paquete["sha256"]:
            raise ErrorCoordinador("El ZIP descargado no coincide con la huella que dio el coordinador: no se entrega.")
        DESCARGAS.mkdir(exist_ok=True)
        (DESCARGAS / f"{s.id}-{s.paquete['nombre']}").write_bytes(datos)
        s.zip = datos
        return datos

    def resumen(self, s: Solicitud) -> dict:
        with zipfile.ZipFile(io.BytesIO(self.descargar(s))) as z:
            man = json.loads(z.read("manifiesto_paquete.json"))
            nota = z.read("mensaje_revisor.txt").decode("utf-8") if "mensaje_revisor.txt" in z.namelist() else ""
        return {"codigo": man.get("codigo"), "estado": man.get("estado"), "hash_contenido": man.get("hash_contenido"),
                "ficheros": [{"nombre": f["nombre"], "bytes": f["bytes"]} for f in man.get("ficheros", [])],
                "nota_revisor": nota, "economia": s.economia, "paquete": s.paquete}


def crear_manejador(gestor: Gestor, puerto: int):
    hosts = {f"127.0.0.1:{puerto}", f"localhost:{puerto}"}

    class Manejador(BaseHTTPRequestHandler):
        server_version = "preventa-frontal"
        sys_version = ""

        def log_message(self, fmt, *args):   # solo método, ruta y código; nunca cuerpos
            sys.stderr.write(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}\n")

        def _json(self, codigo: int, obj) -> None:
            datos = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(datos)

        def _error(self, codigo: int, mensaje: str) -> None:
            self._json(codigo, {"error": mensaje})

        def _host_ok(self) -> bool:   # contra DNS rebinding: solo el propio equipo
            if self.headers.get("Host") in hosts:
                return True
            self._error(HTTPStatus.FORBIDDEN, "Host no permitido.")
            return False

        def _solicitud(self, sid: str) -> Solicitud | None:
            s = gestor.sol.get(sid) if _ID.fullmatch(sid) else None
            if s is None:
                self._error(HTTPStatus.NOT_FOUND, "No existe esa solicitud (el frontal no guarda nada al reiniciarse).")
            return s

        def do_GET(self):
            if not self._host_ok():
                return
            ruta = self.path.split("?")[0]
            partes = [p for p in ruta.split("/") if p]
            try:
                if ruta == "/api/salud":
                    try:
                        gestor.t.comprobar_sesion()
                        return self._json(200, {"modo": gestor.t.modo, "sesion_az": True})
                    except ErrorCoordinador as e:
                        return self._json(200, {"modo": gestor.t.modo, "sesion_az": False, "detalle": str(e)})
                if partes[:2] == ["api", "solicitudes"] and len(partes) == 3:
                    s = self._solicitud(partes[2])
                    return s and self._json(200, s.publico())
                if partes[:2] == ["api", "solicitudes"] and len(partes) == 4 and partes[3] in ("paquete", "resumen"):
                    s = self._solicitud(partes[2])
                    if s is None:
                        return None
                    if partes[3] == "resumen":
                        return self._json(200, gestor.resumen(s))
                    datos = gestor.descargar(s)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f'attachment; filename="{s.paquete["nombre"]}"')
                    self.send_header("Content-Length", str(len(datos)))
                    self.end_headers()
                    self.wfile.write(datos)
                    return None
                if partes and partes[0] == "api":
                    return self._error(404, "Ruta desconocida.")
                return self._estatico(ruta)
            except ErrorCoordinador as e:
                return self._error(HTTPStatus.BAD_GATEWAY, str(e))
            except (KeyError, ValueError, zipfile.BadZipFile) as e:
                return self._error(HTTPStatus.BAD_GATEWAY, f"El paquete no se puede leer: {type(e).__name__}")

        def _estatico(self, ruta: str):
            base = DIST.resolve()
            destino = (base / ruta.lstrip("/")).resolve()
            if not destino.is_relative_to(base) or not destino.is_file():
                destino = base / "index.html"   # aplicación de una página
            if not destino.is_file():
                return self._error(503, "Falta compilar la interfaz: npm --prefix frontal/web run build")
            datos = destino.read_bytes()
            tipos = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
                     ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png", ".ico": "image/x-icon"}
            self.send_response(200)
            self.send_header("Content-Type", tipos.get(destino.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(datos)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(datos)

        def do_POST(self):
            if not self._host_ok():
                return None
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Solo JSON.")
            try:
                n = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                n = -1
            if not 0 < n <= MAX_CUERPO:
                return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "La petición está vacía o supera los 5 MB.")
            try:
                d = json.loads(self.rfile.read(n))
                if not isinstance(d, dict):
                    raise ValueError
            except ValueError:
                return self._error(400, "JSON no válido.")
            partes = [p for p in self.path.split("?")[0].split("/") if p]
            try:
                if partes == ["api", "solicitudes"]:
                    return self._json(202, gestor.crear(d).publico())
                if partes[:2] == ["api", "solicitudes"] and len(partes) == 4:
                    s = self._solicitud(partes[2])
                    if s is None:
                        return None
                    if partes[3] == "respuestas":
                        gestor.responder(s, d.get("respuestas"))
                        return self._json(202, s.publico())
                    if partes[3] == "continuar":
                        gestor.continuar(s)
                        return self._json(202, s.publico())
                    if partes[3] == "descargar":
                        gestor.reintentar_descarga(s)
                        return self._json(200, s.publico())
                return self._error(404, "Ruta desconocida.")
            except ErrorEntrada as e:
                return self._error(HTTPStatus.CONFLICT if isinstance(e, Ocupado) else 400, str(e))

    return Manejador


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Frontal local de preventa (solo 127.0.0.1)")
    ap.add_argument("--puerto", type=int, default=8765)
    ap.add_argument("--reproduccion", action="store_true", help="turnos reales guardados, sin llamar a Foundry")
    ap.add_argument("--pausa", type=float, default=1.5, help="segundos por turno en reproducción")
    a = ap.parse_args(argv)
    transporte = TransporteReproduccion(a.pausa) if a.reproduccion else TransporteFoundry()
    httpd = ThreadingHTTPServer((HOST, a.puerto), crear_manejador(Gestor(transporte), a.puerto))
    print(f"Frontal de preventa en http://127.0.0.1:{a.puerto}  (modo {transporte.modo})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
