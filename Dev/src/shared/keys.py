"""
keys.py — Single source of truth for all DynamoDB key construction.

All PK/SK/GSI key strings for the single-table design MUST be built here.
No other module may hand-construct strings like 'TICKET#...' directly.
"""


# ---------------------------------------------------------------------------
# Primary key builders
# ---------------------------------------------------------------------------

def ticket_pk(ticket_id: str) -> str:
    """PK for all items belonging to a ticket."""
    return f"TICKET#{ticket_id}"


def meta_sk() -> str:
    """SK for the Ticket META item."""
    return "META"


def event_sk(ts_iso: str, u8: str) -> str:
    """SK for an audit EVENT item.  ts_iso should be ISO-8601 UTC, u8 first-8 hex of uuid4."""
    return f"EVENT#{ts_iso}#{u8}"


def comment_sk(ts_iso: str, u8: str) -> str:
    """SK for a COMMENT item."""
    return f"COMMENT#{ts_iso}#{u8}"


def attach_sk(uuid_str: str) -> str:
    """SK for an ATTACH (S3 reference) item."""
    return f"ATTACH#{uuid_str}"


# ---------------------------------------------------------------------------
# GSI1 key builders  (META items only)
# ---------------------------------------------------------------------------

def gsi1_pk(assignee: str) -> str:
    """GSI1PK = ASSIGN#<assignee>"""
    return f"ASSIGN#{assignee}"


def gsi1_sk(status: str, sla_iso: str) -> str:
    """GSI1SK = STATUS#<status>#SLA#<sla_iso>"""
    return f"STATUS#{status}#SLA#{sla_iso}"


def gsi1_sk_status_prefix(status: str) -> str:
    """
    begins_with prefix for GSI1SK filtered by status.
    Used in dashboard queries: begins_with(GSI1SK, "STATUS#<status>#").
    """
    return f"STATUS#{status}#"


# ---------------------------------------------------------------------------
# GSI2 key builders  (used by webhook-ingesta, provided here for completeness)
# ---------------------------------------------------------------------------

def gsi2_pk(hash_value: str) -> str:
    """GSI2PK = HASH#<sha>"""
    return f"HASH#{hash_value}"


def gsi2_sk(parent_ticket_id: str) -> str:
    """GSI2SK = TICKET#<parentId>"""
    return f"TICKET#{parent_ticket_id}"


# ---------------------------------------------------------------------------
# Dedup pointer key builders  (FIX-2: deterministic race-free dedup)
# ---------------------------------------------------------------------------

def dedup_pointer_pk(hash_value: str) -> str:
    """PK for the dedup pointer item that tracks the active parent per hash.

    The dedup pointer is a lightweight sentinel written atomically with the
    first ticket that owns a given (service, alert_type) hash.  Its presence
    is the authoritative, strongly-consistent signal that an active parent
    exists — no GSI read required for the race-critical path.

    PK = DEDUP#<sha256hex>
    """
    return f"DEDUP#{hash_value}"


# Fixed SK for the dedup pointer — there is exactly one pointer per hash.
DEDUP_POINTER_SK: str = "ACTIVE"


# ---------------------------------------------------------------------------
# SK prefix constants (for begins_with queries and item classification)
# ---------------------------------------------------------------------------

SK_PREFIX_META = "META"
SK_PREFIX_EVENT = "EVENT#"
SK_PREFIX_COMMENT = "COMMENT#"
SK_PREFIX_ATTACH = "ATTACH#"
