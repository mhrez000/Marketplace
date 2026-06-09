"""Quote lifecycle housekeeping: enforce expiry."""
from datetime import timedelta

from django.utils import timezone

from apps.notifications.models import dispatch, notify

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


def nudge_stale_enquiries(hours=24):
    """Nudge creatives sitting on unanswered enquiries — responsiveness is the
    marketplace's core promise. Throttled per enquiry."""
    from datetime import timedelta

    from django.utils import timezone

    now = timezone.now()
    cutoff = now - timedelta(hours=hours)
    count = 0
    stale = Enquiry.objects.filter(status=Enquiry.Status.NEW, created_at__lt=cutoff).select_related(
        "workspace", "client")
    for e in stale:
        if e.nudged_at and (now - e.nudged_at) < timedelta(hours=20):
            continue
        days = int(e.age_hours // 24)
        ago = f"{days}d" if days else f"{int(e.age_hours)}h"
        dispatch("lead_waiting", e.workspace.owner,
                 verb=f"Still waiting: {e.client.email}'s enquiry from {ago} ago — reply to keep your ranking.",
                 url="/app/leads/")
        e.nudged_at = now
        e.save(update_fields=["nudged_at", "updated_at"])
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
