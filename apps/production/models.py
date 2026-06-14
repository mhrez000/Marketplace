from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel
from apps.workspaces.models import Workspace


class Deliverable(TimeStampedModel):
    """A single post-shoot production milestone for a booking — back-up, cull,
    sneak peek, edit, final delivery, etc. — with a due date, status and its own
    reminder window. Auto-generated per booking from event-type templates."""

    class Kind(models.TextChoices):
        BACKUP = "backup", "Back up & import"
        CULL = "cull", "Cull & select"
        SNEAK_PEEK = "sneak_peek", "Sneak peek"
        SEND_TO_EDITOR = "send_to_editor", "Send to editor"
        EDITOR_RETURN = "editor_return", "Editor return"
        EDITING = "editing", "Editing"
        PROOFING = "proofing", "Client proofing"
        ALBUM = "album", "Album design"
        FINAL_DELIVERY = "final_delivery", "Final gallery delivery"
        FINAL_PAYMENT = "final_payment", "Final payment due"
        ARCHIVE = "archive", "Archive & cleanup"
        CUSTOM = "custom", "Task"

    class Status(models.TextChoices):
        PENDING = "pending", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        DONE = "done", "Done"

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="deliverables")
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="deliverables")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=160)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_client_facing = models.BooleanField(default=False)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="deliverables",
    )
    reminder_days_before = models.PositiveSmallIntegerField(default=2)
    reminded_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["due_date", "sort_order"]

    def __str__(self):
        return f"{self.title} — {self.booking.title}"

    # ── status helpers ──────────────────────────────────────────────────────
    @property
    def is_done(self):
        return self.status == self.Status.DONE

    @property
    def is_overdue(self):
        return (not self.is_done and self.due_date is not None
                and self.due_date < timezone.now().date())

    @property
    def days_until(self):
        if not self.due_date:
            return None
        return (self.due_date - timezone.now().date()).days

    @property
    def is_due_soon(self):
        d = self.days_until
        return (not self.is_done and d is not None and 0 <= d <= 7)

    @property
    def urgency(self):
        if self.is_done:
            return "done"
        if self.is_overdue:
            return "overdue"
        d = self.days_until
        if d is not None and d <= 2:
            return "today"      # due within 2 days
        if self.is_due_soon:
            return "soon"
        return "upcoming"

    @property
    def due_label(self):
        d = self.days_until
        if d is None:
            return "No date"
        if self.is_done:
            return "Done"
        if d < 0:
            return f"{abs(d)} day{'s' if abs(d) != 1 else ''} overdue"
        if d == 0:
            return "Due today"
        if d == 1:
            return "Due tomorrow"
        return f"In {d} days"

    def mark_done(self):
        self.status = self.Status.DONE
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def reopen(self):
        self.status = self.Status.PENDING
        self.completed_at = None
        self.save(update_fields=["status", "completed_at", "updated_at"])


class DeliverableTemplate(TimeStampedModel):
    """A creative's reusable checklist item. When a workspace has any of these,
    new bookings are seeded from this list instead of the built-in milestones."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="task_templates")
    label = models.CharField(max_length=160)
    day_offset = models.IntegerField(default=7, help_text="Days after the shoot date it's due")
    is_client_facing = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "day_offset", "id"]

    def __str__(self):
        return f"{self.label} (+{self.day_offset}d)"
