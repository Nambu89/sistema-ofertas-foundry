# Resultados del paso 0a contra Azure (18-10-2026, datos sintéticos)

Ejecutado con `.venv/Scripts/python.exe pruebas/paso0a/ejecutar.py --solo <id>`, una prueba cada vez y ningún
comando de más de 90 s. Recurso y proyecto de la suscripción de pruebas, Sweden Central, token de
Entra con el tenant fijo. Las rutas de evidencia son relativas a `pruebas/paso0a/resultados/` (carpeta que no
se versiona). Los agentes `ofa-prueba-herramientas` (v1 y v2) y `ofa-prueba-hosted` (v1, v2 y v3) se conservan
para repetir. Las horas con «Z» son UTC; el resto, hora peninsular.

La ejecución tuvo tres tandas. La primera se cortó a las 12:21 porque az pidió MFA (AADSTS50076) y después hubo
un corte de DNS del servicio de modelos. La segunda, a partir de las 12:43, cerró P4 con la versión 3 del hosted y
repitió P5 con el arnés corregido. La tercera (11:43Z a 11:53Z) repitió P3, P4 y P5 después de la revisión de la
evidencia, para que cada resultado guarde las llamadas que lo produjeron, la hora de la medición y la salida
literal (ver «Tercera tanda»). P1 y P2 no se repitieron: ninguna corrección toca su código ni su evidencia. Las
evidencias de la segunda tanda están en `historial/v3-*.json` y la de P3 de la primera, en `historial/v1-P3.json`.

## Tabla

