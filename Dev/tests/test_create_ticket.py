"""
test_create_ticket.py — Tests for POST /api/v1/incidents  (US-01)
"""
import json
import pytest
from boto3.dynamodb.conditions import Key
from conftest import make_event


BASE_PATH = "/api/v1/incidents"


def get_handler():
    from api_tickets.lambda_function import lambda_handler
    return lambda_handler


# ---------------------------------------------------------------------------
# Test: create ticket with explicit severity
# ---------------------------------------------------------------------------
def test_create_ticket_201(aws_services):
    table, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        BASE_PATH,
        body={
            "title": "DB is down",
            "service": "database",
            "description": "Primary replica not responding.",
            "severity": "P1",
            "assignee": "eng-alice",
        },
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 201

    body = json.loads(resp["body"])
    ticket_id = body["ticket_id"]
    assert ticket_id.startswith("TKT-")
    assert body["status"] == "OPEN"
    assert "sla_deadline" in body
    assert "upload_url" not in body


# ---------------------------------------------------------------------------
# Test: META item is written with correct attributes
# ---------------------------------------------------------------------------
def test_create_ticket_meta_in_dynamo(aws_services):
    table, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        BASE_PATH,
        body={
            "title": "Service X degraded",
            "service": "api-gateway",
            "description": "High latency observed.",
            "severity": "P0",
            "assignee": "eng-bob",
        },
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    ticket_id = body["ticket_id"]

    # Fetch META from DynamoDB
    result = table.get_item(Key={"PK": f"TICKET#{ticket_id}", "SK": "META"})
    meta = result["Item"]

    assert meta["ticket_id"] == ticket_id
    assert meta["status"] == "OPEN"
    assert meta["severity"] == "P0"
    assert meta["assignee"] == "eng-bob"
    assert meta["version"] == 1
    assert meta["attachments_count"] == 0
    assert meta["GSI1PK"] == f"ASSIGN#eng-bob"
    assert meta["GSI1SK"].startswith("STATUS#OPEN#SLA#")
    assert meta["sla_deadline"] == body["sla_deadline"]


# ---------------------------------------------------------------------------
# Test: EVENT(CREATED) is written
# ---------------------------------------------------------------------------
def test_create_ticket_event_written(aws_services):
    table, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        BASE_PATH,
        body={
            "title": "Auth service down",
            "service": "auth",
            "description": "Users cannot login.",
        },
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 201
    ticket_id = json.loads(resp["body"])["ticket_id"]

    # Query all items for this ticket
    result = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKET#{ticket_id}")
    )
    items = result["Items"]
    sks = [item["SK"] for item in items]

    # Must have META + at least one EVENT
    assert "META" in sks
    event_sks = [sk for sk in sks if sk.startswith("EVENT#")]
    assert len(event_sks) >= 1

    # The CREATED event
    created_events = [i for i in items if i.get("event_type") == "CREATED"]
    assert len(created_events) == 1


# ---------------------------------------------------------------------------
# Test: default severity P2 when omitted
# ---------------------------------------------------------------------------
def test_create_ticket_default_severity_p2(aws_services):
    table, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        BASE_PATH,
        body={
            "title": "Minor issue",
            "service": "frontend",
            "description": "Button misaligned.",
            # No severity field
        },
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 201
    ticket_id = json.loads(resp["body"])["ticket_id"]

    result = table.get_item(Key={"PK": f"TICKET#{ticket_id}", "SK": "META"})
    meta = result["Item"]
    assert meta["severity"] == "P2"
    assert meta["assignee"] == "UNASSIGNED"


# ---------------------------------------------------------------------------
# Test: invalid severity returns 400
# ---------------------------------------------------------------------------
def test_create_ticket_invalid_severity(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        BASE_PATH,
        body={
            "title": "Something",
            "service": "svc",
            "description": "Desc",
            "severity": "CRITICAL",  # Invalid
        },
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 400


# ---------------------------------------------------------------------------
# Test: missing required fields returns 400
# ---------------------------------------------------------------------------
def test_create_ticket_missing_title(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        BASE_PATH,
        body={"service": "svc", "description": "Desc"},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 400


# ---------------------------------------------------------------------------
# Test: with attachment -> returns upload_url, ATTACH item written, attachments_count=1
# ---------------------------------------------------------------------------
def test_create_ticket_with_attachment(aws_services):
    table, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        BASE_PATH,
        body={
            "title": "Logs needed",
            "service": "worker",
            "description": "Attach crash log.",
            "severity": "P1",
            "assignee": "eng-carol",
            "attachment": {
                "filename": "crash.log",
                "content_type": "text/plain",
            },
        },
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 201

    body = json.loads(resp["body"])
    ticket_id = body["ticket_id"]
    assert "upload_url" in body
    assert "crash.log" in body["upload_url"] or "attachments" in body["upload_url"]

    # Check META has attachments_count=1
    result = table.get_item(Key={"PK": f"TICKET#{ticket_id}", "SK": "META"})
    meta = result["Item"]
    assert meta["attachments_count"] == 1

    # Check ATTACH item exists
    all_items = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKET#{ticket_id}")
    )["Items"]
    attach_items = [i for i in all_items if i["SK"].startswith("ATTACH#")]
    assert len(attach_items) == 1
    assert attach_items[0]["filename"] == "crash.log"
    assert attach_items[0]["content_type"] == "text/plain"
