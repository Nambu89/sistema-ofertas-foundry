"""I1.2, arreglos de la verificación independiente (pruebas/I12/ARREGLOS-VER.md). Sin red.

VER-1: el veto de región reconoce los nombres de Learn en castellano (alias del catálogo) y el alias reordenado; un
componente fuera de catálogo en una región con vetos se acepta con un aviso que va a la nota del revisor.
VER-2: la lista blanca de `nubes` no borra la sintaxis VTT antes de comparar: falla cerrado, igual en las dos partes.
"""
from __future__ import annotations

import json
import pathlib
import sys
import types

import pytest
from docx import Document

from tests.test_i1_documentos_comun import docs, estado_ejemplo  # noqa: F401  (fixture)

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "sandbox"))
sys.path.insert(0, str(RAIZ))
from nucleo import experto, suficiencia  # noqa: E402
import verificar_paquete as V  # noqa: E402

CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))
FUENTE = json.loads((RAIZ / "catalogo" / "catalogo_referencias_azure.json").read_text(encoding="utf-8"))
UE = ("swedencentral", "francecentral", "westeurope", "northeurope", "germanywestcentral", "spaincentral", "italynorth")


def _comp(servicio, region, cid=None):
    return {"id": "C-09", "servicio": servicio, "catalogo_id": cid, "region": region}


# ── VER-1: nombres en castellano, mayúsculas, sin tildes y reordenados ─────────────────────────────────────────
VETADOS_ES = [  # el nombre contiene un alias del catálogo como frase completa
    ("Busqueda de Azure AI", "swedencentral"), ("Búsqueda de Azure AI", "swedencentral"),
    ("Busqueda cognitiva de Azure", "swedencentral"), ("BÚSQUEDA DE AZURE AI", "westeurope"),
    ("búsqueda cognitiva de azure (S1)", "northeurope"),
    ("Servicio de Voz de Azure AI", "spaincentral"), ("VOZ DE AZURE", "spaincentral"),
    ("Seguridad del contenido de Azure AI", "northeurope"),
    ("Comprensión de contenido de Azure en Foundry Tools", "spaincentral")]
# REVER-2 (I1.2): la regla de palabras reordenadas se retiró (vetaba «API de búsqueda con IA» como AI Search). Estos
# nombres, con catalogo_id null y sin precio que los identifique, ya no se vetan: van con el aviso para el revisor.
REORDENADOS_CON_AVISO = [
    ("Azure AI Búsqueda", "germanywestcentral"), ("Búsqueda AI de Azure", "swedencentral"),
    ("Búsqueda de IA de Azure", "swedencentral"), ("Azure Búsqueda Cognitiva", "westeurope"),
    ("Search AI Azure", "swedencentral"), ("Azure AI Seguridad de Contenido", "northeurope"),
    ("Servicio de agentes de Microsoft Foundry", "northeurope"), ("Foundry: servicio de agente", "northeurope"),
    ("Azure Foundry Tools: comprension de contenido", "italynorth")]


@pytest.mark.parametrize("servicio, region", VETADOS_ES)
def test_nombre_en_castellano_se_veta_igual_en_nucleo_y_puerta(servicio, region):
    comp = _comp(servicio, region)
    motivo = experto.region_no_admitida(comp, CAT)
    assert motivo and "reconocido por el nombre" in motivo, (servicio, region)
    assert V.region_no_admitida(comp, CAT) == motivo
    assert experto.aviso_fuera_de_catalogo(comp, CAT) is None is V.aviso_fuera_de_catalogo(comp, CAT)


def test_cada_servicio_vetado_tiene_un_alias_de_learn_en_castellano_comprobado():
    fuentes = {f["url"]: f for f in FUENTE["fuentes_comprobadas"]}
    for c in FUENTE["componentes"]:
        if c.get("regiones_no_admitidas"):
            es = [a for a in c["alias"] if "/es-es/" in a["fuente_url"]]
            assert es, c["id"]
            for a in es:
                f = fuentes[a["fuente_url"]]
                assert f["http"] == 200 and f["consultado"] >= FUENTE["fecha"] and "/es-es/" in f["url_final"], a


