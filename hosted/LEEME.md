# Coordinador de preventa como hosted agent (opción B)

Fecha: 08-10-2026. Papel H de I1.1. **Sin desplegar**: lo despliega el integrador con `desplegar_hosted.py`.
Sin Microsoft Agent Framework: `azure-ai-agentserver-responses` **2.2.0** fijado exacto (LES-G-013).
La versión A (prompt agent `preventa-coordinador` v5) sigue desplegada como respaldo y no se toca.

## 1. Qué hace y qué no

| Lo hace el código (determinista) | Lo hace un modelo | No lo hace nadie |
|---|---|---|
| Interpretar los mensajes del comercial (§3) | Rellenar `requisitos.json` con citas literales de la transcripción (gpt-6-luna, Responses API del proyecto, `json_schema` estricto) | Enviar correos o mensajes |
| Ejecutar la máquina de estados del núcleo (`sandbox/preventa_api.py`) siguiendo su `SIGUIENTE PASO OBLIGATORIO` | | Dar horas, perfiles o tarifas al cliente (LES-G-053) |
| Transportar por A2A el brief y el consolidado **exactos** que generó el núcleo (LES-G-095) | | Reescribir un brief, una respuesta o una decisión |
| Construir `estimacion_entrada.json` desde las tareas del experto y la tarifa (§5) | | |
| Registrar cada fallo con su motivo literal (`registrar-fallo`) | | |

Las preguntas a/b/c/d de suficiencia ya las redacta el núcleo desde una tabla fija (`nucleo/suficiencia.py`),
así que no se usa el modelo para ellas: se entregan tal cual. Cada cita del modelo la comprueba el núcleo
(`suficiencia`); la única reparación del código es conservadora: una entrada que el modelo marque ASUMIDO
deja el campo en FALTA y se avisa (LES-G-047).

Arregla por diseño H6 y H3/H-V9 (nadie copia el brief ni el bloque de estado), H-V7 (el código no
reintenta por su cuenta), H1/H2 (esquema estricto con la envoltura y «Azure» exacto) y H4 (la entrada de la
estimación la compone el código).

## 2. Contrato del turno

- Protocolo Responses 2.0.0: `POST /responses`. El texto sale de los `input_text` del mensaje del usuario y
  los adjuntos de los `input_file` (`file_data` en data URL o base64, o `file_id` que se descarga de
  `/openai/v1/files` con la identidad del agente). `file_url` se rechaza. Nombres: solo `.txt .vtt .docx
  .pdf .json .zip`, sin rutas, hasta 50 MB (comprobado antes de decodificar) y 4 adjuntos por turno, sin
  pisar un fichero distinto con el mismo nombre. El endpoint del proyecto tiene que ser `*.services.ai.azure.com`.
- Carpeta persistente de la sesión: `$HOME/preventa/` con `datos/` (adjuntos), `trabajo/` (la del núcleo:
  `estado.json`, `entrada/`, `briefs/`, `consolidados/`, `salida/`, `fuentes/`, `procedencia/`) y `tmp/`.
  **Una solicitud por sesión** (por conversación). Un cerrojo en el proceso y otro de fichero (`flock`) sobre
  `$HOME/preventa/.cerrojo` serializan los turnos (API-NUCLEO §4: un solo escritor). Si el cliente cancela,
  el turno para antes del paso siguiente (nunca a mitad de uno) y lo hecho queda guardado.
- Cada turno: guarda adjuntos → interpreta el mensaje → aplica las órdenes → avanza con el `SIGUIENTE PASO`
  del núcleo hasta que haga falta una persona, falle algo o se llegue a `PREVENTA_MAX_A2A_POR_TURNO`
  llamadas A2A → responde con lo ejecutado (salida literal de cada subcomando, con el brief y el
  consolidado citados por su SHA-256), el bloque `=== ESTADO PREVENTA ===` literal, la línea PAQUETE o
  RELEVO con la orden de descarga y `SIGUIENTE PASO: …`.
