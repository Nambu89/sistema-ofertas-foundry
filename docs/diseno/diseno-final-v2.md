> Copia saneada del diseño aprobado por Fernando el 18-10-2026. Los nombres de clientes reales se han
> sustituido por «cliente A», «cliente B»… y los de terceros con acceso al tenant por «identidades ajenas».
> El original vive fuera del repositorio y no se versiona. Las referencias a reglas y notas internas se han
> sustituido por su contenido técnico, y las fuentes internas se citan sin ruta porque no se publican.

**A) DISEÑO FINAL v2. Sistema de ofertas y arquitectura de Fernando en Foundry (18-10-2026)**

**Fuentes.** Las páginas de Learn están bajo `learn.microsoft.com/en-us/azure/foundry/`:
- [HA] agents/concepts/hosted-agents
- [HP] …/hosted-agent-permissions
- [SS] …/agent-state-store
- [A2A] agents/how-to/enable-agent-to-agent-endpoint
- [MEMU] …/memory-usage
- [MEMC] …/what-is-memory
- [MCP] …/tools/model-context-protocol
- [TB] …/toolbox-overview
- [ZIP] …/deploy-hosted-agent-code
- [DH] …/deploy-hosted-agent
- [PUB] …/publish-copilot
- [CON] how-to/connections-add
- [DEC] foundry-models/how-to/use-foundry-models-microsoft-decision
- [RET] openai/concepts/model-retirement-schedule
- [WS] agents/how-to/tools/web-search

Otras fuentes:
- [KSB] learn…/search/agentic-knowledge-source-how-to-blob
- [BLOB] learn…/storage/blobs/versioning-overview
- [WAF] learn…/well-architected/ai/design-principles
- [PAT] learn…/architecture/ai-ml/guide/ai-agent-design-patterns
- [MVP] repositorio del MVP previo (no publicado)
- [CI-med] medición previa de Code Interpreter (no publicada)
- [LEEME] documentación del generador de estimaciones (no publicada)
- [M-A2A] notas de pruebas previas de A2A en Foundry (no publicadas)
- [M-BP] criterio interno de diagramas con buenas prácticas (no publicado)

Lo que no tiene fuente va marcado SUPUESTO.

---

## 1. Principios de diseño

1. **Todo lo que se ejecuta vive en Foundry y Azure.** El portátil solo sirve para construir y desplegar (decisión de Fernando).
2. **El código transporta, decide y recalcula; los modelos proponen.** Medido en el MVP: «0 de 22 envíos alterados en B frente a 2 de 5» [MVP]. Decision-1 puede bloquear o escalar, pero **nunca aprobar**.
3. **Fallar en alto.** El código de salida es el veredicto. Un servicio que no responde, una variable vacía o una respuesta fuera de esquema dejan el proyecto en BLOQUEADO, con el motivo visible.
4. **Un único escritor de lo compartido: el escriba, que es código.** La puerta no tiene ninguna credencial de escritura: los verificadores son de solo lectura.
5. **Un proyecto por turno.** Cada turno usa una SAS limitada al contenedor del proyecto, cada delegación un contextId nuevo, y la memoria de cada cliente va separada de la genérica.
6. **Listas blancas que fallan cerrado.** Se aplican a `allowed_tools`, a la especificación OpenAPI recortada, a las rutas REST, a los dominios de salida y a los campos de cada propuesta. Tras un rechazo se termina el turno.
7. **Límites sagrados con versión exacta, comprobados antes de cada delegación.** Se aplican las trampas de la plataforma ya medidas: el rol que necesita quien llama por A2A, una sola conexión de App Insights por proyecto y la caducidad de Code Interpreter.
8. **Cada vía de escape lleva una condición comprobada contra los datos, y la variabilidad se mide por dos caminos.** Nada se da por cierto sin comando y salida pegados.

## 2. Arquitectura objetivo

