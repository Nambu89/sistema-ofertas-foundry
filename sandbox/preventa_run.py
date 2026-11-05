"""Punto de entrada único del sandbox de preventa-coordinador (I1; CONTRATOS.md §2, §3 y §11).

Se ejecuta dentro del Code Interpreter con los ficheros montados en /mnt/data/<id>-<nombre>, o en
local (pruebas) con `sandbox/` en sys.path. Una fase por turno; cada subcomando, también si falla,
termina imprimiendo el bloque `estado` con el SIGUIENTE PASO OBLIGATORIO. Las puertas de aquí
AYUDAN pero NO CONTROLAN (el modelo domina el sandbox): la puerta real es verificar_paquete.py.

Uso: python preventa_run.py [opciones de carpetas] <subcomando> [opciones]
Subcomandos: entorno, iniciar, suficiencia, asumir, enrutar, registrar-experto, registrar-fallo,
consolidar, registrar-verificacion, anexo-consumo, estimar, paquete, decision, estado, restaurar.

Opciones de carpetas (antes del subcomando; también por variable de entorno; docs/I1/API-NUCLEO.md):
  --trabajo  PREVENTA_TRABAJO (o PREVENTA_RAIZ)  carpeta de trabajo (sandbox: /mnt/data/preventa)
  --datos    PREVENTA_DATOS    adjuntos y ficheros montados       (sandbox: /mnt/data)
  --app      PREVENTA_APP      carpeta que contiene el paquete nucleo (sandbox: /tmp/preventa/app)
  --tmp      PREVENTA_TMP      temporales del generador           (sandbox: /tmp/preventa)
  --montaje  PREVENTA_MONTAJE  sufijo (por defecto: «<id>-<nombre>» o el nombre exacto) o exacto

Capas: (1) arranque del sandbox (montaje por sufijo, file_ids, copia del núcleo), (2) entorno de
carpetas y subcomandos, que no saben de montajes, y (3) CLI. La API de biblioteca está en
preventa_api.py y llama a la misma función de despacho que la CLI.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import glob
import hashlib
import importlib
import json
import os
import pathlib
import platform
import re
import shutil
import sys
import traceback
import unicodedata
from decimal import Decimal, InvalidOperation

VERSION = "I1-1"
DATOS_SANDBOX = pathlib.Path("/mnt/data")
BASE_TMP = pathlib.Path("/tmp/preventa")
APP = BASE_TMP / "app"
GENERADOR = "generar_estimacion.py"
PLANTILLA = "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx"
CATALOGO = "catalogo_componentes.json"
RATE_CARD = "rate-card.json"


_RAIZ_WINDOWS = "C:/Users/usuario/Proyectos"   # misma resolución que desplegar.py


def raiz_proyectos() -> pathlib.Path:
    """Raíz del workspace de Proyectos (de ahí salen el generador y la plantilla canónicos en modo local):
    PREVENTA_PROYECTOS si está fijada (un valor con solo espacios cuenta como no fijado, LES-G-076); si no,
    ~/Proyectos. Nunca una ruta fija de un puesto concreto."""
    fijada = (os.environ.get("PREVENTA_PROYECTOS") or "").strip()
    if fijada:
        return pathlib.Path(fijada)
    casa, windows = pathlib.Path.home() / "Proyectos", pathlib.Path(_RAIZ_WINDOWS)
    return casa if casa.is_dir() or not windows.is_dir() else windows   # la de Windows, solo como último recurso


PROYECTOS = raiz_proyectos()   # valor al importar; Entorno.montado lo resuelve en cada llamada
UMBRAL_STOP = Decimal("100000.00")
MUTAN = ("iniciar", "suficiencia", "asumir", "enrutar", "registrar-experto", "registrar-fallo", "consolidar",
         "registrar-verificacion", "anexo-consumo", "estimar", "paquete", "decision", "restaurar")
SUBDIRECTORIOS = ("entrada", "briefs", "consolidados", "salida", "fuentes")


MARCA_APP = ".preventa-app"  # la deja preparar_sandbox: solo se borra una carpeta de la aplicación con ella
GLOBALES = {"--trabajo": "trabajo", "--datos": "datos", "--app": "app", "--tmp": "tmp", "--montaje": "montaje"}


# ---------------------------------------------------------------------------------------------
# (1) Capa de arranque del sandbox: lo único que sabe de /mnt/data, file_ids y sufijos de montaje.
# ---------------------------------------------------------------------------------------------

def es_local() -> bool:
    """Local si junto a este fichero está el paquete nucleo (en el sandbox llega como nucleo_*.py)."""
    return (pathlib.Path(__file__).resolve().parent / "nucleo" / "estado.py").is_file()


def candidatos(datos: pathlib.Path, nombre: str) -> list[pathlib.Path]:
    """Ficheros de `datos` con ese nombre exacto o terminados en «-<nombre>» (§1.2)."""
    return sorted(pathlib.Path(p) for p in glob.glob(str(datos / "*"))
                  if os.path.isfile(p) and (os.path.basename(p) == nombre or os.path.basename(p).endswith("-" + nombre)))


def localizar_exacto(datos: pathlib.Path, nombre: str) -> list[pathlib.Path]:
    """Montaje sin file_ids (opción B, pruebas): solo el fichero con ese nombre exacto."""
    ruta = pathlib.Path(datos) / nombre
    return [ruta] if ruta.is_file() else []


LOCALIZADORES = {"sufijo": candidatos, "exacto": localizar_exacto}


def _sha(ruta: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def preparar_sandbox(datos: pathlib.Path, app: pathlib.Path | None = None) -> list[str]:
    """Copia cada nucleo_<modulo>.py (nucleo_init.py = __init__.py) a <app>/nucleo (por defecto /tmp/preventa/app), lo pone en
    sys.path y comprueba el montaje contra manifiesto.json (P0). Devuelve los errores de montaje ([] si cuadra)."""
    app = APP if app is None else pathlib.Path(app)
    errores: list[str] = []
    destino = app / "nucleo"
    hijos = sorted(h.name for h in app.iterdir()) if app.is_dir() else []
    ajeno = [h for h in hijos if h not in ("nucleo", MARCA_APP)]
    if ajeno:  # solo se borra la copia del núcleo que hace este arranque, nunca una carpeta con otras cosas
        return [f"La carpeta de la aplicación {app} tiene contenido ajeno al núcleo: {', '.join(ajeno)}"]
    if hijos and MARCA_APP not in hijos:  # un nucleo/ que no copió este arranque no se borra
        return [f"La carpeta de la aplicación {app} tiene un nucleo/ que no creó el arranque (falta {MARCA_APP})"]
    if app.exists():
        shutil.rmtree(app)
    destino.mkdir(parents=True)
    (app / MARCA_APP).write_text("copia del núcleo hecha por preventa_run.preparar_sandbox", encoding="utf-8")
    # El montaje de Code Interpreter colapsa los guiones bajos repetidos del nombre («nucleo__x.py» llega
    # como «nucleo_x.py»; prueba real del 08-10-2026): prefijo con un solo guion bajo y __init__ como «init».
    for p in sorted(glob.glob(str(datos / "*nucleo_*.py"))):
        modulo = os.path.basename(p).split("nucleo_", 1)[1]
        modulo = "__init__.py" if modulo == "init.py" else modulo
        if (destino / modulo).exists():
            errores.append(f"nucleo_{modulo} montado más de una vez")
        shutil.copyfile(p, destino / modulo)
    if not (destino / "__init__.py").exists():
        (destino / "__init__.py").write_text("", encoding="utf-8")
    if str(app) not in sys.path:
        sys.path.insert(0, str(app))
    man = candidatos(datos, "manifiesto.json")
    if len(man) != 1:
        return errores + [f"manifiesto.json montado {len(man)} veces"]
    try:
        fich = json.loads(man[0].read_text(encoding="utf-8")).get("ficheros")
    except (OSError, ValueError) as e:
        return errores + [f"manifiesto.json ilegible: {e}"]
    if not isinstance(fich, dict) or not fich:
        return errores + ["manifiesto.json sin bloque «ficheros»"]
    sin_manifiesto = sorted(os.path.basename(p) for p in glob.glob(str(datos / "*nucleo_*.py"))
                            if not any(os.path.basename(p) == n or os.path.basename(p).endswith("-" + n) for n in fich))
    errores += [f"{n}: módulo del núcleo montado que no está en el manifiesto" for n in sin_manifiesto]
    for nombre, info in sorted(fich.items()):
        cand = candidatos(datos, nombre)
        if len(cand) != 1:
            errores.append(f"{nombre}: montado {len(cand)} veces")
        elif _sha(cand[0]) != (info or {}).get("sha256"):
            errores.append(f"{nombre}: SHA-256 {_sha(cand[0])} distinto del manifiesto {(info or {}).get('sha256')}")
    ya = {e.split(":", 1)[0] for e in errores}  # lo ya dicho del montaje no se repite para la copia
    return errores + [e for e in errores_copia_nucleo(destino, fich) if e.removeprefix("FALTA_NUCLEO ").split(":", 1)[0] not in ya]


def _modulo_de(nombre: str) -> str | None:
    """«nucleo_estado.py» -> «estado.py» («nucleo_init.py» -> «__init__.py»); None si no es un módulo del núcleo."""
    if not (nombre.startswith("nucleo_") and nombre.endswith(".py")):
        return None
    modulo = nombre.split("nucleo_", 1)[1]
    return "__init__.py" if modulo == "init.py" else modulo


def errores_copia_nucleo(destino: pathlib.Path, fich: dict) -> list[str]:
    """EA-6 (LES-G-090.9): la COPIA del núcleo en <app>/nucleo frente al manifiesto, antes de importar nada.
    Cada error lleva el prefijo FALTA_NUCLEO si el módulo no está en la copia (sin él no se puede importar)."""
    errores = []
    for nombre, info in sorted(fich.items()):
        modulo = _modulo_de(nombre)
        if modulo is None:
            continue
        copia = pathlib.Path(destino) / modulo
        if not copia.is_file():
            errores.append(f"FALTA_NUCLEO {nombre}: no está en la copia del núcleo ({copia})")
        elif _sha(copia) != (info or {}).get("sha256"):
            errores.append(f"{nombre}: la copia {copia} tiene SHA-256 {_sha(copia)}, distinto del manifiesto")
    return errores


def faltan_del_nucleo(p0: list[str]) -> list[str]:
    """Módulos del núcleo que faltan (en el montaje o en la copia), están montados más de una vez, no coinciden con
    el manifiesto o no están en él (EA-6). Con cualquiera de ellos el núcleo NO se importa: no se ejecuta código sin
    verificar."""
    nombres = []
    for e in p0:
        # el nombre, tal como lo escriben preparar_sandbox y errores_copia_nucleo (cualquier carácter: Revisión, 3.ª pasada)
        m = (re.match(r"^(?:FALTA_NUCLEO )?(nucleo_.*?\.py): (?:montado [0-9]+ veces|no está en la copia|"
                      r"SHA-256 |la copia )", e)
             or re.match(r"^(.*?nucleo_.*?\.py): módulo del núcleo montado que no está en el manifiesto", e))
        if m and m.group(1) not in nombres:
            nombres.append(m.group(1))
    return nombres


# ---------------------------------------------------------------------------------------------
# (2) Carpetas de la ejecución y subcomandos: reciben un Entorno y no saben de montajes.
# ---------------------------------------------------------------------------------------------

def _normalizado(valor) -> str | None:
    """Valor de opción o de variable de entorno ya normalizado: vacío o solo espacios = sin fijar (LES-G-076)."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def separar_globales(argv: list[str]) -> tuple[dict[str, str], list[str], list[str]]:
    """Separa las opciones de carpetas que van ANTES del subcomando: (opciones, resto, errores).

    Una opción mal formada (sin valor) se deja en el resto para que el parser la rechace con rc 2."""
    opciones: dict[str, str] = {}
    errores: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        nombre, igual, valor = tok.partition("=")
        if nombre not in GLOBALES:
            break
        if not igual:
            if i + 1 >= len(argv):
                break
            valor, i = argv[i + 1], i + 1
        clave = GLOBALES[nombre]
        if clave in opciones:
            errores.append(f"{nombre} repetida")
        if _normalizado(valor) is None:
            errores.append(f"{nombre} vacía")
        opciones[clave] = valor
        i += 1
    return opciones, list(argv[i:]), errores


