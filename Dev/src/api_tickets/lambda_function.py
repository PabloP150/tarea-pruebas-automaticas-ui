"""
lambda_function.py — AWS Lambda entry point for the api-tickets slice.

Handler: lambda_handler(event, context)
Routes HTTP API v2 events to service functions by method + path.

Routes handled:
  POST   /api/v1/webhooks/alerts             → ingest_alert        (US-02)
  POST   /api/v1/incidents                   → create_ticket        (US-01)
  GET    /api/v1/incidents                   → list_dashboard
  GET    /api/v1/incidents/{id}              → get_ticket
  POST   /api/v1/incidents/{id}/comments     → add_comment
  PATCH  /api/v1/incidents/{id}              → update_status  (state machine: ACK/ESCALATED/RESOLVED)
  PATCH  /api/v1/incidents/{id}/assignee     → reassign_ticket (US-06)
"""
import logging
import os
import re

from shared import http as httputil
from shared.models import NotFoundError, ValidationError, VersionConflict
from api_tickets import service

# ---------------------------------------------------------------------------
# Logging setup (level from env LOG_LEVEL, default INFO)
# ---------------------------------------------------------------------------
logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


# ---------------------------------------------------------------------------
# Route patterns
# ---------------------------------------------------------------------------
_BASE = "/api/v1/incidents"
_WEBHOOK_ALERTS = "/api/v1/webhooks/alerts"
# _RE_ASSIGNEE must be checked BEFORE _RE_TICKET: the assignee path
# (/incidents/{id}/assignee) would also satisfy the _RE_TICKET pattern if
# evaluated first (because [^/]+ would match "{id}/assignee").
_RE_ASSIGNEE = re.compile(r"^/api/v1/incidents/([^/]+)/assignee$")
_RE_TICKET = re.compile(r"^/api/v1/incidents/([^/]+)$")
_RE_COMMENTS = re.compile(r"^/api/v1/incidents/([^/]+)/comments$")


def lambda_handler(event: dict, context) -> dict:
    """Main Lambda entry point.  Routes to service functions and translates domain errors."""
    try:
        method = httputil.get_method(event)
        raw_path = httputil.get_raw_path(event)

        logger.info("Request: %s %s", method, raw_path)

        # POST /api/v1/webhooks/alerts — ingest monitoring alert with dedup (US-02)
        # Must be matched before the /incidents routes to avoid any ambiguity.
        if method == "POST" and raw_path == _WEBHOOK_ALERTS:
            body = httputil.parse_body(event)
            result, status = service.ingest_alert(body)
            return httputil.created(result) if status == 201 else httputil.ok(result)

        # POST /api/v1/incidents — create ticket
        if method == "POST" and raw_path == _BASE:
            body = httputil.parse_body(event)
            result, status = service.create_ticket(body)
            return httputil.created(result) if status == 201 else httputil.ok(result)

        # GET /api/v1/incidents — dashboard
        if method == "GET" and raw_path == _BASE:
            query_params = httputil.get_query_params(event)
            assignee = query_params.get("assignee", "")
            status = query_params.get("status", "OPEN")
            result, _ = service.list_dashboard(assignee, status)
            return httputil.ok(result)

        # PATCH /api/v1/incidents/{id}/assignee — reassign ticket (US-06)
        # Must be evaluated BEFORE _RE_TICKET to avoid the sub-path being swallowed.
        m_assignee = _RE_ASSIGNEE.match(raw_path)
        if m_assignee and method == "PATCH":
            ticket_id = m_assignee.group(1)
            body = httputil.parse_body(event)
            result, _ = service.reassign_ticket(ticket_id, body)
            return httputil.ok(result)

        # POST /api/v1/incidents/{id}/comments
        m_comments = _RE_COMMENTS.match(raw_path)
        if m_comments and method == "POST":
            ticket_id = m_comments.group(1)
            body = httputil.parse_body(event)
            result, status = service.add_comment(ticket_id, body)
            return httputil.created(result) if status == 201 else httputil.ok(result)

        # GET /api/v1/incidents/{id} — get ticket
        m_ticket = _RE_TICKET.match(raw_path)
        if m_ticket and method == "GET":
            ticket_id = m_ticket.group(1)
            result, _ = service.get_ticket(ticket_id)
            return httputil.ok(result)

        # PATCH /api/v1/incidents/{id} — general status transition (state machine)
        if m_ticket and method == "PATCH":
            ticket_id = m_ticket.group(1)
            body = httputil.parse_body(event)
            result, _ = service.update_status(ticket_id, body)
            return httputil.ok(result)

        # 404 for unmatched routes
        logger.warning("No route matched: %s %s", method, raw_path)
        return httputil.not_found(f"No route for {method} {raw_path}")

    except ValidationError as exc:
        logger.warning("Validation error: %s", exc)
        return httputil.bad_request(str(exc))
    except NotFoundError as exc:
        logger.warning("Not found: %s", exc)
        return httputil.not_found(str(exc))
    except VersionConflict as exc:
        logger.warning("Version conflict: %s", exc)
        return httputil.conflict(str(exc))
    except Exception:
        # CRIT-01: log the full traceback to CloudWatch for diagnosis,
        # but return a GENERIC message to the client — never leak internal
        # details (stack traces, exception messages) in production responses.
        logger.exception("Unhandled exception in lambda_handler")
        return httputil.internal_error("Internal server error")
