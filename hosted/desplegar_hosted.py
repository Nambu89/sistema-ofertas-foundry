"""Para el INTEGRADOR: despliega el ZIP como hosted agent desechable con create_version_from_code (2.8.0).

Sin --confirmar solo comprueba el ZIP e imprime la definición (no toca Azure). Solo admite nombres con el
prefijo «preventa-prueba-». Tenant explícito con AzureCliCredential (LES-G-052); nunca `az account set`.

  hosted/.venv/Scripts/python.exe hosted/desplegar_hosted.py --zip salidas/hosted/preventa-hosted.zip [--confirmar --sha256 <el de empaquetar.py>]

Después: el rol Foundry Agent Consumer para la identidad del agente sobre los agentes destino lo asigna
El comercial (hosted/asignar_roles.sh); el control de permisos de la herramienta deniega esa acción a un agente.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import time
import zipfile
from datetime import datetime

REPO = pathlib.Path(__file__).resolve().parents[1]
# Tenant y proyecto: de config/entorno.local.json (o PREVENTA_ENTORNO); sin él, falla en alto al importar.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib.config import cargar as _cargar_entorno  # noqa: E402

_ENTORNO = _cargar_entorno()
TENANT = _ENTORNO["tenant_id"]
PROYECTO = _ENTORNO["endpoints"]["proyecto"]
ENTORNO = {"PREVENTA_MODELO": "gpt-6-luna", "PREVENTA_EXPERTO": "preventa-experto-azure",
           "PREVENTA_VERIFICADOR": "preventa-verificador", "PREVENTA_A2A_TIMEOUT_S": "110",
           "PREVENTA_MAX_A2A_POR_TURNO": "1"}


def comprobar_zip(ruta: pathlib.Path) -> str:
    """El ZIP debe ser plano y casar con su MANIFIESTO-HOSTED.json. Devuelve su SHA-256."""
    datos = ruta.read_bytes()
    with zipfile.ZipFile(ruta) as z:
        man = json.loads(z.read("MANIFIESTO-HOSTED.json"))
        for nombre, meta in man["ficheros"].items():
            if hashlib.sha256(z.read(nombre)).hexdigest() != meta["sha256"]:
                raise SystemExit(f"FALLO: {nombre} no casa con MANIFIESTO-HOSTED.json")
        if "main.py" not in z.namelist():
            raise SystemExit("FALLO: el ZIP no tiene main.py en la raíz")
    return hashlib.sha256(datos).hexdigest()


def definicion():
    from azure.ai.projects.models import CodeConfiguration, HostedAgentDefinition, ProtocolVersionRecord
    return HostedAgentDefinition(
        cpu="1", memory="2Gi",
        code_configuration=CodeConfiguration(runtime="python_3_13", entry_point=["python", "main.py"],
                                             dependency_resolution="remote_build"),
        protocol_versions=[ProtocolVersionRecord(protocol="responses", version="2.0.0")],
        environment_variables=dict(ENTORNO))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Despliegue del hosted agent desechable de preventa")
    ap.add_argument("--zip", default=str(REPO / "salidas" / "hosted" / "preventa-hosted.zip"))
    ap.add_argument("--nombre", default="preventa-prueba-hosted")
    ap.add_argument("--proyecto", default=PROYECTO)
    ap.add_argument("--tenant", default=TENANT)
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--sha256", default=None, help="SHA-256 que imprimió empaquetar.py (obligatorio con --confirmar)")
    ap.add_argument("--espera-max-s", type=int, default=900)
    a = ap.parse_args(argv)
    if not a.nombre.startswith("preventa-prueba-"):
        raise SystemExit("Solo se despliegan agentes desechables con el prefijo preventa-prueba-")
    ruta = pathlib.Path(a.zip)
    sha = comprobar_zip(ruta)
    print(f"ZIP OK: {ruta} · SHA-256 {sha}")
    print("Definición:", json.dumps(definicion().as_dict(), ensure_ascii=False))
    if not a.confirmar:
        print("Sin --confirmar: no se ha tocado Azure.")
        return 0
    if a.sha256 != sha:   # ancla externa: el manifiesto del ZIP solo prueba coherencia interna
        raise SystemExit(f"FALLO: --sha256 {a.sha256!r} no coincide con el ZIP ({sha}); no despliego")
    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential
    c = AIProjectClient(endpoint=a.proyecto, credential=AzureCliCredential(tenant_id=a.tenant))
    with open(ruta, "rb") as f:
        v = c.agents.create_version_from_code(a.nombre, definition=definicion(), code=f, code_zip_sha256=sha,
                                              description="Coordinador de preventa (opción B), desechable")
    print(f"Versión creada: {v['version']} · estado {v.get('status')}")
    limite, estado = time.monotonic() + a.espera_max_s, v.get("status")
    while estado not in ("active", "failed") and time.monotonic() < limite:
        time.sleep(10)
        v = c.agents.get_version(agent_name=a.nombre, agent_version=v["version"])
        estado = v.get("status")
        print(f"  estado: {estado}")
    detalle = c.agents.get(a.nombre)
    evidencia = {"nombre": a.nombre, "version": v.get("version"), "estado": estado, "zip_sha256": sha,
                 "error": v.get("error"), "agente": detalle.as_dict() if hasattr(detalle, "as_dict") else dict(detalle)}
    salida = REPO / "salidas" / "hosted" / f"despliegue_{datetime.now():%Y%m%d_%H%M%S}.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(evidencia, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Evidencia: {salida} (busca instance_identity.principal_id para asignar los roles)")
    return 0 if estado == "active" else 1


if __name__ == "__main__":
    sys.exit(main())
