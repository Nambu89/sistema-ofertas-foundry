// Instancia de un pilar de la preventa multinube: montaje estándar de Foundry con red privada,
// frontal y backend en Container Apps, observabilidad, política y presupuesto. Ámbito: grupo de recursos del pilar.
// Fuentes: las páginas de Learn citadas en cada bloque. Nada de esto se ha desplegado.
targetScope = 'resourceGroup'

@allowed(['azure', 'gcp', 'aws'])
param pilar string
param location string = resourceGroup().location
@maxLength(6)
param prefijo string
@description('Espacio de direcciones /16 de la VNet del pilar (RFC 1918, sin solapes con el hub ni con otros pilares).')
param cidr string
@description('Id de la VNet hub de la plataforma; vacío si se despliega sin Firewall.')
param hubVnetId string = ''
@description('IP privada del Azure Firewall; vacía si se despliega sin Firewall.')
param firewallIpPrivada string = ''
@description('principalId de la identidad de CI/CD (OIDC de GitHub) de este pilar.')
param ciPrincipalId string
@description('Capacidad en miles de TPM de cada despliegue. La cuota es de la suscripción y la reparten los tres pilares.')
param capacidadGpt6Luna int = 50
param capacidadGpt56Luna int = 50
@description('Imágenes del frontal y del backend. Por defecto, una imagen de ejemplo pública hasta que CI/CD publique las reales en el ACR del pilar.')
param imagenFrontal string = 'mcr.microsoft.com/k8se/quickstart:latest'
param imagenBackend string = 'mcr.microsoft.com/k8se/quickstart:latest'
param presupuestoMensualEur int
param contactosPresupuesto array
@description('Primer día del mes en que empieza el presupuesto (yyyy-MM-01).')
param inicioPresupuesto string = utcNow('yyyy-MM-01')

var suf = take(uniqueString(resourceGroup().id), 6)
var base = '${prefijo}-${pilar}'
var conFirewall = !empty(firewallIpPrivada)

// GUID de roles integrados, comprobados en Learn (built-in-roles) el 2026-11-04.
var rol = {
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  acrPush: '8311e382-0749-4cb8-b61a-304f252e45ec'
  containerAppsContributor: '358470bc-b998-42bd-ab17-a7e34c199c0f'
  foundryAgentConsumer: 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6'
  kvSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  kvSecretsOfficer: 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'
  storageAccountContributor: '17d1049b-9a84-46fb-8f53-869881c3d3ab'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  cosmosDbOperator: '230815da-be43-4aae-9cb4-875f7bd000aa'
}

// ---------- Observabilidad del pilar (OP-1, OP-2) ----------
resource law 'Microsoft.OperationalInsights/workspaces@2026-03-01' = {
  name: '${base}-law-${suf}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    features: { disableLocalAuth: true }
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: '${base}-appi-${suf}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    // Sin AMPLS la ingesta es pública; la clave local sigue activa porque la conexión de trazas de Foundry usa la cadena de conexión.
    DisableLocalAuth: false
  }
}

