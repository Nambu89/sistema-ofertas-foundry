#!/usr/bin/env python3
"""Coste fijo mensual de la infraestructura de la preventa multinube (infra/*.bicep).

Consulta la Azure Retail Prices API (sin autenticación, EUR) y regenera infra/COSTE-FIJO.md.
Código de salida = veredicto: 0 si todas las líneas tienen un precio único, finito y positivo; 1 si no
(y entonces NO reescribe el documento). `--prueba` ejecuta la autocomprobación sin red.
"""
import datetime
import json
import math
import pathlib
import sys
import urllib.parse
import urllib.request

API = "https://prices.azure.com/api/retail/prices"
REGION = "swedencentral"
HORAS_MES = 730  # convención de la calculadora de Azure
DIAS_MES = HORAS_MES / 24
PILARES = 3
CAMPOS = ("meterId", "retailPrice", "unitOfMeasure", "skuName", "meterName", "currencyCode", "tierMinimumUnits", "type")

# ambito: pilar (se multiplica por 3), plataforma, firewall (plataforma, opcional) o alternativa (fuera del total).
LINEAS = [
    dict(ambito="pilar", concepto="Azure AI Search Basic (1 réplica, 1 partición)",
         filtro=f"serviceName eq 'Azure Cognitive Search' and armRegionName eq '{REGION}' and skuName eq 'Basic' and meterName eq 'Basic Unit'",
         unidad="1 Hour", cantidad=1, factor=HORAS_MES, supuesto="1 unidad × 730 h"),
    dict(ambito="pilar", concepto="Azure Container Registry Premium (exigido por Private Link)",
         filtro=f"serviceName eq 'Container Registry' and armRegionName eq '{REGION}' and skuName eq 'Premium' and meterName eq 'Premium Registry Unit'",
         unidad="1/Day", cantidad=1, factor=DIAS_MES, supuesto="1 registro × 30,42 días"),
    dict(ambito="pilar", concepto="Endpoints privados (Foundry, Storage, Search, Cosmos DB, Key Vault, ACR)",
         filtro="serviceName eq 'Virtual Network' and productName eq 'Virtual Network Private Link' and meterName eq 'Standard Private Endpoint' and armRegionName eq 'Global'",
         unidad="1 Hour", cantidad=6, factor=HORAS_MES, supuesto="6 endpoints × 730 h"),
    dict(ambito="pilar", concepto="Zonas DNS privadas del pilar",
         filtro="serviceName eq 'Azure DNS' and meterName eq 'Private Zone' and armRegionName eq 'Zone 1'",
         tramo=0.0, unidad="1", cantidad=8, factor=1, supuesto="8 zonas (24 en total, por debajo del tramo de 25)"),
    dict(ambito="pilar", concepto="Container Apps: cargo de gestión por el endpoint privado del entorno",
         filtro=f"serviceName eq 'Azure Container Apps' and armRegionName eq '{REGION}' and meterName eq 'Dedicated Plan Management'",
         unidad="1 Hour", cantidad=1, factor=HORAS_MES, supuesto="1 entorno × 730 h (Learn: el endpoint privado activa este cargo)"),
    dict(ambito="pilar", concepto="Log Analytics + Application Insights: ingesta supuesta",
         filtro=f"serviceName eq 'Log Analytics' and armRegionName eq '{REGION}' and meterName eq 'Analytics Logs Data Ingestion'",
         tramo=5.0, unidad="1 GB", cantidad=10, factor=1, supuesto="10 GB/mes supuestos, sin descontar los 5 GB gratuitos"),
    dict(ambito="plataforma", concepto="Azure Front Door Premium, cuota base (WAF incluido en Premium)",
         filtro="serviceName eq 'Azure Front Door Service' and skuName eq 'Premium' and meterName eq 'Premium Base Fees' and armRegionName eq 'Zone 1'",
         unidad="1/Month", cantidad=1, factor=1, supuesto="1 perfil para los tres pilares"),
    dict(ambito="firewall", concepto="Azure Firewall Standard (despliegue)",
         filtro=f"serviceName eq 'Azure Firewall' and armRegionName eq '{REGION}' and skuName eq 'Standard' and meterName eq 'Standard Deployment'",
         unidad="1 Hour", cantidad=1, factor=HORAS_MES, supuesto="1 firewall × 730 h"),
    dict(ambito="firewall", concepto="IP pública estándar estática del Firewall",
         filtro=f"serviceName eq 'Virtual Network' and armRegionName eq '{REGION}' and productName eq 'IP Addresses' and meterName eq 'Standard IPv4 Static Public IP'",
         unidad="1 Hour", cantidad=1, factor=HORAS_MES, supuesto="1 IP × 730 h"),
    dict(ambito="alternativa", concepto="Cosmos DB aprovisionado 3000 RU/s (en vez de serverless)",
         filtro=f"serviceName eq 'Azure Cosmos DB' and armRegionName eq '{REGION}' and productName eq 'Azure Cosmos DB' and skuName eq 'RUs' and meterName eq '100 RU/s'",
         unidad="1/Hour", cantidad=30, factor=HORAS_MES, supuesto="30 × 100 RU/s × 730 h, por pilar"),
]

