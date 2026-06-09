"""Nightly housekeeping — run on a schedule (cron / Celery beat later):

    python manage.py housekeeping

Expires stale quotes, marks overdue invoices, generates delivery reminders,
quote-expiry nudges and payment reminders across every workspace.
"""
from django.core.management.base import BaseCommand

from apps.enquiries.services import (expire_quotes, nudge_stale_enquiries,
                                     quote_expiry_reminders)
from apps.payments.services import mark_overdue_invoices, payment_reminders
from apps.production.services import backfill_for_workspace, generate_reminders
from apps.reviews.services import review_reminders
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Expire quotes, mark overdue invoices, and raise all reminders."

    def handle(self, *args, **opts):
        expired = expire_quotes()
        overdue = mark_overdue_invoices()

        delivery_reminders = 0
        for ws in Workspace.objects.all():
            backfill_for_workspace(ws)
            delivery_reminders += generate_reminders(ws)

        quote_nudges = quote_expiry_reminders()
        pay_reminders = payment_reminders()
        lead_nudges = nudge_stale_enquiries()
        review_nudges = review_reminders()

        self.stdout.write(self.style.SUCCESS(
            f"Housekeeping done: {expired} quote(s) expired, {overdue} invoice(s) overdue, "
            f"{delivery_reminders} delivery + {quote_nudges} quote + {pay_reminders} payment "
            f"+ {lead_nudges} stale-lead + {review_nudges} review reminder(s)."
        ))
