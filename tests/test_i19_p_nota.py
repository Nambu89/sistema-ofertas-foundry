"""I1.9 · papel P: la nota de la versión B explica lo que cambia en la estimación, calculado por código (VA18-3), y el
título de «Cambios pedidos» va una sola vez (VA18-8). Datos: la sesión 2 real de Brezalia (I1.8), versiones A y B."""
from __future__ import annotations

import copy
import json

from tests.i17_p_datos import RAIZ
from nucleo import nota_revision as nr

DIR = RAIZ / "pruebas" / "I18" / "REAL" / "B" / "sesion_2"
CAT = json.loads((RAIZ / "sandbox" / "datos" / "catalogo_componentes.json").read_text(encoding="utf-8"))


def estados():
    a = json.loads((DIR / "lista_A" / "estado.json").read_text(encoding="utf-8"))
    b = json.loads((DIR / "lista_B" / "estado.json").read_text(encoding="utf-8"))
    return a, b


def con_estimacion_devuelta(b: dict, a: dict) -> dict:
    """La DEVUELTA con version_devuelta.estimacion (lo que propone CAMBIOS-I19-P para decision.resumen_version)."""
    b = copy.deepcopy(b)
    next(d for d in b["decisiones"] if d.get("version_devuelta"))["version_devuelta"]["estimacion"] = \
        nr.resumen_estimacion(a)
    return b


def test_la_nota_de_la_version_b_dice_duracion_horas_perfiles_y_fases_que_cambian():
    a, b = estados()
    lineas = nr.lineas_cambios_nota(con_estimacion_devuelta(b, a), CAT)
    estimacion = [x for x in lineas if x.startswith("Estimación: ")]
    assert estimacion == [
        "Estimación: duración de 3 a 5 semanas",
        "Estimación: horas totales de 197 a 213 (+16 h)",
        "Estimación: horas del perfil «AI Architect / Tech Lead» de 17 a 49",
        "Estimación: horas del perfil «Senior AI / Foundry Engineer» de 65 a 98",
        "Estimación: sale el perfil «Integration Engineer / Salesforce» (26 h)",
        "Estimación: horas del perfil «AI Engineer / Tech Lead» de 62 a 36",
        "Estimación: horas del perfil «Project Manager» de 27 a 30",
        "Estimación: sale la fase «Diseño funcional y técnico» (36 h)",
        "Estimación: horas de la fase «Construcción» de 92 a 91",
        "Estimación: horas de la fase «Pruebas y despliegue» de 42 a 27",
        "Estimación: horas de la fase «Gestión de proyecto» de 27 a 30",
        "Estimación: entra la fase «Diseño» (46 h)",
        "Estimación: entra la fase «Integración» (19 h)",
        "Estimación: tareas de 8 a 8, 0 sin cambios: la estimación se ha recalculado entera (ver las dos estimaciones)"]
    assert lineas.index(estimacion[0]) > lineas.index("- Precio cerrado: de 12.668,75 € a 13.878,75 €")


def test_sin_la_estimacion_devuelta_la_nota_lo_dice_y_no_calla():
    _, b = estados()
    lineas = nr.lineas_cambios_nota(b, CAT)
    assert lineas[-1] == nr.AVISO_SIN_ESTIMACION


def test_sin_cambios_lo_dice_y_cuenta_igual_las_tareas():
    a, _ = estados()
    r = nr.resumen_estimacion(a)
    assert nr.lineas_estimacion(r, r) == ["Estimación: duración sin cambios (3 semanas)",
                                          "Estimación: horas totales sin cambios (197)"]
    otro = copy.deepcopy(r)
    otro["tareas"][0]["tecnicas_h"] += 2
    assert nr.lineas_estimacion(r, otro)[-1] == ("Estimación: tareas de 8 a 8, 7 sin cambios: la estimación se ha "
                                                 "replanificado (ver las dos estimaciones)")


def test_horas_en_formato_espanol():
    assert [nr._horas(x) for x in ("213.00", "30.50", 1200, "0.00", "-16.00", "n/d")] == [
        "213", "30,5", "1.200", "0", "-16", "n/d"]


def test_el_titulo_de_cambios_pedidos_va_una_vez_y_cada_linea_en_su_parrafo():
    a, b = estados()
    b = con_estimacion_devuelta(b, a)
    doc = nr.construir(b, CAT, transcripcion="")
    textos = nr.textos_docx(doc)
    lineas = nr.lineas_cambios_nota(b, CAT)
    assert textos.count("Cambios pedidos en la revisión anterior (versión A, DEVUELTA)") == 1
    assert "Cambios pedidos en la revisión anterior" not in textos
    assert all(x in textos for x in lineas)


def test_va18_18_la_nota_de_la_aprobada_registra_las_decisiones_en_vez_de_como_decidir():
    """Caso real: la nota final de Brezalia (sesión 2 de I1.8, APROBADA) conservaba «9. Cómo decidir» con las líneas
    para enviar y devolver, y no decía quién aprobó ni cuándo."""
    final = json.loads((DIR / "final" / "estado.json").read_text(encoding="utf-8"))
    assert final["estado"] == "APROBADA"
    textos = nr.textos_docx(nr.construir(final, CAT, transcripcion=""))
    assert "9. Registro de decisiones" in textos and "9. Cómo decidir" not in textos
    assert not any(t.startswith("DECISION | ") for t in textos)   # ninguna línea para copiar
    registro = nr.lineas_registro_decisiones(final)
    assert len(registro) == len(final["decisiones"]) and all(x in textos for x in registro)
    aprobadas = [x for x in registro if " · APROBADA · " in x]
    assert [x.split(" · ")[2] for x in aprobadas] == ["Responsable de preventa", "Responsable de área"]
    assert all(x.split(" · ")[1] == d["fecha"] for x, d in zip(registro, final["decisiones"]))


def test_va18_18_antes_de_aprobar_sigue_como_decidir():
    _, b = estados()
    textos = nr.textos_docx(nr.construir(b, CAT, transcripcion=""))
    assert "9. Cómo decidir" in textos and "9. Registro de decisiones" not in textos


def test_va18_18_un_comentario_con_palabra_reservada_se_retira_y_se_avisa():
    final = json.loads((DIR / "final" / "estado.json").read_text(encoding="utf-8"))
    final = copy.deepcopy(final)
    final["decisiones"][-1]["comentarios"] = "Aprobada; TBD revisar el anexo"
    from nucleo import hashes
    final["hash_contenido"] = hashes.hash_contenido(final)
    textos = nr.textos_docx(nr.construir(final, CAT, transcripcion=""))
    assert nr.RETIRADO in textos and any(t.startswith("Texto retirado de la nota (registro de decisiones)") for t in textos)
