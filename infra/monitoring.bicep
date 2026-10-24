// Log Analytics workspace + workspace-based Application Insights.
param name string
param location string
param retentionInDays int
param tags object

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${name}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionInDays
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${name}'
  location: location
  tags: tags
  kind: 'other'
  properties: {
    Application_Type: 'other'
    WorkspaceResourceId: logs.id
    IngestionMode: 'LogAnalytics'
  }
}

output connectionString string = appi.properties.ConnectionString
output appInsightsName string = appi.name