```
Fernando ──(playground / POST /responses; Teams «Just you» tras prueba)──┐
                                                                          v
┌──────────────── Proyecto Foundry (suscripción de pruebas, UE) ───────────────┐
│ ofa-coordinador [HOSTED, ZIP bundled con hashes, sin MAF]                    │
│  ├ intérprete: cabecera≠texto pegado → gramática → Decision-1 → «SÍ»         │
│  ├ máquina de estados por proyecto · ensamblador de briefs (sha256)          │
│  ├ escriba: único escritor (SAS del contenedor activo, If-Match ETag)        │
│  ├ puerta: módulo puro, SAS de solo lectura, código de salida = veredicto    │
│  └ generadores: generar_estimacion.py --verificar · diagrama (stdlib)        │
│   │ A2A v1.0 (versión fijada), contextId nuevo por delegación                │
│   │ Foundry Agent Consumer con ámbito POR AGENTE destino                     │
│ ┌─┴─────────┬────────────┬────────────┬────────────┬────────────┐            │
│ facilitador investigador  experto-ms   arquitecto   estimador  verificador   │
│ [prompt]    [prompt]      [prompt]     [prompt]     [prompt]   [prompt,      │
│             MCP Learn     MCP Learn    MCP Learn               otro modelo]  │
│             AI Search(q)  OpenAPI      AI Search(q)                          │
│             Web (saneado) RetailPrices                                       │
│ Decision-1 (systemone) ← solo el código · App Insights (1 conexión)          │
└──────────────────────────────────────────────────────────────────────────────┘
   │ salida HTTP solo a: *.blob.core.windows.net, learn.microsoft.com,
   │ prices.azure.com, el endpoint de Search (lista blanca en el código)
   v
Storage (versionado + borrado temporal + diagnóstico a Log Analytics)
 ├ sistema/     rate-card, plantilla, generador, catálogo de prácticas,
 │              manifiesto (lo sube Fernando; el coordinador solo lee)
 ├ compartido/  lecciones-globales.jsonl (anonimizadas)
 ├ agentes/<a>/ memoria genérica
 └ cli-<cliente>/<codigo>/  .gsd en JSON, memoria/<a>, history/, salida/
AI Search Basic (región UE distinta de Sweden) · índice conocimiento-interno
 (Foundry IQ; ingesta por clave; consulta con query key)
```

El escriba y la puerta viven dentro del coordinador mientras no se demuestre que un hosted puede ser destino A2A. [A2A] solo lo documenta para prompt agents: «you can expose them as A2A endpoints». Quedan fuera los workflows del portal (se retiran el 01-12-2026) y los connected agents (se retiran el 31-03-2027), según el paquete.

## 3. Catálogo de agentes

**Común a los siete agentes con modelo:**
- Prefijo `ofa-`.
- Identidad Entra propia: «Newly created agents receive a unique Entra Agent Blueprint and Entra Agent Identity» (migrate-agent-applications).
- `text.format` estricto, con `propuestas[{destino: PROPIA|CLIENTE|PROYECTO|GLOBAL, regla, motivo, aplica_a}]`.
- Los prompt agents no guardan nada entre llamadas [MVP]. Toda la memoria llega inyectada en el brief y delimitada como DATO, en estos bloques: `MEMORIA_PROPIA` (genérica), `MEMORIA_CLIENTE` (solo la del proyecto activo), `LECCIONES_GLOBALES` (filtradas por `aplica_a`), `LECCIONES_PROYECTO` y `ESTADO_PROYECTO` (solo lectura).
- Memoria genérica: a lo sumo 50 entradas de 600 caracteres como máximo (SUPUESTO).
- **Prohibido a todos:** escribir en Blob o en memoria, llamar a otro agente por A2A, poner horas o tarifas en texto para el cliente y usar datos de otro proyecto.

**Modelos** (comprobado por el manifiesto, §8):
- gpt-5.6-luna se retira el 2028-01-11 [RET]. Es el modelo de los generadores.
- Verificador: gpt-6-luna si en el paso 0 se confirma una fecha de retirada posterior al fin del proyecto más 12 meses. Si no, gpt-5.6-terra, que se retira el 2028-01-11 [RET]; su despliegue está NO VERIFICADO y, al ser de la misma familia, la independencia baja: se declara como riesgo residual.
- DeepSeek-V4-Pro queda descartado: ciclo de vida de 12 meses y fuera de la tabla de herramientas.

### 3.1 ofa-coordinador
- **Tipo:** hosted, ZIP `python_3_13` [ZIP].
- **Modelos:** gpt-5.6-luna solo para extraer valores con `json_schema` [MVP modelo.py:89-97]; Decision-1 para clasificar.
- **Rol:** único interlocutor de Fernando; orquesta, guarda y verifica.
- **Funciones:**
  1. intérprete (§5);
  2. máquina de estados;
  3. briefs con `sha256_enviado` [MVP a2a.py:219];
  4. delegaciones con un máximo de 3 intentos;
  5. escriba, puerta y generadores;
  6. órdenes TRAZA y PREGUNTAR.
- **Herramientas:**
  - A2A saliente solo hacia los 6 agentes `ofa-`;
  - Decision-1 por REST;
  - Blob con SAS de turno;
  - Search por REST con la query key (respaldo, §3.3);
  - HTTP de salida restringido a la lista blanca de §2.
- **Prohibido:**
  - ejecutar órdenes sin confirmar;
  - aceptar `DECISION`, STOP o un importe por encima del umbral configurado sin hash [MVP verificar_paquete.py:19-21];
  - llamar a rutas REST de escritura de agentes (lista blanca de rutas que falla cerrado, como la guarda de prefijos de [MVP lib/foundry.py:196-200]);
  - pasar al modelo la conversación de Responses: solo recibe el mensaje actual.
- **Memoria propia:**
  - genérica en `agentes/ofa-coordinador/` (preferencias de orquestación de Fernando);
  - por cliente en `cli-*/<codigo>/memoria/coordinador.jsonl`.
