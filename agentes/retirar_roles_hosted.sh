#!/usr/bin/env bash
# Para COMERCIAL: deshace agentes/asignar_roles_hosted.sh. Quita el rol Foundry Agent Consumer
# (eed3b665-ab3a-47b6-8f48-c9382fb1dad6) de la identidad del hosted agent de la opción B sobre
# preventa-experto-azure y preventa-verificador (o sobre el proyecto, con --proyecto).
#
# Uso:   bash agentes/retirar_roles_hosted.sh <principal_id> [--proyecto]
# Idempotente: si la asignación no existe, lo dice y sigue. Nunca usa «az account set».
# Nunca toca las asignaciones del coordinador A (identidad_coordinador_principal_id del entorno), que se rechaza como argumento.
set -euo pipefail
export MSYS_NO_PATHCONV=1
PRINCIPAL="${1:?uso: retirar_roles_hosted.sh <principal_id> [--proyecto]}"
MODO="${2:-agentes}"
source "$(dirname "$0")/../agentes/_entorno.sh"
ROL="eed3b665-ab3a-47b6-8f48-c9382fb1dad6"   # Foundry Agent Consumer
PROY="$PROYECTO_ARM"
if ! [[ "$PRINCIPAL" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "FALLO: «$PRINCIPAL» no es un GUID de principal" >&2; exit 2
fi
if [ "$PRINCIPAL" = "$COORD_OID_CONFIG" ]; then
  echo "FALLO: ese es el coordinador A; este script no retira sus roles." >&2; exit 2
fi
case "$MODO" in
  agentes)    AMBITOS=("${PROY}/agents/preventa-experto-azure" "${PROY}/agents/preventa-verificador") ;;
  --proyecto) AMBITOS=("${PROY}") ;;
  *) echo "FALLO: segundo argumento desconocido «$MODO» (solo --proyecto)" >&2; exit 2 ;;
esac
for AMB in "${AMBITOS[@]}"; do
  IDS=$(az role assignment list --assignee "$PRINCIPAL" --role "$ROL" --scope "$AMB" --subscription "$SUB" \
          --query "[].[id, scope]" -o tsv | tr -d '\r' | awk -F'\t' -v a="$AMB" 'tolower($2)==tolower(a){print $1}')
  if [ -z "$IDS" ]; then
    echo "NO EXISTE (nada que retirar): ${AMB##*/projects/}"
    continue
  fi
  # shellcheck disable=SC2086
  az role assignment delete --ids $IDS --subscription "$SUB"
  echo "RETIRADO: Foundry Agent Consumer · $PRINCIPAL · ${AMB##*/projects/}"
done
echo "== Comprobación: asignaciones que quedan de ese principal en la suscripción"
az role assignment list --assignee "$PRINCIPAL" --all --subscription "$SUB" \
  --query "[].{rol:roleDefinitionName, ambito:scope}" -o table
