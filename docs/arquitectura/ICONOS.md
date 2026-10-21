# Iconos del diagrama

El diagrama usa **solo** dos juegos oficiales de Microsoft:

- **Azure Architecture Icons, versión V24.** Es la tanda de julio de 2026, la que añade Foundry Models,
  Foundry Projects y Foundry Agent Service.
- **Microsoft Entra architecture icons, octubre de 2023.** Se usa únicamente para Microsoft Entra ID, que
  no está en el juego de Azure.

**Ninguno de los dos juegos se versiona en este repositorio.** Los iconos solo aparecen incrustados en los
ficheros del diagrama: `arquitectura.*.svg`, `arquitectura.*.html`, `arquitectura.drawio` y los PNG.

**El diagrama es documentación técnica, no marketing.** Los términos del juego de Microsoft Entra
prohíben usar sus iconos «in marketing communications». Por eso el diagrama se presenta siempre como
arquitectura de referencia o documentación técnica.

## Juego de Azure (V24)

- Página de origen: <https://learn.microsoft.com/en-us/azure/architecture/icons/> (consultada el 18-10-2026).
- Fichero descargado: `Azure_Public_Service_Icons_V24.zip`, desde el enlace de esa misma página
  (`https://arch-center.azureedge.net/icons/Azure_Public_Service_Icons_V24.zip`), 1.033.184 bytes,
  SHA-256 `921594ccd1bf3d9c0a1bd7b6d924e050551a59342f2b353bb74bdcf761c35141`.

### Términos de uso (copia literal de la página)

```
Icon terms
Microsoft permits the use of these icons in architectural diagrams, training materials, or documentation. You can copy, distribute, and display the icons only for the permitted use unless granted explicit permission by Microsoft. Microsoft reserves all other rights.

General guidelines
Do's
Use the icon to illustrate how products can work together.
In diagrams, we recommend including the product name somewhere close to the icon.
Use the icons as they would appear within Azure.
Don'ts
Don't crop, flip, or rotate icons.
Don't distort or change icon shape in any way.
Don't use Microsoft product icons to represent your product or service.
```

El documento de preguntas frecuentes que viene dentro del ZIP (`Azure_Icons_FAQ.pdf`) añade dos reglas
que también se cumplen:

- «the full name of the service should always appear near the icon, but not so close that it looks like
  it's overlapping the icon».
- «Azure icons may only be used to represent the Microsoft product that it was designed for».

## Juego de Microsoft Entra (octubre de 2023)

- Página de origen: <https://learn.microsoft.com/en-us/entra/architecture/architecture-icons> (consultada
  el 18-10-2026; la página se actualizó por última vez el 23-10-2023).
- Fichero descargado: `Microsoft Entra architecture icons - Oct 2023.zip`, desde el enlace de esa página
  en `download.microsoft.com`, 7.705.773 bytes, SHA-256
  `4e07536706a2d092e6524e5417e2c861333fdbdb41c36f78d44dfa07ccc5eedc`.
- Icono usado: `Microsoft Entra color icons SVG/Microsoft Entra ID color icon.svg`.

### Términos de uso (copia literal de `Microsoft Terms of Use.docx`, dentro del ZIP)

```
Microsoft Entra Icons
Helping our customers design and architect new solutions is core to the Microsoft Entra mission. Architecture diagrams can help communicate design decisions and the relationships between components of a given workload. The official Microsoft Entra product icons are intended to help you build a custom architecture diagram for your next solution.
Do’s
Use the icon to illustrate how products can work together.
In diagrams, we recommend including the product name somewhere close to the icon.
Don’ts
Don’t crop, flip, or rotate icons.
Don’t distort or change icon shape in any way.
Don’t use Microsoft product icons to represent your product or service.
Don’t use Microsoft product icons in marketing communications.
Terms
Microsoft permits the use of these icons in architectural diagrams, training materials, or documentation. You may copy, distribute, and display the icons only for the permitted use unless granted explicit permission by Microsoft. Microsoft reserves all other rights.
```

## Cómo se respetan

