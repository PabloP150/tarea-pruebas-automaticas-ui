"""
models.py — Domain types, SLA config, statuses, validation, and domain errors.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Final


# ---------------------------------------------------------------------------
# Field length limits  (F-08/IMP-05)
# ---------------------------------------------------------------------------

MAX_TITLE_LEN: Final[int] = 200
MAX_DESCRIPTION_LEN: Final[int] = 4000
MAX_COMMENT_LEN: Final[int] = 2000
MAX_SERVICE_LEN: Final[int] = 100
MAX_ACTOR_LEN: Final[int] = 100
MAX_FILENAME_LEN: Final[int] = 255
MAX_ALERT_TYPE_LEN: Final[int] = 100


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when request payload fails validation (maps to HTTP 400)."""
    pass


class NotFoundError(Exception):
    """Raised when a requested resource does not exist (maps to HTTP 404)."""
    pass


class VersionConflict(Exception):
    """Raised on optimistic-lock version mismatch (maps to HTTP 409)."""
    pass


# ---------------------------------------------------------------------------
# Severity and SLA
# ---------------------------------------------------------------------------

SEVERITIES: Final[tuple[str, ...]] = ("P0", "P1", "P2")
DEFAULT_SEVERITY: Final[str] = "P2"

# SLA in minutes per severity
SLA_MINUTES: Final[dict[str, int]] = {
    "P0": 15,
    "P1": 240,
    "P2": 1440,
}

DEFAULT_ASSIGNEE: Final[str] = "UNASSIGNED"


def validate_severity(severity: str) -> str:
    """Return severity if valid, otherwise raise ValidationError."""
    if severity not in SEVERITIES:
        raise ValidationError(f"Invalid severity '{severity}'. Must be one of {SEVERITIES}.")
    return severity


def compute_sla_deadline(created_at: datetime, severity: str) -> str:
    """
    Compute the SLA deadline as an ISO-8601 UTC string (trailing Z).
    created_at must be timezone-aware UTC.
    """
    minutes = SLA_MINUTES[severity]
    deadline = created_at + timedelta(minutes=minutes)
    return deadline.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

STATUSES: Final[tuple[str, ...]] = ("OPEN", "ACK", "ESCALATED", "RESOLVED")
DEFAULT_STATUS: Final[str] = "OPEN"
RESOLVED_STATUS: Final[str] = "RESOLVED"

RESOLVABLE_STATUSES: Final[tuple[str, ...]] = ("OPEN", "ACK", "ESCALATED")

# ---------------------------------------------------------------------------
# State machine: allowed transitions between statuses.
#
# OPEN is intentionally excluded as a valid target — tickets always start
# OPEN and can never be "un-acknowledged" back to OPEN by an API caller.
# RESOLVED is terminal: no outbound transitions permitted.
#
# Design note: modelling this as a dict[str, frozenset] instead of a graph
# library keeps the dependency footprint at zero (cold-start matters on Lambda)
# while remaining easy to audit, extend, or serialise for a future API.
# ---------------------------------------------------------------------------
ALLOWED_TRANSITIONS: Final[dict[str, frozenset]] = {
    "OPEN":      frozenset({"ACK", "ESCALATED", "RESOLVED"}),
    "ACK":       frozenset({"ESCALATED", "RESOLVED"}),
    "ESCALATED": frozenset({"ACK", "RESOLVED"}),
    "RESOLVED":  frozenset(),   # terminal state
}

# Valid target statuses for the PATCH endpoint (OPEN is not a valid target).
VALID_TARGET_STATUSES: Final[frozenset] = frozenset({"ACK", "ESCALATED", "RESOLVED"})


def validate_status(status: str) -> str:
    """Return status if valid, otherwise raise ValidationError."""
    if status not in STATUSES:
        raise ValidationError(f"Invalid status '{status}'. Must be one of {STATUSES}.")
    return status


# ---------------------------------------------------------------------------
# Webhook deduplication
# ---------------------------------------------------------------------------

def dedup_hash(service: str, alert_type: str) -> str:
    """
    Compute a deterministic SHA-256 dedup key for a (service, alert_type) pair.

    Normalisation rules — case-insensitive, leading/trailing whitespace stripped —
    guarantee that ("Pagos", "HTTP_503") and (" pagos ", "http_503") collide to the
    same hash, preventing spurious duplicate tickets from minor formatting differences
    in the monitoring payload.
    """
    normalised = f"{service.strip().lower()}|{alert_type.strip().lower()}"
    return hashlib.sha256(normalised.encode()).hexdigest()
