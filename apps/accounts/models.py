from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractUser):
    """Email-first user.

    Username is kept (Django internals lean on it) but login is by email via
    allauth. A user can belong to multiple Workspaces (solo creative + a studio
    they second-shoot for) — that membership lives in apps.workspaces.
    """

    class RoleType(models.TextChoices):
        CLIENT = "client", _("Client")
        CREATIVE = "creative", _("Photographer / Videographer")
        STUDIO = "studio", _("Studio owner")
        ADMIN = "admin", _("Platform admin")

    email = models.EmailField(_("email address"), unique=True)
    phone = models.CharField(max_length=32, blank=True)
    role_type = models.CharField(
        max_length=16, choices=RoleType.choices, default=RoleType.CLIENT
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # email + password only on createsuperuser

    objects = UserManager()

    def __str__(self):
        return self.email or self.username

    def save(self, *args, **kwargs):
        # Keep username populated (unique) so Django admin & internals are happy.
        if not self.username:
            self.username = self.email
        super().save(*args, **kwargs)
