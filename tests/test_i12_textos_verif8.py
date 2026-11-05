"""VERIF-8: lo que ve el cliente sin riesgos repetidos, sin capacidades que repiten el objetivo, sin
identificadores de SKU en la prosa y con las referencias compuestas en castellano. Sin red."""
from __future__ import annotations

import json
import pathlib
import sys

import pytest
from pptx import Presentation

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

from nucleo import anexo_consumo, hashes, pptx_revision, textos_cliente as tc  # noqa: E402

UE = "un despliegue que procesa los datos solo dentro del Límite de datos de la UE"


def _json(ruta):
    return json.loads(pathlib.Path(ruta).read_text(encoding="utf-8"))


@pytest.fixture()
def catalogo():
    return _json(RAIZ / "sandbox/datos/catalogo_componentes.json")


@pytest.fixture()
def tarifa():
    return _json(RAIZ / "salidas/rate-card.json")


@pytest.fixture()
def estado():
    return _json(RAIZ / "esquemas/ejemplos/estado.json")


def _componer(est, catalogo, tarifa):
    est["carga"]["anexo_consumo"] = anexo_consumo.calcular(est, catalogo)
    est["carga"]["textos_cliente"] = tc.componer(est, catalogo, tarifa)
    est["hash_contenido"] = hashes.hash_contenido(est)
    return est["carga"]["textos_cliente"]


@pytest.mark.parametrize("texto, regiones, esperado", [
    ("Se plantea gpt-5-mini y DataZoneStandard en Suecia Central.", ["swedencentral"],
     f"Se plantea gpt-5-mini y {UE} en Suecia Central."),
    ("Con la modalidad Data Zone Standard.", ["francecentral"], f"Con {UE}."),
    ("DataZoneStandard en Suecia.", ["swedencentral"], UE[0].upper() + UE[1:] + " en Suecia."),
    ("Con DataZoneStandard.", ["eastus2"], "Con un despliegue que procesa los datos solo dentro de EE. UU."),
    ("Con DataZoneStandard en Iowa.", ["eastus2"],
     "Con un despliegue que procesa los datos solo dentro de EE. UU. en Iowa."),
    ("Con Regional Provisioned Managed.", ["eastus2"], "Con una capacidad reservada en la región elegida."),
    ("Usamos RegionalProvisionedManaged.", [], "Usamos una capacidad reservada en la región elegida."),
    ("Con DataZoneStandard.", ["norwayeast"], "Con DataZoneStandard."),  # zona sin confirmar: no se traduce
    ("Con DataZoneStandard.", ["swedencentral", "eastus"], "Con DataZoneStandard."),  # zonas mezcladas
    ("Con el despliegue GlobalStandard.", [],
     "Con un despliegue global que puede procesar los datos fuera de la región elegida."),
])
def test_traducir_skus(texto, regiones, esperado):
    assert tc.traducir_skus(texto, regiones) == esperado


def test_jerga_tecnica_lista_blanca(catalogo):
    assert tc.jerga_tecnica("Con DataZoneStandard en la región.")
    assert tc.jerga_tecnica("Con Data Zone Standard en la región.")  # sin traducir aunque no lleve mayúscula interna
    assert tc.jerga_tecnica("Un despliegue gptMini o ProvisionedManaged.")
    assert not tc.jerga_tecnica("Canal B2B y B2C con el plan S1 y P0v3.")  # dígito y mayúscula: no es la regla
    assert not tc.jerga_tecnica("Documentos de SharePoint Online y OneDrive con Azure OpenAI y GitHub.")
    assert tc.jerga_tecnica("Oferta para McKelvara's España.")
    assert not tc.jerga_tecnica("Oferta para McKelvara's España.", tc.palabras_admitidas("McKelvara's España"))
    nombres = [c["nombre_oficial"] for c in catalogo["componentes"]]
    assert not [n for n in nombres if tc.jerga_tecnica(n)]


def test_repite_el_objetivo():
    objetivo = ("Crear un asistente de IA para técnicos de mantenimiento que responda en lenguaje natural sobre "
                "procedimientos y cite el procedimiento de origen.")
    assert tc.repite("Responder en lenguaje natural sobre los procedimientos de mantenimiento y citar siempre el "
                     "procedimiento de origen.", objetivo)
    assert not tc.repite("Buscar en procedimientos y manuales de equipos y citar el documento de origen.", objetivo)
    assert not tc.repite("Citar el procedimiento de origen.", objetivo)  # dos raíces comunes no bastan