- Paradas: INFORMACION_INSUFICIENTE, STOP_PRESUPUESTO, LISTA_PARA_REVISION, EN_REVISION_PREVENTA,
  EN_APROBACION_AREA, BLOQUEADA, DEVUELTA_CON_COMENTARIOS (salvo SIGUE) y cualquier `SIGUIENTE PASO` que
  no sea automático (se dice literal).
- Un fallo inesperado devuelve «FALLO INESPERADO del coordinador: <tipo>: <motivo>»; nunca un error opaco.
- **Motivo de cada DISCREPA en el turno (PR18-7, I1.9)**: si `registrar-verificacion` deja DISCREPA efectivos, el turno
  añade «Motivo de cada DISCREPA …» con el id, el campo que discute, el valor correcto, la fuente, el detalle del
  verificador y qué hace el núcleo con él (`fases.motivos_discrepa` → `nucleo.verificacion.lineas_discrepa_turno`, desde
  el estado guardado). Ya no hace falta descargar `estado.json` para verlo. Si el núcleo no puede leerlo, lo dice.
- **Entregable aprobado (VA18-7, I1.9)**: en APROBADA el PPTX del ZIP se llama `<codigo>-Propuesta.pptx` y su `title`
  es «<codigo> · Propuesta comercial» (`nucleo.paquete.nombre_pptx`; el título lo pone `pptx_revision`); en los demás
  estados sigue siendo `<codigo>-Revision.pptx`. La puerta lo exige a los paquetes desde el 2026-10-15.

## 3. Mensajes del comercial (gramática determinista, `preventa_hosted/mensajes.py`)

| Orden | Forma | Efecto |
|---|---|---|
| Alta | `- Cliente: …`, `- Código de cliente: XXX · SEQOF: NNN`, `- Título: …`, `- Términos sensibles: a; b` y la confirmación del NDA, con la transcripción adjunta o pegada tras `TRANSCRIPCIÓN:` | `iniciar` y T1 (requisitos con el modelo y `suficiencia`). Si falta algo, lo dice y no ejecuta nada |
| Confirmaciones | `CONFIRMO: NDA` o la frase del alta «Confirmo que el NDA …» | `--nda-confirmado` (sin ella no hay alta) |
| `ASUMIR: campo = valor` | una por línea, en mayúsculas | `asumir` con el valor literal |
| `ACLARACIÓN: texto` | una por mensaje | se guarda como fuente nueva, el modelo vuelve a proponer requisitos y `suficiencia --aclaracion` |
| `DECISION \| revisor \| TIPO \| AAAA-MM-DD \| hash \| comentarios` | literal | `decision --linea` (la valida el núcleo) |
| `RESTAURAR` | con UN ZIP (Paquete o Relevo) adjunto, o con `estado.json` y `manifiesto_paquete.json` | `restaurar --zip` (preferida) o la forma antigua |
| `ESTADO` | — | solo muestra el estado |
| `SIGUE` o `ADELANTE` | — | avanza; en DEVUELTA repite el análisis con los mismos requisitos |

Lo que no casa con la gramática no es una orden: el turno responde «No he reconocido ninguna orden» y no
ejecuta nada. La gramática de CONFIRMACIONES es propuesta mía: **la confirma el comercial** (CAMBIOS-I11-H §3).

## 4. A2A, identidad y roles

- JSON-RPC 2.0 con `method: SendMessage` (y `GetTask` para releer), cabecera `A2A-Version: 1.0`, contra
  `{proyecto}/agents/<agente>/endpoint/protocols/a2a`. Un único `parts[0].text` con el texto EXACTO.
  Forma tomada de evidencias reales (`pruebas/I0/B5/j_gettask_*.json`, `pruebas/I1/CONTRATO/intento1/`).
- Token: `DefaultAzureCredential().get_token("https://ai.azure.com/.default")` = identidad del propio hosted
  agent. Nunca se imprime ni se guarda.
