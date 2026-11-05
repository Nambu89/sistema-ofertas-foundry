#!/usr/bin/env bash
# Para COMERCIAL (no lo ejecuta ningún agente: el control de permisos lo deniega, LES-G-089.1).
# Da a la identidad del hosted agent desechable el rol Foundry Agent Consumer sobre el proyecto, para que
# pueda llamar por A2A a preventa-experto-azure y preventa-verificador. Uso:
#   bash hosted/asignar_roles.sh <principal_id de instance_identity del hosted agent>
# El principal_id sale en salidas/hosted/despliegue_<fecha>.json (desplegar_hosted.py).
# Para deshacerlo: la misma orden con «az role assignment delete» y los mismos argumentos.
set -euo pipefail
PRINCIPAL="${1:?uso: asignar_roles.sh <principal_id>}"
source "$(dirname "$0")/../agentes/_entorno.sh"
SCOPE="$PROYECTO_ARM"
export MSYS_NO_PATHCONV=1
if [ "$PRINCIPAL" = "$COORD_OID_CONFIG" ]; then
  echo "Ese es el coordinador A: ya tiene el rol. Pasa el principal del hosted agent." >&2; exit 2
fi
az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
  --role "Foundry Agent Consumer" --scope "$SCOPE" --subscription "$SUB" -o table
az role assignment list --assignee "$PRINCIPAL" --scope "$SCOPE" --subscription "$SUB" -o table
