"""Renovación de tokens simulada: tenant fijo, caché, margen de 5 minutos y fallos en alto."""
from __future__ import annotations

import subprocess
import types

import pytest

from lib import azure_auth
from tests.conftest import OTRO_TENANT, TENANT, jwt_falso


class ProveedorFalso:
    """Emite tokens que duran `vida_s` segundos y anota cada petición."""

    def __init__(self, reloj, vida_s: float = 3600, tid: str = TENANT):
        self.reloj, self.vida_s, self.tid = reloj, vida_s, tid
        self.pedidos: list[tuple[str, str]] = []

    def __call__(self, audiencia: str, tenant: str):
        self.pedidos.append((audiencia, tenant))
        exp = self.reloj() + self.vida_s
        return jwt_falso(self.tid, exp, {"n": len(self.pedidos), "aud": audiencia}), exp


def test_tenant_fijo_se_pasa_siempre_al_proveedor(reloj):
    p = ProveedorFalso(reloj)
    g = azure_auth.GestorTokens(proveedor=p, reloj=reloj)
    g.token(azure_auth.AUD_DATOS)
    g.token(azure_auth.AUD_ARM)
    assert p.pedidos == [(azure_auth.AUD_DATOS, TENANT), (azure_auth.AUD_ARM, TENANT)]
    assert g.tenant == TENANT  # sin tenant explícito, el de la configuración


def test_reutiliza_la_cache_mientras_quede_mas_del_margen(reloj):
    p = ProveedorFalso(reloj, vida_s=3600)
    g = azure_auth.GestorTokens(proveedor=p, reloj=reloj)
    t1 = g.token()
    reloj.avanzar(3600 - 301)  # quedan 301 s: por encima del margen
    assert g.token() == t1
    assert g.peticiones == 1


def test_renueva_al_entrar_en_el_margen_de_5_minutos(reloj):
    p = ProveedorFalso(reloj, vida_s=3600)
    g = azure_auth.GestorTokens(proveedor=p, reloj=reloj)
    t1 = g.token()
    reloj.avanzar(3600 - 300)  # quedan exactamente 300 s: se renueva
    t2 = g.token()
    assert t2 != t1 and g.peticiones == 2
    assert g.caduca_en() == pytest.approx(3600)


def test_cache_separada_por_audiencia(reloj):
    p = ProveedorFalso(reloj)
    g = azure_auth.GestorTokens(proveedor=p, reloj=reloj)
    assert g.token(azure_auth.AUD_DATOS) != g.token(azure_auth.AUD_ARM)
    g.token(azure_auth.AUD_DATOS)
    assert g.peticiones == 2


def test_forzar_y_olvidar_piden_token_nuevo(reloj):
    p = ProveedorFalso(reloj)
    g = azure_auth.GestorTokens(proveedor=p, reloj=reloj)
    g.token()
    g.token(forzar=True)
    g.olvidar()
    g.token()
    assert g.peticiones == 3


def test_usa_la_caducidad_mas_prudente(reloj):
    """Si expires_on y exp del JWT discrepan, manda la más temprana."""
    def prov(aud, ten):
        return jwt_falso(ten, reloj() + 600), reloj() + 3600
    g = azure_auth.GestorTokens(proveedor=prov, reloj=reloj)
    g.token()
    assert g.caduca_en() == pytest.approx(600)
    reloj.avanzar(301)  # quedan 299 s según exp: se renueva aunque expires_on diga 1 h
    g.token()
    assert g.peticiones == 2


def test_rechaza_token_de_otro_tenant(reloj):
    g = azure_auth.GestorTokens(proveedor=ProveedorFalso(reloj, tid=OTRO_TENANT), reloj=reloj)
    with pytest.raises(azure_auth.ErrorAutenticacion, match="az login --tenant " + TENANT):
        g.token()
    assert g.caduca_en() is None  # no se guarda en caché


@pytest.mark.parametrize("token,expira", [
    ("", 0.0), ("no-es-un-jwt", 9e9), ("a.b.c", 9e9),
])
def test_rechaza_tokens_invalidos(reloj, token, expira):
    g = azure_auth.GestorTokens(proveedor=lambda a, t: (token, expira), reloj=reloj)
    with pytest.raises(azure_auth.ErrorAutenticacion):
        g.token()


def test_rechaza_token_caducado_o_sin_caducidad(reloj):
    caducado = azure_auth.GestorTokens(
        proveedor=lambda a, t: (jwt_falso(t, reloj() - 10), reloj() - 10), reloj=reloj)
    with pytest.raises(azure_auth.ErrorAutenticacion, match="caducado"):
        caducado.token()
    sin_exp = azure_auth.GestorTokens(proveedor=lambda a, t: (jwt_falso(t), 0.0), reloj=reloj)
    with pytest.raises(azure_auth.ErrorAutenticacion, match="caduca"):
        sin_exp.token()


@pytest.mark.parametrize("tenant", ["", "  ", "no-guid", "ABCDEF00-0000-0000-0000-000000000000", 7])
def test_tenant_invalido_se_rechaza(tenant):
    with pytest.raises(ValueError):
        azure_auth.GestorTokens(tenant=tenant, proveedor=lambda a, t: ("", 0))


