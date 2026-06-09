"""Review chasing — reviews are the marketplace's trust + ranking engine, so a
single 'leave a review?' prompt isn't enough. Nudge completed bookings that
still have no review."""
from datetime import timedelta

from django.utils import timezone

from apps.bookings.models import Booking
from apps.notifications.models import notify


def review_reminders(max_chases=3):
    """Remind clients to review completed bookings (throttled ~20h/booking)."""
    now = timezone.now()
    count = 0
    completed = Booking.objects.filter(status=Booking.Status.COMPLETED).select_related(
        "workspace", "client")
    for b in completed:
        if hasattr(b, "review"):
            continue
        if b.review_reminded_at and (now - b.review_reminded_at) < timedelta(hours=20):
            continue
        notify(b.client,
               f"How was {b.workspace.business_name}? Leave a quick review to help others.",
               url=f"/portal/booking/{b.id}/", icon="bell", email=True)
        b.review_reminded_at = now
        b.save(update_fields=["review_reminded_at", "updated_at"])
        count += 1
    return count
