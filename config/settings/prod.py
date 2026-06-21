"""Production settings (Fly.io, Sydney region per build plan)."""
import os

from .base import *  # noqa: F401,F403

DEBUG = False

# Fail fast: never let production boot with base's insecure dev fallback key.
# `env("SECRET_KEY")` raises ImproperlyConfigured if the secret is unset, so a
# misconfigured deploy crashes loudly instead of silently signing cookies and
# password-reset tokens with a public, committed default.
SECRET_KEY = env("SECRET_KEY")  # noqa: F405

# Trust the platform's proxy for HTTPS detection.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
# Explicit cookie SameSite (Lax is Django's default, but pin it so it can't drift).
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
# NOTE: a Content-Security-Policy is recommended but deferred — the app uses inline
# scripts (Alpine/HTMX) and CDN assets (FullCalendar, Google Fonts), so a strict CSP
# needs per-source allowlisting + nonces to avoid breaking pages. Track separately.

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405

# Fly.io sets FLY_APP_NAME — derive the public host automatically so no one has
# to keep fly.toml env vars in sync with the chosen app name.
FLY_APP = os.environ.get("FLY_APP_NAME")
if FLY_APP:
    _host = f"{FLY_APP}.fly.dev"
    if _host not in ALLOWED_HOSTS:  # noqa: F405
        ALLOWED_HOSTS.append(_host)  # noqa: F405
    if f"https://{_host}" not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(f"https://{_host}")
    SITE_URL = os.environ.get("SITE_URL", f"https://{_host}")

# Email: real SMTP only once EMAIL_HOST is configured; console otherwise so
# signup/notifications never 500 on a demo deploy without a mail provider.
if env("EMAIL_HOST", default=""):  # noqa: F405
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST")  # noqa: F405
    EMAIL_PORT = env.int("EMAIL_PORT", default=587)  # noqa: F405
    EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")  # noqa: F405
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")  # noqa: F405
    EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)  # noqa: F405
    DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="hello@lens.example")  # noqa: F405
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
