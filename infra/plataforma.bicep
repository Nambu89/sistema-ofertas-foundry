// Plataforma compartida de la preventa multinube: Front Door Premium + WAF, red hub con Azure Firewall (opcional),
// Log Analytics de plataforma e identidades de CI/CD con credencial federada OIDC de GitHub (una por pilar, CAD-1).
// Ámbito: grupo de recursos de plataforma. Nada de esto se ha desplegado.
targetScope = 'resourceGroup'

param location string = resourceGroup().location
@maxLength(6)
param prefijo string
param pilares array
@description('Despliega la red hub con Azure Firewall (salida controlada por FQDN, RED-9). Sin él, los agentes salen sin filtro por destino.')
param conFirewall bool = true
param hubCidr string = '10.10.0.0/24'
@description('Organización y repositorio de GitHub para la federación OIDC (marcadores en main.parameters.json).')
param githubOrg string
param githubRepo string

var base = '${prefijo}-plat'

resource law 'Microsoft.OperationalInsights/workspaces@2026-03-01' = {
  name: '${base}-law-${take(uniqueString(resourceGroup().id), 6)}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    features: { disableLocalAuth: true }
  }
}

// ---------- Front Door Premium + WAF (Premium: Private Link hacia Container Apps y reglas administradas) ----------
resource waf 'Microsoft.Network/FrontDoorWebApplicationFirewallPolicies@2026-04-01' = {
  name: '${prefijo}platwaf'
  location: 'Global'
  sku: { name: 'Premium_AzureFrontDoor' }
  properties: {
    policySettings: { enabledState: 'Enabled', mode: 'Prevention', requestBodyCheck: 'Enabled' }
    managedRules: {
      managedRuleSets: [
        { ruleSetType: 'Microsoft_DefaultRuleSet', ruleSetVersion: '2.1', ruleSetAction: 'Block' }
        { ruleSetType: 'Microsoft_BotManagerRuleSet', ruleSetVersion: '1.1' }
      ]
    }
  }
}

resource afd 'Microsoft.Cdn/profiles@2026-07-01' = {
  name: '${base}-afd'
  location: 'global'
  sku: { name: 'Premium_AzureFrontDoor' }
}

resource afdDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: afd
  name: 'a-log-analytics'
  properties: { workspaceId: law.id, logs: [{ categoryGroup: 'allLogs', enabled: true }] }
}

// ---------- Red hub con Azure Firewall Standard (C-HUB, C-FW) ----------
resource hub 'Microsoft.Network/virtualNetworks@2026-01-01' = if (conFirewall) {
  name: '${base}-hub'
  location: location
  properties: {
    addressSpace: { addressPrefixes: [hubCidr] }
    subnets: [{ name: 'AzureFirewallSubnet', properties: { addressPrefix: cidrSubnet(hubCidr, 26, 0) } }]
  }
}

resource fwIp 'Microsoft.Network/publicIPAddresses@2026-01-01' = if (conFirewall) {
  name: '${base}-fw-pip'
  location: location
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}

resource fwPolitica 'Microsoft.Network/firewallPolicies@2026-01-01' = if (conFirewall) {
  name: '${base}-fw-pol'
  location: location
  properties: {
    sku: { tier: 'Standard' }
    threatIntelMode: 'Deny'
  }
}

resource fw 'Microsoft.Network/azureFirewalls@2026-01-01' = if (conFirewall) {
  name: '${base}-fw'
  location: location
  properties: {
    sku: { name: 'AZFW_VNet', tier: 'Standard' }
    firewallPolicy: { id: fwPolitica.id }
    ipConfigurations: [
      {
        name: 'ipconfig'
        properties: { subnet: { id: hub!.properties.subnets[0].id }, publicIPAddress: { id: fwIp.id } }
      }
    ]
  }
}

resource fwDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (conFirewall) {
  scope: fw
  name: 'a-log-analytics'
  properties: { workspaceId: law.id, logAnalyticsDestinationType: 'Dedicated', logs: [{ categoryGroup: 'allLogs', enabled: true }] }
}

// ---------- Identidades de CI/CD, una por pilar, federadas con GitHub Actions (sin secretos) ----------
resource idCi 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [for p in pilares: {
  name: '${prefijo}-${p}-id-ci'
  location: location
}]

resource fedCi 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2024-11-30' = [for (p, i) in pilares: {
  parent: idCi[i]
  name: 'github-${p}'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubOrg}/${githubRepo}:environment:${p}' // solo el entorno de GitHub del pilar
    audiences: ['api://AzureADTokenExchange']
  }
}]

output afdName string = afd.name
output wafId string = waf.id
output hubVnetId string = conFirewall ? hub.id : ''
output hubVnetName string = conFirewall ? hub.name : ''
output firewallIpPrivada string = conFirewall ? fw!.properties.ipConfigurations[0].properties.privateIPAddress : ''
output firewallPoliticaName string = conFirewall ? fwPolitica.name : ''
output ciPrincipalIds array = [for (p, i) in pilares: idCi[i].properties.principalId]