// ---------- Red del pilar (RED-6, RED-7) ----------
resource rutas 'Microsoft.Network/routeTables@2026-01-01' = if (conFirewall) {
  name: '${base}-rt-agentes'
  location: location
  properties: {
    disableBgpRoutePropagation: true
    routes: [
      {
        name: 'salida-por-firewall'
        properties: { addressPrefix: '0.0.0.0/0', nextHopType: 'VirtualAppliance', nextHopIpAddress: firewallIpPrivada }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2026-01-01' = {
  name: '${base}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: [cidr] }
    subnets: [
      {
        // Exclusiva del recurso de Foundry de este pilar (A12).
        name: 'snet-agentes'
        properties: {
          addressPrefix: cidrSubnet(cidr, 24, 0)
          delegations: [{ name: 'agentes', properties: { serviceName: 'Microsoft.App/environments' } }]
          routeTable: conFirewall ? { id: rutas.id } : null
        }
      }
      {
        name: 'snet-pe'
        properties: { addressPrefix: cidrSubnet(cidr, 24, 1) }
      }
      {
        // shortcut: la salida de Container Apps no pasa por el Firewall (exigiría abrir MCR, Entra y Google en sus reglas); llevarla allí antes de producción.
        name: 'snet-aca'
        properties: {
          addressPrefix: cidrSubnet(cidr, 24, 2)
          delegations: [{ name: 'aca', properties: { serviceName: 'Microsoft.App/environments' } }]
        }
      }
    ]
  }
}

resource peeringAlHub 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2026-01-01' = if (!empty(hubVnetId)) {
  parent: vnet
  name: 'al-hub'
  properties: {
    remoteVirtualNetwork: { id: hubVnetId }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
  }
}

// ---------- Recursos propios del montaje estándar (RED-3): Storage, AI Search y Cosmos DB ----------
resource st 'Microsoft.Storage/storageAccounts@2026-06-01' = {
  name: toLower('${prefijo}${pilar}st${suf}')
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_ZRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    networkAcls: { bypass: 'AzureServices', defaultAction: 'Deny' }
  }
}

resource stBlob 'Microsoft.Storage/storageAccounts/blobServices@2026-06-01' = {
  parent: st
  name: 'default'
  properties: {
    isVersioningEnabled: true // DAT-7
    deleteRetentionPolicy: { enabled: true, days: 14 }
    containerDeleteRetentionPolicy: { enabled: true, days: 14 }
  }
}

resource srch 'Microsoft.Search/searchServices@2025-05-01' = {
  name: '${base}-srch-${suf}'
  location: location
  sku: { name: 'basic' } // nivel mínimo con endpoint privado (Learn: «Basic tier or higher»)
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    disableLocalAuth: true
    publicNetworkAccess: 'disabled'
    networkRuleSet: { bypass: 'None', ipRules: [] }
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2026-03-15' = {
  name: '${base}-cosmos-${suf}'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    // Learn (standard-agent-setup): «Both Provisioned Throughput and Serverless modes are supported.» Sin coste fijo de RU/s.
    capabilities: [{ name: 'EnableServerless' }]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
  }
}

// ---------- Key Vault (DAT-5, DAT-6) y ACR Premium (RED-13) ----------
resource kv 'Microsoft.KeyVault/vaults@2026-05-15' = {
  name: '${base}-kv-${suf}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { bypass: 'AzureServices', defaultAction: 'Deny' }
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: toLower('${prefijo}${pilar}acr${suf}')
  location: location
  sku: { name: 'Premium' }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    publicNetworkAccess: 'Disabled'
    networkRuleBypassOptions: 'AzureServices'
  }
}

// ---------- Microsoft Foundry: recurso, modelos, proyecto y capability host ----------
resource foundry 'Microsoft.CognitiveServices/accounts@2026-09-01' = {
  name: '${base}-fdry-${suf}'
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: '${base}-fdry-${suf}'
    disableLocalAuth: true // ID-1
    publicNetworkAccess: 'Disabled' // RED-1
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices', ipRules: [], virtualNetworkRules: [] }
    networkInjections: [
      { scenario: 'agent', subnetArmId: vnet.properties.subnets[0].id, useMicrosoftManagedNetwork: false }
    ]
  }
}

