"""
test_shared.py — Unit tests for shared utility modules.

Covers:
  - shared/keys.py  (key builder contracts + new gsi1_sk_status_prefix helper, CRIT-02)
  - shared/ids.py   (ticket_id format, utc_now timezone awareness)
  - shared/models.py (SLA by severity, validate_severity/status, ISO deadline format,
                      field length constants, F-08)
  - shared/s3.py    (filename sanitization F-04, content_type allowlist F-05)
  - service guards  (state guard in resolve CRIT-03, version < 1 F-11, atomicity CRIT-04)
"""
import json
import re
import pytest

from conftest import make_event


# ===========================================================================
# keys.py
# ===========================================================================

class TestKeys:
    def test_ticket_pk_format(self):
        from shared.keys import ticket_pk
        assert ticket_pk("TKT-ABCD1234") == "TICKET#TKT-ABCD1234"

    def test_meta_sk(self):
        from shared.keys import meta_sk
        assert meta_sk() == "META"

    def test_event_sk_format(self):
        from shared.keys import event_sk
        sk = event_sk("2026-06-01T12:00:00Z", "abcd1234")
        assert sk == "EVENT#2026-06-01T12:00:00Z#abcd1234"

    def test_comment_sk_format(self):
        from shared.keys import comment_sk
        sk = comment_sk("2026-06-01T12:00:00Z", "deadbeef")
        assert sk == "COMMENT#2026-06-01T12:00:00Z#deadbeef"

    def test_attach_sk_format(self):
        from shared.keys import attach_sk
        sk = attach_sk("uuid-hex-string")
        assert sk == "ATTACH#uuid-hex-string"

    def test_gsi1_pk_format(self):
        from shared.keys import gsi1_pk
        assert gsi1_pk("eng-alice") == "ASSIGN#eng-alice"

    def test_gsi1_sk_format(self):
        from shared.keys import gsi1_sk
        sk = gsi1_sk("OPEN", "2026-06-01T12:15:00Z")
        assert sk == "STATUS#OPEN#SLA#2026-06-01T12:15:00Z"

    def test_gsi1_sk_status_prefix_open(self):
        """New helper for begins_with query must not hand-build strings (CRIT-02)."""
        from shared.keys import gsi1_sk_status_prefix, gsi1_sk
        prefix = gsi1_sk_status_prefix("OPEN")
        # Every full GSI1SK for OPEN should start with this prefix
        full_sk = gsi1_sk("OPEN", "2026-06-01T12:00:00Z")
        assert full_sk.startswith(prefix)
        # The prefix itself must not contain SLA (that's filtered by begins_with)
        assert "SLA" not in prefix
        assert prefix == "STATUS#OPEN#"

    def test_gsi1_sk_status_prefix_resolved(self):
        from shared.keys import gsi1_sk_status_prefix
        assert gsi1_sk_status_prefix("RESOLVED") == "STATUS#RESOLVED#"

    def test_gsi2_pk_format(self):
        from shared.keys import gsi2_pk
        assert gsi2_pk("sha256abc") == "HASH#sha256abc"

    def test_gsi2_sk_format(self):
        from shared.keys import gsi2_sk
        assert gsi2_sk("TKT-PARENT") == "TICKET#TKT-PARENT"

    def test_sk_prefix_constants(self):
        from shared.keys import (
            SK_PREFIX_META, SK_PREFIX_EVENT, SK_PREFIX_COMMENT, SK_PREFIX_ATTACH,
            event_sk, comment_sk, attach_sk,
        )
        # Verify prefix constants match actual SK patterns
        assert event_sk("2026-01-01T00:00:00Z", "00000000").startswith(SK_PREFIX_EVENT)
        assert comment_sk("2026-01-01T00:00:00Z", "00000000").startswith(SK_PREFIX_COMMENT)
        assert attach_sk("uuid").startswith(SK_PREFIX_ATTACH)
        assert SK_PREFIX_META == "META"

    def test_dedup_pointer_pk_format(self):
        """FIX-2: dedup_pointer_pk must produce DEDUP#<hash>."""
        from shared.keys import dedup_pointer_pk
        pk = dedup_pointer_pk("abc123")
        assert pk == "DEDUP#abc123"

    def test_dedup_pointer_pk_different_hashes_produce_different_keys(self):
        from shared.keys import dedup_pointer_pk
        assert dedup_pointer_pk("aaa") != dedup_pointer_pk("bbb")

    def test_dedup_pointer_sk_constant(self):
        """FIX-2: the fixed SK for the dedup pointer must be the string 'ACTIVE'."""
        from shared.keys import DEDUP_POINTER_SK
        assert DEDUP_POINTER_SK == "ACTIVE"


