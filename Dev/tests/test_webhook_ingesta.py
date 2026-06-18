"""
test_webhook_ingesta.py — Tests for POST /api/v1/webhooks/alerts  (US-02)

Covers:
  1.  First alert → 201, deduplicated=False, occurrence_count=1;
      META in DB has GSI2PK/GSI2SK, dedup_hash, occurrence_count.
  2.  Second identical alert → 200, deduplicated=True, same ticket_id,
      occurrence_count=2; only one META per hash; get_ticket shows
      ALERT_DUPLICATE event.
  3.  Third identical alert → occurrence_count=3.
  4.  Different service or alert_type → separate ticket created.
  5.  Hash normalisation: ("Pagos","HTTP_503") and (" pagos ","http_503")
      map to the SAME ticket.
  6.  After resolving the parent, an identical alert creates a NEW ticket.
  7.  Validation errors: missing service (400), missing alert_type (400),
      invalid severity (400), oversized title/description/source (400).
  8.  Routing: POST /api/v1/webhooks/alerts reaches ingest_alert via
      lambda_handler.
  9.  Defaults: omitting title/description/severity/source applies
      the documented defaults.
"""
import json
import pytest
from boto3.dynamodb.conditions import Key
from conftest import make_event

from shared import keys, models

WEBHOOK_PATH = "/api/v1/webhooks/alerts"
INCIDENTS_PATH = "/api/v1/incidents"


def get_handler():
    from api_tickets.lambda_function import lambda_handler
    return lambda_handler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ingest(handler, service="payments", alert_type="HTTP_503", **extra):
    """Send a POST /api/v1/webhooks/alerts and return the parsed response."""
    payload = {"service": service, "alert_type": alert_type, **extra}
    event = make_event("POST", WEBHOOK_PATH, body=payload)
    resp = handler(event, {})
    return resp, json.loads(resp["body"])


