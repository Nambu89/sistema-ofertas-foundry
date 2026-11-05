# Frontal local de preventa

Interfaz web para que un comercial registre una solicitud (transcripción de la reunión y explicación), siga las fases del
coordinador B (`preventa-prueba-hosted`) y descargue el paquete de revisión. Primera versión: **solo en local, sin inicio
de sesión y con datos sintéticos**. Solo funciona el pilar Microsoft; Google Cloud y AWS aparecen deshabilitados como «en
construcción».

## Arrancarlo en el Mac

Requisitos: Python 3.13, `uv`, Node 24 y sesión de la CLI de Azure en el tenant de `config/entorno.local.json`
(`az login --tenant <tenant de config/entorno.local.json>`). Desde la raíz del repositorio:

```bash
uv venv -q -p 3.13 frontal/.venv && uv pip install -q -p frontal/.venv/bin/python -r frontal/bff/requirements.txt && npm --prefix frontal/web ci && npm --prefix frontal/web run build
frontal/.venv/bin/python frontal/bff/servidor.py
```

Y abrir <http://127.0.0.1:8765>. Con `--reproduccion` no se llama a Foundry: el BFF devuelve en orden los turnos reales
guardados de la prueba de Hostelia (cliente sintético) de I1.9, saneados para publicar, y un ZIP reducido con solo lo
que lee el frontal (`bff/reproduccion/`). La interfaz lo avisa en pantalla.

## Cómo funciona

| Pieza | Qué hace |
|---|---|
| `bff/servidor.py` | Servidor HTTP de la biblioteca estándar, **solo en 127.0.0.1**. Sirve `web/dist`, valida el formulario y el adjunto (.txt, .vtt o .docx, hasta 5 MB), compone el alta con la gramática de `hosted/preventa_hosted/mensajes.py` y ejecuta los turnos en un hilo. Una solicitud activa a la vez. Rechaza otro `Host` (DNS rebinding) y lo que no sea JSON. |
| `bff/coordinador.py` | Responses API por el endpoint del agente con `background: true` y sondeo. El token sale de la sesión `az` con tenant fijo (`lib/azure_auth.py` a través de `lib/foundry.py`); no se guarda ni se imprime. Descarga el ZIP de la carpeta de la sesión y lo da solo si coinciden tamaño y SHA-256 con la línea `PAQUETE` del coordinador. |
| `bff/protocolo.py` | Lee **solo los marcadores explícitos** del núcleo (`=== ESTADO PREVENTA ===`, `=== PREGUNTAS PARA EL COMERCIAL ===`, la línea `PAQUETE:`), nunca expresiones sobre el registro (LES-G-030). El avance solo sube (LES-G-031). |
| `web/` | React 19, Vite 7, TypeScript 5.9, Tailwind 4 y TanStack Query. Tres pantallas: nueva solicitud, seguimiento con preguntas de suficiencia y resultado. Marca Devoteam: Montserrat, #F8485E, #3C3C3A y blanco. |

Tras cada turno, el BFF envía `SIGUE` mientras el estado no sea una parada (preguntas, paquete listo, bloqueada, stop de
presupuesto, revisión o devuelta), con un tope de 15 turnos seguidos. Las respuestas a las preguntas viajan como
`ASUMIR: campo = valor`. La explicación del comercial va en el mensaje del alta; el coordinador extrae los requisitos solo
de la transcripción.

El frontal no guarda nada al reiniciarse: los ZIP descargados quedan en `frontal/.descargas/` (ignorada por git).

## Pruebas

```bash
(cd frontal/bff && ../.venv/bin/python -m pytest -q -p no:cacheprovider test_bff.py)   # contrato con turnos reales guardados
npm --prefix frontal/web test                                                         # utilidades de la interfaz
(cd frontal/web && npx playwright install chromium && npx playwright test)            # recorrido + axe en 375, 768 y 1440 px
```

Contra el coordinador real (con el servidor arrancado y sesión `az`): `(cd frontal/web && npx playwright test -c
playwright.real.config.ts)`. Las capturas quedan en `frontal/evidencias/`.
