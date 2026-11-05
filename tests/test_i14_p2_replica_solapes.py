"""Prueba de igualdad réplica/núcleo de los solapes del diagrama (ARR13-2). Para el integrador: copiar a
tests/test_i14_p2_replica_solapes.py una vez aplicado el parche a verificar_paquete.py.

LES-G-099.5: la comparación diferencial exige casos de los dos lados (con y sin solapes) o falla.
"""
from __future__ import annotations

import pathlib
import random
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if not (RAIZ / "verificar_paquete.py").is_file():  # ejecutada desde pruebas/I14/P2
    RAIZ = pathlib.Path(__file__).resolve().parents[3]
for p in (str(RAIZ), str(RAIZ / "sandbox")):
    if p not in sys.path:
        sys.path.insert(0, p)

import verificar_paquete as vp  # noqa: E402
from nucleo import pptx_revision as pr  # noqa: E402


def test_mismas_constantes():
    assert (vp.PREFIJO_COMPONENTE, vp.PREFIJO_BANDA) == (pr.PREFIJO_COMPONENTE, pr.PREFIJO_BANDA)
    assert tuple(vp.TITULOS_BANDA) == tuple(pr.TITULOS_BANDA)


def test_diferencial_aleatoria():
    azar, con, sin = random.Random(20261010), 0, 0
    nombres = ["Componente 1", "Componente 2", "Componente 3", "Banda Identidad, seguridad y red",
               "Banda Operación y observabilidad", "CuadroTexto 7", "Rectángulo 9"]
    textos = ["", "Azure AI Search", "Identidad, seguridad y red", "Operación y observabilidad", "SharePoint"]
    for _ in range(4000):
        formas = []
        for _ in range(azar.randint(1, 7)):
            x, y = azar.randint(0, 2000), azar.randint(0, 2000)
            w, h = azar.choice([0, -5, azar.randint(1, 900)]), azar.randint(1, 900)
            formas.append((azar.choice(nombres), azar.choice(textos), x, y, w, h))
        a, b = vp.solapes_diagrama_replica(formas), pr.solapes_diagrama(formas)
        assert a == b, formas
        con += bool(a)
        sin += not a
    assert con >= 200 and sin >= 200, (con, sin)  # con la semilla fija: unas 3.660 y 340


def test_sobre_el_pptx_real_lector_identico(tmp_path):
    sys.path.insert(0, str(RAIZ / "pruebas" / "I14" / "P2"))
    import paquete_capas
    est, cat, _ = paquete_capas.construir_estado()
    prs, informe = pr.construir(est, cat)
    ruta = tmp_path / "replica.pptx"  # integrador I1.4: fuera del repositorio (antes pisaba y borraba la evidencia de P2)
    pr.guardar_atomico(prs, ruta)
    d4 = vp.leer_pptx(ruta).diapositivas[3]
    assert vp.formas_diagrama(d4) == pr.formas_de(prs.slides[3])
    assert informe["modo"] == "diagrama" and vp.solapes_diagrama_replica(vp.formas_diagrama(d4)) == []


def test_filas_no_valoradas_replica_igual_al_nucleo():
    from nucleo import anexo_consumo
    azar = random.Random(1010)
    motivos = [anexo_consumo.MOTIVO_SAAS, anexo_consumo.MOTIVO_SIN_PRECIO, anexo_consumo.MOTIVO_SIN_PRECIO_PUBLICO]
    servicios = ["Microsoft Teams", "Microsoft Entra ID", "SharePoint Online", "Azure Monitor", "Azure Policy",
                 "Microsoft Foundry", "Azure AI Bot Service"]
    vistos_varios = 0
    for _ in range(2000):
        nvs = [{"componente_id": f"C-{i:02d}", "servicio": azar.choice(servicios), "motivo": azar.choice(motivos)}
               for i in range(azar.randint(0, 8))]
        assert vp.filas_no_valoradas_replica(nvs) == pr.filas_no_valoradas(nvs), nvs
        vistos_varios += any(" y " in f[0] for f in pr.filas_no_valoradas(nvs))
    assert vistos_varios >= 500


def _contexto_diagrama(ruta, est, cat):
    """Lo mínimo que usa c_diagrama: el PPTX leído por la puerta, la respuesta del experto, el catálogo y (I1.9, nombres
    de los sistemas del cliente) la carga."""
    import types
    leido = vp.leer_pptx(ruta)
    return types.SimpleNamespace(pptx=lambda: leido, respuesta=est["carga"]["respuestas_expertos"]["azure"]["respuesta"],
                                 catalogo_obj=cat, carga=est["carga"])  # I1.9: c_diagrama lee los requisitos y los textos


def test_c_diagrama_y_diapositiva_8_sobre_el_pptx_real(tmp_path):
    sys.path.insert(0, str(RAIZ / "pruebas" / "I14" / "P2"))
    import paquete_capas
    from nucleo import anexo_consumo
    est, cat, _ = paquete_capas.construir_estado()
    prs, _ = pr.construir(est, cat)
    bueno = tmp_path / "bueno.pptx"
    pr.guardar_atomico(prs, bueno)
    c = vp.c_diagrama(_contexto_diagrama(bueno, est, cat))
    assert c.estado != vp.FALLA, c.detalles
    # diapositiva 8: lo que hace c_coherencia parcheada, con los mismos datos
    d8 = vp.leer_pptx(bueno).diapositivas[7]
    filas8 = [[vp.plano(x) for x in f] for t in d8.tablas for f in t]
    esperadas = vp.filas_no_valoradas_replica(anexo_consumo.no_valorados(est, cat))
    assert all([vp.plano(x) for x in f] in filas8 for f in esperadas)
    assert sum(1 for f in filas8 if "no valorado" in f) == len(esperadas)
    usadas: list[int] = []
    for ln, tcl in zip(est["carga"]["anexo_consumo"]["lineas"], est["carga"]["textos_cliente"]["consumo"]["lineas"]):
        assert vp._fila_propia(d8.tablas, ln["servicio"], tcl["concepto"], usadas) is not None
    # rotura: la banda de identidad sube y tapa la última caja de su columna (ARR13-2)
    banda = next(f for f in prs.slides[3].shapes if f.name.startswith(pr.PREFIJO_BANDA))
    banda.top = banda.top - 300000
    roto = tmp_path / "roto.pptx"
    prs.save(str(roto))
    c = vp.c_diagrama(_contexto_diagrama(roto, est, cat))
    assert c.estado == vp.FALLA and any("tapa o corta" in m and "ARR13-2" in m for m in c.detalles), c.detalles


def test_casos_fijos_con_resultado_esperado():
    """Revisión de la revisión independiente R2: además de la igualdad, el resultado esperado de cada regla, en los dos lados."""
    banda1 = ("Banda Identidad, seguridad y red", "", 0, 1000, 5000, 500)
    banda2 = ("Banda Operación y observabilidad", "", 0, 1400, 5000, 500)          # pisa a la primera
    tapado = ("Componente 1", "Azure Blob Storage", 0, 800, 1000, 400)
    dentro = ("Componente 2", "Microsoft Entra ID", 100, 1050, 1000, 300)
    casos = [([banda1, banda2], "se solapa con la banda"), ([tapado, banda1], "tapa o corta"),
             ([dentro, banda1], "tapa o corta"), ([banda1, dentro], None)]
    for formas, esperado in casos:
        for f in (vp.solapes_diagrama_replica, pr.solapes_diagrama):
            fallos = f(formas)
            assert (fallos == []) if esperado is None else any(esperado in x for x in fallos), (f, formas, fallos)
