"""
service.py — Business logic for the api-tickets slice.

Functions:
  create_ticket(body)               → (response_body, http_status_code)
  list_dashboard(assignee, status)  → (response_body, http_status_code)
  get_ticket(ticket_id)             → (response_body, http_status_code)
  add_comment(ticket_id, body)      → (response_body, http_status_code)
  update_status(ticket_id, body)    → (response_body, http_status_code)
  resolve_ticket(ticket_id, body)   → thin wrapper around update_status (backward compat)
  ingest_alert(body)                → (response_body, http_status_code)
"""
import logging
import os
import re

from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeSerializer

from shared import ddb, ids, keys, models, s3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton for DynamoDB type serialization (FIX-6).
# Instantiating TypeSerializer on every _serialize() call added measurable
# overhead on warm-path transactions.  A single instance at module scope is
# thread-safe (no mutable state) and reused across all calls in the same
# Lambda execution context.
# ---------------------------------------------------------------------------
_SERIALIZER = TypeSerializer()

# Regex for sanitizing the 'source' field (FIX-4).
# Keeps: alphanumeric, space, hyphen, underscore, period.  Everything else is removed.
_SOURCE_SAFE_RE = re.compile(r"[^\w\s.\-]")

# ---------------------------------------------------------------------------
# Create ticket  (US-01)
# ---------------------------------------------------------------------------

def create_ticket(body: dict) -> tuple[dict, int]:
    """
    Create a new ticket.

    Writes META + EVENT(CREATED) + optional ATTACH atomically via
    transact_write_items (CRIT-04: all-or-nothing, no partial writes).

    If attachment is requested: writes ATTACH item and returns presigned PUT URL.

    Returns (response_body, http_status_code).
    """
    # --- Validate required fields ---
    title = body.get("title")
    service_name = body.get("service")
    description = body.get("description")

    if not title:
        raise models.ValidationError("'title' is required.")
    if not service_name:
        raise models.ValidationError("'service' is required.")
    if not description:
        raise models.ValidationError("'description' is required.")

    # --- Field length limits (F-08) ---
    if len(title) > models.MAX_TITLE_LEN:
        raise models.ValidationError(
            f"'title' exceeds maximum length of {models.MAX_TITLE_LEN} characters."
        )
    if len(description) > models.MAX_DESCRIPTION_LEN:
        raise models.ValidationError(
            f"'description' exceeds maximum length of {models.MAX_DESCRIPTION_LEN} characters."
        )
    if len(service_name) > models.MAX_SERVICE_LEN:
        raise models.ValidationError(
            f"'service' exceeds maximum length of {models.MAX_SERVICE_LEN} characters."
        )

    # --- Severity: default P2, validate ---
    severity = body.get("severity", models.DEFAULT_SEVERITY)
    models.validate_severity(severity)

    # --- Assignee: default UNASSIGNED ---
    assignee = body.get("assignee", models.DEFAULT_ASSIGNEE)
    if len(assignee) > models.MAX_ACTOR_LEN:
        raise models.ValidationError(
            f"'assignee' exceeds maximum length of {models.MAX_ACTOR_LEN} characters."
        )

    # --- Generate IDs and timestamps ---
    ticket = ids.ticket_id()
    now = ids.utc_now()
    created_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    sla_deadline = models.compute_sla_deadline(now, severity)

    # --- Build keys ---
    pk = keys.ticket_pk(ticket)
    meta_sk = keys.meta_sk()

    # --- Attachment handling (F-04, F-05) ---
    attachment_payload = body.get("attachment")
    attachments_count = 0
    upload_url = None
    attach_item = None

    if attachment_payload:
        filename = attachment_payload.get("filename")
        content_type = attachment_payload.get("content_type")
        if not filename or not content_type:
            raise models.ValidationError(
                "attachment requires both 'filename' and 'content_type'."
            )
        # Validate content_type against allowlist before generating presigned URL (F-05)
        s3.validate_content_type(content_type)

        year_month = now.strftime("%Y-%m")
        # build_s3_key calls sanitize_filename internally (F-04)
        s3_key = s3.build_s3_key(year_month, ticket, filename)
        # Pass content_type to lock the presigned URL to that type (F-05)
        upload_url = s3.generate_presigned_put_url(s3_key, content_type)

        attach_uuid = ids.new_uuid()
        attach_item = {
            "PK": pk,
            "SK": keys.attach_sk(attach_uuid),
            "s3_key": s3_key,
            "filename": filename,
            "content_type": content_type,
            "size": 0,
        }
        attachments_count = 1

    # --- Build META item ---
    meta_item = {
        "PK": pk,
        "SK": meta_sk,
        "GSI1PK": keys.gsi1_pk(assignee),
        "GSI1SK": keys.gsi1_sk(models.DEFAULT_STATUS, sla_deadline),
        "ticket_id": ticket,
        "title": title,
        "service": service_name,
        "description": description,
        "severity": severity,
        "status": models.DEFAULT_STATUS,
        "assignee": assignee,
        "sla_deadline": sla_deadline,
        "created_at": created_at,
        "updated_at": created_at,
        "version": 1,
        "attachments_count": attachments_count,
    }

    # --- Build EVENT(CREATED) item ---
    event_u8 = ids.short_uuid8()
    event_item = {
        "PK": pk,
        "SK": keys.event_sk(created_at, event_u8),
        "event_type": "CREATED",
        "actor": assignee,
        "action": "Ticket created",
        "payload": {"severity": severity, "title": title},
        "created_at": created_at,
    }

    # --- Write to DynamoDB atomically (CRIT-04) ---
    # transact_write_items guarantees META + EVENT (+ optional ATTACH) are written
    # together or not at all — no half-created tickets.
    table_name = os.environ["TABLE_NAME"]
    client = ddb.get_client()

    transact_items = [
        {"Put": {"TableName": table_name, "Item": _serialize(meta_item)}},
        {"Put": {"TableName": table_name, "Item": _serialize(event_item)}},
    ]
    if attach_item:
        transact_items.append(
            {"Put": {"TableName": table_name, "Item": _serialize(attach_item)}}
        )

    client.transact_write_items(TransactItems=transact_items)

    logger.info("Created ticket %s (severity=%s, assignee=%s)", ticket, severity, assignee)

    # --- Build response ---
    response: dict = {
        "ticket_id": ticket,
        "status": models.DEFAULT_STATUS,
        "sla_deadline": sla_deadline,
    }
    if upload_url:
        response["upload_url"] = upload_url

    return response, 201