def test_componer_verif8(estado, catalogo, tarifa):
    campos = estado["carga"]["requisitos"]["campos"]
    objetivo = campos["objetivo"]["entradas"][0]["valor"]
    repetida = dict(campos["alcance_funcional"]["entradas"][0], valor=objetivo.replace("Asistente de IA que", "Que"))
    campos["alcance_funcional"]["entradas"].append(repetida)
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    resp["supuestos"] += [
        {"id": "S-08", "texto": "Se plantea gpt-5-mini con DataZoneStandard en Suecia Central.", "confianza": "BAJA",
         "hechos": ["C-01"]},
        {"id": "S-09", "texto": "La identidad usa DataZoneStandard sin región.", "confianza": "BAJA", "hechos": ["C-05"]}]
    resp["riesgos"] += [
        {"id": "RG-08", "texto": "El precio de Microsoft Foundry no se verificó en Azure Retail Prices y el coste no "
                                 "queda cerrado.", "mitigacion": "Confirmarlo.", "hechos": ["C-01"]},
        {"id": "RG-09", "texto": "El coste de Microsoft Foundry crecerá si aumentan las consultas.",
         "mitigacion": "Vigilar el consumo.", "hechos": ["C-01"]}]
    t = _componer(estado, catalogo, tarifa)
    motivos = {x["origen"]: x["motivo"] for x in t["excluidas"]}
    textos = [f["texto"] for k in ("alcance", "supuestos", "riesgos") for f in t[k]]
    # VA19-1 (I1.10): la frase que repite el objetivo se queda en «Incluido» (diapositiva 5); solo se omite en
    # «Capacidades principales» (diapositiva 3), donde el objetivo está a la vista
    assert not any("repite el objetivo" in m for m in motivos.values())
    assert any(tc.repite(x, objetivo) for x in (f["texto"] for f in t["alcance"]))
    assert f"Se plantea gpt-5-mini con {UE} en Suecia Central." in textos
    assert "tipo de despliegue sin traducir" in motivos["experto S-09"]  # C-05 (Entra ID) es global: no se traduce (CMP-1: el bot ya va en westeurope)
    assert motivos["experto RG-08"] == "repite un riesgo de consumo que ya declara el código"
    assert "El coste de Microsoft Foundry crecerá si aumentan las consultas." in textos  # otro riesgo: se queda
    assert not [x for d, x in tc._todas(t) if not d.startswith(("componente", "consumo", "portada"))
                and tc.jerga_tecnica(x)]
    refs = t["arquitectura"]["referencias"]
    # REV13-3: el título que se publica es castellano compuesto por código, sin el título inglés de Learn
    assert refs and all(r["titulo"].startswith("Documentación oficial de Microsoft sobre ") and "«" not in r["titulo"]
                        for r in refs)


def test_referencias_en_la_diapositiva(estado, catalogo, tarifa, tmp_path):
    t = _componer(estado, catalogo, tarifa)
    ruta = tmp_path / "r.pptx"
    pptx_revision.generar(estado, catalogo, ruta)
    diapo = Presentation(str(ruta)).slides[3]
    parrafos = [p.text for f in diapo.shapes if f.has_text_frame for p in f.text_frame.paragraphs]
    for r in t["arquitectura"]["referencias"]:  # I1.7 (REVERIF16-3): «Sujeto: URL» bajo el rótulo del pie
        assert pptx_revision.texto_referencia(r) in parrafos
    assert not any("»: https" in p for p in parrafos)


def test_referencia_sin_tema_se_retira_y_el_titulo_ingles_no_se_publica(estado, catalogo, tarifa):
    """REV13-3: el título del experto ya no se publica (ni largo ni corto); una URL sin tema se retira."""
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    # I1.7 (REVERIF16-3): una referencia que no es de ningún componente y no tiene tema se retira; la de un componente
    # sale siempre, con su nombre como título, tenga tema o no
    usadas = {c["referencia_id"] for c in resp["componentes"]}
    libre = next(r for r in resp["referencias"] if r["id"] not in usadas)
    libre["url"] = "https://learn.microsoft.com/azure/otra-cosa/x"
    de_componente = next(r for r in resp["referencias"] if r["id"] in usadas)
    de_componente["titulo"] = "Título " * 30
    t = _componer(estado, catalogo, tarifa)
    publicadas = {r["id"]: r["titulo"] for r in t["arquitectura"]["referencias"]}
    assert de_componente["id"] in publicadas and "Título" not in publicadas[de_componente["id"]]
    assert libre["id"] not in publicadas
    assert any(x["origen"] == f"referencia {libre['id']}" for x in t["excluidas"])


def test_cada_prefijo_de_la_lista_blanca_tiene_tema_en_castellano():
    """Ampliar experto.PREFIJOS_REFERENCIA sin tema haría desaparecer referencias: la prueba falla antes."""
    from nucleo import experto
    assert set(tc.TEMAS_REFERENCIA) == set(experto.PREFIJOS_REFERENCIA)
    assert tc.titulo_referencia("https://learn.microsoft.com/es-es/azure/search/search-what-is-azure-search") == \
        "Documentación oficial de Microsoft sobre Azure AI Search"
    assert tc.titulo_referencia("https://learn.microsoft.com/azure/foundry-classic/x") == \
        "Documentación oficial de Microsoft sobre Microsoft Foundry"  # el prefijo más largo manda
    assert tc.titulo_referencia("https://learn.microsoft.com/azure/searchx/y") is None
    assert tc.titulo_referencia("https://example.com/azure/search/y") is None


def test_nota_frase_excluida_sin_doble_punto(estado, catalogo, tarifa, tmp_path):
    from docx import Document

    from nucleo import nota_revision
    campos = estado["carga"]["requisitos"]["campos"]
    objetivo = campos["objetivo"]["entradas"][0]["valor"]
    # VA19-1 (I1.10): la repetición del objetivo ya no se excluye; la exclusión por forma (más de 400 caracteres) sí
    largo = ("Integración con " + "el sistema documental de la organización, " * 12).rstrip(", ") + "."
    campos["alcance_funcional"]["entradas"].append(dict(campos["alcance_funcional"]["entradas"][0], valor=largo))
    _componer(estado, catalogo, tarifa)
    ruta = tmp_path / "n.docx"
    nota_revision.generar(estado, catalogo, ruta)
    lineas = [p.text for p in Document(str(ruta)).paragraphs if "Frase excluida del PPTX" in p.text]
    assert lineas and not any("repite el objetivo" in x for x in lineas)
    assert not any(".. Motivo:" in x for x in lineas)
    assert "Frase excluida del PPTX (requisito alcance_funcional): " + largo + " Motivo:" in " ".join(lineas)