- **Salida:** `ESTADO`, `SIGUIENTE PASO`, rutas y SHA-256. Sin importes en el texto.
- **Cierre:** puerta en 0, REVISADO y APROBAR ENTREGA (§5).
- **Sustituye a:** pm-orchestrator, la parte determinista de plan-checker y la parte de procedencia de fact-checker.

### 3.2 ofa-facilitador
- **Tipo y modelo:** prompt, gpt-5.6-luna.
- **Rol:** decidir si el brief basta y formular lo que falta.
- **Funciones:**
  1. extraer requisitos (REQ v1, v2 y fuera de alcance) con la cita literal;
  2. preguntas de opción múltiple;
  3. preguntar dónde están los usuarios finales (decide el marco normativo) y qué identidad gobierna los documentos de origen.
- **Herramientas:** ninguna.
- **Memoria propia:** genérica, con patrones de preguntas que funcionaron por tipo de sistema de IA; por cliente, las aclaraciones de ese cliente.
- **Compartida:** lecciones con `aplica_a` igual a «suficiencia».
- **Salida:** `{requisitos[{id, texto, cita}], preguntas[{texto, opciones[]}]}`. El código comprueba cada cita. Decision-1 responde `noul` a «¿está especificado?», con «cannot tell» [DEC]; un «no» o una abstención generan una pregunta.
- **Cierre:** 0 preguntas abiertas, o ASUMIR de Fernando.
- **Sustituye a:** discuss-facilitator.

### 3.3 ofa-investigador
- **Tipo y modelo:** prompt, gpt-5.6-luna.
- **Rol:** contexto del cliente, del sector y normativo, siempre con fuente.
- **Funciones:**
  1. normativa según la ubicación de los usuarios;
  2. referencias internas de la empresa en Foundry IQ;
  3. contexto público.
- **Herramientas:**
  - MCP de Learn, `allowed_tools=[microsoft_docs_search, microsoft_docs_fetch]`;
  - herramienta Azure AI Search sobre `conocimiento-interno`, con conexión por query key;
  - Web Search, que recibe solo un brief saneado por el código: sin cliente, sin términos sensibles y sin texto del pliego. Motivo: «The Microsoft Data Protection Addendum doesn't apply… outside compliance and geographic boundaries» [WS].
  - Si el paso 0 no confirma AI Search o Web Search con gpt-5.6-luna, el código consulta Search por REST e inyecta los resultados, y Web queda desactivado.
- **Prohibido:** NotebookLM, AWS y GCP (hasta que Fernando decida) y datos del cliente en las consultas.
- **Memoria propia:** genérica, con fuentes fiables por sector y normativa; por cliente, hallazgos ya validados.
- **Salida:** `hallazgos[{afirmacion, url, cita_literal, fecha, origen: LEARN|IQ|WEB}]`.
- **Cierre:** la puerta vuelve a comprobar cada cita. En proyectos reales se rechaza `origen=WEB`.
- **Sustituye a:** researcher.

### 3.4 ofa-experto-ms
- **Tipo y modelo:** prompt, gpt-5.6-luna.
- **Rol:** servicio, SKU, disponibilidad en la UE, fecha de retirada y precio de catálogo.
- **Funciones:**
  1. evaluar los servicios candidatos (en paralelo con la investigación);
  2. poner precio a cada nodo de servicio del diagrama (estado PRECIO_NODOS).
- **Herramientas:**
  - MCP de Learn (las 3 herramientas, revalidadas con `tools/list` al desplegar, porque el README dice «Do not hard-code tool names»);
  - OpenAPI recortada a `GET /api/retail/prices`, anónima.
- **Prohibido:** inventar precios sin `url_precio`.
- **Memoria propia:** genérica, con trampas vividas de SKU y regiones (por ejemplo, Sweden sin servicios nuevos de Search); por cliente, las restricciones de región del cliente.
- **Salida:** `componentes[{nodo_id, servicio, sku, region, despliegue, precio_unitario, url_precio, fecha_retirada, url, cita}]` y solo `brief_id`, sin eco del brief. Así se cierra el bloqueo de I1.9 [MVP ARREGLOS.md].
- **Cierre:** el verificador sin ningún DISCREPA y la puerta, regla 10.
- **Sustituye a:** microsoft-expert.

### 3.5 ofa-arquitecto
- **Tipo y modelo:** prompt, gpt-5.6-luna.
- **Rol:** diseñar la arquitectura de cualquier sistema de IA.
- **Funciones:**
  1. elegir el patrón: «Use the lowest level of complexity that reliably meets your requirements» [PAT];
  2. componentes, flujos, requisitos no funcionales y fases que cubran todos los REQ v1;
  3. elegir buenas prácticas del catálogo curado.
