"""I1.8 · papel P: REVERIF17-2 (medidores obligatorios por nivel, valor por defecto de la fila y clase cómputo) y
REVERIF17-3 (tope de instancias del nivel y justificación con más de una). Lo que E pone en el catálogo se simula aquí
sobre el catálogo real; el núcleo y la réplica de la puerta dan lo mismo en cada caso (tests/i18_p_datos.reglas)."""
from __future__ import annotations

from tests.i18_p_datos import B1_DOS, B1_RAZON, analizar, base, comp, fila, precio, reglas
from nucleo import experto

S1 = {"nivel": "S1", "requisito": "Unos 3.000 documentos.",
      "limite_oficial": "S1: 25 GB de almacenamiento por partición", "fuente": None}


def _con_niveles_container_apps(cat: dict):
    f = fila(cat, "az-container-apps")
    f["niveles"] = [{"nivel": "Dedicado D4", "plantillas": ["dedicado-vcpu", "dedicado-memoria", "dedicado-gestion"],
                     "limites": ["D4: 4 núcleos y 16 GiB por nodo"], "instancias_max": 10,
                     "fuente_url": "https://learn.microsoft.com/azure/container-apps/workload-profiles-overview",
                     "medidores_obligatorios": ["dedicado-vcpu", "dedicado-memoria", "dedicado-gestion"]}]


def test_reverif17_2_container_apps_sin_niveles_en_el_catalogo_falla_cerrado():
    brief, req, r, cat = base()
    fila(cat, "az-container-apps").pop("niveles", None)                  # el catálogo de I1.7: sin niveles
    fila(cat, "az-container-apps").pop("medidores_obligatorios", None)
    comp(r, "C-07", "az-container-apps", "Azure Container Apps", "aplicacion_integracion", "Dedicado")
    precio(r, "P-10", "C-07", "dedicado-gestion", instancias=1)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("C-07", "computo_sin_niveles")]


def test_reverif17_2_medidores_obligatorios_del_nivel_y_justificacion():
    brief, req, r, cat = base()
    _con_niveles_container_apps(cat)
    comp(r, "C-07", "az-container-apps", "Azure Container Apps", "aplicacion_integracion", "Dedicado")
    precio(r, "P-10", "C-07", "dedicado-gestion", instancias=1)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("C-07", "falta_medidor_obligatorio"),
                                                           ("C-07", "nivel_sin_justificar")]


def test_reverif17_2_toda_la_clase_computo_se_justifica_aunque_se_valore_por_volumen():
    brief, req, r, cat = base()
    fila(cat, "az-logic-apps").pop("niveles", None)
    comp(r, "C-07", "az-logic-apps", "Azure Logic Apps", "aplicacion_integracion", "Consumo",
         motivo_no_valoracion="depende_del_volumen")
    precio(r, "P-10", "C-07", "consumo-conector-empresarial")
    assert ("C-07", "computo_sin_niveles") in reglas(r, brief, req, cat)["volumen_nivel"]
    cat["computo_por_defecto"]["filas"] = ["az-app-service", "az-functions"]   # fuera de la clase: sin justificación
    assert ("C-07", "computo_sin_niveles") not in reglas(r, brief, req, cat)["volumen_nivel"]


def test_reverif17_2_hosted_de_foundry_es_un_computo():
    brief, req, r, cat = base()
    f = fila(cat, "az-foundry-agent-service")
    f.pop("niveles", None)
    for pl in f["plantillas_precio"]:                                    # por tiempo (I1.7) o por volumen (E, I1.8)
        if pl["id"] in ("hosted-vcpu", "hosted-memoria"):
            pl.update(impulsor="tiempo", divisor=1)
    comp(r, "C-07", "az-foundry-agent-service", "Foundry Agent Service", "ia", "Hosted")
    precio(r, "P-10", "C-07", "hosted-vcpu", instancias=1)
    precio(r, "P-11", "C-07", "hosted-memoria", instancias=1)
    assert ("C-07", "computo_sin_niveles") in reglas(r, brief, req, cat)["volumen_nivel"]


def test_reverif17_2_nivel_por_defecto_de_la_fila_no_exige_justificacion():
    brief, req, r, cat = base()
    assert reglas(r, brief, req, cat)["volumen_nivel"] == []                 # control: C-02 Basic, por defecto
    fuente = "https://learn.microsoft.com/azure/search/search-sku-tier"
    # I1.9 (VC18-1): el nivel por defecto vale solo como {nivel, fuente https}; sin fuente, se justifica (falla cerrado)
    for valor, esperado in (({"nivel": "Basic", "fuente": fuente}, []), ("Basic", [("C-02", "nivel_sin_justificar")]),
                            ({"nivel": "Basic", "motivo": "piloto"}, [("C-02", "nivel_sin_justificar")]),
                            ({"nivel": "Basic", "fuente": "http://x"}, [("C-02", "nivel_sin_justificar")]),
                            ({"nivel": "S3", "fuente": fuente}, [("C-02", "nivel_sin_justificar")]),
                            (7, [("C-02", "nivel_sin_justificar")])):
        fila(cat, "az-ai-search")["nivel_por_defecto"] = valor
        assert reglas(r, brief, req, cat)["volumen_nivel"] == esperado, valor
    fila(cat, "az-ai-search")["nivel_por_defecto"] = {"nivel": "Basic", "fuente": fuente}
    r["precios"][2]["plantilla_id"] = "s1"                                  # otro nivel sin justificar
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("C-02", "nivel_sin_justificar")]


