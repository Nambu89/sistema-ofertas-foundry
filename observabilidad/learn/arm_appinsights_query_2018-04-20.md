# Consulta KQL a Application Insights por Azure Resource Manager (api-version 2018-04-20)

Fuente leída sin autenticar el 08-10-2026. Sirve a `lib/appi.py`.

## Lo que dice Learn

- La referencia REST de Application Insights en Learn (`/rest/api/application-insights/query/execute`) solo
  publica la vista `rest-application-insights-v1`: `POST https://api.applicationinsights.io/v1/apps/{appId}/query`.
  Esa vía exige un token de audiencia `https://api.applicationinsights.io`, que en el tenant de Devoteam pide un
  MFA aparte (VERIF-6).
- Ninguna página de Learn consultada (`access-api`, `azure-resource-queries`, `operation-groups`, búsqueda con el
  MCP de Learn) documenta la ruta de ARM ni su api-version.

## Lo que dice la especificación oficial

La especificación REST oficial de Microsoft, de la que Learn genera las referencias, sí la publica:

- Repositorio `Azure/azure-rest-api-specs`, fichero
  `specification/applicationinsights/data-plane/Insights/preview/2018-04-20/swagger.json`.
  Último commit: `f2a9a666f7ad741ec4f2bf68f6b0b99784ac7b0f` (2026-02-12). SHA-256 del fichero descargado:
  `787ad057752aa6a2eb0632f167eca1b10c0ee9a3167304e18dbd63c2378990a8`.
- `host`: `management.azure.com`; título «Application Insights Data Plane», versión `2018-04-20`.
- Operación `Query_Execute`:
  `POST /subscriptions/{subscriptionId}/resourcegroups/{resourceGroupName}/providers/Microsoft.Insights/components/{applicationName}/query`
  con `api-version` obligatoria en la cadena de consulta.
- Cuerpo `queryBody`: `query` (obligatorio), `timespan` (ISO 8601, opcional) y `applications` (opcional).
- Ejemplo oficial `examples/query-post.json` (SHA-256 `da4a6312f5dc4e0fa712cea1c51670b8335024ad2d4b12a71c0f7c58ee19afe3`):
  `"apiVersion": "2018-04-20"`, cuerpo `{"timespan": "PT12H", "query": "requests | summarize count() by bin(timestamp, 1h)"}`.
  La respuesta 200 trae `{"tables": [{"name": "PrimaryResult", "columns": [...], "rows": [...]}]}`, la misma
  forma que la vía v1.

## Lo que queda sin verificar

- NO VERIFICADO en real: que ARM acepte hoy esa ruta con un token de audiencia `https://management.azure.com` en
  el tenant 00000000-0000-0000-0000-000000000000. La versión está en una carpeta `preview` de la especificación.
  Se comprueba en la siguiente tanda con el comando de `lib/appi.py` (sección «Uso»).