VARIABLES = [
    "Tokens de `gpt-6-luna` y `gpt-5.6-luna` (DataZoneStandard): por uso, no hay cuota fija.",
    "Cosmos DB serverless: RU consumidas y almacenamiento.",
    "Storage (ZRS): capacidad, operaciones, versiones y borrado temporal retenido.",
    "Key Vault Standard: operaciones (no tiene cuota fija).",
    "Container Apps: vCPU, memoria y peticiones (frontal y backend escalan a cero; hay una franquicia mensual por suscripción).",
    "Front Door: peticiones y transferencia de datos; Firewall: datos procesados y unidades de capacidad.",
    "Endpoints privados: datos procesados; DNS privado: consultas; emparejamiento de VNet: GB transferidos.",
    "Log Analytics: ingesta por encima de la supuesta y retención por encima de 30 días.",
    "Microsoft Defender for Cloud (plan AI services) y Purview, si se activan: por uso y por suscripción.",
    "Recurso de Foundry, proyectos, identidades, Azure Policy y presupuestos: sin coste propio.",
]


class PrecioInvalido(Exception):
    pass


def descargar(filtro, abrir=urllib.request.urlopen):
    url = f"{API}?currencyCode=EUR&$filter={urllib.parse.quote(filtro)}"
    items = []
    while url:
        with abrir(url, timeout=60) as r:
            if getattr(r, "status", 200) != 200:
                raise PrecioInvalido(f"HTTP {r.status}")
            pagina = json.loads(r.read().decode("utf-8"))
        if not isinstance(pagina.get("Items"), list):  # 200 a medias (LES-G-099)
            raise PrecioInvalido(f"respuesta sin 'Items': {str(pagina)[:200]}")
        items += pagina["Items"]
        url = pagina.get("NextPageLink")
    return items


def precio(linea, items):
    tramo = linea.get("tramo", 0.0)
    for i in items:
        faltan = [c for c in CAMPOS if c not in i]
        if faltan:
            raise PrecioInvalido(f"{linea['concepto']}: elemento sin {faltan}")
    candidatos = [i for i in items if i["type"] == "Consumption" and float(i["tierMinimumUnits"]) == tramo]
    distintos = {(i["meterId"], i["retailPrice"], i["unitOfMeasure"]) for i in candidatos}
    if len(distintos) != 1:
        raise PrecioInvalido(f"{linea['concepto']}: {len(distintos)} precios candidatos (se espera 1): {sorted(distintos)[:4]}")
    i = candidatos[0]
    p = float(i["retailPrice"])
    if not math.isfinite(p) or p <= 0:
        raise PrecioInvalido(f"{linea['concepto']}: precio no válido {i['retailPrice']!r}")
    if i["currencyCode"] != "EUR":
        raise PrecioInvalido(f"{linea['concepto']}: moneda {i['currencyCode']}")
    if i["unitOfMeasure"] != linea["unidad"]:
        raise PrecioInvalido(f"{linea['concepto']}: unidad {i['unitOfMeasure']!r}, se esperaba {linea['unidad']!r}")
    mes = round(p * linea["cantidad"] * linea["factor"], 2)  # se suman los importes que se muestran
    if not math.isfinite(mes):
        raise PrecioInvalido(f"{linea['concepto']}: importe mensual no finito")
    return dict(linea, meterId=i["meterId"], skuName=i["skuName"], meterName=i["meterName"], precio=p, mes=mes)