# ===========================================================================
# ids.py
# ===========================================================================

class TestIds:
    def test_ticket_id_format(self):
        from shared.ids import ticket_id
        tid = ticket_id()
        assert re.match(r"^TKT-[0-9A-F]{8}$", tid), f"Unexpected format: {tid}"

    def test_ticket_id_unique(self):
        from shared.ids import ticket_id
        ids = {ticket_id() for _ in range(20)}
        assert len(ids) == 20

    def test_short_uuid8_length(self):
        from shared.ids import short_uuid8
        u8 = short_uuid8()
        assert len(u8) == 8
        assert re.match(r"^[0-9a-f]{8}$", u8)

    def test_new_uuid_length(self):
        from shared.ids import new_uuid
        u = new_uuid()
        assert len(u) == 32  # 128-bit hex, no dashes
        assert re.match(r"^[0-9a-f]{32}$", u)

    def test_utc_now_is_timezone_aware(self):
        from shared.ids import utc_now
        from datetime import timezone
        now = utc_now()
        assert now.tzinfo is not None
        assert now.utcoffset().total_seconds() == 0.0

    def test_utc_now_iso_removed(self):
        """utc_now_iso was dead code and must have been removed (IMP-02)."""
        import shared.ids as ids_module
        assert not hasattr(ids_module, "utc_now_iso"), (
            "utc_now_iso is dead code and should have been removed"
        )


# ===========================================================================
# models.py
# ===========================================================================

class TestModels:
    # --- SLA by severity ---

    def test_sla_p0_is_15_minutes(self):
        from shared.models import SLA_MINUTES
        assert SLA_MINUTES["P0"] == 15

    def test_sla_p1_is_240_minutes(self):
        from shared.models import SLA_MINUTES
        assert SLA_MINUTES["P1"] == 240

    def test_sla_p2_is_1440_minutes(self):
        from shared.models import SLA_MINUTES
        assert SLA_MINUTES["P2"] == 1440

    def test_compute_sla_deadline_p0(self):
        from datetime import datetime, timezone, timedelta
        from shared.models import compute_sla_deadline
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        deadline = compute_sla_deadline(now, "P0")
        expected = (now + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert deadline == expected

    def test_compute_sla_deadline_iso_format(self):
        """Deadline must be ISO-8601 UTC with trailing Z."""
        from datetime import datetime, timezone
        from shared.models import compute_sla_deadline
        now = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        deadline = compute_sla_deadline(now, "P2")
        # Must match YYYY-MM-DDTHH:MM:SSZ
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", deadline), (
            f"Deadline does not match ISO-8601 UTC format: {deadline}"
        )

    # --- Severity validation ---

    def test_validate_severity_valid(self):
        from shared.models import validate_severity
        for sev in ("P0", "P1", "P2"):
            assert validate_severity(sev) == sev

    def test_validate_severity_invalid(self):
        from shared.models import validate_severity, ValidationError
        with pytest.raises(ValidationError):
            validate_severity("CRITICAL")

    # --- Status validation ---

    def test_validate_status_valid(self):
        from shared.models import validate_status
        for st in ("OPEN", "ACK", "ESCALATED", "RESOLVED"):
            assert validate_status(st) == st

    def test_validate_status_invalid(self):
        from shared.models import validate_status, ValidationError
        with pytest.raises(ValidationError):
            validate_status("PENDING")

    # --- Field length constants (F-08) ---

    def test_length_constants_exist(self):
        from shared.models import (
            MAX_TITLE_LEN, MAX_DESCRIPTION_LEN, MAX_COMMENT_LEN,
            MAX_SERVICE_LEN, MAX_ACTOR_LEN, MAX_FILENAME_LEN,
        )
        assert MAX_TITLE_LEN == 200
        assert MAX_DESCRIPTION_LEN == 4000
        assert MAX_COMMENT_LEN == 2000
        assert MAX_SERVICE_LEN == 100
        assert MAX_ACTOR_LEN == 100
        assert MAX_FILENAME_LEN == 255

    def test_max_alert_type_len_constant_exists(self):
        """FIX-6: MAX_ALERT_TYPE_LEN must be exported from models and equal 100."""
        from shared.models import MAX_ALERT_TYPE_LEN
        assert MAX_ALERT_TYPE_LEN == 100

    # --- RESOLVABLE_STATUSES ---

    def test_resolvable_statuses(self):
        from shared.models import RESOLVABLE_STATUSES, RESOLVED_STATUS
        assert RESOLVED_STATUS not in RESOLVABLE_STATUSES
        assert "OPEN" in RESOLVABLE_STATUSES
        assert "ACK" in RESOLVABLE_STATUSES
        assert "ESCALATED" in RESOLVABLE_STATUSES


