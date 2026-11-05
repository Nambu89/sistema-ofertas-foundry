"""I1.7, papel E: consultas de la instantánea (429, DNS, 400, NextPageLink) con urlopen simulado, y compatibilidad de la
instantánea y del catálogo propuesto con el núcleo de P (si ya expone esas funciones). Sin red."""
from __future__ import annotations

import io
import json
import socket
import sys
import urllib.error

import pytest

from catalogo import derivar
from catalogo import instantanea_precios as ip

VIVA = json.loads(ip.DESTINOS[0].read_text(encoding="utf-8"))


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http(codigo, cabeceras=None):
    return urllib.error.HTTPError("https://prices.azure.com", codigo, "x", cabeceras or {}, None)


def _simular(monkeypatch, secuencia):
    llamadas = []

    def urlopen(req, timeout=None):
        llamadas.append(req.full_url)
        x = secuencia.pop(0)
        if isinstance(x, Exception):
            raise x
        return _Resp(json.dumps(x).encode())
    monkeypatch.setattr(ip.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ip.time, "sleep", lambda s: None)
    return llamadas


def test_429_espera_y_reintenta_anotado(monkeypatch):
    llamadas = _simular(monkeypatch, [_http(429, {"Retry-After": "7"}), _http(429), {"Items": [{"a": 1}]}])
    notas = []
    assert ip.consultar("f", notas, pausa=0) == [{"a": 1}] and len(llamadas) == 3
    assert len(notas) == 2 and "espera 1/6 de 7 s" in notas[0] and "de 30 s" in notas[1]


def test_429_sin_fin_falla_en_alto(monkeypatch):
    _simular(monkeypatch, [_http(429)] * 3)
    with pytest.raises(ip.ErrorInstantanea, match="HTTP 429"):
        ip.consultar("f", [], pausa=0, max_429=2)


def test_400_dns_y_paginacion_fallan_en_alto(monkeypatch):
    _simular(monkeypatch, [_http(400)])
    with pytest.raises(ip.ErrorInstantanea, match="HTTP 400"):
        ip.consultar("f", [], pausa=0)
    dns = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
    notas = []
    _simular(monkeypatch, [dns, {"Items": []}])
    assert ip.consultar("f", notas, pausa=0) == [] and "reintento único" in notas[0]
    _simular(monkeypatch, [dns, dns])
    with pytest.raises(ip.ErrorInstantanea, match="red"):
        ip.consultar("f", [], pausa=0)
    _simular(monkeypatch, [{"Items": [], "NextPageLink": "https://x"}])
    with pytest.raises(ip.ErrorInstantanea, match="NextPageLink"):
        ip.consultar("f", [], pausa=0)
    _simular(monkeypatch, [{"Count": 0}])
    with pytest.raises(ip.ErrorInstantanea, match="sin lista Items"):
        ip.consultar("f", [], pausa=0)


def test_la_consulta_pide_eur_y_el_filtro_exacto(monkeypatch):
    llamadas = _simular(monkeypatch, [{"Items": []}])
    ip.consultar("serviceName eq 'X' and meterName eq 'Y'", [], pausa=0)
    assert "currencyCode=EUR" in llamadas[0] and "serviceName+eq+%27X%27" in llamadas[0]


def test_main_comprobar_con_la_fecha_del_paquete():
    fecha = VIVA["fecha_consulta"][:10]
    assert ip.main(["--comprobar", "--fecha-paquete", fecha]) == 0
    assert ip.main(["--comprobar", "--fecha-paquete", "2099-01-01"]) == 1


def _nucleo():
    sys.path.insert(0, str(derivar.RAIZ / "sandbox"))
    from nucleo import experto
    return experto


def test_compatible_con_el_nucleo_de_p():
    experto = _nucleo()
    if not hasattr(experto, "errores_instantanea_catalogo"):
        pytest.skip("el núcleo todavía no valida la instantánea (I1.7, papel P)")
    # I1.8: el catálogo vivo del sandbox (la vista previa de I1.7 es v5 y ya no casa con la instantánea de v7)
    cat = json.loads(derivar.DERIVADO.read_text(encoding="utf-8"))
    assert experto.errores_instantanea(VIVA) == []
    assert experto.errores_instantanea_catalogo(VIVA, cat) == []
    fila = next(c for c in cat["componentes"] if c["id"] == "az-foundry")
    pl = next(p for p in fila["plantillas_precio"] if p["id"] == "gpt-6-luna-entrada")
    std, problema = experto.factor_estandar({"plantilla": pl, "fila": fila, "clave": "az-foundry/gpt-6-luna-entrada"}, cat)
    assert problema is None and std["valor_json"] == 5656 and std["bases"]