resource gpt6Luna 'Microsoft.CognitiveServices/accounts/deployments@2026-09-01' = {
  parent: foundry
  name: 'gpt-6-luna'
  sku: { name: 'DataZoneStandard', capacity: capacidadGpt6Luna } // DAT-1
  properties: {
    model: { format: 'OpenAI', name: 'gpt-6-luna', version: '2026-09-22' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource gpt56Luna 'Microsoft.CognitiveServices/accounts/deployments@2026-09-01' = {
  parent: foundry
  name: 'gpt-5.6-luna'
  sku: { name: 'DataZoneStandard', capacity: capacidadGpt56Luna }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5.6-luna', version: '2026-07-09' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [gpt6Luna] // dos despliegues a la vez sobre el mismo recurso chocan
}

// Learn exige que la conexión de Key Vault sea la primera del recurso («no existing connections»): el proyecto depende de ella.
resource conexionKv 'Microsoft.CognitiveServices/accounts/connections@2026-09-01' = {
  parent: foundry
  name: '${foundry.name}-keyvault'
  properties: {
    category: 'AzureKeyVault'
    target: kv.id
    #disable-next-line BCP036
    authType: 'AccountManagedIdentity' // valor de la plantilla de Learn (set-up-key-vault-connection); los tipos de Bicep no lo recogen
    isSharedToAll: true
    metadata: { ApiType: 'Azure', ResourceId: kv.id, location: kv.location }
  }
  dependsOn: [rolFoundryKv]
}

resource proyecto 'Microsoft.CognitiveServices/accounts/projects@2026-09-01' = {
  parent: foundry
  name: '${base}-prj'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Preventa ${pilar}'
    description: 'Proyecto de producción del pilar ${pilar}'
  }
  dependsOn: [conexionKv, gpt56Luna]
}

// IRREVERSIBLE (RED-5): estas tres conexiones y el capability host fijan Storage, Search y Cosmos del proyecto.
// Cambiarlos obliga a borrar y recrear el proyecto.
resource conexionCosmos 'Microsoft.CognitiveServices/accounts/projects/connections@2026-09-01' = {
  parent: proyecto
  name: cosmos.name
  properties: {
    category: 'CosmosDB'
    target: cosmos.properties.documentEndpoint
    authType: 'AAD'
    metadata: { ApiType: 'Azure', ResourceId: cosmos.id, location: cosmos.location }
  }
}

resource conexionSt 'Microsoft.CognitiveServices/accounts/projects/connections@2026-09-01' = {
  parent: proyecto
  name: st.name
  properties: {
    category: 'AzureStorageAccount'
    target: st.properties.primaryEndpoints.blob
    authType: 'AAD'
    metadata: { ApiType: 'Azure', ResourceId: st.id, location: st.location }
  }
  dependsOn: [conexionCosmos] // conexiones en serie sobre el mismo proyecto
}

resource conexionSrch 'Microsoft.CognitiveServices/accounts/projects/connections@2026-09-01' = {
  parent: proyecto
  name: srch.name
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${srch.name}.search.windows.net'
    authType: 'AAD'
    metadata: { ApiType: 'Azure', ResourceId: srch.id, location: srch.location }
  }
  dependsOn: [conexionSt]
}

// LES-G-090: una sola conexión AppInsights por proyecto.
resource conexionAppi 'Microsoft.CognitiveServices/accounts/projects/connections@2026-09-01' = {
  parent: proyecto
  name: '${base}-appinsights'
  properties: {
    category: 'AppInsights'
    target: appi.id
    authType: 'ApiKey'
    credentials: { key: appi.properties.ConnectionString }
    metadata: { ApiType: 'Azure', ResourceId: appi.id }
  }
  dependsOn: [conexionSrch]
}

// Roles de la identidad del proyecto ANTES del capability host (Learn, standard-agent-setup, fases 3 y 4).
var rolesProyectoPrevios = [
  { scope: 'cosmos', rol: rol.cosmosDbOperator }
  { scope: 'st', rol: rol.storageAccountContributor }
  { scope: 'st', rol: rol.storageBlobDataContributor }
  { scope: 'srch', rol: rol.searchIndexDataContributor }
  { scope: 'srch', rol: rol.searchServiceContributor }
]

resource rolProyectoCosmos 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in filter(rolesProyectoPrevios, x => x.scope == 'cosmos'): {
  scope: cosmos
  name: guid(cosmos.id, proyecto.id, r.rol)
  properties: { principalId: proyecto.identity.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r.rol) }
}]