- **Sin recortar, voltear, rotar, distorsionar ni cambiar colores.** El generador comprueba el SHA-256 de
  cada icono contra el de `arquitectura.json` antes de usarlo. Lo incrusta intacto dentro de un `<svg>`
  envoltorio con el mismo `viewBox` cuadrado: la única transformación es un escalado uniforme y una
  traslación.
- **Id renombrados de forma consistente.** Un icono que aparece varias veces (Foundry Agent Service
  aparece siete) lleva un prefijo propio en sus `id` y en sus referencias `url(#…)`, para que sus
  gradientes no choquen. El generador comprueba que quitar el prefijo devuelve el original byte a byte.
- En `arquitectura.drawio` cada icono va como imagen con los bytes originales, sin prefijos.
- **Nombre completo junto a cada icono**, sin tocarlo: en la etiqueta del nodo o en la cabecera de su
  grupo. El coordinador lleva «Foundry Agent Service» en su etiqueta; los seis especialistas, en la
  cabecera «Especialistas · Foundry Agent Service»; los dos modelos, en la cabecera «Modelos · Foundry
  Models». La sección `nombre_servicio` de [arquitectura.json](arquitectura.json) fija el nombre de cada
  icono, y el generador falla si ese nombre no aparece junto a cada icono que lo usa.
- **Cada icono representa el producto para el que se diseñó.** Donde no hay icono oficial no se inventan
  logotipos. Se usa una forma neutra con texto o, solo para dos servicios de Microsoft sin icono propio
  (el MCP de Microsoft Learn y Web Search), un icono genérico del propio juego (categoría `general`).
- **Terceros con forma neutra, sin excepciones.** OpenCode («CLI»), GitHub («Git»), GitHub Actions
  («CI/CD») y azd y Bicep («IaC») se dibujan con la misma forma neutra con texto. Ninguno lleva un icono
  de Microsoft ni su propio logotipo. El protocolo MCP solo aparece como texto.
- **Ningún icono se usa para representar este sistema.** Los iconos solo representan los servicios de
  Microsoft que el sistema usa.

## Iconos usados

Rutas relativas a la carpeta `Icons/` del ZIP de Azure, o a la carpeta raíz del ZIP de Microsoft Entra.
El SHA-256 de cada fichero está en la sección `iconos` de [arquitectura.json](arquitectura.json).

