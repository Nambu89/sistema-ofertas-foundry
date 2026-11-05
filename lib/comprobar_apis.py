"""Comprobación de solo lectura de las APIs que usa I0 (solo GET; no crea ni cambia nada).

Uso: .venv/Scripts/python.exe -m lib.comprobar_apis
Imprime, por cada llamada, el método, la ruta, el api-version y un resumen del resultado.
No imprime tokens ni cabeceras.
"""
from __future__ import annotations

import json
import sys

from lib.foundry import ClienteFoundry, ErrorFoundry


def _probar(nombre: str, fn) -> dict:
    """Ejecuta una lectura y devuelve un resumen sin datos sensibles."""
    try:
        r = fn()
        return {"llamada": nombre, "ok": True, "resumen": r}
    except ErrorFoundry as e:
        return {"llamada": nombre, "ok": False, "estado": e.estado, "error": e.cuerpo[:400]}


def principal() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    c = ClienteFoundry()
    v = c.cfg["api_versions"]
    pruebas = [
        (f"GET /agents?api-version={v['datos_proyecto']}",
         lambda: sorted(a.get("name") for a in c.listar_agentes())),
        (f"GET /agents/agente-ajeno-ejemplo?api-version={v['datos_proyecto']}",
         lambda: {k: c.obtener_agente("agente-ajeno-ejemplo").get(k) for k in ("name", "id", "object")}),
        (f"GET /agents/agente-ajeno-ejemplo/versions?api-version={v['datos_proyecto']}",
         lambda: [(x.get("version"), x.get("definition", {}).get("kind"))
                  for x in c.listar_versiones_agente("agente-ajeno-ejemplo")]),
        ("GET /openai/v1/files (sin api-version)",
         lambda: {"n_ficheros": len(c.listar_ficheros())}),
        (f"GET /deployments?api-version={v['datos_proyecto']}",
         lambda: sorted(d.get("name") for d in c.listar("deployments"))),
        (f"GET /skills/rate-card?api-version={v['datos_proyecto']} (Foundry-Features)",
         lambda: {k: c._datos("GET", "skills/rate-card", preview=True).get(k)
                  for k in ("name", "default_version", "latest_version")}),
        # GET /openai/v1/containers (listado) responde 408 tras ~110 s el 07-10-2026: no se usa.
        # Los contenedores se leen por id (container_file_citation), forma probada en F2.
        (f"GET ARM {c.id_arm_proyecto}/connections?api-version={v['arm_conexiones']}",
         lambda: [(x["name"], x["properties"].get("category"))
                  for x in c._arm("GET", f"{c.id_arm_proyecto}/connections",
                                  v["arm_conexiones"]).get("value", [])]),
        (f"GET ARM conexión inexistente a2a-experto-azure?api-version={v['arm_conexiones']}",
         lambda: {"existe": c.obtener_conexion(c.cfg["conexiones"]["experto_azure"]) is not None}),
        (f"GET ARM {c.id_arm_proyecto}/providers/Microsoft.Authorization/roleAssignments"
         f"?api-version={v['arm_roles']} (filtro principalId de la identidad del proyecto)",
         lambda: {"n": len(c.listar_asignaciones_rol(
             c.id_arm_proyecto, c.cfg["identidad_proyecto_principal_id"]))}),
        (f"GET ARM {c.id_arm_proyecto}?api-version={v['arm_cuenta_proyecto']}",
         lambda: {k: c._arm("GET", c.id_arm_proyecto, v["arm_cuenta_proyecto"]).get(k)
                  for k in ("name", "location")}),
    ]
    resultados = [_probar(n, f) for n, f in pruebas]
    print(json.dumps({"resultados": resultados,
                      "reintentos_anotados": [i.__dict__ for i in c.registro]},
                     ensure_ascii=False, indent=1))
    return 0 if all(r["ok"] for r in resultados) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
