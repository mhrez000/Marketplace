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


class Broadcast(TimeStampedModel):
    """A platform-wide announcement sent by an admin to a target audience as
    in-app notifications (+ optional email, respecting marketing opt-outs)."""

    class Audience(models.TextChoices):
        ALL = "all", "Everyone"
        CREATIVES = "creatives", "Creatives"
        CLIENTS = "clients", "Clients"

    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="broadcasts")
    audience = models.CharField(max_length=12, choices=Audience.choices, default=Audience.ALL)
    title = models.CharField(max_length=160)
    body = models.TextField()
    url = models.CharField(max_length=300, blank=True)
    send_email = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.title} → {self.get_audience_display()}"


def resolve_audience(audience):
    """Users a broadcast should reach (active, non-admin)."""
    from django.contrib.auth import get_user_model
    qs = get_user_model().objects.filter(is_active=True, is_superuser=False)
    if audience == Broadcast.Audience.CREATIVES:
        return qs.filter(owned_workspaces__isnull=False).distinct()
    if audience == Broadcast.Audience.CLIENTS:
        return qs.filter(owned_workspaces__isnull=True).distinct()
    return qs.distinct()


class DeviceToken(TimeStampedModel):
    """A mobile device registered to receive push notifications."""

    class Platform(models.TextChoices):
        ANDROID = "android", "Android"
        IOS = "ios", "iOS"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_tokens")
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=10, choices=Platform.choices, default=Platform.ANDROID)

    def __str__(self):
        return f"{self.platform} device for {self.user}"


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
    _push(user, verb, url)
    if email and getattr(user, "email", "") and getattr(user, "pk", None):
        from .tasks import send_notification_email
        send_notification_email.delay(user.pk, verb, url)
    return n


def _push(user, verb, url):
    """Fan a notification out to the user's mobile devices (inert without keys)."""
    try:
        from django.conf import settings

        from .push import send_push
        send_push(user, getattr(settings, "BRAND_NAME", "Lens"), verb, url)
    except Exception:
        pass


def _email_allowed(user, category):
    """Transactional always sends; reminders/marketing respect a user's
    NotificationPreference if one exists (forward-compatible — defaults to on)."""
    from .events import MARKETING, REMINDER
    if category not in (REMINDER, MARKETING):
        return True  # transactional + digest always send
    pref = getattr(user, "notification_preference", None)
    if pref is None:
        # No preferences set yet: reminders default ON, marketing default OFF (opt-in).
        return category == REMINDER
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
    _push(recipient, verb, url)
    if ("email" in ev["channels"] and getattr(recipient, "email", "")
            and getattr(recipient, "pk", None) and _email_allowed(recipient, ev["category"])):
        send_notification_email.delay(recipient.pk, verb, url,
                                      subject=ev["subject"], cta_label=ev["cta"])

    # SMS — only for urgent events, and only if the user opted in with a phone.
    if "sms" in ev["channels"]:
        pref = getattr(recipient, "notification_preference", None)
        if pref and pref.sms_enabled and pref.sms_phone:
            from django.conf import settings
            from .tasks import send_sms_task
            send_sms_task.delay(pref.sms_phone, f"{getattr(settings, 'BRAND_NAME', 'Lens')}: {verb}")
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
