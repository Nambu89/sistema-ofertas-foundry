"""I1.7 · D · Las réplicas que propone docs/I1/CAMBIOS-I17-D.md §7 para la puerta son las mismas funciones que las del
núcleo (LES-G-097) y dan lo mismo sobre los casos de D16-5, REV16-5 y REVERIF16-3 y sobre los PPTX regenerados. Sin red."""
from __future__ import annotations

import ast
import inspect
import re

import pytest

from tests.i17_d_datos import RAIZ, catalogo, esquema_propuesto, estado_flujo, recomponer
from tests.test_i17_d_pptx import A_B, _arbol, _codo
from nucleo import pptx_revision as pr  # noqa: E402

DOC = RAIZ / "docs" / "I1" / "CAMBIOS-I17-D.md"
PARES = (("cortes_conectores", pr.cortes_conectores), ("separacion_conectores", pr.separacion_conectores),
         ("referencias_faltan", pr.referencias_faltan))


@pytest.fixture(autouse=True)
def _esquema(monkeypatch):
    esquema_propuesto(monkeypatch)


def replica(nombre: str):
    texto = DOC.read_text(encoding="utf-8")
    bloques = [b for b in re.findall(r"```python\n(.*?)```", texto, re.S) if f"def {nombre}_replica(" in b]
    assert len(bloques) == 1, f"CAMBIOS-I17-D.md tiene que traer exactamente un bloque con {nombre}_replica"
    # revisión independiente (I1.7): solo se compila la definición de la réplica, nunca otras sentencias del bloque
    arbol = ast.parse(bloques[0])
    definicion = [x for x in arbol.body if isinstance(x, ast.FunctionDef) and x.name == f"{nombre}_replica"]
    assert len(definicion) == 1 and len(arbol.body) == 1, "el bloque solo puede traer la definición de la réplica"
    espacio: dict = {}
    exec(compile(ast.Module(body=definicion, type_ignores=[]), str(DOC), "exec"), espacio)  # noqa: S102
    return bloques[0], espacio[f"{nombre}_replica"]


def _sin_nombre(fuente: str) -> str:
    arbol = ast.parse(fuente.replace("\r\n", "\n"))
    funcion = next(n for n in arbol.body if isinstance(n, ast.FunctionDef))
    funcion.name = "f"
    return ast.dump(funcion)


@pytest.mark.parametrize("nombre, funcion", PARES)
def test_misma_funcion_que_la_del_nucleo(nombre, funcion):
    fuente, _ = replica(nombre)
    if nombre == "referencias_faltan":
        # Cierre D (I1.9, 17-10): el núcleo lleva la excepción del sistema del cliente fuera del catálogo
        # (CAMBIOS-I19-D §2.4); se aplica en memoria la misma sustitución literal sobre el bloque de I1.7 y se compara
        # sin el docstring, que cambió. tests/test_i19_d_replicas.py hace lo mismo con la réplica viva de la puerta.
        from tests.test_i19_d_replicas import ANCLA_24, NUEVO_24, _sin_docstring
        fuente = fuente.replace("\r\n", "\n")
        assert fuente.count(ANCLA_24) == 1, "el anclaje de §2.4 no está una sola vez en el bloque de I1.7"
        assert _sin_docstring(fuente.replace(ANCLA_24, ANCLA_24 + NUEVO_24)) == _sin_docstring(
            inspect.getsource(funcion))
        return
    assert _sin_nombre(fuente) == _sin_nombre(inspect.getsource(funcion))


@pytest.mark.parametrize("cuerpo", [A_B + _codo(f) for f in ("val 50000", "val 99000", "val 1000", "val ５", "val --5",
                                                              "val 1" + "0" * 5000, "*/ w 1 2")])
def test_conectores_igual_en_nucleo_y_replica(cuerpo):
    arbol = _arbol(cuerpo)
    for nombre, funcion in PARES[:2]:
        assert replica(nombre)[1](arbol) == funcion(arbol)


@pytest.mark.parametrize("caso", ["B1", "A"])
def test_sobre_los_pptx_regenerados(caso):
    estado = recomponer(estado_flujo(caso))
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    prs, _ = pr.construir(estado, catalogo())
    d4 = prs.slides[3]._element
    for nombre, funcion in PARES[:2]:
        assert replica(nombre)[1](d4) == funcion(d4) == []
    assert replica("referencias_faltan")[1](d4, resp) == pr.referencias_faltan(d4, resp) == []
    resp["componentes"][0]["referencia_id"] = "REF-99"
    assert replica("referencias_faltan")[1](d4, resp) == pr.referencias_faltan(d4, resp) != []
