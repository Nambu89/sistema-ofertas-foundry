import { defineConfig } from "@playwright/test";

const PUERTO = 8766;

export default defineConfig({
  testDir: "tests/e2e",
  workers: 1, // una sola solicitud activa en el BFF
  timeout: 90_000,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${PUERTO}`, locale: "es-ES" },
  projects: [
    { name: "movil", use: { viewport: { width: 375, height: 667 } } },
    { name: "tableta", use: { viewport: { width: 768, height: 1024 } } },
    { name: "escritorio", use: { viewport: { width: 1440, height: 900 } } },
  ],
  webServer: {
    command: `../.venv/bin/python ../bff/servidor.py --reproduccion --pausa 0.3 --puerto ${PUERTO}`,
    url: `http://127.0.0.1:${PUERTO}/api/salud`,
    reuseExistingServer: false,
  },
});
