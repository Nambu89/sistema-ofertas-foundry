#!/usr/bin/env bash
# Funciones comunes de los pasos manuales de Fernando (paso 0b). Cada script la carga con «source».
#
# Reglas que cumplen todos los scripts:
#   - Primero muestran el plan. Sin --confirmar (o sin escribir SI en una terminal interactiva) no cambian nada.
#   - Nunca imprimen secretos: las claves pasan por variables de memoria, por la entrada estándar de curl o por
#     ficheros temporales con permisos restringidos que se borran al salir. Solo se muestra una huella
#     (12 caracteres de su SHA-256), que no permite recuperar la clave.
#   - Nunca usan «az account set»: la suscripción va explícita en cada orden y el tenant se comprueba.
#   - Ninguna orden de red espera más de 80 s; las esperas largas son sondeos cortos con progreso.
#
# Códigos de salida (el código es el veredicto):
#   0 hecho y comprobado · 1 fallo · 2 uso incorrecto · 3 solo plan, nada cambiado
#   4 en curso: repetir más tarde (propagación, recurso que aún no existe o verificación pendiente)
set -euo pipefail
export MSYS_NO_PATHCONV=1
umask 077

# Rutas «mixtas» (C:/…/…): las entienden tanto las herramientas de Git Bash como los programas nativos de
# Windows (python.exe, az, gcloud, curl de ucrt64), que con MSYS_NO_PATHCONV=1 no reciben conversión automática.
ruta_mixta() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }
DIR_PASOS="$(ruta_mixta "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")"
RAIZ="$(ruta_mixta "$(cd "$DIR_PASOS/.." && pwd)")"
# Configuración local del entorno (git la ignora); plantilla versionada en config/entorno.ejemplo.json.
# OFA_ENTORNO apunta a otro fichero (las pruebas usan la plantilla); definida pero vacía es un error.
if [ -n "${OFA_ENTORNO+x}" ]; then
  CONFIG="$(printf '%s' "$OFA_ENTORNO" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  [ -n "$CONFIG" ] || { printf 'FALLO: la variable OFA_ENTORNO está definida pero vacía.\n' >&2; exit 1; }
else
  CONFIG="$RAIZ/config/entorno.local.json"
fi

RC_OK=0
RC_FALLO=1
RC_USO=2
RC_PLAN=3
RC_EN_CURSO=4

TMPD="$(ruta_mixta "$(mktemp -d)")"
trap 'rm -rf "$TMPD"' EXIT

paso()  { printf '\n== %s\n' "$*"; }
info()  { printf '   %s\n' "$*"; }
ok()    { printf 'OK: %s\n' "$*"; }
aviso() { printf 'AVISO: %s\n' "$*" >&2; }
progreso() { printf '   … %s\n' "$*" >&2; }
fallo() { local rc="$1"; shift; printf 'FALLO: %s\n' "$*" >&2; exit "$rc"; }

if [ -x "$RAIZ/.venv/Scripts/python.exe" ]; then
  PY="$RAIZ/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
else
  fallo "$RC_FALLO" "no encuentro Python (ni .venv del repositorio ni python en el PATH)."
fi

# Configuración del repositorio (sin secretos). Se lee una vez y se valida que no falte nada.
[ -f "$CONFIG" ] || fallo "$RC_FALLO" "no encuentro $CONFIG. Copia config/entorno.ejemplo.json a config/entorno.local.json y pon los valores de tu entorno."
while IFS='=' read -r _k _v; do
  case "$_k" in
    TENANT|SUB|RG|RECURSO|PROYECTO|REGION_PROYECTO|EP_PROYECTO|API_CONEX|ROL_USER|ROL_CONSUMER|AGENTES|COORD_DEF)
      printf -v "$_k" '%s' "$_v" ;;
  esac