# ---------------------------------------------------------------------------
# Dashboard  (US-03, PA-2)
# ---------------------------------------------------------------------------

def list_dashboard(assignee: str, status: str = models.DEFAULT_STATUS) -> tuple[dict, int]:
    """
    Return tickets filtered by status, optionally scoped to a single assignee.

    With assignee (non-empty string):
      Query GSI1 (ASSIGN#<assignee> / STATUS#<s>#SLA#<t>) — O(result set),
      no table scan.  Sorted ascending by SLA deadline via GSI1SK lexicographic
      order.  Limit 50.

    Without assignee (empty string or absent):
      Paginated Scan with FilterExpression SK=META AND status=<s>.
      Iterates all DynamoDB pages using ExclusiveStartKey until
      LastEvaluatedKey is absent, accumulating only items that match the
      filter.  Hard safety cap: _SCAN_MAX_PAGES / _SCAN_MAX_ITEMS prevents
      runaway consumption on pathologically large tables.

      Production trade-off: DynamoDB Scan reads every page sequentially and
      charges RCU for every item scanned, not just filtered results.  At high
      scale (>100k tickets) this will be slow and expensive.  A proper
      multi-tenant "pending queue" would use a dedicated GSI keyed on status
      (e.g. GSI3PK=STATUS#<s> / GSI3SK=SLA#<t>) with no assignee in the key,
      enabling efficient KeyConditionExpression queries.  That GSI is deferred
      to E5 when the volume justifies the cost; for academic scope the paginated
      Scan is acceptable.

      NOTE: DynamoDB's Limit parameter on Scan restricts the number of items
      READ (before filter evaluation), NOT the number returned.  Passing
      Limit=N on a filtered Scan silently truncates results whenever the
      filter selectivity is low.  We therefore omit the per-page Limit and
      rely solely on the safety caps below to bound execution.
    """
    # Safety caps for the no-assignee full-table Scan to prevent runaway cost.
    # At 100 items/page (DynamoDB default) and 20 pages this covers 2000 results.
    # Increase _SCAN_MAX_PAGES in a future iteration when a proper status-GSI
    # (E5) is added and the Scan path is removed.
    _SCAN_MAX_PAGES: int = 20
    _SCAN_MAX_ITEMS: int = 2000

    models.validate_status(status)

    table = ddb.get_table()

    if assignee:
        # Fast path: GSI1 query scoped to a single engineer
        response = table.query(
            IndexName="GSI1",
            KeyConditionExpression=(
                Key("GSI1PK").eq(keys.gsi1_pk(assignee))
                & Key("GSI1SK").begins_with(keys.gsi1_sk_status_prefix(status))
            ),
            ScanIndexForward=True,
            Limit=50,
        )
        raw_items = response.get("Items", [])
    else:
        # Slow path: paginated full-table Scan.
        # We iterate pages manually with ExclusiveStartKey so that every item
        # matching the FilterExpression is retrieved, regardless of how many
        # non-matching items DynamoDB must read per page to fill its internal
        # page buffer.
        filter_expr = (
            Attr("SK").eq(keys.SK_PREFIX_META)
            & Attr("status").eq(status)
        )
        raw_items: list = []
        scan_kwargs: dict = {"FilterExpression": filter_expr}
        pages_read = 0

        while True:
            response = table.scan(**scan_kwargs)
            raw_items.extend(response.get("Items", []))
            pages_read += 1

            last_key = response.get("LastEvaluatedKey")
            if not last_key or pages_read >= _SCAN_MAX_PAGES or len(raw_items) >= _SCAN_MAX_ITEMS:
                if last_key and (pages_read >= _SCAN_MAX_PAGES or len(raw_items) >= _SCAN_MAX_ITEMS):
                    logger.warning(
                        "Dashboard Scan capped at %d pages / %d items (status=%s). "
                        "Deploy a status-keyed GSI (E5) to eliminate this scan.",
                        pages_read, len(raw_items), status,
                    )
                break

            scan_kwargs["ExclusiveStartKey"] = last_key

        # Sort ascending by sla_deadline after retrieval (Scan returns unordered)
        raw_items.sort(key=lambda x: x.get("sla_deadline", ""))

    items = [
        {
            "ticket_id": item.get("ticket_id"),
            "severity": item.get("severity"),
            "status": item.get("status"),
            "title": item.get("title"),
            "service": item.get("service"),
            "assignee": item.get("assignee"),
            "sla_deadline": item.get("sla_deadline"),
        }
        for item in raw_items
    ]

    return {"items": items}, 200


