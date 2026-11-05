# Pilar AWS: desviaciones respecto a la forma del catálogo de Azure

Fecha: 2026-11-04. Para la integración multinube (quien generaliza el núcleo y los esquemas). Aquí no se ha tocado
ningún esquema común: cada punto dice qué hace hoy el catálogo de AWS y qué necesitaría el esquema o el núcleo.

## Catálogo (`catalogo_componentes.json`)

1. **Esquema propio** `preventa-catalogo-aws/1`. `esquemas/catalogo_componentes.json` no lo valida: exige ids `^az-`,
   URL de `learn.microsoft.com` y regiones de Azure. Los ids de AWS son `^aws-[a-z0-9-]{2,40}$`, las URL de
   `docs.aws.amazon.com` y `aws.amazon.com` (más `learn.microsoft.com` en los factores compartidos con Azure) y las
   regiones, la lista blanca de `REGIONES_UE`.
2. **Filtro de plantilla**: la misma sintaxis `campo eq 'valor' and …`, pero con atributos del fichero de la Bulk API:
   `servicecode`, `regionCode`, `usagetype`, `operation` (opcional) y `termType` (solo `OnDemand`), en ese orden.
   `servicecode` y `termType` eligen fichero y bloque de términos; el resto se compara con los atributos del producto.
   `catalogo/plantillas_precio.py::problemas_plantilla` no lo admite (sus `CAMPOS` son los de Azure Retail Prices).
3. **`servicecode_precios`** sustituye a `service_name_precios`/`producto_precios`.
4. **`unidad` en cada plantilla**: la unidad literal de AWS («1K tokens», «Requests», «GB-Mo», «OCU-hours»…). La
   instantánea exige que el fichero traiga exactamente esa unidad (si AWS la cambia, falla en alto). El divisor es
   1000 para «1K tokens» y 1 para el resto (`instantanea_precios.divisor_de_unidad`); `plantillas_precio.divisor_de_unidad`
   de Azure no reconoce estas unidades.
5. **`periodo` en las plantillas de tiempo** (`hora` | `mes`). AWS cobra por mes algunas unidades cuyo nombre no lo
   dice («Secrets», «Keys»). El núcleo de Azure deduce 730 h o 1 mes de la unidad; con AWS debe leer `periodo`.
6. **`ciclo_vida` de los modelos** lleva `lanzamiento` y `eol_no_antes_de` además de `retirada` (null) y `fuente`:
   las fichas de Bedrock no publican fecha de retirada, solo «EOL no sooner than». Nova 2 Lite: no antes del
   2026-12-02. La regla de ciclo de vida de Azure (retirada publicada antes de oferta + Gantt + 12 meses) lo admitiría
   en silencio: conviene que el núcleo trate `eol_no_antes_de` anterior a ese horizonte como riesgo obligatorio.
7. **`disponibilidad`** añade `producto_mcp` (nombre exacto que acepta `aws___get_regional_availability`). Las regiones
   de cada nivel son las de `isAvailableIn` del MCP el 2026-11-04; `isBeingPlannedIn` e `isNotExpandingIn` se dejan
   fuera y se anotan en `nota`.
8. **`regiones_ue`, `conversion`, `aviso_precios` y `documentacion_mcp`** en la raíz: no existen en Azure.
9. **Factores**: los de RAG (5.656 y 1.171 tokens por consulta) se marcan `supuesto` (en Azure el de entrada es
   `oficial`): la media es de Learn, no de AWS; se reutiliza para que las dos nubes se comparen con el mismo consumo.
10. **Una sola región de precio por fila** (`eu-central-1`, Fráncfort), como Azure con `swedencentral`. Motivo:
    Bedrock Knowledge Bases no está en `eu-north-1`, `eu-south-1` ni `eu-south-2`, y Textract no está en `eu-north-1`
    ni `eu-south-1`. Valorar en otra región de la lista blanca exige plantillas con su `regionCode` y su `usagetype`
    (el prefijo cambia por región: `EUC1-`, `EU-`, `EUW3-`…; en KMS es el código de región entero).
11. **Componentes sin plantillas** (`aws-bedrock-knowledge-bases`): no tiene medidor propio identificable en el
    fichero público; se valoran sus piezas. El motivo `sin_medidor_publico` ya existe en el contrato.
12. **Motivos de `no_valorables` nuevos**: `marketplace_de_terceros`, `solo_inferencia_global_fuera_de_la_ue`,
    `unidad_de_texto_por_validar`, `capa_gratuita_no_aplicada`, `fuera_del_primer_conjunto`,
    `medidor_no_identificado_sin_ambiguedad`, `depende_de_la_carga`.

## Instantánea (`precios_instantanea.json`)

13. **Esquema propio** `preventa-precios-instantanea-aws/1`: `moneda` EUR, `moneda_origen` USD, `conversion`
    {`fuente`, `regla` «EUR = USD / tipo_bce», `tipo_bce`, `fecha_tipo_bce`}, `regiones_ue`, `publicaciones` (URL,
    `publicationDate` y `version` de cada fichero) y `aviso`. Por plantilla: `precio_unitario` (EUR), `precio_origen`
    (USD), `moneda_origen`, `unidad`, `effectiveDate`, `usagetype`, `sku`, `rateCode`, `regionCode`,
    `productos_devueltos`, `terminos_futuros_descartados`, `sha256_articulo` y `tramos` (con `precio_origen` en cada uno).
    No trae `meterName`, `productName`, `skuName` ni `armRegionName` de Azure.
14. **Una sola copia** (`catalogo/aws/precios_instantanea.json`): la copia en `sandbox/datos/` la decide la integración.
15. El tipo del BCE se rechaza con más de 7 días (`MAX_DIAS_TIPO`): el BCE no publica en fines de semana ni festivos
    TARGET y el hueco más largo es de 5 días (Semana Santa).

## Experto (`agentes/aws/`)

16. **`brief_id`**: el límite actual exige `…-AZ-R[1-3]`; el experto de AWS necesita su propio sufijo (p. ej. `-AWS-`).
17. **`herramientas_usadas`** lleva `aws___search_documentation`, `aws___read_documentation` y
    `aws___get_regional_availability` en lugar de las de Learn: el esquema de respuesta y `limites.py` deben admitirlas.
18. **`agente`** = `preventa-experto-aws`.
19. **Bloque generado de las instrucciones**: lo genera `python -m catalogo.aws.comprobar_catalogo --bloque` (no
    `catalogo/derivar.py`) y el comprobador falla si el fichero no lo contiene tal cual. Si `derivar.py` se generaliza,
    puede absorberlo.
20. **Definición** (`definicion_borrador.json`): misma forma de tool MCP que `MCP_LEARN`, con
    `server_url` `https://knowledge-mcp.global.api.aws` y sin autenticación. El modelo del agente es el de Foundry
    (`gpt-6-luna`); el modelo que recomienda a los clientes es Nova 2 Lite. No se ha probado que el cliente MCP de
    Foundry hable con este servidor (exige `Content-Type: application/json` exacto): NO VERIFICADO hasta desplegar.
