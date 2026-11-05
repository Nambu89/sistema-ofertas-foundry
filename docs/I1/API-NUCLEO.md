# API del núcleo portable de preventa (I1, papel P)

Fecha: 08-10-2026. Alcance: `sandbox/preventa_run.py`, `sandbox/preventa_api.py` y `sandbox/nucleo/esquema.py`.
Objetivo: que la opción B (coordinador como hosted agent, sin Microsoft Agent Framework) reutilice el
núcleo **sin tocarlo**. No cambia el comportamiento en el sandbox de Code Interpreter: mismos valores
por defecto, mismas salidas y mismos códigos de salida (evidencia de paridad en la sección 6).

## 1. Las tres capas

| Capa | Dónde | Qué sabe |
|---|---|---|
| 1. Arranque del sandbox | `preventa_run.py`: `es_local`, `candidatos`, `preparar_sandbox`, `LOCALIZADORES` | Lo único que conoce `/mnt/data`, los `file_id` y el sufijo `<file_id>-<nombre>`; copia `nucleo_<modulo>.py` a la carpeta de la aplicación y comprueba el manifiesto (P0). |
| 2. Carpetas y subcomandos | `preventa_run.py`: `Entorno`, `cmd_*`, `_despachar` | Reciben un `Entorno` y piden ficheros con `env.buscar(nombre)`; no saben cómo están montados. |
| 3. CLI y API | `preventa_run.main` y `preventa_api.py` | Las dos llaman a `_despachar(argv, env)`. |

`nucleo/esquema.py` ya no busca en `/mnt/data`: si no hay `esquemas/` en el repositorio, usa el
localizador que le fija el arranque (`esquema.configurar(env.unico_montado)`), que en el sandbox busca
`esquema_<nombre>.json` por sufijo en `/mnt/data`, como antes.

## 2. Carpetas: argumento, variable de entorno y valor por defecto

Precedencia: argumento > variable de entorno > valor por defecto del modo. Un valor vacío o con solo
espacios cuenta como no fijado (LES-G-076). El modo es *sandbox* si junto a `preventa_run.py` no está
`nucleo/estado.py`, y *local* si está.

| Carpeta | Opción CLI | Variable | Sandbox (por defecto) | Local (por defecto) |
|---|---|---|---|---|
| Trabajo (`estado.json`, `entrada/`, `briefs/`, `consolidados/`, `salida/`, `fuentes/`) | `--trabajo` | `PREVENTA_TRABAJO` o `PREVENTA_RAIZ` | `/mnt/data/preventa` | `<datos>/preventa` |
| Datos (adjuntos y ficheros montados) | `--datos` | `PREVENTA_DATOS` | `/mnt/data` | carpeta actual |
| Aplicación (contiene el paquete `nucleo`) | `--app` | `PREVENTA_APP` | `/tmp/preventa/app` (o `<tmp>/app`) | carpeta de `preventa_run.py` |
| Temporales del generador (`<tmp>/base`) | `--tmp` | `PREVENTA_TMP` | `/tmp/preventa` | `/tmp/preventa` |
| Montaje (cómo se buscan ficheros en datos) | `--montaje` | `PREVENTA_MONTAJE` | `sufijo` | `sufijo` |

- Las opciones de carpetas van **antes** del subcomando:
  `python preventa_run.py --trabajo /srv/w --datos /srv/d --montaje exacto estado`.
  Detrás del subcomando el parser las rechaza (rc 2), para que nadie crea que se han aplicado.
- `sufijo`: vale el nombre exacto o `<lo que sea>-<nombre>` (montaje de Code Interpreter).
  `exacto`: solo el nombre exacto; un fichero con `file_id` no se ve. Debe haber exactamente uno o es error.
- Fallan en alto, con rc 2 y el bloque estado, sin guardar nada: `PREVENTA_TRABAJO` y `PREVENTA_RAIZ`
  con valores distintos, un montaje desconocido o una opción repetida o vacía.
- `--app` debe ser la carpeta desde la que se importa `nucleo`; si el proceso ya lo tiene cargado desde
  otra, el arranque falla (rc 4, `SIN_NUCLEO`). En modo sandbox, `preparar_sandbox` borra y rehace
  `<app>/nucleo` y deja la marca `<app>/.preventa-app`. **Se niega** (error de P0, sin borrar nada) si la
  carpeta de la aplicación contiene algo más que `nucleo` y la marca, o un `nucleo/` sin la marca, es
  decir, uno que no copió él.
- En modo local, los ficheros de configuración siguen saliendo de `PREVENTA_CATALOGO`,
  `PREVENTA_RATE_CARD`, `PREVENTA_GENERADOR` y `PREVENTA_PLANTILLA` (o de sus rutas del repositorio).
  En modo sandbox, de `datos` con el montaje elegido.

## 3. API de biblioteca (`sandbox/preventa_api.py`)

