# Arnés de pruebas del paso 0a

Comprueba, con datos sintéticos, lo que el diseño (`docs/diseno/diseno-final-v2.md`, §9, fase 0a) necesita
saber antes de construir: ciclo de vida de los modelos, Decision-1, herramientas de los prompt agents,
hosted agent por ZIP y OpenCode como cliente. Todos los comandos se lanzan desde la raíz del repositorio.

## Contrato

- Cada prueba escribe `pruebas/paso0a/resultados/<id>.json` con `id`, `estado` (PASA, FALLA,
  PENDIENTE_FERNANDO o NO_APLICA), `evidencia` (resumen literal redactado), `comando` (el del arnés más las
  llamadas HTTP hechas) y `fecha`. La carpeta `resultados/` no se versiona.
- Una prueba sin veredicto todavía (despliegue en curso, turno largo, ZIP sin construir) no escribe
  resultado: guarda `resultados/<id>.progreso.json` y sale con 4. Al volver a lanzarla, sigue donde iba.
- Códigos de salida: 0 PASA o NO_APLICA · 1 FALLA · 2 error de uso o del arnés · 3 PENDIENTE_FERNANDO ·
  4 en curso · 5 autenticación. Con varias pruebas manda FALLA, luego en curso, luego PENDIENTE_FERNANDO.
- Si sale 5, Fernando ejecuta `! az login --tenant <id-de-tu-tenant> --scope https://ai.azure.com/.default`.
- Ninguna invocación pasa de unos 85 s (presupuesto por defecto 80 s, `--presupuesto` hasta 85). La única
  excepción es P5: necesita 87 s (opencode con `timeout 75`; antes 120, rebajado para cumplir la regla de 90 s)
  y solo corre con `--solo P5`.
- Nada de lo que se guarda lleva tokens: todo pasa por `lib/redaccion.py`. El token de Fernando sale de
  `az` con el tenant fijado (LES-G-052).
- El arnés solo crea, modifica o llama a agentes `ofa-prueba-` (guarda en `comun.ClientePruebas`, además de
  la de `lib/foundry.py`), y solo lee ARM dentro del recurso de `config/entorno.local.json`.

## Simulación (sin Azure)

```bash
.venv/Scripts/python.exe pruebas/paso0a/ejecutar.py --simular                       # escenario feliz: sale 0
.venv/Scripts/python.exe pruebas/paso0a/ejecutar.py --simular --escenario adverso   # comprueba que falla en alto: sale 1
```

Escribe en `resultados/simulado/<escenario>/` y marca cada evidencia como `[SIMULADO…]`.

## Pruebas reales

| Prueba | Comando | Qué hace | Notas |
|---|---|---|---|
| P1 | `.venv/Scripts/python.exe pruebas/paso0a/ejecutar.py --solo P1` | Lee de ARM los despliegues (modelo, versión y SKU reales) y la lista de modelos de la cuenta (`deprecation.inference` y `skus[].deprecationDate`). Aplica LES-G-036 con el supuesto fin de proyecto = hoy + 6 meses | Sin fecha, falla. Con la fecha de LES-G-036 para gpt-5.6-luna (2028-01-11) y el umbral de hoy (2028-04-18), luna no cumple |
| P2 | `… --solo P2` | Tres llamadas a Decision-1 (noul, choice, score) por `/providers/microsoft/v1/systemone` con token de `https://cognitiveservices.azure.com`; mide latencia | Entrada y salida en `resultados/P2-decision-io.json`. 403 da PENDIENTE_FERNANDO con el comando del rol |
| P3 | `… --solo P3` (repetir hasta que salga distinto de 4) | Crea o versiona `ofa-prueba-herramientas` (gpt-5.6-luna, MCP de Learn y `web_search`), lanza dos preguntas en background y sondea | Si la API rechaza Web Search, el agente se crea sin ella, MCP se prueba igual y Web queda PENDIENTE_FERNANDO con el motivo literal |
| P4 | 1) `.venv/Scripts/python.exe pruebas/paso0a/hosted_prueba/empaquetar.py` · 2) `… ejecutar.py --solo P4` (repetir mientras salga 4) | Despliega `ofa-prueba-hosted` por ZIP bundled y ejecuta P4a SALIDA, P4b MARCADOR, P4d API-VERSION y P4c TURNO LARGO (360 s en background, sondeo corto en cada invocación) | Escribe P4a…P4d y el agregado P4. Si `empaquetar.py` corta a los 80 s, se vuelve a lanzar: cada fase continúa |
| P5 | `… --solo P5` (repetir si sale 4) | En el directorio fijo `$TEMP/ofa-p5-opencode` escribe un `opencode.json` con proveedor `@ai-sdk/openai` hacia el endpoint del hosted y un plugin con `chat.headers` (token, tenant fijo) y un envoltorio de `fetch` que añade `?api-version=v1` solo al prefijo del hosted; ejecuta `opencode run` con 75 s de tiempo máximo | Necesita P4 desplegado. La primera ejecución en el directorio instala las dependencias del plugin y puede salir 4 sin veredicto; el directorio se conserva |

