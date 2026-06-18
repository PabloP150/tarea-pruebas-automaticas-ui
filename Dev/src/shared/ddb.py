"""
ddb.py — Lazy boto3 DynamoDB resource, table, and low-level client factory.

Client/resource creation is deferred until first use so that moto patches
are applied before the boto3 session is initialised.

Two access paths are provided:
  - get_table()    → boto3 DynamoDB resource Table (high-level, handles type
                     marshalling automatically — use for simple get/query/update).
  - get_client()   → boto3 DynamoDB *client* (low-level, wire format — use for
                     transact_write_items which requires pre-serialised items).

Both are lazily initialised and cached; call reset() in test teardown.
"""
import logging
import os
from typing import Any

import boto3

logger = logging.getLogger(__name__)

_resource: Any = None
_table: Any = None
_client: Any = None


def get_resource() -> Any:
    """Return (lazily initialised) boto3 DynamoDB resource."""
    global _resource
    if _resource is None:
        _resource = boto3.resource("dynamodb")
    return _resource


def get_client() -> Any:
    """
    Return (lazily initialised) boto3 DynamoDB *low-level client*.

    Required for transact_write_items, which operates on the wire format
    (TypeSerializer'd dicts) rather than the high-level resource abstraction.
    Using boto3.client() directly (instead of resource.meta.client) ensures
    moto intercepts the session correctly in tests.
    """
    global _client
    if _client is None:
        _client = boto3.client("dynamodb")
    return _client


def get_table() -> Any:
    """
    Return (lazily initialised) DynamoDB Table object.
    Table name read from TABLE_NAME env var.
    """
    global _table
    if _table is None:
        table_name = os.environ["TABLE_NAME"]
        logger.debug("Connecting to DynamoDB table: %s", table_name)
        _table = get_resource().Table(table_name)
    return _table


def reset() -> None:
    """Reset cached singletons — call in test teardown when moto context changes."""
    global _resource, _table, _client
    _resource = None
    _table = None
    _client = None
