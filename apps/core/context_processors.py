from django.conf import settings


def brand(request):
    """Expose brand constants to every template."""
    return {
        "BRAND_NAME": getattr(settings, "BRAND_NAME", "Lens"),
        "BRAND_TAGLINE": getattr(settings, "BRAND_TAGLINE", ""),
        "SITE_URL": getattr(settings, "SITE_URL", ""),
    }


def notifications(request):
    """Recent notifications + unread count for the dashboard bell."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    qs = user.notifications.all()[:10]
    return {
        "nav_notifications": qs,
        "nav_unread_count": user.notifications.filter(is_read=False).count(),
    }
