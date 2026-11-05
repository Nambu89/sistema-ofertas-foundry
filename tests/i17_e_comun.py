"""I1.7, papel E: esquema del sandbox con el que se deriva el catálogo v5 en las pruebas.

Hasta que el integrador aplique docs/I1/CAMBIOS-I17-E (esquema propuesto), el catálogo v5 no cabe en el esquema vigente
(25 plantillas en Microsoft Foundry frente a un tope de 12), así que `catalogo.derivar` lo rechaza sin escribir (rc 2) y
el catálogo vivo del sandbox se queda como estaba. Las pruebas derivan entonces con la propuesta y su vista previa
(`catalogo_componentes.derivado_propuesto.json`). Cuando el esquema vigente lo admita, todo vuelve al catálogo vivo solo.
"""
from __future__ import annotations

import json
import pathlib

from catalogo import derivar
from esquemas import comprobar_esquemas as ce

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CAT = derivar.cargar()
ESQ_VIGENTE = json.loads(derivar.ESQUEMA_SANDBOX.read_text(encoding="utf-8"))
RUTA_PROPUESTO = derivar.PROPUESTA / "catalogo_componentes.propuesto.json"
PROPUESTO = json.loads(RUTA_PROPUESTO.read_text(encoding="utf-8"))
VIGENTE_ADMITE = ce.validar(derivar.catalogo_componentes(CAT, esquema=ESQ_VIGENTE), ESQ_VIGENTE, ESQ_VIGENTE) == []
ESQ_EFECTIVO = ESQ_VIGENTE if VIGENTE_ADMITE else PROPUESTO
ARGS_EFECTIVO = [] if VIGENTE_ADMITE else ["--esquema-sandbox", str(RUTA_PROPUESTO)]
DERIVADO_EFECTIVO = derivar.DERIVADO if VIGENTE_ADMITE else derivar.DERIVADO_PROPUESTO
