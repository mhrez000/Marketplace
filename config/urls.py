from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.accounts.views import notification_settings
from apps.marketplace.sitemaps import SITEMAPS
from apps.marketplace.views import health, robots_txt
from apps.payments.views import stripe_webhook

urlpatterns = [
    path("healthz", health, name="healthz"),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("settings/notifications/", notification_settings, name="settings_notifications"),
    path("app/", include("apps.dashboard.urls")),
    path("portal/", include("apps.portal.urls")),
    path("messages/", include("apps.messaging.urls")),
    path("api/v1/webhooks/stripe/", stripe_webhook, name="stripe_webhook"),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    path("robots.txt", robots_txt, name="robots"),
    path("", include("apps.marketplace.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Branded admin headers.
admin.site.site_header = f"{settings.BRAND_NAME} — Platform Admin"
admin.site.site_title = f"{settings.BRAND_NAME} Admin"
admin.site.index_title = "Operations"