def eur(x):
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def totales(filas):
    suma = lambda amb: sum(f["mes"] for f in filas if f["ambito"] == amb)
    t = dict(pilar=suma("pilar"), plataforma=suma("plataforma"), firewall=suma("firewall"), alternativa=suma("alternativa"))
    t["sin_fw"] = PILARES * t["pilar"] + t["plataforma"]
    t["con_fw"] = t["sin_fw"] + t["firewall"]
    return t


def documento(filas, t, fecha):
    def tabla(amb):
        out = ["| Concepto | skuName | meterName | meterId | Precio unitario | Unidad | Supuesto | €/mes |", "|---|---|---|---|---:|---|---|---:|"]
        for f in (f for f in filas if f["ambito"] == amb):
            out.append(f"| {f['concepto']} | {f['skuName']} | {f['meterName']} | `{f['meterId']}` | {f['precio']:.4f} € | {f['unidad']} | {f['supuesto']} | {eur(f['mes'])} |")
        return "\n".join(out)

    return f"""# Coste fijo mensual de la infraestructura (preventa multinube)

> Generado por `infra/coste_fijo.py` el **{fecha}** con la Azure Retail Prices API
> (`{API}`, `currencyCode=EUR`, región `{REGION}`; los medidores globales usan `Global` o `Zone 1`).
> No editar a mano: se regenera con `python3 infra/coste_fijo.py`. Precios de lista, sin descuentos ni IVA.
> Mes = {HORAS_MES} h. Nada de esto está desplegado.

## Resumen

| Concepto | €/mes |
|---|---:|
| Un pilar | {eur(t['pilar'])} |
| Tres pilares (×{PILARES}) | {eur(PILARES * t['pilar'])} |
| Plataforma compartida sin Firewall | {eur(t['plataforma'])} |
| Azure Firewall (hub compartido) | {eur(t['firewall'])} |
| **Total con Firewall** (diseño con Azure Firewall) | **{eur(t['con_fw'])}** |
| **Total sin Firewall** (variante `conFirewall=false`) | **{eur(t['sin_fw'])}** |

La variante sin Firewall conserva la entrada privada y la red privada de los agentes, pero pierde el control de
salida por destino (RED-9): los agentes pueden llegar a cualquier FQDN público. Azure Firewall Basic no tiene
precio publicado en `{REGION}` en la API (solo «Basic Secured Virtual Hub»), por eso el diseño usa Standard.

## Por pilar (se repite ×{PILARES})

{tabla('pilar')}

Sin coste fijo en el pilar: Cosmos DB **serverless** (Learn, standard-agent-setup: «Both Provisioned Throughput
and Serverless modes are supported.»), Storage, Key Vault Standard, recurso y proyecto de Foundry, despliegues de
modelos (pago por token) y Container Apps con escala a cero.

## Plataforma compartida

{tabla('plataforma')}

## Azure Firewall (opcional, `conFirewall`)

{tabla('firewall')}

## Alternativa no incluida en el total

{tabla('alternativa')}

Si Cosmos DB serverless no sirve en la prueba real (por ejemplo, por el mínimo de 3000 RU/s que exige Learn al
límite de rendimiento de la cuenta), el aprovisionado añade {eur(t['alternativa'])} por pilar y
{eur(PILARES * t['alternativa'])} en total.

## Variable (fuera del coste fijo; solo se nombra)

{chr(10).join('- ' + v for v in VARIABLES)}

## Supuestos y límites del cálculo

- La franquicia gratuita de Log Analytics (5 GB/mes) y la de Container Apps no se descuentan: el cálculo es conservador.
- El cargo de gestión de Container Apps se aplica por el endpoint privado que crea Front Door (Learn, container-apps/billing:
  «features such as private endpoints and planned maintenance are subject to a Dedicated Plan Management charge
  regardless of whether you use the Consumption or Dedicated plans»). La API publica además un medidor «Environment
  Private Endpoint» con el mismo precio; si se facturan los dos, el pilar sube {eur(0.0898 * HORAS_MES)} aprox. `[verificación pendiente]`.
- Las unidades de capacidad del Firewall Standard («Standard Capacity Unit») se tratan como variables `[verificación pendiente]`.
- La cuota base de Front Door Premium es por perfil, no por región; se toma el medidor de `Zone 1`. Las reglas
  administradas del WAF van incluidas en Premium (Learn, frontdoor/understanding-pricing: fila «Web Application
  Firewall managed rules», columna Premium «Free»); las peticiones son variables.
"""