# ---------------------------------------------------------------------------
# Get ticket (PA-1)
# ---------------------------------------------------------------------------

def get_ticket(ticket_id: str) -> tuple[dict, int]:
    """
    Query all items for a ticket (PK = TICKET#<id>) and assemble them.
    Returns {meta, events[], comments[], attachments[]}.
    Raises NotFoundError if no META item is found.

    Pagination limitation: Limit=100 is applied to the underlying query.
    Tickets with more than 100 sub-items (events + comments + attachments)
    will be silently truncated. A cursor-based pagination API should be added
    in a future iteration (tracked for E5).  For the current academic scope
    this is acceptable; real incidents rarely exceed that item count.
    """
    table = ddb.get_table()

    response = table.query(
        KeyConditionExpression=Key("PK").eq(keys.ticket_pk(ticket_id)),
        Limit=100,
    )
    items = response.get("Items", [])

    meta = None
    events = []
    comments = []
    attachments = []

    for item in items:
        sk: str = item.get("SK", "")
        if sk == keys.SK_PREFIX_META:
            meta = item
        elif sk.startswith(keys.SK_PREFIX_EVENT):
            events.append(item)
        elif sk.startswith(keys.SK_PREFIX_COMMENT):
            comments.append(item)
        elif sk.startswith(keys.SK_PREFIX_ATTACH):
            attachments.append(item)

    if meta is None:
        raise models.NotFoundError(f"Ticket '{ticket_id}' not found.")

    # Sort events and comments by SK (which is time-ordered)
    events.sort(key=lambda x: x.get("SK", ""))
    comments.sort(key=lambda x: x.get("SK", ""))

    # Build attachment dicts explicitly: expose download_url, NOT s3_key.
    # Leaking the internal S3 key path would expose bucket structure and
    # enable callers to craft arbitrary keys — defense-in-depth (F-05).
    def _build_attachment(item: dict) -> dict:
        att: dict = {
            "filename": item.get("filename"),
            "content_type": item.get("content_type"),
            "size": item.get("size"),
            "download_url": s3.generate_presigned_get_url(item["s3_key"]),
        }
        if "created_at" in item:
            att["created_at"] = item["created_at"]
        return att

    return {
        "meta": _strip_ddb_keys(meta),
        "events": [_strip_ddb_keys(e) for e in events],
        "comments": [_strip_ddb_keys(c) for c in comments],
        "attachments": [_build_attachment(a) for a in attachments],
    }, 200


def _strip_ddb_keys(item: dict) -> dict:
    """Remove internal DynamoDB key/implementation attributes from returned items.

    Excluded attributes:
      - PK/SK/GSI*: raw single-table keys — expose nothing about the storage layout.
      - dedup_hash: SHA-256 of (service, alert_type); the frontend consumes
        occurrence_count/source, not the raw hash.  Leaking it would allow
        callers to infer internal dedup boundaries or forge hash collisions.
    """
    exclude = {"PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", "dedup_hash"}
    return {k: v for k, v in item.items() if k not in exclude}


# ---------------------------------------------------------------------------
# Add comment  (US-05)
# ---------------------------------------------------------------------------

def add_comment(ticket_id: str, body: dict) -> tuple[dict, int]:
    """
    Append a comment to a ticket.
    Writes COMMENT + EVENT(COMMENT_ADDED) atomically via transact_write_items (CRIT-04).
    """
    author = body.get("author")
    comment_body = body.get("body")

    if not author:
        raise models.ValidationError("'author' is required.")
    if not comment_body:
        raise models.ValidationError("'body' is required.")

    # --- Field length limits (F-08) ---
    if len(author) > models.MAX_ACTOR_LEN:
        raise models.ValidationError(
            f"'author' exceeds maximum length of {models.MAX_ACTOR_LEN} characters."
        )
    if len(comment_body) > models.MAX_COMMENT_LEN:
        raise models.ValidationError(
            f"'body' exceeds maximum length of {models.MAX_COMMENT_LEN} characters."
        )

    # Verify ticket exists
    _require_meta(ticket_id)

    pk = keys.ticket_pk(ticket_id)
    now = ids.utc_now()
    ts_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    u8_comment = ids.short_uuid8()
    u8_event = ids.short_uuid8()

    comment_item = {
        "PK": pk,
        "SK": keys.comment_sk(ts_iso, u8_comment),
        "author": author,
        "body": comment_body,
        "created_at": ts_iso,
    }

    event_item = {
        "PK": pk,
        "SK": keys.event_sk(ts_iso, u8_event),
        "event_type": "COMMENT_ADDED",
        "actor": author,
        "action": "Comment added",
        "payload": {"comment_preview": comment_body[:100]},
        "created_at": ts_iso,
    }

    # Atomic write: COMMENT + EVENT together (CRIT-04)
    table_name = os.environ["TABLE_NAME"]
    client = ddb.get_client()

    client.transact_write_items(
        TransactItems=[
            {"Put": {"TableName": table_name, "Item": _serialize(comment_item)}},
            {"Put": {"TableName": table_name, "Item": _serialize(event_item)}},
        ]
    )

    logger.info("Comment added to ticket %s by %s", ticket_id, author)
    return {"ok": True}, 201


