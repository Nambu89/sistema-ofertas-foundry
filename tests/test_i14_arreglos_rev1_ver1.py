"""Arreglos de I1.4 (10-10-2026): REV-1 (la regla de estimación no se puede saltar) y VER14-1 / PR14-1 (consumo a
0,00 € con Azure facturable). Casos adversos con su resultado esperado, núcleo y réplica de la puerta (LES-G-096.6,
LES-G-097), y datos del paquete REAL de B que dio verde con 0 precios (LES-G-078). Sin red.
"""
from __future__ import annotations

import copy
import inspect
import json
import pathlib
import random
import re
import sys
import types
import zipfile
from datetime import date

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
for p in (RAIZ / "sandbox", RAIZ):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from nucleo import anexo_consumo, brief, esquema, experto, textos_cliente, verificacion  # noqa: E402
from nucleo import estimacion as N  # noqa: E402
from nucleo.errores import ReglaIncumplida  # noqa: E402
import preventa_api  # noqa: E402
import verificar_paquete as vp  # noqa: E402

TARIFA = RAIZ / "tests" / "insumos" / "rate-card.sintetica.json"
from tests.i16_p_datos import a_v3, catalogo_i16  # noqa: E402  (I1.6: contrato común de la decisión 4)
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)
CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
REAL_0_PRECIOS = RAIZ / "pruebas" / "I14" / "REAL" / "B" / "descargas_A" / "OF-BREZALIA-001-A-Paquete.zip"
EJ = RAIZ / "esquemas" / "ejemplos"


def _ej(nombre: str) -> dict:
    return json.loads((EJ / f"{nombre}.json").read_text(encoding="utf-8"))


def _real() -> dict:
    with zipfile.ZipFile(REAL_0_PRECIOS) as z:
        return json.loads(z.read("estado.json"))


@pytest.fixture()
def tarifa() -> dict:
    return N.cargar_tarifa(TARIFA)


@pytest.fixture()
def estado() -> dict:
    est = _ej("estado")
    est["carga"]["estimacion"] = None
    return est


def _compuesta(estado: dict, tarifa: dict) -> dict:
    return N.componer_entrada(estado, N.hitos_tarifa(tarifa), date(2026, 10, 8))[0]


# ── REV-1 en el núcleo ──────────────────────────────────────────────────────

def test_la_entrada_compuesta_es_valida_y_el_ejemplo_regenerado_tambien(estado, tarifa):
    assert N.errores_regla(_compuesta(estado, tarifa), estado, tarifa) == []
    assert N.errores_regla(_ej("estimacion_entrada"), estado, tarifa) == []   # ejemplo regenerado con la regla


def _pm(entrada: dict) -> dict:
    return next(t for t in entrada["tareas"] if t["id"] == "PM-01")


@pytest.mark.parametrize("caso", ["pm_8h_gantt_1_semana", "pm_300h", "perfiles_de_mas", "tipo_24_0", "asuncion_libre",
                                  "tarea_reordenada", "hito_cambiado"])
def test_la_sonda_de_rev1_ya_no_pasa(estado, tarifa, caso):
    """REVISION/sonda_estimacion.txt: PM 8 h con Gantt de 1 semana y PM 300 h daban errores=[]; ahora P6f."""
    e = _compuesta(estado, tarifa)
    if caso == "pm_8h_gantt_1_semana":
        _pm(e).update(tecnicas_h=8, reuniones_h=1)
        e["duracion_semanas"] = 1
        for g in e["gantt"]:
            g["semanas"] = [1]
        esperado = {"tareas", "gantt", "duracion_semanas"}
    elif caso == "pm_300h":
        _pm(e)["tecnicas_h"] = 300
        esperado = {"tareas"}
    elif caso == "perfiles_de_mas":
        e["perfiles"] = sorted({t["perfil"] for t in e["tareas"]})
        esperado = {"perfiles"}
    elif caso == "tipo_24_0":
        e["tareas"][0]["tecnicas_h"] = float(e["tareas"][0]["tecnicas_h"])
        esperado = {"tareas"}
    elif caso == "asuncion_libre":
        e["asunciones"] = ["El cliente acepta cualquier plazo que se le proponga."]
        esperado = {"asunciones"}
    elif caso == "tarea_reordenada":
        e["tareas"][0], e["tareas"][1] = e["tareas"][1], e["tareas"][0]
        esperado = {"tareas"}
    else:
        e["hitos"][0]["porcentaje"] = 30
        esperado = {"hitos"}
    errores = N.validar_entrada(e, estado, tarifa, None)
    campos = {m.group(1) for x in errores if (m := re.match(r"P6f (\w+)", x))}
    assert esperado <= campos, errores