- **Pilares (lista cerrada):** Desarrollo y Mantenibilidad (los dos se mapean a Operational Excellence, pero cada uno con nombre propio), Escalado (Performance Efficiency), Seguridad (Security), Coste (Cost Optimization) y Fiabilidad (Reliability) [WAF].
- **Catálogo:** `sistema/catalogo-practicas.json`, con hash, URL de Learn y cita para cada práctica. El arquitecto elige por id y solo redacta cómo se aplica: «sin dejar que el LLM las invente… Entre 3 y 5 prácticas por pilar» [M-BP].
- **Herramientas:** MCP de Learn (search y fetch) y AI Search sobre `conocimiento-interno`.
- **Prohibido:** prácticas que no estén en el catálogo; proponer modelos sin fecha de retirada.
- **Memoria propia:** genérica, con los patrones elegidos y el motivo; por cliente, las decisiones de arquitectura de ese cliente.
- **Salida:** `diagrama{nodos[{id, tipo, etiqueta, servicio}], grupos, aristas}`, `practicas[{pilar, id_catalogo, nodo_id, aplicacion}]` y `fases[{fase, req_ids}]`.
- **Entregable:** el código genera SVG (escapado con `xml.sax.saxutils`), `.drawio` y un HTML autocontenido con el diagrama y la banda de prácticas. «El diagrama dentro del documento» [M-BP]. El formato se confirma con Fernando (pregunta 8).
- **Cierre:** puerta, reglas 6 a 8.
- **Sustituye a:** solution-architect.

### 3.6 ofa-estimador
- **Tipo y modelo:** prompt, gpt-5.6-luna.
- **Rol:** horas por perfil y fase de un proyecto de servicios.
- **Funciones:**
  1. desglose por tarea con su justificación;
  2. holgura por tarea según la política de estimación configurada;
  3. un mínimo de horas de gestión del proyecto.
- **Herramientas:** ninguna.
- **Prohibido:** ver tarifas y añadir recargos porcentuales: el precio no lleva recargos.
- **Memoria propia:** genérica, con desviaciones de horas por tipo de tarea; por cliente, supuestos aceptados.
- **Salida:** el JSON de datos del generador, sin importes.
- **Generación:** el coordinador ejecuta `generar_estimacion.py` y `--verificar` en su propio contenedor [MVP estimacion.py:678-703], con `sistema/rate-card.json` montado en la ruta que espera el generador [LEEME] y la plantilla corporativa de estimación [LEEME]. Así se evitan los 20 minutos de caducidad y el fichero con permisos 0600 de Code Interpreter.
- **Cierre:** puerta en 0 y REVISADO.
- **Sustituye a:** estimator.

### 3.7 ofa-verificador
- **Tipo y modelo:** prompt, con el modelo de §3 (distinto del de los generadores).
- **Rol:** contrastar hechos contra las fuentes que el código ya ha descargado.
- **Funciones:**
  1. contrastar cada afirmación con su fuente;
  2. separar el hecho de la redacción.
- **Herramientas:** ninguna.
- **Memoria propia:** genérica, con los tipos de DISCREPA frecuentes; sin memoria de cliente.
- **Salida:** `[{id, veredicto: DISCREPA|OBSERVACION|CONFORME, fuente}]`. Solo DISCREPA bloquea, con un tope de 3 rondas y lotes por debajo de unos 120 s.
- **Sustituye a:** verifier, la parte de hechos de offer-validator y fact-checker.

### 3.8 Validador de coherencia (la puerta)
Es código y no tiene modelo (§6). Sustituye a plan-checker, a offer-validator, a verificar_paquete.py y a boundary-guard.

### 3.9 Escriba
Es código y no tiene modelo. Es el único que escribe. Sigue este ciclo: bandeja, filtro, aprobación, `If-Match` sobre el ETag, relectura, anotación en `registro.jsonl` (solo adición) y archivado.

## 4. Modelo de memoria

| Memoria | Ubicación | Estado | Quién escribe | Aprobación |
|---|---|---|---|---|
| Propia genérica | `agentes/<a>/memoria.jsonl` | Storage GA | Escriba | Fernando + filtro global |
| Propia de cliente | `cli-*/<cod>/memoria/<a>.jsonl` | GA | Escriba | Fernando |
| Lecciones globales | `compartido/lecciones-globales.jsonl` + copia maestra en el repositorio | GA | Escriba | Fernando |
| Lecciones del proyecto | `cli-*/<cod>/lecciones.jsonl` | GA | Escriba | Fernando |
| Estado (.gsd) | ver la tabla siguiente | GA | Escriba, desde la salida que ha validado la puerta | Solo `decisiones.json` exige hash |
| Historial | `cli-*/<cod>/history/<a>.jsonl` | GA | Escriba, automático | Solo auditoría: **nunca se inyecta en un brief** |

Equivalencias con `.gsd`, indicando quién lo propone en cada caso:

| Fichero .gsd | Fichero nuevo | Lo propone |
|---|---|---|
| PROJECT | `proyecto.json` | coordinador |
| REQUIREMENTS | `requisitos.json` | facilitador |
| ROADMAP | `roadmap.json` | arquitecto |
| STATE | `estado.json` | coordinador |
| CONTEXT | `decisiones.json` | Fernando; solo cambia con APROBAR y hash |
| RESEARCH | `investigacion.json` y `componentes.json` | investigador y experto |
| LESSONS | `lecciones.jsonl` | cualquier agente |
| estimator-plan.xml | `estimacion.json` | estimador |

