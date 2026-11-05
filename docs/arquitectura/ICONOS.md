# Iconos del diagrama multinube

El diagrama usa **solo** cuatro juegos oficiales:

- **Azure Architecture Icons, versión V24** (Microsoft), para todos los servicios de Azure y para el
  logotipo de Microsoft Azure del recuadro «Qué cambia en cada pilar».
- **Microsoft Entra architecture icons, octubre de 2023** (Microsoft), solo para Microsoft Entra ID y el
  límite del tenant, que no están en el juego de Azure.
- **AWS Architecture Icons, paquete de julio de 2026** (`Icon-package_07312026`), solo para el logotipo de
  AWS del recuadro «Qué cambia en cada pilar».
- **Sign in with Google** (recursos de marca de Google Identity), solo para el botón de inicio de sesión de
  los comerciales y los revisores en el frontal web.

**Ningún juego se versiona en este repositorio.** Los iconos solo aparecen incrustados en los ficheros del
diagrama: `arquitectura.*.svg`, `arquitectura.*.html`, `arquitectura.drawio` y los PNG. El SHA-256 de cada
fichero usado está en la sección `iconos` de [arquitectura.json](arquitectura.json), y el generador falla si
el fichero del disco no coincide.

**El diagrama es documentación técnica, no marketing.** Los términos del juego de Microsoft Entra prohíben
usar sus iconos «in marketing communications».

## Juego de Azure (V24)

- Página de origen: <https://learn.microsoft.com/en-us/azure/architecture/icons/>.
- Fichero: `Azure_Public_Service_Icons_V24.zip` (1.033.184 bytes, SHA-256
  `921594ccd1bf3d9c0a1bd7b6d924e050551a59342f2b353bb74bdcf761c35141`), descomprimido en
  `~/Developer/demos/_iconos-azure/V24/`.

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

El `Azure_Icons_FAQ.pdf` del ZIP añade: «the full name of the service should always appear near the icon,
but not so close that it looks like it's overlapping the icon» y «Azure icons may only be used to represent
the Microsoft product that it was designed for».

## Juego de Microsoft Entra (octubre de 2023)

- Página de origen: <https://learn.microsoft.com/en-us/entra/architecture/architecture-icons>.
- Fichero: `Microsoft Entra architecture icons - Oct 2023.zip` (7.705.773 bytes, SHA-256
  `4e07536706a2d092e6524e5417e2c861333fdbdb41c36f78d44dfa07ccc5eedc`), descomprimido en
  `~/Developer/demos/_iconos-azure/entra/Oct2023/`.
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

## Juego de AWS (julio de 2026)

- Página de origen: <https://aws.amazon.com/architecture/icons/> (consultada el 04-11-2026). La página dice
  que los paquetes salen por trimestres y que no hay paquete en el cuarto: el de julio es el vigente.
- Fichero: `Icon-package_07312026.5846e92413caa21490223536cc97f1269e44fa92.zip` (13.988.918 bytes, SHA-256
  `d2d166c453526471749d520e0db022c459abef759d2946cf2dd1d1c992dc6526`), descomprimido en
  `~/Developer/demos/_iconos-aws/pkg/`.
- Icono usado: `Architecture-Group-Icons_07312026/AWS-Cloud-logo_32.svg` (SHA-256
  `63d73df1aac59dab323df732f82e196e359fb7b6370c0ca8e51e7b897cd350be`).

### Términos de uso (copia literal de la página del paquete)

El paquete no trae fichero de términos. La página publica estas frases:

```
We allow customers and partners to use these toolkits and assets to create architecture diagrams.
You can also put icons in materials like whitepapers, presentations, data sheets, and posters.
Check that you're using up-to-date icons, because some libraries may contain legacy icon sets.
```

