"""I1.8 · papel P: datos y comprobaciones comunes de las pruebas (no es un fichero de pruebas).

Base: el catálogo y la instantánea REALES del sandbox y la respuesta v4 de Brezalia de I1.7 (tests/i17_p_datos.py).
`reglas()` calcula cada regla del núcleo sobre la respuesta completada y exige que la réplica para la puerta
(docs/I1/CAMBIOS-I18-P/replicas_puerta.py) dé exactamente lo mismo: así cada caso adverso es también una prueba de
igualdad (LES-G-097) y su resultado esperado se fija en la propia prueba (LES-G-096.6).
"""
from __future__ import annotations

import copy
import json
import sys

from tests.i17_p_datos import RAIZ, estado_brezalia, perfiles, respuesta_v4
from tests.i19_p_datos import catalogo_i19
from nucleo import experto
import verificar_paquete as vp

_DIR_REPLICAS = RAIZ / "docs" / "I1" / "CAMBIOS-I18-P"
if str(_DIR_REPLICAS) not in sys.path:
    sys.path.insert(0, str(_DIR_REPLICAS))
import replicas_puerta as R  # noqa: E402

if hasattr(vp, "servicios_nombrados_r"):
    # Integrador I1.8: las réplicas ya están pegadas en la puerta, que además aplica N1, N5 y N7 (CAMBIOS-I18-E §3);
    # la copia de docs/ queda como histórico de lo que entregó P y las comparaciones se hacen contra la puerta.
    R = vp  # noqa: F811

if not hasattr(vp, "existentes_r"):  # I1.9 (papel P): hasta pegar docs/I1/CAMBIOS-I19-P/replicas_puerta.py, encima
    import types
    from tests.i19_p_datos import R19 as _r19
    R = types.SimpleNamespace(**{**{k: getattr(R, k) for k in dir(R) if not k.startswith("__")},  # noqa: F811
                                 **{k: x for k, x in vars(_r19).items() if not k.startswith("__")}})