def main():
    fecha = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    filas, errores = [], []
    for linea in LINEAS:
        try:
            filas.append(precio(linea, descargar(linea["filtro"])))
        except Exception as e:  # cada fallo se nombra; ninguno se silencia
            errores.append(f"{linea['concepto']}: {e}")
    if errores:
        print("FALLA: no se reescribe COSTE-FIJO.md", *errores, sep="\n  ")
        return 1
    t = totales(filas)
    if not all(math.isfinite(v) and v > 0 for v in t.values()):
        print(f"FALLA: totales no válidos {t}")
        return 1
    (pathlib.Path(__file__).parent / "COSTE-FIJO.md").write_text(documento(filas, t, fecha), encoding="utf-8")
    for f in filas:
        print(f"{f['ambito']:11} {eur(f['mes']):>14}  {f['concepto']}")
    print(f"Un pilar: {eur(t['pilar'])} | ×{PILARES}: {eur(PILARES * t['pilar'])} | plataforma: {eur(t['plataforma'])} | "
          f"firewall: {eur(t['firewall'])}\nTOTAL con Firewall: {eur(t['con_fw'])} | TOTAL sin Firewall: {eur(t['sin_fw'])} | fecha {fecha}")
    return 0


def prueba():
    base = dict(type="Consumption", meterId="m1", retailPrice=0.5, unitOfMeasure="1 Hour", skuName="S", meterName="M",
                currencyCode="EUR", tierMinimumUnits=0.0)
    linea = dict(concepto="x", unidad="1 Hour", cantidad=2, factor=10)
    assert precio(linea, [base])["mes"] == 10.0
    assert precio(dict(linea, tramo=5.0), [base, dict(base, retailPrice=0.2, tierMinimumUnits=5.0)])["precio"] == 0.2
    malos = {
        "vacío": [],
        "NaN": [dict(base, retailPrice=float("nan"))],
        "cero": [dict(base, retailPrice=0.0)],
        "dos precios": [base, dict(base, meterId="m2")],
        "unidad": [dict(base, unitOfMeasure="1/Day")],
        "moneda": [dict(base, currencyCode="USD")],
        "parcial": [{k: v for k, v in base.items() if k != "retailPrice"}],
    }
    for nombre, items in malos.items():
        try:
            precio(linea, items)
        except PrecioInvalido:
            continue
        raise AssertionError(f"no falla con {nombre}")

    class Resp:
        status = 200
        def __init__(self, cuerpo): self.cuerpo = cuerpo
        def read(self): return json.dumps(self.cuerpo).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    try:
        descargar("x", abrir=lambda u, timeout: Resp({"error": "parcial"}))
        raise AssertionError("acepta un 200 sin Items")
    except PrecioInvalido:
        pass
    paginas = iter([{"Items": [base], "NextPageLink": "p2"}, {"Items": [base], "NextPageLink": None}])
    assert len(descargar("x", abrir=lambda u, timeout: Resp(next(paginas)))) == 2
    print("prueba: OK")
    return 0


if __name__ == "__main__":
    sys.exit(prueba() if "--prueba" in sys.argv else main())
