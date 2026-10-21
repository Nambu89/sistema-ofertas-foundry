# Pasos manuales de Fernando (paso 0b)

Lo que el modo automático de Claude Code no puede hacer: asignar roles, leer o escribir claves y crear
conexiones con clave. Fernando lo ejecuta desde Claude Code con `!` (o desde una terminal propia de Git Bash),
siempre desde la raíz del repositorio:

```bash
! bash /c/demos/sistema-ofertas-foundry/pasos-fernando/<script> [argumentos]
```

## Cómo funcionan todos los scripts

- **Primero el plan.** Sin `--confirmar` cada script muestra lo que va a hacer y sale con 3 sin cambiar nada.
  Con `!` no hay terminal interactiva, así que la confirmación es repetir el mismo comando añadiendo
  `--confirmar`. En una terminal propia también vale escribir `SI` cuando lo pregunta.
- **Comprueban el resultado.** Al terminar releen lo que han cambiado y lo comparan con lo esperado.
- **Son idempotentes.** Lo que ya está hecho no se repite; se pueden relanzar sin miedo.
- **Código de salida = veredicto:**

  | Código | Significado |
  |---|---|
  | 0 | Hecho y comprobado |
  | 1 | Fallo (el mensaje dice qué y qué hacer) |
  | 2 | Uso incorrecto |
  | 3 | Solo plan: no se ha cambiado nada |
  | 4 | En curso: repetir más tarde (propagación, recurso que aún no existe o verificación pendiente) |

- **Nunca imprimen secretos.** La salida de `!` entra en la conversación, así que las claves solo pasan por
  memoria, por la entrada estándar de `curl` o por ficheros temporales que se borran al salir. Para
  identificarlas se muestra una huella (12 caracteres de su SHA-256), que no permite recuperarlas.
  **Nunca pegues una clave en el chat.** Si necesitas verla, hazlo en una terminal propia, no con `!`.
- Tenant fijo (el de `config/entorno.local.json`), suscripción explícita en cada orden y nunca
  `az account set`. Ninguna orden de red espera más de 80 s.
- Si sale un error de autenticación de az: `! az login --tenant <id-de-tu-tenant> --scope https://ai.azure.com/.default`
  y repetir.
- `local.conf` (no se versiona) guarda los identificadores de otros proyectos que usan 04a, 04c y 04d. La
  plantilla es `local.conf.ejemplo`. En este equipo ya está rellenado.

## Orden y tiempos

| Orden | Script | Qué hace | Cuándo | Tiempo |
|---|---|---|---|---|
| 1 | `03-conexion-marcador.sh` | Conexión `ofa-prueba-marcador` (valor no secreto) para la prueba P4b | Ya | 2 min |
| 2 | `06-cerrar-p4b.sh` | Repite P4 del paso 0a hasta su veredicto | Justo después del 1 | 12-15 min (unas 8 tandas de 85 s) |
| 3 | `02-storage.sh` | Cuenta de Storage del sistema y conexión con su clave | Ya (antes de la fase 1) | 5-8 min |
| 4 | `04a-rotar-azure-foundry-key.sh` | Rota `AZURE_FOUNDRY_KEY` | Antes de la fase 1 | 5 min + reabrir herramientas |
| 5 | `04b-rotar-nvidia-key.sh` | Rota `NVIDIA_API_KEY` | Antes de la fase 1 | 5-7 min (usa el portal de NVIDIA) |
| 6 | `04c-rotar-clave-azure-filtrada.sh` | Rota la clave de Azure filtrada en otro repositorio | Antes de la fase 1 | 10 min (con avisar a sus consumidores) |
| 7 | `04d-rotar-clave-gcp.sh` | Rota la clave de cuenta de servicio de GCP versionada | Antes de la fase 1 | 15-20 min (en cuatro pasos) |
| 8 | `05-opencode-password.sh` | Contraseña de `opencode serve` y `opencode web` | Antes de la fase 1, mientras OpenCode siga vivo | 3-5 min |
| 9 | Decisiones del apartado 06 | Leer y decidir lo que salió de P1 y P5 | Antes de arrancar la fase 1 | 15-30 min |
| 10 | `01-roles-coordinador.sh` | Roles de la identidad de `ofa-coordinador` | En la fase 1, al desplegar el coordinador, y cada vez que se despliegue un especialista | 3 min + hasta 10 min de propagación |

