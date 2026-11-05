import { defineConfig } from "@playwright/test";

// Prueba contra el coordinador REAL: arranca antes `python frontal/bff/servidor.py` (puerto 8765) con sesión az.
export default defineConfig({
  testDir: "tests/real",
  workers: 1,
  timeout: 20 * 60_000,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:8765", locale: "es-ES", viewport: { width: 1440, height: 900 } },
});
