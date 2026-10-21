#!/usr/bin/env bash
# 04a · Rotación de AZURE_FOUNDRY_KEY (clave del recurso Foundry de la configuración local, expuesta en un chat durante la
# configuración de OpenCode). Condición de entrada de la fase 1 (diseño §7, «OpenCode»).
#
# Dónde se usa (BACKLOG y memoria del sistema de ofertas; esto no lee ningún .env):
#   - Variable de entorno de USUARIO de Windows AZURE_FOUNDRY_KEY, que heredan Claude Code, OpenCode y Codex.
#   - opencode.json del espacio de ofertas: proveedor «foundry» con apiKey {env:AZURE_FOUNDRY_KEY} y, si se
#     configuró así, la cabecera api-key del MCP foundry-skills.
#   - Codex CLI (~/.codex/config.toml): env_key = "AZURE_FOUNDRY_KEY". Ojo: la revisión obligatoria con Codex
#     usa esta clave; tras rotar, Codex solo funciona en procesos abiertos DESPUÉS de la rotación.
#   - Los agentes del proyecto (ofa-* y los de otros proyectos del mismo recurso) usan Entra, no la clave. Este script lista además las
#     conexiones del proyecto de tipo ApiKey por si alguna apuntara al propio recurso.
#
# Procedimiento (rotar), todo con tu sesión de az y sin imprimir claves:
#   1. Identifica cuál de las dos claves del recurso (key1 o key2) es la de la variable.
#   2. Regenera la OTRA, comprueba que la nueva responde 200 y la guarda en AZURE_FOUNDRY_KEY.
#   3. Regenera la que estaba en uso: la antigua deja de valer. Comprueba que devuelve 401 o 403.
#   Si Azure tarda en invalidarla, la antigua se guarda en la variable de usuario OFA_ROT_FOUNDRY_ANTERIOR
#   (el mismo almacén donde ya estaba) y «verificar» repite la comprobación y la borra.
#
# Antes de rotar: cierra OpenCode y Codex. Después: abre una terminal nueva y vuelve a abrir Claude Code,
# OpenCode y Codex, porque los procesos abiertos conservan la clave antigua.
#
# Uso: bash pasos-fernando/04a-rotar-azure-foundry-key.sh [estado|rotar|verificar] [--confirmar]
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

ACCION="estado"
while [ $# -gt 0 ]; do
  case "$1" in
    estado|rotar|verificar) ACCION="$1" ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,26p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done
VAR="AZURE_FOUNDRY_KEY"
PEND="OFA_ROT_FOUNDRY_ANTERIOR"
RECHAZO='401|403'

paso "04a · $VAR ($ACCION) · recurso $RECURSO"
comprobar_az
URL="$(url_prueba_cs "$RECURSO" "$RG" "$SUB")" || fallo "$RC_FALLO" "no puedo leer el endpoint de $RECURSO."

if [ "$ACCION" = "verificar" ]; then
  ANT="$(var_usuario "$PEND")"
  if [ -z "$ANT" ]; then
    ok "no hay ninguna clave antigua pendiente de verificar ($PEND vacía)."
  else
    c="$(esperar_codigo "clave antigua $(huella "$ANT")" api-key "$ANT" "$URL" "$RECHAZO" 40)" || {
      echo "EN CURSO: la clave antigua $(huella "$ANT") aún responde HTTP $c. Repite «verificar» en unos minutos."
      exit "$RC_EN_CURSO"; }
    ok "la clave antigua $(huella "$ANT") devuelve HTTP $c"
    borrar_var_usuario "$PEND"
    ok "variable $PEND borrada"
  fi
  ACT="$(var_usuario "$VAR")"
  c="$(codigo_con_cabecera api-key "$ACT" "$URL")"
  [ "$c" = "200" ] || fallo "$RC_FALLO" "la clave actual de $VAR ($(huella "$ACT")) responde HTTP $c."
  ok "la clave actual de $VAR ($(huella "$ACT")) responde HTTP 200"
  exit "$RC_OK"
fi

ACT="$(var_usuario "$VAR")"
[ -n "$ACT" ] || fallo "$RC_FALLO" "la variable de usuario $VAR está vacía."
K1="$(clave_cuenta_cs "$RECURSO" "$RG" "$SUB" key1)" || fallo "$RC_FALLO" "no puedo leer las claves del recurso."
K2="$(clave_cuenta_cs "$RECURSO" "$RG" "$SUB" key2)" || fallo "$RC_FALLO" "no puedo leer las claves del recurso."
if [ "$ACT" = "$K1" ]; then EN_USO="key1"; OTRA="key2"
elif [ "$ACT" = "$K2" ]; then EN_USO="key2"; OTRA="key1"
else EN_USO=""; OTRA=""; fi

paso "Estado"
info "$VAR (variable de usuario): huella $(huella "$ACT")"
info "key1 del recurso: huella $(huella "$K1") · key2: huella $(huella "$K2")"
if [ -n "$EN_USO" ]; then info "La variable coincide con la $EN_USO."; else aviso "la variable no coincide con ninguna clave del recurso."; fi
info "La clave de la variable responde HTTP $(codigo_con_cabecera api-key "$ACT" "$URL") en $URL"

