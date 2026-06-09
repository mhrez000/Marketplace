"""Celery app for Lens.

Runs FULLY SYNCHRONOUSLY when no broker is configured (CELERY_TASK_ALWAYS_EAGER
in settings) — so the app behaves exactly as before without Redis. Set REDIS_URL
to switch on real background processing + the Beat schedule.

Run (only needed once REDIS_URL is set):
    celery -A config worker -l info
    celery -A config beat   -l info     # the hourly housekeeping scheduler
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("lens")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
