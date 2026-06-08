import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base: every model gets a UUID-friendly pk option + timestamps.

    We keep the default BigAuto pk for simplicity but expose created/updated
    on every table, as the build plan (§6) specifies.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class UUIDTimeStampedModel(TimeStampedModel):
    """Variant with a UUID primary key — used for public-facing resources
    (profiles, bookings) where exposing sequential ids is undesirable."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
