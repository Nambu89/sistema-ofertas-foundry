#!/usr/bin/env bash
# 02 · Cuenta de almacenamiento del sistema y conexión del proyecto con su clave (lo ejecuta Fernando: el modo
# automático deniega leer y escribir secretos).
#
# Qué deja hecho (diseño §2 y §7):
#   - Cuenta StorageV2 en una región de la UE (por defecto la del proyecto, swedencentral), solo HTTPS, TLS 1.2,
#     acceso público a blobs DESACTIVADO y AllowSharedKeyAccess ACTIVADO (el coordinador firma SAS de turno con
#     la clave de cuenta).
#   - Versionado de blobs y borrado temporal de blobs y de contenedores (14 días por defecto).
#   - Contenedores sistema, compartido y agentes, sin acceso público (los de cada proyecto los crea el
#     coordinador).
#   - Diagnóstico de lectura, escritura y borrado de blobs hacia Log Analytics (por defecto el área de trabajo
#     <recurso>-logs, con el recurso de la configuración local; --log-analytics ninguno lo omite).
#   - Conexión del proyecto de tipo claves personalizadas (CustomKeys) con la clave de la cuenta, en la clave
#     «clave_cuenta». La clave la lee este script en memoria con TU sesión de az y va a Azure en un fichero
#     temporal que se borra al salir. NUNCA la pegues en el chat ni la copies a ningún fichero.
#
# Uso:
#   bash pasos-fernando/02-storage.sh [--cuenta stofasistemaofertas] [--region swedencentral] [--sku Standard_LRS]
#        [--dias-retencion 14] [--log-analytics <recurso>-logs|ninguno] [--conexion ofa-storage-clave]
#        [--clave key1|key2] [--actualizar-conexion] [--confirmar]
#   --actualizar-conexion vuelve a escribir la conexión con la clave indicada (por ejemplo, key2 tras rotar).
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

CUENTA="stofasistemaofertas"
REGION="$REGION_PROYECTO"
SKU="Standard_LRS"
DIAS=14
LA="${RECURSO}-logs"
CONEXION="ofa-storage-clave"
CLAVE_NOMBRE="key1"
ACTUALIZAR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --cuenta) CUENTA="${2:?}"; shift ;;
    --region) REGION="${2:?}"; shift ;;
    --sku) SKU="${2:?}"; shift ;;
    --dias-retencion) DIAS="${2:?}"; shift ;;
    --log-analytics) LA="${2:?}"; shift ;;
    --conexion) CONEXION="${2:?}"; shift ;;
    --clave) CLAVE_NOMBRE="${2:?}"; shift ;;
    --actualizar-conexion) ACTUALIZAR=1 ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,24p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done

[[ "$CUENTA" =~ ^[a-z0-9]{3,24}$ ]] || fallo "$RC_USO" "nombre de cuenta no válido (3 a 24 minúsculas o dígitos): $CUENTA"
case "$REGION" in
  swedencentral|westeurope|northeurope|francecentral|germanywestcentral|spaincentral|italynorth|polandcentral) ;;
  *) fallo "$RC_USO" "región fuera de la lista UE admitida: $REGION" ;;
esac
case "$SKU" in Standard_LRS|Standard_ZRS) ;; *) fallo "$RC_USO" "SKU admitido: Standard_LRS o Standard_ZRS" ;; esac
[[ "$DIAS" =~ ^[0-9]+$ ]] && [ "$DIAS" -ge 1 ] && [ "$DIAS" -le 365 ] || fallo "$RC_USO" "--dias-retencion entre 1 y 365"
[[ "$CONEXION" =~ ^ofa-[a-z0-9-]+$ ]] || fallo "$RC_USO" "la conexión debe llamarse ofa-…: $CONEXION"
case "$CLAVE_NOMBRE" in key1|key2) ;; *) fallo "$RC_USO" "--clave key1 o key2" ;; esac
CONTENEDORES=(sistema compartido agentes)
ID_ST="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.Storage/storageAccounts/$CUENTA"
URL_CONEX="$ARM$ID_PROYECTO/connections/$CONEXION?api-version=$API_CONEX"

