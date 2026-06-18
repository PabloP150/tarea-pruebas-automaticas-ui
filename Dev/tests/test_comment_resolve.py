"""
test_comment_resolve.py — Tests for comment and resolve  (US-05)
"""
import json
import pytest
from boto3.dynamodb.conditions import Key
from conftest import make_event


BASE_PATH = "/api/v1/incidents"


def get_handler():
    from api_tickets.lambda_function import lambda_handler
    return lambda_handler


def create_ticket(handler, **kwargs):
    """Helper: create a ticket and return ticket_id."""
    defaults = {
        "title": "Test ticket",
        "service": "test-svc",
        "description": "Description.",
        "severity": "P2",
        "assignee": "eng-test",
    }
    defaults.update(kwargs)
    event = make_event("POST", BASE_PATH, body=defaults)
    resp = handler(event, {})
    assert resp["statusCode"] == 201
    return json.loads(resp["body"])["ticket_id"]


# ---------------------------------------------------------------------------
# Test: add comment → COMMENT + EVENT(COMMENT_ADDED) written
# ---------------------------------------------------------------------------
def test_add_comment_writes_items(aws_services):
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event(
        "POST",
        f"{BASE_PATH}/{ticket_id}/comments",
        body={"author": "eng-alice", "body": "I'm looking into this now."},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 201

    body = json.loads(resp["body"])
    assert body["ok"] is True

    # Verify items in DynamoDB
    all_items = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKET#{ticket_id}")
    )["Items"]

    comment_items = [i for i in all_items if i["SK"].startswith("COMMENT#")]
    event_items = [i for i in all_items if i["SK"].startswith("EVENT#")]

    assert len(comment_items) == 1
    assert comment_items[0]["author"] == "eng-alice"
    assert comment_items[0]["body"] == "I'm looking into this now."

    comment_added_events = [e for e in event_items if e.get("event_type") == "COMMENT_ADDED"]
    assert len(comment_added_events) == 1


# ---------------------------------------------------------------------------
# Test: add comment to non-existent ticket → 404
# ---------------------------------------------------------------------------
def test_add_comment_ticket_not_found(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        f"{BASE_PATH}/TKT-BOGUS99/comments",
        body={"author": "eng-alice", "body": "Hello?"},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 404


# ---------------------------------------------------------------------------
# Test: comment missing required fields → 400
# ---------------------------------------------------------------------------
def test_add_comment_missing_body_field(aws_services):
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event(
        "POST",
        f"{BASE_PATH}/{ticket_id}/comments",
        body={"author": "eng-alice"},  # missing "body"
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 400


# ---------------------------------------------------------------------------
# Test: resolve with correct version → RESOLVED, GSI1SK updated, version incremented
# ---------------------------------------------------------------------------
def test_resolve_ticket_success(aws_services):
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, severity="P0", assignee="eng-resolver")

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": "RESOLVED", "actor": "eng-resolver", "version": 1},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["status"] == "RESOLVED"
    assert body["version"] == 2

    # Verify META in DynamoDB
    result = table.get_item(Key={"PK": f"TICKET#{ticket_id}", "SK": "META"})
    meta = result["Item"]

    assert meta["status"] == "RESOLVED"
    assert meta["version"] == 2
    assert "resolved_at" in meta

    # GSI1SK must have STATUS#RESOLVED# prefix with original SLA preserved
    gsi1_sk = meta["GSI1SK"]
    assert gsi1_sk.startswith("STATUS#RESOLVED#SLA#"), \
        f"Expected GSI1SK to start with STATUS#RESOLVED#SLA#, got: {gsi1_sk}"

    # The SLA should still be present (frozen, not zeroed)
    sla_part = gsi1_sk.split("STATUS#RESOLVED#SLA#")[-1]
    assert len(sla_part) > 0


# ---------------------------------------------------------------------------
# Test: resolve with WRONG version → 409 conflict
# ---------------------------------------------------------------------------
def test_resolve_version_conflict(aws_services):
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, severity="P1", assignee="eng-conflict")

    # Wrong version (ticket starts at version 1, send version 99)
    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": "RESOLVED", "actor": "eng-conflict", "version": 99},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 409


# ---------------------------------------------------------------------------
# Test: resolve audit EVENT(RESOLVED) is written
# ---------------------------------------------------------------------------
def test_resolve_writes_event(aws_services):
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, severity="P2", assignee="eng-ev")

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": "RESOLVED", "actor": "eng-ev", "version": 1},
    )
    handler(event, {})

    all_items = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKET#{ticket_id}")
    )["Items"]

    resolved_events = [i for i in all_items if i.get("event_type") == "RESOLVED"]
    assert len(resolved_events) == 1
    assert resolved_events[0]["actor"] == "eng-ev"


# ---------------------------------------------------------------------------
# Test: resolve non-existent ticket → 404
# ---------------------------------------------------------------------------
def test_resolve_ticket_not_found(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/TKT-GHOST00",
        body={"status": "RESOLVED", "actor": "eng-x", "version": 1},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 404


# ---------------------------------------------------------------------------
# Test: resolving a RESOLVED ticket → 400 (status guard, CRIT-03)
#
# Pre-CRIT-03 this test expected 409 (version conflict).  With the explicit
# status guard in place, attempting to re-resolve a RESOLVED ticket is caught
# as a domain validation error (400) before the DB write is even attempted.
# 409 is reserved for concurrent version races, not for explicit invalid state
# transitions.
# ---------------------------------------------------------------------------
def test_resolve_twice_returns_400(aws_services):
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    # First resolve — should succeed
    event1 = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": "RESOLVED", "actor": "eng-double", "version": 1},
    )
    resp1 = handler(event1, {})
    assert resp1["statusCode"] == 200

    # Second resolve — status guard catches this as 400 (already RESOLVED)
    event2 = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": "RESOLVED", "actor": "eng-double", "version": 2},
    )
    resp2 = handler(event2, {})
    assert resp2["statusCode"] == 400
    import json
    body = json.loads(resp2["body"])
    assert "RESOLVED" in body["error"] or "cannot be resolved" in body["error"]


# ---------------------------------------------------------------------------
# FIX-5: RESOLVED event action must be in Spanish ("Ticket resuelto")
# ---------------------------------------------------------------------------
def test_resolve_event_action_is_in_spanish(aws_services):
    """
    FIX-5 regression: the action string on the RESOLVED event item must read
    'Ticket resuelto' (consistent with ACK/ESCALATED) — not the old English
    'Ticket resolved'.
    """
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": "RESOLVED", "actor": "eng-i18n", "version": 1},
    )
    handler(event, {})

    all_items = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKET#{ticket_id}")
    )["Items"]

    resolved_events = [i for i in all_items if i.get("event_type") == "RESOLVED"]
    assert len(resolved_events) == 1
    action = resolved_events[0]["action"]
    assert action == "Ticket resuelto", (
        f"Expected 'Ticket resuelto' (FIX-5 i18n), got '{action}'"
    )
