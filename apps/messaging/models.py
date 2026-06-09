from django.conf import settings
from django.db import models

from apps.bookings.models import Booking
from apps.core.models import TimeStampedModel
from apps.enquiries.models import Enquiry
from apps.workspaces.models import Workspace


class Thread(TimeStampedModel):
    """A conversation between a client and a workspace, optionally tied to an
    enquiry/booking."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="threads")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="threads")
    enquiry = models.ForeignKey(Enquiry, on_delete=models.SET_NULL, null=True, blank=True, related_name="threads")
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name="threads")
    subject = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return self.subject or f"Thread {self.pk}"

    @property
    def last_message(self):
        return self.messages.order_by("-created_at").first()

    def is_participant(self, user):
        return user.id in (self.client_id, self.workspace.owner_id)

    def other_party(self, user):
        return self.workspace.owner if user.id == self.client_id else self.client

    def other_label(self, user):
        """Who the conversation is *with*, from `user`'s point of view."""
        if user.id == self.client_id:
            return self.workspace.business_name
        return self.client.get_full_name() or self.client.email

    def unread_for(self, user):
        return self.messages.filter(read_at__isnull=True).exclude(sender=user).count()

    def mark_read_for(self, user):
        from django.utils import timezone
        self.messages.filter(read_at__isnull=True).exclude(sender=user).update(read_at=timezone.now())


class Message(TimeStampedModel):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_messages")
    body = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender}: {self.body[:40]}"
