# Lee el entorno real de config/entorno.local.json (o de $PREVENTA_ENTORNO); se carga con «source».
# Falla en alto si el fichero no existe o si falta una clave: nunca cae a la plantilla de ejemplo.
_RAIZ_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREVENTA_ENTORNO="${PREVENTA_ENTORNO:-$_RAIZ_REPO/config/entorno.local.json}"
if [ ! -f "$PREVENTA_ENTORNO" ]; then
  echo "FALLO: no existe $PREVENTA_ENTORNO; créalo desde config/entorno.ejemplo.json" >&2
  exit 2
fi
entorno() {  # $1 clave (con puntos para anidar)
  python3 -c 'import json, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for k in sys.argv[2].split("."):
    d = d[k]
print(d)' "$PREVENTA_ENTORNO" "$1" || { echo "FALLO: falta la clave $1 en $PREVENTA_ENTORNO" >&2; exit 2; }
}
SUB="$(entorno suscripcion_id)"
CUENTA="/subscriptions/$SUB/resourceGroups/$(entorno grupo_recursos)/providers/Microsoft.CognitiveServices/accounts/$(entorno recurso)"
PROYECTO_ARM="$CUENTA/projects/$(entorno proyecto)"
COORD_OID_CONFIG="$(entorno identidad_coordinador_principal_id)"
