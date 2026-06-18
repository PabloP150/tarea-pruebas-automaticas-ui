import { test, expect } from "@playwright/test";

/**
 * Escenario 3 — Validaciones de campos requeridos al crear un ticket.
 *
 * Prueba negativa: el formulario usa `noValidate`, así que la validación es
 * propia. Verifica que emitir sin título y luego sin descripción produce el
 * mensaje de error correcto y NO navega a la pantalla de éxito.
 */
test.describe("Escenario 3 · Crear ticket — validaciones", () => {
  test("bloquea el envío y muestra errores cuando faltan campos requeridos", async ({ page }) => {
    await page.goto("/nuevo");

    // 1) Emitir vacío → error de título
    await page.getByRole("button", { name: /Emitir Ticket Operativo/ }).click();
    const alerta = page.getByRole("alert");
    await expect(alerta).toContainText("El título del incidente es requerido");

    // No debe haber pantalla de éxito
    await expect(page.getByRole("heading", { name: "Ticket emitido correctamente" })).toHaveCount(0);

    // 2) Con título pero sin descripción → error de descripción
    await page.getByLabel("Título del incidente").fill("Incidente de prueba sin descripción");
    await page.getByRole("button", { name: /Emitir Ticket Operativo/ }).click();
    await expect(alerta).toContainText("La descripción es requerida");

    // 3) Completar descripción → ya emite correctamente
    await page.getByLabel("Descripción del incidente").fill("Descripción válida para superar la validación.");
    await page.getByRole("button", { name: /Emitir Ticket Operativo/ }).click();
    await expect(page.getByRole("heading", { name: "Ticket emitido correctamente" })).toBeVisible();
  });
});
