#!/usr/bin/env bash
# 04d · Rotación de la clave de cuenta de servicio de GCP versionada en el repositorio del sistema A2A de pliegos
# (detectada el 07-10-2026; está en el histórico y en la rama principal de su remoto privado). Condición de
# entrada de la fase 1 (diseño §7, «OpenCode»).
#
# Identificadores (no secretos) en pasos-fernando/local.conf, que no se versiona:
#   ROT_GCP_PROYECTO         proyecto de GCP de la cuenta de servicio
#   ROT_GCP_CLAVE_ANTIGUA    ruta del fichero JSON de la clave antigua (del que solo se leen client_email y
#                            private_key_id; la clave privada nunca se imprime)
#   ROT_GCP_CONSUMIDORES     quién la usa
# Dónde se usa (memoria del sistema y lectura del código de aquel repositorio, sin abrir .env ni la clave):
# GOOGLE_APPLICATION_CREDENTIALS (fichero) en local, y GOOGLE_APPLICATION_CREDENTIALS_BASE64 o _JSON en la app
# desplegada, para Vertex AI (generación de PDF) y Google Docs.
#
# Procedimiento (por pasos, para no dejar a nadie sin credencial):
#   estado                       cuenta activa de gcloud, cuenta de servicio y claves con su estado
#   crear --nueva-clave <ruta>   crea una clave NUEVA en <ruta>, que debe estar FUERA de cualquier repositorio git
#                                y fuera de OneDrive. Tú actualizas después a los consumidores con ella
#   desactivar                   desactiva la clave antigua (reversible: gcloud iam service-accounts keys enable)
#   verificar                    comprueba que la antigua ya no consigue token y que figura desactivada o borrada
#   borrar                       borra la antigua (irreversible; tras unos días sin incidencias)
# Equivalente al 401/403: Google rechaza el canje de la clave antigua en su endpoint de tokens con
# «invalid_grant» (HTTP 400). La comprobación exige ese rechazo Y el estado desactivado en la lista de claves.
# Purgar el histórico de aquel repositorio (reescribirlo y forzar el envío) es decisión tuya y no lo hace esto.
#
# Uso: bash pasos-fernando/04d-rotar-clave-gcp.sh [estado|crear|desactivar|verificar|borrar]
#        [--nueva-clave <ruta>] [--confirmar]
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

ACCION="estado"
NUEVA_RUTA=""
while [ $# -gt 0 ]; do
  case "$1" in
    estado|crear|desactivar|verificar|borrar) ACCION="$1" ;;
    --nueva-clave) NUEVA_RUTA="${2:?falta la ruta tras --nueva-clave}"; shift ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,30p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done
cargar_local
PROY_GCP="${LOCAL_ROT_GCP_PROYECTO:-}"
ANTIGUA="${LOCAL_ROT_GCP_CLAVE_ANTIGUA:-}"
[ -z "$ANTIGUA" ] || ANTIGUA="$(ruta_mixta "$ANTIGUA")"
[ -z "$NUEVA_RUTA" ] || NUEVA_RUTA="$(ruta_mixta "$NUEVA_RUTA")"
[[ "$PROY_GCP" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || fallo "$RC_USO" "ROT_GCP_PROYECTO de local.conf no es un id de proyecto de GCP."
[ -f "$ANTIGUA" ] || fallo "$RC_USO" "no encuentro el fichero de la clave antigua (ROT_GCP_CLAVE_ANTIGUA)."
command -v gcloud >/dev/null 2>&1 || fallo "$RC_FALLO" "no encuentro gcloud."

campos_clave() {  # $1 fichero → «client_email private_key_id» (nunca la clave privada)
  "$PY" -I -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
assert d.get("type") == "service_account", "no es una clave de cuenta de servicio"
print(d["client_email"], d["private_key_id"])' "$1" | tr -d '\r'
}
read -r EMAIL ID_ANT < <(campos_clave "$ANTIGUA"; echo) || true
[ -n "${EMAIL:-}" ] && [ -n "${ID_ANT:-}" ] || fallo "$RC_FALLO" "no pude leer client_email y private_key_id de la clave antigua."

gc() { timeout 80 gcloud "$@" --project "$PROY_GCP" --quiet; }
claves() {  # lista «id disabled» de las claves gestionadas por el usuario
  gc iam service-accounts keys list --iam-account "$EMAIL" --managed-by user --format="value(name.basename(),disabled)" | tr -d '\r'
}
estado_antigua() {  # imprime activa | desactivada | borrada; si no puede listar las claves, «error» y rc 1
  local lista l
  lista="$(claves)" || { echo "error"; return 1; }
  l="$(printf '%s\n' "$lista" | awk -v id="$ID_ANT" '$1==id {print $2}')"
  case "${l,,}" in
    '') echo "borrada" ;;
    true) echo "desactivada" ;;
    *) echo "activa" ;;
  esac
}

