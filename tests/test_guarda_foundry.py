"""Guarda de prefijo ofa-, protegidos y lista blanca de rutas del cliente REST (sin red)."""
from __future__ import annotations

import pytest

from lib import azure_auth, foundry
from tests.conftest import RespuestaFalsa, SesionFalsa, jwt_falso

DEF = {"kind": "prompt", "model": "gpt-5.6-luna", "instructions": "Prueba sintética."}


def _cliente(cfg, reloj, respuestas=None):
    gestor = azure_auth.GestorTokens(
        tenant=cfg["tenant_id"], reloj=reloj,
        proveedor=lambda aud, ten: (jwt_falso(ten, reloj() + 3600), reloj() + 3600))
    sesion = SesionFalsa(respuestas)
    cli = foundry.ClienteFoundry(cfg=cfg, gestor=gestor, sesion=sesion, dormir=lambda s: None)
    return cli, sesion, gestor


PROTEGIDOS = ["Agente-De-Otro-Proyecto", "agente-de-otro-proyecto", "AGENTE-DE-OTRO-PROYECTO",
              "otro-proyecto-coordinador", "otro-proyecto-prueba-hosted", "Otro-proyecto-experto-azure"]
SIN_PREFIJO = ["coordinador", "ofa", "ofacoordinador", "of-coordinador", "otro-ofa-agente"]
MAL_FORMADOS = ["ofa-../agents", "ofa-a/versions", "ofa-a?x=1", "ofa-A", "ofa-", "ofa-a-",
                "ofa-a\n", "ofa-a\r\n", "ofa-a ", "ofa-a%2F..",
                "ofa-" + "a" * 70, "", None, 42]


@pytest.mark.parametrize("nombre", PROTEGIDOS + SIN_PREFIJO + MAL_FORMADOS)
def test_escribir_rechaza_sin_llamar_a_la_red(cfg, reloj, nombre):
    cli, sesion, gestor = _cliente(cfg, reloj)
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.crear_version_agente(nombre, DEF)
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.crear_agente(nombre, DEF)
    assert sesion.llamadas == []
    assert gestor.peticiones == 0  # ni siquiera se pidió un token


@pytest.mark.parametrize("nombre", PROTEGIDOS + SIN_PREFIJO + MAL_FORMADOS)
def test_borrar_rechaza_aunque_se_permita_el_sistema(cfg, reloj, nombre):
    cli, sesion, _ = _cliente(cfg, reloj)
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.borrar_agente(nombre, permitir_sistema=True)
    assert sesion.llamadas == []


def test_todos_los_protegidos_de_la_configuracion_se_rechazan(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj)
    for nombre in cfg["protegidos"]["agentes"]:
        for variante in (nombre, nombre.lower(), nombre.upper()):
            with pytest.raises(foundry.OperacionNoPermitida, match="protegido"):
                cli.crear_version_agente(variante, DEF)
            with pytest.raises(foundry.OperacionNoPermitida, match="protegido"):
                cli.borrar_agente(variante, permitir_sistema=True)
    assert sesion.llamadas == []


def test_protegido_con_prefijo_ofa_se_rechaza(cfg, reloj):
    cfg["protegidos"]["agentes"].append("ofa-reservado")
    cli, sesion, _ = _cliente(cfg, reloj)
    with pytest.raises(foundry.OperacionNoPermitida, match="protegido"):
        cli.crear_version_agente("ofa-reservado", DEF)
    assert sesion.llamadas == []


def test_mensaje_de_protegido_es_explicito(cfg, reloj):
    cli, _, _ = _cliente(cfg, reloj)
    with pytest.raises(foundry.OperacionNoPermitida, match="protegido"):
        cli.crear_version_agente("Agente-De-Otro-Proyecto", DEF)
    with pytest.raises(foundry.OperacionNoPermitida, match="prefijo protegido"):
        cli.borrar_agente("otro-proyecto-coordinador", permitir_sistema=True)


def test_borrar_agente_del_sistema_exige_permiso_explicito(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj)
    with pytest.raises(foundry.OperacionNoPermitida, match="ofa-prueba-"):
        cli.borrar_agente("ofa-coordinador")
    assert sesion.llamadas == []
    cli.borrar_agente("ofa-coordinador", permitir_sistema=True)
    assert sesion.llamadas[-1]["metodo"] == "DELETE"


def test_borrar_agente_de_prueba_permitido(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj, [RespuestaFalsa(204, {})])
    cli.borrar_agente("ofa-prueba-humo")
    ll = sesion.llamadas[0]
    assert ll["metodo"] == "DELETE"
    assert ll["url"] == cfg["endpoints"]["proyecto"] + "/agents/ofa-prueba-humo"
    assert ll["params"] == {"api-version": "v1"}


