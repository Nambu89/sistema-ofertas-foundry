"""P4 de I1.4: EA-1 (paso al empezar un turno), EA-5 (relevo en JSON sueltos), EA-6 (arranque que nombra lo que
falta y `entorno` sin núcleo) y EB-4 (Microsoft 365 no es una nube de despliegue). Sin red; dobles de B, C y D."""
from __future__ import annotations

import json
import pathlib

import pytest

from tests.test_i1_estado_comun import Mundo, ejemplo, estado
from tests.test_i1_restaurar_relevo import F, contenedor_nuevo, miembros

import preventa_run as PR  # noqa: E402  (sandbox/ ya está en sys.path)
from nucleo import hashes, suficiencia  # noqa: E402

RAIZ = pathlib.Path(__file__).resolve().parents[1]
REL_A = "OF-KELVARA-001-A-Relevo.zip"


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


# ── EA-1 ────────────────────────────────────────────────────────────────────────────────────────
def test_turno_nuevo_reescribe_el_paso_sin_mutar_nada(m):
    m.hasta_analisis()
    assert m.run("enrutar")[0] == 0
    r = m.entrada("respuesta_experto_AZ_R1.json", ejemplo("respuesta_experto"))
    rc, out = m.run("registrar-experto", "--experto", "azure", "--respuesta", r)
    assert rc == 0 and "SIGUIENTE PASO OBLIGATORIO: Terminar el turno. En el siguiente: consolidar" in out
    antes = (m.raiz / "estado.json").read_bytes()
    rc, out = m.run("estado", "--turno-nuevo")
    assert rc == 0 and f"SIGUIENTE PASO OBLIGATORIO: consolidar{estado.TURNO_NUEVO}" in out
    assert "Terminar el turno" not in out and (m.raiz / "estado.json").read_bytes() == antes
    assert "SIGUIENTE PASO OBLIGATORIO: Terminar el turno. En el siguiente: consolidar" in m.run("estado")[1]


@pytest.mark.parametrize("paso, esperado", [
    ("Terminar el turno. En el siguiente: anexo-consumo", f"anexo-consumo{estado.TURNO_NUEVO}"),
    (f"{estado.PREFIJO_RECHAZO} (T1 intento 1/3), sin un segundo intento en este turno. {estado.CON_SU_RESPUESTA}"
     "Rellenar entrada/requisitos.json", f"{estado.CON_LA_RESPUESTA}Rellenar entrada/requisitos.json"),
    (f"{estado.PREFIJO_RECHAZO} (T1 intento 2/3), sin un segundo intento en este turno. {estado.CON_SU_RESPUESTA}"
     "Presentar al comercial las preguntas a/b/c/d y terminar el turno. Con su respuesta: asumir",
     f"{estado.CON_LA_RESPUESTA}asumir. Si no responde a las preguntas, presentarlas otra vez y terminar el turno"),
    ("enrutar", "enrutar"), ("paquete", "paquete"), ("Parar. Motivo: x", "Parar. Motivo: x"),
])
def test_paso_turno_nuevo(paso, esperado):
    assert estado.paso_turno_nuevo(paso) == esperado


def test_paso_de_estimar_ya_no_pide_escribir_el_json():
    assert estado.PASO_ESTIMAR.startswith("estimar") and "no se escribe a mano" in estado.PASO_ESTIMAR


# ── EA-5 ────────────────────────────────────────────────────────────────────────────────────────
def _relevo(m) -> dict[str, bytes]:
    """Relevo sin pasar por la verificación (cuyo ejemplo cambia en esta tanda): BLOQUEADA y DESBLOQUEAR."""
    assert m.iniciar()[0] == 0
    for _ in range(3):
        m.run("registrar-fallo", "--fase", "T1", "--error", "HTTP 424 de prueba", "--hipotesis", "corte de prueba")
    assert m.run("decision", "--linea", m.linea(F, "DESBLOQUEAR", "Reanudar tras revisar el fallo de prueba"))[0] == 0
    return miembros(m.raiz / "salida" / REL_A)


