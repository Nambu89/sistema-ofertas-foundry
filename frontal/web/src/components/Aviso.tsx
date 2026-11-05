import { CircleAlert, Info } from "lucide-react";
import type { ReactNode } from "react";

export function Aviso({ tipo, titulo, children }: { tipo: "info" | "error"; titulo: string; children: ReactNode }) {
  const Icono = tipo === "error" ? CircleAlert : Info;
  return (
    <div role={tipo === "error" ? "alert" : "status"}
      className={`mb-6 flex gap-3 rounded-lg border-s-4 p-4 ${tipo === "error" ? "border-poppy-texto bg-poppy-suave" : "border-grafito bg-panel"}`}>
      <Icono aria-hidden="true" className={`mt-0.5 size-5 shrink-0 ${tipo === "error" ? "text-poppy-texto" : ""}`} />
      <div className="min-w-0">
        <p className="font-semibold">{titulo}</p>
        <div className="break-words text-sm">{children}</div>
      </div>
    </div>
  );
}
