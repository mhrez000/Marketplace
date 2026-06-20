"""Local development settings."""
import os

from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]

# GitHub Codespaces: requests arrive via the *.app.github.dev forwarding proxy.
if os.environ.get("CODESPACES"):
    ALLOWED_HOSTS.append(".app.github.dev")
    CSRF_TRUSTED_ORIGINS = ["https://*.app.github.dev"]

# Email goes to the console in dev (allauth verification, notifications).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Allow Django Debug niceties without extra deps.
INTERNAL_IPS = ["127.0.0.1"]

# Throttling is a production control — disable locally (and the test suite runs
# under these settings, so this keeps it from 429-ing repeated logins). A None
# rate short-circuits SimpleRateThrottle. Prod keeps base's real rates.
REST_FRAMEWORK = {**REST_FRAMEWORK,  # noqa: F405
                  "DEFAULT_THROTTLE_RATES": {"anon": None, "user": None,
                                             "login": None, "register": None}}