def test_los_alias_en_castellano_no_vetan_a_su_servicio_fuera_de_sus_regiones_vetadas():
    for c in CAT["componentes"]:
        propias = {v["region"] for v in c.get("regiones_no_admitidas") or []}
        for nombre in c.get("alias") or []:
            for r in sorted(set(UE) - propias):
                for cid in (c["id"], None):
                    assert experto.region_no_admitida(_comp(nombre, r, cid), CAT) is None, (c["id"], nombre, r, cid)


@pytest.mark.parametrize("servicio, region", [
    ("Servidor local del cliente", "swedencentral"), ("Azure Voz", "spaincentral"),
    ("Herramienta de terceros", "northeurope"), ("Busqueda semantica propia", "westeurope"),
    ("Comprension de contenido de Azure", "italynorth"), ("Seguridad del contenido", "northeurope"),
    # REVER-1: el alias de un servicio (con o sin veto) en el nombre ya no silencia el aviso; solo el id o el precio
    ("Azure Blob Storage", "swedencentral"), ("Almacenamiento Blob de Azure", "swedencentral"),
    ("Búsqueda de Azure AI", "francecentral"), *REORDENADOS_CON_AVISO])
def test_fuera_de_catalogo_en_region_con_vetos_se_acepta_con_aviso(servicio, region):
    comp = _comp(servicio, region)
    assert experto.region_no_admitida(comp, CAT) is None is V.region_no_admitida(comp, CAT)
    aviso = experto.aviso_fuera_de_catalogo(comp, CAT)
    assert aviso and experto.AVISO_FUERA_DE_CATALOGO in aviso and aviso == V.aviso_fuera_de_catalogo(comp, CAT)
    resp = {"componentes": [comp]}
    assert aviso in experto.avisos_respuesta(resp, CAT)


@pytest.mark.parametrize("comp", [
    _comp("Servidor local del cliente", "global"), _comp("Búsqueda de Azure AI", "uksouth"),
    _comp("Servidor local del cliente", "swedencentral", "az-app-service")])
def test_sin_aviso_si_lleva_catalogo_id_o_la_region_no_tiene_vetos(comp):
    assert experto.aviso_fuera_de_catalogo(comp, CAT) is None is V.aviso_fuera_de_catalogo(comp, CAT)


@pytest.mark.parametrize("servicio, cid, region", [  # REVER-2: con un id válido manda el id (el cliente ve su nombre)
    ("Azure AI Búsqueda", "az-foundry", "swedencentral"), ("Búsqueda AI de Azure", "az-storage", "westeurope"),
    ("Foundry: servicio de agente", "az-foundry", "northeurope")])
def test_nombre_reordenado_con_un_catalogo_id_valido_no_se_veta_ni_avisa(servicio, cid, region):
    comp = _comp(servicio, region, cid)
    assert experto.region_no_admitida(comp, CAT) is None is V.region_no_admitida(comp, CAT)
    assert experto.aviso_fuera_de_catalogo(comp, CAT) is None is V.aviso_fuera_de_catalogo(comp, CAT)


@pytest.mark.parametrize("servicio, cid, region", [  # la frase completa de un alias vetado sigue vetando con id ajeno
    ("Búsqueda de Azure AI", "az-foundry", "swedencentral"), ("Azure AI Search (S1)", "az-storage", "westeurope"),
    ("Servicio de agente de Foundry", "az-foundry", "northeurope")])
def test_frase_de_un_alias_vetado_con_un_catalogo_id_ajeno_se_veta(servicio, cid, region):
    comp = _comp(servicio, region, cid)
    motivo = experto.region_no_admitida(comp, CAT)
    assert motivo and "quita ese nombre" in motivo and V.region_no_admitida(comp, CAT) == motivo


@pytest.mark.parametrize("servicio, cid, region", [  # Revisión, I1.2: frase genérica en un servicio propio
    ("Microsoft Purview (seguridad del contenido)", "az-purview", "northeurope"),
    ("Azure Language: comprensión de contenido", "az-language", "italynorth"),
    ("Azure Language con IA de búsqueda", "az-language", "swedencentral")])
def test_servicio_propio_con_frase_generica_no_se_veta(servicio, cid, region):
    comp = _comp(servicio, region, cid)
    assert experto.region_no_admitida(comp, CAT) is None is V.region_no_admitida(comp, CAT)


