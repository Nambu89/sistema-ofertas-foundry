import { describe, expect, it } from "vitest";
import { euros, pasos } from "./fases";

const F = ["BORRADOR", "INFORMACION_INSUFICIENTE", "EN_ANALISIS", "EN_VERIFICACION", "VERIFICADA", "LISTA_PARA_REVISION"];

describe("pasos", () => {
  it("antes del primer turno, el alta está en curso", () => {
    expect(pasos(F, -1, false)).toEqual(["actual", "pendiente", "pendiente", "pendiente", "pendiente", "pendiente"]);
  });
  it("en verificación, lo anterior está hecho", () => {
    expect(pasos(F, 3, false)).toEqual(["hecho", "hecho", "hecho", "actual", "pendiente", "pendiente"]);
  });
  it("con el paquete listo, todo está hecho", () => {
    expect(pasos(F, 5, true).every((p) => p === "hecho")).toBe(true);
  });
});

describe("euros", () => {
  it("formatea en castellano", () => {
    expect(euros(22632.5).replace(/\s/g, " ")).toBe("22.632,50 €");
    expect(euros(undefined)).toBe("—");
  });
});