paso "04d · clave GCP de $EMAIL ($ACCION)"
CUENTA_GC="$(timeout 60 gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | tr -d '\r' | head -1)"
[ -n "$CUENTA_GC" ] || fallo "$RC_FALLO" "gcloud no tiene cuenta activa: ejecuta «gcloud auth login» con una cuenta con permisos en $PROY_GCP."
info "gcloud: cuenta activa $CUENTA_GC · proyecto $PROY_GCP · clave antigua $ID_ANT"
LISTA="$(claves)" || fallo "$RC_FALLO" "no puedo listar las claves de $EMAIL (¿permisos iam.serviceAccountKeys en $PROY_GCP?)."
EST="$(estado_antigua)" || fallo "$RC_FALLO" "no puedo listar las claves de $EMAIL para saber el estado de la antigua."

case "$ACCION" in
estado)
  info "Consumidores conocidos (local.conf): ${LOCAL_ROT_GCP_CONSUMIDORES:-sin anotar}"
  info "Claves gestionadas por el usuario (id, desactivada):"
  printf '%s\n' "$LISTA" | sed 's/^/     /'
  info "Clave antigua $ID_ANT: $EST"
  exit "$RC_OK" ;;

crear)
  [ -n "$NUEVA_RUTA" ] || fallo "$RC_USO" "falta --nueva-clave <ruta> (fuera de repositorios y de OneDrive)."
  [ ! -e "$NUEVA_RUTA" ] || fallo "$RC_USO" "$NUEVA_RUTA ya existe; no se sobrescribe."
  DIR_N="$(cd "$(dirname "$NUEVA_RUTA")" 2>/dev/null && pwd)" || fallo "$RC_USO" "la carpeta de $NUEVA_RUTA no existe."
  case "$DIR_N" in *OneDrive*|*onedrive*) fallo "$RC_USO" "la ruta está dentro de OneDrive (se sincronizaría a la nube)." ;; esac
  if git -C "$DIR_N" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fallo "$RC_USO" "la ruta está dentro de un repositorio git; elige una carpeta fuera."
  fi
  paso "Plan"
  info "Crear una clave nueva para $EMAIL en $DIR_N/$(basename "$NUEVA_RUTA"). La antigua sigue activa hasta «desactivar»."
  confirmar "crear clave nueva de $EMAIL"
  gc iam service-accounts keys create "$NUEVA_RUTA" --iam-account "$EMAIL" >/dev/null 2>"$TMPD/gc.err" \
    || fallo "$RC_FALLO" "gcloud no pudo crear la clave: $(head -c 400 "$TMPD/gc.err")"
  read -r EMAIL_N ID_N < <(campos_clave "$NUEVA_RUTA"; echo) || true
  [ "${EMAIL_N:-}" = "$EMAIL" ] && [ -n "${ID_N:-}" ] && [ "$ID_N" != "$ID_ANT" ] \
    || fallo "$RC_FALLO" "la clave creada no tiene la forma esperada."
  ok "clave nueva $ID_N en $NUEVA_RUTA"
  echo "EN CURSO: actualiza a los consumidores con la clave nueva (${LOCAL_ROT_GCP_CONSUMIDORES:-ver local.conf})."
  echo "En la app desplegada, GOOGLE_APPLICATION_CREDENTIALS_BASE64 = base64 del fichero nuevo (hazlo en tu terminal,"
  echo "no con «!»). Después: bash pasos-fernando/04d-rotar-clave-gcp.sh desactivar"
  exit "$RC_EN_CURSO" ;;

