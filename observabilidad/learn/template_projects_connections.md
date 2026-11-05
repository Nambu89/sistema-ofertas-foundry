# Microsoft.CognitiveServices accounts/projects/connections 2025-04-01-preview

- [Latest](../../../accounts/projects/connections)
- [2026-07-15-preview](../../../2026-07-15-preview/accounts/projects/connections)
- [2026-07-01](../../../2026-07-01/accounts/projects/connections)
- [2026-05-15-preview](../../../2026-05-15-preview/accounts/projects/connections)
- [2026-05-01](../../../2026-05-01/accounts/projects/connections)
- [2026-03-15-preview](../../../2026-03-15-preview/accounts/projects/connections)
- [2026-03-01](../../../2026-03-01/accounts/projects/connections)
- [2026-01-15-preview](../../../2026-01-15-preview/accounts/projects/connections)
- [2025-12-01](../../../2025-12-01/accounts/projects/connections)
- [2025-10-01-preview](../../../2025-10-01-preview/accounts/projects/connections)
- [2025-09-01](../../../2025-09-01/accounts/projects/connections)
- [2025-07-01-preview](../../../2025-07-01-preview/accounts/projects/connections)
- [2025-06-01](../../../2025-06-01/accounts/projects/connections)
- [2025-04-01-preview](connections)

::: zone pivot="deployment-language-bicep"

## Bicep resource definition

The accounts/projects/connections resource type can be deployed with operations that target:

- **Resource groups** - See [resource group deployment commands](/en-us/azure/azure-resource-manager/bicep/deploy-to-resource-group)

For a list of changed properties in each API version, see [change log](../../../change-log/accounts/projects/connections).

## Resource format

To create a Microsoft.CognitiveServices/accounts/projects/connections resource, add the following Bicep to your template.

```bicep
resource symbolicname 'Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview' = {
  parent: resourceSymbolicName
  name: 'string'
  properties: {
    category: 'string'
    error: 'string'
    expiryTime: 'string'
    isSharedToAll: bool
    metadata: {
      {customized property}: 'string'
    }
    peRequirement: 'string'
    peStatus: 'string'
    sharedUserList: [
      'string'
    ]
    target: 'string'
    useWorkspaceManagedIdentity: bool
    authType: 'string'
    // For remaining properties, see ConnectionPropertiesV2 objects
  }
}
```

### ConnectionPropertiesV2 objects

Set the **authType** property to specify the type of object.

For **AAD**, use:

```bicep
{
  authType: 'AAD'
}
```

For **AccessKey**, use:

```bicep
{
  authType: 'AccessKey'
  credentials: {
    accessKeyId: 'string'
    secretAccessKey: 'string'
  }
}
```

For **AccountKey**, use:

```bicep
{
  authType: 'AccountKey'
  credentials: {
    key: 'string'
  }
}
```

For **ApiKey**, use:

```bicep
{
  authType: 'ApiKey'
  credentials: {
    key: 'string'
  }
}
```

For **CustomKeys**, use:

```bicep
{
  authType: 'CustomKeys'
  credentials: {
    keys: {
      {customized property}: 'string'
    }
  }
}
```

For **ManagedIdentity**, use:

```bicep
{
  authType: 'ManagedIdentity'
  credentials: {
    clientId: 'string'
    resourceId: 'string'
  }
}
```

For **None**, use:

```bicep
{
  authType: 'None'
}
```

For **OAuth2**, use:

```bicep
{
  authType: 'OAuth2'
  credentials: {
    authUrl: 'string'
    clientId: 'string'
    clientSecret: 'string'
    developerToken: 'string'
    password: 'string'
    refreshToken: 'string'
    tenantId: 'string'
    username: 'string'
  }
}
```

For **PAT**, use:

```bicep
{
  authType: 'PAT'
  credentials: {
    pat: 'string'
  }
}
```

For **SAS**, use:

```bicep
{
  authType: 'SAS'
  credentials: {
    sas: 'string'
  }
}
```

For **ServicePrincipal**, use:

```bicep
{
  authType: 'ServicePrincipal'
  credentials: {
    clientId: 'string'
    clientSecret: 'string'
    tenantId: 'string'
  }
}
```

For **UsernamePassword**, use:

```bicep
{
  authType: 'UsernamePassword'
  credentials: {
    password: 'string'
    securityToken: 'string'
    username: 'string'
  }
}
```

