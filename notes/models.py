from django.db import models


class Note(models.Model):
    # VARCHAR(200), required. The API also checks the length, so the user gets
    # a clean 400 instead of a database error.
    title = models.CharField(max_length=200)

    # Unlimited text. blank=True = validation allows empty; default="" = what is
    # stored. Django convention: empty string, not NULL, for text fields.
    body = models.TextField(blank=True, default="")

    # Set once when the row is INSERTed; stored in UTC because USE_TZ=True.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Newest first. "-id" breaks ties when two notes share a timestamp,
        # so the order is deterministic (stable tests and pagination).
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        # How a note is shown in the admin and the shell.
        return self.title

    def to_dict(self) -> dict:
        """The one JSON shape for a note, used by the API and the S3 export."""
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            # datetime is not JSON-serialisable; ISO 8601 string is,
            # e.g. "2026-11-17T10:00:00.123456+00:00".
            "created_at": self.created_at.isoformat(),
        }