done < <("$PY" -I -c '
import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
ag = d["agentes"]
print("TENANT=" + d["tenant_id"])
print("SUB=" + d["suscripcion_id"])
print("RG=" + d["grupo_recursos"])
print("RECURSO=" + d["recurso"])
print("PROYECTO=" + d["proyecto"])
print("REGION_PROYECTO=" + d["region"])
print("EP_PROYECTO=" + d["endpoints"]["proyecto"])
print("API_CONEX=" + d["api_versions"]["arm_conexiones"])
print("ROL_USER=" + d["roles"]["foundry_user"])
print("ROL_CONSUMER=" + d["roles"]["foundry_agent_consumer"])
print("COORD_DEF=" + ag["coordinador"]["nombre"])
print("AGENTES=" + " ".join(v["nombre"] for k, v in ag.items() if k != "coordinador"))
' "$CONFIG" | tr -d '\r')
for _k in TENANT SUB RG RECURSO PROYECTO REGION_PROYECTO EP_PROYECTO API_CONEX ROL_USER ROL_CONSUMER AGENTES COORD_DEF; do
  [ -n "${!_k:-}" ] || fallo "$RC_FALLO" "$CONFIG no da valor para $_k."
done
# Los valores ficticios de la plantilla solo valen en la propia plantilla versionada (la usan las pruebas, sin
# red): se compara la ruta exacta, sin distinguir mayúsculas (Windows), no el nombre del fichero.
_config_norm="$(ruta_mixta "$CONFIG")"
_plantilla_norm="$RAIZ/config/entorno.ejemplo.json"
case "${_config_norm,,}" in
  "${_plantilla_norm,,}") ;;
  *)
    _ficticios=""
    [ "$TENANT" = "00000000-0000-0000-0000-000000000000" ] && _ficticios="$_ficticios tenant_id"
    [ "$SUB" = "00000000-0000-0000-0000-000000000000" ] && _ficticios="$_ficticios suscripcion_id"
    [ "$RG" = "rg-ejemplo" ] && _ficticios="$_ficticios grupo_recursos"
    [ "$RECURSO" = "mi-recurso-foundry" ] && _ficticios="$_ficticios recurso"
    [ "$PROYECTO" = "mi-proyecto-foundry" ] && _ficticios="$_ficticios proyecto"
    [ -z "$_ficticios" ] || fallo "$RC_FALLO" "$CONFIG conserva valores ficticios de la plantilla:$_ficticios. Sustitúyelos por los de tu entorno."
    ;;
esac
ID_CUENTA="/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.CognitiveServices/accounts/$RECURSO"
ID_PROYECTO="$ID_CUENTA/projects/$PROYECTO"
ARM="https://management.azure.com"

# Confirmación: --confirmar en la línea de órdenes (necesario con «!» desde Claude Code, que no es una
# terminal interactiva) o SI escrito a mano si la entrada es una terminal.
CONFIRMAR=0
confirmar() {  # $1 = resumen de lo que se va a hacer
  if [ "$CONFIRMAR" = 1 ]; then
    info "Confirmado con --confirmar: $1"
    return 0
  fi
  if [ -t 0 ] && [ -t 1 ]; then
    local r=""
    printf '\n¿Continuar? (%s) Escribe SI para seguir: ' "$1"
    read -r r || true
    if [ "$r" = "SI" ]; then return 0; fi
    echo "Cancelado: no se ha cambiado nada."
    exit "$RC_PLAN"
  fi
  printf '\nSOLO PLAN: no se ha cambiado nada. Si estás de acuerdo, repite el mismo comando añadiendo --confirmar.\n'
  exit "$RC_PLAN"
}

mensaje_login() {  # $1 = texto del error de az (no contiene secretos)
  printf 'FALLO de autenticación de az: %s\n' "$(printf '%s' "$1" | tr -d '\r' | head -c 400)" >&2
  printf 'Ejecuta en Claude Code:  ! az login --tenant %s --scope https://ai.azure.com/.default\ny repite este paso.\n' "$TENANT" >&2
  exit "$RC_FALLO"
}