## Property Values

### Microsoft.CognitiveServices/accounts/projects/connections

| Name | Description | Value |
| --- | --- | --- |
| name | The resource name | string Constraints:Pattern = `^[a-zA-Z0-9][a-zA-Z0-9_-]{2,32}$` (required) |
| parent | In Bicep, you can specify the parent resource for a child resource. You only need to add this property when the child resource is declared outside of the parent resource.For more information, see [Child resource outside parent resource](/en-us/azure/azure-resource-manager/bicep/child-resource-name-type#outside-parent-resource). | Symbolic name for resource of type: [accounts/projects](../../../accounts/projects) |
| properties | Connection property base schema. | ConnectionPropertiesV2 (required) |

### AADAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AAD' (required) |

### AccessKeyAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AccessKey' (required) |
| credentials |  | ConnectionAccessKey |

### AccountKeyAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AccountKey' (required) |
| credentials | Account key object for connection credential. | ConnectionAccountKey |

### ApiKeyAuthConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ApiKey' (required) |
| credentials | Api key object for connection credential. | ConnectionApiKey |

### ConnectionAccessKey

| Name | Description | Value |
| --- | --- | --- |
| accessKeyId |  | string |
| secretAccessKey |  | string Constraints:Sensitive value. Pass in as a secure parameter. |

### ConnectionAccountKey

| Name | Description | Value |
| --- | --- | --- |
| key |  | string |

### ConnectionApiKey

| Name | Description | Value |
| --- | --- | --- |
| key |  | string |

### ConnectionManagedIdentity

| Name | Description | Value |
| --- | --- | --- |
| clientId |  | string |
| resourceId |  | string |

### ConnectionOAuth2

| Name | Description | Value |
| --- | --- | --- |
| authUrl | Required by Concur connection category | string |
| clientId | Client id in the format of UUID | string Constraints:Min length = 36Max length = 36Pattern = `^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$` |
| clientSecret |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| developerToken | Required by GoogleAdWords connection category | string Constraints:Sensitive value. Pass in as a secure parameter. |
| password |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| refreshToken | Required by GoogleBigQuery, GoogleAdWords, Hubspot, QuickBooks, Square, Xero, Zohowhere user needs to get RefreshToken offline | string Constraints:Sensitive value. Pass in as a secure parameter. |
| tenantId | Required by QuickBooks and Xero connection categories | string |
| username | Concur, ServiceNow auth server AccessToken grant type is 'Password'which requires UsernamePassword | string |

### ConnectionPersonalAccessToken

| Name | Description | Value |
| --- | --- | --- |
| pat |  | string Constraints:Sensitive value. Pass in as a secure parameter. |

### ConnectionPropertiesV2

| Name | Description | Value |
| --- | --- | --- |
| authType | Set to 'AAD' for type AADAuthTypeConnectionProperties. Set to 'AccessKey' for type AccessKeyAuthTypeConnectionProperties. Set to 'AccountKey' for type AccountKeyAuthTypeConnectionProperties. Set to 'ApiKey' for type ApiKeyAuthConnectionProperties. Set to 'CustomKeys' for type CustomKeysConnectionProperties. Set to 'ManagedIdentity' for type ManagedIdentityAuthTypeConnectionProperties. Set to 'None' for type NoneAuthTypeConnectionProperties. Set to 'OAuth2' for type OAuth2AuthTypeConnectionProperties. Set to 'PAT' for type PATAuthTypeConnectionProperties. Set to 'SAS' for type SASAuthTypeConnectionProperties. Set to 'ServicePrincipal' for type ServicePrincipalAuthTypeConnectionProperties. Set to 'UsernamePassword' for type UsernamePasswordAuthTypeConnectionProperties. | 'AAD''AccessKey''AccountKey''ApiKey''CustomKeys''ManagedIdentity''None''OAuth2''PAT''SAS''ServicePrincipal''UsernamePassword' (required) |
| category | Category of the connection | 'ADLSGen2''AIServices''AmazonMws''AmazonRdsForOracle''AmazonRdsForSqlServer''AmazonRedshift''AmazonS3Compatible''ApiKey''AzureBlob''AzureDatabricksDeltaLake''AzureDataExplorer''AzureMariaDb''AzureMySqlDb''AzureOneLake''AzureOpenAI''AzurePostgresDb''AzureSqlDb''AzureSqlMi''AzureSynapseAnalytics''AzureTableStorage''BingLLMSearch''Cassandra''CognitiveSearch''CognitiveService''Concur''ContainerRegistry''CosmosDb''CosmosDbMongoDbApi''Couchbase''CustomKeys''Db2''Drill''Dynamics''DynamicsAx''DynamicsCrm''Elasticsearch''Eloqua''FileServer''FtpServer''GenericContainerRegistry''GenericHttp''GenericRest''Git''GoogleAdWords''GoogleBigQuery''GoogleCloudStorage''Greenplum''Hbase''Hdfs''Hive''Hubspot''Impala''Informix''Jira''Magento''ManagedOnlineEndpoint''MariaDb''Marketo''MicrosoftAccess''MongoDbAtlas''MongoDbV2''MySql''Netezza''ODataRest''Odbc''Office365''OpenAI''Oracle''OracleCloudStorage''OracleServiceCloud''PayPal''Phoenix''Pinecone''PostgreSql''Presto''PythonFeed''QuickBooks''Redis''Responsys''S3''Salesforce''SalesforceMarketingCloud''SalesforceServiceCloud''SapBw''SapCloudForCustomer''SapEcc''SapHana''SapOpenHub''SapTable''Serp''Serverless''ServiceNow''Sftp''SharePointOnlineList''Shopify''Snowflake''Spark''SqlServer''Square''Sybase''Teradata''Vertica''WebTable''Xero''Zoho' |
| error |  | string |
| expiryTime |  | string |
| isSharedToAll |  | bool |
| metadata | Store user metadata for this connection | ConnectionPropertiesV2Metadata |
| peRequirement |  | 'NotApplicable''NotRequired''Required' |
| peStatus |  | 'Active''Inactive''NotApplicable' |
| sharedUserList |  | string[] |
| target |  | string |
| useWorkspaceManagedIdentity |  | bool |

### ConnectionPropertiesV2Metadata

| Name | Description | Value |
| --- | --- | --- |

### ConnectionServicePrincipal

| Name | Description | Value |
| --- | --- | --- |
| clientId |  | string |
| clientSecret |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| tenantId |  | string |

### ConnectionSharedAccessSignature

| Name | Description | Value |
| --- | --- | --- |
| sas |  | string |

### ConnectionUsernamePassword

| Name | Description | Value |
| --- | --- | --- |
| password |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| securityToken | Optional, required by connections like SalesForce for extra security in addition to UsernamePassword | string Constraints:Sensitive value. Pass in as a secure parameter. |
| username |  | string |

### CustomKeys

| Name | Description | Value |
| --- | --- | --- |
| keys | Dictionary of &lt;string&gt; | CustomKeys |

### CustomKeys

| Name | Description | Value |
| --- | --- | --- |

### CustomKeysConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'CustomKeys' (required) |
| credentials | Custom Keys credential object | CustomKeys |

### ManagedIdentityAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ManagedIdentity' (required) |
| credentials |  | ConnectionManagedIdentity |

### NoneAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'None' (required) |

### OAuth2AuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'OAuth2' (required) |
| credentials | ClientId and ClientSecret are required. Other properties are optionaldepending on each OAuth2 provider's implementation. | ConnectionOAuth2 |

### PATAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'PAT' (required) |
| credentials |  | ConnectionPersonalAccessToken |

### SASAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'SAS' (required) |
| credentials |  | ConnectionSharedAccessSignature |

### ServicePrincipalAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ServicePrincipal' (required) |
| credentials |  | ConnectionServicePrincipal |

### UsernamePasswordAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'UsernamePassword' (required) |
| credentials |  | ConnectionUsernamePassword |

::: zone-end

::: zone pivot="deployment-language-arm-template"

## ARM template resource definition

The accounts/projects/connections resource type can be deployed with operations that target:

- **Resource groups** - See [resource group deployment commands](/en-us/azure/azure-resource-manager/templates/deploy-to-resource-group) For a list of changed properties in each API version, see [change log](../../../change-log/accounts/projects/connections).

## Usage Examples

## Resource format

To create a Microsoft.CognitiveServices/accounts/projects/connections resource, add the following JSON to your template.

```json
{
  "type": "Microsoft.CognitiveServices/accounts/projects/connections",
  "apiVersion": "2025-04-01-preview",
  "name": "string",
  "properties": {
    "category": "string",
    "error": "string",
    "expiryTime": "string",
    "isSharedToAll": "bool",
    "metadata": {
      "{customized property}": "string"
    },
    "peRequirement": "string",
    "peStatus": "string",
    "sharedUserList": [ "string" ],
    "target": "string",
    "useWorkspaceManagedIdentity": "bool",
    "authType": "string"
    // For remaining properties, see ConnectionPropertiesV2 objects
  }
}
```

### ConnectionPropertiesV2 objects

Set the **authType** property to specify the type of object.

For **AAD**, use:

```json
{
  "authType": "AAD"
}
```

For **AccessKey**, use:

```json
{
  "authType": "AccessKey",
  "credentials": {
    "accessKeyId": "string",
    "secretAccessKey": "string"
  }
}
```

For **AccountKey**, use:

```json
{
  "authType": "AccountKey",
  "credentials": {
    "key": "string"
  }
}
```

For **ApiKey**, use:

```json
{
  "authType": "ApiKey",
  "credentials": {
    "key": "string"
  }
}
```

For **CustomKeys**, use:

```json
{
  "authType": "CustomKeys",
  "credentials": {
    "keys": {
      "{customized property}": "string"
    }
  }
}
```

For **ManagedIdentity**, use:

```json
{
  "authType": "ManagedIdentity",
  "credentials": {
    "clientId": "string",
    "resourceId": "string"
  }
}
```

For **None**, use:

```json
{
  "authType": "None"
}
```

For **OAuth2**, use:

```json
{
  "authType": "OAuth2",
  "credentials": {
    "authUrl": "string",
    "clientId": "string",
    "clientSecret": "string",
    "developerToken": "string",
    "password": "string",
    "refreshToken": "string",
    "tenantId": "string",
    "username": "string"
  }
}
```

For **PAT**, use:

```json
{
  "authType": "PAT",
  "credentials": {
    "pat": "string"
  }
}
```

For **SAS**, use:

```json
{
  "authType": "SAS",
  "credentials": {
    "sas": "string"
  }
}
```

For **ServicePrincipal**, use:

```json
{
  "authType": "ServicePrincipal",
  "credentials": {
    "clientId": "string",
    "clientSecret": "string",
    "tenantId": "string"
  }
}
```

For **UsernamePassword**, use:

```json
{
  "authType": "UsernamePassword",
  "credentials": {
    "password": "string",
    "securityToken": "string",
    "username": "string"
  }
}
```

## Property Values

### Microsoft.CognitiveServices/accounts/projects/connections

| Name | Description | Value |
| --- | --- | --- |
| apiVersion | The api version | '2025-04-01-preview' |
| name | The resource name | string Constraints:Pattern = `^[a-zA-Z0-9][a-zA-Z0-9_-]{2,32}$` (required) |
| properties | Connection property base schema. | ConnectionPropertiesV2 (required) |
| type | The resource type | 'Microsoft.CognitiveServices/accounts/projects/connections' |

### AADAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AAD' (required) |

### AccessKeyAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AccessKey' (required) |
| credentials |  | ConnectionAccessKey |

### AccountKeyAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AccountKey' (required) |
| credentials | Account key object for connection credential. | ConnectionAccountKey |

### ApiKeyAuthConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ApiKey' (required) |
| credentials | Api key object for connection credential. | ConnectionApiKey |

### ConnectionAccessKey

| Name | Description | Value |
| --- | --- | --- |
| accessKeyId |  | string |
| secretAccessKey |  | string Constraints:Sensitive value. Pass in as a secure parameter. |

### ConnectionAccountKey

| Name | Description | Value |
| --- | --- | --- |
| key |  | string |

### ConnectionApiKey

| Name | Description | Value |
| --- | --- | --- |
| key |  | string |

### ConnectionManagedIdentity

| Name | Description | Value |
| --- | --- | --- |
| clientId |  | string |
| resourceId |  | string |

### ConnectionOAuth2

| Name | Description | Value |
| --- | --- | --- |
| authUrl | Required by Concur connection category | string |
| clientId | Client id in the format of UUID | string Constraints:Min length = 36Max length = 36Pattern = `^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$` |
| clientSecret |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| developerToken | Required by GoogleAdWords connection category | string Constraints:Sensitive value. Pass in as a secure parameter. |
| password |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| refreshToken | Required by GoogleBigQuery, GoogleAdWords, Hubspot, QuickBooks, Square, Xero, Zohowhere user needs to get RefreshToken offline | string Constraints:Sensitive value. Pass in as a secure parameter. |
| tenantId | Required by QuickBooks and Xero connection categories | string |
| username | Concur, ServiceNow auth server AccessToken grant type is 'Password'which requires UsernamePassword | string |

### ConnectionPersonalAccessToken

| Name | Description | Value |
| --- | --- | --- |
| pat |  | string Constraints:Sensitive value. Pass in as a secure parameter. |

### ConnectionPropertiesV2

| Name | Description | Value |
| --- | --- | --- |
| authType | Set to 'AAD' for type AADAuthTypeConnectionProperties. Set to 'AccessKey' for type AccessKeyAuthTypeConnectionProperties. Set to 'AccountKey' for type AccountKeyAuthTypeConnectionProperties. Set to 'ApiKey' for type ApiKeyAuthConnectionProperties. Set to 'CustomKeys' for type CustomKeysConnectionProperties. Set to 'ManagedIdentity' for type ManagedIdentityAuthTypeConnectionProperties. Set to 'None' for type NoneAuthTypeConnectionProperties. Set to 'OAuth2' for type OAuth2AuthTypeConnectionProperties. Set to 'PAT' for type PATAuthTypeConnectionProperties. Set to 'SAS' for type SASAuthTypeConnectionProperties. Set to 'ServicePrincipal' for type ServicePrincipalAuthTypeConnectionProperties. Set to 'UsernamePassword' for type UsernamePasswordAuthTypeConnectionProperties. | 'AAD''AccessKey''AccountKey''ApiKey''CustomKeys''ManagedIdentity''None''OAuth2''PAT''SAS''ServicePrincipal''UsernamePassword' (required) |
| category | Category of the connection | 'ADLSGen2''AIServices''AmazonMws''AmazonRdsForOracle''AmazonRdsForSqlServer''AmazonRedshift''AmazonS3Compatible''ApiKey''AzureBlob''AzureDatabricksDeltaLake''AzureDataExplorer''AzureMariaDb''AzureMySqlDb''AzureOneLake''AzureOpenAI''AzurePostgresDb''AzureSqlDb''AzureSqlMi''AzureSynapseAnalytics''AzureTableStorage''BingLLMSearch''Cassandra''CognitiveSearch''CognitiveService''Concur''ContainerRegistry''CosmosDb''CosmosDbMongoDbApi''Couchbase''CustomKeys''Db2''Drill''Dynamics''DynamicsAx''DynamicsCrm''Elasticsearch''Eloqua''FileServer''FtpServer''GenericContainerRegistry''GenericHttp''GenericRest''Git''GoogleAdWords''GoogleBigQuery''GoogleCloudStorage''Greenplum''Hbase''Hdfs''Hive''Hubspot''Impala''Informix''Jira''Magento''ManagedOnlineEndpoint''MariaDb''Marketo''MicrosoftAccess''MongoDbAtlas''MongoDbV2''MySql''Netezza''ODataRest''Odbc''Office365''OpenAI''Oracle''OracleCloudStorage''OracleServiceCloud''PayPal''Phoenix''Pinecone''PostgreSql''Presto''PythonFeed''QuickBooks''Redis''Responsys''S3''Salesforce''SalesforceMarketingCloud''SalesforceServiceCloud''SapBw''SapCloudForCustomer''SapEcc''SapHana''SapOpenHub''SapTable''Serp''Serverless''ServiceNow''Sftp''SharePointOnlineList''Shopify''Snowflake''Spark''SqlServer''Square''Sybase''Teradata''Vertica''WebTable''Xero''Zoho' |
| error |  | string |
| expiryTime |  | string |
| isSharedToAll |  | bool |
| metadata | Store user metadata for this connection | ConnectionPropertiesV2Metadata |
| peRequirement |  | 'NotApplicable''NotRequired''Required' |
| peStatus |  | 'Active''Inactive''NotApplicable' |
| sharedUserList |  | string[] |
| target |  | string |
| useWorkspaceManagedIdentity |  | bool |

### ConnectionPropertiesV2Metadata

| Name | Description | Value |
| --- | --- | --- |

### ConnectionServicePrincipal

| Name | Description | Value |
| --- | --- | --- |
| clientId |  | string |
| clientSecret |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| tenantId |  | string |

### ConnectionSharedAccessSignature

| Name | Description | Value |
| --- | --- | --- |
| sas |  | string |

### ConnectionUsernamePassword

| Name | Description | Value |
| --- | --- | --- |
| password |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| securityToken | Optional, required by connections like SalesForce for extra security in addition to UsernamePassword | string Constraints:Sensitive value. Pass in as a secure parameter. |
| username |  | string |

### CustomKeys

| Name | Description | Value |
| --- | --- | --- |
| keys | Dictionary of &lt;string&gt; | CustomKeys |

### CustomKeys

| Name | Description | Value |
| --- | --- | --- |

### CustomKeysConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'CustomKeys' (required) |
| credentials | Custom Keys credential object | CustomKeys |

### ManagedIdentityAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ManagedIdentity' (required) |
| credentials |  | ConnectionManagedIdentity |

### NoneAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'None' (required) |

### OAuth2AuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'OAuth2' (required) |
| credentials | ClientId and ClientSecret are required. Other properties are optionaldepending on each OAuth2 provider's implementation. | ConnectionOAuth2 |

### PATAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'PAT' (required) |
| credentials |  | ConnectionPersonalAccessToken |

### SASAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'SAS' (required) |
| credentials |  | ConnectionSharedAccessSignature |

### ServicePrincipalAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ServicePrincipal' (required) |
| credentials |  | ConnectionServicePrincipal |

### UsernamePasswordAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'UsernamePassword' (required) |
| credentials |  | ConnectionUsernamePassword |

::: zone-end

::: zone pivot="deployment-language-terraform"

## Terraform (AzAPI provider) resource definition

The accounts/projects/connections resource type can be deployed with operations that target:

- **Resource groups** For a list of changed properties in each API version, see [change log](../../../change-log/accounts/projects/connections).

## Resource format

To create a Microsoft.CognitiveServices/accounts/projects/connections resource, add the following Terraform to your template.

```terraform
resource "azapi_resource" "symbolicname" {
  type = "Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview"
  name = "string"
  parent_id = "string"
  body = {
    properties = {
      category = "string"
      error = "string"
      expiryTime = "string"
      isSharedToAll = bool
      metadata = {
        {customized property} = "string"
      }
      peRequirement = "string"
      peStatus = "string"
      sharedUserList = [
        "string"
      ]
      target = "string"
      useWorkspaceManagedIdentity = bool
      authType = "string"
      // For remaining properties, see ConnectionPropertiesV2 objects
    }
  }
}
```

### ConnectionPropertiesV2 objects

Set the **authType** property to specify the type of object.

For **AAD**, use:

```terraform
{
  authType = "AAD"
}
```

For **AccessKey**, use:

```terraform
{
  authType = "AccessKey"
  credentials = {
    accessKeyId = "string"
    secretAccessKey = "string"
  }
}
```

For **AccountKey**, use:

```terraform
{
  authType = "AccountKey"
  credentials = {
    key = "string"
  }
}
```

For **ApiKey**, use:

```terraform
{
  authType = "ApiKey"
  credentials = {
    key = "string"
  }
}
```

For **CustomKeys**, use:

```terraform
{
  authType = "CustomKeys"
  credentials = {
    keys = {
      {customized property} = "string"
    }
  }
}
```

For **ManagedIdentity**, use:

```terraform
{
  authType = "ManagedIdentity"
  credentials = {
    clientId = "string"
    resourceId = "string"
  }
}
```

For **None**, use:

```terraform
{
  authType = "None"
}
```

For **OAuth2**, use:

```terraform
{
  authType = "OAuth2"
  credentials = {
    authUrl = "string"
    clientId = "string"
    clientSecret = "string"
    developerToken = "string"
    password = "string"
    refreshToken = "string"
    tenantId = "string"
    username = "string"
  }
}
```

For **PAT**, use:

```terraform
{
  authType = "PAT"
  credentials = {
    pat = "string"
  }
}
```

For **SAS**, use:

```terraform
{
  authType = "SAS"
  credentials = {
    sas = "string"
  }
}
```

For **ServicePrincipal**, use:

```terraform
{
  authType = "ServicePrincipal"
  credentials = {
    clientId = "string"
    clientSecret = "string"
    tenantId = "string"
  }
}
```

For **UsernamePassword**, use:

```terraform
{
  authType = "UsernamePassword"
  credentials = {
    password = "string"
    securityToken = "string"
    username = "string"
  }
}
```

## Property Values

### Microsoft.CognitiveServices/accounts/projects/connections

| Name | Description | Value |
| --- | --- | --- |
| name | The resource name | string Constraints:Pattern = `^[a-zA-Z0-9][a-zA-Z0-9_-]{2,32}$` (required) |
| parent\_id | The ID of the resource that is the parent for this resource. | ID for resource of type: [accounts/projects](../../../accounts/projects) |
| properties | Connection property base schema. | ConnectionPropertiesV2 (required) |
| type | The resource type | "Microsoft.CognitiveServices/accounts/projects/connections@2025-04-01-preview" |

### AADAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AAD' (required) |

### AccessKeyAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AccessKey' (required) |
| credentials |  | ConnectionAccessKey |

### AccountKeyAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'AccountKey' (required) |
| credentials | Account key object for connection credential. | ConnectionAccountKey |

### ApiKeyAuthConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ApiKey' (required) |
| credentials | Api key object for connection credential. | ConnectionApiKey |

### ConnectionAccessKey

| Name | Description | Value |
| --- | --- | --- |
| accessKeyId |  | string |
| secretAccessKey |  | string Constraints:Sensitive value. Pass in as a secure parameter. |

### ConnectionAccountKey

| Name | Description | Value |
| --- | --- | --- |
| key |  | string |

### ConnectionApiKey

| Name | Description | Value |
| --- | --- | --- |
| key |  | string |

### ConnectionManagedIdentity

| Name | Description | Value |
| --- | --- | --- |
| clientId |  | string |
| resourceId |  | string |

### ConnectionOAuth2

| Name | Description | Value |
| --- | --- | --- |
| authUrl | Required by Concur connection category | string |
| clientId | Client id in the format of UUID | string Constraints:Min length = 36Max length = 36Pattern = `^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$` |
| clientSecret |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| developerToken | Required by GoogleAdWords connection category | string Constraints:Sensitive value. Pass in as a secure parameter. |
| password |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| refreshToken | Required by GoogleBigQuery, GoogleAdWords, Hubspot, QuickBooks, Square, Xero, Zohowhere user needs to get RefreshToken offline | string Constraints:Sensitive value. Pass in as a secure parameter. |
| tenantId | Required by QuickBooks and Xero connection categories | string |
| username | Concur, ServiceNow auth server AccessToken grant type is 'Password'which requires UsernamePassword | string |

### ConnectionPersonalAccessToken

| Name | Description | Value |
| --- | --- | --- |
| pat |  | string Constraints:Sensitive value. Pass in as a secure parameter. |

### ConnectionPropertiesV2

| Name | Description | Value |
| --- | --- | --- |
| authType | Set to 'AAD' for type AADAuthTypeConnectionProperties. Set to 'AccessKey' for type AccessKeyAuthTypeConnectionProperties. Set to 'AccountKey' for type AccountKeyAuthTypeConnectionProperties. Set to 'ApiKey' for type ApiKeyAuthConnectionProperties. Set to 'CustomKeys' for type CustomKeysConnectionProperties. Set to 'ManagedIdentity' for type ManagedIdentityAuthTypeConnectionProperties. Set to 'None' for type NoneAuthTypeConnectionProperties. Set to 'OAuth2' for type OAuth2AuthTypeConnectionProperties. Set to 'PAT' for type PATAuthTypeConnectionProperties. Set to 'SAS' for type SASAuthTypeConnectionProperties. Set to 'ServicePrincipal' for type ServicePrincipalAuthTypeConnectionProperties. Set to 'UsernamePassword' for type UsernamePasswordAuthTypeConnectionProperties. | 'AAD''AccessKey''AccountKey''ApiKey''CustomKeys''ManagedIdentity''None''OAuth2''PAT''SAS''ServicePrincipal''UsernamePassword' (required) |
| category | Category of the connection | 'ADLSGen2''AIServices''AmazonMws''AmazonRdsForOracle''AmazonRdsForSqlServer''AmazonRedshift''AmazonS3Compatible''ApiKey''AzureBlob''AzureDatabricksDeltaLake''AzureDataExplorer''AzureMariaDb''AzureMySqlDb''AzureOneLake''AzureOpenAI''AzurePostgresDb''AzureSqlDb''AzureSqlMi''AzureSynapseAnalytics''AzureTableStorage''BingLLMSearch''Cassandra''CognitiveSearch''CognitiveService''Concur''ContainerRegistry''CosmosDb''CosmosDbMongoDbApi''Couchbase''CustomKeys''Db2''Drill''Dynamics''DynamicsAx''DynamicsCrm''Elasticsearch''Eloqua''FileServer''FtpServer''GenericContainerRegistry''GenericHttp''GenericRest''Git''GoogleAdWords''GoogleBigQuery''GoogleCloudStorage''Greenplum''Hbase''Hdfs''Hive''Hubspot''Impala''Informix''Jira''Magento''ManagedOnlineEndpoint''MariaDb''Marketo''MicrosoftAccess''MongoDbAtlas''MongoDbV2''MySql''Netezza''ODataRest''Odbc''Office365''OpenAI''Oracle''OracleCloudStorage''OracleServiceCloud''PayPal''Phoenix''Pinecone''PostgreSql''Presto''PythonFeed''QuickBooks''Redis''Responsys''S3''Salesforce''SalesforceMarketingCloud''SalesforceServiceCloud''SapBw''SapCloudForCustomer''SapEcc''SapHana''SapOpenHub''SapTable''Serp''Serverless''ServiceNow''Sftp''SharePointOnlineList''Shopify''Snowflake''Spark''SqlServer''Square''Sybase''Teradata''Vertica''WebTable''Xero''Zoho' |
| error |  | string |
| expiryTime |  | string |
| isSharedToAll |  | bool |
| metadata | Store user metadata for this connection | ConnectionPropertiesV2Metadata |
| peRequirement |  | 'NotApplicable''NotRequired''Required' |
| peStatus |  | 'Active''Inactive''NotApplicable' |
| sharedUserList |  | string[] |
| target |  | string |
| useWorkspaceManagedIdentity |  | bool |

### ConnectionPropertiesV2Metadata

| Name | Description | Value |
| --- | --- | --- |

### ConnectionServicePrincipal

| Name | Description | Value |
| --- | --- | --- |
| clientId |  | string |
| clientSecret |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| tenantId |  | string |

### ConnectionSharedAccessSignature

| Name | Description | Value |
| --- | --- | --- |
| sas |  | string |

### ConnectionUsernamePassword

| Name | Description | Value |
| --- | --- | --- |
| password |  | string Constraints:Sensitive value. Pass in as a secure parameter. |
| securityToken | Optional, required by connections like SalesForce for extra security in addition to UsernamePassword | string Constraints:Sensitive value. Pass in as a secure parameter. |
| username |  | string |

### CustomKeys

| Name | Description | Value |
| --- | --- | --- |
| keys | Dictionary of &lt;string&gt; | CustomKeys |

### CustomKeys

| Name | Description | Value |
| --- | --- | --- |

### CustomKeysConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'CustomKeys' (required) |
| credentials | Custom Keys credential object | CustomKeys |

### ManagedIdentityAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ManagedIdentity' (required) |
| credentials |  | ConnectionManagedIdentity |

### NoneAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'None' (required) |

### OAuth2AuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'OAuth2' (required) |
| credentials | ClientId and ClientSecret are required. Other properties are optionaldepending on each OAuth2 provider's implementation. | ConnectionOAuth2 |

### PATAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'PAT' (required) |
| credentials |  | ConnectionPersonalAccessToken |

### SASAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'SAS' (required) |
| credentials |  | ConnectionSharedAccessSignature |

### ServicePrincipalAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'ServicePrincipal' (required) |
| credentials |  | ConnectionServicePrincipal |

### UsernamePasswordAuthTypeConnectionProperties

| Name | Description | Value |
| --- | --- | --- |
| authType | Authentication type of the connection target | 'UsernamePassword' (required) |
| credentials |  | ConnectionUsernamePassword |

::: zone-end
