"""I1.8 · D · Datos comunes de las pruebas de VER17-2: los estados y paquetes reales de la prueba de los arreglos de I1.7
(pruebas/I17/ARREGLOS/REAL/B/sesion_1: versión B LISTA y APROBADA, con la DEVUELTA real del responsable de preventa) y una copia congelada
del catálogo con el que se generaron (SHA-256 94b1cb0c…16f30, el del manifiesto de esos paquetes)."""
from __future__ import annotations

import copy
import io
import json
import pathlib
import sys
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parents[1]
if str(RAIZ / "sandbox") not in sys.path:
    sys.path.insert(0, str(RAIZ / "sandbox"))

REAL = RAIZ / "pruebas" / "I17" / "ARREGLOS" / "REAL" / "B" / "sesion_1"
CATALOGO = RAIZ / "tests" / "fixtures_i18_d" / "catalogo_componentes_i17.json"
COMENTARIO_D002 = ("SIMULADA en la prueba de los arreglos de I1.7, no es una decisión real. Valorad también el "
                   "almacenamiento de los ficheros")


def catalogo() -> dict:
    return json.loads(CATALOGO.read_text(encoding="utf-8"))


def estado_real(caso: str) -> dict:
    """caso: «lista_B» o «aprobada_B»."""
    return copy.deepcopy(json.loads((REAL / caso / "estado.json").read_text(encoding="utf-8")))


def partes_publicadas(caso: str) -> dict:
    """Partes del PPTX que se publicó en la prueba real (con la sección «Cambios pedidos» en la diapositiva 2)."""
    with zipfile.ZipFile(REAL / caso / "OF-BREZALIA-001-B-Paquete.zip") as paquete:
        datos = paquete.read("OF-BREZALIA-001-B-Revision.pptx")
    with zipfile.ZipFile(io.BytesIO(datos)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}
