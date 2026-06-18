# api-tickets — Backend slice for TicketResolve

This directory contains the **TicketResolve** app: the Python **api-tickets** backend slice
(US-01 create, US-02 webhook ingestion + dedup, US-03 dashboard, US-04/US-05 state-machine
transitions + comments, US-06 reassignment, plus attachment upload/download) that runs as an
AWS Lambda function (target runtime `python3.12`), plus a **React frontend** and a **local dev
server** that wire the whole flow end-to-end on your machine. The frontend is documented in
detail in [FRONTEND.md](FRONTEND.md).

> **Packaging for deployment** (not done here): the Lambda zip must include `lambda_function.py` at the root plus the `shared/` package. Wiring the Terraform compute module to build from this source is a later IaC task.

---

## Qué cambió (2026-06-10)

Resumen de las features incorporadas desde la última versión de este README — el detalle
completo del contrato vive en [ARCHITECTURE.md](ARCHITECTURE.md):

- **Webhook de alertas + deduplicación (US-02):** `POST /api/v1/webhooks/alerts`, dedup
  determinista por hash con un puntero race-free (`DEDUP#<hash>/ACTIVE`).
- **Máquina de estados (US-04/US-05):** `PATCH /api/v1/incidents/{id}` ahora soporta
  `ACK`/`ESCALATED`/`RESOLVED` con optimistic locking, no solo "resolver".
- **Dashboard "todos los pendientes":** `GET /api/v1/incidents` sin `assignee` devuelve todos
  los tickets del estado solicitado (antes requería `assignee`).
- **Reasignación (US-06):** nueva ruta `PATCH /api/v1/incidents/{id}/assignee`.
- **Descarga de adjuntos:** `GET /api/v1/incidents/{id}` devuelve `download_url` (presigned GET,
  5 min) por adjunto; ya no expone `s3_key`.
- **Frontend M3 — TicketDetail (`/ticket/:id`):** consola del ticket con cronología, comentarios,
  acciones de la máquina de estados y reasignación (ver [FRONTEND.md](FRONTEND.md)).
- **Dev server:** siembra **7 tickets demo** al arrancar (`SEED_DEMO`, default `1`).
- **Calidad:** Scan paginado del dashboard global con topes de seguridad, puntero determinista
  de dedup, `dedup_hash` oculto en las respuestas, sanitización del campo `source` del webhook.
- **Tests:** backend 82 → **160**; frontend 41 → **85** (suma de la suite `TicketDetail.test.tsx`).

---

## Project layout

```
Dev/
  ARCHITECTURE.md           # backend contract + decisiones (§9: estado de consolidación)
  FRONTEND.md               # estado real del frontend (tema Nexus, M1/M2/M3, componentes)
  README.md                 # este archivo: cómo correr y probar
  requirements.txt          # runtime: boto3>=1.34
  requirements-dev.txt      # pytest + pytest-cov + moto[dynamodb,s3] + fastapi + uvicorn
  pytest.ini                # testpaths=tests, pythonpath=src
  src/
    shared/                 # keys, ids, models, ddb, s3, http (single-table + helpers)
    api_tickets/
      lambda_function.py    # lambda_handler: router by method + path (7 rutas)
      service.py            # create / list_dashboard / get_ticket / add_comment /
                             # update_status / reassign_ticket / ingest_alert
  tests/                    # pytest + moto — 160 tests (sin credenciales AWS)
    conftest.py  test_create_ticket.py  test_get_ticket.py  test_dashboard.py
    test_comment_resolve.py  test_status_transitions.py  test_reassign.py
    test_webhook_ingesta.py  test_attachment_download.py
    test_handler_routing.py  test_shared.py
  devserver/
    main.py                 # FastAPI: envuelve el lambda_handler con moto in-process (:8000)
                             # + seed demo de 7 tickets (SEED_DEMO=1 por default)
  frontend/                 # React + Vite + TS (ver FRONTEND.md) — Vitest, 85 tests
    src/ ...                # pages/ (M1 Composer, M2 Dashboard, M3 TicketDetail),
                             # components/, providers/, hooks/, api/
```