```python
import sys; sys.path.insert(0, "<repo>/sandbox")      # o importar preventa_api con sandbox/ en sys.path
import preventa_api as P

env = P.abrir("/srv/trabajo", datos="/srv/adjuntos")   # montaje: argumento > PREVENTA_MONTAJE > "exacto"
r = P.iniciar(env, cliente="…", codigo_cliente="KELVARA", seqof="001", titulo="…",
              transcripcion="transcripcion.txt", sensibles=["…"], nda_confirmado=True)
if not r.ok:
    print(r.error["tipo"], r.error["mensaje"], r.error["errores"])
print(r.siguiente_paso)
```

`abrir(trabajo=None, *, datos=None, app=None, tmp=None, montaje=None) -> Entorno` resuelve las
carpetas con la misma precedencia de la sección 2 y carga el núcleo. La única diferencia con la CLI es
el montaje por defecto: si no se indica ni hay `PREVENTA_MONTAJE`, la API usa `exacto` (sin file_ids) y
la CLI `sufijo` (el del sandbox). Lanza la excepción del arranque si
el núcleo no se puede cargar. Los errores de configuración salen en cada resultado (rc 2).

Cada función recibe primero la **carpeta**: un `Entorno` de `abrir()` o la ruta de la carpeta de trabajo,
que se abre con los valores por defecto. Los argumentos son los de la CLI, con nombre:

| Función | Subcomando | Argumentos con nombre |
|---|---|---|
| `entorno(c)` | `entorno` | — |
| `iniciar(c, …)` | `iniciar` | `cliente`, `codigo_cliente`, `seqof`, `titulo`, `transcripcion`, `sensibles`, `nda_confirmado=False` |
| `suficiencia(c, …)` | `suficiencia` | `requisitos`, `aclaraciones=()` |
| `asumir(c, …)` | `asumir` | `campo`, `valor` |
| `enrutar(c)` | `enrutar` | — |
| `registrar_experto(c, …)` | `registrar-experto` | `respuesta`, `experto="azure"` |
| `registrar_fallo(c, …)` | `registrar-fallo` | `fase`, `error`, `hipotesis` |
| `consolidar(c, lotes=False)` | `consolidar [--lotes]` | `lotes` (I1.1: imprime los lotes pendientes) |
| `registrar_verificacion(c, …)` | `registrar-verificacion` | `respuesta` |
| `anexo_consumo(c)` | `anexo-consumo` | — |
| `estimar(c, …)` | `estimar` | `aplicar_ajuste=None` (el núcleo compone siempre la entrada desde `tareas_propuestas` y rechaza cualquier otra, P6f; sin `entrada=` desde los arreglos de I1.4) |
| `paquete(c)` | `paquete` | — |
| `decision(c, …)` | `decision` | `linea` |
| `estado(c, …)` | `estado` | `como_json=False`, `turno_nuevo=False` (`--turno-nuevo`, EA-1, I1.4) |
| `restaurar(c, …)` | `restaurar` | `zip` (Paquete o Relevo, I1.1) **o** `estado` y `relevo` juntos (JSON del relevo sueltos, EA-5, I1.4) **o** `estado` y `manifiesto` juntos (forma antigua); nombres de adjunto en datos; excluyentes, `ValueError` si se mezclan |
| `ejecutar(c, argv)` | cualquiera | argumentos de CLI ya formados, sin opciones de carpetas |

`SUBCOMANDOS` mapea el nombre de CLI a su función. Las rutas de `requisitos`, `respuesta`, `entrada` y
las aclaraciones son relativas a la carpeta de trabajo (como en la CLI); `transcripcion`, `estado` y
`manifiesto` son nombres de adjunto en la carpeta de datos. Los valores se pasan como `--opcion=valor`,
así que un valor que empiece por guion no se confunde con una opción.

### Resultado

`ResultadoNucleo` (inmutable):

| Campo | Contenido |
|---|---|
| `subcomando` | nombre de CLI |
| `rc` | 0 bien; 1 regla incumplida o pendiente (p. ej. suficiencia incompleta, STOP); 2 entrada no válida; 3 transición no permitida; 4 integridad rota; 5 inesperado (§11.1) |
| `ok` | `rc == 0` |
| `estado` | estado final, el mismo que describe el bloque estado (copia independiente; `None` sin alta) |
| `salida` | todo lo que la CLI habría impreso, bloque estado incluido |
| `error` | `{"tipo", "mensaje", "errores"}` si hubo excepción del núcleo; `None` si no (un rc 1 sin excepción, como «suficiencia incompleta», trae `error = None`) |
| `siguiente_paso` | texto de la línea `SIGUIENTE PASO OBLIGATORIO` |

Lo que se guarda en `estado.json` lo decide `_despachar` igual que en la CLI (§11.1): la API no guarda
nada por su cuenta.

## 4. Límites conocidos

- **No es reentrante.** La salida se captura redirigiendo `sys.stdout` y el localizador de esquemas es
  global del proceso. Un cerrojo serializa las llamadas dentro del proceso. Dos carpetas de trabajo
  distintas en el mismo proceso funcionan, pero de una en una.
- **Un solo escritor por carpeta de trabajo.** Como con la CLI original, dos procesos que muten a la vez
  la misma carpeta leen el mismo `estado.json` y gana la última escritura (la escritura atómica evita un
  fichero a medias, no la pérdida del cambio anterior). La opción B debe dar una carpeta de trabajo por
  solicitud y serializar los subcomandos de cada solicitud (cola o cerrojo por carpeta).