- **Envío no bloqueante (PR17-2, arreglos I1.7)**: `SendMessage` lleva `configuration.returnImmediately: true` (A2A 1.0)
  y vuelve en segundos con la tarea en `TASK_STATE_SUBMITTED`; el código sondea `GetTask` (`historyLength: 0`) cada
  `PREVENTA_A2A_SONDEO_S` (5 s) hasta un estado terminal, con una espera propia por tarea `PREVENTA_A2A_ESPERA_S` (420 s,
  de 30 a 1.800). Comprobado contra el endpoint real el 13-10-2026 (`pruebas/I17/ARREGLOS/sonda_a2a_verificador.json`:
  SendMessage en 1,5 s y COMPLETED a los 10 s). Antes, el tope síncrono de 110 s cortaba al experto (111,9 y 112,6 s)
  y la respuesta, que Foundry sí terminaba y cobraba (VER17-4), se perdía y gastaba un intento.
  - Un `GetTask` fallido durante la espera es una lectura: se repite en el siguiente sondeo, se cuenta (`errores_sondeo`)
    y se dice en el turno. Con 5 seguidos, o al agotar la espera, o si el cliente cancela, la tarea queda **pendiente**
    (`pendiente: true` en `a2a.jsonl`, con su `task_id`). Por espera o por errores se registra el fallo (T2/T3 n/3) con la
    hipótesis «se recoge por su task_id»; si canceló el cliente, no se registra nada.
  - El turno siguiente, si el último `SendMessage` de esa fase a ese agente quedó pendiente y es del MISMO texto
    (SHA-256), **recoge esa tarea por su `task_id` sin reenviar** (`fases.pendiente_previa`, `recuperada: true`); la
    procedencia conserva la hora y la huella del envío original. Una tarea recogida que terminó mal se registra como fallo
    y el siguiente SIGUE envía de nuevo.
  - **Tarea perdida (REVERIF17-1, I1.8)**: si `GetTask` responde JSON-RPC `-32001` (TaskNotFound; Foundry lo da para un
    `task_id` que no existe o que la identidad no puede leer, `pruebas/I13/E2E-B/procedencia_gettask.json`) en **dos**
    sondeos seguidos, la tarea se da por perdida: `perdida: true`, `pendiente: false`, `codigo_jsonrpc: -32001` y el motivo
    literal en `a2a.jsonl`; el fallo (n/3) se registra con la hipótesis «ya no existe… se reenvía», nunca «sigue viva». El
    siguiente SIGUE **reenvía** el texto y ese envío lleva `reenvio_de` (el `task_id` perdido) y `motivo_reenvio`. Tras
    DESBLOQUEAR no se intenta recoger una tarea inexistente. Un `-32001` suelto (tarea recién creada aún no visible) no
    basta; otro error (por ejemplo `-32603` «Received 400» de un id mal formado) sigue siendo un fallo de lectura.
  - **`-32001` contrastado con la identidad (VPROT-3, I1.9)**: `-32001` también significa «no accesible para esta
    identidad» (lo vio el verificador de protocolo con su identidad sobre una tarea viva de B). Cada `SendMessage` guarda
    en `a2a.jsonl` la identidad con que se creó la tarea (`identidad`: claim `oid` del token, leído sin verificar la firma;
    el token nunca se guarda). Tras los dos `-32001`, la tarea solo se da por perdida si la identidad del sondeo
    (`identidad_sondeo`) es la misma. Si no consta (registro anterior a I1.9), no se puede leer o es otra, la tarea queda
    **pendiente y no se reenvía** («NO ACCESIBLE … se pagaría dos veces una tarea viva»): decide el comercial (volver a la
    identidad que la creó o abrir una sesión nueva). Regla de operación: no redesplegar B con otra identidad mientras
    haya tareas pendientes (hoy los redespliegues conservan 9905d2b3).
  - **Huella de lo enviado no corroborable (VPROT-2, residual)**: la huella de lo enviado a cada agente la escribe B y la
    plataforma no deja contrastarla: la traza corta la entrada a 8.192 caracteres con las instrucciones delante,
    `input_items` da 400 y `GetTask` con otra identidad da `-32001`. Lo mitiga que B calcula la huella sobre la misma
    variable que envía (`a2a.py`, `enviar`). Si Foundry publica el contenido completo (`_MS.GenAIContentId`), contrastarlo.
  - **Sondeo y relectura atados al id (REVERIF17-6)**: un `GetTask` de sondeo cuya respuesta no trae id de tarea es una
    lectura fallida (se repite y cuenta); una relectura que devuelve otro id, o ninguno, queda con error (la puerta: NO
    VERIFICADO).
  - **Línea ilegible en `a2a.jsonl` (REVERIF17-6)**: ya no hace reenviar en silencio. El turno registra el fallo (n/3) con
    las líneas y apunta un aviso (`metodo: LINEA_ILEGIBLE_AVISADA` con el SHA-256 de cada línea); el siguiente SIGUE las
    ignora y reenvía (riesgo declarado: si aquella tarea seguía viva, se paga dos veces). Una línea ilegible nueva vuelve
    a parar.
  - **Sin deduplicación por `messageId` (ARR17-1, sonda del 13-10-2026)**: dos `SendMessage` con el mismo `messageId`
    crearon **dos tareas** distintas en el verificador y `ListTasks` responde `-32004 UNSUPPORTED_OPERATION`
    (`pruebas/I18/R/sonda_a2a_idempotencia.json`). La especificación A2A 1.0 solo dice que la idempotencia «MAY» existir.
    Residual: si se pierde la respuesta de un `SendMessage` (sin `task_id`), el siguiente SIGUE reenvía y esa ejecución
    se paga dos veces; queda registrado en `a2a.jsonl` (el envío sin `task_id` y su error).
  - Si el servidor ignorase la opción y devolviera la tarea ya terminada, se usa tal cual (sin sondeo).
