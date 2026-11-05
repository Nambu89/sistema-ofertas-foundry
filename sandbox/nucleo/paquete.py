"""Paquete revisable: PPTX, nota, mensajes, copia de estado.json, manifiesto y ZIP (CONTRATOS.md §4.17 y §8).

`construir` revalida el contenido antes de escribir nada, nunca regenera el XLSX canónico salvo que
falte (tras `restaurar`) y no cambia `hash_contenido`. Las puertas del sandbox AYUDAN pero NO
CONTROLAN: la puerta real es verificar_paquete.py en el puesto del comercial.
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import zipfile

from nucleo import errores, hashes
from nucleo import estado as est_mod

SCHEMA = "preventa-manifiesto-paquete/1"
# I1.4 · P1: procedencia propia de B (texto recibido de cada tarea A2A y su SHA-256, lo escribe el código del hosted
# agent). Si está en procedencia/, va al ZIP como décimo fichero y el manifiesto lista su SHA-256. A no la tiene.
NOMBRE_PROCEDENCIA = "procedencia_a2a.json"
SCHEMA_PROCEDENCIA = "preventa-procedencia-a2a/1"


# VA18-7 (I1.9): en APROBADA el PPTX es el entregable del cliente, «<codigo>-Propuesta.pptx» (su title, «<codigo> ·
# Propuesta comercial», lo pone pptx_revision.generar); en los demás estados, el borrador «<codigo>-Revision.pptx».
SUFIJO_PPTX_REVISION = "Revision.pptx"
SUFIJO_PPTX_APROBADA = "Propuesta.pptx"


def nombre_pptx(codigo: str, estado_paquete: str | None = None) -> str:
    """VA18-7: nombre del PPTX según el estado del paquete."""
    return f"{codigo}-{SUFIJO_PPTX_APROBADA if estado_paquete == 'APROBADA' else SUFIJO_PPTX_REVISION}"


def nombres_zip(codigo: str, estado_paquete: str | None = None) -> list[str]:
    """Los nueve ficheros del ZIP, en el orden de §8 (el PPTX, según el estado: VA18-7)."""
    return [f"{codigo}-Estimacion.xlsx", f"{codigo}-Anexo-Consumo.xlsx", f"{codigo}-Anexo-Consumo.json",
            nombre_pptx(codigo, estado_paquete), f"{codigo}-Nota-Revision.docx", "estado.json", "manifiesto_paquete.json",
            "mensaje_revisor.txt", "mensaje_aprobador.txt"]


def _artefacto(ruta: pathlib.Path) -> dict:
    return {"nombre": ruta.name, "sha256": hashes.sha256_fichero(ruta), "bytes": ruta.stat().st_size}


def _comprobar_fichero(estado: dict, clave: str, ruta: pathlib.Path) -> list[str]:
    """El fichero existe y su SHA-256 es el registrado en artefactos."""
    reg = (estado.get("artefactos") or {}).get(clave)
    if not ruta.is_file():
        return [f"falta salida/{ruta.name}"]
    if not reg or reg.get("nombre") != ruta.name or reg.get("sha256") != hashes.sha256_fichero(ruta):
        return [f"salida/{ruta.name}: SHA-256 distinto del registrado en artefactos.{clave}"]
    return []


def _revalidar(estado: dict, catalogo: dict, tarifa: dict) -> None:
    """§13 en el sandbox: estado válido, verificación sin DISCREPA, STOP, textos atados a los hechos (P11)."""
    from nucleo import estado as est_mod
    from nucleo import estimacion, textos_cliente
    carga, motivos = estado["carga"], []
    vigente = hashes.hash_contenido(estado)
    if estado.get("hash_contenido") != vigente:
        raise errores.IntegridadRota("hash_contenido guardado distinto del recalculado",
                                     [f"guardado {estado.get('hash_contenido')}", f"recalculado {vigente}"])
    motivos += [f"estado: {e}" for e in est_mod.errores_estado(estado)]
    for k in ("respuestas_expertos", "verificacion", "anexo_consumo", "estimacion", "textos_cliente"):
        if not carga.get(k):
            motivos.append(f"falta carga.{k}")
    if motivos:
        raise errores.IntegridadRota("El estado no permite construir el paquete", motivos)
    if not carga["verificacion"]["resultado"].get("verificada"):
        raise errores.ReglaIncumplida("La verificación tiene DISCREPA efectivos (P5)", [])
    if estimacion.requiere_stop(estado):
        raise errores.ReglaIncumplida("Precio > 100.000 EUR sin CONFIRMA_STOP que cite el hash vigente (P7, LES-G-004)", [])
    recompuesto = textos_cliente.componer(estado, catalogo, tarifa)
    if recompuesto != carga["textos_cliente"]:
        diferentes = sorted(k for k in recompuesto if recompuesto.get(k) != carga["textos_cliente"].get(k))
        raise errores.IntegridadRota("textos_cliente no es lo que compone el código con los hechos vigentes (P11)",
                                     [f"difiere: {k}" for k in diferentes])
    tc, res, anx = carga["textos_cliente"], carga["estimacion"]["resumen"], carga["anexo_consumo"]
    if tc["precio"]["precio_cerrado_eur"] != res["precio_cerrado_eur"]:
        motivos.append("P11: precio del texto distinto del resumen")
    if [h["importe_eur"] for h in tc["precio"]["hitos"]] != [h["importe_eur"] for h in res["hitos"]]:
        motivos.append("P11: hitos del texto distintos del resumen")
    if [x["coste_mensual_eur"] for x in tc["consumo"]["lineas"]] != [x["coste_mensual_eur"] for x in anx["lineas"]]:
        motivos.append("P11: consumo del texto distinto del anexo")
    if motivos:
        raise errores.IntegridadRota("El contenido no es coherente", motivos)


def _xlsx_y_anexo(estado: dict, salida: pathlib.Path, catalogo: dict, rutas) -> None:
    """XLSX canónico y anexo: deben estar con su SHA-256; si faltan (tras restaurar), se regeneran."""
    from nucleo import anexo_consumo, estimacion
    codigo, carga, motivos = estado["codigo"], estado["carga"], []
    xlsx = salida / f"{codigo}-Estimacion.xlsx"
    if not xlsx.exists():
        entrada = carga["estimacion"]["entrada"]
        sha = estimacion.generar_xlsx(entrada, rutas, xlsx)
        dif = estimacion.comparar(carga["estimacion"]["resumen"], estimacion.leer_xlsx(xlsx), "xlsx")
        if dif:
            xlsx.unlink()
            raise errores.IntegridadRota("El XLSX regenerado no cuadra con el resumen guardado", dif)
        estado["artefactos"]["xlsx_estimacion"] = {"nombre": xlsx.name, "sha256": sha, "bytes": xlsx.stat().st_size}
    motivos += _comprobar_fichero(estado, "xlsx_estimacion", xlsx)
    anx_x, anx_j = salida / f"{codigo}-Anexo-Consumo.xlsx", salida / f"{codigo}-Anexo-Consumo.json"
    if not anx_x.exists() or not anx_j.exists():
        anexo = carga["anexo_consumo"]
        anexo_consumo.escribir_json(anexo, anx_j)
        anexo_consumo.generar_xlsx(anexo, anx_x, anexo_consumo.detalle_lineas(estado, catalogo))
        # el JSON es determinista: debe salir con el SHA-256 registrado (se comprueba abajo)
        estado["artefactos"]["anexo_xlsx"] = _artefacto(anx_x)
    motivos += _comprobar_fichero(estado, "anexo_xlsx", anx_x) + _comprobar_fichero(estado, "anexo_json", anx_j)
    if motivos:
        raise errores.IntegridadRota("Los ficheros económicos no cuadran con el estado", motivos)


def _escribir_texto(ruta: pathlib.Path, texto: str) -> None:
    from nucleo import estado as est_mod
    est_mod.escribir_atomico(ruta, texto.encode("utf-8"))
    os.chmod(ruta, 0o644)


def _zip(destino: pathlib.Path, ficheros: list[pathlib.Path]) -> None:
    """ZIP plano con ZIP_DEFLATED, escrito en temporal y sustituido de forma atómica; chmod 644."""
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".zip", dir=destino.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in ficheros:
                zf.write(f, arcname=f.name)
        os.chmod(tmp, 0o644)
        os.replace(tmp, destino)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _procedencia(raiz: pathlib.Path, salida: pathlib.Path) -> list[pathlib.Path]:
    """Copia procedencia/procedencia_a2a.json a salida/ si existe (opción B); [] si no. Ilegible: IntegridadRota."""
    origen = raiz / "procedencia" / NOMBRE_PROCEDENCIA
    if not origen.is_file():
        return []
    datos = origen.read_bytes()
    try:
        doc = json.loads(datos.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise errores.IntegridadRota(f"{NOMBRE_PROCEDENCIA} ilegible: no se empaqueta", [str(e)]) from e
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA_PROCEDENCIA or not isinstance(doc.get("tareas"), list):
        raise errores.IntegridadRota(f"{NOMBRE_PROCEDENCIA} no es {SCHEMA_PROCEDENCIA}: no se empaqueta", [])
    from nucleo import estado as est_mod
    destino = salida / NOMBRE_PROCEDENCIA
    est_mod.escribir_atomico(destino, datos)
    os.chmod(destino, 0o644)
    return [destino]


def _catalogo_sha(estado: dict, catalogo_sha256: str | None) -> str:
    """SHA-256 del catálogo montado; debe ser el mismo con el que se generaron los briefs."""
    briefs = estado["carga"].get("briefs") or []
    del_brief = briefs[-1].get("catalogo_sha256") if briefs else None
    sha = catalogo_sha256 or del_brief
    if not sha:
        raise errores.IntegridadRota("No se conoce el SHA-256 del catálogo montado", [])
    if del_brief and sha != del_brief:
        raise errores.IntegridadRota("El catálogo montado no es el del brief vigente",
                                     [f"montado {sha}", f"brief {del_brief}"])
    return sha


def _instantanea_sha(estado: dict) -> str:
    """I1.7 (decisión 1, CAMBIOS-I17-R §2.5): SHA-256 del fichero de la instantánea de precios montada (la que está junto al
    catálogo cargado, o PREVENTA_PRECIOS). Tiene que ser la misma con la que el núcleo completó la respuesta del experto
    (su huella interna en valoracion_nucleo.instantanea.sha256); si no, IntegridadRota (fallar cerrado)."""
    from nucleo import anexo_consumo
    ruta = anexo_consumo.ruta_instantanea()
    inst = anexo_consumo.cargar_instantanea(ruta)
    resp = est_mod.registro_experto(estado).get("respuesta") or {}
    usada = ((resp.get("valoracion_nucleo") or {}).get("instantanea") or {}).get("sha256")
    if usada != inst.get("sha256"):
        raise errores.IntegridadRota("La instantánea de precios montada no es la que usó el núcleo al registrar la "
                                     "respuesta del experto", [f"montada {inst.get('sha256')}", f"respuesta {usada}"])
    return hashes.sha256_fichero(pathlib.Path(ruta))


def _edad_instantanea(estado: dict, hoy: str | None) -> None:
    """REV17-6 (I1.8): la instantánea de los precios registrados no puede tener más de 31 días en la fecha del paquete
    (la misma regla que el anexo y la puerta, anexo_consumo.errores_edad). IntegridadRota con el motivo si no: se
    redespliega para descargarla de nuevo y se repite el análisis. Defensa en profundidad: la puerta también da FALLA."""
    from nucleo import anexo_consumo
    from nucleo import estado as est_mod
    edad = anexo_consumo.errores_edad(estado, hoy or est_mod.hoy().isoformat())
    if edad:
        raise errores.IntegridadRota("Paquete: la instantánea de precios de la respuesta registrada está caducada", edad)


def construir(estado: dict, raiz: pathlib.Path, catalogo: dict, tarifa: dict, rutas: "RutasGenerador",
              catalogo_sha256: str | None = None, transcripcion: "str | Exception | None" = None,
              hoy: str | None = None) -> dict:
    """Revalida todo (§13), regenera PPTX, DOCX y mensajes, copia estado.json, escribe
    manifiesto_paquete.json y el ZIP; devuelve el manifiesto. No cambia hash_contenido.
    Muta estado["artefactos"] (pptx, docx, zip y, si faltaban, xlsx_estimacion y anexo_xlsx).
    REV17-6 (I1.8): `hoy` (AAAA-MM-DD; por defecto, estado.hoy()) es la fecha con la que se mide la edad de la
    instantánea de precios, antes de escribir nada."""
    from nucleo import esquema, mensajes, nota_revision, pptx_revision
    from nucleo import estado as est_mod
    raiz = pathlib.Path(raiz)
    salida = raiz / "salida"
    if estado.get("estado") not in ("LISTA_PARA_REVISION", "EN_REVISION_PREVENTA", "EN_APROBACION_AREA", "APROBADA"):
        raise errores.TransicionNoPermitida(f"paquete no se construye en {estado.get('estado')}", [])
    _edad_instantanea(estado, hoy)   # REV17-6 (revisión de R): antes de crear nada en disco
    salida.mkdir(parents=True, exist_ok=True)
    codigo = estado["codigo"]
    hash_antes = hashes.hash_contenido(estado)
    _revalidar(estado, catalogo, tarifa)
    cat_sha = _catalogo_sha(estado, catalogo_sha256)
    precios_sha = _instantanea_sha(estado)
    _xlsx_y_anexo(estado, salida, catalogo, rutas)
    nombres = nombres_zip(codigo, estado.get("estado"))
    otro = salida / nombre_pptx(codigo, None if estado.get("estado") == "APROBADA" else "APROBADA")
    if otro.exists():  # VA18-7: el PPTX del otro estado no se queda junto al vigente (no entra en el ZIP)
        otro.unlink()
    pptx = salida / nombres[3]
    pptx_revision.generar(estado, catalogo, pptx)
    estado["artefactos"]["pptx"] = _artefacto(pptx)
    docx = salida / nombres[4]
    nota_revision.generar(estado, catalogo, docx, transcripcion)
    estado["artefactos"]["docx"] = _artefacto(docx)
    nombre_zip = f"{codigo}-Paquete.zip"
    _escribir_texto(salida / "mensaje_revisor.txt", mensajes.mensaje_revisor(estado, nombre_zip))
    _escribir_texto(salida / "mensaje_aprobador.txt", mensajes.mensaje_aprobador(estado, nombre_zip))
    estado["artefactos"]["zip"] = None  # la copia no puede llevar el SHA-256 del ZIP que la contiene
    est_mod.guardar(estado, raiz)  # estado.json del directorio de trabajo = la copia del ZIP
    copia = salida / "estado.json"
    est_mod.escribir_atomico(copia, est_mod.ruta_estado(raiz).read_bytes())
    os.chmod(copia, 0o644)
    procedencia = _procedencia(raiz, salida)
    ficheros = [salida / n for n in nombres if n != "manifiesto_paquete.json"] + procedencia
    man = {"schema": SCHEMA, "codigo": codigo, "version": estado["version"], "estado": estado["estado"],
           "hash_contenido": hash_antes, "estado_json_sha256": hashes.sha256_fichero(copia),
           "ficheros": [_artefacto(f) for f in ficheros],
           "montados": {"rate_card_sha256": hashes.sha256_fichero(pathlib.Path(rutas.rate_card)),
                        "generador_sha256": hashes.sha256_fichero(pathlib.Path(rutas.generador)),
                        "plantilla_sha256": hashes.sha256_fichero(pathlib.Path(rutas.plantilla)),
                        "catalogo_sha256": cat_sha,
                        "precios_instantanea_sha256": precios_sha},   # I1.7 (CAMBIOS-I17-R §2.5)
           "generado_ts": est_mod.ahora_ts(), "orquestador": estado["orquestador"]}   # VER14-3: el de estado.json
    if est_mod.pilar(estado) != est_mod.PILAR_POR_DEFECTO:   # multinube: Azure no escribe la clave (paquete idéntico)
        man["pilar"] = est_mod.pilar(estado)
    esquema.exigir(man, "manifiesto_paquete", errores.IntegridadRota)
    _escribir_texto(salida / "manifiesto_paquete.json", json.dumps(man, ensure_ascii=False, indent=2) + "\n")
    ruta_zip = salida / nombre_zip
    _zip(ruta_zip, [salida / n for n in nombres] + procedencia)
    estado["artefactos"]["zip"] = _artefacto(ruta_zip)
    if hashes.hash_contenido(estado) != hash_antes:
        raise errores.IntegridadRota("paquete cambió hash_contenido (no debe)", [])
    return man
