"""I1.3, previo (09-10-2026): REVPR-1, REVPR-2 y REVPR-3 de pruebas/I12/REVERIFICACION-PRECIO.md.

REVPR-1: la comprobación `experto` de la puerta falla con ids repetidos con el motivo del núcleo y recorre las listas.
REVPR-3: los seis os.replace de nucleo/anexo_consumo.py usan el reintento acotado y anotado de estado (ARRSN-1).
REVPR-2 (bytes de control en las evidencias de pruebas/) no se publica: esas evidencias tampoco.
"""
from __future__ import annotations

import ast
import copy
import datetime as dt
import hashlib
import pathlib
import re
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
sys.path.insert(0, str(RAIZ))
from nucleo import anexo_consumo  # noqa: E402
from nucleo import estado as est_mod  # noqa: E402
from nucleo import experto  # noqa: E402
import verificar_paquete as V  # noqa: E402
from tests.test_i1_estado_comun import ejemplo  # noqa: E402
from tests.test_i12_arreglos_precio import CAT, SW, _replace_que_falla, windows  # noqa: E402,F401
from tests import i17_int  # noqa: E402  (integrador I1.7: validar_respuesta con la instantánea de precios)


def _juzgar(mutar=None):
    """(detalles de la comprobación `experto` de la puerta, errores de nucleo.experto) sobre la misma respuesta."""
    resp, br = ejemplo("respuesta_experto"), ejemplo("brief")
    if mutar:
        mutar(resp)
    br["sha256"] = hashlib.sha256(br["texto"].encode("utf-8")).hexdigest()
    hechos = {h[2:] for x in resp["supuestos"] + resp["riesgos"] for h in x["hechos"] if h.startswith("R-")}
    ctx = V.Contexto(None, RAIZ, {}, RAIZ, RAIZ, RAIZ, RAIZ, None, True, dt.date(2026, 10, 9), RAIZ)
    ctx.catalogo_obj, ctx.tarifa = CAT, {"perfiles": [{"nombre": p} for p in br["perfiles_permitidos"]]}
    # integrador I1.7: la puerta juzga lo que guarda el núcleo (la respuesta completada), no lo que escribió el modelo
    guardada = i17_int.completar(resp, CAT, None, br["texto"])
    ctx.estado = {"carga": {"briefs": [br], "requisitos": {"campos": {k: "x" for k in hechos}},
                            "estimacion": {"entrada": {"fecha": "2026-10-09"}},  # I1.7: ciclo de vida del modelo
                            "respuestas_expertos": {"azure": {"brief_id": br["brief_id"], "respuesta": guardada}}}}
    c = V.c_experto(ctx)
    return c, i17_int.validar(resp, br, CAT, br["perfiles_permitidos"])


def test_control_sin_repetidos_pasa_en_las_dos_capas():
    c, errores = _juzgar()
    assert c.estado != V.FALLA and errores == [], (c.detalles, errores)


def test_c02_repetido_en_swedencentral_delante_del_original_falla_por_si_mismo():
    def a14(r):
        comp = next(x for x in r["componentes"] if x["id"] == "C-02")
        r["componentes"].insert(0, dict(copy.deepcopy(comp), region=SW))
    c, errores = _juzgar(a14)
    assert c.estado == V.FALLA and "componentes: id repetido C-02" in c.detalles, c.detalles
    assert any(d.startswith("C-02: ") and d.endswith("(VERIF-3)") for d in c.detalles), c.detalles  # la copia vetada
    assert "componentes: id repetido C-02" in errores


@pytest.mark.parametrize("bloque", ["referencias", "precios", "tareas_propuestas", "supuestos", "riesgos"])
def test_ids_repetidos_con_el_motivo_del_nucleo(bloque):
    ident = ejemplo("respuesta_experto")[bloque][0]["id"]
    c, errores = _juzgar(lambda r: r[bloque].append(copy.deepcopy(r[bloque][0])))
    motivo = f"{bloque}: id repetido {ident}"
    assert motivo in c.detalles and motivo in errores, (c.detalles, errores)


def test_flujo_con_un_extremo_inexistente_falla_como_en_el_nucleo():
    c, errores = _juzgar(lambda r: r["flujos"].append({"origen": "C-99", "destino": "C-01", "descripcion": "Prueba"}))
    assert "flujos: origen C-99 no es un componente" in c.detalles and "flujos: origen C-99 no es un componente" in errores


def test_ids_repetidos_admite_ids_no_hashables_y_de_otro_tipo():
    assert V.ids_repetidos([{"id": ["x"]}, {"id": ["x"]}, {"id": 3}, {"id": "3"}], "b") == ["b: id repetido ['x']"]
    assert V.ids_repetidos(None, "b") == [] and V.ids_repetidos([{"id": "a"}], "b") == []


# ── REVPR-3 ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_anexo_sin_os_replace_directo_y_seis_llamadas_al_reintento():
    arbol = ast.parse((RAIZ / "sandbox/nucleo/anexo_consumo.py").read_text(encoding="utf-8"))
    llamadas = [n.func for n in ast.walk(arbol) if isinstance(n, ast.Call)]
    directos = [f for f in llamadas if isinstance(f, ast.Attribute) and f.attr == "replace"
                and isinstance(f.value, ast.Name) and f.value.id == "os"]
    propias = [f for f in llamadas if isinstance(f, ast.Name) and f.id == "_reemplazar"]
    assert directos == [] and len(propias) == 6


def test_anexo_replace_denegado_dos_veces_se_reintenta_y_se_anota(windows, monkeypatch, tmp_path, capsys):
    llamadas: list = []
    monkeypatch.setattr(est_mod.os, "replace", _replace_que_falla(2, llamadas))
    anexo_consumo._escribir_atomico(tmp_path / "anexo.json", b"{}\n")
    assert (tmp_path / "anexo.json").read_bytes() == b"{}\n" and len(llamadas) == 3
    assert len(est_mod.REINTENTOS_REPLACE) == 2 and capsys.readouterr().err.count("AVISO: os.replace denegado") == 2
    assert [p.name for p in tmp_path.iterdir()] == ["anexo.json"]


def test_anexo_replace_denegado_siempre_no_se_oculta(windows, monkeypatch, tmp_path):
    monkeypatch.setattr(est_mod.os, "replace", _replace_que_falla(99, []))
    with pytest.raises(PermissionError) as e:
        anexo_consumo._escribir_atomico(tmp_path / "anexo.json", b"{}\n")
    assert any("6 veces seguidas" in n for n in getattr(e.value, "__notes__", [])) and list(tmp_path.iterdir()) == []
