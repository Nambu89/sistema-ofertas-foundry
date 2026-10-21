#!/usr/bin/env bash
# 04b · Rotación de NVIDIA_API_KEY (clave de build.nvidia.com expuesta en un chat al añadir el proveedor
# «nvidia» a OpenCode en junio de 2026). Condición de entrada de la fase 1 (diseño §7, «OpenCode»).
#
# Dónde se usa (BACKLOG, bloque 26, y memoria; esto no lee ningún .env):
#   - Variable de entorno de USUARIO de Windows NVIDIA_API_KEY.
#   - opencode.json del espacio de ofertas: proveedor «nvidia» (baseURL https://integrate.api.nvidia.com/v1,
#     apiKey {env:NVIDIA_API_KEY}); lo usó el agente researcher en la prueba entre nubes.
#
# NVIDIA no tiene CLI para claves: la nueva se crea y la antigua se revoca en el portal (build.nvidia.com,
# apartado de claves de API de tu cuenta). El script nunca te pide que la escribas ni la pegues en el chat:
# la toma del PORTAPAPELES.
#
# Procedimiento:
#   1. En el portal, genera una clave nueva y cópiala (queda en el portapapeles).
#   2. bash pasos-fernando/04b-rotar-nvidia-key.sh rotar --confirmar
#      Lee la nueva del portapapeles, comprueba que funciona, guarda la antigua en la variable de usuario
#      OFA_ROT_NVIDIA_ANTERIOR (mismo almacén donde ya estaba), fija NVIDIA_API_KEY y vacía el portapapeles.
#   3. En el portal, REVOCA la clave antigua.
#   4. bash pasos-fernando/04b-rotar-nvidia-key.sh verificar
#      Comprueba que la antigua devuelve 401 o 403 y borra OFA_ROT_NVIDIA_ANTERIOR.
#
# Cómo se comprueba: /v1/models de NVIDIA es público (responde 200 sin clave), así que se usa
# /v1/chat/completions con un modelo vigente. Primero se calibra con una clave inválida a propósito: solo vale
# un modelo para el que la clave inválida da 401 o 403 (los modelos retirados dan 410 antes de mirar la clave).
#
# Uso: bash pasos-fernando/04b-rotar-nvidia-key.sh [estado|rotar|verificar] [--confirmar]
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

ACCION="estado"
while [ $# -gt 0 ]; do
  case "$1" in
    estado|rotar|verificar) ACCION="$1" ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,29p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done
VAR="NVIDIA_API_KEY"
PEND="OFA_ROT_NVIDIA_ANTERIOR"
URL="https://integrate.api.nvidia.com/v1/chat/completions"
CANDIDATOS=(google/gemma-3-4b-it nvidia/nemotron-nano-3-30b-a3b nvidia/nemotron-3.5-lightning-30b-a3b)

probar() {  # $1 clave, $2 modelo → código HTTP
  codigo_con_cabecera "Authorization" "Bearer $1" "$URL" POST \
    "{\"model\":\"$2\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":1}"
}
MODELO=""
calibrar() {
  local m c
  for m in "${CANDIDATOS[@]}"; do
    c="$(probar "nvapi-invalida-calibracion-ofa" "$m")"
    if [[ "$c" =~ ^(401|403)$ ]]; then MODELO="$m"; info "modelo de prueba: $m (clave inválida → HTTP $c)"; return 0; fi
    progreso "modelo $m descartado (clave inválida → HTTP $c)"
  done
  fallo "$RC_FALLO" "ningún modelo candidato rechaza una clave inválida con 401/403; actualiza CANDIDATOS con uno vigente de /v1/models."
}

paso "04b · $VAR ($ACCION)"
command -v curl >/dev/null || fallo "$RC_FALLO" "no encuentro curl."
calibrar
ACT="$(var_usuario "$VAR")"

if [ "$ACCION" = "estado" ]; then
  if [ -z "$ACT" ]; then aviso "la variable de usuario $VAR está vacía."; else
    info "$VAR: huella $(huella "$ACT") → HTTP $(probar "$ACT" "$MODELO")"; fi
  ANT="$(var_usuario "$PEND")"
  if [ -n "$ANT" ]; then info "Clave antigua pendiente de verificar: huella $(huella "$ANT") → ejecuta «verificar»."; fi
  exit "$RC_OK"
fi

if [ "$ACCION" = "verificar" ]; then
  ANT="$(var_usuario "$PEND")"
  [ -n "$ANT" ] || fallo "$RC_FALLO" "no hay clave antigua guardada en $PEND: ejecuta antes «rotar»."
  c="$(probar "$ANT" "$MODELO")"
  if [[ ! "$c" =~ ^(401|403)$ ]]; then
    echo "EN CURSO: la clave antigua $(huella "$ANT") responde HTTP $c. Revócala en el portal y repite «verificar»."
    exit "$RC_EN_CURSO"
  fi
  ok "la clave antigua $(huella "$ANT") devuelve HTTP $c"
  c="$(probar "$ACT" "$MODELO")"
  [ "$c" = "200" ] || fallo "$RC_FALLO" "la clave actual de $VAR ($(huella "$ACT")) responde HTTP $c; no borro la antigua guardada."
  ok "la clave actual de $VAR ($(huella "$ACT")) responde HTTP 200"
  borrar_var_usuario "$PEND"
  ok "variable $PEND borrada. Abre una terminal nueva antes de volver a usar OpenCode."
  exit "$RC_OK"
fi

# rotar
[ -z "$(var_usuario "$PEND")" ] || fallo "$RC_FALLO" "hay una rotación anterior sin verificar: ejecuta antes «verificar»."
NUEVA="$(leer_portapapeles)"
[[ "$NUEVA" =~ ^nvapi-[A-Za-z0-9_-]{20,}$ ]] \
  || fallo "$RC_USO" "el portapapeles no contiene una clave de NVIDIA (nvapi-…). Cópiala del portal y repite."
[ "$NUEVA" != "$ACT" ] || fallo "$RC_USO" "la clave del portapapeles es la misma que ya tienes en $VAR."

paso "Plan"
info "Clave actual: huella $(huella "${ACT:-}") · clave nueva del portapapeles: huella $(huella "$NUEVA")."
info "Se comprueba la nueva, la antigua se guarda en $PEND, $VAR pasa a la nueva y se vacía el portapapeles."
confirmar "rotar $VAR"

c="$(probar "$NUEVA" "$MODELO")"
[ "$c" = "200" ] || fallo "$RC_FALLO" "la clave nueva responde HTTP $c: no se ha cambiado nada."
ok "la clave nueva responde HTTP 200"
if [ -n "$ACT" ]; then fijar_var_usuario "$PEND" "$ACT"; fi
fijar_var_usuario "$VAR" "$NUEVA"
vaciar_portapapeles
ok "$VAR actualizada y portapapeles vaciado"
echo "EN CURSO: ahora REVOCA la clave antigua (huella $(huella "${ACT:-}")) en el portal de NVIDIA y ejecuta:"
echo "  bash pasos-fernando/04b-rotar-nvidia-key.sh verificar"
exit "$RC_EN_CURSO"
