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

    class Meta:
        verbose_name_plural = "enquiries"

    def __str__(self):
        return f"Enquiry from {self.client} → {self.workspace}"


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

    def recalc(self, deposit_pct=Decimal("0.25")):
        """Compute subtotal/GST/total from line items, server-side only."""
        subtotal = sum(Decimal(str(li.get("amount", 0))) for li in self.line_items)
        self.subtotal = subtotal
        self.gst = (subtotal * GST_RATE).quantize(Decimal("0.01"))
        self.total = subtotal + self.gst
        self.deposit_amount = (self.total * deposit_pct).quantize(Decimal("0.01"))
        return self
