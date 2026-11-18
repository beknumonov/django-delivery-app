"""Integration tests: real Postgres + real (emulated) S3 on Floci.

Unit tests fake S3; these prove the real wiring works — the SQL runs on
Postgres and the export really lands in a bucket.
"""

import json
import os
import uuid

import boto3
import pytest
from django.db import connection

# Skip the whole file unless we're pointed at Postgres. Locally,
# `uv run pytest` (SQLite) stays green; CI sets DATABASE_URL=postgres://...
pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").startswith("postgres"),
        reason="integration tests need DATABASE_URL=postgres://...",
    ),
]


@pytest.fixture
def bucket(settings):
    """Create a fresh, uniquely named bucket per test, so tests never share state."""
    name = f"it-{uuid.uuid4().hex[:12]}"
    s3 = boto3.client("s3", endpoint_url=settings.AWS_ENDPOINT_URL, region_name=settings.AWS_REGION)
    s3.create_bucket(Bucket=name)
    settings.EXPORT_BUCKET = name  # the view will write here
    return s3, name


def test_database_is_postgres():
    # Guards against the job silently running on SQLite.
    assert connection.vendor == "postgresql"


def test_export_round_trip(client, bucket):
    s3, name = bucket
    client.post("/api/notes/", data=json.dumps({"title": "it"}), content_type="application/json")

    resp = client.post("/api/notes/export/")
    assert resp.status_code == 200

    # Read the object back from S3 and check its content — the real round trip.
    obj = s3.get_object(Bucket=name, Key=resp.json()["key"])
    assert [n["title"] for n in json.loads(obj["Body"].read())] == ["it"]