# az con tiempo máximo. La salida estándar se devuelve sin \r; el error va a un fichero y solo se muestra
# si la orden falla. Nunca se mezcla el error con la salida, para que una advertencia no se cuele en un valor.
az_r() {
  local rc=0 out
  out="$(timeout 80 az "$@" 2>"$TMPD/az.err")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    if grep -qE 'AADSTS|az login|refresh token|expired' "$TMPD/az.err"; then
      mensaje_login "$(cat "$TMPD/az.err")"
    fi
    [ "$rc" -eq 124 ] && echo "az no respondió en 80 s." >&2
    tr -d '\r' < "$TMPD/az.err" | head -c 1500 >&2
    echo >&2
    return "$rc"
  fi
  printf '%s' "$out" | tr -d '\r'
}

comprobar_az() {  # $1 = suscripción (por defecto la del sistema)
  local sub="${1:-$SUB}" t
  command -v az >/dev/null 2>&1 || fallo "$RC_FALLO" "no encuentro az (Azure CLI)."
  t="$(az_r account show --subscription "$sub" --query tenantId -o tsv)" \
    || fallo "$RC_FALLO" "no puedo leer la suscripción $sub con az."
  [ "$t" = "$TENANT" ] || fallo "$RC_FALLO" "la suscripción $sub es del tenant «$t», no de $TENANT."
  info "az: suscripción $sub en el tenant $TENANT (sin «az account set»)."
}

token_datos() {  # token de Entra para el plano de datos de Foundry, con el tenant fijado (LES-G-052)
  az_r account get-access-token --tenant "$TENANT" --resource https://ai.azure.com --query accessToken -o tsv
}

valor_seguro() {  # rechaza valores que romperían la configuración de curl (comillas, barras, saltos)
  case "$1" in
    *'"'*|*\\*|*$'\n'*|*$'\r'*|'') return 1 ;;
    *) return 0 ;;
  esac
}