def test_restaurar_con_estado_y_relevo_sueltos(m, tmp_path, monkeypatch):
    cont, h = _relevo(m), m.hash()
    contenedor_nuevo(m, tmp_path, monkeypatch, {n: cont[n] for n in ("estado.json", "relevo.json")})
    rc, out = m.run("restaurar", "--estado", "estado.json", "--relevo", "relevo.json")
    assert rc == 0 and "el relevo relevo.json" in out and m.hash() == h and "decisiones: 1" in out, out
    assert (m.raiz / "estado.json").read_bytes() == cont["estado.json"]


@pytest.mark.parametrize("estropear, motivo", [
    ("estado", "SHA-256 de estado.json"), ("relevo_sin_estado", "no lista estado.json"),
    ("forma", "no tiene la forma esperada"), ("decisiones", "decisiones (última"),
])
def test_restaurar_sueltos_rechaza_sin_escribir(m, tmp_path, monkeypatch, estropear, motivo):
    cont = _relevo(m)
    rel = json.loads(cont["relevo.json"])
    adj = {"estado.json": cont["estado.json"], "relevo.json": cont["relevo.json"]}
    if estropear == "estado":
        adj["estado.json"] = cont["estado.json"] + b"\n"  # JSON válido, otros bytes
    elif estropear == "relevo_sin_estado":
        rel["ficheros"] = [dict(f, nombre="otro.json") if f["nombre"] == "estado.json" else f for f in rel["ficheros"]]
    elif estropear == "forma":
        rel["sobra"] = 1
    elif estropear == "decisiones":
        rel["decisiones"] = 2
    if estropear != "estado":
        adj["relevo.json"] = json.dumps(rel).encode("utf-8")
    contenedor_nuevo(m, tmp_path, monkeypatch, adj)
    rc, out = m.run("restaurar", "--estado", "estado.json", "--relevo", "relevo.json")
    assert rc == 4 and motivo in out, out
    assert not (m.raiz / "estado.json").exists()


def _completar_campo(obj) -> None:
    """Pone «campo»: «ninguno» a los elementos del verificador que no lo traen (forma vigente del esquema)."""
    if isinstance(obj, dict):
        if "veredicto" in obj and "tipo" in obj:
            obj.setdefault("campo", "ninguno")
        if "catalogo_id" in obj and "desviacion_justificada" in obj:  # I1.5: componente del experto, contrato v2
            obj.setdefault("motivo_no_valoracion", "no_aplica")
            obj.setdefault("justificacion_nivel", None)  # I1.6: contrato v3
        if "filtro" in obj and "cantidad_mensual" in obj and "moneda" in obj:  # I1.6: precio del experto (v3)
            obj.setdefault("base_volumen", None)
        for v in obj.values():
            _completar_campo(v)
        az = (obj.get("respuestas_expertos") or {}).get("azure") if isinstance(obj.get("respuestas_expertos"), dict) else None
        if isinstance(az, dict) and isinstance(az.get("respuesta"), dict) and "valoracion_nucleo" not in az["respuesta"]:
            _a_i17(obj, az)  # integrador I1.7: la forma vigente de lo que guarda el núcleo es la completada (v4)
        herr = ((obj.get("verificacion") or {}).get("respuesta") or {}).get("herramientas_usadas") \
            if isinstance(obj.get("verificacion"), dict) else None
        if isinstance(herr, dict):
            herr.pop("precios_azure", None)  # I1.7: el verificador ya no tiene herramienta de precios
        consumo = (obj.get("textos_cliente") or {}).get("consumo") if isinstance(obj.get("textos_cliente"), dict) else None
        if isinstance(consumo, dict) and isinstance(consumo.get("fuente"), str):  # I1.7: «precios consultados el»
            import re as _re
            consumo["fuente"] = _re.sub(r", (regi(?:ón|ones) .+), precios vigentes desde (\S+), consultados el (\S+)$",
                                        r", \1: precios consultados el \3, vigentes desde \2", consumo["fuente"])
    elif isinstance(obj, list):
        for v in obj:
            _completar_campo(v)


