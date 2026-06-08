from django.conf import settings
from django.db import models

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel
from apps.workspaces.models import Workspace


class Client(TimeStampedModel):
    """CRM lens on a user who books a given workspace."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="clients")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="client_records", null=True, blank=True)
    name = models.CharField(max_length=160)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    tags = models.CharField(max_length=200, blank=True)
    lead_source = models.CharField(max_length=60, blank=True, default="marketplace")
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("workspace", "user")

    def __str__(self):
        return self.name

    @property
    def lifetime_value(self):
        from apps.payments.models import Payment
        agg = Payment.objects.filter(
            invoice__booking__workspace=self.workspace,
            invoice__booking__client=self.user,
            status=Payment.Status.SUCCEEDED,
        ).aggregate(total=models.Sum("amount"))
        return agg["total"] or 0


class Task(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        DONE = "done", "Done"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="tasks")
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, null=True, blank=True, related_name="tasks")
    title = models.CharField(max_length=200)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ["status", "due_date"]

    def __str__(self):
        return self.title
