from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import TimeStampedModel


class Workspace(TimeStampedModel):
    """A creative business — solo shooter or a studio. Owns profile, services,
    bookings, etc. A user can own/belong to several (build plan §9)."""

    class Type(models.TextChoices):
        SOLO = "solo", "Solo creative"
        STUDIO = "studio", "Studio"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_workspaces"
    )
    type = models.CharField(max_length=10, choices=Type.choices, default=Type.SOLO)
    business_name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    abn = models.CharField("ABN", max_length=20, blank=True)
    # Verification & publishing — the quality moat (admin-controlled).
    verified_at = models.DateTimeField(null=True, blank=True)
    is_published = models.BooleanField(default=False)

    def __str__(self):
        return self.business_name

    @property
    def is_verified(self):
        return self.verified_at is not None

    def mark_verified(self):
        self.verified_at = timezone.now()
        self.save(update_fields=["verified_at", "updated_at"])

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.business_name) or "workspace"
            slug, i = base, 2
            while Workspace.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Member(TimeStampedModel):
    """Membership of a user in a workspace, carrying a role + permission flags."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MEMBER = "member", "Team member"
        SECOND_SHOOTER = "second_shooter", "Second shooter"
        EDITOR = "editor", "Editor"
        ASSISTANT = "assistant", "Assistant"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.OWNER)
    permissions = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("workspace", "user")

    def __str__(self):
        return f"{self.user} @ {self.workspace} ({self.role})"
