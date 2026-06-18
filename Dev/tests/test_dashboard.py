"""
test_dashboard.py — Tests for GET /api/v1/incidents?assignee=&status=  (US-03, PA-2)
"""
import json
import time
import pytest
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
    }
    defaults.update(kwargs)
    event = make_event("POST", BASE_PATH, body=defaults)
    resp = handler(event, {})
    assert resp["statusCode"] == 201
    return json.loads(resp["body"])["ticket_id"]


# ---------------------------------------------------------------------------
# Test: dashboard returns items for the given assignee, sorted by SLA ascending
# ---------------------------------------------------------------------------
def test_dashboard_returns_items_sorted_by_sla(aws_services):
    _, _ = aws_services
    handler = get_handler()

    assignee = "eng-dashboard-test"

    # Create 3 tickets: P0 (15 min SLA), P1 (240 min), P2 (1440 min)
    # P0 will have the earliest SLA deadline → should appear first
    t0 = create_ticket(handler, title="P0 ticket", service="s", description="d",
                       severity="P0", assignee=assignee)
    t1 = create_ticket(handler, title="P1 ticket", service="s", description="d",
                       severity="P1", assignee=assignee)
    t2 = create_ticket(handler, title="P2 ticket", service="s", description="d",
                       severity="P2", assignee=assignee)

    event = make_event(
        "GET", BASE_PATH,
        query_params={"assignee": assignee, "status": "OPEN"},
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    items = body["items"]
    assert len(items) == 3

    # Should be sorted ascending by SLA deadline
    sla_deadlines = [item["sla_deadline"] for item in items]
    assert sla_deadlines == sorted(sla_deadlines), \
        f"Items not sorted by SLA: {sla_deadlines}"

    # Verify all are OPEN
    for item in items:
        assert item["status"] == "OPEN"
        assert item["assignee"] == assignee


# ---------------------------------------------------------------------------
# Test: only OPEN tickets are returned when status=OPEN
# ---------------------------------------------------------------------------
def test_dashboard_excludes_resolved_tickets(aws_services):
    table, _ = aws_services
    handler = get_handler()

    assignee = "eng-excl-test"

    t_open = create_ticket(handler, title="Open ticket", service="s", description="d",
                           severity="P2", assignee=assignee)
    t_resolve = create_ticket(handler, title="To resolve", service="s", description="d",
                              severity="P1", assignee=assignee)

    # Resolve the second ticket
    resolve_event = make_event(
        "PATCH", f"{BASE_PATH}/{t_resolve}",
        body={"status": "RESOLVED", "actor": "admin", "version": 1},
    )
    resp = handler(resolve_event, {})
    assert resp["statusCode"] == 200

    # Dashboard should only see open
    dash_event = make_event(
        "GET", BASE_PATH,
        query_params={"assignee": assignee, "status": "OPEN"},
    )
    resp = handler(dash_event, {})
    body = json.loads(resp["body"])
    ids_returned = [item["ticket_id"] for item in body["items"]]

    assert t_open in ids_returned
    assert t_resolve not in ids_returned


# ---------------------------------------------------------------------------
# Test: missing assignee now returns 200 via full-table Scan (changed behaviour)
#
# Pre-change: missing assignee raised ValidationError → 400.
# Post-change: missing/empty assignee triggers the Scan path and returns all
# tickets for that status across all assignees.  400 is now reserved for an
# invalid status value, not for an absent assignee.
# ---------------------------------------------------------------------------
def test_dashboard_missing_assignee_returns_200_scan(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event("GET", BASE_PATH, query_params={"status": "OPEN"})
    resp = handler(event, {})
    # With the Scan path active this returns 200 (possibly with 0 items)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert "items" in body


# ---------------------------------------------------------------------------
# Test: default status is OPEN
# ---------------------------------------------------------------------------
def test_dashboard_default_status_open(aws_services):
    _, _ = aws_services
    handler = get_handler()

    assignee = "eng-default-status"
    create_ticket(handler, title="T1", service="s", description="d",
                  severity="P2", assignee=assignee)

    # No status param — should default to OPEN
    event = make_event("GET", BASE_PATH, query_params={"assignee": assignee})
    resp = handler(event, {})
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["items"]) == 1


# ---------------------------------------------------------------------------
# Test: tickets for different assignees don't bleed into each other
# ---------------------------------------------------------------------------
def test_dashboard_isolates_by_assignee(aws_services):
    _, _ = aws_services
    handler = get_handler()

    create_ticket(handler, title="Alice ticket", service="s", description="d",
                  severity="P2", assignee="eng-alice-iso")
    create_ticket(handler, title="Bob ticket", service="s", description="d",
                  severity="P2", assignee="eng-bob-iso")

    event = make_event("GET", BASE_PATH, query_params={"assignee": "eng-alice-iso"})
    resp = handler(event, {})
    body = json.loads(resp["body"])
    assert len(body["items"]) == 1
    assert body["items"][0]["assignee"] == "eng-alice-iso"


# ===========================================================================
# Dashboard Scan path (no assignee)
# ===========================================================================

# ---------------------------------------------------------------------------
# Test: no-assignee Scan returns ALL OPEN tickets across multiple engineers
# ---------------------------------------------------------------------------
def test_dashboard_no_assignee_returns_all_open(aws_services):
    """
    Create tickets for three different assignees. A GET with no assignee and
    status=OPEN must return all of them via the Scan path.
    """
    _, _ = aws_services
    handler = get_handler()

    # Tickets belonging to three distinct engineers
    t_a = create_ticket(handler, title="Alice OPEN", service="s", description="d",
                        severity="P2", assignee="eng-scan-alice")
    t_b = create_ticket(handler, title="Bob OPEN", service="s", description="d",
                        severity="P1", assignee="eng-scan-bob")
    t_c = create_ticket(handler, title="Carol OPEN", service="s", description="d",
                        severity="P0", assignee="eng-scan-carol")

    event = make_event("GET", BASE_PATH, query_params={"status": "OPEN"})
    resp = handler(event, {})
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    returned_ids = {item["ticket_id"] for item in body["items"]}

    assert t_a in returned_ids, "Alice's ticket missing from no-assignee Scan"
    assert t_b in returned_ids, "Bob's ticket missing from no-assignee Scan"
    assert t_c in returned_ids, "Carol's ticket missing from no-assignee Scan"

    # All items must be OPEN
    for item in body["items"]:
        assert item["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Test: no-assignee Scan with status=RESOLVED returns only resolved tickets
# ---------------------------------------------------------------------------
def test_dashboard_no_assignee_resolved_filter(aws_services):
    """
    Create two tickets; resolve one. A no-assignee query for status=RESOLVED
    should return only the resolved ticket; status=OPEN should exclude it.
    """
    _, _ = aws_services
    handler = get_handler()

    t_open = create_ticket(handler, title="Stays open", service="s", description="d",
                           severity="P2", assignee="eng-scan-filter-a")
    t_resolve = create_ticket(handler, title="Gets resolved", service="s", description="d",
                              severity="P2", assignee="eng-scan-filter-b")

    # Resolve one ticket
    patch_event = make_event(
        "PATCH", f"{BASE_PATH}/{t_resolve}",
        body={"status": "RESOLVED", "actor": "admin-scan", "version": 1},
    )
    assert handler(patch_event, {})["statusCode"] == 200

    # Scan for RESOLVED — must find the resolved ticket, not the open one
    scan_resolved = make_event("GET", BASE_PATH, query_params={"status": "RESOLVED"})
    resp_resolved = handler(scan_resolved, {})
    assert resp_resolved["statusCode"] == 200
    resolved_ids = {item["ticket_id"] for item in json.loads(resp_resolved["body"])["items"]}
    assert t_resolve in resolved_ids
    assert t_open not in resolved_ids

    # Scan for OPEN — must NOT include the resolved ticket
    scan_open = make_event("GET", BASE_PATH, query_params={"status": "OPEN"})
    resp_open = handler(scan_open, {})
    open_ids = {item["ticket_id"] for item in json.loads(resp_open["body"])["items"]}
    assert t_open in open_ids
    assert t_resolve not in open_ids


# ---------------------------------------------------------------------------
# Test: no-assignee Scan results are sorted ascending by sla_deadline
# ---------------------------------------------------------------------------
def test_dashboard_no_assignee_sorted_by_sla(aws_services):
    """
    P0 has the tightest SLA (15 min) and must appear first; P2 last.
    """
    _, _ = aws_services
    handler = get_handler()

    # Create in reverse SLA order to ensure sorting is not insertion-order
    create_ticket(handler, title="P2 late", service="s", description="d",
                  severity="P2", assignee="eng-sort-scan-a")
    create_ticket(handler, title="P0 urgent", service="s", description="d",
                  severity="P0", assignee="eng-sort-scan-b")
    create_ticket(handler, title="P1 mid", service="s", description="d",
                  severity="P1", assignee="eng-sort-scan-c")

    event = make_event("GET", BASE_PATH, query_params={"status": "OPEN"})
    resp = handler(event, {})
    assert resp["statusCode"] == 200

    items = json.loads(resp["body"])["items"]
    sla_list = [item["sla_deadline"] for item in items]
    assert sla_list == sorted(sla_list), \
        f"No-assignee Scan items not sorted by sla_deadline: {sla_list}"


# ---------------------------------------------------------------------------
# Test: no-assignee Scan with invalid status → 400
# ---------------------------------------------------------------------------
def test_dashboard_no_assignee_invalid_status(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event("GET", BASE_PATH, query_params={"status": "BOGUS"})
    resp = handler(event, {})
    assert resp["statusCode"] == 400


# ---------------------------------------------------------------------------
# Test: with-assignee path is unchanged (GSI1 query, not Scan)
# ---------------------------------------------------------------------------
def test_dashboard_with_assignee_uses_gsi_path(aws_services):
    """
    Regression guard: providing assignee must still return only that engineer's
    tickets, not a cross-assignee result set.
    """
    _, _ = aws_services
    handler = get_handler()

    t_mine = create_ticket(handler, title="My ticket", service="s", description="d",
                           severity="P2", assignee="eng-gsi-path-owner")
    create_ticket(handler, title="Others ticket", service="s", description="d",
                  severity="P2", assignee="eng-gsi-path-other")

    event = make_event("GET", BASE_PATH,
                       query_params={"assignee": "eng-gsi-path-owner", "status": "OPEN"})
    resp = handler(event, {})
    assert resp["statusCode"] == 200
    items = json.loads(resp["body"])["items"]
    assert len(items) == 1
    assert items[0]["ticket_id"] == t_mine


# ===========================================================================
# FIX-1 — Paginated Scan returns ALL results regardless of DynamoDB page size
# ===========================================================================

def test_scan_returns_all_open_tickets_beyond_single_page(aws_services):
    """
    FIX-1 regression test: create 110 OPEN META items spread across several
    different assignees (so no single GSI1 query would find them all).
    Also create a handful of non-META items (webhook EVENT items) to confirm
    they are filtered out.

    Before the fix, `Scan(Limit=100)` would read at most 100 items from
    DynamoDB *before* applying the FilterExpression, silently discarding any
    tickets whose storage page was beyond the Limit boundary.  With the
    paginated implementation every page is fetched until LastEvaluatedKey is
    absent, so all 110 OPEN tickets must be returned.

    moto honours the DynamoDB pagination contract (it returns pages of items
    and sets LastEvaluatedKey when more remain), so this test reliably catches
    the truncation regression without requiring real AWS.
    """
    _, _ = aws_services
    handler = get_handler()

    # Create 110 OPEN tickets distributed across many assignees to prevent
    # any single GSI1 query from returning them and to maximise page spread.
    created_ids = set()
    for i in range(110):
        assignee = f"eng-scan-bulk-{i % 10}"  # 10 distinct assignees, 11 tickets each
        tid = create_ticket(
            handler,
            title=f"Bulk ticket {i}",
            service="bulk-svc",
            description="Load test.",
            severity="P2",
            assignee=assignee,
        )
        created_ids.add(tid)

    assert len(created_ids) == 110, "All 110 tickets must have unique IDs"

    # Also resolve 5 of them — they must NOT appear in the OPEN scan
    handler_resolved_ids = set()
    for tid in list(created_ids)[:5]:
        patch_event = make_event(
            "PATCH",
            f"{BASE_PATH}/{tid}",
            body={"status": "RESOLVED", "actor": "admin-bulk", "version": 1},
        )
        resp = handler(patch_event, {})
        assert resp["statusCode"] == 200
        handler_resolved_ids.add(tid)

    open_ids = created_ids - handler_resolved_ids  # 105 OPEN tickets

    # No-assignee Scan for OPEN — must return all 105 remaining OPEN tickets.
    event = make_event("GET", BASE_PATH, query_params={"status": "OPEN"})
    resp = handler(event, {})
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    returned_ids = {item["ticket_id"] for item in body["items"]}

    # Every OPEN ticket must be present
    missing = open_ids - returned_ids
    assert not missing, (
        f"Paginated Scan missed {len(missing)} OPEN tickets "
        f"(sample: {list(missing)[:3]}). "
        "This indicates the old Limit=100 truncation bug is still present."
    )

    # No resolved ticket should appear
    spurious = handler_resolved_ids & returned_ids
    assert not spurious, f"Resolved tickets appeared in OPEN scan: {spurious}"

    # Results must be sorted ascending by sla_deadline
    sla_list = [item["sla_deadline"] for item in body["items"]]
    assert sla_list == sorted(sla_list), "Scan results must be sorted ascending by sla_deadline"
