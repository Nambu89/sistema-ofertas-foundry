"""I1.8 · D · VER17-2 y R17-4/INT17-4: «Cambios pedidos en la revisión anterior» vive solo en la nota del revisor, con
el comentario literal, cómo se atendió y el nombre legible de cada servicio; y el PPTX no se publica si lleva texto de la
revisión interna. Con los estados reales de la versión B de I1.7. Sin red."""
from __future__ import annotations

import pytest

from tests.i18_d_datos import catalogo, estado_real
from nucleo import decision, errores, nota_revision as nr, pptx_revision as pr  # noqa: E402


@pytest.mark.parametrize("caso", ["lista_B", "aprobada_B"])
def test_lineas_de_la_nota_con_nombres_legibles(caso):
    lineas = nr.lineas_cambios_nota(estado_real(caso), catalogo())
    assert lineas[0] == f"{decision.TITULO_CAMBIOS} (versión A, DEVUELTA)" and lineas[1] == nr.AVISO_CAMBIOS
    texto = "\n".join(lineas)
    assert "Comentario de Responsable de preventa (D-002): «SIMULADA en la prueba de los arreglos de I1.7" in texto
    assert "- Componente añadido: Azure Blob Storage (Hot LRS, swedencentral)" in texto
    assert "- Consumo añadido: Azure Blob Storage, Hot LRS Data Stored (6 al mes)" in texto
    assert "- Precio cerrado: de 23.457,50 € a 17.533,75 €" in texto
    assert "- Consumo mensual estimado: de 80,62 € a 80,72 €" in texto
    assert "az-" not in texto.replace("(D-002)", "")


@pytest.mark.parametrize("caso", ["lista_B", "aprobada_B"])
def test_la_nota_lleva_cada_linea_en_su_parrafo(caso):
    estado = estado_real(caso)
    textos = nr.textos_docx(nr.construir(estado, catalogo()))
    lineas = nr.lineas_cambios_nota(estado, catalogo())
    assert lineas and all(x in textos for x in lineas)


def test_el_comentario_se_copia_literal_aunque_cite_una_clave():
    estado = estado_real("lista_B")
    estado["decisiones"][1]["comentarios"] = "Cambiad az-storage · hot-lrs-datos por otra cosa, 1200 € al mes"
    lineas = nr.lineas_cambios_nota(estado, catalogo())
    assert "Comentario de Responsable de preventa (D-002): «Cambiad az-storage · hot-lrs-datos por otra cosa, 1200 € al mes»" \
        in lineas


def test_nombres_claves():
    nombres = nr.nombres_claves(estado_real("lista_B"), catalogo())
    assert nombres["az-storage"] == "Azure Blob Storage"
    assert nombres["az-storage · hot-lrs-datos"] == "Azure Blob Storage, Hot LRS Data Stored"
    assert all(not v.startswith("az-") for v in nombres.values())


def test_clave_fuera_del_catalogo_se_queda_y_la_desviacion_se_nombra(monkeypatch):
    estado = estado_real("lista_B")
    real = decision.resumen_version

    def resumen(e):
        r = real(e)
        r["componentes"] = r["componentes"] + [{"clave": "desviación: Azure Maps", "sku": "G2", "region": "westeurope"},
                                               {"clave": "az-inventado", "sku": "x", "region": "y"}]
        return r
    monkeypatch.setattr(decision, "resumen_version", resumen)
    nombres = nr.nombres_claves(estado, catalogo())
    assert nombres["desviación: Azure Maps"] == "Azure Maps (fuera del catálogo)" and "az-inventado" not in nombres


@pytest.mark.parametrize("linea, esperada", [
    ("- Precio cerrado: de 23457.50 € a 17533.75 €", "- Precio cerrado: de 23.457,50 € a 17.533,75 €"),
    ("- Cantidad cambiada en Foundry, GPT 5.4 input: de 1200 a 1500.5 al mes",
     "- Cantidad cambiada en Foundry, GPT 5.4 input: de 1.200 a 1.500,5 al mes"),
    ("- Consumo mensual estimado: de sin dato € a 80.72 €", "- Consumo mensual estimado: de sin dato € a 80,72 €"),
    ("- Cambio de nivel en Azure App Service: de P0v3 a B1", "- Cambio de nivel en Azure App Service: de P0v3 a B1"),
])
def test_cifras_en_formato_espanol_sin_tocar_los_nombres(linea, esperada):
    assert nr._cifras_es(linea) == esperada


def test_version_a_sin_seccion():
    estado = estado_real("lista_B")
    estado["version"] = "A"
    assert nr.lineas_cambios_nota(estado, catalogo()) == []


def test_el_pptx_no_se_publica_con_texto_de_la_revision():
    estado = estado_real("lista_B")
    prs = pr.construir(estado, catalogo())[0]
    supuesto = next(t for d, t in pr.textos_pptx(prs) if d == "diapositiva 6" and t.startswith("El almacenamiento"))
    estado["decisiones"][1]["comentarios"] = f"Quitad esto: {supuesto}"  # no cambia la huella del contenido
    with pytest.raises(errores.ReglaIncumplida) as exc:
        pr.construir(estado, catalogo())
    assert "revisión interna" in str(exc.value)
    assert any("comentario de la decisión D-002" in h for h in exc.value.errores)


def test_lista_de_comprobacion_con_los_puntos_de_i18():
    """CAMBIOS-I18-P §5 (a cargo del cliente, instancias y modelo de Foundry) y VER17-2, en la nota real."""
    textos = nr.textos_docx(nr.construir(estado_real("lista_B"), catalogo()))
    for inicio in ("A cargo del cliente: si algún componente sale a cargo del cliente",
                   "Instancias: si algún servicio lleva más de una instancia",
                   "Modelos de Microsoft Foundry: el modelo que nombra cada componente",
                   "Cambios pedidos (versión abierta por una devolución)"):
        assert sum(t.startswith("☐ " + inicio) or t.startswith(inicio) for t in textos) == 1, inicio
