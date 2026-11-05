// Endpoint privado con su grupo de zonas DNS (las zonas ya existen en el grupo de recursos del pilar).
param nombre string
param location string
param subnetId string
param recursoId string
param grupo string
param zonas array

resource pe 'Microsoft.Network/privateEndpoints@2026-01-01' = {
  name: nombre
  location: location
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      { name: nombre, properties: { privateLinkServiceId: recursoId, groupIds: [grupo] } }
    ]
  }
}

resource zonasPe 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2026-01-01' = {
  parent: pe
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [for z in zonas: {
      name: replace(z, '.', '-')
      properties: { privateDnsZoneId: resourceId('Microsoft.Network/privateDnsZones', z) }
    }]
  }
}
