# Infraestructura como código de la preventa multinube

Arquitectura objetivo: **una instancia independiente por pilar** (Microsoft, Google Cloud y AWS), todas en
Microsoft Foundry, en la misma suscripción y cada una en su grupo de recursos. Las fuentes de cada decisión son las
páginas de Microsoft Learn y la plantilla oficial que se citan más abajo y en los comentarios de cada `.bicep`. **Nada de esto se ha desplegado ni probado con `what-if`.** Solo se ha
compilado y pasado el linter en local.

Cambio respecto al diseño inicial: la entrada de los comerciales **no** es Google Chat ni Teams sino un **frontal web
propio por pilar** en Container Apps, detrás de Front Door con WAF. Por eso no hay Azure Bot Service, ni pasarela
de canales, ni su cola. En producción el frontal pedirá el inicio de sesión de Google y el servidor comprobará el
claim `hd`; la v1 es solo local, así que esa parte no está en la infraestructura.

## Ficheros

| Fichero | Qué despliega |
|---|---|
| `main.bicep` | Ámbito suscripción: grupo de plataforma, un grupo por pilar y los módulos |
| `plataforma.bicep` | Front Door Premium + WAF (reglas administradas y de bots), red hub con Azure Firewall Standard (opcional), Log Analytics de plataforma, una identidad de CI/CD por pilar federada con GitHub Actions (OIDC, sin secretos) |
| `pilar.bicep` | Módulo parametrizado por pilar (`azure`, `gcp`, `aws`): VNet con subred de agentes delegada, subred de endpoints privados y subred de Container Apps; Storage, AI Search y Cosmos DB propios; 6 endpoints privados y 8 zonas DNS privadas vinculadas solo a su VNet; Key Vault con RBAC y protección contra purga; ACR Premium; Application Insights y Log Analytics; recurso de Foundry con inyección de red, proyecto, conexiones y capability host; despliegues `gpt-6-luna` y `gpt-5.6-luna` en `DataZoneStandard`; frontal y backend en Container Apps con identidad administrada; dos políticas con `Deny`; presupuesto con avisos |
| `modulos/pe.bicep` | Un endpoint privado con su grupo de zonas DNS |
| `modulos/enganche-pilar.bicep` | Lo del pilar que vive en el grupo de plataforma: endpoint, origen por Private Link, ruta y política de seguridad de Front Door; emparejamiento hub → pilar; reglas de salida del Firewall |
| `main.parameters.json` | Parámetros con **marcadores** (`<ORGANIZACION_GITHUB>`, `<CORREO_AVISOS_PRESUPUESTO>`…). Los valores reales van fuera del repositorio |
| `comprobar.sh` | Compila y pasa el linter a los tres ficheros, contrasta los parámetros y ejecuta la autocomprobación del coste. Código de salida = veredicto; cualquier aviso cuenta como fallo |
| `coste_fijo.py` | Consulta la Retail Prices API y regenera `COSTE-FIJO.md`. Falla en alto (y no reescribe) ante una respuesta parcial, NaN, precio cero, varios precios candidatos, otra moneda u otra unidad. `--prueba` comprueba esos casos sin red |
| `COSTE-FIJO.md` | Generado. Coste fijo mensual por pilar, ×3, plataforma y Firewall |

## Lo que no se puede cambiar después

- **El vínculo del proyecto con Storage, AI Search y Cosmos DB** (RED-5): las tres conexiones y el capability host
  `caphost-agentes` lo fijan. Cambiar cualquiera de los tres obliga a **borrar y recrear el proyecto**.
- **La conexión de Key Vault del recurso de Foundry** tiene que ser la primera conexión del recurso (Learn,
  set-up-key-vault-connection: «A Foundry resource with no existing connections at the resource or project level»).
  Por eso el proyecto depende de ella. Solo admite una.
- **La subred de agentes** es exclusiva de un recurso de Foundry (A12) y la región del recurso es la de la VNet (RED-7).
- **Purga del Key Vault**: con `enablePurgeProtection` no se puede desactivar ni purgar antes de los 90 días.

