"""Notas del comercial como fuente de requisitos (decisión del comercial, 04-11-2026; esquemas/NOTAS_COMERCIAL.md). Sin red.

Paquetes REALES del núcleo vigente (tests/fixtures_i1/paquete_real.py) con las notas como única fuente, y con
transcripción y notas a la vez; la puerta los comprueba con su copia local (--notas). Las notas sintéticas son el mismo
texto sintético de la transcripción de I1 copiado como notas: así las citas de esquemas/ejemplos valen literal.
"""
from __future__ import annotations

import json
import pathlib
import zipfile

import pytest

import verificar_paquete as vp
from tests.fixtures_i1 import paquete_real

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CATALOGO = RAIZ / "sandbox" / "datos" / "catalogo_componentes.json"
AVISO = "Sin grabación: los requisitos salen de las notas del comercial; revisa con él lo que no esté escrito."
NOTAS = "notas_comercial.txt"
NOTAS_EXTRA = ("Notas del comercial tras la reunión: el cliente insiste en que la primera fase llegue antes del "
               "verano y pide una demostración con sus informes reales.\n")


class FlujoNotas(paquete_real.Flujo):
    """El Flujo real con notas del comercial: solas (sin grabación) o junto a la transcripción."""

    def __init__(self, base: pathlib.Path, con_transcripcion: bool):
        super().__init__(base)
        texto = paquete_real.TRANSCRIPCION.read_text(encoding="utf-8")
        (self.datos / NOTAS).write_text(texto if not con_transcripcion else NOTAS_EXTRA, encoding="utf-8")
        real = self.P

        class Api:
            def __getattr__(self, nombre):
                return getattr(real, nombre)

            def iniciar(self, env, **kw):
                if not con_transcripcion:
                    kw.pop("transcripcion")
                return real.iniciar(env, notas_comercial=NOTAS, **kw)
        self.P = Api()


@pytest.fixture(scope="module")
def solo_notas(tmp_path_factory):
    flujo = FlujoNotas(tmp_path_factory.mktemp("solo_notas"), con_transcripcion=False)
    return flujo, flujo.hasta_lista()


@pytest.fixture(scope="module")
def con_las_dos(tmp_path_factory):
    flujo = FlujoNotas(tmp_path_factory.mktemp("con_las_dos"), con_transcripcion=True)
    return flujo, flujo.hasta_lista()


def _verificar(capsys, paquete, *fuentes):
    rc = vp.main([str(paquete), *fuentes, "--catalogo", str(CATALOGO), "--sin-red"])
    return rc, capsys.readouterr().out


def _miembros(paquete) -> dict[str, bytes]:
    with zipfile.ZipFile(paquete) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def _textos_docx(datos: bytes) -> list[str]:
    import io

    import docx
    return [p.text for p in docx.Document(io.BytesIO(datos)).paragraphs] + [
        c.text for t in docx.Document(io.BytesIO(datos)).tables for f in t.rows for c in f.cells]


def _texto_pptx(datos: bytes) -> str:
    import io

    from pptx import Presentation
    return "\n".join(s.text_frame.text for d in Presentation(io.BytesIO(datos)).slides for s in d.shapes
                     if s.has_text_frame)


def test_solo_notas_fuente_f1_y_aviso_en_lo_interno(solo_notas):
    flujo, paquete = solo_notas
    est = flujo.estado()
    assert [(f["id"], f["tipo"], f["nombre"]) for f in est["carga"]["fuentes"]] == [("F1", "NOTAS_COMERCIAL", NOTAS)]
    m = _miembros(paquete)
    codigo = est["codigo"]
    nota = _textos_docx(m[f"{codigo}-Nota-Revision.docx"])
    assert nota.count(AVISO) == 1
    assert any("CITADO (notas del comercial)" == t for t in nota)
    assert any(t.startswith("Frases de las notas del comercial con forma de requisito") for t in nota)
    assert f"IMPORTANTE. {AVISO}" in m["mensaje_revisor.txt"].decode("utf-8").splitlines()
    pptx = _texto_pptx(next(v for k, v in m.items() if k.endswith(".pptx"))).lower()
    assert "grabación" not in pptx and "notas del comercial" not in pptx   # lo interno no llega al cliente (I1.8)


def test_la_puerta_acepta_el_paquete_de_solo_notas_con_su_copia_local(capsys, solo_notas):
    flujo, paquete = solo_notas
    rc, out = _verificar(capsys, paquete, "--notas", str(flujo.datos / NOTAS))
    assert rc == 0, out
    rc, out = _verificar(capsys, paquete, "--transcripcion", str(paquete_real.TRANSCRIPCION))
    assert rc == 1 and "no se ha dado su copia local (--notas)" in out, out