# Petición HTTP con una cabecera secreta. La cabecera llega a curl por su entrada estándar (-K -), así que no
# aparece en la lista de procesos. Deja el cuerpo en $TMPD/cuerpo e imprime solo el código HTTP (000 si no hay
# respuesta).
codigo_con_cabecera() {  # $1 nombre de cabecera, $2 valor, $3 URL, [$4 método], [$5 cuerpo JSON]
  local metodo="${4:-GET}" extra=()
  valor_seguro "$2" || { echo "000"; return 0; }
  if [ $# -ge 5 ]; then extra=(-H "Content-Type: application/json" --data "$5"); fi
  printf 'header = "%s: %s"\n' "$1" "$2" \
    | curl -s -K - -X "$metodo" -o "$TMPD/cuerpo" -w '%{http_code}' --max-time 40 "${extra[@]}" "$3" || true
}

codigo_bearer() {  # $1 token, $2 URL
  codigo_con_cabecera "Authorization" "Bearer $1" "$2"
}

huella() {  # 12 caracteres del SHA-256: identifica una clave sin revelarla
  printf '%s' "$1" | sha256sum | cut -c1-12
}

# Variables de entorno de USUARIO de Windows (las heredan los procesos que se abran después).
nombre_var_valido() { [[ "$1" =~ ^[A-Z][A-Z0-9_]*$ ]]; }
var_usuario() {
  nombre_var_valido "$1" || fallo "$RC_USO" "nombre de variable no válido: $1"
  powershell.exe -NoProfile -NonInteractive -Command "[Environment]::GetEnvironmentVariable('$1','User')" | tr -d '\r\n'
}
fijar_var_usuario() {  # $1 nombre, $2 valor: el valor viaja en el entorno del proceso, no en la línea de órdenes
  nombre_var_valido "$1" || fallo "$RC_USO" "nombre de variable no válido: $1"
  OFA_VALOR="$2" powershell.exe -NoProfile -NonInteractive -Command \
    "[Environment]::SetEnvironmentVariable('$1', \$env:OFA_VALOR, 'User')"
  [ "$(huella "$(var_usuario "$1")")" = "$(huella "$2")" ] \
    || fallo "$RC_FALLO" "no se pudo fijar la variable de usuario $1."
}
borrar_var_usuario() {
  nombre_var_valido "$1" || fallo "$RC_USO" "nombre de variable no válido: $1"
  powershell.exe -NoProfile -NonInteractive -Command "[Environment]::SetEnvironmentVariable('$1', \$null, 'User')"
  [ -z "$(var_usuario "$1")" ] || fallo "$RC_FALLO" "no se pudo borrar la variable de usuario $1."
}

leer_portapapeles() { powershell.exe -NoProfile -NonInteractive -Command "Get-Clipboard -Raw" | tr -d '\r\n'; }
copiar_portapapeles() { printf '%s' "$1" | clip.exe; }
vaciar_portapapeles() { printf ' ' | clip.exe; }

# Fichero local NO versionado con identificadores (no secretos) que no deben ir al repositorio.
cargar_local() {
  local f="$DIR_PASOS/local.conf" k v
  [ -f "$f" ] || fallo "$RC_USO" "falta $f (no se versiona). Cópialo de local.conf.ejemplo y rellénalo."
  while IFS='=' read -r k v; do
    k="${k%$'\r'}"; v="${v%$'\r'}"
    [[ "$k" =~ ^ROT_[A-Z0-9_]+$ ]] || continue
    printf -v "LOCAL_$k" '%s' "$v"
  done < "$f"
}

# Clave de una cuenta de Cognitive Services (Foundry). Se captura en memoria; nunca se imprime.
clave_cuenta_cs() {  # $1 nombre, $2 grupo, $3 suscripción, $4 key1|key2
  az_r cognitiveservices account keys list -n "$1" -g "$2" --subscription "$3" --query "$4" -o tsv
}
regenerar_cuenta_cs() {  # -o none: la respuesta de regenerate trae las dos claves y no debe imprimirse
  az_r cognitiveservices account keys regenerate -n "$1" -g "$2" --subscription "$3" --key-name "$4" -o none
}
url_prueba_cs() {  # URL de solo lectura que exige clave: lista de modelos de Azure OpenAI de la cuenta
  local ep
  ep="$(az_r cognitiveservices account show -n "$1" -g "$2" --subscription "$3" --query properties.endpoint -o tsv)" \
    || return 1
  printf '%sopenai/models?api-version=2024-10-21' "${ep%/}/"
}

# Sondea hasta que la clave dé uno de los códigos esperados o se acabe el tiempo. Imprime el último código.
esperar_codigo() {  # $1 descripción, $2 nombre cabecera, $3 valor, $4 URL, $5 regex de códigos, $6 segundos
  local fin=$((SECONDS + $6)) c
  while :; do
    c="$(codigo_con_cabecera "$2" "$3" "$4")"
    if [[ "$c" =~ ^($5)$ ]]; then echo "$c"; return 0; fi
    if [ "$SECONDS" -ge "$fin" ]; then echo "$c"; return 1; fi
    progreso "$1: HTTP $c; reintento en 5 s"
    sleep 5
  done
}

# Lee una conexión del proyecto por ARM. Imprime «categoría tipo destino». Devuelve 0 si existe y 4 si ARM
# responde que no existe. Cualquier otro error (red, permisos) falla en alto: nunca se confunde con «no existe».
# Uso: rc=0; x="$(leer_conexion "$URL")" || rc=$?
leer_conexion() {
  local out
  if out="$(az_r rest --method get --url "$1" \
              --query "[properties.category, properties.authType, properties.target]" -o tsv 2>/dev/null)"; then
    printf '%s' "$out" | tr '\n' ' ' | sed 's/ *$//'
    return 0
  fi
  if grep -qiE 'not ?found|\b404\b' "$TMPD/az.err"; then return 4; fi
  printf 'FALLO: no puedo leer la conexión (el error no es «no existe»): %s\n' "$(tr -d '\r' < "$TMPD/az.err" | head -c 300)" >&2
  return 1
}
