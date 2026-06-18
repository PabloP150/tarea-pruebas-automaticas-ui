import { test, expect } from "@playwright/test";
import { crearTicket, abrirTicketPorAsignado } from "./helpers";

/**
 * Escenario 10 — Flujo E2E completo de la consola de incidente.
 *
 * Recorre el ciclo de vida real de un ticket a través de la interfaz:
 *   crear → abrir → comentar → reconocer (ACK) → resolver.
 * Valida que cada acción se refleja en la UI (comentario en la cronología,
 * cambios de estado y congelamiento del SLA al resolver).
 */
test.describe("Escenario 10 · Flujo completo de la consola", () => {
  test("crea, comenta, reconoce y resuelve un ticket de extremo a extremo", async ({ page }) => {
    const sufijo = Date.now();
    await crearTicket(page, {
      titulo: `Flujo E2E ${sufijo}`,
      descripcion: "Ticket para recorrer comentario, ACK y resolución.",
      severidad: "P1",
      servicio: "ERP",
      asignado: "qa-flujo",
    });

    await abrirTicketPorAsignado(page, "qa-flujo");
    await expect(page.locator(".ticket-detail-header .status-chip")).toHaveText("OPEN");

    // ── 1) Agregar un comentario ──
    const comentario = `Diagnóstico inicial en curso ${sufijo}`;
    await page.getByLabel("Tu nombre", { exact: true }).fill("QA Bot");
    await page.getByLabel("Comentario", { exact: true }).fill(comentario);
    await page.getByRole("button", { name: "Publicar comentario" }).click();

    await expect(page.getByText("Comentario publicado.")).toBeVisible();
    await expect(page.getByText(comentario)).toBeVisible();

    // ── 2) Reconocer (ACK) ──
    await page.getByRole("button", { name: /Reconocer \(ACK\)/ }).click();
    await expect(page.locator(".ticket-detail-header .status-chip")).toHaveText("ACK");

    // ── 3) Resolver el ticket ──
    await page.getByRole("button", { name: "Resolver ticket" }).click();
    await expect(page.locator(".ticket-detail-header .status-chip")).toHaveText("RESOLVED");

    // El SLA queda congelado y el botón de resolver muestra el estado final
    await expect(page.getByText("SLA congelado")).toBeVisible();
    await expect(page.getByRole("button", { name: /Ticket resuelto/ })).toBeDisabled();
  });
});