def _resolve(handler, ticket_id, version=1, actor="ops-agent"):
    """Resolve a ticket via PATCH /api/v1/incidents/{id}."""
    event = make_event(
        "PATCH",
        f"{INCIDENTS_PATH}/{ticket_id}",
        body={"status": "RESOLVED", "actor": actor, "version": version},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 200, f"Resolve failed: {resp['body']}"
    return json.loads(resp["body"])


# ---------------------------------------------------------------------------
# 1. First alert — new ticket created (201)
# ---------------------------------------------------------------------------

def test_first_alert_creates_ticket(aws_services):
    table, _ = aws_services
    handler = get_handler()

    resp, body = _ingest(handler, service="payments", alert_type="HTTP_503")

    assert resp["statusCode"] == 201
    assert body["deduplicated"] is False
    assert body["occurrence_count"] == 1
    assert body["status"] == models.DEFAULT_STATUS
    assert "sla_deadline" in body

    ticket_id = body["ticket_id"]
    assert ticket_id.startswith("TKT-")

    # Verify META attributes in DynamoDB
    meta_result = table.get_item(
        Key={"PK": keys.ticket_pk(ticket_id), "SK": keys.meta_sk()}
    )
    meta = meta_result["Item"]

    # GSI2 keys must be present and correctly formatted
    expected_hash = models.dedup_hash("payments", "HTTP_503")
    assert meta["GSI2PK"] == keys.gsi2_pk(expected_hash)
    assert meta["GSI2SK"] == keys.gsi2_sk(ticket_id)
    assert meta["dedup_hash"] == expected_hash
    assert int(meta["occurrence_count"]) == 1
    assert meta["source"] == "monitoring"  # default


# ---------------------------------------------------------------------------
# 2. Second identical alert — dedup, occurrence_count=2
# ---------------------------------------------------------------------------

def test_second_identical_alert_deduplicates(aws_services):
    table, _ = aws_services
    handler = get_handler()

    # First alert
    resp1, body1 = _ingest(handler, service="payments", alert_type="HTTP_503")
    assert resp1["statusCode"] == 201
    parent_id = body1["ticket_id"]

    # Second identical alert
    resp2, body2 = _ingest(handler, service="payments", alert_type="HTTP_503")

    assert resp2["statusCode"] == 200
    assert body2["deduplicated"] is True
    assert body2["ticket_id"] == parent_id
    assert body2["occurrence_count"] == 2
    assert body2["status"] == models.DEFAULT_STATUS

    # GSI2 must still show only ONE active parent
    h = models.dedup_hash("payments", "HTTP_503")
    gsi2_resp = table.query(
        IndexName="GSI2",
        KeyConditionExpression=Key("GSI2PK").eq(keys.gsi2_pk(h)),
    )
    active = [
        i for i in gsi2_resp["Items"]
        if i.get("status") in models.RESOLVABLE_STATUSES
    ]
    assert len(active) == 1, "Expected exactly one active parent META in GSI2"

    # get_ticket must surface an ALERT_DUPLICATE event
    get_event = make_event("GET", f"{INCIDENTS_PATH}/{parent_id}")
    get_resp = handler(get_event, {})
    assert get_resp["statusCode"] == 200
    ticket_data = json.loads(get_resp["body"])
    event_types = [e["event_type"] for e in ticket_data["events"]]
    assert "ALERT_DUPLICATE" in event_types, (
        f"Expected ALERT_DUPLICATE event in timeline, got: {event_types}"
    )


# ---------------------------------------------------------------------------
# 3. Third identical alert — occurrence_count=3
# ---------------------------------------------------------------------------

def test_third_identical_alert_increments_to_3(aws_services):
    _, _ = aws_services
    handler = get_handler()

    _ingest(handler, service="payments", alert_type="HTTP_503")
    _ingest(handler, service="payments", alert_type="HTTP_503")
    resp3, body3 = _ingest(handler, service="payments", alert_type="HTTP_503")

    assert resp3["statusCode"] == 200
    assert body3["occurrence_count"] == 3


# ---------------------------------------------------------------------------
# 4. Different service or alert_type → separate ticket
# ---------------------------------------------------------------------------

def test_different_service_creates_separate_ticket(aws_services):
    _, _ = aws_services
    handler = get_handler()

    _, body_a = _ingest(handler, service="payments", alert_type="HTTP_503")
    _, body_b = _ingest(handler, service="auth", alert_type="HTTP_503")

    assert body_a["ticket_id"] != body_b["ticket_id"]
    assert body_b["deduplicated"] is False
    assert body_b["occurrence_count"] == 1


def test_different_alert_type_creates_separate_ticket(aws_services):
    _, _ = aws_services
    handler = get_handler()

    _, body_a = _ingest(handler, service="payments", alert_type="HTTP_503")
    _, body_b = _ingest(handler, service="payments", alert_type="CPU_HIGH")

    assert body_a["ticket_id"] != body_b["ticket_id"]
    assert body_b["deduplicated"] is False


# ---------------------------------------------------------------------------
# 5. Hash normalisation — case and whitespace insensitive
# ---------------------------------------------------------------------------

def test_hash_normalisation_deduplicates_across_case_and_spaces(aws_services):
    _, _ = aws_services
    handler = get_handler()

    # "Pagos" and " pagos " with different casing must hash identically
    resp1, body1 = _ingest(handler, service="Pagos", alert_type="HTTP_503")
    assert resp1["statusCode"] == 201
    parent_id = body1["ticket_id"]

    resp2, body2 = _ingest(handler, service=" pagos ", alert_type="http_503")

    assert resp2["statusCode"] == 200
    assert body2["deduplicated"] is True
    assert body2["ticket_id"] == parent_id


# ---------------------------------------------------------------------------
# 6. After resolving the parent, next alert creates a NEW ticket
# ---------------------------------------------------------------------------

def test_alert_after_resolve_creates_new_ticket(aws_services):
    _, _ = aws_services
    handler = get_handler()

    # Create the initial ticket
    resp1, body1 = _ingest(handler, service="payments", alert_type="HTTP_503")
    assert resp1["statusCode"] == 201
    parent_id = body1["ticket_id"]

    # Resolve it
    _resolve(handler, parent_id, version=1)

    # Same alert should now create a brand-new ticket
    resp2, body2 = _ingest(handler, service="payments", alert_type="HTTP_503")

    assert resp2["statusCode"] == 201
    assert body2["deduplicated"] is False
    assert body2["ticket_id"] != parent_id
    assert body2["occurrence_count"] == 1


# ---------------------------------------------------------------------------
# 7. Validation errors
# ---------------------------------------------------------------------------

def test_missing_service_returns_400(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event("POST", WEBHOOK_PATH, body={"alert_type": "HTTP_503"})
    resp = handler(event, {})

    assert resp["statusCode"] == 400
    assert "service" in json.loads(resp["body"])["error"]


def test_missing_alert_type_returns_400(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event("POST", WEBHOOK_PATH, body={"service": "payments"})
    resp = handler(event, {})

    assert resp["statusCode"] == 400
    assert "alert_type" in json.loads(resp["body"])["error"]


def test_invalid_severity_returns_400(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        WEBHOOK_PATH,
        body={"service": "payments", "alert_type": "HTTP_503", "severity": "CRITICAL"},
    )
    resp = handler(event, {})

    assert resp["statusCode"] == 400


def test_oversized_title_returns_400(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        WEBHOOK_PATH,
        body={
            "service": "payments",
            "alert_type": "HTTP_503",
            "title": "T" * (models.MAX_TITLE_LEN + 1),
        },
    )
    resp = handler(event, {})

    assert resp["statusCode"] == 400
    assert "title" in json.loads(resp["body"])["error"]


def test_oversized_description_returns_400(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        WEBHOOK_PATH,
        body={
            "service": "payments",
            "alert_type": "HTTP_503",
            "description": "D" * (models.MAX_DESCRIPTION_LEN + 1),
        },
    )
    resp = handler(event, {})

    assert resp["statusCode"] == 400
    assert "description" in json.loads(resp["body"])["error"]


def test_oversized_source_returns_400(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        WEBHOOK_PATH,
        body={
            "service": "payments",
            "alert_type": "HTTP_503",
            "source": "S" * (models.MAX_ACTOR_LEN + 1),
        },
    )
    resp = handler(event, {})

    assert resp["statusCode"] == 400
    assert "source" in json.loads(resp["body"])["error"]


# ---------------------------------------------------------------------------
# 8. Routing — POST /api/v1/webhooks/alerts reaches ingest_alert
# ---------------------------------------------------------------------------

def test_webhook_route_is_reachable(aws_services):
    """
    Verifies that the lambda_handler routes POST /api/v1/webhooks/alerts
    to ingest_alert and returns a valid response (not 404).
    """
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        WEBHOOK_PATH,
        body={"service": "routing-svc", "alert_type": "ROUTE_CHECK"},
    )
    resp = handler(event, {})

    # Must not be 404 (unmatched route) or 405 (wrong method)
    assert resp["statusCode"] in {200, 201}, (
        f"Expected 200 or 201 from webhook route, got {resp['statusCode']}: {resp['body']}"
    )
    body = json.loads(resp["body"])
    assert "ticket_id" in body
    assert "deduplicated" in body


# ---------------------------------------------------------------------------
# 9. Defaults — omitted optional fields use documented defaults
# ---------------------------------------------------------------------------

def test_defaults_applied_when_optional_fields_omitted(aws_services):
    table, _ = aws_services
    handler = get_handler()

    # Send only the two required fields
    resp, body = _ingest(handler, service="my-svc", alert_type="DISK_FULL")

    assert resp["statusCode"] == 201
    ticket_id = body["ticket_id"]

    meta_result = table.get_item(
        Key={"PK": keys.ticket_pk(ticket_id), "SK": keys.meta_sk()}
    )
    meta = meta_result["Item"]

    # Severity default
    assert meta["severity"] == models.DEFAULT_SEVERITY

    # Source default
    assert meta["source"] == "monitoring"

    # Title default
    expected_title = "[my-svc] DISK_FULL"
    assert meta["title"] == expected_title

    # Description default
    expected_description = "Alerta automática 'DISK_FULL' del servicio 'my-svc'."
    assert meta["description"] == expected_description

    # Assignee default
    assert meta["assignee"] == models.DEFAULT_ASSIGNEE


# ===========================================================================
# FIX-2 — Dedup pointer: strongly-consistent race-free deduplication
# ===========================================================================

def test_create_alert_writes_dedup_pointer(aws_services):
    """
    After the first alert, a DEDUP pointer item must exist at
    PK=DEDUP#<hash> / SK=ACTIVE pointing to the created ticket.
    """
    table, _ = aws_services
    handler = get_handler()

    resp, body = _ingest(handler, service="payments", alert_type="HTTP_503")
    assert resp["statusCode"] == 201
    ticket_id = body["ticket_id"]

    h = models.dedup_hash("payments", "HTTP_503")
    from shared import keys as _keys
    pointer = table.get_item(
        Key={"PK": _keys.dedup_pointer_pk(h), "SK": _keys.DEDUP_POINTER_SK}
    ).get("Item")

    assert pointer is not None, "Dedup pointer must be written when first ticket is created"
    assert pointer["parent_ticket_id"] == ticket_id


def test_second_alert_deduplicates_via_pointer(aws_services):
    """
    Second identical alert must join the first ticket (same ticket_id)
    using the pointer as the authoritative signal.
    """
    _, _ = aws_services
    handler = get_handler()

    resp1, body1 = _ingest(handler, service="payments", alert_type="HTTP_503")
    assert resp1["statusCode"] == 201
    parent_id = body1["ticket_id"]

    resp2, body2 = _ingest(handler, service="payments", alert_type="HTTP_503")
    assert resp2["statusCode"] == 200
    assert body2["deduplicated"] is True
    assert body2["ticket_id"] == parent_id
    assert body2["occurrence_count"] == 2


def test_resolve_parent_deletes_dedup_pointer(aws_services):
    """
    Resolving the parent ticket must atomically delete the dedup pointer
    so subsequent alerts for the same hash create a new ticket.
    """
    table, _ = aws_services
    handler = get_handler()

    resp1, body1 = _ingest(handler, service="payments", alert_type="HTTP_503")
    assert resp1["statusCode"] == 201
    parent_id = body1["ticket_id"]

    # Pointer must exist before resolve
    h = models.dedup_hash("payments", "HTTP_503")
    from shared import keys as _keys
    assert table.get_item(
        Key={"PK": _keys.dedup_pointer_pk(h), "SK": _keys.DEDUP_POINTER_SK}
    ).get("Item") is not None, "Pointer must exist before resolve"

    # Resolve the parent
    _resolve(handler, parent_id, version=1)

    # Pointer must be gone after resolve
    pointer_after = table.get_item(
        Key={"PK": _keys.dedup_pointer_pk(h), "SK": _keys.DEDUP_POINTER_SK}
    ).get("Item")
    assert pointer_after is None, "Dedup pointer must be deleted when ticket is resolved"

    # Next identical alert must create a brand-new ticket (not dedup)
    resp2, body2 = _ingest(handler, service="payments", alert_type="HTTP_503")
    assert resp2["statusCode"] == 201
    assert body2["deduplicated"] is False
    assert body2["ticket_id"] != parent_id
    assert body2["occurrence_count"] == 1


def test_dedup_pointer_not_deleted_on_non_resolve_transition(aws_services):
    """
    Transitioning to ACK or ESCALATED must NOT delete the dedup pointer —
    the ticket is still active and future alerts must still dedup against it.
    """
    table, _ = aws_services
    handler = get_handler()

    resp1, body1 = _ingest(handler, service="payments", alert_type="CPU_HIGH")
    assert resp1["statusCode"] == 201
    parent_id = body1["ticket_id"]

    h = models.dedup_hash("payments", "CPU_HIGH")
    from shared import keys as _keys

    # Transition to ACK
    ack_event = make_event(
        "PATCH",
        f"{INCIDENTS_PATH}/{parent_id}",
        body={"status": "ACK", "actor": "ops", "version": 1},
    )
    assert handler(ack_event, {})["statusCode"] == 200

    # Pointer must still exist
    pointer = table.get_item(
        Key={"PK": _keys.dedup_pointer_pk(h), "SK": _keys.DEDUP_POINTER_SK}
    ).get("Item")
    assert pointer is not None, "Pointer must survive non-RESOLVED transitions"
    assert pointer["parent_ticket_id"] == parent_id

    # A duplicate alert must still dedup against the ACK'd ticket
    resp2, body2 = _ingest(handler, service="payments", alert_type="CPU_HIGH")
    assert resp2["statusCode"] == 200
    assert body2["deduplicated"] is True
    assert body2["ticket_id"] == parent_id


# ===========================================================================
# FIX-3 — dedup_hash must not be exposed in get_ticket response
# ===========================================================================

def test_get_ticket_does_not_expose_dedup_hash(aws_services):
    """
    get_ticket for a webhook-originated ticket must not include dedup_hash
    in the meta object — it is an internal implementation detail.
    """
    _, _ = aws_services
    handler = get_handler()

    resp, body = _ingest(handler, service="payments", alert_type="HTTP_503")
    assert resp["statusCode"] == 201
    ticket_id = body["ticket_id"]

    get_event = make_event("GET", f"{INCIDENTS_PATH}/{ticket_id}")
    get_resp = handler(get_event, {})
    assert get_resp["statusCode"] == 200

    meta = json.loads(get_resp["body"])["meta"]
    assert "dedup_hash" not in meta, (
        "dedup_hash is an internal field and must not be returned in the API response"
    )

    # Verify that other webhook fields ARE still present
    assert "occurrence_count" in meta
    assert "source" in meta


# ===========================================================================
# FIX-4 — Blank values and source sanitization
# ===========================================================================

def test_blank_service_after_strip_returns_400(aws_services):
    """'service' that is only whitespace must be rejected with 400."""
    _, _ = aws_services
    handler = get_handler()

    event = make_event("POST", WEBHOOK_PATH, body={"service": "   ", "alert_type": "HTTP_503"})
    resp = handler(event, {})
    assert resp["statusCode"] == 400
    assert "service" in json.loads(resp["body"])["error"].lower()


def test_blank_alert_type_after_strip_returns_400(aws_services):
    """'alert_type' that is only whitespace must be rejected with 400."""
    _, _ = aws_services
    handler = get_handler()

    event = make_event("POST", WEBHOOK_PATH, body={"service": "payments", "alert_type": "\t\n"})
    resp = handler(event, {})
    assert resp["statusCode"] == 400
    assert "alert_type" in json.loads(resp["body"])["error"].lower()


def test_explicit_empty_title_falls_back_to_default(aws_services):
    """
    If title is sent as an empty string (or all-whitespace), the service
    must persist the auto-generated default title, not an empty string.
    """
    table, _ = aws_services
    handler = get_handler()

    resp, body = _ingest(
        handler,
        service="payments",
        alert_type="HTTP_503",
        title="",
    )
    assert resp["statusCode"] == 201
    ticket_id = body["ticket_id"]

    meta = table.get_item(
        Key={"PK": __import__("shared.keys", fromlist=["keys"]).ticket_pk(ticket_id),
             "SK": __import__("shared.keys", fromlist=["keys"]).meta_sk()}
    )["Item"]

    expected_default = "[payments] HTTP_503"
    assert meta["title"] == expected_default, (
        f"Expected default title '{expected_default}', got '{meta['title']}'"
    )


def test_source_with_special_chars_is_sanitized(aws_services):
    """
    A 'source' containing characters outside [alnum, space, -, _, .]
    must be stored with those characters stripped, not as-is.
    """
    table, _ = aws_services
    handler = get_handler()

    resp, body = _ingest(
        handler,
        service="payments",
        alert_type="HTTP_503",
        source="prometheus<script>alert(1)</script>",
    )
    assert resp["statusCode"] == 201
    ticket_id = body["ticket_id"]

    meta = table.get_item(
        Key={"PK": __import__("shared.keys", fromlist=["keys"]).ticket_pk(ticket_id),
             "SK": __import__("shared.keys", fromlist=["keys"]).meta_sk()}
    )["Item"]

    stored_source = meta["source"]
    # Angle brackets and parentheses must have been removed
    assert "<" not in stored_source
    assert ">" not in stored_source
    assert "(" not in stored_source
    assert ")" not in stored_source
    # Alphanumeric characters must be preserved
    assert "prometheus" in stored_source
