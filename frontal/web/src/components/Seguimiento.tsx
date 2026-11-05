import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Circle, LoaderCircle, RotateCw } from "lucide-react";
import { type FormEvent, useState } from "react";
import { api, type Pregunta, type Solicitud } from "../api";
import { ETIQUETAS, pasos } from "../fases";
import { Aviso } from "./Aviso";

function textoEstado(s: Solicitud): string {
  if (s.error) return "El coordinador se ha parado.";
  if (s.estado === "INFORMACION_INSUFICIENTE" && !s.ocupado) return "El coordinador necesita tus respuestas para seguir.";
  if (s.estado === "LISTA_PARA_REVISION") return "Paquete listo: descargándolo de la sesión…";
  if (s.estado && !s.ocupado) return `Parado en ${s.estado}. Revisa el registro.`;
  if (s.lote) return `Verificando el lote ${s.lote.actual} de ${s.lote.total}…`;
  return "El coordinador está trabajando. Cada turno tarda entre 20 y 80 segundos.";
}

export function Seguimiento({ solicitud: s }: { solicitud: Solicitud }) {
  const qc = useQueryClient();
  const refrescar = (n: Solicitud) => qc.setQueryData(["solicitud", s.id], n);
  const responder = useMutation({ mutationFn: (r: Record<string, string>) => api.responder(s.id, r), onSuccess: refrescar });
  const continuar = useMutation({ mutationFn: () => api.continuar(s.id), onSuccess: refrescar });
  const descargar = useMutation({ mutationFn: () => api.reintentarDescarga(s.id), onSuccess: refrescar });
  const faltaDescarga = s.estado === "LISTA_PARA_REVISION" && s.paquete !== null && !s.paquete.descargado && !s.ocupado;
  const estados = pasos(s.fases, s.fase_max, s.estado === "LISTA_PARA_REVISION");

  return (
    <section aria-labelledby="titulo-seguimiento">
      <p className="text-sm font-semibold uppercase tracking-wide text-poppy-texto">Seguimiento</p>
      <h1 id="titulo-seguimiento" className="mt-1 text-2xl font-bold sm:text-3xl">{s.titulo}</h1>
      <p role="status" aria-live="polite" className="mt-3 flex items-center gap-2 text-tenue">
        {s.ocupado && <LoaderCircle aria-hidden="true" className="size-5 animate-spin motion-reduce:animate-none" />}
        {textoEstado(s)}
      </p>

      <ol className="mt-8 grid gap-0" aria-label="Fases del coordinador">
        {s.fases.map((f, i) => {
          const e = estados[i];
          return (
            <li key={f} aria-current={e === "actual" ? "step" : undefined}
              className="relative flex gap-4 pb-6 last:pb-0 before:absolute before:start-[15px] before:top-8 before:h-[calc(100%-2rem)] before:w-0.5 before:bg-borde last:before:hidden">
              <span className={`relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border-2 ${e === "hecho" ? "border-hecho bg-hecho text-white" : e === "actual" ? "border-poppy bg-white" : "border-borde bg-white"}`}>
                {e === "hecho" ? <Check aria-hidden="true" className="size-4" /> : e === "actual" && s.ocupado
                  ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin motion-reduce:animate-none" />
                  : <Circle aria-hidden="true" className={`size-3 ${e === "actual" ? "fill-poppy text-poppy" : "text-borde"}`} />}
              </span>
              <span className="pt-1">
                <span className={`block font-semibold ${e === "pendiente" ? "text-tenue" : ""}`}>{ETIQUETAS[f] ?? f}</span>
                <span className="sr-only">{e === "hecho" ? "(hecha)" : e === "actual" ? "(en curso)" : "(pendiente)"}</span>
                {e === "actual" && f === "EN_VERIFICACION" && s.lote && (
                  <span className="block text-sm text-tenue">Lote {s.lote.actual} de {s.lote.total}</span>
                )}
              </span>
            </li>
          );
        })}
      </ol>

      {s.error && (
        <div className="mt-8">
          <Aviso tipo="error" titulo="El coordinador se ha parado">{s.error}</Aviso>
          {faltaDescarga && (
            <button type="button" onClick={() => descargar.mutate()} disabled={descargar.isPending}
              className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md bg-grafito px-5 font-semibold text-white hover:bg-grafito-hover">
              <RotateCw aria-hidden="true" className="size-4" /> {descargar.isPending ? "Descargando…" : "Reintentar descarga"}
            </button>
          )}
          {descargar.isError && <p role="alert" className="mt-2 text-poppy-texto">{descargar.error.message}</p>}
          {!s.ocupado && s.turnos.length > 0 && s.estado !== "INFORMACION_INSUFICIENTE" && s.estado !== "LISTA_PARA_REVISION" && (
            <button type="button" onClick={() => continuar.mutate()} disabled={continuar.isPending}
              className="inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md bg-grafito px-5 font-semibold text-white hover:bg-grafito-hover">
              <RotateCw aria-hidden="true" className="size-4" /> Continuar
            </button>
          )}
          {continuar.isError && <p role="alert" className="mt-2 text-poppy-texto">{continuar.error.message}</p>}
        </div>
      )}

      {s.estado === "INFORMACION_INSUFICIENTE" && !s.ocupado && s.preguntas.length > 0 && (
        <Preguntas preguntas={s.preguntas} enviando={responder.isPending}
          error={responder.isError ? responder.error.message : null} alEnviar={(r) => responder.mutate(r)} />
      )}

      {s.turnos.length > 0 && (
        <section aria-labelledby="titulo-registro" className="mt-10">
          <h2 id="titulo-registro" className="text-lg font-bold">Registro del coordinador</h2>
          <p className="text-sm text-tenue">Salida literal de cada turno, tal como la devuelve el coordinador.</p>
          <div className="mt-3 grid gap-2">
            {s.turnos.map((t) => (
              <details key={t.n} className="rounded-md border border-borde">
                <summary className="min-h-11 cursor-pointer px-3 py-2.5 text-sm">
                  <span className="font-semibold">Turno {t.n}</span> · «{t.enviado}» → {t.estado ?? "sin estado"} · {t.segundos} s
                </summary>
                <pre tabIndex={0} aria-label={`Salida del turno ${t.n}`} className="max-h-96 overflow-auto whitespace-pre-wrap break-words border-t border-borde bg-panel p-3 text-xs">{t.texto}</pre>
              </details>
            ))}
          </div>
        </section>
      )}
    </section>
  );
}

