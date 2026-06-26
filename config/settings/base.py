"""
Base settings shared across all environments.

Lens — photographer/videographer marketplace + business platform (Australia).
Stack: Django 5 + DRF + HTMX/Alpine + Tailwind. See build plan for context.
"""
from pathlib import Path

import environ

# config/settings/base.py -> config/settings -> config -> PROJECT ROOT
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

# Load .env from the project root if present (never commit .env).
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(str(env_file))

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.sitemaps",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework.authtoken",
    "allauth",
    "allauth.account",
]

# Local apps map 1:1 to chunks of the data model (see build plan §4, §6).
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.workspaces",
    "apps.profiles",
    "apps.enquiries",
    "apps.bookings",
    "apps.contracts",
    "apps.payments",
    "apps.crm",
    "apps.messaging",
    "apps.galleries",
    "apps.reviews",
    "apps.notifications",
    "apps.production",
    "apps.marketplace",
    "apps.dashboard",
    "apps.api",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "apps.core.middleware.HealthCheckMiddleware",  # before host/SSL checks
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",  # no-op unless a CONTENT_SECURITY_POLICY is set
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.brand",
                "apps.core.context_processors.notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------------------
# Database — SQLite by default for local dev (no Docker required).
# Set DATABASE_URL (e.g. postgis://...) to switch to Postgres/PostGIS later.
# ---------------------------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}

# When running on SQLite (incl. the Fly volume demo), give writers a grace
# period instead of failing instantly with "database is locked".
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {})["timeout"] = 20

# Geo search: use PostGIS ST_DWithin when on a PostGIS-enabled Postgres DB,
# else fall back to an in-Python Haversine (apps/marketplace/geo.py). Set to
# True only when DATABASE_URL points at Postgres with the postgis extension.
USE_POSTGIS = env.bool("USE_POSTGIS", default=False)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SITE_ID = 1

# django-allauth — email-based login.
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_UNIQUE_EMAIL = True
LOGIN_REDIRECT_URL = "/app/"
LOGOUT_REDIRECT_URL = "/"

# ---------------------------------------------------------------------------
# Internationalisation — Australia first.
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-au"
TIME_ZONE = "Australia/Melbourne"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",  # mobile apps
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # Rate limiting — brake on brute-force/credential-stuffing and scraping. The
    # auth endpoints get their own tight scopes (set on the views). NOTE: reliable
    # cross-worker throttling needs a shared cache (Redis) in prod — LocMemCache is
    # per-process. Throttles are disabled in test settings.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "240/min",
        "login": "10/min",
        "register": "5/hour",
    },
}

# ---------------------------------------------------------------------------
# Content-Security-Policy (django-csp). Gated behind ENABLE_CSP so it ships dark
# and is rolled out safely; defaults to REPORT-ONLY (observe violations in the
# browser console, break nothing) until CSP_ENFORCE=true. Directives below are
# the verified floor for this app's stack:
#   - script-src needs 'unsafe-eval' because the bundled STANDARD Alpine.js build
#     compiles directives via the AsyncFunction constructor. Dropping it means
#     migrating to @alpinejs/csp + refactoring compound directives (future work).
#   - style-src needs 'unsafe-inline' for data-driven inline styles (e.g. the
#     analytics bar widths) that can't be hashed/nonced. Tailwind is external CSS.
#   - Inline <script> blocks carry a per-request nonce ({{ request.csp_nonce }}).
#   - cdn.jsdelivr.net is whitelisted for FullCalendar (calendar page only).
# ---------------------------------------------------------------------------
ENABLE_CSP = env.bool("ENABLE_CSP", default=False)
CSP_ENFORCE = env.bool("CSP_ENFORCE", default=False)
if ENABLE_CSP:
    from csp.constants import NONCE, NONE, SELF, UNSAFE_EVAL, UNSAFE_INLINE

    _CSP_POLICY = {
        "DIRECTIVES": {
            "default-src": [SELF],
            "script-src": [SELF, NONCE, "https://cdn.jsdelivr.net", UNSAFE_EVAL],
            "style-src": [SELF, UNSAFE_INLINE, "https://fonts.googleapis.com"],
            "font-src": [SELF, "https://fonts.gstatic.com"],
            "img-src": [SELF, "data:"],
            "connect-src": [SELF],
            "frame-ancestors": [NONE],
            "base-uri": [SELF],
            "form-action": [SELF],
            "object-src": [NONE],
        }
    }
    if CSP_ENFORCE:
        CONTENT_SECURITY_POLICY = _CSP_POLICY
    else:
        CONTENT_SECURITY_POLICY_REPORT_ONLY = _CSP_POLICY

# Brand — "Lens" is the working name; rename in one place.
BRAND_NAME = env("BRAND_NAME", default="Lens")
BRAND_TAGLINE = "Find & book Melbourne's best photographers and videographers."

# Absolute base URL for links inside transactional emails.
SITE_URL = env("SITE_URL", default="http://localhost:8000")

# Stripe — when keys are set, the payment gateway switches from the built-in
# TEST gateway to real Stripe automatically (apps/payments/services.get_gateway).
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")

# ---------------------------------------------------------------------------
# Celery — background jobs. With NO REDIS_URL, tasks run inline (eager), so the
# app works exactly as before. Set REDIS_URL to process them on a worker and
# enable the Beat schedule.
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", default="")

# Cache backend. A SHARED cache (Redis) is what makes DRF throttling and allauth's
# login rate-limits hold across gunicorn workers — without it each worker counts
# in its own LocMemCache, weakening the limits. Falls back to LocMemCache when no
# REDIS_URL is set, so dev/test/single-process keeps working unchanged.
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "lens",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "lens-locmem",
        }
    }

CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = REDIS_URL or "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = not bool(REDIS_URL)   # run synchronously without a broker
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "hourly-housekeeping": {
        "task": "apps.core.tasks.run_housekeeping",
        "schedule": 60 * 60,  # every hour
    },
    "daily-message-digest": {
        "task": "apps.notifications.message_digest",
        "schedule": 60 * 60 * 24,  # once a day
    },
}

# SMS (ClickSend) — inert until SMS_ENABLED + credentials are set. Reserved for
# money/time-critical events for users who opted in (build plan §16).
SMS_ENABLED = env.bool("SMS_ENABLED", default=False)
CLICKSEND_USERNAME = env("CLICKSEND_USERNAME", default="")
CLICKSEND_API_KEY = env("CLICKSEND_API_KEY", default="")

# Push notifications (Firebase Cloud Messaging) — inert until a key is set.
# Mobile devices register via POST /api/v1/devices/.
FCM_SERVER_KEY = env("FCM_SERVER_KEY", default="")