- **Reintento con el motivo (PR17-6 parte 2, I1.8)**: tras un rechazo del núcleo a la respuesta del experto, el texto que
  se envía es `nucleo.brief.texto_envio`: un bloque `REINTENTO-PREVENTA/1` con el `brief_id`, el número de rechazos y el
  **motivo literal** del último (anonimizado con los términos del alta), la marca `=== FIN DEL BLOQUE DE REINTENTO ===` y
  detrás el brief entero, sin cambiar. El experto devuelve en `brief_recibido` solo el brief (instrucción vigente: «desde
  la línea BRIEF-PREVENTA/1»). Los rechazos son los fallos T2 que sumó `registrar-experto` desde el último `enrutar`; un
  fallo de A2A no lo es, pero tampoco borra el motivo anterior. La puerta recompone el texto hasta el control que
  registró la respuesta y exige su huella en la tarea usada (paquetes desde el 2026-10-14).
- Timeout por **petición HTTP** `PREVENTA_A2A_TIMEOUT_S` (110 s; máximo 115). Llamadas por turno: `PREVENTA_MAX_A2A_POR_TURNO` (2 por defecto, de 1 a 8). La verificación se envía por **lotes** si el núcleo los genera (cada lote, una llamada) o
  el consolidado entero si no. Desde I1.7 los lotes solo llevan referencias y componentes (no hay lote de precios) y,
  en las rondas 2 y 3, solo lo nuevo o cambiado (PR16-6); ver el bloque I1.7 más abajo.
- Procedencia por llamada en `trabajo/procedencia/a2a.jsonl`: fase, agente, url, método, inicio, id
  JSON-RPC, SHA-256 y bytes de lo enviado y lo recibido, HTTP, latencia, `task_id`, `context_id`, estado de
  la tarea y el motivo literal del error (HTTP, JSON-RPC, timeout, red o tarea fallida). Las relecturas van con
  la fase `T2-relectura` o `T3-relectura`.
- **Procedencia propia de B** (decisión del comercial, 10-10-2026; I1.4 · P1), en
  `trabajo/procedencia/procedencia_a2a.json` (`preventa_hosted/procedencia.py`). Por cada tarea correcta: fase,
  agente, url, objetivo (brief o lote), hora, `task_id`, `context_id`, SHA-256 y bytes de lo enviado, el **texto
  recibido literal** y su SHA-256, y la **relectura con `GetTask`** hecha con la identidad del hosted agent (la
  única que puede leer la tarea, LES-G-089.10): `coincide` true, false o null con el motivo. Si la relectura no
  coincide o no se puede hacer, el turno lo avisa y sigue (la puerta local decide); si la procedencia no se puede
  escribir, la respuesta **no** se registra (`registrar-fallo`, con SIGUE se repite). Con el núcleo de
  `docs/I1/CAMBIOS-I14-P1.md`, el fichero va al ZIP del paquete y del relevo con su SHA-256 en el manifiesto;
  RESTAURAR con un ZIP lo fusiona en la sesión sin pisar nada. La puerta (`verificar_paquete.py`, `c_procedencia`)
  lo contrasta con las trazas de cada `task_id`.
