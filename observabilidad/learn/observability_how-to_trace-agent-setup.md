# Set up tracing in Microsoft Foundry

Important

Items marked preview in this article are currently in preview. This preview is provided without a service-level agreement, and Microsoft doesn't recommend it for production workloads. Certain features might not be supported or might have constrained capabilities. For more information, see [Supplemental Terms of Use for Microsoft Azure Previews](https://azure.microsoft.com/support/legal/preview-supplemental-terms/).

Note

Tracing is generally available for prompt and hosted agents. Workflow and external agents are in preview.

Use tracing to debug your AI agents and monitor their behavior in production. Tracing captures detailed telemetry - including latency, exceptions, prompt content, and retrieval operations - so you can identify and fix issues faster.

The recommended starting point is **server-side tracing**. Foundry enables it automatically after you connect an Application Insights resource to your project. No code changes are required, and traces are available within minutes of enabling it. Server-side tracing works for any agent hosted in Foundry. When you need visibility into your own application code - for example, to trace custom logic surrounding an agent call - you can add client-side instrumentation as a second step.

The [Microsoft Foundry Skill](../../how-to/develop/use-microsoft-foundry-skill) can help choose server-side or client-side tracing and troubleshoot missing telemetry.

## Prerequisites

- A [Foundry project](../../how-to/create-projects).
- An [Azure Monitor Application Insights resource](/en-us/azure/azure-monitor/app/app-insights-overview) to store traces (create a new one or connect an existing one).
- Access to the Application Insights resource connected to your project.
- The [Log Analytics Reader role](/en-us/azure/azure-monitor/logs/manage-access?tabs=portal#log-analytics-reader) on the connected Application Insights resource (required to query telemetry). If the underlying Log Analytics tables are [protected](/en-us/azure/azure-monitor/logs/protected-tables-configure), also assign the [Privileged Monitoring Data Reader role](/en-us/azure/azure-monitor/logs/manage-access?tabs=portal#privileged-monitoring-data-reader).

## Connect Application Insights to your Foundry project

Foundry stores traces in [Application Insights](/en-us/azure/azure-monitor/app/app-insights-overview) by using [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

1. Sign in to [Microsoft Foundry](https://ai.azure.com/?cid=learnDocs). Make sure the **New Foundry** toggle is on. These steps refer to **Foundry (new)**.

    ![](../../media/version-banner/new-foundry.png)
2. Open your Foundry project.
3. In the left navigation, select **Agents**.
4. At the top, select **Traces**.
5. On the right, select **Connect** to create or connect an Application Insights resource.

    [![Screenshot of the Agents tab showing traces and the connect button.](../../media/observability/tracing/traces-connect.png)](../../media/observability/tracing/traces-connect.png#lightbox)

- To connect an existing resource, select the resource, and then select **Connect**.
- To create a new resource, select **Create new**, and then complete the wizard.

A confirmation message appears when the connection succeeds.

### Use the project details connection path

If you don't see the message bar or **Connect** button, use this alternative way to enable Azure Monitor Application Insights.

1. Select **Manage** in the upper-right navigation, and then select **Project details**. [![Screenshot of the Manage section with the Project details option highlighted.](../../media/observability/tracing/project-details.png)](../../media/observability/tracing/project-details.png#lightbox)
2. Select the **Connected resources** tab, and then select **Add connection**. [![Screenshot of Project details with the Connected resources tab selected and the Add connection button highlighted.](../../media/observability/tracing/connected-resources-add-connection.png)](../../media/observability/tracing/connected-resources-add-connection.png#lightbox)
3. In **Choose a connection**, select **Application Insights**. [![Screenshot of Choose a connection with Application Insights highlighted.](../../media/observability/tracing/choose-connection.png)](../../media/observability/tracing/choose-connection.png#lightbox)

For Entra-authenticated trace ingestion, see [Configure Microsoft Entra authentication for Foundry Agent trace ingestion (preview)](trace-ingestion-entra-authentication).

After you connect the resource, your project is ready to use tracing.

Important

Make sure you have the permissions you need to query telemetry.

- For log-based queries, start by assigning the [Log Analytics Reader role](/en-us/azure/azure-monitor/logs/manage-access?tabs=portal#log-analytics-reader). If the underlying Log Analytics tables are [protected](/en-us/azure/azure-monitor/logs/protected-tables-configure), also assign the [Privileged Monitoring Data Reader role](/en-us/azure/azure-monitor/logs/manage-access?tabs=portal#privileged-monitoring-data-reader).
- To learn how to assign roles, see [Assign Azure roles using the Azure portal](/en-us/azure/role-based-access-control/role-assignments-portal).
- To manage access at scale, use [Microsoft Entra groups](../../concepts/rbac-foundry#use-microsoft-entra-groups-with-foundry).

## Instrument AI agents

Choose the approach that matches how you build and run your agent.

### Server-side traces in the Foundry portal

Start with server-side traces. Foundry logs traces for common agent and workflow scenarios without changing your code.

- Foundry automatically logs server-side traces for Prompt agents, Host agents, and workflows in the Foundry portal. After tracing is enabled in your Foundry project, you have access to out-of-the-box traces for the past 90 days.
- Foundry also supports easy [integration](trace-agent-framework) with top agent frameworks.

### Client-side traces with the Microsoft Foundry SDK

Install OpenTelemetry and the Azure SDK tracing plugin by using the following steps:

# [Python](#tab/python)
```bash
pip install azure-ai-projects azure-identity opentelemetry-sdk azure-core-tracing-opentelemetry
```

Reference: [azure-ai-projects](/en-us/python/api/overview/azure/ai-projects-readme), [azure-core-tracing-opentelemetry](/en-us/python/api/overview/azure/core-tracing-opentelemetry-readme)

# [C#](#tab/csharp)
```dotnetcli
dotnet add package Azure.AI.Projects
dotnet add package Azure.AI.Projects.Agents
dotnet add package Azure.Identity
dotnet add package Azure.Monitor.OpenTelemetry.Exporter
dotnet add package OpenTelemetry.Exporter.Console
```

Enable GenAI tracing before you create the project client or run agent operations:

```csharp
using Azure.AI.Projects;
using Azure.Identity;

AppContext.SetSwitch("Azure.Experimental.EnableGenAITracing", true);

var projectEndpoint = Environment.GetEnvironmentVariable(
   "FOUNDRY_PROJECT_ENDPOINT");
AIProjectClient projectClient = new(
   endpoint: new Uri(projectEndpoint!),
   tokenProvider: new DefaultAzureCredential());
```

Reference: [`AIProjectClient`](/en-us/dotnet/api/azure.ai.projects.aiprojectclient), [`DefaultAzureCredential`](/en-us/dotnet/api/azure.identity.defaultazurecredential)

---

Important

To use a project's endpoint in your application, you need to configure Microsoft Entra ID. If you don't configure Microsoft Entra ID, use the Application Insights connection string.

After running your agent, you can view and analyze traces in Foundry portal.

For end-to-end Python and .NET examples that export traces to Azure Monitor or the console, see [Configure client-side tracing](trace-agent-client-side).

### Trace locally with the Microsoft Foundry Toolkit for Visual Studio Code extension

The Microsoft Foundry Toolkit for Visual Studio Code extension lets you trace locally in VS Code by using a local OTLP-compatible collector. This approach is ideal for development and debugging.

The toolkit supports AI frameworks such as Foundry Agent Service, OpenAI, Anthropic, and LangChain through OpenTelemetry. You can see traces instantly in VS Code without needing cloud access.

For detailed setup instructions and SDK-specific code examples, see [Tracing in Foundry Toolkit](https://code.visualstudio.com/docs/intelligentapps/tracing).

## View and analyze traces

### View traces in the Foundry portal

In your Foundry project, go to the **Traces** tab in your agents or workflows. You can search, filter, or sort ingested traces from the last 90 days.

Select a trace to step through each span, identify problems, and observe how your application responds. This process helps you debug and pinpoint problems in your application.

### View traces in Azure Monitor

Your traces are sent to Azure Monitor Application Insights, so you can view them there.

For more information on how to send traces to Azure Monitor and create an Azure Monitor resource, see [Azure Monitor OpenTelemetry documentation](/en-us/azure/azure-monitor/app/opentelemetry-enable).

### View conversation results

A **Conversation** is the persistent context of an end-to-end dialogue history between a user and an agent. In the Foundry portal, you can view **Conversation** results for your agent run out of the box along with traces on the **Traces** page.

Search by Response ID or by a Trace ID that maps to this conversation. Then select a **Conversation ID** to review:

- Conversation history details
- Response information and tokens in a run
- Ordered actions, run steps, and tool calls
- Inputs and outputs between a user and an agent

[![Screenshot of the Conversation details pane in Foundry showing a conversation ID with a trace timeline and run-step details.](../../media/observability/tracing/conversation.png)](../../media/observability/tracing/conversation.png#lightbox)

## Verify tracing works

1. Confirm your project is connected to Application Insights. If needed, follow the steps in Connect Application Insights to your Foundry project.
2. Run your agent or workflow at least once (for example, by using the portal or your app).
3. In your Foundry project, open the **Traces** view and confirm a new trace appears.

    When tracing is working correctly, you see a list of recent traces with timestamps, durations, and status indicators. Select a trace to view its span details.

If you don't see new traces, wait a few minutes and refresh, and then see Troubleshooting.

## Security and privacy

Tracing can capture sensitive information, such as user inputs, model outputs, and tool arguments and results. Use these practices to reduce risk:

- Don't store secrets, credentials, or tokens in prompts, tool arguments, or span attributes.
- Redact or minimize personal data and other sensitive content before it appears in telemetry.
- Treat trace data as production telemetry and apply the same access controls and retention policies you use for logs and metrics.

For more guidance, see [Security and privacy](../concepts/trace-agent-concept#security-and-privacy).

## Data retention and cost

Foundry stores traces in the Application Insights resource connected to your project. Data retention and billing follow your Application Insights and Log Analytics configuration.

## Troubleshooting

| Issue | Cause | Resolution |
| --- | --- | --- |
| You don't see any traces in the Foundry portal | Tracing isn't connected, there is no recent traffic, or ingestion is delayed | Confirm the Application Insights connection, generate new agent traffic, and refresh after a few minutes. |
| You see authorization errors when you query or view telemetry | Missing RBAC permissions on Application Insights or Log Analytics | Confirm access in **Access control (IAM)** for the connected resources. For log queries, assign the [Log Analytics Reader role](/en-us/azure/azure-monitor/logs/manage-access?tabs=portal#log-analytics-reader). If the tables are [protected](/en-us/azure/azure-monitor/logs/protected-tables-configure), also assign [Privileged Monitoring Data Reader](/en-us/azure/azure-monitor/logs/manage-access?tabs=portal#privileged-monitoring-data-reader). |
| Client-side traces don't appear | Instrumentation isn't installed or configured | Recheck your package installation and follow the SDK guidance linked in Client-side traces with the Microsoft Foundry SDK. |
| Sensitive content appears in traces | Prompts, tool arguments, or outputs contain sensitive data | Redact sensitive data before it enters telemetry and follow the guidance in Security and privacy. |
