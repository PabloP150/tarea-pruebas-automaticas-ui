import { expect, type Page } from "@playwright/test";

/**
 * Utilidades compartidas por los escenarios E2E.
 */

export interface NuevoTicket {
  titulo: string;
  descripcion: string;
  severidad?: "P0" | "P1" | "P2";
  servicio?: "ERP" | "Pagos" | "Red" | "Impresoras" | "Correo";
  asignado?: string;
}

/**
 * Crea un ticket a través del formulario de UI (/nuevo) y devuelve el
 * ID generado por el backend que aparece en la pantalla de éxito.
 */
export async function crearTicket(page: Page, t: NuevoTicket): Promise<string> {
  await page.goto("/nuevo");

  await page.getByLabel("Título del incidente").fill(t.titulo);
  await page.getByLabel("Descripción del incidente").fill(t.descripcion);

  if (t.severidad) {
    await page.getByRole("radio", { name: new RegExp(`^${t.severidad}`) }).click();
  }
  if (t.servicio) {
    await page.getByRole("radio", { name: t.servicio, exact: true }).click();
  }
  if (t.asignado) {
    await page.getByPlaceholder("Nombre del ingeniero").fill(t.asignado);
  }

  await page.getByRole("button", { name: /Emitir Ticket Operativo/ }).click();

  // Pantalla de éxito → leer el ID emitido (TKT-XXXXXXXX)
  const idLocator = page.locator(".success-ticket-id");
  await expect(idLocator).toBeVisible();
  const id = (await idLocator.textContent())?.trim() ?? "";
  expect(id).toMatch(/^TKT-/);
  return id;
}

/**
 * Abre el dashboard filtrando por el ingeniero indicado y hace clic en la
 * primera fila de la tabla, navegando al detalle del ticket.
 */
export async function abrirTicketPorAsignado(page: Page, asignado: string): Promise<void> {
  await page.goto("/dashboard");
  await page.getByLabel("Ingeniero asignado").fill(asignado);

  // Espera a que el filtro (con debounce) se aplique: el panel cambia su título
  // a "Tickets de <asignado>" antes de que la fila correcta esté disponible.
  const panel = page.getByRole("region", { name: `Tickets de ${asignado}` });
  await expect(panel).toBeVisible();

  const primeraFila = panel.locator("tr.row-clickable").first();
  await expect(primeraFila).toBeVisible();
  await primeraFila.click();
  await expect(page).toHaveURL(/\/ticket\/TKT-/);
}