@dataclasses.dataclass
class Entorno:
    """Carpetas de una ejecución. `raiz` es la carpeta de trabajo; `datos`, la de adjuntos y ficheros
    montados; `app`, la que contiene el paquete nucleo; `base_tmp`, la de temporales del generador;
    `montaje`, cómo se buscan los ficheros en `datos` ("sufijo" o "exacto"). En local los ficheros de
    configuración se ajustan con PREVENTA_CATALOGO, PREVENTA_RATE_CARD, PREVENTA_GENERADOR y
    PREVENTA_PLANTILLA (solo lectura de rutas)."""
    local: bool
    datos: pathlib.Path
    raiz: pathlib.Path
    p0: list[str]
    app: pathlib.Path | None = None
    base_tmp: pathlib.Path | None = None
    montaje: str = "sufijo"
    errores_config: list[str] = dataclasses.field(default_factory=list)

    @classmethod
    def resolver(cls, trabajo=None, datos=None, app=None, tmp=None, montaje=None, entorno=None) -> "Entorno":
        """Argumento > variable de entorno > valor por defecto del modo (local o sandbox)."""
        env = os.environ if entorno is None else entorno
        v = lambda nombre: _normalizado(env.get(nombre))  # noqa: E731
        errores: list[str] = []
        t_trabajo, t_raiz = v("PREVENTA_TRABAJO"), v("PREVENTA_RAIZ")
        if t_trabajo and t_raiz and t_trabajo != t_raiz:
            errores.append(f"PREVENTA_TRABAJO ({t_trabajo}) y PREVENTA_RAIZ ({t_raiz}) no coinciden")
        trabajo = _normalizado(trabajo) or t_trabajo or t_raiz
        montaje = _normalizado(montaje) or v("PREVENTA_MONTAJE") or "sufijo"
        if montaje not in LOCALIZADORES:
            errores.append(f"montaje {montaje!r} no válido: {' o '.join(sorted(LOCALIZADORES))}")
            montaje = "sufijo"
        local = es_local()
        datos = pathlib.Path(_normalizado(datos) or v("PREVENTA_DATOS") or (os.getcwd() if local else DATOS_SANDBOX))
        raiz = pathlib.Path(trabajo) if trabajo else datos / "preventa"
        tmp = _normalizado(tmp) or v("PREVENTA_TMP")
        base_tmp = pathlib.Path(tmp) if tmp else BASE_TMP
        app = _normalizado(app) or v("PREVENTA_APP")
        if app:
            app = pathlib.Path(app)
        elif local:
            app = pathlib.Path(__file__).resolve().parent
        else:
            app = base_tmp / "app" if tmp else APP
        p0 = [] if local else preparar_sandbox(datos, app)
        return cls(local, datos, raiz, p0, app=app, base_tmp=base_tmp, montaje=montaje, errores_config=errores)

    def buscar(self, nombre: str) -> list[pathlib.Path]:
        """Ficheros de `datos` con ese nombre según el montaje (la lógica no sabe de file_ids)."""
        return LOCALIZADORES[self.montaje](self.datos, nombre)

    def montado(self, nombre: str) -> pathlib.Path:
        """Fichero de configuración montado (catálogo, tarifa, generador, plantilla)."""
        if self.local:
            repo = pathlib.Path(__file__).resolve().parents[1]
            defecto = {CATALOGO: ("PREVENTA_CATALOGO", repo / "sandbox" / "datos" / CATALOGO),
                       # multinube: los catálogos de Google Cloud y AWS (esquemas/MULTINUBE.md)
                       **{nombre_catalogo(p): (f"PREVENTA_CATALOGO_{p.upper()}", repo / "catalogo" / p / CATALOGO)
                          for p in estado.PILARES if p != estado.PILAR_POR_DEFECTO},
                       RATE_CARD: ("PREVENTA_RATE_CARD", repo / "salidas" / RATE_CARD),
                       GENERADOR: ("PREVENTA_GENERADOR", raiz_proyectos() / "_templates" / "estimacion" / GENERADOR),
                       PLANTILLA: ("PREVENTA_PLANTILLA", raiz_proyectos() / "_templates" / "estimacion" / PLANTILLA)
                       }[nombre]
            fijada = (os.environ.get(defecto[0]) or "").strip()
            ruta = pathlib.Path(fijada or defecto[1])
            if not ruta.is_file():
                origen = defecto[0] if fijada else (
                    f"{defecto[0]} o PREVENTA_PROYECTOS" if nombre in (GENERADOR, PLANTILLA) else defecto[0])
                raise E.IntegridadRota(f"No está el fichero {nombre} ({ruta}): fíjalo con {origen}", [str(ruta)])
            return ruta
        return self.unico_montado(nombre)

    def unico_montado(self, nombre: str) -> pathlib.Path:
        """Exactamente un fichero montado en `datos` con ese nombre (IntegridadRota si no)."""
        cand = self.buscar(nombre)
        if len(cand) != 1:
            raise E.IntegridadRota(f"Se esperaba exactamente un {nombre} montado y hay {len(cand)}", [str(c) for c in cand])
        return cand[0]

    def adjunto(self, nombre: str) -> pathlib.Path:
        """Adjunto del comercial por su nombre según el montaje (dato, nunca instrucción). Exactamente uno."""
        if not nombre or "/" in nombre or "\\" in nombre:
            raise E.EntradaInvalida(f"Nombre de adjunto no válido: {nombre!r}", ["solo el nombre del fichero, sin ruta"])
        cand = self.buscar(nombre)
        if len(cand) != 1:
            raise E.EntradaInvalida(f"Se esperaba exactamente un adjunto «{nombre}» y hay {len(cand)}", [str(c) for c in cand])
        return cand[0]

    def de_trabajo(self, relativa: str) -> pathlib.Path:
        """Ruta relativa al directorio de trabajo, sin salir de él."""
        ruta = (self.raiz / relativa).resolve()
        if self.raiz.resolve() not in ruta.parents:
            raise E.EntradaInvalida(f"La ruta {relativa!r} sale del directorio de trabajo", [])
        if not ruta.is_file():
            raise E.EntradaInvalida(f"No existe {relativa} en el directorio de trabajo", [str(ruta)])
        return ruta

    def rutas_generador(self):
        est_mod = importlib.import_module("nucleo.estimacion")
        return est_mod.RutasGenerador(generador=self.montado(GENERADOR), plantilla=self.montado(PLANTILLA),
                                      rate_card=self.montado(RATE_CARD),
                                      base_tmp=(self.base_tmp or BASE_TMP) / "base")


