#!/usr/bin/env bash
# 01 · Roles de la identidad de ofa-coordinador (lo ejecuta Fernando: el modo automático deniega asignar roles).
#
#   - Foundry Agent Consumer con ámbito POR AGENTE destino (…/projects/<p>/agents/<destino>), uno por
#     especialista: así el coordinador solo puede llamar por A2A a esos agentes, no a todo el proyecto.
#     Fuente del ámbito por agente: learn.microsoft.com/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint
#     («Grant access to the A2A endpoint»), probado en otro proyecto del mismo tenant el 09-10-2026 (diseño §7).
#   - Foundry User sobre el proyecto (diseño §7: SUPUESTO de planificación; se mitiga con la lista blanca de
#     rutas REST del coordinador).
#
# La identidad es la instance_identity del agente, que se lee de Foundry en el momento: no se teclea. Si el
# coordinador se borra y se vuelve a crear, su identidad cambia: hay que retirar los roles de la antigua
# (retirar --principal <guid antiguo>) y asignar de nuevo.
#
# Cuándo se ejecuta: en la fase 1, en cuanto ofa-coordinador esté desplegado, y otra vez cada vez que se
# despliegue un especialista nuevo (es idempotente: lo que ya existe no se repite). Hasta entonces sale con 4.
#
# Uso:
#   bash pasos-fernando/01-roles-coordinador.sh [asignar|retirar|estado] [--coordinador ofa-coordinador]
#        [--destinos "ofa-a ofa-b"] [--principal <guid>  (solo con retirar)] [--confirmar]
source "$(dirname "${BASH_SOURCE[0]}")/comun.sh"

ACCION="asignar"
COORD="$COORD_DEF"
DESTINOS="$AGENTES"
PRINCIPAL_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    asignar|retirar|estado) ACCION="$1" ;;
    --coordinador) COORD="${2:?falta el nombre tras --coordinador}"; shift ;;
    --destinos) DESTINOS="${2:?falta la lista tras --destinos}"; shift ;;
    --principal) PRINCIPAL_ARG="${2:?falta el GUID tras --principal}"; shift ;;
    --confirmar) CONFIRMAR=1 ;;
    -h|--help) sed -n '2,22p' "$0"; exit "$RC_OK" ;;
    *) fallo "$RC_USO" "argumento desconocido: $1" ;;
  esac
  shift
done

GUID_RE='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
nombre_ofa() { [[ "$1" =~ ^ofa-[a-z0-9-]+$ ]] && [[ ! "$1" =~ ^ofa-prueba- ]]; }
nombre_ofa "$COORD" || fallo "$RC_USO" "el coordinador debe llamarse ofa-… (no ofa-prueba-…): «$COORD»."
for d in $DESTINOS; do
  nombre_ofa "$d" || fallo "$RC_USO" "destino no permitido: «$d» (solo agentes ofa-…, nunca ofa-prueba-… ni protegidos)."
  [ "$d" != "$COORD" ] || fallo "$RC_USO" "el coordinador no puede ser destino de sí mismo."
done
if [ -n "$PRINCIPAL_ARG" ] && [ "$ACCION" != "retirar" ]; then
  fallo "$RC_USO" "--principal solo se admite con retirar; para asignar, la identidad se lee del agente."
fi

paso "01 · Roles del coordinador ($ACCION)"
comprobar_az
TOKEN="$(token_datos)" || fallo "$RC_FALLO" "no pude obtener el token de datos de Foundry."

# Lee un agente. Devuelve 0 si existe (deja el JSON en $TMPD/cuerpo), 4 si no existe, 1 si hay otro error.
leer_agente() {
  local c
  c="$(codigo_bearer "$TOKEN" "$EP_PROYECTO/agents/$1?api-version=v1")"
  case "$c" in
    200) return 0 ;;
    404) return 4 ;;
    401|403) fallo "$RC_FALLO" "HTTP $c al leer el agente $1: revisa el login de az (tenant $TENANT)." ;;
    *) fallo "$RC_FALLO" "HTTP $c al leer el agente $1: $(head -c 300 "$TMPD/cuerpo" 2>/dev/null)" ;;
  esac
}

if [ -n "$PRINCIPAL_ARG" ]; then
  PRINCIPAL="$PRINCIPAL_ARG"
  info "Identidad indicada a mano para retirar: $PRINCIPAL"
else
  rc=0; leer_agente "$COORD" || rc=$?
  if [ "$rc" -eq 4 ]; then
    echo "EN CURSO: el agente $COORD aún no existe en $PROYECTO. Este paso se ejecuta en la fase 1, en cuanto"
    echo "el coordinador esté desplegado. No se ha cambiado nada."
    exit "$RC_EN_CURSO"
  fi
  PRINCIPAL="$("$PY" -I -c 'import json,sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
print(((d.get("instance_identity") or {}).get("principal_id")) or "")' "$TMPD/cuerpo" | tr -d '\r')"
  info "Identidad (instance_identity.principal_id) de $COORD: $PRINCIPAL"
fi
[[ "$PRINCIPAL" =~ $GUID_RE ]] || fallo "$RC_FALLO" "la identidad del coordinador no es un GUID válido: «$PRINCIPAL»."

