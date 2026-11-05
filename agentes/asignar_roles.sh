#!/usr/bin/env bash
# Asigna con la cuenta del comercial los roles que desbloquean A2A en I0 (lo ejecuta él), por pasos
# para saber qué identidad hace falta (H1/H7 de VERIFICACION-I0.md):
#   consumidor (por defecto) Foundry Agent Consumer a la instance_identity de preventa-coordinador,
#                            sobre el proyecto (la que documenta Learn para agentes del modelo nuevo).
#   compartida               Foundry Agent Consumer a la identidad de agente compartida del proyecto
#                            (agentIdentityId), sobre el proyecto. Solo si «consumidor» no basta.
#   proyecto                 Foundry User a la identidad gestionada del proyecto, sobre la cuenta.
#                            Ningún documento lo pide para A2A: último recurso.
#   todos                    consumidor + proyecto (el comportamiento anterior).
# Uso: agentes/asignar_roles.sh [consumidor|compartida|proyecto|todos]
# Idempotente: si la asignación ya existe, no crea otra. Nunca usa «az account set».
set -euo pipefail
export MSYS_NO_PATHCONV=1
source "$(dirname "$0")/_entorno.sh"
PROYECTO=$PROYECTO_ARM
COORD_OID=${COORD_OID:-$COORD_OID_CONFIG}   # instance_identity de preventa-coordinador
PROY_OID="$(entorno identidad_proyecto_principal_id)"                  # identidad gestionada del proyecto
COMPARTIDA_OID="$(entorno identidad_agente_compartida_id)"  # agentIdentityId compartida del proyecto
AGENT_CONSUMER=eed3b665-ab3a-47b6-8f48-c9382fb1dad6
FOUNDRY_USER=53ca6127-db72-4b80-b1b0-d745d6d5456d

asignar() {  # $1 objectId  $2 rol  $3 ámbito
  local n
  n=$(az role assignment list --assignee "$1" --role "$2" --scope "$3" --subscription "$SUB" --query "length(@)" -o tsv)
  if [ "$n" != "0" ]; then
    echo "Ya existe: rol $2 para $1 en $3"
    return 0
  fi
  az role assignment create --assignee-object-id "$1" --assignee-principal-type ServicePrincipal \
    --role "$2" --scope "$3" --subscription "$SUB" \
    --query "{name:name,principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}" -o json
}

[ "$#" -le 1 ] || { echo "Uso: $0 [consumidor|compartida|proyecto|todos] (un solo argumento)" >&2; exit 2; }
PASO=${1:-consumidor}
case "$PASO" in
  consumidor) asignar "$COORD_OID" "$AGENT_CONSUMER" "$PROYECTO" ;;
  compartida) asignar "$COMPARTIDA_OID" "$AGENT_CONSUMER" "$PROYECTO" ;;
  proyecto)   asignar "$PROY_OID" "$FOUNDRY_USER" "$CUENTA" ;;
  todos)      asignar "$COORD_OID" "$AGENT_CONSUMER" "$PROYECTO"
              asignar "$PROY_OID" "$FOUNDRY_USER" "$CUENTA" ;;
  *) echo "Paso desconocido: $PASO (usa consumidor, compartida, proyecto o todos)" >&2; exit 2 ;;
esac
echo "Hecho $(date '+%d-%m-%Y %H:%M'). La propagación tarda hasta 10 minutos."
