from celery import shared_task


@shared_task(name="apps.notifications.send_notification_email")
def send_notification_email(user_id, verb, url="", subject=None, cta_label="View details"):
    """Send a branded transactional email off the request. Runs inline when
    Celery is eager (no Redis), or on a worker when REDIS_URL is set."""
    from django.contrib.auth import get_user_model

    from .models import _send_email
    user = get_user_model().objects.filter(pk=user_id).first()
    if user and user.email:
        _send_email(user, verb, url, subject=subject, cta_label=cta_label)


@shared_task(name="apps.notifications.send_sms")
def send_sms_task(phone, body):
    from .sms import send_sms
    return send_sms(phone, body)


@shared_task(name="apps.notifications.send_broadcast")
def send_broadcast(broadcast_id):
    """Deliver a broadcast: an in-app notification to everyone in the audience,
    plus a branded email to those who allow marketing (if send_email is on)."""
    from django.utils import timezone

    from .events import MARKETING
    from .models import Broadcast, Notification, _email_allowed, _send_email, resolve_audience

    b = Broadcast.objects.filter(pk=broadcast_id).first()
    if not b:
        return "missing"
    count = 0
    for u in resolve_audience(b.audience).iterator():
        Notification.objects.create(user=u, verb=b.title, url=b.url, icon="megaphone")
        if b.send_email and getattr(u, "email", "") and _email_allowed(u, MARKETING):
            _send_email(u, b.body, b.url, subject=b.title, cta_label="Learn more")
        count += 1
    b.recipient_count = count
    b.sent_at = timezone.now()
    b.save(update_fields=["recipient_count", "sent_at", "updated_at"])
    return f"{count} recipient(s)"


@shared_task(name="apps.notifications.message_digest")
def message_digest():
    """Daily digest: one email per user with new inbound messages (build plan §16
    — messages are digested, not one-email-per-message). Runs via Celery Beat."""
    from django.contrib.auth import get_user_model

    from apps.messaging.models import Message
    from .models import dispatch

    counts = {}
    for m in Message.objects.filter(read_at__isnull=True).select_related(
            "thread", "thread__workspace"):
        parties = {m.thread.client_id, m.thread.workspace.owner_id}
        recipients = parties - {m.sender_id}
        if len(recipients) == 1:
            rid = recipients.pop()
            counts[rid] = counts.get(rid, 0) + 1

    User = get_user_model()
    sent = 0
    for uid, n in counts.items():
        user = User.objects.filter(pk=uid).first()
        if not user:
            continue
        url = "/app/bookings/" if user.owned_workspaces.exists() else "/portal/"
        dispatch("message_digest", user,
                 verb=f"You have {n} new message{'s' if n != 1 else ''} waiting.", url=url)
        sent += 1
    return f"{sent} digest(s) sent"
