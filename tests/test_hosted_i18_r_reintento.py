"""I1.8 · papel R · PR17-6 parte 2 y REVERIF17-6 (línea ilegible) en el turno del hosted. Casos adversos.

PR17-6 parte 2: tras un rechazo del núcleo, el reintento lleva delante el motivo literal del rechazo (bloque
REINTENTO-PREVENTA/1 que compone nucleo.brief.texto_envio) y nunca es el brief idéntico; el brief guardado no cambia y el
eco se compara con él. REVERIF17-6: una línea ilegible de a2a.jsonl ya no hace reenviar en silencio.
"""
from __future__ import annotations

import json

from tests.test_hosted_falsos import A2AFalso, coordinador
from tests.test_hosted_turno import ASUMIR, _estado, _hasta_insuficiente
from preventa_hosted import fases

EXPERTO = "preventa-experto-azure"


class A2ARechazada(A2AFalso):
    """Las `n` primeras respuestas del experto salen sin tareas propuestas (el contrato exige al menos una): el núcleo
    las rechaza y suma un intento T2. Se altera también la tarea guardada, así la relectura GetTask coincide."""

    def __init__(self, n: int):
        super().__init__()
        self.romper = n

    def __call__(self, peticion):
        r = super().__call__(peticion)
        cuerpo = json.loads(peticion.content)
        texto = ((cuerpo.get("params") or {}).get("message") or {}).get("parts", [{}])[0].get("text", "")
        if cuerpo.get("method") == "SendMessage" and "BRIEF-PREVENTA/1" in texto and self.romper > 0 and r.status_code == 200:
            self.romper -= 1
            j = r.json()
            tarea = j["result"]["task"]
            resp = json.loads(tarea["artifacts"][0]["parts"][0]["text"])
            resp["tareas_propuestas"] = []
            tarea["artifacts"][0]["parts"][0]["text"] = json.dumps(resp, ensure_ascii=False)
            self.tareas[tarea["id"]] = json.loads(json.dumps(tarea))
            return type(r)(200, json=j)
        return r


def _textos_experto(a2a) -> list[str]:
    return [x["cuerpo"]["params"]["message"]["parts"][0]["text"] for x in a2a.recibidos if x["agente"] == EXPERTO]


def test_reintento_tras_rechazo_lleva_el_motivo_literal_y_no_el_brief_identico(tmp_path, monkeypatch):
    a2a = A2ARechazada(1)
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _hasta_insuficiente(c)
    r = c.manejar(ASUMIR, [])
    est = _estado(c)
    assert est["intentos"]["T2"] == 1 and "tareas_propuestas" in est["fallos"][-1]["error"], r
    brief = est["carga"]["briefs"][-1]
    r = c.manejar("SIGUE", [])
    textos = _textos_experto(a2a)
    assert len(textos) == 2 and textos[0] == brief["texto"] and textos[1] != brief["texto"], r
    assert textos[1].startswith("REINTENTO-PREVENTA/1\n") and textos[1].endswith("\n" + brief["texto"])
    assert est["fallos"][-1]["error"] in textos[1]                    # el motivo, literal
    assert "EXPERTO: VÁLIDA" in r and "motivo literal del último rechazo" in r, r
    assert _estado(c)["carga"]["briefs"][-1]["texto"] == brief["texto"]   # el brief no cambia


def test_tras_un_fallo_a2a_posterior_al_rechazo_el_reenvio_sigue_llevando_el_motivo(tmp_path, monkeypatch):
    import httpx
    a2a = A2ARechazada(1)
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _hasta_insuficiente(c)
    c.manejar(ASUMIR, [])
    motivo = _estado(c)["fallos"][-1]["error"]
    a2a.fallos.append(httpx.Response(503, text="no disponible"))
    c.manejar("SIGUE", [])                                            # fallo A2A (registrar-fallo), no del núcleo
    assert _estado(c)["intentos"]["T2"] == 2
    r = c.manejar("SIGUE", [])
    textos = _textos_experto(a2a)
    assert len(textos) == 3 and all(t.startswith("REINTENTO-PREVENTA/1") and motivo in t for t in textos[1:]), r
    assert "EXPERTO: VÁLIDA" in r, r


def test_sin_rechazo_se_envia_el_brief_tal_cual(tmp_path, monkeypatch):
    a2a = A2AFalso()
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _hasta_insuficiente(c)
    c.manejar(ASUMIR, [])
    assert _textos_experto(a2a) == [_estado(c)["carga"]["briefs"][0]["texto"]]


def test_linea_ilegible_registra_fallo_avisa_y_el_siguiente_sigue_reenvia(tmp_path, monkeypatch):
    import httpx
    a2a = A2AFalso()
    c, _, _ = coordinador(tmp_path, monkeypatch, a2a=a2a)
    _hasta_insuficiente(c)
    a2a.fallos.append(httpx.Response(503, text="no disponible"))
    c.manejar(ASUMIR, [])                                             # T2 1/3 por el 503
    ruta = c.cfg.trabajo / "procedencia" / "a2a.jsonl"
    with open(ruta, "a", encoding="utf-8") as f:
        f.write('{"fase": "T2", "metodo": "SendMessage", "agente": "preventa-exp\n')   # turno interrumpido
    n = len(_textos_experto(a2a))
    r = c.manejar("SIGUE", [])
    assert len(_textos_experto(a2a)) == n and "línea(s) ilegible(s)" in r, r      # no reenvía a ciegas
    est = _estado(c)
    assert est["intentos"]["T2"] == 2 and "ilegible" in est["fallos"][-1]["error"]
    assert "duplicada" in est["fallos"][-1]["hipotesis"]
    aviso = [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()[-1:]][0]
    assert aviso["metodo"] == fases.METODO_ILEGIBLE and aviso["lineas"] and len(aviso["sha256_lineas"]) == 1
    r = c.manejar("SIGUE", [])
    assert len(_textos_experto(a2a)) == n + 1 and "EXPERTO: VÁLIDA" in r, r       # avisada: se reenvía


def test_una_linea_ilegible_nueva_tras_el_aviso_vuelve_a_parar(tmp_path):
    d = tmp_path / "procedencia"
    d.mkdir()
    (d / "a2a.jsonl").write_text("{roto\n", encoding="utf-8")
    try:
        fases.pendiente_previa(tmp_path, "e", "T2", "x")
    except fases.ProcedenciaIlegible as exc:
        fases.avisar_ilegibles(tmp_path, exc, "e", "T2")
    assert fases.pendiente_previa(tmp_path, "e", "T2", "x") is None    # la avisada ya no para
    with open(d / "a2a.jsonl", "a", encoding="utf-8") as f:
        f.write("{otra rota\n")
    try:
        fases.pendiente_previa(tmp_path, "e", "T2", "x")
        raise AssertionError("una línea ilegible nueva tiene que parar")
    except fases.ProcedenciaIlegible as exc:
        assert [n for n, _ in exc.lineas] == [3]
