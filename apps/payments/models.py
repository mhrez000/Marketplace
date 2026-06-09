from decimal import Decimal

from django.db import models

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel
from apps.workspaces.models import Workspace

PLATFORM_FEE_RATE = Decimal("0.015")  # ~1.5% booking-protection fee (build plan §20)


class Invoice(TimeStampedModel):
    class Type(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        MILESTONE = "milestone", "Milestone"
        FINAL = "final", "Final balance"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        VOID = "void", "Void"

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="invoices")
    invoice_type = models.CharField(max_length=10, choices=Type.choices, default=Type.DEPOSIT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    gst = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.SENT)
    reminded_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.get_invoice_type_display()} ${self.amount} — {self.booking}"

    @property
    def is_paid(self):
        return self.status == self.Status.PAID

    @property
    def is_overdue(self):
        from django.utils import timezone
        return (self.status in {self.Status.SENT, self.Status.OVERDUE}
                and self.due_date is not None and self.due_date < timezone.now().date())


class Payment(TimeStampedModel):
    """A payment against an invoice. `provider` lets us swap the test gateway
    for Stripe without touching callers."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=20, default="test")  # test | stripe
    provider_ref = models.CharField(max_length=120, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Payment ${self.amount} ({self.status})"

    def save(self, *args, **kwargs):
        # Platform fee is computed server-side, never client-supplied.
        if not self.platform_fee:
            self.platform_fee = (self.amount * PLATFORM_FEE_RATE).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


class Subscription(TimeStampedModel):
    class Plan(models.TextChoices):
        FREE = "free", "Listed (Free)"
        PRO = "pro", "Pro"
        STUDIO = "studio", "Studio"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRIALING = "trialing", "Trialing"
        CANCELLED = "cancelled", "Cancelled"

    workspace = models.OneToOneField(Workspace, on_delete=models.CASCADE, related_name="subscription")
    plan = models.CharField(max_length=8, choices=Plan.choices, default=Plan.FREE)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    seats = models.PositiveIntegerField(default=1)
    period_end = models.DateField(null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return f"{self.workspace} — {self.get_plan_display()}"