desactivar)
  if [ "$EST" != "activa" ]; then ok "la clave antigua ya está $EST"; exit "$RC_OK"; fi
  OTRAS="$(printf '%s\n' "$LISTA" | awk -v id="$ID_ANT" '$1!=id && tolower($2)!="true" {n++} END {print n+0}')"
  [ "$OTRAS" -ge 1 ] || fallo "$RC_FALLO" "no hay otra clave activa: crea antes la sustituta («crear»), o los consumidores se quedarán sin credencial."
  paso "Plan"
  info "Desactivar la clave antigua $ID_ANT (hay $OTRAS clave(s) activa(s) más). Reversible con «keys enable»."
  confirmar "desactivar la clave $ID_ANT"
  gc iam service-accounts keys disable "$ID_ANT" --iam-account "$EMAIL" >/dev/null 2>"$TMPD/gc.err" \
    || fallo "$RC_FALLO" "gcloud no pudo desactivarla: $(head -c 400 "$TMPD/gc.err")"
  EST_D="$(estado_antigua)" || fallo "$RC_FALLO" "desactivada, pero no puedo listar las claves para comprobarlo."
  [ "$EST_D" = "desactivada" ] || fallo "$RC_FALLO" "la clave no figura desactivada tras la orden (estado: $EST_D)."
  ok "clave $ID_ANT desactivada. Siguiente: bash pasos-fernando/04d-rotar-clave-gcp.sh verificar"
  exit "$RC_OK" ;;

verificar|borrar)
  [ "$EST" != "activa" ] || fallo "$RC_FALLO" "la clave antigua $ID_ANT sigue ACTIVA: ejecuta antes «desactivar»."
  # Canje real de la clave antigua en una configuración de gcloud aislada y desechable (no toca la tuya).
  CFG="$TMPD/gcloud-aislado"; mkdir -p "$CFG"
  RC_A=0
  CLOUDSDK_CONFIG="$CFG" timeout 60 gcloud auth activate-service-account --key-file="$ANTIGUA" --quiet \
    >/dev/null 2>"$TMPD/act.err" || RC_A=$?
  RC_T=0
  if [ "$RC_A" -eq 0 ]; then
    CLOUDSDK_CONFIG="$CFG" timeout 60 gcloud auth print-access-token --quiet >/dev/null 2>"$TMPD/tok.err" || RC_T=$?
  fi
  rm -rf "$CFG"
  if [ "$RC_A" -eq 0 ] && [ "$RC_T" -eq 0 ]; then
    fallo "$RC_FALLO" "la clave antigua TODAVÍA consigue token. Espera unos minutos y repite «verificar»."
  fi
  MOTIVO="$(cat "$TMPD/act.err" "$TMPD/tok.err" 2>/dev/null | grep -oiE 'invalid_grant[^"]{0,80}' | head -1 || true)"
  [ -n "$MOTIVO" ] || fallo "$RC_FALLO" "el canje falló, pero no con invalid_grant: $(cat "$TMPD/act.err" "$TMPD/tok.err" 2>/dev/null | head -c 300)"
  ok "la clave antigua no consigue token: $MOTIVO · estado en GCP: $EST"
  if [ "$ACCION" = "verificar" ]; then exit "$RC_OK"; fi
  if [ "$EST" = "borrada" ]; then ok "la clave antigua ya estaba borrada"; exit "$RC_OK"; fi
  paso "Plan"
  info "BORRAR definitivamente la clave $ID_ANT (irreversible)."
  confirmar "borrar la clave $ID_ANT"
  gc iam service-accounts keys delete "$ID_ANT" --iam-account "$EMAIL" >/dev/null 2>"$TMPD/gc.err" \
    || fallo "$RC_FALLO" "gcloud no pudo borrarla: $(head -c 400 "$TMPD/gc.err")"
  EST_B="$(estado_antigua)" || fallo "$RC_FALLO" "orden de borrado enviada, pero no puedo listar las claves para comprobarlo."
  [ "$EST_B" = "borrada" ] || fallo "$RC_FALLO" "la clave sigue en la lista tras borrarla (estado: $EST_B)."
  ok "clave $ID_ANT borrada"
  exit "$RC_OK" ;;
esac