Tiempo activo total: entre 75 y 105 minutos, sin contar la espera de la fase 1 para el paso 10. Los pasos
4 a 8 son la condición de entrada de la fase 1 del diseño (§7, «OpenCode»): la prueba es la clave antigua
devolviendo 401 o 403, con el comando y su salida pegados.

## 01 · Roles del coordinador

`01-roles-coordinador.sh [asignar|retirar|estado] [--coordinador ofa-coordinador] [--destinos "…"] [--principal <guid>] [--confirmar]`

- **Foundry Agent Consumer** a la identidad del coordinador con **ámbito en cada agente destino**
  (`…/projects/<proyecto>/agents/<destino>`), patrón ya probado en otro proyecto del mismo tenant: solo
  puede llamar a esos especialistas, no a todo el proyecto. Por defecto los seis de `config/entorno.local.json`.
- **Foundry User** a la misma identidad sobre el proyecto (diseño §7, supuesto de planificación).
- La identidad (`instance_identity.principal_id`) se lee del agente en Foundry en ese momento; no se teclea.
- **Cuándo:** el coordinador aún no existe, así que hoy sale con 4 sin tocar nada. Se ejecuta en la fase 1 en
  cuanto `ofa-coordinador` esté desplegado, y otra vez con cada especialista nuevo (los que faltan se omiten y
  el script sale con 4 hasta que estén todos).
- Si el coordinador se borra y se crea de nuevo, su identidad cambia: primero
  `retirar --principal <guid antiguo> --confirmar` y después `asignar`.
- Comprobación: relee las asignaciones. Propagación: hasta 10 minutos.

## 02 · Storage del sistema

`02-storage.sh [--cuenta stofasistemaofertas] [--region swedencentral] [--sku Standard_LRS] [--dias-retencion 14] [--log-analytics <recurso>-logs|ninguno] [--conexion ofa-storage-clave] [--clave key1|key2] [--actualizar-conexion] [--confirmar]`

- Nombre propuesto **`stofasistemaofertas`** (disponible el 18-10-2026), en el grupo de recursos de la configuración local, región
  **swedencentral** (la del proyecto; solo admite regiones de la UE).
- StorageV2, solo HTTPS, TLS 1.2, **acceso público a blobs desactivado**, **AllowSharedKeyAccess activado**
  (el coordinador firma SAS de turno con la clave de cuenta, diseño §7).
- **Versionado de blobs** y **borrado temporal** de blobs y de contenedores, 14 días.
- Contenedores `sistema`, `compartido` y `agentes`, sin acceso público. Los de cada proyecto los crea el
  coordinador.
- Diagnóstico de lectura, escritura y borrado de blobs hacia `<recurso>-logs` (el recurso de la configuración local).
- Conexión del proyecto **`ofa-storage-clave`**, tipo claves personalizadas, solo para este proyecto, con la
  `key1` de la cuenta en la clave `clave_cuenta`.
- **La clave la lee el script con tu sesión de az, en memoria, y nunca se imprime.** Va a Azure en un fichero
  temporal que se borra al salir. No la copies a ningún sitio ni la pegues en el chat.
- Comprobaciones: propiedades de seguridad, versionado y retención, que la clave abre el contenedor
  `sistema` (si una política del tenant hubiera desactivado la clave compartida, aquí falla), que el
  contenedor no se puede listar sin credenciales y la forma de la conexión.
- Rotación (diseño §7): regenera `key2` en el portal o con az, ejecuta
  `02-storage.sh --clave key2 --actualizar-conexion --confirmar`, termina las sesiones activas del coordinador y
  regenera `key1`.
- La conexión de SAS de solo lectura para la puerta (diseño §7, punto 2) no se crea en este paso. Se hará en
  la fase de la puerta, cuando se fije su caducidad.

