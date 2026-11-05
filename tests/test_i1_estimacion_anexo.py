"""Pruebas de sandbox/nucleo/anexo_consumo.py (constructor B). Sin red."""
from __future__ import annotations

import copy
import json

import pytest

from tests.test_i1_estimacion_comun import EJEMPLOS, ejemplo, aislar, estado_base, preparar_nucleo, sha256_fichero

M = preparar_nucleo()
A, errores, esquema = M["anexo_consumo"], M["errores"], M["esquema"]


@pytest.fixture(autouse=True)
def _aislado(monkeypatch):
    aislar(monkeypatch)

PALETA = {"F8485E", "3C3C3A", "FFFFFF", "F2F2F1", "BFBFBF"}


@pytest.fixture()
def estado() -> dict:
    return estado_base()


@pytest.fixture()
def catalogo() -> dict:
    return A.cargar_catalogo(EJEMPLOS / "catalogo_componentes.json")


def _elemento(estado: dict, pid: str) -> dict:
    return next(e for e in estado["carga"]["verificacion"]["respuesta"]["elementos"] if e["id"] == pid)


def _precio(estado: dict, pid: str) -> dict:
    return next(p for p in estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["precios"] if p["id"] == pid)


def _v2(estado: dict) -> dict:
    """Contrato v2 (I1.5): Foundry y Bot Service, facturables sin precio, declaran su motivo (PR15-2)."""
    for c in estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["componentes"]:
        c.setdefault("motivo_no_valoracion", {"C-01": "depende_del_volumen", "C-03": "depende_del_volumen"}.get(
            c["id"], "no_aplica"))
    return estado


def test_calcular_reproduce_lineas_y_totales_del_ejemplo(estado, catalogo):
    _v2(estado)
    antes = copy.deepcopy(estado)
    anexo = A.calcular(estado, catalogo)
    esperado = ejemplo("anexo_consumo")
    assert anexo["lineas"] == esperado["lineas"]
    # I1.9 (P, intento 1): el ejemplo valora el cómputo por defecto (App Service B1); antes, 338,87 y 4.066,44
    assert (anexo["total_mensual_eur"], anexo["total_anual_eur"]) == ("287.33", "3447.96")  # I1.6: Private Endpoint real (0,0088 €/h)
    assert anexo["avisos"] == [
        A.AVISO_MONEDA,  # integrador I1.7: sin veredicto de precios, ya no hay «P-03 sin contraste independiente»
        "Microsoft Foundry: no valorado. A valorar con el volumen real, así que no suma en el total orientativo.",
        "Azure AI Bot Service: no valorado. A valorar con el volumen real, así que no suma en el total orientativo.",
        "Microsoft Entra ID: no valorado. Se licencia aparte, no se factura por Azure, así que no suma "
        "en el total orientativo.",  # REV13-3 y PR15-2: el motivo concreto no va al cliente
        # I1.7 (papel P): la fecha de la instantánea y el total que solo suma lo valorado
        "Precios consultados el 2026-10-08 en Azure Retail Prices (instantánea descargada por el código al desplegar).",
        "El total solo suma los conceptos valorados: 3 componentes quedan como «No valorado»."]
    assert anexo["fuente"] == esperado["fuente"] and anexo["nota_fija"] == esperado["nota_fija"]
    assert esquema.validar(anexo, esquema.cargar("anexo_consumo")) == []
    assert estado == antes                                       # puro


def test_respuesta_v1_conserva_el_texto_de_entonces_y_la_v2_sin_motivo_se_rechaza(estado, catalogo):
    """Una respuesta v1 (sin el campo) solo llega al recomponer un paquete antiguo: conserva su texto. En la v2, un
    facturable sin precio ni motivo no deja componer el anexo (PR15-2)."""
    v1 = copy.deepcopy(estado)
    for c in v1["carga"]["respuestas_expertos"]["azure"]["respuesta"]["componentes"]:
        c.pop("motivo_no_valoracion", None)
    assert any(a.startswith("Microsoft Foundry: no valorado. No se ha obtenido") for a in A.calcular(v1, catalogo)["avisos"])
    _v2(estado)
    estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["componentes"][0]["motivo_no_valoracion"] = "no_aplica"
    with pytest.raises(errores.ReglaIncumplida) as ex:
        A.calcular(estado, catalogo)
    assert [e for e in ex.value.errores if "PR15-2" in e] and all(e.startswith("Anexo: C-01") for e in ex.value.errores)


def test_aviso_de_moneda_cabe_en_el_esquema():
    assert 5 <= len(A.AVISO_MONEDA) <= 300 and "USD" in A.AVISO_MONEDA


