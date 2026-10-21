#!/usr/bin/env bash
# 05 · Contraseña de «opencode serve» y «opencode web» (OPENCODE_SERVER_PASSWORD) mientras OpenCode siga vivo
# (diseño §7: «opencode serve va con contraseña o apagado»).
#
# Según la documentación de OpenCode (opencode.ai/docs/server, consultada el 18-10-2026): «Set
# OPENCODE_SERVER_PASSWORD to protect the server with HTTP basic auth. The username defaults to opencode, or set
# OPENCODE_SERVER_USERNAME to override it. This applies to both opencode serve and opencode web.»
# Hoy el acceso remoto desde el móvil confía solo en la autenticación del túnel privado; con esto, además, el
# servidor pide usuario y contraseña.
#
# Pasos:
#   fijar [--regenerar]   genera una contraseña aleatoria, la guarda en la variable de USUARIO
#                         OPENCODE_SERVER_PASSWORD y la deja en el PORTAPAPELES para que la guardes en tu gestor
#                         de contraseñas. No se imprime. Si ya existe, no la cambia salvo con --regenerar.
#   verificar [--puerto 4096]
#                         con OpenCode relanzado desde una terminal NUEVA: sin credenciales → 401; con usuario y
#                         contraseña → 200 en /global/health.
#   retirar               borra la variable (cuando OpenCode se apague para siempre).
#   estado                dice si la variable existe y qué responde el servidor local.
# Después de fijar, pide al coordinador del sistema que repita la prueba P5 del paso 0a: que «opencode run» siga
# funcionando con la contraseña puesta está NO VERIFICADO.
#
# Uso: bash pasos-fernando/05-opencode-password.sh [estado|fijar|verificar|retirar] [--regenerar] [--puerto N] [--confirmar]
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

ACCION="estado"
REGENERAR=0
PUERTO=4096
while [ $# -gt 0 ]; do
  case "$1" in
    estado|fijar|verificar|retirar) ACCION="$1" ;;
    --regenerar) REGENERAR=1 ;;
    --puerto) PUERTO="${2:?}"; shift ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,24p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done
[[ "$PUERTO" =~ ^[0-9]{2,5}$ ]] || fallo "$RC_USO" "puerto no válido: $PUERTO"
VAR="OPENCODE_SERVER_PASSWORD"
URL="http://127.0.0.1:$PUERTO/global/health"

paso "05 · $VAR ($ACCION)"
PW="$(var_usuario "$VAR")"
USUARIO="$(var_usuario OPENCODE_SERVER_USERNAME)"
USUARIO="${USUARIO:-opencode}"
sin_credenciales() { curl -s -o "$TMPD/descarte" -w '%{http_code}' --max-time 10 "$URL" || true; }
con_credenciales() {  # usuario y contraseña por la entrada estándar de curl, no por la línea de órdenes
  valor_seguro "$PW" || { echo "000"; return 0; }
  printf 'user = "%s:%s"\n' "$USUARIO" "$PW" | curl -s -K - -o "$TMPD/descarte" -w '%{http_code}' --max-time 10 "$URL" || true
}

case "$ACCION" in
estado)
  if [ -n "$PW" ]; then info "$VAR: definida (${#PW} caracteres) · usuario: $USUARIO"; else info "$VAR: NO definida"; fi
  info "Servidor local en $PUERTO: sin credenciales → HTTP $(sin_credenciales)"
  exit "$RC_OK" ;;

fijar)
  if [ -n "$PW" ] && [ "$REGENERAR" = 0 ]; then
    ok "$VAR ya existe (${#PW} caracteres); no se cambia. Usa --regenerar para crear otra."
    exit "$RC_OK"
  fi
  paso "Plan"
  info "Generar una contraseña aleatoria de 32 caracteres, guardarla en la variable de usuario $VAR y copiarla al portapapeles."
  confirmar "fijar $VAR"
  NUEVA="$("$PY" -I -c 'import secrets; print(secrets.token_urlsafe(24))' | tr -d '\r\n')"
  [ "${#NUEVA}" -ge 32 ] || fallo "$RC_FALLO" "no se pudo generar la contraseña."
  fijar_var_usuario "$VAR" "$NUEVA"
  copiar_portapapeles "$NUEVA"
  ok "$VAR fijada y copiada al portapapeles. Guárdala ahora en tu gestor de contraseñas (usuario: $USUARIO)."
  echo "EN CURSO: cierra OpenCode, ábrelo desde una terminal NUEVA (para que herede la variable) y ejecuta:"
  echo "  bash pasos-fernando/05-opencode-password.sh verificar"
  exit "$RC_EN_CURSO" ;;

verificar)
  [ -n "$PW" ] || fallo "$RC_FALLO" "$VAR no está definida: ejecuta antes «fijar»."
  c1="$(sin_credenciales)"
  if [ "$c1" = "000" ]; then
    echo "EN CURSO: no hay nada escuchando en 127.0.0.1:$PUERTO. Arranca «opencode serve» u «opencode web» desde una"
    echo "terminal nueva y repite (con --puerto si usas otro)."
    exit "$RC_EN_CURSO"
  fi
  [ "$c1" = "401" ] || fallo "$RC_FALLO" "sin credenciales responde HTTP $c1 (se esperaba 401): el servidor no tiene la contraseña; ¿lo abriste desde una terminal nueva?"
  ok "sin credenciales → HTTP 401"
  c2="$(con_credenciales)"
  [ "$c2" = "200" ] || fallo "$RC_FALLO" "con usuario y contraseña responde HTTP $c2 (se esperaba 200)."
  ok "con usuario y contraseña → HTTP 200"
  vaciar_portapapeles
  ok "portapapeles vaciado"
  exit "$RC_OK" ;;

retirar)
  if [ -z "$PW" ]; then ok "$VAR no existe: nada que retirar"; exit "$RC_OK"; fi
  paso "Plan"
  info "Borrar la variable de usuario $VAR (solo cuando OpenCode quede apagado para siempre)."
  confirmar "borrar $VAR"
  borrar_var_usuario "$VAR"
  ok "$VAR borrada"
  exit "$RC_OK" ;;
esac
