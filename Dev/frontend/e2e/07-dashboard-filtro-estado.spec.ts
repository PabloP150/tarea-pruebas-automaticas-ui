import { test, expect } from "@playwright/test";

/**
 * Escenario 7 — Filtro por estado (control segmentado OPEN/ACK/ESCALATED/RESOLVED).
 *
 * Cambiar de estado debe recargar la tabla con sólo tickets de ese estado.
 * Verifica OPEN → RESOLVED → ESCALATED comprobando que TODAS las filas
 * muestran el chip de estado correspondiente.
 */
test.describe("Escenario 7 · Dashboard — filtro por estado", () => {
  test("cada estado muestra únicamente sus tickets", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.locator("tr.row-clickable").first()).toBeVisible();

    const filas = page.locator("tr.row-clickable");

    async function todasLasFilasTienenEstado(estado: string) {
      const chips = page.locator("tr.row-clickable .status-chip");
      // Espera a que la tabla termine de recargar con el nuevo estado antes de
      // tomar el snapshot (React reemplaza todas las filas de una sola vez).
      await expect(chips.first()).toHaveText(estado);
      const textos = await chips.allTextContents();
      expect(textos.length).toBeGreaterThan(0);
      for (const t of textos) {
        expect(t.trim()).toBe(estado);
      }
    }

    // Estado por defecto: OPEN
    await todasLasFilasTienenEstado("OPEN");

    // Cambiar a RESOLVED — el ticket resuelto sembrado debe aparecer
    await page.getByRole("radio", { name: "RESOLVED", exact: true }).click();
    await expect(filas.first()).toBeVisible();
    await todasLasFilasTienenEstado("RESOLVED");

    // Cambiar a ESCALATED — el ticket escalado sembrado debe aparecer
    await page.getByRole("radio", { name: "ESCALATED", exact: true }).click();
    await expect(filas.first()).toBeVisible();
    await todasLasFilasTienenEstado("ESCALATED");
  });
});
