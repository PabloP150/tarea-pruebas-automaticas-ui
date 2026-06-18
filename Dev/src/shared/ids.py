"""
ids.py — ID and timestamp generation utilities.
"""
import uuid
from datetime import datetime, timezone


def ticket_id() -> str:
    """Generate a human-readable ticket ID: TKT-XXXXXXXX (8 uppercase hex chars)."""
    return "TKT-" + uuid.uuid4().hex[:8].upper()


def short_uuid8() -> str:
    """Return first 8 hex chars of a fresh uuid4 (used as tiebreaker in SK)."""
    return uuid.uuid4().hex[:8]


def new_uuid() -> str:
    """Return a full uuid4 hex string (used for ATTACH SK)."""
    return uuid.uuid4().hex


def utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)