resource rolProyectoSt 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in filter(rolesProyectoPrevios, x => x.scope == 'st'): {
  scope: st
  name: guid(st.id, proyecto.id, r.rol)
  properties: { principalId: proyecto.identity.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r.rol) }
}]

resource rolProyectoSrch 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in filter(rolesProyectoPrevios, x => x.scope == 'srch'): {
  scope: srch
  name: guid(srch.id, proyecto.id, r.rol)
  properties: { principalId: proyecto.identity.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r.rol) }
}]

// El capability host de cuenta lo crea la plataforma al haber networkInjections (plantilla oficial 15-private-network).
resource capHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2026-09-01' = {
  parent: proyecto
  name: 'caphost-agentes'
  properties: {
    #disable-next-line BCP037
    capabilityHostKind: 'Agents' // la API lo exige aunque los tipos de Bicep no lo declaren (plantilla oficial)
    vectorStoreConnections: [conexionSrch.name]
    storageConnections: [conexionSt.name]
    threadStorageConnections: [conexionCosmos.name]
  }
  dependsOn: [rolProyectoCosmos, rolProyectoSt, rolProyectoSrch, conexionAppi, peSt, peSrch, peCosmos]
}

// Roles DESPUÉS del capability host: contenedores del agente y base de datos enterprise_memory.
#disable-next-line BCP053
var wsId = proyecto.properties.internalId // la API lo devuelve aunque los tipos no lo declaren (plantilla oficial)
var wsGuid = '${substring(wsId, 0, 8)}-${substring(wsId, 8, 4)}-${substring(wsId, 12, 4)}-${substring(wsId, 16, 4)}-${substring(wsId, 20, 12)}'

resource rolProyectoBlobOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: st
  name: guid(st.id, proyecto.id, rol.storageBlobDataOwner)
  properties: {
    principalId: proyecto.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.storageBlobDataOwner)
    conditionVersion: '2.0'
    // Solo sobre el contenedor <workspaceId>-azureml-agent (condición de la plantilla oficial).
    condition: '((!(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read\'}) AND !(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/filter/action\'}) AND !(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/write\'})) OR (@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringStartsWithIgnoreCase \'${wsGuid}\' AND @Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringLikeIgnoreCase \'*-azureml-agent\'))'
  }
  dependsOn: [capHost]
}

resource rolProyectoCosmosDatos 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2026-03-15' = {
  parent: cosmos
  name: guid(cosmos.id, proyecto.id, 'cosmos-data-contributor')
  properties: {
    principalId: proyecto.identity.principalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002' // Cosmos DB Built-in Data Contributor
    scope: '${cosmos.id}/dbs/enterprise_memory'
  }
  dependsOn: [capHost]
}

// ---------- Endpoints privados y DNS privado del pilar (RED-4); zonas vinculadas solo a esta VNet ----------
var zonaBlob = 'privatelink.blob.${environment().suffixes.storage}'
var zonas = [
  'privatelink.cognitiveservices.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.services.ai.azure.com'
  zonaBlob
  'privatelink.search.windows.net'
  'privatelink.documents.azure.com'
  'privatelink.vaultcore.azure.net'
  'privatelink.azurecr.io'
]

resource dns 'Microsoft.Network/privateDnsZones@2024-06-01' = [for z in zonas: {
  name: z
  location: 'global'
}]

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (z, i) in zonas: {
  parent: dns[i]
  name: '${base}-vnet'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnet.id } }
}]

