"""Despliegue idempotente de I0/I1 en proyecto-ejemplo (agentes y A2A). Nunca borra nada.

Por defecto despliega I1 (--incremento I1); --incremento I0 reproduce el despliegue de I0.

Pasos (se pueden lanzar por separado con --pasos):
  ficheros     sube los ficheros del coordinador (purpose=assistants) y escribe manifiesto.json
  expertos     crea o versiona preventa-experto-azure y preventa-verificador y activa A2A (PATCH)
  card         comprueba con GET el agent card v1.0 de los dos agentes expuestos (debe dar 200)
  conexiones   crea por ARM las conexiones RemoteA2A a2a-experto-azure y a2a-verificador
  coordinador  crea o versiona preventa-coordinador (code_interpreter + dos tools a2a v1.0)
  releer       relee cada agente con GET y compara instrucciones, tools y file_ids
  prueba_ci    (opcional) agente desechable preventa-prueba-ci: coordinador sin tools a2a
Las pruebas de Responses y los roles están en pruebas_b3.py y roles_b3.py.
Todo lo que llama a Azure se ejecuta fuera del sandbox de la herramienta.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
import pathlib
import re
import sys
import zipfile
from typing import Any

from agentes import definiciones as D
from lib import evidencia, hashes
from lib.azure_auth import ErrorAutenticacion, ErrorAz
from lib.config import ErrorConfig, validar as validar_config
from lib.foundry import ClienteFoundry, ErrorFoundry

RAIZ = pathlib.Path(__file__).resolve().parent
# Raíz de Proyectos: PREVENTA_PROYECTOS o ~/Proyectos (como sandbox/preventa_run.raiz_proyectos); la ruta del puesto de
# Windows solo como último recurso, si existe.
_WINDOWS = pathlib.Path("C:/Users/usuario/Proyectos")
PROYECTOS = (pathlib.Path((os.environ.get("PREVENTA_PROYECTOS") or "").strip() or pathlib.Path.home() / "Proyectos"))
PROYECTOS = PROYECTOS if PROYECTOS.is_dir() or not _WINDOWS.is_dir() or (os.environ.get("PREVENTA_PROYECTOS") or "").strip() else _WINDOWS  # fijada: se respeta
CANON = PROYECTOS / "_templates" / "estimacion"
MANIFIESTO = RAIZ / "manifiesto.json"
ESTADO = RAIZ / "agentes" / "despliegue.json"
EVID = RAIZ / "pruebas" / "I0" / "B3"
EVID_I1 = RAIZ / "pruebas" / "I1" / "DESPLIEGUE"
MONTAJE_I1 = RAIZ / "salidas" / "montaje_I1"  # copias con el nombre de subida (§1.2); lo crea este script
# instance_identity del coordinador (si cambia, se pierde el rol: PARA). Sale de config/entorno.local.json.
def _identidad_coordinador() -> str | None:
    try:
        from lib.config import ErrorConfig as _E, cargar as _cargar
        return _cargar().get("identidad_coordinador_principal_id")
    except _E:
        return None


IDENTIDAD_COORDINADOR = _identidad_coordinador()
INCREMENTO = "I1"
PASOS = ["ficheros", "expertos", "card", "conexiones", "coordinador", "releer"]
FICHEROS_INCOMPLETO = "ficheros_incompleto"  # ARR-2: marca de un paso «ficheros» cortado a mitad


class FalloDespliegue(RuntimeError):
    """Fallo explícito de un paso (P-6): se registra y el script termina con rc != 0."""


def ahora() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def leer_json(p: pathlib.Path, defecto: Any) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else defecto


def escribir_json(p: pathlib.Path, obj: Any) -> None:
    """Escribe JSON con la red anti-JWT/Bearer de lib/evidencia.py (C4): si el contenido tiene
    forma de token, lanza EvidenciaConSecreto y no escribe nada. Nunca a través de un enlace simbólico
    (el fichero o una carpeta de su ruta): así una escritura en la carpeta de evidencias no puede acabar
    fuera de ella (Revisión, integración I1.1). La carpeta de --evidencias ya se exige dentro del repositorio."""
    ruta = pathlib.Path(p).absolute()
    # is_junction (Python 3.12+) cubre las junctions de Windows, que is_symlink no ve (Revisión 3).
    enlaces = [str(x) for x in (ruta, *ruta.parents)
               if x.is_symlink() or getattr(x, "is_junction", lambda: False)()]
    if enlaces:
        raise FalloDespliegue(f"Escritura a través de un enlace simbólico rechazada: {p} ({enlaces[0]})")
    evidencia.escribir_json(ruta, obj)


def ruta_fuente() -> pathlib.Path:
    """MontserratVF.ttf: C:/Windows/Fonts o, si no está, la instalación por usuario; en macOS, ~/Library/Fonts y
    /Library/Fonts (donde la misma fuente variable se instala como «Montserrat[wght].ttf», mismos bytes)."""
    mac = [pathlib.Path(d) / n for d in (pathlib.Path.home() / "Library/Fonts", "/Library/Fonts")
           for n in ("MontserratVF.ttf", "Montserrat[wght].ttf")]
    for p in (pathlib.Path("C:/Windows/Fonts/MontserratVF.ttf"),
              pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts/MontserratVF.ttf", *mac):
        if p.is_file():
            return p
    raise FalloDespliegue("No se encuentra MontserratVF.ttf ni en C:/Windows/Fonts, ni en LOCALAPPDATA, ni en "
                          "~/Library/Fonts o /Library/Fonts")


def fuente_zip() -> pathlib.Path:
    """ZIP determinista (fecha fija, permisos 644) con MontserratVF.ttf: /openai/v1/files no
    admite la extensión .ttf (HTTP 400 «Invalid extension ttf», 07-10-2026)."""
    destino = RAIZ / "sandbox" / "MontserratVF.zip"
    info = zipfile.ZipInfo("MontserratVF.ttf", date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    datos = ruta_fuente().read_bytes()   # antes de abrir el destino: sin fuente no se trunca el ZIP versionado
    try:   # misma fuente: el ZIP versionado no se reescribe (otro zlib comprimiría distinto y cambiaría lo que se sube)
        with zipfile.ZipFile(destino) as z:
            if z.namelist() == ["MontserratVF.ttf"] and z.read("MontserratVF.ttf") == datos:
                return destino
    except (OSError, zipfile.BadZipFile):
        pass
    with zipfile.ZipFile(destino, "w") as z:
        z.writestr(info, datos)
    return destino


def ruta_tarifa(reg: list) -> tuple[pathlib.Path, str]:
    """salidas/rate-card.json de B2 si su SHA-256 cuadra con el .sha256; si no, la de _config (provisional)."""
    snap = RAIZ / "salidas" / "rate-card.json"
    sha_f = RAIZ / "salidas" / "rate-card.json.sha256"
    if snap.is_file() and sha_f.is_file():
        esperado = sha_f.read_text(encoding="utf-8").split()[0]
        real = hashes.sha256_fichero(snap)
        if real == esperado:
            return snap, f"skill rate-card v4 (B2), sha256 {real}"
        reg.append({"aviso": f"salidas/rate-card.json no cuadra con su .sha256 ({real} != {esperado})"})
    reg.append({"aviso": "Se usa _config/rate-card.json como tarifa PROVISIONAL"})
    return PROYECTOS / "_config" / "rate-card.json", "PROVISIONAL: _config/rate-card.json"


def ficheros_coordinador(reg: list) -> list[tuple[str, pathlib.Path, str]]:
    """(nombre montado, ruta local, origen) de cada fichero que se monta en el coordinador."""
    tarifa, origen_tarifa = ruta_tarifa(reg)
    return [
        ("preventa_run.py", RAIZ / "sandbox" / "preventa_run.py", "sandbox I0"),
        ("generar_estimacion.py", CANON / "generar_estimacion.py", "canónico sin modificar"),
        ("OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx", CANON / "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx",
         "canónico sin modificar"),
        ("ejemplo.json", CANON / "ejemplo.json", "canónico sin modificar"),
        ("rate-card.json", tarifa, origen_tarifa),
        ("MontserratVF.zip", fuente_zip(), f"fuente corporativa {ruta_fuente()} en ZIP determinista "
                                            "(la API de ficheros rechaza .ttf)"),
    ]


def ficheros_coordinador_i1(reg: list) -> list[tuple[str, pathlib.Path, str]]:
    """Ficheros de I1 (CONTRATOS.md §1.2): CLI, un nucleo_<modulo>.py por módulo (nucleo_init.py = __init__), un esquema_<n>.json
    por esquema, catálogo, tarifa, generador y plantilla canónicos sin modificar y la fuente."""
    import shutil
    tarifa, origen_tarifa = ruta_tarifa(reg)
    if "PROVISIONAL" in origen_tarifa:
        raise FalloDespliegue("I1 exige la instantánea salidas/rate-card.json de la skill v4 (tarifa/leer_rate_card.py)")
    catalogo = RAIZ / "sandbox" / "datos" / "catalogo_componentes.json"
    fuente_cat = RAIZ / "catalogo" / "catalogo_componentes.json"
    if hashes.sha256_fichero(catalogo) != hashes.sha256_fichero(fuente_cat):
        raise FalloDespliegue("sandbox/datos/catalogo_componentes.json no es byte a byte catalogo/catalogo_componentes.json")
    # I1.7 (decisión 1 del comercial): la instantánea de precios del despliegue va montada junto al catálogo; antes, generarla
    # y comprobarla (python -m catalogo.instantanea_precios y --comprobar --fecha-paquete): pruebas/I17/DESPLEGAR-Y-PROBAR.md
    precios = RAIZ / "sandbox" / "datos" / "precios_instantanea.json"
    fuente_precios = RAIZ / "catalogo" / "precios_instantanea.json"
    if not precios.is_file() or hashes.sha256_fichero(precios) != hashes.sha256_fichero(fuente_precios):
        raise FalloDespliegue("sandbox/datos/precios_instantanea.json no existe o no es byte a byte "
                              "catalogo/precios_instantanea.json")
    from catalogo import instantanea_precios as IP  # diferido: solo I1
    fallos_precios = IP.comprobar(json.loads(IP.CATALOGO.read_text(encoding="utf-8")),
                                  dt.datetime.now(dt.timezone.utc).date())
    if fallos_precios:  # nunca se despliega con una instantánea que no vale hoy (fallar cerrado)
        raise FalloDespliegue("La instantánea de precios no vale hoy: " + "; ".join(fallos_precios[:5]))
    if MONTAJE_I1.exists():
        shutil.rmtree(MONTAJE_I1)  # solo la carpeta de copias que crea este mismo script
    MONTAJE_I1.mkdir(parents=True)
    salida: list[tuple[str, pathlib.Path, str]] = [("preventa_run.py", RAIZ / "sandbox" / "preventa_run.py", "sandbox I1")]
    for mod in sorted((RAIZ / "sandbox" / "nucleo").glob("*.py")):
        destino = MONTAJE_I1 / ("nucleo_init.py" if mod.name == "__init__.py" else f"nucleo_{mod.name}")
        shutil.copyfile(mod, destino)
        salida.append((destino.name, destino, f"sandbox/nucleo/{mod.name}"))
    for esq in sorted((RAIZ / "esquemas").glob("*.json")):
        destino = MONTAJE_I1 / f"esquema_{esq.name}"
        shutil.copyfile(esq, destino)
        salida.append((destino.name, destino, f"esquemas/{esq.name}"))
    salida += [
        ("catalogo_componentes.json", catalogo, "catálogo derivado (catalogo/derivar.py)"),
        ("precios_instantanea.json", precios, "instantánea de precios del despliegue (catalogo/instantanea_precios.py)"),
        ("rate-card.json", tarifa, origen_tarifa),
        ("generar_estimacion.py", CANON / "generar_estimacion.py", "canónico sin modificar"),
        ("OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx", CANON / "OF-PLANTILLA-ESTIMACION-MCLOUD.xlsx", "canónico sin modificar"),
        ("MontserratVF.zip", fuente_zip(), "fuente corporativa en ZIP determinista (la API rechaza .ttf)"),
    ]
    dobles = [n for n, _, _ in salida if "__" in n]
    if dobles:  # el montaje colapsa «__» en «_»: el nombre montado no sería el del manifiesto
        raise FalloDespliegue(f"Nombres de subida con guiones bajos repetidos: {dobles}")
    return salida


def diferencias(enviado: Any, recibido: Any, ruta: str = "") -> list[str]:
    """Lo enviado debe estar contenido en lo recibido (el servidor puede añadir campos)."""
    if isinstance(enviado, dict):
        if not isinstance(recibido, dict):
            return [f"{ruta or '/'}: se esperaba objeto y llega {type(recibido).__name__}"]
        out: list[str] = []
        for k, v in enviado.items():
            if k not in recibido:
                out.append(f"{ruta}/{k}: falta en lo leído")
            else:
                out += diferencias(v, recibido[k], f"{ruta}/{k}")
        return out
    if isinstance(enviado, list):
        if not isinstance(recibido, list) or len(enviado) != len(recibido):
            n = len(recibido) if isinstance(recibido, list) else "-"
            return [f"{ruta}: lista de {len(enviado)} elementos y se leen {n}"]
        out = []
        for i, (a, b) in enumerate(zip(enviado, recibido)):
            out += diferencias(a, b, f"{ruta}[{i}]")
        return out
    return [] if enviado == recibido else [f"{ruta}: enviado {str(enviado)[:80]!r} / leído {str(recibido)[:80]!r}"]


def _subir_si_cambia(c: ClienteFoundry, nombre: str, ruta: pathlib.Path, previo: dict | None,
                     reg: list) -> dict:
    """Reutiliza el file_id si el SHA-256 coincide y el fichero sigue existiendo; si no, sube."""
    if ruta.name != nombre:
        raise FalloDespliegue(f"El fichero {ruta} se montaría como {ruta.name}, no como {nombre}")
    sha, size = hashes.sha256_fichero(ruta), ruta.stat().st_size
    if previo and previo.get("sha256") == sha and previo.get("file_id"):
        try:
            info = c.obtener_fichero(previo["file_id"])
            if info.get("filename") == nombre and info.get("bytes") == size:
                reg.append({"fichero": nombre, "accion": "reutilizado", "file_id": previo["file_id"]})
                return {"sha256": sha, "bytes": size, "file_id": previo["file_id"]}
        except ErrorFoundry as e:
            if e.estado != 404:
                raise
    r = c.subir_fichero(ruta)
    if previo and previo.get("file_id"):
        # nunca se borra: el id sustituido queda anotado para retirarlo a mano (ROLLBACK-I0.md)
        reg.append({"fichero": nombre, "huerfano": previo["file_id"]})
    reg.append({"fichero": nombre, "accion": "subido", "file_id": r.get("id"), "bytes": r.get("bytes"),
                "status": r.get("status"), "purpose": r.get("purpose")})
    if r.get("bytes") not in (None, size):
        raise FalloDespliegue(f"{nombre}: subidos {r.get('bytes')} B y el fichero tiene {size} B")
    return {"sha256": sha, "bytes": size, "file_id": r["id"],
            "sustituye_a": previo.get("file_id") if previo else None}


def paso_ficheros(c: ClienteFoundry, est: dict, reg: list) -> None:
    """Sube (o reutiliza) los ficheros del coordinador y después manifiesto.json con sus SHA-256."""
    # ARR-2 (I1.2): el mapa ya no se vacía antes de subir. Cada entrada se sustituye en cuanto su fichero
    # queda subido o reutilizado; si algo falla a mitad (p. ej. ErrorAutenticacion), las que faltan conservan
    # su file_id anterior, el siguiente despliegue las reutiliza o anota su huérfano, y nada se pierde.
    previos = copy.deepcopy(est.get("ficheros", {}))
    nuevos: dict[str, dict] = {}
    lista = ficheros_coordinador_i1(reg) if INCREMENTO == "I1" else ficheros_coordinador(reg)
    for nombre, ruta, origen in lista:
        nuevos[nombre] = _subir_si_cambia(c, nombre, ruta, previos.get(nombre), reg) | {"origen": origen}
        viejo = nuevos[nombre].pop("sustituye_a", None)
        if nuevos[nombre] == previos.get(nombre):
            continue  # reutilizado sin cambios: el estado no se toca
        huerfanos = est.setdefault("ficheros_huerfanos", [])
        if viejo and viejo != nuevos[nombre]["file_id"] and viejo not in huerfanos:
            huerfanos.append(viejo)
        # mezcla de ids nuevos y anteriores: file_ids() se niega a montarla hasta que el paso termine
        est[FICHEROS_INCOMPLETO] = True
        # se guarda en cuanto se sube: si un fichero posterior falla, no se vuelven a subir los previos
        est.setdefault("ficheros", {})[nombre] = nuevos[nombre]
        escribir_json(ESTADO, est)
    huerfanos = est.setdefault("ficheros_huerfanos", [])
    for nombre in sorted(set(previos) - set(nuevos)):  # ya no se montan: huérfanos, no se borran
        viejo = (previos.get(nombre) or {}).get("file_id")
        if viejo and viejo not in huerfanos:
            huerfanos.append(viejo)
            reg.append({"fichero": nombre, "huerfano": viejo, "motivo": f"no se monta en {INCREMENTO}"})
    man = {"schema": "preventa-manifiesto/1", "proyecto": c.cfg["proyecto"],
           "nota": f"SHA-256 de cada fichero montado en preventa-coordinador ({INCREMENTO}). No se incluye a sí mismo.",
           "ficheros": dict(sorted(nuevos.items()))}
    escribir_json(MANIFIESTO, man)
    if est.get("ficheros") != nuevos:
        est[FICHEROS_INCOMPLETO] = True  # el manifiesto subido aún describe el mapa anterior
        est["ficheros"] = nuevos
    manifiesto = _subir_si_cambia(c, "manifiesto.json", MANIFIESTO, est.get("manifiesto"), reg)
    viejo = manifiesto.pop("sustituye_a", None)
    est["manifiesto"] = manifiesto
    if viejo and viejo != manifiesto["file_id"] and viejo not in huerfanos:
        huerfanos.append(viejo)
    est.pop(FICHEROS_INCOMPLETO, None)


def file_ids(est: dict) -> list[str]:
    if "ficheros" not in est or "manifiesto" not in est:
        raise FalloDespliegue("Faltan los ficheros: ejecuta antes el paso «ficheros»")
    if est.get(FICHEROS_INCOMPLETO):
        raise FalloDespliegue("El último paso «ficheros» no terminó (ids nuevos y anteriores mezclados): "
                              "vuelve a ejecutarlo antes de montar el coordinador")
    return [f["file_id"] for f in est["ficheros"].values()] + [est["manifiesto"]["file_id"]]


def _obtener_o_none(c: ClienteFoundry, nombre: str) -> dict | None:
    try:
        return c.obtener_agente(nombre)
    except ErrorFoundry as e:
        if e.estado == 404:
            return None
        raise


def _version_de(r: dict) -> dict:
    """La respuesta de crear puede ser el agente (versions.latest) o directamente la versión."""
    return r.get("versions", {}).get("latest") or r


def asegurar_agente(c: ClienteFoundry, nombre: str, definicion: dict, descripcion: str,
                    reg: list) -> dict:
    """Crea el agente o una versión nueva solo si la definición vigente no contiene la deseada."""
    ag = _obtener_o_none(c, nombre)
    if ag is not None:
        vigente = ag["versions"]["latest"]
        difs = diferencias(definicion, vigente.get("definition", {}))
        if not difs:
            reg.append({"agente": nombre, "accion": "sin cambios", "version": vigente.get("version")})
            return vigente
        reg.append({"agente": nombre, "accion": "nueva versión", "diferencias": difs[:20]})
        v = _version_de(c.crear_version_agente(nombre, definicion, descripcion))
    else:
        v = _version_de(c.crear_agente(nombre, definicion, descripcion))
        reg.append({"agente": nombre, "accion": "creado"})
    reg[-1].update({"version": v.get("version"), "modelo": definicion.get("model"),
                    "instance_identity": v.get("instance_identity")})
    return v


# Un 400 solo activa el respaldo si el cuerpo nombra el modelo o dice que un modelo o una
# herramienta no están soportados. Cualquier otro 400 (esquema, instrucciones...) sube tal cual (P1).
_NO_SOPORTADO = re.compile(r"not supported|unsupported|does not support|no se admite|no admite|"
                           r"no es compatible|no está soportad", re.I)
_SUJETO = re.compile(r"\b(tools?|models?|herramientas?|modelos?)\b", re.I)
# Con el nombre del modelo en el cuerpo, además tiene que haber un verbo de rechazo: un 400 de
# validación que solo repite el modelo en el texto no cuenta (revisión independiente del cierre).
_RECHAZO = re.compile(_NO_SOPORTADO.pattern + r"|not available|not found|does not exist|"
                      r"invalid model|no existe|no disponible|deploymentnotfound|model_not_found", re.I)


_CERCA = 120  # caracteres máximos entre el sujeto y el verbo de rechazo (misma frase)


def _juntos(a: str, b: str, cuerpo: str) -> bool:
    """True si los patrones a y b aparecen a menos de _CERCA caracteres, en cualquier orden."""
    return bool(re.search(f"(?:{a}).{{0,{_CERCA}}}(?:{b})|(?:{b}).{{0,{_CERCA}}}(?:{a})", cuerpo, re.I))


def rechaza_modelo(e: ErrorFoundry, modelo: str) -> bool:
    """True solo si la API rechaza el modelo: HTTP 400 cuyo cuerpo nombra el modelo junto a un
    verbo de rechazo, o dice, en la misma frase, que un modelo o una herramienta no están
    soportados. Nunca ante un 400 genérico, aunque mencione el modelo en otra parte."""
    if e.estado != 400:
        return False
    cuerpo = e.cuerpo or ""
    if modelo and _juntos(re.escape(modelo), _RECHAZO.pattern, cuerpo):
        return True
    return _juntos(_SUJETO.pattern, _NO_SOPORTADO.pattern, cuerpo)


def modelos_validos(cfg: dict, modelos: dict) -> None:
    """Valida los modelos efectivos con la misma regla de lib/config.py (el verificador usa un
    modelo distinto del de los demás) y exige que el respaldo nunca sea el del verificador."""
    prueba = copy.deepcopy(cfg)
    for clave in ("experto_azure", "verificador", "coordinador"):
        prueba["agentes"][clave]["modelo"] = modelos[clave]
    try:
        validar_config(prueba)
    except ErrorConfig as e:
        raise FalloDespliegue(f"Modelos no válidos: {e}") from None
    resp = modelos.get("respaldo")
    if resp and resp == modelos["verificador"]:
        raise FalloDespliegue(f"El respaldo {resp} es el modelo del verificador: rompería la "
                              "independencia de la revisión. Elige otro o no uses --respaldo.")


def asegurar_con_respaldo(c: ClienteFoundry, nombre: str, construir, modelo: str,
                          respaldo: str | None, descripcion: str, reg: list, clave: str,
                          modelos: dict) -> tuple[dict, str]:
    """Intenta con el modelo principal. Solo si la API rechaza ese modelo (rechaza_modelo) y hay
    respaldo, comprueba con la configuración que el cambio no rompe la independencia del
    verificador, anota el error literal y prueba UNA vez con el respaldo (P1)."""
    try:
        return asegurar_agente(c, nombre, construir(modelo), descripcion, reg), modelo
    except ErrorFoundry as e:
        if not respaldo or modelo == respaldo or not rechaza_modelo(e, modelo):
            raise
        modelos_validos(c.cfg, {**modelos, clave: respaldo, "respaldo": None})
        reg.append({"agente": nombre, "intento": f"1/3 con {modelo}", "error_literal": e.cuerpo[:1500],
                    "hipotesis": f"La API rechaza {modelo} (o una herramienta con él); se prueba {respaldo}",
                    "aviso": "RESPALDO USADO: revisar antes de dar el despliegue por bueno"})
    return asegurar_agente(c, nombre, construir(respaldo), descripcion, reg), respaldo


def exponer_si_falta(c: ClienteFoundry, nombre: str, card: dict, reg: list) -> None:
    """PATCH de agent_card + protocolos responses y a2a, solo si el agente no los tiene ya."""
    ag = c.obtener_agente(nombre)
    conf = (ag.get("agent_endpoint") or {}).get("protocol_configuration") or {}
    if "a2a" in conf and "responses" in conf and not diferencias(card, ag.get("agent_card") or {}):
        reg.append({"agente": nombre, "a2a": "ya activado"})
        return
    r = c.exponer_a2a(nombre, card)
    ep = r.get("agent_endpoint") or {}
    reg.append({"agente": nombre, "a2a": "PATCH", "protocols": ep.get("protocols"),
                "protocol_configuration": ep.get("protocol_configuration"),
                "agent_card": r.get("agent_card")})


def paso_expertos(c: ClienteFoundry, est: dict, reg: list, modelos: dict) -> None:
    """Experto Azure y verificador: crear/versionar y activar A2A."""
    resp = modelos.get("respaldo")
    for clave, construir, card, desc in (
            ("experto_azure", constructor("experto_azure"), D.CARD_EXPERTO, f"Experto Azure de preventa ({INCREMENTO})"),
            ("verificador", constructor("verificador"), D.CARD_VERIFICADOR, f"Verificador independiente ({INCREMENTO})")):
        nombre = c.cfg["agentes"][clave]["nombre"]
        v, modelo = asegurar_con_respaldo(c, nombre, construir, modelos[clave], resp, desc, reg,
                                          clave, modelos)
        exponer_si_falta(c, nombre, card, reg)
        est.setdefault("agentes", {})[clave] = {"nombre": nombre, "version": v.get("version"),
                                                "modelo": modelo}


def paso_card(c: ClienteFoundry, est: dict, reg: list) -> None:
    """GET del agent card v1.0 (Learn: …/endpoint/protocols/a2a/agentCard/v1.0); exige 200."""
    for clave in ("experto_azure", "verificador"):
        nombre = c.cfg["agentes"][clave]["nombre"]
        url = f"{c.ep_proyecto}/agents/{nombre}/endpoint/protocols/a2a/agentCard/v1.0"
        card = c._peticion("GET", url, c._tok_datos)
        escribir_json(EVID / f"agentcard_{nombre}.json", card)
        if not isinstance(card, dict):
            raise FalloDespliegue(f"El agent card de {nombre} no es un objeto JSON")
        # La prueba real (07-10-2026) da protocolVersion dentro de supportedInterfaces, no arriba.
        versiones = sorted({i.get("protocolVersion") for i in card.get("supportedInterfaces", [])
                            if i.get("protocolBinding") == "JSONRPC"} | {card.get("protocolVersion")} - {None})
        reg.append({"agente": nombre, "agent_card_v1": "HTTP 200", "versiones_jsonrpc": versiones,
                    "claves": sorted(card)})
        if "1.0" not in versiones:
            raise FalloDespliegue(f"El agent card de {nombre} no anuncia JSONRPC 1.0: {versiones}")


def paso_conexiones(c: ClienteFoundry, est: dict, reg: list) -> None:
    """Conexiones RemoteA2A (AgenticIdentityToken, sin ruta de agent card). No pisa nada."""
    for clave in ("experto_azure", "verificador"):
        con = c.cfg["conexiones"][clave]
        agente = c.cfg["agentes"][clave]["nombre"]
        deseado = c.propiedades_remote_a2a(agente)
        actual = c.obtener_conexion(con)
        if actual is None:
            actual = c.put_conexion(con, deseado)
            reg.append({"conexion": con, "accion": "creada", "id": actual.get("id")})
        else:
            pr = actual.get("properties", {})
            malos = [k for k in ("category", "authType", "target") if pr.get(k) != deseado[k]]
            if malos:
                raise FalloDespliegue(f"La conexión {con} ya existe con otros valores en {malos}: "
                                      "no se pisa; revisar a mano")
            reg.append({"conexion": con, "accion": "ya existía", "id": actual.get("id")})
        pr = actual.get("properties", {})
        reg[-1].update({k: pr.get(k) for k in ("category", "authType", "target", "audience")})
        est.setdefault("conexiones", {})[clave] = {"nombre": con, "id": actual["id"]}


def ids_conexiones(est: dict) -> list[str]:
    try:
        return [est["conexiones"][k]["id"] for k in ("experto_azure", "verificador")]
    except KeyError:
        raise FalloDespliegue("Faltan las conexiones: ejecuta antes el paso «conexiones»") from None


def constructor(clave: str):
    """Definición del agente según el incremento (I1: instrucciones I1, text.format y OpenAPI)."""
    if INCREMENTO == "I1":
        return {"experto_azure": D.def_experto_azure_i1, "verificador": D.def_verificador_i1}[clave]
    return {"experto_azure": D.def_experto_azure, "verificador": D.def_verificador}[clave]


def def_coordinador_actual(est: dict, modelo: str) -> dict:
    construir = D.def_coordinador_i1 if INCREMENTO == "I1" else D.def_coordinador
    return construir(modelo, file_ids(est), ids_conexiones(est))


def principal_de(v: dict) -> str | None:
    ii = v.get("instance_identity")
    return ii.get("principal_id") if isinstance(ii, dict) else ii


def paso_coordinador(c: ClienteFoundry, est: dict, reg: list, modelos: dict) -> None:
    """preventa-coordinador con code_interpreter (file_ids en la definición) y dos tools a2a v1.0."""
    nombre = c.cfg["agentes"]["coordinador"]["nombre"]
    if not IDENTIDAD_COORDINADOR:
        raise FalloDespliegue("PARA: falta identidad_coordinador_principal_id en config/entorno.local.json")
    if INCREMENTO == "I1":  # antes de publicar nada: si el agente no existe o su identidad no es la del rol, PARA
        actual = _obtener_o_none(c, nombre)
        previa = principal_de(((actual or {}).get("versions") or {}).get("latest") or {})
        if previa != IDENTIDAD_COORDINADOR:
            raise FalloDespliegue(f"PARA antes de publicar: la instance_identity vigente del coordinador es {previa} "
                                  f"y debe ser {IDENTIDAD_COORDINADOR} (crear o recrear el agente perdería el rol)")
    v, modelo = asegurar_con_respaldo(c, nombre, lambda m: def_coordinador_actual(est, m),
                                      modelos["coordinador"], modelos.get("respaldo"),
                                      f"Coordinador de preventa ({INCREMENTO})", reg, "coordinador", modelos)
    if principal_de(v) != IDENTIDAD_COORDINADOR:
        raise FalloDespliegue(f"PARA: la instance_identity del coordinador es {principal_de(v)} y debe ser "
                              f"{IDENTIDAD_COORDINADOR} (perdería el rol Foundry Agent Consumer)")
    est.setdefault("agentes", {})["coordinador"] = {
        "nombre": nombre, "version": v.get("version"), "modelo": modelo,
        "instance_identity": v.get("instance_identity")}


def paso_releer(c: ClienteFoundry, est: dict, reg: list) -> None:
    """Relee cada agente con GET y compara instrucciones, tools y file_ids con lo enviado."""
    fallos = []
    for clave in ("experto_azure", "verificador", "coordinador"):
        a = est.get("agentes", {}).get(clave)
        if not a:
            raise FalloDespliegue(f"No hay registro de despliegue de {clave}")
        if clave == "coordinador":
            deseada = def_coordinador_actual(est, a["modelo"])
        else:
            deseada = constructor(clave)(a["modelo"])
        leido = c.obtener_agente(a["nombre"])
        v = leido["versions"]["latest"]
        defi = v.get("definition", {})
        escribir_json(EVID / f"releido_{a['nombre']}.json", leido)
        comp = {"agente": a["nombre"], "version_leida": v.get("version"), "version_desplegada": a["version"],
                "modelo": defi.get("model"),
                "instrucciones_iguales": defi.get("instructions") == deseada["instructions"],
                "tipos_tools_enviados": [t["type"] for t in deseada["tools"]],
                "tipos_tools_leidos": [t.get("type") for t in defi.get("tools", [])],
                "diferencias": diferencias(deseada, defi),
                "protocolos": (leido.get("agent_endpoint") or {}).get("protocols")}
        if clave == "coordinador":
            ci = [t for t in defi.get("tools", []) if t.get("type") == "code_interpreter"]
            leidos = (ci[0].get("container") or {}).get("file_ids", []) if ci else []
            comp["file_ids_iguales"] = sorted(leidos) == sorted(file_ids(est))
            comp["file_ids_leidos"] = leidos
            comp["a2a_leidos"] = [{k: t.get(k) for k in ("a2a_version", "project_connection_id")}
                                  for t in defi.get("tools", []) if t.get("type") == "a2a"]
            comp["instance_identity"] = v.get("instance_identity")
            comp["identidad_conservada"] = principal_de(v) == IDENTIDAD_COORDINADOR
        else:
            if "text" in deseada:  # contenido (el servidor puede añadir campos)
                comp["text_format_igual"] = not diferencias(deseada["text"]["format"],
                                                            (defi.get("text") or {}).get("format"))
        reg.append(comp)
        if comp["diferencias"] or str(comp["version_leida"]) != str(a["version"]) or \
                comp.get("file_ids_iguales") is False or comp.get("identidad_conservada") is False or \
                comp.get("text_format_igual") is False:
            fallos.append(a["nombre"])
    if fallos:
        raise FalloDespliegue(f"La relectura no coincide con lo enviado en: {fallos}")


AGENTE_PRUEBA_CI = "preventa-prueba-ci"


def paso_prueba_ci(c: ClienteFoundry, est: dict, reg: list, modelos: dict) -> None:
    """Agente desechable igual que el coordinador pero SIN tools a2a: aísla el Code Interpreter
    (file_ids en la definición) mientras A2A espera los roles. Se puede borrar (prefijo preventa-prueba-)."""
    defi = (D.def_coordinador_i1 if INCREMENTO == "I1" else D.def_coordinador)(modelos["coordinador"], file_ids(est), [])
    v = asegurar_agente(c, AGENTE_PRUEBA_CI, defi, f"Prueba {INCREMENTO} desechable: Code Interpreter sin A2A", reg)
    est.setdefault("agentes_prueba", {})[AGENTE_PRUEBA_CI] = {"version": v.get("version"),
                                                               "modelo": modelos["coordinador"]}


def main(argv: list[str] | None = None) -> int:
    """Ejecuta los pasos pedidos en orden, guarda el estado tras cada uno y la evidencia al final."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pasos", default=",".join(PASOS), help=f"lista separada por comas de {PASOS}")
    ap.add_argument("--modelo-experto", help="sustituye el modelo del experto Azure")
    ap.add_argument("--modelo-verificador", help="sustituye el modelo del verificador")
    ap.add_argument("--modelo-coordinador", help="sustituye el modelo del coordinador")
    ap.add_argument("--respaldo", default=None,
                    help="modelo si la API rechaza el principal (sin valor por defecto; nunca el "
                         "del verificador)")
    ap.add_argument("--incremento", choices=["I0", "I1"], default="I1")
    ap.add_argument("--evidencias", default=None,
                    help="carpeta de evidencias (por defecto pruebas/I1/DESPLIEGUE en I1); I1.1 usa pruebas/I11/DESPLIEGUE")
    a = ap.parse_args(argv)
    global INCREMENTO, EVID
    INCREMENTO = a.incremento
    if INCREMENTO == "I1":
        EVID = EVID_I1
    if a.evidencias:
        EVID = (RAIZ / a.evidencias).resolve()
        if RAIZ.resolve() not in EVID.parents:
            ap.error("--evidencias tiene que estar dentro del repositorio")
    pasos = [p.strip() for p in a.pasos.split(",") if p.strip()]
    desconocidos = [p for p in pasos if p not in PASOS + ["prueba_ci"]]
    if desconocidos:
        ap.error(f"pasos desconocidos: {desconocidos}")
    c = ClienteFoundry()
    ag = c.cfg["agentes"]
    modelos = {"experto_azure": a.modelo_experto or ag["experto_azure"]["modelo"],
               "verificador": a.modelo_verificador or ag["verificador"]["modelo"],
               "coordinador": a.modelo_coordinador or ag["coordinador"]["modelo"],
               "respaldo": a.respaldo}
    try:
        modelos_validos(c.cfg, modelos)
    except FalloDespliegue as e:
        ap.error(str(e))
    est = leer_json(ESTADO, {})
    reg: list = [{"inicio": ahora(), "pasos": pasos, "modelos": modelos}]
    rc = 1  # solo pasa a 0 si todos los pasos terminan; cualquier otra excepción deja rc=1
    try:
        for p in pasos:
            reg.append({"paso": p})
            print(f"== {p}", flush=True)
            if p == "ficheros":
                paso_ficheros(c, est, reg)
            elif p == "expertos":
                paso_expertos(c, est, reg, modelos)
            elif p == "card":
                paso_card(c, est, reg)
            elif p == "conexiones":
                paso_conexiones(c, est, reg)
            elif p == "coordinador":
                paso_coordinador(c, est, reg, modelos)
            elif p == "prueba_ci":
                paso_prueba_ci(c, est, reg, modelos)
            elif p == "releer":
                paso_releer(c, est, reg)
            escribir_json(ESTADO, est)
        rc = 0
    except (FalloDespliegue, ErrorFoundry) as e:
        reg.append({"FALLO": type(e).__name__, "detalle": str(e)[:3000]})
    except (ErrorAutenticacion, ErrorAz) as e:
        # ARR-2: az pide MFA o falla a mitad. Se registra y el estado se guarda tal como quedó: cada
        # entrada ya sustituida es real y las demás conservan su file_id anterior.
        reg.append({"FALLO": type(e).__name__, "detalle": evidencia.enmascarar_texto(str(e))[:3000],
                    "remedio": f"az login --tenant {c.cfg['tenant_id']} y vuelve a ejecutar"})
        print(f"FALLO de autenticación: az login --tenant {c.cfg['tenant_id']}", file=sys.stderr)
    finally:
        escribir_json(ESTADO, est)
        reg.append({"reintentos_http": [vars(i) for i in c.registro], "fin": ahora()})
        destino = EVID / f"desplegar_{ahora()}.json"
        escribir_json(destino, reg)
        print(json.dumps(reg, ensure_ascii=False, indent=1)[-6000:])
        print(f"Evidencia: {destino} rc={rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
