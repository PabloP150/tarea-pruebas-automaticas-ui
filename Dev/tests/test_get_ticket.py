"""
test_get_ticket.py — Tests for GET /api/v1/incidents/{id}  (PA-1)
"""
import json
import pytest
from conftest import make_event


BASE_PATH = "/api/v1/incidents"


def get_handler():
    from api_tickets.lambda_function import lambda_handler
    return lambda_handler


def create_ticket(handler, **kwargs):
    """Helper: create a ticket and return (ticket_id, response_body)."""
    defaults = {
        "title": "Test ticket",
        "service": "test-svc",
        "description": "A test description.",
        "severity": "P2",
        "assignee": "eng-test",
    }
    defaults.update(kwargs)
    event = make_event("POST", BASE_PATH, body=defaults)
    resp = handler(event, {})
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    return body["ticket_id"], body


# ---------------------------------------------------------------------------
# Test: get ticket assembles meta + events + comments + attachments
# ---------------------------------------------------------------------------
def test_get_ticket_assembles_full_response(aws_services):
    _, _ = aws_services
    handler = get_handler()

    ticket_id, _ = create_ticket(handler)

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(event, {})
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert "meta" in body
    assert "events" in body
    assert "comments" in body
    assert "attachments" in body

    # META should have correct attributes
    meta = body["meta"]
    assert meta["ticket_id"] == ticket_id
    assert meta["status"] == "OPEN"
    assert meta["version"] == 1

    # At least CREATED event
    assert len(body["events"]) >= 1
    event_types = [e["event_type"] for e in body["events"]]
    assert "CREATED" in event_types

    # No GSI keys leaked
    for key in ("PK", "SK", "GSI1PK", "GSI1SK"):
        assert key not in meta


# ---------------------------------------------------------------------------
# Test: meta does NOT contain raw DynamoDB key attributes
# ---------------------------------------------------------------------------
def test_get_ticket_strips_ddb_keys(aws_services):
    _, _ = aws_services
    handler = get_handler()

    ticket_id, _ = create_ticket(handler)

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(event, {})
    body = json.loads(resp["body"])
    meta = body["meta"]

    for attr in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK"):
        assert attr not in meta, f"DynamoDB key '{attr}' should be stripped from response"


# ---------------------------------------------------------------------------
# Test: 404 for unknown ticket
# ---------------------------------------------------------------------------
def test_get_ticket_not_found(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event("GET", f"{BASE_PATH}/TKT-NONEXIST")
    resp = handler(event, {})
    assert resp["statusCode"] == 404


# ---------------------------------------------------------------------------
# Test: get ticket with attachment includes attachments[]
# ---------------------------------------------------------------------------
def test_get_ticket_with_attachment(aws_services):
    _, _ = aws_services
    handler = get_handler()

    ticket_id, _ = create_ticket(
        handler,
        attachment={"filename": "screenshot.png", "content_type": "image/png"},
    )

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(event, {})
    body = json.loads(resp["body"])

    assert resp["statusCode"] == 200
    assert len(body["attachments"]) == 1
    assert body["attachments"][0]["filename"] == "screenshot.png"


# ---------------------------------------------------------------------------
# FIX-3: dedup_hash must not be included in meta for webhook tickets
# ---------------------------------------------------------------------------
def test_get_webhook_ticket_does_not_expose_dedup_hash(aws_services):
    """
    A ticket created via ingest_alert stores dedup_hash internally for
    deduplication.  The get_ticket response must strip that field —
    it is an internal implementation detail that the frontend never needs
    and whose exposure could aid fingerprinting of monitoring topology.
    """
    _, _ = aws_services
    handler = get_handler()

    # Create ticket via the webhook path
    webhook_event = make_event(
        "POST",
        "/api/v1/webhooks/alerts",
        body={"service": "payments", "alert_type": "HTTP_503"},
    )
    webhook_resp = handler(webhook_event, {})
    assert webhook_resp["statusCode"] == 201
    ticket_id = json.loads(webhook_resp["body"])["ticket_id"]

    # Retrieve the ticket
    get_event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    get_resp = handler(get_event, {})
    assert get_resp["statusCode"] == 200

    meta = json.loads(get_resp["body"])["meta"]

    # dedup_hash must be absent
    assert "dedup_hash" not in meta, (
        "dedup_hash is an internal field and must not appear in get_ticket response"
    )

    # Legitimate webhook meta fields must still be present
    assert "occurrence_count" in meta
    assert "source" in meta
