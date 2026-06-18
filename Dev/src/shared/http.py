"""
http.py — HTTP API v2 event parsing and JSON response helpers.
"""
import base64
import json
import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


class _DecimalEncoder(json.JSONEncoder):
    """Convert DynamoDB Decimal values to int or float for JSON serialisation."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            # Preserve integer representation when there is no fractional part
            if obj % 1 == 0:
                return int(obj)
            return float(obj)
        return super().default(obj)


# ---------------------------------------------------------------------------
# Event parsing
# ---------------------------------------------------------------------------

def get_method(event: dict) -> str:
    """Extract HTTP method from HTTP API v2 event."""
    return event["requestContext"]["http"]["method"].upper()


def get_raw_path(event: dict) -> str:
    """Extract rawPath from HTTP API v2 event."""
    return event.get("rawPath", event.get("path", ""))


def get_path_params(event: dict) -> dict[str, str]:
    """Extract path parameters (may be absent)."""
    return event.get("pathParameters") or {}


def get_query_params(event: dict) -> dict[str, str]:
    """Extract query string parameters (may be absent)."""
    return event.get("queryStringParameters") or {}


def parse_body(event: dict) -> dict[str, Any]:
    """
    Parse the JSON body from an HTTP API v2 event.
    Handles base64-encoded bodies (isBase64Encoded flag).

    Returns empty dict if the body field is absent (valid for GET requests).
    Raises ValidationError if the body is present but is not valid JSON (F-07):
    silently swallowing malformed JSON would hide client errors and make
    debugging extremely difficult in production.
    """
    # Import here to avoid circular dependency at module load time.
    from shared.models import ValidationError as _ValidationError

    raw = event.get("body")
    if not raw:
        return {}
    if event.get("isBase64Encoded", False):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse request body: %s", exc)
        raise _ValidationError("Request body is not valid JSON.")


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

def _json_response(status_code: int, body: Any) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, cls=_DecimalEncoder),
    }


def ok(body: Any) -> dict:
    return _json_response(200, body)


def created(body: Any) -> dict:
    return _json_response(201, body)


def bad_request(message: str) -> dict:
    return _json_response(400, {"error": message})


def not_found(message: str = "Not found") -> dict:
    return _json_response(404, {"error": message})


def conflict(message: str = "Version conflict") -> dict:
    return _json_response(409, {"error": message})


def internal_error(message: str = "Internal server error") -> dict:
    return _json_response(500, {"error": message})
