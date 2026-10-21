#!/usr/bin/env bash
# 04c · Rotación de la clave de Azure filtrada en el repositorio de otro proyecto (estuvo versionada en un
# .env.example; se borró del histórico el 21-08-2026, pero sigue VÁLIDA en Azure). Condición de entrada de la
# fase 1 (diseño §7, «OpenCode»).
#
# Qué recurso es y quién lo consume NO se escribe aquí (el repositorio no lleva nombres de clientes): está en
# pasos-fernando/local.conf, que no se versiona (ROT_AZ_RECURSO_ID y ROT_AZ_CONSUMIDORES). Según la memoria
# del sistema de ofertas, la clave puede estar en el .env local (no versionado) de ese otro repositorio y en lo
# que quede del proyecto dueño del recurso; el secreto de la Container App de aquel proyecto apunta a OTRO
# recurso y en principio no le afecta (compruébalo antes).
#
# Como no se sabe cuál de las dos claves (key1 o key2) se filtró sin leer el histórico, se regeneran LAS DOS:
# cualquier consumidor legítimo tendrá que tomar la clave nueva. Se comprueba al final que las dos antiguas
# devuelven 401 o 403. Si Azure tarda en invalidarlas, se guardan en las variables de usuario
# OFA_ROT_AZEXTRA_KEY1_ANTERIOR y OFA_ROT_AZEXTRA_KEY2_ANTERIOR y «verificar» repite la comprobación y las borra.
#
# La clave nueva, si algún consumidor la necesita, la consultas TÚ en una terminal propia (no con «!» en Claude
# Code, porque su salida entra en el chat): az cognitiveservices account keys list --ids <id del recurso>
# Cuando esté verificado, borra también la copia de seguridad del repositorio con el histórico antiguo
# (ruta en ROT_AZ_COPIA_ANTIGUA de local.conf), que todavía contiene la clave.
#
# Uso: bash pasos-fernando/04c-rotar-clave-azure-filtrada.sh [estado|rotar|verificar] [--confirmar]
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

ACCION="estado"
while [ $# -gt 0 ]; do
  case "$1" in
    estado|rotar|verificar) ACCION="$1" ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,24p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done
cargar_local
ID="${LOCAL_ROT_AZ_RECURSO_ID:-}"
RE_ID='^/subscriptions/([0-9a-f-]{36})/resourceGroups/([^/]+)/providers/Microsoft\.CognitiveServices/accounts/([^/]+)$'
[[ "$ID" =~ $RE_ID ]] || fallo "$RC_USO" "ROT_AZ_RECURSO_ID de local.conf no es un id de cuenta de Cognitive Services."
X_SUB="${BASH_REMATCH[1]}"; X_RG="${BASH_REMATCH[2]}"; X_NOMBRE="${BASH_REMATCH[3]}"
[ "$X_NOMBRE" != "$RECURSO" ] || fallo "$RC_USO" "este paso no es para $RECURSO (para esa clave usa 04a)."
RECHAZO='401|403'

paso "04c · clave filtrada del recurso $X_NOMBRE ($ACCION)"
comprobar_az "$X_SUB"
URL="$(url_prueba_cs "$X_NOMBRE" "$X_RG" "$X_SUB")" || fallo "$RC_FALLO" "no puedo leer el endpoint de $X_NOMBRE."

verificar_pendiente() {  # $1 nombre de variable pendiente. 0 si rechazada o vacía, 4 si aún vale
  local v c
  v="$(var_usuario "$1")"
  [ -n "$v" ] || return 0
  if c="$(esperar_codigo "clave antigua $(huella "$v")" api-key "$v" "$URL" "$RECHAZO" 25)"; then
    ok "clave antigua $(huella "$v") ($1) devuelve HTTP $c"
    borrar_var_usuario "$1"
    return 0
  fi
  echo "la clave antigua $(huella "$v") ($1) aún responde HTTP $c"
  return 4
}

