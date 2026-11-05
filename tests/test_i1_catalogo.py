"""Pruebas sin red del catálogo de referencias Azure (BD, I1) y de su derivación."""
from __future__ import annotations

import ast
import json
import pathlib
import re
import socket
import sys
import unicodedata
import urllib.error

import pytest

from catalogo import comprobar_catalogo as cc
from catalogo import derivar
from esquemas import comprobar_esquemas as ce
from tests.i17_e_comun import ARGS_EFECTIVO, DERIVADO_EFECTIVO, ESQ_EFECTIVO  # noqa: E402  (I1.7)

RAIZ = pathlib.Path(__file__).resolve().parent.parent
CAT = derivar.cargar()
COMPS = CAT["componentes"]
ESQ_FUENTE = json.loads((RAIZ / "catalogo" / "esquema_catalogo_referencias.json").read_text(encoding="utf-8"))
ESQ_SANDBOX = json.loads((RAIZ / "esquemas" / "catalogo_componentes.json").read_text(encoding="utf-8"))
CONTRATOS = (RAIZ / "docs" / "I1" / "CONTRATOS.md").read_text(encoding="utf-8")

# CONTRATOS.md §0 (réplica: el barrido único es textos_cliente.marcadores, de C).
_MAYUS = re.compile(r"\b(TBD|TODO|XXX|PLACEHOLDER)\b")
_PALABRAS = re.compile(r"\b(pendiente|pendientes|por definir|lorem)\b")
_ANGULOS = re.compile(r"<[^<>\n]{1,60}>")


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


def marcadores(texto: str) -> list[str]:
    return (_MAYUS.findall(texto) + _PALABRAS.findall(_sin_tildes(texto)) + _ANGULOS.findall(texto))


def _cadenas(o: object):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _cadenas(v)
    elif isinstance(o, list):
        for v in o:
            yield from _cadenas(v)


def test_esquema_fuente_usa_solo_el_subconjunto():
    assert ce.palabras_no_admitidas(ESQ_FUENTE) == []


def test_catalogo_valida_contra_su_esquema():
    assert ce.validar(CAT, ESQ_FUENTE, ESQ_FUENTE) == []


def test_ids_y_nombres_unicos():
    ids = [c["id"] for c in COMPS]
    nombres = [c["nombre_oficial"] for c in COMPS]
    assert len(ids) == len(set(ids))
    assert len(nombres) == len(set(nombres))


def test_cada_componente_tiene_una_url_y_solo_una():
    for c in COMPS:
        assert bool(c["referencia_url"]) != bool(c["referencia_url_propuesta"]), c["id"]


def test_urls_normalizadas():
    for c in COMPS:
        for u in (c["referencia_url"], c["referencia_url_propuesta"]):
            if u:
                assert derivar.normalizar_url(u) == u, (c["id"], u)


def test_referencias_en_lista_blanca():
    for c in COMPS:
        if c["referencia_url"]:
            assert derivar.en_lista_blanca(c["referencia_url"]), c["id"]


def test_propuestas_fuera_de_lista_blanca_declaradas():
    for c in COMPS:
        if c["referencia_url_propuesta"]:
            assert not derivar.en_lista_blanca(c["referencia_url_propuesta"]), c["id"]
            assert c["nota"] and "lista blanca" in c["nota"], c["id"]


def test_comprobacion_de_hoy_completa():
    for c in COMPS:
        k = c["comprobacion"]
        assert k["fecha"] >= CAT["fecha"], c["id"]  # I1.6: los servicios nuevos se comprobaron el 2026-10-11
        assert k["url_http"] == 200, c["id"]
        assert k["url_titulo"] and not cc.SOFT_404.search(k["url_titulo"]), c["id"]
        if c["service_name_precios"]:
            assert k["precios_items"] and k["precios_items"] > 0, c["id"]
        else:
            assert k["precios_items"] is None and c["producto_precios"] is None, c["id"]
            assert c["nota"], f"{c['id']}: sin serviceName hay que declarar por qué"


def test_service_names_reales_conocidos():
    sn = {c["id"]: c["service_name_precios"] for c in COMPS}
    assert sn["az-ai-search"] == "Azure Cognitive Search"
    assert sn["az-foundry"] == "Foundry Models"
    assert sn["az-fabric"] == "Microsoft Fabric"
    assert sn["az-private-link"] == "Virtual Network"


def test_sin_marcadores():
    for s in _cadenas(CAT):
        assert marcadores(s) == [], s


def test_barrido_de_marcadores_por_palabra_completa():
    assert marcadores("Revisión independiente de todos los precios") == []
    assert marcadores("Precio pendiente") == ["pendiente"]
    assert marcadores("Valor TBD") == ["TBD"]
    assert marcadores("Use <valor>") == ["<valor>"]


