#!/usr/bin/env bash
# 03 · Conexión marcador para la prueba P4b del paso 0a (lo ejecuta Fernando: el modo automático deniega crear
# conexiones con clave, aunque el valor no sea secreto).
#
# Crea en el proyecto la conexión ofa-prueba-marcador de tipo claves personalizadas (CustomKeys) con la clave
# «valor» = «marcador-sintetico». El valor NO es secreto: solo sirve para comprobar que una referencia
# ${{connections.ofa-prueba-marcador.credentials.valor}} llega como variable de entorno al hosted desplegado
# por ZIP (diseño §7). La forma del cuerpo es la de las conexiones CustomKeys que ya existen en el proyecto
# (categoría y tipo leídos de ARM el 18-10-2026). Si ARM la rechaza, créala en el portal: proyecto
# del proyecto → Recursos conectados → Nueva conexión → Claves personalizadas, con los mismos nombre, clave y
# valor, y vuelve a ejecutar este paso para comprobarla.
#
# Después: bash pasos-fernando/06-cerrar-p4b.sh (repite la prueba P4 hasta su veredicto).
# Vuelta atrás: bash pasos-fernando/03-conexion-marcador.sh --borrar --confirmar (cuando P4b esté cerrada).
#
# Uso: bash pasos-fernando/03-conexion-marcador.sh [--borrar] [--confirmar]
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

NOMBRE="ofa-prueba-marcador"
BORRAR=0
while [ $# -gt 0 ]; do
  case "$1" in
    --borrar) BORRAR=1 ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,17p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done
URL="$ARM$ID_PROYECTO/connections/$NOMBRE?api-version=$API_CONEX"

paso "03 · Conexión marcador $NOMBRE"
comprobar_az

estado_conexion() {  # imprime «categoría tipo destino», o nada si ARM dice que no existe; otro error → sale con 1
  local rc=0 x
  x="$(leer_conexion "$URL")" || rc=$?
  case "$rc" in 0) printf '%s' "$x" ;; 4) ;; *) exit "$RC_FALLO" ;; esac
}
ACTUAL="$(estado_conexion)" || exit "$RC_FALLO"

paso "Plan"
if [ "$BORRAR" = 1 ]; then
  if [ -z "$ACTUAL" ]; then ok "la conexión $NOMBRE no existe: nada que borrar"; exit "$RC_OK"; fi
  info "Se BORRA la conexión $NOMBRE ($ACTUAL)."
  confirmar "borrar la conexión $NOMBRE"
  az_r rest --method delete --url "$URL" -o none || fallo "$RC_FALLO" "no se pudo borrar la conexión."
  QUEDA="$(estado_conexion)" || exit "$RC_FALLO"
  [ -z "$QUEDA" ] || fallo "$RC_FALLO" "la conexión sigue existiendo tras borrarla."
  ok "conexión $NOMBRE borrada"
  exit "$RC_OK"
fi
if [ -n "$ACTUAL" ]; then
  info "La conexión ya existe ($ACTUAL): no se toca."
else
  info "Se CREA $NOMBRE: CustomKeys, solo este proyecto, clave «valor» = «marcador-sintetico» (no secreto)."
  confirmar "crear la conexión $NOMBRE"
  printf '%s' '{"properties": {"category": "CustomKeys", "authType": "CustomKeys", "target": "https://learn.microsoft.com", "isSharedToAll": false, "credentials": {"keys": {"valor": "marcador-sintetico"}}, "metadata": {"uso": "prueba P4b del paso 0a (valor no secreto)"}}}' \
    > "$TMPD/marcador.json"
  az_r rest --method put --url "$URL" --body @"$TMPD/marcador.json" -o none \
    || fallo "$RC_FALLO" "ARM rechazó la conexión. Créala en el portal (ver cabecera de este script) y repite para comprobarla."
  ok "conexión creada"
fi

paso "Comprobación"
FINAL="$(estado_conexion)" || exit "$RC_FALLO"
case "$FINAL" in "CustomKeys CustomKeys"*) ;; *) false ;; esac \
  || fallo "$RC_FALLO" "la conexión no tiene la forma esperada: «$FINAL»."
ok "$NOMBRE = $FINAL"
echo "Siguiente: bash pasos-fernando/06-cerrar-p4b.sh"
exit "$RC_OK"