module peFoundry 'modulos/pe.bicep' = {
  name: '${base}-pe-fdry'
  params: { nombre: '${base}-pe-fdry', location: location, subnetId: vnet.properties.subnets[1].id, recursoId: foundry.id, grupo: 'account', zonas: take(zonas, 3) }
  dependsOn: [dns]
}
module peSt 'modulos/pe.bicep' = {
  name: '${base}-pe-st'
  params: { nombre: '${base}-pe-st', location: location, subnetId: vnet.properties.subnets[1].id, recursoId: st.id, grupo: 'blob', zonas: [zonaBlob] }
  dependsOn: [dns]
}
module peSrch 'modulos/pe.bicep' = {
  name: '${base}-pe-srch'
  params: { nombre: '${base}-pe-srch', location: location, subnetId: vnet.properties.subnets[1].id, recursoId: srch.id, grupo: 'searchService', zonas: ['privatelink.search.windows.net'] }
  dependsOn: [dns]
}
module peCosmos 'modulos/pe.bicep' = {
  name: '${base}-pe-cosmos'
  params: { nombre: '${base}-pe-cosmos', location: location, subnetId: vnet.properties.subnets[1].id, recursoId: cosmos.id, grupo: 'Sql', zonas: ['privatelink.documents.azure.com'] }
  dependsOn: [dns]
}
module peKv 'modulos/pe.bicep' = {
  name: '${base}-pe-kv'
  params: { nombre: '${base}-pe-kv', location: location, subnetId: vnet.properties.subnets[1].id, recursoId: kv.id, grupo: 'vault', zonas: ['privatelink.vaultcore.azure.net'] }
  dependsOn: [dns]
}
module peAcr 'modulos/pe.bicep' = {
  name: '${base}-pe-acr'
  params: { nombre: '${base}-pe-acr', location: location, subnetId: vnet.properties.subnets[1].id, recursoId: acr.id, grupo: 'registry', zonas: ['privatelink.azurecr.io'] }
  dependsOn: [dns]
}

// ---------- Identidades del frontal y del backend, y roles mínimos ----------
resource idFrontal 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: '${base}-id-frontal'
  location: location
}

resource idBackend 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: '${base}-id-backend'
  location: location
}

resource rolFrontalAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, idFrontal.id, rol.acrPull)
  properties: { principalId: idFrontal.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.acrPull) }
}

resource rolBackendAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, idBackend.id, rol.acrPull)
  properties: { principalId: idBackend.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.acrPull) }
}

// Foundry Agent Consumer sobre el PROYECTO: los agentes no son recursos ARM y no se pueden acotar aquí.
// Tras crear el coordinador, reducir al ámbito …/projects/<proyecto>/agents/<coordinador> (LES-G-089 §9) y borrar esta.
resource rolBackendFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: proyecto
  name: guid(proyecto.id, idBackend.id, rol.foundryAgentConsumer)
  properties: { principalId: idBackend.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.foundryAgentConsumer) }
}

resource rolBackendKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, idBackend.id, rol.kvSecretsUser)
  properties: { principalId: idBackend.properties.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.kvSecretsUser) }
}

resource rolFoundryKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: kv
  name: guid(kv.id, foundry.id, rol.kvSecretsOfficer)
  properties: { principalId: foundry.identity.principalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.kvSecretsOfficer) }
}

// CI/CD del pilar: publicar imágenes y actualizar SOLO las dos Container Apps. No toca red, Foundry, Key Vault ni roles:
// el despliegue de infraestructura lo lanza una persona. Riesgo residual: quien despliega el backend ejecuta código con su identidad.
resource rolCiFrontal 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: frontal
  name: guid(frontal.id, ciPrincipalId, rol.containerAppsContributor)
  properties: { principalId: ciPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.containerAppsContributor) }
}

resource rolCiBackend 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: backend
  name: guid(backend.id, ciPrincipalId, rol.containerAppsContributor)
  properties: { principalId: ciPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.containerAppsContributor) }
}

resource rolCiAcr 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, ciPrincipalId, rol.acrPush)
  properties: { principalId: ciPrincipalId, principalType: 'ServicePrincipal', roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', rol.acrPush) }
}

