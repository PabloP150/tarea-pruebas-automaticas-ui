"""
test_attachment_download.py — Tests for presigned GET URL on attachments (Cambio 1).

Verifies:
  - get_ticket assembles download_url for each attachment (presigned GET).
  - s3_key is NOT present in any attachment returned by get_ticket.
  - download_url is a non-empty string containing the S3 key path.
  - filename, content_type, size are all present.
  - A ticket with no attachments returns an empty list (regression guard).
"""
import json
import pytest
from conftest import make_event


BASE_PATH = "/api/v1/incidents"


def get_handler():
    from api_tickets.lambda_function import lambda_handler
    return lambda_handler


def create_ticket_with_attachment(handler, filename="screenshot.png", content_type="image/png"):
    """Helper: create a ticket with one attachment; return (ticket_id, upload_url)."""
    event = make_event(
        "POST",
        BASE_PATH,
        body={
            "title": "Need screenshot",
            "service": "ui-service",
            "description": "Attaching a screenshot of the error.",
            "severity": "P2",
            "assignee": "eng-dl",
            "attachment": {"filename": filename, "content_type": content_type},
        },
    )
    resp = handler(event, {})
    assert resp["statusCode"] == 201, f"create_ticket failed: {resp['body']}"
    body = json.loads(resp["body"])
    return body["ticket_id"], body.get("upload_url")


# ---------------------------------------------------------------------------
# Core: download_url is present, s3_key is absent
# ---------------------------------------------------------------------------

def test_attachment_has_download_url(aws_services):
    """
    get_ticket must include a presigned download_url for each attachment.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id, _ = create_ticket_with_attachment(handler)

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(event, {})
    assert resp["statusCode"] == 200

    body = json.loads(resp["body"])
    attachments = body["attachments"]
    assert len(attachments) == 1

    att = attachments[0]
    assert "download_url" in att, "attachment must contain 'download_url'"
    assert isinstance(att["download_url"], str)
    assert len(att["download_url"]) > 0


def test_attachment_does_not_expose_s3_key(aws_services):
    """
    The internal s3_key MUST NOT be present in the attachment returned by get_ticket.
    Leaking the bucket key path would expose internal storage structure (F-05).
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id, _ = create_ticket_with_attachment(handler)

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(event, {})
    body = json.loads(resp["body"])

    att = body["attachments"][0]
    assert "s3_key" not in att, "s3_key must NOT be exposed in attachment response"


def test_attachment_download_url_contains_filename(aws_services):
    """
    The presigned GET URL must contain the sanitised filename (embedded in the S3 key).
    This verifies the URL is scoped to the correct object.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id, _ = create_ticket_with_attachment(handler, filename="crash_report.pdf",
                                                  content_type="application/pdf")

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(event, {})
    body = json.loads(resp["body"])

    att = body["attachments"][0]
    # The presigned URL embeds the S3 key in the path or query string
    assert "crash_report.pdf" in att["download_url"], (
        f"Expected filename in download_url, got: {att['download_url']}"
    )


# ---------------------------------------------------------------------------
# Attachment fields: filename, content_type, size present
# ---------------------------------------------------------------------------

def test_attachment_has_required_fields(aws_services):
    """
    Attachment response must contain: filename, content_type, size, download_url.
    """
    _, _ = aws_services
    handler = get_handler()

    ticket_id, _ = create_ticket_with_attachment(handler, filename="log.txt",
                                                  content_type="text/plain")

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(event, {})
    body = json.loads(resp["body"])

    att = body["attachments"][0]
    for field in ("filename", "content_type", "size", "download_url"):
        assert field in att, f"attachment missing field '{field}'"

    assert att["filename"] == "log.txt"
    assert att["content_type"] == "text/plain"
    assert att["size"] == 0  # size is 0 at creation time (upload not completed yet)


# ---------------------------------------------------------------------------
# Regression: no attachments → empty list
# ---------------------------------------------------------------------------

def test_no_attachments_returns_empty_list(aws_services):
    """
    A ticket created without an attachment must return attachments=[].
    This is a regression guard to ensure the _build_attachment refactor
    did not break the no-attachment path.
    """
    _, _ = aws_services
    handler = get_handler()

    event = make_event(
        "POST",
        BASE_PATH,
        body={
            "title": "No attachment ticket",
            "service": "core",
            "description": "Nothing attached.",
        },
    )
    resp = handler(event, {})
    ticket_id = json.loads(resp["body"])["ticket_id"]

    event = make_event("GET", f"{BASE_PATH}/{ticket_id}")
    resp = handler(event, {})
    body = json.loads(resp["body"])

    assert body["attachments"] == [], "Expected empty attachments list"


# ---------------------------------------------------------------------------
# s3.generate_presigned_get_url unit test
# ---------------------------------------------------------------------------

def test_generate_presigned_get_url_returns_string(aws_services):
    """
    Unit test for s3.generate_presigned_get_url: must return a non-empty string
    that contains the bucket name or the key.
    """
    _, s3_client = aws_services
    from shared import s3 as s3_module

    # Put a dummy object so the key exists (not strictly required for presigned URLs)
    import os
    bucket = os.environ["ATTACHMENTS_BUCKET"]
    s3_client.put_object(Bucket=bucket, Key="attachments/2026-06/test.txt", Body=b"x")

    url = s3_module.generate_presigned_get_url("attachments/2026-06/test.txt", expires=60)

    assert isinstance(url, str)
    assert len(url) > 0
    # moto presigned URLs contain the key in the path
    assert "test.txt" in url
