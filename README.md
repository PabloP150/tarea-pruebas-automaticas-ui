# Tarea — Pruebas Automáticas de Interfaz Gráfica (UI / E2E)

**Curso:** Testing · **Proyecto:** TicketResolve — Sistema de Tickets e Incidentes
**Herramienta:** [Playwright](https://playwright.dev/) (Chromium) · **Escenarios:** 10

Esta tarea implementa **10 escenarios de pruebas automáticas de interfaz
gráfica (end-to-end)** sobre la aplicación web TicketResolve. Las pruebas
manejan un navegador real e interactúan con la UI como un usuario (clics,
escritura, navegación), verificando lo que aparece en pantalla.

## 📂 Dónde está cada cosa

| Carpeta / archivo | Contenido |
|-------------------|-----------|
| [`testing/Pruebas-UI-Automatizadas.md`](testing/Pruebas-UI-Automatizadas.md) | **Documento de la entrega** (descripción de los 10 escenarios y cómo correr). |
| [`testing/evidencia/`](testing/evidencia/) | **Evidencia visual**: 1 captura por escenario + índice. |
| [`Dev/frontend/e2e/`](Dev/frontend/e2e/) | **Código de las 10 pruebas** (`*.spec.ts`) + helpers. |
| [`Dev/frontend/playwright.config.ts`](Dev/frontend/playwright.config.ts) | Configuración Playwright (levanta los servidores solo). |
| `Dev/` | Aplicación bajo prueba (frontend React/Vite + backend de desarrollo). |

## ▶️ Cómo ejecutar las pruebas

> Requisitos: **Node.js 18+** y **Python 3.11+**.

```bash
# 1) Backend (una vez)
cd Dev
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

# 2) Frontend + navegador (una vez)
cd frontend
npm install
npx playwright install chromium

# 3) Correr los 10 escenarios
npm run test:e2e
```

Resultado esperado:

```
10 passed
```

Playwright **levanta automáticamente** el backend (`:8000`) y el frontend
(`:5173`) antes de correr; no hay que arrancarlos a mano.

## 🧪 Los 10 escenarios

1. Navegación principal y redirección de la raíz
2. Crear ticket — happy path (pantalla de éxito con ID y SLA)
3. Crear ticket — validaciones de campos requeridos (prueba negativa)
4. Vista previa en vivo + proyección de SLA
5. Dashboard — carga de datos y tarjetas de resumen
6. Dashboard — filtro por severidad
7. Dashboard — filtro por estado
8. Dashboard — filtro por ingeniero + persistencia + estado vacío
9. Detalle del ticket — consola completa
10. Flujo E2E completo — crear → comentar → ACK → resolver

Detalle completo en [`testing/Pruebas-UI-Automatizadas.md`](testing/Pruebas-UI-Automatizadas.md).
