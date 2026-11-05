import { useMutation } from "@tanstack/react-query";
import { FileText, Send } from "lucide-react";
import { type FormEvent, useState } from "react";
import { api } from "../api";
import { Aviso } from "./Aviso";

const MAX_BYTES = 5 * 1024 * 1024;

const PILARES = [
  { id: "microsoft", nombre: "Microsoft", activo: true, nota: "Experto de Azure, verificador y precios oficiales conectados." },
  { id: "google", nombre: "Google Cloud", activo: false, nota: "En construcción: todavía no tiene experto ni precios conectados. No se simula." },
  { id: "aws", nombre: "AWS", activo: false, nota: "En construcción: todavía no tiene experto ni precios conectados. No se simula." },
];

const campo = "mt-1 block w-full min-h-11 rounded-md border border-borde bg-white px-3 py-2 text-base";
const etiqueta = "block text-sm font-semibold";
const ayuda = "mt-1 text-sm text-tenue";

function leerBase64(f: File): Promise<string> {
  return new Promise((ok, mal) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => mal(new Error("No se ha podido leer el fichero."));
    r.readAsDataURL(f);
  });
}

export function NuevaSolicitud({ alCrear }: { alCrear: (id: string) => void }) {
  const [fichero, setFichero] = useState<File | null>(null);
  const [errorLocal, setErrorLocal] = useState<string | null>(null);
  const crear = useMutation({ mutationFn: api.crear, onSuccess: (s) => alCrear(s.id) });

  async function enviar(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrorLocal(null);
    const f = new FormData(e.currentTarget);
    if (!fichero) return setErrorLocal("Adjunta la transcripción de la reunión.");
    if (fichero.size > MAX_BYTES) return setErrorLocal("La transcripción supera los 5 MB.");
    crear.mutate({
      pilar: String(f.get("pilar")),
      cliente: String(f.get("cliente")),
      codigo_cliente: String(f.get("codigo_cliente")).toUpperCase(),
      seqof: String(f.get("seqof")),
      titulo: String(f.get("titulo")),
      sensibles: String(f.get("sensibles")).split(";").map((s) => s.trim()).filter(Boolean),
      explicacion: String(f.get("explicacion")),
      nda: f.get("nda") === "on",
      adjunto: { nombre: fichero.name, base64: await leerBase64(fichero) },
    });
  }

  const error = errorLocal ?? (crear.isError ? crear.error.message : null);
  return (
    <section aria-labelledby="titulo-nueva">
      <h1 id="titulo-nueva" className="text-2xl font-bold sm:text-3xl">Nueva solicitud de preventa</h1>
      <p className="mt-2 max-w-2xl text-tenue">
        Registra la reunión con el cliente. El coordinador extrae los requisitos de la transcripción, te pregunta lo que falte
        y prepara el paquete de revisión. Usa solo datos ficticios.
      </p>
      <form onSubmit={enviar} className="mt-8 grid gap-8" noValidate={false}>
        <fieldset>
          <legend className="text-lg font-bold">Pilar</legend>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {PILARES.map((p) => (
              <label key={p.id}
                className={`flex gap-3 rounded-lg border-2 p-4 ${p.activo ? "cursor-pointer border-borde has-checked:border-grafito has-checked:bg-panel" : "cursor-not-allowed border-dashed border-borde bg-panel/60"}`}>
                <input type="radio" name="pilar" value={p.id} defaultChecked={p.activo} disabled={!p.activo}
                  aria-describedby={`nota-${p.id}`} className="mt-1 size-5 accent-grafito" />
                <span>
                  <span className="block font-semibold">
                    {p.nombre}
                    {!p.activo && <span className="ms-2 rounded bg-white px-2 py-0.5 text-xs font-semibold text-poppy-texto ring-1 ring-poppy-texto">En construcción</span>}
                  </span>
                  <span id={`nota-${p.id}`} className="mt-1 block text-sm text-tenue">{p.nota}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset className="grid gap-5 md:grid-cols-2">
          <legend className="mb-3 text-lg font-bold">Cliente y solicitud</legend>
          <div>
            <label htmlFor="cliente" className={etiqueta}>Cliente (ficticio)</label>
            <input id="cliente" name="cliente" required minLength={2} maxLength={200} className={campo} autoComplete="off" />
          </div>
          <div className="grid grid-cols-[1fr_6rem] gap-3">
            <div>
              <label htmlFor="codigo_cliente" className={etiqueta}>Código de cliente</label>
              <input id="codigo_cliente" name="codigo_cliente" required pattern="[A-Za-z0-9]{2,20}" maxLength={20}
                aria-describedby="ayuda-codigo" className={`${campo} uppercase`} autoComplete="off" />
            </div>
            <div>
              <label htmlFor="seqof" className={etiqueta}>SEQOF</label>
              <input id="seqof" name="seqof" required pattern="[0-9]{3}" defaultValue="001" inputMode="numeric" className={campo} />
            </div>
            <p id="ayuda-codigo" className={`${ayuda} col-span-2`}>Letras y cifras, sin espacios. Forma el código de oferta OF-CÓDIGO-SEQOF.</p>
          </div>
          <div className="md:col-span-2">
            <label htmlFor="titulo" className={etiqueta}>Título</label>
            <input id="titulo" name="titulo" required minLength={5} maxLength={160} className={campo} />
          </div>
          <div className="md:col-span-2">
            <label htmlFor="sensibles" className={etiqueta}>Términos sensibles</label>
            <input id="sensibles" name="sensibles" required aria-describedby="ayuda-sensibles" className={campo} />
            <p id="ayuda-sensibles" className={ayuda}>Separados por punto y coma (;): nombre del cliente, personas, ciudades. Se anonimizan antes de hablar con los expertos.</p>
          </div>
          <div className="md:col-span-2">
            <label htmlFor="explicacion" className={etiqueta}>Explicación (opcional)</label>
            <textarea id="explicacion" name="explicacion" rows={3} maxLength={2000} aria-describedby="ayuda-explicacion" className={campo} />
            <p id="ayuda-explicacion" className={ayuda}>Queda registrada con el alta. Los requisitos salen solo de la transcripción.</p>
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-lg font-bold">Transcripción de la reunión</legend>
          <label htmlFor="transcripcion"
            className="mt-3 flex cursor-pointer flex-col items-center gap-2 rounded-lg border-2 border-dashed border-borde bg-panel p-6 text-center hover:border-grafito has-[:focus-visible]:outline-[3px] has-[:focus-visible]:outline-poppy has-[:focus-visible]:outline-offset-2">
            <FileText aria-hidden="true" className="size-8" />
            <span className="font-semibold">{fichero ? fichero.name : "Elige el fichero de la transcripción"}</span>
            <span className="text-sm text-tenue">.txt, .vtt o .docx · máximo 5 MB</span>
            <input id="transcripcion" type="file" accept=".txt,.vtt,.docx" required className="sr-only"
              onChange={(e) => setFichero(e.currentTarget.files?.[0] ?? null)} />
          </label>
        </fieldset>

        <label className="flex items-start gap-3">
          <input type="checkbox" name="nda" required className="mt-1 size-5 accent-grafito" />
          <span>Confirmo que el NDA con el cliente permite tratar esta información con IA en nuestro entorno de Microsoft Foundry.</span>
        </label>

        <div aria-live="polite">{error && <Aviso tipo="error" titulo="No se ha registrado la solicitud">{error}</Aviso>}</div>

        <div>
          <button type="submit" disabled={crear.isPending}
            className="inline-flex min-h-12 cursor-pointer items-center gap-2 rounded-md bg-grafito px-6 font-semibold text-white hover:bg-grafito-hover disabled:cursor-wait disabled:opacity-70">
            <Send aria-hidden="true" className="size-5" />
            {crear.isPending ? "Registrando…" : "Registrar solicitud"}
          </button>
        </div>
      </form>
    </section>
  );
}
