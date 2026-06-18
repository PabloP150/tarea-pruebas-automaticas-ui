import { test, expect } from "@playwright/test";

/**
 * Escenario 4 — Vista previa en vivo y proyección de SLA.
 *
 * El compositor tiene una tercera columna que refleja en tiempo real lo que se
 * escribe. Verifica que el título, la severidad y la ventana de SLA se
 * actualizan al vuelo, y que el medidor de completitud sube al llenar campos.
 */
test.describe("Escenario 4 · Vista previa en vivo + SLA", () => {
  test("la vista previa refleja título, severidad y ventana de SLA al instante", async ({ page }) => {
    await page.goto("/nuevo");

    // Completitud inicial: solo servicio + severidad están preseleccionados → 40%
    await expect(page.locator(".composer-progress-pct")).toHaveText("40%");

    // Por defecto la severidad es P2 → ventana de SLA de 24 h
    await expect(page.locator(".preview-sla-window")).toHaveText("24 h");

    // Escribir el título se refleja en la tarjeta de vista previa
    await page.getByLabel("Título del incidente").fill("Servidor de Correo no recibe mensajes");
    await expect(page.locator(".preview-card-title")).toHaveText("Servidor de Correo no recibe mensajes");

    // Cambiar a severidad P0 actualiza el badge y la ventana de SLA a 15 min
    await page.getByRole("radio", { name: /^P0/ }).click();
    await expect(page.locator(".preview-card .severity-badge")).toContainText("P0");
    await expect(page.locator(".preview-sla-window")).toHaveText("15 min");

    // Llenar descripción y asignado lleva la completitud a 100%
    await page.getByLabel("Descripción del incidente").fill("Cola SMTP detenida; sin entrega desde hace 20 min.");
    await page.getByPlaceholder("Nombre del ingeniero").fill("Carlos");
    await expect(page.locator(".composer-progress-pct")).toHaveText("100%");
  });
});
