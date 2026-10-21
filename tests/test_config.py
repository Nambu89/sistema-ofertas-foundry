"""Validación de la configuración del entorno: plantilla versionada y fichero local ignorado."""
from __future__ import annotations

import copy
import json
import subprocess

import pytest

from lib import config


def test_la_plantilla_es_valida_y_solo_trae_valores_ficticios():
    cfg = config.cargar(config.RUTA_EJEMPLO)
    assert cfg["prefijo_agentes"] == "ofa-" and cfg["prefijo_agentes_prueba"] == "ofa-prueba-"
    assert cfg["tenant_id"] == cfg["suscripcion_id"] == "00000000-0000-0000-0000-000000000000"
    assert cfg["grupo_recursos"] == "rg-ejemplo"
    assert len(cfg["protegidos"]["agentes"]) >= 2 and cfg["protegidos"]["prefijos_agentes"]
    assert cfg["despliegues"]["Decision-1"]["modelo"] == "Microsoft-Decision-1"
    assert all(a["nombre"].startswith("ofa-") for a in cfg["agentes"].values())


def test_la_configuracion_local_es_valida_y_no_coincide_con_la_plantilla():
    """El fichero real no se versiona: sin él, la comprobación se omite y lo dice."""
    if not config.RUTA_POR_DEFECTO.exists():
        pytest.skip("NO COMPROBADO: falta config/entorno.local.json (local y no versionado). "
                    "Créalo a partir de config/entorno.ejemplo.json.")
    real = config.cargar(config.RUTA_POR_DEFECTO)
    ejemplo = config.cargar(config.RUTA_EJEMPLO)
    for k in ("tenant_id", "suscripcion_id", "recurso", "proyecto"):
        assert real[k] != ejemplo[k], f"{k} conserva el valor ficticio de la plantilla"
    # Ningún valor real del entorno puede haberse colado en la plantilla versionada.
    texto = config.RUTA_EJEMPLO.read_text(encoding="utf-8").casefold()
    reales = [real["tenant_id"], real["suscripcion_id"], real["grupo_recursos"], real["recurso"],
              real["proyecto"], *real["protegidos"]["agentes"], *real["protegidos"]["prefijos_agentes"],
              *real["protegidos"].get("toolboxes", [])]
    assert not [v for v in reales if v.casefold() in texto]


@pytest.mark.parametrize("ruta,ignorado", [
    ("config/entorno.local.json", True),
    ("config/entorno.local.json.bak", True),
    ("config/entorno.local.json~", True),
    ("config/entorno.ejemplo.json", False),
])
def test_el_entorno_local_no_se_versiona_y_la_plantilla_si(ruta, ignorado):
    r = subprocess.run(["git", "check-ignore", "-q", ruta], cwd=config.RAIZ)
    assert r.returncode == (0 if ignorado else 1), r.returncode


@pytest.mark.parametrize("ruta", [config.RUTA_EJEMPLO, config.RUTA_POR_DEFECTO], ids=["ejemplo", "local"])
def test_el_fichero_no_tiene_retornos_de_carro(ruta):
    """LES-G-099: un CR invisible cambia hashes y comparaciones sin avisar."""
    if not ruta.exists():
        pytest.skip(f"NO COMPROBADO: falta {ruta.name}")
    assert b"\r" not in ruta.read_bytes()


def test_sin_fichero_local_falla_en_alto_y_dice_que_se_copie_la_plantilla(monkeypatch, tmp_path):
    monkeypatch.delenv(config.VARIABLE_RUTA, raising=False)
    monkeypatch.setattr(config, "RUTA_POR_DEFECTO", config.RAIZ / "config" / "no-existe.local.json")
    with pytest.raises(config.ErrorConfig, match="Copia la plantilla config/entorno.ejemplo.json"):
        config.cargar()


def _rellenada(tmp_path, **cambios):
    """Copia de la plantilla con valores «reales» inventados (no son de ningún entorno)."""
    cfg = json.loads(config.RUTA_EJEMPLO.read_text(encoding="utf-8"))
    cfg.update(tenant_id="12345678-90ab-cdef-1234-567890abcdef", suscripcion_id="12345678-90ab-cdef-1234-567890abcdef",
               grupo_recursos="rg-otro", recurso="otro-recurso", proyecto="otro-proyecto")
    cfg["endpoints"].update(recurso="https://otro-recurso.services.ai.azure.com",
                            proyecto="https://otro-recurso.services.ai.azure.com/api/projects/otro-proyecto")
    cfg.update(cambios)
    destino = tmp_path / "entorno.local.json"
    destino.write_text(json.dumps(cfg), encoding="utf-8")
    return destino