- **I1.5 (papel R, `docs/I1/CAMBIOS-I15-R.md`)**:
  - Decisión 3 del comercial: si `GetTask` falla, el código lo repite **una vez**, anotado, y nunca más (la relectura
    guarda `intentos`). Sin `coincide: true`, el turno dice NO VERIFICADO y la puerta local deja esa salida NO
    VERIFICADO (con `--estricto` no da verde); una relectura distinta es FALLA.
  - REV-2: no se escribe ni se fusiona una tarea con la hora posterior a «ahora + 5 min».
  - REV-4: tras RESTAURAR, cada tarea nueva del ZIP se relee con `GetTask` antes de añadirla y se guarda la relectura
    nueva; si una difiere o es de otro agente, no se fusiona **nada** y el turno dice «FALLO: no fusiono…».
  - VER14-3: `python main.py` fija `PREVENTA_ORQUESTADOR=B` (no al importar el módulo) y el turno no ejecuta nada si
    no vale B. Con el cambio del núcleo de `CAMBIOS-I15-R.md` §2, `estado.json` y el manifiesto llevan `orquestador`
    y la puerta exige la procedencia si y solo si es B.
  - PR14-5: la línea PAQUETE solo ofrece el ZIP de la versión vigente y con el SHA-256 que registra el estado.
- **I1.7 (papel R, `docs/I1/CAMBIOS-I17-R.md`)**:
  - Decisión 1 del comercial (13-10-2026): ni el experto ni el verificador consultan la API de precios. El núcleo pone el
    precio de la **instantánea** que el código descarga al desplegar (`catalogo/precios_instantanea.json`, copia en
    `sandbox/datos/`), que viaja en el ZIP como `recursos/precios_instantanea.json` (variable `PREVENTA_PRECIOS`).
  - **Sin repetición A2A**: en I1.6 el aborto de Foundry por un error de `precios_azure` (filtro sin comilla o 429 de
    Retail Prices) se repetía una vez tras 20 s. Sin la herramienta de precios ya no hace falta: cualquier fallo A2A se
    registra **una vez** con `registrar-fallo` y su motivo literal, y SIGUE repite la fase (nunca en silencio, P-6).
  - **Lotes del verificador**: solo referencias (4 por lote) y componentes (5 por lote); el lote de precios (L6), que
    abortaba por el 429, desaparece. En la ronda 2 o 3 el núcleo envía solo lo nuevo o cambiado: lo que el
    verificador ya aceptó en una ronda anterior de la misma versión y llega igual se hereda (`brief.aceptados`) y, si
    aun así se objeta, la objeción pasa a OBSERVACION para la nota y nunca bloquea. La ronda 1 lo envía todo (en I1.6,
    5 lotes más el de precios); las rondas 2 y 3, solo lo cambiado (normalmente 1 o 2 lotes, sin medir aún en real).
  - Tras una DEVUELTA, la nota del revisor de la versión siguiente lleva «Cambios pedidos en la revisión anterior» con
    cómo se atendieron (VER16-5); desde I1.8 el PPTX ya no: lo que es del revisor no va al cliente (VER17-2).
- Roles que necesita la identidad del hosted agent (los asigna **el comercial** con `asignar_roles.sh
  <principal_id>`; el principal sale de la evidencia de `desplegar_hosted.py`):
  - **Foundry Agent Consumer** sobre el proyecto (o sobre `preventa-experto-azure` y `preventa-verificador`).
  - Inferencia del modelo y almacenamiento de sesión: por defecto según Learn (NO VERIFICADO).

## 5. Estimación por código (`nucleo.estimacion.componer_entrada`)

