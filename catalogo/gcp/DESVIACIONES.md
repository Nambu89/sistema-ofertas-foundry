# Pilar Google Cloud: desviaciones de forma respecto al catálogo de Azure

Fecha: 2026-11-04. No se ha tocado ningún esquema común (`esquemas/*.json`): esta lista es lo que el agente que
generaliza el núcleo y los esquemas tiene que admitir para cargar `catalogo/gcp/`. La prueba
`tests/test_gcp_catalogo.py::test_solo_desviaciones_documentadas_frente_al_esquema_azure` valida el catálogo de Google
con el esquema de Azure y falla si aparece un error que no esté en esta lista.

## 1. Catálogo (`catalogo_componentes.json`, esquema `preventa-catalogo/1`)

| Campo | Azure | Google Cloud | Motivo |
|---|---|---|---|
| `componentes[].id`, `computo_por_defecto.filas` | `^az-` | `^gcp-` | otro proveedor |
| `referencia_url`, `fuente_url`, `fuente`, `ciclo_vida.fuente`, `por_instancia.fuente_url`, `arquitecturas_referencia[].url`, `modelo_por_defecto.*_url` | `https://learn.microsoft.com/` | `https://docs.cloud.google.com/` o `https://cloud.google.com/` | documentación oficial de Google |
| `modelo_por_defecto.componente` | `az-foundry` | `gcp-vertex-ai` | otro proveedor |
| `modelo_por_defecto.despliegue` | `DataZoneStandard` | `Standard PayGo multirregión eu` | modo de consumo de Gemini (página del modelo) |
| `region_ue` | `^[a-z]+[a-z0-9]*$` | `europe-southwest1`, `eu`… | las regiones de Google llevan guion |
| `plantillas_precio[].filtro` | OData de Retail Prices | `serviceId eq '…' and skuId eq '…' and serviceRegion eq '…'` | la Catalog API no filtra: se identifica el SKU |
| `plantillas_precio[].unidad_uso` (nuevo) | — | `usageUnit` esperado o `null` | sin clave no se ha visto; la instantánea falla mientras sea `null` |
| `plantillas_precio[].fuente_sku` (nuevo) | — | página pública del grupo de SKU | evidencia del skuId y la descripción literal |
| `plantillas_precio[].region_precio` (nuevo) | solo en la fila | también en la plantilla (`global`) | Cloud Run functions mezcla SKU regionales y uno global |
| `ciclo_vida.retirada_no_antes_de` (nuevo) | — | fecha | Google publica «X or later»: fecha más temprana, no retirada programada; `retirada` queda `null` |

## 2. Instantánea de precios (`precios_instantanea.json`)

- Esquema propio `preventa-precios-instantanea-gcp/1` con `procedencia: "gcp_catalog_eur"`. Por plantilla: `filtro`,
  `concepto` (descripción del SKU), `precio_unitario` (primer tramo, EUR por `usageUnit`), `unidad` (`usageUnit`),
  `effectiveStartDate` (`pricingInfo.effectiveTime`), `service_id`, `sku_id`, `service_regions`, `tasa_conversion`
  (`currencyConversionRate`, incluye el recargo de Google por facturar fuera de USD), `display_quantity`, `tramos`.
  Faltan los campos de Azure `meterName`, `productName`, `skuName`, `armRegionName` y `meterId`.
- Tramos: muchos SKU de Google empiezan con un tramo gratuito (`precio_unitario` 0 y `tramos` después). El núcleo
  tiene que valorar SIEMPRE por tramos cuando existan; leer solo `precio_unitario` daría 0 €. La huella `sha256`
  protege la instantánea entera; no se puede detectar sin la API una entrada a la que se quiten los tramos y se
  vuelva a sellar (igual que en Azure).
- Una sola copia en `catalogo/gcp/`; la copia en `sandbox/datos/` y su montaje son del agente de infraestructura.
- Unidades de tiempo: las de Google son segundos de vCPU o de GiB (`unidad` probable `s` o `GiBy.s`, NO VERIFICADO). El
  núcleo cuenta hoy 730 h por instancia con unidades de Azure (`1 Hour`): para Cloud Run tiene que convertir a
  2.628.000 s al mes por instancia y multiplicar por `por_instancia`.
- Divisores: puestos por la unidad de la página pública de precios (1.000.000 tokens, 1.000 consultas, 100.000
  operaciones); **NO VERIFICADOS** contra `usageUnit`. Quien declare `unidad_uso` tras ver la API revisa el divisor a la
  vez (si la API da el precio por unidad suelta, el divisor es 1).

## 3. Respuesta del experto (`agentes/gcp/instrucciones_experto_gcp.md`)

- Mismo contrato salvo: `agente: "preventa-experto-gcp"`, `referencias[].url` de `docs.cloud.google.com` o
  `cloud.google.com` y `herramientas_usadas` con `search_documents` y `get_documents` (en Azure,
  `microsoft_docs_search` y `microsoft_docs_fetch`).
- El bloque «Límites que comprueba el código» es una copia adaptada a mano del que genera
  `agentes/esquemas/limites.py`; el bloque del catálogo lo genera `catalogo/gcp/comprobar_catalogo.py`
  (`--escribir-instrucciones`) y la comprobación sin red falla si no coincide.
- El `motivo_no_valoracion` `licencia_fuera_de_azure` conserva su nombre (es un valor del esquema común).

## 4. Fuera de este primer catálogo (decisión de alcance, no olvido)

- Agent Search Enterprise y el almacenamiento del índice de Agent Search: sin la diferencia oficial de ediciones
  citada no se pueden escribir razones de subida.
- Operaciones de Cloud Storage (clase A y B): SKU con precio mundial; se valoran solo los GB.
- Secret Manager e Identity Platform: no hay página pública de grupo de SKU que dé su skuId; van sin plantillas
  (`sin_medidor_publico`) hasta verlos en la Catalog API.
- Modelos alternativos (Gemini 4 Argon, Gemini 3.5 Flash): `gemini-4-argon` solo está en la multirregión `eu` y en
  Londres; `gemini-3.5-flash` en `eu` y Fráncfort. Para añadirlos hacen falta sus SKU y razones cerradas.
- Firestore: se usan los SKU sin franquicia gratuita (`… Madrid`, no `… (with free tier) Madrid`): la franquicia es
  de una sola base de datos por proyecto; valoración conservadora. Los mismos conceptos existen también bajo el servicio
  App Engine (F17B-412E-CB64): se usa el servicio Cloud Firestore (EE2C-7FAC-5E08).
