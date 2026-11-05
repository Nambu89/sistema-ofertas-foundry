"""Restaurar el estado en un contenedor nuevo y dejar el relevo para otra conversación (CONTRATOS.md §2 y §4.10).

El contenedor de Code Interpreter caduca a los 20 minutos. Cuatro formas de volver, todas con ancla externa:

- `restaurar --zip <codigo>-Paquete.zip`: el último paquete descargado. Cada miembro se comprueba contra
  manifiesto_paquete.json y el estado contra el manifiesto. Los ficheros económicos (XLSX canónico, anexo
  XLSX y JSON) se recuperan BYTE A BYTE, comprobados además contra `artefactos`, así que `paquete` ya no
  los regenera (H7: el `--previo` de verificar_paquete deja de fallar por las fechas internas del XLSX).
- `restaurar --zip <codigo>-Relevo.zip`: el relevo que deja cada `decision` (H12). Lleva estado.json,
  relevo.json, los económicos que haya y el texto de las aclaraciones. Sirve para seguir tras una
  DEVUELTA (u otra decisión posterior al último paquete) sin volver a pegar líneas de decisión.
- `restaurar --estado estado.json --relevo relevo.json`: los dos JSON del relevo SUELTOS (EA-5: la API rechaza
  adjuntos `.zip`). Mismas comprobaciones que con el ZIP del relevo; los demás ficheros que lista relevo.json se
  toman si también se adjuntan, y los que faltan se declaran.
- `restaurar --estado … --manifiesto …`: la forma antigua (sin económicos; paquete los regenera).

Si algo no cuadra: IntegridadRota con todos los motivos y no se escribe nada.
"""
from __future__ import annotations

import collections
import io
import json
import pathlib
import re
import zipfile

from nucleo import esquema
from nucleo import estado as est_mod
from nucleo import hashes
from nucleo.errores import IntegridadRota

SUBDIRECTORIOS = ("entrada", "briefs", "consolidados", "salida", "fuentes")
MANIFIESTO_PAQUETE = "manifiesto_paquete.json"
MANIFIESTO_RELEVO = "relevo.json"
SCHEMA_RELEVO = "preventa-relevo/1"
ECONOMICOS = ("xlsx_estimacion", "anexo_xlsx", "anexo_json")
SUFIJO_ECONOMICO = {"xlsx_estimacion": "-Estimacion.xlsx", "anexo_xlsx": "-Anexo-Consumo.xlsx",
                    "anexo_json": "-Anexo-Consumo.json"}