def test_la_variable_de_ruta_manda_y_vacia_falla(monkeypatch, tmp_path):
    destino = _rellenada(tmp_path)
    monkeypatch.setenv(config.VARIABLE_RUTA, str(destino))
    assert config.ruta_configurada() == destino and config.cargar()["recurso"] == "otro-recurso"
    monkeypatch.setenv(config.VARIABLE_RUTA, "   ")
    with pytest.raises(config.ErrorConfig, match="OFA_ENTORNO"):
        config.cargar()
    monkeypatch.delenv(config.VARIABLE_RUTA)
    assert config.ruta_configurada() == config.RUTA_POR_DEFECTO


def test_una_copia_sin_rellenar_de_la_plantilla_se_rechaza(tmp_path):
    copia = tmp_path / "entorno.local.json"
    copia.write_bytes(config.RUTA_EJEMPLO.read_bytes())
    with pytest.raises(config.ErrorConfig, match="valores ficticios"):
        config.cargar(copia)
    # Basta con que quede uno: aquí solo el tenant sigue siendo el ficticio.
    with pytest.raises(config.ErrorConfig, match=r"\['tenant_id'\]"):
        config.cargar(_rellenada(tmp_path, tenant_id=config.GUID_FICTICIO))
    assert config.cargar(config.RUTA_EJEMPLO)["tenant_id"] == config.GUID_FICTICIO  # la plantilla misma sí
    # Una copia con el MISMO NOMBRE que la plantilla, en otra carpeta, tampoco se libra.
    (tmp_path / "sub").mkdir()
    homonima = tmp_path / "sub" / config.RUTA_EJEMPLO.name
    homonima.write_bytes(config.RUTA_EJEMPLO.read_bytes())
    with pytest.raises(config.ErrorConfig, match="valores ficticios"):
        config.cargar(homonima)


@pytest.mark.parametrize("romper,mensaje", [
    (lambda c: c.pop("tenant_id"), "Faltan"),
    (lambda c: c.__setitem__("tenant_id", "no-guid"), "GUID"),
    (lambda c: c["endpoints"].__setitem__("proyecto", "https://otro.example.com/api/projects/x"), "endpoints"),
    (lambda c: c["endpoints"].__setitem__("arm", "https://arm.example.com"), "arm"),
    (lambda c: c["endpoints"].__setitem__("recurso", "https://mi-recurso-foundry.services.ai.azure.com:444"), "puerto"),
    (lambda c: c.__setitem__("prefijo_agentes", ""), "prefijo_agentes"),
    (lambda c: c.__setitem__("prefijo_agentes_prueba", "ofa-"), "prefijo_agentes_prueba"),
    (lambda c: c["agentes"]["coordinador"].__setitem__("nombre", "coordinador"), "prefijo"),
    (lambda c: c["agentes"]["coordinador"].__setitem__("nombre", "ofa-prueba-x"), "prueba"),
    (lambda c: c["protegidos"]["agentes"].append("ofa-coordinador"), "protegido"),
    (lambda c: c["protegidos"]["prefijos_agentes"].append("of"), "solapa"),
    (lambda c: c["protegidos"].__setitem__("agentes", []), "protegidos"),
    (lambda c: c["protegidos"].__setitem__("agentes", "ofa-reservado"), "lista de cadenas"),
    (lambda c: c["protegidos"].__setitem__("toolboxes", "toolbox-de-otro-proyecto"), "lista de cadenas"),
    (lambda c: c["protegidos"]["agentes"].append(7), "lista de cadenas"),
    (lambda c: c["despliegues"]["gpt-5.6-luna"].pop("sku"), "SKU"),
    (lambda c: c.__setitem__("api_key", "x"), "secretos"),
    (lambda c: c.__setitem__("nota", "AccountKey=" + "A" * 20), "secretos"),
])
def test_rechaza_configuraciones_rotas(romper, mensaje):
    cfg = copy.deepcopy(config.cargar(config.RUTA_EJEMPLO))
    romper(cfg)
    with pytest.raises(config.ErrorConfig, match=mensaje):
        config.validar(cfg)


def test_cargar_falla_en_alto(tmp_path):
    with pytest.raises(config.ErrorConfig, match="No existe"):
        config.cargar(tmp_path / "no.json")
    roto = tmp_path / "roto.json"
    roto.write_text("{", encoding="utf-8")
    with pytest.raises(config.ErrorConfig, match="JSON"):
        config.cargar(roto)
    lista = tmp_path / "lista.json"
    lista.write_text(json.dumps([1]), encoding="utf-8")
    with pytest.raises(config.ErrorConfig, match="objeto"):
        config.cargar(lista)
