"""SMS adapter — inert until SMS_ENABLED + ClickSend credentials are set.

Reserved (per the channel matrix) for money/time-critical events only, and only
for users who opted in + saved a phone number. Uses stdlib urllib so there's no
new dependency; swap ClickSend for Twilio/MessageMedia by editing send_sms().
"""


def send_sms(phone, body):
    from django.conf import settings

    if not getattr(settings, "SMS_ENABLED", False) or not phone:
        return False
    username = getattr(settings, "CLICKSEND_USERNAME", "")
    api_key = getattr(settings, "CLICKSEND_API_KEY", "")
    if not (username and api_key):
        return False

    import base64
    import json
    import urllib.request

    payload = json.dumps({"messages": [{"source": "lens", "body": body[:480], "to": phone}]}).encode()
    req = urllib.request.Request(
        "https://rest.clicksend.com/v3/sms/send", data=payload, method="POST")
    token = base64.b64encode(f"{username}:{api_key}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception:
        return False