paso "02 · Storage del sistema ($CUENTA en $REGION) y conexión $CONEXION"
comprobar_az

# ¿Existe ya la cuenta en el grupo?
# En una subshell, para que el «no existe» esperado no ensucie la consola y para que, si az_r sale por
# autenticación (mensaje_login hace exit), su mensaje quede en show.err y se muestre antes de salir.
EXISTE=0
if ( az_r storage account show -n "$CUENTA" -g "$RG" --subscription "$SUB" --query id -o tsv >/dev/null 2>"$TMPD/show.err" ); then
  EXISTE=1
elif grep -q 'FALLO de autenticación' "$TMPD/show.err"; then
  cat "$TMPD/show.err" >&2
  exit "$RC_FALLO"
elif ! grep -qiE 'ResourceNotFound|was not found|could not be found' "$TMPD/az.err"; then
  cat "$TMPD/show.err" >&2
  fallo "$RC_FALLO" "no puedo comprobar si la cuenta $CUENTA existe."
fi
if [ "$EXISTE" = 0 ]; then
  disp="$(az_r storage account check-name --name "$CUENTA" --subscription "$SUB" --query nameAvailable -o tsv)" \
    || fallo "$RC_FALLO" "no puedo comprobar la disponibilidad del nombre."
  [ "${disp,,}" = "true" ] || fallo "$RC_FALLO" "el nombre $CUENTA no está disponible en Azure; elige otro con --cuenta."
fi

LA_ID=""
if [ "$LA" != "ninguno" ]; then
  LA_ID="$(az_r monitor log-analytics workspace show -n "$LA" -g "$RG" --subscription "$SUB" --query id -o tsv)" \
    || fallo "$RC_FALLO" "no encuentro el área de trabajo de Log Analytics $LA en $RG (usa --log-analytics ninguno para omitirlo)."
fi

rc=0; CONEX_ACTUAL="$(leer_conexion "$URL_CONEX")" || rc=$?
case "$rc" in 0) CONEX_EXISTE=1 ;; 4) CONEX_EXISTE=0 ;; *) exit "$RC_FALLO" ;; esac

paso "Plan"
if [ "$EXISTE" = 1 ]; then
  info "Cuenta $CUENTA: ya existe en $RG → se fuerzan las propiedades de seguridad (idempotente)."
else
  info "Cuenta $CUENTA: se CREA en $REGION ($SKU, StorageV2, Hot) en $RG."
fi
info "Propiedades: solo HTTPS, TLS 1.2, acceso público a blobs NO, AllowSharedKeyAccess SÍ, red pública sí."
info "Versionado de blobs SÍ; borrado temporal de blobs y de contenedores: $DIAS días."
info "Contenedores sin acceso público: ${CONTENEDORES[*]}."
if [ -n "$LA_ID" ]; then info "Diagnóstico de blobs (StorageRead, StorageWrite, StorageDelete y Transaction) hacia $LA."; fi
if [ "$CONEX_EXISTE" = 1 ] && [ "$ACTUALIZAR" = 0 ]; then
  info "Conexión $CONEXION: ya existe ($CONEX_ACTUAL) → no se toca (usa --actualizar-conexion para reescribirla)."
else
  info "Conexión $CONEXION (CustomKeys, solo este proyecto): se ESCRIBE con la $CLAVE_NOMBRE de la cuenta en «clave_cuenta»."
  info "La clave se lee en memoria y no se imprime. No la pegues nunca en el chat."
fi
confirmar "crear o ajustar la cuenta $CUENTA y la conexión $CONEXION"

paso "Cuenta de almacenamiento"
COMUNES=(--https-only true --min-tls-version TLS1_2 --allow-blob-public-access false --allow-shared-key-access true
         --public-network-access Enabled --tags sistema=ofertas-foundry uso=memoria-y-estado)
