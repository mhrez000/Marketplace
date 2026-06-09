"""Raise delivery reminders for every workspace.

Run on a schedule (cron / Celery beat once that lands):
    python manage.py send_reminders
"""
from django.core.management.base import BaseCommand

from apps.production.services import backfill_for_workspace, generate_reminders
from apps.workspaces.models import Workspace


class Command(BaseCommand):
    help = "Generate in-app delivery reminders for due/overdue milestones."

    def handle(self, *args, **opts):
        total = 0
        for ws in Workspace.objects.all():
            backfill_for_workspace(ws)
            total += generate_reminders(ws)
        self.stdout.write(self.style.SUCCESS(f"Raised {total} reminder(s)."))