# ---------------------------------------------------------------------------
# Update ticket status — general state machine  (US-05, CRIT-03, CRIT-04)
# ---------------------------------------------------------------------------

def update_status(ticket_id: str, body: dict) -> tuple[dict, int]:
    """
    Transition a ticket through the allowed state machine using optimistic
    locking on 'version'.

    Allowed transitions (see models.ALLOWED_TRANSITIONS):
      OPEN      → {ACK, ESCALATED, RESOLVED}
      ACK       → {ESCALATED, RESOLVED}
      ESCALATED → {ACK, RESOLVED}
      RESOLVED  → {} (terminal — no further transitions)

    Body: {status: <target>, actor: str, version: int >= 1}

    Guards (CRIT-03):
      1. target must be in VALID_TARGET_STATUSES (OPEN is not a valid target).
      2. actor and version are required; version must be a positive integer.
      3. Application-layer check: current_status must allow target via
         ALLOWED_TRANSITIONS before the DB write is attempted.
      4. DB-layer ConditionExpression: enforces version AND valid source statuses
         atomically, closing the TOCTOU window (CRIT-03 + CRIT-04).

    Atomic write (transact_write_items):
      - Update META: status, version+1, updated_at, GSI1SK recalculated.
        If target==RESOLVED also sets resolved_at.
      - Put EVENT item with event_type matching the target status.

    Returns {"status": target, "version": version+1}, 200.
    Raises ValidationError (400) for invalid target or disallowed transition.
    Raises NotFoundError (404) if ticket does not exist.
    Raises VersionConflict (409) on optimistic lock failure.
    """
    target_status = body.get("status")
    actor = body.get("actor")
    expected_version = body.get("version")

    # --- Validate target status ---
    if target_status not in models.VALID_TARGET_STATUSES:
        raise models.ValidationError(
            f"Invalid target status '{target_status}'. "
            f"Must be one of {sorted(models.VALID_TARGET_STATUSES)}."
        )

    # --- Validate actor ---
    if not actor:
        raise models.ValidationError("'actor' is required.")
    if len(actor) > models.MAX_ACTOR_LEN:
        raise models.ValidationError(
            f"'actor' exceeds maximum length of {models.MAX_ACTOR_LEN} characters."
        )

    # --- Validate version ---
    if expected_version is None:
        raise models.ValidationError("'version' is required.")
    try:
        expected_version = int(expected_version)
    except (ValueError, TypeError):
        raise models.ValidationError("'version' must be an integer.")
    if expected_version < 1:
        raise models.ValidationError("'version' must be >= 1.")

    # --- Read META to get current state ---
    meta = _require_meta(ticket_id)
    current_status = meta.get("status", "")
    sla_deadline = meta.get("sla_deadline", "")

    # --- Application-layer state-machine guard (CRIT-03) ---
    # Catches clearly invalid transitions (e.g. RESOLVED→ACK) before touching DDB.
    allowed_targets = models.ALLOWED_TRANSITIONS.get(current_status, frozenset())
    if target_status not in allowed_targets:
        raise models.ValidationError(
            f"Transition from '{current_status}' to '{target_status}' is not allowed. "
            f"Allowed targets from '{current_status}': {sorted(allowed_targets) or 'none (terminal state)'}."
        )

    # --- Prepare write ---
    pk = keys.ticket_pk(ticket_id)
    now = ids.utc_now()
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    new_gsi1_sk = keys.gsi1_sk(target_status, sla_deadline)

    table_name = os.environ["TABLE_NAME"]
    client = ddb.get_client()
    u8 = ids.short_uuid8()

    # --- Build EVENT payload per target ---
    _EVENT_META: dict[str, dict] = {
        "ACK":       {"event_type": "ACK",       "action": "Ticket reconocido",  "payload": {"previous_status": current_status}},
        "ESCALATED": {"event_type": "ESCALATED",  "action": "Ticket escalado",    "payload": {"previous_status": current_status}},
        "RESOLVED":  {"event_type": "RESOLVED",   "action": "Ticket resuelto",    "payload": {"previous_version": expected_version}},
    }
    ev_meta = _EVENT_META[target_status]

    event_item = {
        "PK": pk,
        "SK": keys.event_sk(now_iso, u8),
        "event_type": ev_meta["event_type"],
        "actor": actor,
        "action": ev_meta["action"],
        "payload": ev_meta["payload"],
        "created_at": now_iso,
    }

    # --- Build UpdateExpression ---
    # Base expression always updates status, version, updated_at, GSI1SK.
    # For RESOLVED we additionally set resolved_at.
    update_expr = (
        "SET #st = :target, updated_at = :now, #ver = :new_ver, GSI1SK = :new_gsi1sk"
    )
    expr_values: dict = {
        ":target": target_status,
        ":now": now_iso,
        ":new_ver": expected_version + 1,
        ":expected_ver": expected_version,
        ":new_gsi1sk": new_gsi1_sk,
    }
    if target_status == models.RESOLVED_STATUS:
        update_expr += ", resolved_at = :now"

    # --- Build DB-level ConditionExpression ---
    # Enforces: version matches expected AND current status is a valid source
    # for the requested target.  This closes the TOCTOU window that exists
    # between the _require_meta read above and this write (CRIT-03 + CRIT-04).
    #
    # "valid source statuses for target" = all statuses S where target ∈ ALLOWED_TRANSITIONS[S]
    valid_sources = [
        s for s, targets in models.ALLOWED_TRANSITIONS.items() if target_status in targets
    ]
    source_placeholders = {f":src{i}": s for i, s in enumerate(valid_sources)}
    source_in_expr = " OR ".join(f"#st = {ph}" for ph in source_placeholders)
    expr_values.update(source_placeholders)

    # --- Build TransactItems list ---
    transact_items = [
        {
            "Update": {
                "TableName": table_name,
                "Key": _serialize({"PK": pk, "SK": keys.meta_sk()}),
                "UpdateExpression": update_expr,
                "ConditionExpression": (
                    f"#ver = :expected_ver AND ({source_in_expr})"
                ),
                "ExpressionAttributeNames": {
                    "#st": "status",
                    "#ver": "version",
                },
                "ExpressionAttributeValues": _serialize(expr_values),
            }
        },
        {
            "Put": {
                "TableName": table_name,
                "Item": _serialize(event_item),
            }
        },
    ]

    # FIX-2: When resolving a webhook-originated ticket, delete its dedup
    # pointer atomically so the next identical alert creates a new parent ticket
    # instead of attempting to dedup against a RESOLVED one.
    # The Delete is unconditional (idempotent) — if the pointer doesn't exist
    # (e.g. ticket was created manually, not via ingest_alert) DynamoDB simply
    # performs a no-op delete without error.
    if target_status == models.RESOLVED_STATUS:
        dedup_hash_value = meta.get("dedup_hash")
        if dedup_hash_value:
            transact_items.append(
                {
                    "Delete": {
                        "TableName": table_name,
                        "Key": _serialize({
                            "PK": keys.dedup_pointer_pk(dedup_hash_value),
                            "SK": keys.DEDUP_POINTER_SK,
                        }),
                    }
                }
            )

    try:
        client.transact_write_items(TransactItems=transact_items)
    except client.exceptions.TransactionCanceledException as exc:
        reasons = exc.response.get("CancellationReasons", [])
        update_reason = reasons[0].get("Code", "") if reasons else ""
        if update_reason == "ConditionalCheckFailed":
            raise models.VersionConflict(
                f"Version conflict or status constraint failed: "
                f"expected version {expected_version}, current status '{current_status}'."
            )
        raise  # unexpected — bubble up to 500 handler

    logger.info(
        "Ticket %s transitioned %s → %s by %s (version %s → %s)",
        ticket_id, current_status, target_status, actor,
        expected_version, expected_version + 1,
    )
    return {"status": target_status, "version": expected_version + 1}, 200


