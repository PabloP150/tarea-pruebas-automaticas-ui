import { test, expect } from "@playwright/test";

/**
 * Escenario 1 — Navegación principal y redirección de la raíz.
 *
 * Verifica el "esqueleto" de la app: la barra de navegación, el indicador de
 * sistema operativo, la redirección de `/` hacia `/nuevo`, y que los enlaces
 * Nuevo Ticket / Dashboard cambian de ruta correctamente.
 */
test.describe("Escenario 1 · Navegación principal", () => {
  test("la raíz redirige a /nuevo y la barra de navegación funciona", async ({ page }) => {
    // La raíz redirige al compositor de tickets
    await page.goto("/");
    await expect(page).toHaveURL(/\/nuevo$/);

    // Marca y estado del sistema visibles en la nav
    await expect(page.getByRole("navigation")).toBeVisible();
    await expect(page.getByText("TicketResolve")).toBeVisible();
    await expect(page.getByText("Sistema operativo")).toBeVisible();

    // El compositor está presente
    await expect(page.getByRole("heading", { name: /Cuéntanos qué pasó/ })).toBeVisible();

    // Navegar al Dashboard
    await page.getByRole("link", { name: "Dashboard" }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Dashboard del Ingeniero" })).toBeVisible();

    // Volver a Nuevo Ticket
    await page.getByRole("link", { name: "Nuevo Ticket" }).click();
    await expect(page).toHaveURL(/\/nuevo$/);
    await expect(page.getByLabel("Título del incidente")).toBeVisible();
  });
});
