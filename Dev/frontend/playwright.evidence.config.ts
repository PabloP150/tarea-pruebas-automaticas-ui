import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/**
 * Config de EVIDENCIA — idéntica a la normal pero captura una pantalla al
 * final de cada escenario (`screenshot: "on"`). Las imágenes se recopilan
 * luego en testing/evidencia/ con un script.
 *
 *   npx playwright test --config=playwright.evidence.config.ts
 */
export default defineConfig({
  ...base,
  use: {
    ...base.use,
    screenshot: "on",
    video: "off",
    trace: "off",
  },
  reporter: [["list"]],
});
