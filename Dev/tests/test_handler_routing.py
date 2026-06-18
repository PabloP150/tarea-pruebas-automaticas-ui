"""
test_handler_routing.py — Tests for handler routing, error mapping, and edge cases.

Covers:
  - 404 for unregistered paths
  - 404 for valid path but wrong method
  - 400 for malformed JSON body (F-07)
  - base64-encoded body round-trip
  - 500 returns a GENERIC message — no internal detail leaked (CRIT-01)
  - POST /api/v1/webhooks/alerts routes to ingest_alert (US-02)
"""
import base64
import json
import pytest
from unittest.mock import patch

from conftest import make_event


BASE_PATH = "/api/v1/incidents"
WEBHOOK_PATH = "/api/v1/webhooks/alerts"


def get_handler():
    from api_tickets.lambda_function import lambda_handler
    return lambda_handler


# ---------------------------------------------------------------------------
# Test: unregistered path → 404
# ---------------------------------------------------------------------------
def test_unknown_path_returns_404(aws_services):
    _, _ = aws_services
    handler = get_handler()

    event = make_event("GET", "/api/v1/nonexistent")
    resp = handler(event, {})

    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert "error" in body


# ---------------------------------------------------------------------------
# Test: valid path, wrong HTTP method → 404
# ---------------------------------------------------------------------------
def test_wrong_method_on_valid_path_returns_404(aws_services):
    _, _ = aws_services
    handler = get_handler()

    # /api/v1/incidents only accepts GET and POST at the collection level.
    # DELETE is not registered.
    event = make_event("DELETE", BASE_PATH)
    resp = handler(event, {})

    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert "error" in body


# ---------------------------------------------------------------------------
# Test: malformed JSON body → 400 (not silent empty dict, not 500)  (F-07)
# ---------------------------------------------------------------------------
def test_invalid_json_body_returns_400(aws_services):
    _, _ = aws_services
    handler = get_handler()

    # Construct a raw event with a body that is not valid JSON
    event = {
        "version": "2.0",
        "rawPath": BASE_PATH,
        "requestContext": {"http": {"method": "POST", "path": BASE_PATH}},
        "isBase64Encoded": False,
        "body": "{not valid json!!!}",
    }
    resp = handler(event, {})

    assert resp["statusCode"] == 400
    body = json.loads(resp["body"])
    assert "error" in body
    # The error message should mention JSON
    assert "json" in body["error"].lower() or "JSON" in body["error"]


# ---------------------------------------------------------------------------
# Test: base64-encoded body is correctly decoded and processed (parse_body)
# ---------------------------------------------------------------------------
def test_base64_encoded_body_is_decoded(aws_services):
    _, _ = aws_services
    handler = get_handler()

    payload = {
        "title": "Base64 ticket",
        "service": "encoder-svc",
        "description": "Body arrives base64 encoded.",
    }
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()

    event = {
        "version": "2.0",
        "rawPath": BASE_PATH,
        "requestContext": {"http": {"method": "POST", "path": BASE_PATH}},
        "isBase64Encoded": True,
        "body": encoded,
    }
    resp = handler(event, {})

    # Should be processed correctly and return 201
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert "ticket_id" in body


# ---------------------------------------------------------------------------
# Test: unhandled exception → 500 with GENERIC message, no internals leaked (CRIT-01)
# ---------------------------------------------------------------------------
def test_500_returns_generic_message_no_leak(aws_services):
    _, _ = aws_services
    handler = get_handler()

    # Patch service.create_ticket to raise an unexpected exception
    with patch("api_tickets.service.create_ticket", side_effect=RuntimeError("secret db creds: password123")):
        event = make_event(
            "POST",
            BASE_PATH,
            body={"title": "T", "service": "s", "description": "d"},
        )
        resp = handler(event, {})

    assert resp["statusCode"] == 500
    body = json.loads(resp["body"])

    # Must have an error key
    assert "error" in body

    # The internal exception message MUST NOT appear in the response
    error_text = body["error"]
    assert "secret db creds" not in error_text
    assert "password123" not in error_text
    assert "RuntimeError" not in error_text

    # The message should be the generic sentinel
    assert error_text == "Internal server error"


# ---------------------------------------------------------------------------
# Test: POST /api/v1/webhooks/alerts routes to ingest_alert  (US-02)
# ---------------------------------------------------------------------------
def test_webhook_alerts_route_reaches_ingest_alert(aws_services):
    """
    Verifies that lambda_handler correctly dispatches POST /api/v1/webhooks/alerts
    to service.ingest_alert.  A successful response (201) proves the route is wired;
    a 404 would indicate the path was swallowed by the catch-all.
    """
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        WEBHOOK_PATH,
        body={"service": "routing-test", "alert_type": "PING_TIMEOUT"},
    )
    resp = handler(event, {})

    assert resp["statusCode"] == 201, (
        f"Expected 201 from ingest_alert, got {resp['statusCode']}: {resp['body']}"
    )
    body = json.loads(resp["body"])
    assert "ticket_id" in body
    assert body["deduplicated"] is False