## 03 · Conexión marcador para P4b

`03-conexion-marcador.sh [--borrar] [--confirmar]`

Crea `ofa-prueba-marcador` (claves personalizadas, clave `valor` = `marcador-sintetico`; **no es secreto**).
La forma del cuerpo es la de las conexiones del mismo tipo que ya existen en el proyecto. Si ARM la rechaza,
créala en el portal (proyecto → Recursos conectados → Nueva conexión → Claves personalizadas) y
vuelve a lanzar el script para comprobarla. Cuando P4b esté cerrada: `--borrar --confirmar`.

## 04 · Rotación de claves del ecosistema de OpenCode

Cada script tiene `estado` (solo mira), `rotar` (o los pasos de GCP) y `verificar`. La clave antigua solo
se da por muerta cuando devuelve 401 o 403. Si Azure o el proveedor tardan en invalidarla, se guarda en una
variable de usuario `OFA_ROT_…_ANTERIOR`, en el mismo almacén donde ya estaba, y `verificar` la vuelve a
probar y la borra.

### 04a · `AZURE_FOUNDRY_KEY` (recurso Foundry de la configuración local)

- **Dónde se usa:** variable de entorno de usuario de Windows que heredan Claude Code, OpenCode y Codex;
  proveedor `foundry` de `opencode.json` del espacio de ofertas y, si se configuró así, la cabecera del MCP
  `foundry-skills`; Codex CLI (`~/.codex/config.toml`, `env_key`). Los agentes del proyecto usan Entra.
- **Cómo:** el script averigua si la variable es la `key1` o la `key2`, regenera la otra, comprueba que
  responde 200, la guarda en la variable, regenera la que estaba en uso y comprueba que la antigua da 401.
  Antes de rotar avisa de copias literales de la clave en ficheros de configuración (y no rota si las hay),
  de conexiones del proyecto con clave que apunten al recurso y de procesos de OpenCode o Codex abiertos.
  Se regeneran las dos claves del recurso: si alguien más del tenant usa la que no está en tu variable,
  también se queda sin acceso.
- **Después:** abre una terminal nueva y vuelve a abrir Claude Code, OpenCode y Codex. Ojo: la revisión
  obligatoria con Codex usa esta clave, así que en la sesión de Claude Code de antes de rotar no funcionará.
- `bash …/04a-rotar-azure-foundry-key.sh estado`, luego `rotar` y `rotar --confirmar`.

### 04b · `NVIDIA_API_KEY` (build.nvidia.com)

- **Dónde se usa:** variable de entorno de usuario y proveedor `nvidia` de `opencode.json`.
- **Cómo:** NVIDIA no tiene CLI de claves.
  1. En el portal de NVIDIA genera una clave nueva y cópiala (el script la toma del portapapeles).
  2. `rotar --confirmar`: comprueba la nueva, guarda la antigua aparte, fija la variable y vacía el
     portapapeles.
  3. Revoca la antigua en el portal.
  4. `verificar`: exige 401 o 403 con la antigua.
- `/v1/models` de NVIDIA responde 200 sin clave, así que la prueba usa `/v1/chat/completions` con un modelo
  calibrado antes con una clave inválida a propósito: los modelos retirados devuelven 410 antes de mirar la
  clave.

### 04c · Clave de Azure filtrada en otro repositorio

- **Qué es:** la clave de una cuenta de Azure de otro proyecto que estuvo versionada en un `.env.example`.
  Se borró del histórico el 21-08-2026, pero sigue válida. El recurso y sus consumidores están en `local.conf`.
- **Cómo:** como no se sabe cuál de las dos se filtró, regenera **las dos** y comprueba que las dos antiguas
  dan 401. Los consumidores legítimos necesitarán la nueva: consúltala tú en una terminal propia, no con `!`.
- Después, borra la copia de seguridad antigua de aquel repositorio (`ROT_AZ_COPIA_ANTIGUA`), que aún tiene la
  clave dentro. El 18-10-2026 no estaba en la ruta anotada: comprueba si se movió.

