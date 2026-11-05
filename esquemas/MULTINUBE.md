# Contrato multinube del núcleo (04-11-2026)

Qué tienen que cumplir el catálogo y la instantánea de precios de **Google Cloud** (`gcp`) y de **AWS** (`aws`) para que
el núcleo (`sandbox/nucleo/`) y la puerta (`verificar_paquete.py`) los acepten. Azure no cambia: todo lo de aquí es
opcional para Azure y, sin las claves nuevas, un fichero o un estado de Azure se lee exactamente igual que antes.

## 1. El pilar

| Dónde | Clave | Valor |
|---|---|---|
| Estado | `carga.alta.pilar` (dentro del hash del contenido) | `azure`, `gcp` o `aws`. Sin la clave es `azure`; el estado de Azure no la escribe. |
| Alta | `preventa_run.py iniciar --pilar <p>` / `preventa_api.iniciar(..., pilar=<p>)` | Lista blanca: otro valor da rc 2 sin crear estado. |
| Brief | `experto: preventa-experto-<p>`, `brief_id: BRF-<código>-<AZ\|GCP\|AWS>-R<n>`, `pilar` (solo fuera de Azure) | |
| Respuesta del experto | `agente: preventa-experto-<p>` | El contrato del modelo es *strict*: el pilar de la respuesta es su `agente`. Se guarda en `carga.respuestas_expertos.<p>` y no puede haber otra clave. |
| `valoracion_nucleo.instantanea` | `pilar`, `fuente_moneda`, `tipo_bce`, `fecha_tipo_bce` (solo fuera de Azure) | Los copia el núcleo de la instantánea. |
| Manifiesto del paquete | `pilar` (solo fuera de Azure) | La puerta exige que coincidan manifiesto, estado, instantánea y catálogo. |

`registrar-experto --experto <p>` solo acepta el pilar de la solicitud.

## 2. Dónde van los ficheros

| Pilar | Local (repositorio) | Variable que lo cambia | Nombre montado en el sandbox |
|---|---|---|---|
| azure | `sandbox/datos/catalogo_componentes.json` y `precios_instantanea.json` | `PREVENTA_CATALOGO` | `catalogo_componentes.json`, `precios_instantanea.json` |
| gcp | `catalogo/gcp/catalogo_componentes.json` y `precios_instantanea.json` | `PREVENTA_CATALOGO_GCP` | `catalogo_componentes_gcp.json`, `precios_instantanea_gcp.json` |
| aws | `catalogo/aws/catalogo_componentes.json` y `precios_instantanea.json` | `PREVENTA_CATALOGO_AWS` | `catalogo_componentes_aws.json`, `precios_instantanea_aws.json` |

La instantánea se busca junto al catálogo con el mismo sufijo (`anexo_consumo.nombre_instantanea`); `PREVENTA_PRECIOS`
la fija a mano. La puerta usa por defecto los del pilar del paquete; `--catalogo` y `--precios` los cambian.

## 3. Catálogo (`esquemas/catalogo_componentes.json`, `preventa-catalogo/1`)

Los esquemas de `esquemas/` siguen siendo los de Azure: de `respuesta_experto.json` salen las instrucciones y el
`text.format` del experto de Azure, que no cambian. Para Google Cloud y AWS el núcleo valida con la **variante del
pilar** que deriva el código (`esquema.cargar_pilar(nombre, pilar)`, aplicada a `catalogo_componentes`, `brief`,
`respuesta_experto`, `respuesta_experto_completa` y los bloques del estado): ids `gcp-…`/`aws-…` en lugar de `az-…`,
URL de los dominios del pilar en lugar de Learn, regiones con guion, `-GCP-R`/`-AWS-R` en el `brief_id`, agente
`preventa-experto-<pilar>`, `pilar` en la raíz del catálogo y del brief, y el modelo por defecto sin las constantes de
Azure. El `text.format` y las instrucciones de los expertos de Google y AWS se derivan de esa variante (trabajo de
`agentes/<pilar>/`).

El catálogo tiene la misma forma que el de Azure, con estas reglas además del esquema
(`anexo_consumo.errores_catalogo_pilar`):

- `"pilar": "gcp"` o `"aws"` en la raíz (sin la clave, el catálogo es de Azure y no vale para otro pilar).
- Ids de componente con el prefijo del pilar: `gcp-…` o `aws-…` (`^(gcp|aws)-[a-z0-9-]{2,40}$`). Las claves de la
  instantánea son `<id de componente>/<id de plantilla>`.
- Toda URL del catálogo es de los dominios del pilar: Google `cloud.google.com`, `docs.cloud.google.com`; AWS
  `docs.aws.amazon.com`, `aws.amazon.com`. En los campos con patrón de URL, la ruta solo admite `[a-z0-9/._-]`.
- Regiones con el código de la nube (`^[a-z][a-z0-9-]*[a-z0-9]$` en la variante: `europe-west1`, `eu-south-2`). En AWS, `region_ue` y
  `modelo_por_defecto.region` tienen que ser de la lista blanca de la UE (§5).
- `modelo_por_defecto.componente` es un id del pilar y `despliegue` es texto libre (2-60). En Azure siguen siendo
  `az-foundry` y `DataZoneStandard`.
- `filtro` de cada plantilla (40-400 caracteres): condiciones `campo eq 'valor'` unidas con ` and `, con la región en
  el campo del pilar: `armRegionName` (Azure), `region` (Google), `regionCode` (AWS). Ejemplos:
  - Google: `serviceName eq 'Vertex AI' and region eq 'europe-west1' and skuId eq '0013-863C-A2FF'`
  - AWS: `serviceCode eq 'AmazonBedrock' and regionCode eq 'eu-south-2' and sku eq 'ABCD1234EFGH5678'`

