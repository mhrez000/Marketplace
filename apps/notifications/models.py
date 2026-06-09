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


class NotificationPreference(TimeStampedModel):
    """Per-user channel opt-outs. Transactional notifications always send; these
    govern reminders, marketing and SMS (build plan §16)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference"
    )
    email_reminders = models.BooleanField(default=True)
    email_marketing = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)
    sms_phone = models.CharField(max_length=32, blank=True)

    def __str__(self):
        return f"Preferences for {self.user}"


def notify(user, verb, url="", icon="bell", email=False):
    """Low-level in-app notification (+ optional branded email). For richer,
    matrix-driven events prefer `dispatch()`."""
    n = Notification.objects.create(user=user, verb=verb, url=url, icon=icon)
    if email and getattr(user, "email", "") and getattr(user, "pk", None):
        from .tasks import send_notification_email
        send_notification_email.delay(user.pk, verb, url)
    return n


def _email_allowed(user, category):
    """Transactional always sends; reminders/marketing respect a user's
    NotificationPreference if one exists (forward-compatible — defaults to on)."""
    from .events import MARKETING, REMINDER
    if category not in (REMINDER, MARKETING):
        return True
    pref = getattr(user, "notification_preference", None)
    if pref is None:
        return True
    if category == REMINDER:
        return getattr(pref, "email_reminders", True)
    return getattr(pref, "email_marketing", False)


def dispatch(event_key, recipient, *, verb, url=""):
    """Send a notification through the channel matrix (apps.notifications.events).
    Creates the in-app record and queues a branded email per the event's channels
    + the recipient's preferences."""
    from .events import event
    from .tasks import send_notification_email

    ev = event(event_key)
    n = Notification.objects.create(user=recipient, verb=verb, url=url, icon=ev["icon"])
    if ("email" in ev["channels"] and getattr(recipient, "email", "")
            and getattr(recipient, "pk", None) and _email_allowed(recipient, ev["category"])):
        send_notification_email.delay(recipient.pk, verb, url,
                                      subject=ev["subject"], cta_label=ev["cta"])
    # "sms" channel is reserved here and wired in a later phase.
    return n


def _send_email(user, verb, url="", subject=None, cta_label="View details"):
    """Send a branded HTML (multipart) transactional email."""
    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives
    from django.template.loader import render_to_string

    brand = getattr(settings, "BRAND_NAME", "Lens")
    site = getattr(settings, "SITE_URL", "")
    cta_url = f"{site}{url}" if url else ""
    heading = subject or verb
    body = verb if subject else ""

    ctx = {"brand": brand, "site_url": site, "first_name": getattr(user, "first_name", ""),
           "heading": heading, "body": body, "cta_url": cta_url, "cta_label": cta_label}
    html = render_to_string("email/notification.html", ctx)
    text_lines = [f"Hi{(' ' + user.first_name) if getattr(user, 'first_name', '') else ''},", "", heading]
    if body:
        text_lines += ["", body]
    if cta_url:
        text_lines += ["", f"{cta_label}: {cta_url}"]
    text_lines += ["", f"— {brand}"]

    msg = EmailMultiAlternatives(
        subject=f"{brand}: {(subject or verb)[:90]}",
        body="\n".join(text_lines), from_email=None, to=[user.email])
    msg.attach_alternative(html, "text/html")
    msg.send(fail_silently=True)
