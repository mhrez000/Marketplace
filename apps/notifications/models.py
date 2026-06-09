from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Notification(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    verb = models.CharField(max_length=200)
    url = models.CharField(max_length=300, blank=True)
    icon = models.CharField(max_length=20, default="bell")
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return self.verb


def notify(user, verb, url="", icon="bell", email=False):
    """In-app notification helper. Set email=True for money/time-critical events
    to also send a transactional email (build plan §16 channel matrix). Email
    uses the console backend in dev; Celery/async delivery lands later."""
    n = Notification.objects.create(user=user, verb=verb, url=url, icon=icon)
    if email and getattr(user, "email", ""):
        _send_email(user, verb, url)
    return n


def _send_email(user, verb, url):
    from django.conf import settings
    from django.core.mail import send_mail

    brand = getattr(settings, "BRAND_NAME", "Lens")
    link = f"{getattr(settings, 'SITE_URL', '')}{url}" if url else ""
    body = f"Hi{(' ' + user.first_name) if getattr(user, 'first_name', '') else ''},\n\n{verb}"
    if link:
        body += f"\n\n{link}"
    body += f"\n\n— {brand}"
    send_mail(subject=f"[{brand}] {verb[:80]}", message=body,
              from_email=None, recipient_list=[user.email], fail_silently=True)
