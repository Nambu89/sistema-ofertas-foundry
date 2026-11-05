# Alta sintética de I1.8 · Hostelia (generalización de la prueba real de B)

**Todo es FICTICIO.** Hostelia Grupo Hotelero, S.A. no es un cliente ni existe; Marina Couto y Rodrigo Valcárcel son
personas inventadas. Ningún dato procede de un cliente real. Se usa en la prueba real de I1.8
(`pruebas/I18/PRUEBA-REAL.md` §3) para comprobar que B generaliza a una solicitud distinta de Brezalia.

## Procedencia de la forma (LES-G-078)

- **Formato**: el mismo WebVTT que `pruebas/I12/REAL/transcripcion_sintetica_I11V.txt` (cabecera `WEBVTT`, marcas
  `hh:mm:ss.mmm --> hh:mm:ss.mmm` y hablante en `<v Nombre>…</v>`), que ya pasó la suficiencia en real en I1.4 a I1.7.
- **Necesidad**: la que fijó el PM el 13-10-2026 para esta tanda, sin añadir hechos:
  - asistente de RR. HH. para unos 1.200 empleados de España y Portugal, usado desde Microsoft Teams;
  - responde sobre las políticas de RR. HH. con los documentos de SharePoint Online (permisos por grupos de Entra ID);
  - consulta el saldo de vacaciones y registra solicitudes de días libres por la API REST de RR. HH. que el cliente ya
    tiene en Azure (App Service propio), publicada con API Management;
  - unas 6.000 consultas y 1.500 acciones al mes; unos 800 documentos; RGPD y datos en la UE; plazo de 10 semanas;
  - ya tienen licencias de Microsoft 365 E3 (es la cita de `ya_contratado_por_cliente`, REV17-3).
- **Lo que no dice a propósito** (no lo fijó el PM y no se inventa): red privada, tipo de suscripción de Azure,
  presupuesto orientativo y lo que queda fuera de alcance. Si la suficiencia lo pide, se responde con las líneas
  `ASUMIR` de `pruebas/I18/REAL/mensajes/H_asumir.txt`, iguales en las dos sesiones (acceso público con autenticación,
  Enterprise Agreement o MCA-E directo, entre 25.000 y 60.000 euros). Son supuestos de la prueba: la oferta los muestra
  como «asumido, confianza baja» y los pide confirmar al cliente.

## Mensaje de alta (T1)

`pruebas/I18/REAL/mensajes/H_T1_alta.txt`, con la transcripción `datos_prueba/transcripcion_sintetica_I18_hostelia.txt`
adjunta como `input_file`.

## Lo que se espera ver (y que la puerta no ve)

- Componentes del catálogo coherentes con la necesidad: Microsoft Foundry (modelo y agente), Azure AI Search sobre los
  documentos de SharePoint con filtrado por permisos (LES-G-065), el canal de Teams y la llamada a la API de RR. HH. a
  través de API Management del cliente.
- Nivel y cómputo justificados o el valor por defecto del catálogo; instancias de más de 1 con justificación visible.
- `a_cargo_del_cliente` solo con la cita de Microsoft 365 E3, o de la API y el App Service que el cliente ya tiene.
- Consumo coherente con la volumetría: 6.000 consultas y 1.500 acciones al mes, 800 documentos.
- Si el experto necesita un servicio fuera del catálogo, se anota como hallazgo con lo que habría que añadir.