# Copias literales de la clave en ficheros de configuración conocidos (solo se imprimen rutas). La clave llega
# a grep por un descriptor, no por la línea de órdenes.
COPIAS=()
FICHEROS=("$HOME/.codex/config.toml" "$HOME/.config/opencode/opencode.json" "$HOME/.config/opencode/opencode.jsonc")
if [ -f "$DIR_PASOS/local.conf" ]; then
  cargar_local
  IFS=';' read -r -a EXTRA <<< "${LOCAL_ROT_FICHEROS_CONFIG:-}"
  FICHEROS+=("${EXTRA[@]}")
fi
for f in "${FICHEROS[@]}"; do
  [ -n "$f" ] && [ -f "$f" ] || continue
  if grep -qF "$VAR" "$f"; then info "usa la variable por nombre: $f"; fi
  if grep -qF -f <(printf '%s\n' "$ACT") "$f"; then COPIAS+=("$f"); fi
done
for f in "${COPIAS[@]}"; do aviso "copia LITERAL de la clave en $f: sustitúyela por {env:$VAR} antes de rotar."; done
CONEX="$(az_r rest --method get --url "$ARM$ID_PROYECTO/connections?api-version=$API_CONEX" \
  --query "value[?properties.authType=='ApiKey' && contains(properties.target, '$RECURSO')].name" -o tsv || true)"
if [ -n "$CONEX" ]; then aviso "conexiones ApiKey del proyecto que apuntan a $RECURSO: $CONEX (habrá que actualizarlas)."; fi
ABIERTOS="$(tasklist 2>/dev/null | grep -iE '^(opencode|codex)' | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"
if [ -n "$ABIERTOS" ]; then aviso "procesos abiertos que conservan la clave antigua: $ABIERTOS"; fi

if [ "$ACCION" = "estado" ]; then
  PEND_V="$(var_usuario "$PEND")"
  if [ -n "$PEND_V" ]; then info "Hay una clave antigua pendiente de verificar: ejecuta «verificar»."; fi
  exit "$RC_OK"
fi

# rotar
[ -n "$EN_USO" ] || fallo "$RC_FALLO" "no sé qué clave rotar: la variable no coincide con key1 ni con key2."
[ "${#COPIAS[@]}" -eq 0 ] || fallo "$RC_FALLO" "hay copias literales de la clave; corrígelas primero (se romperían en silencio)."
[ -z "$(var_usuario "$PEND")" ] || fallo "$RC_FALLO" "hay una rotación anterior sin verificar: ejecuta antes «verificar»."

paso "Plan"
info "1. Regenerar la $OTRA de $RECURSO y comprobar que responde 200."
info "2. Guardarla en la variable de usuario $VAR."
info "3. Regenerar la $EN_USO (la de ahora, huella $(huella "$ACT")) y comprobar que la antigua devuelve 401 o 403."
info "Cierra OpenCode y Codex antes de seguir."
confirmar "rotar $VAR"

regenerar_cuenta_cs "$RECURSO" "$RG" "$SUB" "$OTRA" || fallo "$RC_FALLO" "no se pudo regenerar la $OTRA (no se ha tocado la variable)."
NUEVA="$(clave_cuenta_cs "$RECURSO" "$RG" "$SUB" "$OTRA")" || fallo "$RC_FALLO" "no puedo leer la $OTRA nueva."
c="$(esperar_codigo "clave nueva" api-key "$NUEVA" "$URL" '200' 25)" \
  || fallo "$RC_FALLO" "la $OTRA nueva responde HTTP $c; la variable sigue con la clave de antes, que aún vale."
ok "$OTRA nueva (huella $(huella "$NUEVA")) responde HTTP 200"
fijar_var_usuario "$VAR" "$NUEVA"
ok "$VAR actualizada"

# La clave antigua se apunta como pendiente de verificar solo cuando la regeneración ha ido bien. Si falla, no
# queda nada pendiente y «rotar» se puede repetir: $VAR ya usa la $OTRA nueva, así que el siguiente «rotar»
# regenera la $EN_USO (la antigua deja de valer) y vuelve a rotar la $OTRA.
regenerar_cuenta_cs "$RECURSO" "$RG" "$SUB" "$EN_USO" \
  || fallo "$RC_FALLO" "no se pudo regenerar la $EN_USO: la clave antigua SIGUE VALIENDO, aunque $VAR ya usa la $OTRA nueva. Revisa el error y repite «rotar»."
fijar_var_usuario "$PEND" "$ACT"
if c="$(esperar_codigo "clave antigua" api-key "$ACT" "$URL" "$RECHAZO" 30)"; then
  ok "la clave antigua $(huella "$ACT") devuelve HTTP $c"
  borrar_var_usuario "$PEND"
  echo "Hecho $(date '+%d-%m-%Y %H:%M'). Abre una terminal nueva y vuelve a abrir Claude Code, OpenCode y Codex."
  exit "$RC_OK"
fi
echo "EN CURSO: la $EN_USO ya está regenerada pero la clave antigua aún responde HTTP $c (propagación)."
echo "Repite en unos minutos: bash pasos-fernando/04a-rotar-azure-foundry-key.sh verificar"
exit "$RC_EN_CURSO"
