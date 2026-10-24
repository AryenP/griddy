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

@description('Also deploy Azure AI Foundry for the agent layer (foundry.bicep). Off unless AZURE_DEPLOY_FOUNDRY=true.')
param deployFoundry bool = false
param modelName string = 'gpt-4o-mini'
param modelVersion string = '2024-07-18'
param modelSku string = 'GlobalStandard'
param modelCapacity int = 10
param principalId string = ''

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

module foundry 'foundry.bicep' = if (deployFoundry) {
  name: 'foundry'
  scope: rg
  params: {
    name: environmentName
    location: location
    tags: tags
    modelName: modelName
    modelVersion: modelVersion
    modelSku: modelSku
    modelCapacity: modelCapacity
    principalId: principalId
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_AI_PROJECT_ENDPOINT string = deployFoundry ? foundry.outputs.projectEndpoint : ''
output AZURE_MODEL_DEPLOYMENT string = deployFoundry ? foundry.outputs.deploymentName : ''
output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.connectionString
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.appInsightsName