def _a_i17(carga: dict, az: dict) -> None:
    """Integrador I1.7: convierte la respuesta guardada (v3) en la que guardaría el núcleo con el contrato v4: lo que
    habría escrito el modelo (tests.i17_int.a_v4) completado desde el catálogo real y su instantánea."""
    import json as _json
    from tests import i17_int
    cat = _json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
    brief = next((b for b in carga.get("briefs") or [] if b.get("brief_id") == az.get("brief_id")), {})
    for b in carga.get("briefs") or []:
        for k in ("conservar", "conservar_precios", "aceptados"):
            b.setdefault(k, [])
        b["conservar_precios"] = [x for x in b["conservar_precios"] if isinstance(x, dict) and "precio_ids" in x]
    # integrador I1.9: y después a la forma v5 (sin motivo_cita, con existente_del_cliente; i17_int.a_v5)
    r = i17_int.completar(i17_int.a_v5(i17_int.a_v4(az["respuesta"], cat), cat), cat, carga.get("requisitos"),
                          brief.get("texto"))
    r["precios"] = [p for p in r["precios"] if "filtro" in p]  # los de I1.3 sin plantilla del catálogo v5 no se completan
    az["respuesta"] = r
    az.pop("ajustes_nucleo", None)


def _relevo_brezalia(tmp_path) -> dict[str, bytes]:
    """Relevo compuesto por el núcleo con el estado y los económicos REALES del paquete de Brezalia de B."""
    import io
    import zipfile
    from nucleo import restaurar
    with zipfile.ZipFile(RAIZ / "pruebas/I13/ARREGLOS/REAL_B/descargas/OF-BREZALIA-001-A-Paquete.zip") as z:
        paq = {i.filename: z.read(i) for i in z.infolist()}
    (tmp_path / "salida").mkdir()
    for n, b in paq.items():
        if "-Estimacion." in n or "-Anexo-Consumo." in n:
            (tmp_path / "salida" / n).write_bytes(b)
    est = json.loads(paq["estado.json"])
    _completar_campo(est)  # el esquema del verificador gana «campo» en esta tanda (otro papel); el resto, real
    est["hash_contenido"] = hashes.hash_contenido(est)
    rel = restaurar.componer_relevo(est, tmp_path)
    with zipfile.ZipFile(io.BytesIO(rel["zip"])) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def test_sueltos_recuperan_los_economicos_adjuntos_y_declaran_los_demas(tmp_path):
    from nucleo import restaurar
    cont = _relevo_brezalia(tmp_path)
    xlsx = "OF-BREZALIA-001-A-Estimacion.xlsx"
    est, extras, omitidos = restaurar.leer_sueltos(cont["estado.json"], cont["relevo.json"], {xlsx: cont[xlsx]})
    assert est["codigo"] == "OF-BREZALIA-001-A" and extras == {f"salida/{xlsx}": cont[xlsx]}
    assert sorted(omitidos) == [f"OF-BREZALIA-001-A-Anexo-Consumo.{e}: no adjuntado (lo lista relevo.json)"
                                for e in ("json", "xlsx")]
    with pytest.raises(restaurar.IntegridadRota) as e:
        restaurar.leer_sueltos(cont["estado.json"], cont["relevo.json"], {xlsx: cont[xlsx] + b"x"})
    assert any("distinto del de relevo.json" in x for x in e.value.errores)
    with pytest.raises(restaurar.IntegridadRota, match="no lista"):
        restaurar.leer_sueltos(cont["estado.json"], cont["relevo.json"], {"otro.txt": b"x"})


@pytest.mark.parametrize("args", [["--relevo", "relevo.json"], ["--estado", "e", "--relevo", "r", "--manifiesto", "m"],
                                  ["--zip", "x.zip", "--relevo", "r"]])
def test_restaurar_sueltos_exige_una_forma(m, args):
    rc, out = m.run("restaurar", *args)
    assert rc == 2 and "--relevo relevo.json" in out


# ── EA-6 ────────────────────────────────────────────────────────────────────────────────────────
def _sandbox_roto(monkeypatch, tmp_path, p0):
    monkeypatch.setenv("PREVENTA_DATOS", str(tmp_path))
    monkeypatch.setenv("PREVENTA_TMP", str(tmp_path / "tmp"))
    monkeypatch.setattr(PR, "es_local", lambda: False)
    monkeypatch.setattr(PR, "preparar_sandbox", lambda datos, app: list(p0))
    monkeypatch.setattr(PR, "_nucleo", lambda env=None: (_ for _ in ()).throw(AssertionError("importó el núcleo")))


