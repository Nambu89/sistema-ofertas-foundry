// Etiquetas de las fases del núcleo (sandbox/nucleo/estado.py) en el orden que da el BFF.

export const ETIQUETAS: Record<string, string> = {
  BORRADOR: "Alta y requisitos",
  INFORMACION_INSUFICIENTE: "Suficiencia de la información",
  EN_ANALISIS: "Análisis del experto de Azure",
  EN_VERIFICACION: "Verificación independiente",
  VERIFICADA: "Consumo, estimación y documentos",
  LISTA_PARA_REVISION: "Paquete listo para revisión",
};

export type EstadoPaso = "hecho" | "actual" | "pendiente";

/** Estado de cada paso. Solo sube: el BFF ya guarda el máximo alcanzado (LES-G-031). */
export function pasos(fases: string[], faseMax: number, terminado: boolean): EstadoPaso[] {
  const actual = Math.max(faseMax, 0);
  return fases.map((_, i) => {
    if (i < actual || (i === actual && terminado && i === fases.length - 1)) return "hecho";
    return i === actual ? "actual" : "pendiente";
  });
}

export function euros(n: number | undefined): string {
  if (n === undefined) return "—";
  return new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(n);
}
