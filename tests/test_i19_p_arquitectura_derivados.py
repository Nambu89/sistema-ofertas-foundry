"""I1.9 · papel P: componente de datos sin salida hacia la solución (VA18-4) y errores derivados tras un rechazo
(PR18-4). Igualdad con la réplica en cada caso de reglas (i19_p_datos.reglas_i19)."""
from __future__ import annotations

import copy

from tests import i18_p_datos as P
from tests import i19_p_datos as D
from tests.test_i19_p_existentes import caso_h1
from nucleo import experto

CAT = D.catalogo_i19()


def sin_alternativos(catalogo: dict) -> dict:
    """El catálogo de I1.8 en lo que toca al factor: ninguna plantilla con factores_alternativos (E19-2)."""
    cat = copy.deepcopy(catalogo)
    for e in cat["componentes"]:
        for p in e.get("plantillas_precio") or []:
            p.pop("factores_alternativos", None)
    return cat


def con_blob(flujos: list, supuesto: dict | None = None):
    """Brezalia vB: Blob Storage añadido a la arquitectura (VA18-4), con los flujos dados."""
    br, req, r, cat = P.base()
    P.comp(r, "C-07", "az-storage", "Azure Blob Storage", "datos_conocimiento", "Hot LRS")
    P.comp(r, "C-08", "az-sharepoint", "SharePoint Online", "datos_conocimiento", "SharePoint Online", region="global",
           motivo_no_valoracion="licencia_fuera_de_azure")
    r["flujos"].append({"origen": "C-08", "destino": "C-02", "descripcion": "AI Search indexa SharePoint"})
    P.precio(r, "P-06", "C-07", "hot-lrs-datos", base_volumen={"cita": "Unos 3.000 documentos.", "cantidad_base": 3000,
                                                               "unidad_base": "documentos"})
    r["flujos"] += flujos
    if supuesto:
        r["supuestos"].append(supuesto)
    return br, req, r, cat


def test_caso_real_brezalia_vb_el_blob_que_nadie_lee_se_rechaza():
    br, req, r, cat = con_blob([{"origen": "C-08", "destino": "C-07", "descripcion": "Copia de los ficheros"}])
    assert D.reglas_i19(r, br, req, cat)["arquitectura"] == [("C-07", "datos_sin_salida")]
    errores, _ = P.analizar(r, br, req, cat)
    assert any(e.startswith("componentes.C-07: Azure Blob Storage es un componente de datos y ningún flujo") for e in errores)


def test_con_salida_o_con_quien_lo_consulta_vale():
    for flujo in ({"origen": "C-07", "destino": "C-02", "descripcion": "AI Search indexa los ficheros"},
                  {"origen": "C-04", "destino": "C-07", "descripcion": "La aplicación lee los ficheros"}):
        br, req, r, cat = con_blob([flujo])
        assert D.reglas_i19(r, br, req, cat)["arquitectura"] == []


def test_un_flujo_desde_otro_componente_de_datos_no_es_uso():
    br, req, r, cat = con_blob([{"origen": "C-02", "destino": "C-07", "descripcion": "El índice escribe en el blob"}])
    assert D.reglas_i19(r, br, req, cat)["arquitectura"] == [("C-07", "datos_sin_salida")]


def test_un_supuesto_que_lo_explica_y_nombra_el_servicio_lo_admite_y_la_nota_lo_dice():
    sup = {"id": "S-02", "texto": "Azure Blob Storage guarda una copia de trabajo de los ficheros para su auditoría.",
           "confianza": "MEDIA", "hechos": ["C-07"]}
    br, req, r, cat = con_blob([], sup)
    assert D.reglas_i19(r, br, req, cat)["arquitectura"] == []
    errores, c = P.analizar(r, br, req, cat)
    assert errores == []
    assert ("Componente de datos sin salida hacia la solución: Azure Blob Storage (C-07); se conserva por S-02: «" +
            sup["texto"] + "». Comprobar que alguien usa esos datos") in experto.lineas_para_revisor(c, cat, requisitos=req)
    sup_otro = dict(sup, texto="Los ficheros se guardan una temporada para auditarlos más adelante.")
    br, req, r, cat = con_blob([], sup_otro)
    assert D.reglas_i19(r, br, req, cat)["arquitectura"] == [("C-07", "datos_sin_salida")]