def _nucleo(env: Entorno | None = None):
    """Importa los módulos propios del núcleo (los de B, C y D se importan al usarlos).

    Con `env`: importa nucleo desde env.app (falla si ya está cargado desde otra carpeta) y deja a
    nucleo.esquema buscar esquema_<nombre>.json en los datos con el montaje del entorno."""
    global E, esquema, hashes, estado, suficiencia, brief, experto, verificacion, decision, restaurar
    if env is not None and env.app is not None and str(env.app) not in sys.path:
        sys.path.insert(0, str(env.app))
    from nucleo import errores as E  # noqa: N812
    from nucleo import brief, decision, esquema, estado, experto, hashes, restaurar, suficiencia, verificacion
    if env is None:
        return
    if env.app is not None:
        origen = pathlib.Path(sys.modules["nucleo"].__file__).resolve().parent.parent
        if origen != pathlib.Path(env.app).resolve():
            raise ImportError(f"nucleo está cargado desde {origen}, no desde la carpeta de la aplicación {env.app}")
    esquema.configurar(env.unico_montado)


def modulo(nombre: str):
    """Módulo de otro constructor por su firma pública (B, C o D)."""
    return importlib.import_module(f"nucleo.{nombre}")


def imprimir_fallo(exc: Exception, rc: int) -> None:
    """§11.2: todos los errores, nunca «reintentando»."""
    mensaje = getattr(exc, "mensaje", None) or str(exc)
    print(f"FALLO [{type(exc).__name__}] rc={rc}: {mensaje}")
    for e in getattr(exc, "errores", None) or []:
        print(f"- {e}")


def codigo_salida(exc: Exception) -> int:
    for nombre, rc in (("EntradaInvalida", 2), ("TransicionNoPermitida", 3), ("IntegridadRota", 4),
                       ("ReglaIncumplida", 1), ("Bloqueo", 1)):
        if isinstance(exc, getattr(E, nombre)):
            return rc
    return 5


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse saldría con 2 sin el bloque estado
        raise E.EntradaInvalida(f"Argumentos no válidos: {message}", [self.format_usage().strip()])


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="preventa_run.py", description="Preventa I1: una fase por turno.",
                epilog="Opciones de carpetas, antes del subcomando: --trabajo, --datos, --app, --tmp y --montaje "
                       "(docs/I1/API-NUCLEO.md).")
    s = p.add_subparsers(dest="sub", required=True, parser_class=_Parser)
    s.add_parser("entorno")
    a = s.add_parser("iniciar")
    for opt in ("--cliente", "--codigo-cliente", "--seqof", "--titulo"):
        a.add_argument(opt, required=True)
    a.add_argument("--transcripcion")      # notas del comercial: al menos una de las dos (NOTAS_COMERCIAL.md)
    a.add_argument("--notas-comercial")
    a.add_argument("--sensible", action="append", required=True)
    a.add_argument("--nda-confirmado", action="store_true")
    a.add_argument("--pilar", choices=["azure", "gcp", "aws"], default="azure")   # multinube: lista blanca, rc 2 si no
    a = s.add_parser("suficiencia")
    a.add_argument("--requisitos", required=True)
    a.add_argument("--aclaracion", action="append", default=[])
    a = s.add_parser("asumir")
    a.add_argument("--campo", required=True)
    a.add_argument("--valor", required=True)
    s.add_parser("enrutar")
    a = s.add_parser("registrar-experto")
    a.add_argument("--experto", required=True, choices=["azure", "gcp", "aws"])
    a.add_argument("--respuesta", required=True)
    a = s.add_parser("registrar-fallo")
    a.add_argument("--fase", required=True, choices=["T1", "T2", "T3", "T4"])
    a.add_argument("--error", required=True)
    a.add_argument("--hipotesis", required=True)
    a = s.add_parser("consolidar")
    a.add_argument("--lotes", action="store_true", help="imprimir los lotes pendientes en lugar del consolidado completo")
    a = s.add_parser("registrar-verificacion")
    a.add_argument("--respuesta", required=True)
    s.add_parser("anexo-consumo")
    a = s.add_parser("estimar")  # REV-1: sin --entrada; la entrada la compone siempre el núcleo (10-10-2026)
    a.add_argument("--aplicar-ajuste", default=None)
    s.add_parser("paquete")
    a = s.add_parser("decision")
    a.add_argument("--linea", required=True)
    a = s.add_parser("estado")
    a.add_argument("--json", action="store_true")
    a.add_argument("--turno-nuevo", action="store_true",
                   help="EA-1: primera orden de un turno; el SIGUIENTE PASO dice lo que toca ahora")
    a = s.add_parser("restaurar")
    a.add_argument("--zip", default=None)
    a.add_argument("--estado", default=None)
    a.add_argument("--manifiesto", default=None)
    a.add_argument("--relevo", default=None, help="EA-5: relevo.json suelto, con --estado estado.json")
    return p


@dataclasses.dataclass
class Resultado:
    rc: int
    estado: dict | None
    guardado: bool = False  # el manejador ya guardó (paquete, restaurar)
    error: Exception | None = None  # solo P0 roto: el error que ya se imprimió


def _intento(est: dict, fase: str, exc: Exception, hipotesis: str):
    """Suma el intento N/3 de la fase y relanza: ReglaIncumplida, o Bloqueo si fue el 3/3."""
    errores = list(getattr(exc, "errores", None) or [])
    mensaje = getattr(exc, "mensaje", None) or str(exc)
    n = estado.registrar_intento(est, fase, f"{mensaje}: " + " | ".join(errores)[:3000], hipotesis)
    if est["estado"] == "BLOQUEADA":
        raise E.Bloqueo(f"{mensaje} (intento {n}/3: BLOQUEADA)", errores)
    raise E.ReglaIncumplida(f"{mensaje} (intento {n}/3)", errores)


def _leer_texto(env: Entorno, relativa: str) -> str:
    try:
        return env.de_trabajo(relativa).read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise E.EntradaInvalida(f"{relativa} no está en UTF-8: {e}", []) from e


def _json_modelo(est: dict, env: Entorno, relativa: str, fase: str) -> dict:
    """JSON escrito por el modelo en entrada/: ilegible cuenta como intento de la fase."""
    texto = _leer_texto(env, relativa)
    try:
        return experto.parsear(texto)
    except E.ReglaIncumplida as exc:
        _intento(est, fase, exc, f"{relativa} no es un objeto JSON válido")


