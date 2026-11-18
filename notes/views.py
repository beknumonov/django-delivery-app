import json
import logging
from datetime import UTC, datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Note

# Logger named "notes.views"; output goes to stdout via settings.LOGGING.
logger = logging.getLogger(__name__)


def s3_client():
    """Create an S3 client at request time.

    A separate function for two reasons:
    1. Tests replace exactly this function with a fake
       (patch("notes.views.s3_client")), so no network is needed.
    2. It reads settings when called, not when the module is imported.
    endpoint_url=None means real AWS; http://localhost:4566 means Floci.
    """
    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_ENDPOINT_URL,
        region_name=settings.AWS_REGION,
    )


# CSRF protects browser COOKIE sessions from forged cross-site form posts.
# This JSON API is called by programs and uses no session cookie, so CSRF
# does not apply; without this every POST would get 403.
# (If you ever add cookie login to the API, remove it.)
@csrf_exempt
# Any other method (PUT, DELETE...) gets an automatic 405.
@require_http_methods(["GET", "POST"])
def note_list(request: HttpRequest) -> JsonResponse:
    """GET  /api/notes/  -> list all notes
    POST /api/notes/  -> create one note from {"title": ..., "body": ...}"""

    if request.method == "GET":
        # Wrapped in an object (not a bare list) so we can add "count"/"next"
        # later without breaking clients.
        return JsonResponse({"results": [n.to_dict() for n in Note.objects.all()]})

    # ---- POST: validate input, return 400 on anything wrong ---------------
    try:
        # Empty body is treated as {} so it fails the title check below.
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        # Bad JSON is the CLIENT's fault -> 400, not a 500 crash.
        return JsonResponse({"error": "invalid JSON"}, status=400)

    # "[1, 2]" or "42" is valid JSON but not an object.
    if not isinstance(payload, dict):
        return JsonResponse({"error": "expected a JSON object"}, status=400)

    # str() guards against {"title": 123}; strip() makes "   " count as empty.
    title = str(payload.get("title", "")).strip()
    if not title:
        return JsonResponse({"error": "title is required"}, status=400)
    # Check before the DB does, so the user gets a clear message.
    if len(title) > 200:
        return JsonResponse({"error": "title must be at most 200 characters"}, status=400)

    note = Note.objects.create(title=title, body=str(payload.get("body", "")))
    # 201 Created + the stored object (with its new id and timestamp).
    return JsonResponse(note.to_dict(), status=201)


@csrf_exempt
@require_http_methods(["POST"])  # export changes state -> POST only; GET gets 405
def note_export(request: HttpRequest) -> JsonResponse:
    """POST /api/notes/export/ -> write all notes as one JSON file to S3."""
    notes = [n.to_dict() for n in Note.objects.all()]

    # e.g. exports/staging/notes-20261117T101500Z.json
    # - APP_ENV keeps staging and prod exports apart even in a shared bucket
    # - UTC timestamp: every export is a new object (no overwrite) and keys sort by time
    key = f"exports/{settings.APP_ENV}/notes-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"

    try:
        s3_client().put_object(
            Bucket=settings.EXPORT_BUCKET,
            Key=key,
            Body=json.dumps(notes).encode(),  # S3 stores bytes
            ContentType="application/json",  # served back as JSON
        )
    # BotoCoreError = network/endpoint problems (Floci down, DNS, timeout)
    # ClientError   = AWS answered with an error (NoSuchBucket, AccessDenied)
    except (BotoCoreError, ClientError):
        # Full traceback goes to the logs for YOU...
        logger.exception("export to s3://%s/%s failed", settings.EXPORT_BUCKET, key)
        # ...the client gets a short message with no internals. 502 = an
        # upstream dependency failed, not our own code.
        return JsonResponse({"error": "export failed"}, status=502)

    # The log line you will search for in Module 13.
    logger.info("exported %d notes to s3://%s/%s", len(notes), settings.EXPORT_BUCKET, key)
    return JsonResponse({"bucket": settings.EXPORT_BUCKET, "key": key, "count": len(notes)})
