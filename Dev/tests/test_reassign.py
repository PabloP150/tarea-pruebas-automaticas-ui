"""
test_reassign.py — Tests for PATCH /api/v1/incidents/{id}/assignee  (Cambio 2 / US-06)

Covers:
  - Happy path: reassign changes assignee and GSI1PK; version increments.
  - Dashboard reflects new owner (GSI1 query), old owner no longer finds ticket.
  - ASSIGNED event appears in get_ticket response.
  - Version conflict (wrong version) → 409.
  - Missing assignee / missing actor → 400.
  - Reassigning a RESOLVED ticket → 400.
  - Routing: PATCH /incidents/{id}/assignee reaches reassign_ticket (not update_status).
  - PATCH /incidents/{id} (no /assignee) still routes to update_status (non-regression).
"""
import json
import pytest
from boto3.dynamodb.conditions import Key
from conftest import make_event


BASE_PATH = "/api/v1/incidents"


def get_handler():
    from api_tickets.lambda_function import lambda_handler
    return lambda_handler


def create_ticket(handler, assignee="eng-initial", severity="P2", **kwargs):
    """Helper: create a ticket and return ticket_id."""
    defaults = {
        "title": "Reassign test ticket",
        "service": "test-svc",
        "description": "Testing reassignment.",
        "severity": severity,
        "assignee": assignee,
    }
    defaults.update(kwargs)
    event = make_event("POST", BASE_PATH, body=defaults)
    resp = handler(event, {})
    assert resp["statusCode"] == 201, f"create_ticket failed: {resp['body']}"
    return json.loads(resp["body"])["ticket_id"]


def patch_reassign(handler, ticket_id, assignee, actor, version):
    """Helper: PATCH /incidents/{id}/assignee and return full response."""
    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}/assignee",
        body={"assignee": assignee, "actor": actor, "version": version},
    )
    return handler(event, {})


def patch_status(handler, ticket_id, status, actor, version):
    """Helper: PATCH /incidents/{id} for status transitions."""
    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": status, "actor": actor, "version": version},
    )
    return handler(event, {})


# ===========================================================================
# Happy path
# ===========================================================================

def test_reassign_changes_assignee_and_version(aws_services):
    """
    PATCH /incidents/{id}/assignee returns 200 with new assignee and version+1.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="eng-old")

    resp = patch_reassign(handler, ticket_id, "eng-new", "ops-bot", 1)
    assert resp["statusCode"] == 200, f"Expected 200, got {resp['statusCode']}: {resp['body']}"

    body = json.loads(resp["body"])
    assert body["assignee"] == "eng-new"
    assert body["version"] == 2


def test_reassign_updates_meta_in_dynamo(aws_services):
    """
    META item in DynamoDB must reflect the new assignee, GSI1PK, and version.
    """
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")

    resp = patch_reassign(handler, ticket_id, "bob", "ops-bot", 1)
    assert resp["statusCode"] == 200

    meta = table.get_item(
        Key={"PK": f"TICKET#{ticket_id}", "SK": "META"}
    )["Item"]

    assert meta["assignee"] == "bob"
    assert meta["GSI1PK"] == "ASSIGN#bob", f"GSI1PK should be ASSIGN#bob, got {meta['GSI1PK']}"
    assert meta["version"] == 2


def test_reassign_gsi1pk_updated_for_dashboard(aws_services):
    """
    After reassignment, querying GSI1 by the NEW assignee must find the ticket.
    Querying by the OLD assignee must return empty.
    """
    table, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")
    patch_reassign(handler, ticket_id, "bob", "ops-bot", 1)

    # New assignee (bob) can see the ticket via GSI1
    new_result = table.query(
        IndexName="GSI1",
        KeyConditionExpression=(
            Key("GSI1PK").eq("ASSIGN#bob")
        ),
    )
    new_ticket_ids = [i.get("ticket_id") for i in new_result.get("Items", [])]
    assert ticket_id in new_ticket_ids, "New assignee should find ticket via GSI1"

    # Old assignee (alice) no longer sees the ticket
    old_result = table.query(
        IndexName="GSI1",
        KeyConditionExpression=(
            Key("GSI1PK").eq("ASSIGN#alice")
        ),
    )
    old_ticket_ids = [i.get("ticket_id") for i in old_result.get("Items", [])]
    assert ticket_id not in old_ticket_ids, "Old assignee should NOT find ticket via GSI1"


def test_reassign_event_written(aws_services):
    """
    An ASSIGNED event with from/to payload must be written and visible via get_ticket.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")
    patch_reassign(handler, ticket_id, "bob", "ops-bot", 1)

    get_event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(get_event, {})
    assert resp["statusCode"] == 200

    data = json.loads(resp["body"])
    event_types = [e["event_type"] for e in data["events"]]
    assert "ASSIGNED" in event_types, f"ASSIGNED event not found in: {event_types}"

    assigned_events = [e for e in data["events"] if e["event_type"] == "ASSIGNED"]
    assert len(assigned_events) == 1
    ev = assigned_events[0]
    assert ev["actor"] == "ops-bot"
    assert ev["payload"]["from"] == "alice"
    assert ev["payload"]["to"] == "bob"
    assert "Reasignado a bob" in ev["action"]


