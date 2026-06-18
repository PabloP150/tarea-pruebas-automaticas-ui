"""
main.py — FastAPI dev server for TicketResolve.

Wraps the real api_tickets.lambda_handler behind HTTP so the React
frontend can talk to it locally.  DynamoDB and S3 are mocked in-process
with moto (mock_aws started at module load, kept alive for the process).

Run from Dev/:
    uvicorn devserver.main:app --reload --port 8000
"""
import os
import sys
import logging

# ---------------------------------------------------------------------------
# 1. Put src/ on sys.path BEFORE any application imports
# ---------------------------------------------------------------------------
_DEV_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_DEV_DIR, "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# ---------------------------------------------------------------------------
# 2. Fake AWS credentials so moto/boto3 don't complain about missing creds
# ---------------------------------------------------------------------------
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("LOG_LEVEL", "INFO")

# ---------------------------------------------------------------------------
# 3. Start moto mock_aws at module load (kept alive for the whole process)
# ---------------------------------------------------------------------------
from moto import mock_aws  # noqa: E402

_mock = mock_aws()
_mock.start()

# ---------------------------------------------------------------------------
# 4. Set env vars the handler reads, then create the mocked resources
# ---------------------------------------------------------------------------
TABLE_NAME = "ticketresolve-dev"
BUCKET_NAME = "ticketresolve-attachments-dev"

os.environ["TABLE_NAME"] = TABLE_NAME
os.environ["ATTACHMENTS_BUCKET"] = BUCKET_NAME

import boto3  # noqa: E402

_dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
_s3 = boto3.client("s3", region_name="us-east-1")

