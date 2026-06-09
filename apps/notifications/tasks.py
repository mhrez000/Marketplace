from celery import shared_task


@shared_task(name="apps.notifications.send_notification_email")
def send_notification_email(user_id, verb, url=""):
    """Send a transactional notification email off the request. Runs inline when
    Celery is in eager mode (no Redis), or on a worker when REDIS_URL is set."""
    from django.contrib.auth import get_user_model

    from .models import _send_email
    user = get_user_model().objects.filter(pk=user_id).first()
    if user and user.email:
        _send_email(user, verb, url)