def test_reassign_version_increments_in_response(aws_services):
    """
    Each reassignment must increment version by 1 cumulatively.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")

    resp1 = patch_reassign(handler, ticket_id, "bob", "ops-bot", 1)
    assert json.loads(resp1["body"])["version"] == 2

    resp2 = patch_reassign(handler, ticket_id, "carol", "ops-bot", 2)
    assert resp2["statusCode"] == 200
    assert json.loads(resp2["body"])["version"] == 3


# ===========================================================================
# Optimistic locking: version conflict → 409
# ===========================================================================

def test_reassign_wrong_version_returns_409(aws_services):
    """
    Sending a wrong version must return 409 (VersionConflict).
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")

    # Ticket is at version 1; send version 99
    resp = patch_reassign(handler, ticket_id, "bob", "ops-bot", 99)
    assert resp["statusCode"] == 409, (
        f"Expected 409 for wrong version, got {resp['statusCode']}: {resp['body']}"
    )


def test_reassign_stale_version_after_update_returns_409(aws_services):
    """
    After a reassignment bumps the version to 2, retrying with version=1 must yield 409.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")

    # First reassign succeeds
    resp1 = patch_reassign(handler, ticket_id, "bob", "ops-bot", 1)
    assert resp1["statusCode"] == 200

    # Second with stale version=1 → conflict
    resp2 = patch_reassign(handler, ticket_id, "carol", "ops-bot", 1)
    assert resp2["statusCode"] == 409


# ===========================================================================
# Validation errors → 400
# ===========================================================================

def test_reassign_missing_assignee_returns_400(aws_services):
    """assignee is required."""
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}/assignee",
        body={"actor": "ops-bot", "version": 1},  # no assignee
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 400


def test_reassign_missing_actor_returns_400(aws_services):
    """actor is required."""
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}/assignee",
        body={"assignee": "bob", "version": 1},  # no actor
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 400


def test_reassign_missing_version_returns_400(aws_services):
    """version is required."""
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}/assignee",
        body={"assignee": "bob", "actor": "ops-bot"},  # no version
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 400


def test_reassign_zero_version_returns_400(aws_services):
    """version must be >= 1."""
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}/assignee",
        body={"assignee": "bob", "actor": "ops-bot", "version": 0},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 400


def test_reassign_assignee_too_long_returns_400(aws_services):
    """assignee exceeding MAX_ACTOR_LEN must return 400."""
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}/assignee",
        body={"assignee": "x" * 101, "actor": "ops-bot", "version": 1},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 400


# ===========================================================================
# Guard: cannot reassign a RESOLVED ticket → 400
# ===========================================================================

def test_reassign_resolved_ticket_returns_400(aws_services):
    """
    Reassigning a RESOLVED ticket must return 400 with a meaningful message.
    RESOLVED is a terminal state; ownership changes are meaningless.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")

    # Resolve the ticket first
    resp_resolve = patch_status(handler, ticket_id, "RESOLVED", "alice", 1)
    assert resp_resolve["statusCode"] == 200

    # Attempt to reassign
    resp = patch_reassign(handler, ticket_id, "bob", "ops-bot", 2)
    assert resp["statusCode"] == 400, (
        f"Expected 400 for reassigning RESOLVED ticket, got {resp['statusCode']}: {resp['body']}"
    )

    body = json.loads(resp["body"])
    assert "resuelto" in body["error"].lower() or "resolved" in body["error"].lower(), (
        f"Error message should mention resolved state: {body['error']}"
    )


# ===========================================================================
# Routing
# ===========================================================================

def test_routing_patch_assignee_reaches_reassign_ticket(aws_services):
    """
    PATCH /incidents/{id}/assignee must reach reassign_ticket, NOT update_status.
    A successful 200 with 'assignee' in the response body proves the correct handler fired.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}/assignee",
        body={"assignee": "bob", "actor": "ops-bot", "version": 1},
    )
    resp = handler(event, {})

    assert resp["statusCode"] == 200, (
        f"Expected 200 from reassign_ticket, got {resp['statusCode']}: {resp['body']}"
    )
    body = json.loads(resp["body"])
    assert "assignee" in body, "Response should have 'assignee' key (reassign_ticket contract)"
    assert "version" in body
    # Must NOT have 'status' key (that is update_status's contract)
    assert "status" not in body, "Response should NOT have 'status' — wrong handler fired"


def test_routing_patch_status_still_works_after_assignee_route(aws_services):
    """
    Non-regression: PATCH /incidents/{id} (without /assignee) must still reach
    update_status and NOT be swallowed by the assignee regex.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler, assignee="alice")

    event = make_event(
        "PATCH",
        f"{BASE_PATH}/{ticket_id}",
        body={"status": "ACK", "actor": "alice", "version": 1},
    )
    resp = handler(event, {})

    assert resp["statusCode"] == 200, (
        f"Expected 200 from update_status, got {resp['statusCode']}: {resp['body']}"
    )
    body = json.loads(resp["body"])
    assert body["status"] == "ACK"
    assert "assignee" not in body, "update_status response should NOT have 'assignee'"


def test_routing_assignee_path_wrong_method_returns_404(aws_services):
    """
    GET /incidents/{id}/assignee is not a registered route → 404.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id = create_ticket(handler)

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}/assignee")
    resp = handler(event, {})
    assert resp["statusCode"] == 404


def test_reassign_404_for_nonexistent_ticket(aws_services):
    """
    Reassigning a non-existent ticket must return 404.
    """
    _, _ = aws_services
    handler = get_handler()

    resp = patch_reassign(handler, "TKT-NONEXIST", "bob", "ops-bot", 1)
    assert resp["statusCode"] == 404