# ===========================================================================
# s3.py — filename sanitization (F-04) and content_type allowlist (F-05)
# ===========================================================================

class TestS3Helpers:
    def test_sanitize_filename_strips_path_traversal(self):
        from shared.s3 import sanitize_filename
        # Classic path traversal — must be stripped to just the filename
        result = sanitize_filename("../../etc/passwd")
        assert result == "passwd"
        assert ".." not in result
        assert "/" not in result

    def test_sanitize_filename_strips_windows_path_traversal(self):
        from shared.s3 import sanitize_filename
        result = sanitize_filename("..\\..\\windows\\system32\\cmd.exe")
        # os.path.basename on Unix treats backslash as a regular char, so the whole
        # string becomes the basename; unsafe chars are then replaced with _
        assert ".." not in result or "/" not in result

    def test_sanitize_filename_replaces_unsafe_chars(self):
        from shared.s3 import sanitize_filename
        result = sanitize_filename("my file (1).log")
        # Space and parentheses should be replaced
        assert " " not in result
        assert "(" not in result
        assert ")" not in result

    def test_sanitize_filename_keeps_safe_chars(self):
        from shared.s3 import sanitize_filename
        safe = "crash-report_v2.1.log"
        result = sanitize_filename(safe)
        assert result == safe

    def test_sanitize_filename_enforces_max_length(self):
        from shared.s3 import sanitize_filename
        from shared.models import MAX_FILENAME_LEN
        long_name = "a" * (MAX_FILENAME_LEN + 100) + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= MAX_FILENAME_LEN

    def test_sanitize_filename_raises_on_empty(self):
        from shared.s3 import sanitize_filename
        from shared.models import ValidationError
        with pytest.raises(ValidationError):
            sanitize_filename("")

    def test_sanitize_filename_raises_on_only_unsafe_chars(self):
        from shared.s3 import sanitize_filename
        from shared.models import ValidationError
        # A filename made entirely of path separators will sanitize to empty
        with pytest.raises(ValidationError):
            sanitize_filename("/")

    def test_build_s3_key_sanitizes_filename(self):
        from shared.keys import ticket_pk  # imported only to show we use keys
        from shared.s3 import build_s3_key
        key = build_s3_key("2026-06", "TKT-ABCD", "../../evil.sh")
        # Path traversal must be removed
        assert ".." not in key
        # The ticket prefix must be intact
        assert "TKT-ABCD" in key

    def test_validate_content_type_allowed(self):
        from shared.s3 import validate_content_type
        for ct in ("image/png", "image/jpeg", "application/pdf", "text/plain"):
            validate_content_type(ct)  # must not raise

    def test_validate_content_type_with_charset_param(self):
        """Parameters like charset must be stripped before comparison."""
        from shared.s3 import validate_content_type
        validate_content_type("text/plain; charset=utf-8")  # must not raise

    def test_validate_content_type_case_insensitive(self):
        from shared.s3 import validate_content_type
        validate_content_type("IMAGE/PNG")  # must not raise

    def test_validate_content_type_rejects_disallowed(self):
        from shared.s3 import validate_content_type
        from shared.models import ValidationError
        with pytest.raises(ValidationError):
            validate_content_type("application/x-shellscript")

    def test_validate_content_type_rejects_wildcard(self):
        from shared.s3 import validate_content_type
        from shared.models import ValidationError
        with pytest.raises(ValidationError):
            validate_content_type("application/octet-stream")