## Piezas en preview o fuera de los tipos de Bicep

- `capabilityHostKind: 'Agents'` no está en los tipos de Bicep pero la API lo exige (plantilla oficial
  `foundry-samples/…/15-private-network-standard-agent-setup`): se suprime el aviso BCP037 en esa línea.
- `authType: 'AccountManagedIdentity'` de la conexión de Key Vault: valor de la plantilla de Learn, ausente de los
  tipos de Bicep (BCP036 suprimido). LES-G-049: si la conexión no aparece tras desplegar, sospechar de este literal.
- `proyecto.properties.internalId` (para la condición ABAC del contenedor del agente): la API lo devuelve, los tipos no.
- `Microsoft.Insights/diagnosticSettings@2021-05-01-preview`: la versión con `categoryGroup` es preview.
- No se usa la API de ajustes de capacidad `2026-07-15-preview` (CAD-4); se usa el capability host, que Learn mantiene.

## Versiones de API

Se usa la versión GA más reciente **para la que Bicep 0.48.1 trae tipos**, para que el compilador valide las
propiedades (con tipos ausentes, BCP081, nada se valida). Donde Learn publica una más nueva sin tipos aún, se indica.
Consulta de la referencia de plantillas: 2026-11-04, `https://learn.microsoft.com/en-us/azure/templates/<tipo>`.

| Tipo | Versión usada | Más reciente en Learn |
|---|---|---|
| `Microsoft.CognitiveServices/accounts` (+ `deployments`, `connections`, `projects`, `projects/connections`, `projects/capabilityHosts`) | 2026-09-01 | 2026-09-01 (GA) |
| `Microsoft.Storage/storageAccounts` (+ `blobServices`) | 2026-06-01 | 2026-09-01 (sin tipos en Bicep 0.48.1) |
| `Microsoft.Search/searchServices` | 2025-05-01 | 2026-11-01 (sin tipos en Bicep 0.48.1) |
| `Microsoft.DocumentDB/databaseAccounts` (+ `sqlRoleAssignments`) | 2026-03-15 | 2026-03-15 |
| `Microsoft.KeyVault/vaults` | 2026-05-15 | 2026-05-15 |
| `Microsoft.ContainerRegistry/registries` | 2025-11-01 | 2025-11-01 |
| `Microsoft.App/managedEnvironments`, `containerApps` | 2026-07-01 | 2026-07-01 |
| `Microsoft.Network/*` (VNet, emparejamiento, endpoints privados, grupos de zonas, tablas de rutas, IP pública, Firewall y su política) | 2026-01-01 | 2026-03-01 (sin tipos en Bicep 0.48.1) |
| `Microsoft.Network/privateDnsZones` (+ `virtualNetworkLinks`) | 2024-06-01 | 2024-06-01 |
| `Microsoft.Network/FrontDoorWebApplicationFirewallPolicies` | 2026-04-01 | 2026-04-01 |
| `Microsoft.Cdn/profiles` (+ `afdEndpoints`, `routes`, `originGroups`, `origins`, `securityPolicies`) | 2026-07-01 | 2026-07-01 |
| `Microsoft.OperationalInsights/workspaces` | 2026-03-01 | 2026-03-01 |
| `Microsoft.Insights/components` | 2020-02-02 | 2020-02-02 |
| `Microsoft.Insights/diagnosticSettings` | 2021-05-01-preview | 2021-05-01-preview |
| `Microsoft.ManagedIdentity/userAssignedIdentities` (+ `federatedIdentityCredentials`) | 2024-11-30 | 2024-11-30 |
| `Microsoft.Authorization/roleAssignments` | 2022-04-01 | 2022-04-01 |
| `Microsoft.Authorization/policyAssignments` | 2026-07-01 | 2026-07-01 |
| `Microsoft.Consumption/budgets` | 2026-06-01 | 2026-06-01 |
| `Microsoft.Resources/resourceGroups` | 2025-04-01 | 2025-04-01 |

