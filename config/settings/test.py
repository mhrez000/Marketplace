"""Test settings — fast, isolated."""
from .base import *  # noqa: F401,F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}

# Disable DRF throttling in tests (a None rate short-circuits SimpleRateThrottle)
# so the suite can log in / hit endpoints freely.
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES":  # noqa: F405
                  {"anon": None, "user": None, "login": None, "register": None}}

# Plain static storage — no manifest/collectstatic needed in tests.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