if [ "$EXISTE" = 0 ]; then
  az_r storage account create -n "$CUENTA" -g "$RG" --subscription "$SUB" -l "$REGION" --sku "$SKU" \
    --kind StorageV2 --access-tier Hot "${COMUNES[@]}" -o none \
    || fallo "$RC_FALLO" "no se pudo crear la cuenta (si el error es RequestDisallowedByPolicy, una política del tenant lo impide: avisa al coordinador)."
  ok "cuenta creada"
else
  az_r storage account update -n "$CUENTA" -g "$RG" --subscription "$SUB" "${COMUNES[@]}" -o none \
    || fallo "$RC_FALLO" "no se pudieron ajustar las propiedades de la cuenta."
  ok "propiedades ajustadas"
fi
az_r storage account blob-service-properties update --account-name "$CUENTA" -g "$RG" --subscription "$SUB" \
  --enable-versioning true --enable-delete-retention true --delete-retention-days "$DIAS" \
  --enable-container-delete-retention true --container-delete-retention-days "$DIAS" -o none \
  || fallo "$RC_FALLO" "no se pudo activar el versionado o el borrado temporal."
ok "versionado y borrado temporal activados"

for c in "${CONTENEDORES[@]}"; do
  ex="$(az_r storage container-rm exists --storage-account "$CUENTA" -g "$RG" --subscription "$SUB" -n "$c" --query exists -o tsv)" \
    || fallo "$RC_FALLO" "no puedo comprobar el contenedor $c."
  if [ "${ex,,}" != "true" ]; then
    az_r storage container-rm create --storage-account "$CUENTA" -g "$RG" --subscription "$SUB" -n "$c" \
      --public-access off -o none || fallo "$RC_FALLO" "no se pudo crear el contenedor $c."
    ok "contenedor $c creado"
  else
    info "contenedor $c: ya existía"
  fi
done

if [ -n "$LA_ID" ]; then
  az_r monitor diagnostic-settings create --name ofa-diagnostico-blob --resource "$ID_ST/blobServices/default" \
    --workspace "$LA_ID" \
    --logs '[{"category":"StorageRead","enabled":true},{"category":"StorageWrite","enabled":true},{"category":"StorageDelete","enabled":true}]' \
    --metrics '[{"category":"Transaction","enabled":true}]' -o none \
    || fallo "$RC_FALLO" "no se pudo crear el diagnóstico hacia Log Analytics."
  ok "diagnóstico de blobs hacia $LA"
fi

paso "Clave de la cuenta (en memoria, sin imprimir)"
CLAVE="$(az_r storage account keys list -n "$CUENTA" -g "$RG" --subscription "$SUB" \
          --query "[?keyName=='$CLAVE_NOMBRE'].value | [0]" -o tsv)" || fallo "$RC_FALLO" "no se pudo leer la clave."
[ -n "$CLAVE" ] && valor_seguro "$CLAVE" || fallo "$RC_FALLO" "la clave leída está vacía o no tiene el formato esperado."
info "huella de la $CLAVE_NOMBRE: $(huella "$CLAVE")"
# Prueba de que la clave sirve (y de que ninguna política ha desactivado el acceso con clave compartida).
ex="$(AZURE_STORAGE_KEY="$CLAVE" timeout 60 az storage container exists --account-name "$CUENTA" --name sistema \
        --auth-mode key --query exists -o tsv 2>"$TMPD/k.err" | tr -d '\r')" || true
[ "${ex,,}" = "true" ] || fallo "$RC_FALLO" "la clave no permite leer el contenedor sistema (¿AllowSharedKeyAccess bloqueado por política?): $(head -c 300 "$TMPD/k.err")"
ok "la clave de cuenta funciona (contenedor sistema visible con clave compartida)"

if [ "$CONEX_EXISTE" = 0 ] || [ "$ACTUALIZAR" = 1 ]; then
  OFA_CLAVE="$CLAVE" "$PY" -I -c '