Regla decidida por el comercial el 10-10-2026, que aplica el núcleo igual en A y en B: una tarea por cada
`tareas_propuestas` (mismos campos, `tecnicas_h = horas_base`); gestión de proyecto = máx(8 h, ⌈15 % de las horas
técnicas⌉) y 1 h de seguimiento por semana (PM-02… si pasa de 400 h); fases en orden de aparición más «Gestión de
proyecto»; Gantt secuencial por fases con los perfiles distintos de cada fase trabajando en paralelo:
máx(1, ⌈horas de la fase / (40 × perfiles distintos)⌉) semanas; hitos de la tarifa; `ajuste_comercial_eur = 0` salvo
decisión; asunciones = supuestos del experto; exclusiones = `fuera_de_alcance`. Lo que no cabe en el esquema se omite
y se declara.

Si el `SIGUIENTE PASO` es `estimar (el núcleo compone …)`, el turno llama a `estimar` sin entrada. Desde los arreglos
de I1.4 (REV-1) la rama heredada (`Preparar entrada/estimacion_entrada.json…`) y `fases.estimar` ya no existen, el
núcleo no admite `--entrada` y rechaza cualquier entrada que no sea la de la regla (P6f);
`estimacion_entrada.construir` se conserva como prueba de que B compone con la misma función del núcleo.

## 6. Despliegue, descarga y pruebas

- `empaquetar.py` → ZIP plano y determinista (núcleo sin tocar con la estructura del repositorio, esquemas y
  recursos canónicos; se niega si el generador, la plantilla o la tarifa no casan con `manifiesto.json`). I1.7: se
  niega también si la instantánea de precios falta, no es igual byte a byte a la del catálogo ni a su entrada de
  `manifiesto.json`, tiene la huella interna rota, no cubre exactamente las plantillas del catálogo con su filtro o
  tiene **más de 31 días** (hay que regenerarla con `catalogo/instantanea_precios.py` y redesplegar).
- `desplegar_hosted.py` (integrador): sin `--confirmar` no toca Azure; con él, `create_version_from_code`
  como `preventa-prueba-hosted` (`python_3_13`, `remote_build`, 1 vCPU / 2 GiB, Responses 2.0.0), y exige
  `--sha256` con el que imprimió `empaquetar.py` (ancla externa: el manifiesto del ZIP solo prueba coherencia).
- `descargar_sesion.py` (El comercial): `listar`, `descargar` (no pisa nada) y `subir` por la API de ficheros de
  sesión, con `AzureCliCredential` y tenant explícito.
- `consumo_fallidas.py` (PR14-7, solo lee trazas): con el `a2a.jsonl` de la sesión, atribuye cada SendMessage fallido
  sin `task_id` a su `invoke_agent` (ventana, `conversation.id` y `error.type`) y suma los `chat` con uso de tokens.
  Una ejecución abortada (429, 400) no deja esos `chat`: su consumo sale NO_MEDIBLE (rc 3), nunca 0 €.
- Excepción conocida en las trazas (VER15-6, informativa): al arrancar, el contenedor registra en `exceptions` un
  `ModuleNotFoundError` «Failed to set up A365 OpenAI Agents instrumentation». Lo escribe la distribución
  `microsoft-opentelemetry` 1.4.0 (dependencia de `azure-ai-agentserver-core`, `_distro.py`): intenta instrumentar
  el SDK de OpenAI Agents, que este hosted no usa ni instala, y lo anota como aviso. No es un fallo del turno: las
  trazas siguen llegando (visto en I1.4 y en I1.5). No se silencia con código: instalar `openai-agents` solo para
  callarlo añadiría una dependencia sin uso.
- Pruebas (`tests/test_hosted_*.py`) con `hosted/.venv` (en el `.venv` del repositorio se omiten porque no
  tiene `httpx` ni el paquete fijado): servidor A2A y modelo falsos, núcleo real, servidor real del paquete
  en ASGI y el ZIP extraído en un proceso aparte.
  `PYTHONIOENCODING=utf-8 hosted/.venv/Scripts/python.exe -m pytest -q tests/test_hosted_*.py`
  Con `HOSTED_PRUEBA_NUCLEO=<copia>/sandbox` corren contra una copia del núcleo (p. ej. con el parche 09 de V).
  **Dependencia**: el recorrido completo necesita el parche 09 de V integrado (CAMBIOS-I11-H §2).