def test_prefijos_iguales_a_contratos():
    seccion = CONTRATOS.split("### 6.3", 1)[1].split("### 6.4", 1)[0].split("- **Arquitectura**", 1)[1]
    arq, serv = seccion.split("- **Servicio**", 1)
    serv, ampl = serv.split("- **Ampliación de referencias**", 1)
    rutas = lambda t: tuple(re.findall(r"`(/[a-z0-9/.-]+)`", t))
    assert derivar.PREFIJOS_ARQUITECTURA == rutas(arq)
    assert derivar.PREFIJOS_SERVICIO == rutas(serv)
    assert derivar.PREFIJOS_REFERENCIA_AMPLIACION == rutas(ampl)


def _prefijos_de_nucleo() -> dict[str, tuple[str, ...]]:
    """Lee las tuplas de sandbox/nucleo/experto.py (A) con ast, sin importarlo."""
    ruta = RAIZ / "sandbox" / "nucleo" / "experto.py"
    if not ruta.exists():
        pytest.skip("sandbox/nucleo/experto.py (de A) todavía no existe")
    valores: dict[str, tuple[str, ...]] = {}
    for nodo in ast.parse(ruta.read_text(encoding="utf-8")).body:
        if isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name) and nodo.value is not None:
            nombre, expr = nodo.target.id, nodo.value
        elif isinstance(nodo, ast.Assign) and len(nodo.targets) == 1 and isinstance(nodo.targets[0], ast.Name):
            nombre, expr = nodo.targets[0].id, nodo.value
        else:
            continue
        if nombre.startswith("PREFIJOS_"):
            if isinstance(expr, ast.BinOp) and isinstance(expr.left, ast.Name):
                valores[nombre] = valores[expr.left.id] + ast.literal_eval(expr.right)
            else:
                valores[nombre] = ast.literal_eval(expr)
    return valores


def test_prefijos_iguales_a_los_de_nucleo():
    v = _prefijos_de_nucleo()
    assert v["PREFIJOS_ARQUITECTURA"] == derivar.PREFIJOS_ARQUITECTURA
    ampl = set(derivar.PREFIJOS_REFERENCIA_AMPLIACION)
    assert set(v["PREFIJOS_REFERENCIA"]) in (set(derivar.PREFIJOS_SERVICIO) | ampl,
                                             set(derivar.PREFIJOS_SERVICIO) | set(derivar.PREFIJOS_ARQUITECTURA) | ampl)


URLS_MUESTRA = [
    "https://learn.microsoft.com/en-us/azure/Search/Overview/?view=x#y",
    "https://learn.microsoft.com/zh-hans/azure/search//overview",
    "https://learn.microsoft.com:443/azure/search",
    "https://usuario@learn.microsoft.com/azure/search",
    "HTTPS://LEARN.microsoft.com/azure/%73earch",
    "https://learn.microsoft.com/",
    "http://learn.microsoft.com/azure/search",
]


def test_normalizar_url_igual_que_nucleo_si_se_puede_importar():
    sandbox = str(RAIZ / "sandbox")
    if sandbox not in sys.path:
        sys.path.insert(0, sandbox)
    experto = pytest.importorskip("nucleo.experto")
    for u in URLS_MUESTRA:
        assert derivar.normalizar_url(u) == experto.normalizar_url(u), u


# --- Derivación al catálogo del sandbox y a las tablas ---

def test_derivado_valida_contra_esquema_del_sandbox():
    assert ce.validar(derivar.catalogo_componentes(CAT, esquema=ESQ_EFECTIVO), ESQ_EFECTIVO, ESQ_EFECTIVO) == []


def test_derivado_en_disco_sincronizado():
    disco = json.loads(DERIVADO_EFECTIVO.read_text(encoding="utf-8"))
    assert disco == derivar.catalogo_componentes(CAT, esquema=ESQ_EFECTIVO)


def test_derivado_solo_lleva_lista_blanca():
    ids = {c["id"] for c in derivar.catalogo_componentes(CAT)["componentes"]}
    fuera = {c["id"] for c in COMPS if not c["referencia_url"]}
    assert ids and not (ids & fuera)
    assert ids | fuera == {c["id"] for c in COMPS}


def test_catalogo_ids_del_caso_kelvara_existen():
    resp = json.loads((RAIZ / "esquemas" / "ejemplos" / "respuesta_experto.json").read_text(encoding="utf-8"))
    nombres = {c["id"]: c["nombre_oficial"] for c in derivar.catalogo_componentes(CAT)["componentes"]}
    for comp in resp["componentes"]:
        if comp["catalogo_id"]:
            assert comp["catalogo_id"] in nombres, comp["catalogo_id"]
            assert comp["servicio"] == nombres[comp["catalogo_id"]], comp["catalogo_id"]


def test_tablas_de_instrucciones_sincronizadas():
    assert derivar.main(ARGS_EFECTIVO + ["--comprobar"]) == 0


