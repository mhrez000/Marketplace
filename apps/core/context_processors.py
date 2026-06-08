from django.conf import settings


def brand(request):
    """Expose brand constants to every template."""
    return {
        "BRAND_NAME": getattr(settings, "BRAND_NAME", "Lens"),
        "BRAND_TAGLINE": getattr(settings, "BRAND_TAGLINE", ""),
    }
