"""Post-production logic: generate delivery milestones per booking, keep them in
sync with the booking flow, and raise reminders.

Milestone templates encode real-world turnaround expectations by shoot type
(build research): real estate next-day; events/family ~1-2 weeks; weddings
4-8 weeks; brand video ~3 weeks. Offsets are DAYS AFTER the event/shoot date.
Each tuple: (kind, day_offset, title, is_client_facing, reminder_days_before).
"""
from datetime import timedelta

from django.utils import timezone

from apps.bookings.models import CalendarEvent
from apps.notifications.models import notify

from .models import Deliverable

K = Deliverable.Kind

MILESTONE_TEMPLATES = {
    "weddings": [
        (K.BACKUP, 1, "Back up & import RAW files", False, 1),
        (K.SNEAK_PEEK, 3, "Deliver sneak peek (5–10 images)", True, 1),
        (K.CULL, 7, "Cull & select final images", False, 2),
        (K.EDITING, 28, "Finish editing", False, 5),
        (K.FINAL_DELIVERY, 42, "Deliver full gallery", True, 7),
        (K.FINAL_PAYMENT, 42, "Final payment due", True, 3),
        (K.ALBUM, 70, "Album design proof to client", True, 7),
        (K.ARCHIVE, 90, "Archive project & clear cards", False, 3),
    ],
    "events": [
        (K.BACKUP, 0, "Back up & import", False, 1),
        (K.SNEAK_PEEK, 2, "Send a few teaser shots", True, 1),
        (K.CULL, 4, "Cull & select", False, 2),
        (K.EDITING, 10, "Finish editing", False, 3),
        (K.FINAL_DELIVERY, 14, "Deliver gallery", True, 3),
        (K.FINAL_PAYMENT, 14, "Final payment due", True, 2),
        (K.ARCHIVE, 45, "Archive & cleanup", False, 3),
    ],
    "real-estate": [
        (K.BACKUP, 0, "Back up & import", False, 1),
        (K.EDITING, 1, "Edit / HDR blend & retouch", False, 1),
        (K.FINAL_DELIVERY, 1, "Deliver gallery (next business day)", True, 1),
        (K.FINAL_PAYMENT, 2, "Final payment due", True, 1),
    ],
    "business": [
        (K.BACKUP, 0, "Back up & import footage", False, 1),
        (K.CULL, 2, "Select & log clips", False, 2),
        (K.SEND_TO_EDITOR, 3, "Send to editor", False, 2),
        (K.EDITOR_RETURN, 12, "Editor returns first cut", False, 3),
        (K.PROOFING, 16, "Client review of draft", True, 2),
        (K.FINAL_DELIVERY, 21, "Deliver final film & cutdowns", True, 5),
        (K.FINAL_PAYMENT, 21, "Final payment due", True, 3),
        (K.ARCHIVE, 60, "Archive project", False, 3),
    ],
    "family": [
        (K.BACKUP, 0, "Back up & import", False, 1),
        (K.CULL, 3, "Cull & select", False, 2),
        (K.EDITING, 9, "Finish editing", False, 3),
        (K.FINAL_DELIVERY, 14, "Deliver gallery", True, 3),
        (K.FINAL_PAYMENT, 14, "Final payment due", True, 2),
        (K.ARCHIVE, 45, "Archive & cleanup", False, 3),
    ],
    "content": [
        (K.BACKUP, 0, "Back up & import", False, 1),
        (K.CULL, 2, "Select clips", False, 1),
        (K.EDITING, 6, "Edit reels", False, 2),
        (K.FINAL_DELIVERY, 10, "Deliver final content", True, 3),
        (K.FINAL_PAYMENT, 10, "Final payment due", True, 2),
    ],
}


def _category_for(booking):
    if booking.enquiry and booking.enquiry.event_type:
        return booking.enquiry.event_type
    profile = getattr(booking.workspace, "profile", None)
    return profile.primary_category if profile else "events"


