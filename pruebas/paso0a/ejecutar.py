"""Orquestador del arnés del paso 0a.

Uso (desde la raíz del repositorio):
  .venv/Scripts/python.exe pruebas/paso0a/ejecutar.py [--solo P1|P2|P3|P4|P5] [--repetir] [--presupuesto 80]
  .venv/Scripts/python.exe pruebas/paso0a/ejecutar.py --simular [--escenario feliz|adverso] [--solo Pn]

- Real: usa el token de Fernando (az, tenant fijo). Ninguna invocación pasa de ~85 s: cada prueba avanza lo
  que cabe en el presupuesto y, si aún no tiene veredicto, guarda su progreso y sale con 4 («vuelve a
  ejecutar»). P5 necesita 87 s (opencode con tiempo máximo de 75 s; antes 120 s, rebajado para cumplir
  la regla de 90 s) y solo corre con --solo P5. Una prueba con resultado final no se repite sin --repetir.
- Simulado: sin Azure ni red, con reloj falso; escribe en resultados/simulado/<escenario>/.

Código de salida: 1 si alguna FALLA; si no, 4 si alguna sigue en curso; si no, 3 si alguna queda
PENDIENTE_FERNANDO; 0 si todo PASA o NO_APLICA; 2 error de uso o del arnés; 5 autenticación (MFA).
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import traceback

RAIZ = pathlib.Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from lib import azure_auth  # noqa: E402
from lib.config import ErrorConfig  # noqa: E402
from lib.foundry import OperacionNoPermitida  # noqa: E402
from pruebas.paso0a import comun  # noqa: E402
from pruebas.paso0a import p1_ciclo_vida, p2_decision, p3_herramientas, p4_hosted, p5_opencode  # noqa: E402

PRUEBAS = {"P1": p1_ciclo_vida, "P2": p2_decision, "P3": p3_herramientas, "P4": p4_hosted, "P5": p5_opencode}
PRESUPUESTO_MAX_S = 85.0
PRESUPUESTO_P5_S = p5_opencode.TIMEOUT_OPENCODE_S + 12.0


def correr(prueba, ctx: comun.Contexto) -> dict | comun.EnCurso:
    """Llama a la prueba hasta que tenga veredicto o se agote el presupuesto, esperando lo que pida."""
    while True:
        res = prueba.ejecutar(ctx)
        if isinstance(res, dict):
            return res
        if res.espera_s <= 0 or ctx.restante() < res.espera_s + 5:
            return res
        ctx.escribir(f"  … {res.mensaje}; espero {res.espera_s:.0f} s (quedan {ctx.restante():.0f} s de presupuesto)")
        ctx.dormir(res.espera_s)


def codigo_global(codigos: list[int]) -> int:
    for c in (comun.RC_AUTENTICACION, comun.RC_USO, comun.RC_ESTADO["FALLA"], comun.RC_EN_CURSO,
              comun.RC_ESTADO["PENDIENTE_FERNANDO"]):
        if c in codigos:
            return c
    return 0


def _preparar_simulacion(escenario: str):
    from pruebas.paso0a import simulacion
    destino = comun.DIR_RESULTADOS / "simulado" / escenario
    if destino.exists():   # directorio propio de la simulación: se regenera entero
        shutil.rmtree(destino)
    destino.mkdir(parents=True)
    temporal = comun.directorio_temporal("ofa-sim-")
    zip_sim = simulacion.construir_zip_simulado(temporal / "ofa-prueba-hosted.zip")
    ctx, _ = simulacion.contexto(escenario, destino, temporal / "progreso", temporal / "p5", zip_sim)
    return ctx, temporal


def main(argv: list[str] | None = None) -> int:
    """Punto de entrada: ninguna excepción sale con rc=1, que es el código de FALLA."""
    try:
        return _main(argv)
    except azure_auth.ErrorAutenticacion as e:
        print(f"PARADA rc=5 (autenticación): {comun.redactar(str(e))}")
        return comun.RC_AUTENTICACION
    except Exception as e:   # noqa: BLE001 — un fallo imprevisto del arnés no es un veredicto
        print(f"FALLO DEL ARNÉS rc=2 (inesperado): {type(e).__name__}: {comun.redactar(str(e))}")
        print(comun.redactar(traceback.format_exc()), file=sys.stderr)
        return comun.RC_USO


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Arnés de pruebas del paso 0a")
    ap.add_argument("--solo", choices=sorted(PRUEBAS), help="ejecuta solo esa prueba")
    ap.add_argument("--simular", action="store_true", help="sin Azure: transporte, reloj y procesos falsos")
    ap.add_argument("--escenario", choices=("feliz", "adverso"), default="feliz")
    ap.add_argument("--repetir", action="store_true", help="vuelve a empezar aunque haya resultado o progreso")
    ap.add_argument("--presupuesto", type=float, default=80.0, help="segundos por invocación (máximo 85)")
    ap.add_argument("--zip", help="ZIP del hosted (por defecto pruebas/paso0a/_salidas/ofa-prueba-hosted.zip)")
    ap.add_argument("--conservar", action="store_true", help="P5: sin efecto (el directorio de trabajo de P5 es fijo y se conserva siempre)")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return comun.RC_USO if e.code else 0
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if not 10 <= a.presupuesto <= PRESUPUESTO_MAX_S:
        print(f"FALLO rc=2: --presupuesto debe estar entre 10 y {PRESUPUESTO_MAX_S:.0f} s")
        return comun.RC_USO
    seleccion = [a.solo] if a.solo else list(PRUEBAS)
    temporal = None
    try:
        if a.simular:
            ctx, temporal = _preparar_simulacion(a.escenario)
        else:
            presupuesto = PRESUPUESTO_P5_S if a.solo == "P5" else a.presupuesto
            ctx = comun.contexto_real(presupuesto, {"zip": a.zip, "conservar": a.conservar})
    except (ErrorConfig, comun.ErrorArnes) as e:
        print(f"FALLO rc=2: {e}")
        return comun.RC_USO
    print(f"Arnés paso 0a · {'SIMULADO (' + a.escenario + ')' if a.simular else 'REAL contra Azure'} · "
          f"resultados en {ctx.dir_resultados}")
    codigos = []
    try:
        for id_prueba in seleccion:
            prueba = PRUEBAS[id_prueba]
            destino = ctx.dir_resultados / f"{id_prueba}.json"
            if a.repetir:
                ctx.borrar_progreso(id_prueba)
            elif not a.simular and destino.exists() and not ctx.ruta_progreso(id_prueba).exists():
                previo = comun.leer_json(destino) or {}
                print(f"{id_prueba} {prueba.TITULO}: ya tiene resultado {previo.get('estado')} ({previo.get('fecha')}); "
                      "usa --repetir para volver a ejecutarla")
                codigos.append(comun.codigo_salida(previo.get("estado", "FALLA")))
                continue
            print(f"{id_prueba} {prueba.TITULO}: en marcha (quedan {ctx.restante():.0f} s de presupuesto)")
            ctx.cliente.llamadas.clear()
            try:
                res = correr(prueba, ctx)
            except azure_auth.ErrorAutenticacion as e:
                print(f"PARADA rc=5 (autenticación): {e}\nFernando debe ejecutar: ! "
                      f"{azure_auth.mensaje_login(ctx.cfg['tenant_id'])}")
                return comun.RC_AUTENTICACION
            except (azure_auth.ErrorAz, OperacionNoPermitida, comun.ErrorArnes) as e:
                print(f"FALLO DEL ARNÉS rc=2 en {id_prueba}: {type(e).__name__}: {comun.redactar(str(e))}")
                return comun.RC_USO
            if isinstance(res, comun.EnCurso):
                print(f"{id_prueba}: EN CURSO (sin veredicto todavía) · {res.mensaje}")
                codigos.append(comun.RC_EN_CURSO)
                continue
            res["evidencia"] = ctx.marcar(res["evidencia"])
            ruta = comun.escribir_json(destino, res)
            print(f"{id_prueba}: {res['estado']} → {ruta}\n{res['evidencia']}\n")
            codigos.append(comun.codigo_salida(res["estado"]))
    finally:
        if temporal is not None:
            shutil.rmtree(temporal, ignore_errors=True)
    rc = codigo_global(codigos)
    print(f"Código de salida: {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