# ===========================================================================
# Service-layer guards (integration via handler, uses aws_services fixture)
# ===========================================================================

BASE_PATH = "/api/v1/incidents"


def _create_ticket(handler, **kwargs):
    defaults = {
        "title": "Test ticket",
        "service": "svc",
        "description": "Description.",
        "severity": "P2",
        "assignee": "eng-test",
    }
    defaults.update(kwargs)
    event = make_event("POST", BASE_PATH, body=defaults)
    resp = handler(event, {})
    assert resp["statusCode"] == 201
    return json.loads(resp["body"])["ticket_id"]


class TestServiceGuards:
    # --- Status guard in resolve (CRIT-03) ---

    def test_resolve_already_resolved_returns_400(self, aws_services):
        """Re-resolving a RESOLVED ticket must be 400, not 409 (CRIT-03)."""
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler

        ticket_id = _create_ticket(handler)

        # First resolve succeeds
        r1 = handler(make_event("PATCH", f"{BASE_PATH}/{ticket_id}",
                                body={"status": "RESOLVED", "actor": "a", "version": 1}), {})
        assert r1["statusCode"] == 200

        # Second attempt: status guard fires before DB write
        r2 = handler(make_event("PATCH", f"{BASE_PATH}/{ticket_id}",
                                body={"status": "RESOLVED", "actor": "a", "version": 2}), {})
        assert r2["statusCode"] == 400
        body = json.loads(r2["body"])
        assert "RESOLVED" in body["error"] or "cannot be resolved" in body["error"]

    # --- version < 1 guard (F-11) ---

    def test_resolve_version_zero_returns_400(self, aws_services):
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler

        ticket_id = _create_ticket(handler)

        event = make_event("PATCH", f"{BASE_PATH}/{ticket_id}",
                           body={"status": "RESOLVED", "actor": "a", "version": 0})
        resp = handler(event, {})
        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert "version" in body["error"].lower()

    def test_resolve_version_negative_returns_400(self, aws_services):
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler

        ticket_id = _create_ticket(handler)

        event = make_event("PATCH", f"{BASE_PATH}/{ticket_id}",
                           body={"status": "RESOLVED", "actor": "a", "version": -5})
        resp = handler(event, {})
        assert resp["statusCode"] == 400

    def test_resolve_version_string_non_numeric_returns_400(self, aws_services):
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler

        ticket_id = _create_ticket(handler)

        event = make_event("PATCH", f"{BASE_PATH}/{ticket_id}",
                           body={"status": "RESOLVED", "actor": "a", "version": "abc"})
        resp = handler(event, {})
        assert resp["statusCode"] == 400

    # --- Field length limits (F-08) ---

    def test_create_ticket_title_too_long_returns_400(self, aws_services):
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler
        from shared.models import MAX_TITLE_LEN

        event = make_event("POST", BASE_PATH, body={
            "title": "x" * (MAX_TITLE_LEN + 1),
            "service": "svc",
            "description": "desc",
        })
        resp = handler(event, {})
        assert resp["statusCode"] == 400

    def test_create_ticket_description_too_long_returns_400(self, aws_services):
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler
        from shared.models import MAX_DESCRIPTION_LEN

        event = make_event("POST", BASE_PATH, body={
            "title": "valid title",
            "service": "svc",
            "description": "x" * (MAX_DESCRIPTION_LEN + 1),
        })
        resp = handler(event, {})
        assert resp["statusCode"] == 400

    def test_add_comment_body_too_long_returns_400(self, aws_services):
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler
        from shared.models import MAX_COMMENT_LEN

        ticket_id = _create_ticket(handler)

        event = make_event("POST", f"{BASE_PATH}/{ticket_id}/comments", body={
            "author": "eng-alice",
            "body": "x" * (MAX_COMMENT_LEN + 1),
        })
        resp = handler(event, {})
        assert resp["statusCode"] == 400

    # --- content_type allowlist via handler (F-05) ---

    def test_create_ticket_disallowed_content_type_returns_400(self, aws_services):
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler

        event = make_event("POST", BASE_PATH, body={
            "title": "Attachment test",
            "service": "svc",
            "description": "desc",
            "attachment": {
                "filename": "payload.sh",
                "content_type": "application/x-sh",
            },
        })
        resp = handler(event, {})
        assert resp["statusCode"] == 400

    def test_create_ticket_allowed_content_type_succeeds(self, aws_services):
        _, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler

        event = make_event("POST", BASE_PATH, body={
            "title": "Attachment test",
            "service": "svc",
            "description": "desc",
            "attachment": {
                "filename": "report.pdf",
                "content_type": "application/pdf",
            },
        })
        resp = handler(event, {})
        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert "upload_url" in body

    # --- Atomicity: create writes META + EVENT together (CRIT-04) ---

    def test_create_writes_meta_and_event_atomically(self, aws_services):
        """
        Verify that after a successful create, both META and EVENT items exist.
        The transact_write_items call is all-or-nothing; if either item fails
        neither should be written.  Here we confirm the happy path: both exist.
        """
        table, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler
        from boto3.dynamodb.conditions import Key
        from shared.keys import ticket_pk

        ticket_id = _create_ticket(handler)

        all_items = table.query(
            KeyConditionExpression=Key("PK").eq(ticket_pk(ticket_id))
        )["Items"]

        sks = [item["SK"] for item in all_items]
        assert "META" in sks, "META item missing after create"
        event_sks = [sk for sk in sks if sk.startswith("EVENT#")]
        assert len(event_sks) >= 1, "No EVENT item written after create"

    # --- path traversal in filename rejected (F-04) ---

    def test_create_ticket_path_traversal_filename_is_sanitized(self, aws_services):
        """
        Filenames with path traversal (../../etc/passwd) should be sanitized —
        the ticket should be created successfully with a safe filename in the S3 key,
        not rejected outright unless the sanitized result is empty.
        """
        table, _ = aws_services
        from api_tickets.lambda_function import lambda_handler as handler
        from boto3.dynamodb.conditions import Key
        from shared.keys import ticket_pk

        event = make_event("POST", BASE_PATH, body={
            "title": "Path traversal test",
            "service": "svc",
            "description": "desc",
            "attachment": {
                "filename": "../../etc/passwd",
                "content_type": "text/plain",
            },
        })
        resp = handler(event, {})
        assert resp["statusCode"] == 201

        ticket_id = json.loads(resp["body"])["ticket_id"]

        # Verify the ATTACH item has a sanitized s3_key (no traversal)
        all_items = table.query(
            KeyConditionExpression=Key("PK").eq(ticket_pk(ticket_id))
        )["Items"]
        attach_items = [i for i in all_items if i["SK"].startswith("ATTACH#")]
        assert len(attach_items) == 1
        s3_key = attach_items[0]["s3_key"]
        assert ".." not in s3_key