| Prueba | Estado | Evidencia (ruta y cita literal redactada) | Conclusión para el diseño |
|---|---|---|---|
| P1 Ciclo de vida | **FALLA** (con el supuesto fin de proyecto = hoy + 6 meses, umbral 2028-04-18) | `P1.json`: «gpt-5.6-luna: … retirada 2028-01-11 (deprecation.inference, ciclo GenerallyAvailable) · DataZoneStandard: apto para datos reales · NO CUMPLE»; «gpt-6-luna: … retirada 2028-03-11 … NO CUMPLE»; «Decision-1: modelo Microsoft-Decision-1 v1 · retirada 2027-02-04 (deprecation.inference, ciclo Preview)»; «text-embedding-3-large: … retirada 2028-02-09». gpt-5.6-terra y gpt-5.6-sol son GlobalStandard: «NO apto para datos reales (proceso global)» | Ningún despliegue llega al umbral. El de retirada más tardía es gpt-6-luna (2028-03-11): conviene que sea el modelo de los generadores en lugar de gpt-5.6-luna. **Decision-1 se retira el 2027-02-04**, antes incluso del supuesto fin de proyecto, así que no puede ser una dependencia estructural: debe ir detrás de una interfaz con respaldo (luna con salida estructurada) y con fecha de sustitución. terra y sol quedan fuera del camino de datos reales. Si el umbral de LES-G-036 aplica tal cual a un sistema interno lo decide Fernando |
| P2 Decision-1 | **PASA** | `P2.json` y `P2-decision-io.json`: «noul: HTTP 200 en 1.257 s · VÁLIDA: noul=0.9999…»; «choice: HTTP 200 en 0.181 s · VÁLIDA: choice=rag» (con `confidence` y `probabilities` por opción); «score: HTTP 200 en 0.163 s · VÁLIDA: score=2.83… (escala 0..3)». Endpoint `…services.ai.azure.com/providers/microsoft/v1/systemone`, token con audiencia `https://cognitiveservices.azure.com` | Decision-1 funciona con Entra, sin clave y sin rol nuevo, y tarda unos 0,2 s en caliente. El campo numérico de noul se llama `noul` (era lo NO VERIFICADO del arnés). choice devuelve probabilidades por opción, que sirven de umbral de confianza en el enrutado. Cada llamada usó unos 100 tokens de entrada y 1 de salida |
| P3 Herramientas del prompt agent | **PASA** (tercera tanda, 11:43:59Z) | `P3.json`: «Agente ofa-prueba-herramientas v2 (gpt-5.6-luna); herramientas: mcp mslearn ['microsoft_docs_search', 'microsoft_docs_fetch'] + web_search»; «mcp … tipos=['mcp_list_tools', 'mcp_call']; mcp_call ['microsoft_docs_search'] en mslearn sin error; status literal de cada mcp_call=['completed']»; «web … tipos=['mcp_list_tools', 'web_search_call']; status literal de cada web_search_call=['completed']». Los items de salida (redactados y recortados) están en `P3-io.json` | El MCP de Learn y `web_search` funcionan en un prompt agent sin toolbox ni conexión Bing, y la suscripción no bloquea Web Search. Es la base del experto Microsoft. Web Search saca la consulta del límite de cumplimiento, así que solo se usa con preguntas genéricas, nunca con datos de cliente (diseño §3.3) |
| P4a Salida HTTP del hosted | **PASA** (segunda y tercera tanda) | `P4a.json` (tercera tanda, medido a las 11:44:32Z): ««ORDEN: SALIDA» → HTTP 200 en 6.2 s · https://learn.microsoft.com → HTTP 200 (0.355 s); https://prices.azure.com/api/retail/prices?$top=1 → HTTP 200 (0.223 s); https://azureopendatastorage.blob.core.windows.net/ → HTTP 400 (0.416 s)». La v1 dio «SIN SALIDA: … Name or service not known» porque apuntaba a una cuenta de Storage que no existe: era un defecto del arnés | El hosted sale a Internet: los 200 de Learn y de precios de Azure lo demuestran. Desde `*.blob.core.windows.net` llega una respuesta HTTP, pero el 400 se guardó sin cabeceras (`Server`, `x-ms-request-id`), así que no se puede afirmar que lo firme Azure Storage y no un proxy intermedio. El acceso **autenticado** a la cuenta propia (SAS de turno o identidad) no se ha medido: queda para el paso 0b. El bloqueo §9 se levanta solo en lo que toca a la salida general |
| P4b Secreto por conexión | **PENDIENTE_FERNANDO** | `P4b.json`: «la conexión ofa-prueba-marcador no existe; el agente se desplegó sin la referencia (con ella, el servicio rechaza el despliegue con HTTP 400 «workspace connections … were not found») y la variable no llega: {'variable_definida': False, …}». Error literal del primer intento: «The following workspace connections referenced in environment variable templates were not found: ofa-prueba-marcador» | Una referencia `${{connections.X.credentials.Y}}` a una conexión inexistente **falla en alto al desplegar**: el agente no arranca con la variable vacía. Falta comprobar la resolución real cuando la conexión exista |
| P4c Turno largo en background | **PASA** (segunda y tercera tanda) | `P4c.json` (tercera tanda, lanzado 11:44:56Z y cerrado 11:51:06Z): «background + 15 sondeos cortos; 370 s de reloj local · completed tras 360.0 s medidos en el contenedor (pedidos 360)», con la hora, el HTTP y el status de cada sondeo y «hueco máximo entre sondeos 37 s». Dos sondeos no obtuvieron respuesta (HTTP -1, red) y el turno siguió. `historial/v3-P4c.json`: «background + 8 sondeos cortos; 1623 s de reloj local · completed tras 360.0 s». `historial/v2-P4c.json`: «background + 11 sondeos cortos; 368 s» | Un turno de 6 minutos en background con sondeo corto termina sin cortes, aunque se pierdan sondeos sueltos. Que la respuesta siga recuperable tras un hueco largo sin sondear es una **inferencia NO VERIFICADA**: sale de los 1623 s con solo 8 sondeos de la segunda tanda (corte por MFA), pero esa evidencia no guarda la hora de cada sondeo. El hueco máximo registrado es de 37 s. Antes de que el coordinador confíe en reanudar tras una caída larga del cliente, hay que medirlo a propósito: dejar de sondear un tiempo fijado y anotarlo |
| P4d api-version del endpoint | **PASA** (v2 y v3) | `P4d.json` (v3): «con ?api-version=v1 → HTTP 200: {"orden": "ECO", "eco": "ECO-OFA: api-version-p4d"} \| sin api-version → HTTP 400: {"error":{"code":"BadRequest","message":"Missing required query parameter: api-version"}}» (repetido en la tercera tanda a las 11:44:51Z, con las dos peticiones en el campo `comando`). Las sondas manuales de la segunda tanda (`…/endpoint/protocols/openai/v1/responses?api-version=v1` y el host `…cognitiveservices.azure.com`) no guardaron comando ni respuesta: **NO VERIFICADO** | El endpoint del hosted **exige** `api-version=v1`, igual que la gestión de agentes (`agents…`). Todo cliente del coordinador debe añadirlo |
| P4 agregado | **PENDIENTE_FERNANDO** (solo por P4b) | `P4.json` (tercera tanda, 11:51:06Z): «Agente ofa-prueba-hosted v3 (estado active); ZIP bundled python_3_13 SHA-256 276b4943…20dc (13358398 B); conexión ofa-prueba-marcador: no existe (ARM HTTP 404). Estado al subir: active; active 0.1 s después de la subida (1 sondeos de versión).» con P4a, P4c y P4d en PASA. Su `comando` son las llamadas del despliegue; cada P4x lleva las suyas | El despliegue por ZIP bundled (multipart REST, `dependency_resolution: bundled`, python_3_13) funciona. Volver a subir el mismo ZIP con la misma definición devuelve la versión existente (v3), ya `active`: el versionado por contenido queda comprobado. Cuánto tarda en pasar a `active` una versión **nueva** no consta en ninguna evidencia: **NO VERIFICADO** (se medirá en la v4, con la conexión de P4b). Lo único que falta del hosted es el secreto por conexión |
| P5 OpenCode como cliente | **PASA** (tercera tanda, 11:53:21Z) | `P5.json`: «Comando: timeout 75 opencode run --dir ofa-p5-opencode -m ofa-hosted/ofa-prueba-hosted "ORDEN: ECO p5-06e27788". opencode rc=0 y la respuesta del hosted contiene «ECO-OFA: p5-06e27788» (1 vez/veces); salida literal (redactada, últimos 800 caracteres): {"orden": "ECO", "eco": "ECO-OFA: p5-06e27788"} … > build · ofa-prueba-hosted \| P4d: el endpoint NO responde sin api-version.» Historial del diagnóstico: `historial/v3-P5.json` (PASA de la segunda tanda, sin la salida), `historial/v2-P5.json` («AI_APICallError: Missing required query parameter: api-version»), `historial/P5-manual-urls-ai-sdk-azure.txt` (@ai-sdk/azure tampoco añade la consulta), `historial/P5-manual-bucle-usage-null.txt` (14 respuestas repetidas en una sola ejecución; el fichero no guarda el comando, la duración ni el evento con `usage: null`) y `historial/P5-manual-pasa-fetch-y-usage.txt` (una sola respuesta, sin comando guardado) | OpenCode 1.18.33 sirve como cliente del coordinador con **tres** condiciones, todas comprobadas: (1) un plugin que ponga el token (`chat.headers`, tenant fijo) y añada `?api-version=v1` con un envoltorio de `fetch` limitado al prefijo exacto del hosted, porque OpenCode no añade el parámetro ni con @ai-sdk/azure; (2) **el coordinador debe enviar `usage` en `response.completed`**, porque sin él OpenCode repite el turno en bucle: lo muestran las 14 respuestas repetidas, y con `usage` a cero en el hosted el arnés pasa con una sola respuesta. Que `TextResponse` de agentserver-responses 2.2.0 mande `usage: null` sale de leer su código; no hay captura guardada del evento (NO VERIFICADO en la evidencia); (3) **el lanzador fija `--dir` y `PWD` a la vez**, como hace el arnés. Sin la corrección, el registro de OpenCode muestra la sesión abierta en el directorio del repositorio (el `PWD` heredado), sin el proveedor ni el plugin, y «UnknownError». Las dos se introdujeron juntas, así que no está aislado si basta con una; que OpenCode tome el directorio de `PWD` antes que del directorio real del proceso es una hipótesis compatible con el registro. Esto entra en el canal OpenCode (`canales-opencode-teams.md`). La primera ejecución en un directorio nuevo tarda unos 30 s más porque instala las dependencias del plugin |