def test_fecha_y_ajuste_quedan_fuera_de_la_regla(estado, tarifa):
    e = _compuesta(estado, tarifa)
    e["fecha"] = "2026-11-02"
    assert N.errores_regla(e, estado, tarifa) == []
    e["fecha"] = "no es fecha"
    assert N.errores_regla(e, estado, tarifa)[0].startswith("P6f fecha:")


def test_sin_tareas_propuestas_no_se_puede_recomponer(estado, tarifa):
    e = _compuesta(estado, tarifa)
    estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["tareas_propuestas"] = []
    assert any("P6f: no se puede recomponer" in x for x in N.validar_entrada(e, estado, tarifa, None))


def test_estimar_ya_no_admite_entrada_en_la_cli_ni_en_la_api(tmp_path, monkeypatch):
    from tests.test_i1_estado_comun import Mundo
    m = Mundo(tmp_path, monkeypatch)
    m.hasta_verificada()
    assert m.run("anexo-consumo")[0] == 0
    rc, out = m.run("estimar", "--entrada", m.entrada_estimacion())
    assert rc == 2 and "unrecognized arguments: --entrada" in out, out
    assert m.estado()["carga"].get("estimacion") is None
    rc, out = m.run("estimar")
    assert rc == 0 and "ENTRADA DE ESTIMACIÓN compuesta por el núcleo" in out, out
    assert "entrada" not in inspect.signature(preventa_api.estimar).parameters


# ── REV-1 en la puerta: réplica local y núcleo ──────────────────────────────