| Componente del diagrama | Juego | Icono (ruta en el ZIP) | Tipo |
|---|---|---|---|
| Microsoft Foundry (recurso) | Azure V24 | `ai + machine learning/035746832-icon-service-AI-Foundry.svg` | Producto |
| Proyecto de Foundry | Azure V24 | `ai + machine learning/036509415-icon-service-Foundry-Project.svg` | Producto |
| Coordinador y los seis especialistas | Azure V24 | `ai + machine learning/038470523-icon-service-Foundry-Agent-Service.svg` | Producto (Foundry Agent Service) |
| Microsoft-Decision-1 y modelos GPT-6 | Azure V24 | `ai + machine learning/038470614-icon-service-Foundry-Models.svg` | Producto (Foundry Models) |
| Foundry IQ | Azure V24 | `ai + machine learning/038470497-icon-service-Azure-AI-Foundry-IQ.svg` | Producto |
| Guardarraíles de Foundry con Prompt Shields | Azure V24 | `ai + machine learning/03390-icon-service-Content-Safety.svg` | Producto (Azure AI Content Safety; Learn: los guardarraíles usan sus modelos de clasificación) |
| Azure AI Search | Azure V24 | `ai + machine learning/10044-icon-service-Cognitive-Search.svg` | Producto (el fichero conserva el nombre antiguo) |
| Azure Storage | Azure V24 | `storage/10086-icon-service-Storage-Accounts.svg` | Producto |
| Azure Key Vault | Azure V24 | `security/10245-icon-service-Key-Vaults.svg` | Producto |
| Application Insights | Azure V24 | `monitor/00012-icon-service-Application-Insights.svg` | Producto |
| Área de trabajo de Log Analytics (Azure Monitor) | Azure V24 | `monitor/00009-icon-service-Log-Analytics-Workspaces.svg` | Producto |
| Microsoft Cost Management (presupuestos y alertas) | Azure V24 | `general/10793-icon-service-Cost-Budgets.svg` | Producto (Cost Management: presupuestos); el rótulo da el nombre completo del servicio |
| Límite del grupo de recursos | Azure V24 | `general/10007-icon-service-Resource-Groups.svg` | Producto (grupos de recursos) |
| Límite de la suscripción | Azure V24 | `general/10002-icon-service-Subscriptions.svg` | Producto (suscripciones) |
| Azure Bot Service (canal Teams, futuro) | Azure V24 | `ai + machine learning/10165-icon-service-Bot-Services.svg` | Producto |
| Arquitecto/a de soluciones | Azure V24 | `identity/10230-icon-service-Users.svg` | Usuario |
| Portal de Microsoft Foundry (playground) | Azure V24 | `ai + machine learning/035746832-icon-service-AI-Foundry.svg` | Producto (Microsoft Foundry, el mismo icono que el recurso) |
| MCP de Microsoft Learn | Azure V24 | `general/10816-icon-service-Learn.svg` | Genérico |
| Web Search | Azure V24 | `general/10834-icon-service-Search.svg` | Genérico |
| Límite del tenant y Microsoft Entra ID (identidad de agente, RBAC, OIDC) | Entra oct. 2023 | `Microsoft Entra color icons SVG/Microsoft Entra ID color icon.svg` | Producto (juego de Microsoft Entra) |
| OpenCode (cliente), GitHub, GitHub Actions, azd y Bicep | — | Forma neutra con texto («CLI», «Git», «CI/CD», «IaC») | Terceros o sin icono oficial |
| Azure Retail Prices API (OpenAPI) | — | Forma neutra con texto («API») | Sin icono oficial propio |
| Límite de la región de la UE | — | Solo el rótulo | Sin icono: ver la nota |

## Iconos descartados a propósito

Para respetar que cada icono solo represente su producto, estos no se usan:

- **Azure RBAC.** No tiene icono oficial. «Entra Identity Custom Roles» y «Entra Identity Roles and
  Administrators» representan los roles del directorio de Entra, no Azure RBAC. Se nombra en el texto del
  nodo de Microsoft Entra ID.
- **Región o Data Zone.** «Region Management» es un recurso del portal. El límite de región lleva solo
  su rótulo.
- **Tenant.** «Tenant Properties» es la hoja de propiedades del portal. El límite del tenant usa el icono
  de Microsoft Entra ID.
- **azd y Bicep.** No tienen icono oficial. «Templates» (plantillas ARM) y «Template Specs» son productos
  distintos.
- **Microsoft Entra Agent ID.** El juego de octubre de 2023 no trae icono. La identidad de cada agente
  se dibuja con el icono de Microsoft Entra ID y el rótulo «identidad de agente».
- **Foundry Control Plane.** Su SVG no trae `viewBox` y no se puede escalar sin alterarlo.
- **Identidades administradas.** Las identidades de agente no son identidades administradas.
- **Dev Console para OpenCode.** Es un icono de Microsoft y OpenCode es un producto de terceros: lleva la
  forma neutra «CLI», como el resto de terceros.
- **Management Portal para el portal de Foundry.** Representa el portal de Azure, no el de Foundry. El
  portal de Foundry lleva el icono de Microsoft Foundry y el rótulo «Portal de Microsoft Foundry».
- **Cost Management para la Azure Retail Prices API.** Learn documenta la API junto a Cost Management,
  pero no es ese producto. Se dibuja con una forma neutra rotulada «Azure Retail Prices API (OpenAPI)».

## La marca verde de Azure AI Content Safety

El icono oficial de Azure AI Content Safety trae de serie una marca verde. No se puede quitar sin
alterar el icono, así que se conserva. Para que no se confunda con «Validado en Azure», el sello de
validado del diagrama es distinto (disco verde oscuro con aro exterior) y la banda «Validado en Azure»
lo aclara: «Marca de Content Safety: parte de su icono».
