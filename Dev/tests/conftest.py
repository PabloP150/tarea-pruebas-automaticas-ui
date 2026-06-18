"""
conftest.py — moto-based fixtures for api-tickets tests.

Sets up:
  - A mocked DynamoDB table 'ticketresolve-test' with GSI1 + GSI2 (matching infra schema)
  - A mocked S3 bucket
  - Environment variables TABLE_NAME and ATTACHMENTS_BUCKET
  - Resets lazy boto3 singletons between tests
"""
import json
import os
import pytest

# Set environment variables BEFORE any application imports so lazy clients bind correctly
os.environ.setdefault("TABLE_NAME", "ticketresolve-test")
os.environ.setdefault("ATTACHMENTS_BUCKET", "ticketresolve-test-attachments")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")

import boto3
from moto import mock_aws


TABLE_NAME = os.environ["TABLE_NAME"]
BUCKET_NAME = os.environ["ATTACHMENTS_BUCKET"]


def create_table(dynamodb):
    """Create the DynamoDB table that mirrors the Terraform module schema."""
    return dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "GSI2",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def create_bucket(s3):
    """Create the attachments S3 bucket."""
    s3.create_bucket(Bucket=BUCKET_NAME)


@pytest.fixture
def aws_services():
    """
    Start moto mocks, create table + bucket, reset shared singletons,
    yield the (table, s3_client) pair, then teardown.
    """
    with mock_aws():
        # Reset lazy singletons so moto intercepts the boto3 session
        from shared import ddb, s3 as s3_module
        ddb.reset()
        s3_module.reset()


        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        s3_client = boto3.client("s3", region_name="us-east-1")

        table = create_table(dynamodb)
        create_bucket(s3_client)

        yield table, s3_client

        # Reset again after context exits
        ddb.reset()
        s3_module.reset()



# ---------------------------------------------------------------------------
# HTTP API v2 event builder helper
# ---------------------------------------------------------------------------

def make_event(
    method: str,
    path: str,
    body: dict | None = None,
    path_params: dict | None = None,
    query_params: dict | None = None,
) -> dict:
    """Build a minimal HTTP API Gateway v2 (payload format 2.0) event."""
    event: dict = {
        "version": "2.0",
        "rawPath": path,
        "requestContext": {
            "http": {
                "method": method.upper(),
                "path": path,
            },
        },
        "isBase64Encoded": False,
    }
    if body is not None:
        event["body"] = json.dumps(body)
    if path_params:
        event["pathParameters"] = path_params
    if query_params:
        event["queryStringParameters"] = query_params
    return event