- La puerta real sigue siendo `verificar_paquete.py` en local: la API no añade controles.
- `abrir()` en modo sandbox rehace `<app>/nucleo` en cada llamada (como cada turno de Code Interpreter).
- Cambian los SHA-256 de `preventa_run.py` y `nucleo_esquema.py`: el próximo despliegue debe regenerar
  `manifiesto.json` con `desplegar.py` (papel D). La versión A desplegada no se toca y sigue con sus
  copias.

## 5. Cómo lo reutiliza la opción B

1. El hosted agent lleva `sandbox/preventa_run.py`, `sandbox/preventa_api.py`, `sandbox/nucleo/` y
   `esquemas/` con la estructura del repositorio (así `nucleo.esquema` encuentra `esquemas/`), más el
   catálogo, la tarifa, el generador y la plantilla canónicos, sin modificar, apuntados con
   `PREVENTA_CATALOGO`, `PREVENTA_RATE_CARD`, `PREVENTA_GENERADOR` y `PREVENTA_PLANTILLA`.
2. Por cada solicitud: una carpeta de datos con los adjuntos guardados con su nombre (sin file_id) y una
   carpeta de trabajo propia; `env = preventa_api.abrir(trabajo, datos=datos)`.
3. Cada fase llama a su función y decide con `rc`, `error` y `siguiente_paso`; el texto de `salida` es el
   mismo que hoy ve el modelo en Code Interpreter.
4. `verificar_paquete.py` sigue siendo la puerta, en local, sobre el ZIP de `salida/`.

No hace falta tocar `nucleo/` ni `preventa_run.py` para nada de esto.

## 6. Evidencias (08-10-2026)

Carpeta de evidencias: `una nota de trabajo no publicada` (fuera del repositorio).

| Prueba | Resultado |
|---|---|
| Línea base antes del cambio, `.venv` (Python 3.13.11) | 583 pasadas, 9 omitidas (`baseline-pytest-venv313.txt`) |
| Pytest completo, `.venv` (Python 3.13.11) | 598 pasadas, 9 omitidas (`pytest-venv313-completo.txt`) |
| Pytest completo, venv `py311` (Python 3.11.9, `requirements.txt`) | 598 pasadas, 9 omitidas (`pytest-py311-completo.txt`). Una ejecución anterior, lanzada a la vez que otras tres, dio un fallo intermitente (rc 5 en `paquete` dentro de `test_restaurar_rechaza`) que no se reproduce en aislamiento (5 de 5) ni en la suite sola (`pytest-py311-completo-concurrente.txt`) |
| Pruebas del núcleo, venv `py313` limpio (solo stdlib, openpyxl, python-pptx, python-docx, PyMuPDF, pytest) | 261 pasadas; 2 de `test_i1_integracion.py` fallan por no tener `requests` (importan `desplegar`, que no es núcleo) (`pytest-py313-nucleo.txt`) |
| Paridad en sandbox simulado (`sim_paridad.py`: `/mnt/data/<file_id>-<nombre>` con manifiesto real, un proceso por turno, Python 3.11, módulos reales y generador canónico), original frente a nuevo | rc idénticos en los 14 pasos, de `entorno` a `paquete` y `restaurar` (`paridad-rc.txt`); salida idéntica en 13 de 14, normalizando rutas, marcas de hora y los SHA-256 de los ficheros con hora (`paridad-pasos.txt`); `entorno` solo difiere en el SHA-256 de los dos ficheros cambiados; `hash_contenido` idéntico y los 9 ficheros del ZIP iguales salvo las marcas de hora internas de los XLSX y los SHA-256 que las citan (`paridad-zip.txt`) |
| Revisión independiente del código en solo lectura, dos pasadas | `revision-independiente-1.txt` (4 hallazgos: 2 arreglados, 1 de diseño, 1 preexistente documentado) y `revision-independiente-2.txt` (sin hallazgos) |

Nota sobre el simulador: el `esquema.py` original fija `/mnt/data` en su propio código, así que para la
versión original el simulador también redirige `nucleo.esquema.DATOS_SANDBOX`. Con el nuevo no hace
falta, porque el localizador sale del entorno: es justo la dependencia que quita este cambio.

## 7. Cambios de I1.2 (08-10-2026)

La API de `preventa_api` no cambia. Funciones y constantes públicas nuevas del núcleo, con su réplica en la
puerta cuando la hay (contrato en `CONTRATOS.md` §17):

