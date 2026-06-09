from decimal import Decimal

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.profiles.models import CATEGORY_CHOICES, Package
from apps.workspaces.models import Workspace

GST_RATE = Decimal("0.10")  # Australian GST


class Enquiry(TimeStampedModel):
    class Status(models.TextChoices):
        NEW = "new", "New enquiry"
        QUOTED = "quoted", "Quote sent"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        ARCHIVED = "archived", "Archived"

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enquiries"
    )
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="enquiries")
    event_type = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="weddings")
    event_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=160, blank=True)
    budget_band = models.CharField(max_length=40, blank=True)
    message = models.TextField()
    source = models.CharField(max_length=40, default="marketplace")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    responded_at = models.DateTimeField(null=True, blank=True)  # first creative reply
    nudged_at = models.DateTimeField(null=True, blank=True)     # last "you have a lead waiting"

    class Meta:
        verbose_name_plural = "enquiries"

    def __str__(self):
        return f"Enquiry from {self.client} → {self.workspace}"

    def mark_responded(self):
        if self.responded_at is None:
            from django.utils import timezone
            self.responded_at = timezone.now()
            self.save(update_fields=["responded_at", "updated_at"])

    @property
    def response_hours(self):
        if not self.responded_at:
            return None
        return max(0.0, (self.responded_at - self.created_at).total_seconds() / 3600)

    @property
    def age_hours(self):
        from django.utils import timezone
        return (timezone.now() - self.created_at).total_seconds() / 3600

    @property
    def is_stale(self):
        return self.status == self.Status.NEW and self.age_hours > 24

    @property
    def age_label(self):
        h = self.age_hours
        if h < 1:
            return "just now"
        if h < 24:
            return f"{int(h)}h ago"
        return f"{int(h // 24)}d ago"


class Quote(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"
        EXPIRED = "expired", "Expired"

    enquiry = models.ForeignKey(Enquiry, on_delete=models.CASCADE, related_name="quotes")
    package = models.ForeignKey(Package, on_delete=models.SET_NULL, null=True, blank=True)
    title = models.CharField(max_length=160)
    # line_items: list of {"label": str, "amount": float}
    line_items = models.JSONField(default=list, blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    expires_at = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} — ${self.total}"

    @property
    def is_open(self):
        return self.status in {self.Status.SENT, self.Status.DRAFT}

    @property
    def is_expired(self):
        from django.utils import timezone
        return (self.is_open and self.expires_at is not None
                and self.expires_at < timezone.now().date())

    @property
    def days_to_expiry(self):
        if not self.expires_at:
            return None
        from django.utils import timezone
        return (self.expires_at - timezone.now().date()).days

    def recalc(self, deposit_pct=Decimal("0.25")):
        """Compute subtotal/GST/total from line items, server-side only."""
        subtotal = sum(Decimal(str(li.get("amount", 0))) for li in self.line_items)
        self.subtotal = subtotal
        self.gst = (subtotal * GST_RATE).quantize(Decimal("0.01"))
        self.total = subtotal + self.gst
        self.deposit_amount = (self.total * deposit_pct).quantize(Decimal("0.01"))
        return self