# I1.9: el catálogo real con lo que añade E en I1.9 (nivel por defecto y razones de subida), simulado en i19_p_datos
CAT = catalogo_i19(json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8")))
INST = json.loads((RAIZ / "sandbox" / "datos" / "precios_instantanea.json").read_text(encoding="utf-8"))
HOY = str(INST["fecha_consulta"])[:10]
CONSULTAS = {"cita": "Unas 2.000 consultas al mes.", "cantidad_base": 2000, "unidad_base": "consultas al mes"}
LIMITES_URL = "https://learn.microsoft.com/azure/azure-resource-manager/management/azure-subscription-service-limits"
# I1.9 (contrato v5): más de una instancia de B1 se justifica con una razón del nivel B1 (de prueba: B1_RAZON) y su cita
B1_DOS = {"nivel": "B1", "razon": "tecnicos_sobre_uno", "cita": "60 técnicos."}
B1_RAZON = [{"id": "tecnicos_sobre_uno", "tipo": "umbral", "campo": "volumetria", "unidad": ["técnicos"], "limite": 50,
             "fuente": LIMITES_URL, "texto": "prueba: más técnicos de los que atiende una instancia"}]
CLIENTE = "El cliente ya paga su espacio de Log Analytics."


def base(catalogo: dict | None = None):
    """(brief, requisitos, respuesta, catálogo) de control: la respuesta de Brezalia con el cómputo por defecto."""
    est = estado_brezalia()
    brief = est["carga"]["briefs"][-1]
    r = respuesta_v4(brief)
    r["arquitectura_id"] = "foundry-chat-basica"
    for c in r["componentes"]:
        if c["id"] == "C-04":
            c["justificacion_nivel"] = None
    return brief, est["carga"]["requisitos"], r, copy.deepcopy(catalogo if catalogo is not None else CAT)


def con_campo_cliente(brief: dict, req: dict, r: dict, valores: list[str], en_brief: bool = True, origen="CITADO"):
    """Añade el campo «lo que el cliente ya tiene o paga» a los requisitos y, si se pide, su sección al brief (y al eco)."""
    req["campos"][experto.CAMPO_CLIENTE] = {"estado": "CITADO", "entradas": [
        {"valor": v, "cita": "la frase literal de la transcripción", "fuente": "F1", "origen": origen} for v in valores]}
    if en_brief:
        brief["texto"] = brief["texto"].rstrip("\n") + "\n" + experto.SECCION_CLIENTE + "\n" + "".join(
            f"- {v}\n" for v in valores)
        r["brief_recibido"] = brief["texto"]


def comp(r: dict, cid: str, catalogo_id, servicio: str, capa: str, sku: str, region: str = "swedencentral", **extra):
    c = {"id": cid, "catalogo_id": catalogo_id, "servicio": servicio, "capa": capa, "sku": sku, "region": region,
         "cantidad": 1, "unidad": "recurso", "referencia_id": None, "desviacion_justificada": None,
         "motivo_no_valoracion": "no_aplica", "existente_del_cliente": None, "incluido_en": None,
         "justificacion_nivel": None}  # I1.9: contrato v5
    c.update(extra)
    r["componentes"].append(c)
    return c


def precio(r: dict, pid: str, cid: str, plantilla: str, instancias=None, base_volumen=None):
    r["precios"].append({"id": pid, "componente_id": cid, "plantilla_id": plantilla, "instancias": instancias,
                         "base_volumen": copy.deepcopy(base_volumen), "factor_override": None})


def fila(catalogo: dict, cid: str) -> dict:
    return next(e for e in catalogo["componentes"] if e["id"] == cid)


def analizar(r: dict, brief: dict, req: dict, catalogo: dict):
    return experto.analizar_respuesta(r, brief, catalogo, perfiles(brief), req, INST, HOY)


def reglas(r: dict, brief: dict, req: dict, catalogo: dict) -> dict:
    """Reglas del núcleo sobre la completada; la réplica de la puerta tiene que dar lo mismo en cada una."""
    c, faltas = experto.completar(r, catalogo, INST, req, brief["texto"])
    rec, fallos = R.completar_r(R.proyectar_r(c), catalogo, INST, req, brief["texto"])
    assert rec == c and fallos == [(x["id"], x["regla"]) for x in faltas]
    salida = {"completar": [(x["id"], x["regla"]) for x in faltas],
              "volumen_nivel": [(x["id"], x["regla"]) for x in experto.errores_volumen_nivel(c, brief["texto"], req, catalogo)],
              "motivos": [(x["id"], x["regla"]) for x in experto.errores_motivos(c, catalogo, req, brief["texto"])],
              "ciclo": [(x["id"], x["regla"]) for x in experto.errores_ciclo_vida(
                  c, catalogo, HOY, experto.duracion_gantt(experto.proyectar_modelo(c)))]}
    assert salida["volumen_nivel"] == R.errores_volumen_nivel_replica(c, brief["texto"], req, catalogo)
    assert salida["motivos"] == R.motivos_r(c, catalogo, req, brief["texto"])
    assert salida["ciclo"] == R.ciclo_r(c, catalogo, HOY, vp.semanas_r(R.proyectar_r(c)))
    if hasattr(vp, "existentes_r"):  # I1.9: ya pegadas en la puerta: la puerta también da lo mismo
        assert vp.completar_r(vp.proyectar_r(c), catalogo, INST, req, brief["texto"]) == (rec, fallos)
        assert salida["volumen_nivel"] == vp.errores_volumen_nivel_replica(c, brief["texto"], req, catalogo)
        assert salida["motivos"] == vp.motivos_r(c, catalogo, req, brief["texto"])
        assert salida["ciclo"] == vp.ciclo_r(c, catalogo, HOY, vp.semanas_r(vp.proyectar_r(c)))
    salida["completada"] = c
    return salida
