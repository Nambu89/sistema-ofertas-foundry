#!/usr/bin/env bash
# Para COMERCIAL: lo ejecuta él (el control de permisos de la herramienta deniega asignar roles a un agente,
# LES-G-089.1). Da a la identidad del hosted agent de la opción B (preventa-prueba-hosted) el rol
# Foundry Agent Consumer (eed3b665-ab3a-47b6-8f48-c9382fb1dad6) con ÁMBITO EN CADA AGENTE DESTINO:
# preventa-experto-azure y preventa-verificador. Así solo puede llamar a esos dos, no a todo el proyecto.
# Fuente del ámbito por agente (08-10-2026): learn.microsoft.com/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint,
# «Grant access to the A2A endpoint»: «.../projects/<project>/agents/<agent>».
#
# Uso:   bash agentes/asignar_roles_hosted.sh <principal_id>             (ámbito por agente, recomendado)
#        bash agentes/asignar_roles_hosted.sh <principal_id> --proyecto  (solo si el ámbito por agente fallara)
# El principal_id es la identidad del hosted agent (pruebas/I11/INTEGRACION.md, apartado del despliegue de B).
# Idempotente: si la asignación ya existe, no la repite. Nunca usa «az account set». Deshacer:
# agentes/retirar_roles_hosted.sh con los mismos argumentos. La asignación tarda hasta 10 minutos en propagarse.
set -euo pipefail
export MSYS_NO_PATHCONV=1
PRINCIPAL="${1:?uso: asignar_roles_hosted.sh <principal_id> [--proyecto]}"
MODO="${2:-agentes}"
source "$(dirname "$0")/../agentes/_entorno.sh"
ROL="eed3b665-ab3a-47b6-8f48-c9382fb1dad6"   # Foundry Agent Consumer
PROY="$PROYECTO_ARM"
if ! [[ "$PRINCIPAL" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  echo "FALLO: «$PRINCIPAL» no es un GUID de principal" >&2; exit 2
fi
if [ "$PRINCIPAL" = "$COORD_OID_CONFIG" ]; then
  echo "FALLO: ese es el coordinador A, que ya tiene el rol sobre el proyecto. Pasa el principal del hosted agent." >&2; exit 2
fi
case "$MODO" in
  agentes)    AMBITOS=("${PROY}/agents/preventa-experto-azure" "${PROY}/agents/preventa-verificador") ;;
  --proyecto) AMBITOS=("${PROY}")
              echo "AVISO: ámbito de PROYECTO: la identidad podrá llamar a cualquier agente de proyecto-ejemplo." >&2 ;;
  *) echo "FALLO: segundo argumento desconocido «$MODO» (solo --proyecto)" >&2; exit 2 ;;
esac
existe() {  # $1 = ámbito; compara sin distinguir mayúsculas (ARM puede devolver otra capitalización)
  local lista
  if ! lista=$(az role assignment list --assignee "$PRINCIPAL" --role "$ROL" --scope "$1" --subscription "$SUB" \
                 --query "[].scope" -o tsv); then
    echo "FALLO: no se pudieron leer las asignaciones de ${1##*/projects/}; no asigno a ciegas." >&2
    exit 1
  fi
  printf '%s\n' "$lista" | tr -d '\r' | grep -Fixq -- "$1"
}
for AMB in "${AMBITOS[@]}"; do
  if existe "$AMB"; then
    echo "YA EXISTE: Foundry Agent Consumer · $PRINCIPAL · ${AMB##*/projects/}"
    continue
  fi
  if ! az role assignment create --assignee-object-id "$PRINCIPAL" --assignee-principal-type ServicePrincipal \
        --role "$ROL" --scope "$AMB" --subscription "$SUB" -o none; then
    echo "FALLO al asignar sobre ${AMB##*/projects/}. Si el error dice que el ámbito no es válido," >&2
    echo "repite con --proyecto (y anótalo en ROLLBACK-I1.md). El ámbito no se amplía por su cuenta." >&2
    exit 1
  fi
  echo "ASIGNADO: Foundry Agent Consumer · $PRINCIPAL · ${AMB##*/projects/}"
done
echo "== Comprobación: asignaciones de ese principal en la suscripción"
az role assignment list --assignee "$PRINCIPAL" --all --subscription "$SUB" \
  --query "[].{rol:roleDefinitionName, ambito:scope}" -o table
