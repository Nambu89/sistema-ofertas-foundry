"""I1.9 · D · Las réplicas que propone docs/I1/CAMBIOS-I19-D.md §2 para la puerta son las mismas funciones que las del
núcleo (LES-G-097) y dan lo mismo sobre los PPTX publicados en I1.8 y los regenerados. Sin red."""
from __future__ import annotations

import ast
import inspect
import io
import re
import zipfile

import pytest
from pptx import Presentation

from tests.i19_d_datos import RAIZ, catalogo, estado_real, partes_publicadas, recomponer
from nucleo import pptx_revision as pr  # noqa: E402

DOC = RAIZ / "docs" / "I1" / "CAMBIOS-I19-D.md"
PARES = (("importes_no_permitidos", pr.importes_no_permitidos), ("legibilidad_conectores", pr.legibilidad_conectores))


def replica(nombre: str):
    texto = DOC.read_text(encoding="utf-8")
    bloques = [b for b in re.findall(r"```python\n(.*?)```", texto, re.S) if f"def {nombre}_replica(" in b]
    assert len(bloques) == 1, f"CAMBIOS-I19-D.md tiene que traer exactamente un bloque con {nombre}_replica"
    arbol = ast.parse(bloques[0])
    definicion = [x for x in arbol.body if isinstance(x, ast.FunctionDef) and x.name == f"{nombre}_replica"]
    assert len(definicion) == 1 and len(arbol.body) == 1, "el bloque solo puede traer la definición de la réplica"
    espacio: dict = {}
    exec(compile(ast.Module(body=definicion, type_ignores=[]), str(DOC), "exec"), espacio)  # noqa: S102
    return bloques[0], espacio[f"{nombre}_replica"]


def _sin_nombre(fuente: str) -> str:
    funcion = next(n for n in ast.parse(fuente.replace("\r\n", "\n")).body if isinstance(n, ast.FunctionDef))
    funcion.name = "f"
    return ast.dump(funcion)


@pytest.mark.parametrize("nombre, funcion", PARES)
def test_misma_funcion_que_la_del_nucleo(nombre, funcion):
    fuente, _ = replica(nombre)
    assert _sin_nombre(fuente) == _sin_nombre(inspect.getsource(funcion))


def test_solo_dos_bloques_python_en_el_documento():
    """Los fragmentos de la puerta que no son réplica van como `text`: el contraste solo compila bloques python."""
    assert len(re.findall(r"```python\n", DOC.read_text(encoding="utf-8"))) == 2


def _diapositiva_4(partes: dict):
    datos = io.BytesIO()
    with zipfile.ZipFile(datos, "w") as zf:
        for n, b in partes.items():
            zf.writestr(n, b)
    return Presentation(io.BytesIO(datos.getvalue())).slides[3]._element


@pytest.mark.parametrize("caso", ["hostelia_lista_A", "brezalia_lista_B", "brezalia_final"])
def test_igual_en_nucleo_y_replica_sobre_lo_publicado_y_lo_regenerado(caso):
    _, importes = replica("importes_no_permitidos")
    _, legibilidad = replica("legibilidad_conectores")
    estado = estado_real(caso)
    publicado = partes_publicadas(caso)
    assert importes(publicado, estado) == pr.importes_no_permitidos(publicado, estado)
    assert legibilidad(_diapositiva_4(publicado)) == pr.legibilidad_conectores(_diapositiva_4(publicado))
    nuevo = recomponer(estado)
    partes = pr.partes_de(pr.construir(nuevo, catalogo())[0])
    assert importes(partes, nuevo) == pr.importes_no_permitidos(partes, nuevo) == []
    assert legibilidad(_diapositiva_4(partes)) == pr.legibilidad_conectores(_diapositiva_4(partes)) == []


def test_parte_que_falta_lanza_y_no_da_limpio():
    _, importes = replica("importes_no_permitidos")
    partes = dict(partes_publicadas("hostelia_lista_A"))
    del partes["ppt/presentation.xml"]
    with pytest.raises(KeyError):
        importes(partes, estado_real("hostelia_lista_A"))


# Cierre D (I1.9), CAMBIOS-I19-D §2.4: la réplica de referencias_faltan en la puerta lleva la excepción del sistema del
# cliente fuera del catálogo. Si el integrador aún no la ha pegado, se aplica aquí la sustitución literal del documento.
ANCLA_24 = '        if not isinstance(comp, dict):\n            continue\n'
NUEVO_24 = ('        if isinstance(comp.get("existente_del_cliente"), dict) and comp.get("catalogo_id") is None \\\n'
            '                and comp.get("referencia_id") is None:\n            continue\n')


def _sin_docstring(fuente: str) -> str:
    funcion = next(n for n in ast.parse(fuente.replace("\r\n", "\n")).body if isinstance(n, ast.FunctionDef))
    funcion.name = "f"
    if funcion.body and isinstance(funcion.body[0], ast.Expr) and isinstance(funcion.body[0].value, ast.Constant):
        funcion.body = funcion.body[1:]
    return ast.dump(funcion)


def test_referencias_faltan_replica_con_el_cambio_de_2_4():
    import textwrap
    import verificar_paquete as vp
    assert NUEVO_24 in DOC.read_text(encoding="utf-8"), "§2.4 tiene que traer la sustitución literal"
    fuente = textwrap.dedent(inspect.getsource(vp.referencias_faltan_replica)).replace("\r\n", "\n")
    if NUEVO_24 not in fuente:
        assert fuente.count(ANCLA_24) == 1, "el anclaje de §2.4 no está una sola vez en la réplica de la puerta"
        fuente = fuente.replace(ANCLA_24, ANCLA_24 + NUEVO_24)
    assert _sin_docstring(fuente) == _sin_docstring(inspect.getsource(pr.referencias_faltan))
