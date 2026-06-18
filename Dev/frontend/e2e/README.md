# Pruebas automáticas de interfaz gráfica (E2E) — TicketResolve

Suite de **10 escenarios de pruebas automáticas de interfaz gráfica** sobre la
aplicación TicketResolve, implementada con **Playwright** (Chromium).

## Cómo correrlas

Desde `Dev/frontend/`:

```bash
npm run test:e2e          # corre los 10 escenarios (headless)
npm run test:e2e:ui       # modo interactivo (UI runner de Playwright)
npm run test:e2e:report   # abre el reporte HTML de la última corrida
```

Playwright **levanta automáticamente** ambos servidores antes de correr
(ver `playwright.config.ts`):

| Servidor  | Comando                                              | Puerto |
|-----------|------------------------------------------------------|--------|
| Backend   | `.venv/bin/uvicorn devserver.main:app` (FastAPI+moto) | 8000   |
| Frontend  | `npm run dev` (Vite/React)                            | 5173   |

El backend dev usa **moto** (AWS en memoria) y **siembra datos demo** al
arrancar, así que las pruebas parten de un estado poblado pero efímero.

> Nota: los IDs de ticket (`TKT-XXXXXXXX`) son aleatorios en cada arranque, por
> lo que las pruebas los **leen del DOM** en vez de hardcodearlos. La suite
> corre en serie (`workers: 1`) porque el backend comparte estado en memoria.

## Los 10 escenarios

| # | Archivo | Página | Qué valida |
|---|---------|--------|------------|
| 1 | `01-navegacion.spec.ts` | Global | Redirección `/` → `/nuevo`, barra de navegación, enlaces Nuevo/Dashboard, indicador "Sistema operativo". |
| 2 | `02-crear-ticket-exitoso.spec.ts` | Nuevo Ticket | Happy path: formulario completo → pantalla de éxito con ID, estado OPEN, SLA y acciones de cierre. |
| 3 | `03-crear-ticket-validacion.spec.ts` | Nuevo Ticket | Prueba negativa: validación de campos requeridos (título y descripción) bloquea el envío. |
| 4 | `04-vista-previa-sla.spec.ts` | Nuevo Ticket | Vista previa en vivo: título, badge de severidad, ventana de SLA (24 h → 15 min) y medidor de completitud. |
| 5 | `05-dashboard-carga.spec.ts` | Dashboard | Carga de datos sembrados y coherencia de tarjetas de resumen (P0+P1+P2 = total = nº de filas). |
| 6 | `06-dashboard-filtro-severidad.spec.ts` | Dashboard | Filtro por severidad desde las stat cards (P1), pill "filtrado", y restauración al quitar el filtro. |
| 7 | `07-dashboard-filtro-estado.spec.ts` | Dashboard | Control segmentado OPEN/RESOLVED/ESCALATED: cada estado muestra sólo sus tickets. |
| 8 | `08-dashboard-filtro-ingeniero.spec.ts` | Dashboard | Filtro por ingeniero (con debounce), **persistencia en localStorage** tras recargar, y estado vacío. |
| 9 | `09-detalle-ticket.spec.ts` | Detalle | Apertura del ticket desde el dashboard y consola completa (cabecera, cronología, detalles, acciones). |
| 10 | `10-flujo-completo-consola.spec.ts` | E2E | Ciclo de vida completo: crear → comentar → reconocer (ACK) → resolver → SLA congelado. |

## Cobertura por dimensión

- **Páginas:** las 3 rutas de la app (`/nuevo`, `/dashboard`, `/ticket/:id`).
- **Flujos felices:** creación, navegación, acciones de consola (1, 2, 9, 10).
- **Pruebas negativas / bordes:** validaciones (3), estado vacío (8).
- **Estado y reactividad:** vista previa en vivo (4), filtros y persistencia (6, 7, 8).
- **End-to-end real:** flujo completo del ciclo de vida del incidente (10).

## Estructura

```
e2e/
├── README.md                            (este archivo)
├── helpers.ts                           (utilidades: crearTicket, abrirTicketPorAsignado)
├── 01-navegacion.spec.ts
├── 02-crear-ticket-exitoso.spec.ts
├── 03-crear-ticket-validacion.spec.ts
├── 04-vista-previa-sla.spec.ts
├── 05-dashboard-carga.spec.ts
├── 06-dashboard-filtro-severidad.spec.ts
├── 07-dashboard-filtro-estado.spec.ts
├── 08-dashboard-filtro-ingeniero.spec.ts
├── 09-detalle-ticket.spec.ts
└── 10-flujo-completo-consola.spec.ts
```
