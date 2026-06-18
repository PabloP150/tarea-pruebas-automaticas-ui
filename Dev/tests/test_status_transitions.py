"""
test_status_transitions.py — Tests for the generalised PATCH state machine.

Covers:
  - OPEN → ACK   (happy path: version increments, GSI1SK updated, EVENT written)
  - OPEN → ESCALATED
  - ACK  → ESCALATED
  - ESCALATED → ACK  (backward transition allowed)
  - Full chain: OPEN → ACK → ESCALATED → RESOLVED (version increments at every step)
  - Invalid target (OPEN as target)  → 400
  - Disallowed transition (RESOLVED → ACK) → 400
  - Wrong version on ACK transition  → 409
  - resolve_ticket wrapper still works (backward compat)
  - Routing: PATCH with status=ACK reaches update_status via lambda_handler
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
        "title": "State machine ticket",
        "service": "sm-svc",
        "description": "Testing state transitions.",
        "severity": "P2",
        "assignee": "eng-sm",
    }
    defaults.update(kwargs)
    event = make_event("POST", BASE_PATH, body=defaults)
    resp = handler(event, {})
    assert resp["statusCode"] == 201, f"create_ticket failed: {resp['body']}"
    return json.loads(resp["body"])["ticket_id"]


def patch_status(handler, ticket_id, status, actor, version):
    """Helper: PATCH a ticket status and return the full response dict."""
    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": status, "actor": actor, "version": version},
    )
    return handler(event, {})


# ===========================================================================
# ACK transitions
# ===========================================================================

def test_ack_transition_success(aws_services):
    """
    OPEN → ACK: HTTP 200, status=ACK, version incremented to 2.
    META in DDB must reflect the new status and GSI1SK.
    """
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, severity="P1", assignee="eng-ack-ok")

    resp = patch_status(handler, ticket_id, "ACK", "eng-ack-ok", 1)
    assert resp["statusCode"] == 200, f"Expected 200, got {resp['statusCode']}: {resp['body']}"

    body = json.loads(resp["body"])
    assert body["status"] == "ACK"
    assert body["version"] == 2

    # Verify META persisted correctly
    meta = table.get_item(
        Key={"PK": f"TICKET#{ticket_id}", "SK": "META"}
    )["Item"]
    assert meta["status"] == "ACK"
    assert meta["version"] == 2
    assert meta["GSI1SK"].startswith("STATUS#ACK#SLA#"), \
        f"GSI1SK should start with STATUS#ACK#SLA#, got: {meta['GSI1SK']}"
    # resolved_at must NOT be set for non-RESOLVED transitions
    assert "resolved_at" not in meta


def test_ack_transition_event_written(aws_services):
    """
    OPEN → ACK: an EVENT(ACK) item must be written with the correct actor and payload.
    """
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-ack-ev")
    resp = patch_status(handler, ticket_id, "ACK", "eng-ack-ev", 1)
    assert resp["statusCode"] == 200

    items = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKET#{ticket_id}")
    )["Items"]

    ack_events = [i for i in items if i.get("event_type") == "ACK"]
    assert len(ack_events) == 1, f"Expected 1 ACK event, found {len(ack_events)}"

    ev = ack_events[0]
    assert ev["actor"] == "eng-ack-ev"
    assert ev["action"] == "Ticket reconocido"
    # payload must include previous_status
    assert ev["payload"].get("previous_status") == "OPEN"


def test_ack_visible_via_get_ticket(aws_services):
    """
    After OPEN → ACK the EVENT(ACK) must be visible through GET /incidents/{id}.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-ack-get")
    patch_status(handler, ticket_id, "ACK", "eng-ack-get", 1)

    get_event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(get_event, {})
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    event_types = [e["event_type"] for e in data["events"]]
    assert "ACK" in event_types, f"ACK event not found in events: {event_types}"


# ===========================================================================
# ESCALATED transitions
# ===========================================================================

def test_open_to_escalated_success(aws_services):
    """OPEN → ESCALATED: HTTP 200, GSI1SK with STATUS#ESCALATED#."""
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-esc-open")

    resp = patch_status(handler, ticket_id, "ESCALATED", "eng-esc-open", 1)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["status"] == "ESCALATED"
    assert body["version"] == 2

    meta = table.get_item(
        Key={"PK": f"TICKET#{ticket_id}", "SK": "META"}
    )["Item"]
    assert meta["status"] == "ESCALATED"
    assert meta["GSI1SK"].startswith("STATUS#ESCALATED#SLA#")


