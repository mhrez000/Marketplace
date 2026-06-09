"""Availability logic — the single source of truth for "is this creative free
on date X?".

Two things make a date unavailable:
  1. The creative manually BLOCKED it (holiday, day off).
  2. A CONFIRMED booking already holds it.

`Availability` rows are a denormalised cache (used for fast search + display);
the booking table is the real source of truth for "booked". We keep the cache in
sync on confirm/cancel.
"""
from django.utils import timezone

from .models import Availability

# Booking statuses that genuinely hold a date (deposit paid onward).
HELD_STATES = [
    "confirmed", "planning", "shoot_completed", "editing",
    "delivered", "final_paid", "completed", "archived",
]


def _other_confirmed_booking(workspace, on_date, exclude_booking=None):
    from apps.bookings.models import Booking

    qs = Booking.objects.filter(workspace=workspace, event_date=on_date, status__in=HELD_STATES)
    if exclude_booking is not None:
        qs = qs.exclude(pk=exclude_booking.pk)
    return qs.exists()


def is_blocked(workspace, on_date):
    return Availability.objects.filter(
        workspace=workspace, date=on_date, status=Availability.Status.BLOCKED
    ).exists()


def is_available(workspace, on_date, *, exclude_booking=None):
    """True if the workspace can take a booking on `on_date`."""
    if not on_date:
        return True
    if is_blocked(workspace, on_date):
        return False
    return not _other_confirmed_booking(workspace, on_date, exclude_booking=exclude_booking)


def mark_booked(workspace, on_date):
    if not on_date:
        return
    Availability.objects.update_or_create(
        workspace=workspace, date=on_date,
        defaults={"status": Availability.Status.BOOKED},
    )


def free_date(workspace, on_date, *, exclude_booking=None):
    """Release a date back to available — unless another confirmed booking still
    holds it. Never touches a manual BLOCK."""
    if not on_date:
        return
    if _other_confirmed_booking(workspace, on_date, exclude_booking=exclude_booking):
        return
    av = Availability.objects.filter(workspace=workspace, date=on_date).first()
    if av and av.status == Availability.Status.BOOKED:
        av.status = Availability.Status.AVAILABLE
        av.save(update_fields=["status", "updated_at"])


def block(workspace, on_date):
    if not on_date or _other_confirmed_booking(workspace, on_date):
        return None  # can't block a date that's already booked
    av, _ = Availability.objects.update_or_create(
        workspace=workspace, date=on_date,
        defaults={"status": Availability.Status.BLOCKED},
    )
    return av


def unblock(workspace, on_date):
    Availability.objects.filter(
        workspace=workspace, date=on_date, status=Availability.Status.BLOCKED
    ).update(status=Availability.Status.AVAILABLE)


def unavailable_dates(workspace, *, from_date=None, limit=None):
    """Upcoming dates the creative can't take — blocked + booked — for display."""
    today = from_date or timezone.now().date()
    blocked = set(Availability.objects.filter(
        workspace=workspace, status=Availability.Status.BLOCKED, date__gte=today
    ).values_list("date", flat=True))

    from apps.bookings.models import Booking
    booked = set(Booking.objects.filter(
        workspace=workspace, event_date__gte=today, status__in=HELD_STATES
    ).values_list("event_date", flat=True))

    dates = sorted(blocked | booked)
    return dates[:limit] if limit else dates


def blocked_dates(workspace, *, from_date=None):
    today = from_date or timezone.now().date()
    return list(Availability.objects.filter(
        workspace=workspace, status=Availability.Status.BLOCKED, date__gte=today
    ).order_by("date"))


def completeness(workspace):
    """A profile-quality checklist + whether the profile is good enough to be
    listed in search (the quality gate)."""
    from .models import Package
    p = getattr(workspace, "profile", None)
    has_pkg = Package.objects.filter(service__workspace=workspace).exists()
    items = [
        ("Add a bio", bool(p and p.bio)),
        ("Add a headline", bool(p and p.headline)),
        ("Set a starting price", bool(p and p.starting_price)),
        ("Add at least one package", has_pkg),
        ("Get verified (ABN / insurance)", workspace.is_verified),
    ]
    done = sum(1 for _, ok in items if ok)
    listable = bool(p and p.bio and p.starting_price and has_pkg)
    return {
        "pct": int(done / len(items) * 100),
        "items": items,
        "missing": [label for label, ok in items if not ok],
        "listable": listable,
    }


def is_listable(workspace):
    return completeness(workspace)["listable"]


def filter_listable(profile_qs):
    """Restrict a CreativeProfile queryset to profiles complete enough to rank:
    a bio, a starting price, and at least one package."""
    from .models import Package
    pkg_ws_ids = Package.objects.values_list("service__workspace_id", flat=True).distinct()
    return profile_qs.exclude(bio="").filter(starting_price__gt=0, workspace_id__in=pkg_ws_ids)


def availability_calendar(workspace, *, months=2):
    """Server-rendered month grids of available / booked / blocked / past days."""
    import calendar as _cal

    from apps.bookings.models import Booking
    today = timezone.now().date()
    blocked = set(Availability.objects.filter(
        workspace=workspace, status=Availability.Status.BLOCKED, date__gte=today
    ).values_list("date", flat=True))
    booked = set(Booking.objects.filter(
        workspace=workspace, event_date__gte=today, status__in=HELD_STATES
    ).values_list("event_date", flat=True))

    grids = []
    y, m = today.year, today.month
    cal = _cal.Calendar(firstweekday=0)  # Monday-first (AU)
    for _ in range(months):
        weeks = []
        for week in cal.monthdatescalendar(y, m):
            days = []
            for d in week:
                if d < today:
                    status = "past"
                elif d in blocked:
                    status = "blocked"
                elif d in booked:
                    status = "booked"
                else:
                    status = "available"
                days.append({"date": d, "day": d.day, "in_month": d.month == m, "status": status})
            weeks.append(days)
        grids.append({"label": f"{_cal.month_name[m]} {y}", "weeks": weeks})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return grids


def avg_response_hours(workspace):
    """Mean time-to-first-response across answered enquiries, or None."""
    from apps.enquiries.models import Enquiry
    answered = Enquiry.objects.filter(workspace=workspace, responded_at__isnull=False)
    hours = [e.response_hours for e in answered if e.response_hours is not None]
    if not hours:
        return None
    return sum(hours) / len(hours)


def unavailable_workspace_ids(on_date):
    """Workspace ids that are NOT free on `on_date` — for search exclusion."""
    if not on_date:
        return []
    blocked = set(Availability.objects.filter(
        date=on_date, status__in=[Availability.Status.BLOCKED, Availability.Status.BOOKED]
    ).values_list("workspace_id", flat=True))

    from apps.bookings.models import Booking
    booked = set(Booking.objects.filter(
        event_date=on_date, status__in=HELD_STATES
    ).values_list("workspace_id", flat=True))
    return list(blocked | booked)
