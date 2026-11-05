"""Configuración de pytest común a todo el repositorio publicado (tests, agentes, esquemas, observabilidad y frontal)."""
import os as _os
import pathlib

import pytest

# Las pruebas leen la plantilla de entorno con valores ficticios, nunca el entorno real del fichero local.
# Y la tarifa SINTÉTICA: la real no se publica (se puede fijar otra con PREVENTA_RATE_CARD).
_os.environ.setdefault("PREVENTA_RATE_CARD",
                       str(pathlib.Path(__file__).resolve().parent / "tests" / "insumos" / "rate-card.sintetica.json"))
_os.environ["PREVENTA_ENTORNO"] = str(pathlib.Path(__file__).resolve().parent / "config" / "entorno.ejemplo.json")




# ── Publicación: evidencias y activos privados ──────────────────────────────────────────────────────────────────────
# El repositorio público no lleva las evidencias de las pruebas reales (`pruebas/`, `_baseline/`), las notas de cambio
# por tanda (`docs/I1/CAMBIOS-*`) ni los activos privados (tarifa real y plantillas canónicas). Una prueba que los
# necesita se OMITE nombrando el fichero que falta, nunca pasa en silencio ni se esconde: sale en el resumen con -rs.
import pathlib as _pl  # noqa: E402

_RAIZ = _pl.Path(__file__).resolve().parent
_PRIVADOS = ("pruebas/", "_baseline/", "docs/I1/CAMBIOS")
_LOCALES = ("manifiesto.json", "agentes/despliegue.json")
_MODULOS_PRIVADOS = {"pruebas_b3": "pruebas_b3.py (guion de pruebas reales contra Foundry, no publicado)",
                     "tarifa": "tarifa/ (lectura y publicación de la tarifa real, no publicada)",
                     "paquete_capas": "pruebas/I14/P2 (guion de una tanda anterior, no publicado)"}


def _motivo(e: BaseException) -> str | None:
    if isinstance(e, ModuleNotFoundError) and e.name in _MODULOS_PRIVADOS:
        return f"NO PUBLICADO: {_MODULOS_PRIVADOS[e.name]}"
    if not isinstance(e, FileNotFoundError) or not e.filename:
        return None
    ruta = _pl.Path(str(e.filename))
    texto = ruta.as_posix()
    publicado = texto.startswith(str(_RAIZ / "tests")) or "/tests/insumos/" in texto   # la tarifa sintética sí se publica
    if not publicado and ("rate-card" in texto or "/_templates/" in texto):
        return f"ACTIVO PRIVADO: necesita {ruta.name} (tarifa real o plantilla canónica, no se publican)"
    try:
        rel = ruta.resolve().relative_to(_RAIZ).as_posix()
    except ValueError:
        return None
    if rel.startswith(_PRIVADOS):
        return f"EVIDENCIA NO PUBLICADA (requiere evidencias privadas no publicadas): necesita {rel}"
    if rel in _LOCALES or rel.startswith("salidas/"):
        return f"FICHERO LOCAL NO PUBLICADO: necesita {rel} (registro del despliegue real o salida de una ejecución)"
    return None


class _ModuloConEvidencias(pytest.Module):
    def _getobj(self):
        try:
            return super()._getobj()
        except (FileNotFoundError, ModuleNotFoundError) as e:
            m = _motivo(e)
            if m:
                pytest.skip(m, allow_module_level=True)
            raise
        except pytest.Collector.CollectError as e:   # pytest envuelve los ImportError
            causa = e.__cause__ or e.__context__
            m = _motivo(causa) if causa else None
            if m:
                pytest.skip(m, allow_module_level=True)
            raise


def pytest_pycollect_makemodule(module_path, parent):
    if module_path.name.startswith("test_"):
        return _ModuloConEvidencias.from_parent(parent, path=module_path)
    return None


def _omitir_si_privado(e: BaseException):
    m = _motivo(e)
    if m:
        pytest.skip(m)
    raise e


def _sin_generador(e: BaseException) -> bool:
    """El núcleo falla en alto si no encuentra el generador canónico de estimaciones (no se publica)."""
    return "No está el fichero generar_estimacion.py" in str(e)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    try:
        return (yield)
    except (FileNotFoundError, ModuleNotFoundError) as e:
        _omitir_si_privado(e)
    except Exception as e:
        if _sin_generador(e):
            pytest.skip("ACTIVO PRIVADO: necesita el generador canónico de estimaciones (generar_estimacion.py), "
                        "que no se publica; fíjalo con PREVENTA_GENERADOR o PREVENTA_PROYECTOS")
        raise


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    try:
        return (yield)
    except (FileNotFoundError, ModuleNotFoundError) as e:
        _omitir_si_privado(e)
    except Exception as e:
        if _sin_generador(e):
            pytest.skip("ACTIVO PRIVADO: necesita el generador canónico de estimaciones (generar_estimacion.py), "
                        "que no se publica; fíjalo con PREVENTA_GENERADOR o PREVENTA_PROYECTOS")
        raise