def textos_fuente(env: Entorno, est: dict) -> dict[str, str]:
    """Texto de cada fuente registrada, comprobado contra su SHA-256 (caché en fuentes/<id>.txt)."""
    textos = {}
    for f in est["carga"]["fuentes"]:
        cache = env.raiz / "fuentes" / f"{f['id']}.txt"
        if cache.is_file() and hashes.sha256_texto(cache.read_text(encoding="utf-8")) == f["sha256_texto"]:
            textos[f["id"]] = cache.read_text(encoding="utf-8")
            continue
        if f["tipo"] not in estado.FUENTES_DEL_ALTA:
            raise E.IntegridadRota(f"Falta el texto de la fuente {f['id']} ({f['nombre']})", [str(cache)])
        ruta = env.adjunto(f["nombre"])
        if hashes.sha256_fichero(ruta) != f["sha256"]:
            que = "La transcripción" if f["tipo"] == "TRANSCRIPCION" else "Las notas del comercial"
            raise E.IntegridadRota(f"{que} {f['nombre']} no es la registrada en el alta",
                                   [f"SHA-256 {hashes.sha256_fichero(ruta)} frente a {f['sha256']}"])
        texto = suficiencia.extraer_texto(ruta)
        if hashes.sha256_texto(texto) != f["sha256_texto"]:
            raise E.IntegridadRota(f"El texto extraído de {f['nombre']} no es el registrado", [])
        estado.escribir_atomico(cache, texto.encode("utf-8"))
        textos[f["id"]] = texto
    return textos


def nombre_catalogo(pilar: str) -> str:
    """Multinube: «catalogo_componentes.json» en Azure (como siempre) y «catalogo_componentes_<pilar>.json» en el resto
    (en el sandbox se montan juntos; la instantánea se llama igual: anexo_consumo.nombre_instantanea)."""
    return CATALOGO if pilar == estado.PILAR_POR_DEFECTO else CATALOGO.replace(".json", f"_{pilar}.json")


def _catalogo(env: Entorno, est: dict | None) -> tuple[dict, str]:
    pilar = estado.pilar(est)
    ruta = env.montado(nombre_catalogo(pilar))
    cargar = modulo("anexo_consumo").cargar_catalogo   # Azure con la firma de siempre (dobles de las pruebas incluidos)
    cat = cargar(ruta) if pilar == estado.PILAR_POR_DEFECTO else cargar(ruta, pilar)
    return cat, hashes.sha256_fichero(ruta)


def _tarifa(env: Entorno) -> tuple[dict, list[str]]:
    em = modulo("estimacion")
    tarifa = em.cargar_tarifa(env.montado(RATE_CARD))
    return tarifa, list(em.perfiles(tarifa))


# Notas del comercial (04-11-2026, esquemas/NOTAS_COMERCIAL.md): límites de su texto (tras extraerlo) y cómo se unen las
# fuentes del alta cuando se leen juntas (hablantes, frases sin cita).
NOTAS_MIN, NOTAS_MAX = 40, 20000
TEXTO_ENTRE_FUENTES = "\n\n"


def texto_del_alta(est: dict, textos: dict[str, str]) -> str:
    """El texto de la reunión y de las notas del comercial, en su orden (con solo transcripción, el de F1)."""
    return TEXTO_ENTRE_FUENTES.join(textos[f["id"]] for f in estado.fuentes_del_alta(est))


def cmd_iniciar(args, env: Entorno, est: dict | None) -> Resultado:
    if est is not None:
        raise E.TransicionNoPermitida("Ya existe estado.json: iniciar no lo pisa", [f"estado {est['estado']}, {est['codigo']}"])
    errores = []
    if not args.nda_confirmado:
        errores.append("falta --nda-confirmado (El comercial confirma que el NDA permite tratar estos datos)")
    if len(args.cliente.strip()) < 2:
        errores.append("--cliente demasiado corto")
    if not re.fullmatch(r"[A-Z0-9]{2,20}", args.codigo_cliente or ""):
        errores.append("--codigo-cliente: mayúsculas ASCII y dígitos, de 2 a 20, sin espacios")
    if not re.fullmatch(r"\d{3}", args.seqof or ""):
        errores.append("--seqof: tres dígitos")
    if not 5 <= len(args.titulo.strip()) <= 160:
        errores.append("--titulo: entre 5 y 160 caracteres")
    cortos = [s for s in args.sensible if len(s.strip()) < 3]
    if cortos:
        errores.append(f"--sensible de menos de 3 caracteres: {cortos}")
    if not args.transcripcion and not args.notas_comercial:
        errores.append("falta la fuente: --transcripcion, --notas-comercial o las dos")
    if errores:
        raise E.EntradaInvalida("Alta no válida", errores)
    fuentes, textos = [], []
    for tipo, nombre in (("TRANSCRIPCION", args.transcripcion), ("NOTAS_COMERCIAL", args.notas_comercial)):
        if not nombre:
            continue
        ruta = env.adjunto(nombre)
        datos = ruta.read_bytes()
        texto = suficiencia.extraer_texto(ruta)
        if tipo == "NOTAS_COMERCIAL" and not NOTAS_MIN <= len(texto.strip()) <= NOTAS_MAX:
            raise E.EntradaInvalida("Alta no válida", [f"--notas-comercial: entre {NOTAS_MIN} y {NOTAS_MAX} caracteres "
                                                       f"de texto (tiene {len(texto.strip())})"])
        fuentes.append({"id": f"F{len(fuentes) + 1}", "nombre": nombre, "tipo": tipo,
                        "sha256": hashes.sha256_bytes(datos), "bytes": len(datos),
                        "sha256_texto": hashes.sha256_texto(texto)})
        textos.append(texto)
    texto = TEXTO_ENTRE_FUENTES.join(textos)
    hablantes = suficiencia.hablantes(texto)   # de la reunión y de las notas: se anonimizan igual
    nfc = lambda s: unicodedata.normalize("NFC", " ".join(s.split()))  # noqa: E731
    sensibles = sorted({nfc(s) for s in list(args.sensible) + hablantes + [args.cliente] if len(nfc(s)) >= 3})
    alta = {"cliente": nfc(args.cliente), "codigo_cliente": args.codigo_cliente, "seqof": args.seqof,
            "titulo": nfc(args.titulo), "terminos_sensibles": sensibles, "nda_confirmado": True}
    if args.pilar != estado.PILAR_POR_DEFECTO:   # multinube: Azure no escribe la clave (estado idéntico al de siempre)
        alta["pilar"] = args.pilar
    nuevo = estado.nuevo(alta, *fuentes)
    errores = estado.errores_estado(nuevo)
    if errores:
        raise E.EntradaInvalida("El alta no cabe en el esquema del estado", errores)
    for sub in SUBDIRECTORIOS:
        (env.raiz / sub).mkdir(parents=True, exist_ok=True)
    for fuente, texto_f in zip(fuentes, textos):
        estado.escribir_atomico(env.raiz / "fuentes" / f"{fuente['id']}.txt", texto_f.encode("utf-8"))
    fuente = fuentes[0]
    print(f"ALTA: OK {nuevo['codigo']} · fuente F1 {fuente['nombre']} ({fuente['bytes']} B, SHA-256 {fuente['sha256']})")
    for fuente in fuentes[1:]:
        print(f"Fuente {fuente['id']} ({fuente['tipo']}) {fuente['nombre']} ({fuente['bytes']} B, SHA-256 {fuente['sha256']})")
    if estado.sin_grabacion(nuevo):
        print(f"AVISO: {estado.AVISO_SIN_GRABACION}")
    print(f"Términos sensibles: {len(sensibles)} (hablantes añadidos: {', '.join(hablantes) or 'ninguno'})")
    return Resultado(0, nuevo)


def _preguntas(res) -> None:
    print("=== PREGUNTAS PARA EL COMERCIAL ===")
    for q in res.preguntas:
        print(q)
    print("=== FIN PREGUNTAS ===")


def _registrar_aclaracion(env: Entorno, est: dict, relativa: str) -> str:
    ruta = env.de_trabajo(relativa)
    datos = ruta.read_bytes()
    try:
        texto = unicodedata.normalize("NFC", datos.decode("utf-8-sig").replace("\r\n", "\n"))
    except UnicodeDecodeError as e:
        raise E.EntradaInvalida(f"{relativa} no está en UTF-8", [str(e)]) from e
    if len(texto.strip()) < 3:
        raise E.EntradaInvalida(f"{relativa} está vacía", [])
    sha = hashes.sha256_bytes(datos)
    previa = next((f for f in est["carga"]["fuentes"] if f["sha256"] == sha), None)
    if previa:
        cache = env.raiz / "fuentes" / f"{previa['id']}.txt"
        if not cache.is_file() and hashes.sha256_texto(texto) == previa["sha256_texto"]:
            estado.escribir_atomico(cache, texto.encode("utf-8"))  # tras restaurar sin su texto: se repone
        return previa["id"]
    fid = f"F{len(est['carga']['fuentes']) + 1}"
    est["carga"]["fuentes"].append({"id": fid, "nombre": ruta.name, "tipo": "ACLARACION", "sha256": sha,
                                    "bytes": len(datos), "sha256_texto": hashes.sha256_texto(texto)})
    estado.escribir_atomico(env.raiz / "fuentes" / f"{fid}.txt", texto.encode("utf-8"))
    return fid