def test_detalle_sku_y_estado(estado, catalogo):
    det = A.detalle_lineas(estado, catalogo)
    # integrador I1.7 (CAMBIOS-I17-P §4): el precio sale de la instantánea; el estado de la línea lo dice
    assert det["P-01"] == {"sku": "Standard S1", "estado": "INSTANTÁNEA DE PRECIOS"}
    assert det["P-03"]["estado"] == "INSTANTÁNEA DE PRECIOS"


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): DISCREPA del verificador sobre un precio dentro del 0,5 %; imposible por construcción (el verificador ya no recibe precios: el precio sale de la instantánea del despliegue). Lo vigente: la regla sigue en el anexo para respuestas v3 (puerta de su época); es_observacion_no_precio en tests/test_i17_p_anexo_nota.py")
def test_discrepa_dentro_del_medio_por_ciento_es_orientativo(estado, catalogo):
    e = _elemento(estado, "P-01")
    e.update(veredicto="DISCREPA", valor_correcto="0.3430", fuente_url="https://prices.azure.com/api/retail/prices")
    anexo = A.calcular(estado, catalogo)
    assert anexo["lineas"][0]["verificacion"] == "OK" and anexo["lineas"][0]["precio_unitario"] == 0.3426
    assert any(a.startswith("P-01: el verificador indica 0.3430 EUR") for a in anexo["avisos"])
    assert A.detalle_lineas(estado, catalogo)["P-01"]["estado"] == "ORIENTATIVO"


@pytest.mark.skip(reason="I1.7 (decisión 1, integrador): DISCREPA del verificador sobre un precio fuera de tolerancia; imposible por construcción (el verificador ya no recibe precios: el precio sale de la instantánea del despliegue). Lo vigente: tests/test_i17_p_anexo_nota.py")
@pytest.mark.parametrize("valor", ["0.40", None, "no es un número"])
def test_discrepa_fuera_de_tolerancia_falla(estado, catalogo, valor):
    _elemento(estado, "P-01").update(veredicto="DISCREPA", valor_correcto=valor)
    with pytest.raises(errores.ReglaIncumplida):
        A.calcular(estado, catalogo)


def test_discrepa_efectivo_y_verificacion_no_superada(estado, catalogo):
    estado["carga"]["verificacion"]["resultado"]["discrepa"] = [{"id": "P-02"}]
    with pytest.raises(errores.ReglaIncumplida):
        A.calcular(estado, catalogo)
    estado["carga"]["verificacion"]["resultado"] = {"verificada": False}
    with pytest.raises(errores.ReglaIncumplida):
        A.calcular(estado, catalogo)


def test_sin_respuesta_del_experto(estado, catalogo):
    estado["carga"]["respuestas_expertos"] = {}
    with pytest.raises(errores.ReglaIncumplida):
        A.calcular(estado, catalogo)


def test_desviacion_usa_el_nombre_del_experto_y_avisa(estado, catalogo):
    comp = next(c for c in estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["componentes"] if c["id"] == "C-04")
    comp.update(catalogo_id=None, servicio="Azure Container Apps",
                desviacion_justificada="Se prefiere un servicio sin servidor para el escalado a cero de noche.")
    anexo = A.calcular(estado, catalogo)
    assert anexo["lineas"][1]["servicio"] == "Azure Container Apps"
    assert any("fuera del catálogo" in a for a in anexo["avisos"])


def test_componente_que_no_esta_en_el_catalogo(estado, catalogo):
    catalogo["componentes"] = [c for c in catalogo["componentes"] if c["id"] != "az-ai-search"]
    with pytest.raises(errores.ReglaIncumplida):
        A.calcular(estado, catalogo)


def test_marcador_en_texto_del_experto(estado, catalogo):
    _precio(estado, "P-02")["supuesto_cantidad"] = "Instancias por definir con el cliente."
    with pytest.raises(errores.ReglaIncumplida) as ex:
        A.calcular(estado, catalogo)
    assert any("P9" in e for e in ex.value.errores)


def test_coste_con_redondeo_medio_hacia_arriba(estado, catalogo):
    p = _precio(estado, "P-01")
    p.update(precio=0.125, cantidad_mensual=1)                   # 0,125 -> 0,13 (no 0,12 bancario)
    assert A.calcular(estado, catalogo)["lineas"][0]["coste_mensual_eur"] == "0.13"


def test_sin_precios_con_azure_facturable_se_rechaza(estado, catalogo):
    """PR14-1 / VER14-1 (I1.4): un anexo vacío con Azure facturable enseñaría 0,00 € de consumo al cliente."""
    estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]["precios"] = []
    with pytest.raises(errores.ReglaIncumplida) as ex:
        A.calcular(estado, catalogo)
    assert any("Anexo sin líneas" in e and "PR14-1" in e for e in ex.value.errores)


