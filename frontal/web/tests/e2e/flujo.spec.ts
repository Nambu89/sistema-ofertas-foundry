import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";
import path from "node:path";

const TRANSCRIPCION = path.resolve(import.meta.dirname, "../../../../datos_prueba/transcripcion_sintetica_I18_hostelia.txt");
const EVIDENCIAS = path.resolve(import.meta.dirname, "../../../evidencias");

async function sinViolacionesGraves(page: Page) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  const graves = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(graves.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
}

test("alta, preguntas, seguimiento y paquete con turnos reales guardados", async ({ page }, info) => {
  const captura = (n: string) => page.screenshot({ path: `${EVIDENCIAS}/${n}-${info.project.name}.png`, fullPage: true });

  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Nueva solicitud de preventa" })).toBeVisible();
  await expect(page.getByText("Modo reproducción")).toBeVisible();
  await expect(page.getByRole("radio", { name: /AWS/ })).toBeDisabled();
  await expect(page.getByRole("radio", { name: /Google Cloud/ })).toBeDisabled();
  await expect(page.getByRole("radio", { name: /Microsoft/ })).toBeChecked();
  await sinViolacionesGraves(page);
  await captura("1-nueva-solicitud");

  await page.getByLabel("Cliente (ficticio)").fill("Hostelia Grupo Hotelero, S.A.");
  await page.getByLabel("Código de cliente").fill("hostelia");
  await page.getByLabel("Título").fill("Asistente de RR. HH. en Teams");
  await page.getByLabel("Términos sensibles").fill("Hostelia; Marina Couto; Rodrigo Valcárcel");
  await page.getByLabel("Explicación (opcional)").fill("Asistente para 1.200 empleados de España y Portugal.");
  await page.locator("#transcripcion").setInputFiles(TRANSCRIPCION);
  await page.getByLabel(/Confirmo que el NDA/).check();
  await page.getByRole("button", { name: "Registrar solicitud" }).click();

  await expect(page.getByRole("heading", { name: "Preguntas de suficiencia" })).toBeVisible();
  await expect(page.locator("li[aria-current=step]")).toContainText("Suficiencia de la información");
  await sinViolacionesGraves(page);
  await captura("2-seguimiento-preguntas");

  await page.getByRole("radio", { name: "No, acceso público con autenticación" }).check();
  await page.getByRole("radio", { name: "Enterprise Agreement o MCA-E directo" }).check();
  await page.getByRole("radio", { name: "Entre 25.000 y 60.000 euros" }).check();
  await page.getByRole("button", { name: "Enviar respuestas" }).click();
  await expect(page.getByText(/Verificando el lote \d de 6/)).toBeVisible();
  await captura("2b-seguimiento-verificacion");

  await expect(page.getByRole("heading", { level: 1, name: "Paquete listo para revisión" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("OF-HOSTELIA-001-A", { exact: true })).toBeVisible();
  await expect(page.getByText("Hola, responsable de preventa")).toBeVisible();
  await sinViolacionesGraves(page);
  await captura("3-resultado");

  const descarga = page.waitForEvent("download");
  await page.getByRole("link", { name: /Descargar OF-HOSTELIA-001-A-Paquete.zip/ }).click();
  expect((await descarga).suggestedFilename()).toBe("OF-HOSTELIA-001-A-Paquete.zip");
});

test("si falla la descarga del ZIP, se ofrece reintentarla", async ({ page }) => {
  const id = "d".repeat(32);
  let descargado = false;
  const solicitud = () => ({
    id, pilar: "microsoft", titulo: "Prueba de descarga", ocupado: false, estado: "LISTA_PARA_REVISION", fase_max: 5,
    fases: ["BORRADOR", "INFORMACION_INSUFICIENTE", "EN_ANALISIS", "EN_VERIFICACION", "VERIFICADA", "LISTA_PARA_REVISION"],
    siguiente: "", lote: null, preguntas: [], economia: {}, turnos: [],
    error: descargado ? null : "No se ha podido descargar el paquete: HTTP -1. Pulsa «Reintentar descarga».",
    paquete: { nombre: "OF-PRUEBA-001-A-Paquete.zip", bytes: 1, sha256: "0".repeat(64), descargado },
  });
  await page.route(`**/api/solicitudes/${id}`, (r) => r.fulfill({ json: solicitud() }));
  await page.route(`**/api/solicitudes/${id}/descargar`, (r) => { descargado = true; return r.fulfill({ json: solicitud() }); });
  await page.route(`**/api/solicitudes/${id}/resumen`, (r) => r.fulfill({ json: {
    codigo: "OF-PRUEBA-001-A", estado: "LISTA_PARA_REVISION", hash_contenido: "h", ficheros: [], nota_revisor: "", economia: {} } }));
  await page.goto(`/?solicitud=${id}`);
  await expect(page.getByRole("alert")).toContainText("No se ha podido descargar el paquete");
  await expect(page.getByRole("button", { name: "Continuar" })).toHaveCount(0);
  await page.getByRole("button", { name: "Reintentar descarga" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Paquete listo para revisión" })).toBeVisible();
});
