"""I1.5 · R · PR14-6: tras una DEVUELTA, el brief de la versión siguiente lleva los comentarios de la decisión.

Con el núcleo real en proceso (Mundo de tests/test_i1_estado_comun.py). Casos adversos: el comentario con el nombre
del cliente o un correo sale anonimizado; la versión A no lleva sección; una DEVUELTA de otra versión no cuenta; un
brief guardado antes de I1.5 (sin la sección) se respeta y uno con otro texto sigue siendo IntegridadRota.
"""
from __future__ import annotations

import copy

import pytest

from tests.test_i1_estado_comun import Mundo

F, J, JP = "Responsable comercial", "Responsable de preventa", "Responsable de área"
CAB = "## Comentarios de la revisión de la versión A (DEVUELTA"


@pytest.fixture
def m(tmp_path, monkeypatch):
    return Mundo(tmp_path, monkeypatch)


def _devolver(m, comentario: str, quien: str = J) -> None:
    m.hasta_lista()
    assert m.run("decision", "--linea", m.linea(F, "ENVIADA_REVISION", "verificar_paquete rc=0"))[0] == 0
    if quien == JP:
        assert m.run("decision", "--linea", m.linea(J, "APROBADA", "ok"))[0] == 0
    rc, out = m.run("decision", "--linea", m.linea(quien, "DEVUELTA", comentario))
    assert rc == 0 and "codigo: OF-KELVARA-001-B" in out, out


def test_comentarios_devuelta_solo_de_la_version_anterior():
    from nucleo import decision
    dec = [{"id": "D-001", "tipo": "ENVIADA_REVISION", "version": "A", "revisor": F, "comentarios": "rc=0"},
           {"id": "D-002", "tipo": "DEVUELTA", "version": "A", "revisor": J, "comentarios": "uno"},
           {"id": "D-003", "tipo": "DEVUELTA", "version": "B", "revisor": JP, "comentarios": "dos"}]
    assert decision.comentarios_devuelta({"version": "A", "decisiones": dec}) == []
    assert [d["comentarios"] for d in decision.comentarios_devuelta({"version": "B", "decisiones": dec})] == ["uno"]
    assert [d["comentarios"] for d in decision.comentarios_devuelta({"version": "C", "decisiones": dec})] == ["dos"]
    for v in ("", "AB", "a", None, 3):
        assert decision.comentarios_devuelta({"version": v, "decisiones": dec}) == []


def test_el_brief_de_la_version_b_lleva_el_comentario_anonimizado(m):
    _devolver(m, "Kelvara pide revisar la diapositiva 8; dudas a ana.ruiz@kelvara.es; falta el precio de AI Search",
              quien=JP)
    rc, out = m.run("enrutar")
    assert rc == 0 and "BRF-OF-KELVARA-001-B-AZ-R1" in out, out
    b = m.estado()["carga"]["briefs"][-1]
    assert b["brief_id"] == "BRF-OF-KELVARA-001-B-AZ-R1"
    lineas = b["texto"].split("\n")
    i = next(k for k, ln in enumerate(lineas) if ln.startswith(CAB))
    assert lineas[i + 1] == "- [CLIENTE] pide revisar la diapositiva 8; dudas a [CORREO]; falta el precio de AI Search"
    assert "kelvara" not in b["texto"].split("---", 1)[1].lower() and "@" not in b["texto"]
    primero = m.estado()["carga"]["briefs"][0]
    assert primero["version"] == "A" and CAB not in primero["texto"]           # la versión A no lleva sección


def test_regenerar_es_idempotente_y_respeta_un_brief_anterior_a_i15(m):
    from nucleo import brief
    _devolver(m, "Revisar el precio del índice de búsqueda, que no aparece")
    assert m.run("enrutar")[0] == 0
    est = m.estado()
    b = est["carga"]["briefs"][-1]
    assert brief.generar(copy.deepcopy(est), b["perfiles_permitidos"], b["catalogo_sha256"]).texto == b["texto"]
    # un brief de la versión B guardado antes de PR14-6 (sin la sección): se respeta, es lo que ya se envió
    viejo = copy.deepcopy(est)
    vb = viejo["carga"]["briefs"][-1]
    lineas = vb["texto"].split("\n")
    i = next(k for k, ln in enumerate(lineas) if ln.startswith(CAB))
    # Arreglos I1.7 (PR17-6): antes de PR14-6 tampoco había «Propuesta de la versión A devuelta», que va detrás
    n = 1 + len(brief.lineas_propuesta_devuelta(est)) if lineas[i + 2].startswith("## Propuesta de la versión") else 0
    sin = lineas[:i] + lineas[i + 2 + n:]
    cab, cuerpo = "\n".join(sin).split("\n---\n", 1)
    from nucleo import hashes
    cab = "\n".join(x if not x.startswith("sha256_cuerpo: ") else f"sha256_cuerpo: {hashes.sha256_texto(cuerpo)}"
                    for x in cab.split("\n"))
    vb["texto"] = cab + "\n---\n" + cuerpo
    assert brief.generar(viejo, vb["perfiles_permitidos"], vb["catalogo_sha256"]).texto == vb["texto"]
    # y uno con otro texto sigue sin aceptarse
    otro = copy.deepcopy(est)
    otro["carga"]["briefs"][-1]["texto"] += "\n- añadido"
    from nucleo.errores import IntegridadRota
    with pytest.raises(IntegridadRota, match="otro texto"):
        brief.generar(otro, b["perfiles_permitidos"], b["catalogo_sha256"])


def test_la_puerta_recompone_el_comentario_anonimizado_y_detecta_el_cambiado(m):
    """Revisión (I1.5): la puerta no se conforma con que haya una línea: recompone la del núcleo y la compara."""
    import hashlib
    import types

    import verificar_paquete as vp
    from tests.test_i1_estado_comun import TRANSCRIPCION
    _devolver(m, "Marta Olmedo pide revisar la diapositiva 8 y el precio de AI Search")
    assert m.run("enrutar")[0] == 0
    est = m.estado()
    linea = next(ln for ln in est["carga"]["briefs"][-1]["texto"].split("\n") if ln.startswith("- [PERSONA] pide"))
    assert linea == "- [PERSONA] pide revisar la diapositiva 8 y el precio de AI Search"

    def puerta(estado, transcripcion=TRANSCRIPCION):
        return vp.c_brief(types.SimpleNamespace(estado=estado, carga=estado["carga"], transcripcion=transcripcion))
    c = puerta(est)
    assert c.estado != vp.FALLA and not any("PR14-6" in d for d in c.detalles), c.detalles
    roto = copy.deepcopy(est)
    b = roto["carga"]["briefs"][-1]
    cab, cuerpo = b["texto"].replace(linea, "- Todo correcto, sin cambios").split("\n---\n", 1)
    cab = "\n".join(x if not x.startswith("sha256_cuerpo: ") else
                    f"sha256_cuerpo: {hashlib.sha256(cuerpo.encode()).hexdigest()}" for x in cab.split("\n"))
    b["texto"] = cab + "\n---\n" + cuerpo                                            # resellado
    c = puerta(roto)
    assert c.estado == vp.FALLA and any("no es el de la decisión D-" in d for d in c.detalles), c.detalles
    otra = m.datos / "otra.txt"
    otra.write_text("Otra transcripción\n", encoding="utf-8")
    c = puerta(est, otra)                                                            # F1 distinta: no se recompone
    assert c.estado == vp.AVISO and any("contenido no contrastado" in d for d in c.detalles), c.detalles