## Correcciones hechas al arnés durante la ejecución

1. `comun.ClientePruebas.params_datos`: añade `api-version` (de la configuración) a las rutas `agents…`. No lo
   añade en `openai/v1/…` ni en el endpoint del hosted, donde P4d mide a propósito la llamada sin él.
2. `p4_hosted.definicion`: la referencia a la conexión solo se incluye si la conexión existe.
3. `hosted_prueba/ofa_prueba_hosted/ordenes.py`: el tercer destino de SALIDA pasa a ser la cuenta pública
   `azureopendatastorage`.
4. `hosted_prueba/main.py`: un generador propio con los mismos eventos que `TextResponse` y `usage` a cero en
   `response.completed`.
5. `p5_opencode.py`: envoltorio de `fetch` para `api-version`, directorio fijo `$TEMP/ofa-p5-opencode` con marca
   de calentado, `XDG_DATA_HOME` aislado y 75 s de tiempo máximo (antes 120 s, por la regla de 90 s). El
   presupuesto de P5 pasa a 87 s.
6. Segunda tanda, `p5_opencode.py`:
   - Si la comprobación previa del hosted no obtiene respuesta (DNS o red), o recibe 408, 429 o 5xx, P5 sale
     con 4 (en curso) en lugar de FALLA. El primer intento de la segunda tanda dio «NameResolutionError …
     getaddrinfo failed» 15 s después de un P4 correcto, y `nslookup` y `curl` resolvían bien justo después:
     era un corte transitorio, no un veredicto sobre OpenCode.
   - `entorno()` fija `PWD` al directorio de trabajo y el comando añade `--dir <directorio>`. El segundo
     intento salió «UnknownError … Unexpected server error»; el registro de OpenCode mostraba «creating
     instance» primero en `$TEMP/ofa-p5-opencode` y después en el directorio del repositorio, que es el `PWD`
     heredado del shell. Con la corrección, el tercer intento pasó y el registro solo muestra el directorio de
     `$TEMP`. Ese intento fallido no escribió nada en el repositorio (comprobado con `git status --ignored`) y
     su sesión quedó en la base de datos aislada de `$TEMP`.
