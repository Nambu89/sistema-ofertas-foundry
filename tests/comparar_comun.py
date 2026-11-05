"""I1.9 · papel R · VPROT-7: listas mínimas de conexiones y de agentes para las capturas sintéticas de comparar.py.

Base sin conexiones y con un agente ajeno; la captura actual, con exactamente las conexiones autorizadas (con su destino y,
en ARM, su autenticación) y el mismo agente: comparar.py las da IGUAL."""
import json


def conexiones_autorizadas(cmp_mod, arm: bool) -> dict:
    filas = []
    for nombre, (cat, destino, auth) in cmp_mod.CONEXIONES_AUTORIZADAS.items():
        filas.append({"name": nombre, "properties": {"category": cat, "target": destino, "authType": auth}} if arm
                     else {"name": nombre, "type": cat, "target": destino, "credentials": "<OMITIDO>"})
    return {"value": filas} if arm else {"data": filas}


def escribir_listas(cmp_mod, base, ahora, conexiones_ahora=None, agentes_ahora=None) -> None:
    for n in cmp_mod.CONEXIONES:
        arm = n.startswith("arm_")
        (base / n).write_text(json.dumps({"respuesta": {"value": []} if arm else {"data": []}}), encoding="utf-8")
        cuerpo = (conexiones_ahora or {}).get(n, conexiones_autorizadas(cmp_mod, arm))
        (ahora / n).write_text(json.dumps({"respuesta": cuerpo}), encoding="utf-8")
    (base / cmp_mod.AGENTES_LISTA).write_text(json.dumps({"respuesta": {"data": [{"name": "agente-ajeno-ejemplo"}]}}),
                                              encoding="utf-8")
    agentes = agentes_ahora if agentes_ahora is not None else {"data": [{"name": "agente-ajeno-ejemplo"}]}
    (ahora / cmp_mod.AGENTES_LISTA).write_text(json.dumps({"respuesta": agentes}), encoding="utf-8")
