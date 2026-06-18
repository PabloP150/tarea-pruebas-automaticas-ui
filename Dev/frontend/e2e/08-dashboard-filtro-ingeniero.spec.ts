import { test, expect } from "@playwright/test";

/**
 * Escenario 8 — Filtro por ingeniero asignado, persistencia y estado vacío.
 *
 * Escribir un nombre filtra la cola de ese ingeniero (con debounce). El filtro
 * se persiste en localStorage: al recargar, el nombre y el filtro se mantienen.
 * Un ingeniero inexistente muestra el estado vacío "Sin tickets pendientes".
 */
test.describe("Escenario 8 · Dashboard — filtro por ingeniero", () => {
  test("filtra la cola de 'ana', persiste tras recargar y muestra vacío si no existe", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.locator("tr.row-clickable").first()).toBeVisible();

    // Filtrar por el ingeniero sembrado 'ana'
    await page.getByLabel("Ingeniero asignado").fill("ana");

    // El panel cambia a la vista de la cola de ana (espera el debounce + fetch)
    const panel = page.getByRole("region", { name: "Tickets de ana" });
    await expect(panel).toBeVisible();

    // Todas las filas pertenecen a 'ana'
    const asignados = page.locator("tr.row-clickable .assignee-name");
    const n = await asignados.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < n; i++) {
      await expect(asignados.nth(i)).toHaveText("ana");
    }

    // Persistencia: al recargar, el nombre sigue en el input
    await page.reload();
    await expect(page.getByLabel("Ingeniero asignado")).toHaveValue("ana");
    await expect(page.getByRole("region", { name: "Tickets de ana" })).toBeVisible();

    // Ingeniero inexistente → estado vacío
    await page.getByLabel("Ingeniero asignado").fill("zzz-ingeniero-inexistente");
    await expect(page.getByText("Sin tickets pendientes")).toBeVisible();
  });
});
