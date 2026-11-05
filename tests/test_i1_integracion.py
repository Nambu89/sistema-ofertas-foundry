"""Pruebas del integrador de I1: errores, esquema, textos_cliente y paquete con los módulos reales."""
from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
for _p in (RAIZ / "sandbox", RAIZ / "esquemas"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import comprobar_esquemas  # noqa: E402
from nucleo import errores, esquema, hashes, paquete, pptx_revision, textos_cliente  # noqa: E402

EJ = RAIZ / "esquemas" / "ejemplos"


def ej(nombre: str):
    return json.loads((EJ / f"{nombre}.json").read_text(encoding="utf-8"))


@pytest.fixture()
def contexto():
    est = ej("estado")
    cat = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    tar = json.loads((RAIZ / "tests" / "insumos" / "rate-card.sintetica.json").read_text(encoding="utf-8"))
    return est, cat, tar


def test_errores_codigos_y_forma():
    for clase, rc in ((errores.EntradaInvalida, 2), (errores.ReglaIncumplida, 1), (errores.Bloqueo, 1),
                      (errores.TransicionNoPermitida, 3), (errores.IntegridadRota, 4)):
        e = clase("m", ["a", "b"])
        assert isinstance(e, errores.ErrorPreventa) and e.codigo_salida == rc
        assert e.mensaje == "m" and e.errores == ["a", "b"] and str(e) == "m"


@pytest.mark.parametrize("nombre", sorted(p.stem for p in (RAIZ / "esquemas").glob("*.json")))
def test_esquema_igual_que_la_referencia_en_los_ejemplos(nombre):
    s = esquema.cargar(nombre)
    assert esquema.validar(ej(nombre), s) == [] == comprobar_esquemas.validar(ej(nombre), s, s)
    roto = copy.deepcopy(ej(nombre))
    roto["clave_que_no_existe"] = True
    assert esquema.validar(roto, s) == comprobar_esquemas.validar(roto, s, s) != []


def test_esquema_casos_limite():
    s = {"type": ["string", "null"], "minLength": 30, "pattern": "^abc$"}
    assert esquema.validar(None, s) == []
    assert esquema.validar("abc\n", {"type": "string", "pattern": "^abc$"})  # $ final = \Z
    assert esquema.validar(True, {"type": "integer"}) and esquema.validar(1, {"const": True})
    assert esquema.validar(float("nan"), {"type": "number"})
    with pytest.raises(errores.ReglaIncumplida) as e:
        esquema.exigir({"schema": "x"}, "decision")
    assert len(e.value.errores) > 1  # todos los errores, no solo el primero
    with pytest.raises(errores.EntradaInvalida):
        esquema.cargar("../estado")


def test_marcadores_por_palabra_completa():
    assert textos_cliente.marcadores("Un verificador independiente. Todos los datos.") == []
    assert textos_cliente.marcadores("Queda pendiente") and textos_cliente.marcadores("TBD")
    assert textos_cliente.marcadores("valor <cliente>") and textos_cliente.marcadores("Por Definir")


def test_barrer_detecta_lo_que_no_ve_el_cliente():
    perfiles = ["Project Manager", "Consultor Junior"]
    for malo in ("24 h de trabajo", "3 jornadas", "65 €/h", "la tarifa", "Project Manager", "C-01",
                 "R-objetivo", "estado.json", "x@y.com", "catalogo_id", "contingencia del 15 %"):
        assert textos_cliente.barrer(malo, perfiles), malo
    limpio = "Precio cerrado de 17.852,50 €, IVA no incluido. https://learn.microsoft.com/azure/architecture/ai-ml/"
    assert textos_cliente.barrer(limpio, perfiles) == []


def test_componer_valida_y_esta_atado_a_los_hechos(contexto):
    est, cat, tar = contexto
    t = textos_cliente.componer(est, cat, tar)
    assert esquema.validar(t, esquema.cargar("textos_cliente")) == []
    assert t["hash_hechos"] == hashes.hash_json(pptx_revision.hechos_de(est["carga"]))
    assert t == textos_cliente.componer(copy.deepcopy(est), cat, tar)  # determinista
    assert t["condiciones"][0]["texto"] == "Precio cerrado de 28.025,25 €, IVA no incluido."
    nombres = {c["nombre"] for capa in t["arquitectura"]["capas"] for c in capa["componentes"]}
    oficiales = {c["nombre_oficial"] for c in cat["componentes"]}
    assert nombres <= oficiales  # LES-G-093: nunca un id convertido en nombre
    bajos = [s for s in t["supuestos"] if s["nivel"] == "Confianza baja"]
    # H10 (I1.1): la diapositiva 9 ya no repite los supuestos como riesgos.
    assert len(bajos) == 2 and not any(r["texto"].startswith("Supuesto sin confirmar") for r in t["riesgos"])
    assert not {s["texto"] for s in t["supuestos"]} & {r["texto"] for r in t["riesgos"]}


def test_componer_excluye_prosa_que_no_pasa(contexto):
    est, cat, tar = contexto
    resp = est["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    resp["riesgos"][0]["texto"] = "Riesgo de 40 horas de retraso."
    resp["supuestos"][0]["hechos"] = ["R-inventado"]
    t = textos_cliente.componer(est, cat, tar)
    motivos = {x["origen"]: x["motivo"] for x in textos_cliente.frases_excluidas(t)}
    assert "experto RG-01" in motivos and "horas" in motivos["experto RG-01"]
    assert "experto S-01" in motivos and all("40 horas" not in r["texto"] for r in t["riesgos"])


def test_componer_sin_hechos_es_integridad_rota(contexto):
    est, cat, tar = contexto
    est["carga"]["anexo_consumo"] = None
    with pytest.raises(errores.IntegridadRota):
        textos_cliente.componer(est, cat, tar)


def test_nombres_zip():
    n = paquete.nombres_zip("OF-KELVARA-001-A")
    assert len(n) == len(set(n)) == 9 and n[0] == "OF-KELVARA-001-A-Estimacion.xlsx" and n[-1] == "mensaje_aprobador.txt"


def test_punta_a_punta_local_con_verificar_paquete(tmp_path):
    """CLI real (subproceso) hasta paquete, decisiones, regeneración, restaurar y verificar_paquete rc 0."""
    from tests.evidencias import requerir
    requerir(RAIZ / "pruebas" / "I1" / "INTEGRACION" / "e2e_local.py")
    r = subprocess.run([sys.executable, str(RAIZ / "pruebas" / "I1" / "INTEGRACION" / "e2e_local.py"),
                        str(tmp_path / "e2e")], capture_output=True, text=True, encoding="utf-8", cwd=str(RAIZ))
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]
    assert "RESUMEN e2e: verificar aprobada+previo rc=0 · restaurado rc=0" in r.stdout


def test_esquema_con_palabra_no_admitida_falla_en_alto(tmp_path):
    (tmp_path / "raro.json").write_text(json.dumps({"type": "object", "oneOf": []}), encoding="utf-8")
    with pytest.raises(errores.IntegridadRota):
        esquema.cargar("raro", tmp_path)


def test_componer_rechaza_nombre_de_desviacion_que_no_pasa_el_barrido(contexto):
    est, cat, tar = contexto
    comp = next(c for c in est["carga"]["respuestas_expertos"]["azure"]["respuesta"]["componentes"] if c["id"] == "C-05")  # integrador I1.7: sin precios (C-01 lleva tokens con ciclo de vida)
    comp["catalogo_id"], comp["servicio"] = None, "Servicio propio de 40 horas"
    comp["desviacion_justificada"] = "Prueba"
    with pytest.raises(errores.ReglaIncumplida) as e:
        textos_cliente.componer(est, cat, tar)
    assert any("horas" in x for x in e.value.errores)


def test_limites_de_las_instrucciones_sincronizados_con_los_esquemas():
    from agentes.esquemas import limites
    assert limites.main(["--comprobar"]) == 0
    texto = (RAIZ / "agentes" / "instrucciones" / "experto_azure_i1.md").read_text(encoding="utf-8")
    assert "- `supuestos[].hechos`: entre 1 y 12 elementos." in texto.splitlines()


def test_desplegar_para_antes_de_publicar_si_la_identidad_del_coordinador_no_es_la_del_rol(monkeypatch):
    import desplegar

    class C:
        cfg = {"agentes": {"coordinador": {"nombre": "preventa-coordinador", "modelo": "gpt-6-luna"}}}
        publicado = False

        def obtener_agente(self, nombre):
            return {"versions": {"latest": {"instance_identity": {"principal_id": "otra"}}}}

    def no_publicar(*a, **k):
        C.publicado = True
        raise AssertionError("no debe publicar")
    monkeypatch.setattr(desplegar, "asegurar_con_respaldo", no_publicar)
    monkeypatch.setattr(desplegar, "INCREMENTO", "I1")
    with pytest.raises(desplegar.FalloDespliegue, match="PARA antes de publicar"):
        desplegar.paso_coordinador(C(), {}, [], {"coordinador": "gpt-6-luna"})
    assert not C.publicado


def test_nombres_de_subida_sin_guiones_bajos_repetidos(tmp_path, monkeypatch):
    import desplegar
    from tests.evidencias import requerir
    requerir(RAIZ / "salidas" / "rate-card.json", activo=True)   # desplegar monta la tarifa real
    # REVER-3: nunca sobre la ruta real salidas/montaje_I1 (la borra y la rehace con el núcleo del árbol)
    monkeypatch.setattr(desplegar, "MONTAJE_I1", tmp_path / "montaje_I1")
    nombres = [n for n, _, _ in desplegar.ficheros_coordinador_i1([])]
    assert (tmp_path / "montaje_I1" / "nucleo_init.py").is_file()
    assert not [n for n in nombres if "__" in n] and "nucleo_init.py" in nombres and "esquema_estado.json" in nombres