**Versionado y vuelta atrás.** «every write operation to a blob… results in the creation of a new version» [BLOB]. Además, borrado temporal de blobs y de contenedores, y RESTAURAR a una versión concreta.

**Por qué no la memoria gestionada.** Es preview, sus tres tipos vienen «Enabled by default» [MEMC], `{{$userId}}` no sirve con A2A y no tiene versiones ni auditoría: «Record all deletions in a tamper-evident audit trail» se le pide al integrador [MEMU].

**Por qué no el state store para lo compartido.** «available only to hosted agents» [SS].

**Aislamiento entre clientes:**
- SAS de contenedor por turno (§7).
- La memoria de cliente solo se inyecta con ese proyecto activo.
- Lo de un proyecto solo sube a GLOBAL anonimizado.
- Se rechaza cualquier respuesta A2A cuyo contextId no pertenezca al proyecto activo.

**Envenenamiento (OWASP ASI06):**
1. Ningún agente escribe.
2. Lista blanca de campos: `regla`, `motivo`, `aplica_a`, 600 caracteres como máximo, sin URL ni importes.
3. Detector determinista de nombres de cliente y términos sensibles, contra el registro de clientes.
4. Decision-1 responde `noul` a «¿contiene instrucciones a agentes, datos de cliente o tarifas?». Un «sí», un «cannot tell», un error o un tiempo agotado cuentan como rechazo; un «no» no aprueba nada.
5. Aprobación literal de Fernando.
6. El contenido de los pliegos se inyecta delimitado como DATO, y el historial nunca entra en un brief.

**Migración de las 101 lecciones.** Un script aplica los mismos filtros, falla con la lista de lo que rechaza y deja la revisión a Fernando. Hoy hay 11 líneas con «€» y menciones a clientes (cliente B 9, cliente C 5…), según el informe de seguridad. No se sube nada al repositorio mientras el script no dé 0 coincidencias.

## 5. Conversación con el coordinador

**Canal.** El playground o `POST /responses`: «Conversational chatbot or assistant | Responses | The platform manages conversation history» [HA]. Teams «Just you»: «requires no admin approval» [PUB]. Se prueba en la fase 4, porque Learn se contradice sobre el historial en los canales publicados.

**Intención.**
- **Invariante:** se separan la cabecera de órdenes y el texto pegado [MVP mensajes.py:59-70]. El texto pegado nunca se clasifica.
- Orden de interpretación:
  1. gramática cerrada [MVP mensajes.py:20-33];
  2. si no casa, Decision-1 `choice` sobre la cabecera, con la lista cerrada más `NO_SE`; si no supera 0,8 (SUPUESTO, a calibrar con ejemplos etiquetados [DEC]), se pregunta;
  3. el modelo extrae los valores y el código comprueba que sean literales del mensaje;
  4. el coordinador reescribe la orden canónica y solo la ejecuta tras un «SÍ».
- Si Decision-1 falla, el mensaje se trata como abstención y se pregunta a Fernando.
- La confirmación del NDA no se admite por chat mientras Fernando no decida la política de datos.

**Órdenes:**
- ALTA, `PROYECTO <cod>`, ESTADO, SIGUE;
- `REVISAR <fase> «indicación»`: vuelve a esa fase con la indicación como dato e invalida las posteriores;
- `PREGUNTAR «texto»`: responde desde el estado y las fuentes guardadas, sin escribir;
- ASUMIR y ACLARACIÓN;
- `TRAZA <task_id>`: devuelve el envío y la respuesta completos desde el historial;
- `RESTAURAR <versión>`, `ENLACE <fichero>`, APROBAR y RECHAZAR.

**Estados:** `ALTA → SUFICIENCIA → INVESTIGACION∥EXPERTO → ARQUITECTURA → PRECIO_NODOS → VERIFICACION → ESTIMACION → PUERTA → REVISION_VISUAL → APROBACION → CERRADO`, más `BLOQUEADO(intento n/3, motivo)`. Un paso por turno con SIGUE, como en el MVP. El modo background con sondeo se mide en el paso 0 [HA: «Built-in background mode and polling»].

**Aprobaciones:**
- Lecciones y memoria: `APROBAR L-<id> <hash8>`.
- Revisión visual (obligatoria, mirando las tres hojas [LEEME]): Fernando abre el XLSX en Excel y el HTML o `.drawio`, con una lista de comprobación (Montserrat, geometría, títulos, tablas, Gantt, diagrama), y responde `REVISADO <sha8>`.
- Entrega: `APROBAR ENTREGA <sha8>` solo se acepta después de REVISADO.

**Ficheros.** Por defecto, el coordinador da la ruta y el SHA-256, y Fernando descarga desde el portal de Storage (es Contributor). Así no queda ninguna SAS en las trazas. `ENLACE` emite una SAS con política almacenada (revocable), `sp=r`, `spr=https` y 30 minutos como máximo, y se revoca tras el uso. La descarga de ficheros de sesión desde el portátil queda solo para construir y depurar.