def cmd_suficiencia(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "suficiencia")
    nuevas = [_registrar_aclaracion(env, est, a) for a in args.aclaracion]
    req = _json_modelo(est, env, args.requisitos, "T1")
    textos = textos_fuente(env, est)
    catalogo, _ = _catalogo(env, est)   # PR18-1 (I1.9, CAMBIOS-I19-P §5.1): lo que el cliente ya tiene se casa con el catálogo
    try:
        res = suficiencia.aplicar(est, req, textos, catalogo)
    except E.ReglaIncumplida as exc:
        _intento(est, "T1", exc, "requisitos.json no cumple el contrato (§3.3): revisar esquema, fuentes y ASUMIDO")
    if res.citas_invalidas:
        _intento(est, "T1", E.ReglaIncumplida("Citas que no están literales en las fuentes", res.citas_invalidas),
                 "El modelo parafraseó o inventó la cita: copiarla literal de la transcripción")
    if nuevas:
        print(f"Aclaraciones registradas como fuentes: {', '.join(nuevas)}")
    _avisar_frases_sin_cita(est, texto_del_alta(est, textos))
    if res.completo:
        estado.transitar(est, "suficiencia", "EN_ANALISIS")
        est["intentos"]["T1"] = 0
        print("SUFICIENCIA: COMPLETA (bloqueantes citados; asumibles citados o asumidos)")
        return Resultado(0, est)
    estado.transitar(est, "suficiencia", "INFORMACION_INSUFICIENTE")
    print(f"SUFICIENCIA: INCOMPLETA. Faltan: {', '.join(res.faltan)}")
    _preguntas(res)
    return Resultado(1, est)


def citas_requisitos(est: dict) -> list[str]:
    campos = ((est["carga"].get("requisitos") or {}).get("campos")) or {}
    return [e["cita"] for d in campos.values() for e in d.get("entradas") or [] if e.get("cita")]


def _avisar_frases_sin_cita(est: dict, texto_f1: str) -> None:
    """VERIF-2: avisa (no bloquea) de las frases con forma de requisito que ningún campo cita enteras."""
    for frase, suelta in suficiencia.frases_requisito_sin_cita(texto_f1, citas_requisitos(est)):
        print(f"AVISO (para el comercial y la nota): frase con forma de requisito que ningún campo cita entera: "
              f"«{frase}» · sin citar: «{suelta}»")


def _transcripcion_o_motivo(env: Entorno, est: dict) -> str | Exception:
    """Texto de F1 para la nota del revisor o, si no se puede leer, la excepción (la nota lo declara)."""
    try:
        return texto_del_alta(est, textos_fuente(env, est))
    except (E.ErrorPreventa, OSError, KeyError) as exc:
        return exc


def cmd_asumir(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "asumir")
    res = suficiencia.asumir(est, args.campo, args.valor)
    print(f"ASUMIDO [BAJA]: {args.campo} = {est['carga']['requisitos']['campos'][args.campo]['entradas'][0]['valor']}")
    if res.completo:
        estado.transitar(est, "asumir", "EN_ANALISIS")
        est["intentos"]["T1"] = 0  # H11: igual que cuando la completa suficiencia
        print("SUFICIENCIA: COMPLETA")
    else:
        estado.transitar(est, "asumir", "INFORMACION_INSUFICIENTE")
        print(f"SUFICIENCIA: INCOMPLETA. Faltan: {', '.join(res.faltan)}")
        _preguntas(res)
    return Resultado(0, est)


def cmd_enrutar(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "enrutar")
    _, cat_sha = _catalogo(env, est)
    _, perfiles = _tarifa(env)
    personas = suficiencia.hablantes(texto_del_alta(est, textos_fuente(env, est)))
    b = brief.generar(est, perfiles, cat_sha, personas=personas)  # no depende del estado, solo de versión y ronda
    estado.transitar(est, "enrutar", "EN_ANALISIS")
    estado.escribir_atomico(env.raiz / "briefs" / f"{b.brief_id}.txt", (b.texto + "\n").encode("utf-8"))
    print(f"Brief {b.brief_id} (ronda {b.ronda}, SHA-256 {b.sha256}) en briefs/{b.brief_id}.txt")
    print("=== BRIEF PARA preventa-experto-azure ===")
    print(b.texto)
    print("=== FIN BRIEF ===")
    return Resultado(0, est)


def cmd_registrar_experto(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "registrar-experto")
    texto = _leer_texto(env, args.respuesta)
    catalogo, _ = _catalogo(env, est)
    _, perfiles = _tarifa(env)
    reg = experto.registrar(est, args.experto, texto, catalogo, perfiles, estado.hoy().isoformat())
    estado.transitar(est, "registrar-experto", "EN_ANALISIS")
    r = reg["respuesta"]
    print(f"EXPERTO: VÁLIDA para {reg['brief_id']} · {len(r['referencias'])} referencias, {len(r['componentes'])} "
          f"componentes, {len(r['precios'])} precios, {len(r['tareas_propuestas'])} tareas propuestas")
    for a in experto.avisos_respuesta(r, catalogo):
        print(f"AVISO (para la nota): {a}")
    return Resultado(0, est)


def cmd_registrar_fallo(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "registrar-fallo")
    n = estado.registrar_intento(est, args.fase, args.error, args.hipotesis)
    print(f"FALLO REGISTRADO: {args.fase} intento {n}/3 · error literal guardado en fallos[{len(est['fallos']) - 1}]")
    return Resultado(1 if est["estado"] == "BLOQUEADA" else 0, est)


def cmd_consolidar(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "consolidar")
    catalogo, _ = _catalogo(env, est)
    c = verificacion.consolidar(est, catalogo)
    estado.transitar(est, "consolidar", "EN_VERIFICACION")
    estado.escribir_atomico(env.raiz / "consolidados" / f"{c.consolidado_id}.txt", (c.texto + "\n").encode("utf-8"))
    print(f"Consolidado {c.consolidado_id} ({len(c.ids)} elementos, SHA-256 {c.sha256}) en consolidados/{c.consolidado_id}.txt")
    if not getattr(args, "lotes", False):
        print("=== CONSOLIDADO PARA preventa-verificador ===")
        print(c.texto)
        print("=== FIN CONSOLIDADO ===")
        return Resultado(0, est)
    pendientes = verificacion.lotes_pendientes(est)
    print(f"LOTES: {len(c.lotes)} en total, {len(pendientes)} pendientes (cada uno, una llamada al verificador)")
    for x in pendientes:
        estado.escribir_atomico(env.raiz / "consolidados" / f"{x['lote_id']}.txt", (x["texto"] + "\n").encode("utf-8"))
        print(f"=== LOTE {x['lote_id']} PARA preventa-verificador ({len(x['ids'])} elementos, SHA-256 {x['sha256']}) ===")
        print(x["texto"])
        print("=== FIN LOTE ===")
    return Resultado(0, est)


def cmd_registrar_verificacion(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "registrar-verificacion")
    texto = _leer_texto(env, args.respuesta)
    catalogo, _ = _catalogo(env, est)   # VC18-3 (I1.9): la región de un DISCREPA se contrasta con la disponibilidad
    res = verificacion.registrar(est, texto, estado.hoy().isoformat(), catalogo=catalogo)
    if not res.completa:
        print(f"LOTE {res.lote} registrado. Faltan {len(res.pendientes)}: {', '.join(res.pendientes)}")
        return Resultado(0, est)
    print(f"VERIFICACIÓN ronda {est['ronda_verificacion']}: {'VERIFICADA' if res.verificada else 'CON DISCREPANCIAS'} · "
          f"DISCREPA {len(res.discrepa)}, NO VERIFICABLE {len(res.no_verificables)}, reparados {len(res.reparados)}")
    for linea in verificacion.lineas_discrepa_turno(est):   # PR18-7 (I1.9): campo, valor, fuente y detalle
        print(linea)
    for d in res.no_verificables:
        print(f"- NO VERIFICABLE {d['id']} (riesgo residual): {d['motivo']}")
    for d in res.reparados:
        print(f"- reparado {d['id']}: {d['motivo']}")
    for d in res.observaciones:
        print(f"- OBSERVACIÓN {d['id']} (para la nota del revisor, no bloquea): {d['detalle']}")
    return Resultado(0 if res.verificada else 1, est)


