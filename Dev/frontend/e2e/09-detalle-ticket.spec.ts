import { test, expect } from "@playwright/test";
import { crearTicket, abrirTicketPorAsignado } from "./helpers";

/**
 * Escenario 9 — Apertura del detalle de un ticket y contenido de la consola.
 *
 * Crea un ticket con un asignado único, lo abre desde el dashboard y valida la
 * consola de incidente: cabecera (ID, severidad, estado), cronología con el
 * evento "Ticket creado", panel de detalles (versión) y panel de acciones.
 */
test.describe("Escenario 9 · Detalle del ticket", () => {
  test("abre el ticket desde el dashboard y muestra la consola completa", async ({ page }) => {
    const titulo = `Detalle E2E ${Date.now()}`;
    await crearTicket(page, {
      titulo,
      descripcion: "Ticket creado para validar la consola de detalle.",
      severidad: "P1",
      servicio: "Red",
      asignado: "qa-detalle",
    });

    await abrirTicketPorAsignado(page, "qa-detalle");

    // Cabecera
    await expect(page.locator(".ticket-detail-id")).toHaveText(/^TKT-/);
    await expect(page.locator(".ticket-detail-title")).toHaveText(titulo);
    await expect(page.locator(".ticket-detail-header .severity-badge")).toContainText("P1");
    await expect(page.locator(".ticket-detail-header .status-chip")).toHaveText("OPEN");

    // Cronología con al menos el evento de creación
    await expect(page.getByRole("heading", { name: "Cronología" })).toBeVisible();
    await expect(page.getByText("Ticket creado", { exact: true })).toBeVisible();

    // Panel de detalles: versión inicial v1
    await expect(page.getByText("v1", { exact: true })).toBeVisible();

    // Panel de acciones disponible
    await expect(page.getByRole("heading", { name: "Acciones" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Resolver ticket" })).toBeVisible();
  });
});
