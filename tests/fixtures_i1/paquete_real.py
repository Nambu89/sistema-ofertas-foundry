"""Paquetes REALES para las pruebas de la puerta: el flujo completo del núcleo vigente (sin dobles).

Recorre iniciar → … → paquete con `sandbox/preventa_api.py`, el catálogo y la tarifa del repositorio y
el generador canónico sin modificar, con las entradas de `esquemas/ejemplos` (como el simulador de
paridad de I1.1). Así la recomposición local de `verificar_paquete.py` compara contra lo que el código
de confianza genera hoy, y las roturas de `pruebas/I1/VERIF/romper.py` se aplican sobre un paquete
auténtico. `aprobar()` registra las tres decisiones y vuelve a empaquetar (paquete APROBADA).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
EJ = RAIZ / "esquemas" / "ejemplos"
TRANSCRIPCION = RAIZ / "datos_prueba" / "transcripcion_sintetica_I1.txt"
SENSIBLES = ["Kelvara Ensayos Industriales", "Kelvara", "Marta Olmedo", "Iker Salaverri", "Nuria Castells",
             "Zaragoza", "Tarragona"]


class FlujoRoto(AssertionError):
    """Un paso del núcleo no dio rc 0: se muestra su salida literal (LES-G-048)."""


def _api():
    if str(RAIZ / "sandbox") not in sys.path:
        sys.path.insert(0, str(RAIZ / "sandbox"))
    import preventa_api
    return preventa_api


def _ej(nombre: str) -> dict:
    return json.loads((EJ / f"{nombre}.json").read_text(encoding="utf-8"))


def _paso(r, esperado: int = 0):
    if r.rc != esperado:
        raise FlujoRoto(f"{r.subcomando} rc={r.rc} (se esperaba {esperado}):\n{r.salida[-3000:]}")
    return r


def respuesta_verificador_vigente() -> dict:
    """El ejemplo del verificador ajustado al esquema VIGENTE (LES-G-096), sin inventar nada.

    Si los ejemplos aún no se han regenerado tras el cambio de esquema: se quedan solo los elementos de
    los tipos que admite el esquema (referencias, componentes y precios), el resumen se recuenta desde
    los veredictos y las herramientas nuevas cuentan 0. Si el ejemplo ya es válido, se usa tal cual.
    """
    return ajustar_respuesta_verificador(_ej("respuesta_verificador"))


def ajustar_respuesta_verificador(r: dict) -> dict:
    """Ajusta una respuesta del verificador al esquema vigente (ver respuesta_verificador_vigente)."""
    sys.path.insert(0, str(RAIZ)) if str(RAIZ) not in sys.path else None
    from esquemas.comprobar_esquemas import validar
    esquema = json.loads((RAIZ / "esquemas" / "respuesta_verificador.json").read_text(encoding="utf-8"))
    if not validar(r, esquema, esquema):
        return r
    props = esquema["properties"]
    item = props["elementos"]["items"]
    if "$ref" in item:
        item = esquema["$defs"][item["$ref"].rsplit("/", 1)[-1]]
    tipos = set(item["properties"]["tipo"].get("enum") or [])
    r["elementos"] = [x for x in r["elementos"] if not tipos or x.get("tipo") in tipos]
    claves = {"OK": "ok", "DISCREPA": "discrepa", "OBSERVACION": "observacion", "NO VERIFICABLE": "no_verificable"}
    r["resumen"] = {k: 0 for k in props["resumen"]["required"]}
    for x in r["elementos"]:
        r["resumen"][claves[x["veredicto"]]] += 1
    for k in props["herramientas_usadas"]["required"]:
        r["herramientas_usadas"].setdefault(k, 0)
    errores = validar(r, esquema, esquema)
    if errores:
        raise FlujoRoto(f"el ejemplo del verificador no se puede ajustar al esquema vigente: {errores[:5]}")
    return r


class Flujo:
    """Una solicitud en su propia carpeta de trabajo (un solo escritor, API-NUCLEO.md §4)."""

    def __init__(self, base: pathlib.Path):
        self.P = _api()
        self.base = base
        self.datos, self.trabajo, self.tmp = base / "datos", base / "trabajo", base / "tmp"
        for d in (self.datos, self.trabajo, self.tmp):
            d.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TRANSCRIPCION, self.datos / TRANSCRIPCION.name)
        self.env = self.P.abrir(str(self.trabajo), datos=str(self.datos), tmp=str(self.tmp), montaje="exacto")
        self.hoy = dt.date.today().isoformat()

    def entrada(self, nombre: str, obj: dict) -> str:
        ruta = self.trabajo / "entrada" / nombre
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"entrada/{nombre}"

    def estado(self) -> dict:
        return json.loads((self.trabajo / "estado.json").read_text(encoding="utf-8"))

    def hasta_lista(self) -> pathlib.Path:
        P, e = self.P, self.env
        _paso(P.iniciar(e, cliente="Kelvara Ensayos Industriales, S.A.", codigo_cliente="KELVARA", seqof="001",
                        titulo="Asistente de consulta técnica con IA sobre informes de ensayo",
                        transcripcion=TRANSCRIPCION.name, sensibles=SENSIBLES, nda_confirmado=True))
        req = _ej("requisitos")
        for c in ("volumetria", "identidad_acl_origen"):
            req["campos"][c] = {"estado": "FALTA", "entradas": []}
        _paso(P.suficiencia(e, requisitos=self.entrada("requisitos.json", req)), 1)
        for c in ("volumetria", "identidad_acl_origen"):
            _paso(P.asumir(e, campo=c, valor=_ej("requisitos")["campos"][c]["entradas"][0]["valor"]))
        _paso(P.enrutar(e))
        rexp = _ej("respuesta_experto")
        rexp["brief_recibido"] = (self.trabajo / "briefs" / f"{rexp['brief_id']}.txt").read_text(
            encoding="utf-8").rstrip("\n")
        _paso(P.registrar_experto(e, respuesta=self.entrada("respuesta_experto_AZ_R1.json", rexp)))
        _paso(P.consolidar(e))
        rver = respuesta_verificador_vigente()
        cons = (self.trabajo / "consolidados" / f"{rver['consolidado_id']}.txt").read_text(encoding="utf-8")
        rver["entrada_recibida_inicio"] = "\n".join(cons.split("\n")[:3])
        _paso(P.registrar_verificacion(e, respuesta=self.entrada("respuesta_verificador_R1.json", rver)))
        _paso(P.anexo_consumo(e))
        _paso(P.estimar(e))  # REV-1 (I1.4): la entrada la compone el núcleo con la regla del 10-10-2026
        _paso(P.paquete(e))
        return self.zip()

    def zip(self) -> pathlib.Path:
        zips = sorted(self.trabajo.rglob("*-Paquete.zip"))
        if len(zips) != 1:
            raise FlujoRoto(f"se esperaba un ZIP de paquete y hay {[str(z) for z in zips]}")
        return zips[0]

    def aprobar(self) -> pathlib.Path:
        """ENVIADA_REVISION, APROBADA del responsable de preventa y del responsable de área con el hash vigente; vuelve a empaquetar."""
        h = self.estado()["hash_contenido"]
        for linea in (f"DECISION | Responsable comercial | ENVIADA_REVISION | {self.hoy} | {h} | verificar_paquete rc=0; enviado",
                      f"DECISION | Responsable de preventa | APROBADA | {self.hoy} | {h} | Conforme, sin comentarios",
                      f"DECISION | Responsable de área | APROBADA | {self.hoy} | {h} | Aprobada por el área"):
            _paso(self.P.decision(self.env, linea=linea))
        r = self.P.paquete(self.env)
        if r.rc != 0 and self.estado().get("estado") != "APROBADA":
            raise FlujoRoto(f"paquete tras aprobar rc={r.rc}:\n{r.salida[-3000:]}")
        return self.zip()