def _exigir_verificada(est: dict) -> None:
    ver = est["carga"].get("verificacion")
    if not ver or not ver["resultado"]["verificada"]:
        raise E.TransicionNoPermitida("Hace falta una verificación sin DISCREPA efectivos", [])


def cmd_anexo(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "anexo-consumo")
    _exigir_verificada(est)
    catalogo, _ = _catalogo(env, est)
    anexo = modulo("anexo_consumo").aplicar(est, catalogo, env.raiz / "salida")
    estado.invalidar_desde(est, "anexo_consumo")
    estado.transitar(est, "anexo-consumo", "VERIFICADA")
    print(f"ANEXO DE CONSUMO: {len(anexo['lineas'])} líneas · {anexo['total_mensual_eur']} EUR/mes · "
          f"{anexo['total_anual_eur']} EUR/año (orientativo; fuente {anexo['fuente']['nombre']})")
    for clave in ("anexo_xlsx", "anexo_json"):
        a = est["artefactos"].get(clave)
        if a:
            print(f"  salida/{a['nombre']} SHA-256 {a['sha256']}")
    return Resultado(0, est)


def _precio(resumen: dict) -> Decimal:
    try:
        return Decimal(str(resumen["precio_cerrado_eur"]))
    except (KeyError, InvalidOperation) as e:
        raise E.IntegridadRota("La estimación no trae un precio cerrado legible", [repr(e)]) from e