def test_la_puerta_rechaza_notas_alteradas_o_sin_aviso(capsys, solo_notas, tmp_path):
    flujo, paquete = solo_notas
    otras = tmp_path / NOTAS
    otras.write_text((flujo.datos / NOTAS).read_text(encoding="utf-8") + "\nUna línea añadida después.\n",
                     encoding="utf-8")
    rc, out = _verificar(capsys, paquete, "--notas", str(otras))
    assert rc == 1 and "las notas del comercial locales" in out, out
    m = _miembros(paquete)
    roto = tmp_path / "roto.zip"
    with zipfile.ZipFile(roto, "w") as zf:
        for n, b in m.items():
            if n == "mensaje_revisor.txt":
                b = b.decode("utf-8").replace(f"IMPORTANTE. {AVISO}\n", "").encode("utf-8")
            zf.writestr(n, b)
    rc, out = _verificar(capsys, roto, "--notas", str(flujo.datos / NOTAS))
    assert rc == 1 and "mensaje al responsable de preventa: sin grabación y sin el aviso" in out, out


def test_cita_que_no_esta_en_las_notas_no_pasa_la_suficiencia(tmp_path):
    flujo = FlujoNotas(tmp_path, con_transcripcion=False)
    P, e = flujo.P, flujo.env
    r = P.iniciar(e, cliente="Kelvara Ensayos Industriales, S.A.", codigo_cliente="KELVARA", seqof="001",
                  titulo="Asistente de prueba", transcripcion="x", sensibles=paquete_real.SENSIBLES, nda_confirmado=True)
    assert r.ok, r.salida
    assert "AVISO: " + AVISO in r.salida
    req = json.loads((paquete_real.EJ / "requisitos.json").read_text(encoding="utf-8"))
    for c in ("volumetria", "identidad_acl_origen"):
        req["campos"][c] = {"estado": "FALTA", "entradas": []}
    req["campos"]["objetivo"]["entradas"][0]["cita"] = "Esta frase no la escribió el comercial en ningún sitio."
    r = P.suficiencia(e, requisitos=flujo.entrada("requisitos.json", req))
    assert not r.ok and "no está literal en F1" in r.salida, r.salida


def test_con_las_dos_cada_requisito_dice_su_procedencia(capsys, con_las_dos):
    flujo, paquete = con_las_dos
    est = flujo.estado()
    assert [f["tipo"] for f in est["carga"]["fuentes"]] == ["TRANSCRIPCION", "NOTAS_COMERCIAL"]
    m = _miembros(paquete)
    nota = _textos_docx(m[f"{est['codigo']}-Nota-Revision.docx"])
    assert "CITADO (reunión)" in nota and AVISO not in nota
    assert AVISO not in m["mensaje_revisor.txt"].decode("utf-8")
    rc, out = _verificar(capsys, paquete, "--transcripcion", str(paquete_real.TRANSCRIPCION),
                         "--notas", str(flujo.datos / NOTAS))
    assert rc == 0, out


def test_las_notas_se_anonimizan_en_el_brief(solo_notas):
    flujo, _ = solo_notas
    brief = next((flujo.trabajo / "briefs").glob("*.txt")).read_text(encoding="utf-8")
    for termino in paquete_real.SENSIBLES:
        assert termino not in brief, termino


@pytest.mark.parametrize("kw, motivo", [({}, "falta la fuente"), ({"notas_comercial": "cortas.txt"}, "entre 40 y 20000")])
def test_alta_sin_fuente_o_con_notas_fuera_de_limites(tmp_path, kw, motivo):
    import sys
    sys.path.insert(0, str(RAIZ / "sandbox"))
    import preventa_api as P
    datos = tmp_path / "datos"
    datos.mkdir()
    (datos / "cortas.txt").write_text("Quiere un bot.", encoding="utf-8")
    env = P.abrir(str(tmp_path / "trabajo"), datos=str(datos), tmp=str(tmp_path / "tmp"), montaje="exacto")
    r = P.iniciar(env, cliente="Kelvara", codigo_cliente="KELVARA", seqof="001", titulo="Asistente de prueba",
                  sensibles=["Kelvara"], nda_confirmado=True, **kw)
    assert r.rc == 2 and r.estado is None and motivo in r.salida, r.salida


def test_puerta_sin_ninguna_fuente_es_entrada_ilegible(capsys, solo_notas):
    _, paquete = solo_notas
    rc, out = _verificar(capsys, paquete)
    assert rc == 2 and "falta la fuente" in out

