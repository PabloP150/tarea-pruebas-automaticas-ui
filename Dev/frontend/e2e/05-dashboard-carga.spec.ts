import { test, expect } from "@playwright/test";

/**
 * Escenario 5 — Carga del dashboard: datos sembrados y tarjetas de resumen.
 *
 * El backend dev siembra varios tickets al arrancar. Verifica que el dashboard
 * los carga, que las tarjetas de resumen muestran valores numéricos y que la
 * suma por severidad (P0+P1+P2) es coherente con el total y con las filas.
 *
 * No se afirman cantidades exactas a propósito: otros escenarios crean tickets
 * antes que éste, así que la prueba valida coherencia, no números fijos.
 */
test.describe("Escenario 5 · Dashboard — carga de datos", () => {
  test("muestra tickets sembrados y tarjetas de resumen coherentes", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(page.getByRole("heading", { name: "Dashboard del Ingeniero" })).toBeVisible();

    // Espera a que la tabla esté presente (no skeleton)
    const filas = page.locator("tr.row-clickable");
    await expect(filas.first()).toBeVisible();

    const parse = async (sel: string) =>
      parseInt((await page.locator(sel).first().textContent())?.trim() ?? "0", 10);

    const total = await parse(".stat-total .stat-card-value");
    const p0 = await parse(".stat-p0 .stat-card-value");
    const p1 = await parse(".stat-p1 .stat-card-value");
    const p2 = await parse(".stat-p2 .stat-card-value");

    // Hay datos
    expect(total).toBeGreaterThan(0);

    // Coherencia: las severidades suman el total
    expect(p0 + p1 + p2).toBe(total);

    // La tabla (vista OPEN, sin filtro) tiene tantas filas como el total
    await expect(filas).toHaveCount(total);
  });
});