## 4. Instantánea de precios (`esquemas/precios_instantanea.json`, `preventa-precios-instantanea/1`)

Raíz, además de lo de Azure (`schema`, `fecha_consulta` UTC, `moneda: "EUR"`, `fuente`, `plantillas`, `sha256`):

| Clave | Google | AWS |
|---|---|---|
| `pilar` | `"gcp"` | `"aws"` |
| `fuente_moneda` | `"gcp_catalog_eur"` (obligatoria) | `"aws_usd_convertido_bce"` (obligatoria) |
| `tipo_bce` | prohibida | obligatoria: 1 EUR = `tipo_bce` USD, cuatro decimales como la publica el BCE |
| `fecha_tipo_bce` | prohibida | obligatoria, `AAAA-MM-DD` del tipo publicado, entre 0 y 7 días antes de `fecha_consulta` |

Cada artículo de `plantillas` tiene los campos de Azure (`filtro` = el del catálogo, `precio_unitario` en EUR, `unidad`,
`effectiveStartDate`, `meterName`, `productName`, `skuName`, `armRegionName` = región de la nube, igual a la del filtro,
`articulos_devueltos`, `sha256_articulo`, `tramos` opcional) y el identificador de precio de su nube:

| Pilar | Obligatorios | Prohibidos |
|---|---|---|
| azure | (`meterId` opcional) | `sku_id`, `sku`, `codigo_oferta`, `precio_origen_usd` |
| gcp | `sku_id` (`^[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}$`) | `meterId`, `sku`, `codigo_oferta`, `precio_origen_usd` |
| aws | `sku` y `codigo_oferta` (`^[A-Z0-9]{8,40}$`), `precio_origen_usd` (número ≥ 0) | `meterId`, `sku_id` |

En AWS, cada tramo lleva también `precio_origen_usd`. `sha256` es el SHA-256 del JSON canónico
(`hashes.json_canonico`) de la instantánea sin la clave `sha256`.

**Conversión de AWS**: `precio_unitario = round_half_up(precio_origen_usd / tipo_bce, 6 decimales)` y lo mismo en cada
tramo. EUR = USD / tasa: multiplicar infla el precio un 25 % (1,1179²) y el núcleo y la puerta lo rechazan. Si el BCE no
responde al desplegar, no se pone un tipo antiguo: se falla (la regla de los 7 días lo detecta).

Ejemplo mínimo de AWS (las pruebas `tests/test_multinube_nucleo.py` construyen uno así):

```json
{"schema": "preventa-precios-instantanea/1", "fecha_consulta": "2026-11-04T08:00:00Z", "moneda": "EUR",
 "pilar": "aws", "fuente": "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws (USD) y BCE eurofxref",
 "fuente_moneda": "aws_usd_convertido_bce", "tipo_bce": 1.1179, "fecha_tipo_bce": "2026-11-03",
 "plantillas": {"aws-bedrock/entrada": {
   "filtro": "serviceCode eq 'AmazonBedrock' and regionCode eq 'eu-south-2' and sku eq 'ABCD1234EFGH5678'",
   "precio_unitario": 8.945344, "precio_origen_usd": 10.0, "sku": "ABCD1234EFGH5678", "codigo_oferta": "JRTCKXETXF",
   "unidad": "1M", "effectiveStartDate": "2026-10-01", "meterName": "Input tokens", "productName": "Modelo",
   "skuName": "Modelo entrada", "armRegionName": "eu-south-2", "articulos_devueltos": 1, "sha256_articulo": "…"}},
 "sha256": "…"}
```

Azure no cambia: su procedencia es siempre su `fuente` (Retail Prices con `currencyCode=EUR`), escriba o no
`fuente_moneda`; si la escribe, tiene que ser `azure_retail_eur`.

## 5. Regiones de AWS

Lista blanca de la UE (Knowledge MCP de AWS, 2026-11-04): `eu-central-1`, `eu-west-1`, `eu-west-3`, `eu-north-1`,
`eu-south-1`, `eu-south-2`. **`eu-west-2` (Londres) y `eu-central-2` (Zúrich) no son UE.** Se comprueba en los
artículos de la instantánea, en el catálogo, en la respuesta del experto (`componentes[].region`, `precios[].region`) y,
en la puerta, también en las líneas del anexo. Una región vacía o ausente (componente existente del cliente) no se mira;
`global` se rechaza en AWS.

## 6. Lo que ve el cliente

Anexo (`fuente`): `nombre` y `url` del pilar (`Google Cloud Billing Catalog` /
`https://cloudbilling.googleapis.com/v1/services`; `AWS Price List` /
`https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/index.json`), `fuente_moneda` y, en AWS, `tipo_bce` y
`fecha_tipo_bce`. Frase de la diapositiva 8:

- Google: «Google Cloud Billing Catalog (cloudbilling.googleapis.com), región …: precios consultados el F, vigentes desde V».
- AWS: «AWS Price List (pricing.us-east-1.amazonaws.com), región …: precios consultados el F, vigentes desde V;
  publicados en USD y convertidos a euros con el tipo de referencia del BCE del D (1 EUR = 1,1179 USD), importes
  orientativos».

## 7. Lo que sigue siendo solo de Azure

El análisis de la respuesta del experto (referencias de Learn, arquitecturas, niveles y razones de subida), la
verificación, los nombres de región legibles, la diapositiva del diagrama y el resto de las réplicas de la puerta
siguen escritos para Azure y no se han adaptado ni probado con Google o AWS (NO VERIFICADO de punta a punta).