def test_crear_version_permitida_envia_definicion_y_token(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj, [RespuestaFalsa(200, {"version": "1"})])
    r = cli.crear_version_agente("ofa-facilitador", DEF, descripcion="sintético")
    assert r == {"version": "1"}
    ll = sesion.llamadas[0]
    assert ll["metodo"] == "POST" and ll["url"].endswith("/agents/ofa-facilitador/versions")
    assert ll["json"] == {"definition": DEF, "description": "sintético"}
    assert ll["headers"]["Authorization"].startswith("Bearer ey")


def test_crear_agente_lleva_el_nombre_en_el_cuerpo(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj, [RespuestaFalsa(201, {"name": "ofa-arquitecto"})])
    cli.crear_agente("ofa-arquitecto", DEF)
    assert sesion.llamadas[0]["json"]["name"] == "ofa-arquitecto"
    assert sesion.llamadas[0]["url"].endswith("/agents")


def test_definicion_sin_kind_valido_se_rechaza(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj)
    with pytest.raises(ValueError):
        cli.crear_version_agente("ofa-facilitador", {"kind": "workflow"})
    assert sesion.llamadas == []


def test_lectura_de_agentes_ajenos_permitida(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj, [RespuestaFalsa(200, {"name": "otro-proyecto-coordinador"})])
    assert cli.obtener_agente("otro-proyecto-coordinador")["name"] == "otro-proyecto-coordinador"
    assert sesion.llamadas[0]["metodo"] == "GET"


def test_lectura_rechaza_nombre_que_cambia_la_ruta(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj)
    for malo in ("ofa-a/versions", "../connections", "ofa-a?api-version=x"):
        with pytest.raises(foundry.OperacionNoPermitida):
            cli.obtener_agente(malo)
    assert sesion.llamadas == []


@pytest.mark.parametrize("metodo,ruta", [
    ("PATCH", "agents/ofa-coordinador"),
    ("PUT", "agents/ofa-coordinador"),
    ("POST", "connections"),
    ("DELETE", "agents/ofa-coordinador/versions/1"),
    ("POST", "agents/ofa-coordinador"),
    ("GET", "connections"),
    ("POST", "openai/v1/responses"),
    ("DELETE", "agents"),
])
def test_lista_blanca_de_rutas_falla_cerrado(cfg, reloj, metodo, ruta):
    cli, sesion, gestor = _cliente(cfg, reloj)
    with pytest.raises(foundry.OperacionNoPermitida, match="lista blanca"):
        cli._peticion(metodo, ruta)
    assert sesion.llamadas == [] and gestor.peticiones == 0


def test_escritura_directa_a_protegido_por_el_punto_unico(cfg, reloj):
    """Aunque alguien salte el método público, _peticion repite la guarda de nombre."""
    cli, sesion, _ = _cliente(cfg, reloj)
    with pytest.raises(foundry.OperacionNoPermitida):
        cli._peticion("POST", "agents", json_body={"name": "Agente-De-Otro-Proyecto", "definition": DEF})
    with pytest.raises(foundry.OperacionNoPermitida):
        cli._peticion("DELETE", "agents/otro-proyecto-coordinador")
    with pytest.raises(foundry.OperacionNoPermitida):
        cli._peticion("POST", "agents/otro-proyecto-experto-azure/versions", json_body={"definition": DEF})
    assert sesion.llamadas == []


def test_configuracion_con_prefijo_relajado_no_permite_escribir(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj)
    cli.cfg["prefijo_agentes"] = ""
    with pytest.raises(foundry.OperacionNoPermitida, match="prefijo"):
        cli.crear_version_agente("ofa-facilitador", DEF)
    assert sesion.llamadas == []


@pytest.mark.parametrize("campo,valor", [
    ("proyecto", "https://atacante.example.com/api/projects/mi-proyecto-foundry"),
    ("proyecto", "https://mi-recurso-foundry.services.ai.azure.com:8443/api/projects/mi-proyecto-foundry"),
    ("proyecto", "https://u:p@mi-recurso-foundry.services.ai.azure.com/api/projects/mi-proyecto-foundry"),
    ("proyecto", "http://mi-recurso-foundry.services.ai.azure.com/api/projects/mi-proyecto-foundry"),
    ("recurso", "https://atacante.example.com"),
])
def test_token_solo_viaja_al_host_del_recurso(cfg, reloj, campo, valor):
    cli, sesion, gestor = _cliente(cfg, reloj)
    cli.cfg["endpoints"][campo] = valor  # alterada después de construir el cliente
    with pytest.raises(foundry.OperacionNoPermitida, match="no autorizado"):
        cli.listar_agentes()
    assert sesion.llamadas == [] and gestor.peticiones == 0


def test_cliente_valida_la_configuracion_al_construirse(cfg, reloj):
    from lib.config import ErrorConfig
    cfg["endpoints"]["proyecto"] = "https://atacante.example.com/api/projects/mi-proyecto-foundry"
    with pytest.raises(ErrorConfig):
        _cliente(cfg, reloj)