| Módulo | Nuevo | Para qué |
|---|---|---|
| `nucleo/suficiencia.py` | `forma_nubes`, `NUBES_ADMITIDAS`, `PLANTILLAS_NUBES` | Lista blanca de `nubes` (REV-1). Desaparece `otra_nube`. |
| `nucleo/experto.py` | `alias_servicio`, `alias_inequivocos`, `HOMOGLIFOS` | Veto de región por id y por alias inequívoco (REV-2). |
| `nucleo/restaurar.py` | `migrar_sin_canales`, `SECCION_CANALES` | Estado antiguo en EN_ANALISIS sin canales → INFORMACION_INSUFICIENTE (REV-3). |
| `nucleo/textos_cliente.py` | `traducir_skus`, `jerga_tecnica`, `MARCAS_ADMITIDAS`, `repite`, `REFERENCIA` | Textos del cliente sin SKU, sin repeticiones y con referencias compuestas (VERIF-8). |
| `verificar_paquete.py` | `alias_servicio`, `alias_inequivocos`, `NUBES_ADMITIDAS`, `PLANTILLAS_NUBES`, `via_kql`, `VIAS_KQL`, `consultar_kql_v1` | Réplicas con prueba de igualdad; KQL por ARM con `lib/appi.py` y vuelta atrás `PREVENTA_KQL_VIA=v1`. |
| `lib/appi.py` (nuevo, fuera del núcleo) | `consultar`, `filas`, `url_consulta`, `ErrorAppi` | KQL de Application Insights por ARM, sin la audiencia `api.applicationinsights.io`. |

El catálogo montado (`catalogo_componentes.json`) pasa a la versión 3 con el campo `alias`: cambia el
`catalogo_sha256` de los paquetes, así que hay que regenerar ejemplos, `manifiesto.json` y el montaje, y
redesplegar A y B.

## 8. Cambios de I1.4 (10-10-2026)

API de `preventa_api`: `estimar(entrada=None)`, `estado(turno_nuevo=False)` y `restaurar(estado=…, relevo=…)` (tabla
del §3). Funciones y constantes públicas nuevas del núcleo, con su réplica en la puerta cuando la hay (contrato en
`CONTRATOS.md` §19):

| Módulo | Nuevo | Para qué |
|---|---|---|
| `nucleo/estimacion.py` | `componer_entrada`, `horas_pm`, `semanas_fase` | Regla de estimación del 10-10-2026 en el núcleo: PM = máx(8 h, ⌈15 %⌉) y Gantt con los perfiles de cada fase en paralelo (P4). |
| `nucleo/estado.py` | `PASO_ESTIMAR`, `paso_turno_nuevo` | Paso de estimar sin JSON y reescritura del paso al abrir un turno (EA-1). |
| `nucleo/restaurar.py` | `leer_sueltos`, `restaurar_relevo` | Restaurar con `estado.json` y `relevo.json` sueltos (EA-5); el relevo lleva también `procedencia_a2a.json` (P1). |
| `nucleo/paquete.py` | `NOMBRE_PROCEDENCIA`, `SCHEMA_PROCEDENCIA` | Décimo fichero del ZIP en la opción B (P1). |
| `nucleo/verificacion.py` | `CAMPOS_DISCREPA`, `SAAS_TENANT_NOMBRES`, `es_saas_tenant`, `ECO_LINEAS`, `lineas_eco`, `errores_eco` | Campo discutido, SaaS por igualdad y eco por líneas (P3). |
| `nucleo/pptx_revision.py` | `solapes_diagrama`, `formas_de`, `formas_de_arbol`, `medidas_diagrama`, `filas_no_valoradas`, `medidas_consumo` | Diagrama sin solapes y diapositiva 8 que cabe (P2). |
| `nucleo/textos_cliente.py` | `concepto_legible`, `productos_precio`, `titulo_referencia`, `lista_y`, `TEMAS_REFERENCIA` | Conceptos legibles y referencias en castellano (P2). |
| `nucleo/anexo_consumo.py` | `es_saas_sin_precio`, `MOTIVO_SAAS` | SaaS que se licencian aparte (P2). |
| `verificar_paquete.py` | `SAAS_TENANT_NOMBRES`, `CAMPOS_DISCREPA`, `ECO_LINEAS`, `es_saas_tenant`, `lineas_eco`, `errores_eco`, `es_contrato_v2`, `solapes_diagrama_replica`, `formas_diagrama`, `filas_no_valoradas_replica`, `NOMBRE_PROCEDENCIA` | Réplicas con prueba de igualdad (`tests/test_i14_p3_verificacion.py`, `tests/test_i14_p2_replica_solapes.py`) y procedencia de B (`tests/test_i14_puerta_procedencia.py`). |

El esquema del verificador pasa a v3 (`campo` obligatorio): los estados y paquetes anteriores con verificación no
cargan en el núcleo nuevo ni pasan la puerta; hay que regenerar `manifiesto.json`, el montaje de A y el ZIP de B.

## 9. Cambios de I1.5 (11-10-2026)

Sin cambios en la firma de `preventa_api` ni de `preventa_run`. Funciones y constantes públicas nuevas del núcleo, con
su réplica en la puerta cuando la hay (contrato en `CONTRATOS.md` §20):

