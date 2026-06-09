"""Run the housekeeping sweep once, now (sync).

    python manage.py housekeeping

This is the same task Celery Beat runs hourly once REDIS_URL is set.
"""
from django.core.management.base import BaseCommand

from apps.core.tasks import run_housekeeping


class Command(BaseCommand):
    help = "Expire quotes, mark overdue invoices, and raise all reminders."

    def handle(self, *args, **opts):
        summary = run_housekeeping()  # runs the task body synchronously
        self.stdout.write(self.style.SUCCESS(f"Housekeeping done: {summary}."))
