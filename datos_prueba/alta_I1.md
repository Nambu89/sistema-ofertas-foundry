# Alta sintética de I1 (lo que el comercial escribe en el playground)

**Todo es inventado.** Kelvara Ensayos Industriales, S.A. no es un cliente ni existe; Marta Olmedo,
Iker Salaverri y Nuria Castells son personas inventadas. Ningún dato procede de un cliente real.

## Procedencia de la forma (LES-G-078)

- **Formato de la transcripción**: WebVTT tal como lo exporta Microsoft Teams (cabecera `WEBVTT`,
  marcas `hh:mm:ss.mmm --> hh:mm:ss.mmm` y hablante en `<v Nombre>…</v>`), renombrado a `.txt`
  como prevé el flujo T1 (`sintesis.md`, «un .vtt de Teams se renombra a .txt»). La forma de
  turnos y el tono de reunión de descubrimiento se han contrastado con una transcripción real de
  Teams del workspace (exportada a Markdown, con hablante y minuto por intervención), **sin copiar
  ninguna frase, nombre ni dato**. No se ha tenido delante un `.vtt` real exportado: el formato
  exacto de cue de Teams (identificadores de cue, etiqueta `</v>` de cierre) es **NO VERIFICADO**
  contra un fichero real y debe contrastarse con el primer `.vtt` real que llegue; el parser de A
  debe aceptar cues con y sin identificador y con o sin `</v>`.
- **Dominio y estructura de la necesidad**: inspirada en la forma de un caso real de asistente de
  consulta documental para un departamento de I+D industrial (búsqueda con citas, resumen de
  informes técnicos, comparación entre ensayos, seguridad con Entra ID), **sin copiar nada**: otra
  empresa, otro sector concreto (laboratorio de ensayos de materiales), otras personas, otras cifras.
- **Huecos a propósito**: la transcripción **no** dice cuántos usuarios ni cuántos documentos hay
  (volumetría) ni dónde están los documentos ni quién da los permisos (identidad y ACL del origen,
  LES-G-065), para probar `ASUMIR`. El resto de campos sí está cubierto con frases citables.

## Mensaje de alta (T1), tal como lo escribiría el comercial

> Alta de solicitud nueva. Adjunto la transcripción `transcripcion_sintetica_I1.txt` (reunión de
> descubrimiento del 08-10-2026).
>
> - Cliente: Kelvara Ensayos Industriales, S.A.
> - Código de cliente: KELVARA · SEQOF: 001 (código de oferta OF-KELVARA-001, versión A)
> - Título: Asistente de consulta técnica con IA sobre informes de ensayo
> - Términos sensibles: Kelvara Ensayos Industriales; Kelvara; Marta Olmedo; Iker Salaverri;
>   Nuria Castells; Zaragoza; Tarragona
> - Confirmo que el NDA con el cliente permite tratar esta información con IA en nuestro entorno de Microsoft Foundry.
> - Idioma de la oferta: castellano.

Comando equivalente que debe ejecutar el coordinador (CONTRATOS.md §2):

```bash
python preventa_run.py iniciar --cliente "Kelvara Ensayos Industriales, S.A." \
  --codigo-cliente KELVARA --seqof 001 \
  --titulo "Asistente de consulta técnica con IA sobre informes de ensayo" \
  --transcripcion transcripcion_sintetica_I1.txt \
  --sensible "Kelvara Ensayos Industriales" --sensible "Kelvara" --sensible "Marta Olmedo" \
  --sensible "Iker Salaverri" --sensible "Nuria Castells" --sensible "Zaragoza" \
  --sensible "Tarragona" --nda-confirmado
```

`iniciar` añade por su cuenta los hablantes (`Responsable comercial`, `Marta Olmedo`, `Iker Salaverri`,
`Nuria Castells`) y el cliente a `terminos_sensibles`.

## Resultado esperado de T1

1. `suficiencia` → **INFORMACION_INSUFICIENTE** (rc 1) con dos preguntas a/b/c/d: `volumetria` e
   `identidad_acl_origen`. Los cinco BLOQUEANTES quedan CITADO.
2. Respuesta del comercial (siguiente mensaje):

> ASUMIR: volumetria = 150 técnicos usuarios y unos 20.000 documentos (informes, procedimientos y normas)
>
> ASUMIR: identidad_acl_origen = Documentos en SharePoint Online del tenant del cliente, con permisos por grupos de Entra ID que se respetan en las respuestas

3. `asumir` dos veces → **EN_ANALISIS**. Los dos quedan como supuestos de confianza baja visibles
   en la diapositiva de supuestos y en la nota de revisión. En el brief, «150 técnicos» se
   convierte en «entre 100 y 500 técnicos usuarios» (casi-identificador, CONTRATOS.md §6.2).

## Pruebas negativas que usan estos datos (las monta E)

- Un `--sensible` que siga apareciendo en el brief → `Bloqueo` (no debe ocurrir).
- Una cita alterada en `requisitos.json` (p. ej. «tres meses» → «cuatro meses») → cita inválida.
- `ASUMIR: objetivo = …` → rc 2: `objetivo` es BLOQUEANTE.
