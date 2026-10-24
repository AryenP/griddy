// OPT-IN (main.bicep deployFoundry, off by default): Azure AI Foundry for the agent layer (agent/llm.py FoundryLLM,
// Microsoft Agent Framework's FoundryChatClient). One AI Services account with project management, one project, one
// model deployment, and the signed-in user's roles to call it with Entra ID: no keys anywhere (local auth disabled).
param name string
param location string
param tags object
param modelName string
param modelVersion string
param modelSku string
param modelCapacity int
@description('Object id of the user who runs the demo (azd fills AZURE_PRINCIPAL_ID); empty skips the role grants')
param principalId string

var subdomain = 'ais-${name}-${uniqueString(resourceGroup().id)}'

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: 'ais-${name}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: subdomain
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  parent: account
  name: 'proj-${name}'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {}
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  parent: account
  name: modelName
  sku: { name: modelSku, capacity: modelCapacity }
  properties: { model: { format: 'OpenAI', name: modelName, version: modelVersion } }
}

// Azure AI User (call the project) and Cognitive Services OpenAI User (call the model), for the demo user only.
var roles = ['53ca6127-db72-4b80-b1b0-d745d6d5456d', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd']
resource grants 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for r in roles: if (!empty(principalId)) {
  name: guid(account.id, principalId, r)
  scope: account
  properties: {
    principalId: principalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
  }
}]

output projectEndpoint string = 'https://${subdomain}.services.ai.azure.com/api/projects/${project.name}'
output deploymentName string = deployment.name