Para repetir una prueba con resultado final: añade `--repetir`.

## Empaquetado del hosted (`hosted_prueba/empaquetar.py`)

Tres fases (`--fase descargar|instalar|zip`, por defecto todas): ruedas Linux x86_64 para Python 3.13 en
`hosted_prueba/_build/ruedas`, instalación en `_build/packages` y ZIP determinista en
`pruebas/paso0a/_salidas/ofa-prueba-hosted.zip`. El ZIP lleva `MANIFIESTO-HOSTED.json` con el SHA-256 de cada
fichero y de cada rueda, más la lista exacta de versiones (`bloqueo`). Se rechazan binarios de Windows y `.so`
que no sean ELF.

## Limpieza

```bash
.venv/Scripts/python.exe pruebas/paso0a/limpiar_pruebas.py                         # lista
.venv/Scripts/python.exe pruebas/paso0a/limpiar_pruebas.py --confirmar --forzar    # borra los ofa-prueba- y sus sesiones
```

Solo borra agentes `ofa-prueba-` que superan `comprobar_nombre_borrable`. La conexión `ofa-prueba-marcador`,
si se creó, la borra Fernando (el script imprime el comando).

## Lo que necesita a Fernando

- P4b: crear la conexión `ofa-prueba-marcador` (Custom keys, clave `valor`, valor NO secreto
  `marcador-sintetico`). El resultado PENDIENTE_FERNANDO trae los pasos del portal y un `az rest` alternativo.
- P2: si Decision-1 da 403, asignarse Foundry User sobre el recurso (el resultado trae el comando).
- P3: si Web Search está bloqueada en la suscripción, decidir si se habilita (Learn: `OpenAI.BlockedTools.web_search`).

## Correcciones hechas al ejecutar contra Azure (18-10-2026)

- `comun.ClientePruebas.datos` añade `api-version` a la gestión de agentes (`agents…`): sin él, HTTP 400
  «Missing required query parameter: api-version». No se añade en `openai/v1/…` ni en el endpoint del hosted.
- P4: la referencia `${{connections.ofa-prueba-marcador…}}` solo va en la definición si la conexión existe; con
  una conexión inexistente el servicio rechaza el despliegue (HTTP 400 «workspace connections … were not found»).
- Hosted: el tercer destino de SALIDA era una cuenta de Storage que no existe (NXDOMAIN); ahora es la cuenta
  pública `azureopendatastorage`. Y `response.completed` lleva `usage` a cero: con `usage: null` OpenCode no
  reconoce el fin del turno y repite la petición en bucle.
- P5: envoltorio de `fetch` para `api-version`, directorio fijo, `XDG_DATA_HOME` aislado y 75 s de tiempo máximo.
