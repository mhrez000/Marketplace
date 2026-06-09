"""Quote lifecycle housekeeping: enforce expiry."""
from datetime import timedelta

from django.utils import timezone

from apps.notifications.models import notify

from .models import Enquiry, Quote


def expire_quotes():
    """Mark sent quotes past their expiry date as EXPIRED (idempotent)."""
    today = timezone.now().date()
    stale = Quote.objects.filter(status=Quote.Status.SENT, expires_at__lt=today).select_related(
        "enquiry", "enquiry__workspace", "enquiry__client")
    count = 0
    for q in stale:
        q.status = Quote.Status.EXPIRED
        q.save(update_fields=["status", "updated_at"])
        notify(q.enquiry.client,
               f"Your quote from {q.enquiry.workspace.business_name} has expired",
               url="/portal/", icon="clock")
        count += 1
    return count


def quote_expiry_reminders(days=2):
    """Nudge clients whose quote expires within `days`."""
    today = timezone.now().date()
    window = today + timedelta(days=days)
    count = 0
    for q in Quote.objects.filter(
        status=Quote.Status.SENT, expires_at__gte=today, expires_at__lte=window
    ).select_related("enquiry", "enquiry__workspace", "enquiry__client"):
        notify(q.enquiry.client,
               f"Your quote from {q.enquiry.workspace.business_name} expires {q.expires_at:%d %b} — accept it before it lapses",
               url="/portal/", icon="clock", email=True)
        count += 1
    return count
