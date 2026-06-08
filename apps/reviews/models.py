from django.conf import settings
from django.db import models

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel
from apps.workspaces.models import Workspace


class Review(TimeStampedModel):
    """Reviews come only from completed on-platform bookings (build plan §18).
    The OneToOne to Booking enforces "one verified review per real booking"."""

    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="review")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(default=5)
    title = models.CharField(max_length=160, blank=True)
    body = models.TextField(blank=True)
    verified = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.rating}★ — {self.workspace}"
