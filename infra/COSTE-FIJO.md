# Coste fijo mensual de la infraestructura (preventa multinube)

> Generado por `infra/coste_fijo.py` el **2026-11-04** con la Azure Retail Prices API
> (`https://prices.azure.com/api/retail/prices`, `currencyCode=EUR`, región `swedencentral`; los medidores globales usan `Global` o `Zone 1`).
> No editar a mano: se regenera con `python3 infra/coste_fijo.py`. Precios de lista, sin descuentos ni IVA.
> Mes = 730 h. Nada de esto está desplegado.

## Resumen

| Concepto | €/mes |
|---|---:|
| Un pilar | 247,12 € |
| Tres pilares (×3) | 741,36 € |
| Plataforma compartida sin Firewall | 296,24 € |
| Azure Firewall (hub compartido) | 822,41 € |
| **Total con Firewall** (diseño con Azure Firewall) | **1.860,01 €** |
| **Total sin Firewall** (variante `conFirewall=false`) | **1.037,60 €** |

La variante sin Firewall conserva la entrada privada y la red privada de los agentes, pero pierde el control de
salida por destino (RED-9): los agentes pueden llegar a cualquier FQDN público. Azure Firewall Basic no tiene
precio publicado en `swedencentral` en la API (solo «Basic Secured Virtual Hub»), por eso el diseño usa Standard.

## Por pilar (se repite ×3)

| Concepto | skuName | meterName | meterId | Precio unitario | Unidad | Supuesto | €/mes |
|---|---|---|---|---:|---|---|---:|
| Azure AI Search Basic (1 réplica, 1 partición) | Basic | Basic Unit | `0c873ca2-4113-4997-8cf6-ad5df5775599` | 0.0907 € | 1 Hour | 1 unidad × 730 h | 66,21 € |
| Azure Container Registry Premium (exigido por Private Link) | Premium | Premium Registry Unit | `2f8e1105-47d0-4105-a934-b2175c766a71` | 1.4961 € | 1/Day | 1 registro × 30,42 días | 45,51 € |
| Endpoints privados (Foundry, Storage, Search, Cosmos DB, Key Vault, ACR) | Standard | Standard Private Endpoint | `e6ab7238-e433-4fe0-a2b2-2b2564df2cdb` | 0.0090 € | 1 Hour | 6 endpoints × 730 h | 39,42 € |
| Zonas DNS privadas del pilar | Private | Private Zone | `0b608a26-f611-4232-8192-ce81b6b57194` | 0.4489 € | 1 | 8 zonas (24 en total, por debajo del tramo de 25) | 3,59 € |
| Container Apps: cargo de gestión por el endpoint privado del entorno | Dedicated | Dedicated Plan Management | `f2e51aaf-6c2e-5bdb-acdd-45ece8b2d2db` | 0.0898 € | 1 Hour | 1 entorno × 730 h (Learn: el endpoint privado activa este cargo) | 65,55 € |
| Log Analytics + Application Insights: ingesta supuesta | Analytics Logs | Analytics Logs Data Ingestion | `e3669cc9-19b6-55fc-b9fe-782ab83615ab` | 2.6841 € | 1 GB | 10 GB/mes supuestos, sin descontar los 5 GB gratuitos | 26,84 € |

Sin coste fijo en el pilar: Cosmos DB **serverless** (Learn, standard-agent-setup: «Both Provisioned Throughput
and Serverless modes are supported.»), Storage, Key Vault Standard, recurso y proyecto de Foundry, despliegues de
modelos (pago por token) y Container Apps con escala a cero.

## Plataforma compartida

| Concepto | skuName | meterName | meterId | Precio unitario | Unidad | Supuesto | €/mes |
|---|---|---|---|---:|---|---|---:|
| Azure Front Door Premium, cuota base (WAF incluido en Premium) | Premium | Premium Base Fees | `7c765472-0673-5e48-bcb0-5a7b34c6330d` | 296.2431 € | 1/Month | 1 perfil para los tres pilares | 296,24 € |

## Azure Firewall (opcional, `conFirewall`)

| Concepto | skuName | meterName | meterId | Precio unitario | Unidad | Supuesto | €/mes |
|---|---|---|---|---:|---|---|---:|
| Azure Firewall Standard (despliegue) | Standard | Standard Deployment | `e90604a4-719b-454b-879d-b85523882c92` | 1.1221 € | 1 Hour | 1 firewall × 730 h | 819,13 € |
| IP pública estándar estática del Firewall | Standard | Standard IPv4 Static Public IP | `9c150bf9-2bad-430e-a53c-c213804f49ef` | 0.0045 € | 1 Hour | 1 IP × 730 h | 3,28 € |

## Alternativa no incluida en el total

| Concepto | skuName | meterName | meterId | Precio unitario | Unidad | Supuesto | €/mes |
|---|---|---|---|---:|---|---|---:|
| Cosmos DB aprovisionado 3000 RU/s (en vez de serverless) | RUs | 100 RU/s | `980c96a2-0907-55c7-9f8d-641a757cc7bd` | 0.0072 € | 1/Hour | 30 × 100 RU/s × 730 h, por pilar | 157,68 € |

Si Cosmos DB serverless no sirve en la prueba real (por ejemplo, por el mínimo de 3000 RU/s que exige Learn al
límite de rendimiento de la cuenta), el aprovisionado añade 157,68 € por pilar y
473,04 € en total.

## Variable (fuera del coste fijo; solo se nombra)

- Tokens de `gpt-6-luna` y `gpt-5.6-luna` (DataZoneStandard): por uso, no hay cuota fija.
- Cosmos DB serverless: RU consumidas y almacenamiento.
- Storage (ZRS): capacidad, operaciones, versiones y borrado temporal retenido.
- Key Vault Standard: operaciones (no tiene cuota fija).
- Container Apps: vCPU, memoria y peticiones (frontal y backend escalan a cero; hay una franquicia mensual por suscripción).
- Front Door: peticiones y transferencia de datos; Firewall: datos procesados y unidades de capacidad.
- Endpoints privados: datos procesados; DNS privado: consultas; emparejamiento de VNet: GB transferidos.
- Log Analytics: ingesta por encima de la supuesta y retención por encima de 30 días.
- Microsoft Defender for Cloud (plan AI services) y Purview, si se activan: por uso y por suscripción.
- Recurso de Foundry, proyectos, identidades, Azure Policy y presupuestos: sin coste propio.

## Supuestos y límites del cálculo

- La franquicia gratuita de Log Analytics (5 GB/mes) y la de Container Apps no se descuentan: el cálculo es conservador.
- El cargo de gestión de Container Apps se aplica por el endpoint privado que crea Front Door (Learn, container-apps/billing:
  «features such as private endpoints and planned maintenance are subject to a Dedicated Plan Management charge
  regardless of whether you use the Consumption or Dedicated plans»). La API publica además un medidor «Environment
  Private Endpoint» con el mismo precio; si se facturan los dos, el pilar sube 65,55 € aprox. `[verificación pendiente]`.
- Las unidades de capacidad del Firewall Standard («Standard Capacity Unit») se tratan como variables `[verificación pendiente]`.
- La cuota base de Front Door Premium es por perfil, no por región; se toma el medidor de `Zone 1`. Las reglas
  administradas del WAF van incluidas en Premium (Learn, frontdoor/understanding-pricing: fila «Web Application
  Firewall managed rules», columna Premium «Free»); las peticiones son variables.
