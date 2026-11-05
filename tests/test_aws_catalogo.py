"""Pilar AWS: forma del catálogo, referencias comprobadas y bloque de las instrucciones. Sin red."""
import copy
import json

import pytest

from catalogo.aws import comprobar_catalogo as cc


@pytest.fixture(scope="module")
def cat():
    return cc.leer_json(cc.CATALOGO)


def test_catalogo_real_valido(cat):
    assert cc.problemas_catalogo(cat) == []
    assert 12 <= len(cat["componentes"]) <= 20


def test_referencias_reales_cubren_el_catalogo(cat):
    assert cc.problemas_referencias(cat, cc.leer_json(cc.REFERENCIAS)) == []


def test_instrucciones_llevan_el_bloque_generado(cat):
    texto = cc.INSTRUCCIONES.read_text(encoding="utf-8")
    assert cc.problemas_instrucciones(cat, texto) == []
    assert cc.problemas_instrucciones(cat, texto.replace("nova-2-lite-entrada", "nova-x", 1))


def test_definicion_borrador_usa_el_mcp_de_aws():
    d = json.loads((cc.RAIZ / "agentes" / "aws" / "definicion_borrador.json").read_text(encoding="utf-8"))
    (tool,) = d["tools"]
    assert tool["server_url"] == "https://knowledge-mcp.global.api.aws"
    assert all(t.startswith("aws___") for t in tool["allowed_tools"]["tool_names"])


def test_rechaza_nan_e_infinity(tmp_path):
    for malo in ("NaN", "Infinity", "-Infinity"):
        f = tmp_path / "c.json"
        f.write_text('{"valor": %s}' % malo, encoding="utf-8")
        with pytest.raises(ValueError):
            cc.leer_json(f)


def _con(cat, cambio):
    c = copy.deepcopy(cat)
    cambio(c)
    return cc.problemas_catalogo(c)


def _fila(c, cid):
    return next(x for x in c["componentes"] if x["id"] == cid)


@pytest.mark.parametrize("region", ["eu-west-2", "eu-central-2", "eu-central-1-ham-1", "us-east-1"])
def test_regiones_fuera_de_la_ue_rechazadas(cat, region):
    assert _con(cat, lambda c: _fila(c, "aws-lambda").update(region_ue=region))
    assert _con(cat, lambda c: _fila(c, "aws-lambda")["disponibilidad"]["bajo demanda"]["regiones"].append(region))
    assert _con(cat, lambda c: c.update(regiones_ue=c["regiones_ue"] + [region]))


@pytest.mark.parametrize("cambio", [
    lambda c: _fila(c, "aws-bedrock")["plantillas_precio"][0].update(divisor=1),
    lambda c: _fila(c, "aws-bedrock")["plantillas_precio"][0].update(factor_estandar="no.existe"),
    lambda c: _fila(c, "aws-bedrock")["plantillas_precio"][0].pop("ciclo_vida"),
    lambda c: _fila(c, "aws-kms")["plantillas_precio"][0].update(periodo="semana"),
    lambda c: _fila(c, "aws-api-gateway")["nivel_por_defecto"].update(nivel="Premium"),
    lambda c: _fila(c, "aws-lambda").update(id="az-lambda"),
    lambda c: _fila(c, "aws-lambda").update(referencia_url="https://example.com/x"),
    lambda c: c["factores_estandar"][0].update(valor=float("nan")),
    lambda c: c["factores_estandar"][0].update(valor=float("inf")),
    lambda c: c["modelo_por_defecto"].update(plantillas=["no-existe"]),
    lambda c: _fila(c, "aws-s3")["plantillas_precio"][0].update(
        filtro=_fila(c, "aws-s3")["plantillas_precio"][0]["filtro"].replace("AmazonS3", "AmazonS4")),
])
def test_roturas_detectadas(cat, cambio):
    assert _con(cat, cambio)


def test_titulo_distinto_del_comprobado(cat):
    ref = cc.leer_json(cc.REFERENCIAS)
    c = copy.deepcopy(cat)
    _fila(c, "aws-lambda")["referencia_titulo"] = "Otro título"
    assert any("título distinto" in x for x in cc.problemas_referencias(c, ref))


def test_bloque_lista_las_regiones_y_ninguna_fuera(cat):
    b = cc.bloque(cat)
    assert "`eu-south-2`" in b and "e-0" not in b
    filas = [x for x in b.splitlines() if x.startswith("| aws-")]
    assert len(filas) == len(cat["componentes"])
    assert not any("eu-west-2" in x or "eu-central-2" in x for x in filas)


@pytest.mark.parametrize("contenido", ['[]', '{"componentes": [null]}', '{"componentes": 3}'])
def test_forma_mal_tipada_da_falla_y_no_traza(tmp_path, monkeypatch, capsys, contenido):
    f = tmp_path / "c.json"
    f.write_text(contenido, encoding="utf-8")
    monkeypatch.setattr(cc, "CATALOGO", f)
    assert cc.main([]) == 1
    assert "FALLA" in capsys.readouterr().out
