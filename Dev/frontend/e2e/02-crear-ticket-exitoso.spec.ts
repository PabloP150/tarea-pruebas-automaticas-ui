import { test, expect } from "@playwright/test";

/**
 * Escenario 2 — Creación de ticket exitosa (happy path).
 *
 * Llena el formulario completo, emite el ticket y valida la pantalla de éxito:
 * ID generado (TKT-…), estado inicial OPEN, fecha de SLA y acciones de cierre.
 */
test.describe("Escenario 2 · Crear ticket — happy path", () => {
  test("emite un ticket P0 y muestra la confirmación con ID y SLA", async ({ page }) => {
    await page.goto("/nuevo");

    await page.getByLabel("Título del incidente").fill("Caída total del servicio de Pagos en producción");
    await page
      .getByLabel("Descripción del incidente")
      .fill("La pasarela devuelve 503 desde las 02:14 UTC. Transacciones fallando al 100%.");

    // Severidad P0 (crítico)
    await page.getByRole("radio", { name: /^P0/ }).click();
    // Servicio afectado
    await page.getByRole("radio", { name: "Pagos", exact: true }).click();
    // Asignado (opcional)
    await page.getByPlaceholder("Nombre del ingeniero").fill("Ana López");

    await page.getByRole("button", { name: /Emitir Ticket Operativo/ }).click();

    // ── Pantalla de éxito ──
    await expect(page.getByRole("heading", { name: "Ticket emitido correctamente" })).toBeVisible();

    const id = await page.locator(".success-ticket-id").textContent();
    expect(id?.trim()).toMatch(/^TKT-[0-9A-F]+$/i);

    // Estado inicial OPEN y un SLA con formato de fecha
    await expect(page.getByText("OPEN")).toBeVisible();
    await expect(page.getByText("SLA límite")).toBeVisible();

    // Acciones de cierre
    await expect(page.getByRole("button", { name: "Emitir otro ticket" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Ver en Dashboard" })).toBeVisible();
  });
});
