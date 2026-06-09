"""Scheduled background tasks.

`run_housekeeping` is the single source of truth for the nightly/hourly sweep —
called by the `housekeeping` management command (sync) and by Celery Beat
(async, once REDIS_URL is set).
"""
from celery import shared_task


@shared_task(name="apps.core.tasks.run_housekeeping")
def run_housekeeping():
    """Expire quotes, mark overdue invoices, and raise every reminder. Returns a
    summary string."""
    from apps.enquiries.services import (expire_quotes, nudge_stale_enquiries,
                                         quote_expiry_reminders)
    from apps.payments.services import mark_overdue_invoices, payment_reminders
    from apps.production.services import backfill_for_workspace, generate_reminders
    from apps.reviews.services import review_reminders
    from apps.workspaces.models import Workspace

    expired = expire_quotes()
    overdue = mark_overdue_invoices()

    delivery = 0
    for ws in Workspace.objects.all():
        backfill_for_workspace(ws)
        delivery += generate_reminders(ws)

    quote = quote_expiry_reminders()
    pay = payment_reminders()
    leads = nudge_stale_enquiries()
    reviews = review_reminders()

    return (f"{expired} quote(s) expired, {overdue} invoice(s) overdue, "
            f"{delivery} delivery + {quote} quote + {pay} payment + {leads} stale-lead "
            f"+ {reviews} review reminder(s)")