def test_ack_to_escalated_success(aws_services):
    """ACK → ESCALATED: both transitions allowed; version increments each step."""
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-ack-esc")

    # First: OPEN → ACK
    resp1 = patch_status(handler, ticket_id, "ACK", "eng-ack-esc", 1)
    assert resp1["statusCode"] == 200
    assert json.loads(resp1["body"])["version"] == 2

    # Then: ACK → ESCALATED
    resp2 = patch_status(handler, ticket_id, "ESCALATED", "eng-ack-esc", 2)
    assert resp2["statusCode"] == 200

    body2 = json.loads(resp2["body"])
    assert body2["status"] == "ESCALATED"
    assert body2["version"] == 3

    meta = table.get_item(
        Key={"PK": f"TICKET#{ticket_id}", "SK": "META"}
    )["Item"]
    assert meta["status"] == "ESCALATED"
    assert meta["version"] == 3


def test_escalated_event_written(aws_services):
    """ESCALATED event must carry previous_status in payload."""
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-esc-ev")
    patch_status(handler, ticket_id, "ESCALATED", "eng-esc-ev", 1)

    items = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKET#{ticket_id}")
    )["Items"]

    esc_events = [i for i in items if i.get("event_type") == "ESCALATED"]
    assert len(esc_events) == 1
    assert esc_events[0]["payload"].get("previous_status") == "OPEN"


# ===========================================================================
# Backward transition: ESCALATED → ACK
# ===========================================================================

def test_escalated_to_ack_allowed(aws_services):
    """ESCALATED → ACK is an explicitly allowed transition."""
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-esc-ack")

    patch_status(handler, ticket_id, "ESCALATED", "eng-esc-ack", 1)
    resp = patch_status(handler, ticket_id, "ACK", "eng-esc-ack", 2)
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    assert body["status"] == "ACK"
    assert body["version"] == 3

    meta = table.get_item(
        Key={"PK": f"TICKET#{ticket_id}", "SK": "META"}
    )["Item"]
    assert meta["status"] == "ACK"
    assert meta["version"] == 3


# ===========================================================================
# Full chain: OPEN → ACK → ESCALATED → RESOLVED
# ===========================================================================

def test_full_chain_open_ack_escalated_resolved(aws_services):
    """
    Drive a ticket through all four statuses in sequence.
    At each step verify: HTTP 200, correct status, version incremented by 1,
    correct event type written.
    """
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, severity="P0", assignee="eng-chain")

    steps = [
        ("ACK",       1, 2, "ACK"),
        ("ESCALATED", 2, 3, "ESCALATED"),
        ("RESOLVED",  3, 4, "RESOLVED"),
    ]

    for target, send_ver, expected_ver, expected_event_type in steps:
        resp = patch_status(handler, ticket_id, target, "eng-chain", send_ver)
        assert resp["statusCode"] == 200, \
            f"Step {target} failed ({resp['statusCode']}): {resp['body']}"
        body = json.loads(resp["body"])
        assert body["status"] == target, f"Step {target}: status mismatch"
        assert body["version"] == expected_ver, \
            f"Step {target}: expected version {expected_ver}, got {body['version']}"

    # Verify final META state
    meta = table.get_item(
        Key={"PK": f"TICKET#{ticket_id}", "SK": "META"}
    )["Item"]
    assert meta["status"] == "RESOLVED"
    assert meta["version"] == 4
    assert "resolved_at" in meta

    # Verify all four event types exist
    items = table.query(
        KeyConditionExpression=Key("PK").eq(f"TICKET#{ticket_id}")
    )["Items"]
    event_types = {i.get("event_type") for i in items if "event_type" in i}
    assert {"CREATED", "ACK", "ESCALATED", "RESOLVED"}.issubset(event_types), \
        f"Missing events. Found: {event_types}"


# ===========================================================================
# Invalid transitions → 400
# ===========================================================================

