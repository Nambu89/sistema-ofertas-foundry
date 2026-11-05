import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api";
import { Aviso } from "./components/Aviso";
import { NuevaSolicitud } from "./components/NuevaSolicitud";
import { Resultado } from "./components/Resultado";
import { Seguimiento } from "./components/Seguimiento";

function idDeLaUrl(): string | null {
  const id = new URLSearchParams(window.location.search).get("solicitud");
  return id && /^[0-9a-f]{32}$/.test(id) ? id : null;
}

export default function App() {
  const [id, setId] = useState<string | null>(idDeLaUrl);
  const salud = useQuery({ queryKey: ["salud"], queryFn: api.salud });
  const solicitud = useQuery({
    queryKey: ["solicitud", id],
    queryFn: () => api.solicitud(id as string),
    enabled: id !== null,
    refetchInterval: (q) => (q.state.data?.ocupado === false ? false : 2000),
  });

  const abrir = (nuevo: string | null) => {
    window.history.replaceState(null, "", nuevo ? `?solicitud=${nuevo}` : window.location.pathname);
    setId(nuevo);
  };
  const s = solicitud.data;
  const listo = s?.estado === "LISTA_PARA_REVISION" && s.paquete?.descargado === true;

  return (
    <div className="min-h-dvh bg-white">
      <a href="#principal" className="sr-only focus:not-sr-only focus:absolute focus:start-2 focus:top-2 focus:bg-white focus:p-2">
        Saltar al contenido
      </a>
      <header className="border-b-4 border-poppy bg-grafito text-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <p className="text-lg font-bold tracking-tight">
            Devoteam <span className="font-medium">· Preventa multinube</span>
          </p>
          {id && (
            <button type="button" onClick={() => abrir(null)}
              className="min-h-11 rounded-md border border-white/70 px-3 text-sm font-semibold hover:bg-white/10 cursor-pointer">
              Nueva solicitud
            </button>
          )}
        </div>
      </header>
      <main id="principal" className="mx-auto max-w-5xl px-4 py-6 sm:py-10">
        {salud.data?.modo === "reproduccion" && (
          <Aviso tipo="info" titulo="Modo reproducción">
            Las respuestas del coordinador son turnos reales ya guardados de una prueba con datos sintéticos (Hostelia). No se
            llama a Foundry.
          </Aviso>
        )}
        {salud.data && !salud.data.sesion_az && (
          <Aviso tipo="error" titulo="Sin sesión de Azure">{salud.data.detalle}</Aviso>
        )}
        {salud.isError && <Aviso tipo="error" titulo="El frontal no responde">{salud.error.message}</Aviso>}
        {id === null && <NuevaSolicitud alCrear={abrir} />}
        {id !== null && solicitud.isError && (
          <Aviso tipo="error" titulo="No se puede leer la solicitud">{solicitud.error.message}</Aviso>
        )}
        {s && !listo && <Seguimiento solicitud={s} />}
        {s && listo && <Resultado solicitud={s} />}
      </main>
    </div>
  );
}
