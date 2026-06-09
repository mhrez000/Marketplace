from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel, UUIDTimeStampedModel
from apps.enquiries.models import Enquiry, Quote
from apps.workspaces.models import Workspace


class Booking(UUIDTimeStampedModel):
    """The transactional spine. Status is an explicit state machine so illegal
    jumps (e.g. delivered-but-never-paid) are impossible (build plan §6, §10)."""

    class Status(models.TextChoices):
        NEW = "new", "New enquiry"
        QUOTE_SENT = "quote_sent", "Quote sent"
        QUOTE_ACCEPTED = "quote_accepted", "Quote accepted"
        CONTRACT_SENT = "contract_sent", "Contract sent"
        CONTRACT_SIGNED = "contract_signed", "Contract signed"
        DEPOSIT_PAID = "deposit_paid", "Deposit paid"
        CONFIRMED = "confirmed", "Booking confirmed"
        PLANNING = "planning", "Pre-shoot planning"
        SHOOT_COMPLETED = "shoot_completed", "Shoot completed"
        EDITING = "editing", "Editing in progress"
        DELIVERED = "delivered", "Gallery delivered"
        FINAL_PAID = "final_paid", "Final payment received"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        REFUNDED = "refunded", "Refunded"
        ARCHIVED = "archived", "Archived"

    # Allowed forward transitions (plus universal cancel/archive handled separately).
    TRANSITIONS = {
        Status.NEW: [Status.QUOTE_SENT],
        Status.QUOTE_SENT: [Status.QUOTE_ACCEPTED, Status.NEW],
        Status.QUOTE_ACCEPTED: [Status.CONTRACT_SENT],
        Status.CONTRACT_SENT: [Status.CONTRACT_SIGNED],
        Status.CONTRACT_SIGNED: [Status.DEPOSIT_PAID],
        Status.DEPOSIT_PAID: [Status.CONFIRMED],
        Status.CONFIRMED: [Status.PLANNING, Status.SHOOT_COMPLETED],
        Status.PLANNING: [Status.SHOOT_COMPLETED],
        Status.SHOOT_COMPLETED: [Status.EDITING],
        Status.EDITING: [Status.DELIVERED],
        Status.DELIVERED: [Status.FINAL_PAID],
        Status.FINAL_PAID: [Status.COMPLETED],
        Status.COMPLETED: [Status.ARCHIVED],
    }

    enquiry = models.ForeignKey(Enquiry, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")
    quote = models.ForeignKey(Quote, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="bookings")

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    title = models.CharField(max_length=180, blank=True)
    event_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=180, blank=True)

    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    review_reminded_at = models.DateTimeField(null=True, blank=True)
    internal_notes = models.TextField(blank=True)

    def __str__(self):
        return self.title or f"Booking {self.pk}"

    def can_transition(self, new_status):
        return new_status in self.TRANSITIONS.get(self.status, [])

    def transition(self, new_status, force=False):
        """Advance the booking. Returns True if it moved."""
        terminal = {self.Status.CANCELLED, self.Status.REFUNDED, self.Status.ARCHIVED}
        if force or new_status in terminal or self.can_transition(new_status):
            self.status = new_status
            self.save(update_fields=["status", "updated_at"])
            return True
        return False

    @property
    def is_confirmed(self):
        confirmed_states = {
            self.Status.CONFIRMED, self.Status.PLANNING, self.Status.SHOOT_COMPLETED,
            self.Status.EDITING, self.Status.DELIVERED, self.Status.FINAL_PAID,
            self.Status.COMPLETED, self.Status.ARCHIVED,
        }
        return self.status in confirmed_states

    @property
    def is_complete(self):
        return self.status in {self.Status.COMPLETED, self.Status.ARCHIVED}

    @property
    def awaiting_review(self):
        return self.is_complete and not hasattr(self, "review")


class CalendarEvent(TimeStampedModel):
    class Type(models.TextChoices):
        SHOOT = "shoot", "Shoot"
        EDITING_DUE = "editing_due", "Editing due"
        PAYMENT_DUE = "payment_due", "Payment due"
        CONTRACT_DUE = "contract_due", "Contract due"
        BLOCKED = "blocked", "Blocked"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="calendar_events")
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, null=True, blank=True, related_name="events")
    event_type = models.CharField(max_length=14, choices=Type.choices, default=Type.SHOOT)
    title = models.CharField(max_length=180)
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    external_gcal_id = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["start"]

    def __str__(self):
        return f"{self.title} @ {self.start:%Y-%m-%d}"

    @property
    def is_overdue(self):
        return self.event_type in {self.Type.PAYMENT_DUE, self.Type.EDITING_DUE, self.Type.CONTRACT_DUE} and self.start < timezone.now()