MAX_MIEMBROS = 64
MAX_BYTES_MIEMBRO = 50 * 1024 * 1024
MAX_BYTES_ZIP = 100 * 1024 * 1024  # el ZIP adjunto, comprimido
MAX_BYTES_TOTAL = 200 * 1024 * 1024  # la suma de los miembros, descomprimidos (lo que se lee en memoria)
FECHA_ZIP = (1980, 1, 1, 0, 0, 0)  # fija: las entradas del ZIP no dependen del reloj del contenedor
_NOMBRE_ECONOMICO = re.compile(r"^OF-[A-Z0-9]{2,20}-[0-9]{3}-[A-Z]-(Estimacion\.xlsx|Anexo-Consumo\.(xlsx|json))$")
_NOMBRE_FUENTE = re.compile(r"^fuente-(F[0-9]{1,3})\.txt$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CODIGO = re.compile(r"^OF-[A-Z0-9]{2,20}-[0-9]{3}-[A-Z]$")
_CLAVES_RELEVO = {"schema", "codigo", "version", "estado", "hash_contenido", "estado_json_sha256", "decisiones",
                  "ultima_decision", "ficheros", "generado_ts"}


def _leer(ruta: pathlib.Path, que: str) -> bytes:
    try:
        return pathlib.Path(ruta).read_bytes()
    except OSError as e:
        raise IntegridadRota(f"No se puede leer {que} ({ruta}): {e}", [str(e)]) from e


def _json(datos: bytes, que: str) -> dict:
    try:
        obj = json.loads(datos.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise IntegridadRota(f"{que} no es JSON UTF-8 válido: {e}", [str(e)]) from e
    if not isinstance(obj, dict):
        raise IntegridadRota(f"{que} no es un objeto JSON", [])
    return obj


def _cuadrar(datos_estado: bytes, ancla: dict, que: str, errores: list[str]) -> dict:
    """SHA-256 del fichero, forma, hash guardado = recalculado = ancla, código y versión."""
    sha = hashes.sha256_bytes(datos_estado)
    if sha != ancla["estado_json_sha256"]:
        errores.append(f"SHA-256 de estado.json {sha} distinto de estado_json_sha256 del {que} "
                       f"{ancla['estado_json_sha256']}")
    est = _json(datos_estado, "estado.json")
    forma = est_mod.errores_estado(est)
    if forma:
        raise IntegridadRota("estado.json no valida contra su esquema", errores + forma)
    recalculado = hashes.hash_contenido(est)
    if recalculado != est["hash_contenido"]:
        errores.append(f"hash recalculado {recalculado} distinto del hash_contenido guardado {est['hash_contenido']}")
    if recalculado != ancla["hash_contenido"]:
        errores.append(f"hash recalculado {recalculado} distinto del hash_contenido del {que} {ancla['hash_contenido']}")
    for clave in ("codigo", "version", "estado"):
        if clave in ancla and est[clave] != ancla[clave]:
            errores.append(f"{clave} de estado.json ({est[clave]}) distinto del {que} ({ancla[clave]})")
    return est


def comprobar(datos_estado: bytes, manifiesto: dict) -> dict:
    """Comprobaciones del ancla (manifiesto del paquete); devuelve el estado. IntegridadRota con todos los motivos."""
    errores = [f"manifiesto: {e}" for e in esquema.validar(manifiesto, esquema.cargar("manifiesto_paquete"))]
    if errores:
        raise IntegridadRota("manifiesto_paquete.json no valida contra su esquema", errores)
    est = _cuadrar(datos_estado, manifiesto, "manifiesto", errores)
    if errores:
        raise IntegridadRota("El estado adjunto no cuadra con el ancla externa (manifiesto del último paquete)", errores)
    return est


def _errores_lista(ficheros: object) -> list[str]:
    """Lista [{nombre, sha256, bytes}] sin repetidos y sin rutas."""
    if not isinstance(ficheros, list) or not ficheros:
        return ["ficheros no es una lista con elementos"]
    e, vistos = [], set()
    for i, f in enumerate(ficheros):
        if not isinstance(f, dict) or set(f) != {"nombre", "sha256", "bytes"}:
            e.append(f"ficheros[{i}]: debe tener exactamente nombre, sha256 y bytes")
            continue
        n = f["nombre"]
        if not isinstance(n, str) or not n or "/" in n or "\\" in n or n.startswith(".") or n in vistos:
            e.append(f"ficheros[{i}]: nombre no válido o repetido: {n!r}")
        else:
            vistos.add(n)
        if not isinstance(f["sha256"], str) or not _HEX64.match(f["sha256"]):
            e.append(f"ficheros[{i}]: sha256 no válido")
        if not isinstance(f["bytes"], int) or isinstance(f["bytes"], bool) or f["bytes"] < 1:
            e.append(f"ficheros[{i}]: bytes no válido")
    return e


def _errores_forma_relevo(relevo: dict) -> list[str]:
    """relevo.json se valida en código (no tiene esquema propio en esquemas/)."""
    if set(relevo) != _CLAVES_RELEVO:
        return [f"claves: faltan {sorted(_CLAVES_RELEVO - set(relevo))}, sobran {sorted(set(relevo) - _CLAVES_RELEVO)}"]
    e = []
    if relevo["schema"] != SCHEMA_RELEVO:
        e.append(f"schema {relevo['schema']!r} distinto de {SCHEMA_RELEVO!r}")
    if not isinstance(relevo["codigo"], str) or not _CODIGO.match(relevo["codigo"]):
        e.append(f"codigo no válido: {relevo['codigo']!r}")
    if not isinstance(relevo["version"], str) or not re.fullmatch(r"[A-Z]", relevo["version"]):
        e.append(f"version no válida: {relevo['version']!r}")
    if relevo["estado"] not in est_mod.ESTADOS:
        e.append(f"estado no válido: {relevo['estado']!r}")
    for clave in ("hash_contenido", "estado_json_sha256"):
        if not isinstance(relevo[clave], str) or not _HEX64.match(relevo[clave]):
            e.append(f"{clave} no es un SHA-256 hexadecimal")
    n = relevo["decisiones"]
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        e.append("decisiones no es un entero ≥ 0")
    ult = relevo["ultima_decision"]
    if ult is not None and not (isinstance(ult, str) and re.fullmatch(r"D-[0-9]{3}", ult)):
        e.append(f"ultima_decision no válida: {ult!r}")
    if not isinstance(relevo["generado_ts"], str) or not 19 <= len(relevo["generado_ts"]) <= 40:
        e.append("generado_ts no válido")
    return e + _errores_lista(relevo["ficheros"])


def _miembros(ruta_zip: pathlib.Path) -> dict[str, bytes]:
    """Miembros de un ZIP plano: sin rutas, sin repetidos, con tope de número y de tamaño."""
    try:
        tam = pathlib.Path(ruta_zip).stat().st_size
    except OSError as e:
        raise IntegridadRota(f"No se puede leer ZIP adjunto ({ruta_zip}): {e}", [str(e)]) from e
    if tam > MAX_BYTES_ZIP:
        raise IntegridadRota("El ZIP adjunto es demasiado grande", [f"{tam} B (máximo {MAX_BYTES_ZIP} B)"])
    datos = _leer(ruta_zip, "ZIP adjunto")
    try:
        zf = zipfile.ZipFile(io.BytesIO(datos))
    except zipfile.BadZipFile as e:
        raise IntegridadRota(f"{pathlib.Path(ruta_zip).name} no es un ZIP válido: {e}", [str(e)]) from e
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_MIEMBROS:  # antes de recorrerlos: nada que dependa del número de miembros
            raise IntegridadRota("El ZIP adjunto no tiene la forma de un paquete o un relevo",
                                 [f"el ZIP tiene {len(infos)} miembros (máximo {MAX_MIEMBROS})"])
        errores = [f"miembro repetido: {n}" for n, k in sorted(collections.Counter(i.filename for i in infos).items())
                   if k > 1]
        for i in infos:
            n = i.filename
            if not n or "/" in n or "\\" in n or n.startswith(".") or i.is_dir():
                errores.append(f"miembro con ruta o nombre no admitido: {n!r}")
            if i.file_size > MAX_BYTES_MIEMBRO:
                errores.append(f"{n}: {i.file_size} B supera el máximo de {MAX_BYTES_MIEMBRO} B")
        total = sum(i.file_size for i in infos)
        if total > MAX_BYTES_TOTAL:
            errores.append(f"los miembros suman {total} B descomprimidos (máximo {MAX_BYTES_TOTAL} B)")
        if errores:
            raise IntegridadRota("El ZIP adjunto no tiene la forma de un paquete o un relevo", errores)
        try:
            return {i.filename: zf.read(i) for i in infos}
        except (zipfile.BadZipFile, OSError, RuntimeError) as e:  # CRC roto, cifrado o truncado
            raise IntegridadRota(f"No se puede leer el contenido del ZIP: {e}", [str(e)]) from e


def _comprobar_miembros(miembros: dict[str, bytes], ficheros: list[dict], propio: str) -> list[str]:
    """Exclusividad: el ZIP tiene exactamente lo listado más su manifiesto, y cada uno con su SHA-256 y bytes."""
    esperados = {f["nombre"] for f in ficheros} | {propio}
    e = [f"el ZIP trae {n}, que no está en {propio}" for n in sorted(set(miembros) - esperados)]
    e += [f"falta en el ZIP {n}, que lista {propio}" for n in sorted(esperados - set(miembros))]
    for f in ficheros:
        datos = miembros.get(f["nombre"])
        if datos is None:
            continue
        if len(datos) != f["bytes"] or hashes.sha256_bytes(datos) != f["sha256"]:
            e.append(f"{f['nombre']}: SHA-256 {hashes.sha256_bytes(datos)} ({len(datos)} B) distinto del de {propio} "
                     f"{f['sha256']} ({f['bytes']} B)")
    return e


def _economicos(est: dict, miembros: dict[str, bytes], obligatorios: bool) -> tuple[dict[str, bytes], list[str]]:
    """Ficheros económicos del ZIP comprobados contra `artefactos` (nombre, SHA-256 y bytes)."""
    salida, e = {}, []
    registrados = {}
    for clave in ECONOMICOS:
        art = (est.get("artefactos") or {}).get(clave)
        if not art:
            continue
        if not str(art["nombre"]).endswith(SUFIJO_ECONOMICO[clave]):
            e.append(f"artefactos.{clave}: {art['nombre']!r} no acaba en {SUFIJO_ECONOMICO[clave]}")
        elif art["nombre"] in registrados:
            e.append(f"artefactos.{clave}: {art['nombre']} ya está registrado en artefactos.{registrados[art['nombre']][0]}")
        else:
            registrados[art["nombre"]] = (clave, art)
    for n in sorted(set(miembros) - set(registrados)):
        if _NOMBRE_ECONOMICO.match(n):
            e.append(f"el ZIP trae {n}, que no está registrado en artefactos")
    for nombre, (clave, art) in registrados.items():
        if not _NOMBRE_ECONOMICO.match(nombre):
            e.append(f"artefactos.{clave}: nombre no admitido {nombre!r}")
            continue
        datos = miembros.get(nombre)
        if datos is None:
            if obligatorios:
                e.append(f"artefactos.{clave} registra {nombre}, que no está en el paquete")
            continue
        if len(datos) != art["bytes"] or hashes.sha256_bytes(datos) != art["sha256"]:
            e.append(f"{nombre}: SHA-256 {hashes.sha256_bytes(datos)} distinto de artefactos.{clave} {art['sha256']}")
            continue
        salida[nombre] = datos
    return salida, e


def _fuentes(est: dict, miembros: dict[str, bytes]) -> tuple[dict[str, bytes], list[str]]:
    """Texto de las aclaraciones (fuente-Fn.txt) comprobado contra su sha256_texto del estado."""
    registradas = {f["id"]: f for f in est["carga"]["fuentes"]}
    salida, e = {}, []
    for n, datos in sorted(miembros.items()):
        m = _NOMBRE_FUENTE.match(n)
        if not m:
            continue
        f = registradas.get(m.group(1))
        if f is None or f["tipo"] != "ACLARACION":
            e.append(f"{n}: no es una aclaración registrada en carga.fuentes")
            continue
        try:
            texto = datos.decode("utf-8")
        except UnicodeDecodeError as exc:
            e.append(f"{n}: no está en UTF-8 ({exc})")
            continue
        if hashes.sha256_texto(texto) != f["sha256_texto"]:
            e.append(f"{n}: el texto no es el registrado (sha256_texto distinto)")
            continue
        salida[f"{f['id']}.txt"] = datos
    return salida, e


def leer_zip(ruta_zip: pathlib.Path) -> tuple[str, dict, bytes, dict[str, bytes]]:
    """(tipo «paquete» o «relevo», estado, bytes de estado.json, {ruta relativa: bytes} a reponer).

    Comprueba TODO antes de devolver; IntegridadRota con todos los motivos si algo no cuadra."""
    miembros = _miembros(ruta_zip)
    es_paquete, es_relevo = MANIFIESTO_PAQUETE in miembros, MANIFIESTO_RELEVO in miembros
    if es_paquete == es_relevo:
        raise IntegridadRota("El ZIP no es un paquete ni un relevo de preventa",
                             [f"debe traer {MANIFIESTO_PAQUETE} (paquete) o {MANIFIESTO_RELEVO} (relevo), uno solo",
                              f"miembros: {sorted(miembros)[:20]}"])
    tipo, propio = ("paquete", MANIFIESTO_PAQUETE) if es_paquete else ("relevo", MANIFIESTO_RELEVO)
    ancla = _json(miembros[propio], propio)
    if es_paquete:
        errores = [f"manifiesto: {e}" for e in esquema.validar(ancla, esquema.cargar("manifiesto_paquete"))]
    else:
        errores = [f"relevo: {e}" for e in _errores_forma_relevo(ancla)]
    if errores:
        raise IntegridadRota(f"{propio} no tiene la forma esperada", errores)
    errores = _comprobar_miembros(miembros, ancla["ficheros"], propio)
    if "estado.json" not in miembros:
        raise IntegridadRota(f"El {tipo} no trae estado.json", errores)
    est = _cuadrar(miembros["estado.json"], ancla, propio, errores)
    if es_relevo:
        ultima = est["decisiones"][-1]["id"] if est["decisiones"] else None
        if ancla["decisiones"] != len(est["decisiones"]) or ancla["ultima_decision"] != ultima:
            errores.append(f"relevo: {ancla['decisiones']} decisiones (última {ancla['ultima_decision']}) y el estado "
                           f"tiene {len(est['decisiones'])} (última {ultima})")
    economicos, e_eco = _economicos(est, miembros, obligatorios=es_paquete)
    fuentes, e_fue = _fuentes(est, miembros)
    errores += e_eco + e_fue
    if errores:
        raise IntegridadRota(f"El {tipo} adjunto no cuadra con su ancla ({propio})", errores)
    extras = {f"salida/{n}": b for n, b in economicos.items()}
    extras.update({f"fuentes/{n}": b for n, b in fuentes.items()})
    return tipo, est, miembros["estado.json"], extras


def _escribir(raiz: pathlib.Path, est: dict, datos: bytes, extras: dict[str, bytes]) -> list[str]:
    """Escribe estado.json (bytes exactos, el último), briefs, consolidado y extras. No pisa nada distinto."""
    destino = est_mod.ruta_estado(raiz)
    if destino.exists() and destino.read_bytes() != datos:
        raise IntegridadRota("Ya existe un estado.json distinto en el contenedor: no se pisa",
                             [f"{destino} (SHA-256 {hashes.sha256_fichero(destino)})"])
    distintos = [f"{rel} (SHA-256 {hashes.sha256_fichero(raiz / rel)})" for rel, b in extras.items()
                 if (raiz / rel).exists() and (raiz / rel).read_bytes() != b]
    if distintos:
        raise IntegridadRota("Ya hay ficheros distintos en el contenedor: no se pisan", distintos)
    nuevo = not destino.exists()
    for sub in SUBDIRECTORIOS:
        (raiz / sub).mkdir(parents=True, exist_ok=True)
    # Ficheros derivados del estado: briefs, consolidado y cada lote (VERIF-9: el SIGUIENTE PASO manda leer
    # consolidados/<lote_id>.txt). Con estado nuevo se escriben todos; con el mismo estado ya presente, los que falten.
    derivados = {f"briefs/{b['brief_id']}.txt": b["texto"] for b in est["carga"]["briefs"]}
    cons = est["carga"].get("consolidado")
    if cons:
        derivados[f"consolidados/{cons['consolidado_id']}.txt"] = cons["texto"]
        derivados.update({f"consolidados/{x['lote_id']}.txt": x["texto"] for x in cons.get("lotes") or []})
    for rel, texto in derivados.items():
        if nuevo or not (raiz / rel).exists():
            est_mod.escribir_atomico(raiz / rel, (texto + "\n").encode("utf-8"))
    escritos = []
    for rel, b in extras.items():
        if not (raiz / rel).exists():
            est_mod.escribir_atomico(raiz / rel, b)
            escritos.append(rel)
    if nuevo:
        est_mod.escribir_atomico(destino, datos)
    return escritos


def restaurar(raiz: pathlib.Path, ruta_estado: pathlib.Path, ruta_manifiesto: pathlib.Path) -> dict:
    """Forma antigua: estado.json y manifiesto_paquete.json sueltos. Sin económicos (paquete los regenera)."""
    raiz = pathlib.Path(raiz)
    datos = _leer(ruta_estado, "estado.json adjunto")
    manifiesto = _json(_leer(ruta_manifiesto, "manifiesto_paquete.json adjunto"), "manifiesto_paquete.json")
    est = comprobar(datos, manifiesto)
    _escribir(raiz, est, datos, {})
    return est


def restaurar_zip(raiz: pathlib.Path, ruta_zip: pathlib.Path) -> tuple[dict, str, list[str]]:
    """Desde el ZIP del último paquete o del último relevo: (estado, tipo, ficheros repuestos byte a byte)."""
    raiz = pathlib.Path(raiz)
    tipo, est, datos, extras = leer_zip(ruta_zip)
    return est, tipo, _escribir(raiz, est, datos, extras)


def leer_sueltos(datos_estado: bytes, datos_relevo: bytes,
                 adjuntos: dict[str, bytes]) -> tuple[dict, dict[str, bytes], list[str]]:
    """EA-5: estado.json y relevo.json SUELTOS, sacados del Relevo.zip (la API rechaza adjuntos .zip, LES-G-090.9).

    `adjuntos` = los demás ficheros que lista relevo.json y se han adjuntado ({nombre: bytes}). Se comprueba lo mismo
    que con el ZIP del relevo; lo que relevo.json lista y no se ha adjuntado se omite y se declara (los económicos
    tampoco son obligatorios en el ZIP del relevo). Devuelve (estado, {ruta relativa: bytes} a reponer, omitidos).
    IntegridadRota con todos los motivos si algo no cuadra."""
    relevo = _json(datos_relevo, MANIFIESTO_RELEVO)
    errores = [f"relevo: {e}" for e in _errores_forma_relevo(relevo)]
    if errores:
        raise IntegridadRota(f"{MANIFIESTO_RELEVO} no tiene la forma esperada", errores)
    listados = [f["nombre"] for f in relevo["ficheros"]]
    if "estado.json" not in listados:
        raise IntegridadRota(f"{MANIFIESTO_RELEVO} no lista estado.json", [f"lista: {listados[:20]}"])
    ajenos = sorted(set(adjuntos) - set(listados) - {"estado.json"})
    if ajenos:
        raise IntegridadRota(f"Adjuntos que no lista {MANIFIESTO_RELEVO}", ajenos)
    miembros = {"estado.json": datos_estado, MANIFIESTO_RELEVO: datos_relevo}
    miembros.update((n, b) for n, b in adjuntos.items() if n != "estado.json")
    omitidos = [f"{n}: no adjuntado (lo lista {MANIFIESTO_RELEVO})" for n in listados if n not in miembros]
    presentes = [f for f in relevo["ficheros"] if f["nombre"] in miembros]
    errores = _comprobar_miembros(miembros, presentes, MANIFIESTO_RELEVO)
    est = _cuadrar(datos_estado, relevo, MANIFIESTO_RELEVO, errores)
    ultima = est["decisiones"][-1]["id"] if est["decisiones"] else None
    if relevo["decisiones"] != len(est["decisiones"]) or relevo["ultima_decision"] != ultima:
        errores.append(f"relevo: {relevo['decisiones']} decisiones (última {relevo['ultima_decision']}) y el estado "
                       f"tiene {len(est['decisiones'])} (última {ultima})")
    economicos, e_eco = _economicos(est, miembros, obligatorios=False)
    fuentes, e_fue = _fuentes(est, miembros)
    errores += e_eco + e_fue
    if errores:
        raise IntegridadRota(f"El estado y el relevo adjuntos no cuadran ({MANIFIESTO_RELEVO})", errores)
    extras = {f"salida/{n}": b for n, b in economicos.items()}
    extras.update({f"fuentes/{n}": b for n, b in fuentes.items()})
    return est, extras, omitidos


def restaurar_relevo(raiz: pathlib.Path, ruta_estado: pathlib.Path, ruta_relevo: pathlib.Path,
                     buscar) -> tuple[dict, list[str], list[str]]:
    """EA-5: restaura desde estado.json y relevo.json sueltos. `buscar(nombre)` devuelve los adjuntos con ese nombre
    (el montaje lo sabe la CLI): cada fichero que lista relevo.json se toma si hay exactamente uno.
    Devuelve (estado, ficheros repuestos byte a byte, omitidos)."""
    raiz = pathlib.Path(raiz)
    datos = _leer(ruta_estado, "estado.json adjunto")
    datos_relevo = _leer(ruta_relevo, f"{MANIFIESTO_RELEVO} adjunto")
    relevo = _json(datos_relevo, MANIFIESTO_RELEVO)
    nombres = [f.get("nombre") for f in relevo.get("ficheros") or [] if isinstance(f, dict)] \
        if not _errores_forma_relevo(relevo) else []
    adjuntos, errores = {}, []
    for n in nombres:
        if n == "estado.json":
            continue
        cand = list(buscar(n))
        if len(cand) > 1:
            errores.append(f"{n}: adjuntado {len(cand)} veces")
        elif cand:
            tam = pathlib.Path(cand[0]).stat().st_size
            if tam > MAX_BYTES_MIEMBRO:
                errores.append(f"{n}: {tam} B supera el máximo de {MAX_BYTES_MIEMBRO} B")
            else:
                adjuntos[n] = _leer(cand[0], f"{n} adjunto")
    if errores:
        raise IntegridadRota("Los adjuntos del relevo no se pueden leer sin ambigüedad", errores)
    est, extras, omitidos = leer_sueltos(datos, datos_relevo, adjuntos)
    return est, _escribir(raiz, est, datos, extras), omitidos


SECCION_CANALES = "## Canales e integraciones"


def migrar_sin_canales(est: dict) -> list[str]:
    """REV-3: un estado de antes de VERIF-2 restaurado en EN_ANALISIS sin `canales_integraciones` no tenía salida
    (enrutar exige el campo y en EN_ANALISIS no se admite suficiencia ni asumir). Lo devuelve a
    INFORMACION_INSUFICIENTE (la transición de restaurar admite cualquier estado de destino) para que el comercial
    responda la pregunta a/b/c/d. El brief vigente sin esa sección se retira, porque se compuso sin el canal y
    reenviarlo lo perdería otra vez; con él, lo que dependía de los requisitos (§5.3). Muta `est` en sitio.
    Devuelve lo que ha hecho ([] si no hacía falta: otro estado o el campo ya tiene entradas)."""
    if est.get("estado") != "EN_ANALISIS":
        return []
    campos = ((est["carga"].get("requisitos") or {}).get("campos")) or {}
    if (campos.get("canales_integraciones") or {}).get("entradas"):
        return []
    hecho = ["EN_ANALISIS -> INFORMACION_INSUFICIENTE: el estado restaurado no tiene canales_integraciones "
             "(es de antes de VERIF-2) y sin él no se puede enrutar"]
    vigente = est_mod.brief_id_vigente(est)
    retirados = [b["brief_id"] for b in est["carga"]["briefs"]
                 if b.get("brief_id") == vigente and SECCION_CANALES not in (b.get("texto") or "")]
    if retirados:
        est["carga"]["briefs"] = [b for b in est["carga"]["briefs"] if b.get("brief_id") not in retirados]
        anulados = est_mod.invalidar_desde(est, "requisitos")
        hecho.append(f"brief retirado (sin «{SECCION_CANALES}»): {', '.join(retirados)}; anulado: "
                     f"{', '.join(anulados) or 'nada'}")
    est["estado"] = "INFORMACION_INSUFICIENTE"
    return hecho


def nombre_relevo(codigo: str) -> str:
    return f"{codigo}-Relevo.zip"


def escribir_relevo(est: dict, raiz: pathlib.Path) -> dict:
    """Compone y publica el relevo del estado YA GUARDADO (componer_relevo + publicar_relevo)."""
    return publicar_relevo(componer_relevo(est, raiz), raiz)


def publicar_relevo(relevo: dict, raiz: pathlib.Path) -> dict:
    """Publica el ZIP compuesto si su estado.json es, byte a byte, el guardado en el contenedor."""
    raiz = pathlib.Path(raiz)
    if _leer(est_mod.ruta_estado(raiz), "estado.json del contenedor") != relevo["estado_json"]:
        raise IntegridadRota("El relevo debe llevar el estado guardado y el estado.json del contenedor es distinto", [])
    est_mod.escribir_atomico(relevo["ruta"], relevo["zip"])  # temporal + chmod 644 + os.replace
    return {k: v for k, v in relevo.items() if k not in ("zip", "estado_json")}


def componer_relevo(est: dict, raiz: pathlib.Path) -> dict:
    """salida/<codigo>-Relevo.zip EN MEMORIA, sin escribir nada: estado.json (los bytes que guardará
    estado.guardar), relevo.json, los económicos que estén en el contenedor y coincidan con `artefactos`, y el
    texto de las aclaraciones (H12). Exige est["hash_contenido"] ya recalculado.

    Devuelve {"nombre", "ruta", "sha256", "bytes", "incluidos", "omitidos", "zip", "estado_json"}. Lo omitido se
    declara, no se calla."""
    raiz = pathlib.Path(raiz)
    if est.get("hash_contenido") != hashes.hash_contenido(est):
        raise IntegridadRota("El relevo exige el hash_contenido recalculado antes de componerlo", [])
    datos = est_mod.serializar(est)
    miembros: dict[str, bytes] = {"estado.json": datos}
    omitidos: list[str] = []
    for clave in ECONOMICOS:
        art = (est.get("artefactos") or {}).get(clave)
        if not art:
            continue
        nombre, ruta = art["nombre"], raiz / "salida" / art["nombre"]
        if not _NOMBRE_ECONOMICO.match(nombre):
            omitidos.append(f"{nombre}: nombre no admitido en artefactos.{clave}")
        elif not ruta.is_file():
            omitidos.append(f"{nombre}: no está en este contenedor")
        else:
            b = ruta.read_bytes()
            if len(b) != art["bytes"] or hashes.sha256_bytes(b) != art["sha256"]:
                omitidos.append(f"{nombre}: no coincide con artefactos.{clave}")
            else:
                miembros[nombre] = b
    proc = raiz / "procedencia" / "procedencia_a2a.json"
    if proc.is_file():  # I1.4 · P1: la procedencia de B viaja con el relevo (el hosted la fusiona al restaurar)
        miembros["procedencia_a2a.json"] = proc.read_bytes()
    for f in est["carga"]["fuentes"]:
        if f["tipo"] != "ACLARACION":
            continue
        ruta = raiz / "fuentes" / f"{f['id']}.txt"
        b = ruta.read_bytes() if ruta.is_file() else None
        try:
            ok = b is not None and hashes.sha256_texto(b.decode("utf-8")) == f["sha256_texto"]
        except UnicodeDecodeError:
            ok = False
        if ok:
            miembros[f"fuente-{f['id']}.txt"] = b
        else:
            omitidos.append(f"aclaración {f['id']} ({f['nombre']}): su texto no está en este contenedor o no cuadra")
    relevo = {"schema": SCHEMA_RELEVO, "codigo": est["codigo"], "version": est["version"], "estado": est["estado"],
              "hash_contenido": hashes.hash_contenido(est), "estado_json_sha256": hashes.sha256_bytes(datos),
              "decisiones": len(est["decisiones"]),
              "ultima_decision": est["decisiones"][-1]["id"] if est["decisiones"] else None,
              "ficheros": [{"nombre": n, "sha256": hashes.sha256_bytes(b), "bytes": len(b)} for n, b in miembros.items()],
              "generado_ts": est_mod.ahora_ts()}
    errores = _errores_forma_relevo(relevo)
    if errores:
        raise IntegridadRota("relevo.json no tiene la forma esperada (no se escribe)", errores)
    contenido = {"estado.json": datos,
                 MANIFIESTO_RELEVO: (json.dumps(relevo, ensure_ascii=False, indent=2) + "\n").encode("utf-8")}
    contenido.update((n, b) for n, b in miembros.items() if n != "estado.json")
    salida = raiz / "salida"
    salida.mkdir(parents=True, exist_ok=True)
    destino = salida / nombre_relevo(est["codigo"])
    buf = io.BytesIO()  # se compone en memoria y se publica en último lugar: nada puede fallar después
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for n, b in contenido.items():
            info = zipfile.ZipInfo(n, date_time=FECHA_ZIP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, b)
    datos_zip = buf.getvalue()
    return {"nombre": destino.name, "ruta": destino, "sha256": hashes.sha256_bytes(datos_zip),
            "bytes": len(datos_zip), "incluidos": list(contenido), "omitidos": omitidos, "zip": datos_zip,
            "estado_json": datos}