Las AWS Trademark Guidelines (<https://aws.amazon.com/trademark-guidelines/>, «Last Updated: July 17, 2026»)
se tienen en cuenta: el logotipo no sugiere patrocinio ni respaldo de AWS, no se combina con otras marcas, no
es más grande que el resto de elementos y no se retoca. El uso de las marcas de AWS y de Google en este
diagrama está autorizado por decisión del responsable de la preventa (04-11-2026), sin restricción adicional.

## Sign in with Google (recursos de marca, 15-04-2026)

- Página de origen: <https://developers.google.com/identity/branding-guidelines>, enlace «download brand
  icons» (`https://developers.google.com/static/identity/images/signin-assets.zip`), consultada el
  04-11-2026 (`estudio de AWS y Google (no publicado)` §6.C).
- Fichero: `signin-assets.zip` (855.303 bytes, SHA-256
  `ba884069e12093b06bcfd776915081254a7c95094b80d50be2c5dc6bac1c1da1`, 133 ficheros), descomprimido en
  `~/Developer/demos/_iconos-google/signin-2026-11-04/x/`.
- Icono usado: `Android + Web/PNG @2x/Light/Theme=Light, Show text=Yes, Shape=Pill, Platform=Android+Web@2x.png`
  (360×80 px, SHA-256 `86c7955ee72f3635dc4e1415ac6e10035ca0bb1319245c8e1b441ce1cb5f6981`): el **botón
  completo, con su borde y su texto, tema claro sobre fondo blanco**.
- **Por qué el PNG y no el SVG:** los 24 SVG del paquete son exportaciones de Figma con `<foreignObject>`,
  `<div>` HTML y atributos `style` dentro (el degradado de la «G»). La lista blanca del generador los rechaza
  por seguridad, con razón. El PNG es el mismo botón oficial; se incrusta tal cual, en base64, sin
  retocarlo, y el generador comprueba que se dibuja en su proporción (alto/ancho = 80/360) y que ninguna
  imagen de las salidas apunta fuera del propio fichero.

### Términos de uso (copia literal de la página de normas de marca)

```
Your website or app must follow these guidelines to complete the app verification process.
Regardless of the text, you can't change the size or color of the Google "G" logo. It must be the standard color version ... and appear on a white background.
You can scale the button as needed for different devices and screen sizes, but you must preserve the aspect ratio so that the Google logo is not stretched.
Don't Use the Google icon or logo by itself without the button boundary and without text to indicate the user action.
Don't Use monochrome versions of the Google "G" for the button.
```

Cómo se cumplen: botón completo con borde y texto, versión en color, tema claro, escalado uniforme sin
deformar (comprobado por el generador) y nunca la «G» sola. El uso de las marcas de Google en el diagrama
está autorizado por decisión del responsable de la preventa (04-11-2026).

## Juegos revisados y no usados

- **Google Cloud** (<https://cloud.google.com/icons>, paquetes `category-icons`, `core-products-icons` y
  `google-cloud-legacy-icons`, en `~/Developer/demos/_iconos-google/`). **No trae el logotipo de Google
  Cloud** ni iconos para la documentación, el MCP de Developer Knowledge o la Cloud Billing Catalog API. El
  de Billing solo está en el juego legado, y la guía del paquete dice: «Legacy Google Cloud console product
  icons ... Please note, these icons should not be used as of 2026.» La página no publica términos de
  licencia; solo: «Welcome to the official library for Google Cloud product icons. Here you can find the
  Google Cloud product icons you need for your diagrams, technical documentation, and more.» Por eso el
  pilar de Google Cloud va con forma neutra.
- **Microsoft 365 architecture icons**
  (<https://learn.microsoft.com/en-us/microsoft-365/solutions/architecture-icons-templates>, consultada el
  04-11-2026). Descargado del enlace «Download SVG icons» de esa página
  (`https://go.microsoft.com/fwlink/?linkid=869455`, que redirige a
  `download.microsoft.com/.../2024-microsoft-365-content-icons.zip`) en
  `~/Developer/demos/_iconos-m365/zip/`: 712.812 bytes, SHA-256
  `522c4d43cf98a00380b0836f9ec6e06d81fb99758b258c49b6e5f385c05c547a`, 1.026 entradas. Términos, literal:
  «Microsoft permits the use of these icons in architectural diagrams, training materials, or
  documentation. You may copy, distribute, and display the icons only for the permitted use unless granted
  explicit permission by Microsoft. Microsoft reserves all other rights.» También se revisaron las plantillas
  y galerías de Visio del enlace «Download Visio templates and stencils» de la misma página
  (`https://go.microsoft.com/fwlink/?linkid=2056186` →
  `2024-microsoft-365-content-VisioTemplates.zip`, SHA-256
  `5ed0a9938b0e286656d3db7fa3f57a24f8579f6229a1a576df7d5f900826ef22`, en la misma carpeta). **Ninguno de los
  dos trae el logotipo de Microsoft Teams**: solo iconos de contenido (glifos como «Chat», «Bot», «People
  Team», «Settings» o «Tap» con la paleta de cada producto). Usar el glifo «Chat» como si fuera Teams sería
  representar un producto con el icono de otra cosa. Desde el 04-11-2026 la entrada de los comerciales es un
  frontal web propio y Microsoft Teams ya no aparece en el diagrama: este juego no se usa.

## Cómo se respetan

- **Sin recortar, voltear, rotar, distorsionar ni cambiar colores.** El generador comprueba el SHA-256 de
  cada icono antes de usarlo y lo incrusta intacto dentro de un `<svg>` envoltorio con el mismo `viewBox`
  cuadrado: la única transformación es un escalado uniforme y una traslación. El botón de Google (PNG) va en
  un `<image>` con los bytes originales en base64 y su proporción comprobada.
- **Lista blanca de elementos.** Solo se admiten iconos con elementos de dibujo (`path`, `rect`,
  gradientes, `clipPath`…); un `<script>`, `<style>`, `<image>`, atributo `style=`, manejador `on*` o
  referencia externa hacen fallar la generación.
- **Id renombrados de forma consistente.** Un icono repetido (Foundry Agent Service sale tres veces) lleva
  un prefijo propio en sus `id` y en sus referencias `url(#…)`; el generador comprueba que quitar el prefijo
  devuelve el original byte a byte. En el `.drawio` cada icono va con sus bytes originales.
- **Nombre completo junto a cada icono**, en la etiqueta del nodo o en la cabecera de su grupo. La sección
  `nombre_servicio` de [arquitectura.json](arquitectura.json) fija el nombre de cada icono y el generador
  falla si no aparece junto a él.
- **Cada icono representa el producto para el que se diseñó.** El logotipo de AWS solo aparece junto a
  «AWS»; el de Azure, junto a «Microsoft Azure». Los expertos de los tres pilares son agentes de Foundry y
  llevan el icono de Foundry Agent Service, nunca uno de AWS o de Google: el experto es nuestro, no un
  producto de esas nubes.
- **Terceros y piezas sin icono, con forma neutra y nombre completo:** Google Cloud
  («GC», sin logotipo oficial verificado), GitHub Actions («CI/CD») y azd y Bicep («IaC»).

## Iconos usados

Rutas relativas a la carpeta `Icons/` del ZIP de Azure, a la raíz del ZIP de Microsoft Entra, a la raíz
del paquete de AWS o a la carpeta descomprimida de Sign in with Google. El SHA-256 de cada fichero está en `iconos` de [arquitectura.json](arquitectura.json).

| Componente del diagrama | Juego | Icono (ruta) |
|---|---|---|
| Límite del tenant y Microsoft Entra ID | Entra oct. 2023 | `Microsoft Entra color icons SVG/Microsoft Entra ID color icon.svg` |
| Límite de la suscripción | Azure V24 | `general/10002-icon-service-Subscriptions.svg` |
| Límite del grupo de recursos del pilar | Azure V24 | `general/10007-icon-service-Resource-Groups.svg` |
| Límite de la red privada del pilar | Azure V24 | `networking/10061-icon-service-Virtual-Networks.svg` |
| Microsoft Foundry (cabecera del recurso y proyecto) | Azure V24 | `ai + machine learning/035746832-icon-service-AI-Foundry.svg` |
| Coordinador, experto del pilar y verificador | Azure V24 | `ai + machine learning/038470523-icon-service-Foundry-Agent-Service.svg` |
| Foundry Models | Azure V24 | `ai + machine learning/038470614-icon-service-Foundry-Models.svg` |
| Guardarraíles de Foundry con Prompt Shields | Azure V24 | `ai + machine learning/03390-icon-service-Content-Safety.svg` |
| Azure AI Search | Azure V24 | `ai + machine learning/10044-icon-service-Cognitive-Search.svg` |
| Azure Storage | Azure V24 | `storage/10086-icon-service-Storage-Accounts.svg` |
| Azure Cosmos DB | Azure V24 | `databases/10121-icon-service-Azure-Cosmos-DB.svg` |
| Azure Key Vault | Azure V24 | `security/10245-icon-service-Key-Vaults.svg` |
| Azure Container Registry | Azure V24 | `containers/10105-icon-service-Container-Registries.svg` |
| Application Insights | Azure V24 | `monitor/00012-icon-service-Application-Insights.svg` |
| Log Analytics | Azure V24 | `monitor/00009-icon-service-Log-Analytics-Workspaces.svg` |
| Endpoints privados | Azure V24 | `other/02579-icon-service-Private-Endpoints.svg` |
| Frontal web de preventa (Azure Container Apps) | Azure V24 | `other/02989-icon-service-Container-Apps-Environments.svg` (el juego solo trae el icono del entorno) |
| Identidad administrada del frontal | Azure V24 | `identity/10227-icon-service-Entra-Managed-Identities.svg` |
| Cola y tabla del frontal (Azure Queue Storage) | Azure V24 | `general/10840-icon-service-Storage-Queue.svg` |
| Azure Front Door con política WAF | Azure V24 | `networking/10073-icon-service-Front-Door-and-CDN-Profiles.svg` |
| Azure Firewall | Azure V24 | `networking/10084-icon-service-Firewalls.svg` |
| Azure Policy | Azure V24 | `management + governance/10316-icon-service-Policy.svg` |
| Microsoft Defender for Cloud | Azure V24 | `security/10241-icon-service-Microsoft-Defender-for-Cloud.svg` |
| Microsoft Cost Management (presupuestos) | Azure V24 | `general/10793-icon-service-Cost-Budgets.svg` |
| Acceso condicional | Azure V24 | `security/10233-icon-service-Conditional-Access.svg` |
| Privileged Identity Management | Azure V24 | `identity/02251-icon-service-Entra-Privleged-Identity-Management.svg` (errata del fichero) |
| Revisión humana y comerciales | Azure V24 | `identity/10230-icon-service-Users.svg` |
| Logotipo de Microsoft Azure | Azure V24 | `other/10018-icon-service-Azure-A.svg` |
| Logotipo de AWS | AWS jul. 2026 | `Architecture-Group-Icons_07312026/AWS-Cloud-logo_32.svg` |
| Botón Sign in with Google | Sign in with Google 2026 | `Android + Web/PNG @2x/Light/Theme=Light, Show text=Yes, Shape=Pill, Platform=Android+Web@2x.png` |
| Google Cloud, GitHub Actions, azd y Bicep | — | Forma neutra con texto |
| Límite de la región | — | Solo el rótulo |

## La marca verde de Azure AI Content Safety

El icono oficial de Azure AI Content Safety trae de serie una marca verde que no se puede quitar sin
alterarlo. El sello «Validado en Azure» del diagrama es distinto (disco verde oscuro con aro) y la leyenda
aclara que la marca del icono no significa validado.
