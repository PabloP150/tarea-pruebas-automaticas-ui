import { test, expect } from "@playwright/test";

/**
 * Escenario 6 — Filtro por severidad desde las tarjetas de resumen.
 *
 * Al hacer clic en la tarjeta "P1 · Alto" la tabla debe filtrarse a sólo
 * tickets P1, marcar la tarjeta como activa y mostrar el pill "filtrado · P1".
 * Quitar el filtro restaura todas las filas.
 */
test.describe("Escenario 6 · Dashboard — filtro por severidad", () => {
  test("filtra la tabla por P1 y luego restaura todas las severidades", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.locator("tr.row-clickable").first()).toBeVisible();

    const parse = async (sel: string) =>
      parseInt((await page.locator(sel).first().textContent())?.trim() ?? "0", 10);
    const total = await parse(".stat-total .stat-card-value");
    const p1 = await parse(".stat-p1 .stat-card-value");
    expect(p1).toBeGreaterThan(0);

    // Activar el filtro P1
    const cardP1 = page.getByRole("button", { name: /P1 Alto/ });
    await cardP1.click();
    await expect(cardP1).toHaveAttribute("aria-pressed", "true");

    // La tabla queda con exactamente las filas P1
    const filas = page.locator("tr.row-clickable");
    await expect(filas).toHaveCount(p1);
    await expect(page.locator(".table-panel-filter-pill")).toContainText("P1");

    // Cada fila visible es realmente P1
    const badges = page.locator("tr.row-clickable .severity-badge");
    const n = await badges.count();
    for (let i = 0; i < n; i++) {
      await expect(badges.nth(i)).toHaveText("P1");
    }

    // Quitar el filtro restaura el total
    await cardP1.click();
    await expect(cardP1).toHaveAttribute("aria-pressed", "false");
    await expect(filas).toHaveCount(total);
  });
});
