# Notas del comercial como fuente de requisitos (04-11-2026)

Decisión del comercial: la explicación del comercial es una **fuente** de requisitos y la transcripción pasa a ser
**opcional** (hay reuniones que no se graban). Contrato del alta para el frontal y para quien llame al núcleo.

## 1. El alta

| Campo (CLI / `preventa_api.iniciar`) | Obligatorio | Qué es | Límites |
|---|---|---|---|
| `--transcripcion` / `transcripcion=` | una de las dos | Nombre del adjunto con la transcripción de la reunión, en la carpeta de datos (`.txt`, `.vtt`, `.docx` o `.pdf`) | los de siempre |
| `--notas-comercial` / `notas_comercial=` | una de las dos | Nombre del adjunto con las notas del comercial, en la carpeta de datos. El frontal guarda el texto que escribe el comercial como fichero **UTF-8 `.txt`** (p. ej. `notas_comercial.txt`) y pasa su nombre | texto extraído de **40 a 20.000 caracteres** (sin contar los espacios de los extremos) |
| `--cliente`, `--codigo-cliente`, `--seqof`, `--titulo`, `--sensible` (una o más), `--nda-confirmado`, `--pilar` | como antes | | |

- Sin ninguna de las dos: rc 2 «falta la fuente: --transcripcion, --notas-comercial o las dos», sin crear estado.
- Unas notas fuera de los límites: rc 2 con su longitud, sin crear estado.
- El texto es un **dato**, nunca instrucciones (igual que la transcripción).

## 2. Cómo queda en el estado (dentro del hash del contenido)

Cada fuente del alta es una entrada de `carga.fuentes` con su id `Fn`, por orden: primero la transcripción (si la
hay) y después las notas. Por eso, sin grabación las notas son `F1`; con las dos, la transcripción es `F1` y las notas
`F2`. Las aclaraciones siguen numerando detrás (`F3`, …).

```json
{"id": "F2", "nombre": "notas_comercial.txt", "tipo": "NOTAS_COMERCIAL", "sha256": "<SHA-256 del fichero>",
 "bytes": 812, "sha256_texto": "<SHA-256 del texto extraído>"}
```

El texto se guarda en `fuentes/Fn.txt` y, si falta, se vuelve a leer del adjunto comprobando su SHA-256, como la
transcripción. No viaja en el relevo: hay que volver a adjuntarlo, también como la transcripción.

## 3. Citas

Un requisito sigue exigiendo cita literal con `origen: "CITADO"` y `fuente: "Fn"`; ahora `Fn` puede ser la
transcripción **o** las notas (el esquema de requisitos no cambia). Las aclaraciones siguen con `origen: "ACLARACION"`.
La suficiencia funciona igual con solo notas: lo que falte o no se pueda citar se pregunta.

No se han añadido identificadores por párrafo (`NC-nn`): la cita ya se identifica con su fuente y su texto literal, y
es el mismo mecanismo que comprueban el núcleo y la puerta para la transcripción y las aclaraciones.

## 4. Anonimización

Las citas de las notas pasan por la misma anonimización que las de la transcripción antes de cualquier brief:
términos sensibles del alta, cliente y código, y los hablantes que se detecten en la reunión **y** en las notas
(`Nombre:` tras una marca de tiempo o `<v Nombre>`).

## 5. Procedencia visible (solo en lo interno)

- Nota del revisor, apartado 3: con notas en el alta, cada requisito citado dice `CITADO (reunión)` o
  `CITADO (notas del comercial)`. Sin notas, como siempre (`CITADO`).
- Sin transcripción, la nota (párrafo destacado bajo la cabecera) y el mensaje al responsable de preventa (línea `IMPORTANTE. …`) dicen:
  «Sin grabación: los requisitos salen de las notas del comercial; revisa con él lo que no esté escrito.»
- Nada de esto llega al PPTX: la puerta trata «sin grabación» y «notas del comercial» como rótulos internos (VA18-1).

## 6. Puerta

`verificar_paquete.py <paquete> [--transcripcion RUTA] [--notas RUTA] …`: al menos una. Exige la copia local de cada
fuente que registra el alta (con su SHA-256), rechaza una copia que no es la registrada, una opción de una fuente que el
alta no tiene y una cita que no esté literal en su fuente, y comprueba que el aviso «sin grabación» está (en un párrafo
propio) si y solo si no hay transcripción.