def test_sin_precios_y_solo_saas(estado, catalogo):
    resp = estado["carga"]["respuestas_expertos"]["azure"]["respuesta"]
    resp["precios"] = []
    for c in resp["componentes"]:
        c.update(catalogo_id=None, servicio="Microsoft Teams")
    anexo = A.calcular(estado, catalogo)
    assert anexo["lineas"] == [] and anexo["total_mensual_eur"] == "0.00"
    assert any("no ha declarado precios" in a for a in anexo["avisos"])


def test_cargar_catalogo_rechaza_repetidos(tmp_path):
    cat = ejemplo("catalogo_componentes")
    cat["componentes"].append(dict(cat["componentes"][0]))
    (tmp_path / "c.json").write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(errores.IntegridadRota):
        A.cargar_catalogo(tmp_path / "c.json")


# ── Ficheros ────────────────────────────────────────────────────────────────

def _colores(celda) -> set[str]:
    usados = set()
    for c in (celda.font.color, celda.fill.start_color if celda.fill.fill_type else None,
              *(getattr(celda.border, lado).color for lado in ("left", "right", "top", "bottom"))):
        if c is not None and c.type == "rgb" and c.rgb not in (None, "00000000"):
            usados.add(c.rgb[-6:].upper())
        elif c is not None and c.type == "theme":
            usados.add(f"tema:{c.theme}")
    return usados


def test_escribir_json_y_validar(tmp_path, estado, catalogo):
    anexo = A.calcular(estado, catalogo)
    sha = A.escribir_json(anexo, tmp_path / "a.json")
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == anexo
    assert sha == sha256_fichero(tmp_path / "a.json")
    anexo["total_mensual_eur"] = 340.33
    with pytest.raises(errores.IntegridadRota):
        A.escribir_json(anexo, tmp_path / "b.json")
    assert not (tmp_path / "b.json").exists()


def test_xlsx_montserrat_paleta_y_contenido(tmp_path, estado, catalogo):
    import openpyxl
    anexo = A.calcular(estado, catalogo)
    sha = A.generar_xlsx(anexo, tmp_path / "a.xlsx", A.detalle_lineas(estado, catalogo))
    assert sha == sha256_fichero(tmp_path / "a.xlsx")
    ws = openpyxl.load_workbook(tmp_path / "a.xlsx").active
    celdas = [c for fila in ws.iter_rows() for c in fila if c.value is not None]
    assert {c.font.name for c in celdas} == {"Montserrat"}
    colores = set().union(*(_colores(c) for fila in ws.iter_rows() for c in fila if c.has_style))
    assert colores <= PALETA, colores - PALETA
    textos = [str(c.value) for c in celdas]
    cab = [str(ws.cell(r, 1).value) for r in range(1, 25)].index("Servicio") + 1  # I1.7: dos avisos más arriba
    assert [ws.cell(cab, i).value for i in (1, 3, 7, 8, 10, 11, 12)] == [
        "Servicio", "SKU", "Precio unitario", "Moneda", "effectiveStartDate", "Fuente (filtro de la consulta)", "Estado"]
    # integrador I1.7: estado de la línea «INSTANTÁNEA DE PRECIOS» (el verificador ya no recibe precios)
    assert [ws.cell(cab + 1, i).value for i in (1, 3, 8, 12)] == ["Azure AI Search", "Standard S1", "EUR",
                                                                   "INSTANTÁNEA DE PRECIOS"]
    assert ws.cell(cab + 3, 12).value == "INSTANTÁNEA DE PRECIOS"
    # H9: las tres filas «No valorado» van antes de los totales, que no las suman
    assert [ws.cell(cab + 3 + i, 1).value for i in (1, 2, 3)] == ["Microsoft Foundry", "Azure AI Bot Service",
                                                                   "Microsoft Entra ID"]
    assert {ws.cell(cab + 3 + i, c).value for i in (1, 2, 3) for c in (2, 9, 12)} == {"No valorado"}
    assert ws.cell(cab + 6, 13).value.startswith("Se licencia aparte, no se factura por Azure")  # REV13-3
    assert ws.cell(cab + 7, 9).value == 287.33 and ws.cell(cab + 8, 9).value == 3447.96  # I1.9: ejemplo con B1
    assert any(A.NOTA_FIJA in t for t in textos) and any(A.AVISO_MONEDA in t for t in textos)
    from nucleo import textos_cliente
    assert [m for t in textos for m in textos_cliente.marcadores(t)] == []


def test_xlsx_sin_detalle_toma_el_sku_del_filtro(tmp_path, estado, catalogo):
    import openpyxl
    A.generar_xlsx(A.calcular(estado, catalogo), tmp_path / "a.xlsx")
    ws = openpyxl.load_workbook(tmp_path / "a.xlsx").active
    skus = [ws.cell(r, 3).value for r in range(1, ws.max_row + 1)]
    # I1.5 (decisión 1): los filtros de plantilla del ejemplo no llevan skuName; sin detalle, el XLSX lo dice
    assert "no indicado en la consulta" in skus
    assert A._sku_de_filtro("serviceName eq 'Storage' and skuName eq 'Hot LRS' and meterName eq 'x'") == "Hot LRS"