def generate_deliverables(booking, *, force=False):
    """Create the milestone set for a booking from its event-type template.
    Idempotent unless force=True. No-op without an event date."""
    if not booking.event_date:
        return []
    if booking.deliverables.exists() and not force:
        return list(booking.deliverables.all())

    template = MILESTONE_TEMPLATES.get(_category_for(booking), MILESTONE_TEMPLATES["events"])
    created = []
    for order, (kind, offset, title, client_facing, remind) in enumerate(template):
        d, _ = Deliverable.objects.get_or_create(
            booking=booking, kind=kind,
            defaults=dict(
                workspace=booking.workspace, title=title,
                due_date=booking.event_date + timedelta(days=offset),
                is_client_facing=client_facing, reminder_days_before=remind,
                sort_order=order,
            ),
        )
        created.append(d)

    _sync_calendar(booking)
    return created


def _sync_calendar(booking):
    """Surface the key delivery/payment deadlines on the calendar too."""
    for kind, ev_type, label in [
        (K.FINAL_DELIVERY, CalendarEvent.Type.EDITING_DUE, "Gallery delivery due"),
        (K.FINAL_PAYMENT, CalendarEvent.Type.PAYMENT_DUE, "Final payment due"),
    ]:
        d = booking.deliverables.filter(kind=kind).first()
        if d and d.due_date:
            CalendarEvent.objects.get_or_create(
                workspace=booking.workspace, booking=booking, event_type=ev_type,
                defaults={"title": f"{label} — {booking.title}",
                          "start": timezone.make_aware(
                              timezone.datetime.combine(d.due_date, timezone.datetime.min.time().replace(hour=17)))},
            )


def mark_done(booking, kind):
    for d in booking.deliverables.filter(kind=kind):
        d.mark_done()


def mark_all_done(booking):
    booking.deliverables.exclude(status=Deliverable.Status.DONE).update(
        status=Deliverable.Status.DONE, completed_at=timezone.now())


def backfill_for_workspace(workspace):
    """Ensure post-shoot bookings have deliverables (covers pre-existing data).
    Completed bookings get everything marked done."""
    from apps.bookings.models import Booking

    post_states = [
        Booking.Status.CONFIRMED, Booking.Status.PLANNING, Booking.Status.SHOOT_COMPLETED,
        Booking.Status.EDITING, Booking.Status.DELIVERED, Booking.Status.FINAL_PAID,
        Booking.Status.COMPLETED, Booking.Status.ARCHIVED,
    ]
    for booking in workspace.bookings.filter(status__in=post_states, event_date__isnull=False):
        if not booking.deliverables.exists():
            generate_deliverables(booking)
            if booking.is_complete:
                mark_all_done(booking)
            elif booking.status in {Booking.Status.DELIVERED, Booking.Status.FINAL_PAID}:
                mark_done(booking, K.FINAL_DELIVERY)


def generate_reminders(workspace):
    """Raise in-app reminders for deliverables that are overdue or entering
    their reminder window. Throttled to once per ~20h per deliverable."""
    now = timezone.now()
    today = now.date()
    raised = 0
    pending = workspace.deliverables.exclude(
        status=Deliverable.Status.DONE).filter(due_date__isnull=False).select_related("booking")

    for d in pending:
        in_window = d.due_date <= today + timedelta(days=d.reminder_days_before)
        if not in_window:
            continue
        if d.reminded_at and (now - d.reminded_at) < timedelta(hours=20):
            continue
        if d.is_overdue:
            verb = f"Overdue: {d.title} — {d.booking.title} (was due {d.due_date:%d %b})"
            icon = "alert"
        else:
            days = d.days_until
            when = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
            verb = f"Reminder: {d.title} — {d.booking.title} due {when}"
            icon = "clock"
        notify(workspace.owner, verb, url="/app/deliveries/", icon=icon)
        d.reminded_at = now
        d.save(update_fields=["reminded_at", "updated_at"])
        raised += 1
    return raised