def test_reverif17_2_en_la_clase_computo_solo_vale_el_computo_por_defecto():
    brief, req, r, cat = base()
    fila(cat, "az-functions")["nivel_por_defecto"] = "EP1"
    comp(r, "C-07", "az-functions", "Azure Functions", "aplicacion_integracion", "EP1")
    precio(r, "P-10", "C-07", "premium-vcpu", instancias=1)
    precio(r, "P-11", "C-07", "premium-memoria", instancias=1)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("C-07", "nivel_sin_justificar")]
    cat["computo_por_defecto"]["filas"] = ["az-app-service"]                 # la clase la puede fijar el catálogo
    fila(cat, "az-functions")["nivel_por_defecto"] = {"nivel": "EP1", "fuente": "https://learn.microsoft.com/x"}
    assert reglas(r, brief, req, cat)["volumen_nivel"] == []
    assert experto.filas_computo(cat) == ("az-app-service",)
    assert experto.filas_computo({}) == experto.FILAS_COMPUTO


def test_reverif17_3_mas_instancias_que_el_tope_del_nivel():
    brief, req, r, cat = base()
    fila(cat, "az-app-service")["niveles"][0].update(instancias_max=3, razones_subida=B1_RAZON)
    r["precios"][4]["instancias"] = 4
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("P-05", "instancias_sobre_limite"),
                                                           ("C-04", "instancias_sin_justificar")]
    r["componentes"][3]["justificacion_nivel"] = dict(B1_DOS)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("P-05", "instancias_sobre_limite")]


def test_reverif17_3_dos_instancias_exigen_justificacion_que_ve_el_revisor():
    brief, req, r, cat = base()
    fila(cat, "az-app-service")["niveles"][0].update(instancias_max=3, razones_subida=B1_RAZON)
    r["precios"][4]["instancias"] = 2
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("C-04", "instancias_sin_justificar")]
    r["componentes"][3]["justificacion_nivel"] = dict(B1_DOS)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == []
    errores, completada = analizar(r, brief, req, cat)
    assert errores == []
    lineas = experto.lineas_para_revisor(completada, cat)
    assert any("Instancias de Azure App Service (C-04), plantilla b1-linux (desde el precio P-05): 2 (tope del nivel "
               "B1: 3); justificadas por la razón «tecnicos_sobre_uno» con «60 técnicos.»" in x for x in lineas), lineas
    r["componentes"][3]["justificacion_nivel"] = dict(B1_DOS, cita="Unos 3.000 documentos.")  # no cuenta técnicos
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("C-04", "razon_no_cumplida")]
    fila(cat, "az-app-service")["niveles"][0]["razones_subida"] = None               # B1 sin razones (catálogo real)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("C-04", "nivel_sin_razones")]


def test_reverif17_3_partir_las_instancias_en_lineas_no_esquiva_el_tope():
    brief, req, r, cat = base()
    fila(cat, "az-app-service")["niveles"][0].update(instancias_max=3, razones_subida=B1_RAZON)
    precio(r, "P-10", "C-04", "b1-linux", instancias=1)                     # 1 + 1: dos instancias
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("C-04", "instancias_sin_justificar")]
    precio(r, "P-11", "C-04", "b1-linux", instancias=2)                     # 1 + 1 + 2: cuatro, por encima de 3
    r["componentes"][3]["justificacion_nivel"] = dict(B1_DOS)
    assert reglas(r, brief, req, cat)["volumen_nivel"] == [("P-05", "instancias_sobre_limite")]


def test_reverif17_3_tope_mal_declarado_falla_cerrado():
    for tope in (0, -1, "3", True, 2.5):
        brief, req, r, cat = base()
        fila(cat, "az-app-service")["niveles"][0]["instancias_max"] = tope
        assert reglas(r, brief, req, cat)["volumen_nivel"] == [("P-05", "instancias_max_no_valido")], tope


def test_reverif17_3_instancias_de_un_servicio_sin_niveles_ni_computo_no_se_limitan():
    brief, req, r, cat = base()
    comp(r, "C-07", "az-private-link", "Azure Private Link", "identidad_seguridad_red", "Punto de conexión")
    precio(r, "P-10", "C-07", "punto-conexion", instancias=4)
    assert ("C-07", "instancias_sin_justificar") not in reglas(r, brief, req, cat)["volumen_nivel"]