### 04d · Clave de cuenta de servicio de GCP

- **Qué es:** el fichero JSON de una cuenta de servicio, versionado en el repositorio del sistema A2A de
  pliegos y presente en la rama principal de su remoto privado. Proyecto, ruta y consumidores en `local.conf`.
- **Cómo,** en cuatro pasos para no dejar a nadie sin credencial:
  1. `crear --nueva-clave <ruta> --confirmar`. La ruta tiene que estar fuera de cualquier repositorio git y
     fuera de OneDrive.
  2. Actualiza a los consumidores con la clave nueva desde tu terminal. En la app desplegada es
     `GOOGLE_APPLICATION_CREDENTIALS_BASE64`.
  3. `desactivar --confirmar`. Es reversible con `gcloud iam service-accounts keys enable`.
  4. `verificar`, y días después `borrar --confirmar`.
- **Comprobación:** Google no devuelve 401 en este caso. El equivalente es que el canje de la clave antigua en
  su endpoint de tokens falle con `invalid_grant`. El script lo prueba en una configuración de gcloud aislada,
  que no toca la tuya, y exige además que la clave figure desactivada.
- Hace falta una cuenta de gcloud con permisos sobre las claves de ese proyecto. Purgar el histórico de aquel
  repositorio lo decides tú; el script no lo hace.

## 05 · Contraseña de `opencode serve`

`05-opencode-password.sh [estado|fijar|verificar|retirar] [--regenerar] [--puerto 4096] [--confirmar]`

- `fijar --confirmar` genera 32 caracteres aleatorios y los guarda en la variable de usuario
  `OPENCODE_SERVER_PASSWORD`. Los deja en el portapapeles para que los guardes en tu gestor de contraseñas. El
  usuario es `opencode`, salvo que definas `OPENCODE_SERVER_USERNAME`.
- Cierra OpenCode, ábrelo desde una terminal nueva y ejecuta `verificar`. Debe responder 401 sin credenciales
  y 200 con ellas en `/global/health`. Después vacía el portapapeles.
- El acceso desde el móvil por el túnel seguirá funcionando, pero el navegador pedirá usuario y contraseña.
- `retirar --confirmar` cuando OpenCode se apague para siempre.
- No está verificado que `opencode run` (la prueba P5) siga funcionando con la contraseña puesta. Tras fijarla,
  pide al coordinador del sistema que repita P5.

## 06 · Pendientes de RESULTADOS.md

1. **P4b** (`pruebas/paso0a/RESULTADOS.md`). Ejecuta el paso 03 y después `06-cerrar-p4b.sh --confirmar`,
   repitiéndolo mientras salga 4, hasta 0 o 1.
   - El script añade `--repetir` solo la primera vez. Las siguientes continúan el progreso: con `--repetir` en
     cada invocación, el turno largo de 6 minutos volvería a empezar siempre.
   - En una terminal propia: `06-cerrar-p4b.sh --intentos 10 --confirmar`.
2. **Decisiones que salen de P1:**
   - ¿El umbral de LES-G-036 (fin de proyecto más 12 meses) aplica tal cual a un sistema interno? Con el
     supuesto de hoy más 6 meses, ningún despliegue llega.
   - ¿Pasan los generadores de gpt-5.6-luna (se retira el 2028-01-11) a gpt-6-luna (2028-03-11)?
   - ¿Cómo y cuándo se sustituye Decision-1? Está en Preview y se retira el 2027-02-04. Propuesta del paso 0a:
     ponerla detrás de una interfaz con respaldo (luna con salida estructurada) y con fecha de sustitución.
3. **Requisitos nuevos que hay que confirmar en el diseño:**
   - El coordinador envía `usage` real en `response.completed`. Sin él, OpenCode repite el turno en bucle.
   - El plugin de OpenCode (token con tenant fijo y `api-version=v1` solo para el prefijo del hosted) forma parte
     del canal OpenCode.
   - El lanzador de OpenCode fija el directorio del proyecto con `--dir` o `PWD`.
