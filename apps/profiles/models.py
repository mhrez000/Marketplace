from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.workspaces.models import Workspace

CATEGORY_CHOICES = [
    ("weddings", "Weddings"),
    ("events", "Events"),
    ("real-estate", "Real Estate"),
    ("business", "Business & Brand"),
    ("family", "Family & Portrait"),
    ("content", "Content & Reels"),
]

ACCENTS = [("navy", "Navy"), ("teal", "Teal"), ("sky", "Sky")]


class CreativeProfile(TimeStampedModel):
    """The public, bookable profile for a workspace (build plan §8.2)."""

    workspace = models.OneToOneField(
        Workspace, on_delete=models.CASCADE, related_name="profile"
    )
    headline = models.CharField(max_length=160, blank=True)
    bio = models.TextField(blank=True)

    # Location (suburb-level; PostGIS geometry added in Phase 2).
    suburb = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, default="Melbourne")
    state = models.CharField(max_length=8, default="VIC")
    service_radius_km = models.PositiveIntegerField(default=40)
    # Base location for distance search (PostGIS PointField later).
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    primary_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="weddings")
    styles = models.CharField(max_length=200, blank=True, help_text="Comma-separated style tags")
    equipment = models.CharField(max_length=200, blank=True)
    languages = models.CharField(max_length=120, blank=True, default="English")

    starting_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    response_time_hours = models.PositiveIntegerField(default=24)

    cover_image = models.ImageField(upload_to="covers/", blank=True, null=True)
    accent = models.CharField(max_length=8, choices=ACCENTS, default="navy")
    is_featured = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Profile: {self.workspace.business_name}"

    @property
    def style_list(self):
        return [s.strip() for s in self.styles.split(",") if s.strip()]

    @property
    def location_label(self):
        bits = [b for b in [self.suburb, self.state] if b]
        return ", ".join(bits)


class Service(TimeStampedModel):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="services")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.title


class Package(TimeStampedModel):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name="packages")
    name = models.CharField(max_length=120)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True)
    inclusions = models.TextField(blank=True, help_text="One inclusion per line")

    class Meta:
        ordering = ["base_price"]

    def __str__(self):
        return f"{self.name} (${self.base_price})"

    @property
    def inclusion_list(self):
        return [line.strip() for line in self.inclusions.splitlines() if line.strip()]


class Availability(TimeStampedModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        BLOCKED = "blocked", "Blocked"
        BOOKED = "booked", "Booked"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="availability")
    date = models.DateField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.AVAILABLE)

    class Meta:
        unique_together = ("workspace", "date")
        ordering = ["date"]

    def __str__(self):
        return f"{self.workspace} {self.date} ({self.status})"


class VerificationDocument(TimeStampedModel):
    class DocType(models.TextChoices):
        ABN = "abn", "ABN / business"
        INSURANCE = "insurance", "Public liability insurance"
        WWCC = "wwcc", "Working With Children Check"
        ID = "id", "Identity"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="documents")
    doc_type = models.CharField(max_length=12, choices=DocType.choices)
    file = models.FileField(upload_to="verification/", blank=True, null=True)
    reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_documents",
    )
    note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.get_doc_type_display()} — {self.workspace} ({self.status})"