7. Las pruebas unitarias se han actualizado y ampliado: 339 pasaban al cerrar la segunda tanda (444 tras la
   tercera, ver abajo). La simulación sale con 0 en el escenario feliz.
8. Codex (solo lectura, effort low) revisó las correcciones del punto 6. Su único hallazgo era de severidad
   baja: un 408 se clasificaba como FALLA. Está corregido y tiene prueba. No encontró problemas de seguridad
   en `PWD` ni en `--dir`, porque el proceso recibe una lista de argumentos, no una cadena de shell.

### Tercera tanda: correcciones tras la revisión de código y de evidencia

9. Seguridad y códigos de salida:
   - `lib/redaccion.py`: la redacción y `es_nombre_secreto` reconocen nombres con prefijo de identificador
     (`AZURE_FOUNDRY_KEY`, `NVIDIA_API_KEY`, `OPENCODE_SERVER_PASSWORD`, `"azure_api_key"`), en texto, en
     diccionarios y en la validación de la configuración. Exigen el separador `_` o `-`, para no tocar
     `OLDPWD` ni `total_tokens`.
   - `lib/config.py`: `protegidos.agentes`, `prefijos_agentes` y `toolboxes` tienen que ser listas de cadenas no
     vacías. Una cadena se recorría carácter a carácter y desactivaba la guarda.
   - `comun.ClientePruebas`: `POST openai/v1/responses` exige un único agente `ofa-prueba-` en
     `agent_reference.name` (o `agent.name`) y lo pasa por la guarda de protegidos. Antes dejaba invocar
     cualquier agente del proyecto, protegidos incluidos.
   - `ejecutar.py` y `limpiar_pruebas.py`: una excepción imprevista sale con 2 (error del arnés) y un fallo de
     autenticación, con 5, también fuera del bucle. Antes salían con traceback y rc=1, el código de FALLA.
   - `pasos-fernando/02-storage.sh` muestra el mensaje de `az login` cuando la consulta de la cuenta falla por
     autenticación (antes se perdía en un fichero temporal). `04a` apunta la clave antigua como pendiente solo
     después de regenerarla. `04d` trata como fallo, y no como «borrada», que no se puedan listar las claves.
10. Evidencia:
    - P4: si ARM falla al consultar la conexión (5xx tras los reintentos), P4 da FALLA con la respuesta
      literal. Solo el 403 deja la conexión como «desconocida» y P4b como PENDIENTE_FERNANDO.
    - P4: cada P4x guarda las llamadas que la produjeron y la hora de su medición (antes todas llevaban el
      sondeo final de P4c y la hora del veredicto). P4 lleva las llamadas del despliegue y el tiempo hasta
      `active`. P4c guarda la hora, el HTTP y el status de cada sondeo y el hueco máximo entre dos.
    - P3: el comando acumula las llamadas de todas las invocaciones. Un `web_search_call` solo cuenta con
      status `completed` literal, la evidencia cita el status de cada llamada y los items de salida quedan en
      `P3-io.json`.
    - P5: cuando pasa, la evidencia lleva la salida literal de OpenCode (redactada, sin códigos de color y con
      la carpeta personal sustituida por `~`) y cuántas veces aparece el eco.
    - Repetidas con `--solo`: P3 (PASA), P4 (PENDIENTE_FERNANDO solo por P4b; el turno largo, PASA) y P5
      (PASA). En P5 hubo dos intentos más: uno pasó con la salida aún con códigos de color (se corrigió y se
      repitió) y otro salió con 4 por un fallo de DNS en la comprobación previa («getaddrinfo failed»), igual
      que en la segunda tanda. El siguiente pasó.
    - Pruebas unitarias: 444 pasan. La simulación sale con 0.
