# Entrega — Pruebas Automáticas de Interfaz Gráfica (UI / E2E)

**Curso:** Testing
**Proyecto:** TicketResolve — Sistema de Tickets e Incidentes
**Herramienta:** [Playwright](https://playwright.dev/) (Chromium)
**Cantidad de escenarios:** 10 pruebas automáticas de interfaz gráfica

---

## 1. Resumen

Esta entrega implementa **10 escenarios de pruebas automáticas de interfaz
gráfica (end-to-end)** sobre la aplicación web TicketResolve, usando
**Playwright**. Las pruebas manejan un navegador real (Chromium), interactúan
con la UID como lo haría un usuario (clics, escritura, navegación) y verifican
el resultado visible en pantalla.

La aplicación bajo prueba es un SPA en **React + Vite** con tres rutas:

| Ruta            | Pantalla        | Función |
|-----------------|-----------------|---------|
| `/nuevo`        | Nuevo Ticket    | Compositor para emitir incidentes. |
| `/dashboard`    | Dashboard       | Cola de incidentes con filtros y SLA en vivo. |
| `/ticket/:id`   | Detalle/Consola | Cronología, comentarios y acciones (ACK, escalar, resolver, reasignar). |

> 📁 **El código ejecutable de las pruebas vive en:**
> [`Dev/frontend/e2e/`](../Dev/frontend/e2e/)
> (debe permanecer ahí porque depende del `node_modules`, del
> `playwright.config.ts` y del proxy de Vite del frontend).

---

## 2. Los 10 escenarios

| #  | Archivo | Pantalla | Qué valida |
|----|---------|----------|------------|
| 1  | `01-navegacion.spec.ts` | Global | Redirección `/` → `/nuevo`, barra de navegación, enlaces Nuevo/Dashboard, indicador "Sistema operativo". |
| 2  | `02-crear-ticket-exitoso.spec.ts` | Nuevo Ticket | **Happy path**: formulario completo → pantalla de éxito con ID (`TKT-…`), estado OPEN, SLA y acciones de cierre. |
| 3  | `03-crear-ticket-validacion.spec.ts` | Nuevo Ticket | **Prueba negativa**: la validación de campos requeridos (título y descripción) bloquea el envío. |
| 4  | `04-vista-previa-sla.spec.ts` | Nuevo Ticket | Vista previa en vivo: título, badge de severidad y ventana de SLA (24 h → 15 min) + medidor de completitud. |
| 5  | `05-dashboard-carga.spec.ts` | Dashboard | Carga de datos sembrados y coherencia de tarjetas de resumen (P0+P1+P2 = total = nº de filas). |
| 6  | `06-dashboard-filtro-severidad.spec.ts` | Dashboard | Filtro por severidad desde las tarjetas (P1), pill "filtrado" y restauración al quitar el filtro. |
| 7  | `07-dashboard-filtro-estado.spec.ts` | Dashboard | Control segmentado OPEN/RESOLVED/ESCALATED: cada estado muestra sólo sus tickets. |
| 8  | `08-dashboard-filtro-ingeniero.spec.ts` | Dashboard | Filtro por ingeniero (con debounce), **persistencia en `localStorage`** tras recargar y **estado vacío**. |
| 9  | `09-detalle-ticket.spec.ts` | Detalle | Apertura del ticket desde el dashboard y consola completa (cabecera, cronología, detalles, acciones). |
| 10 | `10-flujo-completo-consola.spec.ts` | End-to-end | **Ciclo de vida completo**: crear → comentar → reconocer (ACK) → resolver → SLA congelado. |

### Cobertura por dimensión

- **Páginas:** las 3 rutas de la aplicación.
- **Camino feliz:** creación, navegación y acciones de consola (1, 2, 9, 10).
- **Pruebas negativas / casos borde:** validaciones (3) y estado vacío (8).
- **Estado y reactividad:** vista previa en vivo (4), filtros y persistencia (6, 7, 8).
- **End-to-end real:** ciclo de vida completo del incidente (10).

---

## 3. Cómo ejecutarlas (clonada limpia)

> Requisitos: **Node.js 18+** y **Python 3.11+**.

Playwright **levanta automáticamente** los dos servidores que la app necesita
(backend FastAPI en `:8000` y frontend Vite en `:5173`); no hay que arrancarlos
a mano.

### Paso 1 — Dependencias del backend (una sola vez)

```bash
cd Dev
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

### Paso 2 — Dependencias del frontend + navegador (una sola vez)

```bash
cd Dev/frontend
npm install
npx playwright install chromium
```

### Paso 3 — Correr las 10 pruebas

```bash
cd Dev/frontend
npm run test:e2e          # ejecuta los 10 escenarios (headless)
```

Scripts auxiliares:

```bash
npm run test:e2e:ui       # runner interactivo de Playwright
npm run test:e2e:report   # abre el reporte HTML de la última corrida
```

### Resultado esperado

```
  10 passed
```

---

## 4. Decisiones de diseño de las pruebas

- **IDs dinámicos:** el backend genera IDs aleatorios (`TKT-XXXXXXXX`) en cada
  arranque; las pruebas los **leen del DOM**, nunca los hardcodean.
- **Sin cantidades fijas frágiles:** se valida *coherencia* (p. ej.
  P0+P1+P2 = total = filas) en lugar de números exactos, porque varios
  escenarios crean tickets durante la corrida.
- **Esperas correctas:** se respeta el *debounce* de los filtros y el *refresh*
  asíncrono de las tablas para evitar condiciones de carrera (clic sobre filas
  obsoletas).
- **Ejecución en serie** (`workers: 1`): el backend de desarrollo comparte
  estado en memoria (moto), así las pruebas que mutan datos no se interfieren.

---

## 5. Backend de pruebas

El frontend habla con un servidor de desarrollo (FastAPI) que envuelve la misma
lógica de la Lambda real, con **AWS simulado en memoria mediante `moto`**
(DynamoDB + S3). Al arrancar **siembra ~7 tickets demo**, por lo que las
pruebas parten de un estado poblado pero efímero (no requiere AWS ni costos).

Configuración Playwright: [`Dev/frontend/playwright.config.ts`](../Dev/frontend/playwright.config.ts)