# Create the DynamoDB table (mirrors conftest.py / Terraform schema exactly)
_dynamodb.create_table(
    TableName=TABLE_NAME,
    KeySchema=[
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    AttributeDefinitions=[
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
        {"AttributeName": "GSI1PK", "AttributeType": "S"},
        {"AttributeName": "GSI1SK", "AttributeType": "S"},
        {"AttributeName": "GSI2PK", "AttributeType": "S"},
        {"AttributeName": "GSI2SK", "AttributeType": "S"},
    ],
    GlobalSecondaryIndexes=[
        {
            "IndexName": "GSI1",
            "KeySchema": [
                {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
        {
            "IndexName": "GSI2",
            "KeySchema": [
                {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        },
    ],
    BillingMode="PAY_PER_REQUEST",
)

# Enable TTL on the table
_ttl_client = boto3.client("dynamodb", region_name="us-east-1")
_ttl_client.update_time_to_live(
    TableName=TABLE_NAME,
    TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
)

# Create the S3 bucket
_s3.create_bucket(Bucket=BUCKET_NAME)

# ---------------------------------------------------------------------------
# 5. Import the handler AFTER moto is active and env is set
#    Also reset lazy boto3 singletons so they bind to the moto context
# ---------------------------------------------------------------------------
from shared import ddb as _ddb_module, s3 as _s3_module  # noqa: E402
_ddb_module.reset()
_s3_module.reset()

from api_tickets.lambda_function import lambda_handler  # noqa: E402
from api_tickets import service as _svc  # noqa: E402

# ---------------------------------------------------------------------------
# 6. Seed demo data (idempotent: table is always fresh in-memory)
# ---------------------------------------------------------------------------

def _seed_demo() -> None:
    """
    Seed ~7 realistic demo tickets so the UI starts populated.

    Each call to a service function is the same code path the real Lambda uses,
    so this exercises the full stack (DDB transact_write via moto) at startup.

    Guarded by SEED_DEMO env var: set SEED_DEMO=0 to disable.
    All errors are caught and logged; the server ALWAYS starts even if seeding fails.
    """
    # Use a local logger: this function is called before the module-level logger
    # is created in the FastAPI setup section below.
    _log = logging.getLogger(__name__)

    if os.environ.get("SEED_DEMO", "1") == "0":
        return

    try:
        # ----------------------------------------------------------------
        # 1. Ticket: P0 — Pasarela de Pagos caída (ana, ESCALATED)
        # ----------------------------------------------------------------
        body1, _ = _svc.create_ticket({
            "title": "[Pagos] Pasarela de pago no responde",
            "service": "pagos",
            "description": "La pasarela principal devuelve HTTP 503 desde las 02:14 UTC. "
                           "Transacciones fallando al 100% en producción.",
            "severity": "P0",
            "assignee": "ana",
        })
        tid1 = body1["ticket_id"]
        _svc.update_status(tid1, {"status": "ACK",       "actor": "ana",    "version": 1})
        _svc.update_status(tid1, {"status": "ESCALATED", "actor": "ana",    "version": 2})
        _svc.add_comment(tid1, {
            "author": "ana",
            "body": "Contactado al proveedor. Esperando RCA. SLA en riesgo.",
        })

        # ----------------------------------------------------------------
        # 2. Ticket: P1 — API Gateway latencia elevada (carlos, ACK)
        # ----------------------------------------------------------------
        body2, _ = _svc.create_ticket({
            "title": "[API] Latencia p99 > 5 segundos en /orders",
            "service": "api-gateway",
            "description": "Spike de latencia detectado por Datadog. p99 subió de 200ms a 5.3s.",
            "severity": "P1",
            "assignee": "carlos",
        })
        tid2 = body2["ticket_id"]
        _svc.update_status(tid2, {"status": "ACK", "actor": "carlos", "version": 1})
        _svc.add_comment(tid2, {
            "author": "carlos",
            "body": "Rollback de deploy en progreso. Monitoreo activo.",
        })

        # ----------------------------------------------------------------
        # 3. Ticket: P1 — Auth service — via webhook con 3 ocurrencias
        # ----------------------------------------------------------------
        body3, _ = _svc.ingest_alert({
            "service": "auth",
            "alert_type": "TOKEN_VALIDATION_FAILURE",
            "severity": "P1",
            "title": "[Auth] Fallo masivo de validación de tokens JWT",
            "description": "Alertas de Prometheus: tasa de errores 401 > 40% en últimos 5 min.",
            "source": "prometheus",
            "assignee": "maria",
        })
        tid3 = body3["ticket_id"]
        # Simular 2 alertas duplicadas (occurrence_count → 3)
        _svc.ingest_alert({
            "service": "auth",
            "alert_type": "TOKEN_VALIDATION_FAILURE",
            "source": "prometheus",
        })
        _svc.ingest_alert({
            "service": "auth",
            "alert_type": "TOKEN_VALIDATION_FAILURE",
            "source": "prometheus",
        })

        # ----------------------------------------------------------------
        # 4. Ticket: P2 — Checkout UI — OPEN, sin asignar
        # ----------------------------------------------------------------
        body4, _ = _svc.create_ticket({
            "title": "[Checkout] Botón 'Comprar' deshabilitado en Safari",
            "service": "checkout",
            "description": "Reporte de QA: el botón de compra aparece disabled en Safari 17. "
                           "No reproducible en Chrome/Firefox.",
            "severity": "P2",
        })

        # ----------------------------------------------------------------
        # 5. Ticket: P2 — Reporte PDF (maria, RESOLVED)
        # ----------------------------------------------------------------
        body5, _ = _svc.create_ticket({
            "title": "[Reportes] PDF de factura mensual no genera",
            "service": "reportes",
            "description": "Usuarios de plan Enterprise no pueden descargar factura de mayo.",
            "severity": "P2",
            "assignee": "maria",
        })
        tid5 = body5["ticket_id"]
        _svc.update_status(tid5, {"status": "ACK",      "actor": "maria", "version": 1})
        _svc.update_status(tid5, {"status": "RESOLVED", "actor": "maria", "version": 2})
        _svc.add_comment(tid5, {
            "author": "maria",
            "body": "Deploy con fix aplicado. Facturas regeneradas manualmente para clientes afectados.",
        })

        # ----------------------------------------------------------------
        # 6. Ticket: P1 — DB réplica de lectura (carlos, OPEN)
        # ----------------------------------------------------------------
        body6, _ = _svc.create_ticket({
            "title": "[DB] Réplica de lectura con lag > 30 segundos",
            "service": "database",
            "description": "CloudWatch: ReplicationLag métrica supera 30s. "
                           "Queries de lectura sirviendo datos desactualizados.",
            "severity": "P1",
            "assignee": "carlos",
        })

        # ----------------------------------------------------------------
        # 7. Ticket: P0 — Notificaciones email (ana, OPEN, sin asignar inicialmente)
        # ----------------------------------------------------------------
        body7, _ = _svc.create_ticket({
            "title": "[Notificaciones] Emails transaccionales sin entregar",
            "service": "notificaciones",
            "description": "SES bounce rate al 12% — umbral crítico. "
                           "Emails de confirmación de orden no llegan a clientes.",
            "severity": "P0",
        })
        tid7 = body7["ticket_id"]
        # Reasignar a ana
        _svc.reassign_ticket(tid7, {"assignee": "ana", "actor": "ops-bot", "version": 1})

        seeded = 7
        _log.info("Seeded %d demo tickets", seeded)

    except Exception:
        _log.exception("Demo seed failed — server will start without seed data")


_seed_demo()

# ---------------------------------------------------------------------------
# 7. FastAPI app
# ---------------------------------------------------------------------------
from fastapi import FastAPI, Request, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

app = FastAPI(title="TicketResolve Dev Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _invoke_handler(request: Request, path: str) -> Response:
    """Build an HTTP API v2 event and call the real lambda_handler."""
    raw_path = f"/api/v1/{path}"
    raw_query = request.url.query  # already encoded string

    # Build queryStringParameters dict (single-value — handler uses .get())
    query_params: dict | None = None
    if raw_query:
        query_params = {}
        for pair in raw_query.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                query_params[k] = v
            else:
                query_params[pair] = ""

    # Read body
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8") if body_bytes else None

    # Flatten headers to plain dict of strings
    headers = dict(request.headers)

    event = {
        "version": "2.0",
        "rawPath": raw_path,
        "rawQueryString": raw_query,
        "headers": headers,
        "requestContext": {
            "http": {
                "method": request.method.upper(),
                "path": raw_path,
            },
        },
        "body": body_str,
        "isBase64Encoded": False,
    }
    if query_params is not None:
        event["queryStringParameters"] = query_params

    logger.info("Invoking handler: %s %s", request.method.upper(), raw_path)
    result = lambda_handler(event, None)

    status_code: int = result.get("statusCode", 200)
    resp_headers: dict = result.get("headers", {})
    resp_body: str = result.get("body", "")

    return Response(
        content=resp_body,
        status_code=status_code,
        headers=resp_headers,
        media_type=resp_headers.get("Content-Type", "application/json"),
    )


@app.get("/api/v1/{path:path}")
async def api_get(request: Request, path: str):
    return await _invoke_handler(request, path)


@app.post("/api/v1/{path:path}")
async def api_post(request: Request, path: str):
    return await _invoke_handler(request, path)


@app.patch("/api/v1/{path:path}")
async def api_patch(request: Request, path: str):
    return await _invoke_handler(request, path)


@app.options("/api/v1/{path:path}")
async def api_options(request: Request, path: str):
    return await _invoke_handler(request, path)