import json, os, sys
cuerpo = {"properties": {
    "category": "CustomKeys", "authType": "CustomKeys", "target": sys.argv[2], "isSharedToAll": False,
    "credentials": {"keys": {"clave_cuenta": os.environ["OFA_CLAVE"]}},
    "metadata": {"cuenta": sys.argv[3], "uso": "firma de SAS de turno del coordinador del sistema de ofertas"}}}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(cuerpo, f)
' "$TMPD/conexion.json" "https://$CUENTA.blob.core.windows.net" "$CUENTA"
  az_r rest --method put --url "$URL_CONEX" --body @"$TMPD/conexion.json" -o none \
    || { rm -f "$TMPD/conexion.json"; fallo "$RC_FALLO" "no se pudo escribir la conexión $CONEXION."; }
  rm -f "$TMPD/conexion.json"
  ok "conexión $CONEXION escrita con la $CLAVE_NOMBRE"
fi
unset CLAVE

paso "Comprobación final"
read -r PUB SHARED TLS HTTPS LOC < <(az_r storage account show -n "$CUENTA" -g "$RG" --subscription "$SUB" \
  --query "[allowBlobPublicAccess, allowSharedKeyAccess, minimumTlsVersion, enableHttpsTrafficOnly, location]" -o tsv | tr '\n' ' '; echo)
read -r VER DEL DDIAS CDEL < <(az_r storage account blob-service-properties show --account-name "$CUENTA" -g "$RG" \
  --subscription "$SUB" --query "[isVersioningEnabled, deleteRetentionPolicy.enabled, deleteRetentionPolicy.days, containerDeleteRetentionPolicy.enabled]" -o tsv | tr '\n' ' '; echo)
MAL=0
comprueba() { if [ "${2,,}" = "${3,,}" ]; then ok "$1 = $2"; else printf 'FALLO: %s = «%s» (se esperaba %s)\n' "$1" "$2" "$3" >&2; MAL=1; fi; }
comprueba "acceso público a blobs" "$PUB" "false"
comprueba "AllowSharedKeyAccess" "$SHARED" "true"
comprueba "TLS mínimo" "$TLS" "TLS1_2"
comprueba "solo HTTPS" "$HTTPS" "true"
comprueba "región" "$LOC" "$REGION"
comprueba "versionado" "$VER" "true"
comprueba "borrado temporal de blobs" "$DEL" "true"
comprueba "días de retención" "$DDIAS" "$DIAS"
comprueba "borrado temporal de contenedores" "$CDEL" "true"
anon="$(curl -s -o "$TMPD/descarte" -w '%{http_code}' --max-time 40 "https://$CUENTA.blob.core.windows.net/sistema?restype=container&comp=list" || true)"
case "$anon" in
  401|403|404|409) ok "listar sistema sin credenciales → HTTP $anon (rechazado)" ;;
  *) printf 'FALLO: listar sistema sin credenciales dio HTTP %s; solo 401, 403, 404 o 409 prueban el rechazo\n' "$anon" >&2; MAL=1 ;;
esac
cat_con="$(leer_conexion "$URL_CONEX")" || { printf 'FALLO: no puedo leer la conexión %s\n' "$CONEXION" >&2; MAL=1; }
comprueba "conexión $CONEXION (categoría, tipo, destino)" "${cat_con:-}" "CustomKeys CustomKeys https://$CUENTA.blob.core.windows.net"
[ "$MAL" = 0 ] || exit "$RC_FALLO"
echo "Hecho $(date '+%d-%m-%Y %H:%M'). Si es la primera vez, avisa al coordinador del sistema: el nombre de la cuenta"
echo "es $CUENTA y la conexión $CONEXION (clave «clave_cuenta»). Rotación: diseño §7 (regenera key2, ejecuta este"
echo "paso con --clave key2 --actualizar-conexion, termina las sesiones activas y regenera key1)."
exit "$RC_OK"