def test_gestor_de_otro_tenant_se_rechaza(cfg, reloj):
    otro = azure_auth.GestorTokens(tenant="00000000-1111-2222-3333-444444444444", reloj=reloj,
                                   proveedor=lambda a, t: ("", 0.0))
    with pytest.raises(foundry.OperacionNoPermitida, match="tenant"):
        foundry.ClienteFoundry(cfg=cfg, gestor=otro, sesion=SesionFalsa())


def test_listar_sigue_la_paginacion(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj, [
        RespuestaFalsa(200, {"data": [{"name": "ofa-a"}], "has_more": True, "last_id": "ofa-a"}),
        RespuestaFalsa(200, {"data": [{"name": "ofa-b"}], "has_more": False}),
    ])
    assert [a["name"] for a in cli.listar_agentes()] == ["ofa-a", "ofa-b"]
    assert sesion.llamadas[1]["params"] == {"api-version": "v1", "after": "ofa-a"}


def test_paginacion_sin_cursor_falla_en_alto(cfg, reloj):
    cli, _, _ = _cliente(cfg, reloj, [RespuestaFalsa(200, {"data": [], "has_more": True})])
    with pytest.raises(foundry.ErrorFoundry, match="truncada"):
        cli.listar_agentes()


def test_reintento_429_anotado_y_post_5xx_no_se_repite(cfg, reloj, capsys):
    cli, sesion, _ = _cliente(cfg, reloj, [RespuestaFalsa(429, {"error": "x"}, {"Retry-After": "1"}),
                                           RespuestaFalsa(200, {"name": "ofa-a"})])
    cli.obtener_agente("ofa-a")
    assert len(cli.registro) == 1 and cli.registro[0].estado == 429
    assert "reintento 1/3" in capsys.readouterr().err

    cli2, sesion2, _ = _cliente(cfg, reloj, [RespuestaFalsa(503, {"error": "caído"})])
    with pytest.raises(foundry.ErrorFoundry):
        cli2.crear_version_agente("ofa-a", DEF)
    assert len(sesion2.llamadas) == 1  # POST no idempotente: no se duplica la versión


def test_error_no_filtra_secretos_del_cuerpo(cfg, reloj):
    tok = jwt_falso()
    cli, _, _ = _cliente(cfg, reloj, [RespuestaFalsa(400, {"eco": f"Authorization: Bearer {tok}"})])
    with pytest.raises(foundry.ErrorFoundry) as e:
        cli.obtener_agente("ofa-a")
    assert tok not in str(e.value) and "[REDACTADO]" in str(e.value)


def test_401_renueva_token_una_vez_y_lo_anota(cfg, reloj):
    cli, sesion, gestor = _cliente(cfg, reloj, [RespuestaFalsa(401, {"error": "token"}),
                                                RespuestaFalsa(200, {"name": "ofa-a"})])
    cli.obtener_agente("ofa-a")
    assert gestor.peticiones == 2 and cli.registro[0].estado == 401


def test_ruta_con_salto_de_linea_final_no_pasa_la_lista_blanca(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj)
    for ruta in ("agents/ofa-a\n", "agents\n", "agents/ofa-a/versions\n"):
        with pytest.raises(foundry.OperacionNoPermitida):
            cli._peticion("GET", ruta)
    assert sesion.llamadas == []


def test_no_sigue_redirecciones(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj, [RespuestaFalsa(302, {}, {"Location": "https://otro.example.com"})])
    with pytest.raises(foundry.ErrorFoundry):
        cli.obtener_agente("ofa-a")
    assert sesion.llamadas[0]["allow_redirects"] is False


def test_mutar_la_configuracion_del_llamante_no_relaja_la_guarda(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj)
    cfg["protegidos"]["agentes"].clear()
    cfg["protegidos"]["prefijos_agentes"].clear()
    cfg["prefijo_agentes"] = ""
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.crear_version_agente("Agente-De-Otro-Proyecto", DEF)
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.borrar_agente("otro-proyecto-coordinador", permitir_sistema=True)
    assert sesion.llamadas == []


def test_borrar_forzar_anade_force_y_respeta_la_guarda(cfg, reloj):
    cli, sesion, _ = _cliente(cfg, reloj, [RespuestaFalsa(204, {})])
    cli.borrar_agente("ofa-prueba-hosted", forzar=True)
    assert sesion.llamadas[0]["params"]["force"] == "true"
    assert sesion.llamadas[0]["params"]["api-version"] == "v1"
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.borrar_agente("ofa-coordinador", forzar=True)
    with pytest.raises(foundry.OperacionNoPermitida):
        cli.borrar_agente("Agente-De-Otro-Proyecto", forzar=True)
    assert len(sesion.llamadas) == 1