| Módulo | Nuevo | Para qué |
|---|---|---|
| `nucleo/anexo_consumo.py` | `SIN_MOTIVO`, `MOTIVOS_NO_VALORACION`, `MOTIVO_A_VALORAR`, `es_respuesta_v1`, `motivo_declarado`, `errores_cobertura`, `motivos_para_revisor` | Cobertura de precios: precio o motivo de la lista cerrada por facturable (P, decisión 2). |
| `nucleo/experto.py` | `region_exige_catalogo`, `_filtro_de_plantilla` | REVERIF14-2 (región sin `catalogo_id`) y filtro EXACTO de plantilla en `problemas_precio` (E, decisión 1). |
| `nucleo/estado.py` | `ORQUESTADORES`, `orquestador_actual` | Marca `orquestador` en `estado.json` desde `PREVENTA_ORQUESTADOR` (R, VER14-3). |
| `nucleo/paquete.py` | — | El manifiesto copia `orquestador` de `estado.json`. |
| `nucleo/decision.py` | `comentarios_devuelta` | Comentarios de las DEVUELTA, anonimizados, en el brief de la versión siguiente (R, PR14-6). |
| `nucleo/pptx_revision.py` | `cortes_conectores`, `enrutar` | Conectores en codo por los huecos y comprobación exacta de cortes (D, PR14-3). |
| `nucleo/textos_cliente.py` | `asunciones_estimacion`, `plazo_del_gantt` | Asunciones del XLSX sin jerga y plazo de la prosa tomado del Gantt (D, VER14-8 y VER14-10). |
| `verificar_paquete.py` | `es_contrato_experto_v1`, `nombre_esquema_experto`, `region_exige_catalogo_replica`, `errores_cobertura_replica`, `_cobertura_precios`, `_filtro_de_plantilla`, `cortes_conectores_replica`, `orquestador_declarado` | Réplicas y comprobaciones de la puerta; las pruebas de igualdad están en `tests/test_i15_p_cobertura_puerta.py`, `tests/test_i15_int_replicas.py` y `tests/test_i12_arreglos_precio.py`. |

`respuesta_experto` pasa a v2 (`motivo_no_valoracion` obligatorio) y el catálogo del sandbox admite `plantillas_precio`
y `no_valorables`: hay que regenerar `manifiesto.json`, el montaje de A, la versión del experto y el ZIP de B, y
desplegarlos entre sesiones (un `estado.json` con una respuesta v1 no carga en el núcleo nuevo).

## 10. Cambios de I1.6 (11-10-2026)

Sin cambios en la firma de `preventa_api` ni de `preventa_run`. Funciones y constantes públicas nuevas del núcleo, con
su réplica en la puerta cuando la hay (contrato en `CONTRATOS.md` §21):

| Módulo | Nuevo | Para qué |
|---|---|---|
| `nucleo/experto.py` | `fijar_conceptos`, `errores_volumen_nivel`, `lineas_para_revisor`, `problemas_auxiliar`, `auxiliar_de_filtro`, `plantillas_auxiliar`, `divisor_de`, `niveles_de`, `citas_volumetria`, `estado_volumetria`; `validar_respuesta(…, requisitos=None)` | Decisión 4 (LES-G-100): concepto fijado desde la plantilla, volumen con base y factor, nivel justificado, auxiliar atado a su plantilla y a su lista (P, REV15-1 y REV15-3). |
| `nucleo/anexo_consumo.py` | `precios_que_cubren` | Solo cubre un precio propio con cantidad: ni el auxiliar ni el de referencia (P, REV15-1). |
| `nucleo/nota_revision.py` | — | Apartado 6: supuestos de volumen con su cuenta, precios de referencia, niveles y conceptos sustituidos. |
| `nucleo/verificacion.py` | `_segmento_nivel`, `_segmento_volumen`; `lineas_conservar` puede lanzar `IntegridadRota` por una línea P- sin forma | Líneas del verificador con nivel y base de volumen (integrador, CAMBIOS-I16-E §3.3); REVERIF15-3 (R). |
| `nucleo/brief.py` | `terminos_anonimizacion(alta, personas=None) -> (sensibles, cliente, personas)` | VER15-7: los firmantes son términos sensibles (R). |
| `nucleo/decision.py` | `NOMBRES_DECISIONES` | Quienes firman decisiones (R). |
| `nucleo/pptx_revision.py` | `separacion_conectores` | ARR15-2/D15-4: conectores que se confunden o van pegados a otra forma (D). |
| `nucleo/textos_cliente.py` | `CONCEPTOS_VALORADOS`, `etiquetas_total` | Total «(conceptos valorados)» con filas «No valorado» (D). |
| `verificar_paquete.py` | `es_contrato_experto_v2`, `precios_que_cubren_replica`, `errores_volumen_nivel_replica`, `conceptos_replica`, `auxiliar_de_filtro`, `problemas_auxiliar`, `_decision_4`, `_contrastar_cobertura_i16`, `separacion_conectores_replica`, `juicio_relectura` | Réplicas y comprobaciones de la puerta; pruebas de igualdad en `tests/test_i16_p_puerta.py`, `tests/test_i16_d_replica_separacion.py`, `tests/test_i15_int_replicas.py` y `tests/test_i16_int_catalogo_real.py`. |

