// Application Insights (workspace-based) for Brownout's decision trace. `azd provision` deploys this.
targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name; prefixes every resource')
param environmentName string

@minLength(1)
@description('Azure region, e.g. westus2')
param location string

@description('Days Log Analytics keeps the trace')
param retentionInDays int = 30

var tags = { 'azd-env-name': environmentName, project: 'brownout' }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module monitoring 'monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    name: environmentName
    location: location
    retentionInDays: retentionInDays
    tags: tags
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.connectionString
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.appInsightsName