def test_aplicar_escribe_y_anula_lo_posterior(tmp_path, estado, catalogo):
    estado["carga"]["anexo_consumo"] = None  # integrador I1.7: el anexo del ejemplo ya es el del núcleo; así cambia
    estado["carga"]["estimacion"] = {"entrada": {}, "resumen": {}, "ajuste": None}
    estado["carga"]["textos_cliente"] = {"x": 1}
    anexo = A.aplicar(estado, catalogo, tmp_path / "salida")
    carga, art = estado["carga"], estado["artefactos"]
    assert carga["anexo_consumo"] == anexo and carga["estimacion"] is None and carga["textos_cliente"] is None
    for clave, nombre in (("anexo_json", "OF-KELVARA-001-A-Anexo-Consumo.json"),
                          ("anexo_xlsx", "OF-KELVARA-001-A-Anexo-Consumo.xlsx")):
        ruta = tmp_path / "salida" / nombre
        assert art[clave] == {"nombre": nombre, "sha256": sha256_fichero(ruta), "bytes": ruta.stat().st_size}
    assert sorted(p.name for p in (tmp_path / "salida").iterdir()) == sorted(
        ["OF-KELVARA-001-A-Anexo-Consumo.json", "OF-KELVARA-001-A-Anexo-Consumo.xlsx"])


def test_aplicar_idempotente_no_anula_la_estimacion(tmp_path, estado, catalogo):
    A.aplicar(estado, catalogo, tmp_path / "salida")
    estado["carga"]["estimacion"] = {"entrada": {}, "resumen": {}, "ajuste": None}
    A.aplicar(estado, catalogo, tmp_path / "salida")
    assert estado["carga"]["estimacion"] is not None


def test_aplicar_con_error_no_muta(tmp_path, estado, catalogo):
    estado["carga"]["verificacion"]["resultado"]["discrepa"] = [{"id": "P-01"}]
    antes = copy.deepcopy(estado)
    with pytest.raises(errores.ReglaIncumplida):
        A.aplicar(estado, catalogo, tmp_path / "salida")
    assert estado == antes and not (tmp_path / "salida").exists()


def test_aplicar_si_falla_el_xlsx_no_deja_json_nuevo(tmp_path, estado, catalogo, monkeypatch):
    def falla(*_a, **_k):
        raise OSError("disco lleno simulado")
    monkeypatch.setattr(A, "generar_xlsx", falla)
    antes = copy.deepcopy(estado)
    with pytest.raises(OSError):
        A.aplicar(estado, catalogo, tmp_path / "salida")
    assert estado == antes and list((tmp_path / "salida").iterdir()) == []


def test_aplicar_si_falla_la_segunda_sustitucion_restaura_el_json(tmp_path, estado, catalogo, monkeypatch):
    salida = tmp_path / "salida"
    A.aplicar(copy.deepcopy(estado), catalogo, salida)
    rj = salida / "OF-KELVARA-001-A-Anexo-Consumo.json"
    rj.write_text('{"previo": true}', encoding="utf-8")
    real = A.os.replace

    def replace(origen, destino):
        if str(destino).endswith("Anexo-Consumo.xlsx"):
            raise OSError("fallo simulado al sustituir el XLSX")
        return real(origen, destino)
    monkeypatch.setattr(A.os, "replace", replace)
    with pytest.raises(OSError):
        A.aplicar(estado, catalogo, salida)
    monkeypatch.setattr(A.os, "replace", real)
    assert rj.read_text(encoding="utf-8") == '{"previo": true}'
    assert sorted(p.name for p in salida.iterdir()) == ["OF-KELVARA-001-A-Anexo-Consumo.json",
                                                        "OF-KELVARA-001-A-Anexo-Consumo.xlsx"]


def test_si_falla_tambien_la_restauracion_se_conserva_la_copia(tmp_path, estado, catalogo, monkeypatch):
    salida = tmp_path / "salida"
    A.aplicar(copy.deepcopy(estado), catalogo, salida)
    real = A.os.replace

    def replace(origen, destino):
        if str(destino).endswith("Anexo-Consumo.xlsx") or str(origen).endswith(".anterior"):
            raise OSError("fallo simulado")
        return real(origen, destino)
    monkeypatch.setattr(A.os, "replace", replace)
    with pytest.raises(OSError):
        A.aplicar(estado, catalogo, salida)
    monkeypatch.setattr(A.os, "replace", real)
    assert (salida / ".OF-KELVARA-001-A-Anexo-Consumo.json.anterior").exists()
