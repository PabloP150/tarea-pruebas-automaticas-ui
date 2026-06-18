"""
s3.py — S3 presigned URL helper.

Creates presigned PUT URLs for attachment uploads.
Bucket name read lazily from ATTACHMENTS_BUCKET env var.
"""
import logging
import os
import re
from typing import Any

import boto3

from shared.models import MAX_FILENAME_LEN, ValidationError

logger = logging.getLogger(__name__)

_s3_client: Any = None

PRESIGNED_URL_EXPIRY_SECONDS: int = 15 * 60  # 15 minutes

# Allowlist of content types accepted for attachment uploads (F-05).
# Expand as new use-cases emerge; never use a wildcard allowlist.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "application/pdf",
        "text/plain",
    }
)

# Characters permitted in sanitised filenames: alphanumeric, dot, dash, underscore.
_SAFE_FILENAME_RE = re.compile(r"[^\w.\-]")


def get_s3_client() -> Any:
    """Return (lazily initialised) boto3 S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def reset() -> None:
    """Reset cached S3 client — call in test teardown when moto context changes."""
    global _s3_client
    _s3_client = None


def sanitize_filename(filename: str) -> str:
    """
    Return a safe filename suitable for use in an S3 key.

    Steps (F-04):
      1. Strip directory components (os.path.basename) to block path traversal.
      2. Replace any character outside [a-zA-Z0-9._-] with '_'.
      3. Enforce MAX_FILENAME_LEN.
      4. Raise ValidationError if the result is empty.
    """
    # Step 1: strip directory traversal (e.g. "../../etc/passwd" → "passwd")
    safe = os.path.basename(filename)

    # Step 2: replace unsafe characters
    safe = _SAFE_FILENAME_RE.sub("_", safe)

    # Step 3: length cap
    safe = safe[:MAX_FILENAME_LEN]

    # Step 4: must not be empty after sanitization
    if not safe:
        raise ValidationError("Attachment filename is empty or invalid after sanitization.")

    return safe


def validate_content_type(content_type: str) -> None:
    """
    Raise ValidationError if content_type is not in ALLOWED_CONTENT_TYPES (F-05).
    Comparison is case-insensitive; parameters (e.g. charset) are stripped.
    """
    # Strip any parameters such as "; charset=utf-8"
    base_type = content_type.split(";")[0].strip().lower()
    if base_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            f"Unsupported content_type '{content_type}'. "
            f"Allowed types: {sorted(ALLOWED_CONTENT_TYPES)}."
        )


def build_s3_key(year_month: str, ticket_id: str, filename: str) -> str:
    """
    Build the S3 object key for an attachment.
    Filename is sanitized here to ensure no path traversal reaches the key.

    year_month: 'YYYY-MM'
    """
    safe_filename = sanitize_filename(filename)
    return f"attachments/{year_month}/{ticket_id}/{safe_filename}"


def generate_presigned_get_url(s3_key: str, expires: int = 300) -> str:
    """
    Generate a presigned GET URL for the given S3 key.

    Allows a client to download the attachment directly from S3 without
    exposing the bucket name or internal key path.  The URL is valid for
    `expires` seconds (default 5 minutes).

    Bucket name is read from ATTACHMENTS_BUCKET env var.
    """
    bucket = os.environ["ATTACHMENTS_BUCKET"]
    client = get_s3_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=expires,
    )
    logger.debug("Generated presigned GET URL for s3://%s/%s", bucket, s3_key)
    return url


def generate_presigned_put_url(s3_key: str, content_type: str) -> str:
    """
    Generate a presigned PUT URL for the given S3 key.

    Passes ContentType to the presigned URL so the browser/client must send the
    correct Content-Type header, preventing content-type spoofing on the bucket (F-05).

    Bucket name is read from ATTACHMENTS_BUCKET env var.
    URL is valid for 15 minutes.
    """
    bucket = os.environ["ATTACHMENTS_BUCKET"]
    client = get_s3_client()
    url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket, "Key": s3_key, "ContentType": content_type},
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )
    logger.debug("Generated presigned PUT URL for s3://%s/%s", bucket, s3_key)
    return url
