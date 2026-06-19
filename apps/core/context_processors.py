from django.conf import settings


def brand(request):
    """Expose brand constants to every template."""
    return {
        "BRAND_NAME": getattr(settings, "BRAND_NAME", "Lens"),
        "BRAND_TAGLINE": getattr(settings, "BRAND_TAGLINE", ""),
        "SITE_URL": getattr(settings, "SITE_URL", ""),
    }


def notifications(request):
    """Recent notifications + unread counts for the header bell & Messages link."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from django.db.models import Q
    from apps.messaging.models import Message
    unread_messages = (Message.objects.filter(read_at__isnull=True)
                       .filter(Q(thread__client=user) | Q(thread__workspace__owner=user))
                       .exclude(sender=user).count())
    from apps.bookings.models import BookingCollaborator
    pending_collabs = BookingCollaborator.objects.filter(
        workspace__owner=user, status=BookingCollaborator.Status.INVITED).count()
    return {
        "nav_notifications": user.notifications.all()[:10],
        "nav_unread_count": user.notifications.filter(is_read=False).count(),
        "nav_unread_messages": unread_messages,
        "nav_pending_collabs": pending_collabs,
    }