## 6. Puertas en la nube

La puerta es un módulo puro: recibe bytes y hashes, usa una SAS de solo lectura y no importa ni el escriba ni el SDK con la clave (hay una prueba que lo comprueba). Recalcula:

1. Que el XLSX lo generó el código y que `--verificar` sale con 0.
2. Horas × tarifa del hash vigente frente a las celdas.
3. Sin recargos porcentuales sobre el precio.
4. Holgura por tarea según la política configurada.
5. Mínimo de horas de gestión del proyecto según la política configurada.
6. Cada REQ v1 dentro de `req_ids` de alguna fase. Es la regla determinista; Decision-1 «¿cubre?» solo puede escalar (código 2).
7. Cada nodo y arista del JSON presente en el SVG, el `.drawio` y el HTML, y sin `<script`, `on*=` ni `javascript:`.
8. Los 6 pilares, cada uno con 3 a 5 ids del catálogo y el nodo citado presente en el diagrama.
9. **Recomprobación de fuentes:** la puerta descarga cada URL (solo learn.microsoft.com) y exige HTTP 200 y la cita literal en el cuerpo. Si no responde, es fallo, nunca se omite.
10. Cada nodo de servicio con su precio; el precio recalculado contra prices.azure.com.
11. Fecha de retirada posterior al fin del proyecto más 12 meses, tanto en los modelos propuestos como en los del propio sistema (manifiesto). Sin fecha, falla.
12. `sha256_enviado` igual al brief que la puerta recompone.
13. Sin marcadores de texto pendiente.
14. Escritura solo en el contenedor activo, comprobada en `registro.jsonl`, y contextId de cada delegación perteneciente al proyecto.
15. Plantilla, generador, catálogo y rate-card con el hash del manifiesto.
16. En proyectos marcados como reales: despliegues DataZoneStandard en la UE y sin hallazgos WEB.

**Veredicto:** 0 pasa, 1 bloquea, 2 es STOP humano. Se prueba con roturas reselladas: en I1 se colaron 3 de 16.

## 7. Seguridad y datos sin pedir nada a TI

**Identidades.**
- El coordinador recibe Foundry Agent Consumer con ámbito de cada especialista. Está probado: Azure lo aceptó el 09-10 con ámbito `…/agents/<agente-de-otro-proyecto>`, y la condición del rol admite `53ca6127` y `eed3b665` [M-A2A].
- Los especialistas no reciben nada.
- Foundry User para el coordinador se da por **necesario** (SUPUESTO de planificación): el acceso implícito solo cubre «Model inferencing… Session storage read and write» [HP]. Se mitiga con la lista blanca de rutas REST.
- Fernando hace todas las asignaciones, porque el modo automático las deniega.

**Conexiones (las crea Fernando a mano):**
1. Storage, «Custom key», con la clave de cuenta. Solo la usa el módulo que firma las SAS de turno, limitadas al contenedor activo, con política almacenada y de minutos de duración. Prueba negativa: leer `cli-B` con `cli-A` activo devuelve 403.
2. SAS de solo lectura para la puerta sobre `sistema/` y `cli-*`, en otra conexión.
3. AI Search con **query key**. Prueba: escribir en el índice devuelve 403. Ingesta de Foundry IQ solo por clave («set aiServices.apiKey», «connectionString» [KSB]).
4. Decision-1 con acceso implícito si el paso 0 lo confirma. Si no, `api-key` en una conexión, declarada como riesgo porque abre toda la cuenta.

**Secretos.** `${{connections…}}` «injects the resolved value as a plain environment variable», y si falta, «the variable is empty» [DH]. Se acepta por escrito que el secreto vive en el entorno del proceso y no en la definición. Al arrancar, el coordinador:
1. lee la variable;
2. la borra de `os.environ`;
3. comprueba que no esté vacía;
4. hace una llamada de prueba de solo lectura;
5. si algo falla, se niega a trabajar.

Nunca se vuelca el entorno a las trazas. El marcador con despliegue por ZIP se prueba en el paso 0.

**Rotación.** Fernando regenera key2, actualiza la conexión, termina las sesiones activas, comprueba que la clave antigua devuelve 403 y regenera key1.

**Trazas.** App Insights con contenido, sin protectGenAISensitiveData. Cortan a 1.024 caracteres, así que el contenido completo se ve con TRAZA. Paso 0: comprobar que Fernando ve el contenido en el portal sin roles nuevos.

**Tenant compartido.** «Project members provided with Log Analytics Reader… can view trace data» [DH], y hay 9 identidades con Owner o Contributor (paquete). Por eso, hasta que Fernando decida:
- datos sintéticos;
- **tarifa sintética**;
- sin indexar contenido interno real de la empresa;
- Storage con diagnóstico hacia Log Analytics.

**Residencia de datos.** El manifiesto guarda el SKU de cada despliegue. Paso 0: comprobar el SKU de Decision-1.

