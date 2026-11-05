#!/usr/bin/env bash
# Validación local sin Azure: compila y pasa el linter de Bicep a main, plataforma y pilar,
# y comprueba que los parámetros no llevan identificadores reales. Código de salida = veredicto.
set -uo pipefail
cd "$(dirname "$0")"
BICEP="${BICEP:-$(command -v bicep || echo "$HOME/.azure/bin/bicep")}"
[[ -x "$BICEP" ]] || { echo "FALLA: no encuentro la CLI de Bicep (az bicep install)"; exit 2; }
echo "Bicep: $("$BICEP" --version)"
fallos=0
for f in main.bicep plataforma.bicep pilar.bicep; do
  for accion in build lint; do
    if [[ $accion == build ]]; then salida=$("$BICEP" build "$f" --stdout 2>&1 >/dev/null); rc=$?
    else salida=$("$BICEP" lint "$f" 2>&1); rc=$?; fi
    # Cualquier aviso cuenta como fallo: un aviso BCP081/BCP036 es una propiedad que nadie valida.
    if [[ $rc -ne 0 || -n "$salida" ]]; then echo "FALLA  $accion $f"; echo "$salida"; fallos=$((fallos+1))
    else echo "OK     $accion $f"; fi
  done
done
if "$BICEP" build main.bicep --stdout 2>/dev/null | python3 -c '
import json,re,sys
arm=json.load(sys.stdin)["parameters"]; t=open("main.parameters.json").read(); dados=json.loads(t)["parameters"]
faltan=[k for k,v in arm.items() if "defaultValue" not in v and k not in dados]; sobran=[k for k in dados if k not in arm]
guid=re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", t)
print("faltan:", faltan, "sobran:", sobran, "GUID:", bool(guid)); sys.exit(1 if faltan or sobran or guid else 0)'; then
  echo "OK     main.parameters.json (casa con main.bicep, sin GUID)"
else echo "FALLA  main.parameters.json"; fallos=$((fallos+1)); fi
if python3 coste_fijo.py --prueba; then echo "OK     coste_fijo.py --prueba (sin red)"; else echo "FALLA  coste_fijo.py --prueba"; fallos=$((fallos+1)); fi
echo "Veredicto: $([[ $fallos -eq 0 ]] && echo PASA || echo "FALLA ($fallos)")"
exit $(( fallos > 0 ))