def test_falta_un_modulo_se_nombra_antes_de_importar(monkeypatch, tmp_path, capsys):
    _sandbox_roto(monkeypatch, tmp_path, ["nucleo_estado.py: montado 0 veces", "rate-card.json: montado 0 veces"])
    assert PR.main(["estado"]) == 4
    out = capsys.readouterr().out
    assert "faltan o no coinciden con el manifiesto: nucleo_estado.py" in out and "SIN_NUCLEO" in out


def test_entorno_no_importa_el_nucleo(monkeypatch, tmp_path, capsys):
    _sandbox_roto(monkeypatch, tmp_path, ["FALTA_NUCLEO nucleo_brief.py: no está en la copia del núcleo (x)"])
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    assert PR.main(["entorno"]) == 4
    out = capsys.readouterr().out
    assert "P0 MONTAJE: ROTO" in out and "MÓDULOS DEL NÚCLEO QUE FALTAN O NO COINCIDEN: nucleo_brief.py" in out and "a.txt" in out
    assert "estado: NO_CONSULTADO" in out and "SIGUIENTE PASO OBLIGATORIO: parar y avisar al comercial" in out


def test_copia_del_nucleo_frente_al_manifiesto(tmp_path):
    (tmp_path / "estado.py").write_text("x", encoding="utf-8")
    fich = {"nucleo_estado.py": {"sha256": "0" * 64}, "nucleo_init.py": {"sha256": "1" * 64}, "otro.json": {}}
    errores = PR.errores_copia_nucleo(tmp_path, fich)
    assert errores[0].startswith("nucleo_estado.py: la copia") and errores[1].startswith("FALTA_NUCLEO nucleo_init.py")
    assert PR.faltan_del_nucleo(errores) == ["nucleo_estado.py", "nucleo_init.py"]


# ── EB-4 ────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("valor", ["Microsoft 365", "Office 365", "M365", "Azure y Microsoft 365"])
def test_m365_se_rechaza_con_su_motivo(valor):
    motivos = suficiencia.nubes_fuera_de_i1([valor])
    assert len(motivos) == 1 and "no una nube de despliegue" in motivos[0] and "canales_integraciones" in motivos[0]
    assert suficiencia.nubes_fuera_de_i1(["Azure"]) == []


def test_modelo_de_b_explica_que_m365_no_es_nube():
    texto = (RAIZ / "hosted" / "preventa_hosted" / "modelo.py").read_text(encoding="utf-8")
    assert "MICROSOFT 365 NO ES UNA NUBE DE DESPLIEGUE" in texto and "canales_integraciones" in texto


@pytest.mark.parametrize("p0", [["nucleo_estado.py: SHA-256 abc distinto del manifiesto def"],
                                ["nucleo_brief.py: la copia x tiene SHA-256 abc, distinto del manifiesto"],
                                ["nucleo_hashes.py: montado 2 veces"]])
def test_modulo_que_no_coincide_tampoco_se_importa(monkeypatch, tmp_path, capsys, p0):
    """Revisión (I1.4): con un módulo del núcleo distinto del manifiesto no se ejecuta su código; se nombra y para."""
    _sandbox_roto(monkeypatch, tmp_path, p0)
    assert PR.main(["estado"]) == 4
    out = capsys.readouterr().out
    assert "faltan o no coinciden con el manifiesto: nucleo_" in out and "SIN_NUCLEO" in out


def test_solo_los_modulos_del_nucleo_impiden_importar():
    """Un módulo fuera del manifiesto también para (Revisión, 2.ª pasada); un fichero que no es código, no."""
    assert PR.faltan_del_nucleo(["generar_estimacion.py: SHA-256 a distinto del manifiesto b",
                                 "x-nucleo_intruso.py: módulo del núcleo montado que no está en el manifiesto",
                                 "assistant-Q-nucleo_extra-mod.py: módulo del núcleo montado que no está en el manifiesto",
                                 "nucleo_a b.py: SHA-256 a distinto del manifiesto b",
                                 "manifiesto.json montado 2 veces"]) == ["x-nucleo_intruso.py",
                                                                         "assistant-Q-nucleo_extra-mod.py", "nucleo_a b.py"]