def test_caso_real_h1_tras_el_rechazo_no_viajan_errores_derivados():
    """PR18-4: en H1 (T2 1/3) el precio P-07 de API Management por llamadas se rechazó (base_no_casa) y el reintento
    llevó además «no es una cadena» y «corrige el catalogo_id», que eran falsos. Ahora solo van los errores ciertos.
    Cierre (E19-2): con el catálogo vigente las acciones ya tienen su factor y P-07 no se rechaza; el rechazo real se
    reproduce con el catálogo de entonces (sin factores alternativos). Lo nuevo, en test_i19_p_factor_base.py."""
    cat = sin_alternativos(CAT)
    r, br, req = caso_h1({"C-01": "EX-02", "C-07": "EX-03"}, quitar_c06=False)
    r["precios"].append({"id": "P-07", "componente_id": "C-06", "plantilla_id": "consumo-llamadas", "instancias": None,
                         "base_volumen": {"cita": "Aproximadamente 1.500 acciones al mes.", "cantidad_base": 1500,
                                          "unidad_base": "acciones al mes"},
                         "factor_override": {"valor": 1, "cita": "Aproximadamente 1.500 acciones al mes.",
                                             "justificacion": "Cada acción es una llamada a la API de RR. HH."}})
    errores, c = D.analizar(r, br, req, cat)
    assert c is None
    assert errores[0].startswith("precios.P-07: la cita «Aproximadamente 1.500 acciones al mes.» no habla de lo que "
                                 "cuenta la base")
    assert not any("no es una cadena" in e or "serviceName" in e or "corrige el catalogo_id" in e for e in errores)
    # Lo que es cierto con el resto de precios sí viaja: el API Management es del cliente y su nivel no es el por defecto
    assert any(e.startswith("componentes.C-06: Azure API Management se valora y el cliente ya lo tiene") for e in errores)
    assert any(e.startswith("componentes.C-06: Azure API Management no usa el nivel por defecto") for e in errores)
    assert len(errores) == 3


def test_un_medidor_obligatorio_que_falta_por_el_rechazo_no_se_pide():
    """El precio rechazado era el obligatorio: «falta_medidor_obligatorio» sería consejo falso (POR_AUSENCIA)."""
    br, req, r, cat = con_blob([{"origen": "C-07", "destino": "C-02", "descripcion": "AI Search indexa los ficheros"}])
    next(p for p in r["precios"] if p["id"] == "P-06")["base_volumen"]["cita"] = "Unas 2.000 consultas al mes."
    next(p for p in r["precios"] if p["id"] == "P-06")["base_volumen"]["cantidad_base"] = 2000
    errores, _ = P.analizar(r, br, req, cat)
    assert errores and all(e.startswith("precios.P-06") for e in errores)


def test_revision_un_canal_sin_computo_no_se_calla_por_un_rechazo_de_otro_componente():
    """Revisión I1.9: solo el rechazo de un precio de la clase cómputo puede explicar la falta de cómputo; con otro
    rechazado (aquí, AI Search), canal_sin_computo viaja en el mismo intento."""
    br, req, r, cat = P.base()
    r["precios"] = [p for p in r["precios"] if p["componente_id"] != "C-04"]   # sin cómputo valorado
    r["componentes"] = [c for c in r["componentes"] if c["id"] != "C-04"]
    r["flujos"] = [f for f in r["flujos"] if "C-04" not in (f["origen"], f["destino"])]
    r["flujos"].append({"origen": "C-03", "destino": "C-01", "descripcion": "El bot llama al modelo"})
    errores, _ = P.analizar(r, br, req, cat)
    assert any(e.startswith("componentes.C-03: Azure AI Bot Service se valora") for e in errores)
    next(p for p in r["precios"] if p["id"] == "P-03")["plantilla_id"] = "no-existe"       # rechazo ajeno al cómputo
    errores, _ = P.analizar(r, br, req, cat)
    assert any(e.startswith("precios.P-03: plantilla_id") for e in errores)
    assert any(e.startswith("componentes.C-03: Azure AI Bot Service se valora") for e in errores)


def test_revision_la_frase_del_canal_negada_no_vale():
    assert experto._dice_sin_computo("La solución no tiene cómputo propio: el bot llama al agente.")
    assert not experto._dice_sin_computo("No es cierto que la solución no tiene cómputo propio.")
    assert D.R19.dice_sin_computo_r("La solución no tiene cómputo propio.") and not D.R19.dice_sin_computo_r(
        "No es cierto que la solución no tiene cómputo propio.")
