from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.workspaces.models import Workspace


class Favourite(TimeStampedModel):
    """A client saving a creative for later (build plan §8.1)."""

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favourites"
    )
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="favourited_by"
    )

    class Meta:
        unique_together = ("client", "workspace")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.client} ♥ {self.workspace}"