@pytest.mark.parametrize("url,esperado", [
    ("https://learn.microsoft.com/en-us/azure/Search/Overview/?view=x#y", "https://learn.microsoft.com/azure/search/overview"),
    ("https://learn.microsoft.com/es-es/entra/fundamentals/what-is-entra", "https://learn.microsoft.com/entra/fundamentals/what-is-entra"),
    ("http://learn.microsoft.com/azure/search", ""),
    ("https://learn.microsoft.com.evil.example/azure/search", ""),
    ("https://docs.microsoft.com/azure/search", ""),
    ("https://learn.microsoft.com/zh-hans/azure/search//overview", "https://learn.microsoft.com/azure/search/overview"),
    ("https://learn.microsoft.com:443/azure/search", ""),
    ("https://usuario@learn.microsoft.com/azure/search", ""),
    ("HTTPS://LEARN.microsoft.com/azure/%73earch", "https://learn.microsoft.com/azure/search"),
    ("https://learn.microsoft.com/", ""),
])
def test_normalizar_url(url, esperado):
    assert derivar.normalizar_url(url) == esperado


@pytest.mark.parametrize("url,ok", [
    ("https://learn.microsoft.com/azure/search", True),
    ("https://learn.microsoft.com/azure/searchx/algo", False),
    ("https://learn.microsoft.com/entra-otra/algo", False),
    ("https://learn.microsoft.com/fabric/fundamentals/microsoft-fabric-overview", False),
    ("https://learn.microsoft.com/en-us/azure/architecture/ai-ml/", True),
])
def test_lista_blanca_respeta_el_limite_de_segmento(url, ok):
    assert derivar.en_lista_blanca(url) is ok


@pytest.mark.parametrize("texto", [
    "sin bloque",
    f"{derivar.CATALOGO_FIN}\n{derivar.CATALOGO_INICIO}",
    f"{derivar.CATALOGO_INICIO}\n{derivar.CATALOGO_INICIO}\n{derivar.CATALOGO_FIN}",
])
def test_insertar_tabla_falla_en_alto(texto):
    with pytest.raises(ValueError):
        derivar.insertar_tabla(texto, "tabla")


# --- Comprobador de red, sin red (LES-G-091: un fallo nunca da verde) ---

def _falso_get(estado, final, cuerpo):
    return lambda url, reintentos: (estado, final or url, cuerpo)


@pytest.mark.parametrize("estado,final,cuerpo,fallo", [
    (200, None, b"<title>Overview - Azure | Microsoft Learn</title>", None),
    (404, None, b"", "HTTP 404"),
    (200, None, b"<title>404 - Content Not Found | Microsoft Learn</title>", "soft 404"),
    (200, "https://learn.microsoft.com/en-us/azure/otra", b"<title>Otra</title>", "redirige"),
    (200, "https://otro.example/azure/search/overview", b"<title>Overview</title>", "redirige"),
    (200, None, b"<html>sin titulo</html>", "sin <title>"),
])
def test_comprobar_url(monkeypatch, estado, final, cuerpo, fallo):
    monkeypatch.setattr(cc, "_get", _falso_get(estado, final, cuerpo))
    r = cc.comprobar_url("https://learn.microsoft.com/azure/search/overview", [])
    if fallo is None:
        assert r["errores"] == []
    else:
        assert any(fallo in e for e in r["errores"]), r["errores"]


def test_comprobar_url_acepta_idioma_en_el_destino(monkeypatch):
    monkeypatch.setattr(cc, "_get", _falso_get(200, "https://learn.microsoft.com/en-us/azure/search/overview/",
                                               b"<title>Azure AI Search</title>"))
    assert cc.comprobar_url("https://learn.microsoft.com/azure/search/overview", [])["errores"] == []


@pytest.mark.parametrize("cuerpo,estado,ok", [
    (b'{"Items": [{"retailPrice": 1}]}', 200, True),
    (b'{"Items": []}', 200, False),
    (b"", 500, False),
])
def test_comprobar_precio(monkeypatch, cuerpo, estado, ok):
    monkeypatch.setattr(cc, "_get", _falso_get(estado, None, cuerpo))
    r = cc.comprobar_precio("Azure Cognitive Search", "Azure AI Search", [])
    assert (r["errores"] == []) is ok
    assert r["filtro"] == "serviceName eq 'Azure Cognitive Search' and productName eq 'Azure AI Search'"


class _Resp:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def geturl(self): return "https://learn.microsoft.com/azure/x"
    def read(self): return b"<title>X</title>"


def test_dns_un_solo_reintento_anotado(monkeypatch):
    llamadas = []
    def urlopen(req, timeout):
        llamadas.append(1)
        if len(llamadas) == 1:
            raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
        return _Resp()
    monkeypatch.setattr(cc.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)
    notas: list[str] = []
    assert cc._get("https://learn.microsoft.com/azure/x", notas)[0] == 200
    assert len(llamadas) == 2 and len(notas) == 1


def test_dns_falla_en_alto_al_segundo_intento(monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
    monkeypatch.setattr(cc.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.URLError):
        cc._get("https://learn.microsoft.com/azure/x", [])