`respuesta_experto` pasa a v3 y el catálogo del sandbox exige `concepto`, `impulsor` y `divisor` en cada plantilla: hay
que regenerar `manifiesto.json`, el montaje de A, las versiones del experto y del verificador y el ZIP de B, y
desplegarlos juntos entre sesiones. Sin el catálogo nuevo, el núcleo rechaza todo precio (`plantilla_sin_impulsor`,
falla cerrado); un `estado.json` con una respuesta v2 no carga en el núcleo nuevo.

## 11. Arreglos de I1.6 (12-10-2026)

Sin subcomandos nuevos. Contrato en `CONTRATOS.md` §22.

- `registrar-experto` rechaza (intento T2) un componente del catálogo cuya referencia no es la de su fila
  (`referencia_no_catalogo`, PR16-1), un motivo de no valoración que contradice el catálogo
  (`licencia_con_precio_azure`, `medidor_publico_en_catalogo`, REV16-1) y, en las rondas 2 y 3, un precio ya verificado
  que no se conserva (`conservado_ausente`, `conservado_cambiado`, PR16-3). El mensaje lleva el remedio literal.
- `enrutar` guarda en el brief `conservar_precios` (ronda 2 o 3) y la línea de cada precio conservado lleva la cantidad
  mensual y la base con su factor.
- La nota del revisor añade una línea cuando una fila con plantillas `por_defecto` se valora con otras.
- Funciones nuevas: `experto.errores_referencia_catalogo`, `experto.errores_conservacion`, `experto.lineas_por_defecto`,
  `verificacion.precios_conservar`, `anexo_consumo.medidor_publico_en_catalogo`. Réplicas en la puerta:
  `referencia_catalogo_replica`, `conservacion_replica` y las dos reglas nuevas de `errores_cobertura_replica`.

## 12. Cambios de I1.7 (13-10-2026)

Sin subcomandos nuevos ni firmas de subcomando cambiadas. Contrato en `CONTRATOS.md` §23.

- `registrar-experto` valida la respuesta v4 del modelo, la completa con el catálogo y la instantánea de precios
  montada junto a él (`<id>-precios_instantanea.json` en el Code Interpreter, `recursos/` en el hosted o
  `PREVENTA_PRECIOS`) y guarda la COMPLETADA. Sin instantánea válida, de más de 31 días o que no cubra el catálogo:
  `IntegridadRota` (rc 4) sin sumar intento. Reglas nuevas con su remedio: `plantilla_desconocida`,
  `sin_precio_en_instantanea`, `instantanea_otra_region`, `region_sin_instantanea`, `override_cita_no_literal`,
  `factor_sin_estandar`, `base_no_casa`, `cantidad_fuera_de_rango`, `modelo_retirado`, `modelo_no_disponible`,
  `ciclo_vida_desconocido`, `cliente_sin_cita`, `cita_cliente_no_literal`, `incluido_sin_componente`,
  `incluido_inexistente`, `inclusion_no_declarada`, `arquitectura_desconocida` y `requisito_no_literal` (solo campos de
  dimensionamiento).
- `consolidar` ya no lleva precios ni lote de precios; en las rondas 2 y 3, solo lo no aceptado (PR16-6). `enrutar`
  guarda `conservar_precios` por efecto y `aceptados`. `registrar-verificacion` pasa a OBSERVACION la DISCREPA sobre una
  línea aceptada sin cambios.
- `anexo-consumo` dice «precios consultados el <fecha de la instantánea>» y rechaza una instantánea de más de 31 días.
  `paquete` escribe `montados.precios_instantanea_sha256` y exige que la instantánea montada sea la de la respuesta.
- `decision` con DEVUELTA guarda `version_devuelta`; la versión siguiente lleva «Cambios pedidos en la revisión anterior»
  en la nota y en la diapositiva 2 del PPTX.
- Funciones nuevas: `experto.completar`, `experto.proyectar_modelo`, `experto.analizar_respuesta(…, instantanea, hoy)`,
  `experto.instantanea_valida`, `experto.errores_instantanea`, `experto.errores_instantanea_catalogo`,
  `experto.sha256_instantanea`, `experto.resolver_plantilla`, `experto.factor_estandar`, `experto.errores_motivos`,
  `experto.errores_ciclo_vida`, `experto.duracion_gantt`, `experto.limite_retirada`, `experto.citas_dimensionamiento`,
  `experto.quitar_comillas`, `experto.precio_medio`; `anexo_consumo.ruta_instantanea`, `cargar_instantanea`,
  `instantanea_vigente`, `errores_edad`, `es_observacion_no_precio`; `verificacion.errores_conservacion_efecto(resp,
  conservar) -> [{"id","regla","detalle"}]`, `precios_conservar`, `aceptados_siguientes`, `contenido_linea`,
  `ids_en_lotes`, `linea_precio_brief`; `decision.resumen_version`, `cambios_pedidos`, `lineas_cambios_pedidos(estado,
  con_importes=True, perfiles=None)`, `TITULO_CAMBIOS`; `pptx_revision.referencias_faltan`, `plan_pie`,
  `texto_referencia`, `lineas_referencia`, `tam_cambios`; `textos_cliente.supuestos_consumo`, `factor_aplicado`,
  `repite_factor`, `ciclo_vida_modelos`, `riesgos_modelo`, `clave_url`, `url_publicable`; `paquete._instantanea_sha`;
  `hosted/empaquetar.comprobar_instantanea(ruta, ahora, catalogo=None)`.
