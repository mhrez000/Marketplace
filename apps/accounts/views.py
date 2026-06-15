from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


@login_required
def notification_settings(request):
    """Notification preferences — usable by clients and creatives alike."""
    from apps.core.selectors import dashboard_shell
    from apps.notifications.models import NotificationPreference

    pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
    if request.method == "POST":
        pref.email_reminders = "email_reminders" in request.POST
        pref.email_marketing = "email_marketing" in request.POST
        pref.sms_enabled = "sms_enabled" in request.POST
        pref.sms_phone = request.POST.get("sms_phone", "").strip()
        pref.save()
        messages.success(request, "Notification preferences saved.")
        return redirect("settings_notifications")
    ws, base_template = dashboard_shell(request.user)
    return render(request, "settings/notifications.html", {
        "pref": pref, "ws": ws, "active": "settings", "base_template": base_template})