def _componer_entrada(est: dict, env: Entorno, em, tarifa: dict, ajuste_d: dict | None) -> dict:
    """Decisión del comercial del 10-10-2026: la entrada del generador la compone el NÚCLEO desde tareas_propuestas
    (nucleo.estimacion.componer_entrada, la misma regla que usa B). Queda escrita en entrada/estimacion_entrada.json
    para la trazabilidad; ningún modelo la escribe."""
    try:
        ajuste = em.leer_ajuste(ajuste_d) if ajuste_d is not None else None
        entrada, avisos = em.componer_entrada(est, em.hitos_tarifa(tarifa), estado.hoy(), ajuste)
    except ValueError as exc:
        _intento(est, "T4", E.ReglaIncumplida("No se puede componer la entrada de la estimación", [str(exc)]),
                 "Faltan datos del experto, del alta o de la decisión de ajuste para componer la estimación")
    datos = (json.dumps(entrada, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    estado.escribir_atomico(env.raiz / "entrada" / "estimacion_entrada.json", datos)
    print(f"ENTRADA DE ESTIMACIÓN compuesta por el núcleo desde tareas_propuestas: entrada/estimacion_entrada.json "
          f"SHA-256 {hashes.sha256_bytes(datos)} · {len(entrada['tareas'])} tareas · {entrada['duracion_semanas']} semanas")
    for a in avisos:
        print(f"AVISO (para el comercial y la nota): {a}")
    return entrada


def cmd_estimar(args, env: Entorno, est: dict) -> Resultado:
    estado.exigir_disparador(est, "estimar")
    _exigir_verificada(est)
    if not est["carga"].get("anexo_consumo"):
        raise E.TransicionNoPermitida("Primero anexo-consumo (orden de T4: anexo-consumo, estimar, paquete)", [])
    d = None
    if args.aplicar_ajuste:
        d = next((x for x in est["decisiones"] if x["id"] == args.aplicar_ajuste), None)
        if d is None or d["tipo"] != "AJUSTE_COMERCIAL" or decision.vigente(est, "AJUSTE_COMERCIAL") is not d:
            raise E.ReglaIncumplida(f"--aplicar-ajuste {args.aplicar_ajuste}: no es la decisión AJUSTE_COMERCIAL vigente",
                                    ["la decisión debe citar el hash_contenido vigente justo antes de estimar"])
    catalogo, _ = _catalogo(env, est)
    tarifa, _ = _tarifa(env)
    em = modulo("estimacion")
    # REV-1 (I1.4): ya no hay forma heredada con --entrada; y aunque alguien escribiera otra entrada, validar_entrada
    # la recompone con la regla (P6f) y la rechaza si difiere
    entrada = _componer_entrada(est, env, em, tarifa, d if args.aplicar_ajuste else None)
    antes = est["intentos"]["T4"]
    try:
        res = em.estimar(est, entrada, tarifa, env.rutas_generador(), env.raiz / "salida", args.aplicar_ajuste)
    except E.ReglaIncumplida as exc:
        if est["intentos"]["T4"] == antes:
            _intento(est, "T4", exc, "La entrada de estimación incumple una regla dura (P6/P7): corregirla desde tareas_propuestas")
        raise
    est["carga"]["textos_cliente"] = modulo("textos_cliente").componer(est, catalogo, tarifa)
    precio = _precio(res.resumen)
    stop = bool(res.stop) or precio > UMBRAL_STOP
    a = est["artefactos"].get("xlsx_estimacion") or {}
    print(f"ESTIMACIÓN: precio cerrado {res.resumen['precio_cerrado_eur']} EUR (IVA no incluido) · "
          f"XLSX canónico salida/{a.get('nombre', '?')} SHA-256 {res.xlsx_sha256}")
    # equivale a estimacion.requiere_stop(est): CONFIRMA_STOP se mira con el hash ya final (CAMBIOS-BB §2)
    if stop and decision.vigente(est, "CONFIRMA_STOP") is None:
        estado.transitar(est, "estimar", "STOP_PRESUPUESTO")
        print(f"STOP: {precio} EUR > {UMBRAL_STOP} EUR. Hace falta la confirmación del comercial con el hash vigente.")
        return Resultado(1, est)
    estado.transitar(est, "estimar", "VERIFICADA")
    est["intentos"]["T4"] = 0
    return Resultado(0, est)


def cmd_paquete(args, env: Entorno, est: dict) -> Resultado:
    """Transita (si VERIFICADA), guarda, construye el ZIP y, si algo falla, deja el estado como estaba."""
    estado.exigir_disparador(est, "paquete")
    c = est["carga"]
    if not c.get("anexo_consumo") or not c.get("estimacion") or not c.get("textos_cliente"):
        raise E.TransicionNoPermitida("paquete exige anexo_consumo, estimacion y textos_cliente en la carga", [])
    if _precio(c["estimacion"]["resumen"]) > UMBRAL_STOP and decision.vigente(est, "CONFIRMA_STOP") is None:
        raise E.ReglaIncumplida("Precio > 100.000 EUR sin CONFIRMA_STOP que cite el hash vigente (LES-G-004)", [])
    catalogo, cat_sha = _catalogo(env, est)  # todo lo que puede fallar antes de tocar estado.json
    tarifa, _ = _tarifa(env)
    rutas = env.rutas_generador()
    transcripcion = _transcripcion_o_motivo(env, est)  # VERIF-2: frases sin cita en la nota
    constructor = modulo("paquete")
    original = copy.deepcopy(est)
    hash_antes = hashes.hash_contenido(est)
    if est["estado"] == "VERIFICADA":
        estado.transitar(est, "paquete", "LISTA_PARA_REVISION")
    estado.anotar_control(est, "paquete", original["estado"], hash_antes)
    estado.guardar(est, env.raiz)
    nombre_zip = f"{est['codigo']}-Paquete.zip"
    ruta_zip = env.raiz / "salida" / nombre_zip
    anterior = ruta_zip.with_name(nombre_zip + ".anterior")
    if ruta_zip.exists():  # un ZIP de una ejecución anterior no puede pasar por el nuevo
        os.replace(ruta_zip, anterior)
    try:
        man = constructor.construir(est, env.raiz, catalogo, tarifa, rutas, catalogo_sha256=cat_sha,
                                    transcripcion=transcripcion)
        if hashes.hash_contenido(est) != hash_antes:
            raise E.IntegridadRota("paquete cambió hash_contenido (no debe)", [f"antes {hash_antes}",
                                                                              f"después {hashes.hash_contenido(est)}"])
        if not ruta_zip.is_file():
            raise E.IntegridadRota(f"paquete terminó sin escribir salida/{nombre_zip}", [])
    except BaseException:
        if anterior.exists():
            os.replace(anterior, ruta_zip)  # vuelve el ZIP anterior, que cuadra con el estado original
        estado.guardar(original, env.raiz)  # el estado vuelve a como estaba antes de paquete
        est.clear()  # y también en memoria: el despachador vuelve a guardar si el fallo es rc 1
        est.update(copy.deepcopy(original))
        raise
    if anterior.exists():
        anterior.unlink()
    estado.guardar(est, env.raiz)
    print(f"PAQUETE: OK salida/{nombre_zip} ({ruta_zip.stat().st_size} B, SHA-256 {hashes.sha256_fichero(ruta_zip)})")
    print(f"Manifiesto: {len(man.get('ficheros', []))} ficheros · hash_contenido {man.get('hash_contenido')} · "
          f"estado.json SHA-256 {man.get('estado_json_sha256')}")
    _imprimir_confirmaciones(est)
    print("Descargar el ZIP en este turno (el contenedor caduca a los 20 minutos) y citarlo en la respuesta.")
    return Resultado(0, est, guardado=True)


def _imprimir_confirmaciones(est: dict) -> None:
    """R2: lo que la puerta local exigirá por línea de órdenes (la decisión queda trazada en estado.json)."""
    for c in decision.confirmaciones_locales(est):
        quien = (f"{c['decision_id']} (huella de la línea {c['huella_linea']})" if c["decision_id"]
                 else "FALTA la decisión que lo respalde")
        importe = c.get("precio_eur") or c.get("importe_eur")
        print(f"CONFIRMACIÓN LOCAL OBLIGATORIA: {c['tipo']} · {importe} EUR · {quien}. verificar_paquete.py exigirá "
              f"{c['opcion']} {c['hash']}, tecleado por el comercial en su puesto.")


def cmd_decision(args, env: Entorno, est: dict) -> Resultado:
    """Registra la decisión, la guarda y deja salida/<codigo>-Relevo.zip para seguir en otra conversación (H12).
    Si el relevo no se puede escribir, el estado vuelve a como estaba (no hay decisión sin relevo)."""
    version, antes, hash_antes = est["version"], est["estado"], hashes.hash_contenido(est)
    original = copy.deepcopy(est)
    d = decision.registrar(est, args.linea, estado.hoy())
    estado.anotar_control(est, "decision", antes, hash_antes)
    est["hash_contenido"] = hashes.hash_contenido(est)  # lo mismo que hará guardar
    compuesto = restaurar.componer_relevo(est, env.raiz)  # en memoria: si falla, no se ha escrito nada
    estado.guardar(est, env.raiz)
    try:
        rel = restaurar.publicar_relevo(compuesto, env.raiz)
    except BaseException as exc:
        try:
            estado.guardar(original, env.raiz)
        except Exception as exc2:  # p. ej., disco lleno: se dice en alto, no se calla
            raise E.IntegridadRota(f"La decisión {d['id']} quedó guardada SIN relevo y no se pudo volver atrás",
                                   [f"relevo: {exc!r}", f"vuelta atrás: {exc2!r}",
                                    "parar y avisar al comercial: estado.json del contenedor contiene la decisión"]) from exc2
        est.clear()
        est.update(copy.deepcopy(original))
        raise
    print(f"DECISIÓN REGISTRADA: {d['id']} · {d['tipo']} · {d['revisor']} · {d['fecha']} · {d['estado_antes']} -> {d['estado_despues']}")
    if est["version"] != version:
        print(f"Nueva versión {est['version']} ({est['codigo']}): estimación y textos para el cliente anulados.")
    if d["tipo"] in decision.OPCION_CONFIRMACION:
        _imprimir_confirmaciones(est)
    print(f"RELEVO: salida/{rel['nombre']} ({rel['bytes']} B, SHA-256 {rel['sha256']}) · {len(rel['incluidos'])} "
          f"ficheros. Descargarlo en este turno: en una conversación nueva basta con adjuntarlo y ejecutar "
          f"restaurar --zip {rel['nombre']} (sin volver a pegar las decisiones).")
    for o in rel["omitidos"]:
        print(f"  no incluido en el relevo: {o}")
    return Resultado(0, est, guardado=True)


def cmd_estado(args, env: Entorno, est: dict | None) -> Resultado:
    if args.json and est is not None:
        print(json.dumps(est, ensure_ascii=False, indent=2))
    return Resultado(0, est)


def cmd_restaurar(args, env: Entorno, est: dict | None) -> Resultado:
    """--zip <Paquete.zip | Relevo.zip> (recupera los económicos byte a byte), --estado y --relevo (los JSON del
    relevo sueltos, EA-5) o --estado y --manifiesto (forma antigua)."""
    formas = [bool(args.zip), bool(args.estado and args.relevo), bool(args.estado and args.manifiesto)]
    if sum(formas) != 1 or (args.zip and (args.estado or args.manifiesto or args.relevo)) \
            or (args.relevo and args.manifiesto):
        raise E.EntradaInvalida("restaurar: o --zip <último ZIP descargado, Paquete o Relevo>, o --estado estado.json "
                                "--relevo relevo.json (sacados del Relevo.zip), o --estado y --manifiesto",
                                ["preferida: restaurar --zip OF-…-Paquete.zip (o OF-…-Relevo.zip si hubo decisiones después)",
                                 "si el ZIP no se puede adjuntar: --estado estado.json --relevo relevo.json"])
    omitidos: list[str] = []
    if args.zip:
        nuevo, tipo, repuestos = restaurar.restaurar_zip(env.raiz, env.adjunto(args.zip))
        ancla = f"el {tipo} {pathlib.Path(args.zip).name}"
    elif args.relevo:
        nuevo, repuestos, omitidos = restaurar.restaurar_relevo(env.raiz, env.adjunto(args.estado),
                                                                env.adjunto(args.relevo), env.buscar)
        ancla = f"el relevo {pathlib.Path(args.relevo).name}"
    else:
        nuevo = restaurar.restaurar(env.raiz, env.adjunto(args.estado), env.adjunto(args.manifiesto))
        repuestos, ancla = [], "el manifiesto"
    print(f"RESTAURADO: {nuevo['codigo']} en {nuevo['estado']} · hash_contenido {nuevo['hash_contenido']} "
          f"(coincide con el estado, {ancla} y el recalculado)")
    for rel in repuestos:
        print(f"  recuperado byte a byte: {rel}")
    for o in omitidos:
        print(f"  no restaurado: {o}")
    if not (env.raiz / "salida" / f"{nuevo['codigo']}-Estimacion.xlsx").is_file() and nuevo["carga"].get("estimacion"):
        print("Los XLSX no están en este contenedor: paquete los regenerará con otra fecha interna y el --previo de "
              "verificar_paquete fallará (H7). Mejor: restaurar --zip con el último Paquete o Relevo.")
    antes, hash_antes = nuevo["estado"], hashes.hash_contenido(nuevo)
    migrado = restaurar.migrar_sin_canales(nuevo)
    if migrado:  # REV-3: estado de antes de VERIF-2; se guarda la migración como un control más de restaurar
        estado.anotar_control(nuevo, "restaurar", antes, hash_antes)
        estado.guardar(nuevo, env.raiz)
        for linea in migrado:
            print(f"MIGRADO: {linea}")
        print("PREGUNTA PARA COMERCIAL (a/b/c/d):")
        print(suficiencia.preguntas_para("canales_integraciones"))
    return Resultado(0, nuevo, guardado=True)


def cmd_entorno(args, env: Entorno, est: dict | None) -> Resultado:
    print(f"preventa_run {VERSION} | python {sys.version.split()[0]} | {platform.platform()} | "
          f"{'local' if env.local else 'sandbox'}")
    for m in ("openpyxl", "pptx", "docx", "fitz"):
        try:
            mod = importlib.import_module(m)
            print(f"  {m} {getattr(mod, '__version__', getattr(mod, 'VERSION', '?'))}")
        except Exception as e:  # se informa, no se oculta
            print(f"  {m} ERROR {e!r}")
    rutas = sorted(p for p in env.datos.glob("*") if p.is_file())
    print(f"Ficheros en {env.datos}: {len(rutas)}")
    for p in rutas:
        print(f"  {p.name}  {p.stat().st_size} B  {oct(p.stat().st_mode & 0o777)}  {_sha(p)}")
    if env.local:
        print("P0 MONTAJE: local, no aplica (la comprobación real es verificar_paquete.py)")
        return Resultado(0, est)
    if env.p0:
        print("P0 MONTAJE: ROTO")
        for e in env.p0:
            print(f"  - {e}")
        faltan = faltan_del_nucleo(env.p0)
        if faltan:
            print(f"MÓDULOS DEL NÚCLEO QUE FALTAN O NO COINCIDEN: {', '.join(faltan)}")
        return Resultado(4, est)
    print("P0 MONTAJE: OK (los ficheros montados coinciden con manifiesto.json)")
    return Resultado(0, est)


def entorno_sin_nucleo(env: Entorno) -> int:
    """EA-6: `entorno` desde la CLI NO importa el núcleo, para diagnosticar justo cuando el núcleo no carga."""
    res = cmd_entorno(None, env, None)
    if env.p0:
        faltan = faltan_del_nucleo(env.p0)
        paso = ("parar y avisar al comercial: el montaje no coincide con manifiesto.json"
                + (f" y hay módulos del núcleo que faltan o no coinciden ({', '.join(faltan)})" if faltan else "")
                + "; nueva conversación o volver a montar los ficheros de la definición")
    else:
        paso = "ejecutar estado (entorno no importa el núcleo ni lee la solicitud)"
    print(f"=== ESTADO PREVENTA ===\nestado: NO_CONSULTADO (entorno no importa el núcleo)\n"
          f"SIGUIENTE PASO OBLIGATORIO: {paso}\n=== FIN ESTADO ===")
    return res.rc


MANEJADORES = {
    "entorno": cmd_entorno, "iniciar": cmd_iniciar, "suficiencia": cmd_suficiencia, "asumir": cmd_asumir,
    "enrutar": cmd_enrutar, "registrar-experto": cmd_registrar_experto, "registrar-fallo": cmd_registrar_fallo,
    "consolidar": cmd_consolidar, "registrar-verificacion": cmd_registrar_verificacion, "anexo-consumo": cmd_anexo,
    "estimar": cmd_estimar, "paquete": cmd_paquete, "decision": cmd_decision, "estado": cmd_estado,
    "restaurar": cmd_restaurar,
}
SIN_ESTADO_ADMITIDOS = ("entorno", "estado", "iniciar", "restaurar")


def _cargar_si_existe(env: Entorno) -> dict | None:
    return estado.cargar(env.raiz) if estado.existe(env.raiz) else None


def _montaje_roto(env: Entorno, sub: str, est: dict | None) -> Resultado:
    """P0 roto en un subcomando que muta: BLOQUEADA (si hay estado que bloquear) y rc 4."""
    exc = E.IntegridadRota("P0: los ficheros montados no coinciden con manifiesto.json", list(env.p0))
    imprimir_fallo(exc, 4)
    if est is not None and est["estado"] not in ("APROBADA", "BLOQUEADA"):
        antes, h = est["estado"], hashes.hash_contenido(est)
        estado.bloquear(est, "IntegridadRota del montaje: " + "; ".join(env.p0)[:1500])
        estado.anotar_control(est, sub, antes, h)
        estado.guardar(est, env.raiz)
    return Resultado(4, est, guardado=True, error=exc)


# ---------------------------------------------------------------------------------------------
# (3) Despacho y CLI. preventa_api.py llama a _despachar() con un Entorno ya resuelto.
# ---------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Despacho:
    """Resultado de un subcomando: rc de §11.1, estado final (el del bloque estado) y el error, si lo hubo."""
    rc: int
    estado: dict | None
    error: Exception | None = None


def _despachar(argv: list[str], env: Entorno) -> Despacho:
    """Despacha, aplica §11.1 (qué se guarda según el rc) e imprime SIEMPRE el bloque estado."""
    est0: dict | None = None
    final: dict | None = None
    rc, error = 5, None
    turno_nuevo = False
    try:
        if env.errores_config:
            raise E.EntradaInvalida("Configuración de carpetas no válida", list(env.errores_config))
        args = parser().parse_args(argv)
        sub = args.sub
        turno_nuevo = bool(getattr(args, "turno_nuevo", False))  # EA-1: solo `estado --turno-nuevo`
        if sub != "restaurar":
            est0 = _cargar_si_existe(env)
        final = est0
        if env.p0 and sub in MUTAN:
            res = _montaje_roto(env, sub, copy.deepcopy(est0) if est0 else None)
            rc, final, error = res.rc, res.estado, res.error
            return Despacho(rc, final, error)
        if est0 is None and sub not in SIN_ESTADO_ADMITIDOS:
            raise E.EntradaInvalida("No hay estado.json en el directorio de trabajo",
                                    ["primero iniciar (alta) o restaurar (contenedor caducado)"])
        if est0 is not None and est0["estado"] == "BLOQUEADA" and sub not in estado.EN_BLOQUEADA:
            raise E.TransicionNoPermitida(f"La solicitud está BLOQUEADA: «{sub}» no se admite",
                                          [f"motivo: {est0.get('motivo_bloqueo')}",
                                           f"solo se admiten: {', '.join(estado.EN_BLOQUEADA)}"])
        trabajo = copy.deepcopy(est0)
        antes = (est0 or {}).get("estado")
        hash_antes = hashes.hash_contenido(est0) if est0 else None
        guardar = sub in MUTAN
        try:
            res = MANEJADORES[sub](args, env, trabajo)
            rc, final = res.rc, res.estado
            guardar = guardar and not res.guardado
        except (E.ReglaIncumplida, E.Bloqueo) as exc:  # §11.1: rc 1 y se guardan contadores y estado
            rc, error = 1, exc
            imprimir_fallo(exc, rc)
            final = trabajo
        if guardar and final is not None:
            estado.anotar_control(final, sub, antes, hash_antes)
            estado.guardar(final, env.raiz)
        return Despacho(rc, final, error)
    except E.ErrorPreventa as exc:  # EntradaInvalida, TransicionNoPermitida, IntegridadRota: no se guarda
        rc, error = codigo_salida(exc), exc
        imprimir_fallo(exc, rc)
        final = est0
        return Despacho(rc, final, error)
    except Exception as exc:  # inesperado: rc 5 con la traza completa
        rc, error = 5, exc
        print(f"FALLO [{type(exc).__name__}] rc=5: error inesperado: {exc}")
        traceback.print_exc(file=sys.stdout)
        final = est0
        return Despacho(rc, final, error)
    finally:
        try:
            print(estado.bloque_estado(final, turno_nuevo=turno_nuevo))
        except Exception as exc:  # el bloque se intenta siempre; si no se puede, se dice
            print(f"=== ESTADO PREVENTA ===\nestado: ILEGIBLE ({type(exc).__name__}: {exc})\n"
                  "SIGUIENTE PASO OBLIGATORIO: parar y avisar al comercial\n=== FIN ESTADO ===")


def ejecutar(argv: list[str], env: Entorno) -> int:
    """Como _despachar, pero devuelve solo el código de salida (CLI y pruebas)."""
    return _despachar(argv, env).rc


def main(argv: list[str] | None = None) -> int:
    """preventa_run.py; códigos de salida de CONTRATOS.md §11.1."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        opciones, argv, errores = separar_globales(argv)
        env = Entorno.resolver(**opciones)
        env.errores_config += errores
    except Exception as exc:  # sin carpetas no hay núcleo ni bloque estado posible: se dice tal cual
        print(f"FALLO [{type(exc).__name__}] rc=4: no se puede preparar el entorno: {exc}")
        traceback.print_exc(file=sys.stdout)
        print("=== ESTADO PREVENTA ===\nestado: SIN_NUCLEO\nSIGUIENTE PASO OBLIGATORIO: parar; ejecutar entorno y "
              "avisar al comercial (montaje incompleto)\n=== FIN ESTADO ===")
        return 4
    if argv == ["entorno"]:  # EA-6: el diagnóstico no depende de que el núcleo cargue
        for e in env.errores_config:
            print(f"CONFIGURACIÓN NO VÁLIDA: {e}")
        rc = entorno_sin_nucleo(env)
        return rc or (2 if env.errores_config else 0)
    faltan = faltan_del_nucleo(env.p0)
    if faltan:  # EA-6: se nombra lo que falta ANTES de importar, en vez de un «cannot import name» opaco
        print(f"FALLO [IntegridadRota] rc=4: módulos del núcleo que faltan o no coinciden con el manifiesto: {', '.join(faltan)}")
        for e in env.p0:
            print(f"- {e}")
        print("=== ESTADO PREVENTA ===\nestado: SIN_NUCLEO\nSIGUIENTE PASO OBLIGATORIO: parar y avisar al comercial: "
              f"faltan o no coinciden {', '.join(faltan)}; ejecutar entorno (no importa el núcleo)\n=== FIN ESTADO ===")
        return 4
    try:
        _nucleo(env)
    except Exception as exc:  # sin núcleo no hay bloque estado posible: se dice tal cual
        print(f"FALLO [{type(exc).__name__}] rc=4: no se puede cargar el núcleo: {exc}")
        traceback.print_exc(file=sys.stdout)
        print("=== ESTADO PREVENTA ===\nestado: SIN_NUCLEO\nSIGUIENTE PASO OBLIGATORIO: parar; ejecutar entorno y "
              "avisar al comercial (montaje incompleto)\n=== FIN ESTADO ===")
        return 4
    return ejecutar(argv, env)


if __name__ == "__main__":
    sys.exit(main())