---

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate    # macOS/Linux
# .venv\Scripts\activate     # Windows
```

> The code is tested with Python 3.13. The Lambda target runtime is python3.12; both are fully compatible.

### 2. Install dependencies

```bash
pip install -r requirements-dev.txt
```

---

## Run tests

```bash
pytest
```

All tests run locally using **moto** to mock DynamoDB and S3. No real AWS credentials are required.

To see verbose output:

```bash
pytest -v
```

Expected result: **160 passed**.

---

## HTTP API

| Method | Path | Action | Status |
|--------|------|--------|--------|
| `POST` | `/api/v1/webhooks/alerts` | Ingest monitoring alert (US-02, dedup) | 201 (new) / 200 (deduplicated) |
| `POST` | `/api/v1/incidents` | Create ticket | 201 |
| `GET` | `/api/v1/incidents?assignee=<e>&status=OPEN` | Dashboard — `assignee` empty ⇒ all pending tickets in that status | 200 |
| `GET` | `/api/v1/incidents/{id}` | Full ticket detail (incl. `download_url` per attachment) | 200 / 404 |
| `POST` | `/api/v1/incidents/{id}/comments` | Add comment | 201 |
| `PATCH` | `/api/v1/incidents/{id}` | State-machine transition (ACK/ESCALATED/RESOLVED) | 200 / 400 / 409 |
| `PATCH` | `/api/v1/incidents/{id}/assignee` | Reassign ticket (US-06) | 200 / 400 / 409 |

Full request/response payloads, the state-machine diagram and the dedup design are documented in
[ARCHITECTURE.md §6](ARCHITECTURE.md#6-contrato-http-http-api-v2--payload-format-20).

Environment variables required at runtime:

| Variable | Description |
|----------|-------------|
| `TABLE_NAME` | DynamoDB table name (e.g. `ticketresolve-dev`) |
| `ATTACHMENTS_BUCKET` | S3 bucket for attachment presigned URLs (upload + download) |
| `LOG_LEVEL` | Logging level (default `INFO`) |
| `SEED_DEMO` | Dev server only: seed 7 demo tickets at startup. `1` (default) seeds, `0` disables |

---

## Cómo correr la app (frontend + dev server)

### 1. Dev server (FastAPI + moto in-process)

```bash
# Desde Dev/, con el venv activo:
source .venv/bin/activate
uvicorn devserver.main:app --reload --port 8000
```

El servidor arranca en `http://localhost:8000`. DynamoDB y S3 son mocks en memoria (moto); los datos se pierden al reiniciar.

Al arrancar, el servidor **siembra 7 tickets de demostración** (variedad de severidades, estados
OPEN/ACK/ESCALATED/RESOLVED, un ticket creado vía webhook con `occurrence_count=3`, y uno
reasignado) para que el dashboard y la consola del ticket no arranquen vacíos. Para deshabilitar
el seed:

```bash
SEED_DEMO=0 uvicorn devserver.main:app --reload --port 8000
```

Verificar que está vivo:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### 2. Frontend (Vite + React)

```bash
# Desde Dev/frontend/:
npm install
npm run dev
```

El frontend arranca en `http://localhost:5173`. El proxy de Vite redirige todas las llamadas `/api` → `http://localhost:8000`, por lo que ambos procesos deben correr simultáneamente.

### 3. Flujo completo

1. Abrir `http://localhost:5173` (redirige automáticamente a `/nuevo`). Si el seed demo está
   activo (default), el dashboard y la consola del ticket ya tendrán datos de ejemplo desde el
   primer arranque.
2. Crear un ticket en **M1 — "Ticket Composer"** (`/nuevo`): un espacio de tres columnas a
   pantalla completa (sin scroll en desktop) donde se elige la **severidad** mediante tarjetas
   P0/P1/P2 (cada una muestra su SLA), el **servicio** mediante chips seleccionables, y se
   completan título, descripción y asignado con **contadores de caracteres en vivo** y un
   **avatar de iniciales** derivado del nombre del asignado. Incluye una zona de **adjunto por
   drag & drop**, un **medidor de completitud** (barra 0–100% sobre 5 señales del formulario) y
   el atajo de teclado **Cmd/Ctrl+Enter** para emitir el ticket. A la derecha, una **vista previa
   en vivo** refleja en tiempo real el badge de severidad, el título, el servicio, el avatar del
   asignado y el **deadline de SLA proyectado en cliente** (calculado localmente, sin consultar al
   backend). Al enviar, la pantalla de éxito muestra el `ticket_id` generado.
