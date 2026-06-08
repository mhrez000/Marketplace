from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("app/", include("apps.dashboard.urls")),
    path("portal/", include("apps.portal.urls")),
    path("", include("apps.marketplace.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Branded admin headers.
admin.site.site_header = f"{settings.BRAND_NAME} — Platform Admin"
admin.site.site_title = f"{settings.BRAND_NAME} Admin"
admin.site.index_title = "Operations"
