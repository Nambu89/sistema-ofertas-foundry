// Lo que cada pilar necesita dentro del grupo de recursos de plataforma: ruta de Front Door con WAF hacia su frontal
// (Private Link), emparejamiento hub -> pilar y reglas de salida del Firewall para su subred de agentes.
param pilar string
param prefijo string
param location string
param afdName string
param wafId string
param frontalFqdn string
param acaId string
param pilarVnetId string
param subredAgentes string
param hubVnetName string = ''
param firewallPoliticaName string = ''
param prioridad int
@description('FQDN de salida permitidos para los agentes del pilar (identidad de Entra + MCP de documentación del pilar).')
param fqdnsSalida array

resource afd 'Microsoft.Cdn/profiles@2026-07-01' existing = {
  name: afdName
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2026-07-01' = {
  parent: afd
  name: '${prefijo}-${pilar}'
  location: 'global'
  properties: { enabledState: 'Enabled' }
}

resource grupo 'Microsoft.Cdn/profiles/originGroups@2026-07-01' = {
  parent: afd
  name: 'frontal-${pilar}'
  properties: {
    loadBalancingSettings: { sampleSize: 4, successfulSamplesRequired: 3, additionalLatencyInMilliseconds: 50 }
    healthProbeSettings: { probePath: '/', probeRequestType: 'HEAD', probeProtocol: 'Https', probeIntervalInSeconds: 100 }
  }
}

resource origen 'Microsoft.Cdn/profiles/originGroups/origins@2026-07-01' = {
  parent: grupo
  name: 'frontal'
  properties: {
    hostName: frontalFqdn
    originHostHeader: frontalFqdn
    httpsPort: 443
    enforceCertificateNameCheck: true
    // La conexión queda PENDIENTE: hay que aprobarla en el entorno de Container Apps antes de que pase tráfico.
    sharedPrivateLinkResource: {
      privateLink: { id: acaId }
      groupId: 'managedEnvironments'
      privateLinkLocation: location
      requestMessage: 'Front Door ${prefijo}-${pilar}'
    }
  }
}

resource ruta 'Microsoft.Cdn/profiles/afdEndpoints/routes@2026-07-01' = {
  parent: endpoint
  name: 'todo'
  properties: {
    originGroup: { id: grupo.id }
    supportedProtocols: ['Http', 'Https']
    httpsRedirect: 'Enabled'
    forwardingProtocol: 'HttpsOnly'
    patternsToMatch: ['/*']
    linkToDefaultDomain: 'Enabled'
  }
  dependsOn: [origen]
}

resource seguridad 'Microsoft.Cdn/profiles/securityPolicies@2026-07-01' = {
  parent: afd
  name: 'waf-${pilar}'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: { id: wafId }
      associations: [{ domains: [{ id: endpoint.id }], patternsToMatch: ['/*'] }]
    }
  }
}

resource hub 'Microsoft.Network/virtualNetworks@2026-01-01' existing = if (!empty(hubVnetName)) {
  name: hubVnetName
}

resource peeringAlPilar 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2026-01-01' = if (!empty(hubVnetName)) {
  parent: hub
  name: 'al-${pilar}'
  properties: {
    remoteVirtualNetwork: { id: pilarVnetId }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
  }
}

resource fwPolitica 'Microsoft.Network/firewallPolicies@2026-01-01' existing = if (!empty(firewallPoliticaName)) {
  name: firewallPoliticaName
}

resource reglas 'Microsoft.Network/firewallPolicies/ruleCollectionGroups@2026-01-01' = if (!empty(firewallPoliticaName)) {
  parent: fwPolitica
  name: 'salida-${pilar}'
  properties: {
    priority: prioridad
    ruleCollections: [
      {
        ruleCollectionType: 'FirewallPolicyFilterRuleCollection'
        name: 'agentes-${pilar}'
        priority: 100
        action: { type: 'Allow' }
        rules: [
          {
            ruleType: 'ApplicationRule'
            name: 'https-permitido'
            sourceAddresses: [subredAgentes]
            protocols: [{ protocolType: 'Https', port: 443 }]
            targetFqdns: fqdnsSalida
          }
        ]
      }
    ]
  }
}

output endpointHost string = endpoint.properties.hostName
