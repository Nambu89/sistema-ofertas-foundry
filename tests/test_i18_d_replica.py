"""I1.8 · D · La réplica que propone docs/I1/CAMBIOS-I18-D.md §2.1 para la puerta es la misma función que
pptx_revision.revision_interna_en_pptx (LES-G-097) y da lo mismo sobre el PPTX real publicado en I1.7 y sobre el que
genera el núcleo nuevo. Sin red."""
from __future__ import annotations

import ast
import inspect
import re

import pytest

from tests.i18_d_datos import RAIZ, catalogo, estado_real, partes_publicadas
from nucleo import pptx_revision as pr  # noqa: E402

DOC = RAIZ / "docs" / "I1" / "CAMBIOS-I18-D.md"
NOMBRE = "revision_interna_en_pptx_replica"


def replica():
    texto = DOC.read_text(encoding="utf-8")
    bloques = [b for b in re.findall(r"```python\n(.*?)```", texto, re.S) if f"def {NOMBRE}(" in b]
    assert len(bloques) == 1, f"CAMBIOS-I18-D.md tiene que traer exactamente un bloque con {NOMBRE}"
    arbol = ast.parse(bloques[0])
    definicion = [x for x in arbol.body if isinstance(x, ast.FunctionDef) and x.name == NOMBRE]
    assert len(definicion) == 1 and len(arbol.body) == 1, "el bloque solo puede traer la definición de la réplica"
    espacio: dict = {}
    exec(compile(ast.Module(body=definicion, type_ignores=[]), str(DOC), "exec"), espacio)  # noqa: S102
    return bloques[0], espacio[NOMBRE]


def _sin_nombre(fuente: str) -> str:
    funcion = next(n for n in ast.parse(fuente.replace("\r\n", "\n")).body if isinstance(n, ast.FunctionDef))
    funcion.name = "f"
    return ast.dump(funcion)


def _vprot1() -> tuple[str, str]:
    """Cierre D (I1.9, 16-10): (anclaje, sustitución) de VPROT-1 tal como los aplica el integrador con
    docs/I1/CAMBIOS-I19-R/aplicar_i19_r.py (CAMBIOS-I19-R §3.2): texto alternativo, diseños y patrones."""
    import importlib.util
    ruta = RAIZ / "docs" / "I1" / "CAMBIOS-I19-R" / "aplicar_i19_r.py"
    spec = importlib.util.spec_from_file_location("aplicar_i19_r", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    cambios = [(v, n) for rel, que, v, n in modulo.CAMBIOS if rel.endswith("pptx_revision.py") and "VPROT-1" in que]
    assert len(cambios) == 1, "el aplicador de R tiene que traer exactamente un cambio VPROT-1 en pptx_revision.py"
    return cambios[0]


def _nucleo_con_vprot1() -> str:
    """El núcleo con VPROT-1: tal cual si ya está aplicado; si no, con la sustitución literal de R en memoria."""
    fuente = inspect.getsource(pr.revision_interna_en_pptx).replace("\r\n", "\n")
    if "VPROT-1" not in fuente:
        viejo, nuevo = _vprot1()
        assert fuente.count(viejo) == 1, "el anclaje de VPROT-1 no está una sola vez en el núcleo"
        fuente = fuente.replace(viejo, nuevo)
    return fuente


def _sin_docstring(fuente: str) -> str:
    funcion = next(n for n in ast.parse(fuente.replace("\r\n", "\n")).body if isinstance(n, ast.FunctionDef))
    funcion.name = "f"
    if funcion.body and isinstance(funcion.body[0], ast.Expr) and isinstance(funcion.body[0].value, ast.Constant):
        funcion.body = funcion.body[1:]
    return ast.dump(funcion)


def test_misma_funcion_que_la_del_nucleo():
    """El bloque de I1.8 es el núcleo; con VPROT-1 (R, I1.9) aplicado, el bloque con la misma sustitución."""
    fuente, _ = replica()
    nucleo = inspect.getsource(pr.revision_interna_en_pptx).replace("\r\n", "\n")
    if "VPROT-1" in nucleo:
        viejo, nuevo = _vprot1()
        assert fuente.count(viejo) == 1
        fuente = fuente.replace(viejo, nuevo)
    assert _sin_nombre(fuente) == _sin_nombre(nucleo)


def test_nucleo_con_vprot1_igual_que_la_replica_viva_de_la_puerta():
    """LES-G-097 (cierre D, I1.9): la puerta ya lleva VPROT-1; el núcleo, una vez aplicado el cambio de R, es la misma
    función (sin contar la documentación)."""
    import verificar_paquete as vp
    assert _sin_docstring(_nucleo_con_vprot1()) == _sin_docstring(inspect.getsource(vp.revision_interna_en_pptx_replica))


def test_solo_un_bloque_python_en_el_documento():
    """Los fragmentos de la puerta que no son réplica van como `text`: el contraste solo compila bloques python."""
    assert len(re.findall(r"```python\n", DOC.read_text(encoding="utf-8"))) == 1


@pytest.mark.parametrize("caso", ["lista_B", "aprobada_B"])
def test_igual_en_nucleo_y_replica(caso):
    _, funcion = replica()
    estado = estado_real(caso)
    publicado = partes_publicadas(caso)
    assert funcion(publicado, estado, catalogo()) == pr.revision_interna_en_pptx(publicado, estado, catalogo()) != []
    nuevo = pr.partes_de(pr.construir(estado, catalogo())[0])
    assert funcion(nuevo, estado, catalogo()) == pr.revision_interna_en_pptx(nuevo, estado, catalogo()) == []


def test_parte_que_falta_lanza_y_no_da_limpio():
    _, funcion = replica()
    partes = dict(partes_publicadas("lista_B"))
    del partes["ppt/presentation.xml"]
    with pytest.raises(KeyError):
        funcion(partes, estado_real("lista_B"), catalogo())