# ---------------------------------------------------------------------------
# resolve_ticket — backward-compatible thin wrapper around update_status
# ---------------------------------------------------------------------------

def resolve_ticket(ticket_id: str, body: dict) -> tuple[dict, int]:
    """
    Backward-compatible wrapper: delegates to update_status.

    Kept so that existing imports (tests, other callers) continue to work
    without modification.  The PATCH router now calls update_status directly.

    Pre-generalisation this function only accepted status='RESOLVED'; that
    constraint is now enforced by update_status via ALLOWED_TRANSITIONS.
    """
    return update_status(ticket_id, body)


# ---------------------------------------------------------------------------
# Reassign ticket  (US-06)
# ---------------------------------------------------------------------------

def reassign_ticket(ticket_id: str, body: dict) -> tuple[dict, int]:
    """
    Atomically reassign a ticket to a new engineer.

    Updates META.assignee and META.GSI1PK so the dashboard-by-engineer GSI
    immediately reflects the new owner.  GSI1SK (SLA deadline) is NOT
    changed — the SLA clock started at creation and is independent of ownership.

    Body: {assignee: str, actor: str, version: int >= 1}

    Guards:
      1. assignee and actor required; both ≤ MAX_ACTOR_LEN.
      2. version required; positive integer (optimistic lock).
      3. Cannot reassign a RESOLVED ticket (terminal guard, checked before DB
         write to give a clean 400 rather than a conditional-check 409).
      4. ConditionExpression on version closes the TOCTOU window (CRIT-03).

    Atomic write (transact_write_items):
      - Update META: assignee, GSI1PK, updated_at, version+1.
        ConditionExpression: version == expected.
      - Put EVENT(ASSIGNED): actor, from/to payload.

    Returns {"assignee": new_assignee, "version": version+1}, 200.
    Raises ValidationError (400) for invalid input or RESOLVED ticket.
    Raises NotFoundError (404) if ticket does not exist.
    Raises VersionConflict (409) on optimistic lock failure.
    """
    new_assignee = body.get("assignee")
    actor = body.get("actor")
    expected_version = body.get("version")

    # --- Validate assignee ---
    if not new_assignee:
        raise models.ValidationError("'assignee' is required.")
    if len(new_assignee) > models.MAX_ACTOR_LEN:
        raise models.ValidationError(
            f"'assignee' exceeds maximum length of {models.MAX_ACTOR_LEN} characters."
        )

    # --- Validate actor ---
    if not actor:
        raise models.ValidationError("'actor' is required.")
    if len(actor) > models.MAX_ACTOR_LEN:
        raise models.ValidationError(
            f"'actor' exceeds maximum length of {models.MAX_ACTOR_LEN} characters."
        )

    # --- Validate version ---
    if expected_version is None:
        raise models.ValidationError("'version' is required.")
    try:
        expected_version = int(expected_version)
    except (ValueError, TypeError):
        raise models.ValidationError("'version' must be an integer.")
    if expected_version < 1:
        raise models.ValidationError("'version' must be >= 1.")

    # --- Read META to get current state ---
    meta = _require_meta(ticket_id)
    current_status = meta.get("status", "")
    old_assignee = meta.get("assignee", "")

    # --- Guard: cannot reassign a RESOLVED ticket ---
    if current_status == models.RESOLVED_STATUS:
        raise models.ValidationError("no se puede reasignar un ticket resuelto")

    # --- Prepare write ---
    pk = keys.ticket_pk(ticket_id)
    now = ids.utc_now()
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    new_gsi1_pk = keys.gsi1_pk(new_assignee)
    u8 = ids.short_uuid8()

    table_name = os.environ["TABLE_NAME"]
    client = ddb.get_client()

    event_item = {
        "PK": pk,
        "SK": keys.event_sk(now_iso, u8),
        "event_type": "ASSIGNED",
        "actor": actor,
        "action": f"Reasignado a {new_assignee}",
        "payload": {"from": old_assignee, "to": new_assignee},
        "created_at": now_iso,
    }

    try:
        client.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": table_name,
                        "Key": _serialize({"PK": pk, "SK": keys.meta_sk()}),
                        "UpdateExpression": (
                            "SET assignee = :a, GSI1PK = :gpk, "
                            "updated_at = :now, #ver = :newver"
                        ),
                        "ConditionExpression": "#ver = :expected",
                        "ExpressionAttributeNames": {"#ver": "version"},
                        "ExpressionAttributeValues": _serialize({
                            ":a": new_assignee,
                            ":gpk": new_gsi1_pk,
                            ":now": now_iso,
                            ":newver": expected_version + 1,
                            ":expected": expected_version,
                        }),
                    }
                },
                {
                    "Put": {
                        "TableName": table_name,
                        "Item": _serialize(event_item),
                    }
                },
            ]
        )
    except client.exceptions.TransactionCanceledException as exc:
        reasons = exc.response.get("CancellationReasons", [])
        update_reason = reasons[0].get("Code", "") if reasons else ""
        if update_reason == "ConditionalCheckFailed":
            raise models.VersionConflict(
                f"Version conflict: expected version {expected_version} "
                f"for ticket '{ticket_id}'."
            )
        raise  # unexpected — bubble up to 500 handler

    logger.info(
        "Ticket %s reassigned %s → %s by %s (version %s → %s)",
        ticket_id, old_assignee, new_assignee, actor,
        expected_version, expected_version + 1,
    )
    return {"assignee": new_assignee, "version": expected_version + 1}, 200