existe_asignacion() {  # $1 rol, $2 ámbito. Compara sin distinguir mayúsculas (ARM puede cambiarlas)
  local lista
  lista="$(az_r role assignment list --assignee "$PRINCIPAL" --role "$1" --scope "$2" --subscription "$SUB" \
             --query "[].scope" -o tsv)" || fallo "$RC_FALLO" "no puedo leer las asignaciones de ${2##*/projects/}; no actúo a ciegas."
  printf '%s\n' "$lista" | grep -Fixq -- "$2"
}

if [ "$ACCION" = "estado" ]; then
  paso "Asignaciones actuales de $PRINCIPAL en la suscripción"
  az_r role assignment list --assignee "$PRINCIPAL" --all --subscription "$SUB" \
    --query "[].{rol:roleDefinitionName, ambito:scope}" -o table || fallo "$RC_FALLO" "no puedo listar las asignaciones."
  echo
  exit "$RC_OK"
fi

# Plan: (rol, ámbito, descripción). En asignar solo entran los destinos que existen.
PLAN_ROL=(); PLAN_AMB=(); PLAN_TXT=(); FALTAN=()
PLAN_ROL+=("$ROL_USER"); PLAN_AMB+=("$ID_PROYECTO"); PLAN_TXT+=("Foundry User · proyecto $PROYECTO")
for d in $DESTINOS; do
  if [ "$ACCION" = "asignar" ]; then
    rc=0; leer_agente "$d" || rc=$?
    if [ "$rc" -eq 4 ]; then FALTAN+=("$d"); continue; fi
  fi
  PLAN_ROL+=("$ROL_CONSUMER"); PLAN_AMB+=("$ID_PROYECTO/agents/$d"); PLAN_TXT+=("Foundry Agent Consumer · agente $d")
done

paso "Plan"
PENDIENTES=0
for i in "${!PLAN_ROL[@]}"; do
  if existe_asignacion "${PLAN_ROL[$i]}" "${PLAN_AMB[$i]}"; then est="existe"; else est="no existe"; fi
  if { [ "$ACCION" = "asignar" ] && [ "$est" = "no existe" ]; } || { [ "$ACCION" = "retirar" ] && [ "$est" = "existe" ]; }; then
    PENDIENTES=$((PENDIENTES + 1)); verbo="$( [ "$ACCION" = asignar ] && echo 'se ASIGNARÁ' || echo 'se RETIRARÁ')"
  else
    verbo="sin cambios ($est)"
  fi
  info "${PLAN_TXT[$i]} → $verbo"
done
for d in "${FALTAN[@]}"; do info "Foundry Agent Consumer · agente $d → el agente aún no existe: se omite"; done

if [ "$PENDIENTES" -gt 0 ]; then
  confirmar "$ACCION $PENDIENTES asignación(es) para $PRINCIPAL"
  for i in "${!PLAN_ROL[@]}"; do
    if [ "$ACCION" = "asignar" ] && ! existe_asignacion "${PLAN_ROL[$i]}" "${PLAN_AMB[$i]}"; then
      az_r role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
        --role "${PLAN_ROL[$i]}" --scope "${PLAN_AMB[$i]}" --subscription "$SUB" -o none \
        || fallo "$RC_FALLO" "no se pudo asignar ${PLAN_TXT[$i]}. El ámbito no se amplía por su cuenta: si Azure no acepta el ámbito por agente, avisa al coordinador del sistema."
      ok "asignado ${PLAN_TXT[$i]}"
    elif [ "$ACCION" = "retirar" ] && existe_asignacion "${PLAN_ROL[$i]}" "${PLAN_AMB[$i]}"; then
      az_r role assignment delete --assignee "$PRINCIPAL" --role "${PLAN_ROL[$i]}" --scope "${PLAN_AMB[$i]}" \
        --subscription "$SUB" -o none || fallo "$RC_FALLO" "no se pudo retirar ${PLAN_TXT[$i]}."
      ok "retirado ${PLAN_TXT[$i]}"
    fi
  done
else
  info "No hay nada que cambiar."
fi

paso "Comprobación"
MAL=0
for i in "${!PLAN_ROL[@]}"; do
  if existe_asignacion "${PLAN_ROL[$i]}" "${PLAN_AMB[$i]}"; then est=1; else est=0; fi
  if { [ "$ACCION" = "asignar" ] && [ "$est" = 1 ]; } || { [ "$ACCION" = "retirar" ] && [ "$est" = 0 ]; }; then
    ok "${PLAN_TXT[$i]}"
  else
    printf 'FALLO: %s no quedó como se esperaba\n' "${PLAN_TXT[$i]}" >&2; MAL=1
  fi
done
[ "$MAL" = 0 ] || exit "$RC_FALLO"
if [ "${#FALTAN[@]}" -gt 0 ]; then
  echo "EN CURSO: faltan por desplegar ${FALTAN[*]}. Repite este paso cuando existan."
  exit "$RC_EN_CURSO"
fi
echo "Hecho $(date '+%d-%m-%Y %H:%M'). Las asignaciones tardan hasta 10 minutos en propagarse."
exit "$RC_OK"