// ---------- Container Apps: frontal web (detrás de Front Door por Private Link) y backend interno ----------
resource aca 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: '${base}-cae'
  location: location
  properties: {
    workloadProfiles: [{ name: 'Consumption', workloadProfileType: 'Consumption' }] // Private Link con Front Door exige perfiles de carga
    vnetConfiguration: { infrastructureSubnetId: vnet.properties.subnets[2].id, internal: false }
    publicNetworkAccess: 'Disabled' // solo entra Front Door por Private Link
    appLogsConfiguration: { destination: 'azure-monitor' } // sin clave compartida de Log Analytics
  }
}

resource acaDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: aca
  name: 'a-log-analytics'
  properties: {
    workspaceId: law.id
    logs: [{ categoryGroup: 'allLogs', enabled: true }]
  }
}

var endpointProyecto = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${proyecto.name}'

resource backend 'Microsoft.App/containerApps@2026-07-01' = {
  name: '${base}-backend'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${idBackend.id}': {} } }
  properties: {
    environmentId: aca.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: false, targetPort: 80, allowInsecure: false, transport: 'auto' }
      registries: [{ server: acr.properties.loginServer, identity: idBackend.id }]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: imagenBackend
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'PILAR', value: pilar }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: endpointProyecto }
            { name: 'AZURE_CLIENT_ID', value: idBackend.properties.clientId }
            { name: 'KEY_VAULT_URI', value: kv.properties.vaultUri }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 3 } // escala a cero: sin coste fijo de cómputo
    }
  }
  dependsOn: [rolBackendAcr, peAcr]
}

resource frontal 'Microsoft.App/containerApps@2026-07-01' = {
  name: '${base}-frontal'
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${idFrontal.id}': {} } }
  properties: {
    environmentId: aca.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: { external: true, targetPort: 80, allowInsecure: false, transport: 'auto' }
      registries: [{ server: acr.properties.loginServer, identity: idFrontal.id }]
    }
    template: {
      containers: [
        {
          name: 'frontal'
          image: imagenFrontal
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'PILAR', value: pilar }
            { name: 'BACKEND_URL', value: 'https://${backend.properties.configuration.ingress.fqdn}' }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 3 }
    }
  }
  dependsOn: [rolFrontalAcr, peAcr]
}

// ---------- Gobierno del pilar: Azure Policy con Deny (IA-7, OP-6) y presupuesto (OP-4) ----------
var politicas = [
  { nombre: 'ai-sin-clave-local', id: '71ef260a-8f18-47b7-abcb-62d0673d94dc' } // key access disabled
  { nombre: 'ai-red-restringida', id: '037eea7a-bd0a-46c5-9a66-03aea78705d3' } // restrict network access
]

resource politica 'Microsoft.Authorization/policyAssignments@2026-07-01' = [for p in politicas: {
  name: '${base}-${p.nombre}'
  properties: {
    displayName: '${base}: ${p.nombre}'
    policyDefinitionId: tenantResourceId('Microsoft.Authorization/policyDefinitions', p.id)
    parameters: { effect: { value: 'Deny' } }
  }
}]

resource presupuesto 'Microsoft.Consumption/budgets@2026-06-01' = {
  name: '${base}-presupuesto'
  properties: {
    category: 'Cost'
    amount: presupuestoMensualEur
    timeGrain: 'Monthly'
    timePeriod: { startDate: inicioPresupuesto }
    notifications: {
      real80: { enabled: true, operator: 'GreaterThan', threshold: 80, thresholdType: 'Actual', contactEmails: contactosPresupuesto }
      previsto100: { enabled: true, operator: 'GreaterThan', threshold: 100, thresholdType: 'Forecasted', contactEmails: contactosPresupuesto }
    }
  }
}

output vnetId string = vnet.id
output vnetName string = vnet.name
output subredAgentes string = cidrSubnet(cidr, 24, 0)
output acaId string = aca.id
output frontalFqdn string = frontal.properties.configuration.ingress.fqdn
output endpointProyecto string = endpointProyecto
output proyectoId string = proyecto.id