def test_replica_de_la_puerta_identica_en_alias_y_aviso():
    assert V.AVISO_FUERA_DE_CATALOGO == experto.AVISO_FUERA_DE_CATALOGO
    assert V.alias_inequivocos(CAT) == experto.alias_inequivocos(CAT)
    assert not hasattr(experto, "palabras_inequivocas") and not hasattr(V, "palabras_inequivocas")  # REVER-2


def test_la_nota_del_revisor_lleva_el_aviso(docs, tmp_path):  # noqa: F811
    estado = estado_ejemplo()
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    c = resp["componentes"][3]
    c.update(servicio="Servidor de aplicaciones propio", catalogo_id=None)
    for p in resp["precios"]:  # REVER-1: un precio con el serviceName de un servicio del catálogo lo identificaría
        if p["componente_id"] == c["id"]:
            p["filtro"] = "serviceName eq 'Servidor propio del cliente' and armRegionName eq 'swedencentral'"
    estado["hash_contenido"] = docs.hashes.hash_contenido(estado)
    ruta = tmp_path / "OF-KELVARA-001-A-Nota-Revision.docx"
    docs.nr.generar(estado, CAT, ruta)
    textos = docs.nr.textos_docx(Document(str(ruta)))
    linea = [t for t in textos if experto.AVISO_FUERA_DE_CATALOGO in t]
    assert linea == ["• Componente C-04 «Servidor de aplicaciones propio» en swedencentral: "
                     f"{experto.AVISO_FUERA_DE_CATALOGO}."]
    ctx = types.SimpleNamespace(codigo="OF-KELVARA-001-A", docx=lambda: (textos, {}, None),
                                paquete=types.SimpleNamespace(ficheros={ruta.name: ruta}))
    ok = V.Comprobacion("experto", "x")
    V._exigir_aviso_en_nota(ok, ctx, "C-04", c)
    assert ok.estado == V.OK, ok.detalles
    sin = types.SimpleNamespace(**{**vars(ctx), "docx": lambda: ([t for t in textos if t not in linea], {}, None)})
    mal = V.Comprobacion("experto", "x")
    V._exigir_aviso_en_nota(mal, sin, "C-04", c)
    assert mal.estado == V.FALLA and "VER-1" in mal.detalles[0]


# ── VER-2: la lista blanca de `nubes` falla cerrado ante saltos de línea y sintaxis VTT ────────────────────────
VTT = ["Azure\n00:00:01.000 --> 00:00:02.000 y AWS", "Azure\n00:01.000 --> 00:02.000\ny AWS", "Azure <v y AWS>",
       "<v Ana>Azure</v>", "Azure\n\nNOTE y AWS", "WEBVTT\n\nNOTE x\n\nAzure", "Azure\nNOTE", "Azure\r\ny AWS",
       "Azure\n", "Azure\u2028y AWS", "Azure\x85", "Azure NOTE", "Azure --> AWS"]


@pytest.mark.parametrize("valor", VTT)
def test_nubes_con_sintaxis_vtt_falla_cerrado_igual_en_nucleo_y_puerta(valor):
    assert suficiencia.nubes_fuera_de_i1([valor]) and V.nubes_fuera_de_i1([valor]) == [valor]
    assert suficiencia.forma_nubes(valor) == V.forma_nubes(valor) not in suficiencia.NUBES_ADMITIDAS


@pytest.mark.parametrize("valor", ["Azure", "Microsoft  Azure", "Microsoft\tAzure", "Solo en Azure.", "«Azure»",
                                   "ÚNICAMENTE EN AZURE", "Azure ", " la solución debe vivir en Azure "])
def test_nubes_admitidas_siguen_pasando_y_la_forma_coincide(valor):
    assert suficiencia.nubes_fuera_de_i1([valor]) == [] == V.nubes_fuera_de_i1([valor])
    assert suficiencia.forma_nubes(valor) == V.forma_nubes(valor)


def test_el_motivo_de_nubes_con_sintaxis_lo_explica():
    (motivo,) = suficiencia.nubes_fuera_de_i1(["Azure\n00:00:01.000 --> 00:00:02.000 y AWS"])
    assert "saltos de línea o sintaxis de subtítulos" in motivo and "«Azure»" in motivo
