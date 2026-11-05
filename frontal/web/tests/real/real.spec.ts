import { expect, test } from "@playwright/test";
import path from "node:path";

const TRANSCRIPCION = path.resolve(import.meta.dirname, "../../../../datos_prueba/transcripcion_sintetica_I18_hostelia.txt");
const EVIDENCIAS = path.resolve(import.meta.dirname, "../../../evidencias");
// Supuestos de la prueba sintética (datos_prueba/alta_I18_hostelia.md); a cualquier otra pregunta, la opción a.
const RESPUESTAS: Record<string, string> = { red_privada: "c", tipo_suscripcion: "a", presupuesto_orientativo: "b" };

test("recorrido completo contra el coordinador real (Hostelia, sintético)", async ({ page }) => {
  const captura = (n: string) => page.screenshot({ path: `${EVIDENCIAS}/real-${n}.png`, fullPage: true });
  await page.goto("/");
  await expect(page.getByText("Sin sesión de Azure")).toHaveCount(0);
  await page.getByLabel("Cliente (ficticio)").fill("Hostelia Grupo Hotelero, S.A.");
  await page.getByLabel("Código de cliente").fill("HOSTELIA");
  await page.getByLabel("SEQOF").fill("002");
  await page.getByLabel("Título").fill("Asistente de RR. HH. para empleados en Microsoft Teams");
  await page.getByLabel("Términos sensibles").fill("Hostelia Grupo Hotelero; Hostelia; Marina Couto; Rodrigo Valcárcel");
  await page.getByLabel("Explicación (opcional)").fill("Asistente de RR. HH. en Teams para unos 1.200 empleados de España y Portugal.");
  await page.locator("#transcripcion").setInputFiles(TRANSCRIPCION);
  await page.getByLabel(/Confirmo que el NDA/).check();
  await captura("1-nueva-solicitud");
  await page.getByRole("button", { name: "Registrar solicitud" }).click();

  const preguntas = page.getByRole("heading", { name: "Preguntas de suficiencia" });
  const listo = page.getByRole("heading", { level: 1, name: "Paquete listo para revisión" });
  const parado = page.getByText("El coordinador se ha parado", { exact: true }).first();
  await expect(preguntas.or(listo).or(parado)).toBeVisible({ timeout: 5 * 60_000 });
  if (await preguntas.isVisible()) {
    await captura("2-seguimiento-preguntas");
    for (const fs of await page.locator("form fieldset").all()) {
      const campo = await fs.locator("input[type=radio]").first().getAttribute("name");
      await fs.locator(`input[value=${RESPUESTAS[campo ?? ""] ?? "a"}]`).check();
    }
    await page.getByRole("button", { name: "Enviar respuestas" }).click();
    await expect(page.getByText(/Verificando el lote|trabajando/)).toBeVisible({ timeout: 5 * 60_000 });
    await captura("2b-seguimiento-en-curso");
  }
  await expect(listo.or(parado)).toBeVisible({ timeout: 15 * 60_000 });
  await expect(page.getByText("Mensaje para el revisor").or(parado)).toBeVisible({ timeout: 60_000 });
  await captura("3-resultado");
  await expect(listo).toBeVisible();
});