# ---------------------------------------------------------------------------
# Webhook alert ingestion with deduplication  (US-02)
# ---------------------------------------------------------------------------

def ingest_alert(body: dict) -> tuple[dict, int]:
    """
    Ingest a monitoring alert and either create a new ticket or deduplicate
    against an existing active ticket identified by a deterministic hash of
    (service, alert_type).

    Deduplication strategy — deterministic pointer (FIX-2):
    -------------------------------------------------------
    The classic GSI-only approach is eventually consistent: two concurrent
    requests for the same hash can both fail to find an existing parent and
    both attempt to create one, producing duplicate tickets.

    We close this race with a *dedup pointer* — a dedicated DynamoDB item:
      PK = DEDUP#<sha256hex>   SK = ACTIVE
      payload: {parent_ticket_id: "<ticket>"}

    The pointer is written in the same atomic transaction as the new ticket
    (META + EVENT + POINTER) with a ConditionExpression="attribute_not_exists(PK)"
    guard.  Only one concurrent request can win the condition; the loser gets
    TransactionCanceledException(ConditionalCheckFailed) and retries the
    detection path to join the winner's ticket as a duplicate.

    The pointer is read with ConsistentRead=True (strongly consistent GetItem)
    so that the detection phase is not subject to GSI replication lag.

    The pointer is deleted atomically when the parent ticket is RESOLVED, so
    that a subsequent alert for the same hash starts fresh.

    GSI2 is kept as the historical hash→ticket index; it is not authoritative
    for the live dedup race.

    Returns (response_body, http_status_code).
    """
    # ------------------------------------------------------------------
    # 1. Validate required fields  (FIX-4: reject blank after strip)
    # ------------------------------------------------------------------
    service_name = body.get("service")
    alert_type = body.get("alert_type")

    if not service_name:
        raise models.ValidationError("'service' is required.")
    if not alert_type:
        raise models.ValidationError("'alert_type' is required.")

    # Reject values that are blank after stripping whitespace (FIX-4).
    # An empty normalised string would produce a hash of just "|", making
    # every such alert deduplicate into the same phantom ticket.
    if not service_name.strip():
        raise models.ValidationError("'service' must not be blank.")
    if not alert_type.strip():
        raise models.ValidationError("'alert_type' must not be blank.")

    # Length limits (FIX-6: use named constant for alert_type)
    if len(service_name) > models.MAX_SERVICE_LEN:
        raise models.ValidationError(
            f"'service' exceeds maximum length of {models.MAX_SERVICE_LEN} characters."
        )
    if len(alert_type) > models.MAX_ALERT_TYPE_LEN:
        raise models.ValidationError(
            f"'alert_type' exceeds maximum length of {models.MAX_ALERT_TYPE_LEN} characters."
        )

    # Optional fields with defaults
    severity = body.get("severity", models.DEFAULT_SEVERITY)
    models.validate_severity(severity)

    # FIX-4: if title/description are explicitly provided but blank after
    # strip, fall back to the auto-generated default rather than persisting
    # an empty string in the ticket.
    default_title = f"[{service_name}] {alert_type}"
    raw_title = body.get("title")
    title = (raw_title.strip() if raw_title else None) or default_title
    if len(title) > models.MAX_TITLE_LEN:
        raise models.ValidationError(
            f"'title' exceeds maximum length of {models.MAX_TITLE_LEN} characters."
        )

    default_description = (
        f"Alerta automática '{alert_type}' del servicio '{service_name}'."
    )
    raw_description = body.get("description")
    description = (raw_description.strip() if raw_description else None) or default_description
    if len(description) > models.MAX_DESCRIPTION_LEN:
        raise models.ValidationError(
            f"'description' exceeds maximum length of {models.MAX_DESCRIPTION_LEN} characters."
        )

    # FIX-4: sanitize 'source' — allow only alphanumeric, space, hyphen,
    # underscore, period.  Remove everything else, then check length/blank.
    raw_source = body.get("source", "monitoring")
    if len(raw_source) > models.MAX_ACTOR_LEN:
        raise models.ValidationError(
            f"'source' exceeds maximum length of {models.MAX_ACTOR_LEN} characters."
        )
    source = _SOURCE_SAFE_RE.sub("", raw_source).strip() or "monitoring"

    assignee = body.get("assignee", models.DEFAULT_ASSIGNEE)
    if len(assignee) > models.MAX_ACTOR_LEN:
        raise models.ValidationError(
            f"'assignee' exceeds maximum length of {models.MAX_ACTOR_LEN} characters."
        )

    # ------------------------------------------------------------------
    # 2. Compute dedup hash; detect active parent via strongly-consistent
    #    GetItem on the dedup pointer (FIX-2).
    # ------------------------------------------------------------------
    h = models.dedup_hash(service_name, alert_type)

    table = ddb.get_table()
    table_name = os.environ["TABLE_NAME"]
    client = ddb.get_client()
    now = ids.utc_now()
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    def _get_pointer() -> dict | None:
        """
        Strongly-consistent read of the dedup pointer.
        Returns the pointer item dict if it exists, else None.
        """
        result = table.get_item(
            Key={
                "PK": keys.dedup_pointer_pk(h),
                "SK": keys.DEDUP_POINTER_SK,
            },
            ConsistentRead=True,
        )
        return result.get("Item")

    def _load_parent_meta(parent_ticket_id: str) -> dict | None:
        """
        Load the META item for a candidate parent ticket.
        Returns None if the item is gone (should never happen in practice).
        """
        result = table.get_item(
            Key={
                "PK": keys.ticket_pk(parent_ticket_id),
                "SK": keys.meta_sk(),
            },
            ConsistentRead=True,
        )
        return result.get("Item")

    # ------------------------------------------------------------------
    # 3. Attempt dedup — try up to 2 times to handle the race where we
    #    win the CREATE condition check on retry.
    # ------------------------------------------------------------------
    for _attempt in range(2):
        pointer = _get_pointer()

        # ------------------------------------------------------------------
        # 3a. DEDUP PATH — pointer exists, pointing to an active parent
        # ------------------------------------------------------------------
        if pointer:
            parent_ticket_id: str = pointer["parent_ticket_id"]
            parent_meta = _load_parent_meta(parent_ticket_id)

            # Edge case: pointer exists but the META was RESOLVED (inconsistent
            # state that should not occur with clean pointer deletion on resolve,
            # but we handle it defensively).
            if parent_meta and parent_meta.get("status") in models.RESOLVABLE_STATUSES:
                parent_id = parent_ticket_id
                parent_status = parent_meta["status"]
                old_count = int(parent_meta.get("occurrence_count", 1))

                pk = keys.ticket_pk(parent_id)
                u8 = ids.short_uuid8()

                event_item = {
                    "PK": pk,
                    "SK": keys.event_sk(now_iso, u8),
                    "event_type": "ALERT_DUPLICATE",
                    "actor": source,
                    "action": "Alerta duplicada recibida",
                    "payload": {"source": source, "alert_type": alert_type},
                    "created_at": now_iso,
                }

                client.transact_write_items(
                    TransactItems=[
                        {
                            "Update": {
                                "TableName": table_name,
                                "Key": _serialize({"PK": pk, "SK": keys.meta_sk()}),
                                "UpdateExpression": (
                                    "ADD occurrence_count :one "
                                    "SET updated_at = :now"
                                ),
                                "ConditionExpression": "attribute_exists(PK)",
                                "ExpressionAttributeValues": _serialize(
                                    {":one": 1, ":now": now_iso}
                                ),
                            }
                        },
                        {
                            "Put": {
                                "TableName": table_name,
                                "Item": _serialize(event_item),
                            }
                        },
                    ]
                )

                logger.info(
                    "Deduped alert for ticket %s (hash=%s, new count=%s)",
                    parent_id, h[:8], old_count + 1,
                )

                return {
                    "ticket_id": parent_id,
                    "status": parent_status,
                    "deduplicated": True,
                    "occurrence_count": old_count + 1,
                }, 200

            # Pointer exists but parent is RESOLVED (stale pointer) —
            # fall through to CREATE path below after this if-block.

        # ------------------------------------------------------------------
        # 3b. NEW TICKET PATH — no valid pointer found; create new ticket
        #     with the dedup pointer in the same atomic transaction.
        # ------------------------------------------------------------------
        ticket = ids.ticket_id()
        created_at = now_iso
        sla_deadline = models.compute_sla_deadline(now, severity)

        pk = keys.ticket_pk(ticket)
        meta_sk_val = keys.meta_sk()

        meta_item = {
            "PK": pk,
            "SK": meta_sk_val,
            # GSI1 — dashboard by assignee
            "GSI1PK": keys.gsi1_pk(assignee),
            "GSI1SK": keys.gsi1_sk(models.DEFAULT_STATUS, sla_deadline),
            # GSI2 — historical hash→ticket index (not authoritative for live dedup)
            "GSI2PK": keys.gsi2_pk(h),
            "GSI2SK": keys.gsi2_sk(ticket),
            # Domain fields
            "ticket_id": ticket,
            "title": title,
            "service": service_name,
            "description": description,
            "severity": severity,
            "status": models.DEFAULT_STATUS,
            "assignee": assignee,
            "sla_deadline": sla_deadline,
            "created_at": created_at,
            "updated_at": created_at,
            "version": 1,
            "attachments_count": 0,
            # Webhook-specific fields
            "dedup_hash": h,
            "occurrence_count": 1,
            "source": source,
        }

        u8 = ids.short_uuid8()
        event_item = {
            "PK": pk,
            "SK": keys.event_sk(created_at, u8),
            "event_type": "CREATED",
            "actor": source,
            "action": "Incidente creado desde webhook",
            "payload": {"source": source, "alert_type": alert_type, "severity": severity},
            "created_at": created_at,
        }

        # Dedup pointer written in the same transaction — its ConditionExpression
        # ensures only one concurrent CREATE wins for this hash.
        pointer_item = {
            "PK": keys.dedup_pointer_pk(h),
            "SK": keys.DEDUP_POINTER_SK,
            "parent_ticket_id": ticket,
        }

        try:
            client.transact_write_items(
                TransactItems=[
                    {"Put": {"TableName": table_name, "Item": _serialize(meta_item)}},
                    {"Put": {"TableName": table_name, "Item": _serialize(event_item)}},
                    {
                        "Put": {
                            "TableName": table_name,
                            "Item": _serialize(pointer_item),
                            # Only one concurrent request may create this pointer.
                            # The loser gets ConditionalCheckFailed and retries
                            # the detection phase to follow the winner as a dedup.
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                ]
            )
        except client.exceptions.TransactionCanceledException as exc:
            reasons = exc.response.get("CancellationReasons", [])
            # The pointer Put is the 3rd item (index 2).
            pointer_reason = reasons[2].get("Code", "") if len(reasons) > 2 else ""
            if pointer_reason == "ConditionalCheckFailed":
                # Another concurrent request won the race and created the pointer.
                # Loop back to detection so we join that ticket as a duplicate.
                logger.info(
                    "Pointer race lost for hash=%s (attempt=%d); retrying dedup detection.",
                    h[:8], _attempt,
                )
                continue
            raise  # unexpected cancellation — bubble up to 500 handler

        logger.info(
            "Created ticket %s from webhook (service=%s, alert_type=%s, hash=%s)",
            ticket, service_name, alert_type, h[:8],
        )

        return {
            "ticket_id": ticket,
            "status": models.DEFAULT_STATUS,
            "sla_deadline": sla_deadline,
            "deduplicated": False,
            "occurrence_count": 1,
        }, 201

    # Exhausted retries (extremely unlikely under normal load).
    raise models.ValidationError(
        "Could not process alert after retries — possible sustained write contention. "
        "Please retry."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require_meta(ticket_id: str) -> dict:
    """
    Fetch the META item for a ticket.
    Raises NotFoundError if it doesn't exist.
    """
    table = ddb.get_table()
    response = table.get_item(
        Key={"PK": keys.ticket_pk(ticket_id), "SK": keys.meta_sk()}
    )
    item = response.get("Item")
    if not item:
        raise models.NotFoundError(f"Ticket '{ticket_id}' not found.")
    return item


def _serialize(obj: dict) -> dict:
    """
    Serialize a plain Python dict into the DynamoDB low-level wire format
    that transact_write_items expects when using the boto3 DynamoDB *client*
    (not the resource/Table abstraction).

    The resource Table handles type marshalling automatically; the client does not.
    We use boto3's own TypeSerializer (module-level singleton _SERIALIZER) to stay
    consistent with how the Table resource would serialise the same values.
    """
    return {k: _SERIALIZER.serialize(v) for k, v in obj.items()}