if [ "$ACCION" = "verificar" ]; then
  r=0
  verificar_pendiente OFA_ROT_AZEXTRA_KEY1_ANTERIOR || r=$?
  verificar_pendiente OFA_ROT_AZEXTRA_KEY2_ANTERIOR || r=$?
  if [ "$r" -ne 0 ]; then echo "EN CURSO: repite «verificar» en unos minutos."; exit "$RC_EN_CURSO"; fi
  ok "no queda ninguna clave antigua de $X_NOMBRE pendiente de verificar"
  exit "$RC_OK"
fi

K1="$(clave_cuenta_cs "$X_NOMBRE" "$X_RG" "$X_SUB" key1)" || fallo "$RC_FALLO" "no puedo leer las claves de $X_NOMBRE."
K2="$(clave_cuenta_cs "$X_NOMBRE" "$X_RG" "$X_SUB" key2)" || fallo "$RC_FALLO" "no puedo leer las claves de $X_NOMBRE."
paso "Estado"
info "Recurso $X_NOMBRE (grupo $X_RG): key1 huella $(huella "$K1") · key2 huella $(huella "$K2")"
info "Consumidores conocidos (local.conf): ${LOCAL_ROT_AZ_CONSUMIDORES:-sin anotar}"
for p in OFA_ROT_AZEXTRA_KEY1_ANTERIOR OFA_ROT_AZEXTRA_KEY2_ANTERIOR; do
  if [ -n "$(var_usuario "$p")" ]; then info "Pendiente de verificar: $p → ejecuta «verificar»."; fi
done
[ "$ACCION" = "estado" ] && exit "$RC_OK"

# rotar
for p in OFA_ROT_AZEXTRA_KEY1_ANTERIOR OFA_ROT_AZEXTRA_KEY2_ANTERIOR; do
  [ -z "$(var_usuario "$p")" ] || fallo "$RC_FALLO" "hay una rotación anterior sin verificar ($p): ejecuta antes «verificar»."
done
paso "Plan"
info "Se regeneran key2 y key1 de $X_NOMBRE. Todo lo que use cualquiera de las dos dejará de funcionar"
info "hasta que reciba la clave nueva: ${LOCAL_ROT_AZ_CONSUMIDORES:-sin consumidores anotados}."
info "Después se comprueba que las dos claves antiguas devuelven 401 o 403."
confirmar "regenerar las dos claves de $X_NOMBRE"

fijar_var_usuario OFA_ROT_AZEXTRA_KEY2_ANTERIOR "$K2"
regenerar_cuenta_cs "$X_NOMBRE" "$X_RG" "$X_SUB" key2 || fallo "$RC_FALLO" "no se pudo regenerar key2."
ok "key2 regenerada"
fijar_var_usuario OFA_ROT_AZEXTRA_KEY1_ANTERIOR "$K1"
regenerar_cuenta_cs "$X_NOMBRE" "$X_RG" "$X_SUB" key1 || fallo "$RC_FALLO" "no se pudo regenerar key1: la key1 antigua SIGUE VALIENDO."
ok "key1 regenerada"
unset K1 K2
r=0
verificar_pendiente OFA_ROT_AZEXTRA_KEY1_ANTERIOR || r=$?
verificar_pendiente OFA_ROT_AZEXTRA_KEY2_ANTERIOR || r=$?
if [ "$r" -ne 0 ]; then
  echo "EN CURSO: regeneradas, pero falta comprobar el rechazo. Repite en unos minutos:"
  echo "  bash pasos-fernando/04c-rotar-clave-azure-filtrada.sh verificar"
  exit "$RC_EN_CURSO"
fi
echo "Hecho $(date '+%d-%m-%Y %H:%M'). Entrega la clave nueva a los consumidores legítimos desde tu terminal y borra"
echo "la copia de seguridad antigua: ${LOCAL_ROT_AZ_COPIA_ANTIGUA:-sin ruta anotada}."
exit "$RC_OK"