## 7. NO VERIFICADO hasta desplegar

1. Que el playground envíe los adjuntos como `input_file` con `file_data` o `file_id`, y que la identidad del
   agente pueda leer `/openai/v1/files/{id}/content`.
2. Que las rutas de la API de ficheros de sesión sean relativas a `$HOME` (el ejemplo de C# usa
   `/mnt/agent/session`).
3. Que la identidad del hosted agent llame a la Responses API con gpt-6-luna sin más roles.
4. ~~El tope real de una llamada A2A directa desde el contenedor~~: desde PR17-2 ya no aplica (envío no bloqueante y
   sondeo; cada petición dura segundos). Sigue sin medir cuánto aguanta un turno en segundo plano con dos esperas largas
   (hasta 2 × 420 s): se verá en la prueba real de los arreglos de I1.7.
5. Que `create_version_from_code` cree el agente si no existe (la docstring habla de «existing agent»; Learn
   lo usa para crearlo) y que el `remote_build` instale `requirements.txt` con Python 3.13.
6. Que `FOUNDRY_AGENT_SESSION_ID` llegue al contenedor (si no, la línea PAQUETE dice «<id de sesión>» y el id
   sale de `agent_session_id` en la respuesta).
7. El consumo: la respuesta del hosted no trae el `usage` del modelo ni el de los expertos (habrá que leerlo
   de las trazas, LES-G-089.5).
8. (I1.4) Que `GetTask` con la identidad del hosted agent lea sus propias tareas y devuelva el **mismo texto** que
   `SendMessage` (en I0 se leyó con el token de quien la creó; con el del hosted no se ha probado). Si devolviera
   otro texto, la relectura queda `coincide: false` y la puerta local rechaza el paquete: se verá en el primer
   recorrido real.

**Estado de los puntos 1 y 6 (18-10-2026, ronda 1 de arreglos de I1.9, COMP19-1): siguen abiertos.** Ninguna prueba
real de I1.4 a I1.9 ha recorrido el playground (por la API, el adjunto llega como `input_file` y la sesión sale de
`agent_session_id`, pero eso no prueba lo que hace el portal). Los cierra el recorrido del comercial con
`GUIA-PLAYGROUND-B.md` (pasos 1 a 4 y «Qué anotar y dónde»), que ya dice qué hacer ante `storage_error`, NO ACCESIBLE
y un rc 4 por instantánea caducada.

**Ronda 2 de arreglos (18-10-2026, `pruebas/I19/ARREGLOS.md`, ARR2-A1).**
- **Punto 6, cerrado por la API**: `FOUNDRY_AGENT_SESSION_ID` llega al contenedor. En los 3 turnos reales con línea de
  descarga (`turno_ARR1_H1A_sigue6`, `turno_ARR1_H2A_sigue6`, `turno_R19_H1B_sigue3`) el id de la línea PAQUETE es el
  `agent_session_id` de la respuesta y ninguno dice «<id de sesión>».
- **Punto 1, mitad `file_id` probada en real y FALLA**: con la transcripción subida a `{proyecto}/openai/v1/files` y
  enviada como `input_file` con `file_id`, B responde «No he podido guardar el adjunto: … HTTP 403 … Identity(object id:
  9905d2b3-…) does not have permissions for Microsoft.CognitiveServices/accounts/AIServices/agents/read actions» (falla
  cerrado, no ejecuta nada). La identidad solo tiene Foundry Agent Consumer sobre `preventa-experto-azure` y
  `preventa-verificador` (`interact/action`). Si el clip del playground usa `file_id`, el alta y RESTAURAR con adjunto
  no funcionan desde el portal hasta que el comercial dé un rol con esa acción de datos (opciones en `ARREGLOS.md`). Qué
  forma usa el portal sigue sin verse: es el paso 2 de la guía.