**OpenCode.** Condición de entrada de la fase 1: Fernando rota las claves del cliente D, GCP, AZURE_FOUNDRY_KEY y NVIDIA. La prueba es la clave antigua devolviendo 401 o 403, con comando y salida pegados. `opencode serve` va con contraseña o apagado.

## 8. Versionado

**Repositorio** (la ubicación la decide Fernando):
- `agentes/<n>/instructions.md`, `metadata.yaml` y `humo.jsonl` (patrón ElBruno);
- `registro.yaml` (modelo, herramientas, esquema, tarjeta, memoria);
- `coordinador/` (ZIP `bundled` con wheels y sus hashes en el manifiesto, en vez de `remote_build` sin hashes);
- `sistema/`.

**Despliegue.** Solo crea versión si hay diferencias, relee y compara [MVP desplegar.py:289-306,486-530]. Solo escribe en `ofa-*`.

**Manifiesto** (lo sube Fernando a `sistema/`): agente:versión, SHA de las instrucciones, `/versions/{v}` de la toolbox, despliegue con SKU y fecha de retirada, protocolo A2A 1.0 y hashes. Se comprueba al desplegar y **antes de cada delegación**, y si no casa, BLOQUEADO. Si la identidad no puede leer las definiciones, queda como riesgo residual declarado. El cliente A2A fija la versión 1.0 y falla si la tarjeta del destino no la anuncia.

**Vuelta atrás.** `version_selector` a la versión anterior, el ZIP anterior por SHA y la versión anterior del blob.

## 9. Hoja de ruta

Días-agente base × 1,3 por las rondas de Codex (SUPUESTO), sin contar los días de espera por Fernando.

| Fase | Días | Contenido | Aceptación | Decide Fernando |
|---|---|---|---|---|
| 0a | 3 | Lo que el agente prueba solo, con datos sintéticos: hosted como destino A2A; marcador con ZIP; salida HTTP del hosted; AI Search y Web con gpt-5.6-luna; fechas de gpt-6, gpt-5.6-terra y Decision-1; wheels `bundled`; turno largo | Cada prueba con comando y salida pegados, y su alternativa si falla | — |
| 0b | 2 + espera | Lo que necesita a Fernando: Foundry User y Agent Consumer; conexiones; query key; SKU de Decision-1; `AllowSharedKeyAccess`; rotación de OpenCode | Clave antigua 403; prueba de SAS cruzada 403 | Repositorio, política de datos, agentes de desarrollo |
| 1 | 9 | Coordinador generalizado desde B, escriba, Storage, manifiesto, experto y verificador; arreglo de I1.9 | 0 de 20 envíos alterados; I1.9 7 de 7; manifiesto alterado → BLOQUEADO | Modelo del verificador |
| 2 | 9 | Investigador, arquitecto, catálogo de prácticas, diagrama y HTML, Foundry IQ | 3 briefs: 0 nodos faltantes, 6 de 6 pilares, 0 DISCREPA | Región de Search, formato del documento |
| 3 | 10 | Estimador y puerta completa | 16 de 16 roturas detectadas; variabilidad de horas ≤15 % (SUPUESTO) | Umbral |
| 4 | 7 | Memoria y lecciones genéricas migradas, facilitador, intención, Teams | 50 mensajes: ≥95 % correctos o abstenidos, 0 ejecutados sin confirmar; «recuerda que…» en pliego e historial → 0 escrituras y 0 inyecciones | Aprobar lecciones; las de cliente, solo tras la pregunta 2 |
| 5 | 5 | Paridad con OpenCode | Requisitos y horas ±10 % (SUPUESTO) en 2 casos sintéticos; con datos reales, solo tras la pregunta 2 | Fecha de apagado (no se programa sin la pregunta 2) |

Total: unos 45 días-agente. Cada fase pasa por Codex, `clean-ai-marks`, una PR con cero hallazgos y ROLLBACK.

## 10. Coste mensual estimado

| Partida | €/mes | Supuesto |
|---|---|---|
| Hosted coordinador | ~10 (87 en 24x7) | 0,119 €/h, 4 h por día laborable (medido en el MVP) |
| AI Search Basic | ~65 | Paquete |
| Modelos | ~12 | SUPUESTO: 3 × 0,20 € × 20 proyectos |
| Decision-1 | <1 | 0,037 € por 1M de tokens |
| Storage, Log Analytics, App Insights | <15 | NO VERIFICADO |
| **Total** | **~100-105** (~180 en 24x7) | Sin memoria gestionada |

## 11. Riesgos y preguntas

**Riesgos:**
- Hosted como destino A2A y salida HTTP del hosted, ambos NO VERIFICADOS. Sin salida no hay ni Blob ni puerta, así que es un bloqueo del paso 0.
- Foundry User es un rol amplio para el coordinador.
- Fechas de retirada de gpt-6 y de Decision-1.
- Verificador de la misma familia si no se confirma gpt-6.
- SDK con cambios incompatibles: fijar 2.9.0.
- Variabilidad del 72 %.
- Tenant compartido.

