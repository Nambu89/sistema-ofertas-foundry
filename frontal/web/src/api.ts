// Contrato con el BFF (frontal/bff/servidor.py, Solicitud.publico y Gestor.resumen).

export type Opcion = { letra: string; texto: string; libre: boolean };
export type Pregunta = { campo: string; pregunta: string; opciones: Opcion[] };
export type Turno = { n: number; enviado: string; estado: string | null; segundos: number; texto: string };

export type Solicitud = {
  id: string;
  pilar: string;
  titulo: string;
  ocupado: boolean;
  estado: string | null;
  fase_max: number;
  fases: string[];
  siguiente: string;
  lote: { actual: number; total: number } | null;
  preguntas: Pregunta[];
  error: string | null;
  paquete: { nombre: string; bytes: number; sha256: string; descargado: boolean } | null;
  economia: { precio_cerrado_eur?: number; consumo_mes_eur?: number };
  turnos: Turno[];
};

export type Resumen = {
  codigo: string;
  estado: string;
  hash_contenido: string;
  ficheros: { nombre: string; bytes: number }[];
  nota_revisor: string;
  economia: Solicitud["economia"];
};

export type Salud = { modo: "real" | "reproduccion"; sesion_az: boolean; detalle?: string };

export type Alta = {
  pilar: string;
  cliente: string;
  codigo_cliente: string;
  seqof: string;
  titulo: string;
  sensibles: string[];
  explicacion: string;
  nda: boolean;
  adjunto: { nombre: string; base64: string };
};

async function pedir<T>(ruta: string, cuerpo?: unknown): Promise<T> {
  const r = await fetch(ruta, cuerpo === undefined ? undefined : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  const datos = (await r.json().catch(() => ({}))) as { error?: string };
  if (!r.ok) throw new Error(datos.error ?? `El frontal respondió HTTP ${r.status}.`);
  return datos as T;
}

export const api = {
  salud: () => pedir<Salud>("/api/salud"),
  solicitud: (id: string) => pedir<Solicitud>(`/api/solicitudes/${id}`),
  resumen: (id: string) => pedir<Resumen>(`/api/solicitudes/${id}/resumen`),
  crear: (alta: Alta) => pedir<Solicitud>("/api/solicitudes", alta),
  responder: (id: string, respuestas: Record<string, string>) =>
    pedir<Solicitud>(`/api/solicitudes/${id}/respuestas`, { respuestas }),
  continuar: (id: string) => pedir<Solicitud>(`/api/solicitudes/${id}/continuar`, {}),
  reintentarDescarga: (id: string) => pedir<Solicitud>(`/api/solicitudes/${id}/descargar`, {}),
  urlPaquete: (id: string) => `/api/solicitudes/${id}/paquete`,
};
