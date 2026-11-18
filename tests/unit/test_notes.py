import json
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from notes.models import Note

# Allow DB access in every test in this file. pytest-django wraps each test in
# a transaction that is ROLLED BACK afterwards: every test starts with an
# empty table and no test can affect another.
pytestmark = pytest.mark.django_db


def post_json(client, url, data):
    """Small helper: POST a dict as a JSON body."""
    return client.post(url, data=json.dumps(data), content_type="application/json")


# `client` is a pytest-django fixture: a fake browser that calls your views
# directly, without starting a server.
def test_list_empty(client):
    resp = client.get("/api/notes/")
    assert resp.status_code == 200
    assert resp.json() == {"results": []}


def test_create_and_list(client):
    resp = post_json(client, "/api/notes/", {"title": "hello", "body": "world"})
    assert resp.status_code == 201
    assert resp.json()["title"] == "hello"

    # The note we created is now returned by the list endpoint.
    results = client.get("/api/notes/").json()["results"]
    assert [n["title"] for n in results] == ["hello"]


# parametrize runs this ONE function 4 times, once per payload, and reports
# each as a separate test: missing, empty, whitespace-only, too long.
@pytest.mark.parametrize("payload", [{}, {"title": ""}, {"title": "   "}, {"title": "x" * 201}])
def test_create_rejects_bad_title(client, payload):
    assert post_json(client, "/api/notes/", payload).status_code == 400


def test_create_rejects_invalid_json(client):
    resp = client.post("/api/notes/", data="{not json", content_type="application/json")
    assert resp.status_code == 400  # client error, not a 500 crash


# `settings` fixture: change a setting for THIS test only; restored afterwards.
def test_export_writes_to_bucket(client, settings):
    settings.EXPORT_BUCKET = "test-bucket"
    Note.objects.create(title="a")
    Note.objects.create(title="b")

    # Replace s3_client WHERE IT IS USED (notes.views), not boto3 globally.
    # `factory` is the fake function; factory.return_value is the fake client
    # the view receives, and it records every call made on it.
    with patch("notes.views.s3_client") as factory:
        resp = client.post("/api/notes/export/")

    assert resp.status_code == 200
    assert resp.json()["count"] == 2

    # Check WHAT OUR CODE SENT to S3: right bucket, body has both notes.
    kwargs = factory.return_value.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "test-bucket"
    assert {n["title"] for n in json.loads(kwargs["Body"])} == {"a", "b"}


def test_export_failure_returns_502(client):
    # side_effect makes the fake RAISE — an error that's hard to trigger
    # against real S3 — so we can test the 502 path.
    error = ClientError({"Error": {"Code": "NoSuchBucket"}}, "PutObject")
    with patch("notes.views.s3_client") as factory:
        factory.return_value.put_object.side_effect = error
        resp = client.post("/api/notes/export/")
    assert resp.status_code == 502


def test_export_rejects_get(client):
    # @require_http_methods(["POST"]) answers 405 for GET.
    assert client.get("/api/notes/export/").status_code == 405


@pytest.mark.parametrize("probe", ["live", "ready", "startup"])
def test_health_probes(client, probe):
    resp = client.get(f"/healthz/{probe}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