- Réplicas en la puerta (igualdad con el núcleo en `tests/test_i17_p_replicas.py` y `tests/test_i17_d_replicas.py`):
  `completar_r`, `proyectar_r`, `motivos_r`, `ciclo_r`, `citas_dim_r`, `referencias_faltan_replica` y las nuevas
  `cortes_conectores_replica` y `separacion_conectores_replica`; `conservacion_replica` por efecto.

## 13. Arreglos de I1.7 (13-10-2026)

- `experto.es_computo_por_defecto(entrada, propias, catalogo)` y `experto.lineas_computo(resp, catalogo)` (nota del
  revisor, vía `lineas_por_defecto`). Reglas nuevas: `falta_medidor_obligatorio` (en `errores_volumen_nivel`) y
  `por_instancia_no_valido` (en `completar`); réplicas en `verificar_paquete` con prueba de igualdad
  (`tests/test_i17_arr_nucleo.py`).
- `brief.lineas_propuesta_devuelta(estado, anon)` y la constante `brief.SECCION_PROPUESTA`.
- `textos_cliente.TEMAS_PAGINA` (temas de páginas concretas; `TEMAS_REFERENCIA` sigue siendo la lista blanca).
- Hosted: `a2a.ClienteA2A(…, espera_s, sondeo_s, dormir, reloj)`, `ClienteA2A.recuperar(agente, task_id, previa)`,
  `ClienteA2A.cancelado` y `fases.pendiente_previa(trabajo, agente, fase, sha256_enviado)`.

## 14. Cambios de I1.8 (14-10-2026)

Contrato en `docs/I1/CONTRATOS.md` §25; detalle por papel en `docs/I1/CAMBIOS-I18-{E,P,R,D}.md`.

- Fuera: `pptx_revision.tam_cambios` (la sección de cambios ya no va en el PPTX). La rama `perfiles` de
  `decision.lineas_cambios_pedidos` ya no la llama nadie del núcleo ni la puerta.
- `pptx_revision.revision_interna_en_pptx(partes, estado, catalogo) -> list[str]` (`[]` si el PPTX está limpio; una
  parte ilegible lanza la excepción) y `pptx_revision.partes_de(prs) -> dict`; `construir` no publica el PPTX si hay algo.
- `nota_revision.lineas_cambios_nota(estado, catalogo) -> list[str]`, `nota_revision.nombres_claves(estado, catalogo) ->
  dict` y `nota_revision.AVISO_CAMBIOS`; `textos_cliente.concordar(cantidad, unidad)`.
- `brief.texto_envio(estado, brief, hasta_n=None) -> str` (lo que B envía al experto; con un rechazo previo, el bloque
  `REINTENTO-PREVENTA/1`), `brief.rechazos_vigentes`, `brief.control_registro_experto`, `brief.cuerpos_ronda_1`,
  `brief.numero_es`, `brief.unidad_es` y `brief.lineas_propuesta_devuelta(…, formato)`.
- `paquete.construir(…, hoy=None)`: mide la edad de la instantánea antes de escribir (`IntegridadRota` con más de 31 días).
- `experto`: `conservar_de`, `conservacion_efecto`, `errores_modelo_sku`, `modelos_catalogo`, `modelos_en`,
  `fuentes_cliente`, `servicios_nombrados`, `nombra_servicio`, `cantidad_con_su_unidad`, `palabras_de_base`,
  `instancias_por_plantilla`, `filas_computo`, `nivel_por_defecto`, `es_por_defecto`, `reglas_medidores_de`, las
  constantes `CAMPO_CLIENTE` y `SECCION_CLIENTE`, y `UNIDADES_TIEMPO` con «1 GB/Month». `niveles_de` devuelve además
  `obligatorios`, `instancias_max`, `instancias_min` e `instancias_validas`.
- Reglas nuevas de `errores_volumen_nivel`: `cantidad_sin_su_unidad`, `instancias_max_no_valido`,
  `instancias_sobre_limite`, `instancias_bajo_minimo`, `instancias_no_admitidas`, `instancias_sin_justificar`,
  `computo_sin_niveles` y `regla_medidores_no_valida`; de `errores_motivos`: `cita_cliente_sin_servicio`; de
  `errores_ciclo_vida`: `modelo_sku_distinto` y `modelo_sin_plantilla`.
- `verificacion.precios_conservar` y `verificacion.errores_conservacion_efecto` delegan en `experto`; fuera
  `verificacion.iguales_conservar` y sus auxiliares.
- Hosted: `a2a.TAREA_NO_ENCONTRADA`, `a2a.NO_ENCONTRADA_SEGUIDOS`; `fases.ProcedenciaIlegible` y `fases.avisar_ilegibles`.
- Réplicas en la puerta con prueba de igualdad (`tests/i18_p_datos.reglas`, `tests/test_i18_int_nucleo_n.py`,
  `tests/test_i18_d_replica.py`): las 17 de P, `reglas_medidores_r`, `_niveles_r` con N5, `TIEMPO_R` con N7, N4 en
  `errores_volumen_nivel_replica` y `revision_interna_en_pptx_replica`.