11. Codex (solo lectura, effort low) revisó los ficheros tocados en esta tanda (EXIT=0) y señaló dos cosas, las
    dos descartadas tras reproducirlas: (a) que `max_tokens` se redactaría como secreto, pero
    `es_nombre_secreto("max_tokens")` da `False` y `redactar("max_tokens=4000")` no cambia nada, porque detrás
    del nombre secreto se exige el separador o el final; (b) que `limpiar_pruebas` fallaría con un agente sin
    nombre, pero `seleccionar` ya lo convierte en la cadena «None» y `main` sale con 0 (queda una prueba que lo
    fija). Un nombre como `max_token`, en singular, sí se redacta: es un exceso del lado seguro.

Antes de la corrección del punto 5, dos ejecuciones manuales de OpenCode y la propia ejecución del arnés
escribieron sesiones de prueba en la base de datos de OpenCode del usuario, porque `XDG_DATA_HOME` aún no estaba
aislado. Son sesiones del directorio `Temp/ofa-p5-*` y no contienen tokens. Desde esa corrección, P5 ya no
escribe ahí.

## Pendiente de Fernando

1. **P4b, conexión de prueba con valor NO secreto.** El modo automático no deja crear conexiones con clave.
   - En el portal de Foundry: el proyecto → Recursos conectados → Nueva conexión → Claves
     personalizadas (Custom keys). Nombre `ofa-prueba-marcador`, clave `valor`, valor `marcador-sintetico`.
   - Alternativa por CLI. La forma de ARM no está verificada; si falla, usa el portal:
     `az rest --method put --url "https://management.azure.com/subscriptions/<suscripcion>/resourceGroups/<grupo>/providers/Microsoft.CognitiveServices/accounts/<recurso>/projects/<proyecto>/connections/ofa-prueba-marcador?api-version=2025-04-01-preview" --body '{"properties": {"category": "CustomKeys", "authType": "CustomKeys", "target": "https://learn.microsoft.com", "isSharedToAll": false, "credentials": {"keys": {"valor": "marcador-sintetico"}}, "metadata": {"uso": "prueba P4b del paso 0a"}}}'`
   - Después, desde la raíz del repositorio: `.venv/Scripts/python.exe pruebas/paso0a/ejecutar.py --solo P4 --repetir`
     UNA vez, y luego la misma orden SIN `--repetir` mientras salga 4: `--repetir` borra el progreso y el turno
     largo volvería a empezar en cada invocación. Son unas 8 invocaciones por el turno largo de 6 minutos. La
     definición cambia sola y el servicio crea una versión nueva (v4) que resuelve la referencia. El script
     `pasos-fernando/06-cerrar-p4b.sh` lo hace así (paso 0b).
2. **Decisiones de diseño que salen de P1:**
   - Si el umbral de LES-G-036 (fin de proyecto + 12 meses) aplica tal cual al sistema interno.
   - Cambiar los generadores de gpt-5.6-luna (retirada 2028-01-11) a gpt-6-luna (2028-03-11).
   - Cómo y cuándo se sustituye Decision-1 (Preview, retirada 2027-02-04).
3. **Requisitos nuevos para el coordinador y el canal OpenCode, a confirmar en el diseño:**
   - El coordinador envía `usage` en `response.completed`, con los tokens reales sumados de sus llamadas a
     modelos.
   - El plugin de OpenCode (token con tenant fijo y `api-version=v1` limitado al prefijo del hosted) forma parte
     del canal OpenCode (`canales-opencode-teams.md`).
   - El lanzador de OpenCode fija el directorio del proyecto con `--dir` y `PWD` a la vez (no está aislado si
     basta con uno).
4. **Mediciones que quedan NO VERIFICADAS** (no bloquean el paso 0a):
   - cuánto tarda en pasar a `active` una versión nueva del hosted (se medirá con la v4 de P4b);
   - si una respuesta en background sigue recuperable tras un hueco largo sin sondear;
   - quién firma el 400 de Blob (no se guardaron cabeceras) y el acceso autenticado a una cuenta propia
     (paso 0b).
