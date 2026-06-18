import { defineConfig, devices } from "@playwright/test";

/**
 * Configuración Playwright — TicketResolve (pruebas E2E de interfaz gráfica).
 *
 * Playwright levanta AUTOMÁTICAMENTE los dos servidores antes de correr:
 *   1. Backend dev (FastAPI + moto, datos sembrados)  → http://localhost:8000
 *   2. Frontend  (Vite/React)                          → http://localhost:5173
 *
 * El frontend habla con el backend vía el proxy `/api` de Vite, así que las
 * pruebas solo navegan a http://localhost:5173 (baseURL).
 *
 * Estado compartido: el backend usa moto en memoria y sólo siembra datos al
 * arrancar. Por eso corremos en serie (workers: 1) — así las pruebas que
 * mutan estado (resolver, comentar) no se pisan entre sí.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],

  use: {
    baseURL: "http://localhost:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    locale: "es-GT",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: [
    {
      // Backend dev: uvicorn desde el venv del proyecto, cwd = Dev/
      command: ".venv/bin/uvicorn devserver.main:app --port 8000 --log-level warning",
      cwd: "..",
      port: 8000,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      // Frontend Vite en puerto fijo
      command: "npm run dev -- --port 5173 --strictPort",
      port: 5173,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