3. Ir a **M2 — Dashboard** (`/dashboard`): dejar la barra de búsqueda **vacía** para ver
   **"Todos los pendientes"** (todos los tickets en el estado seleccionado, sin filtrar por
   ingeniero), o ingresar un nombre de asignado (p. ej. el usado en el paso 2, o uno de los del
   seed: `ana`, `carlos`, `maria`) para ver solo sus tickets. El dashboard ofrece un **control de
   estado segmentado**, **stat-cards** (total y por severidad) con **filtro por severidad
   clicable** (aplicar/quitar al hacer clic), y una **píldora de "SLA vencido"** que se activa
   cuando hay tickets con `sla_deadline` ya pasado. La tabla es **"urgencia-aware"**: cada fila
   recibe un acento por severidad y, según corresponda, una clase de fila *at-risk* (< 15 min
   restantes) o *breached* (SLA vencido), con una **cuenta regresiva de SLA en vivo** por fila. El
   dashboard hace **polling cada 30 segundos** para mantener los datos actualizados. Cada fila es
   clicable.
4. Hacer clic en una fila para ir a **M3 — Consola del ticket** (`/ticket/:id`): muestra la
   cabecera del incidente (severidad, estado, SLA, badge de "×N ocurrencias" si el ticket viene de
   un webhook con alertas duplicadas), un **composer de comentario**, una **cronología** única
   (cronológica ascendente, mezcla eventos del sistema y comentarios) que se refresca tras cada
   acción, y un panel de **acciones**: **Reconocer (ACK)**, **Escalar**, **Resolver** (máquina de
   estados — un `409` por versión muestra un aviso y recarga los datos), **Reasignar** responsable,
   y **descargar** cada adjunto desde su `download_url`.

> **Nota sobre adjuntos en modo moto:** si se adjunta un archivo, la creación del ticket devuelve una `upload_url` (presigned PUT de S3 moto). El frontend intenta el `PUT` pero tolera el fallo silenciosamente; el ticket queda creado correctamente en cualquier caso.

> Inventario completo de componentes, providers, hooks y decisiones de UI/UX de M1, M2 y M3:
> [FRONTEND.md](FRONTEND.md).

---

## Pruebas y CI

### Backend (pytest + moto)

```bash
# Desde Dev/ con el venv activo:
. .venv/bin/activate
python -m pytest -q                                  # 160 tests
python -m pytest --cov=src --cov-report=term-missing # con cobertura
```

No requiere credenciales AWS: `moto` mockea DynamoDB y S3 en memoria.

### Frontend (Vitest + Testing Library)

```bash
# Desde Dev/frontend/:
npm test            # vitest run (85 tests)
npm run test:watch  # modo watch
npm run build       # tsc + vite build (debe pasar sin errores)
```

Suites: [src/api/client.test.ts](frontend/src/api/client.test.ts) (28),
[src/pages/CreateTicket.test.tsx](frontend/src/pages/CreateTicket.test.tsx) (15),
[src/pages/Dashboard.test.tsx](frontend/src/pages/Dashboard.test.tsx) (21) y
[src/pages/TicketDetail.test.tsx](frontend/src/pages/TicketDetail.test.tsx) (21). Detalle de
cobertura funcional de cada suite: [FRONTEND.md §7](FRONTEND.md).

### Integración continua

El workflow [`.github/workflows/dev-ci.yml`](../.github/workflows/dev-ci.yml) corre en push/PR a
`main` cuando cambian rutas de `Dev/**`:

- **Job backend:** instala `requirements-dev.txt` y corre `pytest` con cobertura, fallando si baja
  de **80%** de líneas en `src/`.
- **Job frontend:** `npm ci` → `npm run build` → `npm test`.

> El estado de consolidación, la postura de seguridad y las limitaciones conocidas (incluida la
> autenticación diferida a E5) están documentados en [ARCHITECTURE.md §9](ARCHITECTURE.md) y en
> [ADR 0001](docs/adr/0001-auth-deferred-to-e5.md).
