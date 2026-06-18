"""Push notifications to mobile devices.

Pluggable and INERT until FCM_SERVER_KEY is configured — the same pattern the app
uses for SMS and Stripe, so everything runs end-to-end without push credentials.
When a key is set, this delivers via Firebase Cloud Messaging (which also relays
to APNs for iOS devices registered through Firebase).

To go live: set FCM_SERVER_KEY (and, for iOS, configure an APNs key in your
Firebase project). The mobile apps register their device token via
POST /api/v1/devices/.
"""
import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

FCM_ENDPOINT = "https://fcm.googleapis.com/fcm/send"


def send_push(user, title, body, url=""):
    """Send a push to every device the user has registered. Returns the count
    actually sent (0 when push isn't configured or the user has no devices)."""
    from django.conf import settings

    key = getattr(settings, "FCM_SERVER_KEY", "")
    if not key:
        return 0
    tokens = list(getattr(user, "device_tokens", []).values_list("token", flat=True)) \
        if hasattr(user, "device_tokens") else []
    if not tokens:
        return 0

    sent = 0
    for token in tokens:
        payload = json.dumps({
            "to": token,
            "notification": {"title": title, "body": body},
            "data": {"url": url},
        }).encode()
        req = urllib.request.Request(
            FCM_ENDPOINT, data=payload,
            headers={"Authorization": f"key={key}", "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
            sent += 1
        except Exception as exc:  # never let a push failure break the request
            logger.warning("push to %s failed: %s", token[:12], exc)
    return sent
