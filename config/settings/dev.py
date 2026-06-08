"""Local development settings."""
from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]

# Email goes to the console in dev (allauth verification, notifications).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Allow Django Debug niceties without extra deps.
INTERNAL_IPS = ["127.0.0.1"]
