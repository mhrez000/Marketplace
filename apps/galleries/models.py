from django.db import models
from django.utils import timezone

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel, UUIDTimeStampedModel
from apps.profiles.models import ACCENTS


class Gallery(UUIDTimeStampedModel):
    class Type(models.TextChoices):
        PHOTO = "photo", "Photo"
        VIDEO = "video", "Video"

    class Visibility(models.TextChoices):
        PRIVATE = "private", "Private (logged-in client)"
        PASSWORD = "password", "Password protected"

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="galleries")
    title = models.CharField(max_length=180)
    gallery_type = models.CharField(max_length=6, choices=Type.choices, default=Type.PHOTO)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE)
    access_code = models.CharField(max_length=40, blank=True)
    expiry = models.DateField(null=True, blank=True)
    is_delivered = models.BooleanField(default=False)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "galleries"

    def __str__(self):
        return self.title

    def deliver(self):
        self.is_delivered = True
        self.delivered_at = timezone.now()
        self.save(update_fields=["is_delivered", "delivered_at", "updated_at"])


class Asset(TimeStampedModel):
    class Type(models.TextChoices):
        PHOTO = "photo", "Photo"
        VIDEO = "video", "Video link"

    gallery = models.ForeignKey(Gallery, on_delete=models.CASCADE, related_name="assets")
    title = models.CharField(max_length=160, blank=True)
    image = models.ImageField(upload_to="galleries/", blank=True, null=True)
    video_url = models.URLField(blank=True)
    asset_type = models.CharField(max_length=6, choices=Type.choices, default=Type.PHOTO)
    accent = models.CharField(max_length=8, choices=ACCENTS, default="navy")
    is_favourite = models.BooleanField(default=False)

    def __str__(self):
        return self.title or f"Asset {self.pk}"
