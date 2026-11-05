"""I1.9 · papel P, cierre (16-10-2026): VA18-17, el anexo XLSX se imprime en A4 horizontal y a una página de ancho,
con la cabecera de la tabla repetida (antes ocupaba 7 u 8 páginas y cortaba el título)."""
from __future__ import annotations

import openpyxl

from tests.test_i15_p_cobertura_documentos import CAT, _estado
from nucleo import anexo_consumo as A  # noqa: E402


def test_va18_17_configuracion_de_impresion(tmp_path):
    anexo, detalle = A._construir(_estado(), CAT)
    ruta = tmp_path / "anexo.xlsx"
    A.generar_xlsx(anexo, ruta, detalle)
    ws = openpyxl.load_workbook(ruta).active
    ps = ws.page_setup
    assert (ps.orientation, str(ps.paperSize), ps.fitToWidth, ps.fitToHeight) == ("landscape", "9", 1, 0)
    assert ws.sheet_properties.pageSetUpPr.fitToPage is True
    cab = next(c.row for c in ws["A"] if c.value == A.COLUMNAS[0][0])
    assert ws.print_title_rows == f"${cab}:${cab}"
    assert ws.freeze_panes == f"A{cab + 1}"