## Identidades y roles declarados (los aplica quien despliega, con permiso para asignar roles)

GUID comprobados en Learn (`role-based-access-control/built-in-roles` y sus subpáginas) el 2026-11-04.

| Identidad | Rol | Ámbito |
|---|---|---|
| Backend del pilar (asignada por usuario) | Foundry Agent Consumer (`eed3b665-…`) | Proyecto del pilar. Al crear el coordinador, reducir a `…/agents/<coordinador>` y borrar la de proyecto (LES-G-089 §9) |
| Backend | Key Vault Secrets User, AcrPull | Key Vault y ACR del pilar |
| Frontal | AcrPull | ACR del pilar (no llega a Foundry) |
| Identidad del proyecto | Cosmos DB Operator, Storage Account Contributor, Storage Blob Data Contributor, Search Index Data Contributor, Search Service Contributor | Sus recursos, **antes** del capability host |
| Identidad del proyecto | Storage Blob Data Owner con condición ABAC (`<workspaceId>…-azureml-agent`) y Cosmos DB Built-in Data Contributor sobre `enterprise_memory` | **Después** del capability host |
| Recurso de Foundry | Key Vault Secrets Officer | Key Vault del pilar (conexión de Key Vault) |
| CI/CD del pilar (OIDC, `environment:<pilar>`) | Container Apps Contributor (`358470bc-…`), AcrPush | Solo las dos Container Apps y el ACR del pilar. No toca red, Foundry, Key Vault ni roles. Riesgo residual: quien despliega el backend ejecuta código con la identidad del backend |

Políticas con `Deny` en cada grupo de pilar: «Azure AI Services resources should have key access disabled»
(`71ef260a-…`) y «…should restrict network access» (`037eea7a-…`), ambas con parámetro `effect` = Deny (comprobado).

## Pasos manuales tras un despliegue (no los hace la plantilla)

1. **Aprobar la conexión de Private Link de Front Door** en cada entorno de Container Apps (queda pendiente; Learn,
   container-apps/how-to-integrate-with-azure-front-door). Sin eso el frontal no recibe tráfico.
2. Reducir Foundry Agent Consumer del backend al agente coordinador (arriba).
3. Crear los entornos `azure`, `gcp` y `aws` en GitHub para que la credencial federada case.
4. Publicar las imágenes reales en el ACR del pilar (por defecto corre una imagen pública de ejemplo).
5. Si el pilar de Google necesita la clave de Developer Knowledge (Developer Knowledge API de Google), guardarla en su Key Vault.

## Límites conocidos (shortcut)

- La salida de Container Apps **no** pasa por el Firewall (solo la de los agentes). Llevarla antes de producción
  exige abrir en el Firewall MCR, Entra y los dominios de Google para la comprobación del `hd`.
- Sin Azure Monitor Private Link Scope: la ingesta de Application Insights es pública y conserva la clave local,
  porque la conexión de trazas de Foundry usa la cadena de conexión. La plantilla oficial lo resuelve con AMPLS.
- No incluye: VPN/ExpressRoute ni Bastion, Defender for Cloud ni Purview (son de suscripción y se activan aparte),
  la política de guardarraíles obligatorios (IA-3) ni la de modelos aprobados (IA-6), CMK.
- Cosmos DB va en serverless (sin coste fijo). Learn dice a la vez que admite serverless y que la cuenta debe tener
  un límite de 3000 RU/s: si falla al crear el capability host, pasar a aprovisionado (coste en `COSTE-FIJO.md`).
- Quotas de modelos: `capacidadGpt6Luna` y `capacidadGpt56Luna` (50K TPM por defecto) salen de la misma cuota de
  suscripción para los tres pilares.

## Uso

```bash
infra/comprobar.sh              # validación local, sin Azure
python3 infra/coste_fijo.py     # regenera COSTE-FIJO.md con precios del día
```

El despliegue (`az deployment sub create -l swedencentral -f infra/main.bicep -p @<parametros-reales>.json`) lo
lanza una persona con permiso para asignar roles, previa revisión con `what-if`.