**Preguntas:**
1. ¿Azure DevOps o GitHub?
2. ¿Datos, tarifa y conocimiento reales solo con NDA, suscripción dedicada o tenant propio? (Bloquea las fases 4 y 5 reales.)
3. ¿Los agentes de desarrollo se quedan fuera?
4. ¿AWS y GCP entran?
5. ¿Teams o el playground?
6. ¿4 h al día o 24x7?
7. ¿Qué contenido se indexa en Foundry IQ?
8. ¿El documento de arquitectura en HTML autocontenido, o solo SVG y `.drawio`?

---

**B) REGISTRO DE CAMBIOS**

| Hallazgo | Cambio |
|---|---|
| SEG-BLOQ procedencia URL / coordinador «sin Web» | Recomprobación en la puerta (§6.9) con lista blanca de salida (§2); se quita «sin MCP ni Web» |
| VIA-BLOQ / ENC revisión visual | Estado REVISION_VISUAL y `REVISADO <sha8>` (§5) |
| ENC-BLOQ fichas incompletas | Plantilla única con memoria propia genérica y de cliente en las 7 fichas (§3) |
| ENC-BLOQ pilares y catálogo | 6 pilares con nombre propio, catálogo curado por id, 3-5 por pilar (§3.5, §6.8) |
| SEG secretos en entorno / VIA menor | Se acepta por escrito; borrado de `os.environ`, comprobación de no vacío, prueba de lectura, rotación con fin de sesiones (§7) |
| SEG aislamiento entre clientes, clave de cuenta | SAS por contenedor y turno, prueba de 403 (§7) |
| SEG Decision-1 como control | Solo bloquea o escala; error = rechazo (§4, §6.6) |
| SEG memoria propia global | Separación genérica / cliente con filtro global (§4) |
| SEG historial | Nunca se inyecta; prueba (§4, §9) |
| SEG contextId | Nuevo por delegación y rechazo de los ajenos (§4, §6.14) |
| SEG Web Search | Brief saneado; WEB rechazado en proyectos reales (§3.3) |
| SEG/VIA manifiesto | Antes de cada delegación; versión de A2A fijada (§8) |
| SEG plan B Foundry User / VIA Foundry User obligatorio | Requisito con lista blanca de rutas; query key para Search; Decision-1 implícito o clave como riesgo (§7) |
| SEG/VIA tarifa en tenant | Tarifa sintética; sin conocimiento real; pregunta 2 ampliada |
| SEG/VIA despliegue UE | SKU en el manifiesto, §6.16 |
| SEG rotación OpenCode | Condición de entrada de la fase 1 con prueba de 403 |
| VIA puerta en el coordinador / ENC verificadores de solo lectura | Módulo puro con SAS de solo lectura; `sistema/` lo sube Fernando |
| VIA/ENC modelos | DeepSeek descartado; árbol cerrado del verificador; fechas de los modelos del sistema en el manifiesto (§3, §6.11) |
| VIA herramientas no probadas / ENC fase 0 | Pruebas en la fase 0a con su alternativa |
| VIA ingesta de Foundry IQ | Solo por clave [KSB] |
| VIA/ENC fases 4-5 sin datos reales | Condicionadas a la pregunta 2 |
| VIA esfuerzo | 25 → ~45 días-agente; paso 0 partido |
| ENC entregable de arquitectura | HTML con SVG y banda de prácticas; pregunta 8 |
| ENC iteración | REVISAR, PREGUNTAR, ASUMIR, ACLARACIÓN |
| ENC .gsd | Tabla de equivalencias |
| ENC trazas | TRAZA desde el historial; prueba en el portal |
| Menores | Migración de lecciones por script; cabecera ≠ texto pegado; SAS revocable y ruta por defecto; escapado del SVG; `bundled` con hashes y registro de escrituras; modo SIGUE; destino de las propuestas; rate-card única y plantilla corporativa; sin descarga local; PRECIO_NODOS |

**C) HALLAZGOS RECHAZADOS**

- **Ninguno se rechaza por completo.** Hay dos aceptaciones parciales:
  1. **SEG («si hace falta Foundry User, separar el escriba y la puerta en un hosted propio»).** Queda condicionado al paso 0, porque [A2A] solo documenta los prompt agents como destino («you can expose them as A2A endpoints»). Mientras tanto se mitiga con la puerta como módulo puro de solo lectura y con la lista blanca de rutas.
  2. **SEG («el coordinador no debe escribir SAS en el texto»).** Se cumple por defecto con la ruta y el hash, y la descarga se hace en el portal. La SAS queda solo bajo `ENLACE`, revocable, porque Fernando necesita alguna forma de abrir el fichero sin nada local.
- **VIA («la contradicción ABAC ya está resuelta»).** Se acepta y se quita de los riesgos. Evidencia: [M-A2A] «Puede asignar exactamente dos roles: Foundry User (`53ca6127…`) y Foundry Agent Consumer (`eed3b665…`)» y «Azure lo aceptó» con ámbito por agente (09-10).