function Preguntas({ preguntas, enviando, error, alEnviar }: {
  preguntas: Pregunta[]; enviando: boolean; error: string | null; alEnviar: (r: Record<string, string>) => void;
}) {
  const [elegidas, setElegidas] = useState<Record<string, string>>({});
  const [libres, setLibres] = useState<Record<string, string>>({});
  const [falta, setFalta] = useState<string | null>(null);

  function enviar(e: FormEvent) {
    e.preventDefault();
    const respuestas: Record<string, string> = {};
    for (const p of preguntas) {
      const op = p.opciones.find((o) => o.letra === elegidas[p.campo]);
      const valor = op?.libre ? (libres[p.campo] ?? "").trim() : op?.texto;
      if (!valor || valor.length < 2) return setFalta(`Falta responder: ${p.pregunta}`);
      respuestas[p.campo] = valor;
    }
    setFalta(null);
    alEnviar(respuestas);
  }

  return (
    <form onSubmit={enviar} className="mt-10 rounded-lg border-2 border-grafito p-4 sm:p-6" aria-labelledby="titulo-preguntas">
      <h2 id="titulo-preguntas" className="text-lg font-bold">Preguntas de suficiencia</h2>
      <p className="text-sm text-tenue">La transcripción no lo dice. Lo que elijas se registra como supuesto de confianza baja para confirmarlo con el cliente.</p>
      <div className="mt-5 grid gap-6">
        {preguntas.map((p) => (
          <fieldset key={p.campo}>
            <legend className="font-semibold">{p.pregunta}</legend>
            <div className="mt-2 grid gap-2">
              {p.opciones.map((o) => (
                <label key={o.letra} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border border-borde px-3 py-2 has-checked:border-grafito has-checked:bg-panel">
                  <input type="radio" name={p.campo} value={o.letra} checked={elegidas[p.campo] === o.letra}
                    onChange={() => setElegidas((x) => ({ ...x, [p.campo]: o.letra }))} className="size-5 accent-grafito" />
                  <span>{o.libre ? "Otra respuesta" : o.texto}</span>
                </label>
              ))}
              {p.opciones.some((o) => o.libre && elegidas[p.campo] === o.letra) && (
                <div>
                  <label htmlFor={`libre-${p.campo}`} className="text-sm font-semibold">Tu respuesta</label>
                  <input id={`libre-${p.campo}`} maxLength={600} value={libres[p.campo] ?? ""}
                    onChange={(e) => setLibres((x) => ({ ...x, [p.campo]: e.target.value }))}
                    className="mt-1 block min-h-11 w-full rounded-md border border-borde px-3" />
                </div>
              )}
            </div>
          </fieldset>
        ))}
      </div>
      <div aria-live="polite">
        {(falta ?? error) && <p role="alert" className="mt-4 font-semibold text-poppy-texto">{falta ?? error}</p>}
      </div>
      <button type="submit" disabled={enviando}
        className="mt-5 inline-flex min-h-12 cursor-pointer items-center rounded-md bg-grafito px-6 font-semibold text-white hover:bg-grafito-hover disabled:cursor-wait disabled:opacity-70">
        {enviando ? "Enviando…" : "Enviar respuestas"}
      </button>
    </form>
  );
}
