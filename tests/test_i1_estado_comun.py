"""Utilidades comunes de las pruebas de la máquina de estados (papel BA). Sin red.

Importa `sandbox/nucleo` del repositorio. `errores` y `esquema` (de otro constructor) se sustituyen
por un doble que sigue CONTRATOS.md §4.1-4.2 SOLO si todavía no existen (ModuleNotFoundError de ese
módulo exacto); `SUSTITUTOS` lo declara. Los módulos de B, C y D se sustituyen siempre por dobles
dentro de cada prueba (`instalar_dobles`, con monkeypatch), para probar la CLI por sus firmas.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import importlib
import importlib.util
import json
import pathlib
import re
import sys
import types
import unicodedata
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
SANDBOX = RAIZ / "sandbox"
ESQUEMAS = RAIZ / "esquemas"
EJEMPLOS = ESQUEMAS / "ejemplos"
TRANSCRIPCION = RAIZ / "datos_prueba" / "transcripcion_sintetica_I1.txt"
TARIFA = RAIZ / "tests" / "insumos" / "rate-card.sintetica.json"
SUSTITUTOS: list[str] = []

for _p in (SANDBOX, ESQUEMAS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _doble_errores() -> types.ModuleType:
    m = types.ModuleType("nucleo.errores")

    class ErrorPreventa(Exception):
        codigo_salida = 5

        def __init__(self, mensaje: str, errores: list[str] | None = None):
            super().__init__(mensaje)
            self.mensaje, self.errores = mensaje, list(errores or [])

    m.ErrorPreventa = ErrorPreventa
    for nombre, rc in (("EntradaInvalida", 2), ("ReglaIncumplida", 1), ("Bloqueo", 1),
                       ("TransicionNoPermitida", 3), ("IntegridadRota", 4)):
        setattr(m, nombre, type(nombre, (ErrorPreventa,), {"codigo_salida": rc}))
    return m


def _doble_esquema() -> types.ModuleType:
    import comprobar_esquemas  # referencia ejecutable de §12
    m = types.ModuleType("nucleo.esquema")
    m.cargar = lambda nombre, dir_esquemas=None: json.loads(
        (pathlib.Path(dir_esquemas or ESQUEMAS) / f"{nombre}.json").read_text(encoding="utf-8"))
    m.validar = lambda inst, esq: comprobar_esquemas.validar(inst, esq, esq)

    def exigir(inst, nombre, como=None):
        errores = m.validar(inst, m.cargar(nombre))
        if errores:
            raise (como or sys.modules["nucleo.errores"].ReglaIncumplida)(f"{nombre} no valida", errores)
    m.exigir = exigir
    return m


def _asegurar(nombre: str, fabrica) -> None:
    completo = f"nucleo.{nombre}"
    try:
        importlib.import_module(completo)
    except ModuleNotFoundError as e:
        if e.name != completo:
            raise
        modulo = fabrica()
        sys.modules[completo] = modulo
        setattr(importlib.import_module("nucleo"), nombre, modulo)
        SUSTITUTOS.append(nombre)


_asegurar("errores", _doble_errores)
_asegurar("esquema", _doble_esquema)

from nucleo import brief, decision, errores, estado, experto, hashes, restaurar, suficiencia, verificacion  # noqa: E402


def ejemplo(nombre: str) -> dict:
    return json.loads((EJEMPLOS / f"{nombre}.json").read_text(encoding="utf-8"))


def plegar(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


def marcadores_doble(texto: str) -> list[str]:
    """§0, palabra completa (mismo criterio que textos_cliente.marcadores de C)."""
    h = re.findall(r"\b(?:TBD|TODO|XXX|PLACEHOLDER)\b", texto)
    h += re.findall(r"(?<!\w)(?:pendientes?|por definir|lorem)(?!\w)", plegar(texto))
    return h + re.findall(r"<[^<>\n]{1,60}>", texto)


def _doble_textos() -> types.ModuleType:
    m = types.ModuleType("nucleo.textos_cliente")
    m.marcadores = marcadores_doble

    def componer(est, catalogo, tarifa):
        t = ejemplo("textos_cliente")
        t["codigo"] = t["portada"]["codigo"] = est["codigo"]
        hechos = {k: est["carga"][k] for k in ("alta", "requisitos", "respuestas_expertos", "verificacion", "anexo_consumo")}
        hechos["estimacion_resumen"] = est["carga"]["estimacion"]["resumen"]
        t["hash_hechos"] = hashes.hash_json(hechos)
        return t
    m.componer = componer
    m.barrer = lambda texto, perfiles: []
    return m


def _doble_estimacion() -> types.ModuleType:
    m = types.ModuleType("nucleo.estimacion")
    m.PRECIO, m.ERRORES, m.LLAMADAS = None, [], []

    @dataclasses.dataclass(frozen=True)
    class RutasGenerador:
        generador: pathlib.Path
        plantilla: pathlib.Path
        rate_card: pathlib.Path
        base_tmp: pathlib.Path

    @dataclasses.dataclass(frozen=True)
    class ResultadoEstimacion:
        resumen: dict
        stop: bool
        ruta_xlsx: pathlib.Path
        xlsx_sha256: str

    m.RutasGenerador, m.ResultadoEstimacion = RutasGenerador, ResultadoEstimacion
    # Integrador I1.7: experto.duracion_gantt (regla de ciclo de vida del modelo) usa las reglas puras del Gantt del real
    real = _estimacion_real_privada()
    m.horas_tarea, m.semanas_fase = real.horas_tarea, real.semanas_fase
    m.cargar_tarifa = lambda ruta: json.loads(pathlib.Path(ruta).read_text(encoding="utf-8"))["tarifa"]
    m.perfiles = lambda tarifa: [p["nombre"] for p in tarifa["perfiles"]]
    # REV-1 (I1.4): `estimar` ya no admite --entrada; la CLI compone siempre con componer_entrada
    m.hitos_tarifa = lambda tarifa: copy.deepcopy(ejemplo("estimacion_entrada")["hitos"])

    def componer_entrada(est, hitos, hoy=None, ajuste=None):
        ent = ejemplo("estimacion_entrada")
        ent["codigo"], ent["fecha"] = est["codigo"], (hoy or estado.hoy()).isoformat()
        if ajuste is not None:
            ent["ajuste_comercial_eur"], ent["ajuste_comercial_motivo"] = float(ajuste[0]), ajuste[1]
        return ent, []
    m.componer_entrada = componer_entrada

    def leer_ajuste(d):
        mm = re.match(r"^importe_eur=(-?[0-9]+\.[0-9]{2}); motivo=(.{10,400})$", str(d.get("comentarios") or "").strip(), re.S)
        if not mm:
            raise ValueError("comentarios sin la forma «importe_eur=-1500.00; motivo=…» (§10)")
        return mm.group(1), mm.group(2).strip()
    m.leer_ajuste = leer_ajuste

    def estimar(est, entrada, tarifa, rutas, dir_salida, ajuste_decision_id):
        m.LLAMADAS.append({"ajuste": ajuste_decision_id, "codigo": entrada.get("codigo")})
        if m.ERRORES:
            raise errores.ReglaIncumplida("Entrada de estimación inválida", list(m.ERRORES))
        resumen = copy.deepcopy(ejemplo("estado")["carga"]["estimacion"]["resumen"])
        if m.PRECIO:
            resumen["precio_cerrado_eur"] = m.PRECIO
        ruta = pathlib.Path(dir_salida) / f"{est['codigo']}-Estimacion.xlsx"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"xlsx de prueba " + est["codigo"].encode())
        sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
        est["carga"]["estimacion"] = {"entrada": copy.deepcopy(entrada), "resumen": resumen, "ajuste": None}
        est["artefactos"]["xlsx_estimacion"] = {"nombre": ruta.name, "sha256": sha, "bytes": ruta.stat().st_size}
        return ResultadoEstimacion(resumen, float(resumen["precio_cerrado_eur"]) > 100000, ruta, sha)
    m.estimar = estimar
    return m


_ANEXO_PRIVADO: list[types.ModuleType] = []
_ESTIMACION_PRIVADA: list[types.ModuleType] = []


def _estimacion_real_privada() -> types.ModuleType:
    """Integrador I1.7: copia del `nucleo.estimacion` real con OTRO nombre (como _anexo_real_privado), solo para sus
    reglas puras del Gantt; no se registra en `sys.modules` ni en el paquete `nucleo`. Solo importa `nucleo.errores`."""
    if not _ESTIMACION_PRIVADA:
        spec = importlib.util.spec_from_file_location("_estimacion_real_para_el_doble", SANDBOX / "nucleo" / "estimacion.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # @dataclass busca el módulo por su nombre; el nombre privado no choca con nucleo.*
        spec.loader.exec_module(mod)
        _ESTIMACION_PRIVADA.append(mod)
    return _ESTIMACION_PRIVADA[0]


def _anexo_real_privado() -> types.ModuleType | None:
    """ARR15-4 (I1.6): copia del `nucleo.anexo_consumo` real cargada con OTRO nombre, sin registrarla en el paquete
    `nucleo` ni en `sys.modules["nucleo.anexo_consumo"]`: si se registrara, cambiaría qué módulo ven las demás pruebas,
    que es justo lo que dependía del orden. Solo importa `nucleo.errores`. None si el módulo aún no existe."""
    if not _ANEXO_PRIVADO:
        ruta = SANDBOX / "nucleo" / "anexo_consumo.py"
        if not ruta.is_file():
            return None
        spec = importlib.util.spec_from_file_location("_anexo_consumo_real_para_el_doble", ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ANEXO_PRIVADO.append(mod)
    return _ANEXO_PRIVADO[0]


def _doble_anexo() -> types.ModuleType:
    m = types.ModuleType("nucleo.anexo_consumo")
    # ARR15-4: las reglas puras del real (errores_cobertura, facturables_azure, motivo_sin_precios, sus constantes y lo
    # que se añada) para que `experto.validar_respuesta`, que importa anexo_consumo en diferido, valide igual lanzada la
    # prueba sola o en batería. Solo `aplicar` y `cargar_catalogo` son dobles.
    real = _anexo_real_privado()
    for nombre, valor in (vars(real).items() if real is not None else ()):
        if not nombre.startswith("_") and not isinstance(valor, types.ModuleType):
            setattr(m, nombre, valor)
    m.cargar_catalogo = lambda ruta: json.loads(pathlib.Path(ruta).read_text(encoding="utf-8"))

    def aplicar(est, catalogo, dir_salida):
        anexo = ejemplo("anexo_consumo")
        anexo["codigo"] = est["codigo"]
        est["carga"]["anexo_consumo"] = anexo
        for clave, ext in (("anexo_xlsx", "xlsx"), ("anexo_json", "json")):
            ruta = pathlib.Path(dir_salida) / f"{est['codigo']}-Anexo-Consumo.{ext}"
            ruta.parent.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(b"anexo " + ext.encode())
            est["artefactos"][clave] = {"nombre": ruta.name, "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(),
                                        "bytes": ruta.stat().st_size}
        return anexo
    m.aplicar = aplicar
    return m


def _doble_paquete() -> types.ModuleType:
    m = types.ModuleType("nucleo.paquete")
    m.FALLAR = False
    m.nombres_zip = lambda c: [f"{c}-Estimacion.xlsx", f"{c}-Anexo-Consumo.xlsx", f"{c}-Anexo-Consumo.json",
                               f"{c}-Revision.pptx", f"{c}-Nota-Revision.docx", "estado.json",
                               "manifiesto_paquete.json", "mensaje_revisor.txt", "mensaje_aprobador.txt"]

    def construir(est, raiz, catalogo, tarifa, rutas, catalogo_sha256=None, transcripcion=None):
        if m.FALLAR:
            raise errores.ReglaIncumplida("Revalidación del paquete fallida", ["P11 de prueba"])
        assert est["estado"] in estado.REVISION, est["estado"]
        salida = pathlib.Path(raiz) / "salida"
        salida.mkdir(parents=True, exist_ok=True)
        ficheros = []
        for n in m.nombres_zip(est["codigo"]):
            if n == "manifiesto_paquete.json":
                continue
            ruta = salida / n
            if n == "estado.json":
                ruta.write_bytes((pathlib.Path(raiz) / "estado.json").read_bytes())
            elif not ruta.exists():
                ruta.write_bytes(f"fichero {n}".encode())
            ficheros.append({"nombre": n, "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(), "bytes": ruta.stat().st_size})
        man = {"schema": "preventa-manifiesto-paquete/1", "codigo": est["codigo"], "version": est["version"],
               "estado": est["estado"], "hash_contenido": hashes.hash_contenido(est),
               "estado_json_sha256": next(f["sha256"] for f in ficheros if f["nombre"] == "estado.json"),
               "ficheros": ficheros, "montados": {k: "a" * 64 for k in ("rate_card_sha256", "generador_sha256",
                                                                       "plantilla_sha256", "catalogo_sha256")},
               "generado_ts": "2026-10-08T10:00:00+02:00"}
        (salida / "manifiesto_paquete.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(salida / f"{est['codigo']}-Paquete.zip", "w") as z:
            for n in m.nombres_zip(est["codigo"]):
                z.write(salida / n, n)
        return man
    m.construir = construir
    return m


def instalar_dobles(monkeypatch) -> dict[str, types.ModuleType]:
    """Dobles de B, C y D solo durante la prueba (sys.modules se restaura al terminar)."""
    dobles = {"textos_cliente": _doble_textos(), "estimacion": _doble_estimacion(),
              "anexo_consumo": _doble_anexo(), "paquete": _doble_paquete()}
    for nombre, mod in dobles.items():
        monkeypatch.setitem(sys.modules, f"nucleo.{nombre}", mod)
    return dobles


SENSIBLES = ["Kelvara Ensayos Industriales", "Kelvara", "Marta Olmedo", "Iker Salaverri", "Nuria Castells",
             "Zaragoza", "Tarragona"]
ADJUNTO = "transcripcion_sintetica_I1.txt"


class Mundo:
    """Directorio de datos sintético como /mnt/data, con la CLI ejecutada en proceso."""

    def __init__(self, tmp_path: pathlib.Path, monkeypatch):
        import io
        self._io = io
        self.datos = tmp_path / "data"
        self.datos.mkdir()
        (self.datos / f"assistant-F1x-{ADJUNTO}").write_bytes(TRANSCRIPCION.read_bytes())
        self.catalogo = self.datos / "catalogo_componentes.json"
        self.catalogo.write_bytes((EJEMPLOS / "catalogo_componentes.json").read_bytes())
        # Integrador I1.7: la instantánea de precios del catálogo montado, explícita (el doble de anexo_consumo no recuerda
        # la ruta del catálogo y, sin PREVENTA_PRECIOS, el resultado dependería del orden de las pruebas)
        self.precios = self.datos / "precios_instantanea.json"
        self.precios.write_bytes((EJEMPLOS / "precios_instantanea.json").read_bytes())
        self.raiz = self.datos / "preventa"
        for var, valor in (("PREVENTA_DATOS", self.datos), ("PREVENTA_RAIZ", self.raiz), ("PREVENTA_PRECIOS", self.precios),
                           ("PREVENTA_CATALOGO", self.catalogo), ("PREVENTA_RATE_CARD", TARIFA),
                           ("PREVENTA_GENERADOR", TARIFA), ("PREVENTA_PLANTILLA", TARIFA)):
            monkeypatch.setenv(var, str(valor))
        self.dobles = instalar_dobles(monkeypatch)
        import preventa_run
        self.cli = preventa_run

    def usar_catalogo_real(self) -> None:
        """Integrador I1.7: monta el catálogo REAL del sandbox con SU instantánea de precios (la del ejemplo no lo cubre)."""
        self.catalogo.write_bytes((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_bytes())
        self.precios.write_bytes((RAIZ / "sandbox" / "datos" / "precios_instantanea.json").read_bytes())

    def run(self, *args: str) -> tuple[int, str]:
        buf = self._io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(buf):
            rc = self.cli.main(list(args))
        out = buf.getvalue()
        assert "=== ESTADO PREVENTA ===" in out and "SIGUIENTE PASO OBLIGATORIO:" in out, out
        return rc, out

    def estado(self) -> dict:
        return json.loads((self.raiz / "estado.json").read_text(encoding="utf-8"))

    def entrada(self, nombre: str, contenido) -> str:
        ruta = self.raiz / "entrada" / nombre
        ruta.parent.mkdir(parents=True, exist_ok=True)
        texto = contenido if isinstance(contenido, str) else json.dumps(contenido, ensure_ascii=False, indent=2)
        ruta.write_bytes(texto.encode("utf-8"))  # bytes exactos, sin traducir saltos de línea
        return f"entrada/{nombre}"

    def hash(self) -> str:
        return hashes.hash_contenido(self.estado())

    # Pasos del caso OF-KELVARA-001-A
    def iniciar(self) -> tuple[int, str]:
        args = ["iniciar", "--cliente", "Kelvara Ensayos Industriales, S.A.", "--codigo-cliente", "KELVARA",
                "--seqof", "001", "--titulo", "Asistente de consulta técnica con IA sobre informes de ensayo",
                "--transcripcion", ADJUNTO, "--nda-confirmado"]
        for s in SENSIBLES:
            args += ["--sensible", s]
        return self.run(*args)

    def requisitos_modelo(self) -> dict:
        req = ejemplo("requisitos")
        for c in ("volumetria", "identidad_acl_origen"):
            req["campos"][c] = {"estado": "FALTA", "entradas": []}
        return req

    def hasta_analisis(self) -> None:
        assert self.iniciar()[0] == 0
        assert self.run("suficiencia", "--requisitos", self.entrada("requisitos.json", self.requisitos_modelo()))[0] == 1
        req = ejemplo("requisitos")["campos"]
        for c in ("volumetria", "identidad_acl_origen"):
            assert self.run("asumir", "--campo", c, "--valor", req[c]["entradas"][0]["valor"])[0] == 0

    def hasta_verificacion(self) -> None:
        self.hasta_analisis()
        assert self.run("enrutar")[0] == 0
        r = self.entrada("respuesta_experto_AZ_R1.json", ejemplo("respuesta_experto"))
        assert self.run("registrar-experto", "--experto", "azure", "--respuesta", r)[0] == 0
        assert self.run("consolidar")[0] == 0

    def hasta_verificada(self) -> None:
        self.hasta_verificacion()
        r = self.entrada("respuesta_verificador_R1.json", ejemplo("respuesta_verificador"))
        assert self.run("registrar-verificacion", "--respuesta", r)[0] == 0

    def entrada_estimacion(self) -> str:
        ent = ejemplo("estimacion_entrada")
        ent["codigo"] = self.estado()["codigo"]
        ent["fecha"] = estado.hoy().isoformat()
        return self.entrada("estimacion_entrada.json", ent)

    def hasta_lista(self) -> None:
        self.hasta_verificada()
        assert self.run("anexo-consumo")[0] == 0
        assert self.run("estimar")[0] == 0
        assert self.run("paquete")[0] == 0

    def linea(self, revisor: str, tipo: str, comentarios: str, fecha: str | None = None, h: str | None = None) -> str:
        return f"DECISION | {revisor} | {tipo} | {fecha or estado.hoy().isoformat()} | {h or self.hash()} | {comentarios}"
