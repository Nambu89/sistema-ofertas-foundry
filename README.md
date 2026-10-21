# Sistema de ofertas y arquitectura de IA en Microsoft Foundry

Sistema de Fernando para preparar ofertas comerciales y arquitecturas de sistemas de IA del pilar
Microsoft, nativo en Microsoft Foundry. Sustituye al sistema multiagente que hoy corre en local
(Claude Code y OpenCode) por agentes desplegados en un proyecto de Foundry. Fernando solo habla
con el coordinador; todo lo demás ocurre en la nube.

El diseño aprobado está en [docs/diseno/diseno-final-v2.md](docs/diseno/diseno-final-v2.md)
(copia saneada, sin nombres de clientes).

## Arquitectura

![Arquitectura del sistema en Microsoft Foundry](docs/arquitectura/arquitectura.es.png)

Diagrama con los iconos oficiales de Microsoft (Azure Architecture Icons V24): en
[español](docs/arquitectura/arquitectura.es.svg) y en [inglés](docs/arquitectura/arquitectura.en.svg),
editable en [draw.io](docs/arquitectura/arquitectura.drawio). Cómo leerlo y cómo regenerarlo:
[docs/arquitectura/README.md](docs/arquitectura/README.md).

Resumen en texto:

```
Fernando ── playground / POST /responses (OpenCode como cliente) ──> ofa-coordinador
```

- **ofa-coordinador** (agente hosted, ZIP con dependencias fijadas, sin Microsoft Agent Framework).
  Contiene, como código determinista:
  - el **intérprete** de órdenes (gramática cerrada; Decision-1 solo para clasificar la cabecera);
  - la **máquina de estados** por proyecto (`ALTA → SUFICIENCIA → … → CERRADO`, más `BLOQUEADO`);
  - el **escriba**, único escritor de lo compartido (SAS del contenedor activo, `If-Match`);
  - la **puerta**, módulo puro de solo lectura cuyo código de salida es el veredicto (0, 1 o 2).
- **Especialistas** (prompt agents, llamados por A2A con un `contextId` nuevo por delegación):
  `ofa-facilitador`, `ofa-investigador`, `ofa-experto-ms`, `ofa-arquitecto`, `ofa-estimador` y
  `ofa-verificador` (este con un modelo distinto del de los generadores). Ninguno escribe nada.
- **Memoria y estado** en Storage con versionado y borrado temporal: `sistema/`, `compartido/`,
  `agentes/<a>/` y un contenedor por proyecto con su estado en JSON, su memoria y su historial.
- **Foundry IQ** sobre AI Search como base de conocimiento interna, consultada con query key.
- **Microsoft Decision-1** para clasificar y para bloquear o escalar; nunca aprueba.
- Trazas en Application Insights, visibles para Fernando sin pedir nada a TI.

## Estructura

| Carpeta o fichero | Contenido |
|---|---|
| `config/entorno.ejemplo.json` | Plantilla con valores ficticios del entorno: tenant, suscripción, recurso, proyecto, endpoints, audiencias, versiones de API, prefijos, protegidos y despliegues con su SKU. Sin secretos. El fichero real es `config/entorno.local.json`, que git ignora |
| `lib/azure_auth.py` | Tokens de Entra con tenant fijo, comprobación del `tid`, caché y renovación 5 minutos antes de caducar |
| `lib/foundry.py` | Cliente REST del proyecto: listar, leer, crear agente o versión y borrar, con guardas que fallan cerrado |
| `lib/redaccion.py` | Redacción de tokens, claves, cadenas de conexión y firmas SAS antes de guardar o imprimir |
| `lib/config.py` | Carga y validación de la configuración |
| `tests/` | Pruebas con pytest, sin red ni Azure |
| `pruebas/paso0a/` | Arnés de las pruebas reales del paso 0a (P1 a P5), con modo `--simular` sin Azure. Ver su `LEEME.md` |
| `docs/diseno/` | Diseño aprobado (saneado) |

Las carpetas de los agentes (`agentes/<nombre>/`), del coordinador (`coordinador/`) y de `sistema/`
se añaden en las fases siguientes de la hoja de ruta del diseño (§9).

## Puesta en marcha (portátil, solo para construir y desplegar)

```bash
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest
```

Las pruebas no necesitan nada más: usan la plantilla `config/entorno.ejemplo.json`, con valores
ficticios. Las que comprueban que no se cuela ningún nombre real de cliente leen una lista local que
no se versiona (`config/nombres-reales.local.txt`, a partir de su plantilla `.ejemplo`); sin ella se
omiten y el resumen de pytest lo dice con «NO COMPROBADO». Lo mismo las que validan
`config/entorno.local.json`.

Para hablar con Azure, primero se crea la configuración local a partir de la plantilla y se
sustituyen los valores ficticios por los de tu tenant, suscripción, recurso y proyecto
(`config/entorno.local.json` no se versiona; sin él, `lib/config.py` falla en alto y dice qué copiar):

```bash
cp config/entorno.ejemplo.json config/entorno.local.json
# edita config/entorno.local.json con los valores reales
```

Después hace falta una sesión de la CLI en ese tenant:

```bash
az login --tenant <id-de-tu-tenant> --scope https://ai.azure.com/.default
# o leyéndolo de la configuración local:
az login --tenant "$(.venv/Scripts/python -c "import json; print(json.load(open('config/entorno.local.json', encoding='utf-8'))['tenant_id'])")" --scope https://ai.azure.com/.default
```

## Despliegue

- Los agentes se despliegan con el cliente de `lib/foundry.py`: solo se crea una versión nueva si
  la definición cambia, y después se relee y se compara con lo enviado.
- El coordinador se publica como agente hosted desde un ZIP con las dependencias incluidas y sus
  hashes anotados en el manifiesto.
- Las asignaciones de rol (Foundry User, Foundry Agent Consumer) y las conexiones con clave las
  hace Fernando: el despliegue automático no asigna roles ni lee o escribe secretos.
- Vuelta atrás: `version_selector` a la versión anterior del agente, el ZIP anterior por su SHA-256
  y la versión anterior del blob.

## Reglas

1. **Nada se ejecuta en local en producción.** El portátil solo construye, prueba y despliega.
2. **Prefijos.** Los agentes del sistema empiezan por `ofa-`; los desechables de prueba, por
   `ofa-prueba-`. El cliente REST rechaza escribir o borrar cualquier otro agente, y borrar un
   agente del sistema exige `permitir_sistema=True` explícito.
3. **Protegidos.** No se tocan jamás los agentes y la toolbox de la lista `protegidos` de
   `config/entorno.local.json` (agentes concretos, prefijos de agentes y toolboxes de otros
   proyectos del mismo tenant). La guarda los rechaza antes de pedir un token.
4. **Sin datos de clientes.** En el repositorio solo hay datos sintéticos y ningún nombre de
   cliente real.
5. **Sin secretos.** Ni tokens, ni claves, ni SAS en ficheros, salidas guardadas o logs. Todo texto
   que vaya a disco o a consola pasa por `lib/redaccion.py`. Los ficheros `.env` no se versionan.
6. **Tenant fijo** (el de la configuración local) en toda petición de token, con comprobación del
   `tid` del token recibido.
7. **Fallar en alto.** El código de salida es el veredicto; los reintentos se anotan siempre.
8. **Versiones exactas** de todas las dependencias.