## 15. Cambios de I1.9 (17-10-2026)

Contrato en `docs/I1/CONTRATOS.md` §26; detalle por papel en `docs/I1/CAMBIOS-I19-{E,P,R,D}.md`.

- `experto` (P): `errores_existentes`, `errores_arquitectura` (`canal_sin_computo`, `datos_sin_salida`), `es_existente`,
  `existentes_req`, `lineas_brief_existentes`, `valorados_de`, `razones_validas`, `razon_cumplida`, `afirmada`,
  `numeros_con_unidad`, `citas_de_campos(…, sin_asumido)`, `razones_modelo`, `modelo_por_defecto`, `opcional_de`,
  `cumple_opcional`, `segmento_verificador_i19`, `razon_de_justificacion`, `lineas_revisor_i19`, `factores_alternativos`,
  `factor_por_base`, `bases_admitidas`, la constante `MOTIVO_EXISTENTE` y `VENTANA_UNIDAD`/`NEGACION_TRAS`. Reglas nuevas
  en `errores_volumen_nivel`: `justificacion_sobrante`, `nivel_sin_razones`, `razones_no_validas`, `razon_desconocida`,
  `razon_no_cumplida`, `modelo_sin_justificar`, `modelo_por_defecto_no_declarado`, `opcional_no_valido` y
  `opcional_sin_requisito`; fuera `limite_no_oficial` y `fuente_no_oficial`.
- `suficiencia.aplicar(estado, requisitos, textos_fuente, catalogo=None)` y `suficiencia.reglas_existentes(entradas,
  catalogo)`: con entradas EX exige el catálogo montado (`existente_sin_catalogo`).
- `anexo_consumo`: `MOTIVO_EXISTENTE` («Sistema que ya tiene el cliente»); `no_valorados` nombra un sistema del cliente
  como el diagrama (`textos_cliente.nombre_base_existente`, D-C1); el XLSX se imprime en A4 horizontal a una página de ancho.
- `nota_revision`: `lineas_estimacion`, `resumen_estimacion`, `lineas_registro_decisiones` (APROBADA: «9. Registro de
  decisiones»), `etiqueta_campo`, `ver_veredicto`, `sin_ids_hallazgo`.
- `decision.resumen_version` guarda `estimacion` (esquema `decision.json`, `version_devuelta.estimacion`).
- `verificacion`: `disponibilidad_catalogo`, `region_disponible_segun_catalogo`, `lineas_discrepa_turno`,
  `evaluar`/`registrar(…, catalogo=None)`; la línea del componente sale de `experto.segmento_verificador_i19` (una
  respuesta v4 conserva `_segmento_nivel`) y el «(estándar: …)» del factor, de `experto.factor_por_base`.
- `paquete`: `nombre_pptx`, `nombres_zip(codigo, estado)` (VA18-7).
- `pptx_revision` (D): `legibilidad_conectores(raiz)`, `importes_no_permitidos(partes, estado)`, `es_del_cliente(comp)`,
  `TITULO_APROBADA` y las constantes `PUNTAS`, `ORDENES_EXTRA`, `MAX_BUSQUEDAS`; `revision_interna_en_pptx` recorre
  también el texto alternativo, los diseños y los patrones (VPROT-1).
- `textos_cliente` (D): `nombre_en_diagrama`, `nombre_base_existente`, `entrada_de`, `entradas_existentes`,
  `flujos_cliente`, `presupuesto_en_textos`, `importes_permitidos`, `importes_monetarios`, `lectura_es`, `nivel_con_tope`,
  `frase_sustituta`, `frase_asumido`, `hechos_nombrables`, `llano_cliente`, `region_legible`, `mismo_producto`,
  `nombre_oficial` y las constantes `CAMPOS_INTERNOS`, `SUFIJO_EXISTENTE`, `ARTICULOS`, `REGIONES_LEGIBLES`,
  `VERBOS_INFINITIVO`.
- `preventa_api.catalogo_montado(carpeta)` (lectura, no es subcomando): el catálogo montado para la extracción de B.
- Hosted: `modelo.lista_servicios(catalogo)` y `pedir_requisitos(…, servicios="")`; `a2a.identidad_de_token` (VPROT-3);
  `fases.motivos_discrepa` (PR18-7).
- Réplicas en la puerta con prueba de igualdad: las 56 de `docs/I1/CAMBIOS-I19-P/replicas_puerta.py` (§7, §7.1 y
  §12.3), `importes_no_permitidos_replica`, `legibilidad_conectores_replica` y la excepción de
  `referencias_faltan_replica` (D §2), `disponibilidad_catalogo_replica`, `datos_internos_en_cliente` y
  `revision_interna_en_pptx_replica` con VPROT-1 (R). Código propio de la puerta: `_existentes_y_arquitectura`,
  `_importes_cliente`, `_nombre_existente_valido`, el FALLA del contrato v4 y `region_no_admitida` sin veto para un
  sistema del cliente.