def test_invalid_target_open_returns_400(aws_services):
    """
    OPEN is not a valid target status for PATCH.  Must return 400.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    resp = patch_status(handler, ticket_id, "OPEN", "eng-bad", 1)
    assert resp["statusCode"] == 400, \
        f"Expected 400 for target=OPEN, got {resp['statusCode']}"


def test_invalid_target_garbage_returns_400(aws_services):
    """A completely unknown status string must return 400."""
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)
    resp = patch_status(handler, ticket_id, "FLYING", "eng-bad", 1)
    assert resp["statusCode"] == 400


def test_resolved_to_ack_returns_400(aws_services):
    """
    RESOLVED → ACK: RESOLVED is a terminal state; no transitions allowed.
    Must return 400 (state-machine guard), NOT 409 (version conflict).
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    # Resolve the ticket first
    resp1 = patch_status(handler, ticket_id, "RESOLVED", "eng-terminal", 1)
    assert resp1["statusCode"] == 200

    # Attempt to ACK a RESOLVED ticket
    resp2 = patch_status(handler, ticket_id, "ACK", "eng-terminal", 2)
    assert resp2["statusCode"] == 400, \
        f"Expected 400 for RESOLVED→ACK, got {resp2['statusCode']}: {resp2['body']}"

    body = json.loads(resp2["body"])
    # Error message must mention the invalid transition
    assert "RESOLVED" in body["error"], \
        f"Error should mention RESOLVED state: {body['error']}"


def test_resolved_to_escalated_returns_400(aws_services):
    """RESOLVED → ESCALATED also forbidden."""
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)
    patch_status(handler, ticket_id, "RESOLVED", "admin", 1)

    resp = patch_status(handler, ticket_id, "ESCALATED", "admin", 2)
    assert resp["statusCode"] == 400


def test_resolve_again_returns_400(aws_services):
    """
    Trying to RESOLVE an already RESOLVED ticket must return 400.
    This is the same scenario as test_resolve_twice_returns_400 in
    test_comment_resolve.py — both must pass simultaneously.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    resp1 = patch_status(handler, ticket_id, "RESOLVED", "eng-double-sm", 1)
    assert resp1["statusCode"] == 200

    resp2 = patch_status(handler, ticket_id, "RESOLVED", "eng-double-sm", 2)
    assert resp2["statusCode"] == 400
    body = json.loads(resp2["body"])
    assert "RESOLVED" in body["error"]


# ===========================================================================
# Version conflict (409) on state transitions
# ===========================================================================

def test_wrong_version_on_ack_returns_409(aws_services):
    """
    Supplying a wrong version on an ACK transition must return 409.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-ver-ack")

    # Ticket starts at version 1; send version 99
    resp = patch_status(handler, ticket_id, "ACK", "eng-ver-ack", 99)
    assert resp["statusCode"] == 409, \
        f"Expected 409 for wrong version, got {resp['statusCode']}: {resp['body']}"


def test_wrong_version_on_escalated_returns_409(aws_services):
    """Version mismatch on ESCALATED also yields 409."""
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)
    resp = patch_status(handler, ticket_id, "ESCALATED", "admin", 42)
    assert resp["statusCode"] == 409


# ===========================================================================
# resolve_ticket wrapper backward compatibility
# ===========================================================================

def test_resolve_ticket_wrapper_still_works(aws_services):
    """
    service.resolve_ticket is a thin wrapper around update_status.
    Calling it directly must behave exactly as before.
    """
    from api_tickets import service

    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    result, status_code = service.resolve_ticket(
        ticket_id, {"status": "RESOLVED", "actor": "eng-wrapper", "version": 1}
    )
    assert status_code == 200
    assert result["status"] == "RESOLVED"
    assert result["version"] == 2


def test_resolve_ticket_wrapper_rejects_invalid_target(aws_services):
    """
    resolve_ticket no longer validates target==RESOLVED itself; that gate is
    now in update_status.  Passing status='OPEN' via the wrapper must return
    ValidationError (would map to 400 via the handler).
    """
    from api_tickets import service
    from shared.models import ValidationError

    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    with pytest.raises(ValidationError):
        service.resolve_ticket(
            ticket_id, {"status": "OPEN", "actor": "eng-wrapper-bad", "version": 1}
        )


# ===========================================================================
# Routing: PATCH with status=ACK reaches update_status via lambda_handler
# ===========================================================================

def test_routing_patch_ack_reaches_update_status(aws_services):
    """
    End-to-end routing test: confirms lambda_handler dispatches PATCH requests
    to service.update_status (not to the old resolve_ticket directly).
    A successful 200 with status=ACK proves the route is wired to the new
    general handler.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-route-ack")

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": "ACK", "actor": "eng-route-ack", "version": 1},
    )
    resp = handler(event, {})

    assert resp["statusCode"] == 200, \
        f"Expected 200 for PATCH status=ACK, got {resp['statusCode']}: {resp['body']}"
    body = json.loads(resp["body"])
    assert body["status"] == "ACK"
    assert body["version"] == 2