def _ctx(estado: dict, tarifa: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(respuesta=estado["carga"]["respuestas_expertos"]["azure"]["respuesta"],
                                 tarifa=tarifa, estado=estado, catalogo_obj=CAT)


def test_puerta_regla_en_verde_con_la_entrada_compuesta(estado, tarifa):
    c = vp.Comprobacion("estimacion", "x")
    vp._regla_estimacion(_ctx(estado, tarifa), c, _compuesta(estado, tarifa))
    assert c.estado == "OK", c.detalles
    assert any("regla de estimación recompuesta en local: PM" in d for d in c.detalles)


@pytest.mark.parametrize("tecnicas_pm", [8, 300])
def test_puerta_regla_falla_con_otro_pm(estado, tarifa, tecnicas_pm):
    e = _compuesta(estado, tarifa)
    _pm(e)["tecnicas_h"] = tecnicas_pm
    c = vp.Comprobacion("estimacion", "x")
    vp._regla_estimacion(_ctx(estado, tarifa), c, e)
    texto = "\n".join(c.detalles)
    assert c.estado == "FALLA" and "estimacion.entrada.tareas no es lo que compone la regla" in texto
    assert "regla de estimación (núcleo): P6f tareas" in texto


def test_replica_de_la_regla_igual_al_nucleo_en_casos_variados(estado, tarifa):
    """LES-G-096.6 y LES-G-099.5: muchas respuestas distintas, todas aceptadas, y ninguna diferencia."""
    perfiles = [p["nombre"] for p in tarifa["perfiles"]]
    azar, aceptados = random.Random(20261010), 0
    base = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    for _ in range(300):
        est = copy.deepcopy(estado)
        resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
        tps = []
        for i in range(azar.randint(1, 9)):
            t = copy.deepcopy(base["tareas_propuestas"][i % len(base["tareas_propuestas"])])
            t.update(id=f"T-{i + 1:02d}", fase=f"F{azar.randint(0, 3)}", perfil=azar.choice(perfiles),
                     horas_base=azar.choice([4, 8, 12.5, 16, 24, 40, 80, 160, 399, 401]),
                     reuniones_h=azar.choice([0, 1, 2, 7.5, 12]))
            tps.append(t)
        resp["tareas_propuestas"] = tps
        nucleo = _compuesta(est, tarifa)
        replica = vp.regla_estimacion_replica(resp, tarifa["hitos_pago"])
        for k in replica:
            assert vp._canon_regla(nucleo[k]) == vp._canon_regla(replica[k]), (k, tps)
        aceptados += N.errores_regla(nucleo, est, tarifa) == []
    assert aceptados == 300


# ── VER14-1 / PR14-1 ────────────────────────────────────────────────────────

def test_el_paquete_real_con_0_precios_tiene_azure_facturable():
    resp = _real()["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    assert resp["precios"] == []
    nombres = {x["servicio"] for x in anexo_consumo.facturables_azure(resp, CAT)}
    assert {"Azure App Service", "Azure AI Search"} <= nombres, nombres
    assert len(vp.facturables_azure_replica(resp, CAT)) == len(anexo_consumo.facturables_azure(resp, CAT))


def test_el_nucleo_rechaza_la_respuesta_real_sin_precios():
    est = _real()
    resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    br = next(b for b in est["carga"]["briefs"] if b["brief_id"] == resp["brief_id"])
    for c in resp["componentes"]:  # I1.5: contrato v2 del experto (motivo_no_valoracion); el resto, real
        c.setdefault("motivo_no_valoracion", "no_aplica")
    resp = a_v3(resp)  # I1.6: contrato v3 (justificacion_nivel y base_volumen a null)
    errores = i17_int.validar(resp, br, CAT, br["perfiles_permitidos"])
    assert any(e.startswith("precios: no hay ningún precio de consumo") and "PR14-1" in e for e in errores), errores


def test_sin_precios_y_solo_saas_no_se_rechaza():
    resp, br = _ej("respuesta_experto"), _ej("brief")
    resp["precios"] = []
    for c in resp["componentes"]:
        c.update(catalogo_id=None, servicio="Microsoft Teams",
                 desviacion_justificada="Canal de los usuarios, licenciado aparte por el cliente en Microsoft 365.")
    errores = i17_int.validar(resp, br, CAT, br["perfiles_permitidos"])
    assert not [e for e in errores if e.startswith("precios: no hay")], errores
    assert anexo_consumo.facturables_azure(resp, CAT) == [] and vp.facturables_azure_replica(resp, CAT) == []


def test_el_anexo_no_se_compone_vacio_con_azure_facturable():
    est = _real()
    with pytest.raises(ReglaIncumplida) as ex:
        anexo_consumo.calcular(est, CAT)
    assert any("Anexo sin líneas" in e and "PR14-1" in e for e in ex.value.errores)


def test_fuente_de_consumo_sin_lineas_no_afirma_region_ni_vigencia():
    sin = textos_cliente._consumo({"lineas": [], "fuente": {"consultado_el": "2026-10-10"},
                                   "total_mensual_eur": "0.00", "total_anual_eur": "0.00"})["fuente"]
    assert "región" not in sin and "vigentes" not in sin and "2026-10-10" in sin
    patron = esquema.cargar("textos_cliente")["properties"]["consumo"]["properties"]["fuente"]["pattern"]
    assert re.match(patron, sin)
    anexo = _ej("anexo_consumo")
    con = textos_cliente._consumo(anexo)["fuente"]
    # I1.7 (D): «región» o «regiones» según cuántas haya, y «precios consultados el <fecha>» (decisión 1)
    assert con.startswith("Azure Retail Prices (prices.azure.com), regi") and re.match(patron, con)


def test_el_brief_de_la_ronda_2_lleva_los_filtros_de_precio_sin_importe():
    ln = ("P-02 | C-04 | filtro: serviceName eq 'Azure App Service' and armRegionName eq 'westeurope' | precio: "
          "0.123456789 EUR | unidad: 1 Hour | region: westeurope | effectiveStartDate: 2026-01-01")
    assert verificacion.linea_precio_conservar(ln) == (
        "P-02 | C-04 | filtro: serviceName eq 'Azure App Service' and armRegionName eq 'westeurope' | unidad: 1 Hour "
        "| region: westeurope")
    assert verificacion.linea_precio_conservar("P-02 | sin forma") is None
    est = _ej("estado")
    est["carga"]["verificacion"]["resultado"]["discrepa"] = [{"id": "P-01"}]
    conservar = verificacion.lineas_conservar(est)
    pids = [x.split(" |")[0] for x in conservar if x.startswith("P-")]
    assert "P-01" not in pids and pids and all("precio:" not in x for x in conservar if x.startswith("P-"))
    assert not brief.hallazgos_sensibles("\n".join(conservar), [])


def test_puerta_falla_con_respuesta_y_anexo_sin_precios():
    est = _real()
    ctx = types.SimpleNamespace(respuesta=est["carga"]["respuestas_expertos"]["azure"]["respuesta"],
                                catalogo_obj=CAT, estado=est)
    c = vp.Comprobacion("coherencia", "x")
    vp._sin_precios_con_azure(ctx, c, "anexo de consumo", True)
    assert c.estado == "FALLA" and "PR14-1" in "\n".join(c.detalles)
    c = vp.Comprobacion("coherencia", "x")
    vp._sin_precios_con_azure(ctx, c, "anexo de consumo", False)
    assert c.estado == "OK", c.detalles


def test_la_regex_de_saas_de_la_puerta_es_la_del_nucleo():
    assert vp._SAAS_REPLICA.pattern == anexo_consumo._SAAS.pattern


def test_puerta_falla_si_no_puede_contrastar_facturables_con_el_nucleo():
    resp = copy.deepcopy(_real()["carga"]["respuestas_expertos"]["azure"]["respuesta"])
    resp["componentes"][0]["catalogo_id"] = "no-existe"
    ctx = types.SimpleNamespace(respuesta=resp, catalogo_obj=CAT, estado={})
    c = vp.Comprobacion("experto", "x")
    vp._sin_precios_con_azure(ctx, c, "respuesta del experto", False)
    assert c.estado == "FALLA" and "no se pudo contrastar" in "\n".join(c.detalles)


def test_un_brief_ya_guardado_sin_precios_en_conservar_se_regenera_igual(tmp_path, monkeypatch):
    """Revisión (arreglos I1.4) temía IntegridadRota: _conservar devuelve lo guardado y el texto sale idéntico."""
    from tests import test_i13_convergencia as T
    from tests.test_i1_estado_comun import Mundo
    m = Mundo(tmp_path, monkeypatch)
    m.hasta_verificacion()
    c = T._cons(m)
    T._registrar(m, T._resp(c["consolidado_id"], c["texto"], c["ids"],
                            {"C-02": {"veredicto": "DISCREPA", "campo": "sku", "valor_correcto": "Basic", "fuente_url": T.OTRA}}))
    original = verificacion.lineas_conservar
    monkeypatch.setattr(verificacion, "lineas_conservar",
                        lambda est: [ln for ln in original(est) if not ln.startswith("P-")])  # como antes de I1.4
    assert m.run("enrutar")[0] == 0
    monkeypatch.setattr(verificacion, "lineas_conservar", original)
    est = m.estado()
    viejo = est["carga"]["briefs"][-1]
    assert viejo["ronda"] == 2 and not [ln for ln in viejo["conservar"] if ln.startswith("P-")]
    b = brief.generar(est, viejo["perfiles_permitidos"], viejo["catalogo_sha256"])
    assert b.sha256 == viejo["sha256"] and "## Precios ya verificados" not in b.texto


def test_la_puerta_rechaza_el_paquete_real_que_daba_verde_con_0_euros(capsys):
    """VER14-1: el mismo ZIP que dio rc 0 con --estricto (VERIF/puerta_lista.txt) ahora FALLA por PR14-1."""
    from tests.evidencias import requerir
    requerir(REAL_0_PRECIOS)
    rc = vp.main([str(REAL_0_PRECIOS), "--transcripcion",
                  str(RAIZ / "pruebas" / "I12" / "REAL" / "transcripcion_sintetica_I11V.txt"), "--sin-red"])
    out = capsys.readouterr().out
    fallan = [ln.split("]")[1].split(":")[0].strip() for ln in out.splitlines() if ln.startswith("[FALLA]")]
    assert rc == 1 and {"experto", "coherencia"} <= set(fallan), out
    assert out.count("(PR14-1, LES-G-062)") == 2
    assert "regla de estimación recompuesta en local: PM 30 h técnicas, 5 semanas" in out   # B ya cumplía la regla
