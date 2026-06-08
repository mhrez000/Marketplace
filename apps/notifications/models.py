from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Notification(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    verb = models.CharField(max_length=200)
    url = models.CharField(max_length=300, blank=True)
    icon = models.CharField(max_length=20, default="bell")
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return self.verb


def notify(user, verb, url="", icon="bell"):
    """Lightweight in-app notification helper (build plan §16 — full channel
    routing/email/SMS lands with Celery)."""
    return Notification.objects.create(user=user, verb=verb, url=url, icon=icon)
