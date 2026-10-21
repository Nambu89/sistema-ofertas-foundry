#!/usr/bin/env bash
# 06 · Cierra la prueba P4b del paso 0a (secreto por conexión en el hosted desplegado por ZIP), que quedó
# PENDIENTE_FERNANDO en pruebas/paso0a/RESULTADOS.md. Requiere la conexión del paso 03.
#
# Lanza el arnés con «--solo P4». La primera vez añade --repetir (P4 ya tiene un resultado guardado) y las
# siguientes NO, para continuar donde iba: --repetir borra el progreso y volvería a empezar el turno largo de
# 6 minutos. Cada invocación del arnés dura unos 85 s como máximo; P4 completa necesita unas 8.
# Códigos del arnés: 0 PASA · 1 FALLA · 2 error del arnés · 3 PENDIENTE_FERNANDO · 4 en curso · 5 autenticación.
# Este script devuelve el del último intento.
#
# Uso: bash pasos-fernando/06-cerrar-p4b.sh [--intentos N] [--confirmar]   (por defecto 1 intento; con «!»
#      conviene repetirlo a mano, y en una terminal propia puede usarse --intentos 10)
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

INTENTOS=1
while [ $# -gt 0 ]; do
  case "$1" in
    --intentos) INTENTOS="${2:?}"; shift ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done
[[ "$INTENTOS" =~ ^[0-9]+$ ]] && [ "$INTENTOS" -ge 1 ] && [ "$INTENTOS" -le 15 ] || fallo "$RC_USO" "--intentos entre 1 y 15"
RES="$RAIZ/pruebas/paso0a/resultados"
PYV="$RAIZ/.venv/Scripts/python.exe"
[ -x "$PYV" ] || fallo "$RC_FALLO" "no encuentro el entorno virtual del repositorio ($PYV)."

paso "06 · Cierre de P4b"
comprobar_az
rc=0; cat_con="$(leer_conexion "$ARM$ID_PROYECTO/connections/ofa-prueba-marcador?api-version=$API_CONEX")" || rc=$?
case "$rc" in
  0) case "$cat_con" in "CustomKeys "*) ;; *) fallo "$RC_FALLO" "ofa-prueba-marcador no es CustomKeys: «$cat_con»." ;; esac ;;
  4) fallo "$RC_FALLO" "la conexión ofa-prueba-marcador no existe: ejecuta antes el paso 03." ;;
  *) exit "$RC_FALLO" ;;
esac
ok "la conexión ofa-prueba-marcador existe"

estado_p4() { "$PY" -I -c 'import json,sys
try: print(json.load(open(sys.argv[1], encoding="utf-8")).get("estado", ""))
except FileNotFoundError: print("")' "$RES/P4.json" | tr -d '\r'; }

paso "Plan"
info "Ejecutar el arnés del paso 0a con --solo P4 hasta $INTENTOS vez/veces mientras salga 4. Solo crea versiones"
info "del agente desechable ofa-prueba-hosted (datos sintéticos); el estado actual de P4 es «$(estado_p4)»."
confirmar "ejecutar P4 del paso 0a"

rc=0
for ((i = 1; i <= INTENTOS; i++)); do
  ARGS=(pruebas/paso0a/ejecutar.py --solo P4)
  if [ ! -f "$RES/P4.progreso.json" ]; then
    if [ "$(estado_p4)" = "PASA" ]; then ok "P4 ya está en PASA"; rc=0; break; fi
    ARGS+=(--repetir)
  fi
  progreso "intento $i de $INTENTOS: ${ARGS[*]}"
  rc=0
  (cd "$RAIZ" && "$PYV" "${ARGS[@]}") || rc=$?
  [ "$rc" -eq 4 ] || break
done

case "$rc" in
  0) ok "P4 cerrada: $(estado_p4). Avisa al coordinador para que actualice RESULTADOS.md." ;;
  4) echo "EN CURSO: P4 sigue sin veredicto. Repite este paso." ;;
  5) echo "Autenticación: ejecuta  ! az login --tenant $TENANT --scope https://ai.azure.com/.default  y repite." ;;
  *) echo "P4 terminó con código $rc ($(estado_p4)). Pasa la salida al coordinador del sistema." ;;
esac
exit "$rc"