def test_sin_configuracion_local_no_hay_tenant_por_defecto(monkeypatch, tmp_path):
    """Sin tenant explícito y sin fichero de configuración, falla en alto (no hay tenant en el código)."""
    from lib.config import ErrorConfig
    monkeypatch.setenv("OFA_ENTORNO", str(tmp_path / "no-existe.json"))
    with pytest.raises(ErrorConfig, match="No existe"):
        azure_auth.GestorTokens(proveedor=lambda a, t: ("", 0))


def test_repr_no_muestra_el_token(reloj):
    g = azure_auth.GestorTokens(proveedor=ProveedorFalso(reloj), reloj=reloj)
    t = g.token()
    assert t not in repr(g)


def test_proveedor_az_cli_pasa_tenant_y_detecta_mfa(monkeypatch):
    capturado = {}

    def falso_run(cmd, **kw):
        capturado["cmd"], capturado["timeout"] = cmd, kw.get("timeout")
        return types.SimpleNamespace(returncode=1, stdout="",
                                     stderr="AADSTS50076: Due to a configuration change... Bearer abc.def")
    monkeypatch.setattr(azure_auth, "_ejecutable_az", lambda: "az")
    monkeypatch.setattr(subprocess, "run", falso_run)
    with pytest.raises(azure_auth.ErrorAutenticacion) as e:
        azure_auth.proveedor_az_cli(azure_auth.AUD_DATOS, TENANT)
    cmd = capturado["cmd"]
    assert cmd[cmd.index("--tenant") + 1] == TENANT
    assert cmd[cmd.index("--resource") + 1] == azure_auth.AUD_DATOS
    assert capturado["timeout"] <= 90
    assert "abc.def" not in str(e.value)  # el error de az también se redacta
    assert "az login --tenant " + TENANT + " --scope https://ai.azure.com/.default" in str(e.value)


def test_proveedor_az_cli_lee_token_y_caducidad(monkeypatch):
    tok = jwt_falso(TENANT, 2_000_000)
    monkeypatch.setattr(azure_auth, "_ejecutable_az", lambda: "az")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(
        returncode=0, stderr="", stdout='{"accessToken": "%s", "expires_on": 2000000}' % tok))
    assert azure_auth.proveedor_az_cli(azure_auth.AUD_DATOS, TENANT) == (tok, 2_000_000.0)


def test_proveedor_az_cli_tiempo_agotado(monkeypatch):
    def lento(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(azure_auth, "_ejecutable_az", lambda: "az")
    monkeypatch.setattr(subprocess, "run", lento)
    with pytest.raises(azure_auth.ErrorAz, match="no respondió"):
        azure_auth.proveedor_az_cli(azure_auth.AUD_DATOS, TENANT)


def test_proveedor_credencial_de_azure_identity(reloj):
    llamadas = []

    class CredFalsa:
        def get_token(self, *alcances, **kw):
            llamadas.append((alcances, kw))
            return types.SimpleNamespace(token=jwt_falso(TENANT, reloj() + 3600), expires_on=int(reloj() + 3600))

    g = azure_auth.GestorTokens(proveedor=azure_auth.proveedor_credencial(CredFalsa()), reloj=reloj)
    g.token()
    assert llamadas == [(("https://ai.azure.com/.default",), {"tenant_id": TENANT})]
    g2 = azure_auth.GestorTokens(proveedor=azure_auth.proveedor_credencial(CredFalsa(), pasar_tenant=False),
                                 reloj=reloj)
    g2.token()
    assert llamadas[-1] == (("https://ai.azure.com/.default",), {})


def test_identidad_gestionada_se_construye_sin_red():
    """Solo comprueba que azure-identity está instalado y el adaptador se crea; no pide token."""
    prov = azure_auth.proveedor_identidad_gestionada()
    assert callable(prov)


def test_rechaza_token_de_otra_audiencia(reloj):
    prov = lambda a, t: (jwt_falso(t, reloj() + 3600, {"aud": "https://graph.microsoft.com"}), reloj() + 3600)
    g = azure_auth.GestorTokens(proveedor=prov, reloj=reloj)
    with pytest.raises(azure_auth.ErrorAutenticacion, match="audiencia"):
        g.token(azure_auth.AUD_DATOS)


def test_acepta_alias_de_audiencia_de_arm(reloj):
    prov = lambda a, t: (jwt_falso(t, reloj() + 3600, {"aud": "https://management.core.windows.net/"}),
                         reloj() + 3600)
    g = azure_auth.GestorTokens(proveedor=prov, reloj=reloj)
    assert g.token(azure_auth.AUD_ARM)


def test_olvidar_una_audiencia_conserva_las_demas(reloj):
    g = azure_auth.GestorTokens(proveedor=ProveedorFalso(reloj), reloj=reloj)
    g.token(azure_auth.AUD_DATOS)
    g.token(azure_auth.AUD_ARM)
    g.olvidar(azure_auth.AUD_DATOS)
    assert g.caduca_en(azure_auth.AUD_DATOS) is None and g.caduca_en(azure_auth.AUD_ARM) is not None
