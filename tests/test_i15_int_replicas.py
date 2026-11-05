"""I1.5 · Integrador · Las réplicas pegadas en verificar_paquete.py son las del núcleo (LES-G-097) y la regla de
plantillas no deja pasar un auxiliar mal formado ni rechaza el auxiliar de la lista blanca. Sin red."""
from __future__ import annotations

import ast
import inspect
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
for ruta in (RAIZ / "sandbox", RAIZ):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))

from nucleo import experto, pptx_revision  # noqa: E402
import verificar_paquete as V  # noqa: E402

from tests.i16_p_datos import a_v3, catalogo_i16  # noqa: E402  (I1.6: contrato común de la decisión 4)
CAT = catalogo_i16(json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8")), niveles=False)


def _cuerpo(funcion) -> str:
    arbol = ast.parse(inspect.getsource(funcion).replace("\r\n", "\n"))
    nodo = next(n for n in arbol.body if isinstance(n, ast.FunctionDef))
    nodo.name = "f"
    return ast.dump(nodo)


def test_replica_de_cortes_en_la_puerta_es_la_del_nucleo():
    assert _cuerpo(V.cortes_conectores_replica) == _cuerpo(pptx_revision.cortes_conectores)


def test_la_puerta_ya_no_tiene_el_aviso_de_cruces():
    """CAMBIOS-I15-D §2: cruces() trataba los codos como rectas (avisos falsos). Comprobación estática; la de
    comportamiento es test_i1_verificar_paquete.py::test_conector_que_corta_el_texto_de_una_forma_falla_en_diagrama."""
    assert not hasattr(V, "cruces")
    fuente = inspect.getsource(V.c_diagrama)
    assert "cortes_conectores_replica(d4.raiz)" in fuente and "c.falla(f\"diagrama: {s} (PR14-3" in fuente


def test_filtro_de_plantilla_igual_en_nucleo_y_puerta():
    assert _cuerpo(experto._filtro_de_plantilla) == _cuerpo(V._filtro_de_plantilla)
    assert _cuerpo(experto.problemas_precio) == _cuerpo(V.problemas_precio)


def _comp(cid, region):
    return {"id": "C-02", "servicio": "Componente", "catalogo_id": cid, "region": region}


def _precio(filtro):
    return {"id": "P-01", "componente_id": "C-02", "filtro": filtro}


AUX = ("serviceName eq 'Azure Private Link' and armRegionName eq 'swedencentral' and meterName eq "
       "'Standard Private Endpoint' and priceType eq 'Consumption'")


AUX_I16 = next(p["filtro"] for e in CAT["componentes"] if e["id"] == "az-private-link"
               for p in e["plantillas_precio"] if p["id"] == "punto-conexion")  # I1.6: plantilla de E


def test_el_auxiliar_de_la_lista_blanca_no_pide_plantilla_pero_sigue_sus_reglas():
    """I1.6 (REV15-3): el auxiliar ya SÍ pide plantilla, la suya (`plantillas_de` + `plantillas`), y un componente de su
    lista; el de antes, sin plantilla, se rechaza con el mismo texto en el núcleo y en la puerta."""
    for mod in (experto, V):
        assert mod.incoherencias_servicio(_comp("az-storage", "swedencentral"), CAT, [_precio(AUX_I16)]) == []
        motivos = mod.incoherencias_servicio(_comp("az-storage", "swedencentral"), CAT, [_precio(AUX)])
        assert any("no es el de ninguna plantilla del precio auxiliar" in m for m in motivos), motivos
        motivos = mod.incoherencias_servicio(_comp("az-cosmos-db", "swedencentral"), CAT, [_precio(AUX_I16)])
        assert any("no acompaña a Azure Cosmos DB" in m for m in motivos), motivos


def test_fila_propia_sin_plantillas_falla_cerrado_en_los_dos():
    entrada = dict(next(c for c in CAT["componentes"] if c["id"] == "az-app-service"))
    filtro = entrada["plantillas_precio"][0]["filtro"]
    entrada.pop("plantillas_precio")
    for mod in (experto, V):
        motivos = mod.problemas_precio(_precio(filtro), entrada, "swedencentral", CAT)
        assert any("no trae plantillas de filtro de precio" in m for m in motivos), motivos
