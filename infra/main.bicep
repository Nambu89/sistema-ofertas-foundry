// Preventa multinube: plataforma compartida + una instancia independiente por pilar (una suscripción, un grupo de recursos por pilar),
// todo en una suscripción. Despliegue de suscripción. NO se ha desplegado ni probado con what-if.
targetScope = 'subscription'

@description('Región de todo el despliegue (Sweden Central; Data Zone UE para los modelos).')
param location string = 'swedencentral'
@maxLength(6)
param prefijo string
param conFirewall bool = true
param hubCidr string = '10.10.0.0/24'
param githubOrg string
param githubRepo string
param contactosPresupuesto array
@description('Un objeto por pilar: id (azure|gcp|aws), cidr (/16), presupuestoMensualEur, fqdnsMcp (MCP de documentación del pilar).')
param pilares array

// Dominios de identidad que Learn exige permitir si hay Firewall (RED-9).
var fqdnsIdentidad = [
  'control-${location}.identity.azure.net'
  '${location}.login.microsoft.com'
  replace(replace(environment().authentication.loginEndpoint, 'https://', ''), '/', '') // login.microsoftonline.com en la nube pública
]

resource rgPlataforma 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${prefijo}-plataforma'
  location: location
}

resource rgPilar 'Microsoft.Resources/resourceGroups@2025-04-01' = [for p in pilares: {
  name: 'rg-${prefijo}-${p.id}'
  location: location
}]

module plataforma 'plataforma.bicep' = {
  scope: rgPlataforma
  name: 'plataforma'
  params: {
    location: location
    prefijo: prefijo
    pilares: map(pilares, p => p.id)
    conFirewall: conFirewall
    hubCidr: hubCidr
    githubOrg: githubOrg
    githubRepo: githubRepo
  }
}

module pilar 'pilar.bicep' = [for (p, i) in pilares: {
  scope: rgPilar[i]
  name: 'pilar-${p.id}'
  params: {
    pilar: p.id
    location: location
    prefijo: prefijo
    cidr: p.cidr
    hubVnetId: plataforma.outputs.hubVnetId
    firewallIpPrivada: plataforma.outputs.firewallIpPrivada
    ciPrincipalId: plataforma.outputs.ciPrincipalIds[i]
    presupuestoMensualEur: p.presupuestoMensualEur
    contactosPresupuesto: contactosPresupuesto
  }
}]

// En serie: la política del Firewall y el perfil de Front Door no admiten escrituras concurrentes.
@batchSize(1)
module enganche 'modulos/enganche-pilar.bicep' = [for (p, i) in pilares: {
  scope: rgPlataforma
  name: 'enganche-${p.id}'
  params: {
    pilar: p.id
    prefijo: prefijo
    location: location
    afdName: plataforma.outputs.afdName
    wafId: plataforma.outputs.wafId
    frontalFqdn: pilar[i].outputs.frontalFqdn
    acaId: pilar[i].outputs.acaId
    pilarVnetId: pilar[i].outputs.vnetId
    subredAgentes: pilar[i].outputs.subredAgentes
    hubVnetName: plataforma.outputs.hubVnetName
    firewallPoliticaName: plataforma.outputs.firewallPoliticaName
    prioridad: 200 + i * 10
    fqdnsSalida: concat(fqdnsIdentidad, p.fqdnsMcp)
  }
}]

output frontales array = [for (p, i) in pilares: { pilar: p.id, frontDoor: enganche[i].outputs.endpointHost, proyecto: pilar[i].outputs.endpointProyecto }]
