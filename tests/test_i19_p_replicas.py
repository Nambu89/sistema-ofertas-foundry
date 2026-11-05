"""I1.9 · papel P: igualdad entre el núcleo y las réplicas para la puerta en casos al azar (semilla fija) sobre las dos
respuestas reales de Hostelia: recursos del cliente, niveles y razones, modelo, flujos y supuestos (LES-G-097). Cada
caso adverso tiene además su resultado esperado en tests/test_i19_p_*.py (LES-G-096.6)."""
from __future__ import annotations

import copy
import random

from tests import i19_p_datos as D
from nucleo import experto, suficiencia

CAT = D.catalogo_i19()
H1, H2 = "hostelia_1/lista_A", "hostelia_2/bloqueada"
EXS = ["EX-01", "EX-02", "EX-03", "EX-04", "EX-05", "EX-06", "EX-09", None]
CITAS = ["Aproximadamente 800 documentos.", "API Management", "Unos 200 GB de documentos.", "Microsoft Teams",
         "El cliente pide usar GPT-6 Sol.", "No es un entorno de pruebas.", "Es un entorno de pruebas.", "x"]
RAZONES = ["almacenamiento", "privado_red", "sla_replicas", "desarrollo_y_pruebas", "nivel_nombrado",
           "modelo_nombrado", "alta_disponibilidad", "otra"]
NIVELES = ["Basic", "S1", "Basic v2", "Consumption", "B1", "P0v3", "gpt-6-sol", "S9"]


def _variantes(n: int = 250):
    rnd = random.Random(1909)
    bases = []
    for sesion in (H1, H2):
        req = D.requisitos_hostelia(sesion)
        for v in ("Unos 200 GB de documentos.", "El cliente pide usar GPT-6 Sol.", "Es un entorno de pruebas.",
                  "No es un entorno de pruebas."):
            req["campos"]["volumetria" if "GB" in v else "alcance_funcional"]["entradas"].append(
                {"valor": v, "cita": "frase literal de la transcripción", "fuente": "F1", "origen": "CITADO"})
        br = D.brief_hostelia(sesion, req)
        bases.append((D.con_brief(D.a_v5(D.modelo_hostelia(sesion)), br), br, req))
    fijo = copy.deepcopy(bases[0])   # una subida con razón del nivel y una cita que no es de los requisitos
    next(p for p in fijo[0]["precios"] if p["componente_id"] == "C-05")["plantilla_id"] = "s1"
    D.comp_de(fijo[0], "C-05")["justificacion_nivel"] = {"nivel": "S1", "razon": "almacenamiento", "cita": "x"}
    yield fijo
    for _ in range(n):
        r, br, req = copy.deepcopy(rnd.choice(bases))
        for c in r["componentes"]:
            if rnd.random() < 0.3:
                ex = rnd.choice(EXS)
                c["existente_del_cliente"] = {"entrada": ex} if ex else None
                c["motivo_no_valoracion"] = rnd.choice(["existente_del_cliente", "no_aplica", "licencia_fuera_de_azure"])
            if rnd.random() < 0.3:
                c["justificacion_nivel"] = None if rnd.random() < 0.3 else {
                    "nivel": rnd.choice(NIVELES), "razon": rnd.choice(RAZONES), "cita": rnd.choice(CITAS)}
            if rnd.random() < 0.15:
                c["desviacion_justificada"] = rnd.choice([None, "El de EX-05 aloja la API del cliente; hace falta otro.",
                                                         "Hace falta uno propio para la solución del asistente."])
        if rnd.random() < 0.4:
            r["precios"] = [p for p in r["precios"] if rnd.random() < 0.8]
        if rnd.random() < 0.3:
            r["flujos"] = [f for f in r["flujos"] if rnd.random() < 0.7]
        if rnd.random() < 0.2:
            r["supuestos"].append({"id": "S-09", "texto": rnd.choice([
                "La solución no tiene cómputo propio: el bot llama al agente.",
                "No es cierto que la solución no tiene cómputo propio.", "Azure AI Search guarda una copia de trabajo."]),
                "confianza": "MEDIA", "hechos": [rnd.choice(["C-02", "C-03", "C-04", "C-05"])]})
        if rnd.random() < 0.2:
            for p in r["precios"]:
                if p["plantilla_id"].startswith("gpt-6-luna"):
                    p["plantilla_id"] = p["plantilla_id"].replace("gpt-6-luna", "gpt-6-sol")
        yield r, br, req


def test_replicas_iguales_al_nucleo_en_250_casos_al_azar():
    vistas: set = set()
    for r, br, req in _variantes():
        reglas = D.reglas_i19(r, br, req, CAT)   # asserts de igualdad dentro
        vistas |= {regla for k in ("volumen_nivel", "existentes", "arquitectura") for _, regla in reglas[k]}
    faltan = {"existente_desconocido", "existente_repetido", "existente_otro_servicio", "existente_sin_motivo",
              "motivo_sin_existente", "existente_con_nivel", "existente_valorado", "canal_sin_computo",
              "datos_sin_salida", "justificacion_sobrante", "razon_desconocida", "razon_no_cumplida",
              "requisito_no_literal", "nivel_desconocido", "modelo_sin_justificar"} - vistas
    assert not faltan, faltan   # nada de verdes vacíos (LES-G-099.5)


def test_requisitos_iguales_a_la_replica_en_casos_al_azar():
    rnd = random.Random(19)
    vistas: set = set()
    for _ in range(200):
        entradas = D.entradas_existentes()
        for e in entradas:
            if rnd.random() < 0.2:
                e["valor"] = rnd.choice(["Su App Service propio", "App Service propio, publicada con API Management",
                                         "Teams", "SharePoint", e["valor"]])
            if rnd.random() < 0.15:
                e["servicio_catalogo"] = rnd.choice([None, "az-no-existe", "az-app-service", "az-teams"])
            if rnd.random() < 0.1:
                e["id"] = "EX-01"
        if rnd.random() < 0.3:
            entradas = [e for e in entradas if rnd.random() < 0.7]
        nucleo = suficiencia.reglas_existentes(entradas, CAT)
        assert nucleo == D.R19.existentes_requisitos_r(entradas, CAT)
        vistas |= {regla for _, regla in nucleo}
    assert vistas == {"existente_id_repetido", "existente_valor_no_literal", "existente_servicio_desconocido",
                      "existente_valor_otro_servicio", "existente_recurso_sin_entrada"}
    assert suficiencia.reglas_existentes([], None) == D.R19.existentes_requisitos_r([], None)


def test_brief_y_lectura_del_catalogo_iguales_a_la_replica():
    for fila in CAT["componentes"]:
        n_nucleo = [(n["nombres"], n["razones"]) for n in experto.niveles_de(fila)]
        n_replica = [(n["nombres"], n["razones"]) for n in D.R19._niveles_r(fila)]
        assert n_nucleo == n_replica, fila["id"]
        assert (experto.nivel_por_defecto(fila) or {}).get("nombres") == (D.R19.nivel_defecto_r(fila) or {}).get("nombres")
    for m in ("gpt-6-sol", "gpt-6.1-sol", "gpt-6-luna", "gpt-5"):
        assert experto.razones_modelo(CAT, m) == D.R19.razones_modelo_r(CAT, m)
    assert experto.modelo_por_defecto(CAT) == D.R19.modelo_defecto_r(CAT) == "gpt-6-luna"
