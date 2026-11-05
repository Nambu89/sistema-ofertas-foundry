import { useQuery } from "@tanstack/react-query";
import { Download, FileArchive } from "lucide-react";
import { api, type Solicitud } from "../api";
import { euros } from "../fases";
import { Aviso } from "./Aviso";

const kb = (n: number) => `${new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(n / 1024)} KB`;

// Nombre y extensión por separado: se recorta el nombre y la extensión queda siempre entera.
const partir = (n: string): [string, string] => {
  const i = n.lastIndexOf(".");
  return i > 0 ? [n.slice(0, i), n.slice(i)] : [n, ""];
};

export function Resultado({ solicitud: s }: { solicitud: Solicitud }) {
  const resumen = useQuery({ queryKey: ["resumen", s.id], queryFn: () => api.resumen(s.id) });
  const r = resumen.data;

  return (
    <section aria-labelledby="titulo-resultado">
      <p className="text-sm font-semibold uppercase tracking-wide text-poppy-texto">Resultado</p>
      <h1 id="titulo-resultado" className="mt-1 text-2xl font-bold sm:text-3xl">Paquete listo para revisión</h1>
      <p className="mt-2 max-w-2xl text-tenue">{s.titulo}. Antes de enviarlo a nadie, pasa la puerta local (verificar_paquete.py) sobre el ZIP.</p>

      <a href={api.urlPaquete(s.id)} download={s.paquete?.nombre}
        className="mt-6 inline-flex min-h-12 items-center gap-2 rounded-md bg-grafito px-6 font-semibold text-white hover:bg-grafito-hover">
        <Download aria-hidden="true" className="size-5" /> Descargar {s.paquete?.nombre}
      </a>

      {resumen.isError && <div className="mt-6"><Aviso tipo="error" titulo="No se puede leer el paquete">{resumen.error.message}</Aviso></div>}
      {resumen.isPending && <p role="status" className="mt-6 text-tenue">Leyendo el paquete…</p>}

      {r && (
        <>
          <dl className="mt-8 grid gap-4 sm:grid-cols-3">
            {[
              ["Código de oferta", r.codigo],
              ["Precio cerrado (sin IVA)", euros(r.economia.precio_cerrado_eur)],
              ["Consumo en la nube, orientativo", r.economia.consumo_mes_eur === undefined ? "—" : `${euros(r.economia.consumo_mes_eur)} al mes`],
            ].map(([t, v]) => (
              <div key={t} className="rounded-lg border-t-4 border-poppy bg-panel p-4">
                <dt className="text-sm text-tenue">{t}</dt>
                <dd className="mt-1 text-xl font-bold">{v}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
            <section aria-labelledby="titulo-ficheros" className="min-w-0">
              <h2 id="titulo-ficheros" className="text-lg font-bold">Contenido del paquete</h2>
              <ul className="mt-3 divide-y divide-borde rounded-md border border-borde">
                {r.ficheros.map((f) => (
                  <li key={f.nombre} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
                    <span className="flex min-w-0 items-center gap-2"><FileArchive aria-hidden="true" className="size-4 shrink-0" />
                      <span className="flex min-w-0" title={f.nombre}>
                        <span className="truncate">{partir(f.nombre)[0]}</span>
                        <span className="shrink-0">{partir(f.nombre)[1]}</span>
                      </span></span>
                    <span className="shrink-0 text-tenue">{kb(f.bytes)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 break-all text-xs text-tenue">Estado {r.estado} · huella del contenido {r.hash_contenido}</p>
            </section>
            <section aria-labelledby="titulo-nota" className="min-w-0">
              <h2 id="titulo-nota" className="text-lg font-bold">Mensaje para el revisor</h2>
              <pre tabIndex={0} aria-labelledby="titulo-nota" className="mt-3 max-h-[28rem] overflow-auto whitespace-pre-wrap break-words rounded-md border border-borde bg-panel p-4 text-sm">{r.nota_revisor}</pre>
            </section>
          </div>
        </>
      )}
    </section>
  );
}
